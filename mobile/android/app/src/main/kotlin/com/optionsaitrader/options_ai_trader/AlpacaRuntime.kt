package com.optionsaitrader.options_ai_trader

import android.content.Context

internal object AlpacaRuntime {
    @Volatile private var instance:AlpacaSession?=null
    @Synchronized fun get(context:Context):AlpacaSession {
        val app=context.applicationContext
        return instance ?: AlpacaSession({AlpacaVault(app).read()}).also {instance=it}
    }
    fun stop(){instance?.stop()}
    fun background(monitoring:Boolean){instance?.background(monitoring)}
    fun foreground(){instance?.foreground()}
}
