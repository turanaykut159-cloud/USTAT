/**
 * ÜSTAT v5.4 Desktop — Electron ana process.
 *
 * Pencere: 1400x900 min, koyu tema, always-on-top, tam ekran başlangıç.
 * System tray: Göster/Gizle/Always on top toggle/Çıkış.
 * IPC: MT5 kimlik, OTP, pencere işlemleri.
 */

const { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage } = require('electron');
const path = require('path');
const net = require('net');
const fs = require('fs');
const mt5Manager = require('./mt5Manager');

// ── Dosya loglama (debug) ────────────────────────────────────────
const LOG_PATH = path.join(__dirname, '..', 'electron.log');
function elog(msg) {
  const ts = new Date().toISOString().slice(11, 19);
  const line = `${ts} | ${msg}\n`;
  try { fs.appendFileSync(LOG_PATH, line); } catch { /* ignore */ }
  console.log(`[Main] ${msg}`);
}

process.on('uncaughtException', (err) => {
  elog(`UNCAUGHT EXCEPTION: ${err.stack || err.message}`);
});

process.on('unhandledRejection', (reason) => {
  elog(`UNHANDLED REJECTION: ${reason}`);
});

// ── Sabitler ─────────────────────────────────────────────────────
const APP_TITLE = 'ÜSTAT v5.4';
const MIN_WIDTH = 1400;
const MIN_HEIGHT = 900;
const BG_COLOR = '#0d1117';
const DEV_PORT = 5173;

// ── Splash Screen HTML ──────────────────────────────────────────
// Vite hazır olmadan HEMEN gösterilir. Electron penceresi anında açılır.
const SPLASH_HTML = `<!DOCTYPE html>
<html style="background:${BG_COLOR};height:100%;margin:0">
<head><meta charset="utf-8"><title>${APP_TITLE}</title></head>
<body style="display:flex;align-items:center;justify-content:center;height:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#e6edf3;margin:0">
<div style="text-align:center">
<h1 style="font-size:48px;margin:0;font-weight:300;letter-spacing:2px">\u00dcSTAT <span style="color:#484f58;font-size:24px">v5.4</span></h1>
<p style="color:#484f58;margin:20px 0 30px;font-size:14px">V\u0130OP Algorithmic Trading</p>
<div style="width:36px;height:36px;border:3px solid #21262d;border-top-color:#58a6ff;border-radius:50%;animation:s 1s linear infinite;margin:0 auto"></div>
<p style="color:#30363d;font-size:13px;margin-top:24px">Y\u00fckleniyor...</p>
</div>
<style>@keyframes s{to{transform:rotate(360deg)}}</style>
</body></html>`;

let mainWindow = null;
let tray = null;
let isAlwaysOnTop = true;

// ── Tek instance kilidi ──────────────────────────────────────────
const gotTheLock = app.requestSingleInstanceLock();
elog(`requestSingleInstanceLock: ${gotTheLock}`);
if (!gotTheLock) {
  elog('Baska bir USTAT instance calisiyor, cikis yapiliyor.');
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ── Ana pencere ──────────────────────────────────────────────────
function createWindow() {
  elog('createWindow() baslatildi');
  const iconPath = path.join(__dirname, 'assets', 'icon.png');

  mainWindow = new BrowserWindow({
    width: MIN_WIDTH,
    height: MIN_HEIGHT,
    minWidth: MIN_WIDTH,
    minHeight: MIN_HEIGHT,
    title: APP_TITLE,
    icon: iconPath,
    backgroundColor: BG_COLOR,
    alwaysOnTop: isAlwaysOnTop,
    show: false,                    // İçerik hazır olunca göster
    frame: true,
    autoHideMenuBar: true,          // Menü çubuğunu gizle
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  });

  // Koyu tema tercihi
  mainWindow.webContents.session.setPreloads([]);

  // ── Hızlı açılış: Splash screen → Vite hazır olunca uygulama ──
  const isDev = process.env.NODE_ENV === 'development';
  elog(`isDev: ${isDev}, NODE_ENV: ${process.env.NODE_ENV}`);

  if (isDev) {
    // Splash screen HEMEN yükle (Vite bekleme yok → pencere anında açılır)
    elog('Splash screen yukleniyor (data: URL)');
    mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(SPLASH_HTML)}`);
    if (process.argv.includes('--devtools')) {
      mainWindow.webContents.openDevTools({ mode: 'detach' });
    }
  } else {
    elog('Production: dist/index.html yukleniyor');
    mainWindow.loadFile(path.join(__dirname, 'dist', 'index.html'));
  }

  // Splash/içerik hazır → pencereyi HEMEN göster
  const showTimeout = setTimeout(() => {
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
      elog('Fallback timeout (10sn): pencere gosteriliyor');
      mainWindow.maximize();
      mainWindow.show();
      mainWindow.focus();
    }
  }, 10000);

  mainWindow.once('ready-to-show', () => {
    elog('ready-to-show tetiklendi, pencere gosteriliyor');
    clearTimeout(showTimeout);
    mainWindow.maximize();
    mainWindow.show();
    mainWindow.focus();
  });

  // Pencere focus aldığında webContents'a da klavye focus ver
  mainWindow.on('focus', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.focus();
    }
  });

  // Dev modda: Vite'i arka planda bekle, hazır olunca uygulamayı yükle
  if (isDev) {
    elog('pollForVite baslatiliyor...');
    pollForVite(DEV_PORT, () => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        elog('Vite hazir, uygulama yukleniyor (http://localhost:' + DEV_PORT + ')');
        mainWindow.loadURL(`http://localhost:${DEV_PORT}`);
      }
    });
  }

  // Pencere başlığını zorla
  mainWindow.on('page-title-updated', (e) => {
    e.preventDefault();
  });
  mainWindow.setTitle(APP_TITLE);

  // Kapatma → gizle (tray'de kalsın)
  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── Vite Dev Server Polling ──────────────────────────────────────
/**
 * Vite dev server hazır olana kadar TCP port kontrol et.
 * Hazır olduğunda callback çağır. 30sn timeout.
 *
 * NOT: Vite bazen sadece [::1] (IPv6) üzerinde dinler.
 * Bu yüzden hem 127.0.0.1 (IPv4) hem ::1 (IPv6) kontrol edilir.
 */
function pollForVite(port, callback) {
  const maxWait = 30000;
  const start = Date.now();
  let resolved = false;

  const tryConnect = (host) => {
    return new Promise((resolve) => {
      const client = net.createConnection({ port, host }, () => {
        client.destroy();
        resolve(true);
      });
      client.on('error', () => resolve(false));
      client.setTimeout(1000, () => {
        client.destroy();
        resolve(false);
      });
    });
  };

  const check = async () => {
    if (resolved) return;
    if (Date.now() - start > maxWait) {
      console.error('[Main] Vite 30sn icinde baslatilamadi!');
      return;
    }

    // Hem IPv4 hem IPv6 kontrol et
    const [ipv4, ipv6] = await Promise.all([
      tryConnect('127.0.0.1'),
      tryConnect('::1'),
    ]);

    if (ipv4 || ipv6) {
      resolved = true;
      console.log(`[Main] Vite hazir (IPv4=${ipv4}, IPv6=${ipv6})`);
      callback();
    } else {
      setTimeout(check, 500);
    }
  };

  check();
}

// ── System Tray ──────────────────────────────────────────────────
function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'icon.png');

  // Tray için küçük ikon (16x16 veya 32x32)
  let trayIcon;
  try {
    trayIcon = nativeImage.createFromPath(iconPath);
    trayIcon = trayIcon.resize({ width: 16, height: 16 });
  } catch {
    trayIcon = nativeImage.createEmpty();
  }

  tray = new Tray(trayIcon);
  tray.setToolTip(APP_TITLE);
  updateTrayMenu();

  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

function updateTrayMenu() {
  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Göster',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    {
      label: 'Gizle',
      click: () => mainWindow?.hide(),
    },
    { type: 'separator' },
    {
      label: `Always on Top: ${isAlwaysOnTop ? 'AÇIK' : 'KAPALI'}`,
      click: () => {
        isAlwaysOnTop = !isAlwaysOnTop;
        if (mainWindow) {
          mainWindow.setAlwaysOnTop(isAlwaysOnTop);
        }
        updateTrayMenu();
      },
    },
    { type: 'separator' },
    {
      label: 'Çıkış',
      click: () => {
        app.isQuitting = true;
        app.quit();
      },
    },
  ]);
  tray.setContextMenu(contextMenu);
}

// ── IPC Handlers ─────────────────────────────────────────────────
function setupIPC() {
  // ── Pencere ────────────────────────────────────────────────────
  ipcMain.handle('window:toggleAlwaysOnTop', () => {
    isAlwaysOnTop = !isAlwaysOnTop;
    if (mainWindow) {
      mainWindow.setAlwaysOnTop(isAlwaysOnTop);
    }
    updateTrayMenu();
    return isAlwaysOnTop;
  });

  ipcMain.handle('window:getAlwaysOnTop', () => isAlwaysOnTop);

  ipcMain.handle('window:setAlwaysOnTop', (_event, value) => {
    isAlwaysOnTop = !!value;
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.setAlwaysOnTop(isAlwaysOnTop);
    }
    updateTrayMenu();
    return isAlwaysOnTop;
  });

  // ── MT5 Başlatma ──────────────────────────────────────────────
  ipcMain.handle('mt5:launch', async (_event, creds) => {
    try {
      const result = await mt5Manager.startMT5WithCredentials(creds || {});
      if (mainWindow && result.success) {
        // MT5 penceresi açılınca fokus çalar — minimize/restore ile Windows'ta focus zorla; 2 sn boyunca tekrarla
        if (!result.alreadyConnected) {
          setTimeout(() => {
            if (mainWindow && !mainWindow.isDestroyed()) {
              isAlwaysOnTop = true;
              mainWindow.setAlwaysOnTop(true);
              updateTrayMenu();
              mainWindow.show();
              mainWindow.focus();
              const tryFocus = () => {
                if (mainWindow && !mainWindow.isDestroyed()) {
                  mainWindow.focus();
                  mainWindow.webContents.focus();
                  mainWindow.webContents.executeJavaScript(
                    "var el=document.querySelector('.otp-input');if(el){el.focus();}"
                  ).catch(() => {});
                  mainWindow.webContents.send('window:focusOTPInput');
                }
              };
              for (let i = 0; i <= 20; i++) setTimeout(tryFocus, 100 * i);
            }
          }, 900);
        }
      }
      return result;
    } catch (err) {
      return { success: false, message: err.message, needsCredentials: false };
    }
  });

  // ── MT5 OTP Gönderme ────────────────────────────────────────────
  ipcMain.handle('mt5:sendOTP', async (_event, otpCode) => {
    try {
      elog(`OTP gonderme istegi: ${otpCode ? otpCode.length + ' haneli' : 'bos'}`);
      const result = await mt5Manager.sendOTPToMT5(otpCode);
      elog(`OTP sonuc: ${result.success ? 'BASARILI' : 'BASARISIZ'} — ${result.message}`);

      // Başarılıysa ÜSTAT'ı tekrar öne getir
      if (result.success && mainWindow && !mainWindow.isDestroyed()) {
        setTimeout(() => {
          mainWindow.show();
          mainWindow.focus();
        }, 1000);
      }

      return result;
    } catch (err) {
      elog(`OTP hata: ${err.message}`);
      return { success: false, message: err.message };
    }
  });

  ipcMain.handle('mt5:status', async () => {
    try {
      return await mt5Manager.getStatus();
    } catch (err) {
      return { running: false, hasSaved: false };
    }
  });

  // ── MT5 Kimlik Bilgileri ──────────────────────────────────────
  ipcMain.handle('mt5:getSavedCredentials', () => {
    return mt5Manager.getSavedCredentialsMasked();
  });

  ipcMain.handle('mt5:clearCredentials', () => {
    return mt5Manager.clearCredentials();
  });

  // ── MT5 Bağlantı Doğrulama ───────────────────────────────────
  ipcMain.handle('mt5:verify', async () => {
    try {
      return await mt5Manager.verifyMT5Connection();
    } catch (err) {
      return { connected: false, message: err.message };
    }
  });

  // ── Güvenli kapat (pencere + arka plan + API sonlandırma) ─────────
  ipcMain.handle('app:safeQuit', () => {
    elog('app:safeQuit cagrildi, cikis baslatiliyor');
    app.isQuitting = true;
    // IPC yaniti gitsin diye quit'i bir sonraki tick'te calistir (bazen aninda quit IPC'yi kesiyor)
    setImmediate(() => {
      app.quit();
    });
  });
}

// ── Uygulama yaşam döngüsü ──────────────────────────────────────
elog('app.whenReady bekleniyor...');
app.whenReady().then(() => {
  elog('app.whenReady tamamlandi, IPC + pencere + tray olusturuluyor');
  setupIPC();
  createWindow();
  createTray();
  elog('Baslangic tamamlandi');
});

app.on('window-all-closed', () => {
  // Windows ve Linux'ta tray'de kalsın
  // macOS'ta zaten convention bu
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  } else if (mainWindow) {
    mainWindow.show();
  }
});

app.on('before-quit', () => {
  app.isQuitting = true;
  killApiProcess();
});

/**
 * API process'ini durdur.
 *
 * start_ustat.py API baslatirken PID'i C:\USTAT\api.pid dosyasina yazar.
 * Electron kapatilinca bu PID okunur ve taskkill ile process sonlandirilir.
 * Boylece USTAT kapali iken MT5'e hicbir sinyal gitmez.
 */
function killApiProcess() {
  const pidFile = path.join(__dirname, '..', 'api.pid');
  try {
    const pid = fs.readFileSync(pidFile, 'utf8').trim();
    if (pid && /^\d+$/.test(pid)) {
      const { execFileSync } = require('child_process');
      execFileSync('taskkill', ['/F', '/PID', pid], {
        windowsHide: true,
        timeout: 5000,
      });
      elog(`API process durduruldu (PID ${pid})`);
    }
  } catch (e) {
    elog(`API kapatma: ${e.message}`);
  }
  // PID dosyasini temizle
  try { fs.unlinkSync(pidFile); } catch { /* ignore */ }
}
