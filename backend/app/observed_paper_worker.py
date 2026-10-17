"""Persistent opt-in virtual worker; disabled startup never reads credentials."""
import argparse
from datetime import datetime, timezone
import json
import os
import signal
import threading

from .repository import Repository
from .observed_paper_store import ObservedPaperStore, LedgerConflict
from .observed_paper_runtime import ObservedPaperRuntime
from .observed_paper_data import ObservedPaperData
from .market_data import AlpacaDataTransport
from .option_metadata import AlpacaMetadataTransport
from .market_runtime_worker import credentials_from_file


def build_provider(store):
    if (os.getenv('OAT_OBSERVED_PAPER_APPROVAL')!='virtual_only_approved'
            or os.getenv('OAT_ALPACA_DATA_APPROVAL')!='read_only_approved'):
        return None
    credentials=credentials_from_file(os.getenv('OAT_ALPACA_DATA_CREDENTIALS_FILE',''))
    budget=int(os.getenv('OAT_OBSERVED_PAPER_REQUESTS_PER_MINUTE','10'))
    metadata=AlpacaMetadataTransport(credentials) if os.getenv('OAT_OPTION_METADATA_APPROVAL')=='read_only_approved' else None
    return ObservedPaperData(store,AlpacaDataTransport(credentials,observed_options=True),requests_per_minute=budget,metadata_transport=metadata)


def reset_auth_lock(store):
    with store.repo.transaction() as db:
        row=db.one("SELECT * FROM observed_paper_lease WHERE name='worker'")
        from .paper_settlement import stamp
        if row and stamp(row['expires_at'])>store.now():
            raise LedgerConflict('Stop observed-paper worker before auth reset')
        row=db.one("SELECT payload FROM observed_paper_data_state WHERE name='budget'")
        if row:
            state=json.loads(row['payload']); state.update(authBlocked=False,retryAt=None,failures=0)
            ObservedPaperData._save(db,state)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--once',action='store_true')
    group.add_argument('--healthcheck',action='store_true')
    group.add_argument('--reset-auth-lock',action='store_true')
    args=parser.parse_args(argv)
    if os.getenv('TRADING_MODE','paper')!='paper' or os.getenv('ENABLE_LIVE','false').lower()!='false':
        raise SystemExit('Live is hard locked')
    now=lambda:datetime.now(timezone.utc)
    url=os.getenv('DATABASE_URL','sqlite:///options_demo.db')
    if args.healthcheck:
        from .runtime_health import probe_heartbeat
        return 0 if probe_heartbeat(url,'observed_paper',now()) else 1
    stop=threading.Event()
    previous={name:signal.signal(name,lambda *_:stop.set()) for name in (signal.SIGTERM,signal.SIGINT)}
    repo=runtime=None
    try:
        while not stop.is_set():
            try:
                if repo is None:
                    repo=Repository(url,invalidate_accounts=False)
                    store=ObservedPaperStore(repo,now)
                    if args.reset_auth_lock:
                        reset_auth_lock(store); return 0
                    runtime=ObservedPaperRuntime(store,build_provider(store))
                result=runtime.tick()
                print(json.dumps({'component':'observed_paper','state':result['state'],'externalOrder':False}),flush=True)
                if args.once: return 0
            except Exception:
                print(json.dumps({'component':'observed_paper','state':'WORKER_UNAVAILABLE','externalOrder':False}),flush=True)
                if runtime is not None:
                    try: runtime.close()
                    except Exception: pass
                if repo is not None:
                    try: repo.close()
                    except Exception: pass
                repo=runtime=None
                if args.once or args.reset_auth_lock: return 1
            stop.wait(15)
    finally:
        if runtime is not None:
            try: runtime.close()
            except Exception: pass
        if repo is not None: repo.close()
        for name,handler in previous.items(): signal.signal(name,handler)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
