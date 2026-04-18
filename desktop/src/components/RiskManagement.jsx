/**
 * ÜSTAT v5.9 — Risk Yönetimi sayfası.
 *
 * Layout:
 *   Üst:   Durum banner (işlem izni, kill-switch, rejim)
 *   Orta:  Drawdown göstergeleri (günlük/haftalık/aylık/hard — progress bar)
 *   Alt:   Sayaçlar (günlük işlem, üst üste kayıp, cooldown, pozisyon)
 *
 * Veri kaynağı: GET /api/risk (10sn poll)
 */

import React, { useState, useEffect, useCallback } from 'react';
import { getRisk } from '../services/api';
import { formatMoney } from '../utils/formatters';

// ── Widget Denetimi A13 (H17): Lot çarpanı tier etiketleme ─────
// BABA `lot_multiplier` alanını verdict.lot_multiplier üzerinden RiskResponse'a
// akıtır. Haftalık kayıp (`weekly_loss_halved=True`) sonrası ×0.5,
// graduated lot mantığı ×0.75/×0.50/×0.25, OLAY rejimi ×0.0 vb. değerler
// burada tek "lot_multiplier" alanına toplanır. UI bu sayısal değeri
// rozet + açıklama olarak operatöre gösterir — kullanıcı "lotum neden
// düştü" sorusuna anında yanıt bulur.
function getLotTier(mult) {
  if (mult == null || Number.isNaN(mult)) {
    return { label: '—', cls: 'lot-tier-unknown', hint: '' };
  }
  if (mult >= 0.99) {
    return {
      label: 'Normal Lot',
      cls: 'lot-tier-normal',
      hint: 'Tam risk: graduated azaltma uygulanmıyor.',
    };
  }
  if (mult >= 0.5) {
    return {
      label: 'Yarım Lot',
      cls: 'lot-tier-half',
      hint: 'Risk azaltma aktif (haftalık kayıp veya graduated lot).',
    };
  }
  if (mult >= 0.24) {
    return {
      label: 'Çeyrek Lot',
      cls: 'lot-tier-quarter',
      hint: 'Yoğun risk azaltma — günlük/haftalık birikmiş kayıp.',
    };
  }
  if (mult > 0) {
    return {
      label: 'Asgari Lot',
      cls: 'lot-tier-min',
      hint: 'Kritik risk seviyesi — minimum açılış.',
    };
  }
  return {
    label: 'Lot İptal',
    cls: 'lot-tier-blocked',
    hint: 'OLAY rejimi veya kill-switch — yeni işlem açılmaz.',
  };
}

// ── Kill-Switch Neden Etiketleri ────────────────────────────────
const KS_REASON_MAP = {
  olay_regime: 'OLAY rejimi algılandı',
  daily_loss: 'Günlük kayıp limiti aşıldı',
  consecutive_loss: 'Üst üste kayıp limiti',
  weekly_loss: 'Haftalık kayıp limiti',
  monthly_loss: 'Aylık kayıp limiti',
  hard_drawdown: 'Hard drawdown (%15) tetiklendi',
  floating_loss: 'Floating kayıp limiti aşıldı',
  manual: 'Manuel olarak etkinleştirildi',
  margin_call: 'Marjin yetersiz',
  restored_from_db: 'Veritabanından geri yüklendi (önceki oturumdan)',
  daily_loss_3pct: 'Günlük -%3 kayıp tetiklendi',
};

function formatKsReason(reason) {
  if (!reason) return 'Bilinmiyor';
  return KS_REASON_MAP[reason] || reason;
}

// ── Kill-Switch Bilgi Modalı ────────────────────────────────────

const KillSwitchInfoModal = React.memo(function KillSwitchInfoModal({
  open, onClose, level, details, blockedSymbols, riskReason,
}) {
  useEffect(() => {
    if (!open) return;
    const handleKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;

  const levelLabels = {
    0: { text: 'Yok — Sistem Normal', cls: 'ks-ok' },
    1: { text: 'L1 — Kontrat Dur', cls: 'ks-warn' },
    2: { text: 'L2 — Sistem Pause', cls: 'ks-error' },
    3: { text: 'L3 — Tam Kapanış', cls: 'ks-critical' },
  };
  const levelDescriptions = {
    0: 'Tüm sistemler normal çalışıyor. İşlem izni açık.',
    1: 'Belirli kontratlar için işlem durdu. Diğer kontratlar normal.',
    2: 'Tüm yeni işlemler durduruldu. Mevcut pozisyonlar korunuyor.',
    3: 'ACİL DURUM — Tüm pozisyonlar kapatıldı. Sistem tamamen durdu.',
  };

  const lbl = levelLabels[level] || levelLabels[0];
  const reason = details?.reason || '';
  const message = details?.message || '';
  const triggeredAt = details?.triggered_at || '';
  const symbols = details?.symbols || blockedSymbols || [];

  return (
    <div
      className="confirm-modal-overlay"
      role="dialog"
      aria-modal="true"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="confirm-modal-card" style={{ maxWidth: 480 }} onClick={(e) => e.stopPropagation()}>
        <h2 className="confirm-modal-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 20 }}>{level >= 2 ? '🔴' : level === 1 ? '🟡' : '🟢'}</span>
          Kill-Switch Durumu
        </h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 16 }}>
          {/* Seviye */}
          <div style={{ background: 'var(--bg-elevated, #1a1f2e)', borderRadius: 6, padding: '10px 14px' }}>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: 4 }}>Seviye</div>
            <div style={{ fontSize: 18, fontWeight: 700 }} className={lbl.cls}>{lbl.text}</div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>{levelDescriptions[level]}</div>
          </div>

          {/* Neden */}
          {(reason || riskReason) && (
            <div style={{ background: 'var(--bg-elevated, #1a1f2e)', borderRadius: 6, padding: '10px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: 4 }}>Neden</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{formatKsReason(reason)}</div>
              {message && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>{message}</div>}
              {!reason && riskReason && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>{riskReason}</div>}
            </div>
          )}

          {/* Tetiklenme zamanı */}
          {triggeredAt && (
            <div style={{ background: 'var(--bg-elevated, #1a1f2e)', borderRadius: 6, padding: '10px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: 4 }}>Tetiklenme Zamanı</div>
              <div style={{ fontSize: 14, color: 'var(--text-primary)' }}>
                {new Date(triggeredAt).toLocaleString('tr-TR')}
              </div>
            </div>
          )}

          {/* Engelli semboller */}
          {symbols.length > 0 && (
            <div style={{ background: 'var(--bg-elevated, #1a1f2e)', borderRadius: 6, padding: '10px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: 4 }}>Engelli Kontratlar</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {symbols.map((s) => (
                  <span key={s} style={{
                    background: 'rgba(255,82,82,0.15)', color: 'var(--loss)',
                    padding: '2px 8px', borderRadius: 4, fontSize: 12, fontWeight: 600,
                  }}>{s}</span>
                ))}
              </div>
            </div>
          )}

          {/* Level 0 ise kısa bilgi */}
          {level === 0 && !reason && (
            <div style={{ background: 'var(--bg-elevated, #1a1f2e)', borderRadius: 6, padding: '10px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: 4 }}>Bilgi</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                Kill-switch aktif değil. Sistem normal çalışıyor. Risk limitleri aşıldığında veya OLAY rejimi algılandığında otomatik devreye girer.
              </div>
            </div>
          )}
        </div>

        <div className="confirm-modal-actions">
          <button
            type="button"
            className="confirm-modal-btn confirm-modal-btn-confirm"
            style={{ background: '#f5a623', color: '#1a1f2e', fontWeight: 700 }}
            onClick={onClose}
            autoFocus
          >
            Tamam
          </button>
        </div>
      </div>
    </div>
  );
});

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
  const [ksModalOpen, setKsModalOpen] = useState(false);

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
  // Widget Denetimi A13 (H17): Lot çarpanı tier rozeti + banner.
  const lotTier = getLotTier(risk.lot_multiplier);
  const lotReduced = (risk.lot_multiplier ?? 1.0) < 0.99;

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

        <div
          className={`risk-status-card risk-status--ks-${risk.kill_switch_level}`}
          style={{ cursor: 'pointer' }}
          title="Detay görmek için tıkla"
          onClick={() => setKsModalOpen(true)}
        >
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
          {/* Widget Denetimi A13 (H17): Tier rozeti — operatör çarpanın
              hangi katmanı temsil ettiğini renk + etiketle anında görsün. */}
          <span
            className={`risk-lot-tier-badge ${lotTier.cls}`}
            title={lotTier.hint}
          >
            {lotTier.label}
          </span>
        </div>
      </div>

      {/* Widget Denetimi A13 (H17): Lot azaltma banner'ı. lot_multiplier <
          1.0 olduğunda haftalık/günlük kayıp ya da OLAY/kill-switch nedeniyle
          BABA risk'i düşürdüğünü operatöre net göster. */}
      {lotReduced && (
        <div className={`risk-lot-banner ${lotTier.cls}`}>
          <span className="risk-lot-banner-icon">⚠</span>
          <span className="risk-lot-banner-text">
            <strong>Lot çarpanı düşürüldü:</strong> x
            {risk.lot_multiplier?.toFixed(2) ?? '—'} ({lotTier.label}). {lotTier.hint}
            {risk.risk_reason ? ` Neden: ${risk.risk_reason}` : ''}
          </span>
        </div>
      )}

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

      {/* ═══ KILL-SWITCH BİLGİ MODALI ═════════════════════════════ */}
      <KillSwitchInfoModal
        open={ksModalOpen}
        onClose={() => setKsModalOpen(false)}
        level={risk.kill_switch_level}
        details={risk.kill_switch_details}
        blockedSymbols={risk.blocked_symbols}
        riskReason={risk.risk_reason}
      />
    </div>
  );
}
