"""Konfigürasyon yönetimi.

JSON dosyasından ve ortam değişkenlerinden konfigürasyon okur.
"""

import json
import os
import threading
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
        self._rw_lock = threading.Lock()  # Thread safety: set/save/get koruması
        self._load()

    def _load(self) -> None:
        """Konfigürasyon dosyasını yükle.

        #245 OP-Q boot autorepair (18 Nis 2026 sistemik NULL-tail FS bozulmasi sonrasi):
        json.load() oncesi ham byte null-byte taramasi yapilir. NULL byte kuyrugu
        tespit edilirse: (a) bozuk dosyanin yedegi alinir, (b) tail null'lari temizlenir,
        (c) yeniden parse denenir. Boylece engine boot crash yerine auto-recover.
        Dosyanin icerik kismi bozuksa (scattered null / invalid JSON) fallback
        `self._data = {}` ile devam eder.
        """
        if not self._path.exists():
            logger.critical(
                f"Konfigürasyon dosyası bulunamadı: {self._path} — "
                f"Varsayılan değerlerle çalışılacak!"
            )
            return

        try:
            raw_bytes = self._path.read_bytes()
            null_count = raw_bytes.count(b"\x00")

            if null_count > 0:
                # Tail-only null mu, scattered mi?
                stripped = raw_bytes.rstrip(b"\x00")
                tail_run = len(raw_bytes) - len(stripped)
                if tail_run == null_count:
                    # TAIL-ONLY — autorepair mumkun
                    logger.critical(
                        f"[OP-Q AUTOREPAIR] Konfigurasyonda {null_count} tail NULL byte "
                        f"tespit edildi: {self._path} — otomatik tamir ediliyor"
                    )
                    from datetime import datetime as _dt
                    stamp = _dt.now().strftime("%Y%m%d-%H%M%S")
                    backup = self._path.with_suffix(
                        self._path.suffix + f".corrupt-boot-{stamp}"
                    )
                    try:
                        backup.write_bytes(raw_bytes)
                        logger.warning(f"[OP-Q] Yedek: {backup}")
                    except OSError as bexc:
                        logger.error(f"[OP-Q] Yedek yazilmadi: {bexc}")
                    # Temiz icerigi yaz (trailing newline ile)
                    clean_bytes = stripped if stripped.endswith(b"\n") else stripped + b"\n"
                    try:
                        self._path.write_bytes(clean_bytes)
                        logger.warning(
                            f"[OP-Q] Tail NULL temizlendi: "
                            f"{len(raw_bytes)} -> {len(clean_bytes)} byte"
                        )
                    except OSError as wexc:
                        logger.error(f"[OP-Q] Autorepair yazim hatasi: {wexc}")
                        self._data = {}
                        return
                else:
                    # SCATTERED null — guvenli autorepair zor, skip
                    logger.critical(
                        f"[OP-Q] Konfigurasyonda {null_count} SCATTERED NULL byte "
                        f"(tail_run={tail_run}) — autorepair atlandi, manuel inceleme gerek"
                    )
                    self._data = {}
                    return

            # Normal parse (autorepair sonrasi veya null-free)
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

    def set(self, key: str, value) -> None:
        """Konfigürasyon değeri güncelle (bellekte, thread-safe).

        Args:
            key: Konfigürasyon anahtarı (nokta ile ayrılmış).
            value: Yeni değer.
        """
        with self._rw_lock:
            keys = key.split(".")
            target = self._data
            for k in keys[:-1]:
                if k not in target or not isinstance(target[k], dict):
                    target[k] = {}
                target = target[k]
            target[keys[-1]] = value
        logger.info(f"Config güncellendi: {key} = {value}")

    def save(self) -> None:
        """Bellekteki konfigürasyonu JSON dosyasına kaydet (thread-safe)."""
        with self._rw_lock:
            try:
                with open(self._path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                logger.info(f"Config dosyaya kaydedildi: {self._path}")
            except OSError as exc:
                logger.error(f"Config kayıt hatası: {self._path} — {exc}")
                raise
