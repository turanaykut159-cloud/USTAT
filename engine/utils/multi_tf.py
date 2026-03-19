"""Multi-Timeframe analizi — Çoklu zaman dilimi uyum modülü (v14.2 FAZ 2).

3-katmanlı zaman dilimi hiyerarşisi:
    H1  → Büyük resim (trend yönü, ana S/R, momentum)
    M15 → Sinyal (mevcut strateji üretimi — ogul.py tarafından yönetilir)
    M5  → Hassas giriş zamanlama (giriş tetikleyici, mikro yapı)

Her katmanın bağımsız puanı var. Toplam TF skoru sinyal gücüne eklenir.

OĞUL'un "bilinçli işlemci" dönüşümünün ikinci fazı.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from engine.utils.indicators import (
    atr as calc_atr,
    ema,
    rsi as calc_rsi,
    adx as calc_adx,
    macd as calc_macd,
)
from engine.utils.price_action import (
    analyze_trend_structure,
    find_support_resistance,
    trend_supports_direction,
)


# ═════════════════════════════════════════════════════════════════════
#  VERİ YAPILARI
# ═════════════════════════════════════════════════════════════════════

@dataclass
class TFLayerResult:
    """Tek zaman dilimi analiz sonucu."""
    timeframe: str             # "H1", "M15", "M5"
    trend_direction: str       # "up" | "down" | "range"
    trend_strength: float      # 0.0-1.0
    momentum_aligned: bool     # EMA + MACD yönünü destekliyor mu
    ema_fast: float = 0.0      # Hızlı EMA değeri
    ema_slow: float = 0.0      # Yavaş EMA değeri
    rsi: float = 50.0          # RSI değeri
    adx: float = 0.0           # ADX değeri
    atr: float = 0.0           # ATR değeri
    score: float = 0.0         # 0-100 katman skoru

@dataclass
class MultiTFResult:
    """Çoklu zaman dilimi analiz sonucu."""
    h1: TFLayerResult | None = None
    m15: TFLayerResult | None = None
    m5: TFLayerResult | None = None
    total_score: float = 0.0       # 0-100 toplam TF uyum skoru
    alignment: str = "none"        # "strong" | "moderate" | "weak" | "conflict" | "none"
    can_enter: bool = False        # Yeterli uyum var mı
    entry_timing: str = "wait"     # "now" | "pullback" | "wait"
    details: dict = field(default_factory=dict)


# ═════════════════════════════════════════════════════════════════════
#  SABİTLER
# ═════════════════════════════════════════════════════════════════════

# Minimum bar sayıları
MIN_BARS_H1:  int = 60
MIN_BARS_M15: int = 60
MIN_BARS_M5:  int = 40

# EMA periyotları
EMA_FAST:  int = 20
EMA_SLOW:  int = 50

# ADX eşikleri
ADX_STRONG_TREND: float = 30.0
ADX_WEAK: float = 20.0

# Katman ağırlıkları (toplam 100)
W_H1:  float = 40.0    # Büyük resim en önemli
W_M15: float = 35.0    # Sinyal katmanı
W_M5:  float = 25.0    # Hassas giriş

# Minimum toplam skor
MIN_TF_SCORE: float = 50.0

# M5 giriş zamanlama
M5_PULLBACK_RSI_LOW:  float = 35.0   # RSI < 35 = pullback fırsatı (BUY)
M5_PULLBACK_RSI_HIGH: float = 65.0   # RSI > 65 = pullback fırsatı (SELL)
M5_ENTRY_RSI_RANGE:   tuple = (40.0, 60.0)  # RSI 40-60 arası = momentum başlangıcı


# ═════════════════════════════════════════════════════════════════════
#  KATMAN ANALİZİ
# ═════════════════════════════════════════════════════════════════════

def _analyze_layer(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    timeframe: str,
    direction: str,
) -> TFLayerResult:
    """Tek zaman dilimi katmanını analiz et.

    Args:
        high, low, close, volume: OHLCV verileri.
        timeframe: Zaman dilimi etiketi.
        direction: "BUY" veya "SELL".

    Returns:
        TFLayerResult nesnesi.
    """
    result = TFLayerResult(
        timeframe=timeframe,
        trend_direction="range",
        trend_strength=0.0,
        momentum_aligned=False,
    )

    n = len(close)
    if n < 30:
        return result

    # ── Göstergeler ─────────────────────────────────────────────
    ema_fast_arr = ema(close, EMA_FAST)
    ema_slow_arr = ema(close, EMA_SLOW)
    atr_arr = calc_atr(high, low, close, 14)
    rsi_arr = calc_rsi(close, 14)
    adx_arr = calc_adx(high, low, close, 14)
    _, _, macd_hist = calc_macd(close)

    # Son geçerli değerler
    def _last(arr):
        valid = arr[~np.isnan(arr)]
        return float(valid[-1]) if len(valid) > 0 else None

    ef = _last(ema_fast_arr)
    es = _last(ema_slow_arr)
    atr_val = _last(atr_arr)
    rsi_val = _last(rsi_arr)
    adx_val = _last(adx_arr)
    hist_val = _last(macd_hist)

    if any(v is None for v in (ef, es, atr_val)):
        return result

    result.ema_fast = ef
    result.ema_slow = es
    result.atr = atr_val
    result.rsi = rsi_val or 50.0
    result.adx = adx_val or 0.0

    # ── Trend yapısı ────────────────────────────────────────────
    trend = analyze_trend_structure(high, low, close)
    result.trend_direction = trend.direction
    result.trend_strength = trend.trend_strength

    # ── Momentum uyumu ──────────────────────────────────────────
    ema_aligned = (ef > es) if direction == "BUY" else (ef < es)
    macd_aligned = (hist_val and hist_val > 0) if direction == "BUY" else (hist_val and hist_val < 0)
    result.momentum_aligned = ema_aligned and bool(macd_aligned)

    # ── Katman skoru (0-100) ────────────────────────────────────
    score = 0.0

    # Trend uyumu (0-40)
    trend_ok, t_str = trend_supports_direction(trend, direction)
    if trend_ok:
        score += t_str * 40.0
    else:
        score -= t_str * 20.0  # Ters trend ceza

    # EMA uyumu (0-25)
    if ema_aligned:
        ema_gap = abs(ef - es) / (atr_val if atr_val > 0 else 1.0)
        score += min(ema_gap * 10.0, 25.0)

    # MACD uyumu (0-15)
    if macd_aligned and hist_val:
        hist_norm = abs(hist_val) / (atr_val * 0.3) if atr_val > 0 else 0
        score += min(hist_norm * 7.5, 15.0)

    # ADX gücü (0-15)
    if adx_val:
        if adx_val > ADX_STRONG_TREND:
            score += 15.0
        elif adx_val > ADX_WEAK:
            score += (adx_val - ADX_WEAK) / (ADX_STRONG_TREND - ADX_WEAK) * 15.0

    # RSI uyumu (0-5 bonus veya -5 ceza)
    if rsi_val:
        if direction == "BUY":
            if 40 < rsi_val < 65:
                score += 5.0
            elif rsi_val > 75:
                score -= 5.0  # Aşırı alım riski
        else:
            if 35 < rsi_val < 60:
                score += 5.0
            elif rsi_val < 25:
                score -= 5.0  # Aşırı satış riski

    result.score = max(min(score, 100.0), 0.0)
    return result


# ═════════════════════════════════════════════════════════════════════
#  ANA ANALİZ FONKSİYONU
# ═════════════════════════════════════════════════════════════════════

def analyze_multi_tf(
    direction: str,
    h1_data: dict | None = None,
    m15_data: dict | None = None,
    m5_data: dict | None = None,
) -> MultiTFResult:
    """Çoklu zaman dilimi analizi yap.

    Args:
        direction: "BUY" veya "SELL".
        h1_data: {"high": np.ndarray, "low": ..., "close": ..., "volume": ...} veya None.
        m15_data: Aynı format.
        m5_data: Aynı format.

    Returns:
        MultiTFResult nesnesi.
    """
    result = MultiTFResult()
    details: dict = {}

    # ── H1 Katman ──────────────────────────────────────────────
    if h1_data and len(h1_data.get("close", [])) >= MIN_BARS_H1:
        result.h1 = _analyze_layer(
            h1_data["high"], h1_data["low"],
            h1_data["close"], h1_data["volume"],
            "H1", direction,
        )
        details["h1_trend"] = result.h1.trend_direction
        details["h1_score"] = result.h1.score
        details["h1_adx"] = result.h1.adx

    # ── M15 Katman ─────────────────────────────────────────────
    if m15_data and len(m15_data.get("close", [])) >= MIN_BARS_M15:
        result.m15 = _analyze_layer(
            m15_data["high"], m15_data["low"],
            m15_data["close"], m15_data["volume"],
            "M15", direction,
        )
        details["m15_trend"] = result.m15.trend_direction
        details["m15_score"] = result.m15.score

    # ── M5 Katman ──────────────────────────────────────────────
    if m5_data and len(m5_data.get("close", [])) >= MIN_BARS_M5:
        result.m5 = _analyze_layer(
            m5_data["high"], m5_data["low"],
            m5_data["close"], m5_data["volume"],
            "M5", direction,
        )
        details["m5_trend"] = result.m5.trend_direction
        details["m5_score"] = result.m5.score
        details["m5_rsi"] = result.m5.rsi

    # ── Toplam Skor ────────────────────────────────────────────
    h1_score = result.h1.score if result.h1 else 50.0  # Veri yoksa nötr
    m15_score = result.m15.score if result.m15 else 50.0
    m5_score = result.m5.score if result.m5 else 50.0

    result.total_score = (
        h1_score * W_H1 / 100.0 +
        m15_score * W_M15 / 100.0 +
        m5_score * W_M5 / 100.0
    )

    # ── Uyum Seviyesi ──────────────────────────────────────────
    aligned_count = 0
    conflict_count = 0

    for layer in (result.h1, result.m15, result.m5):
        if layer is None:
            continue
        if layer.momentum_aligned:
            aligned_count += 1
        elif layer.trend_direction != "range":
            # Trend var ama momentum ters
            if direction == "BUY" and layer.trend_direction == "down":
                conflict_count += 1
            elif direction == "SELL" and layer.trend_direction == "up":
                conflict_count += 1

    if aligned_count >= 3:
        result.alignment = "strong"
    elif aligned_count >= 2 and conflict_count == 0:
        result.alignment = "moderate"
    elif conflict_count >= 2:
        result.alignment = "conflict"
    elif aligned_count >= 1:
        result.alignment = "weak"
    else:
        result.alignment = "none"

    details["alignment"] = result.alignment
    details["aligned_count"] = aligned_count
    details["conflict_count"] = conflict_count

    # ── Giriş Yapılabilir mi? ──────────────────────────────────
    # H1 trendi ters ise giriş yapma (büyük resim öncelikli)
    h1_blocks = False
    if result.h1 and result.h1.trend_strength > 0.5:
        trend_ok, _ = trend_supports_direction(
            type("T", (), {
                "direction": result.h1.trend_direction,
                "trend_strength": result.h1.trend_strength,
            })(),
            direction,
        )
        if not trend_ok:
            h1_blocks = True
            details["h1_blocks"] = True

    result.can_enter = (
        result.total_score >= MIN_TF_SCORE
        and result.alignment not in ("conflict", "none")
        and not h1_blocks
    )

    # ── Giriş Zamanlaması (M5 bazlı) ──────────────────────────
    if result.can_enter and result.m5:
        rsi_m5 = result.m5.rsi
        if direction == "BUY":
            if rsi_m5 < M5_PULLBACK_RSI_LOW:
                result.entry_timing = "pullback"  # Geri çekilme fırsatı
            elif M5_ENTRY_RSI_RANGE[0] <= rsi_m5 <= M5_ENTRY_RSI_RANGE[1]:
                result.entry_timing = "now"        # Momentum başlıyor
            else:
                result.entry_timing = "wait"       # Aşırı alım bölgesi
        else:
            if rsi_m5 > M5_PULLBACK_RSI_HIGH:
                result.entry_timing = "pullback"
            elif M5_ENTRY_RSI_RANGE[0] <= rsi_m5 <= M5_ENTRY_RSI_RANGE[1]:
                result.entry_timing = "now"
            else:
                result.entry_timing = "wait"
    elif result.can_enter:
        result.entry_timing = "now"  # M5 verisi yoksa direkt gir

    details["entry_timing"] = result.entry_timing
    result.details = details
    return result


# ═════════════════════════════════════════════════════════════════════
#  YARDIMCI: H1 TREND FİLTRESİ (Hızlı kontrol)
# ═════════════════════════════════════════════════════════════════════

def h1_trend_filter(
    h1_close: np.ndarray,
    h1_high: np.ndarray,
    h1_low: np.ndarray,
    direction: str,
) -> tuple[bool, str, float]:
    """H1 trend filtresi — büyük resim engeli.

    Hızlı kontrol: Sinyal yönü H1 trendiyle uyumlu mu?

    Args:
        h1_close, h1_high, h1_low: H1 OHLC verileri.
        direction: "BUY" veya "SELL".

    Returns:
        (geçer_mi, trend_yönü, trend_gücü)
    """
    if len(h1_close) < 30:
        return True, "unknown", 0.0  # Veri yoksa engelleme

    trend = analyze_trend_structure(h1_high, h1_low, h1_close)

    # Güçlü ters trend → engelle
    if trend.trend_strength > 0.6:
        if direction == "BUY" and trend.direction == "down":
            return False, trend.direction, trend.trend_strength
        if direction == "SELL" and trend.direction == "up":
            return False, trend.direction, trend.trend_strength

    return True, trend.direction, trend.trend_strength


def m5_entry_quality(
    m5_high: np.ndarray,
    m5_low: np.ndarray,
    m5_close: np.ndarray,
    direction: str,
) -> tuple[float, str]:
    """M5 giriş kalitesi — hassas zamanlama.

    Args:
        m5_high, m5_low, m5_close: M5 OHLC verileri.
        direction: "BUY" veya "SELL".

    Returns:
        (kalite_skoru 0-1, zamanlama "now"|"pullback"|"wait")
    """
    if len(m5_close) < 20:
        return 0.5, "now"

    rsi_arr = calc_rsi(m5_close, 14)
    atr_arr = calc_atr(m5_high, m5_low, m5_close, 14)
    ema_fast = ema(m5_close, 10)
    ema_slow = ema(m5_close, 30)

    valid_rsi = rsi_arr[~np.isnan(rsi_arr)]
    valid_ef = ema_fast[~np.isnan(ema_fast)]
    valid_es = ema_slow[~np.isnan(ema_slow)]
    valid_atr = atr_arr[~np.isnan(atr_arr)]

    if len(valid_rsi) == 0 or len(valid_ef) == 0 or len(valid_es) == 0:
        return 0.5, "now"

    rsi = float(valid_rsi[-1])
    ef = float(valid_ef[-1])
    es = float(valid_es[-1])
    atr_val = float(valid_atr[-1]) if len(valid_atr) > 0 else 0

    quality = 0.5
    timing = "now"

    if direction == "BUY":
        # EMA uyumu
        if ef > es:
            quality += 0.2
        # RSI: geri çekilme bölgesi ideal
        if rsi < M5_PULLBACK_RSI_LOW:
            quality += 0.2
            timing = "pullback"
        elif M5_ENTRY_RSI_RANGE[0] <= rsi <= M5_ENTRY_RSI_RANGE[1]:
            quality += 0.1
            timing = "now"
        elif rsi > 70:
            quality -= 0.2
            timing = "wait"
        # Momentum: son 3 bar kapanış yükseliyor mu
        if len(m5_close) >= 3:
            if m5_close[-1] > m5_close[-2] > m5_close[-3]:
                quality += 0.1
    else:
        if ef < es:
            quality += 0.2
        if rsi > M5_PULLBACK_RSI_HIGH:
            quality += 0.2
            timing = "pullback"
        elif M5_ENTRY_RSI_RANGE[0] <= rsi <= M5_ENTRY_RSI_RANGE[1]:
            quality += 0.1
            timing = "now"
        elif rsi < 30:
            quality -= 0.2
            timing = "wait"
        if len(m5_close) >= 3:
            if m5_close[-1] < m5_close[-2] < m5_close[-3]:
                quality += 0.1

    return max(min(quality, 1.0), 0.0), timing
