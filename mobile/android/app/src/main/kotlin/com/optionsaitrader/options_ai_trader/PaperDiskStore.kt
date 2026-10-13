package com.optionsaitrader.options_ai_trader

import android.util.AtomicFile
import java.io.File
import java.io.FileNotFoundException
import org.json.JSONObject

/** App-private, crash-safe ledger bytes. No credentials or execution authority.
 * Expected-byte CAS is shared across Activity instances; no cached preferences
 * read is accepted as proof of a disk commit. Android backup remains disabled.
 */
class PaperDiskStore(private val file: File) {
    companion object { private val lock=Any(); private const val MAX_BYTES=64*1024*1024 }
    private fun readLocked(): String? {
        val atomic=AtomicFile(file)
        return try {
            atomic.openRead().use { input ->
                check(input.channel.size()<=MAX_BYTES)
                val bytes=input.readBytes();check(bytes.size<=MAX_BYTES)
                String(bytes,Charsets.UTF_8)
            }
        } catch(e:FileNotFoundException) {
            if(file.exists()||File(file.path+".bak").exists()||File(file.path+".initialized").exists())throw e
            null
        }
    }
    fun read():String?=synchronized(lock){readLocked()}
    fun write(expected:String?,next:String):Boolean=synchronized(lock) {
        val bytes=next.toByteArray(Charsets.UTF_8);require(bytes.size<=MAX_BYTES)
        val parsed=JSONObject(next);require(parsed.getInt("version")==1)
        require(parsed.get("accounts") is org.json.JSONArray && parsed.get("journal") is org.json.JSONArray)
        check(readLocked()==expected){"Ledger changed"}
        file.parentFile?.mkdirs()
        val atomic=AtomicFile(file);val output=atomic.startWrite()
        try {
            output.write(bytes);output.flush();output.fd.sync();atomic.finishWrite(output)
        } catch(e:Exception) {atomic.failWrite(output);throw e}
        check(readLocked()==next){"Ledger readback differs"}
        val marker=File(file.path+".initialized")
        if(!marker.exists())java.io.FileOutputStream(marker).use {it.write("v1".toByteArray());it.flush();it.fd.sync()}
        true
    }
}
