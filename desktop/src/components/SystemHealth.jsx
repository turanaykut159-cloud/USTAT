/**
 * ÜSTAT v5.1 — Sistem Sağlığı sayfası.
 *
 * 6 bölüm:
 *   1. Motor Döngü Performansı   — adım breakdown, trend grafik, ort/max
 *   2. MT5 Bağlantı Sağlığı      — ping, kopma, reconnect
 *   3. Emir Performansı           — ort süre, başarı/ret/timeout, son 10
 *   4. Katman Durumu              — BABA, OĞUL, H-Engine, ÜSTAT
 *   5. Hata Tablosu               — severity filtre, son 30 event
 *   6. Sistem                     — uptime, cycle, DB boyut, WS istemci, cache
 *
 * Veri kaynağı: GET /api/health (5sn poll)
 */

import React, { useState, useEffect, useCallback } from 'react';
import { getHealth } from '../services/api';

// ── Yardımcılar ──────────────────────────────────────────────────

function fmtMs(val) {
  if (val == null || isNaN(val)) return '—';
  return `${Number(val).toFixed(1)}ms`;
}

function fmtUptime(seconds) {
  if (!seconds) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}sa ${m}dk`;
  if (m > 0) return `${m}dk ${s}sn`;
  return `${s}sn`;
}

function fmtTime(ts) {
  if (!ts) return '—';
  try {
    const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
    return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return String(ts);
  }
}

const SEVERITY_COLORS = {
  ERROR: 'sh-sev-error',
  WARNING: 'sh-sev-warning',
  INFO: 'sh-sev-info',
  DEBUG: 'sh-sev-debug',
};

const STEP_LABELS = {
  heartbeat: 'Heartbeat',
  data_update: 'Veri',
  closure_check: 'Kapanma',
  baba_cycle: 'BABA',
  risk_check: 'Risk',
  top5: 'Top 5',
  ogul_signals: 'OGUL',
  h_engine: 'H-Engine',
  ustat_brain: 'USTAT',
  log_summary: 'Log',
};

const STEP_COLORS = [
  '#58a6ff', '#3fb950', '#d29922', '#f0883e',
  '#f85149', '#a371f7', '#79c0ff', '#56d4dd',
  '#db61a2', '#8b949e',
];

// ══════════════════════════════════════════════════════════════════

export default function SystemHealth() {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState('ALL');

  const fetchData = useCallback(async () => {
    const d = await getHealth();
    setData(d);
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 5000);
    return () => clearInterval(iv);
  }, [fetchData]);

  if (!data) {
    return (
      <div className="sh-page">
        <h2 className="sh-title">Sistem Sagligi</h2>
        <p className="sh-loading">Veriler yukleniyor...</p>
      </div>
    );
  }

  const { cycle = {}, mt5 = {}, orders = {}, layers = {}, recent_events = [], system = {} } = data;

  return (
    <div className="sh-page">
      <h2 className="sh-title">Sistem Sagligi</h2>

      <div className="sh-grid-2">
        {/* ── Bolum 1: Motor Dongu Performansi ──────────────────── */}
        <CycleSection cycle={cycle} />

        {/* ── Bolum 2: MT5 Baglanti Sagligi ─────────────────────── */}
        <MT5Section mt5={mt5} />
      </div>

      <div className="sh-grid-2">
        {/* ── Bolum 3: Emir Performansi ─────────────────────────── */}
        <OrderSection orders={orders} />

        {/* ── Bolum 6: Sistem ───────────────────────────────────── */}
        <SystemSection system={system} />
      </div>

      {/* ── Bolum 4: Katman Durumu ────────────────────────────── */}
      <LayerSection layers={layers} />

      {/* ── Bolum 5: Hata Tablosu ─────────────────────────────── */}
      <EventSection events={recent_events} filter={filter} setFilter={setFilter} />
    </div>
  );
}


// ── Bolum 1: Motor Dongu Performansi ──────────────────────────────

function CycleSection({ cycle }) {
  const lastCycle = cycle.last_cycle;
  const durations = cycle.durations_ms || [];
  const maxDuration = Math.max(...durations, 1);

  return (
    <section className="sh-section">
      <h3 className="sh-section-title">Motor Dongu Performansi</h3>

      {/* Ozet satirlari */}
      <div className="sh-stats-row">
        <div className="sh-stat">
          <span className="sh-stat-label">Ort</span>
          <span className="sh-stat-value">{fmtMs(cycle.avg_ms)}</span>
        </div>
        <div className="sh-stat">
          <span className="sh-stat-label">Max</span>
          <span className="sh-stat-value">{fmtMs(cycle.max_ms)}</span>
        </div>
        <div className="sh-stat">
          <span className="sh-stat-label">Asim</span>
          <span className="sh-stat-value sh-stat-warn">{cycle.overrun_count ?? 0}</span>
        </div>
      </div>

      {/* Adim breakdown (son cycle) */}
      {lastCycle && lastCycle.steps && (
        <div className="sh-steps">
          <div className="sh-steps-header">
            <span>Cycle #{lastCycle.cycle_number}</span>
            <span className={lastCycle.overrun ? 'sh-overrun' : ''}>
              {fmtMs(lastCycle.total_ms)}
              {lastCycle.overrun && ' ASIM!'}
            </span>
          </div>
          {Object.entries(lastCycle.steps).map(([key, ms], i) => {
            const pct = lastCycle.total_ms > 0 ? (ms / lastCycle.total_ms) * 100 : 0;
            return (
              <div key={key} className="sh-step-row">
                <span className="sh-step-name">{STEP_LABELS[key] || key}</span>
                <div className="sh-step-bar-track">
                  <div
                    className="sh-step-bar-fill"
                    style={{ width: `${Math.max(pct, 1)}%`, backgroundColor: STEP_COLORS[i % STEP_COLORS.length] }}
                  />
                </div>
                <span className="sh-step-ms">{fmtMs(ms)}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Mini trend grafik (son 60 dongu) */}
      {durations.length > 0 && (
        <div className="sh-trend">
          <span className="sh-trend-label">Son {durations.length} dongu</span>
          <div className="sh-trend-chart">
            {durations.map((d, i) => (
              <div
                key={i}
                className={`sh-trend-bar ${d > 10000 ? 'sh-trend-bar--over' : ''}`}
                style={{ height: `${Math.max((d / maxDuration) * 100, 2)}%` }}
                title={`${d.toFixed(1)}ms`}
              />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}


// ── Bolum 2: MT5 Baglanti Sagligi ────────────────────────────────

function MT5Section({ mt5 }) {
  const connected = mt5.mt5_uptime_seconds > 0;

  return (
    <section className="sh-section">
      <h3 className="sh-section-title">MT5 Baglanti Sagligi</h3>

      <div className="sh-status-row">
        <span className={`sh-status-dot ${connected ? 'sh-dot-ok' : 'sh-dot-err'}`} />
        <span className="sh-status-text">
          {connected ? `Bagli (${fmtUptime(mt5.mt5_uptime_seconds)})` : 'Bagli degil'}
        </span>
      </div>

      <div className="sh-stats-row">
        <div className="sh-stat">
          <span className="sh-stat-label">Son Ping</span>
          <span className="sh-stat-value">{fmtMs(mt5.last_ping_ms)}</span>
        </div>
        <div className="sh-stat">
          <span className="sh-stat-label">Ort Ping</span>
          <span className="sh-stat-value">{fmtMs(mt5.avg_ping_ms)}</span>
        </div>
        <div className="sh-stat">
          <span className="sh-stat-label">Kopma</span>
          <span className="sh-stat-value sh-stat-warn">{mt5.disconnect_count ?? 0}</span>
        </div>
      </div>

      {/* Reconnect gecmisi */}
      {mt5.reconnect_history && mt5.reconnect_history.length > 0 && (
        <div className="sh-reconnect">
          <h4 className="sh-sub-title">Reconnect Gecmisi</h4>
          <table className="sh-table sh-table-sm">
            <thead>
              <tr>
                <th>Zaman</th>
                <th>Sonuc</th>
                <th>Sure</th>
              </tr>
            </thead>
            <tbody>
              {mt5.reconnect_history.map((r, i) => (
                <tr key={i}>
                  <td>{fmtTime(r.timestamp)}</td>
                  <td>
                    <span className={`sh-badge ${r.success ? 'sh-badge-ok' : 'sh-badge-err'}`}>
                      {r.success ? 'Basarili' : 'Basarisiz'}
                    </span>
                  </td>
                  <td>{fmtMs(r.duration_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}


// ── Bolum 3: Emir Performansi ────────────────────────────────────

function OrderSection({ orders }) {
  const last10 = orders.last_10 || [];

  return (
    <section className="sh-section">
      <h3 className="sh-section-title">Emir Performansi</h3>

      <div className="sh-stats-row">
        <div className="sh-stat">
          <span className="sh-stat-label">Ort Sure</span>
          <span className="sh-stat-value">{fmtMs(orders.avg_send_ms)}</span>
        </div>
        <div className="sh-stat">
          <span className="sh-stat-label">Basarili</span>
          <span className="sh-stat-value sh-stat-ok">{orders.success_count ?? 0}</span>
        </div>
        <div className="sh-stat">
          <span className="sh-stat-label">Ret</span>
          <span className="sh-stat-value sh-stat-warn">{orders.reject_count ?? 0}</span>
        </div>
        <div className="sh-stat">
          <span className="sh-stat-label">Timeout</span>
          <span className="sh-stat-value sh-stat-err">{orders.timeout_count ?? 0}</span>
        </div>
      </div>

      {last10.length > 0 && (
        <div className="sh-orders">
          <h4 className="sh-sub-title">Son 10 Emir</h4>
          <table className="sh-table">
            <thead>
              <tr>
                <th>Zaman</th>
                <th>Sembol</th>
                <th>Yon</th>
                <th>Sure</th>
                <th>Sonuc</th>
                <th>Slippage</th>
              </tr>
            </thead>
            <tbody>
              {last10.map((o, i) => (
                <tr key={i}>
                  <td>{fmtTime(o.timestamp)}</td>
                  <td className="sh-mono">{o.symbol}</td>
                  <td>
                    <span className={o.direction === 'BUY' ? 'sh-dir-buy' : 'sh-dir-sell'}>
                      {o.direction}
                    </span>
                  </td>
                  <td>{fmtMs(o.duration_ms)}</td>
                  <td>
                    <span className={`sh-badge ${o.success ? 'sh-badge-ok' : 'sh-badge-err'}`}>
                      {o.success ? 'OK' : `Ret(${o.retcode})`}
                    </span>
                  </td>
                  <td>{o.slippage != null ? o.slippage.toFixed(4) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}


// ── Bolum 4: Katman Durumu ───────────────────────────────────────

function LayerSection({ layers }) {
  const baba = layers.baba || {};
  const ogul = layers.ogul || {};
  const hEngine = layers.h_engine || {};
  const ustat = layers.ustat || {};

  return (
    <section className="sh-section">
      <h3 className="sh-section-title">Katman Durumu</h3>

      <div className="sh-layer-grid">
        {/* BABA */}
        <div className="sh-layer-card">
          <h4 className="sh-layer-name">BABA</h4>
          <div className="sh-layer-rows">
            <div className="sh-layer-row">
              <span>Rejim</span>
              <span className="sh-mono">{baba.regime || '—'}</span>
            </div>
            <div className="sh-layer-row">
              <span>Guven</span>
              <span>{baba.confidence != null ? `%${(baba.confidence * 100).toFixed(0)}` : '—'}</span>
            </div>
            <div className="sh-layer-row">
              <span>Risk Carpani</span>
              <span>{baba.risk_multiplier ?? '—'}</span>
            </div>
            <div className="sh-layer-row">
              <span>Kill-Switch</span>
              <span className={baba.kill_switch_level > 0 ? 'sh-stat-err' : ''}>
                L{baba.kill_switch_level ?? 0}
              </span>
            </div>
            {baba.killed_symbols && baba.killed_symbols.length > 0 && (
              <div className="sh-layer-row">
                <span>Oldurulen</span>
                <span className="sh-mono sh-stat-warn">{baba.killed_symbols.join(', ')}</span>
              </div>
            )}
          </div>
        </div>

        {/* OGUL */}
        <div className="sh-layer-card">
          <h4 className="sh-layer-name">OGUL</h4>
          <div className="sh-layer-rows">
            <div className="sh-layer-row">
              <span>Aktif Islem</span>
              <span className="sh-mono">{ogul.active_trade_count ?? 0}</span>
            </div>
            <div className="sh-layer-row">
              <span>Aktif Semboller</span>
              <span className="sh-mono">{ogul.active_symbols?.join(', ') || '—'}</span>
            </div>
            <div className="sh-layer-row">
              <span>Gunluk Zarar Stop</span>
              <span className={ogul.daily_loss_stop ? 'sh-stat-err' : 'sh-stat-ok'}>
                {ogul.daily_loss_stop ? 'AKTIF' : 'Yok'}
              </span>
            </div>
            <div className="sh-layer-row">
              <span>Evrensel Yonetim</span>
              <span className={ogul.universal_management ? 'sh-stat-ok' : ''}>
                {ogul.universal_management ? 'Aktif' : 'Kapali'}
              </span>
            </div>
          </div>
        </div>

        {/* H-Engine */}
        <div className="sh-layer-card">
          <h4 className="sh-layer-name">H-Engine</h4>
          <div className="sh-layer-rows">
            <div className="sh-layer-row">
              <span>Aktif Hibrit</span>
              <span className="sh-mono">{hEngine.active_hybrid_count ?? 0}</span>
            </div>
            <div className="sh-layer-row">
              <span>Gunluk K/Z</span>
              <span className={hEngine.daily_pnl < 0 ? 'sh-stat-err' : 'sh-stat-ok'}>
                {hEngine.daily_pnl != null ? hEngine.daily_pnl.toFixed(2) : '—'}
              </span>
            </div>
            <div className="sh-layer-row">
              <span>Gunluk Limit</span>
              <span>{hEngine.daily_limit ?? '—'}</span>
            </div>
            <div className="sh-layer-row">
              <span>Native SL/TP</span>
              <span>{hEngine.native_sltp ? 'Aktif' : 'Yazilimsal'}</span>
            </div>
          </div>
        </div>

        {/* USTAT */}
        <div className="sh-layer-card">
          <h4 className="sh-layer-name">USTAT</h4>
          <div className="sh-layer-rows">
            <div className="sh-layer-row">
              <span>Son Calisma</span>
              <span className="sh-mono">{fmtTime(ustat.last_run_time)}</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}


// ── Bolum 5: Hata Tablosu ────────────────────────────────────────

function EventSection({ events, filter, setFilter }) {
  const filters = ['ALL', 'ERROR', 'WARNING', 'INFO'];

  const filtered = filter === 'ALL'
    ? events
    : events.filter(e => e.severity === filter);

  return (
    <section className="sh-section">
      <h3 className="sh-section-title">Son Olaylar</h3>

      <div className="sh-filter-group">
        {filters.map(f => (
          <button
            key={f}
            className={`sh-filter-btn ${filter === f ? 'sh-filter-active' : ''}`}
            onClick={() => setFilter(f)}
          >
            {f}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="sh-empty">Olay yok.</p>
      ) : (
        <div className="sh-events-wrap">
          <table className="sh-table">
            <thead>
              <tr>
                <th>Zaman</th>
                <th>Tip</th>
                <th>Onem</th>
                <th>Mesaj</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e, i) => (
                <tr key={e.id || i}>
                  <td className="sh-mono">{fmtTime(e.timestamp)}</td>
                  <td className="sh-mono">{e.type}</td>
                  <td>
                    <span className={`sh-sev-badge ${SEVERITY_COLORS[e.severity] || 'sh-sev-info'}`}>
                      {e.severity}
                    </span>
                  </td>
                  <td className="sh-event-msg">{e.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}


// ── Bolum 6: Sistem ──────────────────────────────────────────────

function SystemSection({ system }) {
  return (
    <section className="sh-section">
      <h3 className="sh-section-title">Sistem</h3>

      <div className="sh-sys-grid">
        <div className="sh-sys-item">
          <span className="sh-sys-label">Engine Uptime</span>
          <span className="sh-sys-value">{fmtUptime(system.engine_uptime_seconds)}</span>
        </div>
        <div className="sh-sys-item">
          <span className="sh-sys-label">Dongu Sayisi</span>
          <span className="sh-sys-value">{system.cycle_count?.toLocaleString('tr-TR') ?? '—'}</span>
        </div>
        <div className="sh-sys-item">
          <span className="sh-sys-label">DB Boyutu</span>
          <span className="sh-sys-value">{system.db_file_size_mb != null ? `${system.db_file_size_mb} MB` : '—'}</span>
        </div>
        <div className="sh-sys-item">
          <span className="sh-sys-label">WS Istemci</span>
          <span className="sh-sys-value">{system.ws_clients ?? 0}</span>
        </div>
        <div className="sh-sys-item">
          <span className="sh-sys-label">Cache</span>
          <span className={`sh-sys-value ${system.cache_stale ? 'sh-stat-warn' : 'sh-stat-ok'}`}>
            {system.cache_stale ? 'Bayat' : 'Taze'}
          </span>
        </div>
      </div>
    </section>
  );
}
