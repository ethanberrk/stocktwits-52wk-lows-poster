# Stocktwits 52-Week-Lows Poster — Design

**Date:** 2026-07-27
**Status:** Revised after adversarial review (v2) — pending owner spec review

> **v2 changelog.** An adversarial review on 2026-07-27, plus live verification
> against that day's market data, invalidated several v1 assumptions. The
> universe was effectively $6.6B+ rather than $1B+; preferred shares and
> warrants passed every filter while inheriting their parent's market cap; a
> stock could post as a "new low" while up 3% on the day; and near-zero-volume
> lines parked at their low re-qualified indefinitely. All are addressed below.
> Section "Review findings and how each was resolved" records the full ledger.

## Goal

Every 30 minutes during market hours, post the **largest** US common stocks
over $1B market cap that **broke to a new 52-week low today**, to a **new
dedicated Stocktwits account**, each with a self-rendered 1-year daily
candlestick chart. Copy is locked to the bare, neutral line:

```
$TICKER printed a new 52-week low today
```

This is the deliberate mirror of the live `stocktwits-52wk-poster`
(@Stocktwits52wHighs): same universe, same ranking axis (market cap
descending), same trickle, same safety machinery.

**It is not a pure mirror in its filters, and cannot be.** The high and low
sides of the market are not symmetric. Instruments that sit near their 52-week
low structurally and barely trade — preferred shares, warrants, illiquid
share classes — are invisible on the high side and pervasive on the low side.
Every asymmetry the review found is handled explicitly below rather than
inherited by copying.

## Relationship to the existing posters

### vs. the 52-week-high poster (the parent)

Separate repo (`ethanberrk/stocktwits-52wk-lows-poster`, local
`/Users/ethanberk/stocktwits-52wk-lows-poster`), code cloned from
`stocktwits-52wk-poster` and then inverted. Nothing is shared: its own GitHub
Secrets, its own `state/posted.json`, its own Stocktwits account and token,
its own cron-job.org schedule.

Rationale (decided 2026-07-27, approach A of three considered): the highs
poster is live and posting daily to a real account. Structural isolation
means nothing built here can break it. Two rejected alternatives:

- **Shared core library** — cleaner against upstream breakage, but requires
  refactoring a live production system, and a bad change takes down both
  feeds at once.
- **One repo, a highs/lows switch** — avoids duplication without a refactor,
  but the feeds then share state commits, workflow runs and rollbacks; a
  mistake on the lows side can silence the highs account.

Accepted cost, identical to the RS→RW split: when an unofficial upstream
(Yahoo screen, stockanalysis.com) breaks, the fix must be applied in every
repo that depends on it.

**Clone from the highs repo, not the weakness repo.** The weakness poster's
`src/chart.py` diverged: it dropped the `st_symbol` dash→dot mapping and
dropped the `ChartError` raised when history is stale *and* the live quote is
unusable. The highs repo's renderer is the correct baseline.

**Pull `origin/main` before cloning.** The local highs checkout is at
`b923605` (2026-07-10) and its README still describes the retired chart-img
service; the live repo has moved on.

### vs. the relative-weakness poster (the overlap)

`stocktwits-relative-weakness-poster` (@STRelativeWeakness) has been live
since 2026-07-23 and already draws from the 52-week-low universe. It is a
**different feed with a different thesis**: it ranks by Stocktwits watcher
count descending with a `MIN_WATCHERS = 5000` floor and frames each post as a
*crowded breakdown*. This poster ranks by market cap and states the fact
without a thesis. It also uses a completely different data path — the WSJ
Market Data Center feed enriched by Yahoo v7 bulk quotes
(`src/source/rw_source.py`), **not** `yf.screen` — so its source code answers
no questions about screen-field availability.

**Decided 2026-07-27: the two feeds do NOT coordinate.** They will sometimes
post the same ticker on the same day. That is accepted — separate accounts,
separate audiences. No cross-repo state sharing will be built, because it
would couple two independent systems and create a new silent failure mode for
no editorial gain. Verified harmless: separate repos, output directories,
state files and tokens; posting rate limits are per-token; the shared
GitHub-runner IP pool touches only the unauthenticated symbol-lookup
endpoint, which this poster calls once per pick.

## The universe

`yf.screen`, US region, `intradaymarketcap > $1B`, sorted by market cap
descending, paged.

**Fix over the parent (blocking).** The highs poster's query has no exchange
filter and pages to `_MAX_OFFSET = 3000`. Measured live 2026-07-27: the query
returns exactly 3,000 rows — the cap is hit — of which **1,739 are pink
sheets or otherwise off-exchange** and discarded later, leaving 1,261 usable
names. The 3,000th row's market cap is **$6.59B**, so the real floor is
~$6.6B and roughly half the eligible $1B+ universe is never seen.

The highs poster survives this because ~130 names hit new highs on an ordinary
day and it needs 12. Only 7 hit new lows on the same day. The lows feed cannot
afford to discard half its universe.

Fix, verified live: add `exchange` to the query itself —

```python
yf.EquityQuery("is-in", ["exchange", "NMS", "NYQ", "NGM", "NCM", "ASE"])
```

Result: **2,766 rows down to a true $1.001B floor**, every row on an allowed
exchange, and `_MAX_OFFSET = 3000` no longer truncates. All rows carry
`regularMarketOpen`, `regularMarketVolume` and `regularMarketPreviousClose`.

**Screen-field availability is resolved, not open.** `yf.screen` rows do carry
`regularMarketDayLow` and `fiftyTwoWeekLow`. Verified live: 13 of 3,000 rows
lack them — the *same* 13 rows that also lack the high fields, already handled
by the existing `_REQUIRED` null check. The v1 spec's "per-ticker quote
enrichment fallback" is dropped from the design entirely.

## What a post requires — the full rule chain

A name must clear every one of these. Ordering is cheap-to-expensive.

### Stage 1 — instrument hygiene (screen row)

1. `quoteType == "EQUITY"`, non-empty name, `NAME_EXCLUDE_RE` does not match.
2. Exchange in the allowed set (now enforced in the query, re-checked in code).
3. **Not a preferred share**: reject symbols matching `-P[A-Z]?$`.
4. **Not a warrant, right or unit**: reject 5-character symbols matching
   `^[A-Z]{4}(W|R|U)$`.
5. **One line per company**: group surviving rows by `longName` and keep the
   single line with the highest dollar volume. Drops `BRK-A` in favour of
   `BRK-B`, `MOG-A`/`MOG-B` to one, `BF-A`/`BF-B` to one.

**Why this is new and necessary.** `NAME_EXCLUDE_RE` matches words like
"Pfd"/"Preferred"/"Warrants", but Yahoo gives these rows the **parent
common's `longName`**, so it never fires. Measured live 2026-07-27: of 65
dash-tickers surviving the exchange and `EQUITY` filters, `NAME_EXCLUDE_RE`
excluded exactly **one**. Concrete leaks found, all carrying their parent's
market cap: `WFC-PC` at $113.7B, `ALL-PH` at $29.1B (**on that day's new-lows
list**), `KEY-PK` at $18.0B, `AXIA-PC` at $22.4B. The warrant `DJTWW` charts
cleanly and its Stocktwits symbol resolves 200 — nothing downstream would have
stopped it.

Legitimate dual-class lines (`BRK-B`, `PBR-A`, `HEI-A`, `LEN-B`, `UHAL-B`)
must survive rules 3–4; only rule 5 touches them, and only to pick one.

### Stage 2 — liquidity and freshness

6. **Freshness gate (inherited, unchanged):** `regularMarketTime` must fall on
   today's ET date. Makes stale "new low today" posts structurally impossible
   on holidays and unscheduled closures, with no holiday calendar.
7. **Dollar-volume floor (new): `price × volume >= $5,000,000`.**

**Why.** `TAP-A` on 2026-07-27 traded **116 shares** all day, with
`dayHigh == dayLow == previousClose == fiftyTwoWeekLow == 39.51` and a
today-stamped quote. It passes the freshness gate (it did technically trade)
and ties its 52-week low, so it qualifies every day it prints one flat trade —
and the 2-day cooldown returns it every other day forever. `ALL-PH` traded
58,313 shares. Both are excluded by a $5M floor; every legitimate name on the
verified 2026-07-27 list clears it by a wide margin.

### Stage 3 — the low test and the down-day rule

8. **At the low:** `regularMarketDayLow - 1e-6 <= fiftyTwoWeekLow`.
   Yahoo's `fiftyTwoWeekLow` includes today — verified live: across 1,207
   filtered rows, zero had `regularMarketDayLow` strictly below
   `fiftyTwoWeekLow`, and the equality cases are exactly the day's new lows.
   The epsilon direction mirrors the highs poster correctly: `dayLow 10.00`
   vs `52wLow 10.00` accepts; `dayLow 10.01` vs `52wLow 10.00` rejects.
9. **Down on the day:** `regularMarketPrice < regularMarketPreviousClose`.
10. **Below the open:** `regularMarketPrice < regularMarketOpen`.

**Why 9 and 10 (owner decision, 2026-07-27: "only genuine breaks on down
days").** `src/chart.py:85` colours each candle `UP if c >= o else DOWN`, and
`_legend_text` (`chart.py:64-72`) reports change versus the **previous
close**. A stock that dips to a new low and rallies closes green. Live example
from 2026-07-27: **UBER** printed `dayLow == fiftyTwoWeekLow == 65.41` while
trading **+3.09%** — the post would have read "printed a new 52-week low
today" above a green candle, a green price pill and a legend reading
"+3.02%".

Rule 9 alone guarantees a negative legend; rule 10 additionally guarantees a
red candle body (a gap-down that rallies off the open would otherwise close
green while still being down on the day). Together the headline, the candle
colour and the legend always agree. Cost: a stock that gaps down to a new low
and then rallies is skipped — editorially correct, since that is a bounce
story, not a breakdown.

### Stage 4 — independent break confirmation (at chart time)

11. **Today's low must be strictly below the minimum low of the prior
    ~252 sessions**, computed from the stockanalysis.com daily history
    **excluding** the appended today candle:
    `today_low < min(prior_lows) - 1e-6`.

**Why this is the most important rule in the design.** Two things fall out of
it:

- *It resolves tie-versus-break correctly.* Yahoo's `fiftyTwoWeekLow` includes
  today, so `dayLow == fiftyTwoWeekLow` cannot distinguish "set a new low
  today" from "merely touched a low set three months ago." The prior-session
  minimum can. The owner's decision was genuine breaks only.
- *It is an independent truth check on the exact claim being posted.* The
  history comes from a different vendor than the screen. If the Yahoo filter
  chain silently breaks, this rejects the name before anything is posted.

It costs nothing extra: `src/chart.py` already fetches that year of history to
draw the chart. A name failing rule 11 raises `BreakNotConfirmed`, a subclass
of `ChartError`, so the existing walk-down skips it and tries the next
candidate with no change to `run.py` — while the logs still distinguish "the
chart could not be drawn" from "this was not a genuine break."

### Stage 5 — selection

12. `market_cap >= MIN_MARKET_CAP` (re-checked in `select`).
13. Not blocked by cooldown — same ticker today or the previous trading day.
14. Rank by market cap descending; walk the list (see below).

### Verified end-to-end on live data

Running the full corrected chain against 2026-07-27's market produced **9
candidates**, in rank order: SPCX, SKHY, CCI, PHG, PSKY, LPL, EROC, VNET,
STDN. All genuinely down on the day. No preferreds, no warrants, no illiquid
lines, UBER correctly excluded. Under the v1 spec the same day produced 7
candidates of which three were junk and one (UBER) was up 3%.

## The plausibility gate — replaced, not re-pointed

v1 proposed `MAX_PLAUSIBLE_LOWS = 2000`, ported from the weakness poster. The
review showed the number does not transfer: that poster gates the **WSJ
all-issues new-lows feed**, which has no size floor and genuinely runs to four
digits. Here the entire post-filter universe is 2,766 rows. A parser bug that
accepted every row would yield a count *below* 2,000, pass `select.validate`,
and post "$AAPL printed a new 52-week low today." Undeletable.

**Design decision: the count gate is demoted, and rule 11 is promoted to the
real guard.** A per-name independent confirmation against a second vendor is
strictly stronger than any aggregate count threshold, and it cannot be fooled
by a filter that stops filtering.

The count gate is retained only as a coarse "the parser produced garbage"
tripwire, set at **`MAX_PLAUSIBLE_LOWS = 1200`** (~43% of the universe).
Measured ratio on 2026-07-27: 0.0033. A broad-selloff day will not approach
this; a filter that stopped filtering produces ~1.0 and trips it.

## No tick starvation — the walk-down

The highs poster's `select.pick()` takes the top N by market cap up front, so
a name that fails its chart *deterministically* is re-picked every tick and
can zero the day under `MAX_PER_TICK = 1`. Recorded as out-of-scope in the
highs spec on 2026-07-10, still unfixed there.

That defect is not theoretical here. On 2026-07-27 the two highest-ranked lows
were **SPCX** (SpaceX, $1.47T, first traded ~2026-06-09) and **SKHY** (SK
hynix, $1.03T, first traded ~2026-07-07). Both trip the `MIN_HISTORY_DAYS`
recent-IPO guard. Without the walk-down the feed would have posted **nothing
at all that day**. Recent listings that have fallen are close to the
*definition* of a stock at a 52-week low.

Ported from the weakness poster (`src/select.py:19-36`, `run.py:31-51`, proven
in production since 2026-07-20), with the ranking axis changed to market cap:

- `select.ranked_eligible(...)` returns the full eligible list, sorted by
  market cap descending, uncapped.
- `select.slot_count(...)` returns
  `max(0, min(MAX_PER_TICK, MAX_PER_DAY - daily_count))`.
- `run.py` walks `ranked`, skipping names that fail the symbol check, the
  chart fetch or the break confirmation, and stops once it has `slots`
  chartable names. A skipped name stays eligible for a later tick.

**Bounded, unlike the parent port (new).** An uncapped walk has no time
budget: per candidate the symbol check allows 15s (`src/stocktwits.py:27`)
and each `get_json` retries 4× at 12s (`src/fetch.py:14-27`) — roughly 110s
worst case per name. If stockanalysis.com degrades, the tick walks hundreds of
names. `tick.yml` sets no `timeout-minutes`, and `concurrency: {group: tick,
cancel-in-progress: false}` means a stuck run queues later dispatches until
GitHub drops them — the feed goes dark silently. Therefore:

- **`MAX_CHART_ATTEMPTS = 20` per tick.** Exhausting it logs and ends the tick
  cleanly with zero posts.
- **`timeout-minutes: 15` on the tick job.**

All fallible work still happens **before** any write-ahead intent is recorded,
preserving at-most-once posting.

## Chart fixes (low-side specific)

The renderer is genuinely direction-neutral and needs no colour change — the
v1 claim holds. Four correctness fixes do apply:

1. **Require the live quote to be dated today** before appending it as today's
   candle. `chart.py:51-60` appends whenever history ends before today and the
   quote has `p` and `o` — with no date check. Stockanalysis returned
   `"td": "2026-07-24"` for `TAP.A` on 2026-07-27, which would have produced a
   candle *dated today* built from Friday's prices. Require
   `quote["td"] == today.isoformat()`, else `ChartError`.
2. **Minimum candle count, not just a first date.** `MIN_HISTORY_DAYS = 330`
   checks only that the first candle is old enough. `TAP.A` returned 61
   candles spanning 2025-08-06 → 2026-07-24 and would have passed, rendering a
   sparse chart labelled "1D · 1Y". Add `MIN_HISTORY_CANDLES = 200`.
3. **Clamp the y-axis floor at zero.** `chart.py:110-113` computes
   `ylim(lo - pad, hi + pad)`; for a collapsed name `lo - pad` can go negative.
4. **Delete the v1 "pinned red-candle test."** As specified it asserted what
   `c >= o` already does by construction — it would pass on day one and test
   nothing low-specific. It is replaced by tests on rules 9, 10 and 11, which
   are what actually make the chart match the headline.

**Deferred, recorded here:** a linear y-axis compresses the recent action on a
name down 90%+ over the year — the very part the post is about. Log scale
above some high/low ratio is the fix. Not built now; recorded under
"Out of scope" below as the backlog entry.

## What stays identical (copied untouched)

- `MIN_MARKET_CAP = 1_000_000_000`, enforced in the query and again in
  selection — now with the truncation fixed, so the number is honest.
- `NAME_EXCLUDE_RE`, `quoteType == "EQUITY"`.
- `MIN_HISTORY_DAYS = 330` recent-IPO skip.
- Chart pipeline: keyless stockanalysis.com 1Y daily history plus today's
  candle from the live quote; 800×450 TradingView-light PNG rendered
  in-process with matplotlib.
- Cooldown: same ticker blocked today and on the previous trading day
  (`state.is_blocked`). **Known hole, inherited:**
  `state.previous_trading_day` (`state.py:38-42`) skips weekends only, so
  after a market holiday the cooldown collapses to one day. Accepted, matching
  the parent.
- Market-hours gate (9:30–16:00 ET, weekdays), `--force` for local runs.
- **Write-ahead publishing**: intents recorded as `pending` and git-pushed
  (`run.py --sync-state`) before anything irreversible; confirmed to `posted`
  with the real `post_id` afterwards. A crash can lose a post, never duplicate
  one. `PublishError` leaves the ticker `pending`.
- Pre-post cashtag validation: 404 skips, indeterminate (403/timeout/5xx)
  allows with a log. `st_symbol` dash→dot mapping (`BRK-B` → `BRK.B`).
- **`urllib`, never `requests`** — Stocktwits' CDN bot-blocks `requests`' TLS
  fingerprint. Applies to the symbol check, the chart data fetch and the
  publisher's hand-built multipart POST.
- Dry-run by default; `--live` without `STOCKTWITS_ACCESS_TOKEN` is a hard
  exit, never a silent downgrade.
- Nightly auditor (`scripts/verify_day.py` + `audit.yml`, 22:30 UTC weekdays).
- Tick workflow: `workflow_dispatch` only (**no GitHub `schedule`** — it
  delivered ~27% of its slots, 7–56 minutes late, compressing the trickle and
  burning the daily cap early), `concurrency: tick`.

## Workflow hardening

- State-commit step guarded as `if: always() && github.ref == 'refs/heads/main'`
  (the weakness poster's hardening; the parent's bare `if: always()` lets a
  manual dispatch on a feature branch push state to main).
- `timeout-minutes: 15` on the tick job.

## Publishing contract

`POST https://api.stocktwits.com/api/2/messages/create.json`, multipart, image
in the field named **`chart`**.

**Correction to v1:** this is *not* "confirmed in both existing repos." Both
publishers carry the identical comment that the field name is unconfirmed
against current Stocktwits docs and that the first live post validates it
(`src/publish/stocktwits_pub.py:18-19`). It has worked in production for both
accounts, which is good evidence — but note a 200 plus a message id
(`stocktwits_pub.py:86-95`) does **not** prove the image attached. Phase 2's
human eyeball on the first live post is the real check.

Two other v1 claims — the `422` duplicate-filter rejection and the
`CORE-4302` email-verification `403` — come from the owner's operational
history of the highs account's launch and are **not** corroborated anywhere in
either repo. They are retained as launch cautions, flagged as unverified.

## Caps and expected volume

`MAX_PER_TICK = 1`, `MAX_PER_DAY = 12`, set as workflow env exactly as the
highs poster runs them (repo defaults stay 2/20). The 30-minute trickle also
avoids the Stocktwits duplicate filter.

**Expected volume is well below the cap and that is normal.** With 13 in-market
ticks per day, 12/day is not the binding constraint — supply is. On
2026-07-27, a quiet day, the corrected chain produced 9 candidates, of which
the top 2 were unchartable and the cooldown would remove the previous day's
names: realistically **2–6 posts on an ordinary day, more on a selloff, and
zero on a strong day.** The cap exists to bound a crash day, not to describe
normal output. This must not be read as a malfunction.

## Account isolation (critical)

Posts go to a **new dedicated Stocktwits account** — not @Stocktwits52wHighs
(whose identity is breakouts) and not @STRelativeWeakness. Handle is the
owner's choice, needed only at Phase 2.

**Mandatory pre-wiring check:** call `account/verify` with the new token and
confirm the returned username and user id are the *new* account **before**
storing it as this repo's `STOCKTWITS_ACCESS_TOKEN`. This is the only thing
standing between a mis-pasted token and lows posting to the highs account.
Posts cannot be deleted.

## Rollout — two phases

**Phase 1 — preview (no secrets).** The tick workflow runs dry-run and the
repo holds no posting token, so it is *structurally* incapable of posting.
Each tick renders charts in-process and commits would-be posts (PNG + text) to
`output/YYYY-MM-DD/`. Review several days of samples: right picks, charts that
actually show the break, copy that reads well, and — specifically — **no
preferreds, no ghost-volume lines, and no green charts.**

**Phase 2 — live.** Owner creates the account and verifies its email (an
unverified email produced a `CORE-4302` 403 during the highs launch). Token
minted, verified via `account/verify`, stored as the repo secret. **Preview
state must be cleared first**: `state.is_blocked` covers today and the
previous trading day, so leftover dry-run entries (`post_id: null`) would make
day one skip its strongest names. Then one supervised live post is made and
eyeballed — chart attached? correct account? correct copy? — before the
workflow is flipped to `--sync-state --live` unattended.

## Scheduling

cron-job.org job POSTing `workflow_dispatch` to `tick.yml`, minutes `[15, 45]`,
hours 13–21 UTC, weekdays — 13 in-market ticks. Offset from the highs poster
(`:00/:30`) and the weakness poster (`:05/:35`) so the three feeds do not fire
simultaneously; this is for legibility when debugging, not a technical
requirement. Auth is a **fine-grained GitHub PAT scoped to this repo only**
(Actions read+write), stored in the job's Authorization header.

## Known inherited risk (accepted, not fixed here)

When the scheduler's PAT expires, dispatches fail with 401, cron-job.org still
reports success, and posting stops **silently**. The highs poster's PAT lapses
around 2026-10-04; this repo's will carry its own expiry.

The review argued the case for a dead-man's-switch is materially stronger here
than on the high side, because "zero posts today" is a *plausible normal
outcome* on the low side and therefore indistinguishable from a silent
failure. **Owner decision 2026-07-27: skip it, match the other two accounts.**
Recorded as the top recommendation for a follow-up project covering all three
feeds.

## The auditor — not a one-line change

v1 claimed the auditor's truth check "inverts to lows along with the source."
It is roughly eight edits across two functions in `scripts/verify_day.py`:

- `df["High"]` → `df["Low"]` (two sites) and `prior.max()` → `prior.min()`
  (`verify_day.py:107-132`).
- **The tolerance must invert too**:
  `day_high >= prior_max * (1 - TRUTH_TOLERANCE)` becomes
  `day_low <= prior_min * (1 + TRUTH_TOLERANCE)`. Keeping `(1 - TOL)` turns a
  permissive tolerance into a stricter one and produces false FAILs on every
  post.
- The margin expression and detail strings.
- `verify_day.py:162` (`"52-week high" in text`) and the module docstring
  (line 15).
- **New:** the auditor should also assert the down-day rules (9, 10) held for
  each post, since those are now part of what the copy implies.

## Testing

Port the highs poster's suite (83 tests, verified via `pytest --collect-only`:
"83/86 collected, 3 deselected") and extend it:

- `test_source_parse` / `test_yfinance_source`: fixtures carrying
  `regularMarketDayLow` / `fiftyTwoWeekLow` / `regularMarketOpen` /
  `regularMarketVolume` / `regularMarketPreviousClose`. Assertions for the
  low test at and around the boundary; **new**: preferred-symbol rejection
  (`WFC-PC`, `ALL-PH`, `KEY-PK`) with dual-class survival (`BRK-B`, `PBR-A`,
  `HEI-A`), warrant/right/unit rejection (`DJTWW`), same-company dedupe by
  dollar volume, the $5M dollar-volume floor (`TAP-A` at 116 shares), and the
  down-day plus below-open rules (a UBER-shaped row at its low but +3% must be
  rejected).
- `test_select`: market-cap-descending ordering, the $1B floor, cooldown
  blocking, `ranked_eligible` uncapped, `slot_count` arithmetic.
- `test_config`: the gate at 1200.
- `test_publish`: the locked copy template including the `BRK-B` → `BRK.B`
  mapping.
- `test_chart`: existing tests, **plus** the break-confirmation rule (a name
  whose today-low merely ties a three-month-old low raises `ChartError`), the
  quote-date check, the minimum-candle-count check, and the non-negative
  y-axis floor.
- `test_run`: the walk-down — a deterministic `ChartError` on the top-ranked
  name must result in the *next* eligible name posting, not an empty tick —
  **plus** `MAX_CHART_ATTEMPTS` terminating a walk cleanly.
- `test_audit_rules`: rules replay against the lows condition with the
  inverted tolerance.
- Contract tests (network): live `yf.screen` with the exchange filter
  returning a true $1B floor and populated low fields; live chart render
  producing a real PNG; live Stocktwits symbol lookup.

The full suite must pass before Phase 1's schedule is enabled.

## Review findings and how each was resolved

| # | Finding | Resolution |
|---|---|---|
| 1 | Universe truncated at ~$6.6B, half of it pink sheets | Exchange filter in the query; verified 2,766 rows to $1.001B |
| 2 | `MAX_PLAUSIBLE_LOWS = 2000` unreachable, gate protects nothing | Gate demoted to 1200 tripwire; per-name independent break confirmation (rule 11) promoted to the real guard |
| 3 | Preferreds and warrants inherit parent market cap and rank top | Symbol-pattern rejection + same-company dedupe (stage 1) |
| 4 | Illiquid lines pinned at their low re-qualify forever | $5M dollar-volume floor (rule 7) |
| 5 | Green candle under a "new low" headline; the proposed pinned test was empty | Down-day + below-open rules (9, 10); empty test deleted and replaced |
| 6 | Uncapped walk-down has no time budget | `MAX_CHART_ATTEMPTS = 20`, `timeout-minutes: 15` |
| 7 | Auditor inversion is ~8 edits, and the tolerance must flip | Documented explicitly, with the tolerance trap called out |
| 8 | Quote appended as "today" without a date check | Require `quote["td"] == today` |
| 9 | `MIN_HISTORY_DAYS` checks first date, not density | `MIN_HISTORY_CANDLES = 200` |
| 10 | Negative y-axis floor on collapsed names | Clamp at zero; log scale deferred |
| 11 | v1 wrongly said the weakness renderer was unchanged | Clone from the highs repo; divergences named |
| 12 | Missing `github.ref` guard on the state-commit step | Added |
| 13 | `chart` multipart field described as "confirmed" | Corrected to "works in production, unconfirmed against docs" |
| 14 | 422 / CORE-4302 claims uncorroborated in either repo | Flagged as owner operational history, unverified |
| 15 | Screen low-field availability listed as an open question | Resolved live; fallback dropped |
| 16 | Local highs checkout stale (2026-07-10) | Pull `origin/main` before cloning |
| 17 | Cooldown holiday hole undocumented | Documented, accepted |
| 18 | 12/day implied as expected volume | Expected 2–6/day stated explicitly |

## Out of scope

- Cross-repo deduplication with @STRelativeWeakness (explicitly declined).
- A shared library between the three posters.
- The zero-posts dead-man's-switch (declined 2026-07-27; recommended as a
  separate project covering all three accounts).
- Log-scale charts for collapsed names (deferred, recorded above).
- A market-holiday calendar — the freshness gate covers posting; the cooldown
  hole is accepted.
- Any change to the live highs or weakness posters. **Note:** findings 1, 3,
  4, 6, 8, 9 and 12 are latent in the highs poster too. Fixing them there is a
  separate decision, not part of this build.
