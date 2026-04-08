# Oturum Raporu — 28 Mart 2026

## OĞUL Motoru Kapsamlı İnceleme ve Yeniden Yapılandırma

**Commit:** e57b008
**Versiyon:** v5.8 → v5.9
**Süre:** Uzun oturum (satır satır inceleme + 5 aşamalı uygulama + test)

---

## Yapılan İş

### 1. Satır Satır İnceleme (4898 satır)
OĞUL motoru (engine/ogul.py) baştan sona satır satır incelendi.
44 bulgu tespit edildi: 22 kritik, 7 orta, 13 düşük.

### 2. 5 Aşamalı Yeniden Yapılandırma

**Aşama 1 — Temizlik (C0):**
- Docstring v5.8 güncelleme
- SE2→SE3 isimlendirme (import + 8 referans)
- 30+ ölü sabit, 3 ölü fonksiyon, 2 ölü import kaldırıldı

**Aşama 2 — Config + Güvenlik (C3/C4):**
- TRADING_CLOSE 17:50→17:45 (config'den)
- MAX_LOT, MAX_CONCURRENT config'den okunuyor
- _check_advanced_risk_rules + _check_time_rules çağrısı eklendi
- self.baba None kontrolü eklendi

**Aşama 3 — Emir Basitleştirme (C3):**
- Limit emir → market emir (timeout/retry zinciri kaldırıldı)
- Lot = 1 sabit (test süreci)
- Race condition düzeltildi (lock içinde slot ayırma)
- ManuelMotor müdahaleleri kaldırıldı (EOD, adopt, sync)

**Aşama 4 — Sinyal Mimarisi (C3):**
- Yön konsensüsü: 3 kaynak (oylama + H1 + SE3), 2/3 çoğunluk
- SE3'e symbol gönderme (haber kaynağı aktif)
- SE3 +0.15 bonus kaldırıldı (adil yarışma)
- 24 kapılı filtre → tek confluence gate (skor > 50)
- Yedek sinyal fallback eklendi

**Aşama 5 — Pozisyon Yönetimi (C3):**
- 4 modlu adaptif sistem: KORUMA → TREND → SAVUNMA → ÇIKIŞ
- Swing bazlı trailing (trend gününü taşır)
- Momentum tespiti (RSI divergence + hacim + mum gövdesi)
- Yapısal bozulma çıkışı (LL/HH + EMA kapanış)

### 3. Test
125 test yazıldı — %100 geçti.

---

## Değişiklik Listesi

| Dosya | Değişiklik |
|-------|-----------|
| engine/ogul.py | 5 aşamalı yeniden yapılandırma (613+, 1224-) |
| engine/__init__.py | VERSION 5.8.0 → 5.9.0 |
| config/default.json | version 5.9.0 |
| api/server.py | API_VERSION 5.9.0 |
| api/schemas.py | StatusResponse version 5.9.0 |
| desktop/package.json | version 5.9.0 |
| desktop/main.js | APP_TITLE + splash v5.9 |
| desktop/preload.js | JSDoc v5.9 |
| desktop/src/components/TopBar.jsx | v5.9 |
| desktop/src/components/LockScreen.jsx | v5.9 |
| desktop/src/components/Settings.jsx | v5.9 |
| create_shortcut.ps1 | v5.9 |
| update_shortcut.ps1 | v5.9 |
| CLAUDE.md | v5.9, versiyon 3.2 |
| docs/USTAT_v5_gelisim_tarihcesi.md | #81 kaydı |
| docs/ogul_calculate_lot_backup.md | Lot hesaplama yedeği (yeni) |
| docs/ogul_pozisyon_yonetimi_tasarim.md | 4 mod tasarım dokümanı (yeni) |
| tests/test_ogul_200.py | 125 test (yeni) |

---

## Teknik Detaylar

### Kaldırılan (~700 satır)
- 30+ ölü sabit (Top5, vade, TP2/TP3, voting hold)
- 3 ölü fonksiyon (_business_days_until/since, _is_new_m15_candle)
- 24 kapılı çarpımsal filtre zinciri
- Limit emir + timeout + retry mekanizması
- Oylama bazlı çıkış kararı
- Sabit %20 pullback toleransı
- TP1 yarı kapanış (lot=1 iken çalışmıyordu)
- Piramitleme (send_market_order yoktu)
- Maliyetlendirme (MAX_LOT yüzünden çalışmıyordu)
- Chandelier Exit
- ManuelMotor EOD müdahalesi
- ManuelMotor adopt

### Eklenen (~480 satır)
- _determine_direction(): yön konsensüsü
- _determine_trade_mode(): mod belirleme
- _check_momentum_strength(): momentum tespiti
- _is_structural_break(): yapısal bozulma
- _mode_protect(): KORUMA modu
- _mode_trend(): TREND modu (swing trailing)
- _mode_defend(): SAVUNMA modu (EMA trailing)
- Yedek sinyal fallback (candidates sıralı deneme)
- Config'den parametre okuma (__init__)
- 125 test

---

## Build Durumu
- Syntax: OK
- Import: OK
- Test: 125/125 geçti
- Build: Test edilmedi (piyasa kapalı — barış zamanı)
