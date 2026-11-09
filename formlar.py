"""PDF formları: doldurulabilir alanların listesi ve girilen değerlerin belgeye yazılması (belge ekranında form
doldurma)."""
import re

import pymupdf

from tools import ToolError


FIELD_KINDS = {pymupdf.PDF_WIDGET_TYPE_TEXT: "text", pymupdf.PDF_WIDGET_TYPE_CHECKBOX: "check",
               pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON: "radio", pymupdf.PDF_WIDGET_TYPE_COMBOBOX: "choice",
               pymupdf.PDF_WIDGET_TYPE_LISTBOX: "choice"}


def form_fields(doc):
    """Doldurulabilir form alanları, okunma sırasıyla (ekran koordinatlarında, 0–1 arası). İmza alanı ve düğmeler
    alınmaz. Seçenek düğmeleri aynı adı taşıyan bir grup oluşturur."""
    out = []
    for i, page in enumerate(doc):
        W, H, m = page.rect.width, page.rect.height, page.rotation_matrix
        for w in page.widgets():
            kind = FIELD_KINDS.get(w.field_type)
            if not kind:
                continue
            r = (w.rect * m).normalize()
            f = {"page": i, "xref": w.xref, "name": w.field_name or "", "label": w.field_label or "", "type": kind,
                 "x": r.x0 / W, "y": r.y0 / H, "w": r.width / W, "h": r.height / H,
                 "readonly": bool(w.field_flags & pymupdf.PDF_FIELD_IS_READ_ONLY)}
            if kind == "text":
                f |= {"value": w.field_value or "", "multiline": bool(w.field_flags & pymupdf.PDF_TX_FIELD_IS_MULTILINE),
                      "maxlen": w.text_maxlen or 0, "size": w.text_fontsize or 0}
            elif kind == "choice":
                opts = [[c, c] if isinstance(c, str) else [c[0], c[1]] for c in (w.choice_values or [])]
                f |= {"value": w.field_value or "", "options": opts, "size": w.text_fontsize or 0}
            else:
                f["checked"] = w.field_value not in (False, None, "", "Off")
            out.append(f)
    out.sort(key=lambda f: (f["page"], round(f["y"], 3), f["x"]))
    return out


def _fix_text_appearance(doc, w):
    """MuPDF'in tek satırlı metin alanı ve açılır liste için çizdiği görünümde taban çizgisi kutunun altına düşüyor
    (harflerin alt yarısı kesik görünür): yazı aynı yazı tipi ve harflerle kutunun dikey ortasına alınır."""
    ap = doc.xref_get_key(w.xref, "AP/N")
    found = re.match(r"(\d+) 0 R", ap[1] or "") if ap[0] == "xref" else None
    if not found:
        return
    n = int(found.group(1))
    s = doc.xref_stream(n).decode("latin-1")
    H, W, fs = w.rect.height, w.rect.width, w.text_fontsize
    fixed = re.sub(r"1 0 0 -1 ([-\d.]+) [-\d.]+ Tm", lambda t: f"1 0 0 -1 {t.group(1)} {(H + fs * 0.7) / 2:.2f} Tm", s)
    fixed = re.sub(r"(cm\nq\n)[-\d.]+ [-\d.]+ [-\d.]+ [-\d.]+ re\nW n", rf"\g<1>2 0 {W - 4:.2f} {H:.2f} re\nW n", fixed)
    if fixed != s:
        doc.update_stream(n, fixed.encode("latin-1"))


def op_fill_form(doc, values):
    """Form alanlarını doldurur. values: [{page, xref, value}] — metin ve liste: yazı; onay kutusu: açık/kapalı;
    seçenek düğmesi: seçilen (gruptaki öbürleri kapanır). Salt okunur alanlara dokunulmaz."""
    for v in values or []:
        page = doc[int(v["page"])]
        w = next((w for w in page.widgets() if w.xref == int(v["xref"])), None)
        if w is None:
            raise ToolError("Form alanı bulunamadı; belge değişmiş olabilir.")
        if w.field_flags & pymupdf.PDF_FIELD_IS_READ_ONLY:
            continue
        if w.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON and v["value"]:
            for other_page in doc:
                for o in list(other_page.widgets()):
                    if (o.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON and o.field_name == w.field_name
                            and o.xref != w.xref and o.field_value not in (False, None, "", "Off")):
                        o.field_value = False
                        o.update()
            w = next(w for w in page.widgets() if w.xref == int(v["xref"]))
        if w.field_type in (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON):
            w.field_value = bool(v["value"])
            w.update()
            continue
        multiline = bool(w.field_flags & pymupdf.PDF_TX_FIELD_IS_MULTILINE)
        if not w.text_fontsize:   # "otomatik" boyutta MuPDF yazıyı hiç çizmiyor
            w.text_fontsize = 10 if multiline else round(min(12, max(6, w.rect.height * 0.6)), 1)
        text = str(v["value"])
        w.field_value = text or " "   # PyMuPDF boş değeri yok sayar: görünüm bir boşlukla boşaltılır, değer sonra silinir
        w.update()
        if (w.field_type == pymupdf.PDF_WIDGET_TYPE_TEXT and not multiline) or w.field_type == pymupdf.PDF_WIDGET_TYPE_COMBOBOX:
            _fix_text_appearance(doc, w)
        if not text:
            doc.xref_set_key(w.xref, "V", "()")
