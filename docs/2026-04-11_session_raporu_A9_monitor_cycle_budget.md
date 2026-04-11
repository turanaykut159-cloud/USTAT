# Oturum Raporu — A9 Monitor Döngü Bütçesi Eşik Hizalama

**Tarih:** 2026-04-11 (Cumartesi, Barış Zamanı)
**Kapsam:** Widget Denetimi Bulgu A9 (B10 + H14) — Monitor Performans paneli CYCLE_INTERVAL_MS tabanlı eşikler
**Sınıf:** C1 (Yeşil Bölge)
**Etki:** 1 dosya (`desktop/src/components/Monitor.jsx`) + 1 test (`tests/critical_flows/test_static_contracts.py`)
**Siyah Kapı / Kırmızı Bölge / Sarı Bölge dokunusu:** YOK

---

## 1. Kök Neden

Monitor.jsx PERFORMANS panelindeki `ResponseBar` grid'i ve "DÖNGÜ SÜRESİ" StatCard eşikleri mikro-benchmark literal'leriydi:

| Referans | Eski Değer | Canlı Ölçüm | Görsel Sonuç |
|----------|-----------|------------|--------------|
| BABA DÖNGÜ `max` | 50ms | ~122ms | Bar %244 → clamp dolu |
| OĞUL SİNYAL `max` | 100ms | — | — |
| ÜSTAT BEYİN `max` | 50ms | — | — |
| H-ENGINE `max` | 50ms | — | — |
| VERİ GÜNCELLEME `max` | 100ms | ~2596ms | Bar %2596 → clamp dolu |
| TOPLAM DÖNGÜ `max` | 300ms | ~2739ms | Bar %913 → clamp dolu |
| DÖNGÜ SÜRESİ StatCard | `> 50ms ? red` | ~2871ms | Sürekli kırmızı |
| DÖNGÜ İSTATİSTİK MAX | `> 100ms ? warn` | ~4878ms | Sürekli uyarı |

Backend `config/default.json::engine.cycle_interval = 10` — gerçek döngü bütçesi **10000ms**. Backend `overrun_count = 0` çünkü 10sn bütçeyi kontrol ediyor; frontend mikro-benchmark değerlerine bakıyor. Sonuç: **tüm çubuklar daima dolu, StatCard sürekli kırmızı**, kullanıcı performans panelini hiçbir zaman "normal" durumda göremiyor. Frontend ↔ backend arasında döngü bütçesi senkronsuzluğu.

## 2. Atomik Değişiklik

**Monitor.jsx:**
1. **Yeni sabit** `CYCLE_INTERVAL_MS = 10000` — POLL_MS yanına eklendi, backend `engine.cycle_interval` değeri ile senkron (Flow 4h testi 10000'de kilitler).
2. **ResponseBar genişletmesi:** `barColor = pct > 70 ? '#e74c3c' : pct > 30 ? '#f39c12' : color`. Etiket rengi ve bar rengi ortak bu değeri kullanıyor.
3. **6 ResponseBar max prop** (BABA/OĞUL/ÜSTAT/H-ENGINE/VERİ GÜNCELLEME/TOPLAM DÖNGÜ) → `CYCLE_INTERVAL_MS`.
4. **DÖNGÜ SÜRESİ StatCard:** `cycleAvg > CYCLE_INTERVAL_MS * 0.9 ? red : > * 0.5 ? orange : teal`. Sub etiketi "ortalama döngü" → "bütçe 10000ms".
5. **DÖNGÜ İSTATİSTİK MAX:** `(cycle?.max_ms ?? 0) > CYCLE_INTERVAL_MS * 0.9 ? red : > * 0.5 ? orange : '#8ab0d0'`.

**Flow 4h statik sözleşme testi** (`test_monitor_response_bars_use_cycle_interval_budget`):
- (a) `CYCLE_INTERVAL_MS = 10000` sabit var
- (b) Eski literal max (50/100/300) YASAK
- (c) `max={CYCLE_INTERVAL_MS}` ≥ 6 kez
- (d) `pct > 70` / `pct > 30` yük renk eşikleri
- (e) Eski `cycleAvg > 50 ?` YASAK, yeni `cycleAvg > CYCLE_INTERVAL_MS`
- (f) Eski `> 100 ? '#f39c12'` YASAK, yeni `cycle?.max_ms ?? 0) > CYCLE_INTERVAL_MS`

## 3. Dokunulmayanlar (Bilinçli)

- **Backend `config/default.json::engine.cycle_interval`** — DEĞİŞMEDİ. Frontend bütçesi backend değerine senkronize edildi, tersi değil.
- **`engine/main.py::_run_single_cycle`** — Siyah Kapı #22, dokunulmadı.
- **Dashboard `POLL_MS = 10000`** — API poll interval, döngü bütçesi değil. Bilinçli ayrılık.

## 4. Doğrulama

| Kontrol | Sonuç |
|---------|-------|
| `pytest tests/critical_flows -q` | **41 passed** (40 baseline + 1 yeni Flow 4h), 2.57s |
| `npm run build` (Windows) | **Başarılı** — ustat-desktop@6.0.0, 728 modül, 2.45s, 0 hata |
| dist/ üretildi | index.html 1.07 kB, index.css 90.52 kB, index.js 882.52 kB |
| Siyah Kapı ihlali | **YOK** |
| Kırmızı Bölge ihlali | **YOK** |

## 5. Etki Analizi

- **Dosya sayısı:** 1 JSX (Yeşil Bölge) + 1 test
- **Net satır:** ~20 JSX (1 sabit + 3 satır renk mantığı + 6 max prop + 2 eşik) + ~60 test
- **Çağıran zinciri:** YOK (CYCLE_INTERVAL_MS yerel sabit)
- **Tüketici zinciri:** Dahili (ResponseBar prop'u, StatCard color prop'u)
- **Geriye dönük uyumluluk:** Tam — dış API, backend şema, DB şeması değişmedi

## 6. Deploy Kararı

Piyasa kapalı (Cumartesi, Barış Zamanı). Deploy için `restart_app` yeterli — Electron yeni `dist/` bundle'ını yükleyecek. Kullanıcı zamanlamayı seçer; halen bekleyen A1+A2+A3+A4+B+B25+A9 paketiyle birlikte veya ayrı deploy edilebilir.

## 7. Commit Hash

Bu oturum commit'i:  (dolacak)

## 8. Sonraki Adımlar

- Widget Denetimi kalan A maddeleri (A17 ErrorTracker hardcoded saatler, A7 baseline tekilleştirme, A6 Performans equity/deposits, vb.)
- B17 (TRADE_ERROR kategori haritalama), B8 (Dashboard Otomatik Pozisyon Özeti 45 vs 31 tutarsızlığı), B11 (Monitor MT5 hardcode)
- A1+A2+A3+A4+B+B25+A9 paket deploy zamanlaması (kullanıcı kararı)

## 9. Kaynak

- `docs/2026-04-11_widget_denetimi.md` Bölüm 11.4 + Bölüm 17 A9 (B10+H14)
- Canlı `/api/health` ölçümleri (DataPipeline 2596ms, toplam döngü 2739ms)
- Backend `config/default.json::engine.cycle_interval = 10`
