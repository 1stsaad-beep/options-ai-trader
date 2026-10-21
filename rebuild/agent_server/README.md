# AI trader agent server (PAPER ONLY)

The server-side Claude agent of Options AI Trader, per `AI_TRADER_AGENT_SPEC v2.1`. It is built in stages. **Stages 1 and 2 are in this folder.** Stage 1 is the executor guards and the code layer. Stage 2 is the data tools, the shadow ledger and the decision snapshots. The server never makes an entry in stages 1 and 2. Paper trading starts only after the owner approves stage 3.

## Hard rules

- **Paper only.** The paper trading URL `https://paper-api.alpaca.markets` is hard-coded (`oat_agent/config.py`). The HTTP layer (`oat_agent/net.py`) refuses the live hosts `api.alpaca.markets` and `broker-api.alpaca.markets`, any non-HTTPS URL, and every host not on the allow-list: paper API, Alpaca data, Anthropic, and the ATLAS base URL.
- **Secrets.** These live only in Railway variables set by the owner:
  - `ANTHROPIC_API_KEY`, `ALPACA_PAPER_KEY_ID`, `ALPACA_PAPER_SECRET_KEY`
  - `BRIDGE_HMAC_KEY`, `OWNER_TOKEN`, `ATLAS_BASE_URL`, `FINNHUB_API_KEY`

  A logging filter scrubs their values, and no API response returns them.
- **No ATLAS engine code.** ER3 and BV1 will be called over HTTPS on the ATLAS server, once the ATLAS main chat publishes the endpoint and HMAC contract.
- **Owner settings** come from `OAT_SETTINGS_JSON`, a Railway variable read at start-up. The settings object is frozen, and no agent tool can change it. The defaults are:

  | setting | default |
  |---|---|
  | daily loss stop | 30 % |
  | max open positions | 1 |
  | max opening orders per day | 20 |
  | cooldown | 10 min |
  | max premium per trade | 500 USD |
  | monthly cap | 300 USD |
  | max quote age | 60 s |
  | same-day exit time | 15:50 ET |

## Guards

`oat_agent/guards.py` holds the guard rules, ported from `trader_core` (Dart). The ported rules are:
- market hours: NYSE calendar plus the broker clock (`nyse.py`)
- daily loss stop
- max open positions
- max opening orders per day
- symbol cooldown
- kill switch, which is the Dart per-account pause
- direction lock

On top of these come the agent-spec rules:
- quote age ≤ 60 s for entries only
- monthly cost cap
- contract rules: buy only, OTM only, expiry today or the next session, limit orders only
- every order needs a journal id and an invalidation level

The shared vectors are in `tests/vectors/guard_vectors.json`. Each vector names the Dart test or Dart implementation line it comes from, or `agent-spec` for agent-only rules.

## Code layer

`oat_agent/code_layer.py`:
- Alerts are evaluated in code.
- **Invalidation exit:** an automatic exit on a 5-minute close beyond the level written at entry. Calls exit on a close below the level, puts on a close above it.
- **Time exit:** at 15:50 ET for same-day expiries, or 10 minutes before an early close.
- **Cap:** when the monthly cap is reached, every open trade is closed and new entries are blocked.
- **Owner controls:** kill-and-flatten.
- Exits are blocked only outside regular trading hours.

## Stage 2: data tools, shadow ledger and snapshots

### Data (`data.py`)
- Algo Trader Plus feeds: SIP for equities and OPRA for options.
- Only completed bars are returned.
- Intraday bars are regular-session only unless `ext_hours` is set.
- 1h bars are built from 5m bars in ATLAS's D-1 buckets: 09:30–10:00, then clock hours.

### Tools (`tools.py`)

| tool | what it does |
|---|---|
| `get_bars` | completed bars for a symbol and timeframe |
| `get_indicators` | indicators computed in code, with documented definitions (`indicators.py`) |
| `get_quote` | last trade with its age in seconds, plus bid/ask, day high/low and VWAP |
| `get_chain` | OPRA bid/ask, IV, greeks, open interest and volume, plus the straddle-implied move |
| `get_events` | earnings from Finnhub when the owner adds a key; CPI/FOMC only from `OAT_MACRO_EVENTS_JSON`; no dates are invented |
| `tradable_today` | read from the real chain: today's or the next session's expiry |
| `expected_range`, `check_target` | ER3/BV1 behind an interface; return `available:false` until the ATLAS endpoint and HMAC contract are given |

### Shadow ledger (`shadow.py`, spec §11)
- For every agent entry there is one shadow trade at the same entry time, with the same expiry and the same OTM distance in dollars.
- Its direction is random, seeded with SHA-256(master_seed:journal_id). The master seed is generated once and logged.
- It exits at the agent's exit time, for the agent's exit reason.
- Both legs are scored realistically: buy at the ask, sell at the bid. Alpaca fills are kept for information only.
- An agent order that is cancelled without a fill voids its shadow.

### Decision snapshots (`store.snapshots`)
- They are gzip JSON, append-only, and replayable.
- They hold every tool call with its exact result, the model id and the prompt version.
- They also hold the full guard inputs of every entry attempt (`order_check`).

## Control API (`oat_agent/control_api.py`)

- `GET /health` needs no authentication.
- With `Authorization: Bearer <OWNER_TOKEN>`:
  - `GET /status`
  - `POST /kill` stops new entries.
  - `POST /resume`
  - `POST /flatten` stops new entries and closes every position.
- If no token is configured, every protected route answers 503.

## Run the tests

```text
cd rebuild/agent_server && python3 -m unittest discover -s tests -t . -v
```

The tests use the standard library only. The runtime needs `tzdata` on slim images.
