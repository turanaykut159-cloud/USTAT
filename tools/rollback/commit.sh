#!/usr/bin/env bash
# USTAT Anayasa v3.0 — Tek commit geri alma
# Kullanim: tools/rollback/commit.sh <commit_hash>
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Kullanim: $0 <commit_hash>" >&2
    exit 1
fi

HASH="$1"
cd "$(dirname "$0")/../.."

echo "Commit inceleniyor: $HASH"
git show --stat "$HASH"

echo ""
read -p "Bu commit'i geri almak istediginden emin misin? [yes/NO]: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Iptal edildi."
    exit 0
fi

git revert "$HASH" --no-edit
echo "Geri alma commit'i olusturuldu:"
git log -1 --oneline
