#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ÜSTAT Plus V6.0 — Etki Raporu Aracı

Bir dosya veya dosya::fonksiyon için neden-sonuç raporu üretir.
C2/C3 değişikliklerde pre-commit tarafından zorunlu kılınır.

Kullanım:
  python tools/impact_report.py engine/baba.py
  python tools/impact_report.py engine/baba.py::check_risk_limits

Çıktı: reports/impact_<YYYY-MM-DD>_<dosya>.md
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("HATA: PyYAML gerekli. `pip install pyyaml`", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "governance" / "protected_assets.yaml"
REPORTS_DIR = REPO_ROOT / "reports"


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {}
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}


def _classify(file_rel: str, fn: str | None, manifest: dict[str, Any]) -> tuple[str, list[str]]:
    """Returns (change_class, linked_ids)"""
    linked: list[str] = []
    cls = "C1"

    # Protected functions
    for item in manifest.get("protected_functions", []) or []:
        if item.get("file") == file_rel and item.get("function") == fn:
            linked.append(item.get("id", ""))
            linked.extend(item.get("linked_rules", []) or [])
            cls = "C3"  # function logic change

    # Protected files
    for item in manifest.get("protected_files", []) or []:
        if item.get("path") == file_rel:
            linked.append(f"FILE:{file_rel}")
            if cls == "C1":
                cls = item.get("change_class", "C2")

    # Protected rules whose location mentions this file/function
    for rule in manifest.get("protected_rules", []) or []:
        loc = rule.get("location", "")
        if file_rel in loc:
            if fn is None or fn in loc or "::" not in loc:
                linked.append(rule.get("id", ""))
                if cls not in ("C3",):
                    cls = "C3"  # rule change is C3

    # Dedupe
    linked = [x for x in dict.fromkeys(linked) if x]
    return cls, linked


def _find_callers(file_rel: str, fn: str) -> list[str]:
    """grep-based caller search across repo."""
    results: list[str] = []
    pattern = rf"\b{re.escape(fn)}\s*\("
    for path in REPO_ROOT.rglob("*.py"):
        if any(p in path.parts for p in (".git", ".agent", "USTAT DEPO", "docs", "tests", "reports")):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if str(path).endswith(file_rel.replace("/", "\\")) or str(path).endswith(file_rel):
            continue  # skip self
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(pattern, line) and f"def {fn}" not in line:
                rel = path.relative_to(REPO_ROOT).as_posix()
                results.append(f"{rel}:{i}")
                if len(results) >= 20:
                    return results
    return results


def _find_callees(file_rel: str, fn: str) -> list[str]:
    """AST-based callee extraction within the function body."""
    path = REPO_ROOT / file_rel
    if not path.exists() or path.suffix != ".py":
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    callees: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn:
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Attribute):
                        callees.add(f"{_unparse(child.func)}")
                    elif isinstance(child.func, ast.Name):
                        callees.add(child.func.id)
    return sorted(c for c in callees if c and not c.startswith("_builtin"))[:30]


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<?>"


def _find_tests(file_rel: str, fn: str | None) -> list[str]:
    results: list[str] = []
    needles = [file_rel, Path(file_rel).stem]
    if fn:
        needles.append(fn)
    tests_dir = REPO_ROOT / "tests"
    if not tests_dir.exists():
        return results
    for path in tests_dir.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(n in text for n in needles):
            results.append(path.relative_to(REPO_ROOT).as_posix())
    return sorted(set(results))[:20]


def _git_history(file_rel: str, days: int = 90) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "log", f"--since={days}.days.ago", "--pretty=format:%h %ad %s", "--date=short", "--", file_rel],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if out.returncode == 0:
            return [l for l in out.stdout.splitlines() if l.strip()][:10]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return []


def _consequences(cls: str, linked: list[str], manifest: dict[str, Any]) -> list[str]:
    """Build cause-effect sentences from linked IDs."""
    out: list[str] = []
    inv_map = {i["id"]: i["title"] for i in manifest.get("inviolables", []) or []}
    rule_map = {r["id"]: r["title"] for r in manifest.get("protected_rules", []) or []}
    bk_map = {f["id"]: (f["function"], f["role"]) for f in manifest.get("protected_functions", []) or []}

    for lid in linked:
        if lid in inv_map:
            out.append(f"⚠️ ÇEKİRDEK İHLAL: {lid} ({inv_map[lid]}) bozulabilir — uygulamanın temel korumalarından biri")
        elif lid in rule_map:
            out.append(f"⚠️ KURAL RİSKİ: {lid} ({rule_map[lid]}) davranış sözleşmesi kırılabilir")
        elif lid in bk_map:
            fn, role = bk_map[lid]
            out.append(f"⚠️ FONKSİYON RİSKİ: {lid} ({fn}) — {role}")
    if cls == "C3":
        out.append("❗ Bu değişiklik C3 sınıfıdır: çift doğrulama + 24 saat soğuma ZORUNLU")
    elif cls == "C2":
        out.append("⚠ Bu değişiklik C2 sınıfıdır: açık onay ifadesi + rollback planı ZORUNLU")
    return out


def build_report(target: str) -> str:
    if "::" in target:
        file_rel, fn = target.split("::", 1)
    else:
        file_rel, fn = target, None

    manifest = _load_manifest()
    cls, linked = _classify(file_rel, fn, manifest)
    callers = _find_callers(file_rel, fn) if fn else []
    callees = _find_callees(file_rel, fn) if fn else []
    tests = _find_tests(file_rel, fn)
    history = _git_history(file_rel)
    consequences = _consequences(cls, linked, manifest)

    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# Değişiklik Etki Raporu",
        f"",
        f"**Hedef:** `{target}`",
        f"**Tarih:** {today}",
        f"**Değişiklik Sınıfı:** {cls}",
        f"**Bağlı Koruma Kimlikleri:** {', '.join(linked) if linked else '(yok)'}",
        f"",
        f"---",
        f"",
        f"## 1. Bu hedefi ÇAĞIRAN yerler (yukarı zincir)",
    ]
    if callers:
        lines += [f"- `{c}`" for c in callers]
    else:
        lines.append("(bulunamadı veya uygulanamaz)")

    lines += [
        f"",
        f"## 2. Bu hedefin ÇAĞIRDIĞI yerler (aşağı zincir)",
    ]
    if callees:
        lines += [f"- `{c}`" for c in callees]
    else:
        lines.append("(bulunamadı veya uygulanamaz)")

    lines += [
        f"",
        f"## 3. Bu hedefi ETKİLEYEN/TEST EDEN testler",
    ]
    if tests:
        lines += [f"- `{t}`" for t in tests]
    else:
        lines.append("(bulunamadı — YENİ TEST GEREKLİ OLABİLİR)")

    lines += [
        f"",
        f"## 4. Son 90 günlük git geçmişi",
    ]
    if history:
        lines += [f"- `{h}`" for h in history]
    else:
        lines.append("(geçmiş yok veya git erişilemedi)")

    lines += [
        f"",
        f"## 5. Değiştirirsen olası sonuçlar (neden-sonuç)",
    ]
    if consequences:
        lines += [f"- {c}" for c in consequences]
    else:
        lines.append("- Bu hedef koruma sicilinde listelenmemiş. Değişiklik C1 sınıfı.")

    lines += [
        f"",
        f"## 6. Geri alma planı (rollback)",
        f"```bash",
        f"git revert <bu_commit> --no-edit",
        f"```",
        f"",
        f"## 7. Onay Akışı",
    ]
    if cls == "C3":
        lines += [
            f"- [ ] **Aşama 1:** `ANAYASA ONAYI: <clause_id> {today} <gerekçe>` commit mesajında",
            f"- [ ] **24 saat soğuma**",
            f"- [ ] **Aşama 2:** `ANAYASA TEYİDİ: <clause_id> <aşama1_sha12>` commit mesajında",
            f"- [ ] İmzalı tag: `git tag -a ANAYASA-vX.Y`",
            f"- [ ] Kayıt: `docs/anayasa_degisiklikleri/{today}_<clause_id>_sonuc.md`",
        ]
    elif cls == "C2":
        lines += [
            f"- [ ] **Açık Onay:** `ANAYASA ONAYI: <clause_id> {today} <gerekçe>` commit mesajında",
            f"- [ ] Rollback planı yazılı",
            f"- [ ] Testler yeşil",
        ]
    else:
        lines += [
            f"- [ ] Standart commit",
            f"- [ ] Testler yeşil",
        ]

    lines += [
        f"",
        f"---",
        f"",
        f"*Bu rapor `tools/impact_report.py` tarafından otomatik üretilmiştir. "
        f"Kullanıcı tarafından okunmadan değişiklik uygulanamaz.*",
        f"",
    ]
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print("Kullanım: python tools/impact_report.py <dosya>[::<fonksiyon>]", file=sys.stderr)
        return 2
    target = sys.argv[1]
    report = build_report(target)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    safe = target.replace("/", "_").replace("\\", "_").replace("::", "__")
    out_path = REPORTS_DIR / f"impact_{today}_{safe}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"Etki raporu yazıldı: {out_path.relative_to(REPO_ROOT)}")
    print("---")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
