# Stocktwits 52-Week-Lows Poster — Design

**Date:** 2026-07-27
**Status:** v3 — scope trimmed by owner decision; pending spec review

> **Scope note.** v2 grew a set of editorial rules (post only on down days,
> only below the open, only on a confirmed break of the prior low). The owner
> cut them on 2026-07-27: *"we're overthinking this — the idea is to unbundle
> a screen a trader might use to find 52-week lows. Replicate the 52w high
> stream but inverse it."* A real screen shows every stock at a new low,
> including ones that dipped and bounced. This spec is the straight inverse,
> plus two filters that exclude instruments that are not stocks.

## Goal

Every 30 minutes during market hours, post the **largest** US common stocks
over $1B market cap that printed a **new 52-week low today**, to a **new
dedicated Stocktwits account**, each with a self-rendered 1-year daily
candlestick chart. Copy is locked to:

```
$TICKER printed a new 52-week low today
```

The mirror of the live `stocktwits-52wk-poster` (@Stocktwits52wHighs): same
universe, same market-cap ranking, same trickle, same safety machinery.

## Repo strategy

Separate repo (`ethanberrk/stocktwits-52wk-lows-poster`), code cloned from
`stocktwits-52wk-poster` and inverted. Nothing shared: own GitHub Secrets, own
`state/posted.json`, own Stocktwits account and token, own cron-job.org
schedule. Rationale (approach A of three considered, decided 2026-07-27): the
highs poster is live; structural isolation means nothing built here can break
it. Accepted cost, same as the RS→RW split: an upstream break must be fixed in
each repo.

Two practical notes:

- **Clone from the highs repo, not the weakness repo.** The weakness poster's
  `src/chart.py` diverged — it dropped the `st_symbol` dash→dot mapping and
  dropped the `ChartError` raised when history is stale *and* the live quote is
  unusable.
- **Pull `origin/main` first.** The local highs checkout is at `b923605`
  (2026-07-10) and its README still describes the retired chart-img service.

## Relationship to @STRelativeWeakness

The weakness poster (live since 2026-07-23) already draws from the 52-week-low
universe, but ranks by Stocktwits watcher count with a 5,000-watcher floor and
frames posts as *crowded breakdowns*. Different feed, different thesis.

**Decided: the two do not coordinate.** They will sometimes post the same
ticker the same day. Accepted — separate accounts, separate audiences.
Verified harmless: separate repos, output directories, state files and tokens;
rate limits are per-token; the shared runner IP pool touches only the
unauthenticated symbol lookup, called once per pick.

## The four flips

1. **The eligibility test.** In `src/source/yfinance_source.py`, `_REQUIRED`
   swaps `regularMarketDayHigh` → `regularMarketDayLow` and
   `fiftyTwoWeekHigh` → `fiftyTwoWeekLow`. The day-cumulative test inverts:

   ```python
   # highs: if row["regularMarketDayHigh"] + 1e-6 < row["fiftyTwoWeekHigh"]: reject
   if row["regularMarketDayLow"] - 1e-6 > row["fiftyTwoWeekLow"]:
       return None
   ```

   `Candidate.week52_high` → `week52_low`; `HighsSource` → `LowsSource`.

   Verified live 2026-07-27: Yahoo's `fiftyTwoWeekLow` includes today (across
   1,207 filtered rows, zero had `regularMarketDayLow` strictly below it, and
   the equality cases are exactly that day's new lows), and `yf.screen` rows do
   carry both low fields — 13 of 3,000 rows lack them, the same 13 that lack
   the high fields, already covered by the existing null check.

2. **The copy.** `compose_post_text` returns
   `f"${st_symbol(c.ticker)} printed a new 52-week low today"`. No price,
   percent or market cap — those go stale between the tick and the reader, and
   the highs poster already tried and dropped the enriched form. Cashtags use
   Stocktwits symbology (`BRK.B`, not `BRK-B`).

3. **The broken-feed gate.** `MAX_PLAUSIBLE_HIGHS = 500` →
   `MAX_PLAUSIBLE_LOWS = 1200`. New lows legitimately run far higher than new
   highs on a selloff, and at 500 the poster would halt on its best content
   days. 1,200 is ~43% of the universe: unreachable by real breadth, tripped by
   a filter that stopped filtering. (Not the weakness poster's 2,000 — that
   gates the unbounded WSJ all-issues feed, a much larger universe.)

4. **The chart needs no change.** Candle colours and the last-price pill
   follow the data (`src/chart.py:85`, `:117`), so a low chart renders red
   without a code change — confirmed by the weakness poster shipping the same
   renderer. Note this cuts both ways: a stock that dips to a new low and
   rallies closes **green** under a "new low" headline. Accepted as part of
   showing the screen as it is.

## Two filters: things that are not stocks

A straight mirror posts instruments no trader's 52-week-low screen would show.
Both are asymmetries — invisible on the high side, common on the low side,
because these lines sit near their lows structurally and barely trade.

**Preferred shares, warrants, rights and units.** `NAME_EXCLUDE_RE` matches
words like "Pfd"/"Preferred"/"Warrants", but Yahoo gives these rows the
**parent common's `longName`**, so it never fires — and they inherit the
parent's market cap, so they rank near the top of a size-ranked feed.
Measured live 2026-07-27: of 65 dash-tickers surviving the exchange and
`EQUITY` filters, `NAME_EXCLUDE_RE` excluded exactly **one**. `WFC-PC` came
through at $113.7B, `ALL-PH` at $29.1B (**on that day's new-lows list**),
`KEY-PK` at $18.0B. The warrant `DJTWW` charts cleanly and its Stocktwits
symbol resolves 200 — nothing downstream stops it.

Add to the source filter:

```python
PREFERRED_RE = re.compile(r"-P[A-Z]?$")        # WFC-PC, ALL-PH, KEY-PK
WARRANT_RE   = re.compile(r"^[A-Z]{4}(W|R|U)$")  # DJTWW, units, rights
```

Legitimate dual-class lines (`BRK-B`, `PBR-A`, `HEI-A`, `LEN-B`, `UHAL-B`)
must survive both — covered by tests.

**Ghost volume.** `TAP-A` on 2026-07-27 traded **116 shares** all day, with
`dayHigh == dayLow == previousClose == fiftyTwoWeekLow == 39.51` and a
today-stamped quote. It passes the freshness gate and ties its 52-week low, so
it qualifies every day it prints one flat trade — and the 2-day cooldown
returns it every other day indefinitely. Add
`regularMarketPrice * regularMarketVolume >= $5,000,000`. Every legitimate
name on the verified list clears it by a wide margin.

## One universe fix (not a new rule)

The highs poster's screen query has no exchange filter and pages to
`_MAX_OFFSET = 3000`. Measured live 2026-07-27: the query returns exactly
3,000 rows — the cap is hit — of which **1,739 are pink sheets** discarded
later, leaving 1,261 usable names. The 3,000th row is at **$6.59B**, so the
effective floor is ~$6.6B, not the $1B the config claims.

The highs poster gets away with this because ~130 names hit new highs on an
ordinary day and it needs 12. Only 7 hit new lows the same day.

One line in the query makes the stated floor real:

```python
yf.EquityQuery("is-in", ["exchange", "NMS", "NYQ", "NGM", "NCM", "ASE"])
```

Verified: **2,766 rows down to a true $1.001B floor**, all on allowed
exchanges, no truncation. This removes nothing the poster could ever have
posted — pink sheets are discarded either way — it just stops them consuming
the row budget.

## The walk-down (the one behavioural fix)

The highs poster's `select.pick()` takes the top N by market cap up front, so a
name that fails its chart *deterministically* is re-picked every tick and can
zero the day under `MAX_PER_TICK = 1`. Recorded as out-of-scope in the highs
spec on 2026-07-10, still unfixed there.

Not theoretical here. On 2026-07-27 the two highest-ranked lows were **SPCX**
(SpaceX, $1.47T, first traded ~2026-06-09) and **SKHY** (SK hynix, $1.03T,
first traded ~2026-07-07). Both trip the `MIN_HISTORY_DAYS = 330` recent-IPO
guard. Without the walk-down the feed posts **nothing that day**. Recent
listings that have fallen are close to the definition of a stock at a 52-week
low.

Ported from the weakness poster (`src/select.py:19-36`, `run.py:31-51`, in
production since 2026-07-20), ranking axis changed to market cap:

- `select.ranked_eligible(...)` — full eligible list, market cap descending,
  uncapped.
- `select.slot_count(...)` — `max(0, min(MAX_PER_TICK, MAX_PER_DAY - daily_count))`.
- `run.py` walks `ranked`, skipping names that fail the symbol check or chart
  fetch, stopping at `slots` chartable names. A skipped name stays eligible.

**Bounded**, unlike the parent port: per candidate the symbol check allows 15s
(`src/stocktwits.py:27`) and each `get_json` retries 4× at 12s
(`src/fetch.py:14-27`) — ~110s worst case per name. A lows list on a selloff
day is hundreds long, and `concurrency: {group: tick, cancel-in-progress:
false}` means a stuck run queues later dispatches until GitHub drops them, so
the feed goes dark silently. Therefore `MAX_CHART_ATTEMPTS = 20` per tick
(exhausting it logs and ends the tick cleanly) and `timeout-minutes: 15` on
the job.

All fallible work still happens **before** any write-ahead intent is recorded,
preserving at-most-once posting.

## Three small correctness fixes

Each is one condition, and each prevents a wrong chart under a factual claim:

1. **Require the live quote to be dated today** before appending it as today's
   candle. `chart.py:51-60` appends whenever history ends before today and the
   quote has `p` and `o`, with no date check. Stockanalysis returned
   `"td": "2026-07-24"` for `TAP.A` on 2026-07-27 — that would have produced a
   candle *dated today* built from Friday's prices. Require
   `quote["td"] == today.isoformat()`, else `ChartError`.
2. **Clamp the y-axis floor at zero.** `chart.py:110-113` computes
   `ylim(lo - pad, hi + pad)`; on a collapsed name `lo - pad` goes negative.
3. **Guard the state-commit step** as
   `if: always() && github.ref == 'refs/heads/main'` (the weakness poster's
   hardening). The parent's bare `if: always()` lets a manual dispatch on a
   feature branch push state to main.

## What stays identical

`MIN_MARKET_CAP = 1_000_000_000` (enforced in the query and again in
selection), `NAME_EXCLUDE_RE`, `quoteType == "EQUITY"`, exchange-listed only,
the freshness gate (`regularMarketTime` must fall on today's ET date — makes
holiday posts structurally impossible with no calendar),
`MIN_HISTORY_DAYS = 330`, the chart pipeline (keyless stockanalysis.com 1Y
history + today's candle from the live quote, 800×450 TradingView-light PNG),
the 2-day cooldown, the market-hours gate, write-ahead publishing (`pending`
intents git-pushed before anything irreversible; a crash can lose a post,
never duplicate one), pre-post cashtag validation (404 skips, indeterminate
allows), **`urllib` not `requests`** (Stocktwits' CDN bot-blocks `requests`'
TLS fingerprint), dry-run by default with `--live` requiring a token, the
nightly auditor, and `workflow_dispatch`-only ticks (GitHub `schedule`
delivered ~27% of its slots, 7–56 min late).

**Known hole, inherited:** `state.previous_trading_day` (`state.py:38-42`)
skips weekends only, so after a market holiday the cooldown collapses to one
day. Accepted, matching the parent.

## Caps and expected volume

`MAX_PER_TICK = 1`, `MAX_PER_DAY = 12` as workflow env, exactly as the highs
poster runs them (repo defaults stay 2/20).

**Expect well under the cap.** With 13 in-market ticks a day, supply binds
before the cap does. On 2026-07-27, a quiet day, the corrected chain produced
7 candidates before the junk filters, the top 2 unchartable. Realistically
**2–6 posts on an ordinary day, more on a selloff, zero on a strong day.**
Not a malfunction.

## The auditor — about eight edits, not one

`scripts/verify_day.py`: `df["High"]` → `df["Low"]` (two sites),
`prior.max()` → `prior.min()` (`:107-132`), the margin expression, the detail
strings, `:162` (`"52-week high" in text`), and the module docstring (`:15`).

**The tolerance must invert too**: `day_high >= prior_max * (1 - TRUTH_TOLERANCE)`
becomes `day_low <= prior_min * (1 + TRUTH_TOLERANCE)`. Keeping `(1 - TOL)`
turns a permissive tolerance into a stricter one and produces false FAILs on
every post.

## Publishing contract

`POST https://api.stocktwits.com/api/2/messages/create.json`, multipart, image
in the field named **`chart`**. It works in production on both existing
accounts, but both publishers carry the comment that the field name is
unconfirmed against current Stocktwits docs
(`src/publish/stocktwits_pub.py:18-19`), and a 200 plus a message id does not
prove the image attached. Phase 2's human eyeball is the real check.

Two launch cautions from the highs account's go-live — a `422` from
Stocktwits' duplicate filter when near-identical bodies posted seconds apart,
and a `CORE-4302` 403 from an unverified account email — are the owner's
operational history and are **not** corroborated in either repo. Flagged as
unverified.

## Account isolation (critical)

A **new dedicated Stocktwits account** — not @Stocktwits52wHighs (whose
identity is breakouts) and not @STRelativeWeakness. Handle is the owner's
choice, needed only at Phase 2.

**Mandatory pre-wiring check:** call `account/verify` with the new token and
confirm the returned username and user id are the *new* account **before**
storing it as this repo's `STOCKTWITS_ACCESS_TOKEN`. This is the only thing
between a mis-pasted token and lows posting to the highs account. Posts cannot
be deleted.

## Rollout

**Phase 1 — preview (no secrets).** The workflow runs dry-run and the repo
holds no token, so it is structurally incapable of posting. Each tick commits
would-be posts (PNG + text) to `output/YYYY-MM-DD/`. Review several days:
right picks, charts that show the low, copy that reads well, and no preferreds
or ghost-volume lines.

**Phase 2 — live.** Owner creates the account and verifies its email. Token
minted, verified via `account/verify`, stored as the repo secret. **Preview
state must be cleared first** — `state.is_blocked` covers today and the
previous trading day, so leftover dry-run entries (`post_id: null`) would make
day one skip its strongest names. One supervised live post is eyeballed
(chart attached? correct account? correct copy?) before the workflow is
flipped to `--sync-state --live` unattended.

## Scheduling

cron-job.org job POSTing `workflow_dispatch` to `tick.yml`, minutes `[15, 45]`,
hours 13–21 UTC, weekdays — 13 in-market ticks. Offset from the highs poster
(`:00/:30`) and the weakness poster (`:05/:35`) so the three do not fire
together; for debugging legibility, not a technical requirement. Auth is a
**fine-grained GitHub PAT scoped to this repo only** (Actions read+write) in
the job's Authorization header.

## Known inherited risk (accepted)

When the scheduler's PAT expires, dispatches fail with 401, cron-job.org still
reports success, and posting stops **silently**. The highs poster's PAT lapses
around 2026-10-04; this repo's will carry its own.

The risk is sharper here — "zero posts today" is a plausible normal outcome on
the low side, so it is indistinguishable from a silent failure. **Owner
decision 2026-07-27: skip the dead-man's-switch, match the other two
accounts.** Top recommendation for a follow-up project covering all three
feeds.

## Testing

Port the highs poster's suite (83 tests) and extend:

- **Source**: fixtures with `regularMarketDayLow` / `fiftyTwoWeekLow` /
  `regularMarketVolume`; the low test at and around the boundary; preferred
  rejection (`WFC-PC`, `ALL-PH`, `KEY-PK`) with dual-class survival (`BRK-B`,
  `PBR-A`, `HEI-A`); warrant rejection (`DJTWW`); the $5M dollar-volume floor
  (`TAP-A` at 116 shares).
- **Select**: market-cap-descending ordering, the $1B floor, cooldown
  blocking, `ranked_eligible` uncapped, `slot_count` arithmetic.
- **Config**: the gate at 1200.
- **Publish**: the locked copy template including `BRK-B` → `BRK.B`.
- **Chart**: existing tests, plus the quote-date check and the non-negative
  y-axis floor.
- **Run**: the walk-down — a deterministic `ChartError` on the top-ranked name
  must result in the *next* eligible name posting, not an empty tick — plus
  `MAX_CHART_ATTEMPTS` terminating a walk cleanly.
- **Audit rules**: replay against the lows condition with the inverted
  tolerance.
- **Contract (network)**: live `yf.screen` with the exchange filter returning a
  true $1B floor and populated low fields; live chart render producing a real
  PNG; live Stocktwits symbol lookup.

The full suite must pass before Phase 1's schedule is enabled.

## Out of scope

- **Editorial selection rules** — down-day, below-open, and confirmed-break
  filters were designed in v2 and cut by the owner on 2026-07-27. A real
  screen shows stocks that dipped and bounced; so does this feed.
- Cross-repo deduplication with @STRelativeWeakness (declined).
- A shared library between the three posters.
- The zero-posts dead-man's-switch (declined; recommended as a separate
  project covering all three accounts).
- Log-scale charts for names down 90%+ over the year, where a linear axis
  compresses the recent action the post is about.
- Same-company deduplication (`BRK-A` and `BRK-B` can both post, on different
  days).
- A minimum candle-count check — `MIN_HISTORY_DAYS` checks only the first
  date, so a sparse history can render a thin chart labelled "1D · 1Y".
- A market-holiday calendar.
- Any change to the live highs or weakness posters. **Note:** the universe
  truncation, the preferred/warrant leak, the ghost-volume case, the unbounded
  walk, the quote-date gap and the missing branch guard are all latent in the
  highs poster too. Fixing them there is a separate decision.
