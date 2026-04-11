# Oturum Raporu — 2026-04-11

**Konu:** BULGU #10-12 kalan audit fix'leri + v6.0.0 bump + "ÜSTAT Plus V6.0" yeniden markalama
**Tarih:** 11 Nisan 2026, Cumartesi (Barış Zamanı — piyasa kapalı)
**Versiyon geçişi:** v5.9.0 → **v6.0.0**
**Ürün adı:** ÜSTAT → **ÜSTAT Plus V6.0**

---

## 1. Özet

Bu oturumda `engine/baba.py` derin audit'inin son 3 bulgusu (BULGU #10, #11, #12) atomik, izole commit'lerle kapatıldı; ardından CLAUDE.md Bölüm 7 Adım 3 versiyon kontrolü zorunlu bump tespit etti (kümülatif oran %56.4, üretken kod %33.7) ve kullanıcı talimatıyla v6.0.0 bump + "ÜSTAT Plus V6.0" yeniden markalama tek atomik commit olarak uygulandı.

**Toplam:** 4 commit, 16 dosya, tüm değişikliklerden sonra kritik akış testleri **34/34 yeşil**, production build **başarılı**, davranış değişimi sıfır (hepsi doc/cleanup/rename kategorisinde).

---

## 2. Commit Zinciri

| Sıra | Commit | Başlık | Dosya | Diff |
|---|---|---|---|---|
| 1 | `6b2655a` | docs: #161 BULGU #10 datetime tz mini-audit + naive local-time docstring | 2 | +22/-0 |
| 2 | `33b519c` | refactor: #162 BULGU #11 regime hysteresis docstring + config-fy magic number | 3 | +67/-5 |
| 3 | `aca9aa7` | refactor: #163 BULGU #12 remove 11 dead module constants from baba.py | 2 | +16/-18 |
| 4 | `32ebeda` | build: #164 v6.0.0 bump + rebrand "ÜSTAT Plus V6.0" | 14 | +34/-27 |

---

## 3. BULGU #10 — datetime tz mini-audit (C0 dokümantasyon)

**Audit iddiası:** `baba.py` içinde naive/aware datetime karşılaştırma bug'ı.

**Mini-audit kapsamı:** `baba.py` (13 `datetime.now()` noktası), `ogul.py`, `mt5_bridge.py`, `h_engine.py`, `main.py`, `ustat.py`, `data_pipeline.py`, `database.py`.

**Bulgu:** Kod tabanı naive local time kullanımında **içsel olarak tutarlı**, kanıtlı bir naive/aware karşılaştırma bug'ı **YOK**.
- `baba.py` tüm `datetime.now()` çağrıları naive (tz parametresi yok)
- `database.py _now()` naive ISO string döner
- `_start_cooldown` / `_is_in_cooldown` çifti naive datetime ile çalışır
- Cooldown read-back `datetime.fromisoformat()` naive DB string üzerinde çalışır
- `mt5_bridge.py:1960` istisna olarak `tz=timezone.utc` kullanır ama sadece MT5 epoch'u pozisyon `time` alanı için string gösterimine çevirir (karar mantığında kullanılmaz)

**Aksiyon:** Anayasa "kanıt yoksa dokunma" gereği mantıkla dokunulmadı. Pure C0 dokümantasyon: `baba.py` modül docstring'ine yeni "NOT (v5.9.3 — BULGU #10)" bloğu eklendi (implicit local-time varsayımı, tutarlılık kanıt listesi, Türkiye 2016'dan beri sabit UTC+3/DST yok notu).

**Doğrulama:** 34/34 critical_flows yeşil.

---

## 4. BULGU #11 — regime hysteresis docstring + config-fy (Karma C0 doc + C3/C4)

`detect_regime()` Siyah Kapı #8 fonksiyonunda 4 sorun tespit edildi:

1. **Sihirli sayı (Anayasa ihlali):** `HYSTERESIS_CYCLES = 2` lokal sabit, config'de yok
2. **Yanıltıcı yorum:** `baba.py:714` "OLAY hariç, rejim değişimi..." — aslında OLAY bypass'ı `:643` early-return ile çok daha üstte yapılıyor
3. **Docstring eksik:** hysteresis state machine (3 state değişkeni, geçiş tablosu, ilk-cycle) hiç dokümantasız
4. **Undocumented invariant:** `_confirmed_regime` ASLA `RegimeType.OLAY` olmaz (kasıtlı ama belirtilmemiş)

**Çözüm (kullanıcı seçimi: "Aday A+B birleşik"):**
- `config/default.json` → `engine.regime_hysteresis_cycles: 2` yeni anahtar (default = mevcut)
- `baba.py:405` `__init__` → `self._regime_hysteresis_cycles = int(self._config.get("engine.regime_hysteresis_cycles", 2))`
- `baba.py:626` `detect_regime` docstring tamamen yeniden yazıldı (Siyah Kapı #8 ref, 5 adımlı process, hysteresis state machine 3 değişken + geçiş tablosu, ilk-cycle davranışı, kasıtlı invariant, config kaynağı)
- `baba.py:713-742` hysteresis bloğu — local sabit kaldırıldı, yanıltıcı yorum düzeltildi

**C4 değerlendirmesi:** Siyah Kapı #8'de izin verilen "kanıtlı bug fix" (sihirli sayı yasağı) + pure docstring/variable rename. Default değer (2) ile birebir aynı davranış.

**Doğrulama:** 34/34 critical_flows yeşil.

---

## 5. BULGU #12 — 11 ölü modül sabitinin kaldırılması (C3 Kırmızı Bölge)

**Mini-audit:** `baba.py` modül seviyesinde 11 sabit tespit — hepsi declaration + 0 kullanım:

| # | Sabit | Gerçek Kaynak |
|---|---|---|
| 1 | `MAX_WEEKLY_LOSS_PCT` | `risk_params.max_weekly_loss` |
| 2 | `MAX_MONTHLY_LOSS_PCT` | `risk_params.max_monthly_loss` |
| 3 | `HARD_DRAWDOWN_PCT` | `self._config.get("risk.hard_drawdown_pct")` |
| 4 | `CONSECUTIVE_LOSS_LIMIT` | `risk_params.consecutive_loss_limit` |
| 5 | `COOLDOWN_HOURS` | `risk_params.cooldown_hours` |
| 6 | `MAX_FLOATING_LOSS_PCT` | `risk_params.max_floating_loss` |
| 7 | `MAX_DAILY_TRADES` | `risk_params.max_daily_trades` |
| 8 | `MAX_RISK_PER_TRADE_HARD` | `risk_params.max_risk_per_trade_hard` |
| 9 | `MAX_SAME_DIRECTION` | `risk_params.max_same_direction` |
| 10 | `MAX_SAME_SECTOR_DIRECTION` | `risk_params.max_same_sector_direction` |
| 11 | `MAX_INDEX_WEIGHT_SCORE` | `risk_params.max_index_weight_score` |

**Kanıt:** `grep -c "\b<SABİT>\b" engine/baba.py` → her biri 1 (yalnız declaration satırı). Dış import kontrolü: `grep -rn "from engine.baba import"` hiçbirini import etmiyor.

**Neden sorun:**
1. **Config desync riski:** Modül sabitleri config değerleriyle silah
2. **Dead code:** declaration + 0 kullanım
3. **Yanıltıcı `# config: risk.xxx` yorumları** sabitlerin config'den geldiği izlenimi veriyor
4. CLAUDE.md Bölüm 3.2 ruhuna aykırı (fake config source)

**Çözüm:** `baba.py:151-164` iki sabit bloğu tamamen kaldırıldı, yerine kaldırma gerekçesini belgeleyen "NOT (v5.9.3 — BULGU #12)" yorum bloğu eklendi. Modül docstring `risk_params.*` field adlarını gösterecek şekilde güncellendi.

**Doğrulama:** 34/34 critical_flows yeşil. Davranış değişimi sıfır (kod zaten bu sabitleri okumuyordu).

---

## 6. v6.0.0 Bump + "ÜSTAT Plus V6.0" Yeniden Markalama

### 6.1 Bump Tespiti (CLAUDE.md Bölüm 7 Adım 3)

| Metrik | Değer |
|---|---|
| Son versiyon commit | `e57b008` (v5.9 ilk, 2026-03-28) |
| Mevcut versiyon | 5.9.0 |
| `git diff --shortstat e57b008..HEAD` | 202 dosya, +89737 / -5096 = 94833 satır |
| Toplam izlenen kod | 168064 satır |
| **Ham oran** | **%56.4** |
| **Üretken kod oranı (docs hariç)** | **%33.7** |
| Eşik | %10 — aşıldı, bump **zorunlu** |

**Kategori kırılımı (e57b008..HEAD):**
- `engine/*.py`: 6828 / 1643 = 8471 (%26.1 of 32448)
- `api/**/*.py`: 388 / 20 = 408 (%9.7 of 4220)
- `desktop/src/**`: 2222 / 611 = 2833 (%16.6 of 17076)
- `tests/**`: 8382 / 5 = 8387 (%142 — test kadrosu büyüdü)
- `docs/**`: 64933 / 1 = 64934
- `config/*.json`: 12 / 5 = 17

### 6.2 Versiyon Numarası Seçimi

CLAUDE.md numbering kuralı: "minor 9'dan sonra major artar" → 5.9 → **6.0**.
Kullanıcı talimatı: "uygualamamnın adınıda değişitrelim. 'ÜSTAT Plus V6.0' bu olsun".

### 6.3 22 Atomik Patch

**Fonksiyonel sabitler (9):**
| Dosya | Değişiklik |
|---|---|
| `engine/__init__.py` | `VERSION = "5.9.0"` → `"6.0.0"` |
| `config/default.json` | `"version": "5.9.0"` → `"6.0.0"` |
| `api/server.py` | Module docstring + `API_VERSION` + FastAPI `title` + root `"name"` |
| `api/schemas.py` | `version: str = "5.9.0"` → `"6.0.0"` |
| `desktop/package.json` | version + description ("ÜSTAT v5.9 —" → "ÜSTAT Plus V6.0 —") |

**UI / Electron (13):**
| Dosya | Değişiklik |
|---|---|
| `desktop/main.js` | header docstring + `APP_TITLE` + splash HTML h1 |
| `desktop/preload.js` | header docstring |
| `desktop/mt5Manager.js` | header docstring (v5.7 → V6.0, geçmiş bump atlaması düzeltildi) |
| `desktop/src/components/TopBar.jsx` | header docstring + layout comment + h1 logo |
| `desktop/src/components/LockScreen.jsx` | header docstring + h1 logo |
| `desktop/src/components/Settings.jsx` | header docstring + `VERSION` const + Uygulama FieldRow |

**Kısayol script'leri (5):**
| Dosya | Değişiklik |
|---|---|
| `create_shortcut.ps1` | header comment + `$ShortcutPath` filename + `$Shortcut.Description` |
| `update_shortcut.ps1` | `$newName` + `$shortcut.Description` |

### 6.4 Arkeolojik Koruma

Tarihsel/etiket niteliğindeki `v5.9.2`, `v5.9.3 — BULGU`, `// v5.9: ...` stili yorumlar **KORUNDU** — bunlar "bu değişiklik ne zaman yapıldı" etiketi, ürün adı değil. Yalnız aktif UI/başlık/sabit stringleri değiştirildi.

### 6.5 Doğrulama

- `py_compile engine/__init__.py`: **OK**
- `py_compile api/server.py`: **OK**
- `py_compile api/schemas.py`: **OK**
- `tests/critical_flows`: **34/34 passed** (3 SyntaxWarning — baseline, BULGU dışı)
- `npm run build`: **SUCCESS** — `ustat-desktop@6.0.0`
  - 728 modül transformed
  - `dist/index.html` — 1.06 kB (gzip: 0.60 kB)
  - `dist/assets/index-CiUWDTb0.css` — 90.52 kB (gzip: 15.07 kB)
  - `dist/assets/index-TMBJ4HbH.js` — 880.33 kB (gzip: 251.69 kB)
  - Build süresi: 2.88s

---

## 7. Commit Listesi (Oturum Özeti)

```
32ebeda build: #164 v6.0.0 bump + rebrand "ÜSTAT Plus V6.0"
aca9aa7 refactor: #163 BULGU #12 remove 11 dead module constants from baba.py
33b519c refactor: #162 BULGU #11 regime hysteresis docstring + config-fy magic number
6b2655a docs: #161 BULGU #10 datetime tz mini-audit + naive local-time docstring
```

---

## 8. Versiyon Durumu (v6.0.0 sonrası)

| Dosya | Değer |
|---|---|
| `engine/__init__.py` | `VERSION = "6.0.0"` |
| `config/default.json` | `"version": "6.0.0"` |
| `api/server.py` | `API_VERSION = "6.0.0"`, title `"ÜSTAT Plus V6.0 API"` |
| `api/schemas.py` | `version: str = "6.0.0"` |
| `desktop/package.json` | `"version": "6.0.0"`, name "ÜSTAT Plus V6.0 — VİOP Algorithmic Trading Desktop" |
| `desktop/main.js` | `APP_TITLE = 'ÜSTAT Plus V6.0 VİOP Algorithmic Trading'` |
| Splash / TopBar / LockScreen h1 | `ÜSTAT Plus V6.0` |

---

## 9. Piyasa Durumu

- **Tarih:** Cumartesi, 11 Nisan 2026
- **Piyasa:** KAPALI (hafta sonu)
- **Savaş/Barış:** **Barış Zamanı** — tüm değişiklikler izinli

---

## 10. BULGU Listesi (v6.0 sonrası tamamlanan 12 bulgu)

| # | Commit | Konu |
|---|---|---|
| #1 | #152 | OLAY rejimi Kural 7 uyumu |
| #2 | #153 | `_still_above_hard_drawdown` ölü fonksiyon fix |
| #3 | #155 | Manuel işlem ayrı günlük sayaç |
| #4 | #154 | `activate_kill_switch_l1` kilit eksikliği |
| #5 | #156 | `baba.py` modül docstring stale fix |
| #6 | #157 | `check_drawdown_limits` yanıltıcı isim doc |
| #7 | #158 | `_process_ustat_notifications` yanlış teşhis + statik test |
| #8 | #159 | `receive_feedback()` yanlış teşhis + statik test |
| #9 | #160 | `_calculate_index_weight_score` lot-aware |
| #10 | #161 | datetime tz mini-audit + naive docstring |
| #11 | #162 | regime hysteresis docstring + config-fy |
| #12 | #163 | 11 dead module constant removal |

**12/12 audit bulgusu atomik, izole commit'lerle kapatıldı.**

---

## 11. Sonraki Oturum İçin Notlar

- Kullanıcı kısayol dosyası adını `USTAT Plus V6.0.lnk` olarak yeniden oluşturmak için `create_shortcut.ps1` veya `update_shortcut.ps1` çalıştırmalı (script'ler güncellendi, kısayol otomatik yeniden oluşmaz).
- Tüm oturum raporlarında kullanılan informal etiket `v5.9.3 — BULGU` tarihsel refeans olarak kaldı — yeni BULGU fix'leri geldiğinde `v6.0.0 — BULGU` yaklaşımı kullanılabilir.
- Desktop uygulamasını yeni versiyon/markayla görmek için uygulamayı yeniden başlat (start_ustat.py → Electron yeni dist/ bundle'ını yükleyecek).
