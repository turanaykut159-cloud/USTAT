@echo off
REM ÜSTAT Tam Yeniden Başlatma — API + Vite + Electron + Ajan
REM Bu script her şeyi kapatır ve sıfırdan başlatır.

cd /d "%~dp0"

echo [1/4] Tüm USTAT süreçleri kapatılıyor...
REM Electron kapat
taskkill /IM electron.exe /F >nul 2>&1
REM Node kapat (Vite)
taskkill /IM node.exe /F >nul 2>&1
REM Port 8000 API kapat
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
REM Kalan pythonw kapat (ajan dahil)
taskkill /IM pythonw.exe /F >nul 2>&1
timeout /t 3 /nobreak >nul

echo [2/4] USTAT başlatılıyor...
start "" pythonw "%~dp0start_ustat.py"
timeout /t 20 /nobreak >nul

echo [3/4] Ajan başlatılıyor...
start "" wscript.exe "%~dp0start_agent.vbs"
timeout /t 3 /nobreak >nul

echo [4/4] Tamamlandı.
