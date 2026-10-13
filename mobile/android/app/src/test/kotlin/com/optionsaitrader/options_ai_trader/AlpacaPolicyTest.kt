package com.optionsaitrader.options_ai_trader

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject

class AlpacaPolicyTest {
    private val cfg = AlpacaConfig("iex", listOf("NVDA", "AAPL"), false, false)
    private val time = AlpacaPolicy.parseTime("2026-10-13T14:30:00.123456789Z")
    @Test fun dataBoundaryRejectsAllOrderVerbsAndHosts() {
        assertTrue(AlpacaPolicy.allowed("GET", "data.alpaca.markets", "/v2/stocks/bars"))
        for (method in listOf("POST", "DELETE", "PATCH", "PUT"))
            assertFalse(AlpacaPolicy.allowed(method, "data.alpaca.markets", "/v2/stocks/bars"))
        for (host in listOf("api.alpaca.markets", "paper-api.alpaca.markets", "localhost", "ibkr.com"))
            assertFalse(AlpacaPolicy.allowed("GET", host, "/v2/stocks/bars"))
        assertFalse(AlpacaPolicy.allowed("GET", "data.alpaca.markets", "/v2/orders"))
    }
    @Test fun sessionsRespectNyDst() {
        for (date in listOf("2026-10-13T13:30:00Z", "2026-12-14T14:30:00Z"))
            assertTrue(AlpacaPolicy.inSession(AlpacaPolicy.parseTime(date), false))
        assertFalse(AlpacaPolicy.inSession(AlpacaPolicy.parseTime("2026-12-14T13:30:00Z"), false))
        assertTrue(AlpacaPolicy.inSession(AlpacaPolicy.parseTime("2026-12-14T13:30:00Z"), true))
    }
    @Test fun barValidationDedupAndPrefixProtection() {
        val cache = AlpacaCache()
        val b = AlpacaBar(time, 100.0, 102.0, 99.0, 101.0, 30.0)
        cache.merge("NVDA", b, cfg, time + 60_000)
        cache.merge("NVDA", b.copy(close = 102.0), cfg, time + 60_000)
        assertEquals(1, cache.series("NVDA").size)
        assertEquals(102.0, cache.series("NVDA").single().close, 0.0)
        assertTrue(cache.series("AAPL").isEmpty())
        assertThrows(IllegalArgumentException::class.java) { cache.merge("NVDA", b, cfg, time) }
        assertThrows(IllegalArgumentException::class.java) { cache.merge("TSLA", b, cfg, time + 60_000) }
        assertThrows(IllegalArgumentException::class.java) { b.copy(close = Double.NaN) }
        assertThrows(IllegalArgumentException::class.java) { b.copy(high = 98.0) }
    }
    @Test fun providerExampleShapeIsParsedWithoutPricesBeingInvented() {
        val bar = AlpacaBar.parse(JSONObject("""{"t":"2026-10-13T14:30:00Z","o":100,"h":102,"l":99,"c":101,"v":30}"""))
        assertEquals(time, bar.time)
        assertThrows(Exception::class.java) { AlpacaBar.parse(JSONObject("""{"t":"2026-10-13T14:30:00Z"}""")) }
    }
    @Test fun freshnessBackoffAndConfigBounds() {
        assertFalse(AlpacaPolicy.fresh(time, time - 1))
        assertFalse(AlpacaPolicy.fresh(time, time + 1_000))
        assertTrue(AlpacaPolicy.fresh(time, time + 70_000))
        assertFalse(AlpacaPolicy.fresh(time, time + 151_000))
        assertEquals(300_000L, AlpacaPolicy.backoff(100))
        assertThrows(IllegalArgumentException::class.java) { cfg.copy(feed = "opra") }
        assertThrows(IllegalArgumentException::class.java) { cfg.copy(symbols = listOf("NVDA", "NVDA")) }
        assertThrows(IllegalArgumentException::class.java) { cfg.copy(symbols = listOf("../orders")) }
    }
}
