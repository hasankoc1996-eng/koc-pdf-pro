#!/bin/bash
# Başka Mac'lere kurulabilen, Python gerektirmeyen "Koç PDF Pro" kurulum dosyalarını üretir:
#   .pkg (önerilen: doğrudan Uygulamalar'a kurar) ve .dmg (sürükle-bırak).
#
#   packaging/make_dmg.sh [çıktı.dmg]     (varsayılan: ~/Projeler/Koç PDF Pro Kurulum/<bugün>/)
#
# Önce kaynağın deftere kaydedildiği ve testlerin geçtiği denetlenir (denetle.sh). Taşınabilir Python (uv ile,
# macOS 11+ uyumlu) her derlemede temiz bir ortama kurulur; kütüphaneler bagimliliklar/mac.txt'teki sabit sürümler
# ve parmak izleriyle gelir. Sunucu PyInstaller ile tek klasöre dönüştürülüp uygulamanın içine gömülür. Masaüstündeki
# kurulu uygulamaya dokunulmaz. Sonunda derleme kaydı yazılır (yayinla.sh denetler).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/.." && pwd)"
OUT="${1:-$HOME/Projeler/Koç PDF Pro Kurulum/$(date +%Y-%m-%d)/Koç PDF Pro.dmg}"
WORK="$HOME/Library/Caches/PDFStudyo/package"
ENV="$HOME/Library/Caches/PDFStudyo/buildenv"
UV="$PROJECT/.venv/bin/uv"
PYVER=3.13.16   # packaging/kilitle.sh ve make_windows.sh ile aynı
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
# Paketin sürümü surum.txt'te (yeni sürüm yayımlamadan önce artırılır). Uygulama güncelleme denetiminde bunu
# yayımlanan sürümle karşılaştırır (packaging/yayinla.sh)
VERSION="$(tr -d '[:space:]' < "$PROJECT/surum.txt")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "✗ surum.txt geçersiz: '$VERSION' (ör. 1.0.0)"; exit 1; }

# 0) Kaynak kaydedilmiş mi, testler geçiyor mu (REV, KIRLI_MI, TESTLER)
source "$HERE/denetle.sh"

# 1) Taşınabilir Python ortamı (Homebrew Python yalnızca bu Mac'in macOS sürümünde çalışır): her derlemede sıfırdan,
#    yalnızca kilit listesindeki sürümler (parmak izi tutmayan dosya kurulmaz)
[ -x "$UV" ] || "$PROJECT/.venv/bin/pip" install -q uv
echo "• Derleme ortamı temiz kuruluyor (Python $PYVER, bagimliliklar/mac.txt)…"
"$UV" python install -q "$PYVER"
rm -rf "$ENV"
"$UV" venv -q --python "$PYVER" "$ENV"
"$UV" pip sync -q --python "$ENV/bin/python" --require-hashes --only-binary :all: "$HERE/bagimliliklar/mac.txt"

# 2) Sunucuyu paketle
echo "• Sunucu paketleniyor…"
rm -rf "$WORK"
mkdir -p "$WORK/stage" "$WORK/src"
# Pakete giden kaynakların kopyası (proje klasörü aynen kalır) ve paketin sürüm bilgisi
cp "$PROJECT"/*.py "$WORK/src/"
printf 'SURUM = "%s"\nKAYNAK = "%s"\n' "$VERSION" "$REV" > "$WORK/src/_surum.py"
ditto "$PROJECT/static" "$WORK/src/static"
ditto "$PROJECT/scripts" "$WORK/src/scripts"
KOCPDF_SRC="$WORK/src" "$ENV/bin/pyinstaller" "$HERE/server.spec" --noconfirm --log-level WARN --distpath "$WORK/dist" --workpath "$WORK/build"

# Paketteki en yüksek "en düşük macOS" değeri: uygulamanın çalışacağı en eski sürüm
MINOS=$(find "$WORK/dist/server" -type f \( -name "*.so" -o -name "*.dylib" -o -name "kocpdf-server" \) -exec sh -c \
  'otool -l "$1" 2>/dev/null | awk "/LC_BUILD_VERSION/{f=1} f&&/minos/{print \$2; exit}"' _ {} \; | sort -V | tail -1)
echo "  en düşük macOS: $MINOS"

# 3) Uygulamayı gömülü sunucuyla derle
echo "• Uygulama derleniyor…"
APP="$WORK/stage/Koç PDF Pro.app"
EMBED_SERVER="$WORK/dist/server" "$PROJECT/native/build.sh" "$APP" >/dev/null
/usr/libexec/PlistBuddy -c "Set :LSMinimumSystemVersion $MINOS" "$APP/Contents/Info.plist"
codesign --force --deep -s - "$APP" 2>/dev/null
codesign --verify --deep "$APP"

# 4) Kurulum dosyası: uygulama + Uygulamalar kısayolu + kurulum notu
ln -s /Applications "$WORK/stage/Uygulamalar"
cp "$HERE/Kurulum.txt" "$WORK/stage/Önce Beni Oku.txt"
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
echo "• Kurulum dosyası oluşturuluyor…"
hdiutil create -quiet -volname "Koç PDF Pro" -srcfolder "$WORK/stage" -fs HFS+ -format UDZO -ov "$OUT"

echo "Hazır: $OUT ($(du -h "$OUT" | cut -f1))"

# 5) Kurulum paketi (.pkg): Mac'in kurulum sihirbazıyla doğrudan Uygulamalar klasörüne kurar.
#    DMG'deki gibi masaüstünde disk kalmaz; kurulan uygulama "internetten indirildi" işareti taşımaz.
PKG_OUT="${OUT%.dmg}.pkg"
echo "• Kurulum paketi (.pkg) oluşturuluyor…"
ROOT="$WORK/pkgroot"
mkdir -p "$ROOT/Applications"
# pkgbuild, Türkçe karakterli adları ayrık (NFD) biçimde ister; birleşik "ç" ile "klasör yok" hatası verir.
# macOS iki biçimi aynı ad sayar: kurulunca Finder'da yine "Koç PDF Pro" görünür.
APP_NAME_NFD=$(python3 -c "import unicodedata; print(unicodedata.normalize('NFD', 'Koç PDF Pro.app'))")
ditto "$APP" "$ROOT/Applications/$APP_NAME_NFD"
pkgbuild --analyze --root "$ROOT" "$WORK/components.plist" >/dev/null
# Her zaman /Applications'a kur: bilgisayarda başka bir kopya (ör. açık DMG diski) varsa oraya yönelmesin.
# macOS 27'nin pkgbuild'i bu anahtarı yazmıyor (orada varsayılanı zaten false); eski macOS'larda varsayılan true
# olduğu için açıkça yazılır. Önce silinir: anahtar varsa "Add" hata verir, yoksa "Set" hata verir.
/usr/libexec/PlistBuddy -c "Delete :0:BundleIsRelocatable" "$WORK/components.plist" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Add :0:BundleIsRelocatable bool false" "$WORK/components.plist"
pkgbuild --quiet --root "$ROOT" --component-plist "$WORK/components.plist" --identifier local.pdfstudyo.app \
  --version "$VERSION" --install-location / "$WORK/KocPDFPro.pkg"
sed -e "s/__MINOS__/$MINOS/" -e "s/__VERSION__/$VERSION/" "$HERE/pkg/distribution.xml" > "$WORK/distribution.xml"
rm -f "$PKG_OUT"
productbuild --quiet --distribution "$WORK/distribution.xml" --resources "$HERE/pkg" --package-path "$WORK" "$PKG_OUT"

# Ara kopyaları LaunchServices'ten sil: PDF'ler yanlışlıkla bu kopyalarla açılmasın
"$LSREGISTER" -u "$APP" >/dev/null 2>&1 || true
"$LSREGISTER" -u "$ROOT/Applications/$APP_NAME_NFD" >/dev/null 2>&1 || true
rm -rf "$WORK/stage" "$ROOT"
echo "Hazır: $PKG_OUT ($(du -h "$PKG_OUT" | cut -f1)) · sürüm $VERSION"

# 6) Derleme kaydı: sürüm, kaynak revizyonu, kütüphane listesi, test sonucu, dosyaların parmak izleri (yayinla.sh denetler)
"$PROJECT/.venv/bin/python" "$HERE/derleme_kaydi.py" yaz "$CACHE/derleme-mac.json" mac "$VERSION" "$REV" "$KIRLI_MI" \
  "$TESTLER" "$HERE/bagimliliklar/mac.txt" "$PKG_OUT" "$OUT"
cp "$CACHE/derleme-mac.json" "$(dirname "$OUT")/derleme-mac.json"
echo "Derleme kaydı: $(dirname "$OUT")/derleme-mac.json (kaynak ${REV:0:10}, testler $TESTLER)"
