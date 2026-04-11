"""GET /api/status — Sistem durumu.
POST /api/reactivate — Deaktif kontratları yeniden aktif et.

Bağlantı, rejim, faz, kill-switch, erken uyarılar.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from api.deps import get_baba, get_engine, get_mt5, get_pipeline, get_uptime, is_engine_running
from api.schemas import StatusResponse, SuccessResponse, WarningItem
# v6.0 — Widget Denetimi A5 / H1: Versiyon tek kaynak engine/__init__.py::VERSION.
# TopBar/Settings/LockScreen hardcode "V6.0" stringleri artik /api/status.version
# uzerinden backend'den okur. Tek dokunulacak nokta engine/__init__.py::VERSION.
from engine import VERSION as ENGINE_VERSION

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """Sistem durumunu döndür."""
    engine = get_engine()
    mt5 = get_mt5()
    baba = get_baba()

    # Temel durum
    engine_running = is_engine_running()
    mt5_connected = mt5.is_connected if mt5 else False

    # Rejim
    regime = "TREND"
    regime_confidence = 0.0
    risk_multiplier = 1.0
    if baba and baba.current_regime:
        regime = baba.current_regime.regime_type.value
        regime_confidence = baba.current_regime.confidence
        risk_multiplier = baba.current_regime.risk_multiplier

    # Kill-switch
    kill_switch_level = 0
    daily_trade_count = 0
    if baba:
        kill_switch_level = baba._kill_switch_level
        daily_trade_count = baba._risk_state.get("daily_trade_count", 0)

    # Faz
    if not engine_running:
        phase = "stopped"
    elif not mt5_connected:
        phase = "error"
    elif kill_switch_level >= 3:
        phase = "killed"
    else:
        phase = "running"

    # Erken uyarılar
    warnings: list[WarningItem] = []
    if baba and baba.active_warnings:
        for w in baba.active_warnings:
            warnings.append(WarningItem(
                type=w.warning_type,
                symbol=w.symbol,
                severity=w.severity,
                value=w.value,
                threshold=w.threshold,
                message=w.message,
            ))

    # Son cycle zamanı
    last_cycle = None
    if engine and hasattr(engine, '_last_cycle_time'):
        lc = engine._last_cycle_time
        if lc:
            last_cycle = lc.isoformat() if isinstance(lc, datetime) else str(lc)

    # Deaktif kontratlar
    pipeline = get_pipeline()
    deactivated_symbols = pipeline.get_deactivated_symbols() if pipeline else []

    # v5.4.1: Sessiz hata göstergesi
    import time as _time
    data_fresh = True
    last_successful_cycle = None
    circuit_breaker_active = False

    if engine and hasattr(engine, '_last_successful_cycle_time'):
        lsc = engine._last_successful_cycle_time
        if lsc > 0:
            last_successful_cycle = datetime.fromtimestamp(lsc).isoformat()
            # Veri 60 saniyeden eski ise stale kabul et (6 cycle kaçırılmış)
            stale_threshold = 60.0
            data_fresh = (_time.time() - lsc) < stale_threshold
        else:
            # Engine henüz ilk cycle'ı tamamlamadı
            data_fresh = engine_running

    if mt5 and hasattr(mt5, 'circuit_breaker_active'):
        circuit_breaker_active = mt5.circuit_breaker_active

    return StatusResponse(
        version=ENGINE_VERSION,  # A5/H1: engine/__init__.py::VERSION tek kaynak
        engine_running=engine_running,
        mt5_connected=mt5_connected,
        regime=regime,
        regime_confidence=regime_confidence,
        risk_multiplier=risk_multiplier,
        phase=phase,
        kill_switch_level=kill_switch_level,
        daily_trade_count=daily_trade_count,
        uptime_seconds=get_uptime(),
        last_cycle=last_cycle,
        deactivated_symbols=deactivated_symbols,
        warnings=warnings,
        data_fresh=data_fresh,
        last_successful_cycle=last_successful_cycle,
        circuit_breaker_active=circuit_breaker_active,
    )


@router.post("/reactivate", response_model=SuccessResponse)
async def reactivate_symbols():
    """Tüm deaktif kontratları yeniden aktif et.

    Engine restart veya piyasa saatleri nedeniyle yanlışlıkla
    deaktif edilmiş kontratları toplu olarak geri açar.
    """
    pipeline = get_pipeline()
    if not pipeline:
        return SuccessResponse(success=False, message="DataPipeline aktif değil.")

    deactivated = pipeline.get_deactivated_symbols()
    if not deactivated:
        return SuccessResponse(success=True, message="Deaktif kontrat yok.")

    reactivated: list[str] = []
    for symbol in deactivated:
        if pipeline.reactivate_symbol(symbol):
            reactivated.append(symbol)

    return SuccessResponse(
        success=True,
        message=f"{len(reactivated)} kontrat yeniden aktif edildi: {', '.join(reactivated)}",
    )
