package com.optionsaitrader.options_ai_trader

import org.json.JSONArray
import org.json.JSONObject

internal interface AlpacaCredentials {
    fun exists():Boolean
    fun read():Pair<String,String>
    fun save(id:String,secret:String)
}
internal interface AlpacaSettingsStore {
    fun read():AlpacaSettings
    fun write(settings:AlpacaSettings)
}
internal class AlpacaAccessFailure(val code:String):Exception(code)

internal data class AlpacaSettings(val real:Boolean=false,val feed:String="iex",val session:String="regular",
    val symbols:List<String> = listOf("NVDA","AAPL","TSLA")) {
    fun validated():AlpacaSettings {
        if(!AlpacaPolicy.feed(feed)||session !in listOf("regular","extended")||symbols.size !in 1..10||
            symbols.distinct().size!=symbols.size||symbols.any{!AlpacaPolicy.symbol(it)})throw AlpacaAccessFailure("INVALID_SETTINGS")
        return this
    }
    fun json()=JSONObject().put("real",real).put("feed",feed).put("session",session).put("symbols",JSONArray(symbols))
    companion object {
        fun parse(raw:String):AlpacaSettings {
            val j=JSONObject(raw);val rows=j.getJSONArray("symbols")
            return AlpacaSettings(j.getBoolean("real"),j.getString("feed"),j.getString("session"),
                (0 until rows.length()).map{rows.getString(it)}).validated()
        }
    }
}

/** Shared native boundary for UI and integration tests. Never returns credentials. */
internal class AlpacaAccess(private val keys:AlpacaCredentials,private val settings:AlpacaSettingsStore) {
    companion object {
        fun validKeys(id:String,secret:String)=id.length in 8..128 && secret.length in 8..256 &&
            id.all{it.code in 33..126} && secret.all{it.code in 33..126}
    }
    fun keyState():String = try {
        if(!keys.exists())"missing" else keys.read().let{if(validKeys(it.first,it.second))"readable" else "unreadable"}
    } catch(_:Exception){"unreadable"}
    fun save(id:String,secret:String) {
        if(!validKeys(id,secret))throw AlpacaAccessFailure("INVALID_KEYS")
        try {keys.save(id,secret);check(keys.read()==Pair(id,secret))}
        catch(_:Exception){throw AlpacaAccessFailure("KEY_SAVE_FAILED")}
    }
    fun readSettings():AlpacaSettings = try {settings.read().validated()}
        catch(_:Exception){throw AlpacaAccessFailure("SETTINGS_UNAVAILABLE")}
    fun saveSettings(value:AlpacaSettings) {
        value.validated()
        if(value.real)requireReadableKeys()
        try {settings.write(value);check(settings.read()==value)}
        catch(_:Exception){throw AlpacaAccessFailure("SETTINGS_SAVE_FAILED")}
    }
    private fun requireReadableKeys(){when(keyState()){
        "missing"->throw AlpacaAccessFailure("KEYS_MISSING")
        "unreadable"->throw AlpacaAccessFailure("KEYSTORE_UNAVAILABLE")
    }}
    fun start(confirmed:Boolean,startSession:(AlpacaSettings)->Unit) {
        if(!confirmed)throw AlpacaAccessFailure("CONSENT_REQUIRED")
        val config=readSettings()
        if(!config.real)throw AlpacaAccessFailure("REAL_DATA_OFF")
        requireReadableKeys()
        startSession(config)
    }
}
