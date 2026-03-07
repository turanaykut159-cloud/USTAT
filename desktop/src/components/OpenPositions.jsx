/**
 * ÜSTAT v5.2 — Açık Pozisyonlar ekranı.
 *
 * Tablo:  Sembol, Yön, Lot, Giriş Fiy., Anlık Fiy., SL, TP,
 *         Floating K/Z, Süre, Rejim
 * Özet:   Toplam pozisyon, toplam floating, teminat kullanım oranı
 * Canlı:  WebSocket (position + equity) + REST fallback (5sn)
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { getPositions, getAccount, getStatus, getHybridStatus, connectLiveWS, closePosition, checkHybridTransfer, transferToHybrid } from '../services/api';
import { formatMoney, formatPrice, pnlClass, elapsed } from '../utils/formatters';

// ── Yardımcılar ──────────────────────────────────────────────────

/** Teminat kullanım oranı (%) */
function marginUsagePct(margin, equity) {
  if (!margin || !equity || equity <= 0) return 0;
  return (margin / equity) * 100;
}


// ═══════════════════════════════════════════════════════════════════
//  ANA BİLEŞEN
// ═══════════════════════════════════════════════════════════════════

export default function OpenPositions() {
  const navigate = useNavigate();

  // ── State ────────────────────────────────────────────────────────
  const [positions, setPositions] = useState([]);
  const [account, setAccount] = useState({
    balance: 0, equity: 0, margin: 0, free_margin: 0, floating_pnl: 0,
  });
  const [regime, setRegime] = useState('TREND');
  const [tick, setTick] = useState(new Date()); // süre güncelleme tetikleyici
  const [initialLoading, setInitialLoading] = useState(true);
  const [closingTicket, setClosingTicket] = useState(null); // kapatılan pozisyon ticket (loading)
  const [hybridTickets, setHybridTickets] = useState(new Set()); // hibrit yönetimindeki ticket'lar
  const [transferringTicket, setTransferringTicket] = useState(null); // devir işlemi yapılan ticket
  const wsRef = useRef(null);

  // ── REST fallback (5sn) ──────────────────────────────────────────
  const fetchData = useCallback(async () => {
    const [p, a, s, hybrid] = await Promise.all([
      getPositions(),
      getAccount(),
      getStatus(),
      getHybridStatus(),
    ]);
    setPositions(p.positions || []);
    setAccount(a);
    setRegime(s.regime || 'TREND');
    setInitialLoading(false);
    const tickets = (hybrid.positions || []).map((pos) => pos.ticket).filter(Boolean);
    setHybridTickets(new Set(tickets));
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
        if (msg.type === 'hybrid') {
          const tickets = new Set((msg.positions || []).map((p) => p.ticket));
          setHybridTickets(tickets);
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

  // ── İşlemi Kapat (sadece manuel) ──────────────────────────────────
  const handleClosePosition = useCallback(async (ticket) => {
    if (closingTicket != null) return;
    setClosingTicket(ticket);
    try {
      await closePosition(ticket);
      await fetchData();
    } catch (err) {
      window.alert('Kapatma hatası: ' + (err?.message ?? String(err)));
    } finally {
      setClosingTicket(null);
    }
  }, [closingTicket, fetchData]);

  // ── Hibrite Devret ──────────────────────────────────────────────────
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
  const totalFloating = positions.reduce((s, p) => s + (p.pnl || 0), 0);
  const totalLot = positions.reduce((s, p) => s + (p.volume || 0), 0);
  const marginPct = marginUsagePct(account.margin, account.equity);

  if (initialLoading) {
    return (
      <div className="open-positions">
        <p className="op-loading">Yükleniyor...</p>
      </div>
    );
  }

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
                <th>Swap</th>
                <th>Floating K/Z</th>
                <th>Tür</th>
                <th>Risk</th>
                <th>Yönetim</th>
                <th>Süre</th>
                <th>Rejim</th>
                <th>İşlem</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => {
                const pnl = pos.pnl || 0;
                const rowCls = pnl > 0 ? 'op-row-profit' : pnl < 0 ? 'op-row-loss' : '';
                const isHybrid = hybridTickets.has(pos.ticket);
                // Tür: API'den gelen tur kullan (backend tek kaynak); yoksa fallback
                const apiTur = (pos.tur || '').trim();
                let turLabel = apiTur;
                let turClass = 'manual';
                if (apiTur === 'Hibrit' || apiTur === 'Otomatik' || apiTur === 'Manuel') {
                  turClass = apiTur === 'Hibrit' ? 'hybrid' : apiTur === 'Otomatik' ? 'auto' : 'manual';
                } else {
                  const stratLower = (pos.strategy || '').toLowerCase().trim();
                  const knownAutoStrategies = ['trend_follow', 'mean_reversion', 'breakout'];
                  const isAuto = knownAutoStrategies.includes(stratLower);
                  turLabel = isHybrid ? 'Hibrit' : isAuto ? 'Otomatik' : 'Manuel';
                  turClass = isHybrid ? 'hybrid' : isAuto ? 'auto' : 'manual';
                }
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
                    <td className="op-risk-cell">
                      {turLabel === 'Manuel' && pos.risk_score?.overall ? (
                        <span
                          className={`op-risk-badge op-risk--${pos.risk_score.overall}`}
                          title={`SL: ${pos.risk_score.sl_risk} | Rejim: ${pos.risk_score.regime_risk} | K/Z: ${pos.risk_score.pnl_risk} | Sistem: ${pos.risk_score.system_risk}`}
                        >
                          {pos.risk_score.overall === 'green' ? 'DUSUK' : pos.risk_score.overall === 'yellow' ? 'ORTA' : 'YUKSEK'}
                          <span className="op-risk-score">{pos.risk_score.score}</span>
                        </span>
                      ) : (
                        <span className="text-dim">—</span>
                      )}
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
                          {transferringTicket === pos.ticket ? 'Devrediliyor...' : '🔀 Hibrite Devret'}
                        </button>
                      )}
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
                <td className="mono text-dim">
                  {formatMoney(positions.reduce((s, p) => s + (p.swap || 0), 0))}
                </td>
                <td className={`mono ${pnlClass(totalFloating)}`}>
                  <b>{formatMoney(totalFloating)}</b>
                </td>
                <td colSpan={6}></td>
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
