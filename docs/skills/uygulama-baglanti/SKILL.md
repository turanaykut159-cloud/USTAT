---
name: uygulama-baglanti
description: >
  USTAT masaüstü uygulamasına tarayıcı üzerinden bağlanma protokolü.
  "masa üstü uygulamasına bağlan", "uygulamaya bağlan", "uygulamaya gir",
  "USTAT'a bağlan" gibi komutlarda bu skill tetiklenir.
  Uygulamanın çalıştığı portları, LockScreen bypass yöntemini ve
  bağlantı doğrulama adımlarını içerir.
---

# USTAT Masaüstü Uygulamasına Bağlanma Protokolü

## Port Bilgileri

USTAT iki port üzerinde çalışır:

| Port  | Servis          | Açıklama                                              |
|-------|-----------------|-------------------------------------------------------|
| 8000  | FastAPI Backend | REST API + WebSocket (/ws/live). Engine, motorlar, DB |
| 5173  | Vite Dev Server | React frontend. Electron bu adresi yükler             |

Başlatma zinciri: `start_ustat.py` → API (port 8000) → Vite (port 5173) → Electron

## Bağlantı Adımları (Sırayla Uygula)

### Adım 1: Chrome Tab Bağlantısı

```
tabs_context_mcp(createIfEmpty: true)
```

Eğer bağlantı yoksa kullanıcıdan Chrome uzantısında "Connect" butonuna basmasını iste.

### Adım 2: Uygulamaya Eriş

Mevcut bir tab'da veya yeni oluşturulan tab'da:

```
navigate → http://localhost:5173
```

Sayfa yüklendikten sonra screenshot al ve durumu kontrol et.

### Adım 3: LockScreen Kontrolü

Eğer LockScreen (kilit ekranı) görünüyorsa — yani "MT5 hesap bilgilerinizi girin" yazıyorsa:

**Önce API'nin çalışıp çalışmadığını kontrol et:**

```javascript
fetch('http://localhost:8000/api/status')
  .then(r => r.json())
  .then(d => JSON.stringify({
    engine_running: d.engine_running,
    mt5_connected: d.mt5_connected,
    phase: d.phase
  }))
```

- Eğer `engine_running: true` ve `mt5_connected: true` ise → Adım 4'e geç (LockScreen bypass)
- Eğer `engine_running: false` veya `mt5_connected: false` ise → Kullanıcıya bildir: "Engine veya MT5 çalışmıyor. Önce Electron uygulamasını masaüstünden başlat."

### Adım 4: LockScreen Bypass (React State Manipülasyonu)

MT5 zaten bağlıysa LockScreen'i React state üzerinden aşabilirsin. Aşağıdaki JavaScript kodunu sırayla çalıştır:

**4a. React Container Key'ini bul:**

```javascript
const rootEl = document.getElementById('root');
const keys = Object.keys(rootEl).filter(k => k.includes('reactContainer'));
JSON.stringify(keys);
```

Dönen key'i not al (örn: `__reactContainer$sxm3ddcl9s`). Bu key her oturumda farklı olabilir.

**4b. App bileşenini bul ve isLocked state'ini false yap:**

Aşağıdaki kodda `__reactContainer$XXXXX` kısmını 4a'dan dönen key ile değiştir:

```javascript
const rootEl = document.getElementById('root');
const container = rootEl.__reactContainer$XXXXX;  // ← 4a'dan gelen key

function walkAll(f, depth) {
  if (!f || depth > 25) return null;
  if (f.type && typeof f.type === 'function') {
    let state = f.memoizedState;
    let idx = 0;
    while (state && idx < 10) {
      if ((state.memoizedState === true || state.memoizedState === false) && f.type.name === 'App') {
        return { fiber: f, stateNode: state };
      }
      state = state.next;
      idx++;
    }
  }
  let result = walkAll(f.child, depth + 1);
  if (result) return result;
  return walkAll(f.sibling, depth + 1);
}

const result = walkAll(container, 0);
if (result) {
  const queue = result.stateNode.queue;
  if (queue && queue.dispatch) {
    queue.dispatch(false);
    'Basarili: isLocked = false';
  } else {
    'Hata: dispatch bulunamadi';
  }
} else {
  'Hata: App fiber bulunamadi';
}
```

### Adım 5: Doğrulama

Screenshot al ve uygulamanın açıldığını doğrula. Sol menüde Dashboard, Manuel İşlem Paneli vb. sayfalar görünmeli.

### Adım 6: Sayfa Navigasyonu

İstenen sayfaya hash router ile git:

| Sayfa                   | URL                              |
|-------------------------|----------------------------------|
| Dashboard               | http://localhost:5173/#/          |
| Manuel İşlem Paneli     | http://localhost:5173/#/manual    |
| Hibrit İşlem Paneli     | http://localhost:5173/#/hybrid    |
| Otomatik İşlem Paneli   | http://localhost:5173/#/auto      |
| İşlem Geçmişi           | http://localhost:5173/#/history   |
| Üstat & Performans      | http://localhost:5173/#/performance |
| Risk Yönetimi           | http://localhost:5173/#/risk      |
| System Monitor          | http://localhost:5173/#/monitor   |
| Hata Takip              | http://localhost:5173/#/errors    |
| Ayarlar                 | http://localhost:5173/#/settings  |

## Sorun Giderme

| Sorun                          | Çözüm                                                    |
|--------------------------------|-----------------------------------------------------------|
| Chrome bağlantısı yok          | Kullanıcıdan uzantıda "Connect" tıklamasını iste         |
| localhost:5173 açılmıyor       | Vite dev server çalışmıyor — `npm run dev` gerekli       |
| API yanıt vermiyor (port 8000) | Engine başlamamış — `python start_ustat.py` gerekli      |
| LockScreen bypass çalışmıyor   | React container key değişmiş olabilir — 4a'yı tekrar çalıştır |
| Sayfa boş geliyor              | fetchAll hata vermiş olabilir — console loglarını kontrol et |

## Notlar

- Bu protokol, Electron uygulaması masaüstünde ÇALIŞIRKEN tarayıcıdan erişimi sağlar
- Hesap bilgileri (sunucu adı, hesap no, şifre) GÜVENLİK GEREĞİ asla girilmez
- LockScreen bypass SADECE MT5 zaten bağlıyken çalışır — yoksa bypass yapılamaz
- Her yeni Chrome oturumunda LockScreen bypass tekrar gerekebilir
