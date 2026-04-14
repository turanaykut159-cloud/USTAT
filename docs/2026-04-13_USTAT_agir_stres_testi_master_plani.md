# USTAT Agir Stres Testi Master Plani

**Tarih:** 2026-04-13  
**Amaç:** USTAT uygulamasini tam anlayip, agir yuk, failure-mode ve uzun sureli operasyon kosullarinda sistemin dogruluk, dayanıklilik, kapasite ve mimari yeterliligini olcmek icin profesyonel bir stres testi programi tanimlamak.  
**Durum:** Bu dokuman test programinin tasarim raporudur. Kod tabani okunmus, katmanlar ve baski noktaları cikartilmistir. Burada anlatilanlar “nasil test edilmesi gerektigi” uzerinedir; testlerin fiilen kosulmasi ayri bir uygulama asamasidir.

---

## 1. Yonetici Ozeti

USTAT klasik bir web servisi degildir. Bu nedenle tek boyutlu bir “load test” bu sistem icin yetersizdir. Uygulama su katmanlarin birlesimidir:

- launcher / process orchestration
- FastAPI server
- 10 saniyelik engine cycle
- MT5 bridge ve broker entegrasyonu
- SQLite persistence
- WebSocket event akisi
- Electron/React desktop UI

Bu yapi nedeniyle dogru agir stres testi su 5 ekseni birlikte ele almalidir:

1. **Katman stresi**
2. **Katmanlar arasi iletisim stresi**
3. **Failure-mode / chaos stresi**
4. **Uzun sureli soak testi**
5. **Kapasite ve teknoloji yeterlilik degerlendirmesi**

Bu planin hedefi sadece “uygulama cok istek tasiyor mu” sorusuna cevap vermek degildir. Asil hedef su sorulari yanitlamaktir:

- Yuk altinda dogru karar vermeye devam ediyor mu?
- Risk ve kill-switch mekanizmalari gecikiyor mu?
- DB lock, event backlog veya UI drift olusuyor mu?
- MT5 yavasladiginda veya koptugunda sistem fail-safe kaliyor mu?
- SQLite, Python engine ve Electron/React bu sistemin isletim profiline yeterli mi?

---

## 2. Uygulamanin Stres Testi Acisindan Ozeti

Kod tabaninin okunmasindan cikan stres-test odakli mimari gercek:

### 2.1 Baslatma ve Surec Katmani

- `start_ustat.py` uygulamanin giris noktasi.
- Process management, loglama, port kontrolu, single-instance davranisi ve UI shell davranisi burada basliyor.
- Dosya hem canli launcher davranisi hem de tarihsel pywebview kalintilari tasiyor.

Stres acisindan anlamı:

- tekrarli startup/shutdown testleri gerekli
- stale process / port conflict / double launch testleri kritik
- readiness ile process ayaga kalkmasi karistirilmamali

### 2.2 API Katmani

- `api/server.py` FastAPI lifespan icinde Engine’i olusturuyor.
- Engine thread olarak background’da baslatiliyor.
- Watchdog ile engine restart denemesi var.
- Router yapisi zengin: status, health, notifications, settings, trades, hybrid, manual, live websocket.

Stres acisindan anlamı:

- API tek basina degil, engine ile ayni ortamda yuk altinda olculmeli
- watchdog restart davranisi ayrica test edilmeli
- polling + websocket + settings yazmalari birlikte zorlanmali

### 2.3 Engine Katmani

- `engine/main.py` 10 saniyelik cycle ile calisiyor.
- Sira kabaca: heartbeat, data update, closure check, BABA, risk check, Top5, OGUL, H-Engine, ManuelMotor, USTAT, loglama.
- Motorlar arasi dogrudan referans var.
- HealthCollector cycle ve order metrikleri topluyor.

Stres acisindan anlamı:

- cycle budget en kritik KPI
- yuk altinda sadece hiz degil, karar dogrulugu da izlenmeli
- lock contention ve cross-motor state etkisi olasi darboğaz

### 2.4 MT5 Bridge

- `_safe_call` timeout ve circuit breaker iceriyor.
- read/write lock yapisi var.
- reconnect, symbol resolve, order send, modify, close, history sync ayni buyuk modulde.

Stres acisindan anlamı:

- broker gecikmesi ve kesintisi simule edilmeli
- write path ve read path ayrik zorlanmali
- timeout/retry/circuit-breaker davranisi olculmeli

### 2.5 Database Katmani

- Tek `sqlite3.Connection`, `check_same_thread=False`, `threading.Lock`
- WAL modu acik
- journal_mode=WAL, synchronous=NORMAL, cache ve mmap tuning yapilmis
- events, notifications, trades, bars, risk_snapshots, hybrid tablolar mevcut

Stres acisindan anlamı:

- SQLite iyi ayarlanmis, ama yine de tek baglanti + lock modeli nedeniyle write contention kritik
- retention/backup/canli yazim bir arada zorlanmali
- DB yeterliligi fikirle degil olcumle belirlenmeli

### 2.6 Event ve UI Katmani

- `engine/event_bus.py` pending queue limitli (`_MAX_PENDING = 500`)
- `api/routes/live.py` 2 sn push loop ve 1 sn event drain kullanıyor
- `desktop/src/services/api.js` fallback odakli, yani UI hata halinde sahte-guvenli veri uretebiliyor

Stres acisindan anlamı:

- event burst altinda drop/backpressure izlenmeli
- UI “yanlis ama stabil” veri gosteriyor mu kontrol edilmeli
- websocket + polling birlikte test edilmeli

---

## 3. Neden Tek Bir Stres Testi Yetmez

USTAT’ta stres 4 farkli sekilde ortaya cikabilir:

- throughput stresi
- latency/jitter stresi
- state drift stresi
- failure-recovery stresi

Ornek:

- API yavaslar ama yanlis veri donmezse bu bir performans sorunudur.
- API hizli kalir ama `status`, `notifications`, `positions` gercekten koparsa bu dogruluk sorunudur.
- Engine cycle gecikirse ama BABA gec calisiyorsa bu finansal risk sorunudur.
- MT5 timeout oldugunda sistem kapanmaz ama emir kapisi acik kalirsa bu fail-safe sorunudur.

Bu nedenle USTAT icin agir stres testi su sekilde olmalidir:

- **component stress**
- **integration stress**
- **system stress**
- **chaos stress**
- **soak test**

---

## 4. Ana Test Hedefleri

Agir stres programi boyunca asagidaki 10 ana soruya cevap aranmalidir:

1. Engine cycle hedef butceyi asiyor mu?
2. Risk motoru yuk altinda gecikiyor mu?
3. MT5 timeout/kopma halinde sistem fail-safe kaliyor mu?
4. API ve WebSocket yuk altinda gercegi dogru raporluyor mu?
5. Event backlog olusuyor mu, drop yasaniyor mu?
6. SQLite lock, write starvation veya query bozulmasi yasiyor mu?
7. UI uzun sureli akista memory veya render baskisiyla bozuluyor mu?
8. Restart/recovery sonrasi state kaybi veya state drift var mi?
9. Teknoloji yigini beklenen yuk profilini tasiyabiliyor mu?
10. Sistemin ilk saturasyon noktasi neresi?

---

## 5. Test Fazlari

## 5.1 Faz A - Baseline Profil

Amaç:

- Sistemin normal kosullardaki temel performansini cikarmak

Olculecekler:

- startup suresi
- API p50/p95
- cycle average/max
- MT5 ping
- order send average
- DB dosya boyutu
- memory ve CPU
- websocket client sayisi

Bu faz olmadan agir stresin yorumu saglikli olmaz.

## 5.2 Faz B - Katman Bazli Stres

Her katman tek basina zorlanir:

- launcher/lifecycle
- API
- engine
- MT5 bridge
- DB
- websocket/event
- UI render

Amaç:

- darboğazı izole etmek

## 5.3 Faz C - Entegrasyon Stresi

Katmanlar ikili ve uclu kombinasyonlarda zorlanir:

- API + engine
- engine + DB
- engine + MT5
- event bus + websocket + UI
- settings + DB + UI

Amaç:

- tekil testte gorunmeyen sozlesme bozulmalarini bulmak

## 5.4 Faz D - Tam Sistem Stresi

Tum sistem, gercege yakin isletim profiliyle birlikte yuklenir:

- API polling
- websocket push
- engine cycle
- event uretimi
- DB yazimlari
- MT5 read/write
- UI acik ekranlar

Amaç:

- sistemin entegre davranisini olcmek

## 5.5 Faz E - Chaos ve Failure Injection

Yuk altindayken kontrollu arizalar enjekte edilir:

- MT5 disconnect
- MT5 slow response
- DB lock
- stale process
- websocket drop
- bozuk payload
- config/read failure

Amaç:

- bozuk kosulda fail-safe davranisi dogrulamak

## 5.6 Faz F - Soak Test

Uzun sureli test:

- 6 saat
- 12 saat
- 24 saat

Amaç:

- memory leak
- queue drift
- WAL buyumesi
- stale state
- yavas bozunma

---

## 6. Katman Bazli Test Tasarimi

## 6.1 Launcher / Lifecycle Testleri

### Hedef

- startup/shutdown dayanıkliligi
- single-instance guvencesi
- stale process temizligi
- readiness semantigi

### Senaryolar

- 50 ardışık startup/shutdown
- stale PID ile startup
- port 8000 doluyken startup
- MT5 yokken startup
- API hazir, engine gec hazir senaryosu
- duplicate launch denemesi

### Basari Kriterleri

- zombie/orphan process kalmamalı
- ikinci instance guvenli reddedilmeli veya eskiyi temizlemeli
- startup durumu net siniflanmali
- shutdown sonrası port serbest kalmali

## 6.2 API Stresi

### Hedef

- yuk altinda latency, hata oranı ve veri dogrulugu

### Baskı Noktalari

- `/api/status`
- `/api/health`
- `/api/risk`
- `/api/positions`
- `/api/notifications`
- `/api/settings/*`

### Yuk Profili

- 10, 50, 100, 250 eşzamanlı istek
- polling burst + ayar yazma + bildirim okuma birlikte
- saglik endpoint’ine sık çağrı

### Basari Kriterleri

- p95 latency kabul edilebilir sınırlarda
- 5xx oranı dusuk
- timeout patlamasi yok
- schema drift yok
- fallback veri gerçeği maskelemiyor

## 6.3 Engine Cycle Stresi

### Hedef

- 10 saniyelik cycle’in yuk altinda ne kadar sarktığını görmek

### Baskı Parametreleri

- izlenen sembol sayisi
- veri cekme hacmi
- top5 / score hesap yoğunluğu
- USTAT analiz maliyeti
- event üretim hizi
- DB log yazim hacmi

### Olculecekler

- cycle avg/p95/max
- overrun count
- step bazlı timing
- consecutive slow cycles
- karar verme gecikmesi

### Basari Kriterleri

- cycle, hedef araligin kontrolsuz disina cikmamali
- BABA ve risk step’i tail latency altinda aşırı büyümemeli
- backlog birikmemeli

## 6.4 MT5 Bridge Stresi

### Hedef

- broker katmani yavasladiginda veya hata verdiginde koruma davranisini olcmek

### Senaryolar

- order send burst
- modify burst
- close/open race
- timeout
- intermittent failure
- reconnect dalgasi
- circuit breaker threshold testi

### Basari Kriterleri

- circuit breaker beklenen anda acilmali
- timeout sonrasi sistem durumu tutarlı kalmali
- duplicate order veya korumasiz pozisyon olmamali
- trade_allowed / connection state dogru raporlanmali

## 6.5 Event Bus / WebSocket / UI Testleri

### Hedef

- gercek zamanli akis semantik ve performans olarak saglam mi

### Senaryolar

- saniyede yuksek sayıda event uretimi
- notification burst
- farklı event tiplerinin karışık akisi
- queue limit asimi
- 1, 5, 20 websocket client
- dashboard + monitor ekranı birlikte acik

### Olculecekler

- event drop
- backlog boyutu
- ws disconnect
- render gecikmesi
- unread drift
- notification ordering

### Basari Kriterleri

- `_MAX_PENDING=500` sinirinda sistem kontrollu davranmali
- UI crash etmemeli
- kritik eventler kaybolmamali ya da alarm uretmeli

## 6.6 Database / Persistence Testleri

### Hedef

- SQLite’ın bu uygulama için yeterli olup olmadigini olcmek

### Senaryolar

- event insert burst
- notification insert/read burst
- trades write + positions/risk read ayni anda
- retention/backup esnasinda canli yazim
- uzun sureli WAL buyumesi
- restart sonrasi consistency

### Olculecekler

- write latency
- read latency
- lock bekleme suresi
- `database is locked` frekansi
- WAL dosya boyutu
- query p95
- DB buyume eğrisi

### Basari Kriterleri

- lock contention kontrollu olmalı
- veri kaybi ve duplicate yazim olmamali
- retention canlı kullanimi bozmamali
- restore sonrasi state tutarlı kalmali

---

## 7. Katmanlar Arasi Iletisimi Nasil Test Ederdim

USTAT’ta katmanlar arasi iletisim asagidaki hatlar uzerinden test edilmelidir:

- Launcher -> API
- API -> Engine
- Engine -> MT5Bridge
- Engine -> Database
- Engine -> EventBus
- EventBus -> WebSocket
- WebSocket -> UI
- UI -> API
- API -> DB

Her hat icin 5 soru sorulur:

1. Veri formati dogru mu?
2. Eksik alan olursa ne oluyor?
3. Gecikme olursa ne oluyor?
4. Duplicate veri gelirse ne oluyor?
5. Sira bozulursa ne oluyor?

Kullanilacak test turleri:

- contract test
- malformed payload test
- out-of-order event test
- timeout/retry test
- duplicate message test
- stale cache test

### Kritik Iletisim Testleri

#### API -> Engine

- `/status`, `/risk`, `/health` gercek engine durumunu dogru okuyabiliyor mu?
- engine restart sonrasinda route’lar stale referans taşıyor mu?

#### Engine -> EventBus -> UI

- notification, status ve position event’leri yük altinda UI’da ayni semantik ile görünüyor mu?
- event queue doldugunda hangi olaylar dusuyor?

#### UI -> API -> DB

- notification read / read-all
- settings save/load
- manual trade ve hybrid route’lari

Burada asıl risk:

- “işlem basarili” gorunur ama persist olmaz
- “ayar kaydedildi” gorunur ama restart sonrasi kaybolur

---

## 8. Kac Kombinasyonlu Olurdu

Bu program tam kartesyen carpimla kosulmaz. Cunku kombinasyon uzayi cok buyuktur.

### Parametre Uzayi

- startup mode: `normal`, `degraded_mt5_missing`, `recovery`
- api load: `low`, `medium`, `high`, `extreme`
- engine load: `low`, `medium`, `high`
- db pressure: `low`, `high`
- event rate: `low`, `high`
- mt5 state: `healthy`, `slow`, `intermittent_fail`, `disconnected`
- ui state: `closed`, `dashboard_open`, `monitor_heavy`
- duration: `short`, `soak`

Tam carpim:

`3 x 4 x 3 x 2 x 2 x 4 x 3 x 2 = 3456 kombinasyon`

Bu pratik degildir. Endustride risk bazli ornekleme kullanilir.

### Onerilen Pratik Matris

- 12 temel baseline/load senaryosu
- 18 yuksek riskli entegrasyon kombinasyonu
- 8 chaos/failure senaryosu
- 6 soak senaryosu

Toplam:

- **44 ana stres senaryosu**

Bu seviye, profesyonel ama uygulanabilir bir derinliktir.

---

## 9. Kac Soru Yoneltirdim

Bu stres programi boyunca yaklasik **60-70 cekirdek soru** ile ilerlerdim. Sorular teknik ekip icinde su gruplarda toplanir:

### Startup ve Operasyon

- Sistem ne zaman gercekten “ready” sayilir?
- MT5 yokken ne kadar işlevsel kalabilir?
- duplicate launch guvenli mi?
- watchdog restart dogru mu?

### Engine ve Risk

- Cycle hedef butce nedir?
- Yuk artinca BABA gecikiyor mu?
- kill-switch yuk altinda gec mi tetikleniyor?

### Order ve Protection

- SL/TP kurulamiyorsa ne oluyor?
- timeout ve retry duplicate order uretiyor mu?
- circuit breaker gercekten emir kapisini etkiliyor mu?

### API/UI

- UI yanlis ama stabil fallback veri mi gosteriyor?
- websocket event’leri kayiyor mu?
- notification semantigi bozuluyor mu?

### Database

- SQLite lock contention ne zaman kritik hale geliyor?
- retention canli sistemi etkiliyor mu?
- WAL buyumesi kabul edilebilir mi?

### Teknoloji Yigini

- Python tek surec modeli bu profile yetiyor mu?
- FastAPI, polling + websocket karisik yukte yeterli mi?
- Electron/React uzun sureli veri akisinda akici kalıyor mu?
- SQLite bu yazma/okuma modelini saglikli taşıyor mu?

---

## 10. Teknoloji Yiginin Yeterli Olup Olmadigini Nasil Test Ederdim

Teknoloji yeterliligi, “bize tanidik geliyor mu” diye degil, saturasyon davranisi uzerinden olculur.

## 10.1 Python Engine Yeterliligi

Olculecekler:

- cycle latency
- CPU kullanimi
- lock contention
- step bazli tail latency
- yuk arttikca jitter

Karar:

- Eger cycle ve karar gecikmeleri kontrol altindaysa Python yeterlidir.
- Eger tek surecli model tail latency’yi kabul edilemez hale getiriyorsa ayristirma gerekir.

## 10.2 FastAPI Yeterliligi

Olculecekler:

- polling + websocket birlikte p95
- engine aktifken route latency
- status/health endpoint stabilitesi

Karar:

- Gozlem ve ayar yuzeyi icin yeterli olabilir.
- Eger UI canli veri yukunde API thread/loop davranisi bozuluyorsa ayrıştırma gerekir.

## 10.3 Electron/React Yeterliligi

Olculecekler:

- memory growth
- render latency
- uzun sureli event akisi
- monitor ekraninda responsiveness

Karar:

- Eger 12-24 saatlik kullanımda memory leak ve akicilik bozulmasi yoksa yeterlidir.
- Event storm altinda UI takiliyorsa state yonetimi ya da push modelinin revizyonu gerekir.

## 10.4 SQLite Yeterliligi

Olculecekler:

- write throughput
- concurrent read/write latency
- lock frequency
- WAL growth
- backup/retention etkisi
- tablo buyudukce sorgu maliyeti

Karar:

- Tek kullanici, yerel persistence, orta yazma yoğunluğu icin yeterli olabilir.
- Ama yuksek yazma + uzun sureli olay kaydi + yogun sorgu + canlı polling bir araya geldiginde sınıra geliyorsa ya yazma modelini ya da storage katmanini degistirmek gerekir.

---

## 11. Veri Depolama Sisteminin Yeterliligini Nasil Test Ederdim

Veri depolama yeterliligi 4 ayri boyutta test edilmelidir:

## 11.1 Performans

- insert latency
- query latency
- batch ve tekil yazim farki
- retention / cleanup maliyeti

## 11.2 Buyume

- 1 gun veri
- 1 hafta veri
- 1 ay simulasyonu

Olculecek:

- tablo boyutlari
- indeks etkinligi
- sorgu p95 degisimi

## 11.3 Dayaniklilik

- ani kapanma
- restart sonrasi integrity
- WAL/SHM tutarliligi
- backup/restore guvenilirligi

## 11.4 Semantik Dogruluk

- unread sayisi global dogru mu?
- event kayitlari eksiksiz mi?
- duplicate trade kaydi var mi?
- app_state restore tutarli mi?

Basari kriteri:

- sadece hizli calismasi degil, dogru kaydetmesi ve dogru geri yuklemesi gerekir.

---

## 12. Onerilen 44 Senaryolu Test Paketi

### Grup 1 - Baseline ve Katman Testleri (12)

1. Temiz startup baseline
2. MT5 yok startup baseline
3. 50x startup/shutdown tekrar testi
4. API low concurrency
5. API high concurrency
6. Engine cycle low load
7. Engine cycle high load
8. Event bus high notification burst
9. WebSocket 5 client
10. WebSocket 20 client
11. DB write burst
12. DB read/write mix

### Grup 2 - Entegrasyon Senaryolari (18)

13. API polling + engine cycle
14. API polling + event push + UI dashboard
15. Engine + DB + notifications burst
16. Engine + MT5 slow reads
17. Engine + MT5 intermittent failures
18. MT5 reconnect while API polling
19. Notification read/write while websocket active
20. Settings save/load under API load
21. Hybrid positions + normal positions birlikte
22. Manual trade + OĞUL aktif senaryo
23. Health endpoint spam + engine cycle
24. status/risk/positions paralel okunma
25. event burst + UI monitor heavy
26. event burst + DB writes + websocket
27. backup sırasında canlı event/trade akisi
28. retention sırasında notifications/trades okunma
29. startup recovery + stale process + API load
30. watchdog restart + UI açık senaryo

### Grup 3 - Chaos ve Failure Senaryolari (8)

31. MT5 disconnect under load
32. MT5 timeout storm under load
33. DB locked under load
34. bozuk event payload
35. websocket client flap
36. duplicate launch under load
37. config read anomaly
38. order send failure + fallback protection

### Grup 4 - Soak Senaryolari (6)

39. 6 saat orta yuk
40. 12 saat orta yuk + websocket
41. 12 saat event burst aralikli
42. 24 saat DB growth soak
43. 24 saat dashboard open soak
44. 24 saat degraded mode soak

---

## 13. Metrikler ve Basari Esikleri

Bu testlerden anlamli sonuc almak icin su metrikler toplanmalidir:

### Sistem

- CPU %
- RAM kullanimi
- handle/process count
- startup time
- shutdown time

### API

- p50/p95/p99 latency
- 4xx/5xx oranı
- timeout oranı

### Engine

- avg cycle ms
- max cycle ms
- overrun count
- consecutive slow cycles
- step bazli timing

### MT5

- avg ping
- disconnect count
- reconnect success ratio
- order avg ms
- reject/timeout count
- circuit breaker activation count

### Event/UI

- pending queue boyutu
- dropped event sayisi
- ws disconnect sayisi
- render gecikmesi
- unread drift

### DB

- read/write latency
- lock bekleme
- WAL boyutu
- db file growth
- backup suresi
- retention suresi

### Basari Esikleri

Bu esikler proje ve operasyon toleransina gore sonradan netlestirilmelidir; ancak ilk calismada asagidaki turden sınırlar kullanilabilir:

- cycle overrun istikrarlı hale gelmemeli
- API timeout’lari patlamamali
- DB locked hatasi sureklilik kazanmamali
- UI memory kullanimi soak boyunca kontrolsuz artmamali
- kritik event kaybi yasanmamali
- fail-safe mekanizmalari bozuk durumda permissive olmamali

---

## 14. Testi Hangi Sirayla Kosardim

Sira cok onemlidir. Ben su akisla giderdim:

1. Baseline
2. Katman bazli testler
3. Entegrasyon testleri
4. Tam sistem yuk testi
5. Chaos/failure under load
6. Soak
7. Sonuç analizi
8. Kapasite karari

Direkt tum sistemi agir yuke sokmak, semptom verir ama kok neden cikarmaz.

---

## 15. Nihai Karar Cercevesi

Bu test programi sonunda her katman icin su karar verilir:

### Yeterli

- Yuk profilini kabul edilebilir latency ve hata oraniyla tasiyor

### Sinirda

- Dogru calisiyor ama tail latency, lock contention veya memory growth kritik seviyeye yaklasiyor

### Yetersiz

- Yanlis veri, fail-safe ihlali, backlog birikimi, lock firtinasi veya crash uretiyor

Bu karar asagidaki alanlarda ayrica verilmelidir:

- Python engine modeli
- FastAPI + background thread modeli
- EventBus + WS modeli
- Electron/React desktop modeli
- SQLite persistence modeli

---

## 16. USTAT Icin Beklenen En Kritik Riskler

Bu yapiyi okuyunca stres testi acisindan en muhtemel risk alanlari sunlar:

1. **Engine cycle tail latency**
2. **MT5 timeout/reconnect dalgasi**
3. **SQLite write contention**
4. **Event bus backpressure ve drop**
5. **UI’nin fallback verilerle gercegi maskelemesi**
6. **Cross-motor coupling nedeniyle yuk altinda yan etki riski**
7. **Uzun sureli calismada memory/WAL buyumesi**

Bu nedenle stres programinda ilk odak buralar olmalidir.

---

## 17. Sonuc

USTAT icin agir stres testi su sekilde tasarlanmalidir:

- once katmanlari tek tek zorla
- sonra katmanlar arasi iletisimi zorla
- sonra tum sistemi birlikte zorla
- sonra ariza enjekte et
- sonra uzun sureli soak ile yavas bozulmayi olc
- en sonda kapasite ve teknoloji yeterliligi karari ver

Bu yapi icin tek bir “load test sonucu” anlamsizdir. Gerekli olan sey, **katmanli kapasite ve dayaniklilik denetimi**dir.

Bu dokuman o denetimin temel planidir.
