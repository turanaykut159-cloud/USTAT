"""GET /api/positions — Açık pozisyonlar.

MT5'ten canlı pozisyon listesi. Strateji bilgisi OĞUL active_trades ile zenginleştirilir.
POST /api/positions/close — Tek pozisyonu kapat (ticket ile).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from api.deps import get_mt5, get_ogul, get_h_engine, get_engine
from api.schemas import (
    ClosePositionRequest,
    ClosePositionResponse,
    PositionItem,
    PositionsResponse,
)

router = APIRouter()


# MT5 pozisyon tipi → yön
# MT5Bridge string ("BUY"/"SELL") döndürür, eski format int (0/1) olabilir
_TYPE_MAP = {0: "BUY", 1: "SELL", "BUY": "BUY", "SELL": "SELL"}


def _strategy_for_position(ticket: int, symbol: str, ogul) -> str:
    """Pozisyonun stratejisini OĞUL active_trades üzerinden bul (manual / trend_follow / vb.)."""
    if not ogul or not getattr(ogul, "active_trades", None):
        return "bilinmiyor"
    for _sym, trade in ogul.active_trades.items():
        if getattr(trade, "ticket", 0) == ticket and _sym == symbol:
            return getattr(trade, "strategy", "") or "bilinmiyor"
    return "bilinmiyor"


# Sadece bu üç strateji "Otomatik" sayılır; diğer tümü (manual, bilinmiyor, boş) → Manuel
_OTOMATIK_STRATEJILER = frozenset({"trend_follow", "mean_reversion", "breakout"})


def _tur_for_position(ticket: int, strategy: str, hybrid_tickets: set) -> str:
    """Tür: Hibrit / Otomatik / Manuel (tek kaynak backend)."""
    if ticket in hybrid_tickets:
        return "Hibrit"
    strat = (strategy or "").strip().lower()
    if strat in _OTOMATIK_STRATEJILER:
        return "Otomatik"
    return "Manuel"


@router.get("/positions", response_model=PositionsResponse)
async def get_positions():
    """Açık pozisyonları döndür (strateji + tür ile)."""
    mt5 = get_mt5()
    ogul = get_ogul()
    h_engine = get_h_engine()

    if not mt5 or not mt5.is_connected:
        return PositionsResponse()

    raw = mt5.get_positions()
    if not raw:
        return PositionsResponse()

    hybrid_tickets: set = set()
    if h_engine and getattr(h_engine, "hybrid_positions", None):
        hybrid_tickets = set(h_engine.hybrid_positions.keys())

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

        profit = p.get("profit", 0.0)
        swap = p.get("swap", 0.0)
        ticket = p.get("ticket", 0)
        symbol = p.get("symbol", "")
        strategy = _strategy_for_position(ticket, symbol, ogul)
        tur = _tur_for_position(ticket, strategy, hybrid_tickets)

        items.append(PositionItem(
            ticket=ticket,
            symbol=symbol,
            direction=direction,
            volume=p.get("volume", 0.0),
            entry_price=p.get("price_open", 0.0),
            current_price=p.get("price_current", 0.0),
            sl=p.get("sl", 0.0),
            tp=p.get("tp", 0.0),
            pnl=profit + swap,
            swap=swap,
            open_time=open_time,
            strategy=strategy,
            tur=tur,
        ))

    return PositionsResponse(count=len(items), positions=items)


# ── Pozisyon kapatma ───────────────────────────────────────────────

@router.post("/positions/close", response_model=ClosePositionResponse)
async def close_position(req: ClosePositionRequest):
    """Tek pozisyonu ticket ile kapat (MT5 market kapanış)."""
    mt5 = get_mt5()
    if not mt5 or not mt5.is_connected:
        raise HTTPException(status_code=503, detail="MT5 bağlantısı yok")

    result = mt5.close_position(req.ticket)
    if result is None:
        raise HTTPException(status_code=500, detail="Pozisyon kapatılamadı (MT5 hatası veya pozisyon bulunamadı)")
    engine = get_engine()
    if engine:
        engine.sync_mt5_history_recent(1)
    return ClosePositionResponse(success=True, message="Pozisyon kapatıldı")
