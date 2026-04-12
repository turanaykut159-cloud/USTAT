"""Bildirim API — Persistent notification CRUD.

Endpoint'ler:
    GET  /notifications          → Bildirimleri getir (limit, unread_only)
    POST /notifications/read     → Tek bildirimi okundu yap
    POST /notifications/read-all → Tümünü okundu yap
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from api.deps import get_db

router = APIRouter()


class NotificationItem(BaseModel):
    id: int = 0
    timestamp: str = ""
    type: str = ""
    title: str = ""
    message: str = ""
    severity: str = "info"
    read: bool = False
    details: str = "{}"


class NotificationsResponse(BaseModel):
    count: int = 0
    unread_count: int = 0
    notifications: list[NotificationItem] = []


class MarkReadRequest(BaseModel):
    id: int


@router.get("/notifications", response_model=NotificationsResponse)
async def get_notifications(limit: int = 50, unread_only: bool = False):
    """Bildirimleri getir."""
    db = get_db()
    if not db:
        return NotificationsResponse()

    rows = db.get_notifications(limit=limit, unread_only=unread_only)
    items = [
        NotificationItem(
            id=r.get("id", 0),
            timestamp=r.get("timestamp", ""),
            type=r.get("type", ""),
            title=r.get("title", ""),
            message=r.get("message", ""),
            severity=r.get("severity", "info"),
            read=bool(r.get("read", 0)),
            details=r.get("details", "{}"),
        )
        for r in rows
    ]
    global_unread = db.get_unread_notification_count()
    return NotificationsResponse(count=len(items), unread_count=global_unread, notifications=items)


@router.post("/notifications/read")
async def mark_notification_read(req: MarkReadRequest):
    """Tek bildirimi okundu yap."""
    db = get_db()
    if not db:
        return {"success": False}
    db.mark_notification_read(req.id)
    return {"success": True}


@router.post("/notifications/read-all")
async def mark_all_read():
    """Tüm bildirimleri okundu yap."""
    db = get_db()
    if not db:
        return {"success": False}
    db.mark_all_notifications_read()
    return {"success": True}
