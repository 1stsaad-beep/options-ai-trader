package com.optionsaitrader.options_ai_trader

import org.junit.Assert.*
import org.junit.Test

class AlpacaAccessTest {
    private class MemoryKeys:AlpacaCredentials {
        var value:Pair<String,String>?=null
        var corrupt=false
        var failSave=false
        var mismatch=false
        override fun exists()=value!=null
        override fun read():Pair<String,String>{check(!corrupt);return value?:error("missing")}
        override fun save(id:String,secret:String){check(!failSave);value=if(mismatch)Pair("mock-wrong","mock-wrong") else Pair(id,secret)}
    }
    private class MemorySettings:AlpacaSettingsStore {
        var value=AlpacaSettings();var fail=false
        override fun read()=value
        override fun write(settings:AlpacaSettings){check(!fail);value=settings}
    }
    private val keys=MemoryKeys();private val prefs=MemorySettings();private val access=AlpacaAccess(keys,prefs)
    private fun saved(){access.save("mock-public-id","mock-private-value")}
    private fun failure(code:String,block:()->Unit){try{block();fail("expected $code")}catch(e:AlpacaAccessFailure){assertEquals(code,e.code)}}
    @Test fun fileExistenceDoesNotClaimReadableKeys(){assertEquals("missing",access.keyState());saved();keys.corrupt=true;assertEquals("unreadable",access.keyState())}
    @Test fun saveRequiresSuccessfulEncryptedReadBack(){keys.mismatch=true;failure("KEY_SAVE_FAILED"){saved()}}
    @Test fun secureStorageWriteFailureDoesNotReportSuccess(){keys.failSave=true;failure("KEY_SAVE_FAILED"){saved()};assertEquals("missing",access.keyState())}
    @Test fun validSavedKeysAreReportedWithoutPlaintext(){saved();assertEquals("readable",access.keyState());assertFalse(access.keyState().contains("mock"))}
    @Test fun invalidReplacementPreservesPreviousKeys(){saved();val old=keys.value;failure("INVALID_KEYS"){access.save("","secret with spaces")};assertEquals(old,keys.value)}
    @Test fun missingKeysCannotEnableOrConnect(){failure("KEYS_MISSING"){access.saveSettings(AlpacaSettings(real=true))};assertFalse(prefs.value.real);failure("REAL_DATA_OFF"){access.start(true){fail("network")}}}
    @Test fun corruptKeysBlockPreviouslyEnabledSetting(){saved();access.saveSettings(AlpacaSettings(real=true));keys.corrupt=true;failure("KEYSTORE_UNAVAILABLE"){access.start(true){fail("network")}}}
    @Test fun settingsSurviveNewControllerWithoutStartingNetwork(){saved();val value=AlpacaSettings(true,"sip","extended",listOf("AAPL"));access.saveSettings(value);val restored=AlpacaAccess(keys,prefs);assertEquals(value,restored.readSettings());assertFalse(restored.readSettings().json().toString().contains("mock-private"))}
    @Test fun explicitConsentAndSavedPreferenceAreBothRequired(){saved();access.saveSettings(AlpacaSettings(real=true));failure("CONSENT_REQUIRED"){access.start(false){fail("network")}}}
    @Test fun explicitStartUsesSavedConfigurationOnce(){saved();val value=AlpacaSettings(true,"iex","regular",listOf("TSLA"));access.saveSettings(value);var starts=0;access.start(true){assertEquals(value,it);starts++};assertEquals(1,starts)}
    @Test fun failedSettingsWritePreservesOldPreference(){saved();prefs.fail=true;failure("SETTINGS_SAVE_FAILED"){access.saveSettings(AlpacaSettings(real=true))};assertFalse(access.readSettings().real)}
    @Test fun turningOffNeverRequiresDecryptableKeys(){saved();access.saveSettings(AlpacaSettings(real=true));keys.corrupt=true;access.saveSettings(AlpacaSettings(real=false));assertFalse(access.readSettings().real)}
}
