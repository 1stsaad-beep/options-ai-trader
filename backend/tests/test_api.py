import os
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import create_app
from app.repository import Repository

TOKEN='test-token-at-least-32-characters-long'
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.repo=Repository()
        self.client=TestClient(create_app(self.repo,TOKEN))
        self.client.__enter__()
        self.headers={'Authorization':'Bearer '+TOKEN}
    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.repo.close()
    def test_entire_mock_api_flow(self):
        self.assertFalse(self.client.get('/health').json()['live_enabled'])
        self.assertEqual(self.client.get('/api/accounts').status_code,401)
        account=self.client.post('/api/accounts',headers=self.headers,json={'name':'API'}).json()['id']
        prefix='/api/accounts/'+account
        self.assertEqual(len(self.client.get(prefix+'/watchlist',headers=self.headers).json()),3)
        self.assertEqual(self.client.patch(prefix+'/watchlist/NVDA',headers=self.headers,json={'enabled':True}).status_code,200)
        date=datetime.now(timezone.utc).date()+timedelta(days=7)
        while date.weekday()!=4: date+=timedelta(days=1)
        request=dict(request_key='test-api',symbol='NVDA',right='CALL',expiry=date.isoformat(),strike_cents=15000,side='BUY',quantity=1,limit_cents=50)
        response=self.client.post(prefix+'/orders',headers=self.headers,json=request)
        self.assertEqual(response.status_code,200,response.text)
        order=response.json()['id']
        self.assertEqual(self.client.post(prefix+'/orders',headers=self.headers,json=request).json()['id'],order)
        self.assertEqual(self.client.post(prefix+'/orders/'+order+'/mock-fill',headers=self.headers,json={'fill_id':'api-fill','quantity':1,'price_cents':50}).json()['status'],'FILLED')
        self.assertEqual(len(self.client.get(prefix+'/positions',headers=self.headers).json()),1)
        self.assertTrue(self.client.get(prefix+'/audit',headers=self.headers).json())
        self.assertEqual(self.client.get(prefix+'/performance',headers=self.headers).json()['open_premium_cents'],5000)
        self.assertTrue(self.client.get(prefix+'/opportunities',headers=self.headers).json())
        self.assertEqual(self.client.post(prefix+'/reconcile',headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/emergency-stop',headers=self.headers,json={}).status_code,200)
        request['request_key']='after-stop'
        self.assertEqual(self.client.post(prefix+'/orders',headers=self.headers,json=request).status_code,409)
    def test_strict_fields_and_config(self):
        account=self.client.post('/api/accounts',headers=self.headers,json={'name':'API'}).json()['id']
        prefix='/api/accounts/'+account
        self.assertEqual(self.client.put(prefix+'/risk',headers=self.headers,json={'strategies':[{}]}).status_code,409)
        self.assertEqual(self.client.put(prefix+'/risk',headers=self.headers,json={'trade_risk_pct':True}).status_code,409)
        self.assertEqual(self.client.put(prefix+'/risk',headers=self.headers,json={'mode':'live'}).status_code,409)
        self.assertEqual(self.client.post('/api/accounts',headers=self.headers,json={'name':'API','secret':'unsafe'}).status_code,422)
    def test_no_token_startup_and_live_environment_fail_closed(self):
        with self.assertRaises(RuntimeError):
            with TestClient(create_app(token='')): pass
        with patch.dict(os.environ,{'ENABLE_LIVE':'true'}):
            with self.assertRaises(RuntimeError):
                with TestClient(create_app(token=TOKEN)): pass
