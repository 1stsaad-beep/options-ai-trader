"""Bounded transport of large original receipts, without pruning any evidence."""
import json
from fastapi.testclient import TestClient

from app.main import create_app
from app.observed_paper import canonical
from app.observed_paper_store import EVENT_PAGE_BYTES
from app.repository import Session
from test_observed_paper import stored, iso
from test_alpaca_market_api import TOKEN, HEADERS


def large_originals(store,clock):
    # Deliberately malformed optional analysis, saved as original fixture input.
    # No invented valid candle/price or fill. Its failure fact repeats the key,
    # so receipt JSON is larger than the stored original payload alone.
    observation={'source':'fixture','capturedAt':iso(clock()),'stockFeed':'iex',
        'quotes':[],'bars':{'X'*190000:[]}}
    for i in range(12):
        store.command('a','large'+str(i),{'kind':'CYCLE','observation':observation},
            expected_version=2+i,lease=store.acquire('fixture'))


def test_wire_size_limit_counts_duplicate_receipt_facts_without_skipping_originals(tmp_path):
    repo,store,clock=stored(tmp_path);large_originals(store,clock)
    before=store.snapshot('a',full=True);after=2;all_rows=[];pages=0
    while True:
        rows=store.events('a',after=after,limit=100)
        if not rows:break
        assert len(canonical(rows).encode())<=EVENT_PAGE_BYTES
        assert rows[0]['version']==after+1
        all_rows+=rows;after=rows[-1]['version'];pages+=1
    assert pages==2 and [r['version'] for r in all_rows]==list(range(3,15))
    with repo.transaction() as db:
        for item in all_rows:
            raw=db.one('SELECT payload,digest FROM observed_paper_events WHERE account_id=? AND sequence=?',('a',item['version']))
            assert json.loads(raw['payload'])==item['original'] and raw['digest']==item['eventHash']
    assert store.snapshot('a',full=True)==before
    repo.close()


def test_large_api_page_fits_four_mib_envelope_and_next_cursor(tmp_path):
    repo,store,clock=stored(tmp_path);large_originals(store,clock)
    with TestClient(create_app(repo,TOKEN)) as client:
        first=client.get('/api/observed-paper/accounts/a/events?after=2&limit=100',headers=HEADERS)
        assert first.status_code==200 and len(first.content)<4*1024*1024
        body=first.json();assert 2<body['nextAfter']<14
        second=client.get('/api/observed-paper/accounts/a/events?after='+str(body['nextAfter'])+'&limit=100',headers=HEADERS)
        assert second.status_code==200 and len(second.content)<4*1024*1024
        assert second.json()['nextAfter']==14
    repo.close()


def test_bounded_stream_is_closed_on_byte_cutoff_and_parse_error(tmp_path,monkeypatch):
    repo,store,clock=stored(tmp_path);large_originals(store,clock)
    original=Session.stream;calls=[]
    def tracked(self,sql,parameters=(),batch_size=2):
        item={'read':0,'closed':False};calls.append(item)
        try:
            for row in original(self,sql,parameters,batch_size):
                item['read']+=1
                yield row
        finally:item['closed']=True
    monkeypatch.setattr(Session,'stream',tracked)
    rows=store.events('a',after=2,limit=100)
    assert len(calls)==1 and calls[0]=={'read':len(rows)+1,'closed':True}
    # No original modification: inject a read/decode failure at the cursor only.
    def broken(self,*args,**kwargs):
        try:yield {'payload':'invalid JSON'}
        finally:calls.append({'failureClosed':True})
    monkeypatch.setattr(Session,'stream',broken)
    import pytest
    with pytest.raises(ValueError):store.events('a',after=2)
    assert calls[-1]=={'failureClosed':True}
    repo.close()
