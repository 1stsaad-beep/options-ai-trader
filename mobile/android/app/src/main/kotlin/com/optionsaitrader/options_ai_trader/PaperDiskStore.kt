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
    companion object { private val lock=Any(); private val uncertain=mutableSetOf<String>(); private const val MAX_BYTES=PaperSegments.MAX_BYTES }
    private fun syncDirectory(directory:File) {
        val descriptor=android.system.Os.open(directory.path,android.system.OsConstants.O_RDONLY or android.system.OsConstants.O_DIRECTORY,0)
        try{android.system.Os.fsync(descriptor)}finally{android.system.Os.close(descriptor)}
    }
    private val segments=PaperSegments(File(file.path+".segments"),::syncDirectory)
    private fun logical(raw:String):String {
        if(JSONObject(raw).optString("storageFormat")==PaperSegments.FORMAT)return PaperSegments.utf8(segments.restore(raw))
        val parsed=JSONObject(raw)
        require(parsed.getInt("version")==1&&parsed.get("accounts") is org.json.JSONArray&&parsed.get("journal") is org.json.JSONArray)
        return raw
    }
    private fun readLocked(): String? {
        val atomic=AtomicFile(file)
        return try {
            atomic.openRead().use { input ->
                check(input.channel.size()<=MAX_BYTES)
                val bytes=input.readBytes();check(bytes.size<=MAX_BYTES)
                logical(PaperSegments.utf8(bytes))
            }
        } catch(e:FileNotFoundException) {
            if(file.exists()||File(file.path+".bak").exists()||File(file.path+".initialized").exists())throw e
            null
        }
    }
    fun read():String?=synchronized(lock){check(file.path !in uncertain){"Storage durability uncertain; restart required"};readLocked()}
    fun write(expected:String?,next:String):Boolean=synchronized(lock) {
        check(file.path !in uncertain){"Storage durability uncertain; restart required"}
        val bytes=next.toByteArray(Charsets.UTF_8);require(bytes.size<=MAX_BYTES)
        val parsed=JSONObject(next);require(parsed.getInt("version")==1)
        require(parsed.get("accounts") is org.json.JSONArray && parsed.get("journal") is org.json.JSONArray)
        check(readLocked()==expected){"Ledger changed"}
        file.parentFile?.mkdirs()
        // Preserve the original legacy ledger losslessly before its first physical migration.
        if(file.exists()) {
            val raw=file.readText(Charsets.UTF_8)
            if(JSONObject(raw).optString("storageFormat")!=PaperSegments.FORMAT)segments.preserveLegacy(raw.toByteArray(Charsets.UTF_8))
        }
        val manifest=segments.stage(bytes).toByteArray(Charsets.UTF_8)
        val atomic=AtomicFile(file);val output=atomic.startWrite()
        try {
            output.write(manifest);output.flush();output.fd.sync();atomic.finishWrite(output)
        } catch(e:Exception) {uncertain.add(file.path);atomic.failWrite(output);throw e}
        try {
        file.parentFile?.let(::syncDirectory)
        check(readLocked()==next){"Ledger readback differs"}
        val marker=File(file.path+".initialized")
        if(!marker.exists())java.io.FileOutputStream(marker).use {it.write("v1".toByteArray());it.flush();it.fd.sync()}
        file.parentFile?.let(::syncDirectory)
        true
        }catch(e:Exception){uncertain.add(file.path);throw e}
    }
}
