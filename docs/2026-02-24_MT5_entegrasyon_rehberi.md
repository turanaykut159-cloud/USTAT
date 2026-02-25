# ÜSTAT v5.0 — MT5 Entegrasyonu ve OTP Akışı Rehberi

> Tarih: 2026-02-24
> Amaç: ÜSTAT uygulaması ile MetaTrader 5 arasındaki entegrasyonun tam mimari rehberi

---

## Genel Mimari

ÜSTAT, MetaTrader 5 terminaliyle entegrasyonu **Electron + Node.js (main) + Python (backend)** üzerinden yönetir. OTP doğrulaması, Windows UIPI (User Interface Privilege Isolation) kuralları çerçevesinde **admin privilege** ile gerçekleştirilir.

**Akış zinciri:**
```
LockScreen.jsx → mt5Launcher.js → preload.js → main.js → mt5Manager.js → PowerShell → mt5_automator.py
```

---

## Dosya Haritası ve Sorumluluklar

| Dosya | Rol | Katman |
|-------|-----|--------|
| `desktop/src/components/LockScreen.jsx` | OTP giriş UI, polling | Renderer (React) |
| `desktop/src/services/mt5Launcher.js` | IPC wrapper, state machine | Renderer (JS Service) |
| `desktop/preload.js` | Güvenli IPC köprüsü | Electron Bridge |
| `desktop/main.js` | Electron ana process, IPC handlers | Main (Node.js) |
| `desktop/mt5Manager.js` | MT5 spawn, creds, Python subprocess | Main (Node.js) |
| `desktop/scripts/mt5_automator.py` | OTP dialog'a yaz, OK bas | Admin (Python, Win32) |
| `engine/mt5_bridge.py` | MT5 bağlantı, trading işlemleri | Backend (Python) |

---

## Tam OTP Akışı (Adım Adım)

```
1. Kullanıcı ÜSTAT ikonuna tıklar
   ↓
2. Electron açılır (2-3 sn, splash screen)
   ↓
3. LockScreen.jsx → initFlow() → checkSavedCredentials()
   ↓
4. Kaydedilmiş credentials varsa → doLaunch() çağrılır
   Yoksa → Credential formu gösterilir (server, login, şifre)
   ↓
5. mt5Manager.startMT5WithCredentials() (main process'te)
   → launchMT5() → spawn terminal64.exe (fire-and-forget, normal user)
   → Bağlantı kontrol: zaten çalışıyorsa verify, yoksa WAITING
   ↓
6. LockScreen state → WAITING
   → "MT5'e OTP kodunuzu girin" mesajı gösterilir
   → OTP input field aktif
   → Arka planda polling başlar (3sn aralık, max 120sn)
   ↓
7. Kullanıcı OTP kodunu girer (İKİ SEÇENEKten biri):

   SEÇENEK A — ÜSTAT'a girer:
   → handleOTPSubmit() → sendOTP(code)
   → mt5Manager.sendOTPToMT5() (main process)
   → PowerShell: Start-Process -Verb RunAs (admin yetki)
   → Admin Python: mt5_automator.py --otp XXXXXX --output C:\Temp\...json
   → Win32GUI: MT5 penceresi bul → OTP dialog bul → Edit'e yaz → OK bas
   → Temp dosyadan sonuç oku → Renderer'e dön

   SEÇENEK B — Doğrudan MT5 dialoguna girer:
   → Polling devam eder, müdahale yok

   ↓
8. Arka plan polling (her 3sn):
   → verifyMT5Connection() çağrılır
   → Python subprocess: mt5.initialize() + account_info()
   → Başarılı → { connected: true }
   ↓
9. State → CONNECTED → onUnlock() → Dashboard yüklenir
```

---

## Her Dosyanın Detaylı Açıklaması

### 1. LockScreen.jsx (OTP Giriş Ekranı)
**Yol:** `desktop/src/components/LockScreen.jsx`

Kullanıcıya MT5 giriş formu ve OTP input alanı sunar. Arka planda polling ile bağlantı kontrol eder.

**Önemli fonksiyonlar:**
| Fonksiyon | Ne Yapar |
|-----------|----------|
| `initFlow()` | Başlangıçta saved credentials kontrol eder |
| `doLaunch()` | MT5'i fire-and-forget başlatır, WAITING adımına geçer |
| `handleOTPSubmit()` | OTP kodunu mt5_automator.py'ye iletir |
| `handleCredentialSubmit()` | Server/login/password formunu gönderir |
| Polling (useEffect) | Her 3sn `verifyMT5Connection()` çağırır |

**State akışı:**
```
CHECKING → CREDENTIALS (creds yoksa) → WAITING → CONNECTED
                                                    ↘ ERROR (120sn timeout)
```

**Sabitler:**
```javascript
const POLL_INTERVAL = 3000;   // 3 saniyede bir kontrol
const POLL_TIMEOUT = 120000;  // 120 saniye max bekleme
```

---

### 2. mt5Launcher.js (Renderer IPC Servisi)
**Yol:** `desktop/src/services/mt5Launcher.js`

React componentlerinden MT5 işlemlerini çağırmak için IPC wrapper. State enum tanımlar.

**State Machine:**
```javascript
MT5LauncherState = {
  IDLE: 'idle',
  CHECKING: 'checking',
  CREDENTIALS: 'credentials',
  LAUNCHING: 'launching',
  WAITING: 'waiting',
  CONNECTED: 'connected',
  ERROR: 'error',
};
```

**Fonksiyonlar:** `checkSavedCredentials()`, `launchWithCredentials(creds)`, `sendOTP(otpCode)`, `verifyMT5Connection()`, `checkMT5Window()`

---

### 3. preload.js (Electron Güvenlik Köprüsü)
**Yol:** `desktop/preload.js`

Context isolation ile Renderer'a sadece izin verilen IPC fonksiyonlarını expose eder.

```javascript
contextBridge.exposeInMainWorld('electronAPI', {
    launchMT5: (creds) => ipcRenderer.invoke('mt5:launch', creds),
    sendOTP: (otpCode) => ipcRenderer.invoke('mt5:sendOTP', otpCode),
    verifyMT5Connection: () => ipcRenderer.invoke('mt5:verify'),
    checkMT5Window: () => ipcRenderer.invoke('mt5:checkWindow'),
    getMT5Status: () => ipcRenderer.invoke('mt5:status'),
    getSavedCredentials: () => ipcRenderer.invoke('mt5:getSavedCredentials'),
    clearCredentials: () => ipcRenderer.invoke('mt5:clearCredentials'),
});
```

---

### 4. main.js (Electron Ana Process)
**Yol:** `desktop/main.js`

Electron uygulamasını yönetir, IPC handler'larını tanımlar.

**MT5 IPC Handlers:**
| Handler | Ne Yapar |
|---------|----------|
| `mt5:launch` | mt5Manager.startMT5WithCredentials() |
| `mt5:sendOTP` | mt5Manager.sendOTPToMT5() |
| `mt5:verify` | MT5 bağlantısı doğrula |
| `mt5:status` | MT5 durum bilgisi |
| `mt5:getSavedCredentials` | Kaydedilmiş credentials (maskeli) |
| `mt5:clearCredentials` | Credentials sil |
| `mt5:checkWindow` | MT5 pencere/dialog durumu |

**Sabitler:**
```javascript
const DEV_PORT = 5173;
const APP_TITLE = 'ÜSTAT v5.0';
```

---

### 5. mt5Manager.js (MT5 Yönetim Modülü)
**Yol:** `desktop/mt5Manager.js`

MT5 process yönetimi, credential encrypt/decrypt, OTP koordinasyonu.

**Önemli fonksiyonlar:**
| Fonksiyon | Ne Yapar |
|-----------|----------|
| `loadCredentials()` | Kaydedilmiş credentials oku (şifre decrypt - DPAPI) |
| `saveCredentials(creds)` | Credentials kaydet (şifre encrypt) |
| `launchMT5(options)` | terminal64.exe spawn (fire-and-forget, detached) |
| `isMT5Running()` | tasklist ile MT5 çalışıyor mu kontrol |
| `verifyMT5Connection()` | Python subprocess ile mt5.initialize() + account_info() |
| `sendOTPToMT5(otpCode)` | PowerShell -Verb RunAs ile admin Python başlat |
| `startMT5WithCredentials(options)` | Üst düzey: creds + launch + verify |
| `checkMT5Window()` | Python subprocess ile pencere/dialog kontrol |

**OTP Gönderim Mekanizması (sendOTPToMT5):**
1. Temp dosya oluştur (sonuç için)
2. PowerShell komutu hazırla:
   ```
   Start-Process -Verb RunAs -FilePath python.exe -ArgumentList "mt5_automator.py --otp XXXXXX --output temp.json"
   ```
3. Admin Python çalışır → OTP'yi MT5 dialog'una yazar
4. Sonuç temp dosyaya yazılır → main process okur → Renderer'e döner

**Sabitler:**
```javascript
const DEFAULT_MT5_PATH = 'C:\\Program Files\\GCM MT5 Terminal\\terminal64.exe';
const PYTHON_PATH = 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python314\\python.exe';
const OTP_SCRIPT = path.join(__dirname, 'scripts', 'mt5_automator.py');
```

**Credential Depolama:**
- Electron `safeStorage` (Windows DPAPI encryption)
- Dosya: `%APPDATA%/ustat-desktop/mt5-credentials.json`
- Şifre encrypt edilir, server/login plain text

---

### 6. mt5_automator.py (Admin Python - OTP Gönderici)
**Yol:** `desktop/scripts/mt5_automator.py`

**KRİTİK:** Bu script **admin yetkisiyle** çalışmalıdır. Normal kullanıcı process'i Windows UIPI engeli nedeniyle MT5 (admin pencere) ile iletişim kuramaz.

**Çalışma mekanizması:**
1. Admin kontrolü: `IsUserAnAdmin()` doğrulaması
2. MT5 penceresi tespiti: Win32GUI ile `MetaQuotes::MetaTrader` class
3. OTP Dialog bulma: MT5 PID'ine ait `#32770` dialog (başlık: `&Giriş...`)
4. OTP Edit bulma: `"Tek kullanimlik sifre:"` label'ından sonraki Edit field
5. OTP yazma: `WM_SETTEXT` ile (fallback: `WM_CHAR` ile karakter karakter)
6. OK tıklama: `WM_COMMAND` ile `Tamam` butonuna basma

**Komut satırı:**
```bash
# OTP gönder
python mt5_automator.py --otp 123456 --output C:\Temp\result.json

# Durum kontrol
python mt5_automator.py --check
```

**Çıkış kodları:**
| Kod | Anlam |
|-----|-------|
| 0 | Başarılı |
| 1 | MT5 penceresi bulunamadı |
| 2 | OTP dialog'u bulunamadı |
| 3 | OTP girişi başarısız |
| 4 | Genel hata |
| 5 | Admin değil (UIPI engeli) |

**Win32 API Detayları:**
- Dialog class: `#32770`
- Dialog başlığı: `&Giriş...`
- OTP Edit field ID: 10631
- OK Buton ID: 1
- Mesajlar: `WM_SETTEXT` (0x000C), `WM_COMMAND`, `BM_CLICK`

---

### 7. mt5_bridge.py (MT5 Bağlantı Katmanı)
**Yol:** `engine/mt5_bridge.py`

Python MetaTrader5 kütüphanesi ile MT5'e bağlanan ve tüm trading işlemlerini yöneten tek nokta.

**Bağlantı fonksiyonları:**
| Fonksiyon | Ne Yapar |
|-----------|----------|
| `connect(launch=True)` | MT5 başlat + bağlan |
| `connect(launch=False)` | Sadece bağlan (heartbeat için) |
| `heartbeat()` | 10sn aralıkla terminal_info() ile bağlantı kontrol |
| `_ensure_connection()` | Bağlantı yoksa reconnect dene |
| `disconnect()` | mt5.shutdown() |
| `_resolve_symbols()` | F_THYAO → F_THYAO0226 (vade soneki eşleme) |

**Trading fonksiyonları:**
- `send_order()` — Emir gönderme
- `close_position()` — Pozisyon kapatma
- `modify_position()` — SL/TP değiştirme
- `get_bars()` — Mum verisi çekme
- `get_tick()` — Anlık fiyat
- `get_positions()` — Açık pozisyonlar
- `get_history()` — İşlem geçmişi

**Sabitler:**
```python
WATCHED_SYMBOLS = [
    "F_THYAO", "F_AKBNK", "F_ASELS", "F_TCELL", "F_HALKB",
    "F_PGSUS", "F_GUBRF", "F_EKGYO", "F_SOKM",  "F_TKFEN",
    "F_OYAKC", "F_BRSAN", "F_AKSEN", "F_ASTOR", "F_KONTR",
]
MAX_RETRIES_LAUNCH = 5
MAX_RETRIES_RECONNECT = 3
BASE_WAIT = 2.0            # Artan bekleme: 2→4→8→16→32
HEARTBEAT_INTERVAL = 10.0  # saniye
```

---

## Dosya Çağrı İlişkileri

```
LockScreen.jsx
    ↓ import
mt5Launcher.js
    ↓ window.electronAPI.*
preload.js
    ↓ ipcRenderer.invoke('mt5:*')
main.js
    ↓ require('./mt5Manager')
mt5Manager.js
    ├─ spawn('terminal64.exe')      → MT5 başlatma
    ├─ spawn('python', [...])       → Bağlantı doğrulama
    └─ spawn('powershell', [...])   → OTP gönderimi
        ↓ -Verb RunAs
    mt5_automator.py                → Win32 API ile OTP yazma
```

```
engine/main.py
    ↓ import
mt5_bridge.py
    ↓ import MetaTrader5 as mt5
    mt5.initialize() / mt5.login() / mt5.order_send() / ...
```

---

## Kritik Konfigürasyon Tablosu

| Kaynak | Sabit | Değer | Amacı |
|--------|-------|-------|-------|
| LockScreen.jsx | POLL_INTERVAL | 3000 ms | Bağlantı kontrol sıklığı |
| LockScreen.jsx | POLL_TIMEOUT | 120000 ms | Max bekleme süresi |
| mt5_automator.py | Dialog class | `#32770` | OTP dialog tanıma |
| mt5_automator.py | Dialog başlığı | `&Giriş...` | OTP dialog tanıma |
| mt5_bridge.py | HEARTBEAT_INTERVAL | 10.0 s | Ana döngü bağlantı kontrolü |
| mt5_bridge.py | MAX_RETRIES_LAUNCH | 5 | İlk başlatma deneme |
| mt5_bridge.py | MAX_RETRIES_RECONNECT | 3 | Reconnect deneme |
| mt5Manager.js | DEFAULT_MT5_PATH | C:\Program Files\GCM MT5 Terminal\terminal64.exe | MT5 yolu |
| mt5Manager.js | PYTHON_PATH | C:\Users\pc\...\Python314\python.exe | Python yolu |
| main.js | DEV_PORT | 5173 | Vite dev server portu |

---

## Bilinen Önemli Kurallar

1. **UIPI (User Interface Privilege Isolation):**
   - Normal kullanıcı process'i admin penceresine SendMessage **gönderemez**
   - Çözüm: PowerShell `-Verb RunAs` ile admin Python başlatmak
   - `mt5_automator.py` admin olarak çalıştığını doğrular (`IsUserAnAdmin()`)

2. **Fire-and-Forget MT5 Başlatma:**
   - `spawn(..., { detached: true, stdio: 'ignore' })` ile normal kullanıcı olarak
   - MT5 açılmasını beklemiyor, hemen WAITING adımına geçiyor
   - Polling ile bağlantı kontrol ediliyor

3. **Heartbeat ile MT5 Açma Kontrolü:**
   - `connect(launch=False)` ile heartbeat MT5'i yeniden açmaz
   - ÜSTAT kapatılınca API + Engine de durur (api.pid + killApiProcess)
   - ÜSTAT kapalıyken MT5'e sinyal gitmiyor

4. **Credential Güvenliği:**
   - Electron `safeStorage` → Windows DPAPI ile şifreleme
   - Şifre asla plain text saklanmaz
   - Dosya: `%APPDATA%/ustat-desktop/mt5-credentials.json`

5. **Sembol Eşleme:**
   - Base isim: F_THYAO → MT5 gerçek isim: F_THYAO0226 (vade soneki)
   - `_resolve_symbols()` ile otomatik eşleme
   - Her bağlantıda güncellenir

---

## Sorun Giderme

| Sorun | Olası Neden | Çözüm |
|-------|-------------|-------|
| OTP gönderilemiyor | Admin yetkisi yok | PowerShell -Verb RunAs kontrol |
| MT5 penceresi bulunamıyor | MT5 henüz açılmamış | Bekleme süresini artır |
| OTP dialog bulunamıyor | MT5 OTP sormadı (zaten giriş yapmış) | MT5'i kapat/aç |
| Polling timeout (120sn) | OTP girilmemiş veya hatalı | OTP kodunu kontrol et |
| Credential decrypt hatası | DPAPI anahtarı değişmiş | Credentials temizle, yeniden gir |
| Bağlantı kopması | MT5 kapanmış veya ağ sorunu | Heartbeat otomatik reconnect dener |
