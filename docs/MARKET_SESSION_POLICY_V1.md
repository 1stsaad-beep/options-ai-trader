# Offline US equity-option session policy

Verification date: **2026-10-11**. Calendar version:
`us-equity-options-2026-2027-v1`. This is an optional, per-account simulation
policy. It does not connect to a market, broker, or market-status service.

## Policies and boundaries

| Setting | Behavior |
| --- | --- |
| `session_policy=synthetic_24x7` | Default. Preserves the existing synthetic fixture clock, including weekend fixtures. The legacy `intraday_exit_hour_utc` remains the synthetic intraday deadline. This mode does not claim exchange-calendar realism. |
| `session_policy=us_equity_options_2026_2027` | Opt-in regular-session simulation for New York calendar dates in 2026–2027. Other dates fail closed. |
| `session_exit_buffer_minutes` | Integer from 1 to 120, default 15. For the US policy, the entry cutoff and intraday exit deadline are the modeled close minus this buffer. |

The US policy uses 09:30–16:00 America/New_York, or 09:30–13:00 on the
published early-close dates below. The conservative 16:00/13:00 cutoff applies
even to fixture ETFs: it does not claim to implement product-specific 16:15 or
13:15 exceptions. IANA timezone conversion determines UTC times; a fixed UTC
offset is not used. Missing timezone data blocks new exposure and simulated
fills. Input instants must be timezone aware.

New BUY decisions are permitted at or after the open and strictly before the
entry cutoff. BUY fills must satisfy the same deadline again and remain in the
original New York trading date. This is a DAY decision policy; an accepted BUY
does not acquire fresh authority at the next opening. Scaling and opposite
re-entry use the same service admission checks. A buffer change also affects
pending order admission at fill time.

Owned close acceptance remains available for recording a protective intent.
For the US policy, any actual simulated fill must occur at or after the modeled
open and strictly before the close. Close intents can remain pending awaiting a
valid session. An after-hours quote is not permission to invent a fill. An
idempotent receipt for a fill that already happened remains retrievable after
the session closes; it does not apply a new fill.

Calendar failure must not suppress independent stop-loss, take-profit, trailing,
or other protective evaluation. The calendar cannot grant permission that the
account, ledger, quote, contract, or risk checks deny. An intraday position from
an earlier New York date is overdue and eligible for protective handling at the
next executable session. The `prior_session_position` helper identifies this
condition; it does not authorize a fill.

## Published date snapshot

| Holiday | 2026 | 2027 |
| --- | --- | --- |
| New Year's Day | January 1 | January 1 |
| Martin Luther King Jr. Day | January 19 | January 18 |
| Washington's Birthday | February 16 | February 15 |
| Good Friday | April 3 | March 26 |
| Memorial Day | May 25 | May 31 |
| Juneteenth, observed | June 19 | June 18 |
| Independence Day, observed | July 3 | July 5 |
| Labor Day | September 7 | September 6 |
| Thanksgiving | November 26 | November 25 |
| Christmas, observed | December 25 | December 24 |

Early closes: **2026-11-27**, **2026-12-24**, and **2027-11-26**.
July 2 in 2026 and 2027 is not an early close in the referenced NYSE schedule.
December 31, 2027 is not an observed New Year's Day closure: NYSE explicitly
states that no New Year's Day holiday is observed for January 1, 2028.

## Provenance and audit

`SessionStatus.as_dict()` provides a JSON-safe snapshot containing the policy,
calendar version, verification date, source URLs, New York session date, status,
UTC open/close/exit instants, and entry/fill/exit permissions. Store this with the
original decision and automation audit record. Replay should show those saved
facts instead of silently substituting a later calendar revision.

The date above is when the sources were checked for this implementation, **not**
an invented publication date or evidence that this calendar version was present
at a historical decision. The snapshot does not establish historical market
data quality or out-of-sample performance.

Sources checked on 2026-10-11:

1. [NYSE holidays and trading hours](https://www.nyse.com/trade/hours-calendars):
   publishes 2026–2028 holiday dates, early closes, and regular options hours.
   This is the authority used for the 2026–2027 date snapshot.
2. [Nasdaq equity/options holiday schedule](https://www.nasdaqtrader.com/Trader.aspx?id=Calendar):
   corroborates the 2026 equity/options holiday and early-close dates. An
   independent Nasdaq 2027 confirmation was not retrieved during this review.
3. [Nasdaq options hours](https://www.nasdaqtrader.com/Trader.aspx?id=optionshours):
   specifies equity-option hours and lists ETF/index late-close exceptions.
4. [Python zoneinfo documentation](https://docs.python.org/3/library/zoneinfo.html):
   documents IANA timezone conversion and the need for system timezone data or
   the first-party `tzdata` package. No runtime calendar network request exists.

## Verification and remaining limits

Pure-module tests cover all 20 listed holidays, all three early closes,
open/entry-cutoff/close boundaries, DST transitions in both supported years,
weekends, date exceptions, timezone-equivalent inputs, missing timezone data,
unsupported dates, invalid settings, immutable audit snapshots, and preserved
synthetic behavior. Service/automation tests separately verify that these
results actually gate decisions and fills; a pure-calendar pass alone does not
prove execution integration.

This policy does **not** model unscheduled closures, emergency halts, delayed
opens, extended sessions, product-specific trading hours, broker order handling,
settlement calendars, live time synchronization, or mobile Demo calendar parity.
It does not establish eligibility of a real options contract.

The default synthetic expiry lifecycle is unchanged. The optional US policy now
uses [close-only expiration protection](OPTION_EXPIRATION_POLICY_V1.md): owned
reductions remain possible until the modeled final close, and unresolved
post-cutoff exposure is retained without a writeoff or fictitious settlement.
Real contract qualification, exercise, delivery and assignment remain
unimplemented. Neither policy establishes readiness for a broker trial.

The default mobile local Demo remains explicitly synthetic. No IBKR Paper or
Live connection, external order, paid service, or deployment is enabled here.
