/**
 * ÜSTAT v5.0 — İşlem Geçmişi ekranı.
 *
 * Layout:
 *   1. Filtre çubuğu: Dönem, Sembol, Yön, Sonuç
 *   2. Özet kartlar: Toplam İşlem, Başarı Oranı, Net K/Z, Profit Factor
 *   3. Hızlı erişim butonları: En kârlı/zararlı/uzun/kısa
 *   4. İşlem tablosu (11 sütun + Onayla butonu)
 *   5. Performans paneli (sol) + Risk paneli (sağ)
 *   6. Alt özet satırı
 *
 * Veri: getTrades (1000 kayıt) + getTradeStats + getPerformance
 * Client-side filtre: dönem, yön, sonuç — server-side: sembol
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { getTrades, getTradeStats, getPerformance, approveTrade } from '../services/api';

// ── Sabitler ─────────────────────────────────────────────────────

const PERIOD_OPTIONS = [
  { value: 'today',  label: 'Bugün' },
  { value: '1w',     label: 'Son Hafta' },
  { value: '1m',     label: 'Son Ay' },
  { value: '3m',     label: 'Son 3 Ay' },
  { value: '6m',     label: 'Son 6 Ay' },
  { value: '1y',     label: 'Son Yıl' },
  { value: 'all',    label: 'Tümü' },
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
  if (val == null || isNaN(val)) return '—';
  return val.toLocaleString('tr-TR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 5,
  });
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
    if (totalMin < 60) return `${totalMin}dk`;
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    if (h < 24) return `${h}s ${m}dk`;
    const days = Math.floor(h / 24);
    const rh = h % 24;
    return `${days}g ${rh}s`;
  } catch {
    return '—';
  }
}

function formatMinutes(mins) {
  if (mins == null || isNaN(mins)) return '—';
  if (mins < 60) return `${mins.toFixed(0)} dk`;
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  return `${h}s ${m}dk`;
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

  // Filtreler
  const [period, setPeriod] = useState('1m');
  const [symbolFilter, setSymbolFilter] = useState('all');
  const [dirFilter, setDirFilter] = useState('all');
  const [resultFilter, setResultFilter] = useState('all');

  // Hızlı erişim vurgu
  const [highlight, setHighlight] = useState(null); // trade id

  // Onay
  const [approving, setApproving] = useState(null);

  // ── Veri çekme ───────────────────────────────────────────────────
  const fetchData = useCallback(async () => {
    setLoading(true);
    const [t, s, p] = await Promise.all([
      getTrades({ limit: 1000 }),
      getTradeStats(1000),
      getPerformance(365),
    ]);
    setAllTrades(t.trades || []);
    setStats(s);
    setPerf(p);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // ── Sembol listesi (unique) ──────────────────────────────────────
  const symbolOptions = useMemo(() => {
    const set = new Set(allTrades.map((t) => t.symbol).filter(Boolean));
    return ['all', ...Array.from(set).sort()];
  }, [allTrades]);

  // ── Client-side filtre ───────────────────────────────────────────
  const filteredTrades = useMemo(() => {
    const startDate = periodStartDate(period);
    return allTrades.filter((t) => {
      // Dönem
      if (startDate) {
        const ts = t.exit_time || t.entry_time;
        if (ts && new Date(ts) < startDate) return false;
      }
      // Sembol
      if (symbolFilter !== 'all' && t.symbol !== symbolFilter) return false;
      // Yön
      if (dirFilter !== 'all' && t.direction !== dirFilter) return false;
      // Sonuç
      if (resultFilter === 'profit' && (t.pnl == null || t.pnl <= 0)) return false;
      if (resultFilter === 'loss' && (t.pnl == null || t.pnl >= 0)) return false;
      return true;
    });
  }, [allTrades, period, symbolFilter, dirFilter, resultFilter]);

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

  // ── Ardışık kayıp hesapla ────────────────────────────────────────
  const maxConsecLosses = useMemo(() => {
    let max = 0, cur = 0;
    for (const t of filteredTrades) {
      if (t.pnl != null && t.pnl < 0) { cur++; max = Math.max(max, cur); }
      else cur = 0;
    }
    return max;
  }, [filteredTrades]);

  // ── Onay handler ─────────────────────────────────────────────────
  const handleApprove = async (tradeId) => {
    setApproving(tradeId);
    const res = await approveTrade(tradeId, 'operator', '');
    if (res.success) {
      // Trade listesini güncelle
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

  // ── Hızlı erişim ────────────────────────────────────────────────
  const scrollToTrade = (trade) => {
    if (!trade) return;
    setHighlight(trade.id);
    // Highlight'ı 3 saniye sonra kaldır
    setTimeout(() => setHighlight(null), 3000);
    // Satırı görünüme kaydır
    const el = document.getElementById(`trade-row-${trade.id}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  // ── Render ───────────────────────────────────────────────────────
  return (
    <div className="trade-history">
      <h2>İşlem Geçmişi</h2>

      {/* ═══ FİLTRE ÇUBUĞU ═════════════════════════════════════════ */}
      <div className="th-filters">
        <label className="th-filter">
          <span>Dönem</span>
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            {PERIOD_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

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

        <button className="th-refresh-btn" onClick={fetchData} disabled={loading}>
          {loading ? '...' : '↻'}
        </button>
      </div>

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

      {/* ═══ HIZLI ERİŞİM BUTONLARI ════════════════════════════════ */}
      <div className="th-quick-btns">
        <button
          className="th-quick-btn th-quick--profit"
          onClick={() => scrollToTrade(stats?.best_trade)}
          disabled={!stats?.best_trade}
        >
          ↑ En Kârlı
        </button>
        <button
          className="th-quick-btn th-quick--loss"
          onClick={() => scrollToTrade(stats?.worst_trade)}
          disabled={!stats?.worst_trade}
        >
          ↓ En Zararlı
        </button>
        <button
          className="th-quick-btn"
          onClick={() => scrollToTrade(stats?.longest_trade)}
          disabled={!stats?.longest_trade}
        >
          ⏱ En Uzun
        </button>
        <button
          className="th-quick-btn"
          onClick={() => scrollToTrade(stats?.shortest_trade)}
          disabled={!stats?.shortest_trade}
        >
          ⚡ En Kısa
        </button>
      </div>

      {/* ═══ İŞLEM TABLOSU ═════════════════════════════════════════ */}
      <div className="th-table-wrap">
        {loading ? (
          <div className="th-loading">Yükleniyor...</div>
        ) : filteredTrades.length === 0 ? (
          <div className="th-loading">Filtre kriterlerine uygun işlem yok.</div>
        ) : (
          <table className="th-table">
            <thead>
              <tr>
                <th>Sembol</th>
                <th>Yön</th>
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
              {filteredTrades.map((t) => {
                const approved = isApproved(t);
                const isHighlighted = highlight === t.id;
                return (
                  <tr
                    key={t.id}
                    id={`trade-row-${t.id}`}
                    className={`${isHighlighted ? 'th-row-hl' : ''} ${approved ? '' : 'th-row-new'}`}
                  >
                    <td className="mono">{t.symbol}</td>
                    <td>
                      <span className={`dir-badge dir-badge--${(t.direction || '').toLowerCase()}`}>
                        {t.direction}
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
            <PanelRow label="Maks. Ardışık Kayıp" value={maxConsecLosses} />
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

function PanelRow({ label, value, cls }) {
  return (
    <div className="th-pr">
      <span className="th-pr-label">{label}</span>
      <span className={`th-pr-value ${cls || ''}`}>{value}</span>
    </div>
  );
}
