"""Deterministic observed-bar fixtures; never provider or profitability evidence."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random

from app.engines import Bar
from app.market_strategy import analyze, STRATEGIES, VERSION

ROOT = Path(__file__).parents[1]


def candidates(seed):
    random_ = random.Random(seed)
    price = 100.0
    rows = []
    start = datetime(2026, 10, 13, 14, tzinfo=timezone.utc)
    for i in range(60):
        opening = price
        price = round(price + random_.uniform(-2, 2), 4)
        rows.append(Bar(start + timedelta(minutes=i), opening, max(opening, price) + random_.uniform(.1, .4),
                        min(opening, price) - random_.uniform(.1, .4), price, 1300 if i == 59 else 1000))
    return rows


def main():
    desired = {('trend', 'CALL'), ('trend', 'PUT'), ('pullback', 'CALL'), ('pullback', 'PUT'),
               ('breakout', 'CALL'), ('breakout', 'PUT'), ('divergence', 'CALL'), ('divergence', 'PUT')}
    selected = []
    for seed in range(4000):
        rows = candidates(seed)
        found = []
        for strategy in sorted({strategy for strategy, _ in desired}):
            signal = analyze(rows, strategy)
            key = (strategy, signal['direction'])
            if key in desired:
                desired.remove(key)
                found.append('-'.join(key))
        if found:
            selected.append(('-'.join(found) + f'-seed{seed}', rows))
        if not desired:
            break
        if any(strategy == 'divergence' for strategy, _ in desired):
            for direction in ('CALL', 'PUT'):
                if ('divergence', direction) not in desired:
                    continue
                last = rows[-1]
                close = max(b.high for b in rows) + 1 if direction == 'CALL' else min(b.low for b in rows) - 1
                changed = rows[:-1] + [Bar(last.timestamp, last.open, max(last.high, close + .2),
                                         min(last.low, close - .2), close, last.volume)]
                if analyze(changed, 'divergence')['direction'] == direction:
                    desired.remove(('divergence', direction))
                    selected.append((f'divergence-{direction}-structure-break-seed{seed}', changed))
    assert not desired, desired
    start = datetime(2026, 10, 13, 14, tzinfo=timezone.utc)
    flat = [Bar(start + timedelta(minutes=i), 100, 101, 99, 100, 1000) for i in range(40)]
    selected.extend([('flat-low-volume', flat), ('flat-qualified-volume', flat[:-1] + [Bar(flat[-1].timestamp, 100, 101, 99, 100, 1200)]),
                     ('zero-volume', [Bar(b.timestamp, b.open, b.high, b.low, b.close, 0) for b in flat])])
    result = {'contract': VERSION, 'source': 'authored_fixture', 'cases': []}
    for name, rows in selected:
        result['cases'].append({'name': name, 'bars': [{'at': b.timestamp.isoformat(), 'o': b.open, 'h': b.high,
            'l': b.low, 'c': b.close, 'v': b.volume} for b in rows],
            'prefixes': [{strategy: analyze(rows[:end], strategy) for strategy in STRATEGIES}
                         for end in range(1, len(rows) + 1)]})
    path = ROOT / 'mobile/test/fixtures/market_strategy_v1.json'
    path.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print({'cases': len(result['cases']), 'prefixes': sum(len(c['prefixes']) for c in result['cases']), 'bytes': path.stat().st_size})


if __name__ == '__main__':
    main()
