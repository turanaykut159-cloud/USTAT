/**
 * ÜSTAT v5.4 — İşlem Geçmişi ekranı.
 *
 * Layout:
 *   1. Zaman filtre butonları (Varsayılan | Bugün | Bu Hafta | Bu Ay | 3 Ay | 6 Ay | 1 Yıl)
 *   2. Filtre çubuğu: Sembol, Yön, Sonuç + Sıralama butonları + Yenile + MT5 Sync
 *   3. Özet kartlar: Toplam İşlem, Başarı Oranı, Net K/Z, Profit Factor
 *   4. İşlem tablosu (11 sütun + Onayla butonu) — sayfalama (50/sayfa)
 *   5. Performans paneli (sol) + Risk paneli (sağ)
 *   6. Alt özet satırı
 *
 * Veri: getTrades (1000 kayıt) + getTradeStats + getPerformance
 * Client-side filtre: dönem, yön, sonuç — server-side: sembol
 */

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { getTrades, getTradeStats, getPerformance, approveTrade, syncTrades, connectLiveWS, STATS_BASELINE } from '../services/api';
import { formatMoney, formatPrice, pnlClass } from '../utils/formatters';

// ── Sabitler ─────────────────────────────────────────────────────

const PERIOD_BUTTONS = [
  { value: 'today',  label: 'Bugün' },
  { value: '1w',     label: 'Bu Hafta' },
  { value: '1m',     label: 'Bu Ay' },
  { value: '3m',     label: '3 Ay' },
  { value: '6m',     label: '6 Ay' },
  { value: '1y',     label: '1 Yıl' },
];

const DIR_OPTIONS = [
  { value: 'all',  label: 'Tümü' },
  { value: 'BUY',  label: 'Buy' },
  { value: 'SELL', label: 'Sell' },
];

const RESULT_OPTIONS = [
  { value: 'all',    label: 'Tümü' },
  { value: 'profit', label: 'Kârlı' },
  { value: 'loss',   label: 'Zararlı' },
];

const SORT_BUTTONS = [
  { value: 'pnl_desc',      label: '↑ En Kârlı',   cls: 'th-sort--profit' },
  { value: 'pnl_asc',       label: '↓ En Zararlı',  cls: 'th-sort--loss' },
  { value: 'duration_desc', label: '⏱ En Uzun',     cls: '' },
  { value: 'duration_asc',  label: '⏱ En Kısa',     cls: '' },
];

// Varsayılan filtre değerleri
const DEFAULT_PERIOD = 'all';
const DEFAULT_SYMBOL = 'all';
const DEFAULT_DIR = 'all';
const DEFAULT_RESULT = 'all';

// ── Yardımcılar ──────────────────────────────────────────────────

function formatPct(val) {
  if (val == null || isNaN(val)) return '—';
  return `%${val.toFixed(1)}`;
}

function formatPF(val) {
  if (val == null || isNaN(val) || val === 0) return '—';
  return val.toFixed(2);
}

function formatDateTime(ts) {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    const day = d.getDate().toString().padStart(2, '0');
    const mon = (d.getMonth() + 1).toString().padStart(2, '0');
    const year = d.getFullYear();
    const h = d.getHours().toString().padStart(2, '0');
    const m = d.getMinutes().toString().padStart(2, '0');
    return `${day}.${mon}.${year} ${h}:${m}`;
  } catch {
    return ts;
  }
}

function formatDuration(entryTs, exitTs) {
  if (!entryTs || !exitTs) return '—';
  try {
    const ms = new Date(exitTs) - new Date(entryTs);
    if (isNaN(ms) || ms < 0) return '—';
    const totalMin = Math.floor(ms / 60000);
    if (totalMin < 60) return totalMin === 0 ? '<1dk' : `${totalMin}dk`;
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    if (h < 24) return `${h}sa ${m}dk`;
    const days = Math.floor(h / 24);
    const rh = h % 24;
    return `${days}g ${rh}sa`;
  } catch {
    return '—';
  }
}

function formatMinutes(mins) {
  if (mins == null || isNaN(mins)) return '—';
  if (mins < 60) return `${mins.toFixed(0)} dk`;
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  return `${h}sa ${m}dk`;
}

/** Dönem filtresine göre başlangıç tarihi */
function periodStartDate(period) {
  const now = new Date();
  switch (period) {
    case 'today': {
      const d = new Date(now);
      d.setHours(0, 0, 0, 0);
      return d;
    }
    case '1w':  return new Date(now.getTime() - 7 * 86400000);
    case '1m':  return new Date(now.getTime() - 30 * 86400000);
    case '3m':  return new Date(now.getTime() - 90 * 86400000);
    case '6m':  return new Date(now.getTime() - 180 * 86400000);
    case '1y':  return new Date(now.getTime() - 365 * 86400000);
    default:    return null; // 'all'
  }
}

/** İşlemin süresini ms cinsinden hesapla (sıralama için) */
function tradeDurationMs(t) {
  if (!t.entry_time || !t.exit_time) return 0;
  const ms = new Date(t.exit_time) - new Date(t.entry_time);
  return isNaN(ms) || ms < 0 ? 0 : ms;
}

/** İşlem onaylı mı kontrolü */
function isApproved(trade) {
  return (trade.exit_reason || '').includes('APPROVED');
}


// ═══════════════════════════════════════════════════════════════════
//  ANA BİLEŞEN
// ═══════════════════════════════════════════════════════════════════

export default function TradeHistory() {
  // ── State ────────────────────────────────────────────────────────
  const [allTrades, setAllTrades] = useState([]);
  const [stats, setStats] = useState(null);
  const [perf, setPerf] = useState(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);

  // Filtreler
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [symbolFilter, setSymbolFilter] = useState(DEFAULT_SYMBOL);
  const [dirFilter, setDirFilter] = useState(DEFAULT_DIR);
  const [resultFilter, setResultFilter] = useState(DEFAULT_RESULT);

  // Sıralama
  const [sortMode, setSortMode] = useState(null);

  // Sayfalama
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;

  // Onay
  const [approving, setApproving] = useState(null);

  // MT5 Senkronizasyon
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);

  // ── Filtre sıfırlama ──────────────────────────────────────────
  const resetFilters = useCallback(() => {
    setPeriod(DEFAULT_PERIOD);
    setSymbolFilter(DEFAULT_SYMBOL);
    setDirFilter(DEFAULT_DIR);
    setResultFilter(DEFAULT_RESULT);
    setSortMode(null);
  }, []);

  /** Zaman butonuna tıklayınca: periyodu ayarla + diğer filtreleri sıfırla */
  const handlePeriodClick = useCallback((value) => {
    setPeriod(value);
    setSymbolFilter(DEFAULT_SYMBOL);
    setDirFilter(DEFAULT_DIR);
    setResultFilter(DEFAULT_RESULT);
    setSortMode(null);
  }, []);

  /** Sıralama butonuna tıklayınca: toggle (aynıysa kapat, farklıysa aç) */
  const handleSortClick = useCallback((value) => {
    setSortMode((prev) => prev === value ? null : value);
  }, []);

  // ── Veri çekme ───────────────────────────────────────────────────
  const fetchData = useCallback(async () => {
    setLoading(true);
    setFetchError(false);
    try {
      const [t, s, p] = await Promise.all([
        getTrades({ since: STATS_BASELINE, limit: 1000 }),
        getTradeStats(1000),
        getPerformance(365),
      ]);
      setFetchError(Boolean(t && t.error));
      setAllTrades(t && !t.error ? (t.trades || []) : []);
      setStats(s);
      setPerf(p);
    } finally {
      setLoading(false);
    }
  }, []);

  // İlk yüklemede veri çek + WebSocket event-driven yenileme
  const wsRef = useRef(null);
  useEffect(() => {
    fetchData();

    const { close } = connectLiveWS((messages) => {
      const arr = Array.isArray(messages) ? messages : [messages];
      for (const msg of arr) {
        if (msg.type === 'trade_closed' || msg.type === 'position_closed') {
          fetchData();
          break;
        }
      }
    });
    wsRef.current = close;

    return () => { if (wsRef.current) wsRef.current(); };
  }, [fetchData]);

  // ── Sembol listesi (unique) ──────────────────────────────────────
  const symbolOptions = useMemo(() => {
    const set = new Set(allTrades.map((t) => t.symbol).filter(Boolean));
    return ['all', ...Array.from(set).sort()];
  }, [allTrades]);

  // Filtre/sıralama değiştiğinde sayfayı sıfırla
  useEffect(() => { setPage(1); }, [period, symbolFilter, dirFilter, resultFilter, sortMode]);

  // ── Client-side filtre ───────────────────────────────────────────
  const filteredTrades = useMemo(() => {
    const startDate = periodStartDate(period);
    return allTrades.filter((t) => {
      if (startDate) {
        const ts = t.exit_time || t.entry_time;
        if (ts && new Date(ts) < startDate) return false;
      }
      if (symbolFilter !== 'all' && t.symbol !== symbolFilter) return false;
      if (dirFilter !== 'all' && t.direction !== dirFilter) return false;
      if (resultFilter === 'profit' && (t.pnl == null || t.pnl <= 0)) return false;
      if (resultFilter === 'loss' && (t.pnl == null || t.pnl >= 0)) return false;
      return true;
    });
  }, [allTrades, period, symbolFilter, dirFilter, resultFilter]);

  // ── Sıralama ───────────────────────────────────────────────────
  const sortedTrades = useMemo(() => {
    if (!sortMode) return filteredTrades;
    const arr = [...filteredTrades];
    switch (sortMode) {
      case 'pnl_desc':      return arr.sort((a, b) => (b.pnl || 0) - (a.pnl || 0));
      case 'pnl_asc':       return arr.sort((a, b) => (a.pnl || 0) - (b.pnl || 0));
      case 'duration_desc': return arr.sort((a, b) => tradeDurationMs(b) - tradeDurationMs(a));
      case 'duration_asc':  return arr.sort((a, b) => tradeDurationMs(a) - tradeDurationMs(b));
      default:               return arr;
    }
  }, [filteredTrades, sortMode]);

  // ── Filtre bazlı hesaplamalar ────────────────────────────────────
  const filteredStats = useMemo(() => {
    const pnls = filteredTrades.map((t) => t.pnl).filter((p) => p != null);
    const wins = pnls.filter((p) => p > 0);
    const losses = pnls.filter((p) => p < 0);
    const totalPnl = pnls.reduce((s, p) => s + p, 0);
    const grossProfit = wins.reduce((s, p) => s + p, 0);
    const grossLoss = Math.abs(losses.reduce((s, p) => s + p, 0));
    const totalSwap = filteredTrades.reduce((s, t) => s + (t.swap || 0), 0);
    const totalComm = filteredTrades.reduce((s, t) => s + (t.commission || 0), 0);
    const totalLot = filteredTrades.reduce((s, t) => s + (t.lot || 0), 0);

    return {
      count: filteredTrades.length,
      winRate: pnls.length > 0 ? (wins.length / pnls.length) * 100 : 0,
      winCount: wins.length,
      lossCount: losses.length,
      totalPnl,
      grossProfit,
      grossLoss,
      avgWin: wins.length > 0 ? grossProfit / wins.length : 0,
      avgLoss: losses.length > 0 ? grossLoss / losses.length : 0,
      profitFactor: grossLoss > 0 ? grossProfit / grossLoss : 0,
      totalSwap,
      totalComm,
      totalLot,
      avgLot: filteredTrades.length > 0 ? totalLot / filteredTrades.length : 0,
    };
  }, [filteredTrades]);

  // ── Sayfalama ────────────────────────────────────────────────────
  const totalPages = Math.max(1, Math.ceil(sortedTrades.length / PAGE_SIZE));
  const pagedTrades = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return sortedTrades.slice(start, start + PAGE_SIZE);
  }, [sortedTrades, page]);

  // ── Ardışık kayıp hesapla ────────────────────────────────────────
  const maxConsecLosses = useMemo(() => {
    let max = 0, cur = 0;
    for (const t of filteredTrades) {
      if (t.pnl != null && t.pnl < 0) { cur++; max = Math.max(max, cur); }
      else cur = 0;
    }
    return max;
  }, [filteredTrades]);

  // ── MT5 Sync handler ─────────────────────────────────────────────
  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const res = await syncTrades(90);
      setSyncResult(res);
      if (res.success) {
        await fetchData();
      }
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncResult(null), 5000);
    }
  };

  // ── Onay handler ─────────────────────────────────────────────────
  const handleApprove = async (tradeId) => {
    setApproving(tradeId);
    const res = await approveTrade(tradeId, 'operator', '');
    if (res.success) {
      setAllTrades((prev) =>
        prev.map((t) =>
          t.id === tradeId
            ? { ...t, exit_reason: `${t.exit_reason || ''} | APPROVED by operator` }
            : t
        )
      );
    }
    setApproving(null);
  };

  // Varsayılan durumda mı kontrolü
  const isDefault = period === DEFAULT_PERIOD
    && symbolFilter === DEFAULT_SYMBOL
    && dirFilter === DEFAULT_DIR
    && resultFilter === DEFAULT_RESULT
    && sortMode === null;

  // ── Render ───────────────────────────────────────────────────────
  return (
    <div className="trade-history">

      {/* ═══ ZAMAN FİLTRE BUTONLARI (üst satır) ═════════════════ */}
      <div className="th-period-btns">
        <button
          className={`th-period-btn th-period-btn--default ${isDefault ? 'th-period-btn--active' : ''}`}
          onClick={resetFilters}
        >
          Varsayılan
        </button>
        {PERIOD_BUTTONS.map((o) => (
          <button
            key={o.value}
            className={`th-period-btn ${period === o.value && !isDefault ? 'th-period-btn--active' : ''}`}
            onClick={() => handlePeriodClick(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>

      {/* ═══ FİLTRE + SIRALAMA ÇUBUĞU (alt satır) ═══════════════ */}
      <div className="th-filters">
        <label className="th-filter">
          <span>Sembol</span>
          <select value={symbolFilter} onChange={(e) => setSymbolFilter(e.target.value)}>
            {symbolOptions.map((s) => (
              <option key={s} value={s}>{s === 'all' ? 'Tümü' : s}</option>
            ))}
          </select>
        </label>

        <label className="th-filter">
          <span>Yön</span>
          <select value={dirFilter} onChange={(e) => setDirFilter(e.target.value)}>
            {DIR_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <label className="th-filter">
          <span>Sonuç</span>
          <select value={resultFilter} onChange={(e) => setResultFilter(e.target.value)}>
            {RESULT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <div className="th-sort-btns">
          {SORT_BUTTONS.map((s) => (
            <button
              key={s.value}
              className={`th-sort-btn ${s.cls} ${sortMode === s.value ? 'th-sort-btn--active' : ''}`}
              onClick={() => handleSortClick(s.value)}
            >
              {s.label}
            </button>
          ))}
        </div>

        <button className="th-refresh-btn" onClick={fetchData} disabled={loading}>
          {loading ? '...' : '↻'}
        </button>

        <button
          className="th-sync-btn"
          onClick={handleSync}
          disabled={syncing}
          title="MT5'ten son 90 günlük işlem geçmişini senkronize et"
        >
          {syncing ? 'Senkronize ediliyor...' : '⟳ MT5 Senkronize Et'}
        </button>
      </div>

      {syncResult && (
        <div className={`th-sync-result ${syncResult.success ? 'th-sync-ok' : 'th-sync-err'}`}>
          {syncResult.message}
        </div>
      )}

      {/* ═══ ÖZET KARTLAR (4) ══════════════════════════════════════ */}
      <div className="th-summary-row">
        <div className="th-summary-card">
          <span className="th-sc-label">Toplam İşlem</span>
          <span className="th-sc-value">{filteredStats.count}</span>
        </div>
        <div className="th-summary-card">
          <span className="th-sc-label">Başarı Oranı</span>
          <span className="th-sc-value" style={{ color: filteredStats.winRate >= 50 ? 'var(--profit)' : 'var(--loss)' }}>
            {formatPct(filteredStats.winRate)}
          </span>
        </div>
        <div className="th-summary-card">
          <span className="th-sc-label">Net Kâr/Zarar</span>
          <span className={`th-sc-value ${pnlClass(filteredStats.totalPnl)}`}>
            {formatMoney(filteredStats.totalPnl)}
          </span>
        </div>
        <div className="th-summary-card">
          <span className="th-sc-label">Profit Factor</span>
          <span className="th-sc-value" style={{
            color: filteredStats.profitFactor >= 1.5 ? 'var(--profit)' :
                   filteredStats.profitFactor >= 1 ? 'var(--warning)' : 'var(--loss)'
          }}>
            {formatPF(filteredStats.profitFactor)}
          </span>
        </div>
      </div>

      {/* ═══ İŞLEM TABLOSU ═════════════════════════════════════════ */}
      <div className="th-table-wrap">
        {loading ? (
          <div className="th-loading">Yükleniyor...</div>
        ) : fetchError ? (
          <div className="th-loading th-error-msg">
            <p>İşlem geçmişi yüklenemedi.</p>
            <p className="th-error-hint">MT5 ve API bağlantısını kontrol edip <strong>Yenile</strong> butonuna tıklayın.</p>
            <button type="button" className="th-retry-btn" onClick={fetchData}>Yenile</button>
          </div>
        ) : sortedTrades.length === 0 ? (
          <div className="th-loading">
            {allTrades.length === 0
              ? 'Henüz işlem kaydı yok veya veri gelmedi. Sayfayı yenileyin.'
              : 'Filtre kriterlerine uygun işlem yok.'}
          </div>
        ) : (
          <table className="th-table">
            <thead>
              <tr>
                <th>Sembol</th>
                <th>Yön</th>
                <th>Tür</th>
                <th>Lot</th>
                <th>Giriş Fiy.</th>
                <th>Çıkış Fiy.</th>
                <th>Giriş Tarihi</th>
                <th>Çıkış Tarihi</th>
                <th>Süre</th>
                <th>Swap</th>
                <th>Komisyon</th>
                <th>K/Z</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {pagedTrades.map((t) => {
                const approved = isApproved(t);
                const stratLower = (t.strategy || '').toLowerCase();
                const exitReason = (t.exit_reason || '').toUpperCase();
                const isHybrid = exitReason.includes('SOFTWARE') || stratLower === 'hybrid' || stratLower === 'hibrit';
                const isAuto = !isHybrid && stratLower !== '' && stratLower !== 'manual' && stratLower !== 'bilinmiyor';
                const turLabel = isHybrid ? 'Hibrit' : isAuto ? 'Otomatik' : 'Manuel';
                const turClass = isHybrid ? 'hybrid' : isAuto ? 'auto' : 'manual';
                return (
                  <tr
                    key={t.id}
                    id={`trade-row-${t.id}`}
                    className={approved ? '' : 'th-row-new'}
                  >
                    <td className="mono">{t.symbol}</td>
                    <td>
                      <span className={`dir-badge dir-badge--${(t.direction || '').toLowerCase()}`}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="th-tur-cell">
                      <span className={`th-tur-badge th-tur--${turClass}`}>
                        {turLabel}
                      </span>
                    </td>
                    <td className="mono">{t.lot?.toFixed(2) ?? '—'}</td>
                    <td className="mono">{formatPrice(t.entry_price)}</td>
                    <td className="mono">{formatPrice(t.exit_price)}</td>
                    <td className="text-dim">{formatDateTime(t.entry_time)}</td>
                    <td className="text-dim">{formatDateTime(t.exit_time)}</td>
                    <td className="text-dim">{formatDuration(t.entry_time, t.exit_time)}</td>
                    <td className={`mono ${pnlClass(t.swap)}`}>{formatMoney(t.swap)}</td>
                    <td className={`mono ${pnlClass(t.commission)}`}>{formatMoney(t.commission)}</td>
                    <td className={`mono ${pnlClass(t.pnl)}`}>
                      <b>{formatMoney(t.pnl)}</b>
                    </td>
                    <td>
                      {approved ? (
                        <span className="th-approved-badge">✓</span>
                      ) : (
                        <button
                          className="th-approve-btn"
                          onClick={() => handleApprove(t.id)}
                          disabled={approving === t.id}
                          title="Onayla ve Kaydet"
                        >
                          {approving === t.id ? '...' : 'Onayla'}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* ═══ SAYFALAMA ════════════════════════════════════════════ */}
      {totalPages > 1 && (
        <div className="th-pagination">
          <button className="th-page-btn" onClick={() => setPage(1)} disabled={page === 1}>««</button>
          <button className="th-page-btn" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>«</button>
          <span className="th-page-info">
            {page} / {totalPages}
            <span className="th-page-total"> ({sortedTrades.length} kayit)</span>
          </span>
          <button className="th-page-btn" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>»</button>
          <button className="th-page-btn" onClick={() => setPage(totalPages)} disabled={page === totalPages}>»»</button>
        </div>
      )}

      {/* ═══ PERFORMANS + RİSK PANELLERİ ═══════════════════════════ */}
      <div className="th-panels-row">

        {/* ── Performans Paneli (Sol) ────────────────────────────── */}
        <div className="th-panel">
          <h3>Performans</h3>
          <div className="th-panel-grid">
            <PanelRow label="Toplam Kâr" value={formatMoney(filteredStats.grossProfit)} cls="profit" />
            <PanelRow label="Toplam Zarar" value={formatMoney(-filteredStats.grossLoss)} cls="loss" />
            <PanelRow label="Kazanan" value={filteredStats.winCount} />
            <PanelRow label="Kaybeden" value={filteredStats.lossCount} />
            <PanelRow label="Ort. Kazanç" value={formatMoney(filteredStats.avgWin)} cls="profit" />
            <PanelRow label="Ort. Kayıp" value={formatMoney(-filteredStats.avgLoss)} cls="loss" />
            <PanelRow label="Toplam Swap" value={formatMoney(filteredStats.totalSwap)} cls={pnlClass(filteredStats.totalSwap)} />
            <PanelRow label="Toplam Komisyon" value={formatMoney(filteredStats.totalComm)} cls={pnlClass(filteredStats.totalComm)} />
          </div>
        </div>

        {/* ── Risk Paneli (Sağ) ──────────────────────────────────── */}
        <div className="th-panel">
          <h3>Risk</h3>
          <div className="th-panel-grid">
            <PanelRow
              label="En İyi İşlem"
              value={stats?.best_trade ? `${formatMoney(stats.best_trade.pnl)} (${stats.best_trade.symbol})` : '—'}
              cls="profit"
            />
            <PanelRow
              label="En Kötü İşlem"
              value={stats?.worst_trade ? `${formatMoney(stats.worst_trade.pnl)} (${stats.worst_trade.symbol})` : '—'}
              cls="loss"
            />
            <PanelRow label="Maks. Ardışık Kayıp" value={maxConsecLosses != null ? `${maxConsecLosses} işlem` : '—'} />
            <PanelRow label="Sharpe Oranı" value={perf?.sharpe_ratio?.toFixed(2) ?? '—'} />
            <PanelRow label="Maks. Drawdown" value={perf?.max_drawdown_pct != null ? `%${perf.max_drawdown_pct.toFixed(2)}` : '—'} cls="loss" />
            <PanelRow label="Ort. İşlem Süresi" value={formatMinutes(stats?.avg_duration_minutes)} />
            <PanelRow label="Toplam Lot" value={filteredStats.totalLot.toFixed(2)} />
            <PanelRow label="Ort. Lot" value={filteredStats.avgLot.toFixed(2)} />
          </div>
        </div>
      </div>

      {/* ═══ ALT ÖZET SATIRI ═══════════════════════════════════════ */}
      <div className="th-bottom-summary">
        <div className="th-bs-item">
          <span className="th-bs-label">Kâr</span>
          <span className={`th-bs-value ${pnlClass(filteredStats.totalPnl)}`}>
            {formatMoney(filteredStats.totalPnl)}
          </span>
        </div>
        <div className="th-bs-sep" />
        <div className="th-bs-item">
          <span className="th-bs-label">Swap</span>
          <span className={`th-bs-value ${pnlClass(filteredStats.totalSwap)}`}>
            {formatMoney(filteredStats.totalSwap)}
          </span>
        </div>
        <div className="th-bs-sep" />
        <div className="th-bs-item">
          <span className="th-bs-label">Komisyon</span>
          <span className={`th-bs-value ${pnlClass(filteredStats.totalComm)}`}>
            {formatMoney(filteredStats.totalComm)}
          </span>
        </div>
        <div className="th-bs-sep" />
        <div className="th-bs-item">
          <span className="th-bs-label">Toplam Lot</span>
          <span className="th-bs-value">{filteredStats.totalLot.toFixed(2)}</span>
        </div>
        <div className="th-bs-sep" />
        <div className="th-bs-item">
          <span className="th-bs-label">İşlem Sayısı</span>
          <span className="th-bs-value">{filteredStats.count}</span>
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
//  ALT BİLEŞEN: Panel satırı
// ═══════════════════════════════════════════════════════════════════

const PanelRow = React.memo(function PanelRow({ label, value, cls }) {
  return (
    <div className="th-pr">
      <span className="th-pr-label">{label}</span>
      <span className={`th-pr-value ${cls || ''}`}>{value}</span>
    </div>
  );
});
