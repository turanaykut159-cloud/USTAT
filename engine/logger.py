"""Loglama konfigürasyonu.

Loguru tabanlı merkezi loglama sistemi.
"""

import sys
from pathlib import Path

from loguru import logger

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Varsayılan loguru sink'ini kaldır
logger.remove()

# Konsol çıktısı
logger.add(
    sys.stderr,
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
