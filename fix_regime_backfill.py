"""
ÜSTAT v5.7 — Rejim Backfill + Volume Spike Temizlik Scripti

NULL rejimli eski işlemlere top5_history'den rejim atar.
Birikmiş volume spike uyarılarını çözümlenmiş olarak işaretler.

Kullanım:
    python fix_regime_backfill.py

NOT: Bu script tek seferlik bakım amaçlıdır. İşi bittikten sonra silinebilir.
"""

import sqlite3
import os
import shutil
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "trades.db")

def main():
    if not os.path.exists(DB_PATH):
        print(f"HATA: Veritabanı bulunamadı: {DB_PATH}")
        return

    # 1. Yedek al
    backup_path = DB_PATH.replace(".db", f"_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Yedek alındı: {backup_path}")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # ═══ BÖLÜM 1: REJİM BACKFILL ═══════════════════════════════

    # top5_history'den tarih -> rejim haritası oluştur
    rows = db.execute("""
        SELECT date, regime, COUNT(*) as cnt
        FROM top5_history
        WHERE regime IS NOT NULL AND regime != ''
        GROUP BY date, regime
        ORDER BY date, cnt DESC
    """).fetchall()

    date_regime = {}
    for r in rows:
        if r["date"] not in date_regime:
            date_regime[r["date"]] = r["regime"]

    print(f"✓ Rejim haritası: {len(date_regime)} gün verisi")

    # NULL rejimli işlemleri güncelle
    null_trades = db.execute(
        "SELECT id, entry_time FROM trades WHERE regime IS NULL OR regime = ''"
    ).fetchall()

    matched = 0
    unknown = 0
    for t in null_trades:
        entry_date = (t["entry_time"] or "")[:10]
        regime = date_regime.get(entry_date)
        if regime:
            db.execute("UPDATE trades SET regime = ? WHERE id = ?", (regime, t["id"]))
            matched += 1
        else:
            db.execute("UPDATE trades SET regime = 'UNKNOWN' WHERE id = ?", (t["id"],))
            unknown += 1

    db.commit()
    print(f"✓ Rejim backfill: {matched} eşleşti, {unknown} UNKNOWN atandı (toplam {len(null_trades)} NULL)")

    # Sonucu göster
    print("\n  Yeni rejim dağılımı:")
    for r in db.execute("SELECT regime, COUNT(*) as cnt FROM trades GROUP BY regime ORDER BY cnt DESC"):
        print(f"    {r['regime']}: {r['cnt']}")

    # ═══ BÖLÜM 2: VOLUME SPIKE TEMİZLİK ════════════════════════
    # error_resolutions tablosu üzerinden çözümleme kaydı yazılır.
    # events tablosunda 'resolved' kolonu yok — çözümleme ayrı tabloda tutulur.

    # error_resolutions tablosu var mı kontrol et
    has_table = db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='error_resolutions'"
    ).fetchone()[0]

    if not has_table:
        db.execute("""
            CREATE TABLE IF NOT EXISTS error_resolutions (
                error_type  TEXT PRIMARY KEY,
                resolved_at TEXT NOT NULL,
                resolved_by TEXT NOT NULL DEFAULT 'system'
            )
        """)
        db.commit()
        print("\n✓ error_resolutions tablosu oluşturuldu")

    # Volume spike ile ilgili event tiplerini bul
    spike_types = db.execute("""
        SELECT DISTINCT type FROM events
        WHERE message LIKE '%Hacim patlamas%' OR message LIKE '%VOLUME_SPIKE%'
    """).fetchall()

    spike_count = db.execute("""
        SELECT COUNT(*) FROM events
        WHERE message LIKE '%Hacim patlamas%' OR message LIKE '%VOLUME_SPIKE%'
    """).fetchone()[0]

    now_str = datetime.now().isoformat(timespec="seconds")
    resolved = 0

    for row in spike_types:
        etype = row["type"]
        db.execute(
            """INSERT OR REPLACE INTO error_resolutions
               (error_type, resolved_at, resolved_by) VALUES (?, ?, ?)""",
            (etype, now_str, "regime_backfill_script"),
        )
        resolved += 1

    # Ayrıca EARLY_WARNING tipini de çözümle (volume spike bu tipte)
    db.execute(
        """INSERT OR REPLACE INTO error_resolutions
           (error_type, resolved_at, resolved_by) VALUES (?, ?, ?)""",
        ("EARLY_WARNING", now_str, "regime_backfill_script"),
    )
    resolved += 1

    db.commit()
    print(f"\n✓ Volume spike temizlik: {spike_count} uyarı mevcut, {resolved} error_type çözümlendi")

    # ═══ DOĞRULAMA ══════════════════════════════════════════════

    remaining_null = db.execute(
        "SELECT COUNT(*) FROM trades WHERE regime IS NULL OR regime = ''"
    ).fetchone()[0]

    print(f"\n{'='*50}")
    print(f"  Kalan NULL rejim: {remaining_null}")
    print(f"  Volume spike çözümleme: error_resolutions'a yazıldı")
    print(f"{'='*50}")

    if remaining_null == 0:
        print("  ✅ Tüm temizlik tamamlandı!")

    db.close()

if __name__ == "__main__":
    main()
