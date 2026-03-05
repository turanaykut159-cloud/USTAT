"""ÜSTAT — Strateji yönetimi ve sistem beyni (v13.0).

v13.0 sonrası ÜSTAT'ın görevleri:
    - Strateji havuzu yönetimi (hangi stratejiler aktif)
    - Sistem durumu izleme ve raporlama
    - Günlük performans özeti
    - Top 5 kontrat seçimi OĞUL'a devredildi

Not: Top 5 seçim mantığı (select_top5, puanlama, filtreleme)
     v13.0 ile engine/ogul.py'ye taşındı.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.config import Config
from engine.database import Database
from engine.logger import get_logger

logger = get_logger(__name__)


class Ustat:
    """Strateji yöneticisi — sistem beyni.

    v13.0: Top 5 kontrat seçimi OĞUL'a devredildi.
    ÜSTAT artık raporlama, strateji havuzu ve sistem
    izleme görevlerini üstlenir.

    Her cycle'da ``run_cycle(baba, ogul)`` çağrılır.
    """

    def __init__(self, config: Config, db: Database) -> None:
        self._config = config
        self._db = db
        self._last_daily_report: datetime | None = None

    def run_cycle(self, baba: Any, ogul: Any) -> None:
        """ÜSTAT brain cycle — sistem durumunu izle ve raporla.

        Her 10 sn'de main_loop tarafından çağrılır.
        Ağır işlemler (günlük rapor vb.) zaman kontrolüyle korunur.

        Args:
            baba: Risk yöneticisi instance.
            ogul: Sinyal üretici instance (Top 5 dahil).
        """
        now = datetime.now()

        # Günlük performans özeti — günde 1 kez (18:00'da)
        if self._should_daily_report(now):
            self._generate_daily_report(baba, ogul, now)

    def _should_daily_report(self, now: datetime) -> bool:
        """Günlük rapor zamanı geldi mi? (18:00 sonrası, günde 1 kez)."""
        if now.hour < 18:
            return False
        if self._last_daily_report is None:
            return True
        return self._last_daily_report.date() != now.date()

    def _generate_daily_report(
        self, baba: Any, ogul: Any, now: datetime,
    ) -> None:
        """Günlük performans özetini DB'ye kaydet.

        Args:
            baba: Risk yöneticisi.
            ogul: Sinyal üretici.
            now: Şu anki zaman.
        """
        self._last_daily_report = now

        # Özet bilgileri topla
        regime_str = ""
        if baba and hasattr(baba, "current_regime") and baba.current_regime:
            regime_str = baba.current_regime.regime_type.value

        active_count = len(ogul.active_trades) if ogul else 0
        top5 = ogul._current_top5 if ogul else []

        summary = (
            f"Günlük özet: rejim={regime_str}, "
            f"aktif_islem={active_count}, "
            f"top5={top5}"
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
