#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ÜSTAT Plus V6.0 — Anayasa Doğrulama Aracı

Bu araç anayasanın (USTAT_ANAYASA.md) ve sicilinin (governance/protected_assets.yaml)
kod ile senkron olduğunu kontrol eder. Pre-commit ve CI tarafından çağrılır.

Kontroller:
  1. protected_files: her kayıtlı dosya mevcut mu?
  2. protected_functions: her fonksiyon belirtilen dosyada var mı?
  3. protected_rules: location alanındaki dosya ve varsa fonksiyon var mı?
  4. protected_config_keys: anahtar config/default.json içinde var mı ve değer kilitli ise eşleşiyor mu?
  5. inviolables: required_tests mevcut mu?
  6. anayasa_sha256: USTAT_ANAYASA.md hash'i eşleşiyor mu? (boş ise uyarı + öneri)

Exit kodları:
  0 — Tüm kontroller geçti
  1 — Uyarı (anayasa hash boş vb.)
  2 — Kritik ihlal (hayalet kayıt, hash uyuşmazlığı, kilitli değer değişti)
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("HATA: PyYAML gerekli. `pip install pyyaml`", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "governance" / "protected_assets.yaml"
ANAYASA_PATH = REPO_ROOT / "USTAT_ANAYASA.md"
CONFIG_PATH = REPO_ROOT / "config" / "default.json"


class Result:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, msg: str) -> None:
        self.info.append(msg)

    def exit_code(self) -> int:
        if self.errors:
            return 2
        if self.warnings:
            return 1
        return 0


def _read_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        print(f"HATA: Sicil bulunamadı: {MANIFEST_PATH}", file=sys.stderr)
        sys.exit(2)
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _file_exists(rel: str) -> bool:
    return (REPO_ROOT / rel).is_file()


def _function_in_python_file(path: Path, name: str) -> bool:
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # Fallback: naive regex
        return bool(
            re.search(rf"def\s+{re.escape(name)}\s*\(", src)
            or re.search(rf"class\s+{re.escape(name)}\s*[\(:]", src)
        )
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return True
    return False


def _function_in_js_file(path: Path, name: str) -> bool:
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    patterns = [
        rf"function\s+{re.escape(name)}\s*\(",
        rf"(?:const|let|var)\s+{re.escape(name)}\s*=\s*(?:async\s*)?\(",
        rf"(?:const|let|var)\s+{re.escape(name)}\s*=\s*(?:async\s*)?function",
        rf"^\s*{re.escape(name)}\s*\([^)]*\)\s*\{{",  # method shorthand
        rf"(?:async\s+)?{re.escape(name)}\s*\([^)]*\)\s*\{{",
    ]
    return any(re.search(p, src, re.MULTILINE) for p in patterns)


def _function_exists(file_rel: str, fn: str) -> bool:
    path = REPO_ROOT / file_rel
    if not path.is_file():
        return False
    if path.suffix == ".py":
        return _function_in_python_file(path, fn)
    if path.suffix in (".js", ".jsx", ".ts", ".tsx"):
        return _function_in_js_file(path, fn)
    return False


def _config_get(cfg: dict[str, Any], dotted_key: str) -> Any:
    cur: Any = cfg
    for part in dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check_protected_files(manifest: dict[str, Any], r: Result) -> None:
    for item in manifest.get("protected_files", []) or []:
        p = item.get("path", "")
        if not p:
            r.error("protected_files: path alanı boş")
            continue
        if not _file_exists(p):
            r.error(f"HAYALET DOSYA: protected_files içinde '{p}' kodda yok")


def check_protected_functions(manifest: dict[str, Any], r: Result) -> None:
    for item in manifest.get("protected_functions", []) or []:
        fid = item.get("id", "?")
        file_rel = item.get("file", "")
        fn = item.get("function", "")
        if not file_rel or not fn:
            r.error(f"protected_functions[{fid}]: file/function alanı eksik")
            continue
        if not _file_exists(file_rel):
            r.error(f"HAYALET DOSYA [{fid}]: '{file_rel}' yok")
            continue
        if not _function_exists(file_rel, fn):
            r.error(f"HAYALET FONKSİYON [{fid}]: '{file_rel}::{fn}' bulunamadı")


def check_protected_rules(manifest: dict[str, Any], r: Result) -> None:
    for rule in manifest.get("protected_rules", []) or []:
        rid = rule.get("id", "?")
        loc = rule.get("location", "")
        if not loc or loc in ("operasyon kuralı",):
            continue
        # Birden fazla dosya '+' ile ayrılabilir
        for token in re.split(r"\s*\+\s*", loc):
            token = token.strip()
            if "::" in token:
                file_part, fn_part = token.split("::", 1)
                file_part = file_part.strip()
                fn_part = fn_part.strip()
                if not _file_exists(file_part):
                    r.error(f"KURAL DOSYA YOK [{rid}]: '{file_part}'")
                    continue
                if not _function_exists(file_part, fn_part):
                    r.error(f"KURAL FONKSİYON YOK [{rid}]: '{file_part}::{fn_part}'")
            else:
                # Wildcard veya klasör
                stripped = token.replace("*", "").rstrip("/")
                if stripped and not (REPO_ROOT / stripped).exists():
                    r.warn(f"KURAL KONUM ŞÜPHELİ [{rid}]: '{token}'")


def check_protected_config(manifest: dict[str, Any], r: Result) -> None:
    if not CONFIG_PATH.exists():
        r.error(f"config/default.json bulunamadı")
        return
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        r.error(f"config/default.json JSON parse hatası: {e}")
        return
    for item in manifest.get("protected_config_keys", []) or []:
        key = item.get("key", "")
        expected = item.get("value_locked", None)
        if not key:
            r.error("protected_config_keys: key alanı boş")
            continue
        actual = _config_get(cfg, key)
        if actual is None:
            r.error(f"CONFIG ANAHTAR YOK: '{key}' config/default.json içinde bulunamadı")
            continue
        if expected is not None:
            # Sayısal karşılaştırma — float/int farkını tolere et
            try:
                if float(actual) != float(expected):
                    r.error(
                        f"KİLİTLİ DEĞER DEĞİŞTİ: '{key}' "
                        f"beklenen={expected}, gerçek={actual}. "
                        f"Bu değişiklik C3 sınıfıdır; manifest veya config güncellenmeli."
                    )
            except (TypeError, ValueError):
                if actual != expected:
                    r.error(f"KİLİTLİ DEĞER DEĞİŞTİ: '{key}' beklenen={expected}, gerçek={actual}")


def check_inviolables(manifest: dict[str, Any], r: Result) -> None:
    for inv in manifest.get("inviolables", []) or []:
        iid = inv.get("id", "?")
        for test_ref in inv.get("required_tests", []) or []:
            # Format: path::test_name
            if "::" in test_ref:
                file_part, _ = test_ref.split("::", 1)
            else:
                file_part = test_ref
            if not (REPO_ROOT / file_part).is_file():
                r.warn(f"İHLAL EDİLEMEZ TEST DOSYASI YOK [{iid}]: '{file_part}'")


def check_anayasa_hash(manifest: dict[str, Any], r: Result, auto_fill: bool = False) -> None:
    declared = (manifest.get("anayasa_sha256") or "").strip().lower()
    if not ANAYASA_PATH.exists():
        r.error("USTAT_ANAYASA.md bulunamadı")
        return
    actual = _sha256_file(ANAYASA_PATH)
    if not declared:
        msg = (
            f"ANAYASA HASH BOŞ: governance/protected_assets.yaml::anayasa_sha256 "
            f"doldurulmalı. Güncel hash: {actual}"
        )
        if auto_fill:
            # Manifest'i güncelle
            txt = MANIFEST_PATH.read_text(encoding="utf-8")
            new_txt = re.sub(
                r'(anayasa_sha256:\s*)"[^"]*"',
                f'\\1"{actual}"',
                txt,
            )
            MANIFEST_PATH.write_text(new_txt, encoding="utf-8")
            r.note(f"ANAYASA HASH DOLDURULDU: {actual}")
        else:
            r.warn(msg)
        return
    if declared != actual:
        r.error(
            f"ANAYASA HASH UYUŞMAZLIĞI: manifest={declared[:16]}..., "
            f"gerçek={actual[:16]}... → Anayasa değişmiş demektir. "
            f"C3 prosedürü uygulanmalı ve hash güncellenmeli."
        )


def main() -> int:
    auto_fill = "--fill-hash" in sys.argv
    quiet = "--quiet" in sys.argv

    manifest = _read_manifest()
    r = Result()

    check_protected_files(manifest, r)
    check_protected_functions(manifest, r)
    check_protected_rules(manifest, r)
    check_protected_config(manifest, r)
    check_inviolables(manifest, r)
    check_anayasa_hash(manifest, r, auto_fill=auto_fill)

    if not quiet:
        print(f"ÜSTAT Plus V6.0 — Anayasa Doğrulama")
        print(f"Sicil: {MANIFEST_PATH.relative_to(REPO_ROOT)}")
        print(f"Anayasa: {ANAYASA_PATH.relative_to(REPO_ROOT)}")
        print("-" * 60)
        for msg in r.info:
            print(f"  [INFO] {msg}")
        for msg in r.warnings:
            print(f"  [UYARI] {msg}")
        for msg in r.errors:
            print(f"  [HATA] {msg}")
        print("-" * 60)
        if r.errors:
            print(f"SONUC: {len(r.errors)} kritik ihlal, {len(r.warnings)} uyari")
        elif r.warnings:
            print(f"SONUC: {len(r.warnings)} uyari")
        else:
            print("SONUC: Tum kontroller gecti")

    return r.exit_code()


if __name__ == "__main__":
    sys.exit(main())
