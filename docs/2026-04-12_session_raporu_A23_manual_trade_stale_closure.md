# Oturum Raporu — A23 (K1): ManualTrade Stale Closure Fix

**Tarih:** 12 Nisan 2026
**Kategori:** Widget Denetimi — Priority 3 (K1 kritik)
**Sınıf:** C1 (Yeşil Bölge frontend)
**Kapsam:** 1 frontend + 1 test + 1 changelog + 1 rapor
**Durum:** Tamamlandı — atomik commit hazır

---

## 1. Sorun Tanımı

Widget Denetimi K1 / A23 bulgusu: `desktop/src/components/ManualTrade.jsx`
içindeki `handleExecute` `useCallback` hook'unun dependency array'i
`[symbol, direction, lot, fetchRecentTrades]` şeklinde dört elemandan
oluşuyordu. Oysa fonksiyon gövdesi içinde `executeManualTrade(symbol,
direction, lot, sl, tp)` çağrısı ile `sl` ve `tp` state'leri
kullanılıyordu.

**Etki:** React, useCallback hook'unu yalnızca dependency array'deki
değerler değiştiğinde yeniden yaratır. Bağımlılıkta olmayan state'ler
closure içinde "dondurulmuş" (stale) kalır. Kullanıcı SL/TP değerini
formda değiştirdiği halde, henüz `symbol/direction/lot` değişmemişse
`handleExecute` eski `sl`/`tp` değerleriyle çalışmaya devam ediyor ve
MT5'e yanlış (stale) koruma değerleri gönderebiliyordu.

Bu, canlı para üzerinde işlem açarken **koruma değerlerinin sessizce
kaybolması** anlamına gelir — K1 kritik bulgu sınıfında listelenmesi
tesadüf değil.

---

## 2. Kök Sebep

`useCallback` hook'larında dependency array'in mantığı:
> "Fonksiyon gövdesinde okunan her state/prop bağımlılık listesinde
> olmalı, aksi halde closure stale kalır."

React ESLint `react-hooks/exhaustive-deps` kuralı bu durumu yakalar
fakat ÜSTAT projesinde ESLint strict mode kapalı veya warning olarak
işleniyor olduğu için kod review sırasında gözden kaçmış.

---

## 3. Çözüm

### 3a) `desktop/src/components/ManualTrade.jsx`

```jsx
// A23 (K1): handleExecute useCallback dependency array sl+tp
// eksikti — stale closure riski. Kullanıcı sl/tp değerini değiştirip
// 5 saniye içinde "Çalıştır"a basarsa eski (stale) sl/tp gönderiliyordu.
// Çözüm: dependency array'e sl ve tp eklendi.
const handleExecute = useCallback(async () => {
  setExecuting(true);

  const result = await executeManualTrade(symbol, direction, lot, sl, tp);
  setExecResult(result);
  setExecuting(false);
  setPhase('done');

  // 5 saniye sonra formu sıfırla
  setTimeout(() => {
    handleReset();
    fetchRecentTrades();
  }, 5000);
}, [symbol, direction, lot, sl, tp, handleReset, fetchRecentTrades]);
```

Eski dependency array: `[symbol, direction, lot, fetchRecentTrades]`
Yeni dependency array: `[symbol, direction, lot, sl, tp, handleReset, fetchRecentTrades]`

**Bonus ek:** `handleReset` de setTimeout içinde çağrıldığı için
bağımlılık listesine eklendi (mevcut closure'da da stale riski vardı,
fakat handleReset saf state setter'ları kullandığı için etkisi yoktu —
yine de doğru disiplin).

### 3b) `tests/critical_flows/test_static_contracts.py`

**Flow 4zh** eklendi: `test_manual_trade_handle_execute_no_stale_closure`.
Test handleExecute useCallback bloğunu regex ile parse edip dependency
listesinde zorunlu set'i `{symbol, direction, lot, sl, tp,
fetchRecentTrades}` olarak denetler. Eksik eleman varsa hangilerinin
eksik olduğunu mesajda gösterir.

Ek olarak `A23` audit marker varlığı da doğrulanır (kod yorumunda
geçiyor — regresyon takibi için).

### 3c) `docs/USTAT_GELISIM_TARIHCESI.md`

**#197** girişi #196 üzerine eklendi.

---

## 4. Test Sonuçları

```
python -m pytest tests/critical_flows -q
========================
67 passed, 3 warnings in 3.27s
========================
```

Baseline 66 → 67 (Flow 4zh eklendi).

---

## 5. Build Sonuçları

```
npm run build (vite v6.4.1)
✓ 730 modules transformed
dist/index.js   895.04 kB │ gzip: 256.51 kB
✓ built in 2.56s
```

Bundle boyutu: 895.04 kB (A11 sonrası ile aynı — kod yorumu + 3
dependency eklenmesi minify sonrası ihmal edilebilir fark).

---

## 6. Anayasa Uyumu Doğrulama

| Kontrol | Durum |
|---------|-------|
| Çağrı sırası (BABA → OĞUL → H-Engine → ÜSTAT) | Etkilenmedi |
| Risk kapısı (`can_trade`) | Etkilenmedi |
| Kill-switch monotonluğu | Etkilenmedi |
| SL/TP zorunluluğu | Dolaylı olarak **güçlendi** — artık frontend'den doğru SL/TP MT5'e gidiyor |
| EOD kapanış 17:45 | Etkilenmedi |
| Felaket drawdown %15 | Etkilenmedi |
| OLAY rejimi `risk_multiplier=0` | Etkilenmedi |
| Circuit breaker | Etkilenmedi |
| Siyah Kapı fonksiyonları (31) | Hiçbiri değişmedi |
| Kırmızı Bölge dokunuşu | Yok |
| Sarı Bölge dokunuşu | Yok |
| Backend değişikliği | Yok (tamamen frontend) |
| Sihirli sayı | Yok |

**Değişiklik sınıfı:** C1 — Yeşil Bölge frontend fix, React hook
dependency array düzeltmesi.

---

## 7. Kalan İşler

- Atomik commit (4 dosya: ManualTrade.jsx, test_static_contracts.py, USTAT_GELISIM_TARIHCESI.md, bu rapor)
- Sonraki madde: A24 (K2) — Hibrit handleCheck/handleTransfer try/catch
