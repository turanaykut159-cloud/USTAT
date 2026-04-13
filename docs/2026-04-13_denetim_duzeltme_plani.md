# ÜSTAT v5.9 — Denetim Bulguları Düzeltme Planı

**Tarih:** 13 Nisan 2026, 18:54 TRT (Barış Zamanı)
**Kaynak:** 2026-04-13 Denetim Doğrulama Raporu
**Durum:** ONAY BEKLEMEKTE — kod değişikliği YAPILMADI

> CLAUDE.md Bölüm 3.3 gereği: plan açıklanır, kullanıcı onayı alınır, sonra uygulanır. Sessizlik onay değildir. Her madde için ayrı ayrı ya da toplu onay verilebilir.

---

## Önceki Analizden Çıkarımlar (Karar Noktaları)

1. **P1-A, iki katman birden kırık:** Hem backend `/api/performance` `days`'i kullanmıyor, hem frontend stats/trades çağrıları baseline'a takılı. Ancak `stats_baseline` **kasıtlı** (Widget Denetimi A7 ile tekilleştirilmiş). Çözümde asimetri bilinçli korunmalı: equity eğrisi periyoda göre, aggregate istatistikler baseline'a göre — ama UX belgesiz olmamalı.

2. **P3-B, düşük gibi görünen ama ince bir sorun:** `worst_severity` NewsActiveResponse'da hiç yok; NewsStatusResponse'da var. Yani alan mevcut, sadece yanlış şemaya bağlanmış.

3. **P1-B etki analizi kritik:** 9 frontend bileşeni `getStatus/getRisk/getHealth` tüketiyor. Fallback şeklini değiştirmek **breaking change** potansiyeli taşıyor. Tüketici davranışını bozmadan sinyal vermek için ek alan (`_stale: true`, `_source: 'fallback'`) daha güvenli.

---

## Değişiklik Sınıflandırması (CLAUDE.md Bölüm 9)

| # | Bulgu | Dosya(lar) | Bölge | Sınıf |
|---|-------|-----------|-------|-------|
| 1 | P1-A backend days cutoff | `api/routes/performance.py` | Yeşil | C1 |
| 2 | P1-A frontend UX etiketi | `Performance.jsx` | Yeşil | C1 |
| 3 | P1-B fallback stale sinyali | `api.js` | Yeşil | C2 (tüketici fazla) |
| 4 | P2-A TradeHistory etiket ayrımı | `TradeHistory.jsx` | Yeşil | C1 |
| 5 | P2-B TopBar üçlü mantık | `TopBar.jsx` + `api.js` | Yeşil | C1 |
| 6 | P3-A Auto Trading dinamik sayı | `AutoTrading.jsx` + backend | Yeşil | C1 |
| 7 | P3-B worst_severity eklenmesi | `schemas.py` + `news.py` | Yeşil | C1 |
| 8 | P3-C ölü fetch temizliği | `UstatBrain.jsx` | Yeşil | C1 |

**Kırmızı Bölge dosyasına dokunulmuyor.** Siyah Kapı fonksiyonu değişmiyor. Çağrı sırası, risk kapısı, SL/TP mantığı bozulmuyor.

---

## Bulgu Bazlı Plan

### Bulgu 1 — P1-A Backend: `days` parametresini gerçekten uygula

**Dosya:** `api/routes/performance.py`
**Durum:** `days` Query'de tanımlı (satır 26), gövdede kullanılmıyor (satır 39-40).

**Plan:**
- `baseline = get_stats_baseline()` korunur (tarihsel anchor)
- Ek olarak `cutoff = max(baseline, today - days)` hesaplanır
- `db.get_trades(since=cutoff, limit=5000)` — equity eğrisi artık iki kısıt arasında: "baseline'dan sonra **VE** son N gün içinde"
- Yeni response alanı: `window_start_date` (gerçekten kullanılan başlangıç)

**Etki Analizi:**
- **Tüketici:** Sadece `Performance.jsx` `getPerformance(days)` kullanıyor. `UstatBrain.jsx` da kullanıyor ama sonucu kullanmıyor (Bulgu 8'de temizlenecek)
- **Risk:** Equity eğrisi görseli değişir (beklenen). Risk/pozisyon/emir mantığı ETKİLENMEZ
- **Performans:** Daha küçük pencere → daha hızlı sorgu

**Geri Alma:** `git revert <commit>`

---

### Bulgu 2 — P1-A Frontend: UX etiketlemesi ve dürüst başlık

**Dosya:** `desktop/src/components/Performance.jsx`
**Durum:** `days` değişince stats/trades yenilenmiyor (tasarım), ama kullanıcı bunu bilmiyor.

**Plan:**
- Equity grafiğinin başlığına `days` değerini yaz: `"Son {days} Gün — Equity"`
- İstatistik kartlarının olduğu bölüme küçük not: `"Baseline: {stats_baseline} itibarıyla tüm işlemler"`
- Mevcut tooltip zaten bilgiyi içeriyor (satır 372), sadece görünürlüğü artırılıyor

**Etki Analizi:**
- **Tüketici:** Sadece UI metin değişikliği
- **Risk:** Yok (cosmetic)
- **Breaking:** Yok

**Geri Alma:** `git revert <commit>`

---

### Bulgu 3 — P1-B API Fallback: stale/error sinyali ekle

**Dosya:** `desktop/src/services/api.js`
**Durum:** `getStatus/getRisk/getHealth` hata durumunda sessizce "normal" obje dönüyor.

**Plan (ihtiyatlı yaklaşım):**
- Mevcut tüm alanlar korunur (9 tüketiciyi bozmamak için)
- Ek alan eklenir: `_stale: true` + `_error: err?.message`
- Tüketici bileşenler opsiyonel olarak `_stale`'i kontrol ederek uyarı gösterebilir
- `regime: 'TREND'` → **`regime: 'UNKNOWN'`** olarak değiştirilir (mimari değişiklik — rejim kartı artık "bilinmiyor" gösterir)
- `can_trade: true` → **`can_trade: false`** olarak değiştirilir (fail-closed)
- `risk_multiplier: 1` → **`risk_multiplier: 0`** (hata durumunda sıfır risk)

**Etki Analizi (KRİTİK):**
9 tüketici dosyasında davranış değişir:

| Dosya | Etki |
|-------|------|
| `TopBar.jsx` | Bulgu 5 ile birlikte ele alınır |
| `Dashboard.jsx` | Hata durumunda rejim kartı "UNKNOWN" gösterir (iyi) |
| `RiskManagement.jsx` | `can_trade: false` → "işlem yok" gösterir (iyi) |
| `AutoTrading.jsx` | Status'e bağımlı ise "offline" gösterir (iyi) |
| `Settings.jsx` | Version düşüşü ile fark edilmez |
| `LockScreen.jsx` | Version alanını kullanır, etkilenmez |
| `Monitor.jsx` | Rejim/regime göstergesi "UNKNOWN" olur (iyi) |
| `UstatBrain.jsx` | Status gösterir — muhtemelen etkilenmez |
| `AutoTrading.jsx` | Yukarıda zaten |

- **Risk:** UI'da yanıltıcı görüntü tamamen kaybolur (hedef zaten bu)
- **Breaking:** Hiçbir tüketici null check'e gerek duymaz çünkü alanlar hâlâ dolu. Sadece anlam değişiyor

**Geri Alma:** `git revert <commit>`

---

### Bulgu 4 — P2-A TradeHistory: Risk paneli etiketi netleşsin

**Dosya:** `desktop/src/components/TradeHistory.jsx`
**Durum:** Sol panel filtreli, sağ panel (best/worst trade, sharpe, max DD) global.

**Plan (minimum değişiklik — dürüstlük yaklaşımı):**
- Sağ paneldeki "Risk Analizi" başlığının altına küçük bir rozet: `"Genel İstatistik (filtreden bağımsız)"`
- `best_trade`, `worst_trade`, `sharpe_ratio`, `max_drawdown_pct`, `avg_duration_minutes` alanlarının yanına `*` işareti, altta açıklama

**Alternatif (daha büyük değişiklik — önerilmiyor):**
- Filtreye göre yeniden hesap → backend yeni endpoint gerektirir, C3 seviyesi iş

**Bu planda alternatif dışlanıyor — minimum değişiklik seçiliyor.**

**Etki Analizi:**
- **Tüketici:** Sadece UI metin
- **Risk:** Yok

**Geri Alma:** `git revert <commit>`

---

### Bulgu 5 — P2-B TopBar: Üçlü mantık

**Dosya:** `desktop/src/components/TopBar.jsx` + Bulgu 3 ile zincirli
**Durum:** `allowed !== false` fail-open (undefined → true gösterir).

**Plan:**
- `tradeAllowed` state'i `useState(null)` başlar (initial unknown)
- Mantık değişir:
  - `allowed === true` → trade açık (uyarı yok)
  - `allowed === false` → trade kapalı (kırmızı "⚠ ALGO KAPALI" uyarısı)
  - `allowed === undefined/null` → **bilinmiyor** (gri "⚠ ALGO DURUMU BİLİNMİYOR" uyarısı)
- Bulgu 3 ile birlikte `getHealth` fallback'i `trade_allowed: null` döndürür (şu an döndürmüyor, eklenecek)

**Etki Analizi:**
- **Tüketici:** Sadece TopBar
- **Risk:** Yok; mevcut "uyarı yok" davranışı daraltılıyor

**Geri Alma:** `git revert <commit>`

---

### Bulgu 6 — P3-A Auto Trading: Dinamik kontrat sayısı

**Dosya:** `desktop/src/components/AutoTrading.jsx`
**Durum:** `const activeCount = 15 - deactCount;` — sabit 15.

**Plan:**
- Watchlist toplam uzunluğu backend'den gelir (`/api/settings/watchlist` veya `top5` endpoint'inin `watchlist_size` alanı)
- Frontend `totalCount`'u fetch eder, `activeCount = totalCount - deactCount`
- Backend'de `top5.py` response'una `watchlist_size: int` alanı eklenir

**Etki Analizi:**
- **Backend:** `api/schemas.py` Top5Response'a `watchlist_size` eklenir
- **Tüketici:** Sadece AutoTrading.jsx
- **Risk:** Yok

**Geri Alma:** `git revert <commit>`

---

### Bulgu 7 — P3-B NewsPanel: worst_severity şemada eksik

**Dosyalar:** `api/schemas.py` + `api/routes/news.py`
**Durum:** NewsActiveResponse'da `worst_severity` yok; NewsPanel bekliyor.

**Plan:**
- `api/schemas.py` NewsActiveResponse'a `worst_severity: str | None = None` eklenir
- `api/routes/news.py` satır 85'te hesaplanır: `worst_severity = max(items, key=...).severity if items else None`
- Mevcut `NewsStatusResponse` örneğinden pattern kopyalanır

**Etki Analizi:**
- **Tüketici:** NewsPanel.jsx `worst_severity` destructure ediyor, artık gerçek değer alacak
- **Risk:** Yok; sadece eksik alan dolduruluyor
- **Breaking:** Yok (alan nullable)

**Geri Alma:** `git revert <commit>`

---

### Bulgu 8 — P3-C UstatBrain: Ölü fetch temizliği

**Dosya:** `desktop/src/components/UstatBrain.jsx`
**Durum:** `getPerformance(days)` çağrılıyor, `setPerf(p)` yapılıyor, `perf` hiçbir yerde okunmuyor.

**Plan:**
- Satır 176 `const [perf, setPerf]` kaldırılır
- Satır 184-185 `getPerformance(days)` Promise.all'dan çıkarılır
- Satır 189 `setPerf(p)` kaldırılır
- Destructuring `const [b, s] = await Promise.all(...)` olarak sadeleşir

**Etki Analizi:**
- **Tüketici:** Yok
- **Risk:** Yok (ölü kod)
- **Fayda:** Her `days` değişiminde gereksiz `/api/performance` çağrısı kaybolur

**Geri Alma:** `git revert <commit>`

---

## Uygulama Sırası (Risk Minimizasyonu)

Düşük riskten yükseğe:

1. **Bulgu 8** — ölü kod temizliği (en risksiz)
2. **Bulgu 7** — schema alan ekleme (yeni alan, kırıcı değil)
3. **Bulgu 4** — TradeHistory etiket (cosmetic)
4. **Bulgu 2** — Performance.jsx UX etiketi (cosmetic)
5. **Bulgu 6** — AutoTrading dinamik sayı (backend + frontend birlikte)
6. **Bulgu 1** — performance.py days cutoff (backend sorgu mantığı)
7. **Bulgu 3** — api.js fallback (9 tüketici etkili — en riskli)
8. **Bulgu 5** — TopBar üçlü mantık (Bulgu 3'e bağlı)

Her bulgu **ayrı commit**. Her commit sonrası `tests/critical_flows` çalıştırılır (CLAUDE.md Adım 1.5 zorunluluğu).

---

## Kritik Akış Testleri (Her Bulgu Sonrası Zorunlu)

```bash
python -m pytest tests/critical_flows -q --tb=short
```

Başarısız test varsa commit YASAK (CLAUDE.md Bölüm 7 Adım 1.5).

---

## Versiyon Etkisi

Toplam değişiklik ~8 dosya × ~15-30 satır = yaklaşık 150-200 satır.
CLAUDE.md Bölüm 7 Adım 3 hesabı build sonrası yapılacak. Oran %10'un altında kalırsa v5.9.x patch; üstünde ise v6.0 major.

---

## ONAY GEREKEN KARAR NOKTALARI

Uygulamaya geçmeden önce aşağıdakilerin onaylanması gerekir:

1. **Bulgu 3 — Fallback fail-closed politika:** `regime: 'TREND'` → `'UNKNOWN'`, `can_trade: true` → `false`, `risk_multiplier: 1` → `0` değiştirilsin mi? Bu dürüstlük kazanır ama 9 tüketicinin "hata durumunda ne görüneceği" kararını etkiler.

2. **Bulgu 4 — TradeHistory:** Minimum (etiket) mi yoksa tam (filtreli yeniden hesap) mi? Plan minimum öneriyor.

3. **Bulgu 6 — Top5Response şema değişikliği:** `watchlist_size` eklemek kabul mü?

4. **Uygulama sırası:** Yukarıdaki 8 adımlı sıra onaylansın mı?

---

**Hazır olunduğunda: "Onay, başla" veya değişiklik isteği.**
