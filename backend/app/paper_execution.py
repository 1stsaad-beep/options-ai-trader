"""Portable adverse quote-side paper model; no exchange queue/real-order claim."""
from .paper_settlement import integer, stamp, PATTERN
from datetime import datetime, timezone

VERSION='paper-option-execution-v2'
POLICY={'commissionCents':65,'additionalFeeCents':5,'adverseSlippageCents':1,
        'participationBps':2500,'liquidityPolicy':'minimum_displayed_sides_once_per_quote'}


def project_execution(quote, side, requested, consumed, at):
    base=dict(version=VERSION,policy=dict(POLICY),requestedQuantity=requested,consumedQuantity=consumed,
              side=side,externalOrder=False,queuePositionKnown=False,priceCents=None,feeCents=None,cashDeltaCents=None,quantity=0)
    def no(status):return dict(base,status=status,unfilledQuantity=requested)
    try:
        if at.tzinfo is None:return no('INVALID_REQUEST')
        at=at.astimezone(timezone.utc)
        if (side not in ('BUY','SELL_TO_CLOSE') or type(requested) is not int or not 1<=requested<=1000000
                or type(consumed) is not int or not 0<=consumed<=1000000
                or set(quote)-{'contract','feed','at','bid','ask','bidSize','askSize'}):
            return no('INVALID_REQUEST')
        match=PATTERN.fullmatch(quote['contract'])
        if not match:return no('UNQUALIFIED_QUOTE')
        try:expiry=datetime(2000+int(match[2]),int(match[3]),int(match[4])).date()
        except ValueError:return no('UNQUALIFIED_QUOTE')
        bid,ask,bsize,asize=(quote[k] for k in ('bid','ask','bidSize','askSize'))
        if any(type(v) is not int for v in (bid,ask,bsize,asize)):return no('INVALID_REQUEST')
        age=(at-stamp(quote['at'])).total_seconds()
        if (quote['feed']!='opra' or expiry<at.date() or int(match[6])<=0 or int(match[6])%10
                or not 0<=age<=30 or not 0<bid<=ask<=100000000 or (ask-bid)*5>ask
                or not 1<=bsize<=1000000000 or not 1<=asize<=1000000000):
            return no('UNQUALIFIED_QUOTE')
        available=min(bsize,asize)*2500//10000-consumed
        if available<=0:return no('NO_MODELED_LIQUIDITY')
        quantity=min(requested,available);price=ask+1 if side=='BUY' else bid-1
        if price<=0:return no('NO_POSITIVE_STRESSED_PRICE')
        fee=integer(quantity*70);gross=integer(quantity*price*100)
        return dict(base,status='FILLED' if quantity==requested else 'PARTIAL',quantity=quantity,
            unfilledQuantity=requested-quantity,priceCents=price,feeCents=fee,
            cashDeltaCents=-integer(gross+fee) if side=='BUY' else gross-fee)
    except (ValueError,TypeError,KeyError,OverflowError):return no('INVALID_REQUEST')
