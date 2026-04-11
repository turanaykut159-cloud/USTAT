# Oturum Raporu — H16: Operatör Kimliği Canonical Kaynağa Bağlandı

**Tarih:** 11 Nisan 2026 (Pazar, Barış Zamanı)
**Bulgu:** Widget Denetimi H16 — Hibrit Devir (5.3) operatör hardcode'u
**Sınıf:** C1 (Yeşil Bölge — tamamen frontend utility + 4 bileşen UI)
**Zaman dilimi:** Pazar — piyasa kapalı, Barış Zamanı
**Anayasa uyumu:** Siyah Kapı yok ✓, Kırmızı Bölge yok ✓, Sarı Bölge yok ✓

---

## 1. Kök Neden

Widget Denetimi raporunda (`docs/2026-04-11_widget_denetimi.md`, satır 1490) H16 maddesi "Hibrit devir onay butonu operatör alanı `'operator'` literal ile gönderiliyor" olarak kaydedilmişti. Kodda üç ayrı çağrı noktası tespit edildi ve hepsi aynı anti-pattern'i paylaşıyordu:

1. `desktop/src/components/TradeHistory.jsx::handleApprove` (satır ~366)
   → `approveTrade(tradeId, 'operator', '')` — hibrit işlem onay akışı
2. `desktop/src/components/SideNav.jsx` kill-switch mousedown handler (satır 89)
   → `activateKillSwitch('operator')`
3. `desktop/src/components/TopBar.jsx::handleKsReset` (satır 134)
   → `acknowledgeKillSwitch('operator')`

Üç çağrı da backend `audit_log` tablosuna `operator_name='operator'` sabit değerini yazıyordu. Bu "drift yüzeyi"ydi: backend schema veya route bir gün operatör doğrulaması yaparsa veya ops ekibi birden fazla operatör tanımlamak isterse üç noktaya ayrı ayrı dokunmak gerekecek, birinin unutulması audit log tutarsızlığına yol açacaktı. Ayrıca UI üzerinde operatör adını değiştirme yolu yoktu.

---

## 2. Çözüm (5 dosya + 1 test)

### 2.1 Yeni Canonical Helper — `desktop/src/utils/operator.js`

Tek sorumluluk modülü. İçerik:

- `OPERATOR_NAME_KEY = 'ustat_operator_name'` — localStorage anahtarı
- `DEFAULT_OPERATOR = 'operator'` — geriye dönük uyumluluk fallback
- `getOperatorName()` — localStorage'dan okur, trim eder, boşsa fallback döner. try/catch ile localStorage erişim hatası yakalanır (Electron'da sorun yok ama güvenlik için)
- `setOperatorName(name)` — max 64 karakter (backend audit_log kolon sınırı için güvenli marj), boş string geçilirse localStorage anahtarı silinir (temiz sıfırlama)
- 50+ satırlık JSDoc başlığı: drift yüzeyini, 3 tüketici listesini, backend etkisini, Flow 4za test referansını ve güvenlik modelini açıklar

### 2.2 Tüketici Bileşenleri

Üç çağrı noktası da tek satır değişiklikle canonical'e bağlandı:

```jsx
// TradeHistory.jsx
import { getOperatorName } from '../utils/operator';
const operatorName = getOperatorName();
const res = await approveTrade(tradeId, operatorName, '');

// SideNav.jsx
import { getOperatorName } from '../utils/operator';
await activateKillSwitch(getOperatorName());

// TopBar.jsx
import { getOperatorName } from '../utils/operator';
await acknowledgeKillSwitch(getOperatorName());
```

Her bir dosyada Widget Denetimi H16 açıklayıcı yorumu eklendi (kod arkeolojisi için).

### 2.3 Settings UI — "Operatör Kimliği" Bölümü

`desktop/src/components/Settings.jsx` içine yeni bölüm eklendi (Risk Baseline bölümünden sonra):

- `useState` ile `operatorName` state — mount'ta `getOperatorName()` okur, `DEFAULT_OPERATOR` ise boş gösterir (kullanıcı placeholder görür)
- Max 64 karakter metin inputu
- Kaydet butonu → `setOperatorName()` çağrısı → trimleme + localStorage yazımı
- Başarı/sıfırlama mesajı 3 saniye gösterilir
- JSDoc açıklaması canonical kaynağı işaret eder

### 2.4 Flow 4za — Statik Sözleşme Testi

`tests/critical_flows/test_static_contracts.py` içine `test_operator_identity_canonical_source` eklendi (Flow 4z H7'den sonra, Flow 5'ten önce). 6 aşamalı regresyon koruması:

1. **Helper mevcut** — `operator.js` dosyası var ve 4 export (`getOperatorName`, `setOperatorName`, `DEFAULT_OPERATOR`, `OPERATOR_NAME_KEY`) regex ile doğrulanır
2. **Literal hardcode yasağı** — 3 tüketici dosyada `approveTrade('operator', …)` / `activateKillSwitch('operator')` / `acknowledgeKillSwitch('operator')` literal regex ile aranır, bulunursa test FAIL. Regex fonksiyon çağrısı anchored (`fn_name\s*\([^)]*['\"]operator['\"]`) — import yorumlarındaki "operator" kelimesi false pozitif vermez
3. **Import zorunluluğu** — 3 tüketici dosyada `from '../utils/operator'` import satırı regex ile doğrulanır
4. **Settings yazar** — `Settings.jsx` içinde `setOperatorName` import edilmiş olmalı (UI write path'in sürdürülmesi için)
5. **Fallback sabiti** — `DEFAULT_OPERATOR = 'operator'` regex ile doğrulanır (geriye dönük uyumluluk güvencesi)
6. **Widget Denetimi marker** — `operator.js` içinde `Widget Denetimi H16` yorumu mevcut olmalı (audit iz sürme)

---

## 3. Anayasa Uyumu

| Kontrol | Sonuç |
|---|---|
| Siyah Kapı dokunusu | Yok — tüm 31 korunan fonksiyon değişmedi |
| Kırmızı Bölge (10 dosya) | Yok — sadece frontend bileşenleri + yeni utility |
| Sarı Bölge (7 dosya) | Yok |
| Çağrı sırası | Değişmedi |
| Config dosyası | Değişmedi (`config/default.json` el değmedi) |
| Backend route | `api/routes/trades.py::approve_trade` değişmedi; `ApproveRequest` schema aynı (default `'operator'` parametresi korunuyor — sadece frontend artık gerçek değerle override ediyor) |
| Veritabanı şeması | Değişmedi |
| API kontratı | Değişmedi |
| Piyasa zamanı | Barış Zamanı (Pazar) ✓ |

Davranışsal eşdeğerlik: `DEFAULT_OPERATOR = 'operator'` fallback'i sayesinde mevcut kurulumlarda localStorage anahtarı boş — audit log'a yine `'operator'` yazılır. Kullanıcı Settings'ten adını girdikten sonra yalnız ondan sonraki approve/kill çağrıları yeni adla kaydedilir. Backend davranışı, schema'sı, migration'ı gerektirmiyor.

---

## 4. Test ve Build

**Kritik akış testleri:**
```
python -m pytest tests/critical_flows -q --tb=short
60 passed, 3 warnings in 3.83s
```

Baseline 59 → 60 (Flow 4za H16 eklendi). İlk koşuda yeşil (self-poisoning yok).

**Production build:**
```
python .agent/claude_bridge.py build
ustat-desktop@6.0.0
vite v6.4.1 building for production...
✓ 730 modules transformed
dist/assets/index-P7vXXjvn.js   891.50 kB │ gzip: 255.63 kB
✓ built in 2.80s
```

Modül sayısı 729 → 730 (+1: `operator.js` yeni eklendi). Toplam bundle boyutu +~1 kB (canonical helper + Settings input bölümü).

---

## 5. Değişiklik Özeti

| Dosya | Tür | Satır |
|---|---|---|
| `desktop/src/utils/operator.js` | YENİ | +85 |
| `desktop/src/components/TradeHistory.jsx` | DEĞİŞTİ | +5 / −1 |
| `desktop/src/components/SideNav.jsx` | DEĞİŞTİ | +5 / −1 |
| `desktop/src/components/TopBar.jsx` | DEĞİŞTİ | +5 / −1 |
| `desktop/src/components/Settings.jsx` | DEĞİŞTİ | +65 / 0 |
| `tests/critical_flows/test_static_contracts.py` | DEĞİŞTİ | +80 / 0 |
| `docs/USTAT_GELISIM_TARIHCESI.md` | DEĞİŞTİ | +1 / 0 |
| `docs/2026-04-11_session_raporu_H16_operator_identity_canonical.md` | YENİ | +~140 |

**Toplam:** 4 değişiklik dosyası + 2 yeni dosya + 1 yeni test + 1 changelog girişi.

---

## 6. Sonraki Maddeler

H16 kapatıldı. Backlog'da sıradaki aday maddeler (Widget Denetimi raporundan):

- **A8** — Hibrit MT5 SL/TP görünürlüğü Dashboard (K10, Orta)
- **A15** — Error resolve message_prefix DB yazımı (B18, Orta)
- **A6** — Performans equity vs deposit ayrımı (B14, Yüksek)
- **B8** — Otomatik Pozisyon Özeti duplicate + sayısal tutarsızlık (Yüksek)

Mandate: otonom olarak devam et.
