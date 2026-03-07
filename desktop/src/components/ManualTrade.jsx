/**
 * ÜSTAT v14.0 — Manuel İşlem Paneli (ManuelMotor).
 *
 * Kullanıcı sembol + yön + lot seçerek manuel işlem açar.
 * BABA risk kontrolü yapılır, kullanıcı pozisyonu yönetir.
 * OĞUL müdahale etmez, sadece risk göstergesi sağlar.
 *
 * Akış:
 *   1. Sembol + Yön seç → "Kontrol Et"
 *   2. Risk ön kontrolü (POST /api/manual-trade/check)
 *   3. Sonuç göster → Lot ayarla → "Onayla"
 *   4. Emir gönder (POST /api/manual-trade/execute)
 */

import React, { useState, useEffect, useCallback } from 'react';
import { checkManualTrade, executeManualTrade, getTrades, getManualRiskScores } from '../services/api';

// ── Yardımcı fonksiyonlar ───────────────────────────────────────

function formatMoney(val) {
  if (val == null || isNaN(val)) return '\u2014';
  const abs = Math.abs(val);
  const formatted = abs.toLocaleString('tr-TR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return val < 0 ? `-${formatted}` : formatted;
}

function formatPrice(val) {
  if (val == null || isNaN(val) || val === 0) return '\u2014';
  return val.toLocaleString('tr-TR', {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  });
}

// ── 15 VİOP Kontratı ────────────────────────────────────────────

const SYMBOLS = [
  'F_THYAO', 'F_AKBNK', 'F_ASELS', 'F_TCELL', 'F_HALKB',
  'F_PGSUS', 'F_GUBRF', 'F_EKGYO', 'F_SOKM', 'F_TKFEN',
  'F_OYAKC', 'F_BRSAN', 'F_AKSEN', 'F_ASTOR', 'F_KONTR',
];

// ═════════════════════════════════════════════════════════════════
//  ANA BİLEŞEN
// ═════════════════════════════════════════════════════════════════

export default function ManualTrade() {
  // ── Form state ───────────────────────────────────────────────
  const [symbol, setSymbol] = useState('F_THYAO');
  const [direction, setDirection] = useState('');  // '' | 'BUY' | 'SELL'
  const [lot, setLot] = useState(1.0);

  // ── API state ────────────────────────────────────────────────
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState(null);
  const [executing, setExecuting] = useState(false);
  const [execResult, setExecResult] = useState(null);

  // ── Faz: 'select' → 'checked' → 'done' ──────────────────────
  const [phase, setPhase] = useState('select');

  // ── Son manuel işlemler ──────────────────────────────────────
  const [recentTrades, setRecentTrades] = useState([]);

  // ── Açık manuel pozisyon risk skorları ──────────────────────
  const [riskScores, setRiskScores] = useState({});

  // Son manuel işlemleri çek
  const fetchRecentTrades = useCallback(async () => {
    const res = await getTrades({ strategy: 'manual', limit: 10 });
    setRecentTrades(res.trades || []);
  }, []);

  // Risk skorlarını çek
  const fetchRiskScores = useCallback(async () => {
    const res = await getManualRiskScores();
    setRiskScores(res.scores || {});
  }, []);

  useEffect(() => {
    fetchRecentTrades();
    fetchRiskScores();
    const iv = setInterval(() => { fetchRecentTrades(); fetchRiskScores(); }, 10000);
    return () => clearInterval(iv);
  }, [fetchRecentTrades, fetchRiskScores]);

  // ── Kontrol Et ───────────────────────────────────────────────
  const handleCheck = useCallback(async () => {
    if (!direction) return;
    setChecking(true);
    setCheckResult(null);
    setExecResult(null);

    const result = await checkManualTrade(symbol, direction);
    setCheckResult(result);
    setChecking(false);

    if (result.can_trade) {
      setLot(result.suggested_lot || 1.0);
      setPhase('checked');
    }
  }, [symbol, direction]);

  // ── Onayla (Emir Gönder) ─────────────────────────────────────
  const handleExecute = useCallback(async () => {
    setExecuting(true);

    const result = await executeManualTrade(symbol, direction, lot);
    setExecResult(result);
    setExecuting(false);
    setPhase('done');

    // 5 saniye sonra formu sıfırla
    setTimeout(() => {
      handleReset();
      fetchRecentTrades();
    }, 5000);
  }, [symbol, direction, lot, fetchRecentTrades]);

  // ── Sıfırla ──────────────────────────────────────────────────
  const handleReset = useCallback(() => {
    setDirection('');
    setCheckResult(null);
    setExecResult(null);
    setPhase('select');
    setLot(1.0);
  }, []);

  // Sembol değişince sıfırla
  const handleSymbolChange = useCallback((e) => {
    setSymbol(e.target.value);
    handleReset();
  }, [handleReset]);

  // ── Risk özeti verileri ──────────────────────────────────────
  const risk = checkResult?.risk_summary || {};

  return (
    <div className="manual-trade">
      <h2>Manuel İşlem Paneli</h2>

      <div className="mt-layout">
        {/* ── SOL PANEL: Form ──────────────────────────────────── */}
        <div className="mt-form">

          {/* Sembol Seçimi */}
          <div className="mt-form-group">
            <label>Sembol</label>
            <select
              className="mt-select"
              value={symbol}
              onChange={handleSymbolChange}
              disabled={phase !== 'select'}
            >
              {SYMBOLS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          {/* Yön Seçimi */}
          <div className="mt-form-group">
            <label>Yön</label>
            <div className="mt-dir-buttons">
              <button
                className={`mt-dir-btn ${direction === 'BUY' ? 'active-buy' : ''}`}
                onClick={() => { setDirection('BUY'); setCheckResult(null); setPhase('select'); }}
                disabled={phase === 'done'}
              >
                BUY
              </button>
              <button
                className={`mt-dir-btn ${direction === 'SELL' ? 'active-sell' : ''}`}
                onClick={() => { setDirection('SELL'); setCheckResult(null); setPhase('select'); }}
                disabled={phase === 'done'}
              >
                SELL
              </button>
            </div>
          </div>

          {/* Lot Miktarı — sadece kontrol sonrası */}
          {phase === 'checked' && checkResult?.can_trade && (
            <div className="mt-form-group">
              <label>Lot Miktarı</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="number"
                  className="mt-lot-input"
                  value={lot}
                  onChange={(e) => setLot(parseFloat(e.target.value) || 0)}
                  min={1}
                  max={10}
                  step={1}
                />
                <span className="mt-price-info">
                  BABA önerisi: {checkResult.suggested_lot}
                </span>
              </div>
            </div>
          )}

          {/* Fiyat Bilgisi — kontrol sonrası */}
          {checkResult?.can_trade && (
            <div className="mt-form-group">
              <label>Fiyat Bilgisi</label>
              <div className="mt-price-info">
                {direction === 'BUY' ? 'Ask' : 'Bid'}: {formatPrice(checkResult.current_price)}
              </div>
              <div className="mt-price-info">
                ATR(14): {formatPrice(checkResult.atr_value)}
              </div>
              {checkResult.atr_value > 0 && checkResult.current_price > 0 && (
                <>
                  <div className="mt-price-info">
                    SL: {formatPrice(
                      direction === 'BUY'
                        ? checkResult.current_price - checkResult.atr_value * 2
                        : checkResult.current_price + checkResult.atr_value * 2
                    )} (2xATR)
                  </div>
                  <div className="mt-price-info">
                    TP: {formatPrice(
                      direction === 'BUY'
                        ? checkResult.current_price + checkResult.atr_value * 3
                        : checkResult.current_price - checkResult.atr_value * 3
                    )} (3xATR)
                  </div>
                </>
              )}
            </div>
          )}

          {/* Kontrol Et butonu */}
          {phase === 'select' && (
            <button
              className="mt-check-btn"
              onClick={handleCheck}
              disabled={!direction || checking}
            >
              {checking ? 'Kontrol ediliyor...' : 'Kontrol Et'}
            </button>
          )}

          {/* Onayla butonu */}
          {phase === 'checked' && checkResult?.can_trade && (
            <button
              className={`mt-execute-btn ${direction === 'SELL' ? 'sell' : ''}`}
              onClick={handleExecute}
              disabled={executing || lot <= 0}
            >
              {executing
                ? 'Emir gönderiliyor...'
                : `${direction} ${lot} lot ${symbol} — Onayla`}
            </button>
          )}

          {/* Tekrar dene butonu (red sonrası) */}
          {checkResult && !checkResult.can_trade && phase === 'select' && (
            <button className="mt-check-btn" onClick={handleReset} style={{ marginTop: '8px' }}>
              Sıfırla
            </button>
          )}

          {/* Emir sonucu */}
          {execResult && (
            <div className={`mt-result ${execResult.success ? 'success' : 'error'}`}>
              {execResult.success
                ? `Emir gönderildi! ${direction} ${execResult.lot} lot @ ${formatPrice(execResult.entry_price)}`
                : `Hata: ${execResult.message}`}
            </div>
          )}
        </div>

        {/* ── SAĞ PANEL: Risk Özeti ─────────────────────────────── */}
        <div className="mt-risk-panel">
          <h3 style={{ margin: '0 0 12px', fontSize: '13px', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Risk Özeti
          </h3>

          {checkResult ? (
            <>
              <div className="mt-risk-row">
                <span className="mt-risk-label">Rejim</span>
                <span className="mt-risk-value">
                  {risk.regime || '\u2014'} ({'\u00D7'}{risk.risk_multiplier ?? '\u2014'})
                </span>
              </div>
              <div className="mt-risk-row">
                <span className="mt-risk-label">Günlük İşlem</span>
                <span className="mt-risk-value">
                  {risk.daily_trade_count ?? 0}/{risk.max_daily_trades ?? 5}
                </span>
              </div>
              <div className="mt-risk-row">
                <span className="mt-risk-label">Üst Üste Kayıp</span>
                <span className="mt-risk-value">{risk.consecutive_losses ?? 0}</span>
              </div>
              <div className="mt-risk-row">
                <span className="mt-risk-label">Equity</span>
                <span className="mt-risk-value">{formatMoney(risk.equity)} TL</span>
              </div>
              <div className="mt-risk-row">
                <span className="mt-risk-label">Serbest Teminat</span>
                <span className="mt-risk-value">{formatMoney(risk.free_margin)} TL</span>
              </div>
              <div className="mt-risk-row">
                <span className="mt-risk-label">Floating K/Z</span>
                <span className="mt-risk-value" style={{ color: (risk.floating_pnl || 0) >= 0 ? '#4CAF50' : '#F44336' }}>
                  {formatMoney(risk.floating_pnl)} TL
                </span>
              </div>
              <div className="mt-risk-row">
                <span className="mt-risk-label">Kill-Switch</span>
                <span className="mt-risk-value">FAZ {risk.kill_switch_level ?? 0}</span>
              </div>
              <div className="mt-risk-row">
                <span className="mt-risk-label">Lot Çarpanı</span>
                <span className="mt-risk-value">{'\u00D7'}{risk.lot_multiplier ?? 1.0}</span>
              </div>

              {/* Durum göstergesi */}
              {checkResult.can_trade ? (
                <div className="mt-status-ok">İşlem açılabilir</div>
              ) : (
                <div className="mt-status-fail">{checkResult.reason}</div>
              )}
            </>
          ) : (
            <div style={{ color: 'var(--text-dim)', fontSize: '13px', textAlign: 'center', padding: '32px 0' }}>
              Sembol ve yön seçip "Kontrol Et" tıklayın
            </div>
          )}
        </div>
      </div>

      {/* ── AÇIK MANUEL POZİSYON RİSK GÖSTERGELERİ ──────────────── */}
      {Object.keys(riskScores).length > 0 && (
        <div className="mt-risk-monitor">
          <h3>Açık Manuel Pozisyonlar — Risk Göstergesi</h3>
          <table>
            <thead>
              <tr>
                <th style={{ textAlign: 'left' }}>Sembol</th>
                <th>SL Risk</th>
                <th>Rejim</th>
                <th>K/Z</th>
                <th>Sistem</th>
                <th>Genel</th>
                <th style={{ textAlign: 'right' }}>Skor</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(riskScores).map(([sym, rs]) => {
                const labelMap = { green: 'DUSUK', yellow: 'ORTA', red: 'YUKSEK' };
                const badge = (level) => (
                  <span className={`mt-risk-dim mt-risk-dim--${level}`}>
                    {labelMap[level] || level}
                  </span>
                );
                const colorMap = { green: 'var(--success, #3fb950)', yellow: 'var(--warning, #d29922)', red: 'var(--danger, #f85149)' };
                return (
                  <tr key={sym}>
                    <td style={{ fontWeight: 600 }}>{sym}</td>
                    <td style={{ textAlign: 'center' }}>{badge(rs.sl_risk)}</td>
                    <td style={{ textAlign: 'center' }}>{badge(rs.regime_risk)}</td>
                    <td style={{ textAlign: 'center' }}>{badge(rs.pnl_risk)}</td>
                    <td style={{ textAlign: 'center' }}>{badge(rs.system_risk)}</td>
                    <td style={{ textAlign: 'center' }}>{badge(rs.overall)}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700, color: colorMap[rs.overall] || '#888' }}>
                      {rs.score}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── SON MANUEL İŞLEMLER ──────────────────────────────────── */}
      <div className="mt-history">
        <h3>Son Manuel İşlemler</h3>
        {recentTrades.length === 0 ? (
          <div style={{ color: 'var(--text-dim)', fontSize: '12px', textAlign: 'center', padding: '12px 0' }}>
            Henüz manuel işlem yok
          </div>
        ) : (
          <table style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-dim)' }}>
                <th style={{ textAlign: 'left', padding: '4px 8px' }}>Tarih</th>
                <th style={{ textAlign: 'left', padding: '4px 8px' }}>Sembol</th>
                <th style={{ textAlign: 'center', padding: '4px 8px' }}>Yön</th>
                <th style={{ textAlign: 'right', padding: '4px 8px' }}>Lot</th>
                <th style={{ textAlign: 'right', padding: '4px 8px' }}>Giriş</th>
                <th style={{ textAlign: 'right', padding: '4px 8px' }}>Çıkış</th>
                <th style={{ textAlign: 'right', padding: '4px 8px' }}>K/Z</th>
              </tr>
            </thead>
            <tbody>
              {recentTrades.map((t, i) => (
                <tr key={t.id || i} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 8px' }}>
                    {t.entry_time ? new Date(t.entry_time).toLocaleString('tr-TR', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }) : '\u2014'}
                  </td>
                  <td style={{ padding: '6px 8px', fontWeight: 600 }}>{t.symbol}</td>
                  <td style={{ textAlign: 'center', padding: '6px 8px', color: t.direction === 'BUY' ? '#4CAF50' : '#F44336', fontWeight: 700 }}>
                    {t.direction}
                  </td>
                  <td style={{ textAlign: 'right', padding: '6px 8px' }}>{t.lot}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px' }}>{formatPrice(t.entry_price)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px' }}>{formatPrice(t.exit_price)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 600, color: (t.pnl || 0) >= 0 ? '#4CAF50' : '#F44336' }}>
                    {t.pnl != null ? formatMoney(t.pnl) : '\u2014'}
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
