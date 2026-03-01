"""GET /api/risk — Risk snapshot.

Drawdown, limitler, rejim, kill-switch, sayaçlar.
daily_drawdown_pct ve weekly_drawdown_pct anlık hesaplanır (DB şemasına dokunulmaz).
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter

from api.deps import get_baba, get_db, get_engine, get_mt5
from api.schemas import RiskResponse

router = APIRouter()


@router.get("/risk", response_model=RiskResponse)
async def get_risk():
    """Güncel risk durumunu döndür."""
    baba = get_baba()
    db = get_db()
    mt5 = get_mt5()
    engine = get_engine()

    resp = RiskResponse()

    # ── DB'den son risk snapshot ──────────────────────────────────
    if db:
        snap = db.get_latest_risk_snapshot()
        if snap:
            resp.daily_pnl = snap.get("daily_pnl", 0.0)
            resp.floating_pnl = snap.get("floating_pnl", 0.0)
            resp.total_drawdown_pct = snap.get("drawdown", 0.0)
            equity = snap.get("equity", 0.0) or 0.0

            # daily_drawdown_pct: anlık hesapla (kesir, örn. 0.02 = %2)
            if equity > 0 and snap.get("daily_pnl", 0) < 0:
                resp.daily_drawdown_pct = abs(snap["daily_pnl"]) / equity
            else:
                resp.daily_drawdown_pct = 0.0

            # weekly_drawdown_pct: hafta başı equity'den anlık hesapla
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            week_start_iso = f"{monday.isoformat()}T00:00:00"
            snapshots = db.get_risk_snapshots(since=week_start_iso, limit=500)
            if snapshots and equity > 0:
                week_start_equity = snapshots[-1].get("equity", 0.0) or 0.0
                if week_start_equity > 0 and equity < week_start_equity:
                    resp.weekly_drawdown_pct = (week_start_equity - equity) / week_start_equity
                else:
                    resp.weekly_drawdown_pct = 0.0
            else:
                resp.weekly_drawdown_pct = 0.0

            resp.equity = equity

    # ── Baba'dan canlı risk bilgisi ──────────────────────────────
    if baba:
        # Rejim
        if baba.current_regime:
            resp.regime = baba.current_regime.regime_type.value
            resp.risk_multiplier = baba.current_regime.risk_multiplier

        # Kill-switch
        resp.kill_switch_level = baba._kill_switch_level
        resp.blocked_symbols = list(baba._killed_symbols)

        # Risk state sayaçlar
        rs = baba._risk_state
        resp.daily_trade_count = rs.get("daily_trade_count", 0)
        resp.consecutive_losses = rs.get("consecutive_losses", 0)

        # Cooldown
        until = rs.get("cooldown_until")
        if until is not None:
            resp.cooldown_until = str(until)

        # RiskParams'tan limitler
        if engine and hasattr(engine, 'risk_params'):
            rp = engine.risk_params
            resp.max_daily_loss = rp.max_daily_loss
            resp.max_weekly_loss = rp.max_weekly_loss
            resp.max_monthly_loss = rp.max_monthly_loss
            resp.hard_drawdown = rp.hard_drawdown
            resp.max_floating_loss = rp.max_floating_loss
            resp.max_daily_trades = rp.max_daily_trades
            resp.consecutive_loss_limit = rp.consecutive_loss_limit
            resp.max_open_positions = rp.max_open_positions

        # Risk verdict
        if engine and hasattr(engine, 'risk_params'):
            try:
                verdict = baba.check_risk_limits(engine.risk_params)
                resp.can_trade = verdict.can_trade
                resp.lot_multiplier = verdict.lot_multiplier
                resp.risk_reason = verdict.reason
                if verdict.kill_switch_level > resp.kill_switch_level:
                    resp.kill_switch_level = verdict.kill_switch_level
                if verdict.blocked_symbols:
                    combined = set(resp.blocked_symbols) | set(verdict.blocked_symbols)
                    resp.blocked_symbols = list(combined)
            except Exception:
                pass

    # ── MT5'ten açık pozisyon sayısı ──────────────────────────────
    if mt5 and mt5.is_connected:
        positions = mt5.get_positions()
        resp.open_positions = len(positions) if positions else 0

    return resp
