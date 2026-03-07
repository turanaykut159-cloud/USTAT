/**
 * ÜSTAT v5.1 — Ana Dashboard ekranı.
 *
 * Layout:
 *   Üst:    4 stat kartı (Günlük İşlem, Başarı Oranı, Net K/Z, Profit Factor)
 *   Orta:   Açık Pozisyonlar tablosu (tam genişlik)
 *   Alt:    Son 5 işlem tablosu (tam genişlik)
 *
 * Veri kaynakları:
 *   REST:  getTradeStats, getPerformance, getTrades, getStatus, getPositions (10sn poll)
 *   WS:    connectLiveWS → equity + status + position gerçek zamanlı güncelleme
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  getTradeStats, getPerformance, getTrades, getStatus,
  getAccount, getPositions, closePosition, connectLiveWS,
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

/** Timestamp → tarih + saat (gg.aa.yyyy HH:mm) */
function shortTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleString('tr-TR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

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
  const [status, setStatus] = useState({
    regime: 'TREND', regime_confidence: 0,
    engine_running: false, daily_trade_count: 0,
  });
  const [account, setAccount] = useState({ equity: 0 });
  const [livePositions, setLivePositions] = useState([]);
  const [initialLoading, setInitialLoading] = useState(true);
  const [closingTicket, setClosingTicket] = useState(null);

  // WebSocket kaynak canlı veri
  const [liveEquity, setLiveEquity] = useState(null);
  const wsRef = useRef(null);

  // ── REST veri çekme (10sn) ───────────────────────────────────────
  const fetchAll = useCallback(async () => {
    const [s, p, t, st, acc, pos] = await Promise.all([
      getTradeStats(),
      getPerformance(30),
      getTrades({ limit: 5 }),
      getStatus(),
      getAccount(),
      getPositions(),
    ]);
    setStats(s);
    setPerf(p);
    setRecentTrades(t.trades || []);
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

  // ── İşlemi Kapat (sadece manuel, Dashboard tablosu) ─────────────────
  const handleClosePosition = useCallback(async (ticket) => {
    if (closingTicket != null) return;
    setClosingTicket(ticket);
    try {
      await closePosition(ticket);
      await fetchAll();
    } catch (err) {
      window.alert('Kapatma hatası: ' + (err?.message ?? String(err)));
    } finally {
      setClosingTicket(null);
    }
  }, [closingTicket, fetchAll]);

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
                  <th>Tür</th>
                  <th>İşlem</th>
                </tr>
              </thead>
              <tbody>
                {(livePositions || []).map((pos) => {
                  const pnl = pos.pnl || 0;
                  const isManual = (pos.strategy || '').toLowerCase() === 'manual';
                  const turLabel = isManual ? 'Manuel' : (pos.strategy ? 'Otomatik' : '—');
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
                      <td>
                        <span className={`op-tur-badge op-tur--${isManual ? 'manual' : 'auto'}`}>
                          {turLabel}
                        </span>
                      </td>
                      <td>
                        {isManual && (
                          <button
                            type="button"
                            className="op-close-btn"
                            onClick={() => handleClosePosition(pos.ticket)}
                            disabled={closingTicket === pos.ticket}
                            title="Bu pozisyonu kapat"
                          >
                            {closingTicket === pos.ticket ? 'Kapatılıyor...' : 'İşlemi Kapat'}
                          </button>
                        )}
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
                  <td colSpan={2}></td>
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      </div>

      {/* ═══ ALT: Son İşlemler (tam genişlik) ══════════════════════ */}
      <div className="dash-bottom-row">
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
