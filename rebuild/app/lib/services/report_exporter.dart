import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:trader_core/trader_core.dart';

/// Shares files through the Android share sheet (injectable for tests).
typedef ShareFiles = Future<void> Function(List<File> files, String subject);

Future<void> shareWithSheet(List<File> files, String subject) async {
  await SharePlus.instance.share(ShareParams(files: [for (final f in files) XFile(f.path)], subject: subject));
}

/// Writes CSV / JSON exports into the app's temporary directory and opens the
/// share sheet. CSV files start with a UTF-8 BOM so spreadsheet apps show
/// Arabic text correctly.
class ReportExporter {
  final Future<Directory> Function() dir;
  final ShareFiles share;
  ReportExporter({Future<Directory> Function()? dir, ShareFiles? share})
      : dir = dir ?? getTemporaryDirectory,
        share = share ?? shareWithSheet;

  static String _safe(String name) {
    final s = name.replaceAll(RegExp(r'[^A-Za-z0-9_-]+'), '_').replaceAll(RegExp(r'^_+|_+$'), '');
    return s.replaceAll('_', '').isEmpty ? 'account' : s;
  }

  Future<File> _write(String name, String content, {bool bom = false}) async {
    final d = Directory('${(await dir()).path}/exports');
    await d.create(recursive: true);
    final f = File('${d.path}/$name');
    await f.writeAsString(bom ? '\uFEFF$content' : content, flush: true);
    return f;
  }

  String _stamp(DateTime now) => NewYorkTime.dateKey(now);

  /// Performance report: trades CSV + daily/weekly CSV, or one JSON file.
  Future<List<File>> exportReport(AccountProfile p, AccountReport r, {required bool json, DateTime? now}) async {
    final base = '${_safe(p.name)}_${_stamp(now ?? DateTime.now().toUtc())}';
    final files = json
        ? [
            await _write('${base}_report.json',
                const JsonEncoder.withIndent('  ').convert({'account': p.name, 'broker': p.broker.name, 'mode': p.mode.name, ...r.toJson()}))
          ]
        : [
            await _write('${base}_trades.csv', r.tradesCsv(), bom: true),
            await _write('${base}_daily_weekly.csv', r.periodsCsv(), bom: true),
          ];
    await share(files, 'تقرير أداء ${p.name}');
    return files;
  }

  /// Activity log (cycle records) as CSV or JSON.
  Future<List<File>> exportActivity(AccountProfile p, List<CycleRecord> cycles, {required bool json, DateTime? now}) async {
    final base = '${_safe(p.name)}_${_stamp(now ?? DateTime.now().toUtc())}';
    final f = json
        ? await _write('${base}_activity.json',
            const JsonEncoder.withIndent('  ').convert({'account': p.name, 'cycles': [for (final c in cycles) c.toJson()]}))
        : await _write('${base}_activity.csv', cyclesCsv(cycles), bom: true);
    await share([f], 'سجل دورات ${p.name}');
    return [f];
  }
}
