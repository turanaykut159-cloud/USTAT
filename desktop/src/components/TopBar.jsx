/**
 * ÜSTAT Plus V6.0 — Üst bilgi çubuğu.
 *
 * Sol:  ÜSTAT Plus V6.0 logosu | Kill-switch (L1/L2/L3) | Bağlantı durumu (yeşil/kırmızı nokta)
 * Sağ:  Bakiye | Equity | Floating | Günlük K/Z (Snapshot, 2sn) | Pin | Saat
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { getStatus, getAccount, acknowledgeKillSwitch, getAgentStatus, getHealth, setOgulToggle } from '../services/api';
import { formatMoney } from '../utils/formatters';
// Widget Denetimi H16: kill-switch acknowledge kullanıcı kimliği canonical
// kaynağa bağlandı — eski satır 134 hardcode `'operator'` literal'i
// kullanıyordu. Settings → "Operatör Adı" alanı tek kaynak. Drift Flow 4za.
import { getOperatorName } from '../utils/operator';

// ── Faz etiketleri ──────────────────────────────────────────────
const PHASE_LABELS = {
  running: 'AKTIF',
  stopped: 'PASIF',
  killed:  'DURDURULDU',
  error:   'HATA',
  idle:    'BEKLEMEDE',
};

export default function TopBar() {
  // ── State ──────────────────────────────────────────────────────
  //
  // Widget Denetimi H18: Eski initial state'te piyasa rejimi alanı
  // yanıltıcı bir default değer ile taşınıyordu ama TopBar render'ında
  // bu alan HİÇBİR yerde okunmuyordu — backend status response'u
  // setStatus ile geldiğinde dahi UI'de görünmüyordu. Dashboard.jsx ve
  // AutoTrading.jsx kendi bağımsız status state'lerini tutuyor (React'ta
  // TopBar'daki state onlara prop drill olmuyor), bu yüzden alanı
  // kaldırmak başka bir bileşeni bozmaz. Dead field removal: gelecekte
  // piyasa rejimi TopBar'da gerçekten gösterilmek istenirse ayrı bir
  // state eklenir ve loading state'i için em-dash placeholder kullanılır.
  const [status, setStatus] = useState({
    engine_running: false,
    mt5_connected: false,
    phase: 'stopped',
    kill_switch_level: 0,
  });
  const [account, setAccount] = useState({
    balance: 0, equity: 0, floating_pnl: 0, daily_pnl: 0,
  });
  const [time, setTime] = useState(new Date());
  const [alwaysOnTop, setAlwaysOnTop] = useState(true);
  const [ksResetting, setKsResetting] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [agentAlive, setAgentAlive] = useState(false);
  // P2-B (2026-04-13): Üçlü mantık — true (açık), false (kapalı), null (bilinmiyor)
  // Initial state null çünkü ilk health çağrısı tamamlanana kadar durum bilinmez.
  const [tradeAllowed, setTradeAllowed] = useState(null);
  const [ogulEnabled, setOgulEnabled] = useState(false);
  const [ogulToggling, setOgulToggling] = useState(false);
  const [ogulMsg, setOgulMsg] = useState('');
  const [isMaximized, setIsMaximized] = useState(false);
  // ── v5.9: Pencere durumu kontrolü ────────────────────────────
  useEffect(() => {
    if (window.electronAPI?.windowIsMaximized) {
      window.electronAPI.windowIsMaximized().then(setIsMaximized);
    }
  }, []);

  const handleMinimize = () => window.electronAPI?.windowMinimize?.();
  const handleMaximize = async () => {
    if (window.electronAPI?.windowMaximize) {
      const maximized = await window.electronAPI.windowMaximize();
      setIsMaximized(maximized);
    }
  };
  const handleClose = () => window.electronAPI?.windowClose?.();

  // ── Saat (1sn) ─────────────────────────────────────────────────
  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  // ── Status + Account polling (2sn) ─────────────────────────────
  const fetchData = useCallback(async () => {
    const [s, a] = await Promise.all([getStatus(), getAccount()]);
    setStatus(s);
    setAccount(a);
    setOgulEnabled(s.ogul_enabled === true);
    setInitialLoading(false);
  }, []);

  // ── Agent status polling (10sn) ──────────────────────────────
  useEffect(() => {
    const checkAgent = async () => {
      const ag = await getAgentStatus();
      setAgentAlive(ag?.alive === true);
    };
    checkAgent();
    const iv = setInterval(checkAgent, 10000);
    return () => clearInterval(iv);
  }, []);

  // ── Health / trade_allowed polling (10sn) ────────────────────
  // MT5 terminalindeki "Algo Trading" butonu KAPALI ise emir gonderimi
  // retcode 10027 ile reddedilir. Kullaniciya banner ile gosterilir.
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const h = await getHealth();
        const allowed = h?.mt5?.trade_allowed;
        // P2-B: Üçlü mantık — true => trade açık, false => kapalı, null/undefined => bilinmiyor.
        // Eski "allowed !== false" davranışı fail-open idi; artık tam değeri saklıyoruz.
        if (allowed === true) setTradeAllowed(true);
        else if (allowed === false) setTradeAllowed(false);
        else setTradeAllowed(null);
      } catch {
        setTradeAllowed(null);
      }
    };
    checkHealth();
    const iv = setInterval(checkHealth, 10000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 2000);
    return () => clearInterval(iv);
  }, [fetchData]);

  // ── Always-on-top ──────────────────────────────────────────────
  useEffect(() => {
    if (window.electronAPI?.getAlwaysOnTop) {
      window.electronAPI.getAlwaysOnTop().then(setAlwaysOnTop);
    }
  }, []);

  const handleTogglePin = async () => {
    if (window.electronAPI?.toggleAlwaysOnTop) {
      const next = await window.electronAPI.toggleAlwaysOnTop();
      setAlwaysOnTop(next);
    }
  };

  // ── Kill-Switch Sıfırla ───────────────────────────────────────
  const handleKsReset = useCallback(async () => {
    if (ksResetting) return;
    setKsResetting(true);
    try {
      await acknowledgeKillSwitch(getOperatorName());
      await fetchData();
    } finally {
      setKsResetting(false);
    }
  }, [ksResetting, fetchData]);

  // ── OĞUL Motor Toggle ──────────────────────────────────────────
  const handleOgulToggle = useCallback(async () => {
    if (ogulToggling) return;
    setOgulToggling(true);
    try {
      const action = ogulEnabled ? 'disable' : 'enable';
      const res = await setOgulToggle(action);
      if (res.success) {
        setOgulEnabled(res.enabled);
        setOgulMsg('');
      } else if (res.message) {
        // Açık pozisyon varken kapatma engeli — geçici toast mesaj
        setOgulMsg(res.message);
        setTimeout(() => setOgulMsg(''), 5000);
      }
      await fetchData();
    } finally {
      setOgulToggling(false);
    }
  }, [ogulEnabled, ogulToggling, fetchData]);

  // ── Hesaplanan değerler ────────────────────────────────────────
  const phase = status.phase || 'stopped';
  const phaseLabel = PHASE_LABELS[phase] || phase.toUpperCase();
  const killLevel = status.kill_switch_level || 0;
  const fazLabel = killLevel === 0 ? '—' : `L${killLevel}`;
  const isConnected = status.mt5_connected;
  const floatingPnl = account.floating_pnl || 0;
  const dailyPnl = account.daily_pnl || 0;
  // A5/H1: Versiyon etiketini tek kaynaktan (engine/__init__.py::VERSION) oku.
  // Backend status endpoint'i full semver ("6.0.0") dondurur; V"6.0" formatini
  // korumak icin major.minor'i cikartiyoruz. Fallback "6.0" ilk render ve hata durumu icin.
  const versionLabel = (status.version || '6.0.0').split('.').slice(0, 2).join('.');

  return (
    <div className="top-bar">

      {/* ── SOL: Logo + Faz + Bağlantı ─────────────────────────── */}
      <div className="top-bar-left">
        <h1>ÜSTAT Plus <span className="version">V{versionLabel}</span></h1>
        {initialLoading && <span className="tb-loading">Yükleniyor...</span>}

        <span
          className={`tb-phase tb-phase--${phase}`}
          title={
            phase === 'running' ? 'Engine çalışıyor — sinyal üretimi ve risk kontrolü aktif' :
            phase === 'stopped' ? 'Engine durdurulmuş — işlem yapılmıyor' :
            phase === 'killed' ? 'Kill-Switch ile durdurulmuş — sıfırlama gerekli' :
            phase === 'error' ? 'Engine hata durumunda' :
            phase === 'idle' ? 'Engine hazırlanıyor' : ''
          }
        >
          {phaseLabel}
        </span>

        {phase === 'killed' && (
          <button
            className="tb-ks-reset"
            onClick={handleKsReset}
            disabled={ksResetting}
            title="Kill-Switch'i sıfırla ve sistemi yeniden başlat"
          >
            {ksResetting ? 'Sıfırlanıyor...' : 'Sıfırla'}
          </button>
        )}

        <span
          className={`tb-faz tb-faz--level${killLevel}`}
          title={
            killLevel === 0 ? 'Kill-Switch aktif değil' :
            killLevel === 1 ? 'L1 — Kontrat Durdurma: Anomali tespit edilen kontratta işlem engeli' :
            killLevel === 2 ? 'L2 — Sistem Pause: Yeni işlem açılamaz, mevcut pozisyonlar korunur' :
            killLevel === 3 ? 'L3 — Tam Kapanış: Tüm pozisyonlar kapatılır, sistem durur' : ''
          }
        >
          {fazLabel}
        </span>

        <span
          className={`tb-conn ${isConnected ? 'tb-conn--on' : 'tb-conn--off'}`}
          title={isConnected
            ? 'MT5 bağlantısı aktif — piyasa verisi ve emir iletimi çalışıyor'
            : 'MT5 bağlantısı kopuk — veri akışı ve emir iletimi durmuş'}
        >
          <span className="tb-conn-dot" />
          {isConnected ? 'MT5' : 'Bağlantı Yok'}
        </span>

        <span
          className={`tb-conn ${agentAlive ? 'tb-conn--on' : 'tb-conn--off'}`}
          title={agentAlive
            ? 'ÜSTAT Ajan aktif — Claude komutları Windows üzerinden çalıştırabilir'
            : 'ÜSTAT Ajan çalışmıyor — Windows komutları kullanılamaz'}
        >
          <span className="tb-conn-dot" />
          {agentAlive ? 'AJAN' : 'Ajan Yok'}
        </span>

        <button
          className={`tb-ogul-toggle ${ogulEnabled ? 'tb-ogul-toggle--on' : 'tb-ogul-toggle--off'}`}
          onClick={handleOgulToggle}
          disabled={ogulToggling}
          title={ogulEnabled
            ? 'OĞUL motoru AKTİF — sinyal üretimi ve emir gönderimi çalışıyor.\nTıklayarak kapatabilirsiniz.'
            : 'OĞUL motoru KAPALI — sinyal üretimi durdurulmuş.\nTıklayarak açabilirsiniz.'}
        >
          {ogulToggling ? '...' : ogulEnabled ? '🔓 OĞUL AÇIK' : '🔒 OĞUL KAPALI'}
        </button>

        {ogulMsg && (
          <span className="tb-ogul-msg" title={ogulMsg}>
            {ogulMsg}
          </span>
        )}

        {/* P2-B: Üçlü mantık — false (kırmızı) | null (gri, bilinmiyor) | true (uyarı yok) */}
        {isConnected && tradeAllowed === false && (
          <span
            className="tb-algo-warn"
            title={
              'MT5 terminalinde Algo Trading butonu KAPALI — ÜSTAT emir gönderemez.\n\n' +
              'Çözüm: MT5 penceresini açın, üstteki araç çubuğunda "Algo Trading" butonuna ' +
              'tıklayın (veya Ctrl+E). Buton yeşil olduğunda ÜSTAT otomatik tekrar devreye girer.'
            }
          >
            ⚠ ALGO KAPALI
          </span>
        )}
        {isConnected && tradeAllowed === null && (
          <span
            className="tb-algo-warn"
            style={{
              background: 'rgba(139,148,158,0.18)',
              color: '#8b949e',
              borderColor: '#484f58',
            }}
            title={
              'Algo Trading durumu BİLİNMİYOR — /api/health endpoint\'inden trade_allowed bilgisi alınamadı.\n\n' +
              'Olası nedenler: API/Engine erişilemiyor, MT5 heartbeat henüz tamamlanmadı, ' +
              'health endpoint hata döndürdü. Birkaç saniye içinde durum netleşir; sürerse logları kontrol edin.'
            }
          >
            ⚠ ALGO DURUMU BİLİNMİYOR
          </span>
        )}
      </div>

      {/* ── SAĞ: Finansal veriler + Pin + Saat ─────────────────── */}
      <div className="top-bar-right">

        <div className="tb-metric">
          <span className="tb-metric-label">Bakiye</span>
          <span className="tb-metric-value">{formatMoney(account.balance)}</span>
        </div>

        <div className="tb-divider" />

        <div className="tb-metric">
          <span className="tb-metric-label">Equity</span>
          <span className="tb-metric-value">{formatMoney(account.equity)}</span>
        </div>

        <div className="tb-divider" />

        <div className="tb-metric">
          <span className="tb-metric-label">Floating</span>
          <span className={`tb-metric-value ${floatingPnl >= 0 ? 'profit' : 'loss'}`}>
            {formatMoney(floatingPnl)}
          </span>
        </div>

        <div className="tb-divider" />

        {/* Widget Denetimi A10 fix — etiket "MT5" değil "Snapshot" çünkü
            veri api/routes/account.py::get_account → db.get_latest_risk_snapshot()
            üzerinden risk_snapshots tablosundan okunuyor, doğrudan MT5'ten değil. */}
        <div className="tb-metric" title="Günlük P/L — risk_snapshots tablosundan (2 sn polling)">
          <span className="tb-metric-label">Günlük K/Z (Snapshot)</span>
          <span className={`tb-metric-value ${dailyPnl >= 0 ? 'profit' : 'loss'}`}>
            {formatMoney(dailyPnl)}
          </span>
        </div>

        <div className="tb-divider" />

        <button
          className={`pin-btn ${alwaysOnTop ? 'pinned' : ''}`}
          onClick={handleTogglePin}
          title={alwaysOnTop ? 'Always on top: AÇIK' : 'Always on top: KAPALI'}
        >
          {alwaysOnTop ? '📌' : '📍'}
        </button>

        <span className="clock">
          {time.toLocaleString('tr-TR', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
          })}
        </span>

        {/* Native titleBarOverlay butonları için boşluk (140px) */}
        <div style={{ width: 140, flexShrink: 0 }} />
      </div>
    </div>
  );
}
