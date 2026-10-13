package com.optionsaitrader.options_ai_trader

import okhttp3.*
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.ByteString
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

class AlpacaSessionTest {
    private class SocketFactory:WebSocket.Factory {
        lateinit var listener:WebSocketListener
        lateinit var socket:FakeSocket
        val opened=CountDownLatch(1)
        @Volatile var count=0
        val all=CopyOnWriteArrayList<FakeSocket>()
        val openedAt=CopyOnWriteArrayList<Long>()
        @Volatile var maxLive=0
        override fun newWebSocket(request:Request,listener:WebSocketListener):WebSocket {
            this.listener=listener;socket=FakeSocket(request,listener);count++;all.add(socket);openedAt.add(System.nanoTime()/1_000_000)
            maxLive=maxOf(maxLive,all.count{!it.cancelled&&!it.closed})
            listener.onOpen(socket,Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(101).message("mock").build())
            opened.countDown();return socket
        }
    }
    private class FakeSocket(private val req:Request,val listener:WebSocketListener):WebSocket {
        val sent=CopyOnWriteArrayList<String>();@Volatile var cancelled=false;@Volatile var closed=false;@Volatile var closes=0
        fun confirmClose(){closed=true;listener.onClosed(this,1000,"mock close")}
        fun fail(){cancelled=true;listener.onFailure(this,java.io.IOException("private provider text"),null)}
        override fun request()=req
        override fun queueSize()=0L
        override fun send(text:String):Boolean{sent.add(text);return true}
        override fun send(bytes:ByteString)=false
        override fun close(code:Int,reason:String?):Boolean{closes++;return true}
        override fun cancel(){cancelled=true}
    }
    private class Harness(val httpCode:Int=200,val networkFailure:java.io.IOException?=null,val authTimeout:Long=12000,val fast:Boolean=false,val httpGate:CountDownLatch?=null):AutoCloseable {
        val clock=AtomicLong(Instant.parse("2026-10-13T15:01:15Z").toEpochMilli())
        val sockets=SocketFactory();val requests=CopyOnWriteArrayList<Request>()
        val session=AlpacaSession({Pair("mock-key-only","mock-secret-only")},clock::get,
            OkHttpClient.Builder().addInterceptor { chain ->
                requests.add(chain.request())
                httpGate?.await(3,TimeUnit.SECONDS)
                networkFailure?.let{throw it}
                val body=if(chain.request().url.encodedPath.contains("options"))
                    """{"snapshots":{"NVDA261016C00200000":{"latestQuote":{"t":"2026-10-13T15:01:15Z","bp":2,"ap":2.1,"bs":10,"as":10}}}}"""
                else """{"bars":{"NVDA":[{"t":"2026-10-13T15:00:00Z","o":100,"h":102,"l":99,"c":101,"v":10}]}}"""
                Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(httpCode).message("mock")
                    .header("Retry-After","600").body(body.toResponseBody()).build()
            }.build(),sockets,authTimeout,
            retryDelay={if(fast)40L*(it+1) else AlpacaPolicy.retryMs(it)},
            limitDelay={if(fast)80L shl minOf(it,3) else minOf(120000L,15000L shl minOf(it,3))},
            closeGraceMs=if(fast)30L else 2000L,releasePauseMs=if(fast)10L else 1000L)
        fun start(){session.start("iex","regular",listOf("NVDA"));assertTrue(sockets.opened.await(3,TimeUnit.SECONDS))}
        fun send(text:String){sockets.listener.onMessage(sockets.socket,text)}
        fun auth(){send("""[{"T":"success","msg":"authenticated"}]""")}
        fun view()=JSONObject(session.snapshot())
        fun await(check:()->Boolean){val end=System.nanoTime()+TimeUnit.SECONDS.toNanos(4);while(!check()&&System.nanoTime()<end)Thread.sleep(10);assertTrue(check())}
        override fun close(){session.close()}
    }
    @Test fun authIsRequiredAndSecretNeverInSnapshot(){Harness().use {h->
        h.start();assertFalse(h.view().getBoolean("connected"));h.await{h.sockets.socket.sent.isNotEmpty()}
        assertEquals("auth",JSONObject(h.sockets.socket.sent.first()).getString("action"))
        h.auth();h.await{h.requests.size==1};h.await{h.view().getJSONObject("bars").has("NVDA")}
        assertTrue(h.view().getBoolean("connected"));assertFalse(h.session.snapshot().contains("mock-secret"))
        assertEquals("GET",h.requests.first().method)
        assertEquals("data.alpaca.markets",h.requests.first().url.host)
        assertEquals("iex",h.requests.first().url.queryParameter("feed"))
    }}
    @Test fun correctedBarReplacesRatherThanDuplicatesAndFutureIsRejected(){Harness().use {h->
        h.start();h.auth();h.await{h.view().getJSONObject("bars").has("NVDA")}
        h.send("""[{"T":"u","S":"NVDA","t":"2026-10-13T15:00:00Z","o":100,"h":103,"l":99,"c":102,"v":20},{"T":"b","S":"NVDA","t":"2026-10-13T15:02:00Z","o":100,"h":103,"l":99,"c":102,"v":20}]""")
        h.await{h.view().getJSONObject("bars").getJSONArray("NVDA").getJSONObject(0).getDouble("c")==102.0}
        assertEquals(1,h.view().getJSONObject("bars").getJSONArray("NVDA").length())
    }}
    @Test fun conflictClosesOnlyOwnedSocketAndWaitsWithoutBlamingAnotherApp(){Harness().use {h->
        h.start();h.send("""[{"T":"error","code":406,"msg":"private provider text"}]""")
        h.await{h.view().getString("state")=="RETRY_WAIT"};assertTrue(h.session.enabled)
        assertEquals("CONNECTION_LIMIT",h.view().getString("reason"));assertTrue(h.sockets.socket.closes>0)
        assertTrue(h.view().getLong("retryAt")>=h.clock.get()+14000)
        repeat(20){h.session.start("iex","regular",listOf("NVDA"))};assertEquals(1,h.sockets.count)
        assertFalse(h.session.snapshot().contains("private provider"));assertEquals(0,h.requests.size)
    }}
    @Test fun staleSocketAfterStopCannotAuthenticate(){Harness().use {h->h.start();h.session.stop();h.auth();Thread.sleep(50);assertFalse(h.view().getBoolean("connected"));assertEquals(0,h.requests.size)}}
    @Test fun authRejectionLocks(){Harness().use {h->h.start();h.send("""[{"T":"error","code":402}]""");h.await{!h.session.enabled};assertFalse(h.view().getBoolean("connected"))}}
    @Test fun rateLimitSurvivesManualRestart(){Harness(429).use {h->h.start();h.auth();h.await{h.view().getLong("retryAt")>h.clock.get()};val until=h.view().getLong("retryAt");h.session.stop();h.session.start("iex","regular",listOf("NVDA"));assertEquals(until,h.view().getLong("retryAt"));assertEquals("HTTP_429",h.view().getString("testCode"));assertEquals("RETRY_WAIT",h.view().getString("state"));assertEquals(1,h.requests.size)}}
    @Test fun disconnectedTransportStopsFreshnessAndSchedulesRecovery(){Harness().use {h->h.start();h.auth();h.await{h.view().getBoolean("connected")};h.sockets.listener.onFailure(h.sockets.socket,java.io.IOException("secret provider URL"),null);h.await{!h.view().getBoolean("connected")};assertTrue(h.session.enabled);assertFalse(h.session.snapshot().contains("secret provider"))}}
    @Test fun optionsAreExplicitOpraGetOnly(){Harness().use {h->h.start();h.auth();h.await{h.requests.size==1};h.clock.addAndGet(5000);val done=CountDownLatch(1);var answer:String?=null;h.session.quote("NVDA261016C00200000"){answer=it;done.countDown()};assertTrue(done.await(3,TimeUnit.SECONDS));assertEquals("opra",JSONObject(answer!!).getString("feed"));assertEquals("opra",h.requests.last().url.queryParameter("feed"));assertEquals("GET",h.requests.last().method)}}
    @Test fun optionsForbiddenDoesNotBecomeIndicative(){Harness(403).use {h->h.start();h.auth();h.await{h.requests.size==1};h.clock.addAndGet(5000);val done=CountDownLatch(1);var answer:String?="sentinel";h.session.quote("NVDA261016C00200000"){answer=it;done.countDown()};assertTrue(done.await(3,TimeUnit.SECONDS));assertNull(answer)}}
    @Test fun reconnectionRequiresNewAuthentication(){Harness().use {h->h.start();h.auth();h.await{h.view().getBoolean("connected")};h.sockets.listener.onFailure(h.sockets.socket,java.io.IOException(),null);h.await{!h.view().getBoolean("connected")};Thread.sleep(5200);h.await{h.sockets.count==2};assertFalse(h.view().getBoolean("connected"));h.auth();h.await{h.view().getBoolean("connected")}}}
    @Test fun dataClientRejectsOrderBeforeNetwork(){val client=AlpacaSession.client();try {
        for(method in listOf("GET","DELETE"))try{client.newCall(Request.Builder().url("https://data.alpaca.markets/v2/orders").method(method,null).build()).execute();fail("order permitted")}catch(_:java.io.IOException){}
    }finally{client.dispatcher.executorService.shutdownNow();client.connectionPool.evictAll()}}
    @Test fun successfulTestIncludesAuthenticatedReadOnlyHttpData(){Harness().use{h->h.start();h.auth();h.await{h.view().getString("testStatus")=="succeeded"};assertEquals("CONNECTED_DATA",h.view().getString("testCode"));assertTrue(h.requests.all{it.method=="GET"})}}
    @Test fun http401IsVisibleAndStopsSession(){Harness(401).use{h->h.start();h.auth();h.await{h.view().getString("testCode")=="HTTP_401"};assertFalse(h.session.enabled);assertEquals("failed",h.view().getString("testStatus"))}}
    @Test fun http403IsVisibleAndStopsSession(){Harness(403).use{h->h.start();h.auth();h.await{h.view().getString("testCode")=="HTTP_403"};assertFalse(h.session.enabled)}}
    @Test fun rateLimitIsNotOverwrittenByGenericHistoryError(){Harness(429).use{h->h.start();h.auth();h.await{h.view().getString("testCode")=="HTTP_429"};assertEquals("HTTP_429",h.view().getString("reason"));assertTrue(h.view().getLong("retryAt")>h.clock.get())}}
    @Test fun timeoutIsVisibleWithoutExceptionText(){Harness(networkFailure=java.net.SocketTimeoutException("mock-private-value")).use{h->h.start();h.auth();h.await{h.view().getString("testCode")=="TIMEOUT"};assertFalse(h.session.snapshot().contains("mock-private-value"))}}
    @Test fun networkFailureIsVisibleWithoutUrlOrSecret(){Harness(networkFailure=java.net.UnknownHostException("mock-private-value")).use{h->h.start();h.auth();h.await{h.view().getString("testCode")=="NETWORK_ERROR"};assertFalse(h.session.snapshot().contains("mock-private-value"))}}
    @Test fun missingAuthenticationTimesOutWithVisibleResult(){Harness(authTimeout=100).use{h->h.start();h.await{h.view().getString("testCode")=="AUTH_TIMEOUT"};assertEquals("failed",h.view().getString("testStatus"));assertEquals(0,h.requests.size)}}
    @Test fun websocket403IsDistinctFromHttpEntitlement(){Harness().use{h->h.start();h.send("""[{"T":"error","code":403,"msg":"private response"}]""");h.await{!h.session.enabled};assertEquals("WS_ERROR_403",h.view().getString("testCode"));assertFalse(h.session.snapshot().contains("private response"))}}


    @Test fun concurrentConsumersShareOneAuthenticatedSocket(){Harness(fast=true).use{h->
        val ready=CountDownLatch(12);val go=CountDownLatch(1)
        val threads=(1..12).map{Thread{ready.countDown();go.await();h.session.start("iex","regular",listOf("NVDA"))}.apply{start()}}
        assertTrue(ready.await(2,TimeUnit.SECONDS));go.countDown();threads.forEach{it.join()}
        h.await{h.sockets.count==1};h.await{h.sockets.socket.sent.isNotEmpty()};h.auth();h.await{h.view().getBoolean("connected")}
        repeat(10){h.session.start("iex","regular",listOf("NVDA"))}
        assertEquals(1,h.sockets.count);assertEquals(1,h.sockets.socket.sent.count{JSONObject(it).getString("action")=="auth"})
    }}
    @Test fun rapidReconfigureWaitsForOldCloseAndOpensOnlyLatestConfiguration(){Harness().use{h->
        h.start();val old=h.sockets.socket
        h.session.start("iex","regular",listOf("AAPL"));h.session.start("sip","extended",listOf("TSLA"))
        Thread.sleep(50);assertEquals(1,h.sockets.count);assertTrue(old.closes>0)
        old.confirmClose();h.await{h.sockets.count==2}
        assertEquals("/v2/sip",h.sockets.socket.request().url.encodedPath);assertEquals(1,h.sockets.maxLive)
        old.listener.onMessage(old,"""[{"T":"success","msg":"authenticated"}]""")
        Thread.sleep(30);assertFalse(h.view().getBoolean("connected"));assertEquals(0,h.requests.size)
    }}
    @Test fun missingCloseAcknowledgmentCancelsBeforeReplacement(){Harness(fast=true).use{h->
        h.start();val old=h.sockets.socket;h.session.stop();h.session.start("iex","regular",listOf("NVDA"))
        h.await{h.sockets.count==2};assertTrue(old.cancelled);assertEquals(1,h.sockets.maxLive)
    }}
    @Test fun repeated406HasProgressiveBoundedRecoveryAndManualStartCannotSkipCooldown(){Harness(fast=true).use{h->
        h.start()
        repeat(4){i->h.send("""[{"T":"error","code":406}]""");if(i<3)h.await{h.sockets.count==i+2} else h.await{!h.session.enabled}}
        assertEquals("CONNECTION_LIMIT_EXHAUSTED",h.view().getString("lastError"));assertEquals(4,h.sockets.count)
        val gaps=h.sockets.openedAt.zipWithNext{a,b->b-a}
        assertTrue(gaps[0]>=70);assertTrue(gaps[1]>=150);assertTrue(gaps[2]>=310);assertEquals(1,h.sockets.maxLive)
        repeat(10){h.session.start("iex","regular",listOf("NVDA"))};Thread.sleep(30);assertEquals(4,h.sockets.count)
        assertEquals("CONNECTION_LIMIT",h.view().getString("testCode"));assertEquals("RETRY_WAIT",h.view().getString("state"))
    }}
    @Test fun screenOffPausesAndReturnResumesOnlyExistingConsent(){Harness(fast=true).use{h->
        h.session.foreground();assertEquals(0,h.sockets.count)
        h.start();h.auth();h.await{h.view().getJSONObject("bars").has("NVDA")}
        h.session.background(false);assertFalse(h.view().getBoolean("connected"));assertEquals("PAUSED_BACKGROUND",h.view().getString("state"))
        assertEquals(1,h.view().getJSONObject("bars").getJSONArray("NVDA").length())
        h.session.foreground();h.session.foreground();h.await{h.sockets.count==2};assertFalse(h.view().getBoolean("connected"))
        h.auth();h.await{h.view().getBoolean("connected")};assertEquals(1,h.sockets.maxLive)
        h.session.stop();h.session.foreground();Thread.sleep(50);assertEquals(2,h.sockets.count)
    }}
    @Test fun optedInForegroundMonitorKeepsSameSocketAcrossScreenOff(){Harness(fast=true).use{h->
        h.start();h.auth();h.await{h.view().getBoolean("connected")};h.session.background(true);h.session.foreground()
        assertTrue(h.view().getBoolean("connected"));assertEquals(1,h.sockets.count)
    }}
    @Test fun networkLossRecoversOneSocketAndRequiresNewAuthentication(){Harness(fast=true).use{h->
        h.start();h.auth();h.await{h.view().getBoolean("connected")};h.sockets.socket.fail()
        h.await{h.view().getString("state")=="RETRY_WAIT"};assertFalse(h.view().getBoolean("connected"))
        h.await{h.sockets.count==2};assertFalse(h.view().getBoolean("connected"));h.auth();h.await{h.view().getBoolean("connected")}
        assertEquals(1,h.sockets.maxLive);assertEquals("NETWORK_ERROR",h.view().getString("lastError"))
    }}
    @Test fun slowRestNeverBlocksWebSocketBarCallbacks(){val gate=CountDownLatch(1);Harness(fast=true,httpGate=gate).use{h->
        try{h.start();h.auth();h.await{h.requests.size==1};val began=System.nanoTime()
            h.send("""[{"T":"b","S":"NVDA","t":"2026-10-13T15:00:00Z","o":200,"h":202,"l":199,"c":201,"v":20}]""")
            h.await{h.view().getJSONObject("bars").has("NVDA")};assertTrue((System.nanoTime()-began)/1_000_000<1000);assertEquals(201.0,h.view().getJSONObject("bars").getJSONArray("NVDA").getJSONObject(0).getDouble("c"),0.0)
            assertTrue(h.view().getLong("lastMessageAt")>0);assertTrue(h.view().getLong("lastBarAt")>0)
        }finally{gate.countDown()}
    }}
    @Test fun staleHttpFailureCannotStopReplacementSession(){val gate=CountDownLatch(1);Harness(401,fast=true,httpGate=gate).use{h->
        try{h.start();h.auth();h.await{h.requests.size==1};h.session.stop();h.session.start("iex","regular",listOf("NVDA"));h.await{h.sockets.count==2}
            gate.countDown();Thread.sleep(100);assertTrue(h.session.enabled);assertFalse(h.view().getBoolean("connected"))
        }finally{gate.countDown()}
    }}
    @Test fun oldServiceOwnerCannotStopNewSession(){Harness(fast=true).use{h->
        h.start();val owner=h.session.ownerVersion;h.session.stop();h.session.start("iex","regular",listOf("NVDA"));h.await{h.sockets.count==2}
        h.session.stopIfOwner(owner);assertTrue(h.session.enabled);h.session.stopIfOwner(h.session.ownerVersion);assertFalse(h.session.enabled)
    }}
}
