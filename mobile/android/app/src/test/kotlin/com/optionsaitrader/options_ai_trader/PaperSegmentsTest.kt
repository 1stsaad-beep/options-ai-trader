package com.optionsaitrader.options_ai_trader

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject
import java.io.File
import java.nio.file.Files
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption

class PaperSegmentsTest {
    private fun sync(directory:File){FileChannel.open(directory.toPath(),StandardOpenOption.READ).use{it.force(true)}}
    private fun sample(count:Int=6000):String {
        val random=java.util.Random(2314)
        return "{\"version\":1,\"accounts\":[],\"journal\":["+(0 until count).joinToString(","){"{\"id\":$it,\"text\":\"أسهم مرصودة ${random.nextLong()} ${random.nextLong()}\"}"}+"]}"
    }
    private fun run(block:(File,PaperSegments)->Unit){val dir=Files.createTempDirectory("paper-segments-fixture").toFile();try{block(dir,PaperSegments(File(dir,"parts"),::sync))}finally{dir.deleteRecursively()}}
    private fun rejected(block:()->Unit){try{block();fail("invalid storage accepted")}catch(_:Exception){}}
    @Test fun exactUnicodeBytesAndFreshReaderRoundTrip()=run{dir,store->
        val original=sample().toByteArray(Charsets.UTF_8);val manifest=store.stage(original)
        assertArrayEquals(original,PaperSegments(File(dir,"parts"),::sync).restore(manifest))
        assertEquals(sample(),PaperSegments.utf8(store.restore(manifest)))
        assertTrue(manifest.toByteArray().size<original.size/20)
    }
    @Test fun insertionAndAppendReuseUnchangedImmutableChunks()=run{dir,store->
        val first=sample(14000);val before=store.stage(first.toByteArray());val parts=File(dir,"parts")
        val old=parts.listFiles()!!.associate{it.name to it.lastModified()}
        val changed=first.replace("\"accounts\":[]","\"accounts\":[{\"cash\":12345}]").dropLast(2)+",{\"new\":true}]}"
        val next=store.stage(changed.toByteArray())
        assertEquals(changed,PaperSegments.utf8(store.restore(next)));assertEquals(first,PaperSegments.utf8(store.restore(before)))
        val written=parts.listFiles()!!.filter{it.name !in old}.sumOf{it.length()}
        assertTrue("incremental writes $written",written<first.toByteArray().size/2)
        for((name,time) in old)assertEquals(time,File(parts,name).lastModified())
    }
    @Test fun interruptedStageLeavesPreviousPublishedManifestReadable()=run{dir,store->
        val original=sample();val published=store.stage(original.toByteArray())
        val failing=PaperSegments(File(dir,"parts")){throw java.io.IOException("fixture directory sync failure")}
        rejected{failing.stage((original+" ").toByteArray())}
        assertEquals(original,PaperSegments.utf8(store.restore(published)))
        assertEquals(original+" ",PaperSegments.utf8(store.restore(store.stage((original+" ").toByteArray()))))
    }
    @Test fun missingAndChangedChunksCannotBecomeAnEmptyLedger()=run{dir,store->
        val manifest=store.stage(sample().toByteArray());val sha=JSONObject(manifest).getJSONArray("segments").getJSONObject(0).getString("sha256")
        val part=File(dir,"parts/$sha.bin");val bytes=part.readBytes();part.writeBytes(bytes.copyOf().also{it[0]=(it[0].toInt() xor 1).toByte()})
        rejected{store.restore(manifest)};rejected{store.stage(sample().toByteArray())}
        part.delete();rejected{store.restore(manifest)}
    }
    @Test fun manifestTamperingAndTraversalFailClosed()=run{_,store->
        val original=store.stage(sample().toByteArray())
        for(mode in listOf("digest","length","path","fraction","extra","reorder")) {
            val root=JSONObject(original);val parts=root.getJSONArray("segments")
            when(mode){
                "digest"->root.put("sha256","0".repeat(64))
                "length"->root.put("length",root.getInt("length")-1)
                "path"->parts.getJSONObject(0).put("sha256","../outside")
                "fraction"->parts.getJSONObject(0).put("length",1.5)
                "extra"->root.put("override",true)
                "reorder"->{val first=parts.get(0);parts.put(0,parts.get(1));parts.put(1,first)}
            }
            rejected{store.restore(root.toString())}
        }
    }
    @Test fun legacyOriginalIsRetainedAsVerifiedManifest()=run{dir,store->
        val original=sample();store.preserveLegacy(original.toByteArray());store.preserveLegacy(original.toByteArray())
        val anchors=File(dir,"parts").listFiles()!!.filter{it.name.startsWith("legacy-")};assertEquals(1,anchors.size)
        store.stage((original+" ").toByteArray());assertEquals(original,PaperSegments.utf8(store.restore(anchors.single().readText())))
    }
    @Test fun oversizedAndInvalidUtf8DoNotProduceLogicalLedger()=run{_,store->
        rejected{store.stage(ByteArray(PaperSegments.MAX_BYTES+1))}
        rejected{PaperSegments.utf8(byteArrayOf(0xc0.toByte(),0x80.toByte()))}
        rejected{store.restore(" ".repeat(PaperSegments.MAX_MANIFEST+1))}
    }
    @Test fun repeatedAppendRetainsAllHistoricalManifestsWithBoundedIncrementalWrites()=run{dir,store->
        var value=sample(12000);val roots=mutableListOf<Pair<String,String>>()
        var logicalWritten=0L
        repeat(24){i->
            roots.add(store.stage(value.toByteArray()) to value);logicalWritten+=value.toByteArray().size
            value=value.dropLast(2)+",{\"append\":$i}]}"
        }
        for((manifest,expected) in roots)assertEquals(expected,PaperSegments.utf8(store.restore(manifest)))
        assertTrue(File(dir,"parts").listFiles()!!.sumOf{it.length()}<logicalWritten/3)
    }
}
