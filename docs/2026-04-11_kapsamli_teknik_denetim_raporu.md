# USTAT Kapsamli Teknik Denetim Raporu

Tarih: 2026-04-11
Inceleme tipi: Kod tabani, mimari, runtime akislari, API/UI sozlesmeleri, test altyapisi, operasyonel riskler
Kapsam: `engine/`, `api/`, `desktop/`, `config/`, `tests/`, secili `docs/`

## 1. Yonetici Ozeti

USTAT, canli islem risklerini ciddi sekilde dikkate alan, motor ayrimini bilincli kurmus, ancak hizli evrim nedeniyle katman sinirlari asinmis bir platformdur. Kod tabani "fikir olarak guclu, uygulama olarak yipranmis" bir noktadadir.Genel değerlendirmem şu: proje kötü değil, ama şu an tehlikeli biçimde karmaşıklaşmış.

Bence sistemin özü güçlü:

Doğru problem çözmeye çalışıyor
Risk tarafını ciddiye alıyor
Geliştirirken düşünülmüş
Sıradan bir “dağınık hobi kodu” değil
Ama bugünkü haliyle ana sorun şu:

Kod tabanı büyümüş
Kurallar çoğalmış
Katmanlar birbirine fazla bağlanmış
Gerçek davranış ile dokümantasyon/test/UI bazı yerlerde ayrışmış
Yani özetle:

Fikir seviyesi iyi
Mühendislik niyeti iyi
Operasyon bilinci iyi
Ama sürdürülebilirlik seviyesi düşmeye başlamış
Ben bunu şöyle sınıflandırırım:

Ürün fikri ve alan modellemesi: güçlü
Risk bilinci: güçlü
Kod organizasyonu: orta-alt
Test güvenilirliği: zayıf
Refactor edilebilirlik: riskli
Operasyonel doğruluk: orta, ama sessiz bozulma riski var
En dürüst teknik hüküm:
Bu proje “çalışıyor olabilir”, ama “güvenle geliştirilebilir” durumda değil.

Şu anda en büyük ihtiyaç yeni özellik değil:

sadeleştirme
sözleşme temizliği
test giriş kapısının düzeltilmesi
kritik akışların sağlamlaştırılması
Eğer doğru şekilde toparlanırsa güçlü bir sisteme dönüşebilir.
Eğer aynı tempoda üstüne ekleme yapılmaya devam edilirse bir süre sonra her düzeltme başka bir yeri bozan kırılgan bir sisteme dönüşür.

Tek cümlelik profesyonel hükmüm:
Bu repo, iyi düşünülmüş ama teknik borcu büyümüş bir canlı sistem; kurtarılması gayet mümkün, ama artık disiplinli yeniden düzenleme aşamasına girmiş.

Sistemin ana problemi strateji yoklugu degil; asagidaki dort alanda biriken kirilganliktir:

1. Baslatma ve runtime dayanıkliligi
2. API/UI veri sozlesmelerinin zamanla bozulmasi
3. Test guvencesinin gorundugu kadar guvenilir olmamasi
4. Motorlar arasinda artan capraz bagimlilik ve buyuk dosya baskisi

Sonuc: Sistem bugun halen is yapabilir, fakat "guvenle degistirilebilir" seviyede degildir. Her yeni duzeltme, sistemin baska bir yerinde sessiz bozulma riski tasir.

## 2. Mimari Ozet

Sistemin gorulen ana katmanlari:

- Baslatici: `start_ustat.py`
- API omurgasi: `api/server.py`
- Ana cycle koordinasyonu: `engine/main.py`
- Risk ve kill-switch: `engine/baba.py`
- Otomatik sinyal/emir/pozisyon yonetimi: `engine/ogul.py`
- Hibrit/PRIMNET yonetimi: `engine/h_engine.py`
- Analiz ve meta-geri bildirim: `engine/ustat.py`
- MT5 baglanti katmani: `engine/mt5_bridge.py`
- UI: `desktop/src/*`

Asil mimari niyet dogru kurulmus:

- BABA once calisir
- OĞUL riskin arkasindan gelir
- H-Engine ayrik bir motor olarak hibritleri yonetir
- USTAT gozlemci/analitik katmandir

Sorun, bu ayrimin zamanla dogrudan obje referanslariyla birbirine baglanmasidir.

## 3. Temel Guclu Yanlar

### 3.1 Risk onceligi gercekten tasarima islenmis

`engine/main.py` icindeki cycle sirasi BABA'yi once calistiriyor, sonra risk verdict uretiyor, sonra OĞUL'a izin veriyor. Bu canli islem sistemi icin dogru temel prensiptir.

### 3.2 MT5 katmaninda dayaniklilik dusunulmus

`engine/mt5_bridge.py` icinde:

- timeout korumasi
- circuit breaker
- yazma/islem kilitleri
- reconnect mantigi

gibi olgunluk isaretleri var.

### 3.3 Dokumantasyon ve oturum raporlama kulturunun guclu oldugu goruluyor

`docs/` altinda cok sayida oturum raporu ve karar kaydi var. Bu, karmasik bir sistemin nasil evrildigini izlemek acisindan ciddi deger uretiyor.

### 3.4 Kritik davranislari korumaya yonelik statik test mantigi dogru

`tests/critical_flows/test_static_contracts.py` ile kritik davranislarin farkinda olundugu ve "yanlis refactor" riskine karsi bariyer kuruldugu goruluyor.

## 4. Kritik Bulgular

## 4.1 P0 - Startup senaryosunda kosullu NameError

Dosya: `engine/main.py`

Kanit:

- `fail_names` yalnizca MT5 baglandi ve smoke test FAIL oldugunda tanimlaniyor.
- MT5 hic baglanamazsa else branch'te yine `fail_names` log/event icinde kullaniliyor.

Ilgili bolum:

- `engine/main.py` satir ~262-277

Teknik etki:

- "MT5 baglantisi yok ama engine kisitli modda acilsin" hedefi pratikte cokebilir.
- Sistem en ihtiyac duyulan degrade modda acilmak yerine startup hatasi verebilir.

Neden:

- Bir onceki refactor'da smoke-test branch'i ile no-MT5 branch'i semantik olarak birlestirilmis ama degisken kapsam guvencesi kurulmamış.

Cozum:

- `fail_names` icin branch oncesi default deger tanimlanmali.
- "MT5 yok" ve "MT5 var ama smoke fail" durumlari ayri event reason ile loglanmali.
- Bu akis icin unit/integration test eklenmeli.

## 4.2 P0 - Ana pytest giris kapisi bozuk

Dosya: `pytest.ini`

Kanit:

- `testpaths = USTAT DEPO/tests_aktif`
- Bu yol mevcut repo yapisinda yok.
- `pytest --collect-only` cagrisi archive ve eski worktree testlerini toplamaya basliyor.
- Koleksiyon `archive/USTAT_DEPO/test_trade.py` icindeki `sys.exit(0)` ile bozuluyor.

Teknik etki:

- Test sayisi yuksek gorunse de ana test kapisi guvenilir degil.
- CI veya lokal kontrol yaniltici olabilir.
- Eski, arşiv, worktree ve hatta node_modules turevi testler aktif yuzeye karisiyor.

Neden:

- Tarihsel depo yapisi degismis ama pytest kok ayari guncellenmemis.

Cozum:

- `testpaths` guncel `tests` klasorune cekilmeli.
- `archive/`, `desktop/node_modules/`, eski worktree yolları `norecursedirs` ile dislanmali.
- Kritikal akış testleri ile kalan test suite ayri marker/entrypoint ile yönetilmeli.

## 4.3 P1 - WebSocket notification sozlesmesi bozuk

Dosyalar:

- `engine/event_bus.py`
- `engine/h_engine.py`
- `desktop/src/components/Dashboard.jsx`

Kanit:

- `event_bus.emit()` payload'i `{"type": event, **data}` uretiyor.
- `h_engine.py` `emit("notification", {"type": "hybrid_eod", ...})` cagiriyor.
- `Dashboard.jsx` yalniz `msg.type === 'notification'` ise bildirim ekliyor.

Teknik etki:

- Event gercekten uretiliyor ama `type` alani ic veri tarafindan eziliyor.
- Frontend bildirim drawer'i event'i bekledigi sekilde gormuyor.
- Kullanici REST ile gelen bildirimleri gorebilirken WS ile gelen anlik bildirimlerden mahrum kalabilir.

Neden:

- Event envelope ile event payload ayni `type` alanini kullaniyor.
- Sema ayrimi yok: event tipi ile notification tipi birbirine karismis.

Cozum:

- Ust seviye event tipi `event_type`, alt notification tipi `notification_type` veya `notif_type` olmali.
- Frontend tek bir normalize mesaj semasi kullanmali.
- Bu sozlesme icin bir contract test eklenmeli.

## 4.4 P1 - Settings ekranindaki restartMT5 butonu bagli degil

Dosyalar:

- `desktop/src/components/Settings.jsx`
- `desktop/preload.js`
- `desktop/main.js`

Kanit:

- UI `window.electronAPI?.restartMT5` kontrol edip cagiriyor.
- Preload export listesinde `restartMT5` yok.
- Main process IPC handler tarafinda da bu isimle bir handler yok.
- Kod aramasinda eslesme bulunmadi.

Teknik etki:

- Kullaniciya islevsel gorunen bir buton var.
- Fallback olarak alert cikiyor; yani gercek entegrasyon tamamlanmamis.
- UI guvenilirligi ve operator deneyimi zarar goruyor.

Neden:

- UI tarafinda planlanan bir ozellik tamamlanmamis veya sonra IPC katmanindan duserken buton yerinde kalmis.

Cozum:

- Bu akisa gercek IPC eklensin, ya da buton gecici olarak kaldirilsin.
- UI sadece desteklenen electronAPI yuzeylerini kullanmali.

## 4.5 P1 - Notification prefs backend'e yaziliyor ama UI bunlari source-of-truth olarak okumuyor

Dosyalar:

- `api/routes/settings.py`
- `desktop/src/components/Settings.jsx`
- `desktop/src/services/api.js`

Kanit:

- Backend `GET /settings/notification-prefs` endpoint'i sagliyor.
- Frontend'de getter yok.
- Settings acilisinda prefs localStorage'dan okunuyor.

Teknik etki:

- Config'e kalici yazilan tercih ile UI state'i ayrisabilir.
- Farkli session, restart veya birden fazla pencere durumunda tutarsizlik olusabilir.

Neden:

- Persistence backend'e tasinmis ama read-path frontend'de tamamlanmamis.

Cozum:

- Settings mount aninda backend getter okunmali.
- localStorage sadece cache/fallback olmali.
- Tek kaynak secilmeli: backend config.

## 4.6 P1 - `/api/status.last_cycle` fiilen olu alan

Dosyalar:

- `api/routes/status.py`
- `engine/main.py`

Kanit:

- Status endpoint `engine._last_cycle_time` bekliyor.
- Engine tarafinda `_last_cycle_time` tutulmuyor.
- Sadece `_last_successful_cycle_time` var.

Teknik etki:

- API şemasında anlamli gorunen alan fiilen bos gelebilir.
- UI veya operator bu alana guvenirse yanlış sağlık yorumu yapabilir.

Neden:

- Health refactor'da alan isimleri kaymis, status endpoint guncellenmemis.

Cozum:

- Status endpoint `_last_successful_cycle_time` kullanmali veya engine gercek `last_cycle_time` tutmali.
- Sema ve implementasyon eslestirilmeli.

## 4.7 P1 - `/api/status.phase` semantiği oncelik hatasi iceriyor

Dosya: `api/routes/status.py`

Kanit:

- Faz hesaplamasi:
  - engine yoksa `stopped`
  - MT5 yoksa `error`
  - kill switch >=3 ise `killed`

Teknik etki:

- L3 aktif ve MT5 de kopukse `phase = error`
- Oysa risk semantiği olarak bu sistem "killed" durumunda.
- Kullaniciya giden durum bilgisinde oncelik yanlisi olusur.

Neden:

- Faz belirleme mantigi bağlanti sagligi ile risk sagligini tek lineer blokta cozmeye calisiyor.

Cozum:

- Risk state, connectivity state ve lifecycle state ayrilmali.
- Tek string faz yerine bileşik status modeli daha dogru olur.

## 4.8 P2 - Notification unread_count global sayi degil, sadece donen listenin sayimi

Dosya: `api/routes/notifications.py`

Kanit:

- Once `limit` ile satirlar cekiliyor.
- Sonra `unread_count = sum(1 for i in items if not i.read)`

Teknik etki:

- API `unread_count` alanini global toplam gibi sunuyor ama aslinda sadece donen pencerenin sayisi.
- UI'da badge veya operator paneli yanlis sayi gosterebilir.

Neden:

- Response modeli iki farkli anlami tek field'da birlestirmis.

Cozum:

- Toplam unread count icin ayri DB sorgusu eklenmeli.
- `count` ve `unread_count` semantics dokumante edilmeli.

## 4.9 P2 - Baslatici dosyasinda iki mimari donemin kalintilari birlikte yasiyor

Dosya: `start_ustat.py`

Kanit:

- Dosya basi pywebview + pystray anlatıyor.
- Dosyanin ilerisi Electron baslatma akisi kullaniyor.
- Ayrica pywebview shim mantigi da korunmus.

Teknik etki:

- Yeni gelistirici yanlis mimari model ile ise baslayabilir.
- Hata ayiklama sirasinda "gercek yol" ile "tarihsel kalinti" birbirine karisir.
- Operasyon rehberi ile runtime davranisi ayrisir.

Neden:

- Gecis doneminde eski aciklamalar ve baglanti kodlari temizlenmeden korunmus.

Cozum:

- `start_ustat.py` ust yorum blogu gercek mimariye gore yeniden yazilmali.
- Olü kod ve tarihsel bridge kisimlari ayri archive veya doc notuna tasinmali.

## 4.10 P2 - Motorlar arasi capraz bagimlilik yuksek

Dosya: `engine/main.py`

Kanit:

- `ogul.h_engine = self.h_engine`
- `ogul.ustat = self.ustat`
- `manuel_motor.ogul = self.ogul`
- `h_engine.manuel_motor = self.manuel_motor`
- `baba.h_engine = self.h_engine`
- `baba.ogul = self.ogul`

Teknik etki:

- Bir motorun davranisi digerinin private state'ine baglanabiliyor.
- Test izolasyonu zorlasiyor.
- Hata sebebini tek modulde izole etmek zorlasiyor.

Neden:

- Hizli delivery icin servis arayuzu yerine dogrudan obje baglama tercih edilmis.

Cozum:

- Dar arayuzler tanimlanmali.
- Her motor sadece ihtiyaci olan capability ile baglanmali.
- Private field yerine method/protocol tabanli entegrasyon kurulmalı.

## 5. Motor Bazli Derin Degerlendirme

## 5.1 Engine Main

Guclu:

- Cycle orchestration net
- BABA once prensibi korunmus
- Slow-cycle tespiti ve reconnect denemeleri var

Sorunlar:

- Fazla sorumluluk tasiyor: startup, shutdown, retention, backup, maintenance, orchestration, health
- Lifecycle davranislari tek dosyada buyumus
- Degrade mod davranislari yeterince testli gorunmuyor

Sonuc:

`main.py`, sistemin en kritik ama ayni zamanda en riskli degisim noktasi.

## 5.2 Baba

Guclu:

- Rejim, warning, kill-switch, cooldown, drawdown mantigi zengin
- Dokumantasyon seviyesi yuksek

Sorunlar:

- Dosya boyutu cok yuksek
- Rejim tespiti, risk verdict, kill-switch operasyonu, fake sinyal analizi, state restore ayni modülde
- `self._kill_switch_level`, `self._risk_state`, `self._kill_switch_details` gibi private state alanlari API ve diger katmanlardan dogrudan okunuyor

Sonuc:

Bu modül işlevsel ama "merkezi zihin" haline gelmiş; ayrıştırılmazsa zamanla daha da kırılganlaşır.

## 5.3 Ogul

Guclu:

- Hem sinyal hem emir state-machine dusunulmus
- USTAT ve BABA ile uyumlu olma niyeti var

Sorunlar:

- Sinyal uretimi + pozisyon yonetimi + trade state machine + trailing + zaman kurallari + USTAT entegrasyonu tek dosyada
- Bu kadar farkli eksen bir arada olunca regressions gizlenebilir

Sonuc:

OĞUL teknik borcun en fazla büyüme potansiyeli olan modüllerden biri.

## 5.4 H-Engine

Guclu:

- Hibrit mantik ayri modülde tutulmus
- Bildirim ve DB persist düşünülmüş

Sorunlar:

- Notification event semasi kirik
- PRIMNET, EOD, devir kontrolleri, orphan cleanup, netting sync ayni dosyada birikmis

Sonuc:

Iyi bir uzmanlasma var, ama artik kendi icinde modullesme ihtiyaci dogmus.

## 5.5 Ustat

Guclu:

- Sistemi "gozlemleyen" katman fikri stratejik olarak degerli
- Trade attribution ve strategy pool dusuncesi olgun

Sorunlar:

- Gozlemci kalmasi gereken katman giderek config/risk feedback loop tarafina kayiyor
- Bu alan iyi yonetilmezse gelecekte "ikinci bir kural motoru" gibi davranmaya baslayabilir

Sonuc:

USTAT degerli ama sinirlarinin net tutulmasi gerekiyor: karar veren mi, gozlemleyen mi?

## 6. API Katmani Degerlendirmesi

Genel olarak API yüzeyi zengin. Ancak bazı endpointlerde iki temel sorun var:

1. Private state'e dogrudan baglilik
2. Schema ile runtime semantigin tam ortusmemesi

Ornekler:

- `status.py` private alanlari dogrudan okuyor
- `health.py` hem private alan hem derived alanlarla karma model kullaniyor
- `risk.py` runtime verdict ve snapshot mantigini birlestiriyor

Bu yaklaşım kısa vadede pratik, uzun vadede sema erozyonu uretir.

## 7. Desktop / UI Degerlendirmesi

Guclu:

- Dashboard zengin
- WS + REST fallback birlikte dusunulmus
- Operator odakli ekranlar mevcut

Sorunlar:

- Bazı kontroller gercek backend kabiliyetiyle eslesmiyor
- localStorage ve backend config birlikte source-of-truth olmaya calisiyor
- Bildirimlerde WS ve REST semasi tam hizalanmamis
- Hala `alert(...)` gibi kaba fallbackler kalmis

Sonuc:

UI tarafi uretken ama sistematik bir "state contract cleanup" ihtiyaci var.

## 8. Test ve Kalite Guvencesi

Pozitif:

- Kritik akis statik sozlesme testleri iyi fikir

Negatif:

- Ana test entrypoint bozuk
- Test discovery kontrol disina cikmis
- Archive/worktree testi aktif yuzeye karisiyor
- Testlerin varligi ile testlerin gercekten koruma uretmesi ayni sey degil

En onemli sonuc:

Bu repo icin bugun test sayisindan daha onemli olan sey, "hangi test gercek entrypointten calisiyor?" sorusudur.

## 9. Dokumantasyon ve Surum Erozyonu

Sistemde surumleme ve anlatim tarafinda drift goruluyor:

- Ana dosyalarda `v6.0`
- Bazı docstring ve route yorumlarında eski `v5.7`, `v5.8`, `v5.9`
- Baslatıcı açıklamaları yeni gerçek mimariyle tam hizali degil

Bu tek basina runtime bug degil; ama karmaşık sistemlerde yanlış zihinsel model, gerçek bug kadar maliyetlidir.

## 10. Koku Neden Analizi

Bu kod tabanındaki sorunlarin cogu uc kok nedenden geliyor:

### 10.1 Hizli evrim, yavas temizleme

Yeni kararlar eklenmis, ama eski kararlarin izleri tam temizlenmemis.

### 10.2 Dogrudan obje baglama

Net interface yerine "birbirini taniyan motorlar" modeli secilmis.

### 10.3 Koruma mekanizmasi olarak dokumantasyon

Kodun kendisi moduler ve sade olmaktan uzaklasinca, repo bunu raporlar, anayasa, rehberler ve statik testlerle telafi etmeye calisiyor.

Bu belirli bir seviyeye kadar ise yarar; sonra sistem kendini tasimakta zorlanir.

## 11. Oncelikli Iyilestirme Plani

### Faz A - Stabilizasyon

1. `engine/main.py` startup NameError duzelt
2. `pytest.ini` ve test discovery temizligi
3. WebSocket notification envelope normalizasyonu
4. `restartMT5` butonunu gercekten bagla veya kaldir
5. `/api/status.last_cycle` ve `phase` semantigini duzelt

### Faz B - Sozlesme Temizligi

1. Notification prefs icin backend getter'i frontend source-of-truth yap
2. `status`, `health`, `risk` response alanlarini yeniden tanimla
3. unread count semantiğini ayri sorguyla dogrula

### Faz C - Mimari Ayrıştırma

1. `Baba`:
   - regime detection
   - risk enforcement
   - kill-switch operations
2. `Ogul`:
   - signal generation
   - order state machine
   - active trade management
3. `MT5Bridge`:
   - read operations
   - write operations
   - history sync

## 12. Son Hukum

Bu proje cop degil; aksine ciddi emek ve operasyonel bilinç tasiyor. Ama sistemin olgunluk seviyesi su an "ustune ozellik ekle" noktasindan "cekirdek sozlesmeleri temizle, sonra buyu" noktasina gelmis.

Bugun en dogru teknik strateji:

- once guvenilirlik
- sonra veri sozlesmesi dogrulugu
- sonra modulerlesme

Bu sira tersine cevrilirse her yeni düzeltme yeni bir sessiz bozulma üretmeye devam eder.

## 13. Inceleme Siniri

Bu rapor kod, config, test, UI/API sozlesmeleri ve dokumantasyon uzerinden hazirlandi. Dis servis davranislari, canli MT5 ortam farklari ve piyasa acik saat runtime davranislari ayrica senaryo testleriyle dogrulanmalidir.
