# ÜSTAT v5.9 — Denetim Raporu Doğrulama Çalışması

**Tarih:** 13 Nisan 2026
**Tür:** Kod incelemesi, bulgu doğrulaması (kod değişikliği YAPILMAMIŞTIR)
**Kapsam:** 13 Nisan 2026 tarihli Dashboard Denetim Raporu'ndaki 7 ana bulgu
**Yöntem:** Her bulgu için belirtilen dosya ve satırlar okundu, iddialar kodla karşılaştırıldı

---

## Yönetici Özeti

Denetim raporundaki 7 bulgunun **6'sı tam doğrulandı**, **1'i kısmen doğrulandı**. Raporda "FALSE" olarak görünebilecek tek madde dahi incelendiğinde kanıtla uyumlu çıktı. Yani rapor genel olarak **yüksek doğruluklu** ve operasyonel olarak ciddiye alınmalıdır.

En kritik iki risk, raporun da vurguladığı gibi:

1. **Fail-open davranışlar** — API hatası durumunda sistem "her şey yolunda" sinyali veriyor (TopBar algo uyarısı + api.js fallback'leri). Canlı piyasada operatörün hatalı güven duymasına yol açar.
2. **Performans periyot filtresinin kısmi kırıklığı** — Backend `days` parametresini alıyor ama iç sorguda kullanmıyor; dahası frontend zaten stats/trades çağrılarını periyoda bağlamıyor. Dönem butonları kullanıcıya geri bildirim vermiyor.

| # | Bulgu | Öncelik | Doğrulama Sonucu |
|---|-------|---------|------------------|
| P1-A | Performans dönem filtreleri çalışmıyor | P1 | DOĞRULANDI (kısmi — iki katman birden kırık) |
| P1-B | API fallback katmanı hataları gizliyor | P1 | TAM DOĞRULANDI |
| P2-A | Trade History filtreli/filtresiz metrikleri karıştırıyor | P2 | TAM DOĞRULANDI |
| P2-B | TopBar "ALGO KAPALI" fail-open | P2 | TAM DOĞRULANDI |
| P3-A | Auto Trading aktif kontrat sayısı sabit 15 | P3 | TAM DOĞRULANDI |
| P3-B | NewsPanel `worst_severity` eksik | P3 | TAM DOĞRULANDI |
| P3-C | UstatBrain gereksiz performans fetch'i | P3 | TAM DOĞRULANDI |

---

## P1-A — Performans Dönem Filtreleri Çalışmıyor

**Rapor İddiası:** 1Ay / 3Ay / 6Ay / 1Yıl butonları aktif görünüyor ama aynı veriyi gösteriyor; `getTradeStats` ve `getTrades` sabit `stats_baseline` ile çağrılıyor, backend `/api/performance` `days` parametresini kullanmıyor.

**Doğrulama Sonucu:** DOĞRULANDI — ve aslında durum raporun söylediğinden biraz daha ilginç: kırıklık iki katmanda birden var.

### Kanıt 1 — Frontend: `days` değişiyor ama stats/trades çağrıları sabit

`desktop/src/components/Performance.jsx`:
- Satır 156: `const [days, setDays] = useState(90);`
- Satır 363: `onClick={() => setDays(d)}` (butonlar state'i değiştiriyor)
- Satır 202: `getPerformance(days)` — **days doğru geçiyor**
- Satır 203: `getTradeStats(1000, baselineInfo.stats_baseline)` — **baseline sabit, days yok**
- Satır 204: `getTrades({ since: baselineInfo.stats_baseline, limit: 1000 })` — **baseline sabit, days yok**
- Satır 210: `}, [days, baselineInfo.stats_baseline]);` — effect yeniden çalışıyor ama sorgu parametresi değişmediği için backend aynı cevabı veriyor

### Kanıt 2 — Backend: `days` kabul ediliyor ama kullanılmıyor

`api/routes/performance.py`:
- Satır 25: `async def get_performance(days: int = Query(30, ge=1, le=365))` — parametre imzada var
- Satır 39-40: `baseline = get_stats_baseline()` ve `trades = db.get_trades(since=baseline, limit=5000)` — **`days` hiçbir yerde `baseline` veya `since` üretiminde kullanılmıyor**

### Yorum

Rapor "backend `days`'i almıyor" diyor; aslında **alıyor ama işlemiyor**. Bu daha tehlikeli çünkü OpenAPI şemasında parametre görünüyor, ama hiçbir şey yapmıyor. Sonuç aynı: operatör bir periyoda tıkladığında hiçbir şey değişmiyor.

---

## P1-B — API Fallback Katmanı Hataları Gizliyor

**Rapor İddiası:** `getStatus`, `getRisk`, `getHealth` hata aldığında "TREND, can_trade=true, risk_multiplier=1" gibi güven verici default değerler dönüyor.

**Doğrulama Sonucu:** TAM DOĞRULANDI. Üç kritik fonksiyonun da catch bloğu sistemi "normal görünümde" tutuyor.

### Kanıt — `desktop/src/services/api.js`

`getStatus()` fallback (Satır 39-54):

```
version: '6.0.0',
engine_running: false,
mt5_connected: false,
regime: 'TREND',          ← sanki trend varmış gibi
regime_confidence: 0,
risk_multiplier: 1,       ← sanki tam risk alınabilirmiş gibi
phase: 'stopped',
kill_switch_level: 0,
...
```

`getRisk()` fallback (Satır 150-156):

```
daily_pnl: 0,
can_trade: true,          ← sanki işlem açılabilirmiş gibi
kill_switch_level: 0,
regime: 'TREND',
risk_multiplier: 1,
open_positions: 0,
```

`getHealth()` fallback (Satır 608-611):

```
cycle: {}, mt5: {}, orders: {}, layers: {},
recent_events: [], system: {},
```

### Yorum

Bu en kritik bulgu. Üç farklı kart (rejim göstergesi, risk kartı, algo uyarısı) aynı anda "OK" diyebilir ve API kapalı olabilir. Finansal sistemde "bilmiyorum" ile "her şey yolunda" arasındaki fark zaaflar üretir. Rapor önerisi (unknown/stale rozeti) tamamen yerinde.

---

## P2-A — Trade History Filtreli/Filtresiz Metrikleri Karıştırıyor

**Rapor İddiası:** Sol taraf `filteredTrades/filteredStats` kullanıyor, sağ panel ise global `best_trade`, `worst_trade`, `sharpe_ratio`, `max_drawdown_pct`, `avg_duration_minutes` gösteriyor.

**Doğrulama Sonucu:** TAM DOĞRULANDI.

### Kanıt — `desktop/src/components/TradeHistory.jsx`

Filtreli hesap (sol):
- Satır 277-290: `filteredTrades` — symbol, side, result, period filtreleriyle
- Satır 306-333: `filteredStats = useMemo(() => { const pnls = filteredTrades.map(...) ...})`
- Satır 493-514: Özet kartlar `filteredStats.count`, `filteredStats.winRate`, `filteredStats.totalPnl` vs.

Global hesap (sağ):
- Satır 650: `stats?.best_trade`
- Satır 655: `stats?.worst_trade`
- Satır 659: `perf?.sharpe_ratio`
- Satır 660: `perf?.max_drawdown_pct`
- Satır 661: `stats?.avg_duration_minutes`

### Yorum

Kullanıcı "son 7 gün + BUY" dediğinde sol kartlar uyum sağlar, sağ panel hâlâ tüm zamanın rekorlarını gösterir. Aynı ekranda iki farklı evren. En azından "genel istatistik" etiketlemesi minimum düzeltme olmalı; ideal olan filtreli yeniden hesap.

---

## P2-B — TopBar "ALGO KAPALI" Uyarısı Fail-Open

**Rapor İddiası:** `getHealth()` boş dönerse `allowed !== false` bunu "açık" kabul ediyor.

**Doğrulama Sonucu:** TAM DOĞRULANDI.

### Kanıt — `desktop/src/components/TopBar.jsx`

- Satır 51: `const [tradeAllowed, setTradeAllowed] = useState(true);` — **default true**
- Satır 105: `const allowed = h?.mt5?.trade_allowed;`
- Satır 107: `setTradeAllowed(allowed !== false);`
- Satır 264-275: `{isConnected && !tradeAllowed && (<span>⚠ ALGO KAPALI</span>)}`

### Mantık Tablosu

| `allowed` değeri | `allowed !== false` | UI davranışı |
|------------------|---------------------|--------------|
| `true` (MT5 açık) | true | Uyarı YOK — doğru |
| `false` (MT5 kapalı) | false | Uyarı VAR — doğru |
| `undefined` (API hatası / fallback) | **true** | **Uyarı YOK — yanlış (fail-open)** |
| `null` | **true** | **Uyarı YOK — yanlış** |

### Zincirleme Risk

`getHealth()` hata verdiğinde (P1-B) `mt5 = {}` döner → `h?.mt5?.trade_allowed = undefined` → `undefined !== false = true` → uyarı gizlenir. Yani P1-B ile P2-B zincirleme olarak çalışıyor: ağ hatası sessizce "algo açık" görüntüsüne dönüşüyor.

---

## P3-A — Auto Trading Aktif Kontrat Sayısı Sabit 15

**Rapor İddiası:** Frontend `activeCount = 15 - deactCount` yapıyor.

**Doğrulama Sonucu:** TAM DOĞRULANDI.

### Kanıt — `desktop/src/components/AutoTrading.jsx`

- Satır 453: `const activeCount = 15 - deactCount;`
- Satır 457: `<span>{activeCount}/15 aktif</span>`

### Yorum

Watchlist 20'ye çıkarılırsa (veya 12'ye inerse) bu kart sessizce yanlışlaşır. `top5.score_map` veya `/api/settings/watchlist` uzunluğu backend kaynaklı olarak alınmalı. Düşük öncelik ama tipik "sessiz yanlışlaşma" kalıbı.

---

## P3-B — NewsPanel `worst_severity` Alanı REST Yanıtında Eksik

**Rapor İddiası:** Component `worst_severity` bekliyor, `NewsActiveResponse` şeması ve route bunu döndürmüyor.

**Doğrulama Sonucu:** TAM DOĞRULANDI.

### Kanıt

`desktop/src/components/NewsPanel.jsx`:
- Satır 79: `const { events, worst_sentiment, worst_severity, best_sentiment, active_count } = newsData;`
- Satır 87-90: `{worst_severity && worst_severity !== 'NONE' && (...)}` — rozeti gösteren şart

`api/schemas.py`:
- Satır 945 civarı `NewsActiveResponse`:

```
class NewsActiveResponse(BaseModel):
    count: int = 0
    events: list[NewsEventItem] = []
    best_sentiment: float | None = None
    worst_sentiment: float | None = None
    # worst_severity YOK
```

`api/routes/news.py`:
- Satır 85-89: `return NewsActiveResponse(count=..., events=..., best_sentiment=..., worst_sentiment=...)` — `worst_severity` gönderilmiyor.

Karşılaştırma: `NewsStatusResponse` (Satır 940 civarı) `worst_severity: str | None = None` alanına sahip. Yani alan başka bir şemada var, ama `active` endpoint'i bunu taşımıyor.

### Yorum

Silent fail: `undefined && …` falsy olduğu için hata atmıyor, ama rozet hiç çıkmıyor. Kullanıcı kritik bir haber severity'si olduğunu öğrenmiyor. Sözleşme uyumsuzluğu (contract drift) tipik örneği.

---

## P3-C — UstatBrain Gereksiz Performans Fetch'i

**Rapor İddiası:** Component `getPerformance(days)` çağırıyor ama sonucu görünür şekilde kullanmıyor.

**Doğrulama Sonucu:** TAM DOĞRULANDI.

### Kanıt — `desktop/src/components/UstatBrain.jsx`

- Satır 176: `const [perf, setPerf] = useState(null);`
- Satır 183-185: `const [b, p, s] = await Promise.all([ getUstatBrain(days), getPerformance(days), getStatus() ]);`
- Satır 189: `setPerf(p);`
- Satır 192: `}, [days]);`

JSX içinde `perf` değişkeni **hiçbir yerde okunmuyor**. (Satır 201 ve 363'teki `brain.regime_performance` farklı bir kaynak.)

### Yorum

Her gün `days` değiştikçe gereksiz `/api/performance` çağrısı. Temizlik borcu; kritik değil ama her çağrının görünür karşılığı olmalı prensibine aykırı.

---

## Raporun Dışında Dikkatimi Çeken Yan Bulgular

Doğrulama sırasında kod tabanında raporla tam örtüşen ek iki gözlem ortaya çıktı; ayrı bulgu olarak değil, mevcut bulguların pekiştiricisi olarak kayda geçirilmelidir.

**Zincirleme risk P1-B ↔ P2-B:** `getHealth()` fallback'i boş `mt5: {}` döndürdüğünde `TopBar.jsx:107` `tradeAllowed = true` yapıyor. Dolayısıyla bu iki bulgu ayrı ayrı değil, **tek bir dürüstlük açığı** olarak ele alınmalı: "API hatası → sistem 'normal' görünür". Düzeltme sırası önce fallback'leri `unknown` moduna çekmek, sonra `TopBar` üçlü mantığa geçmek olmalı (iki kart tek atışta düzelir).

**P1-A'nın görünmez yüzü:** Backend `days` parametresini OpenAPI'de tanımlıyor ama iç sorguda kullanmıyor. Bu, frontend ekibi için yanıltıcı: `curl ?days=7` de `?days=365` de aynı veriyi dönüyor. Olası tüketici (ör. ileride mobil ya da rapor scripti) aynı tuzağa düşer.

---

## Öncelik Önerisi

Raporun verdiği sıra teknik olarak doğru. Doğrulama ışığında küçük bir optimizasyon:

1. **P1-B + P2-B'yi birlikte çöz** — ortak kök: "API hatası = normal görünüm". İkisi aynı PR'da düzeltilirse test yüzeyi de tek olur.
2. **P1-A'yı ikinci sırada çöz** — hem frontend çağrı imzasını hem backend sorgu cutoff'unu aynı anda düzelt; yoksa yarısı yapılır ve kullanıcı yine aynı veriyi görür.
3. **P2-A** — en ucuz düzeltme "genel istatistik" etiketi; ideal düzeltme filtreli yeniden hesap.
4. **P3-A** — watchlist uzunluğunu config'den veya `/api/settings/watchlist`'ten almak.
5. **P3-B** — schema'ya `worst_severity: str | None` alanı eklemek; route'ta severity'yi türetmek.
6. **P3-C** — satır 185'teki gereksiz fetch'i ve satır 176, 189'daki ölü state'i kaldırmak.

---

## Metodoloji Notu

Bu çalışmada hiçbir dosyada değişiklik yapılmadı. Sadece okuma ve karşılaştırma yapıldı. Satır numaraları raporla aynı baz alınarak okundu; kayma bulunmadı. Doğrulama kanıtları yukarıdaki kod alıntılarıyla sınırlıdır ve orijinal denetim raporundaki dosya yolları birebir takip edilmiştir.

**Sonuç:** Denetim raporu gerçekten doğrudur. Özellikle P1 kategorisindeki iki bulgu canlı piyasada operatörün yanlış kararına dönüşebilecek "dürüstlük" açığıdır ve öncelikle ele alınmalıdır.
