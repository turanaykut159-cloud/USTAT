/**
 * ÜSTAT v5.0 — Ana Dashboard ekranı.
 *
 * Layout:
 *   Üst:    4 stat kartı (Toplam İşlem, Başarı Oranı, Net K/Z, Profit Factor)
 *   Orta:   Sol — Equity eğrisi (AreaChart), Sağ — Günlük K/Z çubuk grafiği (BarChart)
 *   Alt:    Sol — Son 5 işlem tablosu, Sağ — Aktif rejim + Top 5 kontrat listesi
 *
 * Veri kaynakları:
 *   REST:  getTradeStats, getPerformance, getTrades, getTop5, getStatus (10sn poll)
 *   WS:    connectLiveWS → equity + status gerçek zamanlı güncelleme
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  AreaChart, Area,
  BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import {
  getTradeStats, getPerformance, getTrades, getTop5, getStatus,
  getAccount, connectLiveWS, reactivateSymbols,
} from '../services/api';

// ── Yardımcılar ──────────────────────────────────────────────────

function formatMoney(val) {
  if (val == null || isNaN(val)) return '—';
  const abs = Math.abs(val);
  const formatted = abs.toLocaleString('tr-TR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return val < 0 ? `-${formatted}` : formatted;
}

function formatPct(val) {
  if (val == null || isNaN(val)) return '—';
  return `%${val.toFixed(1)}`;
}

function formatPF(val) {
  if (val == null || isNaN(val) || val === 0) return '—';
  return val.toFixed(2);
}

function pnlClass(val) {
  if (val > 0) return 'profit';
  if (val < 0) return 'loss';
  return '';
}

/** Timestamp → kısa tarih (gün.ay) */
function shortDate(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return `${d.getDate().toString().padStart(2, '0')}.${(d.getMonth() + 1).toString().padStart(2, '0')}`;
  } catch {
    return ts.slice(5, 10);
  }
}

/** Timestamp → saat:dakika */
function shortTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

// ── Rejim renk eşlemesi ──────────────────────────────────────────
const REGIME_META = {
  TREND:    { color: 'var(--profit)',  bg: 'rgba(63,185,80,0.1)',  label: 'Trend'    },
  RANGE:    { color: 'var(--accent)',  bg: 'rgba(88,166,255,0.1)', label: 'Range'    },
  VOLATILE: { color: 'var(--warning)', bg: 'rgba(210,153,34,0.1)', label: 'Volatile' },
  OLAY:     { color: 'var(--loss)',    bg: 'rgba(248,81,73,0.1)',  label: 'Olay'     },
};

// ── Recharts özel tooltip ────────────────────────────────────────

function EquityTooltip({ active, payload }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <span className="chart-tooltip-date">{shortDate(d.timestamp)}</span>
      <span>Equity: <b>{formatMoney(d.equity)}</b></span>
      <span className={pnlClass(d.daily_pnl)}>
        Günlük: <b>{formatMoney(d.daily_pnl)}</b>
      </span>
    </div>
  );
}

function BarTooltip({ active, payload }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <span className="chart-tooltip-date">{d.date}</span>
      <span className={pnlClass(d.pnl)}>
        K/Z: <b>{formatMoney(d.pnl)}</b>
      </span>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//  DASHBOARD
// ═══════════════════════════════════════════════════════════════════

export default function Dashboard() {
  // ── State ────────────────────────────────────────────────────────
  const [stats, setStats] = useState({
    total_trades: 0, win_rate: 0, total_pnl: 0,
  });
  const [perf, setPerf] = useState({
    profit_factor: 0, equity_curve: [],
  });
  const [recentTrades, setRecentTrades] = useState([]);
  const [top5, setTop5] = useState({ contracts: [] });
  const [status, setStatus] = useState({
    regime: 'TREND', regime_confidence: 0,
    engine_running: false, daily_trade_count: 0,
  });
  const [account, setAccount] = useState({ equity: 0 });

  // WebSocket kaynak canlı veri
  const [liveEquity, setLiveEquity] = useState(null);
  const wsRef = useRef(null);

  // ── REST veri çekme (10sn) ───────────────────────────────────────
  const fetchAll = useCallback(async () => {
    const [s, p, t, t5, st, acc] = await Promise.all([
      getTradeStats(),
      getPerformance(30),
      getTrades({ limit: 5 }),
      getTop5(),
      getStatus(),
      getAccount(),
    ]);
    setStats(s);
    setPerf(p);
    setRecentTrades(t.trades || []);
    setTop5(t5);
    setStatus(st);
    setAccount(acc);
  }, []);

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 10000);
    return () => clearInterval(iv);
  }, [fetchAll]);

  // ── WebSocket canlı veri ─────────────────────────────────────────
  useEffect(() => {
    const { close } = connectLiveWS((messages) => {
      if (!Array.isArray(messages)) return;
      for (const msg of messages) {
        if (msg.type === 'equity') {
          setLiveEquity(msg);
        }
        if (msg.type === 'status') {
          setStatus((prev) => ({
            ...prev,
            regime: msg.regime || prev.regime,
            can_trade: msg.can_trade,
            kill_switch_level: msg.kill_switch_level,
          }));
        }
      }
    });

    wsRef.current = close;
    return () => {
      if (wsRef.current) wsRef.current();
    };
  }, []);

  // ── Hesaplamalar ─────────────────────────────────────────────────

  // Equity eğrisi verisini chart'a hazırla
  const equityCurve = (perf.equity_curve || []).map((pt) => ({
    timestamp: pt.timestamp,
    equity: pt.equity,
    daily_pnl: pt.daily_pnl,
  }));

  // Son 30 gün günlük K/Z bar verisi (equity_curve'den türet)
  const dailyBars = (() => {
    const curve = perf.equity_curve || [];
    if (curve.length === 0) return [];

    // Günlük PnL grupla
    const dayMap = {};
    for (const pt of curve) {
      const day = (pt.timestamp || '').slice(0, 10);
      if (!day) continue;
      // Son kaydı al (gün sonu değeri)
      dayMap[day] = pt.daily_pnl || 0;
    }

    return Object.entries(dayMap)
      .sort(([a], [b]) => a.localeCompare(b))
      .slice(-30)
      .map(([date, pnl]) => ({
        date: date.slice(5), // "MM-DD"
        pnl,
        fill: pnl >= 0 ? 'var(--profit)' : 'var(--loss)',
      }));
  })();

  // Gösterilecek equity: canlı WS → perf eğrisi → account API fallback
  const displayEquity = liveEquity?.equity
    ?? perf.equity_curve?.[perf.equity_curve.length - 1]?.equity
    ?? account.equity
    ?? 0;

  // Rejim bilgisi
  const regime = status.regime || 'TREND';
  const regimeMeta = REGIME_META[regime] || REGIME_META.TREND;

  return (
    <div className="dashboard">

      {/* ═══ ÜST: 4 Stat Kartı ════════════════════════════════════ */}
      <div className="dash-stats-row">
        <StatCard
          label="Toplam İşlem"
          sublabel="bugün"
          value={status.daily_trade_count || 0}
          total={stats.total_trades}
          icon="📊"
        />
        <StatCard
          label="Başarı Oranı"
          value={formatPct(stats.win_rate)}
          detail={`${stats.winning_trades || 0}W / ${stats.losing_trades || 0}L`}
          icon="🎯"
          color={stats.win_rate >= 50 ? 'var(--profit)' : 'var(--loss)'}
        />
        <StatCard
          label="Net Kâr/Zarar"
          value={formatMoney(stats.total_pnl)}
          icon="💰"
          color={stats.total_pnl >= 0 ? 'var(--profit)' : 'var(--loss)'}
        />
        <StatCard
          label="Profit Factor"
          value={formatPF(perf.profit_factor)}
          icon="📐"
          color={perf.profit_factor >= 1.5 ? 'var(--profit)' : perf.profit_factor >= 1 ? 'var(--warning)' : 'var(--loss)'}
        />
      </div>

      {/* ═══ ORTA: 2 Grafik ═══════════════════════════════════════ */}
      <div className="dash-charts-row">

        {/* ── Sol: Equity Eğrisi ────────────────────────────────── */}
        <div className="dash-chart-card">
          <div className="dash-chart-header">
            <h3>Equity Eğrisi</h3>
            <span className="dash-chart-value">
              {formatMoney(displayEquity)} <small>TRY</small>
            </span>
          </div>
          <div className="dash-chart-body">
            {equityCurve.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={equityCurve} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#58a6ff" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#58a6ff" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                  <XAxis
                    dataKey="timestamp"
                    tickFormatter={shortDate}
                    stroke="#8b949e"
                    fontSize={11}
                    tickLine={false}
                  />
                  <YAxis
                    stroke="#8b949e"
                    fontSize={11}
                    tickLine={false}
                    tickFormatter={(v) => `${(v / 1000).toFixed(0)}K`}
                    width={48}
                  />
                  <Tooltip content={<EquityTooltip />} />
                  <Area
                    type="monotone"
                    dataKey="equity"
                    stroke="#58a6ff"
                    strokeWidth={2}
                    fill="url(#eqGrad)"
                    dot={false}
                    activeDot={{ r: 4, fill: '#58a6ff' }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="dash-chart-empty">Equity verisi yok</div>
            )}
          </div>
        </div>

        {/* ── Sağ: Günlük K/Z Çubuk Grafiği ─────────────────────── */}
        <div className="dash-chart-card">
          <div className="dash-chart-header">
            <h3>Günlük Kâr/Zarar</h3>
            <span className="dash-chart-value">
              Son 30 gün
            </span>
          </div>
          <div className="dash-chart-body">
            {dailyBars.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={dailyBars} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                  <XAxis
                    dataKey="date"
                    stroke="#8b949e"
                    fontSize={10}
                    tickLine={false}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    stroke="#8b949e"
                    fontSize={11}
                    tickLine={false}
                    tickFormatter={(v) => v >= 1000 || v <= -1000 ? `${(v / 1000).toFixed(1)}K` : v.toFixed(0)}
                    width={48}
                  />
                  <Tooltip content={<BarTooltip />} />
                  <ReferenceLine y={0} stroke="#30363d" />
                  <Bar dataKey="pnl" radius={[2, 2, 0, 0]} maxBarSize={16}>
                    {dailyBars.map((entry, idx) => (
                      <Cell
                        key={idx}
                        fill={entry.pnl >= 0 ? '#3fb950' : '#f85149'}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="dash-chart-empty">Günlük K/Z verisi yok</div>
            )}
          </div>
        </div>
      </div>

      {/* ═══ ALT: Son İşlemler + Rejim & Top 5 ════════════════════ */}
      <div className="dash-bottom-row">

        {/* ── Sol: Son 5 İşlem ──────────────────────────────────── */}
        <div className="dash-card">
          <h3>Son İşlemler</h3>
          {recentTrades.length > 0 ? (
            <table className="dash-trades-table">
              <thead>
                <tr>
                  <th>Sembol</th>
                  <th>Yön</th>
                  <th>Strateji</th>
                  <th>Lot</th>
                  <th>K/Z</th>
                  <th>Zaman</th>
                </tr>
              </thead>
              <tbody>
                {recentTrades.map((t, i) => (
                  <tr key={t.id || i}>
                    <td className="mono">{t.symbol}</td>
                    <td>
                      <span className={`dir-badge dir-badge--${t.direction?.toLowerCase()}`}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="text-dim">{t.strategy || '—'}</td>
                    <td className="mono">{t.lot?.toFixed(2) ?? '—'}</td>
                    <td className={`mono ${pnlClass(t.pnl)}`}>
                      {formatMoney(t.pnl)}
                    </td>
                    <td className="text-dim">{shortTime(t.exit_time || t.entry_time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="dash-empty-msg">Henüz işlem yok</div>
          )}
        </div>

        {/* ── Sağ: Aktif Rejim + Top 5 ──────────────────────────── */}
        <div className="dash-card">
          {/* Rejim göstergesi */}
          <div className="dash-regime">
            <h3>Aktif Rejim</h3>
            <div
              className="regime-badge"
              style={{ background: regimeMeta.bg, color: regimeMeta.color }}
            >
              <span className="regime-dot" style={{ background: regimeMeta.color }} />
              {regimeMeta.label}
              {status.regime_confidence > 0 && (
                <span className="regime-conf">
                  {(status.regime_confidence * 100).toFixed(0)}%
                </span>
              )}
            </div>
          </div>

          {/* Top 5 kontrat listesi */}
          <div className="dash-top5">
            <div className="dash-top5-header">
              <h3>Top 5 Kontrat</h3>
              {top5.last_refresh && (
                <span className="top5-refresh-time">
                  {shortTime(top5.last_refresh)}
                </span>
              )}
            </div>

            {/* Kontrat durumu */}
            {(() => {
              const deactCount = (status.deactivated_symbols || []).length;
              const activeCount = 15 - deactCount;
              return (
                <div className={`top5-status-bar ${deactCount > 0 ? 'top5-status-warn' : 'top5-status-ok'}`}>
                  <span>{activeCount}/15 aktif</span>
                  {deactCount > 0 && (
                    <button
                      className="top5-reactivate-btn"
                      onClick={async () => {
                        const res = await reactivateSymbols();
                        if (res.success) fetchAll();
                      }}
                    >
                      Aktif Et
                    </button>
                  )}
                </div>
              );
            })()}

            {(top5.contracts || []).length > 0 ? (
              <ul className="top5-list">
                {top5.contracts.map((c, i) => {
                  const dir = c.signal_direction || 'NOTR';
                  const dirCls = dir === 'BUY' ? 'top5-dir-buy'
                    : dir === 'SELL' ? 'top5-dir-sell'
                    : 'top5-dir-notr';
                  return (
                    <li key={c.symbol} className="top5-item">
                      <span className="top5-rank">#{c.rank || i + 1}</span>
                      <span className="top5-symbol">{c.symbol}</span>
                      <span className={`top5-direction ${dirCls}`}>{dir}</span>
                      <span className="top5-score">{c.score?.toFixed(1) ?? '—'}</span>
                      <div className="top5-bar-bg">
                        <div
                          className="top5-bar-fill"
                          style={{
                            width: `${Math.min((c.score / (top5.contracts[0]?.score || 1)) * 100, 100)}%`,
                          }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <div className="dash-empty-msg">Top 5 verisi yok</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
//  STAT CARD ALT BİLEŞENİ
// ═══════════════════════════════════════════════════════════════════

function StatCard({ label, sublabel, value, total, detail, icon, color }) {
  return (
    <div className="dash-stat-card">
      <div className="dash-stat-top">
        <span className="dash-stat-icon">{icon}</span>
        <span className="dash-stat-label">{label}</span>
      </div>
      <div className="dash-stat-value" style={color ? { color } : undefined}>
        {value}
      </div>
      {sublabel && total != null && (
        <div className="dash-stat-sub">
          {sublabel} — Toplam: {total}
        </div>
      )}
      {detail && (
        <div className="dash-stat-sub">{detail}</div>
      )}
    </div>
  );
}
