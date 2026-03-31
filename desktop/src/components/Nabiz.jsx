/**
 * ÜSTAT v5.9 — NABIZ Sistem Monitörü.
 *
 * Veritabanı, log, disk ve retention durumunu tek sayfada gösterir.
 * Sadece OKUMA yapar — hiçbir sistemi değiştirmez.
 *
 * Veri: GET /api/nabiz (10 saniyede bir polling)
 */

import React, { useState, useEffect, useCallback, memo } from 'react';
import { getNabiz } from '../services/api';

// ── Sabitler ──────────────────────────────────────────────────────

const POLL_MS = 10000;

const COLORS = {
  green:   '#3fb950',
  yellow:  '#d29922',
  red:     '#f85149',
  blue:    '#58a6ff',
  cyan:    '#00d4aa',
  purple:  '#a371f7',
  dim:     '#8b949e',
  border:  '#30363d',
  card:    '#161b22',
  cardAlt: '#0d1117',
};

// Tablo boyutu eşikleri (satır sayısı)
const TABLE_THRESHOLDS = {
  bars:                 { warn: 50000, danger: 150000 },
  trades:               { warn: 5000,  danger: 20000  },
  risk_snapshots:       { warn: 20000, danger: 100000 },
  events:               { warn: 10000, danger: 50000  },
  top5_history:         { warn: 5000,  danger: 20000  },
  notifications:        { warn: 2000,  danger: 10000  },
  daily_risk_summary:   { warn: 500,   danger: 2000   },
  weekly_top5_summary:  { warn: 500,   danger: 2000   },
  config_history:       { warn: 500,   danger: 2000   },
  manual_interventions: { warn: 200,   danger: 1000   },
  hybrid_positions:     { warn: 500,   danger: 2000   },
  hybrid_events:        { warn: 2000,  danger: 10000  },
  strategies:           { warn: 100,   danger: 500    },
  liquidity_classes:    { warn: 1000,  danger: 5000   },
  app_state:            { warn: 50,    danger: 200    },
};

// ── Yardımcı fonksiyonlar ────────────────────────────────────────

function getRowColor(table, count) {
  const t = TABLE_THRESHOLDS[table];
  if (!t) return COLORS.green;
  if (count >= t.danger) return COLORS.red;
  if (count >= t.warn) return COLORS.yellow;
  return COLORS.green;
}

function formatBytes(mb) {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  if (mb >= 1) return `${mb.toFixed(1)} MB`;
  return `${(mb * 1024).toFixed(0)} KB`;
}

function formatNumber(n) {
  if (n === undefined || n === null || n < 0) return '—';
  return n.toLocaleString('tr-TR');
}


// ═══════════════════════════════════════════════════════════════════
//  ANA BİLEŞEN
// ═══════════════════════════════════════════════════════════════════

export default function Nabiz() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const result = await getNabiz();
      setData(result);
      setLastUpdate(new Date());
      setError(null);
    } catch (err) {
      setError(err?.message || 'Bağlantı hatası');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, POLL_MS);
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading && !data) {
    return (
      <div style={styles.container}>
        <h2 style={styles.title}>NABIZ</h2>
        <div style={styles.loading}>Yükleniyor...</div>
      </div>
    );
  }

  const db = data?.database || {};
  const logs = data?.logs || {};
  const disk = data?.disk || {};
  const retention = data?.retention || {};
  const conflict = data?.cleanup_conflict || {};

  return (
    <div style={styles.container}>
      {/* ── Başlık ──────────────────────────────────────────────── */}
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>NABIZ</h2>
          <span style={styles.subtitle}>Sistem Monitörü</span>
        </div>
        <div style={styles.headerRight}>
          {error && <span style={styles.errorBadge}>Hata: {error}</span>}
          <span style={styles.updateTime}>
            Son: {lastUpdate ? lastUpdate.toLocaleTimeString('tr-TR') : '—'}
          </span>
          <button style={styles.refreshBtn} onClick={fetchData} title="Yenile">
            &#8635;
          </button>
        </div>
      </div>

      {/* ── Üst Kartlar ─────────────────────────────────────────── */}
      <div style={styles.cardRow}>
        <SummaryCard
          label="VERİTABANI"
          value={formatBytes(db.file_size_mb || 0)}
          sub={`WAL: ${formatBytes(db.wal_size_mb || 0)} | ${formatNumber(db.total_rows)} satır`}
          color={COLORS.blue}
          status={db.file_size_mb > 500 ? 'warn' : db.file_size_mb > 1000 ? 'err' : 'ok'}
        />
        <SummaryCard
          label="LOG DOSYALARI"
          value={formatBytes(logs.total_size_mb || 0)}
          sub={`${(logs.files || []).length} dosya`}
          color={COLORS.purple}
          status={logs.total_size_mb > 500 ? 'warn' : logs.total_size_mb > 2000 ? 'err' : 'ok'}
        />
        <SummaryCard
          label="DİSK ALANI"
          value={`${disk.free_gb || 0} GB`}
          sub={`%${disk.usage_pct || 0} kullanılıyor | ${disk.total_gb || 0} GB toplam`}
          color={disk.usage_pct > 90 ? COLORS.red : disk.usage_pct > 80 ? COLORS.yellow : COLORS.cyan}
          status={disk.usage_pct > 90 ? 'err' : disk.usage_pct > 80 ? 'warn' : 'ok'}
        />
        <SummaryCard
          label="RETENTION"
          value={retention.enabled ? 'AKTİF' : 'KAPALI'}
          sub={retention.last_retention_date ? `Son: ${retention.last_retention_date}` : 'Henüz çalışmadı'}
          color={retention.enabled ? COLORS.green : COLORS.red}
          status={retention.enabled ? 'ok' : 'err'}
        />
      </div>

      {/* ── Çakışma Uyarısı ─────────────────────────────────────── */}
      {conflict.has_conflict && (
        <ConflictWarning conflict={conflict} />
      )}

      {/* ── İki Kolon Layout ────────────────────────────────────── */}
      <div style={styles.twoCol}>
        {/* Sol: Veritabanı Tabloları */}
        <div style={styles.col}>
          <TableSizesPanel tables={db.table_sizes || {}} />
        </div>

        {/* Sağ: Log + Retention */}
        <div style={styles.col}>
          <LogFilesPanel logs={logs} />
          <RetentionConfigPanel retention={retention} />
        </div>
      </div>

      {/* ── Eksik Retention Tablosu ─────────────────────────────── */}
      <MissingRetentionPanel items={conflict.missing_retention || []} />
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
//  ALT BİLEŞENLER
// ═══════════════════════════════════════════════════════════════════

const SummaryCard = memo(function SummaryCard({ label, value, sub, color, status }) {
  const statusColors = { ok: COLORS.green, warn: COLORS.yellow, err: COLORS.red };
  return (
    <div style={{
      ...styles.summaryCard,
      borderTop: `3px solid ${color}`,
    }}>
      <div style={styles.cardDot}>
        <span style={{
          display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
          background: statusColors[status] || COLORS.green,
          boxShadow: status !== 'ok' ? `0 0 6px ${statusColors[status]}` : 'none',
        }} />
      </div>
      <div style={{ fontSize: 9, letterSpacing: 2, color: COLORS.dim, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 11, color: COLORS.dim, marginTop: 4 }}>{sub}</div>
    </div>
  );
});


function ConflictWarning({ conflict }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div style={styles.conflictBox}>
      <div style={styles.conflictHeader} onClick={() => setExpanded(!expanded)}>
        <span style={{ fontSize: 16 }}>&#9888;</span>
        <span style={{ fontWeight: 600 }}>Çift Temizlik Çakışması Tespit Edildi</span>
        <span style={{ fontSize: 11, color: COLORS.dim, marginLeft: 'auto' }}>
          {expanded ? '▲' : '▼'}
        </span>
      </div>
      {expanded && (
        <div style={styles.conflictBody}>
          <p style={{ fontSize: 12, color: COLORS.dim, marginBottom: 12 }}>
            {conflict.description}
          </p>
          <table style={styles.miniTable}>
            <thead>
              <tr>
                <th style={styles.miniTh}>Tablo</th>
                <th style={styles.miniTh}>Cleanup (FAZ 2.8)</th>
                <th style={styles.miniTh}>Retention (FAZ-A)</th>
                <th style={styles.miniTh}>Risk</th>
              </tr>
            </thead>
            <tbody>
              {(conflict.affected_tables || []).map((t, i) => (
                <tr key={i}>
                  <td style={styles.miniTd}>{t.table}</td>
                  <td style={{ ...styles.miniTd, color: COLORS.yellow }}>{t.cleanup_days} gün</td>
                  <td style={{ ...styles.miniTd, color: COLORS.green }}>{t.retention_days} gün</td>
                  <td style={{ ...styles.miniTd, color: COLORS.red, fontSize: 11 }}>{t.risk}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


function TableSizesPanel({ tables }) {
  const sorted = Object.entries(tables).sort((a, b) => b[1] - a[1]);
  return (
    <div style={styles.panel}>
      <div style={styles.panelHeader}>
        <h3 style={styles.panelTitle}>Veritabanı Tabloları</h3>
        <span style={{ fontSize: 11, color: COLORS.dim }}>{sorted.length} tablo</span>
      </div>
      <div style={styles.tableWrap}>
        <table style={styles.dataTable}>
          <thead>
            <tr>
              <th style={styles.th}>Tablo</th>
              <th style={{ ...styles.th, textAlign: 'right' }}>Satır</th>
              <th style={{ ...styles.th, width: 60 }}>Durum</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(([name, count]) => {
              const color = getRowColor(name, count);
              return (
                <tr key={name} style={styles.tr}>
                  <td style={styles.td}>
                    <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{name}</span>
                  </td>
                  <td style={{ ...styles.td, textAlign: 'right', fontWeight: 600, color }}>
                    {formatNumber(count)}
                  </td>
                  <td style={{ ...styles.td, textAlign: 'center' }}>
                    <span style={{
                      display: 'inline-block', width: 8, height: 8,
                      borderRadius: '50%', background: color,
                    }} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}


function LogFilesPanel({ logs }) {
  const files = logs.files || [];
  return (
    <div style={styles.panel}>
      <div style={styles.panelHeader}>
        <h3 style={styles.panelTitle}>Log Dosyaları</h3>
        <span style={{ fontSize: 11, color: COLORS.dim }}>
          Toplam: {formatBytes(logs.total_size_mb || 0)}
        </span>
      </div>
      <div style={{ ...styles.tableWrap, maxHeight: 220 }}>
        <table style={styles.dataTable}>
          <thead>
            <tr>
              <th style={styles.th}>Dosya</th>
              <th style={{ ...styles.th, textAlign: 'right' }}>Boyut</th>
              <th style={styles.th}>Güncelleme</th>
            </tr>
          </thead>
          <tbody>
            {files.length === 0 ? (
              <tr><td colSpan={3} style={{ ...styles.td, textAlign: 'center', color: COLORS.dim }}>Log dosyası bulunamadı</td></tr>
            ) : (
              files.slice(0, 15).map((f) => (
                <tr key={f.name} style={styles.tr}>
                  <td style={styles.td}>
                    <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{f.name}</span>
                  </td>
                  <td style={{ ...styles.td, textAlign: 'right', fontSize: 12 }}>
                    {formatBytes(f.size_mb)}
                  </td>
                  <td style={{ ...styles.td, fontSize: 11, color: COLORS.dim }}>
                    {f.modified ? new Date(f.modified).toLocaleDateString('tr-TR') : '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}


function RetentionConfigPanel({ retention }) {
  const cfg = retention.config || {};
  const items = [
    { label: 'Risk Snapshots', value: cfg.risk_snapshots_days, unit: 'gün' },
    { label: 'Top5 History', value: cfg.top5_history_days, unit: 'gün' },
    { label: 'Events (INFO)', value: cfg.events_info_days, unit: 'gün' },
    { label: 'Events (WARNING)', value: cfg.events_warning_days, unit: 'gün' },
    { label: 'Events (ERROR)', value: cfg.events_error_days, unit: 'gün' },
    { label: 'Config History', value: cfg.config_history_days, unit: 'gün' },
    { label: 'Liquidity', value: cfg.liquidity_days, unit: 'gün' },
    { label: 'Hybrid Closed', value: cfg.hybrid_closed_days, unit: 'gün' },
    { label: 'Trade Archive', value: cfg.trade_archive_days, unit: 'gün' },
  ];

  return (
    <div style={styles.panel}>
      <div style={styles.panelHeader}>
        <h3 style={styles.panelTitle}>Retention Ayarları</h3>
        <span style={{
          fontSize: 11, padding: '2px 8px', borderRadius: 4,
          background: retention.enabled ? 'rgba(63,185,80,0.15)' : 'rgba(248,81,73,0.15)',
          color: retention.enabled ? COLORS.green : COLORS.red,
        }}>
          {retention.enabled ? 'Aktif' : 'Kapalı'}
        </span>
      </div>
      <div style={styles.retentionGrid}>
        {items.map((item) => (
          <div key={item.label} style={styles.retentionItem}>
            <span style={{ fontSize: 11, color: COLORS.dim }}>{item.label}</span>
            <span style={{ fontSize: 14, fontWeight: 600, color: COLORS.blue }}>
              {item.value ?? '—'} {item.unit}
            </span>
          </div>
        ))}
      </div>
      <div style={{ padding: '8px 14px', fontSize: 11, color: COLORS.dim, borderTop: `1px solid ${COLORS.border}` }}>
        Son Retention: {retention.last_retention_date || 'Henüz çalışmadı'} &nbsp;|&nbsp;
        Son Cleanup: {retention.last_cleanup_date || 'Henüz çalışmadı'}
      </div>
    </div>
  );
}


function MissingRetentionPanel({ items }) {
  if (!items || items.length === 0) return null;

  return (
    <div style={styles.missingPanel}>
      <div style={styles.panelHeader}>
        <h3 style={{ ...styles.panelTitle, color: COLORS.yellow }}>
          &#9888; Retention Eksik Tablolar
        </h3>
        <span style={{ fontSize: 11, color: COLORS.dim }}>{items.length} tablo</span>
      </div>
      <div style={styles.missingGrid}>
        {items.map((item, i) => (
          <div key={i} style={styles.missingItem}>
            <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600 }}>
              {item.table}
            </div>
            <div style={{ fontSize: 11, color: COLORS.red, marginTop: 4 }}>
              {item.status}
            </div>
            <div style={{ fontSize: 10, color: COLORS.dim, marginTop: 2 }}>
              {item.daily_growth}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
//  STİLLER (inline — Monitor.jsx ile tutarlı)
// ═══════════════════════════════════════════════════════════════════

const styles = {
  container: {
    padding: 0,
    maxWidth: '100%',
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    marginBottom: 20, paddingBottom: 12, borderBottom: `1px solid ${COLORS.border}`,
  },
  title: {
    fontSize: 20, fontWeight: 700, color: '#e6edf3', margin: 0,
    letterSpacing: 2,
  },
  subtitle: {
    fontSize: 11, color: COLORS.dim, marginLeft: 0, display: 'block', marginTop: 2,
  },
  headerRight: {
    display: 'flex', alignItems: 'center', gap: 10,
  },
  updateTime: {
    fontSize: 11, color: COLORS.dim,
  },
  refreshBtn: {
    background: 'none', border: `1px solid ${COLORS.border}`, borderRadius: 6,
    color: COLORS.blue, fontSize: 16, padding: '4px 10px', cursor: 'pointer',
  },
  errorBadge: {
    fontSize: 11, padding: '2px 8px', borderRadius: 4,
    background: 'rgba(248,81,73,0.15)', color: COLORS.red,
  },
  loading: {
    textAlign: 'center', color: COLORS.dim, padding: 40, fontSize: 14,
  },

  // Üst kartlar
  cardRow: {
    display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 18,
  },
  summaryCard: {
    background: COLORS.card, borderRadius: 10, padding: '16px 18px',
    border: `1px solid ${COLORS.border}`, position: 'relative',
  },
  cardDot: {
    position: 'absolute', top: 12, right: 14,
  },

  // Çakışma uyarısı
  conflictBox: {
    background: 'rgba(210,153,34,0.06)', border: `1px solid rgba(210,153,34,0.3)`,
    borderRadius: 10, marginBottom: 18, overflow: 'hidden',
  },
  conflictHeader: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px',
    color: COLORS.yellow, cursor: 'pointer', fontSize: 13,
  },
  conflictBody: {
    padding: '0 16px 14px',
  },

  // İki kolon
  twoCol: {
    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginBottom: 18,
  },
  col: {
    display: 'flex', flexDirection: 'column', gap: 18,
  },

  // Paneller
  panel: {
    background: COLORS.card, border: `1px solid ${COLORS.border}`,
    borderRadius: 10, overflow: 'hidden',
  },
  panelHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '12px 16px', borderBottom: `1px solid ${COLORS.border}`,
  },
  panelTitle: {
    fontSize: 13, fontWeight: 600, color: '#e6edf3', margin: 0,
  },

  // Tablolar
  tableWrap: {
    maxHeight: 400, overflowY: 'auto',
  },
  dataTable: {
    width: '100%', borderCollapse: 'collapse', fontSize: 12,
  },
  th: {
    textAlign: 'left', padding: '8px 14px', fontSize: 10, letterSpacing: 1.5,
    color: COLORS.dim, borderBottom: `1px solid ${COLORS.border}`,
    position: 'sticky', top: 0, background: COLORS.card, zIndex: 1,
  },
  tr: {
    borderBottom: `1px solid rgba(48,54,61,0.4)`,
  },
  td: {
    padding: '7px 14px', fontSize: 12, color: '#e6edf3',
  },

  // Mini tablo (çakışma)
  miniTable: {
    width: '100%', borderCollapse: 'collapse', fontSize: 12,
  },
  miniTh: {
    textAlign: 'left', padding: '6px 10px', fontSize: 10, letterSpacing: 1,
    color: COLORS.dim, borderBottom: `1px solid rgba(48,54,61,0.5)`,
  },
  miniTd: {
    padding: '6px 10px', fontSize: 12, color: '#e6edf3',
  },

  // Retention grid
  retentionGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 0,
  },
  retentionItem: {
    padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 3,
    borderBottom: `1px solid rgba(48,54,61,0.3)`,
    borderRight: `1px solid rgba(48,54,61,0.3)`,
  },

  // Eksik retention
  missingPanel: {
    background: 'rgba(210,153,34,0.04)', border: `1px solid rgba(210,153,34,0.2)`,
    borderRadius: 10, overflow: 'hidden',
  },
  missingGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 0,
  },
  missingItem: {
    padding: '12px 16px', borderBottom: `1px solid rgba(48,54,61,0.3)`,
    borderRight: `1px solid rgba(48,54,61,0.3)`,
  },
};
