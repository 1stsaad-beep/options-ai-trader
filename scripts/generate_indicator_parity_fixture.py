"""Explicit fixture authoring tool; CI compares stored outputs, never regenerates."""
from datetime import datetime, timedelta, timezone
import json
from math import sin
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.engines import Bar
from app.intelligence.indicators import INDICATOR_CONTRACT_VERSION, indicator_series

cases=[]
for name,count in [('single',1),('warmup',14),('linear',50),('oscillating',80),('flat_zero_volume',40),('utc_reset',70)]:
    start=datetime(2026,10,13,23,30,tzinfo=timezone.utc)
    bars=[]
    for i in range(count):
        close=100. if name=='flat_zero_volume' else 100+i*.2 if name=='linear' else 100+i*.03+5*sin(i/4)
        volume=0 if name=='flat_zero_volume' or name=='utc_reset' and 30<=i<35 else 1000+i*7
        bars.append(Bar(start+timedelta(minutes=i),close-.1,close+.5,close-.5,close,volume))
    cases.append({'name':name,'bars':[{'at':b.timestamp.isoformat(),'o':b.open,'h':b.high,'l':b.low,'c':b.close,'v':b.volume} for b in bars],
                  'expected':indicator_series(bars)})
target=ROOT/'mobile/test/fixtures/indicator_contract_v1.json'
target.write_text(json.dumps({'contract':INDICATOR_CONTRACT_VERSION,'source':'synthetic_parity_fixture','cases':cases},indent=2,allow_nan=False)+'\n')
print(f'Wrote {len(cases)} explicit cases')
