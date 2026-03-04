"""WebSocket /ws/live — Canlı veri akışı.

Her 2 saniyede bir push:
  - tick   : Fiyat verileri (Top 5 kontrat)
  - equity : Bakiye / equity / floating PnL
  - position: Açık pozisyonlar
  - status : Rejim / kill-switch durumu

Bağlantı:
  ws://localhost:8000/ws/live
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.deps import get_baba, get_db, get_engine, get_pipeline, get_ustat

logger = logging.getLogger("ustat.api.ws")

router = APIRouter()

# Aktif bağlantılar (broadcast için)
_active_connections: list[WebSocket] = []

PUSH_INTERVAL = 2.0  # saniye


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    """Canlı veri WebSocket endpoint'i."""
    await ws.accept()
    _active_connections.append(ws)
    logger.info(f"WebSocket bağlantısı açıldı. Aktif: {len(_active_connections)}")

    try:
        # Arka plan push task'i
        push_task = asyncio.create_task(_push_loop(ws))

        # İstemciden gelen mesajları dinle (ping/pong, özel komutlar)
        while True:
            try:
                data = await ws.receive_text()
                # İstemci "ping" gönderirse "pong" cevabı ver
                if data.strip().lower() == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except WebSocketDisconnect:
                break
            except Exception:
                break

    finally:
        push_task.cancel()
        if ws in _active_connections:
            _active_connections.remove(ws)
        logger.info(f"WebSocket bağlantısı kapandı. Aktif: {len(_active_connections)}")


async def _push_loop(ws: WebSocket):
    """Her PUSH_INTERVAL saniyede veri gönder."""
    while True:
        try:
            await asyncio.sleep(PUSH_INTERVAL)
            await _send_all_updates(ws)
        except asyncio.CancelledError:
            break
        except WebSocketDisconnect:
            break
        except Exception as e:
            logger.warning(f"WebSocket push hatası: {e}")
            await asyncio.sleep(5)  # Hata sonrası kısa bekleme


async def _send_all_updates(ws: WebSocket):
    """Tüm veri türlerini tek seferde gönder.

    Madde 2.4: Equity ve pozisyon verisi DataPipeline cache'inden okunur,
    MT5'e doğrudan erişilmez. Tick verisi de pipeline.latest_ticks'ten gelir.
    """
    baba = get_baba()
    db = get_db()
    ustat = get_ustat()
    pipeline = get_pipeline()

    messages: list[dict] = []

    # Cache stale kontrolü — engine çalışmıyorsa veri göndermiyoruz
    cache_ok = pipeline and not pipeline.is_cache_stale()

    # ── 1. Tick verileri (Top 5 kontrat, cache'den) ──────────────
    if pipeline and ustat:
        scores = ustat.current_scores or {}
        top_symbols = sorted(scores, key=scores.get, reverse=True)[:5]

        for symbol in top_symbols:
            tick = pipeline.latest_ticks.get(symbol)
            if tick:
                messages.append({
                    "type": "tick",
                    "symbol": tick.symbol,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "spread": tick.spread,
                    "time": tick.time.isoformat() if isinstance(tick.time, datetime) else str(tick.time),
                })

    # ── 2. Equity güncellemesi (cache'den) ───────────────────────
    if cache_ok and pipeline.latest_account:
        info = pipeline.latest_account
        daily_pnl = 0.0
        if db:
            snap = db.get_latest_risk_snapshot()
            if snap:
                daily_pnl = snap.get("daily_pnl", 0.0)

        messages.append({
            "type": "equity",
            "equity": info.equity,
            "balance": info.balance,
            "floating_pnl": info.equity - info.balance,
            "daily_pnl": daily_pnl,
        })

    # ── 3. Pozisyon güncellemesi (cache'den) ─────────────────────
    if cache_ok and pipeline.latest_positions is not None:
        pos_list = []
        for p in pipeline.latest_positions:
            direction = "BUY" if p.get("type", -1) == 0 else "SELL"
            open_time = ""
            t = p.get("time")
            if t:
                try:
                    open_time = (
                        datetime.fromtimestamp(t).isoformat()
                        if isinstance(t, (int, float))
                        else str(t)
                    )
                except (ValueError, OSError):
                    open_time = str(t)

            pos_list.append({
                "ticket": p.get("ticket", 0),
                "symbol": p.get("symbol", ""),
                "direction": direction,
                "volume": p.get("volume", 0.0),
                "entry_price": p.get("price_open", 0.0),
                "current_price": p.get("price_current", 0.0),
                "sl": p.get("sl", 0.0),
                "tp": p.get("tp", 0.0),
                "pnl": p.get("profit", 0.0),
                "open_time": open_time,
            })

        messages.append({
            "type": "position",
            "positions": pos_list,
        })

    # ── 4. Durum güncellemesi ─────────────────────────────────────
    if baba:
        regime = ""
        can_trade = True

        if baba.current_regime:
            regime = baba.current_regime.regime_type.value

        engine = get_engine()
        if engine and hasattr(engine, 'risk_params'):
            try:
                verdict = baba.check_risk_limits(engine.risk_params)
                can_trade = verdict.can_trade
            except Exception:
                pass

        messages.append({
            "type": "status",
            "regime": regime,
            "kill_switch_level": baba._kill_switch_level,
            "can_trade": can_trade,
        })

    # ── Hepsini tek JSON olarak gönder ────────────────────────────
    if messages:
        payload = json.dumps(messages, default=str)
        await ws.send_text(payload)


async def broadcast(message: dict) -> None:
    """Tüm aktif bağlantılara mesaj gönder (engine tarafından çağrılabilir)."""
    if not _active_connections:
        return

    text = json.dumps(message, default=str)
    disconnected: list[WebSocket] = []

    for ws in _active_connections:
        try:
            await ws.send_text(text)
        except Exception:
            disconnected.append(ws)

    for ws in disconnected:
        _active_connections.remove(ws)
