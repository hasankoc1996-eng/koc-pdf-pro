"""Kullanım kılavuzunun PDF hâli (Kılavuz ekranındaki "PDF olarak kaydet"). Kılavuz sayfasının HTML'i
(static/kilavuz/kilavuz.html; Windows'ta kısayolları Ctrl / Shift olarak çevrilir) MuPDF'in HTML dizgisiyle
A4 sayfalara dökülür: kapak ve sayfa numaralı içindekiler, bölümler yeni sayfadan, ekran görüntüleri, yer imleri,
içerideki bağlantılar ve alt bilgide sayfa numarası."""

import html as htmlmod
import io
import re
from datetime import date
from pathlib import Path

import pymupdf
from PIL import Image

PAGE = pymupdf.paper_rect("a4")
BODY = PAGE + (54, 50, -54, -58)   # yazı alanı; altta sayfa numarasına yer
RED = "#c0392b"
# Renkli kutularda üst/alt boşluk padding değil kendi renginde kenarlık: MuPDF dikey padding'li renkli kutunun
# (tablo başlığının da) bir şeridini sonraki sayfalara da çiziyor.
CSS = """
* { font-family: sans-serif; }
body { font-size: 10pt; line-height: 1.45; color: #222; }
h1 { font-size: 26pt; color: #c0392b; margin: 120pt 0 6pt; }
.cover-sub { font-size: 12pt; color: #555; margin: 0 0 60pt; }
.toc-h { font-size: 15pt; margin: 0 0 8pt; }
.toc p { margin: 0 0 3pt; }
.toc p.t2 { margin-left: 14pt; font-size: 9.5pt; color: #444; }
h2 { font-size: 17pt; color: #c0392b; margin: 0 0 8pt; page-break-before: always; }
h3 { font-size: 12.5pt; margin: 14pt 0 5pt; }
p { margin: 0 0 6pt; }
ul, ol { margin: 0 0 6pt; }
li { margin: 0 0 3pt; }
figure { margin: 8pt 0 10pt; text-align: center; }
figcaption { font-size: 8.5pt; color: #666; margin-top: 3pt; }
.g-tip { background-color: #e8f5ec; padding: 0 8pt; border-top: 5pt solid #e8f5ec; border-bottom: 5pt solid #e8f5ec; }
.g-warn { background-color: #fdecea; padding: 0 8pt; border-top: 5pt solid #fdecea; border-bottom: 5pt solid #fdecea; }
kbd { font-size: 9pt; background-color: #eeeeee; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 8pt; }
td, th { border: 0.5pt solid #bbbbbb; padding: 3pt 5pt; font-size: 9pt; text-align: left; }
"""
IMAGE_WIDTH = 1200   # PDF'e giren ekran görüntüsünün genişliği (piksel): yazı alanında ~190 dpi

# Arayüzdeki Windows çevirisinin (app.js › WIN_TEXT) kılavuzda geçenleri
WIN_TEXT = [("⇧⌘", "Ctrl+Shift+"), ("⌘ veya ⇧", "Ctrl veya Shift"), ("⌘", "Ctrl+"), ("⌃", "Ctrl+"), ("⇧", "Shift+"),
            ("↵", "Enter"), ("⌫", "Delete"), ("⌥", "Alt"), ("Finder'da", "Dosya Gezgini'nde")]

_HEADING = re.compile(r'<section class="g-(part|sub)" id="([^"]+)">\s*<h([23])>(.*?)</h\3>', re.S)
# Resimli figure'ın açılış etiketi; resim bir alt başlığın hemen altındaysa bölümün açılış etiketi (sayfa sonu
# başlığın önüne konur, başlık resminden ayrılmaz). Sayfa sonu etiketin kendi stilinde: araya konan boş div'i MuPDF
# bölüm ve başlık önünde yok sayıp bölümü sayfanın altından dışarı diziyordu.
_FIGURE = re.compile(r'(<section class="g-sub" id="[^"]+")(?=>\s*<h3>(?:(?!</h3>).)*</h3>\s*<figure[^>]* data-k="(\d+)">)'
                     r'|(<figure[^>]* data-k="(\d+)")(?=>)', re.S)
_PAGE_BREAK = ' style="page-break-before: always"'
_TAG = re.compile(r"<[^>]+>")


def headings(source):
    """Bölüm ve alt başlıklar sırasıyla: [(düzey, id, başlık)]."""
    return [(1 if kind == "part" else 2, sid, htmlmod.unescape(_TAG.sub("", text)).strip())
            for kind, sid, _, text in _HEADING.findall(source)]


def windows_text(source):
    """Mac kısayol işaretleri ve Finder ifadeleri Windows karşılıklarıyla (yalnızca yazılarda, etiketlerde değil)."""
    def text(m):
        t = m.group(0)
        for a, z in WIN_TEXT:
            t = t.replace(a, z)
        return t
    return re.sub(r"(?<=>)[^<]+", text, source)


def _link(sid, text):
    # MuPDF'in kendi biçimi bağlantıyı mavi ve altı çizili yapar; satır içi biçim onu geçer
    return f'<a href="#{sid}" style="color:{RED};text-decoration:none">{text}</a>'


def _image(path):
    """Ekran görüntüsü PDF'e JPEG olarak girer (PNG'yi MuPDF sıkıştırmadan saklar, dosya birkaç kat büyür)."""
    with Image.open(path) as im:
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, "white")
        flat.paste(im, mask=im)
    if flat.width > IMAGE_WIDTH:
        flat = flat.resize((IMAGE_WIDTH, round(flat.height * IMAGE_WIDTH / flat.width)), Image.LANCZOS)
    buf = io.BytesIO()
    flat.save(buf, "JPEG", quality=80, optimize=True)
    return buf.getvalue()


def _prepare(source, images, archive):
    """Kılavuz HTML'i dizgiye hazır hâle: resimler arşive, iç bağlantılar #id (olmayan başlığa giden bağlantı düz
    yazı olur), resim genişlikleri yazı alanına göre (dar resimler daha küçük). Resimli her figure'a sıra numarası
    (data-k) ve kimlik (kfig<sıra>) verilir; dönen liste resimlerin istenen (genişlik, yükseklik) ölçüleri."""
    out = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    out = re.sub(r'<a href="#" data-to="([^"]+)">(.*?)</a>',
                 lambda m: _link(m.group(1), m.group(2)) if m.group(1) in ids else m.group(2), out, flags=re.S)
    sizes = []

    def img(m):
        name = m.group(2)
        try:
            with Image.open(images / name) as im:
                w, h = im.size
            data = _image(images / name)
        except OSError:
            return m.group(1)   # resim yoksa yeri boş kalır
        narrow = "g-narrow" in m.group(1)
        shown = min(BODY.width * (0.62 if narrow else 1.0), w / 2)   # ekran görüntüleri 2× çekildi
        if h * shown / w > BODY.height * 0.62:   # uzun resim sayfayı doldurmasın
            shown = BODY.height * 0.62 * w / h
        jpg = Path(name).stem + ".jpg"
        archive.add(data, jpg)
        sizes.append((shown, h * shown / w))
        k = len(sizes) - 1
        return (f'{m.group(1)[:-1]} id="kfig{k}" data-k="{k}">'
                f'<img src="{jpg}" width="{shown:.0f}" height="{h * shown / w:.0f}">')
    out = re.sub(r'(<figure[^>]*>)<img src="/static/kilavuz/([^"]+)"[^>]*>', img, out)
    return out, sizes


def _cover(version, toc, pages=None):
    rows = "".join(f'<p class="t{lvl}">{_link(sid, htmlmod.escape(title))}'
                   f'{" · s. " + str(pages[sid]) if pages and sid in pages else ""}</p>'
                   for lvl, sid, title in toc)
    today = date.today().strftime("%d.%m.%Y")
    sub = f"Kullanım Kılavuzu · Sürüm {htmlmod.escape(version)}" if version else "Kullanım Kılavuzu"
    return (f'<h1>Koç PDF Pro</h1><p class="cover-sub">{sub} · {today}</p>'
            f'<p class="toc-h">İçindekiler</p><div class="toc">{rows}</div>')


def _render(html, archive):
    """HTML → PDF; başlıkların sayfaları ({id: sayfa}) ve resimli figure'ların yerleri ({sıra: (sayfa, kutu)}) da
    döner."""
    pages, figures = {}, {}

    def where(pos):
        if not (pos.id and pos.open_close & 1):
            return
        fig = re.fullmatch(r"kfig(\d+)", pos.id)
        if fig:
            figures.setdefault(int(fig.group(1)), (pos.page_num - 1, pymupdf.Rect(pos.rect)))
        else:
            pages.setdefault(pos.id, pos.page_num)

    story = pymupdf.Story(html=html, user_css=CSS, archive=archive)
    doc = story.write_with_links(lambda n, filled: (PAGE, BODY, None), where)
    return doc, pages, figures


def _misplaced(doc, figures, sizes):
    """Sayfa sonuna sığmadığı için MuPDF'in küçülttüğü, sayfanın altından dışarı dizdiği ya da hiç dizmediği resimlerin
    sıra numaraları. Resimler sırayla değil figure'ın yeriyle eşlenir: biri düşünce sıra kayar, sonrakiler yanlış
    eşlenirdi (bir maddenin uzayıp sayfa sonunu kaydırması kılavuzun yarısını bozuyordu)."""
    bad = set()
    for k, (width, _) in enumerate(sizes):
        page, box = figures.get(k, (None, None))
        if page is None or not 0 <= page < doc.page_count or box.y1 > BODY.y1 + 1:
            bad.add(k)
            continue
        shown = [pymupdf.Rect(i["bbox"]) for i in doc[page].get_image_info()]
        shown = [r.width for r in shown if r.intersects(box) and box.contains(r.tl + (0.5, 0.5))]
        if not shown or max(shown) < width * 0.85:
            bad.add(k)
    return bad


def _shrunk(doc, sizes):
    """Bitmiş PDF'te istenenden dar çıkan resimlerin sıra numaraları; resim sayısı tutmuyorsa (biri düşmüşse) hepsi."""
    shown = [pymupdf.Rect(i["bbox"]).width for page in doc
             for i in sorted(page.get_image_info(), key=lambda i: i["bbox"][1])]
    if len(shown) != len(sizes):
        return set(range(len(sizes)))
    return {k for k, (got, (want, _)) in enumerate(zip(shown, sizes)) if got < want * 0.85}


def _with_breaks(body, breaks):
    """breaks'teki resimler yeni sayfadan başlar (alt başlığın hemen altındaysa başlığıyla birlikte)."""
    headed = set()

    def tag(m):
        if m.group(1):   # bölüm, ardından gelen resim için
            headed.add(int(m.group(2)))
            return m.group(1) + (_PAGE_BREAK if int(m.group(2)) in breaks else "")
        k = int(m.group(4))   # resim; başlığıyla birlikte geçtiyse kendisine ikinci kez konmaz
        return m.group(3) + (_PAGE_BREAK if k in breaks and k not in headed else "")
    return _FIGURE.sub(tag, body)


def build_pdf(source, images, dst, version=None, windows=False):
    """source: kılavuz HTML'i, images: ekran görüntülerinin klasörü, dst: yazılacak PDF. Sayfa sayısı döner."""
    if windows:
        source = windows_text(source)
    archive = pymupdf.Archive()
    body, sizes = _prepare(source, Path(images), archive)
    toc = headings(source)
    # Sayfa sonuna sığmayan resim küçülmesin, sonraki sayfaya geçsin; içindekilerdeki sayfa numaraları da son
    # dizgiden. Her geçişte yerleşim değişebildiği için birkaç kez dizilir.
    breaks, pages = set(), None
    for _ in range(8):
        html = _cover(version, toc, pages) + _with_breaks(body, breaks)
        doc, found, figures = _render(html, archive)
        more = _misplaced(doc, figures, sizes) - breaks
        if not more and found == pages:
            break
        breaks |= more
        pages = found
    doc.set_toc([[lvl, title, found[sid]] for lvl, sid, title in toc if sid in found])
    doc.set_metadata({"title": "Koç PDF Pro Kullanım Kılavuzu", "author": "Koç PDF Pro", "creator": "Koç PDF Pro"})
    for page in doc:
        if page.number:
            page.insert_htmlbox(pymupdf.Rect(BODY.x0, PAGE.y1 - 40, BODY.x1, PAGE.y1 - 22),
                                f'<p style="text-align:center;font-size:8pt;color:#888">Koç PDF Pro Kullanım Kılavuzu · '
                                f'{page.number + 1}</p>', css="* { font-family: sans-serif; }")
    doc.subset_fonts()   # simge yazı tipleri (⌘, ›, →) bütünüyle girmesin
    doc.save(dst, garbage=3, deflate=True)
    return doc.page_count
