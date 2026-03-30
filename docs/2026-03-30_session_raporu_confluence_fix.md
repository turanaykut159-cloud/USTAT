# Oturum Raporu — 2026-03-30 Confluence Strateji-Bazlı Skorlama

**Tarih:** 30 Mart 2026 (Pazar — Barış Zamanı)
**Versiyon:** v5.9.0 (değişmedi)
**Kapsam:** Confluence fix (#88), PrimnetDetail fix (#89), kalan düzeltmeler

---

## 1. Problem Tanımı

OĞUL 30 Mart 2026 seansında 184 sinyal üretti ancak hiçbiri confluence eşiğini geçemedi — 0 işlem açıldı. F_AKSEN kontratı +7.11% yaparak tavana kilitlenmesine rağmen, confluence skoru 49/50 ile reddedildi.

**Kök Sebep:** `calculate_confluence()` fonksiyonu strateji tipini bilmiyor. Trend follow ve breakout stratejilerine mean reversion mantığı uyguluyordu:
- RSI > 70 → -3 ceza (güçlü momentum = kötü diyordu)
- Dirence yakınlık → -10 ceza (breakout fırsatını cezalandırıyordu)
- Pattern bileşeni %88 sıfır (10 ölü puan)

## 2. Yapılan Değişiklikler

### Commit 0a89274 — Confluence Strateji-Bazlı Skorlama (#88)
**Dosyalar:** `engine/utils/price_action.py`, `engine/ogul.py`
**Sınıf:** C3 (Kırmızı Bölge — ogul.py tek satır ekleme)

Değişiklikler:
- `calculate_confluence()` → `strategy_type` parametresi eklendi (varsayılan boş string, geriye uyumlu)
- **RSI skorlama:**
  - trend_follow / breakout + RSI > 70 → +5 puan (eskisi: -3 ceza)
  - mean_reversion → aynen korunuyor (-3 ceza)
- **Seviye yakınlığı:**
  - breakout + dirence yakın → +5 puan (eskisi: -10 ceza)
  - trend_follow + dirence yakın → -5 ceza (eskisi: -10)
  - mean_reversion → aynen korunuyor (-10 ceza)
- ogul.py → `candidate.strategy.value` confluence çağrısına eklendi (tek satır)

**F_AKSEN tahmini etki:** Skor 49 → ~57-62 arası. TREND rejimi eşiği 40 → geçerdi.

### Commit 9c532d8 — PrimnetDetail + Theme CSS (#89)
**Dosyalar:** `desktop/src/components/PrimnetDetail.jsx`, `desktop/src/styles/theme.css`
**Sınıf:** C1 (Yeşil Bölge)

- PrimnetDetail.jsx: `buildExplanation()` Faz 2 satırları düzeltildi
- theme.css: PRİMNET modal stilleri iyileştirildi
- Desktop build başarılı (0 hata)

### Commit 4170f3c — Kalan Düzeltmeler
**Dosyalar:** `engine/h_engine.py`, `engine/mt5_bridge.py`, `tests/test_news_100_combinations.py`

- h_engine.py: PRİMNET referans fiyat alındığında `hp.reference_price` güncelleniyor
- mt5_bridge.py: SymbolInfo'ya `session_price_limit_max/min` (tavan/taban) eklendi
- test: pytest import + TestHarness fixture eklendi

## 3. Korunmayan / Değişmeyen

- `CONFLUENCE_THRESHOLDS` ve rejim eşikleri aynen
- `CONFLUENCE_PASS_SCORE = 50.0` (ogul.py) aynen
- Mean reversion mantığı tamamen korunuyor
- Siyah Kapı fonksiyonları dokunulmadı
- Çağrı sırası değişmedi

## 4. Geri Alma

```bash
git revert 0a89274 --no-edit  # Confluence fix
git revert 9c532d8 --no-edit  # PrimnetDetail
git revert 4170f3c --no-edit  # Kalan düzeltmeler
```

## 5. Build Durumu

- Desktop build: BAŞARILI (0 hata, 7.21s)
- Versiyon: v5.9.0 (değişmedi, eşik altında)

## 6. Commit Özeti

| Commit | Hash | Açıklama |
|--------|------|----------|
| 1 | `0a89274` | Confluence strateji-bazlı skorlama (#88) |
| 2 | `9c532d8` | PrimnetDetail Faz 2 + theme.css (#89) |
| 3 | `4170f3c` | PRİMNET ref fiyat + SymbolInfo tavan/taban + test fixture |
