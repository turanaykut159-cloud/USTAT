/**
 * ÜSTAT v5.5 — Hata Takip Paneli (Error Tracker Dashboard).
 *
 * Özellikler:
 *   - Özet kartları (bugünkü hatalar, uyarılar, açık gruplar)
 *   - Kategori bazlı dağılım çubuğu
 *   - Saatlik/günlük trend grafiği (recharts)
 *   - Hata grupları tablosu (filtrelenebilir, çözümlenebilir)
 *   - Toplu çözümleme
 *
 * API endpoint'leri:
 *   GET  /api/errors/summary
 *   GET  /api/errors/groups
 *   GET  /api/errors/trends
 *   POST /api/errors/resolve
 *   POST /api/errors/resolve-all
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  getErrorSummary, getErrorGroups, getErrorTrends,
  resolveError, resolveAllErrors,
} from '../services/api';

// ── Sabitler ──
const POLL_INTERVAL = 15_000; // 15sn

const CATEGORY_COLORS = {
  bağlantı: '#3b82f6',
  emir: '#f59e0b',
  risk: '#ef4444',
  sinyal: '#8b5cf6',
  netting: '#ec4899',
  veri: '#06b6d4',
  sistem: '#6b7280',
  diğer: '#9ca3af',
};

const SEVERITY_COLORS = {
  CRITICAL: '#ef4444',
  ERROR: '#f97316',
  WARNING: '#eab308',
  INFO: '#3b82f6',
};

const SEVERITY_LABELS = {
  CRITICAL: 'KRİTİK',
  ERROR: 'HATA',
  WARNING: 'UYARI',
};

// ── Yardımcılar ──

function timeAgo(isoStr) {
  if (!isoStr) return '—';
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'az önce';
  if (mins < 60) return `${mins}dk önce`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}sa önce`;
  const days = Math.floor(hours / 24);
  return `${days}g önce`;
}

function shortTime(isoStr) {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('tr-TR', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
  } catch { return isoStr; }
}

// ═══════════════════════════════════════════════════════════════════
//  ANA BİLEŞEN
// ═══════════════════════════════════════════════════════════════════

export default function ErrorTracker() {
  // ── State ──
  const [summary, setSummary] = useState(null);
  const [groups, setGroups] = useState([]);
  const [trends, setTrends] = useState([]);
  const [trendPeriod, setTrendPeriod] = useState('hourly');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterSeverity, setFilterSeverity] = useState('');
  const [filterResolved, setFilterResolved] = useState(false);
  const [loading, setLoading] = useState(true);

  // ── Veri çekme ──
  const fetchAll = useCallback(async () => {
    try {
      const [sum, grp, trd] = await Promise.all([
        getErrorSummary(),
        getErrorGroups({
          category: filterCategory || undefined,
          severity: filterSeverity || undefined,
          resolved: filterResolved || undefined,
        }),
        getErrorTrends({ period: trendPeriod }),
      ]);
      setSummary(sum);
      setGroups(grp?.groups || []);
      setTrends(trd?.data || []);
    } catch (err) {
      console.error('[ErrorTracker] fetch:', err?.message);
    } finally {
      setLoading(false);
    }
  }, [filterCategory, filterSeverity, filterResolved, trendPeriod]);

  useEffect(() => {
    fetchAll();
    const timer = setInterval(fetchAll, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [fetchAll]);

  // ── Çözümleme ──
  const handleResolve = useCallback(async (errorType, messagePrefix) => {
    await resolveError(errorType, messagePrefix);
    fetchAll();
  }, [fetchAll]);

  const handleResolveAll = useCallback(async () => {
    await resolveAllErrors();
    fetchAll();
  }, [fetchAll]);

  // ── Yükleniyor ──
  if (loading) {
    return (
      <div className="error-tracker" style={{ padding: 32, color: '#9ca3af' }}>
        Hata verileri yükleniyor...
      </div>
    );
  }

  const s = summary || {};
  const maxTrendCount = Math.max(1, ...trends.map(t => t.count || t.errors || 0));

  return (
    <div className="error-tracker" style={{ padding: '20px 24px', overflow: 'auto' }}>

      {/* ── BAŞLIK ──────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 18, color: '#e5e7eb' }}>
          🔍 Hata Takip Paneli
        </h2>
        <button
          onClick={handleResolveAll}
          style={{
            background: '#065f46', color: '#34d399', border: '1px solid #059669',
            borderRadius: 6, padding: '6px 14px', fontSize: 12, cursor: 'pointer',
          }}
          title="Tüm açık hataları çözümlendi olarak işaretle"
        >
          Tümünü Çözümle ({s.open_groups || 0})
        </button>
      </div>

      {/* ── ÖZET KARTLARI ──────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
        <StatCard
          label="Bugün Hata"
          value={s.today_errors || 0}
          color="#ef4444"
          sub={`${s.total_errors || 0} toplam`}
        />
        <StatCard
          label="Bugün Uyarı"
          value={s.today_warnings || 0}
          color="#eab308"
          sub={`${s.total_warnings || 0} toplam`}
        />
        <StatCard
          label="Açık Gruplar"
          value={s.open_groups || 0}
          color="#f97316"
          sub={`${s.resolved_groups || 0} çözümlendi`}
        />
        <StatCard
          label="Bu Saat"
          value={s.this_hour_count || 0}
          color="#3b82f6"
          sub={s.total_critical > 0 ? `${s.total_critical} kritik` : 'stabil'}
        />
      </div>

      {/* ── KATEGORİ DAĞILIMI ──────────────────────────────────── */}
      {s.by_category && Object.keys(s.by_category).length > 0 && (
        <div style={{
          background: '#1e293b', borderRadius: 8, padding: '14px 16px',
          marginBottom: 20, border: '1px solid #334155',
        }}>
          <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 10, fontWeight: 600 }}>
            KATEGORİ DAĞILIMI
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {Object.entries(s.by_category)
              .sort(([, a], [, b]) => b - a)
              .map(([cat, count]) => (
                <CategoryBadge key={cat} category={cat} count={count} />
              ))}
          </div>
        </div>
      )}

      {/* ── TREND GRAFİĞİ ─────────────────────────────────────── */}
      <div style={{
        background: '#1e293b', borderRadius: 8, padding: '14px 16px',
        marginBottom: 20, border: '1px solid #334155',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 600 }}>
            HATA TRENDİ
          </span>
          <div style={{ display: 'flex', gap: 4 }}>
            <TrendToggle active={trendPeriod === 'hourly'} onClick={() => setTrendPeriod('hourly')} label="Saatlik" />
            <TrendToggle active={trendPeriod === 'daily'} onClick={() => setTrendPeriod('daily')} label="Günlük" />
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 60 }}>
          {trends.map((t, i) => {
            const val = t.count ?? t.errors ?? 0;
            const pct = (val / maxTrendCount) * 100;
            const color = val > 5 ? '#ef4444' : val > 2 ? '#f59e0b' : '#22c55e';
            return (
              <div
                key={i}
                title={`${t.hour || t.date}: ${val} hata`}
                style={{
                  flex: 1, background: color, borderRadius: '2px 2px 0 0',
                  height: `${Math.max(pct, 2)}%`, minHeight: 2,
                  opacity: 0.8, transition: 'height 0.3s',
                }}
              />
            );
          })}
        </div>
        {trends.length > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
            <span style={{ fontSize: 10, color: '#64748b' }}>
              {trends[0]?.hour || trends[0]?.date || ''}
            </span>
            <span style={{ fontSize: 10, color: '#64748b' }}>
              {trends[trends.length - 1]?.hour || trends[trends.length - 1]?.date || ''}
            </span>
          </div>
        )}
      </div>

      {/* ── FİLTRELER ──────────────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <FilterSelect
          value={filterCategory}
          onChange={setFilterCategory}
          placeholder="Tüm Kategoriler"
          options={[
            { value: 'bağlantı', label: 'Bağlantı' },
            { value: 'emir', label: 'Emir' },
            { value: 'risk', label: 'Risk' },
            { value: 'sinyal', label: 'Sinyal' },
            { value: 'netting', label: 'Netting' },
            { value: 'veri', label: 'Veri' },
            { value: 'sistem', label: 'Sistem' },
          ]}
        />
        <FilterSelect
          value={filterSeverity}
          onChange={setFilterSeverity}
          placeholder="Tüm Seviyeler"
          options={[
            { value: 'CRITICAL', label: 'Kritik' },
            { value: 'ERROR', label: 'Hata' },
            { value: 'WARNING', label: 'Uyarı' },
          ]}
        />
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#94a3b8', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={filterResolved}
            onChange={e => setFilterResolved(e.target.checked)}
            style={{ accentColor: '#22c55e' }}
          />
          Çözümlenenleri göster
        </label>
      </div>

      {/* ── HATA GRUPLARI TABLOSU ──────────────────────────────── */}
      <div style={{
        background: '#1e293b', borderRadius: 8, border: '1px solid #334155',
        overflow: 'hidden',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: '#0f172a' }}>
              <th style={thStyle}>SEVİYE</th>
              <th style={thStyle}>KATEGORİ</th>
              <th style={thStyle}>TİP</th>
              <th style={{ ...thStyle, textAlign: 'left', minWidth: 200 }}>MESAJ</th>
              <th style={thStyle}>TEKRAR</th>
              <th style={thStyle}>SON</th>
              <th style={thStyle}>İŞLEM</th>
            </tr>
          </thead>
          <tbody>
            {groups.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ padding: 24, textAlign: 'center', color: '#22c55e' }}>
                  Açık hata yok — sistem stabil
                </td>
              </tr>
            ) : (
              groups.map((g, i) => (
                <tr key={i} style={{
                  background: g.resolved ? '#0f172a' : 'transparent',
                  opacity: g.resolved ? 0.5 : 1,
                  borderBottom: '1px solid #1e293b',
                }}>
                  <td style={tdStyle}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 4,
                      fontSize: 10, fontWeight: 700, letterSpacing: '0.5px',
                      background: SEVERITY_COLORS[g.severity] + '22',
                      color: SEVERITY_COLORS[g.severity],
                      border: `1px solid ${SEVERITY_COLORS[g.severity]}44`,
                    }}>
                      {SEVERITY_LABELS[g.severity] || g.severity}
                    </span>
                  </td>
                  <td style={tdStyle}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 4,
                      fontSize: 10, background: CATEGORY_COLORS[g.category] + '22',
                      color: CATEGORY_COLORS[g.category],
                    }}>
                      {g.category}
                    </span>
                  </td>
                  <td style={{ ...tdStyle, color: '#94a3b8', fontFamily: 'monospace', fontSize: 11 }}>
                    {g.error_type}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'left', color: '#e5e7eb', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {g.message}
                  </td>
                  <td style={{ ...tdStyle, fontWeight: 700, color: g.count > 5 ? '#ef4444' : g.count > 2 ? '#f59e0b' : '#94a3b8' }}>
                    {g.count}×
                  </td>
                  <td style={{ ...tdStyle, color: '#64748b', fontSize: 11 }}>
                    {timeAgo(g.last_seen)}
                  </td>
                  <td style={tdStyle}>
                    {!g.resolved ? (
                      <button
                        onClick={() => handleResolve(g.error_type, g.message?.slice(0, 80))}
                        style={{
                          background: 'transparent', border: '1px solid #334155',
                          color: '#22c55e', borderRadius: 4, padding: '3px 10px',
                          fontSize: 11, cursor: 'pointer',
                        }}
                      >
                        Çözümle
                      </button>
                    ) : (
                      <span style={{ color: '#22c55e', fontSize: 11 }}>✓</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* ── EN SON HATA ────────────────────────────────────────── */}
      {s.latest_error && (
        <div style={{
          background: '#1e293b', borderRadius: 8, padding: '12px 16px',
          marginTop: 16, border: '1px solid #7f1d1d',
        }}>
          <div style={{ fontSize: 11, color: '#f87171', fontWeight: 600, marginBottom: 6 }}>
            SON HATA — {s.latest_error.error_type} ({timeAgo(s.latest_error.last_seen)})
          </div>
          <div style={{ fontSize: 12, color: '#e5e7eb' }}>
            {s.latest_error.message}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//  ALT BİLEŞENLER
// ═══════════════════════════════════════════════════════════════════

function StatCard({ label, value, color, sub }) {
  return (
    <div style={{
      background: '#1e293b', borderRadius: 8, padding: '14px 16px',
      border: '1px solid #334155',
    }}>
      <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color, lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function CategoryBadge({ category, count }) {
  const color = CATEGORY_COLORS[category] || '#9ca3af';
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      background: color + '18', border: `1px solid ${color}44`,
      borderRadius: 6, padding: '4px 10px',
    }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%', background: color,
      }} />
      <span style={{ fontSize: 12, color }}>{category}</span>
      <span style={{ fontSize: 12, fontWeight: 700, color }}>{count}</span>
    </div>
  );
}

function TrendToggle({ active, onClick, label }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? '#334155' : 'transparent',
        color: active ? '#e5e7eb' : '#64748b',
        border: '1px solid #334155', borderRadius: 4,
        padding: '3px 10px', fontSize: 11, cursor: 'pointer',
      }}
    >
      {label}
    </button>
  );
}

function FilterSelect({ value, onChange, placeholder, options }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      style={{
        background: '#0f172a', color: '#e5e7eb', border: '1px solid #334155',
        borderRadius: 6, padding: '5px 10px', fontSize: 12, cursor: 'pointer',
      }}
    >
      <option value="">{placeholder}</option>
      {options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

// ── Tablo stilleri ──
const thStyle = {
  padding: '10px 12px', textAlign: 'center', color: '#64748b',
  fontSize: 10, fontWeight: 600, letterSpacing: '0.5px',
  borderBottom: '1px solid #334155',
};

const tdStyle = {
  padding: '8px 12px', textAlign: 'center',
};
