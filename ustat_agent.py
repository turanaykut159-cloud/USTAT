"""
ÜSTAT AJAN v3.0 — Akıllı Otonom Ajan

v1.0: Basit komut aktarıcı (shell → sonuç)
v2.0: Düşünen, izleyen, kendini iyileştiren otonom varlık
v3.0: FUSE Bypass + Log Management + State bug fix

Mimari:
  ┌─────────────────────────────────────────┐
  │              AJAN BEYNİ                 │
  │  ┌───────────┐  ┌──────────────────┐    │
  │  │  Monitor   │  │  Task Queue      │    │
  │  │  (izleme)  │  │  (görev sırası)  │    │
  │  └─────┬─────┘  └────────┬─────────┘    │
  │        │                 │              │
  │  ┌─────▼─────────────────▼─────────┐    │
  │  │         State Manager            │    │
  │  │    (sistem durumu bilinci)       │    │
  │  └─────────────┬───────────────────┘    │
  │                │                        │
  │  ┌─────────────▼───────────────────┐    │
  │  │       Command Handlers           │    │
  │  │  (genişletilmiş yetenekler)     │    │
  │  └─────────────────────────────────┘    │
  └─────────────────────────────────────────┘
  ↕ JSON Dosya Köprüsü ↕
  Claude (Linux VM)

Yeni Yetenekler:
  ● Sistem bilinçi — ÜSTAT engine, API, MT5, disk, bellek durumu
  ● Proaktif izleme — Sorun tespiti ve otomatik müdahale
  ● Görev sırası — Öncelikli, kalıcı görev yönetimi
  ● Kendini iyileştirme — Crash recovery, auto-restart
  ● Otomatik temizlik — Eski dosyalar, loglar, geçici dosyalar
  ● Akıllı hata yönetimi — Retry, escalation, fallback
  ● Genişletilmiş komutlar — DB backup, config okuma, MT5 kontrol
  ● Bildirim sistemi — Kritik olayları Claude'a raporla
  ● Zamanlayıcı — Periyodik görevler (sağlık kontrolü, yedekleme, temizlik)

Kullanım:
  python ustat_agent.py              (normal başlatma)
  python ustat_agent.py --install    (Windows başlangıcına ekle)
  python ustat_agent.py --uninstall  (başlangıçtan kaldır)
  python ustat_agent.py --status     (anlık durum raporu)
"""

import json
import os
import sys
import time
import threading
import subprocess
import psutil
import platform
import hashlib
import shutil
import traceback
import socket
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import deque
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional

# ═══════════════════════════════════════════════════════════════
# WINDOWS SERVİS ALTYAPISI (v5.9)
# ═══════════════════════════════════════════════════════════════
# pywin32 yüklüyse Windows Service olarak çalışabilir.
# Yüklü değilse normal mod (eski davranış) ile çalışır.

_HAS_WIN32 = False
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    _HAS_WIN32 = True
except ImportError:
    pass

# ═══════════════════════════════════════════════════════════════
# YAPILANDIRMA
# ═══════════════════════════════════════════════════════════════

USTAT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
AGENT_DIR = USTAT_DIR / ".agent"
CMD_DIR = AGENT_DIR / "commands"
RESULT_DIR = AGENT_DIR / "results"
LOG_FILE = AGENT_DIR / "agent.log"
PID_FILE = AGENT_DIR / "agent.pid"
HEARTBEAT_FILE = AGENT_DIR / "heartbeat.json"
STATE_FILE = AGENT_DIR / "system_state.json"
ALERTS_FILE = AGENT_DIR / "alerts.json"
TASK_QUEUE_FILE = AGENT_DIR / "task_queue.json"
DESKTOP_DIR = USTAT_DIR / "desktop"
DB_PATH = USTAT_DIR / "database" / "trades.db"
CONFIG_PATH = USTAT_DIR / "config.json"

AGENT_VERSION = "3.0.0"

# Zamanlama
POLL_INTERVAL = 1.0            # komut tarama aralığı (saniye)
HEARTBEAT_INTERVAL = 10        # canlılık sinyali (saniye)
MONITOR_INTERVAL = 30          # sistem izleme aralığı (saniye)
CLEANUP_INTERVAL = 300         # temizlik aralığı (5 dk)
HEALTH_CHECK_INTERVAL = 60     # sağlık kontrolü (1 dk)
STATE_SAVE_INTERVAL = 15       # durum kayıt aralığı (saniye)

# Limitler
MAX_COMMAND_AGE = 300           # 5 dk'dan eski komutlar atlanır
MAX_SHELL_TIMEOUT = 120         # shell komut zaman aşımı
MAX_LOG_LINES = 200             # log okumada maks satır
MAX_LOG_SIZE_MB = 50            # log dosya boyut limiti
MAX_RESULT_AGE_HOURS = 24       # sonuç dosyaları temizleme
MAX_ALERT_COUNT = 100           # maks alert sayısı
MAX_RETRY = 3                   # komut tekrar deneme

# Port tanımları
KNOWN_PORTS = {
    "API": 8000,
    "Vite": 5173,
    "MT5": 443,        # MT5 remote connection
}


# ═══════════════════════════════════════════════════════════════
# ENUM VE VERİ YAPILARI
# ═══════════════════════════════════════════════════════════════


def _hidden_si():
    """Subprocess pencerelerini gizlemek icin STARTUPINFO olustur."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si

class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

class SystemComponent(str, Enum):
    ENGINE = "engine"
    API = "api"
    MT5 = "mt5"
    DATABASE = "database"
    DISK = "disk"
    DESKTOP = "desktop"
    AGENT = "agent"

class TaskPriority(int, Enum):
    CRITICAL = 0     # Hemen çalıştır
    HIGH = 1         # Sıradaki
    NORMAL = 2       # Normal sıra
    LOW = 3          # Boşta çalıştır

@dataclass
class Alert:
    severity: str
    component: str
    message: str
    timestamp: str = ""
    resolved: bool = False
    action_taken: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

@dataclass
class SystemState:
    """Sistemin anlık durumu."""
    # Bileşen durumları
    engine_running: bool = False
    api_alive: bool = False
    mt5_connected: bool = False
    desktop_running: bool = False
    db_accessible: bool = False

    # Metrikler
    disk_free_gb: float = 0.0
    disk_total_gb: float = 0.0
    api_pid: int = 0
    engine_uptime_s: int = 0
    open_positions: int = 0
    active_trades_count: int = 0

    # Ajan metrikleri
    agent_uptime_s: int = 0
    commands_processed: int = 0
    errors_count: int = 0
    last_command_time: str = ""
    last_health_check: str = ""
    last_monitor_run: str = ""

    # Son güncelleme
    updated: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["updated"] = datetime.now(timezone.utc).isoformat()
        return d


# ═══════════════════════════════════════════════════════════════
# LOGLAMA
# ═══════════════════════════════════════════════════════════════

_log_lock = threading.Lock()

def safe_print(msg: str):
    """Windows cp1254 uyumlu print."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def log(msg: str, level: str = "INFO"):
    """Thread-safe ajan log dosyasına yaz."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{level}] {msg}"
    with _log_lock:
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
    prefix = {
        "INFO": "→", "WARN": "⚠", "ERROR": "✗",
        "OK": "✓", "MONITOR": "◉", "HEAL": "♻",
        "ALERT": "🔔", "TASK": "📋", "CLEAN": "🧹",
    }.get(level, "→")
    safe_print(f"  {prefix} [{level}] {msg}")


# ═══════════════════════════════════════════════════════════════
# UYARI (ALERT) SİSTEMİ
# ═══════════════════════════════════════════════════════════════

class AlertManager:
    """Kritik olayları Claude'a raporlar."""

    def __init__(self):
        self._alerts: deque[Alert] = deque(maxlen=MAX_ALERT_COUNT)
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        """Kalıcı alertleri yükle."""
        try:
            if ALERTS_FILE.exists():
                data = json.loads(ALERTS_FILE.read_text(encoding="utf-8"))
                for a in data.get("alerts", [])[-MAX_ALERT_COUNT:]:
                    self._alerts.append(Alert(**a))
        except Exception:
            pass

    def _save(self):
        """Alertleri diske kaydet."""
        try:
            data = {"alerts": [asdict(a) for a in self._alerts]}
            tmp = ALERTS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(ALERTS_FILE)
        except Exception:
            pass

    def fire(self, severity: Severity, component: SystemComponent,
             message: str, action_taken: str = "") -> Alert:
        """Yeni alert oluştur."""
        alert = Alert(
            severity=severity.value,
            component=component.value,
            message=message,
            action_taken=action_taken,
        )
        with self._lock:
            self._alerts.append(alert)
            self._save()
        log(f"ALERT [{severity.value}] {component.value}: {message}", "ALERT")
        return alert

    def get_unresolved(self) -> list[dict]:
        """Çözülmemiş alertleri getir."""
        with self._lock:
            return [asdict(a) for a in self._alerts if not a.resolved]

    def get_recent(self, count: int = 20) -> list[dict]:
        """Son N alert."""
        with self._lock:
            return [asdict(a) for a in list(self._alerts)[-count:]]

    def resolve_all(self, component: str = None):
        """Alert'leri çözüldü olarak işaretle."""
        with self._lock:
            for a in self._alerts:
                if component is None or a.component == component:
                    a.resolved = True
            self._save()


# ═══════════════════════════════════════════════════════════════
# DURUM YÖNETİCİSİ (STATE MANAGER)
# ═══════════════════════════════════════════════════════════════

class StateManager:
    """Sistemin anlık durumunu takip eder."""

    def __init__(self, alerts: AlertManager):
        self.state = SystemState()
        self.alerts = alerts
        self._lock = threading.Lock()
        self._prev_states: dict[str, bool] = {}  # Geçiş tespiti için

    def update(self) -> SystemState:
        """Tüm bileşenlerin durumunu güncelle."""
        with self._lock:
            self._check_api()
            self._check_engine()
            self._check_desktop()
            self._check_database()
            self._check_disk()
            self._check_mt5()
            self._detect_transitions()
            self.state.updated = datetime.now(timezone.utc).isoformat()
            self._save()
        return self.state

    def _check_api(self):
        """API portu açık mı?"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("127.0.0.1", KNOWN_PORTS["API"]))
            self.state.api_alive = (result == 0)
            sock.close()
        except Exception:
            self.state.api_alive = False

        # api.pid
        pid_file = USTAT_DIR / "api.pid"
        if pid_file.exists():
            try:
                self.state.api_pid = int(pid_file.read_text(encoding="utf-8").strip())
            except Exception:
                self.state.api_pid = 0

    def _check_engine(self):
        """Engine sureci calisiyor mu? (psutil ile — pencere acmaz)"""
        try:
            for p in psutil.process_iter(["name", "cmdline"]):
                try:
                    name = (p.info.get("name") or "").lower()
                    cmdline = " ".join(p.info.get("cmdline") or []).lower()
                    if "python" in name and ("start_ustat" in cmdline or "uvicorn" in cmdline):
                        self.state.engine_running = True
                        return
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.state.engine_running = False
        except Exception:
            self.state.engine_running = False

    def _check_desktop(self):
        """Electron/Vite çalışıyor mu?"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("127.0.0.1", KNOWN_PORTS["Vite"]))
            self.state.desktop_running = (result == 0)
            sock.close()
        except Exception:
            self.state.desktop_running = False

    def _check_database(self):
        """Veritabanı erişilebilir mi?"""
        try:
            if DB_PATH.exists():
                conn = sqlite3.connect(str(DB_PATH), timeout=3)
                cursor = conn.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
                self.state.open_positions = cursor.fetchone()[0]
                cursor = conn.execute("SELECT COUNT(*) FROM trades")
                self.state.active_trades_count = cursor.fetchone()[0]
                conn.close()
                self.state.db_accessible = True
            else:
                self.state.db_accessible = False
        except Exception:
            self.state.db_accessible = False

    def _check_disk(self):
        """Disk durumu."""
        try:
            usage = shutil.disk_usage(str(USTAT_DIR))
            self.state.disk_free_gb = round(usage.free / (1024 ** 3), 1)
            self.state.disk_total_gb = round(usage.total / (1024 ** 3), 1)
        except Exception:
            pass

    def _check_mt5(self):
        """MT5 terminal calisiyor mu? (psutil ile — pencere acmaz)"""
        try:
            for p in psutil.process_iter(["name"]):
                try:
                    name = (p.info.get("name") or "").lower()
                    if "terminal64" in name:
                        self.state.mt5_connected = True
                        return
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.state.mt5_connected = False
        except Exception:
            self.state.mt5_connected = False

    def _detect_transitions(self):
        """Durum değişikliklerini tespit et ve alert oluştur."""
        checks = {
            "api_alive": (self.state.api_alive, SystemComponent.API, "API sunucusu"),
            "engine_running": (self.state.engine_running, SystemComponent.ENGINE, "Trading engine"),
            "mt5_connected": (self.state.mt5_connected, SystemComponent.MT5, "MT5 terminali"),
            "db_accessible": (self.state.db_accessible, SystemComponent.DATABASE, "Veritabanı"),
        }

        for key, (current, component, name) in checks.items():
            prev = self._prev_states.get(key)
            if prev is not None and prev != current:
                if not current:
                    self.alerts.fire(
                        Severity.CRITICAL, component,
                        f"{name} DÜŞTÜ!",
                    )
                else:
                    self.alerts.fire(
                        Severity.INFO, component,
                        f"{name} tekrar aktif.",
                    )
                    self.alerts.resolve_all(component.value)
            self._prev_states[key] = current

        # Disk doluluk uyarısı
        if self.state.disk_total_gb > 0:
            pct = (self.state.disk_total_gb - self.state.disk_free_gb) / self.state.disk_total_gb * 100
            if pct > 90:
                self.alerts.fire(
                    Severity.WARNING, SystemComponent.DISK,
                    f"Disk %{pct:.0f} dolu! ({self.state.disk_free_gb:.1f} GB boş)",
                )

    def _save(self):
        """Durumu diske kaydet."""
        try:
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.state.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(STATE_FILE)
        except Exception:
            pass

    def get_summary(self) -> str:
        """İnsan okunur durum özeti."""
        s = self.state
        lines = [
            f"╔══════════════ ÜSTAT DURUM RAPORU ══════════════╗",
            f"║  API       : {'✅ AKTIF' if s.api_alive else '❌ KAPALI':<20} PID: {s.api_pid}",
            f"║  Engine    : {'✅ ÇALIŞIYOR' if s.engine_running else '❌ DURMUŞ':<20}",
            f"║  MT5       : {'✅ BAĞLI' if s.mt5_connected else '❌ BAĞLANTI YOK':<20}",
            f"║  Desktop   : {'✅ AKTIF' if s.desktop_running else '⚪ KAPALI':<20}",
            f"║  Veritabanı: {'✅ ERIŞILEBILIR' if s.db_accessible else '❌ ERIŞILEMIYOR':<20}",
            f"║  Disk      : {s.disk_free_gb:.1f} GB boş / {s.disk_total_gb:.1f} GB toplam",
            f"║  Pozisyonlar: {s.open_positions} açık",
            f"║  Toplam İşlem: {s.active_trades_count}",
            f"╚══════════════════════════════════════════════════╝",
        ]
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# PROAKTİF İZLEME (MONITOR)
# ═══════════════════════════════════════════════════════════════

class Monitor:
    """Proaktif sistem izleme ve otomatik müdahale."""

    def __init__(self, state_mgr: StateManager, alerts: AlertManager):
        self.state_mgr = state_mgr
        self.alerts = alerts
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._heal_cooldown: dict[str, float] = {}  # component → son heal zamanı

    def start(self):
        """Monitor thread'ini başlat."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Monitor")
        self._thread.start()
        log("Monitor başlatıldı", "MONITOR")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        """Ana izleme döngüsü."""
        while self._running:
            try:
                self.state_mgr.update()
                self._check_and_heal()
                self.state_mgr.state.last_monitor_run = datetime.now(timezone.utc).isoformat()
            except Exception as e:
                log(f"Monitor hatası: {e}", "ERROR")
            time.sleep(MONITOR_INTERVAL)

    def _can_heal(self, component: str, cooldown_s: int = 300) -> bool:
        """Aynı bileşen için heal cooldown kontrolü."""
        last = self._heal_cooldown.get(component, 0)
        if time.time() - last < cooldown_s:
            return False
        self._heal_cooldown[component] = time.time()
        return True

    def _check_and_heal(self):
        """Sorun tespiti ve otomatik müdahale."""
        state = self.state_mgr.state

        # 0. shutdown.signal varsa → kullanıcı kasıtlı kapattı, restart YAPMA
        shutdown_signal = USTAT_DIR / "shutdown.signal"
        if shutdown_signal.exists():
            log("shutdown.signal mevcut — kullanıcı kasıtlı kapattı, restart atlanıyor", "MONITOR")
            return

        # 1. API düştüyse → SADECE UYAR, restart YAPMA (v5.9.1 — kullanıcı kararı)
        # Kullanıcı onayı olmadan uygulama AÇILMAYACAK.
        if not state.api_alive:
            if self._can_heal("api_alert", 300):
                reason = "API düşmüş"
                if not state.engine_running:
                    reason = "API ve Engine ikisi de düşmüş"
                log(f"{reason} — sadece uyarı (otomatik restart DEVRE DIŞI)", "MONITOR")
                self.alerts.fire(
                    Severity.CRITICAL, SystemComponent.API,
                    f"{reason}. Kullanıcı müdahalesi gerekiyor.",
                    action_taken="alert_only",
                )

        # 2. MT5 düştüyse → alarm (MT5 otomatik restart yapılamaz ama uyar)
        if not state.mt5_connected:
            if self._can_heal("mt5_alert", 600):
                self.alerts.fire(
                    Severity.CRITICAL, SystemComponent.MT5,
                    "MT5 terminali çalışmıyor! İşlem yapılamaz.",
                )

        # 3. DB erişilemiyor → alarm
        if not state.db_accessible and DB_PATH.exists():
            if self._can_heal("db_alert", 300):
                self.alerts.fire(
                    Severity.WARNING, SystemComponent.DATABASE,
                    "Veritabanına erişilemiyor (kilitli olabilir).",
                )

        # 4. Log dosyası çok büyüdüyse → rotate
        if LOG_FILE.exists():
            size_mb = LOG_FILE.stat().st_size / (1024 * 1024)
            if size_mb > MAX_LOG_SIZE_MB:
                self._rotate_log()

    def _try_restart_ustat(self):
        """DEVRE DIŞI (v5.9.1) — Kullanıcı kararı: otomatik restart YASAK.
        Uygulama sadece kullanıcı tarafından masaüstü kısayolundan açılacak."""
        log("_try_restart_ustat çağrıldı ama DEVRE DIŞI — otomatik restart YASAK", "HEAL")
        return

    def _rotate_log(self):
        """Log dosyasını döndür."""
        try:
            backup = LOG_FILE.with_suffix(f".{int(time.time())}.log")
            LOG_FILE.rename(backup)
            log("Log dosyası döndürüldü", "CLEAN")
            # Eski backupları temizle (en fazla 3 tut)
            log_backups = sorted(AGENT_DIR.glob("agent.*.log"), key=lambda p: p.stat().st_mtime)
            for old in log_backups[:-3]:
                old.unlink(missing_ok=True)
        except Exception as e:
            log(f"Log rotate hatası: {e}", "ERROR")


# ═══════════════════════════════════════════════════════════════
# OTOMATİK TEMİZLİK
# ═══════════════════════════════════════════════════════════════

class Cleaner:
    """Eski dosyaları ve geçici verileri temizler."""

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Cleaner")
        self._thread.start()
        log("Temizlik servisi başlatıldı", "CLEAN")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        """Periyodik temizlik."""
        # İlk temizlik 30 sn sonra
        time.sleep(30)
        while self._running:
            try:
                self._clean_results()
                self._clean_commands()
                self._clean_screenshots()
            except Exception as e:
                log(f"Temizlik hatası: {e}", "ERROR")
            time.sleep(CLEANUP_INTERVAL)

    def _clean_results(self):
        """Eski sonuç dosyalarını temizle."""
        if not RESULT_DIR.exists():
            return
        cutoff = time.time() - (MAX_RESULT_AGE_HOURS * 3600)
        count = 0
        for f in RESULT_DIR.glob("*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    count += 1
            except Exception:
                pass
        if count:
            log(f"{count} eski sonuç dosyası temizlendi", "CLEAN")

    def _clean_commands(self):
        """İşlenmemiş eski komut dosyalarını temizle."""
        if not CMD_DIR.exists():
            return
        cutoff = time.time() - MAX_COMMAND_AGE
        count = 0
        for f in CMD_DIR.glob("*.json"):
            if f.name.startswith("_"):  # Özel dosyalar
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    count += 1
            except Exception:
                pass
        if count:
            log(f"{count} eski komut dosyası temizlendi", "CLEAN")

    def _clean_screenshots(self):
        """24 saatten eski screenshot dosyalarını temizle."""
        cutoff = time.time() - 86400
        count = 0
        for f in AGENT_DIR.glob("screenshot_*.png"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    count += 1
            except Exception:
                pass
        if count:
            log(f"{count} eski ekran görüntüsü temizlendi", "CLEAN")


# ═══════════════════════════════════════════════════════════════
# KLASÖR HAZIRLIĞI
# ═══════════════════════════════════════════════════════════════

def ensure_dirs():
    """Ajan klasörlerini oluştur."""
    CMD_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    gitignore = AGENT_DIR / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
# HEARTBEAT (BAĞIMSIZ THREAD)
# ═══════════════════════════════════════════════════════════════

class HeartbeatService:
    """Ayrı thread'de çalışan heartbeat servisi.
    Ana döngü komut işlerken bloklanabilir ama heartbeat
    her zaman düzenli çalışmalı — Claude ajanın canlı olduğunu
    heartbeat'ten anlıyor.
    """

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Heartbeat")
        self._thread.start()
        # İlk heartbeat'i hemen yaz
        self._write()
        log("Heartbeat servisi başlatıldı", "INFO")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        # Son heartbeat: alive=False
        try:
            data = json.dumps({
                "alive": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": AGENT_VERSION,
                "shutdown_reason": "agent_stop",
            }, indent=2, ensure_ascii=False)
            HEARTBEAT_FILE.write_text(data, encoding="utf-8")
        except Exception:
            pass

    def _loop(self):
        while self._running:
            try:
                self._write()
            except Exception:
                pass
            time.sleep(HEARTBEAT_INTERVAL)

    def _write(self):
        """Heartbeat dosyasını yaz — cross-mount uyumlu.
        Linux-Windows mount sınırında büyük JSON truncate olabiliyor.
        Bu yüzden: küçük JSON + flush + fsync + rename.
        """
        state = _state_mgr.state if _state_mgr else SystemState()
        # Kompakt tek-satır JSON (küçük = truncation riski düşük)
        data = {
            "alive": True,
            "pid": os.getpid(),
            "version": AGENT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime": int(time.time() - _agent_start_time),
            "cmds": _commands_processed,
            "api": state.api_alive,
            "engine": state.engine_running,
            "mt5": state.mt5_connected,
            "db": state.db_accessible,
            "pos": state.open_positions,
        }
        content = json.dumps(data, ensure_ascii=False)

        try:
            # Yöntem 1: tmp + flush + fsync + rename
            tmp = HEARTBEAT_FILE.with_suffix(".tmp")
            fd = open(tmp, "w", encoding="utf-8")
            fd.write(content)
            fd.flush()
            os.fsync(fd.fileno())
            fd.close()
            tmp.replace(HEARTBEAT_FILE)
        except Exception:
            try:
                # Yöntem 2: doğrudan yaz + flush + fsync
                fd = open(HEARTBEAT_FILE, "w", encoding="utf-8")
                fd.write(content)
                fd.flush()
                os.fsync(fd.fileno())
                fd.close()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# KOMUT OKUMA / SONUÇ YAZMA
# ═══════════════════════════════════════════════════════════════

def read_command(path: Path) -> dict | None:
    """Komut dosyasını oku."""
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception as e:
        log(f"Komut okunamadı: {path.name} — {e}", "ERROR")
        return None


def write_result(cmd_id: str, success: bool, output: str,
                 error: str = "", duration: float = 0.0, extra: dict = None):
    """Sonuç dosyası yaz (atomic)."""
    data = {
        "id": cmd_id,
        "success": success,
        "output": output,
        "error": error,
        "duration_seconds": round(duration, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_version": AGENT_VERSION,
    }
    if extra:
        data.update(extra)
    result_file = RESULT_DIR / f"{cmd_id}.json"
    try:
        tmp = result_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(result_file)
    except Exception as e:
        log(f"Sonuç yazılamadı: {cmd_id} — {e}", "ERROR")


# ═══════════════════════════════════════════════════════════════
# KOMUT İŞLEYİCİLER — MEVCUT (v1.0 uyumlu)
# ═══════════════════════════════════════════════════════════════

def handle_shell(cmd: dict) -> tuple[bool, str, str]:
    """Shell komutu çalıştır (PowerShell / CMD / Python)."""
    command = cmd.get("command", "")
    cwd = cmd.get("cwd", str(USTAT_DIR))
    timeout = min(cmd.get("timeout", MAX_SHELL_TIMEOUT), MAX_SHELL_TIMEOUT)
    shell_type = cmd.get("shell", "powershell")

    if not command:
        return False, "", "Komut boş"

    if shell_type == "powershell":
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    elif shell_type == "python":
        args = [sys.executable, "-c", command]
    else:
        args = ["cmd", "/c", command]

    try:
        result = subprocess.run(
            args,
            capture_output=True, text=True,
            cwd=cwd, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=0x08000000 if os.name == chr(110)+chr(116) else 0,
            startupinfo=_hidden_si(),
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", f"Zaman aşımı ({timeout}s)"
    except Exception as e:
        return False, "", str(e)


def handle_start_app(cmd: dict) -> tuple[bool, str, str]:
    """ÜSTAT uygulamasını başlat.

    schtasks /IT ile kullanıcı oturumunda interaktif olarak çalıştırır.
    API'nin ayağa kalkmasını bekler (max 20sn).
    """
    try:
        start_script = USTAT_DIR / "start_ustat.py"
        if not start_script.exists():
            return False, "", "start_ustat.py bulunamadı"

        python_exe = r"C:\Users\pc\AppData\Local\Programs\Python\Python314\pythonw.exe"
        task_name = "USTAT_InteractiveLaunch"

        # 1. Eski task varsa temizle
        subprocess.run(
            ["schtasks", "/delete", "/tn", task_name, "/f"],
            capture_output=True, timeout=10,
        )

        # 2. Interaktif oturumda çalışacak task oluştur
        result = subprocess.run(
            [
                "schtasks", "/create",
                "/tn", task_name,
                "/tr", f'{python_exe} {start_script}',
                "/sc", "once",
                "/st", "00:00",
                "/RU", "pc",        # Kullanıcı oturumu
                "/IT",              # Interactive Token — kullanıcı masaüstünde çalışır
                "/f",               # Force overwrite
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False, "", f"schtasks create başarısız: {result.stderr}"

        # 3. Task'ı hemen çalıştır
        result = subprocess.run(
            ["schtasks", "/run", "/tn", task_name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False, "", f"schtasks run başarısız: {result.stderr}"

        # 4. API'nin ayağa kalkmasını bekle (max 20sn)
        for i in range(10):
            time.sleep(2)
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                if sock.connect_ex(("127.0.0.1", KNOWN_PORTS["API"])) == 0:
                    sock.close()
                    # 5. Temizlik — geçici task'ı sil
                    subprocess.run(
                        ["schtasks", "/delete", "/tn", task_name, "/f"],
                        capture_output=True, timeout=10,
                    )
                    return True, f"ÜSTAT başlatıldı (interaktif oturum, API aktif)", ""
                sock.close()
            except Exception:
                pass

        # API henüz yanıt vermese de task çalıştı
        subprocess.run(
            ["schtasks", "/delete", "/tn", task_name, "/f"],
            capture_output=True, timeout=10,
        )
        return True, "ÜSTAT başlatıldı ama API henüz yanıt vermiyor. Biraz bekleyin.", ""
    except Exception as e:
        return False, "", str(e)


def handle_stop_app(cmd: dict) -> tuple[bool, str, str]:
    """ÜSTAT uygulamasını durdur.

    İki aşamalı durdurma:
    1. Normal Stop-Process (CommandLine match ile)
    2. Başarısız olursa admin yetkili taskkill /F /PID ile zorla kapat
    """
    killed = []
    errors = []
    targets = ["python.*start_ustat", "uvicorn", "node.*electron", "node.*vite"]

    # ── Aşama 1: Normal Stop-Process ──────────────────────────────
    for target in targets:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-Process | Where-Object {{$_.CommandLine -match '{target}'}} | Stop-Process -Force -PassThru"],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", errors="replace",
                creationflags=0x08000000 if os.name == chr(110)+chr(116) else 0,
                startupinfo=_hidden_si(),
            )
            if result.stdout.strip():
                killed.append(target)
        except Exception as e:
            errors.append(f"{target}: {e}")

    # ── Aşama 2: Hâlâ çalışan ÜSTAT process'leri varsa admin taskkill ─
    still_running = []
    # Ajan PID'leri — bunları ASLA kapatma
    agent_pid = os.getpid()
    agent_pids = {agent_pid}
    # Ajan watchdog (parent) PID'ini de koru
    try:
        import psutil
        agent_pids.add(psutil.Process(agent_pid).ppid())
    except Exception:
        pass

    # Sadece ÜSTAT ile ilişkili process'leri bul (CommandLine match)
    ustat_patterns = ["start_ustat", "uvicorn", "electron", "vite"]
    try:
        check = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process -Name python,pythonw,node,electron -ErrorAction SilentlyContinue "
             "| Select-Object Id,@{n='CL';e={$_.CommandLine}} "
             "| ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            creationflags=0x08000000 if os.name == chr(110)+chr(116) else 0,
            startupinfo=_hidden_si(),
        )
        if check.stdout.strip():
            import json as _json
            procs = _json.loads(check.stdout)
            if isinstance(procs, dict):
                procs = [procs]
            for p in procs:
                pid = p.get("Id", 0)
                cl = (p.get("CL") or "").lower()
                if pid in agent_pids:
                    continue  # Ajanı koru
                if "ustat_agent" in cl:
                    continue  # Ajan scriptini koru
                if any(pat in cl for pat in ustat_patterns):
                    still_running.append(pid)
    except Exception:
        pass

    if still_running:
        for pid in still_running:
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Start-Process taskkill -ArgumentList '/F /PID {pid}' -Verb RunAs -WindowStyle Hidden -Wait"],
                    capture_output=True, text=True, timeout=15,
                    encoding="utf-8", errors="replace",
                    creationflags=0x08000000 if os.name == chr(110)+chr(116) else 0,
                    startupinfo=_hidden_si(),
                )
                killed.append(f"PID:{pid}")
            except Exception as e:
                errors.append(f"taskkill PID {pid}: {e}")

    if killed:
        return True, f"Durduruldu: {', '.join(killed)}", "\n".join(errors) if errors else ""
    elif errors:
        return False, "", "\n".join(errors)
    else:
        return True, "Çalışan ÜSTAT süreci bulunamadı", ""


def handle_build(cmd: dict) -> tuple[bool, str, str]:
    """Desktop npm run build."""
    try:
        if not DESKTOP_DIR.exists():
            return False, "", "desktop/ klasörü bulunamadı"

        if not (DESKTOP_DIR / "node_modules").exists():
            log("node_modules yok, npm install çalıştırılıyor...", "WARN")
            subprocess.run(
                ["npm", "install"],
                cwd=str(DESKTOP_DIR),
                capture_output=True, text=True, timeout=120,
                shell=True, encoding="utf-8", errors="replace",
                creationflags=0x08000000 if os.name == chr(110)+chr(116) else 0,
                startupinfo=_hidden_si(),
            )

        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(DESKTOP_DIR),
            capture_output=True, text=True, timeout=120,
            shell=True, encoding="utf-8", errors="replace",
            creationflags=0x08000000 if os.name == chr(110)+chr(116) else 0,
            startupinfo=_hidden_si(),
        )

        if result.returncode == 0:
            return True, f"Build başarılı.\n{result.stdout.strip()}", ""
        else:
            return False, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Build zaman aşımı (120s)"
    except Exception as e:
        return False, "", str(e)


def handle_screenshot(cmd: dict) -> tuple[bool, str, str]:
    """Ekran görüntüsü al."""
    try:
        from PIL import ImageGrab
        filename = cmd.get("filename", f"screenshot_{int(time.time())}.png")
        filepath = AGENT_DIR / filename
        img = ImageGrab.grab()
        img.save(str(filepath), "PNG")
        return True, str(filepath), ""
    except ImportError:
        try:
            import mss
            filename = cmd.get("filename", f"screenshot_{int(time.time())}.png")
            filepath = AGENT_DIR / filename
            with mss.mss() as sct:
                sct.shot(output=str(filepath))
            return True, str(filepath), ""
        except ImportError:
            return False, "", "Pillow veya mss kurulu değil."
    except Exception as e:
        return False, "", str(e)


def handle_shortcut(cmd: dict) -> tuple[bool, str, str]:
    """Masaüstü kısayolunu güncelle."""
    try:
        script = USTAT_DIR / "update_shortcut.ps1"
        if not script.exists():
            return False, "", "update_shortcut.ps1 bulunamadı"

        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, timeout=30,
            cwd=str(USTAT_DIR), encoding="utf-8", errors="replace",
            input="\n",
            creationflags=0x08000000 if os.name == chr(110)+chr(116) else 0,
            startupinfo=_hidden_si(),
        )
        output = result.stdout.strip()
        error = result.stderr.strip()
        return result.returncode == 0 or "olusturuldu" in output.lower(), output, error
    except Exception as e:
        return False, "", str(e)


def handle_readlog(cmd: dict) -> tuple[bool, str, str]:
    """Log dosyası oku."""
    logname = cmd.get("file", "")
    lines = cmd.get("lines", MAX_LOG_LINES)
    search = cmd.get("search", "")

    log_paths = {
        "api": USTAT_DIR / "api.log",
        "startup": USTAT_DIR / "startup.log",
        "agent": LOG_FILE,
        "electron": DESKTOP_DIR / "electron.log",
    }

    if logname in log_paths:
        target = log_paths[logname]
    else:
        target = USTAT_DIR / logname
        if not target.exists():
            target = USTAT_DIR / "logs" / logname

    if not target.exists():
        available = [k for k, v in log_paths.items() if v.exists()]
        return False, "", f"Log bulunamadı: {logname}\nMevcut: {', '.join(available)}"

    try:
        all_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        if search:
            all_lines = [l for l in all_lines if search.lower() in l.lower()]
        tail = all_lines[-lines:]
        return True, "\n".join(tail), ""
    except Exception as e:
        return False, "", str(e)


def handle_processes(cmd: dict) -> tuple[bool, str, str]:
    """Çalışan süreçleri listele."""
    filter_name = cmd.get("filter", "python|node|electron|uvicorn|mt5|terminal64")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-Process | Where-Object {{$_.ProcessName -match '{filter_name}'}} | "
             "Format-Table ProcessName, Id, CPU, @{N='MB';E={[math]::Round($_.WorkingSet64/1MB,1)}} -AutoSize | Out-String"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            creationflags=0x08000000 if os.name == chr(110)+chr(116) else 0,
            startupinfo=_hidden_si(),
        )
        return True, result.stdout.strip() or "Eşleşen süreç yok", ""
    except Exception as e:
        return False, "", str(e)


def handle_ping(cmd: dict) -> tuple[bool, str, str]:
    """Canlılık kontrolü — artık sistem durumu ile."""
    uptime = int(time.time() - _agent_start_time)
    return True, (
        f"AJAN CANLI — v{AGENT_VERSION} — PID {os.getpid()} — "
        f"uptime {uptime}s — {_commands_processed} komut işlendi"
    ), ""


# ═══════════════════════════════════════════════════════════════
# KOMUT İŞLEYİCİLER — YENİ (v2.0)
# ═══════════════════════════════════════════════════════════════

def handle_system_status(cmd: dict) -> tuple[bool, str, str]:
    """Detaylı sistem durum raporu (v2.0)."""
    try:
        _state_mgr.update()
        summary = _state_mgr.get_summary()
        state_json = json.dumps(_state_mgr.state.to_dict(), indent=2, ensure_ascii=False)
        return True, f"{summary}\n\nJSON:\n{state_json}", ""
    except Exception as e:
        return False, "", str(e)


def handle_health_check(cmd: dict) -> tuple[bool, str, str]:
    """Kapsamlı sağlık kontrolü."""
    issues = []
    ok = []
    state = _state_mgr.state

    # API kontrolü
    if state.api_alive:
        ok.append("API: ✅ Port 8000 açık")
    else:
        issues.append("API: ❌ Port 8000 kapalı — engine çalışmıyor olabilir")

    # Engine kontrolü
    if state.engine_running:
        ok.append("Engine: ✅ Çalışıyor")
    else:
        issues.append("Engine: ❌ Süreç bulunamadı")

    # MT5 kontrolü
    if state.mt5_connected:
        ok.append("MT5: ✅ Terminal aktif")
    else:
        issues.append("MT5: ❌ Terminal çalışmıyor — işlem yapılamaz!")

    # DB kontrolü
    if state.db_accessible:
        ok.append(f"DB: ✅ Erişilebilir ({state.open_positions} açık pozisyon)")
    else:
        issues.append("DB: ❌ Erişilemiyor")

    # Disk kontrolü
    if state.disk_free_gb > 5:
        ok.append(f"Disk: ✅ {state.disk_free_gb:.1f} GB boş")
    elif state.disk_free_gb > 1:
        issues.append(f"Disk: ⚠ Düşük alan — {state.disk_free_gb:.1f} GB boş")
    else:
        issues.append(f"Disk: ❌ KRİTİK — {state.disk_free_gb:.1f} GB boş!")

    # Config kontrolü
    if CONFIG_PATH.exists():
        ok.append("Config: ✅ Mevcut")
    else:
        issues.append("Config: ❌ config.json bulunamadı")

    report = "=== SAĞLIK RAPORU ===\n\n"
    if issues:
        report += "❌ SORUNLAR:\n" + "\n".join(f"  • {i}" for i in issues) + "\n\n"
    report += "✅ İYİ DURUMDA:\n" + "\n".join(f"  • {o}" for o in ok)

    success = len(issues) == 0
    return success, report, "\n".join(issues) if issues else ""


def handle_alerts(cmd: dict) -> tuple[bool, str, str]:
    """Alert listesi (okunmamış veya tümü)."""
    mode = cmd.get("mode", "unresolved")  # unresolved | all | resolve
    count = cmd.get("count", 20)

    if mode == "resolve":
        component = cmd.get("component", None)
        _alert_mgr.resolve_all(component)
        return True, f"Alert'ler çözüldü{f' ({component})' if component else ''}", ""
    elif mode == "all":
        alerts = _alert_mgr.get_recent(count)
    else:
        alerts = _alert_mgr.get_unresolved()

    if not alerts:
        return True, "Bekleyen alert yok ✅", ""

    lines = []
    for a in alerts:
        icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(a["severity"], "⚪")
        lines.append(f"{icon} [{a['component']}] {a['message']} ({a['timestamp'][:19]})")
        if a.get("action_taken"):
            lines.append(f"   → Alınan aksiyon: {a['action_taken']}")
    return True, "\n".join(lines), ""


def handle_db_backup(cmd: dict) -> tuple[bool, str, str]:
    """Veritabanı yedeği al."""
    try:
        if not DB_PATH.exists():
            return False, "", "trades.db bulunamadı"

        backup_dir = DB_PATH.parent
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"trades_backup_{ts}.db"

        # SQLite online backup API
        src = sqlite3.connect(str(DB_PATH))
        dst = sqlite3.connect(str(backup_path))
        src.backup(dst)
        dst.close()
        src.close()

        size_mb = backup_path.stat().st_size / (1024 * 1024)

        # Eski yedekleri temizle (en fazla 5 tut)
        backups = sorted(backup_dir.glob("trades_backup_*.db"), key=lambda p: p.stat().st_mtime)
        removed = 0
        for old in backups[:-5]:
            old.unlink(missing_ok=True)
            removed += 1

        msg = f"Yedek alındı: {backup_path.name} ({size_mb:.1f} MB)"
        if removed:
            msg += f"\n{removed} eski yedek temizlendi."
        return True, msg, ""
    except Exception as e:
        return False, "", str(e)


def handle_db_query(cmd: dict) -> tuple[bool, str, str]:
    """Veritabanında sorgu çalıştır (READ-ONLY)."""
    query = cmd.get("query", "")
    if not query:
        return False, "", "Sorgu boş"

    # Güvenlik: sadece SELECT
    if not query.strip().upper().startswith("SELECT"):
        return False, "", "Güvenlik: Sadece SELECT sorguları desteklenir."

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return True, "Sonuç yok", ""

        # JSON formatında döndür
        result = [dict(r) for r in rows]
        return True, json.dumps(result, indent=2, ensure_ascii=False, default=str), ""
    except Exception as e:
        return False, "", str(e)


def handle_read_config(cmd: dict) -> tuple[bool, str, str]:
    """Config dosyasını oku."""
    key = cmd.get("key", "")
    try:
        if not CONFIG_PATH.exists():
            return False, "", "config.json bulunamadı"

        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

        if key:
            # Noktalı yol: "engine.lot_size"
            parts = key.split(".")
            val = config
            for p in parts:
                val = val[p]
            return True, json.dumps(val, indent=2, ensure_ascii=False), ""
        else:
            return True, json.dumps(config, indent=2, ensure_ascii=False), ""
    except KeyError:
        return False, "", f"Anahtar bulunamadı: {key}"
    except Exception as e:
        return False, "", str(e)


def handle_restart_app(cmd: dict) -> tuple[bool, str, str]:
    """ÜSTAT uygulamasını yeniden başlat (stop + start)."""
    log("ÜSTAT restart başlatılıyor...", "INFO")

    # 1. Durdur
    success, output, error = handle_stop_app(cmd)
    if not success and "bulunamadı" not in output:
        log(f"Stop hatası: {error}", "WARN")

    # 2. Bekle
    time.sleep(5)

    # 3. Başlat
    success, output, error = handle_start_app(cmd)
    if success:
        # 4. API'nin ayağa kalkmasını bekle
        for _ in range(10):
            time.sleep(2)
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                if sock.connect_ex(("127.0.0.1", KNOWN_PORTS["API"])) == 0:
                    sock.close()
                    return True, f"ÜSTAT başarıyla yeniden başlatıldı. API aktif.", ""
                sock.close()
            except Exception:
                pass
        return True, f"ÜSTAT başlatıldı ama API henüz yanıt vermiyor. Biraz bekleyin.", ""
    return success, output, error


def handle_tail_log(cmd: dict) -> tuple[bool, str, str]:
    """Birden fazla log dosyasından son satırları çek."""
    lines_per_file = cmd.get("lines", 30)
    targets = cmd.get("files", ["api", "agent"])

    log_paths = {
        "api": USTAT_DIR / "api.log",
        "startup": USTAT_DIR / "startup.log",
        "agent": LOG_FILE,
        "electron": DESKTOP_DIR / "electron.log",
    }

    output_parts = []
    for name in targets:
        path = log_paths.get(name, USTAT_DIR / name)
        if path.exists():
            try:
                all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = all_lines[-lines_per_file:]
                output_parts.append(f"=== {name.upper()} (son {len(tail)} satır) ===\n" + "\n".join(tail))
            except Exception as e:
                output_parts.append(f"=== {name.upper()} === OKUNAMADI: {e}")
        else:
            output_parts.append(f"=== {name.upper()} === DOSYA YOK")

    return True, "\n\n".join(output_parts), ""


def handle_file_read(cmd: dict) -> tuple[bool, str, str]:
    """Dosya oku (ÜSTAT dizini içinde)."""
    filepath = cmd.get("path", "")
    if not filepath:
        return False, "", "Dosya yolu boş"

    # Güvenlik: sadece USTAT_DIR altında
    target = (USTAT_DIR / filepath).resolve()
    if not str(target).startswith(str(USTAT_DIR.resolve())):
        return False, "", "Güvenlik: Sadece ÜSTAT dizini içindeki dosyalar okunabilir."

    if not target.exists():
        return False, "", f"Dosya bulunamadı: {filepath}"

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        limit = cmd.get("lines", 500)
        if len(lines) > limit:
            content = "\n".join(lines[-limit:])
            content = f"[... {len(lines) - limit} satır atlandı ...]\n" + content
        return True, content, ""
    except Exception as e:
        return False, "", str(e)


def handle_file_write(cmd: dict) -> tuple[bool, str, str]:
    """Dosya yaz (ÜSTAT dizini içinde, sadece .agent/ altında)."""
    filepath = cmd.get("path", "")
    content = cmd.get("content", "")
    if not filepath:
        return False, "", "Dosya yolu boş"

    # Güvenlik: sadece .agent/ dizini altında yazma izni
    target = (AGENT_DIR / filepath).resolve()
    if not str(target).startswith(str(AGENT_DIR.resolve())):
        return False, "", "Güvenlik: Sadece .agent/ dizini altına yazılabilir."

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return True, f"Yazıldı: {target.name} ({len(content)} byte)", ""
    except Exception as e:
        return False, "", str(e)


def handle_list_files(cmd: dict) -> tuple[bool, str, str]:
    """Dizin listele."""
    dirpath = cmd.get("path", "")
    pattern = cmd.get("pattern", "*")

    target = (USTAT_DIR / dirpath).resolve() if dirpath else USTAT_DIR
    if not str(target).startswith(str(USTAT_DIR.resolve())):
        return False, "", "Güvenlik: Sadece ÜSTAT dizini içinde listeleme yapılabilir."

    if not target.is_dir():
        return False, "", f"Dizin bulunamadı: {dirpath}"

    try:
        items = sorted(target.glob(pattern))
        lines = []
        for item in items[:200]:  # Max 200 item
            rel = item.relative_to(USTAT_DIR)
            if item.is_dir():
                lines.append(f"📁 {rel}/")
            else:
                size = item.stat().st_size
                if size > 1024 * 1024:
                    sz = f"{size / (1024*1024):.1f}MB"
                elif size > 1024:
                    sz = f"{size / 1024:.1f}KB"
                else:
                    sz = f"{size}B"
                lines.append(f"📄 {rel} ({sz})")
        return True, "\n".join(lines) if lines else "Boş dizin", ""
    except Exception as e:
        return False, "", str(e)


def handle_positions(cmd: dict) -> tuple[bool, str, str]:
    """Açık pozisyonları listele."""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT id, symbol, direction, lot, open_price, open_time,
                   current_profit, ticket, source, is_manual
            FROM trades
            WHERE status = 'OPEN'
            ORDER BY open_time DESC
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not rows:
            return True, "Açık pozisyon yok", ""

        lines = [f"═══ AÇIK POZİSYONLAR ({len(rows)}) ═══"]
        for r in rows:
            manual = " [MANUEL]" if r.get("is_manual") else ""
            lines.append(
                f"  #{r['id']} {r['symbol']} {r['direction']} {r['lot']}lot "
                f"@ {r['open_price']}{manual} — "
                f"P/L: {r.get('current_profit', '?')} TRY"
            )
        return True, "\n".join(lines), ""
    except Exception as e:
        return False, "", str(e)


def handle_trade_history(cmd: dict) -> tuple[bool, str, str]:
    """İşlem geçmişi."""
    limit = cmd.get("limit", 20)
    symbol = cmd.get("symbol", "")

    try:
        query = """
            SELECT id, symbol, direction, lot, open_price, close_price,
                   open_time, close_time, profit, source, close_reason
            FROM trades
            WHERE status = 'CLOSED'
        """
        params = []
        if symbol:
            query += " AND symbol LIKE ?"
            params.append(f"%{symbol}%")
        query += f" ORDER BY close_time DESC LIMIT {limit}"

        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not rows:
            return True, "İşlem geçmişi boş", ""

        return True, json.dumps(rows, indent=2, ensure_ascii=False, default=str), ""
    except Exception as e:
        return False, "", str(e)


def handle_mt5_check(cmd: dict) -> tuple[bool, str, str]:
    """MT5 detaylı durum kontrolü."""
    info = {}

    # Process kontrolü
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process terminal64 -ErrorAction SilentlyContinue | "
             "Select-Object Id, CPU, WorkingSet64, StartTime | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            creationflags=0x08000000 if os.name == chr(110)+chr(116) else 0,
            startupinfo=_hidden_si(),
        )
        if result.stdout.strip():
            info["process"] = json.loads(result.stdout)
            info["running"] = True
        else:
            info["running"] = False
            info["process"] = None
    except Exception as e:
        info["running"] = False
        info["error"] = str(e)

    # MT5 config dosyası kontrolü
    mt5_data = USTAT_DIR / "mt5_data"
    if mt5_data.exists():
        info["mt5_data_exists"] = True
        info["mt5_files"] = [f.name for f in mt5_data.iterdir() if f.is_file()][:10]
    else:
        info["mt5_data_exists"] = False

    return True, json.dumps(info, indent=2, ensure_ascii=False, default=str), ""


def handle_agent_info(cmd: dict) -> tuple[bool, str, str]:
    """Ajan hakkında bilgi — yetenekler, sürüm, görevler."""
    info = {
        "version": AGENT_VERSION,
        "pid": os.getpid(),
        "uptime_seconds": int(time.time() - _agent_start_time),
        "commands_processed": _commands_processed,
        "capabilities": {
            # Mevcut (v1.0 uyumlu)
            "shell": "PowerShell/CMD/Python komutu çalıştır",
            "start_app": "ÜSTAT uygulamasını başlat",
            "stop_app": "ÜSTAT uygulamasını durdur",
            "restart_app": "ÜSTAT'ı yeniden başlat (akıllı)",
            "build": "Desktop npm run build",
            "screenshot": "Ekran görüntüsü al",
            "shortcut": "Masaüstü kısayolunu güncelle",
            "readlog": "Log dosyası oku",
            "processes": "Çalışan süreçleri listele",
            "ping": "Canlılık kontrolü",
            # Yeni (v2.0)
            "system_status": "Detaylı sistem durum raporu",
            "health_check": "Kapsamlı sağlık kontrolü",
            "alerts": "Alert listesi ve yönetimi",
            "db_backup": "Veritabanı yedeği al",
            "db_query": "Veritabanında READ-ONLY sorgu",
            "read_config": "Config dosyasını oku",
            "tail_log": "Birden fazla logdan son satırlar",
            "file_read": "Dosya oku (ÜSTAT dizini)",
            "file_write": "Dosya yaz (.agent/ dizini)",
            "list_files": "Dizin listele",
            "positions": "Açık pozisyonları listele",
            "trade_history": "İşlem geçmişi",
            "mt5_check": "MT5 detaylı durum kontrolü",
            "agent_info": "Ajan bilgi ve yetenekleri",
            # v3.0 Log Yonetim Sistemi
            "fresh_engine_log": "Engine log oku (FUSE bypass, regex, context)",
            "search_all_logs": "Tum loglarda eszamanli arama",
            "log_digest": "Engine log ozeti (kategorize edilmis olaylar)",
            "log_stats": "Tum log dosyalarinin gercek boyut/tarih bilgisi",
            "log_export": "Log parcasini .agent/results/'a export et",
        },
        "services": {
            "monitor": "Proaktif sistem izleme (30s aralık)",
            "cleaner": "Otomatik dosya temizleme (5dk aralık)",
            "self_healing": "API düşerse otomatik restart",
            "alert_system": "Kritik olay bildirim sistemi",
            "state_tracking": "Sistem durumu sürekli takip",
        },
        "responsibilities": [
            "ÜSTAT sisteminin 7/24 sağlığını izlemek",
            "Sorunları tespit edip mümkünse otomatik çözmek",
            "Claude'a sistem durumu hakkında bilgi vermek",
            "Veritabanı yedekleme ve bakım işlerini yürütmek",
            "Log dosyalarını yönetmek ve döndürmek",
            "MT5, API, Engine durumlarını sürekli kontrol etmek",
            "Kritik değişikliklerde alert oluşturmak",
            "Eski/geçici dosyaları temizlemek",
        ],
    }
    return True, json.dumps(info, indent=2, ensure_ascii=False), ""


# ═══════════════════════════════════════════════════════════════
# LOG YÖNETİM SİSTEMİ v3.0 — FUSE Önbellek Bypass
# ═══════════════════════════════════════════════════════════════
# Bu handler'lar FUSE/virtiofs mount cache sorununu tamamen çözer.
# Windows'taki gerçek dosyayı doğrudan okur, FUSE önbelleği atlanır.
# Claude (Linux VM) bu komutları kullanarak her zaman güncel veri alır.

import re as _re
import glob as _glob


def _get_engine_log_path(date_str: str = "") -> Optional[Path]:
    """Engine log dosyasının yolunu bul.
    date_str: 'YYYY-MM-DD' veya bos (bugun).
    """
    log_dir = USTAT_DIR / "logs"
    if date_str:
        target = log_dir / f"ustat_{date_str}.log"
        if target.exists():
            return target
        return None
    # Bugun
    today = datetime.now().strftime("%Y-%m-%d")
    target = log_dir / f"ustat_{today}.log"
    if target.exists():
        return target
    # En son log
    logs = sorted(log_dir.glob("ustat_*.log"))
    return logs[-1] if logs else None


def _get_all_log_paths() -> dict:
    """Tum log dosyalarinin yollarini dondur."""
    paths = {
        "api": USTAT_DIR / "api.log",
        "startup": USTAT_DIR / "startup.log",
        "agent": LOG_FILE,
        "electron": DESKTOP_DIR / "electron.log",
    }
    # Engine log (bugun)
    eng = _get_engine_log_path()
    if eng:
        paths["engine"] = eng
    return paths


def _tail_file_binary(filepath: Path, max_bytes: int = 5 * 1024 * 1024) -> str:
    """Dosyanin son max_bytes kadarini binary okur (buyuk log icin hizli).
    FUSE cache bypass: dosya boyutunu binary seek ile alir.
    """
    size = filepath.stat().st_size
    chunk = min(size, max_bytes)
    with open(filepath, "rb") as f:
        if chunk < size:
            f.seek(size - chunk)
            # Baslangici tam satira hizala
            f.readline()
        data = f.read()
    return data.decode("utf-8", errors="replace")


def handle_fresh_engine_log(cmd: dict) -> tuple:
    """Engine log oku — FUSE cache bypass, regex destekli, context satirlari.

    Parametreler:
        lines (int): Son N satir (varsayilan 200)
        search (str): Arama metni veya regex deseni
        regex (bool): True ise regex, False ise duz metin arama (varsayilan False)
        context (int): Eslesen satirlarin etrafinda +/- N context satiri (varsayilan 0)
        date (str): Tarih 'YYYY-MM-DD' (varsayilan bugun)
        head (bool): True ise bastan oku (varsayilan False = sondan)
        max_bytes (int): Maks byte okuma (varsayilan 5MB)

    Cikti:
        Eslesen satirlar, dosya bilgisi (boyut, tarih)
    """
    lines_count = cmd.get("lines", 200)
    search = cmd.get("search", "")
    use_regex = cmd.get("regex", False)
    context_n = cmd.get("context", 0)
    date_str = cmd.get("date", "")
    from_head = cmd.get("head", False)
    max_bytes = cmd.get("max_bytes", 5 * 1024 * 1024)

    log_path = _get_engine_log_path(date_str)
    if not log_path or not log_path.exists():
        return False, "", f"Engine log bulunamadi (tarih: {date_str or 'bugun'})"

    try:
        real_size = log_path.stat().st_size
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        # Binary tail okuma (buyuk dosyalar icin hizli)
        raw_text = _tail_file_binary(log_path, max_bytes)
        all_lines = raw_text.splitlines()

        header = f"[{log_path.name} | {real_size / (1024*1024):.1f}MB | son guncelleme: {mtime} | toplam: {len(all_lines)} satir]"

        if search:
            # Arama modu
            if use_regex:
                try:
                    pattern = _re.compile(search, _re.IGNORECASE)
                except _re.error as e:
                    return False, "", f"Regex hatasi: {e}"
                match_indices = [i for i, line in enumerate(all_lines) if pattern.search(line)]
            else:
                search_lower = search.lower()
                match_indices = [i for i, line in enumerate(all_lines) if search_lower in line.lower()]

            if not match_indices:
                return True, f"{header}\nArama: '{search}' -- 0 sonuc", ""

            # Context satirlari ile birlikte topla
            result_lines = []
            seen = set()
            for idx in match_indices[-lines_count:]:  # Son N eslesen
                start = max(0, idx - context_n)
                end = min(len(all_lines), idx + context_n + 1)
                for i in range(start, end):
                    if i not in seen:
                        seen.add(i)
                        marker = ">>>" if i == idx else "   "
                        result_lines.append((i, f"{marker} {all_lines[i]}"))

            result_lines.sort(key=lambda x: x[0])
            output_text = "\n".join(line for _, line in result_lines)
            return True, f"{header}\nArama: '{search}' -- {len(match_indices)} sonuc (son {min(lines_count, len(match_indices))} gosteriliyor)\n\n{output_text}", ""

        else:
            # Duz tail/head modu
            if from_head:
                selected = all_lines[:lines_count]
            else:
                selected = all_lines[-lines_count:]
            return True, f"{header}\n\n" + "\n".join(selected), ""

    except Exception as e:
        return False, "", f"Engine log okuma hatasi: {e}"


def handle_search_all_logs(cmd: dict) -> tuple:
    """TUM log dosyalarinda eszamanli arama.

    Parametreler:
        pattern (str): Arama deseni (zorunlu)
        regex (bool): Regex modu (varsayilan False)
        context (int): Context satir sayisi (varsayilan 1)
        max_results (int): Log basi maks sonuc (varsayilan 20)
        logs (list): Aranacak loglar (varsayilan hepsi)

    Cikti:
        Her log icin eslesen satirlar
    """
    pattern = cmd.get("pattern", "")
    if not pattern:
        return False, "", "Arama deseni (pattern) zorunlu"

    use_regex = cmd.get("regex", False)
    context_n = cmd.get("context", 1)
    max_results = cmd.get("max_results", 20)
    target_logs = cmd.get("logs", None)  # None = hepsi

    all_paths = _get_all_log_paths()
    if target_logs:
        all_paths = {k: v for k, v in all_paths.items() if k in target_logs}

    if use_regex:
        try:
            compiled = _re.compile(pattern, _re.IGNORECASE)
        except _re.error as e:
            return False, "", f"Regex hatasi: {e}"
    else:
        compiled = None

    output_parts = []
    total_matches = 0

    for name, path in all_paths.items():
        if not path.exists():
            continue

        try:
            # Son 5MB oku (buyuk loglar icin)
            raw = _tail_file_binary(path, 5 * 1024 * 1024)
            lines = raw.splitlines()
            real_size = path.stat().st_size

            if compiled:
                matches = [(i, line) for i, line in enumerate(lines) if compiled.search(line)]
            else:
                pattern_lower = pattern.lower()
                matches = [(i, line) for i, line in enumerate(lines) if pattern_lower in line.lower()]

            if not matches:
                continue

            total_matches += len(matches)
            section = [f"=== {name.upper()} ({real_size / (1024*1024):.1f}MB) — {len(matches)} eslesti ==="]

            for idx, match_line in matches[-max_results:]:
                # Context satirlari
                start = max(0, idx - context_n)
                end = min(len(lines), idx + context_n + 1)
                for i in range(start, end):
                    marker = ">>>" if i == idx else "   "
                    section.append(f"{marker} [{i+1}] {lines[i]}")
                if context_n > 0:
                    section.append("---")

            output_parts.append("\n".join(section))

        except Exception as e:
            output_parts.append(f"=== {name.upper()} === HATA: {e}")

    if not output_parts:
        return True, f"'{pattern}' icin hicbir log dosyasinda sonuc bulunamadi.", ""

    summary = f"ARAMA: '{pattern}' — toplam {total_matches} sonuc, {len(output_parts)} log dosyasinda\n\n"
    return True, summary + "\n\n".join(output_parts), ""


def handle_log_digest(cmd: dict) -> tuple:
    """Engine log ozeti — anahtar olaylari kategorize et.

    Parametreler:
        minutes (int): Son N dakika (varsayilan 60)
        categories (list): Filtre ['error','warning','trade','kill','signal','regime','confluence']
                           (varsayilan hepsi)

    Cikti:
        Kategorize edilmis olay ozeti
    """
    minutes = cmd.get("minutes", 60)
    categories = cmd.get("categories", None)  # None = hepsi

    log_path = _get_engine_log_path()
    if not log_path or not log_path.exists():
        return False, "", "Engine log bulunamadi"

    # Kategori desenleri
    CATEGORY_PATTERNS = {
        "error": _re.compile(r"ERROR|HATA|Exception|Traceback|CRITICAL", _re.IGNORECASE),
        "warning": _re.compile(r"WARNING|UYARI|DIKKAT", _re.IGNORECASE),
        "trade": _re.compile(r"EMIR|ORDER|TRADE|POZISYON|FILLED|CLOSED|SEND_ORDER|close_position", _re.IGNORECASE),
        "kill": _re.compile(r"KILL.?SWITCH|KS_|L1|L2|L3|kill_switch|ACIL", _re.IGNORECASE),
        "signal": _re.compile(r"SINYAL|SIGNAL|confluence|PASS|REJECT|candidate", _re.IGNORECASE),
        "regime": _re.compile(r"REJIM|REGIME|TREND|RANGE|VOLATILE|OLAY|regime_type", _re.IGNORECASE),
        "confluence": _re.compile(r"confluence|CONFLUENCE|conf_score|conf_pass", _re.IGNORECASE),
        "risk": _re.compile(r"DRAWDOWN|RISK|can_trade|MARGIN|floating_loss|daily_loss", _re.IGNORECASE),
    }

    if categories:
        active_patterns = {k: v for k, v in CATEGORY_PATTERNS.items() if k in categories}
    else:
        active_patterns = CATEGORY_PATTERNS

    try:
        raw = _tail_file_binary(log_path, 10 * 1024 * 1024)
        all_lines = raw.splitlines()

        # Zaman filtresi: son N dakika
        cutoff = datetime.now() - timedelta(minutes=minutes)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M")

        # Satirlari filtrele (zaman + kategori)
        categorized = {cat: [] for cat in active_patterns}
        for line in all_lines:
            # Zaman kontrolu (satir basindaki timestamp)
            if len(line) >= 16:
                line_time = line[:16]  # "2026-03-30 19:23" formatinda
                if line_time < cutoff_str:
                    continue

            for cat, pattern in active_patterns.items():
                if pattern.search(line):
                    categorized[cat].append(line)
                    break  # Bir kategori yeterli

        # Ozet olustur
        real_size = log_path.stat().st_size
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime).strftime("%H:%M:%S")
        header = f"LOG OZETI — Son {minutes} dakika | {log_path.name} ({real_size/(1024*1024):.1f}MB) | guncelleme: {mtime}"

        parts = [header, "=" * 60]
        total_events = 0
        for cat in ["error", "kill", "risk", "trade", "signal", "confluence", "regime", "warning"]:
            if cat not in categorized:
                continue
            events = categorized[cat]
            total_events += len(events)
            if events:
                parts.append(f"\n[{cat.upper()}] — {len(events)} olay")
                # Son 10 goster
                for ev in events[-10:]:
                    parts.append(f"  {ev[:200]}")
                if len(events) > 10:
                    parts.append(f"  ... ve {len(events) - 10} daha")

        if total_events == 0:
            parts.append(f"\nSon {minutes} dakikada hicbir kategori olayi bulunamadi.")

        parts.append(f"\nTOPLAM: {total_events} olay")
        return True, "\n".join(parts), ""

    except Exception as e:
        return False, "", f"Log digest hatasi: {e}"


def handle_log_stats(cmd: dict) -> tuple:
    """Tum log dosyalarinin GERCEK boyut ve metadata bilgileri.
    FUSE cache bypass: Windows'taki gercek dosya istatistiklerini dondurur.

    Cikti:
        Her log icin: isim, boyut, son guncelleme, satir sayisi (yaklasik)
    """
    try:
        log_dir = USTAT_DIR / "logs"
        results = []

        # Ana loglar
        main_logs = {
            "api.log": USTAT_DIR / "api.log",
            "startup.log": USTAT_DIR / "startup.log",
            "electron.log": DESKTOP_DIR / "electron.log",
            "agent.log": LOG_FILE,
        }

        for name, path in main_logs.items():
            if path.exists():
                stat = path.stat()
                size_mb = stat.st_size / (1024 * 1024)
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                results.append(f"  {name:30s} {size_mb:8.1f} MB  {mtime}")
            else:
                results.append(f"  {name:30s} --- YOK ---")

        # Engine loglar (son 7 gun)
        if log_dir.exists():
            engine_logs = sorted(log_dir.glob("ustat_*.log"), reverse=True)[:7]
            if engine_logs:
                results.append("\nEngine Loglar (son 7 gun):")
                for elog in engine_logs:
                    stat = elog.stat()
                    size_mb = stat.st_size / (1024 * 1024)
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    results.append(f"  {elog.name:30s} {size_mb:8.1f} MB  {mtime}")

        # Disk kullanimi
        total_log_size = 0
        if log_dir.exists():
            for f in log_dir.glob("*.log"):
                total_log_size += f.stat().st_size
        for _, path in main_logs.items():
            if path.exists():
                total_log_size += path.stat().st_size

        results.append(f"\nToplam log boyutu: {total_log_size / (1024*1024):.1f} MB")

        return True, "LOG ISTATISTIKLERI (Windows gercek degerler)\n" + "=" * 60 + "\nAna Loglar:\n" + "\n".join(results), ""

    except Exception as e:
        return False, "", f"Log stats hatasi: {e}"


def handle_log_export(cmd: dict) -> tuple:
    """Log parcasini .agent/results/'a export et — Claude okuyabilsin.

    Parametreler:
        log (str): Log adi ('engine', 'api', 'startup', 'electron', 'agent')
        lines (int): Son N satir (varsayilan 500)
        search (str): Opsiyonel arama filtresi
        output_file (str): Cikti dosya adi (varsayilan 'log_export.txt')
        max_bytes (int): Maks okuma boyutu (varsayilan 10MB)

    Cikti:
        Export edilen dosyanin yolu ve boyutu
    """
    log_name = cmd.get("log", "engine")
    lines_count = cmd.get("lines", 500)
    search = cmd.get("search", "")
    output_name = cmd.get("output_file", "log_export.txt")
    max_bytes = cmd.get("max_bytes", 10 * 1024 * 1024)

    all_paths = _get_all_log_paths()
    if log_name not in all_paths:
        available = ", ".join(all_paths.keys())
        return False, "", f"Log bulunamadi: '{log_name}'. Mevcut: {available}"

    log_path = all_paths[log_name]
    if not log_path.exists():
        return False, "", f"Log dosyasi mevcut degil: {log_path.name}"

    try:
        raw = _tail_file_binary(log_path, max_bytes)
        all_lines = raw.splitlines()

        real_size = log_path.stat().st_size
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        if search:
            search_lower = search.lower()
            filtered = [l for l in all_lines if search_lower in l.lower()]
            selected = filtered[-lines_count:]
            header = f"# Log Export: {log_path.name} | Arama: '{search}'\n# Boyut: {real_size/(1024*1024):.1f}MB | Guncelleme: {mtime}\n# Eslesen: {len(filtered)} satir, gosterilen: {len(selected)}\n"
        else:
            selected = all_lines[-lines_count:]
            header = f"# Log Export: {log_path.name}\n# Boyut: {real_size/(1024*1024):.1f}MB | Guncelleme: {mtime}\n# Toplam: {len(all_lines)} satir, gosterilen: son {len(selected)}\n"

        content = header + "\n".join(selected)

        # .agent/results/ altina yaz
        out_path = RESULT_DIR / output_name
        RESULT_DIR.mkdir(parents=True, exist_ok=True)

        # Atomic yazim
        tmp_path = out_path.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        if out_path.exists():
            out_path.unlink()
        tmp_path.rename(out_path)

        return True, f"Export basarili: {output_name} ({len(content)} byte, {len(selected)} satir)\nYol: .agent/results/{output_name}", ""

    except Exception as e:
        return False, "", f"Log export hatasi: {e}"


# ═══════════════════════════════════════════════════════════════
# FUSE BYPASS SİSTEMİ v1.0 — Tam Dosya Erişim Katmanı
# ═══════════════════════════════════════════════════════════════
# Log'lar dahil HER dosya için FUSE cache'i tamamen atlayan
# dosya okuma/metadata sistemi. Claude (Linux VM) bu komutları
# kullanarak Windows'taki gerçek dosyaya doğrudan erişir.
#
# Mimari:
#   Claude (Linux VM) → ajan komutu → Windows dosya sistemi
#                                          ↓
#                                    gerçek dosya oku
#                                          ↓
#                           .agent/results/fresh_<hash>.txt
#                                          ↓
#                        Claude Read tool (yeni dosya = cache yok)

import hashlib as _hashlib


def _unique_result_name(prefix: str, path: str) -> str:
    """Benzersiz sonuc dosyasi adi olustur.
    Her seferinde yeni dosya = FUSE cache'te karsiligi yok = taze veri.
    """
    ts = int(time.time() * 1000)
    h = _hashlib.md5(f"{path}{ts}".encode()).hexdigest()[:8]
    return f"{prefix}_{h}.txt"


def handle_fresh_file_read(cmd: dict) -> tuple:
    """HERHANGİ bir dosyayi oku — FUSE cache bypass.
    Dosyayi Windows'ta okur, benzersiz isimli yeni dosyaya yazar.
    Claude Read tool ile bu yeni dosyayi okudugunda FUSE cache sorunu olmaz.

    Parametreler:
        path (str): USTAT dizini icinde dosya yolu (zorunlu)
        lines (int): Son N satir (0 = tum dosya, varsayilan 0)
        head_lines (int): Bastan N satir (tail ile birlikte kullanilamaz)
        offset_bytes (int): Baslangic byte offset
        max_bytes (int): Maks okuma boyutu (varsayilan 10MB)
        encoding (str): Karakter kodlamasi (varsayilan utf-8)
        output_file (str): Cikti dosya adi (opsiyonel, otomatik olusturulur)

    Cikti:
        Dosya icerigi + metadata + .agent/results/ yolu
    """
    filepath = cmd.get("path", "")
    if not filepath:
        return False, "", "Dosya yolu (path) zorunlu"

    # Guvenlik: sadece USTAT_DIR altinda
    target = (USTAT_DIR / filepath).resolve()
    if not str(target).startswith(str(USTAT_DIR.resolve())):
        return False, "", "Guvenlik: Sadece USTAT dizini icindeki dosyalar okunabilir."

    if not target.exists():
        return False, "", f"Dosya bulunamadi: {filepath}"

    if target.is_dir():
        return False, "", f"Bu bir dizin, dosya degil: {filepath}"

    tail_lines = cmd.get("lines", 0)
    head_lines = cmd.get("head_lines", 0)
    offset_bytes = cmd.get("offset_bytes", 0)
    max_bytes = cmd.get("max_bytes", 10 * 1024 * 1024)
    encoding = cmd.get("encoding", "utf-8")
    output_name = cmd.get("output_file", "")

    try:
        stat = target.stat()
        real_size = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        # Dosya oku
        if real_size > max_bytes and tail_lines == 0 and head_lines == 0:
            # Buyuk dosya — son max_bytes oku
            content = _tail_file_binary(target, max_bytes)
        else:
            with open(target, "r", encoding=encoding, errors="replace") as f:
                if offset_bytes > 0:
                    f.seek(offset_bytes)
                content = f.read(max_bytes)

        # Satir filtreleme
        if tail_lines > 0:
            lines_list = content.splitlines()
            content = "\n".join(lines_list[-tail_lines:])
        elif head_lines > 0:
            lines_list = content.splitlines()
            content = "\n".join(lines_list[:head_lines])

        # Header bilgisi
        header = f"# FRESH_FILE_READ: {target.name}\n# Boyut: {real_size} byte ({real_size/(1024*1024):.2f} MB)\n# Guncelleme: {mtime}\n# Yol: {filepath}\n"

        full_content = header + "\n" + content

        # Benzersiz dosyaya yaz
        if not output_name:
            output_name = _unique_result_name("file", filepath)

        out_path = RESULT_DIR / output_name
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(".tmp")
        tmp_path.write_text(full_content, encoding="utf-8")
        if out_path.exists():
            out_path.unlink()
        tmp_path.rename(out_path)

        return True, (
            f"OK | {target.name} | {real_size} byte | {mtime}\n"
            f"Dosya: .agent/results/{output_name} ({len(full_content)} byte)\n"
            f"Claude icin: Read tool ile .agent/results/{output_name} dosyasini oku"
        ), ""

    except Exception as e:
        return False, "", f"fresh_file_read hatasi: {e}"


def handle_fresh_file_stat(cmd: dict) -> tuple:
    """Bir dosyanin GERCEK metadata'sini dondur — FUSE cache bypass.

    Parametreler:
        path (str): Dosya yolu (zorunlu)

    Cikti:
        Gercek boyut, mtime, atime, ctime, izinler
    """
    filepath = cmd.get("path", "")
    if not filepath:
        return False, "", "Dosya yolu (path) zorunlu"

    target = (USTAT_DIR / filepath).resolve()
    if not str(target).startswith(str(USTAT_DIR.resolve())):
        return False, "", "Guvenlik: Sadece USTAT dizini icinde."

    if not target.exists():
        return False, "", f"Dosya bulunamadi: {filepath}"

    try:
        stat = target.stat()
        info = {
            "path": filepath,
            "name": target.name,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "atime": datetime.fromtimestamp(stat.st_atime).strftime("%Y-%m-%d %H:%M:%S"),
            "ctime": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            "is_file": target.is_file(),
            "is_dir": target.is_dir(),
            "exists": True,
        }
        if target.is_file():
            # Satir sayisi tahmini (son 1MB'dan)
            try:
                chunk = _tail_file_binary(target, 1024 * 1024)
                lines_in_chunk = chunk.count("\n")
                chunk_size = len(chunk.encode("utf-8"))
                if chunk_size > 0 and stat.st_size > 0:
                    estimated_lines = int(lines_in_chunk * (stat.st_size / chunk_size))
                    info["estimated_lines"] = estimated_lines
            except Exception:
                pass

        return True, json.dumps(info, indent=2, ensure_ascii=False), ""

    except Exception as e:
        return False, "", f"fresh_file_stat hatasi: {e}"


def handle_fresh_dir_stat(cmd: dict) -> tuple:
    """Bir dizindeki TUM dosyalarin GERCEK metadata'sini dondur.

    Parametreler:
        path (str): Dizin yolu (varsayilan kok dizin)
        pattern (str): Glob deseni (varsayilan '*')
        recursive (bool): Alt dizinleri de tara (varsayilan False)
        sort_by (str): Siralama: 'name', 'size', 'mtime' (varsayilan 'name')

    Cikti:
        Her dosya icin: isim, boyut, mtime
    """
    dirpath = cmd.get("path", "")
    pattern = cmd.get("pattern", "*")
    recursive = cmd.get("recursive", False)
    sort_by = cmd.get("sort_by", "name")

    target = (USTAT_DIR / dirpath).resolve() if dirpath else USTAT_DIR
    if not str(target).startswith(str(USTAT_DIR.resolve())):
        return False, "", "Guvenlik: Sadece USTAT dizini icinde."

    if not target.is_dir():
        return False, "", f"Dizin bulunamadi: {dirpath}"

    try:
        if recursive:
            items = list(target.rglob(pattern))
        else:
            items = list(target.glob(pattern))

        entries = []
        total_size = 0
        for item in items[:500]:  # Maks 500 girdih
            try:
                stat = item.stat()
                rel = item.relative_to(USTAT_DIR)
                entry = {
                    "path": str(rel),
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
                entries.append(entry)
                if item.is_file():
                    total_size += stat.st_size
            except Exception:
                continue

        # Siralama
        if sort_by == "size":
            entries.sort(key=lambda e: e["size"], reverse=True)
        elif sort_by == "mtime":
            entries.sort(key=lambda e: e["mtime"], reverse=True)
        else:
            entries.sort(key=lambda e: e["name"])

        # Tablo formatinda cikti
        lines = [f"DIZIN: {dirpath or '.'} | {len(entries)} girdi | Toplam: {total_size/(1024*1024):.1f} MB"]
        lines.append("=" * 80)
        lines.append(f"{'Tip':4s} {'Boyut':>12s}  {'Guncelleme':19s}  Yol")
        lines.append("-" * 80)

        for e in entries:
            typ = "DIR" if e["type"] == "dir" else "FILE"
            if e["size"] > 1024 * 1024:
                sz = f"{e['size']/(1024*1024):.1f} MB"
            elif e["size"] > 1024:
                sz = f"{e['size']/1024:.1f} KB"
            else:
                sz = f"{e['size']} B"
            lines.append(f"{typ:4s} {sz:>12s}  {e['mtime']}  {e['path']}")

        return True, "\n".join(lines), ""

    except Exception as e:
        return False, "", f"fresh_dir_stat hatasi: {e}"


def handle_fresh_file_search(cmd: dict) -> tuple:
    """HERHANGİ bir dosyada arama yap — FUSE cache bypass.

    Parametreler:
        path (str): Dosya yolu (zorunlu)
        pattern (str): Arama deseni (zorunlu)
        regex (bool): Regex modu (varsayilan False)
        context (int): Context satir sayisi (varsayilan 0)
        max_results (int): Maks sonuc (varsayilan 50)
        max_bytes (int): Maks okuma boyutu (varsayilan 10MB)

    Cikti:
        Eslesen satirlar + context
    """
    filepath = cmd.get("path", "")
    pattern = cmd.get("pattern", "")
    if not filepath or not pattern:
        return False, "", "path ve pattern zorunlu"

    target = (USTAT_DIR / filepath).resolve()
    if not str(target).startswith(str(USTAT_DIR.resolve())):
        return False, "", "Guvenlik: Sadece USTAT dizini icinde."

    if not target.exists():
        return False, "", f"Dosya bulunamadi: {filepath}"

    use_regex = cmd.get("regex", False)
    context_n = cmd.get("context", 0)
    max_results = cmd.get("max_results", 50)
    max_bytes = cmd.get("max_bytes", 10 * 1024 * 1024)

    try:
        raw = _tail_file_binary(target, max_bytes)
        all_lines = raw.splitlines()

        real_size = target.stat().st_size
        mtime = datetime.fromtimestamp(target.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        if use_regex:
            try:
                compiled = _re.compile(pattern, _re.IGNORECASE)
            except _re.error as e:
                return False, "", f"Regex hatasi: {e}"
            match_indices = [i for i, line in enumerate(all_lines) if compiled.search(line)]
        else:
            pattern_lower = pattern.lower()
            match_indices = [i for i, line in enumerate(all_lines) if pattern_lower in line.lower()]

        header = f"[{target.name} | {real_size/(1024*1024):.1f}MB | {mtime}]"

        if not match_indices:
            return True, f"{header}\nArama: '{pattern}' — 0 sonuc", ""

        # Context ile topla
        result_lines = []
        seen = set()
        for idx in match_indices[-max_results:]:
            start = max(0, idx - context_n)
            end = min(len(all_lines), idx + context_n + 1)
            for i in range(start, end):
                if i not in seen:
                    seen.add(i)
                    marker = ">>>" if i == idx else "   "
                    result_lines.append((i, f"{marker} [{i+1}] {all_lines[i]}"))

        result_lines.sort(key=lambda x: x[0])
        output = "\n".join(line for _, line in result_lines)

        return True, f"{header}\nArama: '{pattern}' — {len(match_indices)} sonuc (son {min(max_results, len(match_indices))} gosteriliyor)\n\n{output}", ""

    except Exception as e:
        return False, "", f"fresh_file_search hatasi: {e}"


def handle_fresh_grep(cmd: dict) -> tuple:
    """Birden fazla dosyada arama — FUSE cache bypass grep.

    Parametreler:
        pattern (str): Arama deseni (zorunlu)
        path (str): Aranacak dizin (varsayilan kok)
        glob (str): Dosya filtresi (varsayilan '*.py')
        regex (bool): Regex modu (varsayilan False)
        max_results (int): Dosya basi maks sonuc (varsayilan 10)
        recursive (bool): Alt dizinleri de tara (varsayilan True)

    Cikti:
        Her eslesen dosya icin satirlar
    """
    search_pattern = cmd.get("pattern", "")
    if not search_pattern:
        return False, "", "Arama deseni (pattern) zorunlu"

    dirpath = cmd.get("path", "")
    file_glob = cmd.get("glob", "*.py")
    use_regex = cmd.get("regex", False)
    max_results = cmd.get("max_results", 10)
    recursive = cmd.get("recursive", True)

    target_dir = (USTAT_DIR / dirpath).resolve() if dirpath else USTAT_DIR
    if not str(target_dir).startswith(str(USTAT_DIR.resolve())):
        return False, "", "Guvenlik: Sadece USTAT dizini icinde."

    try:
        if recursive:
            files = list(target_dir.rglob(file_glob))
        else:
            files = list(target_dir.glob(file_glob))

        if use_regex:
            compiled = _re.compile(search_pattern, _re.IGNORECASE)
        else:
            compiled = None

        output_parts = []
        total_matches = 0
        files_matched = 0

        for fpath in sorted(files)[:200]:  # Maks 200 dosya
            if not fpath.is_file():
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()

                if compiled:
                    matches = [(i+1, line) for i, line in enumerate(lines) if compiled.search(line)]
                else:
                    pattern_lower = search_pattern.lower()
                    matches = [(i+1, line) for i, line in enumerate(lines) if pattern_lower in line.lower()]

                if matches:
                    rel = fpath.relative_to(USTAT_DIR)
                    files_matched += 1
                    total_matches += len(matches)
                    section = [f"--- {rel} ({len(matches)} eslesti) ---"]
                    for line_num, line_text in matches[:max_results]:
                        section.append(f"  [{line_num}] {line_text[:200]}")
                    if len(matches) > max_results:
                        section.append(f"  ... +{len(matches) - max_results} daha")
                    output_parts.append("\n".join(section))

            except Exception:
                continue

        if not output_parts:
            return True, f"'{search_pattern}' icin {len(files)} dosyada sonuc bulunamadi.", ""

        summary = f"GREP: '{search_pattern}' | {file_glob} | {files_matched}/{len(files)} dosyada {total_matches} eslesti\n\n"
        return True, summary + "\n\n".join(output_parts), ""

    except Exception as e:
        return False, "", f"fresh_grep hatasi: {e}"


# ═══════════════════════════════════════════════════════════════
# KOMUT DAĞITICI
# ═══════════════════════════════════════════════════════════════

HANDLERS = {
    # v1.0 uyumlu
    "shell": handle_shell,
    "start_app": handle_start_app,
    "stop_app": handle_stop_app,
    "build": handle_build,
    "screenshot": handle_screenshot,
    "shortcut": handle_shortcut,
    "status": handle_system_status,     # v2.0: artık detaylı
    "readlog": handle_readlog,
    "processes": handle_processes,
    "ping": handle_ping,
    # v2.0 yeni
    "restart_app": handle_restart_app,
    "system_status": handle_system_status,
    "health_check": handle_health_check,
    "alerts": handle_alerts,
    "db_backup": handle_db_backup,
    "db_query": handle_db_query,
    "read_config": handle_read_config,
    "tail_log": handle_tail_log,
    "file_read": handle_file_read,
    "file_write": handle_file_write,
    "list_files": handle_list_files,
    "positions": handle_positions,
    "trade_history": handle_trade_history,
    "mt5_check": handle_mt5_check,
    "agent_info": handle_agent_info,
    # v3.0 — Log Yönetim Sistemi (FUSE cache bypass)
    "fresh_engine_log": handle_fresh_engine_log,
    "search_all_logs": handle_search_all_logs,
    "log_digest": handle_log_digest,
    "log_stats": handle_log_stats,
    "log_export": handle_log_export,
    # v4.0 — FUSE Bypass Sistemi (tam dosya erisim)
    "fresh_file_read": handle_fresh_file_read,
    "fresh_file_stat": handle_fresh_file_stat,
    "fresh_dir_stat": handle_fresh_dir_stat,
    "fresh_file_search": handle_fresh_file_search,
    "fresh_grep": handle_fresh_grep,
}


# ═══════════════════════════════════════════════════════════════
# KOMUT İŞLEME
# ═══════════════════════════════════════════════════════════════

def process_command(cmd_file: Path):
    """Tek bir komutu işle — retry ve hata yönetimi ile."""
    global _commands_processed

    cmd = read_command(cmd_file)
    if cmd is None:
        cmd_file.unlink(missing_ok=True)
        return

    cmd_id = cmd.get("id", cmd_file.stem)
    cmd_type = cmd.get("type", "")
    created = cmd.get("created", "")

    # Sonuç zaten var mı?
    result_file = RESULT_DIR / f"{cmd_id}.json"
    if result_file.exists():
        cmd_file.unlink(missing_ok=True)
        return

    # Çok eski komutlar atla
    if created:
        try:
            created_time = datetime.fromisoformat(created)
            age = (datetime.now(timezone.utc) - created_time).total_seconds()
            if age > MAX_COMMAND_AGE:
                log(f"Eski komut atlandı: {cmd_id} ({int(age)}s)", "WARN")
                write_result(cmd_id, False, "", f"Komut çok eski ({int(age)}s > {MAX_COMMAND_AGE}s)")
                cmd_file.unlink(missing_ok=True)
                return
        except Exception:
            pass

    # Özel dahili komutlar (_revive vb.)
    if cmd_type.startswith("_"):
        cmd_file.unlink(missing_ok=True)
        return

    handler = HANDLERS.get(cmd_type)
    if handler is None:
        log(f"Bilinmeyen komut tipi: {cmd_type} ({cmd_id})", "ERROR")
        write_result(
            cmd_id, False, "",
            f"Bilinmeyen komut tipi: {cmd_type}\nDesteklenen: {', '.join(sorted(HANDLERS.keys()))}",
        )
        cmd_file.unlink(missing_ok=True)
        return

    log(f"Komut işleniyor: [{cmd_type}] {cmd_id}")
    start = time.time()

    # Retry mekanizması
    max_retry = cmd.get("retry", 1)
    last_error = ""

    for attempt in range(max_retry):
        try:
            success, output, error = handler(cmd)
            duration = time.time() - start

            if success or attempt == max_retry - 1:
                write_result(cmd_id, success, output, error, duration)
                status = "OK" if success else "ERROR"
                log(f"  Tamamlandı: [{cmd_type}] {cmd_id} → {status} ({duration:.1f}s)", status)

                # State güncelle
                _state_mgr.state.last_command_time = datetime.now(timezone.utc).isoformat()
                if not success:
                    _state_mgr.state.errors_count += 1
                break
            else:
                last_error = error
                log(f"  Retry {attempt + 1}/{max_retry}: [{cmd_type}] {cmd_id} — {error}", "WARN")
                time.sleep(1)

        except Exception as e:
            duration = time.time() - start
            last_error = f"{str(e)}\n{traceback.format_exc()}"

            if attempt == max_retry - 1:
                write_result(cmd_id, False, "", last_error, duration)
                log(f"  İstisna: [{cmd_type}] {cmd_id} → {e}", "ERROR")
                _state_mgr.state.errors_count += 1
            else:
                log(f"  Retry {attempt + 1}/{max_retry}: [{cmd_type}] {cmd_id} — {e}", "WARN")
                time.sleep(1)

    # Komutu sil
    cmd_file.unlink(missing_ok=True)
    _commands_processed += 1


# ═══════════════════════════════════════════════════════════════
# WINDOWS BAŞLANGIÇ KAYIT
# ═══════════════════════════════════════════════════════════════

def _auto_install_startup():
    """v5.9: Ajan başlatıldığında otomatik olarak Windows başlangıcına kaydet.
    Zaten kayıtlıysa sessizce geçer. Registry kontrolü yapar."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_QUERY_VALUE,
        )
        try:
            winreg.QueryValueEx(key, "USTAT_Agent")
            winreg.CloseKey(key)
            # Zaten kayıtlı — sessizce geç
            return
        except FileNotFoundError:
            winreg.CloseKey(key)
        # Kayıtlı değil — kaydet
        install_startup()
        log("Windows başlangıcına otomatik kaydedildi.", "INFO")
    except Exception:
        # Windows değilse veya winreg yoksa sessizce geç
        pass


def install_startup():
    """Windows başlangıcına ekle."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        vbs_path = str(USTAT_DIR / "start_agent.vbs")
        winreg.SetValueEx(key, "USTAT_Agent", 0, winreg.REG_SZ,
                          f'wscript.exe "{vbs_path}"')
        winreg.CloseKey(key)
        safe_print("  [OK] USTAT Ajan Windows baslangicina eklendi.")
        safe_print(f"    Kayit: HKCU\\...\\Run\\USTAT_Agent")
    except Exception as e:
        safe_print(f"  [HATA] Baslangic kaydi basarisiz: {e}")


def uninstall_startup():
    """Windows başlangıcından kaldır."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        winreg.DeleteValue(key, "USTAT_Agent")
        winreg.CloseKey(key)
        safe_print("  [OK] USTAT Ajan baslangictan kaldirildi.")
    except FileNotFoundError:
        safe_print("  -> Zaten kayitli degil.")
    except Exception as e:
        safe_print(f"  [HATA] Kaldirma basarisiz: {e}")


def print_status():
    """Anlık durum yazdır (--status parametresi)."""
    ensure_dirs()
    _state_mgr.update()
    safe_print(_state_mgr.get_summary())

    # Heartbeat kontrolü
    if HEARTBEAT_FILE.exists():
        try:
            hb = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
            ts = hb.get("timestamp", "?")
            alive = hb.get("alive", False)
            safe_print(f"\n  Ajan: {'CANLI' if alive else 'KAPALI'} — Son heartbeat: {ts}")
        except Exception:
            safe_print("\n  Ajan: heartbeat okunamadı")
    else:
        safe_print("\n  Ajan: ÇALIŞMIYOR (heartbeat dosyası yok)")


# ═══════════════════════════════════════════════════════════════
# ANA DÖNGÜ
# ═══════════════════════════════════════════════════════════════

_agent_start_time = time.time()
_commands_processed = 0

# Global servisler (main'den önce oluşturulur)
_alert_mgr = AlertManager()
_state_mgr = StateManager(_alert_mgr)


def main():
    """Ajan ana döngüsü — v2.0: çoklu thread, izleme, temizlik."""
    global _commands_processed

    # Argüman kontrolü
    if "--install" in sys.argv:
        install_startup()
        return
    if "--uninstall" in sys.argv:
        uninstall_startup()
        return
    if "--status" in sys.argv:
        print_status()
        return

    ensure_dirs()

    # v5.9: Windows başlangıcına otomatik kayıt — DEVRE DIŞI (v5.9.1)
    # Kullanıcı kararı: Uygulama sadece masaüstü kısayolundan açılacak.
    # Windows açılışında otomatik başlatma istenmiyor.
    # _auto_install_startup()

    # PID dosyası
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    safe_print("")
    safe_print("  ╔══════════════════════════════════════════════════╗")
    safe_print("  ║    ÜSTAT AJAN v3.0 — Akıllı Otonom Ajan         ║")
    safe_print("  ╠══════════════════════════════════════════════════╣")
    safe_print(f"  ║  PID      : {os.getpid():<37}║")
    safe_print(f"  ║  Klasör   : {str(USTAT_DIR):<37}║")
    safe_print(f"  ║  Komutlar : {len(HANDLERS)} adet                              ║")
    safe_print("  ║  Servisler: Monitor, Cleaner, Alerts, State     ║")
    safe_print("  ║  Durdurmak: Ctrl+C                              ║")
    safe_print("  ╚══════════════════════════════════════════════════╝")
    safe_print("")

    log(f"Ajan v{AGENT_VERSION} başlatıldı — PID {os.getpid()} — {len(HANDLERS)} komut tipi")

    # İlk durum taraması
    log("İlk sistem taraması yapılıyor...", "MONITOR")
    _state_mgr.update()
    safe_print(_state_mgr.get_summary())

    # Servisleri başlat
    heartbeat_svc = HeartbeatService()
    monitor = Monitor(_state_mgr, _alert_mgr)
    cleaner = Cleaner()

    heartbeat_svc.start()
    monitor.start()
    cleaner.start()

    _alert_mgr.fire(
        Severity.INFO, SystemComponent.AGENT,
        f"Ajan v{AGENT_VERSION} başlatıldı. {len(HANDLERS)} komut, 4 servis aktif.",
    )

    try:
        while True:
            try:
                # Ajan metrikleri güncelle (heartbeat ayrı thread'de)
                _state_mgr.state.agent_uptime_s = int(time.time() - _agent_start_time)
                _state_mgr.state.commands_processed = _commands_processed

                # Komut dosyalarını tara
                if CMD_DIR.exists():
                    cmd_files = sorted(CMD_DIR.glob("*.json"))
                    for cmd_file in cmd_files:
                        if cmd_file.name.startswith("_"):
                            continue
                        process_command(cmd_file)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                log(f"Döngü hatası: {e}", "ERROR")

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        safe_print("\n  → Ajan durduruluyor...")
        log("Ajan durduruldu (Ctrl+C)")
    finally:
        # Servisleri durdur
        monitor.stop()
        cleaner.stop()
        heartbeat_svc.stop()

        # v5.9: Temiz kapatma sinyali — VBS watchdog yeniden başlatmasın
        shutdown_signal = USTAT_DIR / ".agent" / "shutdown.signal"
        try:
            shutdown_signal.write_text(str(int(time.time())), encoding="utf-8")
        except Exception:
            pass

        # Temizlik
        PID_FILE.unlink(missing_ok=True)

        _alert_mgr.fire(
            Severity.INFO, SystemComponent.AGENT,
            f"Ajan kapatıldı. {_commands_processed} komut işlendi.",
        )

        safe_print("  [OK] Ajan kapatıldı.")


# ═══════════════════════════════════════════════════════════════
# WINDOWS SERVİS SINIFI (v5.9)
# ═══════════════════════════════════════════════════════════════

if _HAS_WIN32:
    class UstatAgentService(win32serviceutil.ServiceFramework):
        """ÜSTAT Ajan — Windows Service olarak çalışır.

        Kurulum:  python ustat_agent.py --service install
        Başlat:   python ustat_agent.py --service start
        Durdur:   python ustat_agent.py --service stop
        Kaldır:   python ustat_agent.py --service remove

        Veya:     net start USTATAgent / net stop USTATAgent
        """
        _svc_name_ = "USTATAgent"
        _svc_display_name_ = "ÜSTAT Ajan v3.0"
        _svc_description_ = (
            "ÜSTAT Trading Platform — Otonom arka plan ajanı. "
            "Claude ile Windows arasında köprü görevi görür. "
            "Komut işleme, sistem izleme, sağlık kontrolü."
        )

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._running = True

        def SvcStop(self):
            """Windows servis durdurma sinyali."""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self._running = False
            win32event.SetEvent(self.stop_event)
            log("Windows Service durdurma sinyali alındı.", "INFO")

        def SvcDoRun(self):
            """Windows Service ana döngüsü — main() ile aynı mantık."""
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            log(f"Windows Service başlatıldı: {self._svc_name_}", "INFO")
            self._run_agent()

        def _run_agent(self):
            """Ajan mantığını servis olarak çalıştır."""
            global _commands_processed

            ensure_dirs()
            PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

            log(f"Ajan v{AGENT_VERSION} başlatıldı (Windows Service) — PID {os.getpid()}")

            # İlk durum taraması
            _state_mgr.update()

            # Servisleri başlat
            heartbeat_svc = HeartbeatService()
            monitor_svc = Monitor(_state_mgr, _alert_mgr)
            cleaner_svc = Cleaner()

            heartbeat_svc.start()
            monitor_svc.start()
            cleaner_svc.start()

            _alert_mgr.fire(
                Severity.INFO, SystemComponent.AGENT,
                f"Ajan v{AGENT_VERSION} başlatıldı (Windows Service). {len(HANDLERS)} komut aktif.",
            )

            try:
                while self._running:
                    try:
                        _state_mgr.state.agent_uptime_s = int(time.time() - _agent_start_time)
                        _state_mgr.state.commands_processed = _commands_processed

                        if CMD_DIR.exists():
                            cmd_files = sorted(CMD_DIR.glob("*.json"))
                            for cmd_file in cmd_files:
                                if cmd_file.name.startswith("_"):
                                    continue
                                process_command(cmd_file)

                    except Exception as e:
                        log(f"Döngü hatası: {e}", "ERROR")

                    # Windows stop event kontrolü (POLL_INTERVAL kadar bekle)
                    rc = win32event.WaitForSingleObject(
                        self.stop_event, int(POLL_INTERVAL * 1000)
                    )
                    if rc == win32event.WAIT_OBJECT_0:
                        break

            finally:
                monitor_svc.stop()
                cleaner_svc.stop()
                heartbeat_svc.stop()
                PID_FILE.unlink(missing_ok=True)

                _alert_mgr.fire(
                    Severity.INFO, SystemComponent.AGENT,
                    f"Ajan kapatıldı (Windows Service). {_commands_processed} komut işlendi.",
                )
                log(f"Windows Service durduruldu. {_commands_processed} komut işlendi.")


def install_service():
    """DEVRE DIŞI (v5.9.1): Windows Service kurulumu YASAK.
    Kullanıcı kararı — uygulama sadece masaüstü kısayolundan açılacak."""
    safe_print("  [ENGEL] Windows Service kurulumu devre dışı bırakıldı (v5.9.1)")
    safe_print("  Uygulama sadece masaüstü kısayolundan açılacak.")
    return False
    # ── Aşağıdaki kod devre dışı bırakıldı ──
    if not _HAS_WIN32:
        safe_print("  [HATA] pywin32 yüklü değil. Önce kur: pip install pywin32")
        safe_print("         Sonra: python Scripts/pywin32_postinstall.py -install")
        return False

    try:
        # Servisi kur
        win32serviceutil.InstallService(
            UstatAgentService._svc_name_,
            UstatAgentService._svc_name_,
            UstatAgentService._svc_display_name_,
            startType=win32service.SERVICE_AUTO_START,
            description=UstatAgentService._svc_description_,
            exeName=sys.executable,
            exeArgs=f'"{os.path.abspath(__file__)}" --service run',
        )
        safe_print(f"  [OK] Servis kuruldu: {UstatAgentService._svc_name_}")
    except Exception as e:
        # Zaten kurulu olabilir — güncelle
        try:
            win32serviceutil.ChangeServiceConfig(
                UstatAgentService._svc_name_,
                UstatAgentService._svc_name_,
                startType=win32service.SERVICE_AUTO_START,
                displayName=UstatAgentService._svc_display_name_,
                description=UstatAgentService._svc_description_,
            )
            safe_print(f"  [OK] Servis güncellendi: {UstatAgentService._svc_name_}")
        except Exception as e2:
            safe_print(f"  [HATA] Servis kurulumu başarısız: {e2}")
            return False

    # Crash restart politikası — 3 kez restart, 10sn aralıkla
    try:
        subprocess.run(
            [
                "sc", "failure", UstatAgentService._svc_name_,
                "actions=", "restart/10000/restart/10000/restart/10000",
                "reset=", "86400",
            ],
            capture_output=True, timeout=10,
        )
        safe_print("  [OK] Crash restart politikası ayarlandı (10sn aralıkla 3 deneme)")
    except Exception:
        safe_print("  [UYARI] Crash restart politikası ayarlanamadı — manuel ayarla")

    # Servisi başlat
    try:
        win32serviceutil.StartService(UstatAgentService._svc_name_)
        safe_print(f"  [OK] Servis başlatıldı: {UstatAgentService._svc_name_}")
    except Exception as e:
        safe_print(f"  [UYARI] Servis başlatılamadı (zaten çalışıyor olabilir): {e}")

    safe_print("")
    safe_print("  Servis yönetimi:")
    safe_print("    net start USTATAgent    — Başlat")
    safe_print("    net stop USTATAgent     — Durdur")
    safe_print("    sc query USTATAgent     — Durum kontrol")
    safe_print("    sc delete USTATAgent    — Kaldır")
    return True


def remove_service():
    """Windows Service'i kaldır."""
    if not _HAS_WIN32:
        safe_print("  [HATA] pywin32 yüklü değil.")
        return

    try:
        win32serviceutil.StopService(UstatAgentService._svc_name_)
    except Exception:
        pass

    try:
        win32serviceutil.RemoveService(UstatAgentService._svc_name_)
        safe_print(f"  [OK] Servis kaldırıldı: {UstatAgentService._svc_name_}")
    except Exception as e:
        safe_print(f"  [HATA] Servis kaldırılamadı: {e}")


if __name__ == "__main__":
    # --service parametresi: Windows Service modu
    if "--service" in sys.argv:
        if not _HAS_WIN32:
            safe_print("  [HATA] pywin32 yüklü değil!")
            safe_print("  Kur: pip install pywin32")
            sys.exit(1)

        idx = sys.argv.index("--service")
        action = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else ""

        if action == "install":
            install_service()
        elif action == "remove":
            remove_service()
        elif action == "start":
            try:
                win32serviceutil.StartService(UstatAgentService._svc_name_)
                safe_print("  [OK] Servis başlatıldı.")
            except Exception as e:
                safe_print(f"  [HATA] {e}")
        elif action == "stop":
            try:
                win32serviceutil.StopService(UstatAgentService._svc_name_)
                safe_print("  [OK] Servis durduruldu.")
            except Exception as e:
                safe_print(f"  [HATA] {e}")
        elif action == "run":
            # Windows SCM bu parametreyle çağırır
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(UstatAgentService)
            servicemanager.StartServiceCtrlDispatcher()
        else:
            safe_print(f"  Bilinmeyen service komutu: {action}")
            safe_print("  Kullanım: --service install|remove|start|stop|run")
    else:
        main()