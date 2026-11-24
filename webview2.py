"""Microsoft Edge WebView2 (Windows).

Koç PDF Pro'nun Windows penceresi Windows'un WebView2 bileşeniyle çalışır. Bileşen eksikse başlatıcı uygulamayı
Microsoft Edge'in uygulama penceresinde açar (yedek yol) ve motora bildirir (PDFSTUDYO_EDGE). O zaman sekme çubuğunda
"WebView2 eksik" rozeti çıkar; Kur, Microsoft'un çevrimdışı (Standalone) kurulum dosyasını bilgisayarın mimarisine
göre indirir, Microsoft imzasını doğrular ve sessizce kurar; bitince uygulama kendi penceresinde yeniden açılabilir.
Küçük "Bootstrapper" kullanılmaz: bir kurum bilgisayarında güvenlik duvarı onun indirme adımını (MicrosoftEdgeUpdate.exe)
engelledi; tam kurulum dosyası orada çalıştı. Kurulum paketine de konmaz (çoğu bilgisayarda WebView2 zaten var)."""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import updater

IS_WIN = sys.platform == "win32"
# Microsoft'un Evergreen Standalone kurulum dosyaları (go.microsoft.com yönlendirmesi, 2026-11 denetlendi)
LINKS = {"x64": 2124701, "x86": 2099617, "arm64": 2099616}
PAGE = "https://developer.microsoft.com/microsoft-edge/webview2/"
CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"   # WebView2 Runtime'ın kaydı
NO_WINDOW = 0x08000000   # CREATE_NO_WINDOW: pythonw'den açılan PowerShell konsol penceresi göstermesin
ASK = ("Bilgi işlemden bu bilgisayara “Microsoft Edge WebView2 Runtime” kurulmasını isteyebilir ya da kurulum "
       "dosyasını aşağıdaki bağlantıdan kendiniz indirip açabilirsiniz.")


def download_url(arch):
    return f"https://go.microsoft.com/fwlink/?linkid={LINKS[arch]}"


def architecture():
    """Windows'un kendi mimarisi (x64 / arm64 / x86); 64 bit Windows'ta 32 bit Python çalışsa da."""
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.IsWow64Process2.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort),
                                             ctypes.POINTER(ctypes.c_ushort))
        process, native = ctypes.c_ushort(), ctypes.c_ushort()
        if kernel32.IsWow64Process2(ctypes.c_void_p(-1), ctypes.byref(process), ctypes.byref(native)):
            return {0x8664: "x64", 0xAA64: "arm64", 0x14C: "x86"}.get(native.value, "x64")
    except Exception:   # Windows değil ya da Windows 10 1709'dan eski
        pass
    name = (os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE") or "").upper()
    return "arm64" if name == "ARM64" else "x86" if name == "X86" else "x64"


def installed():
    """WebView2 kurulu mu? Microsoft'un önerdiği denetim: bilgisayar ya da kullanıcı için kaydında sürüm (pv) var mı."""
    if not IS_WIN:
        return True
    import winreg
    for root, path in ((winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + CLIENT),
                       (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + CLIENT),
                       (winreg.HKEY_CURRENT_USER, "Software\\" + CLIENT)):
        try:
            with winreg.OpenKey(root, path) as key:
                version = str(winreg.QueryValueEx(key, "pv")[0] or "")
        except OSError:
            continue
        if version and version != "0.0.0.0":
            return True
    return False


def _powershell(script, path, timeout, **kw):
    """PowerShell komutu; dosya yolu ortam değişkeniyle verilir (tırnak ve özel karakter sorunu olmasın)."""
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                          env={**os.environ, "KPP_DOSYA": str(path)}, timeout=timeout, creationflags=NO_WINDOW, **kw)


def microsoft_signed(path):
    """Dosya geçerli bir Microsoft Corporation imzası taşıyor mu (Windows'un Authenticode denetimi)."""
    r = _powershell("$s = Get-AuthenticodeSignature -LiteralPath $env:KPP_DOSYA; "
                    "[Console]::Out.Write(('{0}|{1}' -f $s.Status, $s.SignerCertificate.Subject))",
                    path, 180, capture_output=True, text=True)
    status, _, subject = r.stdout.strip().partition("|")
    return status == "Valid" and "O=Microsoft Corporation" in subject


def run_installer(path):
    """Kurulum dosyasını sessizce çalıştırır, çıkış kodunu döndürür. Yönetici izni isterse Windows'un izin penceresi
    çıkar (kullanıcı reddederse kod 0 olmaz)."""
    try:
        return subprocess.run([str(path), "/silent", "/install"], timeout=1200, creationflags=NO_WINDOW).returncode
    except OSError as e:
        if getattr(e, "winerror", None) != 740:   # ERROR_ELEVATION_REQUIRED
            raise
    return _powershell("$p = Start-Process -FilePath $env:KPP_DOSYA -ArgumentList '/silent','/install' -Verb RunAs "
                       "-Wait -PassThru; exit $p.ExitCode", path, 1200).returncode


class Installer:
    """Arka planda indir → doğrula → kur. İlerleme `state` ile izlenir:
    downloading (received, total) → verifying → installing → done, ya da error (error, manual: elle indirme adresi)."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.lock = threading.Lock()
        self.state = {"status": "idle"}
        # denemelerde değiştirilir
        self.open, self.verify, self.run, self.installed = updater._open, microsoft_signed, run_installer, installed

    def start(self):
        with self.lock:
            if self.state["status"] in ("downloading", "verifying", "installing", "done"):
                return self.state
            arch = architecture()
            self.state = {"status": "downloading", "received": 0, "total": 0, "manual": download_url(arch)}
        threading.Thread(target=self._work, args=(arch,), daemon=True).start()
        return self.state

    def _fail(self, text):
        self.state = {"status": "error", "error": f"{text} {ASK}", "manual": self.state.get("manual"), "page": PAGE}

    def _work(self, arch):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"MicrosoftEdgeWebView2RuntimeInstaller{arch.upper()}.exe"
        part = path.with_name(path.name + ".part")
        try:
            self._download(download_url(arch), part)
            part.replace(path)
        except Exception:
            part.unlink(missing_ok=True)
            return self._fail("WebView2 indirilemedi: Microsoft'un indirme sunucusuna ulaşılamadı "
                              "(kurum ağında engellenmiş olabilir).")
        self.state = {**self.state, "status": "verifying"}
        try:
            signed = self.verify(path)
        except Exception:
            signed = False
        if not signed:
            path.unlink(missing_ok=True)
            return self._fail("İndirilen dosyanın Microsoft imzası doğrulanamadı; dosya kurulmadı.")
        self.state = {**self.state, "status": "installing"}
        try:
            code = self.run(path)
        except Exception as e:
            code = f"{type(e).__name__}: {e}"
        path.unlink(missing_ok=True)   # ~200 MB yer kaplamasın
        if not self.installed():
            return self._fail(f"WebView2 kurulamadı (çıkış kodu {code}). Bu bilgisayarda program kurma izni "
                              "kısıtlı olabilir.")
        self.state = {"status": "done"}

    def _download(self, url, part):
        """Önce Python ile; olmazsa (ör. kurumun otomatik vekil sunucu ayarını Python okuyamaz) PowerShell ile.
        PowerShell'de toplam boyut bilinmez, inen miktar dosyadan okunur."""
        try:
            with self.open(url, 60) as r, open(part, "wb") as out:
                self.state["total"] = int(r.headers.get("Content-Length") or 0)
                while chunk := r.read(1 << 16):
                    out.write(chunk)
                    self.state["received"] += len(chunk)
            return
        except Exception:
            if not IS_WIN:
                raise
        part.unlink(missing_ok=True)
        self.state.update(received=0, total=0)
        script = ("$ProgressPreference = 'SilentlyContinue'; "
                  "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
                  "[Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials; "
                  f"Invoke-WebRequest -UseBasicParsing -Uri '{url}' -OutFile $env:KPP_DOSYA")
        proc = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-Command", script], env={**os.environ, "KPP_DOSYA": str(part)},
                                creationflags=NO_WINDOW)
        end = time.time() + 3600
        while proc.poll() is None:
            if time.time() > end:
                proc.kill()
                break
            try:
                self.state["received"] = part.stat().st_size
            except OSError:
                pass
            time.sleep(0.5)
        if proc.returncode != 0 or not part.exists() or part.stat().st_size < 1_000_000:
            raise OSError(f"PowerShell indirmesi başarısız ({proc.returncode})")
        self.state["received"] = part.stat().st_size
