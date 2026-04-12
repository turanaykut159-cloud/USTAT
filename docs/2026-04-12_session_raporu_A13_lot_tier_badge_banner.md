# Oturum Raporu — A13 (H17): Lot çarpanı tier rozeti + banner

**Tarih:** 12 Nisan 2026
**Kategori:** Widget Denetimi — Priority 3 (H17 dead field follow-up)
**Sınıf:** C1 (Yeşil Bölge frontend-only)
**Kapsam:** 1 frontend bileşen + 1 stil + 1 test + 1 changelog + 1 rapor
**Durum:** Tamamlandı — atomik commit hazır

---

## 1. Sorun Tanımı

Risk Yönetimi sayfasının üst banner satırındaki "Lot Çarpanı" kartı sadece
sayısal değer gösteriyordu:

```
Lot Çarpanı
x0.50
```

`lot_multiplier=0.5` görüldüğünde operatör bunun nedenini ayırt edemiyordu:

- BABA graduated lot mu (cumulative loss)?
- Haftalık kayıp tetiklendi mi (`weekly_loss_halved=True`)?
- OLAY rejimi mi (`risk_multiplier=0`)?
- Kill-switch L1/L2 durumu mu?

Tek sayısal değer, "lot neden düştü" sorusuna yanıt vermiyordu — operatör
hangi katmanın aktif olduğunu görmek için Risk Yönetimi sayfasında
KillSwitchInfoModal açıp neden alanını okumak veya log dosyasına girmek
zorundaydı.

Audit notu (`docs/2026-04-11_widget_denetimi.md` A13):

> "Risk sayfasında graduated_lot_mult=1.0 değerinin 'Normal lot' / 'Yarım
> lot' rozet olarak göster. Haftalık kayıp sonrası devreye girdiğini
> banner ile göster."

H17 (#183) bu fakttin _backend_ tarafını çözmüştü — `RiskResponse` artık
yalnızca `lot_multiplier` alanını döner (eski `graduated_lot_mult`
placeholder kaldırıldı). A13 ise bu sayısal değerin görsel anlamlı
sunulması ile ilgili.

---

## 2. Çözüm

Frontend-only, tamamen Yeşil Bölge defansif iyileştirme. Backend
şemaları, BABA mantığı, risk hesaplama, motor sırası — hiçbiri
dokunulmadı.

### 2a) `desktop/src/components/RiskManagement.jsx`

**(i) `getLotTier(mult)` helper:**

```jsx
function getLotTier(mult) {
  if (mult == null || Number.isNaN(mult)) {
    return { label: '—', cls: 'lot-tier-unknown', hint: '' };
  }
  if (mult >= 0.99) {
    return {
      label: 'Normal Lot',
      cls: 'lot-tier-normal',
      hint: 'Tam risk: graduated azaltma uygulanmıyor.',
    };
  }
  if (mult >= 0.5) {
    return {
      label: 'Yarım Lot',
      cls: 'lot-tier-half',
      hint: 'Risk azaltma aktif (haftalık kayıp veya graduated lot).',
    };
  }
  if (mult >= 0.24) {
    return {
      label: 'Çeyrek Lot',
      cls: 'lot-tier-quarter',
      hint: 'Yoğun risk azaltma — günlük/haftalık birikmiş kayıp.',
    };
  }
  if (mult > 0) {
    return {
      label: 'Asgari Lot',
      cls: 'lot-tier-min',
      hint: 'Kritik risk seviyesi — minimum açılış.',
    };
  }
  return {
    label: 'Lot İptal',
    cls: 'lot-tier-blocked',
    hint: 'OLAY rejimi veya kill-switch — yeni işlem açılmaz.',
  };
}
```

Beş tier:

| mult aralığı | Label       | CSS sınıfı            | Renk      |
|--------------|-------------|------------------------|-----------|
| `>= 0.99`    | Normal Lot  | `lot-tier-normal`      | Yeşil     |
| `[0.5, 0.99)`| Yarım Lot   | `lot-tier-half`        | Sarı      |
| `[0.24, 0.5)`| Çeyrek Lot  | `lot-tier-quarter`     | Turuncu   |
| `(0, 0.24)`  | Asgari Lot  | `lot-tier-min`         | Kırmızı   |
| `<= 0`       | Lot İptal   | `lot-tier-blocked`     | Koyu kırmızı |
| `null/NaN`   | —           | `lot-tier-unknown`     | Gri       |

Sınırlar `>= 0.99` ile başlıyor çünkü BABA verdict `lot_multiplier`
genelde tam 1.0 dönüyor; floating-point gevşekliği için 0.01 tolerans.

**(ii) Lot Çarpanı kartına rozet:**

```jsx
<div className="risk-status-card">
  <span className="risk-status-label">Lot Çarpanı</span>
  <span className="risk-status-value">
    x{risk.lot_multiplier?.toFixed(2) ?? '—'}
  </span>
  <span
    className={`risk-lot-tier-badge ${lotTier.cls}`}
    title={lotTier.hint}
  >
    {lotTier.label}
  </span>
</div>
```

**(iii) Lot azaltma banner'ı:**

```jsx
{lotReduced && (
  <div className={`risk-lot-banner ${lotTier.cls}`}>
    <span className="risk-lot-banner-icon">⚠</span>
    <span className="risk-lot-banner-text">
      <strong>Lot çarpanı düşürüldü:</strong> x
      {risk.lot_multiplier?.toFixed(2) ?? '—'} ({lotTier.label}). {lotTier.hint}
      {risk.risk_reason ? ` Neden: ${risk.risk_reason}` : ''}
    </span>
  </div>
)}
```

`lotReduced = (risk.lot_multiplier ?? 1.0) < 0.99` — sadece azaltma aktif
olduğunda banner çıkıyor. `risk.risk_reason` (RiskResponse'un mevcut
alanı) doluysa banner sonuna ekleniyor — operatör tek bakışta ne, ne
kadar, neden cevabını alır.

### 2b) `desktop/src/styles/theme.css`

Yeni CSS sınıfları:

```css
.risk-lot-tier-badge { /* kompakt rozet, padding 2px 8px, font 10px */ }
.risk-lot-tier-badge.lot-tier-normal { /* yeşil renk + açık fon */ }
.risk-lot-tier-badge.lot-tier-half { /* sarı renk + açık fon */ }
.risk-lot-tier-badge.lot-tier-quarter { /* turuncu, daha koyu */ }
.risk-lot-tier-badge.lot-tier-min { /* kırmızı, açık fon */ }
.risk-lot-tier-badge.lot-tier-blocked { /* kırmızı, koyu fon */ }
.risk-lot-tier-badge.lot-tier-unknown { /* gri */ }

.risk-lot-banner {
  /* full-width banner, sarı border varsayılan */
  /* lot-tier-quarter, lot-tier-min, lot-tier-blocked → kırmızı varyant */
}
.risk-lot-banner-icon { /* uyarı ikonu, sabit boyut */ }
.risk-lot-banner-text strong { /* warning veya loss rengi */ }
```

### 2c) `tests/critical_flows/test_static_contracts.py`

**Flow 4zl** eklendi: `test_risk_management_lot_tier_badge_and_banner`.
5 sözleşme noktası:

1. `getLotTier` helper fonksiyonu mevcut + 5 tier label string'i
   ('Normal Lot', 'Yarım Lot', 'Çeyrek Lot', 'Lot İptal')
2. `lotTier = getLotTier(risk.lot_multiplier)` çağrısı + `risk-lot-tier-badge`
   className kullanımı
3. `{lotReduced && (...)}` koşullu banner render bloku +
   `risk-lot-banner` className
4. `theme.css` içinde 6 CSS sınıfı varlığı (`lot-tier-normal/half/quarter/min/blocked` +
   `risk-lot-banner`)
5. `A13` audit markerı her iki dosyada

### 2d) `docs/USTAT_GELISIM_TARIHCESI.md`

**#201** girişi #200 üzerine eklendi.

---

## 3. Test Sonuçları

```
python -m pytest tests/critical_flows -q
========================
71 passed, 3 warnings in 3.29s
========================
```

Baseline 70 → 71 (Flow 4zl eklendi).

---

## 4. Build Sonuçları

```
ustat-desktop@6.0.0 build
> vite build

vite v6.4.1 building for production...
✓ 730 modules transformed.
dist/index.html                 1.08 kB │ gzip:   0.60 kB
dist/assets/index-D4Cik-SP.css 92.80 kB │ gzip:  15.45 kB
dist/assets/index-CS3C3G2W.js  897.92 kB │ gzip: 257.20 kB
✓ built in 2.56s
```

730 modül, 897.92 kB (+1.15 kB; helper + render bloku + CSS), 0 hata.

---

## 5. Anayasa Uyumu Doğrulama

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
| Siyah Kapı fonksiyonları (31) | Hiçbiri değişmedi |
| Kırmızı Bölge dokunuşu | Yok |
| Sarı Bölge dokunuşu | Yok |
| Backend motor değişikliği | Yok (frontend-only) |
| BABA `lot_multiplier` hesaplama mantığı | Değişmedi |
| RiskResponse şeması | Değişmedi (mevcut alan okunuyor) |
| Sihirli sayı | Yok (eşikler tier helper'da tek noktada) |

**Değişiklik sınıfı:** C1 — Yeşil Bölge frontend defansif iyileştirme.
Backend semantik veya davranış değişikliği YOK.

---

## 6. Davranış

| lot_multiplier | Rozet | Banner | Renk |
|----------------|-------|--------|------|
| 1.0 (varsayılan) | Normal Lot | Yok | Yeşil |
| 0.75 (graduated) | Yarım Lot | "Lot çarpanı düşürüldü: x0.75 (Yarım Lot). Risk azaltma aktif..." | Sarı |
| 0.5 (haftalık kayıp) | Yarım Lot | Yukarıdakiyle aynı + risk_reason eklenir | Sarı |
| 0.25 (kritik) | Çeyrek Lot | "Lot çarpanı düşürüldü: x0.25 (Çeyrek Lot). Yoğun risk azaltma..." | Turuncu/Kırmızı |
| 0.1 (asgari) | Asgari Lot | "Lot çarpanı düşürüldü: x0.10 (Asgari Lot). Kritik risk seviyesi..." | Kırmızı |
| 0.0 (OLAY/L2/L3) | Lot İptal | "Lot çarpanı düşürüldü: x0.00 (Lot İptal). OLAY rejimi veya kill-switch..." | Koyu kırmızı |

---

## 7. Geriye Dönük Uyumluluk

- Eski risk response (`lot_multiplier=1.0`) → "Normal Lot" rozeti, banner yok
- `lot_multiplier=null/undefined` → "—" placeholder rozeti
- `lot_multiplier=NaN` → graceful degrade (unknown tier)
- Mevcut tüm Risk Yönetimi davranışları (drawdown bar'ları, sayaçlar, Kill-switch modal) etkilenmedi

---

## 8. Kalan İşler

- Atomik commit (4 dosya: RiskManagement.jsx, theme.css, test_static_contracts.py, USTAT_GELISIM_TARIHCESI.md, bu rapor)
- Sonraki madde: Backlog'da kalan A16 (Manuel watchlist), A20 (NABIZ config), A27 (Operator approve)
