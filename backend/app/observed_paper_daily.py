"""Bounded, causal daily samples of the existing paper liquidation model.

Sample the last microsecond BEFORE the modeled regular close. This is neither
an official closing price nor a post-settlement NAV. No future quotes, forward
fill of stale marks, or returns across missing sessions are permitted.
"""
from datetime import date, datetime, time, timedelta, timezone
from math import sqrt
from statistics import mean, stdev
import json

from .market_sessions import evaluate_session, US_EQUITY_OPTIONS_POLICY
from .observed_option_replay import iso
from .observed_paper_history import retain_original_quotes
from .observed_paper_valuation import summarize
from .paper_settlement import stamp

VERSION = 'observed-paper-daily-v1'
SAMPLING = 'LAST_MICROSECOND_BEFORE_MODELED_SESSION_CLOSE'


def sessions(start, end, now):
    """At most 366 calendar days, entirely closed and inside the known calendar."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Aware report clock required')
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError('ISO date range required')
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if (first.isoformat() != start or last.isoformat() != end or not 0 <= (last-first).days < 366
            or first.year not in (2026, 2027) or last.year not in (2026, 2027)):
        raise ValueError('Bounded supported date range required')
    result = []
    for offset in range((last-first).days+1):
        day = first+timedelta(days=offset)
        # Noon UTC belongs to this same date in New York throughout both years.
        session = evaluate_session(datetime.combine(day, time(12), timezone.utc), US_EQUITY_OPTIONS_POLICY)
        if session.status in ('WEEKEND', 'HOLIDAY'):
            continue
        close = session.closes_at
        if close is None or close > now:
            raise ValueError('Only completed, known sessions may be reported')
        result.append((day.isoformat(), close, close-timedelta(microseconds=1)))
    return result


def performance(points):
    """Simple adjacent daily returns; explicit 252-day, zero-rate Sharpe model."""
    values = [p['liquidationEquityCents'] for p in points]
    returns = [None]
    for previous, current in zip(values, values[1:]):
        returns.append(current/previous-1 if current is not None and previous is not None and previous > 0 else None)
    returns = returns[:len(values)]
    complete = bool(values) and all(value is not None for value in values)
    valid_returns = [value for value in returns[1:] if value is not None]
    all_returns = complete and len(valid_returns) == len(values)-1
    peak = None; drawdown = 0; drawdown_fraction = 0
    if complete:
        for value in values:
            peak = value if peak is None else max(peak, value)
            drawdown = max(drawdown, peak-value)
            if peak > 0:
                drawdown_fraction = max(drawdown_fraction, (peak-value)/peak)
    sharpe = None
    if not values:
        reason = 'NO_SESSIONS'
    elif not complete:
        reason = 'MISSING_DAILY_VALUATION'
    elif not all_returns:
        reason = 'NONPOSITIVE_RETURN_BASE'
    elif len(valid_returns) < 20:
        reason = 'INSUFFICIENT_DAILY_RETURNS'
    elif stdev(valid_returns) == 0:
        reason = 'ZERO_RETURN_VARIANCE'
    else:
        sharpe = mean(valid_returns)/stdev(valid_returns)*sqrt(252)
        reason = 'MODELED_DAILY_RETURNS'
    return {'complete': complete, 'dailyReturns': returns, 'returnSamples': len(valid_returns),
        'totalReturn': values[-1]/values[0]-1 if all_returns and len(values) > 1 and values[0] > 0 else None,
        'maximumDailyDrawdownCents': drawdown if complete else None,
        'maximumDailyDrawdownFraction': drawdown_fraction if complete and max(values) > 0 else None,
        'sharpe': sharpe, 'sharpeStatus': reason, 'annualizationSessions': 252,
        'annualRiskFreeRate': 0, 'minimumSharpeReturns': 20, 'standardDeviation': 'SAMPLE_DDOF_1'}


class DailyProjection:
    def __init__(self, schedule, through):
        self.schedule = schedule; self.through = through; self.index = 0
        self.points = []; self.saved = {}; self.state = None; self.anchor = None

    def observe(self, row, original, state):
        if self.through is not None and row['sequence'] > self.through:
            return
        # Flush BEFORE installing this event, so an event after the sample can
        # never leak a new balance, position, or quote back into that sample.
        self.flush(stamp(original['at']), inclusive=False)
        self.saved = retain_original_quotes(self.saved, original, state)
        self.state = state
        self.anchor = {'version': row['sequence'], 'eventHash': row['digest']}

    def flush(self, until, *, inclusive=True):
        while self.index < len(self.schedule):
            day, close, sample = self.schedule[self.index]
            if sample > until or (sample == until and not inclusive):
                break
            point = {'sessionDate': day, 'sessionClose': iso(close), 'asOf': iso(sample),
                'stateVersion': self.anchor['version'] if self.anchor else None,
                'stateEventHash': self.anchor['eventHash'] if self.anchor else None}
            if self.state is None:
                point.update(status='ACCOUNT_NOT_CREATED', complete=False, cashCents=None,
                    feesCents=None, realizedPnlCents=None, ownedBasisCents=None,
                    liquidationEquityCents=None, unrealizedPnlCents=None, totalPnlCents=None,
                    incompleteReasons=['ACCOUNT_NOT_CREATED'])
            else:
                rows = sorted(self.saved.values(), key=lambda r: stamp(json.loads(r['payload'])['at']), reverse=True)
                value = summarize(iter(rows), self.state, sample)
                point.update({key: value[key] for key in ('status', 'complete', 'cashCents',
                    'ownedBasisCents', 'liquidationEquityCents', 'unrealizedPnlCents', 'totalPnlCents')})
                point.update(feesCents=self.state['fees'], realizedPnlCents=self.state['realized'],
                    incompleteReasons=sorted({leg['status'] for leg in value['options']+value['deliveries']
                        if leg['valueCents'] is None}))
            self.points.append(point); self.index += 1
