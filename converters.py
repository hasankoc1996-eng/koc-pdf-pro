"""Biçim dönüştürmeleri: Word ↔ PDF, Excel → PDF, resim ↔ PDF."""
import io
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path

import pymupdf

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))  # paketlenmiş uygulamada paketin içi
IS_WIN = sys.platform == "win32"
WORD_APP = Path("/Applications/Microsoft Word.app")
WD_FORMAT = {"pdf": 17, "docx": 16}   # Windows Word: wdFormatPDF, wdFormatDocumentDefault
# Word sandbox içinde çalışır; bu klasöre izin penceresi çıkmadan erişebilir.
WORD_SANDBOX = Path.home() / "Library/Containers/com.microsoft.Word/Data/tmp/pdfstudyo"
WORD_SCRIPT = BASE / "scripts" / "word_export.applescript"
WORD_INPUTS = {".doc", ".docx", ".rtf", ".odt", ".txt", ".dotx", ".docm"}
EXCEL_APP = Path("/Applications/Microsoft Excel.app")
EXCEL_SANDBOX = Path.home() / "Library/Containers/com.microsoft.Excel/Data/tmp/pdfstudyo"
EXCEL_SCRIPT = BASE / "scripts" / "excel_export.applescript"
EXCEL_INPUTS = {".xlsx", ".xls", ".xlsm", ".csv", ".ods"}
IMAGE_INPUTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".heic"}

# Word ve Excel aynı anda tek belgeyle güvenilir çalışır.
_word_lock = threading.Lock()
_excel_lock = threading.Lock()


class ConversionError(Exception):
    pass


def soffice_path():
    for p in (shutil.which("soffice"), "/Applications/LibreOffice.app/Contents/MacOS/soffice",
              r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if p and Path(p).exists():
            return p
    return None


def word_installed():
    if IS_WIN:
        try:
            import winreg
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"))
            return True
        except OSError:
            return False
    return WORD_APP.exists()


def excel_installed():
    if IS_WIN:
        try:
            import winreg
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application\CLSID"))
            return True
        except OSError:
            return False
    return EXCEL_APP.exists()


def engines():
    return {"word": word_installed(), "excel": excel_installed(), "libreoffice": bool(soffice_path())}


def _word_export_windows(src: Path, dst: Path, kind: str):
    """Windows: Microsoft Word'ü COM otomasyonuyla görünmeden çalıştırır."""
    import comtypes
    import comtypes.client
    with _word_lock:
        comtypes.CoInitialize()      # Flask her isteği ayrı iş parçacığında işler
        word = None
        try:
            try:
                word = comtypes.client.CreateObject("Word.Application", dynamic=True)
            except OSError as e:
                raise ConversionError(f"Microsoft Word başlatılamadı: {e}")
            word.Visible = False
            word.DisplayAlerts = 0   # wdAlertsNone: PDF dönüştürme uyarısı vb. çıkmasın
            # Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles)
            doc = word.Documents.Open(str(Path(src).resolve()), False, True, False)
            try:
                doc.SaveAs2(str(Path(dst).resolve()), WD_FORMAT[kind])
            finally:
                doc.Close(0)         # wdDoNotSaveChanges
        except ConversionError:
            raise
        except Exception as e:
            raise ConversionError(f"Word dönüştürme hatası: {e}")
        finally:
            if word is not None:
                try:
                    word.Quit(0)
                except Exception:
                    pass
            comtypes.CoUninitialize()
    if not Path(dst).exists() or Path(dst).stat().st_size == 0:
        raise ConversionError("Word çıktı dosyası üretmedi.")


def _word_export(src: Path, dst: Path, kind: str, timeout=240):
    if IS_WIN:
        return _word_export_windows(src, dst, kind)
    with _word_lock:
        WORD_SANDBOX.mkdir(parents=True, exist_ok=True)
        job = "ps" + uuid.uuid4().hex[:10]
        tin = WORD_SANDBOX / f"{job}{src.suffix.lower()}"
        tout = WORD_SANDBOX / f"{job}_out.{kind}"
        shutil.copy(src, tin)
        try:
            try:
                proc = subprocess.run(
                    ["osascript", str(WORD_SCRIPT), str(tin), str(tout), tin.name, kind],
                    capture_output=True, text=True, timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                raise ConversionError("Microsoft Word zamanında yanıt vermedi. Word'de açık bir pencere/uyarı olup olmadığını kontrol edin.")
            if proc.returncode != 0:
                msg = proc.stderr.strip()
                if "-1743" in msg or "not allowed" in msg.lower() or "izin" in msg.lower():
                    msg = ("Word'ü kontrol etme izni yok. Sistem Ayarları › Gizlilik ve Güvenlik › Otomasyon "
                           "bölümünden Terminal/Python için Microsoft Word iznini açın.")
                raise ConversionError(f"Word dönüştürme hatası: {msg}")
            if not tout.exists() or tout.stat().st_size == 0:
                raise ConversionError("Word çıktı dosyası üretmedi.")
            shutil.move(str(tout), str(dst))
        finally:
            for f in WORD_SANDBOX.glob(f"*{job}*"):
                f.unlink(missing_ok=True)


def _libreoffice_to_pdf(src: Path, dst: Path):
    soffice = soffice_path()
    outdir = dst.parent / ("lo_" + uuid.uuid4().hex[:8])
    outdir.mkdir()
    try:
        proc = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(src)],
            capture_output=True, text=True, timeout=240,
        )
        produced = outdir / (src.stem + ".pdf")
        if proc.returncode != 0 or not produced.exists():
            raise ConversionError("LibreOffice dönüştürme hatası: " + (proc.stderr.strip() or "bilinmeyen hata"))
        shutil.move(str(produced), str(dst))
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


def _excel_export_windows(src: Path, dst: Path):
    """Windows: Microsoft Excel COM otomasyonuyla görünmeden; bütün çalışma sayfaları tek PDF'e."""
    import comtypes
    import comtypes.client
    with _excel_lock:
        comtypes.CoInitialize()
        excel = None
        try:
            try:
                excel = comtypes.client.CreateObject("Excel.Application", dynamic=True)
            except OSError as e:
                raise ConversionError(f"Microsoft Excel başlatılamadı: {e}")
            excel.Visible = False
            excel.DisplayAlerts = False
            book = excel.Workbooks.Open(str(Path(src).resolve()), 0, True)   # UpdateLinks=0, ReadOnly=True
            try:
                book.ExportAsFixedFormat(0, str(Path(dst).resolve()))     # xlTypePDF
            finally:
                book.Close(False)
        except ConversionError:
            raise
        except Exception as e:
            raise ConversionError(f"Excel dönüştürme hatası: {e}")
        finally:
            if excel is not None:
                try:
                    excel.Quit()
                except Exception:
                    pass
            comtypes.CoUninitialize()
    if not Path(dst).exists() or Path(dst).stat().st_size == 0:
        raise ConversionError("Excel çıktı dosyası üretmedi.")


def _excel_export_mac(src: Path, dst: Path, timeout=240):
    with _excel_lock:
        EXCEL_SANDBOX.mkdir(parents=True, exist_ok=True)
        job = "ps" + uuid.uuid4().hex[:10]
        tin = EXCEL_SANDBOX / f"{job}{src.suffix.lower()}"
        tout = EXCEL_SANDBOX / f"{job}_out.pdf"
        shutil.copy(src, tin)
        try:
            try:
                proc = subprocess.run(["osascript", str(EXCEL_SCRIPT), str(tin), str(tout), tin.name],
                                      capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise ConversionError("Microsoft Excel zamanında yanıt vermedi. Excel'de açık bir pencere/uyarı olup olmadığını kontrol edin.")
            if proc.returncode != 0:
                msg = proc.stderr.strip()
                if "-1743" in msg or "not allowed" in msg.lower() or "izin" in msg.lower():
                    msg = ("Excel'i kontrol etme izni yok. Sistem Ayarları › Gizlilik ve Güvenlik › Otomasyon "
                           "bölümünden Koç PDF Pro için Microsoft Excel iznini açın.")
                raise ConversionError(f"Excel dönüştürme hatası: {msg}")
            if not tout.exists() or tout.stat().st_size == 0:
                raise ConversionError("Excel çıktı dosyası üretmedi.")
            shutil.move(str(tout), str(dst))
        finally:
            for f in EXCEL_SANDBOX.glob(f"*{job}*"):
                f.unlink(missing_ok=True)


def excel_to_pdf(src: Path, dst: Path):
    """Excel (ve CSV, ODS) → PDF: bütün çalışma sayfaları, Excel'in sayfa düzeniyle. Excel yoksa LibreOffice."""
    if src.suffix.lower() not in EXCEL_INPUTS:
        raise ConversionError(f"Desteklenmeyen dosya türü: {src.suffix}")
    if excel_installed():
        return _excel_export_windows(src, dst) if IS_WIN else _excel_export_mac(src, dst)
    if soffice_path():
        return _libreoffice_to_pdf(src, dst)
    raise ConversionError("Excel → PDF için Microsoft Excel veya LibreOffice gerekli.")


def word_to_pdf(src: Path, dst: Path):
    if src.suffix.lower() not in WORD_INPUTS:
        raise ConversionError(f"Desteklenmeyen dosya türü: {src.suffix}")
    if word_installed():
        return _word_export(src, dst, "pdf")
    if soffice_path():
        return _libreoffice_to_pdf(src, dst)
    raise ConversionError("Word→PDF için Microsoft Word veya LibreOffice gerekli.")


def pdf_to_word(src: Path, dst: Path, engine="standart", password=None):
    if engine == "word":
        if not word_installed():
            raise ConversionError("Microsoft Word bulunamadı.")
        return _word_export(src, dst, "docx")
    from pdf2docx import Converter
    doc = pymupdf.open(src)
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            raise ConversionError("PDF şifreli. Doğru şifreyi girin.")
    doc.close()
    cv = Converter(str(src), password=password)
    try:
        cv.convert(str(dst), multi_processing=False)
    except Exception as e:  # pdf2docx karmaşık sayfalarda hata verebilir
        raise ConversionError(f"PDF→Word dönüştürme hatası: {e}")
    finally:
        cv.close()


def images_to_pdf(srcs, dst: Path, page_size="orijinal", margin=0):
    """page_size: 'orijinal' | 'a4' | 'a4-yatay'. Çok sayfalı TIFF'in her sayfası ayrı sayfa olur."""
    out = pymupdf.open()
    for src in srcs:
        if Path(src).suffix.lower() in TIFF_INPUTS:
            frames = pymupdf.open(src)
            pdf = pymupdf.open("pdf", frames.convert_to_pdf())
            frames.close()
            for page in pdf:
                if page_size == "orijinal":
                    w, h, m = page.rect.width, page.rect.height, 0
                else:
                    (w, h), m = pymupdf.paper_size("a4-l" if page_size == "a4-yatay" else "a4"), margin
                out.new_page(width=w, height=h).show_pdf_page(pymupdf.Rect(m, m, w - m, h - m), pdf, page.number)
            pdf.close()
            continue
        img_bytes = Path(src).read_bytes()
        if Path(src).suffix.lower() in {".heic", ".webp", ".gif", ".bmp"}:
            img_bytes = _to_png(img_bytes)
        img = pymupdf.open(stream=img_bytes)
        rect = img[0].rect
        img.close()
        if page_size == "orijinal":
            w, h = rect.width, rect.height
        else:
            w, h = pymupdf.paper_size("a4-l" if page_size == "a4-yatay" else "a4")
        page = out.new_page(width=w, height=h)
        m = margin if page_size != "orijinal" else 0
        page.insert_image(pymupdf.Rect(m, m, w - m, h - m), stream=img_bytes, keep_proportion=True)
    out.save(dst, garbage=3, deflate=True)
    out.close()


IMAGE_INPUTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".heic"}
TIFF_INPUTS = {".tif", ".tiff"}


def images_to_a4(srcs, dst: Path):
    """Resim ve TIFF sayfaları A4'e: oranı korunarak A4'e sığan en büyük ölçüde, kenar boşluğu eklenmeden; yatay
    resim yatay A4'e. Çözünürlük değişmez (resim olduğu gibi gömülür). Çok sayfalı TIFF'in her sayfası ayrı sayfa olur."""
    out = pymupdf.open()
    for src in srcs:
        src = Path(src)
        if src.suffix.lower() in TIFF_INPUTS:   # her sayfası ayrı resim (pymupdf TIFF'i belge olarak açar)
            frames = pymupdf.open(src)
            pdf = pymupdf.open("pdf", frames.convert_to_pdf())
            frames.close()
            for page in pdf:
                target, area = _a4_page(out, page.rect)
                target.show_pdf_page(area, pdf, page.number)
            pdf.close()
            continue
        data = src.read_bytes()
        if src.suffix.lower() in {".heic", ".webp", ".gif", ".bmp"}:
            data = _to_png(data)
        img = pymupdf.open(stream=data)
        rect = img[0].rect
        img.close()
        target, area = _a4_page(out, rect)
        target.insert_image(area, stream=data, keep_proportion=True)
    out.save(dst, garbage=3, deflate=True)
    out.close()


def pdf_to_tiff(src: Path, dst: Path, dpi=200, mode="gri"):
    """Bütün sayfalar tek, çok sayfalı TIFF dosyasında. mode: 'renkli' | 'gri' | 'sb' (siyah-beyaz: CCITT G4,
    taramalarda en küçük dosya). Sayfalar tek tek işlenir: uzun belgede bellek dolmaz."""
    from PIL import Image
    doc = pymupdf.open(src)

    def frames():
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csRGB if mode == "renkli" else pymupdf.csGRAY)
            im = Image.frombytes("RGB" if pix.n == 3 else "L", (pix.width, pix.height), pix.samples)
            yield im.point(lambda v: 255 if v > 170 else 0, "1") if mode == "sb" else im
    try:
        pages = frames()
        next(pages).save(dst, save_all=True, append_images=pages, dpi=(dpi, dpi),
                         compression="group4" if mode == "sb" else "tiff_lzw")
    finally:
        doc.close()


def _a4_page(doc, rect):
    """Resmin yönüne göre dikey ya da yatay A4 sayfa açar. Dönen: (sayfa, resmin sığacağı en büyük alan)."""
    w, h = pymupdf.paper_size("a4-l" if rect.width > rect.height else "a4")
    page = doc.new_page(width=w, height=h)
    k = min(w / rect.width, h / rect.height)
    fw, fh = rect.width * k, rect.height * k
    return page, pymupdf.Rect((w - fw) / 2, (h - fh) / 2, (w + fw) / 2, (h + fh) / 2)


def _to_png(data: bytes) -> bytes:
    from PIL import Image
    try:
        from pi_heif import register_heif_opener  # iPhone fotoğrafları (HEIC); yalnızca okuyan HEIF kütüphanesi
        register_heif_opener()
    except ImportError:
        pass
    im = Image.open(io.BytesIO(data))
    if im.mode not in ("RGB", "RGBA", "L"):
        im = im.convert("RGBA")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def pdf_to_images(src: Path, dst_zip: Path, fmt="png", dpi=150, pages=None, name=None):
    """Sayfalar resim olur: her sayfa ZIP'e (name_sayfa_001.jpg); hedef .zip değilse yalnızca ilk sayfa doğrudan resim dosyasına."""
    doc = pymupdf.open(src)
    if dst_zip.suffix.lower() != ".zip":
        pix = doc[0].get_pixmap(dpi=dpi, alpha=False)
        dst_zip.write_bytes(pix.tobytes("jpeg", jpg_quality=88) if fmt == "jpg" else pix.tobytes("png"))
        doc.close()
        return
    stem = name or src.stem
    with zipfile.ZipFile(dst_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for i in pages if pages is not None else range(doc.page_count):
            pix = doc[i].get_pixmap(dpi=dpi, alpha=False)
            data = pix.tobytes("jpeg", jpg_quality=88) if fmt == "jpg" else pix.tobytes("png")
            z.writestr(f"{stem}_sayfa_{i + 1:03d}.{fmt}", data)
    doc.close()
