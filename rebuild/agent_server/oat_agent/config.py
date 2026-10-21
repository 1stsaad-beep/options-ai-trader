"""Fixed endpoints and owner settings. PAPER ONLY: the paper trading URL is hard-coded and the live trading host is
on the deny-list of the HTTP layer (net.py), so no code path can reach it."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, fields

PAPER_TRADING_URL = "https://paper-api.alpaca.markets"      # hard-coded; never configurable
MARKET_DATA_URL = "https://data.alpaca.markets"
ANTHROPIC_URL = "https://api.anthropic.com"
FINNHUB_URL = "https://finnhub.io"
LIVE_TRADING_HOSTS = frozenset({"api.alpaca.markets", "broker-api.alpaca.markets"})

# Names of the secret variables (values only ever come from the environment = Railway variables set by the owner).
SECRET_ENV = ("ANTHROPIC_API_KEY", "ALPACA_PAPER_KEY_ID", "ALPACA_PAPER_SECRET_KEY", "BRIDGE_HMAC_KEY",
              "OWNER_TOKEN", "ATLAS_BASE_URL", "FINNHUB_API_KEY")


@dataclass(frozen=True)
class OwnerSettings:
    """Set by the owner (Railway variable OAT_SETTINGS_JSON). The agent has no tool that can change them."""
    daily_loss_limit_percent: float = 30.0      # entries stop for the NY day once equity is down this % from day start
    max_open_positions: int = 1                 # distinct underlyings held or with a working entry order
    max_orders_per_day: int = 20                # opening orders per NY day; exits never capped
    symbol_cooldown_minutes: int = 10           # after an entry or exit on a symbol
    max_premium_per_trade_usd: float = 500.0    # premium of one entry (qty x limit x 100)
    monthly_cap_usd: float = 300.0              # model + data spend of this agent per calendar month (spec §5)
    quote_max_age_s: float = 60.0               # entries only (spec §6); exits never blocked by data age
    same_day_exit_hhmm: str = "15:50"           # time exit (ET) for same-day expiries (spec §5)

    @staticmethod
    def from_env(env=None) -> "OwnerSettings":
        raw = (env or os.environ).get("OAT_SETTINGS_JSON", "")
        if not raw: return OwnerSettings()
        data = json.loads(raw)
        allowed = {f.name for f in fields(OwnerSettings)}
        unknown = set(data) - allowed
        if unknown: raise ValueError(f"unknown settings: {sorted(unknown)}")
        return OwnerSettings(**data)
