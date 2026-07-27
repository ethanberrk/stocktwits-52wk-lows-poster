import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location(
    "verify_day", Path(__file__).parent.parent / "scripts" / "verify_day.py")
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

def test_truth_check_uses_the_low_side_and_a_permissive_tolerance():
    """The tolerance MUST invert with the comparison.

    Highs pass when day_high >= prior_max * (1 - TOL) — a permissive band
    below the max. Lows pass when day_low <= prior_min * (1 + TOL) — a
    permissive band above the min. Keeping (1 - TOL) on the low side turns
    a permissive tolerance into a stricter one and FAILs every real post.
    """
    src = (ROOT / "scripts" / "verify_day.py").read_text()
    assert 'df["Low"]' in src and 'df["High"]' not in src
    assert "prior.min()" in src and "prior.max()" not in src
    assert "(1 + TRUTH_TOLERANCE)" in src
    assert "(1 - TRUTH_TOLERANCE)" not in src
    assert "52-week low" in src and "52-week high" not in src
