"""Real SQL genesis/comparison fixture; no provider or synthetic market prices."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.observed_paper_store import ObservedPaperStore
from app.repository import Repository


def generate():
    repo = Repository(invalidate_accounts=False)
    store = ObservedPaperStore(repo, lambda: datetime(2026, 10, 17, 5, tzinfo=timezone.utc))
    try:
        experiment = store.experiment('alpaca')
        ids = [s['state']['id'] for s in experiment['accounts']]
        return {'experiment': experiment, 'comparison': store.comparison(ids)}
    finally:
        repo.close()


if __name__ == '__main__':
    (ROOT / 'mobile/test/fixtures/observed_experiment_v1.json').write_text(
        json.dumps(generate(), ensure_ascii=False, indent=2) + '\n')
