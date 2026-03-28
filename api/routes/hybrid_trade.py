"""Hibrit İşlem API — Pozisyon devir ve yönetim.

Endpoint'ler:
    POST /hybrid/check     → Devir ön kontrolü (H-Baba)
    POST /hybrid/transfer  → Hibrite devret (atomik)
    POST /hybrid/remove    → Hibritten çıkar
    GET  /hybrid/status    → Aktif hibrit pozisyonlar + günlük PnL
    GET  /hybrid/events    → Hibrit olay geçmişi
"""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import get_h_engine, get_db, get_pipeline
from api.schemas import (
    HybridCheckRequest,
    HybridCheckResponse,
    HybridTransferRequest,
    HybridTransferResponse,
    HybridRemoveRequest,
    HybridRemoveResponse,
    HybridPositionItem,
    HybridStatusResponse,
    PrimnetConfig,
    HybridEventItem,
    HybridEventsResponse,
)

router = APIRouter()


@router.post("/hybrid/check", response_model=HybridCheckResponse)
async def check_hybrid_transfer(req: HybridCheckRequest):
    """Hibrite devir ön kontrolü — emir göndermez."""
    h_engine = get_h_engine()
    if not h_engine:
        return HybridCheckResponse(reason="Engine çalışmıyor")

    result = h_engine.check_transfer(req.ticket)
    return HybridCheckResponse(**result)


@router.post("/hybrid/transfer", response_model=HybridTransferResponse)
async def transfer_to_hybrid(req: HybridTransferRequest):
    """Pozisyonu hibrit yönetime devret (atomik)."""
    h_engine = get_h_engine()
    if not h_engine:
        return HybridTransferResponse(message="Engine çalışmıyor")

    result = h_engine.transfer_to_hybrid(req.ticket)
    return HybridTransferResponse(**result)


@router.post("/hybrid/remove", response_model=HybridRemoveResponse)
async def remove_from_hybrid(req: HybridRemoveRequest):
    """Pozisyonu hibrit yönetiminden çıkar."""
    h_engine = get_h_engine()
    if not h_engine:
        return HybridRemoveResponse(message="Engine çalışmıyor")

    result = h_engine.remove_from_hybrid(req.ticket)
    return HybridRemoveResponse(**result)


@router.get("/hybrid/status", response_model=HybridStatusResponse)
async def get_hybrid_status():
    """Aktif hibrit pozisyonlar ve günlük PnL."""
    h_engine = get_h_engine()
    if not h_engine:
        return HybridStatusResponse()

    pipeline = get_pipeline()
    mt5_positions = pipeline.latest_positions if pipeline else []

    # MT5'ten güncel fiyat ve PnL bilgisini al
    mt5_by_ticket: dict[int, dict] = {}
    if mt5_positions:
        mt5_by_ticket = {p.get("ticket"): p for p in mt5_positions}

    items: list[HybridPositionItem] = []
    for hp in h_engine.hybrid_positions.values():
        mt5_pos = mt5_by_ticket.get(hp.ticket)
        current_price = mt5_pos.get("price_current", 0.0) if mt5_pos else 0.0
        pnl = (mt5_pos.get("profit", 0.0) + mt5_pos.get("swap", 0.0)) if mt5_pos else 0.0
        swap = mt5_pos.get("swap", 0.0) if mt5_pos else 0.0

        items.append(HybridPositionItem(
            ticket=hp.ticket,
            symbol=hp.symbol,
            direction=hp.direction,
            volume=hp.volume,
            entry_price=hp.entry_price,
            current_price=current_price,
            entry_atr=hp.entry_atr,
            initial_sl=hp.initial_sl,
            initial_tp=hp.initial_tp,
            current_sl=hp.current_sl,
            current_tp=hp.current_tp,
            pnl=pnl,
            swap=swap,
            breakeven_hit=hp.breakeven_hit,
            trailing_active=hp.trailing_active,
            transferred_at=hp.transferred_at,
            state=hp.state,
            reference_price=hp.reference_price,
        ))

    # PRİMNET config
    primnet_cfg = PrimnetConfig(
        faz1_stop_prim=h_engine._primnet_faz1_stop,
        faz2_activation_prim=h_engine._primnet_faz2_activation,
        faz2_trailing_prim=h_engine._primnet_faz2_trailing,
        target_prim=h_engine._primnet_target,
    )

    return HybridStatusResponse(
        active_count=len(items),
        max_count=h_engine._max_concurrent,
        daily_pnl=h_engine._daily_hybrid_pnl,
        daily_limit=h_engine._config_daily_limit,
        native_sltp=h_engine._native_sltp,
        positions=items,
        primnet=primnet_cfg,
    )


@router.get("/hybrid/events", response_model=HybridEventsResponse)
async def get_hybrid_events(limit: int = 50):
    """Hibrit olay geçmişi."""
    db = get_db()
    if not db:
        return HybridEventsResponse()

    rows = db.get_hybrid_events(limit=limit)
    events = [
        HybridEventItem(
            id=r.get("id", 0),
            timestamp=r.get("timestamp", ""),
            ticket=r.get("ticket", 0),
            symbol=r.get("symbol", ""),
            event=r.get("event", ""),
            details=r.get("details", "{}"),
        )
        for r in rows
    ]
    return HybridEventsResponse(count=len(events), events=events)


@router.get("/hybrid/performance")
async def get_hybrid_performance():
    """Hibrit pozisyon performans istatistikleri."""
    db = get_db()
    if not db:
        return {}
    return db.get_hybrid_performance()
