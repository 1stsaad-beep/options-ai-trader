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
        override fun newWebSocket(request:Request,listener:WebSocketListener):WebSocket {
            this.listener=listener;socket=FakeSocket(request)
            listener.onOpen(socket,Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(101).message("mock").build())
            opened.countDown();return socket
        }
    }
    private class FakeSocket(private val req:Request):WebSocket {
        val sent=CopyOnWriteArrayList<String>();var cancelled=false
        override fun request()=req
        override fun queueSize()=0L
        override fun send(text:String):Boolean{sent.add(text);return true}
        override fun send(bytes:ByteString)=false
        override fun close(code:Int,reason:String?)=true
        override fun cancel(){cancelled=true}
    }
    private class Harness(val httpCode:Int=200):AutoCloseable {
        val clock=AtomicLong(Instant.parse("2026-10-13T15:01:15Z").toEpochMilli())
        val sockets=SocketFactory();val requests=CopyOnWriteArrayList<Request>()
        val session=AlpacaSession({Pair("mock-key-only","mock-secret-only")},clock::get,
            OkHttpClient.Builder().addInterceptor { chain ->
                requests.add(chain.request())
                val body=if(chain.request().url.encodedPath.contains("options"))
                    """{"snapshots":{"NVDA261016C00200000":{"latestQuote":{"t":"2026-10-13T15:01:15Z","bp":2,"ap":2.1,"bs":10,"as":10}}}}"""
                else """{"bars":{"NVDA":[{"t":"2026-10-13T15:00:00Z","o":100,"h":102,"l":99,"c":101,"v":10}]}}"""
                Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(httpCode).message("mock")
                    .header("Retry-After","600").body(body.toResponseBody()).build()
            }.build(),sockets)
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
    @Test fun conflictDoesNotDisplaceOtherApp(){Harness().use {h->h.start();h.send("""[{"T":"error","code":406,"msg":"private provider text"}]""");h.await{!h.session.enabled};assertEquals("OTHER_APP_CONNECTION_LIMIT",h.view().getString("reason"));assertFalse(h.session.snapshot().contains("private provider"));assertEquals(0,h.requests.size)}}
    @Test fun staleSocketAfterStopCannotAuthenticate(){Harness().use {h->h.start();h.session.stop();h.auth();Thread.sleep(50);assertFalse(h.view().getBoolean("connected"));assertEquals(0,h.requests.size)}}
    @Test fun authRejectionLocks(){Harness().use {h->h.start();h.send("""[{"T":"error","code":402}]""");h.await{!h.session.enabled};assertFalse(h.view().getBoolean("connected"))}}
    @Test fun rateLimitSurvivesManualRestart(){Harness(429).use {h->h.start();h.auth();h.await{h.view().getLong("retryAt")>h.clock.get()};val until=h.view().getLong("retryAt");h.session.stop();h.session.start("iex","regular",listOf("NVDA"));assertEquals(until,h.view().getLong("retryAt"));assertEquals(1,h.requests.size)}}
    @Test fun disconnectedTransportStopsFreshnessAndSchedulesRecovery(){Harness().use {h->h.start();h.auth();h.await{h.view().getBoolean("connected")};h.sockets.listener.onFailure(h.sockets.socket,java.io.IOException("secret provider URL"),null);h.await{!h.view().getBoolean("connected")};assertTrue(h.session.enabled);assertFalse(h.session.snapshot().contains("secret provider"))}}
    @Test fun optionsAreExplicitOpraGetOnly(){Harness().use {h->h.start();h.auth();h.await{h.requests.size==1};h.clock.addAndGet(5000);val done=CountDownLatch(1);var answer:String?=null;h.session.quote("NVDA261016C00200000"){answer=it;done.countDown()};assertTrue(done.await(3,TimeUnit.SECONDS));assertEquals("opra",JSONObject(answer!!).getString("feed"));assertEquals("opra",h.requests.last().url.queryParameter("feed"));assertEquals("GET",h.requests.last().method)}}
    @Test fun optionsForbiddenDoesNotBecomeIndicative(){Harness(403).use {h->h.start();h.auth();h.await{h.requests.size==1};h.clock.addAndGet(5000);val done=CountDownLatch(1);var answer:String?="sentinel";h.session.quote("NVDA261016C00200000"){answer=it;done.countDown()};assertTrue(done.await(3,TimeUnit.SECONDS));assertNull(answer)}}
}
