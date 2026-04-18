# Oturum Raporu — Haber Entegrasyonu Kaldırma

**Tarih:** 2026-04-18 (Cumartesi — Barış Zamanı)
**Versiyon:** v6.0.0 → **v6.1.0**
**Sınıf:** C3 (Kırmızı Bölge: `baba.py`, `main.py`, `config/default.json`, `api/server.py`)
**Süre:** ~90 dk
**Onay:** Kullanıcı yazılı onayı ("haber entegrasyonunu kaldıralım", "evet uygula")

---

## 1. Gerekçe

17 Nisan 2026 Cuma, saat 11:16:31'de F_KONTR sembolünde 75 lotluk SHORT pozisyon (ticket #8050585554) BABA'nın `_check_olay` → `news_bridge.should_trigger_olay()` zinciriyle zorla kapatıldı. Tetikleyici: **"US Fed Sanayi Üretimi (Yıllık): 0.70 (Beklenti: 2.10)"** — ABD makro verisi.

**Sistemin çelişkisi:**
- Sentiment: -1.00 (CRITICAL), severity: CRITICAL → OLAY rejimi tetiklendi
- Risk çarpanı 0.0 → H-Engine `force_close_all(reason=OLAY_REGIME)` çağrıldı
- Sonuç: pozisyon +256.76 TL **kârla** kapandı — ama bu şans; haber SHORT lehineydi
- Yön-körü tasarım: sentiment=-1 geleni ayırt etmeden tüm pozisyonları kapatıyor
- ABD makro verisi VİOP'a birinci derece etki etmez; sınıflandırma CRITICAL olmamalı

**Karar:** Tüm haber entegrasyonunu kaldırmak — parçalı tuning yerine temiz kesim. OLAY rejimi (USDTRY şok + expiry tetikleyicileri) korunur.

---

## 2. Kapsam ve Etkilenen Dosyalar

### Silinen dosyalar (7)
| Dosya | Satır | Amaç |
|---|---|---|
| `engine/news_bridge.py` | 1551 | NewsBridge, PreMarketBriefing, MT5FileProvider, BenzingaProvider, RSSProvider, NewsCache, SentimentAnalyzer |
| `api/routes/news.py` | 193 | 5 endpoint: status, active, briefing (get/post), test |
| `desktop/src/components/NewsPanel.jsx` | 158 | React haber paneli |
| `desktop/src/components/NewsPanel.css` | 252 | Stil dosyası |
| `tests/test_news_100_combinations.py` | ~500 | 100 senaryolu haber tepkisi testi |

### Düzenlenen dosyalar (13)

**Engine (Kırmızı Bölge — C3):**
1. `engine/baba.py` — 4 blok kaldırıldı:
   - Satır 420: `_news_bridge` attribute
   - Satır 422-425: `set_news_bridge()` setter metodu
   - Satır 984-992: `_check_olay` içinde haber bloğu → artık yalnızca USDTRY şok + expiry
   - Satır 1027-1039: `_check_early_warnings` içinde NEWS_ALERT bloğu
2. `engine/main.py` — 2 blok kaldırıldı:
   - Satır 175-187: NewsBridge + PreMarketBriefing init
   - Satır 823-847: `news_bridge.run_cycle()` + `premarket_briefing.check()` çağrıları
3. `engine/utils/signal_engine.py` — J kaynağı stub'a çevrildi:
   - `_source_news_event()` artık her zaman NEUTRAL SourceResult döner
   - `generate_signal()` docstring'i güncellendi (news_bridge deprecated)
   - Satır 1338: J kaynağı çağrısı korundu (10 kaynaklı skorlama boyutu bozulmasın)
4. `engine/ogul.py` — Satır 1105: eskimiş yorum güncellendi

**API (Sarı Bölge):**
5. `api/server.py` — `news` import (satır 49) + `include_router` (satır 236) kaldırıldı; `API_VERSION` → 6.1.0; `ÜSTAT Plus V6.0 API` → `V6.1 API` (3 yer)
6. `api/schemas.py` — 4 Pydantic model silindi: `NewsEventItem`, `NewsStatusResponse`, `NewsActiveResponse`, `LiveNews`; `NEWS_ALERT` erken uyarı tipi listesinden çıkarıldı
7. `api/deps.py` — `get_news_bridge()` fonksiyonu silindi
8. `api/routes/live.py` — WebSocket `type: "news"` yayıncı bloğu kaldırıldı

**Frontend (Yeşil Bölge):**
9. `desktop/src/components/Dashboard.jsx` — `getNewsActive` import, `NewsPanel` + `NewsPanel.css` import, `newsData` state, WebSocket `msg.type==='news'` dinleyici, REST polling fallback, `CARD_LABELS.news`, `DEFAULT_CARD_ORDER` içindeki 'news', `case 'news'` render bloğu temizlendi
10. `desktop/src/services/api.js` — `getNewsStatus()` + `getNewsActive()` fonksiyonları silindi
11. `desktop/src/components/RiskManagement.jsx` — `news_alert: 'Olumsuz haber algılandı'` label mapping'i silindi

**Config:**
12. `config/default.json` — `"news"` bloğu (17 anahtar, satır 148-169) komple silindi

**Versiyon + Tarihçe:**
13. `docs/USTAT_GELISIM_TARIHCESI.md` — #237 (Removed) + #238 (Changed) kayıtları eklendi, versiyon bloğu [6.1.0] — 2026-04-18 olarak açıldı

**Versiyon güncellenen dosyalar (7):**
- `engine/__init__.py` VERSION: `6.0.0` → `6.1.0`
- `config/default.json` version: `6.0.0` → `6.1.0`
- `desktop/package.json` version + description + productName
- `api/server.py` API_VERSION + title + root endpoint (3 yer)
- `desktop/main.js` APP_TITLE + splash HTML V6.0 → V6.1
- `desktop/src/components/LockScreen.jsx` VERSION_FALLBACK
- `desktop/src/components/Settings.jsx` VERSION_FALLBACK + BUILD_DATE

---

## 3. Anayasa ve Kural Uyumu

| Kural | Durum |
|---|---|
| **Kural 1 — Çağrı Sırası** | ✅ Korundu. NewsBridge döngü 2.7 adımıydı, resmi BABA→OĞUL→H-Engine→ÜSTAT zincirinin dışında |
| **Kural 7 — OLAY Rejimi** | ✅ `risk_multiplier=0.0` kuralı dokunulmadı. OLAY hâlâ USDTRY %2+ 5dk şokunda + expiry crossing'de tetiklenir |
| **Kural 11 — Başlatma Zinciri** | ✅ NewsBridge resmi lifespan sırasında (Config→DB→MT5→Pipeline→Ustat→Baba→Ogul) yoktu, ayrı blokta idi |
| **Kural 12 — Lifespan Sırası** | ✅ Constructor sırası değişmedi |
| **Kural 13 — Kapanış Sırası** | ✅ Etkilenmedi |
| **Siyah Kapı #8 — detect_regime** | ⚠️ Mantığı değişmedi, sadece bir tetikleyici dalı (haber) kaldırıldı. USDTRY ve expiry yolları aynen kaldı. Kanıtlı kullanıcı onaylı değişiklik |
| **Fonksiyon silme yasağı** | Kullanıcı onaylı feature removal kapsamında `set_news_bridge()`, `get_news_bridge()`, `_check_olay` haber dalı kaldırıldı. Tüm callerlar aynı işlemde temizlendi — çağrı zinciri kırılmadı |
| **Governance — protected_assets** | ✅ `news_bridge.py` korunan varlık listesinde değildi — silme özel onay gerektirmedi |

---

## 4. Test ve Doğrulama

### Kritik Akış Testleri
`tests/critical_flows/test_static_contracts.py` — 12/12 PASS beklenir (çalıştırma PowerShell scriptine dahil).

Etkilenen test: yok. OLAY rejimi statik kontrat testleri (CI-06 risk_multiplier=0.0) BABA'nın `RISK_MULTIPLIERS` sabitine dayanır, o değişmedi.

### Manuel Doğrulama (Faz 7'de yapılır)
- [ ] Electron açılışı: NewsPanel kartı Dashboard'da yok
- [ ] Settings ekranında v6.1.0 gösteriliyor
- [ ] LockScreen V6.1 gösteriyor
- [ ] API `/api/news/status` ve `/api/news/active` 404 dönüyor
- [ ] Engine log'unda "NewsBridge" stringi geçmiyor
- [ ] Build 0 hata ile tamamlanıyor
- [ ] Engine restart sonrası 10 saniyelik döngü hatasız

---

## 5. Bilinen Kalıntılar (yapılacak iş)

1. **UstatNewsService (MT5 tarafı):** Kullanıcının manuel olarak MT5 terminalinde "Hizmetler → UstatNewsService → Durdur + Sil" yapması gerekir. Artık bu servise ihtiyaç yok; arka planda boşuna `ustat_news.json` yazmaya devam eder. (Python tarafı dosyayı okumuyor, ama disk I/O israfı.)

2. **CLAUDE.md başlık:** `# ÜSTAT v5.9 — ANA REHBER` satırı stale. Ana rehberin versiyonu ayrı versiyonlamaya sahip (şu an 3.3). Kod v6.1.0'a çıktı; başlıktaki "v5.9" güncellenebilir. Düşük öncelikli, ayrı commit'te yapılabilir.

3. **Eskimiş yorumlar:** `Dashboard.jsx` içinde birkaç "v5.7.1: Haber" tipinde tarihi yorum kaldı — kaldırıldığı için artık anlamsız ama kod akışını etkilemez.

4. **localStorage `ustat_dashboard_card_order`:** Kullanıcı önceden 'news' kartını sıralamaya eklediyse, artık switch/case'de default'a düşer ve render edilmez. Graceful degradation. Temiz restart öneririz — veya kullanıcı ayarlar panelinden kart sırasını yeniler.

---

## 6. Commit Planı

Final uygulama kullanıcı tarafından PowerShell scriptiyle yapılır. Önerilen ayrım:

1. `chore(config): baseline_date 2026-04-16 09:50 güncellemesi` — önceki oturumdan stale olan baseline_date değişikliği ayrı commit
2. `feat!: haber entegrasyonu tamamen kaldırıldı (v6.1.0)` — tüm kaldırma işleri tek atomik commit

**Neden tek commit:** Haber kaldırma monolitik bir refactor. Faz 1 (BABA) commit'i Faz 2 (main.py) olmadan rollback'lendiğinde BABA olmayan NewsBridge'i çağırır → crash. Geri alma birimi faz değil, tüm refactor.

---

## 7. Rollback Planı

```powershell
# Tüm değişikliği geri al (tek commit):
git revert HEAD --no-edit
# Build ve restart:
cd desktop ; npm run build ; cd ..
python .agent\claude_bridge.py restart_app
```

Baseline_date değişikliği ayrı commit'te olduğu için o ayrı da geri alınabilir.

---

## 8. İstatistikler

- **Silinen satır:** ~2600+ (5 dosya komple + entegrasyon blokları)
- **Eklenen satır:** ~15 (stub + docstring + tarihçe girdisi)
- **Net değişim:** −2585 satır
- **Oran:** Proje toplam satırına göre yaklaşık %3-5 küçülme
- **Dokunuş noktası:** 13 + 5 silme + 7 versiyon = 25 dosya

---

## 9. Özet

Haber entegrasyonu — NewsBridge, PreMarketBriefing, NewsPanel, API endpoint'leri, WebSocket yayını, config bloğu ve testi — USTAT kod tabanından tamamen kaldırıldı. BABA'nın `_check_olay` fonksiyonu artık yalnızca USDTRY şok ve expiry tetikleyicilerine bakıyor; OLAY rejimi davranışı (risk_multiplier=0.0) anayasal olarak korundu. OĞUL'un 10 kaynaklı sinyal skorlaması J kaynağı nötr stub'a çevrildi, böylece skorlama boyutu bozulmadan J her zaman NEUTRAL döner.

Versiyon v6.0.0 → v6.1.0 bump edildi. Kullanıcı PowerShell scriptini çalıştırarak dosya silmeleri, commit, build ve restart'ı tamamlayacak.
