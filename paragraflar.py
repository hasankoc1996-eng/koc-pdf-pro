"""Metin düzenleme: sayfadaki satırların paragraflara gruplanması, düzenlenen paragrafın yeniden dizilmesi
(alttaki metin kaydırılır) ve belgenin tamamında bul-değiştir."""
import pymupdf

import fonts
from pdf_ortak import _dir_rotate, _fname
from tools import ToolError, hex_to_rgb


REDACT_KEEP = dict(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)


def _shrink(rect):
    """Komşu satırlara taşmaması için redaksiyon alanını dikeyde biraz daralt."""
    dy = rect.height * 0.18
    return pymupdf.Rect(rect.x0 + 0.3, rect.y0 + dy, rect.x1 - 0.3, rect.y1 - dy)


# ---------------------------------------------------------------- paragraflar
# PDF'te paragraf yoktur, yalnızca konumlanmış satırlar vardır. Düzenlenen metnin Word'deki gibi
# yeniden dizilebilmesi için satırlar geometrilerine bakılarak paragraflara gruplanır.

def _paragraphs(lines, W, H):
    """Satır listesini paragraf girdilerine dönüştürür (lines() çıktısıyla aynı alanlar + paragraf bilgisi)."""
    for l in lines:
        l["_r"] = pymupdf.Rect(l["bbox"])
    for l in lines:   # satırın sütunu: yatayda onunla çakışan satırların kapladığı alan
        over = [o["_r"] for o in lines if o["_r"].x0 < l["_r"].x1 and o["_r"].x1 > l["_r"].x0]
        l["_col"] = (min(r.x0 for r in over), max(r.x1 for r in over))
        # aynı hizadaki sağ komşu (tablo hücresi gibi): tek satırlık paragraf onun üstüne taşmasın
        right = [o["_r"].x0 for o in lines if o is not l and abs(o["origin"][1] - l["origin"][1]) < 0.5 * l["size"]
                 and o["_r"].x0 >= l["_r"].x1 - 1]
        l["_next_x"] = min(right) if right else None
        # aynı hizada araya geniş boşluk girmiş komşusu var: tablo hücresi ya da sütun, alt satırla birleşmez
        l["_cell"] = any(o is not l and abs(o["origin"][1] - l["origin"][1]) < 0.5 * l["size"]
                         and max(o["_r"].x0 - l["_r"].x1, l["_r"].x0 - o["_r"].x1) > 1.5 * l["size"] for o in lines)
    # İçerik akışındaki sıra görünen sıra olmayabilir (ör. sonradan yazılan metin): yukarıdan aşağı işle.
    # Her satır, devamı olabileceği en yakın açık paragrafa eklenir (iki sütunlu sayfalar da böylece ayrışır).
    groups = []
    for l in sorted(lines, key=lambda l: (round(l["origin"][1], 1), l["_r"].x0)):
        fits = [g for g in groups if _continues(g, l)]
        if fits:
            max(fits, key=lambda g: g[-1]["origin"][1]).append(l)
        else:
            groups.append([l])
    out = [_para_entry(g, W, H) for g in groups]
    for l in lines:
        del l["_r"], l["_col"], l["_next_x"], l["_cell"]
    return out


def _continues(cur, l):
    """l satırı cur paragrafının devamı mı? Emin olunamayan durumda paragraf bölünür:
    iki paragrafı yanlışlıkla birleştirmek, bir paragrafı ikiye bölmekten çok daha zararlıdır."""
    prev, r, pr = cur[-1], l["_r"], cur[-1]["_r"]
    size = prev["size"]
    if abs(l["size"] - size) > 0.6 or l["bold"] != prev["bold"] or l["_cell"] or prev["_cell"]:
        return False
    dy = l["origin"][1] - prev["origin"][1]
    if dy < 0.5 * size:                                   # aynı hizada ya da yukarıda: başka sütun/tablo
        return False
    if len(cur) >= 2:
        step = prev["origin"][1] - cur[-2]["origin"][1]
        if dy > step * 1.35:                              # paragraf arası boşluk
            return False
        left = min(x["_r"].x0 for x in cur[1:])
        right = max(x["_r"].x1 for x in cur)
        if r.x0 > left + 3:                               # girintili satır: yeni paragrafın ilk satırı
            return False
    else:
        if dy > size * 2.0:
            return False
        if r.x0 > pr.x0 + 3:                              # asılı girinti / madde: bölmek daha güvenli
            return False
        left, right = r.x0, max(pr.x1, prev["_col"][1])
        if pr.x0 - left > max(6 * size, 0.25 * (right - left)):   # bu kadar büyük "girinti" olmaz (tablo)
            return False
    if pr.x1 < right - max(3 * size, 0.15 * (right - left)):   # önceki satır kısa: paragraf bitmişti
        return False
    return r.x1 > left and r.x0 < right


def _join_lines(texts):
    """Satırları tek metne birleştirir; satır sonunda bölünmüş kelimeleri (tire) birleştirir."""
    out = ""
    for t in texts:
        t = t.strip()
        if not out:
            out = t
        elif out[-1] in "-­" and len(out) > 1 and out[-2].isalpha() and t[:1].islower():
            out = out[:-1] + t
        else:
            out += " " + t
    return out


def _para_align(g, left, right):
    if len(g) >= 2:
        if all(abs(l["_r"].x1 - right) < 2.5 for l in g[:-1]):
            return "justify" if all(abs(l["_r"].x0 - left) < 2.5 for l in g[1:]) else "right"
        centers = [(l["_r"].x0 + l["_r"].x1) / 2 for l in g]
        return "center" if max(centers) - min(centers) < 3 else "left"
    r, col = g[0]["_r"], g[0]["_col"]
    if r.x0 > col[0] + 10 and abs((r.x0 + r.x1) / 2 - (col[0] + col[1]) / 2) < 4:
        return "center"
    return "left"


def _para_entry(g, W, H):
    first = g[0]
    dom = max(g, key=lambda l: len(l["text"]))
    union = pymupdf.Rect(first["_r"])
    for l in g[1:]:
        union |= l["_r"]
    body = g[1:] or g
    left = min(l["_r"].x0 for l in body)
    right = max(l["_r"].x1 for l in g)
    indent = max(0.0, first["_r"].x0 - left) if len(g) > 1 else 0.0
    steps = sorted(b["origin"][1] - a["origin"][1] for a, b in zip(g, g[1:]))
    align = _para_align(g, left, right)
    if len(g) == 1:   # tek satır: eklenen metin önce aynı satırda yer bulsun
        col = first["_col"]
        if align == "center":
            left, right = col
        else:
            right = max(right, col[1])
        if first["_next_x"] is not None:
            right = min(right, first["_next_x"] - 0.5 * first["size"])
    entry = {k: dom[k] for k in ("size", "font", "color", "bold", "italic", "serif")}
    entry.update({
        "text": _join_lines(l["text"] for l in g),
        "bbox": [round(v, 3) for v in union],
        "origin": first["origin"],
        "x": union.x0 / W, "y": union.y0 / H, "w": union.width / W, "h": union.height / H,
        "rotate": 0,
        "lines": [l["bbox"] for l in g],
        "left": round(left, 3), "right": round(right, 3), "indent": round(indent, 3),
        "fl": left / W, "fr": right / W,          # ekranda paragrafın sol / sağ kenarı (0–1)
        "lh": round(steps[len(steps) // 2], 3) if steps else round(dom["size"] * 1.15, 3),
        "align": align,
    })
    return entry


def _page_lines(page):
    return [pymupdf.Rect(l["bbox"]) for b in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
            for l in b.get("lines", []) if any(s["text"].strip() for s in l["spans"])]


def _same_line(a, b):
    return abs(a.x0 - b.x0) < 1 and abs(a.y0 - b.y0) < 1


def _page_floor(page, lines):
    """Metnin inebileceği en alt nokta: altta en az ~1,8 cm boşluk kalsın; belge zaten daha aşağıdaysa orası."""
    return max(page.rect.height - 50, max((r.y1 for r in lines), default=0) + 1)


def _shift_text_below(page, src, below, delta, own_bottom, lh, others, floor):
    """Paragrafın altındaki metni delta kadar aşağı (eksiyse yukarı) kaydırır: alan yeni metne açılır,
    Word'deki gibi sonraki paragraflar itilir. Kaydırılan bölge, sayfanın değiştirilmemiş kopyasından
    aynen (yazı tipi ve aralıklar korunarak) yeniden çizilir. Bölgede çizim ya da resim varsa, sayfaya
    sığmıyorsa ya da başka bir sütunla çakışıyorsa hiçbir şey yapılmaz ve False döner."""
    group = [below[0]]
    for r in below[1:]:                       # büyük bir boşluktan sonraki satırlar (sayfa altlığı) yerinde kalır
        if r.y0 - group[-1].y1 > 3 * lh:
            break
        group.append(r)
    footer = below[len(group)] if len(group) < len(below) else None
    clip = pymupdf.Rect(min(r.x0 for r in group) - 1, (own_bottom + group[0].y0) / 2,
                        max(r.x1 for r in group) + 1, max(r.y1 for r in group) + 1)
    target = clip + (0, delta, 0, delta)
    if footer:
        floor = footer.y0 - 2
    if target.y1 > floor:
        return False
    area = clip | target
    moving = set(map(tuple, group))
    if any(r.intersects(area) and tuple(r) not in moving for r in others):
        return False
    for d in page.get_drawings():
        invisible = d.get("color") is None and d.get("fill") in (None, (1.0, 1.0, 1.0))
        if not invisible and d["rect"].intersects(area):
            return False
    if any(pymupdf.Rect(im["bbox"]).intersects(area) for im in page.get_image_info()):
        return False
    for r in group:
        page.add_redact_annot(_shrink(r), fill=False)
    page.apply_redactions(text=pymupdf.PDF_REDACT_TEXT_REMOVE, **REDACT_KEEP)
    page.show_pdf_page(target, src, 0, clip=clip)
    return True


def _edit_paragraph(doc, page, e, cache_dir):
    """Paragrafı yeniden dizer: ilk satırın taban çizgisi, girinti, satır aralığı ve hizalama korunur.
    Metin uzar ya da kısalırsa alttaki metin kaydırılır; kaydırılamıyorsa metin alttaki boş alana yayılır,
    o da yetmezse yazı en çok %15 küçültülür."""
    text = e.get("text", "")
    own = [pymupdf.Rect(b) for b in e["lines"]]
    others = [r for r in _page_lines(page) if not any(_same_line(r, o) for o in own)]
    src = pymupdf.open()
    src.insert_pdf(doc, from_page=page.number, to_page=page.number)   # kaydırma için değişmemiş kopya
    for o in own:
        page.add_redact_annot(_shrink(o), fill=False)
    page.apply_redactions(text=pymupdf.PDF_REDACT_TEXT_REMOVE, **REDACT_KEEP)
    if not text.strip():
        return
    path = fonts.resolve(e.get("font"), text, bold=e.get("bold", False), italic=e.get("italic", False),
                         serif=e.get("serif", False), cache_dir=cache_dir)
    font = fonts.font_obj(path)
    size = float(e["size"])
    lh = max(float(e.get("lh") or size * 1.15), size)
    left, right, indent = float(e["left"]), float(e["right"]), float(e.get("indent") or 0)
    base = float(e["origin"][1])                     # ilk satırın taban çizgisi yerinde kalır
    own_bottom = max(o.y1 for o in own)
    below = sorted((r for r in others if r.y0 >= own_bottom - 1 and r.x1 > left and r.x0 < right),
                   key=lambda r: r.y0)
    floor = _page_floor(page, others + own)
    limit = max(below[0].y0 - 1 if below else floor, own_bottom)
    rows = _break_lines(text, font, size, right - left, indent)
    delta = (len(rows) - len(own)) * lh               # paragraf kaç satır uzadı / kısaldı
    if below and delta and _shift_text_below(page, src, below, delta, own_bottom, lh, others, floor):
        limit += delta
    # Kaydırılamadıysa: alttaki boş alana sığdır, gerekirse yazıyı en çok %15 küçült
    scale = 1.0
    while base + (len(rows) - 1) * lh * scale - font.descender * size * scale > limit:
        scale -= 0.05
        if scale < 0.84:
            raise ToolError("Düzenlenen paragraf sayfaya sığmıyor. Metni biraz kısaltın ya da altında boşluk açın.")
        rows = _break_lines(text, font, size * scale, right - left, indent * scale)
    _write_rows(page, rows, font, size * scale, lh * scale, base, left, right, indent * scale,
                e.get("align"), hex_to_rgb(e.get("color")))


def _break_lines(text, font, size, width, indent):
    """Metni satırlara böler (Word'deki gibi kelime kelime). Her satır: (kelimeler, paragrafın son satırı mı).
    Girinti yalnızca ilk satıra uygulanır; metindeki satır sonları (Shift+Enter) korunur."""
    space = font.text_length(" ", fontsize=size)
    rows = []
    for n, part in enumerate(text.split("\n")):
        words, cur, cur_w = part.split(), [], 0.0
        avail = width - (indent if n == 0 else 0)
        for w in words:
            ww = font.text_length(w, fontsize=size)
            if cur and cur_w + space + ww > avail + 0.01:
                rows.append((cur, False))
                cur, cur_w, avail = [w], ww, width
            else:
                cur_w = ww if not cur else cur_w + space + ww
                cur.append(w)
        rows.append((cur, True))
    return rows


def _write_rows(page, rows, font, size, lh, base, left, right, indent, align, color):
    """Satırları kelime kelime yazar; iki yana yaslamada boşluklar paylaştırılır (son satır hariç)."""
    space = font.text_length(" ", fontsize=size)
    tw = pymupdf.TextWriter(page.rect, color=color)
    for k, (words, last) in enumerate(rows):
        x0 = left + (indent if k == 0 else 0)
        widths = [font.text_length(w, fontsize=size) for w in words]
        natural = sum(widths) + space * max(len(words) - 1, 0)
        gap = space
        if align == "justify" and not last and len(words) > 1:
            gap = (right - x0 - sum(widths)) / (len(words) - 1)
        x = {"center": x0 + (right - x0 - natural) / 2, "right": right - natural}.get(align, x0)
        y = base + k * lh
        for w, wd in zip(words, widths):
            tw.append((x, y), w, font=font, fontsize=size)
            x += wd + gap
    tw.write_text(page)


def op_text_edit(doc, index, edits, cache_dir):
    page = doc[index]
    plain = [e for e in edits if not e.get("lines")]
    if plain:   # tek tek satırlar (döndürülmüş sayfalar): her satır yerinde yeniden yazılır
        for e in plain:
            page.add_redact_annot(_shrink(pymupdf.Rect(e["bbox"])), fill=False)
        page.apply_redactions(text=pymupdf.PDF_REDACT_TEXT_REMOVE, **REDACT_KEEP)
        for e in plain:
            text = e.get("text", "")
            if not text.strip():
                continue
            path = fonts.resolve(e.get("font"), text, bold=e.get("bold", False), italic=e.get("italic", False),
                                 serif=e.get("serif", False), cache_dir=cache_dir)
            page.insert_text(pymupdf.Point(e["origin"]), text, fontsize=float(e["size"]),
                             fontname=_fname(path), fontfile=path,
                             color=hex_to_rgb(e.get("color")), rotate=int(e.get("rotate", page.rotation)))
    # Paragraflar aşağıdan yukarıya işlenir: birinin alttaki metni kaydırması üsttekilerin konumunu bozmaz
    for e in sorted((e for e in edits if e.get("lines")), key=lambda e: -float(e["origin"][1])):
        _edit_paragraph(doc, page, e, cache_dir)


def op_replace_all(doc, find, replace, match_case, cache_dir):
    if not find:
        raise ToolError("Aranacak metni girin.")
    total = 0
    for page in doc:
        hits = page.search_for(find)
        if match_case:
            hits = [r for r in hits if find in page.get_textbox(r + (-1, -1, 1, 1))]
        if not hits:
            continue
        spans = [(s, l["dir"]) for b in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
                 for l in b.get("lines", []) for s in l["spans"]]
        plans = []
        for r in hits:
            best = max(spans, key=lambda sd: (pymupdf.Rect(sd[0]["bbox"]) & r).get_area(), default=None)
            if best is None:
                continue
            plans.append((r, *best))
            page.add_redact_annot(_shrink(r), fill=False)
        page.apply_redactions(text=pymupdf.PDF_REDACT_TEXT_REMOVE, **REDACT_KEEP)
        for r, span, direction in plans:
            total += 1
            if not replace:
                continue
            path = fonts.resolve(span["font"], replace, bold=bool(span["flags"] & 16),
                                 italic=bool(span["flags"] & 2), serif=bool(span["flags"] & 4),
                                 cache_dir=cache_dir)
            rotate = _dir_rotate(direction)
            ox, oy = span["origin"]
            origin = {0: (r.x0, oy), 90: (ox, r.y1), 180: (r.x1, oy), 270: (ox, r.y0)}[rotate]
            page.insert_text(pymupdf.Point(origin), replace, fontsize=span["size"], fontname=_fname(path),
                             fontfile=path, color=hex_to_rgb("#%06x" % span["color"]), rotate=rotate)
    return total
