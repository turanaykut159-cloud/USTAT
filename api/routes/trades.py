"""İşlem geçmişi endpoint'leri.

GET  /api/trades       — İşlem geçmişi (filtreli)
GET  /api/trades/stats  — İstatistikler
POST /api/trades/approve — İşlem onaylama
POST /api/trades/sync   — MT5 işlem geçmişi senkronizasyonu
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from api.constants import STATS_BASELINE
from api.deps import get_db, get_engine

logger = logging.getLogger("ustat.api.routes.trades")
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


# ── Yardımcı: Trade tutarlılık kontrolü (Widget Denetimi A2) ─────

def _check_trade_consistency(
    direction: str | None,
    entry_price: float | None,
    exit_price: float | None,
    pnl: float | None,
) -> str | None:
    """Trade kaydının işaret tutarlılığını kontrol eder.

    MT5 netting mod'da aynı position_id altında scale-in/out veya ters
    dönüşler tek pozisyon olarak toplandığında `get_history_for_sync`
    weighted avg entry/exit üretir, pnl ise MT5 raw profit toplamıdır.
    Bu iki değer bazı parçalı pozisyonlarda matematiksel olarak
    tutarsızlaşır (örn. BUY olarak kaydedilmiş ama exit<entry olduğu
    halde pnl pozitif). Stats endpoint bu trade'leri best/worst
    seçiminden hariç tutar; kullanıcı yanlışlıkla "en kârlı işlem"
    olarak anomali görmez.

    Args:
        direction: "BUY" / "SELL" / ""
        entry_price: ağırlıklı ortalama giriş
        exit_price: ağırlıklı ortalama çıkış
        pnl: MT5 raw profit (ground truth)

    Returns:
        "SIGN_MISMATCH" — pnl işareti (direction × price_diff) işaretiyle çelişiyor
        None — tutarlı veya kontrol için yeterli veri yok
    """
    if pnl is None or entry_price is None or exit_price is None:
        return None
    if direction not in ("BUY", "SELL"):
        return None
    # pnl == 0 (komisyon-wash) tutarsız sayılmaz
    if pnl == 0:
        return None
    price_diff = exit_price - entry_price
    if price_diff == 0:
        return None
    expected_sign = 1 if direction == "BUY" else -1
    # BUY: pnl ve price_diff aynı işaretli olmalı
    # SELL: pnl ve -price_diff aynı işaretli olmalı
    if (pnl > 0) != ((expected_sign * price_diff) > 0):
        return "SIGN_MISMATCH"
    return None


# ── Yardımcı: DB dict → TradeItem ────────────────────────────────

def _to_trade_item(row: dict) -> TradeItem:
    """Veritabanı satırını TradeItem'a dönüştür."""
    entry_price = row.get("entry_price")
    exit_price = row.get("exit_price")
    direction = row.get("direction", "")
    pnl = row.get("pnl")
    return TradeItem(
        id=row.get("id", 0),
        symbol=row.get("symbol", ""),
        direction=direction,
        strategy=row.get("strategy", ""),
        lot=row.get("lot", 0.0),
        entry_price=entry_price,
        exit_price=exit_price,
        pnl=pnl,
        slippage=row.get("slippage"),
        commission=row.get("commission"),
        swap=row.get("swap"),
        regime=row.get("regime"),
        fake_score=row.get("fake_score"),
        exit_reason=row.get("exit_reason"),
        entry_time=row.get("entry_time"),
        exit_time=row.get("exit_time"),
        data_warning=_check_trade_consistency(
            direction, entry_price, exit_price, pnl,
        ),
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
    except Exception as e:
        logger.warning("Duration hesaplama hatası: %s", e)
    return None


# ══════════════════════════════════════════════════════════════════
#  GET /api/trades — İşlem geçmişi
# ══════════════════════════════════════════════════════════════════

@router.get("/trades", response_model=TradesResponse)
async def get_trades(
    symbol: str | None = Query(None, description="Kontrat filtresi"),
    strategy: str | None = Query(None, description="Strateji filtresi"),
    since: str | None = Query(None, description="Başlangıç tarihi (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=1000, description="Maks kayıt"),
):
    """İşlem geçmişini filtreli olarak döndür.

    Sync, engine cycle'ında event-driven yapılır (_check_position_closures).
    """
    db = get_db()
    if not db:
        return TradesResponse()

    rows = db.get_trades(
        symbol=symbol, strategy=strategy,
        since=since, limit=limit,
    )
    items = [_to_trade_item(r) for r in rows]

    return TradesResponse(count=len(items), trades=items)


# ══════════════════════════════════════════════════════════════════
#  GET /api/trades/stats — İstatistikler
# ══════════════════════════════════════════════════════════════════

@router.get("/trades/stats", response_model=TradeStatsResponse)
async def get_trade_stats(
    since: str | None = Query(STATS_BASELINE, description="Başlangıç tarihi (YYYY-MM-DD)"),
    limit: int = Query(500, ge=1, le=5000, description="Analiz edilecek maks kayıt"),
):
    """İşlem istatistiklerini hesapla.

    En kârlı, en zararlı, en uzun, en kısa işlemler.
    Strateji ve sembol bazlı kırılımlar.
    Sync, engine cycle'ında event-driven yapılır (_check_position_closures).
    """
    db = get_db()
    if not db:
        return TradeStatsResponse()

    rows = db.get_trades(since=since, limit=limit)
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

    # v6.0 — Widget Denetimi A2: En kârlı / en zararlı seçiminde
    # SIGN_MISMATCH anomalileri hariç tutulur. MT5 netting sync'te
    # parçalı pozisyonlar weighted avg entry/exit ile pnl işareti çelişebilir;
    # bu kayıtlar "best_trade" olarak UI'a çıkarsa kullanıcıyı yanıltır.
    # total_pnl / win_rate / avg_pnl dahil diğer tüm metrikler ETKİLENMEZ —
    # pnl değeri MT5 ground truth olarak kalır.
    clean_items = [t for t in items if t.data_warning is None]
    anomaly_count = sum(1 for t in items if t.data_warning is not None)
    best_trade = (
        max(clean_items, key=lambda t: t.pnl or 0.0) if clean_items else None
    )
    worst_trade = (
        min(clean_items, key=lambda t: t.pnl or 0.0) if clean_items else None
    )

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
        anomaly_count=anomaly_count,
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


# ── Rejim Backfill ───────────────────────────────────────────


@router.post("/trades/backfill-regime")
async def backfill_regime():
    """NULL rejimli eski işlemlere top5_history'den rejim ata.

    top5_history tablosunda her gün için hangi rejimin aktif olduğu
    kayıtlıdır. Bu endpoint, rejimi NULL olan her işlemi entry_time
    tarihine göre eşleştirerek günceller. Eşleşmeyen kayıtlara
    'UNKNOWN' atanır.

    Tek seferlik bakım endpoint'i — veri düzeltme sonrası kaldırılabilir.
    """
    db = get_db()
    if db is None:
        raise HTTPException(503, "Database mevcut değil")

    # 1. top5_history'den tarih -> rejim haritası
    rows = db._fetch_all(
        """SELECT date, regime, COUNT(*) as cnt
           FROM top5_history
           WHERE regime IS NOT NULL AND regime != ''
           GROUP BY date, regime
           ORDER BY date, cnt DESC"""
    )
    date_regime: dict[str, str] = {}
    for r in rows:
        if r["date"] not in date_regime:
            date_regime[r["date"]] = r["regime"]

    # 2. NULL rejimli işlemleri bul
    null_trades = db._fetch_all(
        "SELECT id, entry_time FROM trades WHERE regime IS NULL OR regime = ''"
    )

    matched = 0
    unknown = 0
    for t in null_trades:
        entry_date = (t["entry_time"] or "")[:10]
        regime = date_regime.get(entry_date)
        if regime:
            db.update_trade(t["id"], {"regime": regime})
            matched += 1
        else:
            db.update_trade(t["id"], {"regime": "UNKNOWN"})
            unknown += 1

    logger.info(
        f"Rejim backfill: {matched} eşleşti, {unknown} UNKNOWN atandı "
        f"(toplam {len(null_trades)} NULL işlem)"
    )

    return {
        "success": True,
        "total_null": len(null_trades),
        "matched_from_top5": matched,
        "set_unknown": unknown,
        "message": (
            f"{matched} işleme top5_history'den rejim atandı, "
            f"{unknown} işlem UNKNOWN olarak işaretlendi"
        ),
    }
