"""ÜSTAT Lifecycle Guard — Atomik Yaşam Döngüsü Koruyucusu (v1.0).

Engine'in yaşam döngüsünü TEK NOKTADAN kontrol eder.
Tüm emir gönderme, pozisyon kapama, MT5 yazma işlemleri bu koruyucudan
geçmek ZORUNDADIR.

Çözülen sorunlar:
    1. Electron kapalıyken MT5'e emir gitmesi (race condition)
    2. Watchdog'un yanlış restart tetiklemesi (false positive)
    3. Kapanış sırasında uçuştaki emirlerin tamamlanması
    4. Signal handler eksikliği (SIGTERM graceful shutdown)

Kullanım:
    guard = LifecycleGuard()
    guard.activate()

    # Emir göndermeden ÖNCE:
    if guard.can_send_order():
        mt5.send_order(...)

    # Kapanışta:
    guard.begin_shutdown("kullanıcı isteği")  # Atomik — yeni emir anında engellenir

Tasarım:
    - threading.Event tabanlı — lock-free, anında yanıt
    - Monotonic clock — sistem saati değişikliklerinden etkilenmez
    - Shutdown state GERİ ALINAMAZ (monotonluk prensibi)

BÖLGE: Kırmızı (risk koruması)
"""

from __future__ import annotations

import signal
import threading
import time as _time
from enum import IntEnum
from typing import Callable

from engine.logger import get_logger

logger = get_logger(__name__)


class EngineState(IntEnum):
    """Engine durumları — sadece yukarı gider (monotonluk)."""
    CREATED = 0      # Henüz başlatılmadı
    STARTING = 1     # Başlatma aşamasında (MT5 bağlantısı bekleniyor)
    RUNNING = 2      # Normal çalışma — emir gönderilebilir
    SHUTTING_DOWN = 3 # Kapanma başladı — YENİ EMİR YASAK, mevcut tamamlanabilir
    STOPPED = 4      # Tamamen durdu — hiçbir işlem yapılamaz


class ShutdownReason:
    """Kapanma nedenleri — log ve analiz için."""
    USER_REQUEST = "kullanıcı_isteği"
    SIGTERM = "SIGTERM_sinyali"
    SIGINT = "SIGINT_sinyali"
    API_SHUTDOWN = "API_shutdown"
    WATCHDOG = "watchdog_restart"
    DB_ERROR = "DB_hatası"
    MT5_LOST = "MT5_bağlantı_kaybı"
    KILL_SWITCH = "kill_switch_L3"
    HARD_DRAWDOWN = "felaket_drawdown"
    UNKNOWN = "bilinmeyen"


class LifecycleGuard:
    """Engine yaşam döngüsü koruyucusu.

    Thread-safe, atomik durum geçişleri.
    Tüm emir/pozisyon işlemleri bu sınıftan onay alır.

    Attributes:
        state: Mevcut engine durumu (EngineState).
        shutdown_reason: Kapanma nedeni (None ise henüz kapanmadı).
        active_orders: Şu anda uçuşta olan emir sayısı.
    """

    def __init__(self) -> None:
        self._state = EngineState.CREATED
        self._lock = threading.RLock()
        self._shutdown_event = threading.Event()
        self._order_gate = threading.Event()  # set = emirler geçebilir
        self._active_orders = 0
        self._active_orders_lock = threading.Lock()
        self._shutdown_reason: str | None = None
        self._shutdown_time: float | None = None
        self._on_shutdown_callbacks: list[Callable] = []
        self._original_sigterm = None
        self._original_sigint = None

    # ═══════════════════════════════════════════════════════════════
    #  DURUM SORGULAMA
    # ═══════════════════════════════════════════════════════════════

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def is_running(self) -> bool:
        """Engine aktif mi? (RUNNING durumunda)"""
        return self._state == EngineState.RUNNING

    @property
    def is_alive(self) -> bool:
        """Engine canlı mı? (STARTING veya RUNNING)"""
        return self._state in (EngineState.STARTING, EngineState.RUNNING)

    @property
    def is_shutdown(self) -> bool:
        """Kapanma başladı mı?"""
        return self._state >= EngineState.SHUTTING_DOWN

    @property
    def shutdown_reason(self) -> str | None:
        return self._shutdown_reason

    @property
    def active_orders(self) -> int:
        return self._active_orders

    # ═══════════════════════════════════════════════════════════════
    #  DURUM GEÇİŞLERİ
    # ═══════════════════════════════════════════════════════════════

    def activate(self) -> None:
        """Engine'i STARTING durumuna geçir."""
        with self._lock:
            if self._state != EngineState.CREATED:
                logger.warning(
                    f"LifecycleGuard.activate() — zaten {self._state.name} durumunda"
                )
                return
            self._state = EngineState.STARTING
            logger.info("LifecycleGuard: STARTING")

    def set_running(self) -> None:
        """Engine'i RUNNING durumuna geçir — emirler artık gönderilebilir."""
        with self._lock:
            if self._state != EngineState.STARTING:
                logger.warning(
                    f"LifecycleGuard.set_running() — beklenmeyen durum: {self._state.name}"
                )
                return
            self._state = EngineState.RUNNING
            self._order_gate.set()  # Emir kapısını aç
            logger.info("LifecycleGuard: RUNNING — emir kapısı AÇIK")

    def begin_shutdown(self, reason: str = ShutdownReason.UNKNOWN) -> None:
        """Kapanmayı başlat — YENİ EMİR ANINDA ENGELLENIR.

        Bu metod atomiktir ve tekrar çağrılabilir (idempotent).
        Kapanma durumu GERİ ALINAMAZ (monotonluk prensibi).

        Args:
            reason: Kapanma nedeni (ShutdownReason sabitlerinden biri).
        """
        with self._lock:
            if self._state >= EngineState.SHUTTING_DOWN:
                return  # Zaten kapanıyor

            self._state = EngineState.SHUTTING_DOWN
            self._shutdown_reason = reason
            self._shutdown_time = _time.monotonic()

            # EMİR KAPISINI KAPAT — atomik, anında etkili
            self._order_gate.clear()
            self._shutdown_event.set()

            logger.critical(
                f"LifecycleGuard: SHUTTING_DOWN — neden: {reason} | "
                f"uçuştaki emir: {self._active_orders}"
            )

        # Callback'leri çağır (lock dışında — deadlock önleme)
        for cb in self._on_shutdown_callbacks:
            try:
                cb(reason)
            except Exception as exc:
                logger.error(f"Shutdown callback hatası: {exc}")

    def set_stopped(self) -> None:
        """Engine'i STOPPED durumuna geçir — tamamen bitti."""
        with self._lock:
            self._state = EngineState.STOPPED
            self._order_gate.clear()
            self._shutdown_event.set()
            logger.info("LifecycleGuard: STOPPED")

    # ═══════════════════════════════════════════════════════════════
    #  EMİR KAPISI (ORDER GATE)
    # ═══════════════════════════════════════════════════════════════

    def can_send_order(self) -> bool:
        """Emir gönderilebilir mi?

        Returns:
            True ise emir gönderilebilir, False ise YASAK.
        """
        return self._order_gate.is_set() and self._state == EngineState.RUNNING

    def order_enter(self) -> bool:
        """Emir göndermeye başla — aktif emir sayacını artır.

        Returns:
            True ise devam edebilir, False ise emir engellendi.

        Kullanım:
            if guard.order_enter():
                try:
                    mt5.send_order(...)
                finally:
                    guard.order_exit()
        """
        if not self.can_send_order():
            logger.warning(
                f"Emir ENGELLENDİ — durum: {self._state.name}, "
                f"neden: {self._shutdown_reason or 'emir kapısı kapalı'}"
            )
            return False

        with self._active_orders_lock:
            # Çift kontrol (double-check locking)
            if not self._order_gate.is_set():
                return False
            self._active_orders += 1

        return True

    def order_exit(self) -> None:
        """Emir tamamlandı — aktif emir sayacını azalt."""
        with self._active_orders_lock:
            self._active_orders = max(0, self._active_orders - 1)

    def wait_for_orders_to_complete(self, timeout: float = 10.0) -> bool:
        """Uçuştaki emirlerin tamamlanmasını bekle.

        Args:
            timeout: Maksimum bekleme süresi (saniye).

        Returns:
            True ise tüm emirler tamamlandı, False ise timeout.
        """
        deadline = _time.monotonic() + timeout
        while self._active_orders > 0:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                logger.error(
                    f"Uçuştaki emir timeout ({timeout}s): "
                    f"{self._active_orders} emir hâlâ aktif"
                )
                return False
            _time.sleep(0.1)

        return True

    # ═══════════════════════════════════════════════════════════════
    #  SİNYAL İŞLEYİCİLER (SIGNAL HANDLERS)
    # ═══════════════════════════════════════════════════════════════

    def install_signal_handlers(self, engine_stop_fn: Callable | None = None) -> None:
        """OS sinyal işleyicilerini kur (SIGTERM, SIGINT).

        Args:
            engine_stop_fn: Engine.stop() referansı — sinyal gelince çağrılır.
        """
        self._engine_stop_fn = engine_stop_fn

        def _handle_sigterm(signum, frame):
            sig_name = "SIGTERM" if signum == signal.SIGTERM else f"SIG{signum}"
            logger.critical(f"OS sinyali alındı: {sig_name} — graceful shutdown başlatılıyor")
            self.begin_shutdown(ShutdownReason.SIGTERM)
            if self._engine_stop_fn:
                try:
                    self._engine_stop_fn(reason=f"OS sinyali: {sig_name}")
                except Exception as exc:
                    logger.error(f"Signal handler engine.stop() hatası: {exc}")

        def _handle_sigint(signum, frame):
            logger.critical("SIGINT (Ctrl+C) alındı — graceful shutdown başlatılıyor")
            self.begin_shutdown(ShutdownReason.SIGINT)
            if self._engine_stop_fn:
                try:
                    self._engine_stop_fn(reason="Ctrl+C (SIGINT)")
                except Exception as exc:
                    logger.error(f"Signal handler engine.stop() hatası: {exc}")

        try:
            self._original_sigterm = signal.getsignal(signal.SIGTERM)
            self._original_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGTERM, _handle_sigterm)
            signal.signal(signal.SIGINT, _handle_sigint)
            logger.info("Signal handlers kuruldu: SIGTERM, SIGINT")
        except (OSError, ValueError) as exc:
            # Worker thread'den signal handler kurulamaz — sadece main thread'den
            logger.warning(f"Signal handler kurulamadı (muhtemelen worker thread): {exc}")

    def uninstall_signal_handlers(self) -> None:
        """OS sinyal işleyicilerini geri yükle."""
        try:
            if self._original_sigterm is not None:
                signal.signal(signal.SIGTERM, self._original_sigterm)
            if self._original_sigint is not None:
                signal.signal(signal.SIGINT, self._original_sigint)
        except (OSError, ValueError):
            pass

    # ═══════════════════════════════════════════════════════════════
    #  CALLBACK YÖNETİMİ
    # ═══════════════════════════════════════════════════════════════

    def on_shutdown(self, callback: Callable[[str], None]) -> None:
        """Kapanma callback'i ekle.

        Args:
            callback: Kapanma nedeni (str) alan fonksiyon.
        """
        self._on_shutdown_callbacks.append(callback)

    # ═══════════════════════════════════════════════════════════════
    #  WATCHDOG İÇİN GELİŞMİŞ HEARTBEAT
    # ═══════════════════════════════════════════════════════════════

    def get_health_status(self) -> dict:
        """Watchdog için sağlık durumu.

        Returns:
            Sözlük: state, active_orders, shutdown_reason, uptime_secs
        """
        uptime = None
        if self._shutdown_time is not None:
            uptime = _time.monotonic() - self._shutdown_time

        return {
            "state": self._state.name,
            "is_running": self.is_running,
            "can_send_orders": self.can_send_order(),
            "active_orders": self._active_orders,
            "shutdown_reason": self._shutdown_reason,
            "shutdown_elapsed_secs": uptime,
        }
