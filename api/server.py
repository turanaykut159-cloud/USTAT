"""ÜSTAT v5.2 API — FastAPI Sunucu.

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
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import set_engine
from api.routes import (
    account,
    events,
    health,
    hybrid_trade,
    killswitch,
    live,
    manual_trade,
    ogul_activity,
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
API_VERSION = "5.2.0"


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

        # Engine crash watchdog — thread sessizce ölürse logla
        async def _engine_watchdog():
            try:
                await engine_task
            except Exception as exc:
                logger.critical(f"Engine thread CRASHED: {exc}")

        watchdog_task = asyncio.create_task(_engine_watchdog())

        logger.info("ÜSTAT Engine başlatıldı.")

    except Exception as e:
        logger.error(f"Engine başlatma hatası: {e}")
        # Engine olmadan da API ayağa kalksın (mock/debug modu)

    yield

    # Shutdown
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


# ── FastAPI Uygulama ──────────────────────────────────────────────

app = FastAPI(
    title="ÜSTAT API",
    version=API_VERSION,
    description="VİOP Algorithmic Trading — REST & WebSocket API",
    lifespan=lifespan,
)

# CORS — Electron dev (5173) ve production
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev
        "http://localhost:3000",   # legacy
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "app://.",                 # Electron production
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
app.include_router(ustat_brain.router, prefix="/api", tags=["ustat-brain"])
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(ogul_activity.router, prefix="/api", tags=["ogul"])
app.include_router(live.router, tags=["websocket"])
app.include_router(settings.router, prefix="/api", tags=["settings"])


@app.get("/")
async def root():
    """API kök endpoint."""
    return {
        "name": "ÜSTAT API",
        "version": API_VERSION,
        "docs": "/docs",
    }
