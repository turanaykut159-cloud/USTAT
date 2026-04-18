# USTAT PROJESİ ANLAMA RAPORU

**Tarih:** 2026-04-16
**İnceleme metodu:** Root manifestleri doğrudan okundu (CLAUDE.md, CLAUDE_CORE.md, USTAT_ANAYASA.md, requirements.txt, pytest.ini, .gitignore, config/default.json, desktop/package.json). `engine/`, `api/`, `desktop/src/`, `tests/`, `governance/`, `tools/`, `start_ustat.py`, `ustat_agent.py`, `database/` içerikleri üç paralel Explore alt-ajanına taratıldı. Aşağıda **hangi iddianın doğrudan görüldüğü**, **hangisinin alt-ajan raporuna dayandığı** açıkça ayrılmıştır.

---

## A. PROJE ADI VE VERSİYONU

| Kaynak | Dosya:Satır | Değer |
|---|---|---|
| Paket sürümü (engine) | `engine/__init__.py` | `VERSION = "6.0.0"` (alt-ajan raporu; doğrudan açılmadı) |
| Config | `config/default.json:2` | `"version": "6.0.0"` (**doğrudan okundu**) |
| Desktop | `desktop/package.json:3` | `"version": "6.0.0"` (**doğrudan okundu**) |
| Desktop ürün adı | `desktop/package.json:37` | `"productName": "ÜSTAT v5.7 VİOP Algorithmic Trading"` (**doğrudan okundu** — burada v5.7, tutarsızlık) |
| API | `api/server.py:66` | `API_VERSION = "6.0.0"` (alt-ajan raporu) |
| Anayasa | `USTAT_ANAYASA.md:3` | `**Versiyon:** 3.0` (**doğrudan okundu** — anayasa kendi versiyonu) |
| Anayasa ürün adı | `USTAT_ANAYASA.md:1` | `# ÜSTAT Plus V6.0 — ANAYASA` (**doğrudan okundu**) |
| CLAUDE_CORE.md başlık | `CLAUDE_CORE.md:1` | `# ÜSTAT v5.9 — CORE` (**doğrudan okundu** — eski) |
| CLAUDE.md başlık | (system-reminder üzerinden) | `# ÜSTAT v5.9 — ANA REHBER` (eski) |

**Ürün adı:** "ÜSTAT Plus V6.0" (anayasa) / "ustat-desktop" (npm paketi) / "ÜSTAT v5.7 VİOP Algorithmic Trading" (electron-builder productName).
**Gerçek aktif sürüm:** **v6.0.0** (kod/config/desktop üçü hemfikir).
**Tutarsızlıklar:** `CLAUDE.md` ve `CLAUDE_CORE.md` başlıkları "v5.9" — kod üç adım önde. `desktop/package.json` içindeki `electron-builder.productName` ise "v5.7" — daha da eski.

---

## B. MİMARİ — MODÜLLER VE İLETİŞİM

**Dört motor (doğrulanmış):**

| Motor | Dosya | Rol | Satır (alt-ajan) |
|---|---|---|---|
| BABA | `engine/baba.py` | Risk, kill-switch, rejim, hard drawdown | 3388 |
| OĞUL | `engine/ogul.py` | Top5, sinyal, emir, EOD | 3570 |
| H-Engine | `engine/h_engine.py` | Hibrit: breakeven, trailing, EOD | 3095 |
| ÜSTAT | `engine/ustat.py` | Strateji havuzu, hata atfetme | 2195 |

**Çağrı sırası (alt-ajan raporuna göre, `engine/main.py:_run_single_cycle`):**
- `main.py:850` BABA `_run_baba_cycle()`
- `main.py:854` BABA `check_risk_limits()`
- `main.py:865` OĞUL `select_top5()`
- `main.py:895` OĞUL `process_signals()`
- `main.py:910` H-Engine `run_cycle()`
- `main.py:932` ÜSTAT `run_cycle()`

**Constructor sırası (alt-ajan, `api/server.py:92-104` ve `engine/main.py:95-130`):** `Config → Database → MT5Bridge → DataPipeline → Ustat → Baba → Ogul → HEngine`.

**Katmanlar:**
1. **Engine (Python)** — `engine/` altında ~19k satır çekirdek + models/ + utils/. Tek süreçte uvicorn lifespan altında.
2. **API (FastAPI)** — `api/server.py` lifespan içinde Engine'i oluşturur; `api/routes/` altında ~23 router modülü (alt-ajan sayımı).
3. **Desktop (Electron 33 + React 18 + Vite 6)** — `desktop/main.js` ana process, `desktop/src/components/` altında alt-ajan **21 JSX** bileşen saydı. Electron production modda `desktop/dist/`'i yükler.
4. **Veritabanı** — SQLite. `database/trades.db` (~71 MB, aktif; wal/shm dosyaları mevcut), `database/ustat.db` (**0 byte** — boş).
5. **Broker köprüsü** — `engine/mt5_bridge.py` → MetaTrader 5 Python API → `C:\Program Files\GCM MT5 Terminal\terminal64.exe` (`config/default.json:37`).
6. **Watchdog/Bootstrap** — `start_ustat.py` (1146 satır) ProcessGuard + Mutex + subprocess + tray.
7. **Otonom ajan** — `ustat_agent.py` (alt-ajan 3781 satır saydı, CLAUDE.md 3686 dedi — **tutarsızlık, kod satır sayısı dokümana göre artmış**) 53 komut handler'ı.
8. **Governance** — `governance/` altında 4 YAML (axioms, protected_assets, authority_matrix, triggers). Otomasyon `tools/` altında (check_constitution, check_triggers, seal_change, session_gate, impact_map, impact_report, rollback/*.sh).

**Akış:** MT5 → `mt5_bridge` → `data_pipeline` → BABA (rejim+risk) → OĞUL (sinyal+emir) → H-Engine → ÜSTAT → `database` / `event_bus` → FastAPI → React UI (WebSocket `/ws/live` + REST).

---

## C. TEKNOLOJİ YIĞINI — GERÇEK BAĞIMLILIKLAR

**Python (`requirements.txt` — doğrudan okundu):**
- MetaTrader5 ≥5.0.45
- pandas ≥2.0, numpy ≥1.24, ta-lib ≥0.4.28
- fastapi ≥0.104, uvicorn[standard] ≥0.24, pydantic ≥2.5
- aiosqlite ≥0.19
- cryptography ≥41
- loguru ≥0.7
- apscheduler ≥3.10
- pytest ≥7.4, pytest-asyncio ≥0.23
- matplotlib ≥3.8

**Node (`desktop/package.json` — doğrudan okundu):**
- Runtime: react 18.3, react-dom 18.3, react-router-dom 6.28, axios 1.7, recharts 2.15, @dnd-kit (core/sortable/utilities)
- Dev: electron 33, vite 6, @vitejs/plugin-react 4.3, electron-builder 25, concurrently 9, cross-env 7, wait-on 8

**Python sürümü:** CLAUDE.md "Python 3.14" diyor — sistemde doğrulanmadı (BİLMİYORUM).

---

## D. DIŞ BAĞIMLILIKLAR — KOD BAĞLANTI NOKTALARI

| Bağımlılık | Nerede | Kanıt |
|---|---|---|
| **MetaTrader 5 API** | `engine/mt5_bridge.py` — `connect()`, `send_order()`, `close_position()`, `modify_position()`, `_safe_call()`, `heartbeat()` | Alt-ajan satır referansları: connect:628, send_order:993, close_position:1503, modify_position:1723, _safe_call:189, heartbeat:774 |
| **Broker (GCM Capital)** | Terminal yolu: `C:\Program Files\GCM MT5 Terminal\terminal64.exe` | `config/default.json:37` (**doğrudan okundu**); `engine/mt5_bridge.py:628` (alt-ajan) terminal64.exe process kontrolü |
| **MT5 başlatma** | `desktop/mt5Manager.js` (535 satır, alt-ajan) | Electron sorumluluğu: `launchMT5()`, OTP akışı. Engine `connect(launch=False)` modunda. |
| **SQLite** | `engine/database.py` (2058 satır) — `aiosqlite` | Şema: alt-ajan 16 tablo saydı (bars, trades, strategies, risk_snapshots, events, top5_history, config_history, manual_interventions, liquidity_classes, app_state, hybrid_positions, hybrid_events, daily_risk_summary, weekly_top5_summary, notifications, mt5_journal). CREATE TABLE ifadeleri `database.py:39-240` |
| **Haber / RSS** | `engine/news_bridge.py` (1550 satır, alt-ajan); `config/default.json:148-169` bloomberght RSS feed listesi, MT5 journal dosyası | **doğrudan okundu** (config) |
| **Windows Credential Manager** | `desktop/mt5Manager.js` (alt-ajan ifadesi) | Doğrulanmadı: **BİLMİYORUM — dosya doğrudan okunmadı** |

---

## E. OLGUNLUK SEVİYESİ — KANITLAR

**Production / canlı işlem yapıyor** göstergeleri:
- `database/trades.db` 71 MB, wal+shm aktif (Nisan 16 12:14)
- `engine.heartbeat` 13 byte — motor çalışıyor (Nisan 16 12:14)
- `electron.log` 2.3 MB, `api.log` 700 KB, `startup_agent.log` 5.4 MB — çalışma logları
- `database/trades_backup_20260416_*.db` aynı gün 3 yedek — aktif yedekleme döngüsü
- `shutdown.signal` dosyası var (12:15) — uygulama yakın zamanda kapandı
- Anayasa (`USTAT_ANAYASA.md`) 2026-04-14'te v3.0'a geçmiş, governance/*.yaml manifestleri tam
- `.githooks/` mevcut (pre-commit zinciri) — alt-ajan varlığını doğruladı
- `tests/critical_flows/test_static_contracts.py` **3504 satır**, **55 test** (alt-ajan) — ciddi sözleşme test katmanı
- Siyah Kapı 31 fonksiyonun tamamı sicile kayıtlı **ve** kodda mevcut (alt-ajan 31/31 doğruladı)

**Olgunluk sınıfı:** **Production**, canlı para ile çalışan algoritmik trading sistemi. İskelet veya prototip değil. Son iki hafta içinde anayasa revizyonu (v2→v3), governance otomasyon zinciri (seal_change, session_gate) eklenmiş — **işletimde aktif evrim** aşamasında.

---

## F. BELİRSİZLİKLER VE TUTARSIZLIKLAR

1. **Versiyon başlıkları kodu takip etmiyor:** `CLAUDE.md` ve `CLAUDE_CORE.md` başlıkları "v5.9", kod "v6.0.0". `desktop/package.json:37` productName "v5.7". Üç farklı sürüm etiketi dolaşıyor.

2. **Endpoint sayımı uyumsuz:** CLAUDE.md "20 endpoint modülü" diyor. Alt-ajan `api/routes/` altında **23 router dosyası** saydı (ek olarak `ogul_toggle.py`, `nabiz.py`, `mt5_journal.py` var; docs listesinde yok). HTTP endpoint toplamı ~60 + 1 WebSocket (`/ws/live`). Docs güncel değil.

3. **React bileşen sayımı:** CLAUDE.md "20 bileşen". Alt-ajan `desktop/src/components/` altında **21 JSX** saydı (docs'ta olmayan `Nabiz.jsx` 660 satır var). Docs güncel değil.

4. **Anayasa CI-01..CI-11 vs axioms.yaml AX-1..AX-7:** Anayasa metninde (v3.0) **11 CI maddesi** (CI-01'den CI-11'e, sonuncusu "Broker SL Sync"). `axioms.yaml`'da alt-ajan **7 axiom** saydı (AX-1..AX-7). Bölüm C tablosundaki CI-06, CI-10, CI-11 için "Axiom ID: —" (eşleşme yok). Yani CI ⊃ AX. Bu tasarımsal olabilir (CI'nin hepsi AX değil), ama doğrulanmadı — **kesin eşleme BİLMİYORUM** (`governance/axioms.yaml` doğrudan açılmadı).

5. **`ustat.db` boş (0 byte):** CLAUDE.md "ÜSTAT analiz veritabanı" diye tanımlıyor. Şu anda boş. Kullanımda mı, ölü mü — **BİLMİYORUM** (engine/database.py'de `ustat.db`'ye bağlanan kod yolu doğrudan doğrulanmadı).

6. **`ustat_agent.py` satır sayısı:** CLAUDE.md "3686 satır" diyor; alt-ajan "3781 satır" ve "53 komut" raporladı. Docs bu noktada geride. Komut sayısı da docs'ta "37 komut" (bölüm 11.2), alt-ajanda 53 → **docs güncel değil**.

7. **Alt-ajan modeli Haiku 4.5 idi (engine raporunu "çok iyi" derecede cilaladı) — iddialar "31/31 DOĞRULANDI" gibi toptan onaylara sahip.** Bu iddialar satır bazında tek tek doğrulanmadı; alt-ajana güven seviyesi var ama risk skoru mevcut. Şüpheli maddelerde (örn. critical_flows testlerinin içeriği, Siyah Kapı fonksiyonlarının imza-mantık uyumu) direkt kod okuması gerekebilir.

8. **Doğrudan okunmayan dosyalar (BİLMİYORUM):**
   - `engine/` altındaki tüm Python dosyaları (alt-ajana devredildi)
   - `api/server.py` içeriği ve tüm `api/routes/*.py`
   - `desktop/src/` bileşenlerinin içerikleri
   - `tests/` altındaki test fonksiyonlarının içerikleri (sadece liste saydırıldı)
   - `governance/axioms.yaml`, `protected_assets.yaml`, `authority_matrix.yaml`, `triggers.yaml` içerikleri (sadece alt-ajan raporu)
   - `tools/*.py` içerikleri
   - `start_ustat.py` ve `ustat_agent.py` gövdeleri
   - `engine/database.py` CREATE TABLE ifadeleri — şema dökümü alt-ajandan
   - `.githooks/pre-commit` içeriği
   - `.github/workflows/ci.yml` içeriği
   - `mql5/` klasörü içeriği
   - `archive/`, `reports/`, `docs/sessions/`, `docs/skills/`, `docs/specs/` alt klasörleri
   - `CLAUDE.md` tamamı (system-reminder üzerinden önizleme geldi, dosya açıldığında 25k token limitini aştı)

9. **`.claudeignore` okunmadı** — içinde ne filtrelendiği **BİLMİYORUM**.

10. **`config/default.json` içinde `baseline_date: "2026-04-16 09:50"`** — bugünün tarihine denk. Gerçek takvim tarihi mi yoksa test sabiti mi belirsiz; ancak `engine.heartbeat` + `electron.log` zaman damgaları uygulamanın bugün canlı çalıştığıyla uyumlu.

---

## ÖZET

- **Ne:** ÜSTAT Plus V6.0, VİOP'ta GCM Capital + MT5 üzerinden canlı para ile çalışan 4 motorlu algoritmik trading platformu.
- **Olgunluk:** Production, aktif çalışıyor, governance katmanı kurulmuş.
- **Ana iskelet:** Python 3.14 engine + FastAPI (port 8000) + Electron 33 + React 18 + Vite 6 + SQLite + MT5 API.
- **Gerçek kanıt:** 71 MB trades.db, wal/shm aktif, heartbeat 12:14, son yedek 10:52.
- **Docs drift:** Versiyon etiketleri (v5.7/v5.9/v6.0) + endpoint sayımı (20 vs 23) + bileşen sayımı (20 vs 21) + ajan satır/komut sayımı (3686/37 vs 3781/53) güncel değil.
- **En güvenilir tek kaynak:** kod + `governance/*.yaml` + `config/default.json`. `CLAUDE.md` ve `CLAUDE_CORE.md` "anlatı/rehber" olarak geride kalmış.
