# Oturum Raporu — Widget Denetimi A10: TopBar "Günlük K/Z (MT5)" etiketi düzeltildi

**Tarih:** 11 Nisan 2026 (Cumartesi — Barış Zamanı)
**Konu:** TopBar üç noktada "MT5" etiketini "Snapshot" olarak değiştirdi — veri kaynağı `risk_snapshots` tablosu
**Değişiklik Sınıfı:** C1 (Yeşil Bölge — tek bileşen, üç string + yorum)
**Versiyon:** v6.0.0 (değişmedi)
**Changelog:** #176
**Commit:** (commit sonrası eklenecek)

---

## 1. Kök Neden (Widget Denetimi Bulgu A10 / B16)

Audit `docs/2026-04-11_widget_denetimi.md` Bölüm 15.1 + 16.2 B16 + 17 A10:

> "Günlük K/Z (MT5) — `account.daily_pnl` — `/api/account` cevabı — Kısmi — veri MT5'ten değil risk_snapshots tablosundan geliyor. 🐛 Yanlış etiket."

Kod tabanı doğrulaması:

1. **`desktop/src/components/TopBar.jsx`** üç nokta:
   - **Satır 5** (dosya başı yorumu): `Sağ:  Bakiye | Equity | Floating | Günlük K/Z (MT5, 2sn) | Pin | Saat`
   - **Satır 245** (metric container title tooltip): `title="MT5 günlük P/L (gerçek zamanlı)"`
   - **Satır 246** (metric label): `<span className="tb-metric-label">Günlük K/Z (MT5)</span>`
   - Değer: `const dailyPnl = account.daily_pnl || 0;` (satır 139), `account` objesi `/api/account` polling'den gelir (satır 31, 2sn interval).

2. **`api/routes/account.py::get_account`** (satır 32-37):
   ```python
   # Günlük PnL: son risk snapshot'tan
   daily_pnl = 0.0
   if db:
       snap = db.get_latest_risk_snapshot()
       if snap:
           daily_pnl = snap.get("daily_pnl", 0.0)
   ```
   `daily_pnl` alanı MT5 hesabından değil, BABA'nın periyodik yazdığı `risk_snapshots` DB tablosundan okunuyor. MT5 hesap bilgisi (`mt5.get_account_info()`) balance/equity/margin/free_margin için kullanılıyor; `daily_pnl` ise ayrı DB kaynağı.

3. **Dashboard'daki aynı alan** WebSocket `liveEquity.daily_pnl` üzerinden geliyor — yine aynı `risk_snapshots` tablosunun akışlı versiyonu. İki farklı okuma yolu (2 sn REST vs WS stream) ama ikisi de aynı kaynaktan besleniyor; label "MT5" demek teknik olarak yanlış.

**Kullanıcı etkisi:** TopBar her ekran render'ında "Günlük K/Z (MT5)" gördüğü için kullanıcı bu değerin MT5 terminal'inden canlı geldiğini sanıyor. Gerçekte bu değer BABA'nın son risk snapshot yazma zamanına bağlı (risk cycle periyotu). MT5 bağlantısı kopuk olsa bile son snapshot kalıcı — kullanıcı yanıltıcı "canlı MT5" algısıyla sistem durumu değerlendiriyor. Audit "🐛 Yanıltıcı" olarak kayıt almış.

## 2. Çözüm

TopBar.jsx'teki üç nokta güncellendi. Mantık, state, veri akışı değişmedi — yalnız görünen etiket doğru kaynağı söylüyor.

### 2.1 `desktop/src/components/TopBar.jsx` (C1 — Yeşil Bölge)

**Değişiklik 1 — Satır 5 (header yorumu):**
```
// Önce
 * Sağ:  Bakiye | Equity | Floating | Günlük K/Z (MT5, 2sn) | Pin | Saat
// Sonra
 * Sağ:  Bakiye | Equity | Floating | Günlük K/Z (Snapshot, 2sn) | Pin | Saat
```

**Değişiklik 2 + 3 — Satır 243-246 (metric blogu):**
```jsx
// Önce
<div className="tb-metric" title="MT5 günlük P/L (gerçek zamanlı)">
  <span className="tb-metric-label">Günlük K/Z (MT5)</span>
  <span className={`tb-metric-value ${dailyPnl >= 0 ? 'profit' : 'loss'}`}>
    {formatMoney(dailyPnl)}
  </span>
</div>

// Sonra
{/* Widget Denetimi A10 fix — etiket "MT5" değil "Snapshot" çünkü
    veri api/routes/account.py::get_account → db.get_latest_risk_snapshot()
    üzerinden risk_snapshots tablosundan okunuyor, doğrudan MT5'ten değil. */}
<div className="tb-metric" title="Günlük P/L — risk_snapshots tablosundan (2 sn polling)">
  <span className="tb-metric-label">Günlük K/Z (Snapshot)</span>
  <span className={`tb-metric-value ${dailyPnl >= 0 ? 'profit' : 'loss'}`}>
    {formatMoney(dailyPnl)}
  </span>
</div>
```

Değişiklik kapsamı:
- Header yorumu: 1 satır (MT5 → Snapshot)
- Metric title tooltip: 1 satır (tooltip metni, gelecekteki refactor için kaynak bilgisi)
- Metric label: 1 satır (UI'da görünen kullanıcı etiketi)
- Eklenen yorum: 3 satır (backend zincirini dokümante eder)

Yeni state yok, yeni prop yok, veri akışı aynı. `account.daily_pnl` → `dailyPnl` const → span render — hepsi korundu.

## 3. Statik Sözleşme Testi (Flow 4m)

`tests/critical_flows/test_static_contracts.py` içine `test_topbar_daily_pnl_label_not_mt5` eklendi. 3 aşamalı doğrulama:

1. **Yanlış etiket kaldırıldı** — `"Günlük K/Z (MT5)"` string'i TopBar.jsx içinde YOK. Birisi fix'i geri alırsa test düşer.
2. **Doğru etiket mevcut** — `"Günlük K/Z (Snapshot)"` string'i dosyada mevcut.
3. **Header yorumu da güncel** — `"Günlük K/Z (MT5, 2sn)"` dosya başı yorumunda da kalmamış olmalı (yorum ile UI etiketi tutarlılığı).

Bu üç assertion gelecek refactor sırasında hardcode'un geri eklenmesini engelliyor.

## 4. Anayasa Etki Analizi

| Katman | Durum |
|--------|-------|
| Kırmızı Bölge | **Dokunulmadı.** Backend, config, engine, API — hiçbiri değişmedi. |
| Sarı Bölge | **Dokunulmadı.** |
| Yeşil Bölge | `desktop/src/components/TopBar.jsx` (3 string + 3 yorum), `tests/critical_flows/test_static_contracts.py` (+Flow 4m). |
| Siyah Kapı | **Dokunulmadı.** |
| Değişmez Kurallar | Hiçbir kural etkilenmedi — saf UI etiket değişikliği. |

Kapsam minimum: tek bileşen, üç string, mantık yok. Veri akışı (`/api/account` polling → `account.daily_pnl` → `dailyPnl` → render) aynen korundu.

## 5. Doğrulama

### 5.1 Kritik Akış Testleri

```
python -m pytest tests/critical_flows -q --tb=short
```

Sonuç: **46 passed in 3.08s** (45 baseline + yeni Flow 4m). Mevcut 3 syntax uyarısı `test_no_rogue_mt5_initialize_calls` içinde regex kaçış sorunu — bu commit ile ilgisiz, backlog.

### 5.2 Windows Production Build

```
python .agent/claude_bridge.py build
```

Sonuç:
- 728 modül dönüştürüldü
- 2.59 saniye
- 0 hata
- `index.js` 886.43 kB (gzip: 253.80 kB)
- `index.css` 90.52 kB (gzip: 15.07 kB)

### 5.3 Canlı Doğrulama Yöntemi

Uygulama yeniden başlatıldığında TopBar:
- **Önce:** `Bakiye | Equity | Floating | Günlük K/Z (MT5) +2500 TRY`
- **Sonra:** `Bakiye | Equity | Floating | Günlük K/Z (Snapshot) +2500 TRY`

Tooltip hover:
- **Önce:** "MT5 günlük P/L (gerçek zamanlı)"
- **Sonra:** "Günlük P/L — risk_snapshots tablosundan (2 sn polling)"

Değer ve renk (profit/loss) aynı kalıyor, sadece etiket doğru kaynağı söylüyor.

## 6. Değişen Dosyalar

1. `desktop/src/components/TopBar.jsx`
2. `tests/critical_flows/test_static_contracts.py`
3. `docs/USTAT_GELISIM_TARIHCESI.md`
4. `docs/2026-04-11_session_raporu_A10_topbar_gunluk_kz_etiketi.md`

## 7. Versiyon Durumu

Değişen satır sayısı ~10 (etiket + yorum + test). v6.0.0 sabit kaldı. Changelog #176 girişi v6.0.0 "ÜSTAT Plus V6.0" bloğu Fixed başlığı altına #175, #174, #173'ten önce eklendi.

## 8. Sonraki Adım

Bu A10 kapandı. Kalan audit öncelikleri (kritiklik + atomiklik dengesi):

- **A18** — Pozisyon `/5` sayacı config'e bağla (H2) — basit config bind
- **A19** — KILL_HOLD_DURATION config'e taşı (H5) — basit sabit taşıma
- **A5** — Version sabiti tekilleştirme (H1) — TopBar + Settings, runtime fetch
- **A15** — Error resolve message_prefix (B18) — A14 devamı, DB schema kontrolü
- **A6** — Performance equity vs deposits (B14) — deposit/withdrawal tracking
- **A8** — Hibrit MT5 SL/TP görünürlüğü (K10) — Dashboard tablosu
- **B8** — Dashboard "Otomatik Pozisyon Özeti" 45 vs 31 tutarsızlığı
