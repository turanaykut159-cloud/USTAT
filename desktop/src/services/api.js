/**
 * ÜSTAT v5.1 — Backend API çağrıları.
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
  } catch (err) {
    console.error('[ÜSTAT API] getStatus:', err?.message ?? err);
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
  } catch (err) {
    console.error('[ÜSTAT API] getAccount:', err?.message ?? err);
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
  } catch (err) {
    console.error('[ÜSTAT API] getPositions:', err?.message ?? err);
    return { count: 0, positions: [] };
  }
}

/** Tek pozisyonu kapat (ticket ile). Sadece manuel pozisyonlar için UI'da buton gösterilir. */
export async function closePosition(ticket) {
  try {
    const { data } = await client.post('/positions/close', { ticket });
    return data;
  } catch (err) {
    const msg = err?.response?.data?.detail ?? err?.message ?? err;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
}

// ── Trades ───────────────────────────────────────────────────────

export async function getTrades(params = {}) {
  try {
    const { data } = await client.get('/trades', { params });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getTrades:', err?.message ?? err);
    return { count: 0, trades: [], error: true };
  }
}

export async function getTradeStats(limit = 500) {
  try {
    const { data } = await client.get('/trades/stats', { params: { limit } });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getTradeStats:', err?.message ?? err);
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
  } catch (err) {
    console.error('[ÜSTAT API] approveTrade:', err?.message ?? err);
    return { success: false, message: 'Bağlantı hatası.' };
  }
}

export async function syncTrades(days = 90) {
  try {
    const { data } = await client.post('/trades/sync', null, { params: { days } });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] syncTrades:', err?.message ?? err);
    return { success: false, message: 'Senkronizasyon hatası.' };
  }
}

// ── Risk ─────────────────────────────────────────────────────────

export async function getRisk() {
  try {
    const { data } = await client.get('/risk');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getRisk:', err?.message ?? err);
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
  } catch (err) {
    console.error('[ÜSTAT API] getPerformance:', err?.message ?? err);
    return { total_pnl: 0, win_rate: 0, equity_curve: [] };
  }
}

// ── Top 5 ────────────────────────────────────────────────────────

export async function getTop5() {
  try {
    const { data } = await client.get('/top5');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getTop5:', err?.message ?? err);
    return { contracts: [], all_scores: {} };
  }
}

// ── Events (Sistem Log) ─────────────────────────────────────────

export async function getEvents(params = {}) {
  try {
    const { data } = await client.get('/events', { params });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getEvents:', err?.message ?? err);
    return { count: 0, events: [] };
  }
}

// ── Kontrat Reactivation ─────────────────────────────────────────

export async function reactivateSymbols() {
  try {
    const { data } = await client.post('/reactivate');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] reactivateSymbols:', err?.message ?? err);
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
  } catch (err) {
    console.error('[ÜSTAT API] activateKillSwitch:', err?.message ?? err);
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
  } catch (err) {
    console.error('[ÜSTAT API] acknowledgeKillSwitch:', err?.message ?? err);
    return { success: false, message: 'Bağlantı hatası.' };
  }
}

// ── Manuel İşlem ─────────────────────────────────────────────────

export async function checkManualTrade(symbol, direction) {
  try {
    const { data } = await client.post('/manual-trade/check', { symbol, direction });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] checkManualTrade:', err?.message ?? err);
    return { can_trade: false, reason: 'Bağlantı hatası.' };
  }
}

export async function executeManualTrade(symbol, direction, lot) {
  try {
    const { data } = await client.post('/manual-trade/execute', { symbol, direction, lot });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] executeManualTrade:', err?.message ?? err);
    return { success: false, message: 'Bağlantı hatası.' };
  }
}

export async function getManualRiskScores() {
  try {
    const { data } = await client.get('/manual-trade/risk-scores');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getManualRiskScores:', err?.message ?? err);
    return { scores: {} };
  }
}

// ── ÜSTAT Beyin (v13.0) ──────────────────────────────────────

export async function getUstatBrain(days = 90) {
  try {
    const { data } = await client.get('/ustat/brain', { params: { days } });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getUstatBrain:', err?.message ?? err);
    return {
      trade_categories: { by_result: [], by_direction: [], by_duration: [], by_regime: [], by_exit_reason: [] },
      contract_profiles: [],
      recent_decisions: [],
      regime_performance: [],
      error_attributions: [],
      next_day_analyses: [],
      strategy_pool: { current_regime: '', profiles: [] },
      regulation_suggestions: [],
    };
  }
}

// ── Hibrit İşlem Paneli ──────────────────────────────────────────

export async function checkHybridTransfer(ticket) {
  try {
    const { data } = await client.post('/hybrid/check', { ticket });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] checkHybridTransfer:', err?.message ?? err);
    return { can_transfer: false, reason: 'Bağlantı hatası.' };
  }
}

export async function transferToHybrid(ticket) {
  try {
    const { data } = await client.post('/hybrid/transfer', { ticket });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] transferToHybrid:', err?.message ?? err);
    return { success: false, message: 'Bağlantı hatası.' };
  }
}

export async function removeFromHybrid(ticket) {
  try {
    const { data } = await client.post('/hybrid/remove', { ticket });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] removeFromHybrid:', err?.message ?? err);
    return { success: false, message: 'Bağlantı hatası.' };
  }
}

export async function getHybridStatus() {
  try {
    const { data } = await client.get('/hybrid/status');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getHybridStatus:', err?.message ?? err);
    return { active_count: 0, max_count: 3, daily_pnl: 0, daily_limit: 500, positions: [] };
  }
}

export async function getHybridEvents(params = {}) {
  try {
    const { data } = await client.get('/hybrid/events', { params });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getHybridEvents:', err?.message ?? err);
    return { count: 0, events: [] };
  }
}

// ── Health (Sistem Sağlığı) ──────────────────────────────────────

export async function getHealth() {
  try {
    const { data } = await client.get('/health');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getHealth:', err?.message ?? err);
    return {
      cycle: {}, mt5: {}, orders: {},
      layers: {}, recent_events: [], system: {},
    };
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
