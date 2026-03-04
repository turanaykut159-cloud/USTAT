/**
 * ÜSTAT v5.1 — Ana Dashboard ekranı.
 *
 * Layout:
 *   Üst:    4 stat kartı (Günlük İşlem, Başarı Oranı, Net K/Z, Profit Factor)
 *   Orta:   Açık Pozisyonlar tablosu (tam genişlik)
 *   Alt:    Sol — Son 5 işlem tablosu, Sağ — Aktif rejim + Top 5 kontrat listesi
 *
 * Veri kaynakları:
 *   REST:  getTradeStats, getPerformance, getTrades, getTop5, getStatus, getPositions (10sn poll)
 *   WS:    connectLiveWS → equity + status + position gerçek zamanlı güncelleme
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  getTradeStats, getPerformance, getTrades, getTop5, getStatus,
  getAccount, getPositions, connectLiveWS, reactivateSymbols,
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

/** Fiyat formatla (2-5 ondalık) */
function formatPrice(val) {
  if (val == null || isNaN(val) || val === 0) return '—';
  return val.toLocaleString('tr-TR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 5,
  });
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
  const [livePositions, setLivePositions] = useState([]);
  const [initialLoading, setInitialLoading] = useState(true);

  // WebSocket kaynak canlı veri
  const [liveEquity, setLiveEquity] = useState(null);
  const wsRef = useRef(null);

  // ── REST veri çekme (10sn) ───────────────────────────────────────
  const fetchAll = useCallback(async () => {
    const [s, p, t, t5, st, acc, pos] = await Promise.all([
      getTradeStats(),
      getPerformance(30),
      getTrades({ limit: 5 }),
      getTop5(),
      getStatus(),
      getAccount(),
      getPositions(),
    ]);
    setStats(s);
    setPerf(p);
    setRecentTrades(t.trades || []);
    setTop5(t5);
    setStatus(st);
    setAccount(acc);
    setLivePositions(pos.positions || []);
    setInitialLoading(false);
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
        if (msg.type === 'position') {
          setLivePositions(msg.positions || []);
        }
      }
    });

    wsRef.current = close;
    return () => {
      if (wsRef.current) wsRef.current();
    };
  }, []);

  // ── Hesaplamalar ─────────────────────────────────────────────────

  // Rejim bilgisi
  const regime = status.regime || 'TREND';
  const regimeMeta = REGIME_META[regime] || REGIME_META.TREND;

  if (initialLoading) {
    return (
      <div className="dashboard">
        <div className="dash-loading-wrap">
          <p className="dash-loading">Yükleniyor...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard">

      {/* ═══ ÜST: 4 Stat Kartı ════════════════════════════════════ */}
      <div className="dash-stats-row">
        <StatCard
          label="Günlük İşlem"
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
          detail="Kapanan işlemler toplamı (DB)"
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

      {/* ═══ HESAP DURUMU (canlı) ═════════════════════════════════ */}
      <div className="dash-account-strip">
        <AccountItem
          label="Bakiye"
          value={formatMoney(liveEquity?.balance ?? account.balance)}
        />
        <AccountItem
          label="Varlık"
          value={formatMoney(liveEquity?.equity ?? account.equity)}
        />
        <AccountItem
          label="Floating K/Z"
          value={formatMoney(liveEquity?.floating_pnl ?? account.floating_pnl)}
          cls={pnlClass(liveEquity?.floating_pnl ?? account.floating_pnl)}
        />
        <AccountItem
          label="Günlük K/Z"
          value={formatMoney(liveEquity?.daily_pnl ?? account.daily_pnl)}
          cls={pnlClass(liveEquity?.daily_pnl ?? account.daily_pnl)}
        />
      </div>

      {/* ═══ ORTA: Açık Pozisyonlar ═════════════════════════════════ */}
      <div className="dash-positions-row">
        <div className="dash-card dash-card--full">
          <div className="dash-card-header">
            <h3>Açık Pozisyonlar</h3>
            <span className="dash-card-badge">
              {(livePositions || []).length} / 5
            </span>
          </div>
          {(livePositions || []).length === 0 ? (
            <div className="dash-positions-empty">
              <span>📭</span> Açık pozisyon yok
            </div>
          ) : (
            <table className="dash-positions-table">
              <thead>
                <tr>
                  <th>Sembol</th>
                  <th>Yön</th>
                  <th>Lot</th>
                  <th>Giriş Fiy.</th>
                  <th>Anlık Fiy.</th>
                  <th>SL</th>
                  <th>TP</th>
                  <th>K/Z</th>
                </tr>
              </thead>
              <tbody>
                {(livePositions || []).map((pos) => {
                  const pnl = pos.pnl || 0;
                  return (
                    <tr key={pos.ticket || pos.symbol}>
                      <td className="mono">{pos.symbol}</td>
                      <td>
                        <span className={`dir-badge dir-badge--${(pos.direction || '').toLowerCase()}`}>
                          {pos.direction}
                        </span>
                      </td>
                      <td className="mono">{pos.volume?.toFixed(2) ?? '—'}</td>
                      <td className="mono">{formatPrice(pos.entry_price)}</td>
                      <td className="mono">{formatPrice(pos.current_price)}</td>
                      <td className="mono text-dim">{formatPrice(pos.sl)}</td>
                      <td className="mono text-dim">{formatPrice(pos.tp)}</td>
                      <td className={`mono ${pnl > 0 ? 'profit' : pnl < 0 ? 'loss' : ''}`}>
                        <b>{formatMoney(pnl)}</b>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="dash-positions-footer">
                  <td colSpan={2}><b>TOPLAM</b></td>
                  <td className="mono">
                    <b>{(livePositions || []).reduce((s, p) => s + (p.volume || 0), 0).toFixed(2)}</b>
                  </td>
                  <td colSpan={4}></td>
                  <td className={`mono ${(livePositions || []).reduce((s, p) => s + (p.pnl || 0), 0) >= 0 ? 'profit' : 'loss'}`}>
                    <b>{formatMoney((livePositions || []).reduce((s, p) => s + (p.pnl || 0), 0))}</b>
                  </td>
                </tr>
              </tfoot>
            </table>
          )}
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

function AccountItem({ label, value, cls }) {
  return (
    <div className="dash-account-item">
      <span className="dash-account-label">{label}</span>
      <span className={`dash-account-value ${cls || ''}`}>
        {value} <span className="dash-account-suffix">TRY</span>
      </span>
    </div>
  );
}


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
