# USTAT Masaustu Kisayol Guncelleme
# Calistirmak icin: PowerShell -ExecutionPolicy Bypass -File "C:\Users\pc\USTAT\update_shortcut.ps1"

$desktop = [Environment]::GetFolderPath("Desktop")
$newName = "USTAT v5.5 VIOP Algorithmic Trading"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Eski kisayollari bul
$oldPatterns = @("USTAT v5*", "ÜSTAT v5*")
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
$shortcut.TargetPath = Join-Path $projectDir "start_ustat.bat"
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = "USTAT v5.5 VIOP Algorithmic Trading"
$shortcut.IconLocation = Join-Path $projectDir "desktop\assets\icon.ico"

# icon.ico yoksa default kullan
if (-not (Test-Path $shortcut.IconLocation)) {
    $shortcut.IconLocation = Join-Path $projectDir "desktop\assets\icon.svg"
}

$shortcut.Save()
Write-Host ""
Write-Host "Yeni kisayol olusturuldu: $newName" -ForegroundColor Green
Write-Host "Konum: $newPath" -ForegroundColor Cyan
Write-Host ""
Read-Host "Devam etmek icin Enter'a bas"
