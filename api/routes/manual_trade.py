"""POST /api/manual-trade — Manuel işlem paneli (v14.0 — ManuelMotor).

Üç endpoint:
    /manual-trade/check       → Risk ön kontrolü (read-only, emir YOK).
    /manual-trade/execute     → Gerçek MARKET emir gönder (BABA + MT5).
    /manual-trade/risk-scores → Açık manuel pozisyonların risk göstergeleri.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import (
    check_idempotency,
    get_idempotent_response,
    get_manuel_motor,
    require_localhost_and_token,
    store_idempotent_response,
)
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


@router.post(
    "/manual-trade/execute",
    response_model=ManualTradeExecuteResponse,
    dependencies=[Depends(require_localhost_and_token)],
)
async def execute_manual_trade(
    req: ManualTradeExecuteRequest,
    idem_key: str | None = Depends(check_idempotency),
):
    """Manuel emir gönder. Idempotency-Key header ile aynı istek tekrar gelirse cached response döner (60sn TTL)."""
    if idem_key:
        cached = get_idempotent_response(idem_key)
        if cached:
            return ManualTradeExecuteResponse(**cached)

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
    # #267 OP-K: Idempotency cache (başarılı sonuç 60sn saklanır)
    if idem_key and isinstance(result, dict):
        store_idempotent_response(idem_key, result)
    return ManualTradeExecuteResponse(**result)


@router.get("/manual-trade/risk-scores", response_model=ManualRiskScoresResponse)
async def get_manual_risk_scores():
    """Tüm açık manuel pozisyonların risk göstergelerini döndür."""
    mm = get_manuel_motor()
    if not mm:
        return ManualRiskScoresResponse()

    scores = mm.get_all_risk_scores()
    return ManualRiskScoresResponse(scores=scores)
