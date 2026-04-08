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

## Derin Tarama — Ek Açıklar (#129)

İlk koruma sonrası yapılan kapsamlı taramada 3 ek açık tespit edildi ve kapatıldı:

| Açık | Dosya | Risk | Çözüm |
|---|---|---|---|
| #1 KRİTİK | `api/routes/mt5_verify.py` _verify() | mt5.initialize() doğrudan çağrılıyordu — MT5 otomatik açabilirdi | terminal64.exe process kontrolü eklendi |
| #2 DÜŞÜK | `health_check.py` | mt5.initialize() doğrudan çağrılıyordu | Process kontrolü + uyarı eklendi (zaten sadece manuel çalıştırılır) |
| #3 DÜŞÜK | `start_ustat.py` UstatWindowApi | Ölü pywebview kodu launch_mt5() hâlâ dosyada | Ölü kod uyarısı + "yeniden aktive etmek YASAK" notu eklendi |

## Tarama Kapsamı

11 vektör tarandı:
1. Tüm .py dosyalarında mt5.initialize() çağrıları
2. Tüm .py dosyalarında connect(launch=True) çağrıları
3. MT5Bridge.__init__ constructor davranışı
4. _safe_call() reconnect mekanizması
5. lifespan() Engine oluşturma sırası
6. ustat_agent.py MT5 komutları
7. start_ustat.py / restart_all.bat gizli çağrılar
8. simulation.py / backtest.py MT5 bağlantısı
9. data_pipeline.py / health.py import-time davranışı
10. Electron/JS tarafı zamanlama
11. Engine crash watchdog davranışı

## Değişen Dosyalar

| Dosya | Bölge | Değişiklik |
|---|---|---|
| `engine/mt5_bridge.py` | Kırmızı + Siyah Kapı | Process kontrol bloğu güçlendirildi, except→return False |
| `engine/main.py` | Kırmızı | _connect_mt5() docstring güçlendirildi |
| `api/routes/mt5_verify.py` | API | _verify() fonksiyonuna process kontrolü eklendi |
| `health_check.py` | Script | mt5.initialize() öncesi process kontrolü eklendi |
| `start_ustat.py` | Kırmızı | Ölü UstatWindowApi sınıfına uyarı eklendi |
| `CLAUDE.md` | Dokümantasyon | Siyah Kapı #31, Kural #15, Başlama Zinciri güncellendi |
| `USTAT_ANAYASA.md` | Anayasa | Siyah Kapı #31, Kural 4.15, Değişiklik Geçmişi #3 |
| `docs/USTAT_GELISIM_TARIHCESI.md` | Dokümantasyon | #128 + #129 maddeleri |
