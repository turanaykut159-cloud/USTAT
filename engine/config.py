"""Konfigürasyon yönetimi.

JSON dosyasından ve ortam değişkenlerinden konfigürasyon okur.
"""

import json
import os
from pathlib import Path

from engine.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "default.json"


class Config:
    """Konfigürasyon yöneticisi."""

    def __init__(self, config_path: str | None = None):
        self._path = Path(config_path) if config_path else CONFIG_PATH
        self._data = {}
        self._load()

    def _load(self) -> None:
        """Konfigürasyon dosyasını yükle."""
        if self._path.exists():
            with open(self._path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            logger.info(f"Konfigürasyon yüklendi: {self._path}")
        else:
            logger.warning(f"Konfigürasyon dosyası bulunamadı: {self._path}")

    def get(self, key: str, default=None):
        """Konfigürasyon değeri getir.

        Args:
            key: Konfigürasyon anahtarı (nokta ile ayrılmış).
            default: Varsayılan değer.

        Returns:
            Konfigürasyon değeri.
        """
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default
