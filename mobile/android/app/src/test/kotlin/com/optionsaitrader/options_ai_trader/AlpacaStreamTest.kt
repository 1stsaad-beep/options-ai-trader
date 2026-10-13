package com.optionsaitrader.options_ai_trader

import okhttp3.*
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.ByteString
import org.junit.Assert.*
import org.junit.Test

class AlpacaStreamTest {
    private class FakeSocket(private val req: Request) : WebSocket {
        var cancelled = false
        val sent = mutableListOf<String>()
        override fun request() = req
        override fun queueSize() = 0L
        override fun send(text: String): Boolean { sent.add(text); return true }
        override fun send(bytes: ByteString) = false
        override fun close(code: Int, reason: String?) = true
        override fun cancel() { cancelled = true }
    }
    private class Factory : WebSocket.Factory {
        lateinit var listener: WebSocketListener
        lateinit var socket: FakeSocket
        var count = 0
        override fun newWebSocket(request: Request, listener: WebSocketListener): WebSocket {
            count++; this.listener = listener; socket = FakeSocket(request); return socket
        }
        fun send(text: String) = listener.onMessage(socket, text)
    }
    @Test fun streamAuthDedupConflictAndLateCallbacksStayDataOnly() {
        var now = AlpacaDataPolicy.parseTime("2026-10-13T14:31:10Z")
        val factory = Factory()
        val client = AlpacaTransport.safeClient().newBuilder().addInterceptor { chain ->
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                .code(200).message("Mock").body("""{"bars":{}}""".toResponseBody()).build()
        }.build()
        val engine = AlpacaEngine(AlpacaTransport({ "mock-id" to "mock-secret" }, client, factory), { now }, false)
        engine.start(AlpacaConfig("iex", listOf("NVDA"), false, true)); engine.poll()
        assertEquals("stream.data.alpaca.markets", factory.socket.request().url.host)
        assertTrue(factory.socket.sent.isEmpty())
        factory.send("""[{"T":"success","msg":"authenticated"}]""")
        factory.send("""[{"T":"success","msg":"authenticated"}]""")
        assertEquals(1, factory.socket.sent.size)
        assertTrue(factory.socket.sent.single().contains("subscribe"))
        assertFalse(factory.socket.sent.single().contains("secret"))
        factory.send("""[{"T":"b","S":"NVDA","t":"2026-10-13T14:30:00Z","o":100,"h":103,"l":99,"c":102,"v":40}]""")
        factory.send("""[{"T":"u","S":"NVDA","t":"2026-10-13T14:30:00Z","o":100,"h":103,"l":99,"c":103,"v":50}]""")
        val series = engine.snapshot()["series"] as Map<*, *>
        assertEquals(1, (series["NVDA"] as List<*>).size)
        factory.send("""[{"T":"error","code":406,"msg":"provider secret"}]""")
        assertEquals("CONNECTION_IN_USE_REST_ONLY", engine.snapshot()["socketState"])
        assertTrue(factory.socket.cancelled)
        now += 360_000; engine.poll(); assertEquals(1, factory.count)
        assertEquals(true, engine.snapshot()["enabled"]) // REST remains independent of the other app's socket.
        assertFalse(engine.snapshot().toString().contains("provider secret"))
        engine.stop(); factory.send("""[{"T":"success","msg":"authenticated"}]""")
        assertEquals(false, engine.snapshot()["connected"])
    }
    @Test fun socketOffMeansNoSubscriptionAtAll() {
        val factory = Factory()
        val client = AlpacaTransport.safeClient().newBuilder().addInterceptor { chain ->
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                .code(401).message("Mock").body("".toResponseBody()).build()
        }.build()
        val engine = AlpacaEngine(AlpacaTransport({ "mock-id" to "mock-secret" }, client, factory), autoPoll = false)
        engine.start(AlpacaConfig("iex", listOf("NVDA"), false, false)); engine.poll()
        assertEquals(0, factory.count)
        assertEquals("AUTH_REJECTED", engine.snapshot()["state"])
    }
}
