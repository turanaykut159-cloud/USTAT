# Session Raporu — 2026-03-09 (Manuel/Hibrit Bug Fix + Risk Baseline)

## Yapilan Is

**Iki ana gorev tamamlandi:**

### 1. Manuel/Hibrit Transfer Bug Fix (3 duzeltme)

Kullanici bug raporu: "Manuel islem actim hibrite devreder etmez kapatti" ve "Manuel islemde islem yokken ayni kontratta islem acamazsiniz uyarisi veriyor."

**Kok neden analizi:**
- Ghost entry: `h_engine.transfer_to_hybrid()` basarili olunca `ManuelMotor.active_trades`'den sembolu silmiyordu
- Anlik kapanma: `check_transfer()` SL hesapladiktan sonra guncel fiyatin zaten SL'yi ihlal edip etmedigini kontrol etmiyordu
- sync_positions: Symbol-based karsilastirma, hibrite devredilen ayni sembolun MT5'te kalmasindan dolayi ghost entry'yi temizleyemiyordu

**Duzeltmeler:**
- Fix A: `transfer_to_hybrid()` sonrasi `ManuelMotor.active_trades.pop(symbol)` eklendi
- Fix A2: `sync_positions()` FILLED kontrolu ticket-based yapildi
- Fix B: `check_transfer()` 10. adim — fiyat vs SL ihlal kontrolu eklendi
- Cross-motor ref: `h_engine.manuel_motor` referansi eklendi (Engine.__init__)

### 2. Risk Baseline Date Ayar Karti

Kullanici istegi: "Ayarlara babanin risk hesaplarini yaptigi tarih baslangicini duzeltebilecegimiz bir kart ekleyelim."

**Uygulama:**
- Backend: Config.set() + Config.save() metotlari, GET/POST /settings/risk-baseline API
- Frontend: Settings sayfasina "Risk Hesaplama Baslangici" karti (tarih input + iki asamali dogrulama)
- Runtime: Baba._risk_baseline_date ve modul sabiti RISK_BASELINE_DATE otomatik guncellenir

## Degisiklik Ozeti

| Dosya | Islem | Detay |
|-------|-------|-------|
| engine/h_engine.py | DUZENLEME | Ghost entry fix + SL kontrolu + manuel_motor ref |
| engine/manuel_motor.py | DUZENLEME | Ticket-based sync |
| engine/main.py | DUZENLEME | h_engine.manuel_motor cross-ref |
| engine/config.py | DUZENLEME | set() ve save() metotlari |
| api/routes/settings.py | YENI | Risk baseline GET/POST endpoint |
| api/schemas.py | DUZENLEME | 3 yeni schema |
| api/server.py | DUZENLEME | Settings router eklendi |
| desktop/src/services/api.js | DUZENLEME | getRiskBaseline, updateRiskBaseline |
| desktop/src/components/Settings.jsx | DUZENLEME | Baseline karti + state + handlers |
| desktop/src/styles/theme.css | DUZENLEME | Baseline CSS kurallari |
| docs/USTAT_v5_gelisim_tarihcesi.md | GUNCELLEME | #37 eklendi |
| docs/islem_sonu_yapilacaklar.md | YENI | Islemi bitir checklist |

**Toplam:** 558 ekleme, 20 silme (12 dosya)

## Teknik Detaylar

### Ghost Entry Fix Akisi
1. Kullanici Manuel'den islem acar -> ManuelMotor.active_trades[symbol] = trade
2. Kullanici hibrite devret -> h_engine.transfer_to_hybrid(ticket) basarili
3. **YENI:** transfer_to_hybrid() icerisinde ManuelMotor.active_trades.pop(symbol) cagirilir
4. Kullanici ayni sembolde yeni manuel islem acabilir (ghost entry yok)

### Fiyat vs SL Kontrolu
- check_transfer() 10. adim olarak eklendi
- BUY: current_price <= suggested_sl ise devir reddedilir
- SELL: current_price >= suggested_sl ise devir reddedilir
- Boylece devir aninda SL ihlali olan pozisyon hibrite alinmaz

### Risk Baseline Karti
- Iki asamali dogrulama: "Tarihi Guncelle" -> uyari mesaji -> "Onayla ve Uygula" / "Iptal"
- Backend: config/default.json + Baba runtime guncelleme
- Tarih validasyonu: YYYY-MM-DD format, gecersiz tarih, gelecek tarih kontrolu

## Versiyon Durumu

- Kumulatif degisiklik orani (v5.2 commit cd7eda9'dan bu yana): %15.1 (4.703 satir / 31.116 toplam)
- Esik: %10 -> VERSIYON YUKSELTME YAPILDI: v5.2 -> v5.3
- 26 dosyada versiyon referanslari guncellendi

## Commit'ler

1. Hash: f24816a — fix: Manuel/Hibrit transfer bug fix + Risk Baseline ayar karti
2. Hash: 09eb1dc — feat: versiyon yukseltme v5.2 -> v5.3

## Build

- npm run build -> BASARILI (0 hata, 2.43sn, ustat-desktop@5.3.0)
