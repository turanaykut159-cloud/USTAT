# OĞUL Evrensel Pozisyon Yönetim Sistemi — Session Raporu

**Tarih:** 2026-03-06
**Session:** Tasarım + Uygulama + Test

---

## Yapılan İş

Strateji bazlı pozisyon yönetimi (trend_follow, mean_reversion, breakout) kaldırılıp evrensel (universal) pozisyon yönetimi kuruldu. 8 fazlık plan hazırlanıp tamamı uygulandı.

---

## Mimari Değişiklikler

### 1. İki Döngü Mimarisi
- **Hızlı döngü (10sn):** Pozisyon yönetimi, risk kontrolü, trailing, breakeven, TP1
- **Sinyal döngüsü (M15 kapanış):** Yeni sinyal üretimi sadece M15 mum kapanışında
- `_is_new_m15_candle()` ile kontrol edilir

### 2. 4 Göstergeli Oylama Sistemi
Eski: RSI + EMA + MACD (3 gösterge, hepsi fiyat bazlı)
Yeni: RSI + EMA crossover + ATR genişleme + Hacim (4 gösterge, 4 farklı veri türü)
- 3/4 çoğunluk kuralı
- ATR ve Hacim yön-nötr onay göstergeleri (çoğunluk yönünü destekler)

### 3. Evrensel Pozisyon Yönetimi
Her FILLED pozisyon için (strateji fark etmez):
1. Peak profit takibi
2. Oylama bazlı çıkış (≤1/4 veya 3/4+ ters → kapat)
3. Hacim patlaması kontrolü (3x ort.)
4. Breakeven (likidite sınıfı: A:1xATR, B:1.3xATR, C:1.5xATR)
5. TP1 yarı kapanış (1.5xATR → yarı pozisyon kapat)
6. Trailing stop (EMA20 - ATRx sınıf çarpanı)
7. Geri çekilme toleransı (düşük:%20, normal:%30, yüksek:%40)
8. Maliyetlendirme (max 1 kez, 5 koşul)

### 4. Giriş Değişiklikleri
- Yarım lot giriş (0.5x) — ekleme payı bırakır
- Limit fiyat ofseti: kapanış - 0.25xATR

### 5. Gelişmiş Risk Kuralları
- Günlük %3 zarar stop
- Sembol bazlı ardışık 2 zarar → o sembol o gün kapalı
- Spread anomalisi (2x ort.) → kârdaysa kapat
- Yatay piyasa (8 mum < 0.5xATR) → kapat
- Son 45dk kâr kapanışı

---

## Feature Flag

```python
USE_UNIVERSAL_MANAGEMENT = True  # ogul.py üst kısım
```

- `True` → evrensel yönetim aktif (yeni sistem)
- `False` → eski strateji bazlı yönetim (anında geri dönüş)

---

## Değişen Dosyalar (11 dosya)

| Dosya | Değişiklik Türü |
|---|---|
| engine/models/trade.py | 8 yeni alan |
| engine/database.py | _migrate_schema() |
| engine/mt5_bridge.py | close_position_partial() |
| engine/ogul.py | ~50 sabit + 8 metot + döngü yeniden yazım |
| api/schemas.py | PositionItem 5 yeni alan |
| api/routes/positions.py | _universal_fields() helper |
| api/routes/live.py | WebSocket evrensel alanlar |
| desktop/src/components/OpenPositions.jsx | Yönetim sütunu |
| desktop/src/styles/theme.css | Badge stilleri |
| docs/USTAT_v5_gelisim_tarihcesi.md | #13 kayıt |
| docs/2026-03-06_evrensel_yonetim_talimatlar.md | Bu dosya |

---

## Doğrulama

- 7/7 Python dosyası syntax hatasız (py_compile)
- Trade model yeni alanlar default değerlerle doğru
- PositionItem oluşturma/serializasyon OK
- ogul.py: 19 sabit, 8 metot, feature flag, iki döngü, restore alanları doğrulandı

---

## Sıradaki Adımlar

1. **Paper trading:** USE_UNIVERSAL_MANAGEMENT=True, küçük lot (0.1)
2. **Events DB kontrolü:** breakeven, TP1, trailing, oylama çıkışı, maliyetlendirme logları
3. **5 işlem günü stabil** → eski metotları sil
4. **MT5 build 5200+** → native_sltp aktif et (ayrı konu)

---

## Dikkat Edilecekler

- `_calculate_voting()` ATR genişleme ve hacim yön-nötr → çoğunluk yönünü destekler, kararsız piyasada NOTR döner
- `close_position_partial()` lot step rounding yapıyor — farklı semboller farklı lot step olabilir
- `_check_cost_average()` market order gönderiyor — slippage riski var ama maliyetlendirme zaten düşük hacimle yapılır
- `restore_active_trades()` evrensel alanları DB'den kurtarır — engine restart sonrası tp1_hit, breakeven_hit vb. korunur
