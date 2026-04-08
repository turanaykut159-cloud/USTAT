# PRİMNET İşlem Yönetimi — Tam Kod Dökümü

**Tarih:** 6 Nisan 2026
**Kapsam:** V5.9 (aktif) + V6.0 (geliştirme aşamasında)
**Hazırlayan:** Claude — ÜSTAT Projesi

---

## İÇİNDEKİLER

1. [Genel Bakış](#1-genel-bakış)
2. [V5.9 — engine/h_engine.py](#2-v59--engineh_enginepy)
3. [V5.9 — api/routes/hybrid_trade.py](#3-v59--apirouteshybrid_tradepy)
4. [V5.9 — api/schemas.py (PrimNet Bölümleri)](#4-v59--apischemaspy)
5. [V5.9 — config/default.json (Hybrid Bölümü)](#5-v59--configdefaultjson)
6. [V5.9 — desktop/src/services/api.js (Hybrid Fonksiyonları)](#6-v59--api-servisi)
7. [V5.9 — desktop/src/components/HybridTrade.jsx](#7-v59--hybridtradejsx)
8. [V5.9 — desktop/src/components/PrimnetDetail.jsx](#8-v59--primnetdetailjsx)
9. [V5.9 — Dashboard.jsx (PrimNet Referansları)](#9-v59--dashboardjsx-primnet)
10. [V5.9 — tests/test_hybrid_100.py](#10-v59--testler)
11. [V6.0 — h_engine Modülü](#11-v60--h_engine-modülü)
12. [V6.0 — ui/pages/hybrid_page.py](#12-v60--hybrid_pagepy)
13. [V6.0 — engine/position_keeper.py](#13-v60--position_keeperpy)
14. [Dosya Haritası](#14-dosya-haritası)

---

## 1. Genel Bakış

### PRİMNET Nedir?

**PRİMNET** (Prim Bazlı Net Emir Takip), ÜSTAT'ın hibrit pozisyon yönetim sistemidir. İnsan işlemi açar, robot PRİMNET ile yönetir ve kapatır.

### Temel Kavramlar

| Kavram | Açıklama |
|--------|----------|
| **Referans Fiyat** | (tavan + taban) / 2 — VİOP uzlaşma fiyatı |
| **Prim** | (fiyat - referans) / (referans × 0.01) |
| **Trailing** | Sabit 1.5 prim mesafeli takip eden stop |
| **Hedef** | ±9.5 prim — tavan/tabana 0.5 prim kala kapanış |
| **H-Baba** | Devir ön kontrolü (risk/yetkilendirme) |
| **H-Oğul** | PRİMNET pozisyon yönetimi |

### Mimari (V5.9)

```
Dashboard/HybridTrade.jsx → API (hybrid_trade.py) → H-Engine (h_engine.py) → MT5
                                                         ↓
                                                    Database (trades.db)
```

### Mimari (V6.0 — Hedef)

```
HybridPage (PySide6) → PositionManager → MT5Gateway
                            ↓
                       RiskFilter + SLTPManager + SignalFusion
                            ↓
                       PositionStore (SQLite/DuckDB)
```

---

## 2. V5.9 — engine/h_engine.py

**Dosya:** `engine/h_engine.py`
**Satır Sayısı:** ~1667
**Sınıflandırma:** Sarı Bölge (Dikkatle değiştirilebilir)
**Görev:** Hibrit İşlem Motoru — H-Baba (risk) + H-Oğul (yönetim)

### 2.1 Sabitler

```python
ATR_PERIOD: int = 14          # ATR hesaplama periyodu
MIN_BARS: int = 30            # ATR hesaplamak için min bar sayısı
TRADING_OPEN: dtime = dtime(9, 40)
TRADING_CLOSE: dtime = dtime(17, 50)
EOD_NOTIFY: dtime = dtime(17, 45)  # Hibrit EOD bildirim saati
```

### 2.2 HybridPosition Dataclass

```python
@dataclass
class HybridPosition:
    ticket: int
    symbol: str
    direction: str              # "BUY" | "SELL"
    volume: float
    entry_price: float
    entry_atr: float            # devir anındaki ATR (SABİT)
    initial_sl: float
    initial_tp: float
    current_sl: float
    current_tp: float
    state: str = "ACTIVE"       # ACTIVE | CLOSED
    breakeven_hit: bool = False
    trailing_active: bool = False
    transferred_at: str = ""
    db_id: int = 0
    reference_price: float = 0.0  # PRİMNET: Uzlaşma fiyatı (devir günü)
```

### 2.3 HEngine Sınıfı — __init__

```python
class HEngine:
    def __init__(self, config, mt5, db, baba, pipeline):
        self.config = config
        self.mt5 = mt5
        self.db = db
        self.baba = baba
        self.pipeline = pipeline
        self.manuel_motor = None  # Cross-motor referansı

        # Pozisyon deposu (bellek)
        self.hybrid_positions: dict[int, HybridPosition] = {}

        # Günlük PnL takibi
        self._daily_hybrid_pnl: float = 0.0
        self._daily_pnl_date: str = date.today().isoformat()

        # Software SL/TP kapatma retry sayaçları
        self._close_retry_counts: dict[int, int] = {}
        self._MAX_CLOSE_RETRIES: int = 3

        # EOD bildirim bayrağı (günde 1 kez)
        self._eod_notified_date: str = ""

        # Günlük PRİMNET yenileme bayrağı
        self._daily_reset_done: str = ""

        # Config parametreleri
        hybrid_cfg = config.get("hybrid", {})
        self._enabled: bool = hybrid_cfg.get("enabled", True)
        self._max_concurrent: int = hybrid_cfg.get("max_concurrent", 3)
        self._config_daily_limit: float = hybrid_cfg.get("daily_loss_limit", 500.0)
        self._sl_atr_mult: float = hybrid_cfg.get("sl_atr_mult", 2.0)
        self._tp_atr_mult: float = hybrid_cfg.get("tp_atr_mult", 2.0)
        self._native_sltp: bool = hybrid_cfg.get("native_sltp", False)

        # PRİMNET parametreleri
        primnet_cfg = hybrid_cfg.get("primnet", {})
        self._primnet_trailing: float = primnet_cfg.get("trailing_prim", 1.5)
        self._primnet_target: float = primnet_cfg.get("target_prim", 9.5)
```

### 2.4 get_hybrid_symbols — OĞUL Netting Koruması

```python
def get_hybrid_symbols(self) -> set[str]:
    """OĞUL bu listeye bakarak netting çakışmasını önler."""
    return {hp.symbol for hp in self.hybrid_positions.values() if hp.state == "ACTIVE"}
```

### 2.5 check_transfer — H-Baba Devir Ön Kontrolü (10 Adım)

```python
def check_transfer(self, ticket: int) -> dict[str, Any]:
    """9+1 adımlı kontrol sırası (H-Baba):
        1. H-Engine aktif mi?
        2. Kill-switch seviyesi < 3?
        3. İşlem saatleri içinde mi?
        4. Ticket MT5'te açık pozisyon mu?
        5. Sembol zaten hibrit yönetiminde mi? (netting lock)
        6. Ticket zaten hibrit yönetiminde mi? (bellek + DB)
        7. Eşzamanlı hibrit limit aşılıyor mu?
        8. Günlük hibrit zarar limiti aşılmış mı?
        9. ATR verisi mevcut mu?
        10. Güncel fiyat SL'yi zaten ihlal ediyor mu?
    """
    result = {
        "can_transfer": False, "reason": "", "symbol": "", "direction": "",
        "volume": 0.0, "entry_price": 0.0, "current_price": 0.0,
        "atr_value": 0.0, "suggested_sl": 0.0, "suggested_tp": 0.0,
        "hybrid_daily_pnl": self._daily_hybrid_pnl,
        "hybrid_daily_limit": self._config_daily_limit,
        "active_hybrid_count": len(self.hybrid_positions),
        "max_hybrid_count": self._max_concurrent,
    }

    # 1. H-Engine aktif mi?
    if not self._enabled:
        result["reason"] = "Hibrit motor devre dışı"
        return result

    # 2. Kill-switch seviyesi
    if self.baba and self.baba.kill_switch_level >= 3:
        result["reason"] = "Kill-switch L3 aktif — tüm işlemler durduruldu"
        return result

    # 3. İşlem saatleri
    now = datetime.now()
    if not self._is_trading_hours(now):
        result["reason"] = "İşlem saatleri dışında (09:40-17:50)"
        return result

    # 4. MT5'te pozisyon kontrolü
    positions = self.mt5.get_positions()
    if not positions:
        result["reason"] = "MT5'te açık pozisyon bulunamadı"
        return result
    mt5_pos = next((p for p in positions if p.get("ticket") == ticket), None)
    if mt5_pos is None:
        result["reason"] = f"Ticket {ticket} MT5'te bulunamadı"
        return result

    symbol = mt5_pos.get("symbol", "")
    direction = "BUY" if mt5_pos.get("type", -1) in (0, "BUY") else "SELL"
    volume = mt5_pos.get("volume", 0.0)
    entry_price = mt5_pos.get("price_open", 0.0)
    current_price = mt5_pos.get("price_current", 0.0)

    # v5.4.1: Atomik netting kilidi al
    from engine.netting_lock import acquire_symbol, release_symbol
    if not acquire_symbol(symbol, owner="h_engine"):
        result["reason"] = f"{symbol} başka motor tarafından kilitli (netting lock)"
        return result

    # 5. Sembol zaten hibrit yönetiminde mi?
    if symbol in self.get_hybrid_symbols():
        release_symbol(symbol, owner="h_engine")
        result["reason"] = f"{symbol} zaten hibrit yönetiminde (netting)"
        return result

    # 6. Ticket zaten hibrit yönetiminde mi? (bellek + DB)
    if ticket in self.hybrid_positions:
        release_symbol(symbol, owner="h_engine")
        result["reason"] = f"Ticket {ticket} zaten hibrit yönetiminde"
        return result

    # 7. Eşzamanlı limit
    active_count = len(self.hybrid_positions)
    if active_count >= self._max_concurrent:
        release_symbol(symbol, owner="h_engine")
        result["reason"] = f"Eşzamanlı hibrit limit aşıldı ({active_count}/{self._max_concurrent})"
        return result

    # 8. Günlük zarar limiti
    self._refresh_daily_pnl()
    if self._daily_hybrid_pnl <= -abs(self._config_daily_limit):
        release_symbol(symbol, owner="h_engine")
        result["reason"] = f"Günlük hibrit zarar limiti aşıldı"
        return result

    # 9. ATR verisi
    atr_value = self._get_atr(symbol)
    if atr_value is None or atr_value <= 0:
        release_symbol(symbol, owner="h_engine")
        result["reason"] = f"{symbol} için ATR verisi bulunamadı"
        return result

    # SL/TP önerileri (ATR fallback)
    if direction == "BUY":
        result["suggested_sl"] = entry_price - (atr_value * self._sl_atr_mult)
        result["suggested_tp"] = entry_price + (atr_value * self._tp_atr_mult)
    else:
        result["suggested_sl"] = entry_price + (atr_value * self._sl_atr_mult)
        result["suggested_tp"] = entry_price - (atr_value * self._tp_atr_mult)

    # 10. Güncel fiyat SL'yi zaten ihlal ediyor mu?
    suggested_sl = result["suggested_sl"]
    if direction == "BUY" and current_price <= suggested_sl:
        release_symbol(symbol, owner="h_engine")
        result["reason"] = "Güncel fiyat zaten SL seviyesinin altında"
        return result
    if direction == "SELL" and current_price >= suggested_sl:
        result["reason"] = "Güncel fiyat zaten SL seviyesinin üstünde"
        return result

    result["can_transfer"] = True
    result["reason"] = "Hibrite devir uygun"
    return result
```

### 2.6 transfer_to_hybrid — Atomik Devir

```python
def transfer_to_hybrid(self, ticket: int) -> dict[str, Any]:
    """Atomik devir sırası:
        1. check_transfer() ile ön kontrol
        2. PRİMNET: Prim bazlı SL/TP hesapla (referans fiyat varsa)
        3. MT5 modify_position — SL/TP ata (native veya software)
        4. DB insert + belleğe ekle
        5. ManuelMotor aktif işlemlerden çıkar
        6. Event log
    """
    result = {"success": False, "message": "", "ticket": ticket,
              "symbol": "", "sl": 0.0, "tp": 0.0, "entry_atr": 0.0}

    check = self.check_transfer(ticket)
    if not check["can_transfer"]:
        result["message"] = check["reason"]
        return result

    symbol = check["symbol"]
    direction = check["direction"]
    volume = check["volume"]
    entry_price = check["entry_price"]
    atr_value = check["atr_value"]
    suggested_sl = check["suggested_sl"]
    suggested_tp = check["suggested_tp"]

    # PRİMNET: Prim bazlı SL/TP hesapla
    ref_price = self._get_reference_price(symbol) or 0.0
    if ref_price > 0:
        entry_prim = self._price_to_prim(entry_price, ref_price)
        if direction == "BUY":
            stop_prim = entry_prim - self._primnet_trailing
            target_prim = self._primnet_target
        else:
            stop_prim = entry_prim + self._primnet_trailing
            target_prim = -self._primnet_target
        suggested_sl = self._prim_to_price(stop_prim, ref_price)
        suggested_tp = self._prim_to_price(target_prim, ref_price)
    else:
        logger.warning(f"PRİMNET: Referans fiyat alınamadı — ATR SL/TP kullanılıyor")

    # SL/TP ataması (native veya software mod)
    if self._native_sltp:
        modify_result = self.mt5.modify_position(ticket, sl=suggested_sl, tp=suggested_tp)
        if modify_result is None:
            result["message"] = "MT5 SL/TP ataması başarısız — devir iptal"
            return result
    else:
        # Software mod + güvenlik ağı SL
        safety_sl = suggested_sl
        try:
            self.mt5.modify_position(ticket, sl=safety_sl)
        except Exception as exc:
            logger.warning(f"Güvenlik ağı SL atanamadı: {exc}")

    # DB'ye kaydet
    db_id = self.db.insert_hybrid_position({...})

    # trades tablosundaki strategy'yi güncelle
    self.db._execute("UPDATE trades SET strategy='hibrit' WHERE mt5_position_id=?", (ticket,))

    # Belleğe ekle
    hp = HybridPosition(
        ticket=ticket, symbol=symbol, direction=direction, volume=volume,
        entry_price=entry_price, entry_atr=atr_value,
        initial_sl=suggested_sl, initial_tp=suggested_tp,
        current_sl=suggested_sl, current_tp=suggested_tp,
        state="ACTIVE", transferred_at=datetime.now().isoformat(timespec="seconds"),
        db_id=db_id, reference_price=ref_price,
    )
    hp.breakeven_hit = True  # PRİMNET: trailing hemen başlar
    self.hybrid_positions[ticket] = hp

    # ManuelMotor aktif işlemlerden çıkar
    if self.manuel_motor and hasattr(self.manuel_motor, 'active_trades'):
        self.manuel_motor.active_trades.pop(symbol, None)

    # Event log
    self.db.insert_hybrid_event(ticket=ticket, symbol=symbol, event="TRANSFER", details={...})

    result["success"] = True
    result["sl"] = suggested_sl
    result["tp"] = suggested_tp
    return result
```

### 2.7 remove_from_hybrid — Hibritten Çıkar

```python
def remove_from_hybrid(self, ticket: int) -> dict[str, Any]:
    """SL/TP kalır, yönetim durur."""
    if ticket not in self.hybrid_positions:
        return {"success": False, "message": f"Ticket {ticket} hibrit yönetiminde değil"}

    hp = self.hybrid_positions[ticket]
    symbol = hp.symbol

    self.db.close_hybrid_position(ticket=ticket, reason="MANUAL_REMOVE", pnl=0.0, swap=0.0)
    self.db.insert_hybrid_event(ticket=ticket, symbol=symbol, event="REMOVE",
                                 details={"reason": "Kullanıcı tarafından çıkarıldı"})
    del self.hybrid_positions[ticket]

    from engine.netting_lock import release_symbol
    release_symbol(symbol, owner="h_engine")

    return {"success": True, "message": f"{symbol} hibrit yönetiminden çıkarıldı"}
```

### 2.8 run_cycle — Ana Döngü (Her 10sn)

```python
def run_cycle(self) -> None:
    """Sıralama:
        1. OLAY rejimi → tüm hibrit pozisyonları anında kapat
        2. 17:45 sonrası açık pozisyon bildirimi (günde 1 kez)
        3. Gün değişimi kontrolü
        4. Her pozisyon için: sync → software SL/TP → hedef → breakeven → trailing
    """
    if not self._enabled or not self.hybrid_positions:
        return

    # OLAY rejimi kontrolü
    if (self.baba and hasattr(self.baba, "current_regime")
            and self.baba.current_regime.regime_type == RegimeType.OLAY):
        self.force_close_all("OLAY_REGIME")
        return

    # 17:45 sonrası EOD bildirimi (günde 1 kez)
    now = datetime.now()
    today_str = now.date().isoformat()
    if now.time() >= EOD_NOTIFY and self._eod_notified_date != today_str:
        self._eod_notified_date = today_str
        # ... bildirim gönder ...

    self._refresh_daily_pnl()

    mt5_positions = self.mt5.get_positions()
    mt5_by_ticket = {p.get("ticket"): p for p in (mt5_positions or [])}

    for ticket in list(self.hybrid_positions.keys()):
        hp = self.hybrid_positions.get(ticket)
        if hp is None or hp.state != "ACTIVE":
            continue

        mt5_pos = mt5_by_ticket.get(ticket)

        # Sync: Pozisyon MT5'te kapanmış mı? (3 ardışık miss doğrulama)
        if mt5_pos is None:
            miss_key = f"miss_{ticket}"
            miss_count = self._close_retry_counts.get(miss_key, 0) + 1
            self._close_retry_counts[miss_key] = miss_count
            if miss_count < 3:
                continue  # Geçici kayıp olabilir
            self._close_retry_counts.pop(miss_key, None)
            self._handle_external_close(hp)
            continue
        else:
            self._close_retry_counts.pop(f"miss_{ticket}", None)

        current_price = mt5_pos.get("price_current", 0.0)
        profit = mt5_pos.get("profit", 0.0)
        swap = mt5_pos.get("swap", 0.0)

        # Netting hacim senkronizasyonu
        mt5_volume = mt5_pos.get("volume", hp.volume)
        if mt5_volume != hp.volume:
            mt5_entry = mt5_pos.get("price_open", hp.entry_price)
            self._sync_netting_volume(hp, mt5_volume, mt5_entry)

        if current_price <= 0:
            continue

        # Software SL/TP kontrolü (native kapalıysa)
        if not self._native_sltp:
            if self._check_software_sltp(hp, current_price, profit, swap):
                continue

        # PRİMNET hedef kontrolü (tavan/tabana 0.5 kala)
        if self._check_primnet_target(hp, current_price, profit, swap):
            continue

        # Breakeven kontrolü
        self._check_breakeven(hp, current_price, profit, swap)

        # Trailing stop kontrolü
        self._check_trailing(hp, current_price, profit, swap)
```

### 2.9 _check_software_sltp — Yazılımsal SL/TP

```python
def _check_software_sltp(self, hp, current_price, profit, swap) -> bool:
    """Fiyat SL veya TP'yi aştıysa DEAL ile kapat.
    Native SLTP çalışmadığında her 10sn'de fiyatı kontrol eder.
    Retry limiti: 3x başarısız → CRITICAL log + event bus bildirimi.
    Returns: True ise pozisyon kapatıldı."""
    sl_hit = False
    tp_hit = False

    if hp.direction == "BUY":
        if hp.current_sl > 0 and current_price <= hp.current_sl: sl_hit = True
        if hp.current_tp > 0 and current_price >= hp.current_tp: tp_hit = True
    else:
        if hp.current_sl > 0 and current_price >= hp.current_sl: sl_hit = True
        if hp.current_tp > 0 and current_price <= hp.current_tp: tp_hit = True

    if not sl_hit and not tp_hit:
        return False

    reason = "SOFTWARE_SL" if sl_hit else "SOFTWARE_TP"
    retry_count = self._close_retry_counts.get(hp.ticket, 0)
    if retry_count >= self._MAX_CLOSE_RETRIES:
        if retry_count == self._MAX_CLOSE_RETRIES:
            logger.critical(f"Software {reason} kapatma {self._MAX_CLOSE_RETRIES}x başarısız: MANUEL KAPATMA GEREKLİ!")
            from engine.event_bus import emit as _emit
            _emit("close_failed", {...})
            self._close_retry_counts[hp.ticket] = retry_count + 1
        return False

    close_result = self.mt5.close_position(hp.ticket, expected_volume=hp.volume)
    if close_result is None:
        self._close_retry_counts[hp.ticket] = retry_count + 1
        return False

    self._close_retry_counts.pop(hp.ticket, None)
    total_pnl = profit + swap
    self._finalize_close(hp, reason, total_pnl, swap)
    return True
```

### 2.10 _sync_netting_volume — Netting Hacim Senkronizasyonu

```python
def _sync_netting_volume(self, hp, mt5_volume, mt5_entry) -> None:
    """VİOP netting'de dışarıdan yapılan lot ekleme/çıkarma.
    Lot ekleme: volume, entry, SL/TP PRİMNET ile yeniden hesaplanır
    Lot çıkarma: volume güncellenir, SL/TP korunur"""
    old_volume = hp.volume
    hp.volume = mt5_volume
    hp.entry_price = mt5_entry

    if mt5_volume > old_volume:
        # Lot ekleme — SL/TP yeni giriş fiyatından PRİMNET ile yeniden hesapla
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
            # ATR fallback
            if hp.direction == "BUY":
                hp.current_sl = mt5_entry - (self._sl_atr_mult * hp.entry_atr)
                hp.current_tp = mt5_entry + (self._tp_atr_mult * hp.entry_atr)
            else:
                hp.current_sl = mt5_entry + (self._sl_atr_mult * hp.entry_atr)
                hp.current_tp = mt5_entry - (self._tp_atr_mult * hp.entry_atr)
        hp.breakeven_hit = True

    # DB güncelle
    self.db.update_hybrid_position(hp.ticket, {
        "volume": hp.volume, "entry_price": hp.entry_price,
        "current_sl": hp.current_sl, "current_tp": hp.current_tp,
        "breakeven_hit": int(hp.breakeven_hit),
    })
```

### 2.11 _check_trailing — PRİMNET Trailing Stop

```python
def _check_trailing(self, hp, current_price, profit, swap) -> None:
    """PRİMNET trailing: SL sadece daha iyi yöne taşınır.
    Hem MT5'e native SL yazar hem bellekte günceller (gap koruması)."""
    if not hp.breakeven_hit:
        return

    new_sl = self._calc_primnet_trailing_sl(hp, current_price)
    if new_sl is None:
        return

    # SL sadece daha iyi yöne taşınır
    if hp.direction == "BUY":
        if new_sl <= hp.current_sl: return
    else:
        if new_sl >= hp.current_sl: return

    # MT5'e native SL yaz (software modda da gap koruması için)
    modify_result = self.mt5.modify_position(hp.ticket, sl=new_sl)
    if modify_result is None:
        retry_key = f"tr_modify_{hp.ticket}"
        fail_count = self._close_retry_counts.get(retry_key, 0) + 1
        self._close_retry_counts[retry_key] = fail_count
        if fail_count >= 3 and fail_count == 3:
            logger.critical(f"Trailing SL 3x modify başarısız — sadece software SL ile devam")
    else:
        self._close_retry_counts.pop(f"tr_modify_{hp.ticket}", None)
        # MT5 doğrulama
        verified_sl = self._verify_mt5_sl(hp.ticket)
        if verified_sl is not None and abs(verified_sl - new_sl) > 0.01:
            new_sl = verified_sl  # MT5 değeri kullanılıyor

    old_sl = hp.current_sl
    hp.current_sl = new_sl
    hp.trailing_active = True

    self.db.update_hybrid_position(hp.ticket, {"current_sl": new_sl, "trailing_active": 1})
    self.db.insert_hybrid_event(ticket=hp.ticket, symbol=hp.symbol, event="TRAILING_UPDATE",
                                 details={"old_sl": old_sl, "new_sl": new_sl, ...})
```

### 2.12 PRİMNET Yardımcı Fonksiyonlar

```python
def _get_reference_price(self, symbol: str) -> float | None:
    """VİOP uzlaşma fiyatı: (tavan + taban) / 2
    Doğrulama: spread %15-%25 arası olmalı (VİOP ±%10 limit)"""
    sym = self.mt5.get_symbol_info(symbol)
    if sym is None: return None
    tavan = getattr(sym, "session_price_limit_max", 0.0)
    taban = getattr(sym, "session_price_limit_min", 0.0)
    if tavan <= 0 or taban <= 0: return None
    ref = (tavan + taban) / 2.0
    spread_pct = (tavan - taban) / ref if ref > 0 else 0
    if spread_pct < 0.10 or spread_pct > 0.30:
        logger.warning(f"PRİMNET referans fiyat şüpheli: spread=%{spread_pct*100:.1f}")
    return ref

def _price_to_prim(self, price: float, ref_price: float) -> float:
    """Prim = (fiyat - referans) / (referans × 0.01)"""
    one_prim = ref_price * 0.01
    if one_prim <= 0: return 0.0
    return (price - ref_price) / one_prim

def _prim_to_price(self, prim: float, ref_price: float) -> float:
    """Fiyat = referans + prim × (referans × 0.01)"""
    return ref_price + prim * (ref_price * 0.01)

def _calc_primnet_trailing_sl(self, hp, current_price) -> float | None:
    """Trailing mesafe HER ZAMAN SABİT (1.5 prim)."""
    ref_price = self._get_reference_price(hp.symbol)
    if ref_price is None: return None

    if hp.reference_price != ref_price:
        hp.reference_price = ref_price

    entry_prim = self._price_to_prim(hp.entry_price, ref_price)
    current_prim = self._price_to_prim(current_price, ref_price)
    trailing_dist = self._primnet_trailing

    if hp.direction == "BUY":
        stop_prim = current_prim - trailing_dist
    else:
        stop_prim = current_prim + trailing_dist

    return self._prim_to_price(stop_prim, ref_price)
```

### 2.13 _check_primnet_target — Hedef Kapanış

```python
def _check_primnet_target(self, hp, current_price, profit, swap) -> bool:
    """BUY: güncel_prim ≥ +9.5 → KAPAT
    SELL: güncel_prim ≤ -9.5 → KAPAT"""
    ref_price = self._get_reference_price(hp.symbol)
    if ref_price is None: return False

    current_prim = self._price_to_prim(current_price, ref_price)
    target = self._primnet_target

    hit = False
    if hp.direction == "BUY" and current_prim >= target: hit = True
    elif hp.direction == "SELL" and current_prim <= -target: hit = True

    if not hit: return False

    close_result = self.mt5.close_position(hp.ticket, expected_volume=hp.volume)
    if close_result is None:
        retry_key = f"primnet_target_{hp.ticket}"
        self._close_retry_counts[retry_key] = self._close_retry_counts.get(retry_key, 0) + 1
        return False

    self._finalize_close(hp, "PRIMNET_TARGET", profit + swap, swap)
    return True
```

### 2.14 force_close_all — Zorla Kapat (EOD / Kill-Switch L3)

```python
def force_close_all(self, reason: str) -> list[int]:
    """Tüm aktif hibrit pozisyonları zorla kapat.
    Returns: Kapatılamayan ticket listesi."""
    failed_tickets = []
    for ticket in list(self.hybrid_positions.keys()):
        hp = self.hybrid_positions.get(ticket)
        if hp is None or hp.state != "ACTIVE": continue

        # MT5'ten güncel PnL al
        pnl, swap = 0.0, 0.0
        try:
            mt5_pos = next((p for p in (self.mt5.get_positions() or [])
                           if p.get("ticket") == ticket), None)
            if mt5_pos:
                pnl = mt5_pos.get("profit", 0.0) + mt5_pos.get("swap", 0.0)
                swap = mt5_pos.get("swap", 0.0)
        except: pass

        close_result = self.mt5.close_position(ticket, expected_volume=hp.volume)
        if close_result is None:
            failed_tickets.append(ticket)
            continue

        self._finalize_close(hp, reason, pnl, swap)
    return failed_tickets
```

### 2.15 _primnet_daily_reset — Overnight Yenileme

```python
def _primnet_daily_reset(self, previous_date: str) -> None:
    """Yeni gün başında overnight pozisyonların PRİMNET SL/TP'sini yenile.
    SL monotonluk: yeni SL eski SL'den kötüyse eski SL korunur."""
    for ticket in list(self.hybrid_positions.keys()):
        hp = self.hybrid_positions.get(ticket)
        if hp is None or hp.state != "ACTIVE": continue

        new_ref = self._get_reference_price(hp.symbol)
        if new_ref is None or new_ref <= 0: continue

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

        # SL monotonluk kontrolü
        sl_worse = False
        if hp.direction == "BUY" and new_sl < hp.current_sl: sl_worse = True
        elif hp.direction == "SELL" and new_sl > hp.current_sl: sl_worse = True
        if sl_worse: new_sl = hp.current_sl

        hp.reference_price = new_ref
        hp.current_sl = new_sl
        hp.current_tp = new_tp
        hp.breakeven_hit = True

        if self._native_sltp:
            self.mt5.modify_position(ticket, sl=new_sl, tp=new_tp)

        self.db.update_hybrid_position(ticket, {
            "current_sl": new_sl, "current_tp": new_tp, "breakeven_hit": 1,
        })
        self.db.insert_hybrid_event(ticket=ticket, symbol=hp.symbol,
                                     event="PRIMNET_DAILY_RESET", details={...})
```

### 2.16 restore_positions — Engine Restart Geri Yükleme

```python
def restore_positions(self) -> None:
    """DB'den aktif hibrit pozisyonları belleğe yükle."""
    rows = self.db.get_active_hybrid_positions()
    for row in rows:
        hp = HybridPosition(
            ticket=row["ticket"], symbol=row["symbol"], direction=row["direction"],
            volume=row["volume"], entry_price=row["entry_price"],
            entry_atr=row["entry_atr"],
            initial_sl=row["initial_sl"], initial_tp=row["initial_tp"],
            current_sl=row.get("current_sl") or row["initial_sl"],
            current_tp=row.get("current_tp") or row["initial_tp"],
            state="ACTIVE",
            breakeven_hit=bool(row.get("breakeven_hit", 0)),
            trailing_active=bool(row.get("trailing_active", 0)),
            transferred_at=row.get("transferred_at", ""),
            db_id=row["id"],
        )
        hp.breakeven_hit = True  # PRİMNET: trailing her zaman aktif
        self.hybrid_positions[hp.ticket] = hp
    self._refresh_daily_pnl()
```

### 2.17 _finalize_close + _handle_external_close

```python
def _finalize_close(self, hp, reason, pnl, swap) -> None:
    """DB + bellek güncelle + günlük PnL + netting kilit serbest + event bus."""
    hp.state = "CLOSED"
    self.db.close_hybrid_position(ticket=hp.ticket, reason=reason, pnl=pnl, swap=swap)
    self.db.insert_hybrid_event(ticket=hp.ticket, symbol=hp.symbol, event="CLOSE",
                                 details={"reason": reason, "pnl": pnl, "swap": swap})
    self._daily_hybrid_pnl += pnl
    self.hybrid_positions.pop(hp.ticket, None)
    from engine.netting_lock import release_symbol
    release_symbol(hp.symbol, owner="h_engine")
    from engine.event_bus import emit as _emit_event
    _emit_event("trade_closed", {
        "ticket": hp.ticket, "symbol": hp.symbol,
        "direction": hp.direction, "pnl": pnl,
        "exit_reason": reason, "source": "hybrid",
    })

def _handle_external_close(self, hp) -> None:
    """MT5'te kapatılmış pozisyon — deal geçmişinden PnL al."""
    pnl, swap = 0.0, 0.0
    try:
        deal_pnl = self.mt5.get_deal_summary(hp.ticket)
        if deal_pnl:
            pnl = deal_pnl.get("pnl", 0.0)
            swap = deal_pnl.get("swap", 0.0)
    except: pass
    self._finalize_close(hp, "EXTERNAL", pnl, swap)
```

---

## 3. V5.9 — api/routes/hybrid_trade.py

**Dosya:** `api/routes/hybrid_trade.py`
**Satır Sayısı:** 155
**5 Endpoint:**

| Endpoint | Metod | Görev |
|----------|-------|-------|
| `/hybrid/check` | POST | Devir ön kontrolü |
| `/hybrid/transfer` | POST | Hibrite devret (atomik) |
| `/hybrid/remove` | POST | Hibritten çıkar |
| `/hybrid/status` | GET | Aktif hibrit pozisyonlar + günlük PnL |
| `/hybrid/events` | GET | Hibrit olay geçmişi |
| `/hybrid/performance` | GET | Performans istatistikleri |

**`/hybrid/status` detayı:**
- MT5'ten güncel fiyat ve PnL bilgisi alır
- PrimnetConfig (trailing_prim, target_prim) döner
- native_sltp modu bilgisi
- daily_pnl ve daily_limit

---

## 4. V5.9 — api/schemas.py (PrimNet Bölümleri)

```python
class HybridCheckRequest(BaseModel):
    ticket: int

class HybridCheckResponse(BaseModel):
    can_transfer: bool = False
    reason: str = ""
    symbol: str = ""
    direction: str = ""
    volume: float = 0.0
    entry_price: float = 0.0
    current_price: float = 0.0
    atr_value: float = 0.0
    suggested_sl: float = 0.0
    suggested_tp: float = 0.0
    hybrid_daily_pnl: float = 0.0
    hybrid_daily_limit: float = 500.0
    active_hybrid_count: int = 0
    max_hybrid_count: int = 3

class HybridTransferRequest(BaseModel):
    ticket: int

class HybridTransferResponse(BaseModel):
    success: bool = False
    message: str = ""
    ticket: int = 0
    symbol: str = ""
    sl: float = 0.0
    tp: float = 0.0
    entry_atr: float = 0.0

class HybridRemoveRequest(BaseModel):
    ticket: int

class HybridRemoveResponse(BaseModel):
    success: bool = False
    message: str = ""

class HybridPositionItem(BaseModel):
    ticket: int
    symbol: str
    direction: str
    volume: float
    entry_price: float
    current_price: float
    entry_atr: float
    initial_sl: float
    initial_tp: float
    current_sl: float
    current_tp: float
    pnl: float = 0.0
    swap: float = 0.0
    breakeven_hit: bool = False
    trailing_active: bool = False
    transferred_at: str = ""
    state: str = "ACTIVE"
    reference_price: float = 0.0

class PrimnetConfig(BaseModel):
    trailing_prim: float = 1.5
    target_prim: float = 9.5

class HybridStatusResponse(BaseModel):
    active_count: int = 0
    max_count: int = 3
    daily_pnl: float = 0.0
    daily_limit: float = 500.0
    native_sltp: bool = False
    positions: list[HybridPositionItem] = []
    primnet: PrimnetConfig = PrimnetConfig()

class HybridEventItem(BaseModel):
    id: int = 0
    timestamp: str = ""
    ticket: int = 0
    symbol: str = ""
    event: str = ""
    details: str = ""

class HybridEventsResponse(BaseModel):
    count: int = 0
    events: list[HybridEventItem] = []
```

---

## 5. V5.9 — config/default.json (Hybrid Bölümü)

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

---

## 6. V5.9 — API Servisi (desktop/src/services/api.js)

```javascript
export async function checkHybridTransfer(ticket) {
  const { data } = await client.post('/hybrid/check', { ticket });
  return data;
}

export async function transferToHybrid(ticket) {
  const { data } = await client.post('/hybrid/transfer', { ticket });
  return data;
}

export async function removeFromHybrid(ticket) {
  const { data } = await client.post('/hybrid/remove', { ticket });
  return data;
}

export async function getHybridStatus() {
  const { data } = await client.get('/hybrid/status');
  return data;
}

export async function getHybridEvents(params = {}) {
  const { data } = await client.get('/hybrid/events', { params });
  return data;
}

export async function getHybridPerformance() {
  const { data } = await client.get('/hybrid/performance');
  return data;
}
```

---

## 7. V5.9 — HybridTrade.jsx

**Dosya:** `desktop/src/components/HybridTrade.jsx` (730 satır)
**Görev:** Hibrit İşlem Paneli — tam sayfa bileşeni

### Yapı

- **State:** openPositions, selectedTicket, checking, checkResult, transferring, transferResult, hybridStatus, hybridEvents, perfStats
- **WebSocket:** `type: "hybrid"` mesajlarını dinler (canlı güncelleme)
- **REST Fallback:** 10sn polling
- **Drag & Drop:** @dnd-kit ile kart sıralaması (5 kart: summary, perf, form, positions, events)

### 5 Kart

1. **Özet:** Aktif Hibrit sayısı, Anlık Floating, Günlük K/Z, Günlük Limit (ilerleme barı)
2. **Performans:** 8 metrik (Toplam, Kazanan, Kaybeden, Başarı%, Toplam K/Z, Ort K/Z, En İyi, En Kötü) + Kapanış Nedenleri rozetleri
3. **Devir & Risk:** Sol panel (pozisyon seçimi + kontrol + devir) + Sağ panel (risk özeti)
4. **Aktif Pozisyonlar:** Tablo (Sembol, Yön, Lot, Giriş, Anlık, SL, TP, K/Z, Durum, Süre, İşlem)
5. **Olay Geçmişi:** Tablo (Zaman, Sembol, Olay, Detay — akıllı format)

### Olay Detay Formatı (events kartı)

```javascript
// TRANSFER: "Giriş: 67.25 | Lot: 1.00 | SL: 66.24 | TP: 73.64"
// BREAKEVEN: "Breakeven: SL 66.24 → 67.25"
// TRAILING_UPDATE: "Trailing SL: 67.25 → 68.00"
// CLOSE: "PRIMNET_TARGET | K/Z: +1,245 | Swap: -3"
// REMOVE: "Hibritten çıkarıldı"
```

---

## 8. V5.9 — PrimnetDetail.jsx

**Dosya:** `desktop/src/components/PrimnetDetail.jsx` (456 satır)
**Görev:** PRİMNET Pozisyon Detay Modalı — -10'dan +10'a prim merdiveni

### Prim Hesaplama Fonksiyonları

```javascript
function priceToPrim(price, refPrice) {
  const onePrim = refPrice * 0.01;
  if (onePrim <= 0) return 0;
  return (price - refPrice) / onePrim;
}

function primToPrice(prim, refPrice) {
  return refPrice + prim * (refPrice * 0.01);
}
```

### buildLadder — Prim Merdiveni Oluşturucu

**Kademeler:** Tam sayılar (-10 ile +10), ±9.5 hedef, giriş primi, stop primi, güncel fiyat
**Durum Sınıfları:** unreachable, target, locked, breakeven, trailing, entry, open, stop, outside
**Her satır:** prim, fiyat, K/Z (TL), stop seviyesi, durum, kilitli kâr, açıklama

### ProximityBar — Tavan/Taban Yakınlık Barı

- -10 ile +10 arasında pozisyonun görsel konumu
- Giriş çizgisi (ortada)
- Faz 2 bölgesi (hedef yakını)
- Aktif pozisyon marker'ı (yukarı/aşağı renk)

### Ana Bileşen Yapısı

1. **Başlık:** PRİMNET rozeti + yön + sembol + ticket
2. **Özet kartları:** Giriş Prim, Güncel Prim, Kâr Primi, K/Z, Trailing
3. **Yakınlık barı:** ProximityBar bileşeni
4. **Kurallar satırı:** "Trailing: 1.5 prim (SABİT) | Hedef: ±9.5 prim"
5. **Prim merdiveni:** 7 kolonlu tablo (PRİM, FİYAT, K/Z, STOP SEV., DURUM, KİLİTLİ KÂR, AÇIKLAMA)
6. **Alt bilgi:** Ref, SL, TP, Lot, Devir zamanı

---

## 9. V5.9 — Dashboard.jsx (PrimNet Referansları)

**Dashboard'daki PRİMNET entegrasyonu:**

- `getHybridStatus()` ile hibrit pozisyon verisi çekilir
- `hybridTickets` Set'i ile pozisyonlar "Hibrit" olarak etiketlenir
- `primnetConfig` state'i saklanır
- Pozisyon tablosunda "PRİMNET" butonu (hibrit pozisyon ise)
- `PrimnetDetail` modalı açılır (pozisyona tıklandığında)
- "Hibrite Devret" butonu (hibrit olmayan pozisyonlar için)
- WebSocket `type: "hybrid"` mesajları ile canlı güncelleme

---

## 10. V5.9 — Testler (test_hybrid_100.py)

**100 kombinasyonlu stres testi — 10 kategori:**

| Kategori | Test Sayısı | Konu |
|----------|-------------|------|
| 1. Devir | 12 | BUY/SELL devir, kâr/zarar devir, limit, duplikat, L3, saatler |
| 2. Prim Hesaplama | 10 | price_to_prim, prim_to_price, roundtrip, ref_price |
| 3. Faz 1 Trailing | 10 | BUY/SELL faz1, iyileşme, gerileme yok, MT5 yazma |
| 4. Faz 2 Trailing | 10 | Sıkı mesafe, kilitli kâr, tavan yakını, desync |
| 5. Hedef Kapanış | 10 | +9.5/-9.5 prim hedef, retry, kapanış sonrası |
| 6. Software SL/TP | 10 | SL/TP hit, retry, 3x başarısız |
| 7. Netting Sync | 10 | Lot ekleme, lot çıkarma, SL/TP yeniden hesaplama |
| 8. EOD/Kill-Switch | 10 | Force close, OLAY rejimi |
| 9. Restore | 8 | Engine restart, DB restore |
| 10. Entegrasyon | 10 | Çoklu pozisyon, günlük PnL, cross-motor |

**Mock sınıfları:** MockConfig, MockDB, MockMT5, MockBaba, MockPipeline
**Helper fonksiyonlar:** `_do_transfer()`, `_simulate_price()`, `_price_at_prim()`, `_prim_at_price()`

---

## 11. V6.0 — h_engine Modülü

**Konum:** `src/ustat/motors/h_engine/`
**Durum:** Tasarım tamamlandı, motor henüz aktif değil (FAZ 6+ işi)

### 11.1 __init__.py — Public API

Dışa aktarılan sınıflar: HybridEngine, EngineState, HEngineConfig, SignalFusion, PositionManager, SLTPManager, RiskFilter + tüm model ve exception sınıfları.

### 11.2 config.py — HEngineConfig (Pydantic BaseSettings)

```python
class HEngineConfig(BaseSettings):
    model_config = {"env_prefix": "HENGINE_"}

    # Pozisyon Limitleri
    max_hybrid_positions: int = 3     # ge=1, le=10
    daily_loss_limit_pct: float = 2.0  # bakiye yüzdesi
    daily_loss_limit_abs: float = 500.0  # mutlak TL
    max_position_size_pct: float = 5.0  # tek pozisyon maks teminat

    # SL/TP Parametreleri (ATR bazlı)
    sl_atr_multiplier: float = 1.5
    tp_atr_multiplier: float = 2.5
    atr_period: int = 14

    # Trailing Stop
    trailing_activation_multiplier: float = 1.0
    trailing_distance_multiplier: float = 1.0
    trailing_min_step_ticks: int = 1

    # Sinyal Füzyon
    min_confidence: float = 0.30
    weight_min: float = 0.2
    weight_max: float = 0.8
    softmax_temperature: float = 1.0
    performance_lookback: int = 20

    # Zamanlama
    cooldown_seconds: int = 300
    cycle_interval_ms: int = 1000
    daily_reset_time: str = "09:25"

    # Güvenlik
    max_close_retries: int = 3
    close_retry_delay_ms: int = 2000
    reconciliation_enabled: bool = True
```

### 11.3 models.py — Veri Modelleri

**Enum'lar:**
- `PositionState`: PENDING_TRANSFER → ACTIVE → TRAILING → CLOSING → CLOSED (+ REJECTED, UNMANAGED, RETRY, EMERGENCY)
- `CloseReason`: SOFTWARE_SL, SOFTWARE_TP, TRAILING_CLOSE, TP_HIT, EXTERNAL_CLOSE, MANUAL_REMOVE, KILL_SWITCH, DAILY_LIMIT, EMERGENCY
- `SignalType`: STRONG_BUY (+0.75..+1.00), BUY (+0.25..+0.75), NEUTRAL, SELL, STRONG_SELL
- `EventType`: 16 olay türü
- `Direction`: BUY, SELL
- `SourceMotor`: MANUAL, OGUL, EXTERNAL

**HybridPosition (V6.0):**
```python
@dataclass
class HybridPosition:
    mt5_ticket: int
    symbol: str
    direction: Direction
    volume: float
    entry_price: float
    software_sl: float
    software_tp: float
    state: PositionState = PositionState.PENDING_TRANSFER
    source_motor: SourceMotor = SourceMotor.MANUAL
    magic_number: int = 0
    h_signal_value: float = 0.0
    id: int | None = None
    trailing_sl: float | None = None
    trailing_max_price: float | None = None
    transfer_time: datetime
    close_retries: int = 0
    updated_at: datetime

    # State machine
    def can_transition_to(self, new_state) -> bool
    def transition_to(self, new_state) -> None

    # Properties
    is_active, is_trailing, is_final
    def calculate_pnl(self, current_price) -> float
```

**HybridSignal (V6.0 — Yeni):**
```python
@dataclass
class HybridSignal:
    value: float          # [-1.0, +1.0]
    signal_type: SignalType
    baba_signal: float
    ogul_signal: float
    w_baba: float
    w_ogul: float
    confidence: float
    # w_baba + w_ogul = 1.0 zorunlu
```

### 11.4 position_manager.py — PRIMNET Pozisyon Yaşam Döngüsü

**transfer_position():** PENDING_TRANSFER → doğrulama → SL/TP hesapla → MT5 SL/TP sıfırla → ACTIVE → DB kaydet
**reconcile():** Her döngüde MT5 vs DB karşılaştırma, EXTERNAL kapanış tespiti
**close_position():** CLOSING → MT5 kapat → başarı: CLOSED / başarısız: RETRY → EMERGENCY
**remove_from_hybrid():** UNMANAGED durumuna geçiş (pozisyon açık kalır)

### 11.5 risk_filter.py — Risk Filtre Zinciri

5 filtre sırayla: min_confidence → baba_veto → position_limit → daily_limit → cooldown

---

## 12. V6.0 — ui/pages/hybrid_page.py

**Dosya:** `ui/pages/hybrid_page.py` (605 satır)
**Teknoloji:** PySide6 (Qt6)
**Görev:** V5.9 HybridTrade.jsx karşılığı — PySide6 ile

**6 Bölüm:**
1. Header bar (Yazılımsal SL/TP rozeti + Sıfırla butonu)
2. 4x istatistik kartı (Aktif Hibrit, Anlık Floating, Günlük K/Z, Günlük Limit)
3. Performans (8 metrik satırı 2x4 grid)
4. Kapanış Nedenleri (rozet satırı)
5. Aktif Hibrit Pozisyonları (QTableWidget — magic 500000-599999 filtresi)
6. Hibrit Olay Geçmişi (QTableWidget)

**Polling:** 10 saniye QTimer

---

## 13. V6.0 — engine/position_keeper.py

**Dosya:** `src/ustat/engine/position_keeper.py`
**Görev:** OĞUL V6.0 — PRIMNET ile açık pozisyonları yönet

**PRIMNET Yaşam Döngüsü (V6.0 genişletilmiş):**
- FAZ 0 — Giriş Koruma
- FAZ 1 — Breakeven
- FAZ 2 — Trailing (1.5 prim sabit)
- FAZ 3 — Hedef (±9.5)
- ZORUNLU — EOD / Kill

**V5.9'dan farklar:**
- VİOP Pending Order koruması (TRADE_ACTION_MODIFY ile SL/TP)
- Likidite sınıfı bazlı breakeven ATR eşikleri (A: 1.0, B: 1.3, C: 1.5)
- Trailing mesafe min/max sınırları (VİOP rapor uyumu)
- PRIMNET_SL_ / PRIMNET_TP_ comment'li bekleyen emirler

---

## 14. Dosya Haritası

### V5.9 Aktif Dosyalar

| Dosya | Satır | Görev |
|-------|-------|-------|
| `engine/h_engine.py` | ~1667 | Ana motor (H-Baba + H-Oğul + PRİMNET) |
| `api/routes/hybrid_trade.py` | 155 | 6 API endpoint |
| `api/schemas.py` | ~110 (hybrid) | Pydantic request/response modelleri |
| `config/default.json` | 12 (hybrid) | PRİMNET config parametreleri |
| `desktop/src/services/api.js` | 60 (hybrid) | 6 API fonksiyonu |
| `desktop/src/components/HybridTrade.jsx` | 730 | Hibrit İşlem Paneli (tam sayfa) |
| `desktop/src/components/PrimnetDetail.jsx` | 456 | PRİMNET Detay Modalı (prim merdiveni) |
| `desktop/src/components/Dashboard.jsx` | ~80 (hybrid) | PRİMNET entegrasyonu |
| `tests/test_hybrid_100.py` | ~600+ | 100 kombinasyonlu stres testi |

### V6.0 Geliştirme Dosyaları

| Dosya | Satır | Görev |
|-------|-------|-------|
| `src/ustat/motors/h_engine/__init__.py` | 78 | Public API |
| `src/ustat/motors/h_engine/config.py` | 230 | Pydantic BaseSettings config |
| `src/ustat/motors/h_engine/models.py` | 315 | Enum + dataclass modelleri |
| `src/ustat/motors/h_engine/position_manager.py` | 587 | Pozisyon yaşam döngüsü |
| `src/ustat/motors/h_engine/risk_filter.py` | 280 | 5 risk filtresi |
| `ui/pages/hybrid_page.py` | 605 | PySide6 Hibrit Paneli |
| `src/ustat/engine/position_keeper.py` | ~780 | PRIMNET PositionKeeper |

---

*Döküm sonu. Tüm aktif kaynak dosyaları eksiksiz dahil edilmiştir.*
