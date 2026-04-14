"""GET /api/positions — Açık pozisyonlar.

MT5'ten canlı pozisyon listesi. Strateji bilgisi OĞUL + ManuelMotor active_trades ile zenginleştirilir.
POST /api/positions/close — Tek pozisyonu kapat (ticket ile).
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("ustat.api.positions")

from api.deps import get_mt5, get_ogul, get_h_engine, get_engine, get_manuel_motor, get_db
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


def _strategy_for_position(ticket: int, symbol: str, ogul, manuel_motor) -> str:
    """Pozisyonun stratejisini OĞUL + ManuelMotor active_trades üzerinden bul."""
    # Önce ManuelMotor kontrol (manuel pozisyonlar)
    if manuel_motor and getattr(manuel_motor, "active_trades", None):
        for _sym, trade in manuel_motor.active_trades.items():
            if getattr(trade, "ticket", 0) == ticket and _sym == symbol:
                return "manual"
    # Sonra OĞUL kontrol (otomatik pozisyonlar)
    if ogul and getattr(ogul, "active_trades", None):
        for _sym, trade in ogul.active_trades.items():
            if getattr(trade, "ticket", 0) == ticket and _sym == symbol:
                return getattr(trade, "strategy", "") or "bilinmiyor"
    return "bilinmiyor"


def _universal_fields(ticket: int, symbol: str, ogul, manuel_motor) -> dict:
    """Evrensel yönetim alanlarını oku (manuel pozisyonlar için default)."""
    defaults = {
        "tp1_hit": False, "breakeven_hit": False, "cost_averaged": False,
        "peak_profit": 0.0, "voting_score": 0,
    }
    # Manuel pozisyonlar: evrensel yönetim alanları yok (kullanıcı kontrollü)
    if manuel_motor and getattr(manuel_motor, "active_trades", None):
        for _sym, trade in manuel_motor.active_trades.items():
            if getattr(trade, "ticket", 0) == ticket and _sym == symbol:
                return defaults
    # OĞUL pozisyonları: evrensel yönetim alanları var
    if ogul and getattr(ogul, "active_trades", None):
        for _sym, trade in ogul.active_trades.items():
            if getattr(trade, "ticket", 0) == ticket and _sym == symbol:
                return {
                    "tp1_hit": getattr(trade, "tp1_hit", False),
                    "breakeven_hit": getattr(trade, "breakeven_hit", False),
                    "cost_averaged": getattr(trade, "cost_averaged", False),
                    "peak_profit": getattr(trade, "peak_profit", 0.0),
                    "voting_score": getattr(trade, "voting_score", 0),
                }
    return defaults


# Sadece bu üç strateji "Otomatik" sayılır; diğer tümü (manual, bilinmiyor, boş) → Manuel
_OTOMATIK_STRATEJILER = frozenset({"trend_follow", "mean_reversion", "breakout"})

# Source cache: ticket → source string. Pozisyon açıkken source değişmez.
# Pozisyon kapandığında cache'ten düşer (ticket listede yoksa).
_source_cache: dict[int, str] = {}


def _source_for_position(ticket: int, symbol: str, manuel_motor, db=None) -> str:
    """Pozisyonun source alanını belirle. Sonuç cache'lenir (pozisyon açıkken sabit)."""
    # Cache hit — anında dön
    if ticket in _source_cache:
        return _source_cache[ticket]

    # 1. ÖNCELİKLİ: DB'den orijinal (ilk) kaydı oku.
    #    Aynı ticket için birden fazla kayıt olabilir (adopt sonrası).
    #    En eski kayıt = orijinal açılış → doğru source.
    db_result = None
    if db:
        try:
            row = db._execute(
                "SELECT source FROM trades WHERE mt5_position_id = ? AND symbol = ? "
                "ORDER BY rowid DESC LIMIT 1",
                (ticket, symbol),
            ).fetchone()
            if row is not None:
                db_result = row[0] or ""
        except Exception:
            pass  # DB kilitli — fallback'e devam

    if db_result is not None and db_result != "":
        _source_cache[ticket] = db_result
        return db_result

    # 2. Fallback: bellekteki active_trades'den oku (DB kilitli/boşsa)
    if manuel_motor and getattr(manuel_motor, "active_trades", None):
        for _sym, trade in manuel_motor.active_trades.items():
            if getattr(trade, "ticket", 0) == ticket and _sym == symbol:
                mm_source = getattr(trade, "source", "")
                if mm_source:
                    _source_cache[ticket] = mm_source
                    return mm_source

    # 3. DB'de source boş ve ManuelMotor'da da bulunamayan pozisyon
    #    → MT5 terminalinden doğrudan açılmış.
    #    ManuelMotor (source="app") ve adopt (source="mt5_direct") pozisyonları
    #    yukarıda yakalanır; buraya düşen = henüz adopt edilmemiş MT5 direct.
    _source_cache[ticket] = "mt5_direct"
    return "mt5_direct"


def _tur_for_position(ticket: int, strategy: str, hybrid_tickets: set, source: str = "") -> str:
    """Tür: Hibrit / Otomatik / MT5 / Manuel (tek kaynak backend)."""
    if ticket in hybrid_tickets:
        return "Hibrit"
    strat = (strategy or "").strip().lower()
    if strat in _OTOMATIK_STRATEJILER:
        return "Otomatik"
    if source == "mt5_direct":
        return "MT5"
    return "Manuel"


@router.get("/positions", response_model=PositionsResponse)
async def get_positions():
    """Açık pozisyonları döndür (strateji + tür + risk göstergesi ile)."""
    mt5 = get_mt5()
    ogul = get_ogul()
    h_engine = get_h_engine()
    mm = get_manuel_motor()
    db = get_db()

    if not mt5 or not mt5.is_connected:
        return PositionsResponse()

    raw = mt5.get_positions()
    if not raw:
        return PositionsResponse()

    hybrid_tickets: set = set()
    if h_engine and getattr(h_engine, "hybrid_positions", None):
        hybrid_tickets = set(h_engine.hybrid_positions.keys())

    # Manuel pozisyon risk skorları
    risk_scores: dict = {}
    if mm:
        try:
            risk_scores = mm.get_all_risk_scores()
        except Exception:
            pass

    # Kapanan pozisyonların source cache'ini temizle
    active_tickets = {p.get("ticket", 0) for p in raw}
    stale = [t for t in _source_cache if t not in active_tickets]
    for t in stale:
        del _source_cache[t]

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
        strategy = _strategy_for_position(ticket, symbol, ogul, mm)
        source = _source_for_position(ticket, symbol, mm, db)
        tur = _tur_for_position(ticket, strategy, hybrid_tickets, source)
        ufields = _universal_fields(ticket, symbol, ogul, mm)

        # Risk skoru: Manuel ve MT5 pozisyonlar için (ManuelMotor yönetiminde)
        risk_score = risk_scores.get(symbol, {}) if tur in ("Manuel", "MT5") else {}

        # Widget Denetimi A8 (K10) — Hibrit sanal koruma görünürlüğü.
        # Hibrit pozisyonlarda MT5 native sl/tp genelde 0 döner; gerçek
        # koruma h_engine.hybrid_positions[ticket].current_sl / current_tp
        # içindedir. Dashboard kullanıcısı hibrit satırda "—" görünce
        # pozisyonu korumasız sanabilir. Bu iki alan backend'de doldurulur,
        # frontend italik + tooltip ile gösterir. Manuel/otomatik/MT5
        # satırlarında 0.0 kalır (varsayılan). Drift: Flow 4zb.
        hybrid_sl_val = 0.0
        hybrid_tp_val = 0.0
        if ticket in hybrid_tickets and h_engine:
            hp = h_engine.hybrid_positions.get(ticket)
            if hp is not None:
                hybrid_sl_val = float(getattr(hp, "current_sl", 0.0) or 0.0)
                hybrid_tp_val = float(getattr(hp, "current_tp", 0.0) or 0.0)

        items.append(PositionItem(
            ticket=ticket,
            symbol=symbol,
            direction=direction,
            volume=p.get("volume", 0.0),
            entry_price=p.get("price_open", 0.0),
            current_price=p.get("price_current", 0.0),
            sl=p.get("sl", 0.0),
            tp=p.get("tp", 0.0),
            hybrid_sl=hybrid_sl_val,
            hybrid_tp=hybrid_tp_val,
            pnl=profit + swap,
            swap=swap,
            open_time=open_time,
            strategy=strategy,
            tur=tur,
            risk_score=risk_score,
            **ufields,
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
        raise HTTPException(status_code=404, detail="Pozisyon bulunamadı veya zaten kapalı")
    engine = get_engine()
    if engine:
        engine.sync_mt5_history_recent(1)
    return ClosePositionResponse(success=True, message="Pozisyon kapatıldı")
