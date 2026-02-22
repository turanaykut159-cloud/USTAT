"""ÜSTAT — Top 5 kontrat seçimi ve strateji yönetimi (v12.0).

Günlük Top 5 seçim süreci:
    09:15'te başla, 30 dakikada bir güncelle.
    15 kontratı 5 kritere göre 0-100 arası puanla.

Puanlama kriterleri (ağırlık):
    Teknik sinyal gücü     %35  (EMA, ADX, RSI, MACD, BB uyumu)
    Hacim kalitesi          %20  (güncel hacim / 20-günlük ortalama)
    Spread durumu           %15  (düşük spread = yüksek skor)
    Tarihsel başarı         %20  (son 30 gün, kontrat + rejim)
    Volatilite uyumu        %10  (ATR/fiyat oranının rejime uygunluğu)

Normalizasyon:
    Winsorization (1. ve 99. percentile) + Min-Max 0-100.

Filtreler:
    Ortalama filtresi — Top 5 ortalamasının altındakiler elenir.
    Vade geçişi       — 3 gün kala yeni işlem yok, 1 gün kala kapat,
                        yeni vadede 2 gün gözlem.
    Haber/bilanço     — TCMB/FED → OLAY, bilanço ±1 → engel,
                        KAP → durdur, manuel → gün boyu deaktif.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np

from engine.config import Config
from engine.database import Database
from engine.logger import get_logger
from engine.models.regime import Regime, RegimeType
from engine.mt5_bridge import WATCHED_SYMBOLS
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

# ── Zamanlama ────────────────────────────────────────────────────────
SELECTION_START: time = time(9, 15)       # ilk seçim saati
REFRESH_INTERVAL_MIN: int = 30            # güncelleme aralığı (dk)

# ── Ağırlıklar ──────────────────────────────────────────────────────
W_TECHNICAL:  float = 0.35    # teknik sinyal gücü
W_VOLUME:     float = 0.20    # hacim kalitesi
W_SPREAD:     float = 0.15    # spread durumu
W_HISTORICAL: float = 0.20    # tarihsel başarı
W_VOLATILITY: float = 0.10    # volatilite uyumu

# ── Winsorization ───────────────────────────────────────────────────
WINSOR_LOWER_PCT: float = 1.0    # 1. percentile
WINSOR_UPPER_PCT: float = 99.0   # 99. percentile

# ── Teknik skor ─────────────────────────────────────────────────────
TECH_EMA_FAST: int = 20
TECH_EMA_SLOW: int = 50
TECH_ADX_PERIOD: int = 14
TECH_RSI_PERIOD: int = 14
TECH_ATR_PERIOD: int = 14
TECH_BB_PERIOD: int = 20
TECH_BB_STD: float = 2.0
TECH_MIN_BARS: int = 60         # M15 minimum bar sayısı

# ── Hacim skor ──────────────────────────────────────────────────────
VOL_LOOKBACK: int = 20          # 20-bar ortalama
VOL_MAX_RATIO: float = 3.0     # oran >= 3 → 100 puan

# ── Tarihsel başarı ─────────────────────────────────────────────────
HIST_LOOKBACK_DAYS: int = 30    # son 30 gün

# ── Volatilite uyumu ────────────────────────────────────────────────
VOLFIT_TREND_IDEAL: float = 0.012   # TREND rejimde ideal ATR/fiyat oranı
VOLFIT_RANGE_IDEAL: float = 0.005   # RANGE rejimde ideal ATR/fiyat oranı
VOLFIT_TOLERANCE: float = 0.010     # tolerans genişliği

# ── Vade geçişi ─────────────────────────────────────────────────────
EXPIRY_NO_NEW_TRADE_DAYS: int = 3   # vade bitişinden 3 iş günü öncesi
EXPIRY_CLOSE_DAYS: int = 1          # vade bitişinden 1 iş günü öncesi
EXPIRY_OBSERVATION_DAYS: int = 2    # yeni vadede ilk 2 gün gözlem

# ── Takvim verileri (baba.py'den) ───────────────────────────────────
from engine.baba import VIOP_EXPIRY_DATES, CENTRAL_BANK_DATES  # noqa: E402

# ── Tatil günleri (time_utils'den + 2026) ───────────────────────────
from engine.utils.time_utils import HOLIDAYS_2025  # noqa: E402

ALL_HOLIDAYS: set[date] = set(HOLIDAYS_2025) | {
    date(2026, 1, 1),    # Yılbaşı
    date(2026, 4, 23),   # Ulusal Egemenlik ve Çocuk Bayramı
    date(2026, 5, 1),    # İşçi Bayramı
    date(2026, 5, 19),   # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    date(2026, 7, 15),   # Demokrasi ve Milli Birlik Günü
    date(2026, 8, 30),   # Zafer Bayramı
    date(2026, 10, 29),  # Cumhuriyet Bayramı
}


# ═════════════════════════════════════════════════════════════════════
#  YARDIMCI FONKSİYONLAR
# ═════════════════════════════════════════════════════════════════════

def _last_valid(arr: np.ndarray) -> float | None:
    """Dizinin son NaN-olmayan değeri."""
    for i in range(len(arr) - 1, -1, -1):
        if not np.isnan(arr[i]):
            return float(arr[i])
    return None


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


# ═════════════════════════════════════════════════════════════════════
#  ÜSTAT
# ═════════════════════════════════════════════════════════════════════

class Ustat:
    """Strateji yöneticisi — Top 5 kontrat seçimi, puanlama,
    vade geçişi ve haber/bilanço filtresi.

    Her 10 saniyelik ana döngüde ``select_top5(regime)`` çağrılır.
    Gerçek skorlama 30 dakikada bir yapılır, aralarda cache döner.
    """

    def __init__(self, config: Config, db: Database) -> None:
        self._config = config
        self._db = db

        # ── Seçim durumu ──────────────────────────────────────────
        self._current_top5: list[str] = []
        self._current_scores: dict[str, float] = {}
        self._last_refresh: datetime | None = None

        # ── Haber / bilanço filtresi ──────────────────────────────
        self._earnings_calendar: dict[str, list[date]] = {}
        self._kap_blocked: set[str] = set()
        self._news_deactivated: set[str] = set()
        self._news_deactivate_date: date | None = None

    # ═════════════════════════════════════════════════════════════════
    #  PUBLIC API
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

        Bilanço günü ±1 gün o kontratta işlem engellenir.

        Args:
            symbol: Kontrat sembolü.
            dates: Bilanço açıklama tarihleri listesi.
        """
        self._earnings_calendar[symbol] = sorted(dates)
        logger.info(f"Bilanço takvimi [{symbol}]: {dates}")

    def set_kap_event(self, symbol: str) -> None:
        """KAP özel durum — kontratı durdur.

        ``clear_kap_event()`` ile kaldırılana kadar aktif kalır.

        Args:
            symbol: Durdurulacak kontrat.
        """
        self._kap_blocked.add(symbol)
        logger.warning(f"KAP özel durum: {symbol} durduruldu")
        self._db.insert_event(
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

        Ertesi gün otomatik sıfırlanır.

        Args:
            symbol: Deaktif edilecek kontrat.
        """
        self._news_deactivated.add(symbol)
        self._news_deactivate_date = date.today()
        logger.warning(f"Manuel haber deaktif: {symbol} (gün boyu)")
        self._db.insert_event(
            event_type="NEWS_FILTER",
            message=f"Manuel haber deaktif: {symbol}",
            severity="WARNING",
            action="manual_news",
        )

    def get_expiry_close_needed(self) -> bool:
        """Vade kapanış emri gerekli mi?

        Oğul tarafından çağrılır: 1 iş günü kala tüm pozisyonlar
        kapatılmalıdır.

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
    #  ZAMANLAMA
    # ═════════════════════════════════════════════════════════════════

    def _should_refresh(self, now: datetime) -> bool:
        """30 dakika aralık veya günün ilk seçimi kontrolü.

        Args:
            now: Şu anki zaman.

        Returns:
            True ise güncelleme gerekli.
        """
        if self._last_refresh is None:
            return True
        if self._last_refresh.date() != now.date():
            return True
        elapsed = (now - self._last_refresh).total_seconds()
        return elapsed >= REFRESH_INTERVAL_MIN * 60

    # ═════════════════════════════════════════════════════════════════
    #  ANA PUANLAMA
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

        Args:
            regime: Mevcut piyasa rejimi.
            now: Şu anki zaman.
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
    #  PUANLAMA KRİTERLERİ
    # ═════════════════════════════════════════════════════════════════

    def _score_technical(self, symbol: str, regime: Regime) -> float:
        """Teknik sinyal gücü puanı (ham 0-100).

        Alt bileşenler:
            ADX uyumu     (0-30): Rejime göre ADX değerlendirmesi
            Trend/EMA     (0-25): EMA mesafesi + MACD momentum
            RSI           (0-25): Aşırı bölge ve yön uyumu
            BB pozisyonu  (0-20): Fiyatın bantlara göre konumu

        Args:
            symbol: Kontrat sembolü.
            regime: Mevcut piyasa rejimi.

        Returns:
            Ham puan (0-100).
        """
        df = self._db.get_bars(symbol, "M15", limit=TECH_MIN_BARS)
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

        adx_val = _last_valid(adx_arr)
        rsi_val = _last_valid(rsi_arr)
        hist_val = _last_valid(histogram)
        ema_fast_val = _last_valid(ema_f)
        ema_slow_val = _last_valid(ema_s)
        bb_upper = _last_valid(bb_u)
        bb_lower = _last_valid(bb_l)

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
            # Yüksek ADX = güçlü trend → iyi
            adx_score = min(adx_val / 50.0 * 30.0, 30.0)
        else:
            # Düşük ADX = range → iyi
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
            # RSI yönle uyumlu → iyi
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
            # Aşırı bölge = mean reversion fırsatı → iyi
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
                # Bant kenarı = trend devam → iyi
                bb_score = 20.0 if (bb_pos > 0.7 or bb_pos < 0.3) else 10.0
            else:
                # Bant ucu = reversal fırsatı
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

        Args:
            symbol: Kontrat sembolü.

        Returns:
            Ham puan (0-100).
        """
        df = self._db.get_bars(symbol, "M15", limit=VOL_LOOKBACK * 4 + 4)
        if df.empty or len(df) < VOL_LOOKBACK + 1:
            return 50.0

        vol = df["volume"].values.astype(np.float64)

        # Son 4 bar (~1 saat M15) ortalaması → güncel hacim
        recent_count = min(4, len(vol))
        current_vol = float(np.mean(vol[-recent_count:]))

        # Geçmiş barlar ortalaması
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
        Likidite sınıfı DB'den okunur, yoksa bar verisinden proxy.

        Args:
            symbol: Kontrat sembolü.

        Returns:
            Ham puan (0-100).
        """
        # Likidite sınıfı verisini dene
        rows = self._db.get_liquidity(
            target_date=date.today().isoformat(), symbol=symbol,
        )
        if rows and rows[0].get("avg_spread") is not None:
            avg_spread = rows[0]["avg_spread"]
            liq_class = rows[0].get("class", "C")

            # Sınıf bonusu
            class_bonus = {"A": 30.0, "B": 10.0, "C": 0.0}.get(
                liq_class, 0.0,
            )

            # Düşük spread → yüksek puan
            # avg_spread tipik aralık: 1-50 (MT5 spread birimi)
            spread_score = max(0.0, 70.0 - avg_spread * 2.0)
            return min(100.0, spread_score + class_bonus)

        # Veri yoksa → bar verisinden (H-L)/C proxy
        df = self._db.get_bars(symbol, "M15", limit=20)
        if df.empty or len(df) < 5:
            return 50.0

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)

        # Range/close oranı = spread proxy
        safe_close = np.where(close > 0, close, 1.0)
        range_pct = (high - low) / safe_close

        current = range_pct[-1]
        avg = float(np.mean(range_pct[:-1]))

        if avg <= 0:
            return 50.0

        ratio = current / avg
        # ratio 0.5 → 100, ratio 3.0 → 0
        score = (3.0 - ratio) / 2.5 * 100.0
        return max(0.0, min(100.0, score))

    def _score_historical(self, symbol: str, regime: Regime) -> float:
        """Tarihsel başarı puanı (ham 0-100).

        Son 30 gün bu kontrat + rejimde win rate ve ortalama PnL.

        Args:
            symbol: Kontrat sembolü.
            regime: Mevcut piyasa rejimi.

        Returns:
            Ham puan (0-100).
        """
        trades = self._db.get_trades(symbol=symbol, limit=200)
        if not trades:
            return 50.0

        # Son 30 gün + rejim filtresi
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

        if not recent or len(recent) < 3:
            return 50.0

        wins = sum(1 for t in recent if t["pnl"] > 0)
        total = len(recent)
        win_rate = wins / total

        avg_pnl = sum(t["pnl"] for t in recent) / total

        # Win rate skoru (0-60): %30 → 0, %50 → 30, %70+ → 60
        wr_score = max(0.0, min(60.0, (win_rate - 0.3) / 0.4 * 60.0))

        # PnL skoru (0-40): güçlü pozitif PnL → 40, negatif → 0
        pnl_score = 20.0 + min(20.0, max(-20.0, avg_pnl * 2.0))

        return max(0.0, min(100.0, wr_score + pnl_score))

    def _score_volatility_fit(self, symbol: str, regime: Regime) -> float:
        """Volatilite uyumu puanı (ham 0-100).

        ATR(14) / fiyat oranının rejime uygunluğu.
        Gaussian benzeri skor: ideale yakın → yüksek.

        Args:
            symbol: Kontrat sembolü.
            regime: Mevcut piyasa rejimi.

        Returns:
            Ham puan (0-100).
        """
        df = self._db.get_bars(symbol, "M15", limit=TECH_MIN_BARS)
        if df.empty or len(df) < 30:
            return 50.0

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)

        atr_arr = calc_atr(high, low, close, TECH_ATR_PERIOD)
        atr_val = _last_valid(atr_arr)
        price = close[-1]

        if atr_val is None or price <= 0:
            return 50.0

        atr_ratio = atr_val / price

        # Rejime göre ideal ATR/fiyat oranı
        if regime.regime_type == RegimeType.TREND:
            ideal = VOLFIT_TREND_IDEAL
        elif regime.regime_type == RegimeType.RANGE:
            ideal = VOLFIT_RANGE_IDEAL
        else:
            # VOLATILE / OLAY → düşük volatilite tercih
            ideal = VOLFIT_RANGE_IDEAL

        # Gaussian benzeri skor: ideale yakın → yüksek
        diff = abs(atr_ratio - ideal)
        score = 100.0 * float(np.exp(-(diff / VOLFIT_TOLERANCE) ** 2))

        return max(0.0, min(100.0, score))

    # ═════════════════════════════════════════════════════════════════
    #  NORMALİZASYON
    # ═════════════════════════════════════════════════════════════════

    def _normalize_and_weight(
        self,
        raw_scores: dict[str, dict[str, float]],
    ) -> dict[str, float]:
        """Ham puanları winsorize + min-max normalize et, ağırlıklı topla.

        Her kriter için:
            1. 15 sembolün ham puanlarını winsorize et
            2. Min-max normalize et (0-100)
            3. Ağırlıkla çarp

        Tüm kriterlerin toplamı = final skor (0-100).

        Args:
            raw_scores: {sembol: {kriter: ham_puan}} sözlüğü.

        Returns:
            {sembol: final_skor} sözlüğü (0-100).
        """
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

        # Her kriter için winsorize + min-max
        normalized: dict[str, dict[str, float]] = {s: {} for s in symbols}

        for crit in criteria:
            values = [raw_scores[s][crit] for s in symbols]

            # Winsorize
            win_values = self._winsorize(values)

            # Min-max normalize
            v_min = min(win_values)
            v_max = max(win_values)
            for i, sym in enumerate(symbols):
                if v_max > v_min:
                    norm = (win_values[i] - v_min) / (v_max - v_min) * 100.0
                else:
                    norm = 50.0  # tüm değerler aynı
                normalized[sym][crit] = norm

        # Ağırlıklı toplam
        final: dict[str, float] = {}
        for sym in symbols:
            score = sum(
                normalized[sym][crit] * weights[crit] for crit in criteria
            )
            final[sym] = round(score, 2)

        return final

    @staticmethod
    def _winsorize(values: list[float]) -> list[float]:
        """Winsorization: 1. ve 99. percentile'a kırp.

        Aşırı uç değerleri sınırlayarak normalizasyonun
        dengeli kalmasını sağlar.

        Args:
            values: Ham değerler listesi.

        Returns:
            Kırpılmış değerler listesi.
        """
        if len(values) < 3:
            return list(values)

        arr = np.array(values, dtype=np.float64)
        lower = float(np.percentile(arr, WINSOR_LOWER_PCT))
        upper = float(np.percentile(arr, WINSOR_UPPER_PCT))
        return [max(lower, min(upper, v)) for v in values]

    # ═════════════════════════════════════════════════════════════════
    #  VADE GEÇİŞİ
    # ═════════════════════════════════════════════════════════════════

    def _get_expiry_status(self, today: date) -> dict[str, str]:
        """Her sembol için vade geçiş durumunu belirle.

        Durumlar:
            ``"normal"``       — işlem yapılabilir
            ``"no_new_trade"`` — 3 iş günü kala, yeni işlem yok
            ``"close"``        — 1 iş günü kala, pozisyonları kapat
            ``"observation"``  — yeni vade, ilk 2 gün sadece gözlem

        Args:
            today: Bugünün tarihi.

        Returns:
            {sembol: durum} sözlüğü.
        """
        status: dict[str, str] = {}

        # En yakın gelecek vade
        future_expiries = sorted(d for d in VIOP_EXPIRY_DATES if d >= today)
        if not future_expiries:
            return {s: "normal" for s in WATCHED_SYMBOLS}

        next_expiry = future_expiries[0]
        bdays_to_expiry = _business_days_until(next_expiry, today)

        # Son tamamlanan vade
        past_expiries = sorted(
            (d for d in VIOP_EXPIRY_DATES if d < today), reverse=True,
        )
        last_expiry = past_expiries[0] if past_expiries else None

        for symbol in WATCHED_SYMBOLS:
            # Yeni vade gözlem periyodu (ilk 2 iş günü)
            if last_expiry:
                bdays_since_expiry = _business_days_since(
                    last_expiry, today,
                )
                if 0 < bdays_since_expiry <= EXPIRY_OBSERVATION_DAYS:
                    status[symbol] = "observation"
                    continue

            # Vade yaklaşıyor
            if bdays_to_expiry <= EXPIRY_CLOSE_DAYS:
                status[symbol] = "close"
            elif bdays_to_expiry <= EXPIRY_NO_NEW_TRADE_DAYS:
                status[symbol] = "no_new_trade"
            else:
                status[symbol] = "normal"

        return status

    # ═════════════════════════════════════════════════════════════════
    #  HABER / BİLANÇO FİLTRESİ
    # ═════════════════════════════════════════════════════════════════

    def _is_news_blocked(self, symbol: str, today: date) -> bool:
        """Haber/bilanço engeli kontrolü.

        Kontroller (sırasıyla):
            1. KAP özel durum → engel
            2. Manuel haber işareti (günlük) → engel
            3. Bilanço günü ±1 → engel

        TCMB/FED günleri baba.py tarafından OLAY rejimi olarak
        zaten işlenir, burada ek kontrol gerekmez.

        Args:
            symbol: Kontrat sembolü.
            today: Bugünün tarihi.

        Returns:
            True ise bu sembolde işlem yapılmamalı.
        """
        # 1. KAP özel durum
        if symbol in self._kap_blocked:
            return True

        # 2. Manuel haber deaktif (günlük)
        if (
            self._news_deactivate_date == today
            and symbol in self._news_deactivated
        ):
            return True

        # 3. Bilanço ±1 gün
        if symbol in self._earnings_calendar:
            for earn_date in self._earnings_calendar[symbol]:
                diff = abs((today - earn_date).days)
                if diff <= 1:
                    return True

        return False

    # ═════════════════════════════════════════════════════════════════
    #  DB KAYIT
    # ═════════════════════════════════════════════════════════════════

    def _log_top5(self, now: datetime, regime: Regime) -> None:
        """Top 5 seçimini DB'ye kaydet.

        ``top5_history`` tablosuna her güncelleme için kayıt atar.

        Args:
            now: Güncelleme zamanı.
            regime: Mevcut rejim.
        """
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

        self._db.insert_top5(entries)
