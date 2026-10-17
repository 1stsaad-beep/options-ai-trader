"""Disposable DB acceptance: synthetic alert receiver, no network or credentials."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from app.observed_alert_delivery import AlertDelivery, ACK
from app.observed_paper import digest
from app.paper_settlement import stamp


class FixtureReceiver:
    def __init__(self):self.calls=[];self.status=200;self.valid=True;self.during=None
    def send(self,body,key):
        self.calls.append((body,key))
        if self.during:self.during()
        event=body['event']
        return SimpleNamespace(status=self.status,body={'contract':ACK,'sequence':event['sequence'],'eventHash':event['eventHash']} if self.valid else {})


def check(repositories):
    with repositories[0].transaction() as db:
        before={table:db.all('SELECT * FROM '+table+' ORDER BY 1') for table in
            ('observed_paper_accounts','observed_paper_events','observed_alert_events','observed_alert_ack')}
    assert before['observed_alert_events']
    import json
    clock=[max(datetime.now(timezone.utc),*(stamp(json.loads(e['payload'])['detectedAt']) for e in before['observed_alert_events']))]
    target=digest(['offline-delivery-fixture',uuid.uuid4().hex])
    wire=FixtureReceiver()
    first=AlertDelivery(repositories[0].transaction,lambda:clock[0],wire,target,'first')
    second=AlertDelivery(repositories[1].transaction,lambda:clock[0],wire,target,'second')
    def overlap():assert second.tick()['state']=='STANDBY'
    wire.during=overlap;wire.valid=False
    assert first.tick()['state']=='RETRY_PENDING'
    wire.during=None
    assert second.tick()['state']=='BACKOFF'
    wire.valid=True;clock[0]+=timedelta(seconds=5)
    assert second.tick()['state']=='DELIVERED'
    assert len(wire.calls)==2 and wire.calls[0]==wire.calls[1]
    with repositories[0].transaction() as db:
        row=db.one('SELECT * FROM observed_alert_delivery_receipts WHERE target_hash=?',(target,))
        assert row['sequence']==1 and row['event_hash']==wire.calls[0][0]['event']['eventHash']
        assert before=={table:db.all('SELECT * FROM '+table+' ORDER BY 1') for table in before}
    for statement in ('UPDATE observed_alert_delivery_receipts SET payload=payload','DELETE FROM observed_alert_delivery_receipts'):
        try:
            with repositories[1].transaction() as db:db.execute(statement)
        except Exception:pass
        else:raise AssertionError('Immutable delivery receipt guard missing')
    return ['notification_cross_connection_lease_fencing','notification_exact_ack_restart_retry_same_key',
        'notification_native_receipt_immutable_guards','notification_preserves_financial_and_owner_inbox_state']
