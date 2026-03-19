' USTAT v5.6 — Baslatici (Admin Elevated)
'
' NEDEN ADMIN (RUNAS):
'   MT5 admin olarak calisiyor (C:\Program Files altinda).
'   OTP scripti (mt5_automator.py) admin Python ile MT5 penceresine
'   SendMessageW gonderiyor (UIPI: normal user -> admin window YASAK).
'   VBS "runas" ile TEK UAC prompt cikar, start_ustat.py admin calisir.
'
' AKIS:
'   Masaustu ikonu -> wscript.exe -> start_ustat.vbs (bu dosya)
'   -> UAC "Evet" -> start_ustat.py (admin)
'   -> API (uvicorn) + Vite + Electron baslatilir
'
' NEDEN FULL PATH:
'   Python "C:\Users\pc\AppData\Local" altinda kurulu (kullanici bazli).
'   wscript.exe sistem PATH'ini kullanir, kullanici PATH'ini KULLANMAZ.
'   Bu yuzden "python" komutu bulunamaz -> VBS sessizce basarisiz olur.
'   Cozum: python.exe'nin tam yolunu kullan.

Dim pythonExe
pythonExe = "C:\Users\pc\AppData\Local\Programs\Python\Python314\python.exe"

' Otomatik: VBS dosyasinin bulundugu klasoru USTAT_DIR olarak kullan
Dim scriptDir
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
Dim startScript
startScript = scriptDir & "\start_ustat.py"

' Admin olarak Python launcher'i baslat
' "runas" verb -> UAC prompt cikar, kullanici "Evet" tiklar
' 0 = gizli pencere (SW_HIDE), Python arka planda calisir
Set appShell = CreateObject("Shell.Application")
appShell.ShellExecute pythonExe, """" & startScript & """", scriptDir, "runas", 0
