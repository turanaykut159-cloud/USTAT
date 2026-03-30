"""
ÜSTAT File Proxy v1.0 — FUSE Cache Bypass Dosya Erişim Sistemi

Bu sistem, FUSE/virtiofs mount cache sorununu KÖKTEN çözer.
Tüm dosya okuma işlemlerini Windows'taki ajan üzerinden yönlendirir.
FUSE'a HİÇ dokunmaz — cache sorunu tamamen ortadan kalkar.

Mimari:
  Claude (Linux VM)
    ↓ file_proxy.py
    ↓ claude_bridge.py → send_command()
    ↓ .agent/commands/ → JSON dosya
    ↓ Windows ajan (ustat_agent.py) → gerçek dosya oku
    ↓ .agent/results/ → benzersiz isimli yeni dosya
    ↓ Claude Read tool → yeni dosya = FUSE cache yok = taze veri

Kullanım:
  # Dosya oku (son 100 satır)
  python .agent/file_proxy.py read logs/ustat_2026-03-30.log --lines 100

  # Dosya oku (tamamı, .agent/results/'a export)
  python .agent/file_proxy.py read engine/ogul.py

  # Dosya metadata
  python .agent/file_proxy.py stat engine/baba.py

  # Dizin listesi (gerçek boyutlar)
  python .agent/file_proxy.py ls logs/
  python .agent/file_proxy.py ls engine/ --sort size

  # Dosya içinde arama
  python .agent/file_proxy.py search engine/baba.py "kill_switch" --context 3

  # Çoklu dosyada grep
  python .agent/file_proxy.py grep "check_risk_limits" --glob "*.py"
  python .agent/file_proxy.py grep "KILL_SWITCH" --glob "*.log" --path logs/

  # Karşılaştırma: FUSE vs gerçek boyut
  python .agent/file_proxy.py compare logs/
"""

import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from claude_bridge import send_command


def cmd_read(args):
    """Dosya oku."""
    if not args:
        print("Kullanim: file_proxy.py read <dosya_yolu> [--lines N] [--head N]")
        return
    kwargs = {"path": args[0]}
    _parse_flags(args[1:], kwargs)
    result = send_command("fresh_file_read", **kwargs)
    _print_result(result)


def cmd_stat(args):
    """Dosya metadata."""
    if not args:
        print("Kullanim: file_proxy.py stat <dosya_yolu>")
        return
    result = send_command("fresh_file_stat", path=args[0])
    _print_result(result)


def cmd_ls(args):
    """Dizin listesi."""
    kwargs = {}
    if args and not args[0].startswith("--"):
        kwargs["path"] = args[0]
        args = args[1:]
    _parse_flags(args, kwargs)
    result = send_command("fresh_dir_stat", **kwargs)
    _print_result(result)


def cmd_search(args):
    """Dosya icinde arama."""
    if len(args) < 2:
        print("Kullanim: file_proxy.py search <dosya_yolu> <desen> [--regex] [--context N]")
        return
    kwargs = {"path": args[0], "pattern": args[1]}
    _parse_flags(args[2:], kwargs)
    result = send_command("fresh_file_search", **kwargs)
    _print_result(result)


def cmd_grep(args):
    """Coklu dosyada arama."""
    if not args:
        print("Kullanim: file_proxy.py grep <desen> [--glob *.py] [--path dir/] [--regex]")
        return
    kwargs = {"pattern": args[0]}
    _parse_flags(args[1:], kwargs)
    result = send_command("fresh_grep", **kwargs)
    _print_result(result)


def cmd_compare(args):
    """FUSE cache vs gercek boyut karsilastirmasi."""
    path = args[0] if args else ""
    result = send_command("fresh_dir_stat", path=path, sort_by="size")
    if result.get("success"):
        print("[WINDOWS GERCEK DEGERLER]")
        print(result.get("output", ""))

        # Simdi FUSE'dan oku
        fuse_base = os.path.join(SCRIPT_DIR, "..", path) if path else os.path.join(SCRIPT_DIR, "..")
        fuse_base = os.path.abspath(fuse_base)
        if os.path.isdir(fuse_base):
            print("\n[FUSE CACHE DEGERLERI]")
            for item in sorted(os.listdir(fuse_base)):
                fpath = os.path.join(fuse_base, item)
                try:
                    st = os.stat(fpath)
                    sz = st.st_size
                    if sz > 1024 * 1024:
                        sz_str = f"{sz/(1024*1024):.1f} MB"
                    elif sz > 1024:
                        sz_str = f"{sz/1024:.1f} KB"
                    else:
                        sz_str = f"{sz} B"
                    tp = "DIR " if os.path.isdir(fpath) else "FILE"
                    print(f"  {tp} {sz_str:>12s}  {item}")
                except Exception:
                    pass
        print("\nFark varsa = FUSE cache stale")
    else:
        _print_result(result)


def _parse_flags(args, kwargs):
    """Ortak flag parse."""
    i = 0
    while i < len(args):
        if args[i] == "--lines" and i + 1 < len(args):
            kwargs["lines"] = int(args[i + 1]); i += 2
        elif args[i] == "--head" and i + 1 < len(args):
            kwargs["head_lines"] = int(args[i + 1]); i += 2
        elif args[i] == "--regex":
            kwargs["regex"] = True; i += 1
        elif args[i] == "--context" and i + 1 < len(args):
            kwargs["context"] = int(args[i + 1]); i += 2
        elif args[i] == "--sort" and i + 1 < len(args):
            kwargs["sort_by"] = args[i + 1]; i += 2
        elif args[i] == "--glob" and i + 1 < len(args):
            kwargs["glob"] = args[i + 1]; i += 2
        elif args[i] == "--path" and i + 1 < len(args):
            kwargs["path"] = args[i + 1]; i += 2
        elif args[i] == "--pattern" and i + 1 < len(args):
            kwargs["pattern"] = args[i + 1]; i += 2
        elif args[i] == "--max" and i + 1 < len(args):
            kwargs["max_results"] = int(args[i + 1]); i += 2
        elif args[i] == "--recursive":
            kwargs["recursive"] = True; i += 1
        elif args[i] == "--output" and i + 1 < len(args):
            kwargs["output_file"] = args[i + 1]; i += 2
        elif args[i] == "--encoding" and i + 1 < len(args):
            kwargs["encoding"] = args[i + 1]; i += 2
        else:
            i += 1


def _print_result(result):
    if result.get("success"):
        dur = result.get("duration_seconds", "?")
        print(f"[OK {dur}s]")
        if result.get("output"):
            print(result["output"])
    else:
        print("[HATA]")
        if result.get("error"):
            print(f"  {result['error']}")
        if result.get("output"):
            print(result["output"])


COMMANDS = {
    "read": cmd_read,
    "stat": cmd_stat,
    "ls": cmd_ls,
    "search": cmd_search,
    "grep": cmd_grep,
    "compare": cmd_compare,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        print("Komutlar: " + ", ".join(COMMANDS.keys()))
        sys.exit(0)

    action = sys.argv[1]
    if action not in COMMANDS:
        print(f"Bilinmeyen komut: {action}")
        print("Komutlar: " + ", ".join(COMMANDS.keys()))
        sys.exit(1)

    COMMANDS[action](sys.argv[2:])


if __name__ == "__main__":
    main()
