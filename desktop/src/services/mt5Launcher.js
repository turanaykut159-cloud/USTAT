/**
 * ÜSTAT v5.1 — MT5 Launcher Service (Renderer tarafı).
 *
 * Electron preload IPC köprüsü üzerinden main process ile iletişim kurar.
 * State machine: IDLE → CHECKING → CREDENTIALS → LAUNCHING → WAITING → CONNECTED
 *
 * WAITING aşamasında:
 *   - Kullanıcıya "MT5'e OTP kodunuzu girin" mesajı gösterilir
 *   - Arka planda mt5.initialize() polling yapılır (3sn aralık, 120sn timeout)
 *   - Kullanıcı OTP'yi MT5'in kendi dialoguna girer
 *   - Bağlantı başarılı olunca → CONNECTED → dashboard
 *
 * OTP, admin Python scripti (mt5_automator.py) ile MT5 dialog'una gönderilir.
 *
 * Kullanım:
 *   import { MT5LauncherState, checkSavedCredentials, launchWithCredentials, ... } from '@services/mt5Launcher';
 */

// ── State Enum ───────────────────────────────────────────────────
export const MT5LauncherState = {
  IDLE: 'idle',                 // Başlangıç
  CHECKING: 'checking',         // Kaydedilmiş credentials kontrol ediliyor
  CREDENTIALS: 'credentials',   // Kullanıcıdan credentials bekleniyor
  LAUNCHING: 'launching',       // MT5 başlatılıyor
  WAITING: 'waiting',           // MT5 OTP bekleniyor (kullanıcı MT5'e girer, polling devam eder)
  CONNECTED: 'connected',       // Her şey hazır
  ERROR: 'error',               // Hata durumu
};

// ── Electron API Erişim Yardımcısı ──────────────────────────────

/**
 * window.electronAPI mevcut mu?
 * (Tarayıcıda test sırasında olmayabilir.)
 */
function getAPI() {
  if (typeof window !== 'undefined' && window.electronAPI) {
    return window.electronAPI;
  }
  return null;
}

// ── Credential İşlemleri ─────────────────────────────────────────

/**
 * Kaydedilmiş credential'ları kontrol et.
 * Şifre maskeli döner (******).
 *
 * @returns {Promise<{ hasSaved: boolean, server?: string, login?: string, passwordMask?: string }>}
 */
export async function checkSavedCredentials() {
  const api = getAPI();
  if (!api) return { hasSaved: false };

  try {
    return await api.getSavedCredentials();
  } catch (err) {
    console.error('[MT5Launcher] Credential kontrol hatası:', err);
    return { hasSaved: false };
  }
}

/**
 * Kaydedilmiş credential'ları sil.
 * "Farklı Hesap" butonu için.
 *
 * @returns {Promise<boolean>}
 */
export async function clearSavedCredentials() {
  const api = getAPI();
  if (!api) return false;

  try {
    return await api.clearCredentials();
  } catch (err) {
    console.error('[MT5Launcher] Credential silme hatası:', err);
    return false;
  }
}

// ── MT5 Başlatma ─────────────────────────────────────────────────

/**
 * MT5'i credentials ile başlat.
 *
 * Credentials yoksa (ilk giriş):
 *   { server, login, password } gerekli.
 *
 * Credentials varsa (sonraki giriş):
 *   Boş obje gönderilebilir, kaydedilmiş değerler kullanılır.
 *
 * @param {{ server?: string, login?: string, password?: string }} creds
 * @returns {Promise<{ success: boolean, message: string, needsCredentials?: boolean }>}
 */
export async function launchWithCredentials(creds = {}) {
  const api = getAPI();
  if (!api) {
    return { success: false, message: 'Electron API bulunamadı.', needsCredentials: false };
  }

  try {
    return await api.launchMT5(creds);
  } catch (err) {
    console.error('[MT5Launcher] MT5 başlatma hatası:', err);
    return { success: false, message: err.message, needsCredentials: false };
  }
}

/**
 * MT5 genel durum bilgisi.
 *
 * @returns {Promise<{ running: boolean, hasSaved: boolean, server?: string, login?: string }>}
 */
export async function getMT5Status() {
  const api = getAPI();
  if (!api) return { running: false, hasSaved: false };

  try {
    return await api.getMT5Status();
  } catch (err) {
    console.error('[MT5Launcher] Durum sorgu hatası:', err);
    return { running: false, hasSaved: false };
  }
}

// ── OTP Gönderme ────────────────────────────────────────────

/**
 * OTP kodunu MT5 dialog'una gönder.
 * Admin Python ile PowerShell -Verb RunAs üzerinden çalışır.
 *
 * @param {string} otpCode - 6 haneli OTP kodu
 * @returns {Promise<{ success: boolean, message: string }>}
 */
export async function sendOTP(otpCode) {
  const api = getAPI();
  if (!api) {
    return { success: false, message: 'Electron API bulunamadı.' };
  }

  try {
    return await api.sendOTP(otpCode);
  } catch (err) {
    console.error('[MT5Launcher] OTP gönderme hatası:', err);
    return { success: false, message: err.message };
  }
}

// ── Bağlantı Doğrulama ──────────────────────────────────────────

/**
 * MT5 bağlantısını Python MetaTrader5 ile doğrula.
 *
 * @returns {Promise<{ connected: boolean, account?: object, message: string }>}
 */
export async function verifyMT5Connection() {
  const api = getAPI();
  if (!api) {
    return { connected: false, message: 'Electron API bulunamadı.' };
  }

  try {
    return await api.verifyMT5Connection();
  } catch (err) {
    console.error('[MT5Launcher] Bağlantı doğrulama hatası:', err);
    return { connected: false, message: err.message };
  }
}

/**
 * MT5 pencere durumunu kontrol et.
 * OTP dialog'u açık mı?
 *
 * @returns {Promise<{ mt5_found: boolean, otp_dialog: boolean }>}
 */
export async function checkMT5Window() {
  const api = getAPI();
  if (!api) return { mt5_found: false, otp_dialog: false };

  try {
    return await api.checkMT5Window();
  } catch (err) {
    console.error('[MT5Launcher] Pencere kontrol hatası:', err);
    return { mt5_found: false, otp_dialog: false };
  }
}

// ── MT5 Durum Dinleyicisi ────────────────────────────────────────

/**
 * MT5 durum değişikliklerini dinle.
 *
 * @param {function} callback - ({ running: boolean }) => void
 */
export function onMT5StatusChange(callback) {
  const api = getAPI();
  if (!api) return;

  api.onMT5StatusChange(callback);
}

// ── Otomatik Başlatma Akışı ─────────────────────────────────────

/**
 * Tam başlatma akışını çalıştır (fire-and-forget).
 *
 * 1. Kaydedilmiş credentials kontrol et
 * 2. Varsa → MT5'i arka planda fire-and-forget başlat → hemen WAITING adımına geç
 * 3. Yoksa → credentials iste
 *
 * WAITING aşamasında:
 *   - "MT5'e OTP kodunuzu girin" mesajı gösterilir
 *   - mt5.initialize() polling ile bağlantı kontrol edilir (3sn aralık, 120sn timeout)
 *   - Bağlantı başarılı olunca → CONNECTED → dashboard
 *
 * @param {function} onStateChange - (state: string, data?: object) => void
 * @returns {Promise<void>}
 */
export async function autoLaunchFlow(onStateChange) {
  // Adım 1: Kaydedilmiş credentials kontrol
  onStateChange(MT5LauncherState.CHECKING);
  const saved = await checkSavedCredentials();

  if (saved.hasSaved) {
    // Adım 2a: Fire-and-forget MT5 başlat → hemen WAITING adımına geç
    const result = await launchWithCredentials();

    if (result.success) {
      // MT5 arka planda başlatıldı → WAITING adımına geç (polling başlar)
      onStateChange(MT5LauncherState.WAITING, {
        server: saved.server,
        login: saved.login,
      });
    } else if (result.needsCredentials) {
      // Credentials sorunlu → yeniden iste
      onStateChange(MT5LauncherState.CREDENTIALS);
    } else {
      // Başka hata
      onStateChange(MT5LauncherState.ERROR, { message: result.message });
    }
  } else {
    // Adım 2b: Kaydedilmiş credentials yok → kullanıcıdan iste
    onStateChange(MT5LauncherState.CREDENTIALS);
  }
}
