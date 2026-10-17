import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

// B14 scope guard: the Android-phase core must not depend on the (out-of-scope) server client.
// Server/iOS sources are kept, not deleted; this only prevents new core coupling.
void main() {
  test('Android-phase core modules do not import the server client', () {
    final core = <File>[
      ...Directory('lib/brokers').listSync().whereType<File>(),
      ...Directory('lib/demo').listSync().whereType<File>(),
      for (final f in Directory('lib').listSync().whereType<File>())
        if (RegExp(r'/(market_paper[^/]*|direct[^/]*|daily_nav|protective_exit|option_pricing|extended_patterns)\.dart$')
            .hasMatch(f.path)) f,
    ].where((f) => f.path.endsWith('.dart')).toList();
    expect(core.length, greaterThan(20));
    final offenders = [
      for (final f in core)
        if (RegExp(r'''import\s+'(\.\./)?(api|observed_server[a-z_]*)\.dart'|package:options_ai_trader/(api|observed_server)''')
            .hasMatch(f.readAsStringSync())) f.path,
    ];
    expect(offenders, isEmpty);
  });

  test('iOS and server sources are retained, not deleted', () {
    for (final p in ['ios/Runner.xcodeproj', '../backend/app', '../infra', '../.github/workflows/ios.yaml',
      '../.github/workflows/checks.yaml']) {
      expect(FileSystemEntity.typeSync(p), isNot(FileSystemEntityType.notFound), reason: p);
    }
  });
}
