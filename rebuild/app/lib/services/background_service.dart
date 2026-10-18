import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';

/// Commands the persistent notification / service send to the app.
abstract final class BackgroundCommand {
  /// Periodic nudge (every 60 s) — the app runs due cycles.
  static const tick = 'tick';

  /// Notification button: emergency pause of all auto-trading (kill switch).
  static const pauseAll = 'pause_all';

  /// Notification button: stop the background service.
  static const stopService = 'stop_service';
}

/// Keeps the app process alive while auto-trading runs in the background.
///
/// Design: cycles always run in the app's main isolate (where accounts,
/// secrets and locks live). The Android foreground service only keeps the
/// process and CPU awake (wake + Wi-Fi lock), shows the persistent
/// notification and sends a [BackgroundCommand.tick] every minute. No server.
abstract class BackgroundRunner {
  /// Whether this platform supports the background service (Android only).
  bool get supported;

  void init(void Function(String command) onCommand);
  Future<bool> isRunning();

  /// Starts the service. Returns null on success or an Arabic error.
  Future<String?> start({required String title, required String text});
  Future<void> stop();
  Future<void> update({required String title, required String text});

  Future<bool> notificationsAllowed();
  Future<bool> requestNotifications();
  Future<bool> isIgnoringBatteryOptimizations();

  /// Opens the system battery-optimization list (no special permission; the
  /// user decides — follows Android's guidance).
  Future<void> openBatterySettings();
}

/// No-op runner for tests and non-Android platforms.
class NoBackgroundRunner implements BackgroundRunner {
  bool running = false;
  final List<String> updates = [];
  void Function(String)? onCommand;

  @override
  bool get supported => false;
  @override
  void init(void Function(String command) onCommand) => this.onCommand = onCommand;
  @override
  Future<bool> isRunning() async => running;
  @override
  Future<String?> start({required String title, required String text}) async {
    running = true;
    updates.add(text);
    return null;
  }

  @override
  Future<void> stop() async => running = false;
  @override
  Future<void> update({required String title, required String text}) async => updates.add(text);
  @override
  Future<bool> notificationsAllowed() async => true;
  @override
  Future<bool> requestNotifications() async => true;
  @override
  Future<bool> isIgnoringBatteryOptimizations() async => true;
  @override
  Future<void> openBatterySettings() async {}

  /// Simulates a command from the notification / service.
  void send(String command) => onCommand?.call(command);
}

/// Background-isolate entry point of the foreground service.
@pragma('vm:entry-point')
void backgroundTaskEntryPoint() {
  FlutterForegroundTask.setTaskHandler(_TickHandler());
}

class _TickHandler extends TaskHandler {
  @override
  Future<void> onStart(DateTime timestamp, TaskStarter starter) async {}

  @override
  void onRepeatEvent(DateTime timestamp) => FlutterForegroundTask.sendDataToMain(BackgroundCommand.tick);

  @override
  Future<void> onDestroy(DateTime timestamp, bool isTimeout) async {}

  @override
  void onNotificationButtonPressed(String id) => FlutterForegroundTask.sendDataToMain(id);

  @override
  void onNotificationPressed() => FlutterForegroundTask.launchApp();
}

/// Android implementation on flutter_foreground_task (specialUse service).
class ForegroundTaskRunner implements BackgroundRunner {
  static const _buttons = [
    NotificationButton(id: BackgroundCommand.pauseAll, text: 'إيقاف طارئ'),
    NotificationButton(id: BackgroundCommand.stopService, text: 'إيقاف الخدمة'),
  ];

  @override
  bool get supported => !kIsWeb && Platform.isAndroid;

  @override
  void init(void Function(String command) onCommand) {
    if (!supported) return;
    FlutterForegroundTask.initCommunicationPort();
    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        channelId: 'oat_auto_trading',
        channelName: 'التداول الآلي',
        channelDescription: 'إشعار دائم أثناء عمل التداول الآلي في الخلفية',
        onlyAlertOnce: true,
      ),
      iosNotificationOptions: const IOSNotificationOptions(showNotification: false),
      foregroundTaskOptions: ForegroundTaskOptions(
        eventAction: ForegroundTaskEventAction.repeat(60000),
        autoRunOnBoot: false,
        autoRunOnMyPackageReplaced: false,
        allowWakeLock: true,
        allowWifiLock: true,
        allowAutoRestart: false,
        stopWithTask: true,
      ),
    );
    FlutterForegroundTask.addTaskDataCallback((data) {
      if (data is String) onCommand(data);
    });
  }

  @override
  Future<bool> isRunning() async => supported && await FlutterForegroundTask.isRunningService;

  @override
  Future<String?> start({required String title, required String text}) async {
    if (!supported) return 'التشغيل في الخلفية متاح على أندرويد فقط';
    if (await FlutterForegroundTask.isRunningService) {
      await update(title: title, text: text);
      return null;
    }
    final r = await FlutterForegroundTask.startService(
      serviceId: 4101,
      serviceTypes: const [ForegroundServiceTypes.specialUse],
      notificationTitle: title,
      notificationText: text,
      notificationButtons: _buttons,
      callback: backgroundTaskEntryPoint,
    );
    return switch (r) {
      ServiceRequestSuccess() => null,
      ServiceRequestFailure(:final error) => 'تعذر تشغيل الخدمة: $error',
    };
  }

  @override
  Future<void> stop() async {
    if (supported) await FlutterForegroundTask.stopService();
  }

  @override
  Future<void> update({required String title, required String text}) async {
    if (!supported || !await FlutterForegroundTask.isRunningService) return;
    await FlutterForegroundTask.updateService(notificationTitle: title, notificationText: text, notificationButtons: _buttons);
  }

  @override
  Future<bool> notificationsAllowed() async =>
      !supported || await FlutterForegroundTask.checkNotificationPermission() == NotificationPermission.granted;

  @override
  Future<bool> requestNotifications() async =>
      !supported || await FlutterForegroundTask.requestNotificationPermission() == NotificationPermission.granted;

  @override
  Future<bool> isIgnoringBatteryOptimizations() async =>
      !supported || await FlutterForegroundTask.isIgnoringBatteryOptimizations;

  @override
  Future<void> openBatterySettings() async {
    if (supported) await FlutterForegroundTask.openIgnoreBatteryOptimizationSettings();
  }
}
