"""ÜSTAT API — Bağımlılık yönetimi (Dependency Injection).

Engine bileşenlerine (Database, MT5Bridge, Baba, Ustat, Engine)
erişim sağlar. FastAPI Depends() ile route'lara enjekte edilir.

Kullanım:
    from api.deps import get_db, get_engine
    @router.get("/status")
    async def status(db=Depends(get_db)):
        ...
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from fastapi import Header, HTTPException, Request

if TYPE_CHECKING:
    from engine.baba import Baba
    from engine.data_pipeline import DataPipeline
    from engine.database import Database
    from engine.h_engine import HEngine
    from engine.main import Engine
    from engine.manuel_motor import ManuelMotor
    from engine.mt5_bridge import MT5Bridge
    from engine.ogul import Ogul
    from engine.ustat import Ustat

# #261 OP-K: Localhost IP allowlist (KARAR #14 localhost+token)
_LOCAL_IPS: set[str] = {"127.0.0.1", "localhost", "::1"}

# ── Global engine referansları ────────────────────────────────────
# server.py lifespan'da set edilir.
_engine: Engine | None = None
_start_time: float = 0.0


def set_engine(engine: Engine) -> None:
    """Engine referansını kaydet (lifespan'da çağrılır)."""
    global _engine, _start_time
    _engine = engine
    _start_time = time.time()


def get_engine() -> Engine | None:
    """Engine instance'ına eriş."""
    return _engine


def get_db() -> Database | None:
    """Database instance'ına eriş."""
    return _engine.db if _engine else None


def get_mt5() -> MT5Bridge | None:
    """MT5Bridge instance'ına eriş."""
    return _engine.mt5 if _engine else None


def get_baba() -> Baba | None:
    """Baba (risk yöneticisi) instance'ına eriş."""
    return _engine.baba if _engine else None


def get_ustat() -> Ustat | None:
    """Ustat (strateji yöneticisi) instance'ına eriş."""
    return _engine.ustat if _engine else None


def get_ogul() -> Ogul | None:
    """Ogul (sinyal üretici) instance'ına eriş."""
    return _engine.ogul if _engine else None


def get_pipeline() -> DataPipeline | None:
    """DataPipeline instance'ına eriş."""
    return _engine.pipeline if _engine else None


def get_h_engine() -> HEngine | None:
    """HEngine (hibrit motor) instance'ına eriş."""
    return _engine.h_engine if _engine else None


def get_manuel_motor() -> ManuelMotor | None:
    """ManuelMotor (bağımsız manuel işlem motoru) instance'ına eriş."""
    return _engine.manuel_motor if _engine else None


def get_uptime() -> int:
    """Çalışma süresi (saniye)."""
    if _start_time == 0.0:
        return 0
    return int(time.time() - _start_time)


def get_mt5_journal():
    """MT5Journal instance'ına eriş."""
    return _engine.mt5_journal if _engine and hasattr(_engine, 'mt5_journal') else None


def is_engine_running() -> bool:
    """Engine çalışıyor mu?"""
    if _engine is None:
        return False
    return getattr(_engine, 'is_running', False)


# ════════════════════════════════════════════════════════════════════
#  #261 OP-K (KARAR #14): AUTHORIZATION GUARD
# ════════════════════════════════════════════════════════════════════

def require_localhost_and_token(
    request: Request,
    x_ustat_token: str | None = Header(None, alias="X-USTAT-TOKEN"),
) -> None:
    """Kritik endpoint'lere localhost + opsiyonel token koruması.

    Politika (KARAR #14):
      - IP allowlist: 127.0.0.1 / ::1 / localhost. Harici → 403.
      - Token opsiyonel: `config/default.json::api.auth_token` (veya
        `USTAT_API_TOKEN` env) ayarlıysa `X-USTAT-TOKEN` header eşleşmeli
        → aksi halde 401. Token boşsa sadece localhost yeterli.

    Kullanım:
        @router.post("/kritik", dependencies=[Depends(require_localhost_and_token)])

    Raises:
        HTTPException 403 — harici IP, 401 — token eşleşmedi.
    """
    # 1. Localhost kontrolü
    client_ip = request.client.host if request.client else None
    if client_ip not in _LOCAL_IPS:
        raise HTTPException(
            status_code=403,
            detail=f"Yalnizca localhost. Gelen IP: {client_ip}",
        )

    # 2. Token kontrolü (opsiyonel)
    expected = ""
    cfg = _engine.config if _engine is not None else None
    if cfg is not None:
        try:
            expected = (cfg.get("api.auth_token", "") or "").strip()
        except Exception:
            expected = ""
    if not expected:
        expected = os.environ.get("USTAT_API_TOKEN", "").strip()
    if not expected:
        return  # Token set edilmedi → sadece localhost yeterli

    if x_ustat_token != expected:
        raise HTTPException(
            status_code=401,
            detail="Gecersiz veya eksik X-USTAT-TOKEN header",
        )


# ════════════════════════════════════════════════════════════════════
#  #267 OP-K idempotency-Key header desteği (KARAR #14 uzantısı)
# ════════════════════════════════════════════════════════════════════

# Idempotency cache: {key: (response_dict, timestamp)} — 60sn TTL
_idempotency_cache: dict[str, tuple[dict, float]] = {}
_IDEMPOTENCY_TTL_SEC: float = 60.0


def check_idempotency(
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> str | None:
    """Idempotency-Key header ile aynı istek tekrar gönderilirse cached döner.

    Kullanım pattern (route içinde):
        key = check_idempotency(request_header)
        if key:
            cached = get_idempotent_response(key)
            if cached:
                return cached
        # ... iş yap ...
        store_idempotent_response(key, result) if key

    Returns:
        Normalize edilmiş key (string) veya None (header yoksa).
    """
    if not idempotency_key:
        return None
    return idempotency_key.strip()[:128]  # Max 128 char, trimmed


def get_idempotent_response(key: str | None) -> dict | None:
    """Cache'de aynı key varsa (ve TTL geçmemişse) response döndür."""
    if not key or key not in _idempotency_cache:
        return None
    response, ts = _idempotency_cache[key]
    if (time.time() - ts) > _IDEMPOTENCY_TTL_SEC:
        _idempotency_cache.pop(key, None)
        return None
    return response


def store_idempotent_response(key: str | None, response: dict) -> None:
    """Response'u cache'e al (başarı sonrası çağrılır)."""
    if not key or not isinstance(response, dict):
        return
    # Cache temizlik (eski girişleri at)
    now = time.time()
    expired = [k for k, (_, t) in _idempotency_cache.items() if (now - t) > _IDEMPOTENCY_TTL_SEC]
    for k in expired:
        _idempotency_cache.pop(k, None)
    _idempotency_cache[key] = (response, now)
