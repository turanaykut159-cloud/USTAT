#!/usr/bin/env bash
# USTAT Anayasa v3.0 — Veritabani geri yukleme
# Kullanim:
#   tools/rollback/db.sh list                      # Mevcut backup'lari listele
#   tools/rollback/db.sh restore <backup_name>     # Belirli backup'i geri yukle
#   tools/rollback/db.sh backup                    # Yeni backup al

set -euo pipefail
cd "$(dirname "$0")/../.."

BACKUP_DIR="database/backups"
DB_FILES=("database/trades.db" "database/ustat.db")

case "${1:-}" in
    list)
        if [ -d "$BACKUP_DIR" ]; then
            ls -lh "$BACKUP_DIR/" 2>/dev/null || echo "Backup klasoru bos"
        else
            echo "Backup klasoru yok: $BACKUP_DIR"
        fi
        ;;
    backup)
        TS=$(date +%Y%m%d-%H%M%S)
        mkdir -p "$BACKUP_DIR"
        for DB in "${DB_FILES[@]}"; do
            if [ -f "$DB" ]; then
                NAME="$(basename "$DB" .db)-$TS.db"
                cp "$DB" "$BACKUP_DIR/$NAME"
                echo "Backup: $BACKUP_DIR/$NAME"
            fi
        done
        ;;
    restore)
        if [ $# -lt 2 ]; then
            echo "Kullanim: $0 restore <backup_name>" >&2
            exit 1
        fi
        BACKUP="$2"
        if [ ! -f "$BACKUP_DIR/$BACKUP" ]; then
            echo "Backup bulunamadi: $BACKUP_DIR/$BACKUP" >&2
            exit 1
        fi
        # Hangi DB?
        case "$BACKUP" in
            trades-*) TARGET="database/trades.db" ;;
            ustat-*)  TARGET="database/ustat.db" ;;
            *)        echo "Anlasilmaz backup adi (trades-* veya ustat-* olmali)"; exit 1 ;;
        esac
        echo "UYARI: $TARGET uzerine yazilacak ($BACKUP)"
        read -p "Emin misin? [yes/NO]: " CONFIRM
        [ "$CONFIRM" = "yes" ] || { echo "Iptal."; exit 0; }
        # Mevcut DB'yi de yedekle (guvenlik)
        TS=$(date +%Y%m%d-%H%M%S)
        cp "$TARGET" "$BACKUP_DIR/$(basename "$TARGET" .db)-pre-restore-$TS.db" 2>/dev/null || true
        cp "$BACKUP_DIR/$BACKUP" "$TARGET"
        echo "Restore tamam: $TARGET <- $BACKUP"
        ;;
    *)
        echo "Kullanim: $0 {list|backup|restore <name>}"
        exit 1
        ;;
esac
