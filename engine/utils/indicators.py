"""Teknik indikatörler — saf NumPy implementasyonu.

TA-Lib bağımlılığı olmadan, yalnızca numpy kullanarak
EMA, SMA, RSI, MACD, ADX, Bollinger Bands, ATR,
Keltner Channel, Williams %R, Normalized ATR,
BB/KC Squeeze, ADX Slope ve Hurst Exponent hesaplar.

Tüm fonksiyonlar ``np.ndarray`` kabul eder ve ``np.ndarray`` döndürür.
İlk ``period-1`` eleman ``np.nan`` olabilir (warm-up dönemi).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ═════════════════════════════════════════════════════════════════════
#  SMA
# ═════════════════════════════════════════════════════════════════════

def sma(data: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average.

    Args:
        data: Fiyat serisi (1-D).
        period: Pencere uzunluğu (>= 1).

    Returns:
        SMA dizisi.  İlk ``period-1`` eleman ``np.nan``.
    """
    data = np.asarray(data, dtype=np.float64)
    if period < 1:
        raise ValueError(f"period >= 1 olmalı, verilen: {period}")

    out = np.full_like(data, np.nan)
    if len(data) < period:
        return out

    # cumsum ile O(n)
    cs = np.cumsum(data)
    out[period - 1] = cs[period - 1] / period
    if len(data) > period:
        out[period:] = (cs[period:] - cs[:-period]) / period

    return out


# ═════════════════════════════════════════════════════════════════════
#  EMA
# ═════════════════════════════════════════════════════════════════════

def ema(data: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average.

    İlk değer SMA(period) ile başlatılır, sonra
    ``EMA_t = close_t * k  +  EMA_{t-1} * (1-k)``  formülü uygulanır.
    ``k = 2 / (period + 1)``

    Args:
        data: Fiyat serisi (1-D).
        period: Periyot (>= 1).

    Returns:
        EMA dizisi.  İlk ``period-1`` eleman ``np.nan``.
    """
    data = np.asarray(data, dtype=np.float64)
    if period < 1:
        raise ValueError(f"period >= 1 olmalı, verilen: {period}")

    n = len(data)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period:
        return out

    k = 2.0 / (period + 1)

    # Seed = ilk period elemanın SMA'sı
    out[period - 1] = np.mean(data[:period])

    for i in range(period, n):
        out[i] = data[i] * k + out[i - 1] * (1.0 - k)

    return out


# ═════════════════════════════════════════════════════════════════════
#  RSI
# ═════════════════════════════════════════════════════════════════════

def rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index (Wilder's smoothing).

    Adımlar:
        1. ``delta = close[i] - close[i-1]``
        2. ``gain / loss`` ayrıştırması
        3. İlk ortalama = SMA(period),  sonrası Wilder smooth
        4. ``RSI = 100 - 100 / (1 + RS)``

    Args:
        data: Kapanış fiyat serisi (1-D).
        period: Periyot (varsayılan 14).

    Returns:
        RSI dizisi (0–100).  İlk ``period`` eleman ``np.nan``.
    """
    data = np.asarray(data, dtype=np.float64)
    if period < 1:
        raise ValueError(f"period >= 1 olmalı, verilen: {period}")

    n = len(data)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period + 1:
        return out

    delta = np.diff(data)                    # n-1 eleman
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)

    # İlk ortalama (SMA seed)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    # Wilder smoothing
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            out[i + 1] = 100.0
        else:
            out[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    return out


# ═════════════════════════════════════════════════════════════════════
#  MACD
# ═════════════════════════════════════════════════════════════════════

def macd(
    data: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD (Moving Average Convergence Divergence).

    ``MACD line   = EMA(fast) - EMA(slow)``
    ``Signal line = EMA(MACD line, signal)``
    ``Histogram   = MACD line - Signal line``

    Args:
        data: Kapanış fiyat serisi (1-D).
        fast: Hızlı EMA periyodu (varsayılan 12).
        slow: Yavaş EMA periyodu (varsayılan 26).
        signal: Sinyal EMA periyodu (varsayılan 9).

    Returns:
        (macd_line, signal_line, histogram) tuple'ı.
    """
    data = np.asarray(data, dtype=np.float64)

    ema_fast = ema(data, fast)
    ema_slow = ema(data, slow)

    macd_line = ema_fast - ema_slow

    # Signal line: MACD line üzerinde EMA
    # NaN olmayan ilk index'ten itibaren hesapla
    valid_start = slow - 1   # ema_slow'un ilk geçerli noktası
    if valid_start < len(macd_line):
        macd_valid = macd_line[valid_start:]
        sig_raw = ema(macd_valid, signal)
        signal_line = np.full_like(macd_line, np.nan)
        signal_line[valid_start:] = sig_raw
    else:
        signal_line = np.full_like(macd_line, np.nan)

    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


# ═════════════════════════════════════════════════════════════════════
#  ATR
# ═════════════════════════════════════════════════════════════════════

def atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Average True Range (Wilder's smoothing).

    ``TR = max(H-L, |H-prev_C|, |L-prev_C|)``
    İlk ATR = SMA(TR, period),  sonrası Wilder smooth.

    Args:
        high: Yüksek fiyat serisi.
        low: Düşük fiyat serisi.
        close: Kapanış fiyat serisi.
        period: Periyot (varsayılan 14).

    Returns:
        ATR dizisi.  İlk ``period`` eleman ``np.nan``.
    """
    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    close = np.asarray(close, dtype=np.float64)
    if period < 1:
        raise ValueError(f"period >= 1 olmalı, verilen: {period}")

    n = len(high)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period + 1:
        return out

    # True Range
    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)

    # İlk ATR = SMA(TR[1:period+1])
    out[period] = np.mean(tr[1 : period + 1])

    # Wilder smoothing
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period

    return out


# ═════════════════════════════════════════════════════════════════════
#  ADX
# ═════════════════════════════════════════════════════════════════════

def adx(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Average Directional Index (Wilder's smoothing).

    Adımlar:
        1. +DM / -DM hesapla
        2. Wilder-smooth +DM, -DM, TR → +DI, -DI
        3. DX = |+DI - -DI| / (+DI + -DI) * 100
        4. ADX = Wilder-smooth(DX)

    Args:
        high: Yüksek fiyat serisi.
        low: Düşük fiyat serisi.
        close: Kapanış fiyat serisi.
        period: Periyot (varsayılan 14).

    Returns:
        ADX dizisi.  İlk ~``2*period`` eleman ``np.nan``.
    """
    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    close = np.asarray(close, dtype=np.float64)
    if period < 1:
        raise ValueError(f"period >= 1 olmalı, verilen: {period}")

    n = len(high)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < 2 * period + 1:
        return out

    # ── True Range ───────────────────────────────────────────────────
    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)

    # ── +DM / -DM ───────────────────────────────────────────────────
    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down

    # ── Wilder smooth: ilk period toplamı, sonra smooth ─────────────
    smooth_tr = np.full(n, np.nan, dtype=np.float64)
    smooth_pdm = np.full(n, np.nan, dtype=np.float64)
    smooth_mdm = np.full(n, np.nan, dtype=np.float64)

    # Seed: index=period  (tr[1..period], dm[1..period] toplamı)
    smooth_tr[period] = np.sum(tr[1 : period + 1])
    smooth_pdm[period] = np.sum(plus_dm[1 : period + 1])
    smooth_mdm[period] = np.sum(minus_dm[1 : period + 1])

    for i in range(period + 1, n):
        smooth_tr[i] = smooth_tr[i - 1] - smooth_tr[i - 1] / period + tr[i]
        smooth_pdm[i] = smooth_pdm[i - 1] - smooth_pdm[i - 1] / period + plus_dm[i]
        smooth_mdm[i] = smooth_mdm[i - 1] - smooth_mdm[i - 1] / period + minus_dm[i]

    # ── +DI / -DI ────────────────────────────────────────────────────
    plus_di = np.full(n, np.nan, dtype=np.float64)
    minus_di = np.full(n, np.nan, dtype=np.float64)
    dx = np.full(n, np.nan, dtype=np.float64)

    for i in range(period, n):
        if smooth_tr[i] and smooth_tr[i] != 0:
            plus_di[i] = 100.0 * smooth_pdm[i] / smooth_tr[i]
            minus_di[i] = 100.0 * smooth_mdm[i] / smooth_tr[i]
        else:
            plus_di[i] = 0.0
            minus_di[i] = 0.0

        di_sum = plus_di[i] + minus_di[i]
        if di_sum != 0:
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum
        else:
            dx[i] = 0.0

    # ── ADX = Wilder smooth(DX) ──────────────────────────────────────
    # İlk ADX = DX[period..2*period-1] ortalaması
    adx_start = 2 * period
    if adx_start < n:
        out[adx_start] = np.nanmean(dx[period : adx_start + 1])
        for i in range(adx_start + 1, n):
            out[i] = (out[i - 1] * (period - 1) + dx[i]) / period

    return out


# ═════════════════════════════════════════════════════════════════════
#  BOLLINGER BANDS
# ═════════════════════════════════════════════════════════════════════

def bollinger_bands(
    data: np.ndarray,
    period: int = 20,
    std: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands.

    ``Middle = SMA(period)``
    ``Upper  = Middle + std * σ``
    ``Lower  = Middle - std * σ``

    Args:
        data: Kapanış fiyat serisi (1-D).
        period: SMA periyodu (varsayılan 20).
        std: Standart sapma çarpanı (varsayılan 2.0).

    Returns:
        (upper, middle, lower) tuple'ı.
        İlk ``period-1`` eleman ``np.nan``.
    """
    data = np.asarray(data, dtype=np.float64)
    if period < 1:
        raise ValueError(f"period >= 1 olmalı, verilen: {period}")

    n = len(data)
    middle = sma(data, period)
    upper = np.full(n, np.nan, dtype=np.float64)
    lower = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        window = data[i - period + 1 : i + 1]
        # Popülasyon stddev (ddof=0) — klasik BB formülü
        s = np.std(window, ddof=0)
        upper[i] = middle[i] + std * s
        lower[i] = middle[i] - std * s

    return upper, middle, lower


# ═════════════════════════════════════════════════════════════════════
#  KELTNER CHANNEL
# ═════════════════════════════════════════════════════════════════════

def keltner_channel(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    ema_period: int = 20,
    atr_period: int = 14,
    atr_mult: float = 1.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keltner Channel — EMA bazlı volatilite kanalı.

    ``Middle = EMA(close, ema_period)``
    ``Upper  = Middle + atr_mult * ATR(atr_period)``
    ``Lower  = Middle - atr_mult * ATR(atr_period)``

    Bollinger Bands'ten farkı: standart sapma yerine ATR kullanır,
    bu nedenle aşırı fiyat hareketlerine daha az duyarlıdır.

    Args:
        high: Yüksek fiyat serisi.
        low: Düşük fiyat serisi.
        close: Kapanış fiyat serisi.
        ema_period: EMA periyodu (varsayılan 20).
        atr_period: ATR periyodu (varsayılan 14).
        atr_mult: ATR çarpanı (varsayılan 1.5).

    Returns:
        (upper, middle, lower) tuple'ı.
    """
    middle = ema(close, ema_period)
    atr_arr = atr(high, low, close, atr_period)

    upper = middle + atr_mult * atr_arr
    lower = middle - atr_mult * atr_arr

    return upper, middle, lower


# ═════════════════════════════════════════════════════════════════════
#  BB/KC SQUEEZE
# ═════════════════════════════════════════════════════════════════════

def bb_kc_squeeze(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    bb_period: int = 20,
    bb_std: float = 2.0,
    kc_ema_period: int = 20,
    kc_atr_period: int = 14,
    kc_atr_mult: float = 1.5,
) -> np.ndarray:
    """Bollinger/Keltner Squeeze tespiti.

    BB bandı KC bandının içine girdiğinde squeeze=True (sıkışma).
    Sıkışma sonrası patlama (breakout) için momentum sinyali.

    ``squeeze = (BB_upper < KC_upper) AND (BB_lower > KC_lower)``

    Args:
        high: Yüksek fiyat serisi.
        low: Düşük fiyat serisi.
        close: Kapanış fiyat serisi.
        bb_period: BB periyodu.
        bb_std: BB standart sapma çarpanı.
        kc_ema_period: KC EMA periyodu.
        kc_atr_period: KC ATR periyodu.
        kc_atr_mult: KC ATR çarpanı.

    Returns:
        Boolean dizisi (1.0=squeeze, 0.0=normal, NaN=yetersiz veri).
    """
    bb_upper, _, bb_lower = bollinger_bands(close, bb_period, bb_std)
    kc_upper, _, kc_lower = keltner_channel(
        high, low, close, kc_ema_period, kc_atr_period, kc_atr_mult,
    )

    n = len(close)
    out = np.full(n, np.nan, dtype=np.float64)

    for i in range(n):
        if (np.isnan(bb_upper[i]) or np.isnan(kc_upper[i])
                or np.isnan(bb_lower[i]) or np.isnan(kc_lower[i])):
            continue
        if bb_upper[i] < kc_upper[i] and bb_lower[i] > kc_lower[i]:
            out[i] = 1.0
        else:
            out[i] = 0.0

    return out


# ═════════════════════════════════════════════════════════════════════
#  WILLIAMS %R
# ═════════════════════════════════════════════════════════════════════

def williams_r(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Williams %R — momentum osilatörü.

    ``%R = (Highest_High - Close) / (Highest_High - Lowest_Low) * -100``

    Aralık: -100 ile 0 arası.
    -80 altı: aşırı satım (oversold).
    -20 üstü: aşırı alım (overbought).

    Args:
        high: Yüksek fiyat serisi.
        low: Düşük fiyat serisi.
        close: Kapanış fiyat serisi.
        period: Periyot (varsayılan 14).

    Returns:
        Williams %R dizisi (-100 ile 0 arası).
        İlk ``period-1`` eleman ``np.nan``.
    """
    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    close = np.asarray(close, dtype=np.float64)
    if period < 1:
        raise ValueError(f"period >= 1 olmalı, verilen: {period}")

    n = len(high)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period:
        return out

    for i in range(period - 1, n):
        hh = np.max(high[i - period + 1 : i + 1])
        ll = np.min(low[i - period + 1 : i + 1])
        hl_range = hh - ll
        if hl_range > 0:
            out[i] = (hh - close[i]) / hl_range * -100.0
        else:
            out[i] = 0.0

    return out


# ═════════════════════════════════════════════════════════════════════
#  NORMALIZED ATR (NATR)
# ═════════════════════════════════════════════════════════════════════

def normalized_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Normalized ATR — fiyat seviyesinden bağımsız volatilite ölçüsü.

    ``NATR = ATR / Close * 100``

    Farklı fiyat seviyelerindeki kontratları karşılaştırmak için kullanılır.
    F_THYAO (yüksek fiyat) vs F_KONTR (düşük fiyat) ATR değerleri
    ham halde karşılaştırılamaz, NATR ile karşılaştırılabilir.

    Args:
        high: Yüksek fiyat serisi.
        low: Düşük fiyat serisi.
        close: Kapanış fiyat serisi.
        period: ATR periyodu (varsayılan 14).

    Returns:
        NATR dizisi (yüzde cinsinden).
    """
    atr_arr = atr(high, low, close, period)
    close = np.asarray(close, dtype=np.float64)

    out = np.full(len(close), np.nan, dtype=np.float64)
    for i in range(len(close)):
        if not np.isnan(atr_arr[i]) and close[i] > 0:
            out[i] = atr_arr[i] / close[i] * 100.0

    return out


# ═════════════════════════════════════════════════════════════════════
#  ADX SLOPE
# ═════════════════════════════════════════════════════════════════════

def adx_slope(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    adx_period: int = 14,
    slope_bars: int = 3,
) -> np.ndarray:
    """ADX Slope — trend güçleniyor mu zayıflıyor mu.

    Son ``slope_bars`` bar'daki ADX değişiminin ortalaması.
    Pozitif = trend güçleniyor, negatif = trend zayıflıyor.

    Args:
        high: Yüksek fiyat serisi.
        low: Düşük fiyat serisi.
        close: Kapanış fiyat serisi.
        adx_period: ADX periyodu (varsayılan 14).
        slope_bars: Eğim hesaplama bar sayısı (varsayılan 3).

    Returns:
        ADX slope dizisi (bar başına ADX değişimi).
    """
    adx_arr = adx(high, low, close, adx_period)
    n = len(adx_arr)
    out = np.full(n, np.nan, dtype=np.float64)

    for i in range(slope_bars, n):
        vals = adx_arr[i - slope_bars : i + 1]
        valid = vals[~np.isnan(vals)]
        if len(valid) >= 2:
            out[i] = (valid[-1] - valid[0]) / len(valid)

    return out


# ═════════════════════════════════════════════════════════════════════
#  HURST EXPONENT
# ═════════════════════════════════════════════════════════════════════

def hurst_exponent(
    data: np.ndarray,
    max_lag: int = 20,
) -> float:
    """Hurst Exponent — zaman serisinin doğası.

    R/S (Rescaled Range) analizi ile hesaplanır.

    ``H > 0.5`` → trend (persistent — momentum stratejileri uygun)
    ``H ≈ 0.5`` → random walk (tahmin edilemez)
    ``H < 0.5`` → mean-reverting (ortalamaya dönüş stratejileri uygun)

    Args:
        data: Fiyat serisi (1-D). En az ``max_lag + 10`` eleman.
        max_lag: Maksimum lag (varsayılan 20).

    Returns:
        Hurst exponenti (float). Veri yetersizse NaN.
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[~np.isnan(data)]

    if len(data) < max_lag + 10:
        return float("nan")

    lags = range(2, max_lag + 1)
    rs_values = []

    for lag in lags:
        # Alt pencere sayısı
        n_windows = len(data) // lag
        if n_windows < 1:
            continue

        rs_list = []
        for w in range(n_windows):
            window = data[w * lag : (w + 1) * lag]
            mean_val = np.mean(window)
            deviations = window - mean_val
            cumulative = np.cumsum(deviations)
            r = np.max(cumulative) - np.min(cumulative)
            s = np.std(window, ddof=1)
            if s > 0:
                rs_list.append(r / s)

        if rs_list:
            rs_values.append((lag, np.mean(rs_list)))

    if len(rs_values) < 3:
        return float("nan")

    # Log-log regresyon: log(R/S) = H * log(n) + c
    log_lags = np.array([np.log(v[0]) for v in rs_values])
    log_rs = np.array([np.log(v[1]) for v in rs_values])

    # En küçük kareler ile eğim = Hurst exponenti
    n_pts = len(log_lags)
    sum_x = np.sum(log_lags)
    sum_y = np.sum(log_rs)
    sum_xy = np.sum(log_lags * log_rs)
    sum_x2 = np.sum(log_lags ** 2)

    denom = n_pts * sum_x2 - sum_x ** 2
    if denom == 0:
        return float("nan")

    hurst = (n_pts * sum_xy - sum_x * sum_y) / denom
    return float(hurst)


# ═════════════════════════════════════════════════════════════════════
#  DataFrame WRAPPER
# ═════════════════════════════════════════════════════════════════════

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Tüm indikatörleri hesapla ve DataFrame'e ekle.

    ``df`` sütunları: open, high, low, close (minimum).
    Eklenen sütunlar:
        ema_9, ema_21, sma_20, rsi_14,
        macd, macd_signal, macd_hist,
        adx_14, bb_upper, bb_middle, bb_lower, atr_14

    Args:
        df: OHLCV DataFrame.

    Returns:
        İndikatörler eklenmiş DataFrame (kopyası).
    """
    df = df.copy()
    c = df["close"].values
    h = df["high"].values
    l = df["low"].values

    df["ema_9"] = ema(c, 9)
    df["ema_21"] = ema(c, 21)
    df["sma_20"] = sma(c, 20)
    df["rsi_14"] = rsi(c, 14)

    macd_line, signal_line, histogram = macd(c)
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = histogram

    df["adx_14"] = adx(h, l, c, 14)

    upper, middle, lower = bollinger_bands(c, 20, 2.0)
    df["bb_upper"] = upper
    df["bb_middle"] = middle
    df["bb_lower"] = lower

    df["atr_14"] = atr(h, l, c, 14)

    return df
