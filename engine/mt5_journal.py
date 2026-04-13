"""
MT5 Journal Parser — v6.0.1

MT5 terminal günlük (Journal) kayıtlarını okur, veritabanına yazar
ve 3 günlük saklama politikası uygular.

MT5 log dosyaları konumu:
  <terminal_data_path>/logs/YYYYMMDD.log

Gerçek dosya formatı (UTF-16-LE, BOM ile):
  PO\t0\t08:54:32.238\tTerminal\tGCM MT5 Terminal x64 build 5738 started...
  DK\t0\t08:54:32.239\tTerminal\tWindows 11 build 26200, 16 x AMD Ryzen 7...
  GR\t1\t08:54:43.443\tNetwork\t'7023084': outdated server build...

Her satır: <2char_prefix>\t<severity>\t<HH:MM:SS.mmm>\t<Source>\t<Message>
Tarih dosya adından gelir (20260413.log → 2026-04-13).
"""

from __future__ import annotations

import os
import re
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.database import Database

logger = logging.getLogger("engine.mt5_journal")

# ── Log satır regex ──────────────────────────────────────────────────
# Gerçek format: "PO\t0\t08:54:32.238\tTerminal\tMessage..."
# Gruplar: (1) saat, (2) kaynak, (3) mesaj
_LINE_RE = re.compile(
    r"^[^\t]*\t"                               # 2-char prefix
    r"[^\t]*\t"                                # severity (0 veya 1)
    r"(\d{2}:\d{2}:\d{2}\.\d{3})"             # saat: 08:54:32.238
    r"\t"
    r"([^\t]+)"                                # kaynak: Terminal/Trades/Network/...
    r"\t"
    r"(.+)$"                                   # mesaj
)

# ── Saklama süresi ───────────────────────────────────────────────────
RETENTION_DAYS = 3


class MT5Journal:
    """MT5 terminal journal kayıtlarını yönetir."""

    def __init__(self, db: Database, mt5_data_path: str | None = None):
        self._db = db
        self._mt5_data_path = mt5_data_path
        self._logs_dir: str | None = None
        self._last_read_pos: dict[str, int] = {}  # dosya -> son okunan byte
        self._initialized = False

        if mt5_data_path:
            self._set_logs_dir(mt5_data_path)

    # ── Public API ───────────────────────────────────────────────────

    def set_terminal_path(self, data_path: str) -> None:
        """MT5 terminal data path ayarla (mt5.terminal_info().data_path'ten gelir)."""
        self._set_logs_dir(data_path)

    def sync(self) -> int:
        """MT5 log dosyalarını oku ve yeni satırları veritabanına yaz.
        Döndürür: eklenen satır sayısı.
        """
        if not self._logs_dir or not os.path.isdir(self._logs_dir):
            return 0

        total_inserted = 0

        # Son 3 günün log dosyalarını bul
        today = datetime.now()
        for day_offset in range(RETENTION_DAYS):
            target_date = today - timedelta(days=day_offset)
            log_file = os.path.join(
                self._logs_dir, f"{target_date.strftime('%Y%m%d')}.log"
            )
            if os.path.isfile(log_file):
                count = self._read_log_file(
                    log_file, target_date.strftime("%Y-%m-%d")
                )
                total_inserted += count

        # Eski kayıtları temizle
        self._cleanup_old_entries()

        return total_inserted

    def get_entries(
        self,
        date: str | None = None,
        source: str | None = None,
        search: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        """Veritabanından journal kayıtlarını getir."""
        conditions = []
        params: list = []

        if date:
            conditions.append("log_date = ?")
            params.append(date)

        if source:
            conditions.append("source = ?")
            params.append(source)

        if search:
            conditions.append("message LIKE ?")
            params.append(f"%{search}%")

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        sql = f"""
            SELECT id, timestamp, source, message, log_date
            FROM mt5_journal
            {where}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        rows = self._db._fetch_all(sql, params)
        if not rows:
            return []

        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "source": r["source"],
                "message": r["message"],
                "log_date": r["log_date"],
            }
            for r in rows
        ]

    def get_sources(self) -> list[str]:
        """Mevcut kaynak türlerini getir (Terminal, Trades, Network, vb.)."""
        rows = self._db._fetch_all(
            "SELECT DISTINCT source FROM mt5_journal ORDER BY source"
        )
        if not rows:
            return []
        return [r["source"] for r in rows]

    def get_dates(self) -> list[str]:
        """Mevcut log tarihlerini getir."""
        rows = self._db._fetch_all(
            "SELECT DISTINCT log_date FROM mt5_journal ORDER BY log_date DESC"
        )
        if not rows:
            return []
        return [r["log_date"] for r in rows]

    def get_stats(self) -> dict:
        """İstatistik bilgileri."""
        row = self._db._fetch_one(
            "SELECT COUNT(*) as total FROM mt5_journal"
        )
        total = row["total"] if row else 0

        row_today = self._db._fetch_one(
            "SELECT COUNT(*) as cnt FROM mt5_journal WHERE log_date = ?",
            [datetime.now().strftime("%Y-%m-%d")]
        )
        today_count = row_today["cnt"] if row_today else 0

        return {
            "total_entries": total,
            "today_entries": today_count,
            "logs_dir": self._logs_dir or "",
            "available_dates": self.get_dates(),
            "available_sources": self.get_sources(),
        }

    # ── Private ──────────────────────────────────────────────────────

    def _set_logs_dir(self, data_path: str) -> None:
        """Terminal data_path'ten logs dizinini belirle."""
        logs_dir = os.path.join(data_path, "logs")
        if os.path.isdir(logs_dir):
            self._logs_dir = logs_dir
            logger.info("MT5 Journal logs dizini: %s", logs_dir)
        else:
            logger.warning("MT5 Journal logs dizini bulunamadı: %s", logs_dir)

    def _read_log_file(self, filepath: str, log_date: str) -> int:
        """Tek bir log dosyasını oku, yeni satırları veritabanına ekle.

        Args:
            filepath: Log dosyası tam yolu (ör. .../logs/20260413.log)
            log_date: ISO tarih (ör. "2026-04-13") — dosya adından türetilmiş
        """
        file_key = os.path.basename(filepath)
        last_pos = self._last_read_pos.get(file_key, 0)

        try:
            file_size = os.path.getsize(filepath)
            if file_size <= last_pos:
                return 0  # Yeni veri yok

            entries = []
            with open(filepath, "r", encoding="utf-16-le", errors="replace") as f:
                if last_pos > 0:
                    f.seek(last_pos)
                else:
                    # BOM karakterini atla (ilk okumada)
                    first_char = f.read(1)
                    if first_char != "\ufeff":
                        f.seek(0)

                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    parsed = self._parse_line(line, log_date)
                    if parsed:
                        ts, source, message = parsed
                        entries.append((ts, source, message, log_date))

                new_pos = f.tell()

            if entries:
                self._batch_insert(entries)

            self._last_read_pos[file_key] = new_pos
            return len(entries)

        except Exception as e:
            logger.error("MT5 log okuma hatası (%s): %s", filepath, e)
            return 0

    def _parse_line(self, line: str, log_date: str) -> tuple[str, str, str] | None:
        """Tek bir log satırını parse et.

        Args:
            line: Ham log satırı (BOM ve boşluk temizlenmiş)
            log_date: ISO tarih (ör. "2026-04-13") — timestamp oluşturmak için

        Returns:
            (timestamp, source, message) veya None
        """
        m = _LINE_RE.match(line)
        if m:
            time_str = m.group(1).strip()    # 08:54:32.238
            source = m.group(2).strip()      # Terminal
            message = m.group(3).strip()     # mesaj
            # Tam ISO timestamp: 2026-04-13T08:54:32.238
            timestamp = f"{log_date}T{time_str}"
            return timestamp, source, message

        # Fallback: tab ile split dene
        parts = line.split("\t")
        if len(parts) >= 5:
            # Format: prefix \t severity \t time \t source \t message
            time_part = parts[2].strip()
            if re.match(r"\d{2}:\d{2}:\d{2}", time_part):
                source = parts[3].strip()
                message = "\t".join(parts[4:]).strip()
                if source and message:
                    timestamp = f"{log_date}T{time_part}"
                    return timestamp, source, message

        return None

    def _batch_insert(self, entries: list[tuple]) -> None:
        """Toplu kayıt ekle (duplicate kontrolü ile)."""
        if not entries:
            return

        sql = """
            INSERT OR IGNORE INTO mt5_journal (timestamp, source, message, log_date)
            VALUES (?, ?, ?, ?)
        """
        try:
            with self._db._lock:
                conn = self._db._conn
                conn.executemany(sql, entries)
                conn.commit()
        except Exception as e:
            logger.error("MT5 Journal batch insert hatası: %s", e)

    def _cleanup_old_entries(self) -> None:
        """3 günden eski kayıtları sil."""
        cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
        try:
            self._db._execute(
                "DELETE FROM mt5_journal WHERE log_date < ?", [cutoff]
            )
        except Exception as e:
            logger.error("MT5 Journal temizlik hatası: %s", e)
