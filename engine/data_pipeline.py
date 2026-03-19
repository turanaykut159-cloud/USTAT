"""Veri çekme, temizleme ve depolama pipeline'ı.

MT5'ten OHLCV / tick verisi çeker, temizler, indikatörleri hesaplar,
veritabanına yazar ve periyodik risk snapshot'ı kaydeder.

Frekanslar:
    OHLCV        : M1, M5, M15, H1 — her kontrat için
    Tick/spread  : Her 10 saniye (ana döngü cycle'ı)
    Risk snapshot: Her 10 saniye (ana döngü cycle'ı)

Temizleme kuralları:
    - Gap: Bar-arası zaman boşluklarını tespit et ve logla
    - Outlier: z-score > 5 olan barları reddet
    - Eksik veri: 3+ ardışık eksik bar → kontratı deaktif et
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from engine.config import Config
from engine.database import Database
from engine.logger import get_logger
from engine.mt5_bridge import MT5Bridge, WATCHED_SYMBOLS, Tick
from engine.utils.indicators import calculate_indicators

logger = get_logger(__name__)

# ── Paralel çekme ayarları ─────────────────────────────────────────
MAX_WORKERS: int = 4          # MT5 thread-safe değil ama GIL altında 4 iş parçacığı güvenli
CYCLE_TIMEOUT_SEC: float = 8.0  # run_cycle maksimum süresi (spike koruması)

# ── MT5 timeframe → etiket eşlemesi ─────────────────────────────────
TIMEFRAMES: dict[str, int] = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1":  mt5.TIMEFRAME_H1,
}

# Her timeframe için çekilecek bar sayısı
BAR_COUNTS: dict[str, int] = {
    "M1":  500,
    "M5":  300,
    "M15": 200,
    "H1":  100,
}

# Beklenen bar aralıkları (saniye) — gap tespiti için
EXPECTED_INTERVALS: dict[str, int] = {
    "M1":  60,
    "M5":  300,
    "M15": 900,
    "H1":  3600,
}

# Temizleme sabitleri
ZSCORE_THRESHOLD: float = 5.0
MAX_CONSECUTIVE_MISSING: int = 3

# Deaktivasyon kontrolü sadece bu timeframe'lerde çalışır.
# M1/M5 çok granüler — VİOP'ta gün içi likidite boşlukları (4+ dk)
# normal olmasına rağmen 3+ missing bar eşiğini aşıp sahte deaktivasyon tetikler.
DEACTIVATION_TIMEFRAMES: frozenset[str] = frozenset({"M15", "H1"})


# ── Yardımcı veri sınıfı ────────────────────────────────────────────
@dataclass
class TickSnapshot:
    """Tek sembol için anlık tick bilgisi."""
    symbol: str
    bid: float
    ask: float
    spread: float
    timestamp: str


# ═════════════════════════════════════════════════════════════════════
class DataPipeline:
    """Veri pipeline'ı — çekme, temizleme, depolama.

    Her 10 saniyelik engine cycle'ında ``run_cycle()`` çağrılır.
    Tick ve risk snapshot her cycle'da çalışır; OHLCV güncelleme
    timeframe bazlı dakika kontrolü ile tetiklenir.
    """

    def __init__(self, mt5_bridge: MT5Bridge, db: Database, config: Config) -> None:
        self._mt5 = mt5_bridge
        self._db = db
        self._config = config

        # Deaktif edilen semboller (3+ ardışık eksik)
        self._deactivated: set[str] = set()

        # Son OHLCV çekme zamanları — gereksiz tekrar çekmeyi önler
        self._last_bar_fetch: dict[str, datetime] = {}

        # Son tick verileri (pipeline dışından okunabilir)
        self.latest_ticks: dict[str, TickSnapshot] = {}

        # MT5 cache — WebSocket buradan okur, MT5'e doğrudan gitmez (Madde 2.4)
        self.latest_account: Any | None = None   # AccountInfo nesnesi
        self.latest_positions: list[dict] = []   # Pozisyon dict listesi
        self._cache_time: datetime | None = None  # Son cache güncelleme zamanı

        # DATA_GAP spam throttle: sembol başına son event zamanı
        # Aynı sembol/timeframe için 5 dakikada en fazla 1 DB event yazılır
        self._last_gap_event: dict[str, datetime] = {}
        _GAP_EVENT_COOLDOWN_SEC: float = 300.0  # 5 dakika

        # Peak equity baseline doğrulaması
        self._validate_peak_equity()

    def is_cache_stale(self, max_age_seconds: float = 15.0) -> bool:
        """Cache'in yaşını kontrol et.

        Args:
            max_age_seconds: Kabul edilebilir maksimum yaş (saniye).

        Returns:
            True → cache eski veya yok, False → taze.
        """
        if self._cache_time is None:
            return True
        age = (datetime.now() - self._cache_time).total_seconds()
        return age > max_age_seconds

    # ── public: ana cycle ────────────────────────────────────────────
    def run_cycle(self) -> None:
        """10 saniyelik ana döngüden çağrılır.

        Sırasıyla:
            1. Tüm semboller için tick/spread verisi çek  (paralel)
            2. OHLCV barlarını güncelle (M1, M5, M15, H1) (paralel)
            3. Risk snapshot kaydet

        Spike koruması: toplam süre CYCLE_TIMEOUT_SEC'i aşarsa
        kalan görevler iptal edilir ve loglanır.
        """
        t_start = datetime.now()

        self.fetch_all_ticks_parallel()
        self.fetch_all_symbols_parallel()

        # Spike kontrolü — OHLCV uzadıysa logla ama risk snapshot HER ZAMAN çalışsın
        elapsed = (datetime.now() - t_start).total_seconds()
        if elapsed > CYCLE_TIMEOUT_SEC:
            logger.warning(
                f"Cycle timeout: {elapsed:.1f}s > {CYCLE_TIMEOUT_SEC}s — "
                f"OHLCV yavaş ama risk snapshot yine de çalışacak"
            )

        # Risk snapshot her zaman güncellenir (BABA stale cache'den korunur)
        self.update_risk_snapshot()

        total = (datetime.now() - t_start).total_seconds()
        if total > 3.0:
            logger.info(f"run_cycle yavaş: {total:.1f}s")

    # ═════════════════════════════════════════════════════════════════
    #  OHLCV
    # ═════════════════════════════════════════════════════════════════
    def fetch_bars(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Tek sembol + tek timeframe için bar verisi çek → temizle → DB'ye yaz.

        Args:
            symbol: Kontrat sembolü (ör. "F_THYAO").
            timeframe: Zaman dilimi etiketi ("M1", "M5", "M15", "H1").

        Returns:
            Temizlenmiş ve indikatörleri eklenmiş DataFrame.
            Hata/boş durumda boş DataFrame.
        """
        mt5_tf = TIMEFRAMES.get(timeframe)
        if mt5_tf is None:
            logger.error(f"Geçersiz timeframe: {timeframe}")
            return pd.DataFrame()

        count = BAR_COUNTS.get(timeframe, 500)

        try:
            df = self._mt5.get_bars(symbol, mt5_tf, count)
            if df.empty:
                logger.warning(f"Boş bar verisi [{symbol}/{timeframe}]")
                return pd.DataFrame()

            # Temizle
            df, is_healthy = self.clean_data(df, symbol, timeframe)
            if df.empty:
                return pd.DataFrame()

            # Sağlıksız kontratı deaktif et
            if not is_healthy:
                return df

            # İndikatörler
            if len(df) >= 30:
                df = calculate_indicators(df)

            # DB'ye yaz
            self._db.insert_bars(symbol, timeframe, df)

            logger.debug(
                f"Bars OK [{symbol}/{timeframe}]: {len(df)} bar"
            )
            return df

        except Exception as exc:
            logger.error(f"fetch_bars istisnası [{symbol}/{timeframe}]: {exc}")
            return pd.DataFrame()

    def fetch_all_symbols(self) -> dict[str, dict[str, int]]:
        """15 kontratın tümü için tüm timeframe'lerde veri çek (sıralı — eski).

        Returns:
            {symbol: {timeframe: bar_sayısı}} istatistik sözlüğü.
        """
        stats: dict[str, dict[str, int]] = {}

        for symbol in WATCHED_SYMBOLS:
            if symbol in self._deactivated:
                continue

            stats[symbol] = {}
            for tf_label in TIMEFRAMES:
                df = self.fetch_bars(symbol, tf_label)
                stats[symbol][tf_label] = len(df)

        active = len(WATCHED_SYMBOLS) - len(self._deactivated)
        logger.info(
            f"OHLCV güncelleme tamamlandı: "
            f"{active} aktif / {len(self._deactivated)} deaktif kontrat"
        )
        return stats

    def fetch_all_symbols_parallel(self) -> dict[str, dict[str, int]]:
        """15 kontratın tümü için tüm timeframe'lerde veri çek (paralel).

        Semboller ThreadPoolExecutor ile paralel çekilir.
        Her sembol içinde timeframe'ler sıralı kalır (DB yazma güvenliği).

        Returns:
            {symbol: {timeframe: bar_sayısı}} istatistik sözlüğü.
        """
        active_symbols = [s for s in WATCHED_SYMBOLS if s not in self._deactivated]

        if not active_symbols:
            return {}

        stats: dict[str, dict[str, int]] = {}

        def _fetch_symbol(symbol: str) -> tuple[str, dict[str, int]]:
            """Tek sembol için tüm timeframe'leri çek."""
            sym_stats: dict[str, int] = {}
            for tf_label in TIMEFRAMES:
                df = self.fetch_bars(symbol, tf_label)
                sym_stats[tf_label] = len(df)
            return symbol, sym_stats

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_symbol, sym): sym
                for sym in active_symbols
            }
            for future in as_completed(futures, timeout=CYCLE_TIMEOUT_SEC):
                try:
                    sym, sym_stats = future.result(timeout=2.0)
                    stats[sym] = sym_stats
                except Exception as exc:
                    sym = futures[future]
                    logger.error(f"Paralel OHLCV hatası [{sym}]: {exc}")

        active = len(active_symbols)
        fetched = len(stats)
        logger.info(
            f"OHLCV paralel güncelleme: "
            f"{fetched}/{active} sembol tamamlandı"
        )
        return stats

    # ═════════════════════════════════════════════════════════════════
    #  TEMİZLEME
    # ═════════════════════════════════════════════════════════════════
    def clean_data(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> tuple[pd.DataFrame, bool]:
        """Ham bar verisini temizle.

        Adımlar:
            1. Temel temizlik (NA, duplikat)
            2. Gap tespiti ve loglama
            3. Outlier filtreleme (z-score > 5)
            4. Ardışık eksik bar kontrolü (3+ → deaktif)

        Args:
            df: Ham OHLCV DataFrame (``time`` sütunu datetime).
            symbol: Kontrat sembolü.
            timeframe: Zaman dilimi etiketi.

        Returns:
            (temizlenmiş_df, is_healthy) tuple'ı.
            is_healthy=False ise kontrat deaktif edilmiştir.
        """
        original_len = len(df)

        # ── 1. Temel temizlik ────────────────────────────────────────
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.drop_duplicates(subset=["time"])
        df = df.sort_values("time").reset_index(drop=True)

        if df.empty:
            logger.warning(f"Temizlik sonrası veri kalmadı [{symbol}/{timeframe}]")
            return df, True

        # ── 2. Gap tespiti ───────────────────────────────────────────
        gap_count = self._detect_gaps(df, symbol, timeframe)

        # ── 3. Outlier filtreleme (z-score > 5) ─────────────────────
        df = self._filter_outliers(df, symbol, timeframe)

        # ── 4. Ardışık eksik bar kontrolü ────────────────────────────
        # M1/M5 atlanır: VİOP'ta gün içi likidite boşlukları normal
        if timeframe in DEACTIVATION_TIMEFRAMES:
            is_healthy = self._check_consecutive_missing(
                df, symbol, timeframe, original_len
            )
        else:
            is_healthy = True

        cleaned = original_len - len(df)
        if cleaned > 0:
            logger.info(
                f"Temizleme [{symbol}/{timeframe}]: "
                f"{original_len}→{len(df)} bar ({cleaned} silindi, "
                f"{gap_count} gap)"
            )

        return df, is_healthy

    def _detect_gaps(
        self, df: pd.DataFrame, symbol: str, timeframe: str
    ) -> int:
        """Bar arası zaman boşluklarını tespit et ve logla.

        Args:
            df: Zamana göre sıralı DataFrame.
            symbol: Kontrat sembolü.
            timeframe: Zaman dilimi etiketi.

        Returns:
            Tespit edilen gap sayısı.
        """
        if len(df) < 2:
            return 0

        expected_sec = EXPECTED_INTERVALS.get(timeframe, 60)
        # 2x beklenen aralık = gap
        threshold_sec = expected_sec * 2

        diffs = df["time"].diff().dt.total_seconds().iloc[1:]
        gaps = diffs[diffs > threshold_sec]

        if len(gaps) > 0:
            # Piyasa kapalı saatlerindeki gap'leri filtrele (normal boşluklar)
            real_gaps = []
            for idx in gaps.index:
                gap_start = df.loc[idx - 1, "time"]
                gap_end = df.loc[idx, "time"]
                if not self._is_market_hours_gap(gap_start, gap_end):
                    real_gaps.append((idx, gap_start, gap_end, gaps[idx]))

            # Sadece gerçek (piyasa saatleri içi) gap'leri logla
            for idx, gap_start, gap_end, gap_sec in real_gaps:
                logger.debug(
                    f"Gap [{symbol}/{timeframe}]: "
                    f"{gap_start} → {gap_end} ({gap_sec:.0f}s, "
                    f"beklenen {expected_sec}s)"
                )

            # DB event throttle: aynı sembol/tf için 5 dakikada 1 kez
            if real_gaps:
                throttle_key = f"{symbol}/{timeframe}"
                now = datetime.now()
                last = self._last_gap_event.get(throttle_key)
                if last is None or (now - last).total_seconds() > 300.0:
                    self._last_gap_event[throttle_key] = now
                    self._db.insert_event(
                        event_type="DATA_GAP",
                        message=(
                            f"{symbol}/{timeframe}: {len(real_gaps)} gap "
                            f"tespit edildi (piyasa saati içi)"
                        ),
                        severity="WARNING",
                    )

        return len(gaps)

    def _filter_outliers(
        self, df: pd.DataFrame, symbol: str, timeframe: str
    ) -> pd.DataFrame:
        """z-score > 5 olan barları filtrele.

        ``close`` fiyatının z-score'unu hesaplar;
        eşiği aşan barları çıkarır.

        Args:
            df: OHLCV DataFrame.
            symbol: Kontrat sembolü.
            timeframe: Zaman dilimi.

        Returns:
            Filtrelenmiş DataFrame.
        """
        if len(df) < 10:
            return df

        close = df["close"]
        mean = close.mean()
        std = close.std()

        if std == 0:
            return df

        z_scores = ((close - mean) / std).abs()
        outlier_mask = z_scores > ZSCORE_THRESHOLD
        n_outliers = outlier_mask.sum()

        if n_outliers > 0:
            outlier_rows = df[outlier_mask]
            for _, row in outlier_rows.iterrows():
                z = abs((row["close"] - mean) / std)
                logger.warning(
                    f"Outlier [{symbol}/{timeframe}]: "
                    f"time={row['time']}, close={row['close']:.4f}, "
                    f"z-score={z:.2f}"
                )

            df = df[~outlier_mask].reset_index(drop=True)

            self._db.insert_event(
                event_type="DATA_OUTLIER",
                message=(
                    f"{symbol}/{timeframe}: {n_outliers} outlier bar filtrelendi "
                    f"(z>{ZSCORE_THRESHOLD})"
                ),
                severity="WARNING",
            )

        return df

    @staticmethod
    def _is_market_hours_gap(t1: pd.Timestamp, t2: pd.Timestamp) -> bool:
        """İki bar arasındaki boşluk piyasa kapalı saatlerine mi denk geliyor?

        VİOP piyasa saatleri: Hafta içi ~09:30-18:15.
        Gece kapanış→açılış ve hafta sonu boşlukları normal kabul edilir.

        Args:
            t1: Önceki barın zamanı.
            t2: Sonraki barın zamanı.

        Returns:
            True ise gap piyasa kapalı dönemine denk geliyor (normal).
        """
        # Hafta sonu geçişi: Cuma → Pazartesi
        if t1.weekday() == 4 and t2.weekday() == 0:  # Fri→Mon
            return True
        # Farklı günler arası (gece kapanışı): aynı hafta içi
        if t1.date() != t2.date():
            return True
        # Aynı gün ama gece seansı arası (18:15 → ertesi gün)
        if t1.hour >= 18 or t2.hour < 9:
            return True
        return False

    def _check_consecutive_missing(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        original_len: int,
    ) -> bool:
        """Ardışık eksik bar kontrolü.

        3+ ardışık beklenen bar eksikse kontratı deaktif eder.
        Piyasa kapalı saatlerindeki (gece, hafta sonu) boşluklar sayılmaz.

        Args:
            df: Temizlenmiş DataFrame.
            symbol: Kontrat sembolü.
            timeframe: Zaman dilimi.
            original_len: Temizlik öncesi bar sayısı.

        Returns:
            True ise kontrat sağlıklı, False ise deaktif edildi.
        """
        if len(df) < 2:
            return True

        expected_sec = EXPECTED_INTERVALS.get(timeframe, 60)
        times = df["time"]
        diffs = times.diff().dt.total_seconds().iloc[1:]

        # Ardışık eksik bar sayısı = (gerçek aralık / beklenen) - 1
        missing_counts = (diffs / expected_sec).round().astype(int) - 1
        missing_counts = missing_counts.clip(lower=0)

        # Piyasa kapalı saatlerindeki boşlukları sıfırla
        for idx in missing_counts.index:
            if missing_counts[idx] >= MAX_CONSECUTIVE_MISSING:
                t1 = times.iloc[idx - 1] if idx > 0 else times.iloc[0]
                t2 = times.iloc[idx] if idx < len(times) else times.iloc[-1]
                if self._is_market_hours_gap(t1, t2):
                    missing_counts.at[idx] = 0

        max_consecutive = int(missing_counts.max()) if len(missing_counts) > 0 else 0

        if max_consecutive >= MAX_CONSECUTIVE_MISSING:
            self._deactivated.add(symbol)
            logger.error(
                f"Kontrat deaktif edildi [{symbol}/{timeframe}]: "
                f"{max_consecutive} ardışık eksik bar "
                f"(eşik={MAX_CONSECUTIVE_MISSING})"
            )
            self._db.insert_event(
                event_type="SYMBOL_DEACTIVATED",
                message=(
                    f"{symbol}: {max_consecutive} ardışık eksik bar "
                    f"({timeframe}), kontrat deaktif edildi"
                ),
                severity="ERROR",
                action="deactivate_symbol",
            )
            return False

        return True

    # ═════════════════════════════════════════════════════════════════
    #  TICK / SPREAD
    # ═════════════════════════════════════════════════════════════════
    def fetch_tick_data(self, symbol: str) -> TickSnapshot | None:
        """Tek sembol için anlık tick/spread verisi çek.

        Args:
            symbol: Kontrat sembolü.

        Returns:
            TickSnapshot nesnesi veya hata durumunda None.
        """
        try:
            tick = self._mt5.get_tick(symbol)
            if tick is None:
                return None

            snap = TickSnapshot(
                symbol=symbol,
                bid=tick.bid,
                ask=tick.ask,
                spread=tick.spread,
                timestamp=tick.time.isoformat(timespec="seconds"),
            )
            self.latest_ticks[symbol] = snap
            return snap

        except Exception as exc:
            logger.error(f"fetch_tick_data istisnası [{symbol}]: {exc}")
            return None

    def fetch_all_ticks(self) -> dict[str, TickSnapshot]:
        """15 kontratın tümü için tick/spread verisi çek — sıralı (eski).

        Returns:
            {symbol: TickSnapshot} sözlüğü.
        """
        result: dict[str, TickSnapshot] = {}

        for symbol in WATCHED_SYMBOLS:
            if symbol in self._deactivated:
                continue
            snap = self.fetch_tick_data(symbol)
            if snap:
                result[symbol] = snap

        logger.debug(f"Tick güncelleme: {len(result)}/{len(WATCHED_SYMBOLS)} sembol")
        return result

    def fetch_all_ticks_parallel(self) -> dict[str, TickSnapshot]:
        """15 kontratın tümü için tick/spread verisi çek (paralel).

        Returns:
            {symbol: TickSnapshot} sözlüğü.
        """
        active_symbols = [s for s in WATCHED_SYMBOLS if s not in self._deactivated]
        result: dict[str, TickSnapshot] = {}

        if not active_symbols:
            return result

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(self.fetch_tick_data, sym): sym
                for sym in active_symbols
            }
            for future in as_completed(futures, timeout=5.0):
                try:
                    snap = future.result(timeout=1.0)
                    if snap:
                        result[snap.symbol] = snap
                except Exception as exc:
                    sym = futures[future]
                    logger.error(f"Paralel tick hatası [{sym}]: {exc}")

        logger.debug(f"Tick paralel güncelleme: {len(result)}/{len(active_symbols)} sembol")
        return result

    # ═════════════════════════════════════════════════════════════════
    #  RISK SNAPSHOT
    # ═════════════════════════════════════════════════════════════════
    def update_risk_snapshot(self) -> dict[str, Any] | None:
        """Equity, floating PnL, pozisyonlar ve drawdown snapshot'ı al ve DB'ye yaz.

        Hesap bilgisi + açık pozisyonlar + son risk snapshot'tan
        drawdown hesaplanır.

        Returns:
            Kaydedilen snapshot sözlüğü veya hata durumunda None.
        """
        try:
            # Hesap bilgisi
            account = self._mt5.get_account_info()
            if account is None:
                logger.warning("Risk snapshot: hesap bilgisi alınamadı")
                return None

            # Açık pozisyonlar
            positions = self._mt5.get_positions()

            # Cache güncelle — WebSocket buradan okur (Madde 2.4)
            self.latest_account = account
            self.latest_positions = positions
            self._cache_time = datetime.now()

            # Floating PnL = pozisyonların toplam profit + swap
            # MT5: equity = balance + profit + swap, dolayısıyla her ikisi de dahil
            floating_pnl = sum(
                p.get("profit", 0.0) + p.get("swap", 0.0) for p in positions
            )

            # Günlük PnL — gün başı equity'den fark
            daily_pnl = self._calculate_daily_pnl(account.equity)

            # Drawdown — peak equity'ye göre
            drawdown = self._calculate_drawdown(account.equity)

            # Margin kullanım oranı
            margin_usage = 0.0
            if account.equity > 0:
                margin_usage = round(account.margin / account.equity * 100, 2)

            # Rejim bilgisi (son risk_snapshot'tan veya default)
            last_snap = self._db.get_latest_risk_snapshot()
            regime = last_snap.get("regime", "NORMAL") if last_snap else "NORMAL"

            snapshot: dict[str, Any] = {
                "equity": account.equity,
                "balance": account.balance,
                "floating_pnl": floating_pnl,
                "daily_pnl": daily_pnl,
                "positions_json": positions,
                "regime": regime,
                "drawdown": drawdown,
                "margin_usage": margin_usage,
            }

            self._db.insert_risk_snapshot(snapshot)

            logger.debug(
                f"Risk snapshot: equity={account.equity:.2f}, "
                f"floating={floating_pnl:.2f}, daily={daily_pnl:.2f}, "
                f"dd={drawdown:.4f}, margin%={margin_usage:.1f}"
            )
            return snapshot

        except Exception as exc:
            logger.error(f"update_risk_snapshot istisnası: {exc}")
            return None

    def _calculate_daily_pnl(self, current_equity: float) -> float:
        """Günlük realized PnL hesapla (MT5 tarzı).

        Bugün kapatılan işlemlerin (pnl + commission + swap) toplamını döndürür.
        Equity değişimi yerine realized profit kullanılır — MT5'in
        HistoryDealGetDouble(DEAL_PROFIT + DEAL_COMMISSION + DEAL_SWAP)
        mantığıyla aynı.

        Args:
            current_equity: Mevcut equity (artık kullanılmıyor, imza uyumu için).

        Returns:
            Günlük realized PnL tutarı.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        trades = self._db.get_trades(
            exit_since=f"{today}T00:00:00",
            closed_only=True,
            limit=1000,
        )

        if not trades:
            return 0.0

        # MT5 tarzı: pnl + commission + swap toplamı
        total = 0.0
        for t in trades:
            pnl = t.get("pnl") or 0.0
            commission = t.get("commission") or 0.0
            swap = t.get("swap") or 0.0
            total += pnl + commission + swap

        return round(total, 2)

    def _validate_peak_equity(self) -> None:
        """Peak equity'yi RISK_BASELINE_DATE'e göre doğrula.

        Eski test/geliştirme verilerinden kalan şişirilmiş peak_equity
        değerini tespit eder ve baseline sonrası gerçek max equity ile
        değiştirir. Engine başlangıcında bir kez çalışır.
        """
        from engine.baba import RISK_BASELINE_DATE

        stored = self._db.get_state("peak_equity")
        if not stored:
            return

        stored_peak = float(stored)

        # Baseline sonrası gerçek max equity'yi bul
        snapshots = self._db.get_risk_snapshots(
            since=f"{RISK_BASELINE_DATE}T00:00:00", limit=50000,
        )
        if not snapshots:
            return

        max_eq = max(
            (s.get("equity", 0.0) for s in snapshots),
            default=0.0,
        )

        # Stored peak baseline sonrası max'tan büyükse → eski dönemden kalmış
        if max_eq > 0 and stored_peak > max_eq:
            self._db.set_state("peak_equity", str(max_eq))
            logger.warning(
                f"Peak equity sıfırlandı: {stored_peak:.2f} → {max_eq:.2f} "
                f"(RISK_BASELINE_DATE={RISK_BASELINE_DATE} ile uyumsuz)"
            )

    def _calculate_drawdown(self, current_equity: float) -> float:
        """Drawdown hesapla (kalıcı peak equity'ye göre).

        Peak equity DB'de kalıcı saklanır (Madde 1.4).
        İlk çalıştırmada DB'de peak yoksa mevcut equity kullanılır.

        Args:
            current_equity: Mevcut equity.

        Returns:
            Drawdown oranı (0.0–1.0 arası). 0.05 = %5 drawdown.
        """
        # DB'den kalıcı peak oku
        stored = self._db.get_state("peak_equity")
        stored_peak = float(stored) if stored else 0.0

        # Mevcut equity ile karşılaştır
        peak = max(stored_peak, current_equity)

        # Yeni peak ise DB'ye kaydet
        if peak > stored_peak:
            self._db.set_state("peak_equity", str(peak))
            logger.debug(f"Peak equity güncellendi: {stored_peak:.2f} → {peak:.2f}")

        if peak <= 0:
            return 0.0

        dd = (peak - current_equity) / peak
        return round(max(dd, 0.0), 6)

    # ═════════════════════════════════════════════════════════════════
    #  KONTRAT YÖNETİMİ
    # ═════════════════════════════════════════════════════════════════
    def reactivate_symbol(self, symbol: str) -> bool:
        """Deaktif edilmiş kontratı tekrar aktif et.

        Args:
            symbol: Kontrat sembolü.

        Returns:
            Kontrat daha önce deaktifse ve yeniden aktif edildiyse True.
        """
        if symbol not in self._deactivated:
            return False

        self._deactivated.discard(symbol)
        logger.info(f"Kontrat yeniden aktif edildi: {symbol}")
        self._db.insert_event(
            event_type="SYMBOL_REACTIVATED",
            message=f"{symbol} yeniden aktif edildi",
            severity="INFO",
        )
        return True

    def get_active_symbols(self) -> list[str]:
        """Aktif (deaktif edilmemiş) sembol listesi.

        Returns:
            Aktif sembol listesi.
        """
        return [s for s in WATCHED_SYMBOLS if s not in self._deactivated]

    def get_deactivated_symbols(self) -> list[str]:
        """Deaktif edilmiş sembol listesi.

        Returns:
            Deaktif sembol listesi.
        """
        return list(self._deactivated)

    def get_pipeline_status(self) -> dict[str, Any]:
        """Pipeline durum özeti.

        Returns:
            Durum sözlüğü: aktif/deaktif sayıları, son tick zamanları.
        """
        return {
            "active_symbols": len(self.get_active_symbols()),
            "deactivated_symbols": self.get_deactivated_symbols(),
            "total_symbols": len(WATCHED_SYMBOLS),
            "ticks_available": len(self.latest_ticks),
            "timeframes": list(TIMEFRAMES.keys()),
        }
