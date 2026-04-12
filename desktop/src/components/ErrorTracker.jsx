/**
 * ÜSTAT v5.7 — Hata Takip Paneli (Error Tracker Dashboard).
 *
 * Özellikler:
 *   - Özet kartları (bugünkü hatalar, uyarılar, açık gruplar)
 *   - Kategori bazlı dağılım çubuğu
 *   - Saatlik/günlük trend grafiği
 *   - Hata grupları tablosu (filtrelenebilir, çözümlenebilir)
 *   - Toplu çözümleme
 *   - EOD geri sayım göstergesi
 *   - Mesaj tooltip (kesilen mesajlar için)
 *
 * v5.5 Güncelleme:
 *   - handleResolve/handleResolveAll'da try/catch eklendi
 *   - Mesaj sütununda hover tooltip eklendi
 *   - EOD kapanış geri sayım göstergesi eklendi
 *   - API hata durumunda sonsuz yükleme düzeltildi
 *   - Trend chart veri alanı tutarlılığı düzeltildi
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
  resolveError, resolveAllErrors, getSession,
} from '../services/api';
// Widget Denetimi H7: Kategori/severity renkleri, etiketleri ve filtre
// seçenekleri frontend canonical modülüne (errorTaxonomy.js) taşındı.
// Eski yerel CATEGORY_COLORS / SEVERITY_COLORS / SEVERITY_LABELS dict'leri
// ve filter option literal'leri bu bileşenden kaldırıldı; backend
// engine/error_tracker.py ERROR_CATEGORIES + SEVERITY_PRIORITY ile sync
// Flow 4z (tests/critical_flows/test_static_contracts.py) ile CI'da garanti.
import {
  CATEGORY_COLORS,
  SEVERITY_COLORS,
  SEVERITY_LABELS,
  CATEGORY_FILTER_OPTIONS,
  SEVERITY_FILTER_OPTIONS,
} from '../utils/errorTaxonomy';

// ── Sabitler ──
const POLL_INTERVAL = 15_000; // 15sn

// ── EOD Sabitleri — Widget Denetimi A17 ──
// Bu değerler FALLBACK; gerçek saatler /api/settings/session üzerinden
// config/default.json::session bloğundan okunur. Backend okunamazsa
// aşağıdaki default'lar devreye girer. BIST VİOP sabitleri: 09:30-18:15,
// EOD zorunlu kapanış 17:45 (Anayasa Kural #5 — engine.trading_close).
const DEFAULT_SESSION_HOURS = {
  market_open: '09:30',
  market_close: '18:15',
  eod_close: '17:45',
};

// "HH:MM" → { hour, min }. Geçersiz değerde null döner.
function parseHHMM(str) {
  if (typeof str !== 'string') return null;
  const m = /^(\d{2}):(\d{2})$/.exec(str);
  if (!m) return null;
  const hour = Number(m[1]);
  const min = Number(m[2]);
  if (Number.isNaN(hour) || Number.isNaN(min)) return null;
  if (hour < 0 || hour > 23 || min < 0 || min > 59) return null;
  return { hour, min };
}

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

function getEodInfo(sessionCfg = DEFAULT_SESSION_HOURS) {
  const now = new Date();
  const day = now.getDay(); // 0=Pazar, 6=Cumartesi
  const nowMins = now.getHours() * 60 + now.getMinutes();

  // Config'den gelen değerleri parse et, hatalıysa default'a düş.
  const openParsed = parseHHMM(sessionCfg.market_open) || parseHHMM(DEFAULT_SESSION_HOURS.market_open);
  const closeParsed = parseHHMM(sessionCfg.market_close) || parseHHMM(DEFAULT_SESSION_HOURS.market_close);
  const eodParsed = parseHHMM(sessionCfg.eod_close) || parseHHMM(DEFAULT_SESSION_HOURS.eod_close);

  const openMins = openParsed.hour * 60 + openParsed.min;
  const closeMins = closeParsed.hour * 60 + closeParsed.min;
  const eodMins = eodParsed.hour * 60 + eodParsed.min;

  // Hafta sonu
  if (day === 0 || day === 6) {
    return { isOpen: false, eodRemaining: null, label: 'PİYASA KAPALI' };
  }

  // Piyasa saatleri dışında
  if (nowMins < openMins || nowMins >= closeMins) {
    return { isOpen: false, eodRemaining: null, label: 'PİYASA KAPALI' };
  }

  // EOD sonrası (17:45 - 18:15 arası)
  if (nowMins >= eodMins) {
    return { isOpen: true, eodRemaining: 0, label: 'EOD KAPANIŞ AKTİF' };
  }

  // Piyasa açık, EOD'ye kalan süre
  const remaining = eodMins - nowMins;
  const hours = Math.floor(remaining / 60);
  const mins = remaining % 60;
  const label = hours > 0 ? `${hours}sa ${mins}dk` : `${mins}dk`;

  return { isOpen: true, eodRemaining: remaining, label };
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
  const [error, setError] = useState(null);
  // A17: session hours backend'den; fetch tamamlanana kadar default.
  const [sessionHours, setSessionHours] = useState(DEFAULT_SESSION_HOURS);
  const [eod, setEod] = useState(() => getEodInfo(DEFAULT_SESSION_HOURS));
  const [resolveMsg, setResolveMsg] = useState(null);
  const [hoveredMsg, setHoveredMsg] = useState(null);

  // ── A17: Session saatlerini mount'ta çek; hata durumunda default kalır ──
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const data = await getSession();
      if (cancelled) return;
      const next = {
        market_open: data?.market_open || DEFAULT_SESSION_HOURS.market_open,
        market_close: data?.market_close || DEFAULT_SESSION_HOURS.market_close,
        eod_close: data?.eod_close || DEFAULT_SESSION_HOURS.eod_close,
      };
      setSessionHours(next);
      setEod(getEodInfo(next));
    })();
    return () => { cancelled = true; };
  }, []);

  // ── EOD geri sayım güncelle (her dakika) ──
  useEffect(() => {
    const timer = setInterval(() => setEod(getEodInfo(sessionHours)), 60_000);
    return () => clearInterval(timer);
  }, [sessionHours]);

  // ── Veri çekme ──
  const fetchAll = useCallback(async () => {
    try {
      setError(null);
      const [sum, grp, trd] = await Promise.all([
        getErrorSummary(),
        getErrorGroups({
          category: filterCategory || undefined,
          severity: filterSeverity || undefined,
          resolved: filterResolved ? undefined : false,
        }),
        getErrorTrends({ period: trendPeriod }),
      ]);
      setSummary(sum);
      setGroups(grp?.groups || []);
      setTrends(trd?.data || []);
    } catch (err) {
      console.error('[ErrorTracker] fetch:', err?.message);
      setError('API bağlantı hatası — veriler güncel olmayabilir');
    } finally {
      setLoading(false);
    }
  }, [filterCategory, filterSeverity, filterResolved, trendPeriod]);

  useEffect(() => {
    fetchAll();
    const timer = setInterval(fetchAll, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [fetchAll]);

  // ── Çözümleme (try/catch ile) ──
  const handleResolve = useCallback(async (errorType, messagePrefix) => {
    try {
      const result = await resolveError(errorType, messagePrefix);
      if (result?.success) {
        setResolveMsg({ type: 'success', text: `${errorType} çözümlendi` });
      } else {
        setResolveMsg({ type: 'error', text: result?.message || 'Çözümleme başarısız' });
      }
      fetchAll();
    } catch (err) {
      setResolveMsg({ type: 'error', text: `Çözümleme hatası: ${err?.message}` });
    }
    setTimeout(() => setResolveMsg(null), 3000);
  }, [fetchAll]);

  const handleResolveAll = useCallback(async () => {
    try {
      const result = await resolveAllErrors();
      if (result?.success) {
        setResolveMsg({ type: 'success', text: `${result.resolved_count} grup çözümlendi` });
      } else {
        setResolveMsg({ type: 'error', text: 'Toplu çözümleme başarısız' });
      }
      fetchAll();
    } catch (err) {
      setResolveMsg({ type: 'error', text: `Toplu çözümleme hatası: ${err?.message}` });
    }
    setTimeout(() => setResolveMsg(null), 3000);
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
  const maxTrendCount = Math.max(1, ...trends.map(t => t.count ?? t.errors ?? 0));

  return (
    <div className="error-tracker" style={{ padding: '20px 24px', overflow: 'auto' }}>

      {/* ── BAŞLIK + EOD GERİ SAYIM ────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 18, color: '#e5e7eb' }}>
          Hata Takip Paneli
        </h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* EOD Geri Sayım */}
          <EodBadge eod={eod} />
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
      </div>

      {/* ── HATA/UYARI BANNER ────────────────────────────────── */}
      {error && (
        <div style={{
          background: '#7f1d1d22', border: '1px solid #7f1d1d', borderRadius: 6,
          padding: '8px 14px', marginBottom: 14, fontSize: 12, color: '#fca5a5',
        }}>
          {error}
        </div>
      )}

      {/* Widget Denetimi A25 (K3): Truncation banner — backend
          /api/errors/summary 7 günlük event sorgusunda 5000 limitine
          değdiğinde bu uyarı görünür. Eski kayıtlar düşmüş demektir,
          özet eksiktir. Operatör retention politikasını gözden geçirmeli. */}
      {s.truncation_warning && (
        <div
          className="error-truncation-banner"
          style={{
            background: '#78350f22', border: '1px solid #d97706', borderRadius: 6,
            padding: '8px 14px', marginBottom: 14, fontSize: 12, color: '#fbbf24',
            display: 'flex', alignItems: 'center', gap: 8,
          }}
          title="Backend events tablosu 7 gün × 5000 limit aşımı tespit etti"
        >
          <span style={{ fontSize: 14 }}>⚠</span>
          <span><b>Eksik özet:</b> {s.truncation_warning}</span>
        </div>
      )}

      {/* ── ÇÖZÜMLEME GERİ BİLDİRİM ─────────────────────────── */}
      {resolveMsg && (
        <div style={{
          background: resolveMsg.type === 'success' ? '#065f4622' : '#7f1d1d22',
          border: `1px solid ${resolveMsg.type === 'success' ? '#059669' : '#7f1d1d'}`,
          borderRadius: 6, padding: '8px 14px', marginBottom: 14, fontSize: 12,
          color: resolveMsg.type === 'success' ? '#34d399' : '#fca5a5',
        }}>
          {resolveMsg.text}
        </div>
      )}

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
            const val = t.count ?? 0;
            const pct = (val / maxTrendCount) * 100;
            const color = val > 5 ? '#ef4444' : val > 2 ? '#f59e0b' : '#22c55e';
            return (
              <div
                key={i}
                title={`${t.hour || t.date || ''}: ${val} hata`}
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
          options={CATEGORY_FILTER_OPTIONS}
        />
        <FilterSelect
          value={filterSeverity}
          onChange={setFilterSeverity}
          placeholder="Tüm Seviyeler"
          options={SEVERITY_FILTER_OPTIONS}
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
                  <td
                    style={{
                      ...tdStyle, textAlign: 'left', color: '#e5e7eb',
                      maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap', cursor: 'pointer', position: 'relative',
                    }}
                    title={g.message}
                    onMouseEnter={() => setHoveredMsg(i)}
                    onMouseLeave={() => setHoveredMsg(null)}
                  >
                    {g.message}
                    {/* Tooltip */}
                    {hoveredMsg === i && g.message && g.message.length > 40 && (
                      <div style={{
                        position: 'absolute', bottom: '100%', left: 0,
                        background: '#0f172a', border: '1px solid #475569',
                        borderRadius: 6, padding: '8px 12px', maxWidth: 450,
                        whiteSpace: 'normal', wordBreak: 'break-word',
                        fontSize: 11, color: '#e5e7eb', zIndex: 100,
                        boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
                      }}>
                        {g.message}
                      </div>
                    )}
                  </td>
                  <td style={{ ...tdStyle, fontWeight: 700, color: g.count > 5 ? '#ef4444' : g.count > 2 ? '#f59e0b' : '#94a3b8' }}>
                    {g.count}x
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

function EodBadge({ eod }) {
  if (!eod.isOpen) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        background: '#33415522', border: '1px solid #334155',
        borderRadius: 6, padding: '4px 12px', fontSize: 11, color: '#64748b',
      }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#64748b' }} />
        {eod.label}
      </div>
    );
  }

  if (eod.eodRemaining === 0) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        background: '#7f1d1d22', border: '1px solid #ef4444',
        borderRadius: 6, padding: '4px 12px', fontSize: 11, color: '#ef4444',
        fontWeight: 700,
      }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#ef4444', animation: 'pulse 1s infinite' }} />
        EOD KAPANIŞ AKTİF
      </div>
    );
  }

  // Renk: 30dk'dan az kaldıysa turuncu, 15dk'dan az kaldıysa kırmızı
  const color = eod.eodRemaining <= 15 ? '#ef4444' : eod.eodRemaining <= 30 ? '#f59e0b' : '#22c55e';

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      background: color + '18', border: `1px solid ${color}44`,
      borderRadius: 6, padding: '4px 12px', fontSize: 11, color,
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: color }} />
      EOD: {eod.label}
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
