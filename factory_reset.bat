@echo off
chcp 65001 >nul 2>&1
title USTAT v5.0 — Fabrika Ayarlarina Donus
color 0E

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║         USTAT v5.0 — FABRIKA AYARLARINA DONUS           ║
echo ║                                                          ║
echo ║  Bu islem tum kod degisikliklerini geri alir ve          ║
echo ║  sistemi v5.0 fabrika ayarlarina dondurur.               ║
echo ║                                                          ║
echo ║  Etkilenen:                                              ║
echo ║    - Tum Python/JS/JSX kaynak kodlari sifirlanir         ║
echo ║    - Konfigürasyon dosyalari sifirlanir                  ║
echo ║    - Veritabani silinir (MT5 sync tekrar dolduracak)     ║
echo ║    - Log dosyalari temizlenir                            ║
echo ║                                                          ║
echo ║  ETKİLENMEYEN:                                           ║
echo ║    - MT5 islem gecmisi (MT5'te kalir)                    ║
echo ║    - MT5 hesap ayarlari                                  ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

set /p ONAY="Devam etmek istiyor musunuz? (E/H): "
if /i not "%ONAY%"=="E" (
    echo Islem iptal edildi.
    pause
    exit /b 0
)

echo.
echo [1/7] Calisan USTAT processleri durduruluyor...

:: API process (api.pid)
if exist "C:\USTAT\api.pid" (
    set /p API_PID=<"C:\USTAT\api.pid"
    taskkill /F /PID %API_PID% >nul 2>&1
    del "C:\USTAT\api.pid" >nul 2>&1
    echo       API process durduruldu.
)

:: Port 8000 (API fallback)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: Port 5173 (Vite)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: Electron
taskkill /F /IM electron.exe >nul 2>&1

echo       Tum processler durduruldu.

echo.
echo [2/7] Git durumu kontrol ediliyor...

cd /d "C:\USTAT"

:: Git var mi?
git --version >nul 2>&1
if errorlevel 1 (
    echo HATA: Git kurulu degil! Git yukleyin: https://git-scm.com
    pause
    exit /b 1
)

:: Git repo mu?
if not exist "C:\USTAT\.git" (
    echo HATA: Git repository bulunamadi! .git klasoru yok.
    pause
    exit /b 1
)

:: Factory tag var mi?
git tag -l "v5.0-factory" | findstr "v5.0-factory" >nul 2>&1
if errorlevel 1 (
    echo HATA: v5.0-factory etiketi bulunamadi!
    pause
    exit /b 1
)

echo       Git kontrol tamam.

echo.
echo [3/7] Kod fabrika ayarlarina dondurulüyor...

git reset --hard v5.0-factory
if errorlevel 1 (
    echo HATA: Git reset basarisiz!
    pause
    exit /b 1
)

echo       Kod sifirlandı.

echo.
echo [4/7] Gereksiz dosyalar temizleniyor...

git clean -fd >nul 2>&1
echo       Temizlik tamamlandı.

echo.
echo [5/7] Veritabani ve loglar temizleniyor...

:: Database sil (MT5 sync tekrar dolduracak)
if exist "C:\USTAT\database\trades.db" del "C:\USTAT\database\trades.db"
if exist "C:\USTAT\database\trades.db-journal" del "C:\USTAT\database\trades.db-journal"
if exist "C:\USTAT\database\trades.db-wal" del "C:\USTAT\database\trades.db-wal"

:: Log dosyalari temizle
del "C:\USTAT\*.log" >nul 2>&1
if exist "C:\USTAT\logs" del "C:\USTAT\logs\*.log" >nul 2>&1

:: Runtime temizle
del "C:\USTAT\api.pid" >nul 2>&1

echo       Veritabani ve loglar temizlendi.

echo.
echo [6/7] Python bagimlilikları kontrol ediliyor...

pip install -r "C:\USTAT\requirements.txt" --quiet >nul 2>&1
if errorlevel 1 (
    echo       UYARI: Python bagimliliklari yuklenemedi.
    echo       Manuel calistirin: pip install -r requirements.txt
) else (
    echo       Python bagimliliklari tamam.
)

echo.
echo [7/7] Node bagimliliklari kontrol ediliyor...

if exist "C:\USTAT\desktop\package.json" (
    if not exist "C:\USTAT\desktop\node_modules" (
        echo       node_modules bulunamadi, yukleniyor (bu biraz surebilir)...
        cd /d "C:\USTAT\desktop"
        npm install --silent >nul 2>&1
        cd /d "C:\USTAT"
        if errorlevel 1 (
            echo       UYARI: Node bagimliliklari yuklenemedi.
            echo       Manuel calistirin: cd desktop ^&^& npm install
        ) else (
            echo       Node bagimliliklari yuklendi.
        )
    ) else (
        echo       Node bagimliliklari zaten mevcut.
    )
)

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║              FABRIKA AYARLARI BASARIYLA YUKLENDI         ║
echo ║                                                          ║
echo ║  USTAT v5.0 sifirdan calistirilmaya hazir.              ║
echo ║                                                          ║
echo ║  Baslatmak icin:                                         ║
echo ║    1. USTAT ikonuna tiklayin                             ║
echo ║    2. OTP kodunu girin                                   ║
echo ║    3. Sistem otomatik calisacak                          ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

:: Dogrulama
echo Dogrulama:
git log --oneline -1
git tag -l "v5.0-factory"
echo.

pause
