/**
 * ÜSTAT v5.0 — Backend API çağrıları.
 *
 * FastAPI sunucusuyla iletişim (REST + WebSocket).
 * Tüm endpoint'ler: /api/status, /api/account, /api/positions,
 * /api/trades, /api/trades/stats, /api/risk, /api/performance,
 * /api/top5, /api/trades/approve, /api/killswitch, /ws/live
 */

import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';
const WS_BASE = 'ws://localhost:8000';

const client = axios.create({
  baseURL: API_BASE,
  timeout: 5000,
});

// ── Status ───────────────────────────────────────────────────────

export async function getStatus() {
  try {
    const { data } = await client.get('/status');
    return data;
  } catch {
    return {
      engine_running: false,
      mt5_connected: false,
      regime: 'TREND',
      regime_confidence: 0,
      risk_multiplier: 1,
      phase: 'stopped',
      kill_switch_level: 0,
      daily_trade_count: 0,
      uptime_seconds: 0,
      warnings: [],
    };
  }
}

// ── Account ──────────────────────────────────────────────────────

export async function getAccount() {
  try {
    const { data } = await client.get('/account');
    return data;
  } catch {
    return {
      balance: 0, equity: 0, margin: 0, free_margin: 0,
      floating_pnl: 0, daily_pnl: 0, margin_level: 0,
      login: 0, server: '', currency: 'TRY',
    };
  }
}

// ── Positions ────────────────────────────────────────────────────

export async function getPositions() {
  try {
    const { data } = await client.get('/positions');
    return data;
  } catch {
    return { count: 0, positions: [] };
  }
}

// ── Trades ───────────────────────────────────────────────────────

export async function getTrades(params = {}) {
  try {
    const { data } = await client.get('/trades', { params });
    return data;
  } catch {
    return { count: 0, trades: [] };
  }
}

export async function getTradeStats(limit = 500) {
  try {
    const { data } = await client.get('/trades/stats', { params: { limit } });
    return data;
  } catch {
    return { total_trades: 0, win_rate: 0, total_pnl: 0 };
  }
}

export async function approveTrade(tradeId, approvedBy = 'operator', notes = '') {
  try {
    const { data } = await client.post('/trades/approve', {
      trade_id: tradeId,
      approved_by: approvedBy,
      notes,
    });
    return data;
  } catch {
    return { success: false, message: 'Bağlantı hatası.' };
  }
}

export async function syncTrades(days = 90) {
  try {
    const { data } = await client.post('/trades/sync', null, { params: { days } });
    return data;
  } catch {
    return { success: false, message: 'Senkronizasyon hatası.' };
  }
}

// ── Risk ─────────────────────────────────────────────────────────

export async function getRisk() {
  try {
    const { data } = await client.get('/risk');
    return data;
  } catch {
    return {
      daily_pnl: 0, can_trade: true, kill_switch_level: 0,
      regime: 'TREND', risk_multiplier: 1, open_positions: 0,
    };
  }
}

// ── Performance ──────────────────────────────────────────────────

export async function getPerformance(days = 30) {
  try {
    const { data } = await client.get('/performance', { params: { days } });
    return data;
  } catch {
    return { total_pnl: 0, win_rate: 0, equity_curve: [] };
  }
}

// ── Top 5 ────────────────────────────────────────────────────────

export async function getTop5() {
  try {
    const { data } = await client.get('/top5');
    return data;
  } catch {
    return { contracts: [], all_scores: {} };
  }
}

// ── Events (Sistem Log) ─────────────────────────────────────────

export async function getEvents(params = {}) {
  try {
    const { data } = await client.get('/events', { params });
    return data;
  } catch {
    return { count: 0, events: [] };
  }
}

// ── Kontrat Reactivation ─────────────────────────────────────────

export async function reactivateSymbols() {
  try {
    const { data } = await client.post('/reactivate');
    return data;
  } catch {
    return { success: false, message: 'Bağlantı hatası.' };
  }
}

// ── Kill-Switch ──────────────────────────────────────────────────

export async function activateKillSwitch(user = 'operator') {
  try {
    const { data } = await client.post('/killswitch', {
      action: 'activate',
      user,
    });
    return data;
  } catch {
    return { success: false, message: 'Bağlantı hatası.' };
  }
}

export async function acknowledgeKillSwitch(user = 'operator') {
  try {
    const { data } = await client.post('/killswitch', {
      action: 'acknowledge',
      user,
    });
    return data;
  } catch {
    return { success: false, message: 'Bağlantı hatası.' };
  }
}

// ── Manuel İşlem ─────────────────────────────────────────────────

export async function checkManualTrade(symbol, direction) {
  try {
    const { data } = await client.post('/manual-trade/check', { symbol, direction });
    return data;
  } catch {
    return { can_trade: false, reason: 'Bağlantı hatası.' };
  }
}

export async function executeManualTrade(symbol, direction, lot) {
  try {
    const { data } = await client.post('/manual-trade/execute', { symbol, direction, lot });
    return data;
  } catch {
    return { success: false, message: 'Bağlantı hatası.' };
  }
}

// ── WebSocket ────────────────────────────────────────────────────

/**
 * Canlı veri WebSocket bağlantısı oluştur.
 *
 * @param {function} onMessage - (data: object[]) => void
 * @param {function} onError   - (error: Event) => void
 * @returns {{ ws: WebSocket, close: () => void }}
 */
export function connectLiveWS(onMessage, onError = null) {
  const ws = new WebSocket(`${WS_BASE}/ws/live`);

  ws.onmessage = (event) => {
    try {
      const messages = JSON.parse(event.data);
      onMessage(messages);
    } catch {
      // Geçersiz JSON
    }
  };

  ws.onerror = (err) => {
    if (onError) onError(err);
  };

  // Ping/pong keep-alive
  const pingInterval = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send('ping');
    }
  }, 30000);

  const close = () => {
    clearInterval(pingInterval);
    ws.close();
  };

  return { ws, close };
}
