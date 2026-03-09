# ÜSTAT v5.2 — Monitor Birleştirme Raporu

**Tarih:** 2026-03-09
**Konu:** `SİSTEM SAĞLIĞI.txt` (Monitor bileşeni) ile mevcut uygulama karşılaştırması

---

## 1. GENEL BAKIŞ

| | Monitor (SİSTEM SAĞLIĞI.txt) | Mevcut Uygulama |
|---|---|---|
| **Yapı** | Tek bileşen, 354 satır | 16 bileşen, ~7.325 satır |
| **Veri Kaynağı** | Hardcoded + random (simülasyon) | API (REST + WebSocket, gerçek veri) |
| **Tasarım** | Koyu tema, monospace, neon renkler, animasyonlu | CSS class tabanlı, light/dark tema desteği |
| **Kullanım** | Bağımsız demo/vitrin | Tam fonksiyonel üretim uygulaması |

---

## 2. BÖLÜM BÖLÜM KARŞILAŞTIRMA

### 2.1 HEADER — Sistem Durumu Çubuğu

| Özellik | Monitor | Mevcut (TopBar.jsx) |
|---|---|---|
| Logo / Başlık | "ÜSTAT · System Monitor" | "ÜSTAT v5.2" |
| Saat | Dijital saat (sağ üst) | Tarih + saat (sağ) |
| Sistem Aktif göstergesi | Yeşil nokta + "SİSTEM AKTİF" animasyonlu | Faz etiketi (AKTİF/PASİF/DURDURULDU) |
| VİOP piyasa durumu | "VİOP AÇIK/KAPALI/PRE-MARKET" renkli | **YOK** |
| Kill-Switch seviyesi | Yok (header'da) | L0-L3 göstergesi + sıfırla butonu |
| MT5 bağlantı | Yok (header'da) | Yeşil/kırmızı nokta + "MT5" / "Bağlantı Yok" |
| Finansal veriler | Yok (header'da) | Bakiye, Equity, Floating, Günlük K/Z |
| Pin (always on top) | Yok | Var |

**Monitor'ün Getirdiği Yeni:**
- VİOP piyasa durumu göstergesi (AÇIK/KAPALI/PRE-MARKET) — saat bazlı otomatik
- Animasyonlu sistem durumu noktası

**Mevcut'ün Avantajı:**
- Gerçek MT5 verisi, kill-switch kontrolü, finansal özet — çok daha fonksiyonel

---

### 2.2 STATS BAR — Üst Özet Kartları

| Kart | Monitor | Mevcut (Dashboard.jsx) |
|---|---|---|
| Günlük P&L | ✅ "+4.280 TL" (hardcoded) | ✅ "Günlük K/Z" (gerçek, WS) |
| Aktif Pozisyon | ✅ "3" | ✅ Pozisyon tablosunda |
| Drawdown | ✅ "%0.8" | RiskManagement.jsx'da detaylı |
| MT5 Ping | ✅ "12ms" | SystemHealth.jsx'da |
| SQLite Lag | ✅ "3.2ms" | **YOK** (health API'de mevcut değil) |
| Uptime | ✅ "%99.2" | SystemHealth.jsx'da |
| İşlem Sayısı | Yok | ✅ Dashboard'da |
| Başarı Oranı | Yok | ✅ Dashboard'da |
| Profit Factor | Yok | ✅ Dashboard'da |

**Monitor'ün Getirdiği Yeni:**
- Tek bakışta 6 kritik metriği gösterme yaklaşımı (P&L, pozisyon, drawdown, ping, lag, uptime)
- SQLite yazma gecikmesi göstergesi

**Mevcut'ün Avantajı:**
- Gerçek API verisi, WS canlı güncelleme, daha detaylı istatistikler

---

### 2.3 FLOW DIAGRAM — Modül Mimarisi Diyagramı ⭐ YENİ

| Özellik | Monitor | Mevcut |
|---|---|---|
| Görsel modül diyagramı | ✅ BABA → OĞUL → ÜSTAT → H-ENGINE → MANUEL → HİBRİT | **MEVCUT DEĞİL** |
| MT5 bağlantı kutusu | ✅ (üstte, bağlantı/ping/sunucu/hesap) | **MEVCUT DEĞİL** |
| Modül arası ok animasyonları | ✅ (flowH/flowV gradient animasyonları) | **MEVCUT DEĞİL** |
| Her modülde metrik | ✅ (kill-switch seviyesi, sinyal sayısı, kontrat sayısı vb.) | SystemHealth'de katman kartları var ama GÖRSEL DEĞİL |
| Modül durum göstergesi | ✅ (ok/warn/err renkli nokta) | SystemHealth'de metin tabanlı |

**Bu tamamen yeni bir özellik.** Mevcut uygulamada hiçbir yerde modüller arası veri akışını gösteren görsel bir diyagram yok.

**Mevcut'ten Alınacak Veri:**
- `GET /api/health` → `layers` bölümü (BABA rejim/kill-switch, OĞUL aktif işlem, H-Engine hibrit sayısı, ÜSTAT son çalışma)
- `GET /api/status` → engine_running, mt5_connected, kill_switch_level
- WS equity mesajları → canlı güncelleme

---

### 2.4 SIGNAL FLOW TABLE — Sinyal Akış Tablosu ⭐ YENİ

| Özellik | Monitor | Mevcut |
|---|---|---|
| Sinyal akış tablosu | ✅ ZAMAN, KAYNAK, KONTRAT, YÖN, BABA ONAY, MOTOR, MT5, MS | **MEVCUT DEĞİL** |
| Kaynak renklendirme | ✅ OĞUL=turuncu, MANUEL=pembe, HİBRİT=mor | **MEVCUT DEĞİL** |
| BABA onay/red gösterimi | ✅ ONAY=yeşil, RED=kırmızı | **MEVCUT DEĞİL** |
| MT5 FILLED/RED durumu | ✅ Renkli | **MEVCUT DEĞİL** |
| Milisaniye gösterimi | ✅ İşlem süresi ms cinsinden | **MEVCUT DEĞİL** |

**Bu tamamen yeni bir özellik.** Mevcut uygulamada:
- `Dashboard.jsx` → "Son İşlemler" tablosu var ama bu KAPANMIŞ işlemleri gösteriyor
- `SystemLog.jsx` → Olayları gösteriyor ama sinyal akış formatında değil
- Sinyal → BABA onay → Motor → MT5 akışını gösteren bir tablo **yok**

**Backend'de Gerekecek:**
- Yeni bir API endpoint veya mevcut event_bus'a sinyal akış verisi eklenmesi
- Her sinyal için: kaynak (OĞUL/MANUEL/HİBRİT), kontrat, yön, BABA kararı, motor ataması, MT5 sonucu, süre (ms)

---

### 2.5 SİSTEM LOG AKIŞI (Alt Sol)

| Özellik | Monitor | Mevcut (SystemLog.jsx) |
|---|---|---|
| Görünüm | Kompakt, streaming tarzı, renkli satırlar | Tablo formatı, filtreli |
| Renk kodlaması | ok=yeşil, info=mavi, warn=turuncu, error=kırmızı | Severity badge'leri (CSS class) |
| Filtreleme | Yok | ✅ Severity + Tip filtresi |
| Sayaç/Özet | Yok | ✅ Toplam/Kritik/Hata/Uyarı/Bilgi sayaçları |
| Olay tipleri | 8 sabit mesaj havuzu | ✅ 25+ olay tipi, DB'den gerçek veri |
| Yenileme | 3.5sn random | 10sn polling, gerçek API |
| Kapasite | Son 18 log | Son 500 olay |

**Mevcut çok daha üstün.** Monitor'ün log bölümü sadece görsel olarak kompakt/streaming tarzı.

**Monitor'den Alınabilecek:**
- Kompakt streaming görünüm modu (opsiyonel toggle)

---

### 2.6 PERFORMANS / RESPONSE TIME (Alt Orta)

| Özellik | Monitor | Mevcut (SystemHealth.jsx) |
|---|---|---|
| Response time barları | ✅ BABA Karar, OĞUL Yürütme, MT5 Ulaşım, Toplam | ✅ Motor döngü adım breakdown (10 adım) |
| Thread durumu | ✅ TICK, M1, SPREAD (durum + son + yazma sayısı) | **YOK** |
| Mini trend grafik | Yok | ✅ Son 60 döngü bar chart |
| Emir performansı | Yok | ✅ Ort süre, başarılı/ret/timeout, son 10 emir tablosu |
| MT5 bağlantı sağlığı | Yok | ✅ Ping, kopma sayısı, reconnect geçmişi |

**Monitor'ün Getirdiği Yeni:**
- **Thread durumu gösterimi** (TICK, M1, SPREAD thread'leri) — mevcut uygulamada yok
- Response time'ı "BABA Karar → OĞUL Yürütme → MT5 Ulaşım → Toplam" şeklinde anlamlı pipeline olarak gösterme

**Mevcut'ün Avantajı:**
- 10 adımlı döngü breakdown, trend grafik, emir tablosu, MT5 reconnect geçmişi

**Backend'de Gerekecek (Thread durumu için):**
- `GET /api/health` yanıtına `threads` bölümü eklenmesi

---

### 2.7 RİSK & KİLL-SWİTCH (Alt Sağ)

| Özellik | Monitor | Mevcut (RiskManagement.jsx) |
|---|---|---|
| Kill-Switch seviyeleri | ✅ L1/L2/L3 görsel kutular (UYARI/DURDUR/KRİTİK) | ✅ Durum banner (metin) |
| Drawdown barları | ✅ Günlük DD (1 bar) | ✅ Günlük + Haftalık + Aylık + Hard + Floating (5 bar) |
| Eşik gösterimi | ✅ L1=%1.0, L2=%1.5, L3=%2.0 doluluk | ✅ Sayısal oran gösterimi |
| Hata sayacı (modül bazlı) | ✅ OĞUL:3, H-ENGINE:1, HİBRİT:2 vb. | **YOK** |
| İşlem izni | Yok | ✅ AÇIK/KAPALI + neden |
| Rejim | Yok | ✅ TREND/RANGE/VOLATILE/OLAY + lot çarpanı |
| Sayaçlar | Yok | ✅ Günlük işlem, üst üste kayıp, cooldown, pozisyon |
| Anlık PnL detay | Yok | ✅ Günlük K/Z, Floating, Bakiye, Toplam DD |

**Monitor'ün Getirdiği Yeni:**
- **Modül bazlı hata sayacı** (BABA, OĞUL, ÜSTAT, H-ENGINE, MANUEL, HİBRİT) — mevcut uygulamada yok
- Kill-switch seviyelerinin 3 ayrı görsel kutu olarak gösterimi (L1/L2/L3 eşikleriyle)

**Mevcut çok daha kapsamlı** risk yönetimi sunuyor.

---

## 3. ÖZET: NE YENİ, NE ÖRTÜŞÜYOR, NE EKSİK?

### ⭐ Monitor'ün Getirdiği TAMAMEN YENİ Özellikler

| # | Özellik | Açıklama | Backend Gereksinimi |
|---|---------|----------|---------------------|
| 1 | **Modül Mimarisi Diyagramı** | BABA → OĞUL → ÜSTAT → H-ENGINE → MANUEL → HİBRİT görsel akış, animasyonlu oklar, her modülde canlı metrik | Mevcut `/api/health` layers verisi yeterli |
| 2 | **Sinyal Akış Tablosu** | Sinyal → BABA onay → Motor → MT5 akışını canlı gösteren tablo | **Yeni API endpoint veya event genişletme gerekli** |
| 3 | **Thread Durumu** | TICK, M1, SPREAD thread'lerinin durumu, son çalışma, yazma sayısı | **Health API'ye thread bilgisi eklenmeli** |
| 4 | **Modül Bazlı Hata Sayacı** | Her modülün bugünkü hata sayısı (6 modül) | **Health API'ye error_counts eklenmeli** |
| 5 | **VİOP Piyasa Durumu** | AÇIK/KAPALI/PRE-MARKET göstergesi | Frontend'de hesaplanabilir (saat bazlı) |

### 🔄 ÖRTÜŞEN Özellikler (Monitor vs Mevcut)

| Özellik | Monitor'deki | Mevcut'teki | Kazanan |
|---------|-------------|-------------|---------|
| Günlük P&L | Stats bar kartı | Dashboard + TopBar | **Mevcut** (gerçek veri, WS) |
| MT5 Ping | Stats bar kartı | SystemHealth MT5 bölümü | **Mevcut** (ping/kopma/reconnect) |
| Uptime | Stats bar kartı | SystemHealth sistem bölümü | **Mevcut** (cycle sayısı, DB boyutu dahil) |
| Drawdown barları | 1 bar (günlük) | 5 bar (günlük/haftalık/aylık/hard/floating) | **Mevcut** (çok daha kapsamlı) |
| Kill-Switch | 3 kutu (L1/L2/L3) | Banner + TopBar | **Berabere** (farklı görselleştirme) |
| Sistem logları | Streaming 18 satır | Tablo 500 olay + filtre | **Mevcut** (fonksiyonel) |
| Katman durumu | Modül kutuları (6 modül) | Katman kartları (4 modül) | **Monitor** (daha görsel, 6 modül) |
| Response time | Pipeline barları | Adım breakdown + trend | **Mevcut** (daha detaylı) |

### ❌ Monitor'de OLMAYAN ama Mevcut'te OLAN

- WebSocket gerçek zamanlı veri akışı
- Hesap durumu (Bakiye, Equity, Margin, Free Margin)
- Açık pozisyon tablosu (SL/TP, Swap, Tür, Yönetim)
- Son işlemler tablosu
- Emir performansı (başarı/ret/timeout, son 10 emir)
- MT5 reconnect geçmişi
- Trend grafik (son 60 döngü)
- Detaylı risk sayaçları (üst üste kayıp, cooldown, pozisyon limiti)
- Filtre ve sıralama
- Hibrit devir, pozisyon kapatma işlemleri

---

## 4. BİRLEŞTİRME ÖNERİSİ

### Seçenek A: Yeni Sayfa — "System Monitor" (Önerilen)

Mevcut 10 sayfalık yapıya 11. sayfa olarak "System Monitor" eklenir. SideNav'a yeni link:
- `📡 System Monitor` → `/monitor`

Bu sayfa Monitor'ün 5 yeni özelliğini içerir, mevcut API verisiyle beslenir:

```
┌──────────────────────────────────────────────────────────┐
│ HEADER: Sistem/VİOP durumu, saat                         │
├──────────────────────────────────────────────────────────┤
│ STATS BAR: P&L | Pozisyon | DD | Ping | Lag | Uptime     │
├──────────────────────────────────────────────────────────┤
│              MODÜL MİMARİSİ DİYAGRAMI                    │
│  BABA ──→ OĞUL ──→ ÜSTAT ──→ H-ENGINE ──→ MANUEL ──→ HİBRİT │
│                     ↑ MT5 (üstte)                        │
├──────────────────────────────────────────────────────────┤
│              SİNYAL AKIŞ TABLOSU                         │
│  Zaman | Kaynak | Kontrat | Yön | BABA | Motor | MT5 | ms│
├──────────┬──────────────┬────────────────────────────────┤
│ LOG      │ RESPONSE +   │ RISK KİLL-SWİTCH +             │
│ (kompakt)│ THREAD       │ HATA SAYACI                    │
└──────────┴──────────────┴────────────────────────────────┘
```

### Seçenek B: Mevcut Sayfalara Dağıtma

- Flow Diagram → SystemHealth.jsx'a eklenir
- Sinyal Akış Tablosu → SystemLog.jsx'a yeni tab olarak
- Thread Durumu → SystemHealth.jsx'a yeni bölüm
- Hata Sayacı → RiskManagement.jsx'a yeni bölüm
- VİOP Durumu → TopBar.jsx'a eklenir

### Seçenek C: Dashboard Zenginleştirme

Dashboard.jsx'ın üstüne Monitor'ün en kritik parçaları (Flow Diagram + Stats Bar) eklenir.

---

## 5. BACKEND GEREKSİNİMLERİ (Hangisi Seçilirse)

| # | Değişiklik | Dosya | Detay |
|---|-----------|-------|-------|
| 1 | Sinyal akış verisi | `engine/event_bus.py` veya yeni | Her sinyalin tam yaşam döngüsünü (kaynak→BABA→motor→MT5→sonuç) kaydetme |
| 2 | Thread durumu | `engine/health.py` → `api/routes/health.py` | TICK/M1/SPREAD thread durumu, son çalışma, yazma sayısı |
| 3 | Modül hata sayacı | `engine/health.py` → `api/routes/health.py` | Modül bazlı bugünkü hata sayıları |
| 4 | (Opsiyonel) SQLite lag | `engine/database.py` → health | Yazma gecikmesi ölçümü |

---

## 6. TAHMİNİ ETKİ

| Metrik | Değer |
|--------|-------|
| Yeni frontend satır | ~400-500 (yeni sayfa) veya ~200-300 (dağıtma) |
| Backend değişiklik | ~100-150 satır (health API genişletme + sinyal akış) |
| Mevcut bileşen etkisi | Seçenek A'da minimal (sadece SideNav + App.jsx route), Seçenek B/C'de orta |
| Risk | Düşük — mevcut yapıya ek, kırıcı değişiklik yok |

---

*Rapor sonu. Yönlendirme bekleniyor.*
