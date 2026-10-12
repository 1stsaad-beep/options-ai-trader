"""Phone-lab backend contract; no physical Android or public HTTPS claim."""
import pytest
from fastapi.testclient import TestClient
from app import phone_lab, market_runtime
from app.market_runtime import MarketCollector
from app.market_data import DisabledMarketData
from app.repository import Repository
from app.service import TradingService

TOKEN = 'phone-lab-test-only-not-a-deployed-token'
HEADERS = {'Authorization': 'Bearer ' + TOKEN}


def safe_environment(monkeypatch):
    for key in list(__import__('os').environ):
        if key.startswith(('OAT_ALPACA_', 'APCA_', 'ALPACA_', 'IBKR_')):
            monkeypatch.delenv(key)
    for k,v in {'OAT_PHONE_LAB':'isolated_mock_only','TRADING_MODE':'paper',
                'BROKER_PROVIDER':'mock','ENABLE_LIVE':'false',
                'DATABASE_URL':'postgresql://phone_lab:fixture@postgres:5432/options_phone_lab'}.items():
        monkeypatch.setenv(k,v)


@pytest.mark.parametrize('key,value', [('OAT_PHONE_LAB',''),('ENABLE_LIVE','true'),
    ('BROKER_PROVIDER','alpaca'),('DATABASE_URL','sqlite:///old-demo.db'),
    ('DATABASE_URL','postgresql://phone_lab:fixture@existing-host/options_phone_lab'),
    ('DATABASE_URL','postgresql://phone_lab:fixture@postgres/other_database'),
    ('OAT_ALPACA_DATA_APPROVAL','read_only_approved'),('APCA_API_KEY_ID','do-not-read'),
    ('IBKR_HOST','do-not-connect')])
def test_startup_rejects_nonisolated_or_provider_configuration(monkeypatch,key,value):
    safe_environment(monkeypatch)
    phone_lab.validate_environment()
    monkeypatch.setenv(key,value)
    with pytest.raises(RuntimeError, match='PHONE_LAB_ISOLATION_REQUIRED'):
        phone_lab.validate_environment()


def test_real_runtime_contract_controls_events_and_no_orders(monkeypatch):
    safe_environment(monkeypatch)
    monkeypatch.setattr('app.market_data.from_environment',lambda:pytest.fail('External provider factory called'))
    repo=Repository()
    try:
        with TestClient(phone_lab.build_app(repo,TOKEN)) as client:
            assert client.get('/api/accounts').status_code==401
            assert client.get('/api/accounts',headers={'Authorization':'Bearer wrong'}).status_code==401
            accounts=client.get('/api/accounts',headers=HEADERS).json()
            assert {a['name'] for a in accounts}==set(phone_lab.ACCOUNT_NAMES)
            a,b=[x['id'] for x in sorted(accounts,key=lambda x:x['name'])]
            service=client.app.state.service
            collector=MarketCollector(service,DisabledMarketData(),owner='phone-lab-test')
            assert collector.tick()['state']=='DISABLED'
            status=client.get(f'/api/accounts/{a}/market-runtime/status',headers=HEADERS).json()
            assert status['heartbeat_fresh'] is True and status['state']=='DISABLED'
            assert status['external_orders_enabled'] is False and status['virtual_fills_enabled'] is False
            assert status['latest']==[] and status['config']['enabled'] is True
            body={'expected_version':status['config']['version'],'enabled':False,
                  'strategies':{'breakout':False,'pullback':True}}
            assert client.put(f'/api/accounts/{a}/market-runtime/config',headers=HEADERS,json=body).status_code==200
            other=client.get(f'/api/accounts/{b}/market-runtime/status',headers=HEADERS).json()
            assert other['config']=={'version':1,'enabled':False,'strategies':{'breakout':False,'pullback':False}}
            events=client.get(f'/api/accounts/{a}/market-runtime/events',headers=HEADERS).json()['items']
            assert {'CONFIG_CHANGED','PHONE_LAB_READY','COLLECTOR_STATE'} <= {e['kind'] for e in events}
            event=events[0]['id']
            assert client.post(f'/api/accounts/{b}/market-runtime/events/{event}/ack',headers=HEADERS).status_code==404
            assert client.post(f'/api/accounts/{a}/market-runtime/events/{event}/ack',headers=HEADERS).status_code==200
            for path in [f'/api/accounts/{a}/orders',f'/api/accounts/{a}/automation/run',
                         f'/api/accounts/{a}/mock-market-data','/api/accounts']:
                assert client.post(path,headers=HEADERS,json={}).status_code==403
            assert client.put(f'/api/accounts/{a}/risk',headers=HEADERS,json={}).status_code==403
            with repo.transaction() as db:
                assert db.all('SELECT * FROM orders')==[]
                assert db.all('SELECT * FROM positions')==[]
            assert client.get('/phone-lab').json()['provider_connected'] is False
            assert client.get('/phone-lab').headers['cache-control']=='no-store'
            phone_lab.seed_accounts(service)
            assert market_runtime.status(service,a)['config']['version']==2
            assert len(service.list_accounts())==2
    finally:
        repo.close()


def test_existing_unrelated_accounts_are_refused_without_changes():
    repo=Repository()
    try:
        service=TradingService(repo)
        service.create_account('Existing Demo — never touch')
        before=service.list_accounts()
        with pytest.raises(RuntimeError,match='PHONE_LAB_EXISTING_DATA_REFUSED'):
            phone_lab.seed_accounts(service)
        assert service.list_accounts()==before
    finally:
        repo.close()
