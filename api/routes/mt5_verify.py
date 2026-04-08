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


@router.get("/mt5/saved-credentials")
async def get_saved_credentials():
    """Kayitli MT5 credentials (Windows Credential Manager)."""
    try:
        import json
        import keyring
        raw = keyring.get_password("ustat-mt5", "credentials")
        if raw:
            data = json.loads(raw)
            return {
                "hasSaved": True,
                "server": data.get("server", ""),
                "login": data.get("login", ""),
                "passwordMask": "******",
            }
    except Exception:
        pass
    return {"hasSaved": False}


def _verify() -> dict:
    """Senkron MT5 doğrulama (thread'de çalışır).

    ╔══════════════════════════════════════════════════════════════╗
    ║  ANAYASA Kural 4.15 — MT5 Başlatma Sorumluluğu Koruması     ║
    ║                                                              ║
    ║  mt5.initialize() çağrılmadan ÖNCE terminal64.exe process    ║
    ║  kontrolü yapılır. MT5 çalışmıyorsa initialize() ÇAĞRILMAZ. ║
    ║  MT5 açma sorumluluğu SADECE Electron'dadır.                 ║
    ╚══════════════════════════════════════════════════════════════╝
    """
    try:
        # ── Anayasa Kural 4.15: MT5 process kontrolü ──
        # mt5.initialize() registry'den MT5'i otomatik açar.
        # Bu endpoint sadece DOĞRULAMA yapmalı, MT5'i AÇMAMALI.
        import subprocess as _sp
        try:
            _result = _sp.run(
                ['tasklist', '/FI', 'IMAGENAME eq terminal64.exe', '/FO', 'CSV', '/NH'],
                capture_output=True, text=True, timeout=5,
                creationflags=0x08000000,
            )
            if 'terminal64.exe' not in _result.stdout.lower():
                return {"connected": False, "message": "MT5 process calismiyorr"}
        except Exception:
            return {"connected": False, "message": "MT5 process kontrol hatasi"}

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
