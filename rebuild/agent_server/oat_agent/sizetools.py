"""Size tools (spec §4): expected_range = ER3 15m (proven) + BV1 1h (calibrated); check_target uses them only.
They are ATLAS engines and are NOT copied here: they are called over HTTPS on the ATLAS server. The endpoint and its
HMAC contract will come from the ATLAS main chat; until then the stub answers {"available": false} and the agent
must say that the size check is unavailable."""
from __future__ import annotations
from typing import Protocol


class SizeTools(Protocol):
    def expected_range(self, sym: str) -> dict: ...
    def check_target(self, sym: str, price: float) -> dict: ...


class UnavailableSizeTools:
    REASON = "ER3/BV1 غير متاحة بعد: عنوان ATLAS وطريقة التوقيع لم يُحددا من محادثة ATLAS الرئيسية"

    def expected_range(self, sym):
        return {"available": False, "sym": sym, "reason_ar": self.REASON}

    def check_target(self, sym, price):
        return {"available": False, "sym": sym, "price": price, "reason_ar": self.REASON}
