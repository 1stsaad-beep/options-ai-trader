"""Alerts written by the model and evaluated in CODE (spec §4 set_alert, §5 code layer).
Grammar:  "<tf> close <op> <price>"  (tf: 1m 5m 15m 1h; evaluated when a bar of that timeframe closes)
          "last <op> <price>"        (evaluated on every trade update)
op: > >= < <="""
from __future__ import annotations
import operator
import re
from dataclasses import dataclass

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
TFS = ("1m", "5m", "15m", "1h")
_RX = re.compile(r"^\s*(?:(1m|5m|15m|1h)\s+close|(last))\s*(>=|<=|>|<)\s*([0-9]+(?:\.[0-9]+)?)\s*$")


@dataclass(frozen=True)
class Condition:
    tf: str | None        # None = "last"
    op: str
    level: float

    def hit(self, value: float) -> bool:
        return OPS[self.op](value, self.level)


def parse(cond: str) -> Condition:
    m = _RX.match(cond or "")
    if not m:
        raise ValueError(f"unsupported alert condition: {cond!r} (use e.g. '5m close > 219.75' or 'last <= 210')")
    tf, last, op, lv = m.groups()
    return Condition(None if last else tf, op, float(lv))


def evaluate_bar(alerts, sym, tf, close):
    """alerts: store rows; returns the rows whose condition is met by this closed bar."""
    out = []
    for a in alerts:
        if a["sym"] != sym: continue
        c = parse(a["cond"])
        if c.tf == tf and c.hit(close): out.append(a)
    return out


def evaluate_last(alerts, sym, price):
    return [a for a in alerts if a["sym"] == sym and (c := parse(a["cond"])).tf is None and c.hit(price)]
