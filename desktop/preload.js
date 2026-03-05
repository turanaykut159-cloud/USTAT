/**
 * ÜSTAT v5.1 Desktop — Electron preload script.
 * Güvenli IPC köprüsü sağlar (contextIsolation + sandbox).
 *
 * Renderer tarafında window.electronAPI üzerinden erişilir.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // ── Pencere işlemleri ──────────────────────────────────────────
  toggleAlwaysOnTop: () => ipcRenderer.invoke('window:toggleAlwaysOnTop'),
  getAlwaysOnTop: () => ipcRenderer.invoke('window:getAlwaysOnTop'),

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

  /**
   * MT5 pencere durumunu kontrol et.
   * @returns {Promise<{ mt5_found: boolean, otp_dialog: boolean }>}
   */
  checkMT5Window: () => ipcRenderer.invoke('mt5:checkWindow'),

  // ── Engine işlemleri ───────────────────────────────────────────
  getEngineStatus: () => ipcRenderer.invoke('engine:status'),
  startEngine: () => ipcRenderer.invoke('engine:start'),
  stopEngine: () => ipcRenderer.invoke('engine:stop'),

  // ── Güvenli kapat (doğrulama sonrası renderer'dan çağrılır) ───────
  /**
   * Uygulamayı tamamen kapatır (pencere + tray + API process).
   * Önce UI'da 2 adım doğrulama yapılmalı.
   */
  safeQuit: () => ipcRenderer.invoke('app:safeQuit'),

  // ── Event dinleyicileri ────────────────────────────────────────
  onTradeUpdate: (callback) => {
    ipcRenderer.on('trade:update', (_, data) => callback(data));
  },
  onStatusChange: (callback) => {
    ipcRenderer.on('status:change', (_, data) => callback(data));
  },
  onMT5StatusChange: (callback) => {
    ipcRenderer.on('mt5:statusChange', (_, data) => callback(data));
  },
});
