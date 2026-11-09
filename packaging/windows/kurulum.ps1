# Koç PDF Pro — Windows kurulumu: masaüstüne ve Başlat menüsüne kısayol ekler, ardından uygulamayı açar.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $here 'python\pythonw.exe'
$launcher = Join-Path $here 'launcher.pyw'
$icon = Join-Path $here 'KocPDFPro.ico'

if (-not (Test-Path $pythonw)) {
    Write-Host 'Hata: python klasörü bulunamadı. ZIP dosyasının tamamını bir klasöre çıkardığınızdan emin olun.' -ForegroundColor Red
    Read-Host 'Kapatmak için Enter'
    exit 1
}

# İnternetten indirilen dosyalardaki "güvenilmeyen kaynak" işaretini kaldır
Get-ChildItem -Path $here -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

$shell = New-Object -ComObject WScript.Shell
$places = @(
    [Environment]::GetFolderPath('Desktop'),
    (Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs')
)
foreach ($dir in $places) {
    $link = $shell.CreateShortcut((Join-Path $dir 'Koç PDF Pro.lnk'))
    $link.TargetPath = $pythonw
    $link.Arguments = '"' + $launcher + '"'
    $link.WorkingDirectory = $here
    $link.IconLocation = $icon
    $link.Description = 'Koç PDF Pro — PDF okuma, dönüştürme ve düzenleme'
    $link.Save()
}

Write-Host ''
Write-Host 'Koç PDF Pro kuruldu.' -ForegroundColor Green
Write-Host 'Masaüstündeki ve Başlat menüsündeki "Koç PDF Pro" kısayoluyla açabilirsiniz.'
Write-Host ''
Start-Process -FilePath $pythonw -ArgumentList ('"' + $launcher + '"') -WorkingDirectory $here
Start-Sleep -Seconds 2
