package com.optionsaitrader.options_ai_trader

import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone
import java.util.TreeMap
import org.json.JSONObject

/** Read-only stock data boundary. Never accepts a URL or HTTP method from Flutter. */
data class AlpacaConfig(val feed: String, val symbols: List<String>, val extended: Boolean, val stream: Boolean) {
    init {
        require(feed in listOf("iex", "sip"))
        require(symbols.isNotEmpty() && symbols.size <= 30 && symbols.distinct().size == symbols.size)
        require(symbols.all { it.matches(Regex("[A-Z][A-Z0-9.]{0,9}")) })
    }
}

object AlpacaDataPolicy {
    const val REST = "https://data.alpaca.markets"
    const val SOCKET = "wss://stream.data.alpaca.markets/v2/"
    const val MAX_BODY = 2 * 1024 * 1024
    const val BAR_LIMIT = 600
    const val FRESH_MS = 150_000L
    fun allowed(method: String, host: String, path: String): Boolean = method == "GET" &&
        host == "data.alpaca.markets" && path in listOf("/v2/stocks/bars", "/v2/stocks/bars/latest")
    fun backoff(attempt: Int): Long = (5_000L * (1L shl attempt.coerceIn(0, 6))).coerceAtMost(300_000)
    fun fresh(timestamp: Long, now: Long): Boolean = now - timestamp in 60_000..FRESH_MS
    fun inSession(timestamp: Long, extended: Boolean): Boolean {
        val c = Calendar.getInstance(TimeZone.getTimeZone("America/New_York"))
        c.timeInMillis = timestamp
        if (c.get(Calendar.DAY_OF_WEEK) in listOf(Calendar.SATURDAY, Calendar.SUNDAY)) return false
        val minute = c.get(Calendar.HOUR_OF_DAY) * 60 + c.get(Calendar.MINUTE)
        // Selection filter only: NOT an exchange holiday/early-close calendar.
        return if (extended) minute in 240 until 1200 else minute in 570 until 960
    }
    fun parseTime(value: String): Long {
        require(value.matches(Regex("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d{1,9})?Z")))
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("UTC"); fmt.isLenient = false
        return requireNotNull(fmt.parse(value.substring(0, 19) + "Z")).time
    }
    fun iso(ms: Long): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("UTC")
        return fmt.format(java.util.Date(ms))
    }
}

data class AlpacaBar(val time: Long, val open: Double, val high: Double, val low: Double, val close: Double, val volume: Double) {
    init {
        require(listOf(open, high, low, close, volume).all { it.isFinite() })
        require(low > 0 && high >= low && open in low..high && close in low..high && volume >= 0)
    }
    fun map(): Map<String, Any> = mapOf("t" to time, "o" to open, "h" to high, "l" to low, "c" to close, "v" to volume)
    companion object {
        fun parse(j: JSONObject) = AlpacaBar(AlpacaDataPolicy.parseTime(j.getString("t")), j.getDouble("o"),
            j.getDouble("h"), j.getDouble("l"), j.getDouble("c"), j.getDouble("v"))
    }
}

class AlpacaCache {
    private val data = mutableMapOf<String, TreeMap<Long, AlpacaBar>>()
    fun merge(symbol: String, bar: AlpacaBar, config: AlpacaConfig, now: Long, replace: Boolean = true) {
        require(symbol in config.symbols)
        require(bar.time % 60_000 == 0L && bar.time <= now - 60_000) // Complete, aligned minutes only.
        if (!AlpacaDataPolicy.inSession(bar.time, config.extended)) return
        val series = data.getOrPut(symbol) { TreeMap() }
        if (replace || !series.containsKey(bar.time)) series[bar.time] = bar
        while (series.size > AlpacaDataPolicy.BAR_LIMIT) series.pollFirstEntry()
    }
    fun series(symbol: String): List<AlpacaBar> = data[symbol]?.values?.toList() ?: emptyList()
    fun clear() = data.clear()
}
