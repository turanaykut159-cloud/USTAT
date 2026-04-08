# MANUEL İŞLEM PANELİ — TAM TEKNİK SPESİFİKASYON

**Kaynak:** ÜSTAT v5.9 kod tabanı (doğrulanmış)
**Amaç:** Bu paneli farklı bir uygulamada sıfırdan yeniden yazmak için gereken TÜM detaylar
**Tarih:** 5 Nisan 2026

---

## 1. GENEL MİMARİ VE AKIŞ

Manuel İşlem Paneli, kullanıcının elle emir açmasını sağlayan bağımsız bir modüldür. OĞUL ve H-Engine'den TAMAMEN ayrı çalışır ancak aynı MT5 bridge ve BABA risk motorunu kullanır.

**Üç katmanlı yapı:**

```
Frontend (ManualTrade.jsx)
        ↓ (axios)
API Katmanı (api/routes/manual_trade.py)
        ↓
ManuelMotor (engine/manuel_motor.py)
        ↓
MT5 Bridge → Broker
```

**Üç fazlı kullanıcı akışı:**

```
[SELECT] → Kullanıcı sembol, yön, lot girer → "Risk Ön Kontrol" butonu
   ↓
[CHECKED] → Backend 12 adımlık kontrol yapar → sonuçlar gösterilir
           → SL/TP otomatik dolar (backend önerisi) → "İŞLEMİ AÇ" butonu
   ↓
[DONE]    → Emir açılır, ticket döner, sonuç gösterilir
           → 5 saniye sonra otomatik SELECT fazına geri döner
```

---

## 2. GÖRSEL TASARIM VE ÖLÇÜLER

### 2.1 Ana Konteyner

```css
.manual-trade {
  padding: 16px;
}
```

Üst üste iki bölüm bulunur:
1. İki sütunlu işlem alanı (sol: form, sağ: risk panel)
2. Aktif pozisyon tablosu
3. Risk monitörü
4. Son işlemler tablosu

### 2.2 İşlem Alanı Grid (Üst Blok)

```css
.mt-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
```

İki eşit sütun. Sol: emir formu. Sağ: risk özet paneli.

### 2.3 Kart Stilleri (Ortak)

Tüm kartlar aynı temel stili paylaşır:

```css
background: var(--bg-card);
border: 1px solid var(--border);
border-radius: 8px;
padding: 16px;
```

Kart başlıkları (h3):
```css
margin: 0 0 14px 0;
font-size: 14px;
font-weight: 600;
color: var(--text-primary);
```

### 2.4 Form Grubu

```css
.mt-form-group {
  margin-bottom: 14px;
}

.mt-form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
```

### 2.5 Form Kontrolleri

**Sembol seçici (.mt-select):**
```css
width: 100%;
padding: 8px 10px;
background: var(--bg-secondary);
border: 1px solid var(--border);
border-radius: 6px;
color: var(--text-primary);
font-size: 13px;
```

**Yön butonları (.mt-dir-btn):** İki buton yan yana, `display: flex; gap: 8px;` içinde.
```css
flex: 1;
padding: 10px;
background: var(--bg-secondary);
border: 2px solid var(--border);
border-radius: 6px;
color: var(--text-primary);
font-weight: 700;
font-size: 14px;
cursor: pointer;
transition: all 0.2s;
```

Aktif durum:
- `.active-buy`: background rgba(63,185,80,0.15), border/color var(--profit)
- `.active-sell`: background rgba(248,81,73,0.15), border/color var(--loss)

**Lot girişi (.mt-lot-input):**
```css
width: 80px;
padding: 8px 10px;
background: var(--bg-secondary);
border: 1px solid var(--border);
border-radius: 6px;
color: var(--text-primary);
font-size: 14px;
font-weight: 600;
text-align: center;
```
`min=1`, `max=10`, `step=1`, `type=number`

**SL/TP girişleri:** Lot input ile aynı stil ama `step=0.01`, `width=100%` veya büyük. İki yan yana grid hücresinde.

**Fiyat bilgisi (.mt-price-info):**
```css
font-size: 12px;
color: var(--text-secondary);
padding: 8px;
background: var(--bg-secondary);
border-radius: 4px;
```

### 2.6 Aksiyon Butonları

```css
.mt-check-btn, .mt-execute-btn {
  width: 100%;
  padding: 12px;
  border: none;
  border-radius: 6px;
  color: #fff;
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
  margin-top: 8px;
  transition: all 0.2s;
}
.mt-check-btn  { background: var(--accent); }
.mt-execute-btn { background: var(--profit); }
.mt-execute-btn.sell { background: var(--loss); }
.mt-check-btn:disabled, .mt-execute-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

### 2.7 Risk Özet Paneli (Sağ)

```css
.mt-risk-panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}
.mt-risk-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 13px;
  border-bottom: 1px solid var(--border);
}
.mt-risk-row:last-child { border-bottom: none; }
.mt-risk-row span:first-child { color: var(--text-secondary); }
.mt-risk-row span:last-child { color: var(--text-primary); font-weight: 600; }
```

İçerik satırları:
- Güncel Fiyat
- ATR (M15)
- Önerilen SL
- Önerilen TP
- Maks Lot
- Durum (BABA verdict: ✓ İşlem serbest / ✗ Engellendi)

Durum mesajları:
```css
.mt-status-ok   { color: var(--profit); background: rgba(63,185,80,0.10); padding: 8px; border-radius: 6px; }
.mt-status-fail { color: var(--loss);   background: rgba(248,81,73,0.10); padding: 8px; border-radius: 6px; font-size: 12px; }
```

### 2.8 Sonuç Bildirimi (.mt-result)

```css
padding: 12px;
border-radius: 6px;
font-weight: 600;
text-align: center;
font-size: 13px;
margin-top: 10px;
```
Başarı: background rgba(63,185,80,0.15), color var(--profit).
Hata: background rgba(248,81,73,0.15), color var(--loss).

### 2.9 Aktif Pozisyonlar Tablosu (.op-table)

Kart `padding: 0` (tablo zaten kendi padding'ini taşıyor).

```css
.op-table-wrap {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  margin-top: 16px;
}
.op-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  min-width: 860px;
}
.op-table th {
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 9px 10px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.op-table td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text-primary);
}
.op-row-profit td { background: rgba(63,185,80,0.04); }
.op-row-loss   td { background: rgba(248,81,73,0.04); }
```

Boş durum:
```css
.op-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  gap: 10px;
  color: var(--text-secondary);
}
.op-empty-icon { font-size: 32px; opacity: 0.5; }
```

Kapat butonu:
```css
.op-close-btn {
  padding: 6px 12px;
  background: var(--loss);
  color: #fff;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
```

**Kolonlar:** Sembol | Yön | Lot | Giriş | Güncel | SL | TP | K/Z (₺) | K/Z (%) | Süre | İşlem

Yön rozeti (.dir-badge):
```css
padding: 1px 6px;
border-radius: 3px;
font-size: 10px;
font-weight: 600;
text-transform: uppercase;
```
BUY: background rgba(63,185,80,0.12), color var(--profit).
SELL: background rgba(248,81,73,0.12), color var(--loss).

### 2.10 Risk Monitörü (.mt-risk-monitor)

```css
background: var(--bg-card);
border: 1px solid var(--border);
border-radius: 8px;
padding: 16px;
margin-top: 16px;
```

İçinde tablo: Ticket | Sembol | Yön | SL Risk | Rejim | K/Z | Sistem | Toplam

Risk rozeti (.mt-risk-dim):
```css
display: inline-block;
padding: 2px 6px;
border-radius: 3px;
font-size: 11px;
font-weight: 600;
text-transform: uppercase;
```
- `.mt-risk-dim--green`:  background rgba(63,185,80,0.18),  color var(--profit)
- `.mt-risk-dim--yellow`: background rgba(210,153,34,0.18), color #d29922
- `.mt-risk-dim--red`:    background rgba(248,81,73,0.18),  color var(--loss)

Toplam skor kolonu: sayı (0-100) ve renk etiketi yan yana.

### 2.11 Son İşlemler (.mt-history)

```css
background: var(--bg-card);
border: 1px solid var(--border);
border-radius: 8px;
padding: 16px;
margin-top: 16px;
```

Son 10 manuel işlemi gösterir (type='Manuel' filtreli). Kolonlar: Zaman | Sembol | Yön | Lot | Giriş | Çıkış | K/Z | Kapanış Nedeni.

### 2.12 Tema Değişkenleri (CSS Variables)

```
--bg-primary:    koyu arka plan
--bg-secondary:  biraz açık arka plan (form, th)
--bg-card:       kart arka planı
--border:        kenarlık rengi (#30363d)
--text-primary:  ana metin
--text-secondary: ikincil metin (label, caption)
--accent:        mavi-yeşil vurgu (check butonu)
--profit:        #3fb950 (yeşil, BUY, kar)
--loss:          #f85149 (kırmızı, SELL, zarar)
```

---

## 3. SEMBOL LİSTESİ (15 VİOP KONTRATI)

```js
const SYMBOLS = [
  'F_THYAO', 'F_AKBNK', 'F_ASELS', 'F_TCELL', 'F_HALKB',
  'F_PGSUS', 'F_GUBRF', 'F_EKGYO', 'F_SOKM',  'F_TKFEN',
  'F_OYAKC', 'F_BRSAN', 'F_AKSEN', 'F_ASTOR', 'F_KONTR'
];
```

Varsayılan: `F_THYAO`. Bu liste `engine/config.py` ve `ManualTrade.jsx` içinde sabit.

---

## 4. FRONTEND STATE MACHİNE (ManualTrade.jsx)

### 4.1 State Değişkenleri

```js
const [symbol, setSymbol] = useState('F_THYAO');
const [direction, setDirection] = useState('');       // '' | 'BUY' | 'SELL'
const [lot, setLot] = useState(1.0);
const [sl, setSl] = useState(0);
const [tp, setTp] = useState(0);
const [phase, setPhase] = useState('select');         // 'select' | 'checked' | 'done'
const [checkResult, setCheckResult] = useState(null); // check response
const [executeResult, setExecuteResult] = useState(null);
const [loading, setLoading] = useState(false);
const [recentTrades, setRecentTrades] = useState([]);
const [activePositions, setActivePositions] = useState([]);
const [riskScores, setRiskScores] = useState({});
```

### 4.2 Faz Geçiş Kuralları

**SELECT → CHECKED:**
- Koşul: `direction !== '' && lot > 0`
- Aksiyon: `checkManualTrade(symbol, direction)` çağrılır
- Başarılı olursa:
  - `checkResult` doldurulur
  - `sl = checkResult.suggested_sl`
  - `tp = checkResult.suggested_tp`
  - `phase = 'checked'`
- Başarısız olursa: `mt-status-fail` mesajı gösterilir, faz değişmez.

**CHECKED → DONE:**
- Koşul: `checkResult.can_trade === true && sl > 0 && tp > 0`
- Aksiyon: `executeManualTrade(symbol, direction, lot, sl, tp)` çağrılır
- Dönen veri `executeResult`'a yazılır.
- `phase = 'done'`
- `setTimeout(() => resetForm(), 5000)` — 5 saniye sonra forma dön.

**DONE → SELECT (otomatik):**
```js
const resetForm = () => {
  setDirection('');
  setLot(1.0);
  setSl(0);
  setTp(0);
  setPhase('select');
  setCheckResult(null);
  setExecuteResult(null);
};
```

**Manuel yeniden kontrol:** Kullanıcı sembol veya yön değiştirirse `phase` otomatik `'select'`'e döner ve `checkResult` temizlenir.

### 4.3 Frontend SL/TP Otomatik Hesaplama (Yedek)

Backend `suggested_sl/suggested_tp` dönerse onlar kullanılır. Backend dönmezse (fallback):
```js
if (direction === 'BUY') {
  sl = price - atr * 2;
  tp = price + atr * 3;
} else {
  sl = price + atr * 2;
  tp = price - atr * 3;
}
```

**NOT:** Backend önerisi ATR×1.5 (SL) ve ATR×2.0 (TP) kullanır. Üretimde backend değeri kazanır.

### 4.4 Polling

```js
useEffect(() => {
  const loadAll = () => {
    fetchRecentTrades();    // GET /trades?type=Manuel&limit=10
    fetchActivePositions(); // GET /positions
    fetchRiskScores();      // GET /manual-trade/risk-scores
  };
  loadAll();
  const id = setInterval(loadAll, 10000); // 10 saniye
  return () => clearInterval(id);
}, []);
```

Aktif pozisyon filtresi: `p.tur === 'Manuel' || p.tur === 'MT5'` (MT5-direct pozisyonlar da gösterilir).

### 4.5 Validasyon Kuralları (Frontend)

- `symbol`: liste içinde olmalı
- `direction`: 'BUY' veya 'SELL' (boş ise check butonu disabled)
- `lot`: min 1, max 10, integer (VİOP'ta ondalık lot yok)
- `sl, tp`: > 0 ve execute öncesi dolu olmalı
- Loading sırasında tüm butonlar disabled

---

## 5. API KATMANI

### 5.1 Endpoint'ler

**POST /api/manual-trade/check**
İstek:
```json
{ "symbol": "F_THYAO", "direction": "BUY" }
```
Yanıt:
```json
{
  "can_trade": true,
  "reason": "",
  "suggested_lot": 1.0,
  "current_price": 285.50,
  "atr_value": 2.34,
  "suggested_sl": 281.99,
  "suggested_tp": 290.18,
  "max_lot": 1.0,
  "risk_summary": {
    "regime": "TREND",
    "can_trade": true,
    "active_manual": 0,
    "max_manual": 3,
    "free_margin_pct": 0.85
  }
}
```

**POST /api/manual-trade/execute**
İstek:
```json
{
  "symbol": "F_THYAO",
  "direction": "BUY",
  "lot": 1.0,
  "sl": 281.99,
  "tp": 290.18
}
```
Yanıt:
```json
{
  "success": true,
  "message": "Manuel işlem açıldı: F_THYAO BUY",
  "ticket": 123456789,
  "entry_price": 285.50,
  "sl": 281.99,
  "tp": 290.18,
  "lot": 1.0
}
```

**GET /api/manual-trade/risk-scores**
Yanıt:
```json
{
  "scores": {
    "123456789": {
      "sl_risk":     "green",
      "regime_risk": "green",
      "pnl_risk":    "yellow",
      "system_risk": "green",
      "overall":     "yellow",
      "score":       85
    }
  }
}
```

### 5.2 API Client Fonksiyonları (desktop/src/services/api.js)

```js
export async function checkManualTrade(symbol, direction) { ... }
export async function executeManualTrade(symbol, direction, lot, sl=0, tp=0) { ... }
export async function getManualRiskScores() { ... }
export async function getPositions() { ... }
export async function closePosition(ticket) { ... }
export async function getTrades(params = {}) { ... } // { type, limit }
```

Tüm fonksiyonlar hata durumunda `null` döner, hata konsola basılır.

---

## 6. BACKEND: MANUELMOTOR (engine/manuel_motor.py)

### 6.1 Sabitler

```python
ATR_PERIOD              = 14       # ATR hesap periyodu
MIN_BARS_M15            = 60       # En az bar sayısı
CONTRACT_SIZE           = 100.0    # VİOP kontrat boyutu
MAX_LOT_PER_CONTRACT    = 1.0      # Her sembol için maks 1 lot (manuel limit)
MARGIN_RESERVE_PCT      = 0.20     # Min serbest marjin oranı
MAX_CONCURRENT_MANUAL   = 3        # Aynı anda en fazla 3 manuel pozisyon
TRADING_OPEN            = 09:40    # İşlem açılış saati
TRADING_CLOSE           = 17:50    # İşlem kapanış saati
SENT_EXPIRE_SEC         = 30.0     # SENT durumu timeout
SL_ATR_GREEN            = 1.5      # SL risk yeşil eşik
SL_ATR_YELLOW           = 0.8      # SL risk sarı eşik
PNL_YELLOW_PCT          = -0.005   # K/Z sarı eşik (-%0.5)
SUGGESTED_SL_ATR_MULT   = 1.5      # Önerilen SL mesafesi
SUGGESTED_TP_ATR_MULT   = 2.0      # Önerilen TP mesafesi
```

### 6.2 check_manual_trade() — 12 Adımlı Kontrol

```
 1. Trading saati kontrolü (09:40-17:50, hafta içi)
 2. Netting kilidi meşgul mü? (başka bir işlem açılırken bu sembol bekler)
 3. Aynı sembolde zıt yön var mı? (OĞUL/H-Engine/ManuelMotor)
 4. BABA.can_trade() çağrısı (rejim, kill-switch, drawdown, L-seviye)
 5. Aynı anda maks 3 manuel pozisyon kontrolü
 6. Korelasyon limiti (aynı grup maks 3)
 7. Serbest marjin ≥ %20 kontrolü
 8. MT5'ten M15 bars (≥60 bar), ATR hesapla
 9. Güncel tick fiyatı al (ask BUY için, bid SELL için)
10. suggested_sl = price ∓ atr × 1.5
    suggested_tp = price ± atr × 2.0
11. max_lot = MAX_LOT_PER_CONTRACT (=1.0)
12. risk_summary doldur ve cevap gönder
```

Herhangi bir adım başarısız olursa `can_trade=False` ve `reason` doldurulur.

### 6.3 open_manual_trade() — Emir Akışı

```python
with netting_lock(symbol):      # Yarış durumu koruması
    # 1. Tekrar check yap (state değişmiş olabilir)
    check = check_manual_trade(symbol, direction)
    if not check.can_trade:
        return error(check.reason)

    # 2. 2 aşamalı emir gönderimi
    #    Aşama A: SL/TP olmadan market emir
    result = mt5_bridge.send_order(
        symbol=symbol, direction=direction, lot=lot,
        sl=0, tp=0, magic=MAGIC_MANUAL,
        comment='Manual'
    )
    if not result.success:
        return error('Emir reddedildi')

    ticket = result.ticket

    # 3. Aşama B: SL/TP ekleme (3 retry)
    for attempt in range(3):
        ok = mt5_bridge.modify_position(ticket, sl=sl, tp=tp)
        if ok: break
        time.sleep(0.5)
    else:
        # SL/TP başarısız → ZORLA KAPAT (Siyah Kapı kuralı #4)
        mt5_bridge.close_position(ticket)
        return error('SL/TP eklenemedi, pozisyon kapatıldı')

    # 4. Trade nesnesi oluştur, DB'ye kaydet
    trade = Trade(ticket=ticket, symbol=symbol, ...)
    database.insert_trade(trade)

    # 5. Marker dosyası güncelle (WAL loss koruması)
    _save_marker()

    # 6. active_trades sözlüğüne ekle
    self.active_trades[ticket] = trade

    return success(ticket, entry_price, sl, tp)
```

### 6.4 Yönetim Kuralları (ÖNEMLİ)

ManuelMotor pozisyonları açtıktan sonra **minimal müdahale eder**:

- ❌ Trailing stop YOK (kullanıcı SL'i koruma olarak tutulur)
- ❌ TP1 yarı kapatma YOK
- ❌ Breakeven taşıma YOK
- ❌ Rejim değişiminde zorla kapatma YOK
- ❌ EOD otomatik kapatma YOK (Siyah Kapı #5'in İSTİSNASI — manuel pozisyonlar için kullanıcı sorumludur, yalnızca uyarı verilir)
- ✅ Kullanıcının SL/TP'si olduğu gibi korunur
- ✅ SL veya TP'ye dokunulursa MT5 pozisyonu kapatır, ManuelMotor sync_positions() ile kapanışı yakalar

### 6.5 sync_positions() — 10 Saniyede Bir

```
1. MT5'ten açık pozisyonları al (MAGIC_MANUAL filtreli)
2. active_trades ile karşılaştır:
   a) SENT durumundaki trade MT5'te görünürse → FILLED'a geçir
   b) FILLED trade MT5'te görünmezse → CLOSED yap, exit fiyatı ve nedeni kaydet
   c) SENT durumunda 30 saniye geçmişse → TIMEOUT
3. MT5'te olup active_trades'te olmayan pozisyon varsa → adopt_mt5_direct_position()
4. Her FILLED pozisyon için güncel K/Z hesapla, DB'ye yaz
5. Marker dosyasını güncelle
```

### 6.6 calculate_risk_score() — Risk Puanlaması

Her aktif manuel pozisyon için 4 boyutta risk hesaplanır:

**1) SL Risk (sl_distance / ATR oranına göre):**
- oran ≥ 1.5 → green (25 puan)
- oran ≥ 0.8 → yellow (15 puan)
- oran <  0.8 → red (0 puan)

**2) Regime Risk (BABA'dan):**
- TREND → green (25)
- RANGE → yellow (15)
- VOLATILE veya OLAY → red (0)

**3) PnL Risk (floating / equity):**
- oran ≥ 0 → green (25)
- oran ≥ -0.5% → yellow (15)
- oran <  -0.5% → red (0)

**4) System Risk (Kill-switch seviyesi):**
- L0 → green (25)
- L1 → yellow (15)
- L2 veya L3 → red (0)

**Toplam:**
- `score = sum(4 boyut)` — maks 100
- `overall = worst_color` (en kötü renk kazanır: red > yellow > green)

### 6.7 restore_active_trades() — Başlangıç Kurtarma

Sistem açılışta:
1. `database.get_trades(state='FILLED', type='Manuel')` ile DB'den aktifleri oku
2. `manual_positions.json` marker dosyasından oku (WAL loss yedeği)
3. İki kaynağı birleştir (union)
4. MT5'ten gerçek açık pozisyonları al
5. Üçünü eşleştir — eksik bilgileri tamamla
6. Sadece MT5'te gerçekten var olanları `active_trades`'e koy

Bu sayede elektrik kesintisi veya crash sonrası veri kaybı yaşanmaz.

### 6.8 adopt_mt5_direct_position()

Kullanıcı MT5 terminalinden ElElle emir açtıysa (Platform dışından), sync_positions bunu yetim pozisyon olarak tespit eder ve:
1. Sembol VİOP listesinde mi? Kontrol et
2. Magic 0 (manuel) veya tanınmayan magic ise ManuelMotor sahiplenir
3. `tur = 'MT5'` olarak işaretlenir (UI'de ayırt etmek için)
4. DB'ye ve marker'a kaydedilir
5. Frontend'te Aktif Pozisyonlar listesinde görünür

### 6.9 _save_marker() — Atomic JSON Yazma

```python
data = {
    "timestamp": now().isoformat(),
    "active": [ trade.to_dict() for trade in active_trades.values() ]
}
tmp = 'manual_positions.json.tmp'
final = 'manual_positions.json'
with open(tmp, 'w') as f:
    json.dump(data, f, indent=2)
os.replace(tmp, final)  # atomik
```

### 6.10 Trading Saati Kontrolü

```python
def _is_trading_allowed():
    now = datetime.now()
    if now.weekday() >= 5:          # Cumartesi/Pazar
        return False
    t = now.time()
    return TRADING_OPEN <= t <= TRADING_CLOSE  # 09:40-17:50
```

---

## 7. VERİ MODELLERİ

### 7.1 Trade (engine/models/trade.py)

```python
@dataclass
class Trade:
    ticket:       int
    symbol:       str
    direction:    str          # 'BUY' | 'SELL'
    lot:          float
    entry_price:  float
    current_price: float
    sl:           float
    tp:           float
    state:        TradeState   # PENDING, SENT, FILLED, CLOSED, ...
    type:         str          # 'Manuel' | 'OGUL' | 'Hibrit' | 'MT5'
    open_time:    datetime
    close_time:   datetime | None
    exit_price:   float | None
    pnl:          float
    pnl_pct:      float
    close_reason: str | None   # 'SL', 'TP', 'Manual', 'EOD', ...
```

### 7.2 Position (API cevabı)

Aktif pozisyon tablosu için frontend şu alanları kullanır:
`ticket, sembol, yon, lot, giris, guncel, sl, tp, pnl, pnl_pct, sure, tur`.

---

## 8. RİSK MONİTÖRÜ RENDER MANTIĞI

```jsx
{activePositions.map(pos => {
  const rs = riskScores[pos.ticket] || {};
  return (
    <tr key={pos.ticket}>
      <td>{pos.ticket}</td>
      <td>{pos.sembol}</td>
      <td><span className={`dir-badge dir-badge--${pos.yon.toLowerCase()}`}>{pos.yon}</span></td>
      <td><span className={`mt-risk-dim mt-risk-dim--${rs.sl_risk}`}>{rs.sl_risk}</span></td>
      <td><span className={`mt-risk-dim mt-risk-dim--${rs.regime_risk}`}>{rs.regime_risk}</span></td>
      <td><span className={`mt-risk-dim mt-risk-dim--${rs.pnl_risk}`}>{rs.pnl_risk}</span></td>
      <td><span className={`mt-risk-dim mt-risk-dim--${rs.system_risk}`}>{rs.system_risk}</span></td>
      <td>
        {rs.score}/100
        <span className={`mt-risk-dim mt-risk-dim--${rs.overall}`}>{rs.overall}</span>
      </td>
    </tr>
  );
})}
```

---

## 9. HATA DURUMLARI VE MESAJLARI

| Durum | Mesaj |
|-------|-------|
| Dışarıda saat | "İşlem saati dışında (09:40-17:50)" |
| Hafta sonu | "Hafta sonu işlem yok" |
| Netting kilidi | "Başka bir işlem açılıyor, lütfen bekleyin" |
| Zıt pozisyon var | "Aynı sembolde zıt yön pozisyon mevcut (netting)" |
| BABA engelledi | "Risk motoru işlemi engelledi: {reason}" |
| L2/L3 kill-switch | "Sistem kilit modunda" |
| Max 3 aşıldı | "Maks eşzamanlı manuel pozisyon sayısı (3) doldu" |
| Korelasyon | "Korelasyonlu pozisyon limiti (3) doldu" |
| Marjin yetersiz | "Serbest marjin %20'nin altında" |
| ATR hesaplanamadı | "M15 verisi yetersiz (<60 bar)" |
| Fiyat alınamadı | "MT5 tick verisi alınamadı" |
| Emir reddedildi | "Broker emri reddetti: {retcode}" |
| SL/TP eklenemedi | "SL/TP eklenemedi, pozisyon güvenlik için kapatıldı" |

---

## 10. ÖNEMLİ GÜVENLİK KURALLARI

1. **Çift kontrol:** Kullanıcı "Risk Ön Kontrol" bassa bile `execute` öncesi backend tekrar check yapar (state değişmiş olabilir).
2. **Netting kilidi:** Aynı sembole aynı anda iki emir gönderilemez (threading.Lock).
3. **SL/TP zorunluluğu:** SL veya TP eklenemezse pozisyon 3 retry sonrası ZORLA kapatılır. Korumasız pozisyon YASAK.
4. **BABA kapısı:** Kill-switch L2/L3'te execute fonksiyonu çalışsa bile BABA reddeder.
5. **Maks 3 manuel:** MAX_CONCURRENT_MANUAL = 3. Dördüncü manuel pozisyon açılamaz.
6. **Maks 1 lot per kontrat:** Manuel modda tek seferde maks 1 lot (VİOP için güvenlik).
7. **İşlem saati:** 09:40'tan önce, 17:50'den sonra işlem açılamaz.
8. **Yetim pozisyon sahiplenme:** MT5'ten elle açılan pozisyon otomatik `tur='MT5'` olarak listelenir ancak ManuelMotor'un tam yönetim kurallarına tabi olur.
9. **Marker dosyası:** Her state değişikliğinde `manual_positions.json` atomik olarak güncellenir (WAL loss koruması).
10. **Magic number:** Manuel emirlerde `magic = MAGIC_MANUAL` set edilir, böylece ManuelMotor kendi pozisyonlarını tanır.

---

## 11. YENİDEN YAZIM İÇİN MİNİMUM GEREKSİNİMLER

Yeni uygulamada bu paneli sıfırdan yazacaksan aşağıdakiler MUTLAKA uygulanmalıdır:

**Frontend:**
- [ ] 3 fazlı state machine (select/checked/done)
- [ ] 10 saniye polling (positions, risk scores, trades)
- [ ] Sembol listesi sabit (15 VİOP)
- [ ] Lot integer + min=1 max=10
- [ ] Yön butonları radyo davranışı
- [ ] Check sonucu gelmeden execute disabled
- [ ] 5 saniye auto-reset done → select
- [ ] Aktif pozisyon tablosu profit/loss renk farkı
- [ ] Risk monitörü 4 boyut + toplam skor

**Backend:**
- [ ] 12 adımlı check fonksiyonu
- [ ] Netting kilidi (thread-safe)
- [ ] 2 aşamalı emir: market order → modify SL/TP
- [ ] SL/TP 3 retry, başarısızsa zorla kapat
- [ ] Maks 3 eşzamanlı manuel pozisyon
- [ ] İşlem saati 09:40-17:50 (hafta içi)
- [ ] ATR(14) M15 üzerinden
- [ ] Önerilen SL: ATR×1.5, TP: ATR×2.0
- [ ] 4 boyutlu risk skorlaması
- [ ] sync_positions 10 saniyede bir
- [ ] SENT timeout = 30 saniye
- [ ] DB + marker dosyası çift kayıt
- [ ] MT5-direct pozisyon sahiplenme
- [ ] BABA verdict zorunlu kapı

**Yapmayacakların:**
- [ ] Trailing stop EKLEME
- [ ] TP1 yarı kapatma EKLEME
- [ ] Breakeven taşıma EKLEME
- [ ] Rejim değişiminde manuel pozisyonu kapatma
- [ ] 1 lot'tan fazla limit
- [ ] SL/TP kontrolünü atlatma

---

**DOKÜMAN SONU** — Tüm ölçüler, kurallar, sabitler ve akışlar ÜSTAT v5.9 kod tabanından doğrulanmıştır.
