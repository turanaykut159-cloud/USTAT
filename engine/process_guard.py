"""ÜSTAT v5.9 — Process Guard (Hayalet Process Koruma Modülü).

Görev:
  1. Başlangıçta önceki oturumdan kalan hayalet process'leri tespit ve temizle
  2. Çalışma sırasında tüm spawned PID'leri kaydet (.ustat_pids.json)
  3. Kapanışta tüm alt process'leri güvenle sonlandır (tree kill)

Mimari:
  - start_ustat.py'den BAĞIMSIZ modül — import edip 3 fonksiyon çağırmak yeterli
  - Windows'a özgü: taskkill, wmic, netstat kullanır
  - Hiçbir engine/API koduna dokunmaz — sadece OS-level process yönetimi

Kullanım:
  from engine.process_guard import ProcessGuard

  guard = ProcessGuard(ustat_dir="C:/Users/pc/Desktop/USTAT", api_port=8000)
  guard.startup_cleanup()          # Başlangıçta çağır (hayalet avı)
  guard.register_pid("electron", pid)  # PID kaydet
  guard.shutdown_all()             # Kapanışta çağır (hepsini öldür)
"""

import os
import sys
import json
import time
import logging

logger = logging.getLogger("ustat.process_guard")

# Sessiz konsol çıktısı için — start_ustat.py kendi slog'unu kullanır
_slog_fn = None


def _log(msg: str) -> None:
    """Hem logger'a hem slog'a yaz (varsa)."""
    logger.info(msg)
    if _slog_fn:
        _slog_fn(f"[GUARD] {msg}")


# ── Windows sabitleri ─────────────────────────────────────────────
CREATE_NO_WINDOW = 0x08000000


class ProcessGuard:
    """ÜSTAT process yaşam döngüsü koruyucusu.

    Üç aşamalı koruma:
      1. startup_cleanup(): Önceki oturumun hayalet process'lerini öldür
      2. register_pid(): Çalışma sırasında PID kaydet
      3. shutdown_all(): Kapanışta kayıtlı tüm PID'leri tree-kill et
    """

    def __init__(self, ustat_dir: str, api_port: int = 8000, slog=None):
        self.ustat_dir = ustat_dir
        self.api_port = api_port
        self.pid_file = os.path.join(ustat_dir, ".ustat_pids.json")
        self._pids: dict[str, int] = {}  # role → PID
        self._my_pid = os.getpid()

        global _slog_fn
        if slog:
            _slog_fn = slog

    # ══════════════════════════════════════════════════════════════
    # AŞAMA 1: BAŞLANGIÇ TEMİZLİĞİ
    # ══════════════════════════════════════════════════════════════

    def startup_cleanup(self) -> dict:
        """Önceki oturumdan kalan hayalet process'leri bul ve öldür.

        Sıralı temizlik:
          1. PID registry dosyasından eski PID'leri oku → öldür
          2. Port 8000'de dinleyen orphan uvicorn'u öldür
          3. Orphan Electron process'leri öldür
          4. Orphan MT5 Python API process'leri öldür
          5. TIME_WAIT socket'leri raporla (OS otomatik temizler)

        Returns:
            dict: Temizlik raporu {"killed": [...], "errors": [...]}
        """
        report = {"killed": [], "errors": [], "clean": True}

        _log(f"Başlangıç temizliği başlatıldı (kendi PID: {self._my_pid})")

        # ── 1. PID Registry'den eski process'leri temizle ────────
        old_pids = self._read_pid_file()
        if old_pids:
            _log(f"Önceki oturum PID'leri bulundu: {old_pids}")
            for role, pid in old_pids.items():
                if pid == self._my_pid:
                    continue  # Kendimizi öldürme
                if self._is_pid_alive(pid):
                    killed = self._tree_kill(pid, f"eski {role}")
                    if killed:
                        report["killed"].append({"role": role, "pid": pid})
                        report["clean"] = False
                    else:
                        report["errors"].append(
                            f"{role} (PID {pid}) öldürülemedi"
                        )
            # Eski dosyayı temizle
            self._delete_pid_file()
        else:
            _log("Önceki oturum PID dosyası yok — temiz başlangıç")

        # ── 2. Port üzerinde orphan process kontrolü ─────────────
        port_pid = self._get_port_listener(self.api_port)
        if port_pid and port_pid != self._my_pid:
            _log(f"Port {self.api_port} orphan process tespit edildi (PID {port_pid})")
            killed = self._tree_kill(port_pid, f"orphan port {self.api_port}")
            if killed:
                report["killed"].append({"role": "orphan_api", "pid": port_pid})
                report["clean"] = False
                # Port'un serbest kalmasını bekle
                for _ in range(10):
                    if not self._is_port_open(self.api_port):
                        break
                    time.sleep(0.3)

        # ── 3. Orphan Electron process kontrolü ──────────────────
        orphan_electrons = self._find_orphan_electrons()
        for pid in orphan_electrons:
            if pid == self._my_pid:
                continue
            _log(f"Orphan Electron tespit edildi (PID {pid})")
            killed = self._tree_kill(pid, "orphan electron")
            if killed:
                report["killed"].append({"role": "orphan_electron", "pid": pid})
                report["clean"] = False

        # ── 4. Orphan MT5 Python process'leri ────────────────────
        # MT5 Python API (MetaTrader5 paketi) dahili bir terminal64.exe
        # process'i başlatır. Python process ölse bile terminal ayakta kalabilir.
        orphan_mt5 = self._find_orphan_mt5_python()
        for pid in orphan_mt5:
            if pid == self._my_pid:
                continue
            _log(f"Orphan MT5-Python process tespit edildi (PID {pid})")
            killed = self._tree_kill(pid, "orphan mt5-python")
            if killed:
                report["killed"].append({"role": "orphan_mt5", "pid": pid})
                report["clean"] = False

        # ── 5. TIME_WAIT socket raporu (sadece log) ─────────────
        # TIME_WAIT socket'leri OS tarafından 2-4 dakikada temizlenir.
        # Kill edemeyiz, sadece raporlayıp SO_REUSEADDR ile çalışırız.
        tw_count = self._count_time_wait_sockets(self.api_port)
        if tw_count > 0:
            _log(f"Port {self.api_port}: {tw_count} TIME_WAIT socket tespit edildi "
                 f"— OS 2-4dk içinde temizleyecek, SO_REUSEADDR aktif")

        # Rapor
        if report["clean"]:
            _log("Temizlik tamamlandı — hayalet process yok")
        else:
            _log(
                f"Temizlik tamamlandı — {len(report['killed'])} hayalet öldürüldü"
            )

        return report

    # ══════════════════════════════════════════════════════════════
    # AŞAMA 2: PID KAYIT
    # ══════════════════════════════════════════════════════════════

    def register_pid(self, role: str, pid: int) -> None:
        """Bir process PID'ini kaydet.

        Args:
            role: Process rolü ("main", "subprocess", "electron")
            pid: OS process ID
        """
        self._pids[role] = pid
        self._write_pid_file()
        _log(f"PID kaydedildi: {role}={pid}")

    def register_self(self) -> None:
        """Ana process'in (start_ustat.py) PID'ini kaydet."""
        self.register_pid("main", self._my_pid)

    # ══════════════════════════════════════════════════════════════
    # AŞAMA 3: KAPANIŞ TEMİZLİĞİ
    # ══════════════════════════════════════════════════════════════

    def shutdown_all(self) -> None:
        """Kayıtlı tüm process'leri sonlandır (kendisi hariç).

        Öncelik sırası:
          1. Electron (UI kapansın)
          2. Subprocess (API + Engine)
          3. Port temizliği (garanti — LISTENING + ESTABLISHED)
          4. api.pid dosyası temizliği
          5. PID dosyası temizliği

        NOT: Electron PID'i alt process tarafından dosyaya yazılır,
        ana process'in _pids dict'inde olmayabilir. Bu yüzden hem
        dict'ten hem dosyadan kontrol edilir.
        """
        _log("Kapanış temizliği başlatıldı")

        # Dosyadan güncel PID'leri oku (alt process'in yazdığı electron dahil)
        file_pids = self._read_pid_file()
        # Dict + dosya birleştir (dosya daha güncel)
        all_pids = {**self._pids, **file_pids}

        # Electron'u önce öldür
        e_pid = all_pids.get("electron")
        if e_pid and e_pid != self._my_pid and self._is_pid_alive(e_pid):
            self._tree_kill(e_pid, "electron")

        # Subprocess'i öldür
        s_pid = all_pids.get("subprocess")
        if s_pid and s_pid != self._my_pid and self._is_pid_alive(s_pid):
            self._tree_kill(s_pid, "subprocess")

        # Port hala açıksa zorla kapat (LISTENING + ESTABLISHED bağlantılar)
        port_pid = self._get_port_listener(self.api_port)
        if port_pid and port_pid != self._my_pid:
            self._tree_kill(port_pid, f"port {self.api_port}")

        # Port'a bağlı ESTABLISHED bağlantıları olan process'leri de öldür
        established_pids = self._get_port_established_pids(self.api_port)
        for pid in established_pids:
            if pid != self._my_pid and self._is_pid_alive(pid):
                self._tree_kill(pid, f"established-conn port {self.api_port}")

        # api.pid dosyasını temizle
        api_pid_path = os.path.join(self.ustat_dir, "api.pid")
        try:
            if os.path.exists(api_pid_path):
                os.remove(api_pid_path)
        except Exception:
            pass

        # PID dosyasını temizle
        self._delete_pid_file()
        _log("Kapanış temizliği tamamlandı")

    # ══════════════════════════════════════════════════════════════
    # DAHİLİ YARDIMCILAR
    # ══════════════════════════════════════════════════════════════

    def _get_electron_pid_from_file(self) -> int | None:
        """PID dosyasından Electron PID'ini oku.

        Electron PID'i ALT PROCESS tarafından dosyaya yazılır,
        ana process'in _pids dict'inde bulunmaz. Bu metod
        dosyadan okuyarak PID'i döndürür.
        """
        pids = self._read_pid_file()
        electron_pid = pids.get("electron")
        if electron_pid and electron_pid != self._my_pid:
            if self._is_pid_alive(electron_pid):
                return electron_pid
        return None

    def _tree_kill(self, pid: int, label: str = "") -> bool:
        """Process'i ve TÜM alt ağacını öldür (taskkill /F /T).

        Args:
            pid: Hedef process ID
            label: Log için açıklama

        Returns:
            True ise process öldürüldü
        """
        import subprocess

        try:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            output = (result.stdout + result.stderr).upper()
            if "SUCCESS" in output or "NOT FOUND" in output:
                _log(f"Tree-kill başarılı: {label} (PID {pid})")
                return True
            else:
                _log(f"Tree-kill başarısız: {label} (PID {pid}) — {result.stderr.strip()}")
                return False
        except subprocess.TimeoutExpired:
            _log(f"Tree-kill timeout: {label} (PID {pid})")
            return False
        except Exception as e:
            _log(f"Tree-kill hata: {label} (PID {pid}) — {e}")
            return False

    def _is_pid_alive(self, pid: int) -> bool:
        """PID hala yaşıyor mu? (Windows uyumlu)."""
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False  # Process yok
        except PermissionError:
            return True  # Process var ama erişim yok → yaşıyor
        except OSError:
            return False  # Diğer OS hataları → ölü say

    def _get_port_listener(self, port: int) -> int | None:
        """Belirtilen portu dinleyen process'in PID'ini döndür."""
        import subprocess

        try:
            result = subprocess.run(
                f'netstat -ano | findstr ":{port} " | findstr "LISTENING"',
                capture_output=True,
                text=True,
                shell=True,
                timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )
            for line in result.stdout.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 5:
                    pid_str = parts[-1]
                    if pid_str.isdigit() and pid_str != "0":
                        return int(pid_str)
        except Exception:
            pass
        return None

    def _is_port_open(self, port: int) -> bool:
        """Port açık mı kontrol et."""
        import socket

        for host, family in [
            ("127.0.0.1", socket.AF_INET),
            ("::1", socket.AF_INET6),
        ]:
            try:
                with socket.socket(family, socket.SOCK_STREAM) as s:
                    s.settimeout(0.3)
                    if s.connect_ex((host, port)) == 0:
                        return True
            except Exception:
                pass
        return False

    def _find_orphan_electrons(self) -> list[int]:
        """USTAT ile ilişkili orphan Electron process'lerini bul.

        wmic ile electron.exe process'lerini arar,
        komut satırında USTAT geçenleri döndürür.
        """
        import subprocess

        pids = []
        try:
            # wmic ile electron process'lerini bul
            result = subprocess.run(
                [
                    "wmic",
                    "process",
                    "where",
                    "name like '%electron%'",
                    "get",
                    "processid,commandline",
                    "/format:csv",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )

            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("Node"):
                    continue
                # CSV format: Node,CommandLine,ProcessId
                # veya bazen sadece ProcessId
                upper = line.upper()
                if "USTAT" in upper or "USTAT_API_MODE" in upper:
                    # Son virgülden sonraki değer PID
                    parts = line.split(",")
                    for part in reversed(parts):
                        part = part.strip()
                        if part.isdigit():
                            pid = int(part)
                            if pid != self._my_pid:
                                pids.append(pid)
                            break
        except FileNotFoundError:
            # wmic yoksa (bazı Windows sürümlerinde kaldırıldı)
            # PowerShell alternatifi dene
            pids = self._find_orphan_electrons_ps()
        except Exception as e:
            _log(f"Electron tarama hatası: {e}")

        return pids

    def _find_orphan_electrons_ps(self) -> list[int]:
        """PowerShell ile orphan Electron process'lerini bul (wmic alternatifi)."""
        import subprocess

        pids = []
        try:
            ps_cmd = (
                "Get-Process -Name '*electron*' -ErrorAction SilentlyContinue | "
                "Where-Object { $_.CommandLine -like '*USTAT*' -or "
                "$_.CommandLine -like '*USTAT_API_MODE*' } | "
                "Select-Object -ExpandProperty Id"
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    if pid != self._my_pid:
                        pids.append(pid)
        except Exception as e:
            _log(f"PowerShell Electron tarama hatası: {e}")

        return pids

    def _find_orphan_mt5_python(self) -> list[int]:
        """ÜSTAT ile ilişkili orphan Python-MT5 process'lerini bul.

        MetaTrader5 Python paketi, initialize() çağrıldığında dahili bir
        metatrader.exe veya terminal64.exe child process başlatır. Ana Python
        process ölse bile bu child hayatta kalabilir.

        Hedef: Komut satırında 'terminal64' veya 'metatrader' geçen VE
        parent'ı artık yaşamayan Python process'leri.
        """
        import subprocess

        pids = []
        try:
            # wmic ile Python process'lerini bul (komut satırında mt5 geçen)
            result = subprocess.run(
                [
                    "wmic", "process", "where",
                    "name='python.exe' or name='pythonw.exe'",
                    "get", "processid,commandline",
                    "/format:csv",
                ],
                capture_output=True, text=True, timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("Node"):
                    continue
                upper = line.upper()
                # MT5 bridge'i veya MetaTrader5 paketini kullanan Python process
                if ("MT5" in upper or "METATRADER" in upper) and "USTAT" in upper:
                    parts = line.split(",")
                    for part in reversed(parts):
                        part = part.strip()
                        if part.isdigit():
                            pid = int(part)
                            if pid != self._my_pid:
                                pids.append(pid)
                            break
        except FileNotFoundError:
            pass  # wmic yoksa atla
        except Exception as e:
            _log(f"MT5-Python tarama hatası: {e}")
        return pids

    def _count_time_wait_sockets(self, port: int) -> int:
        """Belirtilen portta TIME_WAIT durumundaki socket sayısını döndür.

        TIME_WAIT socket'leri öldürülemez — OS (Windows) tarafından
        2-4 dakikada otomatik temizlenir. Bu metod sadece RAPORLAMA amaçlıdır.
        Uvicorn SO_REUSEADDR kullandığından TIME_WAIT socket'ler yeni
        bağlantıyı engellemez.
        """
        import subprocess

        try:
            result = subprocess.run(
                f'netstat -ano | findstr ":{port} " | findstr "TIME_WAIT"',
                capture_output=True, text=True, shell=True, timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )
            count = 0
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    count += 1
            return count
        except Exception:
            return 0

    def _get_port_established_pids(self, port: int) -> list[int]:
        """Belirtilen portta ESTABLISHED bağlantısı olan PID'leri döndür.

        Kapanış sırasında LISTENING process öldürülse bile, istemci tarafında
        (WebSocket vb.) ESTABLISHED bağlantılar kalabilir. Bu metod onları bulur.
        """
        import subprocess

        pids = set()
        try:
            result = subprocess.run(
                f'netstat -ano | findstr ":{port} " | findstr "ESTABLISHED"',
                capture_output=True, text=True, shell=True, timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )
            for line in result.stdout.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 5:
                    pid_str = parts[-1]
                    if pid_str.isdigit() and pid_str != "0":
                        pids.add(int(pid_str))
        except Exception:
            pass
        return list(pids)

    # ── PID Dosya İşlemleri ──────────────────────────────────────

    def _write_pid_file(self) -> None:
        """PID kayıtlarını diske yaz (atomic)."""
        tmp_path = self.pid_file + ".tmp"
        try:
            data = {
                "timestamp": time.time(),
                "pids": self._pids,
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            # Atomic rename (Windows'ta hedef varsa önce sil)
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
            os.rename(tmp_path, self.pid_file)
        except Exception as e:
            _log(f"PID dosyası yazma hatası: {e}")
            # Temp dosyayı temizle
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    def _read_pid_file(self) -> dict[str, int]:
        """Önceki oturumun PID kayıtlarını oku."""
        try:
            if not os.path.exists(self.pid_file):
                return {}
            with open(self.pid_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            pids = data.get("pids", {})
            ts = data.get("timestamp", 0)
            age_hours = (time.time() - ts) / 3600

            # 24 saatten eski PID dosyası — muhtemelen geçersiz
            if age_hours > 24:
                _log(f"PID dosyası çok eski ({age_hours:.1f} saat) — yoksayılıyor")
                self._delete_pid_file()
                return {}

            # int'e çevir (JSON string olabilir)
            return {role: int(pid) for role, pid in pids.items()}
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            _log(f"PID dosyası bozuk: {e}")
            self._delete_pid_file()
            return {}
        except Exception as e:
            _log(f"PID dosyası okuma hatası: {e}")
            return {}

    def _delete_pid_file(self) -> None:
        """PID dosyasını sil."""
        try:
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
        except Exception:
            pass
