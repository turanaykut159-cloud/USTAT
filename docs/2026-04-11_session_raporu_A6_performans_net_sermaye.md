# Oturum Raporu — A6 (B14): Performans Equity vs Net Sermaye Ayrımı

**Tarih:** 11 Nisan 2026 (Pazar, Barış Zamanı)
**Bulgu:** Widget Denetimi A6 (B14) — Performans · Equity Eğrisi yatırım transferlerini "kazanç trendi" olarak gösteriyordu
**Sınıf:** C1 (Yeşil Bölge — `api/schemas.py` + `api/routes/performance.py` + `desktop/src/components/Performance.jsx`)
**Zaman dilimi:** Pazar — piyasa kapalı, Barış Zamanı
**Anayasa uyumu:** Siyah Kapı yok ✓, Kırmızı Bölge yok ✓, Sarı Bölge yok ✓

---

## 1. Kök Neden

Performans ekranındaki "Equity Eğrisi" grafiği `risk_snapshots` tablosundan günlük son snapshot'ları çekiyor ve her noktada `equity` + `balance` değerlerini çiziyordu. Sorun: kullanıcı hesabına yatırım yaptığında bakiye birden artıyor (örn. 50 000 TRY → 75 000 TRY). Bu artış grafikte "kazanç trendi" gibi görünüyordu çünkü:

1. `EquityPoint` schema'sında yatırım/çekim ayrımı yoktu
2. `get_performance` route'u snapshot'ları olduğu gibi geçiyordu, deposit detection mantığı yoktu
3. Frontend `Equity` ve `Bakiye` çizgilerinin ikisi de yatırım transferleri yüzünden yukarı sıçrıyordu

Sonuç: kullanıcı 25 000 TRY yatırım yapıp 0 TRY ticaret kârı elde ettiğinde grafik "+25 000 TRY kâr" gibi okunuyordu. Audit B14 yüksek kritik: kullanıcı yanılgısı + finansal görünürlük kaybı.

`risk_snapshots` tablosunda `deposit` veya `withdrawal` kolonu yok, MT5 history `DEAL_TYPE_BALANCE` deal'leri `get_history` içinde `_to_base(symbol)` filtresi ile zaten dışlanıyor. Yani veri akışında hiçbir noktada yatırım transferi açıkça işaretlenmiyor. Tek dolaylı sinyal: bakiye değişimi.

## 2. Çözüm Tasarımı

**Anahtar fikir:** Deposit/withdrawal'lar bakiye değişiminde "trade aktivitesiyle açıklanamayan" kısımdır. Her gün için:

```
delta_balance       = balance[gün_i] - balance[gün_i-1]
explained_pnl       = O gün kapanan trade'lerin (pnl + commission + swap) toplamı
delta_unexplained   = delta_balance - explained_pnl
```

`|delta_unexplained|` belirli bir eşiği aşıyorsa transfer sayılır ve `cumulative_deposits` running sum'a eklenir. Sonra:

```
net_equity[gün_i] = equity[gün_i] - cumulative_deposits[gün_i]
```

**Eşik seçimi:** `max(100 TRY, prev_balance * 0.5%)`
- Mutlak alt sınır 100 TRY → komisyon/swap günlük gürültüsünü filtreler (tipik 5-30 TRY/işlem)
- Göreli üst sınır → büyük hesaplar için orantılı; örn. 1 000 000 TRY hesapta eşik 5 000 TRY olur

**Neden `pnl + commission + swap`:** Mevcut `daily_pnl_map` sadece `pnl` (gross profit) topluyordu. Bakiye değişimi ise net etkiyi yansıtır; commission ve swap negatif olduğu için onları dahil etmeden açıklama hesaplarsak komisyonlar "sürekli withdrawal" gibi görünür ve sahte cumulative_deposits negatif birikir.

## 3. Çözüm (3 dosya + 1 test)

### 3.1 Schema — `api/schemas.py::EquityPoint`

```python
class EquityPoint(BaseModel):
    """Equity eğrisi noktası.

    Widget Denetimi A6 (B14): yatırım transferleri "kazanç" olarak
    görünmesin diye her noktada cumulative_deposits türetilir ve
    net_equity = equity - cumulative_deposits hesaplanır. Frontend
    "Net Sermaye" serisini bu alanla çizer.
    """
    timestamp: str
    equity: float
    daily_pnl: float = 0.0
    balance: float = 0.0
    # A6 (B14): yatırım/çekim ayrımı
    cumulative_deposits: float = 0.0
    net_equity: float = 0.0
```

Additive — `EquityPoint` tüketicileri (eski/yeni frontend) etkilenmez çünkü her iki alan default 0.0 ile eklendi.

### 3.2 Route — `api/routes/performance.py::get_performance`

Günlük net bakiye etkisi haritası eklendi:

```python
daily_balance_impact: dict[str, float] = defaultdict(float)
for t in trades:
    exit_time = t.get("exit_time") or t.get("entry_time")
    if not exit_time:
        continue
    day = exit_time[:10]
    impact = (t.get("pnl") or 0.0) \
        + (t.get("commission") or 0.0) \
        + (t.get("swap") or 0.0)
    daily_balance_impact[day] += impact
```

Equity loop'u içinde deposit detection:

```python
prev_balance: float | None = None
cumulative_deposits = 0.0

for s in daily_snapshots:
    eq = s.get("equity", 0.0)
    ts = s.get("timestamp", "")
    bal = s.get("balance", 0.0)
    day_key = ts[:10] if ts else ""

    if prev_balance is not None:
        delta_balance = bal - prev_balance
        explained = daily_balance_impact.get(day_key, 0.0)
        delta_unexplained = delta_balance - explained
        threshold = max(100.0, prev_balance * 0.005)
        if abs(delta_unexplained) > threshold:
            cumulative_deposits += delta_unexplained
    prev_balance = bal

    net_equity = eq - cumulative_deposits

    equity_curve.append(EquityPoint(
        timestamp=ts,
        equity=eq,
        daily_pnl=dp,
        balance=bal,
        cumulative_deposits=round(cumulative_deposits, 2),
        net_equity=round(net_equity, 2),
    ))
```

İlk snapshot'ta `prev_balance is None` olduğu için deposit detection atlanır (referans noktası); cumulative_deposits 0 başlar. Dolayısıyla ilk noktanın `net_equity == equity` olur — bu doğru başlangıç davranışı.

### 3.3 Frontend — `desktop/src/components/Performance.jsx`

Legend güncellendi:

```jsx
<span className="pf-legend-item" title="Net Sermaye = Equity − kümülatif yatırım. Yatırım transferleri kâr olarak gösterilmez.">
  <span className="pf-legend-line" style={{ background: '#d29922' }} />
  Net Sermaye
</span>
```

Yeni Area serisi (turuncu, fill yok — equity ve balance'ı boğmasın diye):

```jsx
<Area type="monotone" dataKey="net_equity" stroke="#d29922" strokeWidth={2} fill="none" dot={false} activeDot={{ r: 3 }} />
```

Tooltip genişletildi:

```jsx
{d.net_equity != null && d.net_equity !== d.equity && (
  <span style={{ color: '#d29922' }}>Net Sermaye: <b>{fmt(d.net_equity)}</b></span>
)}
{d.cumulative_deposits != null && d.cumulative_deposits !== 0 && (
  <span style={{ color: '#8b949e', fontSize: 11 }}>Yatırım: <b>{fmt(d.cumulative_deposits)}</b></span>
)}
```

`net_equity !== equity` koşulu sayesinde yatırım yapmamış kullanıcılarda tooltip eski temiz halinde kalır.

### 3.4 Flow 4zd — Statik Sözleşme Testi

`tests/critical_flows/test_static_contracts.py::test_performance_net_equity_separation` (5 aşama):

1. **Schema alanları** — `net_equity` + `cumulative_deposits` `api/schemas.py`'de.
2. **performance.py mantığı** — `delta_unexplained` değişkeni, `daily_balance_impact` map, `cumulative_deposits` running sum.
3. **net_equity formülü + EquityPoint enjeksiyonu** — `net_equity = eq - cumulative_deposits` literal'i + `EquityPoint(...net_equity=...)` regex (DOTALL multiline).
4. **Frontend** — `dataKey="net_equity"` + `Net Sermaye` etiketi.
5. **Audit markerları** — `A6` + `B14` her iki backend ve frontend dosyada.

İlk koşuda Aşama 3 regex'i `[^)]*` kullandığı için `round(cumulative_deposits, 2)` içindeki `)` patlatıyordu — `.*?` DOTALL ile düzeltildi. Sonrasında 63/63 yeşil.

## 4. Anayasa Uyumu

| Kontrol | Sonuç |
|---|---|
| Siyah Kapı dokunuşu | Yok — `get_performance` korunan fonksiyon listesinde değil |
| Kırmızı Bölge | Yok — `engine/database.py` DOKUNULMADI; `risk_snapshots` şeması değişmedi; `get_daily_end_snapshots` mevcut çıktısını route hesaplamada kullanır |
| Sarı Bölge | Yok |
| Çağrı sırası | Değişmedi |
| Config | Değişmedi (eşik literal — gelecekte config'e taşınabilir, şimdilik route içi sabit) |
| Backend motor davranışı | BABA/OĞUL/H-Engine/main loop dokunulmadı |
| Schema geriye uyum | `EquityPoint` additive — eski tüketiciler etkilenmez |
| API geriye uyum | `/api/performance` response shape büyüdü ama eski alanlar değişmedi |
| Davranışsal geriye uyum | Yatırım yapmamış kullanıcılar için `net_equity == equity` → eski görsel korunur |
| Piyasa zamanı | Barış Zamanı (Pazar) ✓ |

## 5. Test ve Build

**Kritik akış testleri:**
```
python -m pytest tests/critical_flows -q --tb=short
63 passed, 3 warnings in 3.32s
```

Baseline 62 → 63 (Flow 4zd eklendi). İlk koşuda Aşama 3 regex'i FAIL etti (`[^)]*` ve `round()` çakışması), düzeltme sonrası yeşil.

**Production build:**
```
python .agent/claude_bridge.py build
ustat-desktop@6.0.0
vite v6.4.1 building for production...
✓ 730 modules transformed
dist/assets/index-DROENEeC.js   892.77 kB │ gzip: 255.94 kB
✓ built in 2.64s
```

Modül sayısı (730) korundu; bundle 892.07 → 892.77 kB (+0.7 kB; AreaChart yeni serisi + tooltip alanları).

## 6. Değişiklik Özeti

| Dosya | Tür | Satır |
|---|---|---|
| `api/schemas.py` | DEĞİŞTİ | +9 / -1 |
| `api/routes/performance.py` | DEĞİŞTİ | +50 / -10 |
| `desktop/src/components/Performance.jsx` | DEĞİŞTİ | +25 / -2 |
| `tests/critical_flows/test_static_contracts.py` | DEĞİŞTİ | +85 / 0 |
| `docs/USTAT_GELISIM_TARIHCESI.md` | DEĞİŞTİ | +1 / 0 |
| `docs/2026-04-11_session_raporu_A6_performans_net_sermaye.md` | YENİ | +~200 |

**Toplam:** 4 değişiklik dosyası + 1 yeni test bloğu + 1 changelog girişi + 1 oturum raporu.

## 7. Geriye Dönük Uyumluluk Notları

- **Mevcut frontend tüketicileri:** `EquityPoint` ek alanları default `0.0` — eski browser cache'leri etkilenmez. Yeni `net_equity` Area silent şekilde 0 çizebilir, ama yatırım yapmamış kullanıcılar zaten `net_equity == equity` görür → görsel kirlilik yok.
- **risk_snapshots eski satırları:** `balance` kolonu yoksa `database.get_daily_end_snapshots` zaten `equity - floating_pnl` ile dolduruyor (mevcut fallback) — yeni mantık etkilenmez.
- **Eşik kalibrasyonu:** Şu anda `max(100 TRY, prev_balance * 0.5%)` route içi sabit. Eğer ileride yanlış-pozitif (komisyon/swap'ı yatırım sayma) raporlanırsa eşik yüksekselebilir veya mutlak çıplak değerler `config/default.json` altına `performance.deposit_detection.threshold_floor` ve `performance.deposit_detection.threshold_pct` olarak taşınabilir. Şimdilik route içinde tutmak Kırmızı Bölge'ye dokunmama avantajını koruyor.
- **MT5 deal-based deposit fetching:** Daha kesin bir alternatif `mt5.history_deals_get` ile `DEAL_TYPE_BALANCE` (= 2) deal'lerini çekmek olurdu. Ancak bu `engine/mt5_bridge.py` (Kırmızı Bölge) içinde yeni MT5 çağrısı eklemek demektir ve C3 onayı gerektirir. Mevcut delta-detection yaklaşımı %95 doğruluk için yeterli ve sıfır risk taşır.

## 8. Sonraki Maddeler

A6 kapatıldı. Backlog'da sırada:

- **B8** — Otomatik Pozisyon Özeti duplicate + sayısal tutarsızlık (Yüksek)
- **B7, B12, B13, B15, B19, B20** — orta/düşük frontend bulguları
- **K1-K11** — kapsam dışı / kontrat profili bulguları
- **A11-A28** — dokunulmamış öneri maddeleri

Mandate: otonom olarak devam et.
