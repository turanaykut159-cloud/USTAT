# Oturum Raporu — 29 Mart 2026

## Konu
Watchdog OTP Bekleme + Frameless Titlebar + BABA EXPIRY_DAYS Düzeltmesi

## Yapılan İş Özeti

Bu oturumda 3 bağımsız sorun çözüldü:

1. **Watchdog OTP Sorunu**: İlk açılışta kullanıcı MT5 OTP kodunu girerken watchdog eski heartbeat dosyasını stale bulup uygulamayı erken yeniden başlatıyordu. 30 saniye ilk bekleme süresi eklendi ve eski heartbeat temizleme mekanizması konuldu.

2. **Profesyonel Pencere Başlığı**: Windows varsayılan beyaz çerçevesi kaldırıldı, Electron frameless pencere + özel SVG pencere kontrol butonları (minimize/maximize/close) eklendi.

3. **BABA EXPIRY_DAYS=2→0**: #81'de kritik C4 bulgu olarak tespit edilen ancak sadece OĞUL tarafında düzeltilen vade kısıtlaması, BABA `detect_regime()` içinde de düzeltildi. Bu değişiklik olmadan vade sonuna 2 gün kala OLAY rejimi tetiklenip L2 kill-switch aktif oluyordu.

## Değişiklik Listesi

| Dosya | Bölge | Değişiklik |
|-------|-------|-----------|
| engine/baba.py | Kırmızı/Siyah Kapı | EXPIRY_DAYS=2→0 (satır 93) |
| start_ustat.py | Sarı | WATCHDOG_INITIAL_DELAY=30 + heartbeat temizleme |
| desktop/main.js | Sarı | frame:false + 4 IPC handler |
| desktop/preload.js | Yeşil | 4 IPC bridge |
| desktop/src/components/TopBar.jsx | Yeşil | SVG pencere kontrol butonları |
| desktop/src/styles/theme.css | Yeşil | Pencere kontrol CSS |
| desktop/index.html | Yeşil | title v5.8→v5.9 |
| docs/USTAT_v5_gelisim_tarihcesi.md | Dokümantasyon | #82 girişi eklendi |

## Teknik Detaylar

### Watchdog
- `WATCHDOG_INITIAL_DELAY = 30` sabiti (start_ustat.py satır 317)
- `watchdog_loop()` başında `engine.heartbeat` siliniyor (stale timestamp engelleniyor)
- 30sn sonra normal 15sn kontrol döngüsüne geçiş
- Mevcut sabitler korundu: WATCHDOG_STALE_SECS=45, WATCHDOG_CHECK_INTERVAL=15

### Frameless Pencere
- Electron `BrowserWindow`: `frame: false`
- IPC: `window:minimize`, `window:maximize`, `window:close`, `window:isMaximized`
- TopBar: useState + useEffect ile maximize state takibi
- CSS: close hover kırmızı (#e81123), `-webkit-app-region: no-drag`

### BABA EXPIRY_DAYS
- Konum: `engine/baba.py` satır 93, `detect_regime()` fonksiyonu içinde kullanılıyor
- Eski: `EXPIRY_DAYS: int = 2` → Yeni: `EXPIRY_DAYS: int = 0`
- Etki: Vade yakınlığından kaynaklanan OLAY rejimi artık tetiklenmeyecek

## Versiyon Durumu
- Mevcut: v5.9 (önceki oturumda yükseltilmişti)
- Değişiklik oranı: %0.23 — versiyon artışı gerekmez

## Commit
- Hash: da730b1
- Mesaj: `feat: watchdog OTP bekleme + frameless titlebar + BABA EXPIRY_DAYS düzeltmesi (#82)`

## Build Sonucu
`cd desktop && npm run build`: 0 hata (önceki oturumda doğrulandı)

## Bekleyen
- Uygulamanın yeniden başlatılması gerekiyor (EXPIRY_DAYS=0 değişikliği runtime'da aktif olsun ve L2 kill-switch temizlensin)
