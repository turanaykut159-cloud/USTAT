"""GET /api/events — Sistem olayları (log).

Filtreleme: event_type, severity, limit.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from api.deps import get_db
from api.schemas import EventItem, EventsResponse

router = APIRouter()


@router.get("/events", response_model=EventsResponse)
async def get_events(
    event_type: str | None = Query(None, description="Olay tipi filtresi"),
    severity: str | None = Query(None, description="Önem derecesi filtresi"),
    limit: int = Query(50, ge=1, le=500, description="Maks kayıt"),
):
    """Sistem olaylarını filtreli olarak döndür."""
    db = get_db()
    if not db:
        return EventsResponse()

    rows = db.get_events(event_type=event_type, severity=severity, limit=limit)
    items = [
        EventItem(
            id=r.get("id", 0),
            timestamp=r.get("timestamp", ""),
            type=r.get("type", ""),
            severity=r.get("severity", "INFO"),
            message=r.get("message", ""),
            action=r.get("action", ""),
        )
        for r in rows
    ]

    return EventsResponse(count=len(items), events=items)
