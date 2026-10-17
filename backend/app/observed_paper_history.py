"""Causal, event-sampled net valuation; no interpolated or future market data.

The caller verifies the immutable ledger in the same transaction. Replay is
streamed from genesis, retaining live state and at most one accepted original
quote per owned contract. Pages bind to an immutable end event, so appends cannot
silently change the result. This is not a daily return series or a Sharpe model.
"""
import json

from .observed_paper import apply, digest
from .observed_paper_valuation import summarize
from .paper_settlement import stamp

VERSION = 'observed-paper-history-v1'


def history(rows, *, after, limit, through):
    points = []; saved = {}; state = None; peak = None; drawdown = 0
    complete = True; missing = 0; samples = 0
    for row in rows:
        sequence = row['sequence']
        if sequence > through or len(points) == limit:
            break
        original = json.loads(row['payload']); command = original['command']
        state = command['state'] if sequence == 0 else apply(state, command, original['at'])[0]
        wanted = {}
        for p in state['positions'].values():
            authority = {'at': p['markAt'], 'identity': p['markIdentity']}
            consumed = state['consumption'].get(p['contract'])
            if consumed and stamp(consumed['at']) > stamp(authority['at']):
                authority = consumed
            wanted[p['contract']] = authority
        saved = {key: value for key, value in saved.items() if key in wanted}
        if command['kind'] == 'CYCLE':
            obs = command['observation']
            for q in obs['quotes']:
                if not isinstance(q, dict) or not isinstance(q.get('contract'), str):
                    continue
                authority = wanted.get(q['contract'])
                if authority and q.get('at') == authority['at'] and digest(q) == authority['identity']:
                    # Only discard unrelated bars/quotes in this read projection;
                    # the complete original event remains unchanged in SQL.
                    saved[q['contract']] = {'payload': json.dumps({'at': original['at'],
                        'command': {'kind': 'CYCLE', 'observation': {'source': obs['source'],
                            'capturedAt': obs['capturedAt'], 'quotes': [q]}}})}
        quote_rows = sorted(saved.values(), key=lambda r: stamp(json.loads(r['payload'])['at']), reverse=True)
        value = summarize(iter(quote_rows), state, stamp(original['at']))
        equity = value['liquidationEquityCents']; samples += 1
        if equity is None:
            missing += 1; complete = False
        elif complete:
            peak = max(peak if peak is not None else equity, equity)
            drawdown = max(drawdown, peak-equity)
        if sequence > after:
            points.append({'version': sequence, 'eventHash': row['digest'], 'asOf': original['at'],
                'status': value['status'], 'complete': value['complete'],
                'cashCents': state['cash'], 'feesCents': state['fees'],
                'realizedPnlCents': state['realized'], 'ownedBasisCents': value['ownedBasisCents'],
                'liquidationEquityCents': equity, 'totalPnlCents': value['totalPnlCents'],
                'unrealizedPnlCents': value['unrealizedPnlCents'],
                'incompleteReasons': sorted({leg['status'] for leg in value['options'] + value['deliveries']
                    if leg['valueCents'] is None}),
                'prefix': {'eventSamples': samples, 'incompleteSamples': missing,
                    'complete': complete, 'maximumSampledDrawdownCents': drawdown if complete else None}})
    return points
