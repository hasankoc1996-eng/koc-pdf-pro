"""Koç PDF Pro — Windows başlatıcısı.

pythonw.exe ile (konsol penceresi açmadan) çalışır:
  1. Uygulama motorunu (app.py) başlatır; zaten çalışıyorsa yeniden başlatmaz.
  2. Arayüzü uygulamanın kendi penceresinde açar: pywebview + Windows'un yerleşik WebView2 bileşeni
     (Edge tarayıcısı açılmaz). Görev çubuğunda Koç PDF Pro simgesi, sekmeler (static/shell.js),
     Windows'un kendi Kaydet / Aç pencereleri, kapatırken kaydedilmemiş değişiklik uyarısı.
  3. Bu pencere açılamazsa (WebView2 yoksa ya da bir hata olursa) eski yönteme döner:
     Microsoft Edge'in uygulama penceresi. Sebep günlük dosyasına yazılır.
  4. Pencere kapanınca motoru da kapatır.
"""
import base64
import ctypes
import faulthandler
import http.client
import json
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "KocPDFPro"
DATA.mkdir(parents=True, exist_ok=True)

# pythonw.exe'de konsol yok: çıktıları günlük dosyasına yaz
_log = open(DATA / "log.txt", "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = _log
faulthandler.enable(file=_log, all_threads=True)   # yerel çöküşlerde de günlüğe iz düşsün
logging.basicConfig(stream=_log, level=logging.WARNING, format="%(asctime)s %(name)s: %(message)s")

PORT = int(os.environ.get("PDFSTUDYO_PORT", "5055"))
URL = f"http://127.0.0.1:{PORT}/"
APP_ID = "HasanKoc.KocPDFPro"          # görev çubuğunda kendi simgesiyle görünsün (pythonw'nin değil)
START_LOCK = "Local\\KocPDFPro.Baslat"   # aynı anda iki kez başlatılırsa sırayla çalışsınlar
SETTINGS = DATA / "pencere.json"       # en son kaydedilen klasör, görünüm (gündüz / gece), arayüz büyüklüğü
SPLASH_MIN = 1.45                      # açılış ekranı kaybolması dahil en az 2 saniye (Mac'teki gibi)
SPLASH_FADE = 0.55


T0 = time.time()   # başlatıcının açıldığı an: günlükte her adımın kaçıncı saniyede olduğu yazar


def log(text):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), f"[+{time.time() - T0:.1f} sn]", text, flush=True)


def message(text):
    ctypes.windll.user32.MessageBoxW(None, text, "Koç PDF Pro", 0x10)


def local_request(method, path, body=None, timeout=1):
    """Motorla doğrudan konuşur. urllib kullanılmaz: Windows'ta sistemin (kurumsal) proxy ayarını okuyup
    127.0.0.1 isteklerini bile proxy sunucusuna gönderebiliyor; o zaman motor açıkken bile ulaşılamıyor ve
    pencere açılış ekranında kalıyordu. http.client proxy kullanmaz."""
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def probe():
    """Motor yanıt veriyor mu? (yanıt veriyor, değilse sebebi)"""
    try:
        status, _ = local_request("GET", "/api/status?yoklama=1")   # araç bilgisini beklemeden
        return status == 200, f"HTTP {status}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def alive():
    return probe()[0]


def app_key():
    """Kurulum paketinde motorun her açılışta ürettiği uygulama anahtarı (bkz. app.py, APP_KEY)."""
    try:
        return (DATA / "oturum").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def entry_url(path="", params=()):
    """Pencerenin ilk açtığı adres: motor yalnızca anahtarı ileten pencereye cevap verir (anahtar çereze yazılır)."""
    key = app_key()
    params = ([("anahtar", key)] if key else []) + list(params)
    return URL + path + ("?" + urllib.parse.urlencode(params) if params else "")


def find_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            exe = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if exe.exists():
                return str(exe)
    return None


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_setting(key, value):
    data = load_settings()
    data[key] = value
    try:
        SETTINGS.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def windows_dark():
    """Windows'ta uygulamalar için koyu mod seçili mi?"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


def splash_html(theme):
    """Açılış ekranı (Mac uygulamasındakinin aynısı): logo belirir, motor hazırlanırken çizgi dolar."""
    try:
        logo = "data:image/png;base64," + base64.b64encode((HERE / "app" / "static" / "logo.png").read_bytes()).decode()
    except OSError:
        logo = ""
    return f"""<!doctype html><html data-theme="{theme}"><head><meta charset="utf-8"><style>
:root {{ color-scheme: light dark; --bg: #f4f5f7; --text: #1c2024; --muted: #6b7280; --track: rgba(0,0,0,.08); --accent: #d6453d; }}
:root[data-theme="dark"] {{ --bg: #15171a; --text: #e8eaed; --muted: #9aa1aa; --track: rgba(255,255,255,.1); --accent: #ef5a50; }}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{ --bg: #15171a; --text: #e8eaed; --muted: #9aa1aa; --track: rgba(255,255,255,.1); --accent: #ef5a50; }}
}}
html, body {{ margin: 0; height: 100%; }}
body {{ background: var(--bg); color: var(--text); display: grid; place-items: center; overflow: hidden;
  font: 15px "Segoe UI", system-ui, sans-serif; user-select: none; cursor: default; }}
.wrap {{ display: flex; flex-direction: column; align-items: center; margin-top: -24px; transition: opacity .35s ease, transform .35s ease; }}
.logo {{ width: 128px; height: 128px; filter: drop-shadow(0 14px 22px rgba(214,69,61,.30)) drop-shadow(0 2px 4px rgba(0,0,0,.14));
  animation: pop .75s cubic-bezier(.2,.9,.25,1.2) both; }}
.logo[src=""] {{ display: none; }}
h1 {{ margin: 20px 0 0; font-size: 26px; font-weight: 700; letter-spacing: -.01em; animation: rise .5s .22s ease-out both; }}
.bar {{ width: 180px; height: 3px; border-radius: 3px; background: var(--track); margin-top: 18px; overflow: hidden; animation: rise .5s .32s ease-out both; }}
.bar i {{ display: block; height: 100%; width: 0; background: var(--accent); border-radius: 3px;
  animation: load {SPLASH_MIN - 0.4:.2f}s .4s cubic-bezier(.3,.4,.4,1) forwards; }}
.copy {{ position: fixed; left: 0; right: 0; bottom: 22px; text-align: center; font-size: 11.5px; color: var(--muted);
  animation: fade .6s .5s both; transition: opacity .3s; }}
body.out .wrap {{ opacity: 0; transform: scale(.97); }}
body.out .copy {{ opacity: 0; }}
@keyframes pop {{ from {{ opacity: 0; transform: scale(.82); }} to {{ opacity: 1; transform: scale(1); }} }}
@keyframes rise {{ from {{ opacity: 0; transform: translateY(6px); }} to {{ opacity: 1; transform: none; }} }}
@keyframes fade {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
@keyframes load {{ to {{ width: 85%; }} }}
@media (prefers-reduced-motion: reduce) {{ * {{ animation-duration: 1ms !important; animation-delay: 0s !important; }} }}
</style></head><body>
<div class="wrap"><img class="logo" src="{logo}" alt=""><h1>Koç PDF Pro</h1><div class="bar"><i></i></div></div>
<div class="copy">© 2026 Hasan Koç · Açık kaynak (GNU AGPL-3.0)</div>
<script>
function finish() {{
  const bar = document.querySelector('.bar i');
  const width = getComputedStyle(bar).width;
  bar.style.animation = 'none';
  bar.style.width = width;
  bar.offsetWidth;
  bar.style.transition = 'width .2s ease-out';
  bar.style.width = '100%';
  setTimeout(() => document.body.classList.add('out'), 200);
}}
</script></body></html>"""


class Starter:
    """Motoru başlatır. Başlatma kilidini motor yanıt verince bırakır: aynı anda yapılan ikinci açılış
    beklerken motor hazırlanır, sonra ikinci açılış açık pencereye yönelir (semaphore: her iş parçacığı bırakabilir).
    Semaphore'u alan süreç kapanınca kilit kendiliğinden boşalmaz: kilidi alan her yol bırakmalı (bkz. main)."""

    def __init__(self):
        self.lock = ctypes.windll.kernel32.CreateSemaphoreW(None, 1, 1, START_LOCK)
        self.released = True        # kilit alınınca False (alınmamış kilit bırakılmaz)
        self.server = None
        self.started_here = False   # motoru bu açılış yükleyecek (açık bir motor yoktu)
        self.launched = False       # motorun yüklenmesi başladı mı
        self.failed = None          # motor yüklenemediyse hatanın ayrıntısı
        self.host_open = None       # pencere açılınca: sonraki başlatmaların gönderdiği belgeleri açar
        self.mutex = threading.Lock()

    def acquire(self, give_up, timeout=60):
        """Başlatma sırasını bekler. Beklerken yarım saniyede bir give_up() sorulur: True dönerse (belgeler açık
        pencereye devredildi) sıra alınmadan False döner. Böylece kilit bir sebeple boşalmamış olsa da açık pencere
        varken beklenmez. Sıra gelirse ya da süre dolarsa True; süre dolunca da alınmış sayılır ki bırakılınca
        takılı kalmış kilit düzelsin."""
        end = time.time() + timeout
        while ctypes.windll.kernel32.WaitForSingleObject(self.lock, 500) != 0:   # 0: sıra geldi
            if give_up():
                return False
            if time.time() >= end:
                log(f"Başlatma sırası {timeout} saniyede gelmedi; yine de devam ediliyor.")
                break
        self.released = False
        return True

    def release(self):
        if not self.released:
            self.released = True
            ctypes.windll.kernel32.ReleaseSemaphore(self.lock, 1, None)

    def start(self):
        """Motoru bu açılış yükleyecekse yüklemeyi bir kez başlatır (pencere göründükten sonra; bkz. native_window)."""
        if self.started_here and not self.launched:
            self.launched = True
            start_server(self)

    def connect(self, host_open):
        """Pencere hazır: bundan sonraki başlatmaların gönderdiği belgeler bu pencerede açılsın. Motor henüz
        yükleniyorsa yüklenince bağlanır (start_server)."""
        with self.mutex:
            self.host_open = host_open
            if self.server is not None:
                self.server.HOST_OPEN = host_open

    def wait_ready(self, timeout=40):
        reason = None
        for i in range(int(timeout / 0.25)):
            if self.failed:
                self.release()
                return False
            ok, reason = probe()
            if ok:
                self.release()
                return True
            if i == 20:   # ~5 saniyedir yanıt yok: sebebi günlüğe yaz
                log(f"Motor henüz yanıt vermiyor: {reason}")
            time.sleep(0.25)
        log(f"Motor yanıt vermedi: {reason}")
        self.release()
        return False


def start_server(starter):
    """Motoru arka planda yükleyip başlatır. Yüklemek (Flask, PDF kitaplığı…) ilk açılışta ve virüs taraması
    sırasında birkaç saniye sürebilir; bu arada pencere açılış ekranıyla açık durur."""
    os.environ["PDFSTUDYO_HEARTBEAT"] = "1"   # pencere kapanınca motor kendini kapatsın
    sys.path.insert(0, str(HERE / "app"))

    def run():
        try:
            import app as server
        except BaseException:   # eksik dosya, bozuk kurulum
            starter.failed = traceback.format_exc()
            log("Motor yüklenemedi:\n" + starter.failed)
            return
        with starter.mutex:
            starter.server = server
            if starter.host_open is not None:
                server.HOST_OPEN = starter.host_open
        log("Motor yüklendi.")
        server.serve()

    threading.Thread(target=run, daemon=True).start()


def hand_over(paths):
    """Uygulama penceresi zaten açıksa: onu öne getir, PDF'leri orada aç. Başarılıysa True."""
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # açık pencere öne gelebilsin
    except Exception:
        pass
    try:
        status, data = local_request("POST", "/api/host/open", json.dumps({"paths": paths}).encode(), timeout=5)
        return status == 200 and bool(json.loads(data or b"{}").get("ok"))
    except Exception:
        return False


# ------------------------------------------------------------------ uygulama penceresi

# --- Sorun bildir: rapor dosyası ekli e-posta
# mailto bağlantısı ek taşıyamaz. Varsayılan e-posta programı klasik Outlook ise Outlook'un kendisiyle (COM; Office
# 32 ya da 64 bit olsun çalışır), Thunderbird gibi Basit MAPI destekleyen bir programsa MAPI ile ekli ileti açılır.
# İkisi de olmazsa sayfa e-postayı mailto ile açar, rapor dosyasını klasörde gösterir (kullanıcı ekler).

def _reg_value(root, path, name):
    import winreg
    try:
        with winreg.OpenKey(root, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def default_mail_client():
    """Windows'un varsayılan e-posta programı ve Basit MAPI desteği: ("Microsoft Outlook", True) gibi."""
    import winreg
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        name = _reg_value(root, r"Software\Clients\Mail", "")
        if name:
            mapi = any(_reg_value(r, rf"Software\Clients\Mail\{name}", v)
                       for r in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER) for v in ("DLLPath", "DLLPathEx"))
            return name, mapi
    return None, False


def run_waiting(fn, wait):
    """fn ayrı iş parçacığında çalışır (ileti penceresi kullanıcı kapatana dek bekletebilir). Süre dolarsa
    pencere açık kabul edilir (True); hata olursa False."""
    out = {}

    def target():
        try:
            out["ok"] = bool(fn())
        except Exception:
            log("E-posta açılamadı:\n" + traceback.format_exc())
            out["ok"] = False
    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(wait)
    return out.get("ok", True)


def outlook_mail(to, subject, body, path):
    import comtypes
    import comtypes.client
    comtypes.CoInitialize()
    outlook = mail = None
    try:
        outlook = comtypes.client.CreateObject("Outlook.Application", dynamic=True)
        mail = outlook.CreateItem(0)   # 0: e-posta iletisi
        mail.To, mail.Subject, mail.Body = to, subject, body
        mail.Attachments.Add(path)
        mail.Display(False)            # pencereyi açar, göndermez
        return True
    finally:
        outlook = mail = None
        comtypes.CoUninitialize()


def copy_file_to_clipboard(path):
    """Dosyayı panoya Gezgin'in "Kopyala"sı gibi koyar (CF_HDROP): Ctrl+V ile klasöre, e-postaya, web sayfasına."""
    import ctypes.wintypes as wt

    class DROPFILES(ctypes.Structure):
        _fields_ = [("pFiles", wt.DWORD), ("pt", wt.POINT), ("fNC", wt.BOOL), ("fWide", wt.BOOL)]
    data = bytes(DROPFILES(ctypes.sizeof(DROPFILES), wt.POINT(0, 0), 0, 1)) + (os.path.abspath(path) + "\0\0").encode("utf-16-le")
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.GlobalAlloc.restype = k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k32.GlobalLock.argtypes = k32.GlobalUnlock.argtypes = k32.GlobalFree.argtypes = [ctypes.c_void_p]
    u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    u32.SetClipboardData.restype = ctypes.c_void_p
    handle = k32.GlobalAlloc(0x0002, len(data))   # GMEM_MOVEABLE
    ctypes.memmove(k32.GlobalLock(handle), data, len(data))
    k32.GlobalUnlock(handle)
    if not u32.OpenClipboard(None):
        k32.GlobalFree(handle)
        return False
    try:
        u32.EmptyClipboard()
        if not u32.SetClipboardData(15, handle):   # CF_HDROP; başarılıysa bellek artık panonun
            k32.GlobalFree(handle)
            return False
        return True
    finally:
        u32.CloseClipboard()


class _MapiRecip(ctypes.Structure):
    _fields_ = [("ulReserved", ctypes.c_ulong), ("ulRecipClass", ctypes.c_ulong), ("lpszName", ctypes.c_wchar_p),
                ("lpszAddress", ctypes.c_wchar_p), ("ulEIDSize", ctypes.c_ulong), ("lpEntryID", ctypes.c_void_p)]


class _MapiFile(ctypes.Structure):
    _fields_ = [("ulReserved", ctypes.c_ulong), ("flFlags", ctypes.c_ulong), ("nPosition", ctypes.c_ulong),
                ("lpszPathName", ctypes.c_wchar_p), ("lpszFileName", ctypes.c_wchar_p), ("lpFileType", ctypes.c_void_p)]


class _MapiMessage(ctypes.Structure):
    _fields_ = [("ulReserved", ctypes.c_ulong), ("lpszSubject", ctypes.c_wchar_p), ("lpszNoteText", ctypes.c_wchar_p),
                ("lpszMessageType", ctypes.c_wchar_p), ("lpszDateReceived", ctypes.c_wchar_p),
                ("lpszConversationID", ctypes.c_wchar_p), ("flFlags", ctypes.c_ulong),
                ("lpOriginator", ctypes.POINTER(_MapiRecip)), ("nRecipCount", ctypes.c_ulong),
                ("lpRecips", ctypes.POINTER(_MapiRecip)), ("nFileCount", ctypes.c_ulong),
                ("lpFiles", ctypes.POINTER(_MapiFile))]


def mapi_mail(to, subject, body, path):
    recip = _MapiRecip(0, 1, to, "SMTP:" + to, 0, None)                      # 1: Kime
    attach = _MapiFile(0, 0, 0xFFFFFFFF, path, os.path.basename(path), None)  # konum: metnin sonu
    msg = _MapiMessage(0, subject, body, None, None, None, 0, None, 1, ctypes.pointer(recip), 1, ctypes.pointer(attach))
    send = ctypes.WinDLL("mapi32.dll").MAPISendMailW
    send.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.POINTER(_MapiMessage), ctypes.c_ulong, ctypes.c_ulong]
    send.restype = ctypes.c_ulong
    result = send(0, 0, ctypes.byref(msg), 0x1 | 0x8, 0)   # MAPI_LOGON_UI | MAPI_DIALOG: ileti penceresi açılır
    if result not in (0, 1):                                 # 0: gönderildi, 1: kullanıcı vazgeçti
        raise OSError(f"MAPISendMailW hata kodu {result}")
    return True


class Host:
    """Pencere sahibi: sayfadaki uygulamanın Windows'a özgü istekleri (window.pywebview.api.message).
    Mac uygulamasındaki Swift kabuğun karşılığı. Alt çizgiyle başlayanlar sayfaya açılmaz."""

    def __init__(self):
        self._window = None
        self._unsaved = 0          # kaydedilmemiş sekme sayısı (sekme kabuğu bildirir)
        self._quitting = False
        self._last_dir = self._load_dir()
        self._shell_ready = False  # açılış ekranı bitip sekme kabuğu yüklendi mi
        self._pending = []         # bu arada gelen PDF'ler (ikinci açılış, "Birlikte aç")
        self._user_closed = False  # pencereyi kullanıcı kapattı (yoksa uygulama yüklenemeden kapanmış demektir)
        self._gave_up = False      # motor yanıt vermedi, kullanıcıya söylendi

    def message(self, msg):
        try:
            return self._handle(msg if isinstance(msg, dict) else {})
        except Exception:
            log("İstek işlenemedi: " + json.dumps(msg, ensure_ascii=False)[:300] + "\n" + traceback.format_exc())
            return None

    # --- en son kullanılan klasör
    def _load_dir(self):
        try:
            return load_settings().get("lastSaveDirectory")
        except Exception:
            return None

    def _remember(self, folder):
        if folder and os.path.isdir(folder):
            self._last_dir = folder
            save_setting("lastSaveDirectory", folder)

    def _dir(self, preferred):
        desktop = str(Path.home() / "Desktop")
        for p in (preferred, self._last_dir, desktop):
            if p and os.path.isdir(p):
                return p
        return ""

    def _ui(self, fn):
        """Windows dosya pencereleri arayüz iş parçacığında açılmalı; sayfadan gelen istekler ayrı iş parçacığında gelir."""
        form = getattr(self._window, "native", None)
        try:
            if form is not None and form.InvokeRequired:
                from System import Func, Object
                box = {}

                def run():
                    box["value"] = fn()
                    return None
                form.Invoke(Func[Object](run))
                return box.get("value")
        except Exception:
            log("Arayüz iş parçacığına aktarılamadı, doğrudan deneniyor:\n" + traceback.format_exc())
        return fn()

    def _apply_zoom(self, zoom):
        """Arayüz büyüklüğü: WebView2'nin yakınlığı. Bütün sekmeler (kabuğun içindeki bölmeler) birlikte büyür."""
        def run():
            self._window.native.browser.webview.ZoomFactor = float(zoom)
        try:
            self._ui(run)
        except Exception:
            log("Arayüz büyüklüğü uygulanamadı:\n" + traceback.format_exc())

    @staticmethod
    def _first(result):
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result

    def _handle(self, msg):
        import webview
        action = msg.get("action")
        w = self._window

        if action == "savePanel":           # Farklı Kaydet / araç çıktısını kaydet
            types = [t for t in (msg.get("types") or []) if isinstance(t, str) and t.isalnum()]
            file_types = tuple(f"{t.upper()} dosyası (*.{t})" for t in types)
            path = self._first(self._ui(lambda: w.create_file_dialog(
                webview.FileDialog.SAVE, directory=self._dir(msg.get("directory")),
                save_filename=msg.get("name") or "belge.pdf", file_types=file_types)))
            if path:
                if types and not path.lower().endswith("." + types[0].lower()):
                    path += "." + types[0]
                self._remember(os.path.dirname(path))
            return path

        if action == "folderPanel":         # birden çok çıktıyı bir klasöre kaydet
            path = self._first(self._ui(lambda: w.create_file_dialog(
                webview.FileDialog.FOLDER, directory=self._dir(msg.get("directory")))))
            self._remember(path)
            return path

        if action == "openPanel":           # PDF / UDF seç
            exts = [p.strip().lstrip(".") for p in (msg.get("accept") or "").split(",") if p.strip().startswith(".")]
            file_types = (f"Belgeler ({';'.join('*.' + e for e in exts)})",) if exts else ()
            result = self._ui(lambda: w.create_file_dialog(
                webview.FileDialog.OPEN, directory=self._dir(msg.get("directory")),
                allow_multiple=bool(msg.get("multiple")), file_types=file_types))
            return list(result) if result else None

        if action == "reveal":              # Klasörde göster
            path = msg.get("path")
            if path and os.path.exists(path):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            return True

        if action == "copyFile":            # PDF'i dosya olarak panoya: Gezgin'e, e-postaya, UYAP'a Ctrl+V
            path = msg.get("path") or ""
            return bool(path) and os.path.isfile(path) and copy_file_to_clipboard(path)

        if action == "mail":                # Sorun bildir: rapor ekli ileti; olmazsa mailto (sayfa dosyayı gösterir)
            path = msg.get("path") or ""
            attached = False
            if path and os.path.isfile(path) and Path(path).resolve().parent == (DATA / "raporlar").resolve():
                ctypes.windll.user32.AllowSetForegroundWindow(-1)   # açılan ileti penceresi öne gelebilsin
                args = (msg.get("to") or "", msg.get("subject") or "", msg.get("body") or "", path)
                client, mapi = default_mail_client()
                if client and "outlook" in client.lower():
                    attached = run_waiting(lambda: outlook_mail(*args), 25)
                elif mapi:
                    attached = run_waiting(lambda: mapi_mail(*args), 4)
                log(f"Sorun raporu: e-posta programı {client or 'yok'}, rapor {'ekli açıldı' if attached else 'eklenemedi'}")
            if attached:
                return "attached"
            url = msg.get("url") or ""
            if url.startswith("mailto:"):
                os.startfile(url)
            return "manual"

        if action == "uiZoom":              # Ayarlar › Görünüm › Arayüz büyüklüğü
            zoom = msg.get("value")
            if isinstance(zoom, (int, float)) and not isinstance(zoom, bool) and 0.6 <= zoom <= 2:
                save_setting("uiZoom", round(float(zoom), 2))
                self._apply_zoom(zoom)
            return True

        if action == "getUiZoom":
            return load_settings().get("uiZoom", 1.0)

        if action == "defaultApps":         # Ayarlar › Belgeler: Windows'un varsayılan uygulamalar ayarı
            os.startfile("ms-settings:defaultapps")
            return True

        if action == "openUrl":             # geliştiricinin sayfası: varsayılan tarayıcıda (uygulama penceresinde değil)
            url = msg.get("url") or ""
            if url.startswith("https://"):
                webbrowser.open(url)
            return True

        if action == "print":               # PDF'i ayrı pencerede aç (yazdır düğmesi ya da Ctrl+P)
            url = msg.get("url") or ""
            if url.startswith(URL.rstrip("/")):
                webview.create_window(f"Yazdır — {msg.get('name') or 'PDF'}", url, width=900, height=1000)
            return True

        if action == "confirm":
            return self._ui(lambda: w.create_confirmation_dialog(msg.get("title") or "Koç PDF Pro", msg.get("message") or ""))

        if action == "title":
            w.set_title(msg.get("title") or "Koç PDF Pro")
            return True

        if action == "theme":               # açılış ekranı bir sonraki açılışta bu görünümle gelsin
            if msg.get("value") in ("auto", "light", "dark"):
                save_setting("theme", msg["value"])
            return True

        if action == "unsaved":
            self._unsaved = int(msg.get("count") or 0)
            return True

        if action == "quit":                # son sekme kapandı
            self._quitting = True
            w.destroy()
            return True
        return None

    def _open_external(self, paths):
        """İkinci başlatma: pencereyi öne getir, gelen PDF'leri yeni sekmede aç (sunucu iş parçacığından çağrılır)."""
        w = self._window
        if w is None:
            return False
        if not self._shell_ready:     # açılış ekranı sürüyor: uygulama yüklenince açılır
            self._pending += paths
            return True
        try:
            w.evaluate_js(f"window.PDFSTUDYO_SHELL && PDFSTUDYO_SHELL.openExternal({json.dumps(paths)})")
        except Exception:
            log("Dışarıdan açma isteği iletilemedi:\n" + traceback.format_exc())
            return False
        form = getattr(w, "native", None)

        def front():
            from System.Windows.Forms import FormWindowState
            if form.WindowState == FormWindowState.Minimized:
                form.WindowState = FormWindowState.Normal
            form.Activate()
        try:
            if form is not None:
                self._ui(front)
        except Exception:
            pass
        return True

    def _on_loaded(self):
        """Sekme kabuğu yüklendi: açılış ekranı sırasında gelen PDF'leri aç."""
        try:
            url = self._window.get_current_url() or ""
        except Exception:
            url = ""
        if "/shell" not in url or self._shell_ready:
            return
        self._shell_ready = True
        log("Uygulama yüklendi.")
        zoom = load_settings().get("uiZoom")
        if zoom and zoom != 1:
            self._apply_zoom(zoom)
        if self._pending:
            paths, self._pending = self._pending, []
            self._open_external(paths)

    def _on_closing(self):
        """Pencere kapatılırken: kaydedilmemiş sekme varsa sorar. False dönerse kapanmaz. Sekme kabuğu hazırsa sekmeler
        sırayla öne gelip sayfanın kendi sorusuyla (Kaydet / Farklı Kaydet / Kaydetmeden kapat / Vazgeç) sorulur;
        hepsi tamamsa kabuk "quit" gönderir ve pencere kapanır."""
        if self._quitting or not self._unsaved:
            self._user_closed = True
            return True
        if self._shell_ready:
            threading.Thread(target=lambda: self._window.evaluate_js(
                "window.PDFSTUDYO_SHELL && PDFSTUDYO_SHELL.closeAll()"), daemon=True).start()
            return False
        n = self._unsaved
        text = ("Bir sekmedeki" if n == 1 else f"{n} sekmedeki") + \
            " değişiklikleri henüz kaydetmediniz. Kapatırsanız değişiklikler kaybolur.\n\nYine de kapatılsın mı?"
        self._user_closed = bool(self._window.create_confirmation_dialog("Kaydedilmemiş değişiklikler var", text))
        return self._user_closed


def start_error(starter):
    """Motor çalışmadıysa kullanıcıya gösterilecek ileti."""
    if starter.failed:
        last = starter.failed.strip().splitlines()[-1]
        return f"Koç PDF Pro başlatılamadı:\n\n{last}\n\nAyrıntılar: {DATA / 'log.txt'}"
    return f"Koç PDF Pro motoru yanıt vermedi.\n\nAyrıntılar: {DATA / 'log.txt'}"


def native_window(open_paths, starter):
    """Uygulamanın kendi penceresi; kapanana kadar bekler. Açılamazsa istisna fırlatır.
    Pencere hemen açılış ekranıyla açılır, motor ondan sonra yüklenir; motor hazır olunca sekme kabuğu (uygulama)
    yüklenir."""
    import webview
    from webview.platforms import winforms   # pythonnet ve WebView2 bileşenlerini yükler
    if not getattr(winforms, "is_chromium", False):
        # WebView2 yoksa pywebview eski Internet Explorer motoruna düşer; uygulama orada çalışmaz
        raise RuntimeError("WebView2 bulunamadı (Windows'un 'Microsoft Edge WebView2 Runtime' bileşeni gerekli)")
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    host = Host()
    starter.connect(host._open_external)   # bundan sonraki başlatmalar bu pencereye yönlenir
    (DATA / "webview").mkdir(parents=True, exist_ok=True)   # pywebview'in kendi oluşturması iki açılışta çakışabiliyor
    theme = load_settings().get("theme", "auto")
    dark = theme == "dark" or (theme == "auto" and windows_dark())
    # Ekranı kaplayarak açılır (görev çubuğu görünür kalır); büyütme düğmesiyle 1320×860'a döner
    window = webview.create_window(
        "Koç PDF Pro", html=splash_html(theme), js_api=host,
        width=1320, height=860, min_size=(960, 620), maximized=True, text_select=True, zoomable=False,
        background_color="#15171A" if dark else "#F4F5F7")
    host._window = window
    shown = threading.Event()
    splash = threading.Event()          # açılış ekranı (logo) pencereye çizildi
    window.events.shown += shown.set
    window.events.shown += lambda: log("Pencere göründü.")
    window.events.loaded += splash.set
    window.events.closing += host._on_closing
    window.events.loaded += host._on_loaded
    webview.settings["ALLOW_DOWNLOADS"] = True

    def boot():
        """Pencere açıldı: motoru yükle; motor hazır olana (ve açılış ekranı en az kısa bir süre görünene) kadar bekle.
        Motor açılış ekranı çizildikten sonra yüklenir: pencereyle aynı anda yüklenince Python ikisini sırayla
        işlediğinden ikisi de geç bitiyordu (Windows denemesinde logo motorla birlikte 7,6. saniyede göründü)."""
        if not shown.wait(20):
            log("Pencere 20 saniyede görünmedi; yine de devam ediliyor.")
        splash.wait(3)
        starter.start()
        t0 = time.time()
        if not starter.wait_ready():
            host._gave_up = True
            message(start_error(starter))
            window.destroy()
            return
        log("Motor hazır; uygulama yükleniyor.")
        rest = SPLASH_MIN - (time.time() - t0)
        if rest > 0:
            time.sleep(rest)
        try:
            window.evaluate_js("window.finish && finish()")
        except Exception:
            pass
        time.sleep(SPLASH_FADE)
        paths, host._pending = open_paths + host._pending, []
        window.load_url(entry_url("shell", [("open", p) for p in paths]))

    try:
        log("Pencere oluşturuluyor.")
        webview.start(boot, gui="edgechromium", private_mode=False, storage_path=str(DATA / "webview"),
                      icon=str(HERE / "KocPDFPro.ico"))
    except Exception:
        if shown.is_set():     # pencere açıldıktan sonraki hatada Edge'e dönme; yalnızca kaydet
            log("Pencere hatası:\n" + traceback.format_exc())
            return
        raise
    log(f"Pencere kapandı (uygulama yüklenmişti: {host._shell_ready}, kullanıcı kapattı: {host._user_closed}).")
    if not host._shell_ready and not host._user_closed and not host._gave_up:
        # Pencere uygulamayı yükleyemeden kendiliğinden kapandı: sessizce çıkma, yedek pencereyi dene
        raise RuntimeError("Uygulama penceresi uygulamayı yükleyemeden kapandı")


def edge_window(started_here):
    """Yedek: Microsoft Edge'in uygulama penceresi (adres çubuğu ve sekme olmadan)."""
    edge = find_edge()
    if edge:
        window = subprocess.Popen([
            edge, f"--app={entry_url()}", f"--user-data-dir={DATA / 'pencere'}",
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate",
            "--window-size=1320,860", "--start-maximized",
        ])
        window.wait()          # pencere kapanana kadar bekle
    else:
        webbrowser.open(entry_url())   # Edge yoksa varsayılan tarayıcıda aç
        if started_here:
            while alive():     # "Uygulamayı kapat" ya da pencere kapanınca motor durana kadar
                time.sleep(2)


def main():
    # Kısayola sürüklenen ya da "Birlikte aç" ile gelen PDF/UDF dosyaları
    open_paths = [a for a in sys.argv[1:] if a.lower().endswith((".pdf", ".udf")) and os.path.isfile(a)]
    try:   # paketin sürümü (make_windows.sh app/_surum.py'ye yazar: SURUM = "1.0.0")
        build = (HERE / "app" / "_surum.py").read_text(encoding="utf-8").split('"')[1]
    except (OSError, IndexError):
        build = "kaynak"
    log(f"Başlatıcı açıldı (sürüm {build}, açılacak belge: {len(open_paths)}).")

    # Aynı anda iki kez başlatılırsa (ör. çift tıklama) sırayla: ikincisi ilkinin açtığı pencereye yönelir.
    # Sıra beklenirken de açık pencere aranır: varsa belgeler hemen ona gider.
    starter = Starter()
    if not starter.acquire(give_up=lambda: alive() and hand_over(open_paths)):
        log("Açık pencereye devredildi.")
        os._exit(0)
    if alive():
        if hand_over(open_paths):
            log("Açık pencereye devredildi.")
            starter.release()      # bırakılmazsa sonraki açılışlar sırayı 60 saniye bekliyordu
            os._exit(0)
        starter.release()          # motor başka bir pencerenin; ona bağlan
    else:
        starter.started_here = True   # motor, açılış ekranı göründükten sonra yüklenir (native_window › boot)

    try:
        native_window(open_paths, starter)
    except Exception:
        log("Uygulama penceresi açılamadı; Edge penceresi kullanılıyor:\n" + traceback.format_exc())
        starter.start()            # pencere görünmeden düştüyse motor henüz yüklenmemiştir
        if not starter.wait_ready():
            message(start_error(starter))
            os._exit(1)
        edge_window(starter.started_here)
    starter.release()              # pencere açılış ekranındayken kapatıldıysa sıra hâlâ bu açılıştadır
    os._exit(0)


if __name__ == "__main__":
    main()
