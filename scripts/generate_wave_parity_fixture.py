"""Explicit fixture authoring; CI verifies stored evidence, never regenerates it."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.engines import Bar
from app.intelligence.pivots import confirmed_pivots
from app.intelligence.waves import wave_candidates, nested_third_candidates, WaveScenarioTracker

CONTRACT='confirmed-wave-pivots-3-1-v1'
START=datetime(2026,10,13,14,tzinfo=timezone.utc)
KINDS={'WAVE_3_CANDIDATE':'third','ABC_ZIGZAG_CANDIDATE':'abc','WAVE_5_PENDING':'fifth',
       'IMPULSE_1_5_COMPLETED':'impulse','THIRD_OF_THIRD_CANDIDATE':'third_of_third'}

def portable(s, all_scenarios):
    def points(v):return [[p['index'],p['confirmed_index'],p['price'],p['kind']=='HIGH'] for p in v['points']]
    return {'kind':KINDS[s['kind']],'degree':s['degree'],'bullish':s['direction']=='BULLISH',
        'points':points(s),'labels':s['labels'],'invalidation':s['invalidation'],'activation':s['activation'],
        'targets':s['targets'],'evidence':s['evidence_score'],
        'observed_at':int((datetime.fromisoformat(s['observed_at'])-START).total_seconds()/60),
        'parentPoints':points(all_scenarios[s['parent_id']]) if s['parent_id'] else None}

def event_key(e):
    s=e['scenario'];parent=s['parentPoints'] or []
    return '|'.join([e['event'],str(e['tick']),s['kind'],s['degree'],','.join(str(p[0]) for p in s['points']),','.join(str(p[0]) for p in parent)])

def trace(rows):
    bars=[Bar(START+timedelta(minutes=i),*row) for i,row in enumerate(rows)]
    tracker=WaveScenarioTracker();known={};steps=[]
    for i,b in enumerate(bars):
        prefix=bars[:i+1]
        main=wave_candidates(confirmed_pivots(prefix,left=3,right=3))
        internal=wave_candidates(confirmed_pivots(prefix,left=1,right=1),degree='internal')
        values=main+internal+nested_third_candidates(main,internal)
        known.update({s.scenario_id:s.to_dict() for s in values})
        events=tracker.observe(values,as_of=b.timestamp,close=b.close)
        portable_events=[{'event':e.event,'tick':i,'close':e.price,'scenario':portable(json.loads(e.snapshot_json),known)} for e in events]
        steps.append({'through':i,'events':sorted(portable_events,key=event_key)})
    return steps

def source(anchors):
    keys=sorted(anchors);rows=[]
    for i in range(keys[-1]+1):
        left=max(k for k in keys if k<=i);right=min(k for k in keys if k>=i)
        c=anchors[left] if left==right else anchors[left]+(anchors[right]-anchors[left])*(i-left)/(right-left)
        c=float(c);rows.append([c,c+.1,c-.1,c,100.])
    return rows

def cases():
    regular=source({0:110,4:100,14:110,24:105,34:125,44:115,54:130,64:90,74:110})
    nested=source({0:110,4:100,14:115,24:105,26:115,28:110,30:130,32:125,34:140,44:120,54:150,64:90,74:110})
    mirror=[[300-o,300-l,300-h,300-c,v] for o,h,l,c,v in regular]
    plateau=[r[:] for r in regular];plateau[15]=plateau[14][:]
    outside=[r[:] for r in regular];outside[24]=[105.,200.,50.,105.,100.]
    return [('bullish_invalidation',regular),('bearish_invalidation',mirror),('nested_parent_confirmation',nested),
        ('equal_extrema_rejected',plateau),('outside_bar_unordered',outside),('flat_no_pivot',[[100.,100.,100.,100.,0.] for _ in range(40)])]

def main():
    data={'contract':CONTRACT,'scope':'confirmed geometry and causal detection/invalidation events; IDs/rank tie-breaks remain engine-local',
          'cases':[{'name':name,'bars':rows,'steps':trace(rows)} for name,rows in cases()]}
    path=ROOT/'mobile/test/fixtures/wave_contract_v1.json';path.write_text(json.dumps(data,indent=2)+'\n')
    print(len(data['cases']),'sources',sum(len(c['steps']) for c in data['cases']),'prefixes')
if __name__=='__main__':main()
