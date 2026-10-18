import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

final _now = DateTime.utc(2026, 6, 1, 15);
OptionContract _c(String u, OptionRight r, {int strike = 10000}) =>
    OptionContract(underlying: u, right: r, expiry: DateTime.utc(2026, 6, 19), strikeCents: strike);

BrokerOrder _order(OptionContract c, OrderSide side, {OrderStatus st = OrderStatus.pending}) => BrokerOrder(
      id: 'o1',
      clientOrderId: 'c1',
      contract: c,
      side: side,
      quantity: 1,
      filledQuantity: 0,
      limitPriceCents: 100,
      status: st,
      createdAt: _now,
    );

void main() {
  group('opposite-direction lock', () {
    test('blocks a Put while a Call is held on the same symbol', () {
      final r = DirectionLock.canOpen(
        symbol: 'AAPL',
        right: OptionRight.put,
        positions: [Position(contract: _c('AAPL', OptionRight.call), quantity: 1, averageCostCents: 100, openedAt: _now)],
        openOrders: const [],
      );
      expect(r.allowed, isFalse);
    });

    test('blocks while an opposite order is still working (even unfilled)', () {
      final r = DirectionLock.canOpen(
        symbol: 'AAPL',
        right: OptionRight.call,
        positions: const [],
        openOrders: [_order(_c('AAPL', OptionRight.put), OrderSide.buyToOpen)],
      );
      expect(r.allowed, isFalse);
    });

    test('blocks while a partially filled opposite close is unfinished', () {
      final r = DirectionLock.canOpen(
        symbol: 'AAPL',
        right: OptionRight.call,
        positions: [Position(contract: _c('AAPL', OptionRight.put), quantity: 1, averageCostCents: 100, openedAt: _now)],
        openOrders: [_order(_c('AAPL', OptionRight.put), OrderSide.sellToClose, st: OrderStatus.partiallyFilled)],
      );
      expect(r.allowed, isFalse);
    });

    test('other symbols and finished orders do not lock', () {
      final r = DirectionLock.canOpen(
        symbol: 'AAPL',
        right: OptionRight.call,
        positions: [Position(contract: _c('MSFT', OptionRight.put), quantity: 3, averageCostCents: 100, openedAt: _now)],
        openOrders: [_order(_c('AAPL', OptionRight.put), OrderSide.buyToOpen, st: OrderStatus.cancelled)],
      );
      expect(r.allowed, isTrue);
    });
  });

  group('sizing', () {
    test('risk per trade limits size', () {
      // equity $10,000, risk 1% = $100; premium $2.00 * 100 * 35% stop = $70 at risk/contract -> 1
      final r = sizePosition(
          s: const AccountSettings(), equityCents: 1000000, buyingPowerCents: 1000000, openExposureCents: 0, premiumCents: 200);
      expect(r.quantity, 1);
    });

    test('exposure cap and cash produce zero size', () {
      final r = sizePosition(
          s: const AccountSettings(), equityCents: 1000000, buyingPowerCents: 1000, openExposureCents: 0, premiumCents: 200);
      expect(r.quantity, 0);
      final r2 = sizePosition(
          s: const AccountSettings(), equityCents: 1000000, buyingPowerCents: 1000000, openExposureCents: 400000, premiumCents: 200);
      expect(r2.quantity, 0);
    });
  });

  group('exit rules', () {
    final rules = DecisionEngine(const AccountSettings());
    Position pos(int qty) => Position(contract: _c('AAPL', OptionRight.call), quantity: qty, averageCostCents: 200, openedAt: _now);
    PositionMeta meta() => PositionMeta(
        occSymbol: 'x', entryTime: _now, entryPremiumCents: 200, initialQuantity: 2, entryScore: 50, entryReasonAr: '', underlyingInvalidation: 95);

    test('stop loss at -35%', () {
      final e = rules.evaluateExit(position: pos(2), meta: meta(), markCents: 129, underlyingPrice: 100, report: null, now: _now);
      expect(e!.kind, ExitKind.stopLoss);
      expect(e.urgent, isTrue);
    });

    test('underlying invalidation exits a call', () {
      final e = rules.evaluateExit(position: pos(2), meta: meta(), markCents: 190, underlyingPrice: 94, report: null, now: _now);
      expect(e!.kind, ExitKind.invalidation);
    });

    test('partial profit sells half once, then trailing stop protects the rest', () {
      final m = meta();
      final partial = rules.evaluateExit(position: pos(2), meta: m, markCents: 290, underlyingPrice: 100, report: null, now: _now);
      expect(partial!.kind, ExitKind.partialProfit);
      expect(partial.quantity, 1);
      m.partialTaken = true;
      // Peak 290 (+45%), drop to 230 (-20.7% from peak) -> trailing stop
      final trail = rules.evaluateExit(position: pos(1), meta: m, markCents: 230, underlyingPrice: 100, report: null, now: _now);
      expect(trail!.kind, ExitKind.trailingStop);
    });

    test('closes near expiry', () {
      final e = rules.evaluateExit(
          position: pos(1), meta: meta(), markCents: 210, underlyingPrice: 100, report: null, now: DateTime.utc(2026, 6, 18));
      expect(e!.kind, ExitKind.expiry);
    });
  });

  group('settings', () {
    test('defaults are valid and JSON round-trips', () {
      const s = AccountSettings();
      expect(s.validate(), isEmpty);
      final back = AccountSettings.fromJson(s.toJson().cast<String, dynamic>());
      expect(back.toJson(), s.toJson());
    });

    test('invalid combination is reported', () {
      final s = const AccountSettings().copyWith(allowCalls: false, allowPuts: false, stopLossPercent: 99);
      expect(s.validate().length, greaterThanOrEqualTo(2));
    });
  });

  group('live guard', () {
    test('paper always passes; live is locked in this build', () {
      LiveTradingGuard.ensureAllowed(mode: TradingMode.paper, accountId: 'a');
      expect(
        () => LiveTradingGuard.ensureAllowed(
          mode: TradingMode.live,
          accountId: 'a',
          approval: LiveApproval(accountId: 'a', approvedAt: _now, acknowledgement: LiveApproval.requiredAcknowledgement),
        ),
        throwsA(isA<BrokerException>().having((e) => e.code, 'code', BrokerErrorCode.liveLocked)),
      );
    });

    test('registry refuses a live simulator', () {
      final market = SyntheticMarket(clock: () => _now);
      expect(
        () => BrokerRegistry.standard().create(
            BrokerKind.simulator,
            AdapterContext(
                accountId: 'a', mode: TradingMode.live, credentials: const BrokerCredentials({}), market: market, clock: () => _now)),
        throwsA(isA<BrokerException>()),
      );
    });
  });

  group('symbols', () {
    test('OCC symbol round trip', () {
      final c = OptionContract(underlying: 'AAPL', right: OptionRight.call, expiry: DateTime.utc(2026, 11, 20), strikeCents: 15000);
      expect(c.occSymbol, 'AAPL261120C00150000');
      expect(OptionContract.fromOcc(c.occSymbol), c);
      final half = OptionContract(underlying: 'SPY', right: OptionRight.put, expiry: DateTime.utc(2026, 11, 20), strikeCents: 45250);
      expect(half.occSymbol, 'SPY261120P00452500');
    });

    test('TradeStation symbol round trip', () {
      final c = OptionContract(underlying: 'SPY', right: OptionRight.put, expiry: DateTime.utc(2026, 11, 20), strikeCents: 45250);
      expect(TradeStationAdapter.tsSymbol(c), 'SPY 261120P452.5');
      expect(TradeStationAdapter.fromTsSymbol('SPY 261120P452.5'), c);
      expect(TradeStationAdapter.tsSymbol(_c('AAPL', OptionRight.call, strike: 15000)), 'AAPL 260619C150');
    });
  });

  group('performance', () {
    test('drawdown and win rate', () {
      final trades = [
        TradeRecord(
            occSymbol: 'a', underlying: 'A', right: OptionRight.call, entryTime: _now, exitTime: _now, quantity: 1,
            entryPremiumCents: 100, exitPremiumCents: 150, feesCents: 0, exitKind: 'takeProfit', entryReasonAr: '', exitReasonAr: ''),
        TradeRecord(
            occSymbol: 'b', underlying: 'B', right: OptionRight.put, entryTime: _now, exitTime: _now, quantity: 1,
            entryPremiumCents: 100, exitPremiumCents: 80, feesCents: 0, exitKind: 'stopLoss', entryReasonAr: '', exitReasonAr: ''),
      ];
      final curve = [EquityPoint(_now, 1000), EquityPoint(_now, 1200), EquityPoint(_now, 900), EquityPoint(_now, 1100)];
      final r = PerformanceReport.compute(trades, curve);
      expect(r.realizedPnlCents, 3000);
      expect(r.winRatePercent, 50);
      expect(r.maxDrawdownCents, 300);
      expect(r.maxDrawdownPercent, closeTo(25, 1e-9));
      expect(formatUsd(-123456), r'-$1,234.56');
    });
  });
}
