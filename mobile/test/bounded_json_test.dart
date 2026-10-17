import 'dart:convert';
import 'dart:math';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/bounded_json.dart';

void main() {
  Object? read(String text, {int bytes = 100000, int nodes = 1000, int depth = 40}) =>
      decodeBoundedJson(text, maxBytes: bytes, maxNodes: nodes, maxDepth: depth);
  test('semantic values match Dart JSON across escapes numbers and Unicode', () {
    final values = [null, true, false, 0, -1, 1.5e-20, 1e25, 'العربية 😀 \\ \n "',
      <String, dynamic>{'a': [1, 2, {'escaped\\"key': false}], 'empty': <String, dynamic>{}}];
    for (final value in values) {
      final text = jsonEncode(value);
      expect(read(text), jsonDecode(text));
    }
    expect(read(r'{"a\u0062":"\uD83D\uDE00"}'), {'ab': '😀'});
  });
  test('UTF8 bound checked without allocating an encoded byte buffer', () {
    final text = jsonEncode('العربية 😀');
    final length = utf8.encode(text).length;
    expect(read(text, bytes: length), 'العربية 😀');
    expect(() => read(text, bytes: length - 1), throwsA(isA<JsonBoundsException>()));
  });
  test('value count and depth boundaries include containers but not map keys', () {
    expect(read('{"a":[0,1]}', nodes: 4, depth: 2), {'a': [0, 1]});
    expect(() => read('{"a":[0,1]}', nodes: 3), throwsA(isA<JsonBoundsException>()));
    expect(() => read('{"a":[0,1]}', depth: 1), throwsA(isA<JsonBoundsException>()));
    expect(read('[]', nodes: 1, depth: 0), isEmpty);
  });
  test('extreme depth refused before full object decode or stack exhaustion', () {
    expect(() => read('${'[' * 20000}0${']' * 20000}'), throwsA(isA<JsonBoundsException>()));
  });
  test('large flat collection is rejected at node budget', () {
    expect(() => read('[${List.filled(20000, '0').join(',')}]', nodes: 100),
      throwsA(isA<JsonBoundsException>()));
  });
  test('duplicate and escaped duplicate keys cannot silently overwrite originals', () {
    for (final text in ['{"cash":1,"cash":2}', r'{"cash":1,"\u0063ash":2}']) {
      expect(() => read(text), throwsFormatException);
    }
    expect(read('{"a":{"cash":1},"b":{"cash":2}}'), {'a': {'cash': 1}, 'b': {'cash': 2}});
  });
  test('braces and escaped quotes inside strings do not count as nesting', () {
    final text = jsonEncode('${'[' * 100}"\\${']' * 100}');
    expect(read(text, depth: 0, nodes: 1), jsonDecode(text));
  });
  test('1000 deterministic nested JSON values retain exact decoder semantics', () {
    final random = Random(51);
    Object? generate(int depth) {
      if (depth > 5) return random.nextInt(100000);
      switch (random.nextInt(7)) {
        case 0: return null;
        case 1: return random.nextBool();
        case 2: return random.nextDouble() * 1e20 - 1e10;
        case 3: return 'العربية 😀 ${random.nextInt(100)} [] {}';
        case 4: return List.generate(random.nextInt(8), (_) => generate(depth + 1));
        default: return {for (var i = 0; i < random.nextInt(8); i++) 'key$i': generate(depth + 1)};
      }
    }
    for (var i = 0; i < 1000; i++) {
      final text = jsonEncode(generate(0));
      expect(read(text, nodes: 100000), jsonDecode(text));
    }
  });
  test('malformed input is not accepted by preflight or decoder', () {
    for (final text in ['', ' ', '[1,]', '{"a":}', '{"a" 1}', '{}[]', '01', '-',
      '1.', '1e', '+1', 'NaN', 'truex', '"unterminated', r'"\u00xz"', r'"\q"']) {
      expect(() => read(text), throwsFormatException, reason: text);
    }
  });
}
