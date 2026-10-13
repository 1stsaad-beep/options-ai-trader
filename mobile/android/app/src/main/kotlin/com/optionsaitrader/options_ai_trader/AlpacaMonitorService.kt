package com.optionsaitrader.options_ai_trader

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.*

/** Optional 30-minute price/indicator session; no boot restart and no virtual/external execution. */
class AlpacaMonitorService:Service() {
    companion object {
        @Volatile var running=false;private set
        private const val ID=2020
        private const val CHANNEL="alpaca_price_monitor"
        fun stop(context:Context){context.stopService(Intent(context,AlpacaMonitorService::class.java));AlpacaRuntime.stop();running=false}
        fun start(context:Context) {
            check(AlpacaRuntime.get(context).enabled)
            val manager=context.getSystemService(NotificationManager::class.java)
            check(manager.areNotificationsEnabled())
            if(Build.VERSION.SDK_INT>=26)check(manager.getNotificationChannel(CHANNEL)?.importance!=NotificationManager.IMPORTANCE_NONE)
            val intent=Intent(context,AlpacaMonitorService::class.java)
            if(Build.VERSION.SDK_INT>=26)context.startForegroundService(intent) else context.startService(intent)
        }
    }
    private val handler=Handler(Looper.getMainLooper())
    private var deadline=0L
    private val tick=object:Runnable {override fun run(){
        if(SystemClock.elapsedRealtime()>=deadline || !AlpacaRuntime.get(this@AlpacaMonitorService).enabled ||
            !getSystemService(NotificationManager::class.java).areNotificationsEnabled()){stopSelf();return}
        handler.postDelayed(this,5000)
    }}
    override fun onBind(intent:Intent?)=null
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        if(intent?.action=="STOP"){stopSelf();return START_NOT_STICKY}
        if(!AlpacaRuntime.get(this).enabled){stopSelf();return START_NOT_STICKY}
        val manager=getSystemService(NotificationManager::class.java)
        if(Build.VERSION.SDK_INT>=26)manager.createNotificationChannel(NotificationChannel(CHANNEL,"Alpaca: مراقبة تجريبية",NotificationManager.IMPORTANCE_LOW))
        val stop=PendingIntent.getService(this,ID,Intent(this,AlpacaMonitorService::class.java).setAction("STOP"),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val open=PendingIntent.getActivity(this,ID,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val builder=if(Build.VERSION.SDK_INT>=26)Notification.Builder(this,CHANNEL) else Notification.Builder(this)
        val notification=builder.setSmallIcon(android.R.drawable.ic_menu_view).setContentTitle("Alpaca • أسعار وتحليل محلي")
            .setContentText("جلسة ≤30 دقيقة؛ لا أوامر تداول. قد تتوقف بسبب الشبكة أو Android.")
            .setOngoing(true).setContentIntent(open).addAction(Notification.Action.Builder(null,"إيقاف",stop).build()).build()
        if(Build.VERSION.SDK_INT>=29)startForeground(ID,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC) else startForeground(ID,notification)
        running=true
        if(deadline==0L)deadline=SystemClock.elapsedRealtime()+30*60*1000L
        handler.removeCallbacks(tick);handler.post(tick)
        return START_NOT_STICKY
    }
    override fun onTimeout(startId:Int,fgsType:Int){stopSelf()}
    override fun onTaskRemoved(rootIntent:Intent?){stopSelf()}
    override fun onDestroy(){handler.removeCallbacks(tick);running=false;AlpacaRuntime.stop();stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy()}
}
