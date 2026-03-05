"""BABA — Risk yönetimi ve piyasa rejim algılama (v13.0).

4 rejim:
    TREND    — ADX>25 + EMA mesafesi artıyor + son 5 barın 4'ü aynı yön
    RANGE    — ADX<20 + BB genişliği < ort×0.8 + dar range
    VOLATILE — ATR>ort×2.0 VEYA spread>normal×3 VEYA %2+ hareket
    OLAY     — TCMB/FED günü VEYA kur hareketi>%2 VEYA vade son 2 gün

Risk çarpanları:
    TREND=1.0  RANGE=0.7  VOLATILE=0.25  OLAY=0.0

Erken uyarı tetikleyicileri (likidite sınıfına göre farklı eşik):
    Spread patlaması  — A:3×  B:4×  C:5×  (10 s içinde)
    Ani fiyat hareketi — A:1.5%  B:2%  C:3%  (son 1 bar)
    Hacim patlaması   — 5 dk hacim > ort×5  (tüm sınıflar)
    USD/TRY şoku      — 5 dk'da %0.5+ hareket (tüm sınıflar)

Risk yönetimi:
    Günlük zarar %1.8 → tüm işlemler dur → ertesi gün 09:30 sıfırla
    Haftalık zarar %4 → lot %50 azalt → Pazartesi 09:30 sıfırla
    Aylık zarar %7    → sistem dur → manuel onay
    Max DD %10 / Hard DD %15 → tam kapanış → manuel onay
    3 üst üste kayıp  → 4 saat cool-down
    Floating loss %1.5 → yeni işlem engeli
    Günlük max işlem 5 / Tek işlem max %2

Korelasyon:
    Max 3 aynı yön / Max 2 aynı sektör aynı yön
    Endeks ağırlık skoru < 0.25

Kill-switch (3 seviye):
    L1 — kontrat durdur (anomali)
    L2 — sistem pause (risk limiti, 3 kayıp, OLAY)
    L3 — tam kapanış (manuel + onay, DD %10+, flash crash)
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from engine.config import Config
from engine.database import Database
from engine.logger import get_logger
from engine.models.regime import (
    EarlyWarning,
    Regime,
    RegimeType,
    RISK_MULTIPLIERS,
)
from engine.models.risk import (
    RiskParams,
    RiskVerdict,
    FakeAnalysis,
    FakeLayerResult,
)
from engine.mt5_bridge import MT5Bridge, WATCHED_SYMBOLS
from engine.utils.helpers import last_valid, nanmean
from engine.utils.indicators import (
    adx as calc_adx,
    atr as calc_atr,
    ema,
    bollinger_bands,
    rsi as calc_rsi,
    macd as calc_macd,
)

logger = get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════
#  SABİTLER
# ═════════════════════════════════════════════════════════════════════

# ── Rejim eşikleri ───────────────────────────────────────────────────
ADX_TREND_THRESHOLD:   float = 25.0
ADX_RANGE_THRESHOLD:   float = 20.0
EMA_DIRECTION_BARS:    int   = 5
EMA_DIRECTION_MIN:     int   = 4
BB_WIDTH_RATIO:        float = 0.8
ATR_VOLATILE_MULT:     float = 2.0
SPREAD_VOLATILE_MULT:  float = 3.0
PRICE_MOVE_PCT:        float = 2.0

# ── OLAY eşikleri ───────────────────────────────────────────────────
USDTRY_SHOCK_PCT:      float = 2.0
EXPIRY_DAYS:           int   = 2

# ── Erken uyarı eşikleri ────────────────────────────────────────────
SPREAD_SPIKE_MULT: dict[str, float] = {"A": 3.0, "B": 4.0, "C": 5.0}
PRICE_SHOCK_PCT:   dict[str, float] = {"A": 1.5, "B": 2.0, "C": 3.0}
VOLUME_SPIKE_MULT: float = 5.0
USDTRY_5M_SHOCK_PCT: float = 0.5

# ── Hesaplama sabitleri ──────────────────────────────────────────────
EMA_FAST:    int   = 9
EMA_SLOW:    int   = 21
ADX_PERIOD:  int   = 14
ATR_PERIOD:  int   = 14
BB_PERIOD:   int   = 20
BB_STD:      float = 2.0
ATR_LOOKBACK: int  = 100

# ── Çok katmanlı kayıp limit sabitleri ───────────────────────────────
MAX_WEEKLY_LOSS_PCT:     float = 0.04
MAX_MONTHLY_LOSS_PCT:    float = 0.07
HARD_DRAWDOWN_PCT:       float = 0.12
CONSECUTIVE_LOSS_LIMIT:  int   = 3
COOLDOWN_HOURS:          int   = 4
MAX_FLOATING_LOSS_PCT:   float = 0.015
MAX_DAILY_TRADES:        int   = 5
MAX_RISK_PER_TRADE_HARD: float = 0.02

# ── Korelasyon sabitleri ─────────────────────────────────────────────
MAX_SAME_DIRECTION:         int   = 3
MAX_SAME_SECTOR_DIRECTION:  int   = 2
MAX_INDEX_WEIGHT_SCORE:     float = 0.25

# ── Risk hesaplama başlangıç tarihi ────────────────────────────────
# Bu tarihten önceki risk snapshot ve trade verileri risk limitlerini
# tetiklemez. Eski test/geliştirme dönemi verileri devre dışı kalır.
# Değiştirmek için bu sabiti güncelleyin.
RISK_BASELINE_DATE: str = "2026-02-23"

# ── Kill-switch seviyeleri ───────────────────────────────────────────
KILL_SWITCH_NONE: int = 0
KILL_SWITCH_L1:   int = 1   # kontrat durdur
KILL_SWITCH_L2:   int = 2   # sistem pause
KILL_SWITCH_L3:   int = 3   # tam kapanış

# ── Fake sinyal analiz sabitleri ───────────────────────────────────
FAKE_SCORE_THRESHOLD:  int   = 3       # toplam >= 3 → pozisyon kapat
FAKE_VOLUME_RATIO_MIN: float = 0.7     # hacim / 20-bar ort. < 0.7 → FAKE
FAKE_VOLUME_LOOKBACK:  int   = 20      # hacim ortalaması bar sayısı
FAKE_SPREAD_MULT: dict[str, float] = {"A": 2.5, "B": 3.5, "C": 5.0}
FAKE_MTF_EMA_PERIOD:   int   = 9       # multi-TF EMA periyodu
FAKE_MTF_AGREEMENT_MIN: int  = 2       # en az 2/3 TF uyumu gerekli

# ── Spread / USDTRY geçmiş buffer uzunluğu ──────────────────────────
SPREAD_HISTORY_LEN: int = 30            # son 30 veri noktası (Madde 3.3)
FAKE_RSI_OVERBOUGHT:   float = 80.0
FAKE_RSI_OVERSOLD:     float = 20.0
FAKE_RSI_PERIOD:       int   = 14
FAKE_WEIGHT_VOLUME:    int   = 1
FAKE_WEIGHT_SPREAD:    int   = 2
FAKE_WEIGHT_MULTI_TF:  int   = 1
FAKE_WEIGHT_MOMENTUM:  int   = 2

# ── Sektör eşlemeleri (15 WATCHED_SYMBOLS) ───────────────────────────
SYMBOL_TO_SECTOR: dict[str, str] = {
    "F_THYAO": "havacilik",
    "F_AKBNK": "banka",
    "F_ASELS": "teknoloji",
    "F_TCELL": "teknoloji",
    "F_HALKB": "banka",
    "F_PGSUS": "havacilik",
    "F_GUBRF": "kimya",
    "F_EKGYO": "gayrimenkul",
    "F_SOKM":  "perakende",
    "F_TKFEN": "holding",
    "F_OYAKC": "sanayi",
    "F_BRSAN": "sanayi",
    "F_AKSEN": "enerji",
    "F_ASTOR": "enerji",
    "F_KONTR": "diger",
}

# ── XU030 endeks ağırlıkları (yaklaşık, çeyreklik güncellenmeli) ─────
XU030_WEIGHTS: dict[str, float] = {
    "F_THYAO": 0.12,
    "F_AKBNK": 0.08,
    "F_ASELS": 0.07,
    "F_TCELL": 0.05,
    "F_HALKB": 0.03,
    "F_PGSUS": 0.04,
    "F_GUBRF": 0.02,
    "F_EKGYO": 0.03,
    "F_SOKM":  0.02,
    "F_TKFEN": 0.03,
    "F_OYAKC": 0.01,
    "F_BRSAN": 0.01,
    "F_AKSEN": 0.02,
    "F_ASTOR": 0.01,
    "F_KONTR": 0.00,
}

# ── Takvim: TCMB / FED toplantı tarihleri (güncellenmeli) ───────────
CENTRAL_BANK_DATES: set[date] = {
    # 2025 TCMB PPK
    date(2025, 1, 23), date(2025, 2, 20), date(2025, 3, 20),
    date(2025, 4, 17), date(2025, 5, 22), date(2025, 6, 19),
    date(2025, 7, 24), date(2025, 8, 21), date(2025, 9, 18),
    date(2025, 10, 23), date(2025, 11, 20), date(2025, 12, 25),
    # 2025 FED FOMC
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7),
    date(2025, 6, 18), date(2025, 7, 30), date(2025, 9, 17),
    date(2025, 10, 29), date(2025, 12, 10),
    # 2026 TCMB (tahmini)
    date(2026, 1, 22), date(2026, 2, 19), date(2026, 3, 19),
    date(2026, 4, 16), date(2026, 5, 21), date(2026, 6, 18),
}

# VİOP vade bitiş tarihleri (her ayın son iş günü)
# NOT: Ramazan/Kurban Bayramı tarihleri yıla göre değişir — tatile
#       denk gelen vade tarihleri önceki iş gününe çekilmelidir.
VIOP_EXPIRY_DATES: set[date] = {
    # 2025
    date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31),
    date(2025, 4, 30), date(2025, 5, 30), date(2025, 6, 30),
    date(2025, 7, 31), date(2025, 8, 29), date(2025, 9, 30),
    date(2025, 10, 31), date(2025, 11, 28), date(2025, 12, 31),
    # 2026
    date(2026, 1, 30), date(2026, 2, 27), date(2026, 3, 31),
    date(2026, 4, 30), date(2026, 5, 25), date(2026, 6, 30),
    date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30),
    date(2026, 10, 28), date(2026, 11, 30), date(2026, 12, 31),
}


def validate_expiry_dates() -> list[str]:
    """VİOP vade tarihlerinin iş günü olduğunu doğrula (Madde 2.7).

    Hafta sonu (Cumartesi/Pazar) veya tatile denk gelen tarihleri tespit eder.
    Engine başlangıcında çağrılır.

    Returns:
        Sorunlu tarihlerin açıklama listesi. Boş liste = tümü geçerli.
    """
    from engine.utils.time_utils import ALL_HOLIDAYS

    issues: list[str] = []
    for expiry in sorted(VIOP_EXPIRY_DATES):
        weekday = expiry.weekday()  # 0=Pazartesi, 5=Cumartesi, 6=Pazar
        if weekday >= 5:
            day_name = "Cumartesi" if weekday == 5 else "Pazar"
            issues.append(f"{expiry.isoformat()} - {day_name} (hafta sonu)")
        elif expiry in ALL_HOLIDAYS:
            issues.append(f"{expiry.isoformat()} - Tatil gunu")
    return issues


# ═════════════════════════════════════════════════════════════════════
#  BABA
# ═════════════════════════════════════════════════════════════════════

class Baba:
    """Risk yöneticisi — rejim algılama, erken uyarı, pozisyon boyutlama,
    çok katmanlı kayıp limitleri, korelasyon yönetimi, kill-switch."""

    def __init__(
        self,
        config: Config,
        db: Database,
        mt5: MT5Bridge | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._mt5 = mt5
        self.current_regime: Regime = Regime(regime_type=RegimeType.TREND)
        self.active_warnings: list[EarlyWarning] = []

        # Spread ring buffer — sembol başına son 30 okuma (≈ 5 dk)
        self._spread_history: dict[str, list[float]] = {
            s: [] for s in WATCHED_SYMBOLS
        }
        # USD/TRY ring buffer
        self._usdtry_history: list[float] = []

        # ── Risk durumu (bellekte, her cycle kontrol edilir) ──────────
        self._risk_state: dict[str, Any] = {
            "daily_reset_date": None,
            "daily_trade_count": 0,
            "weekly_reset_week": None,
            "weekly_loss_halved": False,
            "monthly_reset_month": None,
            "monthly_paused": False,
            "consecutive_losses": 0,
            "last_trade_count": 0,
            "cooldown_until": None,
            "last_cooldown_end": None,
        }

        # ── Cycle sayacı (fake analiz frekansı için) ──────────────────
        self._cycle_count: int = 0

        # ── Kill-switch durumu ───────────────────────────────────────
        self._kill_switch_level: int = KILL_SWITCH_NONE
        self._kill_switch_details: dict[str, Any] = {}
        self._killed_symbols: set[str] = set()
        # L3 kapanışta kapatılamayan pozisyon ticket'ları (API'ye iletilir)
        self._last_l3_failed_tickets: list[int] = []

        # v13.0: "izin verdi" olay kaydı dedup (5 dk'da 1 kez)
        self._last_risk_allowed_log: datetime | None = None

    # ── public: ana cycle ────────────────────────────────────────────
    def run_cycle(self, pipeline=None) -> Regime:
        """Her 10 sn'de engine tarafından çağrılır.

        Sırası:
            1. Spread/USDTRY buffer güncelle
            2. Rejim algılama
            3. Erken uyarı kontrolü
            4. Fake sinyal analizi (açık pozisyonlar)
            5. Period sıfırlama kontrolü
            6. Kill-switch tetikleyici değerlendirme

        Args:
            pipeline: DataPipeline nesnesi (tick verisi için).

        Returns:
            Algılanan Regime.
        """
        self._cycle_count += 1

        if pipeline:
            self._update_spread_history(pipeline)
            self._update_usdtry_history()

        regime = self.detect_regime()
        self.current_regime = regime

        self.active_warnings = self.check_early_warnings()

        # Fake sinyal analizi: her 3 cycle'da bir (30 sn) — Madde 3.2
        if self._cycle_count % 3 == 0:
            self.analyze_fake_signals()

        self._check_period_resets()
        self._evaluate_kill_switch_triggers()

        return regime

    # ═════════════════════════════════════════════════════════════════
    #  REJİM ALGILAMA
    # ═════════════════════════════════════════════════════════════════

    def detect_regime(self) -> Regime:
        """Piyasa rejimini algıla — öncelik: OLAY > VOLATILE > TREND > RANGE.

        Returns:
            Algılanan Regime nesnesi.
        """
        # ── 1) OLAY (takvim + kur, sembolden bağımsız) ───────────────
        olay_result = self._check_olay()
        if olay_result is not None:
            logger.info(
                f"Rejim: OLAY — {olay_result['reason']} "
                f"(multiplier={RISK_MULTIPLIERS[RegimeType.OLAY]})"
            )
            return Regime(
                regime_type=RegimeType.OLAY,
                confidence=1.0,
                details=olay_result,
            )

        # ── 2) Sembol bazlı teknik oylama ────────────────────────────
        votes: dict[RegimeType, int] = {
            RegimeType.TREND: 0,
            RegimeType.RANGE: 0,
            RegimeType.VOLATILE: 0,
        }
        adx_vals: list[float] = []
        atr_rats: list[float] = []
        bb_rats: list[float] = []
        details_per: dict[str, Any] = {}

        for symbol in WATCHED_SYMBOLS:
            result = self._classify_symbol(symbol)
            if result is None:
                continue
            votes[result["regime"]] += 1
            details_per[symbol] = result
            if result.get("adx") is not None:
                adx_vals.append(result["adx"])
            if result.get("atr_ratio") is not None:
                atr_rats.append(result["atr_ratio"])
            if result.get("bb_width_ratio") is not None:
                bb_rats.append(result["bb_width_ratio"])

        total = sum(votes.values())
        if total == 0:
            return Regime(regime_type=RegimeType.RANGE, confidence=0.0)

        # VOLATILE ≥ %30 → tüm piyasa VOLATILE
        if votes[RegimeType.VOLATILE] / total >= 0.30:
            winner = RegimeType.VOLATILE
        else:
            winner = max(votes, key=votes.get)

        confidence = round(votes[winner] / total, 3)

        regime = Regime(
            regime_type=winner,
            confidence=confidence,
            adx_value=round(float(np.mean(adx_vals)), 2) if adx_vals else 0.0,
            atr_ratio=round(float(np.mean(atr_rats)), 3) if atr_rats else 0.0,
            bb_width_ratio=round(float(np.mean(bb_rats)), 3) if bb_rats else 0.0,
            details={"per_symbol": details_per, "votes": {k.value: v for k, v in votes.items()}},
        )

        logger.info(
            f"Rejim: {winner.value} (conf={confidence}, "
            f"ADX={regime.adx_value}, ATR_r={regime.atr_ratio}, "
            f"votes={dict((k.value, v) for k, v in votes.items())}, "
            f"mult={regime.risk_multiplier})"
        )
        return regime

    # ── Sembol sınıflandırma ─────────────────────────────────────────
    def _classify_symbol(self, symbol: str) -> dict[str, Any] | None:
        """Tek sembol için VOLATILE / TREND / RANGE belirle.

        Args:
            symbol: Kontrat sembolü.

        Returns:
            Sınıflandırma sözlüğü veya None.
        """
        df = self._db.get_bars(symbol, "M5", limit=ATR_LOOKBACK)
        if df.empty or len(df) < max(ADX_PERIOD * 3, BB_PERIOD + 10):
            return None

        close = df["close"].values.astype(np.float64)
        high  = df["high"].values.astype(np.float64)
        low   = df["low"].values.astype(np.float64)

        adx_arr  = calc_adx(high, low, close, ADX_PERIOD)
        atr_arr  = calc_atr(high, low, close, ATR_PERIOD)
        ema_fast = ema(close, EMA_FAST)
        ema_slow = ema(close, EMA_SLOW)
        bb_u, _, bb_l = bollinger_bands(close, BB_PERIOD, BB_STD)

        adx_val  = last_valid(adx_arr)
        atr_val  = last_valid(atr_arr)
        atr_mean = nanmean(atr_arr)

        bb_width      = (last_valid(bb_u) or 0) - (last_valid(bb_l) or 0)
        bb_width_mean = nanmean(bb_u - bb_l)

        if adx_val is None or atr_val is None or atr_mean == 0:
            return None

        atr_ratio     = atr_val / atr_mean
        bb_width_ratio = bb_width / bb_width_mean if bb_width_mean > 0 else 1.0
        spread_mult   = self._current_spread_multiple(symbol)

        # Son bar hareket %
        last_move_pct = 0.0
        if len(close) >= 2 and close[-2] != 0:
            last_move_pct = abs(close[-1] - close[-2]) / close[-2] * 100

        base = {
            "adx": round(adx_val, 2),
            "atr_ratio": round(atr_ratio, 3),
            "bb_width_ratio": round(bb_width_ratio, 3),
        }

        # Öncelik: VOLATILE > TREND > RANGE
        if (
            atr_ratio > ATR_VOLATILE_MULT
            or spread_mult > SPREAD_VOLATILE_MULT
            or last_move_pct > PRICE_MOVE_PCT
        ):
            base["regime"] = RegimeType.VOLATILE
            base["reason"] = _volatile_reason(atr_ratio, spread_mult, last_move_pct)
            return base

        if self._check_trend(adx_val, ema_fast, ema_slow, close):
            base["regime"] = RegimeType.TREND
            return base

        if adx_val < ADX_RANGE_THRESHOLD and bb_width_ratio < BB_WIDTH_RATIO:
            base["regime"] = RegimeType.RANGE
            return base

        # Varsayılan (ADX 20-25 arası, belirsiz)
        base["regime"] = RegimeType.RANGE
        return base

    # ── TREND doğrulama ──────────────────────────────────────────────
    @staticmethod
    def _check_trend(
        adx_val: float,
        ema_fast: np.ndarray,
        ema_slow: np.ndarray,
        close: np.ndarray,
    ) -> bool:
        """TREND koşullarını doğrula.

        1. ADX > 25
        2. |EMA_fast - EMA_slow| genişliyor
        3. Son 5 barın 4'ü aynı yönde

        Args:
            adx_val: Son ADX değeri.
            ema_fast: Hızlı EMA dizisi.
            ema_slow: Yavaş EMA dizisi.
            close: Kapanış dizisi.

        Returns:
            TREND ise True.
        """
        if adx_val <= ADX_TREND_THRESHOLD:
            return False

        n = len(ema_fast)
        if n < EMA_DIRECTION_BARS + 1:
            return False

        distances = np.abs(ema_fast - ema_slow)
        recent = distances[-(EMA_DIRECTION_BARS + 1):]
        valid = recent[~np.isnan(recent)]
        if len(valid) < 3:
            return False
        if valid[-1] <= valid[0]:
            return False

        last_bars = close[-EMA_DIRECTION_BARS:]
        if len(last_bars) < EMA_DIRECTION_BARS:
            return False
        diffs = np.diff(last_bars)
        up   = int(np.sum(diffs > 0))
        down = int(np.sum(diffs < 0))
        return up >= EMA_DIRECTION_MIN or down >= EMA_DIRECTION_MIN

    # ── OLAY kontrolü ────────────────────────────────────────────────
    def _check_olay(self) -> dict[str, Any] | None:
        """TCMB/FED günü, vade sonu, kur şoku.

        Returns:
            Neden sözlüğü veya None.
        """
        today = date.today()

        if today in CENTRAL_BANK_DATES:
            return {"reason": "TCMB/FED toplantı günü", "trigger": "calendar"}

        for expiry in VIOP_EXPIRY_DATES:
            days = (expiry - today).days
            if 0 <= days <= EXPIRY_DAYS:
                return {
                    "reason": f"Vade bitiş: {expiry} ({days} gün kaldı)",
                    "trigger": "expiry",
                }

        usdtry_move = self._usdtry_5m_move_pct()
        if usdtry_move >= USDTRY_SHOCK_PCT:
            return {
                "reason": f"USD/TRY şoku: %{usdtry_move:.2f} (5dk)",
                "trigger": "usdtry",
                "value": usdtry_move,
            }

        return None

    # ═════════════════════════════════════════════════════════════════
    #  ERKEN UYARI
    # ═════════════════════════════════════════════════════════════════

    def check_early_warnings(self) -> list[EarlyWarning]:
        """Tüm erken uyarı tetikleyicilerini kontrol et.

        Returns:
            Tetiklenen EarlyWarning listesi.
        """
        warnings: list[EarlyWarning] = []

        for symbol in WATCHED_SYMBOLS:
            liq = self._get_liquidity_class(symbol)

            w = self._check_spread_spike(symbol, liq)
            if w:
                warnings.append(w)

            w = self._check_price_shock(symbol, liq)
            if w:
                warnings.append(w)

            w = self._check_volume_spike(symbol)
            if w:
                warnings.append(w)

        w = self._check_usdtry_shock()
        if w:
            warnings.append(w)

        if warnings:
            for w in warnings:
                self._db.insert_event(
                    event_type="EARLY_WARNING",
                    message=w.message,
                    severity=w.severity,
                    action=f"{w.warning_type}:{w.symbol}",
                )
            logger.warning(
                f"Erken uyarı: {len(warnings)} tetikleyici — "
                f"{[w.warning_type for w in warnings]}"
            )

        return warnings

    # ── Spread patlaması ─────────────────────────────────────────────
    def _check_spread_spike(
        self, symbol: str, liq_class: str
    ) -> EarlyWarning | None:
        """Spread patlaması: A→3×, B→4×, C→5×."""
        history = self._spread_history.get(symbol, [])
        if len(history) < 5:
            return None

        current = history[-1]
        avg = float(np.mean(history[:-1]))
        if avg <= 0:
            return None

        mult = current / avg
        threshold = SPREAD_SPIKE_MULT.get(liq_class, 5.0)

        if mult >= threshold:
            return EarlyWarning(
                warning_type="SPREAD_SPIKE",
                symbol=symbol,
                severity="CRITICAL" if mult >= threshold * 1.5 else "WARNING",
                value=round(mult, 2),
                threshold=threshold,
                liquidity_class=liq_class,
                message=(
                    f"Spread patlaması [{symbol}]: {mult:.1f}× "
                    f"(eşik={threshold}×, sınıf={liq_class})"
                ),
            )
        return None

    # ── Ani fiyat hareketi ───────────────────────────────────────────
    def _check_price_shock(
        self, symbol: str, liq_class: str
    ) -> EarlyWarning | None:
        """Son 1 bar fiyat şoku: A→%1.5, B→%2, C→%3."""
        df = self._db.get_bars(symbol, "M1", limit=2)
        if df.empty or len(df) < 2:
            return None

        close = df["close"].values.astype(np.float64)
        if close[-2] == 0:
            return None

        move_pct = abs(close[-1] - close[-2]) / close[-2] * 100
        threshold = PRICE_SHOCK_PCT.get(liq_class, 3.0)

        if move_pct >= threshold:
            return EarlyWarning(
                warning_type="PRICE_SHOCK",
                symbol=symbol,
                severity="CRITICAL" if move_pct >= threshold * 1.5 else "WARNING",
                value=round(move_pct, 3),
                threshold=threshold,
                liquidity_class=liq_class,
                message=(
                    f"Fiyat şoku [{symbol}]: %{move_pct:.2f} "
                    f"(eşik=%{threshold}, sınıf={liq_class})"
                ),
            )
        return None

    # ── Hacim patlaması ──────────────────────────────────────────────
    def _check_volume_spike(self, symbol: str) -> EarlyWarning | None:
        """5dk hacim > ortalama × 5."""
        df = self._db.get_bars(symbol, "M5", limit=50)
        if df.empty or len(df) < 10:
            return None

        vol = df["volume"].values.astype(np.float64)
        current_vol = vol[-1]
        avg_vol = float(np.mean(vol[:-1]))
        if avg_vol <= 0:
            return None

        mult = current_vol / avg_vol
        if mult >= VOLUME_SPIKE_MULT:
            return EarlyWarning(
                warning_type="VOLUME_SPIKE",
                symbol=symbol,
                severity="CRITICAL" if mult >= VOLUME_SPIKE_MULT * 2 else "WARNING",
                value=round(mult, 2),
                threshold=VOLUME_SPIKE_MULT,
                liquidity_class=self._get_liquidity_class(symbol),
                message=(
                    f"Hacim patlaması [{symbol}]: {mult:.1f}× "
                    f"(eşik={VOLUME_SPIKE_MULT}×)"
                ),
            )
        return None

    # ── USD/TRY şoku ─────────────────────────────────────────────────
    def _check_usdtry_shock(self) -> EarlyWarning | None:
        """5dk'da %0.5+ hareket."""
        move = self._usdtry_5m_move_pct()
        if move >= USDTRY_5M_SHOCK_PCT:
            return EarlyWarning(
                warning_type="USDTRY_SHOCK",
                symbol="USDTRY",
                severity="CRITICAL" if move >= 1.0 else "WARNING",
                value=round(move, 3),
                threshold=USDTRY_5M_SHOCK_PCT,
                liquidity_class="ALL",
                message=f"USD/TRY şoku: %{move:.3f}/5dk (eşik=%{USDTRY_5M_SHOCK_PCT})",
            )
        return None

    # ═════════════════════════════════════════════════════════════════
    #  POZİSYON BOYUTLAMA & DRAWDOWN
    # ═════════════════════════════════════════════════════════════════

    def calculate_position_size(
        self,
        symbol: str,
        risk_params: RiskParams,
        atr_value: float,
        account_equity: float,
    ) -> float:
        """Fixed-fractional pozisyon boyutlama (rejim çarpanlı).

        ``lot = (equity × risk% × regime_mult) / (ATR × kontrat_çarpanı)``

        Args:
            symbol: Kontrat sembolü.
            risk_params: Risk parametreleri.
            atr_value: Son ATR değeri.
            account_equity: Mevcut hesap equity.

        Returns:
            Lot sayısı (0.0 = işlem yapma).
        """
        if atr_value <= 0 or account_equity <= 0:
            return 0.0

        mult = self.current_regime.risk_multiplier
        if mult == 0:
            logger.info(
                f"Pozisyon=0 — rejim={self.current_regime.regime_type.value}"
            )
            return 0.0

        # Risk-per-trade hard cap (%2 üst sınır)
        effective_risk = min(
            risk_params.risk_per_trade,
            risk_params.max_risk_per_trade_hard,
        )
        risk_amount = account_equity * effective_risk * mult

        contract_size = 100.0
        vol_min = 1.0
        vol_step = 1.0
        if self._mt5:
            info = self._mt5.get_symbol_info(symbol)
            if info:
                contract_size = info.trade_contract_size
                vol_min = info.volume_min
                vol_step = info.volume_step

        lot = risk_amount / (atr_value * contract_size)

        if vol_step > 0:
            lot = math.floor(lot / vol_step) * vol_step
        lot = max(lot, 0.0)
        if lot > risk_params.max_position_size:
            lot = risk_params.max_position_size

        # Graduated lot schedule — kademeli kayıp azaltma (R3)
        # 1 kayıp: lot*0.75, 2 kayıp: lot*0.5, 3+ kayıp: cooldown (lot=0)
        consec = self._risk_state.get("consecutive_losses", 0)
        if consec >= risk_params.consecutive_loss_limit:
            logger.info(
                f"Graduated lot: {consec} üst üste kayıp ≥ limit "
                f"({risk_params.consecutive_loss_limit}) → lot=0"
            )
            return 0.0
        elif consec == 2:
            lot = lot * 0.5
            logger.debug(f"Graduated lot: 2 üst üste kayıp → lot*0.5={lot:.2f}")
        elif consec == 1:
            lot = lot * 0.75
            logger.debug(f"Graduated lot: 1 kayıp → lot*0.75={lot:.2f}")

        if vol_step > 0:
            lot = math.floor(lot / vol_step) * vol_step

        # Haftalık yarılama
        if self._risk_state.get("weekly_loss_halved"):
            lot = math.floor(lot * 0.5 / vol_step) * vol_step if vol_step > 0 else lot * 0.5
            logger.debug(f"Haftalık yarılama uygulandı: {lot}")

        logger.debug(
            f"Pozisyon [{symbol}]: {lot} lot "
            f"(eq={account_equity:.0f}, ATR={atr_value:.4f}, "
            f"mult={mult}, consec_loss={consec}, "
            f"rejim={self.current_regime.regime_type.value})"
        )
        return round(lot, 2)

    def check_drawdown_limits(self, risk_params: RiskParams, snap: dict | None = None) -> bool:
        """Günlük ve toplam drawdown limitlerini kontrol et.

        Args:
            risk_params: Risk parametreleri.
            snap: Önceden alınmış risk snapshot'ı. None ise DB'den çekilir.

        Returns:
            True → trading devam, False → durdur.
        """
        if snap is None:
            snap = self._db.get_latest_risk_snapshot()
        if not snap:
            return True

        daily_pnl = snap.get("daily_pnl", 0.0)
        equity    = snap.get("equity", 0.0)
        drawdown  = snap.get("drawdown", 0.0)

        if equity <= 0:
            logger.warning(
                "Equity/bakiye geçersiz (<=0) — işlem durduruluyor"
            )
            return False

        # Madde 1.2: Gün başı equity bazlı hesaplama
        # day_start_equity = anlık_equity - daily_pnl (daily_pnl = current - start)
        day_start_equity = equity - daily_pnl
        if daily_pnl < 0 and day_start_equity > 0:
            daily_loss_pct = abs(daily_pnl) / day_start_equity
        else:
            daily_loss_pct = 0.0

        if daily_loss_pct >= risk_params.max_daily_loss:
            logger.error(
                f"GÜNLÜK KAYIP LİMİTİ: %{daily_loss_pct*100:.2f} "
                f"(limit=%{risk_params.max_daily_loss*100:.1f})"
            )
            self._db.insert_event(
                event_type="DRAWDOWN_LIMIT",
                message=f"Günlük kayıp: %{daily_loss_pct*100:.2f}",
                severity="CRITICAL",
                action="stop_trading",
            )
            return False

        if drawdown >= risk_params.max_total_drawdown:
            logger.error(
                f"TOPLAM DRAWDOWN LİMİTİ: %{drawdown*100:.2f} "
                f"(limit=%{risk_params.max_total_drawdown*100:.1f})"
            )
            self._db.insert_event(
                event_type="DRAWDOWN_LIMIT",
                message=f"Toplam drawdown: %{drawdown*100:.2f}",
                severity="CRITICAL",
                action="stop_trading",
            )
            return False

        return True

    # ═════════════════════════════════════════════════════════════════
    #  PERİOD SIFIRLAMA
    # ═════════════════════════════════════════════════════════════════

    def _check_period_resets(self) -> None:
        """Gün/hafta/ay sıfırlamalarını kontrol et (her cycle çağrılır)."""
        now = datetime.now()
        today = date.today()
        market_open = now.hour > 9 or (now.hour == 9 and now.minute >= 30)

        # Günlük sıfırlama
        if self._risk_state["daily_reset_date"] != today and market_open:
            self._reset_daily(today)

        # Haftalık sıfırlama (Pazartesi ≥ 09:30)
        iso_cal = today.isocalendar()
        current_week = (iso_cal[0], iso_cal[1])
        if (
            self._risk_state["weekly_reset_week"] != current_week
            and today.weekday() == 0
            and market_open
        ):
            self._reset_weekly(current_week)

        # Aylık sıfırlama
        current_month = (today.year, today.month)
        if self._risk_state["monthly_reset_month"] != current_month and market_open:
            self._reset_monthly(current_month)

    def _reset_daily(self, today: date) -> None:
        """Günlük sayaçları sıfırla."""
        self._risk_state["daily_reset_date"] = today
        self._risk_state["daily_trade_count"] = 0

        # Günlük kayıp nedenli L2 varsa kaldır
        if (
            self._kill_switch_level == KILL_SWITCH_L2
            and self._kill_switch_details.get("reason") == "daily_loss"
        ):
            self._clear_kill_switch("Günlük sıfırlama — L2 kaldırıldı")

        logger.info(f"Günlük risk sıfırlama: {today}")
        self._db.insert_event(
            event_type="RISK_RESET",
            message=f"Günlük sıfırlama: {today}",
            severity="INFO",
            action="daily_reset",
        )

    def _reset_weekly(self, week_tuple: tuple) -> None:
        """Haftalık lot yarılama flagini sıfırla."""
        self._risk_state["weekly_reset_week"] = week_tuple
        self._risk_state["weekly_loss_halved"] = False
        logger.info(f"Haftalık risk sıfırlama: hafta {week_tuple}")
        self._db.insert_event(
            event_type="RISK_RESET",
            message=f"Haftalık sıfırlama: hafta {week_tuple}",
            severity="INFO",
            action="weekly_reset",
        )

    def _reset_monthly(self, month_tuple: tuple) -> None:
        """Aylık sayacı sıfırla (monthly_paused manuel onayla kalkar)."""
        self._risk_state["monthly_reset_month"] = month_tuple
        # monthly_paused SIFIRLANMAZ — manuel onay gerekli
        logger.info(f"Aylık risk periodu: {month_tuple}")

    # ═════════════════════════════════════════════════════════════════
    #  ÇOK KATMANLI RİSK KONTROLLERİ
    # ═════════════════════════════════════════════════════════════════

    def check_risk_limits(self, risk_params: RiskParams) -> RiskVerdict:
        """Tüm risk limitlerini kontrol et — ana giriş noktası.

        Kontrol sırası (öncelik):
            1. Kill-switch aktif mi?
            2. Aylık kayıp durumu
            3. Günlük kayıp (mevcut check_drawdown_limits)
            4. Haftalık kayıp
            5. Hard drawdown
            6. Aylık kayıp
            7. Floating loss
            8. Günlük işlem sayısı
            9. Üst üste kayıp / cooldown

        Args:
            risk_params: Risk parametreleri.

        Returns:
            RiskVerdict nesnesi.
        """
        verdict = RiskVerdict()

        # ── Tek sefer snapshot okuma (Madde 1.1) ──
        snap = self._db.get_latest_risk_snapshot()

        # 1. Kill-switch L3 → tam dur
        if self._kill_switch_level >= KILL_SWITCH_L3:
            verdict.can_trade = False
            verdict.lot_multiplier = 0.0
            verdict.kill_switch_level = KILL_SWITCH_L3
            verdict.reason = "KILL_SWITCH L3 aktif — tam kapanış"
            verdict.blocked_symbols = list(self._killed_symbols)
            return verdict

        # 2. Kill-switch L2 → sistem pause
        if self._kill_switch_level == KILL_SWITCH_L2:
            verdict.can_trade = False
            verdict.lot_multiplier = 0.0
            verdict.kill_switch_level = KILL_SWITCH_L2
            verdict.reason = "KILL_SWITCH L2 aktif — sistem durduruldu"
            return verdict

        # 3. Aylık kayıp → manuel onay bekleniyor
        if self._risk_state["monthly_paused"]:
            verdict.can_trade = False
            verdict.reason = "Aylık kayıp limiti — manuel onay bekleniyor"
            return verdict

        # 4. Günlük kayıp (mevcut metod)
        if not self.check_drawdown_limits(risk_params, snap=snap):
            self._activate_kill_switch(
                KILL_SWITCH_L2, "daily_loss",
                "Günlük kayıp limiti aşıldı",
            )
            verdict.can_trade = False
            verdict.reason = "Günlük kayıp limiti aşıldı"
            verdict.kill_switch_level = KILL_SWITCH_L2
            return verdict

        # 5. Hard drawdown (%15+) / Max drawdown (%10+)
        dd_check = self._check_hard_drawdown(risk_params, snap=snap)
        if dd_check == "hard":
            self._activate_kill_switch(
                KILL_SWITCH_L3, "hard_drawdown",
                f"Hard drawdown limiti aşıldı (>{risk_params.hard_drawdown*100:.0f}%)",
            )
            verdict.can_trade = False
            verdict.reason = "Hard drawdown — tam kapanış"
            verdict.kill_switch_level = KILL_SWITCH_L3
            return verdict
        elif dd_check == "soft":
            self._activate_kill_switch(
                KILL_SWITCH_L3, "max_drawdown",
                f"Max drawdown limiti aşıldı (>{risk_params.max_total_drawdown*100:.0f}%)",
            )
            verdict.can_trade = False
            verdict.reason = "Max drawdown — tam kapanış + manuel onay"
            verdict.kill_switch_level = KILL_SWITCH_L3
            return verdict

        # 6. Aylık kayıp (%7+)
        if self._check_monthly_loss(risk_params, snap=snap):
            self._risk_state["monthly_paused"] = True
            self._activate_kill_switch(
                KILL_SWITCH_L2, "monthly_loss",
                "Aylık kayıp limiti aşıldı",
            )
            verdict.can_trade = False
            verdict.reason = "Aylık kayıp limiti — sistem dur"
            return verdict

        # 7. Haftalık kayıp (%4+ → lot yarılama)
        weekly_check = self._check_weekly_loss(risk_params, snap=snap)
        if weekly_check == "halved":
            verdict.lot_multiplier = 0.5
            verdict.details["weekly_halved"] = True

        # 8. Floating loss (%1.5+)
        if self._check_floating_loss(risk_params, snap=snap):
            verdict.can_trade = False
            verdict.reason = f"Floating loss > %{risk_params.max_floating_loss*100:.1f} — yeni işlem engeli"
            return verdict

        # 9. Günlük işlem sayısı
        if self._risk_state["daily_trade_count"] >= risk_params.max_daily_trades:
            verdict.can_trade = False
            verdict.reason = f"Günlük max işlem ({risk_params.max_daily_trades}) doldu"
            return verdict

        # 10. Cooldown (üst üste kayıp)
        if self._is_in_cooldown():
            verdict.can_trade = False
            verdict.reason = "Cooldown aktif (üst üste kayıp)"
            return verdict

        # 11. Üst üste kayıp kontrol
        self._update_consecutive_losses()
        if self._risk_state["consecutive_losses"] >= risk_params.consecutive_loss_limit:
            self._start_cooldown(risk_params)
            self._activate_kill_switch(
                KILL_SWITCH_L2, "consecutive_loss",
                f"{risk_params.consecutive_loss_limit} üst üste kayıp — cooldown",
            )
            verdict.can_trade = False
            verdict.reason = f"{risk_params.consecutive_loss_limit} üst üste kayıp — cooldown başladı"
            verdict.kill_switch_level = KILL_SWITCH_L2
            return verdict

        # v13.0: Risk göstergesi varken izin verildi → olay kaydı (ÜSTAT beslemesi)
        # 5 dk'da en fazla 1 kez logla (her cycle'da loglama çok fazla kayıt oluşturur)
        if self.active_warnings and verdict.can_trade:
            now = datetime.now()
            should_log = (
                self._last_risk_allowed_log is None
                or (now - self._last_risk_allowed_log).total_seconds() >= 300
            )
            if should_log:
                self._last_risk_allowed_log = now
                warning_symbols = {
                    w.symbol for w in self.active_warnings
                    if hasattr(w, "symbol")
                }
                self._db.insert_event(
                    event_type="RISK_ALLOWED",
                    message=(
                        f"Risk göstergesi aktif ({len(self.active_warnings)} uyarı, "
                        f"semboller: {', '.join(sorted(warning_symbols))}) "
                        f"ancak ticarete izin verildi"
                    ),
                    severity="INFO",
                    action="baba_risk_check",
                )

        return verdict

    # ── Alt kontroller ────────────────────────────────────────────────

    def _check_weekly_loss(self, risk_params: RiskParams, snap: dict | None = None) -> str | None:
        """Haftalık kayıp kontrolü.

        Args:
            risk_params: Risk parametreleri.
            snap: Önceden alınmış risk snapshot'ı. None ise DB'den çekilir.

        Returns:
            ``"halved"`` → lot %50 azalt, ``None`` → normal.
        """
        if snap is None:
            snap = self._db.get_latest_risk_snapshot()
        if not snap:
            return None

        today = date.today()
        monday = today - timedelta(days=today.weekday())
        # Baseline: eski veriler risk hesabını etkilemesin
        since_str = max(
            f"{monday.isoformat()}T00:00:00",
            f"{RISK_BASELINE_DATE}T00:00:00",
        )
        snapshots = self._db.get_risk_snapshots(
            since=since_str, limit=500,
        )
        if not snapshots:
            return None

        # En eski snapshot = hafta başı equity
        week_start_equity = snapshots[-1].get("equity", 0.0)
        current_equity = snap.get("equity", 0.0)

        if week_start_equity <= 0:
            return None

        weekly_loss_pct = (week_start_equity - current_equity) / week_start_equity

        if weekly_loss_pct >= risk_params.max_weekly_loss:
            if not self._risk_state["weekly_loss_halved"]:
                self._risk_state["weekly_loss_halved"] = True
                logger.warning(
                    f"HAFTALIK KAYIP LİMİTİ: %{weekly_loss_pct*100:.2f} "
                    f"(limit=%{risk_params.max_weekly_loss*100:.1f}) — lot %50 azaltıldı"
                )
                self._db.insert_event(
                    event_type="RISK_LIMIT",
                    message=f"Haftalık kayıp: %{weekly_loss_pct*100:.2f} — lot %50",
                    severity="ERROR",
                    action="lot_halved",
                )
            return "halved"
        return None

    def _check_monthly_loss(self, risk_params: RiskParams, snap: dict | None = None) -> bool:
        """Aylık kayıp kontrolü.

        Args:
            risk_params: Risk parametreleri.
            snap: Önceden alınmış risk snapshot'ı. None ise DB'den çekilir.

        Returns:
            True → aylık limit aşıldı → sistem durdurulmalı.
        """
        if snap is None:
            snap = self._db.get_latest_risk_snapshot()
        if not snap:
            return False

        today = date.today()
        month_start = today.replace(day=1)
        # Baseline: eski veriler risk hesabını etkilemesin
        since_str = max(
            f"{month_start.isoformat()}T00:00:00",
            f"{RISK_BASELINE_DATE}T00:00:00",
        )
        snapshots = self._db.get_risk_snapshots(
            since=since_str, limit=1000,
        )
        if not snapshots:
            return False

        month_start_equity = snapshots[-1].get("equity", 0.0)
        current_equity = snap.get("equity", 0.0)

        if month_start_equity <= 0:
            return False

        monthly_loss_pct = (month_start_equity - current_equity) / month_start_equity

        if monthly_loss_pct >= risk_params.max_monthly_loss:
            logger.critical(
                f"AYLIK KAYIP LİMİTİ: %{monthly_loss_pct*100:.2f} "
                f"(limit=%{risk_params.max_monthly_loss*100:.1f}) — SİSTEM DURDURULUYOR"
            )
            self._db.insert_event(
                event_type="RISK_LIMIT",
                message=f"Aylık kayıp: %{monthly_loss_pct*100:.2f} — sistem dur",
                severity="CRITICAL",
                action="system_stop",
            )
            return True
        return False

    def _check_hard_drawdown(self, risk_params: RiskParams, snap: dict | None = None) -> str | None:
        """Hard ve soft drawdown kontrolü.

        Args:
            risk_params: Risk parametreleri.
            snap: Önceden alınmış risk snapshot'ı. None ise DB'den çekilir.

        Returns:
            ``"hard"`` → %15+, ``"soft"`` → %10+, ``None`` → normal.
        """
        if snap is None:
            snap = self._db.get_latest_risk_snapshot()
        if not snap:
            return None

        drawdown = snap.get("drawdown", 0.0)

        if drawdown >= risk_params.hard_drawdown:
            logger.critical(
                f"HARD DRAWDOWN: %{drawdown*100:.2f} "
                f"(limit=%{risk_params.hard_drawdown*100:.1f})"
            )
            return "hard"

        if drawdown >= risk_params.max_total_drawdown:
            return "soft"

        return None

    def _check_floating_loss(self, risk_params: RiskParams, snap: dict | None = None) -> bool:
        """Floating (açık pozisyon) kayıp kontrolü.

        Args:
            risk_params: Risk parametreleri.
            snap: Önceden alınmış risk snapshot'ı. None ise DB'den çekilir.

        Returns:
            True → floating loss > %1.5 → yeni işlem engeli.
        """
        if snap is None:
            snap = self._db.get_latest_risk_snapshot()
        if not snap:
            return False

        equity = snap.get("equity", 0.0)
        floating_pnl = snap.get("floating_pnl", 0.0)

        if equity <= 0:
            return False

        if floating_pnl < 0:
            # Madde 1.3: Balance bazlı hesaplama (equity zaten floating'den etkilenmiş)
            # MT5: equity = balance + floating_pnl → balance = equity - floating_pnl
            balance = equity - floating_pnl
            if balance <= 0:
                return False
            floating_loss_pct = abs(floating_pnl) / balance
            if floating_loss_pct >= risk_params.max_floating_loss:
                logger.warning(
                    f"FLOATING LOSS ENGELİ: %{floating_loss_pct*100:.2f} "
                    f"(limit=%{risk_params.max_floating_loss*100:.1f})"
                )
                return True
        return False

    def _update_consecutive_losses(self) -> None:
        """Üst üste kayıp sayacını DB'den güncelle.

        Madde 1.6: Sadece son cooldown bitişinden sonraki trade'leri sayar.
        Bu, cooldown → tekrar aynı trade'leri sayma → tekrar cooldown
        sonsuz döngüsünü önler.
        """
        # Cooldown sonrası veya RISK_BASELINE_DATE sonrası (hangisi yeniyse)
        since = self._risk_state.get("last_cooldown_end") or RISK_BASELINE_DATE
        trades = self._db.get_trades(limit=10, since=since)
        closed = [
            t for t in trades
            if t.get("pnl") is not None
            and t.get("exit_time") is not None
        ]

        count = 0
        for trade in closed:
            if trade.get("pnl", 0.0) < 0:
                count += 1
            else:
                break
        self._risk_state["consecutive_losses"] = count

    def _start_cooldown(self, risk_params: RiskParams) -> None:
        """Cool-down başlat."""
        self._risk_state["cooldown_until"] = (
            datetime.now() + timedelta(hours=risk_params.cooldown_hours)
        )
        logger.warning(
            f"COOLDOWN BAŞLADI: {risk_params.cooldown_hours} saat "
            f"(üst üste {risk_params.consecutive_loss_limit} kayıp)"
        )
        self._db.insert_event(
            event_type="COOLDOWN",
            message=(
                f"{risk_params.cooldown_hours}s cooldown — "
                f"{risk_params.consecutive_loss_limit} üst üste kayıp"
            ),
            severity="WARNING",
            action="cooldown_start",
        )

    def _is_in_cooldown(self) -> bool:
        """Cooldown süresi içinde miyiz?"""
        until = self._risk_state.get("cooldown_until")
        if until is None:
            return False
        if datetime.now() < until:
            return True
        # Cooldown bitti — Madde 1.6: timestamp kaydet (sonsuz döngü önlemi)
        self._risk_state["cooldown_until"] = None
        self._risk_state["consecutive_losses"] = 0
        self._risk_state["last_cooldown_end"] = datetime.now().isoformat(timespec="seconds")
        logger.info("Cooldown sona erdi.")
        self._db.insert_event(
            event_type="COOLDOWN",
            message="Cooldown sona erdi",
            severity="INFO",
            action="cooldown_end",
        )
        return False

    def increment_daily_trade_count(self) -> None:
        """Bir işlem açıldığında çağrılır (Oğul tarafından).

        Günlük işlem sayacını arttırır.
        """
        self._risk_state["daily_trade_count"] += 1
        logger.debug(
            f"Günlük işlem sayısı: {self._risk_state['daily_trade_count']}"
        )

    # ═════════════════════════════════════════════════════════════════
    #  KORELASYON YÖNETİMİ
    # ═════════════════════════════════════════════════════════════════

    def check_correlation_limits(
        self,
        symbol: str,
        direction: str,
        risk_params: RiskParams,
    ) -> RiskVerdict:
        """Yeni işlem için korelasyon kontrolü.

        Kontroller:
            1. Aynı yönde max 3 pozisyon
            2. Aynı sektörde aynı yönde max 2 pozisyon
            3. Endeks ağırlık skoru < 0.25

        Args:
            symbol: Açılmak istenen kontrat.
            direction: ``"BUY"`` veya ``"SELL"``.
            risk_params: Risk parametreleri.

        Returns:
            RiskVerdict — ``can_trade=False`` ise korelasyon engeli.
        """
        verdict = RiskVerdict()

        if self._mt5 is None:
            return verdict

        positions = self._mt5.get_positions()
        if not positions:
            return verdict

        # 1. Aynı yönde max pozisyon
        same_dir = [p for p in positions if p.get("type") == direction]
        if len(same_dir) >= risk_params.max_same_direction:
            verdict.can_trade = False
            verdict.reason = (
                f"Aynı yönde ({direction}) max {risk_params.max_same_direction} "
                f"pozisyon limiti doldu"
            )
            return verdict

        # 2. Aynı sektörde aynı yönde max pozisyon
        target_sector = SYMBOL_TO_SECTOR.get(symbol, "diger")
        same_sector_dir = [
            p for p in positions
            if p.get("type") == direction
            and SYMBOL_TO_SECTOR.get(p.get("symbol", ""), "diger") == target_sector
        ]
        if len(same_sector_dir) >= risk_params.max_same_sector_direction:
            verdict.can_trade = False
            verdict.reason = (
                f"Sektör ({target_sector}) aynı yönde ({direction}) max "
                f"{risk_params.max_same_sector_direction} pozisyon limiti doldu"
            )
            return verdict

        # 3. Endeks ağırlık skoru
        index_score = self._calculate_index_weight_score(
            positions, symbol, direction,
        )
        if index_score > risk_params.max_index_weight_score:
            verdict.can_trade = False
            verdict.reason = (
                f"Endeks ağırlık skoru {index_score:.3f} > "
                f"limit {risk_params.max_index_weight_score}"
            )
            return verdict

        return verdict

    def _calculate_index_weight_score(
        self,
        positions: list[dict],
        new_symbol: str,
        new_direction: str,
        new_lot: float = 1.0,
    ) -> float:
        """Endeks ağırlık skoru hesapla.

        Formül: ``abs(sum(lot_i × xu030_weight_i × sign_i))``

        Args:
            positions: Mevcut açık pozisyonlar.
            new_symbol: Yeni işlem sembolü.
            new_direction: Yeni işlem yönü.
            new_lot: Yeni işlem lot miktarı.

        Returns:
            Endeks ağırlık skoru.
        """
        score = 0.0
        for pos in positions:
            weight = XU030_WEIGHTS.get(pos.get("symbol", ""), 0.0)
            sign = 1.0 if pos.get("type") == "BUY" else -1.0
            score += pos.get("volume", 0.0) * weight * sign

        # Yeni işlem dahil
        new_weight = XU030_WEIGHTS.get(new_symbol, 0.0)
        new_sign = 1.0 if new_direction == "BUY" else -1.0
        score += new_lot * new_weight * new_sign

        return abs(score)

    # ═════════════════════════════════════════════════════════════════
    #  KILL-SWITCH
    # ═════════════════════════════════════════════════════════════════

    def _activate_kill_switch(
        self,
        level: int,
        reason: str,
        message: str,
        symbols: list[str] | None = None,
    ) -> None:
        """Kill-switch'i etkinleştir.

        Sadece yukarı yönlü geçiş (L1→L2 olur ama L2→L1 olmaz).

        Args:
            level: Seviye (1, 2, 3).
            reason: Neden kodu.
            message: Log/event mesajı.
            symbols: L1 için etkilenen semboller.
        """
        if level <= self._kill_switch_level:
            return

        self._kill_switch_level = level
        self._kill_switch_details = {
            "reason": reason,
            "message": message,
            "triggered_at": datetime.now().isoformat(),
            "symbols": symbols or [],
        }

        if level == KILL_SWITCH_L1 and symbols:
            self._killed_symbols.update(symbols)

        severity = {1: "WARNING", 2: "ERROR", 3: "CRITICAL"}.get(level, "CRITICAL")

        logger.log(
            {"WARNING": 30, "ERROR": 40, "CRITICAL": 50}[severity],
            f"KILL-SWITCH L{level} AKTİF: {message}",
        )

        self._db.insert_event(
            event_type="KILL_SWITCH",
            message=message,
            severity=severity,
            action=f"LEVEL_{level}",
        )

        # L3: tüm pozisyonları kapat; başarısız ticket listesi saklanır
        if level == KILL_SWITCH_L3:
            self._last_l3_failed_tickets = self._close_all_positions("KILL_SWITCH_L3")

    def _clear_kill_switch(self, reason: str) -> None:
        """Kill-switch'i temizle.

        Args:
            reason: Temizleme nedeni.
        """
        old_level = self._kill_switch_level
        self._kill_switch_level = KILL_SWITCH_NONE
        self._kill_switch_details = {}
        self._killed_symbols.clear()

        logger.info(f"Kill-switch temizlendi (L{old_level}→L0): {reason}")
        self._db.insert_event(
            event_type="KILL_SWITCH",
            message=f"Kill-switch temizlendi (L{old_level}): {reason}",
            severity="INFO",
            action="LEVEL_0",
        )

    def acknowledge_kill_switch(self, user: str = "operator") -> bool:
        """Manuel kill-switch onay (Desktop/API'den çağrılır).

        L3 veya monthly_paused durumunu onaylayıp sistemi sıfırlar.

        Args:
            user: Onayı veren kullanıcı.

        Returns:
            True ise onay başarılı.
        """
        if self._kill_switch_level == KILL_SWITCH_NONE:
            return False

        self._db.insert_intervention(
            action=f"kill_switch_ack_L{self._kill_switch_level}",
            reason=self._kill_switch_details.get("message", ""),
            user=user,
        )

        self._risk_state["monthly_paused"] = False
        self._clear_kill_switch(f"Manuel onay by {user}")
        return True

    def activate_kill_switch_l1(self, symbol: str, reason: str) -> None:
        """L1: Tek kontrat durdur (anomali tespitinde dışardan çağrılır).

        Args:
            symbol: Durdurulacak kontrat.
            reason: Neden.
        """
        # L1 özel: mevcut seviyeyi yükseltmez, sadece sembolü ekler
        if self._kill_switch_level <= KILL_SWITCH_L1:
            self._kill_switch_level = KILL_SWITCH_L1
            self._kill_switch_details = {
                "reason": reason,
                "message": f"L1 kontrat durdurma: {symbol} — {reason}",
                "triggered_at": datetime.now().isoformat(),
            }
        self._killed_symbols.add(symbol)

        logger.warning(f"KILL-SWITCH L1: {symbol} durduruldu — {reason}")
        self._db.insert_event(
            event_type="KILL_SWITCH",
            message=f"L1 kontrat durdurma: {symbol} — {reason}",
            severity="WARNING",
            action="LEVEL_1",
        )

    def activate_kill_switch_l3_manual(self, user: str = "operator") -> None:
        """L3: Manuel tam kapanış (Desktop'tan 2s basılı + onay).

        Args:
            user: Butona basan kullanıcı.
        """
        self._db.insert_intervention(
            action="manual_kill_switch_L3",
            reason="Manuel tam kapanış butonu",
            user=user,
        )
        self._activate_kill_switch(
            KILL_SWITCH_L3, "manual",
            f"Manuel tam kapanış — {user}",
        )

    def is_symbol_killed(self, symbol: str) -> bool:
        """Kontrat L1 ile durdurulmuş mu?

        Args:
            symbol: Kontrat sembolü.

        Returns:
            True ise durdurulmuş.
        """
        return symbol in self._killed_symbols

    def _close_all_positions(self, reason: str) -> list[int]:
        """Tüm açık pozisyonları kapat (L3 için).

        Args:
            reason: Kapanış nedeni.

        Returns:
            Kapatılamayan pozisyon ticket listesi (boş ise hepsi kapatıldı).
        """
        failed_tickets: list[int] = []
        if self._mt5 is None:
            logger.error("MT5 bağlantısı yok — pozisyonlar kapatılamadı")
            return failed_tickets

        try:
            positions = self._mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası (close_all): {exc}")
            return failed_tickets
        CLOSE_MAX_RETRIES = 3
        closed_count = 0
        for pos in positions:
            ticket = pos.get("ticket")
            if ticket:
                closed = False
                for attempt in range(1, CLOSE_MAX_RETRIES + 1):
                    try:
                        result = self._mt5.close_position(ticket)
                    except Exception as exc:
                        logger.error(
                            f"close_position hatası ticket={ticket} "
                            f"(deneme {attempt}/{CLOSE_MAX_RETRIES}): {exc}"
                        )
                        result = None
                    if result:
                        closed_count += 1
                        closed = True
                        logger.info(
                            f"Pozisyon kapatıldı: {ticket} ({reason}) "
                            f"deneme {attempt}/{CLOSE_MAX_RETRIES}"
                        )
                        break
                    else:
                        logger.warning(
                            f"Kapanış denemesi {attempt}/{CLOSE_MAX_RETRIES} "
                            f"başarısız: ticket={ticket}"
                        )
                if not closed:
                    failed_tickets.append(ticket)
                    logger.error(
                        f"Pozisyon {CLOSE_MAX_RETRIES} denemede kapatılamadı: "
                        f"ticket={ticket}"
                    )

        if closed_count > 0:
            self._db.insert_event(
                event_type="KILL_SWITCH",
                message=f"{closed_count} pozisyon kapatıldı ({reason})",
                severity="CRITICAL",
                action="positions_closed",
            )
        if failed_tickets:
            self._db.insert_event(
                event_type="KILL_SWITCH",
                message=f"Kapatılamayan pozisyonlar: {failed_tickets}",
                severity="CRITICAL",
                action="positions_close_failed",
            )
        return failed_tickets

    def _evaluate_kill_switch_triggers(self) -> None:
        """Erken uyarılardan L1 tetikleyicilerini değerlendir."""
        for warning in self.active_warnings:
            if warning.severity == "CRITICAL" and warning.symbol != "USDTRY":
                if warning.symbol not in self._killed_symbols:
                    self.activate_kill_switch_l1(
                        warning.symbol,
                        f"Erken uyarı: {warning.warning_type} "
                        f"(değer={warning.value})",
                    )

        # OLAY rejimi → L2
        if self.current_regime.regime_type == RegimeType.OLAY:
            if self._kill_switch_level < KILL_SWITCH_L2:
                self._activate_kill_switch(
                    KILL_SWITCH_L2, "olay_regime",
                    "OLAY rejimi algılandı — L2 sistem pause",
                )
        # OLAY rejimi kalktıysa ve L2 olay_regime nedenli ise → temizle
        elif (
            self._kill_switch_level == KILL_SWITCH_L2
            and self._kill_switch_details.get("reason") == "olay_regime"
        ):
            self._clear_kill_switch(
                "OLAY rejimi sona erdi — L2 otomatik kaldırıldı"
            )

    # ═════════════════════════════════════════════════════════════════
    #  FAKE SİNYAL ANALİZİ
    # ═════════════════════════════════════════════════════════════════

    def analyze_fake_signals(self) -> list[FakeAnalysis]:
        """Tüm açık pozisyonlar için fake sinyal analizi.

        Her 10 sn'de ``run_cycle()`` içinden çağrılır.
        ``total_score >= FAKE_SCORE_THRESHOLD`` olan pozisyonlar
        otomatik kapatılır.

        Returns:
            FakeAnalysis listesi (tüm pozisyonlar için).
        """
        if self._mt5 is None:
            return []

        try:
            positions = self._mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası (fake analiz): {exc}")
            return []
        if not positions:
            return []

        results: list[FakeAnalysis] = []

        for pos in positions:
            symbol = pos.get("symbol", "")
            direction = pos.get("type", "")
            ticket = pos.get("ticket", 0)

            if not symbol or not direction:
                continue

            analysis = self._analyze_fake_signal(symbol, direction, ticket)
            results.append(analysis)

            if analysis.total_score >= FAKE_SCORE_THRESHOLD:
                logger.warning(
                    f"FAKE SİNYAL [{symbol}] ticket={ticket}: "
                    f"skor={analysis.total_score}/{FAKE_SCORE_THRESHOLD} "
                    f"— POZİSYON KAPATILIYOR"
                )

                # Pozisyonu kapat
                try:
                    close_result = self._mt5.close_position(ticket)
                except Exception as exc:
                    logger.error(f"close_position hatası (fake) ticket={ticket}: {exc}")
                    close_result = None
                if close_result:
                    logger.info(f"Fake sinyal kapatma başarılı: {ticket}")
                else:
                    logger.error(f"Fake sinyal kapatma başarısız: {ticket}")

                # Event kaydet
                self._db.insert_event(
                    event_type="FAKE_SIGNAL",
                    message=(
                        f"Fake sinyal: {symbol} {direction} ticket={ticket} "
                        f"skor={analysis.total_score} — "
                        f"V={analysis.volume_layer.score} "
                        f"S={analysis.spread_layer.score} "
                        f"TF={analysis.multi_tf_layer.score} "
                        f"M={analysis.momentum_layer.score}"
                    ),
                    severity="WARNING",
                    action="position_closed",
                )

                # DB trade kaydını güncelle
                trades = self._db.get_trades(symbol=symbol, limit=10)
                active_trade = next(
                    (
                        t for t in trades
                        if t.get("exit_time") is None
                        and t.get("direction") == direction
                    ),
                    None,
                )
                if active_trade:
                    self._db.update_trade(
                        active_trade["id"],
                        {"fake_score": analysis.total_score},
                    )
                else:
                    logger.warning(
                        f"Fake sinyal: DB'de aktif trade bulunamadı "
                        f"({symbol} {direction})"
                    )

        return results

    def _analyze_fake_signal(
        self,
        symbol: str,
        direction: str,
        ticket: int,
    ) -> FakeAnalysis:
        """Tek pozisyon için 4 katmanlı fake sinyal analizi.

        Args:
            symbol: Kontrat sembolü.
            direction: ``"BUY"`` veya ``"SELL"``.
            ticket: MT5 pozisyon ticket numarası.

        Returns:
            FakeAnalysis sonucu.
        """
        analysis = FakeAnalysis(
            symbol=symbol,
            direction=direction,
            ticket=ticket,
        )

        analysis.volume_layer = self._fake_check_volume(symbol)
        analysis.spread_layer = self._fake_check_spread(symbol)
        analysis.multi_tf_layer = self._fake_check_multi_tf(symbol, direction)
        analysis.momentum_layer = self._fake_check_momentum(symbol, direction)

        logger.debug(
            f"Fake analiz [{symbol}] t={ticket}: "
            f"skor={analysis.total_score} "
            f"(V={analysis.volume_layer.score} "
            f"S={analysis.spread_layer.score} "
            f"TF={analysis.multi_tf_layer.score} "
            f"M={analysis.momentum_layer.score})"
        )
        return analysis

    # ── Katman 1: Hacim ───────────────────────────────────────────────

    def _fake_check_volume(self, symbol: str) -> FakeLayerResult:
        """Fake sinyal — hacim katmanı.

        ``volume / 20-bar ort. < 0.7`` → FAKE (ağırlık: 1).

        Args:
            symbol: Kontrat sembolü.

        Returns:
            FakeLayerResult.
        """
        df = self._db.get_bars(symbol, "M5", limit=FAKE_VOLUME_LOOKBACK + 1)
        if df.empty or len(df) < FAKE_VOLUME_LOOKBACK + 1:
            return FakeLayerResult(
                "volume", False, FAKE_WEIGHT_VOLUME, 0, "yetersiz veri",
            )

        vol = df["volume"].values.astype(np.float64)
        current_vol = vol[-1]
        avg_vol = float(np.mean(vol[:-1]))

        if avg_vol <= 0:
            return FakeLayerResult(
                "volume", False, FAKE_WEIGHT_VOLUME, 0,
                "ortalama hacim 0",
            )

        ratio = current_vol / avg_vol

        if ratio < FAKE_VOLUME_RATIO_MIN:
            return FakeLayerResult(
                "volume", True, FAKE_WEIGHT_VOLUME, FAKE_WEIGHT_VOLUME,
                f"hacim oranı {ratio:.2f} < {FAKE_VOLUME_RATIO_MIN}",
            )

        return FakeLayerResult(
            "volume", False, FAKE_WEIGHT_VOLUME, 0,
            f"hacim oranı {ratio:.2f} (normal)",
        )

    # ── Katman 2: Spread ──────────────────────────────────────────────

    def _fake_check_spread(self, symbol: str) -> FakeLayerResult:
        """Fake sinyal — spread katmanı.

        ``spread / ort. > eşik`` → FAKE (ağırlık: 2).
        Eşikler: A > 2.5×, B > 3.5×, C > 5.0×.

        Args:
            symbol: Kontrat sembolü.

        Returns:
            FakeLayerResult.
        """
        history = self._spread_history.get(symbol, [])
        if len(history) < 5:
            return FakeLayerResult(
                "spread", False, FAKE_WEIGHT_SPREAD, 0,
                "yetersiz spread verisi",
            )

        current = history[-1]
        lookback = min(FAKE_VOLUME_LOOKBACK, len(history) - 1)
        avg = float(np.mean(history[-lookback - 1:-1]))

        if avg <= 0:
            return FakeLayerResult(
                "spread", False, FAKE_WEIGHT_SPREAD, 0,
                "ortalama spread 0",
            )

        mult = current / avg
        liq_class = self._get_liquidity_class(symbol)
        threshold = FAKE_SPREAD_MULT.get(liq_class, 5.0)

        if mult > threshold:
            return FakeLayerResult(
                "spread", True, FAKE_WEIGHT_SPREAD, FAKE_WEIGHT_SPREAD,
                f"spread {mult:.1f}× > eşik {threshold}× (sınıf={liq_class})",
            )

        return FakeLayerResult(
            "spread", False, FAKE_WEIGHT_SPREAD, 0,
            f"spread {mult:.1f}× (normal, sınıf={liq_class})",
        )

    # ── Katman 3: Multi-TF ────────────────────────────────────────────

    def _fake_check_multi_tf(
        self,
        symbol: str,
        direction: str,
    ) -> FakeLayerResult:
        """Fake sinyal — çoklu zaman dilimi katmanı.

        M5, M15, H1 yön uyumu < 2/3 → FAKE (ağırlık: 1).
        Yön: ``close > EMA-9`` → BUY, ``close < EMA-9`` → SELL.

        Args:
            symbol: Kontrat sembolü.
            direction: Pozisyon yönü (``"BUY"``/``"SELL"``).

        Returns:
            FakeLayerResult.
        """
        timeframes = ["M5", "M15", "H1"]
        agreements = 0
        valid_tf = 0

        for tf in timeframes:
            df = self._db.get_bars(
                symbol, tf, limit=FAKE_MTF_EMA_PERIOD + 5,
            )
            if df.empty or len(df) < FAKE_MTF_EMA_PERIOD + 1:
                continue

            close = df["close"].values.astype(np.float64)
            ema_arr = ema(close, FAKE_MTF_EMA_PERIOD)
            last_close = close[-1]
            last_ema = last_valid(ema_arr)

            if last_ema is None:
                continue

            tf_direction = "BUY" if last_close > last_ema else "SELL"
            valid_tf += 1
            if tf_direction == direction:
                agreements += 1

        if valid_tf < 2:
            return FakeLayerResult(
                "multi_tf", False, FAKE_WEIGHT_MULTI_TF, 0,
                f"yetersiz TF verisi ({valid_tf}/3)",
            )

        if agreements < FAKE_MTF_AGREEMENT_MIN:
            return FakeLayerResult(
                "multi_tf", True, FAKE_WEIGHT_MULTI_TF, FAKE_WEIGHT_MULTI_TF,
                f"TF uyumu {agreements}/{valid_tf} < {FAKE_MTF_AGREEMENT_MIN}/3",
            )

        return FakeLayerResult(
            "multi_tf", False, FAKE_WEIGHT_MULTI_TF, 0,
            f"TF uyumu {agreements}/{valid_tf} (normal)",
        )

    # ── Katman 4: Momentum ────────────────────────────────────────────

    def _fake_check_momentum(
        self,
        symbol: str,
        direction: str,
    ) -> FakeLayerResult:
        """Fake sinyal — momentum katmanı.

        (RSI > 80 veya RSI < 20) VE MACD histogram yön uyumsuzluğu
        → FAKE (ağırlık: 2).

        MACD diverjans: BUY için hist < 0, SELL için hist > 0.

        Args:
            symbol: Kontrat sembolü.
            direction: Pozisyon yönü (``"BUY"``/``"SELL"``).

        Returns:
            FakeLayerResult.
        """
        df = self._db.get_bars(symbol, "M5", limit=50)
        if df.empty or len(df) < 35:
            return FakeLayerResult(
                "momentum", False, FAKE_WEIGHT_MOMENTUM, 0,
                "yetersiz momentum verisi",
            )

        close = df["close"].values.astype(np.float64)

        # RSI kontrolü
        rsi_arr = calc_rsi(close, FAKE_RSI_PERIOD)
        rsi_val = last_valid(rsi_arr)
        if rsi_val is None:
            return FakeLayerResult(
                "momentum", False, FAKE_WEIGHT_MOMENTUM, 0,
                "RSI hesaplanamadı",
            )

        rsi_extreme = (rsi_val > FAKE_RSI_OVERBOUGHT
                       or rsi_val < FAKE_RSI_OVERSOLD)

        # MACD diverjans kontrolü
        _, _, histogram = calc_macd(close)
        hist_val = last_valid(histogram)
        if hist_val is None:
            return FakeLayerResult(
                "momentum", False, FAKE_WEIGHT_MOMENTUM, 0,
                "MACD hesaplanamadı",
            )

        macd_agrees = (
            (direction == "BUY" and hist_val > 0)
            or (direction == "SELL" and hist_val < 0)
        )
        macd_divergence = not macd_agrees

        # Her iki koşul birden sağlanmalı
        if rsi_extreme and macd_divergence:
            return FakeLayerResult(
                "momentum", True, FAKE_WEIGHT_MOMENTUM, FAKE_WEIGHT_MOMENTUM,
                f"RSI={rsi_val:.1f} + MACD div (hist={hist_val:.4f})",
            )

        return FakeLayerResult(
            "momentum", False, FAKE_WEIGHT_MOMENTUM, 0,
            f"RSI={rsi_val:.1f}, MACD hist={hist_val:.4f} (normal)",
        )

    # ═════════════════════════════════════════════════════════════════
    #  DURUM GERİ YÜKLEME
    # ═════════════════════════════════════════════════════════════════

    def restore_risk_state(self) -> None:
        """Engine yeniden başladığında risk durumunu DB'den geri yükle.

        Son KILL_SWITCH ve COOLDOWN event'lerini okur.
        """
        # Kill-switch
        ks_events = self._db.get_events(event_type="KILL_SWITCH", limit=1)
        if ks_events:
            last = ks_events[0]
            action = last.get("action", "LEVEL_0")
            if action.startswith("LEVEL_") and action != "LEVEL_0":
                try:
                    level = int(action.split("_")[1])
                    self._kill_switch_level = level
                    self._kill_switch_details = {
                        "reason": "restored_from_db",
                        "message": last.get("message", ""),
                        "triggered_at": last.get("timestamp", ""),
                    }
                    logger.warning(
                        f"Kill-switch durumu geri yüklendi: L{level}"
                    )
                except (ValueError, IndexError):
                    pass

        # Cooldown
        cd_events = self._db.get_events(event_type="COOLDOWN", limit=1)
        if cd_events:
            last = cd_events[0]
            if last.get("action") == "cooldown_start":
                try:
                    triggered = datetime.fromisoformat(last["timestamp"])
                    end_time = triggered + timedelta(hours=COOLDOWN_HOURS)
                    if datetime.now() < end_time:
                        self._risk_state["cooldown_until"] = end_time
                        remaining = (end_time - datetime.now()).total_seconds()
                        logger.warning(
                            f"Cooldown durumu geri yüklendi: "
                            f"{remaining/60:.0f} dk kaldı"
                        )
                except (ValueError, KeyError):
                    pass

    # ═════════════════════════════════════════════════════════════════
    #  DAHİLİ YARDIMCILAR
    # ═════════════════════════════════════════════════════════════════

    def _get_liquidity_class(self, symbol: str) -> str:
        """Sembolün likidite sınıfını DB'den oku (varsayılan "C")."""
        rows = self._db.get_liquidity(
            target_date=date.today().isoformat(), symbol=symbol
        )
        if rows and rows[0].get("class"):
            return rows[0]["class"]
        return "C"

    def _current_spread_multiple(self, symbol: str) -> float:
        """Mevcut spread / ortalama spread."""
        history = self._spread_history.get(symbol, [])
        if len(history) < 5:
            return 1.0
        current = history[-1]
        avg = float(np.mean(history[:-1]))
        return current / avg if avg > 0 else 1.0

    def _update_spread_history(self, pipeline) -> None:
        """Son tick spread'lerini ring buffer'a ekle."""
        for symbol in WATCHED_SYMBOLS:
            tick = pipeline.latest_ticks.get(symbol)
            if tick is None:
                continue
            buf = self._spread_history[symbol]
            buf.append(tick.spread)
            if len(buf) > SPREAD_HISTORY_LEN:
                self._spread_history[symbol] = buf[-SPREAD_HISTORY_LEN:]

    def _update_usdtry_history(self) -> None:
        """USD/TRY fiyat geçmişini MT5'ten güncelle."""
        if self._mt5 is None:
            return
        try:
            tick = self._mt5.get_tick("USDTRY")
        except Exception as exc:
            logger.error(f"get_tick hatası [USDTRY]: {exc}")
            return
        if tick is not None:
            self._usdtry_history.append(tick.bid)
            if len(self._usdtry_history) > SPREAD_HISTORY_LEN:
                self._usdtry_history = self._usdtry_history[-SPREAD_HISTORY_LEN:]

    def _usdtry_5m_move_pct(self) -> float:
        """USD/TRY son ~5dk hareket yüzdesi."""
        if len(self._usdtry_history) < 2:
            return 0.0
        first = self._usdtry_history[0]
        last  = self._usdtry_history[-1]
        return abs(last - first) / first * 100 if first > 0 else 0.0


# ═════════════════════════════════════════════════════════════════════
#  MODÜL-SEVİYE YARDIMCILAR
# ═════════════════════════════════════════════════════════════════════


def _volatile_reason(atr_ratio: float, spread_mult: float, move_pct: float) -> str:
    """VOLATILE nedenini oluştur."""
    parts = []
    if atr_ratio > ATR_VOLATILE_MULT:
        parts.append(f"ATR {atr_ratio:.1f}×")
    if spread_mult > SPREAD_VOLATILE_MULT:
        parts.append(f"spread {spread_mult:.1f}×")
    if move_pct > PRICE_MOVE_PCT:
        parts.append(f"hareket %{move_pct:.2f}")
    return " + ".join(parts) or "bilinmeyen"
