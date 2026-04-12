# Oturum Raporu — A11 (S4): PRİMNET Eşikleri Görünür Kart

**Tarih:** 11 Nisan 2026
**Kategori:** Widget Denetimi — Priority 3 (S4 sessiz alan)
**Sınıf:** C1 (Yeşil Bölge frontend + CSS)
**Kapsam:** 2 frontend + 1 stil + 1 test + 1 changelog
**Durum:** Tamamlandı — atomik commit hazır

---

## 1. Sorun Tanımı

Widget Denetimi raporundaki **S4 / A11** maddesi: Hibrit İşlem panelinde
PRİMNET trailing ve hedef prim eşikleri (config'den `primnet.trailing_prim=1.5`,
`primnet.target_prim=9.5`) yalnızca `PrimnetDetail` modalı içinde görünüyordu.
Backend `/api/hybrid/status` zaten `primnet` alanını döndürüyordu fakat ana
Hibrit Özet ekranında bu eşikleri gösteren bir kart/rozet yoktu — kullanıcı
modal açmadan koruma seviyesini bilemiyordu.

---

## 2. Kök Sebep

`api/routes/hybrid_trade.py` `HybridStatusResponse.primnet = PrimnetConfig(...)`
ile canlı eşikleri akıtıyor (kanal sağlam) fakat `desktop/src/components/HybridTrade.jsx`
Özet kart bölümünde yalnız 4 kart vardı (Aktif Hibrit, Anlık Floating, Günlük
Hibrit K/Z, Günlük Limit). PRİMNET değerleri sadece `PrimnetDetail` modalında
tüketilmişti — gözden kaçan tüketici eklemesi.

---

## 3. Çözüm

### 3a) `desktop/src/components/HybridTrade.jsx`
Özet kart sırasına 5. kart eklendi:

```jsx
<div className="op-summary-card" title="PRİMNET trailing & hedef eşikleri ...">
  <span className="op-sc-label">PRİMNET Eşikleri</span>
  <span className="op-sc-value op-sc-value--primnet">
    Trailing <strong>{(hybridStatus.primnet?.trailing_prim ?? 1.5).toFixed(1)}</strong>
    {' · '}
    Hedef <strong>±{(hybridStatus.primnet?.target_prim ?? 9.5).toFixed(1)}</strong>
  </span>
</div>
```

- Optional chaining + `?? 1.5/9.5` fallback → eski API yanıtlarına da dayanıklı.
- `cardOrder` localStorage anahtarı dokunulmadı; 5 kart aynı `summary` SortableCard
  içinde olduğu için `parsed.length === DEFAULT_CARD_ORDER.length` kontrolü
  bozulmadı.

### 3b) `desktop/src/styles/theme.css`
Yeni `.op-sc-value--primnet` modifier sınıfı:

```css
.op-sc-value--primnet {
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.3px;
  color: var(--text-secondary);
}
.op-sc-value--primnet strong {
  color: var(--accent);
  font-weight: 700;
  font-size: 15px;
}
```

Diğer 4 kartın 22px büyük rakam görünümünden daha küçük; iki değer yan yana
sığacak biçimde ayarlandı.

### 3c) `tests/critical_flows/test_static_contracts.py`
**Flow 4zf** eklendi: `test_primnet_thresholds_visible_card`. 4 sözleşme noktası:

1. Backend kanalı sağlam mı? `PrimnetConfig` sınıfı + `HybridStatusResponse.primnet` alanı + route'ta `trailing_prim=h_engine._primnet_trailing` / `target_prim=h_engine._primnet_target` atamaları
2. Frontend tüketici yerinde mi? `'PRİMNET Eşikleri'` başlığı + `hybridStatus.primnet?.trailing_prim` / `target_prim` referansları
3. CSS modifier mevcut mu? `.op-sc-value--primnet`
4. Audit marker'ları (HybridTrade.jsx + theme.css)

### 3d) `docs/USTAT_GELISIM_TARIHCESI.md`
**#195** girişi #194 üzerine eklendi.

---

## 4. Test Sonuçları

```
python -m pytest tests/critical_flows -q --tb=short
========================
65 passed in 3.55s
========================
```

Baseline 64 → 65 (Flow 4zf eklendi).

---

## 5. Build Sonuçları

```
npm run build (vite v6.4.1)
✓ 730 modules transformed
dist/index.js   895.03 kB │ gzip: 256.51 kB
✓ built in 2.54s
```

Bundle boyutu artışı: +0.49 kB (5. kart + CSS modifier).

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
| Kırmızı Bölge dokunuşu | Yok |
| Sarı Bölge dokunuşu | Yok |
| Backend kod değişikliği | Yok (sadece okuma) |
| Sihirli sayı | Fallback değerleri 1.5/9.5 yalnız API down durumunda kullanılır, gerçek kaynak `config/default.json::hybrid.primnet` ve `h_engine._primnet_*` alanlarıdır |

---

## 7. Kalan İşler

- Atomik commit (5 dosya: HybridTrade.jsx, theme.css, test_static_contracts.py, USTAT_GELISIM_TARIHCESI.md, bu rapor)
- A7 (Baseline tekilleştirme) — sonraki backlog maddesi
