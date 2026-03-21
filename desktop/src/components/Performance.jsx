/**
 * ÜSTAT v5.7 — Üstat & Performans ekranı.
 *
 * İki sekme:
 *   A) Performans — Klasik performans metrikleri (9 bölüm)
 *   B) Üstat Analiz — v13.0 beyin görev bileşenleri (6 bölüm)
 *
 * Performans bölümleri:
 *   1. Özet kartlar (5): Net K/Z, Win Rate, Sharpe, PF, Max DD
 *   2. Equity eğrisi (detaylı, AreaChart)
 *   3. Drawdown grafiği (AreaChart, kırmızı)
 *   4. Strateji bazlı performans (BarChart)
 *   5. Sembol bazlı başarı oranı (BarChart)
 *   6. Long vs Short karşılaştırma (panel)
 *   7. Win rate trend (LineChart, hareketli ortalama)
 *   8. Saat bazlı performans (heatmap)
 *   9. Aylık kâr/zarar breakdown (BarChart)
 *
 * Üstat Analiz bölümleri:
 *   A. Özet kartlar (4)
 *   B. İşlem kategorileri (4 mini BarChart)
 *   C. Kontrat profilleri (grid kartlar)
 *   D. Karar akışı (timeline)
 *   E. Rejim bazlı performans (BarChart)
 *   F. Placeholder paneller (3 yakında kartı)
 *
 * Veri: getPerformance, getTradeStats, getTrades (Performans)
 *       getUstatBrain (Üstat Analiz)
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  AreaChart, Area,
  BarChart, Bar, Cell,
  LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { getPerformance, getTradeStats, getTrades, getUstatBrain, STATS_BASELINE } from '../services/api';

// ── Yardımcılar ──────────────────────────────────────────────────

function fmt(val) {
  if (val == null || isNaN(val)) return '—';
  const abs = Math.abs(val);
  return (val < 0 ? '-' : '') + abs.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(val) {
  if (val == null || isNaN(val)) return '—';
  return `%${val.toFixed(1)}`;
}

function fmtNum(val, d = 2) {
  if (val == null || isNaN(val)) return '—';
  return val.toFixed(d);
}

function pnlCls(v) { return v > 0 ? 'profit' : v < 0 ? 'loss' : ''; }

function shortDate(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    const dd = d.getDate().toString().padStart(2, '0');
    const mm = (d.getMonth() + 1).toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const min = d.getMinutes().toString().padStart(2, '0');
    return `${dd}.${mm} ${hh}:${min}`;
  } catch { return ts.slice(5, 16); }
}

function monthLabel(key) {
  const months = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
  const [, m] = key.split('-');
  return months[parseInt(m, 10) - 1] || key;
}

// ── Recharts Tooltip'ler ─────────────────────────────────────────

function ChartTip({ active, payload, labelKey, valueKey, prefix }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <span className="chart-tooltip-date">{d[labelKey || 'label'] || ''}</span>
      <span className={pnlCls(d[valueKey || 'value'])}>
        {prefix || ''}<b>{fmt(d[valueKey || 'value'])}</b>
      </span>
    </div>
  );
}

function EquityTip({ active, payload }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <span className="chart-tooltip-date">{shortDate(d.timestamp)}</span>
      <span>Equity: <b>{fmt(d.equity)}</b></span>
      {d.balance > 0 && (
        <span>Bakiye: <b>{fmt(d.balance)}</b></span>
      )}
      {d.daily_pnl != null && (
        <span className={pnlCls(d.daily_pnl)}>Günlük: <b>{fmt(d.daily_pnl)}</b></span>
      )}
    </div>
  );
}

function DdTip({ active, payload }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <span className="chart-tooltip-date">{shortDate(d.timestamp)}</span>
      <span className="loss">DD: <b>%{d.dd.toFixed(2)}</b></span>
    </div>
  );
}

function CategoryTip({ active, payload }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <span className="chart-tooltip-date">{d.label}</span>
      <span className={pnlCls(d.total_pnl)}>K/Z: <b>{fmt(d.total_pnl)}</b></span>
      <span>WR: {fmtPct(d.win_rate)} | {d.count} işlem</span>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
//  ANA BİLEŞEN
// ═══════════════════════════════════════════════════════════════════

export default function Performance() {
  const [activeTab, setActiveTab] = useState('performance');
  const [perf, setPerf] = useState(null);
  const [stats, setStats] = useState(null);
  const [trades, setTrades] = useState([]);
  const [brain, setBrain] = useState(null);
  const [days, setDays] = useState(90);
  const [loading, setLoading] = useState(true);

  // ── Performans verisi ────────────────────────────────────────────
  const fetchPerfData = useCallback(async () => {
    setLoading(true);
    const [p, s, t] = await Promise.all([
      getPerformance(days),
      getTradeStats(1000),
      getTrades({ since: STATS_BASELINE, limit: 1000 }),
    ]);
    setPerf(p);
    setStats(s);
    setTrades(t.trades || []);
    setLoading(false);
  }, [days]);

  // ── Üstat beyin verisi ───────────────────────────────────────────
  const fetchBrainData = useCallback(async () => {
    setLoading(true);
    const b = await getUstatBrain(days);
    setBrain(b);
    setLoading(false);
  }, [days]);

  useEffect(() => {
    if (activeTab === 'performance') {
      fetchPerfData();
    } else {
      fetchBrainData();
    }
  }, [activeTab, fetchPerfData, fetchBrainData]);

  // ── Drawdown verisi ──────────────────────────────────────────────
  const drawdownData = useMemo(() => {
    const curve = perf?.equity_curve || [];
    if (curve.length === 0) return [];
    let peak = 0;
    return curve.map((pt) => {
      if (pt.equity > peak) peak = pt.equity;
      const dd = peak > 0 ? ((peak - pt.equity) / peak) * 100 : 0;
      return { timestamp: pt.timestamp, dd };
    });
  }, [perf]);

  // ── Strateji bazlı ──────────────────────────────────────────────
  const strategyData = useMemo(() => {
    if (!stats?.by_strategy) return [];
    return Object.entries(stats.by_strategy)
      .map(([name, s]) => ({
        name: name === 'unknown' ? 'Bilinmeyen' : name.replace(/_/g, ' '),
        pnl: s.total_pnl || 0,
        trades: s.trades || 0,
        winRate: s.win_rate || 0,
      }))
      .sort((a, b) => b.pnl - a.pnl);
  }, [stats]);

  // ── Sembol bazlı ────────────────────────────────────────────────
  const symbolData = useMemo(() => {
    if (!stats?.by_symbol) return [];
    return Object.entries(stats.by_symbol)
      .map(([sym, s]) => ({
        name: sym,
        winRate: s.win_rate || 0,
        pnl: s.total_pnl || 0,
        trades: s.trades || 0,
      }))
      .sort((a, b) => b.pnl - a.pnl)
      .slice(0, 10);
  }, [stats]);

  // ── Long vs Short ──────────────────────────────────────────────
  const longShort = useMemo(() => {
    const longs = trades.filter((t) => t.direction === 'BUY');
    const shorts = trades.filter((t) => t.direction === 'SELL');
    const calc = (arr) => {
      const pnls = arr.map((t) => t.pnl).filter((p) => p != null);
      const wins = pnls.filter((p) => p > 0);
      const losses = pnls.filter((p) => p < 0);
      const total = pnls.reduce((s, p) => s + p, 0);
      const grossProfit = wins.reduce((s, p) => s + p, 0);
      const grossLoss = Math.abs(losses.reduce((s, p) => s + p, 0));
      return {
        count: arr.length,
        winRate: pnls.length > 0 ? (wins.length / pnls.length) * 100 : 0,
        pnl: total,
        avgPnl: pnls.length > 0 ? total / pnls.length : 0,
        pf: grossLoss > 0 ? grossProfit / grossLoss : 0,
      };
    };
    return { long: calc(longs), short: calc(shorts) };
  }, [trades]);

  // ── Win Rate Trend (20-trade hareketli ortalama) ────────────────
  const winRateTrend = useMemo(() => {
    const window = 20;
    if (trades.length < window) return [];
    const result = [];
    const sorted = [...trades].reverse();
    for (let i = window - 1; i < sorted.length; i++) {
      const slice = sorted.slice(i - window + 1, i + 1);
      const wins = slice.filter((t) => t.pnl != null && t.pnl > 0).length;
      const total = slice.filter((t) => t.pnl != null).length;
      result.push({
        idx: i - window + 2,
        winRate: total > 0 ? (wins / total) * 100 : 0,
      });
    }
    return result;
  }, [trades]);

  // ── Saat bazlı performans (heatmap verisi) ─────────────────────
  const hourData = useMemo(() => {
    const hours = {};
    for (let h = 9; h <= 18; h++) {
      hours[h] = { hour: h, count: 0, pnl: 0, wins: 0 };
    }
    for (const t of trades) {
      const ts = t.entry_time;
      if (!ts) continue;
      try {
        const h = new Date(ts).getHours();
        if (hours[h]) {
          hours[h].count++;
          hours[h].pnl += t.pnl || 0;
          if (t.pnl > 0) hours[h].wins++;
        }
      } catch { /* ignore */ }
    }
    return Object.values(hours);
  }, [trades]);

  const maxHourPnl = useMemo(() => {
    const vals = hourData.map((h) => Math.abs(h.pnl));
    return Math.max(...vals, 1);
  }, [hourData]);

  // ── Aylık kâr/zarar ───────────────────────────────────────────
  const monthlyData = useMemo(() => {
    const map = {};
    for (const t of trades) {
      const ts = t.exit_time || t.entry_time;
      if (!ts || t.pnl == null) continue;
      const key = ts.slice(0, 7);
      if (!map[key]) map[key] = { month: key, pnl: 0, count: 0 };
      map[key].pnl += t.pnl;
      map[key].count++;
    }
    return Object.values(map)
      .sort((a, b) => a.month.localeCompare(b.month))
      .map((m) => ({ ...m, label: monthLabel(m.month) }));
  }, [trades]);

  // ── Üstat Analiz: Özet kartlar hesaplamaları ────────────────────
  const brainSummary = useMemo(() => {
    if (!brain) return { totalTrades: 0, bestRegime: '—', bestContract: '—', totalDecisions: 0 };

    // Toplam analiz edilen işlem
    const cats = brain.trade_categories?.by_result || [];
    const totalTrades = cats.reduce((s, c) => s + c.count, 0);

    // En iyi rejim (en yüksek win rate)
    const regimes = brain.regime_performance || [];
    const bestReg = regimes.length > 0
      ? [...regimes].sort((a, b) => b.win_rate - a.win_rate)[0]
      : null;
    const bestRegime = bestReg ? `${bestReg.label} (%${bestReg.win_rate.toFixed(0)})` : '—';

    // En verimli kontrat (en yüksek toplam K/Z)
    const profiles = brain.contract_profiles || [];
    const bestContract = profiles.length > 0 ? profiles[0].symbol : '—';

    // Toplam karar sayısı
    const totalDecisions = (brain.recent_decisions || []).length;

    return { totalTrades, bestRegime, bestContract, totalDecisions };
  }, [brain]);

  // ── Render ───────────────────────────────────────────────────────
  if (loading && !perf && !brain) {
    return (
      <div className="performance">
        <h2>Üstat & Performans</h2>
        <div className="pf-loading">Yükleniyor...</div>
      </div>
    );
  }

  const eq = perf?.equity_curve || [];

  return (
    <div className="performance">
      <div className="pf-header">
        <h2>Üstat & Performans</h2>
        <div className="pf-period-btns">
          {[30, 90, 180, 365].map((d) => (
            <button
              key={d}
              className={`pf-period-btn ${days === d ? 'active' : ''}`}
              onClick={() => setDays(d)}
            >
              {d <= 30 ? '1 Ay' : d <= 90 ? '3 Ay' : d <= 180 ? '6 Ay' : '1 Yıl'}
            </button>
          ))}
        </div>
      </div>

      {/* ═══ SEKME ÇUBUĞU ═══════════════════════════════════════════ */}
      <div className="pf-tab-bar">
        <button
          className={`pf-tab-btn ${activeTab === 'performance' ? 'active' : ''}`}
          onClick={() => setActiveTab('performance')}
        >
          Performans
        </button>
        <button
          className={`pf-tab-btn ${activeTab === 'ustat' ? 'active' : ''}`}
          onClick={() => setActiveTab('ustat')}
        >
          Üstat Analiz
        </button>
      </div>

      {/* ═══════════════════════════════════════════════════════════════
          PERFORMANS SEKMESİ
          ═════════════════════════════════════════════════════════════ */}
      {activeTab === 'performance' && (
        <>
          {/* ═══ ÖZET KARTLAR (5) ══════════════════════════════════════ */}
          <div className="pf-stats-row">
            <PfStat label="Net Kâr/Zarar" value={fmt(perf?.total_pnl)} cls={pnlCls(perf?.total_pnl)} />
            <PfStat label="Win Rate" value={fmtPct(perf?.win_rate)} cls={perf?.win_rate >= 50 ? 'profit' : 'loss'} />
            <PfStat label="Sharpe Oranı" value={fmtNum(perf?.sharpe_ratio)} cls={perf?.sharpe_ratio >= 1 ? 'profit' : ''} />
            <PfStat label="Profit Factor" value={fmtNum(perf?.profit_factor)} cls={perf?.profit_factor >= 1.5 ? 'profit' : perf?.profit_factor >= 1 ? '' : 'loss'} />
            <PfStat label="Max Drawdown" value={perf?.max_drawdown_pct != null ? `%${perf.max_drawdown_pct.toFixed(2)}` : '—'} cls="loss" />
          </div>

          {/* ═══ EQUİTY EĞRİSİ ════════════════════════════════════════ */}
          <div className="pf-chart-card pf-chart-full">
            <div className="pf-chart-header">
              <h3>Equity Eğrisi</h3>
              <span className="pf-chart-sub">{eq.length} veri noktası</span>
              <div className="pf-chart-legend">
                <span className="pf-legend-item">
                  <span className="pf-legend-line" style={{ background: '#58a6ff' }} />
                  Equity
                </span>
                <span className="pf-legend-item">
                  <span className="pf-legend-line pf-legend-dashed" />
                  Bakiye
                </span>
              </div>
            </div>
            {eq.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={eq} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="eqGradPf" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#58a6ff" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#58a6ff" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="balGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3fb950" stopOpacity={0.15} />
                      <stop offset="95%" stopColor="#3fb950" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                  <XAxis dataKey="timestamp" tickFormatter={shortDate} stroke="#8b949e" fontSize={10} tickLine={false} />
                  <YAxis stroke="#8b949e" fontSize={10} tickLine={false} tickFormatter={(v) => `${(v / 1000).toFixed(0)}K`} width={48} />
                  <Tooltip content={<EquityTip />} />
                  <Area type="monotone" dataKey="balance" stroke="#3fb950" strokeWidth={1.5} strokeDasharray="4 4" fill="url(#balGrad)" dot={false} activeDot={{ r: 3 }} />
                  <Area type="monotone" dataKey="equity" stroke="#58a6ff" strokeWidth={2} fill="url(#eqGradPf)" dot={false} activeDot={{ r: 3 }} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <div className="pf-empty">Equity verisi yok</div>}
          </div>

          {/* ═══ DRAWDOWN GRAFİĞİ ══════════════════════════════════════ */}
          <div className="pf-chart-card pf-chart-full">
            <div className="pf-chart-header">
              <h3>Drawdown</h3>
            </div>
            {drawdownData.length > 0 ? (
              <ResponsiveContainer width="100%" height={160}>
                <AreaChart data={drawdownData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#f85149" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#f85149" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                  <XAxis dataKey="timestamp" tickFormatter={shortDate} stroke="#8b949e" fontSize={10} tickLine={false} />
                  <YAxis stroke="#8b949e" fontSize={10} tickLine={false} tickFormatter={(v) => `%${v.toFixed(1)}`} width={42} reversed />
                  <Tooltip content={<DdTip />} />
                  <Area type="monotone" dataKey="dd" stroke="#f85149" strokeWidth={1.5} fill="url(#ddGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <div className="pf-empty">Drawdown verisi yok</div>}
          </div>

          {/* ═══ STRATEJİ + SEMBOL (yan yana) ══════════════════════════ */}
          <div className="pf-two-col">
            <div className="pf-chart-card">
              <div className="pf-chart-header"><h3>Strateji Bazlı K/Z</h3></div>
              {strategyData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={strategyData} layout="vertical" margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#30363d" horizontal={false} />
                    <XAxis type="number" stroke="#8b949e" fontSize={10} tickLine={false} tickFormatter={(v) => fmt(v)} />
                    <YAxis type="category" dataKey="name" stroke="#8b949e" fontSize={11} tickLine={false} width={100} />
                    <Tooltip content={<ChartTip labelKey="name" valueKey="pnl" prefix="K/Z: " />} />
                    <ReferenceLine x={0} stroke="#30363d" />
                    <Bar dataKey="pnl" radius={[0, 3, 3, 0]} maxBarSize={20}>
                      {strategyData.map((e, i) => (
                        <Cell key={i} fill={e.pnl >= 0 ? '#3fb950' : '#f85149'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : <div className="pf-empty">Strateji verisi yok</div>}
            </div>

            <div className="pf-chart-card">
              <div className="pf-chart-header"><h3>Sembol Bazlı K/Z (Top 10)</h3></div>
              {symbolData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={symbolData} layout="vertical" margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#30363d" horizontal={false} />
                    <XAxis type="number" stroke="#8b949e" fontSize={10} tickLine={false} tickFormatter={(v) => fmt(v)} />
                    <YAxis type="category" dataKey="name" stroke="#8b949e" fontSize={10} tickLine={false} width={80} />
                    <Tooltip content={<ChartTip labelKey="name" valueKey="pnl" prefix="K/Z: " />} />
                    <ReferenceLine x={0} stroke="#30363d" />
                    <Bar dataKey="pnl" radius={[0, 3, 3, 0]} maxBarSize={18}>
                      {symbolData.map((e, i) => (
                        <Cell key={i} fill={e.pnl >= 0 ? '#3fb950' : '#f85149'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : <div className="pf-empty">Sembol verisi yok</div>}
            </div>
          </div>

          {/* ═══ LONG vs SHORT + WIN RATE TREND (yan yana) ════════════ */}
          <div className="pf-two-col">
            <div className="pf-chart-card">
              <div className="pf-chart-header"><h3>Long vs Short</h3></div>
              <div className="pf-ls-grid">
                <div className="pf-ls-col">
                  <span className="pf-ls-title profit">LONG (BUY)</span>
                  <LsRow label="İşlem" value={longShort.long.count} />
                  <LsRow label="Win Rate" value={fmtPct(longShort.long.winRate)} cls={longShort.long.winRate >= 50 ? 'profit' : 'loss'} />
                  <LsRow label="Net K/Z" value={fmt(longShort.long.pnl)} cls={pnlCls(longShort.long.pnl)} />
                  <LsRow label="Ort. K/Z" value={fmt(longShort.long.avgPnl)} cls={pnlCls(longShort.long.avgPnl)} />
                  <LsRow label="PF" value={fmtNum(longShort.long.pf)} />
                </div>
                <div className="pf-ls-divider" />
                <div className="pf-ls-col">
                  <span className="pf-ls-title loss">SHORT (SELL)</span>
                  <LsRow label="İşlem" value={longShort.short.count} />
                  <LsRow label="Win Rate" value={fmtPct(longShort.short.winRate)} cls={longShort.short.winRate >= 50 ? 'profit' : 'loss'} />
                  <LsRow label="Net K/Z" value={fmt(longShort.short.pnl)} cls={pnlCls(longShort.short.pnl)} />
                  <LsRow label="Ort. K/Z" value={fmt(longShort.short.avgPnl)} cls={pnlCls(longShort.short.avgPnl)} />
                  <LsRow label="PF" value={fmtNum(longShort.short.pf)} />
                </div>
              </div>
            </div>

            <div className="pf-chart-card">
              <div className="pf-chart-header"><h3>Win Rate Trend (20-İşlem MA)</h3></div>
              {winRateTrend.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={winRateTrend} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                    <XAxis dataKey="idx" stroke="#8b949e" fontSize={10} tickLine={false} />
                    <YAxis stroke="#8b949e" fontSize={10} tickLine={false} domain={[0, 100]} tickFormatter={(v) => `%${v}`} width={38} />
                    <Tooltip formatter={(v) => [`%${v.toFixed(1)}`, 'Win Rate']} contentStyle={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 6, fontSize: 12 }} />
                    <ReferenceLine y={50} stroke="#30363d" strokeDasharray="4 4" />
                    <Line type="monotone" dataKey="winRate" stroke="#58a6ff" strokeWidth={2} dot={false} activeDot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              ) : <div className="pf-empty">Yeterli işlem yok</div>}
            </div>
          </div>

          {/* ═══ SAAT BAZLI HEATMAP ════════════════════════════════════ */}
          <div className="pf-chart-card pf-chart-full">
            <div className="pf-chart-header"><h3>Saat Bazlı Performans</h3></div>
            <div className="pf-heatmap">
              {hourData.map((h) => {
                const intensity = maxHourPnl > 0 ? Math.abs(h.pnl) / maxHourPnl : 0;
                const bg = h.pnl >= 0
                  ? `rgba(63, 185, 80, ${0.08 + intensity * 0.4})`
                  : `rgba(248, 81, 73, ${0.08 + intensity * 0.4})`;
                return (
                  <div key={h.hour} className="pf-hm-cell" style={{ background: bg }}>
                    <span className="pf-hm-hour">{h.hour.toString().padStart(2, '0')}:00</span>
                    <span className={`pf-hm-pnl ${pnlCls(h.pnl)}`}>{fmt(h.pnl)}</span>
                    <span className="pf-hm-count">{h.count} işlem</span>
                    <span className="pf-hm-wr">
                      WR: {h.count > 0 ? `%${((h.wins / h.count) * 100).toFixed(0)}` : '—'}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* ═══ AYLIK K/Z BREAKDOWN ═══════════════════════════════════ */}
          <div className="pf-chart-card pf-chart-full">
            <div className="pf-chart-header"><h3>Aylık Kâr/Zarar</h3></div>
            {monthlyData.length > 0 ? (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={monthlyData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                  <XAxis dataKey="label" stroke="#8b949e" fontSize={11} tickLine={false} />
                  <YAxis stroke="#8b949e" fontSize={10} tickLine={false} tickFormatter={(v) => v >= 1000 || v <= -1000 ? `${(v / 1000).toFixed(0)}K` : v.toFixed(0)} width={44} />
                  <Tooltip content={<ChartTip labelKey="label" valueKey="pnl" />} />
                  <ReferenceLine y={0} stroke="#30363d" />
                  <Bar dataKey="pnl" radius={[3, 3, 0, 0]} maxBarSize={32}>
                    {monthlyData.map((e, i) => (
                      <Cell key={i} fill={e.pnl >= 0 ? '#3fb950' : '#f85149'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="pf-empty">Aylık veri yok</div>}
          </div>
        </>
      )}

      {/* ═══════════════════════════════════════════════════════════════
          ÜSTAT ANALİZ SEKMESİ
          ═════════════════════════════════════════════════════════════ */}
      {activeTab === 'ustat' && (
        <>
          {/* ═══ A) ÖZET KARTLAR (4) ═══════════════════════════════════ */}
          <div className="pf-stats-row" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
            <PfStat label="Analiz Edilen İşlem" value={brainSummary.totalTrades} />
            <PfStat label="En İyi Rejim" value={brainSummary.bestRegime} />
            <PfStat label="En Verimli Kontrat" value={brainSummary.bestContract} />
            <PfStat label="Toplam Karar" value={brainSummary.totalDecisions} />
          </div>

          {/* ═══ B) İŞLEM KATEGORİLERİ (2x2 grid) ════════════════════ */}
          <div className="pf-category-grid">
            <CategoryChart title="Sonuca Göre" data={brain?.trade_categories?.by_result || []} />
            <CategoryChart title="Yöne Göre" data={brain?.trade_categories?.by_direction || []} />
            <CategoryChart title="Süreye Göre" data={brain?.trade_categories?.by_duration || []} />
            <CategoryChart title="Rejime Göre" data={brain?.trade_categories?.by_regime || []} />
          </div>

          {/* ═══ C) KONTRAT PROFİLLERİ ════════════════════════════════ */}
          <div className="pf-chart-card pf-chart-full">
            <div className="pf-chart-header"><h3>Kontrat Profilleri</h3></div>
            {(brain?.contract_profiles || []).length > 0 ? (
              <div className="pf-contract-grid">
                {brain.contract_profiles.map((cp) => (
                  <div key={cp.symbol} className="pf-contract-card">
                    <div className="pf-contract-symbol">
                      <span>{cp.symbol}</span>
                      <span className={`pf-contract-badge ${cp.preferred_direction === 'BUY' ? 'buy' : 'sell'}`}>
                        {cp.preferred_direction}
                      </span>
                    </div>
                    <div className="pf-contract-stat">
                      <span>İşlem</span>
                      <span className="value">{cp.trade_count}</span>
                    </div>
                    <div className="pf-contract-stat">
                      <span>Win Rate</span>
                      <span className={`value ${cp.win_rate >= 50 ? 'profit' : 'loss'}`}>{fmtPct(cp.win_rate)}</span>
                    </div>
                    <div className="pf-contract-stat">
                      <span>Toplam K/Z</span>
                      <span className={`value ${pnlCls(cp.total_pnl)}`}>{fmt(cp.total_pnl)}</span>
                    </div>
                    <div className="pf-contract-stat">
                      <span>Ort. Süre</span>
                      <span className="value">{cp.avg_duration_min > 60 ? `${(cp.avg_duration_min / 60).toFixed(1)}s` : `${cp.avg_duration_min.toFixed(0)}dk`}</span>
                    </div>
                    <div className="pf-contract-stat">
                      <span>Son İşlem</span>
                      <span className="value" style={{ fontSize: 10 }}>{cp.last_trade || '—'}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : <div className="pf-empty">Kontrat verisi yok</div>}
          </div>

          {/* ═══ D) KARAR AKIŞI (Timeline) ════════════════════════════ */}
          <div className="pf-chart-card pf-chart-full">
            <div className="pf-chart-header"><h3>Karar Akışı</h3></div>
            {(brain?.recent_decisions || []).length > 0 ? (
              <div className="pf-decision-timeline">
                {brain.recent_decisions.slice(0, 20).map((ev) => (
                  <div key={ev.id} className="pf-decision-item">
                    <span className="pf-decision-time">{shortDate(ev.timestamp)}</span>
                    <span className={`pf-decision-badge ${ev.severity}`}>{ev.type}</span>
                    <span className="pf-decision-msg">{ev.message}</span>
                  </div>
                ))}
              </div>
            ) : <div className="pf-empty">Karar verisi yok</div>}
          </div>

          {/* ═══ E) REJİM BAZLI PERFORMANS ════════════════════════════ */}
          <div className="pf-chart-card pf-chart-full">
            <div className="pf-chart-header">
              <h3>Rejim Bazlı Performans</h3>
              {brain?.strategy_pool?.current_regime && (
                <span className="pf-chart-sub">Aktif rejim: {brain.strategy_pool.current_regime}</span>
              )}
            </div>
            {(brain?.regime_performance || []).length > 0 ? (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={brain.regime_performance} layout="vertical" margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" horizontal={false} />
                  <XAxis type="number" stroke="#8b949e" fontSize={10} tickLine={false} tickFormatter={(v) => fmt(v)} />
                  <YAxis type="category" dataKey="label" stroke="#8b949e" fontSize={11} tickLine={false} width={90} />
                  <Tooltip content={<CategoryTip />} />
                  <ReferenceLine x={0} stroke="#30363d" />
                  <Bar dataKey="total_pnl" radius={[0, 3, 3, 0]} maxBarSize={22}>
                    {(brain.regime_performance || []).map((e, i) => (
                      <Cell key={i} fill={e.total_pnl >= 0 ? '#3fb950' : '#f85149'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="pf-empty">Rejim verisi yok</div>}
          </div>

          {/* ═══ F) ÜSTAT BEYİN PANELLERİ ═══════════════════════════════ */}
          <div className="pf-brain-grid">

            {/* ── Hata Atama Raporu ─────────────────────────────────── */}
            {(brain?.error_attributions || []).length > 0 ? (
              <div className="pf-chart-card">
                <div className="pf-chart-header"><h3>Hata Atama Raporu</h3></div>
                <div className="pf-brain-list">
                  {brain.error_attributions.slice(0, 10).map((ea, i) => (
                    <div key={i} className="pf-brain-row">
                      <span className={`pf-brain-badge pf-brain--${ea.responsible.toLowerCase()}`}>
                        {ea.responsible}
                      </span>
                      <span className="pf-brain-type">{ea.error_type}</span>
                      <span className="pf-brain-desc">{ea.description}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="pf-placeholder-card">
                <span className="pf-placeholder-icon">&#x1F50D;</span>
                <span className="pf-placeholder-title">Hata Atama Raporu</span>
                <span className="pf-placeholder-desc">
                  Kim hata yapti? BABA veya OGUL sorumluluk atamasi.
                  USTAT beyin motoru aktif oldugunda dolacak.
                </span>
                <span className="pf-placeholder-badge">Veri bekleniyor</span>
              </div>
            )}

            {/* ── Ertesi Gün Analizi ───────────────────────────────── */}
            {(brain?.next_day_analyses || []).length > 0 ? (
              <div className="pf-chart-card">
                <div className="pf-chart-header"><h3>Ertesi Gun Analizi</h3></div>
                <div className="pf-brain-list">
                  {brain.next_day_analyses.slice(0, 10).map((nda, i) => (
                    <div key={i} className="pf-brain-row pf-nda-row">
                      <span className="pf-brain-symbol">{nda.symbol}</span>
                      <span className={`pf-brain-pnl ${nda.actual_pnl >= 0 ? 'pf-green' : 'pf-red'}`}>
                        {fmt(nda.actual_pnl)}
                      </span>
                      <span className="pf-brain-dim">
                        Potansiyel: {fmt(nda.potential_pnl)} | Kacirilan: {fmt(nda.missed_profit)}
                      </span>
                      <div className="pf-nda-scores">
                        <span title="Sinyal puani">S:{Math.round(nda.signal_score)}</span>
                        <span title="Yonetim puani">Y:{Math.round(nda.management_score)}</span>
                        <span title="Kar puani">K:{Math.round(nda.profit_score)}</span>
                        <span title="Risk puani">R:{Math.round(nda.risk_score)}</span>
                        <span className="pf-nda-total" title="Toplam puan">
                          {Math.round(nda.total_score)}/100
                        </span>
                      </div>
                      {nda.summary && <span className="pf-brain-desc">{nda.summary}</span>}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="pf-placeholder-card">
                <span className="pf-placeholder-icon">&#x1F4CA;</span>
                <span className="pf-placeholder-title">Ertesi Gun Analizi</span>
                <span className="pf-placeholder-desc">
                  Kapanan islemler icin islem gununun ertesi gunu otomatik analiz.
                  Her sabah 09:30'da bir onceki gunun islemleri puanlanir.
                </span>
                <span className="pf-placeholder-badge">Veri bekleniyor</span>
              </div>
            )}

            {/* ── Regülasyon Önerileri ─────────────────────────────── */}
            {(brain?.regulation_suggestions || []).length > 0 ? (
              <div className="pf-chart-card">
                <div className="pf-chart-header"><h3>Regulasyon Onerileri</h3></div>
                <div className="pf-brain-list">
                  {brain.regulation_suggestions.slice(0, 10).map((rs, i) => (
                    <div key={i} className="pf-brain-row pf-reg-row">
                      <span className={`pf-brain-badge pf-brain--${rs.priority.toLowerCase()}`}>
                        {rs.priority}
                      </span>
                      <span className="pf-brain-type">{rs.parameter}</span>
                      <span className="pf-brain-dim">
                        {rs.current_value} &rarr; {rs.suggested_value}
                      </span>
                      <span className="pf-brain-desc">{rs.reason}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="pf-placeholder-card">
                <span className="pf-placeholder-icon">&#x2699;</span>
                <span className="pf-placeholder-title">Regulasyon Onerileri</span>
                <span className="pf-placeholder-desc">
                  BABA/OGUL parametre duzeltme onerileri.
                  Her aksam 18:00'da gunluk rapor uretilir.
                </span>
                <span className="pf-placeholder-badge">Veri bekleniyor</span>
              </div>
            )}

          </div>
        </>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
//  ALT BİLEŞENLER
// ═══════════════════════════════════════════════════════════════════

function PfStat({ label, value, cls }) {
  return (
    <div className="pf-stat-card">
      <span className="pf-stat-label">{label}</span>
      <span className={`pf-stat-value ${cls || ''}`}>{value}</span>
    </div>
  );
}

function LsRow({ label, value, cls }) {
  return (
    <div className="pf-ls-row">
      <span className="pf-ls-label">{label}</span>
      <span className={`pf-ls-value ${cls || ''}`}>{value}</span>
    </div>
  );
}

function CategoryChart({ title, data }) {
  if (!data || data.length === 0) {
    return (
      <div className="pf-chart-card">
        <div className="pf-chart-header"><h3>{title}</h3></div>
        <div className="pf-empty">Veri yok</div>
      </div>
    );
  }
  return (
    <div className="pf-chart-card">
      <div className="pf-chart-header"><h3>{title}</h3></div>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={data} layout="vertical" margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#30363d" horizontal={false} />
          <XAxis type="number" stroke="#8b949e" fontSize={10} tickLine={false} tickFormatter={(v) => fmt(v)} />
          <YAxis type="category" dataKey="label" stroke="#8b949e" fontSize={11} tickLine={false} width={80} />
          <Tooltip content={<CategoryTip />} />
          <ReferenceLine x={0} stroke="#30363d" />
          <Bar dataKey="total_pnl" radius={[0, 3, 3, 0]} maxBarSize={18}>
            {data.map((e, i) => (
              <Cell key={i} fill={e.total_pnl >= 0 ? '#3fb950' : '#f85149'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
