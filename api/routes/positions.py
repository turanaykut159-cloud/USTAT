"""GET /api/positions — Açık pozisyonlar.

MT5'ten canlı pozisyon listesi.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from api.deps import get_mt5
from api.schemas import PositionItem, PositionsResponse

router = APIRouter()


# MT5 pozisyon tipi → yön
_TYPE_MAP = {0: "BUY", 1: "SELL"}


@router.get("/positions", response_model=PositionsResponse)
async def get_positions():
    """Açık pozisyonları döndür."""
    mt5 = get_mt5()

    if not mt5 or not mt5.is_connected:
        return PositionsResponse()

    raw = mt5.get_positions()
    if not raw:
        return PositionsResponse()

    items: list[PositionItem] = []
    for p in raw:
        direction = _TYPE_MAP.get(p.get("type", -1), "UNKNOWN")
        open_time = ""
        t = p.get("time")
        if t:
            try:
                open_time = (
                    datetime.fromtimestamp(t).isoformat()
                    if isinstance(t, (int, float))
                    else str(t)
                )
            except (ValueError, OSError):
                open_time = str(t)

        items.append(PositionItem(
            ticket=p.get("ticket", 0),
            symbol=p.get("symbol", ""),
            direction=direction,
            volume=p.get("volume", 0.0),
            entry_price=p.get("price_open", 0.0),
            current_price=p.get("price_current", 0.0),
            sl=p.get("sl", 0.0),
            tp=p.get("tp", 0.0),
            pnl=p.get("profit", 0.0),
            open_time=open_time,
        ))

    return PositionsResponse(count=len(items), positions=items)
