// Entirely local simulation. No imports of HTTP, sockets, TraderApi or brokers.
import 'dart:convert';
import 'dart:math' as math;

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
      'trade_pct': [1, 2],
      'daily_pct': [1, 3],
      'allocation_pct': [1, 30],
      'max_contracts': [1, 100],
      'stop_pct': [1, 95],
      'take_pct': [1, 500],
      'quantity': [1, 100],
      'fill_chunk': [1, 100],
      'commission': [0, 1000],
      'slippage': [0, 100],
      'group_allocation_pct': [1, 30],
      'group_daily_pct': [1, 3],
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
  }

  void configure(String id, DemoRow changes) {
    final a = account(id), updated = {...risk(a), ...changes};
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
        'source': source,
      });
    }
    result.sort((a, b) => (b['score'] as int).compareTo(a['score'] as int));
    return result;
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

  void _admitBuy(DemoRow a, int premium, int quantity, {DemoRow? existing}) {
    final r = risk(a);
    _require(
      !globalStop && a['stopped'] == false,
      'الإيقاف الطارئ يمنع الدخول',
    );
    _require(r['mode'] == 'demo', 'وضع المراقبة لا يفتح مراكز');
    final old = existing == null ? 0 : reserved(existing);
    final total = exposure(a) - old + premium;
    final originalCost = existing == null
        ? premium
        : existing['quantity'] *
              (existing['limit'] * 100 + existing['commission']);
    _require(
      originalCost <= a['initial'] * r['trade_pct'] ~/ 100,
      'تجاوز مخاطرة الصفقة',
    );
    _require(
      total <= a['initial'] * r['allocation_pct'] ~/ 100,
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
    if (side == 'BUY') {
      _require(
        a['watch'][c['symbol']] == true,
        'فعّل الرمز في قائمة هذا الحساب',
      );
      _admitBuy(a, quantity * (price * 100 + r['commission']) as int, quantity);
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
      ...c,
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
      _admitBuy(a, reserved(o), remaining, existing: o);
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
        };
        positions.add(p);
      } else {
        p = found.single;
      }
      p['quantity'] += qty;
      p['cost'] += cost;
      p['last_bid'] = q['bid'];
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
      rows(a, 'trades').add({
        'day': day,
        'tick': tick,
        'symbol': p['symbol'],
        'quantity': qty,
        'pnl': proceeds - basis,
        'reason': o['reason'],
        'account_id': id,
      });
      if (p['quantity'] == 0) rows(a, 'positions').remove(p);
    }
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
        if (r['automation'] != true) continue;
        final mark = p['last_bid'] * p['quantity'] * 100;
        String? reason;
        if (mark * 100 <= p['cost'] * (100 - r['stop_pct'])) {
          reason = 'وقف خسارة';
        }
        if (mark * 100 >= p['cost'] * (100 + r['take_pct'])) reason = 'جني ربح';
        if (r['holding'] == 'intraday' && now.hour >= 20) {
          reason = 'إغلاق الجلسة الاصطناعية';
        }
        if (reason == null) continue;
        final pendingClose = rows(a, 'orders').where(
          (o) =>
              contractKey(o) == contractKey(p) &&
              o['side'] == 'SELL_TO_CLOSE' &&
              active.contains(o['status']),
        );
        if (pendingClose.isNotEmpty) {
          for (final o in pendingClose) {
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
        try {
          submit(
            a['id'],
            p,
            'SELL_TO_CLOSE',
            p['quantity'],
            'exit-${a['id']}-${contractKey(p)}-${p['entry_tick']}',
            reason: reason,
          );
        } on DemoRejected catch (e) {
          log(a, 'رفض الإغلاق', e.message);
        }
      }
      if (!enter ||
          r['automation'] != true ||
          r['mode'] != 'demo' ||
          globalStop ||
          a['stopped'] == true ||
          now.hour >= 20) {
        continue;
      }
      for (final signal in opportunities(a['id'])) {
        if (signal['strategy'] == null) {
          log(a, 'فرصة ضائعة', '${signal['symbol']}: ${signal['reason']}');
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
          );
        } on DemoRejected catch (e) {
          log(a, 'رفض فرصة', '${signal['symbol']}: ${e.message}');
        }
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
    'version': 1,
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
      if (data['version'] != 1 || data['source'] != source) {
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
      final contracts = <String>{};
      for (final p in rows(a, 'positions')) {
        validateContract(p);
        _require(
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
