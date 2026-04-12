/**
 * ÜSTAT v5.7 — Manuel İşlem Paneli (ManuelMotor).
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
import { checkManualTrade, executeManualTrade, getTrades, getManualRiskScores, getPositions, closePosition, getWatchlistSymbols, getTradingLimits } from '../services/api';
import { formatMoney, formatPrice, pnlClass, elapsed } from '../utils/formatters';

// ── 15 VİOP Kontratı — Fallback (Widget Denetimi A-H3) ──────────
// Canonical kaynak backend engine/mt5_bridge.py::WATCHED_SYMBOLS —
// /api/settings/watchlist endpoint'inden okunur. Aşağıdaki dizi
// yalnız ilk render ve hata fallback'i olarak kullanılır; yeni kontrat
// eklenmesi tek yerde (WATCHED_SYMBOLS) yapılır, UI otomatik senkronize olur.
const DEFAULT_SYMBOLS = [
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
  const [sl, setSl] = useState(0);
  const [tp, setTp] = useState(0);

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

  // ── Aktif manuel pozisyonlar (canlı) ──────────────────────
  const [activePositions, setActivePositions] = useState([]);
  const [closingTicket, setClosingTicket] = useState(null);

  // ── İzlenen VİOP kontratları (Widget Denetimi A-H3) ──────────
  // /api/settings/watchlist → engine/mt5_bridge.py::WATCHED_SYMBOLS.
  // İlk render DEFAULT_SYMBOLS ile; mount'ta backend fetch ile override.
  const [watchlist, setWatchlist] = useState(DEFAULT_SYMBOLS);

  // ── Lot giriş sınırları (Widget Denetimi H4) ─────────────────
  // /api/settings/trading-limits → config.engine.max_lot_per_contract.
  // Hardcoded `min=1 max=10 step=1` drift'i bu state ile kapatılır.
  // İlk render VİOP default'u (1/1/1); mount'ta backend fetch ile override.
  const [lotLimits, setLotLimits] = useState({ lot_min: 1, lot_max: 1, lot_step: 1 });

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

  // Aktif manuel pozisyonları çek
  const fetchActivePositions = useCallback(async () => {
    const res = await getPositions();
    const manual = (res.positions || []).filter((p) => p.tur === 'Manuel' || p.tur === 'MT5');
    setActivePositions(manual);
  }, []);

  // Pozisyon kapat
  const handleClosePosition = useCallback(async (ticket) => {
    setClosingTicket(ticket);
    await closePosition(ticket);
    setClosingTicket(null);
    fetchActivePositions();
    fetchRecentTrades();
  }, [fetchActivePositions, fetchRecentTrades]);

  useEffect(() => {
    fetchRecentTrades();
    fetchRiskScores();
    fetchActivePositions();
    const iv = setInterval(() => { fetchRecentTrades(); fetchRiskScores(); fetchActivePositions(); }, 10000);
    return () => clearInterval(iv);
  }, [fetchRecentTrades, fetchRiskScores, fetchActivePositions]);

  // A-H3: Mount'ta watchlist'i backend'den al — engine/mt5_bridge.py::WATCHED_SYMBOLS.
  // Hardcode SYMBOLS drift riskini ortadan kaldırır (tek kaynak).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await getWatchlistSymbols();
        if (!cancelled && Array.isArray(resp?.symbols) && resp.symbols.length > 0) {
          setWatchlist(resp.symbols);
          // Dropdown'un seçili değeri yeni listede yoksa ilk öğeye çek.
          if (!resp.symbols.includes(symbol)) {
            setSymbol(resp.symbols[0]);
          }
        }
      } catch {
        // Hata durumunda DEFAULT_SYMBOLS state'te zaten mevcut.
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // H4: Mount'ta lot giriş sınırlarını backend'den al — config.engine.max_lot_per_contract.
  // Sessiz truncation (UI 10'a izin verir, motor 1.0'a kırpar) kapatılır.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await getTradingLimits();
        if (cancelled || !resp) return;
        const lmin = Number(resp.lot_min) > 0 ? Number(resp.lot_min) : 1;
        const lmax = Number(resp.lot_max) > 0 ? Number(resp.lot_max) : 1;
        const lstep = Number(resp.lot_step) > 0 ? Number(resp.lot_step) : 1;
        setLotLimits({ lot_min: lmin, lot_max: lmax, lot_step: lstep });
        // Mevcut lot state sınırların dışındaysa içine çek.
        setLot((prev) => {
          if (prev < lmin) return lmin;
          if (prev > lmax) return lmax;
          return prev;
        });
      } catch {
        // Hata durumunda varsayılan 1/1/1 state'te zaten mevcut.
      }
    })();
    return () => { cancelled = true; };
  }, []);

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
      // SL/TP otomatik hesapla: backend suggested veya ATR bazlı
      const price = result.current_price || 0;
      const atr = result.atr_value || 0;
      if (result.suggested_sl > 0) {
        setSl(result.suggested_sl);
      } else if (price > 0 && atr > 0) {
        setSl(direction === 'BUY' ? price - atr * 2 : price + atr * 2);
      }
      if (result.suggested_tp > 0) {
        setTp(result.suggested_tp);
      } else if (price > 0 && atr > 0) {
        setTp(direction === 'BUY' ? price + atr * 3 : price - atr * 3);
      }
      setPhase('checked');
    }
  }, [symbol, direction]);

  // ── Onayla (Emir Gönder) ─────────────────────────────────────
  // A23 (K1): handleExecute useCallback dependency array sl+tp
  // eksikti — stale closure riski. Kullanıcı sl/tp değerini değiştirip
  // 5 saniye içinde "Çalıştır"a basarsa eski (stale) sl/tp gönderiliyordu.
  // Çözüm: dependency array'e sl ve tp eklendi.
  const handleExecute = useCallback(async () => {
    setExecuting(true);

    const result = await executeManualTrade(symbol, direction, lot, sl, tp);
    setExecResult(result);
    setExecuting(false);
    setPhase('done');

    // 5 saniye sonra formu sıfırla
    setTimeout(() => {
      handleReset();
      fetchRecentTrades();
    }, 5000);
  }, [symbol, direction, lot, sl, tp, handleReset, fetchRecentTrades]);

  // ── Sıfırla ──────────────────────────────────────────────────
  const handleReset = useCallback(() => {
    setDirection('');
    setCheckResult(null);
    setExecResult(null);
    setPhase('select');
    setLot(1.0);
    setSl(0);
    setTp(0);
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
              {/* A-H3: Dinamik watchlist — backend WATCHED_SYMBOLS canonical kaynak. */}
              {watchlist.map((s) => (
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
                  min={lotLimits.lot_min}
                  max={lotLimits.lot_max}
                  step={lotLimits.lot_step}
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
                {direction === 'BUY' ? 'Ask' : 'Bid'}: {formatPrice(checkResult.current_price, 4, 4)}
                {' | '}ATR(14): {formatPrice(checkResult.atr_value, 4, 4)}
              </div>
            </div>
          )}

          {/* SL/TP Ayarları — kontrol sonrası, düzenlenebilir */}
          {phase === 'checked' && checkResult?.can_trade && (
            <div className="mt-form-group">
              <label>Stop Loss (SL)</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="number"
                  className="mt-lot-input"
                  value={sl}
                  onChange={(e) => setSl(parseFloat(e.target.value) || 0)}
                  step={0.01}
                />
                <span className="mt-price-info">Önerilen: 2×ATR</span>
              </div>
            </div>
          )}

          {phase === 'checked' && checkResult?.can_trade && (
            <div className="mt-form-group">
              <label>Take Profit (TP)</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="number"
                  className="mt-lot-input"
                  value={tp}
                  onChange={(e) => setTp(parseFloat(e.target.value) || 0)}
                  step={0.01}
                />
                <span className="mt-price-info">Önerilen: 3×ATR</span>
              </div>
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
                ? `Emir gönderildi! ${direction} ${execResult.lot} lot @ ${formatPrice(execResult.entry_price, 4, 4)}`
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

      {/* ═══ AKTİF MANUEL POZİSYONLAR ══════════════════════════════ */}
      <div className="op-table-wrap" style={{ marginTop: '20px' }}>
        <h3 style={{ margin: '0 0 8px', fontSize: '14px', fontWeight: 600 }}>
          Aktif Manuel Pozisyonlar
        </h3>
        {activePositions.length === 0 ? (
          <div className="op-empty">
            <span className="op-empty-icon">📋</span>
            <span>Açık manuel pozisyon yok</span>
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
                <th>K/Z</th>
                <th>Süre</th>
                <th>İşlem</th>
              </tr>
            </thead>
            <tbody>
              {activePositions.map((pos) => {
                const posPnl = pos.pnl || 0;
                const rowCls = posPnl > 0 ? 'op-row-profit' : posPnl < 0 ? 'op-row-loss' : '';
                return (
                  <tr key={pos.ticket} className={rowCls}>
                    <td className="mono op-symbol">{pos.symbol}</td>
                    <td>
                      <span className={`dir-badge dir-badge--${(pos.direction || '').toLowerCase()}`}>
                        {pos.direction}
                      </span>
                    </td>
                    <td className="mono">{pos.volume?.toFixed(2) ?? '\u2014'}</td>
                    <td className="mono">{formatPrice(pos.entry_price)}</td>
                    <td className="mono">{formatPrice(pos.current_price)}</td>
                    <td className={`mono op-pnl-cell ${pnlClass(posPnl)}`}>
                      <b>{formatMoney(posPnl)}</b>
                    </td>
                    <td className="text-dim">{elapsed(pos.open_time)}</td>
                    <td className="op-action-cell">
                      <button
                        type="button"
                        className="op-close-btn"
                        onClick={() => handleClosePosition(pos.ticket)}
                        disabled={closingTicket === pos.ticket}
                        title="Pozisyonu kapat"
                      >
                        {closingTicket === pos.ticket ? 'Kapatılıyor...' : 'Kapat'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            {activePositions.length > 1 && (
              <tfoot>
                <tr className="op-footer-row">
                  <td colSpan={5}><b>TOPLAM</b></td>
                  <td className={`mono ${pnlClass(activePositions.reduce((s, p) => s + (p.pnl || 0), 0))}`}>
                    <b>{formatMoney(activePositions.reduce((s, p) => s + (p.pnl || 0), 0))}</b>
                  </td>
                  <td colSpan={2}></td>
                </tr>
              </tfoot>
            )}
          </table>
        )}
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
                  <td style={{ textAlign: 'right', padding: '6px 8px' }}>{formatPrice(t.entry_price, 4, 4)}</td>
                  <td style={{ textAlign: 'right', padding: '6px 8px' }}>{formatPrice(t.exit_price, 4, 4)}</td>
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
