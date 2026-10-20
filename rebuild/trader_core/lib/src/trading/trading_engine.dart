/// Per-account automation loop. One [TradingEngine] instance per account;
/// accounts never share state, adapters or journals.
///
/// A cycle (call [runCycle] periodically, e.g. every minute):
///   1. Follow submitted orders: book fills, cancel stale orders (reprice next time).
///   2. Fresh broker snapshot: balances, positions, working orders.
///   3. Daily bookkeeping: equity curve, day-start equity, daily loss limit.
///   4. Analyse every watchlist symbol and every held underlying.
///   5. Exits for held positions (protective first), then scale-ins.
///   6. Entries for flat watchlist symbols, with the opposite-direction lock
///      re-checked on freshly fetched broker state right before submission.
/// Every step writes to the journal. Errors on one symbol never stop the rest.
library;

import 'dart:math' as math;

import '../analysis/analyzer.dart';
import '../analysis/signal.dart';
import '../brokers/broker_adapter.dart';
import '../market/market_calendar.dart';
import '../models.dart';
import '../strategies/capitulation_rebound.dart';
import 'account.dart';
import 'account_state.dart';
import 'cycle_record.dart';
import 'decision_engine.dart';
import 'direction_lock.dart';
import 'journal.dart';
import 'risk.dart';

class CycleSummary {
  final bool ran;
  final int ordersSubmitted;
  final int errors;
  final String noteAr;
  const CycleSummary({required this.ran, this.ordersSubmitted = 0, this.errors = 0, this.noteAr = ''});
}

class TradingEngine {
  final AccountProfile profile;
  final BrokerAdapter broker;
  final AccountState state;
  final Analyzer analyzer;
  final DateTime Function() clock;
  final int feePerContractCents;

  /// Regular-hours gate. Null = no gate (the simulator's synthetic market is
  /// 24/7). Real brokers get the NYSE calendar, confirmed by the broker clock
  /// when the adapter implements [MarketClockSource].
  final MarketHoursGate? marketHours;
  final MarketCalendar calendar;

  /// Market status seen by the last cycle (for the UI).
  MarketStatus? lastMarketStatus;

  bool _running = false;

  TradingEngine({
    required this.profile,
    required this.broker,
    required this.state,
    Analyzer? analyzer,
    DateTime Function()? clock,
    this.feePerContractCents = 65,
    MarketHoursGate? marketHours,
    bool useDefaultMarketHours = true,
    this.calendar = const MarketCalendar(),
  })  : analyzer = analyzer ?? Analyzer(),
        clock = clock ?? (() => DateTime.now().toUtc()),
        marketHours = marketHours ?? (useDefaultMarketHours ? defaultMarketHours(broker) : null);

  /// Gate used for [broker] when none is given: none for the simulator,
  /// calendar (+ broker clock if offered) for every real broker.
  static MarketHoursGate? defaultMarketHours(BrokerAdapter broker) => broker.kind == BrokerKind.simulator
      ? null
      : MarketHoursGate(clockSource: broker is MarketClockSource ? broker as MarketClockSource : null);

  /// Completed bars only (drops the still-forming last bar). The simulator's
  /// synthetic bars are complete by construction.
  static List<Candle> completedBarsFor(
          BrokerKind kind, List<Candle> bars, BarTimeframe tf, DateTime now, {MarketCalendar calendar = const MarketCalendar()}) =>
      kind == BrokerKind.simulator ? bars : calendar.completedBars(bars, tf, now);

  String? _closedLoggedFor;

  AccountSettings get s => profile.settings;
  DecisionEngine get rules => DecisionEngine(s);

  /// "No trade" notes are rate-limited per symbol (one per 30 minutes) so routine
  /// skips do not push real decisions out of the bounded journal.
  final Map<String, DateTime> _lastSkip = {};

  /// Record of the cycle in progress (null between cycles).
  CycleRecord? _current;
  String? _capNotifiedFor;

  void _log(JournalAction a, String reason, {String? symbol, Map<String, Object?> details = const {}}) {
    final now = clock();
    final rec = _current;
    if (rec != null) {
      details = {...details, 'cycle': rec.cycle};
      if (a == JournalAction.orderFilled) {
        rec.fills++;
      } else if (a == JournalAction.error) {
        rec.errors.add(symbol == null ? reason : '$symbol: $reason');
      }
      if (symbol != null && a != JournalAction.orderFilled && a != JournalAction.orderCancelled && a != JournalAction.info) {
        final n = rec.symbol(symbol);
        n.action = a.name;
        n.reasonAr = reason;
      }
    }
    if (a == JournalAction.skip && symbol != null) {
      final last = _lastSkip[symbol];
      if (last != null && now.difference(last).inMinutes < 30) return;
      _lastSkip[symbol] = now;
    }
    state.log(JournalEntry(time: now, action: a, symbol: symbol, reasonAr: reason, details: details));
  }

  /// Runs one cycle and records it in [AccountState.cycles].
  Future<CycleSummary> runCycle() async {
    final before = state.cycle;
    final rec = _current = CycleRecord(cycle: before + 1, start: clock());
    CycleSummary r;
    try {
      r = await _runCycle();
    } finally {
      _current = null;
    }
    if (state.cycle > before) {
      rec
        ..ran = r.ran
        ..noteAr = r.noteAr
        ..end = clock();
      state.addCycle(rec);
    }
    return r;
  }

  Future<CycleSummary> _runCycle() async {
    if (_running) return const CycleSummary(ran: false, noteAr: 'دورة سابقة ما زالت تعمل');
    if (!profile.enabled) return const CycleSummary(ran: false, noteAr: 'الحساب غير مفعّل');
    final invalid = s.validate();
    if (invalid.isNotEmpty) {
      _log(JournalAction.error, 'إعدادات غير صالحة: ${invalid.join('، ')}');
      return CycleSummary(ran: false, errors: 1, noteAr: invalid.first);
    }
    _running = true;
    var submitted = 0, errors = 0;
    try {
      state.cycle++;
      await _followOrders();

      final account = await broker.account();
      var positions = await broker.positions();
      var openOrders = await broker.openOrders();
      final now = clock();
      _dailyBookkeeping(account, now);
      _syncMetas(positions, now);

      // ---- market hours: no order of any kind outside regular hours ----
      final gate = marketHours;
      if (gate != null) {
        final st = await gate.status(now);
        lastMarketStatus = st;
        _current
          ?..marketPhase = st.phase.name
          ..marketSummaryAr = st.summaryAr();
        if (!st.isOpen) {
          final key = '${st.phase.name}:${st.nextOpen.toIso8601String()}';
          if (_closedLoggedFor != key) {
            _closedLoggedFor = key;
            _log(JournalAction.info, 'لا تحليل ولا أوامر: ${st.summaryAr()}${st.noteAr != null ? ' — ${st.noteAr}' : ''}',
                details: {'phase': st.phase.name, 'nextOpen': st.nextOpen.toIso8601String(), 'source': st.source.name});
          }
          return CycleSummary(ran: true, noteAr: st.summaryAr());
        }
        if (st.noteAr != null) _log(JournalAction.info, st.noteAr!);
      }

      // ---- analysis ----
      final symbols = <String>{...profile.watchlist, ...positions.map((p) => p.contract.underlying)};
      final reports = <String, AnalysisReport>{};
      final prices = <String, double>{};
      // The capitulation strategy does not use the composite engines (its own daily check runs at entry time).
      final capit = s.entryStrategy == EntryStrategy.capitulationRebound;
      for (final sym in capit ? const <String>{} : symbols) {
        try {
          final raw = await broker.bars(sym, s.timeframe, limit: 300);
          // Engines see completed bars only (the forming bar would repaint).
          final bars = completedBarsFor(broker.kind, raw, s.timeframe, now, calendar: calendar);
          if (bars.length < 60) {
            _log(JournalAction.skip, 'بيانات غير كافية للتحليل (${bars.length} شمعة)', symbol: sym);
            continue;
          }
          final report = reports[sym] = analyzer.analyze(sym, bars, weights: s.engineWeights);
          prices[sym] = bars.last.close;
          _current?.symbol(sym)
            ?..score = report.score
            ..bias = report.bias.name;
        } catch (e) {
          errors++;
          _log(JournalAction.error, 'تعذر تحليل السهم: $e', symbol: sym);
        }
      }

      // ---- exits & scale-ins ----
      // Underlyings with an exit submitted this cycle: no new entry on them until
      // the next cycle confirms the close (explicit separation of a flip).
      final exitedUnderlyings = <String>{};
      for (final p in positions) {
        final occ = p.contract.occSymbol;
        final hasWorkingSell =
            openOrders.any((o) => o.contract == p.contract && o.side == OrderSide.sellToClose && o.status.isOpen);
        if (hasWorkingSell) continue;
        try {
          final q = await broker.optionQuote(p.contract);
          if (q == null || !q.isTwoSided) {
            _log(JournalAction.skip, 'لا يوجد سعر صالح للعقد $occ — لا قرار خروج بدون سعر', symbol: p.contract.underlying);
            continue;
          }
          final meta = state.metas[occ]!;
          final report = reports[p.contract.underlying];
          final exit = capit
              ? capitulationExit(
                  position: p, meta: meta, now: now, exitDaysBeforeExpiry: s.exitDaysBeforeExpiry, cal: calendar)
              : rules.evaluateExit(
                  position: p,
                  meta: meta,
                  markCents: q.bidCents,
                  underlyingPrice: prices[p.contract.underlying],
                  report: report,
                  now: now,
                );
          if (exit != null) {
            final escalated = state.escalate.remove(occ);
            final price = exit.urgent || escalated ? q.bidCents : sellLimitPrice(q, s.entryAggressiveness);
            final sent = await _submit(
              OrderRequest(
                clientOrderId: _clientId('x', occ),
                contract: p.contract,
                side: OrderSide.sellToClose,
                quantity: exit.quantity,
                limitPriceCents: math.max(1, price),
              ),
              purpose: exit.kind.name,
              reason: exit.reasonAr,
              journalAction: JournalAction.exit,
              details: {'markCents': q.bidCents, 'entryCents': meta.entryPremiumCents, if (report != null) 'analysis': report.toJson()},
            );
            if (sent) {
              submitted++;
              exitedUnderlyings.add(p.contract.underlying);
            }
            continue;
          }
          if (capit) continue; // no scale-ins in the capitulation strategy
          final scale = rules.evaluateScaleIn(position: p, meta: meta, markCents: q.bidCents, report: report);
          if (scale != null) {
            final lock = DirectionLock.canOpen(
                symbol: p.contract.underlying, right: p.contract.right, positions: positions, openOrders: openOrders);
            if (!lock.allowed) {
              _log(JournalAction.blocked, lock.reasonAr!, symbol: p.contract.underlying);
              continue;
            }
            final sized = sizePosition(
              s: s,
              equityCents: account.equityCents,
              buyingPowerCents: account.buyingPowerCents,
              openExposureCents: _exposure(positions),
              premiumCents: q.askCents,
              multiplier: p.contract.multiplier,
              feePerContractCents: feePerContractCents,
            );
            if (s.pauseNewEntries) continue;
            if (_openingCapReached()) {
              _log(JournalAction.skip, 'تعزيز غير ممكن: بلغ عدد أوامر الفتح اليوم الحد (${s.maxOrdersPerDay})',
                  symbol: p.contract.underlying);
              continue;
            }
            final qty = math.min(scale.quantity, sized.quantity);
            if (qty <= 0) {
              _log(JournalAction.skip, 'تعزيز غير ممكن: ${sized.reasonAr}', symbol: p.contract.underlying);
              continue;
            }
            final sent = await _submit(
              OrderRequest(
                clientOrderId: _clientId('s', occ),
                contract: p.contract,
                side: OrderSide.buyToOpen,
                quantity: qty,
                limitPriceCents: limitPrice(q, state.escalate.remove(occ) ? 1.0 : s.entryAggressiveness),
              ),
              purpose: 'scaleIn',
              reason: scale.reasonAr,
              journalAction: JournalAction.scaleIn,
              details: {if (report != null) 'analysis': report.toJson()},
            );
            if (sent) submitted++;
          }
        } catch (e) {
          errors++;
          _log(JournalAction.error, 'خطأ أثناء إدارة المركز $occ: $e', symbol: p.contract.underlying);
        }
      }

      // ---- entries ----
      if (_dailyLimitHit(account, now)) {
        return CycleSummary(ran: true, ordersSubmitted: submitted, errors: errors, noteAr: 'حد الخسارة اليومي');
      }
      if (s.pauseNewEntries) {
        return CycleSummary(ran: true, ordersSubmitted: submitted, errors: errors, noteAr: 'الدخول الجديد موقوف مؤقتًا لهذا الحساب');
      }
      if (_openingCapReached()) {
        if (_capNotifiedFor != state.ordersDayKey) {
          _capNotifiedFor = state.ordersDayKey;
          _log(JournalAction.blocked, 'لا دخول جديد اليوم: بلغ عدد أوامر الفتح ${state.ordersToday} من ${s.maxOrdersPerDay}');
        }
        return CycleSummary(ran: true, ordersSubmitted: submitted, errors: errors, noteAr: 'الحد اليومي للأوامر');
      }
      positions = await broker.positions();
      openOrders = await broker.openOrders();
      var openCount = _openSlotsUsed(positions, openOrders);
      if (capit && !inEntryWindow(now, calendar)) {
        return CycleSummary(ran: true, ordersSubmitted: submitted, errors: errors, noteAr: 'خارج نافذة دخول الارتداد (15:45–15:57 نيويورك)');
      }
      List<double>? spyCloses;
      double? spyPrice;
      for (final sym in profile.watchlist) {
        if (openCount >= s.maxOpenPositions) {
          _log(JournalAction.skip, 'تم بلوغ الحد الأقصى للمراكز المفتوحة (${s.maxOpenPositions})', symbol: sym);
          break;
        }
        var report = reports[sym];
        if (report == null && !capit) continue;
        if (exitedUnderlyings.contains(sym)) {
          _log(JournalAction.skip, 'تم إرسال أمر خروج في هذه الدورة — لا دخول جديد قبل تأكيد الإغلاق', symbol: sym);
          continue;
        }
        final active = DirectionLock.activeRight(sym, positions, openOrders);
        if (active != null) continue; // managed by the exit logic above
        final cooldown = _cooldownLeft(sym, now);
        if (cooldown != null) {
          _log(JournalAction.skip, 'فترة تهدئة: لا دخول جديد على $sym قبل ${cooldown.inMinutes + 1} دقيقة', symbol: sym);
          continue;
        }
        if (_openingCapReached()) break;
        try {
          final EntryIntent? intent;
          if (capit) {
            if (spyCloses == null || spyPrice == null) {
              spyCloses = closesBeforeToday(await broker.bars('SPY', BarTimeframe.d1, limit: 300), now, calendar);
              spyPrice = await broker.lastPrice('SPY');
            }
            final closes = closesBeforeToday(await broker.bars(sym, BarTimeframe.d1, limit: 300), now, calendar);
            final price = await broker.lastPrice(sym);
            final sig = evaluateCapitulation(dailyCloses: closes, price: price, spyCloses: spyCloses, spyPrice: spyPrice);
            _current?.symbol(sym).bias = sig.fire ? Bias.bullish.name : Bias.neutral.name;
            if (!sig.fire) {
              _log(JournalAction.skip, sig.reasonAr, symbol: sym, details: {'capitulation': sig.toJson()});
              continue;
            }
            report = AnalysisReport(symbol: sym, time: now, lastClose: price, atr: null, signals: const [], score: 0);
            intent = EntryIntent(sym, OptionRight.call, report, sig.reasonAr);
          } else {
            final r0 = report!;
            intent = rules.evaluateEntry(sym, r0,
                rejection: (r) => _log(JournalAction.skip, r, symbol: sym, details: {'score': r0.score}));
          }
          if (intent == null) continue;
          final ok = await _enter(intent, account, positions, openOrders, now);
          if (ok) {
            submitted++;
            openCount++;
            // Refresh state so the next symbol sees this order.
            positions = await broker.positions();
            openOrders = await broker.openOrders();
          }
        } catch (e) {
          errors++;
          _log(JournalAction.error, 'خطأ أثناء تقييم الدخول: $e', symbol: sym);
        }
      }
      return CycleSummary(ran: true, ordersSubmitted: submitted, errors: errors);
    } catch (e) {
      _log(JournalAction.error, 'فشل الدورة: $e');
      return CycleSummary(ran: false, ordersSubmitted: submitted, errors: errors + 1, noteAr: '$e');
    } finally {
      _running = false;
    }
  }

  Future<bool> _enter(EntryIntent intent, AccountSnapshot account, List<Position> positions,
      List<BrokerOrder> openOrders, DateTime now) async {
    final sym = intent.symbol;
    final lock = DirectionLock.canOpen(symbol: sym, right: intent.right, positions: positions, openOrders: openOrders);
    if (!lock.allowed) {
      _log(JournalAction.blocked, lock.reasonAr!, symbol: sym);
      return false;
    }
    final today = DateTime.utc(now.year, now.month, now.day);
    final chain = await broker.optionChain(
      sym,
      minExpiry: today.add(Duration(days: s.minDaysToExpiry)),
      maxExpiry: today.add(Duration(days: s.maxDaysToExpiry)),
      right: intent.right,
    );
    final choice = selectContract(s: s, chain: chain, right: intent.right, spot: intent.report.lastClose, now: now);
    if (choice == null) {
      _log(JournalAction.skip, 'لا يوجد عقد ${intent.right.arabic} يحقق شروط السيولة والدلتا والانتهاء', symbol: sym);
      return false;
    }
    final q = choice.quote;
    final occ = q.contract.occSymbol;
    final price = limitPrice(q, state.escalate.remove(occ) ? 1.0 : s.entryAggressiveness);
    final sized = sizePosition(
      s: s,
      equityCents: account.equityCents,
      buyingPowerCents: account.buyingPowerCents,
      openExposureCents: _exposure(positions),
      premiumCents: price,
      multiplier: q.contract.multiplier,
      feePerContractCents: feePerContractCents,
    );
    if (sized.quantity <= 0) {
      _log(JournalAction.skip, 'لا دخول: ${sized.reasonAr}', symbol: sym);
      return false;
    }
    // Final guard on fresh broker state: nothing may have changed in between.
    final freshPositions = await broker.positions();
    final freshOrders = await broker.openOrders();
    final recheck = DirectionLock.canOpen(symbol: sym, right: intent.right, positions: freshPositions, openOrders: freshOrders);
    if (!recheck.allowed) {
      _log(JournalAction.blocked, recheck.reasonAr!, symbol: sym);
      return false;
    }
    final bias = intent.right == OptionRight.call ? Bias.bullish : Bias.bearish;
    return _submit(
      OrderRequest(
        clientOrderId: _clientId('e', occ),
        contract: q.contract,
        side: OrderSide.buyToOpen,
        quantity: sized.quantity,
        limitPriceCents: price,
      ),
      purpose: 'entry',
      reason: '${intent.reasonAr}\n${choice.reasonAr}\nالحجم: ${sized.reasonAr}',
      journalAction: JournalAction.entry,
      invalidation: intent.report.invalidationFor(bias),
      target: intent.report.firstTargetFor(bias),
      score: intent.report.score,
      engines: [for (final sig in intent.report.supporting(bias)) sig.engine.name],
      details: {
        'analysis': intent.report.toJson(),
        'contract': occ,
        'bid': q.bidCents,
        'ask': q.askCents,
        'limit': price,
        'qty': sized.quantity,
        'settings': s.toJson(),
      },
    );
  }

  /// Places [r] and journals it. Returns false (and places nothing) when the
  /// market is outside regular hours at this exact moment (last-line guard).
  Future<bool> _submit(
    OrderRequest r, {
    required String purpose,
    required String reason,
    required JournalAction journalAction,
    double? invalidation,
    double? target,
    double score = 0,
    List<String> engines = const [],
    Map<String, Object?> details = const {},
  }) async {
    if (marketHours != null) {
      final st = calendar.statusAt(clock());
      if (!st.isOpen) {
        _log(JournalAction.blocked, 'لم يُرسل الأمر: ${st.summaryAr()}', symbol: r.contract.underlying);
        return false;
      }
    }
    final o = await broker.placeOrder(r);
    final now = clock();
    if (r.side == OrderSide.buyToOpen) {
      _ensureOrdersDay(now);
      state.ordersToday++;
    }
    if (purpose == 'entry' || r.side == OrderSide.sellToClose) state.lastTradeAt[r.contract.underlying] = now;
    _current?.orders.add('${journalAction.name} ${r.side == OrderSide.buyToOpen ? 'شراء' : 'بيع'} ${r.quantity}× '
        '${r.contract.occSymbol} بحد ${(r.limitPriceCents / 100).toStringAsFixed(2)}\$ (${o.status.name})');
    state.tracked[o.id] = TrackedOrder(
      orderId: o.id,
      clientOrderId: r.clientOrderId,
      occSymbol: r.contract.occSymbol,
      side: r.side,
      purpose: purpose,
      reasonAr: reason,
      submittedCycle: state.cycle,
      underlyingInvalidation: invalidation,
      underlyingTarget: target,
      score: score,
      engines: engines,
    );
    _log(journalAction, reason, symbol: r.contract.underlying, details: {
      ...details,
      'orderId': o.id,
      'status': o.status.name,
      'side': r.side.name,
      'qty': r.quantity,
      'limitCents': r.limitPriceCents,
    });
    if (o.status == OrderStatus.rejected) {
      _log(JournalAction.error, 'رفض الوسيط الأمر: ${o.rejectReason ?? '-'}', symbol: r.contract.underlying);
    }
    await _applyFill(state.tracked[o.id]!, o);
    if (!o.status.isOpen) state.tracked.remove(o.id);
    return true;
  }

  /// Books new fills of tracked orders and cancels stale ones.
  Future<void> _followOrders() async {
    for (final t in state.tracked.values.toList()) {
      try {
        final o = await broker.order(t.orderId);
        if (o == null) {
          state.tracked.remove(t.orderId);
          _log(JournalAction.info, 'الأمر ${t.orderId} لم يعد موجودًا لدى الوسيط');
          continue;
        }
        await _applyFill(t, o);
        if (!o.status.isOpen) {
          state.tracked.remove(t.orderId);
          if (o.status == OrderStatus.cancelled || o.status == OrderStatus.rejected) {
            _log(JournalAction.orderCancelled, 'الأمر ${o.id} ${o.status == OrderStatus.rejected ? 'مرفوض' : 'ملغى'}',
                symbol: o.contract.underlying);
          }
          continue;
        }
        if (state.cycle - t.submittedCycle >= s.orderTimeoutCycles) {
          await broker.cancelOrder(t.orderId);
          state.escalate.add(t.occSymbol);
          _log(JournalAction.orderCancelled, 'إلغاء أمر لم يُنفذ خلال ${s.orderTimeoutCycles} دورات — سيعاد التسعير',
              symbol: o.contract.underlying, details: {'orderId': o.id});
        }
      } catch (e) {
        _log(JournalAction.error, 'تعذر متابعة الأمر ${t.orderId}: $e');
      }
    }
  }

  Future<void> _applyFill(TrackedOrder t, BrokerOrder o) async {
    final delta = o.filledQuantity - t.processedFilled;
    if (delta <= 0) return;
    t.processedFilled = o.filledQuantity;
    final price = o.averageFillCents ?? o.limitPriceCents;
    final now = clock();
    final fees = feePerContractCents * delta;
    if (o.side == OrderSide.buyToOpen) {
      final meta = state.metas[t.occSymbol];
      if (meta == null) {
        state.metas[t.occSymbol] = PositionMeta(
          occSymbol: t.occSymbol,
          entryTime: now,
          entryPremiumCents: price,
          initialQuantity: delta,
          entryScore: t.score,
          entryReasonAr: t.reasonAr,
          underlyingInvalidation: t.underlyingInvalidation,
          underlyingTarget: t.underlyingTarget,
          engines: t.engines,
        );
      } else {
        if (t.purpose == 'scaleIn' && t.processedFilled == delta) meta.scaleIns++;
        if (t.purpose == 'entry') meta.initialQuantity += delta;
      }
    } else {
      final meta = state.metas[t.occSymbol];
      final c = o.contract;
      state.trades.add(TradeRecord(
        occSymbol: t.occSymbol,
        underlying: c.underlying,
        right: c.right,
        entryTime: meta?.entryTime ?? now,
        exitTime: now,
        quantity: delta,
        entryPremiumCents: meta?.entryPremiumCents ?? price,
        exitPremiumCents: price,
        multiplier: c.multiplier,
        feesCents: fees * 2, // entry + exit commissions for this quantity
        exitKind: t.purpose,
        entryReasonAr: meta?.entryReasonAr ?? '',
        exitReasonAr: t.reasonAr,
        engines: meta?.engines ?? const [],
      ));
      if (meta != null && t.purpose == ExitKind.partialProfit.name) meta.partialTaken = true;
    }
    _log(JournalAction.orderFilled,
        'تنفيذ ${o.side == OrderSide.buyToOpen ? 'شراء' : 'بيع'} $delta عقد ${t.occSymbol} بسعر ${formatUsd(price)}',
        symbol: o.contract.underlying,
        details: {
          'orderId': o.id,
          'filled': o.filledQuantity,
          'of': o.quantity,
          'side': o.side.name,
          'contract': t.occSymbol,
          'priceCents': price,
        });
  }

  /// Keeps engine memory in line with what the broker actually holds.
  void _syncMetas(List<Position> positions, DateTime now) {
    final held = {for (final p in positions) p.contract.occSymbol: p};
    for (final occ in state.metas.keys.toList()) {
      if (!held.containsKey(occ)) state.metas.remove(occ);
    }
    for (final p in positions) {
      final occ = p.contract.occSymbol;
      final meta = state.metas[occ];
      if (meta == null) {
        state.metas[occ] = PositionMeta(
          occSymbol: occ,
          entryTime: now,
          entryPremiumCents: p.averageCostCents,
          initialQuantity: p.quantity,
          entryScore: 0,
          entryReasonAr: 'مركز موجود مسبقًا لدى الوسيط (تمت إضافته لإدارة المخاطر)',
        );
        _log(JournalAction.info, 'تم اكتشاف مركز $occ لدى الوسيط وأصبح تحت إدارة قواعد الخروج', symbol: p.contract.underlying);
      } else if (p.averageCostCents > 0) {
        meta.entryPremiumCents = p.averageCostCents; // broker is the source of truth
      }
    }
  }

  void _dailyBookkeeping(AccountSnapshot a, DateTime now) {
    state.addEquity(EquityPoint(now, a.equityCents));
    // The trading day is the New York date (the daily-loss limit resets at
    // midnight ET, not UTC).
    final key = NewYorkTime.dateKey(now);
    _ensureOrdersDay(now);
    if (state.dayKey != key) {
      state.dayKey = key;
      state.dayStartEquityCents = a.equityCents;
    }
  }

  void _ensureOrdersDay(DateTime now) {
    final key = NewYorkTime.dateKey(now);
    if (state.ordersDayKey != key) {
      state.ordersDayKey = key;
      state.ordersToday = 0;
    }
  }

  bool _openingCapReached() => state.ordersToday >= s.maxOrdersPerDay;

  /// Remaining cooldown for new entries on [symbol], or null.
  Duration? _cooldownLeft(String symbol, DateTime now) {
    final last = state.lastTradeAt[symbol];
    if (last == null || s.symbolCooldownMinutes <= 0) return null;
    final left = last.add(Duration(minutes: s.symbolCooldownMinutes)).difference(now);
    return left > Duration.zero ? left : null;
  }

  bool _dailyLimitHit(AccountSnapshot a, DateTime now) {
    final start = state.dayStartEquityCents;
    if (start == null || start <= 0) return false;
    final lossPct = (start - a.equityCents) / start * 100;
    if (lossPct < s.dailyLossLimitPercent) return false;
    if (state.dailyLimitNotifiedFor != state.dayKey) {
      state.dailyLimitNotifiedFor = state.dayKey;
      _log(JournalAction.blocked,
          'إيقاف الدخول لبقية اليوم: الخسارة اليومية ${lossPct.toStringAsFixed(2)}% تجاوزت ${s.dailyLossLimitPercent}%');
    }
    return true;
  }

  int _exposure(List<Position> positions) => positions.fold<int>(0, (sum, p) => sum + p.costBasisCents);

  /// Held underlyings + underlyings with a working entry order.
  int _openSlotsUsed(List<Position> positions, List<BrokerOrder> openOrders) => {
        ...positions.map((p) => p.contract.underlying),
        ...openOrders.where((o) => o.side == OrderSide.buyToOpen && o.status.isOpen).map((o) => o.contract.underlying),
      }.length;

  String _clientId(String kind, String occ) => 'oat-${profile.id}-${state.cycle}-$kind-$occ';
}
