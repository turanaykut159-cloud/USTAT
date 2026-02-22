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
    date(2025, 4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
    date(2025, 5, 1),   # İşçi Bayramı
    date(2025, 5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    date(2025, 7, 15),  # Demokrasi ve Milli Birlik Günü
    date(2025, 8, 30),  # Zafer Bayramı
    date(2025, 10, 29), # Cumhuriyet Bayramı
    # Ramazan ve Kurban Bayramı tarihleri yıla göre değişir
]


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
    if now.date() in HOLIDAYS_2025:
        return False

    current_time = now.time()
    return VIOP_OPEN <= current_time <= VIOP_CLOSE


def is_lunch_break(now: datetime | None = None) -> bool:
    """Öğle arası olup olmadığını kontrol et.

    Args:
        now: Kontrol zamanı.

    Returns:
        Öğle arasıysa True.
    """
    if now is None:
        now = datetime.now()
    current_time = now.time()
    return VIOP_LUNCH_START <= current_time <= VIOP_LUNCH_END


def seconds_to_close(now: datetime | None = None) -> int:
    """Piyasa kapanışına kalan saniye.

    Args:
        now: Şu anki zaman.

    Returns:
        Kalan saniye.
    """
    if now is None:
        now = datetime.now()
    close_dt = now.replace(
        hour=VIOP_CLOSE.hour,
        minute=VIOP_CLOSE.minute,
        second=0,
        microsecond=0,
    )
    diff = (close_dt - now).total_seconds()
    return max(0, int(diff))
