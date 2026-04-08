# ÜSTAT v5.9 — VİOP VADE (EXPIRY) LOJİĞİ KAPSAMLI ANALİZİ

**Rapor Tarihi:** 1 Nisan 2026
**Versiyon:** 3.2 (Gelişim: v5.9 → v5.9.1)
**Kapsam:** Tüm vade-ilişkili kod mantığı, rollover mekanizması, hata senaryoları

---

## 1. MEVCUT VADE SİSTEMİNİN YAPISI

### 1.1 Vade Tarihleri Tanımı

**Dosya:** `engine/baba.py` — Satır 243-254

```python
VIOP_EXPIRY_DATES: set[date] = {
    # 2025
    date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31),
    date(2025, 4, 30), date(2025, 5, 30), date(2025, 6, 30),
    ... (tüm 2025-2026 ayları)
    # 2026
    date(2026, 1, 30), date(2026, 2, 27), date(2026, 3, 31),
    ... (devam eden aylar)
}
```

**Özelliği:**
- Her ayın son **iş günü** (Pazartesi-Cuma)
- VİOP Borsa İstanbul vadeli işlem kontratlarının son işlem günü
- Ramazan/Kurban Bayramı tatillerine denk gelen vadeler **önceki iş gününe çekilmiş**
- Sistem başlangıcında `validate_expiry_dates()` (Satır 257-276) ile doğrulama yapılır

---

## 2. VADE GEÇIŞI OTOMASİYONU (ROLLOVER)

### 2.1 Temel Mekanizma: `_next_expiry_suffix()`

**Dosya:** `engine/mt5_bridge.py` — Satır 268-295

```python
@staticmethod
def _next_expiry_suffix() -> str | None:
    """Bugün VİOP vade günüyse, sonraki ayın suffix'ini döndür (MMYY).

    Örnek: 31 Mart 2026 (vade günü) → '0426' (Nisan 2026).
    Vade günü değilse None döndürür.
    """
```

**İş Akışı:**
1. Bugünün tarihi alınır: `today = date.today()`
2. `VIOP_EXPIRY_DATES` seti kontrol edilir (Satır 285)
3. **Bugün vade günüyse (today in VIOP_EXPIRY_DATES):**
   - Sonraki ayın numarası hesaplanır (Satır 289-292)
   - Suffix oluşturulur: `f"{next_month:02d}{next_year % 100:02d}"`
   - Örnek: Mart 31, 2026 → Nisan (04) → `"0426"`
   - **Döndürülür: "0426"**
4. **Vade günü değilse:**
   - `None` döndürülür

---

### 2.2 Ana Rollover Fonksiyonu: `_resolve_symbols()`

**Dosya:** `engine/mt5_bridge.py` — Satır 297-434

#### 2.2.1 Fonksiyon Amacı

```
WATCHED_SYMBOLS (base isimler)    →    MT5 Gerçek İsimler
    F_THYAO                       →    F_THYAO0226 (Şubat) veya F_THYAO0326 (Mart) ...
    F_AKBNK                       →    F_AKBNK0226 (Şubat) veya F_AKBNK0326 (Mart) ...
    ... (15 kontrat)
```

**Çalışma Prensibi:**
- **Günlük bir kez** (main.py'de) çağrılır → Sadece tarih değiştiğinde
- Tüm izlenen 15 kontratı vade bilgisine göre eşler
- Eski vadeyi yeni vadeye otomatik geçirir

#### 2.2.2 Detaylı İş Adımları (Satır 317-402)

**ADIM 1: Hedef Suffix Belirle (Vade Günü Kontrolü)**

```python
target_suffix = self._next_expiry_suffix()
if target_suffix:
    logger.info(f"VADE GEÇİŞİ: Bugün vade son günü — hedef suffix: {target_suffix}")
```

- Vade günüyse: `target_suffix = "0426"` (sonraki ay)
- Normal gün: `target_suffix = None`

**ADIM 2: Her Kontrat İçin Eşleme (15 Kontrat × Vade Lojik)**

```python
for base in WATCHED_SYMBOLS:  # F_THYAO, F_AKBNK, ... (15 tane)
    candidates = [s for s in all_symbols
                  if s.name.upper().startswith(base.upper())
                  and len(s.name) > len(base)]
```

Örneğin `F_THYAO` için:
- MT5'te bulunan adaylar: `[F_THYAO0125, F_THYAO0225, F_THYAO0326, F_THYAO0426]`

**ADIM 3: Yöntem 1 — Vade Günü Geçişi (YALNIZCA VADE GÜNÜ)**

```python
if target_suffix:  # Vade günüyse
    target_name = f"{base}{target_suffix}"  # F_THYAO0426
    match = [s for s in candidates if s.name.upper() == target_name.upper()]
    if match:
        chosen = match[0]
        logger.info(f"Sembol eşleme: {base} → {chosen.name} (vade geçişi)")
```

- **Vade günü (örn. 31 Mart):** `target_suffix = "0426"` → `F_THYAO0426` aranır
- **Bulunursa:** Seçilir ve MT5'te activate edilir
- **Bulunmazsa:** Yöntem 2'ye düşülür (Satır 370-391)

**ADIM 4: Yöntem 2 — Normal Gün (Hedef Bulunamadı)**

```python
if not chosen:
    sorted_cands = sorted(candidates, key=lambda s: s.name)
    for candidate in sorted_cands:  # Alfabetik sırayla
        activated = self._safe_call(mt5.symbol_select, candidate.name, True)
        if activated:
            chosen = candidate
            logger.info(f"Sembol eşleme: {base} → {candidate.name}")
            break
```

- İlk **aktivleştirilebilir** kontratı seçer (genelde en yakın gelecek vade)
- Örneğin normal bir gün → `F_THYAO0226` seçilmiş olabilir
- Vade günü: `F_THYAO0326` seçilmiş olabilir
- **Sonraki vade günü (Mart 31):** `F_THYAO0426` seçilir

**ADIM 5: Atomik Güncelleme**

```python
with self._map_lock:
    self._symbol_map = new_symbol_map       # F_THYAO → F_THYAO0426
    self._reverse_map = new_reverse_map     # F_THYAO0426 → F_THYAO
```

- **Thread-safe** (eş zamanlı okuma/yazma çakışmasını önler)
- Tüm map'ler birlikte güncellenir (atomik)

---

### 2.3 Günlük Re-Resolve Çağrısı

**Dosya:** `engine/main.py` — Satır 735-743

```python
# ── 1b. Günlük sembol re-resolve (VİOP vade geçişi koruması) ──
today = date.today()
if self._last_symbol_resolve_date != today:
    self._last_symbol_resolve_date = today
    try:
        self.mt5._resolve_symbols()
        logger.info(f"Günlük sembol re-resolve tamamlandı: {today}")
    except Exception as exc:
        logger.error(f"Sembol re-resolve hatası: {exc}")
```

**Mekanizma:**
- **Ana döngü** başında (10 sn çevrim) her gün **TAM BİR KEZ** çalışır
- Tarih değiştiğinde otomatik tetiklenir
- Vade günü: Yeni vade ile eşleme güncellenir
- **Timing:** Pazartesi-Cuma 09:45 (piyasa açılışı) öncesi

---

## 3. VADE GÜNÜ KONTROLÜ VE OLAY REJİMİ

### 3.1 EXPIRY_DAYS Parametresi

**Dosya:** `engine/baba.py` — Satır 93

```python
EXPIRY_DAYS: int = 0  # v5.9: Vade kısıtlaması kaldırıldı (kullanıcı talimatı)
```

**Durumu:** `0` — Vade kontrolü **TAMAMEN DEVRE DIŞI**

**Tarihçe:**
- **v5.8 ve öncesi:** Vade son 2-3 günü OLAY rejimi aktive ediliyordu
- **v5.9 (v5.9.1 ile birlikte):** Kullanıcı talimatıyla **devre dışı bırakıldı**
- Oturum #83 düzeltmesi (top5_selection.py)

---

### 3.2 OLAY Rejimi ve Vade Kontrolü

**Dosya:** `engine/baba.py` — Satır 810-841

```python
def _check_olay(self) -> dict[str, Any] | None:
    """TCMB/FED günü (saatlik pencere), vade sonu, kur şoku."""

    # 2. Vade bitiş — tam gün OLAY (OLAY_FULL_DAY_TRIGGERS)
    # v5.9.1: EXPIRY_DAYS=0 ise vade kontrolü tamamen devre dışı
    for expiry in VIOP_EXPIRY_DATES:
        days = (expiry - today).days
        if 0 <= days < EXPIRY_DAYS:  # ← 0 < 0 asla doğru değil!
            return {
                "reason": f"Vade bitiş: {expiry} ({days} gün kaldı)",
                "trigger": "expiry",
            }
```

**Sonuç:**
- `EXPIRY_DAYS = 0` olduğu için: `0 <= days < 0` **asla true olmaz**
- Vade günü bile olsa OLAY rejimi **TETİKLENMEZ**
- İşlem **açılabilir devam eder**

---

## 4. TOP-5 KONTRAT SEÇİMİNDE VADE KONTROLÜ

### 4.1 top5_selection.py'daki Vade Parametreleri

**Dosya:** `engine/top5_selection.py` — Satır 83-85

```python
# ── Vade geçişi parametreleri (GCM paraleli) ────────────────────────
EXPIRY_NO_NEW_TRADE_DAYS: int = 0   # v5.9: Vade kısıtlaması kaldırıldı
EXPIRY_CLOSE_DAYS: int = 0          # v5.9: Vade kısıtlaması kaldırıldı
EXPIRY_OBSERVATION_DAYS: int = 0
```

**Durumu:** Tüm vade kısıtlamaları `0` — **DEVRE DIŞI**

---

### 4.2 Vade Filtresi Fonksiyonu

**Dosya:** `engine/top5_selection.py` — Satır 644-671

```python
def _get_expiry_status(self, today: date) -> dict[str, str]:
    """Her sembol için vade geçiş durumunu belirle."""

    # "observation" → vade sonundan 0 < gün < EXPIRY_OBSERVATION_DAYS
    # "close"       → vade sonuna 0 ≤ gün < EXPIRY_CLOSE_DAYS
    # "no_new_trade" → vade sonuna 0 ≤ gün < EXPIRY_NO_NEW_TRADE_DAYS
    # "normal"       → diğer durumlar

    for symbol in WATCHED_SYMBOLS:
        if bdays_to_expiry < EXPIRY_CLOSE_DAYS:           # 0 < 0 → false
            status[symbol] = "close"
        elif bdays_to_expiry < EXPIRY_NO_NEW_TRADE_DAYS:  # 0 < 0 → false
            status[symbol] = "no_new_trade"
        else:
            status[symbol] = "normal"  # ← HERDÜzen BU DALA GİRER
```

**Sonuç:**
- Vade günü bile olsa: `status = "normal"`
- Tüm kontratlar top-5'e seçilmeye devam ederler

---

### 4.3 Top-5 Seçim Sırasında Vade Filtresi

**Dosya:** `engine/top5_selection.py` — Satır 286-291

```python
# 6. Vade + haber filtresi
expiry_status = self._get_expiry_status(today)
top5_final: list[str] = []
for sym, _sc in top5_above_avg:
    status = expiry_status.get(sym, "normal")
    if status in ("observation", "no_new_trade", "close"):
        continue  # ← EXPIRY_DAYS=0 olduğu için burası HİÇ ÇALIŞMAZ
```

- Vade filtresi yapılmaz (tüm durumlar "normal" döndürür)
- Tüm kontratlar seçilmeye devam eder

---

## 5. SEMBOL ÇEVİRME VE VERI AKIŞI

### 5.1 Base → MT5 Eşlemesi

**Dosya:** `engine/mt5_bridge.py` — Satır 436-443

```python
def _to_mt5(self, base_symbol: str) -> str:
    """Base sembol adını MT5 gerçek adına çevir.

    Eşleme yoksa base'in kendisini döndürür (geriye uyumluluk).
    v5.8/CEO-FAZ2: _map_lock ile thread-safe.
    """
    with self._map_lock:
        return self._symbol_map.get(base_symbol, base_symbol)
```

**Örnek İş Akışı:**

| Zaman | Base | Eşleme | MT5 Çağrısı |
|------|------|--------|-----------|
| Şubat 15 | F_THYAO | F_THYAO0226 | `get_bars("F_THYAO0226", ...)` |
| Şubat 28 | F_THYAO | F_THYAO0226 | `get_bars("F_THYAO0226", ...)` |
| Mart 3 | F_THYAO | F_THYAO0326 | `get_bars("F_THYAO0326", ...)` |
| Mart 31 (vade günü) | F_THYAO | F_THYAO0426 | `get_bars("F_THYAO0426", ...)` |
| Nisan 1 | F_THYAO | F_THYAO0426 | `get_bars("F_THYAO0426", ...)` |

---

### 5.2 MT5 → Base Ters Eşlemesi (Pozisyon Tanıma)

**Dosya:** `engine/mt5_bridge.py` — Satır 445-460

```python
def _to_base(self, mt5_symbol: str) -> str | None:
    """MT5 sembol adını base'e çevir.

    Eşleme yoksa None döndürür (izlenmeyen sembol).
    v5.9.1: Fallback — vade soneki farklı olabilir (ör. map 0326, pozisyon 0426)
    """
    with self._map_lock:
        base = self._reverse_map.get(mt5_symbol)  # 0326 eşlemesi varsa
        if base:
            return base
        # Fallback: prefix eşleşmesi ile base çıkar
        for watched in WATCHED_SYMBOLS:
            if mt5_symbol.upper().startswith(watched.upper()):
                return watched  # ← VİP! Farklı vadeyi çözer
```

**Avantaj: Eski Vade Fallback Koruması**

Senaryo: 31 Mart vade günü, pozisyon açıldı `F_THYAO0426`'da
- Sonraki gün `_resolve_symbols()` çalıştıktan sonra
- `_symbol_map["F_THYAO"] = "F_THYAO0426"` (eşleme güncellendi)
- `_reverse_map["F_THYAO0426"] = "F_THYAO"` (ters eşleme var)
- **Eski pozisyon `F_THYAO0326` hâlâ MT5'te açık kalabilir**
  - Fallback: `if mt5_symbol.startswith("F_THYAO")` → `"F_THYAO"` döner ✓

---

## 6. VADE GÜNÜ ÖNCESİ, GÜNÜ VE SONRASI DAVRANIŞI

### 6.1 Senaryo 1: Vade Günü Öncesi (Örn. Mart 28-30, 2026)

**Tarih:** Cuma, 27 Mart 2026

| Birim | Durum |
|------|-------|
| **Eşleme** | `F_THYAO0326` |
| **İşlem Açma** | Kısıtlama yok (EXPIRY_DAYS=0) |
| **OLAY Rejimi** | Aktif değil |
| **Top-5** | Seçilir |
| **Veri** | `get_bars("F_THYAO0326", ...)` |
| **Pozisyon** | Açık kalabilir |

---

### 6.2 Senaryo 2: Vade Günü (Pazartesi, 31 Mart 2026)

**Tarih:** Pazartesi, 31 Mart 2026

**Saat: 09:45 (Piyasa Açılışı Öncesi)**

`_resolve_symbols()` çağrıldığında:

```python
target_suffix = "0426"  # Nisan 2026
# F_THYAO için:
#   MT5'te bulunan: [F_THYAO0326, F_THYAO0426]
#   target_suffix = "0426" → "F_THYAO0426" aranır
#   BULUNDU → seçilir

_symbol_map["F_THYAO"] = "F_THYAO0426"  # Güncellendi
_reverse_map["F_THYAO0426"] = "F_THYAO"
```

| Birim | Durum |
|------|-------|
| **Eşleme Yeni** | `F_THYAO0426` |
| **İşlem Açma** | Kısıtlama yok (EXPIRY_DAYS=0) |
| **OLAY Rejimi** | Aktif değil (0 < 0 = false) |
| **Top-5** | Seçilir ("normal" statüsü) |
| **Veri** | `get_bars("F_THYAO0426", ...)` |
| **Pozisyon (Eski)** | `F_THYAO0326` hâlâ açık |
| **Pozisyon (Yeni)** | `F_THYAO0426` açılabilir |

---

### 6.3 Senaryo 3: Vade Günü Sonrası (Nisan 1-30, 2026)

**Tarih:** Salı, 1 Nisan 2026

| Bilint | Durum |
|------|-------|
| **Eşleme** | `F_THYAO0426` (değişmedi) |
| **İşlem Açma** | Normal |
| **OLAY Rejimi** | Aktif değil |
| **Top-5** | Seçilir |
| **Veri** | `get_bars("F_THYAO0426", ...)` |
| **Pozisyon (Eski)** | `F_THYAO0326` hâlâ açık ← **RİSK** |
| **Pozisyon (Yeni)** | `F_THYAO0426` açılabilir |

---

## 7. GÜÇLÜ YÖNLER

### ✓ 7.1 Otomatik Vade Geçişi

- `_next_expiry_suffix()` vade günü tespit eder
- Yeni vade doğrudan eşlenir
- Eşleme atomik ve thread-safe (`_map_lock`)
- **Hiçbir manuel müdahale gerekmez**

### ✓ 7.2 Fallback Mekanizması

- `_to_base()` prefix eşleşmesi ile eski vadeyi tanır
- Eski pozisyon açık kalsa bile, pozisyon takibi işlev görür
- MT5 netting modunda iki vade aynı anda kısmi kapanış yapabilir

### ✓ 7.3 Günlük Re-Resolve

- `main.py` (Satır 735-743) her gün **tam 1 kez** çağırır
- Tarih değiştiğinde otomatik tetiklenir
- Piyasa açılışı öncesi çalışır (gecikme riski minimal)

### ✓ 7.4 Kontrat Aktivasyonu

- MT5 sembolü activate edilmeden eşleme yapılmaz
- GCM MT5 vade günü yeni vadeyi visible yapar
- Sistem bunu otomatik algılar ve seçer

---

## 8. ZAYIF YÖNLER VE RİSKLER

### ✗ 8.1 Kritik: Eski Vade Açık Pozisyon Çakışması

**Risk Senaryosu:**
1. Mart 28 (Cuma): `F_THYAO0326` büyük pozisyon açık
2. Mart 31 (Pazartesi) 09:45: `_resolve_symbols()` çalışır
   - `F_THYAO` → `F_THYAO0426` eşlenmesi güncellenir
3. Aynı gün saat 14:00: Yeni sinyal
   - `_to_mt5("F_THYAO")` → `"F_THYAO0426"` döner
   - **YENİ pozisyon `F_THYAO0426`'da açılır**
4. MT5'te şimdi **2 vade aynı anda açık:**
   - `F_THYAO0326`: Eski (vade sonuna 0 gün)
   - `F_THYAO0426`: Yeni (vade sonuna ~30 gün)

**Sonuçlar:**
- **Marjin karşılaştırması yanlış:** Hesap marjini 2 vadeli pozisyon için hesaplanır
- **Risk yönetimi karmaşası:** `active_trades` dict'i base isim ("F_THYAO") tutar
- **Vade kapanış:** Eski vade elle kapatılmalı veya sistem tarafından kapatılmaz

### ✗ 8.2 Vade Günü OLAY Rejimi İLE KAPATILMIŞ

**Kod:** `engine/baba.py` Satır 93 — `EXPIRY_DAYS = 0`

**Sonuç:**
- Vade günü işlem **AÇILABILIR** (OLAY rejimi tetiklenmez)
- Vade günü yüksek volatilite olabilir
- Kontrol koruması yok

**İyileştirme Önerisi:**
```python
EXPIRY_DAYS = 1  # Son 1 gün OLAY (vade günü + günü öncesi)
```

### ✗ 8.3 Sembol Aktivasyonu Başarısız Durumu

**Kod:** `engine/mt5_bridge.py` Satır 393-398

```python
if not chosen:
    # Hiçbiri çalışmadı — en yeni adayı kullan (fallback)
    chosen = max(candidates, key=lambda s: s.name)
    logger.warning(f"Sembol eşleme (fallback): {base} → {chosen.name}")
```

**Risk:** Yanlış vade seçilmesi
- GCM MT5 yeni vadeyi visible yapmamışsa
- Sistem **fallback** ile maksimum alfabetik adı seçer
- Yanlış vadeye işlem yapılabilir

### ✗ 8.4 Vade Günü Kaçırılsa

**Senaryo:** `_resolve_symbols()` vade günü çalışmasa (sistem crash, MT5 timeout)

| Durumu | Etki |
|--------|------|
| Eşleme | Eski vade (`F_THYAO0326`) kalır |
| Yeni İşlem | Eski vadeye açılır ← **HATA** |
| Veri | Eski vade verisi çekilir |
| Pozisyon Kapanış | Vade sonu (17:45) yaklaştığında problem |

---

## 9. VADE GÜNÜ KAÇIRSA NE OLUR (Failure Analysis)

### Senaryo: 31 Mart 2026, Sistem Crash

**Hak İlişkileri:**

| Zaman | Olay | Sonuç |
|------|------|-------|
| 09:45 | `_resolve_symbols()` çalışmalı | ← CRASH |
| 14:00 | Yeni sinyal tetiklenir | `F_THYAO0326` (ESKI) seçilir ← **HATA** |
| 17:30 | Vade bitiş öncesi | Pozisyon `F_THYAO0326`'da (vade sonu 30 dakika) |
| 17:45 | Vade sonu (VİOP Piyasası Kapalı) | Pozisyon kapanmaz ← **KRITIK** |
| 18:00+ | Sistem yeniden başlar | `_resolve_symbols()` çalışır → `F_THYAO0426` |
| Ertesi Gün | Eski pozisyon | `F_THYAO0326` açık (piyasa kapalı sözleşme) ← **İLİKİLENEMEZ** |

**Kalıcı Sonuç:**
- `F_THYAO0326` sözleşmesi sona ermiş, MT5'te "açık" gösterilir
- Marjin kilitli, hesap "çakışma" hatası
- **Manuel müdahale gerekir**

---

## 10. YAPICI ÇALIŞMA ZAMAN ÇİZELGESİ (Normal Senaryo)

### 10.1 Pazartesi - Cuma (VİOP Açık)

```
09:30         Piyasa Açılış
09:45         ↓
              _resolve_symbols() → Vade günü control
              Eşleme güncelleme (varsa)

10:00-17:30   Normal işlem döngüsü (10 sn çevrimi)
              • OĞUL sinyal üretim (base sembol)
              • _to_mt5() → MT5 eşleme
              • send_order() → MT5'e emir

17:30         EOD kontrol başlangıcı
17:45         Tüm pozisyonlar kapatılmalı
              (17:45 = VİOP kapanış saat)

18:00+        Piyasa Kapalı
```

### 10.2 Vade Günü (Pazartesi-Cuma Sonu)

```
09:45         _resolve_symbols()
              target_suffix = "0426" (sonraki ay)
              Tüm kontratlar yeni vadeye eşlenir
              Eski eşleme: F_THYAO0326
              Yeni eşleme: F_THYAO0426

09:50-17:30   YENİ VADEYLE işlem başlar
              Eski pozisyon F_THYAO0326 açık kalabilir

17:45         Tüm pozisyonlar kapatılmalı
              Eski + Yeni vade hepsi
```

---

## 11. KODSAL REFERANS TABLOSU

| Dosya | Satır | Fonksiyon | Görev |
|-------|-------|-----------|-------|
| `mt5_bridge.py` | 268-295 | `_next_expiry_suffix()` | Vade günü tespiti |
| `mt5_bridge.py` | 297-434 | `_resolve_symbols()` | Sembol eşleme güncellemesi |
| `mt5_bridge.py` | 436-443 | `_to_mt5()` | Base → MT5 çevirme |
| `mt5_bridge.py` | 445-460 | `_to_base()` | MT5 → Base (fallback) |
| `main.py` | 735-743 | Günlük re-resolve çağrısı | Piyasa açılışı sırasında |
| `baba.py` | 243-254 | `VIOP_EXPIRY_DATES` | Vade tarihleri |
| `baba.py` | 93 | `EXPIRY_DAYS` | Vade kontrol parametresi (=0) |
| `baba.py` | 835-841 | `_check_olay()` vade kontrolü | OLAY rejimi triggerı |
| `top5_selection.py` | 83-85 | Vade parametreleri | Top-5 filtreleme (=0) |
| `top5_selection.py` | 644-671 | `_get_expiry_status()` | Vade durumu sınıflandırma |
| `data_pipeline.py` | 355 | `get_bars()` | MT5 verisi (çevrilmiş sembol) |

---

## 12. RISK MİTİGASYON ÖNERİLERİ

### A. Acil (Yaşamsal Risk)

**1. Vade Günü OLAY Rejimi Yeniden Aktive Etme**

```python
# engine/baba.py Satır 93
EXPIRY_DAYS: int = 1  # ← 0 yerine 1 yapın

# Etki: Vade günü ve öncesi günü OLAY rejimi olur
# Risk: İşlem açılmaz (yüksek volatilite koruması)
```

**2. Eski Vade Otomatik Kapanışı (Vade Günü)**

```python
# engine/main.py _run_single_cycle() içinde
# BABA çalıştıktan sonra
if today in VIOP_EXPIRY_DATES:
    self._close_old_vade_positions()  # YENİ FONKSİYON

def _close_old_vade_positions():
    """Vade günü eski vadedeaki açık pozisyonları kapat."""
    positions = self.mt5.get_positions()
    for pos in positions:
        base = self.mt5._to_base(pos['symbol'])
        current_vade = self.mt5._symbol_map.get(base)
        if pos['symbol'] != current_vade:
            # Eski vade → kapat
            self.mt5.close_position(pos['ticket'])
```

### B. Önem (Sistem Dayanıklılığı)

**3. EOD Vade Kapanışı (17:45 Zorunlu)**

```python
# engine/ogul.py _check_end_of_day()
# Mevcut: Tüm pozisyonları kapatır
# Yeni: Vade kontrol ekle

if today in VIOP_EXPIRY_DATES:
    # Vade günü → daha agresif (17:30)
    eod_time = time(17, 30)
else:
    # Normal gün → 17:45
    eod_time = time(17, 45)
```

**4. Sistem Restart ve Re-Resolve Garanti**

```python
# start_ustat.py watchdog
# Günlük bir kez (sabit saat 09:40) hard restart
if now.hour == 9 and now.minute == 40:
    restart_application()  # → _resolve_symbols() otomatik çalışır
```

### C. Izleme (Monitoring)

**5. Dashboard Alert: Vade Çakışması**

```python
# api/routes/positions.py
# Yeni endpoint: /api/positions/vade-check

def get_expiry_conflict():
    positions = mt5.get_positions()
    vade_map = mt5._symbol_map

    conflicts = []
    for pos in positions:
        base = mt5._to_base(pos['symbol'])
        expected = vade_map.get(base)
        if pos['symbol'] != expected:
            conflicts.append({
                'symbol': pos['symbol'],
                'expected': expected,
                'status': 'OLD_VADE'
            })
    return conflicts
```

**6. Log Alerts**

```python
# engine/baba.py _check_olay()
if today in VIOP_EXPIRY_DATES:
    logger.critical(f"VADE GÜNÜ UYARISI: {today} — İşlem yüksek riski")
```

---

## 13. ÖZET VE SONUÇ

### Mevcut Sistem Durumu

| Yön | Durum | Risk |
|-----|-------|------|
| **Otomatik Vade Geçişi** | ✓ İşlevsel | Düşük |
| **Sembol Eşlemesi** | ✓ Thread-safe | Düşük |
| **Günlük Re-Resolve** | ✓ Garanti | Düşük |
| **OLAY Rejimi Koruma** | ✗ Devre dışı | **YÜKSEK** |
| **Eski Vade Kapanışı** | ✗ Otomatiksiz | **ORTA** |
| **Fallback (Prefix)** | ✓ Mevcut | Düşük |
| **EOD Kapanış** | ✓ Var | Düşük |

### Sonuç

**ÜSTAT v5.9 Vade Sistemi:**
- ✓ **Otomatik rollover tamam** — Yeni vade günü eşlenir
- ✓ **Eşleme mekanizması güçlü** — Thread-safe, atomik, fallback
- ✗ **OLAY rejimi kapalı** — Vade günü işlem açılabiliyor (riski yüksek)
- ✗ **Eski vade çakışması** — Otomatik kapanmıyor, manual bekliyor
- ⚠ **Sistem crash riski** — Vade günü re-resolve kaçırılırsa kalıcı hasar

### Tavsiye

**Acil Adımlar:**
1. `EXPIRY_DAYS = 1` yapın (OLAY rejimi aktive)
2. Eski vade otomatik kapanış fonksiyonu ekleyin
3. Vade günü hard restart ekleyin (09:40)

**Durum:** Sistem **çoğunlukla güvenli**, ama **vade günü risk yönetimi zayıf**.

---

**Rapor Sonu**
