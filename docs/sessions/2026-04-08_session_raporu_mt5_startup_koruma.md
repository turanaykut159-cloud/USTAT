# Oturum Raporu — MT5 Startup Koruma

**Tarih:** 2026-04-08
**Konu:** MT5 auto-launch bug fix + Anayasa koruma güncellemesi
**Sınıf:** C4 (Siyah Kapı) + C3 (Kırmızı Bölge)

---

## Yapılan İş Özeti

MT5 terminal, uygulama açıldığında kullanıcı müdahalesi olmadan otomatik başlıyordu. Doğru akış: ÜSTAT açılır → LockScreen → Electron launchMT5() → OTP → Dashboard. Bug fix yapıldı ve yapı Anayasa koruması altına alındı.

## Kök Neden

Python MetaTrader5 kütüphanesi, `mt5.initialize()` çağrıldığında path verilmese bile Windows registry'den MT5 yolunu bulup `terminal64.exe`'yi otomatik başlatıyor. Engine'in `_connect_mt5()` → `connect(launch=False)` çağrısı bu davranışı tetikliyordu.

## Çözüm

`mt5_bridge.py connect()` fonksiyonuna `launch=False` modunda `mt5.initialize()` çağrılmadan ÖNCE `terminal64.exe` process kontrolü eklendi. Process çalışmıyorsa bağlantı atlanır — initialize() asla çağrılmaz.

## Test Sonucu

10/10 açma-kapama testi temiz geçti. Her açılışta Engine logda:
```
MT5 process bulunamadı — launch=False, bağlantı atlanıyor.
```
MT5 bir kez bile kendiliğinden açılmadı.

## Koruma Güncellemeleri

| Güncelleme | Dosya | Detay |
|---|---|---|
| Siyah Kapı #31 | CLAUDE.md, USTAT_ANAYASA.md | `connect()` fonksiyonu Siyah Kapı listesine eklendi |
| Anayasa Kural 4.15 | USTAT_ANAYASA.md | MT5 Başlatma Sorumluluğu Kuralı eklendi |
| Değiştirilemez Kural #15 | CLAUDE.md | MT5 Başlatma Sorumluluğu kuralı eklendi |
| Kod koruması | engine/mt5_bridge.py | Siyah Kapı başlık bloğu + except→return False güçlendirmesi |
| Docstring koruması | engine/main.py | _connect_mt5() Anayasa referanslı uyarı kutusu |
| Başlama zinciri | CLAUDE.md | Bölüm 1.6 detaylı MT5 process kontrol akışı eklendi |
| Değişiklik geçmişi | USTAT_ANAYASA.md | #3 kayıt (v2.1) eklendi |
| Gelişim tarihçesi | USTAT_GELISIM_TARIHCESI.md | #128 maddesi eklendi |

## Değişen Dosyalar

| Dosya | Bölge | Değişiklik |
|---|---|---|
| `engine/mt5_bridge.py` | Kırmızı + Siyah Kapı | Process kontrol bloğu güçlendirildi, except→return False |
| `engine/main.py` | Kırmızı | _connect_mt5() docstring güçlendirildi |
| `CLAUDE.md` | Dokümantasyon | Siyah Kapı #31, Kural #15, Başlama Zinciri güncellendi |
| `USTAT_ANAYASA.md` | Anayasa | Siyah Kapı #31, Kural 4.15, Değişiklik Geçmişi #3 |
| `docs/USTAT_GELISIM_TARIHCESI.md` | Dokümantasyon | #128 maddesi |
