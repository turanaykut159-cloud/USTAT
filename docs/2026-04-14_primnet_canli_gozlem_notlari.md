# PRIMNET Canlı Gözlem Notları — 14 Nisan 2026

**Durum:** Savaş Zamanı (piyasa açık) — sadece gözlem, hiçbir dosyaya dokunulmadı
**Pozisyon:** F_KONTR SELL #8050570106, Lot 63, Giriş 10.16, Trailing offset 1.5 prim sabit, Hedef ±9.5 prim
**Akşam düzeltilecek:** 18:15 sonrası Barış Zamanı

---

## Anlık durum serisi (MT5 ile çapraz doğrulandı)

| # | Güncel prim | Footer SL | SL prim | MT5 buy stop | K/Z | Tabloda aktif satır "stop" |
|---|---|---|---|---|---|---|
| 1 | -2.1 | 10.11 | -0.5 | 10.11 | +1323 TL | -0.5 → stop +1.0 |
| 2 | -2.4 | 10.06 | -1.0 | 10.06 | +1512 TL | -2.0 → stop -0.5 ⚠ |
| 3 | -3.1 | 10.01 | -1.5 | 10.01 | +1953 TL | -3.0 → stop -1.5 ✓ |
| 4 | -4.0 | 9.91 | -2.5 | 9.91 | +2583 TL | -4.0 → stop -2.5 ✓ |
| 5 | **-2.7** (geri dönüş!) | 9.91 (değişmedi ✓) | -2.5 | 9.91 | +1701 TL | **-2.7 → stop -1.2 ⚠⚠** |
| 6 | **POZİSYON KAPANDI** — buy stop 9.91 tetiklendi, kâr 1.575 TL kilitli gerçekleşti ✓ |
| 7 | **YENİ POZİSYON #8050576767** SELL 50 @ 9.87 (prim -2.9), güncel -4.0, K/Z +600 TL, Footer SL **9.92** ≠ MT5 SL **9.97** ⚠⚠⚠ |
| 8 | güncel -3.4 (9.81), K/Z +300, Footer SL 9.92 = MT5 SL 9.92 ✓ (önceki 9.97 tespiti snapshot timing'di) |
| 9 | güncel -3.8 (9.77), K/Z +500, SL hâlâ 9.92, monotonic trailing ✓, yeni: f_aselsa 3. pozisyon MT5'te görüldü |

**MT5 karşılaştırması (4. anlık):**
- Pozisyon: sell 63 @ 10.16 ✓ birebir
- Bid/Ask: 9.76 / 9.77 → prim -4.0 ✓
- Kâr: 2 583,00 TL ✓ birebir
- buy stop limit 9.91 = SL footer 9.91 ✓ birebir
- buy limit 9.19 = TP footer 9.19 ✓ birebir

**Sonuç:** Broker tarafındaki gerçek emirler PRIMNET footer değerleri ile tam eşleşiyor. Trading mantığı DOĞRU çalışıyor.

---

## Tespit 1 — PRIMNET tablosu "STOP SEV." kolonu vs gerçek broker senkronsuz

**Belirti:** Tablo her 0.5 prim için teorik "güncel + 1.5" offset gösteriyor. Broker ise 1.0 prim kademeli ilerliyor.

**Örnek (anlık #2):** Güncel -2.4, tablo -2.0 satırı "stop -0.5" diyor ama broker gerçekte SL'i -1.0'da tutuyor (10.06). Kullanıcı tablodan "320 TL kilitli" gördüğünde gerçekte o an 0 TL kilitli.

**Kök neden (muhtemel):** `h_engine.py` trailing step grid 1.0 prim ile uyguluyor, UI tablosu 0.5 prim ile render ediyor. İki tarafın grid adımı aynı olmalı.

**Düzeltme:**
- `engine/h_engine.py` içinde trailing step ne? config'den mi geliyor? Sabit mi?
- `desktop/src/components/PrimnetDetail.jsx` (veya ilgili bileşen) tablo render grid'ini broker grid'ine eşitle

---

## Tespit 2 — "SL" etiketi yanıltıcı

**Belirti:** Footer'da "SL: 9.91" yazıyor. SELL pozisyonu için stop-loss girişin ÜSTÜNDE olmalı (ör. 10.21+). 9.91 girişin ALTI = bu aslında **profit-lock / trailing stop** seviyesi.

**MT5 doğru gösteriyor:** Emir "buy stop limit" olarak tutuluyor. Fiyat 9.91'e yükselirse tetiklenir, short kapatılır, 2.5 prim (1600 TL) kâr kilitli çıkılır.

**Düzeltme:** UI'da "SL" etiketi → "Trailing Stop" / "Kilit Seviyesi" olarak değişsin. Kavramsal karışıklığı önler.

**Dosya:** `desktop/src/components/PrimnetDetail.jsx` (doğrulanacak)

---

## Tespit 3 — TP fiyat hesabı 2 tick sapma

**Belirti:**
- Hedef etiketi: ±9.5 prim → teorik fiyat 10.16 − 0.95 = **9.21**
- MT5 gerçek buy limit: **9.19** (= -9.7 prim)
- Tablo "-9.5 KAPAT" satırı fiyat 9.19 gösteriyor

**Kök neden (muhtemel):** `h_engine` TP fiyat hesabında tick_size snap veya round fonksiyonu 9.21 yerine 9.19 üretiyor. 2 tick aşağı kaydırıyor.

**Düzeltme:** TP hesabındaki yuvarlama mantığı kontrol edilmeli. Hedef etiketi ile gerçek emir aynı sayı olmalı.

---

## Tespit 4 — "STOP SEV." kolonu ZARAR DURDUR satırlarında kafa karıştırıcı

**Belirti:** +1.5 ve +1.0 prim satırlarında (ZARAR DURDUR tetikleyici satırlar) "STOP SEV." kolonu güncel aktif trailing seviyesini gösteriyor. Her anlık güncelleniyor:
- Anlık #2: -1.0
- Anlık #3: -1.5
- Anlık #4: -2.5

**Problem:** Sütun başlığı "O prim seviyesindeki teorik stop" izlenimi veriyor ama aslında "Şu anki aktif stop".

**Düzeltme:** Sütun başlığı → "Aktif Stop" veya bu satırlarda değer gösterilmesin (ZARAR DURDUR satırlarıyla konu alakasız).

---

## Tespit 5 — Tabloda -3.5 kademesi eksik

**Belirti:** Anlık #4'te -3.0'dan direkt -4.0'a geçiş var, -3.5 satırı render edilmemiş. Diğer 0.5 kademeler (-2.5, -4.5) var.

**Kök neden (muhtemel):** Render koşulunda bir edge case. Belki güncel prim kademesi atlandığında çiziliyor.

**Düzeltme:** `PrimnetDetail.jsx` tablosunda tüm 0.5 kademelerin render koşulunu kontrol et.

---

## Tespit 6 — Güncel prim ve K/Z ondalık tutarsızlığı

**Belirti:**
- Anlık #2: K/Z 1512/640 = 2.3625 → gerçek prim -2.36, ekranda -2.4
- Anlık #3: K/Z 1953/640 = 3.052 → gerçek prim -3.05, ekranda -3.1
- Anlık #4: K/Z 2583/640 = 4.036 → gerçek prim -4.04, ekranda -4.0

**Problem:** Güncel prim tek ondalık gösteriliyor, K/Z gerçek fiyattan hesaplanıyor. Kullanıcı hesap tutarsızlığı hissedebilir.

**Düzeltme:** Güncel prim gösterimi iki ondalık (-4.04 gibi). Kritik değil, kozmetik.

---

## Tespit 8 — KRİTİK: Tablo güncel prim geri döndüğünde YANLIŞ stop gösteriyor

**Belirti (anlık #5 — prim -4.0'dan -2.7'ye geri döndü):**
- Gerçek durum: Stop broker'da fiyat **9.91**'de (= prim -2.5 stop seviyesi). Trailing geri gitmez, kilitli.
- PRIMNET footer SL: **9.91** ✓ (doğru, broker ile uyumlu)
- PRIMNET tablosu "-2.7" satırı: **"Stop -1.2 → kilitli kâr +768 TL"** ⚠⚠
- Ama gerçekte stop -2.5 seviyesinde, kilitli kâr **+1600 TL**.

**Problem:** Tablo güncel prim satırında "bu prim seviyesinde olsaydık trailing bizi nereye koyardı" diye **teorik interpolasyon** yapıyor (-2.7 + 1.5 = -1.2). Bu durum trailing'in **monotonic** (geri gitmez) özelliğini yok sayıyor — sanki stop geriye alınabilirmiş gibi gösteriyor.

**Tehlike:** Kullanıcı tabloya bakıp "şu an +768 TL kilitli" algısı oluşturur. Gerçekte **+1600 TL kilitli** (fiyat 9.91'e geri dönerse kazanılacak). Tersi yönde yanıltıcı — bu sefer kullanıcı **az** kâr kilitli sanıyor ama gerçekte daha fazla.

**Kök neden:** PRIMNET tablosu statik bir "prim → teorik stop" hesabı yapıyor, gerçek **locked_stop** değerini referans almıyor. Trailing history'yi (peak prim) dikkate almıyor.

**Düzeltme:**
- Tablo render'ında **güncel satır için** `stop = max(teorik_stop, broker_locked_stop)` (SELL için min/max yönüne göre) mantığı
- Veya: Tabloda **broker'dan gelen gerçek aktif stop** ayrı bir çizgi olarak gösterilmeli (ör. kalın çizgi "Aktif trailing" satırı)
- Veya: Tabloda sadece henüz geçilmemiş (henüz erişilecek) prim seviyeleri gösterilsin, geri dönen güncel prim satırı eklenmesin

**Dosya:** `desktop/src/components/PrimnetDetail.jsx` + ilgili Primnet API endpoint (muhtemelen `api/routes/hybrid_trade.py` veya benzeri)

**Öncelik:** **YÜKSEK** — kullanıcı "kaç TL garanti altında?" sorusuna yanlış cevap veriyor. Özellikle stop'a yakın durumlarda kritik. Şu an: güncel prim -2.7, stop prim -2.5 stop fiyatı 9.91 — **aradaki mesafe sadece 0.2 prim (= 128 TL)**. Fiyat 2 tick yukarı çıksa pozisyon kapanır.

---

## Tespit 7 — Kontrol edilecek: f_akbnk paralel pozisyonu

**Belirti:** MT5'te f_akbnk0426 için bekleyen buy stop limit 9.91 ve sell limit 10.10 emirleri görünüyor. Başka bir PRIMNET pozisyonu olabilir.

**Aksiyon:** f_akbnk PRIMNET ekranını da aç, aynı davranış sorunları var mı doğrula. Tespitler sistematik mi kontrat-bazlı mı anlaşılacak.

**Doğrulandı (anlık #5 MT5):** f_akbnk0426 BUY 5 lot @ 79.96, aktif, bekleyen SL (sell stop limit) 79.55, TP (sell limit) 80.46, kâr ~250 TL. Yani hem SELL (kontr) hem BUY (akbnk) pozisyonları PRIMNET altında çalışıyor. Akşam akbnk ekranını da görmeliyiz.

---

## Tespit 9 — EN KRİTİK: PRIMNET footer SL, MT5 gerçek SL'i göstermiyor

**Belirti (yeni pozisyon #8050576767, anlık #7):**
- MT5 gerçek "buy stop limit" (gerçek SL): **9.97** (prim -1.9, giriş 9.87'nin 10 tick ÜSTÜ = zarar tarafı)
- PRIMNET footer "SL:": **9.92** (prim -2.4)
- PRIMNET tablosu güncel -4.0 satırı "stop -2.5": 9.91 (teorik güncel + 1.5)

**Kök neden analizi:**
- Yeni pozisyonun kârı şu an +1.1 prim (600 TL). Trailing eşiği muhtemelen ≥1.5 prim kâr.
- Trailing henüz aktive OLMAMIŞ → MT5'teki SL hâlâ initial placement'ta (9.97)
- PRIMNET footer ise "trailing aktif olsaydı nerede olurdu" **projeksiyonunu** gösteriyor (9.92 ≈ güncel + 1.5)

**Tehlike:** Kullanıcı footer'a bakıp "stop 9.92'de, fiyat 16 tick uzak" düşünür. Gerçekte:
- Gerçek stop 9.97'de (11 tick uzak)
- Stop tetiklenirse: 9.87 SELL → 9.97 buy back = **−500 TL zarar** (kâr değil!)

Yani kullanıcı **kâr kilidinde** sanırken aslında **açık zarar riski** altında. Bu önceki tespitlerden daha ciddi — yanıltıcı değil, **tersine bilgi**.

**Düzeltme:**
- Footer "SL:" alanı GERÇEKTEN broker'daki aktif stop emrini göstersin (API'den `get_positions().stop_loss` veya pending order listesinden)
- Eğer trailing henüz aktive olmadıysa "SL: 9.97 (initial, trailing bekleniyor)" şeklinde açık etiket
- Trailing aktive olduğunda footer değeri ile broker değeri senkron olsun

**Dosya:**
- `api/routes/hybrid_trade.py` (veya PRIMNET endpoint'i) — footer SL kaynak verisini MT5 pending order'dan çekmek
- `desktop/src/components/PrimnetDetail.jsx` — footer rendering

**Öncelik:** **EN YÜKSEK** — yanıltıcılık + ters bilgi. Bu tespit akşam ilk düzeltilecek.

---

## Önceki pozisyon #8050570106 kapanışı — sistem DOĞRU çalıştı ✓

**Olay sırası:**
1. SELL 63 @ 10.16 açıldı 09:53:37
2. Fiyat 9.76'ya düştü (prim -4.0), trailing stop progressive olarak 9.91'e çekildi (prim -2.5 stop seviyesi, 1600 TL kâr kilidi)
3. Fiyat 9.76'dan geri dönüp 9.89, ardından 9.91'e ulaştı
4. MT5 "buy stop limit 9.91" TETİKLENDİ → SELL pozisyonu kapandı
5. Gerçekleşen kâr: (10.16 − 9.91) × 63 × 100 = **1.575 TL**
6. Fiyat tekrar düşüşe geçince sistem yeni SELL 50 @ 9.87 açtı (#8050576767)

**Sonuç:** Buy stop limit mekaniği tasarım amacına uygun çalıştı. Trailing kâr koruma fonksiyonelliği sorunsuz. Hata sadece **görselleştirmede** (Tespit 1, 8, 9).

---

## Tespit 10 — AÇIKLAMA sütunu mantık ve matematik hataları (anlık #8)

**Bağlam:** Yeni pozisyon #8050576767, giriş -2.9 (9.87), güncel -3.4 (9.81), MT5 SL 9.92, Footer SL 9.92 ✓

### 10.1 — Matematik ters ("<"/">" işaretleri)

| Satır açıklaması | Aritmetik gerçek |
|---|---|
| "Stop -1.5 **<** Giriş" | -1.5 **>** -2.9 (tersine yazılmış) |
| "Stop -1.9 **<** Giriş" | -1.9 **>** -2.9 (tersine) |
| "Stop -2.5 **<** Giriş" | -2.5 **>** -2.9 (tersine) |
| "Stop -3.5 **>** Giriş" | -3.5 **<** -2.9 (tersine) |
| "Stop -4.5 **>** Giriş" | -4.5 **<** -2.9 (tersine) |

Kod "prim eksende daha aşağı = daha yüksek fiyat" intent'iyle yazılmış ama kullanıcı ekranda matematik hatası görüyor.

**Düzeltme:** Matematik-bağımsız ifade kullan. Örn. "Kilitli kâr yok" / "0.6 prim kâr kilitli" yeterli, "Stop < Giriş" kısmı silinsin. Ya da "Stop giriş fiyatı üstünde" gibi fiyat-based ifade.

### 10.2 — Açıklamadaki stop ≠ gerçek aktif broker stop

Açıklama teorik "güncel + 1.5 offset" stop üzerinden mantık yürütüyor. Gerçek broker stop farklı yerde olabilir (özellikle trailing monotonic — stop geri gitmez).

Örn. -3.4 satırı "Stop -1.9 → kilitli kâr yok". Gerçek broker stop -2.4'te. Sonuç ("kilitli kâr yok") doğru ama gerekçe yanlış.

### 10.3 — GİRİŞ satırında iki farklı stop karıştırılmış

-2.9 GİRİŞ satırı:
- STOP SEV kolonu: **-1.4** (initial zarar durdur, 10.02)
- AÇIKLAMA: "Stop **-4.4** (-1.5 prim)" (initial trailing kâr-stop, 9.72)

İki farklı stop mekanizması tek satıra sıkıştırılmış. Kullanıcı kafası karışıyor.

**Düzeltme:** Ya iki ayrı satır ("Zarar Durdur: -1.4" / "Trailing Kâr-Stop: -4.4"), ya da tek aktif stop (hangisi broker'da geçerliyse) + diğeri yorum olarak küçük.

### 10.4 — ZARAR DURDUR satırları yanlış tetikleme fiyatı ima ediyor

-1.4 ve -2.0 satırları "ZARAR DURDUR tetiklendi → KAPAT" diyor. Ama broker stop 9.92'de. Fiyat 10.02'ye ulaşmadan 9.92'de kapanır. Bu satırların fiyat kolonu (10.02, 9.96) yanıltıcı.

**Düzeltme:** ZARAR DURDUR satırları için "Eğer aktif stop'a değilse bu fiyatta kapanırdı" gibi koşullu dil, veya bu satırları sadeleştir.

### 10.5 — -2.4 satırı tarihsel / güncel karışıklığı

-2.4 satırı "AÇIK Zararda. Stop -4.4'da" diyor. Bu tarihsel (fiyat ilk -2.4'e geldiğinde initial trailing -4.4'teydi). Ama şu an stop **zaten -2.4'te** (9.92 = bu satırın fiyatı). Yani aynı satırın fiyat değerine stop değdi, kapanır durumu olur.

Tarihsel vs güncel ayrımı yok, kullanıcı gerçek stop konumunu anlayamıyor.

### 10.6 — K/Z tablosu küçük yuvarlama hataları

- -4.0 satırı: beklenen 600, ekran 582 (fark 18 TL)
- -5.0 satırı: beklenen 1100, ekran 1090 (fark 10 TL)
- -6.0 satırı: beklenen 1600, ekran 1598 (fark 2 TL)

Sistematik olmayan rastgele sapma. Fiyat × multiplier hesabında muhtemelen step_size veya precision sorunu.

**Düzeltme:** PRIMNET endpoint'te K/Z hesabını `(giriş_fiyat - satır_fiyat) × lot × contract_size` şeklinde tam integer math ile yap, ondalık float zinciri kullanma.

---

## Tespit 9 güncellemesi — footer SL senkronizasyonu kısmen çalışıyor

Anlık #8'de MT5 SL **9.92**'ye çekilmiş (önceki #7'de 9.97'deydi). Footer SL de **9.92**. İkisi şu an senkron ✓.

Anlamı: trailing arka tarafta `modify_position` çağırıyor ve MT5'i güncelliyor. Önceki gözlem (9.97 vs 9.92 fark) muhtemelen MT5 ekran snapshot'ın yakalama anı farkından kaynaklıydı.

**Revize tespit:** Tespit 9 hâlâ geçerli ama ağırlığı düşük. Gerçek sorun daha ziyade **güncellemenin anlık mı gecikmeli mi** olduğu. Log'dan `modify_position` çağrı sıklığı ve gecikmesi kontrol edilmeli.

---

## MT5 P&L tutarsızlığı notu (anlık #5)

- PRIMNET f_kontr K/Z: **+1701 TL**
- MT5 Varlık-Bakiye farkı (toplam unrealized): 40 964,45 − 39 139,43 = **+1 825 TL**
- f_akbnk kısmı: 1825 − 1701 = **+124 TL**
- MT5'te görünen f_akbnk kâr sütunu: ~250 TL gibi okunuyordu ama düşük çözünürlükle net değil
- Kontrol gerekli: MT5'in kontr için gösterdiği kâr rakamı ile PRIMNET +1701 tam birebir mi? Komisyon/swap dahil mi?

Akşam: API'de `get_positions()` çıktısını log'dan çek, her pozisyonun **profit** alanını PRIMNET K/Z ile karşılaştır.

**Not (anlık #9):** MT5 kontr kâr 550 TL, PRIMNET 500 TL. 50 TL fark = 1 tick × 5000 (50 lot × 100). Muhtemelen MT5 bid/ask'tan birini (bid), PRIMNET diğerini (ask, SELL close için gerçekçi) kullanıyor. Hata değil, bid/ask spread gösterimi. Düzeltme gerekmez ama UI'da "close-price bazlı K/Z" açıklaması eklemek kullanıcı için şeffaf olur.

---

## Tespit 1 kesinleşti (anlık #9)

**Trailing step grid = 1.0 prim** olarak doğrulandı. Gözlem dizisi:
- Yeni pozisyon giriş -2.9, initial SL -1.4 (10.02)
- Güncel -3.9'u geçtiğinde SL -2.4'e (9.92) atladı
- Güncel -4.0'a indi, geri -3.4'e döndü, tekrar -3.8'e indi → SL hep 9.92 (monotonic ✓)
- Bir sonraki trail: güncel -4.9'a ulaşırsa SL -3.4'e (9.82)

**Tablo grid'i ise 0.1 prim** (her 0.1 prim için bir satır). İki grid uyumsuz.

**Düzeltme önerisi (akşam):**
- Seçenek A: Tablo grid'ini 1.0 prim'e indir (daha temiz)
- Seçenek B: Tabloda **gerçek aktif broker SL'i** ayrı bir vurgulu satır olarak göster, teorik satırlar silik gri
- Seçenek C: Trailing step'i config'den alarak tabloya yansıt (dinamik grid)

Hangi seçenek: kullanıcı tercihi. Auditor ajan akşam analiz edecek.

---

## Çoklu kontrat durumu (anlık #9)

MT5'te şu an 3 aktif pozisyon:
- f_akbnk0426 BUY 5 @ 79.96 (+560 TL)
- f_kontr0426 SELL 50 @ 9.87 (+550 TL)  ← izlediğimiz
- f_aselsa0426 ??? (+480 TL)  ← YENİ, PRIMNET'i görmedik

**Akşam:** Her üç kontratın da PRIMNET ekranını incele. Tespitler sistemik mi kontrat-özel mi. Büyük ihtimalle aynı kod path kullanıldığı için tüm kontratlarda aynı hatalar olacak — ama doğrulamak lazım.

---

## Akşam yapılacaklar (öncelik sırası)

**1. Araştırma (auditor ajan + log):**
- `logs/ustat_2026-04-14.log` → pozisyon 8050570106 için tüm `modify_position` çağrıları zaman serisi
- Her çağrıda SL değeri ne? Trailing step grid kesin kaç prim?
- `engine/h_engine.py` trailing fonksiyonunu (Sarı Bölge) oku, step hesabını çıkar

**2. Plan:**
- Grid adımı düzeltmesi: UI mı broker mı baz alınacak? (Broker'ın davranışı anayasal, UI buna uymalı)
- TP tick snap düzeltmesi
- UI etiket/kolon değişiklikleri

**3. Uygulama (Barış Zamanı):**
- `engine/h_engine.py` — trailing step ve TP hesabı (Sarı Bölge, Bölüm 3.3 adımları)
- `desktop/src/components/PrimnetDetail.jsx` — etiketler, kolon başlığı, render koşulları, ondalık gösterim
- `npm run build` ZORUNLU (Bölüm 7 ADIM 1)
- Kritik akış testleri yeşil olmalı (Bölüm 7 ADIM 1.5)

**4. Doğrulama:**
- Yarın piyasa açıldığında yeniden canlı gözlem, tespitler giderildi mi?

---

## Tespit 11 — BUY yönü analizi (F_AKBNK #8050573843)

**Amaç:** PRIMNET'in BUY yönünde de aynı hataları gösterip göstermediğini kontrol etmek. Tespitler sistemik mi yoksa yön-özel mi ayırmak.

**Pozisyon verisi:**
- F_AKBNK BUY 5 lot, giriş fiyat ~78.97 (giriş primi **+1.3**)
- Güncel fiyat 81.50 (güncel prim **+3.2**)
- Kâr primi +1.9, K/Z **+760 TL**
- Footer: SL **80.35**, TP **86.45**, Lot 5
- Trailing 1.5 prim SABİT, Hedef ±9.5 prim (aynı parametreler)
- MT5: sell stop limit (SL koruma) + sell limit 86.45 (TP hedefi) ✓

### 11.1 — AÇIKLAMA matematik işaretleri BUY'da DOĞRU ✓

| Satır | Açıklama | Aritmetik kontrol |
|---|---|---|
| +3.2 | "Stop +1.7 **>** Giriş" | +1.7 > +1.3 **DOĞRU** ✓ |
| +5.0 | "Stop +3.5 **>** Giriş" | +3.5 > +1.3 **DOĞRU** ✓ |
| +7.0 | "Stop +5.5 **>** Giriş" | +5.5 > +1.3 **DOĞRU** ✓ |

**Sonuç:** Tespit 10.1 (matematik ters) SADECE SELL yönünde geçerli. BUY yönünde mantık doğal çalışıyor.

**Kök neden (kesinleşti):** Kod `prim` değerini "yüksek=iyi" skalasında değerlendiriyor (long bias). BUY'da bu sezgisel (pozitif prim = kâr). SELL'de prim eksi skalaya döndüğünde "daha eksi = daha kârlı" olması gerekirken karşılaştırma operatörleri simetrik çevrilmiyor.

**Düzeltme (revize):** `abs(prim)` veya yön-farkında (direction-aware) karşılaştırma. Mutlaka BUY ve SELL için ayrı test path'i.

### 11.2 — Footer SL senkronizasyonu BUY'da da ÇALIŞIYOR ✓

PRIMNET footer SL 80.35 = MT5 sell stop limit 80.35 ✓ birebir.
TP 86.45 = MT5 sell limit 86.45 ✓ birebir.

**Sonuç:** Tespit 9 revizyonu BUY'da da onaylandı — senkronizasyon genelde çalışıyor, sadece trailing aktive anında snapshot timing farkı olabiliyor.

### 11.3 — Trailing grid BUY'da da 1.0 prim

Giriş +1.3, güncel +3.2 (2 tam prim kazanç yönünde ilerleme). Trailing stop +1.7'ye oturmuş = giriş − 1.5 offset değil, **ilk 1.0 prim'lik step tetiklenmiş** (giriş + 1 = +2.3'ü geçti → stop güncel − 1.5 = 1.7). Aynı grid mantığı.

**Sonuç:** Tespit 1 (grid 1.0 vs UI 0.1) SELL ve BUY'da ortak — sistemik.

### 11.4 — "SL" etiket yanıltıcılığı BUY'da daha az sorun

BUY pozisyonunda gerçek stop-loss **girişin altında** olmalı (80.35 < ~78.97 değil aslında 80.35 > giriş 78.97 yani stop aslında giriş üstünde). Bekle — burada stop 80.35 giriş 78.97'nin **ÜSTÜNDE**. Yani bu da profit-lock / trailing stop seviyesi (initial SL olmaktan çıkmış, trailing aktive olmuş).

BUY için:
- Initial SL (zarar tarafı): girişin ALTINDA (ör. 77.5)
- Trailing kâr stop: girişin ÜSTÜNDE (80.35 gibi)

Şu anki footer "SL: 80.35" = trailing stop. Aynı kavramsal karışıklık. Tespit 2 BUY'da da geçerli.

### 11.5 — Sistemik vs yön-özel tespit özeti

| Tespit | Sistemik mi? | BUY geçerli? | SELL geçerli? |
|---|---|---|---|
| T1 (grid uyumsuz) | ✓ Sistemik | ✓ | ✓ |
| T2 (SL etiketi) | ✓ Sistemik | ✓ | ✓ |
| T3 (TP tick snap) | ? Kontrol | TBD | ✓ |
| T4 (STOP SEV kolon) | ✓ Sistemik | ✓ | ✓ |
| T5 (eksik kademe) | ? Kontrol | TBD | ✓ |
| T6 (ondalık) | ✓ Sistemik | ✓ | ✓ |
| T8 (monotonic görselleştirme) | ✓ Sistemik | ✓ | ✓ |
| T9 (footer sync) | ✓ Sistemik | ✓ | ✓ |
| **T10.1 (matematik ters)** | ✗ **SELL-özel** | **YOK** | ✓ |
| T10.2-10.6 | Muhtemelen sistemik | TBD | ✓ |

**Anahtar bulgu:** T10.1 tek başına **yön-asimetrik** bug. Kod uzun/bias implementasyonu için yazılmış, short path'i eksik. Akşam düzeltmesi için en kritik mimari farkındalık bu.

**Dosya (tahmini):** `desktop/src/components/PrimnetDetail.jsx` AÇIKLAMA üretim fonksiyonu + ilgili backend hesap (muhtemelen `api/routes/hybrid_trade.py` response payload).

**Öncelik:** YÜKSEK — SELL pozisyonlarında kullanıcı matematik hatası görüyor (güven kaybı). BUY görünüşte iyi ama aynı bug gizli kalmış. Düzeltme yön-farkındalığı ile yapılmalı.

---

## Tespit 11 güncellemesi (anlık #10, F_AKBNK BUY fiyat yukarı)

**Anlık veri:**
- Güncel prim **+3.8** (fiyat 81.97), önceki +3.2'den yukarı
- K/Z **+995 TL**, MT5 kâr 975 TL → **20 TL fark** = 0.04 fiyat × 5 × 100 (bid/ask spread, Tespit 6 notu geçerli)
- Footer SL **80.75** (prim +2.3) — önceki 80.35'ten yukarı ✓ trailing ilerledi
- MT5 sell stop limit **80.75** ✓ footer ile **tam senkron**
- MT5 sell limit **86.45** = Footer TP 86.45 ✓
- Aktif satır: +3.8, "Stop +2.3 > Giriş → 1.0 prim kâr kilitli" ✓ matematik doğru

### 11.6 — KRİTİK DÜZELTME: Trailing "grid" değil, SÜREKLİ monotonic ratchet

Önceki analizde "trailing step = 1.0 prim" yazmıştım (F_KONTR gözleminden). Bu yanlış çıkardığım sonuçtu. Gerçek davranış:

| Gözlem | Güncel prim | Stop prim | Fark |
|---|---|---|---|
| Önceki F_AKBNK (#9 civarı) | +3.2 | +1.7 | 1.5 |
| Şimdi F_AKBNK (#10) | +3.8 | +2.3 | 1.5 |
| F_KONTR peak -4.0 | -4.0 | -2.5 | 1.5 |
| F_KONTR geri -2.7 | -2.7 | -2.5 (hold) | peak +1.5 |

**Doğru formül:** `stop = peak_prim ± 1.5` (BUY için −, SELL için +) **monotonic** (peak geriye gitmez).

Benim "1.0 grid" yorumum aslında monotonic ratchet'in görüntüsüydü: fiyat -3.4 ↔ -4.0 arasında salındığında stop -2.5'ten ayrılmıyordu çünkü peak -4.0'da kaldı, stop = peak + 1.5 = -2.5 sabit. Atlama değil, peak-tracking.

**Sonuç:**
- Tespit 1 revize: "UI grid 0.1 vs broker grid 1.0" **YANLIŞ**. Gerçek: UI grid 0.1 prim (teorik satırlar), broker sürekli 1.5 offset (peak-based monotonic). Uyumsuzluk hâlâ mevcut ama nedeni farklı.
- Tespit 8 güçlendi: Tablo "güncel satır için teorik stop" hesaplıyor, peak-tracking yapmıyor. Gerçek aktif stop tablonun dışında.
- Düzeltme akşam: Tabloya **peak_prim** çizgisi eklenmeli + "Aktif Stop = peak ∓ 1.5" göstergesi.

### 11.7 — TP 2 tick sapma BUY'da da doğrulandı (Tespit 3 sistemik)

- Tablo "+9.5 KAPAT" satırı: fiyat **86.47**
- Footer TP: **86.45**
- MT5 sell limit: **86.45**
- Fark: 2 tick (0.02 fiyat)

Teorik +9.5 prim = 78.97 × 1.095 = 86.472. Round/snap aşağı → 86.45 broker'da, 86.47 tabloda. Tespit 3 **sistemik ve yön-bağımsız** olarak kesinleşti.

### 11.8 — Footer SL senkronizasyonu BUY'da da tam sync (peak arttıkça)

Güncel +3.2 → +3.8 geçişi sırasında:
- Önceki SL 80.35 → yeni 80.75 (40 tick yukarı)
- Footer ve MT5 ikisi birden güncellendi, snapshot anında her iki taraf da 80.75 görüyor

**Sonuç:** trailing aktive iken `modify_position` çağrısı MT5 ve PRIMNET'i neredeyse eş zamanlı güncelliyor. Tespit 9'un ağırlığı "trailing aktivasyon anında geçiş boşluğu" olarak spesifik kaldı. Akşam log analizi bu geçişteki delay'i ölçecek.

### 11.9 — Prim → fiyat formülü F_AKBNK için farklı (yüzde tabanlı)

F_KONTR: 1 prim = 0.10 fiyat (sabit kademe, ref 10.16)
F_AKBNK: 1 prim ≈ 0.79 fiyat (yüzde tabanlı, ref 78.97; +1% = 1 prim)

Kontrol:
- +1.3 prim → 78.97 × 1.013 = **79.996** ≈ 80.00 ✓
- +3.8 prim → 78.97 × 1.038 = **81.97** ✓ birebir
- +9.5 prim → 78.97 × 1.095 = 86.47 (tabloda) ✓

**Anlamı:** "Prim" birimi kontrat-özel. F_KONTR'da fiyat-bazlı (0.10 tick), F_AKBNK'da yüzde-bazlı (%1). Bu mimari bilgi akşam düzeltmesinde kritik — UI'daki hesaplar kontrata göre farklı prim_to_price fonksiyonu kullanıyor olmalı.

**Not:** Giriş fiyat 79.96 (MT5) ≠ Tablo +1.3 satır fiyatı 80.00. Tablo round etmiş (+1.3 için teorik = 80.00). Gerçek giriş 79.96 primi = (79.96-78.97)/78.97×100 = 1.254 prim, round → +1.3 ✓. Kozmetik.

---

## Anlık #11 — Manuel kapanış (F_KONTR + F_ASELSA)

**Saat:** Kullanıcı manuel olarak F_KONTR SELL #8050576767 ve F_ASELSA pozisyonlarını kapattı. F_AKBNK BUY #8050573843 tek aktif pozisyon olarak kaldı.

**Gözlem için sonuçlar:**
- F_KONTR SELL'de T10.1 matematik ters bug'ının güncel ekran kanıtı **kaybedildi** (bugün için). Akşam kod okumayla yön-asimetri teyit edilecek.
- F_ASELSA PRIMNET ekranı hiç görülmedi — üçüncü kontrat prim formülü bilinmiyor. Yarınki pozisyonda yakalanmalı.
- F_AKBNK BUY tek canlı — peak geri dönüş (Tespit 8 BUY doğrulaması) hâlâ mümkün.

### 11.10 — Manuel kapanış BABA/kill-switch semantiği notu

Anayasa 4.4'te `_close_ogul_and_hybrid()` **manuel pozisyonlara dokunmaz**. Ama buradaki durum tersi: **kullanıcı** manuel olarak OĞUL+PRIMNET tarafındaki pozisyonları kapattı. Bu akşam kontrol edilecek soru:

- Kullanıcı manuel kapattığında OĞUL state machine bunu **CLOSED** olarak mı görüyor, yoksa "orphan" mı?
- PRIMNET hybrid tracker kapanışı algıladı mı? Yoksa kapanmış pozisyon hâlâ tracker'da aktif mi görünüyor?
- Engine sonraki cycle'da otomatik yeni SELL açmaya çalışırsa bu "kullanıcı müdahalesi ile çatışma" senaryosu — log'dan bakılmalı.

**Akşam log kontrolü (eklendi):**
- `ogul.py` pozisyon senkronizasyon log'ları — manuel kapanış sonrası tracker temizliği
- `h_engine.py` hybrid pozisyon listesi — kapatılmış pozisyon artıklara bakıldı mı
- Yeni sinyal üretimi 17:45 EOD'ye kadar engellendi mi, yoksa yeni SELL açıldı mı?

**Kanıt kaynağı:** `python .agent/claude_bridge.py tail_log` + `python .agent/claude_bridge.py positions` akşam çalıştırılacak.

---

## Tespit 12 — KRİTİK: Trailing "cancel + place" olarak implemente edilmiş (modify_position DEĞİL)

**Kaynak:** MT5 Günlük (Journal) canlı broker log kanıtı (anlık #12)

**Gözlem zinciri (F_AKBNK trailing 80.35 → 80.75 geçişi):**
```
cancel order sell stop limit 5 F_AKBNK0426 at 80.35  ← ESKİ SL iptal
accepted sell stop limit 5 F_AKBNK0426 at 80.75      ← YENİ SL yerleştirildi
order #... sell stop limit ... done in 163.705 ms
order #... sell stop limit ... done in 167.010 ms
```

**Problem:** Trailing adımında **modify_position (SL update)** değil, **cancel eski + place yeni** pattern'i çalışıyor. İki ayrı MT5 çağrısı.

**Tehlike analizi:**
- Cancel ile place arası mikro-pencerede **pozisyon SL'SİZ** kalıyor
- Her çağrı ~163-167 ms → toplam koruma boşluğu ~300 ms/trailing adım
- Piyasa flash move (slippage, news spike) tam bu pencerede olursa: pozisyon kontrolsüz açıkta
- Ne kadar sık trailing → ne kadar çok boşluk (güncel prim her 1 prim ilerlediğinde trailing tetikleniyor)

**Soru işaretleri (akşam araştırma):**
1. `engine/mt5_bridge.py modify_position()` (Siyah Kapı #19) gerçekten kullanılıyor mu?
2. Kullanılıyorsa neden MT5 log'da "cancel + place" görüyoruz?
3. `modify_position` VİOP'ta mümkün mü yoksa broker sadece "cancel + place" destekliyor mu?
   - Eğer broker kısıtlamasıysa → mimari zorunluluk, değiştirilemez. "Cooldown + retry" mantığı eklenmeli.
   - Değilse → `modify_position` kullanılmalı (atomic SL güncellemesi, boşluk yok).
4. Config'te `sltp_max_retries: 3` var — bu cancel+place sırasında place başarısız olursa ne oluyor?

**Anayasa referansı:**
- Anayasa Kural 4: "SL/TP Zorunluluk — korumasız pozisyon YASAK"
- Bu tespit Kural 4'ün **ms-seviye ihlali** olabilir (eğer modify_position kullanılmıyorsa)

**Log analizi planı (akşam, Barış Zamanı):**
```bash
python .agent/claude_bridge.py search_all_logs "modify_position"
python .agent/claude_bridge.py search_all_logs "send_order.*sell stop limit"
python .agent/claude_bridge.py search_all_logs "cancel order.*8050573843"
```

**Öncelik:** **EN YÜKSEK** — bu eğer gerçekten SL boşluğu yaratıyorsa Anayasa ihlali ve Kırmızı Bölge (mt5_bridge.py) düzeltmesi gerektirir. Ama önce kanıt şart — MT5 VİOP broker API'si `modify_position` desteklemiyor olabilir, o zaman implementasyon doğru.

**Dosya:**
- `engine/mt5_bridge.py` (Kırmızı Bölge, modify_position #19, send_order #17)
- `engine/h_engine.py` (Sarı Bölge, trailing çağıran taraf)

---

## Tespit 13 — Manuel kapanış kademeli fill (slippage kanıtı)

**Kaynak:** MT5 Günlük, F_KONTR manuel close detayı

**Gözlem:**
```
exchange buy 50 F_KONTR0426 at market, close #8050576767 sell 50 F_KONTR0426 9.87
deal #... buy 29 F_KONTR0426 at 9.81 done
deal #... buy  1 F_KONTR0426 at 9.81 done
deal #... buy  1 F_KONTR0426 at 9.81 done
deal #... buy  1 F_KONTR0426 at 9.81 done
... (toplam 50 lot, parça parça)
```

**Anlamı:** 50 lotluk market order **tek fiyattan dolmadı**. 29 + çok sayıda 1'lik parça. Derinlik yetersiz olduğunda VİOP'ta bu normal ama:

1. 50 lot gibi büyük pozisyonlar için **liquidity risk** var
2. Aynı fiyatta (9.81) doldu, yani aşırı slippage YOK bu seferlik — broker seviye seviye emdi
3. Ama piyasa hızlı hareket ederken aynı durum olursa her parça farklı fiyatta dolabilir

**Mevcut koruma:** `MAX_SLIPPAGE_ATR_MULT = 0.5` (config) → 0.5 × ATR'den fazla slippage'da emir reddedilir

**Soru:** Bu koruma **manuel close**'da da devrede mi? Yoksa manuel close direkt market order mı (slippage limiti yok)?

**Dosya:** `engine/mt5_bridge.py close_position()` (#18) + manuel close path'i kontrol

**Öncelik:** ORTA — liquidity risk sürekli olmayabilir ama büyük lot için kritik olabilir. Audit gerekli.

---

## Tespit 14 — Pending order orphan cleanup broker otomatik (iyi haber)

**Gözlem:** F_KONTR manuel close sonrası SL (buy stop limit 9.92) ve TP (buy limit 9.19) emirleri MT5 tarafında **otomatik cancel** edildi (pozisyon kapandı → yetim emir → broker otomatik temizlik).

Aynı pattern F_ASELSA'da da görüldü (sell stop limit 382.60 ve diğer pending'ler otomatik cancel).

**Sonuç:** Engine'in orphan cleanup yapmasına gerek yok, broker GCM Capital tarafı bu durumu kendisi yönetiyor. Mevcut kod için pozitif doğrulama.

**Not:** Farklı broker'larda (ya da VİOP yerine başka piyasa) bu otomatik cancel olmayabilir. Kod defansif olarak orphan cleanup yapıyorsa (hybrid_engine ve ogul'un orphan guard'ları) zaten güvende.

---

## Tespit 8 — CANLI KANIT (anlık #14, kullanıcı doğrudan sordu)

**Kullanıcı sorusu:** "Şuan sadece 18 TL mi kilitli kâr var?"
**Cevap:** HAYIR, **595 TL kilitli**. Tablo iki farklı yanlış değer gösteriyor.

**Tablo durumu (güncel prim +4.3, SL 81.15):**

| Satır | Gösterilen Kilitli | Aslında ne? |
|---|---|---|
| +4.3 (güncel, mavi) | +611 TL | Teorik: stop tam +2.8'de olsa. Broker 81.15'te (+2.76). Yaklaşık doğru ama 16 TL sapma |
| +2.8 (aktif stop, kırmızı) | **+18 TL** | **Tamamen teorik ve yanıltıcı**: "eğer güncel prim +2.8 olsaydı, stop +1.3'e düşerdi, kilitli ~0" projeksiyonu. Monotonic trailing'i yok sayıyor |

**Gerçek:**
- (SL 81.15 − Giriş 79.96) × 5 × 100 = **595 TL garanti**
- Peak +4.3 olduğu için stop +2.8'den geri gitmez (monotonic)
- Fiyat düşse bile +2.8 stop aynı yerde

**Kullanıcı tehlikesi:**
- Tablodaki "+18" değerine inanan kullanıcı garanti kârının çok azaldığını sanır → panik satış riski
- Tablodaki "+611" değerine inanan kullanıcı 16 TL fazla bekler → küçük ama sistemik güvensizlik
- Gerçek değer 595 TL sadece **manuel hesap** ile bulunabiliyor (SL footer + giriş fiyat)

**Akşam düzeltme — EN ÖNCELİKLİ (T12 ile birlikte):**
- PRIMNET footer'a **"Garanti Kâr: +595 TL"** satırı eklenmeli (hesap: `(SL − giriş) × lot × multiplier`)
- Ya da aktif stop satırı (kırmızı bantlı) "Kilitli" kolonu **gerçek garanti kâr** göstersin, teorik projeksiyon değil
- Teorik projeksiyon satırları varsa başlık veya renklendirmeyle net ayrılsın ("Bu olsaydı" dili)

**Dosya:**
- `desktop/src/components/PrimnetDetail.jsx` — aktif satır render koşulu + footer row
- `api/routes/hybrid_trade.py` — endpoint response'unda `guaranteed_profit_tl` field'ı eklensin (broker SL + giriş fiyatından)

**Bu anlık gözlem, Tespit 8'in saha kanıtıdır. Kullanıcı bizzat yanlış değerle yanıltıldı.**

---

## Anlık #15 — İKİ YENİ POZİSYON (F_KONTR SELL + F_ASELS SELL)

Kullanıcı F_AKBNK BUY devam ederken manuel olarak iki yeni SELL pozisyonu daha açtı.

### 15.1 — F_KONTR SELL #8050579236 (YENİ)

**Veriler:**
- Giriş prim -2.0 (fiyat 9.96), Lot 25
- Güncel prim -2.4 (fiyat 9.92), K/Z +100 TL (henüz trailing threshold altı)
- Footer SL **10.11** / TP **9.19** ← MT5 ile eşleşme bekleniyor
- Tablo aktif satır: -2.4 "TRAILING — stop -0.9"

**Problem (Tespit 9 canlı SELL):**
- Gerçek stop prim -0.5'te (10.11 = initial loss-stop, giriş üstünde 15 tick)
- Tablo "TRAILING - stop -0.9" diyor ama gerçekte henüz initial loss-stop (trailing aktive olmadı, kâr +0.4 prim < 1.5 eşiği)
- Kullanıcı yanlış stop seviyesi algılar

**Problem (Tespit 10.1 canlı SELL — BUY ile karşılaştırma):**
- F_KONTR -4.0 satırı: "Stop -2.5 **>** Giriş" ← aritmetik **yanlış** (-2.5 < -2.0)
- F_AKBNK +4.0 satırı: "Stop +2.5 **>** Giriş" ← aritmetik **doğru** (+2.5 > +1.3)
- Yön-asimetri bug'ı iki pozisyon canlı olarak yan yana kanıtlandı

### 15.2 — F_ASELS SELL #8050579260 (YENİ)

**Veriler:**
- Giriş prim +0.7 (fiyat 425.71), Lot 1
- Güncel prim +0.8 (hafif zarar -11 TL), henüz kâr yok
- Footer SL **431.95** / TP **382.60**
- Tablo: +0.7 GİRİŞ, +2.2 ZARAR DURDUR satırı stop +2.2

**Prim formülü — üçüncü kontrat, YÜZDE TABANLI:**
- Ref 422.75 × %1 = 1 prim (F_AKBNK ile aynı tip)
- SL 431.95 = 422.75 × 1.0218 → prim +2.18 (≈ giriş +0.7 + 1.5 prim → initial loss-stop)
- TP 382.60 = 422.75 × 0.9050 → prim -9.5 (hedef doğru)

**Tespit 11.9 genişleme — iki prim tipi doğrulandı:**

| Kontrat | Prim tipi | 1 prim = |
|---|---|---|
| F_KONTR | Fiyat-based | 0.10 fiyat (sabit tick) |
| F_AKBNK | Yüzde-based | %1 × ref |
| F_ASELS | Yüzde-based | %1 × ref |

Engine'de prim_to_price fonksiyonu kontrat-fark ında olmalı (muhtemelen kontrat profile'dan çekiyor). Akşam kod kontrolünde doğrulanacak.

### 15.3 — Her iki yeni pozisyonda trailing henüz aktive olmadı

F_KONTR SELL: kâr +0.4 prim < 1.5 eşiği → initial loss-stop 10.11 aktif
F_ASELS SELL: kâr -0.1 prim (hafif zarar) → initial loss-stop 431.95 aktif

Peak'e ulaşıldığında (güncel - giriş ≥ 1.5 prim kâr tarafı) trailing aktive olur, SL kâr tarafına geçer. Bu geçiş anlarını yakalamak T9/T12 için kritik kanıt üretecek.

### 15.4 — Canlı 3 pozisyon birlikte (akşam audit için ideal set)

| Kontrat | Yön | Durum | Prim tipi |
|---|---|---|---|
| F_AKBNK | BUY | Trailing aktif (SL 81.15, peak +4.3) | Yüzde |
| F_KONTR | SELL | Initial loss-stop (10.11), trailing bekliyor | Fiyat |
| F_ASELS | SELL | Initial loss-stop (431.95), trailing bekliyor | Yüzde |

Üç farklı durum + iki yön + iki prim tipi = sistemik tespitlerin ve yön-asimetri tespitlerinin **tam karşılaştırmalı setini** sağlıyor. Akşam auditor ajanı bu dosyayı referans aldığında her tespit için canlı kanıt var.

---

## Anlık #16 — Trailing aktive eşiği kavramı yanlışmış (önemli düzeltme)

Önceki gözlemlerde "trailing ≥1.5 prim kâr eşiğiyle aktive olur" dedim. Anlık #16'da bu **yanlışlandı**.

**Gözlem:**
- F_KONTR SELL: kâr primi +0.6 → SL 10.11'den 10.06'ya trailed (5 tick)
- F_ASELS SELL: kâr primi +0.4 → SL 431.95'ten 429.80'e trailed

**Doğru formül:** Trailing açılıştan itibaren her tick aktif. `stop = peak ± 1.5 prim` sürekli ve monotonic. "Henüz aktive olmadı" diye bir faz yok.

Initial SL = giriş ± 1.5 prim (açılışta sabit), sonra peak ilerledikçe SL peak'i 1.5 prim farkla takip ediyor. Kâr yönüne geçişi için peak − giriş ≥ 1.5 prim lazım (ki bu noktadan sonra SL giriş seviyesini geçip **gerçek garanti kâr** moduna girer).

**Tespit 9 revizyon (tekrar):** "Trailing aktive olmamış" durumu yok. Footer SL ve MT5 SL her zaman senkron, trailing her peak'te güncelleniyor. Tespit 9'un kalan ağırlığı sadece cancel+place arası ms-boşluk (Tespit 12 kapsamında birleşti).

### 16.1 — F_KONTR SELL durumu

- Giriş -2.0 (9.96), güncel -2.6 (9.90), peak ~-2.5
- Footer SL **10.06** = MT5 SL **10.06** ✓
- Stop seviyesi prim -1.0 (tablo "-1.1" gösteriyor, tick snap farkı 1 tick — Tespit 8 mini-kanıt)
- SL tetiklense: (9.96 − 10.06) × 25 × 100 = **-250 TL zarar**
- Trailing initial -500 TL'den -250 TL'ye geriledi (zarar küçülttü)

### 16.2 — F_ASELS SELL durumu

- Giriş +0.7 (425.71), güncel +0.3 (424.02), peak +0.3
- Footer SL **429.80** = MT5 SL **429.80** ✓
- SL tetiklense: (425.71 − 429.80) × 1 × 100 = **-409 TL zarar**
- Trailing initial -624 TL'den -409 TL'ye geriledi

### 16.3 — F_AKBNK BUY durumu (karşılaştırma)

- Giriş +1.3 (79.96), peak +4.3, güncel +4.0
- Footer SL **81.15** = MT5 SL **81.15** ✓
- SL tetiklense: **+595 TL kâr** (peak − giriş = 3.0 prim ≥ 1.5, kâr tarafına geçmiş)

### 16.4 — Kâr tarafına geçiş eşiği (T9 doğru yorumlaması)

Trailing "aktive olmuyor" değil, **kâr tarafına geçmiyor**. Peak − giriş ≥ 1.5 prim olduğunda SL giriş seviyesini aşar ve **gerçek garanti kâr** moduna geçer.

- F_KONTR SELL: peak -2.5, giriş -2.0 → fark 0.5 prim < 1.5 → henüz zarar tarafında SL, kâr kilitli **DEĞİL**
- F_ASELS SELL: peak +0.3, giriş +0.7 → fark 0.4 prim < 1.5 → henüz zarar tarafında SL
- F_AKBNK BUY: peak +4.3, giriş +1.3 → fark 3.0 prim ≥ 1.5 → kâr tarafına geçmiş ✓

**İzlemek için:** F_KONTR güncel prim -3.5'e inerse (peak -3.5'e ulaşır), stop -2.0'a (giriş seviyesi) gelir. Bir sonraki ilerleme ile kâr tarafına geçer. Bu geçiş anı UI ve MT5 açısından kritik test noktası.

### 16.5 — Tespit 12 tekrar kanıt (cancel+place)

MT5 Journal'da F_KONTR ve F_ASELS için trailing update'lerinde yeni "buy stop limit placed" emirleri görünüyor. Eski emir cancel + yeni place zinciri devam ediyor. Üç pozisyonda da aynı pattern → sistemik, broker-API seviye.

---

## Anlık #17 — F_AKBNK ikinci BUY pozisyonu (#8050580101)

Kullanıcı test amaçlı yeni F_AKBNK BUY açtı. İlk pozisyon (#8050573843) Journal'da hâlâ görünüyor, durumu net değil.

**Yeni pozisyon:**
- Giriş prim +3.3 (81.60), Lot 5
- Footer SL 80.40 / TP 86.45 ✓ MT5 birebir sync
- Initial SL = giriş − 1.5 prim = 80.39 teorik, broker 80.40 (1 tick snap — Tespit 3 formu)
- K/Z -25 TL (spread + komisyon)

**YENİ SORU (Tespit 15 kandidatı):** VİOP netting sisteminde aynı sembolde iki aynı yön pozisyon olur mu? Yoksa netleşip tek net pozisyona mı birleşir? MT5 Journal'daki her iki ID de görünüyor ama PRIMNET UI paneli iki ayrı tab mı, yoksa tek netted mi?

**Kontrol planı (akşam log):**
- `get_positions()` çıktısında F_AKBNK kaç pozisyon?
- Aynı sembolde parallel BUY'lar PRIMNET'te ayrı ayrı mı render ediliyor?
- `ogul.py` tracker'da iki pozisyon olarak mı yoksa tek netted mi?
- Netting davranışı Anayasa Kural 4.15 kapsamında (MT5 başlatma koruması) belirtilmemiş — doğrulanmalı

**İzleme değeri:** Kullanıcının test pozisyonu netting davranışını gözlemleme fırsatı. Akşam `database.py` işlem kayıtlarından iki ID'nin nasıl tutulduğu kontrol edilmeli.

---

## Anlık #18 — F_KONTR SELL PRIMNET_SL ile kapandı (12:03)

**PRIMNET Olay Geçmişi sırası:**
- 11:34 TRANSFER: Giriş 9,96 | Lot 25 | SL 10,11 | TP 9,19
- 11:34 PRIMNET_DAILY_RESET: 10,11 → 10,11 (değişiklik yok)
- 11:34 TRAILING_UPDATE: 10,11 → 10,06 (peak 9,91 görüldü, stop = 9,91 + 0,15 = 10,06)
- 12:03 TRAILING_UPDATE: 10,06 → 10,06 (monotonic hold)
- 12:03 CLOSE: SOFTWARE_SL | K/Z −250,00

**Matematik doğrulama:**
- Çıkış 10,06 − Giriş 9,96 = 0,10 fark × 25 lot × 100 çarpan = **250 TL kayıp** ✓
- Peak sadece +0,5 prim kârdaydı → profit-lock (+1,5) eşiğine ulaşmamıştı → stop hâlâ kayıp tarafında kaldı → bu **doğru monotonic davranış**, bug değil

**MT5 Journal (T12 canlı kanıt):**
- 12:02:58 `cancel buy stop limit 25 F_KONTR0426 at 10.06` (SL pending iptal)
- 12:03:00 `cancel buy limit 25 F_KONTR0426 at 9.19` (TP pending iptal)
- Kapanış anında yoğun cancel/place trafiği → Tespit 12 (cancel+place SL gap) riskinin canlı izi

**Sistemik değerlendirme — PROBLEM VAR MI?**

Motor doğru çalıştı:
- Trailing peak-tabanlı monotonic hareket etti ✓
- SOFTWARE_SL doğru tetiklendi ✓
- K/Z hesabı matematik olarak tutuyor ✓
- Event history temiz kayıt ✓ (TRANSFER → DAILY_RESET → TRAILING_UPDATE × 2 → CLOSE)

**Ama izlenmesi gereken (akşam log analizi):**
- Kapanış anındaki cancel/place sırasında SL yoksunluk anı oldu mu?
- `search_all_logs "F_KONTR.*8050" --from 12:02:30 --to 12:03:30` → her emir adımını tarayıp ~300ms SL-gap'in bu işlemde materialize olup olmadığı kontrol edilmeli
- Peak +0,5 primdeydi, profit-lock aktif değildi → bu işlemde kâr kaybı olmadı. Ama aynı pattern profit-lock zamanında olsaydı cancel+place sırasında gap riski artardı

**Sonuç:** Bu kapanışta kullanıcıya zarar veren bir davranış yok. Sistem planlandığı gibi işledi. T12 teorik riski hâlâ geçerli, kapanış bu riskin canlı örneği değil ama yoğun cancel/place trafiği T12'nin akşam düzeltilmesi gerekliliğini teyit ediyor.

---

## Anlık #19 — F_ASELS SELL #8050579260 vs F_AKBNK BUY #8050580101 yan yana (Tespit 10.1 kesin kanıt)

İki pozisyon aynı anda yan yana açık; aynı PRIMNET tablosu farklı yönlerde nasıl render ediyor karşılaştırıldı. Bu **Tespit 10.1'in kesin kanıtı** — SELL AÇIKLAMA formülleri BUY mantığıyla yazılmış.

### F_ASELS SELL #8050579260 snapshot

- Giriş prim +0.7 (425.71), güncel +0.2 (423.60), K/Z +215 TL
- Footer SL 429.80 (prim ≈ +1.67), TP 382.60
- Ref 422.75; 1 prim ≈ 4.23 TL (percent-based)
- Peak prim ≈ +0.17 → stop = peak + 1.5 = +1.67 ✓ formül tutuyor
- MT5 sell 1 @ 425.60 ≈ PRIMNET 425.71 ✓ birebir (snapshot timing farkı)

**SELL AÇIKLAMA problemleri:**

| Prim | Tablo AÇIKLAMA | Gerçek | Durum |
|---|---|---|---|
| +0.7 GİRİŞ | `Stop: -0.8 (-1.5 prim)` | SELL'de SL giriş+1.5 = **+2.2** | ❌ YANLIŞ YÖN |
| +0.2 TRAILING | `Stop +1.7 < Giriş → Kilitli kâr yok` | SELL'de +1.7 giriş+0.7'nin ÜSTÜ (kayıp) | ❌ Karşılaştırma TERS |
| 0.0 TRAILING | `Stop +1.5 < Giriş` | +1.5 > +0.7 | ❌ |
| −1.0 KÂR KİLİTLİ | `Stop +0.5 > Giriş → 0.2 prim kâr kilitli` | Değer doğru ama karşılaştırma mantığı ters | ⚠ |
| −3.0 KÂR KİLİTLİ | `Stop -1.5 > Giriş → 2.2 prim kâr kilitli` | İşaret ve yön mantığı BUY için yazılmış | ❌ |

### F_AKBNK BUY #8050580101 snapshot (aynı anda)

- Giriş +3.3 (81.60), güncel +3.3 (81.58), K/Z -30 TL (henüz hareket yok)
- Footer SL 80.40 (prim +1.8), TP 86.45, Lot 5
- MT5 buy 5 @ 81.60 ✓ + sell stop limit 80.40 ✓ + buy limit 86.45 ✓ birebir

**BUY AÇIKLAMA kontrolü:**

| Prim | Tablo AÇIKLAMA | Gerçek | Durum |
|---|---|---|---|
| +3.3 GİRİŞ | `Stop: +1.8 (-1.5 prim)` | BUY'da SL giriş-1.5 = +1.8 | ✓ |
| +4.0 TRAILING | `Stop +2.5 < Giriş → Kilitli kâr yok` | +2.5 < +3.3 TRUE, kâr yok | ✓ |
| +5.0 KÂR KİLİTLİ | `Stop +3.5 > Giriş → 0.2 prim kâr kilitli` | +3.5 > +3.3 TRUE | ✓ |
| +9.0 KÂR KİLİTLİ | `Stop +7.5 > Giriş → 4.2 prim kâr kilitli` | Tutarlı | ✓ |

### Kök neden hipotezi (akşam doğrulanacak)

`desktop/src/components/PrimnetDetail.jsx` (veya benzer) AÇIKLAMA render mantığı:
- Karşılaştırma ve işaret hesapları `direction === 'BUY'` kontrolü olmadan yazılmış
- SELL için hem yön hem karşılaştırma sembolü ters çevrilmeli
- Muhtemel fix: Stop-giriş diff hesabında `sign = (direction === 'BUY') ? 1 : -1` faktörü uygulanmalı

### Motor vs UI ayrımı (önemli)

- **Motor seviyesi:** İki pozisyon da matematik olarak doğru çalışıyor. Stop formülü, trailing, broker sync hepsi tutuyor. Kullanıcıya finansal zarar yok.
- **UI seviyesi:** SELL AÇIKLAMA yanıltıcı. Kullanıcı AÇIKLAMA kolonuna güvenip pozisyonu yanlış yorumlayabilir (örn: "stop -0.8'de" derken gerçekte +1.67'de).

**Öncelik:** Orta. Motor çalışıyor ama UI yanılgıyı besliyor. Akşam Barış Zamanı'nda `PrimnetDetail.jsx` içinde yön kontrolü eklenecek.

---

## Anlık #20 — F_ASELS peak hareketi, trailing update gecikmesi (Tespit 16 kandidatı)

**F_ASELS SELL #8050579260 zaman serisi:**

| Zaman | Güncel | Kâr primi | Footer SL | Teorik stop (peak+1.5) | Sapma |
|---|---|---|---|---|---|
| #17 | +0.2 | +0.5 | 429.80 (+1.67) | +1.67 | 0 ✓ |
| #20 | −0.3 | +1.0 | 429.80 (+1.67) | +1.2 | **+0.47 prim sapma** ⚠ |

**Gözlem:** Peak prim +0.17'den −0.3'e ilerledi (kâr +0.5 → +1.0), ama Footer SL hareket etmedi. Teorik stop +1.2'de olmalıydı, broker hâlâ +1.67'de.

**İki olasılık:**
- (a) Trailing event bir sonraki 10sn döngüde gelecek → geçici gecikme, kabul edilebilir
- (b) Trailing kademeli update ediyor (örn. her tam 1 prim peak değişiminde bir update) → Anlık #16 "immediate trailing" düzeltmesi yeniden gözden geçirilmeli

**Akşam kontrol planı:**
```
search_all_logs "F_ASELS.*8050579260.*trailing"
search_all_logs "F_ASELS.*8050579260.*cancel"
```
Her trailing_update event zamanı + cancel/place pattern çıkarılmalı. `engine/h_engine.py` içinde trailing trigger threshold var mı (örn. `if abs(peak_change) >= 1.0: update`) bakılacak.

**Önemli — finansal risk değerlendirmesi:**
- Kullanıcıya ek risk **yok**: Stop daha "kötü" (giriş'e daha uzak kayıp tarafında) değil, daha "iyi" pozisyonda olabilecekken eski yerinde duruyor. Yani KORUMASIZ pozisyon riski YOK.
- Kilitli kâr riski **var**: Peak dönerse (fiyat yukarı giderse) teorik +1.2 stop tetiklenirdi, gerçek +1.67 stop daha geç tetiklenecek. Yani kâr küçük miktarda erozyona uğrayabilir.

**Tespit 10.1 canlı devam:** Aynı snapshot'ta SELL AÇIKLAMA "−0.3 TRAILING: Stop +1.2 < Giriş → Kilitli kâr yok" — karşılaştırma sembolü `<` hâlâ yanlış yönlü, `>` olmalı. Kanıt tekrar.

### F_AKBNK BUY #8050580101 kontrast (aynı anda)

- Güncel +3.2 < giriş +3.3 → BUY'da peak güncellemesi YOK → stop initial +1.8'de kalır ✓
- "+3.2 AÇIK: Stop +1.8'da" tablo-footer-broker tümüyle tutarlı ✓
- BUY mantığı sorunsuz, Tespit 16 sadece SELL'de tetiklenmiş görünüyor (ya da henüz BUY trailing'e girmedi — peak giriş'i aşmadı)

**Tespit 16 düzeltme önceliği (akşam):** Log analizi sonucu belirleyecek. Eğer (a) geçici gecikme ise kabul edilebilir, düzeltme GEREKMEZ. Eğer (b) threshold-based ise Anlık #16 düzeltmesi revize edilecek ve mantık `engine/h_engine.py` içinde netleştirilecek.

---

## Anlık #21 — FAZ 1 LOG ANALİZİ SONUÇLARI (Barış Zamanı, kullanıcı beyanı)

**Kaynak:** `logs/ustat_2026-04-14.log` (683.965 satır)

### T1 KESİN DOĞRULANDI — Grid 0.5 prim, UI teorik gösteriyor

Log satırı: `engine.h_engine:__init__:173 - PRİMNET (trailing=1.5, adım=0.5, hedef=±9.5)`

`_calc_primnet_trailing_sl` her döngüde iki değer üretiyor:
- `stop_raw`: sürekli (peak + 1.5)
- `stop_step`: 0.5 prim grid'e snap edilmiş

Örnek: `stop_raw=0.80 → stop_step=1.17 → SL=427.70` ... `stop_raw=0.65 → stop_step=0.67 → SL=425.60`

**Sonuç:** Motor **grid kullanıyor**, UI tablosu teorik sürekli render ediyor → uyumsuzluk. UI `stop_step` değerini göstermeli.

### T12 KESİN KANIT — ~10 saniye SL-gap

Her trailing update patronu:
```
T+0    modify_pending_order çağrılır (ticket=X)
T+0.2  modify deneme 1/3 başarısız retcode=10006
T+0.7  modify deneme 2/3 başarısız
T+1.5  modify deneme 3/3 başarısız → ERROR
T+1.6  [8-9 saniye bekleme — sonraki döngü]
T+10   cancel_pending_order
T+10.3 cancel başarılı
T+10.5 send_stop_limit (yeni emir)
T+10.7 yeni emir başarılı
```

**Toplam SL-gap: ~10 saniye.** Broker (GCM) pending order modify'ı retcode 10006 (INVALID_REQUEST) ile red ediyor. Sonra cancel+place'e düşüyor.

**Anayasa Kural 4 (SL/TP zorunluluk) ihlali** — pozisyon bu 10 saniye korumasız.

**Çözüm önerisi (Faz 4):**
1. modify çağrısını kaldır (her zaman fail oluyor)
2. Sıra: **Önce yeni stop emri gönder**, sonra eskisini iptal et
3. İki stop aynı anda ~300ms (yeni yerleşir yerleşmez eski iptal)
4. SL-gap: ~0 saniye

### T16 ÇÖZÜLDÜ — Bug değil, grid snap tasarımı

Anlık #20'deki "gecikme" aslında 0.5 prim grid snap. Peak değişim tam 0.5'i aşmadan `stop_step` aynı kademede kalıyor. Örnek:
- Peak -0.33 → stop_raw 1.17 → stop_step 1.17 ✓
- Peak -0.50 → stop_raw 1.00 → stop_step 1.17 (aynı kademe)
- Peak -0.85 → stop_raw 0.65 → stop_step 0.67 (bir alt kademe)

**Bu tasarım gereği**, bug değil. T1 düzeltmesi UI tarafında bu grid'i gösterince T16 de çözülür.

### T13 ÇÖZÜLDÜ — Manuel close retry zaten çalışıyor

Log kanıt (F_KONTR #8050570106):
- 10:19:23 close deneme 1/3 → retcode=10019 "No money"
- 10:19:34 close deneme 2/3 → BAŞARILI (pnl=1512.00)

Retry mekanizması düzgün, **SKIP**.

### T15 ÇÖZÜLDÜ — İki F_AKBNK BUY ayrı ID olarak tutuluyor

Log kanıt:
- `transfer_to_hybrid: ticket=8050573843 F_AKBNK BUY SL=78.80 TP=86.45` (09:41)
- `transfer_to_hybrid: ticket=8050580101 F_AKBNK BUY SL=80.40 TP=86.45` (11:55)

Her biri kendi `trail_order` + `tgt_order` ile ayrı tracker'da. VİOP netting MT5 API seviyesinde ama sistem iki ayrı position ID görüyor. PRİMNET UI iki ayrı tab olarak açabilmeli (kontrol edilecek).

### Yeni Tespit: Orphan comment arama spam log

`_find_orders_by_comment` çağrılarında "TRL_X F_X eşleşme yok" uyarıları. DEBUG seviyesinde ama yoğun. Fonksiyon kapanmış pozisyon için trail/tgt emir arıyor olabilir. Faz 2'de koda bakılıp garbage collection eklenmeli.

### Revize edilmiş Faz 3-4 öncelik sırası

| Öncelik | İş | Faz |
|---|---|---|
| **P0** | T12: Önce-yeni-sonra-eski sırası (SL-gap 10s → 0s) | Faz 4 (Kırmızı) |
| **P0** | T8: Tablo kilitli kâr monotonic (peak-based) | Faz 3 (Yeşil) |
| **P1** | T1: UI'da `stop_step` değerini göster (grid 0.5) | Faz 3 |
| **P1** | T10.1: SELL AÇIKLAMA yön çarpanı | Faz 3 |
| **P2** | T2, T4, T5, T6, T9, T3: UI netlik paketi | Faz 3 |
| **P3** | Orphan comment log temizliği | Faz 4 |
| **SKIP** | T7, T13, T14, T15, T16: Zaten çalışıyor veya tasarım | — |

---

## Bu dosyanın statüsü

- Oluşturulma: 14 Nisan 2026, piyasa açıkken (Savaş Zamanı, gözlem)
- Son güncelleme: 14 Nisan 2026
- Yeni gözlemler geldikçe **bu dosya güncellenecek** — kullanıcı talebi
- Akşam 18:15'te bu dosyaya **son durum** eklenecek, düzeltme planı çekirdeği buradan çıkacak
- Düzeltmeler tamamlanınca → `docs/USTAT_GELISIM_TARIHCESI.md`'ye giriş + ayrı session raporu
