"""Tek seferlik PDF araçları: birleştir, böl, sıkıştır, şifrele, filigran, sayfa numarası."""
import errno
import os
import re
import shutil
import sys
from pathlib import Path

import pymupdf

if sys.platform == "win32":
    FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    FONTS = {
        ("sans", False): FONT_DIR / "arial.ttf",
        ("sans", True): FONT_DIR / "arialbd.ttf",
        ("serif", False): FONT_DIR / "times.ttf",
        ("serif", True): FONT_DIR / "timesbd.ttf",
    }
else:
    FONT_DIR = Path("/System/Library/Fonts/Supplemental")
    FONTS = {
        ("sans", False): FONT_DIR / "Arial.ttf",
        ("sans", True): FONT_DIR / "Arial Bold.ttf",
        ("serif", False): FONT_DIR / "Times New Roman.ttf",
        ("serif", True): FONT_DIR / "Times New Roman Bold.ttf",
    }


class ToolError(Exception):
    pass


def disk_full(e, folder=None):
    """Yazma, diskte yer kalmadığı için mi yarıda kaldı? PyMuPDF işletim sisteminin hatasını kendi mesajıyla
    bildirir ("cannot write ...: No space left on device"); mesajdan anlaşılmazsa klasördeki boş yere bakılır."""
    if isinstance(e, OSError) and e.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)):
        return True
    if "no space" in str(e).lower():
        return True
    try:
        return folder is not None and shutil.disk_usage(folder).free < 64 * 2**20
    except OSError:
        return False


def font_for(family="sans", bold=False):
    """Türkçe karakterleri (ğ, ş, ı, İ) destekleyen bir TTF döndürür."""
    path = FONTS.get((family, bold)) or FONTS[("sans", False)]
    if path.exists():
        return f"PSF{family[0]}{int(bold)}", str(path)
    # Arial yoksa PyMuPDF'in gömülü Noto fontuna düş
    return "notos", None


def hex_to_rgb(value, default=(0, 0, 0)):
    value = (value or "").lstrip("#")
    if len(value) != 6:
        return default
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def open_pdf(path, password=None):
    try:
        doc = pymupdf.open(path)
    except Exception:
        raise ToolError(f"{Path(path).name} açılamadı; dosya bozuk ya da PDF değil.")
    if doc.needs_pass and not (password and doc.authenticate(password)):
        raise ToolError(f"{Path(path).name} şifreli. Önce 'Şifre Kaldır' aracını kullanın.")
    return doc


def fix_spaces(doc, all_fonts=False):
    """PyMuPDF eklediği fontlarda boşluk glifini U+00A0'a, tireyi U+00AD'ye eşliyor; bu da kopyalama
    ve aramayı bozuyor. Bizim eklediğimiz (PSF önekli) ya da istenirse tüm fontlarda düzeltir."""
    seen = set()
    for page in doc:
        for xref, _ext, _type, _base, name, _enc in page.get_fonts():
            if xref in seen or not (all_fonts or name.startswith("PSF")):
                continue
            seen.add(xref)
            kind, value = doc.xref_get_key(xref, "ToUnicode")
            if kind != "xref":
                continue
            tu = int(value.split()[0])
            cmap = doc.xref_stream(tu).decode("latin-1")
            fixed = re.sub(r"^(<[0-9a-fA-F]{4}>) <00[aA]0>\s*$", r"\1 <0020>", cmap, flags=re.M)
            fixed = re.sub(r"^(<[0-9a-fA-F]{4}>) <00[aA][dD]>\s*$", r"\1 <002d>", fixed, flags=re.M)
            if fixed != cmap:
                doc.update_stream(tu, fixed.encode("latin-1"))


def finalize(doc, all_fonts=False):
    """Kaydetmeden önce: eklenen fontları küçült ve metin eşlemesini düzelt."""
    try:
        doc.subset_fonts()
    except Exception:
        pass
    fix_spaces(doc, all_fonts=all_fonts)


def save_pdf(doc, dst, **kw):
    opts = dict(garbage=3, deflate=True)
    opts.update(kw)
    finalize(doc)
    doc.save(dst, **opts)
    doc.close()


def parse_ranges(spec, page_count):
    """'1-3, 5, 8-' → [[0,1,2],[4],[7..n-1]] (her virgül bir grup)."""
    groups = []
    for part in re.split(r"[,;]", spec or ""):
        part = part.strip().replace(" ", "")
        if not part:
            continue
        m = re.fullmatch(r"(\d*)-(\d*)", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else page_count
        elif part.isdigit():
            a = b = int(part)
        else:
            raise ToolError(f"Geçersiz sayfa aralığı: '{part}'")
        if a < 1 or b > page_count or a > b:
            raise ToolError(f"'{part}' aralığı geçersiz (belge {page_count} sayfa).")
        groups.append(list(range(a - 1, b)))
    if not groups:
        raise ToolError("Sayfa aralığı girin, örn: 1-3, 5")
    return groups


def merge(srcs, dst, titles=None):
    """PDF'leri sırayla birleştirir; titles verilirse her dosya içindekiler listesinde bir başlık olur."""
    if len(srcs) < 2:
        raise ToolError("Birleştirmek için en az 2 dosya seçin.")
    out, toc = pymupdf.open(), []
    for k, src in enumerate(srcs):
        doc = open_pdf(src)
        if titles:
            toc.append([1, titles[k], out.page_count + 1])
            toc.extend([level + 1, title, out.page_count + page] for level, title, page, *_ in doc.get_toc(simple=False)
                       if page > 0)   # dosyanın kendi bölümleri onun altında
        out.insert_pdf(doc)
        doc.close()
    if toc:
        out.set_toc(toc)
    save_pdf(out, dst)


def split(src, out_dir, mode="each", spec="", every=1):
    """mode: 'each' her sayfa ayrı | 'ranges' her aralık ayrı | 'every' N sayfada bir | 'extract' aralıklar tek dosya"""
    doc = open_pdf(src)
    n = doc.page_count
    stem = Path(src).stem
    if mode == "each":
        groups = [[i] for i in range(n)]
    elif mode == "every":
        every = max(1, int(every))
        groups = [list(range(i, min(i + every, n))) for i in range(0, n, every)]
    else:
        groups = parse_ranges(spec, n)
        if mode == "extract":
            groups = [[p for g in groups for p in g]]
    outputs = []
    for g in groups:
        label = f"{g[0] + 1}" if len(g) == 1 else f"{g[0] + 1}-{g[-1] + 1}"
        name = f"{stem}_sayfa_{label}.pdf" if mode != "extract" else f"{stem}_secilen_sayfalar.pdf"
        path = Path(out_dir) / name
        save_pdf(pages_doc(doc, g), path)
        outputs.append(path)
    doc.close()
    return outputs   # sayfa sırasıyla


def part_toc(toc, pages):
    """Parçaya düşen yer imleri: sayfa numaraları parçadaki yerine taşınır, en üst seviye 1 olur (set_toc ister)."""
    where = {p: k + 1 for k, p in enumerate(pages)}   # özgün sayfa (0'dan) → parçadaki sayfa (1'den)
    kept = [(level, title, where[page - 1]) for level, title, page, *_ in toc if page - 1 in where]
    if not kept:
        return []
    base, prev, out = min(level for level, _, _ in kept) - 1, 0, []
    for level, title, page in kept:
        level = min(level - base, prev + 1)
        out.append([level, title, page])
        prev = level
    return out


def toc_plan(doc):
    """İçindekilere göre bölme: en üstteki (en az iki başlığı olan) seviyenin her başlığı bir parçanın başı ve adı.
    Dönen: {cuts: [bu sayfadan sonra kes], names: {parçanın ilk sayfası: başlık}, note}"""
    toc = [(level, title.strip(), page - 1) for level, title, page, *_ in doc.get_toc() if 1 <= page <= doc.page_count]
    if not toc:
        raise ToolError("Bu belgede içindekiler (yer imi) yok; kesimleri elle yapın.")
    levels = sorted({level for level, _, _ in toc})
    level = next((lv for lv in levels if len({p for v, _, p in toc if v == lv}) >= 2), levels[0])
    starts = {}
    for v, title, page in toc:
        if v == level:
            starts.setdefault(page, title or f"Bölüm {len(starts) + 1}")
    return {"cuts": sorted(p - 1 for p in starts if p > 0), "names": {str(p): t for p, t in starts.items()},
            "note": f"İçindekilerde {len(starts)} başlık bulundu" if len(starts) > 1 else "İçindekilerde tek başlık var"}


REF = re.compile(r"(\d+) 0 R")
TREE_TYPES = ("/Page", "/Pages", "/Catalog", "/Outlines")


def page_objects(doc, page):
    """Sayfanın kullandığı nesneler (içerik, resimler, yazı tipleri, notlar…). Başka sayfalara ve sayfa ağacına
    inilmez (bağlantılar başka sayfaları gösterse de); üst düğümden devralınan kaynaklar da sayılır."""
    stack, x = [page.xref], page.xref
    while doc.xref_get_key(x, "Resources")[0] == "null":   # devralınan /Resources
        kind, value = doc.xref_get_key(x, "Parent")
        if kind != "xref":
            break
        x = int(value.split()[0])
        if doc.xref_get_key(x, "Resources")[0] != "null":
            stack += [int(r) for r in REF.findall(doc.xref_get_key(x, "Resources")[1])]
    found = set()
    while stack:
        x = stack.pop()
        if x in found or not 0 < x < doc.xref_length():
            continue
        if x != page.xref and doc.xref_get_key(x, "Type")[1] in TREE_TYPES:
            continue
        found.add(x)
        stack += [int(r) for r in REF.findall(doc.xref_object(x, compressed=True))]
    return found


def pdf_bytes(doc):
    """Kaydedilince kaplayacağı yer (save_pdf ile aynı ayarlar)."""
    finalize(doc)
    return len(doc.tobytes(garbage=3, deflate=True))


def size_plan(doc, limit):
    """Boyuta göre bölme: sayfa sırası bozulmadan, her parça en fazla limit bayt. Önce sayfaların kullandığı nesnelerden
    tahmin edilir (ortak yazı tipleri ve resimler bir kez sayılır), sonra her parça gerçekten kaydedilip denenir; sınırı
    aşan parçanın son sayfası sonrakine geçer. Dönen: {cuts, sizes: {ilk sayfa: bayt}, note}"""
    import zlib
    known = {}

    def weight(x):   # kaydedilince kaplayacağı yer: sıkıştırılmamış akışlar kaydederken sıkıştırılır
        if x not in known:
            raw = (doc.xref_stream_raw(x) or b"") if doc.xref_is_stream(x) else b""
            if len(raw) > 2048 and doc.xref_get_key(x, "Filter")[0] == "null":
                raw = zlib.compress(raw, 1)
            known[x] = len(doc.xref_object(x, compressed=True)) + len(raw)
        return known[x]

    parts, cur, used, total = [], [], set(), 2000   # 2000: dosyanın başı, sayfa ağacı
    for page in doc:
        objs = page_objects(doc, page)
        extra = sum(weight(x) for x in objs - used)
        if cur and total + extra > limit * 0.97:
            parts.append(cur)
            cur, used, total = [], set(), 2000
            extra = sum(weight(x) for x in objs)
        cur.append(page.number)
        used |= objs
        total += extra
    parts.append(cur)
    sizes, k = [], 0
    while k < len(parts):
        part = parts[k]
        actual = pdf_bytes(pages_doc(doc, part))
        while actual > limit and len(part) > 1:   # tahmin az kaldıysa: son sayfa sonraki parçaya
            moved = part.pop()
            if k + 1 < len(parts):
                parts[k + 1].insert(0, moved)
            else:
                parts.append([moved])
            actual = pdf_bytes(pages_doc(doc, part))
        sizes.append(actual)
        k += 1
    mb = lambda b: f"{b / 1e6:.1f}".replace(".", ",").replace(",0", "") + " MB"
    over = [(p[0], b) for p, b in zip(parts, sizes) if b > limit]
    note = f"Her parça en fazla {mb(limit)}" if len(parts) > 1 else f"Dosya zaten {mb(limit)}'tan küçük; bölmeye gerek yok"
    if over:
        note += "; " + ", ".join(f"{p + 1}. sayfa tek başına {mb(b)}" for p, b in over[:3]) + " (önce Sıkıştır'ı deneyin)"
    return {"cuts": [p[-1] for p in parts[:-1]], "sizes": {str(p[0]): b for p, b in zip(parts, sizes)}, "note": note}


def is_blank(page):
    """Boş sayfa: metni yok, kenarlar (tarayıcının gölgesi) dışında koyu nokta binde 2'den az; kâğıt grisi sayılmaz."""
    if page.get_text("text").strip():
        return False
    r = page.rect
    clip = r + (r.width * .06, r.height * .06, -r.width * .06, -r.height * .06)
    pix = page.get_pixmap(dpi=30, clip=clip, colorspace=pymupdf.csGRAY, alpha=False)
    dark = len(pix.samples.translate(None, bytes(range(200, 256))))   # 200'den koyu noktalar
    return dark < pix.width * pix.height * 0.002


def blank_plan(doc):
    """Boş sayfalara göre bölme (aralarına boş kâğıt konarak topluca taranmış evrak): her boş sayfada yeni parça
    başlar, boş sayfalar alınmaz. Dönen: {cuts, skip, note}"""
    blanks = [page.number for page in doc if is_blank(page)]
    if not blanks:
        raise ToolError("Boş sayfa bulunamadı; kesimleri elle yapın.")
    cuts = {b - 1 for b in blanks if b > 0} | {b for b in blanks if b < doc.page_count - 1}
    return {"cuts": sorted(cuts), "skip": blanks, "note": f"{len(blanks)} boş sayfa bulundu"}


def pages_doc(doc, pages):
    """Seçilen sayfalardan yeni belge; ardışık sayfalar birlikte alınır (aralarındaki bağlantılar kalsın), yer imleri korunur."""
    part = pymupdf.open()
    k = 0
    while k < len(pages):
        j = k
        while j + 1 < len(pages) and pages[j + 1] == pages[j] + 1:
            j += 1
        part.insert_pdf(doc, from_page=pages[k], to_page=pages[j])
        k = j + 1
    toc = part_toc(doc.get_toc(), pages)
    if toc:
        part.set_toc(toc)
    return part


COMPRESS_LEVELS = {
    # seviye: (dpi eşiği, hedef dpi, jpeg kalitesi)
    "dusuk": None,  # yalnızca kayıpsız temizlik
    "orta": (170, 150, 75),
    "ara": (130, 120, 65),   # ara ve en-yuksek yalnızca hedef boyuta inerken denenir
    "yuksek": (110, 96, 55),
    "en-yuksek": (80, 72, 45),
}
COMPRESS_STEPS = ["dusuk", "orta", "ara", "yuksek", "en-yuksek"]   # hedef boyuta inerken sırayla
BITONAL_DPI = {"dusuk": 300, "orta": 200, "ara": 200, "yuksek": 150, "en-yuksek": 120}   # siyah-beyaz taramada
COLORS = ("renkli", "gri", "sb")


def _image_xrefs(doc):
    return {x for x in range(1, doc.xref_length()) if doc.xref_get_key(x, "Subtype")[1] == "/Image"}


def rewrite_images(doc, threshold, target, quality, bitonal=True):
    """Eşikten yüksek çözünürlüklü resimler hedef dpi'ye iner ve JPEG olur (yalnızca küçülüyorsa). Bicubic: MuPDF'in
    varsayılanı (average) yalnız ikinin katlarıyla küçültür; 300 dpi tarama 150'ye inmez, 96 yerine 150'de kalır.
    Siyah-beyaz resimler okunaklı kalsın diye 300 dpi'nin altına indirilmez; bitonal=False ise hiç dokunulmaz."""
    from pymupdf import mupdf
    o = mupdf.PdfImageRewriterOptions()
    for kind in ("color_lossless", "color_lossy", "gray_lossless", "gray_lossy"):
        setattr(o, f"{kind}_image_recompress_method", mupdf.FZ_RECOMPRESS_JPEG)
        setattr(o, f"{kind}_image_recompress_quality", str(quality))
        setattr(o, f"{kind}_image_subsample_method", mupdf.FZ_SUBSAMPLE_BICUBIC)
        setattr(o, f"{kind}_image_subsample_threshold", threshold)
        setattr(o, f"{kind}_image_subsample_to", target)
    if bitonal:
        o.bitonal_image_recompress_method = mupdf.FZ_RECOMPRESS_FAX
        o.bitonal_image_subsample_method = mupdf.FZ_SUBSAMPLE_AVERAGE
        o.bitonal_image_subsample_threshold = 450
        o.bitonal_image_subsample_to = 300
    o.recompress_when = mupdf.FZ_RECOMPRESS_WHEN_SMALLER
    doc.rewrite_images(options=o)


def _otsu(hist):
    """Gri tonlu resmi siyah-beyaza ayıran eşik (Otsu): yazı ile kâğıt arasındaki en iyi ayrım."""
    total, weighted = sum(hist), sum(i * h for i, h in enumerate(hist))
    back = back_sum = 0
    best, threshold = 0, 128
    for t, h in enumerate(hist):
        back += h
        if not back:
            continue
        fore = total - back
        if not fore:
            break
        back_sum += t * h
        between = back * fore * (back_sum / back - (weighted - back_sum) / fore) ** 2
        if between > best:
            best, threshold = between, t
    return threshold


def to_bitonal(doc, dpi):
    """Sayfanın yarısından büyük resimler (taranmış sayfalar) siyah-beyaz olur; eşik her resimde ayrı bulunur,
    çözünürlük en fazla dpi. Metin tanıma katmanı ve sayfadaki diğer her şey olduğu gibi kalır. Dönen: sayfa sayısı"""
    from PIL import Image
    done, pages = set(), set()
    for page in doc:
        for info in page.get_images(full=True):
            xref, bpc = info[0], info[4]
            if bpc == 1 and xref not in done:   # zaten siyah-beyaz
                continue
            try:
                box = page.get_image_bbox(info)
            except Exception:   # form nesnesinin içindeki resim
                continue
            if box.is_infinite or box.is_empty or abs(box & page.rect) < abs(page.rect) * 0.5:
                continue
            pages.add(page.number)
            if xref in done:   # aynı resim başka sayfada da kullanılmış
                continue
            done.add(xref)
            pix = pymupdf.Pixmap(doc, xref)
            if pix.alpha:
                pix = pymupdf.Pixmap(pix, 0)
            if pix.n != 1:
                pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
            im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            current = (pix.width * pix.height / (box.width * box.height)) ** 0.5 * 72   # döndürülmüş resimde de doğru
            if current > dpi:
                k = dpi / current
                im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
            t = _otsu(im.histogram())
            bw = im.point(lambda v: 255 if v > t else 0).convert("1")
            doc.update_stream(xref, bw.tobytes(), compress=True)
            for key, value in (("Width", str(bw.width)), ("Height", str(bw.height)), ("BitsPerComponent", "1"),
                               ("ColorSpace", "/DeviceGray"), ("DecodeParms", "null"), ("Decode", "null"),
                               ("SMask", "null"), ("Mask", "null"), ("Interpolate", "null")):
                doc.xref_set_key(xref, key, value)
    return len(pages)


def compress(src, dst, level="orta", color="renkli", drop=()):
    """color: renkli (olduğu gibi), gri (bütün belge) ya da sb (taranmış sayfalar siyah-beyaz, gerisi gri).
    drop: "attachments" (gömülü ek dosyalar), "meta" (yazar, program, tarih). Sayfa küçük resimleri her düzeyde
    kaldırılır (görüntüleyiciler kendileri çizer). Dönen: yapılanlar {images: küçültülen resim sayısı, found: belgedeki
    resim sayısı, bitonal, gray, thumbs, attachments, meta}"""
    doc = open_pdf(src)
    params = COMPRESS_LEVELS.get(level, COMPRESS_LEVELS["orta"])
    before = _image_xrefs(doc)
    stats = {"images": 0, "found": len(before), "bitonal": 0, "gray": color in ("gri", "sb"),
             "thumbs": 0, "attachments": 0, "meta": False}
    for page in doc:
        if doc.xref_get_key(page.xref, "Thumb")[0] != "null":
            doc.xref_set_key(page.xref, "Thumb", "null")
            stats["thumbs"] += 1
    if "attachments" in drop:
        for name in doc.embfile_names():
            doc.embfile_del(name)
            stats["attachments"] += 1
    if "meta" in drop:
        doc.set_metadata({})
        doc.del_xml_metadata()
        stats["meta"] = True
    if color == "sb":   # özgün resimden: önce küçültülüp bozulmuş resimden değil
        stats["bitonal"] = to_bitonal(doc, BITONAL_DPI.get(level, 200))
    if stats["gray"]:
        doc.recolor(1)
    if params:
        marked = _image_xrefs(doc)
        rewrite_images(doc, *params, bitonal=not stats["bitonal"])   # az önce siyah-beyaz yapılanlar yeniden yazılmaz
        stats["images"] = len(_image_xrefs(doc) - marked)   # yeniden yazılan her resim yeni bir nesne olur
    try:
        doc.subset_fonts()
    except Exception:
        pass
    save_pdf(doc, dst, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True,
             clean=True, use_objstms=1)
    return stats


def protect(src, dst, user_pw, owner_pw=None, allow_print=True, allow_copy=False):
    if not user_pw:
        raise ToolError("Şifre boş olamaz.")
    doc = open_pdf(src)
    perm = pymupdf.PDF_PERM_ACCESSIBILITY
    if allow_print:
        perm |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    if allow_copy:
        perm |= pymupdf.PDF_PERM_COPY
    save_pdf(doc, dst, encryption=pymupdf.PDF_ENCRYPT_AES_256,
             user_pw=user_pw, owner_pw=owner_pw or user_pw, permissions=perm)


def export_pdf(src, dst, flatten=False, shrink=False, clean_meta=False, password=""):
    """Farklı Kaydet seçenekleri tek geçişte: düzleştir (notlar, vurgular, form alanları sayfaya işlenir; silinemez),
    küçült (orta düzey), belge bilgilerini temizle, şifrele (açmak için şifre; yazdırılabilir, kopyalanamaz)."""
    doc = open_pdf(src)
    opts = {}
    if flatten:
        doc.bake(annots=True, widgets=True)
    if shrink:
        rewrite_images(doc, *COMPRESS_LEVELS["orta"])
        opts.update(garbage=4, deflate_images=True, deflate_fonts=True, clean=True, use_objstms=1)
    if clean_meta:
        doc.set_metadata({})
        doc.del_xml_metadata()
    if password:
        opts.update(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password,
                    permissions=pymupdf.PDF_PERM_ACCESSIBILITY | pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ)
    save_pdf(doc, dst, **opts)


def unlock(src, dst, password):
    doc = pymupdf.open(src)
    if doc.needs_pass and not doc.authenticate(password or ""):
        raise ToolError("Şifre yanlış.")
    save_pdf(doc, dst, encryption=pymupdf.PDF_ENCRYPT_NONE)


def watermark(src, dst, text, size=60, opacity=0.18, color="#c0392b", angle=45, pages_spec=""):
    if not text.strip():
        raise ToolError("Filigran metni girin.")
    doc = open_pdf(src)
    fname, ffile = font_for("sans", True)
    font = pymupdf.Font(fontfile=ffile) if ffile else pymupdf.Font(fname)
    rgb = hex_to_rgb(color)
    targets = range(doc.page_count)
    if pages_spec.strip():
        targets = sorted({p for g in parse_ranges(pages_spec, doc.page_count) for p in g})
    for i in targets:
        page = doc[i]
        disp = page.rect  # ekranda görünen boyut
        tw = font.text_length(text, fontsize=size)
        center = pymupdf.Point(disp.width / 2, disp.height / 2)
        start = pymupdf.Point(center.x - tw / 2, center.y + size * 0.35)
        # Ekran koordinatlarından sayfanın yerel koordinatlarına
        start_n = start * page.derotation_matrix
        center_n = center * page.derotation_matrix
        mat = pymupdf.Matrix(angle)
        page.insert_text(start_n, text, fontsize=size, fontname=fname, fontfile=ffile,
                         color=rgb, fill_opacity=opacity, stroke_opacity=opacity,
                         rotate=page.rotation, morph=(center_n, mat), overlay=True)
    save_pdf(doc, dst)


NUMBER_FORMATS = {
    "n": "{sayfa}",
    "n/t": "{sayfa} / {toplam}",
    "sayfa n": "Sayfa {sayfa}",
    "sayfa n/t": "Sayfa {sayfa} / {toplam}",
    "-n-": "- {sayfa} -",
    "ek": "Ek:{ek}/{sayfa}",          # Ek:1/1, Ek:1/2 … (ek numarası / ekin kaçıncı sayfası)
    "ek-sayfa": "EK-{ek} / Sayfa {sayfa}",
}
EK_FORMATS = {"ek", "ek-sayfa", "custom"}


def number_label(template, sayfa, toplam, ek=1):
    """Özel biçimde {n} → ek numarası, {t} → ekin kaçıncı sayfası, {toplam} → son sayfa numarası."""
    values = {"sayfa": sayfa, "toplam": toplam, "ek": ek, "n": ek, "t": sayfa}
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template)


def page_numbers(src, dst, position="alt-orta", fmt="n", start=1, size=11, margin=28,
                 skip_first=False, color="#000000", template=None, bold=False, font="serif", ek=1):
    doc = open_pdf(src)
    fname, ffile = font_for(font if font in ("serif", "sans") else "serif", bold)
    font = pymupdf.Font(fontfile=ffile) if ffile else pymupdf.Font(fname)
    if fmt == "custom":
        template = (template or "").strip()
        if not template:
            raise ToolError("Özel biçim için bir metin yazın, örn: EK-{n} Sayfa {t}")
    else:
        template = NUMBER_FORMATS.get(fmt, "{n}")
    total = doc.page_count - (1 if skip_first else 0) + int(start) - 1
    rgb = hex_to_rgb(color)
    for i, page in enumerate(doc):
        if skip_first and i == 0:
            continue
        n = i + int(start) - (1 if skip_first else 0)
        label = number_label(template, n, total, ek)
        disp = page.rect
        tw = font.text_length(label, fontsize=size)
        vert, horiz = position.split("-")
        y = margin + size * 0.8 if vert == "ust" else disp.height - margin
        x = {"sol": margin, "orta": (disp.width - tw) / 2, "sag": disp.width - margin - tw}[horiz]
        pt = pymupdf.Point(x, y) * page.derotation_matrix
        page.insert_text(pt, label, fontsize=size, fontname=fname, fontfile=ffile,
                         color=rgb, rotate=page.rotation, overlay=True)
    save_pdf(doc, dst)


def info(src):
    doc = pymupdf.open(src)
    meta = doc.metadata or {}
    res = {
        "sayfa": doc.page_count if not doc.needs_pass else None,
        "sifreli": doc.needs_pass,
        "baslik": meta.get("title"),
        "yazar": meta.get("author"),
    }
    doc.close()
    return res
