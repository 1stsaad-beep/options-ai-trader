"""Explicit OPRA quote reads for the independent virtual runtime. No order API.

The default Basic adapter remains indicative-only. This adapter is constructed
only by the opt-in worker, with its own persisted request budget and auth latch.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from bisect import bisect_right
import json
import re

from .market_data import DataResponse, MarketDataError, allowed_query, number, timestamp
from .observed_option_replay import iso
from .observed_paper import canonical
from .paper_settlement import stamp, PATTERN


class ObservedPaperData:
    source='alpaca'

    def __init__(self, store, transport, *, requests_per_minute=10):
        if type(requests_per_minute) is not int or not 2 <= requests_per_minute <= 30:
            raise ValueError('Invalid observed-paper request budget')
        self.store=store; self.transport=transport; self.budget=requests_per_minute
        self.lease=None; self.coverage_limited=False

    def request(self,path,params,*,cursor_kind=None,cursor_after=None):
        if not allowed_query(path,params,observed_options=True):
            raise MarketDataError('DATA_ROUTE_FORBIDDEN')
        now=self.store.now()
        with self.store.repo.transaction() as db:
            if not self.store._owns(db,self.lease,now): raise MarketDataError('WORKER_LEASE_LOST')
            row=db.one("SELECT payload FROM observed_paper_data_state WHERE name='budget'")
            state=json.loads(row['payload']) if row else {'calls':[],'authBlocked':False,'retryAt':None,'failures':0}
            if state['authBlocked']: raise MarketDataError('DATA_AUTH_OR_ENTITLEMENT_DENIED')
            if state['retryAt'] and stamp(state['retryAt'])>now: raise MarketDataError('DATA_RATE_LIMITED')
            # Future timestamps after a clock regression remain charged.
            state['calls']=[t for t in state['calls'] if now-stamp(t)<timedelta(seconds=60)]
            if len(state['calls'])>=self.budget: raise MarketDataError('DATA_RATE_LIMITED')
            state['calls'].append(iso(now)); self._save(db,state)
            if cursor_kind is not None:
                cursor=self._cursor(db)
                if cursor_kind not in ('quotes','bars'): raise ValueError('Invalid capture cursor')
                cursor[cursor_kind]=cursor_after
                self._validate_cursor(cursor)
                # Reserve rotation in the same transaction as the request slot.
                # A failed/uncertain request remains charged across restart.
                db.execute("INSERT INTO observed_paper_data_state VALUES('capture_cursor',?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
                    (canonical(cursor),))
        try:
            response=self.transport.get(path,params)
        except Exception:
            # Connection/decoding errors retain a durable bounded backoff, never
            # provider text, headers containing credentials or exception bodies.
            response=DataResponse(503,{}, {})
        completed=self.store.now()
        with self.store.repo.transaction() as db:
            if not self.store._owns(db,self.lease,completed): raise MarketDataError('WORKER_LEASE_LOST')
            state=json.loads(db.one("SELECT payload FROM observed_paper_data_state WHERE name='budget'")['payload'])
            if response.status in (401,403): state['authBlocked']=True
            elif response.status==429 or response.status>=500:
                state['failures']=min(state['failures']+1,8)
                delay=60 if response.status==429 else min(300,5*2**(state['failures']-1))
                if response.status==429:
                    from email.utils import parsedate_to_datetime
                    headers={str(k).lower():str(v) for k,v in response.headers.items()}
                    try:
                        retry=headers.get('retry-after','60')
                        seconds=float(retry) if retry.isdigit() else (parsedate_to_datetime(retry)-completed).total_seconds()
                        reset=float(headers.get('x-ratelimit-reset','0'))-completed.timestamp()
                        delay=min(86400,max(60,seconds,reset))
                    except (TypeError,ValueError,OverflowError): pass
                state['retryAt']=iso(completed+timedelta(seconds=delay))
            elif response.status==200:
                state.update(failures=0,retryAt=None)
            self._save(db,state)
        if response.status!=200:
            raise MarketDataError('DATA_AUTH_OR_ENTITLEMENT_DENIED' if response.status in (401,403)
                                  else 'DATA_RATE_LIMITED' if response.status==429 else 'DATA_UNAVAILABLE')
        if not isinstance(response.body,dict): raise MarketDataError('INVALID_PROVIDER_RESPONSE')
        return response.body

    @staticmethod
    def _save(db,state):
        db.execute("INSERT INTO observed_paper_data_state VALUES('budget',?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",(canonical(state),))

    @staticmethod
    def _validate_cursor(value):
        if (not isinstance(value,dict) or set(value)!={'version','quotes','bars'} or type(value['version']) is not int
                or value['version']!=1 or value['quotes'] is not None and
                (not isinstance(value['quotes'],str) or len(value['quotes'])>80 or not PATTERN.fullmatch(value['quotes']))
                or value['bars'] is not None and (not isinstance(value['bars'],str)
                    or re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}',value['bars']) is None)):
            raise MarketDataError('DATA_STATE_REVIEW_REQUIRED')
        return value

    @classmethod
    def _cursor(cls,db):
        row=db.one("SELECT payload FROM observed_paper_data_state WHERE name='capture_cursor'")
        try: value=json.loads(row['payload']) if row else {'version':1,'quotes':None,'bars':None}
        except (ValueError,TypeError): raise MarketDataError('DATA_STATE_REVIEW_REQUIRED') from None
        return cls._validate_cursor(value)

    @staticmethod
    def _rotate(values,after,limit):
        ordered=sorted(values); index=bisect_right(ordered,after) if after else 0
        return (ordered[index:]+ordered[:index])[:limit]

    def capture(self,states,lease):
        self.lease=lease
        owned={p['contract'] for s in states for p in s['positions'].values()}
        requested=owned|{c for s in states if s['enabled'] for choices in s['config']['contracts'].values() for c in choices.values()}
        requested_symbols={symbol for s in states if s['enabled'] for symbol in s['config']['contracts']}
        bars={}; now=self.store.now()
        # Reserve remaining request capacity for owned protection before optional
        # analysis. This read never changes the persisted reservation accounting.
        with self.store.repo.transaction() as db:
            if not self.store._owns(db,lease,now): raise MarketDataError('WORKER_LEASE_LOST')
            cursor=self._cursor(db)
            row=db.one("SELECT payload FROM observed_paper_data_state WHERE name='budget'")
            calls=[] if not row else json.loads(row['payload'])['calls']
            available=self.budget-sum(now-stamp(t)<timedelta(seconds=60) for t in calls)
        contracts=self._rotate(owned,cursor['quotes'],30)
        contracts+=self._rotate(requested-owned,cursor['quotes'],30-len(contracts))
        selected_owned={symbol for s in states for symbol,p in s['positions'].items() if p['contract'] in contracts}
        symbols=self._rotate(requested_symbols&selected_owned,cursor['bars'],10)
        symbols+=self._rotate(requested_symbols-selected_owned,cursor['bars'],10-len(symbols))
        self.coverage_limited=len(contracts)<len(requested) or len(symbols)<len(requested_symbols)
        if symbols and available>int(bool(contracts)):
            # One bounded batch. Partial pagination never masquerades as a
            # complete source window; independent quote protection still runs.
            try:
                raw=self.request('/v2/stocks/bars',{'symbols':','.join(symbols),'feed':'iex','timeframe':'1Min',
                    'start':iso(now-timedelta(minutes=120)),'end':iso(now),'limit':10000,'sort':'asc','adjustment':'raw','asof':'-'},
                    cursor_kind='bars',cursor_after=symbols[-1])
                mapping=raw.get('bars')
                if raw.get('next_page_token') is not None or not isinstance(mapping,dict) or set(mapping)-set(symbols):
                    raise ValueError()
                for symbol,rows in mapping.items():
                    try:
                        if not isinstance(rows,list) or len(rows)>1000: raise ValueError()
                        values=[]
                        for r in rows:
                            at=timestamp(r['t'])
                            if not now-timedelta(minutes=120)<=at<=now: raise ValueError()
                            if at+timedelta(minutes=1)<=now:
                                values.append({'at':iso(at),**{k:number(r[k]) for k in ('o','h','l','c','v')}})
                        bars[symbol]=values
                    except (KeyError,ValueError,TypeError,MarketDataError):
                        continue
            except (KeyError,ValueError,TypeError,MarketDataError):
                pass
        if set(bars)!=requested_symbols: self.coverage_limited=True
        quotes=[]
        if contracts:
            raw=self.request('/v1beta1/options/quotes/latest',{'symbols':','.join(contracts),'feed':'opra'},
                cursor_kind='quotes',cursor_after=contracts[-1])
            mapping=raw.get('quotes')
            if not isinstance(mapping,dict) or set(mapping)-set(contracts): raise MarketDataError('INVALID_PROVIDER_RESPONSE')
            # A malformed member cannot suppress another owned protective quote.
            for contract,value in mapping.items():
                try:
                    if not PATTERN.fullmatch(contract): raise ValueError()
                    quotes.append({'contract':contract,'feed':'opra','at':iso(timestamp(value['t'])),
                        'bid':cents(value['bp']),'ask':cents(value['ap']),
                        'bidSize':size(value['bs']),'askSize':size(value['as'])})
                except (KeyError,ValueError,TypeError,MarketDataError):
                    continue
        if len(quotes)!=len(requested): self.coverage_limited=True
        return {'source':'alpaca','capturedAt':iso(self.store.now()),'stockFeed':'iex','bars':bars,'quotes':quotes}


def cents(value):
    number(value)
    try:
        amount=Decimal(str(value))*100
        if amount!=amount.to_integral_value() or not 1<=amount<=100000000: raise ValueError()
        return int(amount)
    except (InvalidOperation,OverflowError): raise ValueError('Invalid cent quote') from None


def size(value):
    if type(value) is not int or not 1<=value<=1000000000: raise ValueError('Invalid displayed size')
    return value
