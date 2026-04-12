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

import time
from typing import TYPE_CHECKING

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


def get_news_bridge():
    """NewsBridge (haber köprüsü) instance'ına eriş."""
    return _engine.news_bridge if _engine and hasattr(_engine, 'news_bridge') else None


def is_engine_running() -> bool:
    """Engine çalışıyor mu?"""
    if _engine is None:
        return False
    return getattr(_engine, 'is_running', False)
