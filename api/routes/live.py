"""WebSocket /ws/live — Canlı veri akışı.

Her 2 saniyede bir push:
  - tick   : Fiyat verileri (Top 5 kontrat)
  - equity : Bakiye / equity / floating PnL
  - position: Açık pozisyonlar
  - status : Rejim / kill-switch durumu

Event-driven:
  - trade_closed   : İşlem kapandığında anında bildirim
  - position_closed : Pozisyon kapanışı sync edildiğinde bildirim

Bağlantı:
  ws://localhost:8000/ws/live
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.deps import get_baba, get_db, get_engine, get_ogul, get_pipeline
from api.routes.positions import _source_for_position, _tur_for_position

logger = logging.getLogger("ustat.api.ws")

router = APIRouter()

# Aktif bağlantılar (broadcast için) — asyncio.Lock ile korunur
_active_connections: list[WebSocket] = []
_connections_lock: asyncio.Lock = asyncio.Lock()

PUSH_INTERVAL = 2.0  # saniye
EVENT_DRAIN_INTERVAL = 1.0  # saniye — event bus kontrol sıklığı

# Risk snapshot cache — sync DB sorgusunun event loop'u bloklamasını önler
_risk_snapshot_cache: dict | None = None
_risk_snapshot_ts: float = 0.0
_RISK_CACHE_TTL: float = 5.0  # saniye

# Global event drain task referansı
_event_drain_task: asyncio.Task | None = None


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    """Canlı veri WebSocket endpoint'i."""
    global _event_drain_task

    await ws.accept()
    async with _connections_lock:
        _active_connections.append(ws)
    logger.info(f"WebSocket bağlantısı açıldı. Aktif: {len(_active_connections)}")

    # İlk bağlantıda global event drain task'i başlat
    if _event_drain_task is None or _event_drain_task.done():
        _event_drain_task = asyncio.create_task(_event_drain_loop())

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
        async with _connections_lock:
            if ws in _active_connections:
                _active_connections.remove(ws)
        logger.info(f"WebSocket bağlantısı kapandı. Aktif: {len(_active_connections)}")

        # Son bağlantı kapandıysa drain task'i durdur
        if not _active_connections and _event_drain_task and not _event_drain_task.done():
            _event_drain_task.cancel()
            _event_drain_task = None


async def _event_drain_loop():
    """Event bus'tan olayları drain edip tüm bağlantılara broadcast et."""
    from engine import event_bus

    while True:
        try:
            await asyncio.sleep(EVENT_DRAIN_INTERVAL)
            events = event_bus.drain()
            for ev in events:
                await broadcast(ev)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Event drain hatası: {e}")


async def _push_loop(ws: WebSocket):
    """Her PUSH_INTERVAL saniyede veri gönder."""
    _consecutive_errors = 0
    _MAX_LOGGED_ERRORS = 5  # ilk 5 hata loglanır, sonra her 60.'da bir

    while True:
        try:
            await asyncio.sleep(PUSH_INTERVAL)
            await _send_all_updates(ws)
            _consecutive_errors = 0  # başarılı gönderimde sıfırla
        except asyncio.CancelledError:
            break
        except WebSocketDisconnect:
            break
        except Exception as e:
            _consecutive_errors += 1
            if _consecutive_errors <= _MAX_LOGGED_ERRORS or _consecutive_errors % 60 == 0:
                logger.warning(
                    f"WebSocket push hatası ({_consecutive_errors}x): {e}"
                )
            # Artan backoff: 5s → 10s → 15s → ... → max 30s
            await asyncio.sleep(min(5 * _consecutive_errors, 30))


async def _send_all_updates(ws: WebSocket):
    """Tüm veri türlerini tek seferde gönder.

    Madde 2.4: Equity ve pozisyon verisi DataPipeline cache'inden okunur,
    MT5'e doğrudan erişilmez. Tick verisi de pipeline.latest_ticks'ten gelir.
    """
    baba = get_baba()
    db = get_db()
    ogul = get_ogul()
    pipeline = get_pipeline()

    messages: list[dict] = []

    # Cache stale kontrolü — engine çalışmıyorsa veri göndermiyoruz
    cache_ok = pipeline and not pipeline.is_cache_stale()

    # ── 1. Tick verileri (Top 5 kontrat, cache'den) ──────────────
    if pipeline and ogul:
        scores = ogul.current_scores or {}
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
                    "time": tick.timestamp if hasattr(tick, 'timestamp') else "",
                })

    # ── 2. Equity güncellemesi (cache'den) ───────────────────────
    if cache_ok and pipeline.latest_account:
        info = pipeline.latest_account
        daily_pnl = 0.0
        if db:
            global _risk_snapshot_cache, _risk_snapshot_ts
            now = time.time()
            if _risk_snapshot_cache is None or (now - _risk_snapshot_ts) > _RISK_CACHE_TTL:
                try:
                    _risk_snapshot_cache = await asyncio.to_thread(db.get_latest_risk_snapshot)
                    _risk_snapshot_ts = now
                except Exception as exc:
                    logger.warning(f"Risk snapshot cache güncelleme hatası: {exc}")
            if _risk_snapshot_cache:
                daily_pnl = _risk_snapshot_cache.get("daily_pnl", 0.0)

        messages.append({
            "type": "equity",
            "equity": info.equity,
            "balance": info.balance,
            "floating_pnl": info.equity - info.balance,
            "daily_pnl": daily_pnl,
            "margin": info.margin,
            "free_margin": info.free_margin,
            "ts": time.time(),
        })

    # ── 3. Pozisyon güncellemesi (cache'den, strateji OĞUL'dan) ───
    if cache_ok and pipeline.latest_positions is not None:
        ogul = get_ogul()
        engine = get_engine()
        # Hibrit ticket seti — positions.py ile tutarlı tür sınıflandırması
        from api.deps import get_h_engine as _get_h_engine
        _h_engine = _get_h_engine()
        _hybrid_tickets: set = set()
        if _h_engine and getattr(_h_engine, "hybrid_positions", None):
            _hybrid_tickets = set(_h_engine.hybrid_positions.keys())
        pos_list = []
        for p in pipeline.latest_positions:
            _type = p.get("type", -1)
            direction = "BUY" if _type == 0 or _type == "BUY" else "SELL"
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

            profit = p.get("profit", 0.0)
            swap = p.get("swap", 0.0)
            ticket = p.get("ticket", 0)
            symbol = p.get("symbol", "")
            strategy = "bilinmiyor"
            tp1_hit = False
            breakeven_hit = False
            cost_averaged = False
            peak_profit = 0.0
            voting_score = 0

            # Önce ManuelMotor kontrol (manuel + MT5 pozisyonlar)
            _mm = engine.manuel_motor if engine else None
            if _mm and getattr(_mm, "active_trades", None):
                for _sym, trade in _mm.active_trades.items():
                    if getattr(trade, "ticket", 0) == ticket and _sym == symbol:
                        strategy = "manual"
                        break

            # Sonra OĞUL kontrol (otomatik pozisyonlar)
            if strategy == "bilinmiyor" and ogul and getattr(ogul, "active_trades", None):
                for _sym, trade in ogul.active_trades.items():
                    if getattr(trade, "ticket", 0) == ticket and _sym == symbol:
                        strategy = getattr(trade, "strategy", "") or "bilinmiyor"
                        tp1_hit = getattr(trade, "tp1_hit", False)
                        breakeven_hit = getattr(trade, "breakeven_hit", False)
                        cost_averaged = getattr(trade, "cost_averaged", False)
                        peak_profit = getattr(trade, "peak_profit", 0.0)
                        voting_score = getattr(trade, "voting_score", 0)
                        break

            # source: DB-tabanlı çözümleme (positions.py ile AYNI fonksiyon)
            source = _source_for_position(ticket, symbol, _mm, db)

            # tur: positions.py ile AYNI fonksiyon
            tur = _tur_for_position(ticket, strategy, _hybrid_tickets, source)

            pos_list.append({
                "ticket": ticket,
                "symbol": symbol,
                "direction": direction,
                "volume": p.get("volume", 0.0),
                "entry_price": p.get("price_open", 0.0),
                "current_price": p.get("price_current", 0.0),
                "sl": p.get("sl", 0.0),
                "tp": p.get("tp", 0.0),
                "pnl": profit + swap,
                "swap": swap,
                "open_time": open_time,
                "strategy": strategy,
                "tur": tur,
                "tp1_hit": tp1_hit,
                "breakeven_hit": breakeven_hit,
                "cost_averaged": cost_averaged,
                "peak_profit": round(peak_profit, 2),
                "voting_score": voting_score,
            })

        messages.append({
            "type": "position",
            "positions": pos_list,
        })

    # ── 4. Durum güncellemesi ─────────────────────────────────────
    if baba:
        regime = ""
        regime_confidence = 0.0
        can_trade = True
        risk_multiplier = 1.0

        if baba.current_regime:
            regime = baba.current_regime.regime_type.value
            regime_confidence = getattr(baba.current_regime, "confidence", 0.0)

        engine = get_engine()
        if engine and hasattr(engine, 'risk_params'):
            try:
                verdict = baba.check_risk_limits(engine.risk_params)
                can_trade = verdict.can_trade
            except Exception as exc:
                can_trade = False
                logger.warning(f"Risk check hatası — can_trade=False: {exc}")
            risk_multiplier = getattr(engine.risk_params, "risk_multiplier", 1.0) if hasattr(engine, "risk_params") else 1.0

        messages.append({
            "type": "status",
            "regime": regime,
            "regime_confidence": regime_confidence,
            "kill_switch_level": baba.kill_switch_level,
            "can_trade": can_trade,
            "engine_running": True,
            "risk_multiplier": risk_multiplier,
            # OĞUL AÇIK/KAPALI durumunu WS push'a ekle — TopBar (REST 2sn) ile
            # AutoTrading (WS 2sn) arasındaki senkron kopukluğunu kapatır.
            "ogul_enabled": bool(getattr(ogul, "ogul_enabled", False)) if ogul else False,
        })

    # ── 5. Hibrit pozisyon güncellemesi ─────────────────────────
    from api.deps import get_h_engine
    h_engine = get_h_engine()
    if h_engine and h_engine.hybrid_positions:
        h_list = []
        for hp in h_engine.hybrid_positions.values():
            current_price = 0.0
            pnl = 0.0
            swap = 0.0
            if pipeline and pipeline.latest_positions:
                for p in pipeline.latest_positions:
                    if p.get("ticket") == hp.ticket:
                        current_price = p.get("price_current", 0.0)
                        pnl = p.get("profit", 0.0) + p.get("swap", 0.0)
                        swap = p.get("swap", 0.0)
                        break
            h_list.append({
                "ticket": hp.ticket,
                "symbol": hp.symbol,
                "direction": hp.direction,
                "volume": hp.volume,
                "entry_price": hp.entry_price,
                "current_price": current_price,
                "entry_atr": hp.entry_atr,
                "initial_sl": hp.initial_sl,
                "initial_tp": hp.initial_tp,
                "current_sl": hp.current_sl,
                "current_tp": hp.current_tp,
                "pnl": pnl,
                "swap": swap,
                "breakeven_hit": hp.breakeven_hit,
                "trailing_active": hp.trailing_active,
                "state": hp.state,
            })
        messages.append({
            "type": "hybrid",
            "positions": h_list,
            "daily_pnl": h_engine._daily_hybrid_pnl,
            "daily_limit": h_engine._config_daily_limit,
        })

    # ── 6. Haber güncellemesi (v5.7.1 — NewsBridge) ─────────────
    engine = get_engine()
    if engine and hasattr(engine, 'news_bridge') and engine.news_bridge.enabled:
        nb = engine.news_bridge
        active_events = nb.get_active_events()
        worst = nb.get_worst_event()
        best = nb.get_best_event()
        messages.append({
            "type": "news",
            "active_count": len(active_events),
            "worst_sentiment": round(worst.sentiment_score, 3) if worst else None,
            "worst_severity": worst.severity if worst else None,
            "worst_headline": worst.headline[:80] if worst else None,
            "best_sentiment": round(best.sentiment_score, 3) if best else None,
            "best_headline": best.headline[:80] if best else None,
            "events": [e.to_dict() for e in active_events[:10]],  # Max 10 haber
        })

    # ── Hepsini tek JSON olarak gönder ────────────────────────────
    if messages:
        payload = json.dumps(messages, default=str)
        await ws.send_text(payload)


async def shutdown_all_connections() -> None:
    """Tüm aktif WebSocket bağlantılarını kapat (graceful shutdown).

    api/server.py lifespan shutdown'ından çağrılır. Açık bağlantılar
    kapatılmazsa uvicorn process'i socket'leri bırakmaz ve port
    TIME_WAIT durumunda kalır.
    """
    global _event_drain_task

    # Event drain task'i durdur
    if _event_drain_task and not _event_drain_task.done():
        _event_drain_task.cancel()
        _event_drain_task = None

    # Tüm bağlantıları kapat
    async with _connections_lock:
        snapshot = list(_active_connections)
        _active_connections.clear()

    closed_count = 0
    for ws in snapshot:
        try:
            await ws.close(code=1001, reason="Server shutdown")
            closed_count += 1
        except Exception:
            pass  # Zaten kopmuş olabilir

    if closed_count > 0:
        logger.info(f"Shutdown: {closed_count} WebSocket bağlantısı kapatıldı")


async def broadcast(message: dict) -> None:
    """Tüm aktif bağlantılara mesaj gönder (engine tarafından çağrılabilir)."""
    if not _active_connections:
        return

    text = json.dumps([message], default=str)
    disconnected: list[WebSocket] = []

    # Snapshot alarak iterate et — lock altında kopya
    async with _connections_lock:
        snapshot = list(_active_connections)

    for ws in snapshot:
        try:
            await ws.send_text(text)
        except Exception as exc:
            logger.debug(f"WebSocket send hatası, bağlantı kaldırılıyor: {exc}")
            disconnected.append(ws)

    if disconnected:
        async with _connections_lock:
            for ws in disconnected:
                if ws in _active_connections:
                    _active_connections.remove(ws)
