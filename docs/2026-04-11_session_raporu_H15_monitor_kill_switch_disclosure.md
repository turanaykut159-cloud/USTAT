# Oturum Raporu — H15: Monitor Kill-Switch Seviyeleri Yaklaşık Disclosure

**Tarih:** 11 Nisan 2026 (Cumartesi — Barış Zamanı)
**Konu:** Widget Denetimi H15 — Monitor L1/L2/L3 kill-switch seviyeleri UI'de "yaklaşık" disclosure eksikliği
**Değişiklik Sınıfı:** C1 (Yeşil Bölge)
**İşlem Tipi:** Tek atomik değişiklik (1 JSX dosyası + 1 test)

---

## 1. Kapsam

Widget Denetimi `docs/2026-04-11_widget_denetimi.md` Bölüm 16.3 H15:
> **Monitor (11.8)** — BABA L1/L2/L3 eşikleri UI'de "yaklaşık" olarak hardcode
> ama "yaklaşık" notu yok — kullanıcı gerçek eşik sanar. (Orta kritiklik)

Bu madde çözüldü. Monitor sayfası RİSK & KİLL-SWİTCH bloğu artık:

- Header'ında `~YAKLAŞIK` disclosure badge gösterir (hover tooltip ile).
- Her L1/L2/L3 kartında `~%{pct}` prefix ile yüzde render eder.
- Her kart ayrı `title` tooltip ile "Yaklaşık görselleştirme — BABA'nın
  gerçek eşiği değil" notunu taşır.
- 0.5 / 0.75 / 1.0 sihirli çarpanları dokümante sabite (`KS_LEVEL_PCT_FRACTIONS`)
  taşındı, üzerinde 8 satırlık yorum bloğu BABA'nın gerçek event-driven
  tetikleyicilerini açıklar.

---

## 2. Kök Neden

Önceki durum (`desktop/src/components/Monitor.jsx`):

```jsx
// Kill-switch level thresholds (yaklaşık hesaplama)
const ksLevels = [
  { lvl: 'L1', label: 'UYARI', pct: (limDaily * 0.5).toFixed(1) },
  { lvl: 'L2', label: 'DURDUR', pct: (limDaily * 0.75).toFixed(1) },
  { lvl: 'L3', label: 'KRİTİK', pct: limDaily.toFixed(1) },
];
```

Render:

```jsx
<div>RİSK & KİLL-SWİTCH</div>
...
<div>{lvl}</div>            {/* L1 / L2 / L3 */}
<div>{label}</div>          {/* UYARI / DURDUR / KRİTİK */}
<div>%{pct}</div>           {/* %0.9 / %1.35 / %1.8 */}
```

Kod yorumu ("yaklaşık hesaplama") sadece geliştirici tarafından görünür;
kullanıcı UI'de hiçbir disclosure görmüyordu. "L1 UYARI %0.9" mesajını
okuyan kullanıcı günlük kayıp %0.9'a ulaştığında L1 tetikleneceğini
sanabilirdi — bu YANLIŞ bir mental model çünkü:

**BABA gerçek L1/L2/L3 tetikleyicileri event-driven** (bkz. `engine/baba.py`):

| Seviye | Gerçek Tetikleyiciler |
|--------|------------------------|
| L1 | Anomali / haber / kontrat-özel engel (`_killed_symbols`), scalar eşik YOK |
| L2 | Günlük/haftalık/aylık kayıp limiti aşımı, 3 ardışık kayıp, OLAY rejimi |
| L3 | Hard drawdown ≥%15, flash crash, felaket kapanış, L2→L3 eskalasyon |

Yani UI'deki 0.5/0.75/1.0 çarpanlarla elde edilen yüzdeler BABA'daki
hiçbir gerçek eşiği temsil etmiyor — sadece görsel doluluk barı için
bir "ilerleme hissi" veriyordu.

**Dürüst çözüm:** UI'de illüstratif olduğunu AÇIKÇA belirtmek.

---

## 3. Yapılan Değişiklikler

### 3.1 `desktop/src/components/Monitor.jsx`

Üç hedefli değişiklik:

**A) `ksLevels` hesaplaması refactor (satır 396-401):**

```jsx
// ── Kill-switch seviye göstergesi (Widget Denetimi H15) ──────
// BABA'nın gerçek L1/L2/L3 kill-switch tetikleyicileri event-driven:
//   L1: anomali / kontrat engeli (scalar eşik YOK — haber, anomali)
//   L2: günlük-aylık kayıp limiti, 3 ardışık kayıp, OLAY rejimi
//   L3: hard drawdown ≥%15, flash crash, felaket kapanış
// Aşağıdaki yüzdeler kullanıcıya YAKLAŞIK görselleştirme sunar —
// BABA'daki gerçek eşik değil. Gerçek değerler Risk Yönetimi sayfasında.
// KS_LEVEL_PCT_FRACTIONS: görsel doluluk için illüstratif payda.
const KS_LEVEL_PCT_FRACTIONS = { L1: 0.5, L2: 0.75, L3: 1.0 };
const ksLevels = [
  { lvl: 'L1', label: 'UYARI',  pct: (limDaily * KS_LEVEL_PCT_FRACTIONS.L1).toFixed(1) },
  { lvl: 'L2', label: 'DURDUR', pct: (limDaily * KS_LEVEL_PCT_FRACTIONS.L2).toFixed(1) },
  { lvl: 'L3', label: 'KRİTİK', pct: (limDaily * KS_LEVEL_PCT_FRACTIONS.L3).toFixed(1) },
];
```

**B) Header'da disclosure badge (RİSK & KİLL-SWİTCH):**

```jsx
<div style={{ ..., display: 'flex', alignItems: 'center', gap: 6 }}>
  <span>RİSK & KİLL-SWİTCH</span>
  <span
    title={
      "BABA'nın gerçek L1/L2/L3 kill-switch tetikleyicileri event-driven:\n" +
      "L1 — anomali / haber / kontrat engeli (scalar eşik yok)\n" +
      "L2 — günlük/aylık kayıp limiti, 3 ardışık kayıp, OLAY rejimi\n" +
      "L3 — hard drawdown ≥%15, flash crash\n\n" +
      "Aşağıdaki yüzdeler YAKLAŞIK görselleştirme — BABA'daki gerçek eşik DEĞİL. " +
      "Gerçek değerler için Risk Yönetimi sayfasına bakın (H15)."
    }
    style={{ ..., cursor: 'help' }}
  >
    ~YAKLAŞIK
  </span>
</div>
```

**C) Her ksLevel kartında `~%` prefix + tooltip:**

```jsx
<div
  key={lvl}
  style={{ ... }}
  title="Yaklaşık görselleştirme — BABA'nın gerçek eşiği değil (H15)"
>
  <div>{lvl}</div>
  <div>{label}</div>
  <div>~%{pct}</div>  {/* eskiden %{pct} */}
</div>
```

### 3.2 `tests/critical_flows/test_static_contracts.py`

Flow 4s eklendi (`test_monitor_kill_switch_levels_are_disclosed_as_approximate`).
4 aşamalı statik kontrol:

(a) `KS_LEVEL_PCT_FRACTIONS` sabiti var + `.L1`, `.L2`, `.L3` okuma
    zincirlerinden geçiyor (inline 0.5/0.75 sihirli sayıların geri
    eklenmesini engeller).
(b) Render header'ında `~YAKLAŞIK` disclosure badge string'i mevcut.
(c) ksLevel kartında `~%{pct}` prefix mevcut (eski `%{pct}` render
    pattern'inin geri gelmesini engeller).
(d) Tooltip içinde `gerçek eşik` veya `gerçek eşiği` açıklaması mevcut.

Gelecekte refactor sırasında bu disclosure'lardan biri silinirse
pre-commit hook commit'i bloklar.

### 3.3 `docs/USTAT_GELISIM_TARIHCESI.md`

#182 girişi eklendi (#181'den önce): 1 kod dosyası + 1 test, test/build
sonuçları, Anayasa uyumu, dokunulmayan bilinçli kalemler.

---

## 4. Neden Config'e Taşınmadı

H15 audit ipucu sabit çarpanları işaret ediyordu, ama çözüm olarak
config'e taşımak DOĞRU olmaz:

1. **İkinci "yalan eşik" kaynağı riski.** Eğer `config.kill_switch_multipliers`
   gibi bir anahtar eklenirse, kullanıcı veya geliştirici bu değerin
   "BABA'nın gerçek eşiği" olduğunu düşünüp değiştirmeye çalışabilir.
   Config'e koymak = "bu önemli bir ayar" sinyali verir, ki değildir.
2. **Çarpanlar frontend-only görsel aid.** BABA'nın gerçek L1/L2/L3
   kararları event-driven — scalar eşik YOK. `limDaily * 0.5` değeri
   BABA'daki hiçbir sayıyla eşleşmez.
3. **Dürüst çözüm: illüstratif olduğunu belirtmek.** UI'de `~YAKLAŞIK`
   badge + tooltip + kod yorumunda açıklama yeterli — kullanıcı ne
   gördüğünü doğru yorumlar.

Sonuç: sihirli sayılar kaldırıldı (local dokümante sabite taşındı),
kullanıcıya dürüst disclosure eklendi, ama çarpanlar frontend-side
kaldı.

---

## 5. Anayasa Uyumu

- **Kırmızı Bölge dokunuşu:** YOK. `engine/baba.py`, `engine/ogul.py`,
  `engine/mt5_bridge.py`, `config/default.json` — hiçbirine dokunulmadı.
- **Sarı Bölge dokunuşu:** YOK.
- **Yeşil Bölge dosyaları:** `desktop/src/components/Monitor.jsx`,
  `tests/critical_flows/test_static_contracts.py`,
  `docs/USTAT_GELISIM_TARIHCESI.md`.
- **Siyah Kapı fonksiyonu:** Dokunulmadı. BABA'nın `_activate_kill_switch`,
  `_check_hard_drawdown`, `_check_monthly_loss`, `check_risk_limits`
  fonksiyonları tamamen korunmuş durumda.
- **Sihirli sayı:** 0.5 / 0.75 / 1.0 inline çarpanları kaldırıldı,
  dokümante `KS_LEVEL_PCT_FRACTIONS` sabitine taşındı.
- **Çağrı sırası:** Dokunulmadı (BABA → OĞUL → H-Engine → ÜSTAT).
- **Config değişikliği:** YOK.
- **Motor davranışı:** Değişmedi. Sadece UI dürüstlük katmanı eklendi.

---

## 6. Test ve Build Sonuçları

### 6.1 Kritik akış testleri

```
python -m pytest tests/critical_flows -q --tb=short
```

Sonuç: **52 passed, 3 warnings in 3.18s**. Flow 4s yeni eklendi, diğer
51 flow dokunulmadan geçti.

### 6.2 Windows production build

```
python .agent/claude_bridge.py build
```

Sonuç: **başarılı**, `ustat-desktop@6.0.0`, 728 modül transform edildi,
2.68 s, `index.js` 889.46 kB (gzip 254.84 kB), `index.css` 90.52 kB.

---

## 7. Versiyon Durumu

Tek atomik C1 düzeltme, ~25 satır net ekleme. Versiyon `v6.0.0` korunuyor.

---

## 8. Dosya Listesi

1. `desktop/src/components/Monitor.jsx` (+25 / -7 satır — KS_LEVEL_PCT_FRACTIONS sabiti, header badge, ksLevel prefix/tooltip)
2. `tests/critical_flows/test_static_contracts.py` (+60 satır — Flow 4s)
3. `docs/USTAT_GELISIM_TARIHCESI.md` (+1 madde — #182)
4. `docs/2026-04-11_session_raporu_H15_monitor_kill_switch_disclosure.md` (yeni — bu dosya)

---

## 9. Dokunulmayanlar (Bilinçli)

- **`engine/baba.py` kill-switch mantığı** — Kırmızı Bölge + Siyah Kapı,
  scope dışı. H15 pure UI disclosure işidir.
- **Drawdown barları (GÜNLÜK DD / HAFTALIK DD / FLOATING P&L)** — Bu
  değerler zaten `risk?.max_daily_loss`, `risk?.max_weekly_loss`,
  `risk?.max_floating_loss` üzerinden backend canonical'ı okuyor. Onlar
  için "yaklaşık" disclosure gerekmez çünkü gerçek BABA eşikleriyle
  birebir eşleşiyorlar (config → baba.py → risk state → /api/risk →
  Monitor).
- **Config anahtarı eklemek** — yukarıda gerekçelendirildi (yalan eşik
  kaynağı riski).
- **TopBar kill-switch rozeti** — TopBar L1/L2/L3'ü `kill_switch_level`
  sayısı olarak gösterir, yüzde çarpanı kullanmıyor, yanıltıcı değil.

---

## 10. Sonuç

Widget Denetimi H15 maddesi tamamen kapatıldı. Monitor sayfası artık
kullanıcıya L1/L2/L3 yüzdelerinin BABA'daki gerçek kill-switch
eşikleri OLMADIĞINI açıkça belirtiyor. `~YAKLAŞIK` header badge,
`~%{pct}` kart prefix'leri ve üç ayrı tooltip ile kullanıcı hatalı
mental modelden korunuyor. Sihirli çarpanlar dokümante edilmiş local
sabite taşındı — okunabilirlik ve gelecekteki refactor güvenliği
artırıldı. Flow 4s statik sözleşme testi bu disclosure'ların silinmesini
engeller.

Sonraki aday: H17 (graduated_lot_mult Risk Yönetimi'nde gösterilmiyor —
Orta), H8 (NABIZ TABLE_THRESHOLDS — Orta), H12 (Ayarlar açık tema
tıklanabilir ama eksik — Orta) veya H7/H9/H11/H13/H16/H18 (Düşük).
Sıradaki pick aynı disiplinle devam edecek.
