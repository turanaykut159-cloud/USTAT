"""API sabitleri.

Tüm route'larda ortak kullanılan sabit değerler.
"""

from __future__ import annotations

import re

# ── Stats Baseline (Widget Denetimi A7) ──────────────────────────────
# Dashboard istatistikleri ve performans hesaplamalarının başlangıç
# tarihi. Bu tarihten önceki veriler istatistik hesaplamalarına dahil
# edilmez. Tek kaynak: config/default.json::risk.stats_baseline_date.
# Aşağıdaki sabit yalnızca config okunamadığında fallback olarak
# kullanılır. risk.baseline_date (peak_equity reset noktası) ile farklı
# anlamlar taşır — iki değer de /settings/stats-baseline endpoint'i
# üzerinden frontend'e birlikte sunulur.
STATS_BASELINE = "2026-02-01"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?$")


def get_stats_baseline() -> str:
    """Config'den risk.stats_baseline_date oku, yoksa STATS_BASELINE default.

    Widget Denetimi A7 — Tek kaynak ilkesi. Eski sabit hardcode davranışı
    korunur (fallback) ancak konfigürasyon dosyasındaki değer tercih
    edilir. Döndürülen değer ISO 8601 formatında ("YYYY-MM-DD" veya
    "YYYY-MM-DD HH:MM") ya da geçersizse fallback'tir.
    """
    try:
        from api.deps import get_engine  # circular-safe local import
    except Exception:
        return STATS_BASELINE
    try:
        engine = get_engine()
    except Exception:
        return STATS_BASELINE
    if engine is None or not hasattr(engine, "config"):
        return STATS_BASELINE
    try:
        val = engine.config.get("risk.stats_baseline_date", "")
    except Exception:
        return STATS_BASELINE
    if isinstance(val, str) and _DATE_RE.match(val.strip()):
        return val.strip()
    return STATS_BASELINE
