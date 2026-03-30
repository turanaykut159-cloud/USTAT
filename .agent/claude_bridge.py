"""
Claude Köprü v4.0 — Linux VM'den Windows Ajanına komut gönder ve sonuç al.

Yenilikler (v4.0):
  - Log Yönetim Sistemi v3.0 (FUSE cache bypass)
  - 30+ komut tipi
  - Retry mekanizması (3 deneme)
  - Otomatik canlandırma
  - Genişletilmiş CLI arayüzü

Kullanım (bash ile):
  python .agent/claude_bridge.py ping
  python .agent/claude_bridge.py shell "dir"
  python .agent/claude_bridge.py start_app
  python .agent/claude_bridge.py stop_app
  python .agent/claude_bridge.py restart_app
  python .agent/claude_bridge.py build
  python .agent/claude_bridge.py screenshot
  python .agent/claude_bridge.py status
  python .agent/claude_bridge.py system_status
  python .agent/claude_bridge.py health_check
  python .agent/claude_bridge.py alerts [unresolved|all|resolve]
  python .agent/claude_bridge.py db_backup
  python .agent/claude_bridge.py db_query "SELECT ..."
  python .agent/claude_bridge.py read_config [key]
  python .agent/claude_bridge.py tail_log [files...]
  python .agent/claude_bridge.py file_read <path>
  python .agent/claude_bridge.py list_files [path] [pattern]
  python .agent/claude_bridge.py positions
  python .agent/claude_bridge.py trade_history [symbol] [limit]
  python .agent/claude_bridge.py mt5_check
  python .agent/claude_bridge.py agent_info
  python .agent/claude_bridge.py readlog api|startup|agent [lines]
  python .agent/claude_bridge.py processes [filter]
  python .agent/claude_bridge.py shell "Get-Process node" --shell powershell

  # v4.0 — Log Yönetim Sistemi (FUSE cache bypass)
  python .agent/claude_bridge.py fresh_engine_log [lines] [--search PATTERN] [--regex] [--context N]
  python .agent/claude_bridge.py search_all_logs "PATTERN" [--regex] [--context N]
  python .agent/claude_bridge.py log_digest [minutes] [--categories error,kill,trade]
  python .agent/claude_bridge.py log_stats
  python .agent/claude_bridge.py log_export [log_name] [--lines N] [--search PATTERN] [--output FILE]

  # v4.0 — FUSE Bypass Sistemi (tam dosya erisim)
  python .agent/claude_bridge.py fresh_file_read <path> [--lines N] [--head N]
  python .agent/claude_bridge.py fresh_file_stat <path>
  python .agent/claude_bridge.py fresh_dir_stat [path] [--pattern *.py] [--sort size|mtime]
  python .agent/claude_bridge.py fresh_file_search <path> <pattern> [--regex] [--context N]
  python .agent/claude_bridge.py fresh_grep <pattern> [--glob *.py] [--path dir/]
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
USTAT_DIR = SCRIPT_DIR.parent
CMD_DIR = SCRIPT_DIR / "commands"
RESULT_DIR = SCRIPT_DIR / "results"
HEARTBEAT_FILE = SCRIPT_DIR / "heartbeat.json"
REVIVE_FLAG = SCRIPT_DIR / "revive.flag"

WAIT_TIMEOUT = 60       # sonuç bekleme zaman aşımı (saniye)
POLL_INTERVAL = 0.5     # sonuç kontrol aralığı
REVIVE_WAIT = 15        # ajan yeniden başlatma sonrası bekleme (saniye)
MAX_RETRIES = 3         # maksimum deneme sayısı


def is_agent_alive() -> bool:
    """Ajan canlı mı kontrol et.
    Cross-mount (Linux↔Windows) ortamında iki sorun oluşabiliyor:
    1. Dosya sonunda null byte'lar (\x00) kalabiliyor
    2. mtime güncellenmeyebiliyor
    Bu yüzden: null'ları temizle, timestamp'ten yaş hesapla.
    """
    if not HEARTBEAT_FILE.exists():
        return False
    try:
        raw = HEARTBEAT_FILE.read_text(encoding="utf-8")
        # Null byte'ları temizle (cross-mount artifact)
        raw = raw.strip().rstrip("\x00").strip()
        if not raw:
            return False

        data = json.loads(raw)
        if not data.get("alive", False):
            return False
        ts = data.get("timestamp", "")
        if ts:
            hb_time = datetime.fromisoformat(ts)
            age = (datetime.now(timezone.utc) - hb_time).total_seconds()
            return age < 30
        return True
    except (json.JSONDecodeError, ValueError):
        # JSON hâlâ bozuksa — timestamp'i regex ile çıkarmayı dene
        try:
            import re
            m = re.search(r'"timestamp":\s*"([^"]+)"', raw)
            if m and '"alive": true' in raw:
                hb_time = datetime.fromisoformat(m.group(1))
                age = (datetime.now(timezone.utc) - hb_time).total_seconds()
                return age < 30
        except Exception:
            pass
        return False
    except Exception:
        return False


def get_agent_info() -> dict:
    """Heartbeat'ten ajan bilgisi al."""
    try:
        if HEARTBEAT_FILE.exists():
            return json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def request_revive() -> bool:
    """Ajanı yeniden başlatma isteği gönder."""
    try:
        REVIVE_FLAG.write_text(
            json.dumps({
                "requested": datetime.now(timezone.utc).isoformat(),
                "reason": "heartbeat_stale",
            }, indent=2),
            encoding="utf-8",
        )

        revive_cmd = {
            "id": f"revive_{int(time.time())}",
            "type": "_revive",
            "vbs_path": str(USTAT_DIR / "start_agent.vbs"),
            "created": datetime.now(timezone.utc).isoformat(),
        }
        revive_file = CMD_DIR / "_revive_request.json"
        CMD_DIR.mkdir(parents=True, exist_ok=True)
        revive_file.write_text(
            json.dumps(revive_cmd, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def wait_for_agent(timeout: int = REVIVE_WAIT) -> bool:
    """Ajanın canlanmasını bekle."""
    start = time.time()
    while time.time() - start < timeout:
        if is_agent_alive():
            return True
        time.sleep(1)
    return False


def send_command(cmd_type: str, retry: int = 0, **kwargs) -> dict:
    """Ajana komut gönder ve sonucu bekle."""
    CMD_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    # Ajan canlılık kontrolü
    if not is_agent_alive():
        if retry < MAX_RETRIES:
            print(f"⚠ Ajan yanıt vermiyor. Canlandırma deneniyor... ({retry + 1}/{MAX_RETRIES})")
            request_revive()
            if wait_for_agent():
                print("✓ Ajan tekrar aktif!")
                return send_command(cmd_type, retry=retry + 1, **kwargs)
        return {
            "success": False,
            "output": "",
            "error": (
                "AJAN ÇALIŞMIYOR ve otomatik canlandırma başarısız.\n"
                "  → Windows'ta 'start_agent.vbs' çift tıklayın\n"
                "  → veya: cd Desktop\\USTAT && python ustat_agent.py"
            ),
        }

    # Komut oluştur
    cmd_id = f"cmd_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    cmd_data = {
        "id": cmd_id,
        "type": cmd_type,
        "created": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }

    # Komut dosyası yaz
    cmd_file = CMD_DIR / f"{cmd_id}.json"
    cmd_file.write_text(json.dumps(cmd_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Sonuç bekle
    result_file = RESULT_DIR / f"{cmd_id}.json"
    start = time.time()

    # Bazı komutlar daha uzun sürer
    timeout = WAIT_TIMEOUT
    if cmd_type in ("restart_app", "build", "db_backup"):
        timeout = 120

    while time.time() - start < timeout:
        if result_file.exists():
            try:
                result = json.loads(result_file.read_text(encoding="utf-8"))
                result_file.unlink(missing_ok=True)
                return result
            except Exception as e:
                return {"success": False, "output": "", "error": f"Sonuç okunamadı: {e}"}
        time.sleep(POLL_INTERVAL)

    # Zaman aşımı
    cmd_file.unlink(missing_ok=True)
    return {
        "success": False,
        "output": "",
        "error": f"Zaman aşımı ({timeout}s). Ajan komutu işlemedi.",
    }


def main():
    """CLI kullanım — v3.0: genişletilmiş komut seti."""
    if len(sys.argv) < 2:
        info = get_agent_info()
        version = info.get("version", "?")
        alive = "CANLI" if info.get("alive") else "KAPALI"
        caps = info.get("capabilities", [])

        print(f"\n  ÜSTAT Ajan Köprüsü v4.0 — Ajan: {alive} (v{version})")
        print(f"  Kullanım: python claude_bridge.py <komut_tipi> [argümanlar...]\n")
        print("  Temel Komutlar:")
        print("    ping                      — Ajan canlı mı?")
        print("    shell <komut>             — Shell komutu çalıştır")
        print("    start_app                 — ÜSTAT'ı başlat")
        print("    stop_app                  — ÜSTAT'ı durdur")
        print("    restart_app               — ÜSTAT'ı yeniden başlat")
        print("    build                     — Desktop build")
        print("    screenshot [dosya]        — Ekran görüntüsü")
        print("    shortcut                  — Masaüstü kısayolu")
        print()
        print("  Durum & İzleme:")
        print("    system_status             — Detaylı sistem durumu")
        print("    health_check              — Kapsamlı sağlık kontrolü")
        print("    alerts [mod]              — Alert yönetimi")
        print("    mt5_check                 — MT5 durum kontrolü")
        print("    agent_info                — Ajan yetenekleri")
        print()
        print("  Veritabanı:")
        print("    positions                 — Açık pozisyonlar")
        print("    trade_history [sembol]    — İşlem geçmişi")
        print("    db_backup                 — Veritabanı yedeği")
        print("    db_query <SQL>            — SELECT sorgusu")
        print()
        print("  Dosya & Log:")
        print("    readlog <ad> [satır]      — Log oku")
        print("    tail_log [dosyalar...]    — Çoklu log oku")
        print("    file_read <yol>           — Dosya oku")
        print("    list_files [yol] [desen]  — Dizin listele")
        print("    read_config [anahtar]     — Config oku")
        print()
        print("  Log Yönetim Sistemi v3.0 (FUSE cache bypass):")
        print("    fresh_engine_log [N]      — Engine log son N satır (varsayılan 200)")
        print("      --search PATTERN        — Metin/regex arama")
        print("      --regex                 — Regex modu aktif")
        print("      --context N             — Eşleşen satır etrafı ±N satır")
        print("      --date YYYY-MM-DD       — Belirli tarih logu")
        print("    search_all_logs PATTERN   — TÜM loglarda arama")
        print("      --regex --context N     — Regex + context")
        print("    log_digest [dakika]       — Son N dk log özeti (varsayılan 60)")
        print("      --categories a,b,c      — error,kill,trade,signal,regime,risk")
        print("    log_stats                 — Tüm logların GERÇEK boyutları")
        print("    log_export [log_adı]      — Log export et (.agent/results/)")
        print("      --lines N --search X    — Satır limiti + filtre")
        print()
        print("  Süreç:")
        print("    processes [filtre]        — Süreçleri listele")
        sys.exit(0)

    cmd_type = sys.argv[1]

    # Argümanları komut tipine göre hazırla
    kwargs = {}

    if cmd_type == "shell" and len(sys.argv) > 2:
        kwargs["command"] = sys.argv[2]
        if "--shell" in sys.argv:
            idx = sys.argv.index("--shell")
            kwargs["shell"] = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "powershell"

    elif cmd_type == "readlog" and len(sys.argv) > 2:
        kwargs["file"] = sys.argv[2]
        if len(sys.argv) > 3:
            kwargs["lines"] = int(sys.argv[3])

    elif cmd_type == "processes" and len(sys.argv) > 2:
        kwargs["filter"] = sys.argv[2]

    elif cmd_type == "screenshot" and len(sys.argv) > 2:
        kwargs["filename"] = sys.argv[2]

    # v2.0 komutları
    elif cmd_type == "db_query" and len(sys.argv) > 2:
        kwargs["query"] = sys.argv[2]

    elif cmd_type == "read_config" and len(sys.argv) > 2:
        kwargs["key"] = sys.argv[2]

    elif cmd_type == "alerts" and len(sys.argv) > 2:
        kwargs["mode"] = sys.argv[2]  # unresolved | all | resolve
        if len(sys.argv) > 3:
            kwargs["component"] = sys.argv[3]

    elif cmd_type == "tail_log" and len(sys.argv) > 2:
        kwargs["files"] = sys.argv[2:]

    elif cmd_type == "file_read" and len(sys.argv) > 2:
        kwargs["path"] = sys.argv[2]
        if len(sys.argv) > 3:
            kwargs["lines"] = int(sys.argv[3])

    elif cmd_type == "list_files":
        if len(sys.argv) > 2:
            kwargs["path"] = sys.argv[2]
        if len(sys.argv) > 3:
            kwargs["pattern"] = sys.argv[3]

    elif cmd_type == "trade_history":
        if len(sys.argv) > 2:
            kwargs["symbol"] = sys.argv[2]
        if len(sys.argv) > 3:
            kwargs["limit"] = int(sys.argv[3])

    elif cmd_type == "positions":
        pass  # Argüman yok

    elif cmd_type == "mt5_check":
        pass

    elif cmd_type == "agent_info":
        pass

    elif cmd_type == "health_check":
        pass

    elif cmd_type == "system_status":
        pass

    elif cmd_type == "db_backup":
        pass

    # v4.0 — Log Yönetim Sistemi komutları
    elif cmd_type == "fresh_engine_log":
        # fresh_engine_log [lines] [--search X] [--regex] [--context N] [--date YYYY-MM-DD]
        args = sys.argv[2:]
        if args and not args[0].startswith("--"):
            try:
                kwargs["lines"] = int(args[0])
                args = args[1:]
            except ValueError:
                pass
        i = 0
        while i < len(args):
            if args[i] == "--search" and i + 1 < len(args):
                kwargs["search"] = args[i + 1]; i += 2
            elif args[i] == "--regex":
                kwargs["regex"] = True; i += 1
            elif args[i] == "--context" and i + 1 < len(args):
                kwargs["context"] = int(args[i + 1]); i += 2
            elif args[i] == "--date" and i + 1 < len(args):
                kwargs["date"] = args[i + 1]; i += 2
            elif args[i] == "--head":
                kwargs["head"] = True; i += 1
            else:
                i += 1

    elif cmd_type == "search_all_logs":
        if len(sys.argv) > 2:
            kwargs["pattern"] = sys.argv[2]
        args = sys.argv[3:]
        i = 0
        while i < len(args):
            if args[i] == "--regex":
                kwargs["regex"] = True; i += 1
            elif args[i] == "--context" and i + 1 < len(args):
                kwargs["context"] = int(args[i + 1]); i += 2
            elif args[i] == "--max" and i + 1 < len(args):
                kwargs["max_results"] = int(args[i + 1]); i += 2
            else:
                i += 1

    elif cmd_type == "log_digest":
        args = sys.argv[2:]
        if args and not args[0].startswith("--"):
            try:
                kwargs["minutes"] = int(args[0])
                args = args[1:]
            except ValueError:
                pass
        i = 0
        while i < len(args):
            if args[i] == "--categories" and i + 1 < len(args):
                kwargs["categories"] = args[i + 1].split(","); i += 2
            else:
                i += 1

    elif cmd_type == "log_stats":
        pass  # Argüman yok

    elif cmd_type == "log_export":
        args = sys.argv[2:]
        if args and not args[0].startswith("--"):
            kwargs["log"] = args[0]
            args = args[1:]
        i = 0
        while i < len(args):
            if args[i] == "--lines" and i + 1 < len(args):
                kwargs["lines"] = int(args[i + 1]); i += 2
            elif args[i] == "--search" and i + 1 < len(args):
                kwargs["search"] = args[i + 1]; i += 2
            elif args[i] == "--output" and i + 1 < len(args):
                kwargs["output_file"] = args[i + 1]; i += 2
            else:
                i += 1

    # v4.0 — FUSE Bypass Sistemi komutlari
    elif cmd_type == "fresh_file_read":
        if len(sys.argv) > 2:
            kwargs["path"] = sys.argv[2]
        args = sys.argv[3:]
        i = 0
        while i < len(args):
            if args[i] == "--lines" and i + 1 < len(args):
                kwargs["lines"] = int(args[i + 1]); i += 2
            elif args[i] == "--head" and i + 1 < len(args):
                kwargs["head_lines"] = int(args[i + 1]); i += 2
            elif args[i] == "--output" and i + 1 < len(args):
                kwargs["output_file"] = args[i + 1]; i += 2
            else:
                i += 1

    elif cmd_type == "fresh_file_stat":
        if len(sys.argv) > 2:
            kwargs["path"] = sys.argv[2]

    elif cmd_type == "fresh_dir_stat":
        args = sys.argv[2:]
        if args and not args[0].startswith("--"):
            kwargs["path"] = args[0]
            args = args[1:]
        i = 0
        while i < len(args):
            if args[i] == "--pattern" and i + 1 < len(args):
                kwargs["pattern"] = args[i + 1]; i += 2
            elif args[i] == "--sort" and i + 1 < len(args):
                kwargs["sort_by"] = args[i + 1]; i += 2
            elif args[i] == "--recursive":
                kwargs["recursive"] = True; i += 1
            else:
                i += 1

    elif cmd_type == "fresh_file_search":
        if len(sys.argv) > 2:
            kwargs["path"] = sys.argv[2]
        if len(sys.argv) > 3:
            kwargs["pattern"] = sys.argv[3]
        args = sys.argv[4:]
        i = 0
        while i < len(args):
            if args[i] == "--regex":
                kwargs["regex"] = True; i += 1
            elif args[i] == "--context" and i + 1 < len(args):
                kwargs["context"] = int(args[i + 1]); i += 2
            elif args[i] == "--max" and i + 1 < len(args):
                kwargs["max_results"] = int(args[i + 1]); i += 2
            else:
                i += 1

    elif cmd_type == "fresh_grep":
        if len(sys.argv) > 2:
            kwargs["pattern"] = sys.argv[2]
        args = sys.argv[3:]
        i = 0
        while i < len(args):
            if args[i] == "--glob" and i + 1 < len(args):
                kwargs["glob"] = args[i + 1]; i += 2
            elif args[i] == "--path" and i + 1 < len(args):
                kwargs["path"] = args[i + 1]; i += 2
            elif args[i] == "--regex":
                kwargs["regex"] = True; i += 1
            elif args[i] == "--max" and i + 1 < len(args):
                kwargs["max_results"] = int(args[i + 1]); i += 2
            elif args[i] == "--recursive":
                kwargs["recursive"] = True; i += 1
            else:
                i += 1

    # Gönder ve bekle
    print(f"→ Komut gönderiliyor: {cmd_type}...")
    result = send_command(cmd_type, **kwargs)

    # Sonuç göster
    if result.get("success"):
        dur = result.get("duration_seconds", "?")
        print(f"✓ Başarılı ({dur}s)")
        if result.get("output"):
            print(result["output"])
    else:
        print(f"✖ Başarısız")
        if result.get("error"):
            print(f"  Hata: {result['error']}")
        if result.get("output"):
            print(result["output"])


if __name__ == "__main__":
    main()
