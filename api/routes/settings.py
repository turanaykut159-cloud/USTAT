"""Ayarlar API — Kullanıcı yapılandırma endpoint'leri.

Endpoint'ler:
    GET  /settings/risk-baseline  → Mevcut risk baseline tarihini döndür
    POST /settings/risk-baseline  → Risk baseline tarihini güncelle
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from fastapi import APIRouter

from api.deps import get_baba, get_db, get_engine
from api.schemas import (
    RiskBaselineGetResponse,
    RiskBaselineUpdateRequest,
    RiskBaselineUpdateResponse,
)

logger = logging.getLogger("ustat.api.routes.settings")

router = APIRouter()


@router.get("/settings/risk-baseline", response_model=RiskBaselineGetResponse)
async def get_risk_baseline():
    """Mevcut risk baseline tarihini döndür."""
    engine = get_engine()
    if not engine:
        return RiskBaselineGetResponse(baseline_date="", source="unavailable")

    baseline = engine.config.get("risk.baseline_date", "")
    source = "config" if baseline else "default"

    # Fallback: baba'dan oku
    if not baseline:
        baba = get_baba()
        if baba and hasattr(baba, "_risk_baseline_date"):
            baseline = baba._risk_baseline_date
            source = "baba"

    return RiskBaselineGetResponse(baseline_date=baseline, source=source)


@router.post("/settings/risk-baseline", response_model=RiskBaselineUpdateResponse)
async def update_risk_baseline(req: RiskBaselineUpdateRequest):
    """Risk baseline tarihini güncelle.

    Güncelleme sırası:
        1. Tarih formatı doğrula (YYYY-MM-DD)
        2. Config bellekte güncelle
        3. Config dosyasına kaydet
        4. Baba'nın runtime referansını güncelle
        5. Baba modül sabiti RISK_BASELINE_DATE güncelle
    """
    engine = get_engine()
    if not engine:
        return RiskBaselineUpdateResponse(message="Engine çalışmıyor")

    new_date = req.new_date.strip()

    # 1. Tarih formatı doğrula: "YYYY-MM-DD" veya "YYYY-MM-DD HH:MM"
    date_only = re.match(r"^\d{4}-\d{2}-\d{2}$", new_date)
    date_time = re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", new_date)
    if not date_only and not date_time:
        return RiskBaselineUpdateResponse(
            message=f"Geçersiz format: {new_date} (YYYY-MM-DD veya YYYY-MM-DD HH:MM bekleniyor)"
        )

    try:
        if date_time:
            parsed_dt = datetime.strptime(new_date, "%Y-%m-%d %H:%M")
        else:
            parsed_dt = datetime.strptime(new_date, "%Y-%m-%d")
    except ValueError:
        return RiskBaselineUpdateResponse(
            message=f"Geçersiz tarih: {new_date}"
        )

    # Gelecek tarih kontrolü
    if parsed_dt > datetime.now():
        return RiskBaselineUpdateResponse(
            message=f"Gelecek tarih/saat kabul edilmez: {new_date}"
        )

    # 2. Eski tarihi al
    old_date = engine.config.get("risk.baseline_date", "")

    # 3. Config güncelle + kaydet
    try:
        engine.config.set("risk.baseline_date", new_date)
        engine.config.save()
    except Exception as exc:
        return RiskBaselineUpdateResponse(
            message=f"Config kayıt hatası: {exc}"
        )

    # 4. Baba runtime referansını güncelle
    baba = get_baba()
    if baba and hasattr(baba, "_risk_baseline_date"):
        baba._risk_baseline_date = new_date
        logger.info(
            f"Baba risk baseline güncellendi: {old_date} → {new_date}"
        )

    # 5. Baba modül sabiti güncelle (data_pipeline uyumu)
    try:
        import engine.baba as baba_module
        baba_module.RISK_BASELINE_DATE = new_date
    except Exception:
        pass

    # 6. Peak equity sıfırla → drawdown mevcut equity'den yeniden başlasın
    db = get_db()
    if db:
        snap = db.get_latest_risk_snapshot()
        current_equity = snap.get("equity", 0.0) if snap else 0.0
        if current_equity > 0:
            db.set_state("peak_equity", str(current_equity))
            logger.info(
                f"Peak equity sıfırlandı: {current_equity:.2f} (baseline reset)"
            )

    logger.info(
        f"Risk baseline tarihi güncellendi: {old_date} → {new_date}"
    )

    return RiskBaselineUpdateResponse(
        success=True,
        message=f"Risk baseline tarihi güncellendi: {old_date} → {new_date}",
        old_date=old_date,
        new_date=new_date,
    )
