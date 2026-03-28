"""Top 5 kontrat seçim modülü.

v5.8/CEO-FAZ3: ogul.py'den ayrıldı (refactoring — 800+ satır).

Her 30 dakikada bir 15 VİOP kontratını 5 kritere göre puanlar:
    1. Teknik sinyal gücü (ADX, EMA, RSI, BB)
    2. Hacim kalitesi (güncel/ortalama oranı)
    3. Spread durumu (düşük spread = yüksek puan)
    4. Tarihsel başarı (son 30 gün win rate + PnL)
    5. Volatilite uyumu (ATR/fiyat oranı rejime göre)

Winsorize + min-max normalizasyon sonrası ağırlıklı toplam → Top 5.
Vade geçişi + haber/bilanço filtresi uygulanır.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from engine.config import Config
from engine.database import Database
from engine.logger import get_logger
from engine.models.regime import Regime, RegimeType
from engine.mt5_bridge import WATCHED_SYMBOLS
from engine.utils.helpers import last_valid
from engine.utils.indicators import (
    adx as calc_adx,
    atr as calc_atr,
    ema,
    bollinger_bands,
    rsi as calc_rsi,
    macd as calc_macd,
)
from engine.baba import VIOP_EXPIRY_DATES

logger = get_logger(__name__)

# ── Top 5 Zamanlama ──────────────────────────────────────────────────
from datetime import time
SELECTION_START: time      = time(9, 15)
REFRESH_INTERVAL_MIN: int  = 30

# ── Top 5 Ağırlıklar ────────────────────────────────────────────────
W_TECHNICAL:  float = 0.35
W_VOLUME:     float = 0.20
W_SPREAD:     float = 0.15
W_HISTORICAL: float = 0.20
W_VOLATILITY: float = 0.10

# ── Winsorization ─────────────────────────────────────────────────────
WINSOR_LOWER_PCT: float = 1.0
WINSOR_UPPER_PCT: float = 99.0

# ── Teknik skor parametreleri ─────────────────────────────────────────
TECH_EMA_FAST: int = 20
TECH_EMA_SLOW: int = 50
TECH_ADX_PERIOD: int = 14
TECH_RSI_PERIOD: int = 14
TECH_ATR_PERIOD: int = 14
TECH_BB_PERIOD: int = 20
TECH_BB_STD: float = 2.0
TECH_MIN_BARS: int = 60

# ── Hacim skor parametreleri ──────────────────────────────────────────
VOL_LOOKBACK: int = 20
VOL_MAX_RATIO: float = 3.0

# ── Tarihsel başarı parametreleri ─────────────────────────────────────
HIST_LOOKBACK_DAYS: int = 30

# ── Volatilite uyumu parametreleri ────────────────────────────────────
VOLFIT_TREND_IDEAL: float = 0.012
VOLFIT_RANGE_IDEAL: float = 0.005
VOLFIT_TOLERANCE: float = 0.010

# ── Vade geçişi parametreleri (GCM paraleli) ────────────────────────
# Son işlem günü (vade günü) eski vadeden yeni işlem açılmaz.
# GCM MT5 o gün yeni vade kontratını visible yapar → _resolve_symbols
# otomatik geçer. Gözlem süresi 0 = yeni vadeye anında geçiş.
EXPIRY_NO_NEW_TRADE_DAYS: int = 0   # v5.9: Vade kısıtlaması kaldırıldı (kullanıcı talimatı)
EXPIRY_CLOSE_DAYS: int = 0          # v5.9: Vade kısıtlaması kaldırıldı (kullanıcı talimatı)
EXPIRY_OBSERVATION_DAYS: int = 0

# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────
from engine.utils.time_utils import ALL_HOLIDAYS


def _business_days_until(target: date, start: date | None = None) -> int:
    """Hedef tarihe kalan iş günü sayısı."""
    if start is None:
        start = date.today()
    if target <= start:
        return 0
    count = 0
    current = start + timedelta(days=1)
    while current <= target:
        if current.weekday() < 5 and current not in ALL_HOLIDAYS:
            count += 1
        current += timedelta(days=1)
    return count


def _business_days_since(start: date, end: date | None = None) -> int:
    """Başlangıç tarihinden bu yana geçen iş günü sayısı."""
    if end is None:
        end = date.today()
    if end <= start:
        return 0
    count = 0
    current = start + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5 and current not in ALL_HOLIDAYS:
            count += 1
        current += timedelta(days=1)
    return count


# ═══════════════════════════════════════════════════════════════════════
class Top5Selector:
    """Top 5 kontrat seçici.

    Ogul sınıfından bağımsız çalışır; db ve config referanslarını alır.
    """

    def __init__(
        self,
        db: Database,
        config: Config,
        ustat_ref: Any = None,
    ) -> None:
        self._db = db
        self._config = config
        self._ustat = ustat_ref  # ÜSTAT referansı (kontrat profili için)

        # State
        self._current_top5: list[str] = []
        self._current_scores: dict[str, float] = {}
        self._last_refresh: datetime | None = None

        # Haber / bilanço filtresi
        self._earnings_calendar: dict[str, list[date]] = {}
        self._kap_blocked: set[str] = set()
        self._news_deactivated: set[str] = set()
        self._news_deactivate_date: date | None = None

    # ── Public API ─────────────────────────────────────────────────────

    def select_top5(self, regime: Regime) -> list[str]:
        """Mevcut rejime göre en iyi kontratları seç.

        Her 30 dakikada bir güncellenir, aralarda cache'ten döner.
        09:15'ten önce boş liste döndürür.
        """
        now = datetime.now()
        if now.time() < SELECTION_START:
            return self._current_top5
        if self._should_refresh(now):
            self._refresh_scores(regime, now)
        return self._current_top5

    @property
    def current_top5(self) -> list[str]:
        """Güncel Top 5 sembol listesi (salt-okunur kopya)."""
        return list(self._current_top5)

    @property
    def current_scores(self) -> dict[str, float]:
        """Son hesaplanan final skorlar (sembol → 0-100)."""
        return dict(self._current_scores)

    @property
    def last_refresh(self) -> datetime | None:
        """Son güncelleme zamanı."""
        return self._last_refresh

    # ── Haber / bilanço yönetimi ──────────────────────────────────────

    def set_earnings_dates(self, symbol: str, dates: list[date]) -> None:
        """Bilanço tarihlerini kaydet."""
        self._earnings_calendar[symbol] = sorted(dates)
        logger.info(f"Bilanço takvimi [{symbol}]: {dates}")

    def set_kap_event(self, symbol: str) -> None:
        """KAP özel durum — kontratı durdur."""
        self._kap_blocked.add(symbol)
        logger.warning(f"KAP özel durum: {symbol} durduruldu")
        self._db.insert_event(
            event_type="NEWS_FILTER",
            message=f"KAP özel durum: {symbol} durduruldu",
            severity="WARNING",
            action="kap_block",
        )

    def clear_kap_event(self, symbol: str) -> None:
        """KAP özel durum kaldır."""
        self._kap_blocked.discard(symbol)
        logger.info(f"KAP özel durum kaldırıldı: {symbol}")

    def set_manual_news_flag(self, symbol: str) -> None:
        """Manuel haber işareti — gün boyu deaktif."""
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
        """Vade kapanış emri gerekli mi?"""
        today = date.today()
        future_expiries = sorted(d for d in VIOP_EXPIRY_DATES if d >= today)
        if not future_expiries:
            return False
        bdays = _business_days_until(future_expiries[0], today)
        return bdays <= EXPIRY_CLOSE_DAYS

    # ── Zamanlama ─────────────────────────────────────────────────────

    def _should_refresh(self, now: datetime) -> bool:
        """30 dakika aralık veya günün ilk seçimi kontrolü."""
        if self._last_refresh is None:
            return True
        if self._last_refresh.date() != now.date():
            return True
        elapsed = (now - self._last_refresh).total_seconds()
        return elapsed >= REFRESH_INTERVAL_MIN * 60

    # ── Ana puanlama ──────────────────────────────────────────────────

    def _refresh_scores(self, regime: Regime, now: datetime) -> None:
        """Tüm kontratları puanla ve Top 5 seç."""
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

        # 2. Normalize
        final_scores = self._normalize_and_weight(raw_scores)

        # 2.5 ÜSTAT kontrat profili bonusu
        final_scores = self._apply_ustat_bonus(final_scores)

        # 3. Sırala
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

        # Minimum 3 kontrat garantisi
        TOP5_MINIMUM = 3
        if len(top5_above_avg) < TOP5_MINIMUM and len(top5_candidates) >= TOP5_MINIMUM:
            top5_above_avg = top5_candidates[:TOP5_MINIMUM]

        # 6. Vade + haber filtresi
        expiry_status = self._get_expiry_status(today)
        top5_final: list[str] = []
        for sym, _sc in top5_above_avg:
            status = expiry_status.get(sym, "normal")
            if status in ("observation", "no_new_trade", "close"):
                continue
            if self._is_news_blocked(sym, today):
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

    # ── Puanlama kriterleri ───────────────────────────────────────────

    def _score_technical(self, symbol: str, regime: Regime) -> float:
        """Teknik sinyal gücü puanı (ham 0-100)."""
        df = self._db.get_bars(symbol, "M15", limit=TECH_MIN_BARS)
        if df.empty or len(df) < TECH_MIN_BARS:
            return 50.0

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)

        adx_arr = calc_adx(high, low, close, TECH_ADX_PERIOD)
        rsi_arr = calc_rsi(close, TECH_RSI_PERIOD)
        ema_f = ema(close, TECH_EMA_FAST)
        ema_s = ema(close, TECH_EMA_SLOW)
        _, _, histogram = calc_macd(close)
        bb_u, _bb_m, bb_l = bollinger_bands(close, TECH_BB_PERIOD, TECH_BB_STD)

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

        # ADX uyumu (0-30)
        if is_trend:
            adx_score = min(adx_val / 50.0 * 30.0, 30.0)
        else:
            adx_score = max(0.0, 30.0 - adx_val * 0.75)

        # Trend/EMA uyumu (0-25)
        ema_gap_pct = abs(ema_fast_val - ema_slow_val) / price * 100
        if is_trend:
            ema_score = min(ema_gap_pct * 10.0, 15.0)
            macd_score = min(abs(hist_val) / price * 1000.0, 10.0)
        else:
            ema_score = max(0.0, 15.0 - ema_gap_pct * 10.0)
            macd_score = max(0.0, 10.0 - abs(hist_val) / price * 1000.0)
        trend_score = min(ema_score + macd_score, 25.0)

        # RSI (0-25)
        if is_trend:
            ema_bullish = ema_fast_val > ema_slow_val
            if (rsi_val > 55 and ema_bullish) or (rsi_val < 45 and not ema_bullish):
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

        # BB pozisyonu (0-20)
        bb_score = 10.0
        if bb_upper is not None and bb_lower is not None and bb_upper > bb_lower:
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
        """Hacim kalitesi puanı (ham 0-100)."""
        df = self._db.get_bars(symbol, "M15", limit=VOL_LOOKBACK * 4 + 4)
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
        """Spread durumu puanı (ham 0-100)."""
        rows = self._db.get_liquidity(
            target_date=date.today().isoformat(), symbol=symbol,
        )
        if rows and rows[0].get("avg_spread") is not None:
            avg_spread = rows[0]["avg_spread"]
            liq_class = rows[0].get("class", "C")
            class_bonus = {"A": 30.0, "B": 10.0, "C": 0.0}.get(liq_class, 0.0)
            spread_score = max(0.0, 70.0 - avg_spread * 2.0)
            return min(100.0, spread_score + class_bonus)

        df = self._db.get_bars(symbol, "M15", limit=20)
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
        """Tarihsel başarı puanı (ham 0-100)."""
        trades = self._db.get_trades(symbol=symbol, limit=200)
        if not trades:
            profile = self._get_contract_profile(symbol)
            if profile and profile.get("trade_count", 0) >= 5:
                wr = profile.get("win_rate", 50)
                return max(0.0, min(100.0, wr))
            return 50.0

        cutoff = (datetime.now() - timedelta(days=HIST_LOOKBACK_DAYS)).isoformat()
        regime_name = regime.regime_type.value

        recent = [
            t for t in trades
            if t.get("exit_time") and t.get("pnl") is not None
            and t["exit_time"] >= cutoff
            and (t.get("regime") == regime_name or t.get("regime") is None)
        ]

        if not recent or len(recent) < 10:
            return 30.0

        wins = sum(1 for t in recent if t["pnl"] > 0)
        total = len(recent)
        win_rate = wins / total
        avg_pnl = sum(t["pnl"] for t in recent) / total

        wr_score = max(0.0, min(60.0, (win_rate - 0.3) / 0.4 * 60.0))
        pnl_score = 20.0 + min(20.0, max(-20.0, avg_pnl * 2.0))
        base_score = wr_score + pnl_score

        profile = self._get_contract_profile(symbol)
        if profile and profile.get("trade_count", 0) >= 5:
            ustat_wr = profile.get("win_rate", 50)
            if ustat_wr < 30:
                base_score -= 15
            elif ustat_wr > 60:
                base_score += 10
            total_pnl = profile.get("total_pnl", 0)
            if total_pnl < -500:
                base_score -= 10

        return max(0.0, min(100.0, base_score))

    def _score_volatility_fit(self, symbol: str, regime: Regime) -> float:
        """Volatilite uyumu puanı (ham 0-100)."""
        df = self._db.get_bars(symbol, "M15", limit=TECH_MIN_BARS)
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
        else:
            ideal = VOLFIT_RANGE_IDEAL

        diff = abs(atr_ratio - ideal)
        score = 100.0 * float(np.exp(-(diff / VOLFIT_TOLERANCE) ** 2))
        return max(0.0, min(100.0, score))

    # ── ÜSTAT Kontrat Profili Bonusu ──────────────────────────────────

    def _apply_ustat_bonus(self, final_scores: dict[str, float]) -> dict[str, float]:
        """ÜSTAT kontrat profillerinden bonus/ceza uygula.

        Win-rate ve ortalama PnL bazında skor ayarlaması:
          - win_rate > %65 ve trade_count >= 10 → +15 puan
          - win_rate > %55 ve trade_count >= 10 → +8 puan
          - win_rate < %35 ve trade_count >= 10 → -12 puan
          - avg_pnl > 0 ve trade_count >= 10 → +5 puan
          - avg_pnl < -50 ve trade_count >= 10 → -8 puan
          - trade_count < 10 → bonus yok (yetersiz veri)

        Returns:
            Güncellenmiş final_scores.
        """
        if self._ustat is None:
            return final_scores

        try:
            profiles = self._ustat.get_contract_profiles()
        except Exception:
            return final_scores

        if not profiles:
            return final_scores

        adjusted = dict(final_scores)
        for symbol, score in final_scores.items():
            profile = profiles.get(symbol)
            if profile is None:
                continue

            trade_count = profile.get("trade_count", 0)
            if trade_count < 10:
                continue  # Yetersiz veri — bonus/ceza yok

            bonus = 0.0
            win_rate = profile.get("win_rate", 50.0)
            avg_pnl = profile.get("avg_pnl", 0.0)

            # Win-rate bonusu/cezası
            if win_rate > 65.0:
                bonus += 15.0
            elif win_rate > 55.0:
                bonus += 8.0
            elif win_rate < 35.0:
                bonus -= 12.0

            # PnL bonusu/cezası
            if avg_pnl > 0:
                bonus += 5.0
            elif avg_pnl < -50.0:
                bonus -= 8.0

            if bonus != 0.0:
                adjusted[symbol] = score + bonus
                logger.debug(
                    f"ÜSTAT bonus [{symbol}]: {bonus:+.1f} "
                    f"(wr={win_rate:.1f}%, pnl={avg_pnl:.1f}, n={trade_count})"
                )

        return adjusted

    # ── Normalizasyon ─────────────────────────────────────────────────

    def _normalize_and_weight(
        self, raw_scores: dict[str, dict[str, float]],
    ) -> dict[str, float]:
        """Ham puanları winsorize + min-max normalize et, ağırlıklı topla."""
        criteria = ["technical", "volume", "spread", "historical", "volatility"]
        weights = {
            "technical": W_TECHNICAL, "volume": W_VOLUME,
            "spread": W_SPREAD, "historical": W_HISTORICAL,
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

    # ── Vade geçişi ───────────────────────────────────────────────────

    def _get_expiry_status(self, today: date) -> dict[str, str]:
        """Her sembol için vade geçiş durumunu belirle."""
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
                bdays_since = _business_days_since(last_expiry, today)
                if 0 < bdays_since <= EXPIRY_OBSERVATION_DAYS:
                    status[symbol] = "observation"
                    continue

            if bdays_to_expiry <= EXPIRY_CLOSE_DAYS:
                status[symbol] = "close"
            elif bdays_to_expiry <= EXPIRY_NO_NEW_TRADE_DAYS:
                status[symbol] = "no_new_trade"
            else:
                status[symbol] = "normal"

        return status

    # ── Haber / bilanço filtresi ──────────────────────────────────────

    def _is_news_blocked(self, symbol: str, today: date) -> bool:
        """Haber/bilanço engeli kontrolü."""
        if symbol in self._kap_blocked:
            return True
        if self._news_deactivate_date == today and symbol in self._news_deactivated:
            return True
        if symbol in self._earnings_calendar:
            for earn_date in self._earnings_calendar[symbol]:
                diff = abs((today - earn_date).days)
                if diff <= 1:
                    return True
        return False

    # ── DB kayıt ──────────────────────────────────────────────────────

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
        self._db.insert_top5(entries)

    # ── ÜSTAT entegrasyonu ────────────────────────────────────────────

    def _get_contract_profile(self, symbol: str) -> dict | None:
        """ÜSTAT kontrat davranış profilini getir."""
        if self._ustat is None:
            return None
        try:
            return self._ustat.get_contract_profile(symbol)
        except Exception:
            return None
