/**
 * ÜSTAT v5.7 — Sol dikey navigasyon menüsü.
 *
 * 6 sayfa linki (ikonlu) + Güvenli Kapat (2 adım doğrulama) + Kill-Switch (en altta, kırmızı, 2s basılı tutma).
 */

import React, { useState, useRef, useCallback, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { activateKillSwitch, getUiPrefs } from '../services/api';
import ConfirmModal from './ConfirmModal';

// ── Menü öğeleri ─────────────────────────────────────────────────
const NAV_ITEMS = [
  { path: '/',            label: 'Dashboard',          icon: '📊' },
  { path: '/manual',      label: 'Manuel İşlem Paneli', icon: '🎯' },
  { path: '/hybrid',      label: 'Hibrit İşlem Paneli',  icon: '🔀' },
  { path: '/auto',        label: 'Otomatik İşlem Paneli', icon: '🤖' },
  { path: '/trades',      label: 'İşlem Geçmişi',     icon: '📋' },
  { path: '/performance', label: 'Performans',          icon: '🏆' },
  { path: '/ustat',       label: 'ÜSTAT',               icon: '🧠' },
  { path: '/risk',        label: 'Risk Yönetimi',      icon: '🛡️' },
  { path: '/monitor',     label: 'System Monitor',      icon: '📡' },
  { path: '/errors',      label: 'Hata Takip',          icon: '🔍' },
  { path: '/nabiz',       label: 'NABIZ',               icon: '💓' },
  { path: '/settings',    label: 'Ayarlar',            icon: '⚙️' },
];

// Kill-switch basılı tutma süresi (ms) — fallback.
// Widget Denetimi A19 / H5: Gerçek değer backend config/default.json::ui.kill_hold_ms
// üzerinden GET /settings/ui-prefs endpoint'inden mount'ta çekilir. Config
// okunamazsa bu sabit fallback olarak kullanılır. Kritik koruma parametresi:
// kullanıcının yanlışlıkla kill-switch tetiklemesini engelleyen çift aşamalı
// koruma (basılı tutma + progress animasyonu) için minimum süre.
const DEFAULT_KILL_HOLD_MS = 2000;

export default function SideNav() {
  // ── Kill-Switch state ──────────────────────────────────────────
  const [killHolding, setKillHolding] = useState(false);
  const [killProgress, setKillProgress] = useState(0);
  const [killFired, setKillFired] = useState(false);
  // Widget Denetimi A19 — kill_hold_ms state'i: mount'ta backend'den çekilir.
  const [killHoldMs, setKillHoldMs] = useState(DEFAULT_KILL_HOLD_MS);
  const holdTimerRef = useRef(null);
  const progressRef = useRef(null);
  const holdStartRef = useRef(0);

  // ── UI prefs fetch (mount'ta bir kez, A19) ─────────────────────
  useEffect(() => {
    let cancelled = false;
    getUiPrefs().then((prefs) => {
      if (cancelled) return;
      const val = Number(prefs?.kill_hold_ms);
      // Güvenlik koruması: geçersiz veya sıra dışı değer gelirse fallback.
      if (Number.isFinite(val) && val >= 500 && val <= 10000) {
        setKillHoldMs(val);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Güvenli Kapat modal (2 adım + hata mesajı) ─────────────────
  const [safeQuitStep, setSafeQuitStep] = useState(null);
  const [alertMessage, setAlertMessage] = useState(null);

  // ── Kill-Switch basılı tutma başlat ────────────────────────────
  const handleKillDown = useCallback(() => {
    if (killFired) return;

    setKillHolding(true);
    setKillProgress(0);
    holdStartRef.current = Date.now();

    // İlerleme animasyonu (60fps)
    progressRef.current = setInterval(() => {
      const elapsed = Date.now() - holdStartRef.current;
      const pct = Math.min(elapsed / killHoldMs, 1);
      setKillProgress(pct);
    }, 16);

    // killHoldMs süresi sonunda tetikle (A19 — config'den okunur)
    holdTimerRef.current = setTimeout(async () => {
      clearInterval(progressRef.current);
      setKillProgress(1);
      setKillHolding(false);
      setKillFired(true);

      await activateKillSwitch('operator');

      // 3 saniye sonra butonu sıfırla
      setTimeout(() => setKillFired(false), 3000);
    }, killHoldMs);
  }, [killFired, killHoldMs]);

  // ── Güvenli Kapat: ilk tıklamada 1. modalı aç ─────────────────────
  const handleSafeQuit = useCallback(() => {
    setSafeQuitStep(1);
  }, []);

  // ── 1. adım onayı → 2. modalı göster ───────────────────────────
  const handleSafeQuitStep1Confirm = useCallback(() => {
    setSafeQuitStep(2);
  }, []);

  // ── 2. adım onayı → gerçek kapatma ─────────────────────────────
  const handleSafeQuitStep2Confirm = useCallback(async () => {
    setSafeQuitStep(null);
    try {
      if (typeof window.electronAPI?.safeQuit === 'function') {
        await window.electronAPI.safeQuit();
      } else {
        setAlertMessage('Güvenli kapatma kullanılamıyor. Lütfen sistem tepsisindeki ÜSTAT ikonuna sağ tıklayıp "Çıkış" seçin.');
      }
    } catch (err) {
      setAlertMessage('Kapatma sırasında hata: ' + (err?.message || String(err)));
    }
  }, []);

  const handleSafeQuitCancel = useCallback(() => {
    setSafeQuitStep(null);
  }, []);

  const handleAlertClose = useCallback(() => {
    setAlertMessage(null);
  }, []);

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
    <>
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

      {/* ── Güvenli Kapat + Kill-Switch (en altta) ───────────────── */}
      <div className="side-nav-bottom">
        <button
          type="button"
          className="safe-quit-btn"
          onClick={handleSafeQuit}
          title="Uygulamayı tamamen kapat (2 adım doğrulama)"
        >
          <span className="safe-quit-icon">🚪</span>
          <span className="safe-quit-label">Güvenli Kapat</span>
        </button>

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

    {/* ── Güvenli Kapat: 1. adım ────────────────────────────────── */}
    <ConfirmModal
      open={safeQuitStep === 1}
      title="Güvenli Kapat"
      message={'ÜSTAT tamamen kapatılacak (arka plan dahil). API ve motor duracak, MT5 açma sinyali gönderilmez.\n\nDevam etmek istiyor musunuz?'}
      confirmLabel="Devam Et"
      cancelLabel="İptal"
      variant="warning"
      onConfirm={handleSafeQuitStep1Confirm}
      onCancel={handleSafeQuitCancel}
    />

    {/* ── Güvenli Kapat: 2. adım (son onay) ──────────────────────── */}
    <ConfirmModal
      open={safeQuitStep === 2}
      title="Son onay"
      message="Uygulama kapatılsın mı?"
      confirmLabel="Kapat"
      cancelLabel="İptal"
      variant="warning"
      onConfirm={handleSafeQuitStep2Confirm}
      onCancel={handleSafeQuitCancel}
    />

    {/* ── Hata / bilgi mesajı (tek buton) ────────────────────────── */}
    <ConfirmModal
      open={!!alertMessage}
      title="Bilgi"
      message={alertMessage || ''}
      confirmLabel="Tamam"
      cancelLabel={null}
      variant="primary"
      onConfirm={handleAlertClose}
    />
    </>
  );
}
