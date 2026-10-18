"""Assemble the full research report (all rounds) into one Arabic RTL HTML and PDF."""
import json
import re
from pathlib import Path

import markdown

R = Path(__file__).resolve().parent.parent  # rebuild/research
OUT = R / "report"


def demote(md: str, drop_title=True, by=1) -> str:
    lines = md.splitlines()
    if drop_title:
        for i, l in enumerate(lines):
            if l.startswith("# "):
                lines.pop(i)
                break
    out = []
    in_code = False
    for l in lines:
        if l.strip().startswith("```"):
            in_code = not in_code
        if not in_code and re.match(r"^#{1,5} ", l):
            l = "#" * by + l
        out.append(l)
    return "\n".join(out)


def section(md: str, start_pat: str, end_pat: str | None) -> str:
    s = md.index(start_pat)
    e = md.index(end_pat, s + 1) if end_pat else len(md)
    return md[s:e]


def read(p):
    return (R / p).read_text(encoding="utf-8")


def round2_table():
    names = {"S0_wave": "S0 الموجات", "S1_tsmom": "S1 TSMOM Calls", "S2_dip_etf": "S2 ارتداد المؤشر (ETF)",
             "S3_52wh": "S3 قمة 52 أسبوعًا", "S4_turtle55": "S4 Turtle-55", "S6_dualmom": "S6 Dual Momentum",
             "S7_nr7": "S7 NR7"}
    rows = ["| الاستراتيجية | الفلاتر المختارة على A | العقد/الخروج المختار على A | الأصل B: n / ربح / عائد | المطوَّر B: n / ربح / عائد / t / PF | المطوَّر A | B فروق ×2 | B بدون الكبار |",
            "|---|---|---|---|---|---|---|---|"]
    lifts = []
    for k, nm in names.items():
        p = R / "results" / "round2" / f"{k}.json"
        if not p.exists():
            continue
        j = json.loads(p.read_text())
        r = j["results"]
        b, e = r["base_B"], r["enh_B"]
        f = lambda x: f"{x * 100:+.1f}%" if isinstance(x, (int, float)) else "—"
        rows.append(f"| {nm} | {', '.join(j['filters']) or 'لا شيء'} | دلتا {j['contract']['delta']}، {j['contract']['dte']} يوم، {j['contract']['exit']} | "
                    f"{int(b['trades'])} / {b.get('win_rate', 0) * 100:.0f}% / {f(b.get('expectancy'))} | "
                    f"{int(e['trades'])} / {e.get('win_rate', 0) * 100:.0f}% / {f(e.get('expectancy'))} / {e.get('t_stat', 0):+.2f} / {e.get('profit_factor', 0):.2f} | "
                    f"{f(r['enh_A'].get('expectancy'))} | {f(r['enh_B_2x'].get('expectancy'))} | {f(r['enh_B_exbig'].get('expectancy'))} |")
        top = j["lifts"][:5]
        lifts.append(f"**{nm}** — أعلى 5 فلاتر (الأثر بالنقاط المئوية في A1 / A2، والتغطية): " +
                     "؛ ".join(f"{c} ({a if a is not None else '—'} / {b_ if b_ is not None else '—'}، {cov:.0%})" for c, a, b_, cov in top))
    return "\n".join(rows) + "\n\n" + "\n\n".join(lifts)


parts = []
parts.append(read("report/00_summary.md"))
parts.append(read("report/01_method.md"))

sr = read("STRATEGY_RESEARCH.md")
prelim = "# الجولة التمهيدية: تشخيص المحركات الحالية وبناء الإطار\n\n" \
         "على بيانات صغيرة حقيقية (AAPL وSPY لعامين) وعلى بيانات اصطناعية للتحقق من الإطار.\n\n" + \
         demote(section(sr, "## 1.", "## 3."), False) + "\n\n" + \
         demote(section(sr, "## 4.", "### 5.3"), False)
parts.append(prelim)

parts.append("# الجولة الأولى (أ): خمس استراتيجيات على أربعة فريمات\n\n" +
             "الدايفرجنس على الموجات، وORB، وارتداد VWAP، وRCB، وTPB، والمحرك المركّب، على فريمات الدقيقة و5 دقائق والساعة واليومي.\n\n" +
             demote(read("FIVE_STRATEGIES_STUDY.md")))
parts.append("# الجولة الأولى (ب): استراتيجيات منشورة، واستراتيجيات مطوّرة، ودراسة مؤكدات الموجات\n\n" +
             demote(read("SIX_STRATEGIES_REPORT.md")))
parts.append("# الجولة الثانية: التطوير المنهجي لكل الاستراتيجيات\n\n" + demote(read("ROUND2_REPORT.md")) +
             "\n\n## تفاصيل الجولة الثانية لكل استراتيجية\n\n" + round2_table())
parts.append(read("report/90_lessons.md"))
parts.append(read("report/95_rules.md"))

appendix = ["# ملحق ب: جداول النتائج الخام (كما أنتجها الكود)"]
for title, p in (("دراسة يومية شاملة: جودة الإشارة، backtest، Walk-Forward، والحساسية (results/d1/RESULTS.md)", "results/d1/RESULTS.md"),
                 ("اليومي بمعاملات ثابتة (results/d1fixed)", "results/d1fixed/RESULTS_INTRADAY.md"),
                 ("الساعة (results/h1)", "results/h1/RESULTS_INTRADAY.md"),
                 ("5 دقائق (results/m5)", "results/m5/RESULTS_INTRADAY.md"),
                 ("دقيقة (results/m1)", "results/m1/RESULTS_INTRADAY.md"),
                 ("الاستراتيجيات المنشورة والجديدة (results/six)", "results/six/RESULTS_SIX.md"),
                 ("دراسة مؤكدات الموجات (results/wave)", "results/wave/RESULTS_WAVE.md")):
    appendix.append(f"## {title}\n\n<div class='raw' markdown='1'>\n\n" + demote(read(p), True, 2) + "\n\n</div>")
parts.append("\n\n".join(appendix))
parts.append("""# ملحق ج: الكود والمصادر

## خريطة الكود (rebuild/research)

| الملف | الوظيفة |
|---|---|
| `fetch_yahoo.py` | تنزيل البيانات |
| `oat_research/data.py` | تحميل البيانات والتحقق منها |
| `oat_research/indicators.py` | المؤشرات السببية والقمم والقيعان |
| `oat_research/options_model.py` | تسعير الخيارات |
| `oat_research/backtest.py` | محاكي المحفظة (القفل، والخروج، وChandelier، ونقل الوقف للتعادل) |
| `oat_research/baseline.py` | نقل حرفي لمحركات التطبيق الحالية |
| `oat_research/engines_v2.py` | بوابة الجودة، وRCB، وTPB |
| `oat_research/intraday.py` | الموجات والدايفرجنس، وORB، وVWAP |
| `oat_research/wave_lab.py` | مختبر مؤكدات الموجات |
| `oat_research/published.py` | الاستراتيجيات المنشورة والمطوّرة |
| `oat_research/features.py` | فلاتر الجولة الثانية |
| `validate_harness.py` | التحقق من خلو الإطار من تسرّب المستقبل |
| `run_study.py`, `run_intraday.py`, `contract_selection.py`, `wave_study.py`, `wave_v2.py`, `run_six.py`, `robustness.py`, `final_six.py`, `round2.py`, `round2_e2.py`, `winrate_tradeoff.py`, `orb_round2.py` | سكربتات الدراسات |

## المصادر
- Moskowitz, Ooi, Pedersen (2012), *Time Series Momentum* — https://papers.ssrn.com/abstract=2089463
- Faber (2007), *A Quantitative Approach to Tactical Asset Allocation* — https://repository.up.ac.za/handle/2263/25223?show=full
- George & Hwang (2004), *The 52-Week High and Momentum Investing* — https://cxoadvisory.com/technical-trading/the-52-week-high-as-a-momentum-indicator-for-individual-stocks
- Connors RSI(2) — https://backtrex.com/en/backtests/connors-rsi-2-sp-500
- Zarattini, Barbon, Aziz (2024), *A Profitable Day Trading Strategy for the U.S. Equity Market* — https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/
- إعادة إنتاج مستقلة لـ ORB — https://www.mql5.com/en/blogs/post/776235
- McConnell & Xu (2008), *Equity Returns at the Turn of the Month* — https://rpc.cfainstitute.org/research/financial-analysts-journal/2008/equity-returns-at-the-turn-of-the-month
- Antonacci, *Dual Momentum* — https://alphaarchitect.com/book-review-dual-momentum-investing/
- Crabel, Narrow Range / NR7 — https://oxfordstrat.com/trading-strategies/narrow-range/
- Moving-average breadth — https://sentimentrader.com/blog/moving-average-breadth
""")

def normalize(md: str) -> str:
    """Make CommonMark-style lists/tables work with Python-Markdown."""
    out, in_code = [], False
    item = re.compile(r"^(\s*)([-*]|\d+\.) ")
    for line in md.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            line = line.lstrip()
        if in_code:
            out.append(line)
            continue
        m = item.match(line)
        if m and 1 <= len(m.group(1)) <= 3:
            line = "    " + line.lstrip()
        if re.match(r"^\s{1,4}\|", line):          # tables nested in list items -> top level
            line = line.lstrip()
            if out and out[-1].strip() and not out[-1].lstrip().startswith("|"):
                out.append("")
        prev = out[-1] if out else ""
        if (m or re.match(r"^\s*([-*]|\d+\.) ", line)) and prev.strip() and not item.match(prev) \
                and not prev.startswith("    ") and not prev.lstrip().startswith("|"):
            out.append("")
        if line.lstrip().startswith("|") and prev.strip() and not prev.lstrip().startswith("|"):
            out.append("")
        out.append(line)
    return "\n".join(out)


md_all = normalize("\n\n<div class='pb'></div>\n\n".join(parts))
html_body = markdown.markdown(md_all, extensions=["tables", "fenced_code", "toc", "md_in_html"], extension_configs={"toc": {"toc_depth": "1-2"}})
toc = markdown.markdown("[TOC]\n\n" + md_all, extensions=["tables", "fenced_code", "toc", "md_in_html"],
                        extension_configs={"toc": {"toc_depth": "1-2"}}).split("</div>")[0] + "</div>"

css = """
@page { size: A4; margin: 16mm 13mm 16mm 13mm; }
body { font-family: 'DejaVu Sans', sans-serif; direction: rtl; font-size: 9.6pt; line-height: 1.6; color: #1d2433; }
h1 { font-size: 17pt; color: #0b4f6c; border-bottom: 2px solid #0b4f6c; padding-bottom: 4px; margin-top: 0; }
h2 { font-size: 13pt; color: #0b4f6c; margin-top: 18px; }
h3 { font-size: 11pt; color: #234; }
h4 { font-size: 10pt; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 7.6pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #c9d3de; padding: 3px 4px; vertical-align: top; unicode-bidi: plaintext; text-align: start; }
th { background: #e8f1f7; }
tr:nth-child(even) td { background: #f8fafc; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 8pt; background: #f1f4f7; padding: 0 2px; direction: ltr; unicode-bidi: embed; }
pre { direction: ltr; text-align: left; background: #f4f6f9; border: 1px solid #dde3ea; padding: 8px; font-size: 7.8pt; white-space: pre-wrap; }
pre code { background: none; }
blockquote { border-right: 4px solid #e0a100; margin: 8px 0; padding: 4px 10px; background: #fff8e6; }
.pb { page-break-after: always; }
.raw { direction: ltr; text-align: left; } .raw table { font-size: 6.6pt; } .raw h2, .raw h3, .raw h4 { text-align: left; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; text-align: center; }
.cover h1 { border: none; font-size: 26pt; }
.cover .sub { font-size: 13pt; color: #456; margin: 6px 0; }
.toc ul { list-style: none; padding-right: 12px; } .toc > ul > li { margin-top: 4px; font-weight: bold; } .toc ul ul li { font-weight: normal; }
a { color: #0b4f6c; text-decoration: none; }
"""
cover = """<div class='cover'><h1>Options AI Trader</h1>
<div class='sub'>التقرير الشامل لدراسات وتطوير استراتيجيات تداول الخيارات</div>
<div class='sub'>الجولة التمهيدية · الجولة الأولى · الجولة الثانية · التوصيات</div>
<div class='sub' style='margin-top:30px;font-size:11pt'>18 أكتوبر 2026 · الفرع rebuild/hybrid-engines-20261018</div>
<div class='sub' style='font-size:10pt'>بيانات حقيقية: Yahoo Finance · 15 رمزًا · 2012–2026 · يومي/ساعة/5 دقائق/دقيقة</div>
</div><div class='pb'></div>"""
html = f"<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><style>{css}</style></head><body>{cover}" \
       f"<h1>المحتويات</h1>{toc}<div class='pb'></div>{html_body}</body></html>"
(OUT / "FULL_REPORT.html").write_text(html, encoding="utf-8")
print("html written", len(html))
