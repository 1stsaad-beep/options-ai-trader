"""Explicit authoring, never CI regeneration: server/Direct divergence contract."""
from datetime import datetime, timedelta, timezone
import json
from math import sin
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.engines import Bar
from app.intelligence.divergence import DIVERGENCE_CONTRACT_VERSION, divergences
from app.intelligence.indicators import indicator_series
from app.intelligence.pivots import Pivot, confirmed_pivots

START = datetime(2026, 10, 13, 14, tzinfo=timezone.utc)


def points(values):
    return [Pivot(i, price, 'HIGH' if high else 'LOW', START+timedelta(minutes=i),
                  START+timedelta(minutes=at), at) for i, at, price, high in values]


def portable(values):
    return [{'kind':d['kind'], 'oscillator':d['oscillator'],
             'from':[d['from']['index'], d['from']['confirmed_index'], d['from']['price'], d['from']['kind']=='HIGH'],
             'to':[d['to']['index'], d['to']['confirmed_index'], d['to']['price'], d['to']['kind']=='HIGH'],
             'momentum_from':d['momentum_from'], 'momentum_to':d['momentum_to']}
            for d in values]


def from_bars(bars):
    pivots=confirmed_pivots(bars,left=3,right=3)
    series=indicator_series(bars)
    return portable(divergences(pivots,series['rsi14'])+divergences(pivots,series['macd']['line'],name='MACD'))


def main():
    cases=[]
    for high in (False,True):
        for price, momentum in ((90,60),(110,40),(110,60),(90,40),(100,60),(90,50),
                                (100-1e-8,60),(90,50+1e-10),(90,None)):
            for name in ('RSI','MACD'):
                p=[[3,6,100,high],[13,16,price,high]]
                oscillator=[50.]*17;oscillator[13]=momentum
                cases.append({'name':f'{name}:{high}:{price}:{momentum}', 'points':p,'oscillator':oscillator,
                              'indicator':name,'expected':portable(divergences(points(p),oscillator,name=name))})
    for distance in (2,3,60,61):
        p=[[3,6,100,False],[3+distance,6+distance,90,False]]
        oscillator=[50.]*(7+distance);oscillator[3+distance]=60
        cases.append({'name':f'distance:{distance}','points':p,'oscillator':oscillator,'indicator':'RSI',
                      'expected':portable(divergences(points(p),oscillator))})
    p=[[3,6,100,False],[8,11,120,True],[13,16,90,False],[18,21,130,True],[23,26,80,False]]
    oscillator=[50.]*27
    for i,v in ((3,20),(8,80),(13,30),(18,70),(23,40)):oscillator[i]=v
    cases.append({'name':'all-adjacent-same-kind-pairs','points':p,'oscillator':oscillator,'indicator':'RSI',
                  'expected':portable(divergences(points(p),oscillator))})
    bar_cases=[]
    for name,sign in [('rising',1),('falling',-1),('flat',0)]:
        bars=[]
        for i in range(160):
            close=100+sign*(i*.02+(6-i*.025)*sin(i/4))
            bars.append(Bar(START+timedelta(minutes=i),close,close+.1,close-.1,close,1000))
        expected=from_bars(bars)
        assert bool(expected)==(sign!=0)
        bar_cases.append({'name':name,'bars':[{'at':b.timestamp.isoformat(),'o':b.open,'h':b.high,'l':b.low,'c':b.close,'v':b.volume} for b in bars],
                          'expected':expected})
    path=ROOT/'mobile/test/fixtures/divergence_contract_v1.json'
    path.write_text(json.dumps({'contract':DIVERGENCE_CONTRACT_VERSION,'cases':cases,'bars':bar_cases},indent=2)+'\n')
    print(f'Authored {len(cases)} pivot cases and {len(bar_cases)} observed-bar cases')


if __name__=='__main__':main()
