# ÜSTAT v5.0 — Eksik Kalan Alanların Derin Analizi (Faz 2)

**Tarih:** 2026-03-01  
**Kapsam:** Engine modülleri, MT5 bağlantı yönetimi, hata yönetimi, canlı veri güncelleme, Kill-Switch mantığı, Config/Ayarlar  
**Kural:** Hiçbir dosyada değişiklik yapılmadı; sadece okuma, analiz ve raporlama.

Bu rapor, ilk rapordaki 12 iyileştirme maddesinin ardından **#13'ten** devam eder.

---

## EKSİK ALAN 1: ENGINE MODÜLLERİ — ÖZET

### baba.py
- **check_drawdown_limits (satır 748–796):** `equity <= 0` durumunda `return True` (işleme izin veriliyor). Bakiye/equity sıfır veya negatif hesapta işlem açmak risklidir; en azından `return False` veya açık uyarı + False düşünülmeli.
- **check_drawdown_limits:** `snap` yoksa `return True` — ilk çalıştırma veya snapshot yoksa limit kontrolü atlanıyor; tasarım bilinçli olabilir ama dokümante edilmeli.
- **_close_all_positions (satır 1465–1494):** L3’te tüm pozisyonlar kapatılıyor; bir pozisyon kapatılamazsa sadece `logger.error` ve döngü devam ediyor. Çağıran tarafa başarısız ticket’lar dönmüyor; API’den “hangi pozisyonlar kapatılamadı” bilgisi verilemiyor.
- **Fake analiz:** `pos.get("symbol")`, `pos.get("type")` — MT5Bridge.get_positions() "BUY"/"SELL" string ve base sembol döndürüyor; uyumlu.

### ogul.py
- **process_signals (satır 211–270):** `symbols` boş liste gelince döngüler çalışmıyor, `_check_end_of_day`, `_advance_orders`, `_manage_active_trades`, `_sync_positions` yine çalışıyor. Boş Top 5 edge case’i güvenli.
- **get_bars / tick:** `df.empty` veya `tick is None` durumları None/early return ile ele alınıyor; hatalı veri gelse bile sinyal üretilmiyor.

### ustat.py
- **_refresh_scores:** Tüm kontratlar vade/haber filtresinden elenirse `top5_final` boş liste; `_current_top5 = top5_final` atanıyor. main.py `select_top5(regime)` ile boş liste alabilir ve ogul’a `process_signals([], regime)` geçer; davranış tutarlı.

### main.py
- **_heartbeat_mt5:** MT5Bridge.heartbeat() başarısızsa bir kez `connect(launch=False)` deniyor. Sabit `MAX_MT5_RECONNECT = 5` ana döngüde kullanılmıyor; yani “5 deneme” dokümantasyonla uyumsuz (bridge’de 3 reconnect denemesi var).
- **Cycle hata:** Genel Exception yakalanıp loglanıyor, döngü sürüyor; _SystemStopError ve _DBError ayrı işleniyor. Recovery mantığı net.

---

## EKSİK ALAN 2: MT5 BAĞLANTI YÖNETİMİ — ÖZET

- **initialize:** `mt5.initialize(**kwargs)` için ayrı bir timeout parametresi yok; bloklayan çağrı uzun sürebilir. Denemeler arası bekleme `BASE_WAIT * (2 ** (attempt - 1))` (2, 4, 8 sn) var.
- **Reconnect:** launch=False iken MAX_RETRIES_RECONNECT=3; heartbeat içinde _ensure_connection() ile 3 deneme. main tarafında ek bir connect(False) denemesi var; toplam 4 deneme/siklus.
- **send_order:** Lot, `volume_min` / `volume_max` (symbol_info) ile kıyaslanmıyor; geçersiz lot ile emir MT5’e gidebilir ve retcode ile reddedilir. Ön validasyon yok.
- **close_position:** positions_get(ticket=ticket) ile tek pozisyon alınıyor; tick yoksa fiyat 0, request gönderilmez; retcode != DONE ise None dönülüyor. Hata yönetimi var.
- **Frontend MT5 göstergesi:** GET /api/status → mt5_connected = mt5.is_connected; engine çalışırken canlı. Engine durunca get_engine() aynı instance’ı döndürür, mt5 disconnect sonrası is_connected False olur.

---

## EKSİK ALAN 3: ERROR HANDLING VE RECOVERY — ÖZET

- **api.js:** Tüm getStatus, getAccount, getTrades vb. try/catch ile sarılı; catch’te hata loglanmıyor, sadece varsayılan obje dönülüyor. Kullanıcı “bağlantı yok” veya “sunucu hatası” görmez; sessiz fallback.
- **Loading:** Dashboard/TopBar/OpenPositions ilk yüklemede veri çekene kadar loading state yok (sadece boş/0 değerler); TradeHistory/Performance/Settings loading gösteriyor.
- **Timeout:** axios timeout=5000; 5 sn sonra catch’e düşer, varsayılan veri döner.
- **Retry:** Frontend’de yeniden deneme veya exponential backoff yok.
- **Backend:** Engine cycle’da Exception loglanıp döngü devam ediyor; API route’larında try/except var (örn. killswitch). Yakalanmamış exception uygulamayı çökertebilir (örn. lifespan dışı).
- **Graceful degradation:** Bir modül (örn. pipeline) hata verince main sadece loglayıp cycle’a devam ediyor; engine durmuyor.

---

## EKSİK ALAN 4: CANLI VERİ GÜNCELLEME — ÖZET

- **Polling:** Dashboard 10 sn, TopBar 2 sn, OpenPositions 5 sn, RiskManagement 5 sn, ManualTrade 10 sn. Aynı API’ler (status, account, positions, risk) farklı sayfalarda tekrarlı çağrılıyor; paylaşılan cache yok.
- **WebSocket:** /ws/live her 2 sn push; Dashboard ve OpenPositions kendi useEffect’inde connectLiveWS çağırıyor. Sekme değişince unmount ile cleanup çalışıyor, clearInterval/close ile sızıntı yok.
- **Stale data:** Sekme değişip geri gelince component yeniden mount olur, useEffect tekrar çalışır ve son veri çekilir; ek bir “last updated” veya force-refresh yok.

---

## EKSİK ALAN 5: KILL-SWITCH GERÇEK ÇALIŞMA MANTIĞI — ÖZET

- **Tetikleme:** POST /api/killswitch { action: "activate" } → baba.activate_kill_switch_l3_manual() → _activate_kill_switch(L3, "manual", ...) → _close_all_positions("KILL_SWITCH_L3"). Tüm kapanışlar senkron; çok pozisyon varsa API yanıtı gecikir.
- **Pozisyon kapatma:** _close_all_positions mt5.get_positions() ile listeyi alıp her ticket için close_position(ticket) çağırıyor. Bir kapanış başarısız olursa log yazılıyor, sonuç çağırana iletilmiyor.
- **Yeni işlem engeli:** check_risk_limits L3’te can_trade=False, lot_multiplier=0; process_signals yeni sinyal açmıyor. Engine durmuyor.
- **Recovery:** acknowledge → baba.acknowledge_kill_switch() → _clear_kill_switch(), monthly_paused=False. L3/L2 temizlenir.
- **Otomatik kill-switch:** Günlük kayıp limiti check_drawdown_limits’te aşılırsa _activate_kill_switch(L2, "daily_loss", ...) tetikleniyor; L2’de can_trade=False. Akış doğru.

---

## EKSİK ALAN 6: CONFIG/AYARLAR — ÖZET

- **Yükleme:** engine/config.py CONFIG_PATH = config/default.json; Config._load() ile okunuyor. Dosya yoksa _data={}, JSON hatasında _data={}.
- **Validasyon:** config.get("mt5.path", default) — negatif lot, sıfır limit, geçersiz sembol kontrolü yok. Engine/mt5_bridge path/login/server None alabilir.
- **Hot reload:** Config sadece __init__’te yükleniyor; dosya değişince uygulama yeniden başlatılmadan güncellenmez.
- **Default:** get(key, default) ile eksik anahtarlar default döner; default.json mevcut, bölümler tanımlı.

---

## İYİLEŞTİRME KARTLARI (#13 – #22)

═══════════════════════════════════════════════════════
İYİLEŞTİRME #13
═══════════════════════════════════════════════════════

📍 KONUM: engine/baba.py → check_drawdown_limits (satır 765–767)
📂 MODÜL: Engine (BABA)
🏷️ KATEGORİ: Güvenlik / Stabilite
⚡ ÖNCELİK: YÜKSEK

🔍 MEVCUT DURUM:
```python
if equity <= 0:
    return True
```
Equity sıfır veya negatifken True dönülüyor; yani günlük/toplam drawdown kontrolü atlanıyor ve “limit aşılmadı” kabul ediliyor. Bu durumda check_risk_limits devam edip diğer kontroller (günlük işlem sayısı vb.) çalışıyor; can_trade başka sebeplerle False olabilir ama equity<=0 özel olarak “işlem durdur” anlamında kullanılmıyor.

❌ SORUN / EKSİKLİK:
Bakiye/equity sıfır veya negatif hesapta yeni işlem açmak risklidir. Mevcut kod bu durumu “limit yok” gibi yorumluyor; açıkça “işlem yok” kararı verilmiyor.

✅ ÖNERİLEN DEĞİŞİKLİK:
equity <= 0 (ve isteğe bağlı balance <= 0) ise False döndür: örn. `if equity <= 0: logger.warning("Equity/bakiye geçersiz — işlem durduruluyor"); return False`. Böylece check_risk_limits bu noktada can_trade=False üretebilir (check_drawdown_limits False döndüğü için mevcut akışta zaten L2 tetiklenir).

📊 FAYDA:
Sıfır/negatif equity’de yeni işlem açılmaz; operasyonel risk azalır.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/baba.py
- Yan etki riski: Düşük (sadece edge case davranışı)
- MT5 etkisi: Yok
- Canlı işlem riski: Yok (sadece engel)
- Geri dönüş: Kolay

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅ (equity 0 / negatif test)

═══════════════════════════════════════════════════════
İYİLEŞTİRME #14
═══════════════════════════════════════════════════════

📍 KONUM: engine/baba.py → _close_all_positions (satır 1465–1494)
📂 MODÜL: Engine (BABA) / Kill-Switch
🏷️ KATEGORİ: Fonksiyonel
⚡ ÖNCELİK: ORTA

🔍 MEVCUT DURUM:
L3 tetiklendiğinde _close_all_positions tüm pozisyonları dolaşıp mt5.close_position(ticket) çağırıyor. Başarısız kapanışta sadece logger.error; closed_count sadece başarılıları sayıyor. Çağıran (activate_kill_switch_l3_manual → _activate_kill_switch) sonuç almıyor; API de “kaç tanesi kapatılamadı” bilgisini dönemiyor.

❌ SORUN / EKSİKLİK:
Kullanıcı/operatör L3 bastığında bazı pozisyonlar (piyasa kapalı, likidite yok vb.) kapatılamayabilir. Şu an bu bilgi sadece logda; UI’da veya API yanıtında gösterilmiyor.

✅ ÖNERİLEN DEĞİŞİKLİK:
_close_all_positions başarısız ticket’ları bir liste olarak döndürsün (veya dict: closed=[], failed=[]). activate_kill_switch_l3_manual veya API tarafında bu bilgi event/mesaj olarak kaydedilsin; isteğe bağlı olarak KillSwitchResponse’a “closed_count”, “failed_tickets” gibi alanlar eklenip frontend’de gösterilebilir.

📊 FAYDA:
L3 sonrası hangi pozisyonların kapatılamadığı izlenebilir; operatör müdahalesi kolaylaşır.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/baba.py; isteğe bağlı api/routes/killswitch.py, api/schemas.py
- Yan etki riski: Düşük
- MT5 etkisi: Yok (sadece mevcut close_position kullanımı)
- Canlı işlem riski: Yok
- Geri dönüş: Kolay

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅ (bir pozisyon kapatılamaz simülasyonu)

═══════════════════════════════════════════════════════
İYİLEŞTİRME #15
═══════════════════════════════════════════════════════

📍 KONUM: engine/mt5_bridge.py → send_order (satır 534–596)
📂 MODÜL: MT5
🏷️ KATEGORİ: Fonksiyonel
⚡ ÖNCELİK: ORTA

🔍 MEVCUT DURUM:
send_order symbol_info ile tick_size, filling_mode alıyor; volume_min, volume_max, volume_step mevcut ama lot değeri bunlarla karşılaştırılmıyor. request["volume"] = lot doğrudan gönderiliyor. MT5 geçersiz lot’ta emri reddeder (retcode) ama ön validasyon yok.

❌ SORUN / EKSİKLİK:
Lot < volume_min, lot > volume_max veya volume_step’e uymayan değerler reddedilir; kullanıcı/çağıran sadece _last_order_error ile sonucu görür. Önceden reddetmek hem hata mesajını netleştirir hem gereksiz ağ/MT5 çağrısını azaltır.

✅ ÖNERİLEN DEĞİŞİKLİK:
symbol_info sonrası lot’u volume_min, volume_max ile sınırla; volume_step’e göre yuvarla (örn. round(lot / volume_step) * volume_step). Sınır dışı veya adım uyumsuzsa None dönüp _last_order_error’a açıklayıcı reason yaz; order_send çağrılmasın.

📊 FAYDA:
Geçersiz lot ile emir gönderimi engellenir; hata mesajı anlaşılır olur.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/mt5_bridge.py
- Yan etki riski: Düşük
- MT5 etkisi: Var (emir gönderim öncesi)
- Canlı işlem riski: Yok (sadece validasyon)
- Geri dönüş: Kolay

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅ (lot 0, çok büyük, step uyumsuz)

═══════════════════════════════════════════════════════
İYİLEŞTİRME #16
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/services/api.js (tüm catch blokları)
📂 MODÜL: Error Handling / Frontend
🏷️ KATEGORİ: UX / Stabilite
⚡ ÖNCELİK: YÜKSEK

🔍 MEVCUT DURUM:
getStatus, getAccount, getTrades vb. try/catch ile sarılı; catch’te sadece varsayılan obje dönülüyor, hata loglanmıyor veya kullanıcıya iletilmiyor. Örn. API kapalı veya timeout’ta ekran “0 işlem”, “bağlantı yok” gibi tek bilgi göstermiyor; kullanıcı verinin gerçekten boş mu yoksa hata mı olduğunu anlamıyor.

❌ SORUN / EKSİKLİK:
Hata durumunda sessiz fallback; kullanıcı bağlantı/API hatasını fark etmeyebilir. Ayrıca retry yok; geçici ağ kesintisinde hemen varsayılan veri gösteriliyor.

✅ ÖNERİLEN DEĞİŞİKLİK:
(1) catch’te en azından console.error veya merkezi bir log/raporlama ile hata kaydedilsin. (2) İsteğe bağlı: Kritik endpoint’ler (getStatus, getAccount) için 1–2 kez kısa aralıklı retry (örn. 1 sn sonra tekrar dene). (3) İsteğe bağlı: API hatası durumunda bileşenlere “connection_error” veya “last_error” gibi bir flag/state geçilsin; UI’da “Bağlantı hatası — yenile” gibi mesaj ve yenile butonu gösterilsin.

📊 FAYDA:
Hata görünür olur; geçici kesintilerde retry ile veri geri gelebilir.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/services/api.js; isteğe bağlı bileşenler (TopBar, Dashboard)
- Yan etki riski: Düşük
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Kolay

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅ (API kapalı, timeout)

═══════════════════════════════════════════════════════
İYİLEŞTİRME #17
═══════════════════════════════════════════════════════

📍 KONUM: engine/main.py → _heartbeat_mt5 ve CYCLE sabitleri (satır 46–47, 328–356)
📂 MODÜL: Engine
🏷️ KATEGORİ: Kod kalitesi / Dokümantasyon
⚡ ÖNCELİK: DÜŞÜK

🔍 MEVCUT DURUM:
MAX_MT5_RECONNECT = 5 tanımlı ama _heartbeat_mt5 içinde kullanılmıyor. Heartbeat başarısızsa sadece bir kez connect(launch=False) deniyor. MT5Bridge’de MAX_RETRIES_RECONNECT = 3; yani reconnect’te 3 deneme var. Dokümantasyonda “5x reconnect” geçiyor; gerçek davranış 3 (bridge) + 1 (main) = 4 deneme/siklus.

❌ SORUN / EKSİKLİK:
Sabit kullanılmadığı için ileride “5 deneme” yapılmak istenirse kolayca unutulur. Dokümantasyon ile kod uyumsuz.

✅ ÖNERİLEN DEĞİŞİKLİK:
(1) _heartbeat_mt5’te heartbeat() ve connect(False) başarısızsa, MAX_MT5_RECONNECT’e kadar (örn. 2–3 sn aralıklarla) tekrar connect(False) denensin; hepsi başarısızsa False dönsün. Veya (2) MAX_MT5_RECONNECT’i kaldırıp docstring’i güncelleyin: “Heartbeat başarısızsa bir kez reconnect (launch=False) denenir; bridge içinde 3 deneme var.”

📊 FAYDA:
Davranış ile dokümantasyon/sabit tutarlı olur.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/main.py
- Yan etki riski: Yok (sadece doc/sabit)
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Kolay

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅

═══════════════════════════════════════════════════════
İYİLEŞTİRME #18
═══════════════════════════════════════════════════════

📍 KONUM: engine/config.py → _load ve Config.get
📂 MODÜL: Config
🏷️ KATEGORİ: Stabilite
⚡ ÖNCELİK: ORTA

🔍 MEVCUT DURUM:
Dosya yoksa veya JSON parse hatası olunca _data = {}; config.get("mt5.path") None döner (default verilmezse). Engine/mt5_bridge path/login/server için None alabilir; mt5.initialize(path=None) çağrılabilir. Validasyon yok; negatif lot, sıfır limit gibi değerler config’ten okunup doğrudan kullanılabilir.

❌ SORUN / EKSİKLİK:
Config bozuk veya eksikse sessizce varsayılan boş dict; kritik alanlar (mt5.path, risk limitleri) yoksa davranış belirsiz. Hatalı değer (negatif max_daily_loss vb.) engine’e girebilir.

✅ ÖNERİLEN DEĞİŞİKLİK:
(1) _load sonrası zorunlu anahtarlar için kontrol: örn. mt5.path yoksa logger.warning veya logger.error. (2) İsteğe bağlı: risk/engine bölümlerinde sayısal alanlar için min/max kontrolü (negatif veya sıfır limit kabul etmeme). (3) Dosya yoksa veya parse hatasındaysa varsayılan bir default.json içeriği (sabit dict) kullanılabilir; böylece uygulama “config yok” durumunda da çalışır.

📊 FAYDA:
Config hatalarında davranış öngörülebilir olur; hatalı değerler engine’e girmeden tespit edilebilir.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/config.py
- Yan etki riski: Düşük
- MT5 etkisi: Yok (sadece path/login okuma)
- Canlı işlem riski: Yok
- Geri dönüş: Kolay

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅ (dosya yok, bozuk JSON)

═══════════════════════════════════════════════════════
İYİLEŞTİRME #19
═══════════════════════════════════════════════════════

📍 KONUM: api/routes/killswitch.py → activate (satır 32–45)
📂 MODÜL: Kill-Switch / API
🏷️ KATEGORİ: Performans / UX
⚡ ÖNCELİK: DÜŞÜK

🔍 MEVCUT DURUM:
activate çağrısı baba.activate_kill_switch_l3_manual() ile senkron çalışıyor; içeride _close_all_positions tüm pozisyonları kapatana kadar API yanıtı bekliyor. Çok sayıda pozisyon varsa HTTP isteği uzun sürebilir; timeout veya kullanıcı “takıldı” sanabilir.

❌ SORUN / EKSİKLİK:
L3 tetikleme uzun sürebilir; kullanıcı arayüzde geri bildirim alamayabilir.

✅ ÖNERİLEN DEĞİŞİKLİK:
(1) Kısa vadede: Frontend’de “Kill-Switch tetikleniyor, pozisyonlar kapatılıyor…” gibi loading mesajı gösterilsin; timeout 30 sn veya daha yüksek tutulsun. (2) Uzun vadede: _close_all_positions arka planda (örn. asyncio.create_task veya thread) çalıştırılıp API hemen “L3 tetiklendi, kapanışlar sürüyor” dönebilir; kapanış sonucu event/log ile raporlanır.

📊 FAYDA:
Kullanıcı bekleme süresini anlar; zaman aşımı hataları azalır.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: api/routes/killswitch.py; isteğe bağlı desktop (loading state)
- Yan etki riski: Düşük
- MT5 etkisi: Yok
- Canlı işlem riski: Yok (L3 zaten kapanış)
- Geri dönüş: Kolay

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅

═══════════════════════════════════════════════════════
İYİLEŞTİRME #20
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/* — ilk veri yüklemesi
📂 MODÜL: UI/UX
🏷️ KATEGORİ: UX
⚡ ÖNCELİK: DÜŞÜK

🔍 MEVCUT DURUM:
Dashboard, TopBar, OpenPositions mount olunca hemen fetchAll/fetchData çağrılıyor; veri gelene kadar state başlangıç değerlerinde (0, boş liste). Loading göstergesi yok; kullanıcı bir an “0 işlem” görüp sonra veri dolabilir.

❌ SORUN / EKSİKLİK:
İlk açılışta “veri yükleniyor” ile “gerçekten 0 veri” ayrımı yok; kısa süreli boş ekran kafa karıştırabilir.

✅ ÖNERİLEN DEĞİŞİKLİK:
Dashboard/TopBar/OpenPositions’ta ilk yükleme için loading state ekleyin (örn. loading=true, ilk fetch tamamlanınca false). Veri gelene kadar “Yükleniyor…” veya skeleton gösterin; böylece “0” ile “henüz yok” ayrışır.

📊 FAYDA:
İlk açılışta kullanıcı ne olduğunu anlar.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/Dashboard.jsx, TopBar.jsx, OpenPositions.jsx
- Yan etki riski: Yok
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Kolay

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅

═══════════════════════════════════════════════════════
İYİLEŞTİRME #21
═══════════════════════════════════════════════════════

📍 KONUM: engine/data_pipeline.py → update_risk_snapshot; api/routes/risk.py
📂 MODÜL: Risk (Backend) — İlk rapordaki #7 ile aynı hedef
🏷️ KATEGORİ: Fonksiyonel
⚡ ÖNCELİK: YÜKSEK

🔍 MEVCUT DURUM:
Risk snapshot’a sadece equity, floating_pnl, daily_pnl, drawdown (toplam), margin_usage yazılıyor. daily_drawdown_pct veya weekly_drawdown_pct hesaplanıp snapshot’a eklenmiyor. API get_risk() bu alanları doldurmuyor; frontend Risk sayfasında “Günlük Kayıp” / “Haftalık Kayıp” barları 0/limit veya fallback (12389) ile dolduruluyor.

❌ SORUN / EKSİKLİK:
Günlük ve haftalık drawdown yüzdesi hem snapshot’ta yok hem API’de hesaplanmıyor; UI doğru dolmuyor.

✅ ÖNERİLEN DEĞİŞİKLİK:
(1) data_pipeline.update_risk_snapshot içinde gün başı equity’ye göre daily_drawdown_pct hesapla (örn. daily_pnl < 0 ise abs(daily_pnl)/day_start_equity); haftalık için hafta başı equity’den weekly_drawdown_pct hesapla. Bu alanları snapshot dict’e ekleyin. (2) database insert_risk_snapshot ve tablo şemasına daily_drawdown_pct, weekly_drawdown_pct ekleyin (veya mevcut drawdown alanına ek olarak). (3) api/routes/risk.py get_risk() içinde snap’ten bu alanları okuyup resp.daily_drawdown_pct, resp.weekly_drawdown_pct set edin. Böylece frontend (#6) sadece API’den gelen değeri gösterebilir; 12389 kaldırılır.

📊 FAYDA:
Risk sayfasında günlük/haftalık limit barları anlamlı dolar; #6 ve #7 birlikte çözülür.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/data_pipeline.py, engine/database.py, api/routes/risk.py, api/schemas.py (RiskResponse zaten alan içeriyor)
- Yan etki riski: Orta (şema/deploy)
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Orta

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅

═══════════════════════════════════════════════════════
İYİLEŞTİRME #22
═══════════════════════════════════════════════════════

📍 KONUM: engine/mt5_bridge.py → connect (satır 219–245)
📂 MODÜL: MT5
🏷️ KATEGORİ: Stabilite
⚡ ÖNCELİK: DÜŞÜK

🔍 MEVCUT DURUM:
mt5.initialize(**kwargs) senkron ve bloklayan bir çağrı; MT5 yanıt vermezse thread/process bekler. Denemeler arası _time.sleep(wait) var; toplam bekleme 2+4+8 (launch 3 deneme) veya 2+4 (reconnect 2 ek bekleme) sn. initialize’ın kendisi için ayrı timeout yok.

❌ SORUN / EKSİKLİK:
MT5 donarsa veya çok yavaş açılırsa initialize süresiz takılabilir; engine başlangıcı veya reconnect uzar.

✅ ÖNERİLEN DEĞİŞİKLİK:
Mümkünse mt5.initialize’ı bir thread veya process içinde çalıştırıp belirli süre (örn. 15–30 sn) sonra zaman aşımı ile kesmek; başarılıysa _connected set et. MT5 Python API’de doğal timeout olup olmadığı dokümantasyona bakılmalı. Alternatif: En azından denemeler arası bekleme ve max deneme sayısı ile toplam süre sınırlı kalır; dokümantasyonda “initialize bloklayabilir” uyarısı eklenebilir.

📊 FAYDA:
Aşırı bekleme durumunda davranış sınırlanır veya dokümante edilir.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/mt5_bridge.py
- Yan etki riski: Orta (thread/timeout eklenirse)
- MT5 etkisi: Var
- Canlı işlem riski: Yok (sadece bağlantı)
- Geri dönüş: Orta

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅

---

## BAĞIMLILIK HARİTASI

- **#6 (Frontend 12389 kaldır) ve #7 (API daily/weekly drawdown):** Birbirine bağımlı. Önce **#7 (veya bu rapordaki #21)** uygulanmalı: backend’de daily_drawdown_pct ve weekly_drawdown_pct hesaplanıp API’den döndürülmeli. Sonra **#6**: frontend’de 12389 kaldırılıp risk.daily_drawdown_pct, risk.weekly_drawdown_pct ve risk.equity (veya account.equity) kullanılmalı.
- **#21 (bu rapor):** İlk rapordaki #7 ile aynı hedefi backend tarafında detaylı adımlarla tarif ediyor; #7 ve #21 birlikte uygulama planı olarak düşünülebilir.
- **#14 (L3 kapanış sonucu):** Bağımsız; #19 (L3 loading/async) ile birlikte düşünülebilir.
- **#16 (API hata gösterimi) ve #20 (ilk yükleme loading):** İkisi de frontend; birlikte “hata ve yükleme deneyimi” iyileştirmesi olarak uygulanabilir.

---

## GÜNCELLENMİŞ ÖZET TABLO (#1–#22)

| # | Modül | Kategori | Öncelik | Yan Etki Riski | Kısa Açıklama |
|---|-------|----------|---------|----------------|---------------|
| 1 | Dashboard | UI/UX | ORTA | Yok | İlk stat kartı "Günlük İşlem" yap |
| 2 | Dashboard | Fonksiyonel | DÜŞÜK | Düşük | Metrik penceresi tutarlılığı veya etiket |
| 3 | İşlem Geçmişi | UI/UX | KOZMETİK | Yok | "En Kısa" ikonu ⚡ → ⏱ |
| 4 | İşlem Geçmişi | UI/UX | ORTA | Yok | "Maks. Ardışık Kayıp" birim: "X işlem" |
| 5 | Açık Pozisyonlar | UI/UX | ORTA | Düşük | Süre "s" → "st"/"sa" (saat) |
| 6 | Risk Yönetimi | Fonksiyonel | YÜKSEK | Orta | 12389 kaldır; equity API’den (#7/#21 sonrası) |
| 7 | Risk (API) | Fonksiyonel | YÜKSEK | Orta | daily/weekly drawdown API’de doldur (#21 ile) |
| 8 | Üst Bar / Risk | UI/UX | DÜŞÜK | Yok | FAZ 1 vs L1 terminoloji |
| 9 | İşlem Paneli | UI/UX | DÜŞÜK | Yok | Para birimi API’den |
| 10 | Performans Analizi | UI/UX | DÜŞÜK | Düşük | Grafik X ekseni; Sharpe tooltip |
| 11 | Üst Bar / Dashboard | UI/UX | DÜŞÜK | Yok | Günlük K/Z vs Net K/Z etiket |
| 12 | Dashboard | Kod kalitesi | DÜŞÜK | Yok | Top 5 bar maxScore hesabı |
| 13 | Engine (BABA) | Güvenlik | YÜKSEK | Düşük | equity<=0 → False (işlem durdur) |
| 14 | Engine (BABA) | Fonksiyonel | ORTA | Düşük | L3 kapanış: başarısız ticket’ları döndür |
| 15 | MT5 | Fonksiyonel | ORTA | Düşük | send_order lot volume_min/max/step validasyonu |
| 16 | Frontend / API | UX | YÜKSEK | Düşük | API hata log + isteğe bağlı retry/UI mesajı |
| 17 | Engine (main) | Kod kalitesi | DÜŞÜK | Yok | MAX_MT5_RECONNECT kullanımı veya doc güncelleme |
| 18 | Config | Stabilite | ORTA | Düşük | Config validasyon + zorunlu alan uyarısı |
| 19 | Kill-Switch / API | Performans | DÜŞÜK | Düşük | L3 tetikleme loading/async |
| 20 | Desktop | UX | DÜŞÜK | Yok | İlk yükleme loading (Dashboard, TopBar, OpenPositions) |
| 21 | Risk (Backend) | Fonksiyonel | YÜKSEK | Orta | Snapshot + API daily/weekly drawdown (#7 detayı) |
| 22 | MT5 | Stabilite | DÜŞÜK | Orta | initialize timeout veya dokümantasyon |

---

## ÖNERİLEN UYGULAMA SIRASI

1. **Öncelik 1 (Kritik / Yüksek):** #13 (equity<=0 durdur), #21+#7 (daily/weekly drawdown backend), #6 (frontend 12389 kaldır — #21/#7 sonrası), #16 (API hata gösterimi).
2. **Öncelik 2 (Orta):** #14 (L3 kapanış sonucu), #15 (lot validasyonu), #18 (config validasyonu), #1 (Dashboard kart başlığı), #4 (Ardışık kayıp birim), #5 (süre formatı).
3. **Öncelik 3 (Düşük / Kozmetik):** #2, #3, #8, #9, #10, #11, #12, #17, #19, #20, #22.

**Bağımlılık sırası:** Önce #21 (veya #7) backend drawdown, sonra #6 frontend. Diğerleri bağımsız veya küçük gruplar halinde uygulanabilir.

---

## UYGULAMA NOTU

- Hiçbir dosyada değişiklik yapılmamıştır; rapor sadece analiz ve öneri içerir.
- İlk rapor: USTAT_v5_İyileştirme_Raporu.md (#1–#12). Bu rapor: USTAT_v5_İyileştirme_Raporu_v2.md (#13–#22 + bağımlılık ve sıra).
- #6 ve #7 birleşik uygulama: Önce backend (#7/#21), sonra frontend (#6).
