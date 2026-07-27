# Backlog

Known, deliberately deferred items. Recorded here rather than lost in a
review thread. Each says what it is, why it was deferred, and what would
close it.

## Open

### `GRP-U` is a false positive of the warrant filter

`config.WARRANT_RE` gained bare `-W`/`-R`/`-U` alternatives alongside Yahoo's
actual `-WT`/`-RT`/`-UN` convention. `GRP-U` — Granite REIT's NYSE stapled-unit
line, a genuine operating REIT — is caught by the bare `-U$` branch and will
never post.

Consequence is an omission, never a wrong post, which is why it shipped.
Closing it means narrowing to the two-letter forms and re-checking against a
live screen that no real warrant slips through.

### Dedupe runs before the market-cap floor

`select.ranked_eligible` dedupes by ticker before applying
`MIN_MARKET_CAP`. If the paged screen returns the same ticker twice and the
first-seen copy reports a cap just under $1B while the duplicate reports just
over, the name is dropped entirely rather than kept.

Safe direction, vanishingly rare. Closing it means deduping after the floor
filter, or keeping the highest-cap copy rather than the first.

### Dangling docstring reference in the auditor test

`tests/test_audit_rules.py` references `test_operator_flip_would_be_caught
below`, which does not exist — the operator-flip proof was a one-off manual
mutation run during review, not a committed test. Either delete the reference
or commit a mutation test that earns it.

### `config.py` comment describes the pre-fix warrant regex

The live-verification comment reads "WARRANT_RE caught exactly DJTWW". That
was true of the NASDAQ-only pattern on 2026-07-27; the pattern has since been
widened to the dash-suffixed forms.

### The walk-down has no memory across ticks

`run.py` restarts from rank 1 every tick. Twenty *deterministically*
unchartable names at the top of the list would consume `MAX_CANDIDATE_ATTEMPTS`
on every tick all day while chartable names sat at rank 21+. Requires 20
consecutive deterministic failures; the worst case observed in design was 2.

### Log-scale charts for collapsed names

A linear y-axis compresses the recent action on a name down 90%+ over the
year — the very part the post is about. The floor is clamped at zero so
nothing renders broken, but the shape is poor. Log scale above some high/low
ratio is the fix.

### No zero-post alarm

Declined by the owner on 2026-07-27 for consistency with the two sibling
posters. Worth knowing that on the low side, "zero posts today" is a
*plausible normal outcome*, so it is indistinguishable from a silent failure —
a lapsed scheduler token, a broken screen, a dead chart source. The
recommended shape is one monitor covering all three accounts, not three
separate ones.

### The plausibility gate goes silent on a crash day

`MAX_PLAUSIBLE_LOWS = 1200` is about 43% of the screened universe. On a
March-2020-scale day, genuine breadth could reach it, `select.validate` would
raise, and every tick would exit non-zero — the feed goes dark on its most
newsworthy day.

Considered and deliberately not changed: the suggested alternative, truncating
to the top N and posting anyway, means a genuinely broken filter posts
megacaps as new 52-week lows. Posts cannot be deleted, so aborting is the safe
side. Revisit only with a gate that can tell breadth from a broken filter.

## Also latent in the sibling highs poster

These were found here and are inherited from `stocktwits-52wk-poster`, which
still carries them. Fixing them there is a separate decision.

- The screen's 3,000-row page cap with no exchange filter, giving an effective
  ~$6.6B floor rather than the $1B the config claims.
- Preferred shares and warrants passing every filter with the parent's name
  and market cap.
- Lines parked at their 52-week extreme on negligible volume re-qualifying
  indefinitely.
- The unbounded walk with no per-tick attempt limit and no job timeout.
- The live quote appended as today's candle with no check on its trade date.
- `_git_sync_state` and the workflow's commit step pushing to main without a
  branch guard.
