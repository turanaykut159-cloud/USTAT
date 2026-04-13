"""MT5 Journal API — v6.0

MT5 terminal günlük (Journal) kayıtlarını sunar.

Endpoints:
    GET /api/mt5-journal          — Journal kayıtlarını getir (filtreli)
    GET /api/mt5-journal/stats    — İstatistik bilgiler
    POST /api/mt5-journal/sync    — Anlık sync tetikle
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Query

from api.deps import get_mt5_journal
from api.schemas import MT5JournalEntry, MT5JournalResponse

logger = logging.getLogger("ustat.api.mt5_journal")

router = APIRouter()


@router.get("/mt5-journal", response_model=MT5JournalResponse)
async def get_journal(
    date: str | None = Query(None, description="Tarih filtresi (YYYY-MM-DD)"),
    source: str | None = Query(None, description="Kaynak filtresi (Terminal, Trades, Network, vb.)"),
    search: str | None = Query(None, description="Mesaj arama"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """MT5 Journal kayıtlarını filtreli getir."""
    journal = get_mt5_journal()
    if journal is None:
        return MT5JournalResponse()

    entries = journal.get_entries(
        date=date,
        source=source,
        search=search,
        limit=limit,
        offset=offset,
    )

    stats = journal.get_stats()

    return MT5JournalResponse(
        entries=[MT5JournalEntry(**e) for e in entries],
        total=stats["total_entries"],
        available_dates=stats["available_dates"],
        available_sources=stats["available_sources"],
    )


@router.get("/mt5-journal/stats")
async def get_journal_stats():
    """MT5 Journal istatistikleri."""
    journal = get_mt5_journal()
    if journal is None:
        return {"total_entries": 0, "today_entries": 0, "logs_dir": "", "available_dates": [], "available_sources": []}

    return journal.get_stats()


@router.post("/mt5-journal/sync")
async def sync_journal():
    """MT5 Journal kayıtlarını anlık senkronize et."""
    journal = get_mt5_journal()
    if journal is None:
        return {"success": False, "message": "MT5 Journal modülü aktif değil", "synced": 0}

    try:
        count = journal.sync()
        return {"success": True, "message": f"{count} yeni kayıt eklendi", "synced": count}
    except Exception as e:
        logger.error("MT5 Journal sync hatası: %s", e)
        return {"success": False, "message": str(e), "synced": 0}
