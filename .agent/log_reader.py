"""
ÜSTAT Log Reader v1.0 — Claude için Yüksek Seviyeli Log Okuma Aracı

Bu script, FUSE/virtiofs mount cache sorununu tamamen atlayarak
Windows'taki gerçek log dosyalarına ajan üzerinden erişir.

Claude bu scripti doğrudan çalıştırabilir veya
claude_bridge.py üzerinden ajan komutlarını kullanabilir.

Kullanım Örnekleri:
  # Son 100 satır engine log
  python .agent/log_reader.py tail 100

  # L2 kill-switch aramak
  python .agent/log_reader.py search "KILL-SWITCH L2"

  # Regex ile arama (context satirlari ile)
  python .agent/log_reader.py search "KILL.*L[23]" --regex --context 3

  # Son 30 dakikanın özeti
  python .agent/log_reader.py digest 30

  # Sadece hata ve kill olayları
  python .agent/log_reader.py digest 60 --categories error,kill

  # Tüm loglarda arama
  python .agent/log_reader.py searchall "Exception"

  # Log boyutları
  python .agent/log_reader.py stats

  # Engine logu export et (Claude okuyabilsin)
  python .agent/log_reader.py export engine --lines 1000

  # API logunda hata ara ve export et
  python .agent/log_reader.py export api --search "ERROR" --lines 200
"""

import sys
import os

# Claude Bridge'i import et
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from claude_bridge import send_command


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    action = sys.argv[1]
    args = sys.argv[2:]

    if action == "tail":
        # tail [lines] [--search X] [--date YYYY-MM-DD]
        kwargs = {}
        if args and not args[0].startswith("--"):
            try:
                kwargs["lines"] = int(args[0])
                args = args[1:]
            except ValueError:
                pass
        _parse_flags(args, kwargs)
        result = send_command("fresh_engine_log", **kwargs)

    elif action == "search":
        # search "PATTERN" [--regex] [--context N]
        if not args:
            print("Kullanim: log_reader.py search PATTERN [--regex] [--context N]")
            sys.exit(1)
        kwargs = {"search": args[0], "lines": 50}
        _parse_flags(args[1:], kwargs)
        result = send_command("fresh_engine_log", **kwargs)

    elif action == "searchall":
        # searchall "PATTERN" [--regex] [--context N]
        if not args:
            print("Kullanim: log_reader.py searchall PATTERN [--regex] [--context N]")
            sys.exit(1)
        kwargs = {"pattern": args[0]}
        _parse_flags(args[1:], kwargs)
        result = send_command("search_all_logs", **kwargs)

    elif action == "digest":
        # digest [minutes] [--categories a,b,c]
        kwargs = {}
        if args and not args[0].startswith("--"):
            try:
                kwargs["minutes"] = int(args[0])
                args = args[1:]
            except ValueError:
                pass
        _parse_flags(args, kwargs)
        result = send_command("log_digest", **kwargs)

    elif action == "stats":
        result = send_command("log_stats")

    elif action == "export":
        # export [log_name] [--lines N] [--search X] [--output FILE]
        kwargs = {}
        if args and not args[0].startswith("--"):
            kwargs["log"] = args[0]
            args = args[1:]
        _parse_flags(args, kwargs)
        result = send_command("log_export", **kwargs)

    else:
        print(f"Bilinmeyen eylem: {action}")
        print("Eylemler: tail, search, searchall, digest, stats, export")
        sys.exit(1)

    # Sonucu göster
    if result.get("success"):
        dur = result.get("duration_seconds", "?")
        print(f"[OK {dur}s]")
        if result.get("output"):
            print(result["output"])
    else:
        print(f"[HATA]")
        if result.get("error"):
            print(f"  {result['error']}")
        if result.get("output"):
            print(result["output"])


def _parse_flags(args, kwargs):
    """Ortak flag'leri parse et."""
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
        elif args[i] == "--lines" and i + 1 < len(args):
            kwargs["lines"] = int(args[i + 1]); i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            kwargs["output_file"] = args[i + 1]; i += 2
        elif args[i] == "--max" and i + 1 < len(args):
            kwargs["max_results"] = int(args[i + 1]); i += 2
        elif args[i] == "--categories" and i + 1 < len(args):
            kwargs["categories"] = args[i + 1].split(","); i += 2
        else:
            i += 1


if __name__ == "__main__":
    main()
