package com.optionsaitrader.options_ai_trader

import android.Manifest
import android.app.NotificationManager
import android.content.pm.PackageManager
import android.os.Build
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var permissionResult: MethodChannel.Result? = null
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val paperDisk=PaperDiskStore(java.io.File(noBackupFilesDir,"market-paper-v1.json"))
        val paperChannel=MethodChannel(flutterEngine.dartExecutor.binaryMessenger,"oat/market_paper_disk",
            io.flutter.plugin.common.StandardMethodCodec.INSTANCE,flutterEngine.dartExecutor.binaryMessenger.makeBackgroundTaskQueue())
        paperChannel.setMethodCallHandler { call,result ->
            try {
                when(call.method) {
                    "read" -> result.success(paperDisk.read())
                    "write" -> result.success(paperDisk.write(call.argument<String>("expected"),call.argument<String>("next")?:""))
                    else -> result.notImplemented()
                }
            }catch(_:Exception){result.error("PAPER_STORAGE_UNCERTAIN","Ledger storage could not be confirmed",null)}
        }
        val access=AlpacaAccess(AlpacaVault(this),AlpacaPreferences(this))
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger,"oat/alpaca_data").setMethodCallHandler { call,result ->
            try {
                when(call.method) {
                    "keyStatus" -> result.success(access.keyState()=="readable")
                    "keyState" -> result.success(access.keyState())
                    "getSettings" -> result.success(access.readSettings().json().toString())
                    "saveSettings" -> {
                        val config=try{AlpacaSettings.parse(call.argument<String>("settings")?:"")}
                            catch(_:Exception){throw AlpacaAccessFailure("INVALID_SETTINGS")}
                        access.saveSettings(config)
                        result.success(true)
                    }
                    "saveKeys" -> {
                        AlpacaMonitorService.stop(this)
                        access.save(call.argument<String>("key")?:"",call.argument<String>("secret")?:"")
                        result.success(true)
                    }
                    "secureScreen" -> {
                        if(call.argument<Boolean>("enabled")==true)window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                        else window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
                        result.success(true)
                    }
                    "start" -> {
                        if(!hasWindowFocus())throw AlpacaAccessFailure("FOREGROUND_REQUIRED")
                        access.start(call.argument<Boolean>("confirmed")==true){config->
                            AlpacaRuntime.get(this).start(config.feed,config.session,config.symbols)
                        }
                        result.success(true)
                    }
                    "stop" -> {AlpacaMonitorService.stop(this);result.success(true)}
                    "snapshot" -> result.success(AlpacaRuntime.get(this).snapshot())
                    "stockQuote" -> AlpacaRuntime.get(this).stockQuote(call.argument<String>("symbol")?:"") { quote -> runOnUiThread {result.success(quote)} }
                    "quote" -> AlpacaRuntime.get(this).quote(call.argument<String>("contract")?:"") { quote -> runOnUiThread {result.success(quote)} }
                    "backgroundStatus" -> result.success(AlpacaMonitorService.running)
                    "backgroundStart" -> {
                        check(hasWindowFocus() && getSystemService(NotificationManager::class.java).areNotificationsEnabled())
                        AlpacaMonitorService.start(this);result.success(true)
                    }
                    else -> result.notImplemented()
                }
            }catch(e:AlpacaAccessFailure){result.error(e.code,e.code,null)}
            catch(_:Exception){result.error("DATA_UNAVAILABLE","DATA_UNAVAILABLE",null)}
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "oat/market_monitor").setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "status" -> result.success(MarketMonitorService.status())
                    "stop" -> result.success(MarketMonitorService.stop(this))
                    "permission" -> {
                        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                            if (permissionResult != null) result.error("BUSY", "Permission request pending", null)
                            else { permissionResult = result; requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1901) }
                        } else result.success(getSystemService(NotificationManager::class.java).areNotificationsEnabled())
                    }
                    "start" -> {
                        if (!hasWindowFocus() || !getSystemService(NotificationManager::class.java).areNotificationsEnabled()) {
                            result.error("FOREGROUND_REQUIRED", "Open the app and allow notifications", null)
                        } else result.success(MarketMonitorService.start(this,
                            call.argument<String>("baseUrl") ?: "",
                            call.argument<String>("account") ?: "",
                            call.argument<String>("token") ?: ""))
                    }
                    else -> result.notImplemented()
                }
            } catch (_: Exception) { result.error("MONITOR_REFUSED", "Monitoring could not be started", null) }
        }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1901) {
            permissionResult?.success(grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED)
            permissionResult = null
        }
    }
    override fun onDestroy() {
        permissionResult?.success(false)
        permissionResult = null
        super.onDestroy()
    }
    override fun onStop() {
        AlpacaRuntime.background(AlpacaMonitorService.running)
        super.onStop()
    }
    override fun onResume(){super.onResume();AlpacaRuntime.foreground()}
}
