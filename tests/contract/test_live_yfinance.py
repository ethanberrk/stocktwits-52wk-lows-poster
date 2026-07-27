# tests/contract/test_live_yfinance.py
"""Run manually on a market day: pytest -m contract tests/contract/test_live_yfinance.py -v"""
import pytest
import config
from src.source.yfinance_source import YFinanceSource

pytestmark = pytest.mark.contract

def test_screen_returns_plausible_universe_and_lows():
    src = YFinanceSource()
    rows = src._screen_rows()
    # coverage check for the documented pagination-cap limitation
    assert len(rows) > 500, f"screen coverage suspiciously low: {len(rows)} rows"
    cands = src.fetch_candidates()
    assert 0 <= len(cands) < 500
    if cands:
        c = cands[0]
        assert c.ticker and c.market_cap >= 1e9 and c.week52_low > 0
        print(f"\n{len(rows)} screened, {len(cands)} on today's 52wk-low list; "
              f"top: {[x.ticker for x in cands[:10]]}")

@pytest.mark.contract
def test_live_screen_reaches_the_one_billion_floor():
    """The screen must not truncate before $1B, and must carry the low fields."""
    rows = YFinanceSource()._screen_rows()
    assert rows, "screen returned nothing"
    caps = [r["marketCap"] for r in rows if r.get("marketCap")]
    assert min(caps) < 1.1e9, (
        f"screen truncated at ${min(caps)/1e9:.2f}B — the $1B floor is not real")
    assert all(r.get("exchange") in config.SCREEN_EXCHANGES for r in rows)
    have_lows = sum(1 for r in rows
                    if r.get("fiftyTwoWeekLow") is not None
                    and r.get("regularMarketDayLow") is not None)
    assert have_lows > 0.99 * len(rows), (
        f"only {have_lows}/{len(rows)} rows carry the 52-week low fields")
