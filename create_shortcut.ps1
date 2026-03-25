# USTAT v5.8 — Masaustu Kisa Yol Olusturucu
# Calistirma: PowerShell -ExecutionPolicy Bypass -File create_shortcut.ps1

$WshShell = New-Object -ComObject WScript.Shell
$ShortcutPath = [System.IO.Path]::Combine($WshShell.SpecialFolders("Desktop"), "USTAT v5.8.lnk")
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = "`"C:\Users\pc\Desktop\USTAT\start_ustat.vbs`""
$Shortcut.WorkingDirectory = "C:\Users\pc\Desktop\USTAT"
$Shortcut.Description = "USTAT v5.8 VIOP Algorithmic Trading"

# Icon ayarla (varsa)
$IconPath = "C:\Users\pc\Desktop\USTAT\desktop\assets\icon.ico"
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
}

$Shortcut.Save()
Write-Host "Kisa yol olusturuldu: $ShortcutPath"
