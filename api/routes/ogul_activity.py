"""GET /api/ogul/activity — OĞUL sinyal aktivitesi.

Top-5 kontratlarının oylama detayı, aktif strateji parametreleri,
açılamayan işlem sayaçları.
"""

from __future__ import annotations

import logging
import math

from fastapi import APIRouter

from api.deps import get_ogul, get_baba, get_db
from api.schemas import (
    OgulActivityResponse,
    OgulSignalItem,
    OgulUnopenedItem,
)

logger = logging.getLogger("ustat.api.routes.ogul_activity")

router = APIRouter()


def _safe_float(val, default=0.0):
    """NaN/None/Inf için güvenli float dönüşümü."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return default


@router.get("/ogul/activity", response_model=OgulActivityResponse)
async def get_ogul_activity():
    """OĞUL sinyal aktivitesini döndür."""
    try:
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
            try:
                from engine.models.regime import REGIME_STRATEGIES
                strats = REGIME_STRATEGIES.get(baba.current_regime.regime_type, [])
                active_strategies = [s.value for s in strats]
            except Exception:
                active_strategies = []
            adx_val = _safe_float(getattr(baba.current_regime, "adx", 0.0))

        # ── Top-5 sembolleri için oylama detayı ───────────────────────
        _raw_top5 = getattr(ogul, "current_top5", None)
        top5 = list(_raw_top5) if _raw_top5 else []
        signals: list[OgulSignalItem] = []
        signal_count = 0

        _last_signals = getattr(ogul, "last_signals", None) or {}

        for symbol in top5:
            direction = _last_signals.get(symbol, "NOTR") if _last_signals else "NOTR"
            if direction in ("BUY", "SELL"):
                signal_count += 1

            # Oylama detayını al (DB sorgusu — hafif)
            try:
                detail = ogul.get_voting_detail(symbol)
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
                for r in (rows or []):
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
            adx_value=round(_safe_float(adx_val), 1),
            scan_symbols=len(top5),
            signal_count=signal_count,
            unopened_count=unopened_count,
            signals=signals,
            unopened=unopened,
        )
    except Exception as exc:
        logger.exception("ogul/activity endpoint HATASI: %s", exc)
        return OgulActivityResponse()
