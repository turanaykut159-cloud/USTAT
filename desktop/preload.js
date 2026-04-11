/**
 * ÜSTAT Plus V6.0 Desktop — Electron preload script.
 * Güvenli IPC köprüsü sağlar (contextIsolation + sandbox).
 *
 * Renderer tarafında window.electronAPI üzerinden erişilir.
 */

const { contextBridge, ipcRenderer } = require('electron');

// ── v14.1: Renderer hata yakalama — main process'e ilet ─────────
// Bu handler'lar renderer process'te oluşan tüm yakalanmamış hataları
// main process'teki electron.log'a yazar.
window.addEventListener('error', (event) => {
  try {
    ipcRenderer.send('renderer:log', 'ERROR',
      `Uncaught: ${event.message} at ${event.filename}:${event.lineno}:${event.colno}`);
  } catch { /* preload henüz hazır değilse yoksay */ }
});

window.addEventListener('unhandledrejection', (event) => {
  try {
    const reason = event.reason?.stack || event.reason?.message || String(event.reason);
    ipcRenderer.send('renderer:log', 'REJECTION', `Unhandled Promise: ${reason}`);
  } catch { /* yoksay */ }
});

contextBridge.exposeInMainWorld('electronAPI', {
  // ── Pencere kontrol (v5.9 frameless titlebar) ─────────────────
  windowMinimize: () => ipcRenderer.invoke('window:minimize'),
  windowMaximize: () => ipcRenderer.invoke('window:maximize'),
  windowClose: () => ipcRenderer.invoke('window:close'),
  windowIsMaximized: () => ipcRenderer.invoke('window:isMaximized'),

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

  // ── v14.1: Renderer → Main log forwarding ─────────────────────
  /**
   * Renderer tarafından main process'e log gönder.
   * electron.log'a yazılır. Seviye: ERROR, WARN, INFO
   * @param {'ERROR'|'WARN'|'INFO'} level
   * @param {string} message
   */
  logToMain: (level, message) => {
    ipcRenderer.send('renderer:log', level, message);
  },

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
