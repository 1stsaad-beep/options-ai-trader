package com.optionsaitrader.options_ai_trader

import okhttp3.*
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test

class AlpacaTransportTest {
    private val cfg = AlpacaConfig("iex", listOf("NVDA"), false, false)
    private val instant = AlpacaPolicy.parseTime("2026-10-13T14:31:10Z")
    private val payload = """{"bars":{"NVDA":{"t":"2026-10-13T14:30:00Z","o":100,"h":102,"l":99,"c":101,"v":30}}}"""
    private fun transport(code: () -> Int, seen: MutableList<Request>, body: () -> String = { payload }): AlpacaTransport {
        val client = AlpacaTransport.safeClient().newBuilder().addInterceptor { chain ->
            seen.add(chain.request())
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                .code(code()).message("Mock").body(body().toResponseBody()).build()
        }.build()
        return AlpacaTransport({ "mock-id-only" to "mock-secret-only" }, client)
    }
    @Test fun authOnlyUsesFixedDataGetAndNeverReturnsCredentials() {
        val seen = mutableListOf<Request>()
        val t = transport({ 200 }, seen)
        assertEquals(200, t.bars(cfg, null, instant).first)
        val r = seen.single()
        assertEquals("GET", r.method); assertEquals("data.alpaca.markets", r.url.host)
        assertEquals("/v2/stocks/bars/latest", r.url.encodedPath)
        assertEquals("mock-id-only", r.header("APCA-API-KEY-ID"))
        assertFalse(r.url.toString().contains("secret"))
    }
    @Test fun errorsIncludingRedirectsNeverSurfaceBodiesOrRetryAutomatically() {
        for (code in listOf(301, 302, 401, 403, 429, 500)) {
            val seen = mutableListOf<Request>()
            val result = transport({ code }, seen, { "sensitive error" }).bars(cfg, null, instant)
            assertEquals(code, result.first); assertEquals("", result.second); assertEquals(1, seen.size)
        }
    }
    @Test fun rateLimitsReconnectDedupAndStopRejectLateWork() {
        var clock = instant; var code = 200
        val seen = mutableListOf<Request>()
        val engine = AlpacaEngine(transport({ code }, seen), { clock }, false)
        engine.start(cfg); engine.poll(); engine.poll()
        assertEquals(1, seen.size)
        assertEquals(true, engine.snapshot()["connected"])
        clock += 10_000; code = 429; engine.poll()
        assertEquals("RATE_LIMITED", engine.snapshot()["state"])
        engine.poll(); assertEquals(2, seen.size)
        clock += 300_000; code = 200; engine.poll()
        assertEquals("CONNECTED", engine.snapshot()["state"])
        assertFalse(engine.snapshot().toString().contains("mock-secret"))
        engine.stop(); clock += 10_000; engine.poll(); assertEquals(3, seen.size)
        assertEquals(false, engine.snapshot()["connected"])
        assertEquals(false, engine.snapshot()["optionsQualified"])
    }
    @Test fun invalidDataAndRevokedCredentialsFailClosed() {
        var clock = instant; var code = 200
        val seen = mutableListOf<Request>()
        val engine = AlpacaEngine(transport({ code }, seen, { "{}" }), { clock }, false)
        engine.start(cfg); engine.poll()
        assertEquals(false, engine.snapshot()["connected"])
        clock += 10_000; code = 401; engine.poll()
        assertEquals("AUTH_REJECTED", engine.snapshot()["state"])
        clock += 100_000; engine.poll(); assertEquals(2, seen.size)
    }
}
