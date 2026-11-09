"""Windows OCR yolunu Mac'te sahte WinRT modülleriyle dener (koordinat dönüşümü, dil seçimi, boyut sınırı)."""
import asyncio, enum, sys, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pymupdf

SRC = Path(__file__).resolve().parent / "deneme.pdf"
STATE = {"turkish": True, "maxdim": 2600, "opened": 0, "closed": 0, "sizes": []}

def mod(name):
    m = types.ModuleType(name); sys.modules[name] = m; return m
for n in ["winrt", "winrt.windows", "winrt.windows.media", "winrt.windows.graphics"]:
    mod(n)
rt = mod("winrt.runtime")
class ApartmentType(enum.IntEnum): SINGLE_THREADED = 0; MULTI_THREADED = 1
rt.ApartmentType = ApartmentType
rt.init_apartment = lambda t: None

glob = mod("winrt.windows.globalization")
class Language:
    def __init__(self, tag): self.language_tag = tag
glob.Language = Language

class Rect:
    def __init__(self, x, y, w, h): self.x, self.y, self.width, self.height = x, y, w, h
class Word:
    def __init__(self, text, rect): self.text, self.bounding_rect = text, rect
class Line:
    def __init__(self, text, words): self.text, self.words = text, words
class Result:
    def __init__(self, lines): self.lines = lines

async def done(v): return v

ocrmod = mod("winrt.windows.media.ocr")
class OcrEngine:
    max_image_dimension = property(lambda self: STATE["maxdim"])
    def __init__(self, tag): self.recognizer_language = Language(tag)
    @classmethod
    def is_language_supported(cls, lang): return STATE["turkish"] and lang.language_tag.startswith("tr")
    @classmethod
    def try_create_from_language(cls, lang): return cls(lang.language_tag)
    @classmethod
    def try_create_from_user_profile_languages(cls): return cls("en-US")
    def recognize_async(self, bitmap):
        # Özgün PDF'teki satırları, görüntünün piksel boyutuna göre döndür (gerçek motorun yaptığı gibi)
        page = pymupdf.open(SRC)[bitmap.page]
        sx, sy = bitmap.pixel_width / page.rect.width, bitmap.pixel_height / page.rect.height
        lines = []
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                words = []
                for sp in l["spans"]:
                    if not sp["text"].strip(): continue
                    x0, y0, x1, y1 = sp["bbox"]
                    words.append(Word(sp["text"].strip(), Rect(x0 * sx, y0 * sy, (x1 - x0) * sx, (y1 - y0) * sy)))
                if words: lines.append(Line(" ".join(w.text for w in words), words))
        return done(Result(lines))
OcrEngine.max_image_dimension = STATE["maxdim"]
ocrmod.OcrEngine = OcrEngine

st = mod("winrt.windows.storage")
class FileAccessMode(enum.IntEnum): READ = 0; READ_WRITE = 1
class Stream:
    def __init__(self, path): self.path = path; STATE["opened"] += 1
    def close(self): STATE["closed"] += 1
class StorageFile:
    def __init__(self, path): self.path = path
    @classmethod
    def get_file_from_path_async(cls, path): return done(cls(path))
    def open_async(self, mode): return done(Stream(self.path))
st.FileAccessMode, st.StorageFile = FileAccessMode, StorageFile

img = mod("winrt.windows.graphics.imaging")
class Bitmap:
    def __init__(self, path):
        pm = pymupdf.Pixmap(path); self.pixel_width, self.pixel_height = pm.width, pm.height
        self.page = int(Path(path).stem[1:]); STATE["sizes"].append(max(pm.width, pm.height))
class Decoder:
    def __init__(self, stream): self.stream = stream
    @classmethod
    def create_async(cls, stream): return done(cls(stream))
    def get_software_bitmap_async(self): return done(Bitmap(self.stream.path))
img.BitmapDecoder = Decoder

import ocr
ocr.IS_WIN = True

def scanned():
    src = pymupdf.open(SRC); out = pymupdf.open()
    for pg in src:
        p = out.new_page(width=pg.rect.width, height=pg.rect.height)
        p.insert_image(p.rect, pixmap=pg.get_pixmap(dpi=120))
    return out

ok = True
def check(name, cond, extra=""):
    global ok; ok &= bool(cond); print(("✅" if cond else "❌"), name, extra)

check("Windows'ta motor bulundu (Türkçe)", ocr.available() and ocr.windows_status()[1] and ocr.notice() is None, ocr.windows_status())
doc = scanned()
n = ocr.ocr_document(doc, only_missing=False, cache_dir=Path.home() / "Library/Caches/PDFStudyo")
check("Tüm sayfalar tanındı", n == doc.page_count, n)
orig = pymupdf.open(SRC)
hits_new = doc[0].search_for("İğne"); hits_orig = orig[0].search_for("İğne")
check("Tanınan metin aranabilir", bool(hits_new), hits_new[:1])
if hits_new and hits_orig:
    d = max(abs(a - b) for a, b in zip(hits_new[0], hits_orig[0]))
    check("Konum özgün yazıyla örtüşüyor (≤3 pt)", d <= 3, f"fark {d:.2f} pt")
check("Görüntüler motor sınırını aşmıyor", max(STATE["sizes"]) <= STATE["maxdim"], f"en büyük {max(STATE['sizes'])} px, sınır {STATE['maxdim']}")
check("Açılan dosyaların hepsi kapatıldı", STATE["opened"] == STATE["closed"] > 0, (STATE["opened"], STATE["closed"]))

# Türkçe paket yoksa: kullanıcının diliyle tanınır, not gösterilir
ocr._win_status = None; STATE["turkish"] = False
check("Türkçe paket yoksa yine çalışır", ocr.available() and ocr.windows_status()[2] == "en-US")
check("Türkçe paket yoksa not çıkar", "Optik karakter tanıma" in (ocr.notice() or ""), ocr.notice())

# Motor hiç yoksa: kullanılamaz, anlaşılır hata
ocr._win_status = None
OcrEngine.try_create_from_user_profile_languages = classmethod(lambda cls: None)
check("Motor yoksa kullanılamaz", not ocr.available())
try:
    ocr.ocr_document(scanned(), only_missing=False); check("Motor yoksa hata verir", False)
except ocr.ToolError as e:
    check("Motor yoksa anlaşılır hata", "bulunamadı" in str(e), str(e)[:70])
print("\nSONUÇ:", "TÜMÜ GEÇTİ" if ok else "HATA VAR")
sys.exit(0 if ok else 1)   # betik ya da otomasyon başarısızlığı çıkış kodundan anlasın
