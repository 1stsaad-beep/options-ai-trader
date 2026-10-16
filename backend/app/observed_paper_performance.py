"""Streaming original-receipt statistics; no synthetic marks or NAV claims."""
import json
from collections import Counter


def summarize(rows,state):
    positions={};realized=fees=peak=drawdown=buy=sell=settlements=adds=events=0
    wins=losses=flat=profit=loss=excluded=0;reasons=Counter()
    for row in rows:
        original=json.loads(row['payload']);facts=original['facts'];events+=1
        for fill in facts.get('fills',[]):
            symbol=fill['symbol'];execution=fill['execution'];quantity=execution['quantity']
            fees+=execution['feeCents'];reasons[fill['reason']]+=1
            if fill['side']=='BUY':
                p=positions.setdefault(symbol,{'quantity':0,'cost':0,'pnl':0,'settled':False})
                adds+=int(p['quantity']>0);p['quantity']+=quantity;p['cost']-=execution['cashDeltaCents'];buy+=quantity
            else:
                p=positions[symbol];removed=p['cost']*quantity//p['quantity']
                amount=execution['cashDeltaCents']-removed;p['pnl']+=amount;realized+=amount
                p['quantity']-=quantity;p['cost']-=removed;sell+=quantity
                if not p['quantity']:
                    if p['settled']:excluded+=1
                    else:
                        outcome=p['pnl'];wins+=int(outcome>0);losses+=int(outcome<0);flat+=int(outcome==0)
                        profit+=max(0,outcome);loss+=max(0,-outcome)
                    positions.pop(symbol)
            peak=max(peak,realized);drawdown=max(drawdown,peak-realized)
        if 'settlement' in facts:
            s=facts['settlement'];settlements+=1;fees+=s['feeCents'];realized+=s['realizedPnl']
            if s['optionQuantity']:
                p=positions[s['symbol']];p['quantity']-=s['optionQuantity'];p['cost']-=s['removedCost'];p['settled']=True
                if not p['quantity']:excluded+=1;positions.pop(s['symbol'])
            peak=max(peak,realized);drawdown=max(drawdown,peak-realized)
    if realized!=state['realized'] or fees!=state['fees'] or {
            k:(p['quantity'],p['cost']) for k,p in positions.items()}!={k:(p['quantity'],p['cost']) for k,p in state['positions'].items()}:
        raise ValueError('Receipt performance invariant failed')
    completed=wins+losses+flat;basis=sum(p['cost'] for p in state['positions'].values())+sum(p['cost'] for p in state['deliveries'].values())
    return {'contract':'observed-paper-performance-v1','account':state['id'],'source':state['source'],
        'externalOrder':False,'realizedPnlCents':realized,'feesCents':fees,'cashCents':state['cash'],
        'ownedBasisCents':basis,'bookCapitalCents':state['cash']+basis,
        'realizedReturnPercent':realized*100/state['initialCash'],'maximumRealizedDrawdownCents':drawdown,
        'liquidationEquityCents':None,'unrealizedPnlCents':None,'equityDrawdownPercent':None,'sharpe':None,
        'closedQuoteRoundTrips':completed,'winningQuoteRoundTrips':wins,'losingQuoteRoundTrips':losses,
        'flatQuoteRoundTrips':flat,'quoteWinRatePercent':wins*100/completed if completed else None,
        'quoteProfitFactor':profit/loss if loss else None,'quoteGrossProfitCents':profit,'quoteGrossLossCents':loss,
        'settlementAffectedClosuresExcluded':excluded,'settlementReceipts':settlements,
        'buyContracts':buy,'sellContracts':sell,'addFills':adds,'fillReasons':dict(sorted(reasons.items())),
        'eventCount':events,'valuationStatus':'UNMARKED','asOf':state['lastAt'],
        'limitations':['Realized drawdown is not marked portfolio drawdown',
            'Quote round-trip statistics exclude settlement-affected closures',
            'Book capital retains owned cost basis and is not liquidation equity',
            'No return forecast, Sharpe or mark-to-market metric without qualified complete valuation']}
