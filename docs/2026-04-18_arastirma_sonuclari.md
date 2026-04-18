# V2 §7 Araştırma Soruları Sonuçları

**Tarih:** 18 Nisan 2026 Cmt gece
**Kapsam:** V2 raporu §7 soruları #3, #6, #7 + OP-I drift kontrolü

---

## #3 News silindikten sonra OLAY rejim tetiği çalışıyor mu?

**Kontrol:** `engine/baba.py::_check_olay` (satır 951-993)

**Sonuç:** ✅ **EVET, çalışıyor.** Üç tetik mekanizması news-bağımsız:
1. **CENTRAL_BANK_DATES** — TCMB/FED takvimi, pencere 12:00-15:30 (sabit liste)
2. **VIOP_EXPIRY_DATES** — Vade bitiş günleri (sabit liste)
3. **USD/TRY 5dk şok** — `_usdtry_5m_move_pct()` tick bazlı

`news_bridge.py` modülü silinmiş ama _check_olay hiç import etmiyor → OLAY rejimi güvenli.

**Kalan stub referansları (ölü kod):** `engine/utils/signal_engine.py` satır 1210/1233/1249/1345 — `news_bridge=None` parametresi backward-compat için kaldı. OP-O kapsamında temizlik yapılır.

---

## #6 monthly_paused durumu

**Kontrol:** `app_state.baba_risk_state`

```
monthly_paused: True
monthly_reset_month: (2026, 4)  # Nisan 2026
```

**Sonuç:** 🔴 **Sistem şu an aylık kayıp paused durumda.**

Mekanizma: BABA `max_monthly_loss_pct=%7` aşıldığında L2 aktif + `monthly_paused=True` set edilir. Aylık sıfırlama ancak yeni aya (Mayıs 2026) geçildiğinde otomatik clear.

**Kritik sonuç:** Pzt 20 Nis 09:00 açılışında sistem TRADING PAUSED durumda açılacak. OGUL sinyal üretmez/emir göndermez.

**Üstat seçenekleri:**
1. Manuel clear: UI Kill-Switch sayfasından ACK → `monthly_paused=False`
2. Beklemek: Mayıs 1'de otomatik reset
3. `_reset_monthly` elle tetikle (C3, riskli)

**Öneri:** Sabah manuel ACK (Pzt 08:45 civarı). Çünkü mevcut drawdown = 0, equity peak (63K), yeni ayı beklemek 12 işlem günü kaybı.

---

## #7 trend_follow %0 WR kalibrasyon analizi

**DB query:** `strategy='trend_follow' ORDER BY id DESC LIMIT 10` (6-7 Nis 2026)

### Dağılım

| Metrik | Değer |
|---|---|
| Trade sayısı | 10 |
| Kazanç | 0 (WR %0) |
| Toplam PnL | -74 TL |
| Ortalama zarar | -7.4 TL |
| Max zarar | -30 TL (F_TKFEN #217) |
| Min zarar | -1 TL (F_HALKB, F_KONTR) |

### Rejim filtresi anomali 🔴

- **RANGE rejim: 7/10 trade** ← **trend_follow RANGE'da hiç açılmamalı**
- TREND rejim: 3/10 trade
- RANGE'daki 7 trade'den 7'si kayıp

**Kök sorun:** Rejim filtresi ya etkisiz ya de regime detection RANGE'da trend sinyali üretiyor. Trend_follow stratejisi "ADX > 25 + EMA ayrışma" kuralıyla çalışır ama RANGE rejiminde de bu koşullar anlık olarak sağlanabiliyor.

### Symbol dağılımı

F_HALKB: 3, F_TCELL: 2, F_KONTR: 2, F_AKBNK: 1, F_ASTOR: 1, F_TKFEN: 1 — 6 farklı kontrat, tek sembol paterni değil.

### Lot + SL

Hep lot=1.0 (minimum), hepsi sl_tp ile çıkış (SL hit). Ortalama zarar -7 TL → SL mesafesi çok dar (1.5×ATR) ya da slippage yüksek.

### KARAR #17 Gerekçelendirme

Bu analiz KARAR #17 "trend_follow kalıcı bloke" kararını **haklı çıkarıyor**:
- Rejim filtresi güvenilir değil (RANGE'da 7/10 açılmış)
- SL çok dar (her trade -1 ile -30 arası küçük zarar)
- 10/10 kayıp istatistiksel olarak "kötü şans" değil, sistemsel

### Gelecek Rebirth için Öneriler

1. **Strict rejim filtresi:** sadece `regime.regime_type == TREND AND regime.conf >= 0.8`
2. **ADX eşik artırımı:** 25 → 30-35
3. **SL genişlet:** 1.5×ATR → 2.0×ATR (daha az stop)
4. **Backtest 30 gün yeni veri ile:** WR ≥%40 çıkarsa re-aktive düşünülebilir (kullanıcı onayı şart)

---

## OP-I: api/server.py risk_params drift gerçek durumu

**Kontrol:** `grep risk_params` — tüm referanslar incelendi.

```
engine/main.py:103   → self.risk_params = RiskParams(config=...)  [TEK KAYNAK]
engine/main.py:120   → Ogul(risk_params=self.risk_params)
engine/main.py:140   → self.ustat._risk_params = self.risk_params
engine/main.py:143   → self.baba._risk_params_ref = self.risk_params
engine/main.py:152   → Baba(risk_params=self.risk_params)
engine/main.py:814   → self.baba.check_risk_limits(self.risk_params)
api/routes/live.py   → engine.risk_params okur (read-only)
api/routes/risk.py   → engine.risk_params okur (read-only)
```

**Sonuç:** ✅ **Drift YOK.** `Engine.__init__` tek kaynak oluşturuyor, tüm motorlar (Ogul, Baba, Ustat) ve API route'lar aynı referansı paylaşıyor. api/server.py RiskParams hiç oluşturmuyor — Engine kendisi yaratıyor.

**Rapor S2-I iddiası:** "api/server.py:98 risk_params drift" → **EKSİK/YANLIŞ TEŞHİS.** O satır Engine constructor'dır, RiskParams duplikasyonu yok. OP-I skip edildi.

**OP-I KAPATILDI — Fabrika patterne gerek yok, mevcut tek-kaynak zaten uyumlu.**

---

## Özet

| # | Soru | Sonuç | Aksiyon |
|---|---|---|---|
| #3 | News silindikten sonra OLAY tetiği? | ✅ Çalışıyor (news-bağımsız) | news_bridge= stub parametreleri OP-O'da temizlenir |
| #6 | monthly_paused durumu | 🔴 **TRUE** | Üstat manuel ACK gerekli Pzt 08:45 |
| #7 | trend_follow %0 WR | Rejim filtresi zayıf + SL dar | KARAR #17 haklı. Rebirth için yukarıdaki öneriler |
| OP-I | api/server.py drift | ✅ Drift YOK | Kapatıldı, fabrika gerekmez |

**3 araştırma + OP-I incelemesi tamam.** Kalan: R-11 sihirli sayı config, OP-K idempotency, OP-N davranış testi, OP-O news stub cleanup.
