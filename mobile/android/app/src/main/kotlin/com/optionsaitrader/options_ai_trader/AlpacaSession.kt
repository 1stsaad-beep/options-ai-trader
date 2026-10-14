package com.optionsaitrader.options_ai_trader

import okhttp3.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.io.InterruptedIOException
import javax.net.ssl.SSLException
import java.time.Instant
import java.util.TreeMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.RejectedExecutionException

/** One stream shared by all local accounts. Credentials never enter snapshots/errors/logs. */
internal class AlpacaSession(
    private val credentials: () -> Pair<String,String>,
    private val now: () -> Long = System::currentTimeMillis,
    private val transport: OkHttpClient = client(),
    private val sockets: WebSocket.Factory = transport,
    private val authTimeoutMs:Long = 12000L,
    private val retryDelay:(Int)->Long = {AlpacaPolicy.retryMs(it)},
    private val limitDelay:(Int)->Long = {minOf(120000L,15000L shl minOf(it,3))},
    private val closeGraceMs:Long = 2000L,
    private val releasePauseMs:Long = 1000L
) {
    companion object {
        fun client()=OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
            .retryOnConnectionFailure(false).connectTimeout(10,TimeUnit.SECONDS)
            .readTimeout(15,TimeUnit.SECONDS).callTimeout(20,TimeUnit.SECONDS).pingInterval(20,TimeUnit.SECONDS)
            .addInterceptor { chain ->
                if(!AlpacaPolicy.permits(chain.request().method,chain.request().url.toString())) throw IOException("DATA_ONLY")
                chain.proceed(chain.request())
            }.build()
    }
    private val worker=Executors.newSingleThreadScheduledExecutor()
    // Slow REST calls must not delay WebSocket authentication, close callbacks or recovery.
    private val http=Executors.newSingleThreadScheduledExecutor()
    private val calls=ConcurrentHashMap<Call,Int>()
    private var connecting:ScheduledFuture<*>?=null
    private var retiring:WebSocket?=null
    private var openAfter=0L
    private var releasedAfter=0L
    private var limitUntil=0L
    private var conflicts=0
    private var resumePending=false
    private var connectionState="IDLE"
    private var connectionsCreated=0
    private var lastMessageAt=0L
    private var lastBarAt=0L
    private var lastError=""
    private var lastErrorAt=0L
    private var retryAt=0L
    private fun elapsed()=System.nanoTime()/1_000_000L
    private fun dispatch(action:()->Unit){try{worker.execute(action)}catch(_:RejectedExecutionException){}}
    @Synchronized private fun retire() {
        val old=socket?:return
        socket=null;retiring=old
        if(!old.close(1000,"session ended")){old.cancel();released(old);return}
        worker.schedule({synchronized(this){if(retiring===old){old.cancel();released(old)}}},closeGraceMs,TimeUnit.MILLISECONDS)
    }
    @Synchronized private fun released(ws:WebSocket){
        if(retiring!==ws)return
        retiring=null;releasedAfter=elapsed()+releasePauseMs
        if(enabled)queueConnect(generation)
    }
    @Synchronized private fun queueConnect(g:Int){
        if(!current(g)||socket!=null)return
        connecting?.cancel(false)
        val wait=maxOf(0L,openAfter-elapsed(),releasedAfter-elapsed(),blockedUntil-now(),limitUntil-elapsed(),if(retiring!=null)closeGraceMs else 0L)
        retryAt=if(wait>0)now()+wait else 0L
        if(wait>0){
            connectionState="RETRY_WAIT"
            // A manual Test during provider cooldown must report the wait, not run into the UI test timeout.
            val code=if(now()<blockedUntil)"HTTP_429" else if(elapsed()<limitUntil)"CONNECTION_LIMIT" else null
            if(code!=null){event(code);testResult("failed",code)}
        }
        connecting=worker.schedule({connect(g)},wait,TimeUnit.MILLISECONDS)
    }
    private val bars=mutableMapOf<String,TreeMap<Long,JSONObject>>()
    private val events=ArrayDeque<JSONObject>()
    @Volatile private var generation=0
    @Volatile var enabled=false; private set
    @Volatile var ownerVersion=0; private set
    @Volatile private var authenticated=false
    @Volatile private var socket: WebSocket?=null
    private var feed="iex"
    private var session="regular"
    private var symbols=listOf<String>()
    @Volatile private var reason="DISABLED"
    private var attempts=0
    @Volatile private var blockedUntil=0L
    @Volatile private var nextRequest=0L

    private var testStatus="idle"
    private var testCode="NOT_TESTED"
    private var testAt=0L
    private class DataFailure(val safeCode:String):IOException(safeCode)
    private fun failure(t:Throwable)=when(t){
        is DataFailure->t.safeCode
        is InterruptedIOException->"TIMEOUT"
        is SSLException->"TLS_ERROR"
        is IOException->"NETWORK_ERROR"
        else->"INVALID_DATA"
    }
    @Synchronized private fun testResult(status:String,code:String){testStatus=status;testCode=code;testAt=now()}
    private fun rateLimit(response:Response){
        val seconds=response.header("Retry-After")?.toLongOrNull()
        val reset=response.header("X-RateLimit-Reset")?.toLongOrNull()?.times(1000)
        blockedUntil=maxOf(now()+maxOf(60L,seconds?:60L)*1000,reset?:0)
    }

    @Synchronized private fun event(code:String) {
        reason=code
        if(code.startsWith("HTTP_")||code.startsWith("WS_ERROR_")||code in listOf("CONNECTION_LIMIT","CONNECTION_LIMIT_EXHAUSTED","NETWORK_ERROR","TIMEOUT","TLS_ERROR","AUTH_TIMEOUT","DISCONNECTED","RETRY_EXHAUSTED","INVALID_DATA","KEYSTORE_UNAVAILABLE")){
            lastError=code;lastErrorAt=now()
        }
        events.addLast(JSONObject().put("at",now()).put("code",code))
        while(events.size>100)events.removeFirst()
    }
    @Synchronized fun start(selectedFeed:String,selectedSession:String,watch:List<String>) {
        require(AlpacaPolicy.feed(selectedFeed) && selectedSession in listOf("regular","extended"))
        require(watch.size in 1..10 && watch.distinct().size==watch.size && watch.all { AlpacaPolicy.symbol(it) })
        val same=feed==selectedFeed&&session==selectedSession&&symbols==watch
        if(enabled&&same)return // Navigation/repeated Test never makes a second socket.
        stop("RECONFIGURED")
        if(!same){bars.clear();lastBarAt=0}
        feed=selectedFeed;session=selectedSession;symbols=watch.toList()
        attempts=0
        if(elapsed()>=limitUntil)conflicts=0
        enabled=true;connectionState="CONNECTING";event("CONNECTING");testResult("running","CONNECTING")
        queueConnect(generation)
    }
    @Synchronized fun stop(code:String="DISABLED") {
        ownerVersion++;generation++;enabled=false;resumePending=false;authenticated=false;connecting?.cancel(false);connecting=null
        for(call in calls.keys)call.cancel()
        retire();connectionState=if(code in listOf("DISABLED","RECONFIGURED"))"IDLE" else "ERROR";event(code)
        if(code !in listOf("DISABLED","RECONFIGURED","PAUSED_BACKGROUND"))testResult("failed",code)
        else if(testStatus=="running")testResult("cancelled","STOPPED")
    }
    @Synchronized fun stopIfOwner(owner:Int){if(ownerVersion==owner)stop()}
    @Synchronized fun background(monitoring:Boolean) {
        if(monitoring||!enabled)return
        stop("PAUSED_BACKGROUND");resumePending=true;connectionState="PAUSED_BACKGROUND"
    }
    @Synchronized fun foreground(){
        // In-memory consent resumes only a previously running session, never a cold launch or explicit Stop.
        if(!resumePending)return
        resumePending=false;enabled=true;connectionState="CONNECTING";event("RESUMING")
        testResult("running","CONNECTING");queueConnect(generation)
    }
    private fun current(g:Int)=enabled && g==generation
    @Synchronized private fun connect(g:Int) {
        if(!current(g)||socket!=null)return
        if(retiring!=null||elapsed()<maxOf(openAfter,releasedAfter,limitUntil)||now()<blockedUntil){queueConnect(g);return}
        connecting=null;retryAt=0;connectionState="CONNECTING"
        try {
            val request=Request.Builder().url("https://stream.data.alpaca.markets/v2/$feed").get().build()
            // Creation and generation validation share the same lock as Stop and Start.
            socket=sockets.newWebSocket(request,object:WebSocketListener(){
                override fun onOpen(ws:WebSocket,response:Response) { dispatch {
                    synchronized(this@AlpacaSession){
                        if(!current(g)||socket!==ws)return@dispatch
                        try {connectionState="AUTHENTICATING";val pair=credentials()
                            if(!ws.send(JSONObject().put("action","auth").put("key",pair.first).put("secret",pair.second).toString()))retry(g,"DISCONNECTED")
                        }catch(_:Exception){stop("KEYSTORE_UNAVAILABLE")}
                    }
                } }
                override fun onMessage(ws:WebSocket,text:String) { dispatch {
                    synchronized(this@AlpacaSession){if(current(g)&&socket===ws)try{receive(g,text)}catch(_:Exception){retry(g,"INVALID_DATA")}}
                } }
                override fun onFailure(ws:WebSocket,t:Throwable,response:Response?) { dispatch {
                    synchronized(this@AlpacaSession){
                        released(ws)
                        if(current(g)&&socket===ws){
                            socket=null;releasedAfter=elapsed()+releasePauseMs
                            val code=response?.code?:0
                            if(code==429){response?.let{rateLimit(it)};retry(g,"HTTP_429",blockedUntil-now())}
                            else if(code==406)retry(g,"CONNECTION_LIMIT")
                            else if(AlpacaPolicy.terminal(code))stop("HTTP_$code") else retry(g,failure(t))
                        }
                    }
                } }
                override fun onClosed(ws:WebSocket,code:Int,reason:String) { dispatch {
                    synchronized(this@AlpacaSession){released(ws);if(current(g)&&socket===ws){socket=null;releasedAfter=elapsed()+releasePauseMs;retry(g,"DISCONNECTED")}}
                } }
                override fun onClosing(ws:WebSocket,code:Int,reason:String) { dispatch {
                    synchronized(this@AlpacaSession){
                        if(current(g)&&socket===ws)retry(g,"DISCONNECTED") else ws.close(1000,null)
                    }
                } }
            })
            connectionsCreated++
            worker.schedule({synchronized(this){if(current(g)&&!authenticated)retry(g,"AUTH_TIMEOUT")}},authTimeoutMs,TimeUnit.MILLISECONDS)
        }catch(e:Exception){retry(g,failure(e))}
    }
    @Synchronized internal fun receive(g:Int,text:String) {
        if(!current(g))return
        require(text.length<=2_000_000)
        val rows=JSONArray(text);lastMessageAt=now()
        for(i in 0 until rows.length()) {
            if(!current(g))break
            val r=rows.getJSONObject(i)
            when(r.optString("T")) {
                "success" -> if(r.optString("msg")=="authenticated"&&!authenticated) {
                    authenticated=true;connectionState="CONNECTED";retryAt=0;event("CONNECTED")
                    testResult("running","AUTHENTICATED_LOADING")
                    socket?.send(JSONObject().put("action","subscribe").put("bars",JSONArray(symbols)).put("updatedBars",JSONArray(symbols)).toString())
                    for(symbol in symbols)http.execute {history(g,symbol)}
                    worker.schedule({synchronized(this){if(current(g)&&authenticated){attempts=0;conflicts=0}}},60,TimeUnit.SECONDS)
                }
                "error" -> {val code=r.optInt("code")
                    if(code==406)retry(g,"CONNECTION_LIMIT")
                    else if(AlpacaPolicy.terminal(code))stop("WS_ERROR_$code")
                    else retry(g,if(code==404)"AUTH_TIMEOUT" else "WS_ERROR_$code")
                }
                "b","u" -> if(authenticated)accept(r.optString("S"),r)
            }
        }
    }
    @Synchronized private fun retry(g:Int,code:String,minDelay:Long=0) {
        if(!current(g))return
        authenticated=false;generation++ // Invalidates all callbacks before closing the old socket.
        for(call in calls.keys)call.cancel()
        retire();event(code);testResult("failed",code)
        val delay:Long
        if(code=="CONNECTION_LIMIT"){
            delay=limitDelay(conflicts)
            limitUntil=maxOf(limitUntil,elapsed()+delay)
            if(conflicts++>=3){stop("CONNECTION_LIMIT_EXHAUSTED");retryAt=now()+delay;return}
        }else{
            if(attempts>=8){stop("RETRY_EXHAUSTED");return}
            delay=maxOf(minDelay,retryDelay(attempts++))
        }
        connectionState="RETRY_WAIT";openAfter=elapsed()+delay;queueConnect(generation)
    }
    @Synchronized private fun accept(symbol:String,r:JSONObject) {
        if(symbol !in symbols)return
        val time=Instant.parse(r.getString("t")).toEpochMilli()
        if(time%60000!=0L || time+60000>now() || !AlpacaPolicy.inSession(time,session))return
        val o=r.getDouble("o");val h=r.getDouble("h");val l=r.getDouble("l");val c=r.getDouble("c");val v=r.getDouble("v")
        require(AlpacaPolicy.validBar(o,h,l,c,v))
        val series=bars.getOrPut(symbol){TreeMap()}
        series[time]=JSONObject().put("t",time).put("o",o).put("h",h).put("l",l).put("c",c).put("v",v)
        lastBarAt=now()
        while(series.size>1000)series.pollFirstEntry() // bounded chart cache, not a decision archive
    }
    private fun request(g:Int,url:HttpUrl):JSONObject {
        if(!current(g)||!authenticated)throw DataFailure("DISCONNECTED")
        if(now()<blockedUntil)throw DataFailure("HTTP_429")
        synchronized(this){if(now()<nextRequest)throw DataFailure("REQUEST_BUDGET")
            nextRequest=now()+4000} // <=15 REST/min across history and options in this instance
        val pair=try{credentials()}catch(_:Exception){throw DataFailure("KEYSTORE_UNAVAILABLE")}
        val req=Request.Builder().url(url).get().header("APCA-API-KEY-ID",pair.first).header("APCA-API-SECRET-KEY",pair.second).build()
        require(AlpacaPolicy.permits(req.method,req.url.toString()))
        val call=transport.newCall(req)
        synchronized(this){if(!current(g))throw DataFailure("DISCONNECTED");calls[call]=g}
        try {call.execute().use { response ->
            synchronized(this){
            if(!current(g))throw DataFailure("DISCONNECTED")
            if(response.code==429) {
                rateLimit(response);event("HTTP_429");testResult("failed","HTTP_429");throw DataFailure("HTTP_429")
            }
            if(response.code==401){stop("HTTP_401");throw DataFailure("HTTP_401")}
            if(response.code==403 && url.encodedPath=="/v2/stocks/bars"){stop("HTTP_403");throw DataFailure("HTTP_403")}
            if(response.code!=200)throw DataFailure("HTTP_${response.code}")
            }
            val body=response.body ?: throw DataFailure("INVALID_DATA")
            val source=body.source()
            source.request(2_000_001)
            require(source.buffer.size<=2_000_000)
            return JSONObject(source.buffer.readUtf8())
        }}finally{calls.remove(call)}
    }
    private fun history(g:Int,symbol:String) {
        if(!current(g))return
        val wait=maxOf(nextRequest,blockedUntil)-now()
        if(wait>0){http.schedule({history(g,symbol)},wait,TimeUnit.MILLISECONDS);return}
        try {
            val url="https://data.alpaca.markets/v2/stocks/bars".toHttpUrl().newBuilder()
                .addQueryParameter("symbols",symbol).addQueryParameter("timeframe","1Min")
                .addQueryParameter("start",Instant.ofEpochMilli(now()-7*86400000L).toString())
                .addQueryParameter("end",Instant.ofEpochMilli(now()-60000).toString())
                .addQueryParameter("limit","1000").addQueryParameter("sort","desc")
                .addQueryParameter("adjustment","raw").addQueryParameter("feed",feed).build()
            val payload=request(g,url);require(payload.has("bars"))
            val groups=if(payload.isNull("bars"))JSONObject() else payload.getJSONObject("bars")
            val rows=groups.optJSONArray(symbol)?:JSONArray()
            synchronized(this) { if(current(g)) for(i in 0 until rows.length()) {
                val r=rows.getJSONObject(i);val t=Instant.parse(r.getString("t")).toEpochMilli()
                // Streaming updates win over a historical response that raced with them.
                if(bars[symbol]?.containsKey(t)!=true)accept(symbol,r)
            }
                if(current(g)){event("CONNECTED");testResult("succeeded",if(bars.values.any{it.isNotEmpty()})"CONNECTED_DATA" else "CONNECTED_NO_BARS")}
            }
        }catch(e:Exception){if(current(g)){
            val code=failure(e);event(code);testResult("failed",code)
            if(code=="KEYSTORE_UNAVAILABLE")stop(code)
            else http.schedule({if(current(g))history(g,symbol)},maxOf(60000,blockedUntil-now()),TimeUnit.MILLISECONDS)
        }}
    }
    fun quote(contract:String,done:(String?)->Unit) {
        require(AlpacaPolicy.contract(contract));val g=generation
        val delay=maxOf(nextRequest,blockedUntil)-now()
        if(delay>10000){done(null);return}
        http.schedule({ try {
            require(AlpacaPolicy.inSession(now(),"regular"))
            val url="https://data.alpaca.markets/v1beta1/options/snapshots".toHttpUrl().newBuilder()
                .addQueryParameter("symbols",contract).addQueryParameter("feed","opra").build()
            val q=request(g,url).getJSONObject("snapshots").getJSONObject(contract).getJSONObject("latestQuote")
            val t=Instant.parse(q.getString("t")).toEpochMilli()
            val bid=q.getDouble("bp");val ask=q.getDouble("ap")
            require(t<=now()&&now()-t<=30000&&bid>0&&ask>=bid&&ask.isFinite()&&q.getInt("bs")>0&&q.getInt("as")>0)
            require(current(g))
            done(JSONObject().put("contract",contract).put("feed","opra").put("t",t).put("bid",bid).put("ask",ask)
                .put("bidSize",q.getInt("bs")).put("askSize",q.getInt("as")).toString())
        }catch(_:Exception){done(null)} },maxOf(0,delay),TimeUnit.MILLISECONDS)
    }
    fun stockQuote(symbol:String,done:(String?)->Unit) {
        require(symbol.matches(Regex("[A-Z]{1,6}")));val g=generation;val selectedFeed=feed
        val delay=maxOf(nextRequest,blockedUntil)-now()
        if(delay>10000){done(null);return}
        http.schedule({try {
            val url="https://data.alpaca.markets/v2/stocks/quotes/latest".toHttpUrl().newBuilder()
                .addQueryParameter("symbols",symbol).addQueryParameter("feed",selectedFeed).build()
            val q=request(g,url).getJSONObject("quotes").getJSONObject(symbol)
            val at=Instant.parse(q.getString("t"));val captured=Instant.ofEpochMilli(now())
            require(!at.isAfter(captured)&&java.time.Duration.between(at,captured).toMillis()<=30000)
            fun cents(field:String):Long {
                val price=java.math.BigDecimal(q.get(field).toString())
                require(price.signum()>0&&price<=java.math.BigDecimal("1000000"))
                return price.movePointRight(2).longValueExact()
            }
            val bid=cents("bp");val ask=cents("ap")
            require(ask>=bid&&(ask-bid)*5<=ask&&current(g)&&feed==selectedFeed)
            done(JSONObject().put("version","paper-delivery-valuation-v1").put("symbol",symbol)
                .put("source","alpaca").put("feed",selectedFeed)
                .put("at",at.truncatedTo(java.time.temporal.ChronoUnit.MICROS).toString())
                .put("bidCents",bid).put("askCents",ask).toString())
        }catch(_:Exception){done(null)}},maxOf(0,delay),TimeUnit.MILLISECONDS)
    }
    @Synchronized fun snapshot():String {
        val series=JSONObject();val analysis=JSONObject()
        for((s,values) in bars) {
            series.put(s,JSONArray(values.values.toList()))
            val closes=values.values.map { it.getDouble("c") }
            analysis.put(s,JSONObject().put("rsi",AlpacaPolicy.rsi(closes)?:JSONObject.NULL)
                .put("macd",AlpacaPolicy.macd(closes)?:JSONObject.NULL))
        }
        return JSONObject().put("enabled",enabled).put("connected",authenticated&&enabled).put("reason",reason)
            .put("feed",feed).put("session",session).put("source","alpaca").put("asOf",now())
            .put("testStatus",testStatus).put("testCode",testCode).put("testAt",testAt)
            .put("symbols",JSONArray(symbols))
            .put("bars",series).put("analysis",analysis).put("retryAt",maxOf(retryAt,blockedUntil))
            .put("state",connectionState).put("lastMessageAt",lastMessageAt).put("lastBarAt",lastBarAt)
            .put("lastError",lastError).put("lastErrorAt",lastErrorAt).put("connectionsCreated",connectionsCreated)
            .put("activeSockets",if(socket==null)0 else 1).put("closingSockets",if(retiring==null)0 else 1)
            .put("events",JSONArray(events.toList())).toString()
    }
    internal fun close(){stop();synchronized(this){retiring?.cancel();retiring=null};worker.shutdownNow();http.shutdownNow();transport.dispatcher.executorService.shutdownNow();transport.connectionPool.evictAll()}
}
