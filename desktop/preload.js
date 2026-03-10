/**
 * ÜSTAT v5.4 Desktop — Electron preload script.
 * Güvenli IPC köprüsü sağlar (contextIsolation + sandbox).
 *
 * Renderer tarafında window.electronAPI üzerinden erişilir.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // ── Pencere işlemleri ──────────────────────────────────────────
  toggleAlwaysOnTop: () => ipcRenderer.invoke('window:toggleAlwaysOnTop'),
  getAlwaysOnTop: () => ipcRenderer.invoke('window:getAlwaysOnTop'),
  setAlwaysOnTop: (value) => ipcRenderer.invoke('window:setAlwaysOnTop', !!value),

  // ── MT5 Başlatma & Durum ───────────────────────────────────────
  /**
   * MT5'i credentials ile başlat.
   * @param {{ server: string, login: string, password: string }} creds
   * @returns {Promise<{ success: boolean, message: string, needsCredentials?: boolean }>}
   */
  launchMT5: (creds) => ipcRenderer.invoke('mt5:launch', creds),

  /**
   * MT5 durum bilgisi al.
   * @returns {Promise<{ running: boolean, hasSaved: boolean, server?: string, login?: string }>}
   */
  getMT5Status: () => ipcRenderer.invoke('mt5:status'),

  /**
   * Kaydedilmiş credential'ları al (şifre maskeli).
   * @returns {Promise<{ hasSaved: boolean, server?: string, login?: string, passwordMask?: string }>}
   */
  getSavedCredentials: () => ipcRenderer.invoke('mt5:getSavedCredentials'),

  /**
   * Kaydedilmiş credential'ları sil.
   * @returns {Promise<boolean>}
   */
  clearCredentials: () => ipcRenderer.invoke('mt5:clearCredentials'),

  // ── MT5 OTP Gönderme ──────────────────────────────────────────────
  /**
   * OTP kodunu MT5 dialog'una gönder (admin Python ile).
   * @param {string} otpCode - 6 haneli OTP kodu
   * @returns {Promise<{ success: boolean, message: string }>}
   */
  sendOTP: (otpCode) => ipcRenderer.invoke('mt5:sendOTP', otpCode),

  // ── MT5 Bağlantı Doğrulama ────────────────────────────────────
  /**
   * MT5 bağlantısını Python MetaTrader5 ile doğrula.
   * @returns {Promise<{ connected: boolean, account?: object, message: string }>}
   */
  verifyMT5Connection: () => ipcRenderer.invoke('mt5:verify'),

  // ── Güvenli kapat (doğrulama sonrası renderer'dan çağrılır) ───────
  /**
   * Uygulamayı tamamen kapatır (pencere + tray + API process).
   * Önce UI'da 2 adım doğrulama yapılmalı.
   */
  safeQuit: () => ipcRenderer.invoke('app:safeQuit'),

  /**
   * Pencere öne getirildiğinde OTP alanına focus verilsin diye main'den gönderilir.
   * Sadece LockScreen (WAITING adımında) dinler; callback'te otpInputRef.current.focus() yapılır.
   * @param {() => void} callback
   * @returns {() => void} Listener'ı kaldırmak için çağrılacak fonksiyon
   */
  onFocusOTPInputRequested: (callback) => {
    const handler = () => callback();
    ipcRenderer.on('window:focusOTPInput', handler);
    return () => ipcRenderer.removeListener('window:focusOTPInput', handler);
  },
});
