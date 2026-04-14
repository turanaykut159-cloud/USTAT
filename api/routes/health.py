"""GET /api/health — Sistem sağlığı metrikleri.

Tek endpoint ile tüm sağlık verisini döndürür:
  - cycle   : Döngü performansı (adım süreleri, trend, aşım)
  - mt5     : MT5 bağlantı sağlığı (ping, kopma, reconnect)
  - orders  : Emir performansı (süre, başarı/ret/timeout)
  - layers  : Katman durumları (BABA, OĞUL, H-Engine, ÜSTAT)
  - recent_events : Son 30 sistem olayı
  - system  : Genel sistem bilgisi (uptime, DB boyutu, WS istemci, cache)

Veri kaynakları:
  - engine.health.snapshot() → bellekte toplanan metrikler (DB'ye yazmaz)
  - Katman öznitelikleri → doğrudan Python obje okuma
  - db.get_events() → SQLite sorgusu (mevcut events tablosu)
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter

logger = logging.getLogger("ustat.api.routes.health")

from api.deps import (
    get_baba,
    get_db,
    get_engine,
    get_h_engine,
    get_ogul,
    get_pipeline,
    get_uptime,
    get_ustat,
)
from api.schemas import HealthResponse

router = APIRouter()


@router.get("/agent-status")
async def get_agent_status():
    """ÜSTAT Ajan heartbeat durumunu döndür."""
    import json
    from pathlib import Path

    hb_path = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent / ".agent" / "heartbeat.json"
    if not hb_path.exists():
        return {"alive": False, "reason": "heartbeat dosyası yok"}
    try:
        data = json.loads(hb_path.read_text(encoding="utf-8"))
        # 30 saniyeden eski heartbeat = ölü
        from datetime import datetime, timezone
        ts = data.get("timestamp", "")
        if ts:
            hb_time = datetime.fromisoformat(ts)
            age = (datetime.now(timezone.utc) - hb_time).total_seconds()
            data["alive"] = data.get("alive", False) and age < 30
            data["age_seconds"] = round(age, 1)
        return data
    except Exception as e:
        return {"alive": False, "reason": str(e)}


@router.get("/health", response_model=HealthResponse)
async def get_health():
    """Sistem sağlığı metriklerini döndür."""
    engine = get_engine()

    # ── 1. HealthCollector snapshot (cycle, mt5, orders) ──────────
    cycle_data: dict = {}
    mt5_data: dict = {}
    orders_data: dict = {}

    alarms_data: dict = {}

    if engine and hasattr(engine, "health"):
        snap = engine.health.snapshot()
        cycle_data = snap.get("cycle", {})
        mt5_data = snap.get("mt5", {})
        orders_data = snap.get("orders", {})
        alarms_data = snap.get("alarms", {})

    # ── 1b. MT5 Algo Trading durumu ───────────────────────────────
    # terminal_info().trade_allowed heartbeat'te guncellenir. False ise
    # retcode 10027 riski — TopBar uyari banner'i icin frontend okur.
    try:
        mt5_bridge = getattr(engine, "mt5", None) if engine else None
        if mt5_bridge and hasattr(mt5_bridge, "is_trade_allowed"):
            mt5_data["trade_allowed"] = bool(mt5_bridge.is_trade_allowed())
        else:
            mt5_data["trade_allowed"] = False  # bilinmiyor => Anayasa Kural 9 fail-safe: suphe=dur
    except Exception as exc:
        logger.debug(f"trade_allowed okunamadi: {exc}")
        mt5_data["trade_allowed"] = False  # Anayasa Kural 9 fail-safe: exception=dur

    # ── 2. Katman durumları ───────────────────────────────────────
    layers = _build_layers()

    # ── 3. Son olaylar ────────────────────────────────────────────
    recent_events = _build_recent_events()

    # ── 4. Sistem bilgisi ─────────────────────────────────────────
    system = _build_system_info()

    return HealthResponse(
        cycle=cycle_data,
        mt5=mt5_data,
        orders=orders_data,
        layers=layers,
        recent_events=recent_events,
        system=system,
        alarms=alarms_data,
    )


# ── Yardımcı fonksiyonlar ────────────────────────────────────────


def _build_layers() -> dict:
    """Katman durumlarını topla (BABA, OĞUL, H-Engine, ÜSTAT)."""
    baba = get_baba()
    ogul = get_ogul()
    h_engine = get_h_engine()
    ustat = get_ustat()

    # ── BABA ──────────────────────────────────────────────────────
    baba_info: dict = {}
    if baba:
        regime = baba.current_regime
        baba_info = {
            "regime": regime.regime_type.value if regime else "UNKNOWN",
            "confidence": round(regime.confidence, 2) if regime else 0.0,
            "risk_multiplier": round(regime.risk_multiplier, 2) if regime else 1.0,
            "kill_switch_level": getattr(baba, "_kill_switch_level", 0),
            "killed_symbols": sorted(getattr(baba, "_killed_symbols", set())),
        }

    # ── OĞUL ──────────────────────────────────────────────────────
    ogul_info: dict = {}
    if ogul:
        active_trades = getattr(ogul, "active_trades", {})
        # O-1/D-7: daily_loss_stop BABA tarafina devredildi — Anayasa Kural 10.
        # OGUL'da stale field kaldirildi; BABA kill_switch_level >= L2 (=2)
        # ise gunluk/ayl1k kayip tetigi aktiftir.
        _ks_level = getattr(baba, "kill_switch_level", 0) if baba else 0
        ogul_info = {
            "active_trade_count": len(active_trades),
            "active_symbols": sorted(active_trades.keys()) if active_trades else [],
            "daily_loss_stop": _ks_level >= 2,
            "universal_management": True,  # USE_UNIVERSAL_MANAGEMENT flag
        }

    # ── H-Engine ──────────────────────────────────────────────────
    h_info: dict = {}
    if h_engine:
        hybrid_pos = getattr(h_engine, "hybrid_positions", {})
        h_info = {
            "active_hybrid_count": len(hybrid_pos),
            "daily_pnl": round(getattr(h_engine, "_daily_hybrid_pnl", 0.0), 2),
            "daily_limit": getattr(h_engine, "_config_daily_limit", 0.0),
            "native_sltp": getattr(h_engine, "_native_sltp", False),
        }

    # ── ÜSTAT ─────────────────────────────────────────────────────
    ustat_info: dict = {}
    if ustat:
        ustat_info = {
            "last_run_time": getattr(ustat, "_last_run_time", ""),
        }

    return {
        "baba": baba_info,
        "ogul": ogul_info,
        "h_engine": h_info,
        "ustat": ustat_info,
    }


def _build_recent_events() -> list[dict]:
    """Son 30 sistem olayını DB'den al."""
    db = get_db()
    if not db:
        return []

    rows = db.get_events(limit=30)
    return [
        {
            "id": r.get("id", 0),
            "timestamp": r.get("timestamp", ""),
            "type": r.get("type", ""),
            "severity": r.get("severity", "INFO"),
            "message": r.get("message", ""),
        }
        for r in rows
    ]


def _build_system_info() -> dict:
    """Genel sistem bilgilerini topla."""
    from api.routes.live import _active_connections

    engine = get_engine()
    pipeline = get_pipeline()
    db = get_db()

    # DB dosya boyutu
    db_size_mb = 0.0
    if db and hasattr(db, "_db_path"):
        try:
            db_size_mb = round(os.path.getsize(db._db_path) / (1024 * 1024), 2)
        except OSError as e:
            logger.debug("DB dosya boyutu okunamadı: %s", e)

    # Cycle sayısı
    cycle_count = 0
    if engine:
        cycle_count = getattr(engine, "_cycle_count", 0)

    # Cache durumu
    cache_stale = False
    if pipeline:
        try:
            cache_stale = pipeline.is_cache_stale()
        except Exception as e:
            logger.warning("Cache staleness kontrolü hatası: %s", e)

    return {
        "engine_uptime_seconds": get_uptime(),
        "cycle_count": cycle_count,
        "db_file_size_mb": db_size_mb,
        "ws_clients": len(_active_connections),
        "cache_stale": cache_stale,
    }
