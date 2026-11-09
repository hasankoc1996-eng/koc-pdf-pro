"""PDF → Excel: sayfalardaki tablolar Excel çalışma kitabına aktarılır. Çizgili tablolar hücreleriyle bulunur
(MuPDF tablo bulucu); çizgisiz, hizalı tablolar (hesap dökümü, ödeme planı) kelimeler arasındaki boşluklardan
sütunlara ayrılır. Türkçe yazılmış tutarlar (12.500,00) sayı, tarihler (01.02.2026) tarih olarak yazılır: Excel'de
toplanıp sıralanabilir."""

import contextlib
import io
import re
from datetime import date

import pymupdf

from tools import ToolError

NUMBER = re.compile(r"^(-?)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(?:\s*(TL|₺))?$")
DATE = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$")


def cell_value(text):
    """Hücre yazısı → (değer, Excel biçimi). Uzun ya da 0 ile başlayan tam sayılar (T.C. kimlik, telefon, dosya no)
    ve yıl gibi binlik ayracı olmayan sayılar biçimsiz kalır; sayı ve tarih değilse yazı olarak yazılır."""
    t = (text or "").strip()
    flat = " ".join(t.split())
    m = DATE.match(flat)
    if m:
        d, mo, y = map(int, m.groups())
        try:
            return date(y, mo, d), "dd.mm.yyyy"
        except ValueError:
            return t, None
    m = NUMBER.match(flat)
    if m:
        sign, whole, frac, cur = m.groups()
        digits = whole.replace(".", "")
        if not frac and (len(digits) > 9 or (len(digits) > 1 and digits.startswith("0"))):
            return t, None
        value = float(f"{sign}{digits}.{frac}") if frac else int(sign + digits)
        grouped = "." in whole or frac   # 12.500 ya da 850,00: binlik ayraçlı gösterilir; 2026 olduğu gibi
        fmt = ("#,##0" if grouped else "0") + ("." + "0" * len(frac) if frac else "") + (' "TL"' if cur else "")
        return value, fmt
    return t, None


def _rows(page, skip):
    """Tablo dışındaki kelimeler satır satır: [(üst, [[x0, x1, yazı], …])]. Aynı yükseklikteki kelimeler (farklı
    metin bloklarında olsalar da) bir satırdır; aralarındaki geniş boşluk yeni hücre başlatır."""
    words = [w for w in page.get_text("words") if not any(pymupdf.Rect(w[:4]).intersects(t) for t in skip)]
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows = []
    for x0, y0, x1, y1, text, *_ in words:
        cy, h = (y0 + y1) / 2, y1 - y0
        row = next((r for r in reversed(rows[-3:]) if abs(r["cy"] - cy) < max(r["h"], h) * 0.5), None)
        if row is None:
            row = {"cy": cy, "h": h, "top": y0, "words": []}
            rows.append(row)
        row["words"].append((x0, x1, text))
        row["h"] = max(row["h"], h)
    out = []
    for r in rows:
        cells = []
        for x0, x1, text in sorted(r["words"]):
            if cells and x0 - cells[-1][1] < r["h"] * 0.9:
                cells[-1][1] = x1
                cells[-1][2] += " " + text
            else:
                cells.append([x0, x1, text])
        out.append((r["top"], cells))
    return out


def _grid(rows):
    """Hizalı satırlar: sütunlar, satırlardaki hücrelerin yatay aralıkları birleştirilerek bulunur (sağa yaslı
    tutarlar da aynı sütuna düşer). Dönen: [[hücre yazısı, …], …]"""
    spans = []
    for x0, x1, _ in sorted(c for _, cells in rows for c in cells):
        if spans and x0 <= spans[-1][1] + 2:
            spans[-1][1] = max(spans[-1][1], x1)
        else:
            spans.append([x0, x1])
    table = []
    for _, cells in rows:
        line = [""] * len(spans)
        for x0, x1, text in cells:
            k = next(k for k, (a, b) in enumerate(spans) if x0 <= b and x1 >= a)
            line[k] = f"{line[k]} {text}".strip()
        table.append(line)
    return table


def page_blocks(page, content="tables"):
    """Sayfanın Excel'e gidecek parçaları okunma sırasıyla: [(tür, satırlar)]. tür: "table" (çizgili tablo),
    "grid" (çizgisiz hizalı tablo) ya da "text" (tek hücrelik satır; yalnızca content="all")."""
    with contextlib.redirect_stdout(io.StringIO()):   # tablo bulucunun öneri iletisi kayda düşmesin
        found = page.find_tables(strategy="lines").tables
    # Renkli başlık hücresindeki dolgular ayrı küçük bir tablo sanılabilir: başka bir tablonun içinde kalan tablo atılır
    boxes = [pymupdf.Rect(t.bbox) for t in found]
    found = [t for t, r in zip(found, boxes) if not any(o.contains(r) and abs(o) > abs(r) for o in boxes)]
    blocks =[(t.bbox[1], "table", [[c or "" for c in row] for row in t.extract()]) for t in found]
    run = []

    def close_run():
        if len(run) >= 2:   # en az iki hizalı satır: tablo
            blocks.append((run[0][0], "grid", _grid(run)))
        elif content == "all":
            blocks.extend((top, "text", [[" ".join(c[2] for c in cells)]]) for top, cells in run)
        run.clear()

    for top, cells in _rows(page, [pymupdf.Rect(t.bbox) for t in found]):
        if len(cells) >= 2:
            run.append((top, cells))
            continue
        close_run()
        if content == "all":
            blocks.append((top, "text", [[cells[0][2]]]))
    close_run()
    blocks.sort(key=lambda b: b[0])
    return [(kind, rows) for _, kind, rows in blocks]


def to_excel(src, dst, content="tables", layout="pages"):
    """PDF'i Excel'e yazar. layout: "pages" (her PDF sayfası ayrı çalışma sayfası) ya da "single" (hepsi tek
    sayfada). Dönen: {tables, note}"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    doc = pymupdf.open(src)
    if not any(page.get_text("text").strip() for page in doc):
        raise ToolError("PDF'te metin yok (taranmış olabilir). Önce “Metin Tanıma (OCR)” uygulayın, sonra yeniden deneyin.")
    line = Side(style="thin", color="B8BEC7")
    border = Border(left=line, right=line, top=line, bottom=line)
    head_fill = PatternFill("solid", fgColor="EEF2F7")
    wb = Workbook()
    sheets, tables, used = [], 0, 0
    ws, row = None, 1
    for i, page in enumerate(doc):
        blocks = page_blocks(page, content)
        if not blocks:
            continue
        used += 1
        if layout == "single":
            if ws is None:
                ws = wb.active
                ws.title = "Tablolar"
                sheets.append(ws)
            ws.cell(row, 1, f"Sayfa {i + 1}").font = Font(bold=True, color="6B7280")
            row += 1
        else:
            ws = wb.active if not sheets else wb.create_sheet()
            ws.title = f"Sayfa {i + 1}"
            sheets.append(ws)
            row = 1
        for kind, rows in blocks:
            tables += kind != "text"
            for k, cells in enumerate(rows):
                for c, text in enumerate(cells, 1):
                    value, fmt = cell_value(text)
                    cell = ws.cell(row, c, value if value != "" else None)
                    if isinstance(value, str) and value.startswith("="):
                        cell.data_type = "s"   # PDF'teki "=…" yazısı yazı kalır: Excel'de formül olarak çalışmaz
                    if fmt:
                        cell.number_format = fmt
                    if kind != "text":
                        cell.border = border
                        if k == 0:   # tablonun ilk satırı: başlık
                            cell.font = Font(bold=True)
                            cell.fill = head_fill
                    if "\n" in str(text):
                        cell.alignment = Alignment(wrap_text=True, vertical="top")
                row += 1
            if kind != "text":
                row += 1   # tablodan sonra boş satır
    if not sheets or (content == "tables" and not tables):
        raise ToolError("Bu PDF'te tablo bulunamadı. “Bütün sayfa” seçeneğiyle metni satır satır aktarabilirsiniz.")
    for sh in sheets:   # sütun genişlikleri en uzun yazıya göre
        for col in sh.columns:
            longest = max((max(len(s) for s in str(c.value).split("\n")) for c in col if c.value is not None), default=0)
            sh.column_dimensions[get_column_letter(col[0].column)].width = min(max(longest + 2, 8), 60)
    wb.save(dst)
    what = f"{tables} tablo" if tables else "metin satır satır"
    return {"tables": tables, "note": what + (f", {used} sayfadan" if used > 1 else "")}
