"""GET /api/performance — Performans metrikleri.

Toplam/günlük/haftalık/aylık PnL, win rate, profit factor,
Sharpe ratio, max drawdown, equity eğrisi.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict

from fastapi import APIRouter, Query

from api.constants import STATS_BASELINE, get_stats_baseline
from api.deps import get_db

logger = logging.getLogger("ustat.api.routes.performance")
from api.schemas import EquityPoint, PerformanceResponse

router = APIRouter()


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance(
    days: int = Query(30, ge=1, le=365, description="Performans penceresi (gün)"),
):
    """Performans metriklerini hesapla.

    Sync, engine cycle'ında event-driven yapılır (_check_position_closures).
    """
    db = get_db()
    if not db:
        return PerformanceResponse()

    # ── İşlemler (baseline ∩ son N gün) ─────────────────────────────
    # Widget Denetimi A7: baseline tek kaynaktan (config/default.json
    # risk.stats_baseline_date → fallback: api.constants.STATS_BASELINE).
    # P1-A (2026-04-13): days parametresi artık gerçekten uygulanır.
    # Pencere = max(baseline, today - days) — periyot butonu equity
    # eğrisini ve aggregate metrikleri etkiler.
    from datetime import datetime, timedelta
    baseline = get_stats_baseline()
    days_cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    effective_since = max(baseline[:10], days_cutoff)
    trades = db.get_trades(since=effective_since, limit=5000)
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

    # Profit factor: kayıp yoksa ve kâr varsa sonsuz (∞), her ikisi yoksa 0
    gross_profit = sum(winning) if winning else 0.0
    gross_loss = abs(sum(losing)) if losing else 0.0
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = 999.0  # Hiç zarar yok, saf kâr → sonsuz göstergesi
    else:
        profit_factor = 0.0

    # ── Günlük PnL kırılımı ──────────────────────────────────────
    daily_pnl_map: dict[str, float] = defaultdict(float)
    for t in trades:
        exit_time = t.get("exit_time") or t.get("entry_time")
        pnl = t.get("pnl")
        if exit_time and pnl is not None:
            day = exit_time[:10]  # "YYYY-MM-DD"
            daily_pnl_map[day] += pnl

    daily_pnls = list(daily_pnl_map.values()) if daily_pnl_map else []

    # Günlük, haftalık, aylık PnL (takvim bazlı)
    from datetime import date, timedelta
    sorted_days = sorted(daily_pnl_map.keys(), reverse=True)
    daily_pnl_today = daily_pnl_map.get(sorted_days[0], 0.0) if sorted_days else 0.0
    _today = date.today()
    _week_start = (_today - timedelta(days=_today.weekday())).isoformat()  # Pazartesi
    _month_start = _today.replace(day=1).isoformat()
    weekly_pnl = sum(v for d, v in daily_pnl_map.items() if d >= _week_start)
    monthly_pnl = sum(v for d, v in daily_pnl_map.items() if d >= _month_start)

    best_day = max(daily_pnls) if daily_pnls else 0.0
    worst_day = min(daily_pnls) if daily_pnls else 0.0

    # ── Sharpe Ratio (yüzde getiri bazlı, Madde 2.2) ─────────────
    sharpe_ratio = 0.0
    # A7 + P1-A: Aynı pencere (baseline ∩ son N gün), trades ile eşlenir.
    _snap_since = effective_since if effective_since else STATS_BASELINE
    daily_snapshots = db.get_daily_end_snapshots(
        since=f"{_snap_since}T00:00:00", limit=365,
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
    # Widget Denetimi A6 (B14): equity vs net sermaye ayrımı
    # ──────────────────────────────────────────────────────────────
    # Yatırım transferleri (deposit) ve çekimler (withdrawal) bakiye
    # büyümesi olarak görünür ama "kazanç" değildir. UI bu artışı
    # kâr trendi gibi çizmesin diye her gün için:
    #   delta_balance      = balance[i] - balance[i-1]
    #   explained_pnl      = trades that closed on day_i (pnl + comm + swap)
    #   delta_unexplained  = delta_balance - explained_pnl
    # Eğer |delta_unexplained| eşiği aşarsa → deposit/withdrawal sayılır
    # Eşik: max(100 TRY, prev_balance * 0.5%) — komisyon/swap gürültüsünü
    # filtreler, yatırım/çekimleri yakalar. Kümülatif toplam
    # cumulative_deposits, net_equity = equity - cumulative_deposits.
    # ──────────────────────────────────────────────────────────────

    # Günlük net bakiye etkisi: pnl + commission + swap
    # (commission/swap genellikle negatif, pnl gross profit)
    daily_balance_impact: dict[str, float] = defaultdict(float)
    for t in trades:
        exit_time = t.get("exit_time") or t.get("entry_time")
        if not exit_time:
            continue
        day = exit_time[:10]
        impact = (t.get("pnl") or 0.0) \
            + (t.get("commission") or 0.0) \
            + (t.get("swap") or 0.0)
        daily_balance_impact[day] += impact

    max_drawdown_pct = 0.0
    equity_curve: list[EquityPoint] = []

    # daily_snapshots zaten Sharpe için çekildi (ASC sıralı, gün başına 1)
    if daily_snapshots:
        peak_equity = 0.0
        prev_balance: float | None = None
        cumulative_deposits = 0.0

        for s in daily_snapshots:
            eq = s.get("equity", 0.0)
            dp = s.get("daily_pnl", 0.0)
            ts = s.get("timestamp", "")
            bal = s.get("balance", 0.0)
            day_key = ts[:10] if ts else ""

            # A6 (B14): deposit/withdrawal tespiti — bakiye değişimi
            # işlem aktivitesiyle açıklanamıyorsa transfer say
            if prev_balance is not None:
                delta_balance = bal - prev_balance
                explained = daily_balance_impact.get(day_key, 0.0)
                delta_unexplained = delta_balance - explained
                threshold = max(100.0, prev_balance * 0.005)
                if abs(delta_unexplained) > threshold:
                    cumulative_deposits += delta_unexplained
            prev_balance = bal

            net_equity = eq - cumulative_deposits

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
                cumulative_deposits=round(cumulative_deposits, 2),
                net_equity=round(net_equity, 2),
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
