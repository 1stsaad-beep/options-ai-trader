import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'api.dart';

Map<String, dynamic> _object(dynamic value) {
  if (value is! Map || value.keys.any((key) => key is! String)) {
    throw const FormatException('Invalid market data object');
  }
  return Map<String, dynamic>.from(value);
}

void _number(dynamic value, {bool nullable = false}) {
  if (value == null && nullable) return;
  if (value is! num || !value.isFinite) {
    throw const FormatException('Invalid market data number');
  }
}

DateTime _time(dynamic value) {
  if (value is! String ||
      !RegExp(r'(Z|[+-]\d\d:\d\d)$').hasMatch(value)) {
    throw const FormatException('Market timestamp needs timezone');
  }
  return DateTime.parse(value).toUtc();
}

void _identity(Map<String, dynamic> value, String account) {
  if (value['schema_version'] != 1 || value['account_id'] != account ||
      value['provider'] != 'alpaca' || value['mode'] != 'real_market_virtual' ||
      value['external_orders_enabled'] != false ||
      value['virtual_fills_enabled'] != false) {
    throw const FormatException('Untrusted market data identity or authority');
  }
}

class MarketStatus {
  final bool enabled;
  final List<String> symbols;
  final String connectionState;
  MarketStatus(this.enabled, this.symbols, this.connectionState);

  factory MarketStatus.parse(dynamic raw, String account) {
    final value = _object(raw);
    _identity(value, account);
    final symbols = value['symbols'];
    if (value['connection_enabled'] is! bool || symbols is! List ||
        symbols.any((s) => s is! String || !RegExp(r'^[A-Z][A-Z0-9.]{0,9}$').hasMatch(s)) ||
        value['connection_state'] is! String ||
        value['stock_feed'] != 'iex' || value['option_feed'] != 'indicative' ||
        value['virtual_execution_state'] != 'ANALYSIS_ONLY') {
      throw const FormatException('Invalid market status');
    }
    return MarketStatus(value['connection_enabled'] as bool,
      List<String>.from(symbols), value['connection_state'] as String);
  }
}

class MarketObservation {
  final Map<String, dynamic> value;
  final Map<String, dynamic> data;
  MarketObservation._(this.value, this.data);

  factory MarketObservation.parse(dynamic raw, String account, String symbol, String kind) {
    final value = _object(raw);
    _identity(value, account);
    final data = _object(value['data']);
    final expectedFeed = kind == 'chain' ? 'indicative' : 'iex';
    if (data['symbol'] != symbol || value['feed'] != expectedFeed ||
        value['complete'] is! bool || value['cached'] is! bool ||
        value['execution_block_reason'] is! String || value['usage'] is! String ||
        value['point_in_time_backtest_verified'] != false ||
        _time(value['captured_at']).isAfter(_time(value['served_at']))) {
      throw const FormatException('Invalid market observation provenance');
    }
    void event(dynamic raw, bool quote) {
      if (raw == null) return;
      final event = _object(raw);
      _time(event['timestamp']);
      _number(event['age_seconds']);
      if (event['fresh'] is! bool) throw const FormatException('Invalid freshness');
      for (final field in quote ? ['bp', 'ap', 'bs', 'as'] : ['p', 's']) {
        _number(event[field], nullable: true);
      }
    }
    if (kind == 'snapshot') {
      _number(data['price'], nullable: true);
      event(data['quote'], true);
      event(data['trade'], false);
    } else if (kind == 'bars') {
      final bars = data['bars'];
      if (bars is! List || data['timeframe'] is! String) {
        throw const FormatException('Invalid bars');
      }
      DateTime? previous;
      for (final raw in bars) {
        final bar = _object(raw);
        final at = _time(bar['timestamp']);
        final closed = _time(bar['closed_at']);
        if ((previous != null && !at.isAfter(previous)) || !closed.isAfter(at)) {
          throw const FormatException('Invalid bar order');
        }
        previous = at;
        for (final field in ['o', 'h', 'l', 'c', 'v']) { _number(bar[field]); }
        if ((bar['l'] as num) > math.min(bar['o'] as num, bar['c'] as num) ||
            (bar['h'] as num) < math.max(bar['o'] as num, bar['c'] as num) ||
            (bar['v'] as num) < 0) {
          throw const FormatException('Invalid OHLCV');
        }
      }
    } else if (kind == 'chain') {
      if (data['contracts'] is! List || data['quote_quality'] != 'MODIFIED_INDICATIVE_NOT_OPRA' ||
          data['trade_delay_seconds'] != 900 || data['quote_delay_seconds'] != null ||
          value['execution_block_reason'] != 'INDICATIVE_OPTIONS_NOT_EXECUTABLE') {
        throw const FormatException('Untrusted options quality');
      }
      for (final raw in data['contracts'] as List) {
        final contract = _object(raw);
        if (contract['symbol'] is! String ||
            !RegExp(r'^[A-Z][A-Z0-9.]{0,9}\d{6}[CP]\d{8}$').hasMatch(contract['symbol'] as String) ||
            contract['greeks_freshness_verified'] != false) {
          throw const FormatException('Invalid option contract');
        }
        event(contract['quote'], true);
        event(contract['trade'], false);
        _number(contract['implied_volatility'], nullable: true);
        if (contract['greeks'] != null) {
          for (final v in _object(contract['greeks']).values) { _number(v, nullable: true); }
        }
      }
    } else {
      throw const FormatException('Unknown observation');
    }
    return MarketObservation._(value, data);
  }
}

/// Separate screen with GET-only observations. It never invokes DemoEngine,
/// writes DemoStore, handles Alpaca keys or submits virtual/external orders.
class MarketDataScreen extends StatefulWidget {
  final TraderApi api;
  final List<Map<String, dynamic>> accounts;
  final String initialAccount;
  const MarketDataScreen({super.key, required this.api, required this.accounts,
    required this.initialAccount});
  @override
  State<MarketDataScreen> createState() => _MarketDataScreenState();
}

class _MarketDataScreenState extends State<MarketDataScreen> {
  late String account;
  String? symbol;
  String timeframe = '1Day';
  MarketStatus? status;
  MarketObservation? observation;
  String? error;
  String kind = 'snapshot';
  bool busy = false;
  int generation = 0;

  @override
  void initState() { super.initState(); account = widget.initialAccount; loadStatus(); }

  String get prefix => '/api/accounts/${Uri.encodeComponent(account)}/market-data';

  Future<void> loadStatus() async {
    final request = ++generation;
    final target = account;
    setState(() { busy = true; error = null; status = null; symbol = null; observation = null; });
    try {
      final value = MarketStatus.parse(await widget.api.request('GET', '$prefix/status'), target);
      if (!mounted || request != generation || account != target) return;
      setState(() { status = value; symbol = value.symbols.firstOrNull; });
    } catch (e) {
      if (mounted && request == generation) setState(() => error = message(e));
    } finally {
      if (mounted && request == generation) setState(() => busy = false);
    }
  }

  String message(Object e) {
    final text = e.toString();
    if (e is FormatException) return 'رفض بيانات غير متوافقة مع الحساب أو المصدر؛ لن تُستبدل ببيانات Demo.';
    if (text.contains('NOT_APPROVED')) return 'الاتصال ببيانات Alpaca غير مفعّل؛ يحتاج موافقة منفصلة وإعداد الخادم.';
    if (text.contains('RATE_LIMITED')) return 'بلغ طلب البيانات حد الاستخدام. انتظر فترة التهدئة ثم أعد المحاولة.';
    if (text.contains('AUTH_OR_ENTITLEMENT')) return 'تعذر التحقق من المصادقة أو حقوق البيانات على الخادم.';
    return e is ApiException ? e.message : 'تعذر الحصول على بيانات موثوقة؛ لا توجد أسعار بديلة اصطناعية.';
  }

  Future<void> fetch(String nextKind) async {
    final selected = symbol;
    if (selected == null || busy || status?.enabled != true) return;
    final request = ++generation;
    final target = account;
    setState(() { busy = true; error = null; observation = null; kind = nextKind; });
    try {
      String route;
      if (nextKind == 'chain') {
        route = '$prefix/options/${Uri.encodeComponent(selected)}/chain';
      } else if (nextKind == 'snapshot') {
        route = '$prefix/stocks/${Uri.encodeComponent(selected)}/snapshot';
      } else {
        final now = DateTime.now().toUtc();
        final end = DateTime.utc(now.year, now.month, now.day, now.hour, now.minute);
        final duration = switch (timeframe) {
          '1Min' => const Duration(hours: 6), '5Min' => const Duration(days: 1),
          '15Min' => const Duration(days: 5), '1Hour' => const Duration(days: 20),
          _ => const Duration(days: 90),
        };
        final query = Uri(queryParameters: {'start': end.subtract(duration).toIso8601String(),
          'end': end.toIso8601String(), 'timeframe': timeframe}).query;
        route = '$prefix/stocks/${Uri.encodeComponent(selected)}/bars?$query';
      }
      final value = MarketObservation.parse(await widget.api.request('GET', route), target, selected, nextKind);
      if (!mounted || request != generation || account != target || symbol != selected) return;
      setState(() => observation = value);
    } catch (e) {
      if (mounted && request == generation) setState(() => error = message(e));
    } finally {
      if (mounted && request == generation) setState(() => busy = false);
    }
  }

  String amount(dynamic value) => value is num ? value.toStringAsFixed(2) : 'غير متاح';
  Widget line(String text) => Padding(padding: const EdgeInsets.symmetric(vertical: 5), child: Text(text));

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('بيانات السوق الحقيقية')),
    body: SafeArea(child: ListView(padding: const EdgeInsets.all(16), children: [
      const Text('Real Market Data + Virtual Trading', textDirection: TextDirection.ltr),
      line('وضع مستقل عن Demo Synthetic • لا أوامر خارجية • Live مقفل'),
      const Card(child: Padding(padding: EdgeInsets.all(12), child: Text(
        'Alpaca Basic: مراقبة وتحليل فقط. أسعار الخيارات إرشادية معدلة، وليست أسعار OPRA قابلة للتعبئة. التنفيذ الوهمي متوقف حتى تتوفر بيانات عقود مؤهلة.'))),
      DropdownButtonFormField<String>(key: ValueKey('market-account-$account'), initialValue: account,
        isExpanded: true, decoration: const InputDecoration(labelText: 'حساب الخادم'),
        items: widget.accounts.map((a) => DropdownMenuItem(value: '${a['id'] ?? a['account_id']}',
          child: Text('${a['name'] ?? a['id']}'))).toList(),
        onChanged: (v) { if (v != null && v != account) { setState(() => account = v); loadStatus(); } }),
      line('قائمة هذا الحساب من الخادم؛ أضف الرموز من قائمة المراقبة. بيانات Demo المحلية وحساباته محفوظة بصورة مستقلة.'),
      if (busy) const LinearProgressIndicator(),
      if (error != null) Semantics(liveRegion: true, child: line(error!)),
      OutlinedButton(onPressed: busy ? null : loadStatus, child: const Text('تحديث حالة الاتصال والقائمة')),
      if (status != null) ...[
        if (!status!.enabled) line('الاتصال غير مفعّل. مفاتيح Alpaca تُضبط على الخادم فقط بعد موافقة منفصلة؛ لا تُدخلها في الهاتف أو المحادثة.'),
        if (status!.symbols.isEmpty) line('قائمة المراقبة فارغة لهذا الحساب.'),
        if (status!.symbols.isNotEmpty) DropdownButtonFormField<String>(
          key: ValueKey('market-symbol-$account-$symbol'), initialValue: symbol, isExpanded: true,
          decoration: const InputDecoration(labelText: 'رمز السهم'),
          items: status!.symbols.map((s) => DropdownMenuItem(value: s, child: Text(s))).toList(),
          onChanged: (v) { ++generation; setState(() { symbol = v; observation = null; error = null; busy = false; }); }),
        DropdownButtonFormField<String>(initialValue: timeframe, isExpanded: true,
          decoration: const InputDecoration(labelText: 'فاصل OHLCV'),
          items: ['1Min','5Min','15Min','1Hour','1Day'].map((f) => DropdownMenuItem(value: f, child: Text(f))).toList(),
          onChanged: busy ? null : (v) => setState(() { timeframe = v!; observation = null; })),
        Wrap(spacing: 8, children: [
          for (final item in [('snapshot','جلب السعر'), ('bars','جلب OHLCV'), ('chain','خيارات إرشادية')])
            OutlinedButton(onPressed: busy || !status!.enabled || symbol == null ? null : () => fetch(item.$1), child: Text(item.$2)),
        ]),
      ],
      if (observation != null) ...results(observation!),
    ])),
  );

  List<Widget> results(MarketObservation observation) {
    final value = observation.value, data = observation.data;
    return [
      line('المصدر: Alpaca / ${value['feed']} • ${value['cached'] == true ? 'من الذاكرة المؤقتة' : 'ملاحظة جديدة'}'),
      line('التقاط UTC: ${value['captured_at']}'),
      if (value['complete'] != true) line('نتيجة جزئية: بلغنا حد صفحات الطلب، ولا نمثلها كسلسلة كاملة.'),
      if (kind == 'snapshot') ...[
        line('آخر صفقة IEX: ${amount(data['price'])} USD'),
        line('IEX بورصة واحدة؛ ليست تغطية مجمعة أو أفضل سعر وطني.'),
        if (data['trade'] != null) line('توقيت الصفقة UTC: ${data['trade']['timestamp']} • ${data['trade']['fresh'] == true ? 'ضمن 60 ثانية' : 'قديمة — للمراقبة فقط'}'),
        line('Bid: ${amount(data['quote']?['bp'])} • Ask: ${amount(data['quote']?['ap'])}'),
        if (data['quote'] != null) line('توقيت العرض UTC: ${data['quote']['timestamp']} • العمر ${amount(data['quote']['age_seconds'])} ثانية'),
        if (data['price'] == null) line('لا توجد صفقة بسعر صالح؛ لم يُولّد سعر بديل.'),
      ],
      if (kind == 'bars') ...[
        line('OHLCV • ${data['timeframe']} • ${(data['bars'] as List).length} شمعة مكتملة • أسعار خام'),
        if ((data['bars'] as List).isEmpty) line('لا توجد شموع مكتملة متاحة ضمن الفترة والصلاحيات.'),
        if ((data['bars'] as List).isNotEmpty) MarketCandleChart(bars: List<Map<String, dynamic>>.from(data['bars'] as List)),
        line('تكبير بإصبعين وتحريك • الوقت UTC • لا ترقيم أو تحليل مصطنع'),
      ],
      if (kind == 'chain') ...[
        line('عروض خيارات معدلة إرشادية؛ تأخير العرض غير محدد. الصفقات مشتقة ومتأخرة 15 دقيقة.'),
        if ((data['contracts'] as List).isEmpty) line('لا توجد خيارات متاحة لهذه العينة أو الصلاحيات.'),
        for (final raw in (data['contracts'] as List).take(20)) Card(child: Padding(padding: const EdgeInsets.all(10), child: Column(
          crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${raw['symbol']}', textDirection: TextDirection.ltr),
            Text('Bid ${amount(raw['quote']?['bp'])} / Ask ${amount(raw['quote']?['ap'])} — إرشادي'),
            Text('توقيت العرض UTC: ${raw['quote']?['timestamp'] ?? 'غير متاح'}'),
            Text('Greeks: ${raw['greeks'] == null ? 'غير متاحة؛ لم تُقدّر محليًا' : jsonEncode(raw['greeks'])}'),
            const Text('حداثة Greeks غير مثبتة؛ لا إذن تنفيذ'),
          ]))),
        if ((data['contracts'] as List).length > 20) line('عرض أول 20 عقدًا من ${(data['contracts'] as List).length} عقدًا مستلمًا.'),
      ],
      line('حقوق الاستخدام تخضع لاتفاقيات Alpaca والبورصات؛ لا يمنح التطبيق حق إعادة توزيع البيانات.'),
    ];
  }
}

class MarketCandleChart extends StatelessWidget {
  final List<Map<String, dynamic>> bars;
  const MarketCandleChart({super.key, required this.bars});
  @override
  Widget build(BuildContext context) {
    final visible = bars.length > 120 ? bars.sublist(bars.length - 120) : bars;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (bars.length > 120) const Text('الشارت يعرض آخر 120 شمعة مستلمة'),
      Semantics(label: 'شموع OHLCV حقيقية من IEX بتوقيت UTC', child: SizedBox(height: 270,
        child: ClipRect(child: InteractiveViewer(minScale: 1, maxScale: 6,
          child: CustomPaint(size: const Size(double.infinity, 270),
            painter: _MarketCandles(visible, Theme.of(context).colorScheme.onSurface)))))),
    ]);
  }
}

class _MarketCandles extends CustomPainter {
  final List<Map<String, dynamic>> bars;
  final Color textColor;
  _MarketCandles(this.bars, this.textColor);
  @override
  void paint(Canvas canvas, Size size) {
    if (bars.isEmpty) return;
    final low = bars.map((b) => (b['l'] as num).toDouble()).reduce(math.min);
    final high = bars.map((b) => (b['h'] as num).toDouble()).reduce(math.max);
    final range = math.max(high - low, math.max(high.abs() * .001, .01));
    final top = high + range * .1, bottom = low - range * .1;
    final plot = Rect.fromLTWH(55, 12, math.max(size.width - 65, 1), size.height - 48);
    double y(num value) => plot.bottom - (value - bottom) / (top - bottom) * plot.height;
    void label(String value, Offset offset) {
      final painter = TextPainter(text: TextSpan(text: value, style: TextStyle(color: textColor, fontSize: 10)),
        textDirection: TextDirection.ltr)..layout(maxWidth: size.width);
      painter.paint(canvas, offset);
    }
    for (var i = 0; i < 4; i++) {
      final price = bottom + (top - bottom) * i / 3;
      canvas.drawLine(Offset(plot.left, y(price)), Offset(plot.right, y(price)), Paint()..color = textColor.withValues(alpha: .15));
      label(price.toStringAsFixed(2), Offset(0, y(price)-5));
    }
    final step = plot.width / bars.length;
    for (var i = 0; i < bars.length; i++) {
      final b = bars[i], x = plot.left + step * (i + .5);
      final paint = Paint()..color = (b['c'] as num) >= (b['o'] as num) ? Colors.teal : Colors.deepOrange;
      canvas.drawLine(Offset(x, y(b['h'] as num)), Offset(x, y(b['l'] as num)), paint);
      final a = y(b['o'] as num), z = y(b['c'] as num);
      canvas.drawRect(Rect.fromLTWH(x-step*.3, math.min(a,z), math.max(step*.6,1), math.max((a-z).abs(),1)), paint);
    }
    label('${bars.first['timestamp']}'.substring(0,16).replaceAll('T',' '), Offset(plot.left, plot.bottom+8));
    if (size.width > 320) label('${bars.last['timestamp']}'.substring(0,16).replaceAll('T',' '), Offset(math.max(plot.right-105,plot.left),plot.bottom+23));
  }
  @override
  bool shouldRepaint(covariant _MarketCandles old) => old.bars != bars || old.textColor != textColor;
}
