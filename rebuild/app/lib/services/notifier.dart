import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// Kinds of local notifications the user can switch on/off.
enum NotifyKind {
  fills('تنفيذ الأوامر', true),
  errors('الأخطاء', true),
  killSwitch('الإيقاف الطارئ', true),
  market('افتتاح وإغلاق السوق', false);

  final String arabic;
  final bool defaultOn;
  const NotifyKind(this.arabic, this.defaultOn);
}

/// Local (on-device) notifications. No push server.
abstract class Notifier {
  Future<void> init();
  Future<bool> requestPermission();
  Future<void> show(NotifyKind kind, String title, String body);
}

/// Records notifications (tests / non-Android).
class RecordingNotifier implements Notifier {
  final List<(NotifyKind, String, String)> shown = [];
  @override
  Future<void> init() async {}
  @override
  Future<bool> requestPermission() async => true;
  @override
  Future<void> show(NotifyKind kind, String title, String body) async => shown.add((kind, title, body));
}

class LocalNotifier implements Notifier {
  final _plugin = FlutterLocalNotificationsPlugin();
  bool _ready = false;
  int _id = 5000;

  bool get _supported => !kIsWeb && Platform.isAndroid;

  @override
  Future<void> init() async {
    if (!_supported || _ready) return;
    await _plugin.initialize(
      settings: const InitializationSettings(android: AndroidInitializationSettings('@mipmap/ic_launcher')),
    );
    _ready = true;
  }

  @override
  Future<bool> requestPermission() async {
    if (!_supported) return false;
    await init();
    final android = _plugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
    return await android?.requestNotificationsPermission() ?? false;
  }

  @override
  Future<void> show(NotifyKind kind, String title, String body) async {
    if (!_supported) return;
    await init();
    final important = kind == NotifyKind.errors || kind == NotifyKind.killSwitch;
    await _plugin.show(
      id: _id++ % 100000,
      title: title,
      body: body,
      notificationDetails: NotificationDetails(
        android: AndroidNotificationDetails(
          'oat_${kind.name}',
          kind.arabic,
          channelDescription: 'إشعارات ${kind.arabic} من Options AI v2',
          importance: important ? Importance.high : Importance.defaultImportance,
          priority: important ? Priority.high : Priority.defaultPriority,
          styleInformation: BigTextStyleInformation(body),
        ),
      ),
    );
  }
}
