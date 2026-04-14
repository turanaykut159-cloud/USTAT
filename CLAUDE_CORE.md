# ÜSTAT v5.9 — CORE (Hızlı Referans)

**Tam rehber:** `CLAUDE.md` | **Anayasa:** `USTAT_ANAYASA.md`
**Kullanım:** Bu dosya her session'ın ilk yükleme katmanıdır. Detay için CLAUDE.md'deki ilgili bölüme git.

---

## NE: ÜSTAT v5.9

VİOP üzerinde GCM Capital + MT5 üzerinden **gerçek para ile** işlem yapan algoritmik trading platformu. Her hata = finansal zarar. Kurallar istisnasız.

**Teknoloji:** Python 3.14 engine + FastAPI (port 8000) + React/Vite + Electron 33 + SQLite + MT5 API.

---

## DÖRT MOTOR — ÇAĞRI SIRASI DEĞİŞTİRİLEMEZ

Her 10 saniyede, SABİT sırayla:

```
heartbeat → data_pipeline → BABA → risk_check → OĞUL → H-Engine → ÜSTAT
```

| Motor | Görev | Dosya |
|---|---|---|
| BABA | Risk, kill-switch, rejim | `engine/baba.py` |
| OĞUL | Top5, sinyal, emir, pozisyon | `engine/ogul.py` |
| H-Engine | Hibrit yönetim (BE, trailing, EOD) | `engine/h_engine.py` |
| ÜSTAT | Hata atfet, strateji, analiz | `engine/ustat.py` |

---

## 6 ALTIN KURAL

1. **ÖNCE ANLA** — kodu oku, "herhalde" yasak
2. **SONRA ARAŞTIR** — log'dan kanıt, screenshot değil
3. **RUNTIME DOĞRULA** — hangi dosya GERÇEKTEN çalışıyor (`startup.log` + process check)
4. **ETKİYİ ÖLÇ** — çağrı zinciri, tüketici, veri akışı
5. **TEST ET** — "çalışıyor gibi" yetmez
6. **SON UYGULA** — tüm kontroller tamamsa

---

## BÖLGE HARİTASI (3 Katman)

### 🔴 KIRMIZI BÖLGE — 10 Dokunulmaz Dosya (Çift Doğrulama)
`baba.py`, `ogul.py`, `mt5_bridge.py`, `main.py`, `ustat.py`, `database.py`, `data_pipeline.py`, `config/default.json`, `start_ustat.py`, `api/server.py`

### 🟡 SARI BÖLGE — 7 Dikkatli Dosya (Standart Onay)
`h_engine.py`, `config.py`, `logger.py`, `killswitch.py`, `positions.py`, `desktop/main.js`, `mt5Manager.js`

### 🟢 YEŞİL BÖLGE — Diğer tüm dosyalar (Standart süreç)

### ⚫ SİYAH KAPI — 31 Değiştirilemez Fonksiyon
Mantığı değiştirilemez. Sadece kanıtlı bug fix + performans (mantık sabit) + güvenlik katmanı eklemesi izinli.
**Tam liste:** CLAUDE.md Bölüm 4.4

---

## 16 DEĞİŞTİRİLEMEZ KURAL (Başlıklar)

1. Çağrı Sırası SABİT
2. Risk Kapısı (can_trade=False → sinyal yok)
3. Kill-Switch Monotonluk (sadece yukarı)
4. SL/TP Zorunlu (başarısız → pozisyon kapat)
5. EOD 17:45 Zorunlu Kapanış
6. Hard Drawdown ≥%15 → L3
7. OLAY Rejimi → risk_multiplier=0
8. Circuit Breaker (5 timeout → 30sn blok)
9. Fail-Safe (şüphede kilitli)
10. Günlük Kayıp → L2 → `_close_ogul_and_hybrid` (manuel dokunulmaz)
11. Startup Zinciri SABİT
12. Lifespan Constructor Sırası SABİT
13. Kapanış Sırası: Electron → lifespan → MT5 → DB
14. API port hazır ≤5sn
15. MT5 Başlatma SADECE Electron'da
16. `mt5.initialize()` Evrensel Koruma

**Detay:** CLAUDE.md Bölüm 4.5

---

## KRİTİK SABİTLER (En Sık İhtiyaç)

| Sabit | Değer | Nerede |
|---|---|---|
| Günlük maks kayıp | %1.8 | config/default.json |
| Hard drawdown | %15 | config/default.json |
| Döngü aralığı | 10sn | engine/main.py |
| MT5 timeout | 8sn | engine/mt5_bridge.py |
| Circuit breaker | 5 fail / 30sn | engine/mt5_bridge.py |
| EOD zamanı | 17:45 | engine/ogul.py |
| Risk per trade | %1 | config/default.json |
| Max pozisyon | 5 | config/default.json |

**Tam tablo:** CLAUDE.md Bölüm 5

---

## DEĞİŞİKLİK SINIFLANDIRMA (C0-C4)

| Sınıf | Tanım | Onay |
|---|---|---|
| C0 | Dokümantasyon/yorum | Gereksiz |
| C1 | Yeşil Bölge kod | Standart |
| C2 | Sarı Bölge | Bölüm 3.3 adımları |
| C3 | Kırmızı Bölge | Çift doğrulama |
| C4 | Siyah Kapı | Üçlü onay (kanıt+plan+sonuç) |

---

## ZAMAN DİSİPLİNİ

| Zaman | Saat | İzin |
|---|---|---|
| SAVAŞ | Hft içi 09:30-18:15 | SADECE kanıtlı bug fix / L3 |
| BARIŞ | 18:15 sonrası + haftasonu | Her şey |
| GRİ | 09:15-09:30 + 17:45-18:15 | HİÇBİR ŞEY |

---

## KESİN YASAKLAR

- Varsayım ("herhalde") / olasılık listesi / copy-paste çözüm
- Birden fazla sorunu aynı atomik değişiklikte çözmek
- Test etmeden commit
- Sihirli sayı (sabitler config'den)
- Fonksiyon silme (özellikle Siyah Kapı)
- Çağrı sırası değiştirme
- "Geçici devre dışı"
- Silent error (try/except pass)
- `USTAT DEPO/` klasörünü referans almak

---

## DEĞİŞİKLİK SONRASI (İŞLEMİ BİTİR) — Kısa Sıra

1. Frontend değiştiyse `build` çalıştır (yoksa Electron eski dist'i yükler)
2. `pytest tests/critical_flows -q` → YEŞİL olmalı
3. `docs/USTAT_GELISIM_TARIHCESI.md`'ye giriş ekle
4. %10 üstü değişim → versiyon artır (Bölüm 7 güncelleme noktaları)
5. Git commit (dosya dosya add, `.` YASAK)
6. Oturum raporu: `docs/YYYY-MM-DD_session_raporu_*.md`

---

## AJAN KOMUTU HATIRLATMALARI (37 komut)

Sık kullanılanlar:
- `python .agent/claude_bridge.py tail_log` — son loglar
- `python .agent/claude_bridge.py build` — production derleme
- `python .agent/claude_bridge.py restart_app` — akıllı restart
- `python .agent/claude_bridge.py status` — sistem durumu
- `python .agent/claude_bridge.py db_query "SELECT ..."` — sadece SELECT

**Tam liste:** CLAUDE.md Bölüm 11.2

---

## CLAUDE SUBAGENT ORKESTRASYONU (Hızlı)

6 özel ajan (`C:\Users\pc\.claude\agents/`). Her biri ayrı context, ana session şişmez.

| Ajan | Model | Alan |
|---|---|---|
| `ustat-engine-guardian` | Opus | `engine/*.py` implementasyon |
| `ustat-api-backend` | Sonnet | `api/*.py` routes/schemas |
| `ustat-desktop-frontend` | Sonnet | `desktop/` (build ZORUNLU) |
| `ustat-auditor` | Opus | READ-ONLY denetim + plan |
| `ustat-ops-watchdog` | Sonnet | startup/logs/.agent |
| `ustat-test-engineer` | Sonnet | tests/critical_flows |

**5 Model:** A=Denetim→Uygulama→Test (C3/C4) · B=Direkt Uzman (C1/C2) · C=Sadece Araştırma · D=Paralel · E=Savaş Zamanı

**Kural:** İş <3k token ise ajana atma (brief maliyeti kazancı yer). İyi brief = 7.5x token tasarrufu.

**Detay:** CLAUDE.md Bölüm 13.12

---

## NE ZAMAN CLAUDE.md'YE GİT

| Konu | Bölüm |
|---|---|
| 4 motor detayı, piyasa rejimleri, stratejiler | 2 |
| Altı Altın Kural açıklaması, yasaklar | 3 |
| Anayasa tam (Kırmızı/Sarı/Siyah Kapı/16 kural) | 4 |
| Tüm sabitler (risk + sistem) | 5 |
| Bağımlılık haritası | 6 |
| İşlemi bitir (tam) | 7 |
| Rollback | 8 |
| C0-C4 checklist | 9 |
| Klasör/Depo erişim kuralları | 10 |
| Ajan 37 komut | 11 |
| Git commit formatı | 12 |
| **Token disiplini (yeni)** | **13** |

---

**Son söz:** Şüphe varsa CLAUDE.md oku. Bu dosya özetten ibarettir, kaynak değildir.
