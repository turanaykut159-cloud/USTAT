"""GET /api/mt5/verify — MT5 bağlantı doğrulama.

Electron child process'ten mt5.initialize() askıda kalma sorununu çözmek için
API server tarafında MT5 bağlantısını doğrular.

Login ekranı bu endpoint'i polling ile çağırır.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from api.deps import get_engine

logger = logging.getLogger("ustat.api.routes.mt5_verify")

router = APIRouter()


@router.get("/mt5/verify")
async def verify_mt5_connection():
    """MT5 bağlantısını doğrula.

    Engine çalışıyorsa mevcut bağlantı durumunu döndür (race condition önleme).
    Engine çalışmıyorsa (login aşaması) mt5.initialize/shutdown ile doğrula.
    """
    # Engine çalışıyorsa, process-global mt5 state'e dokunma
    engine = get_engine()
    if engine and getattr(engine, "_running", False):
        connected = getattr(engine.mt5, "_connected", False)
        if connected:
            try:
                acct = engine.mt5.get_account_info()
                return {
                    "connected": True,
                    "message": "Engine üzerinden doğrulandı",
                    "account": {
                        "login": getattr(acct, "login", None) if acct else None,
                        "server": getattr(acct, "server", None) if acct else None,
                        "balance": getattr(acct, "balance", None) if acct else None,
                        "name": getattr(acct, "name", None) if acct else None,
                    },
                }
            except Exception:
                pass
        return {"connected": False, "message": "Engine çalışıyor ama MT5 bağlı değil"}

    # Engine çalışmıyor → login aşaması, doğrudan MT5 ile doğrula
    try:
        result = await asyncio.to_thread(_verify)
        return result
    except Exception as e:
        logger.warning(f"MT5 verify hatası: {e}")
        return {"connected": False, "message": str(e)}


def _verify() -> dict:
    """Senkron MT5 doğrulama (thread'de çalışır)."""
    try:
        import MetaTrader5 as mt5

        if not mt5.initialize():
            err = mt5.last_error()
            return {"connected": False, "message": f"mt5.initialize() basarisiz: {err}"}

        info = mt5.account_info()
        if info is None:
            mt5.shutdown()
            return {"connected": False, "message": "account_info() None dondu"}

        result = {
            "connected": True,
            "message": "Baglanti basarili",
            "account": {
                "login": info.login,
                "server": info.server,
                "balance": info.balance,
                "name": info.name,
            },
        }
        mt5.shutdown()
        return result

    except Exception as e:
        return {"connected": False, "message": str(e)}
