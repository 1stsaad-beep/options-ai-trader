"""Read-only exporter contract on a disposable SQLite/PostgreSQL database."""
from datetime import datetime, timezone

from app.health_exporter import snapshot
from app.observed_option_replay import iso
from app.observed_paper import canonical
from app.runtime_health import readonly_connection


def check(url, repositories):
    now = datetime.now(timezone.utc)
    with repositories[0].transaction() as db:
        before = {table: db.all('SELECT * FROM ' + table + ' ORDER BY 1') for table in
                  ('observed_paper_accounts', 'observed_paper_events', 'observed_paper_lease',
                   'observed_paper_data_state', 'observed_alert_events', 'observed_alert_delivery_receipts')}
        for name, state in [('observed_paper', 'DISABLED'), ('observed_watchdog', 'MONITORING'),
                            ('observed_alert_delivery', 'AUTH_BLOCKED')]:
            db.execute('INSERT INTO runtime_health VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload',
                       (name, iso(now), canonical({'state': state, 'externalOrder': False})))
    # A writer owns the ordinary advisory/SQLite transaction lock. The exporter
    # must not take it or call Repository/migrate/financial reconciliation.
    with repositories[0].transaction():
        result, status = snapshot(url, now, '0' * 32)
    assert status == 200 and result['databaseReadable']
    assert result['components']['worker'] == {'fresh': True, 'state': 'DISABLED'}
    assert result['components']['delivery'] == {'fresh': True, 'state': 'AUTH_BLOCKED'}
    assert result['externalOrder'] is result['newEntryAllowed'] is result['executionAllowed'] is False
    with readonly_connection(url) as connection:
        try:
            connection.execute("DELETE FROM runtime_health WHERE name='nonexistent-synthetic-probe'")
        except Exception:
            connection.rollback()
        else:
            raise AssertionError('Read-only connection accepted a write')
    with repositories[1].transaction() as db:
        assert before == {table: db.all('SELECT * FROM ' + table + ' ORDER BY 1') for table in before}
    return ['health_export_snapshot_without_writer_advisory_lock',
            'health_export_database_enforced_read_only', 'health_export_no_financial_or_delivery_mutation']
