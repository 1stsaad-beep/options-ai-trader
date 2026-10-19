"""Pre-market watchlist for the three round-12 big-move combinations.
Daily conditions use the last completed session; the gap is ESTIMATED from the latest pre-market trade (Alpaca delayed SIP).
Intraday triggers (RVOL, Donchian break, % change) can only be checked after the open.  python scan_r12.py"""
import json, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone
import numpy as np, pandas as pd
import fetch_alpaca as A
from fetch_volatile import VOL
from scan_capitulation import UNIVERSE as U1
import r7_lib as L7

EXTRA = ["SNDK", "WDC", "STX", "DELL", "HPE", "ANET", "VRT", "CEG", "VST", "NRG", "OKLO", "SMR", "NNE", "CCJ", "LEU", "TLN", "GEV",
         "ASTS", "LUNR", "ACHR", "JOBY", "QUBT", "RGTI", "QBTS", "SOUN", "BBAI", "AI", "PATH", "TEM", "HIMS", "NVO", "ELF", "LULU",
         "DECK", "ONON", "CROX", "CMG", "WING", "CAVA", "DPZ", "EXPE", "BKNG", "MAR", "RCL", "NCLH", "LYFT", "DASH", "Z", "OPEN",
         "RDDT", "DUOL", "TOST", "BILL", "GTLB", "S", "ESTC", "CFLT", "PANW", "FTNT", "CYBR", "TEAM", "WDAY", "INTU", "ADSK",
         "ANF", "GAP", "AEO", "URBN", "BBY", "DG", "DLTR", "KSS", "M", "BURL", "FIVE", "ULTA", "TPR", "RL", "PVH",
         "ALB", "MP", "CLF", "X", "AA", "SQM", "LAC", "VALE", "RIO", "BHP", "GOLD", "AEM", "KGC", "PAAS", "HL", "CDE", "AG",
         "BIDU", "LI", "TME", "BILI", "FUTU", "TCOM", "GRAB", "NU", "STNE", "MSFT", "AAPL", "BMY", "VRTX", "REGN", "BIIB", "ISRG",
         "DXCM", "PODD", "ALGN", "EW", "GEHC", "HCA", "CI", "HUM", "ELV", "CNC", "MOH", "OSCR", "TDOC", "NVAX", "VKTX", "SRPT",
         "EXAS", "INSM", "ALNY", "WBD", "PARA", "FOXA", "SPOT", "TTWO", "EA", "NTES", "SE", "MELI", "CPNG", "LYV",
         "SNPS", "CDNS", "ASML", "TSM", "NXPI", "MCHP", "ADI", "SWKS", "QRVO", "WOLF", "COHR", "LITE", "CIEN", "FN", "CRDO", "ALAB",
         "NBIS", "CRWV", "CORZ", "IREN", "CIFR", "WULF", "HUT", "BTDR", "CLSK", "GLXY", "SBET", "BMNR", "CRCL", "FIG", "KLAR"]
SYMS = sorted(set(VOL) | set(U1) | set(L7.ORIG) | set(L7.NEW) | set(EXTRA)) if len(sys.argv) < 2 else sys.argv[1:]
KID, SEC = A.keys(); H = {"APCA-API-KEY-ID": KID, "APCA-API-SECRET-KEY": SEC}


def get(url):
    for k in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if getattr(e, "code", 0) == 429: time.sleep(3 + 3 * k); continue
            raise


def daily(syms):
    out = {}
    for i in range(0, len(syms), 50):
        q = dict(symbols=",".join(syms[i:i + 50]), timeframe="1Day", start="2026-06-01T00:00:00Z", limit=10000, adjustment="all", feed="sip")
        tok = None
        while True:
            if tok: q["page_token"] = tok
            d = get("https://data.alpaca.markets/v2/stocks/bars?" + urllib.parse.urlencode(q))
            for s, bars in (d.get("bars") or {}).items(): out.setdefault(s, []).extend(bars)
            tok = d.get("next_page_token")
            if not tok: break
    return {s: pd.DataFrame(b).assign(t=lambda x: pd.to_datetime(x.t)).set_index("t") for s, b in out.items()}


def snaps(syms):
    out = {}
    for i in range(0, len(syms), 100):
        d = get("https://data.alpaca.markets/v2/stocks/snapshots?" + urllib.parse.urlencode(dict(symbols=",".join(syms[i:i + 100]), feed="delayed_sip")))
        out.update(d)
    return out


def main():
    D = daily(SYMS); S = snaps(SYMS); rows = []
    today = datetime.now(timezone.utc).date()
    for s, d in D.items():
        if len(d) < 55: continue
        c = d["c"]; v = d["v"]
        sn = S.get(s) or {}; lt = sn.get("latestTrade") or {}
        last_close = float(c.iloc[-1])
        pm = float(lt["p"]) if lt and pd.Timestamp(lt["t"]).date() == today else np.nan
        rows.append(dict(symbol=s, close=round(last_close, 2), roc20=round((c.iloc[-1] / c.iloc[-21] - 1) * 100, 1),
                         vs_sma50=round((c.iloc[-1] / c.iloc[-50:].mean() - 1) * 100, 1), avg_vol_m=round(v.iloc[-20:].mean() / 1e6, 1),
                         atr_pct=round(((d["h"] - d["l"]).iloc[-14:].mean() / last_close) * 100, 1),
                         premkt=round(pm, 2) if pm == pm else np.nan, gap_est=round((pm / last_close - 1) * 100, 1) if pm == pm else np.nan,
                         last_session=str(d.index[-1].date())))
    R = pd.DataFrame(rows); R = R[(R.avg_vol_m >= 1) & (R.close >= 5)]
    R.to_csv(f"scan_results/r12_{today}.csv", index=False)
    pd.set_option("display.width", 200)
    print(f"universe {len(R)} liquid symbols; last completed session {R.last_session.max()}; pre-market prices as of the latest delayed trade\n")
    c1 = R[R.roc20 < -15].sort_values("gap_est")
    print("C1  capitulation in play  (ROC20 < -15%)  -> needs after the open: RVOL>2 and today < -3%\n", c1.head(15).to_string(index=False), "\n")
    c2 = R[R.roc20 > 20].sort_values("gap_est", ascending=False)
    print("C2  momentum gap-up  (ROC20 > +20%)  -> needs gap > +5% and a 15-min close above the 20-bar high\n", c2.head(15).to_string(index=False), "\n")
    c3 = R[R.vs_sma50 < 0].sort_values("gap_est")
    print("C3  gap-down in downtrend  (below SMA50)  -> needs gap < -5% and a 15-min close below the 20-bar low\n", c3.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
