"""Koç PDF Pro — yerel PDF dönüştürme ve düzenleme uygulaması."""
import base64
import io
import json
import os
import re
import secrets
import shutil
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
import webbrowser
import zipfile
from pathlib import Path

from flask import Flask, abort, g, jsonify, redirect, request, send_file, send_from_directory
from werkzeug.serving import WSGIRequestHandler
from werkzeug.utils import secure_filename

import pymupdf

import ayarlar
import converters
import editor
import fonts
import formlar
import karsilastir
import kilavuz
import kisisel_veri
import notlar
import ocr
import paragraflar
import tablolar
import tools
import udf
import updater
import yedekler
from converters import ConversionError
from tools import ToolError
from udf import UdfError

# Paketlenmiş (tek parça) uygulamada dosyalar PyInstaller'ın açtığı klasördedir
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
PORT = int(os.environ.get("PDFSTUDYO_PORT", "5055"))
IS_WIN = sys.platform == "win32"
DATA = (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "KocPDFPro" if IS_WIN
        else Path.home() / "Library/Caches/PDFStudyo")
if os.environ.get("PDFSTUDYO_DATA"):   # testler ve deneme sunucuları uygulamanın verisine (oturum, yedek…) karışmasın
    DATA = Path(os.environ["PDFSTUDYO_DATA"])
UPLOADS = DATA / "uploads"
OUTPUTS = DATA / "outputs"
SESSIONS = DATA / "sessions"
SHARES = DATA / "paylas"   # Mail, AirDrop… ile paylaşılan belgelerin geçici kopyaları
for d in (UPLOADS, OUTPUTS, SESSIONS, SHARES):
    d.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GB
store = editor.SessionStore(SESSIONS)
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}
yedekler.BACKUPS = DATA / "yedekler"
ayarlar.SETTINGS_FILE = DATA / "ayarlar.json"
ayarlar.apply_settings(ayarlar.read_settings())   # yedek sınırı, kurtarma süresi, yazar adı

# Sürüm numarası (ör. 1.0.0) surum.txt'te; kurulum paketinde make_dmg.sh / make_windows.sh _surum.py'ye yazar, yanına
# paketin üretildiği git revizyonunu (KAYNAK, sorun raporunda) ekler. _surum.py yalnızca paketlerde vardır: paketse
# uygulama anahtarı ve güncelleme denetimi açılır. Proje klasöründen çalışan geliştirme sürümünde ikisi de kapalıdır.
try:
    from _surum import SURUM, KAYNAK
    PACKAGED = True
except ImportError:
    SURUM = (BASE / "surum.txt").read_text(encoding="utf-8").strip()
    KAYNAK, PACKAGED = None, False

# Uygulama anahtarı (kurulum paketleri): motor her açılışta rastgele bir anahtar üretir ve yalnızca bu
# anahtarı bilen uygulama penceresine cevap verir. Pencere anahtarı dosyadan okuyup ilk adreste iletir
# (?anahtar=…); motor onu çereze yazar. Böylece arayüz tarayıcıdan açılıp kurcalanamaz.
KEY_FILE = DATA / "oturum"
KEY_COOKIE = "kpa"
OPEN_PATHS = {"/api/status", "/api/host/open"}   # pencere açılmadan önceki yoklama ve ikinci açılış


def init_app_key():
    KEY_FILE.unlink(missing_ok=True)   # geliştirme sürümünde eski paket anahtarı kalmasın
    if not PACKAGED:
        return None
    key = secrets.token_urlsafe(24)
    KEY_FILE.write_text(key, encoding="utf-8")
    os.chmod(KEY_FILE, 0o600)
    return key


APP_KEY = init_app_key()


def key_matches(value):
    return bool(value) and secrets.compare_digest(value.encode("utf-8"), APP_KEY.encode("utf-8"))

BLOCKED_PAGE = """<!doctype html><html lang="tr"><meta charset="utf-8"><title>Koç PDF Pro</title>
<style>body{font:15px -apple-system,"Segoe UI",sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;
background:#f4f5f7;color:#1c2024}main{max-width:460px;text-align:center;padding:24px}h1{font-size:20px;margin:0 0 10px}
p{color:#6b7280;line-height:1.55;margin:0}@media (prefers-color-scheme:dark){body{background:#15171a;color:#e8eaed}
p{color:#9aa1aa}}</style><main><h1>%s</h1><p>%s</p></main></html>"""


def blocked(title, text):
    """Engellenen istek: API'ye JSON, sayfalara açıklama sayfası."""
    if request.path.startswith("/api/"):
        return jsonify(error=f"{title}. {text}"), 403
    return BLOCKED_PAGE % (title, text), 403, {"Content-Type": "text/html; charset=utf-8"}


# ------------------------------------------------------------------ yardımcılar

def safe_name(name, fallback="dosya"):
    """Türkçe karakterleri koruyan, dosya sistemi için güvenli ad."""
    name = os.path.basename(name or "").replace("\x00", "")
    for ch in '/\\:*?"<>|':
        name = name.replace(ch, "_")
    name = name.strip(" .")
    return name or fallback


def save_uploads(field="files"):
    files = request.files.getlist(field) or request.files.getlist("file")
    doc = g.get("doc_input")   # araç açık belgeye uygulanıyorsa: düzenleyicideki belge
    if not files and not doc and not request.form.getlist("staged"):
        raise ToolError("Dosya seçilmedi.")
    paths = []
    staged = request.form.getlist("staged")   # Dönüştür penceresine önceden alınmış dosyalar (kimlikleriyle)
    if files or staged:
        job = UPLOADS / uuid.uuid4().hex[:12]
        job.mkdir()
        for i, f in enumerate(files):
            name = safe_name(f.filename, f"dosya{i}")
            target = job / f"{i:03d}_{name}"
            f.save(target)
            paths.append(target)
        for i, sid in enumerate(staged, len(files)):   # kopyası işlenir: araçların ara dosyaları kaynağın yanına düşmesin
            src = staged_path(sid)
            target = job / f"{i:03d}_{display_name(src)}"
            shutil.copy(src, target)
            paths.append(target)
    if doc:   # birleştirmede açık belgenin listedeki yeri
        pos = min(max(int(request.form.get("doc_pos", 0) or 0), 0), len(paths))
        paths.insert(pos, doc)
    return paths


def target_path(raw, suffix=None):
    """Kaydetme penceresinde seçilen yol (mutlak olmalı, klasörü var olmalı)."""
    p = Path(raw or "").expanduser()
    if not raw or not p.is_absolute() or not p.parent.is_dir():
        raise ToolError("Kaydedilecek klasör bulunamadı.")
    if suffix and p.suffix.lower() != suffix:
        p = p.with_name(p.name + suffix)
    return p


def unique_path(p: Path):
    k = 1
    target = p
    while target.exists():
        target = p.with_name(f"{p.stem} ({k}){p.suffix}")
        k += 1
    return target


def save_error(e, folder):
    """Dosya yazılamadı: kullanıcıya gösterilecek hata. Disk dolduysa ne olduğu ve var olan dosyanın değişmediği söylenir."""
    if tools.disk_full(e, folder):
        return ToolError("Diskte yer kalmadı, kaydedilemedi. Var olan dosya değişmedi; biraz yer açıp yeniden deneyin.")
    return ToolError(f"Kaydedilemedi: {e.strerror or e}") if isinstance(e, OSError) else e


def write_file(target: Path, write):
    """Önce geçici dosyaya yazar, sonra yerine koyar: yarıda kalırsa (disk doldu) eski dosya bozulmaz, yarım geçici
    dosya da bırakılmaz."""
    tmp = target.with_name(f".{target.stem}.kocpdf-tmp{target.suffix}")
    try:
        write(tmp)
        os.replace(tmp, target)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        err = save_error(e, target.parent)
        if err is e:
            raise
        raise err from e


def backup_before_write(target: Path):
    """Üzerine yazılacak dosyanın yedeği (yedekler.backup_existing). Yedek alınamazsa (disk doldu) yazmaya geçilmez."""
    try:
        return yedekler.backup_existing(target)
    except OSError as e:
        raise save_error(e, yedekler.BACKUPS) from e


def display_name(upload_path: Path):
    return upload_path.name.split("_", 1)[1] if "_" in upload_path.name else upload_path.name


def new_output(filename):
    oid = uuid.uuid4().hex[:12]
    d = OUTPUTS / oid
    d.mkdir()
    return d / safe_name(filename)


def describe(path: Path, **extra):
    oid = path.parent.name
    res = {"id": oid, "name": path.name, "size": path.stat().st_size,
           "url": f"/api/out/{oid}", "pdf": path.suffix.lower() == ".pdf"}
    res.update(extra)
    return res


def output_path(oid):
    d = OUTPUTS / secure_filename(oid)
    files = list(d.iterdir()) if d.is_dir() else []
    if not files:
        raise ToolError("Çıktı dosyası bulunamadı (süresi dolmuş olabilir).")
    return files[0]


def form_bool(name):
    return request.form.get(name, "").lower() in ("1", "true", "on", "evet")


def stem(path):
    return Path(display_name(path)).stem


@app.errorhandler(ToolError)
@app.errorhandler(ConversionError)
@app.errorhandler(UdfError)
def handle_known(e):
    return jsonify(error=str(e), needs_password=isinstance(e, editor.PasswordRequired)), 400


@app.errorhandler(413)
def too_large(e):
    return jsonify(error="Dosya çok büyük (en fazla 1 GB)."), 413


@app.errorhandler(Exception)
def handle_other(e):
    if hasattr(e, "code") and isinstance(getattr(e, "code"), int):
        return jsonify(error=str(e)), e.code
    traceback.print_exc()
    return jsonify(error=f"Beklenmeyen hata: {e}"), 500


@app.before_request
def check_host():
    # DNS rebinding'e karşı yalnızca yerel adreslere izin ver
    if request.host not in ALLOWED_HOSTS:
        abort(403)
    # Başka bir web sitesinden gelen istekler (tarayıcıda açık bir sayfa) dosyalara dokunamasın
    origin = request.headers.get("Origin")
    if origin and origin not in ALLOWED_ORIGINS:
        abort(403)
    if APP_KEY and request.path not in OPEN_PATHS:
        if key_matches(request.cookies.get(KEY_COOKIE)):
            return None
        if request.method == "GET" and key_matches(request.args.get("anahtar")):
            # Pencerenin ilk açılışı: anahtar çereze yazılır ve adresten silinir
            rest = [(k, v) for k, v in request.args.items(multi=True) if k != "anahtar"]
            resp = redirect(request.path + ("?" + urllib.parse.urlencode(rest) if rest else ""))
            resp.set_cookie(KEY_COOKIE, APP_KEY, httponly=True, samesite="Strict", path="/")
            return resp
        return blocked("Koç PDF Pro yalnızca kendi penceresinde çalışır",
                       "Bu adres tarayıcıdan kullanılamaz. Lütfen Koç PDF Pro uygulamasını açın.")


# ------------------------------------------------------------------ sayfalar

@app.get("/")
def index():
    return send_from_directory(BASE / "static", "index.html")


@app.get("/shell")
def shell():
    """Windows uygulama penceresi: sekmeleri yöneten kabuk sayfası (static/shell.js)."""
    return send_from_directory(BASE / "static", "shell.html")


@app.get("/static/<path:name>")
def static_files(name):
    resp = send_from_directory(BASE / "static", name)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# Word / Excel / LibreOffice / metin tanıma var mı. Windows'ta ilk yoklama (metin tanıma bileşeni, PATH'te LibreOffice
# araması) bir iki saniye sürebilir: motor açılırken arka planda yapılır (serve), sonuç bir dakika geçerli. Aynı anda
# gelen istekler hesaplananı bekler, yeniden hesaplamaz.
ENGINES = {"value": None, "time": 0.0}
ENGINES_LOCK = threading.Lock()


def engine_status(max_age=60):
    with ENGINES_LOCK:
        if ENGINES["value"] is None or time.time() - ENGINES["time"] > max_age:
            ENGINES["value"] = {**converters.engines(), "ocr": ocr.available()}
            ENGINES["time"] = time.time()
        return ENGINES["value"]


@app.get("/api/status")
def status():
    if request.args.get("yoklama") == "1":   # başlatıcının "motor açıldı mı" yoklaması: araçları beklemesin
        return jsonify(version=SURUM, packaged=PACKAGED, heartbeat=HEARTBEAT)
    return jsonify(engines=engine_status(), version=SURUM, packaged=PACKAGED, heartbeat=HEARTBEAT)


# ------------------------------------------------------------------ güncelleme
UPDATER = updater.Updater(SURUM if PACKAGED else None, DATA / "guncelleme")   # geliştirme sürümü denetlenmez


@app.get("/api/update")
def update_check():
    return jsonify(UPDATER.check(force=request.args.get("yeniden") == "1"))


@app.post("/api/update/download")
def update_download():
    try:
        return jsonify(UPDATER.download())
    except ValueError as e:
        raise ToolError(str(e))


@app.get("/api/update/state")
def update_state():
    return jsonify(UPDATER.state)


@app.post("/api/update/install")
def update_install():
    try:
        UPDATER.install()
    except (ValueError, OSError) as e:
        raise ToolError(f"Kurulum açılamadı: {e}")
    return jsonify(ok=True)


# ------------------------------------------------------------------ sorun bildir
CONTACT = "hasankoc1996@icloud.com"
LOG_FILE = DATA / "log.txt" if IS_WIN else Path.home() / "Library/Logs/PDFStudyo.log"
ROUTINE_LOG = re.compile(r'"(?:GET|POST|HEAD) [^"]*" (?:2\d\d|304) |^ \* (?:Serving|Debug|Running)|WARNING: This is a development|CTRL\+C')
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def report_text(message=""):
    """Sorun raporu: kullanıcının notu, sürüm ve sistem bilgisi, uygulama kaydının son satırları.
    Belgelerin içeriği girmez; ev klasörünün yolu ~ ile kısaltılır."""
    import platform
    try:
        log = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        log = ["(kayıt dosyası bulunamadı)"]
    log = [line for line in map(ANSI.sub, [""] * len(log), log) if not ROUTINE_LOG.search(line)][-150:]   # başarılı istekler kalabalık etmesin
    engines = {**converters.engines(), "metin tanıma": ocr.available()}
    text = "\n".join([
        "Koç PDF Pro sorun raporu",
        f"Tarih: {time.strftime('%d.%m.%Y %H:%M')}",
        f"Sürüm: {SURUM}{' · kaynak ' + KAYNAK[:10] if KAYNAK else '' if PACKAGED else ' (geliştirme)'}",
        f"Sistem: {platform.platform()} · {platform.machine()}",
        f"Python {platform.python_version()} · PyMuPDF {pymupdf.__version__}",
        "Bileşenler: " + ", ".join(f"{k} {'var' if v else 'yok'}" for k, v in engines.items()),
        "", "Kullanıcının notu:", message.strip() or "(boş)",
        "", f"Uygulama kaydı (son {len(log)} satır):", *log])
    return text.replace(str(Path.home()), "~")


@app.get("/api/report")
def report_preview():
    return jsonify(text=report_text())


@app.post("/api/report")
def report_make():
    """Rapor dosyası yazılır (son 10 rapor saklanır); e-posta programına verilecek bilgiler döner."""
    message = str((request.get_json(silent=True) or {}).get("message") or "")[:4000].strip()
    folder = DATA / "raporlar"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"KocPDFPro-sorun-raporu-{time.strftime('%Y%m%d-%H%M%S')}.txt"
    path.write_text(report_text(message), encoding="utf-8")
    for old in sorted(folder.glob("KocPDFPro-sorun-raporu-*.txt"))[:-10]:
        old.unlink(missing_ok=True)
    return jsonify(path=str(path), to=CONTACT, subject=f"Koç PDF Pro - Sorun bildirimi ({SURUM})",
                   body=(message + "\n\n" if message else "") + "Sorun raporu ekte.")


@app.post("/api/kilavuz/pdf")
def guide_pdf():
    """Kullanım kılavuzunun PDF hâli (Kılavuz ekranındaki "PDF olarak kaydet"); Windows'ta kısayollar Ctrl / Shift."""
    folder = BASE / "static" / "kilavuz"
    out = new_output("Koç PDF Pro Kullanım Kılavuzu.pdf")
    kilavuz.build_pdf((folder / "kilavuz.html").read_text(encoding="utf-8"), folder, out, SURUM, windows=IS_WIN)
    return jsonify(describe(out))


# ------------------------------------------------------------------ dönüştürme

def run_each(paths, fn):
    """Her dosyayı ayrı işler; biri başarısız olursa diğerleri devam eder."""
    results = []
    for p in paths:
        try:
            results.append(fn(p))
        except (ToolError, ConversionError) as e:
            results.append({"name": display_name(p), "error": str(e)})
    return jsonify(files=results)


@app.post("/api/convert/word-to-pdf")
def word_to_pdf():
    def one(p):
        out = new_output(stem(p) + ".pdf")
        converters.word_to_pdf(p, out)
        return describe(out)
    return run_each(save_uploads(), one)


@app.post("/api/convert/excel-to-pdf")
def excel_to_pdf():
    """Excel (CSV, ODS) → PDF: bütün çalışma sayfaları, Excel'in sayfa düzeniyle (Microsoft Excel ya da LibreOffice)."""
    def one(p):
        out = new_output(stem(p) + ".pdf")
        converters.excel_to_pdf(p, out)
        return describe(out)
    return run_each(save_uploads(), one)


# ------------------------------------------------------------------ metin tanıma (OCR)

@app.post("/api/tool/ocr")
def ocr_tool():
    """Taranmış PDF ya da fotoğraf → aranabilir, kopyalanabilir PDF"""
    every_page = request.form.get("mode") == "all"

    def one(p):
        ext = p.suffix.lower()
        if ext in converters.IMAGE_INPUTS:
            pdf = p.parent / (p.stem + "_resim.pdf")
            converters.images_to_pdf([p], pdf, "orijinal", 0)
        elif ext == ".pdf":
            pdf = p
        else:
            raise ToolError(f"Desteklenmeyen dosya türü: {ext}")
        doc = tools.open_pdf(pdf)
        count = ocr.ocr_document(doc, only_missing=not every_page, cache_dir=DATA)
        out = new_output(stem(p) + "_aranabilir.pdf")
        tools.save_pdf(doc, out)
        note = f"{count} sayfada metin tanındı" if count else "Sayfalarda zaten metin vardı; değişiklik gerekmedi"
        if count and ocr.notice():   # Windows'ta Türkçe tanıma paketi yoksa
            note += ". " + ocr.notice()
        return describe(out, note=note, changed=bool(count))
    return run_each(save_uploads(), one)


# ------------------------------------------------------------------ UYAP (UDF)

def _udf_doc(p):
    if p.suffix.lower() != ".udf":
        raise ToolError(f"{display_name(p)} bir UDF dosyası değil.")
    return udf.read(p)


@app.post("/api/convert/udf-to-pdf")
def udf_to_pdf():
    def one(p):
        out = new_output(stem(p) + ".pdf")
        udf.to_pdf(_udf_doc(p), out, DATA)
        return describe(out)
    return run_each(save_uploads(), one)


@app.post("/api/convert/udf-to-word")
def udf_to_word():
    def one(p):
        out = new_output(stem(p) + ".docx")
        udf.to_docx(_udf_doc(p), out)
        return describe(out)
    return run_each(save_uploads(), one)


@app.post("/api/convert/to-udf")
def to_udf():
    """Word (.docx/.doc/.rtf/.odt) ya da PDF → UDF"""
    def one(p):
        ext = p.suffix.lower()
        work = p
        if ext == ".pdf":
            work = p.parent / (p.stem + "_donusum.docx")
            converters.pdf_to_word(p, work)
        elif ext in (".doc", ".rtf", ".odt", ".docm", ".dotx"):
            if not converters.word_installed():
                raise ConversionError(f"{ext} dosyasını UDF'ye çevirmek için Microsoft Word gerekli; .docx olarak kaydedip deneyin.")
            work = p.parent / (p.stem + "_donusum.docx")
            converters._word_export(p, work, "docx")
        elif ext != ".docx":
            raise ToolError(f"Desteklenmeyen dosya türü: {ext}")
        out = new_output(stem(p) + ".udf")
        notes = udf.from_docx(work, out)
        return describe(out, note=" ".join(notes) or None)
    return run_each(save_uploads(), one)


@app.post("/api/convert/pdf-to-word")
def pdf_to_word():
    engine = request.form.get("engine", "standart")
    password = request.form.get("password") or None

    def one(p):
        out = new_output(stem(p) + ".docx")
        converters.pdf_to_word(p, out, engine=engine, password=password)
        return describe(out)
    return run_each(save_uploads(), one)


@app.post("/api/convert/pdf-to-excel")
def pdf_to_excel():
    """PDF'teki tablolar (ya da bütün sayfa satır satır) Excel'e. content: tables|all, layout: pages|single"""
    content = "all" if request.form.get("content") == "all" else "tables"
    layout = "single" if request.form.get("layout") == "single" else "pages"

    def one(p):
        out = new_output(stem(p) + ".xlsx")
        result = tablolar.to_excel(p, out, content, layout)
        return describe(out) | {"note": result["note"]}
    return run_each(save_uploads(), one)


@app.post("/api/convert/images-to-pdf")
def images_to_pdf():
    paths = save_uploads()
    size = request.form.get("page_size", "orijinal")
    margin = 28 if size != "orijinal" else 0
    if form_bool("separate"):
        def one(p):
            out = new_output(stem(p) + ".pdf")
            converters.images_to_pdf([p], out, size, margin)
            return describe(out)
        return run_each(paths, one)
    name = request.form.get("name") or (stem(paths[0]) if len(paths) == 1 else "resimler")
    out = new_output(safe_name(name) + ".pdf")
    converters.images_to_pdf(paths, out, size, margin)
    return jsonify(files=[describe(out)])


@app.post("/api/convert/pdf-to-images")
def pdf_to_images():
    fmt = request.form.get("format") if request.form.get("format") in ("jpg", "tiff") else "png"
    dpi = min(max(int(request.form.get("dpi", 150)), 50), 600)

    def one(p):
        if fmt == "tiff":   # bütün sayfalar tek TIFF dosyasında
            out = new_output(stem(p) + ".tif")
            converters.pdf_to_tiff(p, out, dpi, request.form.get("color", "gri"))
            return describe(out)
        with pymupdf.open(p) as d:
            single = d.page_count == 1
        out = new_output(stem(p) + (f".{fmt}" if single else f"_{fmt}.zip"))   # tek sayfa: ZIP yerine doğrudan resim
        converters.pdf_to_images(p, out, fmt, dpi, name=stem(p))
        return describe(out)
    return run_each(save_uploads(), one)


# ------------------------------------------------------------------ araçlar

@app.post("/api/tool/merge")
def merge():
    """PDF, Word, Excel, UDF, resim ve TIFF dosyaları listedeki sırayla tek PDF'te; her dosya içindekilerde bir başlık."""
    paths = save_uploads()
    name = request.form.get("name") or "birlestirilmis"
    out = new_output(safe_name(name) + ".pdf")
    work = UPLOADS / ("birlestir_" + uuid.uuid4().hex[:8])
    work.mkdir()
    pdfs = [as_pdf(p, work / f"{k:03d}.pdf") for k, p in enumerate(paths)]
    tools.merge(pdfs, out, titles=[stem(p) for p in paths])
    return jsonify(files=[describe(out)])


@app.post("/api/tool/compare")
def compare_tool():
    """İki sürüm (PDF, Word, Excel, UDF) arasındaki farklar: listedeki ilk dosya eski, ikincisi yeni sürüm sayılır."""
    paths = save_uploads()
    if len(paths) != 2:
        raise ToolError("Karşılaştırmak için iki dosya seçin: önce eski, sonra yeni sürüm.")
    work = UPLOADS / ("karsilastir_" + uuid.uuid4().hex[:8])
    work.mkdir()
    old, new = (as_pdf(p, work / f"{k}.pdf") for k, p in enumerate(paths))
    out = new_output(safe_name(f"karsilastirma_{stem(paths[1])}") + ".pdf")
    result = karsilastir.compare(old, new, out, display_name(paths[0]), display_name(paths[1]), DATA)
    return jsonify(files=[describe(out) | {"note": result["note"]}])


def as_pdf(src: Path, dst: Path):
    """Birleştirme ve karşılaştırma için PDF hâli: Word Word'le, Excel Excel'le, UDF kendi çizimimizle, resim ve TIFF
    A4 sayfalara."""
    ext = src.suffix.lower()
    if ext == ".pdf":
        return src
    try:
        if ext == ".udf":
            udf.to_pdf(udf.read(src), dst, DATA)
        elif ext in converters.WORD_INPUTS:
            converters.word_to_pdf(src, dst)
        elif ext in converters.EXCEL_INPUTS:
            converters.excel_to_pdf(src, dst)
        elif ext in converters.IMAGE_INPUTS | converters.TIFF_INPUTS:
            converters.images_to_a4([src], dst)
        else:
            raise ToolError(f"{display_name(src)}: bu dosya türü kullanılamaz.")
    except (ConversionError, UdfError) as e:
        raise ToolError(f"{display_name(src)}: {e}")
    return dst


@app.post("/api/tool/split")
def split():
    p = save_uploads()[0]
    tmp = UPLOADS / ("split_" + uuid.uuid4().hex[:8])
    tmp.mkdir()
    mode = request.form.get("mode", "each")
    parts = tools.split(p, tmp, mode=mode, spec=request.form.get("spec", ""),
                        every=request.form.get("every", 1))
    results = []
    for part in parts:   # sayfa sırasıyla (ada göre sıralanırsa 10. parça 2.'den önce gelir); alt dosyalara Türkçe ad
        out = new_output(part.name.replace(p.stem, stem(p)))
        shutil.move(str(part), out)
        results.append(describe(out))
    shutil.rmtree(tmp, ignore_errors=True)
    return jsonify(files=results)


@app.post("/api/tool/compress")
def compress():
    level = request.form.get("level", "orta")

    def one(p):
        out = new_output(stem(p) + "_sikistirilmis.pdf")
        tools.compress(p, out, level)
        before, after = p.stat().st_size, out.stat().st_size
        if after >= before:  # küçülmediyse orijinali ver
            shutil.copy(p, out)
            after = before
        return describe(out, before=before, after=after, changed=after < before)
    return run_each(save_uploads(), one)


@app.post("/api/tool/protect")
def protect():
    pw = request.form.get("password", "")

    def one(p):
        out = new_output(stem(p) + "_sifreli.pdf")
        tools.protect(p, out, pw, allow_print=form_bool("allow_print"), allow_copy=form_bool("allow_copy"))
        return describe(out)
    return run_each(save_uploads(), one)


@app.post("/api/tool/unlock")
def unlock():
    pw = request.form.get("password", "")

    def one(p):
        out = new_output(stem(p) + "_sifresiz.pdf")
        tools.unlock(p, out, pw)
        return describe(out)
    return run_each(save_uploads(), one)


@app.post("/api/tool/watermark")
def watermark():
    f = request.form

    def one(p):
        out = new_output(stem(p) + "_filigranli.pdf")
        tools.watermark(p, out, f.get("text", ""), size=float(f.get("size", 60)),
                        opacity=float(f.get("opacity", 0.18)), color=f.get("color", "#c0392b"),
                        angle=float(f.get("angle", 45)), pages_spec=f.get("pages", ""))
        return describe(out)
    return run_each(save_uploads(), one)


@app.post("/api/tool/numbers")
def numbers():
    f = request.form
    paths = save_uploads()
    fmt = f.get("format", "n")
    first_ek = int(f.get("ek_no", 1) or 1)
    # Birden çok dosya seçildiyse her dosya sıradaki eki olur: Ek 1, Ek 2 …
    ek_of = {p: first_ek + (i if form_bool("ek_artir") else 0) for i, p in enumerate(paths)}

    def one(p):
        suffix = f"_ek{ek_of[p]}" if fmt in tools.EK_FORMATS else "_numarali"
        out = new_output(stem(p) + suffix + ".pdf")
        tools.page_numbers(p, out, position=f.get("position", "alt-orta"), fmt=fmt,
                           start=int(f.get("start", 1) or 1), size=float(f.get("size", 11)),
                           skip_first=form_bool("skip_first"), color=f.get("color", "#000000"),
                           template=f.get("template"), bold=form_bool("bold"),
                           font=f.get("font", "serif"), ek=ek_of[p])
        return describe(out)
    return run_each(paths, one)


# ------------------------------------------------------------------ çıktılar

@app.get("/api/out/<oid>")
def download(oid):
    path = output_path(oid)
    return send_file(path, as_attachment=True, download_name=path.name)


@app.post("/api/out/zip")
def zip_outputs():
    """Seçilen çıktıları tek bir ZIP çıktısında toplar (indirme bağlantısı döner)."""
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    out = new_output("PDF_Studyo.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        used = set()
        for oid in ids:
            p = output_path(oid)
            name = p.name
            k = 1
            while name in used:
                name = f"{p.stem} ({k}){p.suffix}"
                k += 1
            used.add(name)
            z.write(p, name)
    return jsonify(describe(out))


@app.post("/api/out/<oid>/save")
def out_save(oid):
    """Çıktıyı kaydetme penceresinde seçilen yere yazar (üzerine yazılan dosya yedeklenir)."""
    src = output_path(oid)
    target = target_path((request.get_json(silent=True) or {}).get("path"))
    backup = backup_before_write(target)
    write_file(target, lambda tmp: shutil.copy(src, tmp))
    return jsonify(path=str(target), backup=backup)


@app.post("/api/out/save-all")
def out_save_all():
    """Birden çok çıktıyı seçilen klasöre kaydeder; aynı adlı dosyalar korunur."""
    data = request.get_json(silent=True) or {}
    folder = Path(data.get("dir") or "").expanduser()
    if not data.get("dir") or not folder.is_absolute() or not folder.is_dir():
        raise ToolError("Klasör bulunamadı.")
    paths = []
    for oid in data.get("ids", []):
        src = output_path(oid)
        target = unique_path(folder / src.name)
        write_file(target, lambda tmp, src=src: shutil.copy(src, tmp))
        paths.append(str(target))
    return jsonify(dir=str(folder), paths=paths)


# ------------------------------------------------------------------ format değiştir
# Dönüştür penceresine eklenen dosya bir kez sunucuya alınır (küçük resmi ve sayfa sayısı için); dönüştürülürken
# yeniden gönderilmez, kimliğiyle (staged) kullanılır. Sonuçlar seçilen klasöre birlikte kaydedilir.

def file_kind(name):
    e = Path(name).suffix.lower()
    if e in (".pdf", ".udf"):
        return e[1:]
    if e in converters.WORD_INPUTS:
        return "word"
    if e in converters.EXCEL_INPUTS:
        return "excel"
    if e in converters.IMAGE_INPUTS or e in converters.TIFF_INPUTS:
        return "image"
    return None


def staged_path(sid):
    d = UPLOADS / ("stage_" + secure_filename(sid or ""))
    files = list(d.iterdir()) if d.is_dir() else []
    if not files:
        raise ToolError("Dosya bulunamadı (süresi dolmuş olabilir); listeden çıkarıp yeniden ekleyin.")
    return files[0]


def stage_preview(path, kind):
    """İlk sayfanın küçük resmi (data URL) ve sayfa sayısı; Word, Excel ve UDF'de yok."""
    if kind not in ("pdf", "image"):
        return {}
    try:
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                return {"encrypted": True}
            page = doc[0]
            z = 112 / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
            # resimli ilk sayfa: Sıkıştır önizlemesi oradan başlar
            image_page = next((i for i in range(min(doc.page_count, 50)) if doc[i].get_images()), 0)
            # Sıkıştır: e-imza uyarısı ve gömülü ek dosyalar (sayısı, kapladığı yer)
            attached = [doc.embfile_info(i)["length"] for i in range(doc.embfile_count())] if kind == "pdf" else []
            return {"pages": doc.page_count, "image_page": image_page, "signed": kind == "pdf" and editor.is_signed(doc),
                    "bookmarks": len(doc.get_toc()) if kind == "pdf" else 0,
                    "attachments": [len(attached), sum(attached)],
                    "thumb": "data:image/jpeg;base64," + base64.b64encode(pix.tobytes("jpeg", jpg_quality=80)).decode()}
    except Exception:   # bozuk dosya ya da açılamayan resim (HEIC): küçük resimsiz
        return {}


def desktop_dir():
    if IS_WIN:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and Path(buf.value).is_dir():   # Masaüstü (OneDrive'a taşınmış olabilir)
                return Path(buf.value)
        except (OSError, AttributeError):
            pass
    d = Path.home() / "Desktop"
    return d if d.is_dir() else Path.home()


@app.post("/api/stage")
def stage():
    """Pencereye eklenen dosyalar: yüklenen dosyalar, diskteki yolları (yerel uygulama) ya da açık belge (sid).
    Dönen: files [{id, name, kind, size, pages, thumb, encrypted, dir}] (desteklenmeyen dosyada error)"""
    data = request.get_json(silent=True) or {}
    items = []   # (ad, kopyalayan işlev, bulunduğu klasör, ek bilgi)
    if data.get("sid"):   # açık belge: ekrandaki hâli; rev: hangi sürümü (sonuç belgeye uygulanırken denetlenir)
        s = store.get(data["sid"])
        with s.lock:
            items.append((Path(s.name).stem + ".pdf", lambda t, src=Path(s.path): shutil.copy(src, t),
                          str(Path(s.source).parent) if s.source else None, {"rev": Path(s.path).name}))
    for raw in data.get("paths") or []:
        src = Path(str(raw)).expanduser()
        if not src.is_absolute() or not src.is_file():
            raise ToolError(f"{src.name} bulunamadı.")
        items.append((src.name, lambda t, src=src: shutil.copy(src, t), str(src.parent), {}))
    for f in request.files.getlist("files"):
        items.append((f.filename, f.save, None, {}))
    out = []
    for name, put, folder, extra in items:
        name = safe_name(name)
        kind = file_kind(name)
        if not kind:
            out.append({"name": name, "error": "Bu dosya türü dönüştürülemez."})
            continue
        sid = uuid.uuid4().hex[:12]
        target = UPLOADS / f"stage_{sid}" / f"000_{name}"
        target.parent.mkdir()
        put(target)
        if kind == "pdf":
            try:
                pymupdf.open(target).close()
            except Exception:
                shutil.rmtree(target.parent, ignore_errors=True)
                out.append({"name": name, "error": "Açılamadı; dosya bozuk ya da PDF değil."})
                continue
        out.append({"id": sid, "name": name, "kind": kind, "size": target.stat().st_size, "dir": folder}
                   | extra | stage_preview(target, kind))
    return jsonify(files=out, desktop=str(desktop_dir()))


@app.post("/api/stage/<sid>/unlock")
def stage_unlock(sid):
    """Şifreli PDF: pencerede girilen şifreyle şifresiz kopyası alınır (dönüştürmeler şifresiz kopyayla yapılır)."""
    path = staged_path(sid)
    doc = pymupdf.open(path)
    if doc.needs_pass and not doc.authenticate((request.get_json(silent=True) or {}).get("password") or ""):
        return jsonify(ok=False)
    tmp = path.with_name("sifresiz.pdf")
    doc.save(tmp, encryption=pymupdf.PDF_ENCRYPT_NONE)
    doc.close()
    os.replace(tmp, path)
    return jsonify(ok=True, **stage_preview(path, "pdf"))


# Sıkıştır penceresi: her düzeyin gerçek sonucu bir kez hesaplanır ve saklanır; düzey değiştirmek, hedef boyut
# denemek ya da kaydetmek yeniden sıkıştırmaz.
COMPRESSED = {}   # (alınmış dosya kimliği, düzey, renk, kaldırılanlar) → sonuç
COMPRESS_NAMES = {"dusuk": "Hafif", "orta": "Önerilen", "ara": "Önerilen ile Güçlü arası", "yuksek": "Güçlü",
                  "en-yuksek": "En güçlü"}


def compress_note(stats, smaller, level):
    if not smaller:
        return "Belge zaten küçük; değişiklik gerekmedi"
    done = []
    if stats.get("bitonal"):
        done.append(f"{stats['bitonal']} taranmış sayfa siyah-beyaz yapıldı")
    elif stats.get("gray"):
        done.append("belge gri yapıldı")
    if stats.get("images"):
        done.append(f"{stats['images']} resim küçültüldü")
    if stats.get("attachments"):
        done.append(f"{stats['attachments']} ek dosya kaldırıldı")
    if stats.get("meta"):
        done.append("belge bilgileri temizlendi")
    if stats.get("thumbs"):
        done.append(f"{stats['thumbs']} sayfa küçük resmi kaldırıldı")
    if done:
        note = " · ".join(done)
        return note[0].upper() + note[1:]
    if level == "dusuk":
        return "Görünüm aynı; gereksiz veriler temizlendi, yazı tipleri küçültüldü"
    return ("Resimler zaten yeterince küçük" if stats.get("found") else "Belgede resim yok") + "; gereksiz veriler temizlendi"


def compressed(sid, level, color="renkli", drop=()):
    key = (sid, level, color, drop)
    res = COMPRESSED.get(key)
    if res and (OUTPUTS / res["id"]).is_dir():
        return res
    src = staged_path(sid)
    out = new_output(Path(display_name(src)).stem + "_sikistirilmis.pdf")
    stats = tools.compress(src, out, level, color, drop)
    before, after = src.stat().st_size, out.stat().st_size
    if after >= before:   # küçülmediyse aslı
        shutil.copy(src, out)
        after = before
    res = describe(out, level=level, level_name=COMPRESS_NAMES[level], before=before, after=after,
                   changed=after < before, note=compress_note(stats, after < before, level))
    COMPRESSED[key] = res
    while len(COMPRESSED) > 400:   # en eskiler unutulur
        COMPRESSED.pop(next(iter(COMPRESSED)))
    return res


@app.post("/api/compress")
def compress_staged():
    """Alınmış PDF'i bir düzeyde (ve renkte: renkli, gri, sb) sıkıştırır; drop: kaldırılacaklar (attachments, meta). target (bayt) verilirse düzeyler hafiften güçlüye denenir; hedefe inen ilk
    (en kaliteli) sonuç döner, inilemezse en küçüğü (reached: false)."""
    data = request.get_json(silent=True) or {}
    target = int(data.get("target") or 0)
    color = data.get("color") if data.get("color") in tools.COLORS else "renkli"
    drop = tuple(sorted({d for d in data.get("drop") or [] if d in ("attachments", "meta")}))
    if not target:
        level = data.get("level") if data.get("level") in tools.COMPRESS_LEVELS else "orta"
        return jsonify(compressed(data.get("id"), level, color, drop) | {"reached": True})
    best = None
    for level in tools.COMPRESS_STEPS:
        res = compressed(data.get("id"), level, color, drop)
        if res["after"] <= target:
            return jsonify(res | {"reached": True})
        if best is None or res["after"] < best["after"]:
            best = res
    return jsonify(best | {"reached": False})


@app.get("/api/stage/<sid>/page/<int:index>")
def stage_page(sid, index):
    """Alınmış dosyanın bir sayfasının küçük resmi (Böl penceresi), JPEG; w: piksel genişliği."""
    width = min(max(int(request.args.get("w") or 160), 40), 800)
    with pymupdf.open(staged_path(sid)) as doc:
        if not 0 <= index < doc.page_count:
            raise ToolError("Sayfa bulunamadı.")
        page = doc[index]
        z = width / page.rect.width
        data = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False).tobytes("jpeg", jpg_quality=75)
    resp = send_file(io.BytesIO(data), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@app.post("/api/split/plan")
def split_plan():
    """Böl penceresinin sunucuda hesaplanan yöntemleri: toc (içindekilerin başlıkları), size (her parça en fazla limit
    bayt), blank (boş sayfalar). Dönen: {cuts: [bu sayfadan sonra kes], skip: [alınmayacak sayfalar], names: {parçanın ilk sayfası: ad},
    sizes: {parçanın ilk sayfası: bayt}, note}"""
    data = request.get_json(silent=True) or {}
    doc = tools.open_pdf(staged_path(data.get("id")))
    try:
        if data.get("mode") == "toc":
            return jsonify(tools.toc_plan(doc))
        if data.get("mode") == "size":
            return jsonify(tools.size_plan(doc, max(int(data.get("limit") or 0), 100_000)))
        if data.get("mode") == "blank":
            return jsonify(tools.blank_plan(doc))
        raise ToolError("Bilinmeyen bölme yöntemi.")
    finally:
        doc.close()


@app.post("/api/split")
def split_staged():
    """Böl penceresi: parts [{pages: sayfalar (0'dan), name}] → her parça ayrı PDF, verilen sırayla; parçalar kendi
    yer imlerini korur."""
    data = request.get_json(silent=True) or {}
    doc = tools.open_pdf(staged_path(data.get("id")))
    results = []
    for k, part in enumerate(data.get("parts") or [], 1):
        pages = [int(p) for p in part.get("pages") or []]
        if not pages or any(not 0 <= p < doc.page_count for p in pages):
            doc.close()
            raise ToolError(f"{k}. parçanın sayfaları geçersiz.")
        name = safe_name(str(part.get("name") or "")[:150], f"parca_{k}")
        out = new_output((name[:-4] if name.lower().endswith(".pdf") else name) + ".pdf")
        tools.save_pdf(tools.pages_doc(doc, pages), out)
        results.append(describe(out, pages=len(pages)))
    doc.close()
    if not results:
        raise ToolError("Bölünecek parça yok.")
    return jsonify(files=results)


@app.get("/api/compress/page")
def compress_page():
    """Önce / sonra önizlemesi: alınmış dosyanın (src) ya da sıkıştırılmış sonucun (out) bir sayfası, PNG."""
    path = staged_path(request.args.get("src")) if request.args.get("src") else output_path(request.args.get("out", ""))
    zoom = min(max(float(request.args.get("zoom") or 2), 0.5), 6)
    with pymupdf.open(path) as doc:
        page = doc[min(max(int(request.args.get("page") or 0), 0), doc.page_count - 1)]
        data = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png")
    resp = send_file(io.BytesIO(data), mimetype="image/png")
    resp.headers["Cache-Control"] = "private, max-age=600"
    return resp


@app.post("/api/out/save-to")
def out_save_to():
    """Çıktılar bir klasöre: dir (ve folder verilirse içinde açılan alt klasör). items: [{id, name, unzip}]; name verilirse
    dosya bu adla, unzip ise ZIP (sayfa resimleri) bir klasöre açılarak kaydedilir. Hiçbir dosyanın üzerine yazılmaz:
    aynı ad varsa sonuna (1), (2) eklenir. Dönen: {dir, paths}"""
    data = request.get_json(silent=True) or {}
    folder = Path(data.get("dir") or "").expanduser()
    if not data.get("dir") or not folder.is_absolute() or not folder.is_dir():
        raise ToolError("Kaydedilecek klasör bulunamadı.")
    if data.get("folder"):
        folder = folder / safe_name(data["folder"], "Dönüştürülmüş")
        try:
            folder.mkdir(exist_ok=True)
        except OSError as e:
            raise ToolError(f"Klasör oluşturulamadı: {e.strerror or e}")
    paths = []
    for it in data.get("items") or []:
        src = output_path(it.get("id"))
        name = safe_name(it.get("name") or src.name, src.name)
        if Path(name).suffix.lower() != src.suffix.lower():
            name += src.suffix
        if it.get("unzip") and src.suffix.lower() == ".zip":
            target = unique_path(folder / Path(name).stem)
            try:
                target.mkdir()
                with zipfile.ZipFile(src) as z:
                    for member in z.namelist():
                        (target / safe_name(member)).write_bytes(z.read(member))
            except OSError as e:
                raise ToolError(f"Kaydedilemedi: {e.strerror or e}")
        else:
            target = unique_path(folder / name)
            write_file(target, lambda tmp, src=src: shutil.copy(src, tmp))
        paths.append(str(target))
    return jsonify(dir=str(folder), paths=paths)


# ------------------------------------------------------------------ düzenleyici

@app.post("/api/edit/open")
def edit_open():
    data = request.get_json(silent=True) or {}
    source = None
    if data.get("path"):  # yerel uygulama: Finder'dan açılan dosya, yükleme gerekmez
        src = Path(data["path"]).expanduser()
        if not src.is_absolute() or not src.is_file():
            raise ToolError(f"Dosya bulunamadı: {src.name or data['path']}")
        name, source = src.name, str(src)
        m = yedekler.BACKUP_NAME.match(src.name)
        if m and src.resolve().parent == yedekler.BACKUPS.resolve():   # Önceki sürümler: yedek, kopya olarak açılır
            when = time.strftime("%d.%m.%Y %H.%M", time.strptime(m["ts"], "%Y%m%d-%H%M%S"))
            name, source = f"{m['stem']} (yedek {when}){m['suffix']}", None   # Kaydet yedeğin üzerine yazmaz
    elif data.get("out_id"):
        src = output_path(data["out_id"])
        name = src.name
    else:
        src = save_uploads()[0]
        name = display_name(src)
    if src.suffix.lower() == ".udf":   # UYAP belgesi: önce PDF'e çiz, sonra aç
        pdf = UPLOADS / ("udf_" + uuid.uuid4().hex[:10] + ".pdf")
        udf.to_pdf(udf.read(src), pdf, DATA)
        src = pdf
    elif src.suffix.lower() != ".pdf":
        raise ToolError("Yalnızca PDF ve UDF dosyaları açılabilir. Word dosyalarını önce PDF'e dönüştürün.")
    s = store.create(src, name, password=data.get("password") or request.form.get("password") or None,
                     source=source)
    if source:
        remember_recent(source)
    return jsonify(s.info())


# ------------------------------------------------------------------ son açılanlar
# Diskten açılan son 10 belge (ana sayfada listelenir); yedekler ve araç çıktıları girmez.
RECENT_FILE = DATA / "son-acilanlar.json"
RECENT_MAX = 10
recent_lock = threading.Lock()


def load_recent():
    try:
        items = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
        return [it for it in items if isinstance(it, dict) and it.get("path")]
    except (OSError, ValueError):
        return []


def save_recent(items):
    tmp = RECENT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[:RECENT_MAX], ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, RECENT_FILE)


def remember_recent(path):
    with recent_lock:
        items = [it for it in load_recent() if it["path"] != path]
        save_recent([{"path": path, "name": Path(path).name, "time": time.time()}] + items)


@app.get("/api/recent")
def recent_list():
    return jsonify(items=[it | {"exists": Path(it["path"]).is_file()} for it in load_recent()])


@app.post("/api/recent/import")
def recent_import():
    """Eski sürümün (sayfanın belleğindeki) listesi: yalnızca var olan dosyalar, zamana göre sıralı, tekrarsız."""
    incoming = [it for it in (request.get_json(silent=True) or {}).get("items") or []
                if isinstance(it, dict) and isinstance(it.get("path"), str) and Path(it["path"]).is_file()]
    with recent_lock:
        merged, seen = [], set()
        for it in sorted(load_recent() + [{"path": i["path"], "name": Path(i["path"]).name, "time": float(i.get("time") or 0)}
                                          for i in incoming], key=lambda x: -x["time"]):
            if it["path"] not in seen:
                seen.add(it["path"])
                merged.append(it)
        save_recent(merged)
    return jsonify(ok=True)


@app.post("/api/recent/remove")
def recent_remove():
    """Listeden çıkarır ({"path": …}); yol verilmezse liste temizlenir. Dosyalara dokunulmaz."""
    path = (request.get_json(silent=True) or {}).get("path")
    with recent_lock:
        save_recent([it for it in load_recent() if path and it["path"] != path])
    return jsonify(ok=True)


@app.get("/api/edit/<sid>")
def edit_info(sid):
    return jsonify(store.get(sid).info())


@app.get("/api/edit/<sid>/page/<int:index>")
def edit_page(sid, index):
    s = store.get(sid)
    width = min(max(int(request.args.get("w", 300)), 60), 3000)
    with s.lock:
        png = s.render(index, width)
    resp = send_file(io.BytesIO(png), mimetype="image/png")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@app.get("/api/edit/<sid>/search")
def edit_search(sid):
    s = store.get(sid)
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify(hits=[])
    with s.lock:
        return jsonify(hits=s.search(query))


@app.get("/api/search-all")
def search_all():
    """Tüm açık belgelerde arama: belge başına eşleşme sayısı ve ilk sayfaların alıntıları, çoktan aza.
    path: açık sekmelerdeki belgeler (verilirse yalnız onlar); current: bu sekmedeki belge (her zaman dahil)."""
    query = request.args.get("q", "").strip()
    paths, current = set(request.args.getlist("path")), request.args.get("current")
    if not query:
        return jsonify(docs=[])
    latest = {}   # aynı dosya birden çok kez açıldıysa en son kullanılan oturumu
    for s in list(store.sessions.values()):
        if s.closed or (s.id != current and (not s.source or (paths and s.source not in paths))):
            continue
        key = s.source or s.id
        if key not in latest or s.touched > latest[key].touched or s.id == current:
            if latest.get(key) is None or latest[key].id != current:
                latest[key] = s
    docs = []
    for s in latest.values():
        with s.lock:
            hits = s.search(query, limit=500)
        if hits:
            docs.append({"sid": s.id, "name": s.name, "path": s.source, "current": s.id == current,
                         "count": sum(len(h["rects"]) for h in hits),
                         "pages": [{"page": h["page"], "count": len(h["rects"]), "snippet": h["snippet"]} for h in hits[:4]]})
    docs.sort(key=lambda d: (not d["current"], -d["count"]))
    return jsonify(docs=docs)


@app.get("/api/edit/<sid>/lines/<int:index>")
def edit_lines(sid, index):
    s = store.get(sid)
    with s.lock:
        return jsonify(lines=s.lines(index))


@app.post("/api/edit/<sid>/personal-data")
def edit_personal_data(sid):
    """KVKK: belgedeki kişisel veriler (ad soyad, T.C. kimlik no, vergi kimlik no, IBAN, kart, telefon, e-posta,
    aranan kelimeler).
    Taranmış sayfalarda yazı tanınarak aranır (metin tanıma bu bilgisayarda kullanılabiliyorsa)."""
    terms = (request.get_json(silent=True) or {}).get("terms") or []
    s = store.get(sid)
    with s.lock:
        pages = s.scan_pages() if ocr.available() else []
    scans = recognized_lines(s, pages) if pages else {}
    with s.lock:
        return jsonify(s.personal_data(terms[:50], scans))


def recognized_lines(s, indexes):
    """Taranmış sayfaların tanınan yazısı {sayfa: satırlar (okuyucunun kelime biçiminde)}. Sonuç oturumda saklanır:
    okuyucunun metin katmanı ve KVKK aynı tanımayı kullanır. Tanıma sürerken belgenin öbür istekleri beklemez."""
    out, todo = {}, []
    with s.lock:
        doc = s.open()
        try:
            for i in indexes:
                key = (s.path, i)
                if key in s.ocr_words:
                    out[i] = s.ocr_words[key]
                else:
                    work = UPLOADS / ("ocr_" + uuid.uuid4().hex[:10] + ".png")
                    ocr.page_image(doc, i, work)
                    todo.append((i, key, work))
        finally:
            doc.close()
    if not todo:
        return out
    try:
        found = ocr.recognize_images([work for *_, work in todo])
    finally:
        for *_, work in todo:
            work.unlink(missing_ok=True)
    fontfile = fonts.face_file("Arial", cache_dir=DATA)
    font = pymupdf.Font(fontfile=fontfile) if fontfile else pymupdf.Font("helv")
    with s.lock:
        for (i, key, _), lines in zip(todo, found):
            out[i] = s.ocr_words[key] = editor.ocr_word_lines(lines, font)
        while len(s.ocr_words) > 200:
            s.ocr_words.popitem(last=False)
    return out


@app.get("/api/edit/<sid>/words/<int:index>")
def edit_words(sid, index):
    """Okuyucunun seçilebilir metin katmanı (kelime kelime). Düzenleyicinin /lines'ı paragraf döndürür.
    Taranmış sayfa (scan: metni yok ya da yalnızca altta kısa bir yazı var) ?ocr=1 ile tanınır: yazısı seçilip
    kopyalanabilir, belge değişmez."""
    s = store.get(sid)
    with s.lock:
        lines, scan = s.words(index), s.is_scan(index)
    if scan and request.args.get("ocr") == "1" and ocr.available():
        return jsonify(lines=recognized_lines(s, [index])[index], ocr=True)
    return jsonify(lines=lines, scan=scan)


@app.get("/api/edit/<sid>/links/<int:index>")
def edit_links(sid, index):
    s = store.get(sid)
    with s.lock:
        return jsonify(links=s.links(index))


@app.post("/api/edit/<sid>/op")
def edit_op(sid):
    s = store.get(sid)
    if request.content_type and request.content_type.startswith("multipart/"):
        data = request.form.to_dict()
        uploads = save_uploads()
    else:
        data = request.get_json(force=True)
        uploads = []
    op = data.get("op")
    result = {}
    with s.lock:
        doc = s.open_for_edit()
        try:
            if op == "rotate":
                editor.op_rotate(doc, data["pages"], data.get("angle", 90))
            elif op == "delete":
                editor.op_delete(doc, data["pages"])
            elif op == "reorder":
                editor.op_reorder(doc, data["order"])
            elif op == "duplicate":
                editor.op_duplicate(doc, data["pages"])
            elif op == "blank":
                editor.op_blank(doc, int(data.get("after", doc.page_count - 1)))
            elif op == "insert_pdf":
                at = int(data.get("at", doc.page_count))
                for p in uploads:
                    before = doc.page_count
                    editor.op_insert_pdf(doc, p, at)
                    at += doc.page_count - before
            elif op == "insert_images":
                editor.op_insert_images(doc, uploads, int(data.get("at", doc.page_count)))
            elif op == "annotate":
                editor.op_annotate(doc, int(data["page"]), data["items"], DATA)
            elif op == "text_edit":
                paragraflar.op_text_edit(doc, int(data["page"]), data["edits"], DATA)
            elif op == "page_edit":  # metin düzenlemeleri + eklemeler tek adımda
                if data.get("edits"):
                    paragraflar.op_text_edit(doc, int(data["page"]), data["edits"], DATA)
                if data.get("items"):
                    editor.op_annotate(doc, int(data["page"]), data["items"], DATA)
            elif op == "pages_edit":  # birden çok sayfadaki düzenlemeler tek adımda (tek "Geri Al")
                for part in data.get("pages", []):
                    if part.get("edits"):
                        paragraflar.op_text_edit(doc, int(part["page"]), part["edits"], DATA)
                    if part.get("items"):
                        editor.op_annotate(doc, int(part["page"]), part["items"], DATA)
            elif op == "redact_areas":   # KVKK karartması (birden çok sayfa, tek Geri Al adımı)
                kisisel_veri.op_redact_areas(doc, data.get("areas"), bool(data.get("clean_meta")), bool(data.get("fit")))
            elif op == "highlight":
                editor.op_highlight(doc, int(data["page"]), data["rects"], data.get("color"), data.get("note", ""),
                                    data.get("kind", "highlight"))
            elif op == "fill_form":
                formlar.op_fill_form(doc, data.get("fields"))
            elif op == "note":
                editor.op_note(doc, int(data["page"]), float(data["x"]), float(data["y"]), data.get("text", ""))
            elif op == "annot_delete":
                editor.op_annot_delete(doc, int(data["page"]), int(data["xref"]))
            elif op == "annot_style":
                editor.op_annot_style(doc, int(data["page"]), int(data["xref"]), data.get("color"), data.get("kind"))
            elif op == "annot_edit":
                editor.op_annot_edit(doc, int(data["page"]), int(data["xref"]), data.get("text", ""))
            elif op == "bookmark_add":
                editor.op_bookmark_add(doc, int(data["page"]), data.get("title", ""))
            elif op == "bookmark_delete":
                editor.op_bookmark_delete(doc, int(data["index"]))
            elif op == "ocr":
                result["count"] = ocr.ocr_document(doc, only_missing=True, cache_dir=DATA)
                result["notice"] = ocr.notice()
                if result["count"] == 0:
                    doc.close()
                    s.abort_edit()
                    return jsonify(s.info() | result)
            elif op == "replace_all":
                result["count"] = paragraflar.op_replace_all(doc, data.get("find", ""), data.get("replace", ""),
                                                             bool(data.get("match_case")), DATA)
                if result["count"] == 0:
                    doc.close()
                    s.abort_edit()
                    return jsonify(s.info() | result)
            else:
                raise ToolError(f"Bilinmeyen işlem: {op}")
        except Exception:
            if not doc.is_closed:
                doc.close()
            s.abort_edit()
            raise
        parts = [data, *data.get("pages", [])] if op == "pages_edit" else [data]   # karartma: KVKK ya da Karart aracı
        redacting = op == "redact_areas" or any(it.get("type") == "redact" for part in parts for it in part.get("items") or [])
        s.commit(doc, redacted=redacting)
        return jsonify(s.info() | result)


@app.post("/api/edit/<sid>/touch")
def edit_touch(sid):
    """Belge penceresi açık: oturum boşta sayılıp silinmesin (sayfa ara ara bildirir)."""
    store.get(sid)
    return jsonify(ok=True)


@app.post("/api/edit/<sid>/undo")
def edit_undo(sid):
    s = store.get(sid)
    with s.lock:
        s.undo()
        return jsonify(s.info())


@app.post("/api/edit/<sid>/redo")
def edit_redo(sid):
    s = store.get(sid)
    with s.lock:
        s.redo()
        return jsonify(s.info())


@app.get("/api/edit/<sid>/download")
def edit_download(sid):
    s = store.get(sid)
    if request.args.get("inline"):  # okuma/yazdırma: belgenin olduğu gibi gösterimi
        with s.lock:
            data = s.path.read_bytes()
        return send_file(io.BytesIO(data), mimetype="application/pdf", download_name=s.name)
    with s.lock:
        if s.sig_intact:   # e-imzalı: baştan yazılmadan (imza korunur)
            buf = io.BytesIO(s.path.read_bytes())
        else:
            doc = s.open()
            tools.finalize(doc)
            buf = io.BytesIO(doc.tobytes(garbage=3, deflate=True))
            doc.close()
    suffix = request.args.get("suffix") if request.args.get("suffix") in ("notlu", "aranabilir") else "duzenlenmis"
    name = f"{Path(s.name).stem}_{suffix}.pdf"
    return send_file(buf, as_attachment=True, download_name=name, mimetype="application/pdf")


@app.post("/api/edit/<sid>/extract")
def edit_extract(sid):
    """Seçili sayfaları yeni bir PDF olarak çıkarır."""
    s = store.get(sid)
    pages = (request.get_json(silent=True) or {}).get("pages") or []
    with s.lock:
        doc = s.open()
        if not pages or any(not 0 <= p < doc.page_count for p in pages):
            doc.close()
            raise ToolError("Çıkarılacak sayfaları seçin.")
        doc.select(sorted(set(pages)))
        out = new_output(Path(s.name).stem + "_secilen_sayfalar.pdf")
        tools.save_pdf(doc, out)
    return jsonify(describe(out))


@app.post("/api/edit/<sid>/annot-report")
def edit_annot_report(sid):
    """Notlar ve vurgular raporu (Word ya da PDF). {format: docx|pdf, marks, notes, by: page|color}"""
    data = request.get_json(silent=True) or {}
    fmt = "pdf" if data.get("format") == "pdf" else "docx"
    by = "color" if data.get("by") == "color" else "page"
    s = store.get(sid)
    with s.lock:
        doc = s.open()
        try:
            items = notlar.collect(doc, marks=data.get("marks", True), notes=data.get("notes", True))
            pages = doc.page_count
        finally:
            doc.close()
    if not items:
        raise ToolError("Belgede rapora dökülecek vurgu ya da not yok.")
    out = new_output(Path(s.name).stem + f"_notlar.{fmt}")
    if fmt == "pdf":
        notlar.to_pdf(items, s.name, pages, out, DATA, by=by)
    else:
        notlar.to_docx(items, s.name, pages, out, by=by)
    return jsonify(describe(out) | {"count": len(items)})


@app.get("/api/edit/<sid>/fields")
def edit_fields(sid):
    """Doldurulabilir form alanları (okuyucu üstlerine giriş kutuları koyar)."""
    s = store.get(sid)
    with s.lock:
        return jsonify(fields=s.fields())


@app.get("/api/edit/<sid>/annotations")
def edit_annotations(sid):
    s = store.get(sid)
    with s.lock:
        return jsonify(s.annotations())


@app.post("/api/edit/<sid>/save")
def edit_save(sid):
    """Kaydet: açılan dosyanın üzerine (eski hâli yedeklenir). Farklı Kaydet: {"path": seçilen yer}.
    Dosya bu arada değiştirilmiş ya da taşınmışsa 409 döner (arayüz sorar); {"force": true} ile yine yazılır."""
    s = store.get(sid)
    data = request.get_json(silent=True) or {}
    chosen, force = data.get("path"), bool(data.get("force"))
    with s.lock:
        if chosen:
            target = target_path(chosen, ".pdf")
        else:
            if not s.info()["can_save_source"]:
                raise ToolError("Bu belgenin kaydedileceği dosya bilinmiyor; Farklı Kaydet ile bir yer seçin.")
            target = Path(s.source)
            if not target.exists():
                if not force:
                    return jsonify(error="Açtığınız dosya bulunamadı (taşınmış ya da silinmiş olabilir).", conflict="missing"), 409
                if not target.parent.is_dir():
                    raise ToolError("Dosyanın klasörü de bulunamadı; Farklı Kaydet ile bir yer seçin.")
            elif not force and s.source_changed(target):
                return jsonify(error="Dosya siz çalışırken başka bir uygulamada değiştirilmiş.", conflict="modified"), 409
        backup = backup_before_write(target)

        def write(tmp):
            if s.sig_intact:   # e-imzalı: dosya olduğu gibi (değişiklikler sonuna eklenmiş); baştan yazmak imzayı bozar
                shutil.copy(s.path, tmp)
                return
            doc = s.open()
            tools.finalize(doc)
            doc.save(tmp, garbage=3, deflate=True)
            doc.close()
        write_file(target, write)
        # Bundan sonra "Kaydet" bu dosyaya yazar
        s.source, s.name, s.encrypted = str(target), target.name, False
        s.source_stamp = editor.file_stamp(target)
        s.saved = s.path
        s.persist()
        return jsonify(s.info() | {"path": str(target), "backup": backup})


@app.get("/api/backups")
def backups_list():
    """Önceki sürümler: açık dosyanın yedekleri."""
    target = Path(request.args.get("path") or "")
    if not target.is_absolute():
        raise ToolError("Belgenin dosyası bilinmiyor.")
    return jsonify(items=[{"id": f.name, "path": str(f), "time": time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(t)),
                           "size": f.stat().st_size} for f, t in yedekler.backups_of(target)])


@app.post("/api/backups/restore")
def backups_restore():
    """Seçilen yedeği dosyanın yerine koyar; dosyanın şimdiki hâli de yedeklenir (geri yükleme de geri alınabilir)."""
    data = request.get_json(silent=True) or {}
    target = Path(data.get("path") or "")
    chosen = next((f for f, _ in yedekler.backups_of(target) if f.name == data.get("id")), None) if target.is_absolute() else None
    if not chosen:
        raise ToolError("Yedek bulunamadı.")
    if not target.parent.is_dir():
        raise ToolError("Dosyanın klasörü bulunamadı (taşınmış ya da silinmiş olabilir).")
    content = chosen.read_bytes()   # önce oku: yeni yedek alınınca en eski yedek silinebilir
    backup = backup_before_write(target)
    write_file(target, lambda tmp: tmp.write_bytes(content))
    return jsonify(ok=True, backup=backup)


@app.post("/api/edit/<sid>/mark-saved")
def edit_mark_saved(sid):
    """Tarayıcı kendi kaydetme penceresiyle yazdıysa (Windows): belge kaydedildi sayılır."""
    s = store.get(sid)
    name = (request.get_json(silent=True) or {}).get("name")
    with s.lock:
        s.saved = s.path
        if name:   # belge artık tarayıcının seçtiği dosyada; sunucu o dosyanın yerini bilmez
            s.name, s.source = safe_name(name), None
        s.persist()
        return jsonify(s.info())


@app.post("/api/edit/<sid>/export")
def edit_export(sid):
    """Farklı Kaydet seçenekleri: açık belgenin düzleştirilmiş / küçültülmüş / bilgileri temizlenmiş / şifreli kopyası."""
    o = request.get_json(silent=True) or {}
    password = str(o.get("password") or "")
    name = safe_name(str(o.get("name") or ""), "belge")
    out = new_output(name if name.lower().endswith(".pdf") else name + ".pdf")
    s = store.get(sid)
    with s.lock:
        tools.export_pdf(s.path, out, flatten=bool(o.get("flatten")), shrink=bool(o.get("shrink")),
                         clean_meta=bool(o.get("clean_meta")), password=password)
    return jsonify(describe(out))


@app.post("/api/edit/<sid>/close")
def edit_close(sid):
    """Kullanıcı belgeyi kapattı: kaydedilmemiş değişiklikleri sonraki açılışta kurtarılmak üzere sunulmaz."""
    s = store.get(sid)
    with s.lock:
        s.closed = True
        s.persist()
    return jsonify(ok=True)


# ------------------------------------------------------------------ otomatik kurtarma
# Uygulama beklenmedik şekilde kapanırsa (çökme, elektrik kesintisi, kaydetmeden çıkış) oturumlar diskte kalır;
# bir sonraki açılışta kaydedilmemiş değişikliği olan belgeler listelenir (7 gün).
RECOVER_OFFERED = False


@app.get("/api/recover")
def recover_list():
    """Kurtarılabilir belgeler. ?ilk=1 soran ilk sekmeye first: true döner (pencere yalnız orada kendiliğinden açılır)."""
    global RECOVER_OFFERED
    if not store.scanned:
        store.scan()
    items = sorted(store.recoverable.values(), key=lambda x: -x["ts"])
    first = bool(items) and not RECOVER_OFFERED and request.args.get("ilk") == "1"
    RECOVER_OFFERED = RECOVER_OFFERED or first
    return jsonify(items=items, first=first)


@app.post("/api/recover/<sid>")
def recover_open(sid):
    return jsonify(store.restore(sid).info())


@app.post("/api/recover/<sid>/discard")
def recover_discard(sid):
    if sid not in store.recoverable:
        raise ToolError("Kurtarılacak belge bulunamadı.")
    store.discard(sid)
    return jsonify(ok=True)


# ------------------------------------------------------------------ ayarlar penceresi

@app.get("/api/settings")
def settings_get():
    return jsonify(settings=ayarlar.read_settings(), desktop=str(desktop_dir()), version=SURUM, packaged=PACKAGED)


@app.post("/api/settings")
def settings_set():
    """Değişen ayarlar ({ad: değer}); geçersiz değer kabul edilmez. Yedek sınırı düşerse fazlası hemen silinir."""
    body = request.get_json(silent=True) or {}
    s = ayarlar.save_settings(body)
    if body.keys() & {"backupKeep", "backupDays"}:
        yedekler.prune_backups()
    return jsonify(settings=s)


@app.get("/api/backups/prune-preview")
def backups_prune_preview():
    """Yedek sınırı düşürülürse kaç eski sürüm silinir (sayfa önce sorar)."""
    keep, days = request.args.get("keep", type=int), request.args.get("days", type=int)
    return jsonify(count=len(yedekler.prune_backups(keep, days, dry=True)))


def folder_size(root):
    size = count = 0
    for f in root.rglob("*"):
        try:
            if f.is_file():
                size += f.stat().st_size
                count += 1
        except OSError:
            pass
    return size, count


TEMP_GRACE = 15 * 60   # temizlerken son 15 dakikada kullanılan geçici dosyalar kalır (açık bir pencerede olabilir)


@app.get("/api/storage")
def storage():
    """Ayarlar › Depolama: geçici dosyalar, önceki sürümler (yedekler), kurtarılabilir belgeler."""
    if not store.scanned:
        store.scan()
    temp = sum(folder_size(d)[0] for d in (UPLOADS, OUTPUTS, SHARES))
    backups, count = folder_size(yedekler.BACKUPS) if yedekler.BACKUPS.exists() else (0, 0)
    return jsonify(temp=temp, backups=backups, backup_count=count, recover=len(store.recoverable), data=str(DATA))


@app.post("/api/storage/clean")
def storage_clean():
    """{"what": "temp"}: geçici dosyalar · {"what": "backups"}: bütün önceki sürümler. Dönen: güncel depolama bilgisi."""
    what = (request.get_json(silent=True) or {}).get("what")
    if what == "temp":
        clean_temp(TEMP_GRACE)
    elif what == "backups":
        for f in yedekler.BACKUPS.glob("*") if yedekler.BACKUPS.exists() else ():
            if f.is_file():
                f.unlink(missing_ok=True)
    else:
        raise ToolError("Neyin temizleneceği belirtilmedi.")
    return storage()


# Açık belgeyle kullanılabilen araçlar. True: sonuç belgenin yeni hâli olur (düzenleyicide hemen görünür,
# Geri Al ile geri alınır); False: belgeden ayrı bir dosya üretilir (Word, UDF, bölünmüş parçalar…).
DOC_TOOLS = {
    "watermark": (watermark, True), "numbers": (numbers, True), "compress": (compress, True),
    "ocr": (ocr_tool, True), "merge": (merge, True),
    "pdf-to-word": (pdf_to_word, False), "pdf-to-excel": (pdf_to_excel, False), "pdf-to-images": (pdf_to_images, False),
    "split": (split, False),
    "to-udf": (to_udf, False), "protect": (protect, False), "unlock": (unlock, False), "compare": (compare_tool, False),
}


@app.post("/api/edit/<sid>/tool/<name>")
def edit_tool(sid, name):
    """Sol menüdeki bir aracı, yeni dosya seçtirmeden açık belgeye uygular."""
    if name not in DOC_TOOLS:
        raise ToolError("Bu araç açık belgeyle kullanılamaz.")
    view, in_place = DOC_TOOLS[name]
    s = store.get(sid)
    job = UPLOADS / uuid.uuid4().hex[:12]
    job.mkdir()
    with s.lock:
        rev = s.path
        g.doc_input = job / f"000_{safe_name(Path(s.name).stem)}.pdf"
        shutil.copy(rev, g.doc_input)
    data = view().get_json()
    if not in_place:
        return jsonify(data)
    res = data["files"][0]
    if res.get("error"):
        raise ToolError(res["error"])
    with s.lock:
        if s.path != rev:
            raise ToolError("Belge bu sırada değişti; işlemi yeniden deneyin.")
        if res.get("changed", True):
            s.commit_file(output_path(res["id"]))
        extra = {k: res[k] for k in ("note", "before", "after", "changed") if k in res}
        return jsonify(s.info() | extra)


@app.post("/api/edit/<sid>/apply-output")
def edit_apply_output(sid):
    """Pencerede hazırlanan sonuç (Sıkıştır) açık belgenin yeni sürümü olur; Geri Al ile geri alınır."""
    data = request.get_json(silent=True) or {}
    s = store.get(sid)
    with s.lock:
        if data.get("rev") and Path(s.path).name != data["rev"]:
            raise ToolError("Belge bu sırada değişti; pencereyi kapatıp yeniden deneyin.")
        s.commit_file(output_path(data.get("out")))
        return jsonify(s.info())


@app.post("/api/share")
def share_file():
    """Paylaşılacak dosyanın diskteki yeri: araç çıktısı, kaydedilmiş belge ya da belgenin ekrandaki hâli."""
    data = request.get_json(silent=True) or {}
    if data.get("out_id"):
        return jsonify(path=str(output_path(data["out_id"])))
    s = store.get(data.get("sid") or "")
    with s.lock:
        src = Path(s.source) if s.source else None
        if src and src.suffix.lower() == ".pdf" and src.exists() and s.path == s.saved:
            return jsonify(path=str(src))   # değişiklik yok: dosyanın kendisi
        target = SHARES / uuid.uuid4().hex[:12] / safe_name(Path(s.name).stem + ".pdf")
        target.parent.mkdir()
        if s.sig_intact:   # e-imza korunsun
            shutil.copy(s.path, target)
            return jsonify(path=str(target))
        doc = s.open()
        tools.finalize(doc)
        doc.save(target, garbage=3, deflate=True)
        doc.close()
    return jsonify(path=str(target))


# Windows başlatıcısı: uygulama penceresi açıkken ikinci kez başlatılırsa (ya da kısayola PDF sürüklenirse)
# yeni pencere açılmaz; istek bu çağrıyla açık pencereye iletilir. Pencere sahibi kendini buraya bağlar.
HOST_OPEN = None


@app.post("/api/host/open")
def host_open():
    if HOST_OPEN is None:
        return jsonify(ok=False), 404
    paths = [p for p in (request.get_json(silent=True) or {}).get("paths", []) if isinstance(p, str)]
    return jsonify(ok=bool(HOST_OPEN(paths)))


@app.post("/api/shutdown")
def shutdown():
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return jsonify(ok=True)


# ------------------------------------------------------------------ bakım

def clean_temp(max_age):
    """Yüklenen dosyaların, araç çıktılarının ve paylaşım kopyalarının max_age saniyeden eskileri silinir."""
    cutoff = time.time() - max_age
    for root in (UPLOADS, OUTPUTS, SHARES):
        for d in root.iterdir():
            try:
                if d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink()
            except OSError:
                pass


def janitor():
    last = time.time()
    while True:
        if time.time() - last > 3 * 1800:   # beklenenden çok geç uyandık: bilgisayar uykudaydı
            store.touch_all()
        last = time.time()
        clean_temp(6 * 3600)
        store.cleanup()
        store.scan()
        yedekler.prune_backups()
        time.sleep(1800)


def watch_parent(pid):
    """Yerel uygulama penceresi kapanırsa (çökse bile) sunucuyu da kapat."""
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            os._exit(0)
        time.sleep(2)


# Windows başlatıcısı: pencere (Edge) kapanıp sayfa bir süre ses vermezse sunucu kendini kapatır
HEARTBEAT = os.environ.get("PDFSTUDYO_HEARTBEAT") == "1"
_last_ping = [time.time()]


@app.post("/api/ping")
def ping():
    _last_ping[0] = time.time()
    return jsonify(ok=True)


def watch_heartbeat(timeout=180):
    while True:
        time.sleep(15)
        if time.time() - _last_ping[0] > timeout:
            os._exit(0)


class PrivateLogHandler(WSGIRequestHandler):
    """İstek günlüğüne adresin soru işaretinden sonrası yazılmaz: uygulama anahtarı ve açılan
    belgelerin yolları (kimin hangi dosyayla çalıştığı) günlük dosyasında görünmesin."""

    def log_request(self, code="-", size="-"):
        path = self.path
        if "?" in path:
            self.path = path.split("?", 1)[0] + "?…"
        try:
            super().log_request(code, size)
        finally:
            self.path = path


def serve():
    """Sunucuyu çalıştırır (Mac uygulaması ve Windows başlatıcısı bunu kullanır)."""
    parent = os.environ.get("PDFSTUDYO_PARENT_PID")
    if parent and parent.isdigit() and not IS_WIN:   # Windows'ta os.kill(pid, 0) sinyal gönderir
        threading.Thread(target=watch_parent, args=(int(parent),), daemon=True).start()
    if HEARTBEAT:
        threading.Thread(target=watch_heartbeat, daemon=True).start()
    threading.Thread(target=janitor, daemon=True).start()
    threading.Thread(target=fonts.load_index, args=(DATA,), daemon=True).start()
    threading.Thread(target=engine_status, daemon=True).start()   # ana sayfa açılırken hazır olsun
    print(f"Koç PDF Pro çalışıyor: http://127.0.0.1:{PORT}/")
    app.run(host="127.0.0.1", port=PORT, threaded=True, debug=False, request_handler=PrivateLogHandler)


def main():
    url = f"http://127.0.0.1:{PORT}/"
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    serve()


if __name__ == "__main__":
    main()
