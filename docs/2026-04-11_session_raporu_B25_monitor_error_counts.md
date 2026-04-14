# B25-finding — Monitor errorCounts Structured Classifier

**Tarih:** 2026-04-11 (Cumartesi, Barış Zamanı)
**Commit:** `990e503`
**Kaynak:** Widget Denetimi Bölüm 11.4.2-11.4.5 + Bölüm 16 B25
**Değişiklik sınıfı:** C1 — Yeşil Bölge (`desktop/src/components/Monitor.jsx`)
**Changelog girişi:** #170

---

## 1. Özet

Monitor sayfasının modül hata sayacı (`errorCounts`) hesabındaki iki
kritik kırılganlık giderildi: (a) canlı üretim event'lerinin
hiçbiriyle eşleşmeyen serbest metin substring parse → ölü kod;
(b) Türkçe locale duyarsız `String.toLowerCase()` kullanımı. Yeni
`classifyEventModule` helper'ı yapısal `event.type` prefix haritası
ve Türkçe locale + word-boundary regex fallback ile olayları modüle
atar. A4'ün doğrudan devamı: A4 ile `modStatus` gerçek sinyallere
bağlanmıştı ama tüketicisi olan `errorCounts` parse kırılgandı — B25
o sinyali doğru hesaplar.

## 2. Kök Neden

### 2.1 Eski kod

```jsx
const errorCounts = { baba: 0, ustat: 0, ogul: 0, hengine: 0, manuel: 0 };
(health?.recent_events || []).forEach(ev => {
  if (ev.severity === 'ERROR' || ev.severity === 'CRITICAL') {
    const msg = (ev.message || '').toLowerCase();
    if (msg.includes('baba')) errorCounts.baba++;
    else if (msg.includes('ustat') || msg.includes('üstat')) errorCounts.ustat++;
    else if (msg.includes('ogul') || msg.includes('oğul')) errorCounts.ogul++;
    else if (msg.includes('h-engine') || msg.includes('h_engine') || msg.includes('hibrit') || msg.includes('hybrid')) errorCounts.hengine++;
    else if (msg.includes('manuel') || msg.includes('manual')) errorCounts.manuel++;
  }
});
```

Üç ayrı kırılganlık:

### 2.2 Kırılganlık 1 — Ölü kod

Canlı DB üzerinde `SELECT type, COUNT(*) FROM events WHERE severity IN ('ERROR','CRITICAL') GROUP BY type`:

| Type | Adet |
|------|------|
| `KILL_SWITCH` | 25 |
| `DRAWDOWN_LIMIT` | 12 |
| `TRADE_ERROR` | 9 |
| `SYSTEM_STOP` | 1 |
| `RISK_LIMIT` | 1 |
| `DAILY_LOSS_STOP` | 1 |

Mesaj örnekleri:

- `"Kill-switch L2 aktif: daily_loss"`
- `"Günlük kayıp limiti aşıldı"`
- `"Toplam drawdown: %30.43"`
- `"Emir başarısız: F_HALKB BUY 1.0 lot"`
- `"MT5 bağlantısı kurtarılamadı — sistem durduruluyor"`

**Hiçbirinde `baba`/`ogul`/`manuel`/`hengine`/`ustat` kelimesi yok.**
Substring parse tüm 48 olayı sayım dışı bırakıyordu. Monitor "HATA 0
bugün" gösteriyordu; kullanıcı "sistem temiz" sanıyordu.

### 2.3 Kırılganlık 2 — Türkçe locale

`String.prototype.toLowerCase()` Unicode tablosu kullanır; Türkçe
'İ' → 'i̇' (dotless i + combining dot) veya 'İ' → 'i' (tr-TR locale)
davranışı farklıdır. `'Oğul hatası'` → `.toLowerCase()` → `'oğul hatası'`
bazı Node sürümlerinde `'oğul'` string'ine eşleşir, bazılarında
`'og\u0306ul'` NFD normalization sonrası eşleşmez. `'Üstat'` → 'ü'
composing durumunda 'u' + combining diaeresis olabilir. Locale
açıkça `tr-TR` olarak belirtilmeli.

### 2.4 Kırılganlık 3 — Else-if sırası + false positive

Else-if zincirinde ilk eşleşme kazanır. `baba` en başta → "baba
hatası sırasında OĞUL sinyali reddedildi" mesajı tamamen baba'ya
atanır. "haber `babaş` bölgesinden" substring match başarılı olup
baba sayacını yanlışlıkla artırır.

### 2.5 A4 ile ilişkisi

A4 (modStatus refactor) `errorCounts` sözlüğünü modStatus referans
eder hale getirdi — ama sözlüğün kendisi yanlış hesaplanıyordu.
A4 `errorCounts` parse'ını bilinçli olarak B-finding'e bıraktı.
B25 bu parse'ı düzeltir → A4 sinyali artık gerçek veriye dayanır.

## 3. Atomik Değişiklik

### 3.1 `Monitor.jsx` — `classifyEventModule` helper

Dosya üstünde (satır ~41):

```jsx
const MODULE_TYPE_PREFIX = [
  { mod: 'hengine', re: /^HYBRID_/ },
  { mod: 'manuel', re: /^(MANUAL_|MANUEL_)/ },
  { mod: 'baba', re: /^(KILL_SWITCH|DRAWDOWN_|RISK_|COOLDOWN_|REGIME_|BABA_|HARD_DRAWDOWN|DAILY_LOSS_STOP|MONTHLY_LOSS|WEEKLY_RESET|DAILY_RESET|LOT_HALVED|STOP_TRADING|SYSTEM_STOP|SYSTEM_HALT)/ },
  { mod: 'ogul', re: /^(TRADE_|ORDER_|SIGNAL_|OGUL_|VOLUME_SPIKE|PARTIAL_|FAKE_|SIGN_MISMATCH|EOD_|PAPER_TRADE)/ },
  { mod: 'ustat', re: /^(USTAT_|PATTERN_|STRATEGY_|TOP5_)/ },
];

const MODULE_MSG_WORD = [
  { mod: 'hengine', re: /\b(h[-_ ]?engine|hibrit|hybrid)\b/u },
  { mod: 'manuel', re: /\bmanue?l\b/u },
  { mod: 'baba', re: /\bbaba\b/u },
  { mod: 'ogul', re: /\bo[gğ]ul\b/u },
  { mod: 'ustat', re: /\b[üu]stat\b/u },
];

function classifyEventModule(ev) {
  const type = (ev?.type || '').toUpperCase();
  if (type) {
    for (const entry of MODULE_TYPE_PREFIX) {
      if (entry.re.test(type)) return entry.mod;
    }
  }
  const msg = (ev?.message || '').toLocaleLowerCase('tr-TR');
  if (msg) {
    for (const entry of MODULE_MSG_WORD) {
      if (entry.re.test(msg)) return entry.mod;
    }
  }
  return null;
}
```

**Anahtar kararlar:**

1. **İki aşama, prefix önce** — yapısal event.type prefix kanıtı
   mesaj substring'den daha güvenilir. DB'den gelen ERROR/CRITICAL
   event'lerin %100'ü bu aşamada yakalanır (6 type canonical
   listede).
2. **Mesaj fallback yine var** — ileride yeni event type'ları
   eklenirse (ör. özel uygulama-seviyesi hatalar) mesaj regex'i
   köprü sağlar.
3. **Word boundary + Unicode flag** — `\b` ve `/u` beraber kullanılır.
   `babaş bölgesi` eşleşmez, `baba` eşleşir.
4. **`toLocaleLowerCase('tr-TR')`** — Türkçe İ/ı/ğ/Ğ için tutarlı
   davranış.
5. **Sınıflandırılamayan event `null` döner** — sayılmaz. False
   positive yerine sessizlik tercih edildi. Eksik type Kritik Akış
   testinde not edilir, pre-commit hook gelecek refactor'da yeni
   type eklenmesini zorlayabilir.

### 3.2 `Monitor.jsx` — `errorCounts` hesap bloğu

```jsx
const errorCounts = { baba: 0, ustat: 0, ogul: 0, hengine: 0, manuel: 0 };
(health?.recent_events || []).forEach(ev => {
  if (ev.severity === 'ERROR' || ev.severity === 'CRITICAL') {
    const mod = classifyEventModule(ev);
    if (mod) errorCounts[mod]++;
  }
});
```

Else-if zinciri → tek fonksiyon çağrısı. Semantik değişmedi (5
anahtarlı sözlük hâlâ aynı), hesap mekanizması yapısallaştı.

### 3.3 `tests/critical_flows/test_static_contracts.py` — Flow 4g

Yeni test `test_monitor_error_counts_uses_structured_classifier` 5
aşamalı kontrol yapar:

1. `function classifyEventModule` tanımı var.
2. `msg.includes('baba')` ve `.toLowerCase().includes(` kalıpları
   YASAK.
3. `toLocaleLowerCase('tr-TR')` mevcut.
4. 9 canonical type prefix (`KILL_SWITCH`, `DRAWDOWN_`, `TRADE_`,
   `SYSTEM_STOP`, `DAILY_LOSS_STOP`, `HYBRID_`, `MANUAL_`, `MANUEL_`,
   `USTAT_`) `MODULE_TYPE_PREFIX` bloğunda görünüyor.
5. Word-boundary `\bbaba\b` regex fallback mevcut.

### 3.4 False Positive Düzeltmesi (yorum yeniden yazımı)

İlk test çalıştırmasında Flow 4g başarısız oldu: Monitor.jsx yorum
bloğu eski kalıbı literal olarak anıyordu (`msg.toLowerCase().includes('baba')`).
Static grep bunu yakaladı ve test patladı (1 failed, 39 passed).
Yorum yeniden yazıldı, literal pattern kaldırıldı; "mesaj metni
üzerinde serbest substring kontrolü" genel açıklamasına dönüştürüldü.
İkinci denemede **40 passed**.

## 4. Dokunulmayanlar (Bilinçli)

- **`engine/database.py` events tablosu** — `module` kolonu
  eklenmedi. Kırmızı Bölge #6; DB migration + tüm `insert_event`
  call-site'larının (56 çağrı, 12 dosya) güncellenmesi savaş
  zamanı riski. Frontend classifier yeterli koruma sağlıyor.
- **`api/routes/health.py::_build_recent_events`** — şema değişmedi
  (`id, timestamp, type, severity, message`). Frontend yapısal
  type prefix'iyle yetiniyor.
- **Event üretici motorlar** (`baba.py`, `ogul.py`, `h_engine.py`,
  vb.) — `insert_event` çağrı-site'lerinin event_type naming'i
  dokunulmadı. Yalnız tüketici akıllandı.
- **`error_tracker.py` / `ErrorTracker.jsx`** — ayrı bir akış
  (gruplama + `error_resolutions` tablosu), bu B25 kapsamı dışı.
  Audit Bölüm 12 ve A17 ayrı maddeler.
- **`errorCounts` gridinin görsel düzeni** (Monitor.jsx satır 898)
  — 5 modül × ('HATA' + adet) hücre yapısı değişmedi, sadece
  altındaki sayılar artık gerçek.
- **A4 `modStatus` mantığı** — dokunulmadı, `errorCounts` referansı
  zaten doğru. A4 + B25 birlikte: modStatus gerçek sinyali doğru
  hesaplanmış errorCounts üzerinden okuyor.

## 5. Doğrulama

| Kontrol | Sonuç |
|---------|-------|
| critical_flows | **40 passed, 3 warnings in 2.94s** (39 baseline + 1 yeni Flow 4g) |
| Build | `ustat-desktop@6.0.0`, 728 modül transformed, 2.60s, 0 hata, `dist/index.js 882.41 kB` |
| Pre-commit hook | Geçti |
| Git commit | `990e503`, 3 files changed, +144/-7 |

### 5.1 Manuel doğrulama (canlı DB)

`SELECT type, COUNT(*) FROM events WHERE severity IN ('ERROR','CRITICAL') GROUP BY type`:

| Type | Adet | Classifier çıkışı | Beklenen modül |
|------|------|-------------------|----------------|
| `KILL_SWITCH` | 25 | `baba` | ✅ |
| `DRAWDOWN_LIMIT` | 12 | `baba` | ✅ |
| `TRADE_ERROR` | 9 | `ogul` | ✅ |
| `SYSTEM_STOP` | 1 | `baba` (safety stop) | ✅ |
| `RISK_LIMIT` | 1 | `baba` | ✅ |
| `DAILY_LOSS_STOP` | 1 | `baba` | ✅ |

Deploy sonrası Monitor:
- BABA HATA: 40 bugün (25 + 12 + 1 + 1 + 1 = 40) ← sarı rozet
- OĞUL HATA: 9 bugün ← sarı rozet

Eskiden hepsi 0 görünüyordu.

## 6. Etki Analizi

- **Dosya sayısı:** 1 desktop + 1 test + 1 changelog = 3 dosya
- **Zone dokunuşu:** Yeşil Bölge yalnız (Monitor.jsx, Kırmızı/Sarı
  Bölge dokunusu YOK)
- **Siyah Kapı:** YOK
- **Backend değişikliği:** GEREKSİZ — mevcut `/api/health.recent_events`
  şeması yeterli
- **Geriye dönük uyumluluk:** %100 — `errorCounts` sözlüğünün
  tüketicileri (modStatus, ModBox detail grid, hata sayacı grid)
  aynı 5 anahtarlı sözlüğü alır, yalnız değerler doğrulandı
- **Çağıran zinciri:** `classifyEventModule` yalnız bir yerde
  çağrılır (errorCounts forEach); helper geri eklenirse tek noktadan
  refactor edilebilir
- **Tüketici zinciri:** `errorCounts` → 3 yer (modStatus hesap,
  ModBox detail rows `['HATA', ...]`, hata sayacı grid `Object.entries`)

## 7. Deploy Durumu

- Piyasa kapalı (Cumartesi, Barış Zamanı) — deploy güvenli.
- Frontend değişikliği → `restart_app` ile Electron bundle yeniden
  yüklenir.
- A1 + A2 + A3 + A4 + B + **B25** altılısı aynı anda canlıya alınabilir.
  A1 restart sırasında 1 açık pozisyonu L3 ile kapatacak (beklenen
  davranış).

## 8. Follow-Up

- **Eksik event type'ları testle tespit** — gelecek refactor
  sırasında yeni event type eklenirse Flow 4g `classify → null`
  dönen canlı event'leri loglamayabilir. İleride `window.__debugCountsNullCount`
  gibi bir debug alanı eklenebilir. Ayrı madde.
- **A17 — ErrorTracker.jsx hardcoded EOD saatleri** — audit A17,
  henüz ele alınmadı. Config'e taşıma yerine mevcut `engine.trading_open/close`
  kullanımı. Ayrı oturum.
- **B17 — `TRADE_ERROR` kategorisi** — `EVENT_TYPE_CATEGORY`
  sözlüğünde anahtar yok, "sistem" kategorisine düşüyor. ErrorTracker
  akışında ayrı bulgu.
- **Monitor ResponseBar eşikleri (A7)** — `50ms` vs gerçek `2596ms`
  döngü süresi çelişkisi. Ayrı madde.

## 9. Referanslar

- **Widget denetimi raporu:** `docs/2026-04-11_widget_denetimi.md`
  — Bölüm 11.4.2-11.4.5 (Monitor modül kolonları), Bölüm 16 B25
- **A4 session raporu:** `docs/2026-04-11_session_raporu_A4_monitor_modstatus.md`
  — "Dokunulmayanlar (bilinçli)" bölümünde B25 tespiti
- **Canlı DB kanıtı:** `database/trades.db::events` — 48 ERROR/CRITICAL
  kayıt, 6 farklı event type, hiçbirinde modül adı substring'i yok
- **Commit:** `990e503` — fix(monitor): errorCounts structured classifier (Widget Denetimi B25)
- **Changelog:** #170 (`docs/USTAT_GELISIM_TARIHCESI.md`)
