#!/bin/bash
# Paket kütüphanelerinin sürümlerini sabitler: bagimliliklar/*.in'deki kütüphaneler dolaylı bağımlılıklarıyla birlikte
# çözümlenir; her birinin sürümü ve indirilecek dosyaların SHA-256 parmak izleri bagimliliklar/mac.txt ile
# windows.txt'e yazılır. make_dmg.sh ve make_windows.sh yalnızca bu listelerdekini kurar; parmak izi tutmayan dosya
# kurulmaz. Listeler deftere (git) kaydedilir: hangi sürümün hangi kütüphanelerle üretildiği oradan izlenir.
#
#   packaging/kilitle.sh              # .in'e yeni eklenen kütüphane girer; var olanların sürümü değişmez
#   packaging/kilitle.sh --upgrade    # hepsi en son uyumlu sürüme yükseltilir (ardından testler ve deneme şart)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/.." && pwd)"
UV="$PROJECT/.venv/bin/uv"
PYVER=3.13.16   # make_dmg.sh ve make_windows.sh ile aynı
D="$HERE/bagimliliklar"
cd "$D"   # listelerde yollar göreli yazılsın
"$UV" pip compile -q mac.in -o mac.txt --python-version "$PYVER" --python-platform aarch64-apple-darwin \
  --only-binary :all: --generate-hashes --custom-compile-command "packaging/kilitle.sh" "$@"
# proxy-tools (pywebview'in) yalnızca kaynak kodu olarak yayımlanıyor: kurulurken pakete dönüştürülür (saf Python)
"$UV" pip compile -q windows.in -o windows.txt --python-version "$PYVER" --python-platform x86_64-pc-windows-msvc \
  --only-binary :all: --no-binary proxy-tools --generate-hashes --custom-compile-command "packaging/kilitle.sh" "$@"
echo "Hazır: $D/mac.txt ($(grep -c '==' mac.txt) kütüphane) · $D/windows.txt ($(grep -c '==' windows.txt) kütüphane)"
