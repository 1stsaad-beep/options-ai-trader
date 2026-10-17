// Entirely local simulation. No imports of HTTP, sockets, TraderApi or brokers.
import 'dart:convert';
import 'dart:math' as math;
import '../protective_exit.dart';

class DemoRejected implements Exception {
  final String message;
  const DemoRejected(this.message);
  @override
  String toString() => message;
}

typedef DemoRow = Map<String, dynamic>;

class DemoEngine {
  static const symbols = [
    'NVDA',
    'AAPL',
    'TSLA',
    'MSFT',
    'AMZN',
    'META',
    'GOOGL',
    'AMD',
    'SPY',
    'QQQ',
    'JPM',
    'NFLX',
    'INTC',
    'AVGO',
    'IWM',
  ];
  static const source = 'local_synthetic_demo';
  static const active = ['OPEN', 'PARTIAL'];
  static final epoch = DateTime.utc(2026, 1, 5, 14, 30);
  int tick = 24;
  int sequence = 0;
  String scenario = 'flat';
  String theme = 'dark';
  bool marketAvailable = true;
  bool globalStop = false;
  final List<DemoRow> accounts = [];
  DateTime get now => epoch.add(Duration(minutes: tick));
  String get day => now.toIso8601String().substring(0, 10);
  String _id(String kind) => '$kind-${++sequence}';

  static DemoRow defaults() => {
    'trade_pct': 2,
    'daily_pct': 3,
    'allocation_pct': 20,
    'max_contracts': 5,
    'stop_pct': 20,
    'take_pct': 30,
    'quantity': 1,
    'fill_chunk': 1,
    'commission': 65,
    'slippage': 1,
    'strategies': ['breakout', 'pullback'],
    'holding': 'intraday',
    'automation': false,
    'mode': 'demo',
    'group': '',
    'group_allocation_pct': 30,
    'group_daily_pct': 3,
    'exposure_pct': 30,
    'elevated_risk_ack': false,
    'risk_ack_values': null,
    'entry_profile': 'balanced',
    'entry_method': 'confirmed',
    'trailing_pct': 0,
    'partial_take_pct': 0,
    'swing_max_ticks': 2880,
    'expiry_guard_days': 1,
    'scaling_enabled': false,
    'reversal_enabled': false,
    'scaling_max': 2,
    'scaling_quantity': 1,
    'scaling_cooldown': 10,
    'scaling_decreasing': true,

  };

  DemoRow account(String id) => accounts.firstWhere(
    (a) => a['id'] == id,
    orElse: () => throw const DemoRejected('الحساب المحلي غير موجود'),
  );
  List<DemoRow> rows(DemoRow a, String field) =>
      (a[field] as List).cast<DemoRow>();
  DemoRow risk(DemoRow a) => a['risk'] as DemoRow;
  void _require(bool condition, String message) {
    if (!condition) throw DemoRejected(message);
  }

  DemoRow createAccount(String name, int initial) {
    _require(
      name.trim().isNotEmpty && name.trim().length <= 80,
      'أدخل اسمًا من 1 إلى 80 حرفًا',
    );
    _require(
      initial >= 10000 && initial <= 100000000,
      'الرصيد الاصطناعي بين 100 و1,000,000 دولار',
    );
    final a = <String, dynamic>{
      'id': _id('demo'),
      'name': name.trim(),
      'initial': initial,
      'cash': initial,
      'known': true,
      'connected': true,
      'stopped': false,
      'risk': defaults(),
      'orders': <DemoRow>[],
      'positions': <DemoRow>[],
      'trades': <DemoRow>[],
      'audit': <DemoRow>[],
      'reversals': <DemoRow>[],
      'watch': <String, dynamic>{for (final s in symbols.take(3)) s: true},
    };
    accounts.add(a);
    log(a, 'إنشاء حساب', 'رصيد اصطناعي؛ لا وسيط أو أموال حقيقية');
    return a;
  }

  void rename(String id, String name) {
    _require(
      name.trim().isNotEmpty && name.trim().length <= 80,
      'اسم الحساب غير صالح',
    );
    account(id)['name'] = name.trim();
  }

  void validateRisk(DemoRow r) {
    const bounds = {
      'trade_pct': [0, 100],
      'daily_pct': [0, 100],
      'allocation_pct': [0, 100],
      'exposure_pct': [0, 100],
      'trailing_pct': [0, 95],
      'partial_take_pct': [0, 500],
      'swing_max_ticks': [1, 50000],
      'expiry_guard_days': [0, 30],
      'scaling_max': [0, 20],
      'scaling_quantity': [1, 100],
      'scaling_cooldown': [1, 10000],
      'max_contracts': [1, 100],
      'stop_pct': [1, 95],
      'take_pct': [1, 500],
      'quantity': [1, 100],
      'fill_chunk': [1, 100],
      'commission': [0, 1000],
      'slippage': [0, 100],
      'group_allocation_pct': [0, 100],
      'group_daily_pct': [0, 100],
    };
    _require(
      r.keys.toSet().length == defaults().length &&
          defaults().keys.every(r.containsKey),
      'إعدادات غير معروفة',
    );
    for (final e in bounds.entries) {
      _require(
        r[e.key] is int && r[e.key] >= e.value[0] && r[e.key] <= e.value[1],
        'قيمة خارج الحدود: ${e.key}',
      );
    }
    _require(
      ['demo', 'observe'].contains(r['mode']),
      'Paper وLive غير متاحين في Demo',
    );
    _require(
      ['intraday', 'swing'].contains(r['holding']),
      'مدة الاحتفاظ غير صالحة',
    );
    _require(
      r['automation'] is bool &&
          r['group'] is String &&
          r['group'].length <= 60,
      'إعدادات الأتمتة أو المجموعة غير صالحة',
    );
    _require(
      r['strategies'] is List &&
          (r['strategies'] as List).every(
            (s) => ['breakout', 'pullback'].contains(s),
          ),
      'استراتيجية غير مدعومة',
    );
    _require(r['quantity'] <= r['max_contracts'], 'الكمية تتجاوز حد العقود');
    _require(r['elevated_risk_ack'] is bool && r['scaling_enabled'] is bool &&
      r['scaling_decreasing'] is bool && r['reversal_enabled'] is bool, 'إعداد أمان غير صالح');
    _require(['conservative', 'balanced', 'opportunistic'].contains(r['entry_profile']) &&
      ['early', 'confirmed', 'pullback'].contains(r['entry_method']), 'ملف الدخول غير صالح');
    _require(!elevated(r) || (r['elevated_risk_ack'] == true && r['risk_ack_values'] == riskAcknowledgement(r)),
      'المخاطر المرتفعة تحتاج إقرارًا صريحًا بإمكان خسارة كامل رأس المال الاصطناعي');
  }

  static String riskAcknowledgement(DemoRow r) => jsonEncode({for (final key in
    ['trade_pct','daily_pct','allocation_pct','exposure_pct','group_allocation_pct','group_daily_pct']) key:r[key]});

  static bool elevated(DemoRow r) => r['trade_pct'] > 2 || r['daily_pct'] > 3 ||
    r['allocation_pct'] > 30 || r['exposure_pct'] > 30 ||
    r['group_allocation_pct'] > 30 || r['group_daily_pct'] > 3;

  void configure(String id, DemoRow changes) {
    final a = account(id), updated = {...risk(a), ...changes};
    if (changes['elevated_risk_ack'] == true) updated['risk_ack_values'] = riskAcknowledgement(updated);
    if (changes['elevated_risk_ack'] == false) updated['risk_ack_values'] = null;
    validateRisk(updated);
    a['risk'] = updated;
    log(a, 'إعدادات', 'حُفظت إعدادات هذا الحساب فقط');
  }

  void watch(String id, String symbol, {bool? enabled, bool remove = false}) {
    final a = account(id);
    symbol = symbol.trim().toUpperCase();
    _require(
      symbols.contains(symbol),
      'الرمز غير موجود في كتالوج Demo المحلي؛ لم يُتحقق لدى وسيط',
    );
    if (remove) {
      (a['watch'] as Map).remove(symbol);
    } else {
      a['watch'][symbol] = enabled ?? true;
    }
    log(
      a,
      'قائمة المراقبة',
      '$symbol ${remove
          ? 'حُذف'
          : enabled == false
          ? 'أُوقف'
          : 'فُعّل محليًا'}',
    );
  }

  void log(DemoRow a, String event, String reason) {
    rows(a, 'audit').add({
      'at': now.toIso8601String(),
      'event': event,
      'reason': reason,
      'source': source,
    });
    // Bounded local diagnostic log; financial orders/trades are not truncated.
    if (rows(a, 'audit').length > 2000) rows(a, 'audit').removeAt(0);
  }

  int underlying(String symbol, int at) {
    final seed = symbols.indexOf(symbol);
    final direction = seed.isEven ? 1 : -1;
    return 20000 +
        seed * 700 +
        direction * (at % 300) * 12 +
        (math.sin(at / 3) * 22).round();
  }

  List<DemoRow> opportunities(String id, {int? at}) {
    final a = account(id), index = at ?? tick;
    _require(index >= 24 && index <= tick, 'لا يمكن تحليل ملاحظات مستقبلية');
    final result = <DemoRow>[];
    if (!marketAvailable) return result;
    for (final s in (a['watch'] as Map).keys.cast<String>()) {
      if (a['watch'][s] != true) continue;
      final bars = List.generate(21, (i) => underlying(s, index - 20 + i));
      final prior = bars.take(20).toList();
      final sma = prior.reduce((a, b) => a + b) / prior.length;
      final up = bars.last > sma;
      final breakout = up
          ? bars.last > prior.reduce(math.max)
          : bars.last < prior.reduce(math.min);
      final volume = index % 3 == 0 ? 1500 : 1000;
      String? strategy;
      if (breakout &&
          volume >= 1200 &&
          (risk(a)['strategies'] as List).contains('breakout')) {
        strategy = 'breakout';
      } else if ((bars.last - sma).abs() < 160 &&
          (risk(a)['strategies'] as List).contains('pullback')) {
        strategy = 'pullback';
      }
      result.add({
        'symbol': s,
        'right': up ? 'CALL' : 'PUT',
        'strategy': strategy,
        'score': strategy == 'breakout'
            ? 80
            : strategy == 'pullback'
            ? 60
            : 0,
        'regime': up ? 'اتجاه صاعد اصطناعي' : 'اتجاه هابط اصطناعي',
        'reason': strategy == null
            ? 'لم تجتز القواعد الكمية'
            : strategy == 'breakout'
            ? 'اختراق إغلاق 20 ملاحظة وحجم ≥ 1.2 من الأساس الاصطناعي'
            : 'قرب المتوسط في اتجاه الحركة الاصطناعية',
        'as_of': index,
        'expires_tick': index + 3,
        'activation': bars.last,
        'invalidation': up ? prior.reduce(math.min) : prior.reduce(math.max),
        'entry_method': risk(a)['entry_method'],
        'entry_profile': risk(a)['entry_profile'],
        'source': source,
      });
    }
    result.sort((a, b) => (b['score'] as int).compareTo(a['score'] as int));
    return result;
  }

  DemoRow catalogEntry(String symbol) {
    _require(symbols.contains(symbol), 'الرمز غير موجود في الكتالوج الاصطناعي');
    return {'symbol':symbol,'instrument':'STK','exchange':'DEMO','currency':'USD',
      'contract_id':'DEMO-$symbol','options_available':true,'market_data':'synthetic_only',
      'broker_verified':false,'option_multiplier':100};
  }

  DemoRow contract(
    String symbol,
    String right, {
    String? expiry,
    int? strike,
  }) => {
    'symbol': symbol,
    'right': right,
    'expiry':
        expiry ??
        now.add(const Duration(days: 14)).toIso8601String().substring(0, 10),
    'strike': strike ?? (underlying(symbol, tick) ~/ 500) * 500,
  };
  String contractKey(DemoRow c) =>
      '${c['symbol']}|${c['right']}|${c['expiry']}|${c['strike']}';

  DemoRow quote(DemoRow c) {
    _require(marketAvailable, 'بيانات السوق الاصطناعية منقطعة؛ لا تنفيذ');
    final drift = scenario == 'rally'
        ? 65
        : scenario == 'drop'
        ? -45
        : scenario == 'wave'
        ? (math.sin(tick / 3) * 40).round()
        : 0;
    final bid = math.max(1, 100 + drift);
    return {'bid': bid, 'ask': bid + 5, 'tick': tick, 'source': source};
  }

  int exposure(DemoRow a) =>
      rows(a, 'positions').fold<int>(0, (n, p) => n + (p['cost'] as int)) +
      rows(a, 'orders')
          .where((o) => active.contains(o['status']) && o['side'] == 'BUY')
          .fold<int>(0, (n, o) => n + reserved(o));
  int reserved(DemoRow o) =>
      (o['quantity'] - o['filled']) * (o['limit'] * 100 + o['commission'])
          as int;
  int unrealized(DemoRow a) => rows(a, 'positions').fold<int>(
    0,
    (n, p) =>
        n +
        (marketAvailable ? quote(p)['bid'] as int : p['last_bid'] as int) *
            (p['quantity'] as int) *
            100 -
        (p['cost'] as int),
  );
  int realized(DemoRow a, {bool today = false}) => rows(a, 'trades')
      .where((t) => !today || t['day'] == day)
      .fold<int>(0, (n, t) => n + (t['pnl'] as int));

  DemoRow performance(String id) {
    final a = account(id), positions = rows(a, 'positions');
    final value = positions.fold<int>(
      0,
      (n, p) =>
          n +
          (marketAvailable ? quote(p)['bid'] as int : p['last_bid'] as int) *
              (p['quantity'] as int) *
              100,
    );
    return {
      'cash': a['cash'],
      'equity': a['cash'] + value,
      'realized': realized(a),
      'unrealized': unrealized(a),
      'exposure': exposure(a),
      'trades': rows(a, 'trades').length,
      'stale': !marketAvailable,
      'fees': rows(
        a,
        'orders',
      ).fold<int>(0, (n, o) => n + (o['fees_paid'] as int)),
      'source': source,
    };
  }

  void _trusted(DemoRow a) {
    validate();
    _require(
      a['known'] == true && a['connected'] == true,
      'حالة الحساب غير موثوقة؛ أعد المصالحة',
    );
    validateRisk(risk(a));
    _require(
      a['cash'] is int && a['cash'] >= 0,
      'رصيد الحساب غير صالح؛ التنفيذ مقفل',
    );
  }

  void _admitBuy(DemoRow a, int premium, int quantity, {DemoRow? existing, required DemoRow contract}) {
    final r = risk(a);
    _require(
      !globalStop && a['stopped'] == false,
      'الإيقاف الطارئ يمنع الدخول',
    );
    _require(r['mode'] == 'demo', 'وضع المراقبة لا يفتح مراكز');
    final old = existing == null ? 0 : reserved(existing);
    final total = exposure(a) - old + premium;
    final originalCost = premium +
        rows(a, 'positions').where((p) => contractKey(p) == contractKey(contract))
          .fold<int>(0, (n, p) => n + (p['cost'] as int)) +
        rows(a, 'orders').where((o) => o != existing && o['side'] == 'BUY' &&
          active.contains(o['status']) && contractKey(o) == contractKey(contract))
          .fold<int>(0, (n, o) => n + reserved(o));
    _require(
      originalCost <= a['initial'] * r['trade_pct'] ~/ 100,
      'تجاوز مخاطرة الصفقة',
    );
    _require(
      total <= a['initial'] * math.min(r['allocation_pct'] as int, r['exposure_pct'] as int) ~/ 100,
      'تجاوز التعرض المفتوح',
    );
    _require(
      realized(a, today: true) + math.min(0, unrealized(a)) >
          -(a['initial'] * r['daily_pct'] ~/ 100),
      'بلوغ حد الخسارة اليومية',
    );
    final reservedCash =
        rows(a, 'orders')
            .where((o) => active.contains(o['status']) && o['side'] == 'BUY')
            .fold<int>(0, (n, o) => n + reserved(o)) -
        old;
    _require(
      a['cash'] - reservedCash >= premium,
      'الرصيد المتاح غير كافٍ بعد حجوزات الأوامر',
    );
    final contracts =
        rows(
          a,
          'positions',
        ).fold<int>(0, (n, p) => n + (p['quantity'] as int)) +
        rows(a, 'orders')
            .where(
              (o) =>
                  active.contains(o['status']) &&
                  o['side'] == 'BUY' &&
                  o != existing,
            )
            .fold<int>(0, (n, o) => n + (o['quantity'] - o['filled']) as int);
    _require(
      contracts + quantity <= r['max_contracts'],
      'تجاوز عدد العقود للحساب',
    );
    if ((r['group'] as String).isNotEmpty) {
      final members = accounts
          .where((m) => risk(m)['group'] == r['group'])
          .toList();
      _require(
        members.every((m) => m['known'] == true && m['connected'] == true),
        'حساب مرتبط غير موثوق',
      );
      final basis = members.fold<int>(0, (n, m) => n + (m['initial'] as int));
      final cap = members
          .map((m) => risk(m)['group_allocation_pct'] as int)
          .reduce(math.min);
      final lossCap = members
          .map((m) => risk(m)['group_daily_pct'] as int)
          .reduce(math.min);
      _require(
        members.fold<int>(0, (n, m) => n + exposure(m)) - old + premium <=
            basis * cap ~/ 100,
        'المشرف العام: تجاوز تعرض المجموعة',
      );
      _require(
        members.fold<int>(
              0,
              (n, m) =>
                  n + realized(m, today: true) + math.min(0, unrealized(m)),
            ) >
            -(basis * lossCap ~/ 100),
        'المشرف العام: بلوغ خسارة المجموعة',
      );
    }
  }

  DemoRow submit(
    String id,
    DemoRow c,
    String side,
    int quantity,
    String requestKey, {
    int? limit,
    String reason = 'يدوي',
    DemoRow? evidence,
    String entryOrigin = 'manual',
    bool loseResponse = false,
  }) {
    final a = account(id), r = risk(a);
    _require(
      requestKey.isNotEmpty && requestKey.length <= 160,
      'مفتاح الطلب غير صالح',
    );
    final matches = rows(
      a,
      'orders',
    ).where((o) => o['request_key'] == requestKey);
    if (matches.isNotEmpty) {
      final o = matches.single;
      _require(
        contractKey(o) == contractKey(c) &&
            o['side'] == side &&
            o['quantity'] == quantity &&
            (limit == null || o['limit'] == limit),
        'مفتاح مكرر بمحتوى مختلف',
      );
      return o;
    }
    _trusted(a);
    validateContract(c);
    final expiry = DateTime.tryParse('${c['expiry']}T00:00:00Z');
    _require(
      expiry != null &&
          expiry.isAfter(DateTime.utc(now.year, now.month, now.day)),
      'العقد منتهٍ أو تاريخه غير صالح',
    );
    _require(
      ['BUY', 'SELL_TO_CLOSE'].contains(side) &&
          quantity > 0 &&
          quantity <= 100,
      'يسمح بالشراء أو إغلاق المملوك فقط',
    );
    final q = quote(c);
    final price =
        limit ??
        (side == 'BUY'
            ? q['ask'] + r['slippage']
            : math.max(1, q['bid'] - r['slippage']));
    _require(
      price is int && price > 0 && price <= 1000000,
      'حد السعر غير صالح',
    );
    final authorization = <String, dynamic>{
      'origin': entryOrigin,
      'strategy': ['automation', 'manual_reversal', 'automatic_reversal'].contains(entryOrigin)
          ? (evidence == null ? null : evidence['strategy']) : null,
    };
    if (side == 'BUY') {
      _authorizeEntry(a, authorization);
      _directionLock(a, c);
      _require(
        a['watch'][c['symbol']] == true,
        'فعّل الرمز في قائمة هذا الحساب',
      );
      _admitBuy(a, quantity * (price * 100 + r['commission']) as int, quantity, contract: c);
    } else {
      final owned = rows(a, 'positions')
          .where((p) => contractKey(p) == contractKey(c))
          .fold<int>(0, (n, p) => n + (p['quantity'] as int));
      final pending = rows(a, 'orders')
          .where(
            (o) =>
                contractKey(o) == contractKey(c) &&
                o['side'] == 'SELL_TO_CLOSE' &&
                active.contains(o['status']),
          )
          .fold<int>(0, (n, o) => n + (o['quantity'] - o['filled']) as int);
      _require(
        quantity <= owned - pending,
        'لا يمكن بيع عقود غير مملوكة أو محجوزة للإغلاق',
      );
    }
    final o = <String, dynamic>{
      ...contract(c['symbol'], c['right'], expiry: c['expiry'], strike: c['strike']),
      'id': _id('order'),
      'account_id': id,
      'request_key': requestKey,
      'side': side,
      'quantity': quantity,
      'filled': 0,
      'limit': price,
      'commission': r['commission'],
      'slippage': r['slippage'],
      'fees_paid': 0,
      'status': 'OPEN',
      'created_tick': tick,
      'last_fill_tick': -1,
      'reason': reason,
      // JSON text is an immutable decision-time value, never recomputed at replay.
      'decision_json': jsonEncode({
        'account_id': id, 'tick': tick, 'source': source, 'reason': reason,
        'contract': contract(c['symbol'], c['right'], expiry: c['expiry'], strike: c['strike']),
        'side': side, 'quantity': quantity, 'limit': price,
        'risk': jsonDecode(jsonEncode(r)), 'evidence': evidence,
        if (side == 'BUY') 'entry_authorization': authorization,
        'quote': q, 'known': a['known'], 'connected': a['connected'],
        'analysis_label': 'قرار محلي كمي/يدوي؛ لا تفسير لاحق من AI',
      }),
      'fills': <DemoRow>[],
    };
    rows(a, 'orders').add(o);
    log(a, 'أمر محلي', '$side ${c['symbol']} — $reason');
    if (loseResponse) {
      a['known'] = false;
      log(
        a,
        'فقد الاستجابة',
        'الطلب محفوظ؛ لا تعِد إنشاء أمر جديد، صالح الحساب',
      );
      throw const DemoRejected(
        'محاكاة فقد استجابة: قد يكون الأمر مقبولًا؛ صالح الحساب أولًا',
      );
    }
    return o;
  }

  DemoRow order(String id, String orderId) =>
      rows(account(id), 'orders').firstWhere(
        (o) => o['id'] == orderId && o['account_id'] == id,
        orElse: () => throw const DemoRejected('الأمر لا يخص هذا الحساب'),
      );

  void cancel(String id, String orderId) {
    final a = account(id), o = order(id, orderId);
    _trusted(a);
    if (active.contains(o['status'])) {
      o['status'] = 'CANCELLED';
      log(a, 'إلغاء', orderId);
    }
  }

  void fill(String id, String orderId) {
    final a = account(id), o = order(id, orderId);
    _trusted(a);
    if (!active.contains(o['status']) ||
        o['last_fill_tick'] == tick ||
        o['created_tick'] >= tick) {
      return;
    }
    _require('${o['expiry']}'.compareTo(day) > 0, 'لا تنفيذ لعقد منتهٍ');
    final q = quote(o), r = risk(a);
    final price = o['side'] == 'BUY'
        ? q['ask'] + o['slippage']
        : math.max(0, q['bid'] - o['slippage']);
    if ((o['side'] == 'BUY' && price > o['limit']) ||
        (o['side'] != 'BUY' && price < o['limit'])) {
      return;
    }
    final remaining = o['quantity'] - o['filled'] as int;
    final qty = math.min(remaining, r['fill_chunk'] as int);
    final fee = qty * o['commission'] as int;
    if (o['side'] == 'BUY') {
      _authorizeEntry(a, _savedEntryAuthorization(a, o));
      _directionLock(a, o, existing: o);
      if (o['reason'] == 'تعزيز مركز رابح') {
        final owned = rows(a, 'positions').where((p) => contractKey(p) == contractKey(o));
        _require(r['scaling_enabled'] == true && owned.length == 1,
          'التعزيز متوقف أو المركز لم يعد مملوكًا');
        final p = owned.single;
        _require(p['scale_count'] <= r['scaling_max'] &&
          q['bid'] * p['quantity'] * 100 > p['cost'],
          'شروط التعزيز الرابح لم تعد متحققة عند التنفيذ');
      }
      _admitBuy(a, reserved(o), remaining, existing: o, contract: o);
      _require(a['watch'][o['symbol']] == true, 'الرمز متوقف؛ ألغِ الدخول');
      final cost = price * qty * 100 + fee as int;
      _require(a['cash'] >= cost, 'الرصيد غير كافٍ للتنفيذ');
      final positions = rows(a, 'positions');
      final found = positions.where((p) => contractKey(p) == contractKey(o));
      DemoRow p;
      if (found.isEmpty) {
        p = {
          ...contract(
            o['symbol'],
            o['right'],
            expiry: o['expiry'],
            strike: o['strike'],
          ),
          'account_id': id,
          'quantity': 0,
          'cost': 0,
          'entry_tick': tick,
          'last_bid': q['bid'],
          'high_bid': q['bid'],
          'scale_count': 0, 'last_scale_tick': tick,
          'partial_taken': false,
          'entry_decisions': <String>[],
        };
        positions.add(p);
      } else {
        p = found.single;
      }
      if (o['decision_json'] != null && !(p['entry_decisions'] as List).contains(o['decision_json'])) {
        (p['entry_decisions'] as List).add(o['decision_json']);
      }
      p['quantity'] += qty;
      p['cost'] += cost;
      p['last_bid'] = q['bid'];
      p['high_bid'] = math.max(p['high_bid'] as int, q['bid'] as int);
      a['cash'] -= cost;
    } else {
      final p = rows(a, 'positions').firstWhere(
        (p) => contractKey(p) == contractKey(o),
        orElse: () => throw const DemoRejected('المركز المملوك غير موجود'),
      );
      _require(p['quantity'] >= qty, 'إغلاق يتجاوز المملوك');
      final basis = qty == p['quantity']
          ? p['cost']
          : p['cost'] * qty ~/ p['quantity'];
      final proceeds = price * qty * 100 - fee as int;
      _require(a['cash'] + proceeds >= 0, 'الرصيد غير كافٍ لعمولة الإغلاق');
      a['cash'] += proceeds;
      p['cost'] -= basis;
      p['quantity'] -= qty;
      if (o['reason'] == 'جني ربح مرحلي') p['partial_taken'] = true;
      rows(a, 'trades').add({
        'day': day,
        'tick': tick,
        'symbol': p['symbol'],
        'quantity': qty,
        'pnl': proceeds - basis,
        'reason': o['reason'],
        'account_id': id,
        'right': p['right'], 'expiry': p['expiry'], 'strike': p['strike'],
        'entry_tick': p['entry_tick'], 'exit_price': price,
        'cost_basis': basis, 'exit_fee': fee, 'order_id': o['id'],
        'entry_decisions': List<String>.from(p['entry_decisions']),
        'exit_decision': o['decision_json'],
      });
      if (p['quantity'] == 0) rows(a, 'positions').remove(p);
    }
    (o['fills'] as List).add({'tick': tick, 'quantity': qty, 'price': price, 'fee': fee});
    o['filled'] += qty;
    o['fees_paid'] += fee;
    o['last_fill_tick'] = tick;
    o['status'] = o['filled'] == o['quantity'] ? 'FILLED' : 'PARTIAL';
    log(
      a,
      'تنفيذ وهمي',
      '${o['side']} ${o['symbol']} × $qty؛ الرسوم ${(fee / 100).toStringAsFixed(2)}',
    );
  }

  void disconnect(String id) {
    final a = account(id);
    a['connected'] = false;
    a['known'] = false;
    log(a, 'انقطاع', 'لا تنفيذ قبل مصالحة محلية');
  }

  void reconcile(String id) {
    final a = account(id);
    validate();
    a['connected'] = true;
    a['known'] = true;
    log(a, 'مصالحة', 'الأوامر والمراكز والرصيد المحلي متطابقة');
  }

  void stop({String? id}) {
    if (id == null) globalStop = true;
    for (final a in id == null ? accounts : [account(id)]) {
      a['stopped'] = true;
      // Local emergency cancels unfilled entry remainders, retaining ownership.
      for (final o in rows(a, 'orders')) {
        if (o['side'] == 'BUY' && active.contains(o['status'])) {
          o['status'] = 'CANCELLED';
        }
      }
      log(
        a,
        'إيقاف طارئ',
        'منع الدخول؛ تبقى إدارة المراكز المملوكة متاحة بعد المصالحة',
      );
    }
  }

  void resume(String id) {
    final a = account(id);
    _trusted(a);
    _require(!globalStop, 'الإيقاف العام قائم؛ أعد فتحه صراحة من شاشة الطوارئ');
    a['stopped'] = false;
    log(a, 'استئناف', 'تم بطلب صريح داخل Demo');
  }

  void step({bool enter = true}) {
    validate();
    tick++;
    for (final a in accounts) {
      if (a['known'] != true || a['connected'] != true) continue;
      for (final p in List<DemoRow>.from(rows(a, 'positions'))) {
        if ('${p['expiry']}'.compareTo(day) <= 0) {
          for (final o in rows(a, 'orders')) {
            if (contractKey(o) == contractKey(p) &&
                active.contains(o['status'])) {
              o['status'] = 'CANCELLED';
            }
          }
          rows(a, 'trades').add({
            'day': day,
            'tick': tick,
            'symbol': p['symbol'],
            'quantity': p['quantity'],
            'pnl': -(p['cost'] as int),
            'reason': 'انتهاء تحفظي دون ممارسة',
            'account_id': a['id'],
            'right': p['right'], 'expiry': p['expiry'], 'strike': p['strike'],
            'entry_tick': p['entry_tick'], 'exit_price': 0,
            'cost_basis': p['cost'], 'exit_fee': 0,
            'entry_decisions': List<String>.from(p['entry_decisions']),
            'exit_decision': jsonEncode({'tick': tick, 'source': source,
              'reason': 'انتهاء تحفظي دون ممارسة', 'expiry': p['expiry']}),
          });
          rows(a, 'positions').remove(p);
          log(
            a,
            'انتهاء عقد',
            '${p['symbol']} — شطب التكلفة دون تمرين أو تعيين',
          );
        }
      }
      for (final o in List<DemoRow>.from(rows(a, 'orders'))) {
        if (!active.contains(o['status'])) continue;
        if ('${o['expiry']}'.compareTo(day) <= 0) {
          o['status'] = 'CANCELLED';
          continue;
        }
        try {
          fill(a['id'], o['id']);
        } on DemoRejected catch (e) {
          log(a, 'تعذر التنفيذ', e.message);
        }
        if (o['side'] == 'BUY' &&
            active.contains(o['status']) &&
            tick - o['created_tick'] >= 3) {
          o['status'] = 'CANCELLED';
          log(a, 'انتهاء صلاحية أمر', 'أُلغي المتبقي بعد 3 ملاحظات');
        }
      }
      if (!marketAvailable) {
        log(a, 'بيانات مفقودة', 'توقف التنفيذ والدخول؛ لا أسعار بديلة');
        continue;
      }
      final r = risk(a);
      for (final p in List<DemoRow>.from(rows(a, 'positions'))) {
        p['last_bid'] = quote(p)['bid'];
        p['high_bid'] = math.max(p['high_bid'] as int, p['last_bid'] as int);
        if (r['automation'] != true) continue;
        final mark = p['last_bid'] * p['quantity'] * 100;
        String? reason;
        var exitQty = p['quantity'] as int;
        // Shared rule and priority (STOP > TAKE > TRAIL) with Market Paper and Broker Paper.
        reason = const {stopLossExit: 'وقف خسارة', takeProfitExit: 'جني ربح', trailingStopExit: 'وقف متحرك'}[
            protectiveExitCents(basis: p['cost'] as int, value: mark as int,
                peak: (p['high_bid'] as int) * (p['quantity'] as int) * 100,
                stopPercent: r['stop_pct'] as int, takePercent: r['take_pct'] as int, trailPercent: r['trailing_pct'] as int)];
        if (reason == null && r['partial_take_pct'] > 0 && p['partial_taken'] != true &&
            p['quantity'] >= 2 && mark * 100 >= p['cost'] * (100 + r['partial_take_pct'])) {
          reason = 'جني ربح مرحلي'; exitQty = p['quantity'] ~/ 2;
        }
        if (r['holding'] == 'swing' && tick - p['entry_tick'] >= r['swing_max_ticks']) {
          reason = 'خروج Swing زمني'; exitQty = p['quantity'];
        }
        final daysToExpiry = DateTime.parse('${p['expiry']}T00:00:00Z').difference(now).inMinutes / 1440;
        if (r['expiry_guard_days'] > 0 && daysToExpiry <= r['expiry_guard_days']) {
          reason = 'حماية اقتراب الانتهاء'; exitQty = p['quantity'];
        }
        if (r['holding'] == 'intraday' && now.hour >= 20) {
          reason = 'إغلاق الجلسة الاصطناعية'; exitQty = p['quantity'];
        }
        if (reason == null) {
          if (r['scaling_enabled'] == true) {
            try { scale(a['id'], p, automatic: true); } on DemoRejected { /* hard gates remain authoritative */ }
          }
          continue;
        }
        final pendingClose = rows(a, 'orders').where(
          (o) =>
              contractKey(o) == contractKey(p) &&
              o['side'] == 'SELL_TO_CLOSE' &&
              active.contains(o['status']),
        );
        if (pendingClose.isNotEmpty) {
          for (final o in pendingClose) {
            log(a, 'تعديل حد إغلاق', '${o['id']}: سعر اصطناعي محدث دون ضمان تنفيذ');
            o['limit'] = math.max(1, p['last_bid'] - o['slippage']);
          }
          continue;
        }
        for (final o in rows(a, 'orders')) {
          if (contractKey(o) == contractKey(p) &&
              o['side'] == 'BUY' &&
              active.contains(o['status'])) {
            o['status'] = 'CANCELLED';
          }
        }
        // A known terminal cancellation may be replaced by a new decision.
        // Pending or unknown orders are never retried with a new key.
        final prefix = 'exit-${a['id']}-${contractKey(p)}-${p['entry_tick']}-$reason';
        final attempt = rows(a, 'orders').where((o) => (o['request_key'] as String).startsWith(prefix)).length;
        try {
          submit(
            a['id'],
            p,
            'SELL_TO_CLOSE',
            exitQty,
            '$prefix-$attempt',
            reason: reason,
            evidence: {'high_bid': p['high_bid'], 'mark': mark, 'cost': p['cost']},
          );
        } on DemoRejected catch (e) {
          log(a, 'رفض الإغلاق', e.message);
        }
      }
      _advanceReversals(a);
      if (!enter ||
          r['automation'] != true ||
          r['mode'] != 'demo' ||
          globalStop ||
          a['stopped'] == true ||
          now.hour >= 20) {
        continue;
      }
      for (final signal in opportunities(a['id'])) {
        if (rows(a, 'reversals').any((v) => v['symbol'] == signal['symbol'] && !['COMPLETED', 'BLOCKED', 'EXPIRED'].contains(v['state']))) continue;
        if (!_entryEligible(a, signal)) {
          log(a, 'فرصة ضائعة', '${signal['symbol']}: ${signal['reason']}');
          continue;
        }
        final opposite = rows(a, 'positions').any((p) => p['symbol'] == signal['symbol'] && p['right'] != signal['right']);
        if (opposite && r['reversal_enabled'] == true) {
          try {
            requestReversal(a['id'], signal['symbol'], signal['right'], 'auto-reverse-${a['id']}-${signal['symbol']}-$day', automatic: true);
          } on DemoRejected catch (e) { log(a, 'رفض انعكاس', e.message); }
          continue;
        }
        final key = 'auto-${a['id']}-${signal['symbol']}-$day';
        if (rows(a, 'orders').any((o) => o['request_key'] == key)) continue;
        try {
          submit(
            a['id'],
            contract(signal['symbol'], signal['right']),
            'BUY',
            r['quantity'],
            key,
            reason: signal['strategy'],
            evidence: signal,
            entryOrigin: 'automation',
          );
        } on DemoRejected catch (e) {
          log(a, 'رفض فرصة', '${signal['symbol']}: ${e.message}');
        }
      }
    }
  }

  bool _entryEligible(DemoRow a, DemoRow signal) {
    final r = risk(a);
    if (signal['strategy'] == null || signal['as_of'] != tick ||
        signal['expires_tick'] < tick) { return false; }
    if (r['entry_profile'] == 'conservative' && signal['score'] < 80) return false;
    if (r['entry_method'] == 'pullback') return signal['strategy'] == 'pullback';
    if (r['entry_method'] == 'confirmed') {
      if (tick <= 24) return false;
      return opportunities(a['id'], at: tick - 1).any((s) =>
        s['symbol'] == signal['symbol'] && s['right'] == signal['right'] &&
        s['strategy'] != null);
    }
    return true;
  }

  /// Permission at decision time is evidence, not a perpetual fill permission.
  /// Manual actions retain their explicit authority when automation is off.
  void _authorizeEntry(DemoRow a, DemoRow authorization) {
    final origin = authorization['origin'], strategy = authorization['strategy'];
    const origins = ['manual', 'automation', 'manual_reversal',
      'automatic_reversal', 'manual_scaling', 'automatic_scaling'];
    _require(origins.contains(origin), 'مصدر إذن الدخول غير موثوق');
    final quantitative = ['automation', 'manual_reversal', 'automatic_reversal'].contains(origin);
    _require(quantitative ? ['breakout', 'pullback'].contains(strategy) : strategy == null,
      'استراتيجية القرار الأصلي غير صالحة');
    final r = risk(a);
    if (quantitative) {
      _require((r['strategies'] as List).contains(strategy), 'استراتيجية الدخول الأصلية معطلة');
    }
    if (['automation', 'automatic_reversal', 'automatic_scaling'].contains(origin)) {
      _require(r['automation'] == true, 'الأتمتة معطلة؛ لا تنفيذ لدخول آلي معلق');
    }
    if (origin == 'automatic_reversal') {
      _require(r['reversal_enabled'] == true, 'الانعكاس الآلي معطل');
    }
  }

  bool _automaticReversal(DemoRow reversal) {
    if (reversal.containsKey('automatic')) {
      _require(reversal['automatic'] is bool, 'مصدر الانعكاس غير صالح');
      return reversal['automatic'] as bool;
    }
    // Compatibility only: RC2 recorded automatic provenance in its key.
    return (reversal['request_key'] as String).startsWith('auto-reverse-');
  }

  DemoRow _savedEntryAuthorization(DemoRow a, DemoRow order) {
    final text = order['decision_json'];
    final snapshot = text == null ? null : jsonDecode(text as String) as DemoRow;
    if (snapshot != null && snapshot.containsKey('entry_authorization')) {
      final authorization = snapshot['entry_authorization'];
      _require(authorization is Map<String, dynamic>, 'إذن الدخول المحفوظ غير صالح');
      return authorization as DemoRow;
    }
    // Read legacy immutable evidence without rewriting any saved decision.
    final reason = snapshot?['reason'] ?? order['reason'];
    final evidence = snapshot?['evidence'];
    if (reason == 'انعكاس بعد إغلاق ومصالحة') {
      final reversals = rows(a, 'reversals').where((v) => v['entry_order'] == order['id']);
      _require(reversals.length == 1 && evidence is Map, 'مصدر دخول الانعكاس غير محسوم');
      return {'origin': _automaticReversal(reversals.single) ? 'automatic_reversal' : 'manual_reversal',
        'strategy': (evidence as Map)['strategy']};
    }
    if (['breakout', 'pullback'].contains(reason)) {
      return {'origin': 'automation', 'strategy': evidence is Map ? evidence['strategy'] : reason};
    }
    if (reason == 'تعزيز مركز رابح') {
      // Older snapshots cannot distinguish manual scaling while auto was on.
      // Conservatively require that recorded automatic permission to remain on.
      final savedRisk = snapshot?['risk'];
      final automatic = savedRisk is Map && savedRisk['automation'] == true;
      return {'origin': automatic ? 'automatic_scaling' : 'manual_scaling', 'strategy': null};
    }
    return {'origin': 'manual', 'strategy': null};
  }

  void _directionLock(DemoRow a, DemoRow c, {DemoRow? existing}) {
    final conflict = rows(a, 'positions').any((p) =>
      p['symbol'] == c['symbol'] && p['right'] != c['right'] && p['quantity'] > 0) ||
      rows(a, 'orders').any((o) => o != existing && o['side'] == 'BUY' &&
        active.contains(o['status']) && o['symbol'] == c['symbol'] && o['right'] != c['right']);
    _require(!conflict, 'قفل الاتجاه: أغلق الاتجاه القديم بالكامل وصالح الحساب قبل العكس');
  }

  /// Profitable additions reserve their number and cooldown at acceptance, even
  /// when the response is lost. The persisted order key prevents a retry duplicate.
  DemoRow scale(String id, DemoRow c, {bool loseResponse = false, bool automatic = false}) {
    final a = account(id), r = risk(a);
    _trusted(a);
    _require(r['scaling_enabled'] == true, 'التعزيز معطل');
    final p = rows(a, 'positions').firstWhere((p) => contractKey(p) == contractKey(c),
      orElse: () => throw const DemoRejected('التعزيز يحتاج مركزًا مملوكًا'));
    _require(p['scale_count'] < r['scaling_max'], 'بلغ حد التعزيز');
    _require(tick - p['last_scale_tick'] >= r['scaling_cooldown'], 'فترة تهدئة التعزيز قائمة');
    _require(!rows(a, 'orders').any((o) => o['symbol'] == p['symbol'] && active.contains(o['status'])),
      'أمر غير محسوم يمنع التعزيز');
    final q = quote(p);
    _require(q['bid'] * p['quantity'] * 100 > p['cost'], 'التعزيز للمركز الرابح فقط');
    final qty = r['scaling_decreasing'] == true
      ? math.max(1, (r['scaling_quantity'] as int) ~/ ((p['scale_count'] as int) + 1))
      : r['scaling_quantity'] as int;
    final added = qty * ((q['ask'] + r['slippage']) * 100 + r['commission']);
    _require(p['cost'] + added <= a['initial'] * r['trade_pct'] ~/ 100,
      'التعزيز يتجاوز مخاطرة المركز الإجمالية');
    final key = 'scale-$id-${contractKey(p)}-${p['entry_tick']}-${p['scale_count']}';
    final o = submit(id, p, 'BUY', qty, key, reason: 'تعزيز مركز رابح',
      entryOrigin: automatic ? 'automatic_scaling' : 'manual_scaling',
      evidence: {'profit_at_decision': q['bid'] * p['quantity'] * 100 - p['cost'],
        'addition_number': p['scale_count'] + 1, 'cooldown_ticks': r['scaling_cooldown']});
    p['scale_count'] += 1;
    p['last_scale_tick'] = tick;
    if (loseResponse) {
      a['known'] = false;
      throw const DemoRejected('فقد رد التعزيز؛ الأمر محفوظ. المصالحة لازمة ولا يعاد الإرسال');
    }
    return o;
  }

  DemoRow requestReversal(String id, String symbol, String right, String requestKey,
      {bool automatic = false}) {
    final a = account(id);
    _require(requestKey.isNotEmpty && requestKey.length <= 120, 'مفتاح انعكاس غير صالح');
    final previous = rows(a, 'reversals').where((v) => v['request_key'] == requestKey);
    if (previous.isNotEmpty) {
      _require(previous.single['symbol'] == symbol && previous.single['right'] == right,
        'مفتاح انعكاس مكرر بمحتوى مختلف');
      return previous.single;
    }
    _trusted(a);
    _require(!globalStop && a['stopped'] == false && risk(a)['mode'] == 'demo', 'الدخول متوقف');
    _require(['CALL', 'PUT'].contains(right) && symbols.contains(symbol), 'اتجاه انعكاس غير صالح');
    final signals = opportunities(id).where((s) => s['symbol'] == symbol &&
      s['right'] == right && _entryEligible(a, s));
    _require(signals.isNotEmpty, 'لا إشارة كمية صالحة للانعكاس');
    _authorizeEntry(a, {'origin': automatic ? 'automatic_reversal' : 'manual_reversal',
      'strategy': signals.first['strategy']});
    _require(!rows(a, 'reversals').any((v) => v['symbol'] == symbol &&
      !['COMPLETED', 'EXPIRED', 'BLOCKED'].contains(v['state'])), 'انعكاس آخر غير محسوم');
    _require(rows(a, 'positions').any((p) => p['symbol'] == symbol && p['right'] != right),
      'لا مركز معاكس مملوك لإغلاقه');
    final v = <String, dynamic>{'request_key': requestKey, 'account_id': id,
      'symbol': symbol, 'right': right, 'state': 'CLOSING', 'created_tick': tick,
      'expires_tick': tick + 12, 'signal_json': jsonEncode(signals.first),
      'automatic': automatic,
      'close_orders': <String>[], 'entry_order': null};
    rows(a, 'reversals').add(v);
    for (final o in rows(a, 'orders')) {
      if (o['symbol'] == symbol && o['side'] == 'BUY' && active.contains(o['status'])) {
        o['status'] = 'CANCELLED';
      }
    }
    for (final p in rows(a, 'positions').where((p) => p['symbol'] == symbol && p['right'] != right)) {
      final closes = rows(a, 'orders').where((o) => contractKey(o) == contractKey(p) &&
        o['side'] == 'SELL_TO_CLOSE' && active.contains(o['status'])).toList();
      (v['close_orders'] as List).addAll(closes.map<String>((o) => o['id'] as String));
      final pending = closes.fold<int>(0, (n, o) => n + (o['quantity'] - o['filled']) as int);
      if (p['quantity'] > pending) {
        final o = submit(id, p, 'SELL_TO_CLOSE', p['quantity'] - pending,
          'reverse-close-$requestKey-${contractKey(p)}', reason: 'إغلاق قبل انعكاس كمي',
          evidence: signals.first);
        (v['close_orders'] as List).add(o['id']);
      }
    }
    log(a, 'انعكاس محلي', 'إغلاق $symbol أولًا؛ لا شراء معاكس قبل المصالحة');
    return v;
  }

  void _advanceReversals(DemoRow a) {
    for (final v in rows(a, 'reversals')) {
      if (['COMPLETED', 'EXPIRED', 'BLOCKED'].contains(v['state'])) continue;
      if (v['state'] == 'ENTERING') {
        final o = order(a['id'], v['entry_order']);
        if (o['status'] == 'FILLED') v['state'] = 'COMPLETED';
        if (o['status'] == 'CANCELLED') v['state'] = 'BLOCKED';
        if (active.contains(o['status'])) {
          try { _authorizeEntry(a, _savedEntryAuthorization(a, o)); }
          on DemoRejected catch (e) {
            o['status'] = 'CANCELLED'; v['state'] = 'BLOCKED';
            log(a, 'انعكاس مرفوض', e.message);
          }
        }
        continue;
      }
      if (tick > v['expires_tick']) { v['state'] = 'EXPIRED'; continue; }
      if (rows(a, 'positions').any((p) => p['symbol'] == v['symbol']) ||
          rows(a, 'orders').any((o) => o['symbol'] == v['symbol'] && active.contains(o['status']))) { continue; }
      if (!(v['close_orders'] as List).every((oid) => order(a['id'], oid)['status'] == 'FILLED')) {
        v['state'] = 'BLOCKED'; continue;
      }
      try {
        _trusted(a);
        final originalSignal = jsonDecode(v['signal_json'] as String) as DemoRow;
        _authorizeEntry(a, {'origin': _automaticReversal(v) ? 'automatic_reversal' : 'manual_reversal',
          'strategy': originalSignal['strategy']});
        reconcile(a['id']);
        final signals = opportunities(a['id']).where((s) => s['symbol'] == v['symbol'] &&
          s['right'] == v['right'] && _entryEligible(a, s));
        if (signals.isEmpty) { v['state'] = 'BLOCKED'; continue; }
        final o = submit(a['id'], contract(v['symbol'], v['right']), 'BUY', risk(a)['quantity'],
          'reverse-entry-${v['request_key']}', reason: 'انعكاس بعد إغلاق ومصالحة', evidence: signals.first,
          entryOrigin: _automaticReversal(v) ? 'automatic_reversal' : 'manual_reversal');
        v['entry_order'] = o['id']; v['state'] = 'ENTERING';
      } on DemoRejected catch (e) {
        v['state'] = 'BLOCKED'; log(a, 'انعكاس مرفوض', e.message);
      }
    }
  }

  DemoRow backtest(String id, {int steps = 120}) {
    _require(steps >= 1 && steps <= 1000, 'عدد الملاحظات 1–1000');
    final a = account(id), replay = DemoEngine()..scenario = 'wave';
    final test = replay.createAccount(
      'إعادة تشغيل تاريخية اصطناعية',
      a['initial'],
    );
    test['risk'] = {
      ...risk(a),
      'automation': true,
      'group': '',
      'mode': 'demo',
    };
    test['watch'] = Map<String, dynamic>.from(a['watch']);
    var peak = a['initial'] as int, drawdown = 0;
    final curve = <int>[];
    for (var i = 0; i < steps; i++) {
      replay.step(); // Orders created at t are eligible only at t+1.
      final equity = replay.performance(test['id'])['equity'] as int;
      peak = math.max(peak, equity);
      drawdown = math.max(drawdown, peak - equity);
      curve.add(equity);
    }
    return {
      ...replay.performance(test['id']),
      'max_drawdown': drawdown,
      'steps': steps,
      'curve': curve,
      'open_positions': replay.rows(test, 'positions').length,
      'completed_trades': replay.rows(test, 'trades'),
      'next_observation_execution': true,
      'profitability_evidence': false,
      'parameters': Map<String, dynamic>.from(risk(test)),
    };
  }

  DemoRow toJson() => {
    'version': 2,
    'source': source,
    'tick': tick,
    'sequence': sequence,
    'scenario': scenario,
    'theme': theme,
    'market': marketAvailable,
    'global_stop': globalStop,
    'accounts': accounts,
  };
  String encode() => jsonEncode(toJson());
  static DemoEngine decode(String raw) {
    try {
      final data = jsonDecode(raw) as DemoRow;
      if (![1, 2].contains(data['version']) || data['source'] != source) {
        throw const DemoRejected('صيغة حفظ Demo غير مدعومة');
      }
      final e = DemoEngine()
        ..tick = data['tick'] as int
        ..sequence = data['sequence'] as int
        ..scenario = data['scenario'] as String
        ..theme = data['theme'] as String
        ..marketAvailable = data['market'] as bool
        ..globalStop = data['global_stop'] as bool;
      e.accounts.addAll((data['accounts'] as List).cast<DemoRow>());
      if (data['version'] == 1) {
        for (final a in e.accounts) {
          a['risk'] = {...defaults(), ...e.risk(a)};
          a['reversals'] = <DemoRow>[];
          for (final o in e.rows(a, 'orders')) {
            o['decision_json'] = null; o['fills'] = <DemoRow>[];
          }
          for (final p in e.rows(a, 'positions')) {
            p.addAll({'high_bid': p['last_bid'], 'scale_count': 0,
              'last_scale_tick': p['entry_tick'], 'partial_taken': false,
              'entry_decisions': <String>[]});
          }
        }
      }
      e.validate();
      return e;
    } on DemoRejected {
      rethrow;
    } catch (_) {
      throw const DemoRejected(
        'الحفظ المحلي غير صالح؛ لن تُستبدل بياناتك تلقائيًا',
      );
    }
  }

  void validateContract(DemoRow c) {
    final date = c['expiry'] is String
        ? DateTime.tryParse('${c['expiry']}T00:00:00Z')
        : null;
    _require(
      symbols.contains(c['symbol']) &&
          ['CALL', 'PUT'].contains(c['right']) &&
          c['strike'] is int &&
          c['strike'] > 0 &&
          c['strike'] <= 100000000 &&
          date != null &&
          date.toIso8601String().substring(0, 10) == c['expiry'],
      'عقد محلي غير صالح',
    );
  }

  void validate() {
    _require(
      tick >= 24 &&
          tick <= 1000000 &&
          sequence >= 0 &&
          ['flat', 'rally', 'drop', 'wave'].contains(scenario) &&
          ['dark', 'light', 'system'].contains(theme),
      'حالة المحاكاة غير صالحة',
    );
    final ids = <String>{}, orderIds = <String>{};
    var maxId = 0;
    void checkId(dynamic id, String kind) {
      final match = id is String
          ? RegExp('^$kind-([1-9][0-9]*)\$').firstMatch(id)
          : null;
      _require(match != null, 'معرف محلي غير صالح');
      maxId = math.max(maxId, int.parse(match!.group(1)!));
    }

    for (final a in accounts) {
      checkId(a['id'], 'demo');
      _require(
        ids.add(a['id']) &&
            a['name'] is String &&
            a['name'].trim().isNotEmpty &&
            a['name'].length <= 80 &&
            a['initial'] is int &&
            a['initial'] >= 10000 &&
            a['initial'] <= 100000000 &&
            a['cash'] is int &&
            a['cash'] >= 0 &&
            a['known'] is bool &&
            a['connected'] is bool &&
            a['stopped'] is bool,
        'حساب محلي غير صالح',
      );
      validateRisk(risk(a));
      _require(
        a['watch'] is Map &&
            (a['watch'] as Map).entries.every(
              (e) => symbols.contains(e.key) && e.value is bool,
            ),
        'قائمة مراقبة غير صالحة',
      );
      final keys = <String>{};
      for (final o in rows(a, 'orders')) {
        validateContract(o);
        checkId(o['id'], 'order');
        _require(
          (o['decision_json'] == null || o['decision_json'] is String) &&
          o['fills'] is List &&
          o['account_id'] == a['id'] &&
              orderIds.add(o['id']) &&
              o['request_key'] is String &&
              o['request_key'].isNotEmpty &&
              o['request_key'].length <= 160 &&
              keys.add(o['request_key']) &&
              ['BUY', 'SELL_TO_CLOSE'].contains(o['side']) &&
              [
                'OPEN',
                'PARTIAL',
                'FILLED',
                'CANCELLED',
              ].contains(o['status']) &&
              o['quantity'] is int &&
              o['filled'] is int &&
              o['quantity'] > 0 &&
              o['quantity'] <= 100 &&
              o['filled'] >= 0 &&
              o['filled'] <= o['quantity'] &&
              o['limit'] is int &&
              o['limit'] > 0 &&
              o['limit'] <= 1000000 &&
              o['commission'] is int &&
              o['commission'] >= 0 &&
              o['commission'] <= 1000 &&
              o['slippage'] is int &&
              o['slippage'] >= 0 &&
              o['slippage'] <= 100 &&
              o['fees_paid'] is int &&
              o['fees_paid'] == o['filled'] * o['commission'] &&
              o['created_tick'] is int &&
              o['created_tick'] >= 24 &&
              o['created_tick'] <= tick &&
              o['last_fill_tick'] is int &&
              o['last_fill_tick'] <= tick &&
              (o['filled'] == 0
                  ? o['last_fill_tick'] == -1
                  : o['last_fill_tick'] > o['created_tick']) &&
              (o['status'] != 'OPEN' || o['filled'] == 0) &&
              (o['status'] != 'PARTIAL' ||
                  (o['filled'] > 0 && o['filled'] < o['quantity'])) &&
              (o['status'] != 'FILLED' || o['filled'] == o['quantity']) &&
              o['reason'] is String,
          'دفتر الأوامر تالف أو يخلط الحسابات',
        );
      }
      for (final o in rows(a, 'orders')) {
        var fillQty = 0, fillFee = 0, lastTick = o['created_tick'] as int;
        for (final receipt in (o['fills'] as List)) {
          _require(receipt is Map<String,dynamic> && receipt['quantity'] is int && receipt['quantity'] > 0 &&
            receipt['quantity'] <= o['quantity'] && receipt['fee'] is int &&
            receipt['fee'] == receipt['quantity'] * o['commission'] && receipt['tick'] is int &&
            receipt['tick'] > lastTick && receipt['tick'] <= tick && receipt['price'] is int &&
            receipt['price'] > 0 && receipt['price'] <= 1000000, 'إيصال تنفيذ محلي غير صالح');
          fillQty += receipt['quantity'] as int; fillFee += receipt['fee'] as int;
          lastTick = receipt['tick'] as int;
        }
        _require(fillQty <= o['filled'] && fillFee <= o['fees_paid'], 'مجاميع إيصالات التنفيذ غير صالحة');
        if ((o['fills'] as List).isNotEmpty) _require(lastTick == o['last_fill_tick'], 'توقيت آخر تنفيذ غير متطابق');
        if (o['decision_json'] != null) {
          _require(fillQty == o['filled'] && fillFee == o['fees_paid'], 'إيصالات التنفيذ لا تطابق الأمر');
          final snapshot = jsonDecode(o['decision_json'] as String) as DemoRow;
          _require(snapshot['account_id'] == a['id'] && snapshot['tick'] == o['created_tick'] &&
            snapshot['source'] == source && snapshot['reason'] == o['reason'] &&
            snapshot['side'] == o['side'] && snapshot['quantity'] == o['quantity'] &&
            contractKey(snapshot['contract'] as DemoRow) == contractKey(o), 'لقطة القرار لا تطابق الأمر');
        }
      }
      final directions = <String,String>{};
      for (final row in [
        ...rows(a, 'positions'),
        ...rows(a, 'orders').where((o) => o['side'] == 'BUY' && active.contains(o['status']))
      ]) {
        final previous = directions[row['symbol']];
        _require(previous == null || previous == row['right'],
          'دفتر محلي متعارض الاتجاه؛ التنفيذ مقفل حتى مراجعة الحالة');
        directions[row['symbol']] = row['right'];
      }
      final reversalKeys = <String>{};
      for (final v in rows(a, 'reversals')) {
        _require(v['account_id'] == a['id'] && v['request_key'] is String &&
          reversalKeys.add(v['request_key']) && symbols.contains(v['symbol']) &&
          ['CALL', 'PUT'].contains(v['right']) &&
          ['CLOSING', 'ENTERING', 'COMPLETED', 'BLOCKED', 'EXPIRED'].contains(v['state']) &&
          v['created_tick'] is int && v['created_tick'] <= tick &&
          v['expires_tick'] is int && v['expires_tick'] > v['created_tick'] &&
          v['signal_json'] is String && v['close_orders'] is List &&
          (!v.containsKey('automatic') || v['automatic'] is bool) &&
          (v['close_orders'] as List).every((oid) => rows(a, 'orders').any((o) => o['id'] == oid && o['side'] == 'SELL_TO_CLOSE' && o['symbol'] == v['symbol'] && o['right'] != v['right'])) &&
          (v['entry_order'] == null || rows(a, 'orders').any((o) => o['id'] == v['entry_order'] && o['side'] == 'BUY' && o['symbol'] == v['symbol'] && o['right'] == v['right'])),
          'سجل الانعكاس غير صالح أو يخلط الحسابات');
      }
      void validateEntrySnapshots(dynamic value, DemoRow contract) {
        _require(value is List, 'لقطات الدخول غير صالحة');
        for (final text in value as List) {
          _require(text is String && rows(a, 'orders').any((o) => o['side'] == 'BUY' &&
            o['decision_json'] == text && contractKey(o) == contractKey(contract)),
            'لقطة دخول لا تخص هذا الحساب والعقد');
          final snapshot = jsonDecode(text as String) as DemoRow;
          _require(snapshot['account_id'] == a['id'] && snapshot['tick'] <= tick,
            'لقطة دخول تتجاوز الحساب أو الزمن');
        }
      }
      final contracts = <String>{};
      for (final p in rows(a, 'positions')) {
        validateContract(p);
        validateEntrySnapshots(p['entry_decisions'], p);
        _require(
          p['high_bid'] is int && p['high_bid'] >= p['last_bid'] &&
          p['scale_count'] is int && p['scale_count'] >= 0 && p['scale_count'] <= 20 &&
          p['last_scale_tick'] is int && p['last_scale_tick'] >= p['entry_tick'] && p['last_scale_tick'] <= tick &&
          p['partial_taken'] is bool && p['entry_decisions'] is List &&
          (p['entry_decisions'] as List).every((v) => v is String) &&
          p['account_id'] == a['id'] &&
              p['quantity'] is int &&
              p['quantity'] > 0 &&
              p['cost'] is int &&
              p['cost'] > 0 &&
              p['last_bid'] is int &&
              p['last_bid'] >= 0 &&
              p['entry_tick'] is int &&
              p['entry_tick'] > 24 &&
              p['entry_tick'] <= tick &&
              contracts.add(contractKey(p)),
          'دفتر المراكز غير صالح',
        );
      }
      for (final o in rows(a, 'orders').where(
        (o) => o['side'] == 'SELL_TO_CLOSE' && active.contains(o['status']),
      )) {
        final owned = rows(a, 'positions')
            .where((p) => contractKey(p) == contractKey(o))
            .fold<int>(0, (n, p) => n + (p['quantity'] as int));
        final closing = rows(a, 'orders')
            .where(
              (v) =>
                  v['side'] == 'SELL_TO_CLOSE' &&
                  active.contains(v['status']) &&
                  contractKey(v) == contractKey(o),
            )
            .fold<int>(0, (n, v) => n + (v['quantity'] - v['filled']) as int);
        _require(closing <= owned, 'إغلاق معلق يتجاوز المملوك');
      }
      for (final t in rows(a, 'trades')) {
        if (t.containsKey('entry_decisions')) {
          validateContract(t);
          validateEntrySnapshots(t['entry_decisions'], t);
          _require(t['exit_decision'] == null || t['exit_decision'] is String, 'لقطة خروج غير صالحة');
          if (t['exit_decision'] != null) {
            final exit = jsonDecode(t['exit_decision'] as String) as DemoRow;
            if (t['order_id'] != null) {
              _require(rows(a, 'orders').any((o) => o['id'] == t['order_id'] &&
                o['side'] == 'SELL_TO_CLOSE' && o['decision_json'] == t['exit_decision'] &&
                contractKey(o) == contractKey(t)), 'لقطة خروج لا تخص أمر الحساب');
            } else {
              _require(t['reason'] == 'انتهاء تحفظي دون ممارسة' && exit['reason'] == t['reason'] &&
                exit['source'] == source && exit['tick'] == t['tick'] && exit['expiry'] == t['expiry'],
                'لقطة انتهاء غير صالحة');
            }
          }
        }
        _require(
          t['account_id'] == a['id'] &&
              t['pnl'] is int &&
              t['tick'] is int &&
              t['tick'] <= tick &&
              t['quantity'] is int &&
              t['quantity'] > 0 &&
              symbols.contains(t['symbol']) &&
              t['reason'] is String &&
              t['day'] ==
                  epoch
                      .add(Duration(minutes: t['tick'] as int))
                      .toIso8601String()
                      .substring(0, 10),
          'سجل الصفقات غير صالح',
        );
      }
      _require(
        a['audit'] is List &&
            rows(a, 'audit').every(
              (v) =>
                  v['source'] == source &&
                  v['at'] is String &&
                  v['event'] is String &&
                  v['reason'] is String,
            ),
        'سجل القرارات غير صالح',
      );
      final cost = rows(
        a,
        'positions',
      ).fold<int>(0, (n, p) => n + (p['cost'] as int));
      _require(
        a['cash'] + cost == a['initial'] + realized(a),
        'فشل تطابق الرصيد مع دفتر الصفقات',
      );
    }
    _require(sequence >= maxId, 'عداد المعرفات تالف؛ منع التكرار');
  }
}
