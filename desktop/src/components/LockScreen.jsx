/**
 * ÜSTAT v5.0 — Kilit / Bekleme Ekranı.
 *
 * Akış (fire-and-forget MT5 başlatma + polling doğrulama):
 *   CHECKING    → kayıtlı credential kontrol
 *   CREDENTIALS → ilk giriş / farklı hesap formu
 *   WAITING     → MT5 arka planda başlatıldı + "MT5'e OTP kodunuzu girin" mesajı
 *                 + arka planda mt5.initialize() polling (3sn aralık, 120sn timeout)
 *   CONNECTED   → Başarılı! → onUnlock() → Dashboard
 *   ERROR       → hata + yeniden dene
 *
 * OTP iki yolla girilebilir:
 *   a) Kullanıcı OTP'yi bu ekrandaki inputa girer → admin Python ile MT5 dialoguna iletilir
 *   b) Kullanıcı OTP'yi doğrudan MT5'in kendi dialoguna girer
 * Her iki durumda da arka planda mt5.initialize() polling ile bağlantı kontrol edilir.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  MT5LauncherState,
  checkSavedCredentials,
  clearSavedCredentials,
  launchWithCredentials,
  verifyMT5Connection,
  sendOTP,
} from '../services/mt5Launcher';

// ── Polling sabitleri ────────────────────────────────────────────
const POLL_INTERVAL = 3000;   // 3 saniyede bir kontrol
const POLL_TIMEOUT = 120000;  // 120 saniye max bekleme

// ── Bağlantı durumu enum'u ───────────────────────────────────────
const ConnectionStatus = {
  IDLE: 'idle',
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  ERROR: 'error',
};

export default function LockScreen({ onUnlock }) {
  // ── State ──────────────────────────────────────────────────────
  const [step, setStep] = useState(MT5LauncherState.CHECKING);
  const [connStatus, setConnStatus] = useState(ConnectionStatus.IDLE);
  const [error, setError] = useState('');
  const [statusMsg, setStatusMsg] = useState('Başlatılıyor...');

  // Credential
  const [server, setServer] = useState('');
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [savedInfo, setSavedInfo] = useState(null); // { server, login, passwordMask }

  // OTP gönderme
  const [otpCode, setOtpCode] = useState('');
  const [otpSending, setOtpSending] = useState(false);
  const [otpResult, setOtpResult] = useState(null); // { success, message }

  // Polling
  const [elapsed, setElapsed] = useState(0); // geçen süre (saniye)

  const serverRef = useRef(null);
  const otpInputRef = useRef(null);
  const pollingRef = useRef(false); // polling aktif mi

  // ── Başlangıç ─────────────────────────────────────────────────
  const initFlow = useCallback(async () => {
    setStep(MT5LauncherState.CHECKING);
    setConnStatus(ConnectionStatus.CONNECTING);
    setError('');
    setStatusMsg('Hesap bilgileri kontrol ediliyor...');

    const saved = await checkSavedCredentials();

    if (saved.hasSaved) {
      setSavedInfo(saved);
      setServer(saved.server);
      setLogin(saved.login);
      // Fire-and-forget MT5 başlat + hemen WAITING adımına geç
      await doLaunch(null, saved);
    } else {
      setStep(MT5LauncherState.CREDENTIALS);
      setConnStatus(ConnectionStatus.IDLE);
      setStatusMsg('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { initFlow(); }, [initFlow]);

  // ── Focus yönetimi ────────────────────────────────────────────
  useEffect(() => {
    if (step === MT5LauncherState.CREDENTIALS && serverRef.current && !savedInfo) {
      serverRef.current.focus();
    }
    if (step === MT5LauncherState.WAITING && otpInputRef.current) {
      otpInputRef.current.focus();
    }
  }, [step, savedInfo]);

  // ── Polling: WAITING adımında mt5.initialize() kontrolü ───────
  useEffect(() => {
    if (step !== MT5LauncherState.WAITING) {
      pollingRef.current = false;
      return;
    }

    pollingRef.current = true;
    setElapsed(0);
    const startTime = Date.now();

    const timer = setInterval(async () => {
      if (!pollingRef.current) {
        clearInterval(timer);
        return;
      }

      // Geçen süreyi güncelle
      const secs = Math.floor((Date.now() - startTime) / 1000);
      setElapsed(secs);

      // Timeout kontrolü
      if (Date.now() - startTime > POLL_TIMEOUT) {
        clearInterval(timer);
        pollingRef.current = false;
        setStep(MT5LauncherState.ERROR);
        setConnStatus(ConnectionStatus.ERROR);
        setError('MT5 bağlantısı 120 saniye içinde kurulamadı. OTP\'yi girip tekrar deneyin.');
        setStatusMsg('');
        return;
      }

      // mt5.initialize() + account_info() kontrolü
      try {
        const result = await verifyMT5Connection();

        if (result.connected) {
          clearInterval(timer);
          pollingRef.current = false;
          setConnStatus(ConnectionStatus.CONNECTED);
          setStatusMsg('Bağlantı başarılı!');
          setTimeout(() => onUnlock(), 800);
        }
      } catch (err) {
        // Hata olursa sessizce devam et (polling sürsün)
        console.log('[LockScreen] Polling hatası:', err.message);
      }
    }, POLL_INTERVAL);

    return () => {
      clearInterval(timer);
      pollingRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  // ── MT5 Başlat (fire-and-forget → hemen WAITING) ──────────────
  async function doLaunch(creds, info) {
    setConnStatus(ConnectionStatus.CONNECTING);
    setError('');
    setStatusMsg('MT5 arka planda başlatılıyor...');

    const result = await launchWithCredentials(creds || {});

    if (result.alreadyConnected) {
      // MT5 zaten çalışıyor ve bağlı — direkt dashboard'a geç
      setConnStatus(ConnectionStatus.CONNECTED);
      setStatusMsg('MT5 zaten bağlı!');
      setTimeout(() => onUnlock(), 800);
    } else if (result.success) {
      // MT5 arka planda başlatıldı (fire-and-forget)
      // Hemen WAITING adımına geç — polling başlayacak
      setStep(MT5LauncherState.WAITING);
      setConnStatus(ConnectionStatus.CONNECTING);
      setStatusMsg('MT5\'e OTP kodunuzu girin');
    } else if (result.needsCredentials) {
      setStep(MT5LauncherState.CREDENTIALS);
      setConnStatus(ConnectionStatus.IDLE);
      setStatusMsg('');
      setError('Kayıtlı hesap bilgileri geçersiz. Yeniden girin.');
    } else {
      setStep(MT5LauncherState.ERROR);
      setConnStatus(ConnectionStatus.ERROR);
      setError(result.message || 'MT5 başlatılamadı.');
      setStatusMsg('');
    }
  }

  // ── OTP Gönder ───────────────────────────────────────────────
  async function handleOTPSubmit(e) {
    e.preventDefault();
    const code = otpCode.trim();

    if (!code || !/^\d{4,8}$/.test(code)) {
      setOtpResult({ success: false, message: '4-8 haneli OTP kodu girin.' });
      return;
    }

    setOtpSending(true);
    setOtpResult(null);

    try {
      const result = await sendOTP(code);
      setOtpResult(result);

      if (result.success) {
        setOtpCode('');
        // Polling zaten çalışıyor, bağlantı algılanınca dashboard'a geçecek
      }
    } catch (err) {
      setOtpResult({ success: false, message: err.message });
    } finally {
      setOtpSending(false);
    }
  }

  // ── Credential submit ─────────────────────────────────────────
  async function handleCredentialSubmit(e) {
    e.preventDefault();
    setError('');

    if (!server.trim()) { setError('Sunucu adı gerekli.'); return; }
    if (!login.trim()) { setError('Hesap numarası gerekli.'); return; }
    if (!password.trim()) { setError('Şifre gerekli.'); return; }

    const creds = {
      server: server.trim(),
      login: login.trim(),
      password: password.trim(),
    };

    const info = {
      hasSaved: true,
      server: creds.server,
      login: creds.login,
      passwordMask: '******',
    };
    setSavedInfo(info);
    setPassword('');
    await doLaunch(creds, info);
  }

  // ── Farklı Hesap ──────────────────────────────────────────────
  async function handleSwitchAccount() {
    pollingRef.current = false; // polling'i durdur
    await clearSavedCredentials();
    setSavedInfo(null);
    setServer('');
    setLogin('');
    setPassword('');
    setError('');
    setElapsed(0);
    setConnStatus(ConnectionStatus.IDLE);
    setStatusMsg('');
    setStep(MT5LauncherState.CREDENTIALS);
  }

  // ── Bağlantı durumu badge renk/metin ──────────────────────────
  function getConnectionBadge() {
    switch (connStatus) {
      case ConnectionStatus.CONNECTING:
        return { className: 'conn-badge connecting', text: 'MT5\'e bağlanıyor...' };
      case ConnectionStatus.CONNECTED:
        return { className: 'conn-badge connected', text: 'Bağlandı' };
      case ConnectionStatus.ERROR:
        return { className: 'conn-badge error', text: 'Bağlantı Hatası' };
      default:
        return null;
    }
  }

  const badge = getConnectionBadge();

  // ── Render ────────────────────────────────────────────────────
  return (
    <div className="lock-screen">

      {/* ── Logo ─────────────────────────────────────────────────── */}
      <div className="lock-logo">
        <h1>ÜSTAT <span className="version">v5.0</span></h1>
        <p className="lock-tagline">VİOP Algorithmic Trading</p>
      </div>

      {/* ── Bağlantı durumu göstergesi ───────────────────────────── */}
      {badge && (
        <div className={badge.className}>
          <span className="conn-dot" />
          {badge.text}
        </div>
      )}

      {/* ── CHECKING: Spinner ────────────────────────────────────── */}
      {step === MT5LauncherState.CHECKING && (
        <div className="lock-status">
          <div className="spinner" />
          <p className="status-msg">{statusMsg}</p>
        </div>
      )}

      {/* ── CREDENTIALS: Giriş formu ─────────────────────────────── */}
      {step === MT5LauncherState.CREDENTIALS && (
        <div className="lock-credentials">
          <p className="lock-subtitle">MT5 hesap bilgilerinizi girin</p>

          <form onSubmit={handleCredentialSubmit} className="credentials-form">
            <label>
              <span>Sunucu Adı</span>
              <input
                ref={serverRef}
                type="text"
                value={server}
                onChange={(e) => setServer(e.target.value)}
                placeholder="Örn: Broker-Demo"
              />
            </label>

            <label>
              <span>Hesap No</span>
              <input
                type="text"
                value={login}
                onChange={(e) => setLogin(e.target.value)}
                placeholder="Örn: 12345678"
              />
            </label>

            <label>
              <span>Şifre</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="******"
              />
            </label>

            {error && <p className="error">{error}</p>}

            <button type="submit" className="btn-primary">Bağlan</button>
          </form>
        </div>
      )}

      {/* ── WAITING: Hesap kartı + OTP bekleme mesajı + polling ───── */}
      {step === MT5LauncherState.WAITING && (
        <div className="lock-otp-section">

          {/* Hesap bilgileri kartı */}
          {savedInfo && (
            <div className="account-card">
              <div className="account-row">
                <span className="account-label">Sunucu Adı</span>
                <span className="account-value">{savedInfo.server}</span>
              </div>
              <div className="account-row">
                <span className="account-label">Hesap No</span>
                <span className="account-value">{savedInfo.login}</span>
              </div>
              <div className="account-row">
                <span className="account-label">Şifre</span>
                <span className="account-value mask">{savedInfo.passwordMask || '******'}</span>
              </div>
              <button
                type="button"
                className="btn-link account-switch"
                onClick={handleSwitchAccount}
              >
                Farklı Hesap
              </button>
            </div>
          )}

          {/* OTP giriş formu + polling durumu */}
          <div className="otp-waiting">
            <p className="status-msg otp-msg">OTP Kodunuzu Girin</p>

            <form onSubmit={handleOTPSubmit} className="otp-form">
              <input
                ref={otpInputRef}
                type="text"
                inputMode="numeric"
                className="otp-input"
                value={otpCode}
                onChange={(e) => {
                  // Sadece rakam kabul et
                  const val = e.target.value.replace(/\D/g, '').slice(0, 8);
                  setOtpCode(val);
                  setOtpResult(null);
                }}
                placeholder="••••••"
                maxLength={8}
                autoComplete="one-time-code"
                disabled={otpSending}
              />
              <button
                type="submit"
                className="btn-primary"
                disabled={otpSending || otpCode.trim().length < 4}
              >
                {otpSending ? 'Gönderiliyor...' : 'OTP Gönder'}
              </button>
            </form>

            {/* OTP sonuç mesajı */}
            {otpResult && (
              <p className={otpResult.success ? 'otp-success' : 'error'}>
                {otpResult.message}
              </p>
            )}

            <p className="otp-hint">
              OTP kodunu buraya girin, MT5&apos;e otomatik iletilecektir.
              <br />
              Alternatif: MT5 penceresine doğrudan da girebilirsiniz.
            </p>

            {/* Polling durumu */}
            <div className="otp-polling-status">
              <div className="spinner spinner-small" />
              <span className="elapsed-time">
                MT5 bağlantısı bekleniyor... {elapsed > 0 ? `${elapsed}sn` : ''}
              </span>
            </div>
          </div>

          {error && <p className="error">{error}</p>}
        </div>
      )}

      {/* ── ERROR: Hata durumu ────────────────────────────────────── */}
      {step === MT5LauncherState.ERROR && (
        <div className="lock-error">
          <p className="error">{error}</p>
          <div className="lock-error-actions">
            <button type="button" className="btn-primary" onClick={initFlow}>
              Tekrar Dene
            </button>
            <button type="button" className="btn-link" onClick={handleSwitchAccount}>
              Farklı Hesap
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
