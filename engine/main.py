"""ÜSTAT Trading Engine — Ana döngü (v13.0).

Her 10 saniyede çalışan ana döngü:
    1. MT5 heartbeat / reconnect
    2. Veri güncelleme: 15 kontratın fiyat, hacim, spread
    2.5. Pozisyon kapanma tespiti: ticket set diff → kapanma varsa history sync
    3. BABA açık pozisyon denetimi: fake analiz, risk limitleri, erken uyarı
    4. BABA risk kontrolü: günlük/haftalık/aylık zarar, floating, korelasyon
    5. Top 5 kontrat seçimi (OĞUL — v13.0'da ÜSTAT'tan taşındı)
    6. OĞUL sinyal: risk müsaitse + günlük limit dolmadıysa + Top 5 için sinyal ara
    6.5. H-Engine hibrit pozisyon yönetimi
    7. ÜSTAT brain: raporlama + strateji havuzu
    8. Loglama: tüm kararlar SQLite'a

BABA HER ZAMAN ÖNCE ÇALIŞIR — sıralama değiştirilemez.

Fail-safe:
    - Ekonomik takvim erişilemezse → OLAY rejimi
    - MT5 bağlantısı koparsa → 5x reconnect, başarısız → sistem durdur
    - Veri anomalisi → o kontrat deaktif (DataPipeline tarafından)
    - Disk/DB hatası → arşivle, başarısız → sistem durdur
"""

from __future__ import annotations

import signal
import sys
import time as _time
import traceback
from datetime import datetime

from engine.baba import Baba, validate_expiry_dates
from engine.config import Config
from engine.data_pipeline import DataPipeline
from engine.database import Database
from engine.logger import get_logger
from engine.models.regime import RegimeType
from engine.models.risk import RiskParams
from engine.mt5_bridge import MT5Bridge
from engine.h_engine import HEngine
from engine.health import HealthCollector, CycleTimings
from engine.ogul import Ogul
from engine.ustat import Ustat

logger = get_logger(__name__)

# ═════════════════════════════════════════════════════════════════════
#  SABİTLER
# ═════════════════════════════════════════════════════════════════════

CYCLE_INTERVAL: int = 10          # ana döngü aralığı (saniye)
# MT5 kopma: heartbeat'ta tek reconnect (launch=False); çoklu deneme MT5Bridge içinde
MAX_MT5_RECONNECT: int = 5        # Dokümantasyon / ileride kullanım için (heartbeat'ta kullanılmıyor)
DB_ERROR_THRESHOLD: int = 3       # art arda DB hatası → sistem durdur
SHUTDOWN_TIMEOUT: int = 30        # graceful shutdown bekleme (saniye)
CLOSURE_SYNC_LOOKBACK_DAYS: int = 3  # kapanma sync lookback (gün)
CLOSURE_RETRY_INTERVAL: int = 6   # pending ticket retry aralığı (cycle = 60sn)


# ═════════════════════════════════════════════════════════════════════
#  ENGINE
# ═════════════════════════════════════════════════════════════════════

class Engine:
    """Ana trading motoru — 10 saniyelik cycle ile çalışır.

    Bileşenler:
        Config       → JSON konfigürasyon
        Database     → SQLite (thread-safe)
        MT5Bridge    → MetaTrader 5 bağlantısı
        DataPipeline → Veri çekme, temizleme, depolama
        Ustat        → Strateji yönetimi, raporlama (brain)
        Baba         → Risk yönetimi, rejim algılama
        Ogul         → Sinyal üretimi, Top 5 seçimi, emir state-machine
    """

    def __init__(
        self,
        config: Config | None = None,
        db: Database | None = None,
        mt5: MT5Bridge | None = None,
        pipeline: DataPipeline | None = None,
        ustat: Ustat | None = None,
        baba: Baba | None = None,
        ogul: Ogul | None = None,
    ) -> None:
        self.config = config or Config()
        self.db = db or Database(self.config)
        self.mt5 = mt5 or MT5Bridge(self.config)
        self.pipeline = pipeline or DataPipeline(self.mt5, self.db, self.config)
        self.ustat = ustat or Ustat(self.config, self.db)
        self.baba = baba or Baba(self.config, self.db, mt5=self.mt5)
        self.risk_params = RiskParams()
        self.ogul = ogul or Ogul(
            self.config, self.mt5, self.db,
            baba=self.baba, risk_params=self.risk_params,
        )

        # H-Engine (Hibrit İşlem Motoru)
        self.h_engine = HEngine(
            config=self.config,
            mt5=self.mt5,
            db=self.db,
            baba=self.baba,
            pipeline=self.pipeline,
        )
        # OĞUL'a h_engine referansı ver (netting koruması)
        self.ogul.h_engine = self.h_engine

        # ManuelMotor (Bağımsız Manuel İşlem Motoru — v14.0)
        from engine.manuel_motor import ManuelMotor
        self.manuel_motor = ManuelMotor(
            config=self.config,
            mt5=self.mt5,
            db=self.db,
            baba=self.baba,
            risk_params=self.risk_params,
        )
        # Cross-motor referansları
        self.manuel_motor.ogul = self.ogul
        self.manuel_motor.h_engine = self.h_engine
        self.ogul.manuel_motor = self.manuel_motor

        # ── Sistem Sağlığı ─────────────────────────────────────────
        self.health = HealthCollector()
        self.mt5._health = self.health

        # ── Durum ───────────────────────────────────────────────────
        self._running: bool = False
        self._cycle_count: int = 0
        self._consecutive_db_errors: int = 0
        self._shutdown_requested: bool = False
        self._prev_mt5_tickets: set[int] = set()  # pozisyon kapanma tespiti için
        self._pending_closure_tickets: set[int] = set()  # VİOP uzlaşma bekleyen kapanmalar

    # ═════════════════════════════════════════════════════════════════
    #  BAŞLATMA / DURDURMA
    # ═════════════════════════════════════════════════════════════════

    def start(self) -> None:
        """Engine'i başlat — MT5 bağlantısı + durum geri yükleme + ana döngü."""
        logger.info("=" * 60)
        logger.info("ÜSTAT Trading Engine başlatılıyor...")
        logger.info("=" * 60)

        # 0. Config durumu kontrolü (Madde 2.6)
        if not self.config.is_loaded:
            logger.critical("Config dosyası yüklenemedi — varsayılan değerlerle devam ediliyor!")
            self._log_event(
                "CONFIG_MISSING",
                f"Config dosyası bulunamadı veya parse edilemedi: {self.config._path}",
                "CRITICAL",
            )

        # 0.5. VİOP vade tarihleri doğrulama (Madde 2.7)
        expiry_issues = validate_expiry_dates()
        if expiry_issues:
            for issue in expiry_issues:
                logger.warning(f"VİOP vade tarihi sorunu: {issue}")
            self._log_event(
                "EXPIRY_DATE_WARNING",
                f"{len(expiry_issues)} vade tarihi sorunu: {'; '.join(expiry_issues)}",
                "WARNING",
            )
        else:
            logger.info("VİOP vade tarihleri doğrulandı — tümü iş günü.")

        # 1. MT5 bağlantısı
        if not self._connect_mt5():
            logger.critical("MT5 bağlantısı kurulamadı — engine başlatılamıyor.")
            self._log_event("ENGINE_START_FAIL", "MT5 bağlantısı kurulamadı", "CRITICAL")
            return
        self.health.record_connection_established()

        # 1.5. MT5 işlem geçmişi senkronizasyonu (tek seferlik)
        self._sync_mt5_history()

        # 2. Durum geri yükleme
        self._restore_state()

        # 3. Başlangıç event
        self._log_event("ENGINE_START", "ÜSTAT Engine başlatıldı", "INFO")
        logger.info("Engine hazır — ana döngü başlıyor.")

        # 4. Ana döngü
        self._running = True
        self._main_loop()

    def stop(self, reason: str = "kullanıcı isteği") -> None:
        """Engine'i durdur — graceful shutdown.

        Args:
            reason: Durdurma nedeni (log için).
        """
        if not self._running:
            return

        logger.info(f"Engine durduruluyor: {reason}")
        self._running = False
        self._shutdown_requested = True

        # Açık pozisyonlar hakkında uyarı
        active = len(self.ogul.active_trades)
        if active > 0:
            logger.warning(
                f"DİKKAT: {active} aktif işlem var — "
                f"pozisyonlar MT5'te açık kalacak!"
            )

        hybrid_count = len(self.h_engine.hybrid_positions)
        if hybrid_count > 0:
            logger.warning(
                f"DİKKAT: {hybrid_count} hibrit pozisyon var — "
                f"pozisyonlar MT5'te açık kalacak!"
            )

        # MT5 bağlantısını kapat
        try:
            self.mt5.disconnect()
        except Exception as exc:
            logger.error(f"MT5 disconnect hatası: {exc}")

        # DB'yi kapat
        try:
            self.db.close()
        except Exception as exc:
            logger.error(f"DB close hatası: {exc}")

        self._log_event_safe("ENGINE_STOP", f"Engine durduruldu: {reason}", "INFO")
        logger.info("ÜSTAT Engine durduruldu.")

    # ═════════════════════════════════════════════════════════════════
    #  ANA DÖNGÜ
    # ═════════════════════════════════════════════════════════════════

    def _main_loop(self) -> None:
        """10 saniyelik ana döngü.

        Sıralama (DEĞİŞTİRİLEMEZ):
            1. MT5 heartbeat
            2. Veri güncelleme (DataPipeline)
            2.5. Pozisyon kapanma tespiti (ticket set diff → history sync + pending retry)
            3. BABA cycle (rejim + erken uyarı + fake + period reset + kill-switch)
            4. BABA risk kontrolü
            5. Top 5 seçimi (OĞUL — v13.0)
            6. OĞUL sinyal üretimi + emir yönetimi
            6.5. H-Engine hibrit pozisyon yönetimi
            7. ÜSTAT brain (raporlama + strateji havuzu)
            8. Cycle loglama
        """
        while self._running:
            cycle_start = _time.monotonic()
            self._cycle_count += 1

            try:
                self._run_single_cycle()
                # DB hata sayacını sıfırla (başarılı cycle)
                self._consecutive_db_errors = 0

            except _SystemStopError as exc:
                logger.critical(f"SİSTEM DURDURMA: {exc}")
                self._log_event_safe(
                    "SYSTEM_STOP", str(exc), "CRITICAL",
                    action="system_halt",
                )
                self.stop(reason=str(exc))
                return

            except _DBError as exc:
                self._consecutive_db_errors += 1
                logger.error(
                    f"DB hatası ({self._consecutive_db_errors}/"
                    f"{DB_ERROR_THRESHOLD}): {exc}"
                )
                if self._consecutive_db_errors >= DB_ERROR_THRESHOLD:
                    logger.critical(
                        f"Art arda {DB_ERROR_THRESHOLD} DB hatası — sistem durduruluyor."
                    )
                    self._log_event_safe(
                        "SYSTEM_STOP",
                        f"Art arda {DB_ERROR_THRESHOLD} DB hatası",
                        "CRITICAL",
                        action="system_halt",
                    )
                    self.stop(reason="DB hatası eşiği aşıldı")
                    return

            except Exception as exc:
                logger.error(
                    f"Cycle #{self._cycle_count} beklenmeyen hata: {exc}\n"
                    f"{traceback.format_exc()}"
                )
                self._log_event_safe(
                    "CYCLE_ERROR",
                    f"Cycle #{self._cycle_count}: {exc}",
                    "ERROR",
                )

            # Cycle süresini hesapla, kalan süreyi bekle
            elapsed = _time.monotonic() - cycle_start
            sleep_time = max(0, CYCLE_INTERVAL - elapsed)

            if elapsed > CYCLE_INTERVAL:
                logger.warning(
                    f"Cycle #{self._cycle_count} uzun sürdü: "
                    f"{elapsed:.1f}s (hedef: {CYCLE_INTERVAL}s)"
                )

            if sleep_time > 0 and self._running:
                _time.sleep(sleep_time)

    # ═════════════════════════════════════════════════════════════════
    #  TEK CYCLE
    # ═════════════════════════════════════════════════════════════════

    def _run_single_cycle(self) -> None:
        """Tek bir 10 saniyelik cycle'ı çalıştır.

        Raises:
            _SystemStopError: MT5 bağlantısı 5 denemede kurulamadı.
            _DBError: Veritabanı yazma/okuma hatası.
        """
        _pc = _time.perf_counter
        t0 = _pc()

        # ── 1. MT5 Heartbeat ──────────────────────────────────────
        if not self._heartbeat_mt5():
            raise _SystemStopError(
                "MT5 bağlantısı kurtarılamadı — sistem durduruluyor"
            )
        t1 = _pc()

        # ── 2. Veri Güncelleme ────────────────────────────────────
        self._update_data()
        t2 = _pc()

        # ── 2.5 Pozisyon Kapanma Tespiti ─────────────────────────
        self._check_position_closures()
        t3 = _pc()

        # ── 3. BABA Cycle (HER ZAMAN ÖNCE!) ──────────────────────
        regime = self._run_baba_cycle()
        t4 = _pc()

        # ── 4. BABA Risk Kontrolü ─────────────────────────────────
        risk_verdict = self.baba.check_risk_limits(self.risk_params)

        # Risk durumunu logla
        if not risk_verdict.can_trade:
            logger.warning(
                f"İşlem engeli: {risk_verdict.reason} "
                f"(KS={risk_verdict.kill_switch_level})"
            )
        t5 = _pc()

        # ── 5. Top 5 Kontrat Seçimi (v13.0: OĞUL sorumlu) ────────
        top5 = self.ogul.select_top5(regime)
        t6 = _pc()

        # ── 6. OĞUL — Sinyal Üretimi + Emir Yönetimi ─────────────
        # process_signals() içinde:
        #   - EOD check (17:45 kapanış)
        #   - advance_orders (state-machine ilerletme)
        #   - manage_active_trades (trailing stop)
        #   - sync_positions (MT5 senkronizasyon)
        #   - Rejim kontrolü
        #   - Trading hours kontrolü
        #   - Sinyal üretimi (sadece risk OK ise)
        #
        # risk_verdict.can_trade=False olsa bile process_signals()
        # çağrılır çünkü advance_orders ve manage_active_trades
        # her zaman çalışmalı. Sinyal üretimi process_signals()
        # içindeki rejim + saat kontrollerinde durur.
        # process_signals her zaman çağrılır (emir yönetimi + trailing stop).
        # risk kapalıyken top5 yerine boş liste → sinyal üretilmez.
        # Ama bias her zaman güncellenmeli (Dashboard doğru göstersin).
        try:
            if risk_verdict.can_trade:
                self.ogul.process_signals(top5, regime)
            else:
                self.ogul.process_signals([], regime)
                # Risk kapalıyken de bias güncelle (Dashboard için)
                for sym in top5:
                    self.ogul.last_signals[sym] = self.ogul._calculate_bias(sym)
        except Exception as exc:
            logger.error(f"OĞUL process_signals hatası: {exc}")
            self._log_event_safe(
                "OGUL_ERROR", f"OĞUL sinyal/emir hatası: {exc}", "ERROR",
            )
        t7 = _pc()

        # ── 6.5. H-Engine — Hibrit Pozisyon Yönetimi ─────────────
        try:
            self.h_engine.run_cycle()
        except Exception as exc:
            logger.error(f"H-Engine cycle hatası: {exc}")
            self._log_event_safe(
                "H_ENGINE_ERROR", f"H-Engine cycle hatası: {exc}", "ERROR",
            )
        t8 = _pc()

        # ── 6.7. ManuelMotor — Pozisyon Senkronizasyonu ─────────
        try:
            self.manuel_motor.sync_positions()
        except Exception as exc:
            logger.error(f"ManuelMotor sync hatası: {exc}")
            self._log_event_safe(
                "MANUEL_MOTOR_ERROR",
                f"ManuelMotor sync hatası: {exc}",
                "ERROR",
            )
        t8b = _pc()

        # ── 7. ÜSTAT Brain — Raporlama + Strateji Havuzu ─────────
        try:
            self.ustat.run_cycle(self.baba, self.ogul)
        except Exception as exc:
            logger.error(f"ÜSTAT brain cycle hatası: {exc}")
        t9 = _pc()

        # ── 8. Cycle Loglama ──────────────────────────────────────
        self._log_cycle_summary(regime, risk_verdict, top5)
        t10 = _pc()

        # ── Health: cycle zamanlama kaydı ─────────────────────────
        total_ms = (t10 - t0) * 1000
        self.health.record_cycle(CycleTimings(
            cycle_number=self._cycle_count,
            timestamp=_time.time(),
            total_ms=total_ms,
            heartbeat_ms=(t1 - t0) * 1000,
            data_update_ms=(t2 - t1) * 1000,
            closure_check_ms=(t3 - t2) * 1000,
            baba_cycle_ms=(t4 - t3) * 1000,
            risk_check_ms=(t5 - t4) * 1000,
            top5_ms=(t6 - t5) * 1000,
            ogul_signals_ms=(t7 - t6) * 1000,
            h_engine_ms=(t8 - t7) * 1000,
            manuel_sync_ms=(t8b - t8) * 1000,
            ustat_brain_ms=(t9 - t8b) * 1000,
            log_summary_ms=(t10 - t9) * 1000,
            overrun=total_ms > (CYCLE_INTERVAL * 1000),
        ))

    # ═════════════════════════════════════════════════════════════════
    #  MT5 GEÇMİŞ SENKRONİZASYONU
    # ═════════════════════════════════════════════════════════════════

    def _sync_mt5_history(self) -> None:
        """MT5 işlem geçmişini DB ile senkronize et (tek seferlik).

        Engine startup'ta çağrılır. Başarısız olursa warning log yazar,
        engine çalışmaya devam eder (kritik değil).
        """
        try:
            trades = self.mt5.get_history_for_sync(days=90)
            added = self.db.sync_mt5_trades(trades)
            if added:
                logger.info(f"MT5 geçmiş sync: {added} trade eklendi")
            else:
                logger.info("MT5 geçmiş sync: yeni trade yok")
        except Exception as exc:
            logger.warning(f"MT5 geçmiş sync hatası (kritik değil): {exc}")

    def _check_position_closures(self) -> None:
        """Pozisyon kapanma tespiti — ticket set diff ile.

        Her cycle'da pipeline.latest_positions'dan güncel ticket set'ini alır.
        Önceki set'te olup şimdiki set'te olmayan ticket'lar → kapanmış pozisyon.
        Kapanma tespit edilirse MT5 işlem geçmişi DB'ye sync edilir.

        VİOP günlük uzlaşma gecikmesi:
            Pozisyon kapanır ama OUT deal'leri 21:35 uzlaşmasına kadar
            yazılmayabilir. Bu durumda ticket _pending_closure_tickets'a
            eklenir ve CLOSURE_RETRY_INTERVAL (60sn) aralıklarla tekrar
            denenir. OUT deal'ler yazıldığında otomatik çözülür.

        İlk cycle'da (prev boş) sadece set güncellenir, sync tetiklenmez.
        Startup'ta zaten 90 günlük tam sync yapılır.
        """
        # Güncel ticket set'ini oluştur
        current_tickets: set[int] = set()
        for pos in self.pipeline.latest_positions:
            ticket = pos.get("ticket")
            if ticket is not None:
                current_tickets.add(ticket)

        # İlk cycle: sadece set'i başlat, sync yok
        # (Startup'ta 90 günlük tam sync zaten yapıldı)
        if not self._prev_mt5_tickets:
            self._prev_mt5_tickets = current_tickets
            return

        # Kapanan ticket'ları bul: önceki - şimdiki = kapananlar
        closed_tickets = self._prev_mt5_tickets - current_tickets

        # Her durumda set'i güncelle (yeni pozisyonlar da yakalanır)
        self._prev_mt5_tickets = current_tickets

        # Yeni kapanma tespit edildiyse pending'e ekle ve hemen sync dene
        if closed_tickets:
            logger.info(
                f"Pozisyon kapanması tespit edildi: {len(closed_tickets)} ticket "
                f"({closed_tickets})"
            )
            self._pending_closure_tickets.update(closed_tickets)
            self._sync_closed_positions()
            return

        # Yeni kapanma yok ama pending ticket varsa — aralıklı retry
        if self._pending_closure_tickets and self._cycle_count % CLOSURE_RETRY_INTERVAL == 0:
            logger.debug(
                f"Pending kapanma retry: {len(self._pending_closure_tickets)} ticket "
                f"({self._pending_closure_tickets})"
            )
            self._sync_closed_positions()

    def _sync_closed_positions(self) -> None:
        """Kapanan pozisyonların işlem geçmişini DB'ye sync et.

        _pending_closure_tickets'taki ticket'lar için MT5 deal geçmişini
        çeker ve DB'ye yazar. Tamamlanmış trade kaydı bulunan ticket'lar
        (hem IN hem OUT deal'i olan) pending'den çıkar.

        VİOP günlük uzlaşma gecikmesi:
            OUT deal'leri 21:35 uzlaşmasına kadar yazılmayabilir.
            Bu durumda ticket pending'de kalır ve sonraki retry'larda
            tekrar denenir. OUT deal'ler yazıldığında mt5_position_id
            eşleşmesi ile otomatik çözülür.
        """
        try:
            trades = self.mt5.get_history_for_sync(days=CLOSURE_SYNC_LOOKBACK_DAYS)
            added = self.db.sync_mt5_trades(trades)

            # Sync edilen trade'lerin position_id'lerini topla
            synced_position_ids: set[int] = {
                t["mt5_position_id"] for t in trades if "mt5_position_id" in t
            }

            # Pending'den çözülen ticket'ları çıkar
            resolved = self._pending_closure_tickets & synced_position_ids
            if resolved:
                self._pending_closure_tickets -= resolved
                logger.info(
                    f"Kapanma sync: {len(resolved)} ticket çözüldü ({resolved}), "
                    f"DB'ye {added} yeni trade"
                )

            # Hâlâ çözülemeyenler: OUT deal bekleniyor (VİOP 21:35 uzlaşması)
            if self._pending_closure_tickets:
                logger.debug(
                    f"Bekleyen kapanma ticket'ları (OUT deal bekleniyor): "
                    f"{self._pending_closure_tickets}"
                )
        except Exception as exc:
            logger.warning(f"Kapanma-tetiklemeli sync hatası: {exc}")

    def sync_mt5_history_recent(self, days: int = 3) -> int:
        """Son N günlük MT5 işlem geçmişini DB ile senkronize et.

        API'den (get_trades, pozisyon kapatma vb.) veya ana döngüden
        periyodik olarak çağrılır. Değişim olduğunda anlık güncel veri için kullanılır.

        Args:
            days: Kaç günlük geçmiş çekilecek (1–90).

        Returns:
            DB'ye eklenen/güncellenen trade sayısı. Hata durumunda 0.
        """
        if not getattr(self.mt5, "_connected", False):
            return 0
        days = max(1, min(90, days))
        try:
            trades = self.mt5.get_history_for_sync(days=days)
            added = self.db.sync_mt5_trades(trades)
            return added
        except Exception as exc:
            logger.warning(f"MT5 geçmiş sync (son {days} gün) hatası: {exc}")
            return 0

    # ═════════════════════════════════════════════════════════════════
    #  ADIM 1: MT5 HEARTBEAT / RECONNECT
    # ═════════════════════════════════════════════════════════════════

    def _connect_mt5(self) -> bool:
        """İlk MT5 bağlantısı — launch=True ile MT5'i açabilir.

        Returns:
            Bağlantı başarılıysa True.
        """
        return self.mt5.connect(launch=True)

    def _heartbeat_mt5(self) -> bool:
        """MT5 bağlantı kontrolü — kopmuşsa bir kez reconnect dener.

        Heartbeat başarısızsa yalnızca bir kez connect(launch=False) çağrılır.
        Çoklu reconnect denemesi MT5Bridge içinde yapılır; burada tek deneme.
        MT5 kapalıysa açmaz, sadece çalışan MT5'e bağlanmaya çalışır.

        Returns:
            Bağlantı sağlıklıysa True.

        Raises:
            _SystemStopError: Denemeler başarısız olursa.
        """
        if self.mt5.heartbeat():
            return True

        # Heartbeat başarısız — son kez reconnect dene (MT5 açmaz!)
        logger.warning("MT5 heartbeat başarısız — reconnect deneniyor (launch=False)...")
        if self.mt5.connect(launch=False):
            logger.info("MT5 reconnect başarılı.")
            self._log_event_safe(
                "MT5_RECONNECT", "MT5 bağlantısı yeniden kuruldu", "WARNING"
            )
            return True

        # Denemeler başarısız — MT5 kapalı veya erişilemez
        return False

    # ═════════════════════════════════════════════════════════════════
    #  ADIM 2: VERİ GÜNCELLEME
    # ═════════════════════════════════════════════════════════════════

    def _update_data(self) -> None:
        """DataPipeline cycle'ı — 15 kontrat veri çekme/temizleme.

        DataPipeline.run_cycle():
            1. fetch_all_ticks()    — tick/spread
            2. fetch_all_symbols()  — OHLCV (M1/M5/M15/H1)
            3. update_risk_snapshot() — equity/floating/drawdown

        Veri anomalisi (3+ ardışık eksik bar) → pipeline kontratı
        otomatik deaktif eder.
        """
        try:
            self.pipeline.run_cycle()
        except Exception as exc:
            # Veri hatası engine'i durdurmamalı
            logger.error(f"DataPipeline hatası: {exc}")
            self._log_event_safe(
                "DATA_ERROR",
                f"DataPipeline cycle hatası: {exc}",
                "ERROR",
            )

    # ═════════════════════════════════════════════════════════════════
    #  ADIM 3: BABA CYCLE
    # ═════════════════════════════════════════════════════════════════

    def _run_baba_cycle(self):
        """BABA ana cycle'ı — rejim + erken uyarı + fake + reset + kill-switch.

        Ekonomik takvim erişilemezse OLAY rejimi uygulanır
        (Baba.detect_regime() içinde halledilir).

        Returns:
            Algılanan Regime nesnesi.
        """
        try:
            regime = self.baba.run_cycle(self.pipeline)
        except Exception as exc:
            # BABA hatası → güvenli mod: OLAY rejimi
            logger.error(f"BABA cycle hatası: {exc} — OLAY rejimine geçiliyor")
            self._log_event_safe(
                "BABA_ERROR",
                f"BABA cycle hatası: {exc} — OLAY fallback",
                "ERROR",
            )
            from engine.models.regime import Regime
            regime = Regime(
                regime_type=RegimeType.OLAY,
                confidence=1.0,
                details={"reason": f"BABA hatası: {exc}"},
            )

        # Erken uyarı logla
        if self.baba.active_warnings:
            for w in self.baba.active_warnings:
                logger.warning(f"Erken uyarı: {w.warning_type} — {w.message}")

        return regime

    # ═════════════════════════════════════════════════════════════════
    #  LOGLAMA
    # ═════════════════════════════════════════════════════════════════

    def _log_cycle_summary(self, regime, risk_verdict, top5: list[str]) -> None:
        """Cycle özeti logla (her 6 cycle'da = ~1 dk).

        Args:
            regime: Mevcut rejim.
            risk_verdict: Risk kontrol sonucu.
            top5: Seçili kontratlar.
        """
        # Her cycle debug log
        active_count = len(self.ogul.active_trades)
        deactivated = self.pipeline.get_deactivated_symbols()

        logger.debug(
            f"Cycle #{self._cycle_count}: "
            f"rejim={regime.regime_type.value}, "
            f"risk_ok={risk_verdict.can_trade}, "
            f"top5={top5}, "
            f"aktif_islem={active_count}, "
            f"deaktif={len(deactivated)}"
        )

        # Her 6 cycle'da (~1 dk) info-level özet
        if self._cycle_count % 6 == 0:
            logger.info(
                f"[Özet #{self._cycle_count}] "
                f"Rejim: {regime.regime_type.value} | "
                f"Risk: {'OK' if risk_verdict.can_trade else 'ENGEL'} | "
                f"Top5: {top5} | "
                f"Aktif: {active_count} | "
                f"Deaktif: {deactivated}"
            )

    def _log_event(
        self,
        event_type: str,
        message: str,
        severity: str,
        action: str | None = None,
    ) -> None:
        """Event'i DB'ye yaz.

        Raises:
            _DBError: Veritabanı yazma hatası.
        """
        try:
            self.db.insert_event(
                event_type=event_type,
                message=message,
                severity=severity,
                action=action,
            )
        except Exception as exc:
            raise _DBError(f"Event yazma hatası: {exc}") from exc

    def _log_event_safe(
        self,
        event_type: str,
        message: str,
        severity: str,
        action: str | None = None,
    ) -> None:
        """Event'i DB'ye yaz — hata yutulur (shutdown sırasında güvenli)."""
        try:
            self.db.insert_event(
                event_type=event_type,
                message=message,
                severity=severity,
                action=action,
            )
        except Exception:
            pass  # shutdown sırasında DB kapalı olabilir

    # ═════════════════════════════════════════════════════════════════
    #  DURUM GERİ YÜKLEME
    # ═════════════════════════════════════════════════════════════════

    def _restore_state(self) -> None:
        """Engine restart: durumu geri yükle.

        1. BABA risk state → kill-switch, cooldown, kayıp sayaçları
        2. OĞUL active trades → açık pozisyonları MT5'ten oku
        """
        try:
            self.baba.restore_risk_state()
            logger.info("BABA risk durumu geri yüklendi.")
        except Exception as exc:
            logger.error(f"BABA restore hatası: {exc}")

        try:
            self.ogul.restore_active_trades()
            active = len(self.ogul.active_trades)
            logger.info(f"OĞUL aktif işlemler geri yüklendi: {active} adet")
        except Exception as exc:
            logger.error(f"OĞUL restore hatası: {exc}")

        try:
            self.h_engine.restore_positions()
            hybrid_count = len(self.h_engine.hybrid_positions)
            logger.info(f"H-Engine hibrit pozisyonlar geri yüklendi: {hybrid_count} adet")
        except Exception as exc:
            logger.error(f"H-Engine restore hatası: {exc}")

        try:
            self.manuel_motor.restore_active_trades()
            manual_count = len(self.manuel_motor.active_trades)
            logger.info(f"ManuelMotor aktif işlemler geri yüklendi: {manual_count} adet")
        except Exception as exc:
            logger.error(f"ManuelMotor restore hatası: {exc}")


# ═════════════════════════════════════════════════════════════════════
#  ÖZEL HATALAR
# ═════════════════════════════════════════════════════════════════════

class _SystemStopError(Exception):
    """Engine'i durduran kritik hata."""


class _DBError(Exception):
    """Veritabanı hatası — art arda sayılır."""


# ═════════════════════════════════════════════════════════════════════
#  GİRİŞ NOKTASI
# ═════════════════════════════════════════════════════════════════════

def run() -> None:
    """ÜSTAT Engine'i başlat.

    SIGINT/SIGTERM ile graceful shutdown.
    """
    engine = Engine()

    def _signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Sinyal alındı: {sig_name}")
        engine.stop(reason=f"sinyal: {sig_name}")

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        engine.start()
    except KeyboardInterrupt:
        engine.stop(reason="KeyboardInterrupt")
    except Exception as exc:
        logger.critical(f"Engine kritik hata: {exc}\n{traceback.format_exc()}")
        engine.stop(reason=f"kritik hata: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    run()
