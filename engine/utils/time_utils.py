"""VİOP seans saatleri ve tatil günleri yardımcı fonksiyonları."""

from datetime import datetime, time, date


# VİOP seans saatleri (Türkiye saati, UTC+3)
VIOP_OPEN = time(9, 30)
VIOP_CLOSE = time(18, 15)
VIOP_LUNCH_START = time(12, 30)
VIOP_LUNCH_END = time(14, 0)
VIOP_HALF_DAY_CLOSE = time(12, 40)  # v5.9.2: Arefe günü VİOP kapanış saati
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
    date(2026, 3, 19),  # Ramazan Bayramı Arefesi (yarım gün — HALF_DAYS'de)
    date(2026, 3, 20), date(2026, 3, 21), date(2026, 3, 22),  # Ramazan Bayramı
    date(2026, 4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
    date(2026, 5, 1),   # İşçi Bayramı
    date(2026, 5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29), date(2026, 5, 30),  # Kurban Bayramı
    date(2026, 7, 15),  # Demokrasi ve Milli Birlik Günü
    date(2026, 8, 30),  # Zafer Bayramı
    date(2026, 10, 29), # Cumhuriyet Bayramı
]

HOLIDAYS_2027 = [
    date(2027, 1, 1),   # Yılbaşı
    date(2027, 3, 9), date(2027, 3, 10), date(2027, 3, 11),  # Ramazan Bayramı (tahmini)
    date(2027, 4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
    date(2027, 5, 1),   # İşçi Bayramı
    date(2027, 5, 16), date(2027, 5, 17), date(2027, 5, 18), date(2027, 5, 19),  # Kurban Bayramı (tahmini)
    date(2027, 5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    date(2027, 7, 15),  # Demokrasi ve Milli Birlik Günü
    date(2027, 8, 30),  # Zafer Bayramı
    date(2027, 10, 29), # Cumhuriyet Bayramı
]

# Tüm tatil günleri birleşik set (hızlı lookup)
ALL_HOLIDAYS: set[date] = set(HOLIDAYS_2025) | set(HOLIDAYS_2026) | set(HOLIDAYS_2027)

# v5.9.2: Yarım gün (arefe) günleri — VİOP 12:40'ta kapanır.
# VİOP kuralı: Arefe günü vadeye denk gelirse, vade bir önceki iş gününe çekilir.
HALF_DAYS_2025: list[date] = [
    date(2025, 3, 29),  # Ramazan Bayramı Arefesi
    date(2025, 6, 5),   # Kurban Bayramı Arefesi
    date(2025, 10, 28), # Cumhuriyet Bayramı Arefesi
]
HALF_DAYS_2026: list[date] = [
    date(2026, 3, 19),  # Ramazan Bayramı Arefesi
    date(2026, 5, 26),  # Kurban Bayramı Arefesi
    date(2026, 10, 28), # Cumhuriyet Bayramı Arefesi
]
HALF_DAYS_2027: list[date] = [
    date(2027, 3, 8),   # Ramazan Bayramı Arefesi
    date(2027, 5, 15),  # Kurban Bayramı Arefesi
    date(2027, 10, 28), # Cumhuriyet Bayramı Arefesi
]
ALL_HALF_DAYS: set[date] = set(HALF_DAYS_2025) | set(HALF_DAYS_2026) | set(HALF_DAYS_2027)


def is_half_day(d: date | None = None) -> bool:
    """Verilen tarih yarım gün (arefe) mü?

    VİOP yarım günlerde 12:40'ta kapanır, akşam seansı yoktur.
    """
    if d is None:
        d = date.today()
    return d in ALL_HALF_DAYS


def get_close_time(d: date | None = None) -> time:
    """Verilen tarih için VİOP kapanış saatini döndür."""
    if d is None:
        d = date.today()
    if d in ALL_HALF_DAYS:
        return VIOP_HALF_DAY_CLOSE
    return VIOP_CLOSE


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

    # Tatil kontrolü (arefe günleri hariç — yarım gün açık)
    today_date = now.date()
    if today_date in ALL_HOLIDAYS and today_date not in ALL_HALF_DAYS:
        return False

    current_time = now.time()
    close = VIOP_HALF_DAY_CLOSE if today_date in ALL_HALF_DAYS else VIOP_CLOSE
    return VIOP_OPEN <= current_time <= close
