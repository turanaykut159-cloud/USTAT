"""Flow 10: MT5 retcode -> enrich_message zengin hata mesaji.

Bu test ailesi engine.mt5_errors modulunun butun kritik path'lerini dogrular:
    - 10027 (Client disables AT) -> Algo Trading butonu uyarisi
    - 10035 (Invalid order) -> GCM VIOP native STOP reddi
    - Bilinmeyen retcode -> fallback mesaji
    - Detail dict yerine None verilirse crash olmamali
    - Retcode'suz sadece last_error varsa backend yine zenginlestirebilmeli
"""
from __future__ import annotations

from engine.mt5_errors import (
    describe_mt5_error,
    enrich_message,
    user_action_for,
)


def test_retcode_10027_algo_disabled():
    """10027: Algo Trading kapali -> cok satirli kullanici rehberi icerir."""
    msg = enrich_message(
        "Stop trailing emri gönderilemedi — devir iptal",
        {"retcode": 10027, "comment": "Client AT off"},
    )
    assert "Stop trailing emri gönderilemedi" in msg
    assert "Algo Trading" in msg
    assert "Ctrl+E" in msg
    assert "10027" in msg
    assert "TRADE_RETCODE_CLIENT_DISABLES_AT" in msg


def test_retcode_10035_invalid_order():
    """10035: GCM VIOP native STOP reddi -> stop-limit oneri icerir."""
    info = describe_mt5_error(10035)
    assert info["code"] == "TRADE_RETCODE_INVALID_ORDER"
    msg = enrich_message("Emir reddedildi", {"retcode": 10035, "comment": ""})
    assert "10035" in msg


def test_unknown_retcode_does_not_crash():
    """Bilinmeyen retcode verilirse fallback mesaji doner, exception atmaz."""
    msg = enrich_message("Hata", {"retcode": 99999, "comment": "unknown"})
    assert "Hata" in msg
    assert "99999" in msg


def test_none_detail_returns_base_only():
    """Detail None ise sadece base mesaji doner."""
    msg = enrich_message("Temel hata", None)
    assert msg == "Temel hata"


def test_empty_detail_returns_base_only():
    """Detail bos dict ise sadece base mesaji doner."""
    msg = enrich_message("Temel hata", {})
    assert msg == "Temel hata"


def test_last_error_path():
    """retcode olmadan sadece last_error varsa mesaja eklenmeli."""
    msg = enrich_message("X basarisiz", {"last_error": "MT5 bağlantısı yok"})
    assert "X basarisiz" in msg
    assert "MT5 bağlantısı yok" in msg


def test_exception_path():
    """Exception string verilirse gosterilmeli."""
    msg = enrich_message("Y patladi", {"exception": "ConnectionResetError: [WinError 10054]"})
    assert "Y patladi" in msg
    assert "ConnectionResetError" in msg


def test_user_action_for_common_codes():
    """user_action_for() kritik retcode'lar icin bir action dondurur."""
    assert user_action_for(10027) is not None  # USER_FIX
    assert user_action_for(10035) is not None  # RETRY_DIFFERENT
