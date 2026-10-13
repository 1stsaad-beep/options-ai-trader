package com.optionsaitrader.options_ai_trader

import okhttp3.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Only these two reads exist. Credentials are loaded at request time, not in UI state. */
class AlpacaTransport(private val credentials: () -> Pair<String, String>,
                      private val client: OkHttpClient = safeClient()) {
    companion object {
        fun safeClient() = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
            .retryOnConnectionFailure(false).connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS).callTimeout(15, TimeUnit.SECONDS)
            .pingInterval(20, TimeUnit.SECONDS).build()
    }
    private fun request(url: String, socket: Boolean = false): Request {
        val parsed = url.replaceFirst("wss://", "https://").toHttpUrl()
        check(if (socket) parsed.host == "stream.data.alpaca.markets" && parsed.encodedPath in listOf("/v2/iex", "/v2/sip")
            else AlpacaDataPolicy.allowed("GET", parsed.host, parsed.encodedPath))
        val (id, secret) = credentials()
        return Request.Builder().url(url).header("APCA-API-KEY-ID", id).header("APCA-API-SECRET-KEY", secret).get().build()
    }
    fun bars(config: AlpacaConfig, historySymbol: String?, now: Long): Pair<Int, String> {
        val path = if (historySymbol == null) "/v2/stocks/bars/latest" else "/v2/stocks/bars"
        val url = (AlpacaDataPolicy.REST + path).toHttpUrl().newBuilder()
            .addQueryParameter("symbols", historySymbol ?: config.symbols.joinToString(","))
            .addQueryParameter("feed", config.feed)
        if (historySymbol != null) {
            url.addQueryParameter("timeframe", "1Min").addQueryParameter("limit", "600")
                .addQueryParameter("sort", "desc").addQueryParameter("adjustment", "raw")
                .addQueryParameter("start", AlpacaDataPolicy.iso(now - 7 * 86_400_000L))
                // SIP history is conservative for Basic. Live SIP access is tested separately.
                .addQueryParameter("end", AlpacaDataPolicy.iso(now - if (config.feed == "sip") 960_000 else 60_000))
        }
        client.newCall(request(url.build().toString())).execute().use { response ->
            if (response.code != 200) return response.code to "" // Never return/log provider error bodies.
            val source = response.body.source()
            check(!source.request(AlpacaDataPolicy.MAX_BODY.toLong() + 1))
            return 200 to source.readUtf8()
        }
    }
    fun stream(config: AlpacaConfig, listener: WebSocketListener): WebSocket =
        client.newWebSocket(request(AlpacaDataPolicy.SOCKET + config.feed, true), listener)
    fun cancel() { client.dispatcher.cancelAll() }
}

/** One process-wide owner: foreground screen and optional service share this engine. */
class AlpacaEngine(private val transport: AlpacaTransport, private val now: () -> Long = System::currentTimeMillis,
                   autoPoll: Boolean = true) {
    private val scheduler = Executors.newSingleThreadScheduledExecutor()
    private val cache = AlpacaCache()
    private var config: AlpacaConfig? = null
    private var socket: WebSocket? = null
    private var generation = 0
    private var lastRequest = 0L
    private var nextRequest = 0L
    private var lastSuccess = 0L
    private var attempt = 0
    private var wsAttempt = 0
    private var historyIndex = 0
    private var requestCount = 0
    private var wsAuthenticated = false
    private var wsBlocked = false
    private var wsNext = 0L
    private var state = "DISCONNECTED"
    private var socketState = "OFF"
    private val events = ArrayDeque<Map<String, Any>>()
    init { if (autoPoll) scheduler.scheduleWithFixedDelay({ poll() }, 1, 1, TimeUnit.SECONDS) }
    @Synchronized fun start(value: AlpacaConfig) {
        stop(); generation++; config = value; cache.clear(); historyIndex = 0
        nextRequest = 0; attempt = 0; wsAttempt = 0; wsNext = 0; wsBlocked = false
        state = "CONNECTING"; event("START_REQUESTED")
    }
    @Synchronized fun stop() {
        generation++; config = null; socket?.cancel(); socket = null
        transport.cancel(); wsAuthenticated = false; lastSuccess = 0
        state = "DISCONNECTED"; socketState = "OFF"
    }
    private fun event(code: String) {
        events.addLast(mapOf("code" to code, "at" to now()))
        while (events.size > 100) events.removeFirst()
    }
    @Synchronized fun snapshot(): Map<String, Any?> {
        val c = config
        val connected = c != null && ((lastSuccess > 0 && now() - lastSuccess in 0..40_000) || wsAuthenticated)
        return mapOf("enabled" to (c != null), "connected" to connected,
            "state" to state, "socketState" to socketState, "feed" to c?.feed,
            "extended" to c?.extended, "stream" to c?.stream,
            "checkedAt" to lastSuccess, "nextRequestAt" to nextRequest, "requests" to requestCount,
            "events" to events.toList(), "symbols" to (c?.symbols ?: emptyList<String>()),
            "series" to (c?.symbols?.associateWith { symbol -> cache.series(symbol).map { it.map() } } ?: emptyMap<String, Any>()),
            "optionsQualified" to false, "orderCapability" to false)
    }
    internal fun poll() {
        val selected: AlpacaConfig; val epoch: Int; val history: String?
        synchronized(this) {
            selected = config ?: return; epoch = generation
            if (selected.stream && socket == null && !wsBlocked && now() >= wsNext) openSocket(selected, epoch)
            if (now() < nextRequest || now() - lastRequest < 10_000) return
            lastRequest = now(); nextRequest = now() + 10_000; requestCount++
            // Alternate bootstrap history and latest: 6 requests/minute total, not per symbol.
            history = if (historyIndex < selected.symbols.size && requestCount % 2 == 1) selected.symbols[historyIndex] else null
        }
        try {
            val (code, body) = transport.bars(selected, history, now())
            synchronized(this) {
                if (epoch != generation) return
                when (code) {
                    200 -> {
                        val bars = JSONObject(body).getJSONObject("bars")
                        val parsed = mutableListOf<Pair<String, AlpacaBar>>()
                        bars.keys().forEach { symbol ->
                            check(symbol in selected.symbols)
                            val row = bars.get(symbol)
                            if (row is JSONArray) for (i in 0 until row.length()) parsed.add(symbol to AlpacaBar.parse(row.getJSONObject(i)))
                            else if (row is JSONObject) parsed.add(symbol to AlpacaBar.parse(row))
                        }
                        check(parsed.all { it.second.time <= now() - 60_000 })
                        parsed.forEach { (symbol, bar) -> cache.merge(symbol, bar, selected, now()) }
                        if (history != null) historyIndex++
                        lastSuccess = now(); attempt = 0; state = "CONNECTED"
                    }
                    401, 403 -> { stop(); state = if (code == 401) "AUTH_REJECTED" else "FEED_NOT_ENTITLED"; event(state) }
                    429 -> { lastSuccess = 0; state = "RATE_LIMITED"; nextRequest = now() + 300_000; event(state) }
                    else -> failed()
                }
            }
        } catch (_: Exception) { synchronized(this) { if (epoch == generation) failed() } }
    }
    private fun failed() {
        lastSuccess = 0; state = "DISCONNECTED"; nextRequest = now() + AlpacaDataPolicy.backoff(attempt++)
        event("DATA_UNAVAILABLE")
    }
    private fun openSocket(c: AlpacaConfig, epoch: Int) {
        socketState = "CONNECTING"
        val listener = object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                synchronized(this@AlpacaEngine) {
                    if (epoch != generation || webSocket !== socket) return
                    try {
                        check(text.length <= AlpacaDataPolicy.MAX_BODY)
                        val items = JSONArray(text)
                        for (i in 0 until items.length()) {
                            val j = items.getJSONObject(i)
                            when (j.getString("T")) {
                                "success" -> if (j.optString("msg") == "authenticated") {
                                    wsAuthenticated = true; wsAttempt = 0; socketState = "AUTHENTICATED"
                                    webSocket.send(JSONObject().put("action", "subscribe").put("bars", JSONArray(c.symbols))
                                        .put("updatedBars", JSONArray(c.symbols)).toString())
                                }
                                "subscription" -> socketState = "SUBSCRIBED"
                                "b", "u" -> {
                                    check(wsAuthenticated)
                                    cache.merge(j.getString("S"), AlpacaBar.parse(j), c, now())
                                }
                                "error" -> {
                                    val code = j.getInt("code")
                                    wsBlocked = code in listOf(401, 402, 405, 406, 409, 410)
                                    socketState = if (code == 406) "CONNECTION_IN_USE_REST_ONLY" else "STREAM_REJECTED_$code"
                                    event(socketState); closeSocket()
                                }
                            }
                        }
                    } catch (_: Exception) { socketState = "INVALID_STREAM_DATA"; closeSocket() }
                }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                synchronized(this@AlpacaEngine) {
                    if (epoch != generation || webSocket !== socket) return
                    socketState = "DISCONNECTED"; closeSocket()
                }
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                synchronized(this@AlpacaEngine) { if (epoch == generation && webSocket === socket) closeSocket() }
            }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(code, null) }
        }
        try { socket = transport.stream(c, listener) }
        catch (_: Exception) { socketState = "DISCONNECTED"; closeSocket() }
    }
    private fun closeSocket() {
        val previous = socket; socket = null; wsAuthenticated = false
        wsNext = now() + AlpacaDataPolicy.backoff(wsAttempt++)
        previous?.cancel()
    }
}
