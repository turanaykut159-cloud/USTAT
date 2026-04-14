#!/usr/bin/env bash
# USTAT Anayasa v3.0 — Tum misyonu geri alma
# Misyon commit'lerini "mission: M-ID" mesaj pattern'inden bulur, sirayla revert eder.
# Kullanim: tools/rollback/mission.sh <mission_id>
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Kullanim: $0 <mission_id> (ornek: M-2026-04-14-primnet)" >&2
    exit 1
fi

MID="$1"
cd "$(dirname "$0")/../.."

echo "Misyon commit'leri araniyor: $MID"
HASHES=$(git log --grep="($MID)" --format="%H" | head -50)

if [ -z "$HASHES" ]; then
    echo "Bu misyona ait commit bulunamadi."
    exit 2
fi

echo "Bulunan commit'ler (en yenisi onde):"
for H in $HASHES; do git log -1 --oneline "$H"; done

echo ""
read -p "Hepsini sirayla revert et? [yes/NO]: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Iptal edildi."
    exit 0
fi

# En yenisinden eskisine dogru revert (git revert oyle ister)
for H in $HASHES; do
    echo "Revert: $H"
    git revert "$H" --no-edit
done

echo "Misyon geri alindi."
git log --oneline -20
