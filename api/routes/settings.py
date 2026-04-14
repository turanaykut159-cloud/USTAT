"""Ayarlar API — Kullanıcı yapılandırma endpoint'leri.

Endpoint'ler:
    GET  /settings/risk-baseline  → Mevcut risk baseline tarihini döndür
    POST /settings/risk-baseline  → Risk baseline tarihini güncelle
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from fastapi import APIRouter

from api.constants import STATS_BASELINE, get_stats_baseline
from api.deps import get_baba, get_db, get_engine
from api.schemas import (
    NotificationPrefsRequest,
    NotificationPrefsResponse,
    RiskBaselineGetResponse,
    RiskBaselineUpdateRequest,
    RiskBaselineUpdateResponse,
    SessionHoursResponse,
    StatsBaselineResponse,
    TradingLimitsResponse,
    UiPrefsResponse,
    WatchlistResponse,
)

# v6.0 — Widget Denetimi A17: BIST VİOP seans saatleri (fallback).
# Config okunamazsa kullanılır. Backend engine.trading_close (EOD)
# bu değerle senkron olmalıdır. Frontend ErrorTracker ve Performance
# heatmap bu değerleri /api/settings/session endpoint'inden çeker.
DEFAULT_SESSION_HOURS: dict = {
    "market_open": "09:30",
    "market_close": "18:15",
    "eod_close": "17:45",
}

# v6.0 — Widget Denetimi A3/S1: Bildirim tercihleri artık config/default.json
# üzerinden kalıcıdır (eski bellek tabanlı `_notification_prefs` kaldırıldı).
# Kaynak: config.ui.notification_prefs → config.save() ile dosyaya yazılır.
# DEFAULT_PREFS yalnızca config okunamadığında fallback olarak kullanılır;
# frontend default'ları Settings.jsx::DEFAULT_PREFS ile senkron tutulmalıdır.
DEFAULT_NOTIFICATION_PREFS: dict = {
    "soundEnabled": True,
    "killSwitchAlert": True,
    "tradeAlert": True,
    "drawdownAlert": True,
    "regimeAlert": False,
}

# v6.0 — Widget Denetimi A19 / H5: UI-layer sabitleri config'den okunur.
# kill_hold_ms: SideNav kill-switch butonu basılı tutma süresi (ms). Kritik
# koruma parametresi — kullanıcı yanlışlıkla kill-switch tetiklemesini engeller.
# Config okunamazsa fallback olarak bu sabitler kullanılır.
DEFAULT_UI_PREFS: dict = {
    "kill_hold_ms": 2000,
}

# v6.0 — Widget Denetimi A-H3: İzlenen 15 VİOP kontratı fallback listesi.
# Canonical kaynak engine/mt5_bridge.py::WATCHED_SYMBOLS; import başarısız
# olursa bu fallback devreye girer. ManualTrade dropdown'u senkron kalır.
# Yeni kontrat eklendiğinde tek yerde (WATCHED_SYMBOLS) değişir — UI otomatik.
DEFAULT_WATCHLIST_SYMBOLS: list[str] = [
    "F_THYAO", "F_AKBNK", "F_ASELS", "F_TCELL", "F_HALKB",
    "F_PGSUS", "F_GUBRF", "F_EKGYO", "F_SOKM",  "F_TKFEN",
    "F_OYAKC", "F_BRSAN", "F_AKSEN", "F_ASTOR", "F_KONTR",
]

logger = logging.getLogger("ustat.api.routes.settings")

router = APIRouter()


@router.get("/settings/risk-baseline", response_model=RiskBaselineGetResponse)
async def get_risk_baseline():
    """Mevcut risk baseline tarihini döndür."""
    engine = get_engine()
    if not engine:
        return RiskBaselineGetResponse(baseline_date="", source="unavailable")

    baseline = engine.config.get("risk.baseline_date", "")
    source = "config" if baseline else "default"

    # Fallback: baba'dan oku
    if not baseline:
        baba = get_baba()
        if baba and hasattr(baba, "risk_baseline_date"):
            baseline = baba.risk_baseline_date
            source = "baba"

    return RiskBaselineGetResponse(baseline_date=baseline, source=source)


@router.post("/settings/risk-baseline", response_model=RiskBaselineUpdateResponse)
async def update_risk_baseline(req: RiskBaselineUpdateRequest):
    """Risk baseline tarihini güncelle.

    Güncelleme sırası:
        1. Tarih formatı doğrula (YYYY-MM-DD)
        2. Config bellekte güncelle
        3. Config dosyasına kaydet
        4. Baba'nın runtime referansını güncelle
        5. Baba modül sabiti RISK_BASELINE_DATE güncelle
    """
    engine = get_engine()
    if not engine:
        return RiskBaselineUpdateResponse(message="Engine çalışmıyor")

    new_date = req.new_date.strip()

    # 1. Tarih formatı doğrula: "YYYY-MM-DD" veya "YYYY-MM-DD HH:MM"
    date_only = re.match(r"^\d{4}-\d{2}-\d{2}$", new_date)
    date_time = re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", new_date)
    if not date_only and not date_time:
        return RiskBaselineUpdateResponse(
            message=f"Geçersiz format: {new_date} (YYYY-MM-DD veya YYYY-MM-DD HH:MM bekleniyor)"
        )

    try:
        if date_time:
            parsed_dt = datetime.strptime(new_date, "%Y-%m-%d %H:%M")
        else:
            parsed_dt = datetime.strptime(new_date, "%Y-%m-%d")
    except ValueError:
        return RiskBaselineUpdateResponse(
            message=f"Geçersiz tarih: {new_date}"
        )

    # Gelecek tarih kontrolü
    if parsed_dt > datetime.now():
        return RiskBaselineUpdateResponse(
            message=f"Gelecek tarih/saat kabul edilmez: {new_date}"
        )

    # 2. Eski tarihi al
    old_date = engine.config.get("risk.baseline_date", "")

    # 3. Config güncelle + kaydet
    try:
        engine.config.set("risk.baseline_date", new_date)
        engine.config.save()
    except Exception as exc:
        return RiskBaselineUpdateResponse(
            message=f"Config kayıt hatası: {exc}"
        )

    # 4. Baba runtime referansını güncelle
    baba = get_baba()
    if baba and hasattr(baba, "risk_baseline_date"):
        baba.risk_baseline_date = new_date
        logger.info(
            f"Baba risk baseline güncellendi: {old_date} → {new_date}"
        )

    # 5. Baba modül sabiti güncelle (data_pipeline uyumu)
    try:
        import engine.baba as baba_module
        baba_module.RISK_BASELINE_DATE = new_date
    except Exception:
        pass

    # 6. Peak equity sıfırla → drawdown mevcut equity'den yeniden başlasın
    db = get_db()
    if db:
        snap = db.get_latest_risk_snapshot()
        current_equity = snap.get("equity", 0.0) if snap else 0.0
        if current_equity > 0:
            db.set_state("peak_equity", str(current_equity))
            logger.info(
                f"Peak equity sıfırlandı: {current_equity:.2f} (baseline reset)"
            )

    logger.info(
        f"Risk baseline tarihi güncellendi: {old_date} → {new_date}"
    )

    return RiskBaselineUpdateResponse(
        success=True,
        message=f"Risk baseline tarihi güncellendi: {old_date} → {new_date}",
        old_date=old_date,
        new_date=new_date,
    )


def _read_notification_prefs_from_config() -> dict:
    """Config'den bildirim tercihlerini oku; eksik anahtarları default ile doldur.

    Engine yoksa veya config okunamazsa DEFAULT_NOTIFICATION_PREFS döner.
    Kısmi config (örn. sadece soundEnabled) gelirse eksik anahtarlar default
    ile tamamlanır — frontend her zaman 5 anahtarlı tam payload görür.
    """
    engine = get_engine()
    if not engine:
        return dict(DEFAULT_NOTIFICATION_PREFS)
    raw = engine.config.get("ui.notification_prefs", None)
    if not isinstance(raw, dict):
        return dict(DEFAULT_NOTIFICATION_PREFS)
    merged = dict(DEFAULT_NOTIFICATION_PREFS)
    for key in DEFAULT_NOTIFICATION_PREFS:
        if key in raw and isinstance(raw[key], bool):
            merged[key] = raw[key]
    return merged


@router.get("/settings/notification-prefs", response_model=NotificationPrefsResponse)
async def get_notification_prefs():
    """Mevcut bildirim tercihlerini döndür (config.ui.notification_prefs)."""
    return NotificationPrefsResponse(
        success=True, prefs=_read_notification_prefs_from_config()
    )


def _read_session_hours_from_config() -> tuple[dict, str]:
    """Config'den seans saatlerini oku; eksik anahtarları default ile doldur.

    Engine yoksa veya config okunamazsa DEFAULT_SESSION_HOURS döner.
    Kısmi config (örn. sadece eod_close) gelirse eksik anahtarlar default
    ile tamamlanır. Sadece 'HH:MM' format doğrulanır; geçersiz değerler
    sessizce default'la değiştirilir.

    Returns (merged_dict, source) — source: 'config' | 'default'.
    """
    engine = get_engine()
    if not engine:
        return dict(DEFAULT_SESSION_HOURS), "default"
    raw = engine.config.get("session", None)
    if not isinstance(raw, dict):
        return dict(DEFAULT_SESSION_HOURS), "default"
    merged = dict(DEFAULT_SESSION_HOURS)
    hh_mm_re = re.compile(r"^\d{2}:\d{2}$")
    for key in DEFAULT_SESSION_HOURS:
        val = raw.get(key)
        if isinstance(val, str) and hh_mm_re.match(val):
            merged[key] = val
    return merged, "config"


@router.get("/settings/session", response_model=SessionHoursResponse)
async def get_session_hours():
    """BIST VİOP seans saatlerini config'den oku (Widget Denetimi A17).

    Frontend ErrorTracker (EOD geri sayım) ve Performance heatmap
    (9-18 saat aralığı) bu endpoint'ten hardcoded saatleri alır.
    eod_close backend engine.trading_close (EOD zorunlu kapanış,
    Anayasa Kural #5) ile senkron olmalıdır.
    """
    hours, source = _read_session_hours_from_config()
    return SessionHoursResponse(
        market_open=hours["market_open"],
        market_close=hours["market_close"],
        eod_close=hours["eod_close"],
        source=source,
    )


def _read_ui_prefs_from_config() -> tuple[dict, str]:
    """Config'den UI-layer sabitlerini oku; eksik anahtarları default ile doldur.

    Widget Denetimi A19 / H5. Engine yoksa veya config okunamazsa DEFAULT_UI_PREFS
    döner. Geçersiz tipte değerler (örn. string kill_hold_ms) sessizce default'a
    düşer. kill_hold_ms pozitif tamsayı olmalıdır; makul aralık 500-10000 ms.

    Returns (merged_dict, source) — source: 'config' | 'default' | 'error'.
    """
    engine = get_engine()
    if not engine:
        return dict(DEFAULT_UI_PREFS), "default"
    try:
        raw = engine.config.get("ui.kill_hold_ms", None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ui_prefs read failed: %s", exc)
        return dict(DEFAULT_UI_PREFS), "error"
    merged = dict(DEFAULT_UI_PREFS)
    # kill_hold_ms tip + aralık doğrulama: pozitif int, 500-10000 ms aralığı.
    # Geçersiz değer sessizce default'a düşer — UI kırılmasın diye.
    if isinstance(raw, int) and not isinstance(raw, bool) and 500 <= raw <= 10000:
        merged["kill_hold_ms"] = raw
    return merged, "config"


def _read_watchlist_symbols() -> tuple[list[str], str]:
    """engine/mt5_bridge.py::WATCHED_SYMBOLS listesini oku.

    Widget Denetimi A-H3. Canonical kaynak `engine/mt5_bridge.WATCHED_SYMBOLS` —
    ManualTrade dropdown'u hardcode SYMBOLS yerine bu endpoint'ten okur, böylece
    yeni kontrat eklendiğinde tek yerden güncelleme yapılır (backend + UI senkron).

    Import başarısız olur veya liste boş/yanlış tipte gelirse DEFAULT_WATCHLIST_SYMBOLS
    devreye girer — UI dropdown'u asla boş gösterilmez.

    Returns (symbols_list, source) — source: 'bridge' | 'default' | 'error'.
    """
    try:
        from engine.mt5_bridge import WATCHED_SYMBOLS as BRIDGE_SYMBOLS  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("WATCHED_SYMBOLS import failed: %s", exc)
        return list(DEFAULT_WATCHLIST_SYMBOLS), "error"

    if not isinstance(BRIDGE_SYMBOLS, list) or not BRIDGE_SYMBOLS:
        return list(DEFAULT_WATCHLIST_SYMBOLS), "default"

    # Tüm elemanların string olduğunu doğrula — karışık tipler sessizce default'a düşer.
    cleaned = [s for s in BRIDGE_SYMBOLS if isinstance(s, str) and s.strip()]
    if not cleaned:
        return list(DEFAULT_WATCHLIST_SYMBOLS), "default"

    return cleaned, "bridge"


@router.get("/settings/watchlist", response_model=WatchlistResponse)
async def get_watchlist():
    """İzlenen VİOP kontratları listesini döndür (Widget Denetimi A-H3).

    Frontend ManualTrade dropdown'u hardcoded SYMBOLS yerine bu endpoint'ten
    okur. Canonical kaynak `engine/mt5_bridge.py::WATCHED_SYMBOLS`. Yeni kontrat
    eklendiğinde tek yerden (WATCHED_SYMBOLS) güncelleme yapılır; backend +
    frontend otomatik senkron kalır, drift imkansızlaşır.
    """
    symbols, source = _read_watchlist_symbols()
    return WatchlistResponse(symbols=symbols, source=source)


# v6.0 — Widget Denetimi H4: Lot giriş sınırları fallback (VİOP integer kontrat).
# Config okunamaz veya anahtar yoksa bu değerler kullanılır. Canonical kaynak
# `config/default.json.engine.max_lot_per_contract` — frontend Manuel İşlem
# lot input'u hardcoded `min=1 max=10 step=1` yerine bu endpoint'i tüketir.
DEFAULT_LOT_MIN: float = 1.0
DEFAULT_LOT_MAX: float = 1.0
DEFAULT_LOT_STEP: float = 1.0


def _read_trading_limits() -> tuple[float, float, float, str]:
    """Config'den lot giriş sınırlarını oku (Widget Denetimi H4).

    Canonical kaynak `config/default.json.engine.max_lot_per_contract`.
    Ana motor (`engine/ogul.py::OgulEngine.__init__`) ve manuel motor
    (`engine/manuel_motor.py::MAX_LOT_PER_CONTRACT`) aynı limiti kullanır —
    UI bu endpoint üzerinden senkron kalır. Config erişilemez veya anahtar
    yoksa VİOP default'u (1.0/1.0/1.0) devreye girer.

    Returns (lot_min, lot_max, lot_step, source).
    """
    try:
        from engine.config import Config  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("Config import failed (trading-limits): %s", exc)
        return DEFAULT_LOT_MIN, DEFAULT_LOT_MAX, DEFAULT_LOT_STEP, "error"

    try:
        cfg = Config()
        raw_max = cfg.get("engine.max_lot_per_contract", None)
        if raw_max is None:
            return DEFAULT_LOT_MIN, DEFAULT_LOT_MAX, DEFAULT_LOT_STEP, "default"
        lot_max = float(raw_max)
        if lot_max <= 0:
            return DEFAULT_LOT_MIN, DEFAULT_LOT_MAX, DEFAULT_LOT_STEP, "default"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Config read failed (trading-limits): %s", exc)
        return DEFAULT_LOT_MIN, DEFAULT_LOT_MAX, DEFAULT_LOT_STEP, "error"

    # VİOP kontratları integer işlem gördüğünden min/step hard-defaulted.
    # İleride symbol-özel volume_min/volume_step gerekirse buraya genişletilir.
    return DEFAULT_LOT_MIN, lot_max, DEFAULT_LOT_STEP, "config"


@router.get("/settings/trading-limits", response_model=TradingLimitsResponse)
async def get_trading_limits():
    """Lot giriş sınırlarını döndür (Widget Denetimi H4).

    Frontend Manuel İşlem lot input'u hardcoded `min=1 max=10 step=1` yerine
    bu endpoint'ten okur. Canonical kaynak
    `config/default.json.engine.max_lot_per_contract`. Ana motor (OĞUL) ve
    manuel motor aynı limiti uyguladığından UI, config değişikliklerine
    otomatik senkronize olur. Drift imkansızdır.

    Risk notu: config `max_lot_per_contract` değeri 1.0 ise UI max da 1.0
    olur; kullanıcı daha büyük değer giremez. Sessiz truncation (motor
    tarafında min(lot, MAX_LOT_PER_CONTRACT)) ile sınır çıkan yanıltıcı
    UX ortadan kalkar.
    """
    lot_min, lot_max, lot_step, source = _read_trading_limits()
    return TradingLimitsResponse(
        lot_min=lot_min,
        lot_max=lot_max,
        lot_step=lot_step,
        source=source,
    )


@router.get("/settings/ui-prefs", response_model=UiPrefsResponse)
async def get_ui_prefs():
    """UI-layer davranış sabitlerini config'den oku (Widget Denetimi A19 / H5).

    Frontend SideNav (kill-switch basılı tutma süresi) ve gelecekte diğer
    UI-layer sabitleri bu endpoint'ten değer çeker. Hardcode'dan config'e
    taşıma — config.save() ile kalıcı, restart sonrası korunur.

    kill_hold_ms: Kill-switch butonunun basılı tutulması gereken süre (ms).
    Çift aşamalı koruma (basılı tutma + animasyon) kullanıcı yanlışlıkla
    kill-switch tetiklemesini engeller. Varsayılan 2000 ms.
    """
    prefs, source = _read_ui_prefs_from_config()
    return UiPrefsResponse(
        kill_hold_ms=prefs["kill_hold_ms"],
        source=source,
    )


@router.get("/settings/stats-baseline", response_model=StatsBaselineResponse)
async def get_stats_baseline_endpoint():
    """İstatistik ve risk baseline tarihlerini birlikte döndür (Widget Denetimi A7).

    Frontend Performance, TradeHistory ve Dashboard istatistik kartları
    bu endpoint'ten aktif baseline'ı çeker ve küçük bir etiket olarak
    gösterir. İki kavram ayrıdır:

    * stats_baseline → win_rate, profit_factor, best_trade gibi istatistiklerin
      başlangıç tarihi. Kaynak: risk.stats_baseline_date (fallback STATS_BASELINE).
    * risk_baseline → BABA peak_equity/drawdown hesaplamasının başlangıcı.
      Kaynak: risk.baseline_date. Kullanıcı Settings sayfasından değiştirir.
    """
    stats_val = get_stats_baseline()
    stats_source = "config" if stats_val != STATS_BASELINE else "default"

    engine = get_engine()
    risk_val = ""
    risk_source = "unavailable"
    if engine is not None and hasattr(engine, "config"):
        try:
            raw = engine.config.get("risk.baseline_date", "")
        except Exception:
            raw = ""
        if isinstance(raw, str) and raw.strip():
            risk_val = raw.strip()
            risk_source = "config"
        else:
            baba = get_baba()
            if baba is not None and hasattr(baba, "_risk_baseline_date"):
                fallback = getattr(baba, "_risk_baseline_date", "")
                if isinstance(fallback, str) and fallback.strip():
                    risk_val = fallback.strip()
                    risk_source = "default"

    return StatsBaselineResponse(
        stats_baseline=stats_val,
        risk_baseline=risk_val,
        stats_source=stats_source,
        risk_source=risk_source,
    )


@router.post("/settings/notification-prefs", response_model=NotificationPrefsResponse)
async def update_notification_prefs(req: NotificationPrefsRequest):
    """Bildirim tercihlerini güncelle ve config dosyasına kalıcı yaz.

    Kaydetme zinciri:
        1. Engine/config hazır mı kontrol et
        2. Mevcut prefs'i oku (kısmi payload için merge tabanı)
        3. Yeni değerleri merge et
        4. `config.set("ui.notification_prefs", ...)` + `config.save()`
        5. Başarı durumunda güncel payload'ı döndür
    """
    engine = get_engine()
    if not engine:
        logger.warning("Bildirim tercihleri güncellenemedi: engine yok")
        return NotificationPrefsResponse(
            success=False, prefs=dict(DEFAULT_NOTIFICATION_PREFS)
        )

    current = _read_notification_prefs_from_config()
    current.update(req.model_dump())

    try:
        engine.config.set("ui.notification_prefs", current)
        engine.config.save()
    except Exception as exc:
        logger.error(f"Bildirim tercihleri config kayıt hatası: {exc}")
        return NotificationPrefsResponse(success=False, prefs=current)

    logger.info(f"Bildirim tercihleri güncellendi (persist): {current}")
    return NotificationPrefsResponse(success=True, prefs=current)
