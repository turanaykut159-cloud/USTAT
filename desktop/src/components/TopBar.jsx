/**
 * ÜSTAT v5.0 — Üst bilgi çubuğu.
 *
 * Sol:  ÜSTAT v5.0 logosu | Faz göstergesi (FAZ 0–3) | Bağlantı durumu (yeşil/kırmızı nokta)
 * Sağ:  Bakiye | Equity | Floating | Günlük K/Z (canlı, 2sn güncelleme) | Pin | Saat
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { getStatus, getAccount, acknowledgeKillSwitch } from '../services/api';

// ── Faz etiketleri ──────────────────────────────────────────────
const PHASE_LABELS = {
  running: 'AKTIF',
  stopped: 'PASIF',
  killed:  'DURDURULDU',
  error:   'HATA',
  idle:    'BEKLEMEDE',
};

// ── Para formatı ────────────────────────────────────────────────
function formatMoney(val) {
  if (val == null || isNaN(val)) return '—';
  const abs = Math.abs(val);
  const formatted = abs.toLocaleString('tr-TR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return val < 0 ? `-${formatted}` : formatted;
}

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
  const fazLabel = `FAZ ${killLevel}`;
  const isConnected = status.mt5_connected;
  const floatingPnl = account.floating_pnl || 0;
  const dailyPnl = account.daily_pnl || 0;

  return (
    <div className="top-bar">

      {/* ── SOL: Logo + Faz + Bağlantı ─────────────────────────── */}
      <div className="top-bar-left">
        <h1>ÜSTAT <span className="version">v5.0</span></h1>

        <span className={`tb-phase tb-phase--${phase}`}>
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

        <span className={`tb-faz tb-faz--level${killLevel}`}>
          {fazLabel}
        </span>

        <span className={`tb-conn ${isConnected ? 'tb-conn--on' : 'tb-conn--off'}`}>
          <span className="tb-conn-dot" />
          {isConnected ? 'MT5' : 'Bağlantı Yok'}
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

        <div className="tb-metric">
          <span className="tb-metric-label">Günlük K/Z</span>
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

        <span className="clock">{time.toLocaleTimeString('tr-TR')}</span>
      </div>
    </div>
  );
}
