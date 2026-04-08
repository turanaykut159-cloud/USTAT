# ÜSTAT v5.9 VADE ANALİZİ — DOSYA İNDEKSİ

**Rapor Tarihi:** 1 Nisan 2026
**Durum:** RESEARCH-ONLY (Hiçbir dosya değiştirilmemiştir)

---

## Rapor Dosyaları

### 1. VADE_OZET.txt
**Boyut:** 11 KB | **Format:** Düz metin | **Okuma Süresi:** 5 dakika

**İçerik:**
- Vade sistemi nedir? (1 sayfa)
- Rollover mekanizması (diagram)
- Sembol çevirme sistemi
- Günlük çağrı senaryoları
- Güçlü yönler (5 madde) ✓
- Zayıf yönler (4 madde) ✗
- Vade günü kaçırsa ne olur? (senaryo)
- Kritik kodsal referanslar (satır numaraları)
- Öneriler (6 madde, acil/önemli)

**Kimi için?** Hızlı özet, yöneticiler, başlangıç okuyucular

---

### 2. VADE_ANALIZ_RAPORU.md
**Boyut:** 22 KB | **Format:** Markdown | **Okuma Süresi:** 20 dakika

**İçerik:**
- **Bölüm 1:** Vade Tarihleri (VIOP_EXPIRY_DATES tanımı)
- **Bölüm 2:** Vade Geçişi Otomasyonu (6 alt bölüm)
  - 2.1: Temel mekanizma (_next_expiry_suffix)
  - 2.2: Ana rollover (_resolve_symbols) — DETAYLI
  - 2.2.1-2.2.5: Çalışma adımları (ADIM 1-6)
  - 2.3: Günlük re-resolve çağrısı
- **Bölüm 3:** Vade Günü Kontrolü (OLAY rejimi)
- **Bölüm 4:** Top-5 Kontrat Seçiminde Vade
- **Bölüm 5:** Sembol Çevirme Sistemi
- **Bölüm 6:** Vade Günü Öncesi/Günü/Sonrası (3 senaryo)
- **Bölüm 7:** Güçlü Yönler (4 madde) ✓
- **Bölüm 8:** Zayıf Yönler (4 madde + detaylı analiz) ✗
- **Bölüm 9:** Vade Günü Kaçırsa (Failure Analysis)
- **Bölüm 10:** Yapıcı Çalışma Zaman Çizelgesi
- **Bölüm 11:** Kodsal Referans Tablosu (satır, dosya, fonksiyon)
- **Bölüm 12:** Risk Mitigasyon Önerileri (5 kategori × 2-3 adım)
- **Bölüm 13:** Özet ve Sonuç

**Kimi için?** Detaylı analiz, mühendisler, system architects, risk yöneticileri

---

### 3. VADE_KOD_REFERANSLARI.md
**Boyut:** 28 KB | **Format:** Markdown + Kod | **Okuma Süresi:** 30 dakika

**İçerik:**
- **Bölüm 1:** VİOP Vade Tarihleri
  - Satır 240-254: VIOP_EXPIRY_DATES
  - Satır 257-276: validate_expiry_dates()
  - Satır 93: EXPIRY_DAYS
- **Bölüm 2:** Vade Geçişi Mekanizması (5 alt bölüm)
  - WATCHED_SYMBOLS listesi
  - Eşleme haritaları
  - _next_expiry_suffix() tam kod (Satır 268-295)
  - _resolve_symbols() tam analiz (Satır 297-434)
    - ADIM 1-7 (her adım inline kod + açıklama)
  - Günlük re-resolve çağrısı
- **Bölüm 3:** Sembol Çevirme Fonksiyonları
  - _to_mt5() (Satır 436-443)
  - _to_base() + fallback analiz (Satır 445-460)
- **Bölüm 4:** Günlük Re-Resolve Çağrısı (main.py)
- **Bölüm 5:** Vade Günü OLAY Rejimi (baba.py)
- **Bölüm 6:** Top-5 Filtreleme (top5_selection.py)
- **Bölüm 7:** Veri Alımı (get_bars, get_tick)
- **Bölüm 8:** Pozisyon Yönetimi (get_positions, close_position)
- **Bölüm 9:** Emir Gönderimi (send_order — 7 ADIM)
- **Bölüm 10:** Vade Günü Senaryo Saatleri (timeline)
- **Bölüm 11:** Kritik Satır Numaraları Özet Tablosu

**Kimi için?** Geliştiriciler, bug hunters, kodu değiştirmek isteyenler

---

## Hızlı Referans Tablosu

| Soru | Dosya | Satır | Cevap |
|------|-------|-------|-------|
| **Vade tarihleri nelerdir?** | VADE_ANALIZ_RAPORU.md | 1.1 | Set: 24 tarih (her ay son iş günü) |
| **Rollover nasıl çalışır?** | VADE_ANALIZ_RAPORU.md | 2.1-2.2 | Otomatik, günde 1 kez |
| **Hedef suffix nasıl hesaplanır?** | VADE_KOD_REFERANSLARI.md | Bölüm 2-3 | `_next_expiry_suffix()` → Satır 268 |
| **VADE_GÜNÜ ne zaman tetiklenir?** | VADE_ANALIZ_RAPORU.md | 2.2.2 | `today in VIOP_EXPIRY_DATES` → True |
| **Sembol eşleme nerede saklanır?** | VADE_KOD_REFERANSLARI.md | Bölüm 2 | `_symbol_map` (mt5_bridge.py:110) |
| **OLAY rejimi NEDEN kapalı?** | VADE_ANALIZ_RAPORU.md | 3.2 | `EXPIRY_DAYS = 0` (baba.py:93) |
| **Top-5 filtrelemesi neden çalışmaz?** | VADE_ANALIZ_RAPORU.md | 4 | Tüm parametreler `0` (top5_selection.py:83-85) |
| **Eski vade pozisyonu tanınır mı?** | VADE_KOD_REFERANSLARI.md | Bölüm 3 | EVET, fallback mekanizması (Satır 457-459) |
| **Sistem crash vade günü = ?** | VADE_ANALIZ_RAPORU.md | 9 | Kalıcı hasar, MT5'te "açık" pozisyon |
| **İlk adım ne?** | VADE_OZET.txt | Bölüm 10 | `EXPIRY_DAYS = 1` yapın |

---

## Sayısal Özetler

### Dosya Ölçüleri
- **VADE_OZET.txt:** 11 KB (11,000 karakter)
- **VADE_ANALIZ_RAPORU.md:** 22 KB (22,000 karakter)
- **VADE_KOD_REFERANSLARI.md:** 28 KB (28,000 karakter)
- **Toplam:** 61 KB (61,000 karakter metin)

### Kapsanan Kodsal Noktalar
- **Dosya sayısı:** 7 (mt5_bridge.py, baba.py, main.py, ogul.py, top5_selection.py, h_engine.py, data_pipeline.py)
- **Toplam satır referansı:** 90+ satır
- **Fonksiyon sayısı:** 15+
- **Analiz edilen skenario:** 10+

### Vade Tarihleri
- **Tanımlı vade:** 24 tarih (2025-2026)
- **ÜSTAT kontratları:** 15 adet
- **Vade geçişi yılda:** 12 kez (her ay)

---

## Bilgi Akışı Diyagramı

```
┌─────────────────────────────────────────────────────────────────┐
│ RAPOR OKUMA ROTASI                                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│ (1) BAŞLANGIÇ: VADE_OZET.txt okuyun (5 dakika)                 │
│     └─ Ne olduğu hakkında genel fikir                           │
│                                                                  │
│ (2) DETAYlar: VADE_ANALIZ_RAPORU.md okuyun (20 dakika)         │
│     └─ Her bölüm (1-6) zamanında okuyabilirsiniz               │
│     └─ Bölüm 7-8: Güçlü/zayıf yönler                            │
│                                                                  │
│ (3) KOD: VADE_KOD_REFERANSLARI.md okuyun (30 dakika)           │
│     └─ Satır numaraları ile tam kod                             │
│     └─ Eğer düzeltme yapacaksanız, BU dosyayı kullanın         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Kritik Bulgular (Executive Summary)

### Sistem Durumu
| Unsur | Durum | Risk | Çözüm |
|-------|-------|------|-------|
| **Otomatik Rollover** | ✓ Çalışıyor | Düşük | Var |
| **Sembol Eşlemesi** | ✓ Thread-safe | Düşük | Var |
| **OLAY Rejimi** | ✗ Kapalı | **YÜKSEK** | EXPIRY_DAYS=1 |
| **Top-5 Filtreleme** | ✗ Kapalı | **YÜKSEK** | Parametreleri açın |
| **Eski Vade Kapatma** | ✗ Otomatik yok | **ORTA** | Fonksiyon ekleyin |
| **Crash Dayanıklılığı** | ⚠ Hassas | **YÜKSEK** | Hard restart ekleyin |

### Acil Adımlar (İçinde 1 Hafta)
1. `EXPIRY_DAYS = 1` yapın (baba.py:93)
2. Eski vade otomatik kapanış fonksiyonu ekleyin
3. Vade günü hard restart ekleyin (09:40)

### Orta Vadeli (2-4 Hafta)
4. Dashboard vade çakışması alert'i ekleyin
5. EOD zamanını 17:30'ye alındı (vade günü)
6. Watchdog restart garantisi güçlendirilsin

---

## Dosya Erişim İzni

Tüm dosyalar **RESEARCH-ONLY** raporlarıdır:
- ✓ Okuma: Serbest
- ✓ Paylaşma: Serbest
- ✗ Düzenleme: Yapılmadı (analiz only)
- ✗ Kodda uygulanma: Önceden kontrol edin

---

## Notlar

1. **Rapor Tarihi:** 1 Nisan 2026 — Sistem v5.9.1 ile tutarlı
2. **Dil:** Türkçe (tüm belgeler)
3. **Derinlik:** Akademik + Pratik (teorik + satır referansı)
4. **Hedef Kitle:** Turan Aykut, ÜSTAT geliştirme ekibi

---

**Raporlar Hazırlandı — Analiz Tamamlandı**
