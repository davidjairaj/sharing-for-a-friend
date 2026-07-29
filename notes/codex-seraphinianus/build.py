#!/usr/bin/env python3
"""Build the CODEX SERAPHINIANUS note: deck.json -> deck.html -> PDF.

Same format as the CONVERSATIONS WITH CLAUDE volumes: 1280x720 landscape pages,
one idea per page, press next, /PageMode /FullScreen set so it opens full screen.

Usage: python3 build.py
"""
import json, html, re, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT_PDF = HERE / "codex-seraphinianus-analysis.pdf"
OUT_HTML = HERE / "deck.html"

PAPER = "#FAF6EE"
INK = "#171310"
NIGHT = "#14110C"
DIM = "#8A8177"
ACCENT = "#6B3FA0"
ACCENT_BRIGHT = "#C9A6F0"

CSS = f"""
@font-face {{ font-family:'Bricolage'; src:url('../../fonts/BricolageGrotesque-Bold.ttf'); font-weight:700; }}
@font-face {{ font-family:'Bricolage'; src:url('../../fonts/BricolageGrotesque-Regular.ttf'); font-weight:400; }}
@font-face {{ font-family:'Lora'; src:url('../../fonts/Lora-Regular.ttf'); font-weight:400; }}
@font-face {{ font-family:'Lora'; src:url('../../fonts/Lora-Italic.ttf'); font-weight:400; font-style:italic; }}
@font-face {{ font-family:'Lora'; src:url('../../fonts/Lora-Bold.ttf'); font-weight:700; }}
@font-face {{ font-family:'Plex'; src:url('../../fonts/IBMPlexMono-Regular.ttf'); font-weight:400; }}
@font-face {{ font-family:'Plex'; src:url('../../fonts/IBMPlexMono-Bold.ttf'); font-weight:700; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
@page {{ size: 1280px 720px; margin: 0; }}
html, body {{ background:{PAPER}; }}
.page {{ width:1280px; height:720px; page-break-after:always; position:relative;
        overflow:hidden; background:{PAPER}; color:{INK}; }}
.kicker {{ position:absolute; top:64px; left:96px; font:400 15px/1 'Plex';
          letter-spacing:0.22em; text-transform:uppercase; color:{ACCENT}; }}
.pageno {{ position:absolute; bottom:56px; right:96px; font:400 14px/1 'Plex'; color:{DIM}; }}
.footnote {{ position:absolute; bottom:52px; left:96px; right:220px;
            font:400 14.5px/1.5 'Plex'; color:{DIM}; }}
.footnote::before {{ content:'* '; color:{ACCENT}; }}
h1 {{ font-family:'Bricolage'; font-weight:700; letter-spacing:-0.015em; }}
.body {{ font:400 23px/1.58 'Lora'; }}
.body p + p {{ margin-top:0.8em; }}

table {{ border-collapse:collapse; width:100%; font:400 19px/1.4 'Plex'; }}
th, td {{ text-align:right; padding:16px 20px; border-bottom:1px solid rgba(23,19,16,.14); }}
th:first-child, td:first-child {{ text-align:left; }}
thead th {{ font-weight:700; font-size:14.5px; letter-spacing:.06em; text-transform:uppercase;
           color:{DIM}; border-bottom:2px solid {INK}; vertical-align:bottom; }}
tbody tr.subject td {{ background:rgba(107,63,160,.10); font-weight:700; }}
tbody tr.subject td:first-child {{ color:{ACCENT}; }}

.ct {{ font:700 15px 'Plex'; letter-spacing:.12em; text-transform:uppercase; fill:{INK}; }}
.cu {{ font:400 14px 'Plex'; fill:{DIM}; }}
.cl {{ font:400 15px 'Plex'; fill:#4b443c; }}
.cl.sub {{ font-weight:700; fill:{ACCENT}; }}
.cv {{ font:700 15px 'Plex'; fill:{INK}; }}

.src {{ padding:14px 0; border-top:1px solid rgba(23,19,16,.14); }}
.src b {{ font:700 17px/1.3 'Lora'; display:block; }}
.src i {{ font:400 14.5px/1.35 'Plex'; color:#4b443c; font-style:normal; display:block; margin-top:4px; }}
.src u {{ font:400 13px/1.3 'Plex'; color:{DIM}; text-decoration:none; display:block; margin-top:3px;
         word-break:break-all; }}
"""


def sq(text):
    """Straight quotes to typographic quotes and apostrophes."""
    text = re.sub(r"(\w)'(\w)", r"\1’\2", text)
    text = re.sub(r'"([^"]*)"', "“\\1”", text)
    text = re.sub(r"(?<!\w)'([^']+)'(?!\w)", "‘\\1’", text)
    return text.replace("'", "’")


def esc(text, smart=True):
    out = html.escape(text, quote=False)
    return sq(out) if smart else out


def headline_size(text, poster=False):
    n = len(text)
    if poster:
        if n <= 24: return 88
        if n <= 40: return 72
        return 60
    if n <= 20: return 76
    if n <= 34: return 64
    if n <= 48: return 54
    return 46


def render_body(body):
    return "".join(f"<p>{esc(p)}</p>" for p in body.split("\n\n") if p.strip())


def body_tier(words):
    """Font size, column width, top offset, headline cap, tiered by body length."""
    if words <= 90:  return 23, 680, 150, 999
    if words <= 115: return 21.5, 730, 140, 60
    return 20, 780, 128, 52


def chrome(kicker, content, n, foot="", bg=PAPER, fg=INK, accent=ACCENT):
    k = f'<div class="kicker" style="color:{accent};">{esc(kicker, smart=False)}</div>' if kicker else ""
    f = f'<div class="footnote">{esc(foot)}</div>' if foot else ""
    return (f'<div class="page" style="background:{bg}; color:{fg};">'
            f'{k}{content}{f}<div class="pageno">{n}</div></div>')


def idea_page(p, n):
    words = len(p["body"].split())
    fs, w, top, hcap = body_tier(words)
    hsize = min(headline_size(p["headline"]), hcap)
    content = f"""
    <div style="position:absolute; top:{top}px; left:96px; width:1088px;">
      <h1 style="font-size:{hsize}px; line-height:1.04; margin-bottom:30px; max-width:1088px;">{esc(p["headline"])}</h1>
      <div class="body" style="max-width:{w}px; font-size:{fs}px;">{render_body(p["body"])}</div>
    </div>"""
    return chrome(p.get("kicker"), content, n, p.get("footnote", ""))


def statement_page(kicker, headline, body, n, dark=False):
    bg, fg = (NIGHT, PAPER) if dark else (PAPER, INK)
    accent = ACCENT_BRIGHT if dark else ACCENT
    content = f"""
    <div style="position:absolute; top:180px; left:96px; width:1040px;">
      <h1 style="font-size:{headline_size(headline)}px; line-height:1.05; margin-bottom:34px;">{esc(headline)}</h1>
      <div class="body" style="max-width:680px;">{render_body(body)}</div>
    </div>"""
    return chrome(kicker, content, n, bg=bg, fg=fg, accent=accent)


def cover_page(d):
    return f"""
    <div class="page">
      <div style="position:absolute; top:0; left:0; width:26px; height:720px; background:{ACCENT};"></div>
      <div style="position:absolute; top:72px; left:96px; font:400 16px/1 'Plex'; letter-spacing:0.3em;">{d["series"]}</div>
      <div style="position:absolute; top:104px; left:96px; font:400 16px/1 'Plex'; letter-spacing:0.3em; color:{ACCENT};">{d["kind"]} &middot; {d["date"]}</div>
      <div style="position:absolute; top:250px; left:92px; right:80px;">
        <h1 style="font-size:112px; line-height:0.98; letter-spacing:-0.02em;">CODEX<br>SERAPHINIANUS</h1>
      </div>
      <div style="position:absolute; bottom:150px; left:96px; font:italic 400 24px/1.4 'Lora';">by {d["author"]}</div>
      <div style="position:absolute; bottom:96px; left:96px; font:400 15px/1 'Plex'; color:{DIM};">{esc(d["subtitle"], smart=False)}</div>
    </div>"""


def map_page(sections, n):
    left, right = sections[:4], sections[4:]
    def col(items):
        return "".join(
            f'<div style="margin-bottom:34px;">'
            f'<span style="font:400 15px/1 \'Plex\'; color:{ACCENT};">{s["section"]:02d}</span>'
            f'<span style="font:700 26px/1.2 \'Bricolage\'; margin-left:18px;">{esc(s["title"], smart=False)}</span>'
            f"</div>" for s in items)
    content = f"""
    <div style="position:absolute; top:140px; left:96px;"><h1 style="font-size:56px;">Seven doors.</h1></div>
    <div style="position:absolute; top:266px; left:96px; width:520px;">{col(left)}</div>
    <div style="position:absolute; top:266px; left:660px; width:540px;">{col(right)}</div>"""
    return chrome("the map", content, n)


def divider_page(s, n):
    return f"""
    <div class="page" style="background:{ACCENT}; color:{PAPER};">
      <div style="position:absolute; top:52px; right:88px; font:700 190px/1 'Bricolage'; opacity:0.28;">{s["section"]:02d}</div>
      <div style="position:absolute; top:74px; left:96px; font:400 15px/1 'Plex'; letter-spacing:0.22em;">SECTION {s["section"]}</div>
      <div style="position:absolute; bottom:220px; left:96px; right:120px;">
        <h1 style="font-size:84px; line-height:1.0;">{esc(s["title"], smart=False)}</h1>
      </div>
      <div style="position:absolute; bottom:96px; left:96px; right:300px;
                  font:italic 400 22px/1.5 'Lora'; opacity:0.92;">{esc(s["epigraph"])}</div>
      <div class="pageno" style="color:{PAPER}; opacity:0.7;">{n}</div>
    </div>"""


def table_page(p, t, n):
    head = "".join(f"<th>{esc(h, smart=False)}</th>" for h in t["head"])
    rows = ""
    for i, r in enumerate(t["rows"]):
        cls = ' class="subject"' if i == t["subject"] else ""
        rows += f"<tr{cls}>" + "".join(f"<td>{esc(c, smart=False)}</td>" for c in r) + "</tr>"
    content = f"""
    <div style="position:absolute; top:132px; left:96px; right:96px;">
      <h1 style="font-size:{headline_size(p["headline"])}px; line-height:1.04; margin-bottom:14px;">{esc(p["headline"])}</h1>
      <div style="font:400 15px/1 'Plex'; color:{DIM}; letter-spacing:.1em; text-transform:uppercase;
                  margin-bottom:30px;">{esc(t["caption"], smart=False)}</div>
      <table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>
    </div>"""
    return chrome(p.get("kicker"), content, n, p.get("footnote", ""))


def _bar(x1, y, fill):
    """Horizontal bar from x=128, 4px rounded on the far end."""
    return (f'<path fill="{fill}" d="M128,{y} H{x1-4:.1f} A4,4 0 0 1 {x1:.1f},{y+4} '
            f'V{y+16} A4,4 0 0 1 {x1-4:.1f},{y+20} H128 Z"/>')


def _pane(title, unit, rows, vmax):
    """One small bar chart. rows = [(label, value, text, is_subject)]."""
    out = [f'<text class="ct" x="0" y="12">{title}</text>',
           f'<text class="cu" x="0" y="30">{unit}</text>',
           '<line x1="128" y1="44" x2="128" y2="156" stroke="rgba(23,19,16,.22)" stroke-width="1"/>']
    for i, (label, value, text, subject) in enumerate(rows):
        y = 52 + i * 38
        x1 = 128 + (268 * value / vmax)
        cls = "cl sub" if subject else "cl"
        fill = ACCENT if subject else DIM
        out.append(f'<text class="{cls}" x="118" y="{y+13.5}" text-anchor="end">{label}</text>')
        out.append(_bar(x1, y, fill))
        out.append(f'<text class="cv" x="{x1+13:.1f}" y="{y+14.5}">{text}</text>')
    return ('<svg viewBox="0 0 460 176" style="width:100%; height:auto; display:block;">'
            + "".join(out) + "</svg>")


def chart_page(p, n):
    entropy = _pane("Next-character entropy", "bits, lower is more predictable",
                    [("Codex", 1.96, "1.96 bits", True), ("Alice", 3.07, "3.07 bits", False),
                     ("Dante", 2.98, "2.98 bits", False)], 3.5)
    repeats = _pane("Adjacent exact repeats", "percent of tokens",
                    [("Codex", 0.72, "0.72%", True), ("Alice", 0.19, "0.19%", False),
                     ("Dante", 0.05, "0.05%", False)], 0.8)
    content = f"""
    <div style="position:absolute; top:150px; left:96px; width:470px;">
      <h1 style="font-size:46px; line-height:1.04; margin-bottom:26px;">{esc(p["headline"])}</h1>
      <div class="body" style="font-size:19px; line-height:1.55;">{render_body(p["body"])}</div>
    </div>
    <div style="position:absolute; top:150px; left:640px; width:544px;">
      {entropy}<div style="height:34px;"></div>{repeats}
    </div>"""
    return chrome(p.get("kicker"), content, n, p.get("footnote", ""))


PER_SOURCE_PAGE = 5


def sources_pages(p, sources, n):
    """Full-width rows, five to a page, so no URL wraps and nothing clips."""
    chunks = [sources[i:i + PER_SOURCE_PAGE] for i in range(0, len(sources), PER_SOURCE_PAGE)]
    out = []
    for i, chunk in enumerate(chunks):
        rows = "".join(
            f'<div class="src"><b>{esc(a, smart=False)}</b><i>{esc(b, smart=False)}</i>'
            f'<u>{esc(c, smart=False)}</u></div>' for a, b, c in chunk)
        head = esc(p["headline"]) if i == 0 else "Sources, continued."
        kicker = p.get("kicker") if i == 0 else f'{p.get("kicker")} {i + 1} of {len(chunks)}'
        content = f"""
        <div style="position:absolute; top:118px; left:96px;">
          <h1 style="font-size:46px; line-height:1.04;">{head}</h1>
        </div>
        <div style="position:absolute; top:200px; left:96px; right:96px;">{rows}</div>"""
        out.append(chrome(kicker, content, n + i))
    return out


def build():
    d = json.loads((HERE / "deck.json").read_text())
    pages = [cover_page(d)]
    n = 2
    pages.append(statement_page("this note is free", "Take it. Give it away.", d["free_page"], n)); n += 1
    pages.append(statement_page("how to read this", "Full screen. Press next.", d["how_to_read"], n)); n += 1
    pages.append(statement_page("the fine print", "Not the author of the book.", d["disclaimer"], n)); n += 1
    pages.append(map_page(d["sections"], n)); n += 1

    for s in d["sections"]:
        pages.append(divider_page(s, n)); n += 1
        for p in s["pages"]:
            kind = p.get("type", "idea")
            if kind == "table":
                pages.append(table_page(p, d["table"], n))
            elif kind == "chart":
                pages.append(chart_page(p, n))
            elif kind == "sources":
                sp = sources_pages(p, d["sources"], n)
                pages.extend(sp)
                n += len(sp) - 1
            elif kind == "statement":
                pages.append(statement_page(p["kicker"], p["headline"], p["body"], n, dark=p.get("dark", False)))
            else:
                pages.append(idea_page(p, n))
            n += 1

    pages.append(statement_page("the author", "Who wrote this?", d["about"], n)); n += 1
    pages.append(statement_page("one last thing", "Pass it on.", d["share"], n, dark=True)); n += 1

    doc = (f"<!doctype html><html><head><meta charset='utf-8'>"
           f"<title>{d['title']}: {d['subtitle']}</title><style>{CSS}</style></head>"
           f"<body>{''.join(pages)}</body></html>")
    OUT_HTML.write_text(doc)

    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={OUT_PDF}", f"file://{OUT_HTML}"],
                   check=True, capture_output=True)

    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject
    reader = PdfReader(str(OUT_PDF))
    writer = PdfWriter()
    writer.append(reader)
    writer.add_metadata({"/Title": f"{d['title']}: {d['subtitle']}", "/Author": d["author"]})
    writer._root_object[NameObject("/PageMode")] = NameObject("/FullScreen")
    with open(OUT_PDF, "wb") as fh:
        writer.write(fh)
    print(f"{len(reader.pages)} pages -> {OUT_PDF.name} (FullScreen set)")


if __name__ == "__main__":
    build()
