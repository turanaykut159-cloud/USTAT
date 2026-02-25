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
        all_symbols = mt5.symbols_get()
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

        resolved = len(self._symbol_map)
        total = len(WATCHED_SYMBOLS)
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

                if not mt5.initialize(**kwargs):
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
                    if not mt5.symbol_select(mt5_name, True):
                        logger.warning(f"Sembol etkinleştirilemedi: {base} → {mt5_name}")

                self._connected = True
                self._last_heartbeat = _time.monotonic()
                info = mt5.account_info()
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
            mt5.shutdown()
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

        try:
            info = mt5.terminal_info()
            if info is None:
                logger.warning("Heartbeat başarısız — terminal_info None döndü.")
                self._connected = False
                return self._ensure_connection()

            if not info.connected:
                logger.warning("Heartbeat: terminal bağlantı yok.")
                self._connected = False
                return self._ensure_connection()

            logger.debug("Heartbeat OK.")
            return True

        except Exception as exc:
            logger.error(f"Heartbeat istisnası: {exc}")
            self._connected = False
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
            info = mt5.account_info()
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
            info = mt5.symbol_info(mt5_name)
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
            rates = mt5.copy_rates_from_pos(mt5_name, timeframe, 0, count)
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
            tick = mt5.symbol_info_tick(mt5_name)
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
            sym_info = mt5.symbol_info(mt5_name)
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

            # Filling mode: sembolün desteklediğini kullan
            # VİOP genelde RETURN destekler
            if sym_info.filling_mode & mt5.SYMBOL_FILLING_FOK:
                filling = mt5.ORDER_FILLING_FOK
            elif sym_info.filling_mode & mt5.SYMBOL_FILLING_IOC:
                filling = mt5.ORDER_FILLING_IOC
            else:
                filling = mt5.ORDER_FILLING_RETURN

            # Market ise güncel fiyatı al
            if order_type == "market":
                tick = mt5.symbol_info_tick(mt5_name)
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

            result = mt5.order_send(request)
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

                # Pozisyon ticket'ını bul
                position_ticket = order_result.get("order", 0)

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

                sltp_result = mt5.order_send(sltp_request)
                if sltp_result is not None and sltp_result.retcode == mt5.TRADE_RETCODE_DONE:
                    order_result["sl_tp_applied"] = True
                    logger.info(
                        f"SL/TP başarılı [{symbol}]: "
                        f"SL={sl_rounded:.4f} TP={tp_rounded:.4f}"
                    )
                else:
                    sltp_err = (
                        sltp_result.comment
                        if sltp_result else str(mt5.last_error())
                    )
                    logger.warning(
                        f"SL/TP eklenemedi [{symbol}]: {sltp_err} "
                        f"— pozisyon SL/TP'siz açık kalacak"
                    )

            return order_result

        except Exception as exc:
            logger.error(f"send_order istisnası [{symbol}]: {exc}")
            self._last_order_error = {
                "reason": f"Beklenmeyen hata: {exc}",
            }
            return None

    # ── close_position ───────────────────────────────────────────────
    def close_position(self, ticket: int) -> dict[str, Any] | None:
        """Açık pozisyonu kapat.

        Pozisyon bilgisini ticket ile bulur, ters yönde
        aynı hacimde market emri göndererek kapatır.

        Args:
            ticket: Pozisyon ticket numarası.

        Returns:
            Kapanış sonuç sözlüğü veya None.
        """
        if not self._ensure_connection():
            return None

        try:
            positions = mt5.positions_get(ticket=ticket)
            if positions is None or len(positions) == 0:
                logger.error(f"Pozisyon bulunamadı: ticket={ticket}")
                return None

            pos = positions[0]
            symbol = pos.symbol
            lot = pos.volume

            # Ters yön
            if pos.type == mt5.ORDER_TYPE_BUY:
                close_type = mt5.ORDER_TYPE_SELL
                tick = mt5.symbol_info_tick(symbol)
                price = tick.bid if tick else 0.0
            else:
                close_type = mt5.ORDER_TYPE_BUY
                tick = mt5.symbol_info_tick(symbol)
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

            result = mt5.order_send(request)
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
            positions = mt5.positions_get(ticket=ticket)
            if positions is None or len(positions) == 0:
                logger.error(f"Pozisyon bulunamadı (modify): ticket={ticket}")
                return None

            pos = positions[0]
            new_sl = sl if sl is not None else pos.sl
            new_tp = tp if tp is not None else pos.tp

            request: dict[str, Any] = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": pos.symbol,
                "position": ticket,
                "sl": new_sl,
                "tp": new_tp,
            }

            logger.debug(
                f"Pozisyon değiştiriliyor: ticket={ticket}, "
                f"SL={new_sl:.4f}, TP={new_tp:.4f}"
            )

            result = mt5.order_send(request)
            if result is None:
                logger.error(
                    f"Modify emri None [{ticket}]: {mt5.last_error()}"
                )
                return None

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(
                    f"Modify reddedildi [{ticket}]: retcode={result.retcode}, "
                    f"comment={result.comment}"
                )
                return None

            mod_result = result._asdict()
            logger.debug(
                f"Pozisyon değiştirildi: ticket={ticket}, "
                f"SL={new_sl:.4f}, TP={new_tp:.4f}"
            )
            return mod_result

        except Exception as exc:
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
            positions = mt5.positions_get()
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
            deals = mt5.history_deals_get(date_from, date_to)
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
            deals = mt5.history_deals_get(date_from, date_to)
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

            result = mt5.order_send(request)
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
                orders = mt5.orders_get(symbol=mt5_name)
            else:
                orders = mt5.orders_get()

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
            pending = mt5.orders_get(ticket=order_ticket)
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
            history = mt5.history_orders_get(ticket=order_ticket)
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
            deals = mt5.history_deals_get(order=order_ticket)
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
