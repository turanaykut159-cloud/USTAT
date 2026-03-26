"""ÜSTAT v5.7.1 API — Haber Entegrasyon Endpoint'leri.

Endpoint'ler:
    GET  /api/news/status       — Haber motoru durum bilgisi
    GET  /api/news/active       — Aktif haberler listesi
    GET  /api/news/briefing     — Pre-market sabah briefing
    POST /api/news/briefing     — Manuel briefing tetikle
    POST /api/news/test         — Test haberi inject et
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from api.deps import get_engine
from api.schemas import (
    NewsStatusResponse,
    NewsActiveResponse,
    NewsEventItem,
    ErrorResponse,
)

logger = logging.getLogger("ustat.api.news")

router = APIRouter()


@router.get("/news/status", response_model=NewsStatusResponse)
async def news_status():
    """Haber motoru durum bilgisi — Dashboard üst panel için."""
    engine = get_engine()
    if not engine or not hasattr(engine, 'news_bridge'):
        return NewsStatusResponse(enabled=False)

    nb = engine.news_bridge
    status = nb.get_status()

    return NewsStatusResponse(
        enabled=status["enabled"],
        provider_count=status["provider_count"],
        active_news_count=status["active_news_count"],
        total_processed=status["total_processed"],
        total_positive=status["total_positive"],
        total_negative=status["total_negative"],
        worst_sentiment=status["worst_sentiment"],
        worst_headline=status["worst_headline"],
        worst_severity=status["worst_severity"],
        best_sentiment=status["best_sentiment"],
        best_headline=status["best_headline"],
    )


@router.get("/news/active", response_model=NewsActiveResponse)
async def news_active():
    """Aktif (süresi dolmamış) haberler listesi."""
    engine = get_engine()
    if not engine or not hasattr(engine, 'news_bridge'):
        return NewsActiveResponse()

    nb = engine.news_bridge
    events = nb.get_active_events()

    items = []
    for ev in events:
        items.append(NewsEventItem(
            headline=ev.headline,
            source=ev.source,
            timestamp=ev.timestamp,
            time_str=ev.to_dict()["time_str"],
            category=ev.category,
            sentiment_score=round(ev.sentiment_score, 3),
            confidence=round(ev.confidence, 3),
            symbols=ev.symbols,
            is_global=ev.is_global,
            severity=ev.severity,
            age_seconds=round(ev.age_seconds, 1),
            lot_multiplier=ev.lot_multiplier,
        ))

    best_s = max((it.sentiment_score for it in items), default=None) if items else None
    worst_s = min((it.sentiment_score for it in items), default=None) if items else None

    return NewsActiveResponse(
        count=len(items),
        events=items,
        best_sentiment=best_s,
        worst_sentiment=worst_s,
    )


@router.get("/news/briefing")
async def news_briefing():
    """Sabah pre-market briefing sonucu — Dashboard için."""
    engine = get_engine()
    if not engine or not hasattr(engine, 'premarket_briefing'):
        return {"error": "PreMarketBriefing modülü aktif değil", "briefing": None}

    briefing = engine.premarket_briefing.get_latest_briefing()
    if briefing is None:
        return {
            "briefing": None,
            "message": "Henüz bugün için briefing oluşturulmadı. "
                       "Briefing 09:30-09:50 arasında otomatik çalışır.",
        }
    return {"briefing": briefing}


@router.post("/news/briefing")
async def news_briefing_force():
    """Manuel briefing tetikle — test/geliştirme için."""
    engine = get_engine()
    if not engine or not hasattr(engine, 'premarket_briefing'):
        # Yoksa oluştur
        if engine and hasattr(engine, 'news_bridge'):
            from engine.news_bridge import PreMarketBriefing
            engine.premarket_briefing = PreMarketBriefing(
                engine.news_bridge, engine.config if hasattr(engine, 'config') else None
            )
        else:
            return {"success": False, "error": "news_bridge bulunamadı"}

    result = engine.premarket_briefing.force_briefing()
    return {"success": True, "briefing": result}


@router.post("/news/test")
async def news_inject_test():
    """Geliştirme/test amaçlı sahte haber inject et — NewsPanel render kontrolü için.

    Bu endpoint SADECE development ortamında kullanılmalıdır.
    Cache'e 2 test haber ekler (1 negatif KRİTİK, 1 pozitif).
    5 dakika TTL sonrası otomatik silinir.
    """
    import time as _t
    from engine.news_bridge import NewsEvent

    engine = get_engine()
    if not engine or not hasattr(engine, 'news_bridge'):
        return {"success": False, "error": "news_bridge bulunamadı"}

    nb = engine.news_bridge

    test_events = [
        NewsEvent(
            headline="TEST: Trump İran'a yeni yaptırımlar açıkladı — petrol fiyatları yükseldi",
            source="test",
            timestamp=_t.time() - 10,
            category="JEOPOLITIK",
            sentiment_score=-0.82,
            confidence=0.91,
            symbols=["F_XU030", "F_USDTRY"],
            is_global=True,
            event_id="test_neg_001",
        ),
        NewsEvent(
            headline="TEST: TCMB faiz kararı beklentilerin üzerinde — piyasalar olumlu",
            source="test",
            timestamp=_t.time() - 40,
            category="EKONOMIK",
            sentiment_score=0.65,
            confidence=0.78,
            symbols=["F_USDTRY"],
            is_global=False,
            event_id="test_pos_001",
        ),
    ]

    injected = 0
    for ev in test_events:
        nb._cache.add(ev)
        injected += 1

    logger.info(f"[TEST] {injected} test haber inject edildi")
    return {
        "success": True,
        "injected": injected,
        "message": f"{injected} test haber eklendi — WebSocket ile Dashboard'a iletilecek",
    }
