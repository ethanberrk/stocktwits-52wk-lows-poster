from datetime import date

import config
from src import state
from src.source.base import Candidate

class ValidationError(Exception):
    """Source output looks broken; abort the tick before posting anything."""

def validate(candidates: list[Candidate]) -> None:
    if len(candidates) > config.MAX_PLAUSIBLE_LOWS:
        raise ValidationError(
            f"{len(candidates)} '52-week lows' is implausible "
            f"(gate: {config.MAX_PLAUSIBLE_LOWS}); refusing to post")

def ranked_eligible(candidates: list[Candidate], posted: list[dict],
                    today: date) -> list[Candidate]:
    """All postable candidates, LARGEST first. Not capped — run.py walks this
    list and stops once it has enough that actually chart, so an unchartable
    top-mcap name can't starve the whole tick.

    Deduped by ticker (first occurrence wins) BEFORE the sort. The screen
    pages by offset over a list Yahoo sorts by intraday market cap, so a name
    sitting on a page boundary can drift one rank between requests and come
    back on two pages. Both copies would otherwise pass every filter, both
    chart, both post — two undeletable duplicate posts for the same ticker."""
    deduped = []
    seen: set[str] = set()
    for c in candidates:
        if c.ticker in seen:
            continue
        seen.add(c.ticker)
        deduped.append(c)
    eligible = [c for c in deduped
                if c.market_cap >= config.MIN_MARKET_CAP
                and not state.is_blocked(c.ticker, posted, today)]
    eligible.sort(key=lambda c: c.market_cap, reverse=True)
    return eligible


def slot_count(posted: list[dict], today: date) -> int:
    """How many posts this tick may still make: bounded by the per-tick cap
    and the day's remaining budget."""
    remaining_today = config.MAX_PER_DAY - state.daily_count(posted, today)
    return max(0, min(config.MAX_PER_TICK, remaining_today))
