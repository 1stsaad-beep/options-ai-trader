package com.optionsaitrader.options_ai_trader

import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.security.MessageDigest
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject

/** Immutable content-addressed physical storage; logical ledger bytes stay exact.
 * Stage/fsync all chunks before the caller atomically publishes the manifest.
 * No garbage collection: committed history and interrupted-stage chunks survive.
 */
class PaperSegments(private val directory:File,private val syncDirectory:(File)->Unit) {
    companion object {
        const val FORMAT="paper-segment-manifest-v1"
        const val MAX_BYTES=64*1024*1024
        const val MAX_MANIFEST=512*1024
        private const val MIN_CHUNK=32*1024
        private const val MAX_CHUNK=128*1024
        private val names=Regex("[0-9a-f]{64}")
        // Rolling hash only chooses boundaries. SHA-256 verifies all stored bytes.
        private val gear=java.util.Random(61920261014L).let{r->LongArray(256){r.nextLong()}}
        fun digest(bytes:ByteArray):String=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it)}
        fun utf8(bytes:ByteArray):String=Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()
    }
    private fun ensureDirectory() {
        if(!directory.exists()) {check(directory.mkdirs());directory.parentFile?.let(syncDirectory)}
        check(directory.isDirectory)
    }
    private fun bytes(file:File,limit:Int):ByteArray {
        check(file.canonicalFile.parentFile==directory.canonicalFile){"Segment outside storage"}
        check(file.isFile&&file.length()<=limit)
        return file.inputStream().use{input->
            val output=java.io.ByteArrayOutputStream();val buffer=ByteArray(8192)
            while(true){val count=input.read(buffer);if(count<0)break;check(output.size()+count<=limit);output.write(buffer,0,count)}
            output.toByteArray()
        }
    }
    private fun immutable(name:String,data:ByteArray) {
        val target=File(directory,name)
        if(target.exists()){check(bytes(target,data.size).contentEquals(data)){"Immutable segment differs"};return}
        val pending=File(directory,"pending-${UUID.randomUUID()}")
        FileOutputStream(pending).use{it.write(data);it.flush();it.fd.sync()}
        check(pending.renameTo(target)){"Segment publication failed"}
    }
    fun stage(data:ByteArray):String {
        require(data.isNotEmpty()&&data.size<=MAX_BYTES);ensureDirectory()
        val chunks=JSONArray();var start=0;var rolling=0L
        fun append(end:Int) {
            val chunk=data.copyOfRange(start,end);val sha=digest(chunk)
            immutable("$sha.bin",chunk);chunks.put(JSONObject().put("sha256",sha).put("length",chunk.size))
            start=end;rolling=0L
        }
        for(index in data.indices) {
            rolling=(rolling shl 1)+gear[data[index].toInt() and 255]
            val size=index+1-start
            if(size>=MIN_CHUNK&&((rolling and 65535L)==0L||size>=MAX_CHUNK))append(index+1)
        }
        if(start<data.size)append(data.size)
        syncDirectory(directory) // Every referenced rename precedes the root commit.
        val manifest=JSONObject().put("storageFormat",FORMAT).put("length",data.size)
            .put("sha256",digest(data)).put("segments",chunks).toString()
        check(manifest.toByteArray(Charsets.UTF_8).size<=MAX_MANIFEST)
        return manifest
    }
    fun preserveLegacy(data:ByteArray) {
        val manifest=stage(data)
        immutable("legacy-${digest(data)}.json",manifest.toByteArray(Charsets.UTF_8));syncDirectory(directory)
    }
    fun restore(text:String):ByteArray {
        require(text.toByteArray(Charsets.UTF_8).size<=MAX_MANIFEST)
        val root=JSONObject(text)
        require(root.length()==4&&root.getString("storageFormat")==FORMAT)
        fun size(o:JSONObject,key:String,max:Int):Int {
            val value=o.get(key);require(value is Int&&value in 1..max);return value
        }
        val length=size(root,"length",MAX_BYTES);val expected=root.getString("sha256");require(names.matches(expected))
        val parts=root.getJSONArray("segments");require(parts.length() in 1..4096)
        val result=ByteArray(length);var offset=0
        for(i in 0 until parts.length()) {
            val part=parts.getJSONObject(i);require(part.length()==2)
            val sha=part.getString("sha256");require(names.matches(sha));val count=size(part,"length",MAX_CHUNK)
            require(count<=length-offset)
            val data=bytes(File(directory,"$sha.bin"),MAX_CHUNK)
            check(data.size==count&&digest(data)==sha){"Segment integrity failed"}
            data.copyInto(result,offset);offset+=count
        }
        check(offset==length&&digest(result)==expected){"Ledger manifest integrity failed"}
        return result
    }
}
