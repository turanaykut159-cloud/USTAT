/**
 * ÜSTAT v5.7 — Backend API çağrıları.
 *
 * FastAPI sunucusuyla iletişim (REST + WebSocket).
 * Tüm endpoint'ler: /api/status, /api/account, /api/positions,
 * /api/trades, /api/trades/stats, /api/risk, /api/performance,
 * /api/top5, /api/trades/approve, /api/killswitch, /ws/live
 */

import axios from 'axios';

const API_BASE = '/api';
const WS_BASE = `ws://${window.location.host}`;

/**
 * İstatistik hesaplamalarının başlangıç tarihi (fallback).
 *
 * Widget Denetimi A7 — Tek kaynak: backend /api/settings/stats-baseline
 * endpoint'i. Aşağıdaki sabit yalnızca endpoint okunamadığında (erken
 * mount, network hatası, servis yok) fallback olarak kullanılır. Yeni
 * bileşenler `STATS_BASELINE` yerine `getStatsBaseline()` helper'ı
 * kullanmalı ve etkin değeri state'te tutmalıdır.
 */
export const STATS_BASELINE = '2026-02-01';

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
      // P1-B (2026-04-13): Fail-closed — hata durumunda "her şey yolunda"
      // sinyali vermiyoruz. Tüketiciler _stale=true rozetiyle uyarı gösterir.
      // A5: Version fallback hâlâ mevcut (TopBar/Settings/LockScreen kırılmaz).
      version: '6.0.0',
      engine_running: false,
      mt5_connected: false,
      regime: 'UNKNOWN',
      regime_confidence: 0,
      risk_multiplier: 0,
      phase: 'stopped',
      kill_switch_level: 0,
      daily_trade_count: 0,
      uptime_seconds: 0,
      warnings: ['API erişilemiyor — veriler bilinmiyor'],
      _stale: true,
      _error: err?.message ?? 'unknown',
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

export async function getTradeStats(limit = 500, since = STATS_BASELINE) {
  try {
    const { data } = await client.get('/trades/stats', { params: { limit, since } });
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
      // P1-B (2026-04-13): Fail-closed — can_trade=false, risk_multiplier=0.
      // A18: max_open_positions güvenli fallback (5) korunur (UI "n/X" kırılmasın).
      daily_pnl: 0,
      can_trade: false,
      kill_switch_level: 0,
      regime: 'UNKNOWN',
      risk_multiplier: 0,
      open_positions: 0,
      max_open_positions: 5,
      _stale: true,
      _error: err?.message ?? 'unknown',
    };
  }
}

// ── Settings — Risk Baseline ──────────────────────────────────────

export async function getRiskBaseline() {
  try {
    const { data } = await client.get('/settings/risk-baseline');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getRiskBaseline:', err?.message ?? err);
    return { baseline_date: '', source: 'error' };
  }
}

export async function updateRiskBaseline(newDate) {
  try {
    const { data } = await client.post('/settings/risk-baseline', { new_date: newDate });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] updateRiskBaseline:', err?.message ?? err);
    return { success: false, message: 'API hatası.' };
  }
}

export async function getNotificationPrefs() {
  try {
    const { data } = await client.get('/settings/notification-prefs');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getNotificationPrefs:', err?.message ?? err);
    return null;
  }
}

export async function updateNotificationPrefs(prefs) {
  try {
    const { data } = await client.post('/settings/notification-prefs', prefs);
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] updateNotificationPrefs:', err?.message ?? err);
    return { success: false, prefs };
  }
}

// ── Settings — Session Hours (Widget Denetimi A17) ───────────────
// Backend config/default.json::session blok'undan BIST VİOP seans
// saatlerini oku. ErrorTracker (EOD geri sayım) ve Performance
// heatmap (9-18 saat aralığı) bu endpoint'ten hardcoded saatleri
// alır. Hata durumunda güvenli default'la fallback — UI asla kırılmaz.
export async function getSession() {
  try {
    const { data } = await client.get('/settings/session');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getSession:', err?.message ?? err);
    return {
      market_open: '09:30',
      market_close: '18:15',
      eod_close: '17:45',
      source: 'error',
    };
  }
}

// ── Settings — Stats Baseline (Widget Denetimi A7) ───────────────
// Backend config/default.json::risk.stats_baseline_date ve
// risk.baseline_date değerlerini birlikte döndürür. Performance,
// TradeHistory ve Dashboard istatistik kartları bu endpoint'ten
// aktif baseline'ı çeker; hem getTrades çağrılarında since parametresi
// olarak kullanılır, hem de UI'da küçük bir etiketle gösterilir.
// Hata durumunda STATS_BASELINE fallback'i döner — UI asla kırılmaz.
export async function getStatsBaseline() {
  try {
    const { data } = await client.get('/settings/stats-baseline');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getStatsBaseline:', err?.message ?? err);
    return {
      stats_baseline: STATS_BASELINE,
      risk_baseline: '',
      stats_source: 'error',
      risk_source: 'error',
    };
  }
}

// ── Settings — UI Prefs (Widget Denetimi A19 / H5) ───────────────
// Backend config/default.json::ui blok'undan UI-layer sabitlerini oku.
// Şu an sadece kill_hold_ms (SideNav kill-switch basılı tutma süresi)
// alanını içerir. Hata durumunda güvenli default'la fallback —
// kill-switch koruması asla kırılmaz (2000 ms = 2 saniye).
export async function getUiPrefs() {
  try {
    const { data } = await client.get('/settings/ui-prefs');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getUiPrefs:', err?.message ?? err);
    return {
      kill_hold_ms: 2000,
      source: 'error',
    };
  }
}

// ── Settings — Watchlist (Widget Denetimi A-H3) ──────────────────
// Backend engine/mt5_bridge.py::WATCHED_SYMBOLS canonical listesinden
// izlenen VİOP kontratlarını oku. Hardcode SYMBOLS dizisi drift riskini
// ortadan kaldırır — yeni kontrat eklendiğinde tek yerden (bridge)
// güncelleme yapılır. Hata durumunda 15 VİOP kontratı fallback devrede,
// ManualTrade dropdown'u asla boş gösterilmez.
export async function getWatchlistSymbols() {
  try {
    const { data } = await client.get('/settings/watchlist');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getWatchlistSymbols:', err?.message ?? err);
    return {
      symbols: [
        'F_THYAO', 'F_AKBNK', 'F_ASELS', 'F_TCELL', 'F_HALKB',
        'F_PGSUS', 'F_GUBRF', 'F_EKGYO', 'F_SOKM', 'F_TKFEN',
        'F_OYAKC', 'F_BRSAN', 'F_AKSEN', 'F_ASTOR', 'F_KONTR',
      ],
      source: 'error',
    };
  }
}

/**
 * Lot giriş sınırlarını döndür (Widget Denetimi H4).
 * Canonical kaynak: config.engine.max_lot_per_contract.
 * Frontend Manuel İşlem lot input bu fonksiyonu tüketir, hardcoded
 * min/max/step kalıbını ortadan kaldırır.
 */
export async function getTradingLimits() {
  try {
    const { data } = await client.get('/settings/trading-limits');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getTradingLimits:', err?.message ?? err);
    return {
      lot_min: 1.0,
      lot_max: 1.0,
      lot_step: 1.0,
      source: 'error',
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

// ── OĞUL Aktivite ────────────────────────────────────────────────

export async function getOgulActivity() {
  try {
    const { data } = await client.get('/ogul/activity');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getOgulActivity:', err?.message ?? err);
    return { signals: [], unopened: [], scan_symbols: 0, signal_count: 0, unopened_count: 0 };
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

// ── OĞUL Motor Toggle ───────────────────────────────────────────

export async function getOgulToggle() {
  try {
    const { data } = await client.get('/ogul-toggle');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getOgulToggle:', err?.message ?? err);
    return { success: false, enabled: false, has_positions: false, message: 'Bağlantı hatası.' };
  }
}

export async function setOgulToggle(action) {
  try {
    const { data } = await client.post('/ogul-toggle', { action });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] setOgulToggle:', err?.message ?? err);
    return { success: false, enabled: false, has_positions: false, message: 'Bağlantı hatası.' };
  }
}

// ── MT5 Journal ──────────────────────────────────────────────────

export async function getMT5Journal({ date, source, search, limit = 500, offset = 0 } = {}) {
  try {
    const params = { limit, offset };
    if (date) params.date = date;
    if (source) params.source = source;
    if (search) params.search = search;
    const { data } = await client.get('/mt5-journal', { params });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getMT5Journal:', err?.message ?? err);
    return { entries: [], total: 0, available_dates: [], available_sources: [] };
  }
}

export async function syncMT5Journal() {
  try {
    const { data } = await client.post('/mt5-journal/sync');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] syncMT5Journal:', err?.message ?? err);
    return { success: false, message: 'Bağlantı hatası.', synced: 0 };
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

export async function executeManualTrade(symbol, direction, lot, sl = 0, tp = 0) {
  try {
    const { data } = await client.post('/manual-trade/execute', { symbol, direction, lot, sl, tp });
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

export async function getHybridPerformance() {
  try {
    const { data } = await client.get('/hybrid/performance');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getHybridPerformance:', err?.message ?? err);
    return {};
  }
}

// ── Bildirimler ─────────────────────────────────────────────────

export async function getNotifications(params = {}) {
  try {
    const { data } = await client.get('/notifications', { params });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getNotifications:', err?.message ?? err);
    return { count: 0, unread_count: 0, notifications: [] };
  }
}

export async function markNotificationRead(id) {
  try {
    await client.post('/notifications/read', { id });
  } catch (err) {
    console.error('[ÜSTAT API] markNotificationRead:', err?.message ?? err);
  }
}

export async function markAllNotificationsRead() {
  try {
    await client.post('/notifications/read-all');
  } catch (err) {
    console.error('[ÜSTAT API] markAllNotificationsRead:', err?.message ?? err);
  }
}

// ── NABIZ (Sistem Monitörü) ──────────────────────────────────────

export async function getNabiz() {
  try {
    const { data } = await client.get('/nabiz');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getNabiz:', err?.message ?? err);
    return {
      database: {}, logs: {}, disk: {}, retention: {},
      cleanup_conflict: { has_conflict: false },
      // Backend `_build_thresholds_info()` ile aynı anahtar seti — API hatası
      // durumunda bile frontend Number.isFinite() kontrolleri düşmesin.
      thresholds: {
        table_row_thresholds: {},
        summary: {},
        log_files_display_limit: null,
        source: 'api-fallback',
      },
    };
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
      // P1-B + P2-B (2026-04-13): trade_allowed=null → TopBar üçlü mantık
      // "ALGO DURUMU BİLİNMİYOR" rozeti gösterir (fail-open düzeltildi).
      cycle: {},
      mt5: { trade_allowed: null },
      orders: {},
      layers: {},
      recent_events: [],
      system: {},
      _stale: true,
      _error: err?.message ?? 'unknown',
    };
  }
}

// ── Agent Status ────────────────────────────────────────────────

export async function getAgentStatus() {
  try {
    const { data } = await client.get('/agent-status');
    return data;
  } catch {
    return { alive: false };
  }
}

// ── WebSocket (Auto-Reconnect) ──────────────────────────────────

/**
 * Canlı veri WebSocket bağlantısı oluştur.
 * Bağlantı koptuğunda otomatik yeniden bağlanır (exponential backoff).
 *
 * @param {function} onMessage    - (data: object[]) => void
 * @param {function} [onError]    - (error: Event) => void
 * @param {function} [onStateChange] - (state: 'connected'|'reconnecting'|'disconnected') => void
 * @returns {{ close: () => void, getState: () => string }}
 */
export function connectLiveWS(onMessage, onError = null, onStateChange = null) {
  const BACKOFF_INITIAL = 1000;   // 1 saniye
  const BACKOFF_MAX = 30000;      // 30 saniye
  const PING_INTERVAL = 30000;    // 30 saniye

  let ws = null;
  let pingInterval = null;
  let reconnectTimeout = null;
  let backoff = BACKOFF_INITIAL;
  let state = 'disconnected';
  let intentionalClose = false;

  function setState(newState) {
    if (state !== newState) {
      state = newState;
      if (onStateChange) onStateChange(state);
    }
  }

  function connect() {
    try {
      ws = new WebSocket(`${WS_BASE}/ws/live`);
    } catch {
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      backoff = BACKOFF_INITIAL;  // Başarılı bağlantı → backoff sıfırla
      setState('connected');

      // Ping/pong keep-alive
      pingInterval = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, PING_INTERVAL);
    };

    ws.onmessage = (event) => {
      try {
        const messages = JSON.parse(event.data);
        onMessage(messages);
      } catch (parseErr) {
        // v14.1: Geçersiz JSON → loglayarak izole et, WS'yi kapatma
        console.warn(`[WS] JSON parse hatası: ${parseErr.message}, data: ${String(event.data).slice(0, 100)}`);
      }
    };

    ws.onerror = (err) => {
      // v14.1: WS hatasını logla
      console.warn('[WS] WebSocket error event:', err?.type || 'unknown');
      if (onError) onError(err);
    };

    ws.onclose = (event) => {
      // v14.1: Kapanış nedenini logla
      console.warn(`[WS] WebSocket closed: code=${event.code}, reason=${event.reason || 'none'}, clean=${event.wasClean}`);
      cleanup();
      if (!intentionalClose) {
        setState('reconnecting');
        scheduleReconnect();
      } else {
        setState('disconnected');
      }
    };
  }

  function cleanup() {
    if (pingInterval) {
      clearInterval(pingInterval);
      pingInterval = null;
    }
  }

  function scheduleReconnect() {
    if (intentionalClose) return;
    reconnectTimeout = setTimeout(() => {
      connect();
      // Exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s (max)
      backoff = Math.min(backoff * 2, BACKOFF_MAX);
    }, backoff);
  }

  function close() {
    intentionalClose = true;
    cleanup();
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
      reconnectTimeout = null;
    }
    if (ws) {
      ws.close();
      ws = null;
    }
    setState('disconnected');
  }

  function getState() {
    return state;
  }

  // İlk bağlantı
  connect();

  return { close, getState };
}


// ── Error Tracker (Hata Takip) ──────────────────────────────────

export async function getErrorSummary() {
  try {
    const { data } = await client.get('/errors/summary');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getErrorSummary:', err?.message ?? err);
    return { today_errors: 0, today_warnings: 0, open_groups: 0 };
  }
}

export async function getErrorGroups({ category, severity, resolved, limit } = {}) {
  try {
    const params = {};
    if (category) params.category = category;
    if (severity) params.severity = severity;
    if (resolved !== undefined) params.resolved = resolved;
    if (limit) params.limit = limit;
    const { data } = await client.get('/errors/groups', { params });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getErrorGroups:', err?.message ?? err);
    return { count: 0, groups: [] };
  }
}

export async function getErrorTrends({ period = 'hourly', hours, days } = {}) {
  try {
    const params = { period };
    if (hours) params.hours = hours;
    if (days) params.days = days;
    const { data } = await client.get('/errors/trends', { params });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getErrorTrends:', err?.message ?? err);
    return { period, data: [] };
  }
}

export async function resolveError(errorType, messagePrefix = '', resolvedBy = 'operator') {
  try {
    const { data } = await client.post('/errors/resolve', {
      error_type: errorType,
      message_prefix: messagePrefix,
      resolved_by: resolvedBy,
    });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] resolveError:', err?.message ?? err);
    return { success: false };
  }
}

export async function resolveAllErrors(resolvedBy = 'operator') {
  try {
    const { data } = await client.post('/errors/resolve-all', {
      error_type: '*',
      resolved_by: resolvedBy,
    });
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] resolveAllErrors:', err?.message ?? err);
    return { success: false, resolved_count: 0 };
  }
}
