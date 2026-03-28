# OĞUL Pozisyon Yönetim Sistemi — Tasarım Dokümanı

**Tarih:** 2026-03-28
**Versiyon:** v1.0
**Kim istedi:** Turan Aykut
**Durum:** Tasarım onaylandı, inceleme bitince uygulanacak

---

## 1. TEMEL FELSEFE

OĞUL bir trader:
- Kârdayken SÜR, zarardayken KES
- Trend devam ediyorken GENİŞLET, bozuluyorken SIKILAŞTIR
- Yapısal seviyeler (swing) her zaman sabit %'den önemli
- RSI overbought = çıkış DEĞİL (trend piyasasında haftalarca kalır)

---

## 2. 4 MOD SİSTEMİ

```
İşlem açıldı
    │
    ▼
┌─────────┐   kâr < breakeven    ┌──────────┐
│ KORUMA  │◄────────────────────│  GİRİŞ   │
│  MODU   │                      └──────────┘
└────┬────┘
     │ kâr ≥ breakeven (1×ATR)
     ▼
┌─────────┐   trend devam + momentum güçlü
│  TREND  │◄─────────────────────────────────
│  MODU   │
└────┬────┘
     │ momentum zayıflıyor (RSI divergence, hacim düşüyor)
     ▼
┌─────────┐
│ SAVUNMA │
│  MODU   │
└────┬────┘
     │ yapısal bozulma (LL/HH kırılması, EMA kapanış)
     ▼
┌─────────┐
│  ÇIKIŞ  │ → POZİSYON KAPATILDI
│  MODU   │
└─────────┘
```

### Mod Geçiş Kuralları
- KORUMA → TREND: kâr ≥ 1×ATR (breakeven çekilir)
- TREND → SAVUNMA: 3 momentum sinyalinden 2'si uyarı
- SAVUNMA → TREND: momentum tekrar güçlenirse (geri dönüş mümkün)
- SAVUNMA → ÇIKIŞ: yapısal bozulma (1 sinyal yeterli)
- KORUMA → ÇIKIŞ: SL tetiklenir veya yapısal bozulma
- TREND → ÇIKIŞ: ani yapısal bozulma (nadir ama olabilir)

---

## 3. MOD DETAYLARI

### MOD 1: KORUMA (Giriş → Breakeven)

**Trader mantığı:** "Girişim doğru muydu? SL yerinde, bekleyelim."

| Parametre | Değer |
|-----------|-------|
| Trailing SL | Giriş SL'si sabit (yapısal — swing low/high) |
| Çıkış | SL tetiklenir (MT5 otomatik) |
| Müdahale | YOK — sabırlı bekle |
| Süre limiti | 2 saat (8×M15) içinde breakeven'a ulaşamazsa değerlendir |

**2 saat kuralı:**
- Kârdaysa → devam (trend yavaş gelişiyor)
- Zarardaysa ama SL'den uzaksa → trailing SL sıkılaştır (entry - 0.5×ATR)
- SL'ye yakınsa → SL'nin işini yapmasını bekle

### MOD 2: TREND (Breakeven → Kâr Maximizasyonu)

**Trader mantığı:** "Harika gidiyor, trendi sonuna kadar sür."

| Parametre | Değer |
|-----------|-------|
| Trailing SL | Son SWING LOW/HIGH (yapısal) |
| Buffer | Swing seviye - 0.2×ATR (gürültü koruması) |
| RSI | İZLE — kapatma kararı DEĞİL |
| Pullback | Swing kırılmadıkça TUT (sabit % yok) |
| Breakeven | Çoktan çekildi — risksiz |

**Swing trailing mantığı (BUY örnek):**
```
Giriş: 140.00
Swing low 1: 139.50 → trailing: 139.20
Fiyat yükselir, yeni swing low: 142.00 → trailing: 141.70
Fiyat yükselir, yeni swing low: 144.50 → trailing: 144.20
Pullback: 145.00 (trailing 144.20'den yukarı) → TUT
Fiyat devam: 148.00, swing low: 146.00 → trailing: 145.70
```

### MOD 3: SAVUNMA (Momentum Zayıflıyor)

**Trader mantığı:** "Rüzgar azalıyor, yelkenleri topla ama henüz limana dönme."

| Parametre | Değer |
|-----------|-------|
| Trailing SL | EMA20 bazlı (sıkılaştırılmış) |
| Formül | BUY: EMA20 - 1.0×ATR, SELL: EMA20 + 1.0×ATR |
| Pullback | Peak kârın %30'u |
| Çıkış | EMA20 altına/üstüne M15 kapanışı veya yapısal bozulma |

**Geri dönüş:** Momentum tekrar güçlenirse (uyarılar 0'a düşerse) → TREND moduna geri dön.

### MOD 4: ÇIKIŞ (Pozisyon Kapatma)

**Trader mantığı:** "İş bitti, çık."

| Tetikleyici | Açıklama |
|-------------|----------|
| Lower Low (BUY) | Son swing low, önceki swing low'dan düşük |
| Higher High (SELL) | Son swing high, önceki swing high'dan yüksek |
| EMA20 kapanış | M15 mum EMA20'nin ters tarafında kapandı + hacim artışı |
| Entry geri alım | Fiyat breakeven sonrası entry price altına/üstüne döndü |

Aksiyon: ANINDA market emir ile kapat.

---

## 4. MOMENTUM DEĞERLENDİRME

3 sinyalden 2'si uyarı verirse → SAVUNMA moduna geçiş.

### Sinyal 1: RSI Divergence
- BUY pozisyonda: fiyat yeni high yaparken RSI düşük high → bearish divergence
- SELL pozisyonda: fiyat yeni low yaparken RSI yüksek low → bullish divergence
- RSI overbought/oversold TEK BAŞINA çıkış sinyali DEĞİL

### Sinyal 2: Hacim Azalması
- Son 5 bar ortalama hacmi < önceki 5 bar ortalamasının %70'i
- Trend hacimle desteklenmiyorsa momentum zayıflıyor

### Sinyal 3: Mum Gövdesi Küçülmesi
- Son 3 mumun ortalama gövdesi < 20-bar ortalama gövdenin %50'si
- Alıcı/satıcı gücü azalıyor

---

## 5. YAPISAL BOZULMA TESPİTİ

### BUY Pozisyonda Bozulma (1 tanesi yeterli → ÇIKIŞ):
1. **Lower Low:** Son swing low < önceki swing low
2. **EMA20 kapanış:** M15 mum EMA20 altında kapandı + hacim ortalamanın üstünde
3. **Entry geri alım:** Breakeven sonrası fiyat entry price altına döndü

### SELL Pozisyonda Bozulma (1 tanesi yeterli → ÇIKIŞ):
1. **Higher High:** Son swing high > önceki swing high
2. **EMA20 kapanış:** M15 mum EMA20 üstünde kapandı + hacim ortalamanın üstünde
3. **Entry geri alım:** Breakeven sonrası fiyat entry price üstüne döndü

---

## 6. KOD YAPISI

```python
def _manage_position(self, symbol, trade, pos):
    """4 modlu adaptif pozisyon yönetimi."""
    current_price = pos["price_current"]

    # 1. Temel veriler (tek seferde)
    df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values
    open_ = df["open"].values

    atr_val = self._get_current_atr(symbol)
    trend = analyze_trend_structure(high, low, close)

    # 2. Kâr/zarar hesapla
    if trade.direction == "BUY":
        profit_pts = current_price - trade.entry_price
    else:
        profit_pts = trade.entry_price - current_price
    trade.peak_profit = max(trade.peak_profit, profit_pts)

    # 3. Mod belirle
    mode = self._determine_mode(trade, profit_pts, atr_val, trend,
                                 close, high, low, volume, open_)
    trade.current_mode = mode

    # 4. Moda göre yönet
    if mode == "KORUMA":
        self._mode_protect(symbol, trade, atr_val)
    elif mode == "TREND":
        self._mode_trend(symbol, trade, current_price, atr_val, trend)
    elif mode == "SAVUNMA":
        self._mode_defend(symbol, trade, current_price, atr_val,
                          close, high, low)
    elif mode == "ÇIKIŞ":
        self._mode_exit(symbol, trade)


def _determine_mode(self, trade, profit_pts, atr_val, trend,
                     close, high, low, volume, open_):
    """Pozisyonun mevcut modunu belirle."""

    # ÇIKIŞ kontrolü (her zaman önce)
    if self._is_structural_break(trade, trend, close, high, low, volume):
        return "ÇIKIŞ"

    # Henüz breakeven'a ulaşmadı
    if not trade.breakeven_hit:
        if profit_pts >= atr_val:
            trade.breakeven_hit = True
            # Breakeven çek
            self._set_breakeven(trade)
            return "TREND"
        return "KORUMA"

    # Breakeven geçildi — momentum kontrol
    momentum = self._check_momentum(trade, close, high, low, volume, open_)

    if momentum == "strong":
        return "TREND"
    elif momentum == "weakening":
        return "SAVUNMA"
    else:  # "lost"
        return "ÇIKIŞ"


def _check_momentum(self, trade, close, high, low, volume, open_):
    """Momentum gücünü değerlendir: strong / weakening / lost."""
    warnings = 0

    # 1. RSI Divergence
    if self._detect_rsi_divergence(close, trade.direction):
        warnings += 1

    # 2. Hacim azalıyor
    if len(volume) >= 10:
        recent_vol = float(np.mean(volume[-5:]))
        prev_vol = float(np.mean(volume[-10:-5]))
        if prev_vol > 0 and recent_vol < prev_vol * 0.7:
            warnings += 1

    # 3. Mum gövdeleri küçülüyor
    if len(close) >= 20 and len(open_) >= 20:
        recent_bodies = float(np.mean(np.abs(close[-3:] - open_[-3:])))
        avg_body = float(np.mean(np.abs(close[-20:] - open_[-20:])))
        if avg_body > 0 and recent_bodies < avg_body * 0.5:
            warnings += 1

    if warnings >= 2:
        return "weakening"
    else:
        return "strong"


def _is_structural_break(self, trade, trend, close, high, low, volume):
    """Yapısal bozulma var mı?"""
    ema_20 = ema(close, 20)
    ema_val = last_valid(ema_20)
    avg_vol = float(np.mean(volume[-20:])) if len(volume) >= 20 else 0
    current_vol = float(volume[-1]) if len(volume) > 0 else 0

    if trade.direction == "BUY":
        # Lower Low oluştu mu?
        if (trend.last_swing_low is not None
            and trend.prev_swing_low is not None
            and trend.last_swing_low < trend.prev_swing_low):
            return True
        # EMA20 altına kapanış + hacim artışı
        if (ema_val and close[-1] < ema_val
            and avg_vol > 0 and current_vol > avg_vol):
            return True
    else:
        # Higher High oluştu mu?
        if (trend.last_swing_high is not None
            and trend.prev_swing_high is not None
            and trend.last_swing_high > trend.prev_swing_high):
            return True
        # EMA20 üstüne kapanış + hacim artışı
        if (ema_val and close[-1] > ema_val
            and avg_vol > 0 and current_vol > avg_vol):
            return True

    return False


def _mode_protect(self, symbol, trade, atr_val):
    """KORUMA modu: SL yerinde, bekle. 2 saat kuralı kontrol."""
    if trade.opened_at:
        hours = (datetime.now() - trade.opened_at).total_seconds() / 3600
        if hours >= 2:
            # 2 saat doldu, breakeven'a ulaşamadı
            tick = self.mt5.get_tick(symbol)
            if tick:
                current = tick.bid if trade.direction == "BUY" else tick.ask
                if trade.direction == "BUY":
                    profit = current - trade.entry_price
                else:
                    profit = trade.entry_price - current

                if profit < 0:
                    # Zararda — SL sıkılaştır
                    new_sl = (trade.entry_price - 0.5 * atr_val
                              if trade.direction == "BUY"
                              else trade.entry_price + 0.5 * atr_val)
                    # Mevcut SL'den daha sıkı olmalı
                    if trade.direction == "BUY" and new_sl > trade.sl:
                        self.mt5.modify_position(trade.ticket, sl=new_sl)
                        trade.sl = new_sl
                    elif trade.direction == "SELL" and new_sl < trade.sl:
                        self.mt5.modify_position(trade.ticket, sl=new_sl)
                        trade.sl = new_sl


def _mode_trend(self, symbol, trade, current_price, atr_val, trend):
    """TREND modu: swing bazlı geniş trailing."""
    swing_sl = get_structural_sl(
        trade.direction, current_price,
        trend.swing_lows, trend.swing_highs,
        atr_val, buffer_atr_mult=0.2,
    )

    if swing_sl is None:
        return

    # Min/max trailing mesafe sınırı
    swing_sl = _clamp_trailing_distance(
        trade.direction, current_price, swing_sl
    )

    # Sadece sıkılaştırma (monoton)
    if trade.direction == "BUY":
        if swing_sl > trade.trailing_sl:
            result = self.mt5.modify_position(trade.ticket, sl=swing_sl)
            if result:
                trade.trailing_sl = swing_sl
                trade.sl = swing_sl
    else:
        update = (trade.trailing_sl <= 0 or swing_sl < trade.trailing_sl)
        if update:
            result = self.mt5.modify_position(trade.ticket, sl=swing_sl)
            if result:
                trade.trailing_sl = swing_sl
                trade.sl = swing_sl


def _mode_defend(self, symbol, trade, current_price, atr_val,
                  close, high, low):
    """SAVUNMA modu: EMA20 bazlı sıkı trailing."""
    ema_20 = ema(close, 20)
    ema_val = last_valid(ema_20)
    if ema_val is None:
        return

    liq_class = self._get_liq_class(symbol)
    trail_mult = TRAIL_ATR_BY_CLASS.get(liq_class, 1.0)

    if trade.direction == "BUY":
        new_sl = ema_val - trail_mult * atr_val
        new_sl = _clamp_trailing_distance("BUY", current_price, new_sl)
        if new_sl > trade.trailing_sl:
            result = self.mt5.modify_position(trade.ticket, sl=new_sl)
            if result:
                trade.trailing_sl = new_sl
                trade.sl = new_sl
    else:
        new_sl = ema_val + trail_mult * atr_val
        new_sl = _clamp_trailing_distance("SELL", current_price, new_sl)
        update = (trade.trailing_sl <= 0 or new_sl < trade.trailing_sl)
        if update:
            result = self.mt5.modify_position(trade.ticket, sl=new_sl)
            if result:
                trade.trailing_sl = new_sl
                trade.sl = new_sl


def _mode_exit(self, symbol, trade):
    """ÇIKIŞ modu: anında kapat."""
    try:
        self.mt5.close_position(trade.ticket)
    except Exception as exc:
        logger.error(f"Çıkış modu kapatma hatası [{symbol}]: {exc}")
    self._handle_closed_trade(symbol, trade, f"structural_break_{trade.current_mode}")
```

---

## 7. MEVCUT KODDAN KULLANILACAK / KALDIRILACAK

### Kullanılacak (aynen veya adapte)
| Fonksiyon | Kullanım |
|-----------|----------|
| `analyze_trend_structure()` | Swing tespiti, yapısal bozulma |
| `get_structural_sl()` | TREND modu swing trailing |
| `_clamp_trailing_distance()` | Trailing min/max sınırı |
| `_check_volume_spike()` | Hacim patlaması (ek çıkış sinyali) |
| `calc_rsi()` | RSI divergence tespiti |
| `ema()` | EMA20 bazlı trailing (SAVUNMA modu) |
| `_handle_closed_trade()` | Kapanış işleme |

### Kaldırılacak
| Mekanizma | Neden |
|-----------|-------|
| Oylama bazlı çıkış kararı | Trend gününü öldürüyor |
| Pullback toleransı (sabit %) | Swing bazlı ile değiştirildi |
| TP1 yarı kapanış | Lot=1 iken çalışmıyor |
| TP2/TP3 | Hiç implemente edilmemiş |
| Maliyetlendirme | Lot=1 iken çalışmıyor |
| Piramitleme | send_market_order yok + lot=1 |
| Chandelier Exit | Swing trailing yeterli |
| R-Multiple çıkış kararı | Sadece loglama için kalacak |
| Oylama skoru bazlı çıkış | Kaldırılacak (momentum tespiti ile değiştirildi) |

### Dashboard bilgilendirme olarak kalacak
| Mekanizma | Amaç |
|-----------|------|
| `_calculate_voting()` | UI'da yön göstergesi olarak |
| R-Multiple loglama | Performans analizi için |
| Peak profit takibi | İstatistik için |

---

## 8. ÖRNEK SENARYOLAR

### Senaryo 1: Güçlü Trend Günü (Hedef: +10 TL hareket)
```
09:45  BUY @ 140.00, SL: 138.50 → KORUMA
10:30  +1.8 (>1×ATR) → breakeven → TREND
       Trailing: swing low 140.50 → 140.20
11:30  +6.0, swing low: 143.50 → trailing: 143.20
13:00  +5.0 (pullback) > 143.20 → TUT
       Momentum: 1 uyarı → hâlâ TREND
14:30  +8.0, swing low: 146.00 → trailing: 145.70
16:00  +10.0, momentum: 2 uyarı → SAVUNMA
       EMA trailing: 148.80 - 1.5 = 147.30
       Swing trailing: 148.20 (daha sıkı → bunu kullan)
17:45  EOD → KAPAT @ 149.50 → +9.50 TL ✓
```

### Senaryo 2: Yanlış Giriş (SL Koruması)
```
09:45  BUY @ 140.00, SL: 138.50 → KORUMA
10:00  Fiyat: 139.50 (aleyhine)
       KORUMA modu: SL yerinde, bekle
10:30  Fiyat: 138.50 → SL tetiklendi → -1.50 TL zarar
       MT5 otomatik kapattı ✓
```

### Senaryo 3: Yavaş Giriş → 2 Saat Kuralı
```
09:45  BUY @ 140.00, SL: 138.50 → KORUMA
10:00  Fiyat: 140.20 (yatay)
11:00  Fiyat: 139.80 (yatay)
11:45  2 saat doldu, kâr yok, zararda (-0.20)
       SL sıkılaştır: 140.00 - 0.75 = 139.25
       Yeni SL: 139.25 (138.50'den sıkı)
12:30  Fiyat: 139.25 → yeni SL tetiklendi → -0.75 TL zarar
       (eski SL olsaydı -1.50 olacaktı → zarar azaltıldı) ✓
```

### Senaryo 4: Momentum Zayıflama → Erken Çıkış
```
09:45  BUY @ 140.00 → KORUMA
10:15  +1.5 → breakeven → TREND
       Trailing: 139.80
11:00  +3.0, swing low: 141.50, trailing: 141.20
11:30  RSI divergence + hacim düştü → SAVUNMA
       EMA trailing: 142.00 - 1.5 = 140.50
       (swing 141.20 daha sıkı → 141.20 kullan)
12:00  Lower Low oluştu (swing low kırıldı) → ÇIKIŞ
       KAPAT @ 141.80 → +1.80 TL kâr ✓
       (kâr az ama yapısal bozulma → doğru karar)
```

---

## 9. UYGULAMA PLANI

1. Trade modeline `current_mode` alanı ekle
2. `_manage_position()` fonksiyonunu 4 modlu yapıya dönüştür
3. `_determine_mode()` fonksiyonu yaz
4. `_check_momentum()` fonksiyonu yaz (RSI divergence dahil)
5. `_is_structural_break()` fonksiyonu yaz
6. `_mode_protect()`, `_mode_trend()`, `_mode_defend()`, `_mode_exit()` yaz
7. Eski mekanizmaları kaldır (oylama çıkışı, sabit pullback, TP1, piramitleme vb.)
8. Test et: simülasyon verileriyle 4 senaryo doğrula
9. Loglama: her mod geçişinde detaylı log yaz
