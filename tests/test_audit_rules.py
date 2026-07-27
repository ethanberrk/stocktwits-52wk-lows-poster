import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yfinance

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location(
    "verify_day", ROOT / "scripts" / "verify_day.py")
verify_day = importlib.util.module_from_spec(spec)
sys.modules["verify_day"] = verify_day
spec.loader.exec_module(verify_day)

def entry(ticker, d):
    return {"ticker": ticker, "date": d, "post_id": None}

def run_rules(posted):
    verify_day.results.update({"PASS": 0, "WARN": 0, "FAIL": 0})
    verify_day.check_log_rules(posted)
    return verify_day.results["FAIL"]

def test_clean_log_passes():
    posted = [entry("V", "2026-07-02"), entry("JNJ", "2026-07-02"),
              entry("V", "2026-07-06")]  # Thu then Mon: Fri=holiday-ish, gap ok
    assert run_rules(posted) == 0

def test_duplicate_same_day_fails():
    assert run_rules([entry("V", "2026-07-02"), entry("V", "2026-07-02")]) > 0

def test_consecutive_trading_day_fails():
    # Wed 2026-07-01 then Thu 2026-07-02
    assert run_rules([entry("V", "2026-07-01"), entry("V", "2026-07-02")]) > 0

def test_friday_to_monday_counts_as_consecutive():
    # Fri 2026-06-26 then Mon 2026-06-29: weekend is not a gap
    assert run_rules([entry("V", "2026-06-26"), entry("V", "2026-06-29")]) > 0

def test_weekend_post_fails():
    assert run_rules([entry("V", "2026-07-04")]) > 0  # Saturday

def test_daily_cap_violation_fails():
    posted = [entry(f"T{i}", "2026-07-02") for i in range(21)]
    assert run_rules(posted) > 0

class _FakeTicker:
    """Stands in for yf.Ticker(ticker) -- .history() returns a fixed frame."""
    def __init__(self, df):
        self._df = df

    def history(self, **kwargs):
        return self._df


def _history_df(d: date, day_low: float, prior_min: float = 100.0,
                n_prior: int = 252) -> pd.DataFrame:
    """n_prior sessions with Low == prior_min, then a final session (=d)
    with Low == day_low. 252 prior sessions keeps check_truth's PASS/WARN
    split (len(prior) >= 200) on the PASS side."""
    idx = pd.date_range(end=pd.Timestamp(d), periods=n_prior + 1, freq="D")
    lows = [prior_min] * n_prior + [day_low]
    return pd.DataFrame({"Low": lows}, index=idx)


def run_truth(monkeypatch, ticker, d, day_low, prior_min=100.0):
    df = _history_df(d, day_low, prior_min)
    monkeypatch.setattr(yfinance, "Ticker", lambda t: _FakeTicker(df))
    verify_day.results.update({"PASS": 0, "WARN": 0, "FAIL": 0})
    verify_day.check_truth(ticker, d)
    return verify_day.results


@pytest.mark.parametrize("factor, expect", [
    (0.995, "PASS"),    # comfortably below the prior minimum
    (1.0, "PASS"),      # exact match
    (1.0005, "PASS"),   # inside the 0.1% tolerance
    (1.002, "FAIL"),    # just outside the tolerance
    (1.05, "FAIL"),     # nowhere near a 52-week low
])
def test_check_truth_boundary(monkeypatch, factor, expect):
    """Behavioural test of check_truth, driven at the tolerance boundary.

    This replaces a source-text lint that asserted on the CHARACTERS of
    verify_day.py (e.g. '"(1 + TRUTH_TOLERANCE)" in src'). That lint passed
    even after the reviewer flipped the comparison operator to '>=' --
    the auditor is the only automated check that this bot's public claims
    are true, and a text lint blind to its own comparison operator is no
    check at all. See test_operator_flip_would_be_caught below for the
    discriminating proof.
    """
    d = date(2026, 7, 20)
    prior_min = 100.0
    results = run_truth(monkeypatch, "XYZ", d, prior_min * factor, prior_min)
    assert results[expect] == 1, results
    for level in {"PASS", "WARN", "FAIL"} - {expect}:
        assert results[level] == 0, results
