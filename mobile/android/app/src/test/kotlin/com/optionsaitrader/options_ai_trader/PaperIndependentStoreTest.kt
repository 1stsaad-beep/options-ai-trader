package com.optionsaitrader.options_ai_trader

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject
import java.io.File
import java.nio.file.Files
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption

class PaperIndependentStoreTest {
    private fun sync(directory:File){FileChannel.open(directory.toPath(),StandardOpenOption.READ).use{it.force(true)}}
    private fun run(block:(File,PaperIndependentStore)->Unit){val dir=Files.createTempDirectory("paper-independent-fixture").toFile();try{block(dir,PaperIndependentStore(File(dir,"parts"),::sync))}finally{dir.deleteRecursively()}}
    private fun rejected(block:()->Unit){try{block();fail("invalid isolated storage accepted")}catch(_:Exception){}}
    private fun sample()=""" {"version":1,"accounts":[], "barArchive" : {"rows":[1.0,1e3,"أصل {x}, \"قوس\"","\\"]},"journal":[{"source":1.0}],"optionArchive":null,"waveArchive":{"original":true}} """
    private fun chunk(dir:File,root:String,key:String):File {
        val parsed=JSONObject(root)
        val manifest=if(key=="financial")parsed.getString("core")else parsed.getJSONObject("archives").getString(key)
        val sha=JSONObject(manifest).getJSONArray("segments").getJSONObject(0).getString("sha256")
        return File(dir,"parts/$key/$sha.bin")
    }
    @Test fun exactLexemesWhitespaceFieldOrderAndUnicodeRoundTrip()=run{dir,store->
        val text=sample();val root=store.stage(text)
        assertEquals(text,PaperIndependentStore(File(dir,"parts"),::sync).restore(root))
        val core=PaperSegments(File(dir,"parts/financial"),::sync).restore(JSONObject(root).getString("core"))
        assertTrue(PaperSegments.utf8(core).contains("\"source\":1.0"))
    }
    @Test fun missingOptionalChunkKeepsFinancialOriginalAndOpaqueReference()=run{dir,store->
        val root=store.stage(sample());assertTrue(chunk(dir,root,"barArchive").delete())
        val recovered=store.restore(root);val value=JSONObject(recovered)
        assertEquals(1,value.getJSONArray("journal").length())
        assertEquals(PaperIndependentStore.UNAVAILABLE,value.getJSONObject("barArchive").getString("storageUnavailable"))
        assertTrue(recovered.contains("\"source\":1.0"));assertTrue(value.getJSONObject("waveArchive").getBoolean("original"))
        val next=recovered.replace("\"accounts\":[]","\"accounts\":[{\"cash\":12345}]")
        val committed=store.stage(next,root)
        assertEquals(next,store.restore(committed))
        assertEquals(JSONObject(root).getJSONObject("archives").getString("barArchive"),JSONObject(committed).getJSONObject("archives").getString("barArchive"))
    }
    @Test fun corruptedOptionalChunkIsPreservedWhileCoreCanAdvance()=run{dir,store->
        val root=store.stage(sample());val part=chunk(dir,root,"waveArchive");part.writeText("corrupt fixture")
        val recovered=store.restore(root);val next=recovered.replace("\"accounts\":[]","\"accounts\":[{\"cash\":7}]")
        assertEquals(next,store.restore(store.stage(next,root)))
        assertEquals("corrupt fixture",part.readText())
    }
    @Test fun damagedFinancialChunkNeverBecomesAnEmptyOrWritableBook()=run{dir,store->
        val root=store.stage(sample());chunk(dir,root,"financial").writeText("corrupt fixture")
        rejected{store.restore(root)}
    }
    @Test fun unavailableReferencesCannotBeImportedOrRepointed()=run{dir,store->
        val root=store.stage(sample());chunk(dir,root,"barArchive").delete();val recovered=store.restore(root)
        rejected{store.stage(recovered)}
        val value=JSONObject(recovered);value.getJSONObject("barArchive").put("sha256","0".repeat(64))
        rejected{store.stage(value.toString(),root)}
    }
    @Test fun unchangedOptionalArchivesAreNotRewrittenByFinancialUpdates()=run{dir,store->
        val root=store.stage(sample());val files=listOf("waveArchive","optionArchive","barArchive").associateWith{chunk(dir,root,it).readBytes()}
        var previous=root
        repeat(30){i->previous=store.stage(sample().replace("\"accounts\":[]","\"accounts\":[{\"cash\":$i}]"),previous)}
        for((key,bytes) in files){assertArrayEquals(bytes,chunk(dir,previous,key).readBytes());assertEquals(1,File(dir,"parts/$key").listFiles()!!.size)}
    }
    @Test fun interruptedStageCannotChangePublishedRootOrOriginalChunks()=run{dir,store->
        val root=store.stage(sample());val fail=PaperIndependentStore(File(dir,"parts")){throw java.io.IOException("fixture sync")}
        rejected{fail.stage(sample().replace("\"source\":1.0","\"source\":2.0"),root)}
        assertEquals(sample(),store.restore(root))
    }
    @Test fun duplicateRootKeysUnknownManifestAndBrokenTemplateAreRejected()=run{_,store->
        rejected{store.stage("""{"version":1,"accounts":[],"journal":[],"barArchive":{},"barArchive":{}}""")}
        val root=JSONObject(store.stage(sample()));root.put("injected",true);rejected{store.restore(root.toString())}
        val other=JSONObject(store.stage(sample()));other.getJSONObject("archives").remove("waveArchive");rejected{store.restore(other.toString())}
    }
    @Test fun optionalWritePressureRetainsOldArchiveAndPermitsCoreOnlyRetry()=run{dir,store->
        val original=sample();val root=store.stage(original)
        val pressure=PaperIndependentStore(File(dir,"parts")){directory->
            if(directory.name=="barArchive")throw java.io.IOException("fixture optional pressure")
            sync(directory)
        }
        try{pressure.stage(original.replace("\"rows\":[1.0","\"rows\":[2.0"),root);fail("optional staging unexpectedly passed")}
        catch(_:PaperOptionalStageFailure){}
        assertEquals(original,store.restore(root))
        val next=original.replace("\"accounts\":[]","\"accounts\":[{\"cash\":42}]")
        val committed=pressure.stage(next,root);assertEquals(next,store.restore(committed))
        assertEquals(JSONObject(root).getJSONObject("archives").toString(),JSONObject(committed).getJSONObject("archives").toString())
    }
    @Test fun financialWriteFailureCannotBeMisclassifiedAsOptional()=run{dir,store->
        val root=store.stage(sample())
        val pressure=PaperIndependentStore(File(dir,"parts")){directory->
            if(directory.name=="financial")throw java.io.IOException("fixture financial pressure")
            sync(directory)
        }
        try{pressure.stage(sample().replace("\"source\":1.0","\"source\":2.0"),root);fail("financial staging unexpectedly passed")}
        catch(error:Exception){assertFalse(error is PaperOptionalStageFailure)}
        assertEquals(sample(),store.restore(root))
    }
}
