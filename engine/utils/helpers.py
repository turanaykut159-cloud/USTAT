"""Ortak yardımcı fonksiyonlar.

Birden fazla engine modülünde (baba, ogul, ustat) kullanılan
NaN-güvenli numpy yardımcıları.

Madde 3.1: Tekrarlanan fonksiyonların tek noktada birleştirilmesi.
"""

from __future__ import annotations

import numpy as np


def last_valid(arr: np.ndarray) -> float | None:
    """Dizinin son NaN-olmayan değeri.

    Args:
        arr: NumPy dizisi.

    Returns:
        Son geçerli float değer, yoksa None.
    """
    for i in range(len(arr) - 1, -1, -1):
        if not np.isnan(arr[i]):
            return float(arr[i])
    return None


def last_n_valid(arr: np.ndarray, n: int) -> list[float]:
    """Son *n* adet NaN-olmayan değer (eskiden yeniye).

    Args:
        arr: NumPy dizisi.
        n: İstenen değer sayısı.

    Returns:
        Eskiden yeniye sıralı float listesi.
    """
    result: list[float] = []
    for i in range(len(arr) - 1, -1, -1):
        if not np.isnan(arr[i]):
            result.append(float(arr[i]))
            if len(result) >= n:
                break
    result.reverse()
    return result


def nanmean(arr: np.ndarray) -> float:
    """NaN dışı ortalama (tümü NaN ise 0.0).

    Args:
        arr: NumPy dizisi.

    Returns:
        Ortalama değer (float).
    """
    valid = arr[~np.isnan(arr)]
    return float(np.mean(valid)) if len(valid) > 0 else 0.0
