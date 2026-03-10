/**
 * ÜSTAT v5.3 — Risk Yönetimi sayfası.
 *
 * Layout:
 *   Üst:   Durum banner (işlem izni, kill-switch, rejim)
 *   Orta:  Drawdown göstergeleri (günlük/haftalık/aylık/hard — progress bar)
 *   Alt:   Sayaçlar (günlük işlem, üst üste kayıp, cooldown, pozisyon)
 *
 * Veri kaynağı: GET /api/risk (5sn poll)
 */

import React, { useState, useEffect, useCallback } from 'react';
import { getRisk } from '../services/api';
import { formatMoney } from '../utils/formatters';

// ── Yardımcılar ──────────────────────────────────────────────────

function pct(val) {
  if (val == null || isNaN(val)) return '—';
  return `%${(val * 100).toFixed(2)}`;
}

// ── Progress Bar bileşeni ────────────────────────────────────────

const RiskBar = React.memo(function RiskBar({ label, current, limit, unit = '%', danger = false }) {
  const currentPct = limit > 0 ? Math.min(Math.abs(current) / limit, 1) : 0;
  const fillPct = (currentPct * 100).toFixed(1);
  const isHigh = currentPct >= 0.7;
  const isCritical = currentPct >= 0.9;

  let barClass = 'risk-bar-fill--ok';
  if (isCritical || danger) barClass = 'risk-bar-fill--critical';
  else if (isHigh) barClass = 'risk-bar-fill--warning';

  const currentDisplay = unit === '%' ? `%${(Math.abs(current) * 100).toFixed(2)}` : formatMoney(current);
  const limitDisplay = unit === '%' ? `%${(limit * 100).toFixed(1)}` : formatMoney(limit);

  return (
    <div className="risk-bar-row">
      <div className="risk-bar-label">
        <span>{label}</span>
        <span className="risk-bar-values">
          {currentDisplay} <span className="risk-bar-sep">/</span> {limitDisplay}
        </span>
      </div>
      <div className="risk-bar-track">
        <div className={`risk-bar-fill ${barClass}`} style={{ width: `${fillPct}%` }} />
      </div>
    </div>
  );
});

// ── Kill-switch seviye etiketi ───────────────────────────────────

const KS_LABELS = {
  0: { text: 'Yok', cls: 'ks-ok' },
  1: { text: 'L1 — Kontrat Dur', cls: 'ks-warn' },
  2: { text: 'L2 — Sistem Pause', cls: 'ks-error' },
  3: { text: 'L3 — Tam Kapanış', cls: 'ks-critical' },
};

const REGIME_LABELS = {
  TREND: { text: 'TREND', cls: 'regime-trend' },
  RANGE: { text: 'RANGE', cls: 'regime-range' },
  VOLATILE: { text: 'VOLATILE', cls: 'regime-volatile' },
  OLAY: { text: 'OLAY', cls: 'regime-olay' },
};

// ══════════════════════════════════════════════════════════════════

export default function RiskManagement() {
  const [risk, setRisk] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    const data = await getRisk();
    setRisk(data);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 10000);
    return () => clearInterval(iv);
  }, [fetchData]);

  if (loading && !risk) {
    return <div className="risk-page"><p className="risk-loading">Yükleniyor...</p></div>;
  }

  if (!risk) {
    return <div className="risk-page"><p className="risk-loading">Risk verisi alınamadı.</p></div>;
  }

  const ks = KS_LABELS[risk.kill_switch_level] || KS_LABELS[0];
  const reg = REGIME_LABELS[risk.regime] || { text: risk.regime, cls: 'regime-trend' };

  return (
    <div className="risk-page">
      <h2>Risk Yönetimi</h2>

      {/* ═══ DURUM BANNER ═══════════════════════════════════════════ */}
      <div className="risk-status-row">
        <div className={`risk-status-card ${risk.can_trade ? 'risk-status--ok' : 'risk-status--blocked'}`}>
          <span className="risk-status-label">İşlem İzni</span>
          <span className="risk-status-value">
            {risk.can_trade ? 'AÇIK' : 'KAPALI'}
          </span>
          {risk.risk_reason && (
            <span className="risk-status-reason">{risk.risk_reason}</span>
          )}
        </div>

        <div className={`risk-status-card risk-status--ks-${risk.kill_switch_level}`}>
          <span className="risk-status-label">Kill-Switch</span>
          <span className={`risk-status-value ${ks.cls}`}>{ks.text}</span>
          {risk.blocked_symbols?.length > 0 && (
            <span className="risk-status-reason">
              Engelli: {risk.blocked_symbols.join(', ')}
            </span>
          )}
        </div>

        <div className="risk-status-card">
          <span className="risk-status-label">Rejim</span>
          <span className={`risk-status-value ${reg.cls}`}>{reg.text}</span>
          <span className="risk-status-reason">
            Rejim Çarpanı: x{risk.risk_multiplier?.toFixed(2) ?? '—'}
          </span>
        </div>

        <div className="risk-status-card">
          <span className="risk-status-label">Lot Çarpanı</span>
          <span className="risk-status-value">
            x{risk.lot_multiplier?.toFixed(2) ?? '—'}
          </span>
        </div>
      </div>

      {/* ═══ DRAWDOWN GÖSTERGELERİ ═════════════════════════════════ */}
      <div className="risk-section">
        <h3>Zarar Limitleri</h3>
        <div className="risk-bars">
          <RiskBar
            label="Günlük Kayıp"
            current={risk.daily_drawdown_pct ?? 0}
            limit={risk.max_daily_loss}
          />
          <RiskBar
            label="Haftalık Kayıp"
            current={risk.weekly_drawdown_pct ?? 0}
            limit={risk.max_weekly_loss}
          />
          <RiskBar
            label="Aylık Kayıp"
            current={risk.monthly_drawdown_pct ?? risk.total_drawdown_pct ?? 0}
            limit={risk.max_monthly_loss}
          />
          <RiskBar
            label="Hard Drawdown"
            current={risk.total_drawdown_pct || 0}
            limit={risk.hard_drawdown}
          />
          <RiskBar
            label="Floating Kayıp"
            current={risk.equity > 0 && risk.floating_pnl < 0 ? Math.abs(risk.floating_pnl) / risk.equity : 0}
            limit={risk.max_floating_loss}
          />
        </div>
      </div>

      {/* ═══ SAYAÇLAR ══════════════════════════════════════════════ */}
      <div className="risk-section">
        <h3>Sayaçlar</h3>
        <div className="risk-counters">
          <div className="risk-counter-card">
            <span className="risk-counter-label">Günlük İşlem</span>
            <span className="risk-counter-value">
              {risk.daily_trade_count ?? 0}
              <span className="risk-counter-limit"> / {risk.max_daily_trades ?? 5}</span>
            </span>
          </div>

          <div className="risk-counter-card">
            <span className="risk-counter-label">Üst Üste Kayıp</span>
            <span className={`risk-counter-value ${(risk.consecutive_losses || 0) >= (risk.consecutive_loss_limit || 3) ? 'loss' : ''}`}>
              {risk.consecutive_losses ?? 0}
              <span className="risk-counter-limit"> / {risk.consecutive_loss_limit ?? 3}</span>
            </span>
          </div>

          <div className="risk-counter-card">
            <span className="risk-counter-label">Açık Pozisyon</span>
            <span className="risk-counter-value">
              {risk.open_positions ?? 0}
              <span className="risk-counter-limit"> / {risk.max_open_positions ?? 5}</span>
            </span>
          </div>

          <div className="risk-counter-card">
            <span className="risk-counter-label">Cooldown</span>
            <span className={`risk-counter-value ${risk.cooldown_until ? 'loss' : ''}`}>
              {risk.cooldown_until || 'Yok'}
            </span>
          </div>
        </div>
      </div>

      {/* ═══ PNL DETAY ════════════════════════════════════════════ */}
      <div className="risk-section">
        <h3>Anlık Durum</h3>
        <div className="risk-counters">
          <div className="risk-counter-card">
            <span className="risk-counter-label">Günlük K/Z</span>
            <span className={`risk-counter-value ${risk.daily_pnl >= 0 ? 'profit' : 'loss'}`}>
              {formatMoney(risk.daily_pnl)} TRY
            </span>
          </div>
          <div className="risk-counter-card">
            <span className="risk-counter-label">Floating K/Z</span>
            <span className={`risk-counter-value ${risk.floating_pnl >= 0 ? 'profit' : 'loss'}`}>
              {formatMoney(risk.floating_pnl)} TRY
            </span>
          </div>
          <div className="risk-counter-card">
            <span className="risk-counter-label">Bakiye</span>
            <span className="risk-counter-value">
              {formatMoney(risk.balance)} TRY
            </span>
          </div>
          <div className="risk-counter-card">
            <span className="risk-counter-label">Toplam Drawdown</span>
            <span className="risk-counter-value">
              {pct(risk.total_drawdown_pct)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
