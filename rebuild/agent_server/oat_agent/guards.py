"""Executor guards. Rules ported from trader_core (Dart) — trading_engine.dart (_dailyLimitHit, _openSlotsUsed,
_openingCapReached, _cooldownLeft, pause, _submit RTH guard), direction_lock.dart and the market-hours gate — plus the
agent-spec rules (§3 contracts, §5 cap, §6 data/execution guards). Shared vectors: tests/vectors/guard_vectors.json.

Every check returns (code, Arabic reason). An entry is allowed only when no check fails. Exits are blocked ONLY by
market hours (an order cannot be placed outside RTH) — never by data age, caps, cooldowns, loss stops or the kill switch."""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass
from . import nyse
from .config import OwnerSettings
from .models import EntryRequest, GuardState, Order, Position, Quote


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reasons: tuple          # ((code, reason_ar), ...)

    @property
    def codes(self): return [c for c, _ in self.reasons]


# ---------------------------------------------------------------- bookkeeping (Dart _dailyBookkeeping/_ensureOrdersDay)
def on_snapshot(st: GuardState, now: dt.datetime, equity: float) -> None:
    key = nyse.date_key(now)
    ensure_orders_day(st, now)
    if st.day_key != key:
        st.day_key, st.day_start_equity = key, equity


def ensure_orders_day(st: GuardState, now: dt.datetime) -> None:
    key = nyse.date_key(now)
    if st.orders_day_key != key:
        st.orders_day_key, st.orders_today = key, 0


def record_submission(st: GuardState, now: dt.datetime, underlying: str, opening: bool) -> None:
    """After a successful order submission (Dart _submit): opening orders count toward the daily cap; entries and
    exits both start the symbol cooldown."""
    if opening:
        ensure_orders_day(st, now)
        st.orders_today += 1
    st.last_trade_at[underlying] = now


# ---------------------------------------------------------------- individual rules
def daily_limit_hit(st: GuardState, equity: float, limit_pct: float) -> bool:
    start = st.day_start_equity
    if start is None or start <= 0: return False
    loss_pct = (start - equity) / start * 100
    return not (loss_pct < limit_pct)


def opening_cap_reached(st: GuardState, max_orders: int) -> bool:
    return st.orders_today >= max_orders


def cooldown_left(st: GuardState, symbol: str, now: dt.datetime, minutes: int):
    last = st.last_trade_at.get(symbol)
    if last is None or minutes <= 0: return None
    left = last + dt.timedelta(minutes=minutes) - now
    return left if left > dt.timedelta(0) else None


def open_slots_used(positions, orders) -> int:
    held = {p.contract.underlying for p in positions if p.qty > 0}
    working = {o.contract.underlying for o in orders if o.side == "buy_to_open" and o.is_open}
    return len(held | working)


def active_right(symbol: str, positions, orders):
    for p in positions:
        if p.contract.underlying == symbol and p.qty > 0: return p.contract.right
    for o in orders:
        if o.is_open and o.contract.underlying == symbol: return o.contract.right
    return None


def direction_lock(symbol: str, right: str, positions, orders):
    """direction_lock.dart DirectionLock.canOpen — returns None (allowed) or an Arabic reason."""
    opposite = "put" if right == "call" else "call"
    held = sum(p.qty for p in positions if p.contract.underlying == symbol and p.contract.right == opposite)
    if held > 0:
        return f"قفل الاتجاه: يوجد {_ar(opposite)} مفتوح على {symbol} ({held} عقد) — يجب إغلاقه بالكامل أولًا"
    if any(o.is_open and o.contract.underlying == symbol and o.contract.right == opposite for o in orders):
        return f"قفل الاتجاه: يوجد أمر {_ar(opposite)} قيد التنفيذ على {symbol}"
    if any(o.is_open and o.contract.underlying == symbol and o.contract.right == right and o.side == "sell_to_close" for o in orders):
        return f"يوجد أمر إغلاق قيد التنفيذ على {symbol} — انتظار اكتماله"
    return None


def _ar(right): return "Call" if right == "call" else "Put"


def contract_rule(req: EntryRequest, underlying_price: float, now: dt.datetime):
    """Spec §3: buy calls or puts only, OUT OF THE MONEY only, expiring TODAY or the NEXT trading session only."""
    c = req.contract
    out = []
    if req.side != "buy_to_open": out.append(("BUY_ONLY", "مسموح الشراء فقط (Call أو Put)"))
    if req.order_type != "limit" or not req.limit or req.limit <= 0:
        out.append(("LIMIT_ONLY", "أوامر محددة السعر فقط"))
    otm = c.strike > underlying_price if c.right == "call" else c.strike < underlying_price
    if not otm: out.append(("NOT_OTM", f"العقد ليس خارج المال (السعر {underlying_price:.2f}، التنفيذ {c.strike:.2f})"))
    today = nyse.wall(now).date()
    tomorrow = nyse.next_trading_day(today)
    if c.expiry not in (today, tomorrow):
        out.append(("EXPIRY", f"الانتهاء مسموح اليوم أو الجلسة التالية فقط ({today} / {tomorrow})"))
    return out


# ---------------------------------------------------------------- entry / exit verdicts
def check_entry(req: EntryRequest, *, now: dt.datetime, status: nyse.Status, settings: OwnerSettings,
                st: GuardState, equity: float, positions: list[Position], orders: list[Order],
                underlying_price: float | None, underlying_ts: dt.datetime | None, option_quote: Quote | None,
                month_spend_usd: float, journal_exists=lambda jid: True) -> Verdict:
    r = []
    sym = req.contract.underlying
    if st.paused: r.append(("KILL", "مفتاح الإيقاف مفعّل — لا دخول جديد"))
    if month_spend_usd >= settings.monthly_cap_usd:
        r.append(("COST_CAP", f"بلغ الإنفاق الشهري {month_spend_usd:.2f}$ الحد {settings.monthly_cap_usd:.0f}$"))
    if not status.is_open: r.append(("MARKET_CLOSED", "خارج ساعات التداول الرسمية"))
    if daily_limit_hit(st, equity, settings.daily_loss_limit_percent):
        r.append(("DAILY_LOSS", f"حد الخسارة اليومي {settings.daily_loss_limit_percent}% — لا دخول لبقية اليوم"))
    ensure_orders_day(st, now)
    if opening_cap_reached(st, settings.max_orders_per_day):
        r.append(("DAILY_ORDERS", f"بلغ عدد أوامر الفتح اليوم الحد ({settings.max_orders_per_day})"))
    if active_right(sym, positions, orders) is not None:
        r.append(("ACTIVE", f"يوجد مركز أو أمر قائم على {sym}"))
    elif open_slots_used(positions, orders) >= settings.max_open_positions:
        r.append(("MAX_OPEN", f"تم بلوغ الحد الأقصى للمراكز المفتوحة ({settings.max_open_positions})"))
    lock = direction_lock(sym, req.contract.right, positions, orders)
    if lock: r.append(("LOCK", lock))
    left = cooldown_left(st, sym, now, settings.symbol_cooldown_minutes)
    if left: r.append(("COOLDOWN", f"فترة تهدئة على {sym}: {int(left.total_seconds() // 60) + 1} دقيقة"))
    if not req.journal_id or not journal_exists(req.journal_id):
        r.append(("NO_JOURNAL", "كل أمر يجب أن يشير إلى أطروحة مكتوبة في السجل قبل الأمر"))
    if req.invalidation is None: r.append(("NO_INVALIDATION", "كل دخول يحتاج مستوى إبطال على سعر السهم"))
    if underlying_price is None or underlying_ts is None:
        r.append(("STALE_PRICE", "لا يوجد سعر حديث للسهم"))
    else:
        age = (now - underlying_ts).total_seconds()
        if age > settings.quote_max_age_s:
            r.append(("STALE_PRICE", f"آخر سعر للسهم عمره {age:.0f} ثانية (> {settings.quote_max_age_s:.0f})"))
        r += contract_rule(req, underlying_price, now)
    if option_quote is None or not option_quote.two_sided:
        r.append(("NO_QUOTE", "لا يوجد سعر عرض وطلب صالح للعقد"))
    elif (age := option_quote.age_s(now)) is None or age > settings.quote_max_age_s:
        r.append(("STALE_PRICE", f"سعر العقد قديم ({'?' if age is None else f'{age:.0f}'} ثانية)"))
    if req.limit and req.qty * req.limit * 100 > settings.max_premium_per_trade_usd:
        r.append(("PREMIUM_CAP", f"قيمة الصفقة {req.qty * req.limit * 100:.0f}$ أكبر من الحد {settings.max_premium_per_trade_usd:.0f}$"))
    if req.qty < 1: r.append(("QTY", "الكمية يجب أن تكون عقدًا واحدًا على الأقل"))
    return Verdict(not r, tuple(r))


def check_exit(*, status: nyse.Status) -> Verdict:
    """Exits are never blocked by data age, caps, cooldowns, loss stops or the kill switch; only by market hours
    (Dart _submit last-line guard: no order of any kind outside regular hours)."""
    if not status.is_open: return Verdict(False, (("MARKET_CLOSED", "خارج ساعات التداول الرسمية"),))
    return Verdict(True, ())
