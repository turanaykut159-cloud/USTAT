"""Kritik akis testleri — 'bir yeri tamir ederken basini bozuyorsun' onleme.

Bu paket USTAT sistemini end-to-end 12 kritik yoldan test eder:
    1. Emir acilisi (BABA onay > OGUL send > SL/TP)
    2. SL ile kapanis
    3. TP ile kapanis
    4. Manuel kapanis
    5. EOD 17:45 zorunlu kapanis
    6. Hibrit devir (retcode 10027 senaryosu dahil)
    7. Trailing stop guncelleme
    8. Kill-switch L2 (sadece OGUL+Hybrid, manuel dokunulmaz)
    9. Kill-switch L3 (hepsi dahil)
   10. MT5 zengin hata mesaji (retcode -> enrich_message)
   11. Circuit breaker (5 ardisik timeout -> 30sn bloke)
   12. EOD hayalet pozisyon temizligi

Pre-commit hook ve CI bu paketi calistirir. Kirmizi Bolge degisikligi
bu testlerin HEPSINI gecmeden commit edilemez.
"""
