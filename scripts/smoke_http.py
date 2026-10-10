"""Real HTTP + worker smoke test against a temporary synthetic SQLite database."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='mock-smoke-', dir=root) as temp:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    token = secrets.token_urlsafe(32)
    env = os.environ | {'OPTIONS_API_TOKEN': token,
        'DATABASE_URL': 'sqlite:///' + str(Path(temp)/'demo.db'),
        'TRADING_MODE': 'paper', 'ENABLE_LIVE': 'false'}
    with open(Path(temp)/'server.log','w') as log:
        process = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app',
            '--host','127.0.0.1','--port',str(port)], cwd=root/'backend', env=env,
            stdout=log,stderr=log)
        def call(method, path, body=None, auth=True, expected=200):
            headers = {'Content-Type':'application/json'}
            if auth:
                headers['Authorization']='Bearer '+token
            request=Request(f'http://127.0.0.1:{port}'+path,
                data=json.dumps(body).encode() if body is not None else None,
                headers=headers,method=method)
            try:
                response=urlopen(request,timeout=5)
            except HTTPError as e:
                response=e
            assert response.status==expected, (path,response.status,response.read())
            return json.load(response)
        try:
            deadline=time.monotonic()+15
            while True:
                try:
                    health=call('GET','/health',auth=False)
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic()>deadline:
                        raise RuntimeError('Server startup failed: '+Path(temp,'server.log').read_text())
                    time.sleep(.1)
            assert health['live_enabled'] is False
            assert health['version'] == '0.4.0'
            call('GET','/api/accounts',auth=False,expected=401)
            call('GET','/openapi.json',auth=False,expected=401)
            call('GET','/docs',auth=False,expected=401)
            a=call('POST','/api/accounts',{'name':'HTTP demo A'},expected=201)['id']
            b=call('POST','/api/accounts',{'name':'HTTP demo B'},expected=201)['id']
            base='/api/accounts/'+a
            call('POST',base+'/watchlist',{'symbol':'NVDA','enabled':True})
            expiry=datetime.now(timezone.utc).date()+timedelta(days=7)
            expiry+=timedelta(days=(4-expiry.weekday())%7)
            order_body=dict(request_key='smoke-1',symbol='NVDA',right='CALL',
                expiry=expiry.isoformat(),strike_cents=15000,side='BUY',quantity=2,limit_cents=50)
            order=call('POST',base+'/orders',order_body)
            assert call('POST',base+'/orders',order_body)['id']==order['id']
            assert call('GET','/api/accounts/'+b+'/orders')==[]
            fill=dict(fill_id='http-fill',quantity=1,price_cents=50)
            path=base+'/orders/'+order['id']+'/mock-fill'
            assert call('POST',path,fill)['status']=='PARTIAL'
            call('POST',path,fill)
            assert call('GET',base+'/positions')[0]['quantity']==1
            call('POST',base+'/disconnect')
            call('POST',base+'/orders',order_body|{'request_key':'smoke-2'},expected=409)
            assert call('POST',base+'/reconcile')['resubmitted']==0
            worker=subprocess.run([sys.executable,'-m','app.worker','--once'],cwd=root/'backend',
                env=env,capture_output=True,text=True,timeout=15)
            assert worker.returncode==0,worker.stderr
            # Starting a separate repository must not silently restore trust.
            assert call('GET',base+'/status')['snapshot_valid'] is False
            call('POST',base+'/reconcile')
            call('POST',base+'/mock-market-data',{'symbol':'NVDA','available':True})
            opportunities=call('GET',base+'/opportunities')
            assert opportunities and all(o['actionable'] is False for o in opportunities)
            call('POST',base+'/mock-market-data',{'symbol':'NVDA','available':False})
            blocked=call('POST',base+'/orders',order_body|{'request_key':'outage'},expected=409)
            assert 'Market data' in blocked['detail']
            # Actual HTTP automatic entry -> partial fills -> stop-loss close.
            c=call('POST','/api/accounts',{'name':'Automatic HTTP Mock','equity_cents':3000000},expected=201)['id']
            auto_base='/api/accounts/'+c
            call('POST',auto_base+'/watchlist',{'symbol':'NVDA','enabled':True})
            call('PUT',auto_base+'/risk',{'automation_enabled':True,'auto_quantity':2,'auto_fill_chunk':1})
            call('POST',auto_base+'/automation/run',{},auth=False,expected=401)
            call('POST',auto_base+'/automation/run',{'force':True},expected=422)
            cycle=call('POST',auto_base+'/automation/run',{})
            assert cycle['account_id']==c and cycle['source']=='synthetic_mock'
            assert cycle['orders_submitted']==1 and cycle['fills_applied']==1,cycle
            assert call('GET',auto_base+'/orders')[0]['status']=='PARTIAL'
            call('POST',auto_base+'/automation/run',{})
            assert len(call('GET',auto_base+'/orders'))==1
            # The synthetic spread exceeds this deliberately small test stop.
            call('PUT',auto_base+'/risk',{'stop_loss_pct':1})
            for attempt in range(3):
                cycle=call('POST',auto_base+'/automation/run',{})
                if not call('GET',auto_base+'/positions'):
                    break
                time.sleep(1.1)  # A new synthetic quote permits the next fill chunk.
            assert call('GET',auto_base+'/positions')==[],cycle
            automated=call('GET',auto_base+'/orders')
            assert any(o['side']=='SELL_TO_CLOSE' and o['status']=='FILLED' for o in automated)
            assert len([o for o in automated if o['side']=='BUY'])==1
            call('POST',auto_base+'/automation/run',{})
            assert call('GET',auto_base+'/orders')==automated
            assert call('GET','/api/accounts/'+b+'/orders')==[]
            call('POST','/api/emergency-stop',{})
            blocked=call('POST',base+'/orders',order_body|{'request_key':'smoke-3'},expected=409)
            assert 'Emergency stop' in blocked['detail']
            # A response replay remains a read of the exact durable receipt.
            replay=call('POST',base+'/orders',order_body)
            assert replay['id']==order['id'] and replay['status']=='CANCELLED'
            close=call('POST',base+'/orders',order_body|{
                'request_key':'safe-close','side':'SELL_TO_CLOSE','quantity':1})
            closed=call('POST',base+'/orders/'+close['id']+'/mock-fill',
                {'fill_id':'safe-close-fill','quantity':1,'price_cents':50})
            assert closed['status']=='FILLED'
            assert call('GET',base+'/positions')==[]
            assert call('GET','/api/accounts/'+b+'/positions')==[]
            result={'http_server':'passed','authentication':'passed','account_isolation':'passed',
                'idempotency':'passed','partial_fill_duplicate':'passed','disconnect_reconcile':'passed',
                'independent_shadow_worker':'passed','emergency_stop':'passed',
                'worker_preserves_untrusted_state':'passed','market_data_outage':'passed',
                'safe_emergency_owned_close':'passed','version':'0.4.0',
                'automatic_mock_partial_entry_stop_loss_close':'passed',
                'automatic_daily_entry_replay':'passed',
                'live_orders_sent':0,'data_source':'synthetic','database':'SQLite'}
            print(json.dumps(result,indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()
