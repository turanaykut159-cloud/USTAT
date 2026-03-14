"""Teknik indikatörler — saf NumPy implementasyonu.

TA-Lib bağımlılığı olmadan, yalnızca numpy kullanarak
EMA, SMA, RSI, MACD, ADX, Bollinger Bands, ATR,
Keltner Channel, Williams %R, BB/KC Squeeze,
VWAP, Ichimoku Cloud, KAMA ve Multi-Divergence hesaplar.

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
#  RATE OF CHANGE (ROC) — Saf momentum (EMA bağımsız)
# ═════════════════════════════════════════════════════════════════════

def roc(data: np.ndarray, period: int = 12) -> np.ndarray:
    """Rate of Change — yüzdesel fiyat değişimi.

    ``ROC = (close - close[n-period]) / close[n-period] * 100``

    EMA'dan bağımsız, saf momentum ölçüsü. Pozitif = yükseliş momentumu,
    negatif = düşüş momentumu.

    Args:
        data: Kapanış fiyat serisi (1-D).
        period: Geriye bakış periyodu (varsayılan 12).

    Returns:
        ROC dizisi (%).  İlk ``period`` eleman ``np.nan``.
    """
    data = np.asarray(data, dtype=np.float64)
    n = len(data)
    out = np.full(n, np.nan, dtype=np.float64)
    if n <= period:
        return out

    for i in range(period, n):
        if data[i - period] != 0:
            out[i] = (data[i] - data[i - period]) / data[i - period] * 100.0
        else:
            out[i] = 0.0

    return out


# ═════════════════════════════════════════════════════════════════════
#  STOCHASTIC RSI — Hızlı momentum osilatörü (RSI'dan bağımsız tepki)
# ═════════════════════════════════════════════════════════════════════

def stochastic_rsi(
    data: np.ndarray,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Stochastic RSI — RSI'ın stokastik normalizasyonu.

    ``StochRSI = (RSI - RSI_min) / (RSI_max - RSI_min)``
    RSI'dan daha hızlı tepki verir (0-100 aralığında tam salınım).
    RSI 30-70 arasında yatay seyrederken StochRSI hâlâ sinyal üretir.

    Args:
        data: Kapanış fiyat serisi.
        rsi_period: RSI periyodu.
        stoch_period: Stokastik pencere.
        k_smooth: %K düzleştirme.
        d_smooth: %D düzleştirme (sinyal hattı).

    Returns:
        (%K, %D) tuple'ı.  0-100 aralığında.
    """
    data = np.asarray(data, dtype=np.float64)
    n = len(data)

    k_out = np.full(n, np.nan, dtype=np.float64)
    d_out = np.full(n, np.nan, dtype=np.float64)

    rsi_arr = rsi(data, rsi_period)

    # StochRSI hesapla
    stoch_raw = np.full(n, np.nan, dtype=np.float64)
    for i in range(rsi_period + stoch_period, n):
        window = rsi_arr[i - stoch_period + 1: i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) < 2:
            continue
        rsi_min = np.min(valid)
        rsi_max = np.max(valid)
        rng = rsi_max - rsi_min
        if rng > 0:
            stoch_raw[i] = (rsi_arr[i] - rsi_min) / rng * 100.0
        else:
            stoch_raw[i] = 50.0

    # %K = SMA(stoch_raw, k_smooth)
    k_out = sma(stoch_raw, k_smooth) if k_smooth > 1 else stoch_raw.copy()
    # %D = SMA(%K, d_smooth)
    d_out = sma(k_out, d_smooth) if d_smooth > 1 else k_out.copy()

    return k_out, d_out


# ═════════════════════════════════════════════════════════════════════
#  OBV — On Balance Volume (akıllı para akışı)
# ═════════════════════════════════════════════════════════════════════

def obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """On Balance Volume — kümülatif hacim akışı.

    Fiyat yükseldiğinde hacmi ekler, düştüğünde çıkarır.
    OBV yükselirken fiyat düşüyorsa = birikim (akıllı para alıyor).
    OBV düşerken fiyat yükseliyorsa = dağıtım (akıllı para satıyor).

    Args:
        close: Kapanış fiyat serisi.
        volume: Hacim serisi.

    Returns:
        OBV dizisi.
    """
    close = np.asarray(close, dtype=np.float64)
    volume = np.asarray(volume, dtype=np.float64)
    n = len(close)
    out = np.zeros(n, dtype=np.float64)
    if n == 0:
        return out

    out[0] = volume[0]
    for i in range(1, n):
        if np.isnan(close[i]) or np.isnan(close[i - 1]) or np.isnan(volume[i]):
            out[i] = out[i - 1]
        elif close[i] > close[i - 1]:
            out[i] = out[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            out[i] = out[i - 1] - volume[i]
        else:
            out[i] = out[i - 1]

    return out


def obv_divergence(
    close: np.ndarray,
    volume: np.ndarray,
    lookback: int = 20,
) -> np.ndarray:
    """OBV ile fiyat arasındaki divergence tespiti.

    Pozitif divergence: Fiyat düşerken OBV yükseliyor (boğa sinyali).
    Negatif divergence: Fiyat yükselirken OBV düşüyor (ayı sinyali).

    Returns:
        Divergence skoru dizisi. +1.0=boğa div, -1.0=ayı div, 0=yok.
    """
    close = np.asarray(close, dtype=np.float64)
    n = len(close)
    out = np.full(n, 0.0, dtype=np.float64)

    obv_arr = obv(close, volume)

    if n < lookback + 1:
        return out

    for i in range(lookback, n):
        price_change = close[i] - close[i - lookback]
        obv_change = obv_arr[i] - obv_arr[i - lookback]

        # Normalize
        price_pct = price_change / close[i - lookback] if close[i - lookback] != 0 else 0
        obv_range = np.max(obv_arr[i - lookback:i + 1]) - np.min(obv_arr[i - lookback:i + 1])
        obv_pct = obv_change / obv_range if obv_range > 0 else 0

        # Divergence: yönler zıtsa
        if price_pct < -0.005 and obv_pct > 0.1:
            out[i] = min(abs(obv_pct), 1.0)   # Bullish divergence
        elif price_pct > 0.005 and obv_pct < -0.1:
            out[i] = -min(abs(obv_pct), 1.0)  # Bearish divergence

    return out


# ═════════════════════════════════════════════════════════════════════
#  VOLUME MOMENTUM — Hacim-ağırlıklı momentum
# ═════════════════════════════════════════════════════════════════════

def volume_momentum(
    close: np.ndarray,
    volume: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Volume-Weighted Momentum — hacim katılımıyla ağırlıklandırılmış momentum.

    Normal ROC yüksek hacimli hareketlere extra ağırlık vermez.
    Bu indikatör, yüksek hacimli fiyat hareketlerini daha güçlü sayar.

    ``VM = Σ(price_change[i] * volume[i]) / Σ(volume[i])``

    Args:
        close: Kapanış fiyat serisi.
        volume: Hacim serisi.
        period: Pencere uzunluğu.

    Returns:
        Volume momentum dizisi. Pozitif = alım baskısı, negatif = satış baskısı.
    """
    close = np.asarray(close, dtype=np.float64)
    volume = np.asarray(volume, dtype=np.float64)
    n = len(close)
    out = np.full(n, np.nan, dtype=np.float64)

    if n < period + 1:
        return out

    for i in range(period, n):
        changes = np.diff(close[i - period: i + 1])
        vols = volume[i - period + 1: i + 1]

        # NaN kontrolü
        valid_mask = ~(np.isnan(changes) | np.isnan(vols))
        if np.sum(valid_mask) == 0:
            continue

        vol_sum = np.sum(vols[valid_mask])
        if vol_sum > 0:
            out[i] = np.sum(changes[valid_mask] * vols[valid_mask]) / vol_sum
        else:
            out[i] = 0.0

    return out


# ═════════════════════════════════════════════════════════════════════
#  COMPRESSION RATIO — Sıkışma tespiti
# ═════════════════════════════════════════════════════════════════════

def compression_ratio(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    short_period: int = 5,
    long_period: int = 20,
) -> np.ndarray:
    """Fiyat sıkışma oranı — yakın zamanlı range / uzun vadeli range.

    Oran < 0.5 ise ciddi sıkışma var → patlama yakın.
    Oran > 1.0 ise genişleme devam ediyor.

    BB/KC squeeze'den farklı olarak, saf fiyat range'ini ölçer.
    Daha basit, daha güvenilir.

    Args:
        high, low, close: OHLC verileri.
        short_period: Kısa pencere (varsayılan 5 bar).
        long_period: Uzun pencere (varsayılan 20 bar).

    Returns:
        Compression ratio dizisi. < 0.5 = sıkışma, > 1.0 = genişleme.
    """
    n = len(close)
    out = np.full(n, np.nan, dtype=np.float64)

    if n < long_period:
        return out

    for i in range(long_period - 1, n):
        short_start = max(i - short_period + 1, 0)
        short_range = np.max(high[short_start:i + 1]) - np.min(low[short_start:i + 1])
        long_start = i - long_period + 1
        long_range = np.max(high[long_start:i + 1]) - np.min(low[long_start:i + 1])

        if long_range > 0:
            out[i] = short_range / long_range
        else:
            out[i] = 1.0

    return out


# ═════════════════════════════════════════════════════════════════════
#  VWAP (Volume Weighted Average Price)
# ═════════════════════════════════════════════════════════════════════

def vwap(high: np.ndarray, low: np.ndarray, close: np.ndarray,
         volume: np.ndarray, session_bars: int = 78) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Seans bazlı VWAP + üst/alt bantlar (±1 std sapma).

    Her ``session_bars`` barda (M15 = 78 bar ≈ 1 gün) sıfırlanır.

    Args:
        high, low, close: Fiyat serileri.
        volume: Hacim serisi.
        session_bars: Bir seans kaç bar (varsayılan M15 = 78).

    Returns:
        (vwap_line, upper_band, lower_band) — her biri np.ndarray.
    """
    n = len(close)
    typical = (high + low + close) / 3.0
    vwap_line = np.full(n, np.nan, dtype=np.float64)
    upper_band = np.full(n, np.nan, dtype=np.float64)
    lower_band = np.full(n, np.nan, dtype=np.float64)

    for i in range(n):
        session_start = (i // session_bars) * session_bars
        seg_tp = typical[session_start:i + 1]
        seg_vol = volume[session_start:i + 1]
        total_vol = np.sum(seg_vol)
        if total_vol > 0:
            vw = np.sum(seg_tp * seg_vol) / total_vol
            vwap_line[i] = vw
            variance = np.sum(seg_vol * (seg_tp - vw) ** 2) / total_vol
            std = np.sqrt(variance)
            upper_band[i] = vw + std
            lower_band[i] = vw - std

    return vwap_line, upper_band, lower_band


def vwap_distance(close: np.ndarray, vwap_line: np.ndarray,
                  atr_vals: np.ndarray) -> np.ndarray:
    """VWAP'tan ATR-normalize uzaklık. >0 = üstünde, <0 = altında.

    Args:
        close: Kapanış fiyatları.
        vwap_line: VWAP serisi.
        atr_vals: ATR serisi (normalize etmek için).

    Returns:
        Normalize uzaklık dizisi.
    """
    n = len(close)
    out = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        if not (np.isnan(vwap_line[i]) or np.isnan(atr_vals[i]) or atr_vals[i] == 0):
            out[i] = (close[i] - vwap_line[i]) / atr_vals[i]
    return out


# ═════════════════════════════════════════════════════════════════════
#  ICHIMOKU CLOUD
# ═════════════════════════════════════════════════════════════════════

def ichimoku(high: np.ndarray, low: np.ndarray, close: np.ndarray,
             tenkan: int = 9, kijun: int = 26, senkou_b: int = 52
             ) -> dict[str, np.ndarray]:
    """Ichimoku Kinko Hyo — 5 bileşen.

    Args:
        high, low, close: Fiyat serileri.
        tenkan: Tenkan-sen periyodu (varsayılan 9).
        kijun: Kijun-sen periyodu (varsayılan 26).
        senkou_b: Senkou Span B periyodu (varsayılan 52).

    Returns:
        dict: tenkan_sen, kijun_sen, senkou_a, senkou_b, chikou_span
              (senkou değerleri ``kijun`` bar ileri kaydırılmıştır).
    """
    n = len(close)

    def _midline(h: np.ndarray, l: np.ndarray, period: int) -> np.ndarray:
        out = np.full(n, np.nan, dtype=np.float64)
        for i in range(period - 1, n):
            out[i] = (np.max(h[i - period + 1:i + 1]) + np.min(l[i - period + 1:i + 1])) / 2.0
        return out

    tenkan_sen = _midline(high, low, tenkan)
    kijun_sen = _midline(high, low, kijun)
    senkou_b_line = _midline(high, low, senkou_b)

    # Senkou A = (Tenkan + Kijun) / 2 — kijun bar ileri
    senkou_a = np.full(n, np.nan, dtype=np.float64)
    senkou_b_shifted = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        if not (np.isnan(tenkan_sen[i]) or np.isnan(kijun_sen[i])):
            target = i + kijun
            if target < n:
                senkou_a[target] = (tenkan_sen[i] + kijun_sen[i]) / 2.0
        if not np.isnan(senkou_b_line[i]):
            target = i + kijun
            if target < n:
                senkou_b_shifted[target] = senkou_b_line[i]

    # Chikou = close kaydırılmış kijun bar geri
    chikou = np.full(n, np.nan, dtype=np.float64)
    for i in range(kijun, n):
        chikou[i - kijun] = close[i]

    return {
        "tenkan_sen": tenkan_sen,
        "kijun_sen": kijun_sen,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b_shifted,
        "chikou_span": chikou,
    }


def ichimoku_signal(close: np.ndarray, ichi: dict[str, np.ndarray]) -> np.ndarray:
    """Ichimoku sinyal puanı: -100 ile +100 arası.

    Pozitif = bullish, negatif = bearish.

    5 alt sinyal (her biri ±20):
      1. Tenkan/Kijun cross
      2. Fiyat vs Kumo (bulut) pozisyonu
      3. Kumo rengi (Senkou A vs B)
      4. Chikou vs fiyat
      5. Kumo kalınlığı (güç göstergesi)
    """
    n = len(close)
    out = np.full(n, np.nan, dtype=np.float64)

    ts = ichi["tenkan_sen"]
    ks = ichi["kijun_sen"]
    sa = ichi["senkou_a"]
    sb = ichi["senkou_b"]
    ch = ichi["chikou_span"]

    for i in range(1, n):
        score = 0.0
        valid = True

        # NaN kontrol
        for arr in [ts, ks, sa, sb]:
            if np.isnan(arr[i]) or np.isnan(arr[i - 1]):
                valid = False
                break
        if not valid:
            continue

        # 1. TK Cross: Tenkan > Kijun = bullish
        if ts[i] > ks[i]:
            score += 20.0
        elif ts[i] < ks[i]:
            score -= 20.0

        # 2. Fiyat vs Kumo
        kumo_top = max(sa[i], sb[i])
        kumo_bot = min(sa[i], sb[i])
        if close[i] > kumo_top:
            score += 20.0
        elif close[i] < kumo_bot:
            score -= 20.0
        # else: kumo içinde = 0

        # 3. Kumo rengi
        if sa[i] > sb[i]:
            score += 20.0
        elif sa[i] < sb[i]:
            score -= 20.0

        # 4. Chikou vs fiyat (26 bar önceki fiyat)
        if not np.isnan(ch[i]):
            if i >= 26 and not np.isnan(close[i]):
                # Chikou değeri aslında 26 bar öncesine yerleştirilmiş
                # şimdiki close ile karşılaştır
                if ch[i] > close[i]:
                    score += 20.0
                elif ch[i] < close[i]:
                    score -= 20.0

        # 5. Kumo kalınlığı (göreli güç)
        kumo_thick = abs(sa[i] - sb[i])
        price_range = close[i] * 0.001  # %0.1 referans
        if kumo_thick > price_range * 3:
            # Kalın kumo = güçlü sinyal yönünde
            if score > 0:
                score += 20.0
            elif score < 0:
                score -= 20.0

        out[i] = np.clip(score, -100.0, 100.0)

    return out


# ═════════════════════════════════════════════════════════════════════
#  KAMA (Kaufman Adaptive Moving Average)
# ═════════════════════════════════════════════════════════════════════

def kama(close: np.ndarray, er_period: int = 10,
         fast_sc: int = 2, slow_sc: int = 30) -> np.ndarray:
    """Kaufman Adaptive Moving Average.

    Volatilite yüksekken yavaşlar (gürültü filtreler),
    trend netleşince hızlanır (sinyale hızlı tepki verir).

    Args:
        close: Kapanış fiyatları.
        er_period: Efficiency Ratio penceresi.
        fast_sc: Hızlı smoothing constant periyodu.
        slow_sc: Yavaş smoothing constant periyodu.

    Returns:
        KAMA dizisi.
    """
    n = len(close)
    out = np.full(n, np.nan, dtype=np.float64)

    if n < er_period + 1:
        return out

    fast_alpha = 2.0 / (fast_sc + 1.0)
    slow_alpha = 2.0 / (slow_sc + 1.0)

    out[er_period] = close[er_period]

    for i in range(er_period + 1, n):
        direction = abs(close[i] - close[i - er_period])
        volatility = np.sum(np.abs(np.diff(close[i - er_period:i + 1])))

        if volatility == 0:
            er = 0.0
        else:
            er = direction / volatility

        sc = (er * (fast_alpha - slow_alpha) + slow_alpha) ** 2
        out[i] = out[i - 1] + sc * (close[i] - out[i - 1])

    return out


def kama_slope(kama_vals: np.ndarray, lookback: int = 5,
               atr_vals: np.ndarray | None = None) -> np.ndarray:
    """KAMA eğim değişimi (ATR-normalize).

    Pozitif = yukarı trend, negatif = aşağı trend.
    Büyük mutlak değer = güçlü trend.

    Args:
        kama_vals: KAMA serisi.
        lookback: Eğim penceresi.
        atr_vals: ATR serisi (normalize için). None ise ham fark döner.

    Returns:
        Normalize eğim dizisi.
    """
    n = len(kama_vals)
    out = np.full(n, np.nan, dtype=np.float64)
    for i in range(lookback, n):
        if np.isnan(kama_vals[i]) or np.isnan(kama_vals[i - lookback]):
            continue
        diff = kama_vals[i] - kama_vals[i - lookback]
        if atr_vals is not None and not np.isnan(atr_vals[i]) and atr_vals[i] > 0:
            out[i] = diff / atr_vals[i]
        else:
            out[i] = diff
    return out


# ═════════════════════════════════════════════════════════════════════
#  MULTI-DIVERGENCE DETECTOR
# ═════════════════════════════════════════════════════════════════════

def detect_divergence(price: np.ndarray, indicator: np.ndarray,
                      lookback: int = 30, swing_order: int = 5
                      ) -> list[dict]:
    """Fiyat-indikatör diverjans tespiti.

    Hem regular hem hidden divergence arar.

    Args:
        price: Fiyat serisi (genelde close).
        indicator: İndikatör serisi (RSI, MACD hist, OBV, vb.).
        lookback: Geriye bakma penceresi.
        swing_order: Swing noktası tespiti için minimum bar sayısı.

    Returns:
        Liste: [{"type": "bullish"/"bearish", "kind": "regular"/"hidden",
                 "strength": 0-1, "bar_index": int}, ...]
    """
    n = len(price)
    divs: list[dict] = []

    if n < lookback + swing_order * 2:
        return divs

    # Swing noktalarını bul
    swing_highs: list[int] = []
    swing_lows: list[int] = []

    start = max(0, n - lookback - swing_order)
    for i in range(start + swing_order, n - swing_order):
        if np.isnan(price[i]) or np.isnan(indicator[i]):
            continue
        # Swing high
        is_high = True
        for j in range(1, swing_order + 1):
            if price[i] <= price[i - j] or price[i] <= price[i + j]:
                is_high = False
                break
        if is_high:
            swing_highs.append(i)

        # Swing low
        is_low = True
        for j in range(1, swing_order + 1):
            if price[i] >= price[i - j] or price[i] >= price[i + j]:
                is_low = False
                break
        if is_low:
            swing_lows.append(i)

    # Regular Bullish: Fiyat düşük dip, indikatör yüksek dip
    for j in range(1, len(swing_lows)):
        i1, i2 = swing_lows[j - 1], swing_lows[j]
        if np.isnan(indicator[i1]) or np.isnan(indicator[i2]):
            continue
        if price[i2] < price[i1] and indicator[i2] > indicator[i1]:
            price_drop = (price[i1] - price[i2]) / price[i1] if price[i1] > 0 else 0
            ind_rise = (indicator[i2] - indicator[i1]) / (abs(indicator[i1]) + 1e-10)
            strength = min(1.0, (price_drop + abs(ind_rise)) * 5)
            divs.append({"type": "bullish", "kind": "regular",
                         "strength": strength, "bar_index": i2})

    # Regular Bearish: Fiyat yüksek tepe, indikatör düşük tepe
    for j in range(1, len(swing_highs)):
        i1, i2 = swing_highs[j - 1], swing_highs[j]
        if np.isnan(indicator[i1]) or np.isnan(indicator[i2]):
            continue
        if price[i2] > price[i1] and indicator[i2] < indicator[i1]:
            price_rise = (price[i2] - price[i1]) / price[i1] if price[i1] > 0 else 0
            ind_drop = (indicator[i1] - indicator[i2]) / (abs(indicator[i1]) + 1e-10)
            strength = min(1.0, (price_rise + abs(ind_drop)) * 5)
            divs.append({"type": "bearish", "kind": "regular",
                         "strength": strength, "bar_index": i2})

    # Hidden Bullish: Fiyat yüksek dip, indikatör düşük dip (trend devamı)
    for j in range(1, len(swing_lows)):
        i1, i2 = swing_lows[j - 1], swing_lows[j]
        if np.isnan(indicator[i1]) or np.isnan(indicator[i2]):
            continue
        if price[i2] > price[i1] and indicator[i2] < indicator[i1]:
            strength = min(1.0, abs(indicator[i1] - indicator[i2]) / (abs(indicator[i1]) + 1e-10) * 3)
            divs.append({"type": "bullish", "kind": "hidden",
                         "strength": strength * 0.8, "bar_index": i2})

    # Hidden Bearish: Fiyat düşük tepe, indikatör yüksek tepe
    for j in range(1, len(swing_highs)):
        i1, i2 = swing_highs[j - 1], swing_highs[j]
        if np.isnan(indicator[i1]) or np.isnan(indicator[i2]):
            continue
        if price[i2] < price[i1] and indicator[i2] > indicator[i1]:
            strength = min(1.0, abs(indicator[i2] - indicator[i1]) / (abs(indicator[i1]) + 1e-10) * 3)
            divs.append({"type": "bearish", "kind": "hidden",
                         "strength": strength * 0.8, "bar_index": i2})

    return divs


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
