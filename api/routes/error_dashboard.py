"""ÜSTAT v5.6 — Hata Takip Dashboard API.

Endpoint'ler:
    GET  /api/errors/summary    — Dashboard özet (sayaçlar, kategori dağılımı)
    GET  /api/errors/groups     — Hata grupları (filtreli)
    GET  /api/errors/trends     — Saatlik/günlük trend
    POST /api/errors/resolve    — Hata grubunu çözümle
    POST /api/errors/resolve-all — Tüm açık hataları çözümle

v5.5 Güncelleme: Artık sadece ErrorTracker (in-memory) değil,
database events tablosundan da veri çeker. Bu sayede tüm engine
modüllerinin insert_event() ile kaydettiği olaylar da panelde görünür.
Kırmızı Bölge dosyalarına dokunulmadı.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.deps import get_db, get_engine

logger = logging.getLogger("ustat.api.routes.error_dashboard")

router = APIRouter(prefix="/errors", tags=["errors"])


# ── Kategori Eşleme (error_tracker.py ile aynı) ──
# Engine event_type → dashboard kategorisi
EVENT_TYPE_CATEGORY = {
    # bağlantı
    "MT5_DISCONNECT": "bağlantı",
    "MT5_RECONNECT": "bağlantı",
    "MT5_TIMEOUT": "bağlantı",
    "CONNECTION": "bağlantı",
    # emir
    "ORDER_REJECT": "emir",
    "ORDER_TIMEOUT": "emir",
    "ORDER_FILL_PARTIAL": "emir",
    "SLTP_MODIFY_FAIL": "emir",
    "TRADE": "emir",
    "TRADE_OPEN": "emir",
    "TRADE_CLOSE": "emir",
    "EMERGENCY_CLOSE": "emir",
    "FORCE_CLOSE": "emir",
    "EOD_CLOSE": "emir",
    "GHOST_CLOSE": "emir",
    "SL_HIT": "emir",
    "TP_HIT": "emir",
    "TRAILING_UPDATE": "emir",
    "SLTP_ATTACHED": "emir",
    "SLTP_FAIL": "emir",
    # risk
    "KILL_SWITCH": "risk",
    "DRAWDOWN_LIMIT": "risk",
    "RISK_LIMIT": "risk",
    "FLOATING_LIMIT": "risk",
    "COOLDOWN": "risk",
    "EARLY_WARNING": "risk",
    "DAILY_LOSS_STOP": "risk",
    "RISK": "risk",
    "REGIME_CHANGE": "risk",
    # sinyal
    "FAKE_SIGNAL": "sinyal",
    "SIGNAL_REJECTED": "sinyal",
    "SIGNAL": "sinyal",
    # netting
    "NETTING_MISMATCH": "netting",
    "VOLUME_MISMATCH": "netting",
    "EXTERNAL_CLOSE": "netting",
    "SYNC": "netting",
    # veri
    "DATA_ANOMALY": "veri",
    "DATA_STALE": "veri",
    "DATA": "veri",
    # sistem
    "DB_ERROR": "sistem",
    "CYCLE_OVERRUN": "sistem",
    "IPC_ERROR": "sistem",
    "SYSTEM": "sistem",
    "ENGINE": "sistem",
    "STARTUP": "sistem",
    "SHUTDOWN": "sistem",
    "WATCHDOG": "sistem",
    "CONFIG": "sistem",
    "BACKUP": "sistem",
}

# Severity öncelik sırası (sıralama için)
SEVERITY_ORDER = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3, "DEBUG": 4}


def _categorize(event_type: str) -> str:
    """Event type'ı kategoriye çevir."""
    return EVENT_TYPE_CATEGORY.get(event_type, "sistem")


# ── Response Models ──

class ErrorSummaryResponse(BaseModel):
    """Dashboard özet verisi."""
    today_errors: int = 0
    today_warnings: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    total_critical: int = 0
    open_groups: int = 0
    resolved_groups: int = 0
    this_hour_count: int = 0
    by_category: dict = {}
    by_severity: dict = {}
    latest_error: dict | None = None


class ErrorGroupItem(BaseModel):
    """Tek hata grubu."""
    error_type: str = ""
    category: str = ""
    severity: str = ""
    message: str = ""
    first_seen: str = ""
    last_seen: str = ""
    count: int = 0
    resolved: bool = False
    resolved_at: str | None = None
    resolved_by: str = ""
    event_count: int = 0


class ErrorGroupsResponse(BaseModel):
    """Hata grupları listesi."""
    count: int = 0
    groups: list[ErrorGroupItem] = []


class TrendItem(BaseModel):
    """Tek trend noktası."""
    hour: str | None = None
    date: str | None = None
    count: int | None = None
    errors: int | None = None
    warnings: int | None = None
    critical: int | None = None


class TrendsResponse(BaseModel):
    """Trend verisi."""
    period: str = "hourly"
    data: list[TrendItem] = []


class ResolveRequest(BaseModel):
    """Hata çözümleme isteği."""
    error_type: str
    message_prefix: str = ""
    resolved_by: str = "operator"


class ResolveResponse(BaseModel):
    """Hata çözümleme yanıtı."""
    success: bool
    message: str = ""


class ResolveAllResponse(BaseModel):
    """Tüm hataları çözümleme yanıtı."""
    success: bool
    resolved_count: int = 0


# ── DB Helpers ──

def _get_tracker():
    """ErrorTracker instance'ına eriş (resolve işlemleri için)."""
    engine = get_engine()
    if engine and hasattr(engine, "error_tracker"):
        return engine.error_tracker
    return None


def _fetch_events_from_db(
    severity_filter: str | None = None,
    since: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Events tablosundan kayıt çek. Sadece WARNING+ seviye."""
    db = get_db()
    if not db:
        return []

    try:
        clauses = []
        params = []

        # Sadece WARNING, ERROR, CRITICAL göster (INFO/DEBUG gürültü yapar)
        if severity_filter:
            clauses.append("severity = ?")
            params.append(severity_filter)
        else:
            clauses.append("severity IN ('WARNING', 'ERROR', 'CRITICAL')")

        if since:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        return db._fetch_all(
            f"SELECT * FROM events {where} ORDER BY id DESC LIMIT ?",
            tuple(params),
        )
    except Exception as exc:
        logger.warning("DB events çekme hatası: %s", exc)
        return []


# ── Endpoints ──

@router.get("/summary", response_model=ErrorSummaryResponse)
async def get_error_summary():
    """Dashboard özet verisi — DB events tablosundan."""
    try:
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        hour_start = (now - timedelta(hours=1)).isoformat()

        # Son 7 günlük eventler
        week_start = (now - timedelta(days=7)).isoformat()
        events = _fetch_events_from_db(since=week_start, limit=5000)

        if not events:
            return ErrorSummaryResponse()

        today_errors = 0
        today_warnings = 0
        total_errors = 0
        total_warnings = 0
        total_critical = 0
        this_hour_count = 0
        by_category: dict[str, int] = defaultdict(int)
        by_severity: dict[str, int] = defaultdict(int)
        latest_error = None

        for ev in events:
            ts = ev.get("timestamp", "")
            sev = ev.get("severity", "INFO")
            etype = ev.get("type", "")
            cat = _categorize(etype)

            by_category[cat] += 1
            by_severity[sev] += 1

            if sev in ("ERROR", "CRITICAL"):
                total_errors += 1
                if ts >= today_start:
                    today_errors += 1
            elif sev == "WARNING":
                total_warnings += 1
                if ts >= today_start:
                    today_warnings += 1

            if sev == "CRITICAL":
                total_critical += 1

            if ts >= hour_start:
                this_hour_count += 1

            if sev in ("ERROR", "CRITICAL") and latest_error is None:
                latest_error = {
                    "error_type": etype,
                    "message": ev.get("message", ""),
                    "last_seen": ts,
                    "severity": sev,
                    "category": cat,
                }

        # Çözümlenmiş grup sayısı: ErrorTracker'dan al
        resolved_groups = 0
        open_groups = len(set(
            ev.get("type", "") for ev in events
            if ev.get("severity") in ("WARNING", "ERROR", "CRITICAL")
            and ev.get("timestamp", "") >= today_start
        ))
        tracker = _get_tracker()
        if tracker:
            try:
                tracker_summary = tracker.get_summary()
                resolved_groups = tracker_summary.get("resolved_groups", 0)
            except Exception:
                pass

        return ErrorSummaryResponse(
            today_errors=today_errors,
            today_warnings=today_warnings,
            total_errors=total_errors,
            total_warnings=total_warnings,
            total_critical=total_critical,
            open_groups=open_groups,
            resolved_groups=resolved_groups,
            this_hour_count=this_hour_count,
            by_category=dict(by_category),
            by_severity=dict(by_severity),
            latest_error=latest_error,
        )
    except Exception as exc:
        logger.exception("error_summary HATASI: %s", exc)
        return ErrorSummaryResponse()


@router.get("/groups", response_model=ErrorGroupsResponse)
async def get_error_groups(
    category: str | None = Query(None, description="Kategori filtresi"),
    severity: str | None = Query(None, description="Severity filtresi"),
    resolved: bool | None = Query(None, description="Çözümleme durumu filtresi"),
    limit: int = Query(50, ge=1, le=200, description="Maks grup sayısı"),
):
    """Hata gruplarını filtreli getir — DB events tablosundan grupla."""
    try:
        now = datetime.now()
        week_start = (now - timedelta(days=7)).isoformat()

        events = _fetch_events_from_db(
            severity_filter=severity,
            since=week_start,
            limit=5000,
        )

        if not events:
            return ErrorGroupsResponse()

        # Çözümlenmiş tipleri al
        resolved_types: set[str] = set()
        tracker = _get_tracker()
        if tracker and hasattr(tracker, "_resolved_types"):
            resolved_types = tracker._resolved_types

        # Event'leri type'a göre grupla
        groups_map: dict[str, dict] = {}

        for ev in events:
            etype = ev.get("type", "")
            sev = ev.get("severity", "INFO")
            msg = ev.get("message", "")
            ts = ev.get("timestamp", "")
            cat = _categorize(etype)

            # Kategori filtresi
            if category and cat != category:
                continue

            # Severity filtresi (zaten _fetch_events_from_db'de uygulandı ama çift kontrol)
            if severity and sev != severity:
                continue

            is_resolved = etype in resolved_types

            # Çözümleme filtresi
            if resolved is not None:
                if resolved and not is_resolved:
                    continue
                if not resolved and is_resolved:
                    continue

            group_key = etype

            if group_key not in groups_map:
                groups_map[group_key] = {
                    "error_type": etype,
                    "category": cat,
                    "severity": sev,
                    "message": msg,
                    "first_seen": ts,
                    "last_seen": ts,
                    "count": 0,
                    "resolved": is_resolved,
                    "resolved_at": None,
                    "resolved_by": "",
                    "event_count": 0,
                }

            g = groups_map[group_key]
            g["count"] += 1
            g["event_count"] += 1

            # En yüksek severity'yi tut
            if SEVERITY_ORDER.get(sev, 99) < SEVERITY_ORDER.get(g["severity"], 99):
                g["severity"] = sev

            # En son mesajı güncelle
            if ts > g["last_seen"]:
                g["last_seen"] = ts
                g["message"] = msg

            # En eski first_seen
            if ts < g["first_seen"]:
                g["first_seen"] = ts

        # Sıralama: severity → count (desc)
        sorted_groups = sorted(
            groups_map.values(),
            key=lambda g: (SEVERITY_ORDER.get(g["severity"], 99), -g["count"]),
        )

        items = [ErrorGroupItem(**g) for g in sorted_groups[:limit]]
        return ErrorGroupsResponse(count=len(items), groups=items)

    except Exception as exc:
        logger.exception("error_groups HATASI: %s", exc)
        return ErrorGroupsResponse()


@router.get("/trends", response_model=TrendsResponse)
async def get_error_trends(
    period: str = Query("hourly", description="'hourly' veya 'daily'"),
    hours: int = Query(24, ge=1, le=168, description="Saatlik trend: kaç saat"),
    days: int = Query(7, ge=1, le=30, description="Günlük trend: kaç gün"),
):
    """Hata trendi — DB events tablosundan saatlik/günlük."""
    try:
        now = datetime.now()

        if period == "daily":
            since = (now - timedelta(days=days)).isoformat()
            events = _fetch_events_from_db(since=since, limit=10000)

            # Günlere göre grupla
            day_counts: dict[str, dict] = {}
            for i in range(days):
                d = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
                day_counts[d] = {"errors": 0, "warnings": 0, "critical": 0}

            for ev in events:
                ts = ev.get("timestamp", "")[:10]  # YYYY-MM-DD
                sev = ev.get("severity", "INFO")
                if ts in day_counts:
                    if sev == "CRITICAL":
                        day_counts[ts]["critical"] += 1
                        day_counts[ts]["errors"] += 1
                    elif sev == "ERROR":
                        day_counts[ts]["errors"] += 1
                    elif sev == "WARNING":
                        day_counts[ts]["warnings"] += 1

            items = [
                TrendItem(
                    date=d,
                    count=v["errors"] + v["warnings"] + v["critical"],
                    errors=v["errors"],
                    warnings=v["warnings"],
                    critical=v["critical"],
                )
                for d, v in day_counts.items()
            ]
            return TrendsResponse(period="daily", data=items)

        else:
            since = (now - timedelta(hours=hours)).isoformat()
            events = _fetch_events_from_db(since=since, limit=10000)

            # Saatlere göre grupla
            hour_counts: dict[str, dict] = {}
            for i in range(hours):
                h = (now - timedelta(hours=hours - 1 - i)).strftime("%Y-%m-%d %H:00")
                hour_counts[h] = {"errors": 0, "warnings": 0, "critical": 0}

            for ev in events:
                ts = ev.get("timestamp", "")
                if len(ts) >= 13:
                    h_key = ts[:10] + " " + ts[11:13] + ":00"
                    sev = ev.get("severity", "INFO")
                    if h_key in hour_counts:
                        if sev == "CRITICAL":
                            hour_counts[h_key]["critical"] += 1
                            hour_counts[h_key]["errors"] += 1
                        elif sev == "ERROR":
                            hour_counts[h_key]["errors"] += 1
                        elif sev == "WARNING":
                            hour_counts[h_key]["warnings"] += 1

            items = [
                TrendItem(
                    hour=h,
                    count=v["errors"] + v["warnings"] + v["critical"],
                    errors=v["errors"],
                    warnings=v["warnings"],
                    critical=v["critical"],
                )
                for h, v in hour_counts.items()
            ]
            return TrendsResponse(period="hourly", data=items)

    except Exception as exc:
        logger.exception("error_trends HATASI: %s", exc)
        return TrendsResponse(period=period)


@router.post("/resolve", response_model=ResolveResponse)
async def resolve_error_group(req: ResolveRequest):
    """Hata grubunu çözümlendi olarak işaretle."""
    tracker = _get_tracker()
    if not tracker:
        return ResolveResponse(success=False, message="ErrorTracker aktif değil")

    try:
        ok = tracker.resolve_group(
            error_type=req.error_type,
            message_prefix=req.message_prefix,
            by=req.resolved_by,
        )
        if ok:
            return ResolveResponse(success=True, message=f"{req.error_type} çözümlendi")
        return ResolveResponse(success=False, message="Eşleşen hata grubu bulunamadı")
    except Exception as exc:
        logger.exception("resolve_error HATASI: %s", exc)
        return ResolveResponse(success=False, message=str(exc))


@router.post("/resolve-all", response_model=ResolveAllResponse)
async def resolve_all_errors(req: ResolveRequest | None = None, resolved_by: str = Query("operator")):
    """Tüm açık hataları çözümle."""
    tracker = _get_tracker()
    if not tracker:
        return ResolveAllResponse(success=False)

    try:
        by = req.resolved_by if req else resolved_by
        count = tracker.resolve_all(by=by)
        return ResolveAllResponse(success=True, resolved_count=count)
    except Exception as exc:
        logger.exception("resolve_all HATASI: %s", exc)
        return ResolveAllResponse(success=False)
