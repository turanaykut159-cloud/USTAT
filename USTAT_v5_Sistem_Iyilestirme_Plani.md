# ÜSTAT v5.0 — Sistem İyileştirme Spesifikasyonu
# Code-Ready Geliştirme Dokümanı

**Tarih:** 2026-02-27
**Hedef:** Canlı sistemde VİOP'ta para kazanacak seviyeye getirmek
**Format:** Bu doküman, bir coding agent'ın (Claude Code vb.) doğrudan uygulayabileceği formatta yazılmıştır. Her değişiklik: dosya yolu + eski kod + yeni kod + test kriterleri içerir.

**UYARI — CANLI SİSTEM:** Her faz ayrı commit olmalı. Her commit sonrası engine restart ile test edilmeli. Sorun varsa git revert ile geri alınabilmeli.

**UYGULAMA SIRASI:** Faz 1 → Faz 2 → Faz 3. Faz içindeki maddeler sırayla uygulanmalı.

---

# ═══════════════════════════════════════════════════════════════
# FAZ 1 — ACİL BUG DÜZELTMELERİ
# Amaç: Mevcut kodu bozmadan güvenilirliği artır
# Tahmini süre: 2-4 saat
# ═══════════════════════════════════════════════════════════════

---

## FAZ 1.1 — _update_fill_price Netting Mode Düzeltmesi

**Dosya:** `engine/ogul.py`
**Metod:** `_update_fill_price`
**Sorun:** Ticket bazlı eşleştirme yapıyor ama VİOP netting mode'da ticket değişebilir. Sistemin geri kalanı sembol bazlı çalışıyor. Bu tutarsızlık giriş fiyatının güncellenmemesine → yanlış PnL hesabına yol açar.

### ESKİ KOD (KALDIRILACAK):

```python
    def _update_fill_price(self, symbol: str, trade: Trade) -> None:
        """MT5 pozisyondan gerçek dolum fiyatını al ve DB güncelle.

        Args:
            symbol: Kontrat sembolü.
            trade: Güncellenecek Trade.
        """
        positions = self.mt5.get_positions()
        pos = next(
            (p for p in positions if p.get("ticket") == trade.ticket),
            None,
        )

        if pos:
            trade.entry_price = pos.get(
                "price_open", trade.entry_price,
            )

        if trade.db_id > 0:
            self.db.update_trade(trade.db_id, {
                "entry_price": trade.entry_price,
            })
```

### YENİ KOD (YERİNE KONACAK):

```python
    def _update_fill_price(self, symbol: str, trade: Trade) -> None:
        """MT5 pozisyondan gerçek dolum fiyatını al ve DB güncelle.

        Netting mode: sembol bazlı eşleştirme (ticket değişebilir).

        Args:
            symbol: Kontrat sembolü.
            trade: Güncellenecek Trade.
        """
        positions = self.mt5.get_positions()
        # Netting mode: sembol bazlı eşleştir
        pos = next(
            (p for p in positions if p.get("symbol") == symbol),
            None,
        )

        if pos:
            trade.entry_price = pos.get(
                "price_open", trade.entry_price,
            )
            # Ticket güncellemesi — netting merge sonrası farklı olabilir
            new_ticket = pos.get("ticket", 0)
            if new_ticket and new_ticket != trade.ticket:
                logger.debug(
                    f"Ticket güncellendi [{symbol}]: "
                    f"{trade.ticket} → {new_ticket}"
                )
                trade.ticket = new_ticket

        if trade.db_id > 0:
            self.db.update_trade(trade.db_id, {
                "entry_price": trade.entry_price,
            })
```

### TEST KRİTERLERİ:
- LIMIT emir dolunca entry_price MT5'teki price_open ile eşleşmeli
- Ticket değişimi durumunda log mesajı görülmeli

---

## FAZ 1.2 — _manage_active_trades MT5 Çağrı Optimizasyonu

**Dosya:** `engine/ogul.py`
**Metod:** `_manage_active_trades`
**Sorun:** Her aktif işlem için döngü içinde `self.mt5.get_positions()` çağrılıyor. 5 aktif işlem = 5 ayrı MT5 sorgusu. Cycle süresini uzatıyor, trailing stop güncellemesini geciktiriyor.

### ESKİ KOD (KALDIRILACAK):

```python
    def _manage_active_trades(self, regime: Regime) -> None:
        """Mevcut açık işlemleri yönet — trailing stop, çıkış kontrolleri.

        Her cycle'da ``process_signals()`` başında çağrılır.

        Args:
            regime: Mevcut piyasa rejimi.
        """
        if not self.active_trades:
            return

        # VOLATILE / OLAY → FILLED pozisyonları kapat
        if regime.regime_type in (RegimeType.VOLATILE, RegimeType.OLAY):
            for symbol in list(self.active_trades):
                trade = self.active_trades[symbol]
                if trade.state != TradeState.FILLED:
                    continue
                close_result = self.mt5.close_position(trade.ticket)
                reason = f"regime_{regime.regime_type.value.lower()}"
                if close_result:
                    logger.warning(
                        f"Rejim değişimi kapanış [{symbol}]: {reason}"
                    )
                self._handle_closed_trade(symbol, trade, reason)
            return

        # Her aktif işlem için strateji bazlı kontrol (sadece FILLED)
        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]

            # Sadece dolu pozisyonları yönet
            if trade.state != TradeState.FILLED:
                continue

            # Pozisyon hâlâ MT5'te var mı? (Netting: sembol bazlı eşleştir)
            positions = self.mt5.get_positions()
            pos = next(
                (p for p in positions if p.get("symbol") == symbol),
                None,
            )
            if pos is None:
                # Pozisyon harici kapanmış (SL/TP hit)
                self._handle_closed_trade(symbol, trade, "sl_tp")
                continue

            # Pozisyon ticket'ını güncelle (senkronizasyon)
            pos_ticket = pos.get("ticket", 0)
            if pos_ticket and pos_ticket != trade.ticket:
                trade.ticket = pos_ticket

            # Strateji bazlı çıkış kontrolleri
            if trade.strategy == "trend_follow":
                self._manage_trend_follow(symbol, trade, pos)
            elif trade.strategy == "mean_reversion":
                self._manage_mean_reversion(symbol, trade, pos)
            # breakout: sabit SL/TP, ek kontrol yok
```

### YENİ KOD (YERİNE KONACAK):

```python
    def _manage_active_trades(self, regime: Regime) -> None:
        """Mevcut açık işlemleri yönet — trailing stop, çıkış kontrolleri.

        Her cycle'da ``process_signals()`` başında çağrılır.
        MT5 pozisyonları tek seferde alınır (performans).

        Args:
            regime: Mevcut piyasa rejimi.
        """
        if not self.active_trades:
            return

        # MT5 pozisyonlarını BİR KERE al, sembol bazlı indexle
        positions = self.mt5.get_positions()
        pos_by_symbol: dict[str, dict] = {
            p.get("symbol"): p for p in positions
        }

        # VOLATILE / OLAY → FILLED pozisyonları kapat
        if regime.regime_type in (RegimeType.VOLATILE, RegimeType.OLAY):
            for symbol in list(self.active_trades):
                trade = self.active_trades[symbol]
                if trade.state != TradeState.FILLED:
                    continue
                close_result = self.mt5.close_position(trade.ticket)
                reason = f"regime_{regime.regime_type.value.lower()}"
                if close_result:
                    logger.warning(
                        f"Rejim değişimi kapanış [{symbol}]: {reason}"
                    )
                self._handle_closed_trade(symbol, trade, reason)
            return

        # Her aktif işlem için strateji bazlı kontrol (sadece FILLED)
        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]

            if trade.state != TradeState.FILLED:
                continue

            # Pozisyon hâlâ MT5'te var mı?
            pos = pos_by_symbol.get(symbol)
            if pos is None:
                self._handle_closed_trade(symbol, trade, "sl_tp")
                continue

            # Ticket senkronizasyonu
            pos_ticket = pos.get("ticket", 0)
            if pos_ticket and pos_ticket != trade.ticket:
                trade.ticket = pos_ticket

            # Strateji bazlı çıkış kontrolleri
            if trade.strategy == "trend_follow":
                self._manage_trend_follow(symbol, trade, pos)
            elif trade.strategy == "mean_reversion":
                self._manage_mean_reversion(symbol, trade, pos)
            elif trade.strategy == "breakout":
                self._manage_breakout(symbol, trade, pos)
```

**NOT:** `_manage_breakout` metodu Faz 2.1'de eklenecek. Şimdilik bu satırı ekle ama metodu henüz ekleme — `elif trade.strategy == "breakout": pass` olarak bırak, Faz 2.1'de değiştirilecek.

Geçici olarak breakout satırı:
```python
            elif trade.strategy == "breakout":
                pass  # Faz 2.1'de _manage_breakout eklenecek
```

### TEST KRİTERLERİ:
- 3+ aktif işlemle cycle süresi ölç — öncekinden kısa olmalı
- SL/TP tetiklenince pozisyon doğru kapanmalı
- Log'da "sl_tp" reason görünmeli

---

## FAZ 1.3 — increment_daily_trade_count Zamanlaması

**Dosya:** `engine/ogul.py`
**Sorun:** Sayaç SENT'te artıyor ama emir dolmayabilir. 5 timeout = günlük limit dolmuş ama 0 gerçek işlem.

### DEĞİŞİKLİK 1 — _execute_signal'dan kaldır:

**Bul ve kaldır** (`_execute_signal` metodu içinde, `trade.state = TradeState.SENT` ve DB insert sonrası):

```python
        # Risk sayacı güncelle
        if self.baba:
            self.baba.increment_daily_trade_count()
```

Bu 2 satırı **tamamen sil**.

### DEĞİŞİKLİK 2 — _advance_sent'e ekle:

`_advance_sent` metodu içinde, `if order_status == "filled":` bloğunun sonuna (event insert'ten sonra, return'den önce) ekle:

```python
            # Günlük işlem sayacı — sadece gerçek dolumda artır
            if self.baba:
                self.baba.increment_daily_trade_count()
```

### DEĞİŞİKLİK 3 — _advance_partial'a ekle:

`_advance_partial` metodu içinde, `if trade.filled_volume >= threshold:` bloğunun sonuna (event insert'ten sonra) ekle:

```python
            # Günlük işlem sayacı — kısmi dolum kabul edildi
            if self.baba:
                self.baba.increment_daily_trade_count()
```

### DEĞİŞİKLİK 4 — _advance_market_retry'a ekle:

`_advance_market_retry` metodu içinde, `trade.state = TradeState.FILLED` satırından sonra, DB update'ten önce ekle:

```python
        # Günlük işlem sayacı — market retry dolum
        if self.baba:
            self.baba.increment_daily_trade_count()
```

### TEST KRİTERLERİ:
- LIMIT emir gönder → timeout → sayaç değişmemeli
- LIMIT emir gönder → filled → sayaç 1 artmalı
- Engine restart → restore → sayaç korunmalı (BABA _risk_state'te)

---

## FAZ 1.4 — CONTRACT_SIZE Kontrat Bazlı Alma

**Dosya:** `engine/ogul.py`
**Metod:** `_handle_closed_trade`
**Sorun:** `CONTRACT_SIZE = 100.0` hardcoded. VİOP'ta her kontratın çarpanı farklı olabilir.

### ESKİ KOD (BUL):

```python
        # PnL hesapla
        if trade.entry_price > 0 and trade.exit_price > 0:
            if trade.direction == "BUY":
                trade.pnl = (trade.exit_price - trade.entry_price) * trade.volume * CONTRACT_SIZE
            else:
                trade.pnl = (trade.entry_price - trade.exit_price) * trade.volume * CONTRACT_SIZE
```

### YENİ KOD (DEĞİŞTİR):

```python
        # PnL hesapla — kontrat bazlı çarpan
        if trade.entry_price > 0 and trade.exit_price > 0:
            contract_size = CONTRACT_SIZE  # varsayılan fallback
            sym_info = self.mt5.get_symbol_info(symbol)
            if sym_info and hasattr(sym_info, "trade_contract_size"):
                contract_size = sym_info.trade_contract_size

            if trade.direction == "BUY":
                trade.pnl = (trade.exit_price - trade.entry_price) * trade.volume * contract_size
            else:
                trade.pnl = (trade.entry_price - trade.exit_price) * trade.volume * contract_size
```

### TEST KRİTERLERİ:
- F_THYAO kapanışında PnL doğru hesaplanmalı
- MT5 terminalindeki PnL ile eşleşmeli
- get_symbol_info başarısız olursa fallback 100.0 kullanılmalı

---

## FAZ 1.5 — Risk Kapalıyken Bias Güncelleme

**Dosya:** `engine/main.py`
**Metod:** `_run_single_cycle`
**Sorun:** `risk_verdict.can_trade=False` olduğunda `process_signals([])` çağrılıyor. Boş sembol listesi = bias güncellenmez. Dashboard eski veri gösterir.

### ESKİ KOD (BUL):

```python
        # ── 6. OĞUL — Sinyal Üretimi + Emir Yönetimi ─────────────
        if risk_verdict.can_trade:
            self.ogul.process_signals(top5, regime)
        else:
            # Risk kapalı: sadece emir yönetimi + trade yönetimi çalışsın
            # Boş liste = yeni sinyal üretme, ama mevcut emirleri yönet
            self.ogul.process_signals([], regime)
```

### YENİ KOD (DEĞİŞTİR):

```python
        # ── 6. OĞUL — Sinyal Üretimi + Emir Yönetimi ─────────────
        # process_signals her zaman çağrılır (emir yönetimi + trailing stop).
        # risk kapalıyken top5 yerine boş liste → sinyal üretilmez.
        # Ama bias her zaman güncellenmeli (Dashboard doğru göstersin).
        if risk_verdict.can_trade:
            self.ogul.process_signals(top5, regime)
        else:
            self.ogul.process_signals([], regime)
            # Risk kapalıyken de bias güncelle (Dashboard için)
            for sym in top5:
                self.ogul.last_signals[sym] = self.ogul._calculate_bias(sym)
```

### TEST KRİTERLERİ:
- Kill-switch aktifken Dashboard'da bias değerleri güncellenmeli
- VOLATILE/OLAY rejimde bias hâlâ hesaplanmalı

---

# ═══════════════════════════════════════════════════════════════
# FAZ 2 — STRATEJİ İYİLEŞTİRMELERİ
# Amaç: Mevcut stratejilerin VİOP'ta edge üretme kapasitesini artır
# Tahmini süre: 1-2 gün
# ═══════════════════════════════════════════════════════════════

---

## FAZ 2.1 — Breakout Çıkış Yönetimi Ekleme

**Dosya:** `engine/ogul.py`
**Sorun:** Breakout pozisyonları sabit SL/TP'ye bırakılmış, programatik çıkış yok. VİOP'ta false breakout oranı yüksek — erken müdahale edilmezse tam SL'ye kadar zarar edilir.

### YENİ SABİTLER EKLE (sabitlerin sonuna, `TRADING_CLOSE` satırından sonra):

```python
# ── Breakout Çıkış Yönetimi ──────────────────────────────────
BO_TRAILING_ATR_MULT: float = 2.0     # trailing stop: giriş ± 2×ATR (trend follow'dan geniş)
BO_REENTRY_BARS: int = 3              # son 3 bar range içine dönmüşse = false breakout
```

### YENİ METOD EKLE (`_manage_mean_reversion` metodundan sonra):

```python
    def _manage_breakout(
        self,
        symbol: str,
        trade: Trade,
        pos: dict[str, Any],
    ) -> None:
        """Breakout işlem yönetimi — false breakout tespiti + trailing stop.

        İki savunma katmanı:
        1. False breakout tespiti: fiyat kırılım range'inin içine geri döndüyse kapat
        2. Trailing stop: 2×ATR (trend follow'dan geniş, breakout'a alan tanı)

        Args:
            symbol: Kontrat sembolü.
            trade: Aktif Trade nesnesi.
            pos: MT5 pozisyon bilgisi.
        """
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < BO_LOOKBACK + 2:
            return

        close = df["close"].values.astype(np.float64)
        high_arr = df["high"].values.astype(np.float64)
        low_arr = df["low"].values.astype(np.float64)

        atr_arr = calc_atr(high_arr, low_arr, close, ATR_PERIOD)
        atr_val = _last_valid(atr_arr)
        if atr_val is None or atr_val <= 0:
            return

        current_price = float(pos.get("price_current", close[-1]))

        # ── False breakout tespiti ────────────────────────────────
        # Son BO_REENTRY_BARS bar'ın tamamı kırılım seviyesinin
        # gerisine dönmüşse = false breakout
        recent_closes = close[-BO_REENTRY_BARS:]

        # Kırılım seviyesi: trade açılırken kaydedilen entry_price
        # BUY breakout: fiyat entry altına düştüyse false
        # SELL breakout: fiyat entry üstüne çıktıysa false
        false_breakout = False
        if trade.direction == "BUY":
            if all(c < trade.entry_price for c in recent_closes):
                false_breakout = True
        else:
            if all(c > trade.entry_price for c in recent_closes):
                false_breakout = True

        if false_breakout:
            logger.info(
                f"False breakout tespit [{symbol}]: fiyat={current_price:.4f} "
                f"entry={trade.entry_price:.4f} — pozisyon kapatılıyor"
            )
            self.mt5.close_position(trade.ticket)
            self._handle_closed_trade(symbol, trade, "false_breakout")
            return

        # ── Trailing stop ─────────────────────────────────────────
        if trade.direction == "BUY":
            new_sl = current_price - BO_TRAILING_ATR_MULT * atr_val
            if new_sl > trade.trailing_sl:
                mod_result = self.mt5.modify_position(
                    trade.ticket, sl=new_sl,
                )
                if mod_result:
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    logger.debug(
                        f"Breakout trailing SL [{symbol}]: {new_sl:.4f}"
                    )
        else:
            new_sl = current_price + BO_TRAILING_ATR_MULT * atr_val
            if new_sl < trade.trailing_sl:
                mod_result = self.mt5.modify_position(
                    trade.ticket, sl=new_sl,
                )
                if mod_result:
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    logger.debug(
                        f"Breakout trailing SL [{symbol}]: {new_sl:.4f}"
                    )
```

### FAZ 1.2'DEKİ GEÇİCİ KODU GÜNCELLE:

`_manage_active_trades` içindeki geçici `pass` satırını değiştir:

```python
            # ESKİ (geçici):
            elif trade.strategy == "breakout":
                pass  # Faz 2.1'de _manage_breakout eklenecek

            # YENİ:
            elif trade.strategy == "breakout":
                self._manage_breakout(symbol, trade, pos)
```

### TEST KRİTERLERİ:
- Breakout pozisyonu açıldığında trailing stop güncellemesi görülmeli
- Fiyat entry altına 3 bar boyunca dönünce false_breakout kapanışı görülmeli
- Normal breakout devam ediyorsa trailing stop yukarı çekilmeli

---

## FAZ 2.2 — Likidite Sınıfına Göre Parametre Farklılaştırma

**Dosya:** `engine/ogul.py`
**Sorun:** 15 kontratın hepsi aynı parametrelerle değerlendiriliyor. F_THYAO (A sınıfı, yüksek hacim) ile F_KONTR (C sınıfı, düşük hacim) aynı volume eşiğine (1.5x) tabi. C sınıfında 1.5x volume çok sık, A sınıfında çok nadir — bu false positive/negative asimetrisi yaratır.

### YENİ SABİTLER EKLE (mevcut sabitlerin sonuna):

```python
# ── Likidite Sınıfı Bazlı Parametreler ───────────────────────
# A sınıfı: yüksek likidite (F_THYAO, F_AKBNK, F_ASELS, F_TCELL, F_PGSUS)
# B sınıfı: orta likidite (F_HALKB, F_GUBRF, F_EKGYO, F_SOKM, F_TKFEN)
# C sınıfı: düşük likidite (F_OYAKC, F_BRSAN, F_AKSEN, F_ASTOR, F_KONTR)

LIQUIDITY_CLASSES: dict[str, str] = {
    "F_THYAO": "A", "F_AKBNK": "A", "F_ASELS": "A",
    "F_TCELL": "A", "F_PGSUS": "A",
    "F_HALKB": "B", "F_GUBRF": "B", "F_EKGYO": "B",
    "F_SOKM": "B", "F_TKFEN": "B",
    "F_OYAKC": "C", "F_BRSAN": "C", "F_AKSEN": "C",
    "F_ASTOR": "C", "F_KONTR": "C",
}

# Breakout: volume çarpanı (likidite bazlı)
BO_VOLUME_MULT_BY_CLASS: dict[str, float] = {
    "A": 1.5,    # A sınıfında 1.5x yeterli (zaten likit)
    "B": 2.0,    # B sınıfında daha yüksek eşik (gürültü filtrele)
    "C": 3.0,    # C sınıfında çok yüksek eşik (gerçek kırılım filtresi)
}

# ATR genişleme çarpanı (likidite bazlı)
BO_ATR_EXPANSION_BY_CLASS: dict[str, float] = {
    "A": 1.2,    # standart
    "B": 1.3,    # biraz daha sıkı
    "C": 1.5,    # C sınıfında ATR zaten geniş, daha sıkı filtre
}

# Trailing stop ATR çarpanı (likidite bazlı) — tüm stratejiler
TRAILING_ATR_BY_CLASS: dict[str, float] = {
    "A": 1.5,    # dar stop (likit, hızlı çıkış mümkün)
    "B": 1.8,    # biraz geniş
    "C": 2.5,    # geniş stop (düşük likidite, spread geniş, fakeout riski)
}
```

### YARDIMCI FONKSİYON EKLE (class içinde, `_calculate_bias`'tan önce):

```python
    @staticmethod
    def _get_liq_class(symbol: str) -> str:
        """Sembolün likidite sınıfını döndür (A/B/C)."""
        return LIQUIDITY_CLASSES.get(symbol, "C")  # bilinmeyen = C (en muhafazakâr)
```

### _check_breakout'TA VOLUME EŞIK DEĞİŞİKLİĞİ:

`_check_breakout` metodu içinde volume kontrolü satırını bul:

```python
        # ESKİ:
        if vol_avg <= 0 or current_vol <= vol_avg * BO_VOLUME_MULT:
            return None

        # YENİ:
        liq_class = self._get_liq_class(symbol)
        vol_mult = BO_VOLUME_MULT_BY_CLASS.get(liq_class, BO_VOLUME_MULT)
        if vol_avg <= 0 or current_vol <= vol_avg * vol_mult:
            return None
```

Aynı metod içinde ATR genişleme kontrolünü bul:

```python
        # ESKİ:
        if atr_mean <= 0 or atr_val <= atr_mean * BO_ATR_EXPANSION:
            return None

        # YENİ:
        atr_exp = BO_ATR_EXPANSION_BY_CLASS.get(liq_class, BO_ATR_EXPANSION)
        if atr_mean <= 0 or atr_val <= atr_mean * atr_exp:
            return None
```

### _manage_trend_follow'DA TRAILING STOP DEĞİŞİKLİĞİ:

```python
        # ESKİ (BUY):
            new_sl = current_price - TF_TRAILING_ATR_MULT * atr_val

        # YENİ (BUY):
            liq_class = self._get_liq_class(symbol)
            trail_mult = TRAILING_ATR_BY_CLASS.get(liq_class, TF_TRAILING_ATR_MULT)
            new_sl = current_price - trail_mult * atr_val

        # ESKİ (SELL):
            new_sl = current_price + TF_TRAILING_ATR_MULT * atr_val

        # YENİ (SELL):
            liq_class = self._get_liq_class(symbol)
            trail_mult = TRAILING_ATR_BY_CLASS.get(liq_class, TF_TRAILING_ATR_MULT)
            new_sl = current_price + trail_mult * atr_val
```

### TEST KRİTERLERİ:
- F_THYAO breakout: volume eşiği 1.5x olmalı
- F_KONTR breakout: volume eşiği 3.0x olmalı
- F_THYAO trailing stop: 1.5 × ATR
- F_KONTR trailing stop: 2.5 × ATR
- Log mesajlarında kullanılan çarpanlar doğru olmalı

---

## FAZ 2.3 — Config Kullanımını Aktifleştirme

**Dosya:** `config/default.json` ve `engine/config.py`
**Sorun:** Config nesnesi her iki modülde saklanıyor ama hiçbir yerde kullanılmıyor. Tüm sabitler hardcoded. Bu, parametre değişikliği için kod değişikliği gerektiriyor — canlı sistemde riskli.

### ADIM 1 — `config/default.json` GÜNCELLEMESİ:

Mevcut JSON'a şu alanları ekle:

```json
{
    "mt5": {
        "path": "C:/Program Files/MetaTrader 5 GCM/terminal64.exe",
        "login": 5030791,
        "server": "GCMForex-Server"
    },
    "engine": {
        "cycle_interval": 10,
        "trading_open": "09:45",
        "trading_close": "17:45",
        "max_concurrent": 5,
        "max_lot_per_contract": 1.0,
        "margin_reserve_pct": 0.20
    },
    "strategies": {
        "trend_follow": {
            "ema_fast": 20,
            "ema_slow": 50,
            "adx_threshold": 25.0,
            "macd_confirm_bars": 2,
            "sl_atr_mult": 1.5,
            "tp_atr_mult": 2.0,
            "trailing_atr_mult": 1.5
        },
        "mean_reversion": {
            "rsi_period": 14,
            "rsi_oversold": 30.0,
            "rsi_overbought": 70.0,
            "adx_threshold": 20.0,
            "bb_period": 20,
            "bb_std": 2.0,
            "sl_atr_mult": 1.0
        },
        "breakout": {
            "lookback": 20,
            "volume_mult": 1.5,
            "atr_expansion": 1.2,
            "trailing_atr_mult": 2.0,
            "reentry_bars": 3
        }
    },
    "liquidity_overrides": {
        "volume_mult": {"A": 1.5, "B": 2.0, "C": 3.0},
        "atr_expansion": {"A": 1.2, "B": 1.3, "C": 1.5},
        "trailing_atr": {"A": 1.5, "B": 1.8, "C": 2.5}
    }
}
```

### ADIM 2 — `engine/config.py` GÜNCELLEMESİ:

Config sınıfı bu alanları parse edebilmeli. Mevcut Config sınıfının yapısını incele ve yukarıdaki alanları ekle. Config'den okunamazsa mevcut hardcoded değerler fallback olarak kullanılmalı.

**ÖNEMLİ NOT:** Bu değişiklik büyük. İlk aşamada sadece `config/default.json`'a alanları ekle ve Config sınıfında bu alanları oku. Oğul'daki sabitleri config'den okuma işini **Faz 3'ten sonra** yap — önce backtest ile mevcut parametrelerin doğruluğunu teyit et, sonra config'e taşı.

Şimdilik sadece JSON dosyasına alanları ekle, ileriye dönük altyapı hazırlığı.

### TEST KRİTERLERİ:
- Config dosyası parse edilebilmeli
- Eksik alan durumunda default değer kullanılmalı
- Engine başlangıcında config değerleri loglanmalı

---

# ═══════════════════════════════════════════════════════════════
# FAZ 3 — BACKTEST DOĞRULAMA VE OPTİMİZASYON
# Amaç: Mevcut ve iyileştirilmiş stratejilerin VİOP verisinde
#        gerçek performansını ölç
# Tahmini süre: 2-3 gün
# ═══════════════════════════════════════════════════════════════

---

## FAZ 3.1 — Backtest ile Mevcut Strateji Performans Ölçümü

**Dosya:** `backtest/` klasörü (mevcut backtest altyapısı)
**Amaç:** Faz 1 ve Faz 2 değişiklikleri uygulandıktan sonra, mevcut üç stratejinin VİOP geçmiş verisinde performansını ölç.

### BACKTEST SENARYOLARI:

```
Senaryo 1: Trend Follow — son 6 ay VİOP verisi
  - Kontratlar: F_THYAO, F_AKBNK, F_ASELS (A sınıfı)
  - Metrikler: Win rate, avg win/loss ratio, max drawdown, Sharpe ratio
  - Karşılaştır: trailing stop eski (1.5x) vs likidite bazlı (1.5/1.8/2.5)

Senaryo 2: Mean Reversion — son 6 ay VİOP verisi
  - Kontratlar: Tüm 15 kontrat
  - Metrikler: Tetiklenme sıklığı, win rate, ortalama trade süresi
  - Özellikle kontrol et: RSI 30/70 eşikleri yeterince sık tetikleniyor mu?

Senaryo 3: Breakout — son 6 ay VİOP verisi
  - Kontratlar: A ve B sınıfı kontratlar
  - Metrikler: False breakout oranı, _manage_breakout etkisi
  - Karşılaştır: eski (sabit SL/TP) vs yeni (trailing + false breakout tespiti)

Senaryo 4: Kombinasyon — tüm stratejiler birlikte
  - Kontratlar: Tüm 15 kontrat, rejim geçişleri dahil
  - Metrikler: Toplam PnL, equity curve, max drawdown, Sharpe ratio
  - Özellikle kontrol et: Rejim geçiş anlarında pozisyon yönetimi
```

### BACKTEST RAPOR FORMATI:

Her senaryo için şu metrikleri raporla:
- Toplam işlem sayısı
- Win rate (%)
- Ortalama kârlı işlem / ortalama zararlı işlem (ratio)
- Maximum drawdown (%)
- Sharpe ratio (yıllık)
- Profit factor (brüt kâr / brüt zarar)
- Ortalama işlem süresi (dakika)
- Kontrat bazlı performans dağılımı (A/B/C sınıfı)

### AKSİYON KARARI:

Backtest sonuçlarına göre:

1. **Win rate < %40 olan strateji:** Parametreleri optimize et veya devre dışı bırak
2. **Profit factor < 1.0 olan kontrat:** O kontratı Top 5'ten hariç tut
3. **Sharpe < 0.5:** Strateji temelden gözden geçir
4. **Mean reversion tetiklenme < ayda 5:** RSI eşiklerini genişlet (25/75)
5. **Breakout false rate > %70:** C sınıfı kontratlardan breakout'u kaldır

---

## FAZ 3.2 — Parametre Optimizasyonu

**Ön koşul:** Faz 3.1 backtest sonuçları hazır olmalı.

Bu adımda, backtest sonuçlarına göre parametreleri optimize et. Optimizasyon walk-forward yöntemiyle yapılmalı (backtest klasöründe `walk_forward.py` mevcut).

### OPTİMİZE EDİLECEK PARAMETRELER:

```
Trend Follow:
  - TF_EMA_FAST: [10, 15, 20, 25]
  - TF_EMA_SLOW: [30, 40, 50, 60]
  - TF_ADX_THRESHOLD: [20, 22.5, 25, 27.5, 30]
  - TF_TRAILING_ATR_MULT: [1.0, 1.25, 1.5, 1.75, 2.0]

Mean Reversion:
  - MR_RSI_OVERSOLD: [20, 25, 30, 35]
  - MR_RSI_OVERBOUGHT: [65, 70, 75, 80]
  - MR_ADX_THRESHOLD: [15, 18, 20, 22, 25]
  - MR_BB_STD: [1.5, 1.75, 2.0, 2.25, 2.5]

Breakout:
  - BO_LOOKBACK: [10, 15, 20, 25, 30]
  - BO_VOLUME_MULT (A/B/C ayrı): mevcut değerler ± %30
  - BO_REENTRY_BARS: [2, 3, 4, 5]
```

### OPTİMİZASYON KURAL:
- Walk-forward: %70 in-sample, %30 out-of-sample
- Out-of-sample Sharpe > 0.5 olan parametre setleri kabul
- Overfitting kontrolü: in-sample ile out-of-sample Sharpe farkı < %50
- Sonuç parametrelerini `config/default.json`'a yaz

---

## FAZ 3.3 — Yeni Strateji Kararı

**Ön koşul:** Faz 3.1 ve 3.2 tamamlanmış olmalı.

Backtest sonuçlarına göre:

### EĞER mevcut 3 strateji yeterli Sharpe (>1.0) üretiyorsa:
- Yeni strateji ekleme → sonraya bırak
- Config'e taşıma işlemini tamamla
- Canlı performans izleme sürecine geç

### EĞER RANGE dönemlerinde equity flat kalıyorsa:
- Grid stratejisi tasarımına başla — AMA netting mode uyumlu:
  - Tek pozisyonu kademeli büyütme/küçültme mantığı
  - Grid seviyeleri = pozisyon artırma/azaltma noktaları
  - Basket PnL takibi (tüm kademeli girişlerin toplamı)
  - Bu ayrı bir geliştirme dokümanı gerektirir

### EĞER belirli kontratlar sürekli zarar üretiyorsa:
- O kontratları WATCHED_SYMBOLS'dan çıkar veya Top 5 puanlamasında penalize et
- ÜSTAT modülünde (`engine/ustat.py`) negatif performans penaltisi ekle

---

# ═══════════════════════════════════════════════════════════════
# UYGULAMA KONTROL LİSTESİ
# ═══════════════════════════════════════════════════════════════

```
FAZ 1 (Bug Düzeltmeleri):
  [ ] 1.1 _update_fill_price → sembol bazlı eşleştirme
  [ ] 1.2 _manage_active_trades → tek MT5 çağrısı + pos_by_symbol
  [ ] 1.3 increment_daily_trade_count → FILLED'a taşı (4 dosya değişikliği)
  [ ] 1.4 CONTRACT_SIZE → kontrat bazlı (get_symbol_info)
  [ ] 1.5 Risk kapalıyken bias güncelleme (main.py)
  [ ] Git commit: "Faz 1: Bug düzeltmeleri — netting, sayaç, contract_size, bias"
  [ ] Engine restart + test

FAZ 2 (Strateji İyileştirmeleri):
  [ ] 2.1 _manage_breakout metodu ekle (false breakout + trailing)
  [ ] 2.2 Likidite sınıfı parametreleri (LIQUIDITY_CLASSES + override dict'ler)
  [ ] 2.2 _check_breakout'ta volume/ATR eşiklerini likidite bazlı yap
  [ ] 2.2 _manage_trend_follow'da trailing stop'u likidite bazlı yap
  [ ] 2.3 config/default.json'a strateji parametrelerini ekle
  [ ] Git commit: "Faz 2: Strateji iyileştirmeleri — breakout, likidite, config"
  [ ] Engine restart + test

FAZ 3 (Backtest):
  [ ] 3.1 Mevcut stratejileri backtest et (4 senaryo)
  [ ] 3.1 Backtest raporu oluştur
  [ ] 3.2 Parametre optimizasyonu (walk-forward)
  [ ] 3.2 Optimize parametreleri config'e yaz
  [ ] 3.3 Yeni strateji kararı (backtest sonuçlarına göre)
  [ ] Git commit: "Faz 3: Backtest sonuçları ve optimize parametreler"
```

---

# ═══════════════════════════════════════════════════════════════
# EK BİLGİLER — CODE AGENT İÇİN NOTLAR
# ═══════════════════════════════════════════════════════════════

## Dosya Konumları ve Boyutları:
- `engine/ogul.py` — ~1995 satır (ana değişiklik dosyası)
- `engine/baba.py` — ~1972 satır (bu fazda değişiklik yok)
- `engine/main.py` — ~562 satır (Faz 1.5'te 3 satır ekleme)
- `engine/models/trade.py` — 57 satır (değişiklik yok)
- `engine/models/signal.py` — 38 satır (değişiklik yok)
- `engine/config.py` — 51 satır (Faz 2.3'te genişletilecek)
- `config/default.json` — 34 satır (Faz 2.3'te genişletilecek)

## Import Gereksinimleri:
- Yeni import gerekmiyor (tüm kullanılan modüller zaten import edilmiş)

## Mevcut Test Dosyaları:
- `tests/test_ogul.py` — 2511 satır (mevcut testler Faz 1 değişikliklerinden etkilenebilir)
- `tests/test_baba.py` — 2909 satır
- `tests/test_main.py` — 1047 satır

## Kritik Kısıtlar:
- VİOP netting mode: sembol başına TEK pozisyon
- active_trades: dict[str, Trade] — sembol → tek Trade
- MT5 bağlantısı GCM Forex server üzerinden
- İşlem saatleri: 09:45-17:45 (Türkiye saati)
- Gün sonu: tüm pozisyonlar kapatılır
- Bugün (2026-02-27): VIOP vade sonu — OLAY rejimi aktif

## Risk Hatırlatma:
Bu canlı bir trading sistemidir. Her değişiklik:
1. Önce test ortamında (veya piyasa kapalıyken) denenmelidir
2. Git commit ile geri alınabilir olmalıdır
3. Engine restart sonrası mevcut pozisyonları etkilememeli (restore_active_trades)
4. Log mesajları ile doğrulanabilir olmalıdır
