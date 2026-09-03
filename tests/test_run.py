from datetime import datetime, timezone, date
import os
import pytest
import config
import run
from src.chart import ChartError
from src.source.base import Candidate, LowsSource
from src.publish.base import Publisher, PostResult
from src.publish.dryrun import DryRunPublisher
from src.publish.stocktwits_pub import StocktwitsPublisher, PublishError
from src import state

NOW = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)  # Wed 10:00 ET, market open
TODAY = date(2026, 7, 1)

def cand(ticker, mcap=5e9):
    return Candidate(ticker, f"{ticker} Inc", "NYSE", 100.0, 2.0, mcap, 99.0, "EQUITY")

class FakeSource(LowsSource):
    def __init__(self, cands): self.cands = cands
    def fetch_candidates(self): return self.cands

class SpyPublisher(Publisher):
    def __init__(self): self.calls = []
    def post(self, candidate, text, image_png):
        self.calls.append((candidate.ticker, text, image_png))
        return PostResult(post_id=None, dry_run=True)

def test_tick_posts_top_candidates_and_records_state(tmp_path):
    sp = tmp_path / "posted.json"
    pub = SpyPublisher()
    got = run.tick(FakeSource([cand("BIG", 9e9), cand("MID", 5e9), cand("SM", 2e9)]),
                   pub, lambda c: b"PNG", sp, NOW)
    assert got == ["BIG", "MID"]                      # 2-per-tick cap, mcap order
    assert pub.calls[0][0] == "BIG"
    assert pub.calls[0][1].startswith("$BIG ")
    posted = state.load_posted(sp)
    assert [e["ticker"] for e in posted] == ["BIG", "MID"]
    assert all(e["status"] == "posted" for e in posted)   # confirmed after posting

def test_symbol_check_failure_skips_candidate(tmp_path):
    pub = SpyPublisher()
    got = run.tick(FakeSource([cand("BIG", 9e9), cand("MID", 5e9)]),
                   pub, lambda c: b"PNG", tmp_path / "p.json", NOW,
                   symbol_check=lambda c: c.ticker != "BIG")
    assert got == ["MID"]                 # BIG skipped before chart/publish
    assert [e["ticker"] for e in state.load_posted(tmp_path / "p.json")] == ["MID"]

def test_publisher_crash_leaves_pending_writeahead(tmp_path):
    # crash after intents are recorded: nothing double-posts next tick
    sp = tmp_path / "posted.json"
    class ExplodingPublisher(Publisher):
        def post(self, candidate, text, image_png):
            raise RuntimeError("stocktwits 500")
    with pytest.raises(RuntimeError):
        run.tick(FakeSource([cand("BIG", 9e9), cand("MID", 5e9)]),
                 ExplodingPublisher(), lambda c: b"PNG", sp, NOW)
    posted = state.load_posted(sp)
    assert [(e["ticker"], e["status"]) for e in posted] == [
        ("BIG", "pending"), ("MID", "pending")]
    # both are blocked from a repost attempt on the very next tick
    assert state.is_blocked("BIG", posted, TODAY)
    assert state.is_blocked("MID", posted, TODAY)

def test_state_sync_runs_after_writeahead_before_posting(tmp_path):
    events = []
    class OrderedPublisher(Publisher):
        def post(self, candidate, text, image_png):
            events.append(f"post:{candidate.ticker}")
            return PostResult(post_id=None, dry_run=True)
    def sync():
        posted = state.load_posted(tmp_path / "p.json")
        events.append(f"sync:{[e['status'] for e in posted]}")
    run.tick(FakeSource([cand("BIG", 9e9)]), OrderedPublisher(),
             lambda c: b"PNG", tmp_path / "p.json", NOW, state_sync=sync)
    assert events == ["sync:['pending']", "post:BIG"]   # intent pushed first

def test_tick_outside_market_hours_is_noop(tmp_path):
    closed = datetime(2026, 7, 1, 22, 0, tzinfo=timezone.utc)  # 18:00 ET
    pub = SpyPublisher()
    got = run.tick(FakeSource([cand("BIG")]), pub, lambda c: b"PNG",
                   tmp_path / "p.json", closed)
    assert got == [] and pub.calls == []

def test_tick_force_overrides_hours(tmp_path):
    closed = datetime(2026, 7, 1, 22, 0, tzinfo=timezone.utc)
    got = run.tick(FakeSource([cand("BIG")]), SpyPublisher(), lambda c: b"PNG",
                   tmp_path / "p.json", closed, force=True)
    assert got == ["BIG"]

def test_chart_failure_skips_ticker_and_continues(tmp_path):
    def flaky(c):
        if c.ticker == "BIG":
            raise ChartError("boom")
        return b"PNG"
    pub = SpyPublisher()
    got = run.tick(FakeSource([cand("BIG", 9e9), cand("MID", 5e9)]),
                   pub, flaky, tmp_path / "p.json", NOW)
    assert got == ["MID"]                    # BIG skipped, stays unposted/eligible
    posted = state.load_posted(tmp_path / "p.json")
    assert [e["ticker"] for e in posted] == ["MID"]

def test_second_tick_same_day_respects_cooldown(tmp_path):
    sp = tmp_path / "posted.json"
    src = FakeSource([cand("BIG", 9e9), cand("MID", 5e9), cand("SM", 2e9)])
    run.tick(src, SpyPublisher(), lambda c: b"PNG", sp, NOW)
    got2 = run.tick(src, SpyPublisher(), lambda c: b"PNG", sp, NOW)
    assert got2 == ["SM"]                    # BIG/MID posted today -> blocked

def test_build_publisher_dryrun_by_default(tmp_path):
    pub = run.build_publisher(False, tmp_path, TODAY)
    assert isinstance(pub, DryRunPublisher)

def test_build_publisher_live_needs_token(tmp_path, monkeypatch):
    monkeypatch.delenv("STOCKTWITS_ACCESS_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        run.build_publisher(True, tmp_path, TODAY)

def test_build_publisher_live_with_token(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKTWITS_ACCESS_TOKEN", "TKN")
    pub = run.build_publisher(True, tmp_path, TODAY)
    assert isinstance(pub, StocktwitsPublisher)

def test_publish_error_skips_ticker_and_continues(tmp_path):
    sp = tmp_path / "posted.json"
    class Flaky(Publisher):
        def post(self, candidate, text, image_png):
            if candidate.ticker == "BIG":
                raise PublishError("cloudflare 403")
            return PostResult(post_id="x", dry_run=False)
    got = run.tick(FakeSource([cand("BIG", 9e9), cand("MID", 5e9)]),
                   Flaky(), lambda c: b"PNG", sp, NOW)
    assert got == ["MID"]
    status = {e["ticker"]: e["status"] for e in state.load_posted(sp)}
    assert status == {"BIG": "pending", "MID": "posted"}

def test_tick_walks_past_an_unchartable_top_pick(tmp_path):
    """The regression test for tick starvation.

    SPCX/SKHY on 2026-07-27: the two largest names at new lows were both
    recent listings that trip MIN_HISTORY_DAYS. Picking the top N up front
    would have posted nothing that day, every tick, all day.
    """
    sp = tmp_path / "posted.json"
    pub = SpyPublisher()

    def chart(c):
        if c.ticker in ("SPCX", "SKHY"):
            raise ChartError(f"{c.ticker}: recent IPO, 1Y chart would mislead")
        return b"PNG"

    got = run.tick(FakeSource([cand("SPCX", 1.5e12), cand("SKHY", 1.0e12),
                               cand("CCI", 3.2e10), cand("PSKY", 8.9e9)]),
                   pub, chart, sp, NOW)
    assert got == ["CCI", "PSKY"]           # 2-per-tick cap, walked past both
    assert [e["ticker"] for e in state.load_posted(sp)] == ["CCI", "PSKY"]

def test_skipped_name_is_not_recorded_and_stays_eligible(tmp_path):
    sp = tmp_path / "posted.json"
    def chart(c):
        if c.ticker == "SPCX":
            raise ChartError("recent IPO")
        return b"PNG"
    run.tick(FakeSource([cand("SPCX", 1.5e12), cand("CCI", 3.2e10)]),
             SpyPublisher(), chart, sp, NOW)
    # no state entry for SPCX at all -> nothing blocks it on a later tick
    assert "SPCX" not in [e["ticker"] for e in state.load_posted(sp)]

class _FakeCompleted:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout

def test_git_sync_state_skips_push_on_feature_branch_ref(monkeypatch):
    # GITHUB_REF is what a real Actions dispatch on a feature branch sets --
    # must never touch git at all, let alone push to main.
    calls = []
    monkeypatch.setattr(run.subprocess, "run",
                        lambda *a, **k: (calls.append(a[0]), _FakeCompleted())[1])
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feat/lows-poster")
    run._git_sync_state()
    assert calls == []

def test_git_sync_state_falls_back_to_local_branch_when_ref_unset(monkeypatch):
    # Local runs have no GITHUB_REF; fall back to the checked-out branch.
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _FakeCompleted(stdout="some-feature-branch\n")
    monkeypatch.setattr(run.subprocess, "run", fake_run)
    monkeypatch.delenv("GITHUB_REF", raising=False)
    run._git_sync_state()
    assert calls == [["git", "rev-parse", "--abbrev-ref", "HEAD"]]

def test_git_sync_state_proceeds_when_ref_is_main(monkeypatch):
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[-1] == "--quiet":
            return _FakeCompleted(returncode=1)   # pretend something is staged
        return _FakeCompleted()
    monkeypatch.setattr(run.subprocess, "run", fake_run)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    run._git_sync_state()
    push_calls = [c for c in calls if "push" in c]
    assert push_calls == [["git", "push", "origin", "HEAD:main"]]

def test_tick_stops_after_max_candidate_attempts(tmp_path, monkeypatch):
    """Bound the walk: a degraded chart source must not run the tick past
    the workflow timeout, which would silently queue and drop later ticks."""
    monkeypatch.setattr(config, "MAX_CANDIDATE_ATTEMPTS", 3)
    calls = []
    def chart(c):
        calls.append(c.ticker)
        raise ChartError("stockanalysis is down")
    got = run.tick(FakeSource([cand(f"T{i}", 9e9 - i) for i in range(50)]),
                   SpyPublisher(), chart, tmp_path / "p.json", NOW)
    assert got == []
    assert len(calls) == 3


# --- data-source switch + shadow dump ----------------------------------------

def test_build_source_follows_switch(monkeypatch):
    import config
    from src.source.xignite_source import XigniteSource
    from src.source.yfinance_source import YFinanceSource
    monkeypatch.setattr(config, "DATA_SOURCE", "legacy")
    assert isinstance(run.build_source(), YFinanceSource)
    monkeypatch.setattr(config, "DATA_SOURCE", "xignite")
    assert isinstance(run.build_source(), XigniteSource)
    assert isinstance(run.build_source("legacy"), YFinanceSource)


def test_build_source_unknown_is_hard_error(monkeypatch):
    with pytest.raises(SystemExit):
        run.build_source("yahoo-please")


def test_tick_dumps_candidates_for_shadow(tmp_path):
    import json
    dump = tmp_path / "shadow" / "2026-07-01" / "1400.active.json"
    run.tick(FakeSource([cand("BIG", 9e9), cand("SM", 2e9)]), SpyPublisher(),
             lambda c: b"PNG", tmp_path / "p.json", NOW, dump_to=dump)
    d = json.loads(dump.read_text())
    assert [c["ticker"] for c in d["candidates"]] == ["BIG", "SM"]
    assert d["candidates"][0]["market_cap"] == 9e9
    assert d["time"].startswith("2026-07-01T14:00")
