package com.optionsaitrader.options_ai_trader

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import org.json.JSONObject
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** App-private, excluded from backup. Plaintext never returned over the platform channel. */
internal class AlpacaVault(context: Context):AlpacaCredentials {
    private val file=AtomicFile(File(context.noBackupFilesDir,"alpaca-v1.enc"))
    private val alias="oat.alpaca.v1"
    private fun key(create:Boolean): SecretKey {
        val ks=KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if(ks.containsAlias(alias)) return ks.getKey(alias,null) as SecretKey
        check(create) // Reading cannot silently create a replacement key for existing ciphertext.
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").run {
            init(KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).build()); generateKey()
        }
    }
    override fun exists()=file.baseFile.exists()||File(file.baseFile.path+".bak").exists()
    @Synchronized override fun save(id:String,secret:String) {
        require(AlpacaAccess.validKeys(id,secret))
        val bytes=JSONObject().put("id",id).put("secret",secret).toString().toByteArray(Charsets.UTF_8)
        val cipher=Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE,key(true)) }
        val encrypted=try { cipher.doFinal(bytes) } finally { bytes.fill(0) }
        val out=file.startWrite()
        try { out.write(cipher.iv);out.write(encrypted);file.finishWrite(out) }
        catch(e:Exception){file.failWrite(out);throw e}
    }
    @Synchronized override fun read(): Pair<String,String> {
        val bytes=file.readFully();require(bytes.size in 29..4096)
        val cipher=Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE,key(false),GCMParameterSpec(128,bytes.copyOfRange(0,12)))
        }
        val plain=cipher.doFinal(bytes.copyOfRange(12,bytes.size))
        return try { val data=JSONObject(String(plain,Charsets.UTF_8));Pair(data.getString("id"),data.getString("secret")) }
        finally { plain.fill(0) }
    }
}
