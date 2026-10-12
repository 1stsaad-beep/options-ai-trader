"""Local operator CLI: append-only market archive export, verify and restore."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import market_archive
from app.repository import Repository
from app.service import TradingService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('export', 'verify', 'restore'))
    parser.add_argument('file', type=Path)
    parser.add_argument('--account-id')
    parser.add_argument('--sha256')
    parser.add_argument('--trusted-project-archive', action='store_true')
    args = parser.parse_args(argv)
    repo = None
    try:
        if args.operation == 'verify':
            result = market_archive.verify(args.file, expected_sha256=args.sha256)
        else:
            if not args.account_id or not os.getenv('DATABASE_URL'):
                parser.error('Explicit DATABASE_URL and --account-id required')
            repo = Repository(os.environ['DATABASE_URL'], invalidate_accounts=False)
            s = TradingService(repo)
            result = (market_archive.export(s, args.account_id, args.file) if args.operation == 'export' else
                      market_archive.restore(s, args.account_id, args.file, expected_sha256=args.sha256,
                          trusted_archive=args.trusted_project_archive))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'status': 'failed', 'reason': 'Archive operation refused; originals preserved. Check trusted file, digest, identity, disabled runtime and disk.'}))
        return 1
    finally:
        if repo is not None:
            repo.close()


if __name__ == '__main__':
    raise SystemExit(main())
