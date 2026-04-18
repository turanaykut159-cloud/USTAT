"""ÜSTAT Plus V6.1 API — FastAPI Sunucu.

Desktop uygulamasına REST API + WebSocket köprüsü sağlar.

Çalıştırma:
    uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

Endpoint'ler:
    GET  /api/status         — Sistem durumu
    GET  /api/account        — Hesap bilgileri
    GET  /api/positions      — Açık pozisyonlar
    GET  /api/trades         — İşlem geçmişi
    GET  /api/trades/stats   — İşlem istatistikleri
    GET  /api/risk           — Risk snapshot
    GET  /api/performance    — Performans metrikleri
    GET  /api/top5           — Top 5 kontrat
    GET  /api/health         — Sistem sağlığı metrikleri
    POST /api/trades/approve — İşlem onaylama
    POST /api/killswitch     — Kill-switch tetikleme
    WS   /ws/live            — Canlı veri akışı
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.deps import set_engine
from api.routes import (
    account,
    events,
    error_dashboard,
    health,
    hybrid_trade,
    killswitch,
    live,
    manual_trade,
    mt5_journal,
    mt5_verify,
    nabiz,
    notifications,
    ogul_activity,
    ogul_toggle,
    performance,
    positions,
    risk,
    status,
    top5,
    trades,
    ustat_brain,
    settings,
)

logger = logging.getLogger("ustat.api")

# Tek kaynak: OpenAPI ve root endpoint aynı versiyonu kullanır
API_VERSION = "6.2.0"


# ── Lifespan: Engine başlat / durdur ─────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yaşam döngüsü.

    Startup:  Engine oluştur, bağımlılıklara kaydet, arka plan thread'i başlat.
    Shutdown: Engine durdur, kaynakları temizle.
    """
    engine = None
    engine_task = None
    watchdog_task = None

    try:
        from engine.config import Config
        from engine.database import Database
        from engine.mt5_bridge import MT5Bridge
        from engine.data_pipeline import DataPipeline
        from engine.ustat import Ustat
        from engine.baba import Baba
        from engine.ogul import Ogul
        from engine.main import Engine

        config = Config()
        db = Database(config)
        mt5 = MT5Bridge(config)
        pipeline = DataPipeline(mt5, db, config)
        ustat = Ustat(config, db)
        baba = Baba(config, db, mt5)
        ogul = Ogul(config, mt5, db, baba=baba)

        engine = Engine(
            config=config, db=db, mt5=mt5,
            pipeline=pipeline, ustat=ustat,
            baba=baba, ogul=ogul,
        )

        set_engine(engine)

        # Engine'i arka plan thread'inde başlat
        loop = asyncio.get_running_loop()
        engine_task = loop.run_in_executor(None, engine.start)

        # Engine crash watchdog — thread biterse yeniden başlatma dene
        MAX_ENGINE_RESTARTS = 3
        _engine_restart_count = 0

        async def _engine_watchdog():
            nonlocal engine_task, _engine_restart_count

            while True:
                try:
                    await engine_task
                    logger.warning(
                        "Engine thread sonlandı — API açık kalacak, "
                        "engine yeniden başlatılacak."
                    )
                except Exception as exc:
                    logger.error(f"Engine thread CRASHED: {exc}")

                _engine_restart_count += 1
                if _engine_restart_count > MAX_ENGINE_RESTARTS:
                    logger.critical(
                        f"Engine {MAX_ENGINE_RESTARTS} kez yeniden başlatılamadı — "
                        f"API açık kalıyor, manuel müdahale gerekli."
                    )
                    return  # API açık kalır, engine duruyor

                logger.info(
                    f"Engine yeniden başlatılıyor "
                    f"({_engine_restart_count}/{MAX_ENGINE_RESTARTS})..."
                )
                await asyncio.sleep(10)  # 10sn bekle, sonra tekrar dene
                engine_task = loop.run_in_executor(None, engine.start)

        watchdog_task = asyncio.create_task(_engine_watchdog())

        logger.info("ÜSTAT Engine başlatıldı.")

    except Exception as e:
        logger.error(f"Engine başlatma hatası: {e}")
        # Engine olmadan da API ayağa kalksın (mock/debug modu)

    yield

    # Shutdown
    # 1. WebSocket bağlantılarını kapat (socket'ler serbest kalsın)
    try:
        from api.routes.live import shutdown_all_connections
        await shutdown_all_connections()
    except Exception as e:
        logger.warning(f"WebSocket kapatma hatası: {e}")

    # 2. Engine'i durdur
    if engine is not None:
        try:
            engine.stop("API shutdown")
            # Engine thread'inin bitmesini bekle (max 30sn)
            if engine_task is not None:
                try:
                    await asyncio.wait_for(engine_task, timeout=30)
                except asyncio.TimeoutError:
                    logger.warning("Engine thread 30s içinde durdurulamadı.")
                except Exception:
                    pass  # Engine kendi hatalarını logladı
            if watchdog_task is not None:
                watchdog_task.cancel()
            logger.info("ÜSTAT Engine durduruldu.")
        except Exception as e:
            logger.warning(f"Engine durdurma hatası: {e}")

    # 3. api.pid dosyasını temizle
    try:
        _api_pid_path = os.path.join(os.path.dirname(__file__), "..", "api.pid")
        if os.path.exists(_api_pid_path):
            os.remove(_api_pid_path)
    except Exception:
        pass


# ── FastAPI Uygulama ──────────────────────────────────────────────

app = FastAPI(
    title="ÜSTAT Plus V6.1 API",
    version=API_VERSION,
    description="VİOP Algorithmic Trading — REST & WebSocket API",
    lifespan=lifespan,
)

# CORS — pywebview + dev modları
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",  # pywebview production
        "http://localhost:8000",   # pywebview / Chrome
        "http://localhost:5173",   # Vite dev
        "http://localhost:3000",   # legacy
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "app://.",                 # Electron (eski)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Router kayıtları ─────────────────────────────────────────────
app.include_router(status.router, prefix="/api", tags=["status"])
app.include_router(account.router, prefix="/api", tags=["account"])
app.include_router(positions.router, prefix="/api", tags=["positions"])
app.include_router(trades.router, prefix="/api", tags=["trades"])
app.include_router(risk.router, prefix="/api", tags=["risk"])
app.include_router(performance.router, prefix="/api", tags=["performance"])
app.include_router(top5.router, prefix="/api", tags=["top5"])
app.include_router(killswitch.router, prefix="/api", tags=["killswitch"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(manual_trade.router, prefix="/api", tags=["manual-trade"])
app.include_router(hybrid_trade.router, prefix="/api", tags=["hybrid-trade"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(ustat_brain.router, prefix="/api", tags=["ustat-brain"])
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(ogul_activity.router, prefix="/api", tags=["ogul"])
app.include_router(ogul_toggle.router, prefix="/api", tags=["ogul-toggle"])
app.include_router(live.router, tags=["websocket"])
app.include_router(settings.router, prefix="/api", tags=["settings"])
app.include_router(mt5_verify.router, prefix="/api", tags=["mt5"])
app.include_router(error_dashboard.router, prefix="/api", tags=["errors"])
app.include_router(mt5_journal.router, prefix="/api", tags=["mt5-journal"])
app.include_router(nabiz.router, prefix="/api", tags=["nabiz"])


# ── SPA Statik Dosya Sunumu (React build) ────────────────────────
# dist/ varsa React build'i sun, yoksa API JSON dönsün

_DIST_DIR = os.path.join(os.path.dirname(__file__), "..", "desktop", "dist")


class _SPAStaticFiles(StaticFiles):
    """React Router SPA fallback — bilinmeyen path → index.html."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
            if response.status_code == 404:
                return FileResponse(os.path.join(self.directory, "index.html"))
            return response
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return FileResponse(os.path.join(self.directory, "index.html"))
            raise


if os.path.isfile(os.path.join(_DIST_DIR, "index.html")):
    app.mount("/", _SPAStaticFiles(directory=_DIST_DIR, html=True), name="spa")
    logger.info(f"SPA static files mounted: {_DIST_DIR}")
else:
    @app.get("/")
    async def root():
        """API kök endpoint (dist/ yoksa fallback)."""
        return {
            "name": "ÜSTAT Plus V6.1 API",
            "version": API_VERSION,
            "docs": "/docs",
        }
