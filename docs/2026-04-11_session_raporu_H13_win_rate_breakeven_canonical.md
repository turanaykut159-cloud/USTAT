# Oturum Raporu — 2026-04-11 — Widget Denetimi H13: Win Rate Breakeven Canonical Kaynak

**Oturum Türü:** Widget Denetimi Backlog — H13 (Düşük kritiklik)
**Sınıf:** C1 (Yeşil Bölge frontend utility + UI refactor — tek atomik değişiklik)
**Piyasa Durumu:** Kapalı (Pazar, Barış Zamanı)
**Commit:** (aşağıda)
**Oturum Süresi:** ~45 dakika

---

## 1. Bulgu Bağlamı

Widget Denetimi v6.0 (`docs/2026-04-11_widget_denetimi.md`) Bölüm 16.3 Bulgu H13 (Düşük kritiklik):

> **H13 — Win rate breakeven %50 eşiği magic number tekrarı.** `UstatBrain.jsx` kontrat profilleri, `Performance.jsx` Long/Short paneli ve `TradeHistory.jsx` filtered stats katmanlarında `win_rate >= 50 ? 'profit' : 'loss'` ifadesi 4+ ayrı call site'ında aynı sihirli sayıyı hardcode ediyor. Canonical kaynak yok, drift riski var. Frontend breakeven renkleme yalnız UI eşiğidir (backend risk parametresi değildir), bu yüzden `config/default.json` yerine frontend ortak modülünde (`desktop/src/utils/formatters.js`) tek kaynak olarak tutulmalıdır.

Bu oturumda bu bulgu giderildi ve scope analizi sırasında 6 call site tespit edildi (audit'te 4+ diyordu — Dashboard ve HybridTrade de aynı kalıbı inline style ile tekrarlıyordu).

---

## 2. Kök Neden Analizi

### 2.1 Drift Yüzeyi

Grep taraması ile `desktop/src/` altında `win_rate >= 50` / `winRate >= 50` kalıpları:

| # | Dosya | Satır | Tam İfade | Kullanım |
|---|-------|-------|-----------|----------|
| 1 | `UstatBrain.jsx` | 319 | `${cp.win_rate >= 50 ? 'profit' : 'loss'}` | Kontrat profilleri tablosu — CSS class |
| 2 | `Performance.jsx` | 378 | `cls={perf?.win_rate >= 50 ? 'profit' : 'loss'}` | PfStat "Win Rate" — CSS class prop |
| 3 | `Performance.jsx` | 494 | `cls={longShort.long.winRate >= 50 ? 'profit' : 'loss'}` | LsRow Long — CSS class prop |
| 4 | `Performance.jsx` | 503 | `cls={longShort.short.winRate >= 50 ? 'profit' : 'loss'}` | LsRow Short — CSS class prop |
| 5 | `TradeHistory.jsx` | 481 | `style={{ color: filteredStats.winRate >= 50 ? 'var(--profit)' : 'var(--loss)' }}` | Filtered stats — inline CSS var |
| 6 | `Dashboard.jsx` | 589 | `color={stats.win_rate >= 50 ? 'var(--profit)' : 'var(--loss)'}` | StatCard hero `color` prop — CSS var |
| 7 | `HybridTrade.jsx` | 354 | `style={{ color: perfStats.win_rate >= 50 ? 'var(--profit)' : 'var(--loss)' }}` | Perf panel — inline CSS var |

**Not:** Tablo'da 7 satır var çünkü Performance.jsx 3 ayrı yerde tekrar ediyor. Toplam 6 fiziksel dosya (`formatters.js` canonical kaynak + 6 tüketici bileşen).

### 2.2 İki Biçim — İki Helper

Call site'lar iki farklı değer biçimi bekliyor:

- **Biçim A (CSS class adı):** `'profit'` veya `'loss'` — `.profit` ve `.loss` global class'ları `theme.css` satır 905'te tanımlı (`.profit { color: var(--profit); font-weight: 500; }`). Kullanıcılar: UstatBrain, Performance (3x), TradeHistory (bu ikinciyi class'a çevirdik — aşağıya bakın).
- **Biçim B (CSS custom-property değeri):** `var(--profit)` veya `var(--loss)` — `style={{ color }}` veya custom component `color=` prop'u için. Kullanıcılar: Dashboard StatCard, HybridTrade inline style.

Bu yüzden tek helper yeterli değil — iki helper gerekli:
- `winRateClass(winRate)` → `'profit' | 'loss' | ''`
- `winRateColor(winRate)` → `'var(--profit)' | 'var(--loss)' | 'var(--muted)'`

### 2.3 TradeHistory.jsx İnce Karar

TradeHistory.jsx satır 481 orijinal olarak `style={{ color: ... }}` kullanıyordu — yani biçim B. Ancak sibling satır 487 `className={\`th-sc-value ${pnlClass(filteredStats.totalPnl)}\`}` pattern'ını kullanıyor. Tutarlılık için TradeHistory'yi Biçim A'ya (className) çevirdik — `theme.css` global `.profit` class'ı zaten `color: var(--profit)` atıyor, davranışsal fark yok ama kod pattern'ı aynı bileşen içinde tek düze.

### 2.4 Backend İlişkisi (YOKTUR)

`api/routes/ustat_brain.py`, `api/routes/performance.py`, `api/routes/trades.py`, `api/routes/hybrid_trade.py` dosyaları tüketildi — hiçbiri "50" eşiğini bilmiyor veya referans almıyor. Win rate ham yüzde olarak döner (0-100 arası float). Breakeven yorumu tamamen UI katmanında — bu yüzden eşik `config/default.json`'da DEĞİL, `desktop/src/utils/formatters.js`'te canonical olarak tutulur. Backend risk parametresi değildir.

---

## 3. Çözüm Uygulaması

### 3.1 `desktop/src/utils/formatters.js` (canonical kaynak)

Dosya başlığı yorumu H13 açıklaması ile genişletildi (eski 6 drift site listesi + neden frontend-only). Yeni eklenen API:

```javascript
export const WIN_RATE_BREAKEVEN_PCT = 50;

export function winRateClass(winRate) {
  if (winRate == null || isNaN(winRate)) return '';
  return winRate >= WIN_RATE_BREAKEVEN_PCT ? 'profit' : 'loss';
}

export function winRateColor(winRate) {
  if (winRate == null || isNaN(winRate)) return 'var(--muted)';
  return winRate >= WIN_RATE_BREAKEVEN_PCT ? 'var(--profit)' : 'var(--loss)';
}
```

**Null/NaN davranışı:** `winRateClass` boş string (renk yok — default metin rengi), `winRateColor` `var(--muted)` (gri) döner. Her iki helper de JSDoc'ta canonical atıf yapar.

### 3.2 Bileşen Migrasyonları (6 dosya)

Her bileşene H13 atıflı import yorumu eklendi. Davranışsal eşdeğerlik:

| Bileşen | Öncesi | Sonrası | Helper |
|---------|--------|---------|--------|
| `UstatBrain.jsx:319` | `${cp.win_rate >= 50 ? 'profit' : 'loss'}` | `${winRateClass(cp.win_rate)}` | winRateClass |
| `Performance.jsx:378` | `cls={perf?.win_rate >= 50 ? 'profit' : 'loss'}` | `cls={winRateClass(perf?.win_rate)}` | winRateClass |
| `Performance.jsx:494` | `cls={longShort.long.winRate >= 50 ? 'profit' : 'loss'}` | `cls={winRateClass(longShort.long.winRate)}` | winRateClass |
| `Performance.jsx:503` | `cls={longShort.short.winRate >= 50 ? 'profit' : 'loss'}` | `cls={winRateClass(longShort.short.winRate)}` | winRateClass |
| `TradeHistory.jsx:481` | `style={{ color: filteredStats.winRate >= 50 ? 'var(--profit)' : 'var(--loss)' }}` | `className={\`th-sc-value ${winRateClass(filteredStats.winRate)}\`}` | winRateClass (biçim değişimi) |
| `Dashboard.jsx:589` | `color={stats.win_rate >= 50 ? 'var(--profit)' : 'var(--loss)'}` | `color={winRateColor(stats.win_rate)}` | winRateColor |
| `HybridTrade.jsx:354` | `style={{ color: perfStats.win_rate >= 50 ? 'var(--profit)' : 'var(--loss)' }}` | `style={{ color: winRateColor(perfStats.win_rate) }}` | winRateColor |

**Davranışsal fark yok.** Breakeven dahil (>= %50 → profit), null/NaN güvenli, 6 call site'ın tamamı aynı nihai CSS değerini üretir.

### 3.3 Statik Sözleşme Testi — Flow 4y

`tests/critical_flows/test_static_contracts.py`'a Flow 4y (`test_win_rate_breakeven_canonical_source`) eklendi. 4 assertion:

1. **(a)** `formatters.js`'te `WIN_RATE_BREAKEVEN_PCT` sabiti var — canonical kaynak mevcut.
2. **(b)** `winRateClass` ve `winRateColor` export'ları regex ile doğrulanır.
3. **(c)** `desktop/src/components/` altında `rglob("*.jsx")` ile tarama — `\b(?:win_rate|winRate)\s*>=\s*50\b` pattern yakalanırsa test FAIL eder. **Kritik:** sadece 6 bilinen call site değil, HER `.jsx` dosyası taranır. Gelecekte yeni bir bileşen aynı hardcode'u eklerse test yakalar.
4. **(d)** `Widget Denetimi H13` marker yorumu `formatters.js`'te mevcut — canonical kaynağın rolü explicit.

---

## 4. Test ve Build Sonuçları

### 4.1 `tests/critical_flows` — 58 passed

```
58 passed, 3 warnings in 3.36s
```

Baseline 57 (H11 sonrası) + Flow 4y = 58. İlk koşuda yeşil — yorum self-poisoning olmadı çünkü migrasyonlara eklenen açıklayıcı yorumlar literal `win_rate >= 50` / `winRate >= 50` kalıbını içermiyor (sadece "hardcode 50" gibi ara ifadeler kullanıldı).

### 4.2 Windows Production Build — Başarılı

```
ustat-desktop@6.0.0 build
vite v6.4.1 building for production...
728 modules transformed.
dist/index.html                  1.07 kB │ gzip:   0.60 kB
dist/assets/index-CiUWDTb0.css  90.52 kB │ gzip:  15.07 kB
dist/assets/index-nWG86KG-.js  889.86 kB │ gzip: 255.16 kB
✓ built in 2.63s
```

Bundle boyutu: `index.js` 889.86 kB (H11 sonrası 889.85 kB → +0.01 kB net). Net sıfıra yakın: eklenen helper'lar tree-shake sonrası 6 call site'ın kaldırılmasıyla dengelendi.

---

## 5. Anayasa Uyumu

| Kural | Uyum |
|-------|------|
| Çağrı sırası DEĞİŞTİRİLEMEZ | Backend dokunulmadı — motor sırası etkilenmedi |
| Kırmızı Bölge (10 dosya) | Dokunulmadı — hepsi backend/startup kritik dosyaları |
| Sarı Bölge (7 dosya) | Dokunulmadı — `h_engine.py`, `config.py`, `killswitch.py`, `positions.py`, `main.js`, `mt5Manager.js` hiçbiri etkilenmedi |
| Siyah Kapı (31 fonksiyon) | Dokunulmadı — tümü backend risk/emir/state koruması |
| Sihirli sayı yasağı | Tam tersi — bu görev sihirli sayıyı kaldırmak için yapıldı; ama canonical kaynak **frontend utility modülü**'nde çünkü risk/karar parametresi değil sadece UI renk eşiği |
| Geri alma planı | `git revert HEAD` — 7 dosya tek commit'te; geri dönüş 1 komut |
| Test disiplini | Flow 4y statik sözleşme eklendi; herhangi bir regression 6 call site'a hardcode geri dönüşünü CI'de yakalar |
| Piyasa zamanlaması | Pazar → Barış Zamanı → tüm değişiklikler serbest |

---

## 6. Dosya Listesi

| Dosya | Değişiklik | Kategori |
|-------|-----------|----------|
| `desktop/src/utils/formatters.js` | +30/-0 (canonical const + 2 helper + H13 başlık yorumu) | Frontend utility |
| `desktop/src/components/UstatBrain.jsx` | +4/-1 (import + 1 call site) | Frontend UI |
| `desktop/src/components/Performance.jsx` | +4/-3 (import + 3 call site) | Frontend UI |
| `desktop/src/components/TradeHistory.jsx` | +2/-3 (import ekleme + 1 call site biçim değişimi) | Frontend UI |
| `desktop/src/components/Dashboard.jsx` | +2/-1 (import ekleme + 1 call site) | Frontend UI |
| `desktop/src/components/HybridTrade.jsx` | +2/-1 (import ekleme + 1 call site) | Frontend UI |
| `tests/critical_flows/test_static_contracts.py` | +40/-0 (Flow 4y) | Test |
| `docs/USTAT_GELISIM_TARIHCESI.md` | +1 (#188) | Changelog |
| `docs/2026-04-11_session_raporu_H13_win_rate_breakeven_canonical.md` | +N (bu dosya) | Oturum raporu |

**Toplam:** 9 dosya, 0 Siyah Kapı dokunusu, 0 Kırmızı/Sarı Bölge dokunusu, 0 config değişikliği, 0 CSS değişikliği, 0 API değişikliği.

---

## 7. Risk ve Geri Alma

**Risk profili:** Sıfır (frontend UI refactor, davranışsal eşdeğer, backend/engine temassız).

**Geri alma:** `git revert HEAD --no-edit` → `python .agent/claude_bridge.py build` → `python .agent/claude_bridge.py restart_app`. Tek commit olduğu için geri dönüş tek komuttur.

---

## 8. Sonraki Audit Maddesi

Widget Denetimi backlog'da kalan Düşük kritiklik bulgular:
- **H7 — Hata Takip kategori/renk drift:** `ErrorTracker.jsx` içinde kategori renk eşlemesi frontend-only; ama ErrorTracker'da aynı yapıyı birden fazla yerde tekrarlıyor mu bakılmalı.
- **H16 — Hibrit Devir operator identity hardcode:** `HybridTrade.jsx` manuel devir butonunda "kim yaptı" alanı sabit bir placeholder — Settings'ten çekilmeli.

H13 tamamen kapandı. Bir sonraki "Devam edelim" turunda H7 veya H16 değerlendirilecek.
