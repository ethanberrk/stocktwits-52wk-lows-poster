"""Unit tests for the Xignite 52-week-LOW source: universe parsing, the
day-cumulative test, candidate hygiene (incl. dollar-volume floor), flow."""
from datetime import date

import pytest

import config
from src import xignite
from src.source import xignite_source as xs
from src.source.base import SourceError

NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
AAAP|Pacer Barings CLO Market Flex ETF|G|N|N|100|Y|N
BFRGW|Bullfrog AI Holdings, Inc. - Warrants|S|N|N|100|N|N
BRKHU|Burtech Acquisition Corp II - Units|S|N|N|100|N|N
ZTST|Test Issue Inc|Q|Y|N|100|N|N
File Creation Time: 0903202614:01|||||||
"""
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
A|Agilent Technologies, Inc. Common Stock|N|A|N|100|N|A
BRK.B|Berkshire Hathaway Inc. New Common Stock|N|BRK B|N|100|N|BRK.B
BAC$B|Bank of America Depositary Shares Preferred Series GG|N|BACpB|N|100|N|BAC-B
AAC.U|Ares Acquisition Corporation III Units|N|AAC.U|N|100|N|AAC=
SPY|SPDR S&P 500|P|SPY|Y|100|N|SPY
BTG|B2Gold Corp Common Shares|A|BTG|N|100|N|BTG
UAMY|United States Antimony Corp|A|UAMY|N|100|N|UAMY
"""


def _fetch(url):
    return NASDAQ if "nasdaqlisted" in url else OTHER


def test_canonical_ticker_shapes():
    assert xs.canonical_ticker("AAPL") == "AAPL"
    assert xs.canonical_ticker("BRK.B") == "BRK-B"
    assert xs.canonical_ticker("BAC$B") is None          # preferred
    assert xs.canonical_ticker("AAC.U") is None          # unit
    assert xs.canonical_ticker("ACHR.W") is None         # warrant
    assert xs.canonical_ticker("BFRGW") is None          # Nasdaq warrant shape
    assert xs.canonical_ticker("") is None


def test_listed_universe_filters_and_dash_form(monkeypatch):
    monkeypatch.setattr(config, "MIN_UNIVERSE_SIZE", 1)
    pairs = xs.listed_universe(_fetch)
    assert [t for t, _ in pairs] == ["AAPL", "A", "BRK-B", "BTG", "UAMY"]


def test_listed_universe_floor_trips_on_tiny_list():
    with pytest.raises(SourceError, match="look broken"):
        xs.listed_universe(_fetch)


def test_listed_universe_empty_files_fail():
    with pytest.raises(SourceError):
        xs.listed_universe(lambda url: "")


def _q(**kw):
    base = {"Identifier": "NKE", "Outcome": "Success", "Date": "9/3/2026",
            "Open": 39, "High": 39.5, "Low": 37.95, "Last": 38.2, "Volume": 8_000_000,
            "Low52Weeks": 37.95, "PercentChangeFromPreviousClose": -2.1,
            "Security": {"Name": "Nike Inc", "Market": "NYSE"}}
    base.update(kw)
    return base


TODAY = date(2026, 9, 3)


def test_is_new_low_day_cumulative_and_fresh():
    assert xs.is_new_low(_q(), TODAY)
    assert xs.is_new_low(_q(Low=37.9500001, Low52Weeks=37.95), TODAY)   # float slack
    assert not xs.is_new_low(_q(Low=38.5), TODAY)                       # above the low
    assert not xs.is_new_low(_q(Date="9/2/2026"), TODAY)                # stale / holiday
    assert not xs.is_new_low(_q(Low=0, Low52Weeks=0), TODAY)            # no data


def test_build_candidate_maps_fields():
    c = xs.build_candidate("NKE", "Nike (listed name)", _q(), 5.6e10)
    assert (c.ticker, c.exchange, c.price, c.market_cap, c.week52_low) == \
        ("NKE", "NYSE", 38.2, 5.6e10, 37.95)
    assert c.pct_change_today == -2.1 and c.security_type == "EQUITY"
    assert c.name == "Nike Inc"


def test_build_candidate_hygiene():
    assert xs.build_candidate("X", "n", _q(Security={"Name": "X", "Market": "OTC"}), 5e9) is None
    assert xs.build_candidate("X", "n", _q(Security={"Name": "X Preferred", "Market": "NYSE"}), 5e9) is None
    assert xs.build_candidate("WFC-PC", "n", _q(), 5e9) is None                   # preferred shape
    assert xs.build_candidate("X", "n", _q(), None) is None                       # no mcap
    assert xs.build_candidate("X", "n", _q(), config.MIN_MARKET_CAP - 1) is None  # below floor
    assert xs.build_candidate("X", "n", _q(Last=0), 5e9) is None


def test_build_candidate_dollar_volume_floor():
    # 116 shares parked at the low (TAP-A, 2026-07-27) must not qualify
    assert xs.build_candidate("X", "n", _q(Volume=116), 5e9) is None
    assert xs.build_candidate("X", "n", _q(Volume=config.MIN_DOLLAR_VOLUME / 38.2 + 1), 5e9) is not None
    assert xs.build_candidate("X", "n", _q(Volume=None), 5e9) is None


def test_fetch_candidates_only_asks_mcap_for_hits(monkeypatch):
    universe = [("NKE", "Nike"), ("AAPL", "Apple"), ("SMALL", "Small Co")]
    quotes = {"NKE": _q(), "AAPL": _q(Identifier="AAPL", Low=300, Low52Weeks=225),
              "SMALL": _q(Identifier="SMALL")}
    asked = []

    def caps(tickers):
        asked.extend(tickers)
        return {"NKE": 5.6e10, "SMALL": 5e8}
    monkeypatch.setattr(xignite, "quotes", lambda tks: quotes)
    monkeypatch.setattr(xignite, "market_caps", caps)
    monkeypatch.setattr(xs, "datetime", _FakeDT)
    out = xs.XigniteSource(universe=lambda: universe).fetch_candidates()
    assert asked == ["NKE", "SMALL"]           # AAPL not at a low -> never priced
    assert [c.ticker for c in out] == ["NKE"]  # SMALL under the $1B floor


def test_fetch_candidates_zero_quotes_is_broken_feed(monkeypatch):
    monkeypatch.setattr(xignite, "quotes", lambda tks: {})
    with pytest.raises(SourceError, match="zero quotes"):
        xs.XigniteSource(universe=lambda: [("AAPL", "Apple")]).fetch_candidates()


class _FakeDT:
    @staticmethod
    def now(tz=None):
        from datetime import datetime
        return datetime(2026, 9, 3, 14, 0, tzinfo=tz)
