"""Loglama konfigürasyonu.

Loguru tabanlı merkezi loglama sistemi.
"""

import io
import os
import sys
from pathlib import Path

from loguru import logger

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ── pythonw.exe uyumluluğu ────────────────────────────────────────
# pythonw.exe ile çalışırken sys.stderr None olur veya encoding'i
# charmap olur. Bu durumda Türkçe karakterli log mesajları
# UnicodeEncodeError fırlatır. Güvenli bir sink oluştur.
def _safe_stderr():
    """pythonw.exe uyumlu stderr sink döndür."""
    if sys.stderr is None:
        return open(os.devnull, "w", encoding="utf-8")
    if hasattr(sys.stderr, "buffer"):
        return io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    return sys.stderr

_log_sink = _safe_stderr()

# Varsayılan loguru sink'ini kaldır
logger.remove()

# Konsol çıktısı (UTF-8 güvenli)
logger.add(
    _log_sink,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan> - {message}",
)

# Dosya çıktısı
logger.add(
    str(LOG_DIR / "ustat_{time:YYYY-MM-DD}.log"),
    level="DEBUG",
    rotation="1 day",
    retention="30 days",
    encoding="utf-8",
)


def get_logger(name: str):
    """Modül için logger döndür.

    Args:
        name: Modül adı (__name__).

    Returns:
        Logger instance.
    """
    return logger.bind(name=name)
