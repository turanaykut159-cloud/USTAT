# ÜSTAT v5.0 — Kapsamlı Analiz ve İyileştirme Raporu

**Tarih:** 2026-03-01  
**Kapsam:** Tüm modüller (Dashboard, İşlem Paneli, İşlem Geçmişi, Açık Pozisyonlar, Performans Analizi, Risk Yönetimi, Ayarlar, Üst Bar, Yan Menü)  
**Referans:** Ekran görüntüleri (Dashboard, İşlem Paneli, Açık Pozisyonlar, Performans, İşlem Geçmişi, Risk Yönetimi, Ayarlar) + kod incelemesi

---

## ADIM 2: MODÜL MODÜL DERİN İNCELEME (Özet)

### Dashboard
- **Veri tutarlılığı:** "Toplam İşlem" kartında büyük sayı günlük işlem (daily_trade_count), alt metin "bugün — Toplam: 10" ile toplam işlem karışabiliyor; kart başlığı "Toplam İşlem" günlük değeri vurguladığı için yanıltıcı.
- **Metrik penceresi:** Başarı oranı ve Net K/Z `getTradeStats()` (limit 500), Profit Factor `getPerformance(30)` ile geliyor; farklı zaman pencereleri aynı satırda.
- **Görsel:** Rejim badge, Top 5 çubukları ve dir-badge’ler tema ile uyumlu; açık pozisyonlar tablosu footer toplamı doğru.

### İşlem Paneli
- **Boş durum:** Risk Özeti için "Sembol ve yön seçip 'Kontrol Et' tıklayın" metni net.
- **BUY/SELL:** Seçim sonrası `active-buy` / `active-sell` ile renk ayrımı var; seçim yokken iki buton da nötr, kullanıcı hangi adımda olduğunu anlayabiliyor.
- **Risk özeti:** Kontrol sonrası rejim, günlük işlem, equity, lot çarpanı vb. gösteriliyor; para birimi "TL" sabit (API’den gelen currency kullanılmıyor).

### İşlem Geçmişi
- **Hızlı erişim:** "↑ En Kârlı", "↓ En Zararlı", "⏱ En Uzun", "⚡ En Kısa" — ilk üçü ok/saat ikonu, sonuncu şimşek; ikon seti tutarsız.
- **"Maks. Ardışık Kayıp":** Değer (örn. 2) işlem sayısı; etiket "Maks. Ardışık Kayıp" tek başına birim belirtmiyor, "2 işlem" gibi açıklama yok.
- **Onayla / ✓:** Onaylanmamış satırda "Onayla", onaylıda yeşil ✓; davranış tutarlı.

### Açık Pozisyonlar
- **Süre formatı:** `elapsed()` çıktısı "1g 22s" — burada "s" saat (saat); kullanıcı "saniye" okuyabilir, kısaltma belirsiz.
- **Çift özet:** Üst bar ve sayfa altındaki op-info-bar’da Bakiye/Equity/Floating tekrarlanıyor; bilinçli tasarım ama tek yerde toplanabilir veya etiketler netleştirilebilir.

### Performans Analizi
- **X ekseni:** Equity/Drawdown grafiklerinde tarih etiketleri sık tekrarlanabiliyor ("01.03" çok kez); nokta sayısı fazlaysa tick sıkışıyor.
- **Sharpe 0.00:** Az veri veya sıfır volatilite ile 0.00 mantıklı; kullanıcı için kısa açıklama/tooltip yararlı olur.
- **Dönem butonları:** 1 Ay / 3 Ay / 6 Ay / 1 Yıl ve 30/90/180/365 gün eşlemesi doğru.

### Risk Yönetimi
- **Günlük/Haftalık drawdown:** API `/api/risk` yanıtında `daily_drawdown_pct` ve `weekly_drawdown_pct` doldurulmuyor (sadece `total_drawdown_pct` snapshot’tan geliyor); UI’da bar 0/limit gösteriyor veya fallback kullanılıyor.
- **Sihirli sayı:** Günlük/Floating kayıp fallback’inde `12389` (tahmini equity) sabit; doğru hesaplama için gerçek equity (hesap/risk yanıtı) kullanılmalı.
- **Terminoloji:** Üst bar "FAZ 1", Risk sayfası "L1 — Kontrat Dur"; aynı kavram farklı isimle.

### Ayarlar
- **Risk parametreleri:** Salt okunur ve config referansı doğru.
- **Hard Drawdown:** Kırmızı vurgu kritik limit için uygun; para birimi (TRY) diğer ekranlarla tutarlı kullanılabilir.

### Üst Bar
- **Faz/Kill-Switch:** "FAZ 1" ile Risk’teki "L1" aynı seviyeyi ifade ediyor; terim birleştirilebilir veya tooltip ile açıklanabilir.
- **Günlük K/Z / Floating:** Değerler `getAccount()` ile güncelleniyor; Dashboard’daki "Net Kâr/Zarar" (kapanan işlemler toplamı) ile farkı etiketle netleştirmek faydalı.

### Yan Menü (SideNav)
- **Kill-Switch:** 2 sn basılı tutma ve ilerleme çubuğu net; navigasyon öğeleri ve aktif durum tutarlı.

---

## ADIM 3–5: İYİLEŞTİRME KARTLARI

---

═══════════════════════════════════════════════════════
İYİLEŞTİRME #1
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/Dashboard.jsx → StatCard kullanımı (satır ~165–172)
📂 MODÜL: Dashboard
🏷️ KATEGORİ: UI/UX
⚡ ÖNCELİK: ORTA

🔍 MEVCUT DURUM:
İlk stat kartı label="Toplam İşlem", sublabel="bugün", value=status.daily_trade_count, total=stats.total_trades ile render ediliyor. Büyük sayı günlük işlem, alt satır "bugün — Toplam: {total}". Başlık "Toplam İşlem" olduğu için kullanıcı büyük sayının "toplam" mı "günlük" mü olduğunu karıştırabilir.

❌ SORUN / EKSİKLİK:
Kart başlığı ile gösterilen değer uyuşmuyor: başlık "Toplam İşlem", değer ise günlük işlem sayısı. Ekran görüntüsünde "0" ve "bugün — Toplam: 10" birlikte görününce anlam belirsizleşiyor.

✅ ÖNERİLEN DEĞİŞİKLİK:
İlk kartın label'ını "Günlük İşlem" veya "Bugünkü İşlem" yap; sublabel'da "Toplam: X" ifadesini koru. Böylece büyük sayı = bugünkü işlem, alt metin = tüm zamanlar toplamı net olur.

📊 FAYDA:
Kullanıcı tek bakışta "bugün 0 işlem, toplam 10 işlem" olduğunu anlar; yanlış yorumlama azalır.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/Dashboard.jsx
- Yan etki riski: Yok
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Kolay (tek metin değişikliği)

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅

📝 NOT: Sadece label metni değişir; API/state değişmez.

═══════════════════════════════════════════════════════
İYİLEŞTİRME #2
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/Dashboard.jsx → fetchAll (getTradeStats, getPerformance)
📂 MODÜL: Dashboard
🏷️ KATEGORİ: Fonksiyonel / Veri tutarlılığı
⚡ ÖNCELİK: DÜŞÜK

🔍 MEVCUT DURUM:
Dashboard üst satırda dört kart: Toplam (günlük) işlem, Başarı Oranı, Net K/Z, Profit Factor. getTradeStats() ile total_trades, win_rate, total_pnl; getPerformance(30) ile profit_factor alınıyor. Yani Başarı Oranı ve Net K/Z (varsayılan limit 500) işlem penceresine, Profit Factor 30 günlük performans penceresine ait.

❌ SORUN / EKSİKLİK:
Aynı satırdaki metrikler farklı zaman/limit pencerelerinden geliyor. Kullanıcı hepsini "genel" veya "son 30 gün" sanabilir; karar verirken yanıltıcı olabilir.

✅ ÖNERİLEN DEĞİŞİKLİK:
(1) getPerformance(30) zaten çağrılıyorsa, Başarı Oranı ve Net K/Z için de aynı 30 günlük pencereden türetilmiş değerleri kullan: perf.win_rate, perf.total_pnl (PerformanceResponse’ta mevcut). Veya (2) UI’da küçük bir not/tooltip ekle: örn. "Son 30 gün" / "Son 500 işlem" gibi.

📊 FAYDA:
Metrikler tek zaman penceresine referans verir; raporlama ve karar alma tutarlı hale gelir.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/Dashboard.jsx; isteğe bağlı api/schemas.py (ek alan)
- Yan etki riski: Düşük (sadece hangi veri kaynağının gösterildiği)
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Kolay

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅ (boş perf/stats fallback’leri mevcut)

📝 NOT: Performans API’si zaten win_rate, total_pnl döndürüyor; Dashboard’da kaynak seçimi veya etiket netleştirmesi yeterli.

═══════════════════════════════════════════════════════
İYİLEŞTİRME #3
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/TradeHistory.jsx → th-quick-btns (satır ~354–383)
📂 MODÜL: İşlem Geçmişi
🏷️ KATEGORİ: UI/UX
⚡ ÖNCELİK: KOZMETİK

🔍 MEVCUT DURUM:
Dört hızlı erişim butonu: "↑ En Kârlı", "↓ En Zararlı", "⏱ En Uzun", "⚡ En Kısa". İlk üçü ok ve saat ikonu, sonuncu şimşek. Ekran görüntüsünde "⚡ En Kısa" diğerlerinden farklı ikon ailesi kullanıyor.

❌ SORUN / EKSİKLİK:
İkon seti tutarsız; "En Kısa" için de süre ile ilgili tek tip bir ikon (örn. ⏱ veya benzeri) kullanılabilir veya dördü de metin/ok ile tutarlı hale getirilebilir.

✅ ÖNERİLEN DEĞİŞİKLİK:
"⚡ En Kısa" butonundaki ikonu "⏱" veya "⌛" gibi süre temalı bir karakterle değiştir; buton stilini diğerleriyle aynı bırak. Veya dördünde de sadece ok/tek ikon kullan (↑ ↓ ⏱ ⏱ veya ↑ ↓ ↑ ↓ gibi).

📊 FAYDA:
Görsel tutarlılık; kullanıcı tüm butonların aynı aileden olduğunu algılar.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/TradeHistory.jsx
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
İYİLEŞTİRME #4
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/TradeHistory.jsx → Risk paneli PanelRow "Maks. Ardışık Kayıp" (satır ~358)
📂 MODÜL: İşlem Geçmişi
🏷️ KATEGORİ: UI/UX
⚡ ÖNCELİK: ORTA

🔍 MEVCUT DURUM:
PanelRow label="Maks. Ardışık Kayıp" value={maxConsecLosses}. maxConsecLosses ardışık kayıp işlem sayısı (tam sayı). Ekranda sadece "2" gibi görünüyor.

❌ SORUN / EKSİKLİK:
"Maks. Ardışık Kayıp" değeri işlem sayısı; birim belirtilmediği için kullanıcı "2"yi 2 işlem mi, %2 mi, 2 gün mü diye yorumlayabilir (ekran görüntüsü açıklamasında da belirsizlik geçiyor).

✅ ÖNERİLEN DEĞİŞİKLİK:
Değeri "2 işlem" veya "2" + tooltip "Ardışık kayıp işlem sayısı" şeklinde göster. Örn: value={`${maxConsecLosses} işlem`} veya aynı satırda küçük gri "işlem" etiketi ekle.

📊 FAYDA:
Anlam tek; kullanıcı sayının neyi ifade ettiğini bilir.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/TradeHistory.jsx
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
İYİLEŞTİRME #5
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/OpenPositions.jsx → elapsed() (satır ~39–54)
📂 MODÜL: Açık Pozisyonlar
🏷️ KATEGORİ: UI/UX
⚡ ÖNCELİK: ORTA

🔍 MEVCUT DURUM:
elapsed() çıktıları: "Xdk", "Xs Xdk", "Xg Xs" (dakika, saat+dakika, gün+saat). "s" burada saat (saat) kısaltması; kodda `${h}s` kullanılıyor. Ekran görüntüsünde "1g 22s" ifadesi "1 gün 22 saat" anlamında; kullanıcı "22 saniye" okuyabilir.

❌ SORUN / EKSİKLİK:
Türkçe’de "s" yaygın olarak saniye için kullanılıyor; "saat" için "st" veya "sa" daha net. Yanlış okuma süre algısını bozar.

✅ ÖNERİLEN DEĞİŞİKLİK:
Saat kısaltmasını "st" veya "sa" yap: örn. "1s 49dk" → "1st 49dk", "1g 22s" → "1g 22st". Tüm elapsed çıktılarında aynı kısaltmayı kullan; TradeHistory.jsx formatDuration() içinde de aynı kuralı uygula (varsa).

📊 FAYDA:
Süre birimi netleşir; "saniye" ile "saat" karışmaz.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/OpenPositions.jsx; desktop/src/components/TradeHistory.jsx (formatDuration)
- Yan etki riski: Düşük (sadece string format)
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
İYİLEŞTİRME #6
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/RiskManagement.jsx → RiskBar Günlük Kayıp / Floating Kayıp (satır ~154–176)
📂 MODÜL: Risk Yönetimi
🏷️ KATEGORİ: Fonksiyonel / Kod kalitesi
⚡ ÖNCELİK: YÜKSEK

🔍 MEVCUT DURUM:
Günlük Kayıp: current={risk.daily_drawdown_pct || (risk.daily_pnl < 0 ? Math.abs(risk.daily_pnl) / 12389 : 0)}. Floating Kayıp: current={risk.floating_pnl < 0 ? Math.abs(risk.floating_pnl) / 12389 : 0}. 12389 sabit bir sayı (tahmini equity); gerçek equity API’den gelmiyor.

❌ SORUN / EKSİKLİK:
Magic number 12389 farklı hesaplarda yanlış drawdown yüzdesi üretir. Equity değiştikçe (örn. 13.545) oran yanlış olur; ayrıca API’de daily_drawdown_pct zaten doldurulmuyor (api/routes/risk.py sadece total_drawdown_pct alıyor).

✅ ÖNERİLEN DEĞİŞİKLİK:
(1) API’den hesap bilgisi veya risk yanıtına equity/bakiye ekleyin; frontend’de 12389 kullanmayın. (2) Günlük drawdown için: risk.daily_drawdown_pct varsa onu kullan; yoksa (risk.daily_pnl < 0 && risk.equity > 0) ise Math.abs(risk.daily_pnl) / risk.equity. (3) risk.equity RiskResponse’ta yoksa getAccount() veya getRisk() ile equity’yi alıp state’te tutun ve bu hesaplamada kullanın. (4) 12389 sabitini koddan tamamen kaldırın.

📊 FAYDA:
Doğru drawdown yüzdesi; farklı bakiye/equity’lerde doğru limit karşılaştırması.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/RiskManagement.jsx; isteğe bağlı api/schemas.py (RiskResponse’a equity), api/routes/risk.py (equity doldurma)
- Yan etki riski: Orta (risk API/şema değişirse)
- MT5 etkisi: Yok (sadece mevcut API verisi kullanımı)
- Canlı işlem riski: Yok
- Geri dönüş: Orta (fallback eski davranışa bırakılabilir)

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅ (equity 0 veya null’da bölme yapmamak)

📝 NOT: Risk route’unda db.get_latest_risk_snapshot() ile gelen veride daily_drawdown_pct/weekly_drawdown_pct backend’de hesaplanıp doldurulursa UI sadece bu alanları kullanabilir; fallback yine equity ile yapılmalı, 12389 olmamalı.

═══════════════════════════════════════════════════════
İYİLEŞTİRME #7
═══════════════════════════════════════════════════════

📍 KONUM: api/routes/risk.py → get_risk() response alanları
📂 MODÜL: Risk Yönetimi (Backend)
🏷️ KATEGORİ: Fonksiyonel
⚡ ÖNCELİK: YÜKSEK

🔍 MEVCUT DURUM:
RiskResponse’ta daily_drawdown_pct, weekly_drawdown_pct alanları var; get_risk() içinde sadece total_drawdown_pct snap’ten set ediliyor. daily_drawdown_pct ve weekly_drawdown_pct hiç set edilmiyor (varsayılan 0).

❌ SORUN / EKSİKLİK:
Risk sayfasında "Günlük Kayıp" ve "Haftalık Kayıp" barları anlamlı dolmuyor; limitler gösterilse bile mevcut değer 0 kalıyor veya frontend 12389 fallback’ine düşüyor.

✅ ÖNERİLEN DEĞİŞİKLİK:
BABA veya DB’de günlük/haftalık drawdown yüzdesi hesaplanıp snapshot’a yazılıyorsa, get_risk() bu alanları snap’ten okuyup resp’e set etsin. Hesaplanmıyorsa: BABA/engine’de günlük ve haftalık PnL’den (bakiye/equity’ye göre) yüzde drawdown hesaplayıp snapshot’a ekleyin; API bu alanları dönsün. Böylece frontend sadece API değerlerini gösterebilir.

📊 FAYDA:
Zarar limitleri ekranında günlük ve haftalık kullanım doğru yansır; kullanıcı limitlere ne kadar yakın olduğunu görür.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: api/routes/risk.py; engine/baba.py veya database snapshot mantığı; api/schemas.py (gerekirse)
- Yan etki riski: Orta (BABA/DB değişikliği)
- MT5 etkisi: Yok (sadece mevcut PnL/equity kullanımı)
- Canlı işlem riski: Yok (okuma/hesaplama)
- Geri dönüş: Orta

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅ (snap yoksa default 0)

═══════════════════════════════════════════════════════
İYİLEŞTİRME #8
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/TopBar.jsx (fazLabel) + desktop/src/components/RiskManagement.jsx (KS_LABELS)
📂 MODÜL: Üst Bar, Risk Yönetimi
🏷️ KATEGORİ: UI/UX
⚡ ÖNCELİK: DÜŞÜK

🔍 MEVCUT DURUM:
Üst bar: fazLabel = `FAZ ${killLevel}` → "FAZ 1". Risk sayfası: KS_LABELS[1].text = "L1 — Kontrat Dur". Aynı kill-switch seviyesi iki yerde farklı terimle gösteriliyor.

❌ SORUN / EKSİKLİK:
"FAZ 1" ile "L1 — Kontrat Dur" aynı şeyi ifade ediyor; kullanıcı iki farklı kavram sanabilir veya eşleştirmek zorunda kalır.

✅ ÖNERİLEN DEĞİŞİKLİK:
Terimleri birleştir: Üst bar’da "FAZ 1 (L1)" veya "L1" kısaltması kullan; veya Risk’teki gibi "L1 — Kontrat Dur" açıklamasını TopBar’da tooltip olarak ver. Alternatif: Her yerde "L1", "L2", "L3" kullan; "FAZ"ı kaldır veya parantez içinde "FAZ 1" yaz.

📊 FAYDA:
Terminoloji tutarlılığı; kullanıcı tek kavramla düşünür.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/TopBar.jsx (veya RiskManagement.jsx etiketleri)
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
İYİLEŞTİRME #9
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/ManualTrade.jsx → Risk özeti para birimi (örn. satır ~296, 301)
📂 MODÜL: İşlem Paneli
🏷️ KATEGORİ: UI/UX
⚡ ÖNCELİK: DÜŞÜK

🔍 MEVCUT DURUM:
Risk özetinde "Equity", "Serbest Teminat", "Floating K/Z" değerleri "TL" ile bitiyor (formatMoney(risk.equity) + " TL"). API’den gelen currency (örn. TRY) kullanılmıyor.

❌ SORUN / EKSİKLİK:
Para birimi sabit "TL"; hesap TRY veya başka para biriminde olsa bile hep TL yazıyor. Ayarlar ve diğer ekranlarda "TRY" kullanılıyor olabilir; tutarlılık için API’den gelen currency kullanılmalı.

✅ ÖNERİLEN DEĞİŞİKLİK:
checkResult / risk_summary veya getAccount() ile gelen currency’yi kullan: örn. risk.currency || 'TRY'. Değerlerin yanında "TL" yerine bu değişkeni göster. Tüm uygulamada para birimi tek kaynaktan (account.currency veya risk.currency) gelsin.

📊 FAYDA:
Çok para birimli veya farklı gösterim tercihlerinde doğru etiket; TRY/TL tutarlılığı.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/ManualTrade.jsx; manual_trade check response’ta currency dönülüyorsa kullan
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
İYİLEŞTİRME #10
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/Performance.jsx → Equity/Drawdown XAxis + Sharpe tooltip
📂 MODÜL: Performans Analizi
🏷️ KATEGORİ: UI/UX
⚡ ÖNCELİK: DÜŞÜK

🔍 MEVCUT DURUM:
Equity ve Drawdown grafiklerinde XAxis dataKey="timestamp", tickFormatter=shortDate. Çok nokta olduğunda aynı tarih tekrarlanıyor ("01.03" birçok kez). Sharpe oranı 0.00 gösterildiğinde neden 0 olduğu açıklanmıyor.

❌ SORUN / EKSİKLİK:
Tarih etiketleri sıkışık ve tekrarlı; anlamlı zaman akışı zor okunur. Sharpe 0.00 (az veri veya düşük volatilite) kullanıcıyı "performans yok" diye düşündürebilir.

✅ ÖNERİLEN DEĞİŞİKLİK:
(1) XAxis’te tick sayısını sınırla (örn. Recharts tick={{ maxTicks: 8 }} veya interval) veya timestamp’leri günlük/haftalık aggregate edip tek nokta per gün göster; böylece tekrarlar azalır. (2) Sharpe kartına kısa tooltip veya alt satır ekle: "Yetersiz veri veya düşük volatilite durumunda 0 görünebilir."

📊 FAYDA:
Grafik okunabilirliği artar; Sharpe 0.00 yanlış yorumlanmaz.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/Performance.jsx
- Yan etki riski: Düşük
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
İYİLEŞTİRME #11
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/TopBar.jsx + Dashboard.jsx (üst bar vs kartlar)
📂 MODÜL: Üst Bar, Dashboard
🏷️ KATEGORİ: UI/UX
⚡ ÖNCELİK: DÜŞÜK

🔍 MEVCUT DURUM:
Üst bar "Günlük K/Z" getAccount().daily_pnl (MT5 hesabından, gerçek zamanlı günlük P/L). Dashboard "Net Kâr/Zarar" getTradeStats().total_pnl (DB’deki kapanan işlemlerin toplamı). İkisi farklı kaynak; aynı gün içinde günlük 0 iken net pozitif olabilir (önceki günlerin kârı).

❌ SORUN / EKSİKLİK:
İki "K/Z" kavramı yan yana kullanılıyor; etiketler "Günlük K/Z" ve "Net Kâr/Zarar" olsa bile kullanıcı ikisini aynı zannedebilir veya farkı bilmeyebilir.

✅ ÖNERİLEN DEĞİŞİKLİK:
Dashboard’daki Net Kâr/Zarar kartına alt satır veya tooltip ekle: "Kapanan işlemler toplamı (DB)". Üst bar’daki "Günlük K/Z" etiketini olduğu gibi bırak (MT5 günlük). İsteğe bağlı: Üst bar’da "Günlük (MT5)" kısaltması veya Dashboard’da "Net K/Z (toplam kapanan)" gibi kısa açıklama.

📊 FAYDA:
Kullanıcı iki metriğin farklı kaynakları olduğunu bilir; karışıklık azalır.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/Dashboard.jsx (veya TopBar.jsx)
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
İYİLEŞTİRME #12
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/components/Dashboard.jsx → Top 5 bar width (satır ~369)
📂 MODÜL: Dashboard
🏷️ KATEGORİ: Kod kalitesi
⚡ ÖNCELİK: DÜŞÜK

🔍 MEVCUT DURUM:
top5-bar-fill width: `${Math.min((c.score / (top5.contracts[0]?.score || 1)) * 100, 100)}%`. İlk kontratın skoru 0 ise bölme 0’a gider; || 1 ile önleniyor. İlk kontrat skoru çok küçükse diğerlerinin barı 100%’ü aşabilir, Math.min ile kırpılıyor.

❌ SORUN / EKSİKLİK:
contracts[0] sıralı mı bilinmiyor; API’den gelen sıra "rank" alanına göre olmayabilir. Bar’ın "birinciye göre oran" mantığı doğru; ancak contracts[0]’ın gerçekten en yüksek skorlu olması API sözleşmesine bağlı. Belge veya sıralama garantisi yoksa, bar için max score’u reduce ile hesaplamak daha güvenli.

✅ ÖNERİLEN DEĞİŞİKLİK:
Bar genişliği için referans skoru sabit contracts[0] yerine hesapla: maxScore = Math.max(...(top5.contracts || []).map(c => c.score || 0), 1). width = (c.score / maxScore) * 100. Böylece sıra değişse bile bar oranları doğru kalır.

📊 FAYDA:
API sıra değişikliğine dayanıklı; görsel oran her zaman en yüksek skora göre doğru.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/components/Dashboard.jsx
- Yan etki riski: Yok
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Kolay

🧪 TEST SİMÜLASYONU:
- Uygulama açılışı: ✅
- MT5 bağlantılı: ✅
- Açık pozisyonla: ✅
- Diğer sekmeler: ✅
- Edge case'ler: ✅ (boş liste, tek kontrat)

---

## ADIM 6: ÖZET TABLO

| # | Modül | Kategori | Öncelik | Yan Etki Riski | Kısa Açıklama |
|---|-------|----------|---------|----------------|---------------|
| 1 | Dashboard | UI/UX | ORTA | Yok | İlk stat kartı başlığı "Günlük İşlem" yap; değer günlük, alt satır toplam |
| 2 | Dashboard | Fonksiyonel | DÜŞÜK | Düşük | Üst satır metrikleri aynı zaman penceresine (örn. 30 gün) veya etiketle açıkla |
| 3 | İşlem Geçmişi | UI/UX | KOZMETİK | Yok | "En Kısa" butonunda ⚡ yerine süre ikonu (⏱) kullan |
| 4 | İşlem Geçmişi | UI/UX | ORTA | Yok | "Maks. Ardışık Kayıp" değerine birim ekle: "X işlem" veya tooltip |
| 5 | Açık Pozisyonlar | UI/UX | ORTA | Düşük | Süre formatında "s" → "st" veya "sa" (saat) yap; saniye ile karışmasın |
| 6 | Risk Yönetimi | Fonksiyonel | YÜKSEK | Orta | 12389 magic number kaldır; equity API’den al, drawdown % doğru hesapla |
| 7 | Risk (API) | Fonksiyonel | YÜKSEK | Orta | daily_drawdown_pct / weekly_drawdown_pct API’de doldurulsun |
| 8 | Üst Bar / Risk | UI/UX | DÜŞÜK | Yok | FAZ 1 vs L1 terminolojisini birleştir veya tooltip ile açıkla |
| 9 | İşlem Paneli | UI/UX | DÜŞÜK | Yok | Risk özeti para birimini API’den (currency) al; TL sabit olmasın |
| 10 | Performans Analizi | UI/UX | DÜŞÜK | Düşük | Grafik X ekseni tick/aggregation; Sharpe 0 için kısa açıklama |
| 11 | Üst Bar / Dashboard | UI/UX | DÜŞÜK | Yok | Günlük K/Z (MT5) vs Net K/Z (DB) farkını etiket/tooltip ile belirt |
| 12 | Dashboard | Kod kalitesi | DÜŞÜK | Yok | Top 5 bar genişliği için maxScore’u liste üzerinden hesapla |

---

## UYGULAMA NOTU

- Hiçbir dosyada değişiklik yapılmamıştır; rapor sadece analiz ve öneri içerir.
- Uygulama sırası: Önce #6 ve #7 (risk verisi ve magic number), sonra #1–5 ve #8–12 tercih edilebilir.
- Her iyileştirme sonrası ilgili ekranlar ve API yanıtları manuel veya test ile doğrulanmalıdır.
