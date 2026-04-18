"""ÜSTAT Sinyal Arama Motoru — Kod Adı: ÜSTAT-SE

╔══════════════════════════════════════════════════════════════╗
║  Mimar  : Üstat                                             ║
║  Motor  : ÜSTAT Signal Engine v3.0                          ║
║  Tarih  : Mart 2026                                         ║
╚══════════════════════════════════════════════════════════════╝

Felsefe: "Piyasa yapısı ne diyor?" → "Momentum onaylıyor mu?" → "Hacim destekliyor mu?"
         → "Kurumsal akış nerede?" → "Trend adaptif mi?"

9 Bağımsız Sinyal Kaynağı:
    A) Yapı Kırılımı — Fiyat, anahtar S/R seviyesini kırıyor mu?
    B) Momentum Ateşleme — ROC + StochRSI yakınsaması
    C) Hacim İstihbaratı — OBV divergence + hacim klimaksı
    D) Sıkışma Çözülmesi — Compression ratio düşüş sonrası patlama
    E) Aşırı Uç Geri Dönüş — Multi-gösterge aşırı bölge
    F) VWAP Kurumsal — Kurumsal seviye etkileşimi + bant analizi
    G) Akıllı Diverjans — Çoklu indikatör diverjans tespiti
    H) Ichimoku Bulutu — 5 bileşenli Japon bulut sistemi
    I) Adaptif Momentum — KAMA bazlı rejim-uyumlu trend takibi

Her kaynak 0-20 puan üretir.
Minimum 3/9 kaynak uyumlu olmalı (adaptif eşik).
Final sinyal gücü = uyumlu kaynakların ağırlıklı ortalaması.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from engine.utils.indicators import (
    atr as calc_atr,
    ema,
    sma,
    rsi as calc_rsi,
    adx as calc_adx,
    macd as calc_macd,
    bollinger_bands,
    williams_r as calc_williams_r,
    roc as calc_roc,
    stochastic_rsi,
    obv as calc_obv,
    obv_divergence,
    volume_momentum,
    compression_ratio,
    # SE3 yeni indikatörler
    vwap as calc_vwap,
    vwap_distance,
    ichimoku as calc_ichimoku,
    ichimoku_signal,
    kama as calc_kama,
    kama_slope,
    detect_divergence,
)
from engine.utils.price_action import (
    find_swing_points,
    find_support_resistance,
    detect_bar_patterns,
    pattern_confirms_direction,
    analyze_trend_structure,
    trend_supports_direction,
    nearest_level,
    price_near_level,
    Level,
    BarPattern,
    TrendStructure,
)


# ═════════════════════════════════════════════════════════════════════
#  VERİ YAPILARI
# ═════════════════════════════════════════════════════════════════════

@dataclass
class SourceResult:
    """Tek sinyal kaynağının sonucu."""
    name: str           # "structure_break", "momentum_ignition", vb.
    score: float        # 0-20 puan
    direction: str      # "BUY" | "SELL" | "NEUTRAL"
    confidence: float   # 0.0-1.0
    details: dict = field(default_factory=dict)

@dataclass
class SignalVerdict:
    """Sinyal motoru nihai kararı."""
    should_trade: bool = False
    direction: str = "NEUTRAL"      # "BUY" | "SELL" | "NEUTRAL"
    strength: float = 0.0           # 0.0-1.0
    total_score: float = 0.0        # 0-100
    agreeing_sources: int = 0       # Kaç kaynak uyumlu
    sources: list[SourceResult] = field(default_factory=list)
    # Giriş detayları
    entry_price: float = 0.0
    structural_sl: float = 0.0
    structural_tp: float = 0.0
    risk_reward: float = 0.0
    # Hangi strateji tipine eşlenir
    strategy_type: str = "trend_follow"  # ogul.py StrategyType ile uyumlu
    reason: str = ""


# ═════════════════════════════════════════════════════════════════════
#  SABİTLER
# ═════════════════════════════════════════════════════════════════════

# Minimum uyumlu kaynak (yüksek volatilite)
MIN_AGREEING_SOURCES: int = 3
# Düşük volatilite rejiminde minimum uyumlu kaynak
MIN_AGREEING_SOURCES_LOW_VOL: int = 2

# Minimum toplam skor
MIN_TOTAL_SCORE: float = 45.0
# Düşük volatilite rejiminde daha yüksek skor eşiği (2 kaynak ama daha güçlü)
MIN_TOTAL_SCORE_LOW_VOL: float = 55.0

# Minimum R:R oranı
MIN_RISK_REWARD: float = 1.5

# ── v2: Rejim-bazlı eşikler ────────────────────────────────────────
# BABA rejim tespitine göre SE2 parametrelerini uyarla.
# TREND: Trend zaten BABA + strateji tarafından doğrulanmış, daha gevşek eşik.
# RANGE: Standart eşikler.
# VOLATILE: Daha sıkı eşikler — risk yüksek.
REGIME_SE2_PARAMS: dict[str, dict] = {
    "TREND": {
        "min_sources": 2,
        "min_score": 35.0,
        "min_rr": 1.2,
    },
    "RANGE": {
        "min_sources": 2,      # v5.9.2: 3→2 (RANGE'de 2 kaynak yeterli)
        "min_score": 40.0,     # v5.9.2: 45→40
        "min_rr": 1.3,         # v5.9.2: 1.5→1.3
    },
    "VOLATILE": {
        "min_sources": 3,      # v5.9.2: 4→3
        "min_score": 50.0,     # v5.9.2: 60→50
        "min_rr": 1.5,         # v5.9.2: 2.0→1.5
    },
    "OLAY": {
        "min_sources": 5,      # v5.9.2: 99→5 (zor ama imkansız değil)
        "min_score": 70.0,     # v5.9.2: 999→70
        "min_rr": 2.0,         # v5.9.2: 99→2.0
    },
}

# Volatilite rejim tespiti: ATR percentile eşikleri
LOW_VOL_PERCENTILE: float = 30.0   # ATR bu percentilenin altındaysa düşük vol
HIGH_VOL_PERCENTILE: float = 70.0  # ATR bu percentilenin üstündeyse yüksek vol

# Kaynak ağırlıkları (sinyal gücü hesabında)
# [VİOP kalibrasyon: VİOP vadeli piyasada yapı kırılımı ve hacim daha gürültülü,
#  VWAP/momentum/KAMA daha güvenilir — ağırlıklar buna göre ayarlandı]
SOURCE_WEIGHTS: dict[str, float] = {
    "structure_break": 1.1,       # Yapı kırılımı [ESKİ: 1.3 → VİOP'ta S/R daha gürültülü]
    "momentum_ignition": 1.2,     # Momentum [ESKİ: 1.0 → VİOP'ta momentum daha güvenilir]
    "volume_intelligence": 0.9,   # Hacim [ESKİ: 1.2 → VİOP düşük likidite, hacim aldatıcı]
    "compression_release": 1.0,   # Sıkışma [ESKİ: 0.8 → VİOP'ta sıkışma sık ve güvenilir]
    "extreme_reversion": 0.8,     # Mean reversion [ESKİ: 0.7 → VİOP'ta uçlar daha çok]
    # SE3 yeni kaynaklar
    "vwap_institutional": 1.3,    # Kurumsal VWAP [ESKİ: 1.1 → VİOP'ta kurumsal seviyeler net]
    "smart_divergence": 1.0,      # Diverjans — erken uyarı
    "ichimoku_cloud": 0.8,        # Ichimoku [ESKİ: 0.9 → Gecikmeli, VİOP hızlı hareket]
    "adaptive_momentum": 1.1,     # KAMA [ESKİ: 1.0 → Rejim uyumlu, VİOP'a iyi uyar]
    # v5.7.1: Haber bazlı sinyal kaynağı
    "news_event": 1.3,            # Haber [YENİ: Haber sentiment bazlı, VWAP ile eşit ağırlık]
}

# ── SE3: VWAP sabitleri ──
VWAP_BOUNCE_ATR: float = 0.3    # VWAP'a 0.3×ATR yakınlık = bounce bölgesi  [SE3 kalibrasyon 2026-03-13]
VWAP_BREAK_ATR: float = 0.7     # VWAP'tan 0.7×ATR uzaklık = kırılma onayı  [SE3 kalibrasyon 2026-03-13]

# ── SE3: Ichimoku sabitleri ──
ICHI_STRONG_SCORE: float = 50.0   # Ichimoku puanı > 50 = güçlü sinyal  [SE3 kalibrasyon 2026-03-13]
ICHI_WEAK_SCORE: float = 20.0     # < 20 = zayıf, yoksay

# ── SE3: KAMA sabitleri ──
KAMA_TREND_SLOPE: float = 0.2     # KAMA eğimi > 0.2 ATR = trend var  [SE3 kalibrasyon 2026-03-13]
KAMA_FLAT_SLOPE: float = 0.05     # < 0.05 = yatay, trend yok

# ── SE3: Diverjans sabitleri ──
DIV_MIN_STRENGTH: float = 0.4     # Minimum diverjans gücü  [SE3 kalibrasyon 2026-03-13]
DIV_MAX_AGE_BARS: int = 10        # Diverjans en fazla 10 bar eskiyse geçerli

# Yapı kırılımı — S/R proximity
SR_PROXIMITY_ATR: float = 1.5   # Fiyat S/R'ye 1.5×ATR'den yakın olmalı
SR_BREAK_ATR: float = 0.3       # S/R kırılma eşiği: 0.3×ATR

# Momentum  [VİOP kalibrasyon: ROC eşikleri düşürüldü — VİOP daha dar bantlı]
ROC_STRONG: float = 0.8         # ROC > %0.8 = güçlü momentum  [ESKİ: 1.5]
ROC_WEAK: float = 0.15          # ROC < %0.15 = zayıf           [ESKİ: 0.3]
STOCH_RSI_OB: float = 80.0      # StochRSI > 80 = aşırı alım
STOCH_RSI_OS: float = 20.0      # StochRSI < 20 = aşırı satım
STOCH_RSI_CROSS_ZONE: float = 50.0  # %K/%D cross zone

# Sıkışma  [VİOP kalibrasyon: eşikler gevşetildi — VİOP daha sık sıkışır]
COMPRESSION_TIGHT: float = 0.45  # ratio < 0.45 = ciddi sıkışma  [ESKİ: 0.35]
COMPRESSION_EXPANDING: float = 0.6  # ratio > 0.6 = genişleme    [ESKİ: 0.7]

# Aşırı uç
EXTREME_RSI_OB: float = 75.0
EXTREME_RSI_OS: float = 25.0
EXTREME_WR_OB: float = -15.0    # W%R > -15 = aşırı alım
EXTREME_WR_OS: float = -85.0    # W%R < -85 = aşırı satım


# ═════════════════════════════════════════════════════════════════════
#  KAYNAK A: YAPI KIRILIMI (Structure Break)
# ═════════════════════════════════════════════════════════════════════

def _source_structure_break(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    open_: np.ndarray,
    volume: np.ndarray,
    atr_val: float,
    levels: list[Level],
    trend: TrendStructure,
    patterns: list[BarPattern],
) -> SourceResult:
    """Yapı kırılımı — Fiyat anahtar seviyeyi kırıyor mu?

    BUY sinyali:
        - Fiyat direnç seviyesini kırıyor (retest ile)
        - VEYA fiyat destek seviyesinden sıçrıyor (reddedme)
        - Bar pattern (pin bar, hammer, engulfing) destekliyor
        - Trend yapısı uyumlu

    SELL sinyali:
        - Fiyat destek seviyesini kırıyor
        - VEYA fiyat direnç seviyesinden reddediliyor
        - Bar pattern destekliyor

    Skor: 0-20 (yapı kalitesi + pattern + trend)
    """
    score = 0.0
    direction = "NEUTRAL"
    details: dict = {}
    price = float(close[-1])

    if not levels or atr_val <= 0:
        return SourceResult("structure_break", 0.0, "NEUTRAL", 0.0, {})

    # ── Direnç kırılımı (BUY tetikleyici) ─────────────────────────
    resistance_levels = [lv for lv in levels if lv.level_type == "resistance"]
    support_levels = [lv for lv in levels if lv.level_type == "support"]

    buy_score = 0.0
    sell_score = 0.0

    # Direnç kırılımı kontrolü
    for lv in resistance_levels:
        dist = price - lv.price
        if 0 < dist <= atr_val * SR_BREAK_ATR:
            # Direnç yeni kırıldı — breakout candidate
            buy_score += 8.0 + min(lv.strength * 2, 6.0)  # max 14
            details["resistance_broken"] = lv.price
            details["break_distance_atr"] = dist / atr_val
            break
        elif -atr_val * SR_PROXIMITY_ATR < dist < 0:
            # Dirence yaklaşma — henüz kırılmadı ama yakın
            proximity = 1.0 - abs(dist) / (atr_val * SR_PROXIMITY_ATR)
            buy_score += proximity * 4.0  # max 4
            details["approaching_resistance"] = lv.price

    # Destek sıçraması (bounce — BUY)
    for lv in support_levels:
        dist = price - lv.price
        if 0 < dist <= atr_val * SR_PROXIMITY_ATR:
            # Destek üzerindeyiz — sıçrama alanı
            proximity = 1.0 - dist / (atr_val * SR_PROXIMITY_ATR)
            bounce_score = proximity * 6.0 + min(lv.strength * 2, 4.0)
            if bounce_score > buy_score:
                buy_score = bounce_score
                details["support_bounce"] = lv.price

    # Destek kırılımı (SELL tetikleyici)
    for lv in support_levels:
        dist = lv.price - price
        if 0 < dist <= atr_val * SR_BREAK_ATR:
            # Destek kırıldı
            sell_score += 8.0 + min(lv.strength * 2, 6.0)
            details["support_broken"] = lv.price
            break
        elif -atr_val * SR_PROXIMITY_ATR < dist < 0:
            proximity = 1.0 - abs(dist) / (atr_val * SR_PROXIMITY_ATR)
            sell_score += proximity * 4.0

    # Direnç reddedmesi (rejection — SELL)
    for lv in resistance_levels:
        dist = lv.price - price
        if 0 < dist <= atr_val * SR_PROXIMITY_ATR:
            proximity = 1.0 - dist / (atr_val * SR_PROXIMITY_ATR)
            reject_score = proximity * 6.0 + min(lv.strength * 2, 4.0)
            if reject_score > sell_score:
                sell_score = reject_score
                details["resistance_rejection"] = lv.price

    # ── Pattern bonusu ────────────────────────────────────────────
    if patterns:
        if buy_score > sell_score:
            pat_ok, pat_str = pattern_confirms_direction(patterns, "BUY")
            if pat_ok and pat_str > 0:
                buy_score += pat_str * 4.0  # max 4
                details["pattern_confirms_buy"] = True
        elif sell_score > buy_score:
            pat_ok, pat_str = pattern_confirms_direction(patterns, "SELL")
            if pat_ok and pat_str > 0:
                sell_score += pat_str * 4.0
                details["pattern_confirms_sell"] = True

    # ── Trend bonusu ──────────────────────────────────────────────
    if buy_score > sell_score and trend.direction == "up":
        buy_score += trend.trend_strength * 3.0
    elif sell_score > buy_score and trend.direction == "down":
        sell_score += trend.trend_strength * 3.0

    # ── Final ─────────────────────────────────────────────────────
    if buy_score > sell_score and buy_score > 3.0:
        direction = "BUY"
        score = min(buy_score, 20.0)
    elif sell_score > buy_score and sell_score > 3.0:
        direction = "SELL"
        score = min(sell_score, 20.0)

    confidence = score / 20.0
    return SourceResult("structure_break", score, direction, confidence, details)


# ═════════════════════════════════════════════════════════════════════
#  KAYNAK B: MOMENTUM ATEŞLEMESİ (Momentum Ignition)
# ═════════════════════════════════════════════════════════════════════

def _source_momentum_ignition(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    atr_val: float,
) -> SourceResult:
    """Momentum ateşleme — ROC + StochRSI yakınsaması.

    EMA'dan tamamen bağımsız 2 momentum ölçüsü:
    - ROC: saf fiyat değişim hızı
    - StochRSI: RSI'ın normalize momentum durumu

    İkisi aynı yönü gösterdiğinde = momentum ateşleniyor.
    Birbirleriyle korelasyonları düşük (farklı matematik).

    Skor: 0-20 (ROC gücü + StochRSI durumu + yakınsama bonusu)
    """
    score = 0.0
    direction = "NEUTRAL"
    details: dict = {}

    n = len(close)
    if n < 30:
        return SourceResult("momentum_ignition", 0.0, "NEUTRAL", 0.0, {})

    # ROC hesapla (12 ve 5 periyot — 2 hız)
    roc_12 = calc_roc(close, 12)
    roc_5 = calc_roc(close, 5)

    # StochRSI hesapla
    stoch_k, stoch_d = stochastic_rsi(close)

    # Son geçerli değerler
    def _lv(arr):
        v = arr[~np.isnan(arr)]
        return float(v[-1]) if len(v) > 0 else None

    roc12 = _lv(roc_12)
    roc5 = _lv(roc_5)
    sk = _lv(stoch_k)
    sd = _lv(stoch_d)

    if any(v is None for v in (roc12, roc5, sk)):
        return SourceResult("momentum_ignition", 0.0, "NEUTRAL", 0.0, {})

    details["roc_12"] = round(roc12, 3)
    details["roc_5"] = round(roc5, 3)
    details["stoch_k"] = round(sk, 1)

    buy_score = 0.0
    sell_score = 0.0

    # ── ROC analizi (0-10) ────────────────────────────────────────
    # BUY: İki ROC da pozitif ve güçlü
    if roc12 > 0 and roc5 > 0:
        roc_avg = (abs(roc12) + abs(roc5)) / 2.0
        if roc_avg > ROC_STRONG:
            buy_score += 10.0
        elif roc_avg > ROC_WEAK:
            buy_score += roc_avg / ROC_STRONG * 10.0
        # Hızlanma bonusu: kısa periyot > uzun periyot
        if roc5 > roc12:
            buy_score += 2.0
            details["accelerating_up"] = True

    elif roc12 < 0 and roc5 < 0:
        roc_avg = (abs(roc12) + abs(roc5)) / 2.0
        if roc_avg > ROC_STRONG:
            sell_score += 10.0
        elif roc_avg > ROC_WEAK:
            sell_score += roc_avg / ROC_STRONG * 10.0
        if roc5 < roc12:
            sell_score += 2.0
            details["accelerating_down"] = True

    # ── StochRSI analizi (0-8) ────────────────────────────────────
    # BUY: StochRSI aşırı satımdan çıkıyor (20 altından 20 üstüne)
    if sk is not None and sd is not None:
        if sk > sd and sk < 50:
            # %K > %D cross (bullish) ve henüz aşırı alıma gelmemiş
            buy_score += 6.0
            if sk < 30:
                buy_score += 2.0  # Aşırı satımdan çıkış = güçlü
                details["stoch_oversold_exit"] = True
        elif sk < sd and sk > 50:
            # %K < %D cross (bearish) ve henüz aşırı satıma girmemiş
            sell_score += 6.0
            if sk > 70:
                sell_score += 2.0
                details["stoch_overbought_exit"] = True

    # ── Final ─────────────────────────────────────────────────────
    if buy_score > sell_score and buy_score > 4.0:
        direction = "BUY"
        score = min(buy_score, 20.0)
    elif sell_score > buy_score and sell_score > 4.0:
        direction = "SELL"
        score = min(sell_score, 20.0)

    confidence = score / 20.0
    return SourceResult("momentum_ignition", score, direction, confidence, details)


# ═════════════════════════════════════════════════════════════════════
#  KAYNAK C: HACİM İSTİHBARATI (Volume Intelligence)
# ═════════════════════════════════════════════════════════════════════

def _source_volume_intelligence(
    close: np.ndarray,
    volume: np.ndarray,
    atr_val: float,
) -> SourceResult:
    """Hacim istihbaratı — akıllı para ne yapıyor?

    3 bağımsız hacim sinyali:
    1. OBV Divergence: Fiyat-hacim uyumsuzluğu (birikim/dağıtım)
    2. Volume Momentum: Hacim-ağırlıklı fiyat hareketi
    3. Volume Climax: Ani hacim patlaması yönü

    Skor: 0-20 (OBV + VolMom + Climax)
    """
    score = 0.0
    direction = "NEUTRAL"
    details: dict = {}
    n = len(close)

    if n < 25 or atr_val <= 0:
        return SourceResult("volume_intelligence", 0.0, "NEUTRAL", 0.0, {})

    buy_score = 0.0
    sell_score = 0.0

    # ── 1. OBV Divergence (0-8) ───────────────────────────────────
    obv_div = obv_divergence(close, volume, lookback=20)
    div_val = float(obv_div[-1]) if len(obv_div) > 0 and not np.isnan(obv_div[-1]) else 0.0

    if div_val > 0.05:
        buy_score += min(div_val * 8.0, 8.0)  # Bullish divergence
        details["obv_bullish_div"] = round(div_val, 3)
    elif div_val < -0.05:
        sell_score += min(abs(div_val) * 8.0, 8.0)  # Bearish divergence
        details["obv_bearish_div"] = round(div_val, 3)

    # ── 2. Volume Momentum (0-7) ──────────────────────────────────
    vol_mom = volume_momentum(close, volume, 14)
    vm_val = float(vol_mom[-1]) if len(vol_mom) > 0 and not np.isnan(vol_mom[-1]) else 0.0

    # Normalize: vm / atr
    vm_norm = vm_val / atr_val if atr_val > 0 else 0.0
    details["vol_momentum_norm"] = round(vm_norm, 4)

    if vm_norm > 0.02:  # [VİOP kalibrasyon: 0.05→0.02 — düşük likidite ortamı]
        buy_score += min(vm_norm * 35.0, 7.0)  # Çarpan artırıldı: 20→35
    elif vm_norm < -0.02:
        sell_score += min(abs(vm_norm) * 35.0, 7.0)

    # ── 3. Volume Climax (0-5) ────────────────────────────────────
    # Son bar hacmi / 20-bar ortalama
    if n > 21:
        avg_vol = float(np.nanmean(volume[-21:-1]))
        cur_vol = float(volume[-1])
        if avg_vol > 0:
            vol_ratio = cur_vol / avg_vol
            details["vol_ratio"] = round(vol_ratio, 2)

            if vol_ratio >= 1.8:
                # Hacim klimaksı — yön tespiti  [VİOP kalibrasyon: 2.5→1.8]
                price_change = close[-1] - close[-2]
                if price_change > 0:
                    buy_score += 5.0
                    details["volume_climax"] = "bullish"
                elif price_change < 0:
                    sell_score += 5.0
                    details["volume_climax"] = "bearish"
            elif vol_ratio >= 1.1:
                # Ortalamanın üstünde hacim — küçük bonus  [VİOP kalibrasyon: 1.5→1.1]
                price_change = close[-1] - close[-2]
                if price_change > 0:
                    buy_score += 2.0
                elif price_change < 0:
                    sell_score += 2.0

    # ── Final ─────────────────────────────────────────────────────
    if buy_score > sell_score and buy_score > 2.0:
        direction = "BUY"
        score = min(buy_score, 20.0)
    elif sell_score > buy_score and sell_score > 2.0:
        direction = "SELL"
        score = min(sell_score, 20.0)

    confidence = score / 20.0
    return SourceResult("volume_intelligence", score, direction, confidence, details)


# ═════════════════════════════════════════════════════════════════════
#  KAYNAK D: SIKIŞMA ÇÖZÜLMESİ (Compression Release)
# ═════════════════════════════════════════════════════════════════════

def _source_compression_release(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    atr_val: float,
) -> SourceResult:
    """Sıkışma çözülmesi — fiyat sıkışması sonrası patlama.

    BB/KC Squeeze yerine saf fiyat compression ratio kullanır.
    Sıkışma sonrası ilk genişleme = güçlü hareket başlangıcı.

    Sıralama:
    1. Son 5-10 bar'da sıkışma var mıydı? (compression < 0.35)
    2. Şu an genişleme başladı mı? (compression artıyor)
    3. Genişleme yönü = sinyal yönü
    4. Hacim genişlemeyi destekliyor mu?

    Skor: 0-20 (sıkışma kalitesi + patlama gücü + hacim)
    """
    score = 0.0
    direction = "NEUTRAL"
    details: dict = {}
    n = len(close)

    if n < 25 or atr_val <= 0:
        return SourceResult("compression_release", 0.0, "NEUTRAL", 0.0, {})

    # Compression ratio hesapla
    comp = compression_ratio(high, low, close, short_period=5, long_period=20)

    # Son 10 bar'ı analiz et
    recent = comp[-10:]
    valid = recent[~np.isnan(recent)]
    if len(valid) < 5:
        return SourceResult("compression_release", 0.0, "NEUTRAL", 0.0, {})

    current_comp = float(valid[-1])
    min_comp = float(np.min(valid[:-1])) if len(valid) > 1 else current_comp
    details["current_compression"] = round(current_comp, 3)
    details["min_compression"] = round(min_comp, 3)

    # Sıkışma VAR MIYDI?
    had_compression = min_comp < COMPRESSION_TIGHT

    if not had_compression:
        return SourceResult("compression_release", 0.0, "NEUTRAL", 0.0, {"no_compression": True})

    # Genişleme BAŞLADI MI?
    expanding = current_comp > min_comp * 1.3  # %30'dan fazla genişleme
    if not expanding:
        details["compression_building"] = True
        return SourceResult("compression_release", 3.0, "NEUTRAL", 0.15, details)

    # ── Patlama yönü ──────────────────────────────────────────────
    # Son 3 bar'ın net yönü
    if len(close) >= 3:
        move = close[-1] - close[-3]
        if move > atr_val * 0.3:
            direction = "BUY"
        elif move < -atr_val * 0.3:
            direction = "SELL"

    if direction == "NEUTRAL":
        return SourceResult("compression_release", 5.0, "NEUTRAL", 0.25, details)

    # ── Skor hesapla ──────────────────────────────────────────────
    # Sıkışma kalitesi (0-8)
    tightness_score = (COMPRESSION_TIGHT - min_comp) / COMPRESSION_TIGHT * 8.0
    tightness_score = max(min(tightness_score, 8.0), 0.0)

    # Genişleme gücü (0-7)
    expansion = current_comp / min_comp if min_comp > 0 else 1.0
    expansion_score = min((expansion - 1.0) * 5.0, 7.0)

    # Hacim desteği (0-5)
    vol_score = 0.0
    if n > 21:
        avg_vol = float(np.nanmean(volume[-21:-1]))
        cur_vol = float(volume[-1])
        if avg_vol > 0:
            vol_ratio = cur_vol / avg_vol
            if vol_ratio >= 1.5:
                vol_score = min(vol_ratio * 2.0, 5.0)

    score = min(tightness_score + expansion_score + vol_score, 20.0)
    confidence = score / 20.0
    details["expansion_ratio"] = round(expansion, 2)
    details["vol_support"] = round(vol_score, 1)

    return SourceResult("compression_release", score, direction, confidence, details)


# ═════════════════════════════════════════════════════════════════════
#  KAYNAK E: AŞIRI UÇ GERİ DÖNÜŞ (Extreme Reversion)
# ═════════════════════════════════════════════════════════════════════

def _source_extreme_reversion(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    atr_val: float,
) -> SourceResult:
    """Aşırı uç geri dönüş — çoklu bağımsız osilatör yakınsaması.

    Tek bir RSI eşiği yerine, 3 BAĞIMSIZ osilatörün
    hepsinin aynı anda aşırı bölgede olması aranır.
    Bu çok daha güvenilir (yanlış pozitif azalır).

    Osilatörler:
    1. RSI(14) — klasik momentum
    2. Williams %R(14) — range-bazlı momentum
    3. StochRSI(14,14) — RSI'ın stokastik hali

    Minimum 2/3 aşırı bölgede olmalı.

    Skor: 0-20 (osilatör sayısı + aşırılık derecesi + geri dönüş başlangıcı)
    """
    score = 0.0
    direction = "NEUTRAL"
    details: dict = {}
    n = len(close)

    if n < 30 or atr_val <= 0:
        return SourceResult("extreme_reversion", 0.0, "NEUTRAL", 0.0, {})

    # Osilatörler
    rsi_arr = calc_rsi(close, 14)
    wr_arr = calc_williams_r(high, low, close, 14)
    stoch_k, _ = stochastic_rsi(close)

    def _lv(arr):
        v = arr[~np.isnan(arr)]
        return float(v[-1]) if len(v) > 0 else None

    rsi_val = _lv(rsi_arr)
    wr_val = _lv(wr_arr)
    sk_val = _lv(stoch_k)

    if rsi_val is None:
        return SourceResult("extreme_reversion", 0.0, "NEUTRAL", 0.0, {})

    details["rsi"] = round(rsi_val, 1)
    if wr_val: details["williams_r"] = round(wr_val, 1)
    if sk_val: details["stoch_k"] = round(sk_val, 1)

    # Aşırı satım sayımı
    os_count = 0
    ob_count = 0

    # RSI
    if rsi_val < EXTREME_RSI_OS:
        os_count += 1
    elif rsi_val > EXTREME_RSI_OB:
        ob_count += 1

    # Williams %R
    if wr_val is not None:
        if wr_val < EXTREME_WR_OS:
            os_count += 1
        elif wr_val > EXTREME_WR_OB:
            ob_count += 1

    # StochRSI
    if sk_val is not None:
        if sk_val < STOCH_RSI_OS:
            os_count += 1
        elif sk_val > STOCH_RSI_OB:
            ob_count += 1

    details["oversold_count"] = os_count
    details["overbought_count"] = ob_count

    # Minimum 2/3 uyumlu olmalı
    if os_count < 2 and ob_count < 2:
        return SourceResult("extreme_reversion", 0.0, "NEUTRAL", 0.0, details)

    # ── Skor hesapla ──────────────────────────────────────────────
    if os_count >= 2:
        direction = "BUY"
        # Kaç osilatör (0-8)
        count_score = os_count * 4.0

        # RSI aşırılık derecesi (0-6)
        extreme_score = max((EXTREME_RSI_OS - rsi_val) / 15.0 * 6.0, 0.0)

        # Geri dönüş başlangıcı: RSI son 3 bar'da artıyor mu? (0-6)
        reversal_score = 0.0
        valid_rsi = rsi_arr[~np.isnan(rsi_arr)]
        if len(valid_rsi) >= 3:
            if valid_rsi[-1] > valid_rsi[-2] > valid_rsi[-3]:
                reversal_score = 6.0
                details["reversal_starting"] = True
            elif valid_rsi[-1] > valid_rsi[-2]:
                reversal_score = 3.0

        score = min(count_score + extreme_score + reversal_score, 20.0)

    elif ob_count >= 2:
        direction = "SELL"
        count_score = ob_count * 4.0
        extreme_score = max((rsi_val - EXTREME_RSI_OB) / 15.0 * 6.0, 0.0)
        reversal_score = 0.0
        valid_rsi = rsi_arr[~np.isnan(rsi_arr)]
        if len(valid_rsi) >= 3:
            if valid_rsi[-1] < valid_rsi[-2] < valid_rsi[-3]:
                reversal_score = 6.0
                details["reversal_starting"] = True
            elif valid_rsi[-1] < valid_rsi[-2]:
                reversal_score = 3.0

        score = min(count_score + extreme_score + reversal_score, 20.0)

    confidence = score / 20.0
    return SourceResult("extreme_reversion", score, direction, confidence, details)


# ═════════════════════════════════════════════════════════════════════
#  KAYNAK F: VWAP KURUMSAL (Institutional VWAP)
# ═════════════════════════════════════════════════════════════════════

def _source_vwap_institutional(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    atr_val: float,
) -> SourceResult:
    """VWAP kurumsal seviye analizi.

    Mantık:
      - VWAP, kurumsal yatırımcıların referans seviyesidir
      - Fiyat VWAP'a yaklaştığında bounce veya kırılma beklenir
      - VWAP üst/alt bantları aşırı bölge gösterir

    Alt sinyaller:
      1. VWAP pozisyonu: Fiyat VWAP'ın üstünde/altında (0-8 puan)
      2. VWAP bounce/kırılma: Seviyeye yakınlık + yön (0-7 puan)
      3. Bant analizi: Üst/alt bant etkileşimi (0-5 puan)
    """
    details: dict = {}
    direction = "NEUTRAL"
    score = 0.0

    n = len(close)
    if n < 30:
        return SourceResult("vwap_institutional", 0.0, "NEUTRAL", 0.0, details)

    atr_arr = calc_atr(high, low, close, 14)
    vwap_line, upper_band, lower_band = calc_vwap(high, low, close, volume)
    dist = vwap_distance(close, vwap_line, atr_arr)

    # Son geçerli değerleri al
    last_dist = float("nan")
    prev_dist = float("nan")
    last_vwap = float("nan")

    for i in range(n - 1, max(n - 5, -1), -1):
        if not np.isnan(dist[i]):
            if np.isnan(last_dist):
                last_dist = float(dist[i])
            elif np.isnan(prev_dist):
                prev_dist = float(dist[i])
                break

    if not np.isnan(vwap_line[n - 1]):
        last_vwap = float(vwap_line[n - 1])

    if np.isnan(last_dist) or np.isnan(last_vwap):
        return SourceResult("vwap_institutional", 0.0, "NEUTRAL", 0.0, details)

    details["vwap_distance"] = round(last_dist, 3)
    details["vwap_value"] = round(last_vwap, 2)

    # ── 1. VWAP pozisyonu (0-8 puan) ──
    pos_score = 0.0
    if last_dist > VWAP_BREAK_ATR:
        # Fiyat VWAP'ın çok üstünde → güçlü bullish
        direction = "BUY"
        pos_score = min(abs(last_dist) * 4.0, 8.0)
        details["vwap_position"] = "above_strong"
    elif last_dist > VWAP_BOUNCE_ATR:
        # VWAP üstünde, bounce bölgesinden çıkmış
        direction = "BUY"
        pos_score = 5.0
        details["vwap_position"] = "above"
    elif last_dist < -VWAP_BREAK_ATR:
        direction = "SELL"
        pos_score = min(abs(last_dist) * 4.0, 8.0)
        details["vwap_position"] = "below_strong"
    elif last_dist < -VWAP_BOUNCE_ATR:
        direction = "SELL"
        pos_score = 5.0
        details["vwap_position"] = "below"
    else:
        # VWAP etrafında — yön belirsiz
        details["vwap_position"] = "near_vwap"

    # ── 2. VWAP cross momentum (0-7 puan) ──
    cross_score = 0.0
    if not np.isnan(prev_dist):
        # Cross tespit: önceki bar VWAP altında, şimdi üstünde (veya tersi)
        if prev_dist < 0 and last_dist > 0:
            direction = "BUY"
            cross_score = 7.0
            details["vwap_cross"] = "bullish_cross"
        elif prev_dist > 0 and last_dist < 0:
            direction = "SELL"
            cross_score = 7.0
            details["vwap_cross"] = "bearish_cross"
        else:
            # Momentum devamı
            if last_dist > prev_dist and last_dist > 0:
                cross_score = 3.0
                details["vwap_momentum"] = "bullish_accel"
            elif last_dist < prev_dist and last_dist < 0:
                cross_score = 3.0
                details["vwap_momentum"] = "bearish_accel"

    # ── 3. Bant analizi (0-5 puan) ──
    band_score = 0.0
    last_close = float(close[-1])
    if not np.isnan(upper_band[n - 1]) and not np.isnan(lower_band[n - 1]):
        ub = float(upper_band[n - 1])
        lb = float(lower_band[n - 1])

        if last_close > ub:
            # Üst bant kırılması: aşırı alım veya breakout
            if direction == "BUY":
                band_score = 5.0
                details["vwap_band"] = "breakout_upper"
            else:
                band_score = 2.0  # Çelişki durumunda düşük puan
        elif last_close < lb:
            if direction == "SELL":
                band_score = 5.0
                details["vwap_band"] = "breakout_lower"
            else:
                band_score = 2.0

    score = min(pos_score + cross_score + band_score, 20.0)
    confidence = score / 20.0
    return SourceResult("vwap_institutional", score, direction, confidence, details)


# ═════════════════════════════════════════════════════════════════════
#  KAYNAK G: AKILLI DİVERJANS (Smart Divergence)
# ═════════════════════════════════════════════════════════════════════

def _source_smart_divergence(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    atr_val: float,
) -> SourceResult:
    """Çoklu indikatör diverjans tespiti.

    Mantık:
      - Fiyat yeni tepe/dip yaparken indikatörler yapmıyorsa → trend zayıflıyor
      - 3 farklı indikatörde diverjans ararız → güvenilirlik artar
      - Regular divergence = trend dönüşü, Hidden = trend devamı

    İndikatörler:
      1. RSI diverjansı — en klasik ve güvenilir
      2. MACD histogram diverjansı — momentum kaybı
      3. OBV diverjansı — hacim ayrışması (akıllı para)

    Puanlama:
      - 1 indikatörde diverjans: 6-8 puan
      - 2 indikatörde: 12-16 puan
      - 3 indikatörde: 18-20 puan (çok nadir, çok güçlü)
    """
    details: dict = {}
    n = len(close)

    if n < 50:
        return SourceResult("smart_divergence", 0.0, "NEUTRAL", 0.0, details)

    # İndikatörleri hesapla
    rsi_arr = calc_rsi(close, 14)
    _, _, macd_hist = calc_macd(close)
    obv_arr = calc_obv(close, volume)

    # 3 indikatörde diverjans ara
    indicators = [
        ("rsi", rsi_arr),
        ("macd_hist", macd_hist),
        ("obv", obv_arr),
    ]

    bullish_divs: list[dict] = []
    bearish_divs: list[dict] = []

    for ind_name, ind_arr in indicators:
        divs = detect_divergence(close, ind_arr, lookback=30, swing_order=5)
        for d in divs:
            # Sadece son DIV_MAX_AGE_BARS bar içindeki diverjanslar
            if d["bar_index"] >= n - DIV_MAX_AGE_BARS and d["strength"] >= DIV_MIN_STRENGTH:
                d["indicator"] = ind_name
                if d["type"] == "bullish":
                    bullish_divs.append(d)
                else:
                    bearish_divs.append(d)

    # Hangi yönde daha fazla diverjans var?
    bull_inds = set(d["indicator"] for d in bullish_divs)
    bear_inds = set(d["indicator"] for d in bearish_divs)

    details["bullish_count"] = len(bull_inds)
    details["bearish_count"] = len(bear_inds)
    details["bullish_indicators"] = list(bull_inds)
    details["bearish_indicators"] = list(bear_inds)

    direction = "NEUTRAL"
    score = 0.0

    if len(bull_inds) > len(bear_inds) and len(bull_inds) >= 1:
        direction = "BUY"
        count = len(bull_inds)
        # Ortalama güç
        avg_str = np.mean([d["strength"] for d in bullish_divs]) if bullish_divs else 0.0
        # Regular mı hidden mı?
        has_regular = any(d["kind"] == "regular" for d in bullish_divs)
        has_hidden = any(d["kind"] == "hidden" for d in bullish_divs)

        base = count * 6.0  # 1=6, 2=12, 3=18
        strength_bonus = avg_str * 4.0  # max 4
        regular_bonus = 2.0 if has_regular else 0.0  # Regular daha güçlü

        score = min(base + strength_bonus + regular_bonus, 20.0)
        details["dominant_kind"] = "regular" if has_regular else "hidden"

    elif len(bear_inds) > len(bull_inds) and len(bear_inds) >= 1:
        direction = "SELL"
        count = len(bear_inds)
        avg_str = np.mean([d["strength"] for d in bearish_divs]) if bearish_divs else 0.0
        has_regular = any(d["kind"] == "regular" for d in bearish_divs)

        base = count * 6.0
        strength_bonus = avg_str * 4.0
        regular_bonus = 2.0 if has_regular else 0.0

        score = min(base + strength_bonus + regular_bonus, 20.0)
        details["dominant_kind"] = "regular" if has_regular else "hidden"

    confidence = score / 20.0
    return SourceResult("smart_divergence", score, direction, confidence, details)


# ═════════════════════════════════════════════════════════════════════
#  KAYNAK H: ICHIMOKU BULUTU (Ichimoku Cloud)
# ═════════════════════════════════════════════════════════════════════

def _source_ichimoku_cloud(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr_val: float,
) -> SourceResult:
    """Ichimoku Kinko Hyo bulut sinyal analizi.

    Mantık:
      - 5 bileşenli Japon sistemi: Tenkan, Kijun, Senkou A/B, Chikou
      - Her bileşen bağımsız bilgi verir, birlikte güçlü sinyal oluşturur
      - Fiyatın bulut üstünde/altında olması temel yön göstergesi

    Puanlama (ichimoku_signal fonksiyonundan):
      - Score -100 ile +100 arası → normalize 0-20
      - > +60: güçlü BUY (12-20 puan)
      - +20 ile +60: orta BUY (6-12 puan)
      - -20 ile +20: NEUTRAL
      - -60 ile -20: orta SELL
      - < -60: güçlü SELL
    """
    details: dict = {}
    n = len(close)

    if n < 60:  # Ichimoku 52 bar gerektirir
        return SourceResult("ichimoku_cloud", 0.0, "NEUTRAL", 0.0, details)

    ichi = calc_ichimoku(high, low, close)
    ichi_scores = ichimoku_signal(close, ichi)

    # Son geçerli skoru al
    last_score = float("nan")
    for i in range(n - 1, max(n - 5, -1), -1):
        if not np.isnan(ichi_scores[i]):
            last_score = float(ichi_scores[i])
            break

    if np.isnan(last_score):
        return SourceResult("ichimoku_cloud", 0.0, "NEUTRAL", 0.0, details)

    details["ichimoku_raw_score"] = round(last_score, 1)

    # Tenkan/Kijun bilgisi
    ts = ichi["tenkan_sen"]
    ks = ichi["kijun_sen"]
    if not np.isnan(ts[n - 1]) and not np.isnan(ks[n - 1]):
        details["tenkan_kijun_diff"] = round(float(ts[n - 1] - ks[n - 1]), 4)

    # Kumo pozisyonu
    sa = ichi["senkou_a"]
    sb = ichi["senkou_b"]
    if not np.isnan(sa[n - 1]) and not np.isnan(sb[n - 1]):
        kumo_top = max(float(sa[n - 1]), float(sb[n - 1]))
        kumo_bot = min(float(sa[n - 1]), float(sb[n - 1]))
        last_close = float(close[-1])
        if last_close > kumo_top:
            details["kumo_position"] = "above"
        elif last_close < kumo_bot:
            details["kumo_position"] = "below"
        else:
            details["kumo_position"] = "inside"

    direction = "NEUTRAL"
    score = 0.0

    if last_score > ICHI_WEAK_SCORE:
        direction = "BUY"
        # Normalize: 20-100 → 4-20 puan
        score = min((last_score - ICHI_WEAK_SCORE) / (100.0 - ICHI_WEAK_SCORE) * 20.0, 20.0)
        score = max(score, 4.0)
    elif last_score < -ICHI_WEAK_SCORE:
        direction = "SELL"
        score = min((abs(last_score) - ICHI_WEAK_SCORE) / (100.0 - ICHI_WEAK_SCORE) * 20.0, 20.0)
        score = max(score, 4.0)

    # Kumo içindeyse puan düşür
    if details.get("kumo_position") == "inside":
        score *= 0.5

    confidence = score / 20.0
    return SourceResult("ichimoku_cloud", score, direction, confidence, details)


# ═════════════════════════════════════════════════════════════════════
#  KAYNAK I: ADAPTİF MOMENTUM (KAMA-bazlı)
# ═════════════════════════════════════════════════════════════════════

def _source_adaptive_momentum(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    atr_val: float,
) -> SourceResult:
    """Kaufman Adaptive Moving Average bazlı rejim-uyumlu momentum.

    Mantık:
      - KAMA, gürültülü piyasada yavaşlar, trendde hızlanır
      - Eğim yönü = trend yönü, eğim büyüklüğü = trend gücü
      - Fiyat-KAMA ilişkisi = momentum kalitesi
      - Efficiency Ratio = piyasa ne kadar "temiz"

    Alt sinyaller:
      1. KAMA eğimi yönü ve gücü (0-8 puan)
      2. Fiyat-KAMA pozisyonu + cross (0-7 puan)
      3. Efficiency Ratio kalitesi (0-5 puan)
    """
    details: dict = {}
    n = len(close)

    if n < 35:
        return SourceResult("adaptive_momentum", 0.0, "NEUTRAL", 0.0, details)

    atr_arr = calc_atr(high, low, close, 14)
    kama_vals = calc_kama(close, er_period=10, fast_sc=2, slow_sc=30)
    slope_vals = kama_slope(kama_vals, lookback=5, atr_vals=atr_arr)

    # Son geçerli değerler
    last_kama = float("nan")
    last_slope = float("nan")
    prev_kama = float("nan")
    last_close = float(close[-1])
    prev_close = float(close[-2]) if n > 1 else float("nan")

    for i in range(n - 1, max(n - 3, -1), -1):
        if not np.isnan(kama_vals[i]) and np.isnan(last_kama):
            last_kama = float(kama_vals[i])
        if not np.isnan(slope_vals[i]) and np.isnan(last_slope):
            last_slope = float(slope_vals[i])
    if n > 1 and not np.isnan(kama_vals[n - 2]):
        prev_kama = float(kama_vals[n - 2])

    if np.isnan(last_kama) or np.isnan(last_slope):
        return SourceResult("adaptive_momentum", 0.0, "NEUTRAL", 0.0, details)

    details["kama_value"] = round(last_kama, 4)
    details["kama_slope"] = round(last_slope, 4)
    details["price_kama_diff"] = round(last_close - last_kama, 4)

    direction = "NEUTRAL"
    score = 0.0

    # ── 1. KAMA eğimi (0-8 puan) ──
    slope_score = 0.0
    if abs(last_slope) > KAMA_TREND_SLOPE:
        # Güçlü trend
        slope_score = min(abs(last_slope) / KAMA_TREND_SLOPE * 4.0, 8.0)
        direction = "BUY" if last_slope > 0 else "SELL"
        details["kama_trend"] = "strong_up" if last_slope > 0 else "strong_down"
    elif abs(last_slope) > KAMA_FLAT_SLOPE:
        # Orta trend
        slope_score = 3.0
        direction = "BUY" if last_slope > 0 else "SELL"
        details["kama_trend"] = "moderate_up" if last_slope > 0 else "moderate_down"
    else:
        details["kama_trend"] = "flat"

    # ── 2. Fiyat-KAMA pozisyonu + cross (0-7 puan) ──
    cross_score = 0.0
    price_diff_atr = (last_close - last_kama) / atr_val if atr_val > 0 else 0

    # Cross tespit
    if not np.isnan(prev_kama):
        was_below = prev_close < prev_kama
        is_above = last_close > last_kama
        was_above = prev_close > prev_kama
        is_below = last_close < last_kama

        if was_below and is_above:
            cross_score = 7.0
            direction = "BUY"
            details["kama_cross"] = "bullish"
        elif was_above and is_below:
            cross_score = 7.0
            direction = "SELL"
            details["kama_cross"] = "bearish"
        else:
            # Pozisyon gücü
            if price_diff_atr > 0.5 and direction == "BUY":
                cross_score = 4.0
            elif price_diff_atr < -0.5 and direction == "SELL":
                cross_score = 4.0
            elif abs(price_diff_atr) > 0.2:
                cross_score = 2.0

    # ── 3. Efficiency Ratio kalitesi (0-5 puan) ──
    er_score = 0.0
    er_period = 10
    if n > er_period:
        direction_move = abs(close[-1] - close[-1 - er_period])
        volatility = np.sum(np.abs(np.diff(close[-er_period - 1:])))
        if volatility > 0:
            er = direction_move / volatility
            details["efficiency_ratio"] = round(er, 3)
            # ER > 0.6 = çok temiz trend
            if er > 0.6:
                er_score = 5.0
                details["market_quality"] = "clean_trend"
            elif er > 0.4:
                er_score = 3.0
                details["market_quality"] = "moderate"
            elif er > 0.2:
                er_score = 1.0
                details["market_quality"] = "choppy"
            else:
                details["market_quality"] = "noise"
                # Gürültülü piyasada KAMA sinyali güvenilmez
                slope_score *= 0.5
                cross_score *= 0.5

    score = min(slope_score + cross_score + er_score, 20.0)
    confidence = score / 20.0
    return SourceResult("adaptive_momentum", score, direction, confidence, details)


# ═════════════════════════════════════════════════════════════════════
#  J) HABER BAZLI SİNYAL — v6.1'de KALDIRILDI (nötr stub)
# ═════════════════════════════════════════════════════════════════════

def _source_news_event(
    symbol: str = "",
    news_bridge=None,
) -> SourceResult:
    """Stub — haber entegrasyonu v6.1'de tamamen kaldırıldı.

    Skorlama boyutu (10 kaynak) korunur; J kaynağı her zaman NEUTRAL döner.
    Böylece min_agree eşikleri ve skorlama mantığı değişmeden kalır.
    """
    return SourceResult("news_event", 0.0, "NEUTRAL", 0.0, {"reason": "removed_v6.1"})


# ═════════════════════════════════════════════════════════════════════
#  ANA MOTOR: SİNYAL ÜRETİMİ
# ═════════════════════════════════════════════════════════════════════

def generate_signal(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    current_price: float = 0.0,
    regime_type: str = "",
    symbol: str = "",
    news_bridge=None,
) -> SignalVerdict:
    """Ana sinyal üretim motoru — 10 bağımsız kaynaktan karar (SE3).

    Args:
        open_, high, low, close, volume: M15 OHLCV verileri.
        current_price: Güncel tick fiyatı (0 ise close[-1] kullanılır).
        regime_type: BABA rejim tipi ("TREND", "RANGE", "VOLATILE", "OLAY").
        symbol: VİOP kontrat kodu.
        news_bridge: Deprecated — v6.1'de kaldırıldı, parametre backward-compat için tutuluyor, None olmalı.

    Returns:
        SignalVerdict nesnesi.
    """
    verdict = SignalVerdict()
    n = len(close)
    if n < 30:
        return verdict

    if current_price <= 0:
        current_price = float(close[-1])

    # ── Ortak hesaplamalar ────────────────────────────────────────
    atr_arr = calc_atr(high, low, close, 14)
    atr_valid = atr_arr[~np.isnan(atr_arr)]
    if len(atr_valid) == 0:
        return verdict
    atr_val = float(atr_valid[-1])
    if atr_val <= 0:
        return verdict

    # ── Volatilite rejim tespiti ────────────────────────────────
    vol_regime = "NORMAL"  # LOW / NORMAL / HIGH
    if len(atr_valid) >= 50:
        atr_pct = float(np.percentile(atr_valid[-100:], 50))  # medyan referans
        current_rank = float(
            np.searchsorted(np.sort(atr_valid[-100:]), atr_val)
            / len(atr_valid[-100:]) * 100
        )
        if current_rank < LOW_VOL_PERCENTILE:
            vol_regime = "LOW"
        elif current_rank > HIGH_VOL_PERCENTILE:
            vol_regime = "HIGH"

    # ── v2: Rejim-bazlı adaptif eşikler ────────────────────────────
    # BABA rejim tipi varsa REGIME_SE2_PARAMS'dan al, yoksa vol_regime fallback
    _regime_params = REGIME_SE2_PARAMS.get(regime_type, {})
    if _regime_params:
        min_agree = _regime_params["min_sources"]
        min_score = _regime_params["min_score"]
        min_rr = _regime_params["min_rr"]
    else:
        # Fallback: eski vol_regime bazlı mantık
        min_agree = MIN_AGREEING_SOURCES_LOW_VOL if vol_regime == "LOW" else MIN_AGREEING_SOURCES
        min_score = MIN_TOTAL_SCORE_LOW_VOL if vol_regime == "LOW" else MIN_TOTAL_SCORE
        min_rr = MIN_RISK_REWARD

    # Price Action yapısal analiz (FAZ 1'den)
    levels = find_support_resistance(high, low, close, atr_val)
    patterns = detect_bar_patterns(open_, high, low, close, atr_val)
    trend = analyze_trend_structure(high, low, close)

    # ── 9 Kaynak çalıştır (SE3) ────────────────────────────────────
    sources: list[SourceResult] = []

    # A) Yapı Kırılımı
    src_a = _source_structure_break(
        high, low, close, open_, volume,
        atr_val, levels, trend, patterns,
    )
    sources.append(src_a)

    # B) Momentum Ateşleme
    src_b = _source_momentum_ignition(close, high, low, atr_val)
    sources.append(src_b)

    # C) Hacim İstihbaratı
    src_c = _source_volume_intelligence(close, volume, atr_val)
    sources.append(src_c)

    # D) Sıkışma Çözülmesi
    src_d = _source_compression_release(high, low, close, volume, atr_val)
    sources.append(src_d)

    # E) Aşırı Uç Geri Dönüş
    src_e = _source_extreme_reversion(close, high, low, atr_val)
    sources.append(src_e)

    # F) VWAP Kurumsal
    src_f = _source_vwap_institutional(high, low, close, volume, atr_val)
    sources.append(src_f)

    # G) Akıllı Diverjans
    src_g = _source_smart_divergence(close, high, low, volume, atr_val)
    sources.append(src_g)

    # H) Ichimoku Bulutu
    src_h = _source_ichimoku_cloud(high, low, close, atr_val)
    sources.append(src_h)

    # I) Adaptif Momentum (KAMA)
    src_i = _source_adaptive_momentum(close, high, low, atr_val)
    sources.append(src_i)

    # J) Haber Bazlı Sinyal — v6.1'de kaldırıldı, stub nötr döner (skorlama boyutu korunur)
    src_j = _source_news_event(symbol, news_bridge)
    sources.append(src_j)

    verdict.sources = sources
    total_sources = len(sources)  # 10

    # ── Yön belirleme: çoğunluk oylaması (adaptif, 9 kaynak) ──────
    buy_sources = [s for s in sources if s.direction == "BUY" and s.score > 2.0]
    sell_sources = [s for s in sources if s.direction == "SELL" and s.score > 2.0]

    if len(buy_sources) >= min_agree:
        verdict.direction = "BUY"
        agreeing = buy_sources
    elif len(sell_sources) >= min_agree:
        verdict.direction = "SELL"
        agreeing = sell_sources
    elif len(buy_sources) > len(sell_sources) and len(buy_sources) >= 2:
        # 2/9 uyum — düşük güvenle devam (daha sıkı filtreler uygula)
        verdict.direction = "BUY"
        agreeing = buy_sources
    elif len(sell_sources) > len(buy_sources) and len(sell_sources) >= 2:
        verdict.direction = "SELL"
        agreeing = sell_sources
    else:
        verdict.direction = "NEUTRAL"
        return verdict

    verdict.agreeing_sources = len(agreeing)

    # ── Toplam skor (adaptif eşik) ──────────────────────────────
    total = sum(s.score for s in agreeing)
    verdict.total_score = total

    # v5.9.2: Skor düşük → sert blok yerine strength penalty
    if total < min_score:
        score_ratio = total / min_score if min_score > 0 else 0.0
        if score_ratio < 0.5:
            # Çok düşük skor — gerçekten sinyal yok
            verdict.should_trade = False
            verdict.reason = f"Skor çok düşük ({total:.0f} < {min_score * 0.5:.0f})"
            return verdict
        # Düşük ama kullanılabilir skor — strength penalty
        verdict.strength *= score_ratio

    # ── Sinyal gücü (ağırlıklı) ──────────────────────────────────
    weighted_sum = 0.0
    weight_total = 0.0
    for s in agreeing:
        w = SOURCE_WEIGHTS.get(s.name, 1.0)
        weighted_sum += s.confidence * w
        weight_total += w

    if weight_total > 0:
        verdict.strength = weighted_sum / weight_total
    else:
        verdict.strength = total / 100.0

    # ── Giriş fiyatı ─────────────────────────────────────────────
    verdict.entry_price = current_price

    # ── Yapısal SL ───────────────────────────────────────────────
    if verdict.direction == "BUY":
        # SL: Son swing low - buffer
        if trend.swing_lows:
            sl_base = trend.swing_lows[-1][1]
            verdict.structural_sl = sl_base - atr_val * 0.3
        else:
            verdict.structural_sl = current_price - atr_val * 1.5

        # TP: İlk direnç veya 2×risk
        risk = current_price - verdict.structural_sl
        verdict.structural_tp = current_price + max(risk * 2.0, atr_val * 2.0)

        # Yapısal TP: ilk direnç
        for lv in sorted(levels, key=lambda l: l.price):
            if lv.level_type == "resistance" and lv.price > current_price + atr_val:
                verdict.structural_tp = lv.price - atr_val * 0.1
                break

    elif verdict.direction == "SELL":
        if trend.swing_highs:
            sl_base = trend.swing_highs[-1][1]
            verdict.structural_sl = sl_base + atr_val * 0.3
        else:
            verdict.structural_sl = current_price + atr_val * 1.5

        risk = verdict.structural_sl - current_price
        verdict.structural_tp = current_price - max(risk * 2.0, atr_val * 2.0)

        for lv in sorted(levels, key=lambda l: l.price, reverse=True):
            if lv.level_type == "support" and lv.price < current_price - atr_val:
                verdict.structural_tp = lv.price + atr_val * 0.1
                break

    # ── R:R kontrolü ─────────────────────────────────────────────
    risk = abs(current_price - verdict.structural_sl)
    reward = abs(verdict.structural_tp - current_price)
    verdict.risk_reward = reward / risk if risk > 0 else 0.0

    # v5.9.2: R:R yetersiz → sert blok yerine strength penalty
    # R:R min_rr'nin altındaysa strength orantılı düşürülür
    if verdict.risk_reward < min_rr:
        if verdict.risk_reward <= 0:
            verdict.should_trade = False
            verdict.reason = f"R:R sıfır veya negatif ({verdict.risk_reward:.2f})"
            return verdict
        # Kademeli penalty: R:R = min_rr/2 ise strength × 0.5
        rr_penalty = min(verdict.risk_reward / min_rr, 1.0)
        verdict.strength *= rr_penalty
        verdict.reason = f"R:R düşük ({verdict.risk_reward:.2f} < {min_rr}) — strength ×{rr_penalty:.2f}"

    # ── Strateji tipi eşleme (SE3: genişletilmiş) ────────────────
    dominant = max(agreeing, key=lambda s: s.score)

    # Strateji → kaynak eşleme tablosu
    MR_SOURCES = {"extreme_reversion", "smart_divergence"}
    BO_SOURCES = {"compression_release", "structure_break"}
    TF_SOURCES = {"momentum_ignition", "ichimoku_cloud", "adaptive_momentum", "vwap_institutional"}

    if dominant.name in MR_SOURCES:
        verdict.strategy_type = "mean_reversion"
    elif dominant.name in BO_SOURCES:
        if any(s.name == "structure_break" and "broken" in str(s.details) for s in agreeing):
            verdict.strategy_type = "breakout"
        else:
            verdict.strategy_type = "trend_follow"
    elif dominant.name in TF_SOURCES:
        verdict.strategy_type = "trend_follow"
    else:
        verdict.strategy_type = "trend_follow"

    # ── Final karar ──────────────────────────────────────────────
    verdict.should_trade = True
    source_names = ", ".join(f"{s.name}({s.score:.0f})" for s in agreeing)
    verdict.reason = (
        f"ÜSTAT-SE: {verdict.direction} {len(agreeing)}/{total_sources} kaynak uyumlu "
        f"[{source_names}] "
        f"skor={total:.0f} R:R={verdict.risk_reward:.1f} vol={vol_regime} rejim={regime_type or 'N/A'}"
    )

    return verdict
