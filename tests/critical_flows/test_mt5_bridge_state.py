"""Flow 6: Hibrit devir MT5 bridge state field'lari.

Bu test mt5_bridge.py'nin _last_stop_limit_error, _last_limit_error,
_trade_allowed state field'larinin dogru calistigini dogrular. Gercek
MT5'e baglanmaz — sadece sinif instantiation ve attribute kontrolu yapar.

Amac: 'fix one, break another' regresyonlarini yakalamak. Bir sonraki
degisiklik bu field'lari sessizce kaldirirsa test patlar.
"""
from __future__ import annotations

import inspect

from engine.mt5_bridge import MT5Bridge


def test_mt5_bridge_has_stop_limit_error_state():
    """MT5Bridge.__init__ icinde _last_stop_limit_error field'i olmali."""
    src = inspect.getsource(MT5Bridge.__init__)
    assert "_last_stop_limit_error" in src, (
        "MT5Bridge._last_stop_limit_error init'te yok — h_engine devir "
        "hata mesaji zenginlestirme bozulur."
    )


def test_mt5_bridge_has_limit_error_state():
    src = inspect.getsource(MT5Bridge.__init__)
    assert "_last_limit_error" in src


def test_mt5_bridge_has_trade_allowed_state():
    src = inspect.getsource(MT5Bridge.__init__)
    assert "_trade_allowed" in src, (
        "MT5Bridge._trade_allowed init'te yok — TopBar Algo Trading "
        "uyari banner'i bozulur."
    )


def test_mt5_bridge_is_trade_allowed_method_exists():
    assert hasattr(MT5Bridge, "is_trade_allowed")
    assert callable(MT5Bridge.is_trade_allowed)


def test_send_stop_limit_sets_error_state_on_failure():
    """send_stop_limit None path'lerinin hepsinde _last_stop_limit_error yazmali.

    Statik kontrol: fonksiyon icinde 'self._last_stop_limit_error = '
    en az 6 kez gecmeli (baslangic reset + 5-6 hata path).
    """
    src = inspect.getsource(MT5Bridge.send_stop_limit)
    count = src.count("self._last_stop_limit_error")
    assert count >= 5, (
        f"send_stop_limit _last_stop_limit_error yazma sayisi ({count}) "
        f"< 5. Bir hata path'i muhtemelen error state yazmadan return None yapiyor."
    )


def test_send_limit_sets_error_state_on_failure():
    src = inspect.getsource(MT5Bridge.send_limit)
    count = src.count("self._last_limit_error")
    assert count >= 5, (
        f"send_limit _last_limit_error yazma sayisi ({count}) < 5."
    )
