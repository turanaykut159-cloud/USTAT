# Oturum Raporu — 6 Nisan 2026

## Konu: Hayalet Process/Port/Socket Koruma Sistemi

## Özet

ÜSTAT uygulaması kapatıldığında ("güvenli kapat") arka planda kalan zombie process'ler, portlar ve socket'ler sorunu çözüldü. İki katmanlı savunma sistemi kuruldu:

- **Katman 1:** Graceful shutdown zinciri güçlendirildi (WebSocket close → Engine stop → MT5 disconnect → uvicorn socket close)
- **Katman 2:** ProcessGuard modülü ile OS-level zorla temizlik (PID registry, tree-kill, orphan tespiti)

## Değişiklik Listesi

| # | Dosya | Bölge | Değişiklik |
|---|-------|-------|-----------|
| 1 | `engine/process_guard.py` | YENİ (Yeşil) | Hayalet process koruma modülü — PID registry, tree-kill, orphan Electron/MT5 tespiti, port/socket temizliği |
| 2 | `start_ustat.py` | Sarı | api.pid yazımı, _shutdown_api() timeout 20→45sn, çift çağrı koruması, Electron tree-kill subprocess'ten bağımsız |
| 3 | `api/routes/live.py` | Yeşil | shutdown_all_connections() — tüm WebSocket bağlantılarını graceful kapatır |
| 4 | `api/server.py` | Sarı | Lifespan shutdown sırası: WebSocket → Engine → api.pid temizle |
| 5 | `docs/USTAT_GELISIM_TARIHCESI.md` | C0 | #112-116 maddeleri eklendi |

## Teknik Detaylar

### ProcessGuard Mimarisi (engine/process_guard.py)

Üç aşamalı koruma:

1. **startup_cleanup()** — 5 katmanlı başlangıç temizliği:
   - PID registry dosyasından eski PID'leri oku → tree-kill
   - Port 8000'de LISTENING orphan process'i öldür
   - Orphan Electron process'leri (wmic/PowerShell) bul → öldür
   - Orphan MT5-Python process'leri bul → öldür
   - TIME_WAIT socket sayısını raporla (OS otomatik temizler)

2. **register_pid()** — Çalışma sırasında PID kayıt:
   - .ustat_pids.json dosyasına atomic yazım
   - Ana process, subprocess, Electron PID'leri ayrı ayrı kaydedilir
   - Multiprocessing bellek izolasyonu sorunu dosya tabanlı iletişimle çözüldü

3. **shutdown_all()** — Kapanış temizliği:
   - Electron → Subprocess → Port listener → ESTABLISHED bağlantılar sırasıyla öldürülür
   - api.pid dosyası temizlenir
   - PID registry dosyası silinir

### Kapanış Zinciri (Tam Akış)

```
Electron close / Tray Çıkış
  → _shutdown_api() [uvicorn.should_exit = True, 45sn timeout]
    → FastAPI lifespan shutdown:
      1. shutdown_all_connections() — WebSocket'ler kapatılır
      2. engine.stop() — pozisyonlar kapatılır, MT5 disconnect, DB close
      3. api.pid temizlenir
  → ProcessGuard.shutdown_all() — kalan PID'ler + ESTABLISHED bağlantılar
  → Port temizliği (garanti katmanı)
  → Mutex + lock file temizliği
```

### Düzeltilen Hatalar

| Hata | Açıklama | Çözüm |
|------|----------|-------|
| _shutdown_api() timeout | 20sn idi, engine.stop() 30sn sürebilir → kesiyordu | 45sn'ye artırıldı |
| _shutdown_api() çift çağrı | atexit + explicit çağrı aynı anda tetikleniyordu | Boolean guard eklendi |
| Electron tree-kill atlanması | subprocess ölü ise Electron kill atlanıyordu | Subprocess durumundan bağımsız hale getirildi |
| WebSocket cleanup yoktu | Kapanışta WS bağlantıları açık kalıyordu → TIME_WAIT birikimi | shutdown_all_connections() eklendi |
| api.pid hiç yazılmıyordu | Electron killApiProcess() boşa okuyordu | run_webview_process'te port açılınca yazılıyor |
| Electron PID erişilemiyordu | Alt process'te kayıt, ana process'te okunamıyordu | Dosya tabanlı PID iletişimi |

### Tespit Edilen Ek Sorun (Düzeltilmedi — Ayrı Oturum)

MT5 logunda tespit edilen `failed modify` sonsuz döngüsü:
- ogul.py `_mode_protect`, `_mode_trend`, `_mode_defend` fonksiyonlarında failure counter YOK
- modify_position() başarısız olunca trade.sl güncellenmez → koşul her 10sn tekrarlanır
- Her döngüde 5 × dahili retry = dakikada 30 başarısız MT5 API çağrısı
- Kök sebep: Bu üç fonksiyona `_modify_fail_count` + cooldown eklenmeli

## Versiyon Durumu

- Mevcut: v5.9.0 (değişiklik oranı %1.4 — versiyon artışı gerekmedi)
- Commit: `ea40986`
- Build: Gerekmedi (sadece backend değişiklikleri)
