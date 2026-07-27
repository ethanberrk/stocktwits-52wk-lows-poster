# Stocktwits 52-Week-Lows Poster — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone Stocktwits bot that posts the largest US common stocks printing new 52-week lows, every 30 minutes during market hours, each with a self-rendered 1-year candlestick chart.

**Architecture:** A verbatim clone of the live `stocktwits-52wk-poster` engine, then inverted. One tick per invocation, stages behind interfaces: `LowsSource` (yfinance screen) → `select` (filters, cooldown, caps, market-cap ranking) → `chart` (matplotlib, keyless stockanalysis.com data) → `Publisher` (dry-run writer in Phase 1, Stocktwits in Phase 2). State is a single committed JSON posted-log.

**Tech Stack:** Python 3.12, `yfinance>=0.2.50`, `matplotlib>=3.8`, `pytest>=8.0`, GitHub Actions, cron-job.org. No paid APIs, no `requests`.

**Spec:** `docs/superpowers/specs/2026-07-27-stocktwits-52wk-lows-poster-design.md`

## Global Constraints

- **Repo:** `ethanberrk/stocktwits-52wk-lows-poster` (private), local `/Users/ethanberk/stocktwits-52wk-lows-poster`. Nothing is shared with the highs or weakness posters.
- **Post copy is locked, exactly:** `$TICKER printed a new 52-week low today` — no price, percent, market cap or company name.
- **`urllib`, never `requests`.** Stocktwits' CDN 403s the `requests` TLS fingerprint regardless of headers. Applies to the symbol check, chart data fetch and publisher.
- **Dry-run is the default.** `--live` without `STOCKTWITS_ACCESS_TOKEN` must be a hard `SystemExit(1)`, never a silent downgrade. No posting token exists in the repo until Task 10.
- **Run tests with `.venv/bin/python -m pytest`.** The global python has yfinance 0.2.38, which lacks `yf.screen`.
- **Contract tests hit the network** and are deselected by default (`-m "not contract"`). Never make a unit test hit the network.
- **Every task ends with a commit.** Conventional-commit prefixes (`feat:`, `fix:`, `test:`, `chore:`).
- **Constants live in `config.py` only.** No thresholds inline in `src/`.
- **Values fixed by the spec:** `MIN_MARKET_CAP = 1_000_000_000`, `MAX_PLAUSIBLE_LOWS = 1200`, `MIN_DOLLAR_VOLUME = 5_000_000`, `MAX_CANDIDATE_ATTEMPTS = 20`, `MIN_HISTORY_DAYS = 330`, `MAX_PER_TICK = 2` / `MAX_PER_DAY = 20` as repo defaults with `1` / `12` set as workflow env.

### Spec amendment recorded here

The spec names the walk-down bound `MAX_CHART_ATTEMPTS`. This plan implements it as **`MAX_CANDIDATE_ATTEMPTS`**, counting every candidate *examined* rather than every chart *fetched*. Reason: a symbol check costs up to 15s (`src/stocktwits.py:27`) and runs before the chart fetch, so a bound that only counts chart attempts leaves symbol checks unbounded — hundreds of candidates each failing their symbol check would still run the tick past its timeout. Same number (20), strictly stronger bound.

---

## File Structure

Everything is inherited from the highs poster at Task 1. Later tasks only modify.

| File | Responsibility | Touched by |
|---|---|---|
| `config.py` | Every threshold and URL | 3, 4, 5, 6 |
| `src/source/base.py` | `Candidate` dataclass, `LowsSource` ABC, `SourceError` | 2 |
| `src/source/yfinance_source.py` | Screen query + row → `Candidate` (all filtering) | 2, 3, 4 |
| `src/select.py` | Validation gate, ranking, eligibility, slot arithmetic | 5, 6 |
| `src/state.py` | Posted-log I/O, cooldown, market hours | — |
| `src/chart.py` | History fetch + matplotlib render | 7 |
| `src/stocktwits.py` | Cashtag symbology + pre-post validation | — |
| `src/fetch.py` | `get_json` over urllib | — |
| `src/publish/base.py` | `Publisher` ABC, `compose_post_text` | 5 |
| `src/publish/dryrun.py`, `record.py`, `stocktwits_pub.py` | Publishing | 9 |
| `run.py` | One tick: source → select → walk-down → publish | 2, 6 |
| `scripts/verify_day.py` | Independent nightly auditor | 8 |
| `.github/workflows/tick.yml` | 30-min tick | 6, 9 |
| `.github/workflows/audit.yml`, `ci.yml` | Nightly audit, CI | 9 |
| `README.md` | What this repo is | 9 |

---

## Task 1: Baseline clone

Seed the new repo with the highs poster's engine, unmodified, and prove the inherited suite is green before changing anything. The commit boundary matters: every later diff is then readable as "what makes this the lows poster."

**Files:**
- Create: everything under `/Users/ethanberk/stocktwits-52wk-lows-poster` except `docs/` (already present)

**Interfaces:**
- Consumes: nothing
- Produces: the full highs engine — `config`, `src.source.base.Candidate` / `HighsSource` / `SourceError`, `src.source.yfinance_source.YFinanceSource` / `_row_to_candidate`, `src.select.validate` / `pick` / `ValidationError`, `src.state.*`, `src.chart.fetch_chart_png` / `ChartError` / `_fetch_history` / `_render_png`, `src.stocktwits.st_symbol` / `symbol_exists`, `src.fetch.get_json`, `src.publish.base.Publisher` / `PostResult` / `compose_post_text`, `run.tick` / `main` / `build_publisher`

- [ ] **Step 1: Copy the engine from the highs repo's `origin/main`**

The local highs checkout is 239 commits behind and its README describes a retired chart service. Copy from `origin/main`, not the working tree.

```bash
cd /Users/ethanberk/stocktwits-52wk-poster
git fetch origin
cd /Users/ethanberk/stocktwits-52wk-lows-poster
git archive --remote=/Users/ethanberk/stocktwits-52wk-poster origin/main \
  config.py run.py pyproject.toml requirements.txt requirements-dev.txt \
  README.md .gitignore src scripts tests .github | tar -x
ls src tests .github/workflows
```

Expected: `src/` has `chart.py fetch.py select.py state.py stocktwits.py publish source`; `tests/` has 11 `test_*.py` plus `contract/`; `.github/workflows/` has `audit.yml ci.yml tick.yml`.

- [ ] **Step 2: Create empty state and output directories**

No live posting history comes across — this account has never posted.

```bash
mkdir -p state output
printf '{\n  "posts": []\n}\n' > state/posted.json
touch output/.gitkeep
cat state/posted.json
```

Expected: `{"posts": []}` pretty-printed.

- [ ] **Step 3: Create the virtualenv and install**

```bash
python3 -m venv .venv
.venv/bin/pip install -q -r requirements-dev.txt
.venv/bin/python -c "import yfinance; print(yfinance.__version__); print(hasattr(yfinance,'screen'))"
```

Expected: version `0.2.50` or higher, and `True`.

- [ ] **Step 4: Run the inherited suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS, 83 passed, 3 deselected. If anything fails here, stop — the baseline is wrong and every later task inherits the breakage.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "baseline: verbatim clone of stocktwits-52wk-poster engine

Unmodified copy of the highs poster at origin/main, with state and output
emptied. Every subsequent diff is the highs->lows inversion."
```

---

## Task 2: Invert the source to 52-week lows

The core flip. `Candidate` carries a low instead of a high, the ABC is renamed, and the day-cumulative test inverts.

**Files:**
- Modify: `src/source/base.py`
- Modify: `src/source/yfinance_source.py:11-48`
- Modify: `run.py:17`, `run.py:20`
- Test: `tests/test_source_parse.py` (rewrite fixtures), `tests/test_chart.py:9-12`, `tests/test_select.py:8-10`, `tests/test_run.py:6,17,26`

**Interfaces:**
- Consumes: `Candidate`, `HighsSource`, `_row_to_candidate` (Task 1)
- Produces:
  - `src.source.base.Candidate` — frozen dataclass, field `week52_high: float` renamed to `week52_low: float`; field order unchanged (`ticker, name, exchange, price, pct_change_today, market_cap, week52_low, security_type`), so positional construction in tests still works
  - `src.source.base.LowsSource` — ABC with `fetch_candidates(self) -> list[Candidate]`, replaces `HighsSource`
  - `src.source.yfinance_source._row_to_candidate(row: dict, today: date) -> Candidate | None` — signature unchanged

- [ ] **Step 1: Write the failing tests**

Replace the whole of `tests/test_source_parse.py`. Every fixture value flips to the low side: AAPL at $250 with a day low of $248 that equals its 52-week low.

```python
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
        "regularMarketTime": TS_TODAY,
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_source_parse.py -q
```

Expected: FAIL — `KeyError: 'regularMarketDayHigh'` or `TypeError` on the `Candidate` comparison.

- [ ] **Step 3: Invert `src/source/base.py`**

Replace the file:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class Candidate:
    ticker: str
    name: str
    exchange: str            # TradingView-style: "NASDAQ" | "NYSE" | "AMEX" | ""
    price: float
    pct_change_today: float
    market_cap: float
    week52_low: float
    security_type: str       # Yahoo quoteType, e.g. "EQUITY"

class SourceError(Exception):
    """The source itself looks broken (not merely 'no lows right now')."""

class LowsSource(ABC):
    @abstractmethod
    def fetch_candidates(self) -> list[Candidate]:
        """All US equities on today's 52-week-low list (day-cumulative)."""
```

- [ ] **Step 4: Invert the row parser**

In `src/source/yfinance_source.py`, replace `_REQUIRED` (line 11-12) and the two high-side blocks:

```python
_REQUIRED = ("symbol", "regularMarketPrice", "regularMarketDayLow",
             "fiftyTwoWeekLow", "marketCap", "regularMarketTime")
```

Replace the day-cumulative test (lines 35-38) with:

```python
    # Day-cumulative 52wk-low test: today's low touched the 52wk low.
    # Yahoo's fiftyTwoWeekLow already includes today, so equality == new low.
    if row["regularMarketDayLow"] - 1e-6 > row["fiftyTwoWeekLow"]:
        return None
```

Replace the `Candidate` construction field (line 46) with:

```python
        week52_low=float(row["fiftyTwoWeekLow"]),
```

Update the class docstring (line 54) to `"""Screen US equities >$1B by mcap desc, keep rows on today's 52wk-low list."""` and change the import on line 5 and the base class on line 53 from `HighsSource` to `LowsSource`.

- [ ] **Step 5: Update the remaining `HighsSource` and `week52_high` references**

`run.py` line 17: `from src.source.base import LowsSource, SourceError`
`run.py` line 20: `def tick(source: LowsSource, publisher: Publisher, chart_fetch,`
`run.py` line 32: `print(f"{len(candidates)} on today's 52wk-low list; posting {len(picks)}")`

`tests/test_run.py` line 6: `from src.source.base import Candidate, LowsSource`
`tests/test_run.py` line 17: `class FakeSource(LowsSource):`
`tests/test_run.py` line 14 (`cand` helper): the 7th positional argument stays `101.0` but now means `week52_low`; change it to `99.0` so the fixture reads as a low below the $100 price.

`tests/test_select.py` lines 8-10 (`cand` helper): same — change `101.0` to `99.0`.

`tests/test_chart.py` line 11: `week52_high=1.0` becomes `week52_low=1.0`.

- [ ] **Step 6: Run the full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS. `tests/test_yfinance_source.py` and `tests/test_publish.py` may still fail on high-side fixtures — if so, apply the same field renames there (`regularMarketDayHigh` → `regularMarketDayLow`, `fiftyTwoWeekHigh` → `fiftyTwoWeekLow`, `day_high`/`wk_high` local names → `day_low`/`wk_low`) and re-run. `test_publish` copy assertions are Task 5's job; if only those fail, that is expected — note it and move on.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: invert the source to 52-week lows

Candidate.week52_high -> week52_low, HighsSource -> LowsSource, and the
day-cumulative test flips: today's low touching the 52-week low is the signal.
Yahoo's fiftyTwoWeekLow includes today, so equality is a new low."
```

---

## Task 3: Filter out instruments that are not stocks

A straight mirror posts preferred shares and warrants, because Yahoo gives them the **parent common's `longName`** — so `NAME_EXCLUDE_RE` never fires — and the **parent's market cap**, so they rank near the top of a size-ranked feed. It also posts lines that trade a hundred shares a day and sit parked at their low forever.

Measured live on 2026-07-27 against the 2,768-row equity universe:

- `PREFERRED_RE` catches **106** rows — `JPM-PC`, `BAC-PB`, `WFC-PC` ($113.7B), `ALL-PH` ($29.1B, on that day's new-lows list), `KEY-PK`, `PCG-PA`, all genuine preferred series. Zero false positives.
- `WARRANT_RE` catches exactly **1** — `DJTWW`, a Trump Media warrant that charts cleanly and whose Stocktwits symbol resolves 200, so nothing downstream would stop it.
- **18 legitimate dual-class lines survive**: `AGM-A, AKO-A, AKO-B, BF-A, BF-B, BH-A, BRK-A, BRK-B, CIG-C, GEF-B, HEI-A, LEN-B, MKC-V, MOG-A, MOG-B, PBR-A, TAP-A, UHAL-B`.
- `TAP-A` traded **116 shares** that day with `dayHigh == dayLow == previousClose == fiftyTwoWeekLow == 39.51` and a today-stamped quote — it qualifies every day it prints one flat trade, and the 2-day cooldown returns it every other day indefinitely. The $5M dollar-volume floor removes it.

**Files:**
- Modify: `config.py`
- Modify: `src/source/yfinance_source.py:11-14`, `:14-38`
- Test: `tests/test_source_parse.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `_row_to_candidate` (Task 2)
- Produces: `config.PREFERRED_RE: re.Pattern`, `config.WARRANT_RE: re.Pattern`, `config.MIN_DOLLAR_VOLUME: float`. `_REQUIRED` gains `"regularMarketVolume"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_source_parse.py`. Note every `row()` now needs a volume big enough to clear the floor, so also add `"regularMarketVolume": 1_000_000` to the `base` dict in the `row()` helper (at $250 that is $250M, well clear).

```python
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
```

And append to `tests/test_config.py`:

```python
def test_instrument_hygiene_constants():
    assert config.MIN_DOLLAR_VOLUME == 5_000_000
    assert config.PREFERRED_RE.search("WFC-PC")
    assert not config.PREFERRED_RE.search("BRK-B")
    assert config.WARRANT_RE.match("DJTWW")
    assert not config.WARRANT_RE.match("GOOGL")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_source_parse.py tests/test_config.py -q
```

Expected: FAIL — `AttributeError: module 'config' has no attribute 'PREFERRED_RE'`.

- [ ] **Step 3: Add the constants**

Append to `config.py`, below `NAME_EXCLUDE_RE`:

```python
# Instrument hygiene. Yahoo hands preferred shares and warrants the PARENT
# common's longName (so NAME_EXCLUDE_RE never fires) and the parent's market
# cap (so they rank at the top of a size-ranked feed). Invisible on the high
# side; pervasive on the low side, where these lines sit near their lows
# structurally and barely trade. Verified live 2026-07-27: PREFERRED_RE caught
# 106 rows with zero false positives, WARRANT_RE caught exactly DJTWW, and all
# 18 legitimate dual-class lines (BRK-B, PBR-A, HEI-A, MOG-A, ...) survived.
PREFERRED_RE = re.compile(r"-P[A-Z]?$")          # WFC-PC, ALL-PH, KEY-PK
WARRANT_RE = re.compile(r"^[A-Z]{4}(W|R|U)$")    # DJTWW; also rights, units

# A line parked at its 52-week low on a hundred shares a day re-qualifies
# every session and the 2-day cooldown returns it indefinitely (TAP-A,
# 116 shares, 2026-07-27). Dollar volume, so it scales across price levels.
MIN_DOLLAR_VOLUME = 5_000_000
```

- [ ] **Step 4: Apply the filters in the row parser**

In `src/source/yfinance_source.py`, add `"regularMarketVolume"` to `_REQUIRED`:

```python
_REQUIRED = ("symbol", "regularMarketPrice", "regularMarketDayLow",
             "fiftyTwoWeekLow", "marketCap", "regularMarketTime",
             "regularMarketVolume")
```

Then inside `_row_to_candidate`, immediately after the `quoteType` check and before the name check, add:

```python
    # Preferreds and warrants inherit the parent's name AND market cap, so
    # neither NAME_EXCLUDE_RE nor the mcap floor stops them. Symbol shape does.
    symbol = row["symbol"]
    if config.PREFERRED_RE.search(symbol) or config.WARRANT_RE.match(symbol):
        return None
```

And after the exchange check, before the freshness gate, add:

```python
    # Liquidity floor: a flat print on a hundred shares is not a new low
    # anyone traded. Dollar volume, not share count.
    if (float(row["regularMarketPrice"]) * float(row["regularMarketVolume"])
            < config.MIN_DOLLAR_VOLUME):
        return None
```

- [ ] **Step 5: Run the full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS (except any `test_publish` copy assertions, which Task 5 fixes). If `tests/test_yfinance_source.py` fails on a missing `regularMarketVolume`, add it to that file's row fixture with a value of `1_000_000`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: drop preferreds, warrants and ghost-volume lines

Yahoo gives preferreds and warrants the parent common's longName and market
cap, so NAME_EXCLUDE_RE and the mcap floor both miss them and they rank at the
top of a size-ranked lows feed. Filter on symbol shape instead, and add a \$5M
dollar-volume floor so a line parked at its low on 116 shares stops
re-qualifying every session."
```

---

## Task 4: Make the $1B floor real

The inherited query has no exchange filter and pages to `_MAX_OFFSET = 3000`. Measured live 2026-07-27: it returns exactly 3,000 rows — the cap is hit — of which **1,739 are pink sheets** thrown away by the exchange check, leaving 1,261 usable names, and the 3,000th row sits at **$6.59B**. The effective floor is ~$6.6B, not the $1B the config claims.

The highs poster survives this because ~130 names hit new highs on an ordinary day and it needs 12. Only 7 hit new lows the same day. Adding `exchange` to the query itself returns **2,766 rows down to a true $1.001B floor** with no truncation. This removes nothing postable — pink sheets are discarded either way.

**Files:**
- Modify: `src/source/yfinance_source.py:56-70`
- Test: `tests/test_yfinance_source.py`, `tests/contract/test_live_yfinance.py`

**Interfaces:**
- Consumes: `YFinanceSource._screen_rows` (Task 1)
- Produces: `config.SCREEN_EXCHANGES: tuple[str, ...]`. `_screen_rows` behaviour unchanged in shape — still `list[dict]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_yfinance_source.py`. The query object is inspected rather than executed, so this stays offline.

```python
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
```

Add `import config` and `from src.source import yfinance_source` at the top of that file if not already present.

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_yfinance_source.py -q
```

Expected: FAIL — `AttributeError: module 'config' has no attribute 'SCREEN_EXCHANGES'`.

- [ ] **Step 3: Add the constant**

Append to `config.py`:

```python
# Ask Yahoo for listed exchanges only. Without this the screen's 3000-row page
# cap is consumed by ~1,700 pink-sheet rows the exchange check discards later,
# truncating the real market-cap floor to ~$6.6B (measured 2026-07-27). With
# it: 2,766 rows down to a true $1.001B floor, no truncation.
SCREEN_EXCHANGES = ("NMS", "NYQ", "NGM", "NCM", "ASE")
```

- [ ] **Step 4: Add the filter to the query**

In `src/source/yfinance_source.py`, replace the query construction in `_screen_rows`:

```python
        q = yf.EquityQuery("and", [
            yf.EquityQuery("eq", ["region", "us"]),
            yf.EquityQuery("gt", ["intradaymarketcap", config.MIN_MARKET_CAP]),
            yf.EquityQuery("is-in", ["exchange", *config.SCREEN_EXCHANGES]),
        ])
```

- [ ] **Step 5: Run the tests**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS (except any `test_publish` copy assertions).

- [ ] **Step 6: Add the live contract test**

Append to `tests/contract/test_live_yfinance.py`, following that file's existing `@pytest.mark.contract` convention:

```python
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
```

- [ ] **Step 7: Run the contract test**

```bash
.venv/bin/python -m pytest tests/contract/test_live_yfinance.py -q -m contract
```

Expected: PASS. Verified manually 2026-07-27: 2,766 rows, min cap $1.001B, 13 of 3,000 rows lacked the low fields (the same 13 that lack the high fields).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "fix: filter the screen by exchange so the \$1B floor is real

The 3000-row page cap was being consumed by ~1,700 pink sheets discarded
later, truncating the effective floor to ~\$6.6B. Asking Yahoo for listed
exchanges up front returns 2,766 rows to a true \$1.001B floor. The highs
poster tolerates this because ~130 names hit new highs a day; only 7 hit
new lows."
```

---

## Task 5: Post copy and the plausibility gate

**Files:**
- Modify: `src/publish/base.py:16-20`
- Modify: `config.py:8`
- Modify: `src/select.py:10-14`
- Test: `tests/test_publish.py`, `tests/test_config.py`, `tests/test_select.py`

**Interfaces:**
- Consumes: `compose_post_text`, `select.validate`, `st_symbol` (Task 1)
- Produces: `config.MAX_PLAUSIBLE_LOWS: int` (replaces `MAX_PLAUSIBLE_HIGHS`); `compose_post_text(c: Candidate) -> str` returning the locked lows copy

- [ ] **Step 1: Write the failing tests**

In `tests/test_publish.py`, replace the copy assertions:

```python
def test_copy_is_the_locked_lows_line():
    c = Candidate("RIVN", "Rivian Automotive, Inc.", "NASDAQ", 9.12, -4.1,
                  1.1e10, 9.05, "EQUITY")
    assert compose_post_text(c) == "$RIVN printed a new 52-week low today"

def test_copy_has_no_stale_numbers():
    c = Candidate("RIVN", "Rivian Automotive, Inc.", "NASDAQ", 9.12, -4.1,
                  1.1e10, 9.05, "EQUITY")
    text = compose_post_text(c)
    for stale in ("9.12", "4.1", "1.1", "Rivian"):
        assert stale not in text, f"{stale!r} goes stale between tick and reader"

def test_copy_uses_stocktwits_cashtag_symbology():
    # Yahoo spells share classes with a dash; a dash cashtag never lands in
    # the ticker's Stocktwits stream
    c = Candidate("BRK-B", "Berkshire Hathaway Inc.", "NYSE", 400.0, -1.0,
                  1e12, 399.0, "EQUITY")
    assert compose_post_text(c) == "$BRK.B printed a new 52-week low today"
```

In `tests/test_config.py`, replace the gate assertion:

```python
def test_plausibility_gate_is_sized_for_lows():
    # Lows run far higher than highs on a selloff; 500 would halt the feed on
    # its best content days. 1200 is ~43% of the 2,766-row universe:
    # unreachable by real breadth, tripped by a filter that stopped filtering.
    assert config.MAX_PLAUSIBLE_LOWS == 1200
    assert not hasattr(config, "MAX_PLAUSIBLE_HIGHS")
```

In `tests/test_select.py`, update the validation test:

```python
def test_validate_rejects_implausible_count():
    cands = [cand(f"T{i}", 2e9) for i in range(config.MAX_PLAUSIBLE_LOWS + 1)]
    with pytest.raises(select.ValidationError):
        select.validate(cands)
    select.validate(cands[:10])  # plausible: no raise
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_publish.py tests/test_config.py tests/test_select.py -q
```

Expected: FAIL — copy mismatch on "52-week high", and `AttributeError` on `MAX_PLAUSIBLE_LOWS`.

- [ ] **Step 3: Change the copy**

In `src/publish/base.py`, replace `compose_post_text`:

```python
def compose_post_text(c: Candidate) -> str:
    # No price/%chg/mcap in the copy: those numbers go stale between the
    # tick and the reader; the attached chart carries the quantitative story.
    # Cashtag uses Stocktwits symbology (BRK.B, not Yahoo's BRK-B).
    return f"${st_symbol(c.ticker)} printed a new 52-week low today"
```

- [ ] **Step 4: Change the gate**

In `config.py`, replace line 8:

```python
MAX_PLAUSIBLE_LOWS = 1200               # validation gate: more = broken source
```

In `src/select.py`, replace `validate`:

```python
def validate(candidates: list[Candidate]) -> None:
    if len(candidates) > config.MAX_PLAUSIBLE_LOWS:
        raise ValidationError(
            f"{len(candidates)} '52-week lows' is implausible "
            f"(gate: {config.MAX_PLAUSIBLE_LOWS}); refusing to post")
```

- [ ] **Step 5: Run the full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS, all 83+ tests.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: lows copy and a gate sized for lows

Copy locked to '\$TICKER printed a new 52-week low today'. Gate raised
500 -> 1200: new lows legitimately run far higher than new highs on a
selloff, and 500 would halt the feed on its best content days."
```

---

## Task 6: The walk-down — an unchartable top pick must not blank the day

The inherited `select.pick()` takes the top N by market cap up front, so a name that fails its chart *deterministically* is re-picked every tick and zeroes the day under `MAX_PER_TICK = 1`. Recorded as out-of-scope in the highs spec on 2026-07-10, still unfixed there.

Not theoretical here. On 2026-07-27 the two highest-ranked lows were **SPCX** (SpaceX, $1.47T, first traded ~2026-06-09) and **SKHY** (SK hynix, $1.03T, first traded ~2026-07-07). Both trip `MIN_HISTORY_DAYS = 330`. Without the walk-down the feed posts nothing that day. Recent listings that have fallen are close to the definition of a stock at a 52-week low.

**Files:**
- Modify: `src/select.py:16-23` (replace `pick`)
- Modify: `run.py:20-46`
- Modify: `config.py`
- Test: `tests/test_select.py`, `tests/test_run.py`

**Interfaces:**
- Consumes: `select.pick` (removed), `state.is_blocked`, `state.daily_count` (Task 1)
- Produces:
  - `src.select.ranked_eligible(candidates: list[Candidate], posted: list[dict], today: date) -> list[Candidate]` — full eligible list, market cap descending, **uncapped**
  - `src.select.slot_count(posted: list[dict], today: date) -> int`
  - `config.MAX_CANDIDATE_ATTEMPTS: int`
  - `select.pick` no longer exists

- [ ] **Step 1: Write the failing tests**

Replace the `pick` tests in `tests/test_select.py`:

```python
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
```

Replace the corresponding tests in `tests/test_run.py` and add the two new ones:

```python
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
```

Add `import config` and `from src.chart import ChartError` to `tests/test_run.py` if not already imported.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_select.py tests/test_run.py -q
```

Expected: FAIL — `AttributeError: module 'src.select' has no attribute 'ranked_eligible'`.

- [ ] **Step 3: Add the constant**

Append to `config.py`:

```python
# Bound the walk-down. Per candidate the Stocktwits symbol check allows 15s
# and each get_json retries 4x at 12s, so an unbounded walk over a selloff-day
# lows list can outrun the workflow timeout — and because tick.yml uses
# concurrency without cancel-in-progress, a stuck run queues later dispatches
# until GitHub drops them and the feed goes dark silently.
# Counts candidates EXAMINED, not charts fetched: the symbol check runs first
# and costs real time even when no chart is attempted.
MAX_CANDIDATE_ATTEMPTS = 20
```

- [ ] **Step 4: Replace `pick` with `ranked_eligible` + `slot_count`**

In `src/select.py`, delete `pick` and add:

```python
def ranked_eligible(candidates: list[Candidate], posted: list[dict],
                    today: date) -> list[Candidate]:
    """All postable candidates, LARGEST first. Not capped — run.py walks this
    list and stops once it has enough that actually chart, so an unchartable
    top-mcap name can't starve the whole tick."""
    eligible = [c for c in candidates
                if c.market_cap >= config.MIN_MARKET_CAP
                and not state.is_blocked(c.ticker, posted, today)]
    eligible.sort(key=lambda c: c.market_cap, reverse=True)
    return eligible


def slot_count(posted: list[dict], today: date) -> int:
    """How many posts this tick may still make: bounded by the per-tick cap
    and the day's remaining budget."""
    remaining_today = config.MAX_PER_DAY - state.daily_count(posted, today)
    return max(0, min(config.MAX_PER_TICK, remaining_today))
```

- [ ] **Step 5: Walk the ranked list in `run.py`**

Replace lines 31-46 of `run.py` (from `picks = select.pick(...)` through the end of the `for c in picks:` loop) with:

```python
    ranked = select.ranked_eligible(candidates, posted, today)
    slots = select.slot_count(posted, today)
    print(f"{len(candidates)} on today's 52wk-low list; "
          f"{len(ranked)} eligible, up to {slots} slots this tick")

    # Walk the ranked list (largest first), filling up to `slots` posts. A name
    # that fails its symbol check or chart fetch is skipped and the NEXT
    # eligible name is tried — so an unchartable top-mcap name (a recent
    # listing that has fallen is close to the definition of a 52-week low)
    # can't starve the tick. Everything fallible happens BEFORE recording
    # intent; a skipped name stays eligible for a later tick.
    ready = []
    for examined, c in enumerate(ranked, start=1):
        if len(ready) >= slots:
            break
        if examined > config.MAX_CANDIDATE_ATTEMPTS:
            print(f"examined {config.MAX_CANDIDATE_ATTEMPTS} candidates without "
                  f"filling {slots} slot(s); ending tick with {len(ready)}")
            break
        if not symbol_check(c):
            print(f"stocktwits symbol check failed, skipping {c.ticker}")
            continue
        try:
            ready.append((c, chart_fetch(c)))
        except ChartError as e:
            print(f"chart failed, skipping {c.ticker}: {e}")
    if not ready:
        return []
```

- [ ] **Step 6: Run the full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS.

- [ ] **Step 7: Add the job timeout**

In `.github/workflows/tick.yml`, add `timeout-minutes: 15` under `runs-on: ubuntu-latest` in the `tick` job:

```yaml
jobs:
  tick:
    runs-on: ubuntu-latest
    timeout-minutes: 15
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: walk the ranked list instead of picking the top N

An unchartable top-mcap name was re-picked every tick and could zero the day.
On 2026-07-27 the two largest names at new lows were SPCX and SKHY, both
recent listings that trip MIN_HISTORY_DAYS — the feed would have posted
nothing all day. Bounded at 20 candidates examined per tick, with a 15-minute
job timeout, so a degraded chart source can't silently queue out later ticks."
```

---

## Task 7: Chart correctness on the low side

Two one-condition fixes, each preventing a wrong chart under a factual claim.

**Files:**
- Modify: `src/chart.py:51-60`, `:110-113`, `:1-9` (docstring)
- Test: `tests/test_chart.py`

**Interfaces:**
- Consumes: `chart._fetch_history`, `chart._render_png`, `ChartError` (Task 1)
- Produces: no signature changes. `_fetch_history` gains a date check on the live quote.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chart.py`:

```python
def test_stale_quote_is_not_appended_as_todays_candle(monkeypatch):
    """stockanalysis returns the LAST session's quote for a name that hasn't
    traded today (TAP.A on 2026-07-27 returned td=2026-07-24). Appending it
    would draw a candle dated today from Friday's prices, under a headline
    claiming a new low today."""
    def fake_get_json(url, **kw):
        if "history" in url:
            return {"data": [{"t": "2025-07-10", "o": 20.0, "h": 20.5,
                              "l": 19.8, "c": 20.2},
                             {"t": "2026-07-24", "o": 39.51, "h": 39.51,
                              "l": 39.51, "c": 39.51}]}
        if "api/quotes" in url:
            return {"data": {"p": 39.51, "o": 39.51, "h": 39.51,
                             "l": 39.51, "td": "2026-07-24"}}
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(chart, "get_json", fake_get_json)
    with pytest.raises(chart.ChartError, match="stale"):
        chart._fetch_history("TAP-A", today=date(2026, 7, 27))


def test_fresh_quote_is_appended_as_todays_candle(monkeypatch):
    def fake_get_json(url, **kw):
        if "history" in url:
            return {"data": [{"t": "2025-07-10", "o": 20.0, "h": 20.5,
                              "l": 19.8, "c": 20.2},
                             {"t": "2026-07-24", "o": 76.0, "h": 76.4,
                              "l": 74.9, "c": 74.90}]}
        if "api/quotes" in url:
            return {"data": {"p": 74.31, "o": 74.74, "h": 75.2,
                             "l": 73.52, "td": "2026-07-27"}}
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(chart, "get_json", fake_get_json)
    rows = chart._fetch_history("CCI", today=date(2026, 7, 27))
    assert rows[-1] == ["2026-07-27", 74.74, 75.2, 73.52, 74.31]


def test_y_axis_floor_never_goes_negative(monkeypatch):
    """A name down 90%+ over the year pads below zero on a linear axis."""
    captured = {}
    real_subplots = chart.plt.subplots

    def spy_subplots(*a, **kw):
        fig, ax = real_subplots(*a, **kw)
        real_set_ylim = ax.set_ylim
        def spy_set_ylim(lo, hi):
            captured["ylim"] = (lo, hi)
            return real_set_ylim(lo, hi)
        ax.set_ylim = spy_set_ylim
        return fig, ax

    monkeypatch.setattr(chart.plt, "subplots", spy_subplots)
    rows = [[f"2026-01-{d:02d}", 100.0, 101.0, 99.0, 100.0] for d in range(1, 10)]
    rows += [[f"2026-02-{d:02d}", 1.0, 1.1, 0.4, 0.5] for d in range(1, 10)]
    chart._render_png(_c(), rows)
    assert captured["ylim"][0] >= 0.0, f"y-axis floor {captured['ylim'][0]} < 0"
```

`chart.plt` is the module-level `from matplotlib import pyplot as plt` in
`src/chart.py`, so patching it there is enough. `from datetime import date`
and `import pytest` are already at the top of `tests/test_chart.py`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_chart.py -q
```

Expected: FAIL — the stale-quote test appends instead of raising; the ylim test reports a negative floor.

- [ ] **Step 3: Require the live quote to be dated today**

In `src/chart.py`, replace the stale-history branch in `_fetch_history` (lines 51-60):

```python
    if hist[-1][0] < today.isoformat():
        q = (get_json(config.SA_QUOTE_URL.format(ticker=sa_symbol)) or {}).get("data")
        # `td` is the quote's own trade date. Without checking it, a name that
        # did not trade today gets the LAST session's prices drawn as today's
        # candle — a chart dated today built from stale data, under a headline
        # claiming a new low today.
        if q and q.get("p") and q.get("o") and q.get("td") == today.isoformat():
            p = float(q["p"])
            hist.append([today.isoformat(), float(q["o"]),
                         float(q.get("h") or p), float(q.get("l") or p), p])
        else:
            raise ChartError(
                f"{ticker}: history ends {hist[-1][0]} and the live quote is "
                f"stale or unusable (td={(q or {}).get('td')!r}) "
                f"— chart would miss or misdate today's move")
```

- [ ] **Step 4: Clamp the y-axis floor**

In `src/chart.py`, replace line 113:

```python
    ax.set_ylim(max(0.0, lo - pad), hi + pad)
```

- [ ] **Step 5: Update the module docstring**

In `src/chart.py`, change the docstring's closing sentence (lines 7-8) from `a 52wk-high post whose chart stopped yesterday would be missing its own move` to:

```
a 52wk-low post whose chart stopped yesterday would be missing its own move.
```

- [ ] **Step 6: Run the full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS.

- [ ] **Step 7: Run the live chart contract test**

```bash
.venv/bin/python -m pytest tests/contract/test_live_chart_render.py -q -m contract
```

Expected: PASS, a real PNG over 10KB.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "fix: reject stale quotes and clamp the y-axis floor

The renderer appended a 'today' candle whenever history lagged, with no check
on the quote's own trade date — TAP.A on 2026-07-27 returned td=2026-07-24,
which would have drawn Friday's prices as today. Also clamp the padded y-axis
floor at zero for names down 90%+ over the year."
```

---

## Task 8: Invert the independent auditor

The auditor is a deliberately different data path from the poster — per-ticker daily history, not the screener — so it is not the pipeline grading its own homework. It must flip with the source, and its tolerance must flip with it.

**Files:**
- Modify: `scripts/verify_day.py:1-25` (docstring), `:107-132` (`check_truth`), `:162` (artifact copy check)
- Test: `tests/test_audit_rules.py`

**Interfaces:**
- Consumes: `scripts/verify_day.py` `check_truth`, `check_artifacts`, `TRUTH_TOLERANCE` (Task 1)
- Produces: no signature changes

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_rules.py`:

```python
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
```

`ROOT` is already defined in that test module; if not, add `ROOT = Path(__file__).resolve().parent.parent` and `from pathlib import Path`.

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_audit_rules.py -q
```

Expected: FAIL on `df["High"] not in src`.

- [ ] **Step 3: Invert `check_truth`**

In `scripts/verify_day.py`, replace the body of `check_truth` from `prior = ...` to the end:

```python
    prior = df["Low"].iloc[max(0, i - 252):i]
    if prior.empty:
        report("WARN", "truth", f"{ticker}: no prior sessions (IPO day?); skipping")
        return
    prior_min, day_low = float(prior.min()), float(df["Low"].iloc[i])
    margin = (day_low - prior_min) / prior_min
    detail = (f"{ticker} {d}: day low {day_low:.2f} vs prior-252-session min "
              f"{prior_min:.2f} ({margin:+.2%})")
    # Tolerance inverts with the comparison: a permissive band ABOVE the prior
    # minimum. (1 - TOL) here would be stricter than exact and FAIL every post.
    if day_low <= prior_min * (1 + TRUTH_TOLERANCE):
        level = "PASS" if len(prior) >= 200 else "WARN"
        suffix = "" if len(prior) >= 200 else f" [only {len(prior)} prior sessions]"
        report(level, "truth", detail + suffix)
    else:
        report("FAIL", "truth", detail + " — NOT a 52-week low")
```

- [ ] **Step 4: Invert the artifact copy check and the docstring**

At `scripts/verify_day.py:162`, change `and "52-week high" in text` to `and "52-week low" in text`.

In the module docstring, change the `truth` line to:

```
  truth      each posted ticker really printed a 52-week low that day
             (day low <= min Low of up to 252 prior sessions, 0.1% tol)
```

- [ ] **Step 5: Run the full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS.

- [ ] **Step 6: Sanity-run the auditor against an empty log**

```bash
.venv/bin/python scripts/verify_day.py --all
```

Expected: exit 0, with PASS lines for rules and artifacts and no posts to check.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "fix: invert the auditor to the low side, tolerance included

df[High]->df[Low], prior.max()->prior.min(), and critically the tolerance
band flips from (1 - TOL) to (1 + TOL): keeping the high-side form would make
the check stricter than exact and FAIL every genuine post."
```

---

## Task 9: Identity, workflows and docs

Nothing here changes behaviour except the branch guard, but every string that still says "52wk-high" is a trap for the next reader, and a state push from a feature branch is a real hazard.

**Files:**
- Modify: `.github/workflows/tick.yml`, `.github/workflows/audit.yml`, `.github/workflows/ci.yml`
- Modify: `run.py:71-81` (`_git_sync_state`)
- Modify: `config.py:26` (`STOCKTWITS_USER_AGENT`)
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above
- Produces: no code interfaces; the repo is now self-describing

- [ ] **Step 1: Rename the bot identity strings**

In `run.py` `_git_sync_state`, change both occurrences of `52wk-poster-bot` to `52wk-lows-bot`.

In `config.py`, change `STOCKTWITS_USER_AGENT = "stocktwits-52wk-poster/1.0"` to `"stocktwits-52wk-lows-poster/1.0"`.

In `.github/workflows/tick.yml`, change `git config user.name "52wk-poster-bot"` to `"52wk-lows-bot"`.

- [ ] **Step 2: Guard the state-commit step to main**

In `.github/workflows/tick.yml`, change the commit step's condition:

```yaml
      - name: Commit state + output
        # always(): if the tick crashed mid-posting, the pending/confirmed
        # state on disk must still be persisted so nothing double-posts.
        # Branch guard: a manual dispatch on a feature branch must never push
        # its state to main.
        if: always() && github.ref == 'refs/heads/main'
```

- [ ] **Step 3: Set Phase 1 to dry-run with no token**

In `.github/workflows/tick.yml`, replace the "Run tick" step so it cannot post. The `--live` flag and the `STOCKTWITS_ACCESS_TOKEN` env line are added by hand at Task 10, not before.

```yaml
      - name: Run tick (Phase 1 preview — dry-run, no token in this repo)
        env:
          # Launch caps: 1 post/tick (a 30-min trickle that dodges the
          # Stocktwits duplicate filter), 12/day. Repo defaults are 2/20.
          MAX_PER_TICK: "1"
          MAX_PER_DAY: "12"
          PYTHONUNBUFFERED: "1"
        run: python run.py --sync-state
```

- [ ] **Step 4: Rewrite the README**

Replace `README.md`:

```markdown
# stocktwits-52wk-lows-poster

Posts the largest US common stocks printing new **52-week lows**, one every
30 minutes during market hours, each with a self-rendered 1-year daily
candlestick chart.

Copy is fixed: `$TICKER printed a new 52-week low today`. No price, percent or
market cap — those go stale between the tick and the reader; the chart carries
the numbers.

## Pipeline

yfinance screen (US, listed exchanges, >$1B mcap, market-cap desc)
→ today's 52wk-low list (day-cumulative: today's low touched the 52-week low)
→ drop preferreds, warrants and lines under $5M dollar volume
→ rank by market cap, walk down until one charts
→ 1-year candlestick PNG from keyless stockanalysis.com data
→ post to Stocktwits with the chart attached

## Rules

- $1B market-cap floor; exchange-listed only (no pink sheets).
- Never the same ticker on consecutive trading days.
- 1 post per tick, 12 per day (repo defaults 2/20, overridden in the workflow).
- Market hours only. A quote must have traded today, which makes holiday
  posts structurally impossible without a holiday calendar.
- Recent listings are skipped: a "1Y" chart of a three-month-old listing
  misleads. This is why the walk-down exists — recent listings that have
  fallen are close to the definition of a stock at a 52-week low.

**Expect 2–6 posts on an ordinary day**, more on a selloff, zero on a strong
day. Supply binds well before the daily cap. That is not a malfunction.

## Running it

    .venv/bin/python -m pytest -q            # unit tests (83+)
    .venv/bin/python -m pytest -m contract   # live network tests
    .venv/bin/python run.py --force          # one dry-run tick, any time of day

Dry-run is the default. `--live` requires `STOCKTWITS_ACCESS_TOKEN` and exits
1 without it — never a silent downgrade.

## Siblings

Separate repos by design, nothing shared:

- `stocktwits-52wk-poster` — the same engine on the high side (@Stocktwits52wHighs)
- `stocktwits-relative-weakness-poster` — also 52-week lows, but ranked by
  Stocktwits watcher count and framed as crowded breakdowns (@STRelativeWeakness)

The two lows feeds do not coordinate and will sometimes post the same ticker
on the same day. That is intended.

An upstream break (Yahoo screen, stockanalysis.com) must be fixed in each
repo separately.
```

- [ ] **Step 5: Run the full suite and one live dry-run tick**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python run.py --force
```

Expected: tests PASS. The tick prints a candidate count and either writes `output/<today>/<TICKER>.{png,txt}` or reports nothing eligible. **Open the PNG and read the .txt** — the chart must show a stock at the low end of its year, and the text must read exactly `$TICKER printed a new 52-week low today`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: repo identity, branch-guarded state pushes, README

Phase 1 workflow runs dry-run with no token in the repo, so it is
structurally incapable of posting. State commits are guarded to main so a
manual dispatch on a feature branch can't push state."
```

---

## Task 10: Phase 1 preview go-live (owner-driven)

Manual and irreversible in parts. Do not automate; walk the owner through it.

**Files:** none in-repo

- [ ] **Step 1: Create the private GitHub repo and push**

```bash
gh repo create ethanberrk/stocktwits-52wk-lows-poster --private --source=. --remote=origin --push
gh repo view ethanberrk/stocktwits-52wk-lows-poster --json isPrivate,defaultBranchRef
```

Expected: `isPrivate: true`, default branch `main`.

- [ ] **Step 2: Confirm CI is green on the pushed commit**

```bash
gh run list --repo ethanberrk/stocktwits-52wk-lows-poster --limit 5
```

Expected: the `ci` workflow succeeds.

- [ ] **Step 3: Dispatch one tick manually and inspect the artifacts**

```bash
gh workflow run tick.yml --repo ethanberrk/stocktwits-52wk-lows-poster --ref main
sleep 90
gh run list --repo ethanberrk/stocktwits-52wk-lows-poster --workflow tick.yml --limit 1
```

Then pull and open whatever landed in `output/<today>/`. Outside market hours the tick exits cleanly with "outside market hours; nothing to do" — that is a pass for the plumbing, not for the picks.

- [ ] **Step 4: Ask the owner for the cron-job.org API key and a repo-scoped PAT**

⚠️ Both are owner-supplied. The PAT must be **fine-grained, scoped to this repo only, Actions read+write**. Note its expiry date in the spec's "Known inherited risk" section — when it lapses, dispatches 401, cron-job.org still reports success, and the feed goes dark silently with no alarm.

- [ ] **Step 5: Create the cron-job.org schedule**

`PUT https://api.cron-job.org/jobs` with a Bearer API key. The job POSTs to
`https://api.github.com/repos/ethanberrk/stocktwits-52wk-lows-poster/actions/workflows/tick.yml/dispatches`
with body `{"ref":"main"}`, headers `Authorization: Bearer <PAT>` and
`Accept: application/vnd.github+json`. Schedule: minutes `[15, 45]`, hours
`13-21` UTC, weekdays `1-5`. The `:15/:45` offset keeps it clear of the highs
poster (`:00/:30`) and the weakness poster (`:05/:35`).

Verify with `GET /jobs/{id}/history` after the first slot: a 204 from GitHub
and a corresponding workflow run.

- [ ] **Step 6: Let it run several days, then review**

Check each day's `output/`:
- Are the picks recognisable companies, not preferred series or ghost-volume lines?
- Does each chart visibly show the stock at the low end of its year?
- Does the copy read exactly right?
- Is the daily count in the 2–6 range, with the occasional zero?

- [ ] **Step 7: Record the state of play**

Update the spec's status line to note Phase 1 is live and the date, and commit.

**Phase 2 (live posting) is deliberately NOT in this plan.** It needs a new Stocktwits account, a verified email, a token checked against `account/verify` *before* wiring, and the preview state cleared — `state.is_blocked` covers today and the previous trading day, so leftover dry-run entries (`post_id: null`) would make day one skip its strongest names. Plan it separately once the owner has reviewed real preview output.

---

## Verification checklist

Before calling this done:

- [ ] `.venv/bin/python -m pytest -q` — all unit tests pass
- [ ] `.venv/bin/python -m pytest -m contract -q` — all three live contract tests pass
- [ ] `.venv/bin/python run.py --force` during market hours produces a chart, and the PNG shows a stock at the low end of its year
- [ ] `grep -rn "52-week high\|52wk-high\|week52_high\|HighsSource\|MAX_PLAUSIBLE_HIGHS\|fiftyTwoWeekHigh\|regularMarketDayHigh" src tests run.py config.py scripts README.md` returns nothing
- [ ] `grep -rn "STOCKTWITS_ACCESS_TOKEN" .github/` returns nothing — Phase 1 must be structurally incapable of posting
- [ ] `git log --oneline` reads as a clean story from the baseline clone through each inversion
