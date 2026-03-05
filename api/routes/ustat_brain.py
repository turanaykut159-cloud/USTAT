"""GET /api/ustat/brain — ÜSTAT beyin analiz verileri.

v13.0 spesifikasyonu kapsamında ÜSTAT'ın beyin görevleri için
işlem kategorizasyonu, kontrat profilleri, karar akışı ve
rejim bazlı performans verileri sağlar.

Mevcut trades/events tablolarından hesaplanan veriler + henüz
engine'de implemente edilmemiş görevler için placeholder'lar döner.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from api.deps import get_baba, get_db, get_engine
from api.schemas import (
    CategoryGroup,
    ContractProfile,
    EventItem,
    StrategyPool,
    TradeCategories,
    UstatBrainResponse,
)

router = APIRouter()


def _calc_duration_minutes(entry_time: str | None, exit_time: str | None) -> float:
    """İki zaman damgası arasındaki süreyi dakika olarak hesapla."""
    if not entry_time or not exit_time:
        return 0.0
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        entry = datetime.strptime(entry_time[:19], fmt)
        exit_ = datetime.strptime(exit_time[:19], fmt)
        return max((exit_ - entry).total_seconds() / 60.0, 0.0)
    except (ValueError, TypeError):
        return 0.0


def _categorize_trades(trades: list[dict]) -> TradeCategories:
    """İşlemleri çok boyutlu kategorilere ayır."""
    groups: dict[str, dict[str, list[dict]]] = {
        "by_result": {},
        "by_direction": {},
        "by_duration": {},
        "by_regime": {},
        "by_exit_reason": {},
    }

    for t in trades:
        pnl = t.get("pnl")
        if pnl is None:
            continue  # Kapanmamış işlem

        # Sonuca göre
        result_label = "Karlı" if pnl > 0 else ("Zararlı" if pnl < 0 else "Başabaş")
        groups["by_result"].setdefault(result_label, []).append(t)

        # Yöne göre
        direction = t.get("direction", "UNKNOWN")
        groups["by_direction"].setdefault(direction, []).append(t)

        # Süreye göre
        dur_min = _calc_duration_minutes(t.get("entry_time"), t.get("exit_time"))
        if dur_min < 120:
            dur_label = "Kısa (<2s)"
        elif dur_min < 480:
            dur_label = "Orta (2-8s)"
        else:
            dur_label = "Uzun (>8s)"
        groups["by_duration"].setdefault(dur_label, []).append(t)

        # Rejime göre
        regime = t.get("regime") or "Bilinmeyen"
        groups["by_regime"].setdefault(regime, []).append(t)

        # Çıkış nedenine göre
        exit_reason = t.get("exit_reason") or "Bilinmeyen"
        groups["by_exit_reason"].setdefault(exit_reason, []).append(t)

    def build_groups(category: dict[str, list[dict]]) -> list[CategoryGroup]:
        result = []
        for label, trade_list in sorted(category.items()):
            pnls = [tr["pnl"] for tr in trade_list if tr.get("pnl") is not None]
            wins = sum(1 for p in pnls if p > 0)
            total_pnl = sum(pnls)
            count = len(pnls)
            result.append(CategoryGroup(
                label=label,
                count=count,
                total_pnl=round(total_pnl, 2),
                win_rate=round((wins / count) * 100, 1) if count > 0 else 0.0,
                avg_pnl=round(total_pnl / count, 2) if count > 0 else 0.0,
            ))
        return result

    return TradeCategories(
        by_result=build_groups(groups["by_result"]),
        by_direction=build_groups(groups["by_direction"]),
        by_duration=build_groups(groups["by_duration"]),
        by_regime=build_groups(groups["by_regime"]),
        by_exit_reason=build_groups(groups["by_exit_reason"]),
    )


def _build_contract_profiles(trades: list[dict]) -> list[ContractProfile]:
    """Kontrat bazlı detaylı profiller oluştur."""
    by_symbol: dict[str, list[dict]] = {}
    for t in trades:
        sym = t.get("symbol", "")
        if sym:
            by_symbol.setdefault(sym, []).append(t)

    profiles = []
    for symbol, symbol_trades in sorted(by_symbol.items()):
        closed = [t for t in symbol_trades if t.get("pnl") is not None]
        if not closed:
            continue

        pnls = [t["pnl"] for t in closed]
        wins = sum(1 for p in pnls if p > 0)
        total_pnl = sum(pnls)
        count = len(closed)

        durations = [
            _calc_duration_minutes(t.get("entry_time"), t.get("exit_time"))
            for t in closed
        ]
        avg_dur = sum(durations) / len(durations) if durations else 0.0

        # Tercih edilen yön: BUY/SELL hangisi daha kârlı
        buy_pnl = sum(t["pnl"] for t in closed if t.get("direction") == "BUY")
        sell_pnl = sum(t["pnl"] for t in closed if t.get("direction") == "SELL")
        preferred = "BUY" if buy_pnl >= sell_pnl else "SELL"

        # Son işlem tarihi
        last_trade_dt = ""
        for t in closed:
            et = t.get("exit_time") or t.get("entry_time") or ""
            if et > last_trade_dt:
                last_trade_dt = et

        profiles.append(ContractProfile(
            symbol=symbol,
            trade_count=count,
            win_rate=round((wins / count) * 100, 1) if count > 0 else 0.0,
            total_pnl=round(total_pnl, 2),
            avg_pnl=round(total_pnl / count, 2) if count > 0 else 0.0,
            avg_duration_min=round(avg_dur, 1),
            best_pnl=round(max(pnls), 2) if pnls else 0.0,
            worst_pnl=round(min(pnls), 2) if pnls else 0.0,
            last_trade=last_trade_dt[:16] if last_trade_dt else "",
            preferred_direction=preferred,
        ))

    # Toplam K/Z'ye göre sırala (en iyi başta)
    profiles.sort(key=lambda p: p.total_pnl, reverse=True)
    return profiles


@router.get("/ustat/brain", response_model=UstatBrainResponse)
async def get_ustat_brain(
    days: int = Query(90, ge=1, le=365, description="Analiz periyodu (gün)"),
):
    """ÜSTAT beyin analiz verilerini döndür.

    Mevcut trades/events tablolarından hesaplanan veriler ve
    henüz engine'de implemente edilmemiş görevler için boş placeholder'lar.
    """
    engine = get_engine()
    if engine and getattr(engine.mt5, "_connected", False):
        try:
            engine.sync_mt5_history_recent(min(7, days))
        except Exception:
            pass
    db = get_db()
    if not db:
        return UstatBrainResponse()

    # Tarih filtresi
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # İşlemleri çek
    trades = db.get_trades(since=since, limit=5000)

    # İşlem kategorizasyonu
    trade_categories = _categorize_trades(trades)

    # Kontrat profilleri
    contract_profiles = _build_contract_profiles(trades)

    # Son kararlar (events tablosundan)
    events_raw = db.get_events(limit=50)
    recent_decisions = [
        EventItem(
            id=e.get("id", 0),
            timestamp=e.get("timestamp", ""),
            type=e.get("type", ""),
            severity=e.get("severity", "INFO"),
            message=e.get("message", ""),
            action=e.get("action", ""),
        )
        for e in events_raw
    ]

    # Rejim bazlı performans (trade_categories.by_regime ile aynı veri)
    regime_performance = trade_categories.by_regime

    # Strateji havuzu (mevcut rejim)
    current_regime = ""
    baba = get_baba()
    if baba and baba.current_regime:
        current_regime = baba.current_regime.regime_type.value

    strategy_pool = StrategyPool(current_regime=current_regime)

    return UstatBrainResponse(
        trade_categories=trade_categories,
        contract_profiles=contract_profiles,
        recent_decisions=recent_decisions,
        regime_performance=regime_performance,
        strategy_pool=strategy_pool,
        # Placeholder'lar — engine implemente edince dolacak
        error_attributions=[],
        next_day_analyses=[],
        regulation_suggestions=[],
    )
