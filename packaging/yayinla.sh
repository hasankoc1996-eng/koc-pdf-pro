#!/bin/bash
# Yeni sürümü GitHub'daki kaynak kodu deposunun Sürümler (Releases) bölümünde yayımlar; kurulu uygulamalar
# "Güncelleme hazır" deyip kendini günceller.
#
#   packaging/yayinla.sh "Yenilikler: kaşe aracı, sorun bildir…" [docs/surum-notlari/1.0.1.md]
#
# İlk yazı kısa yeniliklerdir: kurulu uygulama "Güncelleme hazır" penceresinde gösterir (düz metin). İsteğe bağlı
# ikinci bilgi, GitHub'daki sürüm sayfasına yazılacak ayrıntılı notların dosyasıdır (Markdown); adı sürüm numarası
# olmalıdır (1.0.1.md). Verilmezse sürüm sayfasına da kısa yenilikler yazılır.
# Önce make_dmg.sh ve make_windows.sh çalıştırılmış olmalı. Paket üretmek ile yayımlamak ayrı adımlardır: burada
# yalnızca derleme kayıtları (derleme_kaydi.py) denetlenir. Testleri geçmeden ya da kaydedilmemiş değişiklikle
# üretilen, üretildikten sonra değişen ya da Mac ile Windows'u farklı revizyonlardan gelen paket yayımlanmaz.
# Sürüme kurulum dosyaları ve surum.json (sürüm, boyut, SHA-256 parmak izi, kaynak revizyonu) eklenir. Kaynak kod bu
# betikle gönderilmez: paketlerin üretildiği revizyon depoda (git push) zaten bulunmalıdır.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/.." && pwd)"
NOTES="${1:?Kullanım: packaging/yayinla.sh \"Yenilikler…\" [sürüm-notları.md]}"
NOTES_FILE="${2:-}"
if [ -n "$NOTES_FILE" ] && [ ! -f "$NOTES_FILE" ]; then
  echo "✗ Yayımlanmadı: sürüm notları dosyası bulunamadı: $NOTES_FILE"
  exit 1
fi
REPO=hasankoc1996-eng/koc-pdf-pro   # updater.py REPO ile aynı
CACHE="$HOME/Library/Caches/PDFStudyo"
# Denetim geçerse MAC_V, WIN_V, PKG, EXE ve KAYNAK (paketlerin üretildiği git revizyonu) gelir
KAYIT=$("$PROJECT/.venv/bin/python" "$HERE/derleme_kaydi.py" denetle "$CACHE/derleme-mac.json" "$CACHE/derleme-windows.json") \
  || exit 1
eval "$KAYIT"
# Sürüm numarası surum.txt'ten gelir; iki paket aynı revizyondan üretildiği için numaraları da aynı olmalı
if [ "$MAC_V" != "$WIN_V" ]; then
  echo "✗ Yayımlanmadı: Mac ($MAC_V) ve Windows ($WIN_V) paketlerinin sürüm numarası farklı."
  exit 1
fi
TAG="v$MAC_V"
# Ayrıntılı notlar başka bir sürümün dosyası olmasın (ör. 1.0.1 yayımlanırken 1.0.0.md)
if [ -n "$NOTES_FILE" ]; then
  if [ "$(basename "$NOTES_FILE")" != "$MAC_V.md" ]; then
    echo "✗ Yayımlanmadı: sürüm notları dosyasının adı $MAC_V.md olmalı: $NOTES_FILE"
    exit 1
  fi
  BODY=(--notes-file "$NOTES_FILE")
else
  BODY=(--notes "$NOTES")
fi

OUT="$CACHE/yayin"
rm -rf "$OUT"
mkdir -p "$OUT"
cp "$PKG" "$OUT/KocPDFPro.pkg"   # GitHub dosya adlarındaki Türkçe harfleri ve boşlukları bozar
cp "$EXE" "$OUT/KocPDFPro-Kurulum.exe"
"$PROJECT/.venv/bin/python" - "$OUT" "$MAC_V" "$WIN_V" "$NOTES" "$KAYNAK" <<'PY'
import hashlib, json, sys
from pathlib import Path
out, mac_v, win_v, notes, rev = Path(sys.argv[1]), *sys.argv[2:]

def entry(name, version):
    data = (out / name).read_bytes()
    return {"surum": version, "dosya": name, "boyut": len(data), "sha256": hashlib.sha256(data).hexdigest()}

manifest = {"notlar": notes, "kaynak": rev,   # paketlerin üretildiği git revizyonu
            "mac": entry("KocPDFPro.pkg", mac_v), "windows": entry("KocPDFPro-Kurulum.exe", win_v)}
(out / "surum.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
PY

if ! gh repo view "$REPO" >/dev/null 2>&1; then
  echo "✗ Yayımlanmadı: $REPO deposu yok. Önce kaynak kodu deposu açılıp gönderilmeli (git push)."
  exit 1
fi
# Paketlerin üretildiği revizyon depoda olmalı: sürüm sayfasındaki kaynak kodu paketlerle aynı olsun
if ! gh api "repos/$REPO/commits/$KAYNAK" >/dev/null 2>&1; then
  echo "✗ Yayımlanmadı: paketlerin üretildiği revizyon (${KAYNAK:0:10}) depoda yok. Önce git push."
  exit 1
fi
# Aynı numara iki kez yayımlanmaz; yeni numara son yayımlanandan büyük olmalı (kurulu uygulamalar büyüğünü yeni sayar)
LATEST=$(gh release view --repo "$REPO" --json tagName -q .tagName 2>/dev/null || true)
LATEST="${LATEST#v}"
if [ -n "$LATEST" ] && { [ "$LATEST" = "$MAC_V" ] || [ "$(printf '%s\n%s\n' "$LATEST" "$MAC_V" | sort -V | tail -1)" != "$MAC_V" ]; }; then
  echo "✗ Yayımlanmadı: son yayımlanan sürüm $LATEST, bu paketler $MAC_V. surum.txt'teki numarayı artırın (ör. 1.0.1),"
  echo "  deftere kaydedip paketleri yeniden üretin."
  exit 1
fi
echo "• $TAG yayımlanıyor (Mac $MAC_V · Windows $WIN_V · kaynak ${KAYNAK:0:10})…"
gh release create "$TAG" "$OUT/surum.json" "$OUT/KocPDFPro.pkg" "$OUT/KocPDFPro-Kurulum.exe" \
  --repo "$REPO" --target "$KAYNAK" --title "Koç PDF Pro $TAG" "${BODY[@]}" --latest
rm -rf "$OUT"
echo "Yayımlandı: https://github.com/$REPO/releases/tag/$TAG"
