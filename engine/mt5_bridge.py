"""MetaTrader 5 bağlantı katmanı.

MT5 terminali ile iletişim kurar, piyasa verisi çeker,
emir gönderir ve pozisyon bilgilerini yönetir.

Desteklenen kontratlar (15 adet VİOP pay vadeli):
    F_THYAO, F_AKBNK, F_ASELS, F_TCELL, F_HALKB, F_PGSUS, F_GUBRF, F_EKGYO,
    F_SOKM, F_TKFEN, F_OYAKC, F_BRSAN, F_AKSEN, F_ASTOR, F_KONTR

Reconnect: Bağlantı koptuğunda 5 deneme, artan bekleme (2-4-8-16-32 sn).
Heartbeat : 10 saniyede bir bağlantı kontrolü.
"""

from __future__ import annotations

import concurrent.futures
import math
import threading
import time as _time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import MetaTrader5 as mt5
import pandas as pd

from engine.config import Config
from engine.logger import get_logger

logger = get_logger(__name__)

# ── İzlenen 15 kontrat ──────────────────────────────────────────────
WATCHED_SYMBOLS: list[str] = [
    "F_THYAO", "F_AKBNK", "F_ASELS", "F_TCELL", "F_HALKB",
    "F_PGSUS", "F_GUBRF", "F_EKGYO", "F_SOKM",  "F_TKFEN",
    "F_OYAKC", "F_BRSAN", "F_AKSEN", "F_ASTOR", "F_KONTR",
]

# ── Reconnect sabitleri ─────────────────────────────────────────────
MAX_RETRIES_LAUNCH: int = 5       # ilk başlatma (launch=True) deneme sayısı
MAX_RETRIES_RECONNECT: int = 3    # reconnect (launch=False) deneme sayısı
BASE_WAIT: float = 2.0            # ilk bekleme (saniye)
HEARTBEAT_INTERVAL: float = 10.0  # saniye
MT5_CALL_TIMEOUT: float = 8.0     # v5.4.1: MT5 API çağrı timeout (saniye)

# ── Circuit Breaker sabitleri ─────────────────────────────────────
CB_FAILURE_THRESHOLD: int = 5       # v5.4.1: Ardışık hata eşiği → devre kesilir
CB_COOLDOWN_SECS: float = 30.0     # v5.4.1: Devre kesildikten sonra bekleme (sn)
CB_PROBE_TIMEOUT: float = 5.0      # v5.4.1: Probe çağrısı timeout (sn)


# ── Veri sınıfları ───────────────────────────────────────────────────
@dataclass
class AccountInfo:
    """Hesap bilgisi."""
    login: int
    server: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    currency: str


@dataclass
class SymbolInfo:
    """Sembol (kontrat) bilgisi."""
    name: str
    point: float               # fiyat adımı
    trade_contract_size: float  # kontrat çarpanı
    trade_tick_value: float    # tick değeri (TL)
    volume_min: float
    volume_max: float
    volume_step: float
    bid: float
    ask: float
    spread: int
    session_price_limit_max: float = 0.0  # günlük tavan fiyat
    session_price_limit_min: float = 0.0  # günlük taban fiyat


@dataclass
class Tick:
    """Anlık fiyat bilgisi."""
    symbol: str
    bid: float
    ask: float
    spread: float
    time: datetime


# ═════════════════════════════════════════════════════════════════════
class MT5Bridge:
    """MetaTrader 5 bağlantı yöneticisi.

    Tüm MT5 iletişimini tek noktadan yönetir.
    Bağlantı koparsa otomatik reconnect uygular.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._connected: bool = False
        self._last_heartbeat: float = 0.0

        # v5.8/CEO-FAZ2: Sembol eşleme kilidi — _resolve_symbols() sırasında
        # diğer thread'lerin dict'ten okuma yapmasını engeller.
        self._map_lock: threading.Lock = threading.Lock()
        # Dinamik sembol eşleme: base → MT5 gerçek ad (ör. F_THYAO → F_THYAO0226)
        self._symbol_map: dict[str, str] = {}
        # Ters eşleme: MT5 gerçek ad → base (ör. F_THYAO0226 → F_THYAO)
        self._reverse_map: dict[str, str] = {}

        # Son emir hatasının detayı — send_order() None döndüğünde
        # çağıran kod buradan retcode/comment okuyabilir.
        self._last_order_error: dict[str, Any] = {}
        # modify_position() başarısız olduğunda MT5 hata detayı (hibrit devir vb.)
        self._last_modify_error: dict[str, Any] = {}
        # send_stop_limit() None döndüğünde retcode/comment detayı
        # (hibrit devir başarısızlığında zengin modal için).
        self._last_stop_limit_error: dict[str, Any] = {}
        # send_limit() None döndüğünde retcode/comment detayı (hedef emir)
        self._last_limit_error: dict[str, Any] = {}
        # MT5 terminalinde Algo Trading butonu durumu (heartbeat'te guncellenir)
        # False => retcode 10027 riski, kullanici Ctrl+E ile acmali
        self._trade_allowed: bool = True
        # Emir gönderimi tek seferde bir çağrı (manuel + engine race önlemi)
        # v5.9.2-fix: RLock — send_order içinden close_position çağrılabilsin (deadlock önlemi)
        self._order_lock: threading.RLock = threading.RLock()
        # v5.8/CEO-FAZ2: Tüm MT5 yazma işlemleri (close, modify) için kilit
        # v5.9.2-fix: RLock — aynı thread reentrant erişim (SL/TP fail → close_position)
        self._write_lock: threading.RLock = threading.RLock()
        # Sistem sağlığı metrikleri (Engine tarafından set edilir)
        self._health: Any = None

        # v5.4.1: Circuit Breaker — ardışık MT5 hataları devre keser
        self._cb_failures: int = 0            # ardışık hata sayacı
        self._cb_tripped: bool = False         # devre kesik mi?
        self._cb_tripped_at: float = 0.0       # devre kesilme zamanı
        self._cb_lock: threading.Lock = threading.Lock()

    # ── Circuit Breaker yardımcıları ──────────────────────────────────

    def _cb_record_success(self) -> None:
        """v5.4.1: Başarılı MT5 çağrısı — circuit breaker sayacını sıfırla."""
        with self._cb_lock:
            if self._cb_failures > 0:
                logger.debug(f"Circuit breaker sıfırlandı (önceki hata: {self._cb_failures})")
            self._cb_failures = 0
            self._cb_tripped = False

    def _cb_record_failure(self) -> None:
        """v5.4.1: Başarısız MT5 çağrısı — circuit breaker sayacını artır."""
        with self._cb_lock:
            self._cb_failures += 1
            if self._cb_failures >= CB_FAILURE_THRESHOLD and not self._cb_tripped:
                self._cb_tripped = True
                self._cb_tripped_at = _time.monotonic()
                logger.critical(
                    f"CIRCUIT BREAKER AÇILDI: {self._cb_failures} ardışık MT5 hatası — "
                    f"{CB_COOLDOWN_SECS}sn boyunca MT5 çağrıları devre dışı"
                )

    def _cb_is_open(self) -> bool:
        """v5.4.1: Circuit breaker açık mı? Cooldown süresi dolduysa probe izni ver."""
        with self._cb_lock:
            if not self._cb_tripped:
                return False
            elapsed = _time.monotonic() - self._cb_tripped_at
            if elapsed >= CB_COOLDOWN_SECS:
                # Fix M9: Cooldown doldu — sadece 1 probe'a izin ver
                # _cb_tripped_at'ı güncelle → diğer thread'ler yeni cooldown bekler
                self._cb_tripped_at = _time.monotonic()
                logger.info(
                    f"Circuit breaker cooldown doldu ({elapsed:.0f}s) — "
                    f"tek probe denemesi yapılacak"
                )
                return False  # bu thread probe denesin
            return True  # hâlâ açık

    @property
    def circuit_breaker_active(self) -> bool:
        """v5.4.1: Circuit breaker şu an aktif mi? (API/UI sorgulama için)."""
        with self._cb_lock:
            return self._cb_tripped

    # ── _safe_call: MT5 API timeout koruyucu ──────────────────────────
    def _safe_call(self, func, *args, timeout: float = MT5_CALL_TIMEOUT, **kwargs):
        """v5.4.1: MT5 C++ API çağrılarını timeout + circuit breaker ile sarmala.

        MT5 Python API, dahili C++ DLL çağrıları yapar.  Bu çağrılar
        terminal donduğunda veya IPC kilitlendiğinde SONSUZ bekleyebilir.
        ThreadPoolExecutor ile ayrı thread'de çalıştırıp timeout uyguluyoruz.

        Circuit Breaker: Ardışık CB_FAILURE_THRESHOLD (5) hata sonrası
        tüm MT5 çağrıları CB_COOLDOWN_SECS (30s) boyunca engellenir.
        Cooldown sonrası tek bir probe çağrısı yapılır; başarılıysa devre kapanır.

        Args:
            func: Çağrılacak mt5.* fonksiyonu.
            *args: Fonksiyon argümanları.
            timeout: Maksimum bekleme süresi (saniye).
            **kwargs: Fonksiyon keyword argümanları.

        Returns:
            Fonksiyon dönüş değeri.

        Raises:
            TimeoutError: Çağrı timeout süresini aştığında.
            ConnectionError: Circuit breaker açık olduğunda.
        """
        # Circuit breaker kontrolü
        if self._cb_is_open():
            raise ConnectionError(
                f"MT5 circuit breaker açık — {func.__name__} engellendi "
                f"(cooldown: {CB_COOLDOWN_SECS}s)"
            )

        # v5.5.1: order_send yazma işlemlerini ana thread'de çağır.
        # MT5 C extension, order_send'i worker thread'den reddediyor.
        # Okuma fonksiyonları (copy_rates, symbol_info vb.) thread-safe.
        _is_write_op = func.__name__ == "order_send"

        if _is_write_op:
            # ── YAZMA: Doğrudan çağrı (ThreadPoolExecutor YOK) ──
            # v3: func(*args, **kwargs) yerine func(args[0]) kullan.
            # Python 3.14 vectorcall + MT5 C extension uyumsuzluğu:
            # **kwargs (boş bile olsa) geçildiğinde C extension reddediyor.
            try:
                result = func(args[0]) if args else func()
                self._cb_record_success()
                return result
            except Exception as exc:
                self._cb_record_failure()
                logger.error(
                    f"MT5 order_send EXCEPTION: {func.__name__}({args}) — "
                    f"{type(exc).__name__}: {exc}"
                )
                raise
        else:
            # ── OKUMA: ThreadPoolExecutor ile timeout korumalı ──
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: func(*args, **kwargs))
                try:
                    result = future.result(timeout=timeout)
                    self._cb_record_success()
                    return result
                except concurrent.futures.TimeoutError:
                    self._cb_record_failure()
                    logger.error(
                        f"MT5 API TIMEOUT ({timeout}s): {func.__name__}({args}) — "
                        f"terminal donmuş olabilir, reconnect tetiklenecek"
                    )
                    self._connected = False
                    if self._health:
                        self._health.record_disconnect()
                    raise TimeoutError(
                        f"MT5 {func.__name__} çağrısı {timeout}s içinde yanıt vermedi"
                    )
                except Exception as exc:
                    self._cb_record_failure()
                    logger.error(
                        f"MT5 API EXCEPTION: {func.__name__}({args}) — "
                        f"{type(exc).__name__}: {exc}"
                    )
                    raise

    # ── property ─────────────────────────────────────────────────────
    @property
    def is_connected(self) -> bool:
        """MT5 bağlantı durumu."""
        return self._connected

    # ── Sembol çözümleme ─────────────────────────────────────────────

    @staticmethod
    def _next_expiry_suffix() -> str | None:
        """Bugün VİOP vade günüyse, sonraki ayın suffix'ini döndür (MMYY).

        Örnek: 31 Mart 2026 (vade günü) → '0426' (Nisan 2026).
        Vade günü değilse None döndürür.
        """
        from datetime import date as _date

        today = _date.today()
        try:
            from engine.baba import VIOP_EXPIRY_DATES
        except ImportError:
            logger.critical(
                "VIOP_EXPIRY_DATES import BAŞARISIZ — vade çözümlemesi devre dışı!"
            )
            return None

        if today not in VIOP_EXPIRY_DATES:
            return None

        # Sonraki ay hesapla
        if today.month == 12:
            next_month, next_year = 1, today.year + 1
        else:
            next_month, next_year = today.month + 1, today.year

        suffix = f"{next_month:02d}{next_year % 100:02d}"
        return suffix

    def _resolve_symbols(self) -> None:
        """WATCHED_SYMBOLS'daki base isimleri MT5'teki gerçek ada eşle.

        VİOP kontrat adları vade soneki içerir (ör. F_THYAO0226).

        v5.9.1: Vade geçişi otomasyonu:
        - Bugün vade günüyse → sonraki ayın suffix'i hesaplanır (ör. 0426)
          → tüm kontratlar doğrudan bu suffix ile eşlenir
        - Vade günü değilse → en yakın aktive edilebilir kontrat seçilir
        - Eski vadede açık pozisyonlar _to_base() prefix fallback ile tanınır
        """
        try:
            all_symbols = self._safe_call(mt5.symbols_get)
        except (TimeoutError, Exception):
            all_symbols = None
        if not all_symbols:
            logger.warning("MT5 sembol listesi alınamadı, eşleme yapılamıyor")
            return

        # Vade günü tespiti — sonraki ayın suffix'ini belirle
        target_suffix = self._next_expiry_suffix()
        if target_suffix:
            logger.info(
                f"VADE GEÇİŞİ: Bugün vade son günü — "
                f"hedef suffix: {target_suffix} "
                f"(tüm kontratlar bu vadeye eşlenecek)"
            )

        # v5.8/CEO-FAZ2: Atomik map güncellemesi
        new_symbol_map: dict[str, str] = {}
        new_reverse_map: dict[str, str] = {}

        for base in WATCHED_SYMBOLS:
            # Base ile başlayan tüm MT5 sembollerini bul
            candidates = [
                s for s in all_symbols
                if s.name.upper().startswith(base.upper())
                and len(s.name) > len(base)
            ]

            if not candidates:
                exact = [s for s in all_symbols if s.name.upper() == base.upper()]
                if exact:
                    mt5_name = exact[0].name
                    new_symbol_map[base] = mt5_name
                    new_reverse_map[mt5_name] = base
                    try:
                        self._safe_call(mt5.symbol_select, mt5_name, True)
                    except (TimeoutError, Exception):
                        pass
                    logger.info(f"Sembol eşleme: {base} → {mt5_name} (tam eşleşme)")
                else:
                    logger.warning(f"Sembol bulunamadı: {base}")
                continue

            chosen = None

            # ── YÖNTEM 1: Vade günü — hedef suffix ile doğrudan eşle ──
            if target_suffix:
                target_name = f"{base}{target_suffix}"
                match = [s for s in candidates if s.name.upper() == target_name.upper()]
                if match:
                    cand = match[0]
                    try:
                        self._safe_call(mt5.symbol_select, cand.name, True)
                    except (TimeoutError, Exception):
                        pass
                    # v5.9.2: trade_mode kontrolü — FULL (4) değilse atla
                    _tm = getattr(cand, "trade_mode", 4)
                    if _tm >= 4:  # SYMBOL_TRADE_MODE_FULL
                        chosen = cand
                        logger.info(
                            f"Sembol eşleme: {base} → {cand.name} "
                            f"(vade geçişi — hedef suffix {target_suffix})"
                        )
                    else:
                        logger.warning(
                            f"Vade hedefi {cand.name} trade_mode={_tm} "
                            f"(FULL değil) — YÖNTEM 2'ye düşülüyor"
                        )

            # ── YÖNTEM 2: Normal gün veya hedef bulunamadı ──
            if not chosen and target_suffix:
                logger.warning(
                    f"Vade hedefi {base}{target_suffix} bulunamadı — "
                    f"YÖNTEM 2'ye düşülüyor (ilk aktif kontrat seçilecek)"
                )
            if not chosen:
                # Artan sırala, en yakın FULL modda kontratı seç
                sorted_cands = sorted(candidates, key=lambda s: s.name)
                for candidate in sorted_cands:
                    try:
                        activated = self._safe_call(
                            mt5.symbol_select, candidate.name, True
                        )
                    except (TimeoutError, Exception):
                        activated = False
                    if not activated:
                        continue
                    # v5.9.2: trade_mode kontrolü — CLOSEONLY/DISABLED atla
                    _tm = getattr(candidate, "trade_mode", 4)
                    if _tm < 4:  # FULL (4) değil
                        logger.warning(
                            f"Sembol {candidate.name} atlandı — "
                            f"trade_mode={_tm} (FULL değil, "
                            f"muhtemelen vade sonu CLOSE_ONLY)"
                        )
                        continue
                    chosen = candidate
                    logger.info(
                        f"Sembol eşleme: {base} → {candidate.name} "
                        f"(visible={candidate.visible}, "
                        f"trade_mode={_tm}, activated=True)"
                    )
                    break

            if not chosen:
                # Hiçbir aday FULL modda değil — en yeni adayı kullan
                # ama CLOSEONLY uyarısı logla
                chosen = max(candidates, key=lambda s: s.name)
                _tm = getattr(chosen, "trade_mode", -1)
                logger.error(
                    f"VADE UYARI: {base} için FULL modda kontrat "
                    f"bulunamadı! Fallback: {chosen.name} "
                    f"(trade_mode={_tm}). Bu kontratta yeni "
                    f"pozisyon AÇILAMAZ."
                )

            mt5_name = chosen.name
            new_symbol_map[base] = mt5_name
            new_reverse_map[mt5_name] = base

        # USDTRY — BABA şok kontrolü için gerekli
        usdtry_candidates = [
            s for s in all_symbols
            if "USDTRY" in s.name.upper()
        ]
        if usdtry_candidates:
            usdtry_sorted = sorted(usdtry_candidates, key=lambda s: s.name)
            usdtry_chosen = None
            for usdtry_sym in usdtry_sorted:
                try:
                    if self._safe_call(mt5.symbol_select, usdtry_sym.name, True):
                        usdtry_chosen = usdtry_sym
                        break
                except (TimeoutError, Exception):
                    continue
            if not usdtry_chosen:
                usdtry_chosen = usdtry_sorted[0]
                logger.warning(f"USDTRY activate edilemedi — fallback: {usdtry_chosen.name}")
            new_symbol_map["USDTRY"] = usdtry_chosen.name
            logger.info(f"Sembol eşleme: USDTRY → {usdtry_chosen.name}")
        else:
            logger.warning("USDTRY sembolü bulunamadı — şok kontrolü pasif kalacak")

        # v5.8/CEO-FAZ2: Atomik swap — tüm map'ler hazır, tek lock ile değiştir
        with self._map_lock:
            self._symbol_map = new_symbol_map
            self._reverse_map = new_reverse_map

        resolved = len(self._symbol_map)
        total = len(WATCHED_SYMBOLS) + 1  # +1 USDTRY
        logger.info(f"Sembol çözümleme tamamlandı: {resolved}/{total} eşlendi")

    def check_trade_modes(self) -> list[str]:
        """v5.9.2: Mevcut map'teki kontratların trade_mode durumunu kontrol et.

        CLOSEONLY veya DISABLED bulunan semboller için otomatik re-resolve
        tetikler. Eski vadede kalan pozisyonları tespit eder ve uyarı verir.
        Saatlik periyodik kontrol olarak main.py'den çağrılır.

        Returns:
            CLOSEONLY/DISABLED tespit edilen base sembol listesi.
        """
        if not self._connected:
            return []

        with self._map_lock:
            current_map = dict(self._symbol_map)

        stale_symbols: list[str] = []
        for base, mt5_name in current_map.items():
            if base == "USDTRY":
                continue
            try:
                info = self._safe_call(mt5.symbol_info, mt5_name)
            except (TimeoutError, Exception):
                continue
            if info is None:
                continue
            _tm = getattr(info, "trade_mode", 4)
            if _tm < 4:  # FULL (4) değil
                stale_symbols.append(base)
                logger.warning(
                    f"VADE TARAMA: {mt5_name} trade_mode={_tm} "
                    f"(FULL değil) — re-resolve gerekli"
                )

        if stale_symbols:
            logger.info(
                f"VADE TARAMA: {len(stale_symbols)} kontrat CLOSEONLY/DISABLED "
                f"tespit edildi: {stale_symbols}. Re-resolve başlatılıyor."
            )
            try:
                self._resolve_symbols()
                logger.info("Periyodik re-resolve tamamlandı.")
            except Exception as exc:
                logger.error(f"Periyodik re-resolve hatası: {exc}")

        # ── Eski vadede kalan pozisyon tespiti ──────────────────
        self._check_stale_positions()

        return stale_symbols

    def _check_stale_positions(self) -> None:
        """v5.9.2: Eski vadede (CLOSEONLY/DISABLED) kalan pozisyonları tespit et.

        Mevcut symbol_map'teki kontratla eşleşmeyen açık pozisyonlar
        eski vadeye ait demektir. Bunları logla ve event bus'a bildir.
        """
        try:
            positions = self._safe_call(mt5.positions_get)
        except (TimeoutError, Exception):
            return
        if not positions:
            return

        with self._map_lock:
            active_mt5_names = set(self._symbol_map.values())

        stale_positions: list[dict] = []
        for pos in positions:
            # İzlenen sembol mü?
            base = self._to_base(pos.symbol)
            if base is None:
                continue
            # symbol_map'teki aktif kontratla eşleşiyor mu?
            if pos.symbol in active_mt5_names:
                continue
            # Eski vadede kalan pozisyon tespit edildi
            _tm = 4
            try:
                info = self._safe_call(mt5.symbol_info, pos.symbol)
                if info:
                    _tm = getattr(info, "trade_mode", 4)
            except (TimeoutError, Exception):
                pass
            stale_positions.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "base": base,
                "volume": pos.volume,
                "profit": pos.profit,
                "trade_mode": _tm,
            })
            logger.error(
                f"ESKİ VADE POZİSYON: {pos.symbol} (base={base}) "
                f"ticket={pos.ticket} vol={pos.volume} P&L={pos.profit:.2f} "
                f"trade_mode={_tm}. Bu kontrat aktif map'te değil!"
            )

        if stale_positions:
            try:
                from engine.event_bus import emit as _emit
                _emit("STALE_POSITION", {
                    "count": len(stale_positions),
                    "positions": stale_positions,
                    "message": (
                        f"{len(stale_positions)} pozisyon eski vadede — "
                        f"manuel kapatma gerekebilir"
                    ),
                })
            except Exception:
                pass

    def _to_mt5(self, base_symbol: str) -> str:
        """Base sembol adını MT5 gerçek adına çevir.

        Eşleme yoksa base'in kendisini döndürür (geriye uyumluluk).
        v5.8/CEO-FAZ2: _map_lock ile thread-safe.
        """
        with self._map_lock:
            return self._symbol_map.get(base_symbol, base_symbol)

    def _to_base(self, mt5_symbol: str) -> str | None:
        """MT5 sembol adını base'e çevir.

        Eşleme yoksa None döndürür (izlenmeyen sembol).
        v5.8/CEO-FAZ2: _map_lock ile thread-safe.
        v5.9.1: Fallback — vade soneki farklı olabilir (ör. map 0326, pozisyon 0426)
        """
        with self._map_lock:
            base = self._reverse_map.get(mt5_symbol)
            if base:
                return base
            # Fallback: prefix eşleşmesi ile base çıkar
            for watched in WATCHED_SYMBOLS:
                if mt5_symbol.upper().startswith(watched.upper()):
                    return watched
            return None

    def _is_watched(self, mt5_symbol: str) -> bool:
        """MT5 sembolü izlenen kontratlardan biri mi?
        v5.8/CEO-FAZ2: _map_lock ile thread-safe.
        """
        with self._map_lock:
            return mt5_symbol in self._reverse_map

    # ── Reconnect yardımcı ───────────────────────────────────────────
    def _ensure_connection(self) -> bool:
        """Bağlantı yoksa reconnect dene.

        Returns:
            Bağlantı varsa / kurulduysa True, yoksa False.
        """
        if self._connected:
            return True
        logger.warning("MT5 bağlantısı yok, reconnect deneniyor...")
        return self.connect(launch=False)

    # ── connect ──────────────────────────────────────────────────────
    def connect(self, launch: bool = False) -> bool:
        """MT5 terminaline bağlan.

        Args:
            launch: True ise path parametresiyle mt5.initialize() çağır
                    (MT5 kapalıysa açar — sadece ilk başlatmada kullan).
                    False ise pathsiz çağır (sadece çalışan MT5'e bağlanır,
                    kapalıysa açmaz — heartbeat reconnect için).

        Config'den mt5.login, mt5.server (ve launch=True ise mt5.path) okunur.
        Başarısız olursa artan bekleme ile tekrar dener.

        Returns:
            Bağlantı başarılı ise True.
        """
        mt5_path: str | None = self._config.get("mt5.path")
        mt5_login: int | None = self._config.get("mt5.login")
        mt5_server: str | None = self._config.get("mt5.server")

        # ══════════════════════════════════════════════════════════════════
        #  🚫 SİYAH KAPI — MT5 PROCESS KORUMASI (ANAYASA Kural 4.15)
        # ══════════════════════════════════════════════════════════════════
        # Bu koruma bloğu DEĞİŞTİRİLEMEZ. Mantığı:
        #
        # 1. Python MetaTrader5 kütüphanesi, mt5.initialize() çağrıldığında
        #    path verilmese bile Windows registry'den MT5 yolunu bulup
        #    terminal64.exe'yi OTOMATİK BAŞLATIR.
        #
        # 2. Bu davranış launch=False modda İSTENMİYOR. Engine hiçbir koşulda
        #    MT5 terminal'ini kendisi açmamalı.
        #
        # 3. MT5 açma sorumluluğu SADECE Electron'dadır (mt5Manager.js →
        #    launchMT5). Kullanıcı OTP girene kadar MT5 kapalı kalır.
        #
        # 4. Bu blok kaldırılırsa veya atlanırsa:
        #    - Uygulama açıldığında MT5 otomatik açılır (istenmeyen)
        #    - Kullanıcı OTP giremez çünkü MT5 yanlış zamanda başlamıştır
        #    - Startup akışı bozulur: ÜSTAT UI → LockScreen → MT5 sırası kırılır
        #
        # DEĞİŞİKLİK GEÇMİŞİ:
        # - 2026-04-08: İlk ekleme — MT5 auto-launch bug fix (10/10 test geçti)
        # ══════════════════════════════════════════════════════════════════
        if not launch:
            try:
                import subprocess as _sp
                _result = _sp.run(
                    ['tasklist', '/FI', 'IMAGENAME eq terminal64.exe', '/FO', 'CSV', '/NH'],
                    capture_output=True, text=True, timeout=5,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                )
                if 'terminal64.exe' not in _result.stdout.lower():
                    logger.info(
                        "MT5 process bulunamadı — launch=False, bağlantı atlanıyor. "
                        "[Siyah Kapı: MT5 açma sorumluluğu Electron'dadır]"
                    )
                    self._connected = False
                    return False
            except Exception as _exc:
                logger.warning(
                    f"MT5 process kontrol hatası: {_exc} — "
                    f"güvenlik gereği bağlantı ATLANACAK (launch=False)."
                )
                self._connected = False
                return False

        max_retries = MAX_RETRIES_LAUNCH if launch else MAX_RETRIES_RECONNECT
        mode_label = "launch" if launch else "reconnect"

        for attempt in range(1, max_retries + 1):
            try:
                kwargs: dict[str, Any] = {}

                # path sadece launch=True modda ve sadece İLK denemede verilir.
                # İlk deneme MT5'i açar, sonraki denemeler sadece bağlanır.
                if launch and attempt == 1 and mt5_path:
                    kwargs["path"] = mt5_path

                if mt5_login:
                    kwargs["login"] = int(mt5_login)
                if mt5_server:
                    kwargs["server"] = mt5_server

                if not self._safe_call(mt5.initialize, timeout=30.0, **kwargs):
                    error = mt5.last_error()
                    logger.error(
                        f"MT5 {mode_label} başarısız "
                        f"(deneme {attempt}/{max_retries}): code={error}"
                    )
                    if attempt < max_retries:
                        wait = BASE_WAIT * (2 ** (attempt - 1))
                        logger.info(f"{wait:.0f} sn sonra tekrar denenecek...")
                        _time.sleep(wait)
                    continue

                # Dinamik sembol çözümleme (base → MT5 gerçek ad)
                # v5.9.1: _resolve_symbols() artık sembol aktivasyonunu da yapıyor
                # (seçim + activate tek döngüde — vade geçişi otomatik)
                self._resolve_symbols()

                self._connected = True
                self._last_heartbeat = _time.monotonic()
                info = self._safe_call(mt5.account_info)
                logger.info(
                    f"MT5 bağlantısı kuruldu ({mode_label}) — "
                    f"hesap={info.login if info else '?'}, "
                    f"sunucu={info.server if info else '?'}"
                )
                return True

            except Exception as exc:
                logger.error(
                    f"MT5 {mode_label} istisnası "
                    f"(deneme {attempt}/{max_retries}): {exc}"
                )
                if attempt < max_retries:
                    wait = BASE_WAIT * (2 ** (attempt - 1))
                    _time.sleep(wait)

        self._connected = False
        logger.critical(
            f"MT5 bağlantısı {max_retries} denemede kurulamadı ({mode_label})!"
        )
        return False

    # ── disconnect ───────────────────────────────────────────────────
    def disconnect(self) -> None:
        """MT5 bağlantısını güvenli şekilde kapat."""
        try:
            self._safe_call(mt5.shutdown, timeout=5.0)
            logger.info("MT5 bağlantısı kapatıldı.")
        except Exception as exc:
            logger.error(f"MT5 disconnect hatası: {exc}")
        finally:
            self._connected = False

    # ── is_trade_allowed ─────────────────────────────────────────────
    def is_trade_allowed(self) -> bool:
        """MT5 Algo Trading butonu acik mi?

        heartbeat() her 10 saniyede bu degeri gunceller. Emir gonderimi
        oncesinde kontrol edilmez (MT5 retcode 10027 gosterir), ancak
        UI'da uyari banner'i icin okunur.
        """
        return self._trade_allowed

    # ── heartbeat ────────────────────────────────────────────────────
    def heartbeat(self) -> bool:
        """Bağlantı kontrolü — 10 saniyede bir çağrılmalı.

        mt5.terminal_info() çağrısı ile bağlantıyı doğrular.
        Kopmuşsa reconnect dener.

        Returns:
            Bağlantı sağlıklı ise True.
        """
        now = _time.monotonic()
        if now - self._last_heartbeat < HEARTBEAT_INTERVAL:
            return self._connected

        self._last_heartbeat = now
        _ping_start = _time.perf_counter()

        try:
            info = self._safe_call(mt5.terminal_info)
            if info is None:
                logger.warning("Heartbeat başarısız — terminal_info None döndü.")
                self._connected = False
                if self._health:
                    self._health.record_disconnect()
                return self._ensure_connection()

            if not info.connected:
                logger.warning("Heartbeat: terminal bağlantı yok.")
                self._connected = False
                if self._health:
                    self._health.record_disconnect()
                return self._ensure_connection()

            # MT5 Algo Trading butonu durumu — False ise emir gonderimi blokajli
            prev_allowed = self._trade_allowed
            self._trade_allowed = bool(getattr(info, 'trade_allowed', True))
            if prev_allowed and not self._trade_allowed:
                logger.warning(
                    "MT5 Algo Trading KAPANDI — emir gonderimi bloke. "
                    "Kullanici Ctrl+E ile acmali."
                )
            elif not prev_allowed and self._trade_allowed:
                logger.info("MT5 Algo Trading yeniden ACIK.")

            # Ping kaydı (başarılı heartbeat)
            if self._health:
                self._health.record_ping((_time.perf_counter() - _ping_start) * 1000)
            logger.debug("Heartbeat OK.")
            return True

        except Exception as exc:
            logger.error(f"Heartbeat istisnası: {exc}")
            self._connected = False
            if self._health:
                self._health.record_disconnect()
            return self._ensure_connection()

    # ── get_account_info ─────────────────────────────────────────────
    def get_account_info(self) -> AccountInfo | None:
        """Hesap bilgilerini getir (bakiye, equity, margin).

        Returns:
            AccountInfo nesnesi veya bağlantı/hata durumunda None.
        """
        if not self._ensure_connection():
            return None

        try:
            info = self._safe_call(mt5.account_info)
            if info is None:
                logger.error(f"account_info alınamadı: {mt5.last_error()}")
                return None

            account = AccountInfo(
                login=info.login,
                server=info.server,
                balance=info.balance,
                equity=info.equity,
                margin=info.margin,
                free_margin=info.margin_free,
                margin_level=info.margin_level if info.margin_level else 0.0,
                currency=info.currency,
            )
            logger.debug(
                f"Hesap: bakiye={account.balance:.2f}, "
                f"equity={account.equity:.2f}, margin={account.margin:.2f}"
            )
            return account

        except Exception as exc:
            logger.error(f"get_account_info istisnası: {exc}")
            return None

    # ── get_symbol_info ──────────────────────────────────────────────
    def get_symbol_info(self, symbol: str) -> SymbolInfo | None:
        """Sembol bilgisi getir (fiyat adımı, çarpan, tick değeri).

        Args:
            symbol: VİOP kontrat sembolü (ör. "F_THYAO").

        Returns:
            SymbolInfo nesnesi veya hata durumunda None.
        """
        if not self._ensure_connection():
            return None

        try:
            mt5_name = self._to_mt5(symbol)
            info = self._safe_call(mt5.symbol_info, mt5_name)
            if info is None:
                logger.error(f"symbol_info alınamadı [{symbol}]: {mt5.last_error()}")
                return None

            sym = SymbolInfo(
                name=info.name,
                point=info.point,
                trade_contract_size=info.trade_contract_size,
                trade_tick_value=info.trade_tick_value,
                volume_min=info.volume_min,
                volume_max=info.volume_max,
                volume_step=info.volume_step,
                bid=info.bid,
                ask=info.ask,
                spread=info.spread,
                session_price_limit_max=getattr(info, "session_price_limit_max", 0.0),
                session_price_limit_min=getattr(info, "session_price_limit_min", 0.0),
            )
            logger.debug(
                f"Sembol [{symbol}]: point={sym.point}, "
                f"çarpan={sym.trade_contract_size}, "
                f"tick_val={sym.trade_tick_value}"
            )
            return sym

        except Exception as exc:
            logger.error(f"get_symbol_info istisnası [{symbol}]: {exc}")
            return None

    # ── get_bars ─────────────────────────────────────────────────────
    def get_bars(
        self,
        symbol: str,
        timeframe: int = mt5.TIMEFRAME_M1,
        count: int = 500,
    ) -> pd.DataFrame:
        """OHLCV bar verisi çek.

        Args:
            symbol: Kontrat sembolü.
            timeframe: MT5 zaman dilimi sabiti (varsayılan M1).
            count: İstenen bar sayısı.

        Returns:
            Sütunlar: time, open, high, low, close, tick_volume, spread, real_volume.
            Hata durumunda boş DataFrame.
        """
        if not self._ensure_connection():
            return pd.DataFrame()

        try:
            mt5_name = self._to_mt5(symbol)
            rates = self._safe_call(mt5.copy_rates_from_pos, mt5_name, timeframe, 0, count)
            if rates is None or len(rates) == 0:
                logger.warning(
                    f"Bar verisi alınamadı [{symbol}]: {mt5.last_error()}"
                )
                return pd.DataFrame()

            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            logger.debug(f"Bar verisi [{symbol}]: {len(df)} bar, tf={timeframe}")
            return df

        except Exception as exc:
            logger.error(f"get_bars istisnası [{symbol}]: {exc}")
            return pd.DataFrame()

    # ── get_tick ─────────────────────────────────────────────────────
    def get_tick(self, symbol: str) -> Tick | None:
        """Anlık bid/ask/spread bilgisi.

        Args:
            symbol: Kontrat sembolü.

        Returns:
            Tick nesnesi veya hata durumunda None.
        """
        if not self._ensure_connection():
            return None

        try:
            mt5_name = self._to_mt5(symbol)
            tick = self._safe_call(mt5.symbol_info_tick, mt5_name)
            if tick is None:
                logger.warning(f"Tick alınamadı [{symbol}]: {mt5.last_error()}")
                return None

            result = Tick(
                symbol=symbol,  # base isim döndür
                bid=tick.bid,
                ask=tick.ask,
                spread=round(tick.ask - tick.bid, 6),
                time=datetime.fromtimestamp(tick.time),
            )
            logger.debug(
                f"Tick [{symbol}]: bid={result.bid}, ask={result.ask}, "
                f"spread={result.spread}"
            )
            return result

        except Exception as exc:
            logger.error(f"get_tick istisnası [{symbol}]: {exc}")
            return None

    # ── send_order ───────────────────────────────────────────────────
    def send_order(
        self,
        symbol: str,
        direction: str,
        lot: float,
        price: float,
        sl: float,
        tp: float,
        order_type: str = "market",
    ) -> dict[str, Any] | None:
        """Emir gönder (2 aşamalı: emir + SL/TP).

        VİOP exchange execution modunda ilk emre SL/TP eklenemez.
        Bu yüzden:
            1) Emir SL/TP olmadan gönderilir.
            2) Başarılıysa TRADE_ACTION_SLTP ile SL/TP eklenir.

        Args:
            symbol: Kontrat sembolü (ör. "F_THYAO").
            direction: "BUY" veya "SELL".
            lot: Lot miktarı.
            price: Fiyat. Market emirde mevcut bid/ask kullanılır.
            sl: Stop-loss fiyatı.
            tp: Take-profit fiyatı.
            order_type: "market" (varsayılan) veya "limit".

        Returns:
            Emir sonuç sözlüğü (ticket, retcode, sl_tp_applied vb.)
            veya None.  Hata durumunda ``_last_order_error``
            sözlüğünde retcode/comment detayı bulunur.
        """
        self._last_order_error = {}
        _order_start = _time.perf_counter()

        # v5.9.3: Lifecycle Guard kontrolü — kapanma başladıysa emir YASAK
        guard = getattr(self, '_lifecycle_guard', None)
        if guard is not None:
            if not guard.order_enter():
                self._last_order_error = {
                    "reason": "Engine kapanıyor — emir engellendi (LifecycleGuard)",
                }
                logger.warning(
                    f"EMİR ENGELLENDİ [{symbol} {direction}]: "
                    f"Engine durumu={guard.state.name}"
                )
                return None
        _guard_entered = guard is not None

        try:
            return self._send_order_inner(
                symbol, direction, lot, price, sl, tp, order_type,
                _order_start,
            )
        finally:
            if _guard_entered:
                guard.order_exit()

    def _send_order_inner(
        self,
        symbol: str,
        direction: str,
        lot: float,
        price: float,
        sl: float,
        tp: float,
        order_type: str,
        _order_start: float,
    ) -> dict[str, Any] | None:
        """Gerçek emir gönderme (guard tarafından korunan iç metod)."""
        with self._order_lock, self._write_lock:
            if not self._ensure_connection():
                self._last_order_error = {
                    "reason": "MT5 bağlantısı kurulamadı",
                }
                return None

            try:
                # Yön → MT5 order type
                if direction.upper() == "BUY":
                    mt5_type = mt5.ORDER_TYPE_BUY
                elif direction.upper() == "SELL":
                    mt5_type = mt5.ORDER_TYPE_SELL
                else:
                    logger.error(f"Geçersiz yön: {direction}")
                    self._last_order_error = {"reason": f"Geçersiz yön: {direction}"}
                    return None

                mt5_name = self._to_mt5(symbol)

                # Sembol bilgisi — tick_size ve filling_mode
                sym_info = self._safe_call(mt5.symbol_info, mt5_name)
                if sym_info is None:
                    err = mt5.last_error()
                    logger.error(
                        f"symbol_info alınamadı [{symbol}]: {err}"
                    )
                    self._last_order_error = {
                        "reason": f"Sembol bilgisi alınamadı ({symbol})",
                        "last_error": str(err),
                    }
                    return None

                tick_size = sym_info.trade_tick_size
                if tick_size <= 0:
                    tick_size = sym_info.point  # fallback

                # Lot validasyonu: volume_min, volume_max, volume_step
                vol_min = sym_info.volume_min
                vol_max = sym_info.volume_max
                vol_step = sym_info.volume_step if sym_info.volume_step > 0 else vol_min
                if lot < vol_min or lot > vol_max:
                    logger.error(
                        f"Lot sınır dışı [{symbol}]: {lot} (min={vol_min}, max={vol_max})"
                    )
                    self._last_order_error = {
                        "reason": f"Lot sınır dışı: {lot} (min={vol_min}, max={vol_max})",
                    }
                    return None
                # volume_step'e göre yuvarla ve sınırlar içinde tut
                lot = round(lot / vol_step) * vol_step
                lot = max(vol_min, min(vol_max, lot))

                # Filling mode: VİOP netting → ORDER_FILLING_RETURN
                # SYMBOL_FILLING_* sabitleri MT5 v5.0.5572'de kaldırılmış.
                # GCM VİOP kontratları RETURN destekler (FOK desteklenmez).
                filling = mt5.ORDER_FILLING_RETURN

                # Market ise güncel fiyatı al
                if order_type == "market":
                    tick = self._safe_call(mt5.symbol_info_tick, mt5_name)
                    if tick is None:
                        err = mt5.last_error()
                        logger.error(
                            f"Emir fiyatı alınamadı [{symbol}]: {err}"
                        )
                        self._last_order_error = {
                            "reason": f"Fiyat alınamadı ({symbol})",
                            "last_error": str(err),
                        }
                        return None
                    price = tick.ask if direction.upper() == "BUY" else tick.bid
                    action = mt5.TRADE_ACTION_DEAL
                else:
                    action = mt5.TRADE_ACTION_PENDING
                    if direction.upper() == "BUY":
                        mt5_type = mt5.ORDER_TYPE_BUY_LIMIT
                    else:
                        mt5_type = mt5.ORDER_TYPE_SELL_LIMIT

                # ── ADIM 1: Emir SL/TP OLMADAN gönder ──────────────────
                # VİOP limit emirleri: GTC + expiration = seans sonu.
                # VİOP exchange GTC emirlerde expiration zorunlu tutar.
                # Eksikse retcode=10022 (Invalid expiration) döner.
                # ORDER_TIME_DAY exchange'lerde desteklenmeyebilir,
                # bu yüzden GTC + açık expiration kullanıyoruz.
                request: dict[str, Any] = {
                    "action": action,
                    "symbol": mt5_name,
                    "volume": lot,
                    "type": mt5_type,
                    "price": price,
                    "type_filling": filling,
                    "type_time": mt5.ORDER_TIME_GTC,
                    "comment": "USTAT",
                }

                # Pending (limit) emirlere seans sonu expiration ekle
                if action == mt5.TRADE_ACTION_PENDING:
                    from datetime import datetime as _dt, timedelta as _td
                    _today = _dt.now().date()
                    # Seans sonu: 18:10 (VİOP kapanış)
                    _expiry = _dt.combine(_today, _dt.min.time().replace(hour=18, minute=10))
                    request["type_time"] = mt5.ORDER_TIME_SPECIFIED
                    request["expiration"] = _expiry

                logger.info(
                    f"Emir gönderiliyor (SL/TP ayrı): {direction} {lot} lot "
                    f"{symbol} @ {price:.4f} [{order_type}] "
                    f"filling={filling} request={request}"
                )

                result = self._safe_call(mt5.order_send, request, timeout=15.0)
                if result is None:
                    err = mt5.last_error()
                    logger.error(
                        f"order_send None döndü [{symbol}]: {err}"
                    )
                    self._last_order_error = {
                        "reason": "MT5 order_send None döndü",
                        "last_error": str(err),
                    }
                    return None

                # Market emir → RETCODE_DONE (10009)
                # LIMIT emir  → RETCODE_PLACED (10008)
                accepted = {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
                if result.retcode not in accepted:
                    logger.error(
                        f"Emir reddedildi [{symbol}]: retcode={result.retcode}, "
                        f"comment={result.comment}"
                    )
                    self._last_order_error = {
                        "reason": f"Emir reddedildi",
                        "retcode": result.retcode,
                        "comment": result.comment,
                    }
                    # Health: reddedilen emir kaydı + ardışık red alarmı
                    if self._health:
                        from engine.health import OrderTiming
                        self._health.record_order(OrderTiming(
                            timestamp=_time.time(),
                            symbol=symbol,
                            direction=direction,
                            duration_ms=(_time.perf_counter() - _order_start) * 1000,
                            success=False,
                            retcode=result.retcode,
                        ))
                        self._health.record_order_reject(
                            symbol, result.retcode, result.comment,
                        )
                    # v5.9.2: retcode 10044 (CLOSE_ONLY) → vade geçişi tetikle
                    _RETCODE_CLOSE_ONLY = 10044
                    _RETCODE_TRADE_DISABLED = 10017
                    if result.retcode in (
                        _RETCODE_CLOSE_ONLY, _RETCODE_TRADE_DISABLED,
                    ):
                        logger.error(
                            f"VADE GEÇİŞİ TETİKLENDİ: {symbol} "
                            f"retcode={result.retcode} — kontrat "
                            f"CLOSE_ONLY veya DISABLED. Anında "
                            f"re-resolve başlatılıyor."
                        )
                        try:
                            self._resolve_symbols()
                            logger.info(
                                "Reaktif re-resolve tamamlandı "
                                f"(tetikleyen: {symbol})"
                            )
                        except Exception as _re_exc:
                            logger.error(
                                f"Reaktif re-resolve hatası: {_re_exc}"
                            )

                    # Event bus: başarısız emir bildir (dashboard + WS)
                    _event_type = "ORDER_REJECTED"
                    _event_data: dict[str, Any] = {
                        "symbol": symbol,
                        "direction": direction,
                        "retcode": result.retcode,
                        "comment": result.comment,
                        "timestamp": _time.time(),
                    }
                    # v5.9.2: CLOSE_ONLY ise özel vade uyarı event'i ekle
                    if result.retcode == _RETCODE_CLOSE_ONLY:
                        _event_data["vade_uyari"] = True
                        _event_data["reason"] = (
                            f"{symbol} kontratı CLOSE_ONLY modunda — "
                            f"vade geçişi gerekiyor"
                        )
                    try:
                        from engine.event_bus import emit as _emit_event
                        _emit_event(_event_type, _event_data)
                        if result.retcode == _RETCODE_CLOSE_ONLY:
                            _emit_event("VADE_UYARI", _event_data)
                    except Exception:
                        pass
                    return None

                order_result = result._asdict()
                order_result["sl_tp_applied"] = False

                # Başarılı emir — ardışık red sayacını sıfırla
                if self._health:
                    self._health.clear_reject_streak()

                logger.info(
                    f"Emir başarılı: ticket={order_result.get('order')}, "
                    f"{direction} {lot} lot {symbol} @ {price:.4f} "
                    f"retcode={result.retcode}"
                )

                # ── ADIM 2: SL/TP ekle (TRADE_ACTION_SLTP) ─────────────
                if sl > 0 or tp > 0:
                    # tick_size'a yuvarla
                    sl_rounded = (
                        round(sl / tick_size) * tick_size if sl > 0 else 0.0
                    )
                    tp_rounded = (
                        round(tp / tick_size) * tick_size if tp > 0 else 0.0
                    )

                    # ── stops_level kontrolü ──────────────────────────
                    stops_level = getattr(sym_info, "trade_stops_level", 0) or 0
                    if stops_level > 0:
                        min_dist = stops_level * (tick_size if tick_size > 0 else sym_info.point)
                        if sl_rounded > 0:
                            if direction.upper() == "BUY" and price - sl_rounded < min_dist:
                                sl_rounded = round((price - min_dist) / tick_size) * tick_size
                                logger.warning(
                                    f"SL stops_level'e göre ayarlandı [{symbol}]: "
                                    f"SL={sl_rounded:.4f} (min mesafe={min_dist:.4f})"
                                )
                            elif direction.upper() == "SELL" and sl_rounded - price < min_dist:
                                sl_rounded = round((price + min_dist) / tick_size) * tick_size
                                logger.warning(
                                    f"SL stops_level'e göre ayarlandı [{symbol}]: "
                                    f"SL={sl_rounded:.4f} (min mesafe={min_dist:.4f})"
                                )
                        if tp_rounded > 0:
                            if direction.upper() == "BUY" and tp_rounded - price < min_dist:
                                tp_rounded = round((price + min_dist) / tick_size) * tick_size
                                logger.warning(
                                    f"TP stops_level'e göre ayarlandı [{symbol}]: "
                                    f"TP={tp_rounded:.4f} (min mesafe={min_dist:.4f})"
                                )
                            elif direction.upper() == "SELL" and price - tp_rounded < min_dist:
                                tp_rounded = round((price - min_dist) / tick_size) * tick_size
                                logger.warning(
                                    f"TP stops_level'e göre ayarlandı [{symbol}]: "
                                    f"TP={tp_rounded:.4f} (min mesafe={min_dist:.4f})"
                                )

                    # Pozisyon ticket: Exchange netting modda order_ticket ≠ position_ticket.
                    # order_send() döndüğü "order" değeri ORDER ticket'ıdır (geçici).
                    # SL/TP için POSITION ticket gerekir.
                    # Strateji: 1) deal.position_id ile al  2) sembolden ara  3) son çare order ticket
                    order_ticket_raw = order_result.get("order", 0)
                    position_ticket = 0

                    # Yöntem 1: history_deals_get ile doğru position_id al
                    DEAL_LOOKUP_RETRIES = 10  # Toplam ~2.8s (exponential backoff)
                    for deal_attempt in range(1, DEAL_LOOKUP_RETRIES + 1):
                        _time.sleep(min(0.1 * deal_attempt, 0.5))
                        deals = self._safe_call(
                            mt5.history_deals_get, order=order_ticket_raw
                        )
                        if deals is not None and len(deals) > 0:
                            pos_id = getattr(deals[0], "position_id", 0)
                            if pos_id and pos_id > 0:
                                position_ticket = pos_id
                                logger.info(
                                    f"SL/TP [{symbol}]: position_id deal'den alındı "
                                    f"(deneme {deal_attempt}): order={order_ticket_raw} "
                                    f"→ position={position_ticket}"
                                )
                                break

                    # Yöntem 2: Sembolden positions_get ile ara (fallback)
                    if position_ticket == 0:
                        TICKET_MAX_RETRIES = 20  # Toplam ~4.2s (exponential backoff)
                        for attempt in range(1, TICKET_MAX_RETRIES + 1):
                            _time.sleep(min(0.1 * attempt, 0.5))  # 0.1, 0.2, ..., 0.5s
                            by_symbol = self._safe_call(mt5.positions_get, symbol=mt5_name)
                            if by_symbol and len(by_symbol) > 0:
                                # En yüksek ticket = en son açılan pozisyon (netting güvenliği)
                                best = max(by_symbol, key=lambda p: getattr(p, "ticket", 0))
                                position_ticket = getattr(best, "ticket", 0)
                                if position_ticket:
                                    if len(by_symbol) > 1:
                                        logger.warning(
                                            f"SL/TP [{symbol}]: {len(by_symbol)} pozisyon bulundu, "
                                            f"en yüksek ticket seçildi: {position_ticket} "
                                            f"(deal lookup başarısız, sembolden alındı)"
                                        )
                                    else:
                                        logger.info(
                                            f"SL/TP [{symbol}]: pozisyon ticket sembolden alındı "
                                            f"(deneme {attempt}): {position_ticket} "
                                            f"(deal lookup başarısız)"
                                        )
                                    break
                        if position_ticket == 0:
                            logger.error(
                                f"SL/TP KRİTİK [{symbol}]: pozisyon ticket alınamadı "
                                f"({TICKET_MAX_RETRIES} deneme). Korumasız pozisyon riski — "
                                f"emir iptal ediliyor."
                            )
                            # Emri iptal etmeye çalış (market emirse zaten dolmuştur)
                            order_ticket = order_result.get("order", 0)
                            if order_ticket:
                                try:
                                    cancel_req = {
                                        "action": mt5.TRADE_ACTION_REMOVE,
                                        "order": order_ticket,
                                    }
                                    self._safe_call(mt5.order_send, cancel_req, timeout=10.0)
                                except Exception:
                                    pass
                            order_result["sl_tp_applied"] = False
                            order_result["unprotected"] = True
                            return order_result

                    # v5.9.2-fix: TRADE_ACTION_SLTP sadece action/symbol/position/sl/tp kabul eder
                    # type_filling ve type_time TRADE_ACTION_DEAL içindir — GCM retcode=10035 veriyordu
                    sltp_request: dict[str, Any] = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": mt5_name,
                        "position": position_ticket,
                        "sl": sl_rounded,
                        "tp": tp_rounded,
                    }

                    logger.info(
                        f"SL/TP ekleniyor [{symbol}]: position={position_ticket} "
                        f"SL={sl_rounded:.4f} TP={tp_rounded:.4f} "
                        f"request={sltp_request}"
                    )

                    # ── Freeze level kontrolü ──────────────────────────
                    freeze_level = getattr(sym_info, "trade_freeze_level", 0) or 0
                    if freeze_level > 0:
                        freeze_dist = freeze_level * (tick_size if tick_size > 0 else sym_info.point)
                        if sl_rounded > 0 and abs(price - sl_rounded) < freeze_dist:
                            logger.warning(
                                f"SL freeze level içinde [{symbol}]: "
                                f"SL={sl_rounded:.4f} fiyat={price:.4f} "
                                f"freeze={freeze_dist:.4f} — SL ayarlanıyor"
                            )
                            if direction.upper() == "BUY":
                                sl_rounded = round((price - freeze_dist - tick_size) / tick_size) * tick_size
                            else:
                                sl_rounded = round((price + freeze_dist + tick_size) / tick_size) * tick_size
                            sltp_request["sl"] = sl_rounded

                    # 5 deneme ile SL/TP ekleme — artan bekleme süresi
                    # (exchange modda deal tamamlanmadan modify başarısız olabiliyor)
                    sltp_applied = False
                    SLTP_MAX_RETRIES = 5
                    for sltp_attempt in range(1, SLTP_MAX_RETRIES + 1):
                        sltp_result = self._safe_call(mt5.order_send, sltp_request, timeout=10.0)
                        if sltp_result is not None and sltp_result.retcode == mt5.TRADE_RETCODE_DONE:
                            order_result["sl_tp_applied"] = True
                            sltp_applied = True
                            logger.info(
                                f"SL/TP başarılı [{symbol}] "
                                f"(deneme {sltp_attempt}/{SLTP_MAX_RETRIES}): "
                                f"SL={sl_rounded:.4f} TP={tp_rounded:.4f}"
                            )
                            break
                        else:
                            sltp_err = (
                                sltp_result.comment
                                if sltp_result else str(mt5.last_error())
                            )
                            retcode = sltp_result.retcode if sltp_result else -1
                            logger.warning(
                                f"SL/TP denemesi {sltp_attempt}/{SLTP_MAX_RETRIES} "
                                f"başarısız [{symbol}]: retcode={retcode} {sltp_err}"
                            )
                            # Retcode 10035 (Invalid order) → SL/TP mesafesini artırarak tekrar dene
                            if retcode == 10035 and sltp_attempt < SLTP_MAX_RETRIES:
                                if sl_rounded > 0:
                                    if direction.upper() == "BUY":
                                        sl_rounded = round((sl_rounded - 2 * tick_size) / tick_size) * tick_size
                                    else:
                                        sl_rounded = round((sl_rounded + 2 * tick_size) / tick_size) * tick_size
                                    sltp_request["sl"] = sl_rounded
                                    logger.info(
                                        f"SL mesafesi artırıldı [{symbol}]: "
                                        f"yeni SL={sl_rounded:.4f}"
                                    )
                            if sltp_attempt < SLTP_MAX_RETRIES:
                                _time.sleep(0.3 * sltp_attempt)  # 0.3, 0.6, 0.9, 1.2s

                    if not sltp_applied:
                        # TRADE_ACTION_SLTP GCM VİOP exchange modda desteklenmiyor.
                        # Pozisyonu KAPATMA — _execute_signal'daki OgulSLTP
                        # mekanizması (Stop/Limit pending emirler) ile SL/TP konulacak.
                        # OgulSLTP da başarısız olursa, koruma kuralı ORADA uygulanır.
                        logger.warning(
                            f"TRADE_ACTION_SLTP {SLTP_MAX_RETRIES} denemede "
                            f"başarısız [{symbol}] — OgulSLTP'ye bırakılıyor "
                            f"(Stop/Limit pending emir ile SL/TP konulacak)"
                        )
                        order_result["sl_tp_applied"] = False

                # Health: başarılı emir kaydı
                if self._health:
                    from engine.health import OrderTiming
                    self._health.record_order(OrderTiming(
                        timestamp=_time.time(),
                        symbol=symbol,
                        direction=direction,
                        duration_ms=(_time.perf_counter() - _order_start) * 1000,
                        success=True,
                        retcode=result.retcode,
                    ))
                return order_result

            except Exception as exc:
                mt5_err = mt5.last_error() if mt5 else None
                logger.error(f"send_order istisnası [{symbol}]: {exc} | MT5: {mt5_err}")
                self._last_order_error = {
                    "reason": f"Beklenmeyen hata: {exc}",
                    "mt5_error": str(mt5_err),
                }
                # Health: başarısız emir kaydı
                if self._health:
                    from engine.health import OrderTiming
                    self._health.record_order(OrderTiming(
                        timestamp=_time.time(),
                        symbol=symbol,
                        direction=direction,
                        duration_ms=(_time.perf_counter() - _order_start) * 1000,
                        success=False,
                        retcode=-1,
                    ))
                return None

    # ── close_position ───────────────────────────────────────────────
    def close_position(
        self,
        ticket: int,
        expected_volume: float | None = None,
    ) -> dict[str, Any] | None:
        """Açık pozisyonu kapat.

        Pozisyon bilgisini ticket ile bulur, ters yönde
        aynı hacimde market emri göndererek kapatır.

        VİOP netting koruması: Eğer ``expected_volume`` verilmişse ve
        MT5'teki gerçek hacim farklıysa, yalnızca beklenen hacim
        kapatılır (partial close). Bu, kullanıcının dışarıdan eklediği
        lotların engine tarafından kapatılmasını önler.

        v5.8/CEO-FAZ2: _write_lock ile thread-safe.

        Args:
            ticket: Pozisyon ticket numarası.
            expected_volume: Engine'in yönettiği lot miktarı (opsiyonel).
                Belirtilmezse MT5'teki tüm hacim kapatılır.

        Returns:
            Kapanış sonuç sözlüğü veya None.
        """
        with self._order_lock, self._write_lock:
            if not self._ensure_connection():
                return None

            try:
                positions = self._safe_call(mt5.positions_get, ticket=ticket)
                if positions is None or len(positions) == 0:
                    logger.error(f"Pozisyon bulunamadı: ticket={ticket}")
                    return None

                pos = positions[0]
                symbol = pos.symbol
                lot = pos.volume

                # ── Netting hacim koruması ───────────────────────────────
                if expected_volume is not None and lot != expected_volume:
                    logger.warning(
                        f"Hacim uyuşmazlığı [ticket={ticket} {symbol}]: "
                        f"MT5={lot} lot, engine={expected_volume} lot — "
                        f"sadece engine hacmi kapatılacak (partial close)"
                    )
                    # Kullanıcı dışarıdan lot eklemiş — sadece kendi lotumuz kapatılır
                    return self.close_position_partial(ticket, expected_volume)

                # Ters yön
                if pos.type == mt5.ORDER_TYPE_BUY:
                    close_type = mt5.ORDER_TYPE_SELL
                    tick = self._safe_call(mt5.symbol_info_tick, symbol)
                    price = tick.bid if tick else 0.0
                else:
                    close_type = mt5.ORDER_TYPE_BUY
                    tick = self._safe_call(mt5.symbol_info_tick, symbol)
                    price = tick.ask if tick else 0.0

                if price == 0.0:
                    logger.error(
                        f"Kapanış fiyatı alınamadı [{symbol}]: {mt5.last_error()}"
                    )
                    return None

                request: dict[str, Any] = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": lot,
                    "type": close_type,
                    "price": price,
                    "position": ticket,
                    "type_filling": mt5.ORDER_FILLING_RETURN,
                    "comment": "USTAT_CLOSE",
                }

                logger.info(
                    f"Pozisyon kapatılıyor: ticket={ticket}, "
                    f"{symbol} {lot} lot @ {price:.4f}"
                )

                result = self._safe_call(mt5.order_send, request, timeout=15.0)
                if result is None:
                    # Fix Y10: CRITICAL — pozisyon hâlâ açık, manuel müdahale gerekebilir
                    logger.critical(
                        f"POZİSYON KAPATILAMADI [{ticket}]: order_send None döndü, "
                        f"last_error={mt5.last_error()} — POZİSYON HÂLÂ AÇIK!"
                    )
                    return None

                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    # Fix Y10: CRITICAL — pozisyon hâlâ açık, manuel müdahale gerekebilir
                    logger.critical(
                        f"POZİSYON KAPATILAMADI [{ticket}]: retcode={result.retcode}, "
                        f"comment={result.comment} — POZİSYON HÂLÂ AÇIK!"
                    )
                    return None

                close_result = result._asdict()
                logger.info(
                    f"Pozisyon kapatıldı: ticket={ticket}, "
                    f"order={close_result.get('order')}"
                )
                return close_result

            except Exception as exc:
                logger.critical(f"POZİSYON KAPATILAMADI [ticket={ticket}]: {exc} — POZİSYON HÂLÂ AÇIK!")
                return None

    # ── close_position_partial ─────────────────────────────────────────
    def close_position_partial(
        self,
        ticket: int,
        volume: float,
    ) -> dict[str, Any] | None:
        """Pozisyonun belirtilen kısmını kapat (TP1 yarım kapanış için).

        Netting modda, belirtilen hacim kadar ters yönde emir gönderir.
        Kalan pozisyon açık kalır.

        Args:
            ticket: Pozisyon ticket numarası.
            volume: Kapatılacak lot miktarı.

        Returns:
            Kapanış sonuç sözlüğü veya None.
        """
        if not self._ensure_connection():
            return None

        try:
            positions = self._safe_call(mt5.positions_get, ticket=ticket)
            if positions is None or len(positions) == 0:
                logger.error(f"Pozisyon bulunamadı (partial): ticket={ticket}")
                return None

            pos = positions[0]
            symbol = pos.symbol

            # Hacim doğrulama: istenen hacim pozisyon hacminden büyük olamaz
            if volume > pos.volume:
                logger.error(
                    f"Kısmi kapanış hacmi pozisyon hacminden büyük: "
                    f"{volume} > {pos.volume} [{symbol}]"
                )
                return None

            # Lot step yuvarlama
            info = self._safe_call(mt5.symbol_info, symbol)
            if info and info.volume_step > 0:
                step = info.volume_step
                volume = round(
                    math.floor(volume / step) * step,
                    int(round(-math.log10(step))),
                )
            if volume <= 0:
                logger.warning(f"Kısmi kapanış hacmi sıfır/negatif: {volume}")
                return None

            # Ters yön
            if pos.type == mt5.ORDER_TYPE_BUY:
                close_type = mt5.ORDER_TYPE_SELL
                tick = self._safe_call(mt5.symbol_info_tick, symbol)
                price = tick.bid if tick else 0.0
            else:
                close_type = mt5.ORDER_TYPE_BUY
                tick = self._safe_call(mt5.symbol_info_tick, symbol)
                price = tick.ask if tick else 0.0

            if price == 0.0:
                logger.error(
                    f"Kısmi kapanış fiyatı alınamadı [{symbol}]: "
                    f"{mt5.last_error()}"
                )
                return None

            request: dict[str, Any] = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": close_type,
                "price": price,
                "position": ticket,
                "type_filling": mt5.ORDER_FILLING_RETURN,
                "comment": "USTAT_PARTIAL_CLOSE",
            }

            logger.info(
                f"Kısmi kapanış: ticket={ticket}, "
                f"{symbol} {volume}/{pos.volume} lot @ {price:.4f}"
            )

            result = self._safe_call(mt5.order_send, request, timeout=15.0)
            if result is None:
                logger.error(
                    f"Kısmi kapanış emri None [{ticket}]: {mt5.last_error()}"
                )
                return None

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(
                    f"Kısmi kapanış reddedildi [{ticket}]: "
                    f"retcode={result.retcode}, comment={result.comment}"
                )
                return None

            close_result = result._asdict()
            logger.info(
                f"Kısmi kapanış başarılı: ticket={ticket}, "
                f"kapatılan={volume} lot, order={close_result.get('order')}"
            )
            return close_result

        except Exception as exc:
            logger.error(
                f"close_position_partial istisnası [ticket={ticket}]: {exc}"
            )
            return None

    # ── modify_position ──────────────────────────────────────────────
    def modify_position(
        self,
        ticket: int,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict[str, Any] | None:
        """Açık pozisyonun SL/TP değerlerini değiştir.

        Args:
            ticket: Pozisyon ticket numarası.
            sl: Yeni stop-loss fiyatı (None ise mevcut korunur).
            tp: Yeni take-profit fiyatı (None ise mevcut korunur).

        Returns:
            Değiştirme sonuç sözlüğü veya None.

        v5.8/CEO-FAZ2: _write_lock ile thread-safe.
        """
        # v5.8/CEO-FAZ2: modify de write_lock + order_lock altına alındı
        with self._order_lock, self._write_lock:
            if not self._ensure_connection():
                return None

            try:
                positions = self._safe_call(mt5.positions_get, ticket=ticket)
                if positions is None or len(positions) == 0:
                    # Exchange netting modda ticket, order ticket olabilir.
                    # deal history'den doğru position_id'yi bulmayı dene.
                    resolved = False
                    deals = self._safe_call(mt5.history_deals_get, order=ticket)
                    if deals is not None and len(deals) > 0:
                        pos_id = getattr(deals[0], "position_id", 0)
                        if pos_id and pos_id > 0 and pos_id != ticket:
                            positions = self._safe_call(mt5.positions_get, ticket=pos_id)
                            if positions and len(positions) > 0:
                                logger.info(
                                    f"Modify: order ticket → position ticket çözümlendi "
                                    f"[{ticket} → {pos_id}]"
                                )
                                ticket = pos_id  # Doğru ticket ile devam et
                                resolved = True
                    if not resolved:
                        logger.error(f"Pozisyon bulunamadı (modify): ticket={ticket}")
                        self._last_modify_error = {
                            "retcode": -1,
                            "comment": f"Position not found for ticket={ticket}",
                        }
                        return None

                pos = positions[0]
                new_sl = sl if sl is not None else pos.sl
                new_tp = tp if tp is not None else pos.tp

                # tick_size'a yuvarla (send_order ile aynı mantık)
                sym_info = self._safe_call(mt5.symbol_info, pos.symbol)
                if sym_info is not None:
                    tick_size = getattr(sym_info, "trade_tick_size", 0) or 0
                    if tick_size <= 0:
                        tick_size = getattr(sym_info, "point", 0) or 0
                    if tick_size > 0:
                        new_sl = (
                            round(new_sl / tick_size) * tick_size
                            if new_sl > 0 else 0.0
                        )
                        new_tp = (
                            round(new_tp / tick_size) * tick_size
                            if new_tp > 0 else 0.0
                        )
                    else:
                        new_sl = round(new_sl, 5) if new_sl > 0 else 0.0
                        new_tp = round(new_tp, 5) if new_tp > 0 else 0.0
                else:
                    new_sl = round(new_sl, 5) if new_sl > 0 else 0.0
                    new_tp = round(new_tp, 5) if new_tp > 0 else 0.0

                self._last_modify_error = {}

                # ── stops_level kontrolü (modify) ─────────────────────
                if sym_info is not None:
                    stops_level = getattr(sym_info, "trade_stops_level", 0) or 0
                    if stops_level > 0:
                        t_size = (getattr(sym_info, "trade_tick_size", 0) or 0)
                        if t_size <= 0:
                            t_size = getattr(sym_info, "point", 0) or 0.01
                        min_dist = stops_level * t_size
                        current_price = pos.price_current
                        pos_type = pos.type  # 0=BUY, 1=SELL

                        if new_sl > 0:
                            if pos_type == 0 and current_price - new_sl < min_dist:
                                new_sl = round((current_price - min_dist) / t_size) * t_size
                                logger.warning(
                                    f"Modify SL stops_level ayarı [{pos.symbol}]: "
                                    f"SL={new_sl:.4f} (min mesafe={min_dist:.4f}, fiyat={current_price:.4f})"
                                )
                            elif pos_type == 1 and new_sl - current_price < min_dist:
                                new_sl = round((current_price + min_dist) / t_size) * t_size
                                logger.warning(
                                    f"Modify SL stops_level ayarı [{pos.symbol}]: "
                                    f"SL={new_sl:.4f} (min mesafe={min_dist:.4f}, fiyat={current_price:.4f})"
                                )

                        if new_tp > 0:
                            if pos_type == 0 and new_tp - current_price < min_dist:
                                new_tp = round((current_price + min_dist) / t_size) * t_size
                                logger.warning(
                                    f"Modify TP stops_level ayarı [{pos.symbol}]: "
                                    f"TP={new_tp:.4f} (min mesafe={min_dist:.4f})"
                                )
                            elif pos_type == 1 and current_price - new_tp < min_dist:
                                new_tp = round((current_price - min_dist) / t_size) * t_size
                                logger.warning(
                                    f"Modify TP stops_level ayarı [{pos.symbol}]: "
                                    f"TP={new_tp:.4f} (min mesafe={min_dist:.4f})"
                                )

                # ── Freeze level kontrolü (modify) ──────────────────
                if sym_info is not None:
                    freeze_level = getattr(sym_info, "trade_freeze_level", 0) or 0
                    if freeze_level > 0:
                        t_size_f = (getattr(sym_info, "trade_tick_size", 0) or 0)
                        if t_size_f <= 0:
                            t_size_f = getattr(sym_info, "point", 0) or 0.01
                        freeze_dist = freeze_level * t_size_f
                        cp = pos.price_current
                        if new_sl > 0 and abs(cp - new_sl) < freeze_dist:
                            if pos.type == 0:  # BUY
                                new_sl = round((cp - freeze_dist - t_size_f) / t_size_f) * t_size_f
                            else:  # SELL
                                new_sl = round((cp + freeze_dist + t_size_f) / t_size_f) * t_size_f
                            logger.warning(
                                f"Modify SL freeze ayarı [{pos.symbol}]: "
                                f"SL={new_sl:.4f} (freeze={freeze_dist:.4f})"
                            )

                # Mevcut SL/TP ile aynıysa gereksiz modify yapma (10035 önleme)
                if abs(new_sl - pos.sl) < 1e-8 and abs(new_tp - pos.tp) < 1e-8:
                    logger.debug(
                        f"Modify atlandı [{pos.symbol}]: SL/TP zaten aynı "
                        f"(SL={new_sl:.4f}, TP={new_tp:.4f})"
                    )
                    return {"retcode": 0, "comment": "no_change"}

                position_ticket = int(getattr(pos, "ticket", ticket))
                # v5.9.2-fix: TRADE_ACTION_SLTP — type_filling/type_time kaldırıldı (10035 fix)
                request: dict[str, Any] = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": pos.symbol,
                    "position": position_ticket,
                    "sl": float(new_sl),
                    "tp": float(new_tp),
                }

                logger.info(
                    f"Modify SL/TP: ticket={ticket} position={position_ticket} "
                    f"pos.symbol={pos.symbol} SL={new_sl:.4f} TP={new_tp:.4f}"
                )

                MODIFY_MAX_RETRIES = 5
                for attempt in range(1, MODIFY_MAX_RETRIES + 1):
                    result = self._safe_call(mt5.order_send, request, timeout=10.0)

                    if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                        self._last_modify_error = {}
                        mod_result = result._asdict()
                        logger.info(
                            f"Pozisyon değiştirildi (deneme {attempt}): ticket={ticket}, "
                            f"SL={new_sl:.4f}, TP={new_tp:.4f}"
                        )
                        return mod_result

                    if result is not None:
                        ret = int(result.retcode)
                        comment = str(result.comment) if result.comment else ""
                        self._last_modify_error = {"retcode": ret, "comment": comment}
                        logger.warning(
                            f"Modify deneme {attempt}/{MODIFY_MAX_RETRIES} başarısız [{ticket}]: "
                            f"retcode={ret}, comment={comment}"
                        )
                    else:
                        err = mt5.last_error()
                        self._last_modify_error = {"last_error": str(err) if err else "Bilinmeyen hata"}
                        logger.warning(
                            f"Modify deneme {attempt}/{MODIFY_MAX_RETRIES} None [{ticket}]: {err}"
                        )

                    if attempt < MODIFY_MAX_RETRIES:
                        _time.sleep(0.5)

                logger.error(
                    f"Modify {MODIFY_MAX_RETRIES} denemede başarısız [{ticket}]: "
                    f"{self._last_modify_error}"
                )
                return None

            except Exception as exc:
                mt5_err = mt5.last_error() if mt5 else None
                self._last_modify_error = {"exception": str(exc), "mt5_error": str(mt5_err)}
                logger.error(f"modify_position istisnası [ticket={ticket}]: {exc} | MT5: {mt5_err}")
                return None

    # ── get_positions ────────────────────────────────────────────────
    def get_positions(self) -> list[dict[str, Any]]:
        """Tüm açık pozisyonları getir.

        Yalnızca izlenen 15 kontrata ait pozisyonları filtreler.

        Returns:
            Pozisyon sözlüklerinin listesi.
            Her sözlükte: ticket, symbol, type, volume, price_open,
            sl, tp, price_current, profit, time.
        """
        if not self._ensure_connection():
            logger.warning("get_positions: MT5 bağlantısı yok — None döndürülüyor")
            return None

        try:
            positions = self._safe_call(mt5.positions_get)
            if positions is None:
                # MT5 API hatası mı yoksa gerçekten 0 pozisyon mu?
                err = mt5.last_error()
                if err and err[0] != 1:  # 1 = RES_S_OK (başarılı, 0 pozisyon)
                    logger.warning(f"get_positions: MT5 API hatası — {err}")
                    return None
                logger.debug("Açık pozisyon yok.")
                return []

            result: list[dict[str, Any]] = []
            for pos in positions:
                base = self._to_base(pos.symbol)
                if base is None:
                    continue  # izlenmeyen sembol
                result.append({
                    "ticket": pos.ticket,
                    "symbol": base,  # base isim döndür
                    "type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                    "volume": pos.volume,
                    "price_open": pos.price_open,
                    "sl": pos.sl,
                    "tp": pos.tp,
                    "price_current": pos.price_current,
                    "profit": pos.profit,
                    "swap": pos.swap,
                    "time": datetime.fromtimestamp(pos.time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                })

            logger.debug(f"Açık pozisyon sayısı: {len(result)}")
            return result

        except Exception as exc:
            logger.error(f"get_positions istisnası: {exc}")
            return None

    # ── get_history ──────────────────────────────────────────────────
    def get_history(
        self,
        date_from: datetime,
        date_to: datetime,
    ) -> list[dict[str, Any]]:
        """Belirli tarih aralığındaki işlem geçmişini getir.

        Args:
            date_from: Başlangıç tarihi.
            date_to: Bitiş tarihi.

        Returns:
            İşlem sözlüklerinin listesi.
            Her sözlükte: ticket, order, symbol, type, volume,
            price, profit, commission, swap, fee, time, comment.
        """
        if not self._ensure_connection():
            return []

        try:
            deals = self._safe_call(mt5.history_deals_get, date_from, date_to)
            if deals is None:
                logger.debug(
                    f"İşlem geçmişi boş: {date_from} → {date_to}, "
                    f"hata={mt5.last_error()}"
                )
                return []

            result: list[dict[str, Any]] = []
            for deal in deals:
                base = self._to_base(deal.symbol)
                if base is None:
                    continue  # izlenmeyen sembol
                result.append({
                    "ticket": deal.ticket,
                    "order": deal.order,
                    "symbol": base,  # base isim döndür
                    "type": deal.type,
                    "volume": deal.volume,
                    "price": deal.price,
                    "profit": deal.profit,
                    "commission": deal.commission,
                    "swap": deal.swap,
                    "fee": deal.fee,
                    "time": datetime.fromtimestamp(deal.time).isoformat(),
                    "comment": deal.comment,
                })

            logger.info(
                f"İşlem geçmişi: {len(result)} deal "
                f"({date_from.date()} → {date_to.date()})"
            )
            return result

        except Exception as exc:
            logger.error(f"get_history istisnası: {exc}")
            return []

    # ── get_history_for_sync ────────────────────────────────────────
    def get_history_for_sync(self, days: int = 90) -> list[dict[str, Any]]:
        """MT5 işlem geçmişini pozisyon bazlı trade'lere dönüştür.

        Tüm deal'leri çeker, position_id ile gruplar,
        IN/OUT eşleştirmesi yaparak trade kayıtları oluşturur.
        İzlenmeyen semboller dahil — regex ile base çıkarır.

        Args:
            days: Geriye dönük kaç günlük geçmiş çekilecek.

        Returns:
            Her biri bir tamamlanmış trade olan dict listesi.
        """
        if not self._ensure_connection():
            return []

        import re
        from collections import defaultdict
        from datetime import timedelta

        date_to = datetime.now()
        date_from = date_to - timedelta(days=days)

        try:
            deals = self._safe_call(mt5.history_deals_get, date_from, date_to)
            if deals is None:
                logger.debug(f"Sync: işlem geçmişi boş, hata={mt5.last_error()}")
                return []

            # 1. position_id ile grupla (balance/correction deal'leri atla)
            positions: dict[int, list] = defaultdict(list)
            for d in deals:
                if d.position_id and d.symbol:
                    positions[d.position_id].append(d)

            # 2. Her pozisyonu trade'e dönüştür
            trades: list[dict[str, Any]] = []
            for pos_id, group in positions.items():
                entries = [d for d in group if d.entry == 0]  # IN
                exits = [d for d in group if d.entry == 1]    # OUT

                if not entries or not exits:
                    continue  # eksik pozisyon, atla

                # Base sembol çıkar (tüm vade aylarını destekler)
                sample_symbol = group[0].symbol
                m = re.match(r"^(F_[A-Z]+)\d{4}", sample_symbol)
                if not m:
                    continue
                base_symbol = m.group(1)

                # Direction: ilk IN deal'in tipi (0=BUY, 1=SELL)
                direction = "BUY" if entries[0].type == 0 else "SELL"

                # Entry: ağırlıklı ortalama fiyat, toplam lot, en erken zaman
                total_entry_vol = sum(d.volume for d in entries)
                entry_price = (
                    sum(d.price * d.volume for d in entries) / total_entry_vol
                    if total_entry_vol > 0
                    else entries[0].price
                )
                entry_time = datetime.fromtimestamp(
                    min(d.time for d in entries)
                )

                # Exit: ağırlıklı ortalama fiyat, en geç zaman
                total_exit_vol = sum(d.volume for d in exits)
                exit_price = (
                    sum(d.price * d.volume for d in exits) / total_exit_vol
                    if total_exit_vol > 0
                    else exits[0].price
                )
                exit_time = datetime.fromtimestamp(
                    max(d.time for d in exits)
                )

                # PnL, commission, swap: tüm deal'lerin toplamı
                total_pnl = sum(d.profit for d in group)
                total_comm = sum(d.commission for d in group)
                total_swap = sum(d.swap for d in group)

                trades.append({
                    "symbol": base_symbol,
                    "direction": direction,
                    "entry_time": entry_time.isoformat(),
                    "exit_time": exit_time.isoformat(),
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "lot": total_entry_vol,
                    "pnl": round(total_pnl, 2),
                    "commission": round(total_comm, 2),
                    "swap": round(total_swap, 2),
                    "mt5_position_id": pos_id,
                    "strategy": "manual",
                    "exit_reason": "mt5_sync",
                    "regime": "",  # main.py tarafından current regime ile doldurulur
                })

            logger.info(
                f"MT5 sync: {len(trades)} trade eşleşti ({days} gün)"
            )
            return trades

        except Exception as exc:
            logger.error(f"get_history_for_sync istisnası: {exc}")
            return []

    # ── get_deal_summary ─────────────────────────────────────────
    def get_deal_summary(self, position_id: int) -> dict[str, float] | None:
        """Tek bir pozisyonun deal bazlı PnL/komisyon/swap özetini getir.

        MT5 deal geçmişinden position_id'ye ait tüm deal'leri çeker,
        profit/commission/swap toplamlarını hesaplar.

        Args:
            position_id: MT5 pozisyon ticket'ı.

        Returns:
            {"pnl": float, "commission": float, "swap": float} veya
            veri bulunamazsa None.
        """
        if not position_id or position_id == 0:
            return None

        if not self._ensure_connection():
            return None

        try:
            deals = self._safe_call(mt5.history_deals_get, position=position_id)
            if deals is None or len(deals) == 0:
                logger.debug(
                    f"Deal özeti bulunamadı: position_id={position_id}, "
                    f"hata={mt5.last_error()}"
                )
                return None

            total_pnl = sum(d.profit for d in deals)
            total_commission = sum(d.commission for d in deals)
            total_swap = sum(d.swap for d in deals)

            logger.debug(
                f"Deal özeti [pos={position_id}]: "
                f"pnl={total_pnl:.2f} comm={total_commission:.2f} "
                f"swap={total_swap:.2f} ({len(deals)} deal)"
            )

            return {
                "pnl": round(total_pnl, 2),
                "commission": round(total_commission, 2),
                "swap": round(total_swap, 2),
            }

        except Exception as exc:
            logger.error(
                f"get_deal_summary istisnası [pos={position_id}]: {exc}"
            )
            return None

    # ── cancel_order ───────────────────────────────────────────────
    def cancel_order(self, order_ticket: int) -> dict[str, Any] | None:
        """Bekleyen emri iptal et.

        ``TRADE_ACTION_REMOVE`` ile bekleyen (LIMIT) emri iptal eder.

        Args:
            order_ticket: İptal edilecek bekleyen emir ticket numarası.

        Returns:
            İptal sonuç sözlüğü veya None.
        """
        if not self._ensure_connection():
            return None

        try:
            request: dict[str, Any] = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order_ticket,
            }

            logger.info(f"Emir iptal ediliyor: order_ticket={order_ticket}")

            result = self._safe_call(mt5.order_send, request, timeout=10.0)
            if result is None:
                logger.error(
                    f"cancel_order None döndü [{order_ticket}]: {mt5.last_error()}"
                )
                return None

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(
                    f"Emir iptali reddedildi [{order_ticket}]: "
                    f"retcode={result.retcode}, comment={result.comment}"
                )
                return None

            cancel_result = result._asdict()
            logger.info(f"Emir iptal edildi: order_ticket={order_ticket}")
            return cancel_result

        except Exception as exc:
            logger.error(f"cancel_order istisnası [{order_ticket}]: {exc}")
            return None

    # ── get_pending_orders ─────────────────────────────────────────
    def get_pending_orders(
        self,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """Bekleyen (doldurulmamış) emirleri getir.

        Args:
            symbol: Opsiyonel sembol filtresi.

        Returns:
            Bekleyen emir sözlüklerinin listesi.
            Her sözlükte: ticket, symbol, type, volume, volume_current,
            price_open, sl, tp, time_setup.
        """
        if not self._ensure_connection():
            return []

        try:
            if symbol:
                mt5_name = self._to_mt5(symbol)
                orders = self._safe_call(mt5.orders_get, symbol=mt5_name)
            else:
                orders = self._safe_call(mt5.orders_get)

            if orders is None:
                logger.debug("Bekleyen emir yok.")
                return []

            result: list[dict[str, Any]] = []
            for order in orders:
                base = self._to_base(order.symbol)
                if base is None:
                    continue  # izlenmeyen sembol
                # Emir tipi haritalama
                order_type_map = {
                    mt5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT",
                    mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
                    mt5.ORDER_TYPE_BUY_STOP: "BUY_STOP",
                    mt5.ORDER_TYPE_SELL_STOP: "SELL_STOP",
                    mt5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY_STOP_LIMIT",
                    mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL_STOP_LIMIT",
                }
                order_type_str = order_type_map.get(order.type, f"UNKNOWN_{order.type}")

                order_dict: dict[str, Any] = {
                    "ticket": order.ticket,
                    "symbol": base,  # base isim döndür
                    "type": order_type_str,
                    "volume": order.volume_initial,
                    "volume_current": order.volume_current,
                    "price_open": order.price_open,
                    "sl": order.sl,
                    "tp": order.tp,
                    "time_setup": datetime.fromtimestamp(
                        order.time_setup
                    ).isoformat(),
                    "comment": getattr(order, "comment", ""),
                }
                # Stop Limit emirleri için stoplimit fiyatı ekle
                if order.type in (
                    mt5.ORDER_TYPE_BUY_STOP_LIMIT,
                    mt5.ORDER_TYPE_SELL_STOP_LIMIT,
                ):
                    order_dict["stoplimit"] = order.price_stoplimit

                result.append(order_dict)

            logger.debug(f"Bekleyen emir sayısı: {len(result)}")
            return result

        except Exception as exc:
            logger.error(f"get_pending_orders istisnası: {exc}")
            return []

    # ── check_order_status ─────────────────────────────────────────
    def check_order_status(
        self,
        order_ticket: int,
    ) -> dict[str, Any] | None:
        """Emir durumunu kontrol et.

        Bekleyen emirler ve geçmişi kontrol ederek emrin durumunu belirler:
        pending, filled, partial veya cancelled.

        Args:
            order_ticket: Kontrol edilecek emir ticket numarası.

        Returns:
            Durum sözlüğü: ``status``, ``filled_volume``,
            ``remaining_volume``, ``deal_ticket`` — veya None.
        """
        if not self._ensure_connection():
            return None

        try:
            # 1. Hâlâ bekleyen emirlerde mi?
            pending = self._safe_call(mt5.orders_get, ticket=order_ticket)
            if pending is not None and len(pending) > 0:
                order = pending[0]
                filled = order.volume_initial - order.volume_current
                return {
                    "status": "pending",
                    "filled_volume": filled,
                    "remaining_volume": order.volume_current,
                    "deal_ticket": 0,
                }

            # 2. Geçmiş emirlerde ara
            history = self._safe_call(mt5.history_orders_get, ticket=order_ticket)
            if history is None or len(history) == 0:
                logger.debug(
                    f"Emir geçmişte bulunamadı: ticket={order_ticket}"
                )
                return None

            hist_order = history[0]
            vol_initial = hist_order.volume_initial
            vol_current = hist_order.volume_current
            filled_vol = vol_initial - vol_current

            # Pozisyona dönüşmüş mü? (deal → position_id bul)
            deal_ticket = 0
            position_ticket = 0
            deals = self._safe_call(mt5.history_deals_get, order=order_ticket)
            if deals is not None and len(deals) > 0:
                deal_ticket = deals[0].ticket
                # Netting modda deal.position_id = pozisyon ticket'ı
                position_ticket = getattr(deals[0], "position_id", 0)
                # Birden fazla deal varsa (kısmi dolum), toplam hacmi hesapla
                filled_vol = sum(d.volume for d in deals)

            if filled_vol >= vol_initial * 0.999:
                status = "filled"
            elif filled_vol > 0:
                status = "partial"
            else:
                status = "cancelled"

            return {
                "status": status,
                "filled_volume": filled_vol,
                "remaining_volume": max(vol_initial - filled_vol, 0.0),
                "deal_ticket": deal_ticket,
                "position_ticket": position_ticket or deal_ticket,
            }

        except Exception as exc:
            logger.error(
                f"check_order_status istisnası [{order_ticket}]: {exc}"
            )
            return None

    # ── send_stop ────────────────────────────────────────────────────
    def send_stop(
        self,
        symbol: str,
        direction: str,
        lot: float,
        price: float,
        comment: str = "USTAT_SL",
    ) -> dict[str, Any] | None:
        """Buy Stop veya Sell Stop bekleyen emri gönder.

        SL koruması için kullanılır. Tetiklendiğinde MARKET emri olarak
        çalışır — dolum garantili.

        Buy Stop  : ask ≥ price → market buy tetiklenir
        Sell Stop : bid ≤ price → market sell tetiklenir

        VİOP netting modda ters yönlü emir pozisyonu kapatır/azaltır.

        Args:
            symbol: Kontrat sembolü (ör. "F_AKBNK").
            direction: "BUY" (Buy Stop) veya "SELL" (Sell Stop).
            lot: Lot miktarı.
            price: Tetikleme fiyatı (stop seviyesi).
            comment: Emir yorumu.

        Returns:
            Emir sonuç sözlüğü (order_ticket, retcode) veya None.
        """
        with self._order_lock, self._write_lock:
            if not self._ensure_connection():
                logger.error("send_stop: MT5 bağlantısı yok")
                return None

            try:
                mt5_name = self._to_mt5(symbol)

                # Sembol bilgisi
                sym_info = self._safe_call(mt5.symbol_info, mt5_name)
                if sym_info is None:
                    logger.error(f"send_stop: symbol_info alınamadı [{symbol}]")
                    return None

                tick_size = sym_info.trade_tick_size
                if tick_size <= 0:
                    tick_size = sym_info.point

                # Fiyatı tick_size'a yuvarla
                price = round(price / tick_size) * tick_size

                # Lot validasyonu
                vol_min = sym_info.volume_min
                vol_max = sym_info.volume_max
                vol_step = sym_info.volume_step if sym_info.volume_step > 0 else vol_min
                lot = round(lot / vol_step) * vol_step
                lot = max(vol_min, min(vol_max, lot))

                # Emir tipi belirle
                if direction.upper() == "BUY":
                    mt5_type = mt5.ORDER_TYPE_BUY_STOP
                elif direction.upper() == "SELL":
                    mt5_type = mt5.ORDER_TYPE_SELL_STOP
                else:
                    logger.error(f"send_stop: Geçersiz yön: {direction}")
                    return None

                # Fiyat ilişkisi doğrulama
                tick = self._safe_call(mt5.symbol_info_tick, mt5_name)
                if tick is not None:
                    if direction.upper() == "BUY":
                        if price <= tick.ask:
                            logger.warning(
                                f"send_stop: BUY STOP price ({price:.4f}) "
                                f"<= Ask ({tick.ask:.4f}) — emir reddedilecek"
                            )
                    else:
                        if price >= tick.bid:
                            logger.warning(
                                f"send_stop: SELL STOP price ({price:.4f}) "
                                f">= Bid ({tick.bid:.4f}) — emir reddedilecek"
                            )

                # Emir isteği — ORDER_TIME_DAY (GCM VİOP)
                request: dict[str, Any] = {
                    "action": mt5.TRADE_ACTION_PENDING,
                    "symbol": mt5_name,
                    "volume": lot,
                    "type": mt5_type,
                    "price": price,
                    "type_filling": mt5.ORDER_FILLING_RETURN,
                    "type_time": mt5.ORDER_TIME_DAY,
                    "comment": comment,
                }

                logger.info(
                    f"Stop emri gönderiliyor: {direction} {lot} lot {symbol} "
                    f"price={price:.4f} request={request}"
                )

                result = self._safe_call(mt5.order_send, request, timeout=15.0)
                if result is None:
                    err = mt5.last_error()
                    logger.error(f"send_stop None [{symbol}]: {err}")
                    return None

                accepted = {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
                if result.retcode not in accepted:
                    logger.error(
                        f"Stop emri reddedildi [{symbol}]: "
                        f"retcode={result.retcode}, comment={result.comment}"
                    )
                    return None

                order_ticket = result.order
                logger.info(
                    f"Stop emri başarılı: ticket={order_ticket} "
                    f"{direction} {lot} lot {symbol} price={price:.4f} "
                    f"retcode={result.retcode}"
                )

                return {
                    "order_ticket": order_ticket,
                    "retcode": result.retcode,
                    "comment": result.comment,
                }

            except Exception as exc:
                logger.error(f"send_stop istisnası [{symbol}]: {exc}")
                return None

    # ── send_limit ───────────────────────────────────────────────────
    def send_limit(
        self,
        symbol: str,
        direction: str,
        lot: float,
        price: float,
        comment: str = "USTAT_TP",
    ) -> dict[str, Any] | None:
        """Buy Limit veya Sell Limit bekleyen emri gönder.

        TP koruması için kullanılır. Fiyat hedefe ulaştığında tetiklenir.

        Buy Limit  : ask ≤ price → market buy tetiklenir
        Sell Limit : bid ≥ price → market sell tetiklenir

        VİOP netting modda ters yönlü emir pozisyonu kapatır/azaltır.

        Args:
            symbol: Kontrat sembolü (ör. "F_AKBNK").
            direction: "BUY" (Buy Limit) veya "SELL" (Sell Limit).
            lot: Lot miktarı.
            price: Hedef fiyat (limit seviyesi).
            comment: Emir yorumu.

        Returns:
            Emir sonuç sözlüğü (order_ticket, retcode) veya None.
        """
        # Yeni cagri — onceki hata durumunu sifirla
        self._last_limit_error = {}

        with self._order_lock, self._write_lock:
            if not self._ensure_connection():
                logger.error("send_limit: MT5 bağlantısı yok")
                self._last_limit_error = {"last_error": "MT5 bağlantısı yok"}
                return None

            try:
                mt5_name = self._to_mt5(symbol)

                # Sembol bilgisi
                sym_info = self._safe_call(mt5.symbol_info, mt5_name)
                if sym_info is None:
                    logger.error(f"send_limit: symbol_info alınamadı [{symbol}]")
                    self._last_limit_error = {
                        "last_error": f"symbol_info alınamadı: {symbol}",
                    }
                    return None

                tick_size = sym_info.trade_tick_size
                if tick_size <= 0:
                    tick_size = sym_info.point

                # Fiyatı tick_size'a yuvarla
                price = round(price / tick_size) * tick_size

                # Lot validasyonu
                vol_min = sym_info.volume_min
                vol_max = sym_info.volume_max
                vol_step = sym_info.volume_step if sym_info.volume_step > 0 else vol_min
                lot = round(lot / vol_step) * vol_step
                lot = max(vol_min, min(vol_max, lot))

                # Emir tipi belirle
                if direction.upper() == "BUY":
                    mt5_type = mt5.ORDER_TYPE_BUY_LIMIT
                elif direction.upper() == "SELL":
                    mt5_type = mt5.ORDER_TYPE_SELL_LIMIT
                else:
                    logger.error(f"send_limit: Geçersiz yön: {direction}")
                    self._last_limit_error = {
                        "last_error": f"Geçersiz yön: {direction}",
                    }
                    return None

                # Fiyat ilişkisi doğrulama
                tick = self._safe_call(mt5.symbol_info_tick, mt5_name)
                if tick is not None:
                    if direction.upper() == "BUY":
                        if price >= tick.ask:
                            logger.warning(
                                f"send_limit: BUY LIMIT price ({price:.4f}) "
                                f">= Ask ({tick.ask:.4f}) — hemen dolabilir"
                            )
                    else:
                        if price <= tick.bid:
                            logger.warning(
                                f"send_limit: SELL LIMIT price ({price:.4f}) "
                                f"<= Bid ({tick.bid:.4f}) — hemen dolabilir"
                            )

                # Emir isteği — ORDER_TIME_DAY (GCM VİOP)
                request: dict[str, Any] = {
                    "action": mt5.TRADE_ACTION_PENDING,
                    "symbol": mt5_name,
                    "volume": lot,
                    "type": mt5_type,
                    "price": price,
                    "type_filling": mt5.ORDER_FILLING_RETURN,
                    "type_time": mt5.ORDER_TIME_DAY,
                    "comment": comment,
                }

                logger.info(
                    f"Limit emri gönderiliyor: {direction} {lot} lot {symbol} "
                    f"price={price:.4f} request={request}"
                )

                result = self._safe_call(mt5.order_send, request, timeout=15.0)
                if result is None:
                    err = mt5.last_error()
                    logger.error(f"send_limit None [{symbol}]: {err}")
                    self._last_limit_error = {
                        "last_error": str(err) if err else "order_send None",
                    }
                    return None

                accepted = {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
                if result.retcode not in accepted:
                    logger.error(
                        f"Limit emri reddedildi [{symbol}]: "
                        f"retcode={result.retcode}, comment={result.comment}"
                    )
                    self._last_limit_error = {
                        "retcode": int(result.retcode),
                        "comment": str(result.comment) if result.comment else "",
                    }
                    return None

                order_ticket = result.order
                logger.info(
                    f"Limit emri başarılı: ticket={order_ticket} "
                    f"{direction} {lot} lot {symbol} price={price:.4f} "
                    f"retcode={result.retcode}"
                )

                return {
                    "order_ticket": order_ticket,
                    "retcode": result.retcode,
                    "comment": result.comment,
                }

            except Exception as exc:
                logger.error(f"send_limit istisnası [{symbol}]: {exc}")
                self._last_limit_error = {"exception": str(exc)}
                return None

    # ── modify_pending_order ─────────────────────────────────────────
    def modify_pending_order(
        self,
        order_ticket: int,
        new_price: float,
        new_stoplimit: float | None = None,
    ) -> dict[str, Any] | None:
        """Bekleyen STOP, LIMIT veya STOP LIMIT emrinin fiyatını güncelle.

        TRADE_ACTION_MODIFY ile atomik güncelleme — tek API çağrısı.
        PrimNet trailing stop ve OĞUL trailing SL için kullanılır.

        STOP LIMIT emirlerde hem tetikleme (price) hem limit (stoplimit)
        fiyatı birlikte güncellenmelidir — aksi halde MT5 ``10015 Invalid
        price`` ile reddeder çünkü SELL STOP LIMIT'te stoplimit ≥ price,
        BUY STOP LIMIT'te stoplimit ≤ price koşulu zorunludur.

        Args:
            order_ticket: Bekleyen emir ticket numarası.
            new_price: Yeni tetikleme/limit fiyatı.
            new_stoplimit: STOP LIMIT emirler için yeni limit fiyatı.
                None ise request'e eklenmez (geriye uyumlu).

        Returns:
            Değiştirme sonuç sözlüğü veya None.
        """
        with self._order_lock, self._write_lock:
            if not self._ensure_connection():
                logger.error("modify_pending_order: MT5 bağlantısı yok")
                return None

            try:
                # Mevcut emri bul
                pending = self._safe_call(mt5.orders_get, ticket=order_ticket)
                if pending is None or len(pending) == 0:
                    logger.error(
                        f"modify_pending_order: Emir bulunamadı ticket={order_ticket}"
                    )
                    return None

                order = pending[0]

                # tick_size al
                sym_info = self._safe_call(mt5.symbol_info, order.symbol)
                tick_size = 0.01
                if sym_info is not None:
                    tick_size = sym_info.trade_tick_size or sym_info.point or 0.01

                # Fiyatı tick_size'a yuvarla
                new_price = round(new_price / tick_size) * tick_size

                # Değişiklik yoksa atla
                if abs(new_price - order.price_open) < tick_size * 0.5:
                    logger.debug(
                        f"modify_pending_order atlandı [{order_ticket}]: fiyat aynı"
                    )
                    return {"retcode": 0, "comment": "no_change"}

                request: dict[str, Any] = {
                    "action": mt5.TRADE_ACTION_MODIFY,
                    "order": order_ticket,
                    "price": new_price,
                    "type_time": mt5.ORDER_TIME_DAY,
                }

                # STOP LIMIT emirlerde limit fiyatı da güncellenmeli
                if new_stoplimit is not None:
                    new_stoplimit = round(new_stoplimit / tick_size) * tick_size
                    request["stoplimit"] = new_stoplimit

                sl_info = f" stoplimit={new_stoplimit:.4f}" if new_stoplimit is not None else ""
                logger.info(
                    f"Pending order modify: ticket={order_ticket} "
                    f"price={new_price:.4f}{sl_info}"
                )

                MODIFY_MAX_RETRIES = 3
                for attempt in range(1, MODIFY_MAX_RETRIES + 1):
                    result = self._safe_call(mt5.order_send, request, timeout=10.0)

                    if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                        logger.info(
                            f"Pending order modify başarılı (deneme {attempt}): "
                            f"ticket={order_ticket} price={new_price:.4f}{sl_info}"
                        )
                        return {"retcode": result.retcode, "comment": result.comment}

                    err_comment = result.comment if result else str(mt5.last_error())
                    ret = result.retcode if result else -1
                    logger.warning(
                        f"Pending order modify deneme {attempt}/{MODIFY_MAX_RETRIES} "
                        f"başarısız [{order_ticket}]: retcode={ret} {err_comment}"
                    )
                    if attempt < MODIFY_MAX_RETRIES:
                        _time.sleep(0.3 * attempt)

                logger.error(
                    f"Pending order modify {MODIFY_MAX_RETRIES} denemede başarısız: "
                    f"ticket={order_ticket}"
                )
                return None

            except Exception as exc:
                logger.error(
                    f"modify_pending_order istisnası [{order_ticket}]: {exc}"
                )
                return None

    # ── cancel_pending_order ─────────────────────────────────────────
    def cancel_pending_order(
        self,
        order_ticket: int,
    ) -> dict[str, Any] | None:
        """Bekleyen STOP veya LIMIT emrini iptal et.

        Pozisyon kapanışında veya yeni emir yerleştirmede eski emri temizler.

        Args:
            order_ticket: İptal edilecek bekleyen emir ticket numarası.

        Returns:
            İptal sonuç sözlüğü veya None.
        """
        with self._order_lock, self._write_lock:
            if not self._ensure_connection():
                logger.error("cancel_pending_order: MT5 bağlantısı yok")
                return None

            try:
                # Emir hâlâ bekliyor mu kontrol et
                pending = self._safe_call(mt5.orders_get, ticket=order_ticket)
                if pending is None or len(pending) == 0:
                    logger.debug(
                        f"cancel_pending_order: Emir zaten yok ticket={order_ticket} "
                        f"(tetiklenmiş veya iptal edilmiş olabilir)"
                    )
                    return {"retcode": 0, "comment": "already_gone"}

                request: dict[str, Any] = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": order_ticket,
                }

                logger.info(f"Pending order iptal: ticket={order_ticket}")

                result = self._safe_call(mt5.order_send, request, timeout=10.0)
                if result is None:
                    err = mt5.last_error()
                    logger.error(
                        f"cancel_pending_order None [{order_ticket}]: {err}"
                    )
                    return None

                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    logger.error(
                        f"cancel_pending_order reddedildi [{order_ticket}]: "
                        f"retcode={result.retcode}, comment={result.comment}"
                    )
                    return None

                logger.info(
                    f"Pending order iptal başarılı: ticket={order_ticket}"
                )
                return {"retcode": result.retcode, "comment": result.comment}

            except Exception as exc:
                logger.error(
                    f"cancel_pending_order istisnası [{order_ticket}]: {exc}"
                )
                return None

    # ── send_stop_limit ─────────────────────────────────────────────
    def send_stop_limit(
        self,
        symbol: str,
        direction: str,
        lot: float,
        stop_price: float,
        limit_price: float,
        comment: str = "USTAT_SL",
    ) -> dict[str, Any] | None:
        """Buy Stop Limit veya Sell Stop Limit bekleyen emri gönder.

        PrimNet trailing stop mekanizması için kullanılır.
        H-Engine pozisyon kapatma emrini bu fonksiyonla yönetir.

        Buy Stop Limit  : stop_price > mevcut Ask, limit_price < stop_price
        Sell Stop Limit : stop_price < mevcut Bid, limit_price > stop_price

        Args:
            symbol: Kontrat sembolü (ör. "F_AKBNK").
            direction: "BUY" (Buy Stop Limit) veya "SELL" (Sell Stop Limit).
            lot: Lot miktarı.
            stop_price: Tetikleme fiyatı (stop seviyesi).
            limit_price: Uygulama fiyatı (limit seviyesi).
            comment: Emir yorumu.

        Returns:
            Emir sonuç sözlüğü (order_ticket, retcode) veya None.
        """
        # Yeni cagri — onceki hata durumunu sifirla
        self._last_stop_limit_error = {}

        with self._order_lock, self._write_lock:
            if not self._ensure_connection():
                logger.error("send_stop_limit: MT5 bağlantısı yok")
                self._last_stop_limit_error = {"last_error": "MT5 bağlantısı yok"}
                return None

            try:
                mt5_name = self._to_mt5(symbol)

                # Sembol bilgisi
                sym_info = self._safe_call(mt5.symbol_info, mt5_name)
                if sym_info is None:
                    logger.error(f"send_stop_limit: symbol_info alınamadı [{symbol}]")
                    self._last_stop_limit_error = {
                        "last_error": f"symbol_info alınamadı: {symbol}",
                    }
                    return None

                tick_size = sym_info.trade_tick_size
                if tick_size <= 0:
                    tick_size = sym_info.point

                # Fiyatları tick_size'a yuvarla
                stop_price = round(stop_price / tick_size) * tick_size
                limit_price = round(limit_price / tick_size) * tick_size

                # Lot validasyonu
                vol_min = sym_info.volume_min
                vol_max = sym_info.volume_max
                vol_step = sym_info.volume_step if sym_info.volume_step > 0 else vol_min
                lot = round(lot / vol_step) * vol_step
                lot = max(vol_min, min(vol_max, lot))

                # Emir tipi belirle
                if direction.upper() == "BUY":
                    mt5_type = mt5.ORDER_TYPE_BUY_STOP_LIMIT
                elif direction.upper() == "SELL":
                    mt5_type = mt5.ORDER_TYPE_SELL_STOP_LIMIT
                else:
                    logger.error(f"send_stop_limit: Geçersiz yön: {direction}")
                    self._last_stop_limit_error = {
                        "last_error": f"Geçersiz yön: {direction}",
                    }
                    return None

                # Fiyat ilişkisi doğrulama
                tick = self._safe_call(mt5.symbol_info_tick, mt5_name)
                if tick is not None:
                    if direction.upper() == "BUY":
                        if stop_price <= tick.ask:
                            logger.warning(
                                f"send_stop_limit: BUY stop_price ({stop_price:.4f}) "
                                f"<= Ask ({tick.ask:.4f}) — emir reddedilecek"
                            )
                        if limit_price >= stop_price:
                            logger.warning(
                                f"send_stop_limit: BUY limit_price ({limit_price:.4f}) "
                                f">= stop_price ({stop_price:.4f}) — emir reddedilecek"
                            )
                    else:
                        if stop_price >= tick.bid:
                            logger.warning(
                                f"send_stop_limit: SELL stop_price ({stop_price:.4f}) "
                                f">= Bid ({tick.bid:.4f}) — emir reddedilecek"
                            )
                        if limit_price <= stop_price:
                            logger.warning(
                                f"send_stop_limit: SELL limit_price ({limit_price:.4f}) "
                                f"<= stop_price ({stop_price:.4f}) — emir reddedilecek"
                            )

                # Emir isteği — ORDER_TIME_DAY (GCM VİOP doğrulandı)
                request: dict[str, Any] = {
                    "action": mt5.TRADE_ACTION_PENDING,
                    "symbol": mt5_name,
                    "volume": lot,
                    "type": mt5_type,
                    "price": stop_price,
                    "stoplimit": limit_price,
                    "type_filling": mt5.ORDER_FILLING_RETURN,
                    "type_time": mt5.ORDER_TIME_DAY,
                    "comment": comment,
                }

                logger.info(
                    f"Stop Limit gönderiliyor: {direction} {lot} lot {symbol} "
                    f"stop={stop_price:.4f} limit={limit_price:.4f} "
                    f"request={request}"
                )

                result = self._safe_call(mt5.order_send, request, timeout=15.0)
                if result is None:
                    err = mt5.last_error()
                    logger.error(
                        f"send_stop_limit None [{symbol}]: {err}"
                    )
                    self._last_stop_limit_error = {
                        "last_error": str(err) if err else "order_send None",
                    }
                    return None

                # RETCODE_PLACED (10008) = bekleyen emir kabul edildi
                # RETCODE_DONE (10009) = hemen dolduruldu (nadir ama olabilir)
                accepted = {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
                if result.retcode not in accepted:
                    logger.error(
                        f"Stop Limit reddedildi [{symbol}]: "
                        f"retcode={result.retcode}, comment={result.comment}"
                    )
                    self._last_stop_limit_error = {
                        "retcode": int(result.retcode),
                        "comment": str(result.comment) if result.comment else "",
                    }
                    return None

                order_ticket = result.order
                logger.info(
                    f"Stop Limit başarılı: ticket={order_ticket} "
                    f"{direction} {lot} lot {symbol} "
                    f"stop={stop_price:.4f} limit={limit_price:.4f} "
                    f"retcode={result.retcode}"
                )

                return {
                    "order_ticket": order_ticket,
                    "retcode": result.retcode,
                    "comment": result.comment,
                }

            except Exception as exc:
                logger.error(f"send_stop_limit istisnası [{symbol}]: {exc}")
                self._last_stop_limit_error = {"exception": str(exc)}
                return None

    # ── modify_stop_limit ───────────────────────────────────────────
    def modify_stop_limit(
        self,
        order_ticket: int,
        new_stop_price: float | None = None,
        new_limit_price: float | None = None,
    ) -> dict[str, Any] | None:
        """Bekleyen Stop Limit emrinin fiyatlarını güncelle.

        TRADE_ACTION_MODIFY ile atomik güncelleme — tek API çağrısı.
        PrimNet trailing stop her 10 saniyede bu fonksiyonu çağırır.

        Args:
            order_ticket: Bekleyen emir ticket numarası.
            new_stop_price: Yeni tetikleme fiyatı (None ise mevcut korunur).
            new_limit_price: Yeni limit fiyatı (None ise mevcut korunur).

        Returns:
            Değiştirme sonuç sözlüğü veya None.
        """
        with self._order_lock, self._write_lock:
            if not self._ensure_connection():
                logger.error("modify_stop_limit: MT5 bağlantısı yok")
                return None

            try:
                # Mevcut emri bul
                pending = self._safe_call(mt5.orders_get, ticket=order_ticket)
                if pending is None or len(pending) == 0:
                    logger.error(
                        f"modify_stop_limit: Emir bulunamadı ticket={order_ticket}"
                    )
                    return None

                order = pending[0]

                # tick_size al
                sym_info = self._safe_call(mt5.symbol_info, order.symbol)
                tick_size = 0.01
                if sym_info is not None:
                    tick_size = sym_info.trade_tick_size or sym_info.point or 0.01

                # Fiyatları belirle
                stop_price = new_stop_price if new_stop_price is not None else order.price_open
                limit_price = new_limit_price if new_limit_price is not None else order.price_stoplimit

                # tick_size'a yuvarla
                stop_price = round(stop_price / tick_size) * tick_size
                limit_price = round(limit_price / tick_size) * tick_size

                # Değişiklik yoksa atla
                if (abs(stop_price - order.price_open) < tick_size * 0.5
                        and abs(limit_price - order.price_stoplimit) < tick_size * 0.5):
                    logger.debug(
                        f"modify_stop_limit atlandı [{order_ticket}]: fiyatlar aynı"
                    )
                    return {"retcode": 0, "comment": "no_change"}

                request: dict[str, Any] = {
                    "action": mt5.TRADE_ACTION_MODIFY,
                    "order": order_ticket,
                    "price": stop_price,
                    "stoplimit": limit_price,
                    "type_time": mt5.ORDER_TIME_DAY,
                }

                logger.info(
                    f"Stop Limit modify: ticket={order_ticket} "
                    f"stop={stop_price:.4f} limit={limit_price:.4f}"
                )

                MODIFY_MAX_RETRIES = 3
                for attempt in range(1, MODIFY_MAX_RETRIES + 1):
                    result = self._safe_call(mt5.order_send, request, timeout=10.0)

                    if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                        logger.info(
                            f"Stop Limit modify başarılı (deneme {attempt}): "
                            f"ticket={order_ticket} stop={stop_price:.4f} "
                            f"limit={limit_price:.4f}"
                        )
                        return {"retcode": result.retcode, "comment": result.comment}

                    err_comment = result.comment if result else str(mt5.last_error())
                    ret = result.retcode if result else -1
                    logger.warning(
                        f"Stop Limit modify deneme {attempt}/{MODIFY_MAX_RETRIES} "
                        f"başarısız [{order_ticket}]: retcode={ret} {err_comment}"
                    )
                    if attempt < MODIFY_MAX_RETRIES:
                        _time.sleep(0.3 * attempt)

                logger.error(
                    f"Stop Limit modify {MODIFY_MAX_RETRIES} denemede başarısız: "
                    f"ticket={order_ticket}"
                )
                return None

            except Exception as exc:
                logger.error(
                    f"modify_stop_limit istisnası [{order_ticket}]: {exc}"
                )
                return None

    # ── cancel_stop_limit ───────────────────────────────────────────
    def cancel_stop_limit(
        self,
        order_ticket: int,
    ) -> dict[str, Any] | None:
        """Bekleyen Stop Limit emrini iptal et.

        Pozisyon kapanışında veya yeni emir yerleştirmede eski emri temizler.

        Args:
            order_ticket: İptal edilecek bekleyen emir ticket numarası.

        Returns:
            İptal sonuç sözlüğü veya None.
        """
        with self._order_lock, self._write_lock:
            if not self._ensure_connection():
                logger.error("cancel_stop_limit: MT5 bağlantısı yok")
                return None

            try:
                # Emir hâlâ bekliyor mu kontrol et
                pending = self._safe_call(mt5.orders_get, ticket=order_ticket)
                if pending is None or len(pending) == 0:
                    logger.debug(
                        f"cancel_stop_limit: Emir zaten yok ticket={order_ticket} "
                        f"(tetiklenmiş veya iptal edilmiş olabilir)"
                    )
                    return {"retcode": 0, "comment": "already_gone"}

                request: dict[str, Any] = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": order_ticket,
                }

                logger.info(f"Stop Limit iptal: ticket={order_ticket}")

                result = self._safe_call(mt5.order_send, request, timeout=10.0)
                if result is None:
                    err = mt5.last_error()
                    logger.error(
                        f"cancel_stop_limit None [{order_ticket}]: {err}"
                    )
                    return None

                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    logger.error(
                        f"cancel_stop_limit reddedildi [{order_ticket}]: "
                        f"retcode={result.retcode}, comment={result.comment}"
                    )
                    return None

                logger.info(
                    f"Stop Limit iptal başarılı: ticket={order_ticket}"
                )
                return {"retcode": result.retcode, "comment": result.comment}

            except Exception as exc:
                logger.error(
                    f"cancel_stop_limit istisnası [{order_ticket}]: {exc}"
                )
                return None
