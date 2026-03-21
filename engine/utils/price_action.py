"""Price Action analizi — Yapısal farkındalık modülü (v14.2 FAZ 1).

Destek/Direnç tespiti, bar pattern tanıma, trend yapısı analizi
ve confluence skor hesaplaması.

OĞUL'un "bilinçli işlemci" dönüşümünün temel taşı.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from engine.utils.indicators import atr as calc_atr, ema, sma


# ═════════════════════════════════════════════════════════════════════
#  VERİ YAPILARI
# ═════════════════════════════════════════════════════════════════════

@dataclass
class Level:
    """Destek veya direnç seviyesi."""
    price: float
    strength: int          # Kaç kez test edildi
    level_type: str        # "support" | "resistance"
    last_touch_idx: int    # Son temas bar indeksi

@dataclass
class BarPattern:
    """Mum pattern tespiti."""
    name: str              # pin_bar, engulfing, doji, hammer, shooting_star, inside_bar
    direction: str         # "bullish" | "bearish"
    strength: float        # 0.0-1.0
    bar_index: int         # Tespit edilen bar

@dataclass
class TrendStructure:
    """Trend yapısı analizi."""
    direction: str         # "up" | "down" | "range"
    swing_highs: list[tuple[int, float]] = field(default_factory=list)  # (idx, price)
    swing_lows: list[tuple[int, float]] = field(default_factory=list)
    last_break_level: float = 0.0          # Son kırılan yapısal seviye
    trend_strength: float = 0.0            # 0.0-1.0

@dataclass
class ConfluenceResult:
    """Confluence skor sonucu."""
    total_score: float          # 0-100
    level_score: float          # 0-25
    pattern_score: float        # 0-20
    indicator_score: float      # 0-25
    volume_score: float         # 0-15
    trend_score: float          # 0-15
    details: dict = field(default_factory=dict)
    can_enter: bool = False     # score >= 60


# ═════════════════════════════════════════════════════════════════════
#  SABİTLER
# ═════════════════════════════════════════════════════════════════════

# Swing tespiti
SWING_ORDER: int = 3              # Fractal: N bar sol + N bar sağ
LEVEL_MERGE_ATR_MULT: float = 0.5 # Yakın seviyeler birleştirme eşiği

# Bar pattern eşikleri
DOJI_BODY_PCT: float = 0.10       # body/range < %10 = doji
PIN_BAR_WICK_RATIO: float = 2.0   # kuyruk/gövde >= 2.0
ENGULFING_MIN_RATIO: float = 1.2  # engulfing gövde oranı

# Trend yapısı
TREND_MIN_SWINGS: int = 3         # Min swing sayısı trend tespiti için
HH_HL_TOLERANCE: float = 0.001   # Higher High/Low tolerans (%)

# Confluence — rejim-bazlı eşikler (v2 revizyon)
# ESKİ: CONFLUENCE_MIN_ENTRY = 60.0 (sabit, tüm rejimlerde aynı)
# YENİ: Rejime göre dinamik eşik. Trend'te düşük (zaten SE2+BABA teyitli),
#        Range'de orta, Volatile'da yüksek.
CONFLUENCE_THRESHOLDS: dict[str, float] = {
    "TREND": 40.0,      # Trend zaten SE2 + BABA tarafından doğrulanmış
    "RANGE": 50.0,      # Orta düzey doğrulama
    "VOLATILE": 65.0,   # Yüksek eşik — korunma
    "OLAY": 999.0,      # OLAY rejiminde işlem yapılmaz
}
CONFLUENCE_MIN_ENTRY: float = 50.0  # Fallback (rejim bilinmiyorsa)


# ═════════════════════════════════════════════════════════════════════
#  DESTEK / DİRENÇ TESPİTİ
# ═════════════════════════════════════════════════════════════════════

def find_swing_points(
    high: np.ndarray,
    low: np.ndarray,
    order: int = SWING_ORDER,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Fractal yöntemiyle swing high/low tespiti.

    Args:
        high: High fiyat serisi.
        low: Low fiyat serisi.
        order: Her iki tarafta kaç bar kontrol edilecek.

    Returns:
        (swing_highs, swing_lows) — her biri [(index, price), ...] listesi.
    """
    n = len(high)
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    for i in range(order, n - order):
        # NaN kontrolü — karşılaştırma yapılamaz
        if np.isnan(high[i]) or np.isnan(low[i]):
            continue

        # Swing High: i'deki high, sol ve sağdaki N bar'dan büyük
        is_swing_high = True
        for j in range(1, order + 1):
            if np.isnan(high[i - j]) or np.isnan(high[i + j]):
                is_swing_high = False
                break
            if high[i] <= high[i - j] or high[i] <= high[i + j]:
                is_swing_high = False
                break
        if is_swing_high:
            swing_highs.append((i, float(high[i])))

        # Swing Low: i'deki low, sol ve sağdaki N bar'dan küçük
        is_swing_low = True
        for j in range(1, order + 1):
            if np.isnan(low[i - j]) or np.isnan(low[i + j]):
                is_swing_low = False
                break
            if low[i] >= low[i - j] or low[i] >= low[i + j]:
                is_swing_low = False
                break
        if is_swing_low:
            swing_lows.append((i, float(low[i])))

    return swing_highs, swing_lows


def find_support_resistance(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr_val: float,
    order: int = SWING_ORDER,
    max_levels: int = 10,
) -> list[Level]:
    """Destek ve direnç seviyelerini tespit et.

    Fractal swing noktalarını bulur, yakın seviyeleri birleştirir
    ve test sayısına göre güç atar.

    Args:
        high, low, close: OHLC verileri.
        atr_val: Güncel ATR değeri.
        order: Swing fractal order.
        max_levels: Maksimum seviye sayısı.

    Returns:
        Level listesi (güçten zayıfa sıralı).
    """
    swing_highs, swing_lows = find_swing_points(high, low, order)

    # Tüm potansiyel seviyeleri topla
    raw_levels: list[tuple[float, str, int]] = []  # (price, type, idx)
    for idx, price in swing_highs:
        raw_levels.append((price, "resistance", idx))
    for idx, price in swing_lows:
        raw_levels.append((price, "support", idx))

    if not raw_levels:
        return []

    # Yakın seviyeleri birleştir (merge_distance = 0.5×ATR)
    merge_dist = atr_val * LEVEL_MERGE_ATR_MULT if atr_val > 0 else 0.01
    raw_levels.sort(key=lambda x: x[0])

    merged: list[Level] = []
    i = 0
    while i < len(raw_levels):
        cluster_prices = [raw_levels[i][0]]
        cluster_type = raw_levels[i][1]
        last_idx = raw_levels[i][2]
        j = i + 1
        while j < len(raw_levels) and raw_levels[j][0] - cluster_prices[0] <= merge_dist:
            cluster_prices.append(raw_levels[j][0])
            last_idx = max(last_idx, raw_levels[j][2])
            j += 1
        avg_price = float(np.mean(cluster_prices))
        merged.append(Level(
            price=avg_price,
            strength=len(cluster_prices),
            level_type=cluster_type,
            last_touch_idx=last_idx,
        ))
        i = j

    # Güçten zayıfa sırala, max_levels ile sınırla
    merged.sort(key=lambda lv: lv.strength, reverse=True)
    return merged[:max_levels]


def nearest_level(
    levels: list[Level],
    price: float,
    level_type: str,
    atr_val: float,
    max_distance_atr: float = 3.0,
) -> Level | None:
    """Verilen fiyata en yakın destek veya direnç seviyesini bul.

    Args:
        levels: Seviye listesi.
        price: Güncel fiyat.
        level_type: "support" veya "resistance".
        atr_val: ATR değeri.
        max_distance_atr: Maksimum mesafe (ATR çarpanı).

    Returns:
        En yakın Level veya None.
    """
    best: Level | None = None
    best_dist = float("inf")
    max_dist = atr_val * max_distance_atr if atr_val > 0 else float("inf")

    for lv in levels:
        if lv.level_type != level_type:
            continue
        dist = abs(lv.price - price)
        if dist < best_dist and dist <= max_dist:
            best_dist = dist
            best = lv

    return best


def price_near_level(
    price: float,
    levels: list[Level],
    atr_val: float,
    proximity_atr: float = 1.0,
) -> tuple[bool, Level | None]:
    """Fiyat herhangi bir seviyeye yakın mı kontrol et.

    Returns:
        (yakın_mı, en_yakın_seviye)
    """
    if not levels or atr_val <= 0:
        return False, None

    for lv in levels:
        if abs(price - lv.price) <= atr_val * proximity_atr:
            return True, lv
    return False, None


# ═════════════════════════════════════════════════════════════════════
#  BAR PATTERN TANIMA
# ═════════════════════════════════════════════════════════════════════

def detect_bar_patterns(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr_val: float,
) -> list[BarPattern]:
    """Son 3 bar'da mum patternleri tespit et.

    Tanınan patternler:
        - Pin Bar (bullish/bearish)
        - Engulfing (bullish/bearish)
        - Doji
        - Hammer / Shooting Star
        - Inside Bar

    Returns:
        Tespit edilen BarPattern listesi (güçten zayıfa).
    """
    patterns: list[BarPattern] = []
    n = len(close)
    if n < 3 or atr_val <= 0:
        return patterns

    # Son bar verileri
    o1, h1, l1, c1 = float(open_[-1]), float(high[-1]), float(low[-1]), float(close[-1])
    o2, h2, l2, c2 = float(open_[-2]), float(high[-2]), float(low[-2]), float(close[-2])

    body1 = abs(c1 - o1)
    range1 = h1 - l1
    body2 = abs(c2 - o2)
    range2 = h2 - l2

    if range1 <= 0:
        range1 = 0.0001
    if range2 <= 0:
        range2 = 0.0001

    upper_wick1 = h1 - max(o1, c1)
    lower_wick1 = min(o1, c1) - l1

    # ── Doji ───────────────────────────────────────────────────────
    body_pct = body1 / range1
    if body_pct < DOJI_BODY_PCT and range1 >= atr_val * 0.3:
        patterns.append(BarPattern(
            name="doji",
            direction="neutral",
            strength=0.5,
            bar_index=n - 1,
        ))

    # ── Pin Bar (Bullish) ──────────────────────────────────────────
    # Uzun alt kuyruk, kısa gövde, boğa yönlü
    if lower_wick1 >= body1 * PIN_BAR_WICK_RATIO and lower_wick1 >= upper_wick1 * 1.5:
        strength = min(lower_wick1 / range1, 1.0) * 0.8
        patterns.append(BarPattern(
            name="pin_bar",
            direction="bullish",
            strength=strength,
            bar_index=n - 1,
        ))

    # ── Pin Bar (Bearish) ──────────────────────────────────────────
    # Uzun üst kuyruk, kısa gövde, ayı yönlü
    if upper_wick1 >= body1 * PIN_BAR_WICK_RATIO and upper_wick1 >= lower_wick1 * 1.5:
        strength = min(upper_wick1 / range1, 1.0) * 0.8
        patterns.append(BarPattern(
            name="pin_bar",
            direction="bearish",
            strength=strength,
            bar_index=n - 1,
        ))

    # ── Hammer (Bullish) ───────────────────────────────────────────
    # Düşüş sonrası alt kuyruklu mum (c2 < o2 iken c1 > o1)
    if c2 < o2 and c1 >= o1:
        if lower_wick1 >= body1 * 1.5 and upper_wick1 < body1 * 0.5:
            patterns.append(BarPattern(
                name="hammer",
                direction="bullish",
                strength=0.7,
                bar_index=n - 1,
            ))

    # ── Shooting Star (Bearish) ────────────────────────────────────
    # Yükseliş sonrası üst kuyruklu mum (c2 > o2 iken c1 < o1)
    if c2 > o2 and c1 <= o1:
        if upper_wick1 >= body1 * 1.5 and lower_wick1 < body1 * 0.5:
            patterns.append(BarPattern(
                name="shooting_star",
                direction="bearish",
                strength=0.7,
                bar_index=n - 1,
            ))

    # ── Bullish Engulfing ──────────────────────────────────────────
    if c2 < o2 and c1 > o1:  # Önceki ayı, son boğa
        if body1 > body2 * ENGULFING_MIN_RATIO and c1 > o2 and o1 < c2:
            strength = min(body1 / body2, 2.0) * 0.5
            patterns.append(BarPattern(
                name="engulfing",
                direction="bullish",
                strength=min(strength, 1.0),
                bar_index=n - 1,
            ))

    # ── Bearish Engulfing ──────────────────────────────────────────
    if c2 > o2 and c1 < o1:  # Önceki boğa, son ayı
        if body1 > body2 * ENGULFING_MIN_RATIO and o1 > c2 and c1 < o2:
            strength = min(body1 / body2, 2.0) * 0.5
            patterns.append(BarPattern(
                name="engulfing",
                direction="bearish",
                strength=min(strength, 1.0),
                bar_index=n - 1,
            ))

    # ── Inside Bar ─────────────────────────────────────────────────
    if h1 <= h2 and l1 >= l2:
        patterns.append(BarPattern(
            name="inside_bar",
            direction="neutral",
            strength=0.4,
            bar_index=n - 1,
        ))

    # Güçten zayıfa sırala
    patterns.sort(key=lambda p: p.strength, reverse=True)
    return patterns


def pattern_confirms_direction(
    patterns: list[BarPattern],
    direction: str,
) -> tuple[bool, float]:
    """Patternler verilen yönü destekliyor mu?

    Args:
        patterns: Tespit edilen patternler.
        direction: "BUY" veya "SELL".

    Returns:
        (destekliyor_mu, en_güçlü_pattern_strength)
    """
    if not patterns:
        return True, 0.0  # Pattern yoksa engel yok

    bullish_map = {"bullish", "neutral"}
    bearish_map = {"bearish", "neutral"}
    target_dirs = bullish_map if direction == "BUY" else bearish_map

    # Çelişen pattern var mı?
    conflicting = [p for p in patterns if p.direction not in target_dirs]
    supporting = [p for p in patterns if p.direction in target_dirs and p.direction != "neutral"]

    if conflicting and not supporting:
        return False, max(p.strength for p in conflicting)

    best_support = max((p.strength for p in supporting), default=0.0)
    return True, best_support


# ═════════════════════════════════════════════════════════════════════
#  TREND YAPISI ANALİZİ
# ═════════════════════════════════════════════════════════════════════

def analyze_trend_structure(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    order: int = SWING_ORDER,
) -> TrendStructure:
    """Higher High/Higher Low ve Lower High/Lower Low analizi.

    Trend yapısı:
        UP:   HH + HL (en az 3 swing)
        DOWN: LH + LL (en az 3 swing)
        RANGE: Belirsiz veya yetersiz swing

    Returns:
        TrendStructure nesnesi.
    """
    swing_highs, swing_lows = find_swing_points(high, low, order)

    result = TrendStructure(direction="range", swing_highs=swing_highs, swing_lows=swing_lows)

    if len(swing_highs) < TREND_MIN_SWINGS or len(swing_lows) < TREND_MIN_SWINGS:
        return result

    # Son N swing'i analiz et
    recent_highs = [p for _, p in swing_highs[-TREND_MIN_SWINGS:]]
    recent_lows = [p for _, p in swing_lows[-TREND_MIN_SWINGS:]]

    # Higher High / Higher Low sayımı
    hh_count = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] > recent_highs[i - 1] * (1 - HH_HL_TOLERANCE))
    hl_count = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] > recent_lows[i - 1] * (1 - HH_HL_TOLERANCE))

    # Lower High / Lower Low sayımı
    lh_count = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] < recent_highs[i - 1] * (1 + HH_HL_TOLERANCE))
    ll_count = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] < recent_lows[i - 1] * (1 + HH_HL_TOLERANCE))

    max_pairs = len(recent_highs) - 1
    if max_pairs <= 0:
        return result

    up_score = (hh_count + hl_count) / (max_pairs * 2)
    down_score = (lh_count + ll_count) / (max_pairs * 2)

    if up_score >= 0.6:
        result.direction = "up"
        result.trend_strength = min(up_score, 1.0)
        # Son swing low = trend kırılma seviyesi
        if swing_lows:
            result.last_break_level = swing_lows[-1][1]
    elif down_score >= 0.6:
        result.direction = "down"
        result.trend_strength = min(down_score, 1.0)
        # Son swing high = trend kırılma seviyesi
        if swing_highs:
            result.last_break_level = swing_highs[-1][1]
    else:
        result.direction = "range"
        result.trend_strength = 0.0

    return result


def trend_supports_direction(
    trend: TrendStructure,
    direction: str,
) -> tuple[bool, float]:
    """Trend yapısı verilen yönü destekliyor mu?

    Args:
        trend: Trend yapısı analiz sonucu.
        direction: "BUY" veya "SELL".

    Returns:
        (destekliyor_mu, trend_strength)
    """
    if trend.direction == "range":
        return True, 0.0  # Range'de her iki yön de serbest (MR için)

    if direction == "BUY" and trend.direction == "up":
        return True, trend.trend_strength
    if direction == "SELL" and trend.direction == "down":
        return True, trend.trend_strength

    # Ters yön — trend yapısına karşı
    return False, trend.trend_strength


# ═════════════════════════════════════════════════════════════════════
#  CONFLUENCE SKOR HESAPLAMA
# ═════════════════════════════════════════════════════════════════════

def calculate_confluence(
    direction: str,
    price: float,
    levels: list[Level],
    patterns: list[BarPattern],
    trend: TrendStructure,
    atr_val: float,
    # Gösterge bilgileri
    adx_val: float = 0.0,
    rsi_val: float = 50.0,
    macd_hist: float = 0.0,
    ema_fast: float = 0.0,
    ema_slow: float = 0.0,
    # Hacim bilgisi
    volume_ratio: float = 1.0,  # current_vol / avg_vol
    # v2: Rejim bilgisi (eşik seçimi için)
    regime_type: str = "",  # "TREND", "RANGE", "VOLATILE", "OLAY"
) -> ConfluenceResult:
    """Giriş kararı için confluence skor hesapla.

    Skor dağılımı (100 üzerinden):
        - Seviye yakınlığı:    0-25 puan
        - Bar pattern:         0-10 puan (v2: 20→10)
        - Gösterge uyumu:      0-35 puan (v2: 25→35)
        - Hacim kalitesi:      0-15 puan
        - Trend yapısı:        0-15 puan

    Args:
        direction: "BUY" veya "SELL".
        price: Giriş fiyatı.
        levels: Destek/direnç seviyeleri.
        patterns: Bar patternleri.
        trend: Trend yapısı.
        atr_val: ATR değeri.
        adx_val: ADX değeri.
        rsi_val: RSI değeri.
        macd_hist: MACD histogram değeri.
        ema_fast: Hızlı EMA.
        ema_slow: Yavaş EMA.
        volume_ratio: Hacim / ortalama hacim.

    Returns:
        ConfluenceResult nesnesi.
    """
    details: dict = {}

    # ── 1. Seviye Yakınlığı (0-25) ──────────────────────────────
    level_score = 0.0
    if levels and atr_val > 0:
        if direction == "BUY":
            # BUY: Desteğe yakınlık = iyi
            near, lv = price_near_level(price, [l for l in levels if l.level_type == "support"], atr_val, 1.5)
            if near and lv:
                proximity = 1.0 - abs(price - lv.price) / (atr_val * 1.5)
                level_score = proximity * 15 + min(lv.strength * 2.5, 10)
                details["support_level"] = lv.price
            # BUY: Dirence yakınlık = kötü (ceza)
            near_r, lv_r = price_near_level(price, [l for l in levels if l.level_type == "resistance"], atr_val, 1.0)
            if near_r and lv_r:
                level_score = max(level_score - 10, 0)
                details["resistance_warning"] = lv_r.price
        else:
            # SELL: Dirence yakınlık = iyi
            near, lv = price_near_level(price, [l for l in levels if l.level_type == "resistance"], atr_val, 1.5)
            if near and lv:
                proximity = 1.0 - abs(price - lv.price) / (atr_val * 1.5)
                level_score = proximity * 15 + min(lv.strength * 2.5, 10)
                details["resistance_level"] = lv.price
            # SELL: Desteğe yakınlık = kötü (ceza)
            near_s, lv_s = price_near_level(price, [l for l in levels if l.level_type == "support"], atr_val, 1.0)
            if near_s and lv_s:
                level_score = max(level_score - 10, 0)
                details["support_warning"] = lv_s.price

    level_score = min(level_score, 25.0)

    # ── 2. Bar Pattern (0-10) ────────────────────────────────────
    # v2 revizyon: 20→10 (VİOP M15'te pattern %88 sıfır, ağırlık düşürüldü)
    pattern_score = 0.0
    confirms, pat_str = pattern_confirms_direction(patterns, direction)
    if confirms:
        pattern_score = pat_str * 10.0
    else:
        # Çelişen pattern: ceza
        pattern_score = -pat_str * 5.0
    details["pattern_confirms"] = confirms
    pattern_score = max(min(pattern_score, 10.0), 0.0)

    # ── 3. Gösterge Uyumu (0-35) ──────────────────────────────────
    # v2 revizyon: 25→35 (Pattern'den aktarılan 10 puan burada)
    # VİOP'ta indikatörler pattern'den daha güvenilir sinyal veriyor
    indicator_score = 0.0

    # ADX gücü (0-12) — ESKİ: 0-8
    if adx_val > 20:
        indicator_score += min((adx_val - 20) / 20.0 * 12, 12)

    # RSI uyumu (0-9) — ESKİ: 0-7
    if direction == "BUY":
        if 30 < rsi_val < 60:  # Aşırı almayı geçmemiş, geri çekilme bölgesi
            indicator_score += 7.0
        elif rsi_val <= 30:     # Aşırı satış = MR fırsatı
            indicator_score += 9.0
        elif rsi_val > 70:      # Aşırı alım = risk
            indicator_score -= 3.0
    else:
        if 40 < rsi_val < 70:
            indicator_score += 7.0
        elif rsi_val >= 70:
            indicator_score += 9.0
        elif rsi_val < 30:
            indicator_score -= 3.0

    # MACD uyumu (0-7) — ESKİ: 0-5
    if direction == "BUY" and macd_hist > 0:
        indicator_score += min(abs(macd_hist) / (atr_val * 0.3) * 7, 7) if atr_val > 0 else 0
    elif direction == "SELL" and macd_hist < 0:
        indicator_score += min(abs(macd_hist) / (atr_val * 0.3) * 7, 7) if atr_val > 0 else 0

    # EMA uyumu (0-7) — ESKİ: 0-5
    if direction == "BUY" and ema_fast > ema_slow:
        indicator_score += 7.0
    elif direction == "SELL" and ema_fast < ema_slow:
        indicator_score += 7.0

    indicator_score = max(min(indicator_score, 35.0), 0.0)

    # ── 4. Hacim Kalitesi (0-15) ──────────────────────────────────
    # v2 revizyon: Sabit eşik yerine kademeli puanlama.
    # ESKİ: volume_ratio >= 2.0 → 15, >= 1.5 → 12, >= 1.0 → 8, >= 0.7 → 4
    # YENİ: Daha erişilebilir eşikler (VİOP düşük hacim gerçeğine uygun)
    volume_score = 0.0
    if volume_ratio >= 1.8:
        volume_score = 15.0
    elif volume_ratio >= 1.3:
        volume_score = 12.0
    elif volume_ratio >= 0.8:
        volume_score = 8.0
    elif volume_ratio >= 0.5:
        volume_score = 4.0
    else:
        volume_score = 0.0
    details["volume_ratio"] = volume_ratio

    # ── 5. Trend Yapısı (0-15) ────────────────────────────────────
    trend_score = 0.0
    trend_ok, t_str = trend_supports_direction(trend, direction)
    if trend_ok:
        trend_score = t_str * 15.0
    else:
        # Trende karşı: ceza
        trend_score = -t_str * 8.0
    trend_score = max(min(trend_score, 15.0), 0.0)
    details["trend_direction"] = trend.direction
    details["trend_supports"] = trend_ok

    # ── Toplam ────────────────────────────────────────────────────
    total = level_score + pattern_score + indicator_score + volume_score + trend_score

    # v2: Rejim-bazlı eşik (ESKİ: sabit 60.0)
    threshold = CONFLUENCE_THRESHOLDS.get(regime_type, CONFLUENCE_MIN_ENTRY)

    return ConfluenceResult(
        total_score=max(total, 0.0),
        level_score=level_score,
        pattern_score=pattern_score,
        indicator_score=indicator_score,
        volume_score=volume_score,
        trend_score=trend_score,
        details=details,
        can_enter=total >= threshold,
    )


# ═════════════════════════════════════════════════════════════════════
#  YARDIMCI FONKSİYONLAR
# ═════════════════════════════════════════════════════════════════════

def get_structural_sl(
    direction: str,
    price: float,
    swing_lows: list[tuple[int, float]],
    swing_highs: list[tuple[int, float]],
    atr_val: float,
    buffer_atr_mult: float = 0.3,
) -> float | None:
    """Yapısal seviyeye dayalı SL hesapla.

    BUY: Son swing low - buffer
    SELL: Son swing high + buffer

    Returns:
        Yapısal SL fiyatı veya None.
    """
    if direction == "BUY" and swing_lows:
        sl_base = swing_lows[-1][1]
        sl = sl_base - atr_val * buffer_atr_mult
        if sl < price:
            return sl
    elif direction == "SELL" and swing_highs:
        sl_base = swing_highs[-1][1]
        sl = sl_base + atr_val * buffer_atr_mult
        if sl > price:
            return sl
    return None


def get_structural_tp(
    direction: str,
    price: float,
    levels: list[Level],
    atr_val: float,
    min_rr: float = 1.5,
    sl: float = 0.0,
) -> float | None:
    """Yapısal seviyeye dayalı TP hesapla.

    BUY: İlk direnç seviyesi (min R:R karşılıyorsa)
    SELL: İlk destek seviyesi (min R:R karşılıyorsa)

    Returns:
        Yapısal TP fiyatı veya None.
    """
    risk = abs(price - sl) if sl > 0 else atr_val
    if risk <= 0:
        return None

    if direction == "BUY":
        targets = sorted(
            [lv for lv in levels if lv.level_type == "resistance" and lv.price > price],
            key=lambda lv: lv.price,
        )
    else:
        targets = sorted(
            [lv for lv in levels if lv.level_type == "support" and lv.price < price],
            key=lambda lv: lv.price,
            reverse=True,
        )

    for t in targets:
        reward = abs(t.price - price)
        if reward / risk >= min_rr:
            return t.price

    return None


def normalize_atr(atr_arr: np.ndarray, percentile: float = 50.0) -> float:
    """ATR'yi percentile ile normalize et (spike koruması).

    Mevcut ATR yerine 20-bar penceresinin median'ını kullanarak
    spike'lardan korunma sağlar.

    Returns:
        Normalize ATR değeri.
    """
    valid = atr_arr[~np.isnan(atr_arr)]
    if len(valid) < 5:
        return float(valid[-1]) if len(valid) > 0 else 0.0
    return float(np.percentile(valid[-20:], percentile))
