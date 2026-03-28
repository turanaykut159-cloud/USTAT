' ÜSTAT AJAN — Sessiz Başlatıcı + Watchdog
' Ajanı arka planda pencere açmadan başlatır.
' Crash durumunda otomatik yeniden başlatır (watchdog).
' Windows başlangıcına eklenir — bilgisayar açıldığında çalışır.
' v5.9: Watchdog loop eklendi — ajan ölürse 10sn sonra yeniden başlar.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strUstatDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strUstatDir

Dim strPidFile
strPidFile = strUstatDir & "\.agent\agent.pid"
Dim strCmd
strCmd = "pythonw """ & strUstatDir & "\ustat_agent.py"""

' Watchdog: Ajan çökmüşse yeniden başlat, Ctrl+C veya kapatma olursa dur.
Do
    WshShell.Run strCmd, 0, True   ' True = process bitene kadar bekle
    ' Process bitti — crash mi kontrol et
    WScript.Sleep 3000
    ' Eğer shutdown.signal varsa dur (temiz kapatma)
    If fso.FileExists(strUstatDir & "\.agent\shutdown.signal") Then
        If fso.FileExists(strUstatDir & "\.agent\shutdown.signal") Then
            fso.DeleteFile strUstatDir & "\.agent\shutdown.signal"
        End If
        Exit Do
    End If
    ' Crash — 10sn bekle, yeniden başlat
    WScript.Sleep 10000
Loop
