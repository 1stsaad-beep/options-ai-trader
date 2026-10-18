import asyncio, sys
from playwright.async_api import async_playwright
async def main(src, dst):
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"])
        pg = await b.new_page()
        await pg.goto("file://" + src, wait_until="load")
        await pg.pdf(path=dst, format="A4", print_background=True, display_header_footer=True,
                     header_template="<div></div>",
                     footer_template="<div style='font-size:8px;width:100%;text-align:center;color:#666;font-family:DejaVu Sans'>Options AI Trader — <span class='pageNumber'></span> / <span class='totalPages'></span></div>",
                     margin={"top": "14mm", "bottom": "16mm", "left": "12mm", "right": "12mm"})
        await b.close()
asyncio.run(main(sys.argv[1], sys.argv[2]))
