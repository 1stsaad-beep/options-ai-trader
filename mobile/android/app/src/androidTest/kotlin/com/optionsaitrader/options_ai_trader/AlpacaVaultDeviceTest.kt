package com.optionsaitrader.options_ai_trader

import android.content.ComponentName
import android.content.pm.ApplicationInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.security.KeyStore
import okhttp3.*
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.ByteString
import org.json.JSONObject
import java.time.Instant
import java.util.concurrent.CopyOnWriteArrayList
import androidx.test.core.app.ActivityScenario
import java.util.concurrent.atomic.AtomicInteger

/** Disposable emulator only; mock strings, no network and no provider credentials. */
@RunWith(AndroidJUnit4::class)
class AlpacaVaultDeviceTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private fun waitFor(check:()->Boolean){
        val until=System.nanoTime()+10_000_000_000L
        while(!check()&&System.nanoTime()<until)Thread.sleep(30)
        assertTrue(check())
    }
    @Test fun paperDiskCompareAndSwapSurvivesNewInstance(){
        val dir=File(context.cacheDir,"paper-disk-cas-test").apply{mkdirs()}
        val file=File(dir,"ledger.json");val first="""{"version":1,"accounts":[],"journal":[]}"""
        val second="""{"version":1,"accounts":[],"journal":[],"journalArchive":[]}"""
        try {
            val store=PaperDiskStore(file);assertNull(store.read());assertTrue(store.write(null,first))
            assertEquals(first,PaperDiskStore(file).read())
            try{PaperDiskStore(file).write(null,second);fail("stale writer accepted")}catch(_:IllegalStateException){}
            assertEquals(first,store.read());assertTrue(store.write(first,second));assertEquals(second,PaperDiskStore(file).read())
        }finally{dir.deleteRecursively()}
    }
    @Test fun paperDiskInterruptedWriteRecoversOriginalWithoutInventingLedger(){
        val dir=File(context.cacheDir,"paper-disk-recovery-test").apply{mkdirs()}
        val file=File(dir,"ledger.json");val first="""{"version":1,"accounts":[],"journal":[]}"""
        try {
            PaperDiskStore(file).write(null,first)
            val atomic=android.util.AtomicFile(file);val interrupted=atomic.startWrite()
            interrupted.write("partial".toByteArray());interrupted.flush();interrupted.fd.sync();interrupted.close()
            assertEquals(first,PaperDiskStore(file).read())
            try{PaperDiskStore(file).write(first,"not-json");fail("invalid bytes accepted")}catch(_:org.json.JSONException){}
            assertEquals(first,PaperDiskStore(file).read())
        }finally{dir.deleteRecursively()}
    }
    @Test fun runtimeIsSharedAcrossActivityAndApplicationContexts(){
        assertSame(AlpacaRuntime.get(context),AlpacaRuntime.get(context.applicationContext))
    }
    @Test fun actualActivityScreenSleepWakeResumesOneMockSession(){
        val opened=AtomicInteger();val active=AtomicInteger();val maximum=AtomicInteger()
        val transport=AlpacaSession.client().newBuilder().addInterceptor{chain->
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("mock")
                .body("""{"bars":{}}""".toResponseBody()).build()
        }.build()
        val sockets=object:WebSocket.Factory{
            override fun newWebSocket(request:Request,listener:WebSocketListener):WebSocket{
                opened.incrementAndGet();maximum.updateAndGet{maxOf(it,active.incrementAndGet())}
                val socket=object:WebSocket{
                    var ended=false
                    override fun request()=request
                    override fun queueSize()=0L
                    override fun send(text:String):Boolean{if(JSONObject(text).optString("action")=="auth")listener.onMessage(this,"""[{"T":"success","msg":"authenticated"}]""");return true}
                    override fun send(bytes:ByteString)=false
                    @Synchronized override fun close(code:Int,reason:String?):Boolean{if(!ended){ended=true;active.decrementAndGet();listener.onClosed(this,1000,"mock")};return true}
                    @Synchronized override fun cancel(){if(!ended){ended=true;active.decrementAndGet()}}
                }
                listener.onOpen(socket,Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(101).message("mock").build());return socket
            }
        }
        val session=AlpacaSession({Pair("mock-public-key","mock-private-value")},transport=transport,sockets=sockets)
        // Test APK only: replace the process singleton with an entirely intercepted transport.
        val field=AlpacaRuntime::class.java.getDeclaredField("instance").apply{isAccessible=true}
        val previous=field.get(null);AlpacaRuntime.stop();field.set(null,session)
        val automation=InstrumentationRegistry.getInstrumentation().uiAutomation
        fun shell(command:String){android.os.ParcelFileDescriptor.AutoCloseInputStream(automation.executeShellCommand(command)).use{it.readBytes()}}
        try{
            shell("input keyevent KEYCODE_WAKEUP");shell("wm dismiss-keyguard")
            ActivityScenario.launch(MainActivity::class.java).use{scenario->
                scenario.onActivity{session.start("iex","regular",listOf("NVDA"))}
                waitFor{JSONObject(session.snapshot()).getBoolean("connected")};assertEquals(1,opened.get())
                shell("input keyevent KEYCODE_SLEEP")
                waitFor{JSONObject(session.snapshot()).getString("state")=="PAUSED_BACKGROUND"}
                assertFalse(JSONObject(session.snapshot()).getBoolean("connected"))
                shell("input keyevent KEYCODE_WAKEUP");shell("wm dismiss-keyguard")
                waitFor{JSONObject(session.snapshot()).getBoolean("connected")&&opened.get()==2}
                assertEquals(1,maximum.get())
                scenario.onActivity{session.stop()}
                shell("input keyevent KEYCODE_SLEEP");Thread.sleep(200)
                shell("input keyevent KEYCODE_WAKEUP");shell("wm dismiss-keyguard");Thread.sleep(300)
                assertFalse(session.enabled);assertEquals(2,opened.get())
            }
        }finally{shell("input keyevent KEYCODE_WAKEUP");shell("wm dismiss-keyguard");session.close();field.set(null,previous)}
    }
    @Test fun encryptedRoundTripUsesNonExportableAndroidKey() {
        val vault=AlpacaVault(context);vault.save("mock-public-key","mock-private-value")
        assertTrue(vault.exists());assertEquals(Pair("mock-public-key","mock-private-value"),vault.read())
        val bytes=File(context.noBackupFilesDir,"alpaca-v1.enc").readBytes()
        assertFalse(String(bytes,Charsets.UTF_8).contains("mock-private-value"))
        assertFalse(String(bytes,Charsets.UTF_8).contains("mock-public-key"))
        val ks=KeyStore.getInstance("AndroidKeyStore").apply{load(null)}
        assertNull(ks.getKey("oat.alpaca.v1",null).encoded)
    }
    @Test fun repeatedSaveHasDifferentIvAndCiphertext() {
        val vault=AlpacaVault(context);val file=File(context.noBackupFilesDir,"alpaca-v1.enc")
        vault.save("mock-public-key","mock-private-value");val before=file.readBytes()
        vault.save("mock-public-key","mock-private-value");assertFalse(before.contentEquals(file.readBytes()))
    }
    @Test fun modifiedCiphertextFailsClosed() {
        val vault=AlpacaVault(context);vault.save("mock-public-key","mock-private-value")
        val file=File(context.noBackupFilesDir,"alpaca-v1.enc");val original=file.readBytes();val changed=original.copyOf()
        changed[changed.size-1]=(changed.last().toInt() xor 1).toByte()
        try {file.writeBytes(changed);try{vault.read();fail("tamper accepted")}catch(_:javax.crypto.AEADBadTagException){}}
        finally {file.writeBytes(original)}
    }
    @Test fun backupDisabledAndMonitorCannotBeStartedByExternalApp() {
        assertEquals(0,context.applicationInfo.flags and ApplicationInfo.FLAG_ALLOW_BACKUP)
        val info=context.packageManager.getServiceInfo(ComponentName(context,AlpacaMonitorService::class.java),0)
        assertFalse(info.exported)
    }
    @Test fun monitoringRequiresExplicitActiveSession() {
        AlpacaRuntime.stop();assertFalse(AlpacaRuntime.get(context).enabled)
        try{AlpacaMonitorService.start(context);fail("unarmed monitor started")}catch(_:IllegalStateException){}
    }
    @Test fun savedStatusSurvivesNewVaultWithoutReturningSecrets() {
        val access=AlpacaAccess(AlpacaVault(context),AlpacaPreferences(context))
        access.save("mock-public-key","mock-private-value")
        assertEquals("readable",AlpacaAccess(AlpacaVault(context),AlpacaPreferences(context)).keyState())
    }
    @Test fun tamperedStorageIsReportedUnreadable() {
        val vault=AlpacaVault(context);vault.save("mock-public-key","mock-private-value")
        val file=File(context.noBackupFilesDir,"alpaca-v1.enc");val original=file.readBytes();val changed=original.copyOf()
        changed[changed.size-1]=(changed.last().toInt() xor 1).toByte()
        try{file.writeBytes(changed);assertEquals("unreadable",AlpacaAccess(AlpacaVault(context),AlpacaPreferences(context)).keyState())}
        finally{file.writeBytes(original)}
    }
    @Test fun storedSettingsSurviveRecreationWithoutAutomaticConnection() {
        AlpacaRuntime.stop()
        val access=AlpacaAccess(AlpacaVault(context),AlpacaPreferences(context))
        access.save("mock-public-key","mock-private-value")
        val value=AlpacaSettings(true,"sip","extended",listOf("TSLA"));access.saveSettings(value)
        val restored=AlpacaAccess(AlpacaVault(context),AlpacaPreferences(context))
        assertEquals(value,restored.readSettings());assertFalse(AlpacaRuntime.get(context).enabled)
        try{restored.start(false){fail("connection without button")};fail("consent accepted")}
        catch(e:AlpacaAccessFailure){assertEquals("CONSENT_REQUIRED",e.code)}
    }
    @Test fun secureStorageSettingsAndSessionIntegrateOverMockDataTransport() {
        val access=AlpacaAccess(AlpacaVault(context),AlpacaPreferences(context))
        access.save("mock-public-key","mock-private-value");access.saveSettings(AlpacaSettings(true,"iex","regular",listOf("NVDA")))
        val requests=CopyOnWriteArrayList<Request>()
        val transport=AlpacaSession.client().newBuilder().addInterceptor{chain->
            val request=chain.request();requests.add(request)
            assertEquals("GET",request.method);assertEquals("data.alpaca.markets",request.url.host)
            assertEquals("mock-public-key",request.header("APCA-API-KEY-ID"));assertEquals("mock-private-value",request.header("APCA-API-SECRET-KEY"))
            Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("mock")
                .body("""{"bars":{"NVDA":[{"t":"2026-10-13T15:00:00Z","o":100,"h":102,"l":99,"c":101,"v":10}]}}""".toResponseBody()).build()
        }.build()
        val sockets=object:WebSocket.Factory{
            override fun newWebSocket(request:Request,listener:WebSocketListener):WebSocket {
            val socket=object:WebSocket {
                override fun request()=request
                override fun queueSize()=0L
                override fun send(text:String):Boolean {
                    if(JSONObject(text).getString("action")=="auth")listener.onMessage(this,"""[{"T":"success","msg":"authenticated"}]""")
                    return true
                }
                override fun send(bytes:ByteString)=false
                override fun close(code:Int,reason:String?)=true
                override fun cancel(){}
            }
            listener.onOpen(socket,Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(101).message("mock").build());return socket
            }
        }
        val session=AlpacaSession({AlpacaVault(context).read()},{Instant.parse("2026-10-13T15:01:15Z").toEpochMilli()},transport,sockets)
        try {
            val restored=AlpacaAccess(AlpacaVault(context),AlpacaPreferences(context))
            restored.start(true){session.start(it.feed,it.session,it.symbols)}
            val end=System.nanoTime()+5_000_000_000L
            while(JSONObject(session.snapshot()).getString("testStatus")!="succeeded"&&System.nanoTime()<end)Thread.sleep(20)
            val snapshot=JSONObject(session.snapshot())
            assertEquals("succeeded",snapshot.getString("testStatus"));assertEquals("CONNECTED_DATA",snapshot.getString("testCode"))
            assertEquals(1,requests.size);assertEquals(1,snapshot.getJSONObject("bars").getJSONArray("NVDA").length())
            assertFalse(snapshot.toString().contains("mock-private-value"))
        }finally{session.close()}
    }
}
