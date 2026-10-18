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
import '../models.dart';
import 'account.dart';
import 'account_state.dart';
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

  bool _running = false;

  TradingEngine({
    required this.profile,
    required this.broker,
    required this.state,
    Analyzer? analyzer,
    DateTime Function()? clock,
    this.feePerContractCents = 65,
  })  : analyzer = analyzer ?? Analyzer(),
        clock = clock ?? (() => DateTime.now().toUtc());

  AccountSettings get s => profile.settings;
  DecisionEngine get rules => DecisionEngine(s);

  /// "No trade" notes are rate-limited per symbol (one per 30 minutes) so routine
  /// skips do not push real decisions out of the bounded journal.
  final Map<String, DateTime> _lastSkip = {};

  void _log(JournalAction a, String reason, {String? symbol, Map<String, Object?> details = const {}}) {
    final now = clock();
    if (a == JournalAction.skip && symbol != null) {
      final last = _lastSkip[symbol];
      if (last != null && now.difference(last).inMinutes < 30) return;
      _lastSkip[symbol] = now;
    }
    state.log(JournalEntry(time: now, action: a, symbol: symbol, reasonAr: reason, details: details));
  }

  Future<CycleSummary> runCycle() async {
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

      // ---- analysis ----
      final symbols = <String>{...profile.watchlist, ...positions.map((p) => p.contract.underlying)};
      final reports = <String, AnalysisReport>{};
      final prices = <String, double>{};
      for (final sym in symbols) {
        try {
          final bars = await broker.bars(sym, s.timeframe, limit: 300);
          if (bars.length < 60) {
            _log(JournalAction.skip, 'بيانات غير كافية للتحليل (${bars.length} شمعة)', symbol: sym);
            continue;
          }
          reports[sym] = analyzer.analyze(sym, bars, weights: s.engineWeights);
          prices[sym] = bars.last.close;
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
          final exit = rules.evaluateExit(
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
            await _submit(
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
            submitted++;
            exitedUnderlyings.add(p.contract.underlying);
            continue;
          }
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
            final qty = math.min(scale.quantity, sized.quantity);
            if (qty <= 0) {
              _log(JournalAction.skip, 'تعزيز غير ممكن: ${sized.reasonAr}', symbol: p.contract.underlying);
              continue;
            }
            await _submit(
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
            submitted++;
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
      positions = await broker.positions();
      openOrders = await broker.openOrders();
      var openCount = _openSlotsUsed(positions, openOrders);
      for (final sym in profile.watchlist) {
        if (openCount >= s.maxOpenPositions) {
          _log(JournalAction.skip, 'تم بلوغ الحد الأقصى للمراكز المفتوحة (${s.maxOpenPositions})', symbol: sym);
          break;
        }
        final report = reports[sym];
        if (report == null) continue;
        if (exitedUnderlyings.contains(sym)) {
          _log(JournalAction.skip, 'تم إرسال أمر خروج في هذه الدورة — لا دخول جديد قبل تأكيد الإغلاق', symbol: sym);
          continue;
        }
        final active = DirectionLock.activeRight(sym, positions, openOrders);
        if (active != null) continue; // managed by the exit logic above
        try {
          final intent = rules.evaluateEntry(sym, report,
              rejection: (r) => _log(JournalAction.skip, r, symbol: sym, details: {'score': report.score}));
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
    await _submit(
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
    return true;
  }

  Future<void> _submit(
    OrderRequest r, {
    required String purpose,
    required String reason,
    required JournalAction journalAction,
    double? invalidation,
    double? target,
    double score = 0,
    Map<String, Object?> details = const {},
  }) async {
    final o = await broker.placeOrder(r);
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
      ));
      if (meta != null && t.purpose == ExitKind.partialProfit.name) meta.partialTaken = true;
    }
    _log(JournalAction.orderFilled,
        'تنفيذ ${o.side == OrderSide.buyToOpen ? 'شراء' : 'بيع'} $delta عقد ${t.occSymbol} بسعر ${formatUsd(price)}',
        symbol: o.contract.underlying, details: {'orderId': o.id, 'filled': o.filledQuantity, 'of': o.quantity});
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
    final key = '${now.year}-${now.month}-${now.day}';
    if (state.dayKey != key) {
      state.dayKey = key;
      state.dayStartEquityCents = a.equityCents;
    }
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
