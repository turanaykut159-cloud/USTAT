# USTAT Derin Inceleme Metodolojisi

**Tarih:** 2026-04-13  
**Amac:** USTAT gibi cok katmanli, risk duyarli, desktop + API + engine + harici servis bagimli bir uygulamayi profesyonel seviyede derinlemesine incelemek icin uygulanabilir bir metodoloji sunmak.  
**Kapsam:** `start_ustat.py`, `api/`, `engine/`, `desktop/`, `database/`, `config/`, `tests/`, `docs/`, operasyonel loglar, baslatma davranisi, hata senaryolari, veri butunlugu ve yazilim muhendisligi kalitesi.

---

## 1. Bu Dokuman Ne Icin Var

Bu dokumanin amaci sadece "kod inceleme" yapmak degildir. Hedef, sistemin su sorulara gercek cevap verip vermedigini anlamaktir:

- Sistem dogru calisiyor mu?
- Sistem bozuldugunda guvenli davraniyor mu?
- Katmanlar birbirleriyle tutarli mi?
- UI, API, engine ve veritabani ayni gercegi mi anlatiyor?
- Testler kritik akisleri gercekten koruyor mu?
- Bu kod tabani korkmadan degistirilebilir mi?

USTAT benzeri sistemlerde tek bir hata tipi yoktur. Problemler su sekillerde ortaya cikar:

- startup crash
- sessiz mantik hatasi
- yanlis durum raporlamasi
- bozuk API/UI sozlesmesi
- risk motorunun gec devreye girmesi
- SL/TP veya emir yasam dongusunde korumasiz durum
- state drift
- testlerin sahte guven vermesi
- dokumantasyon ile gercek davranisin ayrismasi

Bu yuzden derin inceleme, sadece dosya okumaktan degil; sistem haritalama, runtime dogrulama, failure-mode analizi, test guvenilirligi denetimi ve teknik borc envanterinden olusmalidir.

---

## 2. Uygulama Sinifi ve Inceleme Yaklasimi

USTAT su sinifa girer:

- desktop shell + web UI
- yerel process orchestration
- API sunucusu
- surekli calisan engine dongusu
- harici broker/terminal entegrasyonu
- durumlu trade/risk yonetimi
- SQLite tabanli yerel veri saklama
- anlik olay ve durum gosterimi

Bu tip sistemler icin dogru inceleme yaklasimi sudur:

1. Once mimari gercegi cikarilir.
2. Sonra calisma zamani davranisi dogrulanir.
3. Sonra is kurallari ve sozlesmeler kontrol edilir.
4. Sonra hata senaryolari zorlanir.
5. Sonra testlerin bunu ne kadar korudugu olculur.
6. Son olarak refactor ve duzeltme plani risk bazli cikarilir.

Bu siralama onemlidir. Cunku buyuk sistemlerde "kod guzel mi?" sorusu, "sistem kriz aninda ne yapiyor?" sorusundan sonra gelir.

---

## 3. Endustride Bu Is Nasil Yapilir

Profesyonel ekipler bu tur bir incelemeyi genelde asagidaki calisma basliklariyla yapar:

- Architecture Review
- Runtime Validation
- Failure Mode Analysis
- Contract Audit
- Test Effectiveness Review
- Operational Readiness Review
- Technical Debt Assessment

Olgun ekiplerde surec genelde su sekildedir:

1. Sistem sinirlari ve sahiplikler cikarilir.
2. Kritik akislar listelenir.
3. Gozlemlenebilirlik yetersizse once o iyilestirilir.
4. Kaynak kod ve runtime birlikte incelenir.
5. Kontrollu hata senaryolari uygulanir.
6. Bulgular siddet, etki ve duzeltme maliyetine gore siniflanir.
7. Hemen duzeltilecekler ile yapisal refactorlar ayrilir.

Bu noktada temel endustri ilkeleri sunlardir:

- "Works on my machine" kabul edilmez.
- "Test var" tek basina yeterli sayilmaz.
- "Exception atmiyor" dogruluk kaniti degildir.
- "Health endpoint yesil" sistemin is yapmaya hazir oldugu anlamina gelmez.
- "Kod buyumus" normaldir; tehlikeli olan buyumeyi yonetememektir.

---

## 4. Derin Inceleme Icin Ana Ilkeler

Inceleme boyunca su ilkeler korunmalidir:

### 4.1 Tek Gercek Kaynagi

Ayni bilginin birden cok yerde tutuldugu her yer risklidir. Asagidaki alanlarda "source of truth" aranmalidir:

- version
- config
- notification state
- trade state
- engine status
- kill-switch durumu
- user settings

### 4.2 State Merkezli Dusunme

Bu tip sistemlerde en tehlikeli bug'lar exception degil, yanlis state'tir. Bu nedenle su sorular sorulmalidir:

- Bu bilgi memory'de mi, DB'de mi, UI'da mi saklaniyor?
- Restart sonrasi dogru restore oluyor mu?
- State gecisleri belirli mi, yoksa daginik mi?
- Bir state'in birden cok sahibi var mi?

### 4.3 Failure First

Normal akis degil, bozuk akis once incelenmelidir:

- MT5 yoksa ne oluyor?
- Engine var ama API yoksa ne oluyor?
- API var ama UI baglanamiyorsa ne oluyor?
- Notification payload bozulursa ne oluyor?
- Veritabani lock olursa ne oluyor?
- SL/TP uygulanamazsa ne oluyor?

### 4.4 Sozlesme Disiplini

Katmanlar arasi bag su soruyla denetlenmelidir:

"Bu katmani degistirirsem, baska hangi katman sessizce bozulur?"

### 4.5 Kanit Temelli Degerlendirme

Her bulgu mumkun oldugunca su ucleme ile yazilmalidir:

- kanit
- neden-sonuc
- cozum yonu

---

## 5. USTAT Ozelinde Derin Inceleme Hedefleri

USTAT icin derin inceleme, asagidaki 9 eksende yapilmalidir:

1. Baslatma ve lifecycle guvenilirligi
2. Engine dongusu dogrulugu
3. Risk ve kill-switch davranisi
4. Emir yasam dongusu ve koruma mantigi
5. API/UI/event sozlesme tutarliligi
6. Veri butunlugu ve persistence
7. Test guvenilirligi ve kapsami
8. Dokumantasyon ve versiyon drifti
9. Teknik borc ve refactor hazirligi

---

## 6. Calisma Fazlari

Bu inceleme bir oturumda yapilacak bir is degildir. Fazlara bolunmelidir.

## 6.1 Faz 0 - Hazirlik ve Scope Sabitleme

Amac:

- Inceleme sinirlarini netlestirmek
- Hangi ortamda neyin dogrulanacagini belirlemek
- "Okuma", "runtime", "duzeltme" islerini ayirmak

Yapilacaklar:

- repo envanteri cikar
- giris noktalari belirle
- kritik dosya listesi cikar
- runtime bagimliliklari listele
- mevcut raporlari indeksle

Beklenen cikti:

- sistem kapsam haritasi
- inceleme backlog'u
- kritik akis listesi

## 6.2 Faz 1 - Mimari Envanter

Amac:

- Gercek mimariyi cikarmak

Yontem:

- `start_ustat.py`
- `api/server.py`
- `engine/main.py`
- `desktop/main.js`, `desktop/preload.js`, `desktop/src/services/api.js`
- `config/default.json`

incelenir ve sunlar cikarilir:

- process haritasi
- state sahipligi
- veri akis yonleri
- lifecycle sirasi
- dis bagimliliklar

Beklenen cikti:

- tek sayfada sistem diyagrami
- startup sequence
- shutdown sequence
- dependency map

## 6.3 Faz 2 - Sozlesme Envanteri

Amac:

- UI, API, engine ve DB arasindaki tum kritik sozlesmeleri cikarmak

Kontrol listesi:

- API response schema
- request validation
- WebSocket/event payload yapisi
- settings persistence
- version source
- engine public API
- private alan sizintilari

Beklenen cikti:

- contract matrix
- kirilgan alanlar listesi
- "private alana bagli route" raporu

## 6.4 Faz 3 - Runtime Dogrulama

Amac:

- Kodun teorik degil gercek davranisini anlamak

Kontrol listesi:

- temiz startup
- tekrar startup
- stale process sonrasi startup
- MT5 bagli startup
- MT5 bagli degil startup
- API readiness
- UI readiness
- graceful shutdown
- crash recovery

Toplanacak veriler:

- startup loglari
- health/status endpoint ciktilari
- process listesi
- port dinleme durumu
- zaman damgali olay sirasi

Beklenen cikti:

- startup truth table
- readiness state modeli
- shutdown davranis ozeti

## 6.5 Faz 4 - Failure Mode Analizi

Amac:

- Sistem bozuldugunda nasil davrandigini test etmek

Temel senaryolar:

- MT5 process yok
- MT5 initialize basarisiz
- DB lock / WAL sorunu
- config bozuk
- event bus bozuk payload
- API route exception
- notification tablosu anomali
- SL/TP set edilemiyor
- position ticket bulunamiyor
- duplicate instance

Her senaryo icin su yazilir:

- tetikleyici
- beklenen davranis
- mevcut davranis
- risk seviyesi
- cozum onerisi

Beklenen cikti:

- failure matrix
- fail-safe uyum raporu

## 6.6 Faz 5 - Is Kurali ve Mantik Dogrulama

Amac:

- Kod exception atmadan yanlis karar uretiyor mu, bunu bulmak

Bu fazda ozellikle sunlar incelenir:

- kill-switch seviyeleri
- drawdown mantigi
- cooldown mantigi
- lot hesaplama
- SL/TP zorunlulugu
- hybrid transfer mantigi
- orphan cleanup
- manual trade izleme
- notification semantigi
- status endpoint semantigi

Yontem:

- kod okuma
- kritik fonksiyon izi
- test senaryosu cikarimi
- state gecis tablosu

Beklenen cikti:

- mantik celiskileri listesi
- sessiz yanlis calisma riskleri

## 6.7 Faz 6 - Veri Butunlugu ve Persistence Denetimi

Amac:

- Memory, DB ve UI ayni gercegi tasiyor mu?

Kontrol alanlari:

- SQLite tablolari
- WAL/SHM davranişi
- trade kayitlari
- notification kayitlari
- config kayitlari
- baseline/state persist alanlari
- startup restore akisi

Sorulacak sorular:

- restart sonrasi ne kayboluyor?
- duplicate kayit riski var mi?
- retention ile UI beklentisi uyumlu mu?
- sayisal alanlar tek kaynakli mi?

Beklenen cikti:

- veri butunlugu risk raporu
- restore/persist akisi

## 6.8 Faz 7 - Test Stratejisi Denetimi

Amac:

- Testlerin gercekten kritik akisleri koruyup korumadigini anlamak

Kontrol listesi:

- pytest entrypoint dogru mu
- testler dogru yerden toplanıyor mu
- unit/integration/critical smoke ayrimi var mi
- statik contract testleri neyi koruyor
- runtime failure senaryolari testlenmis mi
- flaky test var mi
- hangi risk hic testlenmiyor

Beklenen cikti:

- test coverage matrix
- guvenilirlik puani
- eksik test backlog'u

## 6.9 Faz 8 - Teknik Borc ve Refactor Hazirligi

Amac:

- Sistemi bozmadan nasil toparlariz, bunu planlamak

Bakilacak alanlar:

- buyuk dosyalar
- tek sorumluluk ihlalleri
- dogrudan obje baglama
- private alan sizintisi
- olgunlasmamis abstraction
- kopya mantik
- obsolete docs
- dead field / dead code

Beklenen cikti:

- moduller arasi bagimlilik haritasi
- refactor sirasi
- yuksek riskli tasima alanlari

---

## 7. Incelenecek Katmanlar ve Sorular

## 7.1 Launcher ve Baslatma Katmani

Sorular:

- Tek giris noktasi gercekten tek mi?
- Singleton korumasi guvenilir mi?
- Startup state'leri tanimli mi?
- Readiness ile process ayaga kalkmasi birbirinden ayriliyor mu?
- Degraded mode resmi olarak modellenmis mi?
- Eski mimari kalintilari davranisi etkiliyor mu?

Kontrol nesneleri:

- `start_ustat.py`
- process guard
- lifecycle guard
- startup loglari

## 7.2 API Katmani

Sorular:

- Route'lar private alanlara bagimli mi?
- Health ve status endpoint'leri gercegi mi gosteriyor?
- Fail-safe default'lar dogru mu?
- Version, settings, unread_count gibi alanlar tek anlamli mi?

Kontrol nesneleri:

- `api/server.py`
- `api/routes/`
- response modelleri

## 7.3 Engine Katmani

Sorular:

- Cycle sirasi net mi?
- Motorlar arasinda gizli coupling var mi?
- Risk motoru gercekten once mi calisiyor?
- Trade emir akisi korumali mi?
- State mutation noktalarinin sahipligi net mi?

Kontrol nesneleri:

- `engine/main.py`
- `engine/baba.py`
- `engine/ogul.py`
- `engine/h_engine.py`
- `engine/ustat.py`
- `engine/manuel_motor.py`

## 7.4 Broker ve Harici Entegrasyon

Sorular:

- MT5 baglantisi fail-safe mi?
- initialize / login / reconnect akislari guvenli mi?
- circuit breaker davranisi dogru mu?
- harici servis timeout'lari cycle'i blokluyor mu?

Kontrol nesneleri:

- `engine/mt5_bridge.py`
- `engine/news_bridge.py`
- `health_check.py`

## 7.5 Desktop/UI Katmani

Sorular:

- UI kontrolu var ama backend destegi yok mu?
- Settings gercekten kalici mi?
- Notification, status, TopBar, monitor kartlari ayni gercegi mi gosteriyor?
- preload/main/frontend API surface tutarli mi?

Kontrol nesneleri:

- `desktop/main.js`
- `desktop/preload.js`
- `desktop/src/components/`
- `desktop/src/services/api.js`

## 7.6 Data ve Persistence

Sorular:

- Trade ve notification tablolari semantik olarak dogru mu?
- Retention gercek kullanimla uyumlu mu?
- Baseline, PnL, unread, cycle time gibi metrikler guvenilir mi?

Kontrol nesneleri:

- `engine/database.py`
- `database/*.db`
- config persistence mekanizmalari

---

## 8. Kullanilacak Yontemler

Bu tip bir denetimde tek yontem yetmez. Asagidaki yontemler birlikte kullanilmalidir.

### 8.1 Statik Kod Incelemesi

Ne icin:

- mimari
- coupling
- dead field
- private alan sizintisi
- sozlesme uyumsuzluklari

### 8.2 Akis Izleme

Belirli bir davranisin basa donup nereye kadar gittigini izlemek:

- startup
- order send
- SL/TP set
- kill-switch trigger
- notification emit
- settings save/load

### 8.3 Durum Makinesi Cikarma

Asagidaki konular icin state diagram uretilmelidir:

- engine lifecycle
- MT5 connection lifecycle
- order lifecycle
- notification read/unread
- hybrid transfer state

### 8.4 Sozlesme Haritalama

UI ne bekliyor, API ne donduruyor, engine ne tutuyor, bunlar tabloya dokulmelidir.

### 8.5 Failure Injection

Kontrollu sekilde bazi durumlar olusturulur:

- baglanti kes
- timeout simule et
- process yokmus gibi davran
- bogus payload ver
- lock yarat

### 8.6 Test Etkinligi Analizi

Var olan testler ile gercek riskler karsilastirilir.

### 8.7 Dokuman Drift Analizi

Asagidaki kaynaklar capraz okunur:

- anayasa / rehber
- config
- version alanlari
- kod yorumlari
- startup metinleri
- UI etiketleri

---

## 9. USTAT Icin Ornek Denetim Sorulari

Bu bolum, calisma sirasinda tekrar tekrar sorulacak cekirdek sorulari listeler.

### 9.1 Startup

- Uygulama temiz ortamda tam olarak hangi sirayla kalkiyor?
- Her katman ne zaman "hazir" sayiliyor?
- MT5 yokken sistem neden calisabilir veya neden calisamaz?
- Tek instance garantisi ne kadar saglam?

### 9.2 Engine ve Risk

- BABA her cycle'da karar veriyor mu?
- OĞUL risk kapisini delmeden emir verebilir mi?
- Kill-switch seviyeleri monoton mu?
- Geri donus veya reset kurallari net mi?

### 9.3 Order Protection

- SL/TP her zaman uygulanmak zorunda mi?
- Uygulanamazsa pozisyon kapaniyor mu?
- Virtual SL/TP ile native SL/TP ayrimi net mi?
- "Korumasiz acik pozisyon" teorik olarak mumkun mu?

### 9.4 UI/API Tutarliligi

- Buton var ama gercek fonksiyon yok mu?
- Bir alani UI localStorage'dan, backend DB'den mi okuyor?
- Dashboard ve status endpoint ayni gercegi mi gosteriyor?

### 9.5 Persistence

- Restart sonrasi hangi state geri geliyor?
- Bildirim okunmus/okunmamis sayilari global mi, pencere bazli mi?
- Baseline ve risk parametreleri restart'ta korunuyor mu?

### 9.6 Test

- `pytest` komutunu calistiran bir ekip uyesi gercekten dogru suite'i mi calistiriyor?
- Kritik akislari koruyan testler nasil tetikleniyor?
- Contract testler runtime bug'lari ne kadar yakaliyor?

---

## 10. Beklenen Ciktilar

Derin inceleme sonunda sadece tek bir rapor degil, bir cikti paketi uretilmelidir.

### 10.1 Mimari Ciktilar

- sistem diyagrami
- startup/shutdown sequence
- dependency map
- ownership map

### 10.2 Teknik Ciktilar

- bulgu raporu
- contract matrix
- failure matrix
- test coverage matrix
- technical debt map

### 10.3 Operasyonel Ciktilar

- readiness modeli
- health endpoint degerlendirmesi
- alarm ve log eksik listesi
- incident-ready checklist

### 10.4 Karar Ciktilari

- acil duzeltilecekler
- sonraki sprint maddeleri
- yapisal refactor backlog'u
- "dokunma" alanlari

---

## 11. Bulgular Nasil Siniflanmali

Profesyonel denetimlerde bulgular ayni sepete atilmaz. Su sekilde siniflanmalidir:

### 11.1 Oncelik

- `P0`: canli para riski, veri kaybi, startup crash, fail-safe ihlali
- `P1`: sessiz yanlis calisma, yanlis health/status, UI guven kaybi
- `P2`: teknik borc, dead field, drift, eksik soyutlama
- `P3`: kozmetik, dusuk etkili iyilestirme

### 11.2 Sinif

- `BUG`
- `SOZLESME`
- `BORC`
- `DRIFT`
- `SUREC`
- `GOZLEMLENEBILIRLIK`

### 11.3 Her Bulgu Formati

Her bulgu icin ideal format:

- baslik
- dosya ve satir
- kanit
- neden-sonuc
- etki
- cozum yonu
- oncelik
- sinif

---

## 12. Bu Projede Onerilen Denetim Programi

USTAT icin en gercekci denetim programi su olur:

### Asama 1 - Masa Basi Dogrulama

Sadece okuma ve envanter:

- repo haritasi
- startup akisi
- motorlar arasi baglar
- API/private alan sizintisi
- version drift
- test entrypoint analizi

Sure:

- 1-2 gun

### Asama 2 - Kontrollu Runtime Analizi

- startup denemeleri
- health/status gozlemi
- process/lifecycle kontrolu
- notification akis gozlemi
- persistence kontrolu

Sure:

- 1-2 gun

### Asama 3 - Failure Drill

- MT5 yok
- stale process
- DB lock
- API route failure
- event payload bozulmasi
- SL/TP basarisizligi

Sure:

- 1-2 gun

### Asama 4 - Test ve Guvence Denetimi

- pytest yolu
- mevcut kritik akişlar
- eksik test backlog'u
- contract test guclendirme

Sure:

- 1 gun

### Asama 5 - Remediation Plan

- hemen duzeltilecekler
- dusuk riskli duzeltmeler
- yapisal refactorlar
- belge guncelleme programi

Sure:

- yarim gun

---

## 13. Bu Tip Sistemlerde Genel Durum Kontrolu Nasil Yapilir

Genel durum kontrolu tek komutla olmaz. Su bes boyutta yapilir:

### 13.1 Mimari Durum

- katmanlar net mi
- bagimliliklar kontrol altinda mi
- giris noktasi sade mi

### 13.2 Operasyonel Durum

- startup guvenilir mi
- shutdown duzgun mu
- restart sonrasi tutarlilik var mi

### 13.3 Dogruluk Durumu

- business rule'lar tutarli mi
- UI/API farkli gercekler mi anlatıyor
- state sapmasi var mi

### 13.4 Guvence Durumu

- testler kritik akisleri koruyor mu
- loglar ve health sinyalleri yeterli mi

### 13.5 Surdurulebilirlik Durumu

- ekip korkmadan degisiklik yapabilir mi
- yeni ozellik eklemek pahali mi
- buyuk dosyalar ve coupling kontrolden cikti mi

---

## 14. Basari Kriterleri

Bir derin inceleme asagidaki durumda basarili sayilir:

- sistem mimarisi net olarak cizilebiliyorsa
- kritik akislar ispatli sekilde anlasildiysa
- en buyuk 10 risk acikca yazildiysa
- her kritik bulgu icin neden-sonuc kurulabildiyse
- backlog onceliklendirilmis ise
- duzeltme ile refactor birbirinden ayrildiysa
- ekip, "simdi ne yapacagimizi biliyoruz" diyorsa

---

## 15. USTAT Icin Nihai Oneri

USTAT gibi bir sistemde derin inceleme su dort ekseni birlikte ele almadan tamamlanmis sayilmaz:

1. **Kod gercegi**
2. **Runtime gercegi**
3. **Sozlesme gercegi**
4. **Operasyonel gercek**

Bu dort eksen ayni anda ele alinmazsa tipik hata olur:

- kod guzel gorunur ama runtime bozuk olur
- test var gorunur ama gercek suite kosmaz
- UI calisiyor gorunur ama backend ile ayni dili konusmaz
- risk motoru var gorunur ama failure-mode korumasi eksik kalir

Bu nedenle USTAT icin en dogru profesyonel yol:

- once sistem haritasi
- sonra runtime ve failure-mode analizi
- sonra contract ve state denetimi
- sonra test guvence calismasi
- en son refactor ve sadeleştirme programi

Bu yaklasim, hem bug avina hem de uzun vadeli muhendislik toparlamasina hizmet eder.

---

## 16. Sonuc

Derin inceleme, buyuk uygulamalarda "bir rapor yazma isi" degildir. Bu, sistemin ne oldugunu, nasil bozuldugunu, ne kadar guven verdigini ve nasil toparlanacagini anlama disiplinidir.

USTAT oyle bir esikte duruyor ki:

- sadece yeni ozellik eklemek artik yeterli degil
- sadece bug fix yapmak da yeterli degil
- artik gozlemlenebilir, dogrulanabilir ve refactor edilebilir bir zemine oturtulmasi gerekiyor

Bu dokumanin onerdiği metodoloji, tam olarak bu zemini kurmak icin tasarlanmistir.
