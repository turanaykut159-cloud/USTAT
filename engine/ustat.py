"""ÜSTAT — Sistemin beyni, strateji yönetimi ve raporlama (v13.0).

v13.0 ÜSTAT görevleri:
    1. Olay/karar kaydı — BABA ve OĞUL davranışlarını izleme
    2. "Kim hata yaptı?" ataması — Hata sorumluluğu (BABA/OĞUL)
    3. Risk kaçırma raporu — BABA müdahale etmedi mi?
    4. Açılamayan işlem raporu — Top 5'te fırsat kaçırıldı mı?
    5. Ertesi gün analizi — Kapanan işlemlerin detaylı analizi
    6. Geçmiş kategorizasyonu — Çok boyutlu sınıflandırma (API katmanında)
    7. Strateji havuzu — Dönem parametreleri üretimi
    8. Kontrat tanıtımı — OĞUL'a kontrat profili iletimi
    9. Regülasyon akışı — Parametre düzeltme önerisi

Kritik kurallar:
    - ÜSTAT işlem AÇMAZ ve KAPATMAZ
    - BABA/OĞUL referansları sadece OKUMA amaçlı kullanılır
    - Top 5 listesi ÜSTAT tarafından ÜRETİLMEZ (v13.0: OĞUL görevi)
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, date, timedelta
from typing import Any

from engine.config import Config
from engine.database import Database
from engine.logger import get_logger

logger = get_logger(__name__)


# ── Strateji havuzu dönem parametreleri ──────────────────────────────
# Her dönem tipi için OĞUL'un kullanabileceği parametre setleri.
# ÜSTAT rejime göre aktif seti belirler, OĞUL bunu okuyabilir.

STRATEGY_PROFILES: dict[str, dict[str, Any]] = {
    "volatil": {
        "name": "Volatil Piyasa",
        "market_type": "volatil",
        "parameters": {
            "sl_atr_mult": 1.2,
            "tp_atr_mult": 1.5,
            "lot_scale": 0.7,
            "max_hold_minutes": 240,
            "trailing_start_atr": 0.8,
            "breakeven_atr": 0.5,
            "signal_threshold": 65,
        },
    },
    "duragan": {
        "name": "Durağan / Yatay Piyasa",
        "market_type": "duragan",
        "parameters": {
            "sl_atr_mult": 2.0,
            "tp_atr_mult": 1.8,
            "lot_scale": 1.0,
            "max_hold_minutes": 480,
            "trailing_start_atr": 1.2,
            "breakeven_atr": 0.8,
            "signal_threshold": 55,
        },
    },
    "patlama": {
        "name": "Patlama / Breakout Dönemi",
        "market_type": "patlama",
        "parameters": {
            "sl_atr_mult": 1.5,
            "tp_atr_mult": 3.0,
            "lot_scale": 0.8,
            "max_hold_minutes": 360,
            "trailing_start_atr": 1.0,
            "breakeven_atr": 0.6,
            "signal_threshold": 60,
        },
    },
    "trend": {
        "name": "Trend Piyasası",
        "market_type": "trend",
        "parameters": {
            "sl_atr_mult": 1.8,
            "tp_atr_mult": 2.5,
            "lot_scale": 1.0,
            "max_hold_minutes": 480,
            "trailing_start_atr": 1.0,
            "breakeven_atr": 0.7,
            "signal_threshold": 50,
        },
    },
}

# Ertesi gün analizi puanlama ağırlıkları
SCORING_WEIGHTS = {
    "signal_search": 0.25,
    "trade_management": 0.30,
    "profit_capture": 0.25,
    "risk_compliance": 0.20,
}

# Anlamlı zarar eşiği (TL) — bunun altındaki zararlar atama yapılmaz
ATTRIBUTION_MIN_LOSS = 100.0

# Maksimum tutulacak hata ataması sayısı
MAX_ATTRIBUTIONS = 50

# Strateji havuzu güncelleme aralığı (saniye)
STRATEGY_POOL_INTERVAL_SEC = 1800  # 30 dakika

# Dedup cache TTL (saniye)
DEDUP_CACHE_TTL_SEC = 3600  # 1 saat


class Ustat:
    """Strateji yöneticisi — sistemin beyni.

    v13.0: ÜSTAT raporlama, hata ataması, strateji havuzu,
    kontrat tanıtımı ve regülasyon önerisi üretir.
    İşlem AÇMAZ ve KAPATMAZ.

    Her cycle'da ``run_cycle(baba, ogul)`` çağrılır.
    """

    def __init__(self, config: Config, db: Database) -> None:
        self._config = config
        self._db = db

        # ── Zamanlama kontrolleri ─────────────────────────────────
        self._last_daily_report: datetime | None = None
        self._last_next_day_analysis: date | None = None
        self._last_strategy_pool_update: datetime | None = None
        self._last_contract_profile_update: date | None = None

        # ── Önceki cycle state (değişiklik tespiti) ──────────────
        self._prev_regime: str = ""
        self._prev_kill_level: int = 0
        self._prev_active_trades: set[str] = set()
        self._prev_warning_count: int = 0

        # ── Rapor verileri (API tarafından okunur) ───────────────
        self.error_attributions: list[dict[str, Any]] = []
        self.next_day_analyses: list[dict[str, Any]] = []
        self.regulation_suggestions: list[dict[str, Any]] = []
        self.strategy_pool: dict[str, Any] = {
            "current_regime": "",
            "active_profile": "",
            "profiles": list(STRATEGY_PROFILES.values()),
        }
        self.contract_profiles: dict[str, dict[str, Any]] = {}

        # ── Dedup cache (tekrarlayan olay filtreleme) ────────────
        self._dedup_cache: dict[str, datetime] = {}

        # ── Persistence: DB'den önceki oturum verilerini yükle ─────
        self._load_persisted_state()

    # ════════════════════════════════════════════════════════════════
    #  ANA CYCLE
    # ════════════════════════════════════════════════════════════════

    def run_cycle(self, baba: Any, ogul: Any) -> None:
        """ÜSTAT brain cycle — olay topla, raporla, strateji güncelle.

        Her 10 sn'de main_loop tarafından çağrılır.
        BABA/OĞUL referansları SADECE OKUMA amaçlı kullanılır.

        Args:
            baba: Risk yöneticisi instance (okuma).
            ogul: Sinyal üretici instance (okuma).
        """
        now = datetime.now()
        self._last_run_time: str = now.isoformat()

        # 1. Olay/karar kaydı — her cycle
        self._track_events(baba, ogul, now)

        # 2. Kim hata yaptı + risk kaçırma — her cycle
        self._check_error_attribution(baba, ogul, now)

        # 3. Açılamayan işlem raporu — her cycle
        self._check_unopened_trades(baba, ogul, now)

        # 4. Strateji havuzu güncelleme — 30 dk'da bir
        if self._should_update_strategy_pool(now):
            self._update_strategy_pool(baba, now)

        # 5. Kontrat tanıtımı güncelleme — günde 1 kez
        if self._should_update_contract_profiles(now):
            self._update_contract_profiles(now)

        # 6. Ertesi gün analizi — sabah 09:30'da
        if self._should_next_day_analysis(now):
            self._run_next_day_analysis(now)

        # 7. Günlük rapor + regülasyon önerileri — 18:00'da
        if self._should_daily_report(now):
            self._generate_daily_report(baba, ogul, now)
            self._generate_regulation_suggestions(now)
            self._apply_regulation_feedback()

        # 8. Persistence — her cycle sonunda DB'ye kaydet
        self._save_persisted_state()

    # ════════════════════════════════════════════════════════════════
    #  1. OLAY/KARAR KAYDI
    # ════════════════════════════════════════════════════════════════

    def _track_events(self, baba: Any, ogul: Any, now: datetime) -> None:
        """BABA ve OĞUL davranışlarını izle, değişiklikleri kaydet.

        Her cycle'da çağrılır. Rejim değişikliği, kill-switch değişikliği,
        işlem açılması/kapanması, uyarı artışı gibi olayları tespit eder.

        Args:
            baba: BABA instance (okuma).
            ogul: OĞUL instance (okuma).
            now: Şu anki zaman.
        """
        self._track_regime_change(baba)
        self._track_kill_switch_change(baba)
        self._track_trade_changes(ogul)
        self._track_warning_changes(baba)

    def _track_regime_change(self, baba: Any) -> None:
        """Rejim değişikliğini tespit et ve kaydet."""
        current_regime = ""
        if baba and hasattr(baba, "current_regime") and baba.current_regime:
            current_regime = baba.current_regime.regime_type.value

        if current_regime and current_regime != self._prev_regime:
            if self._prev_regime:  # İlk cycle'da kaydetme
                self._log_event(
                    "REGIME_CHANGE",
                    f"Rejim değişti: {self._prev_regime} → {current_regime}",
                    severity="WARNING",
                )
            self._prev_regime = current_regime

    def _track_kill_switch_change(self, baba: Any) -> None:
        """Kill-switch seviye değişikliğini tespit et ve kaydet."""
        kill_level = getattr(baba, "_kill_switch_level", 0) if baba else 0

        if kill_level != self._prev_kill_level:
            if kill_level > self._prev_kill_level:
                details = getattr(baba, "_kill_switch_details", {})
                reason = details.get("reason", "bilinmiyor")
                self._log_event(
                    "KILL_SWITCH",
                    f"Kill-switch L{kill_level} aktif: {reason}",
                    severity="CRITICAL",
                )
            else:
                self._log_event(
                    "KILL_SWITCH",
                    f"Kill-switch L{self._prev_kill_level} → L{kill_level} (sıfırlandı)",
                    severity="INFO",
                )
            self._prev_kill_level = kill_level

    def _track_trade_changes(self, ogul: Any) -> None:
        """İşlem açılma/kapanma değişikliklerini tespit et ve kaydet."""
        current_trades: set[str] = set()
        if ogul and hasattr(ogul, "active_trades"):
            current_trades = set(ogul.active_trades.keys())

        opened = current_trades - self._prev_active_trades
        closed = self._prev_active_trades - current_trades

        for symbol in opened:
            trade = ogul.active_trades.get(symbol)
            if trade:
                strategy = getattr(trade, "strategy", "bilinmiyor")
                direction = getattr(trade, "direction", "?")
                self._log_event(
                    "TRADE_OPENED",
                    f"İşlem açıldı: {symbol} {direction} (strateji: {strategy})",
                    severity="INFO",
                )

        for symbol in closed:
            self._log_event(
                "TRADE_CLOSED",
                f"İşlem kapandı: {symbol}",
                severity="INFO",
            )

        self._prev_active_trades = current_trades

    def _track_warning_changes(self, baba: Any) -> None:
        """Uyarı sayısı artışını tespit et ve kaydet."""
        warning_count = len(getattr(baba, "active_warnings", [])) if baba else 0

        if warning_count > self._prev_warning_count and warning_count > 0:
            warnings = baba.active_warnings
            symbols = {w.symbol for w in warnings if hasattr(w, "symbol")}
            self._log_event(
                "WARNING_INCREASE",
                f"Aktif uyarı: {self._prev_warning_count} → {warning_count} "
                f"(semboller: {', '.join(sorted(symbols))})",
                severity="WARNING",
            )

        self._prev_warning_count = warning_count

    # ════════════════════════════════════════════════════════════════
    #  2. KİM HATA YAPTI  +  3. RİSK KAÇIRMA RAPORU
    # ════════════════════════════════════════════════════════════════

    def _check_error_attribution(
        self, baba: Any, ogul: Any, now: datetime,
    ) -> None:
        """Hata sorumluluğu ataması ve risk kaçırma kontrolü.

        Son 24 saatteki zararlı kapanan işlemleri analiz eder.

        BABA hatası: Risk vardı (uyarı/drawdown) ama müdahale etmedi.
        OĞUL hatası: Piyasa tersine döndü ama kapatmadı / sinyal kuralları uyulmadı.

        Args:
            baba: BABA instance (okuma).
            ogul: OĞUL instance (okuma).
            now: Şu anki zaman.
        """
        if not self._db:
            return

        since_str = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

        try:
            trades = self._db.get_trades(since=since_str, limit=50, closed_only=True)
        except Exception as exc:
            logger.warning(f"Hata ataması trade çekme hatası: {exc}")
            return

        losing_trades = [t for t in trades if (t.get("pnl") or 0) < 0]
        if not losing_trades:
            return

        # Risk olaylarını çek (hata tespiti için)
        try:
            events = self._db.get_events(limit=200)
        except Exception:
            events = []

        risk_event_types = (
            "KILL_SWITCH", "COOLDOWN", "RISK_LIMIT",
            "DRAWDOWN_WARNING", "SPREAD_SPIKE", "RISK_ALLOWED",
        )
        risk_events = [
            e for e in events
            if e.get("type") in risk_event_types
        ]

        attributed_ids = {ea.get("trade_id") for ea in self.error_attributions}

        for trade in losing_trades:
            trade_id = trade.get("id", 0)
            if trade_id in attributed_ids:
                continue

            attribution = self._determine_fault(trade, risk_events)
            if attribution:
                self.error_attributions.append(attribution)
                self._log_event(
                    "ERROR_ATTRIBUTION",
                    f"Hata ataması: trade#{trade_id} {trade.get('symbol', '')} → "
                    f"{attribution['responsible']}: {attribution['description']}",
                    severity="WARNING",
                )

        # Listeyi sınırla
        if len(self.error_attributions) > MAX_ATTRIBUTIONS:
            self.error_attributions = self.error_attributions[-MAX_ATTRIBUTIONS:]

    def _determine_fault(
        self,
        trade: dict[str, Any],
        risk_events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Tek bir zararlı işlem için hata sorumluluğunu belirle.

        Kurallar (v13.0 spesifikasyonundan):
          - Risk varken BABA müdahale etmediyse → hata BABA'ya.
          - Piyasa tersine dönüp OĞUL kapatmadıysa → hata OĞUL'a.

        Args:
            trade: İşlem kaydı dict.
            risk_events: Son risk olayları listesi.

        Returns:
            Hata atama dict'i veya None.
        """
        trade_id = trade.get("id", 0)
        symbol = trade.get("symbol", "")
        pnl = trade.get("pnl", 0.0) or 0.0
        entry_time = trade.get("entry_time", "")
        exit_time = trade.get("exit_time", "")
        exit_reason = trade.get("exit_reason", "")

        # İşlem süresince risk olayı var mıydı?
        risk_during_trade = [
            e for e in risk_events
            if entry_time and exit_time
            and entry_time <= e.get("timestamp", "") <= exit_time
        ]

        # 1. BABA hatası: Risk sinyali vardı ama pozisyon kapatılmadı
        safe_exits = ("RISK_CLOSE", "KILL_SWITCH", "BABA_CLOSE")
        if risk_during_trade and exit_reason not in safe_exits:
            return {
                "trade_id": trade_id,
                "error_type": "RISK_MISS",
                "responsible": "BABA",
                "description": (
                    f"{symbol}: İşlem süresince {len(risk_during_trade)} risk olayı "
                    f"tespit edildi ancak BABA müdahale etmedi. "
                    f"Zarar: {pnl:.2f} TL"
                ),
            }

        # 2. OĞUL hatası: SL/timeout/expiry ile kapandı (sinyal çıkışı yok)
        ogul_fault_exits = ("SL_HIT", "TIMEOUT", "EXPIRY")
        if exit_reason in ogul_fault_exits:
            return {
                "trade_id": trade_id,
                "error_type": "PROFIT_MISS",
                "responsible": "OGUL",
                "description": (
                    f"{symbol}: İşlem {exit_reason} ile kapandı. "
                    f"OĞUL sinyal kurallarına göre daha erken çıkabilirdi. "
                    f"Zarar: {pnl:.2f} TL"
                ),
            }

        # 3. Anlamlı zarar ama neden belirsiz → genel kayıt
        if abs(pnl) >= ATTRIBUTION_MIN_LOSS:
            return {
                "trade_id": trade_id,
                "error_type": "GENERAL_LOSS",
                "responsible": "OGUL",
                "description": (
                    f"{symbol}: Zararlı işlem ({exit_reason or 'bilinmiyor'}). "
                    f"Zarar: {pnl:.2f} TL"
                ),
            }

        return None

    # ════════════════════════════════════════════════════════════════
    #  4. AÇILAMAYAN İŞLEM RAPORU
    # ════════════════════════════════════════════════════════════════

    def _check_unopened_trades(
        self, baba: Any, ogul: Any, now: datetime,
    ) -> None:
        """Top 5'teki kontratlar için açılamayan fırsat kontrolü.

        Top 5 listesinde kontrat var, OĞUL sinyal üretti ama işlem
        açılmadıysa → neden açılmadı ve parametre düzeltme önerisi.

        Öğle arası ve işlem saatleri dışında çalışmaz (gereksiz log kirliliği).

        Args:
            baba: BABA instance (okuma).
            ogul: OĞUL instance (okuma).
            now: Şu anki zaman.
        """
        if not ogul:
            return

        # İşlem saatleri dışında UNOPENED kontrolü yapma
        from datetime import time as _time
        current_time = now.time()
        if current_time < _time(9, 45) or current_time > _time(17, 45):
            return  # işlem saatleri dışı

        top5 = getattr(ogul, "_current_top5", [])
        active_symbols = set(getattr(ogul, "active_trades", {}).keys())
        last_signals = getattr(ogul, "last_signals", {})

        for symbol in top5:
            if symbol in active_symbols:
                continue

            signal = last_signals.get(symbol, "BEKLE")
            if signal not in ("BUY", "SELL"):
                continue

            reason = self._find_block_reason(symbol, baba)
            if reason:
                self._log_event_deduplicated(
                    "UNOPENED_TRADE",
                    f"Açılamayan işlem: {symbol} sinyali {signal} "
                    f"ancak işlem açılamadı. Neden: {reason}",
                    severity="INFO",
                    dedup_key=f"UNOPENED_{symbol}",
                    dedup_minutes=30,
                )

    def _find_block_reason(self, symbol: str, baba: Any) -> str:
        """Bir sembolün neden işleme alınamadığını belirle.

        BABA'nın risk state'i, kill-switch durumu, cooldown, günlük
        limit gibi nedenleri kontrol eder.

        Args:
            symbol: Kontrat sembolü.
            baba: BABA instance (okuma).

        Returns:
            Engel nedeni açıklaması.
        """
        if not baba:
            return "BABA erişilemiyor"

        reasons: list[str] = []

        # Kill-switch kontrolü
        kill_level = getattr(baba, "_kill_switch_level", 0)
        if kill_level >= 2:
            reasons.append(f"Kill-switch L{kill_level} aktif")

        # Sembol bazlı kill-switch
        killed_symbols = getattr(baba, "_killed_symbols", set())
        if symbol in killed_symbols:
            reasons.append(f"{symbol} L1 kill-switch")

        # Risk state kontrolü
        risk_state = getattr(baba, "_risk_state", {})
        if risk_state.get("cooldown_until"):
            reasons.append("Cooldown aktif")
        if risk_state.get("monthly_paused"):
            reasons.append("Aylık limit aşıldı")

        # Günlük işlem limiti
        daily_count = risk_state.get("daily_trade_count", 0)
        max_daily = 5  # RiskParams default
        if daily_count >= max_daily:
            reasons.append(f"Günlük işlem limiti ({daily_count}/{max_daily})")

        # Üst üste kayıp (consecutive_losses) — cooldown tetiklememiş olsa bile bilgi ver
        consec = risk_state.get("consecutive_losses", 0)
        if consec >= 2:
            reasons.append(f"Üst üste {consec} kayıp")

        if not reasons:
            from datetime import time as _time
            now_t = datetime.now().time()
            if now_t < _time(9, 45) or now_t > _time(17, 45):
                reasons.append("İşlem saatleri dışı")
            else:
                reasons.append("M15 mum kapanışı bekleniyor veya sinyal eşiği karşılanmadı")

        return "; ".join(reasons)

    # ════════════════════════════════════════════════════════════════
    #  5. ERTESİ GÜN ANALİZİ
    # ════════════════════════════════════════════════════════════════

    def _should_next_day_analysis(self, now: datetime) -> bool:
        """Ertesi gün analizi zamanı geldi mi?

        Günde 1 kez, hafta içi. Saat kısıtlaması kaldırıldı —
        motor başlar başlamaz ilk döngüde çalışır.
        """
        today = now.date()
        if self._last_next_day_analysis == today:
            return False
        if today.weekday() >= 5:  # Hafta sonu
            return False
        return True

    def _run_next_day_analysis(self, now: datetime) -> None:
        """Önceki iş günü kapanan işlemlerin detaylı analizi.

        Her işlem için:
          - Potansiyel kâr tahmini
          - Kaçırılan kâr hesabı
          - Puanlama: sinyal arama, işlem yönetimi, kâr yakalama, risk uyumu

        Args:
            now: Şu anki zaman.
        """
        self._last_next_day_analysis = now.date()

        if not self._db:
            return

        # Önceki iş gününü bul
        yesterday = self._previous_business_day(now.date())
        since_str = yesterday.strftime("%Y-%m-%d")

        try:
            all_trades = self._db.get_trades(
                since=since_str, limit=100, closed_only=True,
            )
        except Exception as exc:
            logger.warning(f"Ertesi gün analizi trade çekme hatası: {exc}")
            return

        # Sadece o gün kapanan işlemleri filtrele
        yesterday_trades = [
            t for t in all_trades
            if t.get("exit_time", "")[:10] == since_str
        ]

        if not yesterday_trades:
            logger.info("[ÜSTAT] Ertesi gün analizi: Dün kapanan işlem yok.")
            return

        new_analyses: list[dict[str, Any]] = []
        for trade in yesterday_trades:
            analysis = self._analyze_single_trade(trade)
            if analysis:
                new_analyses.append(analysis)

        if new_analyses:
            self.next_day_analyses = new_analyses
            avg_score = sum(a["total_score"] for a in new_analyses) / len(new_analyses)
            logger.info(
                f"[ÜSTAT] Ertesi gün analizi: {len(new_analyses)} işlem analiz edildi."
            )
            self._log_event(
                "NEXT_DAY_ANALYSIS",
                f"Ertesi gün analizi tamamlandı: {len(new_analyses)} işlem, "
                f"ortalama skor: {avg_score:.1f}/100",
                severity="INFO",
            )

    def _analyze_single_trade(self, trade: dict[str, Any]) -> dict[str, Any] | None:
        """Tek bir kapanan işlemin detaylı analizi.

        Args:
            trade: Kapanmış işlem kaydı.

        Returns:
            Analiz sonucu dict veya None (analiz yapılamadıysa).
        """
        trade_id = trade.get("id", 0)
        symbol = trade.get("symbol", "")
        pnl = trade.get("pnl", 0.0) or 0.0
        entry_price = trade.get("entry_price", 0.0) or 0.0
        exit_price = trade.get("exit_price", 0.0) or 0.0
        direction = trade.get("direction", "BUY")
        exit_reason = trade.get("exit_reason", "")
        lot = trade.get("lot", 1.0) or 1.0

        if not entry_price or not exit_price:
            return None

        # Potansiyel kâr tahmini (fiyat hareketinin ~1.5 katı)
        price_move = abs(exit_price - entry_price)
        potential_move = price_move * 1.5
        # VİOP kontrat çarpanı ile potansiyel TL
        potential_pnl = abs(potential_move * lot * 100)

        # Kaçırılan kâr
        if pnl > 0:
            missed_profit = max(0, potential_pnl - pnl)
        else:
            missed_profit = potential_pnl

        # Puanlama (her boyut 0-100)
        signal_score = self._score_signal_search(trade)
        management_score = self._score_trade_management(trade)
        profit_score = self._score_profit_capture(pnl, potential_pnl)
        risk_score = self._score_risk_compliance(trade)

        total_score = (
            signal_score * SCORING_WEIGHTS["signal_search"]
            + management_score * SCORING_WEIGHTS["trade_management"]
            + profit_score * SCORING_WEIGHTS["profit_capture"]
            + risk_score * SCORING_WEIGHTS["risk_compliance"]
        )

        # Özet metin
        summary_parts: list[str] = []
        if pnl > 0:
            summary_parts.append(f"Kârlı işlem (+{pnl:.2f} TL)")
        else:
            summary_parts.append(f"Zararlı işlem ({pnl:.2f} TL)")
        if missed_profit > 50:
            summary_parts.append(f"Kaçırılan kâr: {missed_profit:.2f} TL")
        summary_parts.append(f"Çıkış: {exit_reason or 'bilinmiyor'}")
        summary_parts.append(f"Skor: {total_score:.0f}/100")

        return {
            "trade_id": trade_id,
            "symbol": symbol,
            "actual_pnl": round(pnl, 2),
            "potential_pnl": round(potential_pnl, 2),
            "missed_profit": round(missed_profit, 2),
            "signal_score": round(signal_score, 1),
            "management_score": round(management_score, 1),
            "profit_score": round(profit_score, 1),
            "risk_score": round(risk_score, 1),
            "total_score": round(total_score, 1),
            "summary": ". ".join(summary_parts),
        }

    def _score_signal_search(self, trade: dict[str, Any]) -> float:
        """Sinyal arama kalitesini puanla (0-100).

        Strateji tanımlı mı, rejim uyumu var mı, sahte sinyal skoru ne?

        Args:
            trade: İşlem kaydı.

        Returns:
            0-100 arası skor.
        """
        score = 50.0
        strategy = trade.get("strategy", "")
        regime = trade.get("regime", "")

        # Strateji tanımlı mı?
        if strategy and strategy != "bilinmiyor":
            score += 20
        else:
            score -= 20

        # Rejim-strateji uyumu
        regime_match = {
            ("trend_follow", "TREND"): 15,
            ("mean_reversion", "RANGE"): 15,
            ("breakout", "VOLATILE"): 10,
            ("breakout", "OLAY"): 10,
        }
        score += regime_match.get((strategy, regime), 0)

        # Fake score varsa
        fake_score = trade.get("fake_score")
        if fake_score is not None:
            if fake_score <= 1:
                score += 15
            elif fake_score >= 3:
                score -= 25

        return max(0.0, min(100.0, score))

    def _score_trade_management(self, trade: dict[str, Any]) -> float:
        """İşlem yönetimini puanla (0-100).

        Çıkış nedeni kalitesi ve slippage kontrolü.

        Args:
            trade: İşlem kaydı.

        Returns:
            0-100 arası skor.
        """
        score = 60.0
        exit_reason = trade.get("exit_reason", "")

        exit_scores = {
            "TP_HIT": 20,
            "TRAILING_STOP": 20,
            "SIGNAL_EXIT": 20,
            "BREAKEVEN": 10,
            "SL_HIT": -10,
            "TIMEOUT": -20,
            "KILL_SWITCH": -5,
        }
        score += exit_scores.get(exit_reason, 0)

        slippage = abs(trade.get("slippage", 0.0) or 0.0)
        if slippage > 5:
            score -= 15
        elif slippage < 1:
            score += 10

        return max(0.0, min(100.0, score))

    def _score_profit_capture(self, actual_pnl: float, potential_pnl: float) -> float:
        """Kâr yakalama oranını puanla (0-100).

        Args:
            actual_pnl: Gerçekleşen K/Z.
            potential_pnl: Tahmini potansiyel kâr.

        Returns:
            0-100 arası skor.
        """
        if potential_pnl <= 0:
            return 50.0

        if actual_pnl > 0:
            capture_ratio = actual_pnl / potential_pnl
            return min(100.0, capture_ratio * 100)

        loss_ratio = abs(actual_pnl) / potential_pnl
        return max(0.0, 50 - loss_ratio * 50)

    def _score_risk_compliance(self, trade: dict[str, Any]) -> float:
        """Risk uyumunu puanla (0-100).

        SL kullanımı, zarar büyüklüğü, BABA müdahalesi.

        Args:
            trade: İşlem kaydı.

        Returns:
            0-100 arası skor.
        """
        score = 70.0
        pnl = trade.get("pnl", 0.0) or 0.0
        exit_reason = trade.get("exit_reason", "")

        # SL çalıştı = risk yönetimi uygulandı
        if exit_reason == "SL_HIT":
            score += 15

        # Büyük zarar cezası
        if pnl < -500:
            score -= 30
        elif pnl < -200:
            score -= 15

        # BABA müdahale zorunda kaldı
        if exit_reason in ("KILL_SWITCH", "RISK_CLOSE", "BABA_CLOSE"):
            score -= 10

        return max(0.0, min(100.0, score))

    # ════════════════════════════════════════════════════════════════
    #  6. STRATEJİ HAVUZU
    # ════════════════════════════════════════════════════════════════

    def _should_update_strategy_pool(self, now: datetime) -> bool:
        """Strateji havuzu güncelleme zamanı geldi mi? (30 dk'da bir)."""
        if self._last_strategy_pool_update is None:
            return True
        elapsed = (now - self._last_strategy_pool_update).total_seconds()
        return elapsed >= STRATEGY_POOL_INTERVAL_SEC

    def _update_strategy_pool(self, baba: Any, now: datetime) -> None:
        """Rejime göre aktif strateji profilini belirle.

        BABA'nın tespit ettiği rejim türüne göre uygun parametre
        setini seçer. OĞUL bu veriyi okuyabilir (DB/config).

        Args:
            baba: BABA instance (okuma — rejim bilgisi).
            now: Şu anki zaman.
        """
        self._last_strategy_pool_update = now

        current_regime = ""
        if baba and hasattr(baba, "current_regime") and baba.current_regime:
            current_regime = baba.current_regime.regime_type.value

        # Rejim → profil eşlemesi
        regime_to_profile = {
            "TREND": "trend",
            "RANGE": "duragan",
            "VOLATILE": "volatil",
            "OLAY": "patlama",
        }
        active_key = regime_to_profile.get(current_regime, "trend")

        self.strategy_pool = {
            "current_regime": current_regime,
            "active_profile": active_key,
            "profiles": [
                {
                    **profile,
                    "active": (key == active_key),
                }
                for key, profile in STRATEGY_PROFILES.items()
            ],
        }

        self._log_event_deduplicated(
            "STRATEGY_POOL",
            f"Strateji havuzu: rejim={current_regime}, aktif_profil={active_key}",
            severity="INFO",
            dedup_key="STRATEGY_POOL_UPDATE",
            dedup_minutes=30,
        )

    # ════════════════════════════════════════════════════════════════
    #  7. KONTRAT TANITIMI (OĞUL'A EĞİTİM)
    # ════════════════════════════════════════════════════════════════

    def _should_update_contract_profiles(self, now: datetime) -> bool:
        """Kontrat profili güncelleme zamanı geldi mi? (günde 1 kez, 10:00+)."""
        today = now.date()
        if self._last_contract_profile_update == today:
            return False
        return now.hour >= 10

    def _update_contract_profiles(self, now: datetime) -> None:
        """Kontrat bazlı davranış profilleri üret.

        Her kontrat için tipik hareket, volatilite, kâr/zarar dağılımı,
        yön tercihi ve strateji dağılımını hesaplar.
        OĞUL bu bilgiyi opsiyonel kullanabilir.

        Args:
            now: Şu anki zaman.
        """
        self._last_contract_profile_update = now.date()

        if not self._db:
            return

        since = (now - timedelta(days=90)).strftime("%Y-%m-%d")
        try:
            trades = self._db.get_trades(since=since, limit=5000, closed_only=True)
        except Exception as exc:
            logger.warning(f"Kontrat profili trade çekme hatası: {exc}")
            return

        # Sembol bazlı grupla
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for t in trades:
            sym = t.get("symbol", "")
            if sym:
                by_symbol.setdefault(sym, []).append(t)

        profiles: dict[str, dict[str, Any]] = {}
        for symbol, symbol_trades in by_symbol.items():
            pnls = [t.get("pnl", 0) or 0 for t in symbol_trades]
            if not pnls:
                continue

            wins = sum(1 for p in pnls if p > 0)
            total_pnl = sum(pnls)
            count = len(pnls)

            # Ortalama fiyat hareketi
            moves = []
            for t in symbol_trades:
                ep = t.get("entry_price", 0) or 0
                xp = t.get("exit_price", 0) or 0
                if ep and xp:
                    moves.append(abs(xp - ep))
            avg_move = sum(moves) / len(moves) if moves else 0

            # Volatilite (PnL std sapması)
            pnl_std = statistics.stdev(pnls) if len(pnls) > 1 else 0.0

            # Yön analizi
            buy_pnl = sum(
                t.get("pnl", 0) or 0 for t in symbol_trades
                if t.get("direction") == "BUY"
            )
            sell_pnl = sum(
                t.get("pnl", 0) or 0 for t in symbol_trades
                if t.get("direction") == "SELL"
            )
            buy_count = sum(
                1 for t in symbol_trades if t.get("direction") == "BUY"
            )
            sell_count = count - buy_count

            # Strateji dağılımı
            strategy_dist: dict[str, int] = {}
            for t in symbol_trades:
                s = t.get("strategy", "bilinmiyor")
                strategy_dist[s] = strategy_dist.get(s, 0) + 1

            profiles[symbol] = {
                "symbol": symbol,
                "trade_count": count,
                "win_rate": round(wins / count * 100, 1) if count else 0,
                "total_pnl": round(total_pnl, 2),
                "avg_pnl": round(total_pnl / count, 2) if count else 0,
                "avg_move": round(avg_move, 4),
                "volatility": round(pnl_std, 2),
                "best_pnl": round(max(pnls), 2),
                "worst_pnl": round(min(pnls), 2),
                "buy_count": buy_count,
                "sell_count": sell_count,
                "buy_pnl": round(buy_pnl, 2),
                "sell_pnl": round(sell_pnl, 2),
                "preferred_direction": "BUY" if buy_pnl >= sell_pnl else "SELL",
                "strategies": strategy_dist,
            }

        self.contract_profiles = profiles
        logger.info(
            f"[ÜSTAT] Kontrat profilleri güncellendi: {len(profiles)} kontrat."
        )

    # ════════════════════════════════════════════════════════════════
    #  8. REGÜLASYON AKIŞI
    # ════════════════════════════════════════════════════════════════

    def _generate_regulation_suggestions(self, now: datetime) -> None:
        """Hata atamalarına ve analizlere dayalı parametre önerileri üret.

        Rapor türüne göre hangi BABA/OĞUL parametrelerinin gözden
        geçirileceğini belirler.

        Args:
            now: Şu anki zaman.
        """
        suggestions: list[dict[str, Any]] = []

        # 1. BABA hataları → risk parametrelerini sorgula
        baba_errors = [
            ea for ea in self.error_attributions
            if ea.get("responsible") == "BABA"
        ]
        if len(baba_errors) >= 2:
            suggestions.append({
                "parameter": "max_daily_loss",
                "current_value": "0.018 (1.8%)",
                "suggested_value": "Gözden geçirilmeli",
                "reason": (
                    f"Son 24 saatte {len(baba_errors)} BABA hatası. "
                    f"Risk parametreleri yeterince koruyucu olmayabilir."
                ),
                "priority": "HIGH",
            })

        # 2. OĞUL hataları → sinyal parametrelerini sorgula
        ogul_errors = [
            ea for ea in self.error_attributions
            if ea.get("responsible") == "OGUL"
        ]
        if len(ogul_errors) >= 3:
            suggestions.append({
                "parameter": "signal_threshold",
                "current_value": "mevcut eşik",
                "suggested_value": "Artırılmalı",
                "reason": (
                    f"Son 24 saatte {len(ogul_errors)} OĞUL hatası. "
                    f"Sinyal eşiği veya çıkış kriterleri gözden geçirilmeli."
                ),
                "priority": "MEDIUM",
            })

        # 3. Düşük skorlu ertesi gün analizleri → işlem yönetimi
        low_score_analyses = [
            a for a in self.next_day_analyses
            if a.get("total_score", 100) < 40
        ]
        if low_score_analyses:
            avg_score = (
                sum(a["total_score"] for a in low_score_analyses)
                / len(low_score_analyses)
            )
            suggestions.append({
                "parameter": "trade_management",
                "current_value": f"Ortalama skor: {avg_score:.0f}/100",
                "suggested_value": "İşlem yönetimi iyileştirilmeli",
                "reason": (
                    f"{len(low_score_analyses)} işlem düşük skor aldı. "
                    f"Trailing stop, breakeven ve çıkış parametreleri "
                    f"gözden geçirilmeli."
                ),
                "priority": "MEDIUM",
            })

        # 4. Kontrat profillerinden düşük win-rate tespiti
        for sym, profile in self.contract_profiles.items():
            win_rate = profile.get("win_rate", 50)
            trade_count = profile.get("trade_count", 0)
            if trade_count >= 5 and win_rate < 30:
                suggestions.append({
                    "parameter": f"kontrat_filtre_{sym}",
                    "current_value": (
                        f"Win rate: %{win_rate:.0f} ({trade_count} işlem)"
                    ),
                    "suggested_value": "Top 5 skorlamasında cezalandırılmalı",
                    "reason": (
                        f"{sym} düşük win rate. "
                        f"Toplam K/Z: {profile.get('total_pnl', 0):.2f} TL"
                    ),
                    "priority": "LOW",
                })

        self.regulation_suggestions = suggestions
        if suggestions:
            logger.info(
                f"[ÜSTAT] Regülasyon önerileri: {len(suggestions)} öneri."
            )

    # ════════════════════════════════════════════════════════════════
    #  FEEDBACK LOOP — Regülasyon Önerilerini Parametrelere Yansıt
    # ════════════════════════════════════════════════════════════════

    def _apply_regulation_feedback(self) -> None:
        """Regülasyon önerilerini strateji havuzundaki parametrelere uygula.

        Güvenli mikro-ayarlama: parametreleri %10-%20 aralığında değiştirir.
        Büyük değişiklikler yapmaz — sistemi kademeli optimize eder.

        Kurallar:
          - BABA hataları çoksa → SL çarpanını sıkılaştır (küçült)
          - OĞUL hataları çoksa → sinyal eşiğini yükselt
          - Düşük skorlu işlemler → trailing/breakeven parametrelerini ayarla
          - Düşük win-rate kontratlar → (Top 5 zaten cezalandırıyor, ek ayar yok)

        Tüm değişiklikler DB'ye config_history olarak kaydedilir.
        """
        if not self.regulation_suggestions:
            return

        active_key = self.strategy_pool.get("active_profile", "trend")
        profile = STRATEGY_PROFILES.get(active_key)
        if not profile or "parameters" not in profile:
            return

        params = profile["parameters"]
        applied: list[str] = []

        for suggestion in self.regulation_suggestions:
            param = suggestion.get("parameter", "")
            priority = suggestion.get("priority", "LOW")

            # HIGH öncelik: BABA risk hataları → SL sıkılaştır
            if param == "max_daily_loss" and priority == "HIGH":
                old_sl = params.get("sl_atr_mult", 1.5)
                # SL'yi %10 küçült (daha sıkı risk)
                new_sl = round(max(0.8, old_sl * 0.90), 2)
                if new_sl != old_sl:
                    params["sl_atr_mult"] = new_sl
                    applied.append(f"sl_atr_mult: {old_sl} → {new_sl}")

            # MEDIUM öncelik: OĞUL sinyal hataları → eşik yükselt
            elif param == "signal_threshold" and priority in ("MEDIUM", "HIGH"):
                old_th = params.get("signal_threshold", 50)
                # Eşiği %10 artır (daha seçici sinyal)
                new_th = min(80, old_th + 5)
                if new_th != old_th:
                    params["signal_threshold"] = new_th
                    applied.append(f"signal_threshold: {old_th} → {new_th}")

            # MEDIUM öncelik: İşlem yönetimi kötü → trailing iyileştir
            elif param == "trade_management" and priority == "MEDIUM":
                old_trail = params.get("trailing_start_atr", 1.0)
                # Trailing'i %10 sıkılaştır (daha erken aktif)
                new_trail = round(max(0.5, old_trail * 0.90), 2)
                if new_trail != old_trail:
                    params["trailing_start_atr"] = new_trail
                    applied.append(f"trailing_start_atr: {old_trail} → {new_trail}")

        if applied:
            # Strateji havuzunu güncelle
            for i, prof in enumerate(self.strategy_pool.get("profiles", [])):
                if prof.get("market_type") == profile.get("market_type"):
                    self.strategy_pool["profiles"][i]["parameters"] = params

            changes_text = "; ".join(applied)
            logger.info(f"[ÜSTAT] Feedback loop: {changes_text}")

            self._log_event(
                "REGULATION_APPLIED",
                f"Regülasyon uygulandı ({active_key}): {changes_text}",
                severity="WARNING",
            )

            # Config history'ye kaydet
            try:
                self._db.insert_event(
                    event_type="CONFIG_CHANGE",
                    message=f"ÜSTAT feedback: {changes_text}",
                    severity="INFO",
                    action="ustat_regulation",
                )
            except Exception:
                pass

    # ════════════════════════════════════════════════════════════════
    #  GÜNLÜK RAPOR
    # ════════════════════════════════════════════════════════════════

    def _should_daily_report(self, now: datetime) -> bool:
        """Günlük rapor zamanı geldi mi? (Günde 1 kez, saat kısıtlaması kaldırıldı)."""
        if self._last_daily_report is None:
            return True
        return self._last_daily_report.date() != now.date()

    def _generate_daily_report(
        self, baba: Any, ogul: Any, now: datetime,
    ) -> None:
        """Günlük performans özetini DB'ye kaydet.

        Args:
            baba: Risk yöneticisi (okuma).
            ogul: Sinyal üretici (okuma).
            now: Şu anki zaman.
        """
        self._last_daily_report = now

        regime_str = ""
        if baba and hasattr(baba, "current_regime") and baba.current_regime:
            regime_str = baba.current_regime.regime_type.value

        active_count = len(getattr(ogul, "active_trades", {})) if ogul else 0
        top5 = getattr(ogul, "_current_top5", []) if ogul else []
        error_count = len(self.error_attributions)
        suggestion_count = len(self.regulation_suggestions)
        nda_count = len(self.next_day_analyses)

        summary = (
            f"Günlük özet: rejim={regime_str}, "
            f"aktif_islem={active_count}, "
            f"top5={top5}, "
            f"hata_atama={error_count}, "
            f"regulasyon_onerisi={suggestion_count}, "
            f"ertesi_gun_analiz={nda_count}"
        )
        logger.info(f"[ÜSTAT Brain] {summary}")

        try:
            self._db.insert_event(
                event_type="DAILY_REPORT",
                message=summary,
                severity="INFO",
                action="ustat_brain",
            )
        except Exception as exc:
            logger.error(f"Günlük rapor DB hatası: {exc}")

    # ════════════════════════════════════════════════════════════════
    #  YARDIMCI METODLAR
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def _previous_business_day(target: date) -> date:
        """Verilen tarihten önceki iş gününü döndür.

        Args:
            target: Hedef tarih.

        Returns:
            Önceki iş günü (Pazartesi ise Cuma).
        """
        prev = target - timedelta(days=1)
        # Pazar → Cuma, Cumartesi → Cuma
        while prev.weekday() >= 5:
            prev -= timedelta(days=1)
        return prev

    def _log_event(
        self,
        event_type: str,
        message: str,
        severity: str = "INFO",
    ) -> None:
        """DB'ye olay kaydı yaz.

        Args:
            event_type: Olay türü (REGIME_CHANGE, KILL_SWITCH, vb.).
            message: Olay açıklaması.
            severity: Önem derecesi (INFO/WARNING/CRITICAL).
        """
        try:
            self._db.insert_event(
                event_type=event_type,
                message=message,
                severity=severity,
                action="ustat_brain",
            )
        except Exception as exc:
            logger.warning(f"ÜSTAT event yazma hatası: {exc}")

    def _log_event_deduplicated(
        self,
        event_type: str,
        message: str,
        severity: str = "INFO",
        dedup_key: str = "",
        dedup_minutes: int = 30,
    ) -> None:
        """Tekrarlayan olayları filtreleyerek DB'ye yaz.

        Aynı ``dedup_key`` ile son ``dedup_minutes`` dakika içinde
        zaten loglanmışsa tekrar yazmaz.

        Args:
            event_type: Olay türü.
            message: Olay açıklaması.
            severity: Önem derecesi.
            dedup_key: Tekrar kontrol anahtarı.
            dedup_minutes: Minimum tekrar aralığı (dakika).
        """
        now = datetime.now()
        key = dedup_key or f"{event_type}_{message[:50]}"

        last_logged = self._dedup_cache.get(key)
        if last_logged and (now - last_logged).total_seconds() < dedup_minutes * 60:
            return

        self._dedup_cache[key] = now
        self._log_event(event_type, message, severity)

        # Cache temizliği (eski kayıtları sil)
        expired_keys = [
            k for k, v in self._dedup_cache.items()
            if (now - v).total_seconds() > DEDUP_CACHE_TTL_SEC
        ]
        for k in expired_keys:
            del self._dedup_cache[k]

    # ════════════════════════════════════════════════════════════════
    #  PERSISTENCE — DB'ye kaydet / DB'den yükle
    # ════════════════════════════════════════════════════════════════

    def _load_persisted_state(self) -> None:
        """Uygulama başlangıcında önceki oturum verilerini DB'den yükle.

        app_state tablosundaki JSON verilerini okuyarak ÜSTAT'ın
        error_attributions, next_day_analyses, regulation_suggestions,
        strategy_pool ve contract_profiles verilerini geri yükler.
        Böylece uygulama restart'ında veriler kaybolmaz.
        """
        if not self._db:
            return

        keys_map = {
            "ustat_error_attributions": "error_attributions",
            "ustat_next_day_analyses": "next_day_analyses",
            "ustat_regulation_suggestions": "regulation_suggestions",
            "ustat_strategy_pool": "strategy_pool",
            "ustat_contract_profiles": "contract_profiles",
        }

        for db_key, attr_name in keys_map.items():
            try:
                raw = self._db.get_state(db_key)
                if raw:
                    data = json.loads(raw)
                    setattr(self, attr_name, data)
                    logger.info(
                        f"[ÜSTAT] Persistence yüklendi: {attr_name} "
                        f"({len(data) if isinstance(data, (list, dict)) else '?'} kayıt)"
                    )
            except Exception as exc:
                logger.warning(f"[ÜSTAT] Persistence yükleme hatası ({db_key}): {exc}")

    def _save_persisted_state(self) -> None:
        """ÜSTAT verilerini DB'ye kaydet (her cycle sonunda çağrılır).

        Tüm analiz sonuçlarını app_state tablosuna JSON olarak yazar.
        Böylece uygulama kapansa bile veriler korunur.
        """
        if not self._db:
            return

        data_map = {
            "ustat_error_attributions": self.error_attributions,
            "ustat_next_day_analyses": self.next_day_analyses,
            "ustat_regulation_suggestions": self.regulation_suggestions,
            "ustat_strategy_pool": self.strategy_pool,
            "ustat_contract_profiles": self.contract_profiles,
        }

        for db_key, data in data_map.items():
            try:
                self._db.set_state(db_key, json.dumps(data, ensure_ascii=False))
            except Exception as exc:
                logger.warning(f"[ÜSTAT] Persistence kaydetme hatası ({db_key}): {exc}")

    # ════════════════════════════════════════════════════════════════
    #  AKTIF STRATEJİ PARAMETRELERİ — OĞUL OKUR
    # ════════════════════════════════════════════════════════════════

    def get_active_params(self) -> dict[str, Any]:
        """Aktif rejim profiline göre strateji parametrelerini döndür.

        OĞUL bu metodu çağırarak rejime uygun dinamik parametreleri alır.
        Eğer aktif profil yoksa varsayılan (trend) parametreleri döner.

        Returns:
            Parametre sözlüğü: sl_atr_mult, tp_atr_mult, lot_scale,
            max_hold_minutes, trailing_start_atr, breakeven_atr,
            signal_threshold.
        """
        active_key = self.strategy_pool.get("active_profile", "trend")
        profile = STRATEGY_PROFILES.get(active_key)
        if profile and "parameters" in profile:
            return dict(profile["parameters"])
        # Fallback: trend profili
        return dict(STRATEGY_PROFILES["trend"]["parameters"])

    def get_contract_profile(self, symbol: str) -> dict[str, Any] | None:
        """Belirli bir kontratın davranış profilini döndür.

        OĞUL Top 5 seçiminde ve sinyal üretiminde bu bilgiyi kullanır.

        Args:
            symbol: Kontrat sembolü.

        Returns:
            Kontrat profili dict veya None (profil yoksa).
        """
        return self.contract_profiles.get(symbol)

    # ════════════════════════════════════════════════════════════════
    #  API TARAFINDAN OKUNAN VERİLER
    # ════════════════════════════════════════════════════════════════

    def get_error_attributions(self) -> list[dict[str, Any]]:
        """Hata atamalarını döndür (API için)."""
        return list(self.error_attributions)

    def get_next_day_analyses(self) -> list[dict[str, Any]]:
        """Ertesi gün analizlerini döndür (API için)."""
        return list(self.next_day_analyses)

    def get_regulation_suggestions(self) -> list[dict[str, Any]]:
        """Regülasyon önerilerini döndür (API için)."""
        return list(self.regulation_suggestions)

    def get_strategy_pool(self) -> dict[str, Any]:
        """Strateji havuzunu döndür (API için)."""
        return dict(self.strategy_pool)

    def get_contract_profiles(self) -> dict[str, dict[str, Any]]:
        """Kontrat profillerini döndür (API için)."""
        return dict(self.contract_profiles)
