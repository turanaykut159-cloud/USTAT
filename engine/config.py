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
    """Konfigürasyon yöneticisi.

    Nokta-ayrımlı anahtar erişimi destekler:
        config.get("strategies.trend_follow.ema_fast", 20)
        config.get("liquidity_overrides.volume_mult.A", 1.5)
    """

    def __init__(self, config_path: str | None = None):
        self._path = Path(config_path) if config_path else CONFIG_PATH
        self._data: dict = {}
        self._is_loaded: bool = False
        self._load()

    def _load(self) -> None:
        """Konfigürasyon dosyasını yükle."""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                self._is_loaded = True
                logger.info(f"Konfigürasyon yüklendi: {self._path}")
                self._log_summary()
            except (json.JSONDecodeError, OSError) as exc:
                logger.error(
                    f"Konfigürasyon parse hatası: {self._path} — {exc}"
                )
                self._data = {}
        else:
            logger.critical(
                f"Konfigürasyon dosyası bulunamadı: {self._path} — "
                f"Varsayılan değerlerle çalışılacak!"
            )

    def _log_summary(self) -> None:
        """Yüklenen config bölümlerini logla."""
        sections = list(self._data.keys())
        logger.info(f"Config bölümleri: {sections}")

        # Strateji parametrelerini logla (varsa)
        strategies = self._data.get("strategies")
        if strategies:
            for name, params in strategies.items():
                logger.info(f"  strateji.{name}: {params}")

        # Likidite override'larını logla (varsa)
        liq = self._data.get("liquidity_overrides")
        if liq:
            logger.info(f"  liquidity_overrides: {liq}")

    @property
    def is_loaded(self) -> bool:
        """Config dosyası başarıyla yüklendi mi?"""
        return self._is_loaded

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
