"""ÜSTAT API — Pydantic request/response şemaları.

Tüm endpoint'lerin veri kontratları burada tanımlanır.
Engine modelleri (Trade, Regime, RiskParams vb.) → API response modelleri
dönüşümü bu şemalar aracılığıyla yapılır.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════
#  STATUS
# ═══════════════════════════════════════════════════════════════════

class StatusResponse(BaseModel):
    """GET /api/status — Sistem durumu."""
    version: str = "5.5.0"
    engine_running: bool = False
    mt5_connected: bool = False
    regime: str = "TREND"          # TREND / RANGE / VOLATILE / OLAY
    regime_confidence: float = 0.0
    risk_multiplier: float = 1.0
    phase: str = "idle"            # idle / running / stopped / error
    kill_switch_level: int = 0     # 0=yok, 1=L1, 2=L2, 3=L3
    daily_trade_count: int = 0
    uptime_seconds: int = 0
    last_cycle: str | None = None
    deactivated_symbols: list[str] = []
    warnings: list[WarningItem] = []
    # v5.4.1: Sessiz hata göstergesi
    data_fresh: bool = True                       # veri güncel mi?
    last_successful_cycle: str | None = None       # son başarılı cycle ISO timestamp
    circuit_breaker_active: bool = False            # MT5 circuit breaker durumu


class WarningItem(BaseModel):
    """Erken uyarı kalemi."""
    type: str           # SPREAD_SPIKE, PRICE_SHOCK, VOLUME_SPIKE, USDTRY_SHOCK
    symbol: str
    severity: str       # WARNING / CRITICAL
    value: float
    threshold: float
    message: str = ""


# Forward-ref güncelle
StatusResponse.model_rebuild()


# ═══════════════════════════════════════════════════════════════════
#  ACCOUNT
# ═══════════════════════════════════════════════════════════════════

class AccountResponse(BaseModel):
    """GET /api/account — Hesap bilgileri."""
    login: int = 0
    server: str = ""
    currency: str = "TRY"
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    free_margin: float = 0.0
    margin_level: float = 0.0
    floating_pnl: float = 0.0
    daily_pnl: float = 0.0


# ═══════════════════════════════════════════════════════════════════
#  POSITIONS
# ═══════════════════════════════════════════════════════════════════

class PositionItem(BaseModel):
    """Tek açık pozisyon."""
    ticket: int
    symbol: str
    direction: str       # BUY / SELL
    volume: float
    entry_price: float
    current_price: float
    sl: float = 0.0
    tp: float = 0.0
    pnl: float = 0.0     # profit + swap (toplam floating K/Z)
    swap: float = 0.0    # birikmiş swap maliyeti
    open_time: str = ""
    strategy: str = ""   # "manual" | "trend_follow" | "mean_reversion" | "breakout" | "bilinmiyor"
    tur: str = ""        # "Otomatik" | "Manuel" | "Hibrit" — backend tek kaynak
    # ── Evrensel pozisyon yönetimi alanları ──────────────────────
    tp1_hit: bool = False         # TP1 yarı kapanış tetiklendi mi
    breakeven_hit: bool = False   # breakeven seviyesi çekildi mi
    cost_averaged: bool = False   # maliyetlendirme yapıldı mı
    peak_profit: float = 0.0     # ulaşılan en yüksek kâr (puan)
    voting_score: int = 0        # anlık 4-gösterge oylama skoru (0-4)
    # ── Manuel pozisyon risk göstergesi ─────────────────────────
    risk_score: dict = {}        # {sl_risk, regime_risk, pnl_risk, system_risk, overall, score}


class PositionsResponse(BaseModel):
    """GET /api/positions — Açık pozisyonlar."""
    count: int = 0
    positions: list[PositionItem] = []


class ClosePositionRequest(BaseModel):
    """POST /api/positions/close isteği."""
    ticket: int


class ClosePositionResponse(BaseModel):
    """Pozisyon kapatma yanıtı."""
    success: bool
    message: str


# ═══════════════════════════════════════════════════════════════════
#  TRADES
# ═══════════════════════════════════════════════════════════════════

class TradeItem(BaseModel):
    """Tek işlem kaydı."""
    id: int
    symbol: str
    direction: str
    strategy: str = ""
    lot: float = 0.0
    entry_price: float | None = None
    exit_price: float | None = None
    pnl: float | None = None
    slippage: float | None = None
    commission: float | None = None
    swap: float | None = None
    regime: str | None = None
    fake_score: int | None = None
    exit_reason: str | None = None
    entry_time: str | None = None
    exit_time: str | None = None


class TradesResponse(BaseModel):
    """GET /api/trades — İşlem geçmişi."""
    count: int = 0
    trades: list[TradeItem] = []


class TradeStatsResponse(BaseModel):
    """GET /api/trades/stats — İşlem istatistikleri."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    best_trade: TradeItem | None = None     # en kârlı
    worst_trade: TradeItem | None = None    # en zararlı
    longest_trade: TradeItem | None = None  # en uzun (süre)
    shortest_trade: TradeItem | None = None # en kısa (süre)
    avg_duration_minutes: float = 0.0
    by_strategy: dict[str, StrategyStats] = {}
    by_symbol: dict[str, SymbolStats] = {}


class StrategyStats(BaseModel):
    """Strateji bazlı istatistikler."""
    trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0


class SymbolStats(BaseModel):
    """Sembol bazlı istatistikler."""
    trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0


# Forward-ref güncelle
TradeStatsResponse.model_rebuild()


class ApproveRequest(BaseModel):
    """POST /api/trades/approve — İşlem onaylama."""
    trade_id: int
    approved_by: str = "operator"
    notes: str = ""


class ApproveResponse(BaseModel):
    """POST /api/trades/approve response."""
    success: bool
    trade_id: int
    message: str = ""


# ═══════════════════════════════════════════════════════════════════
#  RISK
# ═══════════════════════════════════════════════════════════════════

class RiskResponse(BaseModel):
    """GET /api/risk — Risk snapshot."""
    # Drawdown
    daily_pnl: float = 0.0
    daily_drawdown_pct: float = 0.0
    weekly_drawdown_pct: float = 0.0
    monthly_drawdown_pct: float = 0.0
    total_drawdown_pct: float = 0.0
    floating_pnl: float = 0.0
    equity: float = 0.0  # Snapshot equity (floating kayıp oranı hesabı için)
    balance: float = 0.0  # Hesap bakiyesi (floating hariç)

    # Limitler
    max_daily_loss: float = 0.018
    max_weekly_loss: float = 0.04
    max_monthly_loss: float = 0.07
    hard_drawdown: float = 0.15
    max_floating_loss: float = 0.015

    # Durum
    can_trade: bool = True
    lot_multiplier: float = 1.0
    kill_switch_level: int = 0
    blocked_symbols: list[str] = []
    risk_reason: str = ""

    # Rejim
    regime: str = "TREND"
    risk_multiplier: float = 1.0

    # Sayaçlar
    daily_trade_count: int = 0
    max_daily_trades: int = 5
    consecutive_losses: int = 0
    consecutive_loss_limit: int = 3
    cooldown_until: str | None = None

    # Pozisyon limitleri
    open_positions: int = 0
    max_open_positions: int = 5

    # Graduated lot (v5.1)
    graduated_lot_mult: float = 1.0


# ═══════════════════════════════════════════════════════════════════
#  PERFORMANCE
# ═══════════════════════════════════════════════════════════════════

class PerformanceResponse(BaseModel):
    """GET /api/performance — Performans metrikleri."""
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_trade_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    best_day_pnl: float = 0.0
    worst_day_pnl: float = 0.0
    equity_curve: list[EquityPoint] = []


class EquityPoint(BaseModel):
    """Equity eğrisi noktası."""
    timestamp: str
    equity: float
    daily_pnl: float = 0.0
    balance: float = 0.0


# Forward-ref güncelle
PerformanceResponse.model_rebuild()


# ═══════════════════════════════════════════════════════════════════
#  TOP 5
# ═══════════════════════════════════════════════════════════════════

class Top5Item(BaseModel):
    """Top 5 kontrat kalemi."""
    rank: int
    symbol: str
    score: float = 0.0
    regime: str = ""
    signal_direction: str = ""  # "BUY" | "SELL" | "BEKLE"


class Top5Response(BaseModel):
    """GET /api/top5 — Güncel Top 5 kontrat."""
    contracts: list[Top5Item] = []
    last_refresh: str | None = None
    all_scores: dict[str, float] = {}


# ═══════════════════════════════════════════════════════════════════
#  KILLSWITCH
# ═══════════════════════════════════════════════════════════════════

class KillSwitchRequest(BaseModel):
    """POST /api/killswitch — Kill-switch tetikleme/onaylama."""
    action: str = Field(
        ...,
        description="activate (L3 manuel tam kapanış) veya acknowledge (onaylama/sıfırlama)",
    )
    user: str = "operator"
    reason: str = ""


class KillSwitchResponse(BaseModel):
    """POST /api/killswitch response."""
    success: bool
    kill_switch_level: int = 0
    message: str = ""
    failed_tickets: list[int] = []  # L3 kapanışta kapatılamayan pozisyon ticket'ları


# ═══════════════════════════════════════════════════════════════════
#  WEBSOCKET LIVE
# ═══════════════════════════════════════════════════════════════════

class LiveTick(BaseModel):
    """WebSocket tick verisi."""
    type: str = "tick"
    symbol: str
    bid: float
    ask: float
    spread: float
    time: str


class LiveEquity(BaseModel):
    """WebSocket equity güncellemesi."""
    type: str = "equity"
    equity: float
    balance: float
    floating_pnl: float
    daily_pnl: float


class LivePosition(BaseModel):
    """WebSocket pozisyon güncellemesi."""
    type: str = "position"
    positions: list[PositionItem] = []


class LiveStatus(BaseModel):
    """WebSocket durum güncellemesi."""
    type: str = "status"
    regime: str = ""
    kill_switch_level: int = 0
    can_trade: bool = True


# ═══════════════════════════════════════════════════════════════════
#  EVENTS (Sistem Log)
# ═══════════════════════════════════════════════════════════════════

class EventItem(BaseModel):
    """Tek olay kaydı."""
    id: int = 0
    timestamp: str = ""
    type: str = ""           # TRADE, ORDER_SENT, KILL_SWITCH, COOLDOWN, ...
    severity: str = "INFO"   # INFO / WARNING / CRITICAL
    message: str = ""
    action: str = ""


class EventsResponse(BaseModel):
    """GET /api/events — Sistem olayları."""
    count: int = 0
    events: list[EventItem] = []


# Forward-ref güncelle
EventsResponse.model_rebuild()


# ═══════════════════════════════════════════════════════════════════
#  OĞUL AKTİVİTE
# ═══════════════════════════════════════════════════════════════════

class OgulSignalItem(BaseModel):
    """Tek sembol için OĞUL sinyal durumu."""
    symbol: str = ""
    direction: str = "NOTR"       # BUY / SELL / NOTR
    buy_votes: int = 0
    sell_votes: int = 0
    rsi_vote: str = "NOTR"
    ema_vote: str = "NOTR"
    atr_expanding: bool = False
    volume_above_avg: bool = False


class OgulUnopenedItem(BaseModel):
    """Açılamayan işlem kaydı."""
    timestamp: str = ""
    message: str = ""


class OgulActivityResponse(BaseModel):
    """GET /api/ogul/activity — OĞUL sinyal aktivitesi."""
    last_m15_close: str = ""          # son M15 mum kapanışı
    regime: str = "TREND"
    active_strategies: list[str] = []  # ["TREND_FOLLOW"] vb.
    adx_value: float = 0.0
    scan_symbols: int = 0             # taranan sembol sayısı
    signal_count: int = 0             # üretilen sinyal sayısı
    unopened_count: int = 0           # reddedilen sinyal sayısı
    signals: list[OgulSignalItem] = []
    unopened: list[OgulUnopenedItem] = []


OgulActivityResponse.model_rebuild()


# ═══════════════════════════════════════════════════════════════════
#  GENEL
# ═══════════════════════════════════════════════════════════════════

class ErrorResponse(BaseModel):
    """Hata response."""
    error: str
    detail: str = ""


class SuccessResponse(BaseModel):
    """Başarılı işlem response."""
    success: bool = True
    message: str = ""


# ═══════════════════════════════════════════════════════════════════
#  MANUEL İŞLEM (İŞLEM PANELİ)
# ═══════════════════════════════════════════════════════════════════

class ManualTradeCheckRequest(BaseModel):
    """Manuel işlem risk ön kontrolü — istek."""
    symbol: str
    direction: str

class ManualTradeCheckResponse(BaseModel):
    """Manuel işlem risk ön kontrolü — yanıt."""
    can_trade: bool = False
    reason: str = ""
    suggested_lot: float = 0.0
    current_price: float = 0.0
    atr_value: float = 0.0
    suggested_sl: float = 0.0
    suggested_tp: float = 0.0
    max_lot: float = 0.0
    risk_summary: dict = {}

class ManualTradeExecuteRequest(BaseModel):
    """Manuel işlem emir gönder — istek."""
    symbol: str
    direction: str
    lot: float
    sl: float | None = None
    tp: float | None = None

class ManualTradeExecuteResponse(BaseModel):
    """Manuel işlem emir gönder — yanıt."""
    success: bool = False
    message: str = ""
    ticket: int = 0
    entry_price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    lot: float = 0.0


class ManualRiskScoresResponse(BaseModel):
    """GET /api/manual-trade/risk-scores — Manuel pozisyon risk göstergeleri."""
    scores: dict = {}


# ═══════════════════════════════════════════════════════════════════
#  HİBRİT İŞLEM
# ═══════════════════════════════════════════════════════════════════

class HybridCheckRequest(BaseModel):
    """Hibrite devir ön kontrolü — istek."""
    ticket: int


class HybridCheckResponse(BaseModel):
    """Hibrite devir ön kontrolü — yanıt."""
    can_transfer: bool = False
    reason: str = ""
    symbol: str = ""
    direction: str = ""
    volume: float = 0.0
    entry_price: float = 0.0
    current_price: float = 0.0
    atr_value: float = 0.0
    suggested_sl: float = 0.0
    suggested_tp: float = 0.0
    hybrid_daily_pnl: float = 0.0
    hybrid_daily_limit: float = 500.0
    active_hybrid_count: int = 0
    max_hybrid_count: int = 3


class HybridTransferRequest(BaseModel):
    """Hibrite devret — istek."""
    ticket: int


class HybridTransferResponse(BaseModel):
    """Hibrite devret — yanıt."""
    success: bool = False
    message: str = ""
    ticket: int = 0
    symbol: str = ""
    sl: float = 0.0
    tp: float = 0.0
    entry_atr: float = 0.0


class HybridRemoveRequest(BaseModel):
    """Hibritten çıkar — istek."""
    ticket: int


class HybridRemoveResponse(BaseModel):
    """Hibritten çıkar — yanıt."""
    success: bool = False
    message: str = ""


class HybridPositionItem(BaseModel):
    """Hibrit pozisyon detayı."""
    ticket: int
    symbol: str
    direction: str
    volume: float
    entry_price: float
    current_price: float = 0.0
    entry_atr: float
    initial_sl: float
    initial_tp: float
    current_sl: float
    current_tp: float
    pnl: float = 0.0
    swap: float = 0.0
    breakeven_hit: bool = False
    trailing_active: bool = False
    transferred_at: str = ""
    state: str = "ACTIVE"


class HybridStatusResponse(BaseModel):
    """Hibrit panel durum bilgisi."""
    active_count: int = 0
    max_count: int = 3
    daily_pnl: float = 0.0
    daily_limit: float = 500.0
    native_sltp: bool = False
    positions: list[HybridPositionItem] = []


class HybridEventItem(BaseModel):
    """Hibrit olay kaydı."""
    id: int = 0
    timestamp: str = ""
    ticket: int = 0
    symbol: str = ""
    event: str = ""
    details: str = ""


class HybridEventsResponse(BaseModel):
    """Hibrit olaylar listesi."""
    count: int = 0
    events: list[HybridEventItem] = []


# ═══════════════════════════════════════════════════════════════════
#  ÜSTAT BEYİN (v13.0)
# ═══════════════════════════════════════════════════════════════════

class CategoryGroup(BaseModel):
    """İşlem kategori grubu (sonuç/yön/süre/rejim bazlı)."""
    label: str
    count: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    avg_pnl: float = 0.0


class TradeCategories(BaseModel):
    """Çok boyutlu işlem kategorizasyonu."""
    by_result: list[CategoryGroup] = []
    by_direction: list[CategoryGroup] = []
    by_duration: list[CategoryGroup] = []
    by_regime: list[CategoryGroup] = []
    by_exit_reason: list[CategoryGroup] = []


class ContractProfile(BaseModel):
    """Kontrat bazlı detaylı profil."""
    symbol: str
    trade_count: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    avg_duration_min: float = 0.0
    best_pnl: float = 0.0
    worst_pnl: float = 0.0
    last_trade: str = ""
    preferred_direction: str = ""  # BUY veya SELL


class ErrorAttribution(BaseModel):
    """Hata atama kaydı — BABA veya OĞUL sorumluluğu."""
    trade_id: int
    error_type: str
    responsible: str  # "BABA" | "OGUL"
    description: str


class NextDayAnalysis(BaseModel):
    """Ertesi gün analizi — kapanan işlemlerin detaylı puanlaması."""
    trade_id: int
    symbol: str
    actual_pnl: float
    potential_pnl: float
    missed_profit: float
    signal_score: float
    management_score: float
    profit_score: float = 0.0
    risk_score: float = 0.0
    total_score: float = 0.0
    summary: str


class RegulationSuggestion(BaseModel):
    """Parametre regülasyon önerisi — BABA/OĞUL parametreleri."""
    parameter: str
    current_value: str
    suggested_value: str
    reason: str
    priority: str = "MEDIUM"  # HIGH / MEDIUM / LOW


class StrategyProfile(BaseModel):
    """Strateji havuzu profili — dönem parametreleri."""
    name: str
    market_type: str = ""  # volatil / duragan / patlama
    parameters: dict = {}
    active: bool = False


class StrategyPool(BaseModel):
    """Strateji havuzu durumu — rejime göre aktif parametre seti."""
    current_regime: str = ""
    active_profile: str = ""
    profiles: list[StrategyProfile] = []


class UstatBrainResponse(BaseModel):
    """GET /api/ustat/brain — ÜSTAT beyin analiz verileri."""
    trade_categories: TradeCategories = TradeCategories()
    contract_profiles: list[ContractProfile] = []
    recent_decisions: list[EventItem] = []
    regime_performance: list[CategoryGroup] = []
    error_attributions: list[ErrorAttribution] = []
    next_day_analyses: list[NextDayAnalysis] = []
    strategy_pool: StrategyPool = StrategyPool()
    regulation_suggestions: list[RegulationSuggestion] = []


# ═══════════════════════════════════════════════════════════════════
#  SİSTEM SAĞLIĞI
# ═══════════════════════════════════════════════════════════════════

class HealthResponse(BaseModel):
    """GET /api/health — Sistem sağlığı metrikleri."""
    cycle: dict = {}        # döngü zamanlama metrikleri
    mt5: dict = {}          # MT5 bağlantı metrikleri
    orders: dict = {}       # emir performans metrikleri
    layers: dict = {}       # katman durumları (BABA, OĞUL, H-Engine, ÜSTAT)
    recent_events: list[dict] = []  # son 30 olay
    system: dict = {}       # sistem bilgileri (uptime, DB boyutu, WS istemci)


# Forward-ref güncelle
UstatBrainResponse.model_rebuild()


# ═══════════════════════════════════════════════════════════════════
#  SETTINGS — Risk Baseline Date
# ═══════════════════════════════════════════════════════════════════

class RiskBaselineGetResponse(BaseModel):
    """GET /api/settings/risk-baseline — Mevcut risk baseline tarihi."""
    baseline_date: str = ""
    source: str = "config"    # config | default


class RiskBaselineUpdateRequest(BaseModel):
    """POST /api/settings/risk-baseline — Baseline tarih güncelle."""
    new_date: str = Field(..., description="Yeni baseline tarihi (YYYY-MM-DD veya YYYY-MM-DD HH:MM)")


class RiskBaselineUpdateResponse(BaseModel):
    """POST /api/settings/risk-baseline response."""
    success: bool = False
    message: str = ""
    old_date: str = ""
    new_date: str = ""
