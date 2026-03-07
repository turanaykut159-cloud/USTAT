"""GET /api/performance — Performans metrikleri.

Toplam/günlük/haftalık/aylık PnL, win rate, profit factor,
Sharpe ratio, max drawdown, equity eğrisi.
"""

from __future__ import annotations

import math
from collections import defaultdict

from fastapi import APIRouter, Query

from api.deps import get_db, get_engine
from engine.baba import RISK_BASELINE_DATE
from api.schemas import EquityPoint, PerformanceResponse

router = APIRouter()


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance(
    days: int = Query(30, ge=1, le=365, description="Performans penceresi (gün)"),
):
    """Performans metriklerini hesapla. MT5'te değişim olduğunda anlık: önce son 3 gün sync."""
    engine = get_engine()
    if engine and getattr(engine.mt5, "_connected", False):
        try:
            engine.sync_mt5_history_recent(3)
        except Exception:
            pass
    db = get_db()
    if not db:
        return PerformanceResponse()

    # ── İşlemler (baseline sonrası) ────────────────────────────────
    trades = db.get_trades(since=RISK_BASELINE_DATE, limit=5000)
    if not trades:
        return PerformanceResponse()

    pnl_values = [t.get("pnl", 0.0) or 0.0 for t in trades if t.get("pnl") is not None]
    if not pnl_values:
        return PerformanceResponse()

    total_pnl = sum(pnl_values)
    winning = [p for p in pnl_values if p > 0]
    losing = [p for p in pnl_values if p < 0]
    win_rate = len(winning) / len(pnl_values) * 100 if pnl_values else 0.0

    avg_trade = total_pnl / len(pnl_values) if pnl_values else 0.0
    avg_win = sum(winning) / len(winning) if winning else 0.0
    avg_loss = sum(losing) / len(losing) if losing else 0.0

    # Profit factor
    gross_profit = sum(winning) if winning else 0.0
    gross_loss = abs(sum(losing)) if losing else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    # ── Günlük PnL kırılımı ──────────────────────────────────────
    daily_pnl_map: dict[str, float] = defaultdict(float)
    for t in trades:
        exit_time = t.get("exit_time") or t.get("entry_time")
        pnl = t.get("pnl")
        if exit_time and pnl is not None:
            day = exit_time[:10]  # "YYYY-MM-DD"
            daily_pnl_map[day] += pnl

    daily_pnls = list(daily_pnl_map.values()) if daily_pnl_map else []

    # Günlük, haftalık, aylık PnL (son N gün)
    sorted_days = sorted(daily_pnl_map.keys(), reverse=True)
    daily_pnl_today = daily_pnl_map.get(sorted_days[0], 0.0) if sorted_days else 0.0
    weekly_pnl = sum(daily_pnl_map[d] for d in sorted_days[:5]) if len(sorted_days) >= 1 else 0.0
    monthly_pnl = sum(daily_pnl_map[d] for d in sorted_days[:22]) if len(sorted_days) >= 1 else 0.0

    best_day = max(daily_pnls) if daily_pnls else 0.0
    worst_day = min(daily_pnls) if daily_pnls else 0.0

    # ── Sharpe Ratio (yüzde getiri bazlı, Madde 2.2) ─────────────
    sharpe_ratio = 0.0
    daily_snapshots = db.get_daily_end_snapshots(
        since=f"{RISK_BASELINE_DATE}T00:00:00", limit=365,
    )
    if daily_snapshots:
        daily_returns: list[float] = []
        for snap in daily_snapshots:
            eq = snap.get("equity", 0.0)
            dp = snap.get("daily_pnl", 0.0)
            day_start_eq = eq - dp  # Madde 1.2 formülü ile tutarlı
            if day_start_eq > 0:
                daily_returns.append(dp / day_start_eq)

        if len(daily_returns) >= 5:
            mean_return = sum(daily_returns) / len(daily_returns)
            variance = sum((r - mean_return) ** 2 for r in daily_returns) / len(daily_returns)
            std_return = math.sqrt(variance) if variance > 0 else 0.0
            if std_return > 0:
                sharpe_ratio = (mean_return / std_return) * math.sqrt(252)

    # ── Max Drawdown + Equity Eğrisi (günlük snapshot, Madde 2.3) ──
    max_drawdown_pct = 0.0
    equity_curve: list[EquityPoint] = []

    # daily_snapshots zaten Sharpe için çekildi (ASC sıralı, gün başına 1)
    if daily_snapshots:
        peak_equity = 0.0
        for s in daily_snapshots:
            eq = s.get("equity", 0.0)
            dp = s.get("daily_pnl", 0.0)
            ts = s.get("timestamp", "")
            bal = s.get("balance", 0.0)

            if eq > peak_equity:
                peak_equity = eq
            if peak_equity > 0:
                dd = (peak_equity - eq) / peak_equity
                if dd > max_drawdown_pct:
                    max_drawdown_pct = dd

            equity_curve.append(EquityPoint(
                timestamp=ts,
                equity=eq,
                daily_pnl=dp,
                balance=bal,
            ))

    max_drawdown_pct *= 100  # yüzde olarak

    return PerformanceResponse(
        total_pnl=total_pnl,
        daily_pnl=daily_pnl_today,
        weekly_pnl=weekly_pnl,
        monthly_pnl=monthly_pnl,
        win_rate=win_rate,
        profit_factor=profit_factor,
        sharpe_ratio=round(sharpe_ratio, 2),
        max_drawdown_pct=round(max_drawdown_pct, 2),
        avg_trade_pnl=avg_trade,
        total_trades=len(pnl_values),
        winning_trades=len(winning),
        losing_trades=len(losing),
        avg_win=avg_win,
        avg_loss=avg_loss,
        best_day_pnl=best_day,
        worst_day_pnl=worst_day,
        equity_curve=equity_curve,
    )
