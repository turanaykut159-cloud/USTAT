"""ÜSTAT v5.7 — Hata Takip Motoru (Error Tracker).

Mevcut events tablosunu kullanarak hata agregasyonu, gruplama,
trend analizi ve dashboard istatistikleri sağlar.

Özellikler:
    - Hata gruplama (aynı tip + mesaj → tek grup)
    - Zaman bazlı trend (saatlik, günlük)
    - Kategori bazlı dağılım
    - Canlı hata sayaçları (bellek içi)
    - Çözümleme takibi (resolved/unresolved)

Kullanım:
    tracker = ErrorTracker(db)
    tracker.record_error("MT5_DISCONNECT", "Bağlantı koptu", severity="ERROR")
    summary = tracker.get_summary()
    trends = tracker.get_trends(hours=24)
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("ustat.error_tracker")


# ── Hata kategorileri ──
ERROR_CATEGORIES = {
    "MT5_DISCONNECT": "bağlantı",
    "MT5_RECONNECT": "bağlantı",
    "MT5_TIMEOUT": "bağlantı",
    "ORDER_REJECT": "emir",
    "ORDER_TIMEOUT": "emir",
    "ORDER_FILL_PARTIAL": "emir",
    "SLTP_MODIFY_FAIL": "emir",
    # Widget Denetimi A14 (B17) — TRADE_ERROR ve MANUAL_TRADE_ERROR
    # ogul.py::_execute_signal (send_order fail, orphan) ve
    # manuel_motor.py::execute_manual_trade (MT5 reject) bu tipleri emit ediyor.
    # Önceden "diğer" kategorisine düşüyordu; "emir" doğru kategoridir.
    "TRADE_ERROR": "emir",
    "MANUAL_TRADE_ERROR": "emir",
    "KILL_SWITCH": "risk",
    "DRAWDOWN_LIMIT": "risk",
    "RISK_LIMIT": "risk",
    "FLOATING_LIMIT": "risk",
    "COOLDOWN": "risk",
    "EARLY_WARNING": "risk",
    "FAKE_SIGNAL": "sinyal",
    "SIGNAL_REJECTED": "sinyal",
    "NETTING_MISMATCH": "netting",
    "VOLUME_MISMATCH": "netting",
    "EXTERNAL_CLOSE": "netting",
    "DATA_ANOMALY": "veri",
    "DATA_STALE": "veri",
    "DB_ERROR": "sistem",
    "CYCLE_OVERRUN": "sistem",
    "IPC_ERROR": "sistem",
    "UNKNOWN": "diğer",
}

# Severity → renk + öncelik
SEVERITY_PRIORITY = {
    "CRITICAL": 4,
    "ERROR": 3,
    "WARNING": 2,
    "INFO": 1,
    "DEBUG": 0,
}


class ErrorGroup:
    """Aynı tip + benzer mesajlı hataları gruplar."""

    __slots__ = (
        "error_type", "category", "severity", "first_seen", "last_seen",
        "count", "message", "resolved", "resolved_at", "resolved_by",
        "event_ids",
    )

    def __init__(
        self,
        error_type: str,
        message: str,
        severity: str = "ERROR",
        event_id: int = 0,
    ):
        self.error_type = error_type
        self.category = ERROR_CATEGORIES.get(error_type, "diğer")
        self.severity = severity
        self.message = message
        self.first_seen = datetime.now()
        self.last_seen = datetime.now()
        self.count = 1
        self.resolved = False
        self.resolved_at: datetime | None = None
        self.resolved_by: str = ""
        self.event_ids: list[int] = [event_id] if event_id else []

    def bump(self, event_id: int = 0) -> None:
        """Aynı hata tekrar oluştu."""
        self.count += 1
        self.last_seen = datetime.now()
        if event_id:
            self.event_ids.append(event_id)
        # Çözümlenmişse tekrar açılır
        if self.resolved:
            self.resolved = False
            self.resolved_at = None

    def resolve(self, by: str = "operator") -> None:
        """Hata çözümlendi olarak işaretle."""
        self.resolved = True
        self.resolved_at = datetime.now()
        self.resolved_by = by

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "count": self.count,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "event_count": len(self.event_ids),
        }


class ErrorTracker:
    """Hata takip ve analiz motoru."""

    def __init__(self, db=None):
        self._db = db
        self._lock = threading.Lock()

        # Bellek içi gruplar: key = "error_type::message_prefix"
        self._groups: dict[str, ErrorGroup] = {}

        # Canlı sayaçlar (son 24 saat, saat bazlı)
        self._hourly_counts: dict[str, int] = defaultdict(int)
        self._daily_counts: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

        # Toplam sayaçlar
        self._total_errors = 0
        self._total_warnings = 0
        self._total_critical = 0

        # ── Widget Denetimi A15 (B18) — Çözümleme granülaritesi ────
        # İki seviyeli bastırma:
        #   _resolved_types: message_prefix BOŞ iken çözümlenen tüm tip
        #     (wildcard). resolve_all ve message_prefix=='' ile resolve_group
        #     çağrıldığında kullanılır.
        #   _resolved_keys: (error_type, message[:80]) çifti bazlı spesifik
        #     bastırma. Frontend "Çözümle" butonu mesaj bazlı prefix gönderdiği
        #     için kullanıcı tek satırı çözümlese aynı tipin farklı mesajlı
        #     satırları görünmeye devam eder. Bu A15'in kök fix'i.
        # Eski davranış: sadece _resolved_types vardı — aynı tipin tüm
        # mesajları sessizce bastırılıyordu (audit bulgusu B18). Artık
        # resolve_group(type, prefix) spesifik, resolve_group(type, '') veya
        # resolve_all wildcard.
        self._resolved_types: set[str] = set()
        self._resolved_keys: set[tuple[str, str]] = set()

        # DB tabloları + mevcut hataları yükle
        if db:
            self._ensure_resolution_table()
            self._load_resolved_types()
            self._load_from_db()
            self._apply_resolutions()

    def _group_key(self, error_type: str, message: str) -> str:
        """Hata gruplama anahtarı: tip + mesajın ilk 80 karakteri."""
        prefix = message[:80].strip() if message else ""
        return f"{error_type}::{prefix}"

    def _hour_key(self, dt: datetime | None = None) -> str:
        """Saat bazlı anahtar: 2026-03-13T14"""
        if dt is None:
            dt = datetime.now()
        return dt.strftime("%Y-%m-%dT%H")

    def _day_key(self, dt: datetime | None = None) -> str:
        """Gün bazlı anahtar: 2026-03-13"""
        if dt is None:
            dt = datetime.now()
        return dt.strftime("%Y-%m-%d")

    # ── Yükleme ──

    def _load_from_db(self) -> None:
        """DB'deki son 7 günlük hataları belleğe yükle.

        Çözümlenmiş tipleri (_resolved_types) atlar — dashboard'da göstermez.
        """
        try:
            rows = self._db.get_events(severity="WARNING", limit=500)
            rows += self._db.get_events(severity="ERROR", limit=500)
            rows += self._db.get_events(severity="CRITICAL", limit=500)

            for r in rows:
                etype = r.get("type", "UNKNOWN")
                msg = r.get("message", "")
                sev = r.get("severity", "ERROR")
                eid = r.get("id", 0)
                ts_str = r.get("timestamp", "")

                with self._lock:
                    # Sayaçları her zaman güncelle (trend için)
                    if sev == "CRITICAL":
                        self._total_critical += 1
                    elif sev == "ERROR":
                        self._total_errors += 1
                    elif sev == "WARNING":
                        self._total_warnings += 1

                    if ts_str:
                        try:
                            dt = datetime.fromisoformat(ts_str)
                            self._hourly_counts[self._hour_key(dt)] += 1
                            self._daily_counts[self._day_key(dt)][sev] += 1
                        except ValueError:
                            pass

                    # Çözümlenmiş tip ise gruplara EKLEME
                    # NOT: CRITICAL ve ERROR seviyesi asla bastırılmaz
                    # Widget Denetimi A15 (B18): İki seviyeli bastırma:
                    #   wildcard (_resolved_types) veya spesifik (_resolved_keys)
                    msg_prefix_load = msg[:80].strip() if msg else ""
                    if (
                        (
                            etype in self._resolved_types
                            or (etype, msg_prefix_load) in self._resolved_keys
                        )
                        and sev not in ("CRITICAL", "ERROR")
                    ):
                        continue

                    key = self._group_key(etype, msg)
                    if key in self._groups:
                        self._groups[key].bump(eid)
                    else:
                        g = ErrorGroup(etype, msg, sev, eid)
                        if ts_str:
                            try:
                                g.first_seen = datetime.fromisoformat(ts_str)
                                g.last_seen = g.first_seen
                            except ValueError:
                                pass
                        self._groups[key] = g

            logger.info(
                f"ErrorTracker: DB'den {len(self._groups)} hata grubu yüklendi "
                f"({len(self._resolved_types)} tip bastırıldı) "
                f"(E={self._total_errors} W={self._total_warnings} C={self._total_critical})"
            )
        except Exception as exc:
            logger.warning(f"ErrorTracker DB yükleme hatası: {exc}")

    # ── Kayıt ──

    def record_error(
        self,
        error_type: str,
        message: str,
        severity: str = "ERROR",
        action: str | None = None,
    ) -> int:
        """Yeni hata kaydet — DB'ye yaz + bellekte grupla.

        Çözümlenmiş hata tipleri dashboard'da gösterilmez ama
        DB'ye loglama amaçlı yazılır.

        Returns:
            DB event id.
        """
        event_id = 0

        # Çözümlenmiş tip ise → DB'ye yaz ama dashboard'a ekleme
        # NOT: CRITICAL ve ERROR seviyesi asla bastırılmaz (risk olayları görünmeli)
        # Widget Denetimi A15 (B18): İki seviyeli bastırma kontrolü:
        #   - error_type _resolved_types içinde (wildcard) → bastır
        #   - (error_type, message[:80]) _resolved_keys içinde (spesifik) → bastır
        prefix_for_check = message[:80].strip() if message else ""
        is_suppressed = (
            (
                error_type in self._resolved_types
                or (error_type, prefix_for_check) in self._resolved_keys
            )
            and severity not in ("CRITICAL", "ERROR")
        )

        # DB'ye yaz (her zaman — loglama için)
        if self._db:
            try:
                event_id = self._db.insert_event(
                    event_type=error_type,
                    message=message,
                    severity=severity,
                    action=action,
                )
            except Exception as exc:
                logger.error(f"Hata kaydı DB yazma hatası: {exc}")

        now = datetime.now()

        with self._lock:
            # Sayaçlar (her zaman güncelle — trend için)
            if severity == "CRITICAL":
                self._total_critical += 1
            elif severity == "ERROR":
                self._total_errors += 1
            elif severity == "WARNING":
                self._total_warnings += 1

            self._hourly_counts[self._hour_key(now)] += 1
            self._daily_counts[self._day_key(now)][severity] += 1

            # Çözümlenmiş tip ise dashboard grubuna EKLEME
            if is_suppressed:
                return event_id

            # Bellek gruplama (sadece çözümlenmemiş tipler)
            key = self._group_key(error_type, message)
            if key in self._groups:
                self._groups[key].bump(event_id)
            else:
                self._groups[key] = ErrorGroup(error_type, message, severity, event_id)

        return event_id

    # ── Çözümleme (DB kalıcı) ──

    def _load_resolved_types(self) -> None:
        """DB'den çözümlenmiş hata tiplerini + (tip, prefix) çiftlerini belleğe yükle.

        Widget Denetimi A15 (B18): Eski davranış sadece error_type bazlı
        bir set döndürüyordu. Artık iki seviyeli:
          - message_prefix == ''    → wildcard → _resolved_types'a ekle
          - message_prefix != ''    → spesifik → _resolved_keys'e ekle
        """
        resolutions = self._load_resolutions()
        self._resolved_types = set()
        self._resolved_keys = set()
        for (etype, prefix), _res in resolutions.items():
            if prefix:
                self._resolved_keys.add((etype, prefix))
            else:
                self._resolved_types.add(etype)
        total = len(self._resolved_types) + len(self._resolved_keys)
        if total:
            logger.info(
                f"ErrorTracker: {len(self._resolved_types)} wildcard tip + "
                f"{len(self._resolved_keys)} spesifik (tip, prefix) yüklendi"
            )

    def _ensure_resolution_table(self) -> None:
        """error_resolutions tablosunu oluştur (yoksa) + A15 göçü.

        Widget Denetimi A15 (B18): Eski şema (error_type TEXT PRIMARY KEY)
        message_prefix kolonu içermiyordu. Yeni şema:

            error_resolutions(
                error_type      TEXT NOT NULL,
                message_prefix  TEXT NOT NULL DEFAULT '',
                resolved_at     TEXT NOT NULL,
                resolved_by     TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (error_type, message_prefix)
            )

        Göç mantığı:
          1. Tablo yoksa → yeni şema ile oluştur (normal path)
          2. Varsa ve message_prefix kolonu eksikse → rebuild:
             rename old → create new → copy (prefix='') → drop old
          3. Varsa ve message_prefix kolonu mevcutsa → no-op
        """
        if not self._db:
            return
        try:
            # Tablo varlığını kontrol et
            rows = self._db._fetch_all(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='error_resolutions'"
            )
            table_exists = bool(rows)

            if not table_exists:
                self._db._execute(
                    """CREATE TABLE error_resolutions (
                           error_type      TEXT NOT NULL,
                           message_prefix  TEXT NOT NULL DEFAULT '',
                           resolved_at     TEXT NOT NULL,
                           resolved_by     TEXT NOT NULL DEFAULT '',
                           PRIMARY KEY (error_type, message_prefix)
                       )""",
                    (),
                )
                logger.info("error_resolutions tablosu oluşturuldu (A15 şeması).")
                return

            # Kolon listesi
            col_rows = self._db._fetch_all("PRAGMA table_info(error_resolutions)")
            col_names = {r["name"] for r in col_rows}

            if "message_prefix" in col_names:
                return  # Zaten yeni şema

            # A15 göçü — eski şemayı yeni şemaya taşı
            logger.info("error_resolutions A15 göçü başlıyor...")
            self._db._execute(
                "ALTER TABLE error_resolutions RENAME TO error_resolutions_old",
                (),
            )
            self._db._execute(
                """CREATE TABLE error_resolutions (
                       error_type      TEXT NOT NULL,
                       message_prefix  TEXT NOT NULL DEFAULT '',
                       resolved_at     TEXT NOT NULL,
                       resolved_by     TEXT NOT NULL DEFAULT '',
                       PRIMARY KEY (error_type, message_prefix)
                   )""",
                (),
            )
            self._db._execute(
                """INSERT INTO error_resolutions
                   (error_type, message_prefix, resolved_at, resolved_by)
                   SELECT error_type, '', resolved_at, resolved_by
                   FROM error_resolutions_old""",
                (),
            )
            self._db._execute("DROP TABLE error_resolutions_old", ())
            logger.info("error_resolutions A15 göçü tamamlandı.")
        except Exception as exc:
            logger.warning(f"error_resolutions tablo/göç hatası: {exc}")

    def _load_resolutions(self) -> dict[tuple[str, str], dict]:
        """DB'den çözümleme kayıtlarını oku. Anahtar (error_type, message_prefix) tuple.

        Widget Denetimi A15 (B18): Eski dönüş dict[str, dict] (sadece tip)
        idi; şimdi dict[tuple[str, str], dict] (tip + prefix).
        """
        if not self._db:
            return {}
        try:
            rows = self._db._fetch_all(
                "SELECT error_type, message_prefix, resolved_at, resolved_by "
                "FROM error_resolutions"
            )
            return {(r["error_type"], r.get("message_prefix", "") or ""): r for r in rows}
        except Exception:
            return {}

    def _apply_resolutions(self) -> None:
        """DB'deki çözümleme kayıtlarını bellek gruplarına uygula.

        Widget Denetimi A15 (B18): İki seviyeli eşleştirme:
          - (error_type, prefix) spesifik çözümleme: SADECE aynı grup
          - (error_type, '') wildcard çözümleme: tip altındaki tüm gruplar
        """
        resolutions = self._load_resolutions()
        if not resolutions:
            return
        # Wildcard ve spesifik ayrıştırma
        wildcards = {etype: res for (etype, p), res in resolutions.items() if not p}
        specifics = {(etype, p): res for (etype, p), res in resolutions.items() if p}
        with self._lock:
            for key, group in self._groups.items():
                # Grup key formatı: "error_type::prefix"
                g_prefix = key.split("::", 1)[1] if "::" in key else ""
                res = specifics.get((group.error_type, g_prefix))
                if res is None:
                    res = wildcards.get(group.error_type)
                if res:
                    res_time = res["resolved_at"]
                    if group.last_seen.isoformat() <= res_time:
                        group.resolved = True
                        group.resolved_at = datetime.fromisoformat(res_time)
                        group.resolved_by = res.get("resolved_by", "")

    def resolve_group(self, error_type: str, message_prefix: str = "", by: str = "operator") -> bool:
        """Hata grubunu çözümlendi olarak işaretle — DB'ye kalıcı yaz + eski event'leri sil.

        Widget Denetimi A15 (B18): İki davranış modu:
          - message_prefix BOŞ → wildcard: aynı tipin TÜM gruplarını çözümler;
            (error_type, '') satırı DB'ye yazılır; _resolved_types'a eklenir.
          - message_prefix DOLU → spesifik: SADECE (error_type, prefix[:80])
            eşleşen grup çözümlenir; (error_type, prefix[:80]) DB'ye yazılır;
            _resolved_keys'e eklenir. Aynı tipin farklı mesajlı satırları
            görünmeye devam eder.

        Eski davranış: prefix dolu olsa bile DB'ye sadece error_type yazılıyor,
        suppression yine tüm tip bastırıyordu. Bu audit bulgusu.
        """
        resolved_any = False
        prefix_key = message_prefix[:80].strip() if message_prefix else ""

        with self._lock:
            keys_to_remove = []
            for key, group in list(self._groups.items()):
                if group.error_type == error_type:
                    # Eşleşme: prefix boşsa tüm grubu çözümle,
                    # doluysa grup key'indeki prefix ile tam eşleşmesi gerekir.
                    # Grup key formatı: "error_type::prefix"
                    g_prefix = key.split("::", 1)[1] if "::" in key else ""
                    matches = (
                        not prefix_key
                        or prefix_key == g_prefix
                        or prefix_key in (group.message or "")[:80].strip()
                    )
                    if matches:
                        group.resolve(by)
                        keys_to_remove.append(key)
                        resolved_any = True

            # Bellekten sil
            for k in keys_to_remove:
                del self._groups[k]

            # Suppression set'ine ekle (wildcard vs spesifik)
            if resolved_any:
                if prefix_key:
                    self._resolved_keys.add((error_type, prefix_key))
                else:
                    self._resolved_types.add(error_type)

        if resolved_any and self._db:
            now_str = datetime.now().isoformat(timespec="seconds")
            try:
                self._db._execute(
                    """INSERT OR REPLACE INTO error_resolutions
                       (error_type, message_prefix, resolved_at, resolved_by)
                       VALUES (?, ?, ?, ?)""",
                    (error_type, prefix_key, now_str, by),
                )
                # Eski event'leri temizle — prefix varsa sadece eşleşen
                # mesajlı event'leri siliyoruz, yoksa tüm tipi.
                if prefix_key:
                    self._db._execute(
                        "DELETE FROM events WHERE type = ? "
                        "AND substr(trim(message), 1, 80) = ? "
                        "AND timestamp <= ?",
                        (error_type, prefix_key, now_str),
                    )
                else:
                    self._db._execute(
                        "DELETE FROM events WHERE type = ? AND timestamp <= ?",
                        (error_type, now_str),
                    )
            except Exception as exc:
                logger.error(f"Çözümleme DB yazma hatası: {exc}")

        return resolved_any

    def resolve_all(self, by: str = "operator") -> int:
        """Tüm açık hataları çözümle — DB'ye kalıcı yaz + eski event'leri sil.

        Tüm çözümlenen tipler _resolved_types set'ine eklenir.
        Engine bu tipleri üretse bile artık dashboard'da gösterilmez.
        """
        resolved_types: list[str] = []
        with self._lock:
            for group in self._groups.values():
                if not group.resolved:
                    group.resolve(by)
                    if group.error_type not in resolved_types:
                        resolved_types.append(group.error_type)

            # Suppression set'ine ekle
            for etype in resolved_types:
                self._resolved_types.add(etype)

            # Tüm grupları bellekten temizle
            self._groups.clear()

        if resolved_types and self._db:
            now_str = datetime.now().isoformat(timespec="seconds")
            try:
                for etype in resolved_types:
                    # Widget Denetimi A15 (B18): wildcard satır → message_prefix=''
                    self._db._execute(
                        """INSERT OR REPLACE INTO error_resolutions
                           (error_type, message_prefix, resolved_at, resolved_by)
                           VALUES (?, '', ?, ?)""",
                        (etype, now_str, by),
                    )
                    self._db._execute(
                        "DELETE FROM events WHERE type = ? AND timestamp <= ?",
                        (etype, now_str),
                    )
            except Exception as exc:
                logger.error(f"Toplu çözümleme DB hatası: {exc}")

        logger.info(f"Toplu çözümleme: {len(resolved_types)} tip çözümlendi ve bastırıldı")
        return len(resolved_types)

    # ── Sorgulama ──

    def get_summary(self) -> dict[str, Any]:
        """Dashboard özet verisi."""
        now = datetime.now()
        today = self._day_key(now)
        this_hour = self._hour_key(now)

        with self._lock:
            # Bugünkü sayaçlar
            today_counts = self._daily_counts.get(today, {})
            today_errors = today_counts.get("ERROR", 0) + today_counts.get("CRITICAL", 0)
            today_warnings = today_counts.get("WARNING", 0)

            # Açık / çözülmüş
            open_groups = [g for g in self._groups.values() if not g.resolved]
            resolved_groups = [g for g in self._groups.values() if g.resolved]

            # En son hata
            latest = None
            if open_groups:
                latest_group = max(open_groups, key=lambda g: g.last_seen)
                latest = latest_group.to_dict()

            # Kategori dağılımı
            by_category: dict[str, int] = defaultdict(int)
            for g in open_groups:
                by_category[g.category] += g.count

            # Severity dağılımı
            by_severity: dict[str, int] = defaultdict(int)
            for g in open_groups:
                by_severity[g.severity] += g.count

            # Bu saatteki hata sayısı
            this_hour_count = self._hourly_counts.get(this_hour, 0)

            return {
                "today_errors": today_errors,
                "today_warnings": today_warnings,
                "total_errors": self._total_errors,
                "total_warnings": self._total_warnings,
                "total_critical": self._total_critical,
                "open_groups": len(open_groups),
                "resolved_groups": len(resolved_groups),
                "this_hour_count": this_hour_count,
                "by_category": dict(by_category),
                "by_severity": dict(by_severity),
                "latest_error": latest,
            }

    def get_groups(
        self,
        category: str | None = None,
        severity: str | None = None,
        resolved: bool | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Hata gruplarını filtreli getir."""
        with self._lock:
            groups = list(self._groups.values())

        # Filtrele
        if category:
            groups = [g for g in groups if g.category == category]
        if severity:
            groups = [g for g in groups if g.severity == severity]
        if resolved is not None:
            groups = [g for g in groups if g.resolved == resolved]

        # Sırala: severity priority DESC, count DESC, last_seen DESC
        groups.sort(
            key=lambda g: (
                SEVERITY_PRIORITY.get(g.severity, 0),
                g.count,
                g.last_seen,
            ),
            reverse=True,
        )

        return [g.to_dict() for g in groups[:limit]]

    def get_trends(self, hours: int = 24) -> list[dict[str, Any]]:
        """Saatlik hata trendi (son N saat)."""
        now = datetime.now()
        result = []

        with self._lock:
            for i in range(hours):
                dt = now - timedelta(hours=i)
                key = self._hour_key(dt)
                count = self._hourly_counts.get(key, 0)
                result.append({
                    "hour": key,
                    "count": count,
                })

        result.reverse()  # Kronolojik sıra
        return result

    def get_daily_trends(self, days: int = 7) -> list[dict[str, Any]]:
        """Günlük hata trendi (son N gün)."""
        now = datetime.now()
        result = []

        with self._lock:
            for i in range(days):
                dt = now - timedelta(days=i)
                key = self._day_key(dt)
                counts = self._daily_counts.get(key, {})
                result.append({
                    "date": key,
                    "errors": counts.get("ERROR", 0) + counts.get("CRITICAL", 0),
                    "warnings": counts.get("WARNING", 0),
                    "critical": counts.get("CRITICAL", 0),
                })

        result.reverse()
        return result

    def get_categories(self) -> list[str]:
        """Mevcut kategorileri getir."""
        return sorted(set(ERROR_CATEGORIES.values()))
