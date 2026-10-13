import 'dart:convert';
import 'direct_alpaca.dart';
import 'market_paper_reports.dart';

Map<String, dynamic> copyPaper(Map<String, dynamic> value) =>
    jsonDecode(jsonEncode(value)) as Map<String, dynamic>;

/// Stable comparison across JSON encoders with different map insertion order.
String paperBytes(Object? value) {
  Object? normalize(Object? item) {
    if (item is Map) {
      final keys = item.keys.cast<String>().toList()..sort();
      return {for (final key in keys) key: normalize(item[key])};
    }
    if (item is List) return item.map(normalize).toList();
    return item;
  }
  return jsonEncode(normalize(value));
}

void validatePaper(Map<String, dynamic> book) {
  Never invalid() => throw const FormatException('Invalid Market Paper ledger');
  bool integer(Object? value, int minimum, int maximum) =>
      value is int && value >= minimum && value <= maximum;
  bool text(Object? value) => value is String && value.trim().isNotEmpty;
  bool timestamp(Object? value) => value is String &&
      (value.endsWith('Z') || RegExp(r'[+-]\d\d:\d\d$').hasMatch(value)) &&
      DateTime.tryParse(value) != null;
  final symbol = RegExp(r'^[A-Z][A-Z0-9.]{0,9}$');
  const maxMoney = 9007199254740991;
  if (book['version'] != 1 || book['accounts'] is! List || book['journal'] is! List) invalid();
  final ids = <String>{};
  for (final raw in book['accounts'] as List) {
    if (raw is! Map) invalid();
    final a = raw;
    if (!text(a['id']) || !ids.add(a['id'] as String) || !text(a['name']) ||
        !integer(a['cash'], 0, maxMoney) || !integer(a['initialCash'], 1, maxMoney) ||
        a['enabled'] is! bool || a['addEnabled'] is! bool ||
        a['positions'] is! Map || a['contracts'] is! Map || a['lastSignal'] is! Map ||
        !integer(a['quantity'], 1, 10)) {
      invalid();
    }
    for (final field in ['riskPercent', 'stopPercent', 'takePercent', 'trailPercent']) {
      if (!integer(a[field], 1, 50)) invalid();
    }
    if (a.containsKey('ledgerPolicy') && a['ledgerPolicy']!='receipt-v2') invalid();
    if (a.containsKey('strategy') && !paperStrategyLabels.containsKey(a['strategy'])) invalid();
    if (a.containsKey('watchlist')) {
      final watch = a['watchlist'];
      if (watch is! List || watch.isEmpty || watch.length > 10 || watch.toSet().length != watch.length ||
          watch.any((s) => s is! String || !symbol.hasMatch(s))) {
        invalid();
      }
    }
    for (final field in ['fees', 'closedTrades', 'winningTrades', 'peakEquity', 'maxDrawdown']) {
      if (a.containsKey(field) && !integer(a[field], 0, maxMoney)) invalid();
    }
    for (final field in ['allocationPercent', 'dailyLossPercent']) {
      if (a.containsKey(field) && !integer(a[field], 0, 100)) invalid();
    }
    for (final field in ['maxPositions', 'maxContracts']) {
      if (a.containsKey(field) && !integer(a[field], 1, 100)) invalid();
    }
    if (a.containsKey('holdingMode') && !['intraday','swing'].contains(a['holdingMode'])) invalid();
    if (a.containsKey('maxHoldingDays') && !integer(a['maxHoldingDays'],1,30)) invalid();
    if (a.containsKey('partialPercent') && !integer(a['partialPercent'],0,100)) invalid();
    if (a.containsKey('scenarioExit') && a['scenarioExit'] is! bool) invalid();
    if (a['closedTrades'] is int && (a['winningTrades'] is! int || a['winningTrades'] > a['closedTrades'])) invalid();
    if (a.containsKey('dailyRealized') && (a['dailyRealized'] is! Map ||
        (a['dailyRealized'] as Map).entries.any((e) => e.key is! String ||
          !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(e.key as String) || !integer(e.value, -maxMoney, maxMoney)))) {
      invalid();
    }
    for (final entry in (a['contracts'] as Map).entries) {
      if (entry.key is! String || entry.value is! String) invalid();
      final match = OptionQuote.pattern.firstMatch(entry.value as String);
      if (match == null) invalid();
      final direction = match[5] == 'C' ? 'CALL' : 'PUT';
      if (entry.key != '${match[1]}:$direction') invalid();
      final expiry = DateTime.utc(2000 + int.parse(match[2]!), int.parse(match[3]!), int.parse(match[4]!));
      if (expiry.month != int.parse(match[3]!) || expiry.day != int.parse(match[4]!) || int.parse(match[6]!) <= 0) invalid();
    }
    for (final entry in (a['lastSignal'] as Map).entries) {
      if (entry.key is! String || !symbol.hasMatch(entry.key as String) || !text(entry.value)) invalid();
    }
    for (final entry in (a['positions'] as Map).entries) {
      if (entry.key is! String || !symbol.hasMatch(entry.key as String) || entry.value is! Map) invalid();
      final p = entry.value as Map;
      if (p['contract'] is! String) invalid();
      final match = OptionQuote.pattern.firstMatch(p['contract'] as String);
      if (match == null || match[1] != entry.key ||
          p['direction'] != (match[5] == 'C' ? 'CALL' : 'PUT') ||
          !integer(p['quantity'], 1, 1000000) || !integer(p['cost'], 1, maxMoney) ||
          !integer(p['highBid'], 1, maxMoney) || p['added'] is! bool || !timestamp(p['opened'])) {
        invalid();
      }
      if (p.containsKey('entryFees') && !integer(p['entryFees'], 0, maxMoney)) invalid();
      if (p.containsKey('scenarioLevel') && (p['scenarioLevel'] is! num || !(p['scenarioLevel'] as num).isFinite || p['scenarioLevel']<=0)) invalid();
      if (p.containsKey('realizedPnl') && !integer(p['realizedPnl'],-maxMoney,maxMoney)) invalid();
      if (p.containsKey('partialTaken') && p['partialTaken'] is! bool) invalid();
      if (p.containsKey('lastCloseQuoteAt') && !timestamp(p['lastCloseQuoteAt'])) invalid();
      if (p.containsKey('consumedQuote') && !text(p['consumedQuote'])) invalid();
      if (p.containsKey('closeIntent')) {
        final intent=p['closeIntent'];
        if (intent is! Map || !{'MANUAL','STOP_LOSS','TAKE_PROFIT','TRAILING_STOP','EXPIRATION_PROTECTION','INTRADAY_EXIT','MAX_HOLDING_EXIT','CONFIRMED_DIVERGENCE','SCENARIO_EXIT','PARTIAL_PROFIT'}.contains(intent['reason']) || !integer(intent['remaining'],1,p['quantity'] as int) || !timestamp(intent['at'])) invalid();
      }
      if (p.containsKey('mark')) {
        final m = p['mark'];
        if (m is! Map || m['contract'] != p['contract'] || m['feed'] != 'opra' || !timestamp(m['at']) ||
            !integer(m['bid'], 1, maxMoney) || !integer(m['ask'], 1, maxMoney) || m['ask'] < m['bid'] ||
            !integer(m['bidSize'], 0, maxMoney) || !integer(m['askSize'], 0, maxMoney)) {
          invalid();
        }
      }
    }
  }
  final archive = book['journalArchive'] ?? [];
  if (archive is! List || archive.any((s) => s is! List)) invalid();
  final events = [for (final segment in archive) ...(segment as List), ...(book['journal'] as List)];
  for (final raw in events) {
    if (raw is! Map || !ids.contains(raw['account']) ||
        raw['symbol'] is! String || !symbol.hasMatch(raw['symbol'] as String) ||
        !text(raw['decision']) || !timestamp(raw['at'])) {
      invalid();
    }
    if (raw.containsKey('quote')) {
      final q = raw['quote'];
      if (q is! Map || q['contract'] is! String ||
          OptionQuote.pattern.firstMatch(q['contract'] as String)?.group(1) != raw['symbol'] ||
          q['feed'] != 'opra' || !timestamp(q['at']) ||
          !integer(q['bid'], 1, maxMoney) || !integer(q['ask'], 1, maxMoney) || q['ask'] < q['bid']) {
        invalid();
      }
    }
    if (raw.containsKey('evidence')) {
      final e = raw['evidence'];
      if (e is! Map || !['alpaca', 'fixture'].contains(e['source']) || e['stockDataValid'] is! bool ||
          !paperStrategyLabels.containsKey(e['strategy']) || !text(e['observation']) ||
          (e['source'] == 'alpaca' && e['stockDataValid'] == true && !timestamp(e['observation']))) {
        invalid();
      }
    }
    if (raw.containsKey('fill')) {
      final f = raw['fill'];
      if (f is! Map || raw['quote'] is! Map || !['BUY', 'SELL_TO_CLOSE'].contains(f['side']) ||
          !integer(f['quantity'], 1, 1000000) || !integer(f['price'], 1, maxMoney) ||
          !integer(f['fee'], 0, maxMoney) || !integer(f['cashAfter'], 0, maxMoney)) {
        invalid();
      }
    }
  }
  final experiment = book['experiment'];
  if (experiment != null && (experiment is! Map || experiment['id'] != 'four-accounts-three-sessions-v1' ||
      !timestamp(experiment['createdAt']) || experiment['accounts'] is! List || experiment['accounts'].length != 4 ||
      (experiment['accounts'] as List).toSet().length != 4 || (experiment['accounts'] as List).any((id) => !ids.contains(id)))) {
    invalid();
  }
  // Accounts created by this version reconcile against their original receipts.
  // Legacy history lacks quantities; it is not silently upgraded or invented.
  for (final a in (book['accounts'] as List).cast<Map>()) {
    if (a['ledgerPolicy'] != 'receipt-v2') continue;
    var cash = a['initialCash'] as int, fees = 0, closed = 0, winners = 0;
    final held = <String, Map<String, dynamic>>{}, daily = <String, int>{};
    for (final event in events.cast<Map>().where((e) => e['account'] == a['id'])) {
      final f = event['fill'];
      if (f == null) {
        if ((event['decision'] as String).startsWith('OPENED_') ||
            (event['decision'] as String).startsWith('CLOSED_') || event['decision'] == 'ADD_ON_OPRA' || (event['decision'] as String).startsWith('PARTIAL_')) {
          invalid();
        }
        continue;
      }
      final q = event['quote'] as Map, key = event['symbol'] as String;
      final qty = f['quantity'] as int, price = f['price'] as int, fee = f['fee'] as int;
      if (fee != qty * 65 || price != q[f['side'] == 'BUY' ? 'ask' : 'bid']) invalid();
      fees += fee;
      if (f['side'] == 'BUY') {
        final p = held.putIfAbsent(key, () => {'contract': q['contract'], 'quantity': 0, 'cost': 0, 'entryFees': 0, 'realizedPnl': 0});
        if (p['contract'] != q['contract']) invalid();
        p['quantity'] = (p['quantity'] as int) + qty;
        p['cost'] = (p['cost'] as int) + qty * price * 100;
        p['entryFees'] = (p['entryFees'] as int) + fee;
        cash -= qty * price * 100 + fee;
      } else {
        final p = held[key];
        if (p == null || p['contract'] != q['contract'] || qty > (p['quantity'] as int)) invalid();
        final oldQty=p['quantity'] as int;
        final cost=(p['cost'] as int)*qty~/oldQty,entry=(p['entryFees'] as int)*qty~/oldQty;
        final pnl = qty * price * 100 - fee - cost - entry;
        if (f['realizedPnl'] != pnl || f['removedCost'] != cost || f['entryFees'] != entry) invalid();
        cash += qty * price * 100 - fee;
        p['realizedPnl']=(p['realizedPnl'] as int)+pnl;
        final day = (event['at'] as String).substring(0, 10);
        daily[day] = (daily[day] ?? 0) + pnl;
        if(qty==oldQty){closed++;if((p['realizedPnl'] as int)>0)winners++;held.remove(key);}
        else{p['quantity']=oldQty-qty;p['cost']=(p['cost'] as int)-cost;p['entryFees']=(p['entryFees'] as int)-entry;}

      }
      if (cash != f['cashAfter'] || cash < 0) invalid();
    }
    final actual = {for (final p in (a['positions'] as Map).entries) p.key: {
      for (final k in ['contract', 'quantity', 'cost', 'entryFees']) k: p.value[k],
      'realizedPnl':p.value['realizedPnl']??0,
    }};
    if (cash != a['cash'] || fees != a['fees'] || closed != a['closedTrades'] || winners != a['winningTrades'] ||
        paperBytes(held) != paperBytes(actual) || paperBytes(daily) != paperBytes(a['dailyRealized'])) {
      invalid();
    }
  }
}
