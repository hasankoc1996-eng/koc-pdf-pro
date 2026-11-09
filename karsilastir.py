"""İki belgenin metin karşılaştırması (bir dilekçenin ya da sözleşmenin iki sürümü). Sonuç tek bir PDF: ilk sayfalarda
değişiklik listesi, ardından eski ve yeni sayfalar yan yana; eskiden silinen yerler kırmızı, yenide eklenen yerler
yeşil boyanır. Önce satırlar karşılaştırılır, değişen satırlarda kelimeler: uzun belgede de hızlıdır."""

import difflib
import html
import io
from pathlib import Path

import pymupdf

import fonts
import tools
from tools import ToolError

DELETED = (1, 0.55, 0.55)   # eski sürümde silinen
INSERTED = (0.45, 0.85, 0.5)   # yeni sürümde eklenen
MAX_LIST = 400   # listede gösterilen en çok değişiklik


def words(doc):
    """Kelimeler okunma sırasıyla [(sayfa, Rect, metin)] ve satırlar [(ilk kelime, son kelime + 1)]."""
    out, lines, current = [], [], None
    for i, page in enumerate(doc):
        for x0, y0, x1, y1, text, block, line, _ in page.get_text("words"):
            if (i, block, line) != current:
                current = (i, block, line)
                lines.append([len(out), len(out)])
            out.append((i, pymupdf.Rect(x0, y0, x1, y1), text.replace("\xad", "")))
            lines[-1][1] = len(out)
    return out, lines


def diff(aw, al, bw, bl):
    """Değişiklikler: [(eski kelimeler [i, j), yeni kelimeler [k, l))]. Önce satırlar, değişen bloklarda kelimeler."""
    text = lambda ws, s, e: " ".join(w[2] for w in ws[s:e])
    la = [text(aw, s, e) for s, e in al]
    lb = [text(bw, s, e) for s, e in bl]
    changes = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, la, lb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        a0 = al[i1][0] if i1 < i2 else (al[i1 - 1][1] if i1 else 0)
        a1 = al[i2 - 1][1] if i1 < i2 else a0
        b0 = bl[j1][0] if j1 < j2 else (bl[j1 - 1][1] if j1 else 0)
        b1 = bl[j2 - 1][1] if j1 < j2 else b0
        wa, wb = [w[2] for w in aw[a0:a1]], [w[2] for w in bw[b0:b1]]
        if len(wa) * len(wb) > 25_000_000:   # çok büyük blok: kelime kelime karşılaştırma uzun sürer
            changes.append(((a0, a1), (b0, b1)))
            continue
        for t, x1, x2, y1, y2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
            if t != "equal":
                changes.append(((a0 + x1, a0 + x2), (b0 + y1, b0 + y2)))
    return changes


def _boxes(ws, s, e):
    """Kelime aralığının dikdörtgenleri: aynı satırdaki kelimeler birleşir. [[sayfa, Rect]]"""
    out = []
    for page, r, _ in ws[s:e]:
        last = out[-1] if out else None
        if last and last[0] == page and abs(last[1].y0 - r.y0) < r.height * 0.5 and r.x0 - last[1].x1 < r.height * 1.5:
            last[1] |= r
        else:
            out.append([page, pymupdf.Rect(r)])
    return out


def _paint(doc, boxes, color):
    for page, r in boxes:
        doc[page].draw_rect(r + (-0.5, -0.5, 0.5, 0.5), color=None, fill=color, fill_opacity=0.45, overlay=False)


def _summary_pdf(changes, aw, bw, old_name, new_name, pages, counts, cache_dir):
    esc = html.escape
    snippet = lambda ws, s, e: esc(" ".join(w[2] for w in ws[s:e])[:600])
    rows = []
    for n, ((a0, a1), (b0, b1)) in enumerate(changes[:MAX_LIST], 1):
        where = []
        if a1 > a0:
            where.append(f"eski s. {aw[a0][0] + 1}")
        if b1 > b0:
            where.append(f"yeni s. {bw[b0][0] + 1}")
        body = ""
        if a1 > a0:
            body += f"<span class='del'>{snippet(aw, a0, a1)}</span> "
        if b1 > b0:
            body += f"<span class='ins'>{snippet(bw, b0, b1)}</span>"
        rows.append(f"<p class='row'><span class='n'>{n}. {' · '.join(where)}</span><br>{body}</p>")
    more = len(changes) - MAX_LIST
    body = (f"<h1>Karşılaştırma</h1><p class='meta'><b>Eski:</b> {esc(old_name)} ({pages[0]} sayfa)<br><b>Yeni:</b> {esc(new_name)}"
            f" ({pages[1]} sayfa)</p><p class='sum'>{esc(counts)}</p>"
            + ("<p class='legend'><span class='del'>silinen</span> <span class='ins'>eklenen</span> — sonraki sayfalarda eski ve"
               " yeni sayfalar yan yana, farklar boyalı.</p>" if changes else "<p>Metinler aynı; fark bulunmadı.</p>")
            + "".join(rows) + (f"<p class='meta'>… ve {more} değişiklik daha (yan yana sayfalarda boyalı).</p>" if more > 0 else ""))
    css = """
body { font-family: 'Arial'; font-size: 10pt; line-height: 1.35; }
h1 { font-size: 18pt; margin: 0 0 6pt 0; }
.meta { color: #555555; font-size: 9.5pt; margin: 0 0 6pt 0; }
.sum { font-weight: bold; margin: 0 0 6pt 0; }
.legend { color: #555555; font-size: 9pt; margin: 0 0 10pt 0; }
.row { margin: 0 0 7pt 0; }
.n { color: #6b7280; font-size: 8.5pt; font-weight: bold; }
.del { color: #b42318; text-decoration: line-through; background-color: #fee4e2; }
.ins { color: #067647; background-color: #dcfae6; }
"""
    archive, faces = fonts.story_faces({"Arial"}, cache_dir)
    story = pymupdf.Story(html=f"<body>{body}</body>", user_css=faces + css, archive=archive)
    data = io.BytesIO()
    writer = pymupdf.DocumentWriter(data)
    mediabox = pymupdf.paper_rect("a4")
    more_pages, count = 1, 0
    while more_pages and count < 500:
        device = writer.begin_page(mediabox)
        more_pages, _ = story.place(mediabox + (50, 50, -50, -50))
        story.draw(device)
        writer.end_page()
        count += 1
    writer.close()
    return pymupdf.open("pdf", data.getvalue())


def compare(old_path, new_path, dst, old_name, new_name, cache_dir=Path(".")):
    """Karşılaştırma PDF'ini dst'ye yazar. Dönen: {changes, inserted, deleted} (kelime sayıları)."""
    a, b = pymupdf.open(old_path), pymupdf.open(new_path)
    aw, al = words(a)
    bw, bl = words(b)
    if not aw or not bw:
        which = "Eski" if not aw else "Yeni"
        raise ToolError(f"{which} sürümde okunabilir metin yok (taranmış olabilir). Önce “Metin Tanıma (OCR)” uygulayın.")
    changes = diff(aw, al, bw, bl)
    deleted = sum(a1 - a0 for (a0, a1), _ in changes)
    inserted = sum(b1 - b0 for _, (b0, b1) in changes)
    counts = (f"{len(changes)} değişiklik: {inserted} kelime eklendi, {deleted} kelime silindi" if changes else "Fark yok")
    for (a0, a1), (b0, b1) in changes:
        _paint(a, _boxes(aw, a0, a1), DELETED)
        _paint(b, _boxes(bw, b0, b1), INSERTED)

    out = _summary_pdf(changes, aw, bw, old_name, new_name, (a.page_count, b.page_count), counts, cache_dir)
    summary_pages = out.page_count
    fontfile = fonts.face_file("Arial", bold=True, cache_dir=cache_dir)
    gap, head = 18, 22
    for i in range(max(a.page_count, b.page_count)):
        ra = a[i].rect if i < a.page_count else None
        rb = b[i].rect if i < b.page_count else None
        wa, wb = (ra or rb).width, (rb or ra).width
        H = max(r.height for r in (ra, rb) if r) + head
        page = out.new_page(width=wa + gap + wb, height=H)
        if fontfile:
            page.insert_font(fontname="kf", fontfile=fontfile)
        for x, r, doc, label, color in ((0, ra, a, f"Eski · {old_name} · s. {i + 1}", (0.7, 0.14, 0.1)),
                                        (wa + gap, rb, b, f"Yeni · {new_name} · s. {i + 1}", (0.03, 0.46, 0.28))):
            if r is None:
                continue
            page.insert_text((x + 4, 15), label[:110], fontsize=9, color=color, fontname="kf" if fontfile else "helv")
            page.show_pdf_page(pymupdf.Rect(x, head, x + r.width, head + r.height), doc, i)
        page.draw_line((wa + gap / 2, 0), (wa + gap / 2, H), color=(0.75, 0.75, 0.75), width=0.5)
    out.set_toc([[1, "Değişiklik listesi", 1]] + [[1, f"Sayfa {i + 1}", summary_pages + i + 1]
                                                   for i in range(out.page_count - summary_pages)])
    tools.finalize(out, all_fonts=True)
    out.save(dst, garbage=3, deflate=True)
    return {"changes": len(changes), "inserted": inserted, "deleted": deleted, "note": counts}
