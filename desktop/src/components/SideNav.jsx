/**
 * ÜSTAT v5.0 — Sol dikey navigasyon menüsü.
 *
 * 6 sayfa linki (ikonlu) + Kill-Switch butonu (en altta, kırmızı, 2s basılı tutma).
 */

import React, { useState, useRef, useCallback } from 'react';
import { NavLink } from 'react-router-dom';
import { activateKillSwitch } from '../services/api';

// ── Menü öğeleri ─────────────────────────────────────────────────
const NAV_ITEMS = [
  { path: '/',            label: 'Dashboard',          icon: '📊' },
  { path: '/manual',      label: 'İşlem Paneli',       icon: '🎯' },
  { path: '/trades',      label: 'İşlem Geçmişi',     icon: '📋' },
  { path: '/positions',   label: 'Açık Pozisyonlar',   icon: '📈' },
  { path: '/performance', label: 'Performans Analizi', icon: '🏆' },
  { path: '/risk',        label: 'Risk Yönetimi',      icon: '🛡️' },
  { path: '/settings',    label: 'Ayarlar',            icon: '⚙️' },
];

// Kill-switch basılı tutma süresi (ms)
const KILL_HOLD_DURATION = 2000;

export default function SideNav() {
  // ── Kill-Switch state ──────────────────────────────────────────
  const [killHolding, setKillHolding] = useState(false);
  const [killProgress, setKillProgress] = useState(0);
  const [killFired, setKillFired] = useState(false);
  const holdTimerRef = useRef(null);
  const progressRef = useRef(null);
  const holdStartRef = useRef(0);

  // ── Kill-Switch basılı tutma başlat ────────────────────────────
  const handleKillDown = useCallback(() => {
    if (killFired) return;

    setKillHolding(true);
    setKillProgress(0);
    holdStartRef.current = Date.now();

    // İlerleme animasyonu (60fps)
    progressRef.current = setInterval(() => {
      const elapsed = Date.now() - holdStartRef.current;
      const pct = Math.min(elapsed / KILL_HOLD_DURATION, 1);
      setKillProgress(pct);
    }, 16);

    // 2 saniye sonunda tetikle
    holdTimerRef.current = setTimeout(async () => {
      clearInterval(progressRef.current);
      setKillProgress(1);
      setKillHolding(false);
      setKillFired(true);

      await activateKillSwitch('operator');

      // 3 saniye sonra butonu sıfırla
      setTimeout(() => setKillFired(false), 3000);
    }, KILL_HOLD_DURATION);
  }, [killFired]);

  // ── Kill-Switch bırakma (erken) ────────────────────────────────
  const handleKillUp = useCallback(() => {
    if (holdTimerRef.current) {
      clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }
    if (progressRef.current) {
      clearInterval(progressRef.current);
      progressRef.current = null;
    }
    setKillHolding(false);
    setKillProgress(0);
  }, []);

  return (
    <nav className="side-nav">
      {/* ── Navigasyon linkleri ─────────────────────────────────── */}
      <ul className="side-nav-links">
        {NAV_ITEMS.map((item) => (
          <li key={item.path}>
            <NavLink
              to={item.path}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      {/* ── Kill-Switch butonu (en altta) ──────────────────────── */}
      <div className="side-nav-bottom">
        <button
          className={`kill-switch-btn ${killHolding ? 'holding' : ''} ${killFired ? 'fired' : ''}`}
          onMouseDown={handleKillDown}
          onMouseUp={handleKillUp}
          onMouseLeave={handleKillUp}
          onTouchStart={handleKillDown}
          onTouchEnd={handleKillUp}
          disabled={killFired}
          title="Kill-Switch: 2 saniye basılı tutun"
        >
          {/* İlerleme çubuğu (arka plan) */}
          {killHolding && (
            <span
              className="kill-progress"
              style={{ width: `${killProgress * 100}%` }}
            />
          )}

          <span className="kill-icon">⛔</span>
          <span className="kill-label">
            {killFired ? 'DURDURULDU!' : killHolding ? 'Basılı tutun...' : 'Kill-Switch'}
          </span>
        </button>
      </div>
    </nav>
  );
}
