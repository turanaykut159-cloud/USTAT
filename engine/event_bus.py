"""Hafif, thread-safe event bus.

Engine thread'den emit edilir, async WS thread'den dinlenir.
Kapanmış işlem gibi olayları gerçek zamanlı UI'a iletmek için kullanılır.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable

_logger = logging.getLogger("ustat.event_bus")

_listeners: dict[str, list[Callable]] = defaultdict(list)
_lock = threading.Lock()

# Async taraf için bekleyen olaylar (WS push loop tüketir)
_pending: list[dict[str, Any]] = []
_pending_lock = threading.Lock()

# Backpressure: maksimum bekleyen event sayısı
_MAX_PENDING = 500


def emit(event: str, data: dict[str, Any] | None = None) -> None:
    """Event yayınla — tüm listener'ları çağır + pending kuyruğa ekle.

    Dup-key koruması (Widget Denetimi B-finding): Eski versiyon outer
    event'i önce yazıp inner data'yı spread ediyordu — iç ``data`` sözlüğünde
    ``type`` anahtarı varsa (h_engine bildirim alt tipleri gibi ``hybrid_eod``,
    ``hybrid_direction_flip``, ``hybrid_daily_reset``), dict spread iç
    ``type``'ı dış ``event``'in üstüne yazıyordu. Sonuç: payload
    inner type ile çıkıyor, Dashboard'daki notification WS branch'i hiçbir
    zaman eşleşmiyor, bildirim drawer'a düşmüyordu (ölü kod).

    Yeni mantık: İç ``data``'da ``type`` varsa ``notif_type`` olarak taşınır
    (Dashboard `msg.notif_type || msg.type` zaten okuyor), dış ``event`` her
    zaman ``type`` olarak yazılır. Mevcut ``notif_type`` override EDİLMEZ.
    """
    payload: dict[str, Any] = dict(data or {})
    if "type" in payload:
        inner_type = payload.pop("type")
        payload.setdefault("notif_type", inner_type)
    payload["type"] = event

    # Senkron listener'ları çağır
    with _lock:
        for cb in _listeners.get(event, []):
            try:
                cb(payload)
            except Exception as exc:
                _logger.error(
                    f"Event listener hatası [{event}]: {exc}"
                )

    # Async taraf için kuyruğa ekle (WS broadcast)
    with _pending_lock:
        if len(_pending) >= _MAX_PENDING:
            # Backpressure: en eski event'leri at
            dropped = len(_pending) - _MAX_PENDING + 1
            del _pending[:dropped]
            _logger.warning(
                f"Event bus backpressure: {dropped} eski event silindi "
                f"(kuyruk limiti: {_MAX_PENDING})"
            )
        _pending.append(payload)


def drain() -> list[dict[str, Any]]:
    """Bekleyen tüm olayları al ve kuyruğu temizle.

    WS push loop tarafından periyodik olarak çağrılır.
    """
    with _pending_lock:
        if not _pending:
            return []
        events = _pending.copy()
        _pending.clear()
        return events
