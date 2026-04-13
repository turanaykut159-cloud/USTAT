"""OĞUL Motor Toggle — Sinyal üretimini açıp kapatır.

GET  /api/ogul-toggle  — Mevcut durumu döndür
POST /api/ogul-toggle  — Aç/kapat (açık pozisyon varken kapatma engellenir)

v6.0: Manuel ve Hibrit motorlar bağımsız çalışmaya devam eder.
OĞUL kapatıldığında HIZLI DÖNGÜ (EOD, trailing, sync) hâlâ çalışır,
sadece SİNYAL DÖNGÜSÜ (yeni işlem açma) engellenir.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from api.deps import get_ogul
from api.schemas import OgulToggleRequest, OgulToggleResponse

logger = logging.getLogger("ustat.api")

router = APIRouter()


@router.get("/ogul-toggle", response_model=OgulToggleResponse)
async def get_ogul_toggle():
    """OĞUL motor durumunu döndür."""
    ogul = get_ogul()
    if not ogul:
        return OgulToggleResponse(
            success=False,
            enabled=False,
            has_positions=False,
            message="OĞUL motoru henüz başlatılmadı.",
        )

    has_pos = len(ogul.active_trades) > 0

    return OgulToggleResponse(
        success=True,
        enabled=ogul.ogul_enabled,
        has_positions=has_pos,
        message="",
    )


@router.post("/ogul-toggle", response_model=OgulToggleResponse)
async def toggle_ogul(req: OgulToggleRequest):
    """OĞUL motorunu aç veya kapat.

    Kurallar:
        - enable:  Koşulsuz açar.
        - disable: Açık OĞUL pozisyonu varken REDDEDER.
    """
    ogul = get_ogul()
    if not ogul:
        return OgulToggleResponse(
            success=False,
            enabled=False,
            has_positions=False,
            message="OĞUL motoru henüz başlatılmadı.",
        )

    action = req.action.lower().strip()
    has_pos = len(ogul.active_trades) > 0

    if action == "enable":
        ogul.ogul_enabled = True
        logger.info("OĞUL motor toggle: kullanıcı tarafından AKTİF edildi")
        return OgulToggleResponse(
            success=True,
            enabled=True,
            has_positions=has_pos,
            message="OĞUL motoru aktif — sinyal üretimi başladı.",
        )

    if action == "disable":
        # Açık pozisyon varken kapatma YASAK
        if has_pos:
            logger.warning(
                "OĞUL toggle REDDEDILDI: %d açık pozisyon var",
                len(ogul.active_trades),
            )
            return OgulToggleResponse(
                success=False,
                enabled=ogul.ogul_enabled,
                has_positions=True,
                message=f"OĞUL kapatılamaz — {len(ogul.active_trades)} açık pozisyon var. Önce pozisyonları kapatın.",
            )
        ogul.ogul_enabled = False
        logger.info("OĞUL motor toggle: kullanıcı tarafından KAPALI edildi")
        return OgulToggleResponse(
            success=True,
            enabled=False,
            has_positions=False,
            message="OĞUL motoru kapatıldı — sinyal üretimi durduruldu.",
        )

    return OgulToggleResponse(
        success=False,
        enabled=ogul.ogul_enabled,
        has_positions=has_pos,
        message=f"Geçersiz action: '{action}'. 'enable' veya 'disable' kullanın.",
    )
