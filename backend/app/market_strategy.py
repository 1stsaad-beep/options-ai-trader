"""Versioned observed-bar signal contract shared with Direct Market Paper.

This is a deterministic signal, never authority to fill an option. Source,
freshness, session, ownership, quote and portfolio admission remain separate.
Legacy synthetic strategies and immutable original decisions are not rewritten.
"""
from math import isfinite

from .intelligence.indicators import checked_bars, indicator_series
from .intelligence.divergence import divergences
from .intelligence.pivots import confirmed_pivots

VERSION = 'observed-market-strategy-v1'
STRATEGIES = ('confluence', 'trend', 'breakout', 'pullback', 'divergence')


def greater(a, b):
    # Decisions near floating-point ties must agree across Python and Dart.
    return a - b > 1e-9 * max(1.0, abs(a), abs(b))


def analyze(bars, strategy='confluence'):
    def result(direction='WAIT', reverse=False, reason='QUANTITATIVE_RULE'):
        return {'contract': VERSION, 'direction': direction,
                'confirmedReverse': reverse, 'reason': reason}
    if len(bars) < 35:
        return result()
    if strategy not in STRATEGIES:
        return result(reason='UNSUPPORTED_STRATEGY')
    bars = checked_bars(bars)
    series = indicator_series(bars)
    points = confirmed_pivots(bars, left=3, right=3)
    evidence = divergences(points, series['rsi14']) + divergences(
        points, series['macd']['line'], name='MACD')
    bull = bear = False
    for item in evidence:
        if item['to']['confirmed_index'] != len(bars) - 1:
            continue
        between = bars[item['from']['index'] + 1:item['to']['index']]
        if not between:
            continue
        if item['kind'] == 'REGULAR_BULLISH' and greater(bars[-1].close, max(b.high for b in between)):
            bull = True
        if item['kind'] == 'REGULAR_BEARISH' and greater(min(b.low for b in between), bars[-1].close):
            bear = True
    if strategy in ('confluence', 'divergence') and bull != bear:
        return result('CALL' if bull else 'PUT', True, 'DIVERGENCE_AND_STRUCTURE_BREAK')
    if strategy == 'divergence':
        return result(reason='NO_CONFIRMED_DIVERGENCE_STRUCTURE')
    momentum = series['rsi14'][-1]
    if momentum is None or not isfinite(momentum):
        return result()
    last, previous = bars[-1], bars[-2]
    mean, macd = series['sma20'][-1], series['macd']['line'][-1]
    if strategy == 'breakout':
        history = bars[-21:-1]
        volume = sum(b.volume for b in history) / len(history)
        if volume <= 0 or greater(volume * 1.2, last.volume):
            return result(reason='BREAKOUT_VOLUME_NOT_CONFIRMED')
        if greater(last.close, max(b.high for b in history)):
            return result('CALL', reason='UPPER_RANGE_VOLUME_BREAK')
        if greater(min(b.low for b in history), last.close):
            return result('PUT', reason='LOWER_RANGE_VOLUME_BREAK')
        return result(reason='NO_RANGE_BREAK')
    bullish = greater(macd, 0) and not greater(50, momentum) and not greater(momentum, 70)
    bearish = greater(0, macd) and not greater(30, momentum) and not greater(momentum, 50)
    if strategy == 'pullback':
        if bullish and not greater(last.low, mean) and greater(last.close, mean) and greater(last.close, previous.high):
            return result('CALL', reason='BULLISH_MEAN_RETEST_AND_STRUCTURE')
        if bearish and not greater(mean, last.high) and greater(mean, last.close) and greater(previous.low, last.close):
            return result('PUT', reason='BEARISH_MEAN_RETEST_AND_STRUCTURE')
        return result(reason='NO_CONFIRMED_MEAN_RETEST')
    if bullish and greater(last.close, mean):
        return result('CALL')
    if bearish and greater(mean, last.close):
        return result('PUT')
    return result()
