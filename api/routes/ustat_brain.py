"""GET /api/ustat/brain — ÜSTAT beyin analiz verileri.

v13.0 spesifikasyonu kapsamında ÜSTAT'ın beyin görevleri:
  - İşlem kategorizasyonu (çok boyutlu)
  - Kontrat profilleri
  - Karar/olay akışı
  - Rejim bazlı performans
  - Hata ataması ("Kim hata yaptı?" — BABA/OĞUL)
  - Ertesi gün analizi (puanlama)
  - Strateji havuzu (dönem parametreleri)
  - Regülasyon önerileri

Veriler iki kaynaktan gelir:
  1. DB'den hesaplanan: trades/events tablolarından kategorizasyon ve profiller
  2. Engine'den okunan: ÜSTAT brain cycle çıktıları (hata ataması, analiz, strateji)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from api.deps import get_baba, get_db, get_engine, get_ustat

logger = logging.getLogger("ustat.api.routes.ustat_brain")
from api.schemas import (
    CategoryGroup,
    ContractProfile,
    ErrorAttribution,
    EventItem,
    NextDayAnalysis,
    RegulationSuggestion,
    StrategyPool,
    StrategyProfile,
    TradeCategories,
    UstatBrainResponse,
)

router = APIRouter()


def _calc_duration_minutes(entry_time: str | None, exit_time: str | None) -> float:
    """İki zaman damgası arasındaki süreyi dakika olarak hesapla."""
    if not entry_time or not exit_time:
        return 0.0
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        entry = datetime.strptime(entry_time[:19].replace("T", " "), fmt)
        exit_ = datetime.strptime(exit_time[:19].replace("T", " "), fmt)
        return max((exit_ - entry).total_seconds() / 60.0, 0.0)
    except (ValueError, TypeError):
        return 0.0


def _categorize_trades(trades: list[dict]) -> TradeCategories:
    """İşlemleri çok boyutlu kategorilere ayır."""
    groups: dict[str, dict[str, list[dict]]] = {
        "by_result": {},
        "by_direction": {},
        "by_duration": {},
        "by_regime": {},
        "by_exit_reason": {},
    }

    for t in trades:
        pnl = t.get("pnl")
        if pnl is None:
            continue  # Kapanmamış işlem

        # Sonuca göre
        result_label = "Karlı" if pnl > 0 else ("Zararlı" if pnl < 0 else "Başabaş")
        groups["by_result"].setdefault(result_label, []).append(t)

        # Yöne göre
        direction = t.get("direction", "UNKNOWN")
        groups["by_direction"].setdefault(direction, []).append(t)

        # Süreye göre
        dur_min = _calc_duration_minutes(t.get("entry_time"), t.get("exit_time"))
        if dur_min < 120:
            dur_label = "Kısa (<2 saat)"
        elif dur_min < 480:
            dur_label = "Orta (2-8 saat)"
        else:
            dur_label = "Uzun (>8 saat)"
        groups["by_duration"].setdefault(dur_label, []).append(t)

        # Rejime göre
        regime = t.get("regime") or "Bilinmeyen"
        groups["by_regime"].setdefault(regime, []).append(t)

        # Çıkış nedenine göre
        exit_reason = t.get("exit_reason") or "Bilinmeyen"
        groups["by_exit_reason"].setdefault(exit_reason, []).append(t)

    def build_groups(category: dict[str, list[dict]]) -> list[CategoryGroup]:
        result = []
        for label, trade_list in sorted(category.items()):
            pnls = [tr["pnl"] for tr in trade_list if tr.get("pnl") is not None]
            wins = sum(1 for p in pnls if p > 0)
            total_pnl = sum(pnls)
            count = len(pnls)
            result.append(CategoryGroup(
                label=label,
                count=count,
                total_pnl=round(total_pnl, 2),
                win_rate=round((wins / count) * 100, 1) if count > 0 else 0.0,
                avg_pnl=round(total_pnl / count, 2) if count > 0 else 0.0,
            ))
        return result

    return TradeCategories(
        by_result=build_groups(groups["by_result"]),
        by_direction=build_groups(groups["by_direction"]),
        by_duration=build_groups(groups["by_duration"]),
        by_regime=build_groups(groups["by_regime"]),
        by_exit_reason=build_groups(groups["by_exit_reason"]),
    )


def _build_contract_profiles(trades: list[dict]) -> list[ContractProfile]:
    """Kontrat bazlı detaylı profiller oluştur."""
    by_symbol: dict[str, list[dict]] = {}
    for t in trades:
        sym = t.get("symbol", "")
        if sym:
            by_symbol.setdefault(sym, []).append(t)

    profiles = []
    for symbol, symbol_trades in sorted(by_symbol.items()):
        closed = [t for t in symbol_trades if t.get("pnl") is not None]
        if not closed:
            continue

        pnls = [t["pnl"] for t in closed]
        wins = sum(1 for p in pnls if p > 0)
        total_pnl = sum(pnls)
        count = len(closed)

        durations = [
            _calc_duration_minutes(t.get("entry_time"), t.get("exit_time"))
            for t in closed
        ]
        avg_dur = sum(durations) / len(durations) if durations else 0.0

        # Tercih edilen yön: BUY/SELL hangisi daha kârlı
        buy_pnl = sum(t["pnl"] for t in closed if t.get("direction") == "BUY")
        sell_pnl = sum(t["pnl"] for t in closed if t.get("direction") == "SELL")
        preferred = "BUY" if buy_pnl >= sell_pnl else "SELL"

        # Son işlem tarihi
        last_trade_dt = ""
        for t in closed:
            et = t.get("exit_time") or t.get("entry_time") or ""
            if et > last_trade_dt:
                last_trade_dt = et

        profiles.append(ContractProfile(
            symbol=symbol,
            trade_count=count,
            win_rate=round((wins / count) * 100, 1) if count > 0 else 0.0,
            total_pnl=round(total_pnl, 2),
            avg_pnl=round(total_pnl / count, 2) if count > 0 else 0.0,
            avg_duration_min=round(avg_dur, 1),
            best_pnl=round(max(pnls), 2) if pnls else 0.0,
            worst_pnl=round(min(pnls), 2) if pnls else 0.0,
            last_trade=last_trade_dt[:16] if last_trade_dt else "",
            preferred_direction=preferred,
        ))

    # Toplam K/Z'ye göre sırala (en iyi başta)
    profiles.sort(key=lambda p: p.total_pnl, reverse=True)
    return profiles


@router.get("/ustat/brain-debug")
async def get_ustat_brain_debug():
    """Brain modülü debug — sorunu tespit etmek için."""
    result = {"steps": []}
    try:
        db = get_db()
        result["db_available"] = db is not None
        result["steps"].append("db_check_ok")

        if db:
            since = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
            trades = db.get_trades(since=since, limit=5000) or []
            result["trade_count"] = len(trades)
            result["steps"].append(f"trades_fetched: {len(trades)}")

            if trades:
                cats = _categorize_trades(trades)
                result["categories_by_result"] = len(cats.by_result)
                result["steps"].append("categorize_ok")

                profiles = _build_contract_profiles(trades)
                result["profile_count"] = len(profiles)
                result["steps"].append("profiles_ok")

        ustat = get_ustat()
        result["ustat_available"] = ustat is not None
        result["steps"].append("ustat_check_ok")

    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        import traceback
        result["traceback"] = traceback.format_exc()

    return result


@router.get("/ustat/brain", response_model=UstatBrainResponse)
async def get_ustat_brain(
    days: int = Query(90, ge=1, le=365, description="Analiz periyodu (gün)"),
):
    """ÜSTAT beyin analiz verilerini döndür.

    İki veri kaynağı:
      1. DB'den: trades/events tabloları → kategorizasyon, profiller
      2. Engine ÜSTAT'tan: hata ataması, ertesi gün analizi, strateji havuzu,
         regülasyon önerileri (run_cycle çıktıları)
    """
    engine = get_engine()
    if engine and getattr(engine.mt5, "_connected", False):
        try:
            engine.sync_mt5_history_recent(min(7, days))
        except Exception:
            pass
    db = get_db()
    if not db:
        logger.warning("Brain: DB bağlantısı yok — boş yanıt dönülüyor")
        return UstatBrainResponse()
    logger.info(f"Brain: DB bağlantısı OK, days={days}")

    # Tarih filtresi
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        # İşlemleri çek
        trades = db.get_trades(since=since, limit=5000) or []
        logger.info(f"Brain: {len(trades)} trade bulundu (since={since})")

        # İşlem kategorizasyonu
        trade_categories = _categorize_trades(trades)

        # Kontrat profilleri
        contract_profiles = _build_contract_profiles(trades)

        # Son kararlar (events tablosundan)
        events_raw = db.get_events(limit=50) or []
        recent_decisions = []
        for e in events_raw:
            try:
                recent_decisions.append(EventItem(
                    id=e.get("id") or 0,
                    timestamp=str(e.get("timestamp") or ""),
                    type=str(e.get("type") or ""),
                    severity=str(e.get("severity") or "INFO"),
                    message=str(e.get("message") or ""),
                    action=str(e.get("action") or ""),
                ))
            except Exception:
                continue  # Hatalı event kaydını atla, diğerlerine devam

        # Rejim bazlı performans
        regime_performance = trade_categories.by_regime

        # ── ÜSTAT engine verileri ────────────────────────────────────
        ustat = get_ustat()

        # Hata atamaları (ÜSTAT brain cycle'dan)
        error_attributions: list[ErrorAttribution] = []
        if ustat:
            for ea in (ustat.get_error_attributions() or []):
                error_attributions.append(ErrorAttribution(
                    trade_id=ea.get("trade_id", 0),
                    error_type=ea.get("error_type", ""),
                    responsible=ea.get("responsible", ""),
                    description=ea.get("description", ""),
                ))

        # Ertesi gün analizleri (ÜSTAT brain cycle'dan)
        next_day_analyses: list[NextDayAnalysis] = []
        if ustat:
            for nda in (ustat.get_next_day_analyses() or []):
                next_day_analyses.append(NextDayAnalysis(
                    trade_id=nda.get("trade_id", 0),
                    symbol=nda.get("symbol", ""),
                    actual_pnl=nda.get("actual_pnl", 0.0),
                    potential_pnl=nda.get("potential_pnl", 0.0),
                    missed_profit=nda.get("missed_profit", 0.0),
                    signal_score=nda.get("signal_score", 0.0),
                    management_score=nda.get("management_score", 0.0),
                    profit_score=nda.get("profit_score", 0.0),
                    risk_score=nda.get("risk_score", 0.0),
                    total_score=nda.get("total_score", 0.0),
                    summary=nda.get("summary", ""),
                ))

        # Strateji havuzu (ÜSTAT brain cycle'dan)
        strategy_pool = StrategyPool()
        if ustat:
            sp = ustat.get_strategy_pool() or {}
            strategy_pool = StrategyPool(
                current_regime=sp.get("current_regime", ""),
                active_profile=sp.get("active_profile", ""),
                profiles=[
                    StrategyProfile(
                        name=p.get("name", ""),
                        market_type=p.get("market_type", ""),
                        parameters=p.get("parameters", {}),
                        active=p.get("active", False),
                    )
                    for p in sp.get("profiles", [])
                ],
            )
        else:
            # Engine yoksa sadece rejim bilgisini al
            baba = get_baba()
            if baba and baba.current_regime:
                strategy_pool.current_regime = baba.current_regime.regime_type.value

        # Regülasyon önerileri (ÜSTAT brain cycle'dan)
        regulation_suggestions: list[RegulationSuggestion] = []
        if ustat:
            for rs in (ustat.get_regulation_suggestions() or []):
                regulation_suggestions.append(RegulationSuggestion(
                    parameter=rs.get("parameter", ""),
                    current_value=rs.get("current_value", ""),
                    suggested_value=rs.get("suggested_value", ""),
                    reason=rs.get("reason", ""),
                    priority=rs.get("priority", "MEDIUM"),
                ))

        # Geçmiş kategorizasyonu (ÜSTAT engine'den — çok boyutlu sınıflandırma)
        trade_categorization_engine: dict = {}
        if ustat:
            tc = ustat.get_trade_categories() or {}
            trade_categorization_engine = tc.get("summary", {})

        return UstatBrainResponse(
            trade_categories=trade_categories,
            contract_profiles=contract_profiles,
            recent_decisions=recent_decisions,
            regime_performance=regime_performance,
            error_attributions=error_attributions,
            next_day_analyses=next_day_analyses,
            strategy_pool=strategy_pool,
            regulation_suggestions=regulation_suggestions,
            trade_categorization_engine=trade_categorization_engine,
        )
    except Exception as exc:
        logger.exception("ustat/brain endpoint HATASI: %s", exc)
        return UstatBrainResponse()
