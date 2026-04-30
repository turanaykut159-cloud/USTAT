/**
 * ÜSTAT v5.7 — Performans ekranı.
 *
 * 9 Bölüm:
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
 * Veri: getPerformance, getTradeStats, getTrades
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  AreaChart, Area,
  BarChart, Bar, Cell,
  LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { getPerformance, getTradeStats, getTrades, getSession, getStatsBaseline, STATS_BASELINE } from '../services/api';
// Widget Denetimi H13: Long/Short win rate renk eşiği canonical kaynağa
// bağlandı — eski iki call site (line 494 long, line 503 short) hardcode
// `>= 50` kullanıyordu. Artık winRateClass helper'ı formatters.js
// WIN_RATE_BREAKEVEN_PCT sabitinden okuyor, drift koruması Flow 4y.
import { winRateClass } from '../utils/formatters';

// ── BIST VİOP seans saatleri — Widget Denetimi A17 ──
// Heatmap saat aralığı backend config/default.json::session'dan okunur.
// Fallback (API erişilemezse) BIST sabitleri: 09:30-18:15.
const DEFAULT_HEATMAP_HOURS = { market_open: '09:30', market_close: '18:15' };

// "HH:MM" → integer saat bölümü (00-23). Geçersizde null.
function parseHour(str) {
  if (typeof str !== 'string') return null;
  const m = /^(\d{2}):\d{2}$/.exec(str);
  if (!m) return null;
  const h = Number(m[1]);
  if (Number.isNaN(h) || h < 0 || h > 23) return null;
  return h;
}

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
      {/* A6 (B14): yatırım transferleri hariç net sermaye */}
      {d.net_equity != null && d.net_equity !== d.equity && (
        <span style={{ color: '#d29922' }}>Net Sermaye: <b>{fmt(d.net_equity)}</b></span>
      )}
      {d.cumulative_deposits != null && d.cumulative_deposits !== 0 && (
        <span style={{ color: '#8b949e', fontSize: 11 }}>Yatırım: <b>{fmt(d.cumulative_deposits)}</b></span>
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
  const [perf, setPerf] = useState(null);
  const [stats, setStats] = useState(null);
  const [trades, setTrades] = useState([]);
  const [days, setDays] = useState(90);
  const [loading, setLoading] = useState(true);
  // M3-294: Promise.all reject'inde sonsuz spinner bug'i — UstatBrain #280 ile
  // ayni pattern. fetchPerfData try/catch/finally ile sariliyor, hata durumunda
  // "Tekrar Dene" butonu gosteriliyor.
  const [fetchError, setFetchError] = useState(null);
  // A17: Heatmap saat aralığı backend session config'den çekilir.
  const [heatmapHours, setHeatmapHours] = useState(DEFAULT_HEATMAP_HOURS);
  // A7: Aktif istatistik/risk baseline tarihleri backend'den çekilir.
  const [baselineInfo, setBaselineInfo] = useState({
    stats_baseline: STATS_BASELINE,
    risk_baseline: '',
    stats_source: 'default',
    risk_source: 'unavailable',
  });

  // ── A17: Session saatleri mount'ta çekilir, hata durumunda default ──
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const data = await getSession();
      if (cancelled) return;
      setHeatmapHours({
        market_open: data?.market_open || DEFAULT_HEATMAP_HOURS.market_open,
        market_close: data?.market_close || DEFAULT_HEATMAP_HOURS.market_close,
      });
    })();
    return () => { cancelled = true; };
  }, []);

  // ── A7: Stats baseline mount'ta çekilir, fallback STATS_BASELINE ─
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const data = await getStatsBaseline();
      if (cancelled) return;
      setBaselineInfo({
        stats_baseline: data?.stats_baseline || STATS_BASELINE,
        risk_baseline: data?.risk_baseline || '',
        stats_source: data?.stats_source || 'default',
        risk_source: data?.risk_source || 'unavailable',
      });
    })();
    return () => { cancelled = true; };
  }, []);

  // ── Performans verisi ────────────────────────────────────────────
  const fetchPerfData = useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    try {
      const [p, s, t] = await Promise.all([
        getPerformance(days),
        getTradeStats(1000, baselineInfo.stats_baseline),
        getTrades({ since: baselineInfo.stats_baseline, limit: 1000 }),
      ]);
      setPerf(p);
      setStats(s);
      setTrades(t.trades || []);
    } catch (err) {
      // M3-294: Promise.all reject'inde onceden setLoading(false) hic calismazdi,
      // sonsuz spinner. Artik son bilinen veri korunur, rozet gosterilir.
      console.error('[Performance] fetchPerfData:', err?.message ?? err);
      setFetchError(err?.message ?? 'Bilinmeyen hata');
    } finally {
      setLoading(false);
    }
  }, [days, baselineInfo.stats_baseline]);

  useEffect(() => {
    fetchPerfData();
  }, [fetchPerfData]);

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

  // ── Saat bazlı performans (heatmap verisi) — A17 ───────────────
  // Heatmap saat aralığı config/default.json::session'dan okunur.
  // Fallback: BIST VİOP 09-18 (DEFAULT_HEATMAP_HOURS).
  const hourData = useMemo(() => {
    const hours = {};
    const openHour = parseHour(heatmapHours.market_open) ?? parseHour(DEFAULT_HEATMAP_HOURS.market_open);
    const closeHour = parseHour(heatmapHours.market_close) ?? parseHour(DEFAULT_HEATMAP_HOURS.market_close);
    for (let h = openHour; h <= closeHour; h++) {
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
  }, [trades, heatmapHours]);

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
  // ── Render ───────────────────────────────────────────────────────
  if (loading && !perf && !fetchError) {
    return (
      <div className="performance">
        <h2>Performans</h2>
        <div className="pf-loading">Yükleniyor...</div>
      </div>
    );
  }

  // M3-294: Hata durumu — kullanici "Tekrar Dene" ile yeniden cagrabilir.
  if (!perf && fetchError) {
    return (
      <div className="performance">
        <h2>Performans</h2>
        <div className="pf-loading" style={{ color: '#f85149' }}>
          Performans verisi yüklenemedi: {fetchError}
        </div>
        <button
          type="button"
          onClick={fetchPerfData}
          style={{ marginTop: 12, padding: '6px 14px', cursor: 'pointer' }}
        >
          Tekrar Dene
        </button>
      </div>
    );
  }

  const eq = perf?.equity_curve || [];

  return (
    <div className="performance">
      <div className="pf-header">
        <h2>Performans</h2>
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

      {/* A7: Aktif istatistik tabanı + risk tabanı etiketi */}
      <div className="pf-baseline-label" title="İstatistik tabanı: Dashboard, Performans ve TradeHistory kartlarındaki win rate, profit factor, best/worst trade gibi metriklerin başlangıç tarihi. Risk tabanı: BABA peak_equity ve drawdown hesaplamalarının başlangıcı.">
        <span>İstatistik tabanı: <b>{(baselineInfo.stats_baseline || STATS_BASELINE).slice(0, 10)}</b></span>
        {baselineInfo.risk_baseline && (
          <span style={{ marginLeft: 12 }}>· Risk tabanı: <b>{baselineInfo.risk_baseline.slice(0, 10)}</b></span>
        )}
      </div>

      {/* ═══════════════════════════════════════════════════════════════
          PERFORMANS İÇERİĞİ
          ═════════════════════════════════════════════════════════════ */}
          {/* ═══ ÖZET KARTLAR (5) ══════════════════════════════════════ */}
          {/* P1-A: Bu kartlar getPerformance(days) sonucundan beslenir.
              Backend artık "baseline + son N gün" kesişimini uygular.
              Equity eğrisi ve aggregate metrikler periyot butonuna duyarlı. */}
          <div
            className="pf-stats-row"
            title={`Seçili pencere: Son ${days} gün (istatistik tabanı ${(baselineInfo.stats_baseline || STATS_BASELINE).slice(0, 10)} sonrası)`}
          >
            <PfStat label="Net Kâr/Zarar" value={fmt(perf?.total_pnl)} cls={pnlCls(perf?.total_pnl)} />
            <PfStat label="Win Rate" value={fmtPct(perf?.win_rate)} cls={winRateClass(perf?.win_rate)} />
            <PfStat label="Sharpe Oranı" value={fmtNum(perf?.sharpe_ratio)} cls={perf?.sharpe_ratio >= 1 ? 'profit' : ''} />
            <PfStat label="Profit Factor" value={fmtNum(perf?.profit_factor)} cls={perf?.profit_factor >= 1.5 ? 'profit' : perf?.profit_factor >= 1 ? '' : 'loss'} />
            <PfStat label="Max Drawdown" value={perf?.max_drawdown_pct != null ? `%${perf.max_drawdown_pct.toFixed(2)}` : '—'} cls="loss" />
          </div>

          {/* ═══ EQUİTY EĞRİSİ ════════════════════════════════════════ */}
          <div className="pf-chart-card pf-chart-full">
            <div className="pf-chart-header">
              <h3>Equity Eğrisi — Son {days} Gün</h3>
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
                {/* A6 (B14): yatırım hariç net sermaye */}
                <span className="pf-legend-item" title="Net Sermaye = Equity − kümülatif yatırım. Yatırım transferleri kâr olarak gösterilmez.">
                  <span className="pf-legend-line" style={{ background: '#d29922' }} />
                  Net Sermaye
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
                  {/* A6 (B14): Net sermaye serisi — yatırım transferleri hariç */}
                  <Area type="monotone" dataKey="net_equity" stroke="#d29922" strokeWidth={2} fill="none" dot={false} activeDot={{ r: 3 }} />
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

          {/* ═══ STRATEJİ + SEMBOL (yan yana) ══════════════════════════
              NOT: Aşağıdaki iki kart `getTradeStats` (baseline-anchored) verisinden
              beslenir; periyot butonundan ETKİLENMEZ. Bu tasarımdır — aggregate
              sembol/strateji metrikleri tarihsel anchor'a ihtiyaç duyar. */}
          <div className="pf-two-col">
            <div className="pf-chart-card">
              <div className="pf-chart-header">
                <h3>Strateji Bazlı K/Z</h3>
                <span
                  className="pf-chart-sub"
                  title={`Baseline (${(baselineInfo.stats_baseline || STATS_BASELINE).slice(0, 10)}) sonrası tüm işlemler`}
                  style={{ fontSize: 10, opacity: 0.6 }}
                >
                  baseline'dan beri
                </span>
              </div>
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
              <div className="pf-chart-header">
                <h3>Sembol Bazlı K/Z (Top 10)</h3>
                <span
                  className="pf-chart-sub"
                  title={`Baseline (${(baselineInfo.stats_baseline || STATS_BASELINE).slice(0, 10)}) sonrası tüm işlemler`}
                  style={{ fontSize: 10, opacity: 0.6 }}
                >
                  baseline'dan beri
                </span>
              </div>
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
                  <LsRow label="Win Rate" value={fmtPct(longShort.long.winRate)} cls={winRateClass(longShort.long.winRate)} />
                  <LsRow label="Net K/Z" value={fmt(longShort.long.pnl)} cls={pnlCls(longShort.long.pnl)} />
                  <LsRow label="Ort. K/Z" value={fmt(longShort.long.avgPnl)} cls={pnlCls(longShort.long.avgPnl)} />
                  <LsRow label="PF" value={fmtNum(longShort.long.pf)} />
                </div>
                <div className="pf-ls-divider" />
                <div className="pf-ls-col">
                  <span className="pf-ls-title loss">SHORT (SELL)</span>
                  <LsRow label="İşlem" value={longShort.short.count} />
                  <LsRow label="Win Rate" value={fmtPct(longShort.short.winRate)} cls={winRateClass(longShort.short.winRate)} />
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
