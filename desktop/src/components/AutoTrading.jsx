/**
 * ÜSTAT v5.1 — Otomatik İşlem Paneli.
 *
 * Layout:
 *   Üst:    4 stat kartı (Durum, Aktif Rejim, Lot Çarpanı, Oto. İşlem)
 *   Orta:   Sol — Top 5 Kontrat, Sağ — Otomatik Pozisyonlar
 *   Alt:    Son Otomatik İşlemler (tam genişlik)
 *
 * Veri kaynakları:
 *   REST:  getStatus, getTop5, getPositions, getTrades (10sn poll)
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  getStatus, getTop5, getPositions, getTrades, reactivateSymbols,
  getOgulActivity,
} from '../services/api';
import { formatMoney, formatPrice, pnlClass } from '../utils/formatters';

// ── Yardımcılar ──────────────────────────────────────────────────

function shortTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleString('tr-TR', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return '';
  }
}

// ── Rejim renk eşlemesi ──────────────────────────────────────────
const REGIME_META = {
  TREND:    { color: 'var(--profit)',  bg: 'rgba(63,185,80,0.1)',  label: 'Trend',    strategies: 'Trend Follow' },
  RANGE:    { color: 'var(--accent)',  bg: 'rgba(88,166,255,0.1)', label: 'Range',    strategies: 'MR + Breakout' },
  VOLATILE: { color: 'var(--warning)', bg: 'rgba(210,153,34,0.1)', label: 'Volatile', strategies: 'Sinyal yok' },
  OLAY:     { color: 'var(--loss)',    bg: 'rgba(248,81,73,0.1)',  label: 'Olay',     strategies: 'Sistem pause' },
};

// Otomatik strateji isimleri
const AUTO_STRATEGIES = new Set(['trend_follow', 'mean_reversion', 'breakout']);

// ═══════════════════════════════════════════════════════════════════
//  OTOMATİK İŞLEM PANELİ
// ═══════════════════════════════════════════════════════════════════

export default function AutoTrading() {
  const [status, setStatus] = useState({
    regime: 'TREND', regime_confidence: 0,
    engine_running: false, kill_switch_level: 0,
    risk_multiplier: 1, phase: 'stopped',
    deactivated_symbols: [],
  });
  const [top5, setTop5] = useState({ contracts: [] });
  const [autoPositions, setAutoPositions] = useState([]);
  const [autoTrades, setAutoTrades] = useState([]);
  const [autoTradeCount, setAutoTradeCount] = useState(0);
  const [ogulActivity, setOgulActivity] = useState({
    signals: [], unopened: [], scan_symbols: 0,
    signal_count: 0, unopened_count: 0,
    last_m15_close: '', regime: 'TREND',
    active_strategies: [], adx_value: 0,
  });
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    const [st, t5, pos, trades, ogul] = await Promise.all([
      getStatus(),
      getTop5(),
      getPositions(),
      getTrades({ limit: 50 }),
      getOgulActivity(),
    ]);
    setStatus(st);
    setTop5(t5);
    setOgulActivity(ogul);

    // Otomatik pozisyonları filtrele
    const allPos = pos.positions || [];
    setAutoPositions(allPos.filter((p) => p.tur === 'Otomatik'));

    // Otomatik işlemleri filtrele (son 10)
    const allTrades = trades.trades || [];
    const autoOnly = allTrades.filter((t) =>
      AUTO_STRATEGIES.has((t.strategy || '').toLowerCase())
    );
    setAutoTrades(autoOnly.slice(0, 10));
    setAutoTradeCount(autoOnly.length);

    setLoading(false);
  }, []);

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 10000);
    return () => clearInterval(iv);
  }, [fetchAll]);

  // ── Hesaplamalar ─────────────────────────────────────────────────
  const regime = status.regime || 'TREND';
  const regimeMeta = REGIME_META[regime] || REGIME_META.TREND;
  const ksLevel = status.kill_switch_level || 0;
  const mult = status.risk_multiplier ?? 1;

  // Durum belirleme
  let durumLabel, durumColor;
  if (!status.engine_running) {
    durumLabel = 'KAPALI';
    durumColor = 'var(--text-dim)';
  } else if (ksLevel >= 2) {
    durumLabel = 'DURDURULDU';
    durumColor = 'var(--loss)';
  } else if (ksLevel === 1) {
    durumLabel = 'KISITLI';
    durumColor = 'var(--warning)';
  } else {
    durumLabel = 'AKTİF';
    durumColor = 'var(--profit)';
  }

  // Lot çarpanı renk
  let multColor = 'var(--profit)';
  if (mult === 0) multColor = 'var(--loss)';
  else if (mult <= 0.25) multColor = 'var(--warning)';
  else if (mult < 1) multColor = 'var(--accent)';

  if (loading) {
    return (
      <div className="auto-page">
        <p className="auto-loading">Yükleniyor...</p>
      </div>
    );
  }

  return (
    <div className="auto-page">
      <h2 className="auto-title">Otomatik İşlem Paneli</h2>

      {/* ═══ ÜST: 4 Stat Kartı ════════════════════════════════════ */}
      <div className="auto-stats-row">
        {/* 1. Durum */}
        <div className="auto-stat-card">
          <div className="auto-stat-label">DURUM</div>
          <div className="auto-stat-value" style={{ color: durumColor }}>
            {durumLabel}
          </div>
          <div className="auto-stat-sub">
            {ksLevel > 0 ? `Kill-Switch L${ksLevel}` : 'Kill-Switch yok'}
          </div>
        </div>

        {/* 2. Aktif Rejim */}
        <div className="auto-stat-card">
          <div className="auto-stat-label">AKTİF REJİM</div>
          <div className="auto-stat-value">
            <span
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
            </span>
          </div>
          <div className="auto-stat-sub">{regimeMeta.strategies}</div>
        </div>

        {/* 3. Lot Çarpanı */}
        <div className="auto-stat-card">
          <div className="auto-stat-label">LOT ÇARPANI</div>
          <div className="auto-stat-value" style={{ color: multColor }}>
            x{mult.toFixed(2)}
          </div>
          <div className="auto-stat-sub">
            {mult === 0 ? 'İşlem izni yok' : mult < 1 ? 'Azaltılmış' : 'Normal'}
          </div>
        </div>

        {/* 4. Oto. İşlem Sayısı */}
        <div className="auto-stat-card">
          <div className="auto-stat-label">OTO. İŞLEM</div>
          <div className="auto-stat-value" style={{ color: 'var(--text-primary)' }}>
            {autoTradeCount}
          </div>
          <div className="auto-stat-sub">
            Açık poz: {autoPositions.length}
          </div>
        </div>
      </div>

      {/* ═══ ORTA: Top 5 + Otomatik Pozisyonlar ═══════════════════ */}
      <div className="auto-main-row">

        {/* ── Sol: Top 5 Kontrat ────────────────────────────────── */}
        <div className="auto-card">
          <div className="dash-top5">
            <div className="dash-top5-header">
              <h3>Top 5 Kontrat</h3>
              {top5.last_refresh && (
                <span className="top5-refresh-time">
                  {shortTime(top5.last_refresh)}
                </span>
              )}
            </div>

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
              <div className="auto-empty-msg">Top 5 verisi yok</div>
            )}
          </div>
        </div>

        {/* ── Sağ: Otomatik Pozisyonlar ─────────────────────────── */}
        <div className="auto-card">
          <h3>Otomatik Pozisyonlar</h3>
          {autoPositions.length > 0 ? (
            <table className="auto-table">
              <thead>
                <tr>
                  <th>Sembol</th>
                  <th>Yön</th>
                  <th>Strateji</th>
                  <th>Lot</th>
                  <th>Giriş</th>
                  <th>Anlık</th>
                  <th>K/Z</th>
                </tr>
              </thead>
              <tbody>
                {autoPositions.map((pos) => (
                  <tr key={pos.ticket}>
                    <td className="mono">{pos.symbol}</td>
                    <td>
                      <span className={`dir-badge dir-badge--${(pos.direction || '').toLowerCase()}`}>
                        {pos.direction}
                      </span>
                    </td>
                    <td className="text-dim">{pos.strategy || '—'}</td>
                    <td className="mono">{pos.volume?.toFixed(2) ?? '—'}</td>
                    <td className="mono">{formatPrice(pos.entry_price)}</td>
                    <td className="mono">{formatPrice(pos.current_price)}</td>
                    <td className={`mono ${pnlClass(pos.pnl)}`}>
                      <b>{formatMoney(pos.pnl)}</b>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="auto-empty-msg">Açık otomatik pozisyon yok</div>
          )}
        </div>
      </div>

      {/* ═══ ALT: Son Otomatik İşlemler ════════════════════════════ */}
      <div className="auto-trades-row">
        <div className="auto-card">
          <h3>Son Otomatik İşlemler</h3>
          {autoTrades.length > 0 ? (
            <table className="auto-table">
              <thead>
                <tr>
                  <th>Sembol</th>
                  <th>Yön</th>
                  <th>Strateji</th>
                  <th>Lot</th>
                  <th>K/Z</th>
                  <th>Rejim</th>
                  <th>Zaman</th>
                </tr>
              </thead>
              <tbody>
                {autoTrades.map((t, i) => (
                  <tr key={t.id || i}>
                    <td className="mono">{t.symbol}</td>
                    <td>
                      <span className={`dir-badge dir-badge--${(t.direction || '').toLowerCase()}`}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="text-dim">{t.strategy || '—'}</td>
                    <td className="mono">{t.lot?.toFixed(2) ?? '—'}</td>
                    <td className={`mono ${pnlClass(t.pnl)}`}>
                      {formatMoney(t.pnl)}
                    </td>
                    <td className="text-dim">{t.regime || '—'}</td>
                    <td className="text-dim">{shortTime(t.exit_time || t.entry_time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="auto-empty-msg">Henüz otomatik işlem yok</div>
          )}
        </div>
      </div>

      {/* ═══ OĞUL AKTİVİTE — Sinyal Tarama Durumu ═══════════════════ */}
      <div className="auto-trades-row">
        <div className="auto-card ogul-activity-card">
          <div className="ogul-header">
            <h3>Oğul Aktivite</h3>
            <div className="ogul-header-meta">
              {ogulActivity.last_m15_close && (
                <span className="ogul-m15-label">
                  Son M15: {ogulActivity.last_m15_close.replace('T', ' ').slice(0, 16)}
                </span>
              )}
              <span className="ogul-strategy-label">
                {ogulActivity.active_strategies?.length > 0
                  ? ogulActivity.active_strategies.join(' + ')
                  : 'Strateji yok'}
              </span>
              {ogulActivity.adx_value > 0 && (
                <span className="ogul-adx-label">
                  ADX: {ogulActivity.adx_value}
                </span>
              )}
            </div>
          </div>

          {/* ── Sayaçlar ─────────────────────────────────────────── */}
          <div className="ogul-counters">
            <div className="ogul-counter">
              <span className="ogul-counter-val">{ogulActivity.scan_symbols}</span>
              <span className="ogul-counter-lbl">Tarama</span>
            </div>
            <div className="ogul-counter">
              <span className="ogul-counter-val" style={{
                color: ogulActivity.signal_count > 0 ? 'var(--profit)' : 'var(--text-dim)'
              }}>
                {ogulActivity.signal_count}
              </span>
              <span className="ogul-counter-lbl">Sinyal</span>
            </div>
            <div className="ogul-counter">
              <span className="ogul-counter-val" style={{
                color: ogulActivity.unopened_count > 0 ? 'var(--warning)' : 'var(--text-dim)'
              }}>
                {ogulActivity.unopened_count}
              </span>
              <span className="ogul-counter-lbl">Reddedilen</span>
            </div>
          </div>

          {/* ── Oylama Detayı (Top-5) ────────────────────────────── */}
          {(ogulActivity.signals || []).length > 0 ? (
            <table className="auto-table ogul-vote-table">
              <thead>
                <tr>
                  <th>Sembol</th>
                  <th>Yön</th>
                  <th>RSI</th>
                  <th>EMA</th>
                  <th>ATR</th>
                  <th>Hacim</th>
                  <th>Oy</th>
                </tr>
              </thead>
              <tbody>
                {ogulActivity.signals.map((s) => {
                  const totalVotes = s.buy_votes + s.sell_votes;
                  const favorable = Math.max(s.buy_votes, s.sell_votes);
                  return (
                    <tr key={s.symbol}>
                      <td className="mono">{s.symbol}</td>
                      <td>
                        <span className={`dir-badge dir-badge--${s.direction.toLowerCase()}`}>
                          {s.direction}
                        </span>
                      </td>
                      <td>
                        <span className={`ogul-vote-chip ogul-vote-${s.rsi_vote.toLowerCase()}`}>
                          {s.rsi_vote === 'BUY' ? '▲' : s.rsi_vote === 'SELL' ? '▼' : '—'}
                        </span>
                      </td>
                      <td>
                        <span className={`ogul-vote-chip ogul-vote-${s.ema_vote.toLowerCase()}`}>
                          {s.ema_vote === 'BUY' ? '▲' : s.ema_vote === 'SELL' ? '▼' : '—'}
                        </span>
                      </td>
                      <td>
                        <span className={`ogul-vote-chip ${s.atr_expanding ? 'ogul-vote-active' : 'ogul-vote-notr'}`}>
                          {s.atr_expanding ? '✓' : '—'}
                        </span>
                      </td>
                      <td>
                        <span className={`ogul-vote-chip ${s.volume_above_avg ? 'ogul-vote-active' : 'ogul-vote-notr'}`}>
                          {s.volume_above_avg ? '✓' : '—'}
                        </span>
                      </td>
                      <td className="mono">
                        <span className={`ogul-score ${favorable >= 3 ? 'ogul-score-strong' : favorable >= 2 ? 'ogul-score-mid' : 'ogul-score-weak'}`}>
                          {favorable}/{totalVotes || 4}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div className="auto-empty-msg">Oylama verisi yok</div>
          )}

          {/* ── Açılamayan İşlemler ──────────────────────────────── */}
          {(ogulActivity.unopened || []).length > 0 && (
            <div className="ogul-unopened">
              <h4>Açılamayan İşlemler</h4>
              {ogulActivity.unopened.map((u, i) => (
                <div key={i} className="ogul-unopened-item">
                  <span className="ogul-unopened-time">
                    {u.timestamp?.slice(11, 16) || ''}
                  </span>
                  <span className="ogul-unopened-msg">{u.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
