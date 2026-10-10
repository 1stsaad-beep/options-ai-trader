import unittest
from fastapi.testclient import TestClient
from app.main import create_app
from app.repository import Repository

class V03ApiTests(unittest.TestCase):
    def setUp(self):
        self.repo=Repository()
        self.client=TestClient(create_app(self.repo,'v03-token-longer-than-32-characters'))
        self.client.__enter__()
        self.headers={'Authorization':'Bearer v03-token-longer-than-32-characters'}
        self.a=self.client.post('/api/accounts',headers=self.headers,json={'name':'test'}).json()['id']
        self.prefix='/api/accounts/'+self.a
    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.repo.close()
    def test_api_documentation_requires_authentication(self):
        for path in ('/docs','/openapi.json'):
            self.assertEqual(self.client.get(path).status_code,401)
            self.assertEqual(self.client.get(path,headers=self.headers).status_code,200)
    def test_new_routes_require_authentication(self):
        self.assertEqual(self.client.get(self.prefix+'/status').status_code,401)
        self.assertEqual(self.client.post(self.prefix+'/mock-market-data',json={'symbol':'NVDA'}).status_code,401)
    def test_market_data_requires_strict_boolean_and_mock_entitlement(self):
        self.client.patch(self.prefix+'/watchlist/NVDA',headers=self.headers,json={'enabled':True})
        path=self.prefix+'/mock-market-data'
        self.assertEqual(self.client.post(path,headers=self.headers,json={'symbol':'NVDA','available':'false'}).status_code,422)
        self.assertEqual(self.client.post(path,headers=self.headers,json={'symbol':'OTHER'}).status_code,409)
        response=self.client.post(path,headers=self.headers,json={'symbol':'NVDA','available':False})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['source'],'synthetic_fixture')
    def test_status_and_modes_live_inaccessible(self):
        self.assertFalse(self.client.get(self.prefix+'/status',headers=self.headers).json()['live_enabled'])
        self.assertEqual(self.client.put(self.prefix+'/risk',headers=self.headers,json={'mode':'shadow'}).status_code,200)
        self.assertFalse(self.client.get(self.prefix+'/status',headers=self.headers).json()['new_entries_allowed'])
        self.assertEqual(self.client.put(self.prefix+'/risk',headers=self.headers,json={'mode':'live'}).status_code,409)
