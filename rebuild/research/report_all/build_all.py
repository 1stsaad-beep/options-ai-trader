"""Master PDF: catalog + all round reports. python report_all/build_all.py"""
import re, subprocess, sys
from pathlib import Path
import markdown
from pypdf import PdfReader, PdfWriter
R = Path(__file__).resolve().parent.parent
OUT = R / "report_all"
src = (R / "report/build_report.py").read_text(encoding="utf-8")
ns = {"re": re}
exec(src[src.index("def normalize"):src.index("md_all =")], ns)
css = re.search(r'css = """(.*?)"""', src, re.S).group(1)
md_all = ns["normalize"]((OUT / "00_catalog.md").read_text(encoding="utf-8"))
ext = ["tables", "fenced_code", "toc", "md_in_html"]
body = markdown.markdown(md_all, extensions=ext)
cover = """<div class='cover'><h1>Options AI Trader</h1>
<div class='sub'>التقرير الشامل لكل جولات البحث (0 → 5)</div>
<div class='sub'>دليل وفهرس كل الاستراتيجيات · تقارير الجولات كاملة · نتائج بأسعار خيارات حقيقية</div>
<div class='sub' style='margin-top:30px;font-size:11pt'>18 أكتوبر 2026 · github.com/1stsaad-beep/options-ai-trader · rebuild/hybrid-engines-20261018</div>
</div><div class='pb'></div>"""
h = OUT / "catalog.html"
h.write_text(f"<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><style>{css}</style></head><body>{cover}{body}</body></html>", encoding="utf-8")
subprocess.run([sys.executable, str(R / "report/to_pdf.py"), str(h), str(OUT / "catalog.pdf")], check=True)
parts = [OUT / "catalog.pdf", R / "report/Options_AI_Trader_Research_Report.pdf", Path(sys.argv[1]),
         R / "report4/Options_AI_Trader_Round4_Report.pdf", R / "report5/Options_AI_Trader_Round5_Report.pdf"]
w = PdfWriter()
for p in parts:
    for pg in PdfReader(str(p)).pages:
        w.add_page(pg)
with open(OUT / "Options_AI_Trader_ALL_ROUNDS_Report.pdf", "wb") as f:
    w.write(f)
print(sum(len(PdfReader(str(p)).pages) for p in parts))
