/**
 * ÜSTAT v5.2 — Sistem Günlüğü sayfası.
 *
 * Tüm sistem olaylarını (BABA kararları, OĞUL emirleri, erken uyarılar,
 * risk limitleri, cooldown, kill-switch vb.) kronolojik sırayla gösterir.
 *
 * Veri: getEvents (GET /api/events) — limit 500, client-side filtreleme.
 * Polling: 10 saniye.
 */

import React, { useState, useCallback, useEffect, useMemo } from 'react';
import { getEvents } from '../services/api';

// ── Yardımcılar ──────────────────────────────────────────────────

function fmtDateTime(ts) {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    const dd = d.getDate().toString().padStart(2, '0');
    const mm = (d.getMonth() + 1).toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const min = d.getMinutes().toString().padStart(2, '0');
    const sec = d.getSeconds().toString().padStart(2, '0');
    return `${dd}.${mm} ${hh}:${min}:${sec}`;
  } catch {
    return String(ts);
  }
}

const SEVERITY_COLORS = {
  CRITICAL: 'sl-sev-critical',
  ERROR:    'sl-sev-error',
  WARNING:  'sl-sev-warning',
  INFO:     'sl-sev-info',
  DEBUG:    'sl-sev-debug',
};

const TYPE_LABELS = {
  ENGINE_START:       'Motor Başladı',
  ENGINE_START_FAIL:  'Motor Başlatma Hatası',
  ENGINE_STOP:        'Motor Durdu',
  EARLY_WARNING:      'Erken Uyarı',
  DRAWDOWN_LIMIT:     'Zarar Limiti',
  RISK_RESET:         'Risk Sıfırlama',
  RISK_ALLOWED:       'Risk İzin',
  RISK_LIMIT:         'Risk Limiti',
  COOLDOWN:           'Bekleme Süresi',
  KILL_SWITCH:        'Kill-Switch',
  FAKE_SIGNAL:        'Sahte Sinyal',
  ORDER_SENT:         'Emir Gönderildi',
  ORDER_CANCELLED:    'Emir İptal',
  ORDER_FILLED:       'Emir Gerçekleşti',
  MARKET_RETRY:       'Piyasa Tekrar Deneme',
  EOD_CLOSE:          'Gün Sonu Kapanış',
  TRADE_CLOSE:        'İşlem Kapandı',
  TRADE_OPENED:       'İşlem Açıldı',
  TRADE_CLOSED:       'İşlem Kapandı',
  TRADE_ERROR:        'İşlem Hatası',
  TRADE:              'İşlem',
  NEWS_FILTER:        'Haber Filtresi',
  DATA_GAP:           'Veri Boşluğu',
  DATA_OUTLIER:       'Veri Sapması',
  SYMBOL_DEACTIVATED: 'Sembol Devre Dışı',
  SYMBOL_REACTIVATED: 'Sembol Aktif',
  REGIME_CHANGE:      'Rejim Değişimi',
  DAILY_REPORT:       'Günlük Rapor',
  MANUAL_TRADE_ERROR: 'Manuel İşlem Hatası',
  MANUAL_ORDER_SENT:  'Manuel Emir',
  MANUAL_TRADE_CLOSE: 'Manuel Kapanış',
  WARNING_INCREASE:   'Uyarı Artışı',
};

const SEVERITY_LABELS = {
  ALL:      'Tümü',
  CRITICAL: 'Kritik',
  ERROR:    'Hata',
  WARNING:  'Uyarı',
  INFO:     'Bilgi',
  DEBUG:    'Debug',
};


// ═══════════════════════════════════════════════════════════════════
//  ANA BİLEŞEN
// ═══════════════════════════════════════════════════════════════════

export default function SystemLog() {
  const [data, setData] = useState(null);
  const [sevFilter, setSevFilter] = useState('ALL');
  const [typeFilter, setTypeFilter] = useState('ALL');

  const fetchData = useCallback(async () => {
    const d = await getEvents({ limit: 500 });
    setData(d);
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 10000);
    return () => clearInterval(iv);
  }, [fetchData]);

  // ── Türetilmiş veriler ──────────────────────────────────────────
  const allEvents = useMemo(() => data?.events || [], [data]);

  const eventTypes = useMemo(
    () => [...new Set(allEvents.map((e) => e.type))].sort(),
    [allEvents],
  );

  const filtered = useMemo(
    () =>
      allEvents.filter((e) => {
        if (sevFilter !== 'ALL' && e.severity !== sevFilter) return false;
        if (typeFilter !== 'ALL' && e.type !== typeFilter) return false;
        return true;
      }),
    [allEvents, sevFilter, typeFilter],
  );

  // ── Yükleniyor ─────────────────────────────────────────────────
  if (!data) {
    return (
      <div className="sl-page">
        <h2 className="sl-title">Sistem Günlüğü</h2>
        <p className="sl-loading">Veriler yükleniyor...</p>
      </div>
    );
  }

  return (
    <div className="sl-page">
      <h2 className="sl-title">Sistem Günlüğü</h2>

      <SeveritySummary events={allEvents} />

      <FilterBar
        sevFilter={sevFilter}
        setSevFilter={setSevFilter}
        typeFilter={typeFilter}
        setTypeFilter={setTypeFilter}
        eventTypes={eventTypes}
      />

      {filtered.length === 0 ? (
        <p className="sl-empty">Olay bulunamadı.</p>
      ) : (
        <EventTable events={filtered} />
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
//  ALT BİLEŞENLER
// ═══════════════════════════════════════════════════════════════════

function SeveritySummary({ events }) {
  const counts = useMemo(() => {
    const c = { CRITICAL: 0, ERROR: 0, WARNING: 0, INFO: 0, DEBUG: 0 };
    for (const e of events) {
      if (c[e.severity] !== undefined) c[e.severity]++;
    }
    return c;
  }, [events]);

  return (
    <div className="sl-summary">
      <div className="sl-summary-item">
        <span className="sl-summary-count">{events.length}</span>
        <span className="sl-summary-label">Toplam</span>
      </div>
      {counts.CRITICAL > 0 && (
        <div className="sl-summary-item sl-summary-critical">
          <span className="sl-summary-count">{counts.CRITICAL}</span>
          <span className="sl-summary-label">Kritik</span>
        </div>
      )}
      <div className="sl-summary-item sl-summary-error">
        <span className="sl-summary-count">{counts.ERROR}</span>
        <span className="sl-summary-label">Hata</span>
      </div>
      <div className="sl-summary-item sl-summary-warning">
        <span className="sl-summary-count">{counts.WARNING}</span>
        <span className="sl-summary-label">Uyarı</span>
      </div>
      <div className="sl-summary-item sl-summary-info">
        <span className="sl-summary-count">{counts.INFO}</span>
        <span className="sl-summary-label">Bilgi</span>
      </div>
    </div>
  );
}

function FilterBar({ sevFilter, setSevFilter, typeFilter, setTypeFilter, eventTypes }) {
  const severities = ['ALL', 'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'];

  return (
    <div className="sl-filters">
      <div className="sl-filter-group">
        {severities.map((s) => (
          <button
            key={s}
            className={`sl-filter-btn ${sevFilter === s ? 'sl-filter-active' : ''}`}
            onClick={() => setSevFilter(s)}
          >
            {SEVERITY_LABELS[s] || s}
          </button>
        ))}
      </div>
      <div className="sl-filter-type">
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="sl-select"
        >
          <option value="ALL">Tüm Tipler</option>
          {eventTypes.map((t) => (
            <option key={t} value={t}>
              {TYPE_LABELS[t] || t}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function EventTable({ events }) {
  const hasAction = useMemo(() => events.some((e) => e.action), [events]);

  return (
    <div className="sl-table-wrap">
      <table className="sl-table">
        <thead>
          <tr>
            <th>Zaman</th>
            <th>Tip</th>
            <th>Önem</th>
            <th>Mesaj</th>
            {hasAction && <th>Aksiyon</th>}
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr
              key={e.id}
              className={e.severity === 'CRITICAL' ? 'sl-row-critical' : ''}
            >
              <td className="sl-mono">{fmtDateTime(e.timestamp)}</td>
              <td className="sl-type">{TYPE_LABELS[e.type] || e.type}</td>
              <td>
                <span
                  className={`sl-sev-badge ${SEVERITY_COLORS[e.severity] || 'sl-sev-info'}`}
                >
                  {SEVERITY_LABELS[e.severity] || e.severity}
                </span>
              </td>
              <td className="sl-event-msg">{e.message}</td>
              {hasAction && <td className="sl-event-action">{e.action || ''}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
