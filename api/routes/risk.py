"""GET /api/risk — Risk snapshot.

Drawdown, limitler, rejim, kill-switch, sayaçlar.
daily_drawdown_pct ve weekly_drawdown_pct anlık hesaplanır (DB şemasına dokunulmaz).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter

from api.deps import get_baba, get_db, get_engine, get_mt5

logger = logging.getLogger("ustat.api.routes.risk")
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

            # daily_drawdown_pct: gün başı equity bazlı (Madde 1.2)
            daily_pnl = snap.get("daily_pnl", 0.0)
            day_start_equity = equity - daily_pnl
            if daily_pnl < 0 and day_start_equity > 0:
                resp.daily_drawdown_pct = abs(daily_pnl) / day_start_equity
            else:
                resp.daily_drawdown_pct = 0.0

            # Baseline tarih (Baba'dan al, yoksa fallback)
            baseline_iso = ""
            if baba and hasattr(baba, "risk_baseline_date"):
                from engine.baba import _baseline_to_iso
                baseline_iso = _baseline_to_iso(baba.risk_baseline_date)

            # weekly_drawdown_pct: hafta başı equity'den anlık hesapla (baseline filtreli)
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            week_start_iso = f"{monday.isoformat()}T00:00:00"
            week_since = max(week_start_iso, baseline_iso) if baseline_iso else week_start_iso
            snapshots = db.get_risk_snapshots(since=week_since, limit=1, oldest_first=True)
            if snapshots and equity > 0:
                week_start_equity = snapshots[0].get("equity", 0.0) or 0.0
                if week_start_equity > 0 and equity < week_start_equity:
                    resp.weekly_drawdown_pct = (week_start_equity - equity) / week_start_equity
                else:
                    resp.weekly_drawdown_pct = 0.0
            else:
                resp.weekly_drawdown_pct = 0.0

            # monthly_drawdown_pct: ay başı equity'den anlık hesapla (baseline filtreli)
            month_start = today.replace(day=1)
            month_start_iso = f"{month_start.isoformat()}T00:00:00"
            month_since = max(month_start_iso, baseline_iso) if baseline_iso else month_start_iso
            m_snapshots = db.get_risk_snapshots(since=month_since, limit=1, oldest_first=True)
            if m_snapshots and equity > 0:
                month_start_equity = m_snapshots[0].get("equity", 0.0) or 0.0
                if month_start_equity > 0 and equity < month_start_equity:
                    resp.monthly_drawdown_pct = (month_start_equity - equity) / month_start_equity
                else:
                    resp.monthly_drawdown_pct = 0.0
            else:
                resp.monthly_drawdown_pct = 0.0

            resp.equity = equity
            resp.balance = snap.get("balance", 0.0) or 0.0

    # ── Baba'dan canlı risk bilgisi ──────────────────────────────
    if baba:
        # Rejim
        if baba.current_regime:
            resp.regime = baba.current_regime.regime_type.value
            resp.risk_multiplier = baba.current_regime.risk_multiplier

        # Kill-switch
        resp.kill_switch_level = baba.kill_switch_level
        resp.kill_switch_details = baba.kill_switch_details
        resp.blocked_symbols = baba.killed_symbols

        # Risk state sayaçlar
        rs = baba.risk_state
        resp.daily_trade_count = rs.get("daily_trade_count", 0)
        resp.consecutive_losses = rs.get("consecutive_losses", 0)

        # Cooldown
        until = rs.get("cooldown_until")
        if until is not None:
            resp.cooldown_until = str(until)

        # RiskParams'tan limitler (engine yoksa config'den fallback)
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
        else:
            # Engine henüz başlamadıysa config'den oku (schema default'larına güvenme)
            from engine.config import Config
            try:
                _cfg = Config()
                resp.max_daily_loss = _cfg.get("risk.max_daily_loss_pct", 0.018)
                resp.max_weekly_loss = _cfg.get("risk.max_weekly_loss_pct", 0.04)
                resp.max_monthly_loss = _cfg.get("risk.max_monthly_loss_pct", 0.07)
                resp.hard_drawdown = _cfg.get("risk.hard_drawdown_pct", 0.15)
                resp.max_floating_loss = _cfg.get("risk.max_floating_loss_pct", 0.015)
                resp.max_daily_trades = _cfg.get("risk.max_daily_trades", 5)
                resp.consecutive_loss_limit = _cfg.get("risk.consecutive_loss_limit", 3)
                resp.max_open_positions = _cfg.get("risk.max_open_positions", 5)
            except Exception:
                pass  # Schema default'ları kalır

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
            except Exception as e:
                # Fail-CLOSED: verdict hesaplanamadıysa frontend'e "AÇIK" gösterme
                # (schema default can_trade=True, lot_multiplier=1.0). Anayasa kural 9
                # (Fail-Safe) gereği — güvenlik modülü belirsizse sistem "kilitli".
                logger.exception("Risk limitleri kontrolü HATASI: %s", e)
                resp.can_trade = False
                resp.lot_multiplier = 0.0
                resp.risk_reason = f"Risk verdict hatası: {type(e).__name__}"

    # ── MT5'ten açık pozisyon sayısı ──────────────────────────────
    if mt5 and mt5.is_connected:
        positions = mt5.get_positions()
        resp.open_positions = len(positions) if positions else 0

    return resp
