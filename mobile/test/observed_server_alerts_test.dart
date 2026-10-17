import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/observed_server_alerts.dart';

Map<String, dynamic> fixture() => jsonDecode(File('test/fixtures/observed_alert_v1.json').readAsStringSync()) as Map<String, dynamic>;

void main() {
  test('SQL pages have independently reproduced SHA and explicit ACK only', () {
    final f = fixture(), cursor = ObservedAlertCursor();
    for (var i = 0; i < 2; i++) {
      expect(cursor.accept(f['pages'][i]), f['pages'][i]);
      final before = i == 0 ? 0 : 25;
      expect(cursor.acknowledged['sequence'], before);
      final request = cursor.acknowledgementRequest();
      expect(request['expected_ack'], before);
      cursor.acceptAcknowledgement(f['acks'][i], request);
    }
    expect(cursor.after, 30); expect(cursor.acknowledged['sequence'], 30);
    expect(() => cursor.acknowledgementRequest(), throwsFormatException);
    expect(ObservedAlertCursor().accept(f['read'])['events'], isEmpty);
  });
  test('empty SQL genesis has zero anchor and no write', () {
    final cursor = ObservedAlertCursor();
    expect(cursor.accept(fixture()['empty'])['events'], isEmpty);
    expect(cursor.after, 0); expect(() => cursor.acknowledgementRequest(), throwsFormatException);
  });
  for (final mutation in ['authority','future','range','skip','duplicate','fraction','hash','time','raw_error','codes',
    'transition','empty','truncated','tail','cursor','more','ack','ack_hash']) {
    test('reject $mutation without advancing or acknowledging', () {
      final cursor = ObservedAlertCursor(), f = fixture(), page = f['pages'][0], e = page['events'][1];
      switch (mutation) {
        case 'authority': page['executionAllowed'] = true; break;
        case 'future': page['through'] = 24; break;
        case 'range': page['after'] = -1; break;
        case 'skip': page['after'] = 1; break;
        case 'duplicate': e['sequence'] = 1; break;
        case 'fraction': e['sequence'] = 2.0; break;
        case 'hash': e['eventHash'] = alertZeroHash; break;
        case 'time': e['detectedAt'] = 'no timezone'; break;
        case 'raw_error': e['active'] = ['private provider text']; break;
        case 'codes': e['active'].add(e['active'][0]); break;
        case 'transition': e['resolved'] = ['DATA_RATE_LIMITED']; break;
        case 'empty': page['events'] = []; break;
        case 'truncated': page['events'].removeLast(); break;
        case 'tail': page['throughHash'] = alertZeroHash; break;
        case 'cursor': page['nextAfter'] = 20; break;
        case 'more': page['hasMore'] = false; break;
        case 'ack': page['acknowledged']['sequence'] = 2; break;
        case 'ack_hash': page['acknowledged']['eventHash'] = 'a' * 64; break;
      }
      expect(() => cursor.accept(page), throwsFormatException);
      expect(cursor.after, null); expect(cursor.acknowledged['sequence'], 0);
      expect(cursor.accept(fixture()['pages'][0])['nextAfter'], 25);
    });
  }
  test('page retry keeps pinned cursor and ACK rejection keeps exact pending request', () {
    final cursor = ObservedAlertCursor(), f = fixture();
    cursor.accept(f['pages'][0]);
    final request = cursor.acknowledgementRequest();
    expect(() => cursor.acceptAcknowledgement(f['acks'][1],request), throwsFormatException);
    expect(cursor.acknowledgementRequest(), request);
    cursor.acceptAcknowledgement(f['acks'][0],request);
    expect(() => cursor.accept(f['pages'][0]), throwsFormatException);
    final changed = fixture()['pages'][1]; changed['throughHash'] = 'a' * 64;
    expect(() => cursor.accept(changed), throwsFormatException);
    expect(cursor.after,25); expect(cursor.acknowledged['sequence'],25);
    cursor.accept(f['pages'][1]); expect(cursor.after,30);
  });
  for (final brightness in Brightness.values) {
    testWidgets('360px RTL $brightness explicit ACK lost response and bounded page retry', (tester) async {
      tester.view.physicalSize=const Size(360,800); tester.view.devicePixelRatio=1;
      addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
      final f=fixture(), posts=<Map<String,dynamic>>[], reads=<String?>[];
      var failAck=true, failPage=true;
      final api=TraderApi(baseUrl:'https://server.invalid',token:'fixture-owner',client:MockClient((request) async {
        expect(request.headers['authorization'],'Bearer fixture-owner');
        if(request.method=='POST') {
          expect(request.url.path,'/api/observed-paper/alerts/ack');
          posts.add(jsonDecode(request.body) as Map<String,dynamic>);
          if(failAck) { failAck=false;return http.Response('{}',503); }
          return http.Response(jsonEncode(f['acks'][0]),200);
        }
        expect(request.method,'GET');expect(request.url.path,'/api/observed-paper/alerts');
        final after=request.url.queryParameters['after'];reads.add(after);
        if(after=='25' && failPage) {failPage=false;return http.Response('{}',503);}
        if(after!=null) {expect(after,'25');expect(request.url.queryParameters['through'],'30');}
        return http.Response(jsonEncode(f['pages'][after==null?0:1]),200);
      }));
      addTearDown(api.close);
      await tester.pumpWidget(MaterialApp(theme:ThemeData(brightness:brightness),home:ObservedAlertsScreen(api:api)));
      await tester.pumpAndSettle();expect(posts,isEmpty);expect(reads,[null]);
      expect(find.byKey(const Key('alerts-next')),findsNothing);
      await tester.tap(find.byKey(const Key('alerts-ack')));await tester.pumpAndSettle();
      expect(find.byKey(const Key('alerts-error')),findsOneWidget);
      expect(find.text('إعادة نفس إقرار القراءة'),findsOneWidget);
      await tester.tap(find.byKey(const Key('alerts-ack')));await tester.pumpAndSettle();
      expect(posts.length,2);expect(posts[0],posts[1]);
      await tester.tap(find.byKey(const Key('alerts-next')));await tester.pumpAndSettle();
      expect(find.byKey(const Key('alerts-error')),findsOneWidget);
      await tester.tap(find.byKey(const Key('alerts-next')));await tester.pumpAndSettle();
      expect(reads,[null,'25','25']);expect(posts.length,2);
      await tester.drag(find.byType(ListView),const Offset(0,10000));await tester.pumpAndSettle();
      expect(find.byKey(const Key('alert-event-1')),findsNothing);
      expect(find.byKey(const Key('alert-event-26')),findsOneWidget);
      expect(tester.takeException(),null);
    });
  }
}
