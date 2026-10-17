"""Causal, event-sampled net valuation; no interpolated or future market data.

The verified replay passes each original and its rebuilt state to this bounded
projection in the same transaction. No second ledger replay or SQL scan is
needed. Retains at most one accepted original quote per owned contract.
Pages bind to an immutable end event, so appends cannot
silently change the result. This is not a daily return series or a Sharpe model.
"""
import json

from .observed_paper import digest
from .observed_paper_valuation import summarize
from .paper_settlement import stamp

VERSION = 'observed-paper-history-v1'


class HistoryProjection:
    """Consumes validated transitions; publication waits for full ledger checks."""
    def __init__(self, *, after, limit, through):
        self.after=after; self.limit=limit; self.through=through
        self.points=[]; self.saved={}; self.peak=None; self.drawdown=0
        self.complete=True; self.missing=0; self.samples=0

    def observe(self, row, original, state):
        sequence=row['sequence']
        if (self.through is not None and sequence>self.through) or len(self.points)==self.limit:
            return
        command=original['command']
        wanted = {}
        for p in state['positions'].values():
            authority = {'at': p['markAt'], 'identity': p['markIdentity']}
            consumed = state['consumption'].get(p['contract'])
            if consumed and stamp(consumed['at']) > stamp(authority['at']):
                authority = consumed
            wanted[p['contract']] = authority
        self.saved = {key: value for key, value in self.saved.items() if key in wanted}
        if command['kind'] == 'CYCLE':
            obs = command['observation']
            for q in obs['quotes']:
                if not isinstance(q, dict) or not isinstance(q.get('contract'), str):
                    continue
                authority = wanted.get(q['contract'])
                if authority and q.get('at') == authority['at'] and digest(q) == authority['identity']:
                    # Only discard unrelated bars/quotes in this read projection;
                    # the complete original event remains unchanged in SQL.
                    self.saved[q['contract']] = {'payload': json.dumps({'at': original['at'],
                        'command': {'kind': 'CYCLE', 'observation': {'source': obs['source'],
                            'capturedAt': obs['capturedAt'], 'quotes': [q]}}})}
        quote_rows = sorted(self.saved.values(), key=lambda r: stamp(json.loads(r['payload'])['at']), reverse=True)
        value = summarize(iter(quote_rows), state, stamp(original['at']))
        equity = value['liquidationEquityCents']; self.samples += 1
        if equity is None:
            self.missing += 1; self.complete = False
        elif self.complete:
            self.peak = max(self.peak if self.peak is not None else equity, equity)
            self.drawdown = max(self.drawdown, self.peak-equity)
        if sequence > self.after:
            self.points.append({'version': sequence, 'eventHash': row['digest'], 'asOf': original['at'],
                'status': value['status'], 'complete': value['complete'],
                'cashCents': state['cash'], 'feesCents': state['fees'],
                'realizedPnlCents': state['realized'], 'ownedBasisCents': value['ownedBasisCents'],
                'liquidationEquityCents': equity, 'totalPnlCents': value['totalPnlCents'],
                'unrealizedPnlCents': value['unrealizedPnlCents'],
                'incompleteReasons': sorted({leg['status'] for leg in value['options'] + value['deliveries']
                    if leg['valueCents'] is None}),
                'prefix': {'eventSamples': self.samples, 'incompleteSamples': self.missing,
                    'complete': self.complete, 'maximumSampledDrawdownCents': self.drawdown if self.complete else None}})
