"""Deterministic local Mock scenarios, not a strategy profitability backtest."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json

from app.automation import fixture_quotes, run_account
from app.repository import Repository
from app.service import TradingService


def scenario(reason):
    clock = [datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)]
    repo = Repository()
    service = TradingService(repo, now=lambda: clock[0], today=lambda: clock[0].date())
    try:
        account = service.create_account('Synthetic ' + reason, 3000000)['id']
        service.watch(account, 'NVDA', True)
        service.configure(account, {'automation_enabled': True, 'auto_quantity': 3,
                                    'auto_fill_chunk': 1})
        cycles = [run_account(service, account)]
        assert cycles[0]['orders_submitted'] == cycles[0]['fills_applied'] == 1
        replay = run_account(service, account)
        assert replay['orders_submitted'] == replay['fills_applied'] == 0
        clock[0] += timedelta(seconds=1)
        if reason == 'disconnect':
            service.disconnect(account)
            blocked = run_account(service, account)
            assert blocked['blocked_reasons'] and blocked['fills_applied'] == 0
            cycles.append(blocked)
            service.reconcile(account)
            service.mock_market_data(account, 'NVDA')
        cycles.append(run_account(service, account))
        assert service.rows(account, 'positions')[0]['quantity'] == 2
        if reason == 'expiry':
            expiry = date.fromisoformat(service.rows(account, 'orders')[0]['expiry'])
            clock[0] = datetime.combine(expiry, datetime.min.time(), timezone.utc)
            assert run_account(service, account)['blocked_reasons']
            service.reconcile(account)
            cycles.append(run_account(service, account))
            assert cycles[-1]['expired_positions'] == 1
        else:
            bid, ask = (1.40, 1.45) if reason == 'take_profit' else (.70, .73)
            def quotes(symbol, now):
                return [replace(q, bid=bid, ask=ask) for q in fixture_quotes(symbol, now)]
            for _ in range(2):
                clock[0] += timedelta(seconds=1)
                cycles.append(run_account(service, account, quote_feed=quotes))
            assert any(a.get('reason') == ('TAKE_PROFIT' if reason == 'take_profit' else 'STOP_LOSS')
                       for cycle in cycles for a in cycle['actions'])
        assert not service.rows(account, 'positions')
        orders = service.rows(account, 'orders')
        buys = [o for o in orders if o['side'] == 'BUY']
        assert len(buys) == 1
        assert buys[0]['filled'] == 2
        assert buys[0]['status'] == ('EXPIRED' if reason == 'expiry' else 'CANCELLED')
        final = run_account(service, account)
        assert final['orders_submitted'] == final['fills_applied'] == final['expired_positions'] == 0
        return {'scenario': reason, 'status': 'passed',
                'orders': [{k: o[k] for k in ('side', 'quantity', 'filled', 'status')} for o in orders],
                'realized_pnl_cents': service.performance(account)['realized_pnl_cents'],
                'positions_remaining': 0, 'cycles': cycles}
    finally:
        repo.close()


if __name__ == '__main__':
    print(json.dumps({'version': '1.0.0-rc.2', 'source': 'synthetic_mock', 'live_enabled': False,
                      'purpose': 'Controlled lifecycle/accounting checks; not profitability evidence',
                      'scenarios': [scenario(name) for name in
                                    ('take_profit', 'stop_loss', 'expiry', 'disconnect')]}, indent=2))
