# Oturum Raporu — A18 Dashboard Pozisyon Rozeti Config Binding (H2)

**Tarih:** 11 Nisan 2026 (Cumartesi — Barış Zamanı)
**Audit kaynağı:** `docs/2026-04-11_widget_denetimi.md` Bölüm 3.3 (B16), 16.3 H2, 17 A18
**Bulgu kodu:** A18 / H2 (Orta kritiklik — Dashboard rozeti hardcode `/5`)
**Değişiklik sınıfı:** C1 (Yeşil Bölge — Dashboard.jsx + services/api.js)
**Versiyon artışı:** YOK
**Commit hedefi:** Tek atomik commit — 2 kod dosyası + 1 test + 1 changelog + 1 rapor

---

## 1. Bulgu Özeti

`desktop/src/components/Dashboard.jsx` satır 671'de `{(livePositions || []).length} / 5` şeklinde hardcode edilmiş bir rozet vardı. `max_open_positions` (eşzamanlı maksimum açık pozisyon sayısı) zaten `config/default.json::risk.max_open_positions = 5` üzerinden backend'e biliniyor ve `api/routes/risk.py::get_risk()` RiskResponse'a atama yapıyordu. Ancak Dashboard bu endpoint'i hiç çağırmıyordu — kullanıcı config'den değeri 3'e veya 7'ye çekse bile UI hâlâ `n / 5` gösteriyor, BABA'nın gerçekten kullandığı limit ile UI arasında kavramsal kopukluk oluşuyordu.

Audit B16: "🧱 Hardcode — config'den `max_open_positions` okunmalı"
Audit H2: "Dashboard (3.3) `1 / 5` pozisyon sayacı — `max_open_positions` config'den değil, sabit '/5'"

---

## 2. Anayasa Değerlendirmesi

| Kontrol | Durum |
|---|---|
| **Siyah Kapı dokunusu** | YOK |
| **Kırmızı Bölge** | YOK — backend hiç dokunulmadı, sadece frontend tüketimi eklendi |
| **Sarı Bölge** | YOK |
| **Çağrı sırası** | DEĞİŞMEDİ |
| **Fonksiyon silme** | YOK |
| **Savaş zamanı ihlali** | YOK — Cumartesi (Barış Zamanı) |

**Sınıf:** C1 (Yeşil Bölge). Kullanıcı standing directive: "Bir sonraki audit maddesini sen seç ve İŞLEMİ BİTİR disipliniyle tamamla."

---

## 3. Atomik Değişiklikler

### 3.1 Frontend

**(a) `desktop/src/services/api.js::getRisk()`** — fallback objesine tek alan eklendi:
```javascript
return {
  daily_pnl: 0, can_trade: true, kill_switch_level: 0,
  regime: 'TREND', risk_multiplier: 1, open_positions: 0,
  // A18: hata durumunda bile max_open_positions güvenli fallback değeri (5).
  // Dashboard rozetinin "n / X" formatı hiçbir koşulda kırılmaz.
  max_open_positions: 5,
};
```

Hata durumunda rozet asla `n / undefined` göstermez — geriye dönük uyumluluk garantili.

**(b) `desktop/src/components/Dashboard.jsx`** — dört değişiklik:
1. `getRisk` import eklendi (mevcut import bloğuna ek satır)
2. Yeni `riskState` state'i — `useState(_dashCache?.riskState ?? null)` — cache'li ilk render
3. `fetchAll` içindeki `Promise.all` tuple'ına `getRisk()` çağrısı eklendi (`rk` değişkeni), `setRiskState(rk || null)` ile state'e yazıldı
4. `_dashCache` objesi `riskState` alanı içerecek şekilde genişletildi (sonraki mount'ta anında)
5. Rozet satırı güncellendi:
```jsx
{/* A18: "/5" eski hardcode'u, artık riskState.max_open_positions (config zinciri). */}
{(livePositions || []).length} / {riskState?.max_open_positions ?? 5}
```

`?? 5` fallback — ilk render'da (state henüz null) veya REST hata durumunda güvenli değer.

### 3.2 Backend Dokunulmadı

`/api/risk` endpoint'i, `RiskResponse` schema'sı, `api/routes/risk.py` ve `config/default.json::risk.max_open_positions` hepsi zaten hazırdı. Bu fix sadece **tüketici tarafı** değişikliği.

### 3.3 Statik Sözleşme Testi

**`tests/critical_flows/test_static_contracts.py::test_dashboard_max_open_positions_from_config`** (Flow 4o) — 5 aşamalı zincir doğrulaması:

1. `config/default.json::risk.max_open_positions` var + pozitif int
2. `api/schemas.py::RiskResponse.max_open_positions` alanı mevcut
3. `api/routes/risk.py` `resp.max_open_positions` atama yapıyor
4. `services/api.js::getRisk` export + fallback objesinde `max_open_positions` mevcut (regex ile fonksiyon gövdesi kontrolü)
5. `Dashboard.jsx`:
   - Eski `|| []).length} / 5\n` hardcode pattern'i **YOK** (regression koruma)
   - `getRisk` import + `riskState` state + `setRiskState` setter mevcut
   - `riskState?.max_open_positions` ifadesi mevcut

Gelecek refactor sırasında hardcode geri eklenirse pre-commit hook commit'i bloklayacak.

---

## 4. Dokunulmayanlar (Bilinçli)

- `ManualTrade.jsx` lot min/max hardcode — A16 ayrı bulgu
- `NewsPanel` SYMBOLS listesi — B8 ayrı bulgu
- `max_daily_trades` için ayrı bulgu (Performance/Monitor) — A18 kapsamı dışı
- Dashboard `daily_trade_count` rozeti ayrı bulgu — A18 kapsamı dışı

---

## 5. Etki Analizi

| Kriter | Değer |
|---|---|
| Dosya sayısı | 2 kod + 1 test + 1 changelog + 1 rapor = 5 |
| Net satır | ~20 ekleme |
| Siyah Kapı dokunusu | 0 |
| Backend dokunusu | 0 (endpoint zaten hazırdı) |
| Çağıran zinciri | `Dashboard mount → fetchAll → getRisk() → /api/risk → baba/config.get("risk.max_open_positions") → RiskResponse → riskState state → JSX` |
| Tüketici zinciri | Geriye dönük uyumlu — yeni tüketici, mevcut konsümerler etkilenmez |
| Kullanıcı deneyimi | Rozet artık canlı config değerini yansıtıyor; admin `max_open_positions`'ı 3'e çekse restart sonrası `n / 3` görür |

---

## 6. Doğrulama

| Test | Sonuç |
|---|---|
| `tests/critical_flows` | **48/48 yeşil** (47 baseline + yeni Flow 4o), 3.08s |
| Windows `npm run build` | `ustat-desktop@6.0.0`, 728 modül transformed, 2.59s, **0 hata** |
| dist/ çıktıları | `index.js 886.99 kB`, `index.css 90.52 kB` |
| Piyasa durumu | Cumartesi — Barış Zamanı |
| Deploy hazırlığı | `restart_app` yeterli (sadece Electron bundle yenilenir, backend etkilenmez) |

---

## 7. Versiyon Durumu

Tek başına versiyon artışı gerektirecek büyüklükte değil. Versiyon sabiti korundu — v6.0.0.

---

## 8. Geri Alma Planı

```bash
git revert <commit_hash> --no-edit
```

Commit tamamen atomic: 5 dosya birlikte geri alınır. Fallback 5 rozet satırında kalır (`?? 5`), rozet geri almadan sonra hâlâ `n / 5` gösterir (davranış aynı).

---

## 9. Kaynak Belgeler

- `docs/2026-04-11_widget_denetimi.md` Bölüm 3.3 (B16), 16.3 (H2), 17 (A18)
- `docs/USTAT_GELISIM_TARIHCESI.md` entry #178
- `CLAUDE.md` Bölüm 9 (C1 sınıfı)
- `USTAT_ANAYASA.md` v2.0
