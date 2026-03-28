# OĞUL _calculate_lot() — Yedek (Test Süreci Sonrası Kullanılacak)

**Tarih:** 2026-03-28
**Neden yedeklendi:** Test sürecinde lot=1 sabit. Bu fonksiyon test bitince geri gelecek.
**Kaynak:** engine/ogul.py satır 2206-2323 (v5.8)
**Kim istedi:** Kullanıcı (Turan Aykut)

## İlişkili Sabitler (ogul.py modül seviyesi)

```python
MAX_LOT_PER_CONTRACT: float  = 1.0     # test süreci: kontrat başına max 1 lot
MARGIN_RESERVE_PCT_DEFAULT: float = 0.20

# ── FAZ 3: Conviction (inanç) bazlı lot ölçekleme ────────────
CONVICTION_HIGH_THRESHOLD: float = 75.0    # Confluence >= 75 → tam lot
CONVICTION_MED_THRESHOLD:  float = 60.0    # Confluence 60-75 → %70 lot
CONVICTION_LOW_MULT:       float = 0.5     # Confluence < 60 → %50 lot
CONVICTION_HIGH_MULT:      float = 1.0     # Yüksek inanç → tam lot
CONVICTION_MED_MULT:       float = 0.7     # Orta inanç → %70 lot
```

## _execute_signal() içindeki lot çarpanları (satır 1998-2067)

```python
# 1. ÜSTAT lot_scale
ustat_lot_scale = self._get_ustat_param("lot_scale", 1.0)
if ustat_lot_scale != 1.0:
    lot = lot * ustat_lot_scale

# 2. ENTRY_LOT_FRACTION (evrensel yönetim yarılama)
if USE_UNIVERSAL_MANAGEMENT:
    if lot <= 2:
        fraction = 1.0
    else:
        fraction = ENTRY_LOT_FRACTION  # 0.5
    lot = lot * fraction
    # Lot step yuvarlama
    try:
        sym_info = self.mt5.get_symbol_info(signal.symbol)
        if sym_info and hasattr(sym_info, "volume_step"):
            step = sym_info.volume_step
            if step > 0:
                lot = round(
                    math.floor(lot / step) * step,
                    int(round(-math.log10(step))),
                )
    except Exception:
        pass
    if lot <= 0:
        # vol_min fallback
        try:
            sym_info_f = self.mt5.get_symbol_info(signal.symbol)
            v_min = sym_info_f.volume_min if sym_info_f else 1.0
        except Exception:
            v_min = 1.0
        fractioned_lot = lot_before_fraction * fraction
        if fractioned_lot >= v_min * 0.5:
            lot = v_min
        else:
            # iptal
            return
```

## Ana Fonksiyon: _calculate_lot()

```python
def _calculate_lot(
    self,
    signal: Signal,
    regime: Regime,
    equity: float,
    risk_params: RiskParams,
) -> float:
    """Pozisyon boyutu hesapla.

    BABA varsa ``calculate_position_size`` kullanır,
    yoksa basit fallback (1 lot). Her durumda
    ``MAX_LOT_PER_CONTRACT`` ile sınırlar.

    A4: Bias-lot entegrasyonu — bias ters yöndeyse lot=0,
    bias nötr ise lot*0.7 (güven düşürme).

    Returns:
        Hesaplanan lot miktarı.
    """
    if self.baba:
        atr_val = self._get_current_atr(signal.symbol)
        if atr_val is None or atr_val <= 0:
            return 0.0
        lot = self.baba.calculate_position_size(
            signal.symbol, risk_params, atr_val, equity,
        )
    else:
        lot = 1.0

    # A4: Bias-lot entegrasyonu
    bias = self._calculate_bias(signal.symbol)
    direction = "BUY" if signal.signal_type == SignalType.BUY else "SELL"
    if bias != "NOTR" and bias != direction:
        # Bias ters yönde → işlem yapma
        logger.info(
            f"Bias-lot engeli [{signal.symbol}]: "
            f"sinyal={direction}, bias={bias} → lot=0"
        )
        return 0.0
    elif bias == "NOTR":
        # Bias nötr → güven düşürme (Fix 6: 0.7→0.85 yumuşatma)
        lot = lot * 0.85
        logger.debug(
            f"Bias-lot nötr [{signal.symbol}]: lot*0.85={lot:.2f}"
        )

    # ── FAZ 3: Conviction bazlı lot ölçekleme ───────────────
    try:
        df = self.db.get_bars(signal.symbol, "M15", limit=MIN_BARS_M15)
        if df is not None and not df.empty and len(df) >= MIN_BARS_M15:
            _close = df["close"].values.astype(np.float64)
            _high = df["high"].values.astype(np.float64)
            _low = df["low"].values.astype(np.float64)
            _volume = df["volume"].values.astype(np.float64)
            _open = df["open"].values.astype(np.float64) if "open" in df.columns else _close.copy()

            _atr_arr = calc_atr(_high, _low, _close, ATR_PERIOD)
            _atr = last_valid(_atr_arr)
            if _atr is not None and _atr > 0:
                _levels = find_support_resistance(_high, _low, _close, _atr)
                _patterns = detect_bar_patterns(_open, _high, _low, _close, _atr)
                _trend = analyze_trend_structure(_high, _low, _close)

                _ema_f = last_valid(ema(_close, TF_EMA_FAST)) or 0
                _ema_s = last_valid(ema(_close, TF_EMA_SLOW)) or 0
                _rsi = last_valid(calc_rsi(_close, MR_RSI_PERIOD)) or 50
                _, _, _hist = calc_macd(_close)
                _hist_val = last_valid(_hist) or 0
                _adx = last_valid(calc_adx(_high, _low, _close, ATR_PERIOD)) or 0
                _vol_avg = float(np.nanmean(_volume[-21:-1])) if len(_volume) > 21 else float(np.nanmean(_volume))
                _vol_ratio = float(_volume[-1]) / _vol_avg if _vol_avg > 0 else 1.0

                conf = calculate_confluence(
                    direction=direction, price=signal.price,
                    levels=_levels, patterns=_patterns, trend=_trend,
                    atr_val=_atr, adx_val=_adx, rsi_val=_rsi,
                    macd_hist=_hist_val, ema_fast=_ema_f, ema_slow=_ema_s,
                    volume_ratio=_vol_ratio,
                    regime_type=regime.regime_type.value if regime else "",
                )

                # Fix M17: Confluence skor sınır kontrolü
                if conf.total_score < 0 or conf.total_score > 100:
                    conf.total_score = max(0.0, min(100.0, conf.total_score))

                if conf.total_score >= CONVICTION_HIGH_THRESHOLD:
                    conv_mult = CONVICTION_HIGH_MULT
                elif conf.total_score >= CONVICTION_MED_THRESHOLD:
                    conv_mult = CONVICTION_MED_MULT
                else:
                    conv_mult = CONVICTION_LOW_MULT

                lot = lot * conv_mult
    except Exception as exc:
        logger.warning(f"[FAZ3] Conviction sizing hatası [{signal.symbol}]: {exc}")

    # v14: Lot çarpan yığılması koruması
    if 0 < lot < 1.0:
        lot = 1.0

    return min(lot, MAX_LOT_PER_CONTRACT)
```

## Hesaplama Akışı (10 Adım)

1. BABA `calculate_position_size()` → risk bazlı lot
2. Bias-lot entegrasyonu → ters yön lot=0, nötr ×0.85
3. Conviction sizing → confluence skora göre ×0.5/×0.7/×1.0
4. Lot floor koruması → lot < 1.0 ise 1.0'a yuvarla
5. MAX_LOT_PER_CONTRACT sınırı → min(lot, 1.0)
6. ÜSTAT lot_scale çarpanı
7. ENTRY_LOT_FRACTION yarılama (0.5)
8. Lot step yuvarlama (volume_step)
9. vol_min fallback
10. R-Multiple initial_risk hesaplama

## Bilinen Sorunlar (Test Süreci Sonrası Düzeltilecek)

- MAX_LOT_PER_CONTRACT=1.0 → ENTRY_LOT_FRACTION hiçbir zaman uygulanmıyor
- Piramitleme ve maliyetlendirme MAX_LOT sınırı yüzünden çalışmıyor
- R-Multiple canlı hesabında CONTRACT_SIZE=100 hardcoded (get_symbol_info override yok)
- Bias-lot engeli sinyal gücü yerine oylama sonucuna bakıyor — sinyal güçlü olsa bile bias NOTR'da lot %15 düşüyor
