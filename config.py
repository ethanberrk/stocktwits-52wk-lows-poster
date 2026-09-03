"""All knobs in one place. Nothing else defines numbers or thresholds."""
import os
import re

MIN_MARKET_CAP = 1_000_000_000          # USD floor
MAX_PER_TICK = int(os.environ.get("MAX_PER_TICK", "2"))   # posts per 30-min tick
MAX_PER_DAY = int(os.environ.get("MAX_PER_DAY", "20"))    # posts per trading day
MAX_PLAUSIBLE_LOWS = 1200               # validation gate: more = broken source

MARKET_TZ = "America/New_York"
MARKET_OPEN = (9, 30)                   # ET
MARKET_CLOSE = (16, 0)                  # ET

# Self-rendered charts: keyless daily-OHLC history + live quote from
# stockanalysis.com (same source the relative-strength poster runs on).
SA_QUOTE_URL = "https://stockanalysis.com/api/quotes/s/{ticker}"
SA_HISTORY_URL = ("https://stockanalysis.com/api/symbol/s/{ticker}/history"
                  "?range=1Y&period=Daily")
MIN_HISTORY_DAYS = 330      # refuse a "1Y" chart for a recent IPO with less
                            # than ~11 months of candles — it would mislead
CHART_WIDTH = 800           # px; matches the size chart-img produced
CHART_HEIGHT = 450
# public, unauthenticated; used to validate a cashtag resolves before posting
STOCKTWITS_SYMBOL_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
STOCKTWITS_CREATE_URL = "https://api.stocktwits.com/api/2/messages/create.json"
STOCKTWITS_USER_AGENT = "stocktwits-52wk-lows-poster/1.0"

# Drop non-common-equity by name (same rule the WSJ prototype proved out)
NAME_EXCLUDE_RE = re.compile(
    r"\b(ETF|Fund|Pfd|Preferred|Notes?|Units?|Warrants?|Wt|Bond|Rt|Rights)\b"
    r"|Acquisition Corp",
    re.I,
)

# Instrument hygiene. Yahoo hands preferred shares and warrants the PARENT
# common's longName (so NAME_EXCLUDE_RE never fires) and the parent's market
# cap (so they rank at the top of a size-ranked feed). Invisible on the high
# side; pervasive on the low side, where these lines sit near their lows
# structurally and barely trade. Verified live 2026-07-27: PREFERRED_RE caught
# 106 rows with zero false positives, WARRANT_RE caught exactly DJTWW, and all
# 18 legitimate dual-class lines (BRK-B, PBR-A, HEI-A, MOG-A, ...) survived.
PREFERRED_RE = re.compile(r"-P[A-Z]?$")          # WFC-PC, ALL-PH, KEY-PK
# Two symbologies for the same three instrument types (warrant/right/unit):
# NASDAQ's 5-letter convention (DJTWW) and NYSE/AMEX's dash suffix
# (XYZ-WT, XYZ-RT, XYZ-UN). Only the first was covered until 2026-07-27 --
# the dash form inherits the parent's longName and market cap just like a
# preferred does, and clears the dollar-volume floor on a heavily traded
# parent. Real dual-class lines (BRK-B, PBR-A, MKC-V, ...) never end in a
# bare -W/-R/-U/-WT/-RT/-UN, so neither branch below touches them.
WARRANT_RE = re.compile(r"^[A-Z]{4}(W|R|U)$|-(WT|RT|UN|W|R|U)$")

# A line parked at its 52-week low on a hundred shares a day re-qualifies
# every session and the 2-day cooldown returns it indefinitely (TAP-A,
# 116 shares, 2026-07-27). Dollar volume, so it scales across price levels.
MIN_DOLLAR_VOLUME = 5_000_000

# Ask Yahoo for listed exchanges only. Without this the screen's 3000-row page
# cap is consumed by ~1,700 pink-sheet rows the exchange check discards later,
# truncating the real market-cap floor to ~$6.6B (measured 2026-07-27). With
# it: 2,766 rows down to a true $1.001B floor, no truncation.
SCREEN_EXCHANGES = ("NMS", "NYQ", "NGM", "NCM", "ASE")

# Runtime tripwire, not a filter: a working exchange filter reaches down to
# ~$1.0B. If yfinance ever turns "is-in" into a no-op, the screen silently
# reverts to 3,000 truncated rows and a ~$6.6B effective floor -- fewer,
# larger names, no alarm otherwise. _screen_rows prints (does not raise) when
# the screened minimum market cap exceeds this.
SCREEN_TRUNCATION_WARN_CAP = 2_000_000_000

# Bound the walk-down. Per candidate the Stocktwits symbol check allows 15s
# and each get_json retries 4x at 12s, so an unbounded walk over a selloff-day
# lows list can outrun the workflow timeout — and because tick.yml uses
# concurrency without cancel-in-progress, a stuck run queues later dispatches
# until GitHub drops them and the feed goes dark silently.
# Counts candidates EXAMINED, not charts fetched: the symbol check runs first
# and costs real time even when no chart is attempted.
# NOTE: this bound alone does not keep a tick inside timeout-minutes: 15 —
# worst case is ~20 x 110s ≈ 39 minutes. The job's timeout-minutes is the
# real backstop that ends a stuck run; this cap exists so a degraded chart
# source ends the tick with a clear log line well before that, rather than
# being killed mid-walk with no explanation.
MAX_CANDIDATE_ATTEMPTS = 20

# ---------------------------------------------------------------------------
# Data-source switch. "legacy" = the scraped feeds above (Yahoo screener +
# stockanalysis.com charts); "xignite" = Ethan's licensed Xignite subscription
# (Nasdaq Trader symbol files for the universe, GlobalQuotes for the 52wk
# test, FactSet fundamentals for market cap, GlobalHistorical for charts).
# In CI this is the repository VARIABLE `DATA_SOURCE` (tick.yml), so going
# live — and reverting — is a Settings change, not a deploy. Design:
# docs/superpowers/specs/2026-09-03-xignite-data-source-design.md
DATA_SOURCE = os.environ.get("DATA_SOURCE", "legacy")
DATA_SOURCES = ("legacy", "xignite")
XIGNITE_TOKEN = os.environ.get("XIGNITE_TOKEN", "")
XIGNITE_QUOTES_URL = ("https://globalquotes.xignite.com/v3/xGlobalQuotes.json/"
                      "GetGlobalDelayedQuotes")
XIGNITE_HISTORY_URL = ("https://globalhistorical.xignite.com/v3/xGlobalHistorical.json/"
                       "GetGlobalHistoricalQuotesRange")
XIGNITE_FUNDAMENTALS_URL = ("https://factsetfundamentals.xignite.com/"
                            "xFactSetFundamentals.json/GetFundamentals")
XIGNITE_BATCH = 500                     # identifiers per call (verified 2026-09-03)
XIGNITE_HISTORY_DAYS = 400              # calendar days requested for a "1Y" chart
XIGNITE_EXCHANGES = ("NYSE", "NASDAQ", "AMEX")   # Security.Market values kept

# Universe for the xignite source: Nasdaq Trader's official symbol
# directories (keyless; refreshed nightly). nasdaqlisted.txt = Nasdaq;
# otherlisted.txt = every other US exchange, filtered to NYSE (N) and NYSE
# American (A) — Arca/BATS/IEX are ETF venues. ETF and test issues dropped.
# Preferreds/warrants/units use PREFERRED_RE / WARRANT_RE above.
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
OTHER_LISTED_EXCHANGES = ("N", "A")
MIN_UNIVERSE_SIZE = 1000                # tripwire: fewer listed names = broken files

# Shadow comparison output (see scripts/shadow.py)
SHADOW_DIR = "shadow"
