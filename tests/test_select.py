from datetime import date
import pytest
import config
from src import select
from src.source.base import Candidate

TODAY = date(2026, 7, 1)  # Wednesday

def cand(ticker, mcap):
    return Candidate(ticker, f"{ticker} Inc", "NYSE", 100.0, 2.0,
                     mcap, 99.0, "EQUITY")

def posted_entry(ticker, d=TODAY):
    return {"ticker": ticker, "date": d.isoformat(), "post_id": None}

def test_validate_rejects_implausible_count():
    cands = [cand(f"T{i}", 2e9) for i in range(config.MAX_PLAUSIBLE_LOWS + 1)]
    with pytest.raises(select.ValidationError):
        select.validate(cands)
    select.validate(cands[:10])  # plausible: no raise

def test_ranked_eligible_filters_mcap_and_ranks_desc():
    cands = [cand("SMALL", 5e8), cand("MID", 5e9), cand("BIG", 5e11)]
    got = select.ranked_eligible(cands, [], TODAY)
    assert [c.ticker for c in got] == ["BIG", "MID"]   # SMALL under $1B

def test_ranked_eligible_is_uncapped():
    # the tick walks this list; capping it here would reintroduce starvation
    cands = [cand(f"T{i}", 2e9 + i) for i in range(50)]
    assert len(select.ranked_eligible(cands, [], TODAY)) == 50

def test_ranked_eligible_respects_cooldown():
    cands = [cand("A", 3e9), cand("B", 2e9)]
    posted = [posted_entry("A", date(2026, 6, 30))]  # posted Tuesday -> blocked Wed
    assert [c.ticker for c in select.ranked_eligible(cands, posted, TODAY)] == ["B"]

def test_slot_count_bounded_by_both_caps():
    assert select.slot_count([], TODAY) == config.MAX_PER_TICK
    almost = [posted_entry(f"T{i}") for i in range(config.MAX_PER_DAY - 1)]
    assert select.slot_count(almost, TODAY) == 1
    full = [posted_entry(f"T{i}") for i in range(config.MAX_PER_DAY)]
    assert select.slot_count(full, TODAY) == 0
    over = [posted_entry(f"T{i}") for i in range(config.MAX_PER_DAY + 5)]
    assert select.slot_count(over, TODAY) == 0        # never negative
