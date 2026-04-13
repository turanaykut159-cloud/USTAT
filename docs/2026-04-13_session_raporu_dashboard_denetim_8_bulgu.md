# Oturum Raporu — Dashboard Denetim 8 Bulgu Düzeltmesi

**Tarih:** 13 Nisan 2026
**Versiyon:** v6.0.0 (artış yok — toplam değişiklik küçük)
**Sınıf:** C1 (Yeşil Bölge ağırlıklı)
**Süre:** Tek oturum
**Piyasa:** Pazartesi (Savaş Zamanı dışında, akşam saatleri)

---

## 1. Özet

Kullanıcı tarafından sağlanan kapsamlı dashboard denetim raporundaki 8 bulgunun tamamı kanıtla doğrulanıp düzeltildi. Hiçbir Kırmızı/Sarı Bölge dosyasına dokunulmadı, hiçbir Siyah Kapı fonksiyonu değiştirilmedi.

| Bulgu | Konu | Dosya | Commit |
|-------|------|-------|--------|
| 1 | Performance `days` parametresi pencereyi etkilemiyordu | api/routes/performance.py | 4b04887 |
| 2 | Performance UI pencere kaynağını göstermiyordu | desktop/src/components/Performance.jsx | 6af3e4a |
| 3 | API client fail-open fallback iyimser default döndürüyordu | desktop/src/services/api.js | 1d87a19 |
| 4 | TradeHistory karışık metrikler (filtrelenmiş tablo + baseline aggregate) | desktop/src/components/TradeHistory.jsx | a0e1814 |
| 5 | TopBar "ALGO KAPALI" rozeti fail-open çalışıyordu | desktop/src/components/TopBar.jsx | 312cd6f |
| 6 | AutoTrading hardcoded 15 kontrat sayısı | desktop/src/components/AutoTrading.jsx | 3cb400f |
| 7 | NewsPanel REST cevabında `worst_severity` eksik | api/schemas.py + api/routes/news.py | 9907960 |
| 8 | UstatBrain ölü `getPerformance` fetch'i | desktop/src/components/UstatBrain.jsx | dccf181 |

---

## 2. Doğrulama

- **Build:** Windows-side `python .agent/claude_bridge.py build` → `ustat-desktop@6.0.0`, 730 modül transformed, 2.70s, 0 hata, `dist/index.js 909.83 kB`.
- **Critical flows:** `python -m pytest tests/critical_flows -q --tb=short` → **71 passed**, 3.91s.
- **Anayasa kontrol:** Hiçbir Kırmızı Bölge / Siyah Kapı / config dokunusu yok.

---

## 3. Bulgu Detayları

### Bulgu 1 — `api/routes/performance.py`

**Kök neden:** `days` query parametresi tanımlıydı (`Query(30, ge=1, le=365)`) ama hiçbir yerde kullanılmıyordu. `STATS_BASELINE`'dan beri tüm trade'ler okunup tüm metrikler hesaplanıyordu. UI'deki "1Ay/3Ay/6Ay/1Yıl" butonları aynı veriyi döndürüyordu.

**Düzeltme:**
```python
baseline = get_stats_baseline()
days_cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
effective_since = max(baseline[:10], days_cutoff)
trades = db.get_trades(since=effective_since, limit=5000)
# Sharpe için aynı pencere:
_snap_since = effective_since if effective_since else STATS_BASELINE
```

`max(...)` koruması: `days` baseline'dan daha geriye giderse baseline anchor'ı korunur (Widget Denetimi A7 sözleşmesi).

### Bulgu 2 — `desktop/src/components/Performance.jsx`

UI etiketleri eklendi: pf-stats-row tooltip (`days` info), "Equity Eğrisi — Son {days} Gün" başlığı, kategori grafiklerinde "(baseline'dan beri)" notu.

### Bulgu 3 — `desktop/src/services/api.js`

**Kök neden:** `getStatus`/`getRisk`/`getHealth` HTTP/network hatasında iyimser default döndürüyordu (`regime: 'OPEN'`, `can_trade: true`, `mt5: { trade_allowed: true }`). Bu fail-open davranış, backend tamamen düştüğünde UI'de "her şey yolunda" izlenimi veriyordu — Anayasa Kural 9 (Fail-Safe) ihlali.

**Düzeltme:** Üç fonksiyon da fail-closed default + `_stale: true` + `_error` meta alanları döndürür.

### Bulgu 4 — `desktop/src/components/TradeHistory.jsx`

Risk panelinin `<h3>` başlığına "ⓘ Genel İstatistik" rozet, etiketlere `*` ve panele dipnot eklendi: kullanıcı filtrelenmiş tablo metrikleriyle baseline aggregate'i karıştırmaz.

### Bulgu 5 — `desktop/src/components/TopBar.jsx`

**Kök neden:** Önceki kod `tradeAllowed` boolean default `true` taşıyordu — health endpoint hata verince UI ALGO'yu açık sayıyordu (fail-open).

**Düzeltme:** Üç durumlu mantık:
```jsx
const [tradeAllowed, setTradeAllowed] = useState(null);
// fetchHealth: true → setTradeAllowed(true); false → setTradeAllowed(false); diğer → setTradeAllowed(null)
{tradeAllowed === false && <span className="topbar-warning">⚠ ALGO KAPALI</span>}
{tradeAllowed === null && <span className="topbar-warning topbar-warning-unknown">⚠ ALGO DURUMU BİLİNMİYOR</span>}
```

### Bulgu 6 — `desktop/src/components/AutoTrading.jsx`

```jsx
const totalCount = top5.all_scores ? Object.keys(top5.all_scores).length : 15;
const activeCount = Math.max(totalCount - deactCount, 0);
```

WATCHED_SYMBOLS değişirse kart otomatik takip eder.

### Bulgu 7 — `api/schemas.py` + `api/routes/news.py`

WebSocket payload'unda olan `worst_severity` REST cevabında yoktu. Severity ranking eklendi:

```python
_SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}
worst_sev = max((it.severity for it in items),
                key=lambda s: _SEV_RANK.get(s or "NONE", 0), default=None)
```

`NewsActiveResponse.worst_severity: str | None = None` alanı.

### Bulgu 8 — `desktop/src/components/UstatBrain.jsx`

`perf` state ve `getPerformance` import/çağrısı tamamen kaldırıldı — bileşen `perf`'i hiç render etmiyordu.

---

## 4. Bağlam Notları

Çalışma sırasında bazı dosyalar (TopBar.jsx, TradeHistory.jsx, AutoTrading.jsx, Performance.jsx, services/api.js, UstatBrain.jsx) Edit aracının cwork mount'undaki yazma yarış durumu yüzünden truncate olmuştu. Her dosya `git show HEAD:...` ile orijinal kuyrukları ekleyerek onarıldı; build 730 modülde temiz geçti.

---

## 5. Versiyon

Bu oturumdaki net değişiklik ~150 satır (8 commit). v6.0.0 `git diff --stat`'a göre toplam değişim oranı %10 altında kaldı — versiyon arttırılmadı, changelog #219–#226 eklendi.

---

## 6. Referanslar

- Doğrulama raporu: `docs/2026-04-13_denetim_dogrulama_raporu.md`
- Düzeltme planı: `docs/2026-04-13_denetim_duzeltme_plani.md`
- Changelog girişleri: #219 → #226
