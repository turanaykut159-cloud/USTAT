"""POST /api/killswitch — Kill-switch tetikleme / onaylama.

İki aksiyon:
  activate    → L3 manuel tam kapanış (Desktop'tan 2s basılı + onay)
  acknowledge → Aktif kill-switch'i onayla ve sistemi sıfırla
"""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import get_baba, get_db, get_h_engine
from api.schemas import KillSwitchRequest, KillSwitchResponse

router = APIRouter()


@router.post("/killswitch", response_model=KillSwitchResponse)
async def trigger_killswitch(req: KillSwitchRequest):
    """Kill-switch tetikle veya onayla."""
    baba = get_baba()

    if not baba:
        return KillSwitchResponse(
            success=False,
            message="Risk yönetim modülü (BABA) aktif değil.",
        )

    action = req.action.lower().strip()

    # ── ACTIVATE: L3 Manuel Tam Kapanış ──────────────────────────
    if action == "activate":
        try:
            baba.activate_kill_switch_l3_manual(user=req.user)
            failed = getattr(baba, "_last_l3_failed_tickets", [])

            # Hibrit pozisyonları da kapat (L3)
            h_engine = get_h_engine()
            if h_engine:
                h_failed = h_engine.force_close_all(reason="KILL_SWITCH_L3")
                if h_failed:
                    failed = list(failed) + h_failed

            msg = f"L3 kill-switch aktif — {req.user}"
            if failed:
                msg += f"; kapatılamayan pozisyonlar: {failed}"
            return KillSwitchResponse(
                success=True,
                kill_switch_level=3,
                message=msg,
                failed_tickets=failed,
            )
        except Exception as e:
            return KillSwitchResponse(
                success=False,
                kill_switch_level=baba._kill_switch_level,
                message=f"Kill-switch aktivasyon hatası: {e}",
            )

    # ── ACKNOWLEDGE: Onayla ve Sıfırla ───────────────────────────
    if action == "acknowledge":
        try:
            success = baba.acknowledge_kill_switch(user=req.user)
            if success:
                return KillSwitchResponse(
                    success=True,
                    kill_switch_level=0,
                    message=f"Kill-switch sıfırlandı — {req.user}",
                )
            else:
                return KillSwitchResponse(
                    success=False,
                    kill_switch_level=baba._kill_switch_level,
                    message="Aktif kill-switch yok veya onaylama başarısız.",
                )
        except Exception as e:
            return KillSwitchResponse(
                success=False,
                kill_switch_level=baba._kill_switch_level,
                message=f"Kill-switch onay hatası: {e}",
            )

    # ── Bilinmeyen aksiyon ───────────────────────────────────────
    return KillSwitchResponse(
        success=False,
        kill_switch_level=baba._kill_switch_level,
        message=f"Bilinmeyen aksiyon: '{req.action}'. 'activate' veya 'acknowledge' kullanın.",
    )
