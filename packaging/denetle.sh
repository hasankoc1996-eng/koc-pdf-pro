# Paketlemeden önceki denetim: make_dmg.sh ve make_windows.sh bunu okur ("source"), kendi başına çalıştırılmaz.
#  • Kaynak deftere (git) kaydedilmiş olmalı: paketin hangi revizyondan üretildiği REV'de kalır, derleme kaydına yazılır.
#  • Testler geçmeli; geçmezse paket üretilmez. Aynı revizyonda daha önce geçtiyse yeniden çalıştırılmaz.
# Yalnızca denemelik paket için (yayinla.sh bunları yayımlamaz): KIRLI=1 kaydedilmemiş değişiklikle, TESTSIZ=1 testsiz.
CACHE="$HOME/Library/Caches/PDFStudyo"
REV="$(git -C "$PROJECT" rev-parse HEAD)"
if [ -n "$(git -C "$PROJECT" status --porcelain)" ]; then
  if [ "${KIRLI:-}" != 1 ]; then
    echo "✗ Kaynakta deftere (git) kaydedilmemiş değişiklik var: paket üretilmedi. Önce değişiklikleri kaydedin."
    echo "  (Yalnızca denemelik paket için KIRLI=1 ile üretilebilir; yayinla.sh onu yayımlamaz.)"
    exit 1
  fi
  KIRLI_MI=evet
  echo "! Kaydedilmemiş değişiklikle üretiliyor (KIRLI=1): bu paket yayımlanamaz"
else
  KIRLI_MI=hayir
fi
if [ "${TESTSIZ:-}" = 1 ]; then
  TESTLER=atlandı
  echo "! Testler atlandı (TESTSIZ=1): bu paket yayımlanamaz"
elif [ "$KIRLI_MI" = hayir ] && [ -f "$CACHE/testler/$REV" ]; then
  TESTLER=geçti
  echo "• Testler bu revizyonda daha önce geçti (${REV:0:10})"
else
  echo "• Testler çalışıyor (birkaç dakika sürer)…"
  mkdir -p "$CACHE/testler"
  TEST_LOG="$CACHE/testler/son.log"
  if ! "$PROJECT/.venv/bin/python" -W ignore "$PROJECT/test/backend_test.py" > "$TEST_LOG" 2>&1; then
    grep "^❌" "$TEST_LOG" | cut -c1-200 | head -20 || true
    echo "✗ Testler başarısız: paket üretilmedi (ayrıntı: $TEST_LOG)"
    exit 1
  fi
  TESTLER=geçti
  if [ "$KIRLI_MI" = hayir ]; then touch "$CACHE/testler/$REV"; fi
fi
