"""Win-rate vs. expectancy trade-off: premium take-profit levels (A and B shown)."""
from dataclasses import replace
from round2 import STRATS, run, A, B, data
from oat_research import study as S, backtest as bt
for key in ("S1_tsmom", "S2_dip_etf", "S4_turtle55", "S3_52wh"):
    maker, cfg, only = STRATS[key]; syms = only or list(data); sigs = maker()
    for tp in (None, 1.0, 0.5, 0.3):
        c2 = replace(cfg, exits=replace(cfg.exits, option_target=tp))
        cells = []
        for lab, per in (("A", A), ("B", B)):
            tr, cv = run(sigs, c2, syms, per); st = S.trade_stats(tr); m = bt.metrics(tr, cv)
            cells.append(f"{lab}: win={st.get('win_rate',0):.0%} exp={st.get('expectancy',0):+.1%} PF={st.get('profit_factor',0):.2f} DD={m.get('max_dd',0):+.0%}")
        print(f"{key:12s} take-profit={str(tp):5s} | " + " | ".join(cells), flush=True)
