"""A real service response fixture is consumed by Python and Flutter.

Regenerate intentionally with this module's fixture_payload(), then review the
contract change on both sides. UUIDs/clock are fixed only for serialization.
"""
from datetime import datetime, timedelta, timezone
from itertools import count
import json
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.repository import Repository
from app.research_workbench import (inspect_workbench, snapshot_workbench,
                                   list_workbench_snapshots, replay_workbench)
from app.service import Rejected, TradingService

FIXTURE = Path(__file__).parents[2] / 'mobile/test/fixtures/research_contract_v1.json'
NOW = datetime(2026, 10, 9, 14, 0, 35, tzinfo=timezone.utc)


def fixture_payload():
    # A short session prefix keeps the shared mobile fixture compact; full
    # tournament folds are tested separately by the research workbench suite.
    clock = [NOW.replace(hour=0, minute=40)]
    ids = count(1)
    repo = Repository()
    try:
        with patch('app.service.uuid.uuid4', side_effect=lambda: UUID(int=next(ids))):
            service = TradingService(repo, now=lambda: clock[0], today=lambda: clock[0].date())
            account = service.create_account('Contract fixture')['id']
            service.watch(account, 'NVDA', True)
            current = inspect_workbench(service, account, 'NVDA')
            snapshot = snapshot_workbench(service, account, 'NVDA')
            listing = list_workbench_snapshots(service, account, 'NVDA')
            clock[0] += timedelta(minutes=2)
            replay = replay_workbench(service, account, 'NVDA', snapshot['snapshot_id'])
            return dict(current=current, snapshot=snapshot, list=listing, replay=replay)
    finally:
        repo.close()


def test_python_and_flutter_share_real_service_contract():
    assert fixture_payload() == json.loads(FIXTURE.read_text())


def test_journal_account_symbol_isolation_restart_and_original_payload(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'journal.db')
    repo = Repository(url)
    service = TradingService(repo, now=lambda: NOW, today=lambda: NOW.date())
    a = service.create_account('A')['id']
    b = service.create_account('B')['id']
    service.watch(a, 'NVDA', True)
    saved = snapshot_workbench(service, a, 'NVDA')
    service.watch(a, 'NVDA', False)
    assert list_workbench_snapshots(service, b, 'NVDA')['items'] == []
    assert list_workbench_snapshots(service, a, 'AAPL')['items'] == []
    repo.close()
    repo = Repository(url)
    try:
        service = TradingService(repo, now=lambda: NOW, today=lambda: NOW.date())
        listing = list_workbench_snapshots(service, a, 'NVDA')
        assert listing['items'][0]['snapshot_id'] == saved['snapshot_id']
        assert listing['truncated'] is False
        result = replay_workbench(service, a, 'NVDA', saved['snapshot_id'])
        assert result['original_workbench'] == saved['workbench']
        assert result['as_of'] == result['outcome_as_of'] == saved['workbench']['as_of']
        assert service.rows(a, 'orders') == []
        with pytest.raises(Rejected, match='Unknown account'):
            list_workbench_snapshots(service, 'missing', 'NVDA')
    finally:
        repo.close()


def test_list_is_bounded_and_reports_incomplete_history():
    repo = Repository()
    try:
        service = TradingService(repo, now=lambda: NOW, today=lambda: NOW.date())
        account = service.create_account('A')['id']
        service.watch(account, 'NVDA', True)
        original = snapshot_workbench(service, account, 'NVDA')
        with repo.transaction() as db:
            row = db.one('SELECT * FROM decision_snapshots WHERE id=?', (original['snapshot_id'],))
            for n in range(100):
                db.execute('INSERT INTO decision_snapshots VALUES(?,?,?,?,?,?,?,?)',
                           (str(n), account, None, None, row['action'], row['payload'], row['digest'], row['created']))
        result = list_workbench_snapshots(service, account, 'NVDA')
        assert len(result['items']) == 100
        assert result['truncated'] is True
    finally:
        repo.close()


def test_journal_list_route_requires_authentication():
    repo = Repository()
    token = 'contract-fixture-test-token-0000'
    with TestClient(create_app(repo, token)) as client:
        service = client.app.state.service
        account = service.create_account('A')['id']
        path = f'/api/accounts/{account}/research/NVDA/snapshots'
        assert client.get(path).status_code == 401
        response = client.get(path, headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == 200
        assert response.json()['items'] == []
    repo.close()


@pytest.mark.parametrize('mutation', ['digest', 'version', 'authority'])
def test_corrupt_saved_evidence_fails_closed(mutation):
    repo = Repository()
    try:
        service = TradingService(repo, now=lambda: NOW, today=lambda: NOW.date())
        account = service.create_account('A')['id']
        service.watch(account, 'NVDA', True)
        result = inspect_workbench(service, account, 'NVDA')
        if mutation == 'version':
            result['schema_version'] = True
        if mutation == 'authority':
            result['external_connections'] = True
        with repo.transaction() as db:
            if mutation == 'digest':
                db.execute('INSERT INTO decision_snapshots VALUES(?,?,?,?,?,?,?,?)',
                           ('bad', account, None, None, 'SHADOW_RESEARCH', '{}', '0' * 64, NOW.isoformat()))
            else:
                service.decision(db, account, 'SHADOW_RESEARCH', {'symbol': 'NVDA', 'workbench': result})
        with pytest.raises(Rejected, match='failed validation'):
            list_workbench_snapshots(service, account, 'NVDA')
    finally:
        repo.close()
