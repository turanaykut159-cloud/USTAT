"""Teknik indikatörler — saf NumPy implementasyonu.

TA-Lib bağımlılığı olmadan, yalnızca numpy kullanarak
EMA, SMA, RSI, MACD, ADX, Bollinger Bands ve ATR hesaplar.

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
