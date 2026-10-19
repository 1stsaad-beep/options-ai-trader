"""Chart of one chain: one panel per generation with its bars (close line), labels, invalidation and targets."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from . import bars as B, project as PJ

INK = "#0b0b0b"; INK2 = "#52514e"; BLUE = "#2a78d6"; OR = "#eb6834"; RED = "#e34948"; GRID = "#e1e0d9"; SURF = "#fcfcfb"


def chain_figure(sym, chain, asof, path, title=None, last_n=None):
    gens = chain.gens if last_n is None else chain.gens[-last_n:]
    fig, axes = plt.subplots(len(gens), 1, figsize=(12, 2.9 * len(gens)), facecolor=SURF)
    axes = np.atleast_1d(axes)
    for ax, z in zip(axes, gens):
        pat, idx = z.parts[0]
        t0 = pd.Timestamp(z.pts_t[idx[0]])
        b = B.bars(sym, z.tf, t0 - (pd.Timedelta(days=60) if z.tf in ("M", "W") else pd.Timedelta(0)), asof)
        x = np.arange(len(b)); pos = {t: i for i, t in enumerate(b.index)}
        ax.set_facecolor(SURF)
        ax.plot(x, b["close"].to_numpy(), color=INK2, lw=1)
        for t, p, lab, _ in z.labels():
            i = pos.get(pd.Timestamp(t), np.searchsorted(b.index.values, np.datetime64(pd.Timestamp(t))))
            i = min(i, len(b) - 1)
            ax.scatter([i], [p], s=18, color=BLUE, zorder=3)
            ax.annotate(lab, (i, p), textcoords="offset points", xytext=(0, 7), ha="center", color=BLUE, fontsize=10, fontweight="bold")
        pts = [(min(pos.get(pd.Timestamp(t), len(b) - 1), len(b) - 1), p) for t, p, _, _ in z.labels()]
        ax.plot([a for a, _ in pts], [c for _, c in pts], color=BLUE, lw=1.4, alpha=0.8)
        r = PJ.targets(z)
        ax.axhline(r["invalid"], color=RED, lw=1, ls="--")
        ax.text(len(b) - 1, r["invalid"], " invalid", color=RED, fontsize=8, va="bottom", ha="right")
        for name, lv in r["levels"]:
            ax.axhline(lv, color=OR, lw=0.8, ls=":")
            ax.text(len(b) - 1, lv, " " + name, color=OR, fontsize=7.5, va="bottom", ha="right")
        c = z.current()
        ax.set_title(f"{z.tf}  |  {' + '.join(p for p, _ in z.parts)}  |  now: wave {c['leg']} {'up' if c['leg_up'] else 'down'}  |  score {z.score:.2f}",
                     loc="left", fontsize=10, color=INK)
        ticks = np.linspace(0, len(b) - 1, 6).astype(int)
        fmt = "%Y" if z.tf in ("M", "W") else ("%Y-%m-%d" if z.tf == "D" else "%m-%d %H:%M")
        ax.set_xticks(ticks); ax.set_xticklabels([b.index[i].strftime(fmt) for i in ticks], fontsize=8)
        if z.tf in ("M", "W"): ax.set_yscale("log")
        ax.grid(color=GRID, lw=0.5)
        for s in ax.spines.values(): s.set_visible(False)
    fig.suptitle(title or sym, x=0.01, ha="left", fontsize=13, fontweight="bold")
    plt.tight_layout(rect=(0, 0, 1, 0.98)); plt.savefig(path, dpi=110, facecolor=SURF); plt.close(fig)
