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
from engine.baba import VIOP_EXPIRY_DATES
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
MIN_BARS_H1:     int = 30           # H1 onay için min bar
CONTRACT_SIZE:   float = 100.0      # VİOP çarpanı (varsayılan)

# ── State Machine ────────────────────────────────────────────────
ORDER_TIMEOUT_SEC: int       = 5       # limit emir timeout (saniye)
MAX_SLIPPAGE_ATR_MULT: float = 0.5     # max slippage = 0.5 × ATR
MAX_LOT_PER_CONTRACT: float  = 1.0     # test süreci: kontrat başına max 1 lot
MARGIN_RESERVE_PCT: float    = 0.20    # test süreci: %20 teminat ayırma
MAX_CONCURRENT: int          = 5       # test süreci: eş zamanlı maks 5 pozisyon
TRADING_OPEN: time           = time(9, 45)   # işlem başlangıç
TRADING_CLOSE: time          = time(17, 45)  # işlem bitiş + tüm pozisyonlar kapatılır

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


# ═════════════════════════════════════════════════════════════════════
#  YARDIMCI FONKSİYONLAR
# ═════════════════════════════════════════════════════════════════════


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
        self.last_signals: dict[str, str] = {}  # symbol → "BUY"|"SELL"|"BEKLE"
        self.h_engine: Any | None = None  # HEngine referansı (main.py tarafından atanır)
        self.manuel_motor: Any | None = None  # ManuelMotor referansı (main.py tarafından atanır)

        # ── Top 5 kontrat seçimi (v13.0: ÜSTAT'tan taşındı) ────────
        self._current_top5: list[str] = []
        self._current_scores: dict[str, float] = {}
        self._last_refresh: datetime | None = None

        # ── Haber / bilanço filtresi ────────────────────────────────
        self._earnings_calendar: dict[str, list[date]] = {}
        self._kap_blocked: set[str] = set()
        self._news_deactivated: set[str] = set()
        self._news_deactivate_date: date | None = None

        # ── İki döngü mimarisi (sinyal: M15 kapanış, yönetim: 10 sn) ──
        self._last_m15_candle_ts: str = ""          # son işlenen M15 mum timestamp
        self._daily_loss_stop: bool = False          # %3 günlük zarar durdurucu
        self._daily_loss_stop_date: date | None = None  # sıfırlama takibi
        self._symbol_loss_count: dict[str, int] = {}    # sembol bazlı ardışık zarar
        self._symbol_loss_date: date | None = None       # günlük sıfırlama

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

        # ═══ SİNYAL DÖNGÜSÜ (sadece M15 mum kapanışında) ═════════

        # 6. M15 mum kapanış kontrolü — kapanmamışsa sinyal üretme
        if not self._is_new_m15_candle():
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
        for symbol in symbols:
            # Sembol başına 1 aktif işlem kuralı
            if symbol in self.active_trades:
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
        if self._current_top5:
            sample_symbol = self._current_top5[0]
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

        # ── Oy 3: Volatilite — ATR(14) genişliyor mu ──────────────
        atr_arr = calc_atr(high, low, close, period=ATR_PERIOD)
        if atr_arr is not None and len(atr_arr) >= VOTING_ATR_LOOKBACK * 2:
            recent_atr = np.nanmean(atr_arr[-VOTING_ATR_LOOKBACK:])
            prev_atr = np.nanmean(
                atr_arr[-(VOTING_ATR_LOOKBACK * 2):-VOTING_ATR_LOOKBACK]
            )
            if prev_atr > 0 and recent_atr > prev_atr:
                result["atr_expanding"] = True
                # ATR genişleme yön nötr — ama çoğunluk yönünü destekler
                if buy_votes > sell_votes:
                    buy_votes += 1
                elif sell_votes > buy_votes:
                    sell_votes += 1

        # ── Oy 4: Likidite — Hacim > 20-bar ortalaması mı ─────────
        if len(volume) >= VOL_LOOKBACK + 1:
            current_vol = volume[-1]
            avg_vol = np.nanmean(volume[-(VOL_LOOKBACK + 1):-1])
            if avg_vol > 0 and current_vol > avg_vol:
                result["volume_above_avg"] = True
                # Hacim yön nötr — ama çoğunluk yönünü destekler
                if buy_votes > sell_votes:
                    buy_votes += 1
                elif sell_votes > buy_votes:
                    sell_votes += 1

        result["buy_votes"] = buy_votes
        result["sell_votes"] = sell_votes

        # Sonuç: en yüksek oy alan yön
        if buy_votes > sell_votes:
            result["direction"] = "BUY"
            result["total_favorable"] = buy_votes
        elif sell_votes > buy_votes:
            result["direction"] = "SELL"
            result["total_favorable"] = sell_votes
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
        # M15 bar verisi
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < MIN_BARS_M15:
            return None

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)

        candidates: list[Signal] = []

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

        # En güçlü sinyali seç
        best = max(candidates, key=lambda s: s.strength)

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

        # Trend follow ise H1 onayı gerekli
        if best.strategy == StrategyType.TREND_FOLLOW:
            if not self._confirm_h1(symbol, best):
                logger.debug(
                    f"H1 onayı başarısız [{symbol}]: {best.signal_type.value}"
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

        # SL hesaplama: swing low/high - 1 ATR veya fallback
        if direction == SignalType.BUY:
            swing = _find_swing_low(low, SWING_LOOKBACK)
            if swing is not None and swing < price:
                sl = swing - atr_val
            else:
                sl = price - TF_SL_ATR_MULT * atr_val
            tp = price + TF_TP_ATR_MULT * atr_val
        else:
            swing = _find_swing_high(high, SWING_LOOKBACK)
            if swing is not None and swing > price:
                sl = swing + atr_val
            else:
                sl = price + TF_SL_ATR_MULT * atr_val
            tp = price - TF_TP_ATR_MULT * atr_val

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

        # SL / TP
        if direction == SignalType.BUY:
            sl = bb_low - MR_SL_ATR_MULT * atr_val
            tp = bb_mid
        else:
            sl = bb_up + MR_SL_ATR_MULT * atr_val
            tp = bb_mid

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

        # SL / TP
        range_width = high_20 - low_20

        if direction == SignalType.BUY:
            sl = last_close - BO_SL_ATR_MULT * atr_val
            tp = price + range_width
        else:
            sl = last_close + BO_SL_ATR_MULT * atr_val
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

        # Eş zamanlı pozisyon limiti
        active_states = (
            TradeState.FILLED, TradeState.SENT,
            TradeState.PARTIAL, TradeState.MARKET_RETRY,
        )
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

        # Teminat kontrolü
        account = self.mt5.get_account_info()
        if account is None:
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = "account_info_unavailable"
            self._log_cancelled_trade(trade)
            return

        equity = account.equity
        free_margin = account.free_margin
        if equity <= 0 or free_margin < equity * MARGIN_RESERVE_PCT:
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = (
                f"margin_insufficient (free={free_margin:.0f}, "
                f"reserve={equity * MARGIN_RESERVE_PCT:.0f})"
            )
            self._log_cancelled_trade(trade)
            return

        # Lot hesaplama (evrensel yönetimde yarım lot ile giriş)
        lot = self._calculate_lot(signal, regime, equity, self.risk_params)
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
                # Fix 2: pre-fraction lot yeterliyse vol_min uygula
                try:
                    sym_info_f = self.mt5.get_symbol_info(signal.symbol)
                    v_min = sym_info_f.volume_min if sym_info_f else 1.0
                except Exception:
                    v_min = 1.0
                if lot_before_fraction >= v_min:
                    lot = v_min
                    logger.info(
                        f"ENTRY_LOT_FRACTION floor [{signal.symbol}]: "
                        f"lot=0→vol_min={v_min} "
                        f"(pre_frac={lot_before_fraction:.2f})"
                    )
                else:
                    trade.state = TradeState.CANCELLED
                    trade.cancel_reason = "lot_zero_after_fraction"
                    self._log_cancelled_trade(trade)
                    return

        trade.volume = lot
        trade.requested_volume = lot
        trade.initial_volume = lot  # orijinal lot kaydı

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
            trade.ticket = status.get(
                "position_ticket",
                status.get("deal_ticket", trade.order_ticket),
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
        # Bekleyen emri iptal et
        try:
            self.mt5.cancel_order(trade.order_ticket)
        except Exception as exc:
            logger.error(f"cancel_order hatası [{symbol}] ticket={trade.order_ticket}: {exc}")

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
            failed = self.h_engine.force_close_all(reason="EOD_17:45")
            if failed:
                logger.error(f"EOD hibrit kapatma başarısız: {failed}")

        self.db.insert_event(
            event_type="EOD_CLOSE",
            message="Gün sonu: tüm pozisyon ve emirler kapatıldı",
            severity="INFO",
            action="eod_close",
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

        # VOLATILE / OLAY → FILLED pozisyonları kapat
        if regime.regime_type in (RegimeType.VOLATILE, RegimeType.OLAY):
            for symbol in list(self.active_trades):
                trade = self.active_trades[symbol]
                if trade.state != TradeState.FILLED:
                    continue
                try:
                    close_result = self.mt5.close_position(trade.ticket)
                except Exception as exc:
                    logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                    close_result = None
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
                self.db.update_trade(trade.db_id, {
                    "lot": trade.volume,
                    "entry_price": trade.entry_price,
                    "mt5_position_id": trade.ticket,
                })

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

        # ── Manuel pozisyon güvenlik kontrolü ─────────────────────
        if self.manuel_motor:
            mt = self.manuel_motor.active_trades.get(symbol)
            if mt and mt.ticket and mt.ticket == trade.ticket:
                logger.debug(
                    f"Manage: {symbol} ticket={trade.ticket} manuel — atlanıyor"
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

        # ── 2. Sinyal Devam Kontrolü (4 gösterge oylama) ──────────
        voting = self._get_voting_detail(symbol)
        if trade.direction == "BUY":
            favorable = voting["buy_votes"]
            reverse = voting["sell_votes"]
        else:
            favorable = voting["sell_votes"]
            reverse = voting["buy_votes"]
        trade.voting_score = favorable

        # 3/4+ ters oy veya ≤1/4 lehte → çık
        if reverse >= 3 or favorable <= 1:
            exit_reason = "signal_reversal" if reverse >= 3 else "signal_loss"
            logger.info(
                f"Oylama çıkışı [{symbol}]: lehte={favorable}, "
                f"ters={reverse} → {exit_reason}"
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

        # ── 6. Trailing Stop Güncelle (EMA20 bazlı) ───────────────
        ema_20 = ema(close, period=TF_EMA_FAST)
        ema_val = last_valid(ema_20)
        if ema_val is not None:
            trail_mult = TRAIL_ATR_BY_CLASS.get(liq_class, 1.5)

            # Öğle arası genişletme
            now_time = datetime.now().time()
            if LUNCH_START <= now_time <= LUNCH_END:
                trail_mult *= LUNCH_TRAIL_WIDEN

            if trade.direction == "BUY":
                new_trailing = ema_val - trail_mult * atr_val
                if new_trailing > trade.trailing_sl:
                    try:
                        result = self.mt5.modify_position(
                            trade.ticket, sl=new_trailing
                        )
                        if result:
                            trade.trailing_sl = new_trailing
                            trade.sl = new_trailing
                            logger.debug(
                                f"Trailing güncellendi [{symbol}]: "
                                f"SL={new_trailing:.4f}"
                            )
                    except Exception as exc:
                        logger.error(
                            f"Trailing modify hatası [{symbol}]: {exc}"
                        )
            else:
                new_trailing = ema_val + trail_mult * atr_val
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
                            logger.debug(
                                f"Trailing güncellendi [{symbol}]: "
                                f"SL={new_trailing:.4f}"
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
        last_close = volume[-1]  # dummy — asıl fiyat hareketi
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
            2. Spread anormal (≥ ort×2) → kârdaysa kapat
            3. Gap kontrolü: açılışta SL aşılmışsa → anında kapat
        """
        if not USE_UNIVERSAL_MANAGEMENT:
            return
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
        if trade.direction == "BUY":
            new_sl = current_price - trail_mult * atr_val
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
                        f"Trailing SL güncellendi [{symbol}]: {new_sl:.4f}"
                    )
        else:  # SELL
            new_sl = current_price + trail_mult * atr_val
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
                        f"Trailing SL güncellendi [{symbol}]: {new_sl:.4f}"
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

        # Manuel pozisyon ticket'larını topla — yetim sahiplenmesini engelle
        # (1) ManuelMotor active_trades (restore sonrası dolu olabilir)
        manual_tickets: set[int] = set()
        manual_symbols: set[str] = set()
        if self.manuel_motor:
            for s, t in self.manuel_motor.active_trades.items():
                if t.ticket:
                    manual_tickets.add(t.ticket)
                manual_symbols.add(s)

        for pos in positions:
            symbol = pos.get("symbol", "")
            ticket = pos.get("ticket", 0)
            direction = pos.get("type", "")

            if not symbol or not ticket:
                continue

            # Manuel pozisyon kontrolü — OĞUL sahiplenmez
            # (1) ManuelMotor active_trades kontrolü
            if ticket in manual_tickets or symbol in manual_symbols:
                logger.debug(
                    f"Restore: {symbol} ticket={ticket} manuel (active_trades) — atlanıyor"
                )
                continue

            # DB'de eşleşen aktif trade ara
            trades = self.db.get_trades(symbol=symbol, limit=10)

            # (2) DB'de strategy="manual" + exit_time=None → ManuelMotor'a ait
            is_manual_in_db = any(
                t.get("exit_time") is None and t.get("strategy") == "manual"
                for t in trades
            )
            if is_manual_in_db:
                logger.debug(
                    f"Restore: {symbol} ticket={ticket} manuel (DB) — atlanıyor"
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
    #  TOP 5 KONTRAT SEÇİMİ (v13.0: ÜSTAT'tan taşındı)
    # ═════════════════════════════════════════════════════════════════

    def select_top5(self, regime: Regime) -> list[str]:
        """Mevcut rejime göre en iyi kontratları seç.

        Her 30 dakikada bir güncellenir, aralarda cache'ten döner.
        09:15'ten önce boş liste döndürür.

        Args:
            regime: Mevcut piyasa rejimi (Baba'dan).

        Returns:
            Seçilen kontrat sembolleri
            (max 5, ortalama filtresiyle daha az olabilir).
        """
        now = datetime.now()

        # 09:15 öncesi → seçim yok
        if now.time() < SELECTION_START:
            return self._current_top5

        # Güncelleme gerekli mi?
        if self._should_refresh(now):
            self._refresh_scores(regime, now)

        return self._current_top5

    @property
    def current_scores(self) -> dict[str, float]:
        """Son hesaplanan final skorlar (sembol → 0-100)."""
        return dict(self._current_scores)

    @property
    def last_refresh(self) -> datetime | None:
        """Son güncelleme zamanı."""
        return self._last_refresh

    # ── Haber / bilanço yönetimi ──────────────────────────────────

    def set_earnings_dates(self, symbol: str, dates: list[date]) -> None:
        """Bilanço tarihlerini kaydet.

        Args:
            symbol: Kontrat sembolü.
            dates: Bilanço açıklama tarihleri listesi.
        """
        self._earnings_calendar[symbol] = sorted(dates)
        logger.info(f"Bilanço takvimi [{symbol}]: {dates}")

    def set_kap_event(self, symbol: str) -> None:
        """KAP özel durum — kontratı durdur.

        Args:
            symbol: Durdurulacak kontrat.
        """
        self._kap_blocked.add(symbol)
        logger.warning(f"KAP özel durum: {symbol} durduruldu")
        self.db.insert_event(
            event_type="NEWS_FILTER",
            message=f"KAP özel durum: {symbol} durduruldu",
            severity="WARNING",
            action="kap_block",
        )

    def clear_kap_event(self, symbol: str) -> None:
        """KAP özel durum kaldır.

        Args:
            symbol: Serbest bırakılacak kontrat.
        """
        self._kap_blocked.discard(symbol)
        logger.info(f"KAP özel durum kaldırıldı: {symbol}")

    def set_manual_news_flag(self, symbol: str) -> None:
        """Manuel haber işareti — gün boyu deaktif.

        Args:
            symbol: Deaktif edilecek kontrat.
        """
        self._news_deactivated.add(symbol)
        self._news_deactivate_date = date.today()
        logger.warning(f"Manuel haber deaktif: {symbol} (gün boyu)")
        self.db.insert_event(
            event_type="NEWS_FILTER",
            message=f"Manuel haber deaktif: {symbol}",
            severity="WARNING",
            action="manual_news",
        )

    def get_expiry_close_needed(self) -> bool:
        """Vade kapanış emri gerekli mi?

        Returns:
            True ise tüm pozisyonlar kapatılmalı.
        """
        today = date.today()
        future_expiries = sorted(d for d in VIOP_EXPIRY_DATES if d >= today)
        if not future_expiries:
            return False
        bdays = _business_days_until(future_expiries[0], today)
        return bdays <= EXPIRY_CLOSE_DAYS

    # ═════════════════════════════════════════════════════════════════
    #  TOP 5 — ZAMANLAMA
    # ═════════════════════════════════════════════════════════════════

    def _should_refresh(self, now: datetime) -> bool:
        """30 dakika aralık veya günün ilk seçimi kontrolü."""
        if self._last_refresh is None:
            return True
        if self._last_refresh.date() != now.date():
            return True
        elapsed = (now - self._last_refresh).total_seconds()
        return elapsed >= REFRESH_INTERVAL_MIN * 60

    # ═════════════════════════════════════════════════════════════════
    #  TOP 5 — ANA PUANLAMA
    # ═════════════════════════════════════════════════════════════════

    def _refresh_scores(self, regime: Regime, now: datetime) -> None:
        """Tüm kontratları puanla ve Top 5 seç.

        Adımlar:
            1. Ham puanları hesapla (5 kriter × 15 sembol)
            2. Winsorize + min-max normalize et
            3. Ağırlıklı toplam → final skor
            4. Büyükten küçüğe sırala, ilk 5'i al
            5. Ortalama filtresi uygula
            6. Vade + haber filtresi uygula
            7. DB'ye kaydet
        """
        today = now.date()

        # Günlük haber deaktif sıfırlama
        if self._news_deactivate_date != today:
            self._news_deactivated.clear()
            self._news_deactivate_date = today

        # 1. Ham puanlar
        raw_scores: dict[str, dict[str, float]] = {}
        for symbol in WATCHED_SYMBOLS:
            raw_scores[symbol] = {
                "technical": self._score_technical(symbol, regime),
                "volume": self._score_volume(symbol),
                "spread": self._score_spread(symbol),
                "historical": self._score_historical(symbol, regime),
                "volatility": self._score_volatility_fit(symbol, regime),
            }

        # 2. Normalize (winsorize + min-max per kriter + ağırlıklı toplam)
        final_scores = self._normalize_and_weight(raw_scores)

        # 3. Sırala (yüksekten düşüğe)
        ranked = sorted(
            final_scores.items(), key=lambda x: x[1], reverse=True,
        )

        # 4. İlk 5'i al
        top5_candidates = ranked[:5]

        # 5. Ortalama filtresi
        if top5_candidates:
            avg = sum(s for _, s in top5_candidates) / len(top5_candidates)
            top5_above_avg = [
                (sym, sc) for sym, sc in top5_candidates if sc >= avg
            ]
        else:
            top5_above_avg = []
            avg = 0.0

        # Fix 5: Minimum 3 kontrat garantisi
        TOP5_MINIMUM = 3
        if len(top5_above_avg) < TOP5_MINIMUM and len(top5_candidates) >= TOP5_MINIMUM:
            top5_above_avg = top5_candidates[:TOP5_MINIMUM]
            logger.info(
                f"Top5 minimum garanti: {len(top5_above_avg)} kontrat "
                f"(avg filtresi yetersiz, ilk {TOP5_MINIMUM} alındı)"
            )

        # 6. Vade + haber filtresi
        expiry_status = self._get_expiry_status(today)
        top5_final: list[str] = []
        for sym, _sc in top5_above_avg:
            status = expiry_status.get(sym, "normal")
            if status == "observation":
                logger.debug(f"Vade gözlem engeli: {sym}")
                continue
            if status == "no_new_trade":
                logger.debug(f"Vade kapanış yakın — yeni işlem yok: {sym}")
                continue
            if self._is_news_blocked(sym, today):
                logger.debug(f"Haber/bilanço engeli: {sym}")
                continue
            top5_final.append(sym)

        # 7. Durum güncelle
        self._current_top5 = top5_final
        self._current_scores = dict(final_scores)
        self._last_refresh = now

        # 8. DB kayıt
        self._log_top5(now, regime)

        symbols_str = ", ".join(
            f"{s}={final_scores.get(s, 0):.1f}" for s in top5_final
        )
        logger.info(
            f"Top 5 güncellendi ({len(top5_final)} kontrat): "
            f"[{symbols_str}] avg={avg:.1f}"
        )

    # ═════════════════════════════════════════════════════════════════
    #  TOP 5 — PUANLAMA KRİTERLERİ
    # ═════════════════════════════════════════════════════════════════

    def _score_technical(self, symbol: str, regime: Regime) -> float:
        """Teknik sinyal gücü puanı (ham 0-100).

        Alt bileşenler:
            ADX uyumu     (0-30): Rejime göre ADX değerlendirmesi
            Trend/EMA     (0-25): EMA mesafesi + MACD momentum
            RSI           (0-25): Aşırı bölge ve yön uyumu
            BB pozisyonu  (0-20): Fiyatın bantlara göre konumu
        """
        df = self.db.get_bars(symbol, "M15", limit=TECH_MIN_BARS)
        if df.empty or len(df) < TECH_MIN_BARS:
            return 50.0

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)

        # İndikatörler
        adx_arr = calc_adx(high, low, close, TECH_ADX_PERIOD)
        rsi_arr = calc_rsi(close, TECH_RSI_PERIOD)
        ema_f = ema(close, TECH_EMA_FAST)
        ema_s = ema(close, TECH_EMA_SLOW)
        _, _, histogram = calc_macd(close)
        bb_u, _bb_m, bb_l = bollinger_bands(
            close, TECH_BB_PERIOD, TECH_BB_STD,
        )

        adx_val = last_valid(adx_arr)
        rsi_val = last_valid(rsi_arr)
        hist_val = last_valid(histogram)
        ema_fast_val = last_valid(ema_f)
        ema_slow_val = last_valid(ema_s)
        bb_upper = last_valid(bb_u)
        bb_lower = last_valid(bb_l)

        if any(
            v is None
            for v in [adx_val, rsi_val, hist_val, ema_fast_val, ema_slow_val]
        ):
            return 50.0

        price = close[-1]
        if price <= 0:
            return 50.0

        is_trend = regime.regime_type == RegimeType.TREND

        # ── 1. ADX uyumu (0-30) ─────────────────────────────────
        if is_trend:
            adx_score = min(adx_val / 50.0 * 30.0, 30.0)
        else:
            adx_score = max(0.0, 30.0 - adx_val * 0.75)

        # ── 2. Trend/EMA uyumu (0-25) ──────────────────────────
        ema_gap_pct = abs(ema_fast_val - ema_slow_val) / price * 100

        if is_trend:
            ema_score = min(ema_gap_pct * 10.0, 15.0)
            macd_score = min(
                abs(hist_val) / price * 1000.0, 10.0,
            )
        else:
            ema_score = max(0.0, 15.0 - ema_gap_pct * 10.0)
            macd_score = max(
                0.0, 10.0 - abs(hist_val) / price * 1000.0,
            )
        trend_score = min(ema_score + macd_score, 25.0)

        # ── 3. RSI (0-25) ──────────────────────────────────────
        if is_trend:
            ema_bullish = ema_fast_val > ema_slow_val
            if (rsi_val > 55 and ema_bullish) or (
                rsi_val < 45 and not ema_bullish
            ):
                rsi_score = 25.0
            elif 40 <= rsi_val <= 60:
                rsi_score = 15.0
            else:
                rsi_score = 5.0
        else:
            if rsi_val > 70 or rsi_val < 30:
                rsi_score = 25.0
            elif rsi_val > 60 or rsi_val < 40:
                rsi_score = 18.0
            else:
                rsi_score = 10.0

        # ── 4. BB pozisyonu (0-20) ─────────────────────────────
        bb_score = 10.0
        if (
            bb_upper is not None
            and bb_lower is not None
            and bb_upper > bb_lower
        ):
            bb_width = bb_upper - bb_lower
            bb_pos = (price - bb_lower) / bb_width

            if is_trend:
                bb_score = 20.0 if (bb_pos > 0.7 or bb_pos < 0.3) else 10.0
            else:
                if bb_pos > 0.85 or bb_pos < 0.15:
                    bb_score = 20.0
                elif 0.3 <= bb_pos <= 0.7:
                    bb_score = 15.0
                else:
                    bb_score = 10.0

        total = adx_score + trend_score + rsi_score + bb_score
        return max(0.0, min(100.0, total))

    def _score_volume(self, symbol: str) -> float:
        """Hacim kalitesi puanı (ham 0-100).

        Güncel hacim / 20-bar ortalama hacim oranı.
        Oran 0 → 0 puan, oran >= 3 → 100 puan (lineer).
        """
        df = self.db.get_bars(symbol, "M15", limit=VOL_LOOKBACK * 4 + 4)
        if df.empty or len(df) < VOL_LOOKBACK + 1:
            return 50.0

        vol = df["volume"].values.astype(np.float64)

        recent_count = min(4, len(vol))
        current_vol = float(np.mean(vol[-recent_count:]))

        past_vol = vol[:-recent_count] if len(vol) > recent_count else vol
        avg_vol = float(np.mean(past_vol))

        if avg_vol <= 0:
            return 50.0

        ratio = current_vol / avg_vol
        score = min(ratio / VOL_MAX_RATIO * 100.0, 100.0)
        return max(0.0, score)

    def _score_spread(self, symbol: str) -> float:
        """Spread durumu puanı (ham 0-100).

        Düşük spread = yüksek puan.
        """
        rows = self.db.get_liquidity(
            target_date=date.today().isoformat(), symbol=symbol,
        )
        if rows and rows[0].get("avg_spread") is not None:
            avg_spread = rows[0]["avg_spread"]
            liq_class = rows[0].get("class", "C")

            class_bonus = {"A": 30.0, "B": 10.0, "C": 0.0}.get(
                liq_class, 0.0,
            )

            spread_score = max(0.0, 70.0 - avg_spread * 2.0)
            return min(100.0, spread_score + class_bonus)

        df = self.db.get_bars(symbol, "M15", limit=20)
        if df.empty or len(df) < 5:
            return 50.0

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)

        safe_close = np.where(close > 0, close, 1.0)
        range_pct = (high - low) / safe_close

        current = range_pct[-1]
        avg = float(np.mean(range_pct[:-1]))

        if avg <= 0:
            return 50.0

        ratio = current / avg
        score = (3.0 - ratio) / 2.5 * 100.0
        return max(0.0, min(100.0, score))

    def _score_historical(self, symbol: str, regime: Regime) -> float:
        """Tarihsel başarı puanı (ham 0-100).

        Son 30 gün bu kontrat + rejimde win rate ve ortalama PnL.
        """
        trades = self.db.get_trades(symbol=symbol, limit=200)
        if not trades:
            return 50.0

        cutoff = (
            datetime.now() - timedelta(days=HIST_LOOKBACK_DAYS)
        ).isoformat()
        regime_name = regime.regime_type.value

        recent = [
            t
            for t in trades
            if t.get("exit_time")
            and t.get("pnl") is not None
            and t["exit_time"] >= cutoff
            and (t.get("regime") == regime_name or t.get("regime") is None)
        ]

        if not recent or len(recent) < 10:
            return 30.0  # FAZ 2.7: yetersiz veri penaltısı (3→10 min, 50→30 default)

        wins = sum(1 for t in recent if t["pnl"] > 0)
        total = len(recent)
        win_rate = wins / total

        avg_pnl = sum(t["pnl"] for t in recent) / total

        wr_score = max(0.0, min(60.0, (win_rate - 0.3) / 0.4 * 60.0))
        pnl_score = 20.0 + min(20.0, max(-20.0, avg_pnl * 2.0))

        return max(0.0, min(100.0, wr_score + pnl_score))

    def _score_volatility_fit(self, symbol: str, regime: Regime) -> float:
        """Volatilite uyumu puanı (ham 0-100).

        ATR(14) / fiyat oranının rejime uygunluğu.
        """
        df = self.db.get_bars(symbol, "M15", limit=TECH_MIN_BARS)
        if df.empty or len(df) < 30:
            return 50.0

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)

        atr_arr = calc_atr(high, low, close, TECH_ATR_PERIOD)
        atr_val = last_valid(atr_arr)
        price = close[-1]

        if atr_val is None or price <= 0:
            return 50.0

        atr_ratio = atr_val / price

        if regime.regime_type == RegimeType.TREND:
            ideal = VOLFIT_TREND_IDEAL
        elif regime.regime_type == RegimeType.RANGE:
            ideal = VOLFIT_RANGE_IDEAL
        else:
            ideal = VOLFIT_RANGE_IDEAL

        diff = abs(atr_ratio - ideal)
        score = 100.0 * float(np.exp(-(diff / VOLFIT_TOLERANCE) ** 2))

        return max(0.0, min(100.0, score))

    # ═════════════════════════════════════════════════════════════════
    #  TOP 5 — NORMALİZASYON
    # ═════════════════════════════════════════════════════════════════

    def _normalize_and_weight(
        self,
        raw_scores: dict[str, dict[str, float]],
    ) -> dict[str, float]:
        """Ham puanları winsorize + min-max normalize et, ağırlıklı topla."""
        criteria = ["technical", "volume", "spread", "historical", "volatility"]
        weights = {
            "technical": W_TECHNICAL,
            "volume": W_VOLUME,
            "spread": W_SPREAD,
            "historical": W_HISTORICAL,
            "volatility": W_VOLATILITY,
        }

        symbols = list(raw_scores.keys())
        if not symbols:
            return {}

        normalized: dict[str, dict[str, float]] = {s: {} for s in symbols}

        for crit in criteria:
            values = [raw_scores[s][crit] for s in symbols]
            win_values = self._winsorize(values)
            v_min = min(win_values)
            v_max = max(win_values)
            for i, sym in enumerate(symbols):
                if v_max > v_min:
                    norm = (win_values[i] - v_min) / (v_max - v_min) * 100.0
                else:
                    norm = 50.0
                normalized[sym][crit] = norm

        final: dict[str, float] = {}
        for sym in symbols:
            score = sum(
                normalized[sym][crit] * weights[crit] for crit in criteria
            )
            final[sym] = round(score, 2)

        return final

    @staticmethod
    def _winsorize(values: list[float]) -> list[float]:
        """Winsorization: 1. ve 99. percentile'a kırp."""
        if len(values) < 3:
            return list(values)

        arr = np.array(values, dtype=np.float64)
        lower = float(np.percentile(arr, WINSOR_LOWER_PCT))
        upper = float(np.percentile(arr, WINSOR_UPPER_PCT))
        return [max(lower, min(upper, v)) for v in values]

    # ═════════════════════════════════════════════════════════════════
    #  TOP 5 — VADE GEÇİŞİ
    # ═════════════════════════════════════════════════════════════════

    def _get_expiry_status(self, today: date) -> dict[str, str]:
        """Her sembol için vade geçiş durumunu belirle.

        Durumlar:
            ``"normal"``       — işlem yapılabilir
            ``"no_new_trade"`` — 3 iş günü kala, yeni işlem yok
            ``"close"``        — 1 iş günü kala, pozisyonları kapat
            ``"observation"``  — yeni vade, ilk 2 gün sadece gözlem
        """
        future_expiries = sorted(d for d in VIOP_EXPIRY_DATES if d >= today)
        if not future_expiries:
            return {s: "normal" for s in WATCHED_SYMBOLS}

        next_expiry = future_expiries[0]
        bdays_to_expiry = _business_days_until(next_expiry, today)

        past_expiries = sorted(
            (d for d in VIOP_EXPIRY_DATES if d < today), reverse=True,
        )
        last_expiry = past_expiries[0] if past_expiries else None

        status: dict[str, str] = {}
        for symbol in WATCHED_SYMBOLS:
            if last_expiry:
                bdays_since_expiry = _business_days_since(
                    last_expiry, today,
                )
                if 0 < bdays_since_expiry <= EXPIRY_OBSERVATION_DAYS:
                    status[symbol] = "observation"
                    continue

            if bdays_to_expiry <= EXPIRY_CLOSE_DAYS:
                status[symbol] = "close"
            elif bdays_to_expiry <= EXPIRY_NO_NEW_TRADE_DAYS:
                status[symbol] = "no_new_trade"
            else:
                status[symbol] = "normal"

        return status

    # ═════════════════════════════════════════════════════════════════
    #  TOP 5 — HABER / BİLANÇO FİLTRESİ
    # ═════════════════════════════════════════════════════════════════

    def _is_news_blocked(self, symbol: str, today: date) -> bool:
        """Haber/bilanço engeli kontrolü.

        Kontroller:
            1. KAP özel durum → engel
            2. Manuel haber işareti (günlük) → engel
            3. Bilanço günü ±1 → engel
        """
        if symbol in self._kap_blocked:
            return True

        if (
            self._news_deactivate_date == today
            and symbol in self._news_deactivated
        ):
            return True

        if symbol in self._earnings_calendar:
            for earn_date in self._earnings_calendar[symbol]:
                diff = abs((today - earn_date).days)
                if diff <= 1:
                    return True

        return False

    # ═════════════════════════════════════════════════════════════════
    #  TOP 5 — DB KAYIT
    # ═════════════════════════════════════════════════════════════════

    def _log_top5(self, now: datetime, regime: Regime) -> None:
        """Top 5 seçimini DB'ye kaydet."""
        if not self._current_top5:
            return

        entries = []
        for rank, symbol in enumerate(self._current_top5, start=1):
            entries.append({
                "date": now.date().isoformat(),
                "time": now.time().isoformat(timespec="seconds"),
                "rank": rank,
                "symbol": symbol,
                "score": self._current_scores.get(symbol, 0.0),
                "regime": regime.regime_type.value,
            })

        self.db.insert_top5(entries)
