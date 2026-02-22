@echo off
:: USTAT v5.0 — Tek tikla baslatici
:: API ve Vite arka planda, Electron gorunur baslar.

:: 1. API sunucusunu gizli baslat
start /B "" cmd /c "cd /d C:\USTAT && python -m uvicorn api.server:app --host 127.0.0.1 --port 8000 >nul 2>&1"

:: API'nin ayaga kalkmasi icin 2 sn bekle
timeout /t 2 /nobreak >nul

:: 2. Vite dev server gizli baslat
start /B "" cmd /c "cd /d C:\USTAT\desktop && npx vite --port 5173 >nul 2>&1"

:: Vite'in hazir olmasi icin 4 sn bekle
timeout /t 4 /nobreak >nul

:: 3. Electron'u dogrudan baslat
set NODE_ENV=development
cd /d C:\USTAT\desktop
start "" "C:\USTAT\desktop\node_modules\electron\dist\electron.exe" .

:: Bu pencere kapansin
exit
