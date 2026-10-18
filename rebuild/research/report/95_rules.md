# ملحق أ: القواعد الحتمية الكاملة للاستراتيجيات الموصى بها (جاهزة للبرمجة)

جميع القواعد تُحسب على **الشموع اليومية بعد الإغلاق**، والأمر يُرسل **عند افتتاح اليوم التالي** كأمر Limit قرب منتصف السعر.

- `SMA(n)`: متوسط بسيط. `ATR(14)`: متوسط Wilder للمدى الحقيقي.
- `RSI2`: RSI لفترتين بطريقة Wilder.
- `IBS = (Close − Low) / (High − Low)`.
- `ret12m = Close / Close[252] − 1`.

## S1 — TSMOM Calls الشهرية
```
IF today is the last trading day of the month
AND ret12m > 0
AND Close > SMA(200)
THEN signal = CALL

contract: delta ≈ 0.75, expiry ≈ 35 calendar days
exits (first that triggers):
  - 21 trading days held
  - ≤ 7 days to expiry
size: 2% of equity (premium), max 10% per position, max 5 positions
optional variant: take profit at +30% premium (higher win rate, lower expectancy)
```

## S2 — ارتداد المؤشر داخل الترند (ETF فقط)
```
universe: SPY, QQQ, IWM
IF Close > SMA(200) AND SMA(50) > SMA(200)
AND SPY.Close > SPY.SMA(200)
AND RSI2 < 5 AND IBS < 0.25
AND VIX.Close < 35
THEN signal = CALL

contract: delta ≈ 0.60, expiry ≈ 35 days
stop: underlying Close < min(Low, 5 days) − 1.5·ATR
exits:
  - Close > SMA(5) OR RSI2 > 70
  - 7 trading days held
  - ≤ 7 days to expiry
```

## S3 — قمة 52 أسبوعًا + غير ممتد
```
IF Close > max(High over previous 252 days)
AND no such close in the previous 20 days
AND (Close − SMA(50)) / ATR(14) < 3
THEN signal = CALL

contract: delta ≈ 0.75, expiry ≈ 35 days
stop: underlying Close < entry Close − 2·ATR
exit: 20 trading days, or ≤ 7 days to expiry
```

## S4 — Turtle-55 الجودة
```
IF Close > max(High, previous 55 days)
AND ADX(14) ≥ 20
AND Close > SMA200 AND SMA50 > SMA200 AND SPY > SPY.SMA200
AND ret63 > SPY.ret63
AND percentile(RV20, 252) ≤ 0.70
THEN signal = CALL

contract: delta ≈ 0.75, expiry ≈ 60 days
stop: Close − 2·ATR
exits:
  - Close < min(Low, previous 20 days)
  - trailing: armed at +60% premium, exit on a 30% drop from the peak
  - 30 days held
```

## S0 — الموجة 2/B مع المؤكدات (مؤشر ثقة، لا دخول مستقل)
```
swings: confirmed pivots (3 bars left / 2 right); ignore swings < 1.5·ATR
setup: low s0 → high s1 → higher low s2
  leg1 = s1 − s0 ≥ 3·ATR
  retracement (s1 − s2) / leg1 in [0.382, 0.886]
  s2 > s0
confirmations (≥ 3 of 4):
  Close > anchored VWAP(from s0)
  weekly close > 20-week SMA (previous week)
  MACD(12,26) line > 0
  Close > SMA(200)
trigger (within 10 bars of s2 confirmation):
  Close > max(High, last 3 bars) AND Close > EMA(20)
stop: s2 − 0.25·ATR
target: s2 + leg1
contract: delta 0.75, 45 days
exits: +100% premium; trailing armed at +50%, exit on a 30% drop; 20 days held
```

## قاعدة القفل (مشتركة)
لا يُفتح Call وPut على نفس السهم في نفس الحساب. الاتجاه الآخر لا يُفتح إلا بعد إغلاق المركز كاملًا، وعدم وجود أوامر معلقة، وفي دورة تالية.
