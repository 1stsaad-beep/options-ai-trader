#!/usr/bin/env python3
"""Run one explicit, verified, non-destructive market archive cycle."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.market_archive_cycle import run_cycle
from app.repository import Repository
from app.service import TradingService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', help='Existing private directory (0700)')
    parser.add_argument('--account-id', action='append', required=True)
    parser.add_argument('--reserve-mib', type=int, default=512)
    args = parser.parse_args(argv)
    url = os.environ.get('DATABASE_URL', '')
    if not url or args.reserve_mib < 1:
        print(json.dumps({'verified': False, 'error': 'EXPLICIT_DATABASE_AND_POSITIVE_RESERVE_REQUIRED'}))
        return 2
    repo = None
    try:
        # Do not invalidate Demo account state merely to export market records.
        repo = Repository(url, invalidate_accounts=False)
        result = run_cycle(TradingService(repo), args.account_id, args.destination,
                           reserve_bytes=args.reserve_mib * 1024 * 1024)
        print(json.dumps(result))
        return 0
    except Exception:
        # DB errors/paths can carry credentials. Report no raw exception/DSN.
        print(json.dumps({'verified': False, 'error': 'ARCHIVE_CYCLE_FAILED_RETAINED_FILES_REQUIRE_REVIEW'}))
        return 1
    finally:
        if repo is not None:
            repo.close()


if __name__ == '__main__':
    raise SystemExit(main())
