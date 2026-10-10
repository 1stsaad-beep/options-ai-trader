import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'engine.dart';

abstract interface class DemoStore {
  Future<String?> load();
  Future<void> save(String value);
}

class PreferencesDemoStore implements DemoStore {
  static const key = 'options_ai_trader.local_demo.v1';
  @override
  Future<String?> load() async =>
      (await SharedPreferences.getInstance()).getString(key);
  @override
  Future<void> save(String value) async {
    final ok = await (await SharedPreferences.getInstance()).setString(
      key,
      value,
    );
    if (!ok) throw const DemoRejected('تعذر حفظ المحاكاة على الجهاز');
  }
}

class MemoryDemoStore implements DemoStore {
  String? data;
  bool failWrites = false;
  MemoryDemoStore([this.data]);
  @override
  Future<String?> load() async => data;
  @override
  Future<void> save(String value) async {
    if (failWrites) throw const DemoRejected('فشل حفظ اصطناعي');
    data = value;
  }
}

class DemoController extends ChangeNotifier {
  final DemoStore store;
  DemoEngine engine = DemoEngine();
  bool ready = false, busy = false;
  String? error;
  Timer? _timer;
  bool _disposed = false;
  bool get playing => _timer != null;
  DemoController(this.store);

  Future<void> load() async {
    pause();
    busy = true;
    error = null;
    notifyListeners();
    try {
      final data = await store.load();
      if (data == null) {
        engine = DemoEngine();
        for (final name in ['حساب تجريبي محلي', 'محفظة التوازن', 'مختبر Swing', 'مراقبة الفرص']) {
          final a = engine.createAccount(name, 1000000);
          if (name == 'مختبر Swing') engine.configure(a['id'], {'holding': 'swing'});
          if (name == 'مراقبة الفرص') engine.configure(a['id'], {'mode': 'observe'});
        }
        await store.save(engine.encode());
      } else {
        engine = DemoEngine.decode(data);
      }
      ready = true;
    } catch (e) {
      ready = false;
      error = '$e';
    }
    busy = false;
    if (!_disposed) notifyListeners();
  }

  Future<void> change(void Function(DemoEngine) operation) async {
    if (!ready || busy || _disposed) return;
    busy = true;
    error = null;
    final before = engine.encode();
    try {
      try {
        operation(engine);
      } on DemoRejected catch (e) {
        error = e.message;
      }
      // A simulated lost response still persists the accepted order and unknown
      // state; all writes are serialized and the whole ledger is one snapshot.
      engine.validate();
      await store.save(engine.encode());
    } catch (_) {
      engine = DemoEngine.decode(before);
      _timer?.cancel();
      _timer = null;
      error =
          'تعذر التحقق أو الحفظ؛ أُلغيت الدورة وتوقف التشغيل. لم تُستبدل النسخة السابقة.';
    }
    busy = false;
    if (!_disposed) notifyListeners();
  }

  void play() {
    if (!ready || playing || _disposed) return;
    _timer = Timer.periodic(const Duration(milliseconds: 1500), (_) {
      if (!busy) change((e) => e.step());
    });
    notifyListeners();
  }

  void pause() {
    _timer?.cancel();
    _timer = null;
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }
}
