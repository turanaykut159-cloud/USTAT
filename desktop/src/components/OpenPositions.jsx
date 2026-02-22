/**
 * ÜSTAT v5.0 — Açık Pozisyonlar ekranı.
 *
 * Tablo:  Sembol, Yön, Lot, Giriş Fiy., Anlık Fiy., SL, TP,
 *         Floating K/Z, Süre, Rejim
 * Özet:   Toplam pozisyon, toplam floating, teminat kullanım oranı
 * Canlı:  WebSocket (position + equity) + REST fallback (5sn)
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { getPositions, getAccount, getStatus, connectLiveWS } from '../services/api';

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

function formatPrice(val) {
  if (val == null || isNaN(val) || val === 0) return '—';
  return val.toLocaleString('tr-TR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 5,
  });
}

function pnlClass(val) {
  if (val > 0) return 'profit';
  if (val < 0) return 'loss';
  return '';
}

/** Açılış zamanından itibaren süre */
function elapsed(openTime) {
  if (!openTime) return '—';
  try {
    const ms = Date.now() - new Date(openTime).getTime();
    if (isNaN(ms) || ms < 0) return '—';
    const totalMin = Math.floor(ms / 60000);
    if (totalMin < 60) return `${totalMin}dk`;
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    if (h < 24) return `${h}s ${m}dk`;
    const d = Math.floor(h / 24);
    return `${d}g ${h % 24}s`;
  } catch {
    return '—';
  }
}

/** Teminat kullanım oranı (%) */
function marginUsagePct(margin, equity) {
  if (!margin || !equity || equity <= 0) return 0;
  return (margin / equity) * 100;
}


// ═══════════════════════════════════════════════════════════════════
//  ANA BİLEŞEN
// ═══════════════════════════════════════════════════════════════════

export default function OpenPositions() {
  // ── State ────────────────────────────────────────────────────────
  const [positions, setPositions] = useState([]);
  const [account, setAccount] = useState({
    balance: 0, equity: 0, margin: 0, free_margin: 0, floating_pnl: 0,
  });
  const [regime, setRegime] = useState('TREND');
  const [tick, setTick] = useState(new Date()); // süre güncelleme tetikleyici
  const wsRef = useRef(null);

  // ── REST fallback (5sn) ──────────────────────────────────────────
  const fetchData = useCallback(async () => {
    const [p, a, s] = await Promise.all([
      getPositions(),
      getAccount(),
      getStatus(),
    ]);
    setPositions(p.positions || []);
    setAccount(a);
    setRegime(s.regime || 'TREND');
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 5000);
    return () => clearInterval(iv);
  }, [fetchData]);

  // ── WebSocket canlı veri ─────────────────────────────────────────
  useEffect(() => {
    const { close } = connectLiveWS((messages) => {
      if (!Array.isArray(messages)) return;
      for (const msg of messages) {
        if (msg.type === 'position') {
          setPositions(msg.positions || []);
        }
        if (msg.type === 'equity') {
          setAccount((prev) => ({
            ...prev,
            equity: msg.equity ?? prev.equity,
            balance: msg.balance ?? prev.balance,
            floating_pnl: msg.floating_pnl ?? prev.floating_pnl,
          }));
        }
        if (msg.type === 'status') {
          setRegime(msg.regime || 'TREND');
        }
      }
    });
    wsRef.current = close;
    return () => { if (wsRef.current) wsRef.current(); };
  }, []);

  // ── Süre yenileme (30sn) ─────────────────────────────────────────
  useEffect(() => {
    const iv = setInterval(() => setTick(new Date()), 30000);
    return () => clearInterval(iv);
  }, []);

  // ── Hesaplamalar ─────────────────────────────────────────────────
  const totalFloating = positions.reduce((s, p) => s + (p.pnl || 0), 0);
  const totalLot = positions.reduce((s, p) => s + (p.volume || 0), 0);
  const marginPct = marginUsagePct(account.margin, account.equity);

  return (
    <div className="open-positions">
      <h2>Açık Pozisyonlar</h2>

      {/* ═══ ÖZET KARTLAR ══════════════════════════════════════════ */}
      <div className="op-summary-row">
        <div className="op-summary-card">
          <span className="op-sc-label">Açık Pozisyon</span>
          <span className="op-sc-value">{positions.length}</span>
        </div>
        <div className="op-summary-card">
          <span className="op-sc-label">Toplam Lot</span>
          <span className="op-sc-value">{totalLot.toFixed(2)}</span>
        </div>
        <div className="op-summary-card">
          <span className="op-sc-label">Toplam Floating</span>
          <span className={`op-sc-value ${pnlClass(totalFloating)}`}>
            {formatMoney(totalFloating)}
          </span>
        </div>
        <div className="op-summary-card">
          <span className="op-sc-label">Teminat Kullanımı</span>
          <div className="op-margin-wrap">
            <span className={`op-sc-value ${marginPct > 80 ? 'loss' : marginPct > 50 ? 'warning-text' : ''}`}>
              %{marginPct.toFixed(1)}
            </span>
            <div className="op-margin-bar">
              <div
                className={`op-margin-fill ${marginPct > 80 ? 'danger' : marginPct > 50 ? 'warn' : ''}`}
                style={{ width: `${Math.min(marginPct, 100)}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* ═══ POZİSYON TABLOSU ══════════════════════════════════════ */}
      <div className="op-table-wrap">
        {positions.length === 0 ? (
          <div className="op-empty">
            <span className="op-empty-icon">📭</span>
            <span>Açık pozisyon yok</span>
          </div>
        ) : (
          <table className="op-table">
            <thead>
              <tr>
                <th>Sembol</th>
                <th>Yön</th>
                <th>Lot</th>
                <th>Giriş Fiy.</th>
                <th>Anlık Fiy.</th>
                <th>SL</th>
                <th>TP</th>
                <th>Floating K/Z</th>
                <th>Süre</th>
                <th>Rejim</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => {
                const pnl = pos.pnl || 0;
                const rowCls = pnl > 0 ? 'op-row-profit' : pnl < 0 ? 'op-row-loss' : '';
                return (
                  <tr key={pos.ticket} className={rowCls}>
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
                    <td className={`mono op-pnl-cell ${pnlClass(pnl)}`}>
                      <b>{formatMoney(pnl)}</b>
                    </td>
                    <td className="text-dim">{elapsed(pos.open_time)}</td>
                    <td>
                      <span className={`op-regime-tag op-regime--${(regime || '').toLowerCase()}`}>
                        {regime}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>

            {/* Alt toplam satırı */}
            <tfoot>
              <tr className="op-footer-row">
                <td colSpan={2}><b>TOPLAM</b></td>
                <td className="mono"><b>{totalLot.toFixed(2)}</b></td>
                <td colSpan={4}></td>
                <td className={`mono ${pnlClass(totalFloating)}`}>
                  <b>{formatMoney(totalFloating)}</b>
                </td>
                <td colSpan={2}></td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>

      {/* ═══ ALT BİLGİ SATIRI ══════════════════════════════════════ */}
      <div className="op-info-bar">
        <div className="op-info-item">
          <span className="op-info-label">Bakiye</span>
          <span className="op-info-value">{formatMoney(account.balance)}</span>
        </div>
        <div className="op-info-sep" />
        <div className="op-info-item">
          <span className="op-info-label">Equity</span>
          <span className="op-info-value">{formatMoney(account.equity)}</span>
        </div>
        <div className="op-info-sep" />
        <div className="op-info-item">
          <span className="op-info-label">Teminat</span>
          <span className="op-info-value">{formatMoney(account.margin)}</span>
        </div>
        <div className="op-info-sep" />
        <div className="op-info-item">
          <span className="op-info-label">Serbest Teminat</span>
          <span className="op-info-value">{formatMoney(account.free_margin)}</span>
        </div>
        <div className="op-info-sep" />
        <div className="op-info-item">
          <span className="op-info-label">Floating</span>
          <span className={`op-info-value ${pnlClass(account.floating_pnl)}`}>
            {formatMoney(account.floating_pnl)}
          </span>
        </div>
      </div>
    </div>
  );
}
