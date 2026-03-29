# 29 Mart 2026 — Oturum Raporu #83 / #84

## Konu
Vade geçişi düzeltme + 10.000 stres testi + tam sistem doğrulama + event dedup + dosya organizasyonu

## Yapılan İşler

### 1. Vade Günü Top 5 Engeli Düzeltme
- **Sorun**: `top5_selection.py` satır 662-664'te `<=` operatörü vade günü (bdays=0) tüm sembolleri engelliyordu.
- **Çözüm**: `<=` → `<` operatörü. `0 < 0 = False` → vade günü artık açık.
- **Kural**: Vade-1 eski kontrat ile işlem, vade günü GCM geçiş → yeni kontrat ile işlem.
- **Doğrulama**: 3 aylık tablo (Mart/Nisan/Mayıs 2026), GCM/BIST tatil takvimi ile uyumlu.

### 2. Ajan Düzeltmeleri
- `ChangeServiceConfig()` parametre sırası düzeltildi (startType çakışması).
- `main()` çağrısı eklendi (normal mod çalışmıyordu).

### 3. ManualTrade MT5 Filtresi
- MT5 türündeki pozisyonlar Manuel Trade sayfasında görünür hale getirildi.

### 4. Settings.jsx Versiyon Güncelleme
- VERSION: 5.8 → 5.9
- BUILD_DATE: 2026-03-26 → 2026-03-29

### 5. Cache ve Build Temizliği
- Eski Python 3.10 `.pyc` dosyaları temizlendi.
- `npm run build` yeniden alındı — tüm bileşenler doğrulandı.

### 6. 10.000 Kombinasyonlu Stres Testi
- `tests/test_stress_10000.py` — 10.003 test, %100 PASSED, 7.94 saniye
- BABA, OĞUL, H-Engine, MT5 Bridge, Manuel Motor, Top5, Database, Entegrasyon

### 7. Tam Sistem Doğrulama
- 354 fonksiyon, 24 Siyah Kapı, 26 API endpoint, 4 motor, 11 sayfa — hepsi çalışıyor.

## Commitler
| Hash | Mesaj |
|------|-------|
| `ebab753` | fix: ajan main() çağrısı + ManualTrade MT5 pozisyon filtresi |
| `1d93ffd` | fix: vade günü Top 5 engeli kaldırıldı — <= yerine < operatörü |
| `a36f3d0` | test: 10.000 kombinasyonlu kapsamlı stres testi |
| `80468a2` | test: 10.003 test tamamlandı — eksik kombinasyonlar eklendi |
| `7bba799` | fix: Settings.jsx versiyon ve build tarihi güncellendi |

### 8. Event Deduplication (#84)
- **Sorun**: `insert_event()` hiçbir dedup yapmıyordu. Aynı EARLY_WARNING (Baker Hughes haberi) 3600+ kez DB'ye yazılmıştı.
- **Çözüm**: `dedup_seconds` parametresi eklendi (varsayılan=0, mevcut davranış korunur). 300sn dedup: EARLY_WARNING, DRAWDOWN_LIMIT, KILL_SWITCH, DATA_GAP.
- **Sonuç**: Günlük ~8640 → ~288 kayıt.

### 9. Gelişim Tarihçesi Profesyonel Format (#84)
- 3182 satır → 243 satır (Keep a Changelog standardı)
- Çift numaralar ve bozuk sıralama düzeltildi
- Başlıkta "nasıl tutulur" kılavuzu eklendi

### 10. Dosya Organizasyonu (#84)
- 6 rapor/doküman kökten → RAPORLAR/
- 4 oturum raporu RAPORLAR/ → docs/
- Kök dizin temizlendi

### 11. Simülasyon Testi (500 cycle)
- Tüm modüller çalıştı: BABA rejim algılama, OĞUL sinyal + işlem, H-Engine, ÜSTAT Brain
- İşlem açıldı (F_ASTOR SELL, F_AKSEN BUY), SL tetiklendi
- Rejim geçişleri: TREND → OLAY → RANGE (8 değişiklik)
- Sonuç: +42.16 TL (+0.35%)

## Commitler (ek)
| Hash | Mesaj |
|------|-------|
| `ddcb053` | fix: event deduplication — aynı uyarı 5dk tekrar yazmaz |
| `0927520` | docs: gelişim tarihçesi Keep a Changelog formatı |
| `7a2a749` | refactor: tarihçe yeniden adlandırma USTAT_GELISIM_TARIHCESI.md |
| `2b64dc7` | refactor: dosya organizasyonu — raporlar RAPORLAR/, raporlar docs/ |

## Versiyon
v5.9.0 — versiyon artışı gerekmedi (ana engine kodu değişmedi, çoğu test + fix).

## Build
`npm run build` — 0 hata, 2.31s
