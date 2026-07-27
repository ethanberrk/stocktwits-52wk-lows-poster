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

    .venv/bin/python -m pytest -q            # unit tests
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
