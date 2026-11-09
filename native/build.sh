#!/bin/bash
# Yerel Mac uygulamasını derler ve masaüstüne "Koç PDF Pro.app" olarak kurar.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/.." && pwd)"
DEST="${1:-$HOME/Desktop/Koç PDF Pro.app}"
BUILD="$HOME/Library/Caches/PDFStudyo/build"  # iCloud Masaüstü öznitelikleri imzayı bozmasın
APP="$BUILD/Koç PDF Pro.app"
# Sürüm numarası (Hakkında panelinde görünür): surum.txt
VERSION="$(tr -d '[:space:]' < "$PROJECT/surum.txt")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "✗ surum.txt geçersiz: '$VERSION' (ör. 1.0.0)"; exit 1; }

rm -rf "$BUILD"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -swift-version 5 -target "$(uname -m)-apple-macos13.0" \
  -framework Cocoa -framework WebKit -framework PDFKit -framework UniformTypeIdentifiers \
  "$HERE/PDFStudyo.swift" -o "$APP/Contents/MacOS/PDFStudyo"
# Simge: native/logo_source.png → AppIcon.iconset (make_icon.py) → AppIcon.icns
"$PROJECT/.venv/bin/python" "$HERE/make_icon.py" >/dev/null
iconutil -c icns "$HERE/AppIcon.iconset" -o "$HERE/AppIcon.icns"
cp "$HERE/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cp "$PROJECT/static/logo.png" "$APP/Contents/Resources/splash.png"   # açılış ekranındaki logo
# Metin tanıma yardımcısı (Apple Vision)
swiftc -O -swift-version 5 -target "$(uname -m)-apple-macos13.0" -framework Vision \
  "$HERE/ocr.swift" -o "$APP/Contents/MacOS/kocpdf-ocr"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Koç PDF Pro</string>
  <key>CFBundleDisplayName</key><string>Koç PDF Pro</string>
  <key>CFBundleIdentifier</key><string>local.pdfstudyo.app</string>
  <key>CFBundleExecutable</key><string>PDFStudyo</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleDevelopmentRegion</key><string>tr</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>© 2026 Hasan Koç. Açık kaynak, GNU AGPL-3.0 lisansıyla.</string>
  <key>NSAppleEventsUsageDescription</key><string>Word belgelerini PDF'e dönüştürmek için Microsoft Word kullanılır.</string>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>PDFStudyoProjectPath</key><string>$PROJECT</string>
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key><string>PDF Belgesi</string>
      <key>CFBundleTypeRole</key><string>Viewer</string>
      <key>LSHandlerRank</key><string>Alternate</string>
      <key>LSItemContentTypes</key><array><string>com.adobe.pdf</string></array>
    </dict>
    <dict>
      <key>CFBundleTypeName</key><string>UYAP Belgesi</string>
      <key>CFBundleTypeRole</key><string>Viewer</string>
      <key>LSHandlerRank</key><string>Alternate</string>
      <key>LSItemContentTypes</key><array><string>tr.gov.uyap.udf</string></array>
      <key>CFBundleTypeExtensions</key><array><string>udf</string></array>
    </dict>
  </array>
  <key>UTImportedTypeDeclarations</key>
  <array>
    <dict>
      <key>UTTypeIdentifier</key><string>tr.gov.uyap.udf</string>
      <key>UTTypeDescription</key><string>UYAP Belgesi</string>
      <key>UTTypeConformsTo</key><array><string>public.data</string></array>
      <key>UTTypeTagSpecification</key><dict>
        <key>public.filename-extension</key><array><string>udf</string></array>
      </dict>
    </dict>
  </array>
</dict>
</plist>
PLIST
if [ -n "${EMBED_SERVER:-}" ]; then
  # Taşınabilir sürüm: PyInstaller ile paketlenmiş sunucuyu uygulamanın içine göm
  ditto "$EMBED_SERVER" "$APP/Contents/Resources/server"
  /usr/libexec/PlistBuddy -c "Delete :PDFStudyoProjectPath" "$APP/Contents/Info.plist"
fi
xattr -cr "$APP"
codesign --force --deep -s - "$APP"
codesign --verify --deep "$APP"

# Eski sürümü (çalışıyorsa) kapat ve yenisiyle değiştir — yalnızca Masaüstündeki kuruluma yazarken
if [ "$DEST" = "$HOME/Desktop/Koç PDF Pro.app" ]; then
  osascript -e 'tell application id "local.pdfstudyo.app" to quit' >/dev/null 2>&1 || true
fi
rm -rf "$DEST"
# Eski adla kurulmuş sürümü kaldır (uygulama "PDF Stüdyo" iken)
[ "$DEST" = "$HOME/Desktop/Koç PDF Pro.app" ] && rm -rf "$HOME/Desktop/PDF Stüdyo.app"
ditto "$APP" "$DEST"
[ "$DEST" = "$HOME/Desktop/Koç PDF Pro.app" ] && /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST" >/dev/null 2>&1 || true
echo "Kuruldu: $DEST"
