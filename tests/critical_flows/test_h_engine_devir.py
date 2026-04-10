"""Flow 6b: h_engine devir akisinda zengin hata mesaji.

h_engine.py'nin hibrit devir fonksiyonunun stop_limit hatasi ve
native_sltp hatasi durumunda enrich_message() cagirdigini dogrular.
Bu testler gercek HEngine instance olusturmadan statik kontrol yapar.
"""
from __future__ import annotations

import inspect

from engine import h_engine as hm


def test_h_engine_imports_enrich_message():
    """h_engine modulunde enrich_message importu olmali."""
    assert hasattr(hm, "enrich_message"), (
        "h_engine 'enrich_message' import etmiyor — devir hata mesaji "
        "zenginlestirilemez."
    )


def test_h_engine_calls_enrich_on_stop_limit_failure():
    """HEngine sinifinda enrich_message cagrisi var mi?"""
    src = inspect.getsource(hm.HEngine)
    assert "enrich_message(" in src
    # _last_stop_limit_error okuniyor mu?
    assert "_last_stop_limit_error" in src, (
        "HEngine _last_stop_limit_error okumaz — trailing hatasi "
        "sade mesaj gosterir (retcode 10027 maskelenir)."
    )


def test_h_engine_calls_enrich_on_native_sltp_failure():
    """Native SLTP hata path'i de enrich_message kullanmali."""
    src = inspect.getsource(hm.HEngine)
    # _last_modify_error ile enrich_message birlikte gecmeli
    assert "_last_modify_error" in src
    # Eski manuel concat kaldirildi mi?
    assert "result[\"message\"] += f\" — MT5:" not in src, (
        "Eski manuel hata concat kodu hala var — enrich_message'e tam gecis "
        "tamamlanmamis, iki farkli format yan yana yaziyor."
    )
