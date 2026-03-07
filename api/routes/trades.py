"""İşlem geçmişi endpoint'leri.

GET  /api/trades       — İşlem geçmişi (filtreli)
GET  /api/trades/stats  — İstatistikler
POST /api/trades/approve — İşlem onaylama
POST /api/trades/sync   — MT5 işlem geçmişi senkronizasyonu
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from api.deps import get_db, get_engine
from engine.baba import RISK_BASELINE_DATE
from api.schemas import (
    ApproveRequest,
    ApproveResponse,
    StrategyStats,
    SymbolStats,
    TradeItem,
    TradeStatsResponse,
    TradesResponse,
)

router = APIRouter()


# ── Yardımcı: DB dict → TradeItem ────────────────────────────────

def _to_trade_item(row: dict) -> TradeItem:
    """Veritabanı satırını TradeItem'a dönüştür."""
    return TradeItem(
        id=row.get("id", 0),
        symbol=row.get("symbol", ""),
        direction=row.get("direction", ""),
        strategy=row.get("strategy", ""),
        lot=row.get("lot", 0.0),
        entry_price=row.get("entry_price"),
        exit_price=row.get("exit_price"),
        pnl=row.get("pnl"),
        slippage=row.get("slippage"),
        commission=row.get("commission"),
        swap=row.get("swap"),
        regime=row.get("regime"),
        fake_score=row.get("fake_score"),
        exit_reason=row.get("exit_reason"),
        entry_time=row.get("entry_time"),
        exit_time=row.get("exit_time"),
    )


def _duration_minutes(entry: str | None, exit_: str | None) -> float | None:
    """İşlem süresini dakika olarak hesapla."""
    if not entry or not exit_:
        return None
    try:
        fmt_patterns = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]
        t_in = t_out = None
        for fmt in fmt_patterns:
            try:
                t_in = datetime.strptime(entry, fmt)
                break
            except ValueError:
                continue
        for fmt in fmt_patterns:
            try:
                t_out = datetime.strptime(exit_, fmt)
                break
            except ValueError:
                continue
        if t_in and t_out:
            return (t_out - t_in).total_seconds() / 60.0
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════
#  GET /api/trades — İşlem geçmişi
# ══════════════════════════════════════════════════════════════════

@router.get("/trades", response_model=TradesResponse)
async def get_trades(
    symbol: str | None = Query(None, description="Kontrat filtresi"),
    strategy: str | None = Query(None, description="Strateji filtresi"),
    limit: int = Query(100, ge=1, le=1000, description="Maks kayıt"),
):
    """İşlem geçmişini filtreli olarak döndür. MT5'te değişim olduğunda anlık: önce son 3 gün sync."""
    engine = get_engine()
    if engine and getattr(engine.mt5, "_connected", False):
        try:
            engine.sync_mt5_history_recent(3)
        except Exception:
            pass
    db = get_db()
    if not db:
        return TradesResponse()

    rows = db.get_trades(
        symbol=symbol, strategy=strategy,
        since=RISK_BASELINE_DATE, limit=limit,
    )
    items = [_to_trade_item(r) for r in rows]

    return TradesResponse(count=len(items), trades=items)


# ══════════════════════════════════════════════════════════════════
#  GET /api/trades/stats — İstatistikler
# ══════════════════════════════════════════════════════════════════

@router.get("/trades/stats", response_model=TradeStatsResponse)
async def get_trade_stats(
    limit: int = Query(500, ge=1, le=5000, description="Analiz edilecek maks kayıt"),
):
    """İşlem istatistiklerini hesapla.

    En kârlı, en zararlı, en uzun, en kısa işlemler.
    Strateji ve sembol bazlı kırılımlar.
    MT5'te değişim olduğunda anlık: önce son 3 gün sync.
    """
    engine = get_engine()
    if engine and getattr(engine.mt5, "_connected", False):
        try:
            engine.sync_mt5_history_recent(3)
        except Exception:
            pass
    db = get_db()
    if not db:
        return TradeStatsResponse()

    rows = db.get_trades(since=RISK_BASELINE_DATE, limit=limit)
    if not rows:
        return TradeStatsResponse()

    items = [_to_trade_item(r) for r in rows]
    pnl_values = [t.pnl for t in items if t.pnl is not None]
    total_trades = len(items)
    winning = [p for p in pnl_values if p > 0]
    losing = [p for p in pnl_values if p < 0]
    total_pnl = sum(pnl_values) if pnl_values else 0.0
    avg_pnl = total_pnl / len(pnl_values) if pnl_values else 0.0
    win_rate = len(winning) / len(pnl_values) * 100 if pnl_values else 0.0

    # En kârlı / en zararlı
    best_trade = max(items, key=lambda t: t.pnl or 0.0) if items else None
    worst_trade = min(items, key=lambda t: t.pnl or 0.0) if items else None

    # En uzun / en kısa (süre bazlı)
    durations: list[tuple[float, TradeItem]] = []
    for t in items:
        d = _duration_minutes(t.entry_time, t.exit_time)
        if d is not None and d > 0:
            durations.append((d, t))

    longest_trade = None
    shortest_trade = None
    avg_duration = 0.0
    if durations:
        durations.sort(key=lambda x: x[0])
        longest_trade = durations[-1][1]
        shortest_trade = durations[0][1]
        avg_duration = sum(d[0] for d in durations) / len(durations)

    # Strateji bazlı
    by_strategy: dict[str, StrategyStats] = {}
    for t in items:
        key = t.strategy or "unknown"
        if key not in by_strategy:
            by_strategy[key] = StrategyStats()
        by_strategy[key].trades += 1
        if t.pnl is not None:
            by_strategy[key].total_pnl += t.pnl
    for key, st in by_strategy.items():
        wins = sum(
            1 for x in items
            if (x.strategy or "unknown") == key and x.pnl is not None and x.pnl > 0
        )
        st.win_rate = wins / st.trades * 100 if st.trades > 0 else 0.0

    # Sembol bazlı
    by_symbol: dict[str, SymbolStats] = {}
    for t in items:
        key = t.symbol
        if key not in by_symbol:
            by_symbol[key] = SymbolStats()
        by_symbol[key].trades += 1
        if t.pnl is not None:
            by_symbol[key].total_pnl += t.pnl
    for key, ss in by_symbol.items():
        wins = sum(
            1 for x in items
            if x.symbol == key and x.pnl is not None and x.pnl > 0
        )
        ss.win_rate = wins / ss.trades * 100 if ss.trades > 0 else 0.0

    return TradeStatsResponse(
        total_trades=total_trades,
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=win_rate,
        total_pnl=total_pnl,
        avg_pnl=avg_pnl,
        best_trade=best_trade,
        worst_trade=worst_trade,
        longest_trade=longest_trade,
        shortest_trade=shortest_trade,
        avg_duration_minutes=avg_duration,
        by_strategy=by_strategy,
        by_symbol=by_symbol,
    )


# ══════════════════════════════════════════════════════════════════
#  POST /api/trades/approve — İşlem onaylama
# ══════════════════════════════════════════════════════════════════

@router.post("/trades/approve", response_model=ApproveResponse)
async def approve_trade(req: ApproveRequest):
    """İşlemi onayla (kayıt altına alma).

    Operatör, gerçekleşen işlemi inceleyip onaylar.
    Veritabanına "approved" notu eklenir.
    """
    db = get_db()
    if not db:
        return ApproveResponse(
            success=False, trade_id=req.trade_id,
            message="Veritabanı bağlantısı yok.",
        )

    trade = db.get_trade(req.trade_id)
    if not trade:
        return ApproveResponse(
            success=False, trade_id=req.trade_id,
            message=f"İşlem bulunamadı: #{req.trade_id}",
        )

    # Exit reason'a onay notu ekle
    existing_reason = trade.get("exit_reason") or ""
    new_reason = f"{existing_reason} | APPROVED by {req.approved_by}"
    if req.notes:
        new_reason += f": {req.notes}"

    success = db.update_trade(req.trade_id, {"exit_reason": new_reason.strip()})

    if success:
        db.insert_event(
            event_type="TRADE",
            message=f"İşlem #{req.trade_id} onaylandı: {req.approved_by}",
            severity="INFO",
            action="APPROVED",
        )

    return ApproveResponse(
        success=success,
        trade_id=req.trade_id,
        message="İşlem onaylandı." if success else "Onay başarısız.",
    )


# ── MT5 Senkronizasyon ─────────────────────────────────────────


@router.post("/trades/sync")
async def sync_mt5_trades(days: int = Query(90, ge=1, le=365)):
    """MT5 işlem geçmişini veritabanına senkronize et.

    MT5'ten deal'leri çeker, position_id ile gruplar,
    IN/OUT eşleştirmesi yaparak trades tablosuna yazar.
    Zaten mevcut olan pozisyonları atlar (dedup).
    """
    engine = get_engine()
    if engine is None:
        raise HTTPException(503, "Engine çalışmıyor")
    if not engine.mt5._connected:
        raise HTTPException(503, "MT5 bağlantısı yok")

    trades = engine.mt5.get_history_for_sync(days=days)
    synced = engine.db.sync_mt5_trades(trades)
    deduped = engine.db.deduplicate_trades()

    return {
        "success": True,
        "total_found": len(trades),
        "newly_added": synced,
        "duplicates_removed": deduped,
        "message": (
            f"{synced} trade senkronize edildi, "
            f"{deduped} çift kayıt temizlendi ({len(trades)} toplam)"
        ),
    }
