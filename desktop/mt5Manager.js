/**
 * ÜSTAT v5.7 — MT5 Yönetim Modülü (Main Process).
 *
 * Sorumluluklar:
 *   1. MT5 terminal64.exe spawn (normal kullanıcı, fire-and-forget)
 *   2. Kimlik bilgisi yönetimi (safeStorage + DPAPI)
 *   3. MT5 bağlantı doğrulama (Python MetaTrader5 kütüphanesi)
 *   4. MT5 süreç durumu takibi
 *
 * Başlatma akışı:
 *   1. ÜSTAT açılır → kilit ekranı görünür
 *   2. MT5 arka planda fire-and-forget başlatılır (bekleme yok)
 *   3. "MT5'e OTP kodunuzu girin" mesajı gösterilir
 *   4. Kullanıcı OTP'yi MT5'in kendi dialoguna girer
 *   5. mt5.initialize() polling ile bağlantı kontrol edilir
 *   6. Bağlantı başarılıysa → dashboard'a geçilir
 *
 * NOT: OTP, MT5'e bu uygulama tarafından GÖNDERİLMEZ.
 * Windows UIPI kuralı nedeniyle pyautogui/PostMessage çalışmaz.
 */

const { app, safeStorage } = require('electron');
const { spawn, execFile } = require('child_process');
const path = require('path');
const fs = require('fs');

// ── Sabitler ──────────────────────────────────────────────────────
const DEFAULT_MT5_PATH = 'C:\\Program Files\\GCM MT5 Terminal\\terminal64.exe';
const CREDENTIALS_FILE = 'mt5-credentials.json';
const OTP_SCRIPT = path.join(__dirname, 'scripts', 'mt5_automator.py');

/**
 * Python tam yolu.
 * NEDEN TAM YOL:
 *   Windows App Store alias (%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe)
 *   farklı bir Python sürümüne yönlendirebilir veya çalışmayabilir.
 *   Tam yol ile kurulu Python doğrudan çağrılır.
 */
const PYTHON_PATH = 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python314\\python.exe';

// ── State ─────────────────────────────────────────────────────────
let mt5Process = null;
let mt5Running = false;
let store = null;       // electron-store instance (lazy init)

// ── Credential Yönetimi ───────────────────────────────────────────

/**
 * Credentials dosya yolunu döndür.
 * userData dizini: %APPDATA%/ustat-desktop/
 */
function getCredentialsPath() {
  return path.join(app.getPath('userData'), CREDENTIALS_FILE);
}

/**
 * Kaydedilmiş kimlik bilgilerini oku.
 * Şifre, safeStorage ile OS-native şifreleme (DPAPI) kullanır.
 *
 * @returns {{ server: string, login: string, password: string } | null}
 */
function loadCredentials() {
  try {
    const filePath = getCredentialsPath();
    if (!fs.existsSync(filePath)) return null;

    const raw = fs.readFileSync(filePath, 'utf-8');
    const data = JSON.parse(raw);

    if (!data.server || !data.login || !data.encryptedPassword) return null;

    // safeStorage ile şifreyi çöz
    if (!safeStorage.isEncryptionAvailable()) {
      console.warn('[MT5Manager] safeStorage şifreleme kullanılamıyor.');
      return null;
    }

    const decrypted = safeStorage.decryptString(
      Buffer.from(data.encryptedPassword, 'base64')
    );

    return {
      server: data.server,
      login: data.login,
      password: decrypted,
    };
  } catch (err) {
    console.error('[MT5Manager] Kimlik bilgisi okuma hatası:', err.message);
    return null;
  }
}

/**
 * Kimlik bilgilerini kaydet.
 * Şifre safeStorage (DPAPI) ile şifrelenir, sunucu/hesap düz metin.
 *
 * @param {{ server: string, login: string, password: string }} creds
 * @returns {boolean}
 */
function saveCredentials(creds) {
  try {
    if (!safeStorage.isEncryptionAvailable()) {
      console.warn('[MT5Manager] safeStorage kullanılamıyor, kayıt iptal.');
      return false;
    }

    const encrypted = safeStorage.encryptString(creds.password);
    const data = {
      server: creds.server,
      login: creds.login,
      encryptedPassword: encrypted.toString('base64'),
      savedAt: new Date().toISOString(),
    };

    const filePath = getCredentialsPath();
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf-8');
    return true;
  } catch (err) {
    console.error('[MT5Manager] Kimlik bilgisi kaydetme hatası:', err.message);
    return false;
  }
}

/**
 * Kaydedilmiş kimlik bilgilerini sil.
 * @returns {boolean}
 */
function clearCredentials() {
  try {
    const filePath = getCredentialsPath();
    if (fs.existsSync(filePath)) {
      fs.unlinkSync(filePath);
    }
    return true;
  } catch (err) {
    console.error('[MT5Manager] Kimlik silme hatası:', err.message);
    return false;
  }
}

/**
 * Kaydedilmiş kimlik bilgilerini maskeli olarak döndür.
 * Şifre: ****** olarak gösterilir.
 *
 * @returns {{ server: string, login: string, passwordMask: string, hasSaved: true } | { hasSaved: false }}
 */
function getSavedCredentialsMasked() {
  const creds = loadCredentials();
  if (!creds) return { hasSaved: false };

  return {
    hasSaved: true,
    server: creds.server,
    login: creds.login,
    passwordMask: '******',
  };
}

// ── MT5 Süreç Yönetimi ───────────────────────────────────────────

/**
 * MT5 çalışıyor mu kontrol et (tasklist ile).
 * PID bilgisini de döndürür.
 *
 * @returns {Promise<{ running: boolean, pid: number | null }>}
 */
function isMT5RunningDetailed() {
  return new Promise((resolve) => {
    const proc = spawn(
      'tasklist',
      ['/FI', 'IMAGENAME eq terminal64.exe', '/FO', 'CSV', '/NH'],
      { shell: true, stdio: ['ignore', 'pipe', 'ignore'] },
    );

    let stdout = '';
    proc.stdout.on('data', (data) => { stdout += data.toString(); });
    proc.on('close', () => {
      if (!stdout.includes('terminal64.exe')) {
        resolve({ running: false, pid: null });
        return;
      }
      // CSV formatı: "terminal64.exe","12345","Console","1","123.456 K"
      const match = stdout.match(/"terminal64\.exe","(\d+)"/i);
      const pid = match ? parseInt(match[1], 10) : null;
      resolve({ running: true, pid });
    });
    proc.on('error', () => resolve({ running: false, pid: null }));
  });
}

/**
 * MT5 çalışıyor mu kontrol et (basit boolean).
 * @returns {Promise<boolean>}
 */
async function isMT5Running() {
  const { running } = await isMT5RunningDetailed();
  return running;
}

/**
 * MT5 terminal64.exe'yi normal kullanıcı olarak başlat (fire-and-forget).
 *
 * Başlat ve hemen dön — MT5'in ayağa kalkmasını BEKLEME.
 * OTP girişi paralelde yapılacak.
 *
 * Akış:
 *   1. Zaten çalışıyorsa → hemen başarı dön.
 *   2. Dosya yoksa → hata dön.
 *   3. spawn() ile normal kullanıcı olarak başlat (detached, fire-and-forget).
 *   4. Hemen dön (bekleme yok).
 *
 * @param {{ server?: string, login?: string, password?: string, mt5Path?: string }} options
 * @returns {Promise<{ success: boolean, message: string, alreadyRunning?: boolean }>}
 */
async function launchMT5(options = {}) {
  // ── 1. Zaten çalışıyorsa tekrar başlatma ────────────────────
  const status = await isMT5RunningDetailed();
  if (status.running) {
    mt5Running = true;
    console.log(`[MT5Manager] MT5 zaten calisiyor (PID: ${status.pid}).`);
    return {
      success: true,
      message: `MT5 zaten calisiyor (PID: ${status.pid}).`,
      alreadyRunning: true,
    };
  }

  // ── 2. Dosya kontrolü ───────────────────────────────────────
  const mt5Path = options.mt5Path || DEFAULT_MT5_PATH;

  if (!fs.existsSync(mt5Path)) {
    return {
      success: false,
      message: `MT5 bulunamadi: ${mt5Path}`,
    };
  }

  // ── 3. Command-line argümanları ─────────────────────────────
  const spawnArgs = [];
  if (options.login) spawnArgs.push(`/login:${options.login}`);
  if (options.server) spawnArgs.push(`/server:${options.server}`);
  if (options.password) spawnArgs.push(`/password:${options.password}`);

  // ── 4. Fire-and-forget: normal kullanıcı olarak başlat ──────
  try {
    const child = spawn(mt5Path, spawnArgs, {
      detached: true,
      stdio: 'ignore',
      windowsHide: false,
    });

    child.unref(); // Üst process'ten bağımsız çalışsın

    child.on('error', (err) => {
      console.error('[MT5Manager] MT5 spawn hatasi:', err.message);
    });

    console.log('[MT5Manager] MT5 arka planda baslatildi (normal kullanici).');
    mt5Running = true;
    return {
      success: true,
      message: 'MT5 arka planda baslatildi.',
    };

  } catch (err) {
    return {
      success: false,
      message: `MT5 baslama hatasi: ${err.message}`,
    };
  }
}

// ── Bağlantı Doğrulama ───────────────────────────────────────────

/**
 * Python MetaTrader5 kütüphanesi ile MT5 bağlantısını doğrula.
 *
 * Python tek-satır script çalıştırır:
 *   mt5.initialize() → mt5.account_info() → JSON çıktı
 *
 * @returns {Promise<{ connected: boolean, account?: object, message: string }>}
 */
function verifyMT5Connection() {
  // API server üzerinden doğrulama (Electron child process'te mt5.initialize() askıda kalıyordu)
  const http = require('http');

  return new Promise((resolve) => {
    const req = http.get('http://127.0.0.1:8000/api/mt5/verify', { timeout: 10000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch {
          resolve({ connected: false, message: 'API yanıtı okunamadı.' });
        }
      });
    });

    req.on('error', (err) => {
      resolve({ connected: false, message: `API erişim hatası: ${err.message}` });
    });

    req.on('timeout', () => {
      req.destroy();
      resolve({ connected: false, message: 'API zaman aşımı (10sn).' });
    });
  });
}

/**
 * MT5 durumunu kontrol et (Python script ile pencere durumu).
 *
 * @returns {Promise<{ mt5_found: boolean, otp_dialog: boolean }>}
 */
function checkMT5Window() {
  return new Promise((resolve) => {
    execFile(PYTHON_PATH, [OTP_SCRIPT, '--check'], {
      timeout: 10000,
      encoding: 'utf-8',
    }, (error, stdout) => {
      if (error) {
        resolve({ mt5_found: false, otp_dialog: false });
        return;
      }

      try {
        resolve(JSON.parse(stdout.trim()));
      } catch {
        resolve({ mt5_found: false, otp_dialog: false });
      }
    });
  });
}

/**
 * Tam başlatma akışı (fire-and-forget):
 *   1. Kaydedilmiş credentials varsa oku
 *   2. MT5'i arka planda başlat (bekleme yok)
 *   3. Hemen sonucu döndür — OTP aşamasına geç
 *
 * @param {{ server?: string, login?: string, password?: string, save?: boolean }} options
 * @returns {Promise<{ success: boolean, message: string, needsCredentials: boolean }>}
 */
async function startMT5WithCredentials(options = {}) {
  let creds = null;

  // Yeni credentials verilmişse kullan ve kaydet
  if (options.server && options.login && options.password) {
    creds = {
      server: options.server,
      login: options.login,
      password: options.password,
    };

    if (options.save !== false) {
      clearCredentials();
      const saved = saveCredentials(creds);
      if (!saved) {
        console.warn('[MT5Manager] Credentials kaydedilemedi (devam ediyor).');
      }
    }
  } else {
    creds = loadCredentials();
    if (!creds) {
      return {
        success: false,
        message: 'Kayıtlı hesap bilgisi yok.',
        needsCredentials: true,
      };
    }
  }

  // MT5'i fire-and-forget başlat
  const result = await launchMT5(creds);

  // MT5 zaten çalışıyorsa, bağlantıyı kontrol et
  // Bağlıysa OTP gerekmez → direkt dashboard'a geçebilir
  if (result.alreadyRunning) {
    console.log('[MT5Manager] MT5 zaten calisiyor, baglanti kontrol ediliyor...');
    const verify = await verifyMT5Connection();
    if (verify.connected) {
      console.log('[MT5Manager] MT5 zaten bagli:', verify.account);
      return {
        success: true,
        message: 'MT5 zaten bagli.',
        needsCredentials: false,
        alreadyConnected: true,
        account: verify.account,
      };
    }
    console.log('[MT5Manager] MT5 calisiyor ama bagli degil, OTP gerekli.');
  }

  return { ...result, needsCredentials: false };
}

/**
 * MT5 durumu özeti.
 * @returns {Promise<object>}
 */
async function getStatus() {
  const running = await isMT5Running();
  mt5Running = running;

  const saved = getSavedCredentialsMasked();
  return {
    running,
    ...saved,
  };
}

// ── OTP Gönderme (Admin Python) ───────────────────────────────────

/**
 * MT5 OTP dialog'una OTP kodunu admin Python ile gönder.
 *
 * Neden admin:
 *   MT5 admin olarak çalışıyor. Windows UIPI kuralı gereği
 *   normal process admin pencereye SendMessage gönderemez.
 *   Python scriptini admin olarak çalıştırarak UIPI aşılır.
 *
 * Mekanizma:
 *   1. Temp dosya yolu oluştur (sonuç için)
 *   2. PowerShell Start-Process -Verb RunAs ile admin Python başlat
 *   3. Python mt5_automator.py --otp XXX --output tempfile çalışır
 *   4. PowerShell biter → temp dosyayı oku → JSON parse → sonucu dön
 *
 * NOT: Admin process'in stdout'u non-admin parent yakalayamaz.
 * Bu yüzden --output ile temp dosyaya yazılır.
 *
 * @param {string} otpCode - 6 haneli OTP kodu
 * @returns {Promise<{ success: boolean, message: string }>}
 */
function sendOTPToMT5(otpCode) {
  return new Promise((resolve) => {
    // Girdi doğrulama
    if (!otpCode || !/^\d{4,8}$/.test(otpCode)) {
      resolve({ success: false, message: 'Geçersiz OTP kodu. 4-8 haneli rakam olmalı.' });
      return;
    }

    // Temp dosya yolu
    const tmpDir = require('os').tmpdir();
    const outputFile = path.join(tmpDir, `ustat_otp_${Date.now()}.json`);

    // PowerShell komutu: Python'u admin olarak çalıştır
    const psCommand = [
      `Start-Process`,
      `-FilePath '${PYTHON_PATH}'`,
      `-ArgumentList '${OTP_SCRIPT} --otp ${otpCode} --output ${outputFile}'`,
      `-Verb RunAs`,
      `-Wait`,
      `-WindowStyle Hidden`,
    ].join(' ');

    const psProc = spawn('powershell.exe', ['-NoProfile', '-Command', psCommand], {
      shell: false,
      stdio: 'ignore',
      windowsHide: true,
    });

    // Timeout: 30sn (UAC prompt + script çalışma süresi)
    const timeout = setTimeout(() => {
      try { psProc.kill(); } catch { /* ignore */ }
      cleanup();
      resolve({ success: false, message: 'OTP gönderme zaman aşımı (30sn). UAC onayladınız mı?' });
    }, 30000);

    function cleanup() {
      clearTimeout(timeout);
      // Temp dosyayı temizle (gecikmeli — okunması bitmemiş olabilir)
      setTimeout(() => {
        try { fs.unlinkSync(outputFile); } catch { /* ignore */ }
      }, 1000);
    }

    psProc.on('error', (err) => {
      cleanup();
      resolve({ success: false, message: `PowerShell hatası: ${err.message}` });
    });

    psProc.on('close', (code) => {
      cleanup();

      // UAC reddedildi
      if (code !== 0) {
        resolve({
          success: false,
          message: 'OTP gönderilemedi. UAC (yönetici izni) reddedilmiş olabilir.',
        });
        return;
      }

      // Temp dosyadan sonucu oku
      try {
        if (!fs.existsSync(outputFile)) {
          resolve({ success: false, message: 'OTP sonuç dosyası bulunamadı. Script çalışmamış olabilir.' });
          return;
        }

        const raw = fs.readFileSync(outputFile, 'utf-8');
        const result = JSON.parse(raw);
        resolve(result);
      } catch (err) {
        resolve({ success: false, message: `Sonuç okunamadı: ${err.message}` });
      }
    });
  });
}

// ── Module Export ─────────────────────────────────────────────────
module.exports = {
  // Credentials
  loadCredentials,
  saveCredentials,
  clearCredentials,
  getSavedCredentialsMasked,

  // MT5 process
  launchMT5,
  isMT5Running,
  isMT5RunningDetailed,

  // Bağlantı doğrulama
  verifyMT5Connection,
  checkMT5Window,

  // OTP gönderme
  sendOTPToMT5,

  // Üst düzey akış
  startMT5WithCredentials,
  getStatus,
};
