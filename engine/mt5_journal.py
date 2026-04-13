"""
MT5 Journal Parser — v6.0

MT5 terminal günlük (Journal) kayıtlarını okur, veritabanına yazar
ve 3 günlük saklama politikası uygular.

MT5 log dosyaları konumu:
  <terminal_data_path>/logs/YYYYMMDD.log

Format:
  0	2026.04.13 16:40:20.263	Terminal	GCM MT5 Terminal x64 build 5738 started...

Her satır: <sekme_harfi>\t<tarih_saat>\t<kaynak>\t<mesaj>
"""

from __future__ import annotations

import os
import re
import glob
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.database import Database

logger = logging.getLogger("engine.mt5_journal")

# ── Log satır regex ──────────────────────────────────────────────────
# Örnek: "0\t2026.04.13 16:40:20.263\tTerminal\tGCM MT5 Terminal..."
# Bazen satır başında karakter olmayabilir, esnek parse
_LINE_RE = re.compile(
    r"^[^\t]*?\t?"                          # opsiyonel prefix
    r"(\d{4}\.\d{2}\.\d{2}\s+"             # tarih: 2026.04.13
    r"\d{2}:\d{2}:\d{2}\.\d{3})"           # saat: 16:40:20.263
    r"\t"
    r"(\w+)"                                # kaynak: Terminal/Trades/Network/...
    r"\t"
    r"(.+)$"                                # mesaj
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
                count = self._read_log_file(log_file, target_date.strftime("%Y-%m-%d"))
                total_inserted += count

        # Eski kayıtları temizle
        self._cleanup_old_entries()

        if total_inserted > 0:
            logger.info("MT5 Journal sync: %d yeni kayıt eklendi", total_inserted)

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
        # mt5.terminal_info().data_path -> C:\Users\pc\AppData\Roaming\MetaQuotes\Terminal\<ID>
        logs_dir = os.path.join(data_path, "logs")
        if os.path.isdir(logs_dir):
            self._logs_dir = logs_dir
            logger.info("MT5 Journal logs dizini: %s", logs_dir)
        else:
            # Fallback: bilinen GCM terminal dizini
            fallback = r"C:\Users\pc\AppData\Roaming\MetaQuotes\Terminal"
            if os.path.isdir(fallback):
                # İlk bulunan terminal dizinini kullan
                for entry in os.listdir(fallback):
                    candidate = os.path.join(fallback, entry, "logs")
                    if os.path.isdir(candidate) and len(entry) > 20:
                        self._logs_dir = candidate
                        logger.info("MT5 Journal logs dizini (fallback): %s", candidate)
                        break

            if not self._logs_dir:
                logger.warning("MT5 Journal logs dizini bulunamadı: %s", logs_dir)

    def _read_log_file(self, filepath: str, log_date: str) -> int:
        """Tek bir log dosyasını oku, yeni satırları veritabanına ekle."""
        file_key = os.path.basename(filepath)
        last_pos = self._last_read_pos.get(file_key, 0)

        try:
            file_size = os.path.getsize(filepath)
            if file_size <= last_pos:
                return 0  # Yeni veri yok

            entries = []
            with open(filepath, "r", encoding="utf-16-le", errors="replace") as f:
                f.seek(last_pos)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    parsed = self._parse_line(line)
                    if parsed:
                        ts, source, message = parsed
                        # ISO formatına çevir: 2026.04.13 16:40:20.263 -> 2026-04-13T16:40:20.263
                        iso_ts = ts.replace(".", "-", 2).replace(" ", "T", 1)
                        entries.append((iso_ts, source, message, log_date))

                new_pos = f.tell()

            if entries:
                self._batch_insert(entries)

            self._last_read_pos[file_key] = new_pos
            return len(entries)

        except Exception as e:
            logger.error("MT5 log okuma hatası (%s): %s", filepath, e)
            return 0

    def _parse_line(self, line: str) -> tuple[str, str, str] | None:
        """Tek bir log satırını parse et."""
        m = _LINE_RE.match(line)
        if m:
            return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()

        # Alternatif: tab ile split dene
        parts = line.split("\t")
        if len(parts) >= 3:
            # İlk tab'dan sonra tarih, sonra kaynak, sonra mesaj
            for i, part in enumerate(parts):
                if re.match(r"\d{4}\.\d{2}\.\d{2}", part.strip()):
                    ts = parts[i].strip()
                    source = parts[i + 1].strip() if i + 1 < len(parts) else ""
                    message = "\t".join(parts[i + 2:]).strip() if i + 2 < len(parts) else ""
                    if ts and message:
                        return ts, source, message
                    break

        return None

    def _batch_insert(self, entries: list[tuple]) -> None:
        """Toplu kayıt ekle (duplicate kontrolü ile)."""
        if not entries:
            return

        # Mevcut son timestamp'i al — sadece yenileri ekle
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
