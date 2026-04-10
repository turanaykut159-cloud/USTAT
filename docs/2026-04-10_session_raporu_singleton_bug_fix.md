# 2026-04-10 Oturum Raporu — Singleton Bug Kalıcı Kapatma

## Özet

Kullanıcı talebi: "UYGULAMA NEDEN AÇILMIYOR?" → sonrasında "TAMAM ÇÖZÜM UYGULAMANIN BAŞLATILMASINADA SORUN İSTEMİYORUM DEMİR GİBİ SAĞLAM BİR SİSTEME KUR ÇÖKMESİN. KESİNLİKLE ÇÖKMESİNİ İSTEMİYORUM."

Üç motorlu bir bug zinciri `restart_app` komutunu 3-5 denemeden sonra sonsuza dek bloke ediyordu. TDD fail-first disiplini ile 3 kritik akış testi yazıldı (flow 13/14/15), sonra 3 atomik patch uygulandı ve tüm testler yeşile döndü.

## Kök Neden Analizi (Log Kanıtı)

`logs/electron.log` son 60 satır: 5 ardışık başarısız başlatma denemesi `13:57:45` ile `13:59` arasında hepsi aynı desen:

```
requestSingleInstanceLock: false (apiMode=true)
Baska bir USTAT Electron instance calisiyor, cikis yapiliyor.
app.whenReady bekleniyor...
app.whenReady tamamlandi, API_MODE=true
createWindow() baslatildi           ← HAYALET PENCERE!
```

Bu log `app.quit()` asenkron olduğu için execution'ın devam ettiğini ve `createWindow()`'un hayalet pencere oluşturduğunu kanıtladı. Oluşan hayalet pencere Chromium userData mutex'ini tutuyor ve sonraki her başlatma denemesini bloke ediyordu.

### Üç Bug Konsorsiyumu

| Bug | Dosya | Mekanizma |
|-----|-------|-----------|
| **A** | `desktop/main.js` | `app.quit()` asenkron → `whenReady()` fire → `createWindow()` → hayalet pencere Chromium mutex tutuyor |
| **B** | `ustat_agent.py handle_stop_app` | PowerShell `Get-Process.CommandLine` boş döner (Windows limitasyonu) → regex hiçbir Electron'u yakalamıyor → her `restart_app` zombi Electron bırakıyor |
| **C** | (A)+(B) sinerjisi | Hayalet pencere + biriken zombi'ler → singleton lock sonsuza dek bloke |

## TDD Fail-First Testleri

`tests/critical_flows/test_static_contracts.py` içine üç yeni statik sözleşme testi eklendi:

- **Flow 13** — `test_mainjs_singleton_conflict_exits_with_code_42`: `!gotTheLock` bloğunda `app.exit(42)` bulundu mu
- **Flow 14** — `test_agent_stop_app_kills_electron_reliably`: `handle_stop_app` içinde `psutil` + `electron` + `_kill_ustat_electrons` marker'ı
- **Flow 15** — `test_start_ustat_handles_electron_exit_42`: `run_webview_process` içinde `42` + `singleton_retry` + `ProcessGuard`/`_find_orphan_electrons` marker'ı

Testler patch'lerden ÖNCE yazılıp fail edildiği doğrulandı, sonra patch'lerle birlikte yeşile döndü.

## Uygulanan Patch'ler

### Patch A — `desktop/main.js` (Yellow Zone, C2, commit `8acecad`)

`if (!gotTheLock)` bloğunda `app.quit()` (asenkron) → `app.exit(42)` (senkron) değişimi. Exit code 42 parent Python'a "singleton çatışması" sinyali gönderir.

### Patch B — `ustat_agent.py` (Green Zone, C1, commit `97b334b`)

Yeni helper `_kill_ustat_electrons()`:
- `psutil.process_iter(["pid", "name", "cmdline"])` ile tara
- `name` "electron" içeren VE `cmdline` `USTAT_DIR` veya "ustat" veya "ustat_api_mode" içerenleri filtrele
- Ajan kendi PID'ini ve parent'ını KORU
- `taskkill /F /T /PID` ile tree-kill, psutil fallback
- Öldürülen PID listesini döner

`handle_stop_app` Phase 0 olarak bu helper'ı çağırır — zombi fabrikası kapandı.

### Patch C — `start_ustat.py run_webview_process` (Red Zone, C4 Siyah Kapı, ADDITIVE, commit `969ffd0`)

`electron_proc.wait()` sonrası ADDITIVE bir katman:

```
SINGLETON_CONFLICT_EXIT_CODE = 42
MAX_SINGLETON_RETRIES = 1
_singleton_retries = 0

while True:
    Popen(electron) + wait()
    if exit_code == 42 and _singleton_retries < 1:
        ProcessGuard()._find_orphan_electrons() + _tree_kill()
        time.sleep(1.5)  # Chromium mutex release
        _singleton_retries += 1
        continue
    break
```

Mevcut kapanış zinciri (`_shutdown_api`, atexit, parent monitor) DEĞİŞMEDİ. Anayasa Kural 11 (başlatma zinciri sırası) ve Siyah Kapı #25 mantığı korundu — sadece retry katmanı eklendi.

## Doğrulama

### Kritik Akış Testleri
```
tests/critical_flows — 32 passed, 3 warnings in 2.56s
```

### Live Restart (`17:44:29`)
```
[GUARD] Baslangic temizligi baslatildi (PID 49116)
[GUARD] Onceki oturum PID dosyasi yok - temiz baslangic
[GUARD] Temizlik tamamlandi - hayalet process yok
Named Mutex olusturuldu (Global\USTAT_SINGLE_INSTANCE_v59)
Alt process baslatildi (PID 50544, parent=49116)
[APP] API baslatiliyor (uvicorn)...
[APP] API hazir (port 8000, 0.6sn)    ← Anayasa Kural 14 (≤5sn) OK
[APP] Electron baslatiliyor
[APP] Electron baslatildi (PID 50068)
HTTP 200 /api/health
```

### Build
```
npm run build → vite v6.4.1 → 728 modules transformed
dist/assets/index-NJupWGD_.js  880.31 kB (gzip 251.68 kB)
built in 2.58s
```

## Commit Serisi

| Commit | Dosya | Zone | Açıklama |
|--------|-------|------|----------|
| `0e7221d` | `tests/critical_flows/test_static_contracts.py` | Test | fail-first flow 13/14/15 |
| `8acecad` | `desktop/main.js` | Yellow C2 | `app.exit(42)` senkron çıkış |
| `97b334b` | `ustat_agent.py` | Green C1 | psutil `_kill_ustat_electrons` |
| `969ffd0` | `start_ustat.py` | Red C4 additive | exit 42 + ProcessGuard sweep + retry |

## Etki Analizi

- **Anayasa Kural 11** (başlatma zinciri sırası): Korundu — sadece ADDITIVE retry katmanı
- **Anayasa Kural 14** (startup performansı ≤5sn): Korundu (0.6sn ölçüldü)
- **Anayasa Kural 15** (MT5 launch sadece Electron): Dokunulmadı
- **Siyah Kapı #25** (`run_webview_process`): Mantık değişmedi, yeni davranış sadece `exit_code == 42` durumunda devreye giriyor
- **C4 sınıfı değişiklik için üçlü onay**: Kullanıcı onayı ("DEMİR GİBİ SAĞLAM") + kök neden kanıtı (electron.log) + fail-first test + live doğrulama

## Versiyon Durumu

Toplam değişim: 4 dosya, ~165 satır (ağırlıklı additive). Versiyon bump eşiği %10 altında → patch/minor bump gerekmedi. v5.9.0 içinde #151 numaralı madde olarak tarihçeye işlendi.

## Geri Alma Planı

```bash
git revert 969ffd0  # start_ustat.py patch
git revert 97b334b  # ustat_agent.py patch
git revert 8acecad  # main.js patch
git revert 0e7221d  # testler (opsiyonel)
```

Her commit bağımsız olarak geri alınabilir. Patch C'nin geri alınması sadece retry katmanını kaldırır, base davranışı bozmaz.
