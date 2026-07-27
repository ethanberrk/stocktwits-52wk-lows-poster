from datetime import date, datetime
from zoneinfo import ZoneInfo

import config
from src.source.base import Candidate, LowsSource, SourceError
import yfinance as yf

# Yahoo exchange codes -> TradingView prefixes chart-img understands
_EXCHANGES = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ",
              "NYQ": "NYSE", "ASE": "AMEX"}
_REQUIRED = ("symbol", "regularMarketPrice", "regularMarketDayLow",
             "fiftyTwoWeekLow", "marketCap", "regularMarketTime",
             "regularMarketVolume")

def _row_to_candidate(row: dict, today: date) -> Candidate | None:
    if any(row.get(k) is None for k in _REQUIRED):
        return None
    if row.get("quoteType") != "EQUITY":
        return None
    # Preferreds and warrants inherit the parent's name AND market cap, so
    # neither NAME_EXCLUDE_RE nor the mcap floor stops them. Symbol shape does.
    symbol = row["symbol"]
    if config.PREFERRED_RE.search(symbol) or config.WARRANT_RE.match(symbol):
        return None
    name = row.get("longName") or row.get("shortName") or ""
    if not name or config.NAME_EXCLUDE_RE.search(name):
        return None
    # Exchange-listed only: drops OTC/pink-sheet lines (PNK/OQX/OID etc.) —
    # not the "US stocks at new lows" our audience means, and there's no
    # exchange prefix to resolve for the chart legend anyway.
    if row.get("exchange") not in _EXCHANGES:
        return None
    # Liquidity floor: a flat print on a hundred shares is not a new low
    # anyone traded. Dollar volume, not share count.
    if (float(row["regularMarketPrice"]) * float(row["regularMarketVolume"])
            < config.MIN_DOLLAR_VOLUME):
        return None
    # Freshness gate: the quote must have traded TODAY (ET). On market
    # holidays every quote still carries the previous session's timestamp,
    # so this makes stale "new low today" posts structurally impossible —
    # no holiday calendar needed, and unscheduled closures are covered too.
    traded = datetime.fromtimestamp(
        row["regularMarketTime"], ZoneInfo(config.MARKET_TZ)).date()
    if traded != today:
        return None
    # Day-cumulative 52wk-low test: today's low touched the 52wk low.
    # Yahoo's fiftyTwoWeekLow already includes today, so equality == new low.
    if row["regularMarketDayLow"] - 1e-6 > row["fiftyTwoWeekLow"]:
        return None
    return Candidate(
        ticker=row["symbol"],
        name=name,
        exchange=_EXCHANGES.get(row.get("exchange"), ""),
        price=float(row["regularMarketPrice"]),
        pct_change_today=float(row.get("regularMarketChangePercent") or 0.0),
        market_cap=float(row["marketCap"]),
        week52_low=float(row["fiftyTwoWeekLow"]),
        security_type=row["quoteType"],
    )

_PAGE = 250
_MAX_OFFSET = 3000  # safety backstop; ~2-3k US names clear the $1B floor

class YFinanceSource(LowsSource):
    """Screen US equities >$1B by mcap desc, keep rows on today's 52wk-low list."""

    def _screen_rows(self) -> list[dict]:
        q = yf.EquityQuery("and", [
            yf.EquityQuery("eq", ["region", "us"]),
            yf.EquityQuery("gt", ["intradaymarketcap", config.MIN_MARKET_CAP]),
            yf.EquityQuery("is-in", ["exchange", *config.SCREEN_EXCHANGES]),
        ])
        rows, offset = [], 0
        while offset < _MAX_OFFSET:
            resp = yf.screen(q, offset=offset, size=_PAGE,
                             sortField="intradaymarketcap", sortAsc=False)
            quotes = (resp or {}).get("quotes", [])
            rows.extend(quotes)
            if len(quotes) < _PAGE:
                break
            offset += _PAGE
        return rows

    def fetch_candidates(self) -> list:
        rows = self._screen_rows()
        if not rows:
            raise SourceError("Yahoo screen returned zero quotes; feed looks broken")
        today = datetime.now(ZoneInfo(config.MARKET_TZ)).date()
        return [c for c in (_row_to_candidate(r, today) for r in rows) if c is not None]
