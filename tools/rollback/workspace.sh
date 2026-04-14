#!/usr/bin/env bash
# USTAT Anayasa v3.0 — Kirli workspace'i temizleme
# UYARI: Bu islem commit edilmemis tum degisiklikleri KAYBEDER.
# Kullanim:
#   tools/rollback/workspace.sh           # Interaktif — her dosya icin onay
#   tools/rollback/workspace.sh --all     # Tumunu bir kerede sifirla (onay sonrasi)
#   tools/rollback/workspace.sh --stash   # Kaybetmeden stash'e koy

set -euo pipefail
cd "$(dirname "$0")/../.."

MODE="${1:-interactive}"

case "$MODE" in
    --stash)
        MSG="workspace-rollback-$(date +%Y%m%d-%H%M%S)"
        git stash push -u -m "$MSG"
        echo "Workspace stash'lendi: $MSG"
        echo "Geri yuklemek icin: git stash pop"
        ;;
    --all)
        echo "UYARI: Tum modified/untracked dosyalar SILINECEK"
        git status --short
        read -p "Emin misin? [yes/NO]: " CONFIRM
        if [ "$CONFIRM" != "yes" ]; then
            echo "Iptal."
            exit 0
        fi
        git reset --hard HEAD
        git clean -fd
        echo "Workspace temiz."
        ;;
    interactive|*)
        echo "Kirli dosyalar:"
        git status --short
        echo ""
        echo "Secenekler:"
        echo "  1) --stash      ile kaybedmeden sakla"
        echo "  2) --all        ile tumunu kalici olarak sifirla"
        echo "  3) git checkout -- <path>  ile dosya bazinda seçici geri alma"
        ;;
esac
