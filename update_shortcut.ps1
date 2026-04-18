# USTAT Masaustu Kisayol Guncelleme
# Calistirmak icin: PowerShell -ExecutionPolicy Bypass -File "C:\Users\pc\USTAT\update_shortcut.ps1"

$desktop = [Environment]::GetFolderPath("Desktop")
# #274 SYSTEM user fallback — ajan tarafından çağrıldığında GetFolderPath boş döner
if ([string]::IsNullOrEmpty($desktop)) {
    if (Test-Path "C:\Users\pc\Desktop") {
        $desktop = "C:\Users\pc\Desktop"
    } elseif ($env:USERPROFILE -and (Test-Path (Join-Path $env:USERPROFILE "Desktop"))) {
        $desktop = Join-Path $env:USERPROFILE "Desktop"
    } else {
        Write-Host "HATA: Desktop klasörü bulunamadı (SYSTEM user? USERPROFILE eksik?)" -ForegroundColor Red
        exit 1
    }
}
$newName = "USTAT Plus V6.2 VIOP Algorithmic Trading"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Eski kisayollari bul
$oldPatterns = @("USTAT v5*", "ÜSTAT v5*", "USTAT Plus V6.0*", "ÜSTAT Plus V6.0*", "USTAT Plus V6.1*", "ÜSTAT Plus V6.1*")
$found = $false

foreach ($pattern in $oldPatterns) {
    $oldFiles = Get-ChildItem -Path $desktop -Filter "$pattern.lnk" -ErrorAction SilentlyContinue
    foreach ($oldFile in $oldFiles) {
        Write-Host "Eski kisayol bulundu: $($oldFile.Name)" -ForegroundColor Yellow
        Remove-Item $oldFile.FullName -Force
        Write-Host "  Silindi." -ForegroundColor Red
        $found = $true
    }
}

# Yeni kisayol olustur
$newPath = Join-Path $desktop "$newName.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($newPath)
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = "`"$(Join-Path $projectDir 'start_ustat.vbs')`""
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = "USTAT Plus V6.2 VIOP Algorithmic Trading"
$iconPath = Join-Path $projectDir "desktop\assets\icon.ico"
if (Test-Path $iconPath) {
    $shortcut.IconLocation = "$iconPath,0"
}

$shortcut.Save()
Write-Host ""
Write-Host "Yeni kisayol olusturuldu: $newName" -ForegroundColor Green
Write-Host "Konum: $newPath" -ForegroundColor Cyan
