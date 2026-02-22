/**
 * Yerel depolama servisi.
 * Hesap bilgileri ve uygulama ayarlarını saklar.
 */

const KEYS = {
  SETTINGS: 'ustat_settings',
  ACCOUNT: 'ustat_account',
};

/**
 * Ayarları yerel depolamadan oku.
 * @returns {object} Kayıtlı ayarlar.
 */
export function loadSettings() {
  try {
    const raw = localStorage.getItem(KEYS.SETTINGS);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

/**
 * Ayarları yerel depolamaya kaydet.
 * @param {object} settings - Kaydedilecek ayarlar.
 */
export function saveSettings(settings) {
  localStorage.setItem(KEYS.SETTINGS, JSON.stringify(settings));
}

/**
 * Hesap bilgilerini oku.
 * @returns {object|null} Hesap bilgileri.
 */
export function loadAccount() {
  try {
    const raw = localStorage.getItem(KEYS.ACCOUNT);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * Hesap bilgilerini kaydet.
 * @param {object} account - Hesap bilgileri.
 */
export function saveAccount(account) {
  localStorage.setItem(KEYS.ACCOUNT, JSON.stringify(account));
}
