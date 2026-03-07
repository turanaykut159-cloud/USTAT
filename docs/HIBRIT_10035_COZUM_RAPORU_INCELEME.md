# Hibrit Panel 10035 — Çözüm Raporu İncelemesi

**Tarih:** 2026-03-05  
**İnceleyen:** Kod tabanı ile rapor karşılaştırması

---

## 1. Rapor–Kod Uyumu

| Rapor maddesi | Kod durumu | Not |
|---------------|------------|-----|
| `config/default.json` → `hybrid.native_sltp: false` | ✅ | `config/default.json` satır 96 |
| `transfer_to_hybrid`: native ise MT5 modify, değilse atla | ✅ | `h_engine.py` 329–356: `if self._native_sltp` → modify; else log + devam |
| SL/TP bellek+DB'ye yazılıyor | ✅ | Aynı blok sonrası `insert_hybrid_position` + `HybridPosition` + `insert_hybrid_event` |
| `run_cycle` her 10sn → `_check_software_sltp()` | ✅ | `main.py` 346: `h_engine.run_cycle()`; `h_engine.run_cycle()` 501–503: `if not self._native_sltp` → `_check_software_sltp()` |
| SL/TP ihlalinde `close_position()` (DEAL) | ✅ | `_check_software_sltp` 558–567: `close_position(hp.ticket)` + `_finalize_close` |
| Breakeven/trailing: native ise modify, değilse sadece internal | ✅ | `_check_breakeven` 616–623, `_check_trailing` 692–699: `if self._native_sltp` → modify; yoksa sadece `hp.current_sl` + DB + event |
| API `native_sltp` response | ✅ | `api/routes/hybrid_trade.py` 112: `native_sltp=h_engine._native_sltp`; `api/schemas.py` 509 |
| UI "Yazılımsal SL/TP" badge | ✅ | `HybridTrade.jsx` 226, 231–240: `nativeSltp` + `ht-sltp--software` / `ht-sltp--native` |
| Dokümantasyon | ✅ | `docs/HIBRIT_10035_KOK_NEDEN_ANALIZI.md` güncel (yazılımsal SL/TP, geçiş planı, dikkat) |

**Sonuç:** Raporla kod tam uyumlu; anlatılan çözüm kodda mevcut ve doğru bağlanmış.

---

## 2. Mantık Kontrolü

### 2.1 Yazılımsal SL/TP tetikleme

- **BUY:** SL = `current_price <= current_sl`, TP = `current_price >= current_tp` ✅  
- **SELL:** SL = `current_price >= current_sl`, TP = `current_price <= current_tp` ✅  
- Kapatma: `close_position()` → TRADE_ACTION_DEAL ✅  

### 2.2 Sıra (run_cycle)

1. `_check_software_sltp` (SL/TP ihlali → kapat)  
2. `_check_breakeven` (SL’i girişe taşı)  
3. `_check_trailing` (SL’i takip ettir)  

Önce kapatma, sonra breakeven/trailing doğru; aynı cycle’da hem SL hit hem breakeven güncellemesi nadir ama sıra mantıklı.

### 2.3 Breakeven/trailing (software mod)

- MT5’e `modify_position` **çağrılmıyor** ✅  
- `hp.current_sl` ve DB güncelleniyor ✅  
- Sonraki cycle’larda `_check_software_sltp` yeni `current_sl` ile kontrol ediyor ✅  

---

## 3. Raporla Küçük Farklar (bilgi)

- Rapor: "order_check kaldırıldı, 3 retry + 0.5s eklendi" — Kodda `modify_position` içinde `order_check` hâlâ var; yazılımsal çözüm **MT5 modify’i tamamen atladığı** için bu fark pratikte 10035’i etkilemiyor.
- Rapor: "10 dosya" — Liste dokümandaki 10 maddeyle uyumlu; `theme.css` ve diğerleri grep ile doğrulandı.

---

## 4. Öneriler

1. **Geçiş planı:** MT5 build 5200+ sonrası `native_sltp: true` yapılması dokümanda net; config’i değiştirip engine restart yeterli.
2. **Slippage uyarısı:** Dokümandaki “10sn aralıklı kontrol → slippage riski” ifadesi doğru; kullanıcıya panelde veya tooltip’te hatırlatılabilir (isteğe bağlı).
3. **Olay geçmişi:** SOFTWARE_SL / SOFTWARE_TP kapanışları `insert_hybrid_event` ile zaten loglanıyor; UI’da “Hibrit olay geçmişi”nde görünüyorsa doğrulama tamam.

---

## 5. Kısa Özet

- **Kök neden:** MT5/broker (TRADE_ACTION_SLTP 10035; build 4755 < 5200).  
- **Çözüm:** Yazılımsal SL/TP (native_sltp=false): devirde MT5 modify yok; run_cycle’da fiyat kontrolü + DEAL ile kapatma; breakeven/trailing sadece internal.  
- **Kod:** Raporla uyumlu, akış doğru, geçiş planı ve dikkat notu dokümanda yer alıyor.

**İnceleme sonucu:** Çözüm raporu onaylanmıştır; ek değişiklik gerekmez.
