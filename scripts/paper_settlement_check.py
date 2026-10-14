"""Disposable PostgreSQL settlement transaction/concurrency acceptance only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import uuid

import psycopg
from psycopg import sql

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.repository import Repository
from app.service import TradingService, Rejected


def run():
    url=os.environ.get('TEST_DATABASE_URL','');parsed=urlparse(url)
    if os.environ.get('TEST_DATABASE_ALLOW_DISPOSABLE')!='1' or parsed.scheme not in ('postgres','postgresql') or parsed.hostname not in ('localhost','127.0.0.1','::1','postgres'):
        raise SystemExit('Only an explicitly disposable local PostgreSQL server is permitted')
    schema='oat_settlement_fixture_'+uuid.uuid4().hex
    repositories=[];checks=[];now=datetime(2026,10,13,15,5,tzinfo=timezone.utc)
    with psycopg.connect(url,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            query=dict(parse_qsl(parsed.query));query['options']='-csearch_path='+schema
            scoped=urlunparse(parsed._replace(query=urlencode(query)))
            repositories=[Repository(scoped),Repository(scoped)]
            services=[TradingService(r,now=lambda:now,today=lambda:now.date()) for r in repositories]
            s=services[0];account=s.create_account('settlement',10000000)['id']
            s.configure(account,{'session_policy':'us_equity_options_2026_2027','commission_cents':65});s.watch(account,'NVDA',True)
            order=s.submit(account,dict(request_key='entry',symbol='NVDA',right='CALL',expiry='2026-10-16',strike_cents=20000,side='BUY',quantity=2,limit_cents=210))
            s.fill(account,order['id'],'entry-fill',2,210)
            request=dict(id='receipt-1',action='EXERCISE',contract='NVDA261016C00200000',quantity=1,feeCents=100,
                underlyingCents=22000,effectiveAt=now.isoformat(),recordedAt=now.isoformat(),source='fixture',reference='postgres-fixture')
            barrier=threading.Barrier(2)
            def attempt(i):
                barrier.wait(timeout=10);return services[i].settle_paper(account,request)
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
            assert results[0]==results[1] and len(s.rows(account,'paper_settlement_receipts'))==1
            assert s.performance(account)['simulated_cash_cents']==7957770
            checks.append('two_connection_duplicate_settlement_commits_once')
            for table in ('paper_settlement_receipts','fill_receipt_times'):
                for command in ('UPDATE '+table+' SET recorded_at=recorded_at','DELETE FROM '+table):
                    try:
                        with repositories[1].transaction() as db:db.execute(command)
                    except psycopg.Error as e:assert 'immutable' in str(e)
                    else:raise AssertionError('Receipt mutation accepted')
            checks.append('postgres_native_receipt_and_clock_immutability')
            try:
                with repositories[1].transaction() as db:
                    db.execute("INSERT INTO paper_delivery_positions VALUES('missing','NVDA',1,1)")
            except psycopg.errors.ForeignKeyViolation:pass
            else:raise AssertionError('Orphan delivery accepted')
            checks.append('delivery_account_foreign_key')
            services[1].reconcile(account)
            close=s.submit(account,dict(request_key='close',symbol='NVDA',right='CALL',expiry='2026-10-16',strike_cents=20000,side='SELL_TO_CLOSE',quantity=1,limit_cents=200))
            services[1].fill(account,close['id'],'close-fill',1,200)
            s.settle_paper(account,request|{'id':'sale','action':'SELL_DELIVERY','quantity':100})
            assert services[1].performance(account)['realized_pnl_cents']==177605
            services[1].reconcile(account);checks.append('interleaved_fill_and_delivery_reconcile_across_connections')
            with repositories[1].transaction() as db:db.execute('UPDATE accounts SET realized=realized+1 WHERE id=?',(account,))
            try:s.reconcile(account)
            except Rejected:pass
            else:raise AssertionError('Corrupt balance accepted')
            checks.append('tampered_balance_locks_reconciliation')
            print(json.dumps({'status':'passed','database':'PostgreSQL','broker':'none','checks_passed':len(checks),'checks_failed':0,'checks':checks},indent=2))
        finally:
            for repo in repositories:repo.close()
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__=='__main__':run()
