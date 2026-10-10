import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';

void main() {
  test(
    'redirect responses are rejected without forwarding authorization',
    () async {
      final api = TraderApi(
        token: 'test-only-token',
        client: MockClient((request) async {
          expect(request.followRedirects, false);
          return http.Response(
            '',
            302,
            headers: {'location': 'https://other.example/api/accounts'},
          );
        }),
      );
      await expectLater(
        api.list('/api/accounts'),
        throwsA(isA<ApiException>()),
      );
    },
  );
  test('account path and bearer header are explicit', () async {
    final paths = <String>[];
    final api = TraderApi(
      token: 'test-only-token',
      client: MockClient((request) async {
        paths.add(request.url.path);
        expect(request.headers['Authorization'], 'Bearer test-only-token');
        return http.Response(
          jsonEncode([
            {'account_id': request.url.path.split('/')[3]},
          ]),
          200,
        );
      }),
    );
    final first = await api.list('/api/accounts/one/orders');
    final second = await api.list('/api/accounts/two/orders');
    expect(first.single['account_id'], 'one');
    expect(second.single['account_id'], 'two');
    expect(paths, ['/api/accounts/one/orders', '/api/accounts/two/orders']);
  });
  test('remote plaintext connection is rejected before sending', () async {
    var called = false;
    final api = TraderApi(
      baseUrl: 'http://remote.example',
      client: MockClient((_) async {
        called = true;
        return http.Response('[]', 200);
      }),
    );
    await expectLater(api.list('/api/accounts'), throwsA(isA<ApiException>()));
    expect(called, false);
  });
  test('server rejection and malformed payload are surfaced', () async {
    final denied = TraderApi(
      client: MockClient(
        (_) async => http.Response('{"detail":"Live locked"}', 403),
      ),
    );
    await expectLater(
      denied.list('/api/accounts'),
      throwsA(predicate((e) => e is ApiException && e.status == 403)),
    );
    final malformed = TraderApi(
      client: MockClient((_) async => http.Response('not json', 200)),
    );
    await expectLater(
      malformed.list('/api/accounts'),
      throwsA(isA<ApiException>()),
    );
  });
  test('malformed list and non-object rows fail closed', () async {
    for (final body in ['{}', '[1]', '{"items": "bad"}']) {
      final api = TraderApi(
        client: MockClient((_) async => http.Response(body, 200)),
      );
      await expectLater(
        api.list('/api/accounts'),
        throwsA(isA<ApiException>()),
      );
    }
  });
  test('URL query and credentials are rejected before transport', () async {
    for (final url in [
      'https://example.com?token=secret',
      'https://user:secret@example.com',
    ]) {
      var called = false;
      final api = TraderApi(
        baseUrl: url,
        client: MockClient((_) async {
          called = true;
          return http.Response('[]', 200);
        }),
      );
      await expectLater(
        api.list('/api/accounts'),
        throwsA(isA<ApiException>()),
      );
      expect(called, false);
    }
  });
  test('transport failure does not retry mutation', () async {
    var attempts = 0;
    final api = TraderApi(
      client: MockClient((_) async {
        attempts++;
        throw http.ClientException('offline');
      }),
    );
    await expectLater(
      api.request('POST', '/api/accounts/a/orders', {'request_key': 'stable'}),
      throwsA(isA<ApiException>()),
    );
    expect(attempts, 1);
  });
  test('mock cycle posts an empty body to the explicit account only', () async {
    final calls = <String>[];
    final api = TraderApi(
      client: MockClient((request) async {
        calls.add(request.url.path);
        expect(request.method, 'POST');
        expect(jsonDecode(request.body), <String, dynamic>{});
        return http.Response(
          jsonEncode({
            'account_id': 'account-b',
            'source': 'synthetic_mock',
            'actions': [],
          }),
          200,
        );
      }),
    );
    final result = await api.runMockCycle('account-b');
    expect(result['account_id'], 'account-b');
    expect(calls, ['/api/accounts/account-b/automation/run']);
  });
  test(
    'mock cycle rejects a result for another account or data source',
    () async {
      for (final value in [
        {'account_id': 'b', 'source': 'synthetic_mock'},
        {'account_id': 'a', 'source': 'live'},
        <String, String>{},
      ]) {
        final api = TraderApi(
          client: MockClient(
            (_) async => http.Response(jsonEncode(value), 200),
          ),
        );
        await expectLater(api.runMockCycle('a'), throwsA(isA<ApiException>()));
      }
    },
  );
  test(
    'mock cycle transport failure is sent once without automatic retry',
    () async {
      var attempts = 0;
      final api = TraderApi(
        client: MockClient((_) async {
          attempts++;
          throw http.ClientException('connection lost');
        }),
      );
      await expectLater(api.runMockCycle('a'), throwsA(isA<ApiException>()));
      expect(attempts, 1);
    },
  );
  test('empty account cannot start a mock cycle', () async {
    var called = false;
    final api = TraderApi(
      client: MockClient((_) async {
        called = true;
        return http.Response('{}', 200);
      }),
    );
    await expectLater(api.runMockCycle(' '), throwsA(isA<ApiException>()));
    expect(called, false);
  });
}
