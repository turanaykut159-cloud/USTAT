/**
 * ÜSTAT v5.1 — Ana Dashboard ekranı.
 *
 * Layout:
 *   Üst:    4 stat kartı (Günlük İşlem, Başarı Oranı, Net K/Z, Profit Factor)
 *   Hesap:  Bakiye, Varlık, Teminat, Serbest Teminat, Floating K/Z, Günlük K/Z
 *   Orta:   Açık Pozisyonlar — TAM ÖZELLİKLİ (Swap, Yönetim, Süre, Rejim, Hibrit)
 *   Alt:    Son 5 işlem tablosu (tam genişlik)
 *
 * Veri kaynakları:
 *   REST:  getTradeStats, getPerformance, getTrades, getStatus, getPositions,
 *          getAccount, getHybridStatus (10sn poll)
 *   WS:    connectLiveWS → equity + status + position + hybrid gerçek zamanlı
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getTradeStats, getPerformance, getTrades, getStatus,
  getAccount, getPositions, closePosition, connectLiveWS,
  getHybridStatus, checkHybridTransfer, transferToHybrid,
} from '../services/api';
import { formatMoney, formatPrice, pnlClass, elapsed } from '../utils/formatters';

// ── Yardımcılar ──────────────────────────────────────────────────

function formatPct(val) {
  if (val == null || isNaN(val)) return '—';
  return `%${val.toFixed(1)}`;
}

function formatPF(val) {
  if (val == null || isNaN(val) || val === 0) return '—';
  return val.toFixed(2);
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

/** Teminat kullanım oranı (%) */
function marginUsagePct(margin, equity) {
  if (!margin || !equity || equity <= 0) return 0;
  return (margin / equity) * 100;
}

// Bilinen otomatik stratejiler
const KNOWN_AUTO_STRATEGIES = ['trend_follow', 'mean_reversion', 'breakout'];

// ═══════════════════════════════════════════════════════════════════
//  DASHBOARD
// ═══════════════════════════════════════════════════════════════════

export default function Dashboard() {
  const navigate = useNavigate();

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
  const [account, setAccount] = useState({
    balance: 0, equity: 0, margin: 0, free_margin: 0, floating_pnl: 0,
  });
  const [livePositions, setLivePositions] = useState([]);
  const [initialLoading, setInitialLoading] = useState(true);
  const [closingTicket, setClosingTicket] = useState(null);
  const [hybridTickets, setHybridTickets] = useState(new Set());
  const [transferringTicket, setTransferringTicket] = useState(null);

  // WebSocket kaynak canlı veri
  const [liveEquity, setLiveEquity] = useState(null);
  const wsRef = useRef(null);

  // Süre yenileme tetikleyici (30sn)
  const [, setTick] = useState(new Date());

  // ── Trade/Stats veri çekme (WS event-driven) ────────────────────
  const fetchTradeData = useCallback(async () => {
    const [s, p, t] = await Promise.all([
      getTradeStats(),
      getPerformance(30),
      getTrades({ limit: 5 }),
    ]);
    setStats(s);
    setPerf(p);
    setRecentTrades(t.trades || []);
  }, []);

  // ── Durum/Pozisyon veri çekme (REST fallback, 30sn) ────────────
  const fetchAll = useCallback(async () => {
    const [s, p, t, st, acc, pos, hybrid] = await Promise.all([
      getTradeStats(),
      getPerformance(30),
      getTrades({ limit: 5 }),
      getStatus(),
      getAccount(),
      getPositions(),
      getHybridStatus(),
    ]);
    setStats(s);
    setPerf(p);
    setRecentTrades(t.trades || []);
    setStatus(st);
    setAccount(acc);
    setLivePositions(pos.positions || []);
    setInitialLoading(false);
    const tickets = (hybrid.positions || []).map((hp) => hp.ticket).filter(Boolean);
    setHybridTickets(new Set(tickets));
  }, []);

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 30000); // 30sn REST fallback (WS zaten anlık)
    return () => clearInterval(iv);
  }, [fetchAll]);

  // ── Süre yenileme (30sn) ─────────────────────────────────────────
  useEffect(() => {
    const iv = setInterval(() => setTick(new Date()), 30000);
    return () => clearInterval(iv);
  }, []);

  // ── WebSocket canlı veri ─────────────────────────────────────────
  useEffect(() => {
    const { close } = connectLiveWS((messages) => {
      const arr = Array.isArray(messages) ? messages : [messages];
      for (const msg of arr) {
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
        if (msg.type === 'hybrid') {
          const tickets = new Set((msg.positions || []).map((hp) => hp.ticket));
          setHybridTickets(tickets);
        }
        if (msg.type === 'trade_closed' || msg.type === 'position_closed') {
          fetchTradeData();
        }
      }
    });

    wsRef.current = close;
    return () => {
      if (wsRef.current) wsRef.current();
    };
  }, [fetchTradeData]);

  // ── İşlemi Kapat ─────────────────────────────────────────────────
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

  // ── Hibrite Devret ────────────────────────────────────────────────
  const handleTransferToHybrid = useCallback(async (ticket) => {
    if (transferringTicket != null) return;
    setTransferringTicket(ticket);
    try {
      const check = await checkHybridTransfer(ticket);
      if (!check.can_transfer) {
        window.alert('Hibrite devir yapılamaz: ' + (check.reason || 'Bilinmeyen hata'));
        return;
      }
      const result = await transferToHybrid(ticket);
      if (result.success) {
        setHybridTickets((prev) => new Set([...prev, ticket]));
      } else {
        window.alert('Devir hatası: ' + (result.message || 'Bilinmeyen hata'));
      }
    } catch (err) {
      window.alert('Devir hatası: ' + (err?.message ?? String(err)));
    } finally {
      setTransferringTicket(null);
    }
  }, [transferringTicket]);

  // ── Hesaplamalar ─────────────────────────────────────────────────
  const regime = status.regime || 'TREND';
  const totalFloating = (livePositions || []).reduce((s, p) => s + (p.pnl || 0), 0);
  const totalLot = (livePositions || []).reduce((s, p) => s + (p.volume || 0), 0);
  const totalSwap = (livePositions || []).reduce((s, p) => s + (p.swap || 0), 0);
  const eq = liveEquity?.equity ?? account.equity;
  const marginPct = marginUsagePct(account.margin, eq);

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
          label="Teminat"
          value={formatMoney(account.margin)}
        />
        <AccountItem
          label="Serbest Teminat"
          value={formatMoney(account.free_margin)}
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

      {/* ═══ ORTA: Açık Pozisyonlar (TAM ÖZELLİKLİ) ═══════════════ */}
      <div className="dash-positions-row">
        <div className="dash-card dash-card--full">
          <div className="dash-card-header">
            <h3>Açık Pozisyonlar</h3>
            <div className="dash-card-header-right">
              <span className="dash-card-badge">
                {(livePositions || []).length} / 5
              </span>
              {account.margin > 0 && (
                <span className={`dash-margin-badge ${marginPct > 80 ? 'danger' : marginPct > 50 ? 'warn' : ''}`}>
                  Teminat: %{marginPct.toFixed(1)}
                </span>
              )}
            </div>
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
                  <th>Swap</th>
                  <th>K/Z</th>
                  <th>Tür</th>
                  <th>Yönetim</th>
                  <th>Süre</th>
                  <th>Rejim</th>
                  <th>İşlem</th>
                </tr>
              </thead>
              <tbody>
                {(livePositions || []).map((pos) => {
                  const pnl = pos.pnl || 0;
                  const rowCls = pnl > 0 ? 'op-row-profit' : pnl < 0 ? 'op-row-loss' : '';
                  const isHybrid = hybridTickets.has(pos.ticket);

                  // Tür: API'den gelen tur kullan; yoksa fallback
                  const apiTur = (pos.tur || '').trim();
                  let turLabel = apiTur;
                  let turClass = 'manual';
                  if (apiTur === 'Hibrit' || apiTur === 'Otomatik' || apiTur === 'Manuel') {
                    turClass = apiTur === 'Hibrit' ? 'hybrid' : apiTur === 'Otomatik' ? 'auto' : 'manual';
                  } else {
                    const stratLower = (pos.strategy || '').toLowerCase().trim();
                    const isAuto = KNOWN_AUTO_STRATEGIES.includes(stratLower);
                    turLabel = isHybrid ? 'Hibrit' : isAuto ? 'Otomatik' : 'Manuel';
                    turClass = isHybrid ? 'hybrid' : isAuto ? 'auto' : 'manual';
                  }

                  return (
                    <tr key={pos.ticket || pos.symbol} className={rowCls}>
                      <td className="mono op-symbol">{pos.symbol}</td>
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
                      <td className={`mono text-dim ${pnlClass(pos.swap || 0)}`}>
                        {formatMoney(pos.swap || 0)}
                      </td>
                      <td className={`mono op-pnl-cell ${pnlClass(pnl)}`}>
                        <b>{formatMoney(pnl)}</b>
                      </td>
                      <td className="op-tur-cell">
                        <span className={`op-tur-badge op-tur--${turClass}`}>
                          {turLabel}
                        </span>
                      </td>
                      <td className="op-mgmt-cell">
                        {pos.tp1_hit && <span className="op-mgmt-badge op-mgmt--tp1" title="TP1 yarı kapanış yapıldı">TP1</span>}
                        {pos.breakeven_hit && <span className="op-mgmt-badge op-mgmt--be" title="Breakeven çekildi">BE</span>}
                        {pos.cost_averaged && <span className="op-mgmt-badge op-mgmt--avg" title="Maliyetlendirme yapıldı">MA</span>}
                        {(pos.voting_score != null && pos.voting_score > 0) && (
                          <span className={`op-mgmt-badge op-mgmt--vote${pos.voting_score >= 3 ? '-strong' : '-weak'}`}
                            title={`Oylama skoru: ${pos.voting_score}/4`}>
                            {pos.voting_score}/4
                          </span>
                        )}
                      </td>
                      <td className="text-dim">{elapsed(pos.open_time)}</td>
                      <td>
                        <span className={`op-regime-tag op-regime--${(regime || '').toLowerCase()}`}>
                          {regime}
                        </span>
                      </td>
                      <td className="op-action-cell">
                        <button
                          type="button"
                          className="op-close-btn"
                          onClick={() => handleClosePosition(pos.ticket)}
                          disabled={closingTicket === pos.ticket}
                          title="Bu pozisyonu kapat"
                        >
                          {closingTicket === pos.ticket ? 'Kapatılıyor...' : 'İşlemi Kapat'}
                        </button>
                        {isHybrid ? (
                          <button
                            type="button"
                            className="op-hybrid-link-btn"
                            onClick={() => navigate('/hybrid')}
                            title="Hibrit panelinde yönetiliyor — tıklayınca Hibrit İşlem Paneline gider"
                          >
                            Hibritte
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="op-hybrid-btn"
                            onClick={() => handleTransferToHybrid(pos.ticket)}
                            disabled={transferringTicket === pos.ticket}
                            title="Robot yönetimine devret"
                          >
                            {transferringTicket === pos.ticket ? 'Devrediliyor...' : 'Hibrite Devret'}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="op-footer-row">
                  <td colSpan={2}><b>TOPLAM</b></td>
                  <td className="mono"><b>{totalLot.toFixed(2)}</b></td>
                  <td colSpan={4}></td>
                  <td className="mono text-dim">
                    {formatMoney(totalSwap)}
                  </td>
                  <td className={`mono ${pnlClass(totalFloating)}`}>
                    <b>{formatMoney(totalFloating)}</b>
                  </td>
                  <td colSpan={5}></td>
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
//  ALT BİLEŞENLER
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
