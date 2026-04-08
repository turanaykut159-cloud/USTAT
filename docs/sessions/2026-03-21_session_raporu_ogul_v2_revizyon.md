# Oturum Raporu — OĞUL v2 Revizyon: Aktif İşlem Kapasitesi

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-21 |
| **Versiyon** | 5.6.0 → 5.7.0 |
| **Commit** | `91e56b2` |
| **Build** | `npm run build` — 0 HATA, 718 modül, 9.28s |

## Yapılan İş Özeti

OĞUL motoru 157 DB kaydından 0 otomatik işlem açabiliyordu. 6 aşamalı revizyon planı uygulanarak OĞUL'un sinyal pipeline'ı aktif işlem yapabilecek kapasiteye getirildi.

**Kök Neden:** PA Confluence Gate (sabit 60.0 eşiği) VİOP koşullarında matematiksel olarak geçilemez — Pattern alt-skoru %88 sıfır, Volume %77 sıfır.

## Değişiklik Listesi

### Engine (Çekirdek Değişiklikler)

| Dosya | Aşama | Değişiklik |
|-------|-------|-----------|
| `config/default.json` ⛔ | 0 | `paper_mode: true` eklendi, versiyon 5.7.0 |
| `engine/ogul.py` ⛔ | 0+2 | Paper trade modu, 5 hard veto → soft penalty dönüşümü, SE2'ye regime_type geçişi |
| `engine/utils/price_action.py` | 1 | Rejim-bazlı confluence eşikleri (TREND:40/RANGE:50/VOLATILE:65), VİOP volume kalibrasyonu |
| `engine/utils/signal_engine.py` | 3+4 | REGIME_SE2_PARAMS, regime_type parametresi, VİOP kalibrasyonu (ROC, volume, compression, ağırlıklar) |
| `engine/backtest.py` 🆕 | 5 | Walk-forward validasyon aracı |

### Versiyon Güncelleme (5.6.0 → 5.7.0)

| Dosya | Güncelleme |
|-------|-----------|
| `engine/__init__.py` | VERSION sabiti |
| `api/server.py` | API_VERSION + docstring |
| `api/schemas.py` | StatusResponse version |
| `api/routes/error_dashboard.py` | Docstring |
| `desktop/package.json` | version + productName + description |
| `desktop/main.js` | APP_TITLE + splash HTML + docstring |
| `desktop/preload.js` | JSDoc başlığı |
| `desktop/mt5Manager.js` | JSDoc başlığı |
| `desktop/src/components/TopBar.jsx` | Logo versiyonu + docstring |
| `desktop/src/components/LockScreen.jsx` | Logo versiyonu + docstring |
| `desktop/src/components/Settings.jsx` | VERSION sabiti + docstring |
| `desktop/src/components/*.jsx` (x9) | JSDoc başlıkları |
| `desktop/src/services/*.js` (x2) | JSDoc başlıkları |
| `desktop/src/utils/formatters.js` | JSDoc başlığı |
| `desktop/src/styles/theme.css` | Yorum başlığı |
| `desktop/src/main.jsx` | JSDoc başlığı |
| `desktop/src/App.jsx` | JSDoc başlığı |
| `start_ustat.py` | Başlatıcı versiyonu |
| `fix_regime_backfill.py` | Script başlığı |
| `engine/error_tracker.py` | Modül docstring |
| `engine/backtest.py` | Modül docstring |
| `create_shortcut.ps1` | Kısayol adı + açıklama |
| `update_shortcut.ps1` | Kısayol adı + açıklama |
| `docs/USTAT_v5_gelisim_tarihcesi.md` | Başlık v5.7 + #48 girdisi |

## Teknik Detaylar

### Aşama 0 — Paper Trading
`engine.paper_mode` konfigürasyonla kontrol edilir. Aktifken sinyal `PAPER_TRADE` event olarak DB'ye yazılır, MT5'e emir gönderilmez.

### Aşama 1 — Rejim-Bazlı Confluence
`CONFLUENCE_THRESHOLDS` dictionary: BABA rejim tespitine göre farklı eşikler. Pattern ağırlığı düşürüldü (VİOP'ta bar pattern güvenilmez), indicator ağırlığı artırıldı.

### Aşama 2 — Soft Penalty Sistemi
5 hard veto noktası kademeli penalty'ye dönüştürüldü. Sinyal hiçbir zaman sıfıra düşmez (min %30 korunur). Sadece çok güçlü ters trend (h1_str > 0.8) hard engel olarak kalır. Final minimum güç eşiği: 0.10.

### Aşama 3 — Rejim-Uyumlu SE2
`generate_signal()` artık `regime_type` alır. REGIME_SE2_PARAMS ile TREND/RANGE/VOLATILE için farklı min_sources, min_score, min_rr değerleri.

### Aşama 4 — VİOP Kalibrasyonu
Volume klimaks: 2.5→1.8, momentum eşiği: 0.05→0.02, ROC: 1.5→0.8. Kaynak ağırlıkları: VWAP ↑1.3 (kurumsal seviyeler VİOP'ta net), momentum ↑1.2, volume ↓0.9 (düşük likidite aldatıcı).

### Aşama 5 — Validasyon
Sentetik backtest: TREND rejiminde 40 pencereden 4 sinyal (%10), tümü final'a ulaştı. RANGE: 0 sinyal (daha sıkı eşikler).

## ANAYASA Uyumluluk
Tüm immutable sabitler korundu:
- max_daily_loss_pct: 0.018 ✓
- max_daily_trades: 5 ✓
- cooldown_hours: 4 ✓
- hard_drawdown_pct: 0.15 ✓
- consecutive_loss_limit: 3 ✓

## Sonraki Adımlar
1. Sistemi `python start_ustat.py` ile başlat
2. VİOP piyasa saatlerinde (09:45-17:45) PAPER_TRADE event'lerini izle
3. Sinyaller doğrulandıktan sonra `paper_mode: false` yap
4. Kısayol güncelle: `update_shortcut.ps1` çalıştır
