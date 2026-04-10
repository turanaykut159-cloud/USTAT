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
    Günlük zarar %2.5 → tüm işlemler dur → ertesi gün 09:30 sıfırla
    Haftalık zarar %4 → lot %50 azalt → Pazartesi 09:30 sıfırla
    Aylık zarar %7    → sistem dur → manuel onay
    Max DD %10 / Hard DD %15 → tam kapanış → manuel onay
    3 üst üste kayıp  → 2 saat cool-down
    Floating loss %2.0 → yeni işlem engeli
    Günlük max işlem 8 / Tek işlem max %2

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
import threading
from collections import deque
from datetime import date, datetime, time, timedelta
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
ATR_VOLATILE_MULT:     float = 2.5     # v14: 2.0→2.5 (VİOP normali daha volatil)
SPREAD_VOLATILE_MULT:  float = 4.0     # v14: 3.0→4.0 (düşük likidite spread'i)
PRICE_MOVE_PCT:        float = 2.5     # v14: 2.0→2.5 (VİOP haber odaklı piyasa)
VOLATILE_VOTE_PCT:     float = 0.40    # v14: %30→%40 (VOLATILE için daha fazla oy)

# ── OLAY eşikleri ───────────────────────────────────────────────────
USDTRY_SHOCK_PCT:      float = 2.0
EXPIRY_DAYS:           int   = 0     # v5.9: Vade kısıtlaması kaldırıldı (kullanıcı talimatı)

# ── OLAY saatlik pencere (v14: tüm gün yerine zaman bazlı) ────────
# TCMB PPK kararı genelde 14:00, FED kararı gece (TR saati).
# Sabah (09:45-12:00) ve karar sonrası (15:30+) normal işlem mümkün.
OLAY_BLOCK_START: time = time(12, 0)   # OLAY blok başlangıcı
OLAY_BLOCK_END:   time = time(15, 30)  # OLAY blok bitişi
OLAY_FULL_DAY_TRIGGERS: set = {"expiry", "usdtry"}  # Tam gün OLAY tetikleyicileri

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
HARD_DRAWDOWN_PCT:       float = 0.15    # config: risk.hard_drawdown_pct
CONSECUTIVE_LOSS_LIMIT:  int   = 3
COOLDOWN_HOURS:          int   = 4       # config: risk.cooldown_hours
MAX_FLOATING_LOSS_PCT:   float = 0.015   # config: risk.max_floating_loss_pct
MAX_DAILY_TRADES:        int   = 5       # config: risk.max_daily_trades
MAX_RISK_PER_TRADE_HARD: float = 0.02

# ── Korelasyon sabitleri ─────────────────────────────────────────────
MAX_SAME_DIRECTION:         int   = 3
MAX_SAME_SECTOR_DIRECTION:  int   = 2
MAX_INDEX_WEIGHT_SCORE:     float = 0.25

# ── Risk hesaplama başlangıç tarihi (varsayılan) ──────────────────
# Config'den okunur (risk.baseline_date). Bu sabit yalnızca fallback.
# Format: "YYYY-MM-DD" veya "YYYY-MM-DD HH:MM"
_DEFAULT_RISK_BASELINE_DATE: str = "2026-03-07"
RISK_BASELINE_DATE = _DEFAULT_RISK_BASELINE_DATE      # data_pipeline uyumu


def _baseline_to_iso(baseline: str) -> str:
    """Baseline string'ini ISO karşılaştırma formatına çevir.

    "2026-03-10"              → "2026-03-10T00:00:00"
    "2026-03-10 12:00"        → "2026-03-10T12:00:00"
    "2026-03-10T13:01:00"     → "2026-03-10T13:01:00"  (zaten ISO)
    """
    baseline = baseline.strip()
    if "T" in baseline:
        # Zaten ISO formatında — olduğu gibi döndür
        return baseline
    if " " in baseline:
        # "YYYY-MM-DD HH:MM" → "YYYY-MM-DDThh:mm:00"
        parts = baseline.split(" ", 1)
        return f"{parts[0]}T{parts[1]}:00"
    return f"{baseline}T00:00:00"

# ── Kill-switch seviyeleri ───────────────────────────────────────────
KILL_SWITCH_NONE: int = 0
KILL_SWITCH_L1:   int = 1   # kontrat durdur
KILL_SWITCH_L2:   int = 2   # sistem pause
KILL_SWITCH_L3:   int = 3   # tam kapanış

# ── Fake sinyal analiz sabitleri ───────────────────────────────────
FAKE_SCORE_THRESHOLD:  int   = 6       # v14: 5→6 (max 6, tüm katmanlar tetiklenmeli)
FAKE_VOLUME_RATIO_MIN: float = 0.7     # hacim / 20-bar ort. < 0.7 → FAKE
FAKE_VOLUME_LOOKBACK:  int   = 20      # hacim ortalaması bar sayısı
FAKE_SPREAD_MULT: dict[str, float] = {"A": 2.5, "B": 3.5, "C": 5.0}
FAKE_MTF_EMA_PERIOD:   int   = 9       # multi-TF EMA periyodu
FAKE_MTF_AGREEMENT_MIN: int  = 2       # en az 2/3 TF uyumu gerekli

# ── Spread / USDTRY geçmiş buffer uzunluğu ──────────────────────────
# SPREAD_HISTORY_LEN artık __init__'te dinamik hesaplanıyor (FAZ 2.4)
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
    # 2026 TCMB PPK (tahmini — her ayın üçüncü Perşembesi)
    date(2026, 1, 22), date(2026, 2, 19), date(2026, 3, 19),
    date(2026, 4, 16), date(2026, 5, 21), date(2026, 6, 18),
    date(2026, 7, 16), date(2026, 8, 20), date(2026, 9, 17),
    date(2026, 10, 22), date(2026, 11, 19), date(2026, 12, 17),
    # 2026 FED FOMC (tahmini — 8 toplantı, 2 günlük, son gün)
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 5, 6),
    date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16),
    date(2026, 10, 28), date(2026, 12, 16),
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
    # 2026 (v5.9.2: Mayıs düzeltmesi — Kurban Bayramı arefe 26 May yarım gün
    #        → VİOP kuralı: yarım gün = önceki iş günü → 25 Mayıs Pazartesi)
    date(2026, 1, 30), date(2026, 2, 27), date(2026, 3, 31),
    date(2026, 4, 30), date(2026, 5, 25), date(2026, 6, 30),
    date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30),
    date(2026, 10, 30), date(2026, 11, 30), date(2026, 12, 31),
}


def validate_expiry_dates() -> list[str]:
    """VİOP vade tarihlerinin iş günü olduğunu doğrula (Madde 2.7).

    Hafta sonu, tatil veya yarım güne denk gelen tarihleri tespit eder.
    VİOP kuralı: Yarım gün (arefe) vadeye denk gelirse,
    vade bir önceki iş gününe çekilmelidir.
    Engine başlangıcında çağrılır.

    Returns:
        Sorunlu tarihlerin açıklama listesi. Boş liste = tümü geçerli.
    """
    from engine.utils.time_utils import ALL_HOLIDAYS, ALL_HALF_DAYS

    issues: list[str] = []
    for expiry in sorted(VIOP_EXPIRY_DATES):
        weekday = expiry.weekday()  # 0=Pazartesi, 5=Cumartesi, 6=Pazar
        if weekday >= 5:
            day_name = "Cumartesi" if weekday == 5 else "Pazar"
            issues.append(f"{expiry.isoformat()} - {day_name} (hafta sonu)")
        elif expiry in ALL_HOLIDAYS:
            issues.append(f"{expiry.isoformat()} - Tatil günü")
        elif expiry in ALL_HALF_DAYS:
            issues.append(
                f"{expiry.isoformat()} - Yarım gün (arefe) — "
                f"vade önceki iş gününe çekilmeli!"
            )
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
        error_tracker=None,
    ) -> None:
        self._config = config
        self._db = db
        self._mt5 = mt5
        self._error_tracker = error_tracker
        self.current_regime: Regime = Regime(regime_type=RegimeType.TREND)
        self.active_warnings: list[EarlyWarning] = []

        # Baseline date — config'den oku (FAZ 2.3)
        self._risk_baseline_date: str = self._config.get(
            "risk.baseline_date", _DEFAULT_RISK_BASELINE_DATE
        )

        # Spread ring buffer — cycle_interval'a göre dinamik boyut (FAZ 2.4)
        _cycle_interval = self._config.get("engine.cycle_interval", 10)
        self._spread_history_len: int = max(10, int(300 / _cycle_interval))

        self._spread_history: dict[str, deque[float]] = {
            s: deque(maxlen=self._spread_history_len) for s in WATCHED_SYMBOLS
        }
        # USD/TRY ring buffer (deque: thread-safe append + auto truncation)
        self._usdtry_history: deque[float] = deque(maxlen=self._spread_history_len)

        # ── Risk durumu (bellekte, her cycle kontrol edilir) ──────────
        self._risk_state: dict[str, Any] = {
            "daily_reset_date": None,
            "daily_trade_count": 0,
            "daily_auto_trade_count": 0,    # v14: otomatik işlem sayısı
            "daily_manual_trade_count": 0,  # v14: manuel işlem sayısı
            "weekly_reset_week": None,
            "weekly_loss_halved": False,
            "monthly_reset_month": None,
            "monthly_paused": False,
            "consecutive_losses": 0,
            "last_trade_count": 0,
            "cooldown_until": None,
            "last_cooldown_end": None,
            "daily_reset_equity": None,     # Fix: günlük sıfırlama anındaki equity
        }

        # ── Risk state geri yükleme (restart dayanıklılığı) ─────────
        self._restore_risk_state()

        # ── Cycle sayacı (fake analiz frekansı için) ──────────────────
        self._cycle_count: int = 0

        # ── Cross-motor referansı (fake sinyal koruması) ─────────────
        self.manuel_motor: Any | None = None  # main.py tarafından atanır
        # v14.1 — OĞUL referansı (L2 kayıp kapanışı için)
        self.ogul: Any | None = None  # main.py tarafından atanır

        # ── ÜSTAT geri bildirim ─────────────────────────────────────
        self._risk_miss_log: list[dict] = []
        self._risk_miss_count: int = 0

        # ── Kill-switch durumu ───────────────────────────────────────
        self._kill_switch_level: int = KILL_SWITCH_NONE
        self._kill_switch_details: dict[str, Any] = {}
        self._killed_symbols: set[str] = set()
        self._ks_lock = threading.Lock()  # Kill-switch atomik geçiş kilidi (Anayasa 4.3)
        self._rs_lock = threading.Lock()  # Risk-state atomik okuma/yazma kilidi
        # L3 kapanışta kapatılamayan pozisyon ticket'ları (API'ye iletilir)
        self._last_l3_failed_tickets: list[int] = []
        # v5.8/CEO-FAZ1: SL/TP eklenememiş + kapatılamamış korumasız pozisyonlar
        self._unprotected_positions: list[dict] = []

        # v5.8/CEO-FAZ1: Regime hysteresis — ping-pong önleme
        # Rejim değişimi ancak 2 ardışık cycle aynı yeni rejimi gösterdiğinde onaylanır
        self._confirmed_regime: RegimeType | None = None   # Son onaylanmış rejim
        self._pending_regime: RegimeType | None = None      # Aday rejim (henüz onaylanmamış)
        self._pending_regime_count: int = 0                 # Aday kaç cycle devam etti

        # v5.8/CEO-FAZ2: Margin reserve kontrolü — config'den oku
        self._margin_reserve_pct: float = float(
            self._config.get("engine.margin_reserve_pct", 0.20)
        )

        # v13.0: "izin verdi" olay kaydı dedup (5 dk'da 1 kez)
        self._last_risk_allowed_log: datetime | None = None

        # Volume spike cooldown — sembol başına son uyarı zamanı (saniye)
        self._volume_spike_cooldowns: dict[str, float] = {}

        # v5.7.1: Haber köprüsü referansı (main.py tarafından atanır)
        self._news_bridge: Any | None = None

    def set_news_bridge(self, news_bridge) -> None:
        """NewsBridge referansını kaydet (engine başlatmada çağrılır)."""
        self._news_bridge = news_bridge
        logger.info("BABA: NewsBridge referansı bağlandı.")

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

        # ── ÜSTAT bildirimlerini oku ve logla ────────────────────
        # ÜSTAT risk parametrelerini değiştirdiğinde ustat_notifications
        # kuyruğuna yazar. BABA burada bilgilendirilir.
        self._process_ustat_notifications()

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

        # ── Risk state DB persist (her cycle) ─────────────────────
        self._persist_risk_state()

        return regime

    # ── Risk state DB persist / restore ────────────────────────────

    _RISK_STATE_DB_KEY = "baba_risk_state"

    def _persist_risk_state(self) -> None:
        """Risk state'ini DB'ye kaydet (her cycle sonunda).

        Serileştirme: date/datetime/tuple → ISO string dönüşümü yapılır.
        Geri yükleme sırasında ``_restore_risk_state`` aynı dönüşümü tersine çevirir.
        """
        try:
            import json as _json

            # date / datetime / tuple → JSON-serializable dönüşüm
            serializable: dict[str, Any] = {}
            for key, val in self._risk_state.items():
                if isinstance(val, date) and not isinstance(val, datetime):
                    serializable[key] = {"_type": "date", "v": val.isoformat()}
                elif isinstance(val, datetime):
                    serializable[key] = {"_type": "datetime", "v": val.isoformat()}
                elif isinstance(val, tuple):
                    serializable[key] = {"_type": "tuple", "v": list(val)}
                else:
                    serializable[key] = val

            self._db.set_state(
                self._RISK_STATE_DB_KEY, _json.dumps(serializable)
            )
        except Exception as exc:
            logger.warning(f"[BABA] Risk state persist hatası: {exc}")

    def _restore_risk_state(self) -> None:
        """Engine restart'ta risk state'ini DB'den geri yükle.

        DB'de kayıtlı state yoksa veya deserializasyon başarısız olursa
        varsayılan (sıfır) değerlerle devam edilir.
        """
        try:
            import json as _json

            raw = self._db.get_state(self._RISK_STATE_DB_KEY)
            if not raw:
                logger.info("[BABA] Risk state geri yükleme: DB'de kayıt yok — varsayılan")
                return

            stored: dict[str, Any] = _json.loads(raw)
            restored_keys: list[str] = []

            for key, val in stored.items():
                if key not in self._risk_state:
                    continue  # bilinmeyen anahtar — güvenli atla

                # Tip dönüşümü (serialize sırasında eklenen _type tag'ları)
                if isinstance(val, dict) and "_type" in val:
                    t = val["_type"]
                    v = val["v"]
                    if t == "date":
                        val = date.fromisoformat(v)
                    elif t == "datetime":
                        val = datetime.fromisoformat(v)
                    elif t == "tuple":
                        val = tuple(v)

                old = self._risk_state[key]
                if old != val:
                    restored_keys.append(f"{key}: {old} → {val}")
                self._risk_state[key] = val

            if restored_keys:
                logger.info(
                    f"[BABA] Risk state geri yüklendi: {'; '.join(restored_keys)}"
                )
            else:
                logger.info("[BABA] Risk state geri yüklendi (değişiklik yok)")

        except Exception as exc:
            logger.warning(
                f"[BABA] Risk state geri yükleme hatası: {exc} — varsayılan kullanılacak"
            )

    def _process_ustat_notifications(self) -> None:
        """ÜSTAT'ın risk parametre ayarlamalarını oku ve logla.

        ÜSTAT parametreleri değiştirdiğinde RiskParams.ustat_notifications
        kuyruğuna mesaj yazar. BABA burada bu mesajları okur, loglar ve
        kuyruğu temizler. Böylece BABA, ÜSTAT'ın yaptığı değişikliklerden
        haberdar olur ve loglarına yansıtır.
        """
        # risk_params referansını bul (self'te olmayabilir, main.py'de tutulur)
        # BABA check_risk_limits'e risk_params parametre olarak alır,
        # ama run_cycle'da doğrudan erişim yok. risk_params kuyruğunu
        # main.py üzerinden erişebilmek için dolaylı yol kullanıyoruz.
        # Alternatif: main.py'de risk_params referansını baba'ya da ver.
        # Burada __init__'te atanmış _risk_params_ref kullanılır.
        rp = getattr(self, "_risk_params_ref", None)
        if rp is None:
            return

        notifications = getattr(rp, "ustat_notifications", [])
        if not notifications:
            return

        for msg in notifications:
            logger.info(f"[BABA] ÜSTAT bildirimi: {msg}")
            # DB'ye de kaydet
            try:
                if self._db:
                    self._db.insert_event(
                        event_type="USTAT_NOTIFICATION",
                        message=msg,
                        severity="WARNING",
                        action="baba_risk",
                    )
            except Exception as exc:
                logger.warning(f"ÜSTAT bildirimi DB kayıt hatası: {exc}")

        # Kuyruğu temizle
        rp.ustat_notifications.clear()

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

        # FAZ 2.1: Likidite sınıfına göre oy ağırlığı
        _LIQ_VOTE_WEIGHT = {"A": 3, "B": 2, "C": 1}

        for symbol in WATCHED_SYMBOLS:
            result = self._classify_symbol(symbol)
            if result is None:
                continue
            liq = self._get_liquidity_class(symbol)
            votes[result["regime"]] += _LIQ_VOTE_WEIGHT.get(liq, 1)
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

        # v14: VOLATILE ≥ %40 → tüm piyasa VOLATILE (eskiden %30)
        if votes[RegimeType.VOLATILE] / total >= VOLATILE_VOTE_PCT:
            winner = RegimeType.VOLATILE
        else:
            winner = max(votes, key=votes.get)

        # Fix 7: RANGE + yüksek ADX çelişkisi → TREND'e override
        adx_override = False
        if winner == RegimeType.RANGE and adx_vals:
            avg_adx = float(np.nanmean(adx_vals))
            if np.isnan(avg_adx):
                avg_adx = 0.0
            if avg_adx > ADX_TREND_THRESHOLD:
                logger.info(
                    f"Rejim ADX çapraz kontrol: RANGE→TREND "
                    f"(avg_adx={avg_adx:.1f}>{ADX_TREND_THRESHOLD})"
                )
                winner = RegimeType.TREND
                adx_override = True

        # Fix: ADX override sonrası confidence, override koşulundan hesaplansın
        if adx_override:
            # ADX override güvenilir bir karar — confidence ADX gücüne göre
            confidence = round(min(avg_adx / 50.0, 1.0), 3)
        else:
            confidence = round(votes[winner] / total, 3)

        regime = Regime(
            regime_type=winner,
            confidence=confidence,
            adx_value=round(float(np.mean(adx_vals)), 2) if adx_vals else 0.0,
            atr_ratio=round(float(np.mean(atr_rats)), 3) if atr_rats else 0.0,
            bb_width_ratio=round(float(np.mean(bb_rats)), 3) if bb_rats else 0.0,
            details={"per_symbol": details_per, "votes": {k.value: v for k, v in votes.items()}},
        )

        # v5.8/CEO-FAZ1: Regime hysteresis — ping-pong önleme
        # OLAY hariç, rejim değişimi 2 ardışık cycle aynı sonucu verdiğinde onaylanır
        HYSTERESIS_CYCLES = 2
        raw_winner = winner

        if self._confirmed_regime is not None and winner != self._confirmed_regime:
            # Yeni rejim önerisi geldi — aday olarak beklet
            if winner == self._pending_regime:
                self._pending_regime_count += 1
            else:
                self._pending_regime = winner
                self._pending_regime_count = 1

            if self._pending_regime_count >= HYSTERESIS_CYCLES:
                # Yeterince tekrar etti — onayla
                logger.info(
                    f"Rejim hysteresis onay: {self._confirmed_regime.value}"
                    f"→{winner.value} ({self._pending_regime_count} cycle)"
                )
                self._confirmed_regime = winner
                self._pending_regime = None
                self._pending_regime_count = 0
            else:
                # Henüz onaylanmadı — eski rejimi koru
                logger.debug(
                    f"Rejim hysteresis bekleme: ham={winner.value}, "
                    f"korunan={self._confirmed_regime.value} "
                    f"(sayaç={self._pending_regime_count}/{HYSTERESIS_CYCLES})"
                )
                winner = self._confirmed_regime
                confidence = round(votes.get(winner, 0) / total, 3) if total > 0 else 0.5
                regime = Regime(
                    regime_type=winner,
                    confidence=confidence,
                    adx_value=round(float(np.mean(adx_vals)), 2) if adx_vals else 0.0,
                    atr_ratio=round(float(np.mean(atr_rats)), 3) if atr_rats else 0.0,
                    bb_width_ratio=round(float(np.mean(bb_rats)), 3) if bb_rats else 0.0,
                    details={"per_symbol": details_per, "votes": {k.value: v for k, v in votes.items()},
                             "hysteresis": f"bekleme({raw_winner.value})"},
                )
        else:
            # İlk kez veya aynı rejim devam ediyor
            self._confirmed_regime = winner
            self._pending_regime = None
            self._pending_regime_count = 0

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
        """TCMB/FED günü (saatlik pencere), vade sonu, kur şoku.

        v14 iyileştirmesi: Merkez bankası günlerinde tüm gün OLAY yerine
        sadece 12:00-15:30 arası OLAY. Vade ve kur şoku tam gün kalır.

        Returns:
            Neden sözlüğü veya None.
        """
        today = date.today()
        now_time = datetime.now().time()

        # 1. TCMB/FED günü — v14: saatlik pencere (12:00-15:30)
        if today in CENTRAL_BANK_DATES:
            if OLAY_BLOCK_START <= now_time <= OLAY_BLOCK_END:
                return {"reason": "TCMB/FED toplantı saati", "trigger": "calendar"}
            # Pencere dışında → OLAY değil, normal rejim algılamaya devam
            logger.debug(
                f"TCMB/FED günü ama pencere dışı ({now_time}) — "
                f"OLAY atlandı (pencere={OLAY_BLOCK_START}-{OLAY_BLOCK_END})"
            )

        # 2. Vade bitiş — tam gün OLAY (OLAY_FULL_DAY_TRIGGERS)
        # v5.9.1: EXPIRY_DAYS=0 ise vade kontrolü tamamen devre dışı
        # (top5_selection.py ile tutarlı — oturum #83 düzeltmesinin baba.py karşılığı)
        for expiry in VIOP_EXPIRY_DATES:
            days = (expiry - today).days
            if 0 <= days < EXPIRY_DAYS:
                return {
                    "reason": f"Vade bitiş: {expiry} ({days} gün kaldı)",
                    "trigger": "expiry",
                }

        # 3. USD/TRY şoku — tam gün OLAY
        usdtry_move = self._usdtry_5m_move_pct()
        if usdtry_move >= USDTRY_SHOCK_PCT:
            return {
                "reason": f"USD/TRY şoku: %{usdtry_move:.2f} (5dk)",
                "trigger": "usdtry",
                "value": usdtry_move,
            }

        # 4. Haber bazlı OLAY — news_bridge entegrasyonu (v5.7.1)
        if hasattr(self, '_news_bridge') and self._news_bridge is not None:
            news_olay = self._news_bridge.should_trigger_olay()
            if news_olay is not None:
                logger.warning(
                    f"HABER OLAY TETİKLEME: sentiment={news_olay['sentiment']:.2f} "
                    f"severity={news_olay['severity']} — {news_olay['reason']}"
                )
                return news_olay

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

        # Haber bazlı erken uyarılar (v5.7.1 — news_bridge entegrasyonu)
        if hasattr(self, '_news_bridge') and self._news_bridge is not None:
            news_warnings = self._news_bridge.get_news_warnings()
            for nw in news_warnings:
                warnings.append(EarlyWarning(
                    warning_type=nw["warning_type"],
                    symbol=nw["symbol"],
                    severity=nw["severity"],
                    value=nw["value"],
                    threshold=nw["threshold"],
                    liquidity_class=self._get_liquidity_class(nw["symbol"]) if nw["symbol"] != "GLOBAL" else "A",
                    message=nw["message"],
                ))

        if warnings:
            for w in warnings:
                self._db.insert_event(
                    event_type="EARLY_WARNING",
                    message=w.message,
                    severity=w.severity,
                    action=f"{w.warning_type}:{w.symbol}",
                    dedup_seconds=300,
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
        buf = self._spread_history.get(symbol)
        if buf is None or len(buf) < 5:
            return None
        history = list(buf)  # deque → list atomik snapshot

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
        if mult > VOLUME_SPIKE_MULT:
            import time as _time_mod
            now = _time_mod.time()
            last = self._volume_spike_cooldowns.get(symbol, 0.0)
            if now - last < 600.0:  # 10 dakikalık cooldown — flood önleme
                return None
            self._volume_spike_cooldowns[symbol] = now
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

        # Fix 2: lot formula pozitifse ama rounding sıfırladıysa → vol_min uygula
        if lot == 0 and risk_amount > 0 and vol_min > 0:
            base_lot = risk_amount / (atr_value * contract_size)
            if base_lot >= vol_min * 0.5:
                lot = vol_min
                logger.info(
                    f"Lot floor [{symbol}]: lot=0→vol_min={vol_min} "
                    f"(base_lot={base_lot:.3f})"
                )

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

        # Fix 1: Günlük sıfırlama sonrası reset equity varsa onu baz al
        # Bu sayede önceki günün kaybı yeni günü bloklamaz
        # Fix Y1: reset_eq'nun bugüne ait olduğunu doğrula (bayat veri koruması)
        reset_eq = self._risk_state.get("daily_reset_equity")
        reset_date = self._risk_state.get("daily_reset_date")
        today_str = date.today().isoformat()

        if (reset_eq is not None and reset_eq > 0
                and reset_date == today_str):
            day_start_equity = reset_eq
            daily_pnl = equity - reset_eq
        else:
            # Orijinal mantık: gün başı equity = anlık - daily_pnl
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
                dedup_seconds=300,
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
                dedup_seconds=300,
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

        # Haftalık sıfırlama (hafta değişmişse, piyasa açıkken)
        iso_cal = today.isocalendar()
        current_week = (iso_cal[0], iso_cal[1])
        if (
            self._risk_state["weekly_reset_week"] != current_week
            and market_open
        ):
            self._reset_weekly(current_week)

        # Aylık sıfırlama
        current_month = (today.year, today.month)
        if self._risk_state["monthly_reset_month"] != current_month and market_open:
            self._reset_monthly(current_month)

    def _reset_daily(self, today: date) -> None:
        """Günlük sayaçları sıfırla."""
        # FAZ 2.2: Snapshot ÖNCE al, SONRA reset yap (senkron sıralama)
        snap = self._db.get_latest_risk_snapshot()

        self._risk_state["daily_reset_date"] = today
        self._risk_state["daily_trade_count"] = 0
        self._risk_state["daily_auto_trade_count"] = 0     # v14: reset
        self._risk_state["daily_manual_trade_count"] = 0   # v14: reset
        self._risk_state["daily_reset_equity"] = None   # önceki günü temizle

        # Günlük kayıp veya üst üste kayıp nedenli L2 varsa kaldır
        # (yeni gün = temiz başlangıç — eski günün kaybı bugünü bloklamamalı)
        if (
            self._kill_switch_level == KILL_SWITCH_L2
            and self._kill_switch_details.get("reason")
            in ("daily_loss", "consecutive_loss")
        ):
            self._clear_kill_switch("Günlük sıfırlama — L2 kaldırıldı")

        # v5.9.1: Haber kaynaklı L1 kontrat engeli de yeni günde temizlenir
        # (önceki günün haberi bugünkü ticareti engellemememeli)
        if self._kill_switch_level == KILL_SWITCH_L1 and self._killed_symbols:
            self._clear_kill_switch(
                "Günlük sıfırlama — L1 kontrat engelleri kaldırıldı"
            )

        # Yeni gün: üst üste kayıp sayacını ve cooldown'u sıfırla
        # (önceki günün consecutive loss'u bugünü engellemesini önle)
        self._risk_state["consecutive_losses"] = 0
        self._risk_state["cooldown_until"] = None
        self._risk_state["last_cooldown_end"] = (
            datetime.now().isoformat(timespec="seconds")
        )

        # Snapshot'tan yeni günün equity bazını ayarla
        if snap:
            self._risk_state["daily_reset_equity"] = snap.get("equity", 0.0)
            logger.info(
                f"Günlük risk sıfırlama: {today} "
                f"(reset equity={self._risk_state['daily_reset_equity']:.2f})"
            )
        else:
            logger.info(f"Günlük risk sıfırlama: {today}")

        self._db.insert_event(
            event_type="RISK_RESET",
            message=f"Günlük sıfırlama: {today}",
            severity="INFO",
            action="daily_reset",
        )

        # Fix Y11: Reset sonrası hemen persist — crash durumunda
        # eski cooldown'un geri gelmesini önle
        self._persist_risk_state()

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
            verdict.risk_multiplier = 0.0  # v5.9.2-fix: L3'te risk_multiplier mutlaka 0
            verdict.kill_switch_level = KILL_SWITCH_L3
            verdict.reason = "KILL_SWITCH L3 aktif — tam kapanış"
            verdict.blocked_symbols = list(self._killed_symbols)
            return verdict

        # 2. Kill-switch L2 → sistem pause (can_trade=False kalır)
        # v5.9.2: risk_multiplier ile kısıtlı işlem imkanı
        if self._kill_switch_level == KILL_SWITCH_L2:
            verdict.can_trade = False
            verdict.lot_multiplier = 0.0
            verdict.kill_switch_level = KILL_SWITCH_L2
            verdict.reason = "KILL_SWITCH L2 aktif — sistem durduruldu"
            # v5.9.2: L2 nedenine göre kısıtlı risk_multiplier
            # v5.9.3 — BULGU #1 fix: Anayasa Kural 7 gereği OLAY rejimi
            # risk_multiplier 0.0 olmalı ("yeni işlem açılmaz, mevcutlar kapatılır").
            # Önceden yanlış olarak 0.15 verilmişti.
            ks_reason = self._kill_switch_details.get("reason", "")
            if ks_reason == "olay_regime":
                verdict.risk_multiplier = 0.0   # OLAY: Anayasa Kural 7 — tam blok
            elif ks_reason in ("daily_loss", "consecutive_loss"):
                verdict.risk_multiplier = 0.0   # Kayıp bazlı: tam blok
            else:
                verdict.risk_multiplier = 0.25  # Diğer L2: kısıtlı
            return verdict

        # 2b. v5.8/CEO-FAZ1: Korumasız pozisyon varsa yeni işlem yasak
        if self._unprotected_positions:
            verdict.can_trade = False
            verdict.reason = (
                f"KORUMASIZ POZİSYON — {len(self._unprotected_positions)} pozisyon "
                f"SL/TP'siz açık. Manuel müdahale gerekli."
            )
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

        # 8. Floating loss (%1.5+) — sadece OĞUL pozisyonları (v5.7.1)
        if self._check_floating_loss(risk_params, snap=snap):
            verdict.can_trade = False
            verdict.reason = f"OĞUL floating loss > %{risk_params.max_floating_loss*100:.1f} — yeni işlem engeli"
            return verdict

        # 8.5. Master floating koruma (%5) — TÜM motorlar (v5.7.1 — CEO Option C)
        if self._check_master_floating(snap=snap):
            self._activate_kill_switch(
                KILL_SWITCH_L2, "master_floating",
                "Master floating koruma: tüm motorlar toplam %5 aşıldı",
            )
            verdict.can_trade = False
            verdict.reason = "Master floating koruma (%5) — tüm motorlar durduruldu"
            verdict.kill_switch_level = KILL_SWITCH_L2
            return verdict

        # 9. Günlük işlem sayısı (v14: sadece otomatik işlemler sınırlanır)
        if self._risk_state["daily_auto_trade_count"] >= risk_params.max_daily_trades:
            verdict.can_trade = False
            verdict.reason = f"Günlük max otomatik işlem ({risk_params.max_daily_trades}) doldu"
            return verdict

        # 9.5 Hesap seviyesi toplam pozisyon limiti (v5.5.1)
        # OĞUL(5) + H-Engine(3) + Manuel(3) = 11 teorik max → config ile sınırla
        MAX_TOTAL_POSITIONS = self._config.get("engine.max_total_positions", 8)
        try:
            total_positions = len(self._mt5.get_positions() or [])
            if total_positions >= MAX_TOTAL_POSITIONS:
                verdict.can_trade = False
                verdict.reason = (
                    f"Toplam pozisyon limiti: {total_positions}/{MAX_TOTAL_POSITIONS} "
                    f"(tüm motorlar toplamı)"
                )
                return verdict
        except Exception as exc:
            # Fail-Safe (Anayasa 4.9): MT5 hatası → pozisyon sayısı bilinemiyor → işlem açma
            logger.error(
                "check_risk_limits: MT5 pozisyon sorgusu başarısız (%s) → can_trade=False (fail-safe)",
                exc,
            )
            verdict.can_trade = False
            verdict.reason = f"MT5 pozisyon sorgusu başarısız: {exc} (fail-safe kilitleme)"
            return verdict

        # 9.7 v5.8/CEO-FAZ2: Margin reserve kontrolü — BABA seviyesinde
        # Config'deki margin_reserve_pct (%20) serbest teminat kontrolü.
        # Daha önce sadece OĞUL/ManuelMotor emir seviyesinde kontrol ediyordu,
        # şimdi BABA risk seviyesinde de kontrol ediyor (çift katmanlı güvenlik).
        if self._mt5 is not None:
            try:
                _account = self._mt5.get_account_info()
                if _account is not None and _account.equity > 0:
                    if _account.free_margin < _account.equity * self._margin_reserve_pct:
                        verdict.can_trade = False
                        verdict.reason = (
                            f"Yetersiz serbest teminat — "
                            f"free={_account.free_margin:.0f} < "
                            f"reserve={_account.equity * self._margin_reserve_pct:.0f} "
                            f"(%{self._margin_reserve_pct*100:.0f} of equity)"
                        )
                        return verdict
            except Exception as exc:
                logger.warning(f"Margin reserve kontrolü başarısız: {exc} — devam ediliyor")

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

        # v5.9.2: Ardışık kayıp kademeli risk_multiplier
        cons_losses = self._risk_state.get("consecutive_losses", 0)
        if cons_losses >= 1 and verdict.can_trade:
            graduated = {1: 0.75, 2: 0.50}
            verdict.risk_multiplier = graduated.get(cons_losses, 0.25)

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
        # Fix Y8: String max yerine datetime karşılaştırma (leksikografik hata riski)
        monday_dt = datetime.combine(monday, time.min)
        baseline_dt = datetime.fromisoformat(
            _baseline_to_iso(self._risk_baseline_date)
        )
        since_dt = max(monday_dt, baseline_dt)
        since_str = since_dt.isoformat(timespec="seconds")
        snapshots = self._db.get_risk_snapshots(
            since=since_str, limit=1, oldest_first=True,
        )
        if not snapshots:
            return None

        # En eski snapshot = hafta başı equity (oldest_first=True ile ASC sıralı)
        week_start_equity = snapshots[0].get("equity", 0.0)
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
            _baseline_to_iso(self._risk_baseline_date),
        )
        snapshots = self._db.get_risk_snapshots(
            since=since_str, limit=1, oldest_first=True,
        )
        if not snapshots:
            return False

        # En eski snapshot = ay başı equity (oldest_first=True ile ASC sıralı)
        month_start_equity = snapshots[0].get("equity", 0.0)
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
        """Floating (açık pozisyon) kayıp kontrolü — motor bazlı ayrıştırma.

        v5.7.1 (CEO Option C):
          Katman 1 — OĞUL floating: sadece OĞUL pozisyonlarının kayıp oranı (%1.5).
                     Hibrit/Manuel floating bu kontrolü ETKİLEMEZ.
          Katman 2 — Master floating: TÜM motorların toplam kayıp oranı (%5).
                     Bu eşik aşılırsa Kill-Switch L2 tetiklenir (check_risk_limits'te).

        Args:
            risk_params: Risk parametreleri.
            snap: Önceden alınmış risk snapshot'ı. None ise DB'den çekilir.

        Returns:
            True → OĞUL floating loss > %1.5 → yeni işlem engeli.
        """
        if snap is None:
            snap = self._db.get_latest_risk_snapshot()
        if not snap:
            return False

        equity = snap.get("equity", 0.0)
        if equity <= 0:
            return False

        # ── Katman 1: OĞUL bazlı floating kontrol (%1.5) ──
        # ogul_floating_pnl snapshot'ta varsa onu kullan,
        # yoksa 0.0 kabul et (tüm hesap zararını OĞUL'a yükleme).
        # Master floating check (%5) zaten tüm hesabı koruyor.
        ogul_floating = snap.get("ogul_floating_pnl", 0.0)

        if ogul_floating < 0:
            ogul_loss_pct = abs(ogul_floating) / equity
            if ogul_loss_pct >= risk_params.max_floating_loss:
                logger.warning(
                    f"OĞUL FLOATING LOSS ENGELİ: %{ogul_loss_pct*100:.2f} "
                    f"(limit=%{risk_params.max_floating_loss*100:.1f})"
                )
                return True
        return False

    def _check_master_floating(self, snap: dict | None = None) -> bool:
        """Hesap seviyesi master floating koruma — TÜM motorlar.

        v5.7.1 (CEO Option C — Katman 2):
          Tüm motorların toplam floating kaybı equity'nin %5'ini aşarsa
          Kill-Switch L2 tetiklenir. Bu, tek bir motorun kontrolsüz
          büyümesine karşı son savunma hattıdır.

        Args:
            snap: Önceden alınmış risk snapshot'ı. None ise DB'den çekilir.

        Returns:
            True → toplam floating loss > %5 → Kill-Switch tetikle.
        """
        _MASTER_FLOATING_LIMIT = self._config.get("risk.master_floating_loss_pct", 0.05)

        if snap is None:
            snap = self._db.get_latest_risk_snapshot()
        if not snap:
            return False

        equity = snap.get("equity", 0.0)
        if equity <= 0:
            return False

        floating_pnl = snap.get("floating_pnl", 0.0)
        if floating_pnl < 0:
            total_loss_pct = abs(floating_pnl) / equity
            if total_loss_pct >= _MASTER_FLOATING_LIMIT:
                logger.warning(
                    f"MASTER FLOATING KORUMA: %{total_loss_pct*100:.2f} "
                    f"(limit=%{_MASTER_FLOATING_LIMIT*100:.1f}) — "
                    f"TÜM MOTORLAR toplam floating aşıldı"
                )
                return True
        return False

    def _update_consecutive_losses(self) -> None:
        """Üst üste kayıp sayacını DB'den güncelle — SADECE OĞUL trade'leri.

        Madde 1.6: Sadece son cooldown bitişinden sonraki trade'leri sayar.
        Bu, cooldown → tekrar aynı trade'leri sayma → tekrar cooldown
        sonsuz döngüsünü önler.

        v5.9.2: Motor izolasyonu — H-Engine (source="hybrid") ve ManuelMotor
        (source="app"/"mt5_direct") kayıpları OĞUL'un ardışık kayıp sayacını
        ETKİLEMEZ. Her motor kendi işlem limitlerinden sorumludur.
        """
        # Cooldown sonrası veya baseline sonrası (hangisi yeniyse)
        since = self._risk_state.get("last_cooldown_end") or _baseline_to_iso(self._risk_baseline_date)
        # limit=30: motor filtresi sonrası yeterli OĞUL trade'i kalsın
        trades = self._db.get_trades(limit=30, since=since)
        closed = [
            t for t in trades
            if t.get("pnl") is not None
            and t.get("exit_time") is not None
            and t.get("source", "") in ("", "auto", None)  # Sadece OĞUL trade'leri
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

    def increment_daily_trade_count(self, trade_type: str = "auto") -> None:
        """Bir işlem açıldığında çağrılır (Oğul tarafından).

        Günlük işlem sayacını arttırır (otomatik/manuel ayrımı).

        Args:
            trade_type: İşlem tipi ("auto" veya "manual"). Varsayılan "auto".
        """
        with self._rs_lock:
            self._risk_state["daily_trade_count"] += 1
            if trade_type == "manual":
                self._risk_state["daily_manual_trade_count"] += 1
            else:  # default is "auto"
                self._risk_state["daily_auto_trade_count"] += 1
        logger.debug(
            f"Günlük işlem sayısı: {self._risk_state['daily_trade_count']} "
            f"({trade_type})"
        )

    # ── Public risk durumu erişimleri (OĞUL/API kullanımı için) ────

    @property
    def kill_switch_level(self) -> int:
        """Mevcut kill-switch seviyesi (0=yok, 1=L1, 2=L2, 3=L3)."""
        return self._kill_switch_level

    @property
    def daily_trade_count(self) -> int:
        """Bugünkü işlem sayısı."""
        return self._risk_state.get("daily_trade_count", 0)

    @property
    def consecutive_losses(self) -> int:
        """Art arda zarar sayısı."""
        return self._risk_state.get("consecutive_losses", 0)

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
    #  ÜSTAT GERİ BİLDİRİM
    # ═════════════════════════════════════════════════════════════════

    def receive_feedback(self, attribution: dict) -> None:
        """ÜSTAT'tan hata atama geri bildirimi al ve eşik bazlı aksiyon al.

        RISK_MISS atandığında ÜSTAT bu metodu çağırır.
        BABA gelen bilgiyi loglar, sayacı günceller ve eşiklere göre aksiyon alır:
          - Aynı sembolde 3+ miss (24 saat) → L1 sembol durdur (1 gün)
          - Toplam 5+ miss (24 saat) → floating_loss eşiğini %10 sıkılaştır (geçici)

        Args:
            attribution: Hata atama dict'i (trade_id, error_type, symbol vb).
        """
        if not hasattr(self, "_risk_miss_log"):
            self._risk_miss_log: list[dict] = []
            self._risk_miss_count: int = 0

        self._risk_miss_log.append(attribution)
        self._risk_miss_count = getattr(self, "_risk_miss_count", 0) + 1

        # Max 50 kayıt tut
        if len(self._risk_miss_log) > 50:
            self._risk_miss_log = self._risk_miss_log[-50:]

        symbol = attribution.get("symbol", "?")
        trade_id = attribution.get("trade_id", 0)
        logger.warning(
            f"[BABA] ÜSTAT geri bildirimi: RISK_MISS — trade#{trade_id} "
            f"{symbol}, toplam miss: {self._risk_miss_count}"
        )

        # DB'ye kaydet
        if self._db:
            try:
                self._db.insert_event(
                    event_type="BABA_FEEDBACK",
                    message=(
                        f"ÜSTAT RISK_MISS bildirimi: trade#{trade_id} {symbol}. "
                        f"Toplam miss sayısı: {self._risk_miss_count}"
                    ),
                    severity="WARNING",
                )
            except Exception as exc:
                logger.warning(f"Risk feedback DB kayıt hatası: {exc}")

        # ── ÜSTAT Feedback Aksiyonları ──
        now = datetime.now()
        cutoff = now - timedelta(hours=24)

        # Son 24 saatteki miss'leri filtrele
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        recent_misses = [
            m for m in self._risk_miss_log
            if m.get("timestamp", "") >= cutoff_str
        ]

        # Aksiyon 1: Aynı sembolde 3+ miss → L1 sembol durdur
        symbol_miss_count = sum(
            1 for m in recent_misses if m.get("symbol") == symbol
        )
        if symbol_miss_count >= 3 and symbol not in self._killed_symbols:
            self._activate_kill_switch(
                level=1,  # KILL_SWITCH_L1
                reason=f"ÜSTAT feedback: {symbol} 24 saatte {symbol_miss_count} risk_miss",
                symbols=[symbol],
            )
            logger.warning(
                f"[BABA] ÜSTAT aksiyonu: {symbol} L1 durduruldu "
                f"({symbol_miss_count} miss/24h)"
            )

        # Aksiyon 2: Toplam 5+ miss → floating_loss eşiğini geçici sıkılaştır
        if len(recent_misses) >= 5:
            feedback_key = "_ustat_floating_tightened"
            if not getattr(self, feedback_key, False):
                rp = getattr(self, "_risk_params_ref", None)
                if rp is not None:
                    old_val = rp.max_floating_loss
                    new_val = round(max(0.008, old_val * 0.90), 4)
                    if new_val != old_val:
                        rp.max_floating_loss = new_val
                        setattr(self, feedback_key, True)
                        logger.warning(
                            f"[BABA] ÜSTAT aksiyonu: floating_loss eşiği sıkılaştırıldı "
                            f"%{old_val*100:.1f} → %{new_val*100:.1f} "
                            f"({len(recent_misses)} miss/24h)"
                        )

    # ═════════════════════════════════════════════════════════════════
    #  KILL-SWITCH
    # ═════════════════════════════════════════════════════════════════

    def _log_kill_event(
        self, message: str, severity: str = "ERROR", action: str | None = None,
    ) -> None:
        """Kill-switch olayını ErrorTracker + DB'ye kaydet."""
        if self._error_tracker:
            self._error_tracker.record_error(
                error_type="KILL_SWITCH",
                message=message,
                severity=severity,
                action=action,
            )
        else:
            self._db.insert_event(
                event_type="KILL_SWITCH",
                message=message,
                severity=severity,
                action=action,
                dedup_seconds=300,
            )

    def _activate_kill_switch(
        self,
        level: int,
        reason: str,
        message: str,
        symbols: list[str] | None = None,
    ) -> None:
        """Kill-switch'i etkinleştir.

        Sadece yukarı yönlü geçiş (L1→L2 olur ama L2→L1 olmaz).
        Thread-safe: _ks_lock ile korunur (Anayasa 4.3 — monotonluk garantisi).

        Args:
            level: Seviye (1, 2, 3).
            reason: Neden kodu.
            message: Log/event mesajı.
            symbols: L1 için etkilenen semboller.
        """
        with self._ks_lock:
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

        self._log_kill_event(message, severity, f"LEVEL_{level}")

        # L3: tüm pozisyonları kapat; başarısız ticket listesi saklanır
        if level == KILL_SWITCH_L3:
            # v5.9.1 Fix #146: Önce h_engine bekleyen emirlerini iptal et.
            # BABA _close_all_positions sadece MT5 pozisyonlarını kapatır —
            # h_engine'in STOP LIMIT / LIMIT emirleri kalır ve yetim olur.
            # force_close_all hem emirleri iptal eder hem pozisyonları kapatır.
            h_eng = getattr(self, "h_engine", None)
            if h_eng is not None:
                try:
                    h_failed = h_eng.force_close_all("KILL_SWITCH_L3")
                    if h_failed:
                        logger.error(
                            f"L3 h_engine kapatma başarısız ticketlar: {h_failed}"
                        )
                except Exception as exc:
                    logger.error(f"L3 h_engine.force_close_all hatası: {exc}")
            self._last_l3_failed_tickets = self._close_all_positions("KILL_SWITCH_L3")

        # v14.1 — L2 kayıp tetikleri: OĞUL + H-Engine pozisyonlarını kapat
        # Manuel pozisyonlar ManuelMotor'un sorumluluğunda — dokunulmaz.
        # Eskiden bu iş OĞUL _check_advanced_risk_rules'in işiydi;
        # tek merkezi kapanış yeri olarak BABA'ya taşındı.
        # v5.9.3 — BULGU #1 fix: OLAY rejimi L2 de OĞUL + H-Engine pozisyonlarını
        # kapatır (Anayasa Kural 7: "Yeni işlem açılmaz, mevcutlar kapatılır").
        # Manuel pozisyonlar yine dokunulmaz.
        elif level == KILL_SWITCH_L2 and reason in ("daily_loss", "monthly_loss", "olay_regime"):
            try:
                self._close_ogul_and_hybrid(f"KILL_SWITCH_L2_{reason}")
            except Exception as exc:
                logger.error(f"L2 ({reason}) kapanış hatası: {exc}")

    def _clear_kill_switch(self, reason: str) -> None:
        """Kill-switch'i temizle.

        Thread-safe: _ks_lock ile korunur.

        Args:
            reason: Temizleme nedeni.
        """
        with self._ks_lock:
            old_level = self._kill_switch_level
            self._kill_switch_level = KILL_SWITCH_NONE
            self._kill_switch_details = {}
            self._killed_symbols.clear()

        logger.info(f"Kill-switch temizlendi (L{old_level}→L0): {reason}")
        self._log_kill_event(
            f"Kill-switch temizlendi (L{old_level}): {reason}", "INFO", "LEVEL_0",
        )

    def acknowledge_kill_switch(self, user: str = "operator") -> bool:
        """Manuel kill-switch onay (Desktop/API'den çağrılır).

        L3 veya monthly_paused durumunu onaylayıp sistemi sıfırlar.
        v5.8/CEO-FAZ1: Başarısız kapanış ticket'ları varsa onay REDDEDİLİR.

        Args:
            user: Onayı veren kullanıcı.

        Returns:
            True ise onay başarılı.
        """
        if self._kill_switch_level == KILL_SWITCH_NONE:
            return False

        # v5.8/CEO-FAZ1: Kapatılamayan pozisyon varsa onay kabul edilmez
        if self._last_l3_failed_tickets:
            logger.critical(
                f"Kill-switch onay REDDEDİLDİ — {len(self._last_l3_failed_tickets)} "
                f"pozisyon hâlâ açık: {self._last_l3_failed_tickets}. "
                f"Önce bu pozisyonlar manuel kapatılmalı."
            )
            self._db.insert_event(
                event_type="L3_ACK_BLOCKED",
                severity="CRITICAL",
                message=(
                    f"Kill-switch onayı reddedildi: {len(self._last_l3_failed_tickets)} "
                    f"kapatılamayan pozisyon mevcut — {self._last_l3_failed_tickets}"
                ),
            )
            return False

        self._db.insert_intervention(
            action=f"kill_switch_ack_L{self._kill_switch_level}",
            reason=self._kill_switch_details.get("message", ""),
            user=user,
        )

        self._risk_state["monthly_paused"] = False
        self._clear_kill_switch(f"Manuel onay by {user}")
        return True

    def report_unprotected_position(self, symbol: str, ticket: int) -> None:
        """v5.8/CEO-FAZ1: Korumasız pozisyon bildir (OĞUL → BABA).

        SL/TP eklenememiş ve kapatılamamış bir pozisyon oluştuğunda
        çağrılır. can_trade otomatik False olur.

        Args:
            symbol: Korumasız pozisyon sembolü.
            ticket: MT5 pozisyon ticket'ı.
        """
        entry = {"symbol": symbol, "ticket": ticket, "time": datetime.now().isoformat()}
        self._unprotected_positions.append(entry)
        logger.critical(
            f"KORUMASIZ POZİSYON RAPOR EDİLDİ: {symbol} ticket={ticket} "
            f"— Yeni işlem açma DURDURULDU. Toplam: {len(self._unprotected_positions)}"
        )
        self._db.insert_event(
            event_type="UNPROTECTED_POSITION",
            severity="CRITICAL",
            message=f"Korumasız pozisyon: {symbol} ticket={ticket} — yeni işlem yasak",
        )

    def clear_unprotected_positions(self, user: str = "operator") -> list[dict]:
        """v5.8/CEO-FAZ1: Korumasız pozisyon listesini temizle.

        Kullanıcı pozisyonlara manuel SL/TP ekledikten veya kapattıktan
        sonra çağrılarak yeni işlem açma izni verilir.

        Args:
            user: Temizlemeyi onaylayan kullanıcı.

        Returns:
            Temizlenen pozisyon listesi.
        """
        cleared = list(self._unprotected_positions)
        if cleared:
            logger.warning(
                f"Korumasız pozisyon listesi temizlendi by {user}: {cleared}"
            )
            self._db.insert_intervention(
                action="clear_unprotected",
                reason=f"Pozisyonlar: {cleared}",
                user=user,
            )
            self._unprotected_positions = []
        return cleared

    def clear_failed_tickets(self, user: str = "operator") -> list[int]:
        """v5.8/CEO-FAZ1: Kapatılamayan pozisyon listesini temizle.

        Kullanıcı pozisyonları MT5'ten manuel kapattıktan sonra
        bu metod çağrılarak L3 onayının önü açılır.

        Args:
            user: Temizlemeyi onaylayan kullanıcı.

        Returns:
            Temizlenen ticket listesi.
        """
        cleared = list(self._last_l3_failed_tickets)
        if cleared:
            logger.warning(
                f"Başarısız ticket listesi temizlendi by {user}: {cleared}"
            )
            self._db.insert_intervention(
                action="clear_failed_tickets",
                reason=f"Tickets: {cleared}",
                user=user,
            )
            self._last_l3_failed_tickets = []
        return cleared

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
        self._log_kill_event(
            f"L1 kontrat durdurma: {symbol} — {reason}", "WARNING", "LEVEL_1",
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
        """Akıllı pozisyon kapatma (L3 için).

        Rapor AÇIK #6 düzeltmesi: Önce zarardaki pozisyonları kapatır,
        ardından drawdown hâlâ eşik üstündeyse kârdakileri de kapatır.

        v5.4.1 ekleme: Başarısız kapatımlar için agresif retry (5 deneme, 2sn
        aralık) + market order fallback + acil uyarı.

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

        if not positions:
            logger.warning("close_all_positions: Pozisyon listesi boş/alınamadı")
            return failed_tickets

        # Pozisyonları kâr/zarar durumuna göre ayır
        losing = [p for p in positions if p.get("profit", 0.0) < 0]
        winning = [p for p in positions if p.get("profit", 0.0) >= 0]

        logger.info(
            f"L3 akıllı kapatma: {len(losing)} zararda, "
            f"{len(winning)} kârda ({reason})"
        )

        CLOSE_MAX_RETRIES = 5  # v5.4.1: 3'ten 5'e çıkarıldı
        closed_count = 0

        # 1) Önce zarardakileri kapat
        for pos in losing:
            closed, failed = self._try_close_position(
                pos, reason, CLOSE_MAX_RETRIES
            )
            closed_count += closed
            failed_tickets.extend(failed)

        # 2) Zarardakiler kapandıktan sonra drawdown hâlâ eşik üstündeyse
        #    kârdakileri de kapat
        if winning and self._still_above_hard_drawdown():
            logger.warning(
                f"Zarardakiler kapatıldı ama drawdown hâlâ eşik üstünde "
                f"— {len(winning)} kârdaki pozisyon da kapatılıyor"
            )
            for pos in winning:
                closed, failed = self._try_close_position(
                    pos, reason, CLOSE_MAX_RETRIES
                )
                closed_count += closed
                failed_tickets.extend(failed)
        elif winning:
            logger.info(
                f"Zarardakiler kapatıldı, drawdown eşik altına düştü "
                f"— {len(winning)} kârdaki pozisyon korundu"
            )

        # v5.4.1: Başarısız kapatımlar için agresif ikinci tur retry
        if failed_tickets:
            logger.critical(
                f"L3 ilk tur başarısız: {len(failed_tickets)} pozisyon açık kaldı "
                f"— agresif retry başlatılıyor (5 deneme, 2sn aralık)"
            )
            import time as _time
            still_failed: list[int] = []
            for ticket in failed_tickets:
                recovered = False
                for retry in range(1, 6):
                    _time.sleep(2)  # 2sn bekleme — piyasa emri için zaman ver
                    try:
                        result = self._mt5.close_position(ticket)
                    except Exception:
                        result = None
                    if result:
                        logger.info(
                            f"L3 agresif retry başarılı: ticket={ticket} "
                            f"(deneme {retry}/5)"
                        )
                        closed_count += 1
                        recovered = True
                        break
                    logger.warning(
                        f"L3 agresif retry {retry}/5 başarısız: ticket={ticket}"
                    )
                if not recovered:
                    still_failed.append(ticket)
                    logger.critical(
                        f"L3 KRİTİK: ticket={ticket} 10 denemede kapatılamadı! "
                        f"MANUEL MÜDAHALE GEREKLİ!"
                    )
            failed_tickets = still_failed

        if closed_count > 0:
            self._log_kill_event(
                f"{closed_count} pozisyon kapatıldı ({reason})",
                "CRITICAL", "positions_closed",
            )
        if failed_tickets:
            self._log_kill_event(
                f"KRİTİK: {len(failed_tickets)} pozisyon 10 denemede "
                f"kapatılamadı — MANUEL MÜDAHALE GEREKLİ: {failed_tickets}",
                "CRITICAL", "positions_close_failed_final",
            )
            # v5.4.1: Event bus üzerinden UI'a acil uyarı gönder
            try:
                from engine.event_bus import emit as _emit
                _emit("l3_close_failed", {
                    "failed_tickets": failed_tickets,
                    "reason": reason,
                    "message": f"{len(failed_tickets)} pozisyon kapatılamadı — MANUEL MÜDAHALE GEREKLİ",
                })
            except Exception:
                pass
        return failed_tickets

    def _close_ogul_and_hybrid(self, reason: str) -> list[int]:
        """L2 kayıp kapanışı — OĞUL ve H-Engine pozisyonları (v14.1).

        Manuel ve yetim (orphan) pozisyonlara dokunmaz.
        Tek merkezi risk kapanışı — OĞUL'dan BABA'ya taşınan sorumluluk.

        Args:
            reason: Kapanış nedeni (event log için).

        Returns:
            Kapatılamayan ticket listesi.
        """
        failed_tickets: list[int] = []
        if self._mt5 is None:
            logger.error(f"L2 kapanış — MT5 bağlantısı yok ({reason})")
            return failed_tickets

        # 1) H-Engine hibrit pozisyonlarını kapat (emirler + pozisyonlar)
        h_eng = getattr(self, "h_engine", None)
        if h_eng is not None:
            try:
                h_failed = h_eng.force_close_all(reason)
                if h_failed:
                    logger.error(
                        f"L2 ({reason}) h_engine kapatma başarısız: {h_failed}"
                    )
                    failed_tickets.extend(h_failed)
            except Exception as exc:
                logger.error(f"L2 ({reason}) h_engine.force_close_all hatası: {exc}")

        # 2) OĞUL active_trades FILLED pozisyonları (yetim HARIÇ)
        og = getattr(self, "ogul", None)
        if og is None or not getattr(og, "active_trades", None):
            logger.info(f"L2 ({reason}) — OĞUL pozisyon yok")
            return failed_tickets

        closed_count = 0
        for symbol in list(og.active_trades):
            trade = og.active_trades.get(symbol)
            if trade is None:
                continue
            if getattr(trade, "orphan", False):
                continue
            state = getattr(trade, "state", None)
            state_name = state.name if state is not None and hasattr(state, "name") else str(state)
            if state_name != "FILLED":
                continue
            ticket = getattr(trade, "ticket", 0)
            if not ticket:
                continue
            try:
                result = self._mt5.close_position(ticket)
                if result:
                    closed_count += 1
                    try:
                        og._handle_closed_trade(symbol, trade, reason.lower())
                    except Exception:
                        pass
                else:
                    failed_tickets.append(ticket)
            except Exception as exc:
                logger.error(
                    f"L2 ({reason}) OĞUL kapatma hatası [{symbol}] ticket={ticket}: {exc}"
                )
                failed_tickets.append(ticket)

        logger.warning(
            f"L2 ({reason}) kapanış tamamlandı: "
            f"{closed_count} OĞUL pozisyonu kapatıldı, {len(failed_tickets)} başarısız"
        )
        if closed_count > 0:
            self._log_kill_event(
                f"{closed_count} OĞUL pozisyonu kapatıldı ({reason})",
                "CRITICAL", "positions_closed_l2",
            )
        return failed_tickets

    def _try_close_position(
        self, pos: dict, reason: str, max_retries: int
    ) -> tuple[int, list[int]]:
        """Tek pozisyonu kapatmayı dene.

        v5.4.1: Denemeler arasına 1sn bekleme eklendi.

        Returns:
            (kapatılan_sayı, başarısız_ticket_listesi)
        """
        import time as _time
        ticket = pos.get("ticket")
        if not ticket:
            return 0, []
        for attempt in range(1, max_retries + 1):
            try:
                result = self._mt5.close_position(ticket)
            except Exception as exc:
                logger.error(
                    f"close_position hatası ticket={ticket} "
                    f"(deneme {attempt}/{max_retries}): {exc}"
                )
                result = None
            if result:
                logger.info(
                    f"Pozisyon kapatıldı: {ticket} ({reason}) "
                    f"deneme {attempt}/{max_retries}"
                )
                return 1, []
            logger.warning(
                f"Kapanış denemesi {attempt}/{max_retries} "
                f"başarısız: ticket={ticket}"
            )
            if attempt < max_retries:
                _time.sleep(1)  # v5.4.1: Denemeler arası 1sn bekleme
        logger.error(
            f"Pozisyon {max_retries} denemede kapatılamadı: ticket={ticket}"
        )
        return 0, [ticket]

    def _still_above_hard_drawdown(self) -> bool:
        """Zarardaki pozisyonlar kapatıldıktan sonra drawdown kontrolü."""
        try:
            snap = self._db.get_latest_risk_snapshot()
            if not snap:
                return True  # Veri yoksa güvenli tarafta kal
            equity = snap.get("equity", 0.0)
            peak = self._risk_state.get("peak_equity", equity)
            if peak <= 0:
                return True
            dd = (peak - equity) / peak
            hard_limit = self._risk_state.get("hard_drawdown", 0.15)
            return dd >= hard_limit
        except Exception:
            return True  # Hata durumunda güvenli tarafta kal

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

        # Manuel pozisyon ticket'ları — fake sinyalden muaf
        manual_tickets: set[int] = set()
        if self.manuel_motor:
            for t in self.manuel_motor.active_trades.values():
                if t.ticket:
                    manual_tickets.add(t.ticket)

        results: list[FakeAnalysis] = []

        for pos in positions:
            symbol = pos.get("symbol", "")
            direction = pos.get("type", "")
            ticket = pos.get("ticket", 0)

            if not symbol or not direction:
                continue

            # Manuel pozisyonları atla — kullanıcı açar, kullanıcı kapatır
            if ticket in manual_tickets:
                logger.debug(
                    f"Fake analiz: {symbol} ticket={ticket} manuel — atlanıyor"
                )
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

            elif analysis.total_score >= FAKE_SCORE_THRESHOLD - 1:
                # v14: skor 5 → uyarı gönder, kapatma yapma
                logger.warning(
                    f"FAKE UYARI [{symbol}] ticket={ticket}: "
                    f"skor={analysis.total_score}/{FAKE_SCORE_THRESHOLD} "
                    f"— İZLEMEDE (kapatma eşiğine yakın)"
                )
                self._db.insert_event(
                    event_type="FAKE_WARNING",
                    message=(
                        f"Fake uyarı: {symbol} {direction} ticket={ticket} "
                        f"skor={analysis.total_score} — izlemede"
                    ),
                    severity="INFO",
                    action="monitoring",
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
        buf = self._spread_history.get(symbol)
        if buf is None or len(buf) < 5:
            return FakeLayerResult(
                "spread", False, FAKE_WEIGHT_SPREAD, 0,
                "yetersiz spread verisi",
            )
        history = list(buf)  # deque → list atomik snapshot

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
                    _cd_hours = self._config.get("risk.cooldown_hours", 4)
                    end_time = triggered + timedelta(hours=_cd_hours)
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
        """Mevcut spread / ortalama spread (thread-safe snapshot)."""
        buf = self._spread_history.get(symbol)
        if buf is None or len(buf) < 5:
            return 1.0
        snapshot = list(buf)  # deque → list atomik snapshot
        current = snapshot[-1]
        avg = float(np.mean(snapshot[:-1]))
        return current / avg if avg > 0 else 1.0

    def _update_spread_history(self, pipeline) -> None:
        """Son tick spread'lerini ring buffer'a ekle (deque ile otomatik trim)."""
        for symbol in WATCHED_SYMBOLS:
            tick = pipeline.latest_ticks.get(symbol)
            if tick is None:
                continue
            self._spread_history[symbol].append(tick.spread)

    def _update_usdtry_history(self) -> None:
        """USD/TRY fiyat geçmişini MT5'ten güncelle."""
        if self._mt5 is None:
            return
        try:
            tick = self._mt5.get_tick("USDTRY")
        except Exception as exc:
            logger.error(f"get_tick hatası [USDTRY]: {exc}")
            return
        if tick is not None and tick.bid > 0:
            self._usdtry_history.append(tick.bid)

    def _usdtry_5m_move_pct(self) -> float:
        """USD/TRY son ~5dk hareket yüzdesi."""
        if len(self._usdtry_history) < 2:
            return 0.0
        first = self._usdtry_history[0]
        last  = self._usdtry_history[-1]
        if first <= 0 or last <= 0:
            return 0.0
        return abs(last - first) / first * 100


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
