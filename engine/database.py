"""SQLite veritabanı yönetimi.

Thread-safe (check_same_thread=False + threading.Lock) veritabanı katmanı.
İlk çalıştırmada tüm tablolar otomatik oluşturulur.

Tablolar:
    bars               – OHLCV bar verileri
    trades             – İşlem geçmişi (entry/exit/pnl/slippage …)
    strategies         – Strateji tanımları ve metrikleri
    risk_snapshots     – Periyodik risk görüntüleri
    events             – Sistem olayları ve uyarıları
    top5_history       – Her döngüde seçilen Top-5 kontratlar
    config_history     – Konfigürasyon değişiklik kaydı
    manual_interventions – Manuel müdahale kaydı
    liquidity_classes  – Günlük likidite sınıflandırması
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from engine.config import Config
from engine.logger import get_logger

logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent / "database" / "trades.db"

# ── DDL ──────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol    TEXT    NOT NULL,
    timeframe TEXT    NOT NULL,
    timestamp TEXT    NOT NULL,
    open      REAL    NOT NULL,
    high      REAL    NOT NULL,
    low       REAL    NOT NULL,
    close     REAL    NOT NULL,
    volume    REAL    NOT NULL,
    PRIMARY KEY (symbol, timeframe, timestamp)
);

CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy        TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    direction       TEXT    NOT NULL,
    entry_time      TEXT,
    exit_time       TEXT,
    entry_price     REAL,
    exit_price      REAL,
    lot             REAL    NOT NULL,
    pnl             REAL,
    slippage        REAL,
    commission      REAL,
    swap            REAL,
    regime          TEXT,
    fake_score      REAL,
    exit_reason     TEXT,
    mt5_position_id INTEGER
);

CREATE TABLE IF NOT EXISTS strategies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    signal_type TEXT    NOT NULL,
    parameters  TEXT    NOT NULL DEFAULT '{}',
    status      TEXT    NOT NULL DEFAULT 'active',
    metrics     TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS risk_snapshots (
    timestamp      TEXT NOT NULL,
    equity         REAL NOT NULL,
    floating_pnl   REAL NOT NULL,
    daily_pnl      REAL NOT NULL,
    positions_json TEXT NOT NULL DEFAULT '[]',
    regime         TEXT,
    drawdown       REAL,
    margin_usage   REAL,
    PRIMARY KEY (timestamp)
);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT    NOT NULL,
    type      TEXT    NOT NULL,
    severity  TEXT    NOT NULL DEFAULT 'INFO',
    message   TEXT    NOT NULL,
    action    TEXT
);

CREATE TABLE IF NOT EXISTS top5_history (
    date   TEXT NOT NULL,
    time   TEXT NOT NULL,
    rank   INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    score  REAL,
    regime TEXT,
    PRIMARY KEY (date, time, rank)
);

CREATE TABLE IF NOT EXISTS config_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT NOT NULL,
    param      TEXT NOT NULL,
    old_value  TEXT,
    new_value  TEXT,
    changed_by TEXT
);

CREATE TABLE IF NOT EXISTS manual_interventions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    action    TEXT NOT NULL,
    reason    TEXT,
    user      TEXT
);

CREATE TABLE IF NOT EXISTS liquidity_classes (
    date       TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    avg_volume REAL,
    avg_spread REAL,
    class      TEXT,
    PRIMARY KEY (date, symbol)
);

CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bars_symbol        ON bars (symbol);
CREATE INDEX IF NOT EXISTS idx_trades_symbol       ON trades (symbol);
CREATE INDEX IF NOT EXISTS idx_trades_strategy     ON trades (strategy);
CREATE INDEX IF NOT EXISTS idx_trades_mt5pos       ON trades (mt5_position_id);
CREATE INDEX IF NOT EXISTS idx_events_type         ON events (type);
CREATE INDEX IF NOT EXISTS idx_events_severity     ON events (severity);
CREATE INDEX IF NOT EXISTS idx_top5_date           ON top5_history (date);
CREATE INDEX IF NOT EXISTS idx_risk_timestamp      ON risk_snapshots (timestamp);

CREATE TABLE IF NOT EXISTS hybrid_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket          INTEGER NOT NULL UNIQUE,
    symbol          TEXT    NOT NULL,
    direction       TEXT    NOT NULL,
    volume          REAL    NOT NULL,
    entry_price     REAL    NOT NULL,
    entry_atr       REAL    NOT NULL,
    initial_sl      REAL    NOT NULL,
    initial_tp      REAL    NOT NULL,
    current_sl      REAL,
    current_tp      REAL,
    state           TEXT    NOT NULL DEFAULT 'ACTIVE',
    breakeven_hit   INTEGER NOT NULL DEFAULT 0,
    trailing_active INTEGER NOT NULL DEFAULT 0,
    trailing_order_ticket INTEGER DEFAULT 0,
    target_order_ticket   INTEGER DEFAULT 0,
    transferred_at  TEXT    NOT NULL,
    closed_at       TEXT,
    close_reason    TEXT,
    pnl             REAL,
    swap            REAL    DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS hybrid_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT    NOT NULL,
    ticket    INTEGER NOT NULL,
    symbol    TEXT    NOT NULL,
    event     TEXT    NOT NULL,
    details   TEXT    DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_hybrid_pos_state   ON hybrid_positions (state);
CREATE INDEX IF NOT EXISTS idx_hybrid_pos_ticket  ON hybrid_positions (ticket);
CREATE INDEX IF NOT EXISTS idx_hybrid_evt_ticket  ON hybrid_events (ticket);

-- Composite index'ler (FAZ-A veri yönetimi)
CREATE INDEX IF NOT EXISTS idx_risk_ts_dd       ON risk_snapshots (timestamp, drawdown);
CREATE INDEX IF NOT EXISTS idx_events_ts_type   ON events (timestamp, type, severity);
CREATE INDEX IF NOT EXISTS idx_top5_date_sym    ON top5_history (date, symbol);

-- Günlük risk özet tablosu (aggregation)
CREATE TABLE IF NOT EXISTS daily_risk_summary (
    date          TEXT PRIMARY KEY,
    min_equity    REAL,
    max_equity    REAL,
    avg_equity    REAL,
    min_drawdown  REAL,
    max_drawdown  REAL,
    avg_drawdown  REAL,
    total_pnl     REAL,
    snapshot_count INTEGER,
    created_at    TEXT NOT NULL
);

-- Haftalık top5 özet tablosu (aggregation)
CREATE TABLE IF NOT EXISTS weekly_top5_summary (
    week           TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    avg_score      REAL,
    selection_count INTEGER,
    avg_rank       REAL,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (week, symbol)
);

CREATE TABLE IF NOT EXISTS notifications (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT    NOT NULL,
    type      TEXT    NOT NULL DEFAULT 'info',
    title     TEXT    NOT NULL DEFAULT '',
    message   TEXT    NOT NULL DEFAULT '',
    severity  TEXT    NOT NULL DEFAULT 'info',
    read      INTEGER NOT NULL DEFAULT 0,
    details   TEXT    DEFAULT '{}'
);
"""


# ═════════════════════════════════════════════════════════════════════
class Database:
    """Thread-safe SQLite veritabanı yöneticisi.

    Tek bir ``sqlite3.Connection`` tutar; her public metod
    ``self._lock`` ile korunur.  ``check_same_thread=False``
    sayesinde farklı thread'lerden güvenle çağrılabilir.
    """

    # ── init / bağlantı ──────────────────────────────────────────────
    def __init__(self, config: Config) -> None:
        self._config = config
        self._db_path = str(
            Path(config.get("database.path", str(DB_PATH)))
        )
        self._lock = threading.Lock()

        # Klasör yoksa oluştur
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn: sqlite3.Connection = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")  # WAL modunda NORMAL güvenlidir ve yazma performansını artırır
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA cache_size=-64000")   # 64MB cache (varsayılan ~2MB)
        self._conn.execute("PRAGMA mmap_size=268435456") # 256MB memory-mapped I/O

        # Bütünlük kontrolü — bozuk DB erken tespit
        self._check_integrity()

        self._create_tables()
        self._migrate_schema()
        logger.info(f"Veritabanı hazır: {self._db_path}")

    # ── Bütünlük kontrolü ────────────────────────────────────────────
    def _check_integrity(self) -> None:
        """Veritabanı bütünlük kontrolü — başlatmada çağrılır.

        PRAGMA quick_check ile hızlı kontrol yapar.
        Başarısızsa kritik hata loglar ama engine'i durdurmaz
        (yedekten geri yükleme operatörün sorumluluğundadır).
        """
        try:
            result = self._conn.execute("PRAGMA quick_check").fetchone()
            if result and result[0] == "ok":
                logger.info("DB bütünlük kontrolü: OK")
            else:
                detail = result[0] if result else "sonuç alınamadı"
                logger.critical(
                    f"DB BÜTÜNLÜK HATASI: {detail}. "
                    f"Veritabanı bozuk olabilir! Yedekten geri yüklemeyi düşünün. "
                    f"Yedek dosyaları: {Path(self._db_path).parent / 'trades_backup_*.db'}"
                )
        except Exception as exc:
            logger.error(f"DB bütünlük kontrolü yapılamadı: {exc}")

    # ── Yedekleme ──────────────────────────────────────────────────────
    def backup(self) -> str:
        """trades.db'nin tarihli yedeğini al. Son 5 yedeği tutar.

        SQLite backup API ile güvenli yedek alır (WAL aktifken bile
        tutarlı snapshot garantisi — shutil.copy2'den daha güvenli).

        Returns:
            Yedek dosya yolu.
        """
        db_path = Path(self._db_path)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.parent / f"trades_backup_{ts}.db"
        try:
            backup_conn = sqlite3.connect(str(backup_path))
            # Fix M10: WAL modda backup okuyucu olarak çalışır —
            # parçalı kopyalama ile yazma lock'unu uzun süre tutmayı önle
            self._conn.backup(backup_conn, pages=100, sleep=0.005)
            backup_conn.close()
            logger.info(f"DB yedekleme tamamlandı (sqlite3.backup): {backup_path}")
        except Exception as exc:
            logger.error(f"DB yedekleme hatası: {exc}")
            # Fallback: shutil ile kopyalama dene
            try:
                shutil.copy2(str(db_path), str(backup_path))
                logger.warning(f"DB yedekleme fallback (shutil.copy2): {backup_path}")
            except Exception as exc2:
                logger.error(f"DB yedekleme fallback da başarısız: {exc2}")
                return ""
        # Eski yedekleri temizle — son 5 tane tut
        backups = sorted(db_path.parent.glob("trades_backup_*.db"))
        for old in backups[:-5]:
            try:
                old.unlink()
                logger.debug(f"Eski yedek silindi: {old}")
            except Exception:
                pass
        return str(backup_path)

    def _create_tables(self) -> None:
        """Tüm tabloları ve indeksleri oluştur (idempotent)."""
        with self._lock:
            self._conn.executescript(_SCHEMA)
            # Mevcut DB için mt5_position_id kolonu yoksa ekle
            try:
                self._conn.execute(
                    "ALTER TABLE trades ADD COLUMN mt5_position_id INTEGER"
                )
            except Exception:
                pass  # kolon zaten varsa hata verir, sorun yok
            # Madde 3.5: risk_snapshots tablosuna balance kolonu ekle
            try:
                self._conn.execute(
                    "ALTER TABLE risk_snapshots ADD COLUMN balance REAL DEFAULT 0"
                )
            except Exception:
                pass  # kolon zaten varsa hata verir, sorun yok
            self._conn.commit()
        logger.debug("Tablo şeması doğrulandı.")

    def _migrate_schema(self) -> None:
        """Evrensel pozisyon yönetimi için trades tablosuna yeni kolonlar ekle."""
        _MIGRATIONS = [
            "ALTER TABLE trades ADD COLUMN tp1_hit INTEGER DEFAULT 0",
            "ALTER TABLE trades ADD COLUMN cost_averaged INTEGER DEFAULT 0",
            "ALTER TABLE trades ADD COLUMN initial_volume REAL",
            "ALTER TABLE trades ADD COLUMN peak_profit REAL DEFAULT 0",
            "ALTER TABLE trades ADD COLUMN breakeven_hit INTEGER DEFAULT 0",
            # v5.8.2: İşlem kaynağı — "app" (ManuelMotor UI), "mt5_direct" (MT5 terminali)
            "ALTER TABLE trades ADD COLUMN source TEXT DEFAULT ''",
        ]
        with self._lock:
            for sql in _MIGRATIONS:
                try:
                    self._conn.execute(sql)
                except Exception:
                    pass  # kolon zaten varsa hata verir, sorun yok
            self._conn.commit()
        logger.debug("Pozisyon yönetimi migration tamamlandı.")

    def close(self) -> None:
        """Bağlantıyı kapat — WAL önce checkpoint'lenir.

        v5.8.1: WAL checkpoint eklendi. Checkpoint yapılmadan close()
        çağrılırsa WAL'daki kayıtlar kaybolabilir (id 168-171 vakası).
        """
        with self._lock:
            try:
                # WAL'ı ana DB'ye yaz — veri kaybını önle
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                logger.info("WAL checkpoint yapıldı (close öncesi)")
            except Exception as exc:
                logger.warning(f"WAL checkpoint hatası (close öncesi): {exc}")
            try:
                self._conn.close()
            except Exception as exc:
                logger.error(f"DB close hatası: {exc}")
        logger.info("Veritabanı bağlantısı kapatıldı.")

    # ── genel yardımcılar ────────────────────────────────────────────
    def _execute(
        self,
        sql: str,
        params: tuple = (),
        *,
        commit: bool = True,
    ) -> sqlite3.Cursor:
        """Tek SQL çalıştır (thread-safe).

        Args:
            sql: SQL ifadesi.
            params: Parametreler.
            commit: Otomatik commit.

        Returns:
            Cursor nesnesi.
        """
        with self._lock:
            try:
                cur = self._conn.execute(sql, params)
                if commit:
                    self._conn.commit()
                return cur
            except sqlite3.Error as exc:
                logger.error(f"SQL hatası: {exc}\n  SQL: {sql}\n  params: {params}")
                raise

    def _executemany(
        self,
        sql: str,
        seq: list[tuple],
        *,
        commit: bool = True,
    ) -> None:
        """Toplu SQL çalıştır (thread-safe).

        Args:
            sql: SQL ifadesi.
            seq: Parametre listesi.
            commit: Otomatik commit.
        """
        with self._lock:
            try:
                self._conn.executemany(sql, seq)
                if commit:
                    self._conn.commit()
            except sqlite3.Error as exc:
                logger.error(f"SQL (many) hatası: {exc}\n  SQL: {sql}")
                raise

    def _fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """SELECT → list[dict] (thread-safe).

        Args:
            sql: SELECT ifadesi.
            params: Parametreler.

        Returns:
            Satır sözlüklerinin listesi.
        """
        with self._lock:
            try:
                rows = self._conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.Error as exc:
                logger.error(f"Fetch hatası: {exc}\n  SQL: {sql}")
                return []

    def _fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        """SELECT → tek satır dict veya None (thread-safe).

        Args:
            sql: SELECT ifadesi.
            params: Parametreler.

        Returns:
            Satır sözlüğü veya None.
        """
        with self._lock:
            try:
                row = self._conn.execute(sql, params).fetchone()
                return dict(row) if row else None
            except sqlite3.Error as exc:
                logger.error(f"Fetch-one hatası: {exc}\n  SQL: {sql}")
                return None

    @staticmethod
    def _now() -> str:
        """ISO-8601 şu-an damgası."""
        return datetime.now().isoformat(timespec="seconds")

    # ═════════════════════════════════════════════════════════════════
    #  APP STATE (key-value)
    # ═════════════════════════════════════════════════════════════════

    def get_state(self, key: str) -> str | None:
        """app_state tablosundan değer oku.

        Args:
            key: Anahtar adı.

        Returns:
            Değer veya None.
        """
        row = self._fetch_one(
            "SELECT value FROM app_state WHERE key=?", (key,),
        )
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        """app_state tablosuna değer yaz (upsert).

        Args:
            key: Anahtar adı.
            value: Kaydedilecek değer.
        """
        self._execute(
            "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
            (key, value),
        )

    # ═════════════════════════════════════════════════════════════════
    #  BARS
    # ═════════════════════════════════════════════════════════════════
    def insert_bars(self, symbol: str, timeframe: str, df: pd.DataFrame) -> int:
        """OHLCV bar verisi toplu ekle/güncelle.

        Args:
            symbol: Kontrat sembolü.
            timeframe: Zaman dilimi etiketi (ör. "M1", "H1").
            df: Sütunlar → time/timestamp, open, high, low, close,
                tick_volume/volume.

        Returns:
            Eklenen/güncellenen satır sayısı.
        """
        ts_col = "timestamp" if "timestamp" in df.columns else "time"
        vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"

        rows = [
            (symbol, timeframe, str(getattr(r, ts_col)),
             r.open, r.high, r.low, r.close, getattr(r, vol_col))
            for r in df.itertuples(index=False)
        ]
        self._executemany(
            """INSERT OR REPLACE INTO bars
               (symbol, timeframe, timestamp, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        logger.debug(f"Bars upsert [{symbol}/{timeframe}]: {len(rows)} satır")
        return len(rows)

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        since: str | None = None,
    ) -> pd.DataFrame:
        """Bar verisi getir.

        Args:
            symbol: Kontrat sembolü.
            timeframe: Zaman dilimi etiketi.
            limit: Maksimum satır sayısı.
            since: Başlangıç timestamp (ISO-8601).

        Returns:
            OHLCV DataFrame (boş olabilir).
        """
        if since:
            rows = self._fetch_all(
                """SELECT * FROM bars
                   WHERE symbol=? AND timeframe=? AND timestamp>=?
                   ORDER BY timestamp ASC LIMIT ?""",
                (symbol, timeframe, since, limit),
            )
        else:
            rows = self._fetch_all(
                """SELECT * FROM bars
                   WHERE symbol=? AND timeframe=?
                   ORDER BY timestamp DESC LIMIT ?""",
                (symbol, timeframe, limit),
            )
            rows.reverse()
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def delete_bars(self, symbol: str, timeframe: str, before: str) -> int:
        """Eski bar verilerini sil.

        Args:
            symbol: Kontrat sembolü.
            timeframe: Zaman dilimi.
            before: Bu tarihten önceki verileri sil (ISO-8601).

        Returns:
            Silinen satır sayısı.
        """
        cur = self._execute(
            "DELETE FROM bars WHERE symbol=? AND timeframe=? AND timestamp<?",
            (symbol, timeframe, before),
        )
        logger.debug(f"Bars delete [{symbol}/{timeframe}] <{before}: {cur.rowcount}")
        return cur.rowcount

    # ═════════════════════════════════════════════════════════════════
    #  TRADES
    # ═════════════════════════════════════════════════════════════════
    def insert_trade(self, trade: dict[str, Any]) -> int:
        """Yeni işlem kaydı ekle.

        Args:
            trade: Alanlar → strategy, symbol, direction, lot ve opsiyonel
                   entry_time, exit_time, entry_price, exit_price, pnl,
                   slippage, commission, swap, regime, fake_score, exit_reason.

        Returns:
            Oluşturulan satırın id'si.
        """
        cur = self._execute(
            """INSERT INTO trades
               (strategy, symbol, direction, entry_time, exit_time,
                entry_price, exit_price, lot, pnl, slippage,
                commission, swap, regime, fake_score, exit_reason,
                mt5_position_id, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trade["strategy"], trade["symbol"], trade["direction"],
                trade.get("entry_time"), trade.get("exit_time"),
                trade.get("entry_price"), trade.get("exit_price"),
                trade["lot"],
                trade.get("pnl"), trade.get("slippage"),
                trade.get("commission"), trade.get("swap"),
                trade.get("regime"), trade.get("fake_score"),
                trade.get("exit_reason"),
                trade.get("mt5_position_id"),
                trade.get("source", ""),
            ),
        )
        logger.debug(f"Trade insert id={cur.lastrowid}: {trade['symbol']}")
        return cur.lastrowid

    def sync_mt5_trades(self, trades: list[dict[str, Any]]) -> int:
        """MT5 işlem geçmişini trades tablosuna senkronize et.

        Dedup mantığı (sırayla):
        1. mt5_position_id ile birebir eşleşme → atla.
        2. OĞUL kaydı eşleştirme: mt5_position_id NULL + aynı symbol + direction
           + entry_time ±5 dk tolerans → mevcut kaydı güncelle (INSERT yerine UPDATE).
        3. Eşleşme yoksa → yeni satır ekle.

        Args:
            trades: get_history_for_sync() çıktısı — her biri bir trade dict.

        Returns:
            Eklenen + güncellenen trade sayısı.
        """
        added = 0
        updated = 0
        # Fix Y9: Tüm döngüyü try/except ile sar — hata durumunda rollback yap
        try:
            for t in trades:
                pos_id = t.get("mt5_position_id")

                # 1) mt5_position_id ile birebir eşleşme → komisyon/swap/pnl MT5'ten güncelle
                #    (OĞUL kapanışta get_deal_summary bazen None döner, sync ile doldurulur)
                if pos_id:
                    existing = self._fetch_one(
                        "SELECT id, commission, swap, pnl FROM trades WHERE mt5_position_id=?",
                        (pos_id,),
                    )
                    if existing:
                        # Fix Y12: Hibrit kontrolü + UPDATE tek atomik SQL
                        # (eski: ayrı SELECT + UPDATE → race condition)
                        self._execute(
                            """UPDATE trades SET pnl=?, commission=?, swap=?,
                               exit_time=COALESCE(exit_time, ?),
                               exit_price=COALESCE(exit_price, ?),
                               strategy = CASE
                                   WHEN EXISTS(SELECT 1 FROM hybrid_positions WHERE ticket=?)
                                   THEN 'hibrit' ELSE strategy END
                               WHERE id=?""",
                            (
                                t.get("pnl"), t.get("commission"), t.get("swap"),
                                t.get("exit_time"), t.get("exit_price"),
                                pos_id,
                                existing["id"],
                            ),
                            commit=False,
                        )
                        updated += 1
                        continue

                # 2) OĞUL kaydı eşleştirme: mt5_position_id NULL + symbol + direction
                #    Strateji A: entry_time ±5 dk tolerans
                #    Strateji B: exit_price + PnL eşleşmesi (timezone farkı durumu)
                entry_time = t.get("entry_time")
                ogul_match = None
                if pos_id and entry_time:
                    ogul_match = self._fetch_one(
                        """SELECT id FROM trades
                           WHERE mt5_position_id IS NULL
                             AND symbol=? AND direction=?
                             AND entry_time IS NOT NULL
                             AND ABS(
                                 CAST(strftime('%%s', entry_time) AS INTEGER)
                               - CAST(strftime('%%s', ?) AS INTEGER)
                             ) <= 300
                           ORDER BY id LIMIT 1""",
                        (t["symbol"], t["direction"], entry_time),
                    )

                # Strateji B: exit_price + PnL (timezone farkı yakalamak için)
                if not ogul_match and pos_id and t.get("exit_price") is not None:
                    sync_pnl = t.get("pnl") or 0.0
                    ogul_match = self._fetch_one(
                        """SELECT id FROM trades
                           WHERE mt5_position_id IS NULL
                             AND symbol=? AND direction=?
                             AND exit_price=?
                             AND pnl IS NOT NULL
                             AND ABS(pnl - ?) <= 5.0
                           ORDER BY id LIMIT 1""",
                        (t["symbol"], t["direction"],
                         t["exit_price"], sync_pnl),
                    )

                if ogul_match:
                    # Mevcut OĞUL kaydını MT5 verileriyle güncelle
                    self._execute(
                        """UPDATE trades SET
                             pnl=?, commission=?, swap=?,
                             mt5_position_id=?,
                             exit_time=?, exit_price=?,
                             entry_price=?, lot=?
                           WHERE id=?""",
                        (
                            t.get("pnl"), t.get("commission"), t.get("swap"),
                            pos_id,
                            t.get("exit_time"), t.get("exit_price"),
                            t.get("entry_price"), t["lot"],
                            ogul_match["id"],
                        ),
                        commit=False,
                    )
                    updated += 1
                    logger.debug(
                        f"Sync: OĞUL kaydı güncellendi id={ogul_match['id']} "
                        f"→ mt5_position_id={pos_id}"
                    )
                else:
                    # 3) Yeni kayıt ekle
                    # Fix Y12: Hibrit kontrolü atomik subquery ile
                    base_strategy = t.get("strategy", "manual")
                    self._execute(
                        """INSERT INTO trades
                           (strategy, symbol, direction, entry_time, exit_time,
                            entry_price, exit_price, lot, pnl, slippage,
                            commission, swap, regime, fake_score, exit_reason,
                            mt5_position_id)
                           VALUES (
                            CASE WHEN ? IS NOT NULL
                                      AND EXISTS(SELECT 1 FROM hybrid_positions WHERE ticket=?)
                                 THEN 'hibrit' ELSE ? END,
                            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            pos_id, pos_id, base_strategy,
                            t["symbol"], t["direction"],
                            t.get("entry_time"), t.get("exit_time"),
                            t.get("entry_price"), t.get("exit_price"),
                            t["lot"], t.get("pnl"), t.get("slippage"),
                            t.get("commission"), t.get("swap"),
                            t.get("regime"), t.get("fake_score"),
                            t.get("exit_reason"), pos_id,
                        ),
                        commit=False,
                    )
                    added += 1

            # Tüm değişiklikleri tek commit ile yaz (I/O optimizasyonu)
            if added or updated:
                with self._lock:
                    self._conn.commit()
                logger.info(
                    f"MT5 sync: {added} yeni eklendi, "
                    f"{updated} mevcut kayıt güncellendi"
                )
        except Exception as exc:
            with self._lock:
                self._conn.rollback()
            logger.error(
                f"MT5 sync hatası — rollback yapıldı "
                f"(added={added}, updated={updated}): {exc}"
            )
            raise
        return added + updated

    def update_trade(self, trade_id: int, fields: dict[str, Any]) -> bool:
        """İşlem kaydını güncelle.

        Args:
            trade_id: Güncellenecek işlem id'si.
            fields: Güncellenecek alan-değer çiftleri.

        Returns:
            Güncelleme başarılıysa True.
        """
        if not fields:
            return False
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = tuple(fields.values()) + (trade_id,)
        cur = self._execute(
            f"UPDATE trades SET {set_clause} WHERE id=?", values
        )
        logger.debug(f"Trade update id={trade_id}: {list(fields.keys())}")
        return cur.rowcount > 0

    def get_trade(self, trade_id: int) -> dict[str, Any] | None:
        """Tek işlem getir.

        Args:
            trade_id: İşlem id'si.

        Returns:
            İşlem sözlüğü veya None.
        """
        return self._fetch_one("SELECT * FROM trades WHERE id=?", (trade_id,))

    def deduplicate_trades(self) -> int:
        """Mevcut çift kayıtları temizle.

        Aynı pozisyon için hem OĞUL kaydı (mt5_position_id NULL) hem Sync
        kaydı (mt5_position_id NOT NULL) varsa, OĞUL kaydını siler.

        Eşleşme stratejisi (sırayla):
        1. symbol + direction + entry_time ±5 dk tolerans
        2. symbol + direction + aynı exit_price + yakın PnL (±5 TL)
           (timezone farkı nedeniyle entry_time uyuşmadığında)

        Returns:
            Silinen çift kayıt sayısı.
        """
        sync_rows = self._fetch_all(
            """SELECT id, symbol, direction, entry_time, exit_price,
                      pnl, mt5_position_id
               FROM trades WHERE mt5_position_id IS NOT NULL""",
            (),
        )
        if not sync_rows:
            return 0

        deleted_ids: set[int] = set()
        for sr in sync_rows:
            # Strateji 1: entry_time ±5 dk
            ogul_dup = None
            if sr.get("entry_time"):
                ogul_dup = self._fetch_one(
                    """SELECT id FROM trades
                       WHERE mt5_position_id IS NULL
                         AND symbol=? AND direction=?
                         AND entry_time IS NOT NULL
                         AND id NOT IN ({excluded})
                         AND ABS(
                             CAST(strftime('%%s', entry_time) AS INTEGER)
                           - CAST(strftime('%%s', ?) AS INTEGER)
                         ) <= 300
                       ORDER BY id LIMIT 1""".format(
                        excluded=",".join(str(d) for d in deleted_ids)
                        if deleted_ids else "0"
                    ),
                    (sr["symbol"], sr["direction"], sr["entry_time"]),
                )

            # Strateji 2: exit_price + PnL eşleşmesi (timezone farkı durumu)
            if not ogul_dup and sr.get("exit_price") is not None:
                sync_pnl = sr.get("pnl") or 0.0
                ogul_dup = self._fetch_one(
                    """SELECT id FROM trades
                       WHERE mt5_position_id IS NULL
                         AND symbol=? AND direction=?
                         AND exit_price=?
                         AND pnl IS NOT NULL
                         AND id NOT IN ({excluded})
                         AND ABS(pnl - ?) <= 5.0
                       ORDER BY id LIMIT 1""".format(
                        excluded=",".join(str(d) for d in deleted_ids)
                        if deleted_ids else "0"
                    ),
                    (sr["symbol"], sr["direction"],
                     sr["exit_price"], sync_pnl),
                )

            if ogul_dup:
                self._execute(
                    "DELETE FROM trades WHERE id=?", (ogul_dup["id"],)
                )
                deleted_ids.add(ogul_dup["id"])
                logger.debug(
                    f"Çift kayıt silindi: id={ogul_dup['id']} "
                    f"(mt5_position_id={sr['mt5_position_id']} "
                    f"ile eşleşti)"
                )

        # Strateji 3: Aynı mt5_position_id ile birden fazla kayıt varsa
        # en düşük id'li olanı (OĞUL kaydı) sil, en yüksek id'li (Sync) kalsın
        dup_pos_rows = self._fetch_all(
            """SELECT mt5_position_id, MIN(id) AS min_id, COUNT(*) AS cnt
               FROM trades
               WHERE mt5_position_id IS NOT NULL
               GROUP BY mt5_position_id
               HAVING cnt > 1""",
            (),
        )
        for dp in dup_pos_rows:
            if dp["min_id"] not in deleted_ids:
                self._execute(
                    "DELETE FROM trades WHERE id=?", (dp["min_id"],)
                )
                deleted_ids.add(dp["min_id"])
                logger.debug(
                    f"Aynı position çift kaydı silindi: id={dp['min_id']} "
                    f"(mt5_position_id={dp['mt5_position_id']})"
                )

        deleted = len(deleted_ids)
        if deleted:
            logger.info(f"Dedup: {deleted} çift kayıt temizlendi")
        return deleted

    def get_trades(
        self,
        symbol: str | None = None,
        strategy: str | None = None,
        since: str | None = None,
        limit: int = 100,
        closed_only: bool = True,
        exit_since: str | None = None,
    ) -> list[dict[str, Any]]:
        """İşlem listesi getir (filtreli).

        Args:
            symbol: Filtre: kontrat sembolü.
            strategy: Filtre: strateji adı.
            since: Filtre: bu tarihten sonra (YYYY-MM-DD). entry_time bazlı.
            limit: Maksimum satır.
            closed_only: True ise yalnızca kapanmış işlemler (exit_time dolu).
                         False ise açık/kapanmamış kayıtlar da dahil.
            exit_since: Filtre: bu tarihten sonra kapatılan işlemler (exit_time bazlı).
                        MT5 tarzı günlük realized P/L hesaplaması için kullanılır.

        Returns:
            İşlem sözlüklerinin listesi.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if closed_only:
            clauses.append("exit_time IS NOT NULL")
        if symbol:
            clauses.append("symbol=?")
            params.append(symbol)
        if strategy:
            clauses.append("strategy=?")
            params.append(strategy)
        if since:
            clauses.append("entry_time>=?")
            params.append(since)
        if exit_since:
            clauses.append("exit_time>=?")
            params.append(exit_since)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        order = "exit_time DESC, id DESC" if closed_only else "exit_time IS NULL DESC, exit_time DESC, id DESC"
        return self._fetch_all(
            f"SELECT * FROM trades {where} ORDER BY {order} LIMIT ?",
            tuple(params),
        )

    # ═════════════════════════════════════════════════════════════════
    #  RISK SNAPSHOTS
    # ═════════════════════════════════════════════════════════════════
    def insert_risk_snapshot(self, snap: dict[str, Any]) -> None:
        """Risk görüntüsü kaydet.

        Args:
            snap: Alanlar → equity, floating_pnl, daily_pnl ve opsiyonel
                  timestamp, positions_json, regime, drawdown, margin_usage.
        """
        positions = snap.get("positions_json")
        if isinstance(positions, (list, dict)):
            positions = json.dumps(positions)

        self._execute(
            """INSERT OR REPLACE INTO risk_snapshots
               (timestamp, equity, floating_pnl, daily_pnl,
                positions_json, regime, drawdown, margin_usage, balance)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                snap.get("timestamp", self._now()),
                snap.get("equity", 0.0), snap.get("floating_pnl", 0.0), snap.get("daily_pnl", 0.0),
                positions or "[]",
                snap.get("regime"), snap.get("drawdown"), snap.get("margin_usage"),
                snap.get("balance", 0.0),
            ),
        )
        logger.debug(f"Risk snapshot kaydedildi: equity={snap.get('equity', 0.0):.2f}")

    def get_risk_snapshots(
        self,
        since: str | None = None,
        limit: int = 100,
        oldest_first: bool = False,
    ) -> list[dict[str, Any]]:
        """Risk görüntülerini getir.

        Args:
            since: Başlangıç timestamp (ISO-8601).
            limit: Maksimum satır.
            oldest_first: True ise en eskiden yeniye sırala (ASC).
                          False ise en yeniden eskiye sırala (DESC, mevcut davranış).

        Returns:
            Risk snapshot sözlüklerinin listesi.
        """
        order = "ASC" if oldest_first else "DESC"
        if since:
            rows = self._fetch_all(
                f"""SELECT * FROM risk_snapshots
                   WHERE timestamp>=? ORDER BY timestamp {order} LIMIT ?""",
                (since, limit),
            )
        else:
            rows = self._fetch_all(
                f"SELECT * FROM risk_snapshots ORDER BY timestamp {order} LIMIT ?",
                (limit,),
            )
        for r in rows:
            r["positions_json"] = json.loads(r.get("positions_json") or "[]")
            if not r.get("balance"):
                r["balance"] = r.get("equity", 0.0) - r.get("floating_pnl", 0.0)
        return rows

    def get_daily_end_snapshots(
        self,
        since: str | None = None,
        limit: int = 365,
    ) -> list[dict[str, Any]]:
        """Her işlem günü için son risk snapshot'ını döndür.

        SQL GROUP BY ile gün bazlı gruplama yapar. Sharpe ratio hesabı
        için yüzde getiri türetmede kullanılır (Madde 2.2).

        SQLite özelliği: MAX(timestamp) ile birlikte bare column'lar
        aynı satırdan gelir (documented extension to SQL).

        Args:
            since: Başlangıç timestamp (ISO-8601).
            limit: Maksimum gün sayısı.

        Returns:
            Gün bazlı son snapshot listesi (kronolojik sırada).
        """
        if since:
            rows = self._fetch_all(
                """SELECT *, MAX(timestamp) AS _max_ts
                   FROM risk_snapshots
                   WHERE timestamp >= ?
                   GROUP BY substr(timestamp, 1, 10)
                   ORDER BY _max_ts ASC
                   LIMIT ?""",
                (since, limit),
            )
        else:
            rows = self._fetch_all(
                """SELECT *, MAX(timestamp) AS _max_ts
                   FROM risk_snapshots
                   GROUP BY substr(timestamp, 1, 10)
                   ORDER BY _max_ts ASC
                   LIMIT ?""",
                (limit,),
            )
        for r in rows:
            r["positions_json"] = json.loads(r.get("positions_json") or "[]")
            if not r.get("balance"):
                r["balance"] = r.get("equity", 0.0) - r.get("floating_pnl", 0.0)
        return rows

    def get_latest_risk_snapshot(self) -> dict[str, Any] | None:
        """En son risk görüntüsünü getir.

        Returns:
            Risk snapshot sözlüğü veya None.
        """
        row = self._fetch_one(
            "SELECT * FROM risk_snapshots ORDER BY timestamp DESC LIMIT 1"
        )
        if row:
            row["positions_json"] = json.loads(row.get("positions_json") or "[]")
            # Geriye uyumluluk: eski kayıtlarda balance=0/None ise hesapla
            if not row.get("balance"):
                row["balance"] = row.get("equity", 0.0) - row.get("floating_pnl", 0.0)
        return row

    def delete_risk_snapshots(self, before: str) -> int:
        """Eski risk görüntülerini sil.

        Args:
            before: Bu tarihten önceki verileri sil (ISO-8601).

        Returns:
            Silinen satır sayısı.
        """
        cur = self._execute(
            "DELETE FROM risk_snapshots WHERE timestamp<?", (before,)
        )
        logger.debug(f"Risk snapshots delete <{before}: {cur.rowcount}")
        return cur.rowcount

    # ═════════════════════════════════════════════════════════════════
    #  EVENTS
    # ═════════════════════════════════════════════════════════════════
    # Deduplication cache: {(event_type, message_prefix): last_insert_time}
    _event_dedup_cache: dict[tuple[str, str], str] = {}

    def insert_event(
        self,
        event_type: str,
        message: str,
        severity: str = "INFO",
        action: str | None = None,
        dedup_seconds: int = 0,
    ) -> int:
        """Sistem olayı kaydet.

        Args:
            event_type: Olay tipi (ör. "TRADE", "RISK", "SYSTEM", "ERROR").
            message: Olay mesajı.
            severity: Önem derecesi ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL").
            action: Yapılan/önerilen aksiyon.
            dedup_seconds: >0 ise aynı (type, mesaj ilk 80 karakter) çifti
                bu süre içinde tekrar yazılmaz. 0 = dedup yok (varsayılan).

        Returns:
            Oluşturulan satırın id'si veya dedup nedeniyle atlandıysa 0.
        """
        if dedup_seconds > 0:
            from datetime import datetime, timedelta
            prefix = message[:80]
            key = (event_type, prefix)
            now = datetime.now()
            last = self._event_dedup_cache.get(key)
            if last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    if (now - last_dt).total_seconds() < dedup_seconds:
                        return 0  # Dedup — atla
                except (ValueError, TypeError):
                    pass
            self._event_dedup_cache[key] = now.isoformat()
            # Cache temizliği: 1000+ girişte eski kayıtları sil
            if len(self._event_dedup_cache) > 1000:
                cutoff = (now - timedelta(seconds=dedup_seconds * 2)).isoformat()
                self._event_dedup_cache = {
                    k: v for k, v in self._event_dedup_cache.items()
                    if v > cutoff
                }

        cur = self._execute(
            """INSERT INTO events (timestamp, type, severity, message, action)
               VALUES (?,?,?,?,?)""",
            (self._now(), event_type, severity, message, action),
        )
        logger.debug(f"Event [{severity}] {event_type}: {message}")
        return cur.lastrowid

    def get_events(
        self,
        event_type: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Olayları getir (filtreli).

        Args:
            event_type: Filtre: olay tipi.
            severity: Filtre: minimum önem derecesi.
            limit: Maksimum satır.

        Returns:
            Olay sözlüklerinin listesi.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if event_type:
            clauses.append("type=?")
            params.append(event_type)
        if severity:
            clauses.append("severity=?")
            params.append(severity)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        return self._fetch_all(
            f"SELECT * FROM events {where} ORDER BY id DESC LIMIT ?",
            tuple(params),
        )

    def delete_events(self, before: str) -> int:
        """Eski olayları sil.

        Args:
            before: Bu tarihten önceki olayları sil (ISO-8601).

        Returns:
            Silinen satır sayısı.
        """
        cur = self._execute(
            "DELETE FROM events WHERE timestamp<?", (before,)
        )
        logger.debug(f"Events delete <{before}: {cur.rowcount}")
        return cur.rowcount

    # ═════════════════════════════════════════════════════════════════
    #  TOP5 HISTORY
    # ═════════════════════════════════════════════════════════════════
    def insert_top5(self, entries: list[dict[str, Any]]) -> None:
        """Top-5 kontrat seçim kaydı ekle.

        Args:
            entries: Her biri → date, time, rank, symbol, score, regime
                     içeren sözlük listesi (genelde 5 adet).
        """
        if not entries:
            logger.warning("insert_top5 boş liste ile çağrıldı — kayıt yok")
            return
        rows = [
            (
                e["date"], e["time"], e["rank"],
                e["symbol"], e.get("score"), e.get("regime"),
            )
            for e in entries
        ]
        self._executemany(
            """INSERT OR REPLACE INTO top5_history
               (date, time, rank, symbol, score, regime)
               VALUES (?,?,?,?,?,?)""",
            rows,
        )
        symbols = [e["symbol"] for e in entries]
        logger.debug(f"Top5 kaydedildi [{entries[0]['date']}]: {symbols}")

    def get_top5(
        self,
        target_date: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Top-5 geçmişi getir.

        Args:
            target_date: Filtre: belirli bir gün (YYYY-MM-DD).
            limit: Maksimum satır.

        Returns:
            Top-5 kayıt sözlüklerinin listesi.
        """
        if target_date:
            return self._fetch_all(
                """SELECT * FROM top5_history
                   WHERE date=? ORDER BY time DESC, rank ASC LIMIT ?""",
                (target_date, limit),
            )
        return self._fetch_all(
            """SELECT * FROM top5_history
               ORDER BY date DESC, time DESC, rank ASC LIMIT ?""",
            (limit,),
        )

    # ═════════════════════════════════════════════════════════════════
    #  MANUAL INTERVENTIONS
    # ═════════════════════════════════════════════════════════════════
    def insert_intervention(
        self,
        action: str,
        reason: str | None = None,
        user: str = "operator",
    ) -> int:
        """Manuel müdahale kaydı ekle.

        Args:
            action: Yapılan müdahale (ör. "engine_stop", "force_close").
            reason: Müdahale sebebi.
            user: Müdahaleyi yapan kullanıcı.

        Returns:
            Oluşturulan satırın id'si.
        """
        cur = self._execute(
            """INSERT INTO manual_interventions (timestamp, action, reason, user)
               VALUES (?,?,?,?)""",
            (self._now(), action, reason, user),
        )
        logger.info(f"Manuel müdahale: {action} by {user} — {reason}")
        return cur.lastrowid

    # ═════════════════════════════════════════════════════════════════
    #  LIQUIDITY CLASSES
    # ═════════════════════════════════════════════════════════════════
    def get_liquidity(
        self,
        target_date: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """Likidite sınıflandırmasını getir.

        Args:
            target_date: Filtre: gün (YYYY-MM-DD).
            symbol: Filtre: kontrat sembolü.

        Returns:
            Likidite sözlüklerinin listesi.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if target_date:
            clauses.append("date=?")
            params.append(target_date)
        if symbol:
            clauses.append("symbol=?")
            params.append(symbol)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self._fetch_all(
            f"SELECT * FROM liquidity_classes {where} ORDER BY date DESC, symbol",
            tuple(params),
        )

    # ═════════════════════════════════════════════════════════════════
    #  HİBRİT POZİSYONLAR
    # ═════════════════════════════════════════════════════════════════

    def insert_hybrid_position(self, data: dict[str, Any]) -> int:
        """Yeni hibrit pozisyon kaydı ekle.

        Args:
            data: ticket, symbol, direction, volume, entry_price, entry_atr,
                  initial_sl, initial_tp, current_sl, current_tp alanları.

        Returns:
            Oluşturulan satırın id'si.
        """
        # v14: INSERT OR REPLACE — aynı ticket tekrar devredilirse eski kaydı güncelle
        cur = self._execute(
            """INSERT OR REPLACE INTO hybrid_positions
               (ticket, symbol, direction, volume, entry_price, entry_atr,
                initial_sl, initial_tp, current_sl, current_tp,
                state, breakeven_hit, trailing_active,
                trailing_order_ticket, target_order_ticket, transferred_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["ticket"], data["symbol"], data["direction"],
                data["volume"], data["entry_price"], data["entry_atr"],
                data["initial_sl"], data["initial_tp"],
                data.get("current_sl", data["initial_sl"]),
                data.get("current_tp", data["initial_tp"]),
                "ACTIVE", 0, 0, 0, 0, self._now(),
            ),
        )
        logger.info(
            f"Hibrit pozisyon eklendi: ticket={data['ticket']} "
            f"{data['symbol']} {data['direction']}"
        )
        return cur.lastrowid

    def update_hybrid_position(self, ticket: int, updates: dict[str, Any]) -> None:
        """Hibrit pozisyon alanlarını güncelle.

        Args:
            ticket: MT5 pozisyon ticket'ı.
            updates: Güncellenecek alan-değer çiftleri
                     (current_sl, current_tp, breakeven_hit, trailing_active, state vb.).
        """
        if not updates:
            return
        set_parts = [f"{k}=?" for k in updates]
        values = list(updates.values()) + [ticket]
        self._execute(
            f"UPDATE hybrid_positions SET {', '.join(set_parts)} WHERE ticket=?",
            tuple(values),
        )

    def get_active_hybrid_positions(self) -> list[dict[str, Any]]:
        """Aktif (state='ACTIVE') hibrit pozisyonları getir.

        Returns:
            Hibrit pozisyon sözlüklerinin listesi.
        """
        return self._fetch_all(
            "SELECT * FROM hybrid_positions WHERE state='ACTIVE' ORDER BY id",
        )

    def close_hybrid_position(
        self, ticket: int, reason: str, pnl: float, swap: float = 0.0,
    ) -> None:
        """Hibrit pozisyonu kapat (state=CLOSED, kapanış bilgileri yaz).

        Args:
            ticket: MT5 pozisyon ticket'ı.
            reason: Kapanış nedeni (BREAKEVEN, TRAILING_SL, TP_HIT, SL_HIT, EOD, KILL_SWITCH_L3, MANUAL_REMOVE, EXTERNAL).
            pnl: Kapanış K/Z (TRY).
            swap: Birikmiş swap maliyeti (TRY).
        """
        self._execute(
            """UPDATE hybrid_positions
               SET state='CLOSED', closed_at=?, close_reason=?, pnl=?, swap=?
               WHERE ticket=?""",
            (self._now(), reason, pnl, swap, ticket),
        )
        logger.info(
            f"Hibrit pozisyon kapatıldı: ticket={ticket} "
            f"neden={reason} pnl={pnl:.2f}"
        )

    def insert_hybrid_event(
        self, ticket: int, symbol: str, event: str, details: dict[str, Any] | None = None,
    ) -> int:
        """Hibrit olay kaydı ekle.

        Args:
            ticket: İlgili pozisyon ticket'ı.
            symbol: Kontrat sembolü.
            event: Olay tipi (TRANSFER, BREAKEVEN, TRAILING_UPDATE, SL_MODIFY, TP_HIT, CLOSE, REMOVE, EOD_CLOSE, L3_CLOSE).
            details: Ek bilgi sözlüğü (JSON olarak saklanır).

        Returns:
            Oluşturulan satırın id'si.
        """
        import json as _json
        details_str = _json.dumps(details or {}, default=str)
        cur = self._execute(
            """INSERT INTO hybrid_events (timestamp, ticket, symbol, event, details)
               VALUES (?,?,?,?,?)""",
            (self._now(), ticket, symbol, event, details_str),
        )
        return cur.lastrowid

    def get_hybrid_daily_pnl(self, target_date: str | None = None) -> float:
        """Belirtilen güne ait kapatılan hibrit pozisyonların toplam PnL'ini getir.

        Args:
            target_date: Tarih (YYYY-MM-DD). None ise bugün.

        Returns:
            Toplam PnL (TRY). Kayıt yoksa 0.0.
        """
        if target_date is None:
            target_date = date.today().isoformat()
        rows = self._fetch_all(
            """SELECT COALESCE(SUM(pnl), 0) as total
               FROM hybrid_positions
               WHERE state='CLOSED' AND closed_at LIKE ?""",
            (f"{target_date}%",),
        )
        return rows[0]["total"] if rows else 0.0

    def get_hybrid_events(
        self, limit: int = 50, ticket: int | None = None,
    ) -> list[dict[str, Any]]:
        """Hibrit olay geçmişini getir.

        Args:
            limit: Maksimum satır sayısı.
            ticket: Opsiyonel filtre: sadece bu ticket'ın olayları.

        Returns:
            Olay sözlüklerinin listesi.
        """
        if ticket is not None:
            return self._fetch_all(
                "SELECT * FROM hybrid_events WHERE ticket=? ORDER BY id DESC LIMIT ?",
                (ticket, limit),
            )
        return self._fetch_all(
            "SELECT * FROM hybrid_events ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    # ═════════════════════════════════════════════════════════════════
    #  v5.8/CEO-FAZ2: ARŞİVLEME VE BAKIM
    # ═════════════════════════════════════════════════════════════════

    def archive_old_trades(self, days: int = 90) -> int:
        """90 günden eski işlemleri archive.db'ye taşı.

        Trades tablosu hiç temizlenmiyordu — DB sınırsız büyüyordu.
        Bu metot eski trade'leri ayrı bir arşiv DB'ye kopyalar ve
        ana DB'den siler.

        Args:
            days: Bu günden eski trade'ler arşivlenir (varsayılan 90).

        Returns:
            Arşivlenen trade sayısı.
        """
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        archive_path = Path(self._db_path).parent / "trades_archive.db"

        with self._lock:
            try:
                # 1. Arşivlenecek trade sayısını kontrol et
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM trades WHERE exit_time IS NOT NULL AND exit_time < ?",
                    (cutoff,),
                ).fetchone()
                count = row[0] if row else 0
                if count == 0:
                    return 0

                # 2. Arşiv DB'ye bağlan ve tablo oluştur
                archive_conn = sqlite3.connect(str(archive_path))
                archive_conn.execute("PRAGMA journal_mode=WAL")

                # Ana DB'deki trades tablosu şemasını kopyala
                schema_row = self._conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='trades'"
                ).fetchone()
                if schema_row and schema_row[0]:
                    # CREATE TABLE IF NOT EXISTS yaparak idempotent ol
                    create_sql = schema_row[0].replace(
                        "CREATE TABLE trades",
                        "CREATE TABLE IF NOT EXISTS trades",
                    )
                    archive_conn.execute(create_sql)
                    archive_conn.commit()

                # 3. Eski trade'leri arşive kopyala
                old_trades = self._conn.execute(
                    "SELECT * FROM trades WHERE exit_time IS NOT NULL AND exit_time < ?",
                    (cutoff,),
                ).fetchall()

                if old_trades:
                    # Kolon sayısını al
                    col_count = len(old_trades[0])
                    placeholders = ",".join(["?"] * col_count)
                    archive_conn.executemany(
                        f"INSERT OR IGNORE INTO trades VALUES ({placeholders})",
                        old_trades,
                    )
                    archive_conn.commit()

                archive_conn.close()

                # 4. Ana DB'den sil
                self._conn.execute(
                    "DELETE FROM trades WHERE exit_time IS NOT NULL AND exit_time < ?",
                    (cutoff,),
                )
                self._conn.commit()

                logger.info(
                    f"Trade arşivleme tamamlandı: {count} trade → {archive_path} "
                    f"(cutoff: {cutoff})"
                )
                return count

            except Exception as exc:
                logger.error(f"Trade arşivleme hatası: {exc}")
                return 0

    def wal_checkpoint(self) -> bool:
        """WAL dosyasını ana DB'ye checkpoint et.

        WAL dosyası (trades.db-wal) büyüyebilir. Periyodik checkpoint
        WAL içeriğini ana DB'ye yazar ve WAL boyutunu küçültür.

        Returns:
            Checkpoint başarılı ise True.
        """
        with self._lock:
            try:
                # TRUNCATE modu: WAL'ı ana DB'ye yaz ve WAL dosyasını sıfırla
                result = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if result:
                    busy, log_pages, checkpointed = result
                    logger.info(
                        f"WAL checkpoint tamamlandı: "
                        f"busy={busy}, log_pages={log_pages}, "
                        f"checkpointed={checkpointed}"
                    )
                    return busy == 0
                return True
            except Exception as exc:
                logger.error(f"WAL checkpoint hatası: {exc}")
                return False

    def vacuum(self) -> bool:
        """VACUUM çalıştırarak boş alanı geri kazan.

        DELETE sonrası SQLite dosya boyutu küçülmez — VACUUM gerekir.
        DİKKAT: Kısa süreliğine DB kilitlenir, sadece piyasa kapalıyken çalıştırın.

        Returns:
            VACUUM başarılı ise True.
        """
        with self._lock:
            try:
                self._conn.execute("VACUUM")
                logger.info("DB VACUUM tamamlandı — boş alan geri kazanıldı")
                return True
            except Exception as exc:
                logger.error(f"DB VACUUM hatası: {exc}")
                return False

    def run_maintenance(self, archive_days: int = 90) -> dict[str, Any]:
        """Kapsamlı bakım: arşivle → checkpoint → vacuum.

        Sadece piyasa kapalıyken çağrılmalıdır (Anayasa: Barış zamanı kuralları).

        Args:
            archive_days: Bu günden eski trade'ler arşivlenir.

        Returns:
            Bakım sonuç raporu.
        """
        report: dict[str, Any] = {
            "archived_trades": 0,
            "wal_checkpoint": False,
            "vacuum": False,
        }

        # 1. Trade arşivleme
        report["archived_trades"] = self.archive_old_trades(archive_days)

        # 2. WAL checkpoint
        report["wal_checkpoint"] = self.wal_checkpoint()

        # 3. VACUUM (arşivleme + silme sonrası yer kazanma)
        if report["archived_trades"] > 0:
            report["vacuum"] = self.vacuum()

        logger.info(f"DB bakım raporu: {report}")
        return report

    # ═════════════════════════════════════════════════════════════════
    #  DATA RETENTION (FAZ-A Veri Yönetimi)
    # ═════════════════════════════════════════════════════════════════

    def _aggregate_daily_risk(self, target_date: str) -> bool:
        """Belirli bir günün risk snapshot'larını günlük özete dönüştür.

        Args:
            target_date: YYYY-MM-DD formatında gün.

        Returns:
            Aggregation başarılı ise True.
        """
        try:
            row = self._fetch_one(
                """SELECT
                       MIN(equity) AS min_equity,
                       MAX(equity) AS max_equity,
                       AVG(equity) AS avg_equity,
                       MIN(drawdown) AS min_drawdown,
                       MAX(drawdown) AS max_drawdown,
                       AVG(drawdown) AS avg_drawdown,
                       SUM(daily_pnl) AS total_pnl,
                       COUNT(*) AS snapshot_count
                   FROM risk_snapshots
                   WHERE timestamp LIKE ?""",
                (f"{target_date}%",),
            )
            if row and row["snapshot_count"] > 0:
                self._execute(
                    """INSERT OR REPLACE INTO daily_risk_summary
                       (date, min_equity, max_equity, avg_equity,
                        min_drawdown, max_drawdown, avg_drawdown,
                        total_pnl, snapshot_count, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        target_date,
                        row["min_equity"], row["max_equity"], row["avg_equity"],
                        row["min_drawdown"], row["max_drawdown"], row["avg_drawdown"],
                        row["total_pnl"], row["snapshot_count"],
                        self._now(),
                    ),
                )
                return True
            return False
        except Exception as exc:
            logger.error(f"Günlük risk aggregation hatası [{target_date}]: {exc}")
            return False

    def _aggregate_weekly_top5(self, week_start: str, week_end: str) -> int:
        """Belirli bir haftanın top5 verilerini haftalık özete dönüştür.

        Args:
            week_start: Hafta başlangıcı (YYYY-MM-DD).
            week_end: Hafta sonu (YYYY-MM-DD).

        Returns:
            Oluşturulan özet satır sayısı.
        """
        try:
            rows = self._fetch_all(
                """SELECT
                       symbol,
                       AVG(score) AS avg_score,
                       COUNT(*) AS selection_count,
                       AVG(rank) AS avg_rank
                   FROM top5_history
                   WHERE date >= ? AND date <= ?
                   GROUP BY symbol""",
                (week_start, week_end),
            )
            count = 0
            for r in rows:
                self._execute(
                    """INSERT OR REPLACE INTO weekly_top5_summary
                       (week, symbol, avg_score, selection_count, avg_rank, created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (week_start, r["symbol"], r["avg_score"],
                     r["selection_count"], r["avg_rank"], self._now()),
                )
                count += 1
            return count
        except Exception as exc:
            logger.error(f"Haftalık top5 aggregation hatası [{week_start}]: {exc}")
            return 0

    def run_retention(self, retention_config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Veri retention politikasını uygula: aggregate → sil → checkpoint.

        Silmeden önce veriyi özetler (aggregation) — veri kaybı olmaz.
        Sadece piyasa kapalıyken çağrılmalıdır.

        Args:
            retention_config: Tablo bazlı retention günleri. Varsayılan:
                risk_snapshots_days=30, top5_history_days=60,
                events_info_days=14, events_warning_days=30,
                events_error_days=90, config_history_days=365,
                liquidity_days=30, hybrid_closed_days=90

        Returns:
            Retention sonuç raporu.
        """
        cfg = retention_config or {}
        risk_days = cfg.get("risk_snapshots_days", 30)
        top5_days = cfg.get("top5_history_days", 60)
        ev_info_days = cfg.get("events_info_days", 14)
        ev_warn_days = cfg.get("events_warning_days", 30)
        ev_err_days = cfg.get("events_error_days", 90)
        config_days = cfg.get("config_history_days", 365)
        liquidity_days = cfg.get("liquidity_days", 30)
        hybrid_days = cfg.get("hybrid_closed_days", 90)

        now = datetime.now()
        report: dict[str, Any] = {
            "risk_aggregated_days": 0,
            "risk_deleted": 0,
            "top5_aggregated_weeks": 0,
            "top5_deleted": 0,
            "events_deleted": 0,
            "config_history_deleted": 0,
            "liquidity_deleted": 0,
            "hybrid_archived": 0,
        }

        logger.info(
            f"Retention başlatılıyor — risk:{risk_days}g, top5:{top5_days}g, "
            f"events(I/W/E):{ev_info_days}/{ev_warn_days}/{ev_err_days}g"
        )

        # ── 1. Risk Snapshots: Aggregate → Sil ──
        risk_cutoff = (now - timedelta(days=risk_days)).strftime("%Y-%m-%d")
        try:
            # Silinecek günleri bul
            days_to_agg = self._fetch_all(
                """SELECT DISTINCT substr(timestamp, 1, 10) AS day
                   FROM risk_snapshots
                   WHERE timestamp < ?
                   ORDER BY day""",
                (risk_cutoff,),
            )
            for row in days_to_agg:
                if self._aggregate_daily_risk(row["day"]):
                    report["risk_aggregated_days"] += 1

            # Aggregate edildikten sonra raw veriyi sil
            if days_to_agg:
                report["risk_deleted"] = self.delete_risk_snapshots(risk_cutoff)
                logger.info(
                    f"Risk retention: {report['risk_aggregated_days']} gün aggregate, "
                    f"{report['risk_deleted']} satır silindi"
                )
        except Exception as exc:
            logger.error(f"Risk retention hatası: {exc}")

        # ── 2. Top5 History: Haftalık Aggregate → Sil ──
        top5_cutoff = (now - timedelta(days=top5_days)).strftime("%Y-%m-%d")
        try:
            # Silinecek haftaları bul (Pazartesi bazlı)
            weeks_to_agg = self._fetch_all(
                """SELECT DISTINCT
                       date(date, 'weekday 1', '-7 days') AS week_start
                   FROM top5_history
                   WHERE date < ?
                   ORDER BY week_start""",
                (top5_cutoff,),
            )
            for row in weeks_to_agg:
                ws = row["week_start"]
                we = (datetime.strptime(ws, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")
                agg_count = self._aggregate_weekly_top5(ws, we)
                if agg_count > 0:
                    report["top5_aggregated_weeks"] += 1

            # Aggregate edildikten sonra raw veriyi sil
            if weeks_to_agg:
                cur = self._execute(
                    "DELETE FROM top5_history WHERE date < ?", (top5_cutoff,)
                )
                report["top5_deleted"] = cur.rowcount
                logger.info(
                    f"Top5 retention: {report['top5_aggregated_weeks']} hafta aggregate, "
                    f"{report['top5_deleted']} satır silindi"
                )
        except Exception as exc:
            logger.error(f"Top5 retention hatası: {exc}")

        # ── 3. Events: Severity bazlı retention ──
        try:
            deleted = 0
            # INFO: kısa retention
            info_cutoff = (now - timedelta(days=ev_info_days)).isoformat(timespec="seconds")
            cur = self._execute(
                "DELETE FROM events WHERE severity='INFO' AND timestamp<?",
                (info_cutoff,),
            )
            deleted += cur.rowcount

            # WARNING: orta retention
            warn_cutoff = (now - timedelta(days=ev_warn_days)).isoformat(timespec="seconds")
            cur = self._execute(
                "DELETE FROM events WHERE severity='WARNING' AND timestamp<?",
                (warn_cutoff,),
            )
            deleted += cur.rowcount

            # ERROR/CRITICAL: uzun retention
            err_cutoff = (now - timedelta(days=ev_err_days)).isoformat(timespec="seconds")
            cur = self._execute(
                "DELETE FROM events WHERE severity IN ('ERROR','CRITICAL') AND timestamp<?",
                (err_cutoff,),
            )
            deleted += cur.rowcount

            report["events_deleted"] = deleted
            if deleted > 0:
                logger.info(f"Events retention: {deleted} satır silindi")
        except Exception as exc:
            logger.error(f"Events retention hatası: {exc}")

        # ── 4. Config History: 12 ay retention ──
        try:
            cfg_cutoff = (now - timedelta(days=config_days)).isoformat(timespec="seconds")
            cur = self._execute(
                "DELETE FROM config_history WHERE timestamp<?", (cfg_cutoff,)
            )
            report["config_history_deleted"] = cur.rowcount
        except Exception as exc:
            logger.error(f"Config history retention hatası: {exc}")

        # ── 5. Liquidity Classes: 30 gün retention ──
        try:
            liq_cutoff = (now - timedelta(days=liquidity_days)).strftime("%Y-%m-%d")
            cur = self._execute(
                "DELETE FROM liquidity_classes WHERE date<?", (liq_cutoff,)
            )
            report["liquidity_deleted"] = cur.rowcount
        except Exception as exc:
            logger.error(f"Liquidity retention hatası: {exc}")

        # ── 6. Hybrid: Kapatılmış pozisyonları arşivle ──
        try:
            hybrid_cutoff = (now - timedelta(days=hybrid_days)).isoformat(timespec="seconds")
            cur = self._execute(
                "DELETE FROM hybrid_events WHERE ticket IN "
                "(SELECT ticket FROM hybrid_positions WHERE state='CLOSED' AND closed_at<?)",
                (hybrid_cutoff,),
            )
            cur2 = self._execute(
                "DELETE FROM hybrid_positions WHERE state='CLOSED' AND closed_at<?",
                (hybrid_cutoff,),
            )
            report["hybrid_archived"] = cur2.rowcount
        except Exception as exc:
            logger.error(f"Hybrid retention hatası: {exc}")

        # ── 7. WAL Checkpoint + Vacuum ──
        total_deleted = sum(
            v for k, v in report.items()
            if k.endswith("_deleted") or k == "hybrid_archived"
        )
        if total_deleted > 0:
            self.wal_checkpoint()
            self.vacuum()
            logger.info(f"Retention sonrası WAL checkpoint + VACUUM tamamlandı")

        logger.info(f"Retention raporu: {report}")
        return report

    def get_table_sizes(self) -> dict[str, int]:
        """Tüm tabloların satır sayılarını döndür.

        Returns:
            Tablo adı → satır sayısı sözlüğü.
        """
        tables = [
            "bars", "trades", "strategies", "risk_snapshots", "events",
            "top5_history", "config_history", "manual_interventions",
            "liquidity_classes", "app_state", "hybrid_positions",
            "hybrid_events", "daily_risk_summary", "weekly_top5_summary",
            "notifications",
        ]
        sizes = {}
        for t in tables:
            try:
                row = self._fetch_one(f"SELECT COUNT(*) AS cnt FROM {t}")
                sizes[t] = row["cnt"] if row else 0
            except Exception:
                sizes[t] = -1
        return sizes

    # ═════════════════════════════════════════════════════════════════
    #  BİLDİRİMLER
    # ═════════════════════════════════════════════════════════════════

    def insert_notification(
        self,
        notif_type: str,
        title: str,
        message: str,
        severity: str = "info",
        details: str = "{}",
    ) -> int:
        """Bildirim kaydet.

        Args:
            notif_type: Bildirim tipi (hybrid_eod, hybrid_daily_reset, vb.).
            title: Başlık.
            message: Mesaj.
            severity: info / warning / error / critical.
            details: JSON detay.

        Returns:
            Oluşturulan satırın id'si.
        """
        cur = self._execute(
            """INSERT INTO notifications (timestamp, type, title, message, severity, read, details)
               VALUES (?,?,?,?,?,0,?)""",
            (self._now(), notif_type, title, message, severity, details),
        )
        return cur.lastrowid

    def get_notifications(self, limit: int = 50, unread_only: bool = False) -> list[dict[str, Any]]:
        """Bildirimleri getir (yeniden eskiye).

        Args:
            limit: Maksimum satır.
            unread_only: True ise sadece okunmamış.

        Returns:
            Bildirim sözlüklerinin listesi.
        """
        where = "WHERE read=0" if unread_only else ""
        return self._fetch_all(
            f"SELECT * FROM notifications {where} ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    def mark_notification_read(self, notif_id: int) -> None:
        """Bildirimi okundu olarak işaretle."""
        self._execute("UPDATE notifications SET read=1 WHERE id=?", (notif_id,))

    def mark_all_notifications_read(self) -> None:
        """Tüm bildirimleri okundu olarak işaretle."""
        self._execute("UPDATE notifications SET read=1 WHERE read=0")

    # ═════════════════════════════════════════════════════════════════
    #  HİBRİT PERFORMANS İSTATİSTİKLERİ
    # ═════════════════════════════════════════════════════════════════

    def get_hybrid_performance(self) -> dict[str, Any]:
        """Hibrit pozisyon performans istatistikleri.

        Returns:
            dict: Toplam, kazanan, kaybeden, ortalama PnL, kapanış nedeni dağılımı.
        """
        rows = self._fetch_all(
            "SELECT close_reason, pnl, swap FROM hybrid_positions WHERE state='CLOSED'",
        )
        if not rows:
            return {
                "total": 0, "winners": 0, "losers": 0,
                "total_pnl": 0.0, "avg_pnl": 0.0,
                "best_pnl": 0.0, "worst_pnl": 0.0,
                "win_rate": 0.0, "close_reasons": {},
            }

        total = len(rows)
        pnls = [r.get("pnl", 0.0) or 0.0 for r in rows]
        winners = sum(1 for p in pnls if p > 0)
        losers = sum(1 for p in pnls if p < 0)
        total_pnl = sum(pnls)
        avg_pnl = total_pnl / total if total > 0 else 0.0

        # Kapanış nedeni dağılımı
        reasons: dict[str, int] = {}
        for r in rows:
            reason = r.get("close_reason") or "UNKNOWN"
            reasons[reason] = reasons.get(reason, 0) + 1

        return {
            "total": total,
            "winners": winners,
            "losers": losers,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 2),
            "best_pnl": round(max(pnls), 2) if pnls else 0.0,
            "worst_pnl": round(min(pnls), 2) if pnls else 0.0,
            "win_rate": round(winners / total * 100, 1) if total > 0 else 0.0,
            "close_reasons": reasons,
        }

