# Koç PDF Pro — kurulum/kaldırma sırasında açık uygulamayı bulur ya da kapatır.
#   kapat.ps1 -Check   açık kopya sayısını çıkış kodu olarak döndürür
#   kapat.ps1          açık kopyaları kapatır
param([switch]$Check)
$procs = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like '*KocPDFPro*launcher.pyw*' })
if ($Check) { exit $procs.Count }
foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800   # dosyalar serbest kalsın
exit 0
