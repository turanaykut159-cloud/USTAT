"""VİOP seans saatleri ve tatil günleri yardımcı fonksiyonları."""

from datetime import datetime, time, date


# VİOP seans saatleri (Türkiye saati, UTC+3)
VIOP_OPEN = time(9, 30)
VIOP_CLOSE = time(18, 15)
VIOP_LUNCH_START = time(12, 30)
VIOP_LUNCH_END = time(14, 0)
# Resmi tatil günleri (yıllık güncellenmeli)
HOLIDAYS_2025 = [
    date(2025, 1, 1),   # Yılbaşı
    date(2025, 3, 30), date(2025, 3, 31), date(2025, 4, 1),  # Ramazan Bayramı
    date(2025, 4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
    date(2025, 5, 1),   # İşçi Bayramı
    date(2025, 5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    date(2025, 6, 6), date(2025, 6, 7), date(2025, 6, 8), date(2025, 6, 9),  # Kurban Bayramı
    date(2025, 7, 15),  # Demokrasi ve Milli Birlik Günü
    date(2025, 8, 30),  # Zafer Bayramı
    date(2025, 10, 29), # Cumhuriyet Bayramı
]

HOLIDAYS_2026 = [
    date(2026, 1, 1),   # Yılbaşı
    date(2026, 3, 19), date(2026, 3, 20), date(2026, 3, 21),  # Ramazan Bayramı (tahmini)
    date(2026, 4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
    date(2026, 5, 1),   # İşçi Bayramı
    date(2026, 5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    date(2026, 5, 26), date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29),  # Kurban Bayramı (tahmini)
    date(2026, 7, 15),  # Demokrasi ve Milli Birlik Günü
    date(2026, 8, 30),  # Zafer Bayramı
    date(2026, 10, 29), # Cumhuriyet Bayramı
]

# Tüm tatil günleri birleşik set (hızlı lookup)
ALL_HOLIDAYS: set[date] = set(HOLIDAYS_2025) | set(HOLIDAYS_2026)


def is_market_open(now: datetime | None = None) -> bool:
    """VİOP piyasasının açık olup olmadığını kontrol et.

    Args:
        now: Kontrol zamanı (varsayılan: şu an).

    Returns:
        Piyasa açıksa True.
    """
    if now is None:
        now = datetime.now()

    # Hafta sonu kontrolü
    if now.weekday() >= 5:
        return False

    # Tatil kontrolü
    if now.date() in ALL_HOLIDAYS:
        return False

    current_time = now.time()
    return VIOP_OPEN <= current_time <= VIOP_CLOSE
