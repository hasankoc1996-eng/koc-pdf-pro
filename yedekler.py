"""Önceki sürümler: kaydedilirken üzerine yazılacak dosyanın eski hâli yedekler klasörüne kopyalanır; sınırı aşan
ve süresi dolan yedekler silinir. Klasörü (DATA/yedekler) app.py açılışta BACKUPS'a verir."""
import hashlib
import re
import shutil
import time
import unicodedata
from pathlib import Path

BACKUPS = None


# Yedekler: ad_konumkimliği_YılAyGün-SaatDakikaSaniye.uzantı (eski yedeklerde konum kimliği yok).
# Her dosyanın son 10 yedeği tutulur, 60 günden eskiler silinir (Ayarlar › Kaydetme ile değişir);
# "Önceki sürümler" penceresi bunları listeler.
BACKUP_KEEP, BACKUP_DAYS = 10, 60
BACKUP_NAME = re.compile(r"^(?P<stem>.+?)_(?:(?P<tag>[0-9a-f]{8})_)?(?P<ts>\d{8}-\d{6})(?P<suffix>\.[^.]+)$")


def file_tag(path):
    """Dosyanın konumundan kısa kimlik: aynı adlı ama farklı klasördeki dosyaların yedekleri karışmasın."""
    return hashlib.md5(unicodedata.normalize("NFC", str(Path(path).resolve())).lower().encode()).hexdigest()[:8]


def backup_existing(target: Path):
    """Üzerine yazılacak dosyanın eski hâlini yedekler klasörüne kopyalar."""
    if not target.exists():
        return None
    BACKUPS.mkdir(exist_ok=True)
    when = time.time()
    while True:   # aynı saniyede ikinci yedek öncekinin üzerine yazılmasın
        backup = BACKUPS / f"{target.stem}_{file_tag(target)}_{time.strftime('%Y%m%d-%H%M%S', time.localtime(when))}{target.suffix}"
        if not backup.exists():
            break
        when += 1
    try:
        shutil.copy2(target, backup)
    except BaseException:
        backup.unlink(missing_ok=True)   # yarım kalan yedek (disk doldu) bırakılmaz
        raise
    prune_backups()
    return str(backup)


def backups_of(target: Path):
    """Bir dosyanın yedekleri, yeniden eskiye: [(yol, zaman)]. Konum kimliği olmayan eski yedekler adından eşleşir."""
    tag, found = file_tag(target), []
    for f in BACKUPS.glob("*"):
        m = BACKUP_NAME.match(f.name)
        if m and m["suffix"].lower() == target.suffix.lower() and (m["tag"] == tag if m["tag"] else m["stem"] == target.stem):
            found.append((f, time.mktime(time.strptime(m["ts"], "%Y%m%d-%H%M%S"))))
    return sorted(found, key=lambda x: -x[1])


def prune_backups(keep=None, days=None, dry=False):
    """Sınırı aşan ve süresi dolan yedekleri siler. dry: silmeden, silinecekleri döndürür (ayar düşürülürken sorulur)."""
    keep, days = keep or BACKUP_KEEP, days or BACKUP_DAYS
    groups, old = {}, []
    for f in BACKUPS.glob("*"):
        m = BACKUP_NAME.match(f.name)
        if m:
            groups.setdefault(m["tag"] or f"eski:{m['stem']}{m['suffix']}", []).append((m["ts"], f))
    cutoff = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() - days * 86400))
    for items in groups.values():
        items.sort(reverse=True)
        old += [f for k, (ts, f) in enumerate(items) if k >= keep or ts < cutoff]
    if not dry:
        for f in old:
            f.unlink(missing_ok=True)
    return old
