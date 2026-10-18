# ملحق أ: القواعد الحتمية (شبه كود)

```
COMMON
  bars: 5-minute regular session; daily_asof(15:50) = daily OHLC whose close is the 15:50 price
  contract: long Call (dir=+1) / long Put (dir=-1); expiry = first Friday >= entry_date + min_days
            (SPY/QQQ: same-day expiry allowed when min_days = 0, since 2022-11)
  strike: listed strike whose |delta| is closest to target_delta (BS on live IV)
  order: LIMIT near mid (results show the edge is about the size of the spread)
  conditional exits: decided on a bar close, executed at the next bar open
  sell by the close of the session before expiry day (weekly contracts)
  one position per symbol (Call/Put lock of the app still applies)

A  TREND-DIP @15:50
  at 15:50: rsi2(daily_asof) < 10 AND close > sma200 AND vix_prev_close < 35  -> BUY CALL
  delta 0.5, min_days 2, size 2% NAV premium
  exit when (checked 15:50): close >= entry + 0.75*ATR | close <= entry - 1*ATR | close > sma5 | rsi2 > 70

B  WAVE-2/B EXHAUSTION @15:50
  zigzag(confirmed pivots 3/2, swing >= 1.5*ATR): s0 = last swing low, s1 = last swing high (bull case)
  wave1 = s1 - s0 >= 3*ATR AND s1 > previous swing high
  retr = (s1 - low_today)/(s1 - s0) in [0.382, 0.786]
  close > s0 AND close > AVWAP(from s0) AND weekly_trend_up AND close > sma200 AND rsi2 < 10 -> BUY CALL
  mirror for PUT (wave B rally in a down-trend, rsi2 > 90)
  delta 0.5, min_days 2; exit +0.5*ATR / -1*ATR

C  ORB-5 IN PLAY (same day)
  first 5-min bar volume >= 2 * avg(first-bar volume, 14 days); dir = sign(close - open) of that bar
  BUY at 09:35 open; stop = nearer of (first-bar extreme, entry -/+ 0.10*daily ATR); else exit at the close
  delta 0.5, min_days 0, size 1%

D  NOISE-AREA MOMENTUM (SPY/QQQ, same day)
  sigma(t) = mean over 14 days of |close(t)/open - 1| at the same time of day
  UB = max(open, prev_close)*(1+sigma), LB = min(open, prev_close)*(1-sigma)
  at :00/:30 marks 10:00-15:00: close > UB -> CALL, close < LB -> PUT (first signal of the day)
  exit at :00/:30 when close < max(UB, VWAP) (calls) / > min(LB, VWAP) (puts); else at the close
  delta 0.7, 0-DTE, size 1%

PRE-FOMC (candidate for Paper only)
  BUY CALL on SPY/QQQ/IWM at 15:50 the session before a scheduled FOMC statement,
  SELL at 13:55 on statement day (before 14:00); delta 0.5, nearest weekly
```

# ملحق ب: خريطة الكود

| الملف | الوظيفة |
|---|---|
| `fetch_alpaca.py` | تنزيل شموع 5 دقائق من Alpaca (المفاتيح من ملف خارج المستودع) |
| `static/fomc.csv` | تواريخ بيانات FOMC 1999–2026 |
| `oat_research/shortdated.py` | محرك العقود الأسبوعية/اليومية |
| `oat_research/setups4.py` | إعدادات الجولة الرابعة (الارتداد، الموجات، FOMC، ORB، منطقة الضجيج…) |
| `oat_research/intraday4.py` | شرائح الجلسة وسلسلة "حتى 15:50" |
| `oat_research/timing.py` | محرك زمن الوصول للهدف |
| `r4_timing.py` | دراسة الوقت |
| `r4_sim.py`, `r4_close.py` | المحاكاة (الدخول عند الافتتاح التالي وعند الإغلاق) |
| `r4_intraday.py`, `r4_intraday2.py`, `r4_intraday3.py`, `r4_wave_hourly.py` | بيانات 5 دقائق (15:50، ونفس اليوم، والموجات) |
| `r4_noise_robust.py` | متانة زخم منطقة الضجيج |
| `r4_final.py` | الاستراتيجيات الأربع (robust / holdout) |
| `r4_validate.py` | التحقق من الإطار |
| `r4_real_options.py`, `r4_real_dev.py`, `r4_iv_filter.py`, `r4_real_dte.py` | التحقق والتطوير بأسعار العقود الحقيقية |
| `results/r4/*.md`, `*.json` | كل النتائج والتسجيل المسبق |

# ملحق ج: المصادر
- Lucca & Moench (2015), *The Pre-FOMC Announcement Drift*, Journal of Finance.
- Zarattini, Barbon & Aziz (2024), *A Profitable Day Trading Strategy for the U.S. Equity Market* (5-min ORB, stocks in play).
- Zarattini, Aziz & Barbon (2024), *Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)* (noise area).
- Connors & Alvarez, *Short Term Trading Strategies That Work* (RSI(2)).
- Ariel (1990), *High Stock Returns before Holidays*; McConnell & Xu (2008), turn of the month.
- Federal Reserve, FOMC meeting calendars (federalreserve.gov).
- Data: Yahoo Finance (daily), Alpaca Markets SIP (5-minute stock bars) and option bars (2024+).
