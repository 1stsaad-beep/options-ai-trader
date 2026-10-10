"""Reproducible synthetic walk-forward accounting evidence, never performance advice."""
from datetime import datetime, timedelta, timezone
import json
from math import sin

from app.research import MomentumCandidate, ResearchPoint, StrategyTournament


def main():
    start = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
    quotes = []
    for index in range(150):
        mid = 2 + .002 * index + .08 * sin(index / 7)
        quotes.append(ResearchPoint(start + timedelta(minutes=index), mid - .04, mid + .04))
    candidates = (MomentumCandidate('short-fixture', 5, .005),
                  MomentumCandidate('long-fixture', 12, .015))
    settings = dict(train_size=40, test_size=12, purge=2,
                    commission=.65, slippage=.01, multiplier=100)
    engine = StrategyTournament()
    prefix = engine.walk_forward(quotes[:100], candidates, **settings)
    complete = engine.walk_forward(quotes, candidates, **settings)
    assert prefix['folds'] == complete['folds'][:len(prefix['folds'])]
    result = {
        'version': '1.0.0-rc.2', 'source': 'synthetic_fixed_option_quote_series',
        'purpose': 'Causal selection and cost accounting demonstration only',
        'profitability_evidence': False, 'execution_authority': False,
        'observations': len(quotes), 'settings': settings,
        'future_append_preserves_completed_folds': True,
        'limitations': ['No real market data', 'No exercise or assignment',
                        'One contract and no portfolio capital model',
                        'No option chain rolls or real liquidity verification'],
        'walk_forward': complete,
    }
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
