"""POST /api/manual-trade — Manuel işlem paneli.

İki endpoint:
    /manual-trade/check   → Risk ön kontrolü (read-only, emir YOK).
    /manual-trade/execute → Gerçek MARKET emir gönder (BABA + MT5).
"""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import get_ogul
from api.schemas import (
    ManualTradeCheckRequest,
    ManualTradeCheckResponse,
    ManualTradeExecuteRequest,
    ManualTradeExecuteResponse,
)

router = APIRouter()


@router.post("/manual-trade/check", response_model=ManualTradeCheckResponse)
async def check_manual_trade(req: ManualTradeCheckRequest):
    """Risk ön kontrolü — emir göndermez."""
    ogul = get_ogul()
    if not ogul:
        return ManualTradeCheckResponse(reason="Engine çalışmıyor")

    direction = req.direction.upper()
    if direction not in ("BUY", "SELL"):
        return ManualTradeCheckResponse(reason="Geçersiz yön (BUY/SELL)")

    check = ogul.check_manual_trade(req.symbol, direction)
    return ManualTradeCheckResponse(**check)


@router.post("/manual-trade/execute", response_model=ManualTradeExecuteResponse)
async def execute_manual_trade(req: ManualTradeExecuteRequest):
    """Manuel emir gönder."""
    ogul = get_ogul()
    if not ogul:
        return ManualTradeExecuteResponse(message="Engine çalışmıyor")

    direction = req.direction.upper()
    if direction not in ("BUY", "SELL"):
        return ManualTradeExecuteResponse(message="Geçersiz yön (BUY/SELL)")

    if req.lot <= 0 or req.lot > 10:
        return ManualTradeExecuteResponse(message="Geçersiz lot (0-10 arası)")

    result = ogul.open_manual_trade(req.symbol, direction, req.lot)
    return ManualTradeExecuteResponse(**result)
