"""Hafif, thread-safe event bus.

Engine thread'den emit edilir, async WS thread'den dinlenir.
Kapanmış işlem gibi olayları gerçek zamanlı UI'a iletmek için kullanılır.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable

_listeners: dict[str, list[Callable]] = defaultdict(list)
_lock = threading.Lock()

# Async taraf için bekleyen olaylar (WS push loop tüketir)
_pending: list[dict[str, Any]] = []
_pending_lock = threading.Lock()


def on(event: str, callback: Callable) -> None:
    """Event dinleyici ekle."""
    with _lock:
        _listeners[event].append(callback)


def off(event: str, callback: Callable) -> None:
    """Event dinleyici kaldır."""
    with _lock:
        try:
            _listeners[event].remove(callback)
        except ValueError:
            pass


def emit(event: str, data: dict[str, Any] | None = None) -> None:
    """Event yayınla — tüm listener'ları çağır + pending kuyruğa ekle."""
    payload = {"type": event, **(data or {})}

    # Senkron listener'ları çağır
    with _lock:
        for cb in _listeners.get(event, []):
            try:
                cb(payload)
            except Exception:
                pass

    # Async taraf için kuyruğa ekle (WS broadcast)
    with _pending_lock:
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
