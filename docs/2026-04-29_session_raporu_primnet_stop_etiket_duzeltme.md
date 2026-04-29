# Oturum Raporu — PRİMNET Grid: STOP Etiketi Tutarsızlığı Düzeltmesi

**Tarih:** 2026-04-29
**Tarihçe:** #292
**Sınıf:** C2 (Yeşil Bölge, frontend kosmetik fix)
**Bölge:** Yeşil — `desktop/src/components/PrimnetDetail.jsx`
**Versiyon Etkisi:** Yok (≤%1 değişim, v6.2.0 korunur)

---

## 1. Sorun

Kullanıcı, açık SELL pozisyonu (`F_TKFEN` #8050699748) için PRİMNET modalını açıp ekran görüntüsü paylaştı. Trailing aktifleşmiş, broker SL +0.50 prim seviyesine kaymıştı (footer: `TRAILING STOP: 141.00 · kâr-trailing aktif · BROKER SYNC`). Buna rağmen grid tablosunda **+1.50, +1.00 ve +0.50** satırlarının üçü birden `STOP` etiketi taşıyor ve aynı açıklamayı gösteriyordu: *"Bu seviyede zarar-durdur tetiklenir → KAPAT"*.

Bu semantik olarak yanlıştı: gerçek aktif stop sadece **+0.50** (=141.00 fiyat) idi. Fiyat geri yukarı dönerse +0.50'de tetiklenir ve pozisyon kapanır — fiyat +1.00 veya +1.50'ye **asla ulaşamaz** çünkü zaten +0.50'de çıkmış olur. Dolayısıyla +1.00 ve +1.50 satırlarının `DIŞARDA` etiketi taşıması gerekirdi.

İlk ekran görüntüsünde (trailing henüz aktif değilken, broker SL hâlâ initial +1.50'deyken) bug görünmüyordu — sadece +1.50 STOP'tu, üstü DIŞARDA. Trailing devreye girince bug ortaya çıkmıştı.

## 2. Kök Neden

`buildLadder` fonksiyonundaki SELL dalının (eski satır 287-294) loss-side dallanması:

```javascript
} else if (prim > entryPrim && prim <= slPrim) {
  status = 'AÇIK'; statusClass = 'open';
} else if (isStop || (prim > slPrim && prim <= entryPrim + trailingDist + 0.25)) {
  status = 'STOP'; statusClass = 'stop';
} else if (prim > slPrim) {
  status = 'DIŞARDA'; statusClass = 'outside';
}
```

`isStop` bayrağı (satır 214) **başlangıç stop pozisyonuna** sabitlenmişti (entry + trailing = +1.50). İkinci koşulun ikinci kanadı *"slPrim üstünde ve initial+0.25 altında"* aralığını kapsıyordu. Bu mantık trailing **aktifleşmediğinde** (slPrim ≈ 1.50) doğru çalışıyordu — sadece +1.50 satırı STOP koşulunu sağlardı.

Trailing devreye girip slPrim aşağı kayınca (örn. 0.499'a) artık `prim > slPrim && prim ≤ entryPrim + trailingDist + 0.25` aralığı **+0.50, +1.00 ve +1.50 satırlarının üçünü birden** kapsıyordu. Üçü de STOP etiketi alıyordu.

BUY dalı (satır 252-259) simetrik aynı kusuru taşıyordu.

## 3. Çözüm

`isCurrentStop` (canlı slPrim'e en yakın satırı tespit eden mevcut bayrak — satır 218-220) STOP'un birincil kapısı yapıldı:

**SELL dalı (yeni satır 290-301):**
```javascript
} else if (isCurrentStop || (!hasValidSl && isStop)) {
  // Aktif SL satiri (trailing ile guncel slPrim'e en yakin satir).
  // SL henuz okunamadiysa initial stop pozisyonuna fallback.
  status = 'STOP'; statusClass = 'stop';
  stopLevel = '';
} else if (prim > entryPrim && prim < slPrim) {
  status = 'AÇIK'; statusClass = 'open';
} else if (prim > entryPrim) {
  // slPrim ustundeki satirlar: pozisyon SL'de zaten kapanmis olur, buraya ulasilamaz.
  status = 'DIŞARDA'; statusClass = 'outside';
}
```

**BUY dalı (yeni satır 252-263):** simetrik (`prim < entryPrim`, `prim > slPrim` → AÇIK; `prim < entryPrim` → DIŞARDA).

Edge case — broker SL henüz okunmamışken (`hasValidSl = false`): `(!hasValidSl && isStop)` fallback'i sayesinde initial stop satırı yine STOP gösterilir, eski davranış korunur.

## 4. Etki Analizi

- **Backend / Engine / MT5:** Dokunulmadı.
- **`buildExplanation()`:** `statusClass` üzerinden okuyor, tutarlı kalıyor.
- **`isCurrentStop` styling** (kırmızı pulse, `pn-row--current-stop`): aynı şekilde çalışıyor.
- **GİRİŞ / KÂR KİLİTLİ / BREAKEVEN / TRAİLİNG / HEDEF / ULAŞILAMAZ:** Bu daldan ÖNCE kontrol ediliyor, etkilenmedi.
- **Statik sözleşme testleri (12 critical flow):** Frontend kontrat değişmedi, hepsi geçti.

## 5. Doğrulama

1. **Kaynak grep:** Eski `+ 0.25 / - 0.25` deseni dosyada 0 eşleme.
2. **Build:** `python .agent/claude_bridge.py build` — 728 modül transform, 4.20s, 0 hata. Bundle hash: `BsOlCKIe.js` → `ByUuB_C_.js` (909.232 byte).
3. **Bundle içerik:** Yeni dist'te `0.25` literal'i 0 eşleme — eski koda özgü değer kaldırıldı.
4. **Restart:** `python .agent/claude_bridge.py restart_app` — başarılı, 17.99s, "API aktif".
5. **Critical flows:** `python -m pytest tests/critical_flows -q --tb=short` — **119 passed**, 3 syntax warning (mevcut, ilgisiz).
6. **Ekran teyidi:** Kullanıcı modal'ı yeniden açtığında +1.50 ve +1.00 satırları DIŞARDA, sadece aktif slPrim satırı (+0.50) STOP olarak görünmeli.

## 6. Versiyon Etkisi

- Değişen dosya: 1 (`PrimnetDetail.jsx`)
- Değişen satır: ~14 (BUY+SELL dallarında symmetric reflow)
- Toplam kod satırına oran: <%0.1
- **Versiyon ARTMIYOR**, v6.2.0 korunur (CLAUDE.md §7 ADIM 3 — eşik %10).

## 7. Kalan Riskler

- **Renderer cache:** Bundle hash değiştiği için Chromium cache busting otomatik. Yine de kullanıcının modal'ı kapatıp yeniden açması gerekebilir (eski React state'i mount'ta atılır).
- **Profit-side değişmedi:** TRAILING/BREAKEVEN/KÂR KİLİTLİ rotaları intakt; bu fix sadece loss-side STOP/DIŞARDA dallanmasını etkiliyor.

## 8. Geri Alma

Tek dosya, tek commit. Sorun çıkarsa:
```bash
git revert <commit_hash> --no-edit
python .agent/claude_bridge.py build
python .agent/claude_bridge.py restart_app
```

## 9. İlgili Dosyalar

- `desktop/src/components/PrimnetDetail.jsx` (modifiye)
- `docs/USTAT_GELISIM_TARIHCESI.md` (#292 girişi)
- `docs/2026-04-29_session_raporu_primnet_stop_etiket_duzeltme.md` (bu rapor)
