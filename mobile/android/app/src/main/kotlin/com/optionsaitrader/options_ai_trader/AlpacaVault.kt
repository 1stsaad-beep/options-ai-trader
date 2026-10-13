package com.optionsaitrader.options_ai_trader

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject

/** Secrets never leave native code after saving. No read/reveal MethodChannel operation. */
class AlpacaVault(context: Context) {
    private val file = AtomicFile(File(context.noBackupFilesDir, "alpaca_credentials.aesgcm"))
    private val alias = "oat.alpaca.data.v1"
    private val aad = "oat.alpaca.data.v1".toByteArray(Charsets.UTF_8)
    private fun key(create: Boolean): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        check(create)
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).build())
        }.generateKey()
    }
    fun present(): Boolean = file.baseFile.exists()
    @Synchronized fun save(id: String, secret: String) {
        require(id.matches(Regex("[A-Za-z0-9_-]{8,128}")) && secret.matches(Regex("[A-Za-z0-9_-]{8,256}")))
        val plain = JSONObject().put("id", id).put("secret", secret).toString().toByteArray(Charsets.UTF_8)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key(true)); cipher.updateAAD(aad)
        var output: java.io.FileOutputStream? = null
        try {
            val encoded = byteArrayOf(1, cipher.iv.size.toByte()) + cipher.iv + cipher.doFinal(plain)
            output = file.startWrite(); output.write(encoded); file.finishWrite(output)
        } catch (e: Exception) { file.failWrite(output); throw e }
        finally { plain.fill(0) }
    }
    @Synchronized fun credentials(): Pair<String, String> {
        val bytes = file.openRead().use { it.readBytes() }
        check(bytes.size in 30..2048 && bytes[0].toInt() == 1 && bytes[1].toInt() == 12)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(false), GCMParameterSpec(128, bytes.copyOfRange(2, 14)))
        cipher.updateAAD(aad)
        val plain = cipher.doFinal(bytes.copyOfRange(14, bytes.size))
        try { val j = JSONObject(String(plain, Charsets.UTF_8)); return j.getString("id") to j.getString("secret") }
        finally { plain.fill(0) }
    }
    @Synchronized fun forget() {
        file.delete()
        KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry(alias) }
    }
}
