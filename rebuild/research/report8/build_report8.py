"""Round-4 Arabic report -> HTML + PDF.  python report4/build_report4.py"""
import re, subprocess, sys
from pathlib import Path
import markdown
R = Path(__file__).resolve().parent.parent
OUT = R / "report8"
sys.argv = [sys.argv[0]]
src = (R / "report/build_report.py").read_text(encoding="utf-8")
ns = {"re": re}
exec(src[src.index("def normalize"):src.index("md_all =")], ns)          # normalize()
css = re.search(r'css = """(.*?)"""', src, re.S).group(1)
def demote(md, by=1):
    lines = md.splitlines()
    for i, l in enumerate(lines):
        if l.startswith("# "):
            lines.pop(i); break
    out, code = [], False
    for l in lines:
        if l.strip().startswith("```"): code = not code
        if not code and re.match(r"^#{1,5} ", l): l = "#" * by + l
        out.append(l)
    return "\n".join(out)
parts = [(OUT / "10_main.md").read_text(encoding="utf-8")]
app = ["# ملحق: النتائج الخام (results/r7 و results/r8)"]
for f in ("r7/AUDIT", "r7/JUDGE", "r7/DIAG", "r7/DEV", "r8/A", "r8/A_DEV", "r8/B", "r8/B_DEV", "r8/B_NOREGIME", "r8/C", "r8/C_DEV"):
    p = R / "results" / f"{f}.md"
    if p.exists():
        app.append(f"## {f}.md\n\n<div class='raw' markdown='1'>\n\n" + demote(p.read_text(encoding="utf-8"), 2) + "\n\n</div>")
parts.append("\n\n".join(app))
md_all = ns["normalize"]("\n\n<div class='pb'></div>\n\n".join(parts))
ext = ["tables", "fenced_code", "toc", "md_in_html"]
cfg = {"toc": {"toc_depth": "1-2"}}
body = markdown.markdown(md_all, extensions=ext, extension_configs=cfg)
toc = markdown.markdown("[TOC]\n\n" + md_all, extensions=ext, extension_configs=cfg).split("</div>")[0] + "</div>"
cover = """<div class='cover'><h1>Options AI Trader</h1>
<div class='sub'>اختبار مستقل للتقرير الشامل + اختبار وتطوير الدراسة الجديدة (A/B/C)</div>
<div class='sub'>30 سهمًا جديدًا خارج العينة · أسعار عقود حقيقية 2024–2026 · فحص تسرّب المستقبل</div>
<div class='sub' style='margin-top:30px;font-size:11pt'>19 أكتوبر 2026 · الفرع rebuild/hybrid-engines-20261018</div>
<div class='sub' style='font-size:10pt'>Alpaca 5 دقائق 2016–2026 · أسعار عقود حقيقية 2024–2026 · 15 رمزًا</div>
</div><div class='pb'></div>"""
html = f"<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><style>{css}</style></head><body>{cover}<h1>المحتويات</h1>{toc}<div class='pb'></div>{body}</body></html>"
h = OUT / "ROUND8_REPORT.html"
h.write_text(html, encoding="utf-8")
subprocess.run([sys.executable, str(R / "report/to_pdf.py"), str(h), str(OUT / "Options_AI_Trader_Round7-8_Verification.pdf")], check=True)
print("ok")
