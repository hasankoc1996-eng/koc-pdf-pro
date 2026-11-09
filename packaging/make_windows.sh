#!/bin/bash
# Windows'ta çalışan "Koç PDF Pro" paketini (ZIP) Mac'te hazırlar. Derleme gerekmez:
#   • python.org'un Windows için taşınabilir ("embeddable") Python'u
#   • kütüphanelerin Windows (win_amd64) sürümleri: bagimliliklar/windows.txt'teki sabit sürümler ve parmak izleriyle,
#     her derlemede temiz bir klasöre
#   • uygulama kodu, başlatıcı (kendi uygulama penceresi; açılamazsa Edge) ve kurulum betikleri
# Önce kaynağın deftere kaydedildiği ve testlerin geçtiği denetlenir (denetle.sh); sonunda derleme kaydı yazılır.
#
#   packaging/make_windows.sh [çıktı.zip]     (varsayılan: ~/Projeler/Koç PDF Pro Kurulum/<bugün>/)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/.." && pwd)"
OUT="${1:-$HOME/Projeler/Koç PDF Pro Kurulum/$(date +%Y-%m-%d)/Koç PDF Pro - Windows.zip}"
PYVER=3.13.16   # packaging/kilitle.sh ve make_dmg.sh ile aynı
PY_SHA=97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297   # python-$PYVER-embed-amd64.zip
WORK="$HOME/Library/Caches/PDFStudyo/win"
UV="$PROJECT/.venv/bin/uv"
STAGE="$WORK/stage/KocPDFPro"
# Paketin sürümü surum.txt'te (yeni sürüm yayımlamadan önce artırılır). Uygulama güncelleme denetiminde bunu
# yayımlanan sürümle karşılaştırır (packaging/yayinla.sh)
VERSION="$(tr -d '[:space:]' < "$PROJECT/surum.txt")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "✗ surum.txt geçersiz: '$VERSION' (ör. 1.0.0)"; exit 1; }

# 0) Kaynak kaydedilmiş mi, testler geçiyor mu (REV, KIRLI_MI, TESTLER)
source "$HERE/denetle.sh"

# 1) İndirmeler (bir kez; parmak izi tutmazsa durur)
mkdir -p "$WORK/dl"
if [ ! -f "$WORK/dl/python-$PYVER-embed-amd64.zip" ]; then
  echo "• Windows Python $PYVER indiriliyor…"
  curl -sSL -o "$WORK/dl/python-$PYVER-embed-amd64.zip" \
    "https://www.python.org/ftp/python/$PYVER/python-$PYVER-embed-amd64.zip"
fi
echo "$PY_SHA  $WORK/dl/python-$PYVER-embed-amd64.zip" | shasum -a 256 -c - >/dev/null
[ -x "$UV" ] || "$PROJECT/.venv/bin/pip" install -q uv
# Kütüphaneler her derlemede temiz klasöre, yalnızca kilit listesindeki sürümler: uygulamanınkiler, Word/Excel
# otomasyonu, uygulama penceresi (pywebview: Windows'un yerleşik WebView2 bileşeni; Edge açılmaz) ve Windows'un
# yerleşik metin tanıması (winrt). proxy-tools yalnızca kaynak kodu olarak yayımlanıyor (saf Python).
echo "• Windows kütüphaneleri temiz kuruluyor (bagimliliklar/windows.txt)…"
rm -rf "$WORK/site-packages"
"$UV" pip sync -q --target "$WORK/site-packages" --python-platform x86_64-pc-windows-msvc --python-version "$PYVER" \
  --require-hashes --only-binary :all: --no-binary proxy-tools "$HERE/bagimliliklar/windows.txt"

# Microsoft Visual C++ çalışma zamanı (PDF kütüphanesi msvcp140.dll ister; her Windows'ta kurulu olmayabilir).
# Microsoft bu dosyaların uygulamayla birlikte dağıtılmasına izin verir. Kaynak: PyPI "msvc-runtime" paketi.
MSVC_URL="https://files.pythonhosted.org/packages/fe/17/7a1eace5a7c6083bd99db861625c08bb37010dfbe90ed7a0194ae0281689/msvc_runtime-14.44.35112-cp313-cp313-win_amd64.whl"
MSVC_SHA=d4f6cf106aaf235f2a90952f9ec7de49e9946323880d051abf9745a6d4bf60bf
if [ ! -f "$WORK/dl/msvc_runtime.whl" ]; then
  echo "• Visual C++ çalışma zamanı indiriliyor…"
  curl -sSL -o "$WORK/dl/msvc_runtime.whl" "$MSVC_URL"
fi
echo "$MSVC_SHA  $WORK/dl/msvc_runtime.whl" | shasum -a 256 -c - >/dev/null

# 2) Paket klasörü
echo "• Paket hazırlanıyor…"
rm -rf "$WORK/stage"
mkdir -p "$STAGE/python" "$STAGE/app"
unzip -q "$WORK/dl/python-$PYVER-embed-amd64.zip" -d "$STAGE/python"
PTH=$(ls "$STAGE/python"/python3*._pth)
ZIPNAME=$(basename "$(ls "$STAGE/python"/python3*.zip)")
# Arama yolları: standart kitaplık, kütüphaneler, uygulama kodu; site modülü .pth dosyalarını işlesin
printf '%s\r\n.\r\nLib\\site-packages\r\n..\\app\r\nimport site\r\n' "$ZIPNAME" > "$PTH"
mkdir -p "$STAGE/python/Lib"
ditto "$WORK/site-packages" "$STAGE/python/Lib/site-packages"
unzip -q -j "$WORK/dl/msvc_runtime.whl" '*.data/data/msvcp140.dll' '*.data/data/msvcp140_1.dll' \
  '*.data/data/msvcp140_2.dll' -d "$STAGE/python"
cp "$PROJECT"/{app.py,converters.py,tools.py,editor.py,fonts.py,udf.py,ocr.py,person_names.py,updater.py,notlar.py,karsilastir.py,tablolar.py,kilavuz.py,formlar.py,kisisel_veri.py,pdf_ortak.py,paragraflar.py,yedekler.py,ayarlar.py} "$STAGE/app/"
printf 'SURUM = "%s"\nKAYNAK = "%s"\n' "$VERSION" "$REV" > "$STAGE/app/_surum.py"
ditto "$PROJECT/static" "$STAGE/app/static"
cp "$HERE/windows/"{launcher.pyw,kapat.ps1,kurulum.ps1,Kurulum.bat,Baslat.bat,"BENI OKU.txt"} "$STAGE/"
"$PROJECT/.venv/bin/python" - "$STAGE/KocPDFPro.ico" "$PROJECT/native" <<'PY'
import sys
sys.path.insert(0, sys.argv[2])
from make_icon import make_tile
make_tile(256).save(sys.argv[1], sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
PY
perl -pi -e 's/\r?\n/\r\n/' "$STAGE/BENI OKU.txt"   # Windows satır sonları
find "$WORK/stage" -name ".DS_Store" -delete
find "$WORK/stage" -name "__pycache__" -type d -prune -exec rm -rf {} +
# Python dosyalarının derlenmiş (hazır) hâlleri pakete girer: Windows kurulumdan ve her güncellemeden sonraki ilk
# açılışta yüzlerce dosyayı yeniden derlemesin (açılışı birkaç saniye uzatıyordu). Kütüphaneler değişmez: hazır hâlleri
# kaynakları okunmadan kullanılır (unchecked-hash). Uygulamanın kendi kodu (app/) her açılışta kaynağıyla
# karşılaştırılır (checked-hash): elle düzeltilirse düzeltme geçerli olur. .pyc biçimi Python sürümüne bağlıdır:
# derleyen Python paketteki Windows Python'uyla aynı sürüm ($PYVER). -s: dosyalara Mac'teki derleme yolu yazılmaz.
"$UV" python install -q "$PYVER"
PY_BUILD="$("$UV" python find "$PYVER")"
"$PY_BUILD" -m compileall -q -j0 -s "$STAGE" --invalidation-mode unchecked-hash "$STAGE/python/Lib/site-packages" >/dev/null \
  || echo "! Bazı kütüphane dosyaları derlenemedi; onlar ilk açılışta derlenir."
"$PY_BUILD" -m compileall -q -j0 -s "$STAGE" --invalidation-mode checked-hash "$STAGE/app"

# 3) Kurulum programı (.exe): kurar, güncellemede eskisinin üzerine kurar, kaldırıcı ekler (NSIS, Homebrew: makensis)
EXE="$(dirname "$OUT")/Koç PDF Pro Kurulum.exe"
BUILT_EXE=""   # derleme kaydına yalnızca bu derlemede üretilen .exe girer
if command -v makensis >/dev/null; then
  echo "• Kurulum programı (.exe) oluşturuluyor…"
  rm -f "$EXE"
  # Türkçe karakterler için UTF-8 dil ortamı şart (yoksa "Bad text encoding")
  LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 makensis -V2 -INPUTCHARSET UTF8 -DSTAGE="$STAGE" -DOUTFILE="$EXE" -DVERSION="$VERSION" "$HERE/windows/kurulum.nsi"
  BUILT_EXE="$EXE"
  echo "Hazır: $EXE ($(du -h "$EXE" | cut -f1)) · sürüm $VERSION"
else
  echo "! makensis yok (brew install makensis): yalnızca ZIP üretilecek"
fi

# 4) ZIP (Mac'e özgü ek dosyalar olmadan)
echo "• ZIP oluşturuluyor…"
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
"$PROJECT/.venv/bin/python" - "$WORK/stage" "$OUT" <<'PY'
import os, sys, zipfile
root, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(base, name)
            z.write(full, os.path.relpath(full, root))
PY
echo "Hazır: $OUT ($(du -h "$OUT" | cut -f1))"

# 5) Derleme kaydı: sürüm, kaynak revizyonu, kütüphane listesi, test sonucu, dosyaların parmak izleri (yayinla.sh denetler)
"$PROJECT/.venv/bin/python" "$HERE/derleme_kaydi.py" yaz "$CACHE/derleme-windows.json" windows "$VERSION" "$REV" \
  "$KIRLI_MI" "$TESTLER" "$HERE/bagimliliklar/windows.txt" "$BUILT_EXE" "$OUT"
cp "$CACHE/derleme-windows.json" "$(dirname "$OUT")/derleme-windows.json"
echo "Derleme kaydı: $(dirname "$OUT")/derleme-windows.json (kaynak ${REV:0:10}, testler $TESTLER)"
