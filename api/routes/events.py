"""GET /api/events — Sistem olayları (log).

Filtreleme: event_type, severity, limit.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from api.deps import get_db
from api.schemas import EventItem, EventsResponse

logger = logging.getLogger("ustat.api.routes.events")

router = APIRouter()


@router.get("/events", response_model=EventsResponse)
async def get_events(
    event_type: str | None = Query(None, description="Olay tipi filtresi"),
    severity: str | None = Query(None, description="Önem derecesi filtresi"),
    limit: int = Query(50, ge=1, le=500, description="Maks kayıt"),
):
    """Sistem olaylarını filtreli olarak döndür."""
    try:
        db = get_db()
        if not db:
            return EventsResponse()

        rows = db.get_events(event_type=event_type, severity=severity, limit=limit)
        if not rows:
            rows = []

        items = []
        for r in rows:
            try:
                items.append(EventItem(
                    id=r.get("id", 0),
                    timestamp=str(r.get("timestamp", "")),
                    type=str(r.get("type", "")),
                    severity=str(r.get("severity", "INFO")),
                    message=str(r.get("message", "")),
                    action=str(r.get("action", "")),
                ))
            except Exception:
                continue

        return EventsResponse(count=len(items), events=items)
    except Exception as exc:
        logger.exception("events endpoint HATASI: %s", exc)
        return EventsResponse()
