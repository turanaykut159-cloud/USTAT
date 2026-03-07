/**
 * ÜSTAT v5.1 — Hibrit İşlem Paneli.
 *
 * İnsan işlemi açar, robot yönetir ve kapatır.
 * Açık pozisyonlardan seçerek hibrite devredilir.
 *
 * Akış:
 *   1. Açık pozisyon seç → "Kontrol Et"
 *   2. H-Baba ön kontrolü (POST /api/hybrid/check)
 *   3. Sonuç göster → SL/TP önerileri → "Hibrite Devret"
 *   4. Atomik devir (POST /api/hybrid/transfer)
 *
 * Canlı güncelleme: WebSocket (type: "hybrid") + REST fallback (10sn)
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  getPositions,
  checkHybridTransfer,
  transferToHybrid,
  removeFromHybrid,
  getHybridStatus,
  getHybridEvents,
  connectLiveWS,
} from '../services/api';
import { formatMoney, formatPrice, pnlClass, elapsed } from '../utils/formatters';

// ── Yardımcı fonksiyonlar ───────────────────────────────────────

/** Hibrit pozisyon durumu etiketi */
function stateLabel(hp) {
  if (hp.trailing_active) return 'Trailing';
  if (hp.breakeven_hit) return 'Breakeven';
  return 'Aktif';
}

function stateBadgeClass(hp) {
  if (hp.trailing_active) return 'ht-state--trailing';
  if (hp.breakeven_hit) return 'ht-state--breakeven';
  return 'ht-state--active';
}


// ═══════════════════════════════════════════════════════════════════
//  ANA BİLEŞEN
// ═══════════════════════════════════════════════════════════════════

export default function HybridTrade() {
  // ── State ────────────────────────────────────────────────────
  const [openPositions, setOpenPositions] = useState([]);
  const [selectedTicket, setSelectedTicket] = useState('');
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState(null);
  const [transferring, setTransferring] = useState(false);
  const [transferResult, setTransferResult] = useState(null);

  // Hibrit durum
  const [hybridStatus, setHybridStatus] = useState({
    active_count: 0, max_count: 3, daily_pnl: 0, daily_limit: 500, positions: [],
  });
  const [hybridEvents, setHybridEvents] = useState([]);
  const [removingTicket, setRemovingTicket] = useState(null);
  const [tick, setTick] = useState(new Date()); // süre güncelleme

  const wsRef = useRef(null);

  // ── Açık pozisyonları çek (hibrit olmayanları filtrele) ─────
  const fetchOpenPositions = useCallback(async () => {
    const [posRes, hStatus] = await Promise.all([
      getPositions(),
      getHybridStatus(),
    ]);
    const hybridTickets = new Set((hStatus.positions || []).map((p) => p.ticket));
    const nonHybrid = (posRes.positions || []).filter(
      (p) => !hybridTickets.has(p.ticket)
    );
    setOpenPositions(nonHybrid);
    setHybridStatus(hStatus);
  }, []);

  const fetchEvents = useCallback(async () => {
    const res = await getHybridEvents({ limit: 20 });
    setHybridEvents(res.events || []);
  }, []);

  // ── REST fallback (10sn) ─────────────────────────────────────
  useEffect(() => {
    fetchOpenPositions();
    fetchEvents();
    const iv = setInterval(() => {
      fetchOpenPositions();
      fetchEvents();
    }, 10000);
    return () => clearInterval(iv);
  }, [fetchOpenPositions, fetchEvents]);

  // ── WebSocket canlı veri ─────────────────────────────────────
  useEffect(() => {
    const { close } = connectLiveWS((messages) => {
      if (!Array.isArray(messages)) return;
      for (const msg of messages) {
        if (msg.type === 'hybrid') {
          setHybridStatus((prev) => ({
            ...prev,
            positions: msg.positions || [],
            daily_pnl: msg.daily_pnl ?? prev.daily_pnl,
            daily_limit: msg.daily_limit ?? prev.daily_limit,
            active_count: (msg.positions || []).length,
          }));
        }
      }
    });
    wsRef.current = close;
    return () => { if (wsRef.current) wsRef.current(); };
  }, []);

  // ── Süre yenileme (30sn) ─────────────────────────────────────
  useEffect(() => {
    const iv = setInterval(() => setTick(new Date()), 30000);
    return () => clearInterval(iv);
  }, []);

  // ── Kontrol Et ───────────────────────────────────────────────
  const handleCheck = useCallback(async () => {
    if (!selectedTicket) return;
    setChecking(true);
    setCheckResult(null);
    setTransferResult(null);

    const result = await checkHybridTransfer(parseInt(selectedTicket, 10));
    setCheckResult(result);
    setChecking(false);
  }, [selectedTicket]);

  // ── Hibrite Devret ───────────────────────────────────────────
  const handleTransfer = useCallback(async () => {
    if (!selectedTicket) return;
    setTransferring(true);

    const result = await transferToHybrid(parseInt(selectedTicket, 10));
    setTransferResult(result);
    setTransferring(false);

    if (result.success) {
      // Listeyi güncelle
      setTimeout(() => {
        fetchOpenPositions();
        fetchEvents();
        setSelectedTicket('');
        setCheckResult(null);
        setTransferResult(null);
      }, 2000);
    }
  }, [selectedTicket, fetchOpenPositions, fetchEvents]);

  // ── Hibritten Çıkar ──────────────────────────────────────────
  const handleRemove = useCallback(async (ticket) => {
    if (removingTicket != null) return;
    setRemovingTicket(ticket);
    try {
      await removeFromHybrid(ticket);
      await fetchOpenPositions();
      await fetchEvents();
    } catch (err) {
      window.alert('Çıkarma hatası: ' + (err?.message ?? String(err)));
    } finally {
      setRemovingTicket(null);
    }
  }, [removingTicket, fetchOpenPositions, fetchEvents]);

  // ── Sıfırla ──────────────────────────────────────────────────
  const handleReset = useCallback(() => {
    setSelectedTicket('');
    setCheckResult(null);
    setTransferResult(null);
  }, []);

  // ── Hesaplamalar ─────────────────────────────────────────────
  const hybridPositions = hybridStatus.positions || [];
  const totalHybridPnl = hybridPositions.reduce((s, p) => s + (p.pnl || 0), 0);
  const limitUsedPct = hybridStatus.daily_limit > 0
    ? Math.abs(hybridStatus.daily_pnl) / hybridStatus.daily_limit * 100
    : 0;

  const nativeSltp = hybridStatus.native_sltp ?? false;

  return (
    <div className="hybrid-trade">
      <h2>
        Hibrit İşlem Paneli
        <span
          className={`ht-sltp-badge ${nativeSltp ? 'ht-sltp--native' : 'ht-sltp--software'}`}
          title={nativeSltp
            ? 'SL/TP MT5 native emirleriyle yönetiliyor'
            : 'SL/TP yazılımsal olarak H-Oğul tarafından yönetiliyor (10sn aralıklı fiyat kontrolü)'
          }
        >
          {nativeSltp ? 'MT5 SL/TP' : 'Yazılımsal SL/TP'}
        </span>
      </h2>

      {/* ═══ ÖZET KARTLAR ════════════════════════════════════════ */}
      <div className="op-summary-row">
        <div className="op-summary-card">
          <span className="op-sc-label">Aktif Hibrit</span>
          <span className="op-sc-value">
            {hybridStatus.active_count} / {hybridStatus.max_count}
          </span>
        </div>
        <div className="op-summary-card">
          <span className="op-sc-label">Anlık Floating</span>
          <span className={`op-sc-value ${pnlClass(totalHybridPnl)}`}>
            {formatMoney(totalHybridPnl)}
          </span>
        </div>
        <div className="op-summary-card">
          <span className="op-sc-label">Günlük Hibrit K/Z</span>
          <span className={`op-sc-value ${pnlClass(hybridStatus.daily_pnl)}`}>
            {formatMoney(hybridStatus.daily_pnl)}
          </span>
        </div>
        <div className="op-summary-card">
          <span className="op-sc-label">Günlük Limit</span>
          <div className="op-margin-wrap">
            <span className={`op-sc-value ${limitUsedPct > 80 ? 'loss' : limitUsedPct > 50 ? 'warning-text' : ''}`}>
              %{limitUsedPct.toFixed(0)} / {formatMoney(hybridStatus.daily_limit)}
            </span>
            <div className="op-margin-bar">
              <div
                className={`op-margin-fill ${limitUsedPct > 80 ? 'danger' : limitUsedPct > 50 ? 'warn' : ''}`}
                style={{ width: `${Math.min(limitUsedPct, 100)}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* ═══ DEVİR FORMU + RİSK ÖZETİ ═══════════════════════════ */}
      <div className="mt-layout">
        {/* ── SOL PANEL: Form ──────────────────────────────────── */}
        <div className="mt-form">
          {/* Pozisyon Seçimi */}
          <div className="mt-form-group">
            <label>Açık Pozisyon Seç</label>
            {openPositions.length === 0 ? (
              <div style={{ color: 'var(--text-dim)', fontSize: '13px', padding: '8px 0' }}>
                Devir edilebilir açık pozisyon yok
              </div>
            ) : (
              <select
                className="mt-select"
                value={selectedTicket}
                onChange={(e) => { setSelectedTicket(e.target.value); setCheckResult(null); setTransferResult(null); }}
                disabled={transferring}
              >
                <option value="">-- Pozisyon seç --</option>
                {openPositions.map((p) => (
                  <option key={p.ticket} value={p.ticket}>
                    #{p.ticket} — {p.symbol} {p.direction} {p.volume} lot ({formatMoney(p.pnl)} TRY)
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Kontrol Et butonu */}
          {selectedTicket && !checkResult && (
            <button
              className="mt-check-btn"
              onClick={handleCheck}
              disabled={checking}
            >
              {checking ? 'Kontrol ediliyor...' : 'Kontrol Et'}
            </button>
          )}

          {/* Kontrol sonucu — SL/TP önerileri */}
          {checkResult && checkResult.can_transfer && (
            <div className="mt-form-group">
              <label>Devir Bilgileri</label>
              <div className="mt-price-info">
                Sembol: <b>{checkResult.symbol}</b> {checkResult.direction}
              </div>
              <div className="mt-price-info">
                Giriş Fiyatı: {formatPrice(checkResult.entry_price)}
              </div>
              <div className="mt-price-info">
                Güncel Fiyat: {formatPrice(checkResult.current_price)}
              </div>
              <div className="mt-price-info">
                ATR(14): {formatPrice(checkResult.atr_value)}
              </div>
              <div className="mt-price-info">
                SL: {formatPrice(checkResult.suggested_sl)} ({checkResult.direction === 'BUY' ? '-' : '+'}2×ATR)
              </div>
              <div className="mt-price-info">
                TP: {formatPrice(checkResult.suggested_tp)} ({checkResult.direction === 'BUY' ? '+' : '-'}2×ATR)
              </div>
            </div>
          )}

          {/* Red mesajı */}
          {checkResult && !checkResult.can_transfer && (
            <div className="mt-status-fail">{checkResult.reason}</div>
          )}

          {/* Hibrite Devret butonu */}
          {checkResult && checkResult.can_transfer && !transferResult && (
            <button
              className="mt-execute-btn"
              onClick={handleTransfer}
              disabled={transferring}
            >
              {transferring
                ? 'Devrediliyor...'
                : `${checkResult.symbol} — Hibrite Devret`}
            </button>
          )}

          {/* Devir sonucu */}
          {transferResult && (
            <div className={`mt-result ${transferResult.success ? 'success' : 'error'}`}>
              {transferResult.success
                ? `Hibrite devredildi! SL: ${formatPrice(transferResult.sl)} TP: ${formatPrice(transferResult.tp)}`
                : `Hata: ${transferResult.message}`}
            </div>
          )}

          {/* Sıfırla butonu */}
          {(checkResult || transferResult) && (
            <button className="mt-check-btn" onClick={handleReset} style={{ marginTop: '8px' }}>
              Sıfırla
            </button>
          )}
        </div>

        {/* ── SAĞ PANEL: Risk Özeti ─────────────────────────────── */}
        <div className="mt-risk-panel">
          <h3 style={{ margin: '0 0 12px', fontSize: '13px', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Hibrit Risk Özeti
          </h3>

          <div className="mt-risk-row">
            <span className="mt-risk-label">Aktif Hibrit</span>
            <span className="mt-risk-value">
              {hybridStatus.active_count} / {hybridStatus.max_count}
            </span>
          </div>
          <div className="mt-risk-row">
            <span className="mt-risk-label">Günlük K/Z</span>
            <span className="mt-risk-value" style={{ color: (hybridStatus.daily_pnl || 0) >= 0 ? '#4CAF50' : '#F44336' }}>
              {formatMoney(hybridStatus.daily_pnl)} TRY
            </span>
          </div>
          <div className="mt-risk-row">
            <span className="mt-risk-label">Günlük Limit</span>
            <span className="mt-risk-value">{formatMoney(hybridStatus.daily_limit)} TRY</span>
          </div>
          <div className="mt-risk-row">
            <span className="mt-risk-label">Anlık Floating</span>
            <span className="mt-risk-value" style={{ color: totalHybridPnl >= 0 ? '#4CAF50' : '#F44336' }}>
              {formatMoney(totalHybridPnl)} TRY
            </span>
          </div>

          {checkResult && checkResult.can_transfer && (
            <>
              <div style={{ borderTop: '1px solid var(--border)', margin: '8px 0' }} />
              <div className="mt-risk-row">
                <span className="mt-risk-label">ATR Değeri</span>
                <span className="mt-risk-value">{formatPrice(checkResult.atr_value)}</span>
              </div>
            </>
          )}

          {hybridStatus.active_count >= hybridStatus.max_count && (
            <div className="mt-status-fail" style={{ marginTop: '12px' }}>
              Eşzamanlı limit dolu
            </div>
          )}
        </div>
      </div>

      {/* ═══ AKTİF HİBRİT POZİSYONLAR ══════════════════════════ */}
      <div className="op-table-wrap" style={{ marginTop: '20px' }}>
        <h3 style={{ margin: '0 0 8px', fontSize: '14px', fontWeight: 600 }}>
          Aktif Hibrit Pozisyonlar
        </h3>
        {hybridPositions.length === 0 ? (
          <div className="op-empty">
            <span className="op-empty-icon">🔀</span>
            <span>Hibrit yönetiminde pozisyon yok</span>
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
                <th>K/Z</th>
                <th>Durum</th>
                <th>Süre</th>
                <th>İşlem</th>
              </tr>
            </thead>
            <tbody>
              {hybridPositions.map((hp) => {
                const hpPnl = hp.pnl || 0;
                const rowCls = hpPnl > 0 ? 'op-row-profit' : hpPnl < 0 ? 'op-row-loss' : '';
                return (
                  <tr key={hp.ticket} className={rowCls}>
                    <td className="mono op-symbol">{hp.symbol}</td>
                    <td>
                      <span className={`dir-badge dir-badge--${(hp.direction || '').toLowerCase()}`}>
                        {hp.direction}
                      </span>
                    </td>
                    <td className="mono">{hp.volume?.toFixed(2) ?? '\u2014'}</td>
                    <td className="mono">{formatPrice(hp.entry_price)}</td>
                    <td className="mono">{formatPrice(hp.current_price)}</td>
                    <td className="mono text-dim">{formatPrice(hp.current_sl)}</td>
                    <td className="mono text-dim">{formatPrice(hp.current_tp)}</td>
                    <td className={`mono op-pnl-cell ${pnlClass(hpPnl)}`}>
                      <b>{formatMoney(hpPnl)}</b>
                    </td>
                    <td>
                      <span className={`op-tur-badge ${stateBadgeClass(hp)}`}>
                        {stateLabel(hp)}
                      </span>
                    </td>
                    <td className="text-dim">{elapsed(hp.transferred_at)}</td>
                    <td className="op-action-cell">
                      <button
                        type="button"
                        className="op-close-btn"
                        onClick={() => handleRemove(hp.ticket)}
                        disabled={removingTicket === hp.ticket}
                        title="Hibrit yönetiminden çıkar (pozisyon açık kalır)"
                      >
                        {removingTicket === hp.ticket ? 'Çıkarılıyor...' : 'Hibritten Çıkar'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            {hybridPositions.length > 1 && (
              <tfoot>
                <tr className="op-footer-row">
                  <td colSpan={7}><b>TOPLAM</b></td>
                  <td className={`mono ${pnlClass(totalHybridPnl)}`}>
                    <b>{formatMoney(totalHybridPnl)}</b>
                  </td>
                  <td colSpan={3}></td>
                </tr>
              </tfoot>
            )}
          </table>
        )}
      </div>

      {/* ═══ HİBRİT OLAY GEÇMİŞİ ═══════════════════════════════ */}
      <div className="mt-history" style={{ marginTop: '20px' }}>
        <h3>Hibrit Olay Geçmişi</h3>
        {hybridEvents.length === 0 ? (
          <div style={{ color: 'var(--text-dim)', fontSize: '12px', textAlign: 'center', padding: '12px 0' }}>
            Henüz hibrit olay yok
          </div>
        ) : (
          <table style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-dim)' }}>
                <th style={{ textAlign: 'left', padding: '4px 8px' }}>Zaman</th>
                <th style={{ textAlign: 'left', padding: '4px 8px' }}>Sembol</th>
                <th style={{ textAlign: 'center', padding: '4px 8px' }}>Olay</th>
                <th style={{ textAlign: 'left', padding: '4px 8px' }}>Detay</th>
              </tr>
            </thead>
            <tbody>
              {hybridEvents.map((evt, i) => (
                <tr key={evt.id || i} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 8px' }}>
                    {evt.timestamp ? new Date(evt.timestamp).toLocaleString('tr-TR', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }) : '\u2014'}
                  </td>
                  <td style={{ padding: '6px 8px', fontWeight: 600 }}>{evt.symbol}</td>
                  <td style={{ textAlign: 'center', padding: '6px 8px' }}>
                    <span className={`ht-event-badge ht-event--${(evt.event || '').toLowerCase()}`}>
                      {evt.event}
                    </span>
                  </td>
                  <td style={{ padding: '6px 8px', color: 'var(--text-dim)', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {(() => {
                      try {
                        const d = JSON.parse(evt.details || '{}');
                        if (d.new_sl) return `SL: ${formatPrice(d.old_sl)} → ${formatPrice(d.new_sl)}`;
                        if (d.reason) return d.reason;
                        if (d.pnl != null) return `K/Z: ${formatMoney(d.pnl)}`;
                        return evt.details;
                      } catch {
                        return evt.details;
                      }
                    })()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
