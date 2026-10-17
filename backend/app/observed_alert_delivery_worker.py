"""Explicitly approved notification sender; never starts trading or migrates DB."""
import argparse
from datetime import datetime, timezone
import json
import os
import signal
import threading
import uuid

from .alert_webhook import from_file
from .observed_alert_delivery import AlertDelivery
from .observed_paper_watchdog import connection
from .observed_option_replay import iso
from .observed_paper import canonical


def health(url, owner, now, state):
    with connection(url) as db:
        db.execute("INSERT INTO runtime_health VALUES('observed_alert_delivery',?,?) ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload",
            (iso(now),canonical({'state':state,'owner':owner,'externalOrder':False})))


def stop_health(url,owner):
    with connection(url) as db:
        row=db.one("SELECT payload FROM runtime_health WHERE name='observed_alert_delivery'")
        if row and json.loads(row['payload']).get('owner')==owner:
            db.execute("UPDATE runtime_health SET payload=? WHERE name='observed_alert_delivery' AND payload=?",
                (canonical({'state':'STOPPED','owner':owner,'externalOrder':False}),row['payload']))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--once',action='store_true')
    group.add_argument('--healthcheck',action='store_true')
    group.add_argument('--reset-auth-lock',action='store_true')
    args=parser.parse_args(argv)
    if os.getenv('TRADING_MODE','paper')!='paper' or os.getenv('ENABLE_LIVE','false').lower()!='false': return 1
    now=lambda:datetime.now(timezone.utc)
    url=os.getenv('DATABASE_URL','sqlite:///options_demo.db')
    if args.healthcheck:
        from .runtime_health import probe_heartbeat
        return 0 if probe_heartbeat(url,'observed_alert_delivery',now()) else 1
    if os.getenv('OAT_ALERT_DELIVERY_APPROVAL')!='notifications_only_approved':
        print(json.dumps({'component':'observed_alert_delivery','state':'DISABLED','externalOrder':False}),flush=True)
        return 0
    owner=uuid.uuid4().hex;stop=threading.Event()
    previous={name:signal.signal(name,lambda *_:stop.set()) for name in (signal.SIGTERM,signal.SIGINT)}
    try:
        try:
            receiver=from_file(os.getenv('OAT_ALERT_RECEIVER_FILE',''))
            sender=AlertDelivery(lambda:connection(url),now,receiver,receiver.target_hash,owner)
        except Exception:
            print(json.dumps({'component':'observed_alert_delivery','state':'CONFIGURATION_UNAVAILABLE','externalOrder':False}),flush=True)
            return 1
        if args.reset_auth_lock:
            try:sender.reset_auth();return 0
            except Exception:
                print(json.dumps({'component':'observed_alert_delivery','state':'RESET_UNAVAILABLE','externalOrder':False}),flush=True)
                return 1
        while not stop.is_set():
            try:
                result=sender.tick();health(url,owner,now(),result['state']);ok=True
            except Exception:
                result={'state':'DELIVERY_UNAVAILABLE','externalOrder':False};ok=False
            print(json.dumps({'component':'observed_alert_delivery',**result}),flush=True)
            if args.once:return 0 if ok else 1
            stop.wait(5)
    finally:
        try:stop_health(url,owner)
        except Exception:pass
        for name,handler in previous.items():signal.signal(name,handler)
    return 0


if __name__=='__main__':raise SystemExit(main())
