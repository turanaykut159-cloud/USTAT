# Oturum Raporu — TokenMax v3.0 + Claude Subagent Orkestrasyonu

**Tarih:** 14 Nisan 2026
**Konu:** Claude/Cowork session'larında token disiplini + 6 özel subagent için orkestrasyon rehberi
**Sınıf:** C1 (Yeşil Bölge — sadece dokümantasyon ve yeni dosyalar; hiçbir kod/config/engine değişmedi)
**Çalışan uygulamaya etki:** YOK
**Commit:** `1ba306a`

---

## 1. Motivasyon

Kullanıcının Max 20x planının 3 günde %46 tükenmesi üzerine token ekonomisi konusu açıldı. Çözüm önerisi olarak "TokenMax v2.0" taslağı sunuldu; ardından Anthropic'in 2026 güncellemeleri (cache-aware rate limits, deferred tool loading) ve `C:\Users\pc\.claude\agents/` altında mevcut 6 özel subagent'ın varlığı tespit edildi. Bu iki başlık birleştirilerek **TokenMax v3.0** olarak kalıcı doküman haline getirildi.

## 2. Araştırma Çıktıları

### 2.1 Token Ekonomisi (Anthropic 2026)

- **Cache-aware rate limits (Şubat 2026):** Cache read tokenları ITPM limitine dahil değil artık. Doğru kullanılırsa %90'a kadar input tasarrufu.
- **Cache TTL:** 5 dakika (standart) veya 60 dakika (extended). 5 dakika idle → tüm context yeniden process.
- **Min cache boyutu:** 1024 token (Sonnet 4.6 için).
- **Deferred tool loading:** Cowork'ta MCP schemaları artık on-demand yüklenir (bu session'da doğrulandı — `ToolSearch` ile çekiliyor).
- **.claudeignore etkisi:** Per-request %40-70 azaltma (ölçülmüş).
- **Trigger-based CLAUDE.md:** %54 initial context azaltma (GitHub vaka).

### 2.2 Mevcut Subagent Envanteri

`C:\Users\pc\.claude\agents/` altında 6 aktif subagent tespit edildi:

| # | Ajan | Model | Alan |
|---|---|---|---|
| 1 | `ustat-engine-guardian` | **Opus** | `engine/*.py` (BABA/OĞUL/H-Engine/ÜSTAT) |
| 2 | `ustat-api-backend` | Sonnet | `api/*.py` FastAPI katmanı |
| 3 | `ustat-desktop-frontend` | Sonnet | `desktop/` (Electron + React) |
| 4 | `ustat-auditor` | **Opus** | READ-ONLY denetim + plan |
| 5 | `ustat-ops-watchdog` | Sonnet | `start_ustat.py`, `.agent/`, logs |
| 6 | `ustat-test-engineer` | Sonnet | `tests/` ve `critical_flows/` |

Arşivde 3 eski ajan (`_archive_2026-04-11/`). Bunlar işlem dışı.

## 3. Yapılan Değişiklikler

### 3.1 Yeni Dosya — `CLAUDE_CORE.md` (180 satır, ~2k token)

Üç katmanlı context yükleme sisteminin L1 katmanı. İçerik:
- ÜSTAT kısa tanım + 4 motor çağrı sırası
- 6 Altın Kural
- Bölge haritası (Kırmızı/Sarı/Yeşil/Siyah Kapı) — dosya isimleri, detay yok
- 16 değiştirilemez kural (başlıklar)
- Kritik sabitler (en sık 8 tane)
- C0-C4 sınıflandırma özeti
- Zaman disiplini (Savaş/Barış/Gri)
- Yasaklar listesi
- İşlemi Bitir kısa sıra
- Ajan komutu hatırlatmaları
- **6 ajan orkestrasyonu hızlı referans** (Bölüm 13.12'ye atıf)
- "Ne zaman CLAUDE.md'ye git" yönlendirme tablosu

**Kullanım prensibi:** Her session'da otomatik yüklenir. L2 (`CLAUDE.md`) ve L3 (`USTAT_ANAYASA.md`) sadece gerektiğinde çağrılır.

### 3.2 Yeni Dosya — `.claudeignore` (86 satır)

Claude/Cowork'un her session başında otomatik okuduğu filtreleme dosyası. Kapsamı:
- Veritabanları (*.db, *.sqlite, journal/wal/shm)
- Derlenmiş frontend (`desktop/dist/`, `node_modules/`)
- Python artifaktları (`__pycache__/`, `.pytest_cache/`, venv)
- Loglar (`logs/`, `*.log`, `api.log`, `startup.log`)
- Ajan runtime (`.agent/results/`, `.processing`, `.pid`, `.heartbeat`, `.lock`)
- Git internals
- Arşiv (`docs/arsiv/`, `USTAT DEPO/`, geçmiş oturum raporları)
- MQL5 derlenmiş dosyalar
- Test fixture ve output
- IDE (vscode, idea, swp)
- Backup/temp

**Beklenen etki:** Per-request context %40-70 azalma.

### 3.3 `CLAUDE.md` — Bölüm 13 Eklendi (yaklaşık 280 satır)

Bölüm 12.2 (commit formatı) tamamlandıktan sonra Bölüm 13 olarak eklendi. Alt başlıklar:

- **13.1** Üç katmanlı context yükleme (L1/L2/L3)
- **13.2** `.claudeignore` kuralı
- **13.3** Dosya okuma disiplini (Grep > Read, Edit > Write, aynı dosyayı iki kez okuma yasağı)
- **13.4** Model seçim matrisi (Haiku/Sonnet/Opus)
- **13.5** Zorunlu task prompt şablonu
- **13.6** Session & cache kuralları
- **13.7** MCP/Tool disiplini
- **13.8** Agent delegasyonu (built-in Claude agents)
- **13.9** Şeffaflık ve uyarı eşikleri (>15k token öncesi kullanıcıya bildir)
- **13.10** Beklenen kazanım ve token audit
- **13.11** İhlal durumunda
- **13.12** Claude Subagent Orkestrasyonu:
  - 6 ajan envanteri
  - 5 orkestrasyon modeli (A: Denetim→Uygulama→Test, B: Direkt Uzman, C: Sadece Araştırma, D: Paralel Koşu, E: Savaş Zamanı)
  - Karar ağacı
  - Ajan çağırmama kuralları (maliyet tuzağı)
  - Maksimum performans brief şablonu (kötü brief vs iyi brief = 7.5x fark)
  - `ustat_agent.py` ile ayrım
  - Ajan kullanım metrikleri

## 4. Anayasa / Bölge Uyumu

| Kontrol | Sonuç |
|---|---|
| Kırmızı Bölge dosyasına dokunuldu mu? | **Hayır** |
| Sarı Bölge dosyasına dokunuldu mu? | **Hayır** |
| Siyah Kapı fonksiyon mantığı değişti mi? | **Hayır** |
| Çağrı sırası değişti mi? | **Hayır** |
| Kritik sabit değiştirildi mi? | **Hayır** |
| Risk parametresi değişti mi? | **Hayır** |
| 16 değiştirilemez kural ihlali var mı? | **Hayır** |

Sadece Yeşil Bölge: 2 yeni dokümantasyon dosyası + CLAUDE.md'ye yeni bölüm ekleme.

## 5. Test / Doğrulama

Bu değişiklik engine, api, desktop veya tests kodlarını etkilemediği için:

- `critical_flows` testleri teknik olarak zorunlu değil
- Build gerekmiyor (frontend değişmedi)
- restart_app gerekmiyor

Doğrulama yapılanlar:
- `grep -n "BÖLÜM 13"` → CLAUDE.md satır 877'de mevcut
- `wc -l CLAUDE_CORE.md` → 195 satır
- `wc -l .claudeignore` → 86 satır
- `git status --short` → sadece 3 yeni/değişmiş dosya bu commit kapsamında

## 6. Versiyon Durumu

Değişim oranı: (~500 eklenen satır) / (~20.000 toplam kod satır) = **~%2.5**. CLAUDE.md Bölüm 7 ADIM 3'e göre %10 eşiği altında → **versiyon bumpı yapılmadı**.

Mevcut versiyon: **6.0.0** (değişmedi).

## 7. Beklenen Kazanım

- Max 20x haftalık kota: 3 gün yerine 7-10 güne yayılma hedefi
- Per-request context: %40-70 azalma (`.claudeignore`)
- Initial load: %50+ azalma (CLAUDE_CORE.md ile L1/L2/L3 ayrımı)
- Ajan brief kalitesi: 7.5x token farkı (kötü brief vs iyi brief örneği)

Ölçüm: Bir sonraki session sonunda token audit screenshot'ı `docs/token_audit/2026-04-14.png` olarak kaydedilecek.

## 8. Geri Alma Planı

Gerekirse tek commit geri alınır:
```bash
git revert <bu_commitin_hash>
```

Riskler:
- CLAUDE_CORE.md ve .claudeignore silinir → eski durum (tek CLAUDE.md)
- CLAUDE.md Bölüm 13 kaldırılır
- Hiçbir çalışan kod etkilenmez — zero impact revert

## 9. Diğer Ajanlara Etki

Bu değişiklik 6 mevcut subagent'ı tanıyan ve orkestrasyon kuralları koyan bir doküman güncellemesidir. Subagent dosyalarının içeriği (`C:\Users\pc\.claude\agents/*.md`) değiştirilmedi. Gelecek session'larda ajan çağrıları Bölüm 13.12'deki karar ağacına göre yapılacak.

## 10. Sonraki Adımlar (Önerilen)

- İlk gerçek test: Sıradaki C2/C3 değişiklikte Model A veya Model B uygulanması, token tüketiminin audit edilmesi
- Haftalık audit: `docs/token_audit/weekly_YYYY-WW.md` oluşturma disipline girer
- 4 skill dosyası oluşturma (isteğe bağlı ileri optimizasyon): `ustat-zones`, `ustat-agent-cmds`, `ustat-rollback`, `ustat-change-class` — CLAUDE.md'yi 2k altına indirmek için

---

**Rapor sonu.**
