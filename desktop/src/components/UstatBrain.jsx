/**
 * ÜSTAT v5.7 — Üstat Beyin Merkezi
 *
 * Kurumsal ve profesyonel analiz sayfası.
 * Üç motor mimarisinin beyin katmanı: ÜSTAT analiz motoru.
 *
 * Bölümler:
 *   1. Hero banner — Motor durumu + özet metrikler
 *   2. Üç Motor Panorama — BABA / OĞUL / ÜSTAT canlı durum kartları
 *   3. İşlem Kategorileri — 4'lü grid (sonuç, yön, süre, rejim)
 *   4. Kontrat Profilleri — Detaylı sembol kartları
 *   5. Karar Akışı — Zaman çizelgesi
 *   6. Rejim Bazlı Performans — Bar chart
 *   7. Beyin Panelleri — Hata atama, ertesi gün analizi, regülasyon
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { getUstatBrain, getPerformance, getStatus } from '../services/api';

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

// ── Tooltip ──────────────────────────────────────────────────────

function CategoryTip({ active, payload }) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <span className="chart-tooltip-date">{d.label}</span>
      <span className={pnlCls(d.total_pnl)}>K/Z: <b>{fmt(d.total_pnl)}</b></span>
      <span>WR: {fmtPct(d.win_rate)} | {d.count} islem</span>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//  ANA BİLEŞEN
// ═══════════════════════════════════════════════════════════════════

export default function UstatBrain() {
  const [brain, setBrain] = useState(null);
  const [perf, setPerf] = useState(null);
  const [status, setStatus] = useState(null);
  const [days, setDays] = useState(90);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    const [b, p, s] = await Promise.all([
      getUstatBrain(days),
      getPerformance(days),
      getStatus(),
    ]);
    setBrain(b);
    setPerf(p);
    setStatus(s);
    setLoading(false);
  }, [days]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ── Özet hesaplamalar ──────────────────────────────────────────
  const summary = useMemo(() => {
    if (!brain) return { totalTrades: 0, bestRegime: '—', bestContract: '—', totalDecisions: 0 };
    const cats = brain.trade_categories?.by_result || [];
    const totalTrades = cats.reduce((s, c) => s + c.count, 0);
    const regimes = brain.regime_performance || [];
    const bestReg = regimes.length > 0 ? [...regimes].sort((a, b) => b.win_rate - a.win_rate)[0] : null;
    const bestRegime = bestReg ? `${bestReg.label} (%${bestReg.win_rate.toFixed(0)})` : '—';
    const profiles = brain.contract_profiles || [];
    const bestContract = profiles.length > 0 ? profiles[0].symbol : '—';
    const totalDecisions = (brain.recent_decisions || []).length;
    return { totalTrades, bestRegime, bestContract, totalDecisions };
  }, [brain]);

  // ── Motor durumları ────────────────────────────────────────────
  const motors = useMemo(() => {
    const phase = status?.phase || 'unknown';
    const mt5 = status?.mt5_connected || false;
    const engineOn = status?.engine_running || false;
    return {
      baba: { name: 'BABA', role: 'Kalkan', desc: 'Risk yonetimi, rejim algilama, kill-switch',
              status: engineOn ? 'AKTIF' : 'DURDURULDU', ok: engineOn },
      ogul: { name: 'OGUL', role: 'Silah', desc: 'Top 5 secim, sinyal uretimi, emir yonetimi',
              status: engineOn && mt5 ? 'AKTIF' : 'BEKLEMEDE', ok: engineOn && mt5 },
      ustat: { name: 'USTAT', role: 'Beyin', desc: 'Hata atfetme, strateji havuzu, analiz',
               status: engineOn ? 'AKTIF' : 'DURDURULDU', ok: engineOn },
    };
  }, [status]);

  if (loading && !brain) {
    return (
      <div className="ustat-brain">
        <div className="ub-loading">
          <div className="ub-loading-spinner" />
          <span>USTAT Beyin Merkezi yukleniyor...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="ustat-brain">

      {/* ═══ 1. HERO BANNER ═══════════════════════════════════════════ */}
      <div className="ub-hero">
        <div className="ub-hero-left">
          <div className="ub-hero-brand">
            <span className="ub-hero-logo">U</span>
            <div className="ub-hero-title-group">
              <h1 className="ub-hero-title">USTAT</h1>
              <span className="ub-hero-subtitle">Beyin Merkezi</span>
            </div>
          </div>
          <p className="ub-hero-desc">
            Uc motor mimarisinin analiz katmani.
            Hata atfetme, strateji havuzu yonetimi ve kontrat profilleme.
          </p>
        </div>
        <div className="ub-hero-right">
          <div className="ub-hero-metrics">
            <div className="ub-hero-metric">
              <span className="ub-hm-value">{summary.totalTrades}</span>
              <span className="ub-hm-label">Analiz Edilen Islem</span>
            </div>
            <div className="ub-hero-metric">
              <span className="ub-hm-value">{summary.bestRegime}</span>
              <span className="ub-hm-label">En Iyi Rejim</span>
            </div>
            <div className="ub-hero-metric">
              <span className="ub-hm-value">{summary.bestContract}</span>
              <span className="ub-hm-label">En Verimli Kontrat</span>
            </div>
            <div className="ub-hero-metric">
              <span className="ub-hm-value">{summary.totalDecisions}</span>
              <span className="ub-hm-label">Toplam Karar</span>
            </div>
          </div>
          <div className="ub-hero-period">
            {[30, 90, 180, 365].map((d) => (
              <button key={d} className={`ub-period-btn ${days === d ? 'active' : ''}`} onClick={() => setDays(d)}>
                {d <= 30 ? '1 Ay' : d <= 90 ? '3 Ay' : d <= 180 ? '6 Ay' : '1 Yil'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ═══ 2. UC MOTOR PANORAMA ════════════════════════════════════ */}
      <div className="ub-motors">
        {Object.values(motors).map((m) => (
          <div key={m.name} className={`ub-motor-card ${m.ok ? 'ub-motor--active' : 'ub-motor--inactive'}`}>
            <div className="ub-motor-header">
              <span className={`ub-motor-indicator ${m.ok ? 'ub-ind--green' : 'ub-ind--red'}`} />
              <span className="ub-motor-name">{m.name}</span>
              <span className="ub-motor-role">{m.role}</span>
            </div>
            <p className="ub-motor-desc">{m.desc}</p>
            <span className={`ub-motor-status ${m.ok ? 'ub-status--ok' : 'ub-status--warn'}`}>{m.status}</span>
          </div>
        ))}
      </div>

      {/* ═══ 3. ISLEM KATEGORILERI ═══════════════════════════════════ */}
      <div className="ub-section">
        <h2 className="ub-section-title">Islem Kategorileri</h2>
        <div className="ub-cat-grid">
          <MiniBarChart title="Sonuca Gore" data={brain?.trade_categories?.by_result || []} />
          <MiniBarChart title="Yone Gore" data={brain?.trade_categories?.by_direction || []} />
          <MiniBarChart title="Sureye Gore" data={brain?.trade_categories?.by_duration || []} />
          <MiniBarChart title="Rejime Gore" data={brain?.trade_categories?.by_regime || []} />
        </div>
      </div>

      {/* ═══ 4. KONTRAT PROFILLERI ═══════════════════════════════════ */}
      <div className="ub-section">
        <h2 className="ub-section-title">Kontrat Profilleri</h2>
        {(brain?.contract_profiles || []).length > 0 ? (
          <div className="ub-profile-grid">
            {brain.contract_profiles.map((cp) => (
              <div key={cp.symbol} className="ub-profile-card">
                <div className="ub-profile-header">
                  <span className="ub-profile-symbol">{cp.symbol}</span>
                  <span className={`ub-profile-dir ${cp.preferred_direction === 'BUY' ? 'ub-dir--buy' : 'ub-dir--sell'}`}>
                    {cp.preferred_direction}
                  </span>
                </div>
                <div className="ub-profile-stats">
                  <div className="ub-ps"><span className="ub-ps-label">Islem</span><span className="ub-ps-val">{cp.trade_count}</span></div>
                  <div className="ub-ps"><span className="ub-ps-label">Win Rate</span><span className={`ub-ps-val ${cp.win_rate >= 50 ? 'profit' : 'loss'}`}>{fmtPct(cp.win_rate)}</span></div>
                  <div className="ub-ps"><span className="ub-ps-label">K/Z</span><span className={`ub-ps-val ${pnlCls(cp.total_pnl)}`}>{fmt(cp.total_pnl)}</span></div>
                  <div className="ub-ps"><span className="ub-ps-label">Ort. Sure</span><span className="ub-ps-val">{cp.avg_duration_min > 60 ? `${(cp.avg_duration_min / 60).toFixed(1)}s` : `${cp.avg_duration_min.toFixed(0)}dk`}</span></div>
                </div>
              </div>
            ))}
          </div>
        ) : <EmptyState icon="📈" text="Kontrat verisi yok" />}
      </div>

      {/* ═══ 5. KARAR AKISI ═════════════════════════════════════════ */}
      <div className="ub-section">
        <h2 className="ub-section-title">Karar Akisi</h2>
        {(brain?.recent_decisions || []).length > 0 ? (
          <div className="ub-timeline">
            {brain.recent_decisions.slice(0, 20).map((ev) => (
              <div key={ev.id} className="ub-tl-item">
                <div className="ub-tl-dot" />
                <div className="ub-tl-content">
                  <div className="ub-tl-top">
                    <span className="ub-tl-time">{shortDate(ev.timestamp)}</span>
                    <span className={`ub-tl-badge ub-sev--${ev.severity}`}>{ev.type}</span>
                  </div>
                  <p className="ub-tl-msg">{ev.message}</p>
                </div>
              </div>
            ))}
          </div>
        ) : <EmptyState icon="📋" text="Karar verisi yok" />}
      </div>

      {/* ═══ 6. REJIM BAZLI PERFORMANS ══════════════════════════════ */}
      <div className="ub-section">
        <div className="ub-section-header">
          <h2 className="ub-section-title">Rejim Bazli Performans</h2>
          {brain?.strategy_pool?.current_regime && (
            <span className="ub-section-badge">Aktif: {brain.strategy_pool.current_regime}</span>
          )}
        </div>
        {(brain?.regime_performance || []).length > 0 ? (
          <div className="ub-chart-container">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={brain.regime_performance} layout="vertical" margin={{ top: 5, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2430" horizontal={false} />
                <XAxis type="number" stroke="#6b7685" fontSize={11} tickLine={false} tickFormatter={(v) => fmt(v)} />
                <YAxis type="category" dataKey="label" stroke="#a0aab5" fontSize={12} tickLine={false} width={100} />
                <Tooltip content={<CategoryTip />} />
                <ReferenceLine x={0} stroke="#2a3040" />
                <Bar dataKey="total_pnl" radius={[0, 4, 4, 0]} maxBarSize={24}>
                  {(brain.regime_performance || []).map((e, i) => (
                    <Cell key={i} fill={e.total_pnl >= 0 ? '#22c55e' : '#ef4444'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : <EmptyState icon="🎯" text="Rejim verisi yok" />}
      </div>

      {/* ═══ 7. BEYIN PANELLERI ═════════════════════════════════════ */}
      <div className="ub-panels">

        {/* Hata Atama */}
        <BrainPanel
          title="Hata Atama Raporu"
          icon="🔍"
          placeholder="Kim hata yapti? BABA veya OGUL sorumluluk atamasi."
          data={brain?.error_attributions}
          render={(items) => items.slice(0, 10).map((ea, i) => (
            <div key={i} className="ub-bp-row">
              <span className={`ub-bp-badge ub-bp--${ea.responsible.toLowerCase()}`}>{ea.responsible}</span>
              <span className="ub-bp-type">{ea.error_type}</span>
              <span className="ub-bp-desc">{ea.description}</span>
            </div>
          ))}
        />

        {/* Ertesi Gun Analizi */}
        <BrainPanel
          title="Ertesi Gun Analizi"
          icon="📊"
          placeholder="Kapanan islemler icin ertesi gun otomatik analiz. Her sabah 09:30'da puanlanir."
          data={brain?.next_day_analyses}
          render={(items) => items.slice(0, 10).map((nda, i) => (
            <div key={i} className="ub-bp-row ub-nda-row">
              <span className="ub-bp-symbol">{nda.symbol}</span>
              <span className={`ub-bp-pnl ${nda.actual_pnl >= 0 ? 'profit' : 'loss'}`}>{fmt(nda.actual_pnl)}</span>
              <div className="ub-nda-scores">
                <span>S:{Math.round(nda.signal_score)}</span>
                <span>Y:{Math.round(nda.management_score)}</span>
                <span>K:{Math.round(nda.profit_score)}</span>
                <span>R:{Math.round(nda.risk_score)}</span>
                <span className="ub-nda-total">{Math.round(nda.total_score)}/100</span>
              </div>
            </div>
          ))}
        />

        {/* Regulasyon Onerileri */}
        <BrainPanel
          title="Regulasyon Onerileri"
          icon="⚙️"
          placeholder="BABA/OGUL parametre duzeltme onerileri. Her aksam 18:00'da uretilir."
          data={brain?.regulation_suggestions}
          render={(items) => items.slice(0, 10).map((rs, i) => (
            <div key={i} className="ub-bp-row">
              <span className={`ub-bp-badge ub-bp--${rs.priority.toLowerCase()}`}>{rs.priority}</span>
              <span className="ub-bp-type">{rs.parameter}</span>
              <span className="ub-bp-dim">{rs.current_value} &rarr; {rs.suggested_value}</span>
              <span className="ub-bp-desc">{rs.reason}</span>
            </div>
          ))}
        />
      </div>

    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
//  ALT BİLEŞENLER
// ═══════════════════════════════════════════════════════════════════

function MiniBarChart({ title, data }) {
  if (!data || data.length === 0) {
    return (
      <div className="ub-mini-chart">
        <h3 className="ub-mc-title">{title}</h3>
        <EmptyState icon="📉" text="Veri yok" small />
      </div>
    );
  }
  return (
    <div className="ub-mini-chart">
      <h3 className="ub-mc-title">{title}</h3>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={data} layout="vertical" margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2430" horizontal={false} />
          <XAxis type="number" stroke="#6b7685" fontSize={10} tickLine={false} tickFormatter={(v) => fmt(v)} />
          <YAxis type="category" dataKey="label" stroke="#a0aab5" fontSize={11} tickLine={false} width={80} />
          <Tooltip content={<CategoryTip />} />
          <ReferenceLine x={0} stroke="#2a3040" />
          <Bar dataKey="total_pnl" radius={[0, 3, 3, 0]} maxBarSize={18}>
            {data.map((e, i) => (
              <Cell key={i} fill={e.total_pnl >= 0 ? '#22c55e' : '#ef4444'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function BrainPanel({ title, icon, placeholder, data, render }) {
  const hasData = data && data.length > 0;
  return (
    <div className="ub-brain-panel">
      <div className="ub-bp-header">
        <span className="ub-bp-icon">{icon}</span>
        <h3 className="ub-bp-title">{title}</h3>
      </div>
      {hasData ? (
        <div className="ub-bp-list">{render(data)}</div>
      ) : (
        <div className="ub-bp-empty">
          <p>{placeholder}</p>
          <span className="ub-bp-waiting">Veri bekleniyor</span>
        </div>
      )}
    </div>
  );
}

function EmptyState({ icon, text, small }) {
  return (
    <div className={`ub-empty ${small ? 'ub-empty--sm' : ''}`}>
      <span className="ub-empty-icon">{icon}</span>
      <span className="ub-empty-text">{text}</span>
    </div>
  );
}
