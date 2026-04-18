"""v5.4.1: Sembol seviyesinde netting kilidi.

Cross-motor netting race condition'ı önlemek için paylaşılan kilit mekanizması.
OĞUL sinyal üretimi ve H-Engine transfer işlemi aynı kilidi paylaşır.

v5.8.1: Timeout mekanizması eklendi — crash durumunda kilitler otomatik temizlenir.

Kullanım:
    from engine.netting_lock import acquire_symbol, release_symbol, is_symbol_locked

    if acquire_symbol("F_THYAO", owner="ogul"):
        try:
            # sinyal üret veya pozisyon aç
            ...
        finally:
            release_symbol("F_THYAO", owner="ogul")
"""

import time as _time
import threading
from engine.logger import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_locked_symbols: dict[str, dict] = {}  # symbol → {"owner": str, "acquired_at": float}

# Kilit timeout — #265 R-11 KARAR #11: config'den override desteği
# Default 120sn (2 dakika); sanity_thresholds.netting_lock_timeout_sec ile overrideable
LOCK_TIMEOUT_SEC: float = 120.0


def set_lock_timeout(seconds: float) -> None:
    """Runtime'da lock timeout değeri güncelle (config-driven).

    Boot sırasında engine config'i yüklendikten sonra çağrılır:
        cfg.get("sanity_thresholds.netting_lock_timeout_sec", 120.0)

    Args:
        seconds: Yeni timeout (en az 30 sn, en fazla 600 sn).
    """
    global LOCK_TIMEOUT_SEC
    clamped = max(30.0, min(600.0, float(seconds)))
    LOCK_TIMEOUT_SEC = clamped
    logger.info(f"Netting lock timeout güncellendi: {clamped}sn")


def _cleanup_stale() -> None:
    """Süresi dolmuş kilitleri temizle (her acquire/is_locked çağrısında çalışır)."""
    now = _time.monotonic()
    stale = [
        sym for sym, info in _locked_symbols.items()
        if now - info["acquired_at"] > LOCK_TIMEOUT_SEC
    ]
    for sym in stale:
        owner = _locked_symbols[sym]["owner"]
        age = now - _locked_symbols[sym]["acquired_at"]
        del _locked_symbols[sym]
        logger.warning(
            f"Netting kilit STALE TEMİZLİK: {sym} ← {owner} "
            f"({age:.0f}sn > {LOCK_TIMEOUT_SEC:.0f}sn timeout)"
        )


def acquire_symbol(symbol: str, owner: str) -> bool:
    """Sembol kilidini al (atomik + timeout korumalı).

    Args:
        symbol: Kilitlenecek sembol (örn. "F_THYAO").
        owner: Kilidi alan motor/bileşen (örn. "ogul", "h_engine", "manuel").

    Returns:
        True ise kilit alındı, False ise sembol başka motor tarafından kilitli.
    """
    with _lock:
        _cleanup_stale()

        if symbol in _locked_symbols:
            current_owner = _locked_symbols[symbol]["owner"]
            if current_owner != owner:
                logger.debug(
                    f"Netting kilit RED: {symbol} zaten {current_owner} tarafından kilitli "
                    f"(talep eden: {owner})"
                )
                return False
            # Aynı owner reentrant acquire — KILIT GECERLI SAYILIR (True) ama
            # acquired_at DEĞİŞTİRİLMEZ (YB-400 fix). Aksi halde motor crash/hang olsa bile
            # periyodik re-acquire çağrıları timestamp'i tazeler → stale timeout hiç tetiklenmez
            # → infinit lock riski. Şimdi ilk acquire zamanı korunur, 120sn timeout garantidir.
            logger.debug(
                f"Netting kilit REENTRANT: {symbol} ← {owner} "
                f"(acquired_at korunuyor — stale timeout orjinal zamandan ölçülür)"
            )
            return True

        _locked_symbols[symbol] = {
            "owner": owner,
            "acquired_at": _time.monotonic(),
        }
        logger.debug(f"Netting kilit AL: {symbol} → {owner}")
        return True


def release_symbol(symbol: str, owner: str) -> None:
    """Sembol kilidini serbest bırak.

    Args:
        symbol: Serbest bırakılacak sembol.
        owner: Kilidi bırakan motor (sadece kendi kilidi varsa serbest bırakır).
    """
    with _lock:
        if symbol in _locked_symbols and _locked_symbols[symbol]["owner"] == owner:
            del _locked_symbols[symbol]
            logger.debug(f"Netting kilit SERBEST: {symbol} ← {owner}")


def is_symbol_locked(symbol: str, exclude_owner: str | None = None) -> bool:
    """Sembol başka bir motor tarafından kilitli mi?

    Args:
        symbol: Kontrol edilecek sembol.
        exclude_owner: Bu owner'ı hariç tut (kendi kilidi sayılmaz).

    Returns:
        True ise sembol kilitli (başka biri tarafından).
    """
    with _lock:
        _cleanup_stale()

        if symbol not in _locked_symbols:
            return False
        if exclude_owner and _locked_symbols[symbol]["owner"] == exclude_owner:
            return False
        return True


def get_locked_symbols() -> dict[str, str]:
    """Tüm kilitli sembolleri ve sahiplerini döndür (debug/monitoring).

    Returns:
        {symbol: owner} sözlüğünün kopyası.
    """
    with _lock:
        _cleanup_stale()
        return {sym: info["owner"] for sym, info in _locked_symbols.items()}
