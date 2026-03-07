"""GET /api/ogul/activity — OĞUL sinyal aktivitesi.

Top-5 kontratlarının oylama detayı, aktif strateji parametreleri,
açılamayan işlem sayaçları.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import get_ogul, get_baba, get_db
from api.schemas import (
    OgulActivityResponse,
    OgulSignalItem,
    OgulUnopenedItem,
)

router = APIRouter()


@router.get("/ogul/activity", response_model=OgulActivityResponse)
async def get_ogul_activity():
    """OĞUL sinyal aktivitesini döndür."""
    ogul = get_ogul()
    baba = get_baba()
    db = get_db()

    if not ogul:
        return OgulActivityResponse()

    # ── Son M15 mum kapanışı ──────────────────────────────────────
    last_m15 = getattr(ogul, "_last_m15_candle_ts", "") or ""

    # ── Rejim ve aktif stratejiler ────────────────────────────────
    regime_str = "TREND"
    active_strategies: list[str] = []
    adx_val = 0.0

    if baba and baba.current_regime:
        regime_str = baba.current_regime.regime_type.value
        from engine.models.regime import REGIME_STRATEGIES
        strats = REGIME_STRATEGIES.get(baba.current_regime.regime_type, [])
        active_strategies = [s.value for s in strats]
        adx_val = baba.current_regime.adx

    # ── Top-5 sembolleri için oylama detayı ───────────────────────
    top5 = list(ogul._current_top5) if ogul._current_top5 else []
    signals: list[OgulSignalItem] = []
    signal_count = 0

    for symbol in top5:
        direction = ogul.last_signals.get(symbol, "NOTR")
        if direction in ("BUY", "SELL"):
            signal_count += 1

        # Oylama detayını al (DB sorgusu — hafif)
        try:
            detail = ogul._get_voting_detail(symbol)
        except Exception:
            detail = {}

        signals.append(
            OgulSignalItem(
                symbol=symbol,
                direction=direction,
                buy_votes=detail.get("buy_votes", 0),
                sell_votes=detail.get("sell_votes", 0),
                rsi_vote=detail.get("rsi_vote", "NOTR"),
                ema_vote=detail.get("ema_vote", "NOTR"),
                atr_expanding=detail.get("atr_expanding", False),
                volume_above_avg=detail.get("volume_above_avg", False),
            )
        )

    # ── Açılamayan işlemler (bugünün UNOPENED_TRADE eventleri) ────
    unopened: list[OgulUnopenedItem] = []
    unopened_count = 0

    if db:
        try:
            from datetime import date

            rows = db.get_events(event_type="UNOPENED_TRADE", limit=50)
            today_str = date.today().isoformat()
            for r in rows:
                ts = r.get("timestamp", "")
                if ts.startswith(today_str):
                    unopened_count += 1
                    if len(unopened) < 10:  # UI'da son 10 göster
                        unopened.append(
                            OgulUnopenedItem(
                                timestamp=ts,
                                message=r.get("message", ""),
                            )
                        )
        except Exception:
            pass

    return OgulActivityResponse(
        last_m15_close=last_m15,
        regime=regime_str,
        active_strategies=active_strategies,
        adx_value=round(adx_val, 1),
        scan_symbols=len(top5),
        signal_count=signal_count,
        unopened_count=unopened_count,
        signals=signals,
        unopened=unopened,
    )
