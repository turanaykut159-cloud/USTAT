============================================================================
BABA - OGUL - USTAT v5.0
OGUL YENI MOTOR TEKNIK SPESIFIKASYONU
Tick Bazli Sinyal Motoru
Tarih: 1 Mart 2026
Platform: VIOP / GCM Capital / MetaTrader 5 + Python
============================================================================


============================================================================
1. GIRIS VE AMAC
============================================================================

Bu dokuman, OGUL modulunun sinyal uretim motorunun tamamen yeniden
yazilmasi icin teknik spesifikasyondur.

DEGISEN:     OGUL sinyal uretimi (engine/ogul.py) ve cikis mantigi
EKLENEN:     Tick veri motoru (engine/tick_engine.py — yeni dosya)
DEGISMEYEN:  BABA (risk, rejim, veto, kill-switch)
             State Machine (SIGNAL->PENDING->SENT->FILLED->CLOSED)
             USTAT (Top 5 kontrat secimi)
             Emir yonetimi (advance_orders, timeout, retry)
             Netting mode


----------------------------------------------------------------------------
1.1 NEDEN DEGISTIRIYORUZ?
----------------------------------------------------------------------------

SORUN 1 — Gecikmeli sinyal
  Neden:  EMA/RSI M15 bar bazli, 15 dk gecikmeli. Sinyal uretildiginde
          buyuk oyuncu hareketi bitirmis.
  Sonuc:  Gec giris, kotu fiyat, VIOP sigliginda manipulasyona acik.

SORUN 2 — Herkesin bildigi sinyaller
  Neden:  EMA crossover, RSI 30/70, 20-bar breakout — perakende
          trader'larin %90'i bunlari kullaniyor.
  Sonuc:  Buyuk oyuncular bu sinyalleri tuzak olarak kullaniyor.
          Sinyal tetiklendiginde karsi tarafta pozisyon almis oluyorlar.

SORUN 3 — Fiyata bakiyor, guce bakmiyor
  Neden:  Bar verisi fiyatin ozetini gosterir. Kimin aldigi, kimin
          sattigi, ne kadar lot ile islem yaptigi gorunmez.
  Sonuc:  Manipulasyon tespiti imkansiz. False breakout, fake sinyal
          ayristirilamaz.


----------------------------------------------------------------------------
1.2 VERI TEMELI — GCM MT5 TEST SONUCLARI (27 Subat 2026)
----------------------------------------------------------------------------

Asagidaki TUM kararlar gercek VIOP verisiyle dogrulanmistir:

  BUY/SELL flag         -> Flag guvenilir degil (her tickte ikisi birden)
                           Cozum: last<=bid SELL, last>=ask BUY
  Volume doluluk        -> 996/1000 dolu, tick bazli hacim analizi mumkun
  Buyuk islem esigi     -> 4+ lot (ortalama + 2*standart sapma)
  Tick performansi      -> 3 kontrat 1000 tick = 2.1 ms (%0.02 cycle)
  Fiyat-delta uyumu     -> THYAO %83, AKBNK %60
  Kontratlar arasi      -> Ortak 229 dk, domino sinyali uygulanabilir
  Gercek islem orani    -> %6.6 (geri kalan fiyat guncellemesi, filtrelenir)


============================================================================
2. YENI OGUL MIMARISI
============================================================================


----------------------------------------------------------------------------
2.1 DOSYA YAPISI
----------------------------------------------------------------------------

  engine/tick_engine.py     YENI       Tick toplama, siniflandirma, 5dk pencere
  engine/ogul.py            DEGISIYOR  7 yeni sinyal, skorlama, yeni cikis
  config/default.json       GENISLIYOR tick_signals ve regime_adjustments eklenir
  models/trade.py           KUCUK      signal_score, signal_type alanlari eklenir
  engine/main.py            KUCUK      tick_engine import ve cycle cagrisi

  engine/baba.py            DEGISMIYOR Tum risk yonetimi aynen kalir
  engine/ustat.py           DEGISMIYOR Top 5 kontrat secimi aynen kalir


----------------------------------------------------------------------------
2.2 VERI AKISI
----------------------------------------------------------------------------

MEVCUT AKIS (degismiyor):
  main.py -> BABA rejim belirle -> OGUL sinyal uret -> BABA veto -> MT5 emir

OGUL IC AKIS (yeni):
  1.  tick_engine.collect(top5_symbols)          # 2-3 ms
  2.  tick_engine.classify_trades()               # last vs bid/ask
  3.  tick_engine.aggregate(window=5min)           # delta, ratio, spread
  4.  ogul._check_aggressor_shift(agg_data)       # Ana sinyal
  5.  ogul._check_absorption(agg_data)            # Emme sinyal
  6.  ogul._check_exhaustion(agg_data)            # Tukenme sinyal
  7.  ogul._check_silent_accumulation(agg_data)   # Birikim sinyal
  8.  ogul._check_spread_squeeze(agg_data)        # Zamanlama skoru
  9.  ogul._check_domino(agg_data)                # Oncu sinyal
  10. ogul._check_trap(signal)                    # Filtre (60sn)
  11. ogul._score_signal(signal, modifiers)        # 0-100 skor
  12. if score >= 60: Trade olustur -> BABA veto -> execute


----------------------------------------------------------------------------
2.3 REJIM ESLEME DEGISIKLIGI
----------------------------------------------------------------------------

  Rejim       Eski Strateji                  Yeni Strateji
  --------    ---------------------------    ----------------------------------
  TREND       TREND_FOLLOW (EMA crossover)   TICK_SIGNALS (tumu aktif,
                                              accumulation devre disi)
  RANGE       MEAN_REVERSION + BREAKOUT      TICK_SIGNALS (tumu aktif,
                                              absorption ve squeeze oncelikli)
  VOLATILE    [] (islem yok)                 [] (AYNEN KALIR)
  OLAY        [] (sistem dur)                [] (AYNEN KALIR)

Neden:  VOLATILE ve OLAY rejimlerinde BABA "dur" demis. OGUL sinyal
        uretse bile BABA veto eder. Bu mekanizma AYNEN korunuyor.
        TREND ve RANGE arasindaki fark artik OGUL icinde parametre
        farklilasmasiyla yapilir (hangi sinyallerin calistigi degil,
        esik degerleri farklidir):

  TREND rejiminde:
    aggressor_shift.consecutive_windows = 3  (hizli tepki)
    exhaustion.lot_shrink_ratio = 0.4
    silent_accumulation: DEVRE DISI (TREND'de sessizlik yok)

  RANGE rejiminde:
    aggressor_shift.consecutive_windows = 5  (daha dikkatli)
    absorption: ONCELIKLI (RANGE'de emme cok olur)
    silent_accumulation: AKTIF
    spread_squeeze: ONCELIKLI


============================================================================
3. TICK ENGINE (engine/tick_engine.py)
============================================================================

Tamamen yeni dosya. OGUL'un veri kaynagi. 3 ana sinif icerir.


----------------------------------------------------------------------------
3.1 TickCollector Sinifi
----------------------------------------------------------------------------

Gorev:  MT5'ten tick verisi toplar, bellekte tutar.

  class TickCollector:
      def __init__(self, mt5_wrapper):
          self.mt5 = mt5_wrapper
          self.tick_buffer = {}          # symbol -> deque(maxlen=5000)

      def collect(self, symbols: list[str]) -> dict:
          """Her sembol icin son cycle'dan bu yana tick ceker.
          Returns: {symbol: numpy_array_of_ticks}"""

          for symbol in symbols:
              ticks = mt5.copy_ticks_from(
                  symbol,
                  utc_from=last_collect_time,
                  count=5000,
                  flags=mt5.COPY_TICKS_ALL
              )
              # Sadece gercek islem ticklerini filtrele:
              # flags & (TICK_FLAG_BUY | TICK_FLAG_SELL) != 0
              # VE last > 0 VE volume > 0
              real_trades = filter_real_trades(ticks)
              self.tick_buffer[symbol].extend(real_trades)

          return self.tick_buffer

  Performans: 5 kontrat x 5000 tick = ~5 ms (10sn cycle'in %0.05'i)

  Bellek: deque(maxlen=5000) = kontrat basina ~500 KB
          5 kontrat = ~2.5 MB (ihmal edilebilir)


----------------------------------------------------------------------------
3.2 TradeClassifier Sinifi
----------------------------------------------------------------------------

Gorev:  Her tick'i BUY veya SELL olarak siniflandirir.

Neden flag kullanmiyoruz:
  GCM her gercek islem tick'inde HEM BUY HEM SELL flag koyuyor.
  85/85 tickte %100 her ikisi birden. Istatistiksel olarak imkansiz.
  GCM bilateral raporluyor (alici + satici ayni tick).

Cozum:  last fiyatinin bid/ask konumu:

  class TradeClassifier:
      @staticmethod
      def classify(tick) -> str:
          """
          last <= bid  -> 'SELL' (satici agresor, bid kabul etmis)
          last >= ask  -> 'BUY'  (alici agresor, ask kabul etmis)
          bid < last < ask -> mid-point'e gore siniflandir
          """
          if tick.last <= 0 or tick.volume <= 0:
              return 'NEUTRAL'        # fiyat guncellemesi, gercek islem degil

          if tick.last <= tick.bid:
              return 'SELL'
          if tick.last >= tick.ask:
              return 'BUY'

          mid = (tick.bid + tick.ask) / 2
          return 'BUY' if tick.last >= mid else 'SELL'

Dogrulama: 27 Subat F_THYAO 14:00-15:00 testinde 85 gercek islemde
           74 at_ask (BUY), 11 at_bid (SELL) basariyla siniflandirildi.
           0 belirsiz. Volume delta +141 lot (alis baskin).


----------------------------------------------------------------------------
3.3 TickAggregator Sinifi
----------------------------------------------------------------------------

Gorev:  Siniflandirilmis ticklerden 5 dakikalik pencere metrikleri hesaplar.
        Son 12 pencere bellekte tutulur (60 dk gecmis).

  class TickAggregator:
      def __init__(self):
          self.windows = {}  # symbol -> deque(maxlen=12)

      def aggregate(self, symbol, classified_ticks) -> WindowData:
          """5 dakikalik pencere metrikleri"""

          buy_ticks  = [t for t in classified_ticks if t.direction == 'BUY']
          sell_ticks = [t for t in classified_ticks if t.direction == 'SELL']

          return WindowData(
              timestamp        = pencere_baslangic_zamani,
              volume_delta     = sum(t.vol for t in buy_ticks) - sum(t.vol for t in sell_ticks),
              buy_ratio        = buy_vol / (buy_vol + sell_vol) if total > 0 else 0.5,
              big_buy_count    = len([t for t in buy_ticks if t.vol >= 4]),
              big_sell_count   = len([t for t in sell_ticks if t.vol >= 4]),
              big_buy_volume   = sum(t.vol for t in buy_ticks if t.vol >= 4),
              big_sell_volume  = sum(t.vol for t in sell_ticks if t.vol >= 4),
              tick_velocity    = len(classified_ticks) / 5.0,    # tick/dk
              avg_spread       = mean(t.ask - t.bid for t in all_ticks),
              avg_lot_size     = mean(t.vol for t in classified_ticks) if len > 0 else 0,
              price_open       = classified_ticks[0].last if len > 0 else 0,
              price_close      = classified_ticks[-1].last if len > 0 else 0,
              price_change     = price_close - price_open,
              silence_seconds  = simdi - son_islem_zamani,
              total_buy_vol    = sum(t.vol for t in buy_ticks),
              total_sell_vol   = sum(t.vol for t in sell_ticks),
          )

Her cycle'da (10sn) aggregate cagirilir. Pencere dolmamissa partial
sonuc doner. Pencere tamamlaninca windows deque'ye eklenir ve bir
sonraki pencere baslar.

Metrik tablosu:

  Metrik              Hesaplama                                 Kullanim
  ------------------- ----------------------------------------- -------------------------
  volume_delta        BUY_vol - SELL_vol                        Net alis/satis baskisi
  buy_ratio           BUY_vol / (BUY_vol + SELL_vol)            Agresor yon orani (0-1)
  big_trade_count     4+ lot islem sayisi (ayri BUY/SELL)       Buyuk oyuncu aktivitesi
  big_trade_ratio     big_BUY_vol / (big_BUY + big_SELL)        Buyuk oyuncu yonu
  tick_velocity       gercek islem tick / dakika                 Aktivite seviyesi
  avg_spread          ortalama (ask - bid)                       Likidite durumu
  avg_lot_size        ortalama islem hacmi                       Islem buyuklugu trendi
  price_change        son fiyat - ilk fiyat                      Fiyat yonu
  silence_seconds     son islemden bu yana gecen sure             Sessizlik tespiti


============================================================================
4. SINYAL METODLARI (engine/ogul.py)
============================================================================

Mevcut 3 metod KALDIRILIR:
  _check_trend_follow()      # EMA crossover + ADX -> SIL
  _check_mean_reversion()    # RSI + Bollinger     -> SIL
  _check_breakout()          # 20-bar high/low     -> SIL

Yeni 7 metod EKLENIR (asagida detayli):


----------------------------------------------------------------------------
4.1 AGRESOR DEGISIMI (_check_aggressor_shift)
----------------------------------------------------------------------------

Tur:     Ana giris sinyali
Neden:   Piyasada her an bir taraf kontrol ediyor — ya alici agresor
         (at_ask) ya satici agresor (at_bid). Kontrol el degistirdiginde
         trend donuyor. El degistirme aninda yeni yone girmek trendin
         baslanicicini yakalamak demek.
Kanit:   THYAO 14:00 BUY->SELL, 14:15 SELL->BUY gecisi.
         14:15'te BUY girseydin gunun en iyi trade'i.
Veri:    buy_ratio (5dk pencere), 3+ ardisik pencerede yon degisimi

  def _check_aggressor_shift(self, symbol, agg_windows):
      N = config.aggressor_shift.consecutive_windows  # TREND:3, RANGE:5
      if len(agg_windows) < N:
          return None

      son_N = agg_windows[-N:]

      # BUY->SELL gecisi: buy_ratio surekli dusuyorsa
      ratios = [w.buy_ratio for w in son_N]
      if all(ratios[i] < ratios[i-1] for i in range(1, N)):
          if ratios[-1] < 0.40:
              # Teyit: son pencerede 4+ lot SELL var mi?
              if son_N[-1].big_sell_count > 0:
                  return Signal(symbol, 'SELL', score=40, type='aggressor_shift')

      # SELL->BUY gecisi: buy_ratio surekli yukseliyorsa
      if all(ratios[i] > ratios[i-1] for i in range(1, N)):
          if ratios[-1] > 0.60:
              if son_N[-1].big_buy_count > 0:
                  return Signal(symbol, 'BUY', score=40, type='aggressor_shift')

      return None


----------------------------------------------------------------------------
4.2 EMME TESPITI (_check_absorption)
----------------------------------------------------------------------------

Tur:     Kontra sinyal — baski var ama fiyat gitmiyor
Neden:   Buyuk oyuncu karsi tarafta her islemi emiyor. Emme bitince
         fiyat emen yonde patlar.
Kanit:   AKBNK 13:00-14:00 — delta +40 ama fiyat -0.48.
         Sonraki saat fiyat +0.70 yukseldi. Alici sabirla biriktirmis.
Veri:    volume_delta, price_change, ATR

  def _check_absorption(self, symbol, agg_windows):
      son_6 = agg_windows[-6:]  # son 30 dk (6 x 5dk)
      if len(son_6) < 6:
          return None

      total_delta = sum(w.volume_delta for w in son_6)
      total_price = son_6[-1].price_close - son_6[0].price_open
      atr = self.baba.get_atr(symbol)
      threshold = config.absorption.volume_delta_threshold  # default: 20

      # Alis baskisi var ama fiyat dusmus -> buyuk satici emiyor
      if total_delta > threshold:
          if total_price < -config.absorption.price_move_atr_ratio * atr:  # 0.3
              # Emme bitiyor mu? Son pencere sell hizi dusuyor mu?
              if son_6[-1].tick_velocity < son_6[-3].tick_velocity * 0.7:
                  return Signal(symbol, 'BUY', score=40, type='absorption')

      # Satis baskisi var ama fiyat yukseldi -> buyuk alici emiyor
      if total_delta < -threshold:
          if total_price > config.absorption.price_move_atr_ratio * atr:
              if son_6[-1].tick_velocity < son_6[-3].tick_velocity * 0.7:
                  return Signal(symbol, 'SELL', score=40, type='absorption')

      return None


----------------------------------------------------------------------------
4.3 TUKENME TESPITI (_check_exhaustion)
----------------------------------------------------------------------------

Tur:     Cikis sinyali + opsiyonel ters giris
Neden:   Trendin yakiti buyuk lot. Lot kuculuyorsa yakit bitiyor,
         perakende kovaliyor. Trend dondugunde perakende tuzakta kalir.
Kanit:   THYAO 14:00 — 51 lot satis, sonra 10, 10, sonra sessizlik.
         Satici tukendi. 14:15'te 126 lot alim geldi.
Veri:    avg_lot_size, volume_delta, silence_seconds

  def _check_exhaustion(self, symbol, agg_windows):
      if len(agg_windows) < 6:
          return None

      ilk_3 = agg_windows[-6:-3]
      son_3 = agg_windows[-3:]

      ilk_avg = safe_mean([w.avg_lot_size for w in ilk_3])
      son_avg = safe_mean([w.avg_lot_size for w in son_3])

      if ilk_avg == 0:
          return None

      ratio = son_avg / ilk_avg

      if ratio < config.exhaustion.lot_shrink_ratio:  # default: 0.4
          # Mevcut trend yonu ne?
          trend_delta = sum(w.volume_delta for w in agg_windows[-6:])

          # Sessizlik var mi? (tukenmenin son asamasi)
          if son_3[-1].silence_seconds > config.exhaustion.silence_seconds:  # 300sn
              if trend_delta > 0:
                  return Signal(symbol, 'SELL', score=40, type='exhaustion',
                                note='yukselis tukendi')
              elif trend_delta < 0:
                  return Signal(symbol, 'BUY', score=40, type='exhaustion',
                                note='dusus tukendi')

      return None

  NOT: Tukenme sinyali oncelikle CIKIS amaciyla kullanilir.
       Mevcut pozisyon varsa trailing stop sikilastirilir.
       Ters giris ancak 4+ lot ters tick gelirse yapilir (teyit gerekli).


----------------------------------------------------------------------------
4.4 TUZAK FILTRESI (_check_trap)
----------------------------------------------------------------------------

Tur:     Filtre — tum sinyallere uygulanir, sinyal URETMEZ
Neden:   Herhangi bir sinyal tuzak olabilir. Sinyalden sonra 60sn
         izleyerek tuzak mi gercek mi anlasilir.
Kanit:   THYAO 14:00 — 51 lot satis spike'i breakout gibi gorunur.
         60sn sonra alim basladi. Tuzakti.
Veri:    Sinyal sonrasi 60sn icerisindeki tick'ler

  def _check_trap(self, signal, recent_ticks_60s):
      """Sinyal uretildikten sonra 60sn izle.
      True  -> sinyal gecerli, devam et
      False -> tuzak tespit, sinyal IPTAL"""

      trades = [t for t in recent_ticks_60s if t.direction != 'NEUTRAL']
      if len(trades) < 3:
          return True  # yeterli veri yok, gecir (ihtiyatli)

      same_dir = [t for t in trades if t.direction == signal.direction]
      reverse_ratio = 1 - (len(same_dir) / len(trades))

      # Spread genisliyor mu? (tuzak isareti)
      avg_spread_pre = signal.pre_spread   # sinyal anindaki spread
      avg_spread_post = mean(t.ask - t.bid for t in recent_ticks_60s)
      spread_expanding = avg_spread_post > avg_spread_pre * 1.5

      if reverse_ratio > config.trap.reverse_ratio:  # default: 0.6
          signal.trapped = True
          signal.trap_reason = f"ters oran: {reverse_ratio:.0%}"
          return False

      if spread_expanding and reverse_ratio > 0.4:
          signal.trapped = True
          signal.trap_reason = "spread genisledi + ters akis"
          return False

      return True  # sinyal gecerli

  ONEMLI: Tuzak filtresi sinyal uretiminden SONRA calisir.
  60sn gecikme ekler. Bu gecikme kabul edilebilir cunku tuzak
  tespiti olmadan giris yapmak cok daha pahaliya patlar.

  UYGULAMA: Sinyal uretildiginde Trade objesi SIGNAL state'e gecer
  ama emir GONDERILMEZ. 60sn sonra tuzak kontrolu yapilir.
  Gecerliyse PENDING state'e gecer ve emir gonderilir.
  Tuzaksa CANCELLED state'e gecer.

  State machine degisikligi:
    Eski:  SIGNAL -> PENDING -> SENT -> FILLED -> CLOSED
    Yeni:  SIGNAL -> TRAP_CHECK (60sn) -> PENDING -> SENT -> FILLED -> CLOSED
                                       -> CANCELLED (tuzak ise)


----------------------------------------------------------------------------
4.5 SESSIZ BIRIKIM (_check_silent_accumulation)
----------------------------------------------------------------------------

Tur:     Erken giris sinyali
Neden:   Buyuk oyuncu pozisyon alirken gurultu cikarmaz. Dusuk hacim
         donemlerinde sistematik tek yonlu buyuk lot = birikim.
         Birikim bittikten sonra kirilim gelir.
Kanit:   AKBNK 13:30'da +1 delta (sessiz). 13:35'te +73 delta.
         Sessiz birikim sonrasi patlama.
Veri:    tick_velocity, big_trade_count, big_trade direction, price range

  def _check_silent_accumulation(self, symbol, agg_windows):
      # RANGE rejiminde aktif, TREND'de devre disi
      if self.baba.regime == 'TREND':
          return None

      son_6 = agg_windows[-6:]  # son 30 dk
      if len(son_6) < 6:
          return None

      # Kosul 1: Piyasa sessiz (tick hizi dusuk)
      avg_velocity = mean([w.tick_velocity for w in son_6])
      daily_avg = self.tick_engine.get_daily_avg_velocity(symbol)
      if avg_velocity > daily_avg * config.accumulation.tick_speed_ratio:  # 0.5
          return None  # piyasa sessiz degil

      # Kosul 2: Buyuk islem var (4+ lot)
      big_buys = sum(w.big_buy_count for w in son_6)
      big_sells = sum(w.big_sell_count for w in son_6)
      total_big = big_buys + big_sells
      if total_big < config.accumulation.big_trade_min_count:  # 3
          return None  # yeterli buyuk islem yok

      # Kosul 3: Buyuk islemlerin %70+ ayni yonde
      if total_big > 0:
          buy_direction_ratio = big_buys / total_big
      else:
          return None

      threshold = config.accumulation.direction_ratio  # 0.7

      # Kosul 4: Fiyat dar range'de (birikim belirtisi)
      prices = [w.price_close for w in son_6 if w.price_close > 0]
      if len(prices) < 2:
          return None
      price_range = max(prices) - min(prices)
      atr = self.baba.get_atr(symbol)
      if price_range > 0.5 * atr:
          return None  # fiyat cok hareketli, birikim degil

      if buy_direction_ratio >= threshold:
          return Signal(symbol, 'BUY', score=40, type='silent_accumulation',
                        note=f"birikim: {big_buys} buyuk alis, range {price_range:.2f}")
      elif (1 - buy_direction_ratio) >= threshold:
          return Signal(symbol, 'SELL', score=40, type='silent_accumulation',
                        note=f"birikim: {big_sells} buyuk satis, range {price_range:.2f}")

      return None


----------------------------------------------------------------------------
4.6 SPREAD SQUEEZE (_check_spread_squeeze)
----------------------------------------------------------------------------

Tur:     Zamanlama ve kalite skoru — sinyal URETMEZ, mevcut sinyali guclendirir
Neden:   Spread en dar noktada piyasa en sakin aninda. Buyuk hareket
         oncesi spread daralir cunku her iki taraf pozisyon almis, bekliyor.
         Squeeze aninda giris maliyeti en dusuk, patlama potansiyeli en yuksek.
Kanit:   THYAO 16:00'da spread 0.33 (gunun en dari). 16:20'de +51 lot patlama.
Veri:    avg_spread, 30dk hareketli ortalama

  def _check_spread_squeeze(self, symbol, agg_windows):
      """Sinyal uretmez. squeeze_active=True donerse skor bonusu verilir."""

      if len(agg_windows) < 6:
          return False

      son_6 = agg_windows[-6:]
      current_spread = son_6[-1].avg_spread
      avg_spread_30m = mean([w.avg_spread for w in son_6])

      if avg_spread_30m == 0:
          return False

      ratio = current_spread / avg_spread_30m

      if ratio < config.squeeze.spread_ratio:  # default: 0.5
          return True   # squeeze aktif -> skor bonusu +20

      return False  # squeeze yok

  UYGULAMA: _score_signal icinde kullanilir:
    if self._check_spread_squeeze(symbol, windows):
        signal.score += config.squeeze.score_bonus  # +20


----------------------------------------------------------------------------
4.7 KONTRATLAR ARASI DOMINO (_check_domino)
----------------------------------------------------------------------------

Tur:     Oncu sinyal — baska kontrattaki hareketten sinyal turetir
Neden:   Para bir kontrata girince ayni sektordeki diger kontratlara
         da girer. Oncu kontrati tespit edersen takipci kontratta
         erken pozisyon alirsin.
Kanit:   AKBNK 13:35'te +73 lot. THYAO 14:15'te +126 lot. 40 dk fark.
         AKBNK'yi gorup THYAO'da BUY acsaydik erken girmis olurduk.
Veri:    5dk volume delta tum Top 5 kontratlar icin

  def _check_domino(self, symbol, all_agg_data):
      """symbol: sinyal aradigimiz kontrat
      all_agg_data: tum Top 5 kontratlarin aggregated pencere verisi"""

      # Bu kontratta zaten hareket var mi?
      own_windows = all_agg_data[symbol]
      if len(own_windows) < 2:
          return None
      own_last_delta = own_windows[-1].volume_delta
      if abs(own_last_delta) > config.domino.delta_threshold:  # 30
          return None  # kendi zaten hareket etmis, domino degil

      # Diger kontratlarda buyuk hareket var mi?
      for other_symbol, other_windows in all_agg_data.items():
          if other_symbol == symbol:
              continue
          if len(other_windows) < 2:
              continue

          other_delta = other_windows[-1].volume_delta
          other_big = other_windows[-1].big_buy_count + other_windows[-1].big_sell_count

          if abs(other_delta) > config.domino.delta_threshold and other_big >= 3:
              # Diger kontratta buyuk hareket var!
              # Yon belirle
              if other_delta > 0:
                  direction = 'BUY'
              else:
                  direction = 'SELL'

              # Bu kontratta ayni yone hafif isaret var mi? (teyit)
              if direction == 'BUY' and own_last_delta > 0:
                  return Signal(symbol, 'BUY', score=40, type='domino',
                                note=f"oncu: {other_symbol} delta {other_delta:+d}")
              elif direction == 'SELL' and own_last_delta < 0:
                  return Signal(symbol, 'SELL', score=40, type='domino',
                                note=f"oncu: {other_symbol} delta {other_delta:+d}")

      return None

  KISITLAMA: Domino sadece Top 5 icerisinde calisir.
  USTAT'in secmedigi kontratlar TARANMAZ.
  Timeout: Domino sinyali 60dk icinde teyit gelmezse iptal olur.


============================================================================
5. SKORLAMA SISTEMI
============================================================================

Her sinyal temel 40 puan ile baslar. Teyit kosullari eklendikce
skor artar. Skor, islem acilip acilmayacagini ve lot buyuklugunu belirler.


----------------------------------------------------------------------------
5.1 SKOR BILESENLERI
----------------------------------------------------------------------------

  Bilesen                     Puan     Kosul
  --------------------------- -------- -------------------------------------------
  Temel sinyal                40       Herhangi bir sinyal tetiklendi
  Spread squeeze              +20      Mevcut spread < 30dk ort * 0.5
  Buyuk islem teyidi          +15      Son 5dk'da 4+ lot sinyal yonunde
  Fiyat-delta uyumu           +15      Fiyat yonu ile delta yonu ayni
  Domino teyidi               +10      Baska kontrattan ayni yon sinyali
                              -----
  Maksimum                    100


----------------------------------------------------------------------------
5.2 SKOR -> ISLEM KARARI
----------------------------------------------------------------------------

  Skor        Karar              Lot              Emir Tipi
  ----------- ------------------ ---------------- -----------------
  >= 80       ISLEM AC           Buyuk lot (%50+) MARKET (hiz oncelikli)
  60 - 79     ISLEM AC           Standart lot     LIMIT (mevcut akis)
  < 60        ATLA               -                -

  def _score_signal(self, signal, agg_data):
      score = signal.score  # baslangic: 40

      # Spread squeeze bonusu
      if self._check_spread_squeeze(signal.symbol, agg_data[signal.symbol]):
          score += config.squeeze.score_bonus  # +20

      # Buyuk islem teyidi
      last_window = agg_data[signal.symbol][-1]
      if signal.direction == 'BUY' and last_window.big_buy_count > 0:
          score += 15
      elif signal.direction == 'SELL' and last_window.big_sell_count > 0:
          score += 15

      # Fiyat-delta uyumu
      if signal.direction == 'BUY' and last_window.price_change > 0 and last_window.volume_delta > 0:
          score += 15
      elif signal.direction == 'SELL' and last_window.price_change < 0 and last_window.volume_delta < 0:
          score += 15

      # Domino teyidi (baska kontrattan ayni sinyal geldiyse)
      if self._has_domino_confirmation(signal, agg_data):
          score += 10

      signal.score = min(score, 100)
      return signal


============================================================================
6. CIKIS MOTORU
============================================================================

Mevcut trailing stop KORUNUR (son savunma hatti). Yeni cikis kosullari
EKLENIR. Hangisi ONCE tetiklenirse pozisyon kapatilir.


----------------------------------------------------------------------------
6.1 CIKIS KOSULLARI (ONCELIK SIRASINA GORE)
----------------------------------------------------------------------------

  1. SPREAD PATLAMA (ACIL CIKIS)
     Kosul:   Mevcut spread > 2x gunluk ortalama spread
     Neden:   Likidite cekildi. Piyasa yapicisi kacti. Fiyat her an
              buyuk kayabilir. Kalmak tehlikeli.
     Eylem:   MARKET emri ile HEMEN kapat.
     Config:  exit.spread_multiplier = 2.0

  2. AGRESOR DEGISIMI CIKISI
     Kosul:   Pozisyon BUY iken buy_ratio 3 ardisik pencerede dusuyor
              VE son pencere buy_ratio < 0.40
     Neden:   Kontrol el degistirdi. Pozisyon artik trende karsi.
     Eylem:   Trailing stop'u mevcut fiyata cek (1 tick mesafe).
              Bir sonraki cycle'da tetiklenir.
     Config:  exit.aggressor_shift_windows = 3

  3. DELTA TERSINE DONME
     Kosul:   Volume delta pozisyon yonunun tersi 2 ardisik pencere
     Neden:   Para akisi tersine dondu. Trend gucunu kaybediyor.
     Eylem:   2 pencere -> uyari (trailing stop sikilastir)
              3 pencere -> kapat
     Config:  exit.delta_reverse_warn = 2, exit.delta_reverse_close = 3

  4. TUKENME CIKISI
     Kosul:   avg_lot_size son 15dk / ilk 15dk < 0.4
              VE son 5dk islem sessizligi > 300sn
     Neden:   Buyuk oyuncu cikti. Kalan kucuk lotlar trendi
              tasiyamaz. Geri donus yakinda.
     Eylem:   Trailing stop sikilastir (ATR * 0.5 mesafe).
              Sessizlik devam ederse kapat.
     Config:  exit.exhaustion_lot_ratio = 0.4, exit.silence_threshold = 300

  5. TRAILING STOP (MEVCUT — AYNEN KALIR)
     Kosul:   Fiyat trail seviyesine duserse
     Neden:   Son savunma hatti. Diger cikislar calismasa bile
              trailing stop pozisyonu korur.
     Eylem:   MARKET emri ile kapat.
     Config:  Mevcut ATR bazli trailing stop ayarlari

  6. ZAMAN BAZLI (MEVCUT — AYNEN KALIR)
     Kosul:   17:30 (VIOP seans bitisi)
     Neden:   Gece pozisyon tasimama kurali (BABA).
     Eylem:   Tum acik pozisyonlari kapat.


----------------------------------------------------------------------------
6.2 CIKIS ONCELIK MANTIGI
----------------------------------------------------------------------------

  def check_exit_conditions(self, trade, agg_data):
      """Her cycle'da cagirilir. Ilk tetiklenen kosul kazanir."""

      windows = agg_data[trade.symbol]
      current = windows[-1]

      # 1. ACIL: Spread patlama
      daily_avg_spread = self.tick_engine.get_daily_avg_spread(trade.symbol)
      if current.avg_spread > daily_avg_spread * config.exit.spread_multiplier:
          return ExitSignal('SPREAD_EMERGENCY', order_type='MARKET')

      # 2. Agresor degisimi
      if self._exit_aggressor_shift(trade, windows):
          return ExitSignal('AGGRESSOR_REVERSE', order_type='TIGHTEN_STOP')

      # 3. Delta tersine
      reverse_count = self._count_delta_reverse(trade, windows)
      if reverse_count >= config.exit.delta_reverse_close:
          return ExitSignal('DELTA_REVERSE', order_type='MARKET')
      elif reverse_count >= config.exit.delta_reverse_warn:
          return ExitSignal('DELTA_WARNING', order_type='TIGHTEN_STOP')

      # 4. Tukenme
      if self._exit_exhaustion(trade, windows):
          return ExitSignal('EXHAUSTION', order_type='TIGHTEN_STOP')

      # 5-6. Trailing stop ve zaman -> mevcut kod aynen calisir
      return None


============================================================================
7. CONFIG YAPISI
============================================================================

config/default.json icine eklenen yeni bolumler:

  {
    "tick_signals": {
      "aggressor_shift": {
        "consecutive_windows_trend": 3,
        "consecutive_windows_range": 5,
        "buy_ratio_threshold_high": 0.60,
        "buy_ratio_threshold_low": 0.40,
        "require_big_trade_confirm": true
      },
      "absorption": {
        "volume_delta_threshold": 20,
        "price_move_atr_ratio": 0.3,
        "lookback_windows": 6,
        "velocity_decay_ratio": 0.7
      },
      "exhaustion": {
        "lot_shrink_ratio": 0.4,
        "silence_seconds": 300,
        "lookback_windows": 6
      },
      "trap": {
        "confirmation_seconds": 60,
        "reverse_ratio": 0.6,
        "spread_expand_ratio": 1.5,
        "min_trades_for_check": 3
      },
      "accumulation": {
        "tick_speed_ratio": 0.5,
        "big_trade_min_count": 3,
        "direction_ratio": 0.7,
        "max_price_range_atr": 0.5,
        "enabled_regimes": ["RANGE"]
      },
      "squeeze": {
        "spread_ratio": 0.5,
        "score_bonus": 20,
        "lookback_windows": 6
      },
      "domino": {
        "delta_threshold": 30,
        "big_trade_min_count": 3,
        "timeout_minutes": 60,
        "require_same_direction_hint": true
      }
    },

    "scoring": {
      "base_score": 40,
      "squeeze_bonus": 20,
      "big_trade_bonus": 15,
      "price_delta_bonus": 15,
      "domino_bonus": 10,
      "min_score_to_trade": 60,
      "high_score_threshold": 80,
      "high_score_lot_multiplier": 1.5
    },

    "exit": {
      "spread_multiplier": 2.0,
      "aggressor_shift_windows": 3,
      "delta_reverse_warn": 2,
      "delta_reverse_close": 3,
      "exhaustion_lot_ratio": 0.4,
      "silence_threshold": 300,
      "exhaustion_tighten_atr_multiplier": 0.5
    },

    "tick_engine": {
      "buffer_size": 5000,
      "window_minutes": 5,
      "max_windows_history": 12,
      "big_trade_threshold": 4,
      "real_trade_filter": true
    }
  }

PARAMETRE KAYNAGI:
Hicbir parametre havadan atilmamistir.

  4 lot esigi       -> 27 Subat volume dagilimi: ort 1.3, std 1.35 (ort+2*std)
  5 dk pencere      -> VIOP tick frekansi 13/dk, 5dk'da ~65 tick (yeterli veri)
  0.6 tuzak esigi   -> 27 Subat tuzak orneklerinden turetilmis
  20 lot delta esigi -> THYAO saatlik delta araligi: 8-141 (20 anlamli baslangic)
  30 lot domino      -> AKBNK 73 lot spike olay, 30 lot ustunu buyuk hareket
  300sn sessizlik    -> THYAO 14:03-14:15 arasi 720sn sessizlik (300 ilk uyari)
  2x spread         -> THYAO ortalama 0.60, alarm 1.20+ (2x)


============================================================================
8. TRADE OBJESI DEGISIKLIKLERI
============================================================================

models/trade.py'ye eklenen yeni alanlar:

  class Trade:
      # MEVCUT ALANLAR (AYNEN KALIR):
      symbol: str
      direction: str           # 'BUY' veya 'SELL'
      lot: float
      entry_price: float
      sl: float
      tp: float
      state: str               # SIGNAL, PENDING, SENT, FILLED, CLOSED
      ...

      # YENI ALANLAR:
      signal_type: str         # 'aggressor_shift', 'absorption', 'exhaustion',
                               # 'silent_accumulation', 'domino'
      signal_score: int        # 0-100
      signal_note: str         # Sinyal aciklamasi (debug icin)
      trapped: bool            # Tuzak filtresi sonucu
      trap_reason: str         # Tuzak nedeni
      exit_reason: str         # 'trailing_stop', 'spread_emergency',
                               # 'aggressor_reverse', 'delta_reverse',
                               # 'exhaustion', 'time_close'
      score_breakdown: dict    # {'base': 40, 'squeeze': 20, ...}

State machine guncellemesi:
  Eski:  SIGNAL -> PENDING -> SENT -> FILLED -> CLOSED
  Yeni:  SIGNAL -> TRAP_CHECK -> PENDING -> SENT -> FILLED -> CLOSED
                              -> CANCELLED (tuzak ise)

  TRAP_CHECK state'i 60sn surer. Bu surede emir gonderilmez.
  60sn sonra _check_trap cagirilir. Gecerliyse PENDING'e gecer.
  Tuzaksa CANCELLED'a gecer ve loglanir.


============================================================================
9. BABA ILE ETKILESIM (DEGISMEYEN NOKTALAR)
============================================================================

BABA'nin asagidaki TUM mekanizmalari AYNEN calisir:

  Rejim belirleme:    BABA rejimi belirler, OGUL'a iletir
  Risk limitleri:     Gunluk zarar limiti, max pozisyon sayisi
  Kill-switch:        Limit asilirsa sistem durur
  Veto mekanizmasi:   OGUL sinyal uretir, BABA onaylar veya reddeder
  Gece korumasi:      17:30 tum pozisyon kapanir
  VOLATILE/OLAY:      Bu rejimlerde islem YAPILMAZ (bos strateji listesi)

OGUL'dan BABA'ya giden arayuz DEGISMIYOR:

  # OGUL sinyal uretir:
  trade = Trade(symbol, direction, lot, entry, sl, tp, signal_score, signal_type)

  # BABA veto kontrolu:
  approved = self.baba.check_trade(trade)
  if approved:
      self.execute_trade(trade)
  else:
      trade.state = 'VETOED'
      log(f"BABA veto: {trade.symbol} {trade.direction}")


============================================================================
10. UYGULAMA PLANI
============================================================================


----------------------------------------------------------------------------
FAZ A — VERI ALTYAPISI (1 hafta)
----------------------------------------------------------------------------

  Gorev:
    1. engine/tick_engine.py olustur (TickCollector, TradeClassifier, TickAggregator)
    2. Birim testleri yaz (mevcut 27 Subat verisiyle dogrula)
    3. 1 hafta canli veri topla (log dosyasina kaydet)
    4. Toplanan verinin kalitesini kontrol et

  Basari kriteri:
    - TickCollector 5 kontrat icin < 10ms'de veri cekiyor
    - TradeClassifier %95+ dogru siniflandirma (manuel kontrol)
    - TickAggregator 5dk pencereleri dogru hesapliyor

  Dosyalar:
    YENI:  engine/tick_engine.py
    YENI:  tests/test_tick_engine.py
    EDIT:  engine/main.py (import + cycle cagrisi)


----------------------------------------------------------------------------
FAZ B — SINYAL MOTORU (2 hafta)
----------------------------------------------------------------------------

  Gorev:
    1. Mevcut 3 sinyal metodunu kaldir
    2. 7 yeni sinyal metodunu yaz
    3. Skorlama sistemini yaz
    4. 27 Subat verisiyle backtest (beklenen sinyal noktalarini kontrol)
    5. Daha fazla gun verisi topla, backtest genislet

  Basari kriteri:
    - 27 Subat THYAO'da 14:15'te BUY sinyali uretiliyor (agresor degisimi)
    - 27 Subat AKBNK'da 13:00-14:00 absorption tespiti yapiliyor
    - Tuzak filtresi THYAO 14:00 satis spike'ini yakalayip iptal ediyor
    - Tum sinyaller config'den parametre okuyor (hardcoded degil)

  Dosyalar:
    EDIT:  engine/ogul.py (3 eski metod sil, 7 yeni ekle, skorlama ekle)
    EDIT:  config/default.json (tick_signals + scoring bolumleri)
    EDIT:  models/trade.py (yeni alanlar)


----------------------------------------------------------------------------
FAZ C — CIKIS MOTORU (1 hafta)
----------------------------------------------------------------------------

  Gorev:
    1. 4 yeni cikis kosulunu yaz
    2. Mevcut trailing stop'u koru
    3. Oncelik mantigi uygula (ilk tetiklenen kazanir)
    4. Backtest ile dogrula

  Basari kriteri:
    - Spread patlama cikisi tetiklendiginde MARKET emir gonderiliyor
    - Agresor degisimi cikisi trailing stop'u sikilastiriyor
    - Tukenme cikisi sessizlik kosulunu dogru tespit ediyor
    - Mevcut trailing stop degismeden calisiyor

  Dosyalar:
    EDIT:  engine/ogul.py (cikis metodlari)
    EDIT:  config/default.json (exit bolumleri)


----------------------------------------------------------------------------
FAZ D — SHADOW MODE (2 hafta)
----------------------------------------------------------------------------

  Gorev:
    1. Canli piyasada sinyal uret ama islem ACMA
    2. Her sinyali logla: tip, skor, yon, zaman, fiyat
    3. Sinyal uretildikten 15dk/30dk/60dk sonra fiyati kaydet
    4. 2 hafta sonunda analiz:
       - Kac sinyal uretildi?
       - Kac tanesi karli olurdu?
       - Hangi sinyal tipi en basarili?
       - Skorun yuksekligi ile basari korelasyonu var mi?
       - Tuzak filtresi kac tuzak yakaladi?

  Basari kriteri:
    - Minimum 50 sinyal loglandi
    - Sinyal loglari insan tarafindan kontrol edildi
    - Parametre ayarlama onerileri cikarildi

  Dosyalar:
    EDIT:  engine/ogul.py (shadow_mode flag)
    YENI:  logs/shadow_signals.csv


----------------------------------------------------------------------------
FAZ E — CANLI GECIS (1 hafta)
----------------------------------------------------------------------------

  Gorev:
    1. Shadow basariliysa canli gec
    2. Ilk hafta minimum lot (1 lot)
    3. Gunluk rapor: kac sinyal, kac islem, PnL
    4. Haftalik analiz: sinyal tipi bazli basari orani

  Basari kriteri:
    - 1 hafta sonunda net kar/zarar raporu
    - Hicbir bug veya beklenmeyen davranis yok
    - BABA'nin tum koruma mekanizmalari calisiyor

  Dosyalar:
    EDIT:  engine/ogul.py (shadow_mode = False)
    EDIT:  config/default.json (lot ayarlari)


============================================================================
11. RISK VE SINIRLILIKLARI
============================================================================

Bu dokuman yeni motorun CALISACAGINI GARANTI ETMEZ.
Asagidaki risklerin farkindayiz:

  1. Tek gun verisi: Tum kalibrasyonlar 27 Subat verisine dayanir.
     Farkli piyasa kosullarinda parametreler yanlis olabilir.
     Cozum: Shadow mode'da 2 hafta farkli kosullarda test et.

  2. Overfitting riski: 7 sinyal + 5 skor bileseni = cok parametre.
     Gecmis veriye asiri uyum riski var.
     Cozum: Parametreleri mumkun oldugunca az ve genis tut.
     Shadow mode'da out-of-sample test yap.

  3. GCM veri kalitesi: GCM'in tick verisi kalitesi diger broker'lardan
     farkli olabilir. Broker degisikligi durumunda classifier tekrar
     test edilmeli.

  4. VİOP likidite degisimi: VİOP'un sig yapisi bizim avantajimiz.
     Eger likidite artarsa (daha cok katilimci), buyuk oyuncu izi
     daha zor gorunur hale gelebilir. 4 lot esigi yeniden kalibre
     edilmeli.

  5. Performans varsayimlari: 2.1 ms test sonucu piyasa kapali iken
     alinmistir. Canli seansta ag gecikmesi ve MT5 yuklenme farki
     olabilir. Faz A'da canli performans olculmeli.

  6. Rakam tahmini YOKTUR: Bu dokumanda win rate, ROI, drawdown
     tahmini KASITLI OLARAK BULUNMAZ. Bu rakamlar ancak shadow mode
     ve canli islem verilerinden cikarilir. Onceden tahmin yapmak
     yanilticidir.


============================================================================
12. OZET
============================================================================

KALDIRILAN:
  - _check_trend_follow() (EMA crossover + ADX)
  - _check_mean_reversion() (RSI 30/70 + Bollinger)
  - _check_breakout() (20-bar high/low kirilimi)

EKLENEN:
  - engine/tick_engine.py (TickCollector, TradeClassifier, TickAggregator)
  - _check_aggressor_shift() (ana giris sinyali)
  - _check_absorption() (emme — kontra sinyal)
  - _check_exhaustion() (tukenme — cikis + ters)
  - _check_trap() (tuzak filtresi — 60sn izleme)
  - _check_silent_accumulation() (sessiz birikim — erken giris)
  - _check_spread_squeeze() (zamanlama — skor bonusu)
  - _check_domino() (oncu kontrat — para akisi)
  - _score_signal() (0-100 skorlama)
  - 5 yeni cikis kosulu (spread, agresor, delta, tukenme + mevcut trailing)

KORUNAN:
  - BABA tum risk yonetimi, rejim, veto, kill-switch
  - State machine (SIGNAL->PENDING->SENT->FILLED->CLOSED + TRAP_CHECK)
  - USTAT Top 5 kontrat secimi
  - Emir yonetimi (advance_orders, timeout, retry)
  - Netting mode uyumu
  - Trailing stop (son savunma hatti olarak)
  - 17:30 tum pozisyon kapatma

FELSEFE:
  Fiyata degil, fiyati hareket ettiren guce bak.
  Herkesin gordugu veriyi degil, kimsenin bakmadigini oku.
  Tahmin yapma, veri konussun.

============================================================================
DOKUMAN SONU
============================================================================
