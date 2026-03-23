' ÜSTAT AJAN — Sessiz Başlatıcı
' Ajanı arka planda pencere açmadan başlatır.
' Çift tıklayın veya Windows başlangıcına ekleyin.

Set WshShell = CreateObject("WScript.Shell")
strUstatDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strUstatDir
WshShell.Run "pythonw """ & strUstatDir & "\ustat_agent.py""", 0, False
