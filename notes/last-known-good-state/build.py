#!/usr/bin/env python3
"""Build THE LAST KNOWN GOOD STATE: deck.json -> deck.html -> PDF.

The output follows the shelf format: 1280x720 landscape pages, one idea per
page, and /PageMode /FullScreen for a press-next reading experience.

Usage:
    uv run --with pypdf python build.py
"""

import html
import json
import re
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT_PDF = HERE / "last-known-good-state.pdf"
OUT_HTML = HERE / "deck.html"

PAPER = "#FAF6EE"
INK = "#171310"
NIGHT = "#14110C"
DIM = "#746C63"
BODY = "#4B443C"
ACCENT = "#1F6B50"
ACCENT_BRIGHT = "#93D5B5"
RULE = "rgba(23,19,16,.15)"


CSS = f"""
@font-face {{ font-family:'Bricolage'; src:url('../../fonts/BricolageGrotesque-Bold.ttf'); font-weight:700; }}
@font-face {{ font-family:'Bricolage'; src:url('../../fonts/BricolageGrotesque-Regular.ttf'); font-weight:400; }}
@font-face {{ font-family:'Lora'; src:url('../../fonts/Lora-Regular.ttf'); font-weight:400; }}
@font-face {{ font-family:'Lora'; src:url('../../fonts/Lora-Italic.ttf'); font-weight:400; font-style:italic; }}
@font-face {{ font-family:'Lora'; src:url('../../fonts/Lora-Bold.ttf'); font-weight:700; }}
@font-face {{ font-family:'Plex'; src:url('../../fonts/IBMPlexMono-Regular.ttf'); font-weight:400; }}
@font-face {{ font-family:'Plex'; src:url('../../fonts/IBMPlexMono-Bold.ttf'); font-weight:700; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
@page {{ size:1280px 720px; margin:0; }}
html, body {{ background:{PAPER}; }}
.page {{ width:1280px; height:720px; page-break-after:always; position:relative;
         overflow:hidden; background:{PAPER}; color:{INK}; }}
.kicker {{ position:absolute; top:64px; left:96px; font:400 15px/1 'Plex';
           letter-spacing:.22em; text-transform:uppercase; color:{ACCENT}; }}
.pageno {{ position:absolute; bottom:56px; right:96px; font:400 14px/1 'Plex'; color:{DIM}; }}
.footnote {{ position:absolute; bottom:52px; left:96px; right:220px;
             font:400 14px/1.48 'Plex'; color:{DIM}; }}
.footnote::before {{ content:'* '; color:{ACCENT}; }}
h1 {{ font-family:'Bricolage'; font-weight:700; letter-spacing:-.015em; }}
.body {{ font:400 23px/1.58 'Lora'; color:inherit; }}
.body p + p {{ margin-top:.8em; }}
.mono {{ font-family:'Plex'; }}

table {{ border-collapse:collapse; width:100%; font:400 17px/1.35 'Plex'; }}
th, td {{ text-align:left; padding:15px 14px; border-bottom:1px solid {RULE}; vertical-align:top; }}
thead th {{ font-weight:700; font-size:13px; letter-spacing:.08em; text-transform:uppercase;
            color:{DIM}; border-bottom:2px solid {INK}; }}
tbody tr.subject td {{ background:rgba(31,107,80,.10); }}
tbody tr.subject td:first-child {{ color:{ACCENT}; font-weight:700; }}

.src {{ padding:18px 0; border-top:1px solid {RULE}; }}
.src b {{ font:700 18px/1.25 'Lora'; display:block; }}
.src i {{ font:400 15px/1.35 'Plex'; color:{BODY}; font-style:normal; display:block; margin-top:4px; }}
.src a {{ font:400 13px/1.28 'Plex'; color:{DIM}; text-decoration:none; display:block; margin-top:4px;
          word-break:break-all; }}
"""


def sq(text):
    """Turn plain quotation marks into restrained typographic marks."""
    text = re.sub(r"(\w)'(\w)", r"\1’\2", text)
    text = re.sub(r'"([^"]*)"', "“\\1”", text)
    text = re.sub(r"(?<!\w)'([^']+)'(?!\w)", "‘\\1’", text)
    return text.replace("'", "’")


def esc(text, smart=True):
    out = html.escape(str(text), quote=False)
    return sq(out) if smart else out


def attr(text):
    return html.escape(str(text), quote=True)


def headline_size(text, poster=False):
    n = len(text)
    if poster:
        if n <= 24:
            return 88
        if n <= 40:
            return 72
        return 60
    if n <= 20:
        return 76
    if n <= 34:
        return 64
    if n <= 48:
        return 54
    return 46


def render_body(body):
    return "".join(f"<p>{esc(p)}</p>" for p in body.split("\n\n") if p.strip())


def body_tier(words):
    if words <= 88:
        return 23, 690, 150, 999
    if words <= 112:
        return 21.5, 740, 140, 60
    return 20, 800, 128, 52


def chrome(kicker, content, n, foot="", bg=PAPER, fg=INK, accent=ACCENT):
    k = (
        f'<div class="kicker" style="color:{accent};">{esc(kicker, smart=False)}</div>'
        if kicker
        else ""
    )
    f = f'<div class="footnote">{esc(foot)}</div>' if foot else ""
    page_number_color = DIM if bg == PAPER else "#AAA39A"
    return (
        f'<div class="page" style="background:{bg}; color:{fg};">'
        f'{k}{content}{f}<div class="pageno" style="color:{page_number_color};">{n}</div></div>'
    )


def idea_page(p, n):
    words = len(p["body"].split())
    if p.get("layout") == "compact":
        fs, width, top, headline_cap, headline_gap = 20, 820, 122, 50, 24
    else:
        fs, width, top, headline_cap = body_tier(words)
        headline_gap = 30
    hsize = min(headline_size(p["headline"]), headline_cap)
    content = f"""
    <div style="position:absolute; top:{top}px; left:96px; width:1088px;">
      <h1 style="font-size:{hsize}px; line-height:1.04; margin-bottom:{headline_gap}px; max-width:1088px;">{esc(p['headline'])}</h1>
      <div class="body" style="max-width:{width}px; font-size:{fs}px;">{render_body(p['body'])}</div>
    </div>"""
    return chrome(p.get("kicker"), content, n, p.get("footnote", ""))


def statement_page(kicker, headline, body, n, dark=False):
    bg, fg = (NIGHT, PAPER) if dark else (PAPER, INK)
    accent = ACCENT_BRIGHT if dark else ACCENT
    content = f"""
    <div style="position:absolute; top:180px; left:96px; width:1040px;">
      <h1 style="font-size:{headline_size(headline)}px; line-height:1.05; margin-bottom:34px;">{esc(headline)}</h1>
      <div class="body" style="max-width:700px;">{render_body(body)}</div>
    </div>"""
    return chrome(kicker, content, n, bg=bg, fg=fg, accent=accent)


def cover_page(d):
    lines = "<br>".join(esc(line, smart=False) for line in d["cover_lines"])
    return f"""
    <div class="page">
      <div style="position:absolute; top:0; left:0; width:26px; height:720px; background:{ACCENT};"></div>
      <div style="position:absolute; top:72px; left:96px; font:400 16px/1 'Plex'; letter-spacing:.3em;">{esc(d['series'], smart=False)}</div>
      <div style="position:absolute; top:104px; left:96px; font:400 16px/1 'Plex'; letter-spacing:.3em; color:{ACCENT};">{esc(d['kind'], smart=False)} &middot; {esc(d['date'], smart=False)}</div>
      <div style="position:absolute; top:218px; left:92px; right:70px;">
        <h1 style="font-size:91px; line-height:.92; letter-spacing:-.025em;">{lines}</h1>
      </div>
      <div style="position:absolute; bottom:150px; left:96px; font:italic 400 24px/1.4 'Lora';">by {esc(d['author'], smart=False)}</div>
      <div style="position:absolute; bottom:96px; left:96px; font:400 15px/1 'Plex'; color:{DIM};">{esc(d['subtitle'], smart=False)}</div>
    </div>"""


def map_page(d, n):
    sections = d["sections"]
    midpoint = (len(sections) + 1) // 2
    left, right = sections[:midpoint], sections[midpoint:]

    def column(items):
        return "".join(
            f'<div style="margin-bottom:34px;">'
            f'<span style="font:400 15px/1 \'Plex\'; color:{ACCENT};">{s["section"]:02d}</span>'
            f'<span style="font:700 26px/1.2 \'Bricolage\'; margin-left:18px;">{esc(s["title"], smart=False)}</span>'
            f'</div>'
            for s in items
        )

    content = f"""
    <div style="position:absolute; top:140px; left:96px;"><h1 style="font-size:56px;">{esc(d['map_headline'])}</h1></div>
    <div style="position:absolute; top:266px; left:96px; width:520px;">{column(left)}</div>
    <div style="position:absolute; top:266px; left:660px; width:540px;">{column(right)}</div>"""
    return chrome("the map", content, n)


def divider_page(section, n):
    return f"""
    <div class="page" style="background:{ACCENT}; color:{PAPER};">
      <div style="position:absolute; top:52px; right:88px; font:700 190px/1 'Bricolage'; opacity:.25;">{section['section']:02d}</div>
      <div style="position:absolute; top:74px; left:96px; font:400 15px/1 'Plex'; letter-spacing:.22em;">SECTION {section['section']}</div>
      <div style="position:absolute; bottom:220px; left:96px; right:120px;">
        <h1 style="font-size:84px; line-height:1;">{esc(section['title'], smart=False)}</h1>
      </div>
      <div style="position:absolute; bottom:96px; left:96px; right:300px; font:italic 400 22px/1.5 'Lora'; opacity:.92;">{esc(section['epigraph'])}</div>
      <div class="pageno" style="color:{PAPER}; opacity:.7;">{n}</div>
    </div>"""


def cut_page(p, n):
    content = f"""
    <div style="position:absolute; top:126px; left:96px; width:1088px;">
      <h1 style="font-size:54px; line-height:1.04; max-width:980px;">{esc(p['headline'])}</h1>
    </div>
    <svg viewBox="0 0 1088 250" style="position:absolute; left:96px; top:315px; width:1088px; height:250px;">
      <line x1="40" y1="116" x2="1048" y2="116" stroke="{DIM}" stroke-width="3"/>
      <line x1="512" y1="24" x2="512" y2="216" stroke="{ACCENT}" stroke-width="5"/>
      <circle cx="240" cy="116" r="15" fill="{ACCENT}"/>
      <circle cx="776" cy="116" r="10" fill="{PAPER}" stroke="{ACCENT}" stroke-width="5"/>
      <path d="M1018 101 L1048 116 L1018 131" fill="none" stroke="{ACCENT}" stroke-width="5"/>
      <text x="240" y="76" text-anchor="middle" font-family="Plex" font-size="17" font-weight="700" fill="{INK}">KNOWN GOOD</text>
      <text x="240" y="157" text-anchor="middle" font-family="Plex" font-size="15" fill="{DIM}">anchor + observed proof</text>
      <text x="512" y="236" text-anchor="middle" font-family="Plex" font-size="15" font-weight="700" fill="{ACCENT}">RECOVERY CUT</text>
      <text x="776" y="76" text-anchor="middle" font-family="Plex" font-size="17" font-weight="700" fill="{INK}">WORK IN FLIGHT</text>
      <text x="776" y="157" text-anchor="middle" font-family="Plex" font-size="15" fill="{DIM}">attempted, pending, uncertain</text>
      <text x="1048" y="76" text-anchor="end" font-family="Plex" font-size="17" font-weight="700" fill="{ACCENT}">NEXT</text>
    </svg>
    <div class="body" style="position:absolute; left:96px; top:590px; width:760px; font-size:18px;">{render_body(p['body'])}</div>"""
    return chrome(p.get("kicker"), content, n)


def conditions_page(p, rows, n):
    head = "".join(
        f"<th>{h}</th>"
        for h in ["Condition", "Visible memory", "Search cost", "Live edges", "Transfer"]
    )
    body = ""
    for i, row in enumerate(rows):
        cls = ' class="subject"' if i == 3 else ""
        body += f"<tr{cls}>" + "".join(f"<td>{esc(cell, smart=False)}</td>" for cell in row) + "</tr>"
    content = f"""
    <div style="position:absolute; top:126px; left:96px; right:96px;">
      <h1 style="font-size:52px; line-height:1.04; margin-bottom:38px;">{esc(p['headline'])}</h1>
      <table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
    </div>"""
    return chrome(p.get("kicker"), content, n)


def packet_page(p, fields, n):
    cards = []
    for number, title, description in fields:
        cards.append(
            f'<div style="border-top:2px solid {INK}; padding:13px 4px 0; min-height:86px;">'
            f'<div style="font:700 13px/1 \'Plex\'; color:{ACCENT}; letter-spacing:.12em;">{esc(number, smart=False)}</div>'
            f'<div style="font:700 22px/1.12 \'Bricolage\'; margin-top:8px;">{esc(title, smart=False)}</div>'
            f'<div style="font:400 14px/1.38 \'Plex\'; color:{BODY}; margin-top:7px;">{esc(description, smart=False)}</div>'
            f'</div>'
        )
    content = f"""
    <div style="position:absolute; top:118px; left:96px; right:96px;">
      <h1 style="font-size:52px; line-height:1.04; margin-bottom:34px;">{esc(p['headline'])}</h1>
      <div style="display:grid; grid-template-columns:1fr 1fr; column-gap:58px; row-gap:18px;">{''.join(cards)}</div>
    </div>"""
    return chrome(p.get("kicker"), content, n)


def omissions_page(p, rows, n):
    cards = []
    for missing, failure in rows:
        cards.append(
            f'<div style="display:grid; grid-template-columns:135px 28px 1fr; align-items:center; border-top:1px solid {RULE}; padding:17px 0;">'
            f'<div style="font:700 17px/1.2 \'Plex\'; color:{ACCENT};">{esc(missing, smart=False)}</div>'
            f'<div style="font:700 18px/1 \'Plex\'; color:{DIM};">-&gt;</div>'
            f'<div style="font:400 17px/1.32 \'Lora\';">{esc(failure, smart=False)}</div>'
            f'</div>'
        )
    content = f"""
    <div style="position:absolute; top:118px; left:96px; right:96px;">
      <h1 style="font-size:50px; line-height:1.04; margin-bottom:30px;">{esc(p['headline'])}</h1>
      <div style="display:grid; grid-template-columns:1fr 1fr; column-gap:64px;">{''.join(cards)}</div>
    </div>"""
    return chrome(p.get("kicker"), content, n)


SOURCES_PER_PAGE = 4


def source_pages(p, sources, n):
    chunks = [sources[i : i + SOURCES_PER_PAGE] for i in range(0, len(sources), SOURCES_PER_PAGE)]
    pages = []
    for index, chunk in enumerate(chunks):
        rows = "".join(
            f'<div class="src"><b>{esc(author, smart=False)}</b><i>{esc(title, smart=False)}</i><a href="{attr("https://" + url)}">{esc(url, smart=False)}</a></div>'
            for author, title, url in chunk
        )
        headline = esc(p["headline"]) if index == 0 else "Sources, continued."
        kicker = p.get("kicker") if index == 0 else f'{p.get("kicker")} {index + 1} of {len(chunks)}'
        content = f"""
        <div style="position:absolute; top:112px; left:96px; right:96px;">
          <h1 style="font-size:46px; line-height:1.04;">{headline}</h1>
          <div style="margin-top:30px;">{rows}</div>
        </div>"""
        pages.append(chrome(kicker, content, n + index))
    return pages


def build():
    data = json.loads((HERE / "deck.json").read_text(encoding="utf-8"))
    pages = [cover_page(data)]
    page_number = 2

    pages.append(statement_page("this note is free", "Take it. Give it away.", data["free_page"], page_number))
    page_number += 1
    pages.append(statement_page("how to read this", "Full screen. Press next.", data["how_to_read"], page_number))
    page_number += 1
    pages.append(statement_page("the boundary", "A bounded claim.", data["disclaimer"], page_number))
    page_number += 1
    pages.append(map_page(data, page_number))
    page_number += 1

    for section in data["sections"]:
        pages.append(divider_page(section, page_number))
        page_number += 1
        for page in section["pages"]:
            kind = page.get("type", "idea")
            if kind == "cut":
                pages.append(cut_page(page, page_number))
            elif kind == "conditions":
                pages.append(conditions_page(page, data["conditions"], page_number))
            elif kind == "packet":
                pages.append(packet_page(page, data["packet"], page_number))
            elif kind == "omissions":
                pages.append(omissions_page(page, data["omissions"], page_number))
            elif kind == "sources":
                source_set = source_pages(page, data["sources"], page_number)
                pages.extend(source_set)
                page_number += len(source_set) - 1
            elif kind == "statement":
                pages.append(
                    statement_page(
                        page.get("kicker", ""),
                        page["headline"],
                        page["body"],
                        page_number,
                        dark=page.get("dark", False),
                    )
                )
            else:
                pages.append(idea_page(page, page_number))
            page_number += 1

    pages.append(statement_page("the author", "Who wrote this?", data["about"], page_number))
    page_number += 1
    pages.append(statement_page("one last thing", "Pass it on.", data["share"], page_number, dark=True))

    document = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{esc(data['title'], smart=False)}: {esc(data['subtitle'], smart=False)}</title>"
        f"<style>{CSS}</style></head><body>{''.join(pages)}</body></html>"
    )
    OUT_HTML.write_text(document, encoding="utf-8")

    subprocess.run(
        [
            CHROME,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={OUT_PDF}",
            f"file://{OUT_HTML}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    reader = PdfReader(str(OUT_PDF))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.metadata = {
        "/Title": f"{data['title']}: {data['subtitle']}",
        "/Author": data["author"],
        "/Subject": "A recovery protocol for interrupted work",
        "/Creator": "",
        "/Producer": "",
    }
    writer._root_object[NameObject("/PageMode")] = NameObject("/FullScreen")
    with OUT_PDF.open("wb") as stream:
        writer.write(stream)

    print(f"{len(reader.pages)} pages -> {OUT_PDF.name} (FullScreen set)")


if __name__ == "__main__":
    build()
