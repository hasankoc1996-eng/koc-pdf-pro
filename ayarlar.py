"""Ayarlar: Ayarlar penceresinin uygulama genelindeki seçimleri okunur, doğrulanır, kaydedilir ve uygulanır.
Dosyanın yerini (DATA/ayarlar.json) app.py açılışta SETTINGS_FILE'a verir."""
import json
import os
import threading

import editor
import yedekler
from tools import ToolError

SETTINGS_FILE = None

# Ayarlar penceresinin uygulama genelindeki seçimleri (DATA/ayarlar.json); yalnız listelenen değerler kabul edilir.
# Gece / gündüz, sayfa görünümü, imza ve kaşe sayfanın belleğinde; arayüz büyüklüğü Mac / Windows kabuğunda durur.
SETTINGS_DEFAULTS = {"backupKeep": 10, "backupDays": 60, "recoverDays": 7, "autoUpdate": True,
                     "saveFolder": "doc", "resumePage": True, "author": ""}
SETTINGS_CHOICES = {
    "backupKeep": (3, 5, 10, 20, 50),
    "backupDays": (7, 30, 60, 180, 365),
    "recoverDays": (1, 3, 7, 14, 30),
    "saveFolder": ("doc", "last", "desktop"),   # Farklı Kaydet: belgenin klasörü, en son kullanılan, Masaüstü
}
settings_lock = threading.Lock()


def valid_setting(key, value):
    default = SETTINGS_DEFAULTS.get(key)
    if key == "author":   # notlarda ve işaretlerde yazar adı: tek satır, en çok 60 harf
        return isinstance(value, str) and len(value) <= 60 and value == " ".join(value.split())
    # bool, int'in alt türü: True, 1 gün sayılmasın
    return default is not None and type(value) is type(default) and value in SETTINGS_CHOICES.get(key, (True, False))


def read_settings():
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    return {k: saved[k] if valid_setting(k, saved.get(k)) else d for k, d in SETTINGS_DEFAULTS.items()}


def save_settings(changes):
    """Değişen ayarlar ({ad: değer}) doğrulanıp kaydedilir ve uygulanır; geçersiz değer kabul edilmez.
    Dönen: bütün ayarlar."""
    with settings_lock:
        s = read_settings()
        for k, v in changes.items():
            if k == "author" and isinstance(v, str):
                v = " ".join(v.split())   # satır sonları ve fazla boşluklar tek boşluk
            if not valid_setting(k, v):
                raise ToolError("Bu ayar değeri geçersiz.")
            s[k] = v
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, SETTINGS_FILE)
        apply_settings(s)
    return s


def apply_settings(s):
    yedekler.BACKUP_KEEP, yedekler.BACKUP_DAYS = s["backupKeep"], s["backupDays"]
    editor.RECOVER_DAYS = s["recoverDays"]
    editor.AUTHOR = s["author"]
