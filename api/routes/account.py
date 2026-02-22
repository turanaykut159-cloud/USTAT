"""GET /api/account — Hesap bilgileri.

Bakiye, equity, floating PnL, günlük PnL.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import get_db, get_mt5
from api.schemas import AccountResponse

router = APIRouter()


@router.get("/account", response_model=AccountResponse)
async def get_account():
    """MT5 hesap bilgilerini döndür."""
    mt5 = get_mt5()
    db = get_db()

    if not mt5 or not mt5.is_connected:
        return AccountResponse()

    info = mt5.get_account_info()
    if info is None:
        return AccountResponse()

    # Floating PnL: açık pozisyonlardan hesapla
    floating_pnl = info.equity - info.balance

    # Günlük PnL: son risk snapshot'tan
    daily_pnl = 0.0
    if db:
        snap = db.get_latest_risk_snapshot()
        if snap:
            daily_pnl = snap.get("daily_pnl", 0.0)

    return AccountResponse(
        login=info.login,
        server=info.server,
        currency=info.currency,
        balance=info.balance,
        equity=info.equity,
        margin=info.margin,
        free_margin=info.free_margin,
        margin_level=info.margin_level,
        floating_pnl=floating_pnl,
        daily_pnl=daily_pnl,
    )
