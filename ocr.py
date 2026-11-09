"""Taranmış (resim) sayfalara görünmez metin katmanı ekler: PDF aranabilir ve kopyalanabilir olur.

Metin tanıma bilgisayarın kendi motoruyla yapılır (internetsiz):
  • Mac: Apple Vision. Tanıma işini native/ocr.swift'ten derlenen `kocpdf-ocr` yardımcısı yapar;
    Mac uygulaması yolunu PDFSTUDYO_OCR_BIN ortam değişkeniyle bildirir.
  • Windows: Windows'un yerleşik metin tanıması (Windows.Media.Ocr, "winrt" paketleriyle).
    Önce Türkçe motor kullanılır; Türkçe dil paketi yoksa kullanıcının Windows dilleriyle tanınır.
Her iki motor da aynı biçimi döndürür: görüntü başına satır listesi, konumlar 0–1 arası, sol üst başlangıç.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pymupdf

import fonts
from tools import ToolError

OCR_FONT = "PSFocr"     # "PSF" öneki: boşluk eşlemesi düzeltilsin (tools.fix_spaces)
DPI = 250
IS_WIN = sys.platform == "win32"
TR_LANGUAGE_HINT = ("Türkçe metin tanıma için: Windows Ayarlar › Saat ve dil › Dil ve bölge › Türkçe › Dil seçenekleri › "
                    "\"Optik karakter tanıma\" bileşenini yükleyin.")


def helper_path():
    app = "Koç PDF Pro.app/Contents/MacOS/kocpdf-ocr"
    home = Path.home()
    candidates = [
        os.environ.get("PDFSTUDYO_OCR_BIN"),                       # Mac uygulaması yolunu kendisi bildirir
        str(home / "Library/Caches/PDFStudyo/build" / app),        # geliştirme (native/build.sh çıktısı)
        str(home / "Library/Caches/PDFStudyo/build/kocpdf-ocr"),
        str(home / "Desktop" / app),                               # tarayıcı modu
        *map(str, sorted(home.glob("Desktop/*/" + app))),          # Masaüstündeki bir klasöre taşınmışsa
        str(home / "Applications" / app),
        "/Applications/" + app,
        shutil.which("kocpdf-ocr"),
    ]
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


# ------------------------------------------------------------------ Windows: Windows.Media.Ocr

def _win_apartment():
    """WinRT, çağrıldığı iş parçacığında COM'un başlatılmış olmasını ister (sunucu her isteği ayrı iş parçacığında işler)."""
    try:
        from winrt.runtime import ApartmentType, init_apartment
        init_apartment(ApartmentType.MULTI_THREADED)
    except Exception:
        pass   # bu iş parçacığında zaten başlatılmış


def _win_engine():
    """Windows'un tanıma motoru: önce Türkçe, yoksa kullanıcının Windows dilleri. Hiçbiri yoksa None."""
    _win_apartment()
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine
    for tag in ("tr-TR", "tr"):
        try:
            lang = Language(tag)
            if OcrEngine.is_language_supported(lang):
                engine = OcrEngine.try_create_from_language(lang)
                if engine is not None:
                    return engine
        except Exception:
            pass
    return OcrEngine.try_create_from_user_profile_languages()


_win_status = None
_win_lock = threading.Lock()


def windows_status():
    """(kullanılabilir mi, Türkçe mi, motorun dili, en büyük görüntü boyutu) — bir kez hesaplanır; aynı anda soran
    istekler ilk hesaplamayı bekler."""
    global _win_status
    with _win_lock:
        if _win_status is None:
            _win_status = _compute_windows_status()
    return _win_status


def _compute_windows_status():
    try:
        from winrt.windows.media.ocr import OcrEngine
        engine = _win_engine()
        tag = engine.recognizer_language.language_tag if engine is not None else None
        return (engine is not None, bool(tag) and tag.lower().startswith("tr"), tag,
                int(OcrEngine.max_image_dimension or 0))
    except Exception:
        return (False, False, None, 0)


def notice():
    """Kullanıcıya gösterilecek not: Windows'ta Türkçe tanıma paketi yoksa (ş, ğ, ı hatalı çıkabilir)."""
    if IS_WIN:
        ok, turkish, tag, _ = windows_status()
        if ok and not turkish:
            return f"Türkçe tanıma paketi yüklü değil; metin {tag or 'Windows'} diliyle tanındı, ş, ğ, ı gibi harfler hatalı olabilir. " + TR_LANGUAGE_HINT
    return None


def _recognize_windows(images):
    engine = _win_engine() if windows_status()[0] else None
    if engine is None:
        raise ToolError("Bu bilgisayarda metin tanıma bulunamadı. " + TR_LANGUAGE_HINT)
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage import FileAccessMode, StorageFile

    async def one(path):
        file = await StorageFile.get_file_from_path_async(os.path.abspath(path))
        stream = await file.open_async(FileAccessMode.READ)
        try:
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            W, H = bitmap.pixel_width, bitmap.pixel_height
            result = await engine.recognize_async(bitmap)
        finally:
            stream.close()   # dosya açık kalırsa geçici klasör silinemez
        lines = []
        for line in result.lines:
            rects = [word.bounding_rect for word in line.words]
            if not rects or not W or not H:
                continue
            x0, y0 = min(r.x for r in rects), min(r.y for r in rects)
            x1, y1 = max(r.x + r.width for r in rects), max(r.y + r.height for r in rects)
            lines.append({"text": line.text, "x": x0 / W, "y": y0 / H, "w": (x1 - x0) / W, "h": (y1 - y0) / H, "conf": 1.0})
        return lines

    async def run():
        return [await one(p) for p in images]

    _win_apartment()
    try:
        return asyncio.run(run())
    except Exception as e:
        raise ToolError(f"Metin tanıma başarısız: {e}")


def available():
    if IS_WIN:
        return windows_status()[0]
    return sys.platform == "darwin" and helper_path() is not None


def page_has_text(page):
    return len(page.get_text("text").strip()) > 20


def needs_ocr(doc, sample=6):
    """Belgenin ilk sayfalarında hiç metin yoksa taranmış kabul edilir."""
    return not any(page_has_text(doc[i]) for i in range(min(sample, doc.page_count)))


def _recognize(images):
    if IS_WIN:
        return _recognize_windows(images)
    helper = helper_path()
    if not helper:
        raise ToolError("Metin tanıma bu bilgisayarda kullanılamıyor.")
    results = []
    for start in range(0, len(images), 8):          # 8'er sayfalık gruplar
        chunk = images[start:start + 8]
        try:
            proc = subprocess.run([helper, *chunk], capture_output=True, timeout=120 + 60 * len(chunk))
        except subprocess.TimeoutExpired:
            raise ToolError("Metin tanıma zaman aşımına uğradı.")
        if proc.returncode != 0:
            raise ToolError("Metin tanıma başarısız: " + proc.stderr.decode("utf-8", "replace")[:300])
        results += json.loads(proc.stdout or b"[]")
    return results


def page_image(doc, index, path):
    """Tanınacak sayfanın görüntüsü (ekranda görünen yönde); Windows motorunun boyut sınırı gözetilir."""
    page = doc[index]
    max_side = windows_status()[3] if IS_WIN else 0
    dpi = min(DPI, int(max_side * 72 / max(page.rect.width, page.rect.height))) if max_side else DPI
    page.get_pixmap(dpi=dpi, alpha=False).save(path)


def recognize_images(paths):
    """Görüntülerin yazısı, sırayla; her biri [{text, x, y, w, h}] (0–1 arası). Yardımcı 8'er görüntüyle çalışır."""
    return _recognize([str(p) for p in paths])


def ocr_document(doc, only_missing=True, cache_dir=Path(".")):
    """Metni olmayan (ya da tüm) sayfalara görünmez metin ekler. Tanınan sayfa sayısını döndürür."""
    targets = [i for i in range(doc.page_count) if not (only_missing and page_has_text(doc[i]))]
    if not targets:
        return 0
    max_side = windows_status()[3] if IS_WIN else 0   # Windows motoru belirli bir boyuttan büyük görüntüyü tanımaz
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        images = []
        for i in targets:
            path = Path(tmp) / f"s{i:05d}.png"
            dpi = DPI
            if max_side:
                dpi = min(DPI, int(max_side * 72 / max(doc[i].rect.width, doc[i].rect.height)))
            doc[i].get_pixmap(dpi=dpi, alpha=False).save(path)   # ekranda görünen yönde
            images.append(str(path))
        results = _recognize(images)

    fontfile = fonts.face_file("Arial", cache_dir=cache_dir)
    font = pymupdf.Font(fontfile=fontfile) if fontfile else pymupdf.Font("helv")
    for i, lines in zip(targets, results):
        page = doc[i]
        W, H = page.rect.width, page.rect.height
        rot = page.rotation
        for line in lines:
            text = " ".join(line.get("text", "").split())
            if not text:
                continue
            box = pymupdf.Rect(line["x"] * W, line["y"] * H, (line["x"] + line["w"]) * W, (line["y"] + line["h"]) * H)
            size = max(box.height * 0.82, 2)
            natural = font.text_length(text, fontsize=size) or 1
            scale = box.width / natural                       # satır genişliğine sığdır
            origin = pymupdf.Point(box.x0, box.y1 - box.height * 0.18) * page.derotation_matrix
            matrix = pymupdf.Matrix(scale, 1) if rot in (0, 180) else pymupdf.Matrix(1, scale)
            page.insert_text(origin, text, fontsize=size, fontname=OCR_FONT, fontfile=fontfile,
                             render_mode=3, rotate=rot, morph=(origin, matrix))
    return len(targets)
