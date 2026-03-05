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
import sqlite3
import threading
from datetime import datetime, date
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
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._create_tables()
        logger.info(f"Veritabanı hazır: {self._db_path}")

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

    def close(self) -> None:
        """Bağlantıyı kapat."""
        with self._lock:
            self._conn.close()
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
            (symbol, timeframe, str(r[ts_col]),
             r["open"], r["high"], r["low"], r["close"], r[vol_col])
            for _, r in df.iterrows()
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
                commission, swap, regime, fake_score, exit_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trade["strategy"], trade["symbol"], trade["direction"],
                trade.get("entry_time"), trade.get("exit_time"),
                trade.get("entry_price"), trade.get("exit_price"),
                trade["lot"],
                trade.get("pnl"), trade.get("slippage"),
                trade.get("commission"), trade.get("swap"),
                trade.get("regime"), trade.get("fake_score"),
                trade.get("exit_reason"),
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
                    # MT5 verisiyle commission/swap/pnl güncelle (eksikse veya her zaman)
                    self._execute(
                        """UPDATE trades SET pnl=?, commission=?, swap=?,
                           exit_time=COALESCE(exit_time, ?), exit_price=COALESCE(exit_price, ?)
                           WHERE id=?""",
                        (
                            t.get("pnl"), t.get("commission"), t.get("swap"),
                            t.get("exit_time"), t.get("exit_price"),
                            existing["id"],
                        ),
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
                )
                updated += 1
                logger.debug(
                    f"Sync: OĞUL kaydı güncellendi id={ogul_match['id']} "
                    f"→ mt5_position_id={pos_id}"
                )
            else:
                # 3) Yeni kayıt ekle
                self._execute(
                    """INSERT INTO trades
                       (strategy, symbol, direction, entry_time, exit_time,
                        entry_price, exit_price, lot, pnl, slippage,
                        commission, swap, regime, fake_score, exit_reason,
                        mt5_position_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        t.get("strategy", "manual"),
                        t["symbol"], t["direction"],
                        t.get("entry_time"), t.get("exit_time"),
                        t.get("entry_price"), t.get("exit_price"),
                        t["lot"], t.get("pnl"), t.get("slippage"),
                        t.get("commission"), t.get("swap"),
                        t.get("regime"), t.get("fake_score"),
                        t.get("exit_reason"), pos_id,
                    ),
                )
                added += 1

        if added or updated:
            logger.info(
                f"MT5 sync: {added} yeni eklendi, "
                f"{updated} mevcut kayıt güncellendi"
            )
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
    ) -> list[dict[str, Any]]:
        """İşlem listesi getir (filtreli).

        Args:
            symbol: Filtre: kontrat sembolü.
            strategy: Filtre: strateji adı.
            since: Filtre: bu tarihten sonra (YYYY-MM-DD). entry_time bazlı.
            limit: Maksimum satır.
            closed_only: True ise yalnızca kapanmış işlemler (exit_time dolu).
                         False ise açık/kapanmamış kayıtlar da dahil.

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

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        order = "exit_time DESC, id DESC" if closed_only else "exit_time IS NULL DESC, exit_time DESC, id DESC"
        return self._fetch_all(
            f"SELECT * FROM trades {where} ORDER BY {order} LIMIT ?",
            tuple(params),
        )

    def delete_trade(self, trade_id: int) -> bool:
        """İşlem kaydını sil.

        Args:
            trade_id: Silinecek işlem id'si.

        Returns:
            Silme başarılıysa True.
        """
        cur = self._execute("DELETE FROM trades WHERE id=?", (trade_id,))
        logger.debug(f"Trade delete id={trade_id}: rowcount={cur.rowcount}")
        return cur.rowcount > 0

    # ═════════════════════════════════════════════════════════════════
    #  STRATEGIES
    # ═════════════════════════════════════════════════════════════════
    def insert_strategy(
        self,
        name: str,
        signal_type: str,
        parameters: dict | None = None,
        status: str = "active",
    ) -> int:
        """Yeni strateji ekle.

        Args:
            name: Strateji adı (unique).
            signal_type: Sinyal tipi (ör. "ema_cross", "macd").
            parameters: Strateji parametreleri (JSON olarak saklanır).
            status: Durum ("active" / "paused" / "disabled").

        Returns:
            Oluşturulan satırın id'si.
        """
        cur = self._execute(
            """INSERT INTO strategies (name, signal_type, parameters, status, metrics)
               VALUES (?, ?, ?, ?, '{}')""",
            (name, signal_type, json.dumps(parameters or {}), status),
        )
        logger.debug(f"Strategy insert id={cur.lastrowid}: {name}")
        return cur.lastrowid

    def update_strategy(self, strategy_id: int, fields: dict[str, Any]) -> bool:
        """Strateji güncelle.

        ``parameters`` veya ``metrics`` alanı dict ise otomatik JSON'a çevrilir.

        Args:
            strategy_id: Strateji id'si.
            fields: Güncellenecek alan-değer çiftleri.

        Returns:
            Güncelleme başarılıysa True.
        """
        if not fields:
            return False
        for key in ("parameters", "metrics"):
            if key in fields and isinstance(fields[key], dict):
                fields[key] = json.dumps(fields[key])
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = tuple(fields.values()) + (strategy_id,)
        cur = self._execute(
            f"UPDATE strategies SET {set_clause} WHERE id=?", values
        )
        logger.debug(f"Strategy update id={strategy_id}: {list(fields.keys())}")
        return cur.rowcount > 0

    def get_strategy(self, name: str) -> dict[str, Any] | None:
        """İsme göre strateji getir.

        Args:
            name: Strateji adı.

        Returns:
            Strateji sözlüğü (parameters/metrics JSON-parse'lı) veya None.
        """
        row = self._fetch_one("SELECT * FROM strategies WHERE name=?", (name,))
        if row:
            row["parameters"] = json.loads(row.get("parameters") or "{}")
            row["metrics"] = json.loads(row.get("metrics") or "{}")
        return row

    def get_strategies(self, status: str | None = None) -> list[dict[str, Any]]:
        """Tüm stratejileri getir.

        Args:
            status: Filtre: durum ("active", "paused", "disabled").

        Returns:
            Strateji sözlüklerinin listesi.
        """
        if status:
            rows = self._fetch_all(
                "SELECT * FROM strategies WHERE status=?", (status,)
            )
        else:
            rows = self._fetch_all("SELECT * FROM strategies")
        for r in rows:
            r["parameters"] = json.loads(r.get("parameters") or "{}")
            r["metrics"] = json.loads(r.get("metrics") or "{}")
        return rows

    def delete_strategy(self, strategy_id: int) -> bool:
        """Strateji sil.

        Args:
            strategy_id: Silinecek strateji id'si.

        Returns:
            Silme başarılıysa True.
        """
        cur = self._execute("DELETE FROM strategies WHERE id=?", (strategy_id,))
        logger.debug(f"Strategy delete id={strategy_id}: rowcount={cur.rowcount}")
        return cur.rowcount > 0

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
                snap["equity"], snap["floating_pnl"], snap["daily_pnl"],
                positions or "[]",
                snap.get("regime"), snap.get("drawdown"), snap.get("margin_usage"),
                snap.get("balance", 0.0),
            ),
        )
        logger.debug(f"Risk snapshot kaydedildi: equity={snap['equity']:.2f}")

    def get_risk_snapshots(
        self,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Risk görüntülerini getir.

        Args:
            since: Başlangıç timestamp (ISO-8601).
            limit: Maksimum satır.

        Returns:
            Risk snapshot sözlüklerinin listesi.
        """
        if since:
            rows = self._fetch_all(
                """SELECT * FROM risk_snapshots
                   WHERE timestamp>=? ORDER BY timestamp DESC LIMIT ?""",
                (since, limit),
            )
        else:
            rows = self._fetch_all(
                "SELECT * FROM risk_snapshots ORDER BY timestamp DESC LIMIT ?",
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
    def insert_event(
        self,
        event_type: str,
        message: str,
        severity: str = "INFO",
        action: str | None = None,
    ) -> int:
        """Sistem olayı kaydet.

        Args:
            event_type: Olay tipi (ör. "TRADE", "RISK", "SYSTEM", "ERROR").
            message: Olay mesajı.
            severity: Önem derecesi ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL").
            action: Yapılan/önerilen aksiyon.

        Returns:
            Oluşturulan satırın id'si.
        """
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

    def delete_top5(self, before_date: str) -> int:
        """Eski Top-5 kayıtlarını sil.

        Args:
            before_date: Bu tarihten önceki kayıtları sil (YYYY-MM-DD).

        Returns:
            Silinen satır sayısı.
        """
        cur = self._execute(
            "DELETE FROM top5_history WHERE date<?", (before_date,)
        )
        logger.debug(f"Top5 delete <{before_date}: {cur.rowcount}")
        return cur.rowcount

    # ═════════════════════════════════════════════════════════════════
    #  CONFIG HISTORY
    # ═════════════════════════════════════════════════════════════════
    def insert_config_change(
        self,
        param: str,
        old_value: Any,
        new_value: Any,
        changed_by: str = "system",
    ) -> int:
        """Konfigürasyon değişiklik kaydı ekle.

        Args:
            param: Değişen parametre adı.
            old_value: Eski değer.
            new_value: Yeni değer.
            changed_by: Değişikliği yapan ("system", "user", "baba" vb.).

        Returns:
            Oluşturulan satırın id'si.
        """
        cur = self._execute(
            """INSERT INTO config_history
               (timestamp, param, old_value, new_value, changed_by)
               VALUES (?,?,?,?,?)""",
            (self._now(), param, str(old_value), str(new_value), changed_by),
        )
        logger.debug(f"Config değişikliği: {param} {old_value}→{new_value} by {changed_by}")
        return cur.lastrowid

    def get_config_history(
        self,
        param: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Konfigürasyon değişiklik geçmişini getir.

        Args:
            param: Filtre: parametre adı.
            limit: Maksimum satır.

        Returns:
            Config değişiklik sözlüklerinin listesi.
        """
        if param:
            return self._fetch_all(
                """SELECT * FROM config_history
                   WHERE param=? ORDER BY id DESC LIMIT ?""",
                (param, limit),
            )
        return self._fetch_all(
            "SELECT * FROM config_history ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    def delete_config_history(self, before: str) -> int:
        """Eski konfigürasyon kayıtlarını sil.

        Args:
            before: Bu tarihten önceki kayıtları sil (ISO-8601).

        Returns:
            Silinen satır sayısı.
        """
        cur = self._execute(
            "DELETE FROM config_history WHERE timestamp<?", (before,)
        )
        return cur.rowcount

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

    def get_interventions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Manuel müdahale geçmişini getir.

        Args:
            limit: Maksimum satır.

        Returns:
            Müdahale sözlüklerinin listesi.
        """
        return self._fetch_all(
            "SELECT * FROM manual_interventions ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    def delete_interventions(self, before: str) -> int:
        """Eski müdahale kayıtlarını sil.

        Args:
            before: Bu tarihten önceki kayıtları sil (ISO-8601).

        Returns:
            Silinen satır sayısı.
        """
        cur = self._execute(
            "DELETE FROM manual_interventions WHERE timestamp<?", (before,)
        )
        return cur.rowcount

    # ═════════════════════════════════════════════════════════════════
    #  LIQUIDITY CLASSES
    # ═════════════════════════════════════════════════════════════════
    def insert_liquidity(self, entries: list[dict[str, Any]]) -> None:
        """Günlük likidite sınıflandırması kaydet.

        Args:
            entries: Her biri → date, symbol, avg_volume, avg_spread, class
                     içeren sözlük listesi.
        """
        rows = [
            (
                e["date"], e["symbol"],
                e.get("avg_volume"), e.get("avg_spread"), e.get("class"),
            )
            for e in entries
        ]
        self._executemany(
            """INSERT OR REPLACE INTO liquidity_classes
               (date, symbol, avg_volume, avg_spread, class)
               VALUES (?,?,?,?,?)""",
            rows,
        )
        logger.debug(f"Likidite sınıfları kaydedildi: {len(rows)} sembol")

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

    def delete_liquidity(self, before_date: str) -> int:
        """Eski likidite kayıtlarını sil.

        Args:
            before_date: Bu tarihten önceki kayıtları sil (YYYY-MM-DD).

        Returns:
            Silinen satır sayısı.
        """
        cur = self._execute(
            "DELETE FROM liquidity_classes WHERE date<?", (before_date,)
        )
        logger.debug(f"Liquidity delete <{before_date}: {cur.rowcount}")
        return cur.rowcount

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
        cur = self._execute(
            """INSERT INTO hybrid_positions
               (ticket, symbol, direction, volume, entry_price, entry_atr,
                initial_sl, initial_tp, current_sl, current_tp,
                state, breakeven_hit, trailing_active, transferred_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["ticket"], data["symbol"], data["direction"],
                data["volume"], data["entry_price"], data["entry_atr"],
                data["initial_sl"], data["initial_tp"],
                data.get("current_sl", data["initial_sl"]),
                data.get("current_tp", data["initial_tp"]),
                "ACTIVE", 0, 0, self._now(),
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
    #  YARDIMCI
    # ═════════════════════════════════════════════════════════════════
    def get_watched_symbols(self) -> list[str]:
        """İzlenen kontrat sembollerini getir.

        Returns:
            Sembol listesi (mt5_bridge.WATCHED_SYMBOLS).
        """
        from engine.mt5_bridge import WATCHED_SYMBOLS
        return list(WATCHED_SYMBOLS)

    def table_counts(self) -> dict[str, int]:
        """Her tablodaki satır sayısını getir (debug/monitoring).

        Returns:
            Tablo adı → satır sayısı sözlüğü.
        """
        tables = [
            "bars", "trades", "strategies", "risk_snapshots",
            "events", "top5_history", "config_history",
            "manual_interventions", "liquidity_classes",
        ]
        counts: dict[str, int] = {}
        for t in tables:
            row = self._fetch_one(f"SELECT COUNT(*) as cnt FROM {t}")
            counts[t] = row["cnt"] if row else 0
        return counts
