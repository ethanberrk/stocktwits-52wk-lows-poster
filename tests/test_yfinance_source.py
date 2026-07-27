import time

import pytest
import config
from src.source import yfinance_source
from src.source.base import SourceError
from src.source.yfinance_source import YFinanceSource

def good_row(sym, day_low, wk_low, ts=None):
    # fetch_candidates compares quote timestamps to the real current ET date,
    # so fixtures default to "now" (= today) and holiday tests pass a stale ts
    return {"symbol": sym, "shortName": f"{sym} Inc", "exchange": "NYQ",
            "quoteType": "EQUITY", "regularMarketPrice": day_low + 1,
            "regularMarketChangePercent": -1.0, "regularMarketDayLow": day_low,
            "fiftyTwoWeekLow": wk_low, "marketCap": 5e9,
            "regularMarketTime": ts if ts is not None else int(time.time()),
            "regularMarketVolume": 1_000_000}

def test_fetch_filters_to_new_lows(monkeypatch):
    src = YFinanceSource()
    rows = [good_row("LO", 90.0, 90.0),        # at 52wk low -> candidate
            good_row("HI", 101.0, 90.0)]       # not at low -> dropped
    monkeypatch.setattr(src, "_screen_rows", lambda: rows)
    got = src.fetch_candidates()
    assert [c.ticker for c in got] == ["LO"]

def test_fetch_raises_source_error_on_empty_screen(monkeypatch):
    src = YFinanceSource()
    monkeypatch.setattr(src, "_screen_rows", lambda: [])
    with pytest.raises(SourceError):
        src.fetch_candidates()

def test_zero_lows_from_nonempty_screen_is_fine(monkeypatch):
    src = YFinanceSource()
    monkeypatch.setattr(src, "_screen_rows", lambda: [good_row("HI", 101.0, 90.0)])
    assert src.fetch_candidates() == []

def test_holiday_all_quotes_stale_yields_no_candidates(monkeypatch):
    # market-holiday scenario: screen succeeds but every quote last traded
    # a prior session -> zero candidates, quiet tick, nothing posted
    stale = int(time.time()) - 3 * 86400
    src = YFinanceSource()
    monkeypatch.setattr(src, "_screen_rows",
                        lambda: [good_row("LO", 90.0, 90.0, ts=stale)])
    assert src.fetch_candidates() == []

def test_screen_query_filters_by_exchange(monkeypatch):
    """The screen must ask Yahoo for listed exchanges only.

    Without this the 3000-row page cap is consumed by ~1,700 pink sheets that
    the exchange check discards anyway, and the effective market-cap floor
    lands at ~$6.6B instead of the $1B config.MIN_MARKET_CAP claims.
    """
    seen = {}

    def fake_screen(q, offset=0, size=250, **kw):
        # EquityQuery.to_dict() exists in yfinance >= 0.2.50 and expands an
        # is-in into nested EQ operands; stringifying is enough to assert on.
        seen["query"] = str(q.to_dict())
        return {"quotes": []}

    monkeypatch.setattr(yfinance_source.yf, "screen", fake_screen)
    yfinance_source.YFinanceSource()._screen_rows()
    for code in config.SCREEN_EXCHANGES:
        assert code in seen["query"], f"{code} missing from screen query"

def test_screen_warns_when_truncated(monkeypatch, capsys):
    # If the exchange filter ever silently stops filtering, the screen
    # reverts to ~$6.6B truncated rows with no other signal -- this is the
    # only alarm. Fixture's minimum cap sits above the $2B tripwire.
    rows = [{"marketCap": 6_600_000_000}, {"marketCap": 3_000_000_000}]
    src = YFinanceSource()
    monkeypatch.setattr(yfinance_source.yf, "screen",
                        lambda *a, **k: {"quotes": rows})
    src._screen_rows()
    assert "WARNING" in capsys.readouterr().out

def test_screen_stays_quiet_when_floor_is_real(monkeypatch, capsys):
    rows = [{"marketCap": 1_001_000_000}, {"marketCap": 3_000_000_000}]
    src = YFinanceSource()
    monkeypatch.setattr(yfinance_source.yf, "screen",
                        lambda *a, **k: {"quotes": rows})
    src._screen_rows()
    assert "WARNING" not in capsys.readouterr().out
