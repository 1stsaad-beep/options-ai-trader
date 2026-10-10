import unittest
from decimal import Decimal
from app.core import Mode, RiskProfile, TradingAccount, MockBroker, LiveTradingDisabled, submit_live_order

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.risk = RiskProfile(Decimal('30'), Decimal('2'), Decimal('3'))
    def test_live_always_disabled(self):
        with self.assertRaises(LiveTradingDisabled):
            submit_live_order()
    def test_mock_rejects_live_account(self):
        account = TradingAccount('account-1', Mode.LIVE, self.risk)
        with self.assertRaises(PermissionError):
            MockBroker().submit_paper_order(account, 'NVDA', 1)
    def test_account_isolation(self):
        broker = MockBroker()
        a = TradingAccount('a', Mode.PAPER, self.risk)
        b = TradingAccount('b', Mode.PAPER, self.risk)
        broker.submit_paper_order(a, 'NVDA', 1)
        broker.submit_paper_order(b, 'AAPL', 2)
        self.assertEqual([o['account_id'] for o in broker.orders], ['a', 'b'])
    def test_invalid_risk(self):
        with self.assertRaises(ValueError):
            RiskProfile(Decimal('101'), Decimal('2'), Decimal('3')).validate()
    def test_negative_quantity(self):
        a = TradingAccount('a', Mode.PAPER, self.risk)
        with self.assertRaises(ValueError):
            MockBroker().submit_paper_order(a, 'NVDA', -1)

if __name__ == '__main__':
    unittest.main()
