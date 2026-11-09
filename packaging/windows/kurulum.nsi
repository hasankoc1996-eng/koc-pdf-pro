; Koç PDF Pro — Windows kurulum programı (NSIS 3). packaging/make_windows.sh derler:
;   makensis -DSTAGE=<paket klasörü> -DOUTFILE=<çıktı.exe> -DVERSION=<sürüm> kurulum.nsi
; Kullanıcının kendi program klasörüne kurar (yönetici parolası gerekmez). Yeni sürüm eskisinin
; üzerine kurulur; ayarlar (%LOCALAPPDATA%\KocPDFPro) ayrı durduğu için korunur.
Unicode True
ManifestDPIAware true
SetCompressor /SOLID lzma
RequestExecutionLevel user

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

!define APPNAME "Koç PDF Pro"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\KocPDFPro"
!define PROGID "KocPDFPro.Belge"

Name "${APPNAME}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\KocPDFPro"
BrandingText "${APPNAME} ${VERSION} · © 2026 Hasan Koç"

!define MUI_ICON "${STAGE}/KocPDFPro.ico"
!define MUI_UNICON "${STAGE}/KocPDFPro.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "${APPNAME} Kurulumu"
!define MUI_WELCOMEPAGE_TEXT "PDF okuma, düzenleme ve dönüştürme uygulaması ${APPNAME} bilgisayarınıza kurulacak.$\r$\n$\r$\nDaha önce kurduysanız yeni sürüm eskisinin üzerine kurulur; ayarlarınız ve son açtığınız belgeler korunur.$\r$\n$\r$\nUygulama internetsiz çalışır; dosyalarınız bilgisayardan çıkmaz."
!define MUI_FINISHPAGE_TITLE "Kurulum tamamlandı"
!define MUI_FINISHPAGE_TEXT "${APPNAME}'yu masaüstündeki ya da Başlat menüsündeki kısayolla açabilirsiniz.$\r$\n$\r$\nPDF'e sağ tıklayıp “Birlikte aç” menüsünden de açabilirsiniz."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "${APPNAME}'yu şimdi aç"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Turkish"

; Sürüm surum.txt'ten gelir (1.0.0); Windows dört parçalı ister: 1.0.0.0
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=${LANG_TURKISH} "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=${LANG_TURKISH} "CompanyName" "Hasan Koç"
VIAddVersionKey /LANG=${LANG_TURKISH} "LegalCopyright" "© 2026 Hasan Koç. Açık kaynak, GNU AGPL-3.0 lisansıyla."
VIAddVersionKey /LANG=${LANG_TURKISH} "FileDescription" "${APPNAME} Kurulum"
VIAddVersionKey /LANG=${LANG_TURKISH} "FileVersion" "${VERSION}.0"
VIAddVersionKey /LANG=${LANG_TURKISH} "ProductVersion" "${VERSION}"

; Uygulama açıksa: uyar, onay gelirse kapat (kaydedilmemiş değişiklikler için İptal fırsatı)
!macro CloseApp SCRIPT
  nsExec::ExecToStack 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${SCRIPT}" -Check'
  Pop $0
  Pop $1
  ${If} $0 != "0"
  ${AndIf} $0 != "error"
  ${AndIf} $0 != "timeout"
    MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION "${APPNAME} şu anda açık; devam etmek için kapatılacak.$\r$\n$\r$\nKaydedilmemiş değişiklikleriniz varsa İptal'e basıp önce kaydedin." /SD IDOK IDOK +2
    Abort
    nsExec::ExecToStack 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${SCRIPT}"'
    Pop $0
    Pop $1
  ${EndIf}
!macroend

Section "${APPNAME}" SecMain
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "${STAGE}/kapat.ps1"
  !insertmacro CloseApp "$PLUGINSDIR\kapat.ps1"

  SetOutPath "$INSTDIR"
  ; Eski sürümün program dosyaları (ayarlara dokunulmaz)
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  File /r "${STAGE}/python"
  File /r "${STAGE}/app"
  File "${STAGE}/launcher.pyw"
  Delete "$INSTDIR\kocpdf_baslat.pyc"   ; eski sürümlerin derlenmiş başlatıcısı (artık launcher.pyw'nin kendisi çalışır)
  File "${STAGE}/KocPDFPro.ico"
  File "${STAGE}/kapat.ps1"
  File "${STAGE}/BENI OKU.txt"

  ; Kısayollar (eski ZIP kurulumunun kısayollarının üzerine yazar)
  SetShellVarContext current
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\launcher.pyw"' "$INSTDIR\KocPDFPro.ico" 0 SW_SHOWNORMAL "" "${APPNAME} — PDF okuma, dönüştürme ve düzenleme"
  CreateShortcut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\launcher.pyw"' "$INSTDIR\KocPDFPro.ico" 0 SW_SHOWNORMAL "" "${APPNAME} — PDF okuma, dönüştürme ve düzenleme"

  ; PDF / UDF: sağ tık › Birlikte aç listesinde görünsün (varsayılan uygulama değişmez)
  WriteRegStr HKCU "Software\Classes\${PROGID}" "" "${APPNAME} belgesi"
  WriteRegStr HKCU "Software\Classes\${PROGID}\DefaultIcon" "" "$INSTDIR\KocPDFPro.ico"
  WriteRegStr HKCU "Software\Classes\${PROGID}\shell\open" "FriendlyAppName" "${APPNAME}"
  WriteRegStr HKCU "Software\Classes\${PROGID}\shell\open\command" "" '"$INSTDIR\python\pythonw.exe" "$INSTDIR\launcher.pyw" "%1"'
  WriteRegStr HKCU "Software\Classes\.pdf\OpenWithProgids" "${PROGID}" ""
  WriteRegStr HKCU "Software\Classes\.udf\OpenWithProgids" "${PROGID}" ""
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'

  ; Ayarlar › Uygulamalar listesi ve kaldırıcı
  WriteUninstaller "$INSTDIR\Kaldir.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\KocPDFPro.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Hasan Koç"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Kaldir.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Kaldir.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Function LaunchApp
  Exec '"$INSTDIR\python\pythonw.exe" "$INSTDIR\launcher.pyw"'
FunctionEnd

Section "Uninstall"
  !insertmacro CloseApp "$INSTDIR\kapat.ps1"
  SetShellVarContext current
  Delete "$DESKTOP\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  DeleteRegKey HKCU "Software\Classes\${PROGID}"
  DeleteRegValue HKCU "Software\Classes\.pdf\OpenWithProgids" "${PROGID}"
  DeleteRegValue HKCU "Software\Classes\.udf\OpenWithProgids" "${PROGID}"
  DeleteRegKey HKCU "${UNINST_KEY}"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  RMDir /r "$INSTDIR"
  ; Ayarlar ve günlük (%LOCALAPPDATA%\KocPDFPro) yeniden kurulumda kullanılmak üzere bırakılır
SectionEnd
