import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'engine.dart';
import 'backup.dart';

abstract interface class DemoStore {
  Future<String?> load();
  Future<void> save(String value);
}

/// An immutable local copy, separate from the active ledger. Implementations
/// must refuse a different second value; recovery must never erase old evidence.
abstract interface class DemoRecoveryStore {
  Future<String?> loadRecoveryCopy();
  Future<void> preserveRecoveryCopy(String value);
}

class PreferencesDemoStore implements DemoStore, DemoRecoveryStore {
  static const key = 'options_ai_trader.local_demo.v1';
  static const recoveryKey = 'options_ai_trader.local_demo.recovery.v1';
  @override
  Future<String?> load() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.reload();
    return prefs.getString(key);
  }
  @override
  Future<void> save(String value) async {
    final ok = await (await SharedPreferences.getInstance()).setString(
      key,
      value,
    );
    if (!ok) throw const DemoRejected('تعذر حفظ المحاكاة على الجهاز');
  }

  @override
  Future<String?> loadRecoveryCopy() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.reload();
    return prefs.getString(recoveryKey);
  }

  @override
  Future<void> preserveRecoveryCopy(String value) async {
    final existing = await loadRecoveryCopy();
    if (existing == value) return;
    if (existing != null) {
      throw const DemoRejected('توجد نسخة استرداد سابقة مختلفة؛ لن تُمحى');
    }
    final prefs = await SharedPreferences.getInstance();
    if (!await prefs.setString(recoveryKey, value) ||
        await loadRecoveryCopy() != value) {
      throw const DemoRejected('تعذر حفظ نسخة البيانات الأصلية والتحقق منها');
    }
  }
}

class MemoryDemoStore implements DemoStore, DemoRecoveryStore {
  String? data;
  String? recoveryCopy;
  bool failWrites = false;
  MemoryDemoStore([this.data]);
  @override
  Future<String?> load() async => data;
  @override
  Future<void> save(String value) async {
    if (failWrites) throw const DemoRejected('فشل حفظ اصطناعي');
    data = value;
  }
  @override
  Future<String?> loadRecoveryCopy() async => recoveryCopy;
  @override
  Future<void> preserveRecoveryCopy(String value) async {
    if (failWrites || (recoveryCopy != null && recoveryCopy != value)) {
      throw const DemoRejected('تعذر حفظ نسخة الاسترداد دون محو نسخة سابقة');
    }
    recoveryCopy = value;
  }
}

class DemoController extends ChangeNotifier {
  final DemoStore store;
  DemoEngine engine = DemoEngine();
  bool ready = false, busy = false;
  bool storageUncertain = false;
  String? error;
  String? _unreadableSnapshot;
  String? get unreadableSnapshot => _unreadableSnapshot;
  bool get canRecover => !ready && !busy && !storageUncertain &&
      !_disposed && _unreadableSnapshot != null && store is DemoRecoveryStore;
  Timer? _timer;
  bool _disposed = false;
  bool get playing => _timer != null;
  DemoController(this.store);

  Future<void> load() async {
    if (busy || _disposed) return;
    final recovering = storageUncertain;
    final previousEngine = engine;
    final previouslyReady = ready;
    String? loaded;
    pause();
    busy = true;
    error = null;
    notifyListeners();
    try {
      final data = await store.load();
      loaded = data;
      if (data == null) {
        if (recovering || previouslyReady || _unreadableSnapshot != null) {
          throw const DemoRejected('الحفظ غير موجود؛ احتفظ بالأصل المتاح وصدّره');
        }
        engine = DemoEngine();
        for (final name in ['حساب تجريبي محلي', 'محفظة التوازن', 'مختبر Swing', 'مراقبة الفرص']) {
          final a = engine.createAccount(name, 1000000);
          if (name == 'مختبر Swing') engine.configure(a['id'], {'holding': 'swing'});
          if (name == 'مراقبة الفرص') engine.configure(a['id'], {'mode': 'observe'});
        }
        await store.save(engine.encode());
        if (await store.load() != engine.encode()) {
          throw const DemoRejected('تعذر التحقق من الحفظ الأول؛ لم يبدأ تشغيل المحاكاة');
        }
      } else {
        engine = DemoEngine.decode(data);
      }
      ready = true;
      storageUncertain = false;
      _unreadableSnapshot = null;
    } catch (e) {
      if (recovering || previouslyReady) {
        engine = previousEngine;
        ready = previouslyReady;
        storageUncertain = true;
        error = 'تعذرت إعادة قراءة الحفظ؛ بيانات الذاكرة محفوظة والتصدير متاح، والكتابة مقفلة. $e';
      } else {
        ready = false;
        _unreadableSnapshot = loaded ?? _unreadableSnapshot;
        error = '$e';
      }
    }
    busy = false;
    if (!_disposed) notifyListeners();
  }

  Future<void> change(void Function(DemoEngine) operation) async {
    if (!ready || busy || storageUncertain || _disposed) return;
    busy = true;
    error = null;
    final before = engine.encode();
    String? previous;
    var writeStarted = false;
    try {
      previous = await store.load() ?? before;
      try {
        operation(engine);
      } on DemoRejected catch (e) {
        error = e.message;
      }
      // A simulated lost response still persists the accepted order and unknown
      // state; all writes are serialized and the whole ledger is one snapshot.
      engine.validate();
      final replacement = engine.encode();
      writeStarted = true;
      await store.save(replacement);
      if (await store.load() != replacement) {
        throw const DemoRejected('تعذر التحقق من النسخة المحفوظة');
      }
    } catch (_) {
      final restored = !writeStarted ||
          (previous != null && await _restoreStored(previous));
      engine = DemoEngine.decode(before);
      _timer?.cancel();
      _timer = null;
      storageUncertain = !restored;
      error = restored
          ? 'تعذر التحقق أو الحفظ؛ أُلغيت الدورة وتوقف التشغيل. بقيت النسخة السابقة محفوظة.'
          : 'تعذر الحفظ واستعادة النسخة السابقة على القرص؛ بقيت بيانات الذاكرة متاحة للتصدير، والكتابة مقفلة حتى إعادة قراءة موثوقة.';
    }
    busy = false;
    if (!_disposed) notifyListeners();
  }

  Future<bool> _restoreStored(String previous) async {
    try {
      if (await store.load() != previous) {
        await store.save(previous);
      }
      return await store.load() == previous;
    } catch (_) {
      return false;
    }
  }

  String exportBackup() {
    if (!ready || busy || _disposed) {
      throw const DemoRejected('انتظر اكتمال حفظ المحاكاة أولًا');
    }
    pause();
    return DemoBackup.export(engine);
  }

  Future<String?> recoveryCopy() async {
    if (_disposed || busy) return null;
    final target = store;
    return target is DemoRecoveryStore
        ? (target as DemoRecoveryStore).loadRecoveryCopy() : null;
  }

  Future<bool> recoverBackup(DemoBackupPreview preview,
      {required String expectedDamaged}) async {
    if (!canRecover || _unreadableSnapshot != expectedDamaged) return false;
    final target = store as DemoRecoveryStore;
    pause();
    busy = true;
    error = null;
    notifyListeners();
    var writeStarted = false;
    var success = false;
    try {
      final candidate = DemoBackup.prepareImport(preview);
      if (await store.load() != expectedDamaged) {
        throw const DemoRejected('تغير الحفظ؛ أعد القراءة والمعاينة');
      }
      await target.preserveRecoveryCopy(expectedDamaged);
      if (await target.loadRecoveryCopy() != expectedDamaged) {
        throw const DemoRejected('لم تثبت مطابقة نسخة البيانات الأصلية');
      }
      // Recheck after the asynchronous archive operation, before replacing.
      if (await store.load() != expectedDamaged) {
        throw const DemoRejected('تغير الحفظ أثناء الاحتفاظ بالأصل؛ أعد القراءة');
      }
      final replacement = candidate.encode();
      writeStarted = true;
      await store.save(replacement);
      if (await store.load() != replacement) {
        throw const DemoRejected('تعذر التحقق من الحفظ المستعاد');
      }
      engine = candidate;
      ready = true;
      storageUncertain = false;
      _unreadableSnapshot = null;
      success = true;
    } catch (_) {
      final restored = !writeStarted || await _restoreStored(expectedDamaged);
      storageUncertain = !restored;
      error = restored
          ? 'تعذر الاسترداد. لم يُستبدل الحفظ أو أُعيد أصله؛ أعد القراءة. قد توجد نسخة استرداد سابقة مختلفة لا يمكن محوها.'
          : 'تعذر التحقق من الاسترداد والتراجع؛ الكتابة مقفلة. النص الأصلي محفوظ منفصلًا ومتاح للنسخ؛ أعد القراءة قبل أي إجراء.';
    }
    busy = false;
    if (!_disposed) notifyListeners();
    return success;
  }

  Future<bool> importBackup(DemoBackupPreview preview, {required String expectedCurrent}) async {
    if (!ready || busy || storageUncertain || _disposed) return false;
    if (engine.encode() != expectedCurrent) {
      error = 'تغيرت بيانات Demo منذ فتح الاستيراد؛ أعد المعاينة قبل الاستبدال.';
      notifyListeners();
      return false;
    }
    pause();
    busy = true;
    error = null;
    notifyListeners();
    String? previous;
    var writeStarted = false;
    var success = false;
    try {
      final candidate = DemoBackup.prepareImport(preview);
      previous = await store.load() ?? engine.encode();
      final replacement = candidate.encode();
      writeStarted = true;
      await store.save(replacement);
      if (await store.load() != replacement) {
        throw const DemoRejected('تعذر التحقق من النسخة المحفوظة');
      }
      engine = candidate;
      success = true;
    } catch (_) {
      final restored = !writeStarted ||
          (previous != null && await _restoreStored(previous));
      error = restored
        ? 'فشل الاستيراد؛ بقيت النسخة السابقة محفوظة ولم تتغير بيانات المحاكاة.'
        : 'فشل الاستيراد واستعادة الحفظ. بقيت النسخة السابقة في الذاكرة، لكن حالة التخزين غير مؤكدة؛ صدّرها قبل إغلاق التطبيق.';
      storageUncertain = !restored;
    }
    busy = false;
    if (!_disposed) notifyListeners();
    return success;
  }

  void play() {
    if (!ready || busy || storageUncertain || playing || _disposed) return;
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
