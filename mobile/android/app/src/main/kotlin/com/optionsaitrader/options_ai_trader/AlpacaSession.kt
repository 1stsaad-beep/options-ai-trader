package com.optionsaitrader.options_ai_trader

import okhttp3.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.time.Instant
import java.util.TreeMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** One stream shared by all local accounts. Credentials never enter snapshots/errors/logs. */
internal class AlpacaSession(
    private val credentials: () -> Pair<String,String>,
    private val now: () -> Long = System::currentTimeMillis,
    private val transport: OkHttpClient = client(),
    private val sockets: WebSocket.Factory = transport
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
    private val bars=mutableMapOf<String,TreeMap<Long,JSONObject>>()
    private val events=ArrayDeque<JSONObject>()
    @Volatile private var generation=0
    @Volatile var enabled=false; private set
    @Volatile private var authenticated=false
    @Volatile private var socket: WebSocket?=null
    private var feed="iex"
    private var session="regular"
    private var symbols=listOf<String>()
    @Volatile private var reason="DISABLED"
    private var attempts=0
    @Volatile private var blockedUntil=0L
    private var nextRequest=0L
    private var reconnectPending=false

    @Synchronized private fun event(code:String) {
        reason=code
        events.addLast(JSONObject().put("at",now()).put("code",code))
        while(events.size>100)events.removeFirst()
    }
    @Synchronized fun start(selectedFeed:String,selectedSession:String,watch:List<String>) {
        require(AlpacaPolicy.feed(selectedFeed) && selectedSession in listOf("regular","extended"))
        require(watch.size in 1..10 && watch.distinct().size==watch.size && watch.all { AlpacaPolicy.symbol(it) })
        stop("RECONFIGURED");feed=selectedFeed;session=selectedSession;symbols=watch.toList()
        bars.clear();attempts=0;enabled=true;event("CONNECTING")
        val g=generation;worker.execute { connect(g) }
    }
    @Synchronized fun stop(code:String="DISABLED") {
        generation++;enabled=false;authenticated=false;socket?.cancel();socket=null;reconnectPending=false;event(code)
    }
    private fun current(g:Int)=enabled && g==generation
    private fun connect(g:Int) {
        if(!current(g))return
        if(now()<blockedUntil){retry(g,"RATE_LIMIT",blockedUntil-now());return}
        try {
            val request=Request.Builder().url("https://stream.data.alpaca.markets/v2/$feed").get().build()
            socket=sockets.newWebSocket(request,object:WebSocketListener(){
                override fun onOpen(ws:WebSocket,response:Response) { worker.execute {
                    if(!current(g)){ws.cancel();return@execute}
                    try { val pair=credentials();ws.send(JSONObject().put("action","auth").put("key",pair.first).put("secret",pair.second).toString()) }
                    catch(_:Exception){stop("KEYSTORE_UNAVAILABLE")}
                } }
                override fun onMessage(ws:WebSocket,text:String) { worker.execute {
                    if(current(g)) try { receive(g,text) } catch(_:Exception){retry(g,"INVALID_DATA")} }
                }
                override fun onFailure(ws:WebSocket,t:Throwable,response:Response?) { worker.execute {
                    if(current(g)) { val code=response?.code ?: 0
                        if(AlpacaPolicy.terminal(code))stop("AUTH_OR_ENTITLEMENT_$code") else retry(g,"DISCONNECTED") }
                } }
                override fun onClosed(ws:WebSocket,code:Int,reason:String) { worker.execute { if(current(g))retry(g,"DISCONNECTED") } }
                override fun onClosing(ws:WebSocket,code:Int,reason:String) { ws.close(code,null) }
            })
            worker.schedule({if(current(g)&&!authenticated)retry(g,"AUTH_TIMEOUT")},12,TimeUnit.SECONDS)
        }catch(_:Exception){retry(g,"CONNECT_FAILED")}
    }
    @Synchronized internal fun receive(g:Int,text:String) {
        if(!current(g))return
        require(text.length<=2_000_000)
        val rows=JSONArray(text)
        for(i in 0 until rows.length()) {
            if(!current(g))break
            val r=rows.getJSONObject(i)
            when(r.optString("T")) {
                "success" -> if(r.optString("msg")=="authenticated") {
                    authenticated=true;attempts=0;event("CONNECTED")
                    socket?.send(JSONObject().put("action","subscribe").put("bars",JSONArray(symbols)).put("updatedBars",JSONArray(symbols)).toString())
                    for(symbol in symbols) worker.execute { history(g,symbol) }
                }
                "error" -> { val code=r.optInt("code")
                    if(AlpacaPolicy.terminal(code))stop(if(code==406)"OTHER_APP_CONNECTION_LIMIT" else "AUTH_OR_ENTITLEMENT_$code")
                    else retry(g,"STREAM_ERROR_$code")
                }
                "b","u" -> if(authenticated) accept(r.optString("S"),r)
            }
        }
    }
    @Synchronized private fun retry(g:Int,code:String,minDelay:Long=0) {
        if(!current(g)||reconnectPending)return
        authenticated=false;socket?.cancel();socket=null
        if(attempts>=8){stop("RETRY_EXHAUSTED");return}
        reconnectPending=true;event(code)
        val delay=maxOf(minDelay,AlpacaPolicy.retryMs(attempts++))
        // Invalidate callbacks from the old socket before scheduling a replacement.
        val next=++generation
        worker.schedule({synchronized(this){reconnectPending=false};if(current(next))connect(next)},delay,TimeUnit.MILLISECONDS)
    }
    @Synchronized private fun accept(symbol:String,r:JSONObject) {
        if(symbol !in symbols)return
        val time=Instant.parse(r.getString("t")).toEpochMilli()
        if(time%60000!=0L || time+60000>now() || !AlpacaPolicy.inSession(time,session))return
        val o=r.getDouble("o");val h=r.getDouble("h");val l=r.getDouble("l");val c=r.getDouble("c");val v=r.getDouble("v")
        require(AlpacaPolicy.validBar(o,h,l,c,v))
        val series=bars.getOrPut(symbol){TreeMap()}
        series[time]=JSONObject().put("t",time).put("o",o).put("h",h).put("l",l).put("c",c).put("v",v)
        while(series.size>1000)series.pollFirstEntry() // bounded chart cache, not a decision archive
    }
    private fun request(g:Int,url:HttpUrl):JSONObject {
        if(!current(g)||!authenticated)throw IOException("DISCONNECTED")
        if(now()<maxOf(blockedUntil,nextRequest))throw IOException("BUDGET")
        nextRequest=now()+4000 // <=15 REST/min across history and options in this instance
        val pair=credentials()
        val req=Request.Builder().url(url).get().header("APCA-API-KEY-ID",pair.first).header("APCA-API-SECRET-KEY",pair.second).build()
        require(AlpacaPolicy.permits(req.method,req.url.toString()))
        transport.newCall(req).execute().use { response ->
            if(!current(g))throw IOException("DISCONNECTED")
            if(response.code==429) {
                val seconds=response.header("Retry-After")?.toLongOrNull()
                val reset=response.header("X-RateLimit-Reset")?.toLongOrNull()?.times(1000)
                blockedUntil=maxOf(now()+maxOf(60L,seconds?:60L)*1000,reset?:0)
                event("RATE_LIMIT");throw IOException("RATE_LIMIT")
            }
            if(response.code==401){stop("AUTH_OR_ENTITLEMENT_401");throw IOException("AUTH")}
            if(response.code==403 && url.encodedPath=="/v2/stocks/bars"){stop("AUTH_OR_ENTITLEMENT_403");throw IOException("ENTITLEMENT")}
            if(response.code!=200)throw IOException("HTTP_${response.code}")
            val body=response.body ?: throw IOException("EMPTY")
            val source=body.source()
            source.request(2_000_001)
            require(source.buffer.size<=2_000_000)
            return JSONObject(source.buffer.readUtf8())
        }
    }
    private fun history(g:Int,symbol:String) {
        if(!current(g))return
        val wait=maxOf(nextRequest,blockedUntil)-now()
        if(wait>0){worker.schedule({history(g,symbol)},wait,TimeUnit.MILLISECONDS);return}
        try {
            val url="https://data.alpaca.markets/v2/stocks/bars".toHttpUrl().newBuilder()
                .addQueryParameter("symbols",symbol).addQueryParameter("timeframe","1Min")
                .addQueryParameter("start",Instant.ofEpochMilli(now()-7*86400000L).toString())
                .addQueryParameter("end",Instant.ofEpochMilli(now()-60000).toString())
                .addQueryParameter("limit","1000").addQueryParameter("sort","desc")
                .addQueryParameter("adjustment","raw").addQueryParameter("feed",feed).build()
            val rows=request(g,url).optJSONObject("bars")?.optJSONArray(symbol)?:JSONArray()
            synchronized(this) { if(current(g)) for(i in 0 until rows.length()) {
                val r=rows.getJSONObject(i);val t=Instant.parse(r.getString("t")).toEpochMilli()
                // Streaming updates win over a historical response that raced with them.
                if(bars[symbol]?.containsKey(t)!=true)accept(symbol,r)
            } }
        }catch(_:Exception){if(current(g)){event("HISTORY_UNAVAILABLE");worker.schedule({if(current(g))history(g,symbol)},maxOf(60000,blockedUntil-now()),TimeUnit.MILLISECONDS)}}
    }
    fun quote(contract:String,done:(String?)->Unit) {
        require(AlpacaPolicy.contract(contract));val g=generation
        worker.execute { try {
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
        }catch(_:Exception){done(null)} }
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
            .put("bars",series).put("analysis",analysis).put("retryAt",blockedUntil)
            .put("events",JSONArray(events.toList())).toString()
    }
    internal fun close(){stop();worker.shutdownNow();transport.dispatcher.executorService.shutdownNow();transport.connectionPool.evictAll()}
}
