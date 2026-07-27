# Stocktwits 52-Week-Lows Poster — Design

**Date:** 2026-07-27
**Status:** Approved (pending spec review)

## Goal

Every 30 minutes during market hours, post the **largest** US common stocks
over $1B market cap that printed a **new 52-week low today** to a **new
dedicated Stocktwits account**, each with a self-rendered 1-year daily
candlestick chart. Copy is locked to the bare, neutral line:

```
$TICKER printed a new 52-week low today
```

This is the deliberate mirror of the live `stocktwits-52wk-poster`
(@Stocktwits52wHighs): same universe, same ranking axis (market cap
descending), same trickle, same safety machinery — the low side of the
same coin.

## Relationship to the existing posters

### vs. the 52-week-high poster (the parent)

Separate repo (`ethanberrk/stocktwits-52wk-lows-poster`, local
`/Users/ethanberk/stocktwits-52wk-lows-poster`), code cloned from
`stocktwits-52wk-poster` and then inverted. Nothing is shared: its own
GitHub Secrets, its own `state/posted.json`, its own Stocktwits account and
token, its own cron-job.org schedule.

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

### vs. the relative-weakness poster (the overlap)

`stocktwits-relative-weakness-poster` (@STRelativeWeakness) has been live
since 2026-07-23 and already draws from the 52-week-low universe. It is a
**different feed with a different thesis**: it ranks by Stocktwits watcher
count descending with a `MIN_WATCHERS = 5000` floor and frames each post as
a *crowded breakdown*. This poster ranks by market cap and states the fact
without a thesis.

**Decided 2026-07-27: the two feeds do NOT coordinate.** They will sometimes
post the same ticker on the same day. That is accepted — separate accounts,
separate audiences. No cross-repo state sharing will be built, because it
would couple two independent systems and create a new silent failure mode
for no editorial gain.

## What flips vs. the highs poster — exactly four things

1. **The eligibility test — lows instead of highs.** The identical Yahoo
   `yf.screen` universe (US equities, `intradaymarketcap > $1B`, sorted by
   market cap descending, paged to `_MAX_OFFSET = 3000`) already carries the
   low fields. In `src/source/yfinance_source.py`:
   - `_REQUIRED` swaps `regularMarketDayHigh` → `regularMarketDayLow` and
     `fiftyTwoWeekHigh` → `fiftyTwoWeekLow`.
   - The day-cumulative test inverts. Highs:
     `if row["regularMarketDayHigh"] + 1e-6 < row["fiftyTwoWeekHigh"]: reject`.
     Lows: `if row["regularMarketDayLow"] - 1e-6 > row["fiftyTwoWeekLow"]: reject`.
     Yahoo's `fiftyTwoWeekLow` already includes today, so equality means a
     new low was printed today.
   - `Candidate.week52_high` → `week52_low`; `HighsSource` → `LowsSource`.

   **Verification required before implementation:** a live contract test must
   confirm `yf.screen` rows actually populate `regularMarketDayLow` and
   `fiftyTwoWeekLow` (the highs poster only ever read the high fields). If a
   field is absent from screen rows, the source falls back to a per-ticker
   quote enrichment step — a known, bounded change, not a redesign.

2. **The copy.** `src/publish/base.py` `compose_post_text` returns
   `f"${st_symbol(c.ticker)} printed a new 52-week low today"`. Locked
   2026-07-27 over "hit a new" and a company-name variant. No price, percent
   or market cap in the line — those go stale between the tick and the
   reader, and the highs poster already tried and dropped the enriched form.
   Cashtags use Stocktwits symbology (`BRK.B`, not Yahoo's `BRK-B`) via the
   existing `st_symbol`.

3. **The plausibility gate.** `MAX_PLAUSIBLE_HIGHS = 500` becomes
   `MAX_PLAUSIBLE_LOWS = 2000`. The gate exists to catch a broken parser, not
   market breadth. New lows legitimately explode on broad selloff days in a
   way highs never do; at 500 the poster would halt on exactly the days it is
   most interesting. Volume control is the job of the per-tick and per-day
   caps, not the gate. Same number and same reasoning the weakness poster
   settled on.

4. **The chart is already direction-neutral** and needs no code change:
   candle colors and the last-price pill follow the data
   (`UP = #089981`, `DOWN = #F23645` in `src/chart.py`). Confirmed by the
   weakness poster, which shipped the same renderer unchanged. The flip is
   delivered as a **pinned test** asserting a downtrend renders a red closing
   candle and a red last-price pill, so future styling work cannot silently
   break the framing.

## One deliberate improvement: no tick starvation

The highs poster's `select.pick()` takes the top N by market cap up front,
and `run.py` skips any of those N whose chart fails. A name that fails
*deterministically* — the `MIN_HISTORY_DAYS = 330` recent-IPO guard being the
common case — is re-picked every tick and can zero the day's posts under
`MAX_PER_TICK = 1`. This was recorded as out-of-scope in the highs spec on
2026-07-10 and is still unfixed there.

That defect is materially more dangerous on the low side: a company that
IPO'd inside the last year and has fallen is close to the *definition* of a
stock at a 52-week low, so the top-ranked pick failing its chart is a
routine event here, not an edge case.

Fix, ported verbatim from the weakness poster (proven in production since
2026-07-20):

- `select.ranked_eligible(candidates, posted, today)` returns the **full**
  eligible list sorted by market cap descending, uncapped.
- `select.slot_count(posted, today)` returns
  `max(0, min(MAX_PER_TICK, MAX_PER_DAY - daily_count))`.
- `run.py` walks `ranked`, skipping names that fail the symbol check or the
  chart fetch, and stops once it has `slots` chartable names. A skipped name
  stays eligible for a later tick.

All fallible work still happens **before** any write-ahead intent is
recorded, preserving at-most-once posting.

## What stays identical (copied untouched)

- `MIN_MARKET_CAP = 1_000_000_000`, enforced twice — in the screen query and
  again in selection.
- Exchange-listed only (`NMS`/`NGM`/`NCM`/`NYQ`/`ASE` → NASDAQ/NYSE/AMEX);
  OTC and pink sheets excluded.
- `NAME_EXCLUDE_RE` — drops ETFs, funds, preferreds, notes, units, warrants,
  rights and acquisition corps. `quoteType` must be `EQUITY`.
- **Freshness gate**: `regularMarketTime` must fall on today's ET date. This
  makes a stale "new low today" post structurally impossible on market
  holidays and unscheduled closures, with no holiday calendar — and also
  filters stale quotes.
- `MIN_HISTORY_DAYS = 330` recent-IPO skip: a "1Y" chart of a three-month-old
  listing misleads on the way down exactly as it does on the way up.
- Chart pipeline: keyless stockanalysis.com 1Y daily history plus today's
  candle from the live quote; 800×450 TradingView-light PNG rendered
  in-process with matplotlib. `ChartError` when history is stale *and* the
  live quote is unusable — never a "new low today" post with a chart ending
  yesterday.
- Cooldown: the same ticker is blocked today and on the previous trading day
  (`state.is_blocked`; weekends are not gap days).
- Market-hours gate (`9:30`–`16:00` ET, weekdays), `--force` for local runs.
- **Write-ahead publishing**: intents recorded as `pending` and git-pushed
  (`run.py --sync-state`) before anything irreversible happens; confirmed to
  `posted` with the real `post_id` afterwards. A crash can lose a post, never
  duplicate one. `PublishError` leaves the ticker `pending`.
- Pre-post cashtag validation against the public Stocktwits symbol endpoint:
  404 skips, indeterminate (403/timeout/5xx) allows with a log.
- **`urllib`, never `requests`** — Stocktwits' CDN bot-blocks `requests`' TLS
  fingerprint (403 regardless of headers). This applies to the symbol check,
  the chart data fetch and the publisher's hand-built multipart POST.
- Publishing contract: `POST https://api.stocktwits.com/api/2/messages/create.json`,
  multipart, image in the field named `chart` (confirmed in both existing
  repos).
- Dry-run by default; `--live` without `STOCKTWITS_ACCESS_TOKEN` is a hard
  exit, never a silent downgrade.
- Nightly auditor (`scripts/verify_day.py` + `audit.yml` at 22:30 UTC
  weekdays) — re-derives truth from per-ticker history and replays the rules
  from git. Its truth check inverts to lows along with the source.
- Tick workflow shape: `workflow_dispatch` only (**no GitHub `schedule`** —
  it delivered ~27% of its slots, 7–56 minutes late, and its late fires
  compressed the trickle and burned the daily cap early), `concurrency: tick`,
  and a `if: always()` state-commit step.

## Caps

`MAX_PER_TICK = 1`, `MAX_PER_DAY = 12`, set as workflow env exactly as the
highs poster runs them today (repo defaults stay 2/20). Decided 2026-07-27:
mirror the highs feed's pacing. The 30-minute trickle also avoids the
Stocktwits duplicate filter, which returned a 422 on the highs account when
two near-identical bodies posted seconds apart.

## Account isolation (critical)

Posts go to a **new dedicated Stocktwits account** — not @Stocktwits52wHighs
(whose identity is breakouts) and not @STRelativeWeakness. Handle is Ethan's
choice, needed only at Phase 2.

**Mandatory pre-wiring check**, learned from the weakness poster's go-live:
call `account/verify` with the new token and confirm the returned username
and user id are the *new* account **before** storing it as this repo's
`STOCKTWITS_ACCESS_TOKEN`. This is the only thing standing between a
mis-pasted token and lows posting to the highs account. Posts cannot be
deleted.

## Rollout — two phases

**Phase 1 — preview (no secrets).** The tick workflow runs dry-run and the
repo holds no posting token, so it is *structurally* incapable of posting.
Each tick renders charts in-process and commits would-be posts (PNG + text)
to `output/YYYY-MM-DD/`. Ethan reviews several days of samples: are the picks
right, do the charts show the low, does the copy read well?

**Phase 2 — live.** Ethan creates the account and verifies its email (an
unverified email produced a `CORE-4302` 403 that blocked the highs poster's
first live post). Token minted, verified via `account/verify`, stored as the
repo secret. **Preview state must be cleared first**: `state.is_blocked`
covers today and the previous trading day, so leftover dry-run entries
(`post_id: null`) would make day one skip its strongest names. Then one
supervised live post is made and eyeballed — chart attached? correct
account? correct copy? — before the workflow is flipped to
`--sync-state --live` unattended.

## Scheduling

cron-job.org job POSTing `workflow_dispatch` to `tick.yml`, minutes `[15, 45]`,
hours 13–21 UTC, weekdays. Offset from the highs poster (`:00/:30`) and the
weakness poster (`:05/:35`) so the three feeds do not fire simultaneously —
this is for legibility when debugging, not a technical requirement.
Auth is a **fine-grained GitHub PAT scoped to this repo only** (Actions
read+write), stored in the job's Authorization header.

## Known inherited risk (accepted, not fixed here)

When the scheduler's PAT expires, dispatches fail with 401, cron-job.org
still reports success, and posting stops **silently**. The highs poster's PAT
lapses around 2026-10-04; this repo's will carry its own expiry. Ethan
declined a dead-man's-switch for the highs poster on 2026-07-09. This build
inherits the same gap for consistency. **Recommended follow-up (out of
scope): one alarm covering all three accounts that fails loudly when a
trading day ends with zero posts.**

## Testing

Port the highs poster's suite (83 tests) and invert the direction:

- `test_source_parse` / `test_yfinance_source`: fixtures carrying
  `regularMarketDayLow` / `fiftyTwoWeekLow`; assertions that a stock at its
  low is accepted, one above its low is rejected, and boundary equality
  counts as a new low.
- `test_select`: market-cap-descending ordering, the `$1B` floor, cooldown
  blocking, `ranked_eligible` returning the full list uncapped, `slot_count`
  arithmetic against both caps.
- `test_config`: gate at 2000.
- `test_publish`: the locked copy template, including the `BRK-B` → `BRK.B`
  cashtag mapping.
- `test_chart`: existing tests unchanged, **plus** the new pinned test that a
  downtrend renders a red closing candle and a red last-price pill.
- `test_run`: the walk-down — a deterministic `ChartError` on the top-ranked
  name must result in the *next* eligible name being posted, not an empty
  tick. This is the regression test for the starvation fix.
- `test_audit_rules`: rules replay against the lows condition.
- Contract tests (network, run manually / in CI): live `yf.screen` returning
  low fields, live chart render producing a real PNG, live Stocktwits symbol
  lookup.

The full suite must pass before Phase 1's schedule is enabled.

## Out of scope

- Cross-repo deduplication with @STRelativeWeakness (explicitly declined).
- A shared library between the three posters.
- The zero-posts dead-man's-switch (recommended as a separate project).
- A market-holiday calendar — the freshness gate covers it.
- Any change to the live highs or weakness posters.
