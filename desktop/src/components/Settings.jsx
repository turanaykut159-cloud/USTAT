/**
 * ÜSTAT v5.0 — Ayarlar ekranı.
 *
 * Bölümler:
 *   1. MT5 Bağlantı Bilgileri (sunucu, hesap, şifre maskeli)
 *   2. "Farklı hesap ile giriş" butonu
 *   3. Risk Parametreleri (salt okunur — güvenlik)
 *   4. Tema Ayarı (şimdilik sadece koyu tema)
 *   5. Bildirim Tercihleri
 *   6. Sistem Log Görüntüleme
 *   7. Versiyon Bilgisi
 *
 * Veri: getAccount, getRisk, getStatus, getEvents
 */

import React, { useState, useEffect, useCallback } from 'react';
import { getAccount, getRisk, getStatus, getEvents } from '../services/api';

// ── Sabitler ──────────────────────────────────────────────────────

const VERSION = '5.0.0';
const BUILD_DATE = '2026-02-22';

const SEVERITY_ORDER = { CRITICAL: 0, WARNING: 1, INFO: 2 };

const DEFAULT_PREFS = {
  soundEnabled: true,
  killSwitchAlert: true,
  tradeAlert: true,
  drawdownAlert: true,
  regimeAlert: false,
};

// ── Yardımcılar ──────────────────────────────────────────────────

function maskLogin(login) {
  if (!login) return '—';
  const s = String(login);
  if (s.length <= 4) return '****';
  return s.slice(0, 2) + '*'.repeat(s.length - 4) + s.slice(-2);
}

function pctLabel(val) {
  if (val == null) return '—';
  return `%${(val * 100).toFixed(1)}`;
}

function formatTS(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    const dd = d.getDate().toString().padStart(2, '0');
    const mm = (d.getMonth() + 1).toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mi = d.getMinutes().toString().padStart(2, '0');
    const ss = d.getSeconds().toString().padStart(2, '0');
    return `${dd}.${mm} ${hh}:${mi}:${ss}`;
  } catch {
    return ts;
  }
}

function sevCls(sev) {
  if (sev === 'CRITICAL') return 'st-sev-critical';
  if (sev === 'WARNING') return 'st-sev-warning';
  return 'st-sev-info';
}


// ═══════════════════════════════════════════════════════════════════
//  ANA BİLEŞEN
// ═══════════════════════════════════════════════════════════════════

export default function Settings() {
  const [account, setAccount] = useState(null);
  const [risk, setRisk] = useState(null);
  const [status, setStatusData] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);

  // Bildirim tercihleri (localStorage)
  const [prefs, setPrefs] = useState(() => {
    try {
      const saved = localStorage.getItem('ustat_notification_prefs');
      return saved ? { ...DEFAULT_PREFS, ...JSON.parse(saved) } : DEFAULT_PREFS;
    } catch {
      return DEFAULT_PREFS;
    }
  });

  // Log filtreleri
  const [logFilter, setLogFilter] = useState('all');       // all / CRITICAL / WARNING / INFO
  const [logLimit, setLogLimit] = useState(50);

  // MT5 şifre göster/gizle
  const [showLogin, setShowLogin] = useState(false);

  // ── Veri çekme ──────────────────────────────────────────────────

  const fetchData = useCallback(async () => {
    setLoading(true);
    const [acc, rsk, sts, evt] = await Promise.all([
      getAccount(),
      getRisk(),
      getStatus(),
      getEvents({ limit: logLimit }),
    ]);
    setAccount(acc);
    setRisk(rsk);
    setStatusData(sts);
    setEvents(evt.events || []);
    setLoading(false);
  }, [logLimit]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ── Log yenile ─────────────────────────────────────────────────

  const refreshLogs = useCallback(async () => {
    const severity = logFilter === 'all' ? undefined : logFilter;
    const evt = await getEvents({ severity, limit: logLimit });
    setEvents(evt.events || []);
  }, [logFilter, logLimit]);

  useEffect(() => { refreshLogs(); }, [refreshLogs]);

  // ── Pref kaydet ─────────────────────────────────────────────────

  const togglePref = (key) => {
    setPrefs((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      localStorage.setItem('ustat_notification_prefs', JSON.stringify(next));
      return next;
    });
  };

  // ── Render ──────────────────────────────────────────────────────

  if (loading && !account) {
    return (
      <div className="settings">
        <h2>Ayarlar</h2>
        <div className="st-loading">Yükleniyor...</div>
      </div>
    );
  }

  return (
    <div className="settings">
      <h2>Ayarlar</h2>

      <div className="st-grid">

        {/* ═══ SOL KOLON ═════════════════════════════════════════════ */}
        <div className="st-col">

          {/* ── MT5 BAĞLANTI ─────────────────────────────────────── */}
          <section className="st-section">
            <div className="st-section-header">
              <h3>MT5 Bağlantı Bilgileri</h3>
              <span className={`st-conn-badge ${status?.mt5_connected ? 'connected' : 'disconnected'}`}>
                {status?.mt5_connected ? 'Bağlı' : 'Bağlantı Yok'}
              </span>
            </div>

            <div className="st-field-group">
              <FieldRow label="Sunucu" value={account?.server || '—'} />
              <FieldRow
                label="Hesap No"
                value={showLogin ? String(account?.login || '—') : maskLogin(account?.login)}
                action={
                  <button
                    className="st-eye-btn"
                    onClick={() => setShowLogin((v) => !v)}
                    title={showLogin ? 'Gizle' : 'Göster'}
                  >
                    {showLogin ? '◉' : '○'}
                  </button>
                }
              />
              <FieldRow label="Şifre" value="••••••••" />
              <FieldRow label="Para Birimi" value={account?.currency || 'TRY'} />
            </div>

            <button className="st-btn st-btn-secondary" onClick={() => {
              // Electron IPC ile MT5 launcher'a yeni hesap isteği gönder
              if (window.electronAPI?.restartMT5) {
                window.electronAPI.restartMT5();
              } else {
                alert('MT5 Launcher servisine bağlanılamadı.\nManuel olarak MetaTrader 5\'i yeniden başlatın.');
              }
            }}>
              Farklı Hesap ile Giriş
            </button>
          </section>

          {/* ── RİSK PARAMETRELERİ ───────────────────────────────── */}
          <section className="st-section">
            <div className="st-section-header">
              <h3>Risk Parametreleri</h3>
              <span className="st-readonly-badge">Salt Okunur</span>
            </div>
            <p className="st-section-note">
              Güvenlik nedeniyle risk parametreleri arayüzden değiştirilemez.
              Değişiklik için <code>engine/config.py</code> düzenleyin.
            </p>

            <div className="st-field-group">
              <FieldRow label="Günlük Maks Kayıp" value={pctLabel(risk?.max_daily_loss)} />
              <FieldRow label="Haftalık Maks Kayıp" value={pctLabel(risk?.max_weekly_loss)} />
              <FieldRow label="Aylık Maks Kayıp" value={pctLabel(risk?.max_monthly_loss)} />
              <FieldRow label="Hard Drawdown" value={pctLabel(risk?.hard_drawdown)} cls="loss" />
              <FieldRow label="Maks Floating Kayıp" value={pctLabel(risk?.max_floating_loss)} />
              <div className="st-field-sep" />
              <FieldRow label="Günlük Maks İşlem" value={risk?.max_daily_trades ?? '—'} />
              <FieldRow label="Ard. Kayıp Limiti" value={risk?.consecutive_loss_limit ?? '—'} />
              <FieldRow label="Maks Açık Pozisyon" value={risk?.max_open_positions ?? '—'} />
              <div className="st-field-sep" />
              <FieldRow label="Lot Çarpanı" value={risk?.lot_multiplier != null ? `×${risk.lot_multiplier.toFixed(2)}` : '—'} />
              <FieldRow label="Risk Çarpanı (Rejim)" value={risk?.risk_multiplier != null ? `×${risk.risk_multiplier.toFixed(2)}` : '—'} />
            </div>
          </section>

        </div>

        {/* ═══ SAĞ KOLON ═════════════════════════════════════════════ */}
        <div className="st-col">

          {/* ── TEMA AYARI ───────────────────────────────────────── */}
          <section className="st-section">
            <div className="st-section-header">
              <h3>Tema</h3>
            </div>
            <div className="st-theme-row">
              <div className="st-theme-card active">
                <div className="st-theme-preview dark" />
                <span>Koyu Tema</span>
              </div>
              <div className="st-theme-card disabled" title="Yakında...">
                <div className="st-theme-preview light" />
                <span>Açık Tema</span>
              </div>
            </div>
          </section>

          {/* ── BİLDİRİM TERCİHLERİ ─────────────────────────────── */}
          <section className="st-section">
            <div className="st-section-header">
              <h3>Bildirim Tercihleri</h3>
            </div>
            <div className="st-toggle-group">
              <ToggleRow
                label="Ses bildirimleri"
                desc="İşlem ve uyarı sesleri"
                checked={prefs.soundEnabled}
                onChange={() => togglePref('soundEnabled')}
              />
              <ToggleRow
                label="Kill-Switch uyarısı"
                desc="L1/L2/L3 tetiklendiğinde bildirim"
                checked={prefs.killSwitchAlert}
                onChange={() => togglePref('killSwitchAlert')}
              />
              <ToggleRow
                label="İşlem bildirimi"
                desc="Yeni işlem açıldığında / kapandığında"
                checked={prefs.tradeAlert}
                onChange={() => togglePref('tradeAlert')}
              />
              <ToggleRow
                label="Drawdown uyarısı"
                desc="Risk limitlerine yaklaşıldığında"
                checked={prefs.drawdownAlert}
                onChange={() => togglePref('drawdownAlert')}
              />
              <ToggleRow
                label="Rejim değişikliği"
                desc="Piyasa rejimi değiştiğinde"
                checked={prefs.regimeAlert}
                onChange={() => togglePref('regimeAlert')}
              />
            </div>
          </section>

          {/* ── VERSİYON BİLGİSİ ─────────────────────────────────── */}
          <section className="st-section st-version-section">
            <div className="st-section-header">
              <h3>Hakkında</h3>
            </div>
            <div className="st-version-grid">
              <FieldRow label="Uygulama" value="ÜSTAT Desktop" />
              <FieldRow label="Versiyon" value={`v${VERSION}`} />
              <FieldRow label="Build Tarihi" value={BUILD_DATE} />
              <FieldRow label="Engine" value={status?.engine_running ? 'Çalışıyor' : 'Durduruldu'} cls={status?.engine_running ? 'profit' : 'loss'} />
              <FieldRow label="Uptime" value={status?.uptime_seconds ? formatUptime(status.uptime_seconds) : '—'} />
              <FieldRow label="Faz" value={status?.phase || '—'} />
            </div>
          </section>

        </div>
      </div>

      {/* ═══ SİSTEM LOG — TAM GENİŞLİK ════════════════════════════ */}
      <section className="st-section st-log-section">
        <div className="st-section-header">
          <h3>Sistem Log</h3>
          <div className="st-log-controls">
            <div className="st-log-filters">
              {['all', 'CRITICAL', 'WARNING', 'INFO'].map((f) => (
                <button
                  key={f}
                  className={`st-log-filter-btn ${logFilter === f ? 'active' : ''}`}
                  onClick={() => setLogFilter(f)}
                >
                  {f === 'all' ? 'Tümü' : f}
                </button>
              ))}
            </div>
            <select
              className="st-log-limit"
              value={logLimit}
              onChange={(e) => setLogLimit(Number(e.target.value))}
            >
              <option value={25}>25 kayıt</option>
              <option value={50}>50 kayıt</option>
              <option value={100}>100 kayıt</option>
              <option value={200}>200 kayıt</option>
            </select>
            <button className="st-btn st-btn-sm" onClick={refreshLogs}>
              Yenile
            </button>
          </div>
        </div>

        <div className="st-log-table-wrap">
          <table className="st-log-table">
            <thead>
              <tr>
                <th style={{ width: 110 }}>Zaman</th>
                <th style={{ width: 90 }}>Önem</th>
                <th style={{ width: 120 }}>Tip</th>
                <th>Mesaj</th>
                <th style={{ width: 100 }}>Aksiyon</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 ? (
                <tr>
                  <td colSpan={5} className="st-log-empty">Kayıt bulunamadı</td>
                </tr>
              ) : (
                events.map((ev) => (
                  <tr key={ev.id} className={sevCls(ev.severity)}>
                    <td className="st-log-ts">{formatTS(ev.timestamp)}</td>
                    <td>
                      <span className={`st-sev-badge ${sevCls(ev.severity)}`}>
                        {ev.severity}
                      </span>
                    </td>
                    <td className="st-log-type">{ev.type}</td>
                    <td className="st-log-msg">{ev.message}</td>
                    <td className="st-log-action">{ev.action || '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="st-log-footer">
          <span>{events.length} kayıt gösteriliyor</span>
        </div>
      </section>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
//  ALT BİLEŞENLER
// ═══════════════════════════════════════════════════════════════════

function FieldRow({ label, value, cls, action }) {
  return (
    <div className="st-field-row">
      <span className="st-field-label">{label}</span>
      <div className="st-field-value-wrap">
        <span className={`st-field-value ${cls || ''}`}>{value}</span>
        {action}
      </div>
    </div>
  );
}

function ToggleRow({ label, desc, checked, onChange }) {
  return (
    <div className="st-toggle-row">
      <div className="st-toggle-info">
        <span className="st-toggle-label">{label}</span>
        {desc && <span className="st-toggle-desc">{desc}</span>}
      </div>
      <button
        className={`st-toggle ${checked ? 'on' : 'off'}`}
        onClick={onChange}
        role="switch"
        aria-checked={checked}
      >
        <span className="st-toggle-knob" />
      </button>
    </div>
  );
}


// ── Yardımcı: uptime formatlama ─────────────────────────────────

function formatUptime(sec) {
  if (!sec || sec <= 0) return '—';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}sa ${m}dk`;
  if (m > 0) return `${m}dk ${s}sn`;
  return `${s}sn`;
}
