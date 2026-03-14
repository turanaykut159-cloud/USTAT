"""v5.4.1: Sembol seviyesinde netting kilidi.

Cross-motor netting race condition'ı önlemek için paylaşılan kilit mekanizması.
OĞUL sinyal üretimi ve H-Engine transfer işlemi aynı kilidi paylaşır.

Kullanım:
    from engine.netting_lock import acquire_symbol, release_symbol, is_symbol_locked

    if acquire_symbol("F_THYAO", owner="ogul"):
        try:
            # sinyal üret veya pozisyon aç
            ...
        finally:
            release_symbol("F_THYAO", owner="ogul")
"""

import threading
from engine.logger import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_locked_symbols: dict[str, str] = {}  # symbol → owner


def acquire_symbol(symbol: str, owner: str) -> bool:
    """Sembol kilidini al (atomik).

    Args:
        symbol: Kilitlenecek sembol (örn. "F_THYAO").
        owner: Kilidi alan motor/bileşen (örn. "ogul", "h_engine", "manuel").

    Returns:
        True ise kilit alındı, False ise sembol başka motor tarafından kilitli.
    """
    with _lock:
        if symbol in _locked_symbols:
            current_owner = _locked_symbols[symbol]
            if current_owner != owner:
                logger.debug(
                    f"Netting kilit RED: {symbol} zaten {current_owner} tarafından kilitli "
                    f"(talep eden: {owner})"
                )
                return False
            # Aynı owner tekrar kilitliyorsa izin ver (reentrant)
            return True
        _locked_symbols[symbol] = owner
        logger.debug(f"Netting kilit AL: {symbol} → {owner}")
        return True


def release_symbol(symbol: str, owner: str) -> None:
    """Sembol kilidini serbest bırak.

    Args:
        symbol: Serbest bırakılacak sembol.
        owner: Kilidi bırakan motor (sadece kendi kilidi varsa serbest bırakır).
    """
    with _lock:
        if symbol in _locked_symbols and _locked_symbols[symbol] == owner:
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
        if symbol not in _locked_symbols:
            return False
        if exclude_owner and _locked_symbols[symbol] == exclude_owner:
            return False
        return True


def get_locked_symbols() -> dict[str, str]:
    """Tüm kilitli sembolleri ve sahiplerini döndür (debug/monitoring).

    Returns:
        {symbol: owner} sözlüğünün kopyası.
    """
    with _lock:
        return dict(_locked_symbols)
