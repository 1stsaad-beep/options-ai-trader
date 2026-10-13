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

/** Disposable emulator only; mock strings, no network and no provider credentials. */
@RunWith(AndroidJUnit4::class)
class AlpacaVaultDeviceTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
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
}
