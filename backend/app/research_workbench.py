"""Account-scoped, synthetic SHADOW workbench with durable decision evidence.

This orchestrates existing pure research engines. It never submits, fills,
reconciles or enables an account, and accepts no client-supplied signals or text.
Snapshot writes append only to the existing immutable decision/audit store.
"""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import cos, sin, tanh

from .analysis_service import analysis_fixture
from .engines import aware
from .research import (
    AutonomousSafetySupervisor, ContractQualityPolicy, CounterfactualReplay,
    DecisionMemory, EntrySetup, EntryTimingOptimizer, LiquidityTrapDetector,
    MomentumCandidate, OptionContract, OptionTwin, PortfolioCorrelationGuard,
    ResearchPoint, SafetyState, ShadowScenarioBattle, StrategyTournament,
    assess_contract,
)
from .service import Rejected


EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
QUALITY = ContractQualityPolicy(max_age_seconds=120)
REPLAY_HOLDING_OBSERVATIONS = 1
FIXED_RESEARCH_EXPIRY = datetime(2027, 12, 31, 20, tzinfo=timezone.utc)
QUOTE_MODEL_VERSION = 'synthetic-option-fixture-v1'


def _spot(symbol, stamp):
    index = int((stamp - EPOCH).total_seconds() / 60)
    base = {'NVDA': 100, 'AAPL': 200, 'TSLA': 250}.get(symbol, 150)
    return base + 3 * sin(index / 5) + 7 * sin(index / 20)


def fixture_quote(symbol, right, strike, stamp):
    """A fixed contract's quote at stamp depends only on stamp and identity.

    This artificial quote process is deliberately not fitted to observations
    or described as a real options pricing model.
    """
    aware(stamp)
    index = int((stamp - EPOCH).total_seconds() / 60)
    intrinsic = max(0, (_spot(symbol, stamp) - strike) * (1 if right == 'CALL' else -1))
    mid = 3 + .5 * intrinsic + .2 * sin(index / 11) + .1 * cos(index / 23)
    return ResearchPoint(stamp, mid - .02, mid + .02)


def fixture_quotes(contract, end, count=150):
    if type(count) is not int or not 2 <= count <= 10000:
        raise ValueError('Bounded synthetic quote history required')
    aware(end)
    return tuple(fixture_quote(contract.symbol, contract.right, contract.strike,
                               end - timedelta(minutes=count - index - 1))
                 for index in range(count))


def _contract(symbol, right, now):
    observed = now.replace(second=0, microsecond=0)
    spot = _spot(symbol, observed)
    strike = float(round(spot))
    expiry = observed.replace(hour=20, minute=0) + timedelta(days=30)
    quote = fixture_quote(symbol, right, strike, observed)
    identifier = f'SYNTHETIC:{symbol}:{right}:{strike:.2f}:{expiry.isoformat()}'
    return OptionContract(identifier, symbol, right, strike, expiry, observed, spot,
                          quote.bid, quote.ask, .5 if right == 'CALL' else -.5,
                          .04, -.04, .12, .3, 500, 1000)


def _json_contract(contract):
    return {**asdict(contract), 'expiry': contract.expiry.isoformat(),
            'observed_at': contract.observed_at.isoformat()}


def _tournament(symbol, now):
    """Five-minute prefixes of a declared UTC synthetic session, fixed contract.

    Strike, right and expiry are defined at EPOCH, before every training fold;
    they are never selected from the final spot or winning backtest result.
    A new UTC day is a new named session, not a rewrite of a saved session.
    """
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0)
    strike = float({'NVDA': 100, 'AAPL': 200, 'TSLA': 250}.get(symbol, 150))
    definition = {'contract_id': f'SYNTHETIC-FIXED:{symbol}:CALL:{strike:.2f}:2027-12-31',
                  'symbol': symbol, 'right': 'CALL', 'strike': strike,
                  'known_at': EPOCH.isoformat(), 'expiry': FIXED_RESEARCH_EXPIRY.isoformat()}
    metadata = {'mode': 'SHADOW', 'source': 'synthetic_fixture',
                'session_id': f'SYNTHETIC-UTC:{start.date().isoformat()}',
                'observation_interval_minutes': 5, 'fixed_contract': definition,
                'contract_id': definition['contract_id'],
                'contract_selection_uses_end_of_sample_data': False,
                'real_contract_chain_selection_tested': False,
                'execution_authority': False, 'profitability_evidence': False}
    if start < EPOCH or end >= FIXED_RESEARCH_EXPIRY:
        return {**metadata, 'status': 'OUTSIDE_FIXED_FIXTURE_CONTRACT_LIFETIME',
                'folds': [], 'out_of_sample_pnl': None}
    count = int((end - start).total_seconds() // 300) + 1
    if count < 54:
        return {**metadata, 'status': 'INSUFFICIENT_SESSION_HISTORY', 'observations': count,
                'required_observations': 54, 'folds': [], 'out_of_sample_pnl': None}
    quotes = tuple(fixture_quote(symbol, 'CALL', strike, start + timedelta(minutes=5 * index))
                   for index in range(count))
    result = StrategyTournament().walk_forward(
        quotes, [MomentumCandidate('momentum_3', 3, .002), MomentumCandidate('momentum_8', 8, .004)],
        train_size=40, test_size=12, purge=2, commission=.65, slippage=.01)
    return {**result, **metadata, 'status': 'EVALUATED', 'observations': count}


def _context(service, db, account_id, symbol):
    account = service.account(db, account_id)
    watch = db.one('SELECT * FROM watchlist WHERE account_id=? AND symbol=?', (account_id, symbol))
    if not watch or not watch['verified'] or not watch['enabled']:
        raise Rejected('Research requires an enabled, qualified synthetic watch symbol')
    positions = db.all('SELECT * FROM positions WHERE account_id=?', (account_id,))
    pending = db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",
                     (account_id,))
    exposures = {}
    for position in positions:
        exposures[position['symbol']] = exposures.get(position['symbol'], 0.) + position['cost'] / 100
    for order in pending:
        exposures[order['symbol']] = exposures.get(order['symbol'], 0.) + service._pending_cost(db, order) / 100
    if len(exposures) > 100:
        raise Rejected('Research exposure projection exceeds its bounded calculation budget')
    reconciled = bool(account['state_known'])
    try:
        service._validate_ledger(db, account_id)
    except Rejected:
        reconciled = False
    return {'account': account, 'exposures': exposures,
            'account_known': bool(account['state_known']),
            'balances_fresh': service.snapshot_valid(account),
            'orders_reconciled': reconciled,
            'market_fresh': service.market_valid(db, account_id, symbol),
            'emergency_stop': bool(account['stopped']) or bool(db.one('SELECT stopped FROM supervisor WHERE id=1')['stopped']),
            'owned_close_quantity_known': reconciled and bool(positions)}


def _project(context, symbol, now):
    aware(now)
    bars = tuple(analysis_fixture(symbol, now))
    prior = bars[-21:-1]
    span = max(b.high for b in prior) - min(b.low for b in prior)
    move = (prior[-1].close - prior[0].close) / max(span, .01)
    signed_score = tanh(move)
    scores = {'bullish': .5 + .25 * signed_score,
              'bearish': .5 - .25 * signed_score, 'neutral': .5 - .2 * abs(signed_score)}
    battle = ShadowScenarioBattle().compare([
        {'id': f'{symbol}:{direction}:{prior[-1].timestamp.isoformat()}',
         'direction': direction, 'score': score, 'known_at': prior[-1].timestamp,
         'invalidated': False} for direction, score in scores.items()], now)
    battle['score_definition'] = '20-bar signed movement / high-low range, bounded by tanh; not a calibrated probability'
    preferred = next((s for s in battle['ranked'] if s['id'] == battle['preferred_id']), None)
    # A neutral/conflicted comparison still needs a displayed contract. It is not a recommendation.
    right = 'PUT' if preferred and preferred['direction'] == 'bearish' else 'CALL'
    contract = _contract(symbol, right, now)
    activation = max(b.high for b in prior) if right == 'CALL' else min(b.low for b in prior)
    invalidation = min(b.low for b in prior) if right == 'CALL' else max(b.high for b in prior)
    scenario_id = preferred['id'] if preferred else f'{symbol}:NO_PREFERRED_SCENARIO'
    setup = EntrySetup(right, activation, invalidation, prior[-1].timestamp,
                       prior[-1].timestamp + timedelta(minutes=15), scenario_id)
    strength = max(scores['bullish'], scores['bearish'])
    timing = EntryTimingOptimizer().compare(setup, bars, now, 'balanced', strength)
    timing['directional_conflict'] = battle['directional_conflict']
    timing['candidate_must_not_override_conflict'] = True
    twin = OptionTwin().simulate(contract, now, [
        {'spot': contract.spot * .95, 'elapsed_days': 1, 'iv': .35},
        {'spot': contract.spot, 'elapsed_days': 7, 'iv': .3},
        {'spot': contract.spot * 1.05, 'elapsed_days': 1, 'iv': .25}], policy=QUALITY)
    histories = {name: tuple(ResearchPoint(b.timestamp, b.close, b.close)
                             for b in analysis_fixture(name, now)) for name in context['exposures']}
    account = context['account']
    budget = max(0, account['equity'] + account['realized']) * account['config']['allocation_pct'] / 10000
    correlation = PortfolioCorrelationGuard().assess(histories, context['exposures'], now, pair_limit=budget)
    correlation.update({'exposure_basis': 'owned_and_pending_premium_proxy',
                        'exposures': context['exposures'], 'pair_limit_dollars': budget,
                        'actual_delta_or_portfolio_var': False,
                        'scope': 'selected_account_only', 'data_source': 'synthetic_fixture'})
    tournament = _tournament(symbol, now)
    state = SafetyState(**{name: context[name] for name in (
        'account_known', 'balances_fresh', 'orders_reconciled', 'market_fresh',
        'emergency_stop', 'owned_close_quantity_known')}, live_locked=True,
        contract_qualified=assess_contract(contract, now, QUALITY)['accepted_for_research'])
    safety = AutonomousSafetySupervisor().assess(state, {
        'account_snapshot': float(context['balances_fresh']),
        'market_observation': float(context['market_fresh']),
        'order_reconciliation': float(context['orders_reconciled'])})
    safety['qualification_scope'] = 'synthetic_contract_only_not_broker_verified'
    modules = {'scenario_battle': battle, 'entry_timing': timing, 'option_twin': twin,
               'liquidity_trap': LiquidityTrapDetector().assess(bars, now),
               'correlation_guard': correlation, 'strategy_tournament': tournament,
               'safety_supervisor': safety}
    reasons = ['SYNTHETIC_SHADOW_ONLY', 'RANGE_SCORED_SCENARIO_COMPARISON',
               'DIRECTIONAL_CONFLICT' if battle['directional_conflict'] else 'DIRECTIONAL_COMPARISON_AVAILABLE']
    reasons.extend('SAFETY_GATE_' + failure for failure in safety['hard_failures'])
    evidence = {'source': 'synthetic_fixture', 'symbol': symbol, 'right': right,
                'observed_at': contract.observed_at.isoformat(), 'scenario_scores': scores,
                'activation': activation, 'invalidation': invalidation,
                'entry_reasons': [method['reason'] for method in timing['methods']],
                'hard_failures': safety['hard_failures'], 'execution_authority': False,
                'holding_observations': REPLAY_HOLDING_OBSERVATIONS}
    decision_id = sha256(json.dumps({'account_id': account['id'], 'as_of': now.isoformat(),
                                    **evidence}, sort_keys=True).encode()).hexdigest()
    memory = DecisionMemory()
    memory.record(account['id'], decision_id, now, contract.observed_at,
                  contract.contract_id, reasons, evidence)
    decision = memory.to_state()['records'][0]
    return {'schema_version': 1, 'mode': 'SHADOW', 'source': 'synthetic_fixture',
            'quote_model_version': QUOTE_MODEL_VERSION,
            'account_id': account['id'], 'symbol': symbol, 'as_of': now.isoformat(),
            'observed_at': contract.observed_at.isoformat(), 'contract': _json_contract(contract),
            'modules': modules, 'decision': decision, 'execution_authority': False,
            'external_connections': False, 'profitability_evidence': False,
            'limitations': ['Synthetic quotes and scores do not establish profitability or broker qualification.',
                            'Every module is read-only research; execution must independently recheck all mandatory risk gates.',
                            'Correlation uses owned cost plus pending buy commitments, not measured Greeks or a nonlinear portfolio model.',
                            'A displayed Call contract when scenarios conflict is illustrative, not an accepted entry.',
                            'Each saved snapshot is an independent immutable research journal; it is not a broker order.',
                            'Tournament uses a separately predefined fixed Call contract, five-minute synthetic UTC sessions, and no hindsight contract-chain selection.',
                            'No LLM, external network, account reconciliation or market observation refresh is performed.']}


def inspect_workbench(service, account_id, symbol):
    with service.repo.transaction() as db:
        return _project(_context(service, db, account_id, symbol), symbol, service.now())


def _envelope(account_id, symbol):
    return {'schema_version': 1, 'mode': 'SHADOW', 'source': 'synthetic_fixture',
            'account_id': account_id, 'symbol': symbol, 'execution_authority': False,
            'external_connections': False, 'profitability_evidence': False}


def _stored_workbench(row, account_id):
    if sha256(row['payload'].encode()).hexdigest() != row['digest']:
        raise ValueError('Snapshot digest mismatch')
    payload = json.loads(row['payload'])
    result = payload['workbench']
    expected = _envelope(account_id, payload['symbol'])
    if any(type(result.get(k)) is not type(v) or result.get(k) != v
           for k, v in expected.items()):
        raise ValueError('Research identity or safety contract mismatch')
    memory = DecisionMemory.from_state({'schema_version': 1, 'records': [result['decision']]})
    records = memory.observations(account_id)
    if len(records) != 1 or records[0].decided_at.isoformat() != result['as_of']:
        raise ValueError('Decision identity mismatch')
    return result, records[0]


def list_workbench_snapshots(service, account_id, symbol):
    """Bounded account journal scan, including snapshots of disabled watch symbols.

    Never silently claim complete history: at most 100 results / 1000 scanned
    records are returned. The response exposes truncation to the mobile client.
    """
    with service.repo.transaction() as db:
        service.account(db, account_id)
        rows = db.all("SELECT * FROM decision_snapshots WHERE account_id=? AND action='SHADOW_RESEARCH' "
                      'ORDER BY created DESC, id DESC LIMIT 1001', (account_id,))
    items = []
    truncated = len(rows) > 1000
    try:
        for row in rows[:1000]:
            result, decision = _stored_workbench(row, account_id)
            if result['symbol'] != symbol:
                continue
            if len(items) == 100:
                truncated = True
                break
            items.append({'snapshot_id': row['id'], 'account_id': account_id,
                          'symbol': symbol, 'as_of': result['as_of'],
                          'decision_id': decision.decision_id,
                          'decided_at': decision.decided_at.isoformat(), 'digest': row['digest']})
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise Rejected('Stored research evidence failed validation; refusing to reconstruct reasons') from exc
    return {**_envelope(account_id, symbol), 'items': items, 'truncated': truncated}


def snapshot_workbench(service, account_id, symbol):
    with service.repo.transaction() as db:
        result = _project(_context(service, db, account_id, symbol), symbol, service.now())
        identifier = service.decision(db, account_id, 'SHADOW_RESEARCH', {'symbol': symbol,
                                      'source': 'synthetic_fixture', 'workbench': result})
        service.audit(db, account_id, 'RESEARCH_SNAPSHOT', {'snapshot_id': identifier,
                      'symbol': symbol, 'execution_authority': False})
        return {**_envelope(account_id, symbol), 'snapshot_id': identifier, 'workbench': result}


def replay_workbench(service, account_id, symbol, snapshot_id):
    now = service.now()
    aware(now)
    now = now.astimezone(timezone.utc)
    with service.repo.transaction() as db:
        service.account(db, account_id)
        row = db.one("SELECT * FROM decision_snapshots WHERE account_id=? AND id=? AND action='SHADOW_RESEARCH'",
                     (account_id, snapshot_id))
        # Capture time as well as market time must have been available by replay.
        observations = db.all('SELECT * FROM research_observations WHERE account_id=? AND snapshot_id=? '
                              'AND captured_at<=? AND observed_at<=? ORDER BY observed_at LIMIT 2',
                              (account_id, snapshot_id, now.isoformat(), now.isoformat()))
    if not row:
        raise Rejected('Unknown account research snapshot')
    try:
        result, decision = _stored_workbench(row, account_id)
        if result['symbol'] != symbol:
            raise ValueError('Research identity mismatch')
        item = result['contract']
        contract = OptionContract(**{**item, 'expiry': datetime.fromisoformat(item['expiry']),
                                     'observed_at': datetime.fromisoformat(item['observed_at'])})
        if decision.contract_id != contract.contract_id:
            raise ValueError('Decision contract mismatch')
        evidence = json.loads(decision.evidence_json)
        if evidence['holding_observations'] != REPLAY_HOLDING_OBSERVATIONS:
            raise ValueError('Saved replay policy mismatch')
        quotes = tuple(_observation(row, result, snapshot_id, now) for row in observations)
        replay = CounterfactualReplay().replay(decision, quotes, now,
                    holding_observations=REPLAY_HOLDING_OBSERVATIONS,
                    commission=contract.commission_per_contract, slippage=contract.slippage_per_share,
                    contract_id=contract.contract_id)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise Rejected('Stored research evidence failed validation; refusing to reconstruct reasons') from exc
    return {**_envelope(account_id, symbol), 'snapshot_id': snapshot_id,
            'as_of': result['as_of'], 'original_workbench': result,
            'outcome_as_of': quotes[-1].timestamp.isoformat() if quotes else result['as_of'],
            'account_id': account_id, 'symbol': symbol, 'original_decision': result['decision'],
            'counterfactual': replay, 'execution_authority': False,
            'external_connections': False, 'profitability_evidence': False}


def _observation(row, workbench, snapshot_id, as_of):
    if sha256(row['payload'].encode()).hexdigest() != row['digest']:
        raise ValueError('Observation digest mismatch')
    value = json.loads(row['payload'])
    for key, expected in {**_envelope(workbench['account_id'], workbench['symbol']),
                          'snapshot_id': snapshot_id,
                          'contract_id': workbench['contract']['contract_id'],
                          'quote_model_version': workbench.get('quote_model_version')}.items():
        if type(value.get(key)) is not type(expected) or value.get(key) != expected:
            raise ValueError('Observation identity mismatch')
    if value['quote_model_version'] != QUOTE_MODEL_VERSION:
        raise ValueError('Unsupported captured quote model')
    observed = datetime.fromisoformat(row['observed_at'])
    captured = datetime.fromisoformat(row['captured_at'])
    decided = datetime.fromisoformat(workbench['decision']['decided_at'])
    if (value['observed_at'] != row['observed_at'] or value['captured_at'] != row['captured_at']
            or not decided < observed <= captured <= as_of
            or observed >= datetime.fromisoformat(workbench['contract']['expiry'])):
        raise ValueError('Observation time mismatch')
    return ResearchPoint(observed, value['bid'], value['ask'])


def capture_workbench_observation(service, account_id, symbol, snapshot_id):
    """Capture this minute's fixture quote prospectively; never fill missing past.

    Empty-body POST accepts no prices or timestamps. Duplicate requests in one
    minute return the same immutable observation without another audit event.
    """
    with service.repo.transaction() as db:
        service.account(db, account_id)
        row = db.one("SELECT * FROM decision_snapshots WHERE account_id=? AND id=? AND action='SHADOW_RESEARCH'",
                     (account_id, snapshot_id))
        if not row:
            raise Rejected('Unknown account research snapshot')
        try:
            result, decision = _stored_workbench(row, account_id)
            if result['symbol'] != symbol or result.get('quote_model_version') != QUOTE_MODEL_VERSION:
                raise ValueError('Snapshot source version or symbol does not support new observations')
            now = service.now()
            aware(now)
            now = now.astimezone(timezone.utc)
            if result['contract']['contract_id'] != decision.contract_id or result['contract']['symbol'] != symbol:
                raise ValueError('Saved contract identity mismatch')
            observed = now.replace(second=0, microsecond=0)
            if not decision.decided_at < observed < datetime.fromisoformat(result['contract']['expiry']):
                raise ValueError('A later unexpired synthetic minute is required')
            prior = db.one('SELECT * FROM research_observations WHERE account_id=? AND snapshot_id=? AND observed_at=?',
                           (account_id, snapshot_id, observed.isoformat()))
            if prior:
                _observation(prior, result, snapshot_id, now)
                return json.loads(prior['payload'])
            contract = result['contract']
            quote = fixture_quote(symbol, contract['right'], contract['strike'], observed)
            payload = {**_envelope(account_id, symbol), 'snapshot_id': snapshot_id,
                       'quote_model_version': QUOTE_MODEL_VERSION, 'contract_id': contract['contract_id'],
                       'observed_at': observed.isoformat(), 'captured_at': now.isoformat(),
                       'bid': quote.bid, 'ask': quote.ask}
            encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
            db.execute('INSERT INTO research_observations VALUES(?,?,?,?,?,?)',
                       (account_id, snapshot_id, observed.isoformat(), now.isoformat(), encoded,
                        sha256(encoded.encode()).hexdigest()))
            service.audit(db, account_id, 'RESEARCH_OBSERVATION', {'snapshot_id': snapshot_id,
                          'symbol': symbol, 'observed_at': observed.isoformat(), 'source': 'synthetic_fixture'})
            return payload
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise Rejected('Research observation rejected: ' + str(exc)) from exc
