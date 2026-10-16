package com.optionsaitrader.options_ai_trader

import java.io.File
import org.json.JSONObject

/** Physical isolation of optional research from the financial receipt journal.
 * The lossless template retains every original JSON number/string lexeme and
 * field order; parsing/re-encoding doubles would break captured source digests.
 * Missing optional chunks become explicit opaque references, never empty data.
 */
class PaperIndependentStore(private val directory:File, private val syncDirectory:(File)->Unit) {
    companion object {
        const val FORMAT="paper-independent-manifest-v2"
        const val UNAVAILABLE="paper-optional-archive-v1"
        val OPTIONAL=setOf("waveArchive","optionArchive","barArchive")
        private const val MAX_ROOT=2*1024*1024
    }
    private fun parts(name:String)=PaperSegments(File(directory,name),syncDirectory)
    data class Field(val key:String,val start:Int,val end:Int)

    /** Only find top-level value spans. JSONObject separately validates values. */
    private fun fields(text:String):List<Field> {
        var i=0
        fun spaces(){while(i<text.length&&text[i].isWhitespace())i++}
        fun stringEnd():Int {
            require(i<text.length&&text[i]=='"');i++
            while(i<text.length){val c=text[i++];if(c=='\\'){require(i<text.length);i++}else if(c=='"')return i}
            error("Unclosed JSON string")
        }
        spaces();require(i<text.length&&text[i++]=='{');spaces()
        val result=mutableListOf<Field>();val keys=mutableSetOf<String>()
        if(i<text.length&&text[i]=='}'){i++;spaces();require(i==text.length);return result}
        while(true) {
            spaces();val keyStart=i;val keyEnd=stringEnd();spaces();require(i<text.length&&text[i++]==':');spaces()
            val key=JSONObject("{${text.substring(keyStart,keyEnd)}:null}").keys().next()
            require(keys.add(key)){"Duplicate ledger field"}
            val start=i;var depth=0
            while(i<text.length) {
                when(text[i]) {
                    '"'->{stringEnd();continue}
                    '[','{'->{depth++;require(depth<=64)}
                    ']'->{depth--;require(depth>=0)}
                    '}'->{if(depth==0)break;depth--}
                    ','->if(depth==0)break
                }
                i++
            }
            require(depth==0);var end=i;while(end>start&&text[end-1].isWhitespace())end--
            require(end>start);result.add(Field(key,start,end));spaces();require(i<text.length)
            if(text[i++]=='}')break
            require(text[i-1]==',')
        }
        spaces();require(i==text.length)
        return result
    }
    private fun validLedger(text:String):List<Field> {
        val result=fields(text);val root=JSONObject(text)
        require(!root.has("storageFormat")&&root.getInt("version")==1)
        require(root.get("accounts") is org.json.JSONArray&&root.get("journal") is org.json.JSONArray)
        return result
    }
    private fun replace(text:String,fields:List<Field>,values:Map<String,String>):String {
        val out=StringBuilder();var offset=0
        for(field in fields){val value=values[field.key]?:continue
            out.append(text,offset,field.start);out.append(value);offset=field.end}
        return out.append(text,offset,text.length).toString()
    }
    private fun root(text:String):JSONObject {
        require(text.toByteArray(Charsets.UTF_8).size<=MAX_ROOT)
        val root=JSONObject(text)
        require(root.length()==3&&root.getString("storageFormat")==FORMAT)
        val archives=root.getJSONObject("archives")
        require(archives.keys().asSequence().all{it in OPTIONAL})
        require(root.get("core") is String)
        for(key in archives.keys())require(archives.get(key) is String)
        return root
    }
    fun stage(text:String,previous:String?=null):String {
        require(text.toByteArray(Charsets.UTF_8).size<=PaperSegments.MAX_BYTES)
        val fields=validLedger(text);val archives=JSONObject();val substitutions=mutableMapOf<String,String>()
        val previousArchives=previous?.let{root(it).getJSONObject("archives")}
        if(!directory.exists()){check(directory.mkdirs());directory.parentFile?.let(syncDirectory)}
        check(directory.isDirectory)
        for(field in fields.filter{it.key in OPTIONAL}) {
            val value=text.substring(field.start,field.end)
            val candidate=try{JSONObject(value)}catch(_:Exception){null}
            val manifest=if(candidate?.optString("storageUnavailable")==UNAVAILABLE) {
                require(candidate.length()==2&&previousArchives?.has(field.key)==true){"Unavailable archive cannot be imported"}
                val original=previousArchives!!.getString(field.key)
                require(candidate.getString("sha256")==PaperSegments.digest(original.toByteArray(Charsets.UTF_8))){"Archive reference changed"}
                original // Keep the physical original even when it is unreadable.
            }else parts(field.key).stage(value.toByteArray(Charsets.UTF_8))
            archives.put(field.key,manifest);substitutions[field.key]="null"
        }
        val core=parts("financial").stage(replace(text,fields,substitutions).toByteArray(Charsets.UTF_8))
        val result=JSONObject().put("storageFormat",FORMAT).put("core",core).put("archives",archives).toString()
        require(result.toByteArray(Charsets.UTF_8).size<=MAX_ROOT)
        return result
    }
    fun restore(text:String):String {
        val root=root(text);val archives=root.getJSONObject("archives")
        val core=PaperSegments.utf8(parts("financial").restore(root.getString("core")))
        val fields=validLedger(core);val optional=fields.filter{it.key in OPTIONAL}
        require(optional.map{it.key}.toSet()==archives.keys().asSequence().toSet())
        val values=mutableMapOf<String,String>();var size=core.toByteArray(Charsets.UTF_8).size
        for(field in optional) {
            require(core.substring(field.start,field.end)=="null")
            val manifest=archives.getString(field.key)
            val value=try {
                require(JSONObject(manifest).getInt("length")<=PaperSegments.MAX_BYTES-size+4)
                PaperSegments.utf8(parts(field.key).restore(manifest))
            }catch(_:Exception) {
                JSONObject().put("storageUnavailable",UNAVAILABLE)
                    .put("sha256",PaperSegments.digest(manifest.toByteArray(Charsets.UTF_8))).toString()
            }
            size+=value.toByteArray(Charsets.UTF_8).size-4;require(size<=PaperSegments.MAX_BYTES)
            values[field.key]=value
        }
        return replace(core,fields,values)
    }
}
