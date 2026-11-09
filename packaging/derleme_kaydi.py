"""Derleme kaydı: paketin hangi kaynak revizyonundan, hangi kütüphane listesiyle üretildiği, testlerin geçip geçmediği
ve üretilen dosyaların SHA-256 parmak izleri. make_dmg.sh / make_windows.sh paketi üretince yazar; yayinla.sh
yayımlamadan önce denetler: testleri geçmeyen, kaydedilmemiş değişiklikle üretilen ya da sonradan değişen paket
yayımlanmaz.

  derleme_kaydi.py yaz KAYIT PLATFORM SÜRÜM REVİZYON KİRLİ TESTLER KİLİT DOSYA...
  derleme_kaydi.py denetle KAYIT_MAC KAYIT_WINDOWS     # yayinla.sh için değişkenler (MAC_V, WIN_V, PKG, EXE, KAYNAK)
"""
import hashlib
import json
import shlex
import sys
import time
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write(record, platform, version, rev, dirty, tests, lock, *files):
    data = {"platform": platform, "surum": version, "kaynak": rev, "kirli": dirty == "evet", "testler": tests,
            "kilit": Path(lock).name, "kilit_sha256": sha256(lock), "tarih": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dosyalar": [{"yol": str(Path(f).resolve()), "boyut": Path(f).stat().st_size, "sha256": sha256(f)}
                         for f in files if Path(f).is_file()]}
    Path(record).parent.mkdir(parents=True, exist_ok=True)
    Path(record).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def check(path, platform, suffix):
    """Kayıt yayımlanabilir mi; değilse nedenleri. Dönen: (kayıt, kurulum dosyasının yolu, sorunlar)."""
    try:
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None, [f"{platform}: derleme kaydı yok ({path}); önce paketi üretin"]
    problems = []
    if rec.get("platform") != platform:
        problems.append(f"{platform}: kayıt başka bir platformun ({rec.get('platform')})")
    if rec.get("testler") != "geçti":
        problems.append(f"{platform}: testler geçmeden üretilmiş ({rec.get('testler')})")
    if rec.get("kirli") is not False:
        problems.append(f"{platform}: kaydedilmemiş değişiklikle üretilmiş")
    installer = next((f for f in rec.get("dosyalar", []) if f["yol"].lower().endswith(suffix)), None)
    if not installer:
        problems.append(f"{platform}: kurulum dosyası ({suffix}) üretilmemiş")
    elif not Path(installer["yol"]).is_file():
        problems.append(f"{platform}: kurulum dosyası bulunamadı ({installer['yol']})")
    elif sha256(installer["yol"]) != installer["sha256"]:
        problems.append(f"{platform}: kurulum dosyası üretildikten sonra değişmiş ({installer['yol']})")
    return rec, installer and installer["yol"], problems


def verify(mac_record, win_record):
    mac, pkg, p1 = check(mac_record, "mac", ".pkg")
    win, exe, p2 = check(win_record, "windows", ".exe")
    problems = p1 + p2
    if mac and win and mac.get("kaynak") != win.get("kaynak"):
        problems.append(f"Mac ve Windows paketleri farklı revizyonlardan üretilmiş "
                        f"({str(mac.get('kaynak'))[:10]} / {str(win.get('kaynak'))[:10]})")
    if problems:
        print("✗ Yayımlanmadı:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    for name, value in (("MAC_V", mac["surum"]), ("WIN_V", win["surum"]), ("PKG", pkg), ("EXE", exe),
                        ("KAYNAK", mac["kaynak"])):
        print(f"{name}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    cmd, args = sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2:]
    if cmd == "yaz" and len(args) >= 7:
        write(*args)
    elif cmd == "denetle" and len(args) == 2:
        sys.exit(verify(*args))
    else:
        sys.exit(__doc__)
