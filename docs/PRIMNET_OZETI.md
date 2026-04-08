# PRİMNET İşlem Yönetimi Sistemi — Kapsamlı Özet

**Tarih:** 6 Nisan 2026
**Versiyon:** ÜSTAT v5.9
**Hazırlayan:** Claude — Kod Analizi

---

## İÇİNDEKİLER

1. [PRİMNET Nedir?](#primnet-nedir)
2. [Temel Kavramlar](#temel-kavramlar)
3. [Sistem Mimarisi](#sistem-mimarisi)
4. [Prim Hesaplama](#prim-hesaplama)
5. [H-Engine Bileşenleri](#h-engine-bileşenleri)
6. [Devir Süreci (Atomik)](#devir-süreci-atomik)
7. [Pozisyon Yönetimi Döngüsü](#pozisyon-yönetimi-döngüsü)
8. [Trailing Stop Mekanizması](#trailing-stop-mekanizması)
9. [Hedef Kapanış Mantığı](#hedef-kapanış-mantığı)
10. [Breakeven Kontrol](#breakeven-kontrol)
11. [SL/TP Modları](#sltp-modları)
12. [Netting Senkronizasyonu](#netting-senkronizasyonu)
13. [Günlük PRİMNET Yenileme](#günlük-primnet-yenileme)
14. [API Endpoint'leri](#api-endpoints)
15. [Config Parametreleri](#config-parametreleri)

---

## PRİMNET Nedir?

**PRİMNET** (Prim Bazlı Net Emir Takip), ÜSTAT'ın **hibrit pozisyon yönetim sistemidir**.

### Temel Prensip
- **İnsan açar** → İşlemi manüel veya OĞUL'dan açar
- **Robot yönetir** → PRİMNET prim bazlı SL/TP ve trailing ile yönetir
- **Robot kapatır** → Hedef veya SL hit'i tetikler, otomatik kapatır

### Neden PRİMNET?
VİOP'ta (Vadeli İşlem ve Opsiyon Piyasası):
- **Tavan fiyat** = Referans × 1.10
- **Taban fiyat** = Referans × 0.90
- Günlük limite yaklaşanlar (tavan/tabana ±0.5 prim kala) otomatik kapatılır

**PRİMNET** bu dinamiğe uygun, **prim cinsinden hesaplanan** bir stop-loss ve hedef sistemidir.

---

## Temel Kavramlar

| Kavram | Tanım | Örnek |
|--------|-------|-------|
| **Referans Fiyat** | Günlük uzlaşma = (tavan + taban) / 2 | 28000 TRY |
| **Prim** | (Fiyat - Referans) / (Referans × 0.01) | +5.3 prim |
| **1 Prim (1P)** | Referans × %1 | 28000 × 0.01 = 280 TRY |
| **Trailing** | Sabit mesafeli kâr takibi | 1.5 prim (tavsiye) |
| **Hedef** | Tavan/tabana 0.5 prim kala | ±9.5 prim (tavsiye) |
| **Breakeven** | SL'yi entry'ye taşıma noktası | Profit ≥ 1×ATR |
| **H-Baba** | Devir ön kontrolü (risk) | 10 adımlı kontrol |
| **H-Oğul** | Çalışan pozisyon yönetimi | Trailing + hedef + kapanış |

---

## Sistem Mimarisi

```
┌─────────────────┐
│ Frontend/React  │  (Dashboard, HybridTrade.jsx, PrimnetDetail.jsx)
└────────┬────────┘
         │ HTTP/WebSocket (port 5173 dev, 8000 API)
         ↓
┌─────────────────┐
│  API Sunucu     │  (FastAPI, uvicorn port 8000)
│  /hybrid/*      │
└────────┬────────┘
         │
         ↓
┌─────────────────────────────────────────────┐
│          H-ENGINE (engine/h_engine.py)      │
│  ┌─────────────────────────────────────┐   │
│  │ H-BABA (devir ön kontrolü)          │   │
│  │ • check_transfer() — 10 adım kontrol│   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │ H-OĞUL (çalışan yönetim)            │   │
│  │ • run_cycle() — her 10sn             │   │
│  │ • Trailing stop (PRİMNET)            │   │
│  │ • Hedef kapanış                      │   │
│  │ • Software/Native SL/TP              │   │
│  └─────────────────────────────────────┘   │
└────────┬────────────────────────────────────┘
         │
         ↓
┌─────────────────┐
│  MT5 Bridge     │  (engine/mt5_bridge.py)
│  modify / close │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  MT5 Terminal   │  (GCM Capital)
│  (gerçek pozisyon)
└─────────────────┘

         ↓ (veritabanı)
┌─────────────────┐
│  SQLite DB      │  (trades.db, ustat.db)
│  hybrid_*       │
│  events         │
└─────────────────┘
```

---

## Prim Hesaplama

### Referans Fiyat Alınması

```python
def _get_reference_price(symbol: str) -> float | None:
    """
    VİOP'ta günlük limit:
        Tavan = Referans × 1.10 (+%10)
        Taban = Referans × 0.90 (-%10)

    Dolayısıyla:
        Referans = (Tavan + Taban) / 2
    """
    sym = mt5.get_symbol_info(symbol)
    tavan = sym.session_price_limit_max      # En yüksek limit
    taban = sym.session_price_limit_min      # En düşük limit
    referans = (tavan + taban) / 2.0

    # Doğrulama: spread %15-%25 olmalı (±%10 limit farkı)
    spread_pct = (tavan - taban) / referans
    if spread_pct < 0.10 or spread_pct > 0.30:
        logger.warning(f"Referans fiyat şüpheli: {spread_pct*100:.1f}%")

    return referans
```

**Örnek:**
```
AKBNK (Akbank)
  Tavan:    28500 TRY
  Taban:    27500 TRY
  Referans: (28500 + 27500) / 2 = 28000 TRY
  Spread:   (28500 - 27500) / 28000 = %3.57 (normal)
```

### Fiyatı Prime Çevirme

```python
def _price_to_prim(price: float, ref_price: float) -> float:
    """
    Prim = (Fiyat - Referans) / (Referans × 0.01)

    Çünkü 1 Prim = Referans × %1
    """
    one_prim = ref_price * 0.01  # 28000 × 0.01 = 280 TRY
    if one_prim <= 0:
        return 0.0
    return (price - ref_price) / one_prim
```

**Örnek:**
```
Referans = 28000 TRY
1 Prim = 280 TRY

Fiyat 28280 TRY ise:
  Prim = (28280 - 28000) / 280 = +1.0 prim

Fiyat 28560 TRY ise:
  Prim = (28560 - 28000) / 280 = +2.0 prim

Fiyat 27720 TRY ise:
  Prim = (27720 - 28000) / 280 = -1.0 prim
```

### Prime Fiyat Çevirme

```python
def _prim_to_price(prim: float, ref_price: float) -> float:
    """Ters işlem"""
    return ref_price + prim * (ref_price * 0.01)
```

**Örnek:**
```
Referans = 28000, Prim = +3.0
  Fiyat = 28000 + 3.0 × 280 = 28840 TRY
```

---

## H-Engine Bileşenleri

### 1. HybridPosition Veri Modeli

```python
@dataclass
class HybridPosition:
    # Temel bilgi
    ticket: int                    # MT5 position ID
    symbol: str                    # "AKBNK-H26", "GARAN-H26"
    direction: str                 # "BUY" | "SELL"
    volume: float                  # Lot sayısı
    entry_price: float             # Giriş fiyatı

    # Yönetim bilgisi
    entry_atr: float               # Devir anındaki ATR (SABİT)
    initial_sl: float              # İlk SL (devir anında)
    initial_tp: float              # İlk TP (devir anında)
    current_sl: float              # Mevcut SL (trailing ile güncellenir)
    current_tp: float              # Mevcut TP

    # Durum
    state: str = "ACTIVE"          # ACTIVE | CLOSED
    breakeven_hit: bool = False    # Trailing'in çalışıp çalışmadığı
    trailing_active: bool = False  # Trailing stop devrede mi?
    reference_price: float = 0.0   # PRİMNET uzlaşma fiyatı (devir günü)

    # İdari
    transferred_at: str = ""       # Devir zamanı (ISO 8601)
    db_id: int = 0                 # Database ID
```

### 2. HEngine Sınıfı — __init__ Parametreleri

```python
class HEngine:
    def __init__(self, config, mt5, db, baba, pipeline):
        # ── Config parametreleri ──
        self._enabled: bool = True             # Hibrit motor aktif mi?
        self._max_concurrent: int = 3          # Max eşzamanlı hibrit
        self._config_daily_limit: float = 500  # Günlük zarar limiti (TRY)
        self._sl_atr_mult: float = 2.0         # SL = entry ± ATR*2 (fallback)
        self._tp_atr_mult: float = 2.0         # TP = entry ± ATR*2 (fallback)
        self._native_sltp: bool = False        # MT5 native SL/TP mi?

        # ── PRİMNET Config ──
        self._primnet_trailing: float = 1.5    # Trailing mesafe (prim)
        self._primnet_target: float = 9.5      # Hedef (prim)

        # ── Bellek ──
        self.hybrid_positions: dict[int, HybridPosition] = {}
        self._daily_hybrid_pnl: float = 0.0    # Günlük hibrit kâr/zarar
        self._close_retry_counts: dict = {}    # Kapatma deneme sayaçları
        self._eod_notified_date: str = ""      # EOD bildirimi gönderildi mi?
        self._daily_reset_done: str = ""       # PRİMNET yenilemesi yapıldı mı?
```

---

## Devir Süreci (Atomik)

### 1. Devir Ön Kontrolü — check_transfer() — 10 Adım

H-Baba'nın sorumluluğu. Hibrite devretmeden önce 10 kontrol:

| # | Kontrol | Hata Kodu |
|---|---------|-----------|
| 1 | H-Engine aktif mi? | "Hibrit motor devre dışı" |
| 2 | Kill-switch L3 aktif mi? | "Kill-switch L3 aktif" |
| 3 | İşlem saatleri içinde mi? (09:40-17:50) | "İşlem saatleri dışında" |
| 4 | Ticket MT5'te açık mi? | "Ticket MT5'te bulunamadı" |
| 5 | Sembol zaten hibrit mi? (netting lock) | "Zaten hibrit yönetiminde" |
| 6 | Ticket zaten hibrit mi? (bellek+DB) | "Ticket zaten hibrit" |
| 7 | Eşzamanlı limit aşıldı mı? | "Limit aşıldı (n/max)" |
| 8 | Günlük zarar limiti aşıldı mı? | "Zarar limiti aşıldı" |
| 9 | ATR verisi mevcut mu? | "ATR verisi yok" |
| 10 | Fiyat SL'yi ihlal ediyor mu? | "Fiyat SL altında/üstünde" |

**Kod:**
```python
def check_transfer(self, ticket: int) -> dict[str, Any]:
    result = {
        "can_transfer": False,
        "reason": "",
        "symbol": "",
        "direction": "",
        "volume": 0.0,
        "entry_price": 0.0,
        "current_price": 0.0,
        "atr_value": 0.0,
        "suggested_sl": 0.0,
        "suggested_tp": 0.0,
        "hybrid_daily_pnl": self._daily_hybrid_pnl,
        "hybrid_daily_limit": self._config_daily_limit,
        "active_hybrid_count": len(self.hybrid_positions),
        "max_hybrid_count": self._max_concurrent,
    }

    # 1. H-Engine aktif?
    if not self._enabled:
        result["reason"] = "Hibrit motor devre dışı"
        return result

    # 2. Kill-switch seviyesi
    if self.baba and self.baba.kill_switch_level >= 3:
        result["reason"] = "Kill-switch L3 aktif"
        return result

    # 3-9. [Benzer kontroller...]

    # Başarılıysa SL/TP önerileri dön
    result["can_transfer"] = True
    result["suggested_sl"] = ...
    result["suggested_tp"] = ...
    return result
```

### 2. Atomik Devir — transfer_to_hybrid()

Başarısızlık durumunda "hiçbir şey değişmez" garantisi:

```python
def transfer_to_hybrid(self, ticket: int) -> dict[str, Any]:
    # Adım 1: Ön kontrol
    check = self.check_transfer(ticket)
    if not check["can_transfer"]:
        return {"success": False, "message": check["reason"]}

    symbol = check["symbol"]
    direction = check["direction"]
    entry_price = check["entry_price"]
    atr_value = check["atr_value"]

    # Adım 2: PRİMNET SL/TP hesapla
    ref_price = self._get_reference_price(symbol) or 0.0
    if ref_price > 0:
        # Prim bazlı hesaplama
        entry_prim = self._price_to_prim(entry_price, ref_price)
        if direction == "BUY":
            stop_prim = entry_prim - self._primnet_trailing      # -1.5 prim
            target_prim = self._primnet_target                   # +9.5 prim
        else:
            stop_prim = entry_prim + self._primnet_trailing      # +1.5 prim
            target_prim = -self._primnet_target                  # -9.5 prim

        suggested_sl = self._prim_to_price(stop_prim, ref_price)
        suggested_tp = self._prim_to_price(target_prim, ref_price)
        logger.info(f"PRİMNET devir: giriş_prim={entry_prim:.2f} "
                    f"stop_prim={stop_prim:.2f} hedef_prim={target_prim:.2f}")
    else:
        # Fallback: ATR kullan
        if direction == "BUY":
            suggested_sl = entry_price - (atr_value * self._sl_atr_mult)
            suggested_tp = entry_price + (atr_value * self._tp_atr_mult)
        else:
            suggested_sl = entry_price + (atr_value * self._sl_atr_mult)
            suggested_tp = entry_price - (atr_value * self._tp_atr_mult)

    # Adım 3: MT5'e SL/TP yaz (BAŞARISIZ OLURSA DEVIR İPTAL)
    if self._native_sltp:
        # Native mod: Atomik TRADE_ACTION_SLTP
        modify_result = self.mt5.modify_position(
            ticket, sl=suggested_sl, tp=suggested_tp
        )
        if modify_result is None:
            return {"success": False, "message": "MT5 SL/TP ataması başarısız"}
    else:
        # Software mod: Safety SL'yi MT5'e yaz (gap koruması)
        try:
            self.mt5.modify_position(ticket, sl=suggested_sl)
        except Exception as exc:
            logger.warning(f"Güvenlik ağı SL atanamadı: {exc}")

    # Adım 4: DB'ye kaydet
    db_id = self.db.insert_hybrid_position({
        "ticket": ticket,
        "symbol": symbol,
        "direction": direction,
        "volume": check["volume"],
        "entry_price": entry_price,
        "entry_atr": atr_value,
        "initial_sl": suggested_sl,
        "initial_tp": suggested_tp,
        "current_sl": suggested_sl,
        "current_tp": suggested_tp,
    })

    # Adım 5: Belleğe ekle
    hp = HybridPosition(
        ticket=ticket,
        symbol=symbol,
        direction=direction,
        volume=check["volume"],
        entry_price=entry_price,
        entry_atr=atr_value,
        initial_sl=suggested_sl,
        initial_tp=suggested_tp,
        current_sl=suggested_sl,
        current_tp=suggested_tp,
        state="ACTIVE",
        transferred_at=datetime.now().isoformat(),
        db_id=db_id,
        reference_price=ref_price,
    )
    hp.breakeven_hit = True  # PRİMNET: Trailing hemen başlar
    self.hybrid_positions[ticket] = hp

    # Adım 6: Event log
    self.db.insert_hybrid_event(
        ticket=ticket, symbol=symbol, event="TRANSFER",
        details={
            "direction": direction,
            "entry_price": entry_price,
            "sl": suggested_sl,
            "tp": suggested_tp,
        }
    )

    return {
        "success": True,
        "message": "Pozisyon hibrit yönetime devredildi",
        "ticket": ticket,
        "symbol": symbol,
        "sl": suggested_sl,
        "tp": suggested_tp,
        "entry_atr": atr_value,
    }
```

**Devir Öncesi Kontrol Sonucu (API Response):**
```json
{
  "can_transfer": true,
  "reason": "Hibrite devir uygun",
  "symbol": "AKBNK-H26",
  "direction": "BUY",
  "volume": 1.0,
  "entry_price": 28150.0,
  "current_price": 28200.0,
  "atr_value": 245.5,
  "suggested_sl": 27904.5,
  "suggested_tp": 29195.0,
  "hybrid_daily_pnl": -150.0,
  "hybrid_daily_limit": 500.0,
  "active_hybrid_count": 1,
  "max_hybrid_count": 3
}
```

---

## Pozisyon Yönetimi Döngüsü

### run_cycle() — Her 10 Saniye

H-Oğul'un sorumluluğu. Aktif hibrit pozisyonları yönetir:

```python
def run_cycle(self) -> None:
    # ADIM 1: OLAY rejimi kontrolü
    if baba.current_regime.regime_type == RegimeType.OLAY:
        self.force_close_all("OLAY_REGIME")  # Tüm hibrit kapatılır
        return

    # ADIM 2: EOD 17:45 bildirimi
    if now.time() >= 17:45 and not notified_today:
        send_notification("Hibrit pozisyonlar açık, kapatmak veya tutmak?")
        self._eod_notified_date = today

    # ADIM 3: Günlük PnL yenileme
    self._refresh_daily_pnl()  # Gün değişmişse sıfırla

    # ADIM 4: MT5'ten güncel pozisyonları al
    mt5_positions = self.mt5.get_positions()
    mt5_by_ticket = {p["ticket"]: p for p in mt5_positions}

    # ADIM 5: Her aktif pozisyon için
    for ticket in list(self.hybrid_positions.keys()):
        hp = self.hybrid_positions.get(ticket)
        if hp.state != "ACTIVE":
            continue

        mt5_pos = mt5_by_ticket.get(ticket)

        # 5a. Sync: MT5'te hala açık mı?
        if mt5_pos is None:
            miss_count = ++miss_counts[ticket]
            if miss_count < 3:
                continue  # 3 ardışık miss doğrulama
            self._handle_external_close(hp)  # Harici kapanış işle
            continue

        current_price = mt5_pos["price_current"]
        profit = mt5_pos["profit"]
        swap = mt5_pos["swap"]

        # 5b. Netting hacim senkronizasyonu
        if mt5_pos["volume"] != hp.volume:
            self._sync_netting_volume(hp, mt5_pos["volume"], mt5_pos["price_open"])

        # 5c. Software SL/TP kontrolü (native kapalıysa)
        if not self._native_sltp:
            if self._check_software_sltp(hp, current_price, profit, swap):
                continue  # Kapatıldı

        # 5d. PRİMNET hedef kontrolü
        if self._check_primnet_target(hp, current_price, profit, swap):
            continue  # Hedef kapanış

        # 5e. Breakeven kontrolü
        self._check_breakeven(hp, current_price, profit, swap)

        # 5f. Trailing stop kontrolü
        self._check_trailing(hp, current_price, profit, swap)
```

---

## Trailing Stop Mekanizması

### PRİMNET Trailing — Sabit Mesafeli Takip

```python
def _check_trailing(self, hp: HybridPosition, current_price: float,
                    profit: float, swap: float) -> None:
    """
    Trailing stop: SL sadece DAHA İYİ yöne taşınır.

    Mesafe HER ZAMAN SABİT: 1.5 prim (ayarlanabilir)
    BUY: current_price'ın 1.5 prim altında
    SELL: current_price'ın 1.5 prim üstünde
    """

    if not hp.breakeven_hit:
        return  # Trailing henüz aktif değil

    # Yeni SL hesapla
    new_sl = self._calc_primnet_trailing_sl(hp, current_price)
    if new_sl is None:
        return

    # SL sadece daha iyi yöne taşınır (asla geri gelmez)
    if hp.direction == "BUY":
        if new_sl <= hp.current_sl:
            return  # Daha kötü, taşıma
    else:
        if new_sl >= hp.current_sl:
            return  # Daha kötü, taşıma

    # MT5'e native SL yaz
    modify_result = self.mt5.modify_position(hp.ticket, sl=new_sl)
    if modify_result is None:
        # Modify başarısız — sadece bellekte güncelle (software fallback)
        retry_key = f"tr_modify_{hp.ticket}"
        self._close_retry_counts[retry_key] += 1
        if self._close_retry_counts[retry_key] >= 3:
            logger.critical(f"Trailing SL 3x modify başarısız — gap riski!")

    # Bellekte güncelle
    old_sl = hp.current_sl
    hp.current_sl = new_sl
    hp.trailing_active = True

    # DB ve event log
    self.db.update_hybrid_position(hp.ticket, {
        "current_sl": new_sl,
        "trailing_active": 1,
    })
    self.db.insert_hybrid_event(
        ticket=hp.ticket,
        symbol=hp.symbol,
        event="TRAILING_UPDATE",
        details={
            "old_sl": old_sl,
            "new_sl": new_sl,
            "price": current_price,
            "pnl": profit + swap,
        }
    )

    logger.info(f"Trailing SL: {hp.symbol} {old_sl:.4f} → {new_sl:.4f}")
```

### Trailing SL Hesaplama

```python
def _calc_primnet_trailing_sl(self, hp: HybridPosition,
                              current_price: float) -> float | None:
    """
    Prim bazlı trailing SL hesabı.

    Giriş prim'i referans olarak alır, güncel fiyatı kullanır.
    Mesafe HER ZAMAN SABİT (faz ayrımı yok).
    """

    # Referans fiyat al
    ref_price = self._get_reference_price(hp.symbol)
    if ref_price is None:
        return None

    # Primler hesapla
    entry_prim = self._price_to_prim(hp.entry_price, ref_price)
    current_prim = self._price_to_prim(current_price, ref_price)

    # Kâr primi (yöne göre)
    if hp.direction == "BUY":
        profit_prim = current_prim - entry_prim
    else:
        profit_prim = entry_prim - current_prim

    # Trailing mesafe SABİT
    trailing_dist = self._primnet_trailing  # 1.5 prim

    # Stop prim hesapla (current'ın trailing_dist prim altında/üstünde)
    if hp.direction == "BUY":
        stop_prim = current_prim - trailing_dist
    else:
        stop_prim = current_prim + trailing_dist

    # Prime'den fiyata çevir
    new_sl = self._prim_to_price(stop_prim, ref_price)

    logger.debug(
        f"PRİMNET trailing [{hp.symbol}]: "
        f"giriş_prim={entry_prim:.2f} güncel_prim={current_prim:.2f} "
        f"kâr_prim={profit_prim:.2f} trailing_dist={trailing_dist} "
        f"stop_prim={stop_prim:.2f} → SL={new_sl:.4f}"
    )

    return new_sl
```

**Örnek:**
```
AKBNK-H26 BUY işlemi:
  Referans: 28000 TRY
  1 Prim: 280 TRY

  Giriş fiyatı: 28150 TRY
    Giriş prim = (28150 - 28000) / 280 = +0.54 prim

  Güncel fiyat: 28420 TRY (kâr yönü)
    Güncel prim = (28420 - 28000) / 280 = +1.5 prim
    Kâr prim = 1.5 - 0.54 = +0.96 prim

  Trailing mesafe: 1.5 prim (sabit)

  Yeni Stop prim = 1.5 - 1.5 = 0.0 prim
    Yeni SL = 28000 + 0.0 × 280 = 28000 TRY

  Güncel piyasa: 28420 TRY
  SL: 28000 TRY (420 TRY kâra sabitlenmiş)
```

**Faz Sistemi YOK:**
PRİMNET'te sadece bir faz var — **sabit 1.5 prim trailing**.
Eski "Faz 1 (1.5P) → Faz 2 (1.0P)" sistemi kaldırıldı.

---

## Hedef Kapanış Mantığı

### PRİMNET Target — Tavan/Tabana 0.5 Prim Kala

```python
def _check_primnet_target(self, hp: HybridPosition, current_price: float,
                          profit: float, swap: float) -> bool:
    """
    Hedef kapanış: Pozisyon tavan/tabana 0.5 prim kala otomatik kapanır.

    VİOP limit: Tavan = Ref × 1.10, Taban = Ref × 0.90
    Tavan/taban primi: ±10 prim
    Target: ±9.5 prim (0.5 prim kala kapanış)
    """

    # Referans fiyat al
    ref_price = self._get_reference_price(hp.symbol)
    if ref_price is None:
        return False

    # Güncel prim hesapla
    current_prim = self._price_to_prim(current_price, ref_price)
    target = self._primnet_target  # 9.5 prim

    # Hedef hit kontrolü
    hit = False
    if hp.direction == "BUY" and current_prim >= target:
        # BUY: tavan'a 0.5 prim kala
        hit = True
    elif hp.direction == "SELL" and current_prim <= -target:
        # SELL: taban'a 0.5 prim kala
        hit = True

    if not hit:
        return False

    # Retry limiti kontrolü (başarısız kapatmalar için)
    retry_key = f"primnet_target_{hp.ticket}"
    retry_count = self._close_retry_counts.get(retry_key, 0)
    if retry_count >= self._MAX_CLOSE_RETRIES:
        return False

    logger.info(f"PRİMNET HEDEF: {hp.symbol} {hp.direction} "
                f"prim={current_prim:.2f} hedef=±{target} — kapatılıyor")

    # Pozisyonu kapat
    close_result = self.mt5.close_position(
        hp.ticket, expected_volume=hp.volume
    )

    if close_result is None:
        self._close_retry_counts[retry_key] = retry_count + 1
        logger.error(f"PRİMNET hedef kapanış başarısız (deneme {retry_count+1}/3)")
        return False

    # Başarılı — kapatmayı bitir
    self._close_retry_counts.pop(retry_key, None)
    total_pnl = profit + swap
    self._finalize_close(hp, "PRIMNET_TARGET", total_pnl, swap)

    logger.info(f"PRİMNET hedef kapanış başarılı: {hp.symbol} pnl={total_pnl:.2f}")
    return True
```

**Örnek:**
```
AKBNK-H26 BUY:
  Referans: 28000 TRY
  Tavan primi: +10 prim (28000 × 1.10 = 30800)
  Target: +9.5 prim (0.5 kala)

  Fiyat: 30660 TRY
    Prim = (30660 - 28000) / 280 = +9.5 prim ✓ HIT!

  Pozisyon otomatik kapanır.

AKBNK-H26 SELL:
  Taban primi: -10 prim (28000 × 0.90 = 25200)
  Target: -9.5 prim (0.5 kala)

  Fiyat: 25340 TRY
    Prim = (25340 - 28000) / 280 = -9.5 prim ✓ HIT!

  Pozisyon otomatik kapanır.
```

---

## Breakeven Kontrol

### PRİMNET Breakeven — Trailing Başlangıç

```python
def _check_breakeven(self, hp: HybridPosition, current_price: float,
                     profit: float, swap: float) -> None:
    """
    PRİMNET'te breakeven ayrı bir adım DEĞİLDİR.

    Devir anında SL zaten prim bazlı hesaplanmıştır.
    Bu fonksiyon sadece breakeven_hit = True yapar.
    Trailing hemen başlar (faz ayrımı yok).
    """

    if hp.breakeven_hit:
        return  # Zaten trailing aktif

    # PRİMNET: Breakeven hemen True yapılır (devir anında)
    hp.breakeven_hit = True
```

**Not:** Eski sistem'de breakeven "profit ≥ 1×ATR" kontrollüydü.
PRİMNET'te bu kontrol yapılmaz — trailing hemen başlar.

---

## SL/TP Modları

### 1. Native Mode (native_sltp = true)

MT5'in kendi SL/TP mekanizması kullanılır:

```python
if self._native_sltp:
    # Devir anında
    modify_result = self.mt5.modify_position(
        ticket, sl=suggested_sl, tp=suggested_tp
    )

    # Trailing'de
    new_sl = self._calc_primnet_trailing_sl(hp, current_price)
    self.mt5.modify_position(hp.ticket, sl=new_sl)
```

**Avantajlar:**
- MT5 broker tarafında SL/TP yönetimi (gap koruması)
- 10sn polling beklemez

**Dezavantajlar:**
- GCM VİOP build < 5200'de çalışmayabilir
- Modify başarısız → devir iptal

### 2. Software Mode (native_sltp = false)

SL/TP bellekte tutulur, H-Oğul fiyat kontrollü kapatır:

```python
else:
    # Devir anında: Güvenlik ağı SL MT5'e yaz
    try:
        self.mt5.modify_position(ticket, sl=suggested_sl)
    except:
        logger.warning("Güvenlik ağı SL atanamadı")

    # 10sn'de: Software kontrolü
    if not self._native_sltp:
        if self._check_software_sltp(hp, current_price, profit, swap):
            continue  # Kapatıldı
```

**Avantajlar:**
- Modify başarısız olsa bile devir yapılır
- Build < 5200 uyumlu

**Dezavantajlar:**
- 10sn polling — gap riski
- İkinci SL (güvenlik ağı) var

---

## Software SL/TP Kontrolü

### _check_software_sltp — Yazılımsal Kapatma

```python
def _check_software_sltp(self, hp: HybridPosition, current_price: float,
                         profit: float, swap: float) -> bool:
    """
    Native SLTP kapalı olduğunda:
    Her 10sn'de fiyat kontrolü, ihlal varsa DEAL ile kapat.
    """

    sl_hit = False
    tp_hit = False

    # SL/TP ihlal kontrolü
    if hp.direction == "BUY":
        if hp.current_sl > 0 and current_price <= hp.current_sl:
            sl_hit = True
        if hp.current_tp > 0 and current_price >= hp.current_tp:
            tp_hit = True
    else:
        if hp.current_sl > 0 and current_price >= hp.current_sl:
            sl_hit = True
        if hp.current_tp > 0 and current_price <= hp.current_tp:
            tp_hit = True

    if not sl_hit and not tp_hit:
        return False

    # Hit! Kapatmayı dene
    reason = "SOFTWARE_SL" if sl_hit else "SOFTWARE_TP"
    retry_count = self._close_retry_counts.get(hp.ticket, 0)

    # Retry limiti: 3 başarısız deneme
    if retry_count >= self._MAX_CLOSE_RETRIES:
        if retry_count == self._MAX_CLOSE_RETRIES:
            logger.critical(
                f"Software {reason} kapatma 3x başarısız: "
                f"MANUEL KAPATMA GEREKLİ!"
            )
            # Event bus bildirimi
            from engine.event_bus import emit as _emit
            _emit("close_failed", {
                "ticket": hp.ticket,
                "symbol": hp.symbol,
                "reason": reason,
                "message": f"Pozisyon 3x kapatılamadı — manuel müdahale gerekli",
            })
            self._close_retry_counts[hp.ticket] = retry_count + 1
        return False

    logger.info(
        f"Software {reason}: {hp.symbol} fiyat={current_price:.4f} "
        f"seviye={hp.current_sl if sl_hit else hp.current_tp:.4f} "
        f"— kapatılıyor (deneme {retry_count+1}/3)"
    )

    # Netting koruması: exact volume ile kapat
    close_result = self.mt5.close_position(
        hp.ticket, expected_volume=hp.volume
    )

    if close_result is None:
        self._close_retry_counts[hp.ticket] = retry_count + 1
        logger.error(f"Software {reason} başarısız (deneme {retry_count+1}/3)")
        return False

    # Başarılı
    self._close_retry_counts.pop(hp.ticket, None)
    total_pnl = profit + swap
    self._finalize_close(hp, reason, total_pnl, swap)

    logger.info(f"Software {reason} başarılı: {hp.symbol} PnL={total_pnl:.2f}")
    return True
```

---

## Netting Senkronizasyonu

### MT5 Dışarıdan Lot Değişikliğini Otomatik Benimse

VİOP'ta bir pozisyon dışarıdan lot eklenebilir/çıkarılabilir:

```python
def _sync_netting_volume(self, hp: HybridPosition,
                         mt5_volume: float, mt5_entry: float) -> None:
    """
    MT5'te volume veya entry_price değişmişse güncellemeleri otomatik benimse.

    LOT EKLEME (volume > old_volume):
        - SL/TP yeni giriş fiyatından PRİMNET ile yeniden hesapla
        - breakeven_hit = True (trailing devam eder)

    LOT ÇIKARMA (volume < old_volume):
        - SL/TP koru
        - volume ve entry_price'ı güncelle (MT5'ten)
    """

    old_volume = hp.volume
    old_entry = hp.entry_price
    old_sl = hp.current_sl
    old_tp = hp.current_tp

    hp.volume = mt5_volume
    hp.entry_price = mt5_entry

    if mt5_volume > old_volume:
        # Lot ekleme — SL/TP yeni giriş fiyatından PRİMNET ile hesapla
        ref_price = self._get_reference_price(hp.symbol)
        if ref_price and ref_price > 0:
            entry_prim = self._price_to_prim(mt5_entry, ref_price)
            if hp.direction == "BUY":
                stop_prim = entry_prim - self._primnet_trailing
                target_prim = self._primnet_target
            else:
                stop_prim = entry_prim + self._primnet_trailing
                target_prim = -self._primnet_target

            hp.current_sl = self._prim_to_price(stop_prim, ref_price)
            hp.current_tp = self._prim_to_price(target_prim, ref_price)
        else:
            # Fallback: ATR
            if hp.direction == "BUY":
                hp.current_sl = mt5_entry - (self._sl_atr_mult * hp.entry_atr)
                hp.current_tp = mt5_entry + (self._tp_atr_mult * hp.entry_atr)
            else:
                hp.current_sl = mt5_entry + (self._sl_atr_mult * hp.entry_atr)
                hp.current_tp = mt5_entry - (self._tp_atr_mult * hp.entry_atr)

        hp.breakeven_hit = True  # Trailing hemen başlar

        logger.info(
            f"Netting SYNC (lot ekleme): {hp.symbol} "
            f"lot {old_volume}→{mt5_volume}, entry {old_entry:.4f}→{mt5_entry:.4f}, "
            f"SL {old_sl:.4f}→{hp.current_sl:.4f}"
        )
    else:
        # Lot çıkarma — SL/TP koru, sadece volume/entry güncelle
        logger.info(
            f"Netting SYNC (lot çıkarma): {hp.symbol} "
            f"lot {old_volume}→{mt5_volume}, entry {old_entry:.4f}→{mt5_entry:.4f} "
            f"(SL/TP korundu)"
        )

    # DB güncelle
    self.db.update_hybrid_position(hp.ticket, {
        "volume": hp.volume,
        "entry_price": hp.entry_price,
        "current_sl": hp.current_sl,
        "current_tp": hp.current_tp,
        "breakeven_hit": int(hp.breakeven_hit),
    })

    # Event log
    event_type = "NETTING_SYNC_ADD" if mt5_volume > old_volume else "NETTING_SYNC_REDUCE"
    self.db.insert_hybrid_event(
        ticket=hp.ticket, symbol=hp.symbol, event=event_type,
        details={
            "old_volume": old_volume, "new_volume": mt5_volume,
            "old_entry": old_entry, "new_entry": mt5_entry,
            "old_sl": old_sl, "new_sl": hp.current_sl,
            "old_tp": old_tp, "new_tp": hp.current_tp,
        }
    )
```

---

## Günlük PRİMNET Yenileme

### Overnight Pozisyonların Referans Fiyatını Güncelle

Piyasa açıldığında (09:40+), **overnight kalan pozisyonlar** için:
- Yeni gün referans fiyatını al
- SL/TP'yi yeni referans'tan yeniden hesapla
- SL monotonluğu: yeni SL eski SL'den daha kötüyse, eski SL'yi koru

```python
def _primnet_daily_reset(self, previous_date: str) -> None:
    """Piyasa açılışında overnight pozisyonların PRİMNET'i yenile."""

    logger.info(
        f"PRİMNET günlük yenileme başlatıldı: "
        f"{len(self.hybrid_positions)} overnight pozisyon"
    )

    for ticket in list(self.hybrid_positions.keys()):
        hp = self.hybrid_positions.get(ticket)
        if hp is None or hp.state != "ACTIVE":
            continue

        old_ref = hp.reference_price
        old_sl = hp.current_sl
        old_tp = hp.current_tp

        # Yeni referans fiyat al
        new_ref = self._get_reference_price(hp.symbol)
        if new_ref is None or new_ref <= 0:
            logger.warning(
                f"PRİMNET yenileme: {hp.symbol} t={ticket} "
                f"referans fiyat alınamadı — eski SL/TP korunuyor"
            )
            continue

        # Yeni primler hesapla
        entry_prim = self._price_to_prim(hp.entry_price, new_ref)
        trailing_dist = self._primnet_trailing

        if hp.direction == "BUY":
            stop_prim = entry_prim - trailing_dist
            target_prim = self._primnet_target
        else:
            stop_prim = entry_prim + trailing_dist
            target_prim = -self._primnet_target

        new_sl = self._prim_to_price(stop_prim, new_ref)
        new_tp = self._prim_to_price(target_prim, new_ref)

        # SL monotonluk: yeni SL eski SL'den daha kötüyse, eski'yi koru
        sl_worse = False
        if hp.direction == "BUY" and new_sl < old_sl:
            sl_worse = True
        elif hp.direction == "SELL" and new_sl > old_sl:
            sl_worse = True

        if sl_worse:
            new_sl = old_sl
            logger.info(
                f"PRİMNET yenileme [{hp.symbol}] t={ticket}: "
                f"yeni SL daha kötü — eski SL korundu"
            )

        # Güncelle
        hp.reference_price = new_ref
        hp.current_sl = new_sl
        hp.current_tp = new_tp
        hp.breakeven_hit = True

        # MT5'e yaz (native mod)
        if self._native_sltp:
            modify_result = self.mt5.modify_position(ticket, sl=new_sl, tp=new_tp)
            if modify_result is None:
                logger.error(f"PRİMNET yenileme MT5 modify başarısız")

        # DB güncelle
        self.db.update_hybrid_position(ticket, {
            "current_sl": new_sl,
            "current_tp": new_tp,
            "breakeven_hit": 1,
        })

        # Event log
        self.db.insert_hybrid_event(
            ticket=ticket, symbol=hp.symbol, event="PRIMNET_DAILY_RESET",
            details={
                "old_ref": old_ref, "new_ref": new_ref,
                "old_sl": old_sl, "new_sl": new_sl,
                "old_tp": old_tp, "new_tp": new_tp,
                "entry_prim": round(entry_prim, 2),
                "trailing_dist": trailing_dist,
            }
        )

        logger.info(
            f"PRİMNET yenileme: {hp.symbol} {hp.direction} "
            f"ref {old_ref:.4f}→{new_ref:.4f}, "
            f"SL {old_sl:.4f}→{new_sl:.4f}"
        )

    logger.info("PRİMNET günlük yenileme tamamlandı")
```

**Tetikleyici:**
```python
def _refresh_daily_pnl(self) -> None:
    # ...

    # PRİMNET yenileme — piyasa açılışında (09:40+)
    now = datetime.now()
    if (self._daily_reset_done != today
            and self.hybrid_positions
            and self._is_trading_hours(now)):  # 09:40 - 17:50
        self._daily_reset_done = today
        self._primnet_daily_reset(yesterday)
```

---

## API Endpoint'leri

### 1. POST /hybrid/check — Devir Ön Kontrolü

**İstek:**
```json
{
  "ticket": 123456
}
```

**Yanıt (Başarılı):**
```json
{
  "can_transfer": true,
  "reason": "Hibrite devir uygun",
  "symbol": "AKBNK-H26",
  "direction": "BUY",
  "volume": 1.0,
  "entry_price": 28150.0,
  "current_price": 28200.0,
  "atr_value": 245.5,
  "suggested_sl": 27904.5,
  "suggested_tp": 29195.0,
  "hybrid_daily_pnl": -150.0,
  "hybrid_daily_limit": 500.0,
  "active_hybrid_count": 1,
  "max_hybrid_count": 3
}
```

**Yanıt (Başarısız):**
```json
{
  "can_transfer": false,
  "reason": "Kill-switch L3 aktif — tüm işlemler durduruldu"
}
```

### 2. POST /hybrid/transfer — Hibrite Devret

**İstek:**
```json
{
  "ticket": 123456
}
```

**Yanıt (Başarılı):**
```json
{
  "success": true,
  "message": "Pozisyon hibrit yönetime devredildi",
  "ticket": 123456,
  "symbol": "AKBNK-H26",
  "sl": 27904.5,
  "tp": 29195.0,
  "entry_atr": 245.5
}
```

### 3. POST /hybrid/remove — Hibritten Çıkar

**İstek:**
```json
{
  "ticket": 123456
}
```

**Yanıt:**
```json
{
  "success": true,
  "message": "AKBNK-H26 hibrit yönetiminden çıkarıldı"
}
```

### 4. GET /hybrid/status — Aktif Hibrit Pozisyonlar

**Yanıt:**
```json
{
  "active_count": 1,
  "max_count": 3,
  "daily_pnl": 450.0,
  "daily_limit": 500.0,
  "native_sltp": false,
  "positions": [
    {
      "ticket": 123456,
      "symbol": "AKBNK-H26",
      "direction": "BUY",
      "volume": 1.0,
      "entry_price": 28150.0,
      "current_price": 28420.0,
      "entry_atr": 245.5,
      "initial_sl": 27904.5,
      "initial_tp": 29195.0,
      "current_sl": 28140.0,
      "current_tp": 29195.0,
      "pnl": 270.0,
      "swap": 0.0,
      "breakeven_hit": true,
      "trailing_active": true,
      "transferred_at": "2026-04-06T14:30:00",
      "state": "ACTIVE",
      "reference_price": 28000.0
    }
  ],
  "primnet": {
    "trailing_prim": 1.5,
    "target_prim": 9.5
  }
}
```

### 5. GET /hybrid/events — Hibrit Olay Geçmişi

**Yanıt:**
```json
{
  "count": 3,
  "events": [
    {
      "id": 1,
      "timestamp": "2026-04-06T14:30:00",
      "ticket": 123456,
      "symbol": "AKBNK-H26",
      "event": "TRANSFER",
      "details": "{\"direction\": \"BUY\", \"entry_price\": 28150.0, ...}"
    },
    {
      "id": 2,
      "timestamp": "2026-04-06T14:35:00",
      "ticket": 123456,
      "symbol": "AKBNK-H26",
      "event": "TRAILING_UPDATE",
      "details": "{\"old_sl\": 27904.5, \"new_sl\": 28140.0, ...}"
    },
    {
      "id": 3,
      "timestamp": "2026-04-06T14:45:00",
      "ticket": 123456,
      "symbol": "AKBNK-H26",
      "event": "PRIMNET_TARGET",
      "details": "{\"prim\": 9.5, \"pnl\": 450.0}"
    }
  ]
}
```

### 6. GET /hybrid/performance — Hibrit Performans

Hibrit işlemlerinin istatistiksel performansı (win rate, avg pnl, vb.)

---

## Config Parametreleri

### config/default.json — Hybrid Bölümü

```json
{
  "hybrid": {
    "enabled": true,
    "native_sltp": false,
    "max_concurrent": 3,
    "daily_loss_limit": 500.0,
    "sl_atr_mult": 2.0,
    "tp_atr_mult": 2.0,
    "primnet": {
      "trailing_prim": 1.5,
      "target_prim": 9.5
    }
  }
}
```

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `enabled` | true | Hibrit motor aktif mi? |
| `native_sltp` | false | MT5 native SL/TP kullan mı? |
| `max_concurrent` | 3 | Max eşzamanlı hibrit pozisyon |
| `daily_loss_limit` | 500.0 | Günlük zarar limiti (TRY) |
| `sl_atr_mult` | 2.0 | SL = entry ± ATR×2 (fallback) |
| `tp_atr_mult` | 2.0 | TP = entry ± ATR×2 (fallback) |
| **primnet.trailing_prim** | 1.5 | Trailing mesafe (prim) |
| **primnet.target_prim** | 9.5 | Hedef (prim) |

### Kritik Sabitler (Kod İçi)

```python
ATR_PERIOD: int = 14          # ATR hesaplama periyodu
MIN_BARS: int = 30            # ATR hesaplamak için min bar
TRADING_OPEN: dtime = dtime(9, 40)     # İşlem açılış
TRADING_CLOSE: dtime = dtime(17, 50)   # İşlem kapanış
EOD_NOTIFY: dtime = dtime(17, 45)      # EOD bildirimi
MAX_CLOSE_RETRIES: int = 3    # Kapatma deneme limiti
```

---

## Dosya Haritası

```
/sessions/clever-intelligent-turing/mnt/USTAT/
├── engine/
│   ├── h_engine.py            ← PRİMNET ANA MOTOR (1667 satır)
│   │   ├── HybridPosition
│   │   ├── HEngine sınıfı
│   │   │   ├── check_transfer() — H-Baba
│   │   │   ├── transfer_to_hybrid() — Atomik devir
│   │   │   ├── remove_from_hybrid() — Hibritten çıkar
│   │   │   ├── run_cycle() — Ana döngü (H-Oğul)
│   │   │   ├── _check_software_sltp()
│   │   │   ├── _sync_netting_volume()
│   │   │   ├── _check_breakeven()
│   │   │   ├── _check_trailing()
│   │   │   ├── _check_primnet_target()
│   │   │   ├── _get_reference_price()
│   │   │   ├── _price_to_prim()
│   │   │   ├── _prim_to_price()
│   │   │   ├── _calc_primnet_trailing_sl()
│   │   │   ├── _primnet_daily_reset()
│   │   │   └── force_close_all()
│   ├── main.py                ← h_engine.run_cycle() çağrısı
│   └── baba.py                ← kill_switch_level kontrolü
│
├── api/
│   ├── routes/
│   │   └── hybrid_trade.py    ← 5 endpoint
│   │       ├── POST /hybrid/check
│   │       ├── POST /hybrid/transfer
│   │       ├── POST /hybrid/remove
│   │       ├── GET /hybrid/status
│   │       └── GET /hybrid/events
│   └── schemas.py             ← HybridPosition*, PrimnetConfig
│
├── config/
│   └── default.json           ← hybrid.primnet parametreleri
│
├── database/
│   ├── trades.db              ← hybrid_positions tabelı
│   └── ustat.db               ← hybrid_events tabelı
│
├── docs/
│   └── PRIMNET_KOD_DOKUMU.md  ← BU DOSYA (v1.0)
│
└── desktop/
    └── src/
        ├── components/
        │   ├── HybridTrade.jsx      ← Devir/çıkma UI
        │   └── PrimnetDetail.jsx    ← Prim görselleştirmesi
        └── services/
            └── api.js              ← API istemcisi
```

---

## Özet Tablo

| Öğe | Değer/Detay |
|-----|-------------|
| **Sistem Adı** | PRİMNET (Prim Bazlı Net Emir Takip) |
| **Amaç** | Hibrit pozisyon yönetimi |
| **Ana Motor** | engine/h_engine.py |
| **Bileşenler** | H-Baba (kontrol) + H-Oğul (yönetim) |
| **Döngü Aralığı** | Her 10 saniye |
| **Referans Fiyat** | (Tavan + Taban) / 2 (VİOP uzlaşma) |
| **Prim Tanımı** | (Fiyat - Referans) / (Referans × 0.01) |
| **Trailing Mesafesi** | Sabit 1.5 prim (ayarlanabilir) |
| **Hedef** | ±9.5 prim (tavan/tabana 0.5 kala) |
| **Max Eşzamanlı** | 3 hibrit pozisyon (ayarlanabilir) |
| **Günlük Zarar Limiti** | 500 TRY (ayarlanabilir) |
| **SL/TP Modları** | Native (MT5) veya Software (bellekte) |
| **Netting Koruması** | Atomik kilidi (acquire/release) |
| **API Endpoint'ler** | 5 ana endpoint (check, transfer, remove, status, events) |
| **Veritabanı** | SQLite (hybrid_positions, hybrid_events) |
| **Versiyon** | ÜSTAT v5.9.0 |

---

**Hazırlanma Tarihi:** 6 Nisan 2026
**Versiyon:** 1.0
**Dil:** Türkçe
**Kaynak:** engine/h_engine.py + api/routes/hybrid_trade.py + docs/PRIMNET_KOD_DOKUMU.md
