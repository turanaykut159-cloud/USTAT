/**
 * ÜSTAT v5.9 — Üst bilgi çubuğu.
 *
 * Sol:  ÜSTAT v5.9 logosu | Kill-switch (L1/L2/L3) | Bağlantı durumu (yeşil/kırmızı nokta)
 * Sağ:  Bakiye | Equity | Floating | Günlük K/Z (MT5, 2sn) | Pin | Saat
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { getStatus, getAccount, acknowledgeKillSwitch, getAgentStatus } from '../services/api';
import { formatMoney } from '../utils/formatters';

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
  const [status, setStatus] = useState({
    engine_running: false,
    mt5_connected: false,
    regime: 'TREND',
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
      await acknowledgeKillSwitch('operator');
      await fetchData();
    } finally {
      setKsResetting(false);
    }
  }, [ksResetting, fetchData]);

  // ── Hesaplanan değerler ────────────────────────────────────────
  const phase = status.phase || 'stopped';
  const phaseLabel = PHASE_LABELS[phase] || phase.toUpperCase();
  const killLevel = status.kill_switch_level || 0;
  const fazLabel = killLevel === 0 ? '—' : `L${killLevel}`;
  const isConnected = status.mt5_connected;
  const floatingPnl = account.floating_pnl || 0;
  const dailyPnl = account.daily_pnl || 0;

  return (
    <div className="top-bar">

      {/* ── SOL: Logo + Faz + Bağlantı ─────────────────────────── */}
      <div className="top-bar-left">
        <h1>ÜSTAT <span className="version">v5.9</span></h1>
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

        <div className="tb-metric" title="MT5 günlük P/L (gerçek zamanlı)">
          <span className="tb-metric-label">Günlük K/Z (MT5)</span>
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
