"""POST /api/manual-trade — Manuel işlem paneli (v14.0 — ManuelMotor).

Üç endpoint:
    /manual-trade/check       → Risk ön kontrolü (read-only, emir YOK).
    /manual-trade/execute     → Gerçek MARKET emir gönder (BABA + MT5).
    /manual-trade/risk-scores → Açık manuel pozisyonların risk göstergeleri.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import get_manuel_motor
from api.schemas import (
    ManualRiskScoresResponse,
    ManualTradeCheckRequest,
    ManualTradeCheckResponse,
    ManualTradeExecuteRequest,
    ManualTradeExecuteResponse,
)

router = APIRouter()


@router.post("/manual-trade/check", response_model=ManualTradeCheckResponse)
async def check_manual_trade(req: ManualTradeCheckRequest):
    """Risk ön kontrolü — emir göndermez."""
    mm = get_manuel_motor()
    if not mm:
        return ManualTradeCheckResponse(reason="Engine çalışmıyor")

    direction = req.direction.upper()
    if direction not in ("BUY", "SELL"):
        return ManualTradeCheckResponse(reason="Geçersiz yön (BUY/SELL)")

    check = mm.check_manual_trade(req.symbol, direction)
    return ManualTradeCheckResponse(**check)


@router.post("/manual-trade/execute", response_model=ManualTradeExecuteResponse)
async def execute_manual_trade(req: ManualTradeExecuteRequest):
    """Manuel emir gönder."""
    mm = get_manuel_motor()
    if not mm:
        return ManualTradeExecuteResponse(message="Engine çalışmıyor")

    direction = req.direction.upper()
    if direction not in ("BUY", "SELL"):
        return ManualTradeExecuteResponse(message="Geçersiz yön (BUY/SELL)")

    if req.lot <= 0:
        return ManualTradeExecuteResponse(message="Lot 0'dan büyük olmalı")

    result = mm.open_manual_trade(
        req.symbol, direction, req.lot, sl=req.sl, tp=req.tp,
    )
    return ManualTradeExecuteResponse(**result)


@router.get("/manual-trade/risk-scores", response_model=ManualRiskScoresResponse)
async def get_manual_risk_scores():
    """Tüm açık manuel pozisyonların risk göstergelerini döndür."""
    mm = get_manuel_motor()
    if not mm:
        return ManualRiskScoresResponse()

    scores = mm.get_all_risk_scores()
    return ManualRiskScoresResponse(scores=scores)
