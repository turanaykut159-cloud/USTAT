"""GET /api/nabiz — NABIZ Sistem Monitoru.

Veritabani, log dosyalari, disk kullanimi ve retention durumunu
tek endpoint ile dondurur. Sadece OKUMA yapar — hicbir seyi degistirmez.

Veri kaynaklari:
  - db.get_table_sizes() → tablo satir sayilari
  - os.path.getsize()   → dosya boyutlari (DB, log)
  - shutil.disk_usage() → disk alani
  - config/default.json → retention konfigurasyonu
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from api.deps import get_db, get_engine

logger = logging.getLogger("ustat.api.routes.nabiz")

router = APIRouter()

# Proje kok dizini (api/routes/nabiz.py → ../../)
_PROJECT_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent


@router.get("/nabiz")
async def get_nabiz():
    """NABIZ sistem monitoru verisini dondur."""
    engine = get_engine()
    db = get_db()

    result = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "database": _build_database_info(db),
        "logs": _build_log_info(),
        "disk": _build_disk_info(),
        "retention": _build_retention_info(engine),
        "cleanup_conflict": _build_cleanup_conflict_info(engine),
    }

    return result


def _build_database_info(db) -> dict:
    """Veritabani bilgilerini topla."""
    info = {
        "file_size_mb": 0.0,
        "table_sizes": {},
        "total_rows": 0,
        "wal_size_mb": 0.0,
    }

    if not db:
        return info

    # DB dosya boyutu
    if hasattr(db, "_db_path"):
        try:
            db_path = Path(db._db_path)
            info["file_size_mb"] = round(db_path.stat().st_size / (1024 * 1024), 2)

            # WAL dosyasi boyutu
            wal_path = db_path.with_suffix(".db-wal")
            if wal_path.exists():
                info["wal_size_mb"] = round(wal_path.stat().st_size / (1024 * 1024), 2)
        except OSError as e:
            logger.debug("DB dosya boyutu okunamadi: %s", e)

    # Tablo boyutlari
    try:
        sizes = db.get_table_sizes()
        info["table_sizes"] = sizes
        info["total_rows"] = sum(v for v in sizes.values() if v > 0)
    except Exception as e:
        logger.warning("Tablo boyutlari alinamadi: %s", e)

    return info


def _build_log_info() -> dict:
    """Log dosyalari bilgilerini topla."""
    logs_dir = _PROJECT_ROOT / "logs"
    info = {
        "files": [],
        "total_size_mb": 0.0,
        "log_dir_exists": logs_dir.exists(),
    }

    if not logs_dir.exists():
        return info

    total = 0.0
    try:
        for f in sorted(logs_dir.iterdir(), reverse=True):
            if f.is_file() and f.suffix == ".log":
                size = f.stat().st_size
                total += size
                info["files"].append({
                    "name": f.name,
                    "size_mb": round(size / (1024 * 1024), 2),
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                })
    except OSError as e:
        logger.warning("Log dosyalari listelenemedi: %s", e)

    # Kok dizindeki tekil log dosyalari
    for name in ("api.log", "electron.log", "startup.log", "vite.log"):
        fpath = _PROJECT_ROOT / name
        if fpath.exists():
            try:
                size = fpath.stat().st_size
                total += size
                info["files"].append({
                    "name": name,
                    "size_mb": round(size / (1024 * 1024), 2),
                    "modified": datetime.fromtimestamp(fpath.stat().st_mtime).isoformat(timespec="seconds"),
                })
            except OSError:
                pass

    info["total_size_mb"] = round(total / (1024 * 1024), 2)
    return info


def _build_disk_info() -> dict:
    """Disk kullanim bilgisini topla."""
    info = {
        "total_gb": 0.0,
        "used_gb": 0.0,
        "free_gb": 0.0,
        "usage_pct": 0.0,
    }

    try:
        usage = shutil.disk_usage(str(_PROJECT_ROOT))
        info["total_gb"] = round(usage.total / (1024 ** 3), 1)
        info["used_gb"] = round(usage.used / (1024 ** 3), 1)
        info["free_gb"] = round(usage.free / (1024 ** 3), 1)
        info["usage_pct"] = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0.0
    except OSError as e:
        logger.warning("Disk kullanimi alinamadi: %s", e)

    return info


def _build_retention_info(engine) -> dict:
    """Retention konfigurasyonu ve son calisma durumunu topla."""
    info = {
        "enabled": False,
        "config": {},
        "last_retention_date": None,
        "last_cleanup_date": None,
    }

    if not engine:
        return info

    # Config'den retention ayarlarini oku
    config = getattr(engine, "config", None)
    if config:
        info["enabled"] = config.get("retention.enabled", False)
        info["config"] = {
            "risk_snapshots_days": config.get("retention.risk_snapshots_days", 30),
            "top5_history_days": config.get("retention.top5_history_days", 60),
            "events_info_days": config.get("retention.events_info_days", 14),
            "events_warning_days": config.get("retention.events_warning_days", 30),
            "events_error_days": config.get("retention.events_error_days", 90),
            "config_history_days": config.get("retention.config_history_days", 365),
            "liquidity_days": config.get("retention.liquidity_days", 30),
            "hybrid_closed_days": config.get("retention.hybrid_closed_days", 90),
            "trade_archive_days": config.get("retention.trade_archive_days", 180),
        }

    # Son calisma tarihleri (in-memory)
    last_ret = getattr(engine, "_last_retention_date", None)
    last_clean = getattr(engine, "_last_cleanup_date", None)
    info["last_retention_date"] = str(last_ret) if last_ret else None
    info["last_cleanup_date"] = str(last_clean) if last_clean else None

    return info


def _build_cleanup_conflict_info(engine) -> dict:
    """Cift temizlik sistemi cakisma durumunu DINAMIK kontrol et.

    _run_daily_cleanup (main.py) sabit gunlerle silerken,
    run_retention (database.py) config'den okuyor. Ikisi ayni
    tabloyu farkli surelerle temizliyorsa cakisma var demektir.
    """
    # _run_daily_cleanup sabit degerleri (engine/main.py'den)
    CLEANUP_BARS_DAYS = 30
    CLEANUP_EVENTS_DAYS = 60
    CLEANUP_SNAPSHOTS_DAYS = 90

    # Retention config'den dinamik degerler
    config = getattr(engine, "config", None) if engine else None
    ret_snap_days = config.get("retention.risk_snapshots_days", 30) if config else 30
    ret_events_info = config.get("retention.events_info_days", 14) if config else 14
    ret_events_warn = config.get("retention.events_warning_days", 30) if config else 30
    ret_events_err = config.get("retention.events_error_days", 90) if config else 90

    # Cakisma kontrolu: cleanup suresi ile retention suresi farkli mi?
    affected = []

    # events: cleanup 60 gun, retention INFO=14 / WARN=30 / ERR=90
    if CLEANUP_EVENTS_DAYS != ret_events_err:
        affected.append({
            "table": "events",
            "cleanup_days": CLEANUP_EVENTS_DAYS,
            "retention_days": f"{ret_events_info} (INFO) / {ret_events_warn} (WARNING) / {ret_events_err} (ERROR)",
            "risk": (
                "cleanup, INFO/WARNING icin retention'dan once siliyor"
                if CLEANUP_EVENTS_DAYS < ret_events_err
                else "farkli sureler — tutarsizlik"
            ),
        })

    # risk_snapshots: cleanup 90 gun, retention config'den
    if CLEANUP_SNAPSHOTS_DAYS != ret_snap_days:
        affected.append({
            "table": "risk_snapshots",
            "cleanup_days": CLEANUP_SNAPSHOTS_DAYS,
            "retention_days": ret_snap_days,
            "risk": (
                "cleanup aggregation yapmadan siliyor — veri kaybi"
                if CLEANUP_SNAPSHOTS_DAYS > ret_snap_days
                else "farkli sureler — tutarsizlik"
            ),
        })

    has_conflict = len(affected) > 0

    # Retention eksik tablolar: DB'deki tum tablolari kontrol et
    # retention config'de tanimlanan tablolar
    retention_covered = {
        "risk_snapshots", "top5_history", "events",
        "config_history", "liquidity_classes", "hybrid_positions",
        "trades",  # trade_archive_days ile kapsaniyor
    }

    # DB'deki buyuyebilecek tablolar
    db = get_db()
    growing_tables = {}
    if db:
        try:
            sizes = db.get_table_sizes()
            for table, count in sizes.items():
                if table in ("app_state", "strategies"):
                    continue  # Sabit/kucuk tablolar
                if table not in retention_covered and count > 0:
                    growing_tables[table] = count
        except Exception:
            pass

    missing = []
    for table, count in sorted(growing_tables.items(), key=lambda x: -x[1]):
        missing.append({
            "table": table,
            "status": f"retention YOK ({count:,} satir)",
            "daily_growth": "buyuyor" if count > 100 else "dusuk",
        })

    return {
        "has_conflict": has_conflict,
        "description": (
            f"{len(affected)} tablo cakismasi tespit edildi."
            if has_conflict
            else "Cakisma yok — cleanup ve retention uyumlu."
        ),
        "affected_tables": affected,
        "missing_retention": missing,
    }
