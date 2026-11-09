"""Notlar ve vurgular raporu: belgedeki vurgular, altı/üstü çizili yerler ve notlar, sayfa numaralarıyla tek bir
Word ya da PDF belgesine dökülür (bir dosyayı inceledikten sonra rapor ya da dilekçe yazarken kullanılır)."""

import html
import io
from datetime import date
from pathlib import Path

import pymupdf

import editor
import fonts
import tools

LABELS = {"Highlight": "Vurgu", "Underline": "Altı çizili", "StrikeOut": "Üstü çizili",
          "Text": "Not", "FreeText": "Metin kutusu"}
MARKS = ("Highlight", "Underline", "StrikeOut")
NOTES = ("Text", "FreeText")

# Renge göre gruplarken işaret rengine en yakın ad
COLOR_NAMES = [("Sarı", (255, 225, 77)), ("Yeşil", (142, 240, 160)), ("Mavi", (143, 211, 255)), ("Pembe", (255, 163, 209)),
               ("Kırmızı", (214, 69, 61)), ("Turuncu", (255, 153, 0)), ("Mor", (150, 90, 200)), ("Lacivert", (29, 78, 216)),
               ("Koyu yeşil", (31, 138, 76)), ("Gri", (150, 150, 150)), ("Siyah", (17, 17, 17))]


def color_name(rgb):
    return min(COLOR_NAMES, key=lambda c: sum((a - b) ** 2 for a, b in zip(c[1], rgb)))[0]


def collect(doc, marks=True, notes=True):
    """Belgedeki işaretler, okunma sırasıyla: [{page, kind, label, quote, note, color (#rrggbb), color_name, image}].
    Metni okunamayan (taranmış sayfadaki) işaretin yerine işaretli yerin görüntüsü konur: image (png, genişlik, yükseklik pt)."""
    kinds = (MARKS if marks else ()) + (NOTES if notes else ())
    items = []
    for i, page in enumerate(doc):
        m = page.rotation_matrix
        for a in page.annots():
            kind = a.type[1]
            if kind not in kinds:
                continue
            r = (a.rect * m).normalize()
            stroke = (a.colors or {}).get("stroke") or (1, 0.85, 0.2)
            rgb = tuple(int(c * 255) for c in stroke[:3])
            note = a.info.get("content", "").strip()
            quote = editor.annot_quote(page, a)
            if kind == "FreeText" and not note:
                note = quote
            image = None
            if kind in MARKS and not quote:
                clip = (r + (-2, -1, 2, 1)) & page.rect
                if not clip.is_empty:
                    image = (page.get_pixmap(clip=clip, dpi=150).tobytes("png"), clip.width, clip.height)
            if not (quote or note or image):
                continue
            items.append({"page": i, "kind": kind, "label": LABELS[kind], "quote": quote, "note": note, "image": image,
                          "color": "#%02x%02x%02x" % rgb, "color_name": color_name(rgb), "_at": (i, round(r.y0), r.x0)})
    items.sort(key=lambda it: it.pop("_at"))
    return items


def groups(items, by="page"):
    """[(başlık, işaretler)]: sayfa sayfa ya da renk renk (renkler belgede ilk geçtikleri sırayla)."""
    out = {}
    for it in items:
        key = f"Sayfa {it['page'] + 1}" if by == "page" else it["color_name"]
        out.setdefault(key, []).append(it)
    return list(out.items())


def summary(items):
    marks = sum(it["kind"] in MARKS for it in items)
    notes = len(items) - marks
    parts = ([f"{marks} işaret"] if marks else []) + ([f"{notes} not"] if notes else [])
    return " ve ".join(parts) or "İşaret yok"


def _heading(name, pages):
    return f"{name} · {pages} sayfa · {date.today().strftime('%d.%m.%Y')}"


def to_docx(items, name, pages, dst, by="page"):
    from docx import Document
    from docx.enum.text import WD_UNDERLINE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    grey = RGBColor(0x6b, 0x72, 0x80)
    d = Document()
    for style in ("Normal", "Heading 1", "Heading 2"):
        d.styles[style].font.name = "Arial"
    d.styles["Normal"].font.size = Pt(11)
    d.add_heading("Notlar ve vurgular", level=1)
    p = d.add_paragraph()
    p.add_run(_heading(name, pages)).font.color.rgb = grey
    p.add_run("\n" + summary(items)).font.color.rgb = grey

    def shade(run, color):   # vurgu rengi zemin olarak
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), color.lstrip("#"))
        run._r.get_or_add_rPr().append(shd)

    for title, group in groups(items, by):
        d.add_heading(title, level=2)
        for it in group:
            p = d.add_paragraph()
            p.paragraph_format.space_after = Pt(2 if it["quote"] and it["note"] else 8)
            tag = p.add_run((f"s. {it['page'] + 1} · " if by != "page" else "") + it["label"] + "   ")
            tag.font.size, tag.font.color.rgb, tag.bold = Pt(8.5), grey, True
            if it["image"]:   # taranmış sayfa: işaretli yerin görüntüsü
                png, w, _ = it["image"]
                p.add_run().add_picture(io.BytesIO(png), width=Pt(min(w, 430)))
                if it["note"]:
                    p = d.add_paragraph()
                    p.paragraph_format.left_indent = Pt(18)
                    p.paragraph_format.space_after = Pt(8)
                    p.add_run("Not: ").bold = True
            elif it["kind"] in MARKS and it["quote"]:
                q = p.add_run(f"“{it['quote']}”")
                if it["kind"] == "Highlight":
                    shade(q, it["color"])
                elif it["kind"] == "Underline":
                    q.font.underline = WD_UNDERLINE.SINGLE
                else:
                    q.font.strike = True
                if it["note"]:
                    p = d.add_paragraph()
                    p.paragraph_format.left_indent = Pt(18)
                    p.paragraph_format.space_after = Pt(8)
                    p.add_run("Not: ").bold = True
            elif it["kind"] in MARKS:
                p.add_run("Not: ").bold = True
            p.add_run(it["note"])
    d.save(dst)


PAGE = pymupdf.paper_rect("a4")
CSS = """
body { font-family: 'Arial'; font-size: 10.5pt; line-height: 1.35; }
h1 { font-size: 18pt; margin: 0 0 4pt 0; }
h2 { font-size: 12.5pt; margin: 14pt 0 4pt 0; }
.meta { color: #6b7280; font-size: 9.5pt; margin: 0 0 6pt 0; }
.item { margin: 0 0 8pt 0; }
.tag { color: #6b7280; font-size: 8.5pt; font-weight: bold; }
.note { margin: 2pt 0 0 14pt; }
"""


def _story_pdf(html_text, css, archive, where):
    """Story → bellekte PDF (A4)."""
    story = pymupdf.Story(html=html_text, user_css=css, archive=archive)
    data = io.BytesIO()
    writer = pymupdf.DocumentWriter(data)
    more, count = 1, 0
    while more and count < 2000:
        device = writer.begin_page(PAGE)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
        count += 1
    writer.close()
    return pymupdf.open("pdf", data.getvalue())


def to_pdf(items, name, pages, dst, cache_dir=Path("."), by="page"):
    esc = html.escape
    archive, faces = fonts.story_faces({"Arial"}, cache_dir)
    where = PAGE + (56, 56, -56, -64)
    out = [f"<h1>Notlar ve vurgular</h1><p class='meta'>{esc(_heading(name, pages))}<br>{esc(summary(items))}</p>"]
    widths = []   # taranmış sayfa görüntülerinin genişlikleri, sırayla
    for title, group in groups(items, by):
        out.append(f"<h2>{esc(title)}</h2>")
        for it in group:
            tag = (f"s. {it['page'] + 1} · " if by != "page" else "") + it["label"]
            body, mark = "", ""
            if it["image"]:   # taranmış sayfa: işaretli yerin görüntüsü
                png, w, h = it["image"]
                img = f"isaret{len(out)}.png"
                archive.add((png, img))
                shown = min(w, 430, where.height * 0.6 * w / h)
                mark = f" data-k='{len(widths)}'"
                widths.append(shown)
                body = f"<br><img src='{img}' width='{shown:.0f}'>"
                if it["note"]:
                    body += f"</p><p class='note'><b>Not:</b> {esc(it['note'])}"
            elif it["kind"] in MARKS and it["quote"]:
                style = {"Highlight": f"background-color:{it['color']}", "Underline": "text-decoration:underline",
                         "StrikeOut": "text-decoration:line-through"}[it["kind"]]
                body = f"<span style='{style}'>“{esc(it['quote'])}”</span>"
                if it["note"]:
                    body += f"</p><p class='note'><b>Not:</b> {esc(it['note'])}"
            else:
                body = (f"<b>Not:</b> " if it["kind"] in MARKS else "") + esc(it["note"])
            out.append(f"<div class='item'{mark}><p><span class='tag'>{esc(tag)}</span>&#160;&#160; {body}</p></div>")
    # Sayfa sonuna sığmayan görüntüyü MuPDF küçültür: o işaret sonraki sayfadan başlatılıp yeniden dizilir
    breaks = set()
    for _ in range(8):
        text = "".join(f"<div style='page-break-before: always'></div>{part}"
                       if any(f"data-k='{k}'>" in part for k in breaks) else part for part in out)
        pdf = _story_pdf(f"<body>{text}</body>", faces + CSS, archive, where)
        shown = [pymupdf.Rect(i["bbox"]).width for page in pdf
                 for i in sorted(page.get_image_info(), key=lambda i: i["bbox"][1])]
        more = {k for k, (got, want) in enumerate(zip(shown, widths)) if got < want * 0.85} - breaks
        if len(shown) != len(widths) or not more:
            break
        breaks |= more
    for n, page in enumerate(pdf, 1):   # sayfa numarası
        label = f"{n} / {pdf.page_count}"
        page.insert_text((PAGE.width / 2 - pymupdf.get_text_length(label, fontsize=8) / 2, PAGE.height - 32),
                         label, fontsize=8, color=(0.45, 0.45, 0.45))
    tools.finalize(pdf, all_fonts=True)
    data = pdf.tobytes(garbage=3, deflate=True)
    pdf.close()
    Path(dst).write_bytes(data)
