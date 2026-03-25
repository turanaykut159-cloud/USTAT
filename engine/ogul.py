"""OĞUL — Sinyal üretimi ve emir state-machine (v12.0).

3 sinyal stratejisi:
    TREND_FOLLOW   — EMA(20)×EMA(50) crossover + ADX>25 + MACD 2-bar
                     M15 giriş + H1 onay, trailing stop 1.5×ATR
    MEAN_REVERSION — RSI(14) aşırı bölge + BB bant teması + ADX<20
                     SL: BB bant ± 1 ATR, TP: BB orta bant
    BREAKOUT       — 20-bar high/low kırılımı + hacim>1.5× + ATR genişleme
                     SL: entry ± 1.5×ATR, TP: %100 range genişliği

Rejim → Aktif sinyaller:
    TREND    → trend follow aktif, mean reversion deaktif
    RANGE    → mean reversion aktif, breakout bekle
    VOLATILE → TÜM sinyaller durur
    OLAY     → SİSTEM PAUSE
"""

from __future__ import annotations

import math
import threading
import time as _time
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np

from engine.config import Config
from engine.database import Database
from engine.logger import get_logger
from engine.models.regime import Regime, RegimeType
from engine.models.risk import RiskParams
from engine.models.signal import Signal, SignalType, StrategyType
from engine.models.trade import Trade, TradeState
from engine.mt5_bridge import MT5Bridge, WATCHED_SYMBOLS
from engine.utils.helpers import last_valid, last_n_valid
from engine.utils.indicators import (
    adx as calc_adx,
    atr as calc_atr,
    ema,
    bollinger_bands,
    rsi as calc_rsi,
    macd as calc_macd,
    bb_kc_squeeze,
    williams_r as calc_williams_r,
)
from engine.utils.price_action import (
    find_support_resistance,
    detect_bar_patterns,
    pattern_confirms_direction,
    analyze_trend_structure,
    trend_supports_direction,
    calculate_confluence,
    get_structural_sl,
    get_structural_tp,
    CONFLUENCE_MIN_ENTRY,
    CONFLUENCE_THRESHOLDS,
)
from engine.utils.multi_tf import (
    analyze_multi_tf,
    h1_trend_filter,
    m5_entry_quality,
)
from engine.utils.signal_engine import (
    generate_signal as se2_generate_signal,
    SignalVerdict,
)
from engine.baba import VIOP_EXPIRY_DATES
from engine.top5_selection import Top5Selector
from engine.utils.time_utils import ALL_HOLIDAYS

logger = get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════
#  SABİTLER
# ═════════════════════════════════════════════════════════════════════

# ── Trend Follow ──────────────────────────────────────────────────
TF_EMA_FAST:          int   = 20
TF_EMA_SLOW:          int   = 50
TF_ADX_THRESHOLD:     float = 25.0   # eski eşik (referans)
TF_ADX_HARD:          float = 28.0   # FAZ 2.6: kesin trend
TF_ADX_SOFT:          float = 22.0   # FAZ 2.6: kesin range
TF_MACD_CONFIRM_BARS: int   = 2     # histogram 2 bar aynı işaret
TF_SL_ATR_MULT:       float = 1.5   # entry ± 1.5×ATR (fallback)
TF_TP_ATR_MULT:       float = 2.0   # 2×ATR
TF_TRAILING_ATR_MULT: float = 1.5   # trailing stop 1.5×ATR

# ── Mean Reversion ────────────────────────────────────────────────
MR_RSI_PERIOD:    int   = 14
MR_RSI_OVERSOLD:  float = 20.0
MR_RSI_OVERBOUGHT: float = 80.0
MR_ADX_THRESHOLD: float = 25.0      # eski eşik (referans)
MR_ADX_HARD:      float = 28.0      # FAZ 2.6: kesin trend (MR engel)
MR_ADX_SOFT:      float = 22.0      # FAZ 2.6: kesin range (MR serbest)
MR_BB_PERIOD:     int   = 20
MR_BB_STD:        float = 2.0
MR_SL_ATR_MULT:   float = 1.0       # BB bant ± 1 ATR

# ── Breakout ──────────────────────────────────────────────────────
BO_LOOKBACK:       int   = 20       # 20-bar high/low
BO_VOLUME_MULT:    float = 1.5      # hacim > ort × 1.5
BO_ATR_EXPANSION:  float = 1.2      # ATR genişleme oranı
BO_SL_ATR_MULT:    float = 1.5      # Breakout SL = entry ± 1.5 × ATR
BO_TRAILING_ATR_MULT: float = 2.0   # trailing stop: fiyat ± 2×ATR (trend follow'dan geniş)
BO_REENTRY_BARS: int = 3            # son 3 bar range içine dönmüşse = false breakout

# ── Genel ─────────────────────────────────────────────────────────
SWING_LOOKBACK:  int = 10           # swing high/low arama barı
ATR_PERIOD:      int = 14
MIN_BARS_M15:    int = 60           # M15 için min bar
MIN_BARS_M5:     int = 60           # M5 sinyal tetikleme için min bar (v5.7)
MIN_BARS_H1:     int = 30           # H1 onay için min bar
CONTRACT_SIZE:   float = 100.0      # VİOP çarpanı (varsayılan)

# ── State Machine ────────────────────────────────────────────────
ORDER_TIMEOUT_SEC: int       = 15      # v14: 5→15 (C sınıfı düşük likidite)
MAX_SLIPPAGE_ATR_MULT: float = 0.5     # max slippage = 0.5 × ATR
MAX_LOT_PER_CONTRACT: float  = 1.0     # test süreci: kontrat başına max 1 lot
# v5.8/CEO-FAZ2: Varsayılan değer — config'den override edilir (Ogul.__init__).
# config/default.json → engine.margin_reserve_pct
MARGIN_RESERVE_PCT_DEFAULT: float = 0.20
MAX_CONCURRENT: int          = 5       # test süreci: eş zamanlı maks 5 pozisyon
TRADING_OPEN: time           = time(9, 40)   # işlem başlangıç (açılıştan 10dk sonra)
TRADING_CLOSE: time          = time(17, 50)  # işlem bitiş (kapanıştan 25dk önce)

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

# ── Top 5 Kontrat Seçimi (v13.0: ÜSTAT'tan taşındı) ────────────────
SELECTION_START: time       = time(9, 15)       # ilk seçim saati
REFRESH_INTERVAL_MIN: int   = 30               # güncelleme aralığı (dk)

# ── Top 5 Ağırlıklar ──────────────────────────────────────────────
W_TECHNICAL:  float = 0.35    # teknik sinyal gücü
W_VOLUME:     float = 0.20    # hacim kalitesi
W_SPREAD:     float = 0.15    # spread durumu
W_HISTORICAL: float = 0.20    # tarihsel başarı
W_VOLATILITY: float = 0.10    # volatilite uyumu

# ── Winsorization ───────────────────────────────────────────────────
WINSOR_LOWER_PCT: float = 1.0    # 1. percentile
WINSOR_UPPER_PCT: float = 99.0   # 99. percentile

# ── Top 5 Teknik skor ─────────────────────────────────────────────
TECH_EMA_FAST: int = 20
TECH_EMA_SLOW: int = 50
TECH_ADX_PERIOD: int = 14
TECH_RSI_PERIOD: int = 14
TECH_ATR_PERIOD: int = 14
TECH_BB_PERIOD: int = 20
TECH_BB_STD: float = 2.0
TECH_MIN_BARS: int = 60         # M15 minimum bar sayısı

# ── Top 5 Hacim skor ──────────────────────────────────────────────
VOL_LOOKBACK: int = 20          # 20-bar ortalama
VOL_MAX_RATIO: float = 3.0     # oran >= 3 → 100 puan

# ── Top 5 Tarihsel başarı ─────────────────────────────────────────
HIST_LOOKBACK_DAYS: int = 30    # son 30 gün

# ── Top 5 Volatilite uyumu ────────────────────────────────────────
VOLFIT_TREND_IDEAL: float = 0.012
VOLFIT_RANGE_IDEAL: float = 0.005
VOLFIT_TOLERANCE: float = 0.010

# ── Vade geçişi ─────────────────────────────────────────────────────
EXPIRY_NO_NEW_TRADE_DAYS: int = 3   # vade bitişinden 3 iş günü öncesi
EXPIRY_CLOSE_DAYS: int = 1          # vade bitişinden 1 iş günü öncesi
EXPIRY_OBSERVATION_DAYS: int = 2    # yeni vadede ilk 2 gün gözlem

# ═════════════════════════════════════════════════════════════════════
#  EVRENSEL POZİSYON YÖNETİMİ SABİTLERİ
# ═════════════════════════════════════════════════════════════════════

# Feature flag — True: evrensel yönetim, False: eski strateji bazlı
USE_UNIVERSAL_MANAGEMENT: bool = True

# ── Breakeven eşikleri (likidite sınıfı bazlı) ─────────────────────
BE_ATR_BY_CLASS: dict[str, float] = {
    "A": 1.0,    # kâr ≥ 1×ATR → breakeven
    "B": 1.3,    # kâr ≥ 1.3×ATR → breakeven
    "C": 1.5,    # kâr ≥ 1.5×ATR → breakeven
}

# ── TP1 (yarım kapanış) ────────────────────────────────────────────
TP1_ATR_MULT: float = 1.5          # kâr ≥ 1.5×ATR → toplam pozisyonun yarısı kapatılır

# ── Trailing Stop (EMA20 bazlı, likidite sınıfı ATR çarpanı) ──────
TRAIL_ATR_BY_CLASS: dict[str, float] = {
    "A": 1.0,    # EMA20 − 1.0×ATR
    "B": 1.3,    # EMA20 − 1.3×ATR
    "C": 1.5,    # EMA20 − 1.5×ATR
}

# ── Giriş ───────────────────────────────────────────────────────────
ENTRY_LOT_FRACTION: float = 0.5    # ilk giriş: hesaplanan lotun %50'si
LIMIT_OFFSET_ATR: float = 0.25     # limit emir ofset: mum kapanışından 0.25×ATR geri

# ── Geri çekilme toleransı (volatilite bazlı dinamik) ──────────────
PULLBACK_LOW_VOL: float = 0.20     # düşük volatilite: en yüksek kârın %20'si
PULLBACK_NORMAL_VOL: float = 0.30  # normal: %30
PULLBACK_HIGH_VOL: float = 0.40    # yüksek volatilite: %40
PULLBACK_LOW_THRESHOLD: float = 0.005    # ATR/fiyat < %0.5 = düşük vol
PULLBACK_HIGH_THRESHOLD: float = 0.012   # ATR/fiyat > %1.2 = yüksek vol

# ── Maliyetlendirme (cost averaging) ───────────────────────────────
AVG_PULLBACK_ATR: float = 1.0      # geri çekilme ≥ 1×ATR gerekli
AVG_MAX_RISK_MULT: float = 1.2     # toplam risk ≤ başlangıcın %120'si

# ── Zaman kuralları ─────────────────────────────────────────────────
FLAT_CANDLE_COUNT: int = 8          # 8 × M15 = 2 saat
FLAT_ATR_MULT: float = 0.5         # range < 0.5×ATR = yatay
LUNCH_START: time = time(12, 30)    # öğle arası başlangıç
LUNCH_END: time = time(14, 0)       # öğle arası bitiş
LAST_45_MIN: time = time(17, 0)     # son 45 dakika
LUNCH_TRAIL_WIDEN: float = 1.3      # öğle arası trailing %30 genişlet

# ── Gelişmiş risk kuralları ─────────────────────────────────────────
DAILY_LOSS_STOP_PCT: float = 0.03           # günlük zarar ≥ equity'nin %3'ü → dur
SYMBOL_CONSECUTIVE_LOSS_LIMIT: int = 2      # aynı sembolde 2 ardışık zarar → o gün dur
SPREAD_SPIKE_MULT: float = 2.0             # spread ≥ ort×2 = anormal
VOLUME_SPIKE_MULT: float = 3.0             # hacim ≥ ort×3 = patlama
SPREAD_AVG_LOOKBACK: int = 100              # son 100 tick spread ortalaması

# ── Oylama sistemi ──────────────────────────────────────────────────
VOTING_ATR_LOOKBACK: int = 5        # ATR genişleme: son 5 bar ATR vs önceki 5 bar

# ── FAZ 3: Ağırlıklı oylama sistemi ──────────────────────────────
# Oy ağırlıkları (toplam 10)
VOTE_W_RSI:       float = 2.0    # RSI momentum
VOTE_W_EMA:       float = 2.5    # EMA trend
VOTE_W_TREND_PA:  float = 2.5    # Price Action trend yapısı (FAZ 1)
VOTE_W_ATR:       float = 1.5    # ATR genişleme
VOTE_W_VOLUME:    float = 1.5    # Hacim

# Ağırlıklı oylama eşikleri
WEIGHTED_VOTE_EXIT_THRESHOLD: float = 3.0   # Ağırlıklı ters skor >= 3 → çık
WEIGHTED_VOTE_HOLD_THRESHOLD: float = 4.0   # Ağırlıklı lehte skor >= 4 → tut

# ── FAZ 3: 3-kademeli TP sistemi ─────────────────────────────────
TP1_ATR: float = 1.5    # TP1: 1.5×ATR → %33 kapat
TP2_ATR: float = 2.5    # TP2: 2.5×ATR → %33 kapat
TP3_TRAIL: bool = True   # TP3: kalan trailing ile yönetilir
TP1_CLOSE_PCT: float = 0.33   # TP1'de kapatılacak oran
TP2_CLOSE_PCT: float = 0.50   # TP2'de kalanın yarısı

# ── FAZ 3: Conviction (inanç) bazlı lot ölçekleme ────────────────
CONVICTION_HIGH_THRESHOLD: float = 75.0    # Confluence >= 75 → tam lot
CONVICTION_MED_THRESHOLD:  float = 60.0    # Confluence 60-75 → %70 lot
CONVICTION_LOW_MULT:       float = 0.5     # Confluence < 60 → %50 lot (düşük inanç)
CONVICTION_HIGH_MULT:      float = 1.0     # Yüksek inanç → tam lot
CONVICTION_MED_MULT:       float = 0.7     # Orta inanç → %70 lot

# ═════════════════════════════════════════════════════════════════════
#  İYİLEŞTİRME v13.0 — R-Multiple, Drawdown, Pyramid, Chandelier, Hold
# ═════════════════════════════════════════════════════════════════════

# ── 1. R-Multiple Takip Sistemi (Van Tharp) ──────────────────────
R_MULT_TRACK_ENABLED: bool = True     # R-Multiple takibi aktif mi
R_MULT_STOP_LOSS: float = -2.0        # -2R: mutlaka kapat (felaket koruma)
R_MULT_WARNING: float = -1.5          # -1.5R: uyarı, trailing sıkılaştır

# ── 2. Aylık Drawdown Limiti ─────────────────────────────────────
MONTHLY_DD_ENABLED: bool = True
MONTHLY_DD_MAX_PCT: float = 0.06       # aylık max drawdown: equity'nin %6'sı
MONTHLY_DD_WARN_PCT: float = 0.04      # %4'te yeni işlem alma, mevcutları yönet

# ── 3. Piramitleme (Turtle-style add to winners) ─────────────────
PYRAMID_ENABLED: bool = True
PYRAMID_ATR_STEP: float = 0.5         # her 0.5 × ATR lehine hareket → ekleme
PYRAMID_MAX_ADDS: int = 3             # max 3 ekleme (toplam 4 katman)
PYRAMID_ADD_FRACTION: float = 0.5     # her eklemede orijinal lotun %50'si
PYRAMID_SL_UPDATE: bool = True        # her eklemede tüm SL'leri yeni entry-2N'ye taşı
PYRAMID_MIN_PROFIT_ATR: float = 0.3   # eklemeden önce min 0.3×ATR kâr gerekli

# ── 4. Chandelier Exit (opsiyonel, hibrit trailing'e ek) ─────────
CHANDELIER_ENABLED: bool = True
CHANDELIER_LOOKBACK: int = 22          # 22-bar Highest High / Lowest Low
CHANDELIER_ATR_MULT: float = 3.0       # HH - 3×ATR (longs), LL + 3×ATR (shorts)
CHANDELIER_WEIGHT: float = 0.3         # hibrit karışım: %30 chandelier + %70 mevcut

# ── 5. Maksimum Pozisyon Süresi ──────────────────────────────────
MAX_HOLD_ENABLED: bool = True
# ── 6. Trailing Mesafe Sınırları (VİOP Rapor uyumu) ─────────────
#    ATR trailing mesafesinin fiyata göre yüzdesel alt/üst sınırı.
#    Aşırı sakin günlerde (ATR çok düşük) trailing gürültüde tetiklenmez,
#    aşırı volatil günlerde (ATR çok yüksek) trailing koruma işlevini yitirmez.
TRAILING_MIN_PCT: float = 0.015   # min trailing mesafesi = fiyatın %1.5'i
TRAILING_MAX_PCT: float = 0.080   # max trailing mesafesi = fiyatın %8.0'i
MAX_HOLD_BARS: int = 96                # 96 × M15 = 24 saat (1.5 işlem günü)
MAX_HOLD_PROFIT_EXIT: bool = True      # süre dolunca kârdaysa kapat
MAX_HOLD_LOSS_TIGHTEN: bool = True     # süre dolunca zarardaysa SL sıkılaştır


# ═════════════════════════════════════════════════════════════════════
#  YARDIMCI FONKSİYONLAR
# ═════════════════════════════════════════════════════════════════════


def _clamp_trailing_distance(
    direction: str,
    current_price: float,
    new_sl: float,
    min_pct: float = TRAILING_MIN_PCT,
    max_pct: float = TRAILING_MAX_PCT,
) -> float:
    """Trailing SL mesafesini fiyatın %min_pct - %max_pct arasına sınırla.

    VİOP Rapor uyumu:
        - Aşırı sakin günlerde (ATR çok düşük) trailing mesafesi %1.5'in altına
          düşmez — normal gürültüde erken tetiklenme önlenir.
        - Aşırı volatil günlerde (ATR çok yüksek) trailing mesafesi %8'in üstüne
          çıkmaz — stop koruma işlevini yitirmez.

    Args:
        direction: "BUY" veya "SELL"
        current_price: Anlık fiyat.
        new_sl: Hesaplanmış trailing SL.
        min_pct: Min trailing mesafe yüzdesi (varsayılan %1.5).
        max_pct: Max trailing mesafe yüzdesi (varsayılan %8.0).

    Returns:
        Sınırlandırılmış SL değeri.
    """
    if current_price <= 0:
        return new_sl

    min_dist = current_price * min_pct
    max_dist = current_price * max_pct

    if direction == "BUY":
        # BUY: SL fiyatın altında → mesafe = current_price - new_sl
        distance = current_price - new_sl
        clamped = max(min_dist, min(distance, max_dist))
        return current_price - clamped
    else:
        # SELL: SL fiyatın üstünde → mesafe = new_sl - current_price
        distance = new_sl - current_price
        clamped = max(min_dist, min(distance, max_dist))
        return current_price + clamped


def _business_days_until(target: date, from_date: date) -> int:
    """Hedef tarihe kalan iş günü sayısı (tatiller dahil).

    Args:
        target: Hedef tarih.
        from_date: Başlangıç tarihi.

    Returns:
        Kalan iş günü sayısı.
    """
    if target <= from_date:
        return 0
    count = 0
    d = from_date + timedelta(days=1)
    while d <= target:
        if d.weekday() < 5 and d not in ALL_HOLIDAYS:
            count += 1
        d += timedelta(days=1)
    return count


def _business_days_since(start: date, from_date: date) -> int:
    """Başlangıç tarihinden bu yana geçen iş günü sayısı.

    Args:
        start: Başlangıç tarihi.
        from_date: Bugünün tarihi.

    Returns:
        Geçen iş günü sayısı.
    """
    if from_date <= start:
        return 0
    count = 0
    d = start + timedelta(days=1)
    while d <= from_date:
        if d.weekday() < 5 and d not in ALL_HOLIDAYS:
            count += 1
        d += timedelta(days=1)
    return count


def _find_swing_low(low: np.ndarray, lookback: int) -> float | None:
    """Son *lookback* bar içindeki en düşük fiyat."""
    if len(low) < lookback:
        return None
    segment = low[-lookback:]
    valid = segment[~np.isnan(segment)]
    if len(valid) == 0:
        return None
    return float(np.min(valid))


def _find_swing_high(high: np.ndarray, lookback: int) -> float | None:
    """Son *lookback* bar içindeki en yüksek fiyat."""
    if len(high) < lookback:
        return None
    segment = high[-lookback:]
    valid = segment[~np.isnan(segment)]
    if len(valid) == 0:
        return None
    return float(np.max(valid))


# ═════════════════════════════════════════════════════════════════════
#  OĞUL
# ═════════════════════════════════════════════════════════════════════

class Ogul:
    """Sinyal üretici ve emir yöneticisi.

    Her 10 saniyede ``process_signals()`` çağrılır.
    3 strateji: trend follow, mean reversion, breakout.
    """

    def __init__(
        self,
        config: Config,
        mt5: MT5Bridge,
        db: Database,
        baba: Any | None = None,
        risk_params: RiskParams | None = None,
    ) -> None:
        self.config = config
        self.mt5 = mt5
        self.db = db
        self.baba = baba
        self.risk_params = risk_params or RiskParams()
        self.active_trades: dict[str, Trade] = {}
        self._trade_lock = threading.Lock()  # Pozisyon limiti atomik kontrolü
        # v5.8/CEO-FAZ2: margin_reserve_pct config'den okunuyor (hardcoded değil)
        self._margin_reserve_pct: float = float(
            config.get("engine.margin_reserve_pct", MARGIN_RESERVE_PCT_DEFAULT)
        )
        self.last_signals: dict[str, str] = {}  # symbol → "BUY"|"SELL"|"BEKLE"
        self.h_engine: Any | None = None  # HEngine referansı (main.py tarafından atanır)
        self.manuel_motor: Any | None = None  # ManuelMotor referansı (main.py tarafından atanır)
        self.ustat: Any | None = None  # ÜSTAT referansı (main.py tarafından atanır)

        # ── Top 5 kontrat seçimi (v5.8/CEO-FAZ3: ayrı modüle taşındı) ──
        self._top5 = Top5Selector(db=db, config=config)
        # Geriye uyumluluk property'leri (mevcut kodun bozulmaması için)
        # self._current_top5, _current_scores, _last_refresh → _top5 delegasyonu

        # ── İki döngü mimarisi (sinyal: M15 kapanış, yönetim: 10 sn) ──
        self._last_m15_candle_ts: str = ""          # son işlenen M15 mum timestamp
        self._last_m5_candle_ts: str = ""           # son işlenen M5 mum timestamp (v5.7: M5 tetikleme)
        self._daily_loss_stop: bool = False          # %3 günlük zarar durdurucu
        self._daily_loss_stop_date: date | None = None  # sıfırlama takibi
        self._symbol_loss_count: dict[str, int] = {}    # sembol bazlı ardışık zarar
        self._symbol_loss_date: date | None = None       # günlük sıfırlama

        # ── v13.0 İyileştirme alanları ─────────────────────────────
        # R-Multiple istatistikleri
        self._r_multiple_history: list[float] = []        # kapanan işlemlerin R değerleri
        self._r_expectancy: float = 0.0                   # (WR × Avg Win R) - (LR × 1R)
        # Aylık drawdown takibi
        self._monthly_start_equity: float = 0.0           # ay başı equity
        self._monthly_start_date: date | None = None
        self._monthly_dd_stop: bool = False               # aylık limit aşıldı mı
        self._monthly_dd_warn: bool = False               # uyarı seviyesi
        # Pyramid tracking per symbol
        self._pyramid_last_add: dict[str, float] = {}     # symbol → son ekleme fiyatı

    # ═════════════════════════════════════════════════════════════════
    #  ÜSTAT ENTEGRASYONu — Dinamik Parametre Okuma
    # ═════════════════════════════════════════════════════════════════

    def _get_ustat_param(self, key: str, fallback: float) -> float:
        """ÜSTAT strateji havuzundan parametre oku, yoksa fallback döndür.

        ÜSTAT'ın rejime göre belirlediği aktif profil parametrelerini
        kullanır. ÜSTAT erişilemezse veya parametre yoksa hardcoded
        sabite geri döner.

        Args:
            key: Parametre adı (ör. "sl_atr_mult", "tp_atr_mult").
            fallback: ÜSTAT erişilemezse kullanılacak varsayılan değer.

        Returns:
            Parametre değeri.
        """
        if self.ustat is None:
            return fallback
        try:
            params = self.ustat.get_active_params()
            # Fix M14: None değer kontrolü — float(None) crash önleme
            val = params.get(key)
            if val is None:
                return fallback
            return float(val)
        except (TypeError, ValueError) as exc:
            logger.warning(
                f"ÜSTAT param dönüşüm hatası [{key}]={val!r}: {exc} "
                f"→ fallback={fallback}"
            )
            return fallback
        except Exception:
            return fallback

    def _get_contract_profile(self, symbol: str) -> dict[str, Any] | None:
        """ÜSTAT'tan kontrat davranış profilini oku.

        Top 5 seçimi ve sinyal üretiminde kontratın geçmiş performansı,
        yön tercihi ve win-rate bilgisi için kullanılır.

        Args:
            symbol: Kontrat sembolü.

        Returns:
            Kontrat profili dict veya None.
        """
        if self.ustat is None:
            return None
        try:
            return self.ustat.get_contract_profile(symbol)
        except Exception:
            return None

    def _get_ustat_strategy_hint(self) -> str:
        """ÜSTAT'tan tercih edilen strateji yönlendirmesini oku.

        ÜSTAT rejim ve geçmiş verilere dayalı olarak hangi stratejinin
        mevcut koşullarda daha etkili olacağını belirler. OĞUL bu bilgiyi
        sinyal gücü hesaplamasında bonus olarak kullanır.

        Returns:
            Tercih edilen strateji adı (trend_follow/mean_reversion/breakout)
            veya boş string (ÜSTAT erişilemezse).
        """
        if self.ustat is None:
            return ""
        try:
            params = self.ustat.get_active_params()
            return str(params.get("preferred_strategy", ""))
        except Exception:
            return ""

    # ═════════════════════════════════════════════════════════════════
    #  ANA GİRİŞ
    # ═════════════════════════════════════════════════════════════════

    def process_signals(self, symbols: list[str], regime: Regime) -> None:
        """Seçilen kontratlar için sinyal üret ve emirleri yönet.

        Her 10 sn'de ``main_loop`` tarafından çağrılır.
        İki döngü mimarisi:
            HIZLI DÖNGÜ (her 10 sn): pozisyon yönetimi, risk, acil çıkış
            SİNYAL DÖNGÜSÜ (M15 kapanış): sinyal üretimi, yeni işlem

        Çağrı sırası:
            1. _check_end_of_day()             — 17:45 kapatma (EN ÖNCE)
            2. _advance_orders(regime)          — SENT/PARTIAL/TIMEOUT ilerletme
            3. _manage_active_trades(regime)    — evrensel pozisyon yönetimi
            4. _sync_positions()               — MT5 senkronizasyon
            5. _check_advanced_risk_rules()     — gelişmiş risk kontrolleri
            6. _check_time_rules(regime)        — zaman bazlı kurallar
            7. Oylama hesapla                  — 4 gösterge, Dashboard için
            8. M15 kapanış → sinyal üretimi    — yeni mum yoksa atla

        Args:
            symbols: Top-5 kontrat sembolleri.
            regime: Mevcut piyasa rejimi.
        """
        now = datetime.now()

        # ── Günlük sıfırlamalar ────────────────────────────────────
        today = now.date()
        if self._daily_loss_stop_date != today:
            self._daily_loss_stop = False
            self._daily_loss_stop_date = today
        if self._symbol_loss_date != today:
            self._symbol_loss_count.clear()
            self._symbol_loss_date = today

        # ═══ HIZLI DÖNGÜ (her 10 sn) ══════════════════════════════

        # 1. Gün sonu kontrolü — 17:45 tüm pozisyon/emir kapatma
        self._check_end_of_day()

        # 2. Bekleyen emir state-machine ilerletme
        self._advance_orders(regime)

        # 3. Mevcut işlemleri yönet (evrensel veya strateji bazlı)
        self._manage_active_trades(regime)

        # 4. MT5 ile pozisyon senkronizasyonu
        self._sync_positions()

        # 5. Her sembol için oylama hesapla — her zaman, koşulsuz (Dashboard)
        for symbol in symbols:
            self.last_signals[symbol] = self._calculate_voting(symbol)

        # Günlük zarar durdurucu aktifse sinyal üretme
        if self._daily_loss_stop:
            return

        # ═══ SİNYAL DÖNGÜSÜ (M5 mum kapanışında tetiklenir — v5.7) ═════

        # 6. M5 mum kapanış kontrolü — kapanmamışsa sinyal üretme
        #    v5.7: M15→M5 tetikleme geçişi — 3x daha hızlı sinyal üretimi.
        #    M15/H1 verileri filtreleme+doğrulama olarak kullanılmaya devam eder.
        if not self._is_new_m5_candle():
            return

        # 7. Rejim kontrolü — aktif stratejiler
        strategies = regime.allowed_strategies
        if not strategies:
            logger.debug(
                f"Rejim {regime.regime_type.value}: tüm sinyaller deaktif"
            )
            return

        # 8. İşlem saatleri kontrolü
        if not self._is_trading_allowed():
            return

        # 10. Her sembol için sinyal üretimi
        from engine.netting_lock import is_symbol_locked, acquire_symbol, release_symbol

        for symbol in symbols:
            # Sembol başına 1 aktif işlem kuralı
            if symbol in self.active_trades:
                continue

            # v5.4.1: Atomik netting kilidi kontrolü (race condition önleme)
            if is_symbol_locked(symbol, exclude_owner="ogul"):
                logger.debug(f"Netting kilit: {symbol} — başka motor tarafından kilitli, sinyal atlanıyor")
                continue

            # Hibrit yönetimindeki sembol atla (netting koruması)
            if self.h_engine and symbol in self.h_engine.get_hybrid_symbols():
                logger.debug(f"Hibrit yönetiminde: {symbol} — sinyal atlanıyor")
                continue

            # Manuel yönetimdeki sembol atla (netting koruması — v14.0)
            if self.manuel_motor and symbol in self.manuel_motor.get_manual_symbols():
                logger.debug(f"Manuel yönetimde: {symbol} — sinyal atlanıyor")
                continue

            # Kill-switch kontrolü
            if self.baba and self.baba.is_symbol_killed(symbol):
                logger.debug(f"Sembol durdurulmuş (L1): {symbol}")
                continue

            # Ardışık zarar kontrolü — o gün sembol kapalı
            if self._symbol_loss_count.get(symbol, 0) >= SYMBOL_CONSECUTIVE_LOSS_LIMIT:
                logger.debug(
                    f"Ardışık {SYMBOL_CONSECUTIVE_LOSS_LIMIT} zarar: "
                    f"{symbol} bugün sinyal atlanıyor"
                )
                continue

            signal = self._generate_signal(symbol, regime, strategies)
            if signal:
                self.last_signals[symbol] = signal.signal_type.value
                self._execute_signal(signal, regime)

    # ═════════════════════════════════════════════════════════════════
    #  M15 MUM KAPANIŞ TESPİTİ
    # ═════════════════════════════════════════════════════════════════

    def _is_new_m15_candle(self) -> bool:
        """Yeni bir M15 mum kapanıp kapanmadığını kontrol et.

        DB'deki en son M15 bar timestamp'ını izler.
        Aynı mum iki kez işlenmez.

        Returns:
            True: yeni mum kapanmış, sinyal üretilebilir.
            False: aynı mum, sinyal üretme.
        """
        # İzlenen herhangi bir sembolden en son M15 barı al
        sample_symbol = None
        if self.current_top5:
            sample_symbol = self.current_top5[0]
        else:
            # Top5 henüz belirlenmemişse WATCHED_SYMBOLS'dan al
            from engine.mt5_bridge import WATCHED_SYMBOLS
            if WATCHED_SYMBOLS:
                sample_symbol = list(WATCHED_SYMBOLS)[0]

        if sample_symbol is None:
            return False

        try:
            df = self.db.get_bars(sample_symbol, "M15", limit=1)
            if df is None or df.empty:
                return False

            latest_ts = str(df.iloc[-1].get("timestamp", ""))
            if not latest_ts:
                return False

            if latest_ts != self._last_m15_candle_ts:
                self._last_m15_candle_ts = latest_ts
                logger.debug(f"Yeni M15 mum kapanışı tespit edildi: {latest_ts}")
                return True

            return False

        except Exception as exc:
            logger.error(f"M15 mum kontrolü hatası: {exc}")
            return False

    def _is_new_m5_candle(self) -> bool:
        """Yeni bir M5 mum kapanıp kapanmadığını kontrol et.

        v5.7: Sinyal tetiklemesi M15 yerine M5 mum kapanışına bağlandı.
        Her 5 dakikada bir sinyal üretimi tetiklenir (3x daha hızlı).
        M15/H1 verileri filtreleme ve doğrulama için kullanılmaya devam eder.

        Returns:
            True: yeni M5 mumu kapanmış, sinyal üretilebilir.
            False: aynı mum, sinyal üretme.
        """
        sample_symbol = None
        if self.current_top5:
            sample_symbol = self.current_top5[0]
        else:
            from engine.mt5_bridge import WATCHED_SYMBOLS
            if WATCHED_SYMBOLS:
                sample_symbol = list(WATCHED_SYMBOLS)[0]

        if sample_symbol is None:
            return False

        try:
            df = self.db.get_bars(sample_symbol, "M5", limit=1)
            if df is None or df.empty:
                return False

            latest_ts = str(df.iloc[-1].get("timestamp", ""))
            if not latest_ts:
                return False

            if latest_ts != self._last_m5_candle_ts:
                self._last_m5_candle_ts = latest_ts
                logger.debug(f"Yeni M5 mum kapanışı tespit edildi: {latest_ts}")
                return True

            return False

        except Exception as exc:
            logger.error(f"M5 mum kontrolü hatası: {exc}")
            return False

    # ═════════════════════════════════════════════════════════════════
    #  YÖN EĞİLİMİ (OYLAMA)
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _get_liq_class(symbol: str) -> str:
        """Sembolün likidite sınıfını döndür (A/B/C)."""
        return LIQUIDITY_CLASSES.get(symbol, "C")  # bilinmeyen = C (en muhafazakâr)

    def _calculate_bias(self, symbol: str) -> str:
        """Geriye uyumluluk: _calculate_voting'e yönlendir."""
        return self._calculate_voting(symbol)

    def _calculate_voting(self, symbol: str) -> str:
        """4 göstergeli oylama sistemi ile yön eğilimi hesapla.

        4 farklı veri türünden bağımsız sinyaller:
            1. Momentum  — RSI(14): >50 BUY, <50 SELL
            2. Trend     — EMA(20) vs EMA(50) crossover
            3. Volatilite — ATR(14) genişliyor mu (güç doğrulama)
            4. Likidite  — Hacim > 20-bar ortalaması mı (güç doğrulama)

        Returns:
            ``"BUY"``, ``"SELL"`` veya ``"NOTR"``.
        """
        detail = self._get_voting_detail(symbol)
        return detail["direction"]

    def _get_voting_detail(self, symbol: str) -> dict:
        """Detaylı oylama sonucu (pozisyon yönetiminde kullanılır).

        Returns:
            dict: direction, buy_votes, sell_votes, total_favorable,
                  rsi_vote, ema_vote, atr_expanding, volume_above_avg
        """
        result = {
            "direction": "NOTR",
            "buy_votes": 0,
            "sell_votes": 0,
            "total_favorable": 0,
            "rsi_vote": "NOTR",
            "ema_vote": "NOTR",
            "atr_expanding": False,
            "volume_above_avg": False,
        }

        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df is None or df.empty or len(df) < MIN_BARS_M15:
            return result

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)

        buy_votes = 0
        sell_votes = 0

        # ── Oy 1: Momentum — RSI(14) ──────────────────────────────
        rsi_arr = calc_rsi(close, period=MR_RSI_PERIOD)
        rsi_val = last_valid(rsi_arr)
        if rsi_val is not None:
            if rsi_val > 50:
                buy_votes += 1
                result["rsi_vote"] = "BUY"
            elif rsi_val < 50:
                sell_votes += 1
                result["rsi_vote"] = "SELL"

        # ── Oy 2: Trend — EMA(20) vs EMA(50) crossover ────────────
        ema_f = ema(close, period=TF_EMA_FAST)
        ema_s = ema(close, period=TF_EMA_SLOW)
        ef = last_valid(ema_f)
        es = last_valid(ema_s)
        if ef is not None and es is not None:
            if ef > es:
                buy_votes += 1
                result["ema_vote"] = "BUY"
            elif ef < es:
                sell_votes += 1
                result["ema_vote"] = "SELL"

        # ── Oy 3: Volatilite — ATR(14) genişliyor mu (adaptif) ─────
        atr_arr = calc_atr(high, low, close, period=ATR_PERIOD)
        _vol_regime = "NORMAL"  # LOW / NORMAL / HIGH
        if atr_arr is not None and len(atr_arr) >= VOTING_ATR_LOOKBACK * 2:
            recent_atr = np.nanmean(atr_arr[-VOTING_ATR_LOOKBACK:])
            prev_atr = np.nanmean(
                atr_arr[-(VOTING_ATR_LOOKBACK * 2):-VOTING_ATR_LOOKBACK]
            )

            # Volatilite rejim tespiti (adaptif filtreler için)
            if len(atr_arr) >= 50:
                atr_clean = atr_arr[~np.isnan(atr_arr)]
                if len(atr_clean) >= 50:
                    pct_rank = float(
                        np.searchsorted(np.sort(atr_clean[-100:]), recent_atr)
                        / len(atr_clean[-100:]) * 100
                    )
                    if pct_rank < 30:
                        _vol_regime = "LOW"
                    elif pct_rank > 70:
                        _vol_regime = "HIGH"

            if prev_atr > 0 and recent_atr > prev_atr:
                result["atr_expanding"] = True
                if buy_votes > sell_votes:
                    buy_votes += 1
                elif sell_votes > buy_votes:
                    sell_votes += 1
                # Beraberlikte ATR oy vermez — tiebreaker ağırlıklı skorla çözülür
            elif _vol_regime == "LOW" and prev_atr > 0:
                # Düşük volatilite: ATR genişlemese bile stabil ise kabul et
                # (sıkışma bölgesinde sinyal kaçırmamak için)
                ratio = recent_atr / prev_atr if prev_atr > 0 else 0
                if ratio >= 0.90:  # %10'dan fazla daralmadıysa stabil
                    result["atr_expanding"] = True
                    result["atr_regime_override"] = True

        result["vol_regime"] = _vol_regime

        # ── Oy 4: Likidite — Hacim adaptif eşik ─────────────────
        if len(volume) >= VOL_LOOKBACK + 1:
            current_vol = volume[-1]
            avg_vol = np.nanmean(volume[-(VOL_LOOKBACK + 1):-1])
            if avg_vol > 0:
                vol_ratio = current_vol / avg_vol
                # Düşük volatilite rejiminde hacim eşiği %80'e düşer
                # Normal/yüksek rejimde standart %100
                vol_threshold = 0.80 if _vol_regime == "LOW" else 1.0

                if vol_ratio >= vol_threshold:
                    result["volume_above_avg"] = True
                    if buy_votes > sell_votes:
                        buy_votes += 1
                    elif sell_votes > buy_votes:
                        sell_votes += 1
                result["vol_ratio"] = round(vol_ratio, 2)

        result["buy_votes"] = buy_votes
        result["sell_votes"] = sell_votes

        # ── FAZ 3: Ağırlıklı oylama (price action dahil) ────────
        w_buy = 0.0
        w_sell = 0.0

        # RSI ağırlığı
        if result["rsi_vote"] == "BUY":
            w_buy += VOTE_W_RSI
        elif result["rsi_vote"] == "SELL":
            w_sell += VOTE_W_RSI

        # EMA ağırlığı
        if result["ema_vote"] == "BUY":
            w_buy += VOTE_W_EMA
        elif result["ema_vote"] == "SELL":
            w_sell += VOTE_W_EMA

        # ATR genişleme ağırlığı (mevcut çoğunluk yönüne)
        if result["atr_expanding"]:
            if w_buy > w_sell:
                w_buy += VOTE_W_ATR
            elif w_sell > w_buy:
                w_sell += VOTE_W_ATR

        # Hacim ağırlığı (mevcut çoğunluk yönüne)
        if result["volume_above_avg"]:
            if w_buy > w_sell:
                w_buy += VOTE_W_VOLUME
            elif w_sell > w_buy:
                w_sell += VOTE_W_VOLUME

        # FAZ 3: Price Action trend yapısı ağırlığı
        try:
            pa_trend = analyze_trend_structure(high, low, close)
            if pa_trend.direction == "up":
                w_buy += VOTE_W_TREND_PA * pa_trend.trend_strength
                result["pa_trend"] = "up"
            elif pa_trend.direction == "down":
                w_sell += VOTE_W_TREND_PA * pa_trend.trend_strength
                result["pa_trend"] = "down"
            else:
                result["pa_trend"] = "range"
            result["pa_trend_strength"] = pa_trend.trend_strength
        except Exception:
            result["pa_trend"] = "error"
            result["pa_trend_strength"] = 0.0

        result["weighted_buy"] = round(w_buy, 2)
        result["weighted_sell"] = round(w_sell, 2)

        # Sonuç: en yüksek oy alan yön
        # Beraberlikte ağırlıklı skorlar tiebreaker olarak kullanılır
        if buy_votes > sell_votes:
            result["direction"] = "BUY"
            result["total_favorable"] = buy_votes
        elif sell_votes > buy_votes:
            result["direction"] = "SELL"
            result["total_favorable"] = sell_votes
        elif w_buy > w_sell and (w_buy - w_sell) >= 1.0:
            # Tiebreaker: basit oylar eşit ama ağırlıklı skor fark ≥ 1.0
            result["direction"] = "BUY"
            result["total_favorable"] = buy_votes
            result["tiebreaker"] = "weighted"
        elif w_sell > w_buy and (w_sell - w_buy) >= 1.0:
            result["direction"] = "SELL"
            result["total_favorable"] = sell_votes
            result["tiebreaker"] = "weighted"
        else:
            result["direction"] = "NOTR"
            result["total_favorable"] = 0

        return result

    # ═════════════════════════════════════════════════════════════════
    #  SİNYAL ÜRETİMİ
    # ═════════════════════════════════════════════════════════════════

    def _generate_signal(
        self,
        symbol: str,
        regime: Regime,
        strategies: list[StrategyType],
    ) -> Signal | None:
        """Bir kontrat için en güçlü sinyali üret.

        Args:
            symbol: Kontrat sembolü.
            regime: Mevcut rejim.
            strategies: Aktif strateji listesi.

        Returns:
            En yüksek strength'e sahip Signal veya None.
        """
        # ── v5.7: M5 verisi SE2 sinyal tetiklemesi için ────────────────
        df_m5 = self.db.get_bars(symbol, "M5", limit=MIN_BARS_M5)
        if df_m5 is None or df_m5.empty or len(df_m5) < MIN_BARS_M5:
            logger.debug(f"{symbol}: M5 verisi yetersiz ({len(df_m5) if df_m5 is not None else 0} bar)")
            return None

        m5_close = df_m5["close"].values.astype(np.float64)
        m5_high = df_m5["high"].values.astype(np.float64)
        m5_low = df_m5["low"].values.astype(np.float64)
        m5_volume = df_m5["volume"].values.astype(np.float64)
        m5_open = df_m5["open"].values.astype(np.float64) if "open" in df_m5.columns else m5_close.copy()

        # ── M15 verisi filtre/confluence için (eski ana veri, şimdi doğrulama) ──
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < MIN_BARS_M15:
            return None

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)
        open_ = df["open"].values.astype(np.float64) if "open" in df.columns else close.copy()

        candidates: list[Signal] = []

        # ═══════════════════════════════════════════════════════════════
        #  Signal Engine v2.0 — Yapı-Öncelikli Ana Motor
        #  v5.7: SE2 artık M5 verisiyle beslenir (3x daha hızlı tetikleme)
        #         M15/H1 verileri confluence + filtreleme olarak kalır
        # ═══════════════════════════════════════════════════════════════
        try:
            _regime_str = regime.regime_type.value if regime else ""
            verdict: SignalVerdict = se2_generate_signal(
                m5_open, m5_high, m5_low, m5_close, m5_volume,
                current_price=float(m5_close[-1]),
                regime_type=_regime_str,
            )
            if verdict.should_trade and verdict.direction != "NEUTRAL":
                # SignalVerdict → Signal dönüşümü
                se2_signal_type = (
                    SignalType.BUY if verdict.direction == "BUY"
                    else SignalType.SELL
                )
                se2_strategy_map = {
                    "trend_follow": StrategyType.TREND_FOLLOW,
                    "mean_reversion": StrategyType.MEAN_REVERSION,
                    "breakout": StrategyType.BREAKOUT,
                }
                se2_strategy = se2_strategy_map.get(
                    verdict.strategy_type, StrategyType.TREND_FOLLOW
                )
                se2_signal = Signal(
                    symbol=symbol,
                    signal_type=se2_signal_type,
                    price=verdict.entry_price,
                    sl=verdict.structural_sl,
                    tp=verdict.structural_tp,
                    strength=min(verdict.strength + 0.15, 1.0),  # SE3 bonusu
                    reason=verdict.reason,
                    strategy=se2_strategy,
                )
                candidates.append(se2_signal)
                logger.info(
                    f"[ÜSTAT-SE] Sinyal üretildi [{symbol}]: "
                    f"{verdict.direction} güç={verdict.strength:.2f} "
                    f"skor={verdict.total_score:.0f} "
                    f"kaynak={verdict.agreeing_sources}/9 "
                    f"R:R={verdict.risk_reward:.1f}"
                )
        except Exception as exc:
            logger.warning(f"[ÜSTAT-SE] Sinyal motoru hatası [{symbol}]: {exc}")

        # ═══════════════════════════════════════════════════════════════
        #  Eski Strateji Motoru (Fallback)
        # ═══════════════════════════════════════════════════════════════
        for strategy in strategies:
            signal: Signal | None = None

            if strategy == StrategyType.TREND_FOLLOW:
                signal = self._check_trend_follow(
                    symbol, close, high, low, volume, regime,
                )
            elif strategy == StrategyType.MEAN_REVERSION:
                signal = self._check_mean_reversion(
                    symbol, close, high, low, volume, regime,
                )
            elif strategy == StrategyType.BREAKOUT:
                signal = self._check_breakout(
                    symbol, close, high, low, volume,
                )

            if signal:
                candidates.append(signal)

        if not candidates:
            return None

        # ── ÜSTAT strateji yönlendirmesi: tercih edilen stratejiye bonus ──
        # ÜSTAT'ın rejim ve geçmiş veriye dayalı strateji tercihi,
        # eşleşen sinyallerin strength'ine eklenir.
        ustat_pref = self._get_ustat_strategy_hint()
        if ustat_pref:
            bonus = self._get_ustat_param("strategy_bonus", 10) / 100.0
            strategy_name_map = {
                StrategyType.TREND_FOLLOW: "trend_follow",
                StrategyType.MEAN_REVERSION: "mean_reversion",
                StrategyType.BREAKOUT: "breakout",
            }
            for cand in candidates:
                cand_name = strategy_name_map.get(cand.strategy, "")
                if cand_name == ustat_pref:
                    cand.strength = min(1.0, cand.strength + bonus)

        # En güçlü sinyali seç (SE2 bonusu ile SE2 sinyali tercih edilir)
        best = max(candidates, key=lambda s: s.strength)

        # ── FAZ 1: Price Action Confluence Gate ────────────────────
        # Yapısal farkındalık: sinyal, piyasa yapısıyla uyumlu mu?
        try:
            atr_arr = calc_atr(high, low, close, ATR_PERIOD)
            atr_val = last_valid(atr_arr)
            if atr_val and atr_val > 0:
                direction_str = "BUY" if best.signal_type == SignalType.BUY else "SELL"

                # Destek/Direnç seviyeleri
                pa_levels = find_support_resistance(high, low, close, atr_val)

                # Bar pattern tanıma
                pa_patterns = detect_bar_patterns(open_, high, low, close, atr_val)

                # Trend yapısı (HH/HL/LH/LL)
                pa_trend = analyze_trend_structure(high, low, close)

                # Gösterge değerleri (confluence hesabı için)
                ema_f_arr = ema(close, TF_EMA_FAST)
                ema_s_arr = ema(close, TF_EMA_SLOW)
                rsi_arr = calc_rsi(close, MR_RSI_PERIOD)
                _, _, hist_arr = calc_macd(close)
                adx_arr = calc_adx(high, low, close, ATR_PERIOD)

                _ema_f = last_valid(ema_f_arr) or 0.0
                _ema_s = last_valid(ema_s_arr) or 0.0
                _rsi = last_valid(rsi_arr) or 50.0
                _hist = last_valid(hist_arr) or 0.0
                _adx = last_valid(adx_arr) or 0.0

                # Hacim oranı
                vol_avg = float(np.nanmean(volume[-21:-1])) if len(volume) > 21 else float(np.nanmean(volume))
                vol_ratio = float(volume[-1]) / vol_avg if vol_avg > 0 else 1.0

                # Confluence hesapla
                # v2: Rejim bilgisini al
                _regime_str = regime.regime_type.value if regime else ""

                confluence = calculate_confluence(
                    direction=direction_str,
                    price=best.price,
                    levels=pa_levels,
                    patterns=pa_patterns,
                    trend=pa_trend,
                    atr_val=atr_val,
                    adx_val=_adx,
                    rsi_val=_rsi,
                    macd_hist=_hist,
                    ema_fast=_ema_f,
                    ema_slow=_ema_s,
                    volume_ratio=vol_ratio,
                    regime_type=_regime_str,
                )

                # v2: Rejim-bazlı eşik logla
                _conf_threshold = CONFLUENCE_THRESHOLDS.get(_regime_str, CONFLUENCE_MIN_ENTRY)

                # v2: Confluence gate → soft penalty
                # ESKİ: can_enter=False → return None (hard veto, %100 red)
                # YENİ: Düşük skor → güç cezası (sinyal ölmez, zayıflar)
                if not confluence.can_enter:
                    conf_factor = confluence.total_score / 100.0
                    penalty = 0.3 + 0.7 * conf_factor  # En az %30 kalır
                    original_str = best.strength
                    best.strength *= penalty
                    logger.info(
                        f"[PA] Confluence düşük [{symbol}]: "
                        f"skor={confluence.total_score:.1f} < {_conf_threshold} "
                        f"→ güç cezası {original_str:.2f}×{penalty:.2f}={best.strength:.2f} "
                        f"(seviye={confluence.level_score:.1f}, "
                        f"pattern={confluence.pattern_score:.1f}, "
                        f"indikatör={confluence.indicator_score:.1f}, "
                        f"hacim={confluence.volume_score:.1f}, "
                        f"trend={confluence.trend_score:.1f})"
                    )
                else:
                    # Confluence iyi — bonus ver
                    confluence_bonus = (confluence.total_score - _conf_threshold) / 100.0
                    best.strength = min(best.strength + confluence_bonus * 0.3, 1.0)
                    logger.debug(
                        f"[PA] Confluence OK [{symbol}]: "
                        f"skor={confluence.total_score:.1f} ≥ {_conf_threshold}"
                    )

                # Eski: Confluence skoru sinyal gücüne ekle (taşındı yukarı)
                # confluence_bonus = (confluence.total_score - CONFLUENCE_MIN_ENTRY) / 100.0
                # best.strength = min(best.strength + confluence_bonus * 0.3, 1.0)

                # Pattern yönü ters ise uyarı logla (soft engel — strength düşür)
                pat_ok, pat_str = pattern_confirms_direction(pa_patterns, direction_str)
                if not pat_ok:
                    best.strength *= 0.7
                    logger.debug(
                        f"[PA] Pattern çelişkisi [{symbol}]: "
                        f"strength {best.strength:.2f} (×0.7)"
                    )

                # Trend yapısı ters ise strength düşür
                trend_ok, t_str = trend_supports_direction(pa_trend, direction_str)
                if not trend_ok and t_str > 0.5:
                    best.strength *= 0.6
                    logger.debug(
                        f"[PA] Trend çelişkisi [{symbol}]: "
                        f"yapı={pa_trend.direction}, sinyal={direction_str} "
                        f"strength {best.strength:.2f} (×0.6)"
                    )

                # Yapısal SL/TP iyileştirmesi
                structural_sl = get_structural_sl(
                    direction_str, best.price,
                    pa_trend.swing_lows, pa_trend.swing_highs,
                    atr_val,
                )
                if structural_sl is not None:
                    # Yapısal SL daha sıkı (daha yakın) ise kullan
                    if direction_str == "BUY" and structural_sl > best.sl:
                        logger.debug(
                            f"[PA] Yapısal SL [{symbol}]: "
                            f"{best.sl:.4f} → {structural_sl:.4f}"
                        )
                        best.sl = structural_sl
                    elif direction_str == "SELL" and structural_sl < best.sl:
                        logger.debug(
                            f"[PA] Yapısal SL [{symbol}]: "
                            f"{best.sl:.4f} → {structural_sl:.4f}"
                        )
                        best.sl = structural_sl

                structural_tp = get_structural_tp(
                    direction_str, best.price,
                    pa_levels,
                    atr_val,
                    sl=best.sl,
                )
                if structural_tp is not None:
                    # Yapısal TP daha uzak ise kullan (daha iyi R:R)
                    if direction_str == "BUY" and structural_tp > best.tp:
                        best.tp = structural_tp
                    elif direction_str == "SELL" and structural_tp < best.tp:
                        best.tp = structural_tp

                # Confluence detaylarını reason'a ekle
                best.reason += (
                    f" | PA: conf={confluence.total_score:.0f}"
                    f" trend={pa_trend.direction}"
                )

                logger.info(
                    f"[PA] Confluence geçti [{symbol}]: "
                    f"skor={confluence.total_score:.1f} "
                    f"(L={confluence.level_score:.0f} P={confluence.pattern_score:.0f} "
                    f"I={confluence.indicator_score:.0f} V={confluence.volume_score:.0f} "
                    f"T={confluence.trend_score:.0f}) "
                    f"trend={pa_trend.direction}"
                )
        except Exception as exc:
            # Price Action hatası sinyal üretimini engellemez
            logger.warning(f"[PA] Price action analiz hatası [{symbol}]: {exc}")

        # ── FAZ 2: Multi-Timeframe Uyum Gate ──────────────────────
        try:
            direction_str = "BUY" if best.signal_type == SignalType.BUY else "SELL"

            # H1 verisi al
            h1_df = self.db.get_bars(symbol, "H1", limit=70)
            h1_data = None
            if h1_df is not None and not h1_df.empty and len(h1_df) >= 30:
                h1_data = {
                    "high": h1_df["high"].values.astype(np.float64),
                    "low": h1_df["low"].values.astype(np.float64),
                    "close": h1_df["close"].values.astype(np.float64),
                    "volume": h1_df["volume"].values.astype(np.float64),
                }

            # M5 verisi al
            m5_df = self.db.get_bars(symbol, "M5", limit=60)
            m5_data = None
            if m5_df is not None and not m5_df.empty and len(m5_df) >= 20:
                m5_data = {
                    "high": m5_df["high"].values.astype(np.float64),
                    "low": m5_df["low"].values.astype(np.float64),
                    "close": m5_df["close"].values.astype(np.float64),
                    "volume": m5_df["volume"].values.astype(np.float64),
                }

            # M15 verisi (zaten elimizde var)
            m15_data = {
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }

            mtf = analyze_multi_tf(direction_str, h1_data, m15_data, m5_data)

            # v2: H1 ters trend → kademeli ceza (ESKİ: hard veto)
            # Sadece çok güçlü ters trend (>0.8) hard engel kalır
            if h1_data is not None:
                h1_pass, h1_dir, h1_str = h1_trend_filter(
                    h1_data["close"], h1_data["high"], h1_data["low"],
                    direction_str,
                )
                if not h1_pass:
                    if h1_str > 0.8:
                        # Çok güçlü ters trend — hala hard engel
                        logger.info(
                            f"[MTF] H1 güçlü ters trend ENGEL [{symbol}]: "
                            f"sinyal={direction_str}, H1={h1_dir}, "
                            f"güç={h1_str:.2f} > 0.8"
                        )
                        return None
                    else:
                        # Orta güçlü ters trend — soft penalty
                        penalty = 1.0 - h1_str * 0.6
                        best.strength *= penalty
                        logger.info(
                            f"[MTF] H1 ters trend CEZA [{symbol}]: "
                            f"sinyal={direction_str}, H1={h1_dir}, "
                            f"güç={h1_str:.2f} → strength ×{penalty:.2f}"
                        )

            # v2: MTF conflict → soft penalty (ESKİ: hard veto)
            if mtf.alignment == "conflict":
                best.strength *= 0.5
                logger.info(
                    f"[MTF] TF çakışması CEZA [{symbol}]: "
                    f"skor={mtf.total_score:.1f}, "
                    f"alignment={mtf.alignment} → strength ×0.5"
                )
            elif mtf.alignment == "none":
                best.strength *= 0.7
                logger.debug(
                    f"[MTF] TF uyum yok [{symbol}]: strength ×0.7"
                )

            # MTF skoru sinyal gücüne ekle
            if mtf.total_score > 50:
                mtf_bonus = (mtf.total_score - 50) / 200.0  # max 0.25 bonus
                best.strength = min(best.strength + mtf_bonus, 1.0)

            # Strong alignment bonus
            if mtf.alignment == "strong":
                best.strength = min(best.strength + 0.1, 1.0)

            # M5 giriş kalitesi
            if m5_data is not None:
                m5_qual, m5_timing = m5_entry_quality(
                    m5_data["high"], m5_data["low"], m5_data["close"],
                    direction_str,
                )
                if m5_timing == "wait" and m5_qual < 0.3:
                    best.strength *= 0.7  # Kötü zamanlama cezası
                    logger.debug(
                        f"[MTF] M5 zamanlama kötü [{symbol}]: "
                        f"kalite={m5_qual:.2f}, timing={m5_timing}"
                    )

            best.reason += f" | MTF: {mtf.alignment}({mtf.total_score:.0f})"

            logger.info(
                f"[MTF] Analiz [{symbol}]: skor={mtf.total_score:.1f} "
                f"uyum={mtf.alignment} "
                f"H1={mtf.h1.trend_direction if mtf.h1 else '?'} "
                f"M15={mtf.m15.trend_direction if mtf.m15 else '?'} "
                f"M5={mtf.m5.trend_direction if mtf.m5 else '?'}"
            )
        except Exception as exc:
            # Multi-TF hatası sinyal üretimini engellemez
            logger.warning(f"[MTF] Multi-TF analiz hatası [{symbol}]: {exc}")

        # ÜSTAT signal_threshold — rejime göre minimum sinyal gücü filtresi
        ustat_threshold = self._get_ustat_param("signal_threshold", 0)
        if ustat_threshold > 0:
            # ÜSTAT threshold 0-100 ölçeğinde, strength 0-1 ölçeğinde
            min_strength = ustat_threshold / 100.0
            if best.strength < min_strength:
                logger.debug(
                    f"[ÜSTAT] Sinyal gücü yetersiz [{symbol}]: "
                    f"{best.strength:.2f} < {min_strength:.2f} (threshold={ustat_threshold})"
                )
                return None

        # C1: Seans zamanlama filtresi — açılış/kapanış volatilitesinde
        # strength düşürme (09:45-10:15 ve 17:15-17:45)
        now_time = datetime.now().time()
        SESSION_OPEN_END = time(10, 15)
        SESSION_CLOSE_START = time(17, 15)
        if now_time < SESSION_OPEN_END or now_time >= SESSION_CLOSE_START:
            original_str = best.strength
            best.strength = best.strength * 0.5
            logger.debug(
                f"Seans filtresi [{symbol}]: strength {original_str:.2f} "
                f"→ {best.strength:.2f} (saat={now_time})"
            )

        # v2: Trend follow H1 onayı → soft penalty (ESKİ: hard veto)
        # H1 nötr iken de trend follow izni var, sadece ceza
        if best.strategy == StrategyType.TREND_FOLLOW:
            if not self._confirm_h1(symbol, best):
                best.strength *= 0.6
                logger.debug(
                    f"H1 onayı yok [{symbol}]: {best.signal_type.value} "
                    f"→ strength ×0.6 = {best.strength:.2f}"
                )

        # v2: Tüm soft penaltylerden sonra minimum strength kontrolü
        # Çok zayıflayan sinyalleri ele (gereksiz işlem önleme)
        MIN_FINAL_STRENGTH = 0.10
        if best.strength < MIN_FINAL_STRENGTH:
            logger.info(
                f"[v2] Sinyal çok zayıf [{symbol}]: "
                f"güç={best.strength:.2f} < {MIN_FINAL_STRENGTH} — red"
            )
            return None

        logger.info(
            f"Sinyal üretildi [{symbol}]: {best.signal_type.value} "
            f"strateji={best.strategy.value} güç={best.strength:.2f} "
            f"SL={best.sl:.4f} TP={best.tp:.4f}"
        )
        return best

    # ── Trend Follow ──────────────────────────────────────────────

    def _check_trend_follow(
        self,
        symbol: str,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
        regime: "Regime | None" = None,
    ) -> Signal | None:
        """Trend follow sinyali kontrolü.

        Long: EMA(20) > EMA(50) + ADX > 22-28 (hysteresis) + MACD histogram 2 bar pozitif
        Short: EMA(20) < EMA(50) + ADX > 22-28 (hysteresis) + MACD histogram 2 bar negatif
        """
        # İndikatörler
        ema_fast = ema(close, TF_EMA_FAST)
        ema_slow = ema(close, TF_EMA_SLOW)
        adx_arr = calc_adx(high, low, close, ATR_PERIOD)
        atr_arr = calc_atr(high, low, close, ATR_PERIOD)
        _, _, histogram = calc_macd(close)

        # Son geçerli değerler
        ema_f = last_valid(ema_fast)
        ema_s = last_valid(ema_slow)
        adx_val = last_valid(adx_arr)
        atr_val = last_valid(atr_arr)

        if any(v is None for v in (ema_f, ema_s, adx_val, atr_val)):
            return None
        if atr_val <= 0:
            return None

        # MACD histogram son 2 bar
        hist_vals = last_n_valid(histogram, TF_MACD_CONFIRM_BARS)
        if len(hist_vals) < TF_MACD_CONFIRM_BARS:
            return None

        # ADX eşik — FAZ 2.6 hysteresis
        # ADX <= 22: kesin range → TF engel
        # ADX >= 28: kesin trend → TF serbest
        # 22 < ADX < 28: geçiş bölgesi → rejim TREND ise devam et
        if adx_val <= TF_ADX_SOFT:
            return None
        if adx_val < TF_ADX_HARD:
            # Geçiş bölgesi: yalnızca rejim TREND ise izin ver
            if regime is None or regime.regime_type != RegimeType.TREND:
                return None

        # Yön belirleme
        direction: SignalType | None = None

        if ema_f > ema_s and all(h > 0 for h in hist_vals):
            direction = SignalType.BUY
        elif ema_f < ema_s and all(h < 0 for h in hist_vals):
            direction = SignalType.SELL

        if direction is None:
            return None

        # Giriş fiyatı
        tick = self.mt5.get_tick(symbol)
        if tick is None:
            return None
        price = tick.ask if direction == SignalType.BUY else tick.bid

        # SL/TP hesaplama: ÜSTAT strateji havuzundan dinamik parametre
        tf_sl_mult = self._get_ustat_param("sl_atr_mult", TF_SL_ATR_MULT)
        tf_tp_mult = self._get_ustat_param("tp_atr_mult", TF_TP_ATR_MULT)

        if direction == SignalType.BUY:
            swing = _find_swing_low(low, SWING_LOOKBACK)
            if swing is not None and swing < price:
                sl = swing - atr_val
            else:
                sl = price - tf_sl_mult * atr_val
            tp = price + tf_tp_mult * atr_val
        else:
            swing = _find_swing_high(high, SWING_LOOKBACK)
            if swing is not None and swing > price:
                sl = swing + atr_val
            else:
                sl = price + tf_sl_mult * atr_val
            tp = price - tf_tp_mult * atr_val

        # Sinyal gücü: ADX (0-0.5) + MACD (0-0.3) + EMA mesafesi (0-0.2)
        adx_str = min((adx_val - TF_ADX_THRESHOLD) / 25.0, 0.5)
        hist_avg = abs(sum(hist_vals) / len(hist_vals))
        macd_str = min(hist_avg / (atr_val * 0.5) if atr_val > 0 else 0.0, 0.3)
        ema_dist = abs(ema_f - ema_s) / (price * 0.01) if price > 0 else 0.0
        ema_str = min(ema_dist * 0.1, 0.2)
        strength = adx_str + macd_str + ema_str

        return Signal(
            symbol=symbol,
            signal_type=direction,
            price=price,
            sl=sl,
            tp=tp,
            strength=min(strength, 1.0),
            reason=(
                f"TREND_FOLLOW: EMA({TF_EMA_FAST}){'>' if direction == SignalType.BUY else '<'}"
                f"EMA({TF_EMA_SLOW}) ADX={adx_val:.1f}"
            ),
            strategy=StrategyType.TREND_FOLLOW,
        )

    # ── Mean Reversion ────────────────────────────────────────────

    def _check_mean_reversion(
        self,
        symbol: str,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
        regime: "Regime | None" = None,
    ) -> Signal | None:
        """Mean reversion sinyali kontrolü.

        Long: RSI(14) < 20 + BB alt bant teması + ADX < 22-28 (hysteresis) + W%R < -80
        Short: RSI(14) > 80 + BB üst bant teması + ADX < 22-28 (hysteresis) + W%R > -20
        C3: Williams %R çift onay eklendi.
        """
        # İndikatörler
        rsi_arr = calc_rsi(close, MR_RSI_PERIOD)
        bb_upper, bb_middle, bb_lower = bollinger_bands(
            close, MR_BB_PERIOD, MR_BB_STD,
        )
        adx_arr = calc_adx(high, low, close, ATR_PERIOD)
        atr_arr = calc_atr(high, low, close, ATR_PERIOD)
        wr_arr = calc_williams_r(high, low, close, MR_RSI_PERIOD)

        # Son geçerli değerler
        rsi_val = last_valid(rsi_arr)
        bb_up = last_valid(bb_upper)
        bb_mid = last_valid(bb_middle)
        bb_low = last_valid(bb_lower)
        adx_val = last_valid(adx_arr)
        atr_val = last_valid(atr_arr)
        wr_val = last_valid(wr_arr)

        if any(v is None for v in (rsi_val, bb_up, bb_mid, bb_low, adx_val, atr_val)):
            return None
        if atr_val <= 0:
            return None

        # ADX eşik — FAZ 2.6 hysteresis
        # ADX >= 28: kesin trend → MR engel
        # ADX <= 22: kesin range → MR serbest
        # 22 < ADX < 28: geçiş bölgesi → rejim RANGE ise devam et
        if adx_val >= MR_ADX_HARD:
            return None
        if adx_val > MR_ADX_SOFT:
            # Geçiş bölgesi: yalnızca rejim RANGE ise izin ver
            if regime is None or regime.regime_type != RegimeType.RANGE:
                return None

        last_close = float(close[-1])
        direction: SignalType | None = None

        # Long: RSI < 20 + BB alt bant teması + W%R < -80 (C3)
        if rsi_val < MR_RSI_OVERSOLD and last_close <= bb_low:
            if wr_val is not None and wr_val < -80.0:
                direction = SignalType.BUY
        # Short: RSI > 80 + BB üst bant teması + W%R > -20 (C3)
        elif rsi_val > MR_RSI_OVERBOUGHT and last_close >= bb_up:
            if wr_val is not None and wr_val > -20.0:
                direction = SignalType.SELL

        if direction is None:
            return None

        # Giriş fiyatı
        tick = self.mt5.get_tick(symbol)
        if tick is None:
            return None
        price = tick.ask if direction == SignalType.BUY else tick.bid

        # SL / TP — ÜSTAT strateji havuzundan dinamik parametre
        mr_sl_mult = self._get_ustat_param("sl_atr_mult", MR_SL_ATR_MULT)

        # v14: TP hedefi BB_mid + 0.3×ATR (BB_mid tek başına çok konservatif)
        if direction == SignalType.BUY:
            sl = bb_low - mr_sl_mult * atr_val
            tp = bb_mid + 0.3 * atr_val
        else:
            sl = bb_up + mr_sl_mult * atr_val
            tp = bb_mid - 0.3 * atr_val

        # Sinyal gücü: RSI aşırılık (0-0.5) + BB temas (0-0.3) + ADX zayıflık (0-0.2)
        if direction == SignalType.BUY:
            rsi_str = min((MR_RSI_OVERSOLD - rsi_val) / 30.0, 0.5)
            bb_touch = min((bb_low - last_close) / atr_val if atr_val > 0 else 0.0, 0.3)
        else:
            rsi_str = min((rsi_val - MR_RSI_OVERBOUGHT) / 30.0, 0.5)
            bb_touch = min((last_close - bb_up) / atr_val if atr_val > 0 else 0.0, 0.3)

        adx_str = min((MR_ADX_THRESHOLD - adx_val) / 20.0, 0.2)
        strength = max(rsi_str, 0.0) + max(bb_touch, 0.0) + max(adx_str, 0.0)

        return Signal(
            symbol=symbol,
            signal_type=direction,
            price=price,
            sl=sl,
            tp=tp,
            strength=min(strength, 1.0),
            reason=(
                f"MEAN_REVERSION: RSI={rsi_val:.1f} "
                f"ADX={adx_val:.1f} BB_touch"
            ),
            strategy=StrategyType.MEAN_REVERSION,
        )

    # ── Breakout ──────────────────────────────────────────────────

    def _check_breakout(
        self,
        symbol: str,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
    ) -> Signal | None:
        """Breakout sinyali kontrolü.

        Long: 20-bar high kırılımı + hacim > ort×1.5 + ATR genişleme
        Short: 20-bar low kırılımı + hacim > ort×1.5 + ATR genişleme
        Hacim filtresi ZORUNLU.
        """
        if len(close) < BO_LOOKBACK + 2:
            return None

        atr_arr = calc_atr(high, low, close, ATR_PERIOD)
        atr_val = last_valid(atr_arr)
        if atr_val is None or atr_val <= 0:
            return None

        # 20-bar high/low (son bar hariç)
        lookback_high = high[-(BO_LOOKBACK + 1):-1]
        lookback_low = low[-(BO_LOOKBACK + 1):-1]
        valid_high = lookback_high[~np.isnan(lookback_high)]
        valid_low = lookback_low[~np.isnan(lookback_low)]

        if len(valid_high) == 0 or len(valid_low) == 0:
            return None

        high_20 = float(np.max(valid_high))
        low_20 = float(np.min(valid_low))

        # Hacim kontrolü (ZORUNLU)
        lookback_vol = volume[-(BO_LOOKBACK + 1):-1]
        valid_vol = lookback_vol[~np.isnan(lookback_vol)]
        if len(valid_vol) == 0:
            return None
        vol_avg = float(np.mean(valid_vol))
        current_vol = float(volume[-1])

        liq_class = self._get_liq_class(symbol)
        vol_mult = BO_VOLUME_MULT_BY_CLASS.get(liq_class, BO_VOLUME_MULT)
        if vol_avg <= 0 or current_vol <= vol_avg * vol_mult:
            return None

        # ATR genişleme kontrolü
        atr_valid = atr_arr[~np.isnan(atr_arr)]
        if len(atr_valid) < 5:
            return None
        atr_mean = float(np.mean(atr_valid[:-1])) if len(atr_valid) > 1 else atr_val
        atr_exp = BO_ATR_EXPANSION_BY_CLASS.get(liq_class, BO_ATR_EXPANSION)
        if atr_mean <= 0 or atr_val <= atr_mean * atr_exp:
            return None

        last_close = float(close[-1])
        direction: SignalType | None = None

        if last_close > high_20:
            direction = SignalType.BUY
        elif last_close < low_20:
            direction = SignalType.SELL

        if direction is None:
            return None

        # Giriş fiyatı
        tick = self.mt5.get_tick(symbol)
        if tick is None:
            return None
        price = tick.ask if direction == SignalType.BUY else tick.bid

        # SL / TP — ÜSTAT strateji havuzundan dinamik parametre
        bo_sl_mult = self._get_ustat_param("sl_atr_mult", BO_SL_ATR_MULT)
        range_width = high_20 - low_20
        # Fix M15: Çok dar range → TP=entry olur, anlamsız işlem → reddet
        if range_width < atr_val * 0.5:
            logger.warning(
                f"Breakout range çok dar [{symbol}]: "
                f"range={range_width:.4f} < ATR*0.5={atr_val*0.5:.4f} "
                f"→ sinyal reddedildi"
            )
            return None

        if direction == SignalType.BUY:
            sl = last_close - bo_sl_mult * atr_val
            tp = price + range_width
        else:
            sl = last_close + bo_sl_mult * atr_val
            tp = price - range_width

        # Sinyal gücü: hacim patlaması (0-0.5) + ATR genişleme (0-0.3) + kırılım büyüklüğü (0-0.2)
        # A2 fix: likidite sınıfı bazlı eşikler kullanılıyor (global sabit yerine)
        vol_str = min((current_vol / vol_avg - vol_mult) / 2.0, 0.5)
        atr_str = min((atr_val / atr_mean - atr_exp) / 1.0, 0.3)
        if direction == SignalType.BUY:
            break_size = (last_close - high_20) / atr_val if atr_val > 0 else 0.0
        else:
            break_size = (low_20 - last_close) / atr_val if atr_val > 0 else 0.0
        break_str = min(break_size * 0.2, 0.2)

        strength = max(vol_str, 0.0) + max(atr_str, 0.0) + max(break_str, 0.0)

        # C2: Squeeze çıkışında bonus — sıkışma sonrası kırılım daha güvenilir
        squeeze_arr = bb_kc_squeeze(high, low, close)
        squeeze_bonus = 0.0
        if len(squeeze_arr) >= 3:
            # Son 3 bar'dan en az 1'i squeeze ise → yakın zamanda sıkışma vardı
            recent_squeeze = squeeze_arr[-3:]
            valid_sq = recent_squeeze[~np.isnan(recent_squeeze)]
            if len(valid_sq) > 0 and np.any(valid_sq == 1.0):
                squeeze_bonus = 0.15
                strength += squeeze_bonus

        return Signal(
            symbol=symbol,
            signal_type=direction,
            price=price,
            sl=sl,
            tp=tp,
            strength=min(strength, 1.0),
            reason=(
                f"BREAKOUT: {'high' if direction == SignalType.BUY else 'low'} "
                f"kırılım vol={current_vol/vol_avg:.1f}× "
                f"ATR_exp={atr_val/atr_mean:.2f}"
            ),
            strategy=StrategyType.BREAKOUT,
        )

    # ── H1 Onay ──────────────────────────────────────────────────

    def _confirm_h1(self, symbol: str, signal: Signal) -> bool:
        """H1 zaman diliminde trend onayı (sadece trend follow).

        BUY → H1 EMA(20) > EMA(50)
        SELL → H1 EMA(20) < EMA(50)

        Args:
            symbol: Kontrat sembolü.
            signal: Onaylanacak sinyal.

        Returns:
            True ise H1 onaylı.
        """
        df = self.db.get_bars(symbol, "H1", limit=MIN_BARS_H1)
        if df.empty or len(df) < TF_EMA_SLOW + 1:
            return False

        close_h1 = df["close"].values.astype(np.float64)
        ema_fast_h1 = ema(close_h1, TF_EMA_FAST)
        ema_slow_h1 = ema(close_h1, TF_EMA_SLOW)

        ef = last_valid(ema_fast_h1)
        es = last_valid(ema_slow_h1)

        if ef is None or es is None:
            return False

        if signal.signal_type == SignalType.BUY:
            return ef > es
        elif signal.signal_type == SignalType.SELL:
            return ef < es

        return False

    # ═════════════════════════════════════════════════════════════════
    #  EMİR YÜRÜTME
    # ═════════════════════════════════════════════════════════════════

    def _execute_signal(self, signal: Signal, regime: Regime) -> None:
        """Sinyali state-machine ile emir akışına sok.

        SIGNAL → PENDING → SENT (LIMIT emir).

        Args:
            signal: Çalıştırılacak sinyal.
            regime: Mevcut rejim.
        """
        symbol = signal.symbol
        direction = "BUY" if signal.signal_type == SignalType.BUY else "SELL"
        now = datetime.now()

        # ── PAPER TRADING MODU ──────────────────────────────────────
        # Paper mode aktifken sinyal log'lanır, DB'ye kaydedilir ama
        # MT5'e emir gönderilmez. Parametre değişikliklerini güvenle
        # test etmek için kullanılır.
        if self.config.get("engine.paper_mode", False):
            logger.info(
                f"[PAPER] Sinyal üretildi [{symbol}]: "
                f"{direction} strateji={signal.strategy.value} "
                f"güç={signal.strength:.2f} "
                f"fiyat={signal.price:.4f} "
                f"SL={signal.sl:.4f} TP={signal.tp:.4f} "
                f"rejim={regime.regime_type.value}"
            )
            self.db.insert_event(
                event_type="PAPER_TRADE",
                message=(
                    f"Paper sinyal: {direction} {symbol} "
                    f"strateji={signal.strategy.value} "
                    f"güç={signal.strength:.2f} "
                    f"SL={signal.sl:.4f} TP={signal.tp:.4f}"
                ),
                severity="INFO",
                action="paper_trade",
            )
            return

        # ── FAZ 1: SIGNAL ────────────────────────────────────────────
        trade = Trade(
            symbol=symbol,
            direction=direction,
            volume=0.0,  # lot henüz hesaplanmadı
            entry_price=signal.price,
            sl=signal.sl,
            tp=signal.tp,
            state=TradeState.SIGNAL,
            opened_at=now,
            strategy=signal.strategy.value,
            trailing_sl=signal.sl,
            regime_at_entry=regime.regime_type.value,
        )

        # BABA onay — korelasyon kontrolü (Madde 2.1: merkezi risk_params)
        if self.baba:
            corr_verdict = self.baba.check_correlation_limits(
                symbol, direction, self.risk_params,
            )
            if not corr_verdict.can_trade:
                trade.state = TradeState.CANCELLED
                trade.cancel_reason = f"correlation: {corr_verdict.reason}"
                self._log_cancelled_trade(trade)
                return

        # ── FAZ 2: PENDING (pre-flight) ──────────────────────────────
        trade.state = TradeState.PENDING

        # İşlem saatleri kontrolü
        if not self._is_trading_allowed(now):
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = "outside_trading_hours"
            self._log_cancelled_trade(trade)
            return

        # Eş zamanlı pozisyon limiti (atomik kontrol — race condition önlemi)
        active_states = (
            TradeState.PENDING, TradeState.FILLED, TradeState.SENT,
            TradeState.PARTIAL, TradeState.MARKET_RETRY,
        )
        with self._trade_lock:
            active_count = sum(
                1 for t in self.active_trades.values()
                if t.state in active_states
            )
            if active_count >= MAX_CONCURRENT:
                trade.state = TradeState.CANCELLED
                trade.cancel_reason = (
                    f"concurrent_limit ({active_count}/{MAX_CONCURRENT})"
                )
                self._log_cancelled_trade(trade)
                return
            # Lock içinde trade'i aktif olarak işaretle (slot ayır)
            trade.state = TradeState.PENDING

        # Teminat kontrolü
        account = self.mt5.get_account_info()
        if account is None:
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = "account_info_unavailable"
            self._log_cancelled_trade(trade)
            return

        equity = account.equity
        free_margin = account.free_margin
        # v5.8/CEO-FAZ2: config'den okunan margin_reserve_pct kullanılıyor
        if equity <= 0 or free_margin < equity * self._margin_reserve_pct:
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = (
                f"margin_insufficient (free={free_margin:.0f}, "
                f"reserve={equity * self._margin_reserve_pct:.0f})"
            )
            self._log_cancelled_trade(trade)
            return

        # Lot hesaplama (evrensel yönetimde yarım lot ile giriş)
        lot = self._calculate_lot(signal, regime, equity, self.risk_params)

        # ÜSTAT lot_scale — rejime göre lot ölçekleme
        ustat_lot_scale = self._get_ustat_param("lot_scale", 1.0)
        if ustat_lot_scale != 1.0:
            lot = lot * ustat_lot_scale
            logger.debug(
                f"[ÜSTAT] lot_scale={ustat_lot_scale:.2f} uygulandı: "
                f"{signal.symbol} lot={lot:.2f}"
            )

        if lot <= 0:
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = "lot_zero"
            self._log_cancelled_trade(trade)
            return

        lot_before_fraction = lot  # Fix 2: pre-fraction lot kaydı

        if USE_UNIVERSAL_MANAGEMENT:
            # Fix 4: Lot zaten minimumda ise yarılama — piramitleme kapasitesi yok
            if lot <= 2:
                fraction = 1.0
            else:
                fraction = ENTRY_LOT_FRACTION
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
                # Fix 2+: fraction sonrası lot 0 → vol_min fallback
                # Doğru kontrol: fraction uygulanmış lot v_min'in yarısından büyükse
                # v_min'e yuvarla. Aksi halde emir iptal.
                try:
                    sym_info_f = self.mt5.get_symbol_info(signal.symbol)
                    v_min = sym_info_f.volume_min if sym_info_f else 1.0
                except Exception:
                    v_min = 1.0
                fractioned_lot = lot_before_fraction * fraction
                if fractioned_lot >= v_min * 0.5:
                    lot = v_min
                    logger.info(
                        f"ENTRY_LOT_FRACTION floor [{signal.symbol}]: "
                        f"lot=0→vol_min={v_min} "
                        f"(pre_frac={lot_before_fraction:.2f}, "
                        f"frac_lot={fractioned_lot:.2f})"
                    )
                else:
                    trade.state = TradeState.CANCELLED
                    trade.cancel_reason = "lot_zero_after_fraction"
                    logger.info(
                        f"ENTRY_LOT_FRACTION iptal [{signal.symbol}]: "
                        f"frac_lot={fractioned_lot:.2f} < v_min*0.5={v_min*0.5:.2f}"
                    )
                    self._log_cancelled_trade(trade)
                    return

        trade.volume = lot
        trade.requested_volume = lot
        trade.initial_volume = lot  # orijinal lot kaydı

        # v13.0: R-Multiple initial_risk hesapla (1R = |entry - SL| × lot × contract_size)
        if R_MULT_TRACK_ENABLED and signal.sl > 0 and signal.price > 0:
            risk_pts = abs(signal.price - signal.sl)
            contract_size = CONTRACT_SIZE
            try:
                sym_info_r = self.mt5.get_symbol_info(signal.symbol)
                if sym_info_r and hasattr(sym_info_r, "trade_contract_size"):
                    contract_size = sym_info_r.trade_contract_size
            except Exception:
                pass
            trade.initial_risk = risk_pts * lot * contract_size
            if trade.initial_risk > 0:
                logger.debug(
                    f"R-Multiple 1R={trade.initial_risk:.2f} TL [{symbol}]: "
                    f"|{signal.price:.4f}-{signal.sl:.4f}|×{lot}×{contract_size}"
                )

        # v13.0: Aylık drawdown uyarısında yeni işlem engelle
        if MONTHLY_DD_ENABLED and (self._monthly_dd_warn or self._monthly_dd_stop):
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = "monthly_dd_limit"
            logger.warning(
                f"Aylık drawdown limiti — yeni işlem engellendi [{symbol}]"
            )
            self._log_cancelled_trade(trade)
            return

        # Max slippage hesapla
        atr_val = self._get_current_atr(symbol)
        trade.max_slippage = (
            atr_val * MAX_SLIPPAGE_ATR_MULT if atr_val else 0.0
        )

        # ── FAZ 3: SENT (LIMIT emir gönder) ─────────────────────────
        # Evrensel yönetimde limit fiyat ofsetli (mum kapanışından 0.25×ATR geri)
        if USE_UNIVERSAL_MANAGEMENT and atr_val and atr_val > 0:
            if direction == "BUY":
                limit_price = signal.price - LIMIT_OFFSET_ATR * atr_val
            else:
                limit_price = signal.price + LIMIT_OFFSET_ATR * atr_val
        else:
            limit_price = signal.price

        # Fix M16: Limit fiyat güncel piyasadan çok uzaksa düzelt
        tick_check = self.mt5.get_tick(symbol)
        if tick_check and atr_val and atr_val > 0:
            market_price = tick_check.ask if direction == "BUY" else tick_check.bid
            distance = abs(limit_price - market_price)
            if distance > atr_val * 2:
                logger.warning(
                    f"Limit fiyat piyasadan uzak [{symbol}]: "
                    f"limit={limit_price:.4f} market={market_price:.4f} "
                    f"distance={distance:.4f} > 2×ATR={atr_val*2:.4f} → düzeltildi"
                )
                if direction == "BUY":
                    limit_price = market_price - LIMIT_OFFSET_ATR * atr_val
                else:
                    limit_price = market_price + LIMIT_OFFSET_ATR * atr_val

        trade.limit_price = limit_price
        result = self.mt5.send_order(
            symbol=symbol,
            direction=direction,
            lot=lot,
            price=limit_price,
            sl=signal.sl,
            tp=signal.tp,
            order_type="limit",
        )

        if result is None:
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = "send_order_failed"
            self._log_cancelled_trade(trade)
            self.db.insert_event(
                event_type="TRADE_ERROR",
                message=f"Emir başarısız: {symbol} {direction} {lot} lot",
                severity="ERROR",
                action="order_failed",
            )
            return

        # v5.8/CEO-FAZ1: Korumasız pozisyon kontrolü — SL/TP eklenememiş + kapatılamamış
        if result.get("unprotected_position"):
            logger.critical(
                f"KORUMASIZ POZİSYON TESPİT EDİLDİ [{symbol}] — "
                f"BABA'ya bildiriliyor, yeni işlem durdurulacak"
            )
            self.baba.report_unprotected_position(
                symbol=symbol,
                ticket=result.get("position_ticket", result.get("order", 0)),
            )

        # Başarılı → SENT
        trade.state = TradeState.SENT
        trade.order_ticket = result.get("order", 0)
        trade.sent_at = now

        # DB kayıt
        db_id = self.db.insert_trade({
            "strategy": signal.strategy.value,
            "symbol": symbol,
            "direction": direction,
            "entry_time": now.isoformat(),
            "entry_price": signal.price,
            "lot": lot,
            "regime": regime.regime_type.value,
        })
        trade.db_id = db_id

        # Aktif işlemlere ekle
        self.active_trades[symbol] = trade

        # Event kaydet
        self.db.insert_event(
            event_type="ORDER_SENT",
            message=(
                f"LIMIT emir gönderildi: {direction} {lot} lot {symbol} "
                f"@ {signal.price:.4f} SL={signal.sl:.4f} TP={signal.tp:.4f} "
                f"strateji={signal.strategy.value} "
                f"order_ticket={trade.order_ticket}"
            ),
            severity="INFO",
            action="order_sent",
        )

        logger.info(
            f"LIMIT emir gönderildi [{symbol}]: {direction} {lot} lot "
            f"@ {signal.price:.4f} order_ticket={trade.order_ticket}"
        )

    # ═════════════════════════════════════════════════════════════════
    #  MANUEL İŞLEM — ManuelMotor'a taşındı (v14.0)
    # ═════════════════════════════════════════════════════════════════

    # ── Yardımcı metodlar ─────────────────────────────────────────

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
        # Confluence skoru yüksekse → daha büyük lot (güçlü inanç)
        # Düşükse → daha küçük lot (düşük inanç)
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
                        logger.warning(
                            f"Confluence skor sınır dışı [{signal.symbol}]: "
                            f"{conf.total_score:.0f} → clamp [0,100]"
                        )
                        conf.total_score = max(0.0, min(100.0, conf.total_score))

                    if conf.total_score >= CONVICTION_HIGH_THRESHOLD:
                        conv_mult = CONVICTION_HIGH_MULT
                    elif conf.total_score >= CONVICTION_MED_THRESHOLD:
                        conv_mult = CONVICTION_MED_MULT
                    else:
                        conv_mult = CONVICTION_LOW_MULT

                    lot_before = lot
                    lot = lot * conv_mult
                    logger.info(
                        f"[FAZ3] Conviction sizing [{signal.symbol}]: "
                        f"conf={conf.total_score:.0f} → ×{conv_mult} "
                        f"lot {lot_before:.2f}→{lot:.2f}"
                    )
        except Exception as exc:
            logger.warning(f"[FAZ3] Conviction sizing hatası [{signal.symbol}]: {exc}")

        # v14: Lot çarpan yığılması koruması — tüm çarpanlar sonrası
        # lot hâlâ pozitifse minimum 1.0 lot (vol_min) uygula
        if 0 < lot < 1.0:
            logger.info(
                f"Lot floor [{signal.symbol}]: {lot:.3f}→1.0 "
                f"(çarpan yığılması koruması)"
            )
            lot = 1.0

        return min(lot, MAX_LOT_PER_CONTRACT)

    def _get_current_atr(self, symbol: str) -> float | None:
        """Sembol için güncel ATR(14) değeri.

        Returns:
            ATR değeri veya veri yoksa None.
        """
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < ATR_PERIOD + 1:
            return None

        close = df["close"].values.astype(np.float64)
        high_arr = df["high"].values.astype(np.float64)
        low_arr = df["low"].values.astype(np.float64)
        atr_arr = calc_atr(high_arr, low_arr, close, ATR_PERIOD)
        return last_valid(atr_arr)

    def _log_cancelled_trade(self, trade: Trade) -> None:
        """İptal edilen trade'i logla ve event yaz.

        Args:
            trade: İptal edilen Trade nesnesi.
        """
        self.db.insert_event(
            event_type="ORDER_CANCELLED",
            message=(
                f"Emir iptal: {trade.direction} {trade.symbol} "
                f"neden={trade.cancel_reason}"
            ),
            severity="WARNING",
            action="order_cancelled",
        )
        logger.info(
            f"Emir iptal [{trade.symbol}]: {trade.cancel_reason}"
        )

    def _remove_trade(
        self,
        symbol: str,
        trade: Trade,
        reason: str,
    ) -> None:
        """Trade'i active_trades'den sil ve DB güncelle.

        Args:
            symbol: Kontrat sembolü.
            trade: Silinecek Trade nesnesi.
            reason: Silme nedeni.
        """
        trade.state = TradeState.CANCELLED
        trade.cancel_reason = reason

        if trade.db_id > 0:
            self.db.update_trade(trade.db_id, {
                "exit_time": datetime.now().isoformat(),
                "exit_reason": reason,
            })

        self.db.insert_event(
            event_type="ORDER_CANCELLED",
            message=(
                f"Emir kaldırıldı: {trade.direction} {trade.symbol} "
                f"neden={reason}"
            ),
            severity="WARNING",
            action="order_removed",
        )

        self.active_trades.pop(symbol, None)
        logger.info(f"Trade kaldırıldı [{symbol}]: {reason}")

    # ═════════════════════════════════════════════════════════════════
    #  STATE MACHINE — EMİR İLERLETME
    # ═════════════════════════════════════════════════════════════════

    def _advance_orders(self, regime: Regime) -> None:
        """Bekleyen emirlerin state-machine'ini ilerlet.

        SENT → FILLED / PARTIAL / TIMEOUT
        PARTIAL → FILLED / CANCELLED
        TIMEOUT → MARKET_RETRY / CANCELLED
        MARKET_RETRY → FILLED / REJECTED

        Her cycle'da ``process_signals()`` başında çağrılır.

        Args:
            regime: Mevcut piyasa rejimi.
        """
        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]

            if trade.state == TradeState.SENT:
                self._advance_sent(symbol, trade, regime)
            elif trade.state == TradeState.PARTIAL:
                self._advance_partial(symbol, trade, regime)
            elif trade.state == TradeState.TIMEOUT:
                self._advance_timeout(symbol, trade, regime)
            elif trade.state == TradeState.MARKET_RETRY:
                self._advance_market_retry(symbol, trade, regime)

    def _advance_sent(
        self,
        symbol: str,
        trade: Trade,
        regime: Regime,
    ) -> None:
        """SENT state ilerletme — emir dolum kontrolü.

        Args:
            symbol: Kontrat sembolü.
            trade: SENT state'teki Trade.
            regime: Mevcut rejim.
        """
        status = self.mt5.check_order_status(trade.order_ticket)

        if status is None:
            # MT5 yanıt yok — timeout kontrolü
            if trade.sent_at and (
                datetime.now() - trade.sent_at
            ).total_seconds() > ORDER_TIMEOUT_SEC:
                trade.state = TradeState.TIMEOUT
                logger.warning(
                    f"Emir timeout (yanıt yok) [{symbol}]: "
                    f"order_ticket={trade.order_ticket}"
                )
            return

        order_status = status["status"]

        if order_status == "filled":
            trade.state = TradeState.FILLED
            # Netting modda position_ticket kullan (close_position bunu bekler)
            # Fix Y5: position_ticket yoksa uyarı logla — fallback ticket
            #         ile close_position başarısız olabilir
            pos_ticket = status.get("position_ticket")
            if pos_ticket:
                trade.ticket = pos_ticket
            else:
                fallback_ticket = status.get("deal_ticket", trade.order_ticket)
                trade.ticket = fallback_ticket
                logger.warning(
                    f"Netting: position_ticket yok [{symbol}], "
                    f"fallback ticket={fallback_ticket} kullanılıyor — "
                    f"close_position başarısız olabilir"
                )
            trade.filled_volume = status.get(
                "filled_volume", trade.volume,
            )
            trade.volume = trade.filled_volume
            self._update_fill_price(symbol, trade)
            logger.info(
                f"LIMIT emir doldu [{symbol}]: position_ticket={trade.ticket}"
            )
            self.db.insert_event(
                event_type="ORDER_FILLED",
                message=(
                    f"Emir doldu: {trade.direction} {trade.volume} lot "
                    f"{symbol} ticket={trade.ticket}"
                ),
                severity="INFO",
                action="order_filled",
            )
            # Günlük işlem sayacı — sadece gerçek dolumda artır
            if self.baba:
                self.baba.increment_daily_trade_count()

        elif order_status == "partial":
            trade.state = TradeState.PARTIAL
            trade.filled_volume = status.get("filled_volume", 0.0)
            logger.info(
                f"Kısmi dolum [{symbol}]: "
                f"{trade.filled_volume}/{trade.requested_volume} lot"
            )

        elif order_status == "pending":
            # Hâlâ bekliyor — timeout kontrolü
            if trade.sent_at and (
                datetime.now() - trade.sent_at
            ).total_seconds() > ORDER_TIMEOUT_SEC:
                trade.state = TradeState.TIMEOUT
                logger.info(
                    f"LIMIT emir timeout [{symbol}]: "
                    f"order_ticket={trade.order_ticket}"
                )

        elif order_status == "cancelled":
            # Borsa tarafından iptal edilmiş
            trade.state = TradeState.TIMEOUT
            logger.warning(
                f"Emir borsa tarafından iptal edildi [{symbol}]: "
                f"order_ticket={trade.order_ticket}"
            )

    def _advance_partial(
        self,
        symbol: str,
        trade: Trade,
        regime: Regime,
    ) -> None:
        """PARTIAL state ilerletme — kısmi dolum değerlendirme.

        ≥%50 dolum → kabul (FILLED).
        <%50 dolum → kısmi pozisyonu kapat (CANCELLED).

        Args:
            symbol: Kontrat sembolü.
            trade: PARTIAL state'teki Trade.
            regime: Mevcut rejim.
        """
        # Kalan bekleyen emri iptal et
        try:
            self.mt5.cancel_order(trade.order_ticket)
        except Exception as exc:
            logger.error(f"cancel_order hatası [{symbol}] ticket={trade.order_ticket}: {exc}")

        threshold = trade.requested_volume * 0.5

        if trade.filled_volume >= threshold:
            # Kabul — kısmi dolum yeterli
            trade.state = TradeState.FILLED
            trade.volume = trade.filled_volume
            self._update_fill_price(symbol, trade)
            logger.info(
                f"Kısmi dolum kabul [{symbol}]: "
                f"{trade.filled_volume}/{trade.requested_volume} lot"
            )
            self.db.insert_event(
                event_type="ORDER_FILLED",
                message=(
                    f"Kısmi dolum kabul: {trade.filled_volume} lot "
                    f"{symbol} (istek: {trade.requested_volume})"
                ),
                severity="INFO",
                action="partial_accepted",
            )
            # Günlük işlem sayacı — kısmi dolum kabul edildi
            if self.baba:
                self.baba.increment_daily_trade_count()
        else:
            # Yetersiz — kısmi pozisyonu kapat
            if trade.ticket:
                try:
                    self.mt5.close_position(trade.ticket)
                except Exception as exc:
                    logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
            self._remove_trade(
                symbol, trade,
                f"partial_insufficient "
                f"({trade.filled_volume}/{trade.requested_volume})",
            )

    def _advance_timeout(
        self,
        symbol: str,
        trade: Trade,
        regime: Regime,
    ) -> None:
        """TIMEOUT state ilerletme — market retry veya iptal.

        VOLATILE/OLAY → market emir YASAK → CANCELLED.
        TREND/RANGE → market retry (max 1 kez).

        Args:
            symbol: Kontrat sembolü.
            trade: TIMEOUT state'teki Trade.
            regime: Mevcut rejim.
        """
        # Bekleyen emri iptal et (v5.5.1: 3 deneme ile retry)
        cancel_ok = False
        for _cancel_try in range(1, 4):
            try:
                self.mt5.cancel_order(trade.order_ticket)
                cancel_ok = True
                break
            except Exception as exc:
                logger.error(
                    f"cancel_order hatası [{symbol}] ticket={trade.order_ticket} "
                    f"deneme {_cancel_try}/3: {exc}"
                )
                if _cancel_try < 3:
                    import time as _time
                    _time.sleep(0.5)

        if not cancel_ok:
            logger.error(
                f"cancel_order 3 denemede başarısız [{symbol}] "
                f"ticket={trade.order_ticket} — sync_positions düzeltmeli"
            )

        # VOLATILE/OLAY rejimde market emir yasak
        if trade.regime_at_entry in ("VOLATILE", "OLAY"):
            self._remove_trade(
                symbol, trade,
                f"timeout_no_market_retry "
                f"(regime={trade.regime_at_entry})",
            )
            return

        # Max retry kontrolü
        if trade.retry_count >= 1:
            self._remove_trade(
                symbol, trade, "timeout_max_retry_reached",
            )
            return

        # Market emir gönder
        result = self.mt5.send_order(
            symbol=symbol,
            direction=trade.direction,
            lot=trade.volume,
            price=trade.limit_price,
            sl=trade.sl,
            tp=trade.tp,
            order_type="market",
        )

        if result is None:
            trade.state = TradeState.REJECTED
            trade.cancel_reason = "market_retry_failed"
            self._remove_trade(symbol, trade, "market_retry_send_failed")
            return

        # Market retry başarılı — order ticket'ı kaydet
        trade.state = TradeState.MARKET_RETRY
        trade.order_ticket = result.get("order", 0)
        trade.retry_count += 1

        logger.info(
            f"Market retry [{symbol}]: order_ticket={trade.order_ticket}"
        )
        self.db.insert_event(
            event_type="MARKET_RETRY",
            message=(
                f"Market retry: {trade.direction} {trade.volume} lot "
                f"{symbol} ticket={trade.ticket}"
            ),
            severity="INFO",
            action="market_retry",
        )

    def _advance_market_retry(
        self,
        symbol: str,
        trade: Trade,
        regime: Regime,
    ) -> None:
        """MARKET_RETRY state ilerletme — dolum ve slippage kontrolü.

        Dolum var → slippage kontrol → kabul veya red.
        Dolum yok → REJECTED.

        Args:
            symbol: Kontrat sembolü.
            trade: MARKET_RETRY state'teki Trade.
            regime: Mevcut rejim.
        """
        # MT5'te pozisyon var mı? (Netting: sembol bazlı eşleştir)
        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası [{symbol}]: {exc}")
            positions = []
        pos = next(
            (p for p in positions if p.get("symbol") == symbol),
            None,
        )

        if pos is None:
            # Pozisyon oluşmadı
            self._remove_trade(
                symbol, trade, "market_retry_no_position",
            )
            return

        # Pozisyon ticket'ını kaydet (close_position için gerekli)
        trade.ticket = pos.get("ticket", 0)

        # Dolum fiyatı ve slippage kontrolü
        fill_price = pos.get("price_open", 0.0)
        slippage = abs(fill_price - trade.limit_price)

        if trade.max_slippage > 0 and slippage > trade.max_slippage:
            # Slippage aşımı — pozisyonu kapat
            logger.warning(
                f"Slippage aşımı [{symbol}]: "
                f"fill={fill_price:.4f} limit={trade.limit_price:.4f} "
                f"slippage={slippage:.4f} max={trade.max_slippage:.4f}"
            )
            try:
                self.mt5.close_position(trade.ticket)
            except Exception as exc:
                logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
            self._remove_trade(
                symbol, trade,
                f"slippage_exceeded "
                f"({slippage:.4f}>{trade.max_slippage:.4f})",
            )
            return

        # Kabul — dolum başarılı
        trade.state = TradeState.FILLED
        trade.entry_price = fill_price
        trade.filled_volume = trade.volume
        # Günlük işlem sayacı — market retry dolum
        if self.baba:
            self.baba.increment_daily_trade_count()

        if trade.db_id > 0:
            self.db.update_trade(trade.db_id, {
                "entry_price": fill_price,
            })

        logger.info(
            f"Market retry dolum [{symbol}]: "
            f"fill_price={fill_price:.4f} slippage={slippage:.4f}"
        )
        self.db.insert_event(
            event_type="ORDER_FILLED",
            message=(
                f"Market retry dolum: {trade.direction} {trade.volume} lot "
                f"{symbol} @ {fill_price:.4f}"
            ),
            severity="INFO",
            action="market_retry_filled",
        )

    def _update_fill_price(self, symbol: str, trade: Trade) -> None:
        """MT5 pozisyondan gerçek dolum fiyatını al ve DB güncelle.

        Netting mode: sembol bazlı eşleştirme (ticket değişebilir).

        Args:
            symbol: Kontrat sembolü.
            trade: Güncellenecek Trade.
        """
        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası [{symbol}] (fill_price): {exc}")
            return
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

    # ═════════════════════════════════════════════════════════════════
    #  İŞLEM SAATLERİ VE GÜN SONU
    # ═════════════════════════════════════════════════════════════════

    def _is_trading_allowed(
        self,
        now: datetime | None = None,
    ) -> bool:
        """İşlem saatleri içinde olup olmadığını kontrol et.

        09:45-17:45 arası + piyasa açık (hafta içi, tatil değil).

        Args:
            now: Kontrol zamanı (varsayılan: şu an).

        Returns:
            İşlem yapılabilir ise True.
        """
        if now is None:
            now = datetime.now()

        from engine.utils.time_utils import is_market_open
        if not is_market_open(now):
            return False

        current_time = now.time()
        return TRADING_OPEN <= current_time <= TRADING_CLOSE

    def _check_end_of_day(
        self,
        now: datetime | None = None,
    ) -> None:
        """Gün sonu kontrolü — 17:45 sonrası tüm pozisyon/emir kapatma.

        FILLED pozisyonlar → close_position.
        SENT/PARTIAL emirler → cancel_order + remove.

        Args:
            now: Kontrol zamanı (varsayılan: şu an).
        """
        if now is None:
            now = datetime.now()

        if now.time() < TRADING_CLOSE:
            return

        if not self.active_trades:
            return

        logger.warning(
            "Gün sonu: tüm pozisyon ve emirler kapatılıyor"
        )

        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]

            if trade.state == TradeState.FILLED:
                # Pozisyonu kapat
                try:
                    self.mt5.close_position(trade.ticket)
                except Exception as exc:
                    logger.error(f"EOD close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                self._handle_closed_trade(symbol, trade, "end_of_day")

            elif trade.state in (
                TradeState.SENT, TradeState.PARTIAL,
                TradeState.TIMEOUT, TradeState.MARKET_RETRY,
            ):
                # Bekleyen emri iptal et
                if trade.order_ticket:
                    try:
                        self.mt5.cancel_order(trade.order_ticket)
                    except Exception as exc:
                        logger.error(f"EOD cancel_order hatası [{symbol}] ticket={trade.order_ticket}: {exc}")
                # Kısmi dolum varsa pozisyonu da kapat
                if trade.ticket and trade.filled_volume > 0:
                    try:
                        self.mt5.close_position(trade.ticket)
                    except Exception as exc:
                        logger.error(f"EOD close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                self._remove_trade(symbol, trade, "end_of_day")

        # Hibrit pozisyonları da kapat (EOD)
        if self.h_engine:
            failed = self.h_engine.force_close_all(reason="EOD_17:50")
            if failed:
                logger.error(f"EOD hibrit kapatma başarısız: {failed}")

        # Manuel pozisyonları da kapat (EOD) — v14.1 düzeltme
        # Fix Y6: manuel_motor referansını yerel değişkene al (race condition koruması)
        _mm = self.manuel_motor
        if _mm and _mm.active_trades:
            trades_snapshot = dict(_mm.active_trades)  # snapshot al
            manual_count = len(trades_snapshot)
            logger.warning(
                f"EOD: {manual_count} manuel pozisyon kapatılıyor"
            )
            for sym, trade in trades_snapshot.items():
                if trade.ticket:
                    try:
                        self.mt5.close_position(trade.ticket)
                    except Exception as exc:
                        logger.error(
                            f"EOD manuel close_position hatası [{sym}] "
                            f"ticket={trade.ticket}: {exc}"
                        )
            # sync_positions bir sonraki cycle'da kapanışları tespit edecek
            # ama hemen de sync çağırabiliriz
            try:
                _mm.sync_positions()
            except Exception as exc:
                logger.error(f"EOD ManuelMotor sync hatası: {exc}")

        # v5.4.1: EOD sonrası MT5 doğrulama — hala açık pozisyon var mı?
        self._verify_eod_closure()

        self.db.insert_event(
            event_type="EOD_CLOSE",
            message="Gün sonu: tüm pozisyon ve emirler kapatıldı",
            severity="INFO",
            action="eod_close",
        )

    def _verify_eod_closure(self) -> None:
        """v5.4.1: EOD kapatım sonrası MT5 doğrulama.

        MT5'te hala açık pozisyon varsa agresif retry ile kapatır.
        Bu adım, phantom pozisyonların (DB'de kapalı, MT5'te açık) oluşmasını önler.
        """
        import time as _time
        try:
            remaining = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"EOD doğrulama — MT5 sorgu hatası: {exc}")
            return

        if not remaining:
            logger.info("EOD doğrulama: MT5'te açık pozisyon yok — OK")
            return

        logger.critical(
            f"EOD DOĞRULAMA: MT5'te hala {len(remaining)} açık pozisyon var! "
            f"Zorla kapatma başlatılıyor..."
        )

        still_open: list[int] = []
        for pos in remaining:
            ticket = pos.get("ticket")
            if not ticket:
                continue
            closed = False
            for attempt in range(1, 6):
                try:
                    result = self.mt5.close_position(ticket)
                    if result:
                        logger.info(
                            f"EOD doğrulama — ticket={ticket} kapatıldı "
                            f"(deneme {attempt}/5)"
                        )
                        closed = True
                        break
                except Exception as exc:
                    logger.error(
                        f"EOD doğrulama — close hatası ticket={ticket} "
                        f"deneme {attempt}/5: {exc}"
                    )
                _time.sleep(1)
            if not closed:
                still_open.append(ticket)

        if still_open:
            logger.critical(
                f"EOD KRİTİK: {len(still_open)} pozisyon kapatılamadı! "
                f"GECE BOYUNCA AÇIK KALACAK! Ticketlar: {still_open}"
            )
            self.db.insert_event(
                event_type="EOD_CLOSE_FAILED",
                message=(
                    f"KRİTİK: {len(still_open)} pozisyon EOD'da kapatılamadı — "
                    f"MANUEL MÜDAHALE GEREKLİ: {still_open}"
                ),
                severity="CRITICAL",
                action="eod_close_verification_failed",
            )
            # UI'a acil uyarı
            try:
                from engine.event_bus import emit as _emit
                _emit("eod_close_failed", {
                    "still_open": still_open,
                    "message": f"{len(still_open)} pozisyon gece boyunca açık kalacak!",
                })
            except Exception:
                pass
        else:
            logger.info(
                f"EOD doğrulama: tüm {len(remaining)} pozisyon başarıyla kapatıldı"
            )

    # ═════════════════════════════════════════════════════════════════
    #  AKTİF İŞLEM YÖNETİMİ
    # ═════════════════════════════════════════════════════════════════

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
        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası (manage_filled): {exc}")
            return
        pos_by_symbol: dict[str, dict] = {
            p.get("symbol"): p for p in positions
        }

        # OLAY → tüm FILLED pozisyonları kapat (tam dur)
        if regime.regime_type == RegimeType.OLAY:
            for symbol in list(self.active_trades):
                trade = self.active_trades[symbol]
                if trade.state != TradeState.FILLED:
                    continue
                try:
                    close_result = self.mt5.close_position(trade.ticket)
                except Exception as exc:
                    logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                    close_result = None
                reason = "regime_olay"
                if close_result:
                    logger.warning(
                        f"Rejim değişimi kapanış [{symbol}]: {reason}"
                    )
                self._handle_closed_trade(symbol, trade, reason)
            return

        # v14: VOLATILE → kârdaki pozisyonları koru, zarardakileri kapat
        if regime.regime_type == RegimeType.VOLATILE:
            for symbol in list(self.active_trades):
                trade = self.active_trades[symbol]
                if trade.state != TradeState.FILLED:
                    continue
                pos = pos_by_symbol.get(symbol)
                if pos is None:
                    self._handle_closed_trade(symbol, trade, "sl_tp")
                    continue
                current_profit = pos.get("profit", 0.0)
                if current_profit < 0:
                    # Zarardaki pozisyonu kapat
                    try:
                        close_result = self.mt5.close_position(trade.ticket)
                    except Exception as exc:
                        logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                        close_result = None
                    if close_result:
                        logger.warning(
                            f"VOLATILE kapanış [{symbol}]: zarar={current_profit:.2f}"
                        )
                    self._handle_closed_trade(symbol, trade, "regime_volatile_loss")
                else:
                    # Kârdaki pozisyonu koru — trailing stop ile yönetilmeye devam
                    logger.info(
                        f"VOLATILE koruma [{symbol}]: kâr={current_profit:.2f} — "
                        f"trailing stop ile yönetilecek"
                    )
                    self._manage_position(symbol, trade, pos)
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

            # Pozisyon senkronizasyonu (netting: lot/fiyat değişebilir)
            pos_ticket = pos.get("ticket", 0)
            if pos_ticket and pos_ticket != trade.ticket:
                trade.ticket = pos_ticket
            pos_vol = pos.get("volume", trade.volume)
            pos_entry = pos.get("price_open", trade.entry_price)
            sync_needed = False
            if abs(pos_vol - trade.volume) > 1e-8:
                trade.volume = pos_vol
                sync_needed = True
            if abs(pos_entry - trade.entry_price) > 1e-4:
                trade.entry_price = pos_entry
                sync_needed = True
            if sync_needed and trade.db_id > 0:
                # Fix Y7: DB sync hatasını yakala — sessiz veri kaybını önle
                try:
                    self.db.update_trade(trade.db_id, {
                        "lot": trade.volume,
                        "entry_price": trade.entry_price,
                        "mt5_position_id": trade.ticket,
                    })
                except Exception as exc:
                    logger.error(
                        f"DB sync başarısız [{symbol}] db_id={trade.db_id}: {exc} "
                        f"— bellek/MT5 ile DB arasında tutarsızlık olabilir"
                    )

            # Pozisyon yönetimi (evrensel veya eski strateji bazlı)
            if USE_UNIVERSAL_MANAGEMENT:
                self._manage_position(symbol, trade, pos)
            else:
                if trade.strategy == "trend_follow":
                    self._manage_trend_follow(symbol, trade, pos)
                elif trade.strategy == "mean_reversion":
                    self._manage_mean_reversion(symbol, trade, pos)
                elif trade.strategy == "breakout":
                    self._manage_breakout(symbol, trade, pos)

    # ═════════════════════════════════════════════════════════════════
    #  EVRENSEL POZİSYON YÖNETİMİ
    # ═════════════════════════════════════════════════════════════════

    def _manage_position(
        self,
        symbol: str,
        trade: Trade,
        pos: dict[str, Any],
    ) -> None:
        """Evrensel pozisyon yönetimi — tüm stratejiler için tek metod.

        Sıra (her 10 sn, her FILLED pozisyon için):
            1. Peak profit güncelle
            2. Sinyal devam kontrolü (4 gösterge oylama)
            3. Hacim patlaması kontrolü
            4. Breakeven kontrolü (likidite sınıfı bazlı)
            5. TP1 kontrolü (1.5×ATR → yarı kapanış)
            6. Trailing stop güncelle (EMA20 - ATR × liq_mult)
            7. Geri çekilme toleransı (dinamik, volatiliteye göre)
            8. Maliyetlendirme kontrolü

        Args:
            symbol: Kontrat sembolü.
            trade: Trade nesnesi.
            pos: MT5 pozisyon sözlüğü.
        """
        current_price = pos.get("price_current", 0.0)
        if current_price <= 0:
            return

        # ── Manuel/Hibrit pozisyon güvenlik kontrolü ────────────────
        if self.manuel_motor:
            mt = self.manuel_motor.active_trades.get(symbol)
            if mt and mt.ticket and mt.ticket == trade.ticket:
                logger.debug(
                    f"Manage: {symbol} ticket={trade.ticket} manuel — atlanıyor"
                )
                return

        if self.h_engine and trade.ticket in self.h_engine.hybrid_positions:
            logger.debug(
                f"Manage: {symbol} ticket={trade.ticket} hibrit — atlanıyor"
            )
            return

        # ── Gösterge verileri (tek seferde al) ─────────────────────
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df is None or df.empty or len(df) < 30:
            return

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)

        atr_arr = calc_atr(high, low, close, period=ATR_PERIOD)
        atr_val = last_valid(atr_arr)
        if atr_val is None or atr_val <= 0:
            return

        liq_class = self._get_liq_class(symbol)

        # ── 1. Peak Profit Güncelle ────────────────────────────────
        if trade.direction == "BUY":
            current_profit_pts = current_price - trade.entry_price
        else:
            current_profit_pts = trade.entry_price - current_price
        trade.peak_profit = max(trade.peak_profit, current_profit_pts)

        # ── 1b. R-Multiple Takibi (Van Tharp) ────────────────────
        if R_MULT_TRACK_ENABLED and trade.initial_risk > 0:
            trade.r_multiple = (current_profit_pts * trade.volume * CONTRACT_SIZE) / trade.initial_risk
            # -2R felaket koruma: anında kapat
            if trade.r_multiple <= R_MULT_STOP_LOSS:
                logger.warning(
                    f"R-Multiple STOP [{symbol}]: R={trade.r_multiple:.2f} ≤ {R_MULT_STOP_LOSS}R → kapat"
                )
                try:
                    self.mt5.close_position(trade.ticket)
                except Exception as exc:
                    logger.error(f"R-mult stop kapatma hatası [{symbol}]: {exc}")
                self._handle_closed_trade(symbol, trade, f"r_multiple_stop_{trade.r_multiple:.1f}R")
                return
            # -1.5R uyarı: trailing sıkılaştır
            if trade.r_multiple <= R_MULT_WARNING and not getattr(trade, '_r_warning_sent', False):
                logger.warning(
                    f"R-Multiple UYARI [{symbol}]: R={trade.r_multiple:.2f} → trailing sıkılaştırılıyor"
                )
                trade._r_warning_sent = True

        # ── 1c. Maksimum Pozisyon Süresi Kontrolü ────────────────
        if MAX_HOLD_ENABLED and trade.opened_at:
            bars_held = int((datetime.now() - trade.opened_at).total_seconds() / 900)  # M15 bar sayısı
            if bars_held >= MAX_HOLD_BARS:
                if current_profit_pts > 0 and MAX_HOLD_PROFIT_EXIT:
                    logger.info(
                        f"Max hold süresi → kâr kapanışı [{symbol}]: "
                        f"{bars_held} bar, kâr={current_profit_pts:.4f}"
                    )
                    try:
                        self.mt5.close_position(trade.ticket)
                    except Exception as exc:
                        logger.error(f"Max hold kapatma hatası [{symbol}]: {exc}")
                    self._handle_closed_trade(symbol, trade, "max_hold_profit")
                    return
                elif current_profit_pts <= 0 and MAX_HOLD_LOSS_TIGHTEN and not trade.max_hold_warned:
                    # Zarardaysa SL'yi entry'ye sıkılaştır (breakeven)
                    trade.max_hold_warned = True
                    new_sl = trade.entry_price
                    try:
                        result = self.mt5.modify_position(trade.ticket, sl=new_sl)
                        if result:
                            trade.sl = new_sl
                            logger.info(
                                f"Max hold → SL sıkılaştırıldı [{symbol}]: "
                                f"SL={new_sl:.4f}, {bars_held} bar"
                            )
                    except Exception as exc:
                        logger.error(f"Max hold SL modify hatası [{symbol}]: {exc}")

        # ── 2. Sinyal Devam Kontrolü (4 gösterge oylama) ──────────
        voting = self._get_voting_detail(symbol)
        if trade.direction == "BUY":
            favorable = voting["buy_votes"]
            reverse = voting["sell_votes"]
        else:
            favorable = voting["sell_votes"]
            reverse = voting["buy_votes"]
        trade.voting_score = favorable

        # FAZ 3: Ağırlıklı oylama ile çıkış kararı
        w_buy = voting.get("weighted_buy", 0.0)
        w_sell = voting.get("weighted_sell", 0.0)

        if trade.direction == "BUY":
            w_favorable = w_buy
            w_reverse = w_sell
        else:
            w_favorable = w_sell
            w_reverse = w_buy

        # Ağırlıklı ters skor yeterince yüksek veya lehte çok düşük → çık
        weighted_exit = (
            w_reverse >= WEIGHTED_VOTE_EXIT_THRESHOLD
            or (w_favorable < 2.0 and reverse >= 3)
        )
        # Legacy fallback: eski 3/4 kuralı da hâlâ geçerli
        legacy_exit = (reverse >= 3 or favorable <= 1)

        if weighted_exit or legacy_exit:
            if weighted_exit:
                exit_reason = f"weighted_reversal(w_rev={w_reverse:.1f})"
            else:
                exit_reason = "signal_reversal" if reverse >= 3 else "signal_loss"
            logger.info(
                f"Oylama çıkışı [{symbol}]: lehte={favorable}(w={w_favorable:.1f}), "
                f"ters={reverse}(w={w_reverse:.1f}) → {exit_reason}"
            )
            try:
                self.mt5.close_position(trade.ticket)
            except Exception as exc:
                logger.error(f"Oylama çıkış kapatma hatası [{symbol}]: {exc}")
            self._handle_closed_trade(symbol, trade, exit_reason)
            return

        # ── 3. Hacim Patlaması Kontrolü ────────────────────────────
        spike_action = self._check_volume_spike(
            symbol, trade, volume, current_price, atr_val
        )
        if spike_action == "close":
            try:
                self.mt5.close_position(trade.ticket)
            except Exception as exc:
                logger.error(f"Hacim spike kapatma hatası [{symbol}]: {exc}")
            self._handle_closed_trade(symbol, trade, "volume_spike_adverse")
            return

        # ── 4. Breakeven Kontrolü ──────────────────────────────────
        be_threshold = BE_ATR_BY_CLASS.get(liq_class, 1.5)
        if not trade.breakeven_hit and current_profit_pts >= be_threshold * atr_val:
            try:
                tick = self.mt5.get_tick(symbol)
                spread = (tick.ask - tick.bid) if tick else 0.0
            except Exception:
                spread = 0.0

            if trade.direction == "BUY":
                new_sl = trade.entry_price + spread
            else:
                new_sl = trade.entry_price - spread

            try:
                result = self.mt5.modify_position(trade.ticket, sl=new_sl)
                if result:
                    trade.breakeven_hit = True
                    trade.sl = new_sl
                    trade.trailing_sl = max(trade.trailing_sl, new_sl) \
                        if trade.direction == "BUY" \
                        else min(trade.trailing_sl, new_sl) \
                        if trade.trailing_sl > 0 else new_sl
                    logger.info(
                        f"Breakeven çekildi [{symbol}]: SL={new_sl:.4f}, "
                        f"kâr={current_profit_pts:.4f}, eşik={be_threshold}×ATR"
                    )
                    self.db.insert_event(
                        "BREAKEVEN_SET",
                        f"{symbol} SL={new_sl:.4f} profit={current_profit_pts:.4f}",
                        severity="INFO",
                    )
            except Exception as exc:
                logger.error(f"Breakeven modify hatası [{symbol}]: {exc}")

        # ── 5. TP1 Kontrolü (1.5×ATR → yarı kapanış) ──────────────
        if not trade.tp1_hit and current_profit_pts >= TP1_ATR_MULT * atr_val:
            close_vol = round(trade.volume / 2, 2)
            # Lot step doğrulaması
            try:
                sym_info = self.mt5.get_symbol_info(symbol)
                if sym_info and hasattr(sym_info, "volume_step"):
                    step = sym_info.volume_step
                    if step > 0:
                        close_vol = round(
                            math.floor(close_vol / step) * step,
                            int(round(-math.log10(step))),
                        )
            except Exception:
                pass

            if close_vol > 0:
                try:
                    result = self.mt5.close_position_partial(
                        trade.ticket, close_vol
                    )
                    if result:
                        trade.tp1_hit = True
                        trade.tp1_price = current_price
                        if trade.initial_volume == 0.0:
                            trade.initial_volume = trade.volume
                        trade.volume -= close_vol

                        # TP'yi kaldır — kalan yarı sinyal + trailing ile yönetilir
                        try:
                            self.mt5.modify_position(trade.ticket, tp=0.0)
                        except Exception:
                            pass

                        logger.info(
                            f"TP1 tetiklendi [{symbol}]: {close_vol} lot kapatıldı, "
                            f"kalan={trade.volume:.2f}, kâr_pts={current_profit_pts:.4f}"
                        )
                        self.db.insert_event(
                            "TP1_TRIGGERED",
                            f"{symbol} closed={close_vol} remaining={trade.volume:.2f} "
                            f"profit={current_profit_pts:.4f}",
                            severity="INFO",
                        )
                        # DB güncelle
                        if trade.db_id > 0:
                            self.db.update_trade(trade.db_id, {
                                "lot": trade.volume,
                                "tp1_hit": 1,
                                "initial_volume": trade.initial_volume,
                            })
                except Exception as exc:
                    logger.error(f"TP1 kısmi kapanış hatası [{symbol}]: {exc}")

        # ── 6. Trailing Stop Güncelle (EMA20 + Swing bazlı hibrit) ──
        ema_20 = ema(close, period=TF_EMA_FAST)
        ema_val = last_valid(ema_20)
        if ema_val is not None:
            trail_mult = TRAIL_ATR_BY_CLASS.get(liq_class, 1.5)

            # Öğle arası genişletme
            now_time = datetime.now().time()
            if LUNCH_START <= now_time <= LUNCH_END:
                trail_mult *= LUNCH_TRAIL_WIDEN

            # FAZ 3: Swing-bazlı trailing — yapısal seviye ile EMA hibrit
            # En sıkı olanı (pozisyona en yakın) seçilir
            try:
                swing_sl = get_structural_sl(
                    trade.direction, current_price,
                    analyze_trend_structure(high, low, close).swing_lows,
                    analyze_trend_structure(high, low, close).swing_highs,
                    atr_val, buffer_atr_mult=0.2,
                )
            except Exception:
                swing_sl = None

            # v13.0: Chandelier Exit hesapla (varsa karıştır)
            chandelier_sl = None
            if CHANDELIER_ENABLED and len(high) >= CHANDELIER_LOOKBACK:
                if trade.direction == "BUY":
                    hh = float(np.nanmax(high[-CHANDELIER_LOOKBACK:]))
                    chandelier_sl = hh - CHANDELIER_ATR_MULT * atr_val
                else:
                    ll = float(np.nanmin(low[-CHANDELIER_LOOKBACK:]))
                    chandelier_sl = ll + CHANDELIER_ATR_MULT * atr_val

            # R-Multiple uyarısında trailing sıkılaştır
            r_tighten = 1.0
            if R_MULT_TRACK_ENABLED and getattr(trade, '_r_warning_sent', False):
                r_tighten = 0.7  # trailing'i %30 sıkılaştır

            if trade.direction == "BUY":
                ema_trailing = ema_val - trail_mult * atr_val * r_tighten
                # Swing SL varsa ve EMA trailing'den sıkıysa tercih et
                if swing_sl is not None and swing_sl > ema_trailing:
                    base_trailing = swing_sl
                else:
                    base_trailing = ema_trailing

                # Chandelier hibrit karışım
                if chandelier_sl is not None and CHANDELIER_ENABLED:
                    new_trailing = (
                        CHANDELIER_WEIGHT * chandelier_sl
                        + (1 - CHANDELIER_WEIGHT) * base_trailing
                    )
                else:
                    new_trailing = base_trailing

                # Min/Max trailing mesafe sınırı (VİOP Rapor uyumu)
                new_trailing = _clamp_trailing_distance(
                    "BUY", current_price, new_trailing,
                )

                if new_trailing > trade.trailing_sl:
                    try:
                        result = self.mt5.modify_position(
                            trade.ticket, sl=new_trailing
                        )
                        if result:
                            trade.trailing_sl = new_trailing
                            trade.sl = new_trailing
                            src = 'swing' if swing_sl and swing_sl > ema_trailing else 'ema'
                            if chandelier_sl and CHANDELIER_ENABLED:
                                src += '+chandelier'
                            logger.debug(
                                f"Trailing güncellendi [{symbol}]: "
                                f"SL={new_trailing:.4f} ({src})"
                            )
                    except Exception as exc:
                        logger.error(
                            f"Trailing modify hatası [{symbol}]: {exc}"
                        )
            else:
                ema_trailing = ema_val + trail_mult * atr_val * r_tighten
                # Swing SL varsa ve EMA trailing'den sıkıysa tercih et
                if swing_sl is not None and swing_sl < ema_trailing:
                    base_trailing = swing_sl
                else:
                    base_trailing = ema_trailing

                # Chandelier hibrit karışım
                if chandelier_sl is not None and CHANDELIER_ENABLED:
                    new_trailing = (
                        CHANDELIER_WEIGHT * chandelier_sl
                        + (1 - CHANDELIER_WEIGHT) * base_trailing
                    )
                else:
                    new_trailing = base_trailing

                # Min/Max trailing mesafe sınırı (VİOP Rapor uyumu)
                new_trailing = _clamp_trailing_distance(
                    "SELL", current_price, new_trailing,
                )

                update = False
                if trade.trailing_sl <= 0:
                    update = True
                elif new_trailing < trade.trailing_sl:
                    update = True
                if update:
                    try:
                        result = self.mt5.modify_position(
                            trade.ticket, sl=new_trailing
                        )
                        if result:
                            trade.trailing_sl = new_trailing
                            trade.sl = new_trailing
                            src = 'swing' if swing_sl and swing_sl < ema_trailing else 'ema'
                            if chandelier_sl and CHANDELIER_ENABLED:
                                src += '+chandelier'
                            logger.debug(
                                f"Trailing güncellendi [{symbol}]: "
                                f"SL={new_trailing:.4f} ({src})"
                            )
                    except Exception as exc:
                        logger.error(
                            f"Trailing modify hatası [{symbol}]: {exc}"
                        )

        # ── 7. Geri Çekilme Toleransı (dinamik) ───────────────────
        if trade.peak_profit > 0 and current_profit_pts > 0:
            price_ratio = atr_val / current_price if current_price > 0 else 0
            if price_ratio < PULLBACK_LOW_THRESHOLD:
                tolerance_pct = PULLBACK_LOW_VOL
            elif price_ratio > PULLBACK_HIGH_THRESHOLD:
                tolerance_pct = PULLBACK_HIGH_VOL
            else:
                tolerance_pct = PULLBACK_NORMAL_VOL

            pullback = trade.peak_profit - current_profit_pts
            max_pullback = trade.peak_profit * tolerance_pct
            if pullback > max_pullback:
                logger.info(
                    f"Geri çekilme toleransı aşıldı [{symbol}]: "
                    f"peak={trade.peak_profit:.4f}, "
                    f"current={current_profit_pts:.4f}, "
                    f"pullback={pullback:.4f} > max={max_pullback:.4f} "
                    f"(tolerans={tolerance_pct:.0%})"
                )
                try:
                    self.mt5.close_position(trade.ticket)
                except Exception as exc:
                    logger.error(
                        f"Pullback kapatma hatası [{symbol}]: {exc}"
                    )
                self._handle_closed_trade(
                    symbol, trade, "pullback_tolerance"
                )
                return

        # ── 8. Maliyetlendirme Kontrolü ────────────────────────────
        self._check_cost_average(symbol, trade, pos, voting, atr_val, volume)

        # ── 9. Piramitleme — Kazanan Pozisyona Ekleme (Turtle) ───
        if PYRAMID_ENABLED and trade.pyramid_count < PYRAMID_MAX_ADDS:
            self._check_pyramid_add(symbol, trade, current_price, atr_val, voting)

    def _check_pyramid_add(
        self,
        symbol: str,
        trade: Trade,
        current_price: float,
        atr_val: float,
        voting: dict,
    ) -> None:
        """Turtle-style piramitleme: kazanan pozisyona ekleme.

        Koşullar (hepsi geçerli olmalı):
            1. Kâr ≥ PYRAMID_MIN_PROFIT_ATR × ATR
            2. Son eklemeden/girişten beri ≥ PYRAMID_ATR_STEP × ATR lehine hareket
            3. Oylama 3/4+ aynı yönde
            4. Aylık drawdown uyarısı aktif değil
            5. Max ekleme sayısına ulaşılmamış
        """
        # Aylık drawdown uyarısı aktifse yeni ekleme yapma
        if self._monthly_dd_warn or self._monthly_dd_stop:
            return

        # Kâr kontrolü
        if trade.direction == "BUY":
            profit_pts = current_price - trade.entry_price
        else:
            profit_pts = trade.entry_price - current_price

        if profit_pts < PYRAMID_MIN_PROFIT_ATR * atr_val:
            return

        # Son eklemeden beri yeterli hareket
        last_price = self._pyramid_last_add.get(symbol, trade.entry_price)
        if trade.direction == "BUY":
            move = current_price - last_price
        else:
            move = last_price - current_price

        if move < PYRAMID_ATR_STEP * atr_val:
            return

        # Oylama kontrolü
        if trade.direction == "BUY":
            favorable = voting.get("buy_votes", 0)
        else:
            favorable = voting.get("sell_votes", 0)
        if favorable < 3:
            return

        # Ekleme lot hesapla
        base_vol = trade.initial_volume if trade.initial_volume > 0 else trade.volume
        add_vol = round(base_vol * PYRAMID_ADD_FRACTION, 2)

        # Lot step doğrulaması
        try:
            sym_info = self.mt5.get_symbol_info(symbol)
            if sym_info and hasattr(sym_info, "volume_step"):
                step = sym_info.volume_step
                if step > 0:
                    add_vol = round(
                        math.floor(add_vol / step) * step,
                        int(round(-math.log10(step))),
                    )
        except Exception:
            pass

        if add_vol <= 0:
            return

        # Emir gönder
        try:
            order_type = "BUY" if trade.direction == "BUY" else "SELL"
            result = self.mt5.send_market_order(
                symbol, order_type, add_vol,
                sl=trade.sl, tp=trade.tp,
                comment=f"pyramid_{trade.pyramid_count + 1}"
            )
            if result:
                trade.pyramid_count += 1
                trade.volume += add_vol
                self._pyramid_last_add[symbol] = current_price
                # Pyramid fiyatlarını kaydet
                prices = trade.pyramid_prices.split(",") if trade.pyramid_prices else []
                prices.append(f"{current_price:.4f}")
                trade.pyramid_prices = ",".join(prices)

                # Turtle SL güncelleme: tüm SL'leri yeni entry - 2×ATR'ye taşı
                if PYRAMID_SL_UPDATE:
                    if trade.direction == "BUY":
                        new_sl = current_price - 2.0 * atr_val
                    else:
                        new_sl = current_price + 2.0 * atr_val
                    try:
                        self.mt5.modify_position(trade.ticket, sl=new_sl)
                        trade.sl = new_sl
                        trade.trailing_sl = new_sl
                    except Exception:
                        pass

                logger.info(
                    f"Piramit ekleme [{symbol}]: #{trade.pyramid_count}, "
                    f"+{add_vol} lot @ {current_price:.4f}, "
                    f"toplam={trade.volume:.2f}"
                )
                self.db.insert_event(
                    "PYRAMID_ADD",
                    f"{symbol} #{trade.pyramid_count} +{add_vol}lot "
                    f"@ {current_price:.4f} total={trade.volume:.2f}",
                    severity="INFO",
                )
                if trade.db_id > 0:
                    self.db.update_trade(trade.db_id, {
                        "lot": trade.volume,
                        "pyramid_count": trade.pyramid_count,
                    })
                # BABA günlük işlem sayacı
                if self.baba:
                    self.baba.increment_daily_trade_count()
        except Exception as exc:
            logger.error(f"Piramit ekleme hatası [{symbol}]: {exc}")

    def _check_volume_spike(
        self,
        symbol: str,
        trade: Trade,
        volume: np.ndarray,
        current_price: float,
        atr_val: float,
    ) -> str | None:
        """Ani hacim patlaması kontrolü.

        Returns:
            "close": pozisyon kapatılmalı (aleyhine patlama)
            None: aksiyon gerekmez
        """
        if len(volume) < VOL_LOOKBACK + 1:
            return None

        current_vol = volume[-1]
        avg_vol = np.nanmean(volume[-(VOL_LOOKBACK + 1):-1])
        if avg_vol <= 0:
            return None

        ratio = current_vol / avg_vol
        if ratio < VOLUME_SPIKE_MULT:
            return None  # patlama yok

        # Aleyhine hareket kontrolü
        if trade.direction == "BUY":
            profit = current_price - trade.entry_price
        else:
            profit = trade.entry_price - current_price

        if profit < -0.3 * atr_val:
            # Hacim patlaması + pozisyon aleyhine → anında kapat
            logger.warning(
                f"Hacim patlaması (aleyhine) [{symbol}]: "
                f"hacim_ratio={ratio:.1f}x, kâr={profit:.4f}"
            )
            self.db.insert_event(
                "VOLUME_SPIKE_EXIT",
                f"{symbol} ratio={ratio:.1f}x adverse profit={profit:.4f}",
                severity="WARNING",
            )
            return "close"

        if ratio >= VOLUME_SPIKE_MULT and profit > 0:
            # Lehine patlama — log yaz, çıkış kararı trailing'e bırakılır
            logger.info(
                f"Hacim patlaması (lehine) [{symbol}]: "
                f"hacim_ratio={ratio:.1f}x, kâr={profit:.4f}"
            )

        return None

    def _check_cost_average(
        self,
        symbol: str,
        trade: Trade,
        pos: dict[str, Any],
        voting: dict,
        atr_val: float,
        volume: np.ndarray,
    ) -> None:
        """Maliyetlendirme (cost averaging) kontrolü.

        Şartlar (hepsi geçerli olmalı):
            1. Daha önce maliyetlendirme yapılmamış
            2. Sinyal 3/4+ aynı yönde
            3. Fiyat 1×ATR geri çekilmiş
            4. Hacim düşmüyor
            5. Toplam risk ≤ başlangıcın %120'si
        """
        # 1. Zaten yapılmışsa atla
        if trade.cost_averaged:
            return

        # 2. Oylama: 3/4+ lehte olmalı
        if trade.direction == "BUY":
            favorable = voting.get("buy_votes", 0)
        else:
            favorable = voting.get("sell_votes", 0)
        if favorable < 3:
            return

        # 3. Fiyat 1×ATR geri çekilmiş olmalı
        current_price = pos.get("price_current", 0.0)
        if trade.direction == "BUY":
            pullback = trade.entry_price - current_price
        else:
            pullback = current_price - trade.entry_price
        if pullback < AVG_PULLBACK_ATR * atr_val:
            return

        # 4. Hacim düşmüyor olmalı
        if len(volume) >= VOL_LOOKBACK + 1:
            recent_vol = np.nanmean(volume[-4:])
            avg_vol = np.nanmean(volume[-(VOL_LOOKBACK + 1):-1])
            if avg_vol > 0 and recent_vol < avg_vol:
                return  # hacim düşüyor, ekleme yapma

        # 5. Toplam risk kontrolü (≤ %120)
        initial_risk = trade.initial_volume * atr_val if trade.initial_volume > 0 \
            else trade.volume * atr_val
        add_lot = trade.volume  # mevcut lot kadar ekle (toplam max 1.0)
        total_after = trade.volume + add_lot
        if total_after > MAX_LOT_PER_CONTRACT:
            add_lot = MAX_LOT_PER_CONTRACT - trade.volume
        if add_lot <= 0:
            return

        new_total_risk = total_after * atr_val
        if new_total_risk > initial_risk * AVG_MAX_RISK_MULT:
            return

        # Spread kontrolü
        try:
            tick = self.mt5.get_tick(symbol)
            if not tick:
                return
            if trade.direction == "BUY":
                price = tick.ask
            else:
                price = tick.bid
        except Exception:
            return

        # Ekleme emri gönder (market)
        try:
            result = self.mt5.send_order(
                symbol,
                trade.direction,
                add_lot,
                price=price,
                sl=trade.sl,
                tp=trade.tp,
                order_type="market",
            )
            if result:
                old_entry = trade.entry_price
                old_vol = trade.volume
                # Yeni ortalama maliyet
                trade.entry_price = (
                    (old_entry * old_vol + price * add_lot) / (old_vol + add_lot)
                )
                trade.volume = old_vol + add_lot
                trade.cost_averaged = True
                if trade.initial_volume == 0.0:
                    trade.initial_volume = old_vol

                logger.info(
                    f"Maliyetlendirme [{symbol}]: +{add_lot} lot @ {price:.4f}, "
                    f"ort.maliyet={trade.entry_price:.4f}, "
                    f"toplam={trade.volume:.2f} lot"
                )
                self.db.insert_event(
                    "COST_AVERAGE",
                    f"{symbol} +{add_lot} lot @ {price:.4f} "
                    f"avg_entry={trade.entry_price:.4f} total={trade.volume:.2f}",
                    severity="INFO",
                )
                # DB güncelle
                if trade.db_id > 0:
                    self.db.update_trade(trade.db_id, {
                        "lot": trade.volume,
                        "entry_price": trade.entry_price,
                        "cost_averaged": 1,
                        "initial_volume": trade.initial_volume,
                    })
                # BABA günlük sayaç (ekleme de bir işlem sayılır)
                if self.baba:
                    self.baba.increment_daily_trade_count()
        except Exception as exc:
            logger.error(f"Maliyetlendirme emri hatası [{symbol}]: {exc}")

    # ═════════════════════════════════════════════════════════════════
    #  ZAMAN KURALLARI
    # ═════════════════════════════════════════════════════════════════

    def _check_time_rules(self, regime: Regime) -> None:
        """Zaman bazlı pozisyon yönetim kuralları.

        Kurallar:
            1. Yatay kontrol: son 8 mum range < 0.5×ATR → kapat
            2. Son 45 dk (17:00+): kârdaysan kapat
        """
        if not USE_UNIVERSAL_MANAGEMENT:
            return
        if not self.active_trades:
            return

        now = datetime.now()
        current_time = now.time()

        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]
            if trade.state != TradeState.FILLED:
                continue

            # ── Son 45 dk kârdaysan kapat ──────────────────────────
            if current_time >= LAST_45_MIN:
                current_price = 0.0
                try:
                    tick = self.mt5.get_tick(symbol)
                    if tick:
                        current_price = tick.bid if trade.direction == "BUY" else tick.ask
                except Exception:
                    pass

                if current_price > 0:
                    if trade.direction == "BUY":
                        profit = current_price - trade.entry_price
                    else:
                        profit = trade.entry_price - current_price

                    if profit > 0:
                        logger.info(
                            f"Son 45 dk kâr kapanışı [{symbol}]: "
                            f"kâr={profit:.4f}"
                        )
                        try:
                            self.mt5.close_position(trade.ticket)
                        except Exception as exc:
                            logger.error(
                                f"Son 45 dk kapatma hatası [{symbol}]: {exc}"
                            )
                        self._handle_closed_trade(
                            symbol, trade, "last_45min_profit"
                        )
                        continue

            # ── Yatay kontrol (2 saat = 8 × M15 mum) ──────────────
            try:
                df = self.db.get_bars(symbol, "M15", limit=FLAT_CANDLE_COUNT)
                if df is not None and len(df) >= FLAT_CANDLE_COUNT:
                    highs = df["high"].values.astype(np.float64)
                    lows = df["low"].values.astype(np.float64)
                    closes = df["close"].values.astype(np.float64)

                    candle_range = np.max(highs) - np.min(lows)
                    atr_arr = calc_atr(highs, lows, closes, period=ATR_PERIOD)
                    atr_val = last_valid(atr_arr)

                    if atr_val and atr_val > 0:
                        if candle_range < FLAT_ATR_MULT * atr_val:
                            logger.info(
                                f"Yatay piyasa [{symbol}]: range={candle_range:.4f} "
                                f"< {FLAT_ATR_MULT}×ATR={FLAT_ATR_MULT * atr_val:.4f}"
                            )
                            try:
                                self.mt5.close_position(trade.ticket)
                            except Exception as exc:
                                logger.error(
                                    f"Yatay kapatma hatası [{symbol}]: {exc}"
                                )
                            self._handle_closed_trade(
                                symbol, trade, "flat_market"
                            )
                            continue
            except Exception as exc:
                logger.error(f"Yatay kontrol hatası [{symbol}]: {exc}")

    # ═════════════════════════════════════════════════════════════════
    #  GELİŞMİŞ RİSK KURALLARI
    # ═════════════════════════════════════════════════════════════════

    def _check_advanced_risk_rules(self) -> None:
        """Gelişmiş risk kuralları — her cycle'da kontrol edilir.

        Kurallar:
            1. Günlük zarar ≥ equity'nin %3'ü → hepsini kapat, gün sonu
            1b. Aylık drawdown ≥ %6 → tüm işlemleri kapat, ay sonuna kadar dur
            2. Spread anormal (≥ ort×2) → kârdaysa kapat
            3. Gap kontrolü: açılışta SL aşılmışsa → anında kapat
        """
        if not USE_UNIVERSAL_MANAGEMENT:
            return

        # ── 0. Aylık Drawdown Takibi (v13.0) ────────────────────
        if MONTHLY_DD_ENABLED:
            try:
                today = date.today()
                account = self.mt5.get_account_info()
                if account:
                    current_equity = account.equity
                    # Ay başı equity'yi ayarla / sıfırla
                    if (self._monthly_start_date is None
                            or self._monthly_start_date.month != today.month
                            or self._monthly_start_date.year != today.year):
                        self._monthly_start_equity = current_equity
                        self._monthly_start_date = today
                        self._monthly_dd_stop = False
                        self._monthly_dd_warn = False
                        logger.info(
                            f"Aylık drawdown sıfırlandı: equity={current_equity:.0f}"
                        )

                    if self._monthly_start_equity > 0:
                        monthly_dd = (self._monthly_start_equity - current_equity) / self._monthly_start_equity

                        # %6 mutlak limit: tüm işlemleri kapat
                        if monthly_dd >= MONTHLY_DD_MAX_PCT and not self._monthly_dd_stop:
                            self._monthly_dd_stop = True
                            logger.critical(
                                f"AYLIK DRAWDOWN LİMİTİ AŞILDI: {monthly_dd:.2%} ≥ {MONTHLY_DD_MAX_PCT:.0%}"
                            )
                            self.db.insert_event(
                                "MONTHLY_DD_STOP",
                                f"dd={monthly_dd:.2%} start={self._monthly_start_equity:.0f} "
                                f"current={current_equity:.0f}",
                                severity="CRITICAL",
                                action="close_all",
                            )
                            for sym in list(self.active_trades):
                                t = self.active_trades[sym]
                                if t.state == TradeState.FILLED:
                                    try:
                                        self.mt5.close_position(t.ticket)
                                    except Exception:
                                        pass
                                    self._handle_closed_trade(sym, t, "monthly_dd_limit")
                            return

                        # %4 uyarı: yeni işlem alma
                        if monthly_dd >= MONTHLY_DD_WARN_PCT and not self._monthly_dd_warn:
                            self._monthly_dd_warn = True
                            logger.warning(
                                f"Aylık drawdown uyarısı: {monthly_dd:.2%} ≥ {MONTHLY_DD_WARN_PCT:.0%} "
                                f"→ yeni işlem alınmayacak"
                            )
                            self.db.insert_event(
                                "MONTHLY_DD_WARNING",
                                f"dd={monthly_dd:.2%}",
                                severity="WARNING",
                            )
            except Exception as exc:
                logger.error(f"Aylık drawdown kontrol hatası: {exc}")

        if not self.active_trades:
            return

        # ── 1. Günlük zarar limiti (%3 equity) ────────────────────
        if not self._daily_loss_stop:
            try:
                account = self.mt5.get_account_info()
                if account:
                    equity = account.equity
                    balance = account.balance
                    if balance > 0:
                        daily_pnl_pct = (equity - balance) / balance
                        if daily_pnl_pct <= -DAILY_LOSS_STOP_PCT:
                            logger.warning(
                                f"Günlük zarar limiti aşıldı: "
                                f"{daily_pnl_pct:.2%} ≤ -{DAILY_LOSS_STOP_PCT:.0%}"
                            )
                            self._daily_loss_stop = True
                            self.db.insert_event(
                                "DAILY_LOSS_STOP",
                                f"equity={equity:.0f} balance={balance:.0f} "
                                f"pnl={daily_pnl_pct:.2%}",
                                severity="CRITICAL",
                                action="close_all",
                            )
                            # Tüm FILLED pozisyonları kapat
                            for sym in list(self.active_trades):
                                t = self.active_trades[sym]
                                if t.state == TradeState.FILLED:
                                    try:
                                        self.mt5.close_position(t.ticket)
                                    except Exception:
                                        pass
                                    self._handle_closed_trade(
                                        sym, t, "daily_loss_limit"
                                    )
                            return
            except Exception as exc:
                logger.error(f"Günlük zarar kontrol hatası: {exc}")

        # ── 2. Spread anormalliği ──────────────────────────────────
        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]
            if trade.state != TradeState.FILLED:
                continue

            try:
                tick = self.mt5.get_tick(symbol)
                if tick and tick.spread > 0:
                    # Basit kontrol: spread çok yüksekse
                    df = self.db.get_bars(symbol, "M15", limit=20)
                    if df is not None and len(df) >= 10:
                        highs = df["high"].values.astype(np.float64)
                        lows = df["low"].values.astype(np.float64)
                        avg_range = np.nanmean(highs[-10:] - lows[-10:])
                        if avg_range > 0:
                            spread_ratio = tick.spread / avg_range
                            if spread_ratio > SPREAD_SPIKE_MULT:
                                # Kârdaysa kapat
                                if trade.direction == "BUY":
                                    profit = tick.bid - trade.entry_price
                                else:
                                    profit = trade.entry_price - tick.ask
                                if profit > 0:
                                    logger.warning(
                                        f"Spread anormal [{symbol}]: "
                                        f"ratio={spread_ratio:.1f}x, kapat"
                                    )
                                    try:
                                        self.mt5.close_position(trade.ticket)
                                    except Exception:
                                        pass
                                    self._handle_closed_trade(
                                        symbol, trade, "spread_anomaly"
                                    )
            except Exception as exc:
                logger.error(f"Spread kontrol hatası [{symbol}]: {exc}")

    # ═════════════════════════════════════════════════════════════════
    #  ESKİ STRATEJİ BAZLI YÖNETİM (feature flag=False için korunur)
    # ═════════════════════════════════════════════════════════════════

    def _manage_trend_follow(
        self,
        symbol: str,
        trade: Trade,
        pos: dict[str, Any],
    ) -> None:
        """Trend follow işlem yönetimi — EMA ihlali + trailing stop.

        Args:
            symbol: Kontrat sembolü.
            trade: Aktif Trade nesnesi.
            pos: MT5 pozisyon bilgisi.
        """
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < TF_EMA_FAST + 1:
            return

        close = df["close"].values.astype(np.float64)
        high_arr = df["high"].values.astype(np.float64)
        low_arr = df["low"].values.astype(np.float64)

        ema_20 = ema(close, TF_EMA_FAST)
        atr_arr = calc_atr(high_arr, low_arr, close, ATR_PERIOD)

        ema_val = last_valid(ema_20)
        atr_val = last_valid(atr_arr)
        current_price = float(pos.get("price_current", close[-1]))

        if ema_val is None or atr_val is None or atr_val <= 0:
            return

        # EMA(20) ihlali kontrolü
        ema_violated = False
        if trade.direction == "BUY" and current_price < ema_val:
            ema_violated = True
        elif trade.direction == "SELL" and current_price > ema_val:
            ema_violated = True

        if ema_violated:
            logger.info(
                f"EMA ihlali kapatma [{symbol}]: "
                f"fiyat={current_price:.4f} EMA(20)={ema_val:.4f}"
            )
            try:
                self.mt5.close_position(trade.ticket)
            except Exception as exc:
                logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
            self._handle_closed_trade(symbol, trade, "ema_violation")
            return

        # Trailing stop güncelleme — likidite bazlı çarpan
        liq_class = self._get_liq_class(symbol)
        trail_mult = TRAILING_ATR_BY_CLASS.get(liq_class, TF_TRAILING_ATR_MULT)
        # Başarısız modify cooldown: 5 döngü boyunca tekrar deneme
        _modify_fails = getattr(trade, "_modify_fail_count", 0)
        if _modify_fails >= 3:
            _cooldown = getattr(trade, "_modify_cooldown", 0)
            if _cooldown > 0:
                trade._modify_cooldown = _cooldown - 1
                return
            else:
                trade._modify_fail_count = 0  # Cooldown bitti, tekrar dene

        if trade.direction == "BUY":
            new_sl = current_price - trail_mult * atr_val
            new_sl = _clamp_trailing_distance("BUY", current_price, new_sl)
            if new_sl > trade.trailing_sl:
                try:
                    mod_result = self.mt5.modify_position(
                        trade.ticket, sl=new_sl,
                    )
                except Exception as exc:
                    logger.error(f"modify_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                    mod_result = None
                if mod_result:
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    trade._modify_fail_count = 0
                    logger.debug(
                        f"Trailing SL güncellendi [{symbol}]: {new_sl:.4f}"
                    )
                else:
                    trade._modify_fail_count = getattr(trade, "_modify_fail_count", 0) + 1
                    if trade._modify_fail_count >= 3:
                        trade._modify_cooldown = 10  # 10 döngü bekle
                        logger.warning(
                            f"Trailing SL modify 3x başarısız [{symbol}], "
                            f"10 döngü cooldown uygulanıyor"
                        )
        else:  # SELL
            new_sl = current_price + trail_mult * atr_val
            new_sl = _clamp_trailing_distance("SELL", current_price, new_sl)
            if new_sl < trade.trailing_sl:
                try:
                    mod_result = self.mt5.modify_position(
                        trade.ticket, sl=new_sl,
                    )
                except Exception as exc:
                    logger.error(f"modify_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                    mod_result = None
                if mod_result:
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    trade._modify_fail_count = 0
                    logger.debug(
                        f"Trailing SL güncellendi [{symbol}]: {new_sl:.4f}"
                    )
                else:
                    trade._modify_fail_count = getattr(trade, "_modify_fail_count", 0) + 1
                    if trade._modify_fail_count >= 3:
                        trade._modify_cooldown = 10
                        logger.warning(
                            f"Trailing SL modify 3x başarısız [{symbol}], "
                            f"10 döngü cooldown uygulanıyor"
                        )

    def _manage_mean_reversion(
        self,
        symbol: str,
        trade: Trade,
        pos: dict[str, Any],
    ) -> None:
        """Mean reversion işlem yönetimi — breakeven + BB orta bant kontrolü.

        A5: Kâr %50+ olduğunda SL'yi entry fiyatına çek (breakeven).
        Normalde TP MT5 tarafından yönetilir, ama programatik kontrol de
        ekleyelim — fiyat BB orta bandına ulaştıysa kapat.

        Args:
            symbol: Kontrat sembolü.
            trade: Aktif Trade nesnesi.
            pos: MT5 pozisyon bilgisi.
        """
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < MR_BB_PERIOD + 1:
            return

        close = df["close"].values.astype(np.float64)
        _, bb_middle, _ = bollinger_bands(close, MR_BB_PERIOD, MR_BB_STD)
        bb_mid = last_valid(bb_middle)

        if bb_mid is None:
            return

        current_price = float(pos.get("price_current", close[-1]))

        # A5: Breakeven trailing — kâr %50+ ise SL'yi entry'e çek
        entry = trade.entry_price
        if entry > 0 and trade.sl != entry:
            if trade.direction == "BUY":
                tp_distance = trade.tp - entry if trade.tp > 0 else 0
                current_profit = current_price - entry
            else:
                tp_distance = entry - trade.tp if trade.tp > 0 else 0
                current_profit = entry - current_price

            # TP mesafesinin %50'sine ulaştıysa breakeven
            if tp_distance > 0 and current_profit >= tp_distance * 0.5:
                try:
                    mod_result = self.mt5.modify_position(
                        trade.ticket, sl=entry,
                    )
                except Exception as exc:
                    logger.error(
                        f"MR breakeven hatası [{symbol}] "
                        f"ticket={trade.ticket}: {exc}"
                    )
                    mod_result = None
                if mod_result:
                    trade.sl = entry
                    trade.trailing_sl = entry
                    logger.info(
                        f"MR breakeven [{symbol}]: SL→entry={entry:.4f} "
                        f"(kâr={current_profit:.4f}, "
                        f"TP mesafe={tp_distance:.4f})"
                    )

        # BB orta banda ulaşım kontrolü
        reached_target = False
        if trade.direction == "BUY" and current_price >= bb_mid:
            reached_target = True
        elif trade.direction == "SELL" and current_price <= bb_mid:
            reached_target = True

        if reached_target:
            logger.info(
                f"BB orta bant ulaşımı [{symbol}]: "
                f"fiyat={current_price:.4f} BB_mid={bb_mid:.4f}"
            )
            try:
                self.mt5.close_position(trade.ticket)
            except Exception as exc:
                logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
            self._handle_closed_trade(symbol, trade, "bb_middle_reached")

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
        atr_val = last_valid(atr_arr)
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
            try:
                self.mt5.close_position(trade.ticket)
            except Exception as exc:
                logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
            self._handle_closed_trade(symbol, trade, "false_breakout")
            return

        # ── Trailing stop (A3: likidite sınıfı bazlı) ─────────────
        liq_class = self._get_liq_class(symbol)
        trail_mult = TRAILING_ATR_BY_CLASS.get(liq_class, BO_TRAILING_ATR_MULT)

        if trade.direction == "BUY":
            new_sl = current_price - trail_mult * atr_val
            new_sl = _clamp_trailing_distance("BUY", current_price, new_sl)
            if new_sl > trade.trailing_sl:
                try:
                    mod_result = self.mt5.modify_position(
                        trade.ticket, sl=new_sl,
                    )
                except Exception as exc:
                    logger.error(f"modify_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                    mod_result = None
                if mod_result:
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    logger.debug(
                        f"Breakout trailing SL [{symbol}] "
                        f"(liq={liq_class}, mult={trail_mult}): {new_sl:.4f}"
                    )
        else:
            new_sl = current_price + trail_mult * atr_val
            new_sl = _clamp_trailing_distance("SELL", current_price, new_sl)
            if new_sl < trade.trailing_sl:
                try:
                    mod_result = self.mt5.modify_position(
                        trade.ticket, sl=new_sl,
                    )
                except Exception as exc:
                    logger.error(f"modify_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                    mod_result = None
                if mod_result:
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    logger.debug(
                        f"Breakout trailing SL [{symbol}] "
                        f"(liq={liq_class}, mult={trail_mult}): {new_sl:.4f}"
                    )

    # ═════════════════════════════════════════════════════════════════
    #  POZİSYON SENKRONİZASYONU
    # ═════════════════════════════════════════════════════════════════

    def _sync_positions(self) -> None:
        """MT5 pozisyonları ile active_trades senkronize et.

        Netting modda sembol bazlı kontrol: MT5'te o sembolde
        açık pozisyon yoksa → harici kapanmış → DB güncelle.
        """
        if not self.active_trades:
            return

        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası (sync): {exc}")
            return
        open_symbols = {p.get("symbol") for p in positions}

        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]
            # Sadece dolu pozisyonları senkronize et
            if trade.state != TradeState.FILLED:
                continue
            if symbol not in open_symbols:
                logger.info(
                    f"Pozisyon harici kapanmış [{symbol}]: ticket={trade.ticket}"
                )
                self._handle_closed_trade(symbol, trade, "external_close")

    def _handle_closed_trade(
        self,
        symbol: str,
        trade: Trade,
        exit_reason: str,
    ) -> None:
        """Kapanmış işlemi işle — state güncelle, DB yaz, active_trades'den sil.

        Args:
            symbol: Kontrat sembolü.
            trade: Kapanan Trade nesnesi.
            exit_reason: Kapanış nedeni.
        """
        now = datetime.now()
        trade.state = TradeState.CLOSED
        trade.closed_at = now

        # Son fiyatı al
        try:
            tick = self.mt5.get_tick(symbol)
        except Exception as exc:
            logger.error(f"get_tick hatası [{symbol}]: {exc}")
            tick = None
        if tick:
            if trade.direction == "BUY":
                trade.exit_price = tick.bid
            else:
                trade.exit_price = tick.ask
        elif trade.exit_price == 0:
            # Fallback: en son bar kapanışı
            df = self.db.get_bars(symbol, "M15", limit=1)
            if not df.empty:
                trade.exit_price = float(df["close"].values[-1])

        # PnL hesapla — önce fiyat farkından (fallback)
        if trade.entry_price > 0 and trade.exit_price > 0:
            contract_size = CONTRACT_SIZE  # varsayılan fallback
            sym_info = self.mt5.get_symbol_info(symbol)
            if sym_info and hasattr(sym_info, "trade_contract_size"):
                contract_size = sym_info.trade_contract_size

            if trade.direction == "BUY":
                trade.pnl = (trade.exit_price - trade.entry_price) * trade.volume * contract_size
            else:
                trade.pnl = (trade.entry_price - trade.exit_price) * trade.volume * contract_size

        # MT5 deal verisinden gerçek PnL/komisyon/swap al (geçmişe yazılma gecikmesi için retry)
        commission = 0.0
        swap = 0.0
        deal_summary = None
        for attempt in range(3):
            deal_summary = self.mt5.get_deal_summary(trade.ticket)
            if deal_summary is not None:
                break
            if attempt < 2:
                _time.sleep(0.8)
        if deal_summary is not None:
            trade.pnl = deal_summary["pnl"]
            commission = deal_summary["commission"]
            swap = deal_summary["swap"]
            logger.debug(
                f"MT5 deal verisi kullanıldı [{symbol}]: "
                f"pnl={trade.pnl:.2f} comm={commission:.2f} swap={swap:.2f}"
            )

        # DB güncelle — entry_price/lot da dahil (netting değişikliği yansısın)
        if trade.db_id > 0:
            self.db.update_trade(trade.db_id, {
                "exit_time": now.isoformat(),
                "exit_price": trade.exit_price,
                "entry_price": trade.entry_price,
                "lot": trade.volume,
                "pnl": trade.pnl,
                "exit_reason": exit_reason,
                "mt5_position_id": trade.ticket,
                "commission": commission,
                "swap": swap,
            })

        # Event kaydet
        self.db.insert_event(
            event_type="TRADE_CLOSE",
            message=(
                f"İşlem kapandı: {trade.direction} {trade.volume} lot {symbol} "
                f"@ {trade.exit_price:.4f} PnL={trade.pnl:.2f} "
                f"neden={exit_reason}"
            ),
            severity="INFO",
            action="trade_closed",
        )

        logger.info(
            f"İşlem kapandı [{symbol}]: {exit_reason} "
            f"PnL={trade.pnl:.2f}"
        )

        # ── Event bus — trade_closed bildirimi ────────────────────
        from engine.event_bus import emit as _emit_event
        _emit_event("trade_closed", {
            "ticket": trade.ticket, "symbol": symbol,
            "direction": trade.direction, "pnl": trade.pnl,
            "exit_reason": exit_reason,
        })

        # ── Ardışık zarar sayacı (Faz 6) ─────────────────────────
        today = datetime.now().date()
        if self._symbol_loss_date != today:
            self._symbol_loss_count.clear()
            self._symbol_loss_date = today

        if trade.pnl < 0:
            self._symbol_loss_count[symbol] = self._symbol_loss_count.get(symbol, 0) + 1
            logger.info(
                f"Ardışık zarar [{symbol}]: "
                f"{self._symbol_loss_count[symbol]}/{SYMBOL_CONSECUTIVE_LOSS_LIMIT}"
            )
        else:
            self._symbol_loss_count[symbol] = 0

        # ── v13.0: R-Multiple hesapla ve geçmişe kaydet ──────────
        if R_MULT_TRACK_ENABLED and trade.initial_risk > 0:
            trade.r_multiple_at_close = trade.pnl / trade.initial_risk
            self._r_multiple_history.append(trade.r_multiple_at_close)

            # Expectancy güncelle: (WR × Avg Win R) - (LR × 1R)
            wins = [r for r in self._r_multiple_history if r > 0]
            losses = [r for r in self._r_multiple_history if r <= 0]
            total = len(self._r_multiple_history)
            if total > 0:
                wr = len(wins) / total
                avg_win_r = sum(wins) / len(wins) if wins else 0.0
                lr = len(losses) / total
                self._r_expectancy = (wr * avg_win_r) - (lr * 1.0)

            logger.info(
                f"R-Multiple [{symbol}]: {trade.r_multiple_at_close:+.2f}R "
                f"(1R={trade.initial_risk:.2f} TL), "
                f"Expectancy={self._r_expectancy:.3f}R "
                f"({len(self._r_multiple_history)} işlem)"
            )
            if trade.db_id > 0:
                self.db.update_trade(trade.db_id, {
                    "r_multiple": trade.r_multiple_at_close,
                    "initial_risk": trade.initial_risk,
                })

        # Piramit takibini temizle
        self._pyramid_last_add.pop(symbol, None)

        # Aktif işlemlerden sil
        self.active_trades.pop(symbol, None)

    # ═════════════════════════════════════════════════════════════════
    #  DURUM GERİ YÜKLEME
    # ═════════════════════════════════════════════════════════════════

    def restore_active_trades(self) -> None:
        """Engine restart'ta açık işlemleri geri yükle (P0-3 iyileştirme).

        MT5 pozisyonları ile DB trade kayıtlarını eşleyerek
        ``active_trades`` dict'ini yeniden oluşturur.

        P0-3: Strateji bilgisi, rejim bilgisi ve entry zamanı da
        DB'den kurtarılır. trailing_sl için mevcut SL kullanılır.
        """
        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası (restore): {exc}")
            return

        if not positions:
            logger.info("Geri yükleme: açık pozisyon yok")
            return

        restored_count = 0
        orphan_count = 0

        # Manuel + Hibrit pozisyon ticket'larını topla — yetim sahiplenmesini engelle
        # (1) ManuelMotor active_trades (restore sonrası dolu olabilir)
        manual_tickets: set[int] = set()
        manual_symbols: set[str] = set()
        if self.manuel_motor:
            for s, t in self.manuel_motor.active_trades.items():
                if t.ticket:
                    manual_tickets.add(t.ticket)
                manual_symbols.add(s)

        # (2) H-Engine hybrid_positions (restore sonrası dolu olabilir)
        hybrid_tickets: set[int] = set()
        hybrid_symbols: set[str] = set()
        if self.h_engine:
            for tk, hp in self.h_engine.hybrid_positions.items():
                hybrid_tickets.add(tk)
                hybrid_symbols.add(hp.symbol)

        for pos in positions:
            symbol = pos.get("symbol", "")
            ticket = pos.get("ticket", 0)
            direction = pos.get("type", "")

            if not symbol or not ticket:
                continue

            # Manuel/Hibrit pozisyon kontrolü — OĞUL sahiplenmez
            # (1) ManuelMotor active_trades kontrolü
            if ticket in manual_tickets or symbol in manual_symbols:
                logger.debug(
                    f"Restore: {symbol} ticket={ticket} manuel (active_trades) — atlanıyor"
                )
                continue

            # (2) H-Engine hybrid_positions kontrolü
            if ticket in hybrid_tickets or symbol in hybrid_symbols:
                logger.debug(
                    f"Restore: {symbol} ticket={ticket} hibrit (H-Engine) — atlanıyor"
                )
                continue

            # DB'de eşleşen aktif trade ara
            trades = self.db.get_trades(symbol=symbol, limit=10)

            # (3) DB'de strategy="manual" + exit_time=None → ManuelMotor'a ait
            is_manual_in_db = any(
                t.get("exit_time") is None and t.get("strategy") == "manual"
                for t in trades
            )
            if is_manual_in_db:
                logger.debug(
                    f"Restore: {symbol} ticket={ticket} manuel (DB) — atlanıyor"
                )
                continue

            # (4) DB'de hybrid_positions tablosunda aktif → H-Engine'e ait
            if self.db:
                active_hybrids = self.db.get_active_hybrid_positions()
                is_hybrid_in_db = any(
                    h.get("ticket") == ticket for h in active_hybrids
                )
                if is_hybrid_in_db:
                    logger.debug(
                        f"Restore: {symbol} ticket={ticket} hibrit (DB) — atlanıyor"
                    )
                    continue
            db_trade = next(
                (
                    t for t in trades
                    if t.get("exit_time") is None
                    and t.get("direction") == direction
                ),
                None,
            )

            # P0-3: Strateji ve rejim bilgisini DB'den al
            strategy = db_trade.get("strategy", "") if db_trade else ""

            # Manuel işlemler ManuelMotor'a ait — OĞUL restore'a almaz (v14.0)
            if strategy == "manual":
                continue

            regime_at_entry = db_trade.get("regime", "") if db_trade else ""
            entry_time_str = db_trade.get("entry_time", "") if db_trade else ""

            # Evrensel yönetim alanlarını DB'den kurtar
            tp1_hit = bool(db_trade.get("tp1_hit", 0)) if db_trade else False
            cost_averaged = bool(db_trade.get("cost_averaged", 0)) if db_trade else False
            breakeven_hit = bool(db_trade.get("breakeven_hit", 0)) if db_trade else False
            peak_profit = float(db_trade.get("peak_profit", 0.0) or 0.0) if db_trade else 0.0
            initial_volume = float(db_trade.get("initial_volume", 0.0) or 0.0) if db_trade else 0.0

            opened_at = None
            if entry_time_str:
                try:
                    opened_at = datetime.fromisoformat(entry_time_str)
                except (ValueError, TypeError):
                    pass

            trade = Trade(
                symbol=symbol,
                direction=direction,
                volume=pos.get("volume", 0.0),
                entry_price=pos.get("price_open", 0.0),
                sl=pos.get("sl", 0.0),
                tp=pos.get("tp", 0.0),
                state=TradeState.FILLED,
                ticket=ticket,
                strategy=strategy,
                trailing_sl=pos.get("sl", 0.0),
                db_id=db_trade.get("id", 0) if db_trade else 0,
                regime_at_entry=regime_at_entry,
                # Evrensel yönetim alanları
                tp1_hit=tp1_hit,
                cost_averaged=cost_averaged,
                breakeven_hit=breakeven_hit,
                peak_profit=peak_profit,
                initial_volume=initial_volume,
            )
            if opened_at:
                trade.opened_at = opened_at

            self.active_trades[symbol] = trade
            restored_count += 1

            if db_trade:
                # DB'yi MT5 pozisyonuyla senkronize et (netting farkı düzeltme)
                sync_fields: dict[str, Any] = {}
                db_lot = db_trade.get("lot", 0.0)
                db_entry = db_trade.get("entry_price", 0.0)
                if abs(trade.volume - db_lot) > 1e-8:
                    sync_fields["lot"] = trade.volume
                if abs(trade.entry_price - db_entry) > 1e-4:
                    sync_fields["entry_price"] = trade.entry_price
                if trade.ticket and not db_trade.get("mt5_position_id"):
                    sync_fields["mt5_position_id"] = trade.ticket
                if sync_fields and trade.db_id > 0:
                    self.db.update_trade(trade.db_id, sync_fields)
                    logger.info(
                        f"DB senkronize [{symbol}]: {sync_fields}"
                    )

                logger.info(
                    f"Geri yüklendi [{symbol}]: ticket={ticket} "
                    f"{direction} {trade.volume} lot "
                    f"strateji={strategy} rejim={regime_at_entry}"
                )
            else:
                orphan_count += 1
                logger.warning(
                    f"Yetim pozisyon geri yüklendi [{symbol}]: ticket={ticket} "
                    f"{direction} {trade.volume} lot (DB eşleşmesi yok)"
                )

        logger.info(
            f"Geri yükleme tamamlandı: {restored_count} aktif işlem "
            f"({orphan_count} yetim)"
        )

    # ═════════════════════════════════════════════════════════════════
    #  TOP 5 KONTRAT SEÇİMİ — v5.8/CEO-FAZ3: Top5Selector'a delege
    # ═════════════════════════════════════════════════════════════════

    def select_top5(self, regime: Regime) -> list[str]:
        """Top5Selector'a delege et."""
        return self._top5.select_top5(regime)

    @property
    def current_top5(self) -> list[str]:
        """Top5Selector'a delege et."""
        return self._top5.current_top5

    @property
    def current_scores(self) -> dict[str, float]:
        """Top5Selector'a delege et."""
        return self._top5.current_scores

    @property
    def last_refresh(self) -> datetime | None:
        """Top5Selector'a delege et."""
        return self._top5.last_refresh

    # ── Haber / bilanço yönetimi — Top5Selector'a delege ──────────

    def set_earnings_dates(self, symbol: str, dates: list[date]) -> None:
        """Top5Selector'a delege et."""
        self._top5.set_earnings_dates(symbol, dates)

    def set_kap_event(self, symbol: str) -> None:
        """Top5Selector'a delege et."""
        self._top5.set_kap_event(symbol)

    def clear_kap_event(self, symbol: str) -> None:
        """Top5Selector'a delege et."""
        self._top5.clear_kap_event(symbol)

    def set_manual_news_flag(self, symbol: str) -> None:
        """Top5Selector'a delege et."""
        self._top5.set_manual_news_flag(symbol)

    def get_expiry_close_needed(self) -> bool:
        """Top5Selector'a delege et."""
        return self._top5.get_expiry_close_needed()

    # ═════════════════════════════════════════════════════════════════
    #  TOP 5 — v5.8/CEO-FAZ3: Tüm iç metotlar engine/top5_selection.py'ye taşındı.
    #  Geriye uyumluluk: select_top5(), current_scores, last_refresh,
    #  set_earnings_dates(), set_kap_event(), clear_kap_event(),
    #  set_manual_news_flag(), get_expiry_close_needed()
    #  hepsi self._top5 (Top5Selector) üzerinden delege edilir.
    # ═════════════════════════════════════════════════════════════════
