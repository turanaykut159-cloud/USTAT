# Anayasa v2 → v3 Geçiş Haritası

**Tarih:** 2026-04-14
**Kapsam:** `USTAT_ANAYASA.md` v2.0 → v3.0

## Felsefe Değişimi

| v2.0 | v3.0 |
|------|------|
| Kilit-odaklı ("neye dokunulmaz") | Yetki-odaklı ("kim, nerede, nasıl dokunur") |
| Savunmacı kurallar listesi | Savunmacı + etkinleştirici (kural ↔ otomasyon eşlenik) |
| Metin tek başına | Metin + `governance/*.yaml` + `tools/*` zinciri |
| 3 değişiklik sınıfı (C0–C3) | 4 değişiklik sınıfı (C0–C4, Siyah Kapı ayrıldı) |

## Bölüm Bazlı Değişimler

| v2 Bölüm | v3 Bölüm | Değişim |
|----------|----------|---------|
| A — Amaç | A — Amaç ve Felsefe | "Felsefe özeti" paragrafı eklendi; 2. soru "Yetki Matrisi"ne bağlandı |
| B — Otorite | B — Otorite | Yetki Matrisi (`authority_matrix.yaml`) referansı eklendi; 4 yetki seviyesi tanımlandı |
| C — Çekirdek | C — Çekirdek (Axioms) | CI-XX tablosuna **Axiom ID** kolonu (AX-1..7) eklendi; `governance/axioms.yaml` eşlemesi |
| D — Sınıflar | D — Sınıflar + Triggers | **C4 Siyah Kapı** sınıfı eklendi; Guard Trigger tablosu eklendi |
| E — Korunan Varlıklar | E — Korunan Varlıklar + Rollback | `tools/rollback/*` araçları tablosu eklendi; rollback planı zorunluluğu netleştirildi |
| F — Teknik | F — Enforcement Zinciri | **Session Gate** ve **Commit Seal** adımları eklendi |
| — (yeni) | **G — Misyon Modeli** | Tamamen yeni bölüm |
| G — Savaş/Barış | I — Savaş/Barış | Bölüm numarası değişti; C4 eklenince savaş zamanı yasağı genişletildi |
| H — Değişiklik Rejimi | H — Değişiklik Rejimi | Aynı; `tools/rollback` referansı eklendi |
| I — İhlal | J — İhlal | Session gate bypass İ3 kapsamına eklendi; seal_change atlama İ2 |
| J — Bütünlük | K — Metin Bütünlüğü | `axioms.yaml` ↔ Bölüm C senkron check eklendi |
| K — Hiyerarşi | L — Hiyerarşi | 5 katmandan 7 katmana çıktı (axioms, authority, triggers ayrıldı) |
| L — Yürürlük | M — Yürürlük + Sürüm Tarihçesi | Sürüm tarihçesi tablosu eklendi |

## Yeni Altyapı Dosyaları (Faz 1'de oluşturuldu)

| Dosya | Görev |
|-------|-------|
| `.gitattributes` | Satır sonu politikası (LF/CRLF normalization) |
| `governance/axioms.yaml` | 7 dokunulmaz çekirdek makine-okunur |
| `governance/authority_matrix.yaml` | Zone × Class × Action → Authority |
| `governance/triggers.yaml` | Guard triggers (halt/escalate) |
| `tools/session_gate.py` | Oturum açılış kapısı (lock, workspace, branch) |
| `tools/check_triggers.py` | Dosya/diff taraması, trigger değerlendirme |
| `tools/seal_change.py` | Commit seremonisi (6 adım) |
| `tools/rollback/commit.sh` | Tek commit revert |
| `tools/rollback/mission.sh` | Misyon toplu revert |
| `tools/rollback/workspace.sh` | Kirli workspace temizliği |
| `tools/rollback/db.sh` | DB yedek/geri yükleme |

## CI-XX ↔ Axiom ID Eşlemesi

Bölüm C tablosuna eklenen axiom ID kolonu ikili referansı sağlar:

- CI-01 ↔ AX-2 (can_trade gate)
- CI-02 ↔ AX-3 (kill-switch monotonicity)
- CI-03 ↔ AX-4 (SL/TP requirement)
- CI-04 ↔ AX-5 (EOD closure)
- CI-05 ↔ AX-6 (hard drawdown)
- CI-07 ↔ AX-1 (call order)
- CI-09 ↔ AX-7 (mt5.initialize single source)

CI-06 (OLAY rejimi), CI-08 (MT5 başlatma), CI-10 (fail-closed) — v3'te axiom listesine eklenmedi, sadece insan-okunur metinde. Bir sonraki revizyonda axioms.yaml'a alınması değerlendirilir.

## Geri Uyumluluk

- v2 onay ifadeleri (`ANAYASA ONAYI:`, `ANAYASA TEYİDİ:`) v3'te **aynen geçerlidir**
- v2 CI-01..10 numaraları **değişmedi**; sadece axiom ID kolonu eklendi
- v2'de tanımlı 24h soğuma **aynen** korundu
- v2 protected_assets.yaml sicilindeki kayıtlar **bozulmadı**

## Geçiş Adımları

1. `docs/arsiv/USTAT_ANAYASA_v2.md` — v2 metni arşivlendi (HEAD'den alındı, 767 satır)
2. `USTAT_ANAYASA.md` — v3.0 yazıldı
3. `governance/protected_assets.yaml::anayasa_sha256` alanı güncellenmeli (v3 hash)
4. `git tag -a ANAYASA-v3.0 -m "..."` imzalı tag atılmalı
5. CLAUDE.md referans satırı v3.0 olarak güncellenmeli

## Rollback Planı

v3'te kritik sorun tespit edilirse:

```bash
# Anayasa dosyasını v2'ye geri al
cp docs/arsiv/USTAT_ANAYASA_v2.md USTAT_ANAYASA.md
git add USTAT_ANAYASA.md
git commit -m "revert: anayasa v3 -> v2 (kritik sorun: <gerekçe>)"

# Tag sil
git tag -d ANAYASA-v3.0

# Yeni altyapı dosyaları durabilir (v3 özgü değil, genel iyileştirme)
# İstenirse: git rm tools/session_gate.py tools/check_triggers.py ... governance/axioms.yaml ...
```
