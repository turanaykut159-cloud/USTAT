# Oturum Raporu — B8: Otomatik Pozisyon Özeti + Hibrit Scratch Görünürlüğü

**Tarih:** 11 Nisan 2026
**Kategori:** Widget Denetimi — Orta/Yüksek kritiklik (B8)
**Sınıf:** C3 (Kırmızı Bölge — `engine/database.py` additive)
**Kapsam:** 1 Kırmızı Bölge dosyası (additive), 4 frontend/test dosyası, 1 changelog
**Durum:** Tamamlandı — atomik commit hazır

---

## 1. Sorun Tanımı

`docs/2026-04-11_widget_denetimi.md` raporundaki **B8** maddesi iki ayrı bulguyu birleştiriyordu:

1. **AutoTrading.jsx — Otomatik Pozisyon Özeti (sağ kart):**
   Kart, sol bölümle aynı listeyi (açık otomatik pozisyonlar) tekrar çiziyordu.
   Kullanıcıya yeni bir bilgi sunmuyordu — sessiz duplicate.

2. **HybridTrade.jsx + database.py — Sayısal tutarsızlık:**
   `get_hybrid_performance()` `total = winners + losers` varsayımıyla yazılmıştı,
   ancak `pnl == 0` ile kapanan işlemler (manuel kapanış, breakeven, dış kapanış)
   ne `winners` ne `losers` sayısına giriyordu. UI `total = 45` gösterirken
   `winners + losers = 31` gözlendi → 14 işlem nereye gittiği belirsizdi.

---

## 2. Kök Sebep

### 2a) AutoTrading sağ kart
`AutoTrading.jsx` içinde sağdaki kart şu kalıbı kullanıyordu:

```jsx
<div className="auto-card">
  <h3>Otomatik Pozisyon Özeti</h3>
  {autoPositions.map(...)}  {/* Soldaki ile birebir aynı liste */}
</div>
```

Sol bölümdeki "Otomatik Pozisyonlar" kartıyla içerik kesişimi %100; ekran alanını
boş yere işgal eden cosmetic duplicate.

### 2b) get_hybrid_performance scratch atlaması
`engine/database.py`:

```python
winners = sum(1 for p in pnls if p > 0)
losers  = sum(1 for p in pnls if p < 0)
return {"total": total, "winners": winners, "losers": losers, ...}
```

`pnl == 0` durumu hiçbir alana yazılmıyor. `total - (winners + losers) > 0`
olması beklenebileceği halde frontend bu farkı hiçbir yerde göstermiyordu.

---

## 3. Çözüm

### 3a) `engine/database.py` (Kırmızı Bölge — additive)
`get_hybrid_performance()` artık `scratches` alanını döndürür ve invariant
`total == winners + losers + scratches` her dönüşte garanti edilir. Eski alanlar
korunur, yeni alan eklenir → backward compatible.

```python
total = len(rows)
winners = sum(1 for p in pnls if p > 0)
losers  = sum(1 for p in pnls if p < 0)
# B8: scratch = pnl == 0 kapanışlar (manuel/break-even/external)
scratches = total - winners - losers
return {
    "total": total,
    "winners": winners,
    "losers": losers,
    "scratches": scratches,  # B8: invariant
    ...
}
```

**Anayasa uyumu:** `engine/database.py` Kırmızı Bölge #6'dır. İzin verilen
müdahale: additive alan ekleme, mevcut alanların değerleri/anlamı değişmez.
Siyah Kapı'da DEĞİL. Tek fonksiyona dokunuldu. Sihirli sayı yok.

### 3b) `desktop/src/components/HybridTrade.jsx`
"Eşit" hücresi performans grid'ine eklendi (Kaybeden ile Başarı arası).
`perfStats.scratches ?? 0` fallback ile eski API yanıtlarına da dayanıklı.
Tooltip: "Eşit kapanan işlemler (pnl = 0): manuel kapanış, breakeven, dış kapanış".

### 3c) `desktop/src/components/AutoTrading.jsx`
Sağ kart sessiz duplicate yerine zenginleştirilmiş özete çevrildi (`auto-summary-grid`):

- **Anlık Floating** — açık otomatik pozisyonların toplam P&L'i
- **Bugün / Bu Ay** — kapanmış işlem sayıları
- **K / Z / Eşit** — bu ayın kazanan / kaybeden / eşit dağılımı (B8 invariant)
- **Strateji** — bu ayki strateji sayım rozetleri (Trend / MR / Breakout)

IIFE pattern ile inline türetilmiş state — store'a dokunulmadı.

### 3d) `desktop/src/styles/theme.css`
Yeni `auto-summary-grid` / `auto-summary-row` / `auto-summary-lbl` /
`auto-summary-val` / `auto-summary-strat` / `auto-strat-tag` sınıfları eklendi.
Mevcut sınıflar değişmedi.

### 3e) `tests/critical_flows/test_static_contracts.py`
**Flow 4ze** eklendi: `test_hybrid_scratch_and_auto_summary_enrichment`. Dört
bölümlük statik sözleşme testi:

1. `database.py` → `get_hybrid_performance` `scratches` alanını döndürüyor mu?
2. `HybridTrade.jsx` → `Eşit` hücresi var mı, `perfStats.scratches` referansı var mı?
3. `AutoTrading.jsx` → `auto-summary-grid` ve `Otomatik Özet` başlığı var mı, `stratCounts` türetimi var mı?
4. Üç dosyada da B8 audit marker'ı var mı?

### 3f) `docs/USTAT_GELISIM_TARIHCESI.md`
**#194** girişi #193 üzerine eklendi (Keep a Changelog formatı).

---

## 4. Test Sonuçları

```
python -m pytest tests/critical_flows -q --tb=short
========================
64 passed in 0.69s
========================
```

Baseline 63 → 64 (Flow 4ze eklendi, mevcut testler bozulmadı).

---

## 5. Build Sonuçları

```
npm run build
✓ 730 modules transformed
dist/index.js   894.54 kB │ gzip: 234.18 kB
✓ built in 2.72s
```

0 hata. Bundle boyutu marjinal artış (~1 KB) — ek React bileşeni ve CSS sınıfları
kabul edilebilir sınırda.

---

## 6. Anayasa Uyumu Doğrulama

| Kontrol | Durum |
|---------|-------|
| Çağrı sırası (BABA → OĞUL → H-Engine → ÜSTAT) | Etkilenmedi |
| Risk kapısı (`can_trade`) | Etkilenmedi |
| Kill-switch monotonluğu | Etkilenmedi |
| SL/TP zorunluluğu | Etkilenmedi |
| EOD kapanış 17:45 | Etkilenmedi |
| Felaket drawdown %15 | Etkilenmedi |
| OLAY rejimi `risk_multiplier=0` | Etkilenmedi |
| Circuit breaker | Etkilenmedi |
| Siyah Kapı fonksiyonları (31 fonksiyon) | Hiçbiri değişmedi |
| Kırmızı Bölge dokunuşu | `engine/database.py` (sadece `get_hybrid_performance`, additive) |
| Sihirli sayı | Yok — tüm değerler türetildi |

---

## 7. Kalan İşler

- Atomik commit (7 dosya)
- Backlog kalan maddeler: S1-S4, B3-B7, B12-B24, H10/H14, K1-K11, A11-A28
