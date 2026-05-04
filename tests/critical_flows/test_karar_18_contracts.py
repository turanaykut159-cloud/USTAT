"""KARAR #18 (2026-05-04) — statik kontrat testleri.

OĞUL aktive paketinin sözleşmeleri:
  C1. trend_follow ADX>=32 filtresi _generate_signal'da var
  C2. trend_follow günlük max trade limiti var
  C3. KARAR #17 hard-block kaldırıldı (yorumda kaldı)
  C4. trend_follow sayacı send_order başarılı sonrası artıyor
  C5. mean_reversion varsayılan parametreleri korunuyor
  C6. breakout _enabled flag kontrolü var
  C7. config/default.json strategies bloğunda yeni anahtarlar var
  C8. KARAR #18 _decision_history yorumu var

Bu testler 'KARAR #18 sözleşmesi degismesin' koruma halkasidir.
Pre-commit hook ile her commit'te çalışır.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OGUL_SRC = (ROOT / "engine" / "ogul.py").read_text(encoding="utf-8")
CONFIG = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))


# ── C1: trend_follow ADX>=32 filtresi _generate_signal'da var ────
def test_c1_trend_follow_adx_min_guard_in_generate_signal():
    """trend_follow için ADX>=32 candidate döngüsünde kontrol edilmeli."""
    # Pattern: candidate.strategy == StrategyType.TREND_FOLLOW + adx_min_trade okuma
    assert "candidate.strategy == StrategyType.TREND_FOLLOW" in OGUL_SRC, (
        "trend_follow candidate kontrolü _generate_signal'dan kalkmış"
    )
    assert "adx_min_trade" in OGUL_SRC, (
        "adx_min_trade config anahtarı koddan kalkmış — ADX guard yok"
    )
    # adx_min_trade okuma yakınında strategies.trend_follow path'i var mı
    assert 'strategies.trend_follow.adx_min_trade' in OGUL_SRC, (
        "trend_follow adx_min_trade config'den okunmuyor"
    )


# ── C2: trend_follow günlük max trade limiti ─────────────────────
def test_c2_trend_follow_daily_trade_cap():
    """trend_follow günlük max trade limiti _generate_signal'da kontrol edilmeli."""
    assert "max_trades_per_day" in OGUL_SRC, (
        "max_trades_per_day kontrolü koddan kalkmış"
    )
    assert "_tf_trade_count_today" in OGUL_SRC, (
        "_tf_trade_count_today state field koddan kalkmış"
    )
    assert 'strategies.trend_follow.max_trades_per_day' in OGUL_SRC, (
        "max_trades_per_day config'den okunmuyor"
    )


# ── C3: KARAR #17 tam hard-block kaldırıldı ─────────────────────
def test_c3_karar_17_hardblock_removed():
    """_execute_signal başında trend_follow hard-block AKTİF KOD olarak kaldırılmış olmalı."""
    # KARAR #17 yorum referansı KORUNMALI (tarihçe için)
    assert "KARAR #17" in OGUL_SRC, "KARAR #17 tarihçe yorumu silinmiş"
    assert "KARAR #18" in OGUL_SRC, "KARAR #18 yorumu yok"

    # _execute_signal içinde aktif (yorum olmayan) hard-block kalıbı KALMAMIŞ olmalı
    # Eski hard-block aşağıdaki gibiydi:
    #   if strategy_name == "trend_follow":
    #       logger.info(...HARD_BLOCK...)
    #       self.db.insert_event(...trend_follow hard-block...)
    #       return
    # Bu blok şimdi yorumda olmalı, aktif değil

    # _execute_signal fonksiyonunu izole et
    m = re.search(
        r'def _execute_signal\(self,.*?\n(.*?)(?=\n    def |\nclass )',
        OGUL_SRC, re.DOTALL,
    )
    assert m, "_execute_signal bulunamadı"
    body = m.group(1)
    # Yorum satırları çıkar
    code_only = "\n".join(
        line for line in body.split("\n")
        if not line.strip().startswith("#")
    )
    # Aktif kod içinde "trend_follow hard-block" string LITERAL kalmamalı
    assert 'trend_follow hard-block' not in code_only, (
        "_execute_signal hala aktif trend_follow hard-block içeriyor"
    )
    # Aktif kod içinde "[TREND_FOLLOW HARD_BLOCK" log mesajı kalmamalı
    assert '[TREND_FOLLOW HARD_BLOCK' not in code_only, (
        "_execute_signal hala aktif HARD_BLOCK log içeriyor — KARAR #17 kaldırılmamış"
    )


# ── C4: TF sayacı increment_daily_trade_count yanında artıyor ────
def test_c4_tf_counter_increments_after_trade():
    """trend_follow sayacı başarılı emir sonrası artmalı."""
    # Pattern: increment_daily_trade_count() + StrategyType.TREND_FOLLOW + _tf_trade_count_today += 1
    assert "self._tf_trade_count_today += 1" in OGUL_SRC, (
        "trend_follow sayacı artırma kodu kalkmış"
    )
    # signal.strategy == StrategyType.TREND_FOLLOW kontrolü var mı
    pattern = re.search(
        r"increment_daily_trade_count\(\)[^}]{0,500}?TREND_FOLLOW[^}]{0,500}?_tf_trade_count_today \+= 1",
        OGUL_SRC, re.DOTALL,
    )
    assert pattern, (
        "TF sayacı artırması increment_daily_trade_count'tan sonra değil veya bağlantısı kopmuş"
    )


# ── C5: mean_reversion varsayılan parametreleri korunuyor ────────
def test_c5_mean_reversion_defaults_unchanged():
    """mean_reversion RSI 20/80 ve W%R zorunluluğu KORUNMALI."""
    mr = CONFIG["strategies"]["mean_reversion"]
    assert mr["rsi_oversold"] == 20.0, "MR RSI oversold 20 olmalı"
    assert mr["rsi_overbought"] == 80.0, "MR RSI overbought 80 olmalı"
    assert mr["bb_period"] == 20
    assert mr["bb_std"] == 2.0
    assert mr["williams_r_oversold"] == -80.0
    assert mr["williams_r_overbought"] == -20.0
    # Kod tarafında MR_RSI_OVERSOLD/OVERBOUGHT sabitleri 20/80 olmalı
    assert "MR_RSI_OVERSOLD:  float = 20.0" in OGUL_SRC
    assert "MR_RSI_OVERBOUGHT: float = 80.0" in OGUL_SRC


# ── C6: breakout _enabled flag kontrolü ──────────────────────────
def test_c6_breakout_enabled_flag():
    """breakout _enabled=False olduğunda strateji atlanmalı."""
    # Config tarafında flag var
    bo = CONFIG["strategies"]["breakout"]
    assert "_enabled" in bo, "breakout._enabled flag'ı config'de yok"
    assert bo["_enabled"] is False, (
        "breakout şu an False olmalı (KARAR #18 backtest negatif)"
    )
    # Kod tarafında flag kontrolü var
    assert 'strategies.breakout._enabled' in OGUL_SRC, (
        "breakout._enabled config kontrolü koddan kalkmış"
    )


# ── C7: config/default.json strategies yeni anahtarlar ───────────
def test_c7_config_strategies_new_keys():
    """KARAR #18 ile eklenen config anahtarları yerinde."""
    tf = CONFIG["strategies"]["trend_follow"]
    assert tf["adx_min_trade"] == 32.0, "adx_min_trade=32 olmalı"
    assert tf["sl_atr_mult"] == 1.2, "TF SL 1.5→1.2 olmalı"
    assert tf["tp_atr_mult"] == 2.5, "TF TP 2.0→2.5 olmalı"
    assert tf["max_trades_per_day"] == 5, "max_trades_per_day=5 olmalı"
    assert "daily_loss_pct_limit" in tf, "daily_loss_pct_limit eklenmemiş"
    # adx_threshold KARAR #17'deki 9999 değerinden geri çekildi
    assert tf["adx_threshold"] != 9999.0, (
        "adx_threshold hala KARAR #17'nin 9999 değerinde — geri alınmamış"
    )


# ── C8: KARAR #18 karar tarihçesi yorumu ─────────────────────────
def test_c8_karar_18_history_documented():
    """KARAR #18 _decision_history config'de ve KARAR #18 yorumu kodda olmalı."""
    tf = CONFIG["strategies"]["trend_follow"]
    assert "_decision_history" in tf, "trend_follow _decision_history yok"
    history_str = json.dumps(tf["_decision_history"])
    assert "KARAR #17" in history_str, "KARAR #17 tarihçesi kayıp"
    assert "KARAR #18" in history_str, "KARAR #18 tarihçesi kayıp"

    # Kod tarafında en az 5 KARAR #18 referansı olmalı
    karar_18_count = OGUL_SRC.count("KARAR #18")
    assert karar_18_count >= 5, (
        f"KARAR #18 yorum referansı az ({karar_18_count}) — koruma niyeti silikleşmiş"
    )


# ── C9: TF default sabitleri güncellenmiş ────────────────────────
def test_c9_tf_default_constants_updated():
    """ogul.py'deki TF_SL_ATR_MULT ve TF_TP_ATR_MULT defaults güncel."""
    assert "TF_SL_ATR_MULT:       float = 1.2" in OGUL_SRC, (
        "TF_SL_ATR_MULT defaultu 1.5 → 1.2 değişmemiş"
    )
    assert "TF_TP_ATR_MULT:       float = 2.5" in OGUL_SRC, (
        "TF_TP_ATR_MULT defaultu 2.0 → 2.5 değişmemiş"
    )


# ── C10: TF günlük sayacı reset mantığı ──────────────────────────
def test_c10_tf_counter_daily_reset():
    """trend_follow günlük sayacı her yeni günde sıfırlanmalı."""
    assert "self._tf_trade_count_date" in OGUL_SRC, (
        "_tf_trade_count_date state field koddan kalkmış"
    )
    # Reset pattern: tarih farklıysa sıfırla
    pattern = re.search(
        r"if self\._tf_trade_count_date != today:.*?"
        r"self\._tf_trade_count_today = 0",
        OGUL_SRC, re.DOTALL,
    )
    assert pattern, "TF sayacı günlük sıfırlama mantığı yok"
