package com.optionsaitrader.options_ai_trader

import android.content.Context

internal object AlpacaRuntime {
    @Volatile private var instance:AlpacaSession?=null
    @Synchronized fun get(context:Context):AlpacaSession {
        return instance ?: AlpacaSession({AlpacaVault(context.applicationContext).read()}).also {instance=it}
    }
    fun stop(){instance?.stop()}
}
