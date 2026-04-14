# ÜSTAT Plus V6.0 — ANAYASA

**Yürürlük Tarihi:** 2026-04-14
**Versiyon:** 3.0 (Operasyonel Revizyon — v2 arşivi: `docs/arsiv/USTAT_ANAYASA_v2.md`, v1 arşivi: `docs/arsiv/USTAT_ANAYASA_v1.md`)
**Kapsam:** Tüm geliştiriciler (insan ve AI) için bağlayıcıdır.
**Konu:** Bu belge uygulamanın **çalışmasını** değil, uygulamaya **dokunulmasını** düzenler. Bir değişim yönetmeliğidir.

> **v3.0'ın farkı:** Anayasa artık sadece ne yapılamayacağını söylemez; değişikliği nasıl **yapabileceğini** de gösterir. "Savunmacı" kurallardan "etkinleştirici + savunmacı" sisteme geçiş. Her çekirdek kural, bir makine-okunur manifest ve bir otomasyon aracıyla eşlenmiştir. Kural ile otomasyon artık çatışmaz — biri diğerini doğrular.
>
> Bu belgedeki hiçbir çekirdek madde, kullanıcının açık yazılı onayı olmadan değiştirilemez.
> AI ajanlar (Claude dahil) anayasa değiştiremez; sadece teklif eder.

---

## BÖLÜM A — AMAÇ VE FELSEFE

Bu anayasa altı soruya cevap verir:

1. **NE** değiştirilirken dikkat edilir? → Korunan Varlık Sicili (`governance/protected_assets.yaml`)
2. **KİM** izin verir? → Yetki Matrisi (`governance/authority_matrix.yaml`) ve kullanıcı (Üstat). AI teklif eder, kullanıcı onaylar.
3. **NASIL** değişir? → Değişiklik Sınıfları (Bölüm D) + Guard Triggers (`governance/triggers.yaml`)
4. **DOĞRULUK** nasıl kanıtlanır? → `tests/critical_flows`, `tools/check_constitution.py`, `tools/check_triggers.py`, CI
5. **KÖTÜ** değişiklik nasıl geri alınır? → `tools/rollback/*` + Bölüm E
6. **ANAYASA KENDİSİ** nasıl değişir? → C3 prosedürü + çift doğrulama (Bölüm H)

**Öncelik sırası:** Uygulamanın sürdürülebilirliği > değişiklik hızı > yeni özellik.
Şüphe durumunda **fail-closed**: devam et değil, dur.

**Felsefe özeti:** Anayasa *kilitlemek* için değil, *güvenle hızlı çalışmak* için vardır. Kurallar otomasyonla eşleştiğinde, "kural çiğnendi mi?" sorusu insanın hafızasına bırakılmaz — araç cevap verir.

---

## BÖLÜM B — OTORİTE

- **Nihai Otorite:** Üstat (kullanıcı). Bu otorite devredilemez.
- **Teklif Yetkisi:** Tüm geliştiriciler ve AI ajanlar. Teklif onay değildir.
- **Uygulama Yetkisi:** Onay alındıktan sonra teklifi yapan taraf uygular.
- **Sessizlik onay DEĞİLDİR.** Açık ifade gereklidir.

**Yetki Matrisi (`governance/authority_matrix.yaml`):**
Zone × Class × Action → Authority seviyesi. Dört seviye:
- `tam`: AI doğrudan uygulayabilir
- `misyon`: Misyon ID açılmış olmalı, seal_change ile kapatılmalı
- `plan`: Plan + onay + seal
- `dur` / `yasak`: AI uygulayamaz; kullanıcı onayı olmadan girilemez

**C3 Onay İfadesi (Aşama 1):**
```
ANAYASA ONAYI: <clause_id> <YYYY-MM-DD> <kısa_gerekçe>
```

**C3 Teyit İfadesi (Aşama 2, ≥24 saat sonra):**
```
ANAYASA TEYİDİ: <clause_id> <aşama1_commit_sha[:12]>
```

---

## BÖLÜM C — ÇEKİRDEK İHLAL EDİLEMEZLER (AXIOMS)

Aşağıdaki maddeler uygulamanın bozulmadan evrilmesinin şartlarıdır. Her madde hem `governance/axioms.yaml` içinde makine-okunur olarak, hem `governance/protected_assets.yaml` içindeki testlerle eşlenmiş olarak tutulur. Bir madde ihlal edilirse `tests/critical_flows` veya `tests/governance` kırmızıya döner ve merge bloke olur.

| ID | Axiom ID | Madde | Koruma Noktası |
|----|----------|-------|----------------|
| **CI-01** | AX-2 | Risk kapısı atlanamaz: `can_trade=False` iken OĞUL emir göndermez | `baba.check_risk_limits` + OĞUL `_execute_signal` |
| **CI-02** | AX-3 | Kill-switch monotonluğu: seviye sadece yukarı gider (L1→L2→L3). Otomatik düşme yok. | `baba._activate_kill_switch` |
| **CI-03** | AX-4 | Korumasız pozisyon yasak: `send_order` SL/TP başarısız → pozisyon ZORLA kapatılır | `mt5_bridge.send_order` |
| **CI-04** | AX-5 | EOD 17:45 zorunlu kapanış: OĞUL + Hybrid tüm pozisyonlar kapatılır (manuel + orphan hariç) | `ogul._check_end_of_day`, `_verify_eod_closure` |
| **CI-05** | AX-6 | Hard drawdown ≥%15 → L3 kill-switch → tüm pozisyonlar kapatılır | `baba._check_hard_drawdown` |
| **CI-06** | — | OLAY rejiminde `risk_multiplier = 0.0`; yeni işlem açılmaz | `baba.detect_regime` |
| **CI-07** | AX-1 | Çağrı sırası: `heartbeat → data → BABA → risk_check → OĞUL → H-Engine → ÜSTAT`. Değiştirilemez. | `main._run_single_cycle` |
| **CI-08** | — | MT5 başlatma sorumluluğu SADECE Electron (`mt5Manager.js::launchMT5`). Engine MT5'i başlatamaz. | `mt5_bridge.connect(launch=False)` + process kontrol |
| **CI-09** | AX-7 | `mt5.initialize()` evrensel koruma: her çağrıdan ÖNCE `terminal64.exe` process kontrolü. Yeni `mt5.initialize()` çağrısı yasak. | `mt5_bridge.connect`, `health_check`, `mt5_verify` |
| **CI-10** | — | Fail-closed: güvenlik modülü sessizce düşerse sistem "kilitli" duruma geçer. Sessiz fail YASAK. | `main._main_loop` hata izolasyonu |

**Kural:** Bir CI-XX maddesi için test eşlemesi yoksa, o madde anayasada YER ALMAZ. Test olmadan koruma yok.

**Axiom-CI ilişkisi:** `governance/axioms.yaml` makine-okunur çekirdektir; bu tablo insan-okunur yansımasıdır. İkisi arasında çelişki tespit edilirse `tools/check_constitution.py` CI'yı kırar.

---

## BÖLÜM D — DEĞİŞİKLİK SINIFLARI VE GUARD TRIGGERS

Her değişiklik uygulanmadan ÖNCE sınıflandırılır. Sınıf, yetki matrisi (`governance/authority_matrix.yaml`) tarafından belirlenir; statik tetikleyiciler (`governance/triggers.yaml`) sınıfı otomatik yükseltebilir (escalate) veya durdurabilir (halt).

| Sınıf | Kapsam | Onay | Soğuma | Zorunlu Adımlar |
|-------|--------|------|--------|-----------------|
| **C0** Editoryal | Yazım, yorum, format | Yok | Yok | Normal commit |
| **C1** Operasyonel | Yeşil bölge (sicil dışı) kod, dokümantasyon | Standart | Yok | Testler yeşil |
| **C2** Korunan | Sicile kayıtlı dosya/fonksiyon/config anahtarı (Sarı/Kırmızı Bölge) | Açık onay ifadesi + etki raporu + rollback planı | Yok | `tools/check_triggers.py` + pre-commit + CI + manifest check |
| **C3** Anayasal | Çekirdek madde (CI-01…CI-10), korunan kural (R-01…R-XX), anayasa metni, manifest, `locked_values` | Çift doğrulama (Aşama 1 + Aşama 2) | **24 saat** | Pre-commit + CI + manifest check + etki raporu + imzalı tag (`ANAYASA-vX.Y`) |
| **C4** Siyah Kapı | Korunan fonksiyon mantığı (31 fonksiyon) | Üçlü onay (kanıt + plan + sonuç) + auditor raporu | Yok (acil değilse 24h önerilir) | C3 adımları + `ustat-auditor` raporu + statik sözleşme testi |

**C2 Açık Onay:** Commit mesajında `ANAYASA ONAYI: <clause_id> <tarih> <gerekçe>` ifadesi.

**C3 Çift Doğrulama:**
- Aşama 1: Plan + etki raporu kullanıcıya sunulur, açık onay alınır, `ANAYASA ONAYI:` commit'i yapılır.
- Aşama 2 (≥24h sonra): Kullanıcı `ANAYASA TEYİDİ: <clause_id> <sha12>` verir, uygulama commit'i yapılır.
- Pre-commit hem ifadeyi, hem sha varlığını, hem 24h geçmesini doğrular.

**Guard Triggers (`governance/triggers.yaml`):** Statik tarayıcı aşağıdaki durumlarda sınıfı otomatik yükseltir veya durdurur. `tools/check_triggers.py` exit kodları: 0 temiz, 2 yükselt, 3 dur.

| Trigger | Davranış | Açıklama |
|---------|----------|----------|
| TR-AX1..7 | **halt** | Axiom ihlali tespit edildi |
| TR-CONFIG | C3 escalate | `config/default.json` `locked_values` değişimi |
| TR-SCHEMA | C3 + backup | DB şema değişimi (yeni tablo/kolon/migration) |
| TR-API | C2 + test | API route/schema değişimi |
| TR-RED-30 | auditor zorunlu | Kırmızı Bölge dosyada >30 satır değişim |
| TR-BLACKDOOR | C4 + auditor + test | Siyah Kapı fonksiyon mantığı değişimi |
| TR-UI | require_build | `desktop/src/` değişimi → `npm run build` zorunlu |
| TR-CRITICAL-FLOW | always | `tests/critical_flows` yeşil zorunlu |
| TR-MAGIC | C2 | Sihirli sayı (config dışı sabit) eklenmesi |
| TR-MT5-INIT-SCAN | **halt** | `mt5_bridge.py` dışında `mt5.initialize()` çağrısı |
| TR-CALL-ORDER | **halt** | `_run_single_cycle` çağrı sırası bozulması |

---

## BÖLÜM E — KORUNAN VARLIKLAR VE ROLLBACK

Listelerin kendisi anayasa metninde tutulmaz. Tek kaynak: `governance/protected_assets.yaml`.

Sicil dört kategoride tutulur:

1. **Korunan Dosyalar** (Kırmızı Bölge): Değişiklik C2, silme C3.
2. **Korunan Fonksiyonlar** (Siyah Kapı): Mantık değişikliği C4, performans/güvenlik iyileştirmesi C2 (mantık ve çıktı değişmeden).
3. **Korunan Kurallar** (R-01…R-XX): Uygulama davranış sözleşmeleri (çağrı sırası, rejimler, Top 5, state machine, EOD vb.). Kural değişimi C3.
4. **Korunan Config Anahtarları:** Anahtar yapısı değişimi C2; kilitli değer (`locked_values`) değişimi C3.

**Hayalet yasağı:** Sicile yazılan her dosya, fonksiyon ve kural kodda VAR olmalıdır. `tools/check_constitution.py` her commit'te bunu doğrular. Hayalet kayıt CI'yı kırar.

**Rollback Araçları (`tools/rollback/`):**

| Araç | Amaç |
|------|------|
| `tools/rollback/commit.sh <hash>` | Tek commit'i `git revert` ile geri al (onaylı) |
| `tools/rollback/mission.sh <M-ID>` | Bir misyonun tüm commit'lerini sırayla revert et |
| `tools/rollback/workspace.sh [--stash\|--all]` | Kirli workspace'i stash'e al veya tümüyle sıfırla |
| `tools/rollback/db.sh {list\|backup\|restore <name>}` | Veritabanı yedek ve geri yükleme (`trades.db`, `ustat.db`) |

Her C2/C3/C4 değişiklik öncesi ilgili rollback komutu planda yazılı olmalıdır. Rollback planı olmayan değişiklik uygulamaya alınmaz.

---

## BÖLÜM F — TEKNİK ZORUNLULUKLAR (ENFORCEMENT ZİNCİRİ)

Anayasa sadece belge olarak değil, zincirle uygulanır.

1. **Hook aktivasyonu:** `git config core.hooksPath .githooks` repo kurulumunda zorunlu. `scripts/setup_repo.ps1` bunu uygular.
2. **Session Gate:** Her oturum başında `python tools/session_gate.py` çalıştırılır. Exit 0 dışında başlama yasak. Gate şunları doğrular:
   - `governance/*.yaml` manifest bütünlüğü
   - `.gitattributes` satır-sonu politikası
   - Workspace temizliği (veya bilinçli `--force`)
   - Dal senkronizasyonu (`main`/feature branch)
   - Oturum kilidi (`.ustat_session.lock`) — paralel session çatışmasını engeller
3. **Pre-commit kapısı:** `.githooks/pre-commit`
   - `tools/check_constitution.py` çalıştırır (manifest-kod senkron)
   - `tools/check_triggers.py` çalıştırır (sınıf yükseltme / halt)
   - `tests/critical_flows` çalıştırır
   - C2/C3 değişikliklerde onay ifadesi varlığını doğrular
   - C3 değişikliklerde Aşama 2'nin 24 saat geçtiğini ve sha eşlemesinin doğru olduğunu doğrular
4. **Commit Seal (`tools/seal_change.py`):** C1+ tüm değişiklikler için tek giriş noktası. 6 adımda:
   `triggers → test → build (UI değiştiyse) → changelog → stage (sadece declared files) → commit`. Bu araç dışında commit atmak C0 editoryal hariç yasaktır.
5. **CI kapısı:** `.github/workflows/ci.yml`
   - `continue-on-error: true` YASAK
   - `tests/critical_flows` + `tests/governance` zorunlu yeşil
   - Manifest check + trigger check zorunlu yeşil
   - Başarısız test → merge bloke
6. **Etki raporu:** C2/C3/C4 değişiklikte `tools/impact_report.py` ile rapor üretilir; `reports/impact_<tarih>_<dosya>.md` dosyası commit'e dahil edilir. Rapor yoksa pre-commit bloklar.
7. **İmzalı tag:** Her C3 sonrası `git tag -a ANAYASA-vX.Y -m ...` zorunlu.

---

## BÖLÜM G — MİSYON MODELİ

C2+ değişiklikler "misyon" kapsamında yürütülür. Misyon, birbiriyle ilişkili değişiklik grubunun izlenebilir birimidir.

**Misyon ID formatı:** `M-YYYY-MM-DD-<kısa_ad>` (örn: `M-2026-04-14-primnet-fixes`)

**Misyon yaşam döngüsü:**
1. **Açılış:** `docs/misyonlar/<M-ID>.md` oluşturulur (amaç, kapsam, dosya listesi, rollback planı, test planı)
2. **Yürütme:** Her commit mesajı `(M-ID)` içerir; `tools/seal_change.py --mission M-ID ...`
3. **Kapanış:** Tüm dosyalar ele alındığında misyon dosyasına "Sonuç" bölümü eklenir (commit'ler, test sonuçları, canlı doğrulama)
4. **Geri alma:** `tools/rollback/mission.sh <M-ID>` ile toplu revert mümkün

**Misyon kuralı:** Bir misyon altındaki commit'ler *atomik* olmalıdır — her biri tek başına yeşil test bırakır. Misyonun yarısında kalan commit dizisi yasaktır.

---

## BÖLÜM H — ANAYASA DEĞİŞİKLİK REJİMİ

Bu belgenin kendisini değiştirmek C3 sınıfıdır.

**Aşama 1 — Plan ve Onay**
- Değişiklik teklifi yazılır: `docs/anayasa_degisiklikleri/<YYYY-MM-DD>_<clause_id>_plan.md`
- Etki raporu üretilir: `tools/impact_report.py USTAT_ANAYASA.md` çalıştırılır
- Kullanıcıya sunulur, açık onay ifadesi alınır
- Aşama 1 commit yapılır (`ANAYASA ONAYI:` içeren)

**24 Saat Soğuma**
Bu sürede hiçbir müdahale yapılmaz. Teklifi yapan düşünür, kullanıcı gözden geçirir.

**Aşama 2 — Teyit ve Uygulama**
- Kullanıcı teyit ifadesini verir (`ANAYASA TEYİDİ: <clause_id> <sha12>`)
- Uygulama commit'i yapılır
- Sonrasında imzalı tag: `git tag -a ANAYASA-vX.Y`
- Kayıt dosyası tamamlanır: `docs/anayasa_degisiklikleri/<YYYY-MM-DD>_<clause_id>_sonuc.md`

**Zorunlu Kayıt İçeriği:**
- Neden gerekli oldu (kanıt)
- Ne değişti (önce/sonra)
- Etki analizi
- Test sonuçları (önce/sonra)
- Rollback planı (tools/rollback komutu)
- Her iki commit SHA

**İstisna (Acil Durum Waiver):**
Kullanıcı açıkça `ACIL WAIVER: <clause_id> <gerekçe>` yazarsa 24h soğuma bir kereliğine atlanabilir. Atlanma sonrası 7 gün içinde standart C3 prosedürüyle değişiklik gözden geçirilir, onaylanmazsa geri alınır. Waiver'lar `docs/anayasa_degisiklikleri/waivers.md` içinde kayıt altında tutulur.

---

## BÖLÜM I — SAVAŞ / BARIŞ ZAMANI

| Zaman | Aralık | İzin |
|-------|--------|------|
| **Savaş Zamanı** | Hafta içi 09:30–18:15 | Sadece kanıtlı bug fix + L3 acil müdahale + log/monitor ekleme |
| **Barış Zamanı** | Hafta içi 18:15 sonrası + hafta sonu | Tüm değişiklikler |
| **Gri Bölge** | 09:15–09:30 ve 17:45–18:15 | Hiçbir değişiklik; sadece izle |

Savaş zamanında C3/C4 değişiklik yasaktır (soğuma süresi zaten bunu engeller). Savaş zamanı C2 değişiklik için kullanıcının açık yazılı "acil" onayı gerekir.

---

## BÖLÜM J — İHLAL VE YAPTIRIM

Anayasa ihlali üç kategoriye ayrılır:

| Seviye | Tanım | Sonuç |
|--------|-------|-------|
| **İ1** Teknik ihlal | Pre-commit/CI/trigger bloklaması | Otomatik red, commit reddedilir |
| **İ2** Prosedür ihlali | Onay ifadesi olmadan C2/C3 değişiklik yapılması, seal_change atlanarak commit | Değişiklik revert edilir, kayıt düşülür |
| **İ3** Bilinçli atlama | `--no-verify`, hook devre dışı bırakma, session gate bypass (`--force` gerekçesiz) | Değişiklik revert edilir, nedeni `docs/anayasa_degisiklikleri/ihlaller.md` içinde kayda geçer |

**Hook atlama teknik olarak mümkündür.** Anayasanın güvencesi son noktada kullanıcı denetimine dayanır. Bu dürüst bir sınırdır, gizlenmez.

---

## BÖLÜM K — METİN BÜTÜNLÜĞÜ

Bu metin tek başına kendini koruyamaz. Bütünlük şu mekanizmalarla sağlanır:

- Her C3 değişiklik sonrası imzalı tag
- `USTAT_ANAYASA.md` hash'i `governance/protected_assets.yaml::anayasa_sha256` alanında tutulur
- `tools/check_constitution.py` hash eşleşmesini doğrular
- Hash eşleşmezse pre-commit ve CI kırılır
- Hash'i güncellemek C3 değişiklik sayılır (anayasa değişmiş demektir)
- `governance/axioms.yaml` ↔ Bölüm C tablosu senkron tutulur; çelişki → CI halt

---

## BÖLÜM L — İLKE HİYERARŞİSİ

Çelişki durumunda öncelik sırası:
1. Bu anayasa (`USTAT_ANAYASA.md`)
2. `governance/axioms.yaml` (makine-okunur çekirdek)
3. `governance/protected_assets.yaml` (sicilin kendisi)
4. `governance/authority_matrix.yaml` + `governance/triggers.yaml` (yetki ve tetik)
5. `docs/USTAT_CALISMA_REHBERI.md` (çalışma rehberi)
6. `CLAUDE.md` (geliştirme özeti)
7. Oturum raporları ve tarihsel belgeler

Alt katman anayasayla çeliştiğinde anayasa kazanır. Çelişki tespit edilirse alt katman düzeltilir, anayasa değişmez (C3 hariç).

---

## BÖLÜM M — YÜRÜRLÜK VE SÜRÜM TARİHÇESİ

Bu anayasa `git tag ANAYASA-v3.0` imzalandığı anda yürürlüğe girer. Önceki sürümler (`docs/arsiv/USTAT_ANAYASA_v2.md`, `docs/arsiv/USTAT_ANAYASA_v1.md`) referans olarak saklanır, bağlayıcılığı yoktur.

**Sürüm Tarihçesi:**

| Sürüm | Tarih | Ana Değişim |
|-------|-------|-------------|
| v1.0 | 2026 öncesi | İlk anayasa (kilit-odaklı, "yasaklar" listesi) |
| v2.0 | 2026-04 | Yapısal revizyon; sicil `governance/protected_assets.yaml`'a taşındı; C0-C3 sınıfları; 24h soğuma; imzalı tag |
| **v3.0** | **2026-04-14** | **Operasyonel revizyon; axioms.yaml/authority_matrix.yaml/triggers.yaml makine-okunur çekirdek; session_gate + seal_change + rollback araçları; misyon modeli; C4 Siyah Kapı sınıfı; "yetki-önce" felsefesi** |

**İlk Yürürlük Commit'i:** bu dosyanın v3.0 commit'i
**İlk İmzalı Tag:** `ANAYASA-v3.0`

---

*Anayasa kısa tutulmuştur. Detay kurallar `governance/` altındadır. İşletim prosedürleri `docs/USTAT_CALISMA_REHBERI.md` içindedir. Otomasyon `tools/` altındadır. Bu metin 6 soruya cevap vermekle yetinir — gerisi sicil, tetik ve araçlarda.*
