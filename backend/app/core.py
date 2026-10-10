"""Legacy Sprint-1 test fixture only. API/worker use TradingService for durable risk admission.

This compatibility module performs no external execution and is not a broker adapter.
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

class Mode(str, Enum):
    ANALYSIS = 'analysis'
    PAPER = 'paper'
    LIVE = 'live'

@dataclass(frozen=True)
class RiskProfile:
    allocation_pct: Decimal
    trade_risk_pct: Decimal
    daily_loss_pct: Decimal

    def validate(self):
        for value in (self.allocation_pct, self.trade_risk_pct, self.daily_loss_pct):
            if not value.is_finite() or not Decimal('0') <= value <= Decimal('100'):
                raise ValueError('Risk percentages must be between 0 and 100')

@dataclass(frozen=True)
class TradingAccount:
    account_id: str
    mode: Mode
    risk: RiskProfile

class MockBroker:
    def __init__(self):
        self.orders = []
    def submit_paper_order(self, account: TradingAccount, symbol: str, quantity: int):
        if account.mode != Mode.PAPER:
            raise PermissionError('Mock orders allowed only in paper mode')
        account.risk.validate()
        if not symbol or quantity <= 0:
            raise ValueError('Invalid order')
        order = {'account_id': account.account_id, 'symbol': symbol, 'quantity': quantity, 'status': 'SIMULATED'}
        self.orders.append(order)
        return order

class LiveTradingDisabled(RuntimeError):
    pass

def submit_live_order(*args, **kwargs):
    raise LiveTradingDisabled('Live execution is not implemented in Sprint 1')
