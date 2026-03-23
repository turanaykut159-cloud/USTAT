/**
 * ÜSTAT v5.7.1 — Haber Entegrasyon Paneli.
 *
 * Dashboard'a gömülen canlı haber akış paneli.
 * WebSocket'ten "news" mesajlarını alır, REST fallback olarak
 * GET /api/news/active endpoint'ini kullanır.
 *
 * Özellikler:
 *   - Canlı haber akışı (sentiment renk kodlu)
 *   - En kötü / en iyi sentiment göstergesi
 *   - Severity badge (LOW → CRITICAL)
 *   - Kategori etiketleri (JEOPOLİTİK, EKONOMİK, vs.)
 *   - Sembol etiketleri (etkilenen kontratlar)
 *   - Haber yaşı (saniye) göstergesi
 */

import React from 'react';

// ── Yardımcılar ──────────────────────────────────────────────────

/** Sentiment skoruna göre renk sınıfı */
function sentimentColor(score) {
  if (score == null) return '';
  if (score >= 0.5) return 'news-positive';
  if (score >= 0.2) return 'news-mild-positive';
  if (score > -0.2) return 'news-neutral';
  if (score > -0.5) return 'news-mild-negative';
  return 'news-negative';
}

/** Severity → badge sınıfı */
function severityBadge(severity) {
  const map = {
    CRITICAL: { cls: 'badge-critical', label: 'KRİTİK' },
    HIGH: { cls: 'badge-high', label: 'YÜKSEK' },
    MEDIUM: { cls: 'badge-medium', label: 'ORTA' },
    LOW: { cls: 'badge-low', label: 'DÜŞÜK' },
    NONE: { cls: 'badge-none', label: '' },
  };
  return map[severity] || map.NONE;
}

/** Kategori → badge label */
function categoryLabel(cat) {
  const map = {
    JEOPOLITIK: 'Jeopolitik',
    EKONOMIK: 'Ekonomik',
    SEKTOREL: 'Sektörel',
    SIRKET: 'Şirket',
    GENEL: 'Genel',
  };
  return map[cat] || cat;
}

/** Yaş formatlama */
function formatAge(seconds) {
  if (seconds < 60) return `${Math.round(seconds)}sn`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}dk`;
  return `${Math.round(seconds / 3600)}sa`;
}

// ═══════════════════════════════════════════════════════════════════
//  NEWS PANEL
// ═══════════════════════════════════════════════════════════════════

export default function NewsPanel({ newsData }) {
  if (!newsData || !newsData.events || newsData.events.length === 0) {
    return (
      <div className="news-panel news-panel-empty">
        <div className="news-header">
          <span className="news-title">📰 Haber Akışı</span>
          <span className="news-status-dot news-dot-idle" />
        </div>
        <div className="news-empty-msg">Aktif haber yok</div>
      </div>
    );
  }

  const { events, worst_sentiment, worst_severity, best_sentiment, active_count } = newsData;

  return (
    <div className="news-panel">
      {/* Başlık + Özet */}
      <div className="news-header">
        <span className="news-title">📰 Haber Akışı</span>
        <span className="news-count">{active_count || events.length} aktif</span>
        {worst_severity && worst_severity !== 'NONE' && (
          <span className={`news-severity-badge ${severityBadge(worst_severity).cls}`}>
            ⚠ {severityBadge(worst_severity).label}
          </span>
        )}
        <span className="news-status-dot news-dot-active" />
      </div>

      {/* Sentiment Özet Bar */}
      <div className="news-sentiment-bar">
        {best_sentiment != null && (
          <span className={`news-sentiment-chip ${sentimentColor(best_sentiment)}`}>
            ▲ En İyi: {best_sentiment > 0 ? '+' : ''}{best_sentiment?.toFixed(2)}
          </span>
        )}
        {worst_sentiment != null && (
          <span className={`news-sentiment-chip ${sentimentColor(worst_sentiment)}`}>
            ▼ En Kötü: {worst_sentiment > 0 ? '+' : ''}{worst_sentiment?.toFixed(2)}
          </span>
        )}
      </div>

      {/* Haber Listesi */}
      <div className="news-list">
        {events.slice(0, 8).map((ev, idx) => (
          <div
            key={ev.event_id || idx}
            className={`news-item ${sentimentColor(ev.sentiment_score)}`}
          >
            <div className="news-item-top">
              <span className="news-time">{ev.time_str}</span>
              <span className={`news-cat-badge cat-${ev.category?.toLowerCase()}`}>
                {categoryLabel(ev.category)}
              </span>
              {ev.severity && ev.severity !== 'NONE' && (
                <span className={`news-sev-badge ${severityBadge(ev.severity).cls}`}>
                  {severityBadge(ev.severity).label}
                </span>
              )}
              <span className="news-age">{formatAge(ev.age_seconds)}</span>
            </div>

            <div className="news-headline">{ev.headline}</div>

            <div className="news-item-bottom">
              <span className={`news-score ${sentimentColor(ev.sentiment_score)}`}>
                {ev.sentiment_score > 0 ? '+' : ''}{ev.sentiment_score?.toFixed(2)}
              </span>
              <span className="news-confidence">
                güven: {(ev.confidence * 100).toFixed(0)}%
              </span>
              {ev.symbols && ev.symbols.length > 0 && (
                <span className="news-symbols">
                  {ev.symbols.map((s) => (
                    <span key={s} className="news-symbol-tag">{s.replace('F_', '')}</span>
                  ))}
                </span>
              )}
              {ev.is_global && <span className="news-global-tag">🌍 Global</span>}
              {ev.lot_multiplier < 1.0 && (
                <span className="news-lot-warn">
                  Lot ×{ev.lot_multiplier.toFixed(2)}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
