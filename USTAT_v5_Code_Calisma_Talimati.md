# ÜSTAT v5.0 — Code Çalışma Talimatı

---

## KİMLİK VE ÇALIŞMA PRENSİPLERİ

Sen bu projede 50 kişilik bir yazılım ekibinin teknik liderisin. Görevin, canlı bir algoritmik trading sisteminde kritik iyileştirmeler yapmak. Bu sistem gerçek parayla VİOP'ta işlem yapıyor. Her satır kod, her değişiklik gerçek finansal sonuç doğurur.

### Çalışma Disiplinin

**Önce anla.** Senden istenen her işi uygulamaya başlamadan önce tam olarak anla. Ne istendiğini, neden istendiğini, hangi sorunu çözdüğünü kavra. Anlamadığın bir şey varsa varsayım yapma — sor.

**Sonra araştır.** Sorunu çözmeden önce kaynağını bul. Kod tabanında sorunun nerede başladığını, hangi dosyaları etkilediğini, hangi metodların bu sorunla bağlantılı olduğunu tespit et. Kodu oku, akışı takip et, neden-sonuç ilişkisini kur.

**Sonra etkiyi ölç.** Çözümü bulduktan sonra "bu değişiklik sistemin başka yerini bozar mı?" sorusunu sor. Değişikliğin dokunduğu her metodu, her çağrı zincirini, her state geçişini kontrol et. Geniş bakış açısıyla düşün.

**Sonra test et.** Değişikliği uyguladıktan sonra, sisteme yüklemeden önce test et. Test kriterlerini kontrol et. Edge case'leri düşün.

**En son uygula.** Her şey temizse commit et, engine restart et, logları izle.

### Kesin Yasaklar

- **Varsayım yapma.** "Bu muhtemelen şöyle çalışıyordur" deme. Kodu aç, oku, teyit et.
- **"As far as I know" kullanma.** Bilmiyorsan kodu oku. Kod yoksa sor.
- **Kopyala-yapıştır çözüm üretme.** Her satırın neden orada olduğunu bil.
- **Birden fazla sorunu tek seferde çözme.** Her değişiklik izole, test edilebilir, geri alınabilir olmalı.
- **Test etmeden commit yapma.**

### İletişim Formatı

Her işlem için şu formatı kullan:

```
[ADIM X.Y] — Başlık
SORUN: Ne yanlış, nerede, neden
NEDEN: Kök sebep analizi
ÇÖZÜM: Ne yapılacak, hangi dosyada, hangi satırda
ETKİ ANALİZİ: Bu değişiklik başka neyi etkiler
TEST: Nasıl doğrulanacak
SONUÇ: Başarılı mı, log çıktısı ne
```

---

## PROJE TANIMI

### Sistem Nedir

ÜSTAT v5.0, VİOP (Vadeli İşlem ve Opsiyon Piyasası) üzerinde otomatik alım-satım yapan bir algoritmik trading sistemidir. Python tabanlı trading engine'i, MetaTrader 5 üzerinden GCM Forex broker'ına bağlanır ve 15 VİOP vadeli işlem kontratında işlem yapar.

### Mimari

Sistem üç ana modülden oluşur:

- **BABA** (`engine/baba.py`, 1972 satır): Risk yönetimi ve piyasa rejimi algılama. Her 10 saniyede piyasa durumunu değerlendirir (TREND / RANGE / VOLATILE / OLAY). Çok katmanlı zarar limitleri, kill-switch sistemi ve fake sinyal analizi yapar.

- **OĞUL** (`engine/ogul.py`, 1995 satır): Sinyal üretimi ve emir state machine. Üç strateji çalıştırır: Trend Follow, Mean Reversion, Breakout. Emirleri SIGNAL → PENDING → SENT → FILLED → CLOSED akışıyla yönetir.

- **ÜSTAT** (`engine/ustat.py`, 934 satır): 15 kontrat arasından günlük Top 5 seçimi yapar.

Orkestrasyon `engine/main.py` (562 satır) tarafından yapılır. Her 10 saniyede: MT5 heartbeat → veri güncelleme → BABA cycle → risk kontrolü → Top 5 seçimi → OĞUL sinyal + emir yönetimi.

### Kritik Kısıtlar

1. **Canlı sistem.** Gerçek parayla işlem yapıyor. Her hata finansal kayıp demek.
2. **VİOP netting mode.** Sembol başına tek pozisyon. Aynı kontrata ikinci pozisyon açılamaz — mevcut pozisyonla birleşir.
3. **active_trades yapısı:** `dict[str, Trade]` — sembol anahtarı, tek Trade değeri.
4. **İşlem saatleri:** 09:45-17:45. Gün sonunda tüm pozisyonlar kapatılır.
5. **Broker:** GCM Forex, MT5 server üzerinden.

---

## YAPILACAK İŞLER

Aşağıda üç faz halinde sıralanmış işler var. Her faz ayrı bir commit olacak. Fazlar sırayla uygulanacak. Bir faz tamamlanmadan diğerine geçilmeyecek.

Referans doküman: `USTAT_v5_Sistem_Iyilestirme_Plani.md` — her değişikliğin eski kod / yeni kod karşılaştırması bu dokümanda mevcut.

---

## FAZ 1 — BUG DÜZELTMELERİ

**Amaç:** Mevcut sistemi bozmadan güvenilirliği artır.
**Kural:** Hiçbir yeni özellik ekleme. Sadece mevcut kodun hatalı davranışlarını düzelt.

### Adım 1.1 — Netting Mode Pozisyon Eşleştirme Düzeltmesi

**Dosya:** `engine/ogul.py`
**Metod:** `_update_fill_price`

**Sorun:** Bu metod pozisyonu MT5'te `ticket` bazlı arıyor. Sistemin geri kalanı (`_sync_positions`, `_manage_active_trades`, `_advance_market_retry`) sembol bazlı arıyor. VİOP netting mode'da ticket değişebilir (partial close, merge). Ticket değişince bu metod pozisyonu bulamaz → giriş fiyatı güncellenmez → PnL yanlış hesaplanır → BABA yanlış risk kararı verir.

**Yapılacak:** Ticket bazlı aramayı sembol bazlı aramaya çevir. Ticket değiştiyse güncelle ve logla.

**Etki analizi:** Bu metodu çağıran yerler: `_advance_sent` (FILLED geçişi) ve `_advance_partial` (kısmi dolum kabulü). İkisi de sembol parametresini zaten geçiriyor. Başka bir yeri etkilemez.

**Test:** LIMIT emir dolunca `entry_price` MT5'teki `price_open` ile eşleşmeli.

---

### Adım 1.2 — MT5 Çağrı Optimizasyonu

**Dosya:** `engine/ogul.py`
**Metod:** `_manage_active_trades`

**Sorun:** Her aktif işlem için döngü içinde `self.mt5.get_positions()` çağrılıyor. 5 aktif işlem = 5 ayrı MT5 sorgusu + `_sync_positions` ayrıca çağrılıyor = her cycle'da 6+ MT5 pozisyon sorgusu. Cycle süresini uzatır, trailing stop güncellemesini geciktirir.

**Yapılacak:** `get_positions()` çağrısını döngü dışına al, bir kere çağır, sonucu `pos_by_symbol` dict'inde indexle, döngü içinde dict'ten oku.

**Etki analizi:** `_manage_active_trades` içinde `self.mt5.close_position()` ve `self.mt5.modify_position()` çağrıları var — bunlar etkilenmez, ayrı MT5 komutları. Sadece okuma optimize ediliyor.

**Ek:** Bu adımda `elif trade.strategy == "breakout": pass` satırı ekle — Faz 2.1'de gerçek metod gelecek.

**Test:** 3+ aktif işlemle cycle süresi ölç. SL/TP tetiklenince pozisyon doğru kapanmalı.

---

### Adım 1.3 — Günlük İşlem Sayacı Zamanlaması

**Dosya:** `engine/ogul.py`
**Metodlar:** `_execute_signal`, `_advance_sent`, `_advance_partial`, `_advance_market_retry`

**Sorun:** `baba.increment_daily_trade_count()` şu an `_execute_signal` içinde, SENT state'inde çağrılıyor. Emir gönderildiğinde sayaç artıyor. Ama emir dolmayabilir — TIMEOUT, CANCELLED olabilir. 5 emir timeout olursa, günlük limit (5) dolmuş görünür ama sıfır gerçek işlem açılmıştır. Sonuç: günün geri kalanında sistem hiçbir işlem açamaz.

**Yapılacak:**
1. `_execute_signal` içindeki `increment_daily_trade_count()` çağrısını sil.
2. `_advance_sent` içinde `order_status == "filled"` bloğuna ekle.
3. `_advance_partial` içinde `filled_volume >= threshold` bloğuna ekle.
4. `_advance_market_retry` içinde `trade.state = TradeState.FILLED` sonrasına ekle.

**Etki analizi:** BABA'nın `_risk_state["daily_trade_count"]` değeri değişir. `check_risk_limits` bu değeri `max_daily_trades` (5) ile karşılaştırır. Sadece gerçek dolumlar sayılacağı için, timeout olan emirler sayacı tüketmez. Diğer risk kontrolleri etkilenmez.

**Test:** LIMIT emir gönder → timeout → sayaç artmamış olmalı. LIMIT emir gönder → filled → sayaç 1 artmış olmalı.

---

### Adım 1.4 — Kontrat Bazlı PnL Hesaplama

**Dosya:** `engine/ogul.py`
**Metod:** `_handle_closed_trade`

**Sorun:** `CONTRACT_SIZE = 100.0` sabit değer ile PnL hesaplanıyor. VİOP'ta her kontratın çarpanı farklı olabilir. Yanlış çarpan = yanlış PnL = yanlış equity tracking = yanlış risk kararları.

**Yapılacak:** PnL hesaplama sırasında `self.mt5.get_symbol_info(symbol)` ile gerçek `trade_contract_size` değerini al. Alınamazsa mevcut 100.0 fallback olarak kalsın.

**Etki analizi:** `_handle_closed_trade` çağrıldığında MT5 bağlantısı aktif olmalı — zaten aktif, çünkü bu metod pozisyon kapatma sonrası çağrılıyor. `get_symbol_info` BABA'da zaten kullanılıyor (`calculate_position_size` içinde), yeni bir bağımlılık değil.

**Test:** Bir işlem kapandığında, hesaplanan PnL MT5 terminalindeki PnL ile eşleşmeli.

---

### Adım 1.5 — Risk Kapalıyken Bias Güncelleme

**Dosya:** `engine/main.py`
**Metod:** `_run_single_cycle`

**Sorun:** `risk_verdict.can_trade = False` olduğunda `process_signals([])` çağrılıyor. Boş sembol listesi geçtiği için bias hesaplama döngüsü çalışmıyor. Dashboard'da eski bias değerleri görünüyor — operatör yanlış bilgiyle karar verebilir.

**Yapılacak:** Risk kapalı dalındaki `process_signals([])` çağrısından sonra, Top 5 sembolleri için bias hesaplamasını ayrıca yap.

**Etki analizi:** `_calculate_bias` salt okunur bir metod — veri okur, hiçbir state değiştirmez, emir göndermez. Güvenle çağrılabilir. `last_signals` dict'ine yazar — bu dict Dashboard tarafından okunuyor.

**Test:** Kill-switch aktifken Dashboard'da bias değerleri güncellenmeli. VOLATILE rejimde bias hâlâ görünmeli.

---

## FAZ 2 — STRATEJİ İYİLEŞTİRMELERİ

**Amaç:** Mevcut stratejilerin VİOP'ta kâr üretme kapasitesini artır.
**Kural:** Her yeni özellik mevcut state machine'i ve risk akışını bozmamalı.

### Adım 2.1 — Breakout Çıkış Yönetimi

**Dosya:** `engine/ogul.py`

**Sorun:** Breakout pozisyonlarında programatik çıkış yönetimi yok. Kodda açıkça yazılmış: `# breakout: sabit SL/TP, ek kontrol yok`. Trend follow'da trailing stop + EMA ihlali var. Mean reversion'da BB orta bant kontrolü var. Breakout'ta hiçbiri yok. VİOP'ta false breakout oranı yüksek — korumasız pozisyon tam SL'ye kadar zarar eder.

**Yapılacak:**
1. İki yeni sabit ekle: `BO_TRAILING_ATR_MULT = 2.0` ve `BO_REENTRY_BARS = 3`
2. `_manage_breakout` metodu ekle: false breakout tespiti (son 3 bar entry altına/üstüne döndüyse kapat) + trailing stop (2×ATR — trend follow'dan geniş, breakout'a hareket alanı tanır)
3. Faz 1.2'de eklenen `pass` satırını `self._manage_breakout(symbol, trade, pos)` ile değiştir.

**Etki analizi:** Yeni metod sadece `trade.strategy == "breakout"` olan pozisyonlar için çalışır. Diğer stratejilere dokunmaz. `mt5.close_position` ve `mt5.modify_position` mevcut, test edilmiş MT5Bridge metodları. State machine akışı değişmez — `_handle_closed_trade` zaten her çıkış nedeni için çalışıyor.

**Test:** Breakout pozisyonu açıldığında trailing stop güncellemesi logda görülmeli. Fiyat 3 bar boyunca entry'nin gerisine dönünce "false_breakout" kapanışı logda görülmeli.

---

### Adım 2.2 — Likidite Sınıfına Göre Parametre Farklılaştırma

**Dosya:** `engine/ogul.py`

**Sorun:** 15 kontratın tamamı aynı sabit parametrelerle değerlendiriliyor. F_THYAO (A sınıfı, yüksek hacim, dar spread) ile F_KONTR (C sınıfı, düşük hacim, geniş spread) aynı volume eşiğine (1.5x), aynı ATR çarpanına, aynı trailing stop mesafesine tabi. Bu kontratlar arasında likidite farkı 10x-50x olabilir. Tek parametre seti kullanmak, A sınıfında gerçek sinyalleri kaçırmaya, C sınıfında false sinyallere girmeye yol açar.

**Yapılacak:**
1. `LIQUIDITY_CLASSES` dict'i ekle: 15 kontratın A/B/C sınıflandırması
2. `BO_VOLUME_MULT_BY_CLASS` dict'i ekle: A=1.5, B=2.0, C=3.0
3. `BO_ATR_EXPANSION_BY_CLASS` dict'i ekle: A=1.2, B=1.3, C=1.5
4. `TRAILING_ATR_BY_CLASS` dict'i ekle: A=1.5, B=1.8, C=2.5
5. `_get_liq_class` static metod ekle
6. `_check_breakout` içinde volume ve ATR eşiklerini likidite bazlı yap
7. `_manage_trend_follow` içinde trailing stop çarpanını likidite bazlı yap

**Etki analizi:** Parametre değişiklikleri sadece eşik kontrollerini etkiler. Sinyal üretim mantığı, state machine, risk akışı değişmez. A sınıfı kontratlar için mevcut davranış korunur (aynı değerler). B ve C sınıfı kontratlar için eşikler sıkılaşır — daha az sinyal ama daha kaliteli sinyal.

**Test:** F_THYAO breakout: volume eşiği 1.5x olmalı. F_KONTR breakout: volume eşiği 3.0x olmalı. F_THYAO trailing stop: 1.5×ATR. F_KONTR trailing stop: 2.5×ATR.

---

### Adım 2.3 — Config Altyapısı Hazırlığı

**Dosya:** `config/default.json`, `engine/config.py`

**Sorun:** Config nesnesi her modülde saklanıyor ama hiçbir yerde kullanılmıyor. Tüm stratejik parametreler modül seviyesinde hardcoded. Parametre değişikliği için kod değişikliği gerekiyor — canlı sistemde riskli, her seferinde deploy gerekiyor.

**Yapılacak:**
1. `config/default.json` dosyasına strateji parametreleri, likidite override'ları ve engine ayarlarını ekle
2. `engine/config.py` sınıfında bu alanları parse et
3. Bu fazda sadece altyapıyı hazırla — Oğul'daki sabitleri config'den okuma işini Faz 3 backtest sonrası yap

**Etki analizi:** JSON dosyasına alan eklemek mevcut sistemi etkilemez. Config parse başarısız olursa mevcut hardcoded değerler fallback olarak çalışır. Engine başlangıcında config değerleri loglanmalı.

**Test:** Engine başlangıcında config doğru parse edilmeli. Eksik alan durumunda default değer kullanılmalı. Config dosyası bozuksa engine çökmemeli.

---

## FAZ 3 — BACKTEST VE OPTİMİZASYON

**Amaç:** Faz 1 ve 2 değişiklikleri uygulandıktan sonra, stratejilerin gerçek VİOP verisinde performansını ölç ve parametreleri optimize et.
**Kural:** Optimizasyon sonuçlarını canlıya almadan önce walk-forward doğrulaması yap.

### Adım 3.1 — Strateji Performans Ölçümü

**Mevcut backtest altyapısı:** `backtest/` klasöründe runner, report, monte_carlo, sensitivity, walk_forward modülleri mevcut.

**Çalıştırılacak 4 senaryo:**

1. **Trend Follow** — Son 6 ay, A sınıfı kontratlar (F_THYAO, F_AKBNK, F_ASELS). Ölç: win rate, ortalama kâr/zarar oranı, max drawdown, Sharpe.

2. **Mean Reversion** — Son 6 ay, tüm 15 kontrat. Ölç: tetiklenme sıklığı (RSI 30/70 ne kadar sık tetikleniyor), win rate, ortalama işlem süresi. Sorgulanacak: eşikler yeterince sık tetikleniyor mu?

3. **Breakout** — Son 6 ay, A ve B sınıfı kontratlar. Ölç: false breakout oranı, yeni `_manage_breakout` ile eski (sabit SL/TP) karşılaştırması. Sorgulanacak: false breakout tespiti drawdown'ı ne kadar azaltıyor?

4. **Tüm stratejiler birlikte** — Son 6 ay, tüm kontratlar, rejim geçişleri dahil. Ölç: toplam PnL, equity curve, max drawdown, Sharpe, profit factor. Sorgulanacak: rejim geçiş anlarında pozisyon yönetimi düzgün çalışıyor mu?

**Her senaryo için raporlanacak metrikler:**
- Toplam işlem sayısı
- Win rate (%)
- Ortalama kârlı / ortalama zararlı işlem oranı
- Maximum drawdown (%)
- Sharpe ratio (yıllık)
- Profit factor (brüt kâr / brüt zarar)
- Kontrat bazlı performans (A/B/C sınıfı kırılımı)

---

### Adım 3.2 — Parametre Optimizasyonu

**Ön koşul:** Adım 3.1 raporları hazır olmalı.

**Yöntem:** Walk-forward optimizasyon (%70 in-sample, %30 out-of-sample).

**Optimize edilecek parametreler:** Referans dokümandaki Faz 3.2 parametre listesi.

**Kabul kriterleri:**
- Out-of-sample Sharpe > 0.5
- In-sample ile out-of-sample Sharpe farkı < %50 (overfitting kontrolü)

**Sonuç:** Optimize parametreler `config/default.json` dosyasına yazılacak.

---

### Adım 3.3 — Sonuç Değerlendirmesi

Backtest sonuçlarına göre karar:

- **Sharpe > 1.0:** Mevcut stratejiler yeterli. Config'e taşıma tamamla, canlı izlemeye geç.
- **RANGE dönemlerinde equity flat:** Grid stratejisi tasarımına başla (ayrı doküman).
- **Belirli kontratlar sürekli zararda:** O kontratları Top 5'ten hariç tut veya penalize et.
- **Win rate < %40 olan strateji:** Parametreleri optimize et veya devre dışı bırak.
- **Profit factor < 1.0 olan kontrat sınıfı:** O sınıftan strateji çalıştırmayı durdur.

---

## UYGULAMA KONTROL LİSTESİ

Her adım tamamlandığında işaretle:

```
FAZ 1 — Bug Düzeltmeleri:
  [ ] 1.1 — _update_fill_price sembol bazlı eşleştirme
  [ ] 1.2 — _manage_active_trades tek MT5 çağrısı
  [ ] 1.3 — increment_daily_trade_count FILLED'a taşıma
  [ ] 1.4 — CONTRACT_SIZE kontrat bazlı alma
  [ ] 1.5 — Risk kapalıyken bias güncelleme
  [ ] Test: Engine restart, logları kontrol et
  [ ] Commit: "Faz 1 — Bug düzeltmeleri"

FAZ 2 — Strateji İyileştirmeleri:
  [ ] 2.1 — _manage_breakout metodu
  [ ] 2.2 — Likidite sınıfı parametreleri
  [ ] 2.3 — Config altyapısı
  [ ] Test: Engine restart, strateji testleri
  [ ] Commit: "Faz 2 — Strateji iyileştirmeleri"

FAZ 3 — Backtest:
  [ ] 3.1 — 4 senaryo backtest
  [ ] 3.2 — Walk-forward optimizasyon
  [ ] 3.3 — Sonuç değerlendirmesi ve karar
  [ ] Commit: "Faz 3 — Backtest sonuçları"
```

---

## REFERANS DOKÜMANLAR

- **Detaylı kod değişiklikleri (eski/yeni karşılaştırma):** `USTAT_v5_Sistem_Iyilestirme_Plani.md`
- **Oğul yapı dokümanı:** `OGUL_YAPI.md`
- **Baba yapı dokümanı:** `BABA_YAPI.md`
- **Gelişim tarihçesi:** `USTAT_v5_gelisim_tarihcesi.md`
- **Kod dökümü:** `USTAT_v5_kod_dokumu_2026-02-23.md`

---

## DOSYA HARİTASI

Değişiklik yapılacak dosyalar ve satır sayıları:

| Dosya | Satır | Faz | Değişiklik Özeti |
|-------|-------|-----|-----------------|
| `engine/ogul.py` | 1995 | 1.1, 1.2, 1.3, 1.4, 2.1, 2.2 | Ana değişiklik dosyası |
| `engine/main.py` | 562 | 1.5 | 3 satır ekleme |
| `config/default.json` | 34 | 2.3 | Strateji parametreleri |
| `engine/config.py` | 51 | 2.3 | Config parse genişletme |
| `backtest/` | — | 3.x | Mevcut altyapı kullanılacak |

Değişiklik YAPILMAYACAK dosyalar (dokunma):
- `engine/baba.py` — bu fazda değişiklik yok
- `engine/models/` — model yapıları korunacak
- `engine/ustat.py` — Top 5 mantığı korunacak
- `engine/mt5_bridge.py` — MT5 katmanı korunacak
- `api/` — API katmanı korunacak
- `desktop/` — UI katmanı korunacak
