package com.optionsaitrader.options_ai_trader

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URI
import java.util.concurrent.Executors

/** Opt-in session; keeps no token, account data, or startup setting on disk. */
class MarketMonitorService : Service() {
    data class Config(val endpoint: URI, val account: String, val token: String)
    companion object {
        private const val CHANNEL = "market_monitor_experiment"
        private const val NOTICE = 1901
        private const val STOP = "oat.monitor.STOP"
        @Volatile private var pending: Config? = null
        @Volatile private var instance: MarketMonitorService? = null
        @Volatile private var snapshot: Map<String, Any?> = mapOf("active" to false, "state" to "STOPPED")
        fun status(): Map<String, Any?> = snapshot
        fun start(context: Context, base: String, account: String, token: String): Map<String, Any?> {
            require(instance == null && pending == null) { "MONITOR_ALREADY_ACTIVE" }
            val config = Config(MonitorPolicy.endpoint(base, account, token), account, token)
            pending = config
            snapshot = mapOf("active" to false, "state" to "STARTING", "account" to account)
            try {
                val intent = Intent(context, MarketMonitorService::class.java)
                if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
            } catch (_: Exception) {
                pending = null
                snapshot = mapOf("active" to false, "state" to "START_FAILED")
            }
            return status()
        }
        fun stop(context: Context): Map<String, Any?> {
            pending = null
            instance?.finish("STOPPED")
            context.stopService(Intent(context, MarketMonitorService::class.java))
            snapshot = mapOf("active" to false, "state" to "STOPPED")
            return status()
        }
    }
    private val main = Handler(Looper.getMainLooper())
    private val executor = Executors.newSingleThreadExecutor()
    private var config: Config? = null
    private var started = 0L
    private var stopped = false
    @Volatile private var connection: HttpURLConnection? = null
    private val poll = Runnable { readStatus() }

    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) { finish("STOPPED"); return START_NOT_STICKY }
        val requested = pending
        pending = null
        if (intent == null || requested == null || stopped) { finish("STOPPED"); return START_NOT_STICKY }
        config = requested
        instance = this
        started = SystemClock.elapsedRealtime()
        try {
            val manager = getSystemService(NotificationManager::class.java)
            if (!manager.areNotificationsEnabled()) { finish("NOTIFICATIONS_REQUIRED"); return START_NOT_STICKY }
            if (Build.VERSION.SDK_INT >= 26) {
                manager.createNotificationChannel(NotificationChannel(CHANNEL, "مراقبة السوق التجريبية", NotificationManager.IMPORTANCE_LOW))
                if (manager.getNotificationChannel(CHANNEL).importance == NotificationManager.IMPORTANCE_NONE) {
                    finish("NOTIFICATIONS_REQUIRED"); return START_NOT_STICKY
                }
            }
            val notification = notice("بدء جلسة مراقبة محدودة — لا تداول")
            if (Build.VERSION.SDK_INT >= 29) startForeground(NOTICE, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            else startForeground(NOTICE, notification)
            publish("CONNECTING")
            main.postDelayed({ finish("SESSION_ENDED") }, MonitorPolicy.SESSION_MS)
            readStatus()
        } catch (_: Exception) { finish("START_FAILED") }
        return START_NOT_STICKY
    }
    private fun notice(message: String): Notification {
        val stop = PendingIntent.getService(this, 0, Intent(this, MarketMonitorService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val open = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL) else Notification.Builder(this)
        return builder.setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("مراقبة خادم السوق • تجريبية")
            .setContentText(message).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
            .setVisibility(Notification.VISIBILITY_PRIVATE)
            .addAction(Notification.Action.Builder(null, "إيقاف المراقبة", stop).build()).build()
    }
    private fun publish(state: String) {
        val selected = config ?: return
        snapshot = mapOf("active" to true, "state" to state, "account" to selected.account,
            "checkedAt" to System.currentTimeMillis(),
            "remainingSeconds" to ((MonitorPolicy.SESSION_MS - (SystemClock.elapsedRealtime() - started)).coerceAtLeast(0) / 1000))
    }
    private fun readStatus() {
        val selected = config ?: return
        if (stopped || MonitorPolicy.expired(started, SystemClock.elapsedRealtime())) { finish("SESSION_ENDED"); return }
        executor.execute {
            var result = "UNAVAILABLE"
            var terminal = false
            try {
                val conn = selected.endpoint.toURL().openConnection() as HttpURLConnection
                connection = conn
                conn.requestMethod = "GET"
                conn.instanceFollowRedirects = false
                conn.useCaches = false
                conn.connectTimeout = 8000
                conn.readTimeout = 8000
                conn.setRequestProperty("Authorization", "Bearer ${selected.token}")
                conn.setRequestProperty("Accept", "application/json")
                when (conn.responseCode) {
                    401, 403 -> { result = "AUTH_REQUIRED"; terminal = true }
                    200 -> {
                        val out = ByteArrayOutputStream()
                        val deadline = SystemClock.elapsedRealtime() + 12000
                        conn.inputStream.use { input ->
                            val buffer = ByteArray(4096)
                            while (true) {
                                check(SystemClock.elapsedRealtime() <= deadline && !Thread.currentThread().isInterrupted)
                                val count = input.read(buffer)
                                if (count < 0) break
                                check(out.size() + count <= MonitorPolicy.MAX_BODY_BYTES)
                                out.write(buffer, 0, count)
                            }
                        }
                        val json = JSONObject(out.toString("UTF-8"))
                        val fields = mutableMapOf<String, Any>()
                        json.keys().forEach { fields[it] = json.get(it) }
                        check(MonitorPolicy.validStatus(fields, selected.account))
                        result = if (json.getBoolean("heartbeat_fresh")) "API_REACHABLE" else "WORKER_UNAVAILABLE"
                    }
                }
            } catch (_: Exception) { result = "UNAVAILABLE" }
            finally { connection?.disconnect(); connection = null }
            main.post {
                if (!stopped && config === selected) {
                    if (terminal) finish(result)
                    else if (MonitorPolicy.expired(started, SystemClock.elapsedRealtime())) finish("SESSION_ENDED")
                    else {
                        publish(result)
                        val message = when (result) {
                            "API_REACHABLE" -> "API متاح؛ نبض العامل حديث وقت القراءة — لا تداول"
                            "WORKER_UNAVAILABLE" -> "API متاح؛ نبض العامل قديم أو مفقود"
                            else -> "تعذر التحقق من الخادم؛ لا أسعار معتمدة"
                        }
                        try { getSystemService(NotificationManager::class.java).notify(NOTICE, notice(message)) }
                        catch (_: Exception) { finish("NOTIFICATIONS_REQUIRED") }
                        if (!stopped) main.postDelayed(poll, MonitorPolicy.POLL_MS)
                    }
                }
            }
        }
    }
    private fun finish(reason: String) {
        if (stopped) return
        stopped = true
        pending = null
        config = null
        main.removeCallbacksAndMessages(null)
        connection?.disconnect()
        executor.shutdownNow()
        snapshot = mapOf("active" to false, "state" to reason)
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }
    override fun onTaskRemoved(rootIntent: Intent?) { finish("TASK_REMOVED") }
    override fun onTimeout(startId: Int, fgsType: Int) { finish("SYSTEM_TIMEOUT") }
    override fun onDestroy() {
        finish("STOPPED")
        if (instance === this) instance = null
        super.onDestroy()
    }
}
