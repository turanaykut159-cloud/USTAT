# USTAT Anayasa Kurumsal Denetim Raporu

**Tarih:** 2026-04-13  
**Kapsam:** `USTAT_ANAYASA.md`, `CLAUDE.md`, `docs/USTAT_CALISMA_REHBERI.md`, `engine/*`, `api/*`, `desktop/*`, `.githooks/pre-commit`, `.github/workflows/ci.yml`, `tests/critical_flows/*`  
**Amaç:** Uygulamanın mevcut "anayasa" yapısının gerçekten yönetişim, koruma, değiştirilemezlik ve kurumsal sürdürülebilirlik sağlayıp sağlamadığını değerlendirmek.

---

## 1. Yönetici Özeti

Mevcut anayasa, sıradan bir proje dokümanından daha güçlüdür. Çünkü yalnızca niyet beyanı içermiyor; bazı kritik davranışlar kod, test ve operasyon akışına da yansıtılmış durumda. Özellikle risk kapısı, kill-switch monotonluğu, MT5 başlatma sorumluluğu, çağrı sırası ve bazı startup/shutdown zincirleri gerçekten çalışan mekanizmalarla korunuyor.

Buna rağmen mevcut yapı, **tam anlamıyla kurumsal ve profesyonel bir anayasa seviyesinde değildir**. Bunun ana nedeni şudur:

1. Anayasa tek başına bağlayıcı bir yönetişim motoru değil, büyük ölçüde dokümantasyon + geliştirici disiplini kombinasyonudur.
2. "Değiştirilemez" denilen maddeler teknik olarak hâlâ değiştirilebilir durumdadır.
3. En güçlü koruma katmanı olan test ve commit kapıları, teslim hattında zorunlu ve kaçınılmaz şekilde çalışmıyor.
4. Belge zaman içinde büyümüş, anayasa ile çalışma rehberi, test politikası, acil durum playbook'u ve organizasyon şeması birbirine karışmıştır.

Sonuç olarak mevcut anayasa:

- **Operasyonel güvenlik kültürü üretmekte güçlü**
- **Bazı kritik davranışları korumakta orta-güçlü**
- **Kurumsal yönetişim ve gerçek değiştirilemezlik sağlamada zayıf**

Kısa hüküm:

- **Uygulamayı yönetmeye kısmen yeterli**
- **Uygulamayı gerçekten korumaya kısmen yeterli**
- **Değiştirilemez maddeleri gerçekten değiştirilemez yapmaya yetersiz**

---

## 2. İnceleme Yöntemi

Bu değerlendirme yalnızca belge okuması değil, belge ile kodun birbirini doğrulayıp doğrulamadığını kontrol eden bir eşleştirme denetimi olarak yapılmıştır.

İncelenen başlıca kanıtlar:

- `USTAT_ANAYASA.md` içeriği ve değişiklik geçmişi
- `CLAUDE.md` içindeki anayasa özeti ve çalışma prosedürleri
- `.githooks/pre-commit` içindeki commit öncesi kontroller
- `.github/workflows/ci.yml` içindeki CI zorunlulukları
- `tests/critical_flows/test_static_contracts.py` içindeki statik sözleşme testleri
- `engine/main.py`, `engine/baba.py`, `engine/ogul.py`, `engine/mt5_bridge.py`
- `start_ustat.py`, `api/server.py`, `api/routes/mt5_verify.py`, `api/routes/killswitch.py`
- `desktop/main.js`, `desktop/mt5Manager.js`

Doğrudan doğrulamalar:

- `python -m pytest tests\critical_flows -q` çalıştırıldı
- Sonuç: **71 test geçti**, 3 adet düşük önem seviyeli `SyntaxWarning` üretildi

---

## 3. Doğrudan Sorulara Cevap

### 3.1 Bu anayasa uygulamayı yönetmeye yeterli mi?

**Kısmen yeterli, ama tam kurumsal yönetim seviyesi için yeterli değil.**

Neden kısmen yeterli:

- Kritik dosyaları, fonksiyonları ve davranışları isim vererek tanımlıyor.
- Ön-onay, etki analizi, geri alma planı ve test disiplini getiriyor.
- Riskli bir canlı trading sistemi için "dokunmadan önce düşün" kültürü oluşturuyor.
- Acil durum, test, ajan koordinasyonu ve değişiklik tarihi gibi alanları da kapsıyor.

Neden tam yeterli değil:

- Anayasa, rehber, süreç kitabı, test politikası, organizasyon şeması ve playbook tek belgede birleşmiş.
- Hangi maddenin "kurucu ilke", hangisinin "operasyon kuralı", hangisinin "çalışma prosedürü" olduğu net ayrışmıyor.
- Gerçek yönetişim için gereken bağımsız denetim, teknik kilitler, dış onay mekanizmaları ve fail-closed teslim hattı eksik.

### 3.2 Anayasa uygulamayı gerçekten koruyor mu?

**Evet, ama kısmi olarak.**

Gerçekten koruduğu alanlar var:

- `engine/baba.py` içinde kill-switch seviyesi aşağı düşmüyor; `_activate_kill_switch()` monotonluk uyguluyor.
- `engine/main.py` içinde `_run_single_cycle()` akışı BABA'yı OĞUL'dan önce çalıştırıyor.
- `engine/mt5_bridge.py` içinde `connect(launch=False)` çağrısı öncesi `terminal64.exe` process kontrolü var; engine MT5'i kendisi açmıyor.
- `engine/mt5_bridge.py` içinde `_safe_call()` timeout + circuit breaker uyguluyor.
- `api/routes/mt5_verify.py` içinde `mt5.initialize()` öncesi process kontrolü var.
- `desktop/main.js` içinde singleton conflict için `app.exit(42)` koruması var.
- `tests/critical_flows/test_static_contracts.py` bu davranışların bir kısmını test ediyor.

Ama korumanın sınırı şurada:

- Belgenin tamamını zorlayan tekil bir "constitutional enforcement engine" yok.
- Her madde için makine tarafından doğrulanan bir kontrol matrisi yok.
- Koruma zinciri commit ve CI hattında tam kapanmıyor.

### 3.3 "Değiştirilemez" dediğimiz maddeleri kolaylıkla değiştirebiliyor muyuz?

**Teknik olarak evet.**

Bu çok önemli bir tespittir: repo içindeki bir Markdown dosyası kendi başına değiştirilemez olamaz.

Bugünkü durumda:

- `USTAT_ANAYASA.md` normal bir sürüm kontrollü dosyadır.
- Git geçmişi bu dosyanın birçok kez değiştirildiğini açıkça gösteriyor.
- `git log --follow -- USTAT_ANAYASA.md` çıktısında anayasanın büyüdüğü ve yeni "değiştirilemez" kurallar eklendiği görülüyor.
- `USTAT_ANAYASA.md` değişiklik geçmişinde Bölüm 3.3 ve Bölüm 4'e yeni kurallar eklendiği bizzat kayıt altına alınmış.

Bu şu anlama gelir:

- Mevcut sistemde "değiştirilemezlik", **ontolojik değil prosedüreldir**.
- Yani gerçekten "değiştirilemez" değil; sadece "değiştirilmesi zorlaştırılmış" veya "izin gerektirir" durumdadır.

Kurumsal gerçek:

- Aynı repo içinde duran bir belge, repo yazma yetkisi olan kişi veya ajan tarafından her zaman değiştirilebilir.
- Gerçek immutability ancak dış güven kökü, imzalı onay, korumalı branch, zorunlu CI ve bağımsız denetim ile sağlanabilir.

---

## 4. Güçlü Yönler

### 4.1 Uygulamaya özgü ve risk odaklı

Belge jenerik değil. VİOP, MT5, EOD, drawdown, kill-switch, startup sırası, OTP akışı gibi uygulamaya özgü riskleri isimliyor. Bu çok değerli.

### 4.2 Sadece "ne" değil "neden" de yazıyor

Birçok madde koruma nedenini açıklıyor. Bu, anayasanın eğitim ve karar kalitesi açısından güçlü tarafı.

### 4.3 Kodla kısmi hizalanma var

Bazı maddeler gerçekten çalışan kodla destekleniyor:

- Risk kapısı
- Kill-switch monotonluğu
- Circuit breaker
- MT5 auto-launch önleme
- Startup/singleton koruması

### 4.4 Test tabanı oluşmuş

`tests/critical_flows` klasörü önemli bir kazanım. Bu klasör, anayasanın en azından bir bölümünü sözlü kural olmaktan çıkarıp ölçülebilir kurala dönüştürüyor.

### 4.5 Değişiklik tarihi ve neden-sonuç mantığı doğru bir yön

Belgenin sonradan versiyonlama, neden-sonuç kaydı ve karar gerekçesi eklemesi profesyonel yönetişime giden doğru bir hareket.

---

## 5. Kritik Bulgular

### Bulgu 1 — Anayasa teknik olarak korunmuyor, sadece prosedürle korunuyor

Şiddet: **Kritik**

Kanıt:

- `USTAT_ANAYASA.md` sıradan bir repo dosyası
- Hook zorunluluğu repo seviyesinde aktif görünmüyor; `git config --get core.hooksPath` boş döndü
- `.githooks/pre-commit` dosyasında açıkça `git commit --no-verify` ile atlanabileceği yazıyor

Yorum:

Bu durumda anayasa ihlali, teknik olarak imkansız değil; sadece "yapılmaması gereken şey" seviyesinde kalıyor.

### Bulgu 2 — CI hattı anayasal korumayı fail-closed çalıştırmıyor

Şiddet: **Kritik**

Kanıt:

- `.github/workflows/ci.yml` içinde pytest yolu `USTAT DEPO/tests_aktif/` olarak tanımlı
- Bu yol çalışma alanında mevcut değil
- Aynı job `continue-on-error: true` ile işaretlenmiş

Sonuç:

- Testler başarısız olsa bile teslim hattı bunu engel olarak kullanmayabilir
- Bu, anayasanın "testsiz deploy yasak" iddiasını zayıflatır

### Bulgu 3 — Anayasa ile gerçek kod arasında tutarsız maddeler var

Şiddet: **Yüksek**

Örnekler:

- `USTAT_ANAYASA.md` içinde `_check_advanced_risk_rules()` anayasal siyah kapı olarak listelenmiş, fakat `engine/ogul.py` içinde böyle bir fonksiyon bulunmuyor
- Belge `send_order()` başarısız SL/TP durumunda zorla kapatır diyor; gerçek uygulamada kapanış yükü `OgulSLTP` fallback zincirine bırakılmış
- Bazı akış açıklamaları eski sıraları veya artık var olmayan ara adımları referanslıyor

Sonuç:

- Belge artık tam bir "source of truth" değil
- Bu da anayasanın yönetişim değerini düşürür

### Bulgu 4 — Belge aşırı genişlemiş, anayasa ile işletim kılavuzu birbirine karışmış

Şiddet: **Yüksek**

Mevcut belge şunları aynı çatıya toplamış durumda:

- çekirdek güvenlik ilkeleri
- dosya/fonksiyon koruma listeleri
- test politikası
- organizasyon modeli
- CEO/direktörlük kuralları
- savaş/barış zamanı
- acil durum playbook'u
- ajan koordinasyonu

Bu, büyüme evresinde anlaşılır; fakat kurumsal modelde bu bir problem üretir:

- temel anayasal ilke ile günlük operasyon prosedürü eşit ağırlıkta görünmeye başlar
- hangi madde ihlal edildiğinde ne seviyede işlem yapılacağı bulanıklaşır

### Bulgu 5 — Tüm "değiştirilemez" maddeler için makine doğrulaması yok

Şiddet: **Yüksek**

Evet, `tests/critical_flows` iyi bir başlangıç. Ama anayasanın ilan ettiği tüm siyah kapılar ve değiştirilemez kuralların tamamı için:

- test eşlemesi
- AST/fingerprint doğrulaması
- zorunlu onay kaydı
- CI kapısı

bulunmuyor.

Yani koruma seçici ve parçalı.

### Bulgu 6 — Hook var ama zorunlu politika motoru yok

Şiddet: **Orta**

`.githooks/pre-commit` faydalı:

- AST kontrolü yapıyor
- `tests/critical_flows` çalıştırıyor
- kırmızı bölgeyi uyarıyor

Ama eksikleri:

- aktif olacağı garanti değil
- atlanabiliyor
- gerçek "approval token" veya onay ID doğrulamıyor
- sadece uyarı veriyor; bazı anayasal maddeleri makine diliyle yorumlamıyor

### Bulgu 7 — Mevcut yapı güçlü bir güvenlik rejimi kuruyor ama güçlü bir kurumsal anayasa rejimi kurmuyor

Şiddet: **Orta**

Bugünkü yapı "sakın bozma" konusunda iyi; fakat şu alanlarda eksik:

- yetki ayrılığı
- bağımsız güvenlik onayı
- değişiklik sınıflandırma standardı
- istisna prosedürü
- zaman sınırlı waiver mekanizması
- dış denetim izi
- imzalı karar zinciri

---

## 6. Mevcut Yapının Gerçek Koruma Seviyesi

### 6.1 Güçlü korunan alanlar

- Risk kapısı ve kill-switch
- MT5 başlatma sorumluluğu
- Circuit breaker
- Startup/singleton koruması
- Bazı kritik akışlar için statik sözleşme testleri

### 6.2 Orta seviyede korunan alanlar

- Kırmızı bölge farkındalığı
- Etki analizi disiplini
- Değişiklik öncesi dikkat uyarıları
- Çalışma rehberi ve süreç disiplini

### 6.3 Zayıf korunan alanlar

- Anayasa dosyasının kendisi
- Çekirdek maddelerin gerçek immutability'si
- CI üzerinden zorunlu yürütme
- Onay kayıtlarının teknik doğrulanması
- Her madde için birebir enforcement mapping

---

## 7. Kurumsal ve Profesyonel Bir Anayasa Nasıl Olmalı?

Profesyonel bir anayasa, büyük ve ayrıntılı bir belge olmak zorunda değildir. Aksine, **kısa, üst seviye, az sayıda ama sert şekilde uygulanan kurucu kurallardan** oluşmalıdır.

Kurumsal modelde önerilen ayrım şudur:

### 7.1 Tek belge yerine belge ailesi

1. **Constitution Charter**
   Yalnızca çekirdek ilkeler, değişiklik sınıfları, otorite zinciri ve ihlal sonuçları
2. **Safety Invariants Spec**
   Teknik olarak korunacak davranışlar
3. **Protected Assets Registry**
   Kritik dosya, fonksiyon, config, test ve owner listesi
4. **Change Control Standard**
   Onay, rollback, test, release koşulları
5. **Runbooks / Playbooks**
   Acil durum ve operasyon prosedürleri
6. **Engineering Handbook**
   Günlük çalışma pratiği

Bugünkü USTAT anayasası bu altı katmanı tek başına taşımaya çalışıyor.

### 7.2 Profesyonel anayasanın temel özellikleri

- Kısa çekirdek
- Açık hiyerarşi
- Dış güven kökü
- Makine doğrulanabilir hükümler
- Fail-closed CI
- Onaysız değişiklikte otomatik red
- İstisna mekanizması
- Zaman sınırlı waiver
- İmzalı değişiklik geçmişi

### 7.3 "Değiştirilemezlik" profesyonelce nasıl tanımlanır?

Gerçekçi tanım şu olmalı:

> Hiçbir kural aynı otorite düzeyi içinde kendini mutlak olarak değiştirilemez kılamaz. Bu nedenle değiştirilemez çekirdek, repo içi beyanla değil; dış onay, korumalı branch, zorunlu CI, imzalı commit/tag ve bağımsız onay katmanı ile korunur.

Bu tanım bugünkü yapıdan çok daha dürüst ve uygulanabilirdir.

---

## 8. Ben Bu Uygulama İçin Nasıl Bir Anayasa Yazardım?

Ben bu uygulama için anayasayı daha kısa, daha sert ve daha makine uygulanabilir kurardım.

### 8.1 Önerilen anayasal çekirdek

**Bölüm A — Amaç ve Öncelik**

- Sistem önceliği: sermaye korunumu > güvenli duruş > veri doğruluğu > işlem fırsatı
- Şüphede fail-open değil fail-closed

**Bölüm B — Yetki ve Hiyerarşi**

- Nihai otorite: kullanıcı
- Operasyon otoritesi: production safety owner
- Geliştirme otoritesi: engineering owner
- Tek kişiyle çekirdek kural değişmez; iki aşamalı onay gerekir

**Bölüm C — Çekirdek Güvenlik İhlal Edilemezleri**

- Risk kapısı atlanamaz
- Kill-switch seviyesi otomatik düşürülemez
- Korumasız pozisyon tolere edilemez
- Engine MT5'i launch-false modda açamaz
- BABA, OĞUL'dan önce çalışır
- Hard drawdown eşiği fail-open yorumlanamaz

**Bölüm D — Korunan Varlıklar**

- Kırmızı dosyalar
- Siyah kapı fonksiyonları
- Kritik config anahtarları
- Kritik testler
- Kritik deploy adımları

**Bölüm E — Değişiklik Sınıfları**

- Sınıf 0: Editorial
- Sınıf 1: Operational
- Sınıf 2: Protected
- Sınıf 3: Core Constitutional

Her sınıf için:

- gerekli onay
- gerekli testler
- gerekli rollback planı
- deploy şartı

**Bölüm F — Teknik Zorunluluklar**

- Protected branch zorunlu
- Required status checks zorunlu
- Signed commits veya signed tags zorunlu
- Constitution manifest kontrolü zorunlu
- Approval ID olmadan protected değişiklik merge edilemez

**Bölüm G — Olay ve Acil Durum Yetkileri**

- Seviye 1 finansal risk
- Seviye 2 koruma kaybı
- Seviye 3 operasyonel bozulma
- Seviye 4 arayüz/raporlama sorunu

**Bölüm H — Anayasa Değişiklik Rejimi**

- Çekirdek maddeler ayrı depoda veya imzalı manifestte tutulur
- Çekirdek değişiklik için iki imza + test paketi + ayrı sürüm etiketi gerekir

### 8.2 Belge değil sistem tasarımı önerisi

Ben ek olarak şu teknik yapıyı kurardım:

1. `governance/constitutional_manifest.yaml`
2. `tools/check_constitution.py`
3. `tests/governance/test_constitution_manifest.py`
4. CI içinde zorunlu `constitution-check` job
5. Protected file diff olduğunda zorunlu approval token doğrulaması
6. Siyah kapı fonksiyonları için AST fingerprint veya contract snapshot

Örnek manifest alanları:

- `clause_id`
- `title`
- `protected_paths`
- `protected_functions`
- `protected_config_keys`
- `required_tests`
- `required_approvals`
- `rollback_required`
- `owner`
- `waiver_policy`

---

## 9. USTAT İçin Somut Gap Analizi

### Şu an var

- İyi niyetli ve alan bilgisi yüksek anayasa
- Bazı güçlü runtime korumaları
- Kritik akış testleri
- Pre-commit koruması
- Süreç farkındalığı

### Şu an eksik

- Aktif ve zorunlu hook kaydı
- Fail-closed CI
- Constitution manifest
- Her anayasal madde için enforcement mapping
- Protected branch / signed approval zinciri
- Değişiklik sınıfına göre otomatik merge gate
- Anayasa ile işletim rehberinin ayrılması

### En kritik eksik

**"Bu kural değiştirilemez" cümlesinin dış dünyada bağlayıcı teknik karşılığı yok.**

---

## 10. Sonuç Hükmü

Mevcut anayasa, bu uygulama için rastgele yazılmış bir belge değil; ciddi emek verilmiş, risk farkındalığı yüksek, uygulamaya özgü ve önemli ölçüde faydalı bir güvenlik çerçevesidir. Bu yönüyle değerlidir ve kesinlikle çöpe atılacak bir yapı değildir.

Ancak kurumsal ve profesyonel ölçekte değerlendirildiğinde, mevcut yapı **anayasa olma iddiasını kısmen taşıyor ama gerçek anayasal rejim olma seviyesine henüz ulaşmıyor**.

En net hüküm şudur:

- Bu belge **iyi bir güvenlik anayasası taslağıdır**
- Ama henüz **tam bir kurumsal anayasa sistemi değildir**
- Korur, ama **tam ve zorunlu biçimde korumaz**
- Değişikliği zorlaştırır, ama **gerçek anlamda değiştirilemez yapmaz**

USTAT gibi canlı para riski taşıyan bir sistem için bir sonraki olgunluk seviyesi şudur:

> Belgeden kurala, kuraldan teste, testten CI kapısına, CI kapısından imzalı onaya geçen zincir kurulmalıdır.

O zincir kurulduğunda anayasa gerçekten "yazılmış" değil, "uygulanıyor" olur.

---

## 11. Nihai Tavsiye

Kısa vadede:

1. `.githooks` zorunlu hale getirilmeli
2. `.github/workflows/ci.yml` düzeltilmeli ve fail-closed çalışmalı
3. Anayasa ile çalışma rehberi ayrılmalı
4. Siyah kapı / değiştirilemez kural listesi kodla yeniden senkronize edilmeli
5. Her çekirdek madde için test veya statik kontrol eşlemesi çıkarılmalı

Orta vadede:

1. Constitution manifest kurulmalı
2. Protected asset registry ayrı dosya olmalı
3. Onay ID ve waiver mekanizması getirilmeli
4. Anayasa değişiklikleri için imzalı sürümleme yapılmalı

Uzun vadede:

1. Çekirdek anayasal hükümler repo dışı güven kökü ile korunmalı
2. İki-aşamalı onay ve bağımsız doğrulama zorunlu hale gelmeli
3. "Değiştirilemez çekirdek" teknik olarak ölçülebilir hale getirilmeli

Bu yapıya geçilirse USTAT'ın anayasası yalnızca iyi bir belge olmaktan çıkar, gerçekten kurumsal bir yönetim ve koruma sistemi haline gelir.
