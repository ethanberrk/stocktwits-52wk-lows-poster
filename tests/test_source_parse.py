from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.source.base import Candidate
from src.source.yfinance_source import _row_to_candidate

ET = ZoneInfo("America/New_York")
TODAY = date(2026, 7, 1)
# 2026-07-01 14:30 ET, expressed the way Yahoo sends it: epoch seconds
TS_TODAY = int(datetime(2026, 7, 1, 14, 30, tzinfo=ET).timestamp())
TS_YESTERDAY = int(datetime(2026, 6, 30, 15, 59, tzinfo=ET).timestamp())

def row(**over):
    base = {
        "symbol": "AAPL", "shortName": "Apple Inc.", "exchange": "NMS",
        "quoteType": "EQUITY", "regularMarketPrice": 250.0,
        "regularMarketChangePercent": -1.8, "regularMarketDayLow": 248.0,
        "fiftyTwoWeekLow": 248.0, "marketCap": 3.9e12,
        "regularMarketTime": TS_TODAY, "regularMarketVolume": 1_000_000,
    }
    base.update(over)
    return base

def test_new_low_row_parses():
    c = _row_to_candidate(row(), TODAY)
    assert c == Candidate("AAPL", "Apple Inc.", "NASDAQ", 250.0, -1.8,
                          3.9e12, 248.0, "EQUITY")

def test_not_at_low_is_dropped():
    # day low sits above the 52-week low: no new low today
    assert _row_to_candidate(row(regularMarketDayLow=260.0), TODAY) is None

def test_day_cumulative_low_kept_even_after_bounce():
    # broke down earlier today (day low == 52wk low), rallied back to 255
    assert _row_to_candidate(row(regularMarketPrice=255.0), TODAY) is not None

def test_boundary_equality_counts_as_a_new_low():
    # Yahoo's fiftyTwoWeekLow includes today, so exact equality IS the signal
    assert _row_to_candidate(
        row(regularMarketDayLow=248.0, fiftyTwoWeekLow=248.0), TODAY) is not None

def test_float_noise_within_epsilon_still_counts():
    assert _row_to_candidate(
        row(regularMarketDayLow=248.0000001, fiftyTwoWeekLow=248.0), TODAY) is not None

def test_stale_quote_dropped_market_holiday():
    # holiday scenario: gate passes (weekday) but the quote last traded
    # the previous session -> must not post
    assert _row_to_candidate(row(regularMarketTime=TS_YESTERDAY), TODAY) is None

def test_missing_quote_time_dropped():
    r = row(); del r["regularMarketTime"]
    assert _row_to_candidate(r, TODAY) is None
    assert _row_to_candidate(row(regularMarketTime=None), TODAY) is None

def test_non_equity_dropped():
    assert _row_to_candidate(row(quoteType="ETF"), TODAY) is None

def test_excluded_name_dropped():
    assert _row_to_candidate(row(shortName="Foo Acquisition Corp"), TODAY) is None

def test_missing_field_dropped():
    assert _row_to_candidate(row(marketCap=None), TODAY) is None
    r = row(); del r["fiftyTwoWeekLow"]
    assert _row_to_candidate(r, TODAY) is None

def test_exchange_mapping():
    assert _row_to_candidate(row(exchange="NYQ"), TODAY).exchange == "NYSE"
    assert _row_to_candidate(row(exchange="ASE"), TODAY).exchange == "AMEX"
    assert _row_to_candidate(row(exchange="NMS"), TODAY).exchange == "NASDAQ"

def test_otc_and_unknown_exchanges_dropped():
    # pink sheets / OTC markets are not "US stocks at 52wk lows" for our
    # audience, and they have no exchange prefix for the chart legend
    for code in ("PNK", "OQX", "OID", "???", None):
        assert _row_to_candidate(row(exchange=code), TODAY) is None

def test_preferred_shares_dropped():
    # Yahoo gives preferreds the PARENT's longName and market cap, so
    # NAME_EXCLUDE_RE never fires and they rank at the top of a size-ranked
    # feed. Verified live 2026-07-27: 106 such rows in the $1B+ universe.
    for sym in ("WFC-PC", "ALL-PH", "KEY-PK", "JPM-PD", "PCG-PA", "AXIA-PC"):
        assert _row_to_candidate(row(symbol=sym), TODAY) is None, sym

def test_dual_class_common_survives():
    # real share classes, not preferreds — these must still post
    for sym in ("BRK-B", "PBR-A", "HEI-A", "LEN-B", "UHAL-B", "MOG-A", "BF-B"):
        assert _row_to_candidate(row(symbol=sym), TODAY) is not None, sym

def test_warrants_rights_and_units_dropped():
    for sym in ("DJTWW", "ABCDR", "ABCDU"):
        assert _row_to_candidate(row(symbol=sym), TODAY) is None, sym

def test_four_letter_and_ordinary_five_letter_tickers_survive():
    # the warrant rule is 5 chars ending W/R/U — must not eat normal tickers
    for sym in ("AAPL", "GOOGL", "SIRI", "INTC"):
        assert _row_to_candidate(row(symbol=sym), TODAY) is not None, sym

def test_ghost_volume_dropped():
    # TAP-A on 2026-07-27: 116 shares all day, parked exactly at its 52wk low,
    # today-stamped quote. Qualifies forever without a liquidity floor.
    assert _row_to_candidate(
        row(symbol="TAP-A", regularMarketPrice=39.51, regularMarketDayLow=39.51,
            fiftyTwoWeekLow=39.51, regularMarketVolume=116), TODAY) is None

def test_dollar_volume_floor_is_price_times_volume():
    # $10 x 400,000 = $4M -> under the $5M floor
    assert _row_to_candidate(
        row(regularMarketPrice=10.0, regularMarketDayLow=9.0,
            fiftyTwoWeekLow=9.0, regularMarketVolume=400_000), TODAY) is None
    # $10 x 600,000 = $6M -> clears it
    assert _row_to_candidate(
        row(regularMarketPrice=10.0, regularMarketDayLow=9.0,
            fiftyTwoWeekLow=9.0, regularMarketVolume=600_000), TODAY) is not None

def test_missing_volume_dropped():
    r = row(); del r["regularMarketVolume"]
    assert _row_to_candidate(r, TODAY) is None
