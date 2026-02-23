"""GET /api/top5 — Güncel Top 5 kontrat.

Ustat modülünden seçilen en iyi 5 kontrat, skorlar, rejim.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import get_baba, get_db, get_ogul, get_ustat
from api.schemas import Top5Item, Top5Response

router = APIRouter()


@router.get("/top5", response_model=Top5Response)
async def get_top5():
    """Güncel Top 5 kontratları döndür."""
    ustat = get_ustat()
    baba = get_baba()
    ogul = get_ogul()
    db = get_db()

    if not ustat:
        return Top5Response()

    # Tüm skorlar (property)
    all_scores = ustat.current_scores or {}

    # Son refresh zamanı
    last_refresh = None
    if ustat.last_refresh:
        last_refresh = ustat.last_refresh.isoformat()

    # Mevcut rejim
    regime_str = ""
    if baba and baba.current_regime:
        regime_str = baba.current_regime.regime_type.value

    # Aktif trade'lerden sinyal yönü bilgisi (read-only)
    active_trades = ogul.active_trades if ogul else {}

    # Top 5 listesi (sıralı)
    sorted_symbols = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
    contracts: list[Top5Item] = []
    for rank, (symbol, score) in enumerate(sorted_symbols[:5], start=1):
        # Sinyal yönü: aktif trade varsa direction, yoksa BEKLE
        trade = active_trades.get(symbol)
        direction = trade.direction if trade else "BEKLE"
        contracts.append(Top5Item(
            rank=rank,
            symbol=symbol,
            score=round(score, 2),
            regime=regime_str,
            signal_direction=direction,
        ))

    # DB'den son Top5 geçmişini de kontrol et (fallback)
    if not contracts and db:
        history = db.get_top5(limit=50)
        seen: set[str] = set()
        for h in history:
            sym = h.get("symbol", "")
            if sym in seen:
                continue
            seen.add(sym)
            contracts.append(Top5Item(
                rank=len(contracts) + 1,
                symbol=sym,
                score=h.get("score", 0.0),
                regime=h.get("regime", ""),
            ))
            if len(contracts) >= 5:
                break

    return Top5Response(
        contracts=contracts,
        last_refresh=last_refresh,
        all_scores={k: round(v, 2) for k, v in all_scores.items()},
    )
