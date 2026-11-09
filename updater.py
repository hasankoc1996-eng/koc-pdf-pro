"""Otomatik güncelleme.

Yeni sürümler GitHub'daki kaynak kodu deposunun Sürümler (Releases) bölümünde yayımlanır: her sürümde
surum.json ile Mac (.pkg) ve Windows (Kurulum.exe) kurulum dosyaları (packaging/yayinla.sh). Uygulama
surum.json'u okuyup kendi sürümüyle karşılaştırır; kullanıcı isterse kurulum dosyası indirilir, SHA-256
parmak iziyle doğrulanır ve açılır. Yalnızca kurulum paketinde (sürümü belli) çalışır; proje klasöründen
çalışan geliştirme sürümü denetlenmez."""

import hashlib
import json
import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO = "hasankoc1996-eng/koc-pdf-pro"   # packaging/yayinla.sh REPO ile aynı
# Deneme için PDFSTUDYO_UPDATE_URL ile başka bir adres (ör. file:///…/) verilebilir
BASE_URL = os.environ.get("PDFSTUDYO_UPDATE_URL") or f"https://github.com/{REPO}/releases/latest/download/"
PLATFORM = "windows" if sys.platform == "win32" else "mac"
CHECK_EVERY = 6 * 3600   # başarılı denetimden sonra
RETRY_AFTER = 1800       # ağ yoksa


def parse(version):
    """'1.0.12' → (1, 0, 12); okunamazsa ()."""
    try:
        return tuple(int(x) for x in str(version).split("."))
    except ValueError:
        return ()


def _open(url, timeout):
    context = ssl.create_default_context()
    if PLATFORM == "mac" and Path("/etc/ssl/cert.pem").exists():   # paketteki Python sistemin sertifikalarını bilmez
        context.load_verify_locations("/etc/ssl/cert.pem")
    request = urllib.request.Request(url, headers={"User-Agent": "KocPDFPro"})
    return urllib.request.urlopen(request, timeout=timeout, context=context)


class Updater:
    def __init__(self, current, folder):
        # Geliştirme sürümünde yalnızca deneme adresi verilmişse çalışır (en eski sürüm sayılır)
        self.current = current or ("0.0.0" if os.environ.get("PDFSTUDYO_UPDATE_URL") else None)
        self.folder = folder
        self.lock = threading.Lock()
        self.info, self.checked = None, 0.0
        self.state = {"status": "idle"}

    def check(self, force=False):
        """Yeni sürüm var mı? {available, current, surum, notlar, boyut, state}"""
        if not self.current:
            return {"available": False, "current": None}
        with self.lock:
            ttl = RETRY_AFTER if not self.info or "error" in self.info else CHECK_EVERY
            if force or time.time() - self.checked > ttl:
                try:
                    with _open(BASE_URL + "surum.json", 10) as r:
                        manifest = json.load(r)
                    self.info = {**manifest.get(PLATFORM, {}), "notlar": manifest.get("notlar", "")}
                except Exception as e:   # ağ yok, depo yok…: sessizce sonra yeniden denenir
                    self.info = {"error": str(e)}
                self.checked = time.time()
            info = self.info
        available = bool(info.get("surum")) and parse(info["surum"]) > parse(self.current)
        return {"available": available, "current": self.current, "surum": info.get("surum"),
                "notlar": info.get("notlar"), "boyut": info.get("boyut"), "state": self.state}

    def download(self):
        """Kurulum dosyasını arka planda indirmeye başlar; ilerleme `state` ile izlenir."""
        with self.lock:
            if self.state["status"] in ("downloading", "ready"):
                return self.state
            info = self.info or {}
            if not (info.get("dosya") and info.get("sha256")) or parse(info.get("surum")) <= parse(self.current):
                raise ValueError("Yeni sürüm bilgisi alınamadı; biraz sonra yeniden deneyin.")
            self.state = {"status": "downloading", "received": 0, "total": int(info.get("boyut") or 0)}
        threading.Thread(target=self._fetch, args=(info,), daemon=True).start()
        return self.state

    def _fetch(self, info):
        name = Path(info["dosya"]).name
        self.folder.mkdir(parents=True, exist_ok=True)
        for old in self.folder.iterdir():   # önceki indirmeler
            if old.is_file():
                old.unlink(missing_ok=True)
        part = self.folder / (name + ".part")
        try:
            digest = hashlib.sha256()
            with _open(BASE_URL + name, 30) as r, open(part, "wb") as out:
                self.state["total"] = int(r.headers.get("Content-Length") or 0) or self.state["total"]
                while chunk := r.read(1 << 16):
                    out.write(chunk)
                    digest.update(chunk)
                    self.state["received"] += len(chunk)
            if digest.hexdigest() != str(info["sha256"]).lower():
                raise ValueError("İndirilen dosya doğrulanamadı (eksik ya da değiştirilmiş); yeniden deneyin.")
            path = part.with_name(name)
            part.replace(path)
            self.state = {"status": "ready", "path": str(path), "received": self.state["received"],
                          "total": self.state["total"]}
        except Exception as e:
            part.unlink(missing_ok=True)
            self.state = {"status": "error", "error": str(e) if isinstance(e, ValueError)
                          else "Güncelleme indirilemedi. İnternet bağlantınızı denetleyip yeniden deneyin."}

    def install(self):
        """İndirilen kurulum dosyasını açar (Mac: kurulum sihirbazı, Windows: Kurulum.exe). Uygulama sonra kapanır."""
        if self.state.get("status") != "ready":
            raise ValueError("Önce güncellemeyi indirin.")
        path = self.state["path"]
        if PLATFORM == "windows":
            os.startfile(path)
        else:
            subprocess.Popen(["open", path])
