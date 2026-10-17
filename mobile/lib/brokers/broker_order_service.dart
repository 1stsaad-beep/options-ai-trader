/// Review -> explicit confirm -> journaled send for broker Paper option orders.
///
/// `review` fetches fresh balances/positions and a quote and runs admission.
/// `submit` (called only after the user confirms) fetches everything again,
/// re-runs admission, persists the INTENT, sends once, and records the outcome.
library;

import 'dart:math';

import 'package:http/http.dart' as http;

import '../direct_alpaca.dart' show OptionQuote;
import 'alpaca_paper.dart';
import 'broker_adapter.dart';
import 'broker_models.dart';
import 'broker_options.dart';
import 'broker_order_admission.dart';
import 'broker_order_journal.dart';
import 'broker_portfolio.dart';
import 'broker_reconcile.dart';
import 'broker_store.dart';
import 'option_eligibility.dart';

typedef DirectQuoteSource = Future<OptionQuote?> Function(String contract);
typedef ContractTermsSource = Future<Map<String, dynamic>?> Function(BrokerAccount account, OccContract contract);
typedef UnderlyingQuoteSource = Future<UnderlyingQuote?> Function(String symbol);

class BrokerOrderReview {
  final BrokerAccount account;
  final BrokerOrderTicket ticket;
  final BrokerPortfolio portfolio;
  final BrokerQuote? quote;
  final BrokerAdmission admission;
  final DateTime reviewedAt;
  final OptionEligibility? eligibility; // entries only
  const BrokerOrderReview(this.account, this.ticket, this.portfolio, this.quote, this.admission, this.reviewedAt,
      [this.eligibility]);
}

class BrokerOrderOutcome {
  final String clientOrderId, state;
  final String? brokerOrderId, code, message;
  const BrokerOrderOutcome(this.clientOrderId, this.state, {this.brokerOrderId, this.code, this.message});
}

class BrokerOrderService {
  static const reviewValidity = Duration(seconds: 60);
  final BrokerAccountRegistry registry;
  final http.Client? client;
  final DirectQuoteSource? directQuote;
  final BrokerRiskPolicy policy;
  final DateTime Function() now;
  final Random _random;
  final ContractTermsSource? termsSource;
  final UnderlyingQuoteSource? underlyingQuote;
  final EligibilityPolicy eligibilityPolicy;
  /// B9: entries must pass on-phone option eligibility. Only tests of unrelated paths turn this off.
  final bool requireEligibility;
  BrokerOrderService(this.registry, {this.client, this.directQuote, this.policy = const BrokerRiskPolicy(),
      DateTime Function()? clock, Random? random, this.termsSource, this.underlyingQuote,
      this.eligibilityPolicy = const EligibilityPolicy(), this.requireEligibility = true})
      : now = clock ?? DateTime.now, _random = random ?? Random.secure();

  /// Contract terms from an Alpaca Paper account (this one if Alpaca, else the first
  /// registered active Alpaca account). Read-only metadata; null when none is available.
  Future<Map<String, dynamic>?> _defaultTerms(BrokerAccount a, OccContract c) async {
    final alpaca = a.broker == BrokerKind.alpaca ? a
        : (await registry.list()).where((x) => x.broker == BrokerKind.alpaca && !x.archived).firstOrNull;
    if (alpaca == null) return null;
    try {
      final adapter = createPaperAdapter(alpaca, await registry.credentials(alpaca.id), client: client, clock: now);
      return await (adapter as AlpacaPaperAdapter).contractTerms(c);
    } on BrokerException {
      return null;
    }
  }

  /// Eligibility for an entry ticket given an already-fetched quote (also used by tests).
  Future<OptionEligibility> eligibilityFor(BrokerAccount a, BrokerOrderTicket t, BrokerQuote? quote) =>
      _eligibility(a, t, quote);

  Future<OptionEligibility> _eligibility(BrokerAccount a, BrokerOrderTicket t, BrokerQuote? quote) async {
    final c = OccContract.parse(t.contract)!;
    Map<String, dynamic>? terms;
    UnderlyingQuote? u;
    try {
      terms = await (termsSource ?? _defaultTerms)(a, c);
    } catch (_) {
      terms = null;
    }
    try {
      u = underlyingQuote == null ? null : await underlyingQuote!(c.root);
    } catch (_) {
      u = null;
    }
    return evaluateEligibility(contract: c, terms: terms, quote: quote, underlying: u, now: now(), policy: eligibilityPolicy);
  }

  BrokerOrderJournal journal(BrokerAccount a) => BrokerOrderJournal(registry.storage, a.id, clock: now);

  Future<BrokerAdapter> _adapter(BrokerAccount a) async => createPaperAdapter(a, await registry.credentials(a.id),
      client: client, clock: now, onRefreshTokenRotated: (t) => registry.updateSecret(a.id, 'refreshToken', t));

  Future<BrokerQuote?> _quote(BrokerAdapter adapter, BrokerAccount a, BrokerOrderTicket t) async {
    final c = OccContract.parse(t.contract);
    if (c == null) return null;
    if (a.broker == BrokerKind.alpaca) {
      final q = directQuote == null ? null : await directQuote!(c.occ);
      return q == null ? null : BrokerQuote.fromDirect(q);
    }
    return adapter.optionQuote(c, conid: t.ibkrConid);
  }

  Future<(BrokerAdapter, BrokerOrderReview)> _evaluate(BrokerAccount a, BrokerOrderTicket t) async {
    final adapter = await _adapter(a);
    final portfolio = await loadPortfolio(a, adapter, clock: now);
    final quote = await _quote(adapter, a, t);
    final orders = await journal(a).orders();
    final at = now();
    var admission = admitBrokerOrder(t, portfolio, quote, orders, at, policy: policy);
    OptionEligibility? eligibility;
    if (requireEligibility && t.side == TicketSide.buyToOpen && admission.admitted) {
      eligibility = await _eligibility(a, t, quote);
      admission = eligibility.eligible
          ? BrokerAdmission(null, admission.costCents, admission.feeCents, [...admission.passed, 'OPTION_ELIGIBILITY'])
          : BrokerAdmission('OPTION_NOT_ELIGIBLE', 0, 0, admission.passed);
    }
    return (adapter, BrokerOrderReview(a, t, portfolio, quote, admission, at, eligibility));
  }

  /// Read-only broker queries; appends STATUS/FILL/RESOLVED events only.
  Future<ReconcileResult> reconcile(BrokerAccount a) async {
    final adapter = await _adapter(a);
    final portfolio = await loadPortfolio(a, adapter, clock: now);
    return BrokerReconciler(journal(a), clock: now).run(a, adapter, positions: portfolio.positions);
  }

  Future<void> resolveManually(BrokerAccount a, String clientOrderId, String note) =>
      BrokerReconciler(journal(a), clock: now).resolveManually(clientOrderId, note: note);

  Future<BrokerOrderReview> review(BrokerAccount a, BrokerOrderTicket t) async => (await _evaluate(a, t)).$2;

  String _clientId() {
    const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
    return 'oat-${List.generate(20, (_) => alphabet[_random.nextInt(alphabet.length)]).join()}';
  }

  static const _definitiveRejects = {'HTTP_400', 'HTTP_401', 'HTTP_403', 'HTTP_404', 'HTTP_422', 'HTTP_429',
      'ORDER_REJECTED', 'INVALID_ORDER'};
  static const _notSent = {'TLS_ERROR', 'HOST_NOT_ALLOWED'};

  /// Only call after the user explicitly confirmed [reviewed].
  Future<BrokerOrderOutcome> submit(BrokerOrderReview reviewed) async {
    if (!reviewed.admission.admitted) throw const BrokerException('NOT_ADMITTED');
    if (now().difference(reviewed.reviewedAt) > reviewValidity) throw const BrokerException('REVIEW_EXPIRED');
    final (adapter, fresh) = await _evaluate(reviewed.account, reviewed.ticket);
    if (!fresh.admission.admitted) throw BrokerException(fresh.admission.reason!);
    final t = fresh.ticket, c = OccContract.parse(t.contract)!, a = fresh.account;
    final id = _clientId();
    final j = journal(a);
    final request = PaperOrderRequest(symbol: c.symbolFor(a.broker), assetClass: AssetClass.option,
        side: t.side == TicketSide.buyToOpen ? OrderSide.buy : OrderSide.sell, quantity: t.quantity,
        limitPrice: centsText(t.limitCents), clientOrderId: id, ibkrConid: t.ibkrConid);
    await j.append(id, 'INTENT', {
      'state': OrderState.intent, 'broker': a.broker.name, 'contract': c.occ, 'brokerSymbol': request.symbol,
      'side': t.sideCode, 'quantity': t.quantity, 'limitCents': t.limitCents, 'costCents': fresh.admission.costCents,
      'feeCents': fresh.admission.feeCents, 'ibkrConid': t.ibkrConid, 'quote': fresh.quote!.toJson(),
      'checks': fresh.admission.passed, 'policy': policy.toJson(),
      if (fresh.eligibility != null) 'eligibility': fresh.eligibility!.toJson(), 'confirmedByUser': true, 'environment': 'paper',
    });
    BrokerOrderAck ack;
    try {
      ack = await adapter.submitPaperOrder(request);
    } on BrokerException catch (e) {
      final state = _definitiveRejects.contains(e.code) ? OrderState.rejected
          : _notSent.contains(e.code) ? OrderState.notPlaced : OrderState.unknown;
      await j.append(id, 'SEND_RESULT', {'state': state, 'code': e.code});
      return BrokerOrderOutcome(id, state, code: e.code);
    } catch (_) {
      await j.append(id, 'SEND_RESULT', {'state': OrderState.unknown, 'code': 'UNEXPECTED'});
      return BrokerOrderOutcome(id, OrderState.unknown, code: 'UNEXPECTED');
    }
    if (ack.status == 'NEEDS_CONFIRMATION') {
      await j.append(id, 'SEND_RESULT', {'state': OrderState.confirmationRequired, 'replyId': ack.orderId,
          'message': ack.message});
      return BrokerOrderOutcome(id, OrderState.confirmationRequired, message: ack.message);
    }
    await j.append(id, 'ACK', {'state': OrderState.open, 'brokerOrderId': ack.orderId, 'brokerStatus': ack.status,
        if (ack.message != null) 'message': ack.message});
    return BrokerOrderOutcome(id, OrderState.open, brokerOrderId: ack.orderId);
  }
}
