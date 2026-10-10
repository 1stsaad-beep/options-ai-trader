# Quantitative engines and historical simulator

Implemented as pure standard-library Python components in `backend/app/engines.py`
and `backend/app/backtest.py`. They contain no broker, network connection, trading
credentials, execution callback, or live order method.

## Implemented rules

- Technical analysis requires at least 21 strictly chronological completed OHLCV
  bars with finite prices and timezone-aware timestamps. Computes SMA20, previous
  SMA20, 14-bar mean true range, and 20-return population standard deviation.
- Regime: high volatility when ATR / close >= 6%; otherwise SMA direction and
  close position distinguish uptrend/downtrend/range. High volatility and range
  suppress these V1 strategy entries.
- Breakout: close exceeds **previous** 20-bar high (CALL) or falls below previous
  20-bar low (PUT), agrees with regime, and volume >= 1.2 times prior average.
- Pullback: trending close resumes direction versus previous close, with the
  current low/high within half ATR of SMA20. Fixed ranking scores are rule
  priorities, not predicted success probabilities.
- Opportunity radar ranks valid signals by score and deterministic tie breakers.
- Options selection: exact underlying/right; future/stale quotes excluded;
  default 7–45 days to expiry, open interest >=100, absolute delta .35–.70,
  positive bid, relative spread <=15%, standard multiplier 100. Selects nearest
  .5 absolute delta then tighter spread. Inputs do not prove broker entitlement.
- Volatility intelligence reports per-bar realized dispersion, available quote
  implied volatility average and wide-spread count. It deliberately does not
  divide annualized IV by unannualized realized dispersion.
- Hybrid AI: optional injected explanation function receives quantitative
  summaries and reasons. Invalid/failed provider responses retain the rule
  narrative. The provider cannot change signals; provider text is untrusted
  display content and must never be parsed as an order. No external AI is wired.
- Shadow mode records account-specific proposed analyses, without executing.

## Historical option simulation

Signals see only the prefix of completed bars at each decision time. Entry occurs
on the next bar, using only the newest option quote timestamped at or before that
bar and no older than the configured freshness limit (60 seconds default).
The current decision bar never receives an entry fill. Entry uses ask plus
slippage, exit bid minus slippage, with per-contract commission on each side.
Maximum premium includes entry fees; cash cannot fund fractional contracts.
Only one long position exists in one run; exits occur after configured holding
bars if a fresh quote exists. Missing quotes skip entry or defer exit.

Expiry is a conservative premium write-off on the first bar dated on or after expiry,
with no invented quote, exercise or assignment. Open final positions are
explicitly reported, not silently closed or counted as completed profits.
The result cash value excludes open-position value and is not account equity.
`trades` includes realized cash P&L and costs. No accuracy, returns or profitability
claims are supported by these synthetic tests.

## Interfaces

`AnalysisEngine().analyze(bars)` returns an immutable `Analysis` containing regime,
ATR, per-bar volatility, signals, narrative and AI status. `OptionQuote` contains
symbol, expiry date, right (`CALL`/`PUT`), strike, bid/ask, signed delta, IV,
open interest, timestamp, multiplier. `OptionsSelectionEngine.select(...)`
returns an eligible quote or `None`.

`BacktestEngine(...).run(symbol, bars, quotes, strategy=None)` returns realized
trades, cash, open contract, decisions and skipped entries. A test strategy
callback receives only a chronological bar prefix and must return a signal for
the current completed bar. Custom callback implementations are trusted Python
code and can themselves violate methodological assumptions; only the default
engine and supplied tested callbacks follow the documented prefix contract.

## Explicit limitations

No licensed historical dataset, exchange calendar, corporate action adjustment,
session/market-hours validation, Greeks calculator, term structure, historical
IV percentile, survivorship correction, exercise economics, fill probability,
partial-fill simulation, parameter optimization, walk-forward statistics, or
actual backtest of a funded trading strategy is implemented here. Bars now carry an explicit `completed` boolean and unfinished bars are rejected.
Feed adapters must establish that timestamp means the completed interval end;
the flag cannot independently prove feed provenance. Broker execution and partial fills belong to the independent execution
service. These engines propose candidates and never authorize risk or execution.

Date boundaries use the timezone on the supplied timestamp. Historical callers
should normalize timestamps consistently (UTC in included tests); full US
exchange expiration timing is a future integration requirement. Floating-point
analytics/simulation are illustrative, while execution accounting must use
decimal arithmetic in the risk/execution service.

Run the actual deterministic checks: `cd backend && python -m unittest discover
-s tests -p test_engines.py -v`.


## V0.3 feed and decision controls

`AnalysisPipeline` composes immutable quantitative engines with fail-closed feed
checks: availability must be exactly `True`, at least 21 completed bars,
timezone-aware as-of time, latest interval end no older than 3 minutes and no
future end, no gaps over 5 minutes within the recent 21-bar window. These defaults
are for the included minute fixture. Daily/swing feeds must inject limits and a
session-aware adapter; applying the minute default to historical/daily bars is
not appropriate. Pure `AnalysisEngine` remains independently usable for validated
historical prefixes.

`analyze_snapshot(symbol,bars,as_of,quotes,available)` exposes a JSON-serializable
proposal with optional filtered option quote and a missed reason for missing
eligible quotes. It always returns `actionable=False` and
`execution_authority=False`; input source is labelled caller supplied/unverified.
It has no broker or risk override. Option selection alone does not imply order
eligibility; independent account/global risk and execution admission are required.

The default shadow worker retains each account's paper/shadow/analysis mode and
never submits an order. It does not reconcile unknown state or fabricate market
observations. V0.4 adds an explicit opt-in execution path: run the worker with
`--execute-mock` and enable automation for an individual paper/mock account.
That path uses the same pure quantitative pipeline and option selector, then
TradingService risk admission, ownership reservation and durable fill accounting.
AI narratives still have no execution authority. See AUTOMATION_V04.md.

## V0.3 backtest accounting verification

Historical quotes with the same contract and timestamp are rejected as ambiguous.
Future quotes cannot affect a prior prefix. Expiry-day premium is conservatively
written off without an exercise or assignment model. This is an explicit safety
assumption, not accurate exchange exercise economics. Result metrics distinguish
realized P&L, total commissions and open acquisition cost from available cash.
An unfilled final-bar signal is reported. No Sharpe ratio, return on equity, or
profitability claim is inferred from cash without mark-to-market data.

Reproduce the synthetic accounting demonstration:

```sh
cd backend
python -m app.backtest
python -m pytest -q tests/test_engines.py tests/test_engines_v03.py tests/test_execution.py
```

The demo actually executed during this change and returns one losing closed trade:
2 contracts; signal 14:50 UTC, next-bar entry 14:51, exit 14:52; ask+slippage
$2.01 entry, bid−slippage $1.89 exit; commissions $2.60 total; realized P&L
−$26.60; final cash $9,973.40 from $10,000. The injected signal only tests causal
fill/accounting logic. It is not a backtest of Breakout/Pullback profitability.
The combined engine/execution subset actually ran **48 passed, 0 failed** at this
checkpoint; root release evidence contains the final full-suite totals.

The added tests cover completed/future/stale/gapped feeds, outage flags/exceptions,
independent strategy warmup, untrusted AI narrative preserving quantitative
signals, proposal serialization, quote ambiguity, future quote invariance,
open-cost/cash distinction, expiry-day write-off, disconnected scan lock,
per-account mode labels/decisions/watchlists, stale market state, disabled
strategies/no-signal decisions and local/global emergency stop.
