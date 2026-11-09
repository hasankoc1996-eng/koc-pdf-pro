"""UYAP UDF (UYAP Doküman Editörü) dosyaları: okuma, PDF/Word'e çevirme ve Word'den UDF üretme.

İnternetsiz çalışır. UDF bir ZIP dosyasıdır; içindeki content.xml şunları taşır:
  <content>   belgenin tüm düz metni (paragraflar "\\n" ile ayrılır)
  <elements>  paragraflar, tablolar, resimler; her yazı parçası metne startOffset/length ile bağlanır
  <styles>    varsayılan yazı tipi ve paragraf biçimi
  <properties><pageFormat> sayfa boyutu ve kenar boşlukları (pt)
"""
import base64
import html
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

import pymupdf

import fonts
import tools

ALIGN_CSS = {0: "left", 1: "center", 2: "right", 3: "justify"}


class UdfError(Exception):
    pass


# ================================================================== okuma

def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _bool(v):
    return str(v).lower() == "true"


def _color(v):
    """Java renk tamsayısı (işaretli ARGB) → #rrggbb"""
    if v in (None, ""):
        return None
    try:
        return "#%06x" % (int(v) & 0xFFFFFF)
    except ValueError:
        return None


class Doc:
    def __init__(self):
        self.page = {"width": 595.28, "height": 841.89, "left": 70.9, "right": 70.9, "top": 56.7, "bottom": 56.7}
        self.family = "Times New Roman"
        self.size = 12.0
        self.blocks = []      # {"type": "p"|"table"|"pagebreak", ...}


def read(source) -> Doc:
    """source: dosya yolu ya da bayt dizisi"""
    try:
        z = zipfile.ZipFile(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
        xml = z.read("content.xml")
    except (zipfile.BadZipFile, KeyError):
        raise UdfError("Bu dosya geçerli bir UDF değil (UYAP Doküman Editörü belgesi bekleniyordu).")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise UdfError(f"UDF içeriği okunamadı: {e}")

    doc = Doc()
    text = root.findtext("content") or ""
    styles = {s.get("name"): s.attrib for s in root.iter("style")}
    base = {**styles.get("default", {}), **styles.get("hvl-default", {})}
    if base.get("family") and base["family"] not in ("Dialog", "SansSerif", "Serif"):
        doc.family = base["family"]
    doc.size = _num(base.get("size"), 12.0) or 12.0

    pf = root.find("properties/pageFormat")
    if pf is not None:
        landscape = pf.get("paperOrientation") == "2"
        w, h = pymupdf.paper_size("a4")
        if landscape:
            w, h = h, w
        doc.page.update(width=w, height=h,
                        left=_num(pf.get("leftMargin"), 70.9), right=_num(pf.get("rightMargin"), 70.9),
                        top=_num(pf.get("topMargin"), 56.7), bottom=_num(pf.get("bottomMargin"), 56.7))

    def run_style(el):
        a = {**styles.get(el.get("resolver") or "", {}), **el.attrib}
        fam = a.get("family")
        return {
            "family": fam if fam and fam not in ("Dialog", "SansSerif", "Serif") else None,
            "size": _num(a.get("size"), 0) or None,
            "bold": _bool(a.get("bold")),
            "italic": _bool(a.get("italic")),
            "underline": _bool(a.get("underline")),
            "strike": _bool(a.get("strikethrough")),
            "color": _color(a.get("foreground")),
            "background": _color(a.get("background")),
        }

    def paragraph(el):
        a = {**styles.get(el.get("resolver") or "", {}), **el.attrib}
        runs = []
        for child in el.iter():
            if child is el:
                continue
            tag = child.tag
            if tag == "image":
                data = child.get("imageData")
                if data:
                    try:
                        runs.append({"image": base64.b64decode(data), "width": _num(child.get("width")),
                                     "height": _num(child.get("height"))})
                    except ValueError:
                        pass
                continue
            if tag == "page-break":
                runs.append({"pagebreak": True})
                continue
            if child.get("startOffset") is None:
                continue
            s, n = int(_num(child.get("startOffset"))), int(_num(child.get("length")))
            piece = text[s:s + n]
            if tag == "tab":
                piece = "\t"
            runs.append({"text": piece, **run_style(child)})
        # paragrafın sonundaki satır sonunu at
        while runs and "text" in runs[-1] and runs[-1]["text"].endswith("\n"):
            runs[-1]["text"] = runs[-1]["text"][:-1]
            if not runs[-1]["text"]:
                runs.pop()
        return {
            "type": "p",
            "align": int(_num(a.get("Alignment"), 0)),
            "left": _num(a.get("LeftIndent")), "right": _num(a.get("RightIndent")),
            "first": _num(a.get("FirstLineIndent")),
            "above": _num(a.get("SpaceAbove")), "below": _num(a.get("SpaceBelow")),
            "line": _num(a.get("LineSpacing")),
            "bullet": _bool(a.get("Bulleted")), "number": a.get("NumberType") not in (None, "", "NUMBER_TYPE_NONE"),
            "level": int(_num(a.get("ListLevel"), 0)),
            "runs": runs,
        }

    def block(el, out):
        if el.tag == "paragraph":
            out.append(paragraph(el))
        elif el.tag == "table":
            rows = []
            for row in el.findall("row"):
                cells = []
                for cell in row.findall("cell"):
                    content = []
                    for child in cell:
                        block(child, content)
                    cells.append({"blocks": content, "colspan": int(_num(cell.get("colspan"), 1)) or 1})
                rows.append(cells)
            widths = [_num(w) for w in (el.get("columnSpans") or "").split(",") if w.strip()]
            border = (el.get("border") or "borderCell") != "borderNone"
            out.append({"type": "table", "rows": rows, "widths": widths, "border": border})
        elif el.tag == "page-break":
            out.append({"type": "pagebreak"})
        else:                                   # bilinmeyen kapsayıcı: içindekileri sırayla al
            for child in el:
                block(child, out)

    elements = root.find("elements")
    if elements is not None:
        for el in elements:
            block(el, doc.blocks)
    if not doc.blocks and text.strip():        # biçim bilgisi yoksa düz metin
        doc.blocks = [{"type": "p", "align": 0, "left": 0, "right": 0, "first": 0, "above": 0, "below": 0,
                       "line": 0, "bullet": False, "number": False, "level": 0,
                       "runs": [{"text": line}]} for line in text.split("\n")]
    return doc


def plain_text(doc: Doc) -> str:
    lines = []

    def walk(blocks):
        for b in blocks:
            if b["type"] == "p":
                lines.append("".join(r.get("text", "") for r in b["runs"]))
            elif b["type"] == "table":
                for row in b["rows"]:
                    for cell in row:
                        walk(cell["blocks"])
    walk(doc.blocks)
    return "\n".join(lines)


# ================================================================== HTML ve PDF

def _font_stack(family):
    serif = any(k in (family or "").lower() for k in ("times", "serif", "georgia", "cambria", "garamond", "book"))
    return family or ("Times New Roman" if serif else "Arial")


def to_html(doc: Doc) -> str:
    out = []
    counters = {}

    def runs_html(runs, para_size):
        parts = []
        for r in runs:
            if r.get("pagebreak"):
                continue
            if "image" in r:
                b64 = base64.b64encode(r["image"]).decode()
                size = ""
                if r.get("width"):
                    size += f' width="{r["width"]:.0f}"'
                if r.get("height"):
                    size += f' height="{r["height"]:.0f}"'
                parts.append(f'<img src="data:image/png;base64,{b64}"{size}>')
                continue
            t = html.escape(r["text"]).replace("\t", "&emsp;&emsp;").replace("\n", "<br>")
            css = []
            if r.get("family"):
                css.append(f"font-family:'{_font_stack(r['family'])}'")
            if r.get("size") and abs(r["size"] - para_size) > 0.01:
                css.append(f"font-size:{r['size']:g}pt")
            if r.get("bold"):
                css.append("font-weight:bold")
            if r.get("italic"):
                css.append("font-style:italic")
            deco = [d for d, on in (("underline", r.get("underline")), ("line-through", r.get("strike"))) if on]
            if deco:
                css.append("text-decoration:" + " ".join(deco))
            if r.get("color") and r["color"] != "#000000":
                css.append(f"color:{r['color']}")
            if r.get("background") and r["background"] != "#ffffff":
                css.append(f"background-color:{r['background']}")
            parts.append(f'<span style="{";".join(css)}">{t}</span>' if css else t)
        return "".join(parts) or "&nbsp;"

    def para_html(p):
        css = [f"text-align:{ALIGN_CSS.get(p['align'], 'left')}", "margin:0"]
        if p["left"]:
            css.append(f"margin-left:{p['left']:g}pt")
        if p["right"]:
            css.append(f"margin-right:{p['right']:g}pt")
        if p["first"]:
            css.append(f"text-indent:{p['first']:g}pt")
        if p["above"]:
            css.append(f"margin-top:{p['above']:g}pt")
        if p["below"]:
            css.append(f"margin-bottom:{p['below']:g}pt")
        css.append(f"line-height:{1.15 + max(p['line'], 0):.2f}")
        prefix = ""
        if p["bullet"]:
            prefix = "•&nbsp;&nbsp;"
        elif p["number"]:
            counters[p["level"]] = counters.get(p["level"], 0) + 1
            prefix = f"{counters[p['level']]}.&nbsp;&nbsp;"
        return f'<p style="{";".join(css)}">{prefix}{runs_html(p["runs"], doc.size)}</p>'

    def blocks_html(blocks):
        for b in blocks:
            if b["type"] == "p":
                if not (b["bullet"] or b["number"]):
                    counters.clear()
                out.append(para_html(b))
            elif b["type"] == "table":
                border = "1px solid #000" if b["border"] else "none"
                out.append('<table style="border-collapse:collapse;width:100%">')
                for row in b["rows"]:
                    out.append("<tr>")
                    for cell in row:
                        span = f' colspan="{cell["colspan"]}"' if cell["colspan"] > 1 else ""
                        out.append(f'<td{span} style="border:{border};padding:2pt 4pt;vertical-align:top">')
                        blocks_html(cell["blocks"])
                        out.append("</td>")
                    out.append("</tr>")
                out.append("</table>")
            elif b["type"] == "pagebreak":
                out.append('<p style="page-break-after:always;margin:0"></p>')

    blocks_html(doc.blocks)
    return "\n".join(out)


def _families(doc: Doc):
    seen = {doc.family}

    def walk(blocks):
        for b in blocks:
            if b["type"] == "p":
                seen.update(r["family"] for r in b["runs"] if r.get("family"))
            elif b["type"] == "table":
                for row in b["rows"]:
                    for cell in row:
                        walk(cell["blocks"])
    walk(doc.blocks)
    return seen


def to_pdf(doc: Doc, dst: Path, cache_dir: Path):
    """UDF'yi sayfa düzeniyle PDF'e çizer (Word gerekmez). Türkçe karakterler için sistem fontları gömülür."""
    archive, faces = fonts.story_faces({_font_stack(fam) for fam in _families(doc)}, cache_dir)
    css = faces + f"\nbody {{font-family:'{_font_stack(doc.family)}'; font-size:{doc.size:g}pt;}}"
    story = pymupdf.Story(html=f"<body>{to_html(doc)}</body>", user_css=css, archive=archive)
    p = doc.page
    mediabox = pymupdf.Rect(0, 0, p["width"], p["height"])
    where = pymupdf.Rect(p["left"], p["top"], p["width"] - p["right"], p["height"] - max(p["bottom"], 20))
    writer = pymupdf.DocumentWriter(str(dst))
    more = 1
    pages = 0
    while more and pages < 2000:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
        pages += 1
    writer.close()
    # Yazı tiplerini küçült, boşluk/tire eşlemesini düzelt (kopyalama ve arama doğru çalışsın)
    pdf = pymupdf.open(dst)
    tools.finalize(pdf, all_fonts=True)
    data = pdf.tobytes(garbage=3, deflate=True)
    pdf.close()
    Path(dst).write_bytes(data)


# ================================================================== Word (.docx)

def to_docx(doc: Doc, dst: Path):
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.shared import Pt, RGBColor

    align = {0: WD_ALIGN_PARAGRAPH.LEFT, 1: WD_ALIGN_PARAGRAPH.CENTER,
             2: WD_ALIGN_PARAGRAPH.RIGHT, 3: WD_ALIGN_PARAGRAPH.JUSTIFY}
    d = Document()
    sec = d.sections[0]
    p = doc.page
    sec.page_width, sec.page_height = Pt(p["width"]), Pt(p["height"])
    if p["width"] > p["height"]:
        sec.orientation = WD_ORIENT.LANDSCAPE
    sec.left_margin, sec.right_margin = Pt(p["left"]), Pt(p["right"])
    sec.top_margin, sec.bottom_margin = Pt(p["top"]), Pt(max(p["bottom"], 14))
    normal = d.styles["Normal"]
    normal.font.name = doc.family
    normal.font.size = Pt(doc.size)
    normal.paragraph_format.space_after = Pt(0)

    def fill_paragraph(par, b):
        par.alignment = align.get(b["align"], WD_ALIGN_PARAGRAPH.LEFT)
        f = par.paragraph_format
        f.left_indent, f.right_indent = Pt(b["left"]), Pt(b["right"])
        f.first_line_indent = Pt(b["first"])
        f.space_before, f.space_after = Pt(b["above"]), Pt(b["below"])
        f.line_spacing = 1.0 + max(b["line"], 0)
        if b["bullet"]:
            par.add_run("•\t")
        for r in b["runs"]:
            if r.get("pagebreak"):
                par.add_run().add_break(WD_BREAK.PAGE)
                continue
            if "image" in r:
                try:
                    width = Pt(r["width"]) if r.get("width") else None
                    par.add_run().add_picture(io.BytesIO(r["image"]), width=width)
                except Exception:
                    pass
                continue
            run = par.add_run(r["text"])
            if r.get("family"):
                run.font.name = r["family"]
            if r.get("size"):
                run.font.size = Pt(r["size"])
            run.bold = r.get("bold") or None
            run.italic = r.get("italic") or None
            run.underline = r.get("underline") or None
            if r.get("strike"):
                run.font.strike = True
            if r.get("color") and r["color"] != "#000000":
                run.font.color.rgb = RGBColor.from_string(r["color"][1:].upper())

    def add_blocks(container, blocks, first_par=None):
        for b in blocks:
            if b["type"] == "p":
                par = first_par if first_par is not None else container.add_paragraph()
                first_par = None
                fill_paragraph(par, b)
            elif b["type"] == "table":
                ncols = max((sum(c["colspan"] for c in row) for row in b["rows"]), default=1)
                table = container.add_table(rows=len(b["rows"]), cols=ncols)
                if b["border"]:
                    table.style = d.styles["Table Grid"]
                for ri, row in enumerate(b["rows"]):
                    ci = 0
                    for cell in row:
                        target = table.cell(ri, ci)
                        if cell["colspan"] > 1:
                            target = target.merge(table.cell(ri, min(ci + cell["colspan"] - 1, ncols - 1)))
                        add_blocks(target, cell["blocks"], first_par=target.paragraphs[0])
                        ci += cell["colspan"]
            elif b["type"] == "pagebreak":
                container.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    add_blocks(d, doc.blocks)
    d.save(str(dst))


# ================================================================== Word → UDF

def _xml_cdata(text):
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def from_docx(src: Path, dst: Path):
    """Word belgesini UYAP Doküman Editörü'nün açtığı UDF biçimine çevirir. Uyarı listesi döner."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = Document(str(src))
    warnings = set()
    normal = d.styles["Normal"]
    base_family = normal.font.name or "Times New Roman"
    base_size = normal.font.size.pt if normal.font.size else 12.0
    align_map = {WD_ALIGN_PARAGRAPH.CENTER: 1, WD_ALIGN_PARAGRAPH.RIGHT: 2,
                 WD_ALIGN_PARAGRAPH.JUSTIFY: 3, WD_ALIGN_PARAGRAPH.DISTRIBUTE: 3}
    text = []
    pos = [0]

    def add_text(t):
        start = pos[0]
        text.append(t)
        pos[0] += len(t)
        return start, len(t)

    def style_chain(par, attr):
        """Paragraf biçimi: önce paragrafın kendisi, sonra stil zinciri."""
        v = getattr(par.paragraph_format, attr)
        style = par.style
        while v is None and style is not None:
            v = getattr(style.paragraph_format, attr)
            style = style.base_style
        return v

    def font_chain(run, par, attr):
        v = getattr(run.font, attr)
        style = run.style if run.style is not None and run.style.name != "Default Paragraph Font" else None
        while v is None and style is not None:
            v = getattr(style.font, attr)
            style = style.base_style
        style = par.style
        while v is None and style is not None:
            v = getattr(style.font, attr)
            style = style.base_style
        return v

    def pt(v):
        return round(v.pt, 2) if v is not None else 0

    def paragraph_xml(par):
        al = align_map.get(style_chain(par, "alignment"), 0)
        ls = style_chain(par, "line_spacing")
        line = max(round(ls - 1.0, 2), 0) if isinstance(ls, float) else 0
        attrs = (f'Alignment="{al}" LeftIndent="{pt(style_chain(par, "left_indent"))}" '
                 f'RightIndent="{pt(style_chain(par, "right_indent"))}" '
                 f'FirstLineIndent="{pt(style_chain(par, "first_line_indent"))}" LineSpacing="{line}" '
                 f'SpaceAbove="{pt(style_chain(par, "space_before"))}" SpaceBelow="{pt(style_chain(par, "space_after"))}"')
        runs = []
        for run in par.runs:
            if run.element.xpath(".//*[local-name()='drawing' or local-name()='pict']"):
                warnings.add("Belgedeki resimler UDF'ye aktarılmadı.")
            t = run.text
            if not t:
                continue
            family = font_chain(run, par, "name") or base_family
            size = font_chain(run, par, "size")
            size = size.pt if size is not None else base_size
            extra = ""
            if font_chain(run, par, "bold"):
                extra += ' bold="true"'
            if font_chain(run, par, "italic"):
                extra += ' italic="true"'
            if font_chain(run, par, "underline"):
                extra += ' underline="true"'
            color = run.font.color.rgb if run.font.color is not None and run.font.color.type is not None else None
            if color is not None and str(color) != "000000":
                extra += f' foreground="{int(str(color), 16) - 0x1000000}"'
            # sekmeler ayrı öğe olarak yazılır
            for i, piece in enumerate(t.split("\t")):
                if i:
                    s, n = add_text("\t")
                    runs.append(f'<tab family={quoteattr(family)} size="{size:g}"{extra} startOffset="{s}" length="{n}" />')
                if piece:
                    s, n = add_text(piece)
                    runs.append(f'<content family={quoteattr(family)} size="{size:g}"{extra} startOffset="{s}" length="{n}" />')
        s, n = add_text("\n")
        runs.append(f'<content family={quoteattr(base_family)} size="{base_size:g}" startOffset="{s}" length="{n}" />')
        return f'<paragraph {attrs}>{"".join(runs)}</paragraph>'

    def table_xml(table):
        rows_xml = []
        ncols = len(table.columns)
        widths = []
        for col in table.columns:
            try:
                widths.append(round(col.width.pt) if col.width is not None else 0)
            except Exception:
                widths.append(0)
        if not all(widths):
            widths = [round(450 / max(ncols, 1))] * ncols
        for ri, row in enumerate(table.rows):
            cells_xml = []
            seen = set()
            for cell in row.cells:
                if id(cell._tc) in seen:      # birleştirilmiş hücre tekrarı
                    continue
                seen.add(id(cell._tc))
                inner = "".join(paragraph_xml(p) for p in cell.paragraphs)
                cells_xml.append(f"<cell>{inner}</cell>")
            rows_xml.append(f'<row rowName="row{ri + 1}" rowType="dataRow">{"".join(cells_xml)}</row>')
        return (f'<table tableName="Sabit" columnCount="{ncols}" columnSpans="{",".join(map(str, widths))}" '
                f'border="borderCell">{"".join(rows_xml)}</table>')

    body = []
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            body.append(paragraph_xml(Paragraph(child, d)))
        elif tag == "tbl":
            body.append(table_xml(Table(child, d)))

    sec = d.sections[0]
    landscape = sec.page_width is not None and sec.page_height is not None and sec.page_width > sec.page_height
    page = (f'<pageFormat mediaSizeName="1" leftMargin="{pt(sec.left_margin) or 70.87}" '
            f'rightMargin="{pt(sec.right_margin) or 70.87}" topMargin="{pt(sec.top_margin) or 56.7}" '
            f'bottomMargin="{pt(sec.bottom_margin) or 56.7}" paperOrientation="{2 if landscape else 1}" '
            f'headerFOffset="20.0" footerFOffset="20.0" />')
    xml = ('<?xml version="1.0" encoding="UTF-8" ?> \n\n<template format_id="1.8" >\n'
           f"<content>{_xml_cdata(''.join(text))}</content>\n"
           f"<properties>{page}</properties>\n"
           f'<elements resolver="hvl-default" >\n{"".join(body)}\n</elements>\n'
           '<styles><style name="default" description="Geçerli" family="Dialog" size="12" bold="false" '
           'italic="false" foreground="-13421773" />'
           f'<style name="hvl-default" family={quoteattr(base_family)} size="{base_size:g}" description="Gövde" />'
           "</styles>\n</template>\n")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("content.xml", xml.encode("utf-8"))
    return sorted(warnings)
