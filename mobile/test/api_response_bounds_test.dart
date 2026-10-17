import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';

void main() {
  test('exact byte limit and split UTF8 are accepted', () async {
    final body = utf8.encode('"مرحبا"');
    final padded = [...body, ...List<int>.filled(TraderApi.maxResponseBytes - body.length, 32)];
    final api = TraderApi(client: MockClient.streaming((_, __) async => http.StreamedResponse(
      Stream.fromIterable([padded.sublist(0, 3), padded.sublist(3)]), 200, headers: {'content-type': 'application/json; charset=utf-8'})));
    addTearDown(api.close);
    expect(await api.request('GET', '/api/check'), 'مرحبا');
  });
  for (final declared in [false, true]) {
    test('oversized ${declared ? 'declared' : 'chunked'} reply cancels without mutation retry', () async {
      var cancelled = false, attempts = 0;
      late StreamController<List<int>> stream;
      stream = StreamController<List<int>>(onListen: () {
        stream.add(List<int>.filled(TraderApi.maxResponseBytes, 32));
        stream.add([32]);
      }, onCancel: () { cancelled = true; });
      final api = TraderApi(client: MockClient.streaming((_, __) async {
        attempts++;
        return http.StreamedResponse(stream.stream, 200, contentLength: declared ? TraderApi.maxResponseBytes + 1 : null);
      }));
      addTearDown(api.close);
      await expectLater(api.request('POST', '/api/check', {}), throwsA(isA<ApiException>()));
      expect(cancelled, true); expect(attempts, 1);
      await stream.close();
    });
  }
  for (final body in ['{"a":1,"a":2}', r'{"a":1,"\u0061":2}', '${'[' * 65}0${']' * 65}']) {
    test('ambiguous or deeply nested server JSON of ${body.length} characters is rejected before decode', () async {
      final api = TraderApi(client: MockClient((_) async => http.Response(body, 200)));
      addTearDown(api.close);
      await expectLater(api.request('GET', '/api/check'), throwsA(isA<ApiException>()));
    });
  }
  testWidgets('absolute deadline cancels even a slowly arriving body', (tester) async {
    var cancelled = false;
    final stream = StreamController<List<int>>(onCancel: () { cancelled = true; });
    final api = TraderApi(client: MockClient.streaming((_, __) async => http.StreamedResponse(stream.stream, 200)));
    addTearDown(api.close);
    final completed = expectLater(api.request('GET', '/api/check'), throwsA(isA<ApiException>()));
    await tester.pump();
    for (var i = 0; i < 3; i++) {
      stream.add([32]);
      await tester.pump(const Duration(seconds: 4));
    }
    await completed; expect(cancelled, true);
    await stream.close();
  }, timeout: const Timeout(Duration(seconds: 45)));
  testWidgets('headers arriving after deadline are discarded without body consumption', (tester) async {
    var cancelled = false, attempts = 0;
    final headers = Completer<http.StreamedResponse>();
    final stream = StreamController<List<int>>(onCancel: () { cancelled = true; });
    final api = TraderApi(client: MockClient.streaming((_, __) { attempts++; return headers.future; }));
    addTearDown(api.close);
    final completed = expectLater(api.request('POST', '/api/check', {}), throwsA(isA<ApiException>()));
    await tester.pump(const Duration(seconds: 12)); await completed;
    headers.complete(http.StreamedResponse(stream.stream, 200));
    await tester.pump();
    expect(cancelled, true); expect(attempts, 1);
    await stream.close();
  }, timeout: const Timeout(Duration(seconds: 45)));
}
