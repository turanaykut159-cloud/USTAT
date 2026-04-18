/**
 * ÜSTAT Plus V6.0 — Ayarlar ekranı.
 *
 * Bölümler:
 *   1. MT5 Bağlantı Bilgileri (sunucu, hesap no maskeli, para birimi —
 *      şifre UI'de GÖSTERİLMEZ; Widget Denetimi H11: eski dummy sabit
 *      bullet FieldRow tamamen kaldırıldı, çünkü /api/account endpoint'i
 *      şifreyi hiç döndürmez — MT5 şifresi Windows credential store'da
 *      tutulur ve renderer'a güvenlik gereği aktarılmaz. Placeholder
 *      bile değildi, tamamen dekoratif ölü UI idi)
 *   2. "Farklı hesap ile giriş" butonu
 *   3. Tema Ayarı (koyu tema aktif; açık tema CSS'te hazır ama tüm bileşenlerde
 *      doğrulanmadığı için disabled — Widget Denetimi H12)
 *   4. Bildirim Tercihleri
 *   5. Sistem Log Görüntüleme
 *   6. Versiyon Bilgisi
 *
 * Risk Parametreleri → Risk Yönetimi sayfasında gösteriliyor (mükerrer kaldırıldı).
 *
 * Veri: getAccount, getStatus, getEvents
 */

import React, { useState, useEffect, useCallback } from 'react';
import { getAccount, getStatus, getEvents, getRiskBaseline, updateRiskBaseline, getNotificationPrefs, updateNotificationPrefs } from '../services/api';
// Widget Denetimi H16: Operatör adı canonical kaynağa bağlandı.
// localStorage'ta saklanır; TradeHistory.jsx::handleApprove,
// SideNav.jsx::handleKillSwitch ve TopBar.jsx::handleKsReset
// `getOperatorName()` ile aynı değeri okur. Drift Flow 4za.
import { getOperatorName, setOperatorName, DEFAULT_OPERATOR } from '../utils/operator';

// ── Sabitler ──────────────────────────────────────────────────────

// A5/H1: VERSION hardcode'u kaldirildi — tek kaynak engine/__init__.py::VERSION.
// Artik status?.version uzerinden /api/status endpoint'inden okunur.
// Fallback '6.2.0' ilk render ve hata durumu icin.
const VERSION_FALLBACK = '6.2.0';
const BUILD_DATE = '2026-04-18';

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

  // Risk Baseline Date+Time — iki aşamalı doğrulama
  const [baselineDate, setBaselineDate] = useState('');       // "YYYY-MM-DD HH:MM" veya "YYYY-MM-DD"
  const [baselineDateInput, setBaselineDateInput] = useState('');
  const [baselineTimeInput, setBaselineTimeInput] = useState('00:00');
  const [baselineStep, setBaselineStep] = useState('idle'); // idle | confirm | saving
  const [baselineMsg, setBaselineMsg] = useState('');

  // Widget Denetimi H16: Operatör adı (localStorage canonical kaynak).
  // Settings'te düzenlenir; TradeHistory/SideNav/TopBar getOperatorName()
  // ile okur. Boş bırakılırsa DEFAULT_OPERATOR ('operator') fallback'ı
  // devreye girer (geriye uyumlu).
  const [operatorName, setOperatorNameState] = useState(() => {
    const v = getOperatorName();
    return v === DEFAULT_OPERATOR ? '' : v;
  });
  const [operatorMsg, setOperatorMsg] = useState('');

  // ── Tema (localStorage + DOM) — Widget Denetimi H12 ──
  //
  // Açık tema CSS değişkenleri (theme.css `:root[data-theme="light"]`) hazır,
  // ancak tüm bileşenlerde doğrulanmadığı için UI'den seçilemez (disabled
  // kart + tooltip). applyTheme sadece 'dark' argümanını kabul eder; 'light'
  // çağrısı güvenlik amaçlı sessizce reddedilir. Açık tema hazır olduğunda
  // kart disabled state'inden çıkarılır ve bu guard kaldırılır.
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem('ustat_theme');
    // Legacy kullanıcı 'light' kaydetmiş olsa bile UI 'dark' gösterir;
    // gerçek applyTheme çağrısı olana kadar DOM data-theme attribute'u
    // App.jsx mount effect'inde zaten yönetilir.
    return saved === 'light' ? 'dark' : (saved || 'dark');
  });

  const applyTheme = useCallback((newTheme) => {
    // H12 guard: açık tema henüz tam doğrulanmadı, yalnız 'dark' kabul edilir.
    if (newTheme !== 'dark') {
      return;
    }
    setTheme('dark');
    localStorage.setItem('ustat_theme', 'dark');
    document.documentElement.removeAttribute('data-theme');
  }, []);

  // ── Veri çekme ──────────────────────────────────────────────────

  const fetchData = useCallback(async () => {
    setLoading(true);
    const [acc, sts, evt, bl, np] = await Promise.all([
      getAccount(),
      getStatus(),
      getEvents({ limit: logLimit }),
      getRiskBaseline(),
      getNotificationPrefs(),
    ]);
    setAccount(acc);
    setStatusData(sts);
    setEvents(evt.events || []);
    if (bl.baseline_date) {
      setBaselineDate(bl.baseline_date);
      // "YYYY-MM-DD HH:MM" → date + time parçala
      const parts = bl.baseline_date.split(' ');
      setBaselineDateInput(parts[0] || '');
      setBaselineTimeInput(parts[1] || '00:00');
    }
    // P1-API-06: Backend tek kaynak — localStorage sadece cache
    if (np?.prefs) {
      const merged = { ...DEFAULT_PREFS, ...np.prefs };
      setPrefs(merged);
      localStorage.setItem('ustat_notification_prefs', JSON.stringify(merged));
    }
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
      updateNotificationPrefs(next).catch(() => {/* sessiz hata — localStorage zaten güncellendi */});
      return next;
    });
  };

  // ── Risk Baseline handlers ─────────────────────────────────────

  const handleBaselineChange = useCallback(() => {
    const datePart = baselineDateInput.trim();
    const timePart = baselineTimeInput.trim() || '00:00';
    const combined = datePart + ' ' + timePart;  // "YYYY-MM-DD HH:MM"
    if (!datePart || combined === baselineDate) {
      setBaselineMsg('Tarih/saat değişmedi.');
      return;
    }
    // Tarih formatı kontrolü
    if (!/^\d{4}-\d{2}-\d{2}$/.test(datePart)) {
      setBaselineMsg('Geçersiz tarih formatı. YYYY-MM-DD kullanın.');
      return;
    }
    // Saat formatı kontrolü
    if (!/^\d{2}:\d{2}$/.test(timePart)) {
      setBaselineMsg('Geçersiz saat formatı. HH:MM kullanın.');
      return;
    }
    // Geçerli tarih+saat mi?
    const d = new Date(datePart + 'T' + timePart + ':00');
    if (isNaN(d.getTime())) {
      setBaselineMsg('Geçersiz tarih/saat.');
      return;
    }
    // Gelecek tarih mi?
    if (d > new Date()) {
      setBaselineMsg('Gelecek tarih/saat kabul edilmez.');
      return;
    }
    setBaselineMsg(baselineDate + ' \u2192 ' + combined + ' olarak de\u011fi\u015ftirilecek. Risk hesaplamalar\u0131 bu tarih/saatten itibaren yeniden hesaplanacak.');
    setBaselineStep('confirm');
  }, [baselineDateInput, baselineTimeInput, baselineDate]);

  const confirmBaselineChange = useCallback(async () => {
    setBaselineStep('saving');
    setBaselineMsg('Kaydediliyor...');
    const combined = baselineDateInput.trim() + ' ' + (baselineTimeInput.trim() || '00:00');
    const result = await updateRiskBaseline(combined);
    if (result.success) {
      setBaselineDate(combined);
      setBaselineMsg('Ba\u015far\u0131l\u0131: ' + result.old_date + ' \u2192 ' + result.new_date);
      setBaselineStep('idle');
      setTimeout(() => setBaselineMsg(''), 4000);
    } else {
      setBaselineMsg('Hata: ' + result.message);
      setBaselineStep('idle');
    }
  }, [baselineDateInput, baselineTimeInput]);

  const cancelBaselineChange = useCallback(() => {
    const parts = baselineDate.split(' ');
    setBaselineDateInput(parts[0] || '');
    setBaselineTimeInput(parts[1] || '00:00');
    setBaselineStep('idle');
    setBaselineMsg('');
  }, [baselineDate]);

  // ── Operatör adı handler (H16) ─────────────────────────────────
  // Boş input → localStorage temizlenir → DEFAULT_OPERATOR fallback.
  // Dolu input → trim + 64 char limit + localStorage'a yazılır.
  // Ekrana kısa onay mesajı düşer (3sn sonra silinir).
  const handleSaveOperator = useCallback(() => {
    const saved = setOperatorName(operatorName);
    if (saved === DEFAULT_OPERATOR) {
      setOperatorMsg('Operatör adı temizlendi — varsayılan ("operator") kullanılacak.');
    } else {
      setOperatorMsg(`Kaydedildi: ${saved}`);
    }
    setTimeout(() => setOperatorMsg(''), 3000);
  }, [operatorName]);

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
              {/* Widget Denetimi H11: Eski dummy "Şifre" satırı kaldırıldı.
                  /api/account MT5 şifresini hiç döndürmez (güvenlik), bu
                  FieldRow sabit bir bullet dizisi gösteriyordu ve hiçbir
                  backend verisine bağlı değildi. Kullanıcıya "uygulama
                  şifreyi bilip maskeliyor" yanlış mesajını veriyordu.
                  "Farklı Hesap ile Giriş" butonu aşağıda zaten kimlik
                  değişimini sağlıyor. */}
              <FieldRow label="Para Birimi" value={account?.currency || 'TRY'} />
            </div>

            <button
              className="st-btn st-btn-secondary"
              disabled
              title="Bu özellik yakında eklenecek — şimdilik MT5 terminalinden hesap değiştirin"
            >
              Farklı Hesap ile Giriş
            </button>
          </section>

          {/* ── RİSK BASELINE TARİHİ ───────────────────────────── */}
          <section className="st-section">
            <div className="st-section-header">
              <h3>Risk Hesaplama Başlangıcı</h3>
            </div>
            <p className="st-section-desc">
              BABA'nın risk hesaplamalarında (drawdown, haftalık/aylık zarar)
              kullandığı referans başlangıç tarihi. Bu tarihten önceki veriler
              risk hesabına dahil edilmez.
            </p>
            <div className="st-baseline-row">
              <label className="st-field-label">Başlangıç Tarihi</label>
              <input
                type="date"
                className="st-baseline-input"
                value={baselineDateInput}
                onChange={(e) => {
                  setBaselineDateInput(e.target.value);
                  setBaselineStep('idle');
                  setBaselineMsg('');
                }}
              />
              <input
                type="time"
                className="st-baseline-input st-baseline-time"
                value={baselineTimeInput}
                onChange={(e) => {
                  setBaselineTimeInput(e.target.value);
                  setBaselineStep('idle');
                  setBaselineMsg('');
                }}
              />
            </div>

            {baselineStep === 'idle' && (
              <button
                className="st-btn st-btn-primary"
                onClick={handleBaselineChange}
                disabled={!baselineDateInput || (baselineDateInput + ' ' + baselineTimeInput) === baselineDate}
              >
                Güncelle
              </button>
            )}

            {baselineStep === 'confirm' && (
              <div className="st-baseline-confirm">
                <div className="st-baseline-warning">
                  ⚠ {baselineMsg}
                </div>
                <div className="st-baseline-actions">
                  <button className="st-btn st-btn-danger" onClick={confirmBaselineChange}>
                    Onayla ve Uygula
                  </button>
                  <button className="st-btn st-btn-secondary" onClick={cancelBaselineChange}>
                    İptal
                  </button>
                </div>
              </div>
            )}

            {baselineStep === 'saving' && (
              <div className="st-baseline-msg saving">{baselineMsg}</div>
            )}

            {baselineStep === 'idle' && baselineMsg && (
              <div className={'st-baseline-msg ' + (baselineMsg.startsWith('Hata') ? 'error' : 'success')}>
                {baselineMsg}
              </div>
            )}
          </section>

          {/* ── OPERATÖR KİMLİĞİ (Widget Denetimi H16) ───────────── */}
          <section className="st-section">
            <div className="st-section-header">
              <h3>Operatör Kimliği</h3>
            </div>
            <p className="st-section-desc">
              İşlem onayı ve kill-switch işlemlerinde audit log'a yazılan
              operatör adı. Boş bırakılırsa varsayılan ("operator") kullanılır.
              Bu alan yalnız bu masaüstünde saklanır (localStorage), başka
              cihazlara senkronize edilmez.
            </p>
            <div className="st-baseline-row">
              <label className="st-field-label">Operatör Adı</label>
              <input
                type="text"
                className="st-baseline-input"
                value={operatorName}
                maxLength={64}
                placeholder="Örn: Turan Aykut"
                onChange={(e) => {
                  setOperatorNameState(e.target.value);
                  setOperatorMsg('');
                }}
              />
            </div>
            <button
              className="st-btn st-btn-primary"
              onClick={handleSaveOperator}
            >
              Kaydet
            </button>
            {operatorMsg && (
              <div className={'st-baseline-msg ' + (operatorMsg.startsWith('Kaydedildi') ? 'success' : 'info')}>
                {operatorMsg}
              </div>
            )}
          </section>

          {/* ── VERSİYON BİLGİSİ ─────────────────────────────────── */}
          <section className="st-section st-version-section">
            <div className="st-section-header">
              <h3>Hakkında</h3>
            </div>
            <div className="st-version-grid">
              {/* A5/H1: Versiyon status.version (engine/__init__.py::VERSION) tek kaynaktan okunur. */}
              <FieldRow
                label="Uygulama"
                value={`ÜSTAT Plus V${(status?.version || VERSION_FALLBACK).split('.').slice(0, 2).join('.')} Desktop`}
              />
              <FieldRow label="Versiyon" value={`v${status?.version || VERSION_FALLBACK}`} />
              <FieldRow label="Build Tarihi" value={BUILD_DATE} />
              <FieldRow label="Engine" value={status?.engine_running ? 'Çalışıyor' : 'Durduruldu'} cls={status?.engine_running ? 'profit' : 'loss'} />
              <FieldRow label="Uptime" value={status?.uptime_seconds ? formatUptime(status.uptime_seconds) : '—'} />
              <FieldRow label="Faz" value={status?.phase || '—'} />
              <FieldRow label="Geliştirici" value="TURAN AYKUT" />
              <FieldRow label="Copyright" value="© 2026 TURAN AYKUT — Tüm hakları saklıdır" />
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
              <div
                className={`st-theme-card ${theme === 'dark' ? 'active' : ''}`}
                onClick={() => applyTheme('dark')}
              >
                <div className="st-theme-preview dark" />
                <span>Koyu Tema</span>
              </div>
              <div
                className="st-theme-card disabled"
                title="Açık tema henüz tüm bileşenlerde doğrulanmadı — yalnız koyu tema aktif (Widget Denetimi H12)"
                aria-disabled="true"
              >
                <div className="st-theme-preview light" />
                <span>Açık Tema (yakında)</span>
              </div>
            </div>
          </section>

          {/* ── BİLDİRİM TERCİHLERİ ─────────────────────────────── */}
          <section className="st-section">
            <div className="st-section-header">
              <h3>Bildirim Tercihleri</h3>
            </div>
            {/* v6.0 — Widget Denetimi A3/S1: dürüst kapsam uyarısı */}
            <div className="st-info-note" style={{
              padding: '8px 12px',
              marginBottom: '10px',
              background: 'rgba(255, 193, 7, 0.08)',
              border: '1px solid rgba(255, 193, 7, 0.3)',
              borderRadius: '4px',
              fontSize: '12px',
              color: 'var(--text-secondary, #aaa)',
              lineHeight: '1.5',
            }}>
              <strong>Kapsam:</strong> Şu an yalnızca <strong>İşlem & Hibrit Uyarıları</strong> toggle'ı
              Dashboard bildirim çekmecesinde (zil ikonu) gerçek davranışa bağlıdır.
              Diğer toggle'lar tercihleriniz sunucuda kalıcı olarak saklanır, ancak henüz bağlı oldukları bir
              tetikleme mekanizması yoktur.
            </div>
            <div className="st-toggle-group">
              <ToggleRow
                label="Ses bildirimleri"
                desc="İşlem ve uyarı sesleri (henüz aktif değil)"
                checked={prefs.soundEnabled}
                onChange={() => togglePref('soundEnabled')}
              />
              <ToggleRow
                label="Kill-Switch uyarısı"
                desc="L1/L2/L3 tetiklendiğinde bildirim (henüz aktif değil)"
                checked={prefs.killSwitchAlert}
                onChange={() => togglePref('killSwitchAlert')}
              />
              <ToggleRow
                label="İşlem & Hibrit Uyarıları"
                desc="Hibrit pozisyon, EOD ve yön değişimi bildirimleri"
                checked={prefs.tradeAlert}
                onChange={() => togglePref('tradeAlert')}
              />
              <ToggleRow
                label="Drawdown uyarısı"
                desc="Risk limitlerine yaklaşıldığında (henüz aktif değil)"
                checked={prefs.drawdownAlert}
                onChange={() => togglePref('drawdownAlert')}
              />
              <ToggleRow
                label="Rejim değişikliği"
                desc="Piyasa rejimi değiştiğinde (henüz aktif değil)"
                checked={prefs.regimeAlert}
                onChange={() => togglePref('regimeAlert')}
              />
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
