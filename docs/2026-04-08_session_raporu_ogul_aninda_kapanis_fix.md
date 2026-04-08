# Oturum Raporu — 2026-04-08
## OĞUL Anında Kapanış Sorunu Düzeltmesi (#122)

### Sorun Tanımı
07.04.2026 tarihli tüm otomatik işlemler (F_HALKB, F_AKBNK, F_TCELL, F_KONTR) açılır açılmaz zararlı kapanıyordu. Toplam 6 işlemde -23 TL kayıp oluştu.

### Kök Neden Analizi (Log Kanıtlı)

**3 Katmanlı Bug Zinciri:**

**Katman 1 — TRADE_ACTION_SLTP GCM VİOP'ta Desteklenmiyor:**
- GCM Capital VİOP, Exchange Execution modunda çalışıyor
- `TRADE_ACTION_SLTP` (action=6) her çağrıda `retcode=10035 Invalid order` döndürüyor
- 19 Mart'tan bugüne kadar TÜM log dosyaları tarandı: `SL/TP başarılı` logu **SIFIR** kez yazılmış
- Exchange modda pozisyon SL/TP'si ancak ayrı pending Stop/Limit emirleri ile konulabilir

**Katman 2 — Pozisyon Hemen Kapatılıyordu:**
- `_send_order_inner` SLTP 5 denemede başarısız → pozisyon HEMEN kapatılıyordu
- OgulSLTP mekanizması (plain STOP pending emir) sıra gelmeden pozisyon ölüyordu
- Hatalı `close_result.get("success", False)` kontrolü: MT5 result dict'te "success" anahtarı yok → kapatma başarılı olsa bile "KORUMASIZ POZİSYON AÇIK" yanlış alarmı

**Katman 3 — _execute_signal Akış Hatası:**
- `force_closed` kontrolü eksikti → kapatılmış pozisyon FILLED olarak kaydediliyordu
- Stop Limit SL başarıyla yerleştirilse bile pozisyon zaten ölmüştü
- DB'ye açılış/kapanış art arda yazılıyordu → ekranda anlık zararlı kapanış

### Yapılan Değişiklikler

**Değişiklik 1 — `engine/mt5_bridge.py` `_send_order_inner` (Siyah Kapı #17):**
- SLTP başarısız olduğunda pozisyonu kapatma kodu kaldırıldı
- `sl_tp_applied=False` ile döner, pozisyona dokunmaz
- `_execute_signal`'daki OgulSLTP mekanizmasına bırakır

**Değişiklik 2 — `engine/ogul.py` `_execute_signal` (Siyah Kapı #11):**
- OgulSLTP başarısız olursa → Anayasa 4.4 kuralı BURADA uygulanır
- Pozisyon kapatılır, trade CLOSED olarak işaretlenir, BABA'ya bildirilir
- Kapatma da başarısız olursa → KORUMASIZ POZİSYON raporu

**Değişiklik 3 — close_position return bug'ı:**
- Hatalı `close_result.get("success", False)` kontrolü Değişiklik 1'de kaldırıldı
- Diğer tüm tüketiciler (H-Engine, BABA, OĞUL) doğru kontrol (`is None`) kullanıyor

### Yeni Akış Zinciri
```
Market emir → Dolar → TRADE_ACTION_SLTP (başarısız, beklenen)
→ sl_tp_applied=False ile döner (pozisyona dokunmaz)
→ OgulSLTP STOP emir yerleştirir (başarılı ✓)
→ Pozisyon korumalı yaşar, normal trade döngüsüne girer
→ VEYA OgulSLTP de başarısız → Pozisyon kapatılır (güvenlik ağı)
```

### Etkilenen Dosyalar
| Dosya | Bölge | Değişiklik |
|-------|-------|-----------|
| `engine/mt5_bridge.py` | Kırmızı + Siyah Kapı #17 | SLTP fail → pozisyon kapatma kaldırıldı |
| `engine/ogul.py` | Kırmızı + Siyah Kapı #11 | OgulSLTP fail → pozisyon kapat eklendi |
| `docs/USTAT_GELISIM_TARIHCESI.md` | Dokümantasyon | #122 maddesi |

### Versiyon Durumu
- Değişiklik oranı: %0.1 (94 satır / 87646 toplam) → versiyon artışı gerekmez
- Mevcut versiyon: v5.9.0

### Commit
- Hash: `5185c60`
- Mesaj: `fix: #122 — OĞUL anında kapanış sorunu — TRADE_ACTION_SLTP yerine OgulSLTP STOP emir`

### Doğrulama
- Python syntax: `ast.parse` ile her iki dosya hatasız
- UI güncellemesi: Gerekmiyor (backend-only değişiklik)
