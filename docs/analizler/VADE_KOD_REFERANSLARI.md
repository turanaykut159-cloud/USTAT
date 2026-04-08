# ÜSTAT v5.9 — VADE KODU DETAYLI REFERANS

**Son Güncelleme:** 1 Nisan 2026
**Amaç:** Vade-ilişkili tüm kod satırlarının tam referansı

---

## 1. VİOP VADE TARİHLERİ

### Dosya: `engine/baba.py`

**Satır 240-254: VIOP_EXPIRY_DATES Tanımı**

```python
# Satır 240: Başlık yorum
# Satır 241-242: Açıklama (Ramazan/Kurban Bayramı notu)
# Satır 243: VIOP_EXPIRY_DATES: set[date] = {

# İçerik:
# - 2025 yılı (12 ay) — Satır 245
# - 2026 yılı (12 ay) — Satır 250
# - Toplam 24 vade tarihi

# Örnek: Satır 245: date(2025, 1, 31),  # Ocak 2025 son iş günü
# Örnek: Satır 251: date(2026, 3, 31),  # Mart 2026 son iş günü
```

**Satır 257-276: validate_expiry_dates() Fonksiyonu**

```python
def validate_expiry_dates() -> list[str]:
    """VİOP vade tarihlerinin iş günü olduğunu doğrula."""
    # Satır 269: for expiry in sorted(VIOP_EXPIRY_DATES):
    # Satır 270:     weekday = expiry.weekday()  # 0=Pazartesi, 5=Cumartesi
    # Satır 271-273: Hafta sonu kontrolü
    # Satır 274-275: Tatil günü kontrolü (ALL_HOLIDAYS)

    # NOT: Engine başlangıcında çağrılır, her çevrimde değil
```

**Satır 93: EXPIRY_DAYS Parametresi**

```python
EXPIRY_DAYS: int = 0     # v5.9: Vade kısıtlaması kaldırıldı
```

- **Tarih:** 0
- **Anlamı:** Vade günü kontrolleri devre dışı
- **İmpact:** OLAY rejimi tetiklenmiyor, top-5 filtresi çalışmıyor

---

## 2. VADE GEÇIŞI MEKANIZMASI

### Dosya: `engine/mt5_bridge.py`

#### Bölüm 1: WATCHED_SYMBOLS (İzlenen 15 Kontrat)

**Satır 32-37: WATCHED_SYMBOLS Listesi**

```python
WATCHED_SYMBOLS: list[str] = [
    "F_THYAO", "F_AKBNK", "F_ASELS", "F_TCELL", "F_HALKB",
    "F_PGSUS", "F_GUBRF", "F_EKGYO", "F_SOKM",  "F_TKFEN",
    "F_OYAKC", "F_BRSAN", "F_AKSEN", "F_ASTOR", "F_KONTR",
]
```

- **Satır 33-37:** 15 adet VİOP vadeli kontrat (base isimler)
- **Kullanım:** Sistem tüm sembol eşlemesini bu liste üzerine kurar

#### Bölüm 2: Sembol Eşleme Veritabanları

**Satır 106-112: Eşleme Haritaları**

```python
# Satır 106-108: Lock (thread-safety)
self._map_lock: threading.Lock = threading.Lock()

# Satır 110: Base → MT5 çevirme
self._symbol_map: dict[str, str] = {}  # "F_THYAO" → "F_THYAO0226"

# Satır 112: MT5 → Base ters çevirme
self._reverse_map: dict[str, str] = {}  # "F_THYAO0226" → "F_THYAO"
```

**Satır 119-120: Emir Lock'u**

```python
# Satır 119-120: _order_lock
self._order_lock: threading.Lock = threading.Lock()
# NOT: Emir gönderimi tek seferde 1 çağrı
```

#### Bölüm 3: Vade Günü Tespiti

**Satır 268-295: _next_expiry_suffix() Fonksiyonu**

```python
# Satır 268-270: Fonksiyon tanımı ve docstring
@staticmethod
def _next_expiry_suffix() -> str | None:
    """Bugün VİOP vade günüyse, sonraki ayın suffix'ini döndür (MMYY)."""

# Satır 274-276: İçe aktarımlar ve tarih alma
    from datetime import date as _date
    today = _date.today()
    try:
        from engine.baba import VIOP_EXPIRY_DATES

# Satır 285: KRITIK KONTROL
    if today not in VIOP_EXPIRY_DATES:
        return None

# Satır 288-292: Sonraki ay hesapla
    if today.month == 12:
        next_month, next_year = 1, today.year + 1
    else:
        next_month, next_year = today.month + 1, today.year

# Satır 294-295: Suffix formatla ve döndür
    suffix = f"{next_month:02d}{next_year % 100:02d}"
    return suffix
    # Örnek döndürüş: "0426" (Nisan 2026 için)
```

**Temel Mantık:**
- **Satır 285:** `today in VIOP_EXPIRY_DATES` → True ise vade günü
- **Satır 288-292:** Sonraki ayın sayısı
- **Satır 294:** Format: MMYY (ör. "0426" = Nisan 2026)

#### Bölüm 4: Ana Rollover Fonksiyonu

**Satır 297-434: _resolve_symbols() Fonksiyonu**

**ADIM 1: MT5 Sembol Listesi Al**

```python
# Satır 308-314
try:
    all_symbols = self._safe_call(mt5.symbols_get)  # MT5'ten tüm semboller
except (TimeoutError, Exception):
    all_symbols = None
if not all_symbols:
    logger.warning("MT5 sembol listesi alınamadı, eşleme yapılamıyor")
    return
```

**ADIM 2: Hedef Suffix Belirle**

```python
# Satır 317-323: Vade günü tespiti
target_suffix = self._next_expiry_suffix()  # "0426" veya None
if target_suffix:
    logger.info(
        f"VADE GEÇİŞİ: Bugün vade son günü — "
        f"hedef suffix: {target_suffix} "
        f"(tüm kontratlar bu vadeye eşlenecek)"
    )
```

**ADIM 3: Atomik Map Oluştur (Güncelleme Öncesi)**

```python
# Satır 326-327: Yeni eşlemeler (thread güvenliği için)
new_symbol_map: dict[str, str] = {}
new_reverse_map: dict[str, str] = {}
```

**ADIM 4: Her Kontrat İçin Eşleme**

```python
# Satır 329-402: 15 kontrat loop'u
for base in WATCHED_SYMBOLS:  # F_THYAO, F_AKBNK, ...
    # Satır 331-335: Aday sembol listesi
    candidates = [
        s for s in all_symbols
        if s.name.upper().startswith(base.upper())
        and len(s.name) > len(base)
    ]
    # Örnek: base="F_THYAO" → candidates=[F_THYAO0125, F_THYAO0225, F_THYAO0326]
```

**ADIM 4A: Tam Eşleşme (Suffix Yok)**

```python
# Satır 337-350: Eğer suffix'siz sembol varsa (örn. F_THYAO)
if not candidates:
    exact = [s for s in all_symbols if s.name.upper() == base.upper()]
    if exact:
        mt5_name = exact[0].name
        new_symbol_map[base] = mt5_name
        new_reverse_map[mt5_name] = base
        try:
            self._safe_call(mt5.symbol_select, mt5_name, True)  # Aktivate
        except (TimeoutError, Exception):
            pass
        logger.info(f"Sembol eşleme: {base} → {mt5_name} (tam eşleşme)")
    else:
        logger.warning(f"Sembol bulunamadı: {base}")
    continue
```

**ADIM 4B: YÖNTEM 1 — Vade Günü Geçişi (ÖNEMLİ!)**

```python
# Satır 352-367: Eğer target_suffix varsa ve aday bulunursa
chosen = None

if target_suffix:  # Vade günü ise
    target_name = f"{base}{target_suffix}"  # "F_THYAO0426"
    match = [s for s in candidates if s.name.upper() == target_name.upper()]
    if match:
        chosen = match[0]
        try:
            self._safe_call(mt5.symbol_select, chosen.name, True)
        except (TimeoutError, Exception):
            pass
        logger.info(
            f"Sembol eşleme: {base} → {chosen.name} "
            f"(vade geçişi — hedef suffix {target_suffix})"
        )
```

**Kritik:**
- **Satır 355:** `if target_suffix:` — Sadece vade günü
- **Satır 356:** `target_name = f"{base}{target_suffix}"` — Yeni vade adı
- **Satır 357:** Eğer bulunursa, seçilir ve **atomik map'e eklenir**

**ADIM 4C: Hedef Bulunamadı Uyarısı**

```python
# Satır 370-374
if not chosen and target_suffix:
    logger.warning(
        f"Vade hedefi {base}{target_suffix} bulunamadı — "
        f"YÖNTEM 2'ye düşülüyor (ilk aktif kontrat seçilecek)"
    )
```

**ADIM 4D: YÖNTEM 2 — Normal Gün (Fallback)**

```python
# Satır 375-391: Eğer hâlâ seçilmediyse
if not chosen:
    sorted_cands = sorted(candidates, key=lambda s: s.name)  # Alfabetik sıra
    for candidate in sorted_cands:
        try:
            activated = self._safe_call(
                mt5.symbol_select, candidate.name, True  # Aktivate et
            )
        except (TimeoutError, Exception):
            activated = False
        if activated:
            chosen = candidate
            logger.info(
                f"Sembol eşleme: {base} → {candidate.name} "
                f"(visible={candidate.visible}, activated=True)"
            )
            break  # İlk aktif olanı seç ve dur
```

**Mantık:**
- Alfabetik sırayla ilk aktivleştirilebilir kontratı seçer
- Örneğin: [F_THYAO0125, F_THYAO0225, F_THYAO0326]
  - 0125 aktive edilebilir? Hayır
  - 0225 aktive edilebilir? Hayır
  - **0326 aktive edilebilir? EVET → Seçilir**

**ADIM 4E: Fallback (Hiç Biri Çalışmazsa)**

```python
# Satır 393-398: En son çare
if not chosen:
    # Hiçbiri çalışmadı — en yeni adayı kullan
    chosen = max(candidates, key=lambda s: s.name)  # Alfabetik maksimum
    logger.warning(
        f"Sembol eşleme (fallback): {base} → {chosen.name}"
    )
```

**ADIM 4F: Eşleme Kaydet**

```python
# Satır 400-402
mt5_name = chosen.name
new_symbol_map[base] = mt5_name
new_reverse_map[mt5_name] = base
# Örnek: new_symbol_map["F_THYAO"] = "F_THYAO0426"
```

**ADIM 5: USDTRY Özel Kontratı**

```python
# Satır 404-425: USDTRY (BABA şok kontrolü için)
usdtry_candidates = [
    s for s in all_symbols
    if "USDTRY" in s.name.upper()
]
if usdtry_candidates:
    # ... (benzer seçim mantığı)
    new_symbol_map["USDTRY"] = usdtry_chosen.name
    logger.info(f"Sembol eşleme: USDTRY → {usdtry_chosen.name}")
else:
    logger.warning("USDTRY sembolü bulunamadı — şok kontrolü pasif kalacak")
```

**ADIM 6: Atomik Swap (KRITIK)**

```python
# Satır 427-430: Thread-safe güncelleme
# v5.8/CEO-FAZ2: Atomik map güncellemesi
with self._map_lock:  # Lock'u tutarak
    self._symbol_map = new_symbol_map      # Tüm eşlemeler birlikte
    self._reverse_map = new_reverse_map    # Ters eşlemeler birlikte
    # Lock atılır → diğer thread'ler okuyabilir
```

**Kritik Neden:**
- `_to_mt5()` ve `_to_base()` aynı anda okuyabilir
- Eksik swap → race condition → yanlış sembol çevirme

**ADIM 7: Sonuç Loglama**

```python
# Satır 432-434
resolved = len(self._symbol_map)
total = len(WATCHED_SYMBOLS) + 1  # +1 USDTRY
logger.info(f"Sembol çözümleme tamamlandı: {resolved}/{total} eşlendi")
# Örnek: "Sembol çözümleme tamamlandı: 16/16 eşlendi"
```

---

## 3. SEMBOL ÇEVİRME FONKSİYONLARI

### Dosya: `engine/mt5_bridge.py`

#### Base → MT5 Çevirme

**Satır 436-443: _to_mt5() Fonksiyonu**

```python
def _to_mt5(self, base_symbol: str) -> str:
    """Base sembol adını MT5 gerçek adına çevir."""
    # Satır 442-443: Thread-safe okuma
    with self._map_lock:
        return self._symbol_map.get(base_symbol, base_symbol)
```

**Kullanım Yerleri:**
- `get_bars()` (Satır 720)
- `get_tick()` (Satır 751)
- `send_order()` (Satır 827)
- `get_symbol_info()` (Satır 681)

**Örnek:**
```
Input:  "F_THYAO"
Map:    {"F_THYAO": "F_THYAO0326"}
Output: "F_THYAO0326"
```

#### MT5 → Base Ters Çevirme (Fallback Dahil)

**Satır 445-460: _to_base() Fonksiyonu (ÖNEMLİ)**

```python
def _to_base(self, mt5_symbol: str) -> str | None:
    """MT5 sembol adını base'e çevir.

    v5.9.1: Fallback — vade soneki farklı olabilir
    """
    with self._map_lock:
        # ADIM 1: Ters harita'dan ara
        base = self._reverse_map.get(mt5_symbol)  # Satır 453
        if base:
            return base

        # ADIM 2: Fallback — prefix eşleşme
        for watched in WATCHED_SYMBOLS:  # Satır 457
            if mt5_symbol.upper().startswith(watched.upper()):
                return watched  # Satır 459

        # ADIM 3: İzlenmeyen sembol
        return None  # Satır 460
```

**Kritik: Fallback Mekanizması**

Senaryo:
- `_symbol_map["F_THYAO"] = "F_THYAO0426"` (Nisan)
- MT5'te açık pozisyon: `F_THYAO0326` (Mart — eski vade)
- `_to_base("F_THYAO0326")` çağrı:
  - **Satır 453:** `_reverse_map.get("F_THYAO0326")` → None (yeni vade'de değil)
  - **Satır 457-459:** `"F_THYAO0326".startswith("F_THYAO")` → **"F_THYAO" döner** ✓
  - **Sonuç:** Eski vade da tanınır!

**Kullanım Yerleri:**
- `get_positions()` (Satır 1676)
- `get_history()` (Satır 1731)
- `_is_watched()` (Satır 462)

---

## 4. GÜNLÜK RE-RESOLVE ÇAĞRISI

### Dosya: `engine/main.py`

**Satır 735-743: Ana Döngü İçinde Günlük Re-Resolve**

```python
# ── 1b. Günlük sembol re-resolve (VİOP vade geçişi koruması) ──
today = date.today()  # Satır 736: Bugünün tarihi
if self._last_symbol_resolve_date != today:  # Satır 737: Tarih değişti mi?
    self._last_symbol_resolve_date = today  # Satır 738: Güncelle
    try:
        self.mt5._resolve_symbols()  # Satır 740: ÇAĞIR
        logger.info(f"Günlük sembol re-resolve tamamlandı: {today}")
    except Exception as exc:
        logger.error(f"Sembol re-resolve hatası: {exc}")
```

**Kontext:**
- Fonksiyon: `_run_single_cycle()`
- Zaman: Her 10 saniyede bir, ama sadece AYNI GÜN İÇİNDE 1 kez
- Sırası: **Adım 1b** (very early, MT5 heartbeat sonra)

**Mekanizma:**
- `_last_symbol_resolve_date` = sonra düzenlenen tarihi saklar
- Yeni gün = Yeni `date.today()` → Koşul true → `_resolve_symbols()`
- **Otomatik!** Elle çağırma gerekmez

---

## 5. VADE GÜNÜ OLAY REJİMİ KONTROLÜ

### Dosya: `engine/baba.py`

**Satır 810-841: _check_olay() Fonksiyonu**

```python
# Satır 810-811: Fonksiyon tanımı
def _check_olay(self) -> dict[str, Any] | None:
    """TCMB/FED günü (saatlik pencere), vade sonu, kur şoku."""

    # Satır 830: Bugünün tarihi
    today = date.today()

    # ... (TCMB/FED kontrolü — Satır 815-830)

    # Satır 832: VADE BİTİŞ KONTROLÜ
    # "2. Vade bitiş — tam gün OLAY (OLAY_FULL_DAY_TRIGGERS)"
    # v5.9.1: EXPIRY_DAYS=0 ise vade kontrolü tamamen devre dışı

    # Satır 835-841: Loop
    for expiry in VIOP_EXPIRY_DATES:  # Her vade tarihi için
        days = (expiry - today).days  # Satır 836: Kalan gün
        if 0 <= days < EXPIRY_DAYS:   # Satır 837: KONTROL
            # EXPIRY_DAYS=0 olduğu için: 0 <= days < 0 asla true değil!
            return {
                "reason": f"Vade bitiş: {expiry} ({days} gün kaldı)",
                "trigger": "expiry",
            }

    # Satır 843+: (Kur şoku kontrolü devam)
```

**Analiz:**
- **Satır 837:** `if 0 <= days < EXPIRY_DAYS:`
- **Mevcut Durum:** `EXPIRY_DAYS = 0`
- **Sonuç:** `0 <= days < 0` **asla true** → vade günü OLAY tetiklenmiyor ✗

**Örnek Senaryo:**

| Tarih | Days | Kontrol | Sonuç |
|-------|------|---------|-------|
| Mart 29 (Cuma) | 2 | `0 <= 2 < 0` | False |
| Mart 30 (Cumartesi) | 1 | `0 <= 1 < 0` | False |
| Mart 31 (Pazartesi, VADE) | 0 | `0 <= 0 < 0` | **False** ✗ |
| Nisan 1 | -1 | `0 <= -1 < 0` | False |

---

## 6. TOP-5 KONTRAT SEÇİMİNDE VADE KONTROLÜ

### Dosya: `engine/top5_selection.py`

#### Bölüm 1: Vade Parametreleri

**Satır 83-85: Vade Geçişi Parametreleri**

```python
# ── Vade geçişi parametreleri (GCM paraleli) ────────────────────────
EXPIRY_NO_NEW_TRADE_DAYS: int = 0   # v5.9: Vade kısıtlaması kaldırıldı
EXPIRY_CLOSE_DAYS: int = 0          # v5.9: Vade kısıtlaması kaldırıldı
EXPIRY_OBSERVATION_DAYS: int = 0
```

**Durumu:** Tüm parametreler `0`

#### Bölüm 2: Vade Durumu Belirle

**Satır 644-671: _get_expiry_status() Fonksiyonu**

```python
def _get_expiry_status(self, today: date) -> dict[str, str]:
    """Her sembol için vade geçiş durumunu belirle."""

    # Satır 646: Gelecek vadeler
    future_expiries = sorted(d for d in VIOP_EXPIRY_DATES if d >= today)
    if not future_expiries:
        # Satır 648: Vade yok (imkansız)
        return {s: "normal" for s in WATCHED_SYMBOLS}

    # Satır 650: Sonraki vade
    next_expiry = future_expiries[0]
    # Satır 651: Kalan iş günü sayısı
    bdays_to_expiry = _business_days_until(next_expiry, today)

    # Satır 653-656: Geçmiş vadeler
    past_expiries = sorted(
        (d for d in VIOP_EXPIRY_DATES if d < today), reverse=True,
    )
    last_expiry = past_expiries[0] if past_expiries else None

    # Satır 658: Sembol başına durumu belirle
    status: dict[str, str] = {}
    for symbol in WATCHED_SYMBOLS:
        # Satır 660-664: Gözlem dönemi (OBSERVATION_DAYS=0)
        if last_expiry:
            bdays_since = _business_days_since(last_expiry, today)
            if 0 < bdays_since <= EXPIRY_OBSERVATION_DAYS:  # 0 < X <= 0 = false
                status[symbol] = "observation"
                continue

        # Satır 666-671: Diğer durumlar
        if bdays_to_expiry < EXPIRY_CLOSE_DAYS:            # X < 0 = false
            status[symbol] = "close"
        elif bdays_to_expiry < EXPIRY_NO_NEW_TRADE_DAYS:   # X < 0 = false
            status[symbol] = "no_new_trade"
        else:
            status[symbol] = "normal"  # ← HERDÜZEN BURAYA GİRER

    return status
```

**Sonuç:** Tüm semboller "normal" statüsü döner

#### Bölüm 3: Top-5 Filtreleme

**Satır 286-291: Vade Filtresi Uygulaması**

```python
# 6. Vade + haber filtresi
expiry_status = self._get_expiry_status(today)  # Satır 286
top5_final: list[str] = []
for sym, _sc in top5_above_avg:  # Satır 288
    status = expiry_status.get(sym, "normal")  # Satır 289
    if status in ("observation", "no_new_trade", "close"):  # Satır 290
        continue  # Atla
    if self._is_news_blocked(sym, today):  # Satır 291
        continue  # Atla
    # Diğer kontratlar top5_final'e eklenir
```

**Sonuç:**
- `status = "normal"` → `if status in (...)` **false**
- Hiçbir sembol atlanmaz
- Tüm 15 kontrat potansiyel top-5'e girebilir

---

## 7. VERI ALIMI (get_bars, get_tick)

### Dosya: `engine/mt5_bridge.py`

#### get_bars() — OHLCV Verisi

**Satır 699-735: get_bars() Fonksiyonu**

```python
def get_bars(
    self,
    symbol: str,  # BASE sembol (örn. "F_THYAO")
    timeframe: int = mt5.TIMEFRAME_M1,
    count: int = 500,
) -> pd.DataFrame:
    """OHLCV bar verisi çek."""

    # Satır 716-717: Bağlantı kontrolü
    if not self._ensure_connection():
        return pd.DataFrame()

    try:
        # Satır 720: BASE → MT5 çevirme
        mt5_name = self._to_mt5(symbol)  # "F_THYAO" → "F_THYAO0326"

        # Satır 721: MT5'e çağrı
        rates = self._safe_call(mt5.copy_rates_from_pos, mt5_name, timeframe, 0, count)

        # Satır 722-726: Hata kontrolü
        if rates is None or len(rates) == 0:
            logger.warning(
                f"Bar verisi alınamadı [{symbol}]: {mt5.last_error()}"
            )
            return pd.DataFrame()

        # Satır 728-731: DataFrame oluştur
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        logger.debug(f"Bar verisi [{symbol}]: {len(df)} bar, tf={timeframe}")
        return df
```

**Mekanizma:**
- Satır 720: `_to_mt5()` çevirme
- Satır 721: MT5'e eşlenmiş isimle çağrı
- **Otomatik vade geçişi:** Eşleme güncellenirse, veri kaynağı otomatik değişir

#### get_tick() — Anlık Fiyat

**Satır 738-772: get_tick() Fonksiyonu**

```python
def get_tick(self, symbol: str) -> Tick | None:
    """Anlık bid/ask/spread bilgisi."""

    if not self._ensure_connection():
        return None

    try:
        # Satır 751: BASE → MT5 çevirme
        mt5_name = self._to_mt5(symbol)  # "F_THYAO" → "F_THYAO0326"

        # Satır 752: MT5'e çağrı
        tick = self._safe_call(mt5.symbol_info_tick, mt5_name)
        if tick is None:
            logger.warning(f"Tick alınamadı [{symbol}]: {mt5.last_error()}")
            return None

        # Satır 757-763: Tick nesnesi oluştur
        result = Tick(
            symbol=symbol,  # BASE isim döndür
            bid=tick.bid,
            ask=tick.ask,
            spread=round(tick.ask - tick.bid, 6),
            time=datetime.fromtimestamp(tick.time),
        )

        # Satır 764-767: Log
        logger.debug(
            f"Tick [{symbol}]: bid={result.bid}, ask={result.ask}, "
            f"spread={result.spread}"
        )
        return result
```

**Not:** Satır 758 — BASE isim döndürüldüğü için, çağıran kod vade değişimini farketmez.

---

## 8. POZİSYON YÖNETİMİ

### Dosya: `engine/mt5_bridge.py`

#### get_positions() — Açık Pozisyonlar

**Satır 1649-1698: get_positions() Fonksiyonu**

```python
def get_positions(self) -> list[dict[str, Any]]:
    """Tüm açık pozisyonları getir."""

    # Satır 1659-1661: Bağlantı kontrolü
    if not self._ensure_connection():
        logger.warning("get_positions: MT5 bağlantısı yok")
        return None

    try:
        # Satır 1664: MT5'ten tüm pozisyonları al
        positions = self._safe_call(mt5.positions_get)

        # ... (hata kontrolü — Satır 1665-1672)

        # Satır 1674-1691: Filtrele ve dönüştür
        result: list[dict[str, Any]] = []
        for pos in positions:
            # Satır 1676: MT5 → BASE çevirme (FALLBACK ile!)
            base = self._to_base(pos.symbol)
            if base is None:
                continue  # İzlenmeyen sembol

            # Satır 1679-1691: Pozisyon bilgisi
            result.append({
                "ticket": pos.ticket,
                "symbol": base,  # BASE isim döndür
                "type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "sl": pos.sl,
                "tp": pos.tp,
                "price_current": pos.price_current,
                "profit": pos.profit,
                "swap": pos.swap,
                "time": datetime.fromtimestamp(...).isoformat(),
            })

        logger.debug(f"Açık pozisyon sayısı: {len(result)}")
        return result
```

**Kritik (Satır 1676):**
- `self._to_base(pos.symbol)` — MT5'deki gerçek isimden base çıkar
- **Fallback mekanizması:** Eski vade bile tanınır ✓

#### close_position() — Pozisyon Kapatma

**Satır 1226-1333: close_position() Fonksiyonu**

```python
def close_position(
    self,
    ticket: int,
    expected_volume: float | None = None,
) -> dict[str, Any] | None:
    """Açık pozisyonu kapat."""

    # Satır 1231-1239: Docstring (netting koruması)
    # VİOP netting modda, expected_volume ile partial close

    # Satır 1241: Thread-safe (_write_lock)
    # Satır 1259-1277: MT5'ten pozisyon bilgisi al

    pos = self._safe_call(mt5.positions_get, ticket=ticket)
    if not pos or len(pos) == 0:
        # Satır 1281-1283: Pozisyon bulunamadı
        logger.error(f"POZİSYON BULUNAMADI [ticket={ticket}]")
        return None

    # ... (lot hesaplaması — Satır 1286-1299)

    # Satır 1302-1310: Kapatma emri hazırla
    # Ters yönde market emri gönder (netting mode)

    # Satır 1311-1323: Sonuç kontrolü
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.critical(
            f"POZİSYON KAPATILAMADI [{ticket}]: retcode={result.retcode}, "
            f"comment={result.comment} — POZİSYON HÂLÂ AÇIK!"
        )
        return None
```

**Not:** Kapatma sırasında sembol çevirme yoktur (ticket zaten MT5'te açıktır).

---

## 9. EMIR GÖNDERIMI

### Dosya: `engine/mt5_bridge.py`

#### send_order() — 2 Aşamalı Emir

**Satır 775-1223: send_order() Fonksiyonu**

**ADIM 1: Hazırlık**

```python
# Satır 806-814: Lock ve bağlantı kontrolü
with self._order_lock, self._write_lock:
    if not self._ensure_connection():
        self._last_order_error = {
            "reason": "MT5 bağlantısı kurulamadı",
        }
        return None

# Satır 816-825: Yön kontrolü
if direction.upper() == "BUY":
    mt5_type = mt5.ORDER_TYPE_BUY
elif direction.upper() == "SELL":
    mt5_type = mt5.ORDER_TYPE_SELL
else:
    logger.error(f"Geçersiz yön: {direction}")
    return None

# Satır 827: KRITIK — BASE → MT5 çevirme
mt5_name = self._to_mt5(symbol)
```

**Satır 827: Sembol Çevirme**
- Input: `symbol = "F_THYAO"`
- Eşleme: `_symbol_map["F_THYAO"] = "F_THYAO0326"`
- Output: `mt5_name = "F_THYAO0326"`

**ADIM 2: Sembol Bilgisi**

```python
# Satır 830: Sembol bilgisi al
sym_info = self._safe_call(mt5.symbol_info, mt5_name)
# mt5_name'i kullanarak MT5'ten bilgi çek

# Satır 842-844: Tick size (fiyat adımı)
tick_size = sym_info.trade_tick_size
if tick_size <= 0:
    tick_size = sym_info.point
```

**ADIM 3: Lot Validasyonu**

```python
# Satır 847-860: Min/Max/Step kontrolü
vol_min = sym_info.volume_min
vol_max = sym_info.volume_max
vol_step = sym_info.volume_step if sym_info.volume_step > 0 else vol_min

if lot < vol_min or lot > vol_max:
    logger.error(
        f"Lot sınır dışı [{symbol}]: {lot} (min={vol_min}, max={vol_max})"
    )
    return None

lot = round(lot / vol_step) * vol_step
lot = max(vol_min, min(vol_max, lot))
```

**ADIM 4: Emir Kurulu Hazırla**

```python
# Satır 895-903: Request sözlüğü
request: dict[str, Any] = {
    "action": action,
    "symbol": mt5_name,          # ← Çevrilmiş isim
    "volume": lot,
    "type": mt5_type,
    "price": price,
    "type_filling": filling,
    "type_time": mt5.ORDER_TIME_GTC,
    "comment": "USTAT",
}

# Satır 906-913: Limit emirlere expiration ekle
if action == mt5.TRADE_ACTION_PENDING:
    # ... (seans sonu expiration)
```

**ADIM 5: Emir Gönder (AŞAMA 1)**

```python
# Satır 915-920: Log
logger.info(
    f"Emir gönderiliyor (SL/TP ayrı): {direction} {lot} lot "
    f"{symbol} @ {price:.4f} [{order_type}] "
    f"filling={filling} request={request}"
)

# Satır 921: MT5'e gönder (15 saniye timeout)
result = self._safe_call(mt5.order_send, request, timeout=15.0)
```

**ADIM 6: Emir Kontrolü**

```python
# Satır 935-936: Kabul edilen sonuçlar
accepted = {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
if result.retcode not in accepted:
    # Satır 937-972: Hata işlemesi
    logger.error(
        f"Emir reddedildi [{symbol}]: retcode={result.retcode}, "
        f"comment={result.comment}"
    )
    return None

# Satır 974-975: Başarılı
order_result = result._asdict()
order_result["sl_tp_applied"] = False
```

**ADIM 7: SL/TP Ekleme (AŞAMA 2)**

```python
# Satır 987-995: SL/TP yuvarlama
if sl > 0 or tp > 0:
    sl_rounded = (
        round(sl / tick_size) * tick_size if sl > 0 else 0.0
    )
    tp_rounded = (
        round(tp / tick_size) * tick_size if tp > 0 else 0.0
    )

# Satır 997-998: Stops level kontrolü
stops_level = getattr(sym_info, "trade_stops_level", 0) or 0
```

**(Devam Satır 998+)**

---

## 10. VADE GÜNÜ SENARYO SAATLERİ

### Main Loop Timing

**Dosya:** `engine/main.py` — `_run_single_cycle()`

```
09:45 (Piyasa Açılış - 15 dakika öncesi)
├─ _heartbeat_mt5() — MT5 bağlantı kontrolü
├─ _resolve_symbols() ← VADE GÜNÜ ÇAĞRISI
│  └─ target_suffix = "0426" (Nisan 2026)
│  └─ F_THYAO → F_THYAO0426 eşlemesi
│  └─ _symbol_map güncellenir (atomik)
│
├─ _update_data() — Piyasa verisi
│  └─ get_bars("F_THYAO") → "F_THYAO0426" verisi
│  └─ get_tick("F_THYAO") → "F_THYAO0426" fiyatı
│
├─ BABA cycle — Risk kontrolü
├─ check_risk_limits() — can_trade kararı
├─ OĞUL — Sinyal üretim
│  └─ send_order("F_THYAO", ...) → "F_THYAO0426" emirle
│
└─ (Her 10 saniye tekrarla)

17:45 (Vade Sonu)
└─ EOD kontrol → Tüm pozisyonlar kapatılmalı
   ├─ Eski vade (F_THYAO0326) açıksa → problem
   └─ Yeni vade (F_THYAO0426) açıksa → kapatılır
```

---

## 11. KRITIK SATIR NUMARALARı (Özet)

| Olay | Dosya | Satır | Kod |
|------|-------|-------|-----|
| **Vade günü tespiti** | baba.py | 243-254 | `VIOP_EXPIRY_DATES` |
| **Vade parametresi** | baba.py | 93 | `EXPIRY_DAYS = 0` |
| **Vade OLAY kontrolü** | baba.py | 837 | `if 0 <= days < EXPIRY_DAYS:` ← KAPATILMIŞ |
| **Sonraki ay suffix** | mt5_bridge.py | 294 | `f"{next_month:02d}{next_year % 100:02d}"` |
| **Rollover başlangıcı** | mt5_bridge.py | 317 | `target_suffix = self._next_expiry_suffix()` |
| **Yöntem 1 (Hedef)** | mt5_bridge.py | 355-367 | Vade günü doğru eşleme |
| **Yöntem 2 (Fallback)** | mt5_bridge.py | 375-391 | Normal gün aktif seçimi |
| **Atomik swap** | mt5_bridge.py | 428-430 | `with self._map_lock:` |
| **Günlük çağrı** | main.py | 740 | `self.mt5._resolve_symbols()` |
| **Base → MT5** | mt5_bridge.py | 443 | `_symbol_map.get(base_symbol, base_symbol)` |
| **MT5 → Base** | mt5_bridge.py | 457-459 | Fallback: `startswith()` |
| **Emir gönderimi** | mt5_bridge.py | 827 | `mt5_name = self._to_mt5(symbol)` |
| **Top-5 durumu** | top5_selection.py | 671 | `status[symbol] = "normal"` ← HERDÜzen |

---

**Rapor Sonu**
