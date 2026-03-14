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
from datetime import datetime
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

        # Dinamik sembol eşleme: base → MT5 gerçek ad (ör. F_THYAO → F_THYAO0226)
        self._symbol_map: dict[str, str] = {}
        # Ters eşleme: MT5 gerçek ad → base (ör. F_THYAO0226 → F_THYAO)
        self._reverse_map: dict[str, str] = {}

        # Son emir hatasının detayı — send_order() None döndüğünde
        # çağıran kod buradan retcode/comment okuyabilir.
        self._last_order_error: dict[str, Any] = {}
        # modify_position() başarısız olduğunda MT5 hata detayı (hibrit devir vb.)
        self._last_modify_error: dict[str, Any] = {}
        # Emir gönderimi tek seferde bir çağrı (manuel + engine race önlemi)
        self._order_lock: threading.Lock = threading.Lock()
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
                # Cooldown doldu — probe denemesi için izin ver
                logger.info(
                    f"Circuit breaker cooldown doldu ({elapsed:.0f}s) — "
                    f"probe denemesi yapılacak"
                )
                return False  # probe denesin
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
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

    # ── property ─────────────────────────────────────────────────────
    @property
    def is_connected(self) -> bool:
        """MT5 bağlantı durumu."""
        return self._connected

    # ── Sembol çözümleme ─────────────────────────────────────────────

    def _resolve_symbols(self) -> None:
        """WATCHED_SYMBOLS'daki base isimleri MT5'teki gerçek ada eşle.

        VİOP kontrat adları vade soneki içerir (ör. F_THYAO0226).
        Her base için visible (aktif/front-month) kontratı bulur.
        Bulunamazsa en kısa soneke sahip olanı seçer.
        """
        try:
            all_symbols = self._safe_call(mt5.symbols_get)
        except (TimeoutError, Exception):
            all_symbols = None
        if not all_symbols:
            logger.warning("MT5 sembol listesi alınamadı, eşleme yapılamıyor")
            return

        self._symbol_map.clear()
        self._reverse_map.clear()

        for base in WATCHED_SYMBOLS:
            # Base ile başlayan tüm MT5 sembollerini bul
            candidates = [
                s for s in all_symbols
                if s.name.upper().startswith(base.upper())
                and len(s.name) > len(base)  # tam eşleşme değil, sonekli
            ]

            if not candidates:
                # Sonek yoksa base'in kendisi olabilir
                exact = [s for s in all_symbols if s.name.upper() == base.upper()]
                if exact:
                    mt5_name = exact[0].name
                    self._symbol_map[base] = mt5_name
                    self._reverse_map[mt5_name] = base
                    logger.info(f"Sembol eşleme: {base} → {mt5_name} (tam eşleşme)")
                else:
                    logger.warning(f"Sembol bulunamadı: {base}")
                continue

            # Visible olanları tercih et (aktif kontrat)
            visible = [s for s in candidates if s.visible]
            chosen = None

            if len(visible) == 1:
                chosen = visible[0]
            elif len(visible) > 1:
                # Birden fazla visible varsa en kısa isimli olanı seç (yakın vade)
                chosen = min(visible, key=lambda s: len(s.name))
            else:
                # Hiçbiri visible değil — en kısa sonekli olanı seç
                chosen = min(candidates, key=lambda s: len(s.name))

            mt5_name = chosen.name
            self._symbol_map[base] = mt5_name
            self._reverse_map[mt5_name] = base
            logger.info(f"Sembol eşleme: {base} → {mt5_name} (visible={chosen.visible})")

        # USDTRY — BABA şok kontrolü için gerekli
        # GCM'de sembol adı farklı olabilir (ör. USDTRY_YAKINVADE)
        usdtry_candidates = [
            s for s in all_symbols
            if "USDTRY" in s.name.upper()
        ]
        if usdtry_candidates:
            usdtry_sym = min(usdtry_candidates, key=lambda s: len(s.name))
            self._symbol_map["USDTRY"] = usdtry_sym.name
            logger.info(f"Sembol eşleme: USDTRY → {usdtry_sym.name}")
        else:
            logger.warning("USDTRY sembolü bulunamadı — şok kontrolü pasif kalacak")

        resolved = len(self._symbol_map)
        total = len(WATCHED_SYMBOLS) + 1  # +1 USDTRY
        logger.info(f"Sembol çözümleme tamamlandı: {resolved}/{total} eşlendi")

    def _to_mt5(self, base_symbol: str) -> str:
        """Base sembol adını MT5 gerçek adına çevir.

        Eşleme yoksa base'in kendisini döndürür (geriye uyumluluk).
        """
        return self._symbol_map.get(base_symbol, base_symbol)

    def _to_base(self, mt5_symbol: str) -> str | None:
        """MT5 sembol adını base'e çevir.

        Eşleme yoksa None döndürür (izlenmeyen sembol).
        """
        return self._reverse_map.get(mt5_symbol)

    def _is_watched(self, mt5_symbol: str) -> bool:
        """MT5 sembolü izlenen kontratlardan biri mi?"""
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
                self._resolve_symbols()

                # Çözümlenen sembollerin görünürlüklerini aç
                for base in WATCHED_SYMBOLS:
                    mt5_name = self._to_mt5(base)
                    try:
                        if not self._safe_call(mt5.symbol_select, mt5_name, True):
                            logger.warning(f"Sembol etkinleştirilemedi: {base} → {mt5_name}")
                    except (TimeoutError, Exception):
                        logger.warning(f"Sembol etkinleştirme timeout: {base} → {mt5_name}")

                # USDTRY — BABA şok kontrolü için gerekli
                usdtry_mt5 = self._to_mt5("USDTRY")
                try:
                    usdtry_ok = self._safe_call(mt5.symbol_select, usdtry_mt5, True)
                except (TimeoutError, Exception):
                    usdtry_ok = False
                if not usdtry_ok:
                    logger.warning(f"USDTRY ({usdtry_mt5}) MarketWatch'a eklenemedi — şok kontrolü pasif kalacak")

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

        with self._order_lock:
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
                    # Health: reddedilen emir kaydı
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
                    return None

                order_result = result._asdict()
                order_result["sl_tp_applied"] = False

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

                    # Pozisyon ticket: emir yanıtında 0 dönebilir (netting/gecikme) — sembole göre bul
                    position_ticket = order_result.get("order", 0)
                    if position_ticket == 0:
                        TICKET_MAX_RETRIES = 20  # Toplam ~4.2s (exponential backoff)
                        for attempt in range(1, TICKET_MAX_RETRIES + 1):
                            _time.sleep(min(0.1 * attempt, 0.5))  # 0.1, 0.2, ..., 0.5s
                            by_symbol = self._safe_call(mt5.positions_get, symbol=mt5_name)
                            if by_symbol and len(by_symbol) > 0:
                                position_ticket = getattr(by_symbol[0], "ticket", 0)
                                if position_ticket:
                                    logger.debug(
                                        f"SL/TP için pozisyon ticket sembolden alındı "
                                        f"(deneme {attempt}): {position_ticket}"
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

                    sltp_request: dict[str, Any] = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": mt5_name,
                        "position": position_ticket,
                        "sl": sl_rounded,
                        "tp": tp_rounded,
                        "type_filling": filling,      # GCM VİOP: RETURN
                        "type_time": mt5.ORDER_TIME_GTC,
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
                        # 5 deneme de başarısız — pozisyonu kapat (korumasız bırakma)
                        logger.error(
                            f"SL/TP {SLTP_MAX_RETRIES} denemede eklenemedi [{symbol}] "
                            f"— pozisyon korumasız, kapatılıyor"
                        )
                        self.close_position(position_ticket)
                        order_result["sl_tp_applied"] = False
                        order_result["force_closed"] = True

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
                logger.error(f"send_order istisnası [{symbol}]: {exc}")
                self._last_order_error = {
                    "reason": f"Beklenmeyen hata: {exc}",
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

        Args:
            ticket: Pozisyon ticket numarası.
            expected_volume: Engine'in yönettiği lot miktarı (opsiyonel).
                Belirtilmezse MT5'teki tüm hacim kapatılır.

        Returns:
            Kapanış sonuç sözlüğü veya None.
        """
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
                "type_filling": mt5.ORDER_FILLING_IOC,
                "comment": "USTAT_CLOSE",
            }

            logger.info(
                f"Pozisyon kapatılıyor: ticket={ticket}, "
                f"{symbol} {lot} lot @ {price:.4f}"
            )

            result = self._safe_call(mt5.order_send, request, timeout=15.0)
            if result is None:
                logger.error(
                    f"Kapanış emri None [{ticket}]: {mt5.last_error()}"
                )
                return None

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(
                    f"Kapanış reddedildi [{ticket}]: retcode={result.retcode}, "
                    f"comment={result.comment}"
                )
                return None

            close_result = result._asdict()
            logger.info(
                f"Pozisyon kapatıldı: ticket={ticket}, "
                f"order={close_result.get('order')}"
            )
            return close_result

        except Exception as exc:
            logger.error(f"close_position istisnası [ticket={ticket}]: {exc}")
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
                "type_filling": mt5.ORDER_FILLING_IOC,
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
        """
        if not self._ensure_connection():
            return None

        try:
            positions = self._safe_call(mt5.positions_get, ticket=ticket)
            if positions is None or len(positions) == 0:
                logger.error(f"Pozisyon bulunamadı (modify): ticket={ticket}")
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
                    # tick_size yoksa VİOP için 5 ondalık (broker reddini önlemek)
                    new_sl = round(new_sl, 5) if new_sl > 0 else 0.0
                    new_tp = round(new_tp, 5) if new_tp > 0 else 0.0
            else:
                # sembol bilgisi alınamadıysa yine de ondalık hassasiyeti düşür
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
                        if pos_type == 0 and current_price - new_sl < min_dist:  # BUY
                            new_sl = round((current_price - min_dist) / t_size) * t_size
                            logger.warning(
                                f"Modify SL stops_level ayarı [{pos.symbol}]: "
                                f"SL={new_sl:.4f} (min mesafe={min_dist:.4f}, fiyat={current_price:.4f})"
                            )
                        elif pos_type == 1 and new_sl - current_price < min_dist:  # SELL
                            new_sl = round((current_price + min_dist) / t_size) * t_size
                            logger.warning(
                                f"Modify SL stops_level ayarı [{pos.symbol}]: "
                                f"SL={new_sl:.4f} (min mesafe={min_dist:.4f}, fiyat={current_price:.4f})"
                            )

                    if new_tp > 0:
                        if pos_type == 0 and new_tp - current_price < min_dist:  # BUY
                            new_tp = round((current_price + min_dist) / t_size) * t_size
                            logger.warning(
                                f"Modify TP stops_level ayarı [{pos.symbol}]: "
                                f"TP={new_tp:.4f} (min mesafe={min_dist:.4f})"
                            )
                        elif pos_type == 1 and current_price - new_tp < min_dist:  # SELL
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

            # TRADE_ACTION_SLTP için position alanı zorunlu (MT5 API gereksinimi).
            # GCM VİOP exchange modunda SLTP istekleri sunucu tarafında bağlı
            # bekleyen emirlere dönüştürülüyor — type_filling ve type_time zorunlu,
            # yoksa 10035 Invalid order dönüyor.
            position_ticket = int(getattr(pos, "ticket", ticket))
            request: dict[str, Any] = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": pos.symbol,
                "position": position_ticket,
                "sl": float(new_sl),    # float zorunlu (int → silent fail)
                "tp": float(new_tp),    # float zorunlu
                "type_filling": mt5.ORDER_FILLING_RETURN,
                "type_time": mt5.ORDER_TIME_GTC,
            }

            logger.info(
                f"Modify SL/TP: ticket={ticket} position={position_ticket} "
                f"pos.symbol={pos.symbol} SL={new_sl:.4f} TP={new_tp:.4f}"
            )

            # order_check kullanmıyoruz — eski MT5 build'larda (4755<5200)
            # SLTP için false-negative dönebiliyor. Doğrudan order_send + retry.
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

                # Hata detayını kaydet
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

                # Son deneme değilse bekle ve tekrar dene
                if attempt < MODIFY_MAX_RETRIES:
                    _time.sleep(0.5)

            # Tüm denemeler başarısız
            logger.error(
                f"Modify {MODIFY_MAX_RETRIES} denemede başarısız [{ticket}]: "
                f"{self._last_modify_error}"
            )
            return None

        except Exception as exc:
            self._last_modify_error = {"exception": str(exc)}
            logger.error(f"modify_position istisnası [ticket={ticket}]: {exc}")
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
            return []

        try:
            positions = self._safe_call(mt5.positions_get)
            if positions is None:
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
                    "time": datetime.fromtimestamp(pos.time).isoformat(),
                })

            logger.debug(f"Açık pozisyon sayısı: {len(result)}")
            return result

        except Exception as exc:
            logger.error(f"get_positions istisnası: {exc}")
            return []

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
                result.append({
                    "ticket": order.ticket,
                    "symbol": base,  # base isim döndür
                    "type": (
                        "BUY_LIMIT"
                        if order.type == mt5.ORDER_TYPE_BUY_LIMIT
                        else "SELL_LIMIT"
                    ),
                    "volume": order.volume_initial,
                    "volume_current": order.volume_current,
                    "price_open": order.price_open,
                    "sl": order.sl,
                    "tp": order.tp,
                    "time_setup": datetime.fromtimestamp(
                        order.time_setup
                    ).isoformat(),
                })

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
