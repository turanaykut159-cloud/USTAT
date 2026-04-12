# Oturum Raporu — A24 (K2): Hibrit handleCheck/handleTransfer try/catch

**Tarih:** 12 Nisan 2026
**Kategori:** Widget Denetimi — Priority 3 (K2 kritik)
**Sınıf:** C1 (Yeşil Bölge frontend)
**Kapsam:** 1 frontend + 1 test + 1 changelog + 1 rapor
**Durum:** Tamamlandı — atomik commit hazır

---

## 1. Sorun Tanımı

Widget Denetimi K2 / A24 bulgusu: `desktop/src/components/HybridTrade.jsx`
içindeki `handleCheck` ve `handleTransfer` `useCallback` fonksiyonları
try/catch sarmadan API çağrısı yapıyordu:

```jsx
// ESKİ — A24 öncesi
const handleCheck = useCallback(async () => {
  if (!selectedTicket) return;
  setChecking(true);
  setCheckResult(null);
  setTransferResult(null);

  const result = await checkHybridTransfer(parseInt(selectedTicket, 10));
  setCheckResult(result);
  setChecking(false);  // ⚠ exception path'inde HİÇ çağrılmaz
}, [selectedTicket]);
```

**Etki:** `checkHybridTransfer` veya `transferToHybrid` herhangi bir
hata fırlatırsa (network, 500, timeout, schema mismatch), JavaScript
exception yukarı kabarcıklanır ve `setChecking(false)`/`setTransferring(false)`
HİÇ çağrılmaz. Kullanıcı:

1. Loading spinner sonsuza kadar döner (`Kontrol ediliyor...` /
   `Devrediliyor...`)
2. Butonlar disabled kalır (`disabled={checking}`)
3. Hata mesajı gösterilmez — sessiz kayıp
4. Sayfayı yenilemeden tekrar deneyemez

Bu, **canlı para üzerinde hibrit pozisyon devri sırasında** "butonum
donmuş" UX hatasıdır. Kullanıcı devir yaptım sandığı halde aslında
hata olduğunu bilmez, MT5 tarafında pozisyon korumasız kalabilir.

Öte yandan aynı dosyadaki `handleRemove` ZATEN try/catch sahibiydi —
pattern tutarsızlığı vardı.

---

## 2. Kök Sebep

React hook fonksiyonlarında async API çağrılarının try/catch/finally
pattern'i:

```jsx
const handleX = useCallback(async () => {
  setLoading(true);
  try {
    const result = await api();
    setResult(result);
  } catch (err) {
    setError(err.message);
  } finally {
    setLoading(false);  // ✓ HER PATH'te çalışır
  }
}, [...]);
```

`handleCheck` ve `handleTransfer` bu pattern'i takip etmiyor, sadece
"happy path" düşünülmüş.

---

## 3. Çözüm

### 3a) `desktop/src/components/HybridTrade.jsx`

```jsx
// A24 (K2): handleCheck/handleTransfer try/catch sarıldı. Eskiden API
// hatası (network/500/timeout) atıldığında setChecking(false) hiç
// çağrılmıyor, loading spinner sonsuza kadar dönüyor ve kullanıcı
// hatadan haberdar olmuyordu. Şimdi hata ConfirmModal ile gösterilir,
// loading state finally bloğunda kapatılır.
const handleCheck = useCallback(async () => {
  if (!selectedTicket) return;
  setChecking(true);
  setCheckResult(null);
  setTransferResult(null);

  try {
    const result = await checkHybridTransfer(parseInt(selectedTicket, 10));
    setCheckResult(result);
  } catch (err) {
    setErrorModal({
      title: 'Kontrol Hatası',
      message: err?.message ?? String(err),
    });
  } finally {
    setChecking(false);
  }
}, [selectedTicket]);

// A24 (K2): try/catch + finally — devir başarısız olursa
// setTransferring(false) hiçbir şekilde unutulmaz; canlı para üzerinde
// pozisyon devri sırasında "buton donmuş" UX hatası kaybolur.
const handleTransfer = useCallback(async () => {
  if (!selectedTicket) return;
  setTransferring(true);

  try {
    const result = await transferToHybrid(parseInt(selectedTicket, 10));
    setTransferResult(result);

    if (result.success) {
      setTimeout(() => {
        fetchOpenPositions();
        fetchEvents();
        setSelectedTicket('');
        setCheckResult(null);
        setTransferResult(null);
      }, 2000);
    }
  } catch (err) {
    setErrorModal({
      title: 'Devir Hatası',
      message: err?.message ?? String(err),
    });
  } finally {
    setTransferring(false);
  }
}, [selectedTicket, fetchOpenPositions, fetchEvents]);
```

`setErrorModal` state ZATEN dosyada vardı (handleRemove için
kullanılıyordu) ve `<ConfirmModal>` JSX altta render ediliyordu — hiç
ek altyapı kurulmadı, mevcut kanal kullanıldı.

### 3b) `tests/critical_flows/test_static_contracts.py`

**Flow 4zi** eklendi: `test_hybrid_trade_check_transfer_have_try_catch`.
11 sözleşme noktası:

- `handleCheck` body içinde `try {`, `catch`, `finally`
- `handleCheck` catch içinde `setErrorModal` çağrısı
- `handleCheck` finally içinde `setChecking(false)`
- `handleTransfer` body içinde `try {`, `catch`, `finally`
- `handleTransfer` catch içinde `setErrorModal` çağrısı
- `handleTransfer` finally içinde `setTransferring(false)`
- `A24` audit marker'ı dosyada mevcut

Eksik kontrol varsa hata mesajı hangi kontrolün başarısız olduğunu
gösterir — birisi yarın try/catch'i çıkarırsa CI yakalar.

### 3c) `docs/USTAT_GELISIM_TARIHCESI.md`

**#198** girişi #197 üzerine eklendi.

---

## 4. Test Sonuçları

```
python -m pytest tests/critical_flows -q
========================
68 passed, 3 warnings in 3.13s
========================
```

Baseline 67 → 68 (Flow 4zi eklendi).

---

## 5. Build Sonuçları

```
npm run build (vite v6.4.1)
✓ 730 modules transformed
dist/index.js   895.23 kB │ gzip: 256.54 kB
✓ built in 2.57s
```

Bundle boyutu: 895.23 kB (A23 sonrası 895.04 → +0.19 kB; try/catch +
yorum minify sonrası ihmal edilebilir fark).

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
| Siyah Kapı fonksiyonları (31) | Hiçbiri değişmedi |
| Kırmızı Bölge dokunuşu | Yok |
| Sarı Bölge dokunuşu | Yok |
| Backend değişikliği | Yok (tamamen frontend) |
| Sihirli sayı | Yok |

**Değişiklik sınıfı:** C1 — Yeşil Bölge frontend hata yönetimi
sertleştirme (defensive coding).

---

## 7. Kalan İşler

- Atomik commit (4 dosya: HybridTrade.jsx, test_static_contracts.py,
  USTAT_GELISIM_TARIHCESI.md, bu rapor)
- Sonraki madde: A25 (K3) — Event 5000 limit alarmı
