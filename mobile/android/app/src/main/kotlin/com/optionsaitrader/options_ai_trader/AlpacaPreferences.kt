package com.optionsaitrader.options_ai_trader

import android.content.Context

/** Nonsecret preferences only; separate from Demo and server settings. Never starts a session. */
internal class AlpacaPreferences(context:Context):AlpacaSettingsStore {
    private val prefs=context.applicationContext.getSharedPreferences("oat.alpaca.settings.v1",Context.MODE_PRIVATE)
    override fun read()=prefs.getString("config",null)?.let{AlpacaSettings.parse(it)}?:AlpacaSettings()
    override fun write(settings:AlpacaSettings){check(prefs.edit().putString("config",settings.validated().json().toString()).commit())}
}
