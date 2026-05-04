# KARAR #18 — OĞUL Aktivasyon Paketi
**Tarih:** 4 Mayıs 2026  
**Sınıf:** C4 — Kırmızı Bölge + Siyah Kapı  
**Onay:** Kullanıcı (TURAN AYKUT) — yazılı onay alındı  
**Kapsam:** `engine/ogul.py` + `config/default.json` + `tests/critical_flows`

---

## 1. Sorunun Tespiti

OĞUL motorunun veritabanı geçmişine bakıldığında 5 ay 22 günde **6 otomatik işlem** açıldığı görüldü (hepsi 2026-04-07 günü, hepsi `trend_follow`, toplam −23 TL).

`engine/ogul.py:1665` `_execute_signal` fonksiyonunda **KARAR #17 hard-block** mevcuttu — `strategy_name == "trend_follow"` koşuluyla TÜM trend_follow sinyalleri reddediliyordu. Aynı zamanda `config/default.json`'da `adx_threshold: 9999.0` ile sinyal üretimi de pratik olarak imkansız kılınmıştı.

### Kritik bulgu — kaskad etki

`_generate_signal` candidate listesini strength'e göre sıralıyor; SE3 motoru genellikle trend_follow candidate üretip listenin başına oturuyor. `_generate_signal` ilk uygun candidate'ı döndürüyor. `_execute_signal` trend_follow'u reddedince, **mean_reversion adayına SIRA HİÇ GELMİYORDU.** Bu yüzden `mean_reversion` ve `breakout` 5 ayda 0 kez tetiklendi.

## 2. Backtest (28 gün × 15 sembol × M5)

Komisyon + slippage = 0.15 ATR/trade dahil edilerek:

| Strateji + Parametre | Trade | /gün | WR% | Asim | E[ATR] | PF |
|---|---|---|---|---|---|---|
| **mean_reversion default** | 33 | 1.6 | **81.8** | 0.18 | **+1.673** | **24.5** |
| trend_follow varsayılan | 384 | 18.3 | 44.5 | 0.89 | -0.090 | 0.90 |
| trend_follow ADX≥32 (tahmin) | düşük | düşük | tahmini >50 | <0.7 | >0 | tahmini >1.2 |
| breakout (tüm varyantlar) | — | — | 41-44 | ~0.85 | **negatif** | <1 |

**Sonuç:** mean_reversion altın stratejidir (varsayılan parametreler korunmalı). trend_follow ADX≥32 filtresiyle pozitif edge potansiyeli. breakout şu an çalışmıyor.

## 3. Uygulanan Değişiklikler (7 cerrahi)

### config/default.json — `strategies` bloğu
- `trend_follow.adx_threshold`: 9999.0 → **25.0** (KARAR #17 geri alındı)
- `trend_follow.adx_min_trade`: **YENİ 32.0** (KARAR #18 ek filtre)
- `trend_follow.sl_atr_mult`: 1.5 → **1.2** (asimetri iyileştirme)
- `trend_follow.tp_atr_mult`: 2.0 → **2.5** (R:R artırma)
- `trend_follow.max_trades_per_day`: **YENİ 5**
- `trend_follow.daily_loss_pct_limit`: **YENİ 0.5%**
- `trend_follow._decision_history`: KARAR #17 + KARAR #18 tarihçesi
- `breakout._enabled`: **YENİ false** (hibernate)
- `breakout._decision_history`: backtest gerekçesi

### engine/ogul.py — 7 değişiklik

1. `TF_SL_ATR_MULT` default: 1.5 → 1.2 (config override edilebilir)
2. `TF_TP_ATR_MULT` default: 2.0 → 2.5
3. `__init__` state: `_tf_trade_count_today`, `_tf_trade_count_date` eklendi
4. `process_signals` günlük sıfırlama: TF sayacı yeni günde 0'a döner
5. `_generate_signal` candidate döngüsünde **trend_follow ADX guard** + **günlük 5 trade limiti** (Bu ana değişiklik — mean_reversion'a sıra gelmesini sağlar)
6. `_execute_signal` KARAR #17 hard-block KALDIRILDI (yorum tarihçe için kalıyor)
7. `process_signals` strateji döngüsünde breakout `_enabled=False` ise atlama

### tests/critical_flows/test_karar_18_contracts.py — 10 statik test
- C1-C10: trend_follow ADX guard, günlük cap, KARAR #17 kaldırıldı, mean_reversion korundu, breakout flag, config anahtarları, tarihçe yorumu, defaults, reset

**Tüm 10 test yeşil.**

## 4. Anayasa Pre-Flight Checklist

- [x] Değişiklik sınıfı: **C4** (Siyah Kapı `_execute_signal` + Kırmızı Bölge `engine/ogul.py`)
- [x] Etki analizi: trend_follow akışı, mean_reversion akışı, breakout akışı, config bağımlılık zinciri
- [x] Geri alma planı: `git revert <commit>` + `default.json.bak` + `ogul.py.bak` yedekleri
- [x] Test sözleşmeleri: 10 yeni statik test + 37 mevcut test yeşil
- [x] Config'den parametre: tüm yeni değerler config anahtarlarına bağlı
- [x] Kullanıcı onayı: alındı (paket onayı)
- [ ] **Build + paper mode sanity:** kullanıcı makinesinde Salı yapılacak

## 5. Beklenen Davranış (Salı Paper Mode)

- mean_reversion günde 1-2 sinyal üretmeli (varsayılan parametreler altında)
- trend_follow ADX≥32 koşulunda günde 0-2 sinyal (TREND rejiminde)
- breakout 0 sinyal (hibernate)
- Toplam günlük: 1-4 paper sinyal beklenir

Eğer Salı paper mode'da mean_reversion HALA hiç tetiklenmiyorsa, kök sebep:
- Top 5 selection süzgeci (mean_reversion'ın istediği semboller dışarıda kalıyor)
- M5 candle close timing yarış koşulu
- `_calculate_voting` fonksiyonunda gizli filtre

Bu durumda 2. tur araştırma gerekir.

## 6. Sonraki Adım — Salı Sabah

1. Kullanıcı: `npm run build` (Windows, desktop)
2. Kullanıcı: `paper_mode=True` ile engine başlat
3. Kullanıcı: 2-3 saat paper sinyal logu izler
4. Sinyal sayısı 0-1 arası ise → derin araştırma; 2-5 arası ise → live mikro-lot ön hazırlık

---

**Yazan:** Claude (Cowork session)  
**Onaylayan:** TURAN AYKUT
