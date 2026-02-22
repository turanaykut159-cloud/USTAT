"""Sabitler, kontrat listesi ve sektör tanımları."""

# VİOP Pay Vadeli İşlem Kontratları - Aktif semboller
VIOP_EQUITY_FUTURES = [
    "F_AKBNK",
    "F_ARCLK",
    "F_ASELS",
    "F_BIMAS",
    "F_EKGYO",
    "F_EREGL",
    "F_FROTO",
    "F_GARAN",
    "F_GUBRF",
    "F_HEKTS",
    "F_ISCTR",
    "F_KCHOL",
    "F_KOZAA",
    "F_KOZAL",
    "F_KRDMD",
    "F_MGROS",
    "F_PETKM",
    "F_PGSUS",
    "F_SAHOL",
    "F_SASA",
    "F_SISE",
    "F_TAVHL",
    "F_TCELL",
    "F_THYAO",
    "F_TKFEN",
    "F_TOASO",
    "F_TUPRS",
    "F_TTKOM",
    "F_VAKBN",
    "F_YKBNK",
]

# Endeks vadeli kontratları
VIOP_INDEX_FUTURES = [
    "F_XU030",  # BIST 30
    "F_XU100",  # BIST 100
    "F_XBANK",  # BIST Banka
]

# Sektör tanımları
SECTORS = {
    "banka": ["F_AKBNK", "F_GARAN", "F_ISCTR", "F_VAKBN", "F_YKBNK"],
    "holding": ["F_KCHOL", "F_SAHOL", "F_TKFEN"],
    "sanayi": ["F_ARCLK", "F_EREGL", "F_FROTO", "F_TOASO", "F_SISE"],
    "enerji": ["F_PETKM", "F_TUPRS"],
    "teknoloji": ["F_ASELS", "F_TCELL", "F_TTKOM"],
    "madencilik": ["F_KOZAA", "F_KOZAL", "F_KRDMD"],
    "perakende": ["F_BIMAS", "F_MGROS"],
    "havacılık": ["F_THYAO", "F_PGSUS", "F_TAVHL"],
    "kimya": ["F_GUBRF", "F_HEKTS", "F_SASA"],
    "gayrimenkul": ["F_EKGYO"],
}

# Kontrat çarpanları (lot başına)
CONTRACT_MULTIPLIERS = {
    "F_XU030": 1000,
    "F_XU100": 100,
    "F_XBANK": 1000,
    # Pay vadeli kontratlar genelde 100 adet
}
DEFAULT_CONTRACT_MULTIPLIER = 100

# Risk sabitleri
MAX_DAILY_LOSS_PCT = 0.02       # %2
MAX_TOTAL_DRAWDOWN_PCT = 0.10   # %10
MAX_OPEN_POSITIONS = 5
RISK_PER_TRADE_PCT = 0.01       # %1

# Engine sabitleri
CYCLE_INTERVAL_SECONDS = 10
DATA_LOOKBACK_BARS = 500
