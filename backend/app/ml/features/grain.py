"""What a period *is*, in one place.

Every other module treats a period as an opaque integer counter and does
integer arithmetic on it - lags, folds, horizons, origins. Only this module
knows whether that counter counts months or ISO weeks, and only this module
turns a real date into one.

That was already almost true before weekly existed: `panel.month_index` and
`index_to_period` were the sole month-aware pair in the ML layer, and
`ais_preprocessing.month_key` was the sole date-to-period function in
ingestion. Weekly is those three functions taught a second vocabulary, not a
second pipeline.

**The counter is absolute, never a row position.** A series that starts late
must still land on the same index as every other series for the same week, or
origins and folds stop meaning the same thing across the panel.

**Weekly uses the ISO calendar**, so a period is `YYYY-Www` where the year is
the ISO year, not the calendar one: 29 Dec 2025 is `2026-W01`. The index is
derived from the ordinal of that week's Monday rather than from `year * 52 +
week`, because ISO years are 52 or 53 weeks long - 2026 has 53 - and the naive
form silently collides on the long ones. Round-trip and monotonicity are
asserted over a four-year span in `tests/test_grain.py`, including that
boundary.

Generic and dataset-agnostic, as `app/ml/` must be: no AIS column name appears
here, and nothing in this module reads a panel.
"""

from __future__ import annotations

from datetime import date
from typing import Final, Literal

Grain = Literal["monthly", "weekly"]

MONTHLY: Final[Grain] = "monthly"
WEEKLY: Final[Grain] = "weekly"

GRAINS: Final[tuple[Grain, ...]] = (MONTHLY, WEEKLY)

#: Spellings accepted from configuration, folded to the canonical pair. The
#: deployment `.env` already carried `AIS_PANEL_GRAIN=week` before this module
#: existed, so the short forms are read rather than rejected - but they are
#: folded here, at the edge, so no module downstream ever sees a second
#: vocabulary for the same thing.
_ALIASES: Final[dict[str, Grain]] = {
    "month": MONTHLY,
    "monthly": MONTHLY,
    "week": WEEKLY,
    "weekly": WEEKLY,
}


#: The user-facing word for one period at each grain, so a message written
#: once does not have to be rewritten when the panel grain changes. The
#: frontend keeps the same pair in `src/app/period.ts`.
_PERIOD_NOUNS: Final[dict[str, tuple[str, str]]] = {
    MONTHLY: ("month", "months"),
    WEEKLY: ("week", "weeks"),
}


def period_noun(grain: str, *, plural: bool = False) -> str:
    """What one period is called at this grain - "week" or "month"."""
    one, many = _PERIOD_NOUNS.get(normalise_grain(grain), ("period", "periods"))
    return many if plural else one


def normalise_grain(value: str) -> Grain:
    """Fold a configured spelling to the canonical grain name."""
    key = str(value).strip().lower()
    if key not in _ALIASES:
        raise ValueError(f"grain must be one of {sorted(_ALIASES)}, got {value!r}")
    return _ALIASES[key]

#: Periods in a year, per grain. 52 rather than 52.18: a seasonal period has to
#: be a whole number of observations, and the fractional part is what leap weeks
#: express instead.
PERIODS_PER_YEAR: Final[dict[str, int]] = {MONTHLY: 12, WEEKLY: 52}

#: The mandated forecast horizon, per grain. Both are six months of demand -
#: 26 weeks is the same span the monthly pipeline always covered, which is what
#: lets a weekly run be scored against the monthly record on equal terms.
HORIZON: Final[dict[str, int]] = {MONTHLY: 6, WEEKLY: 26}

#: The training floor, per grain: one complete annual cycle. Below it a
#: seasonal period cannot be estimated at all, so a fold that trains on less is
#: not evidence about a seasonal model.
MIN_TRAIN_PERIODS: Final[dict[str, int]] = {MONTHLY: 12, WEEKLY: 52}

# --------------------------------------------------------------------------
# Date -> period
# --------------------------------------------------------------------------


def period_key(value: date, grain: str) -> str:
    """The period a real date falls in.

    The one function that collapses a transaction date to a modelling period.
    Swapping the grain here is what makes the whole panel weekly.
    """
    if grain == WEEKLY:
        iso = value.isocalendar()
        return f"{iso[0]:04d}-W{iso[1]:02d}"
    return f"{value.year:04d}-{value.month:02d}"


# --------------------------------------------------------------------------
# Period <-> index
# --------------------------------------------------------------------------


def period_index(period: str, grain: str) -> int:
    """Turn a period label into a monotonic counter.

    Used instead of a date so lag arithmetic is integer arithmetic - no
    timezone, no day-of-month, no DST, and no calendar length to carry.
    """
    if grain == WEEKLY:
        iso_year, iso_week = period.split("-W")
        monday = date.fromisocalendar(int(iso_year), int(iso_week), 1)
        # Ordinal 1 is a Monday, so every Monday is 7k + 1 and the division is
        # exact. This is why the index cannot collide on a 53-week year.
        return (monday.toordinal() - 1) // 7
    year, month = period.split("-")
    return int(year) * 12 + (int(month) - 1)


def index_to_period(index: int, grain: str) -> str:
    if grain == WEEKLY:
        iso = date.fromordinal(index * 7 + 1).isocalendar()
        return f"{iso[0]:04d}-W{iso[1]:02d}"
    year, month = divmod(index, 12)
    return f"{year:04d}-{month + 1:02d}"


def is_period(value: str, grain: str) -> bool:
    """Whether `value` parses as a period at this grain. Used by the readers
    that have to tell a period label from a free-text cell."""
    try:
        period_index(value, grain)
    except (ValueError, TypeError):
        return False
    return True


def grain_of_period(value: str) -> Grain | None:
    """Which grain a period label was written at, or `None` if neither.

    The label carries its own grain: `2026-W13` is a week and `2026-03` is a
    month, and nothing else in the string is ambiguous between them. This
    exists for stored data that predates the grain being recorded alongside it
    - a run backfilled from `origins_json` must be scored on the grain it was
    trained at, not on whatever the deployment is set to today, or a monthly
    run gets measured against a 26-period window it never had.
    """
    if not isinstance(value, str):
        return None
    if is_period(value, WEEKLY):
        return WEEKLY
    if is_period(value, MONTHLY):
        return MONTHLY
    return None


# --------------------------------------------------------------------------
# Grain -> the month a period reports under
# --------------------------------------------------------------------------


def period_month(period: str, grain: str) -> str:
    """The calendar month `YYYY-MM` this period is reported under.

    A weekly forecast is produced per week and read per month, so something has
    to say which month a week belongs to. **The ISO week's Thursday decides**,
    which is the same rule that decides its ISO year: a week belongs to the
    month holding the majority of its days, and Thursday is the median day. The
    alternative - splitting a week's units across two months by day count -
    would invent a daily profile the source does not contain.
    """
    if grain != WEEKLY:
        return period
    iso_year, iso_week = period.split("-W")
    thursday = date.fromisocalendar(int(iso_year), int(iso_week), 4)
    return f"{thursday.year:04d}-{thursday.month:02d}"


def calendar_month_number(index: int, grain: str) -> int:
    """The calendar month 1-12 the period at `index` reports under.

    Monthly it is arithmetic on the counter. Weekly it is a real lookup through
    the Thursday rule, because a week's month is not a function of the week
    number alone - ISO week 5 is February in one year and January in the next.
    """
    if grain != WEEKLY:
        return index % 12 + 1
    return int(period_month(index_to_period(index, WEEKLY), WEEKLY)[5:7])


def annual_lag(grain: str) -> int:
    """Periods back to the same point in the previous year: 12 or 52."""
    return PERIODS_PER_YEAR[grain]


def periods_spanning_months(months: int, grain: str) -> int:
    """How many periods cover `months` months of demand, at this grain.

    Six months is 6 periods monthly and 26 weekly. Used where a window is
    stated in months because a plant plans in months - the horizon, the
    accuracy windows - so the same window means the same span at either grain.
    """
    if grain == WEEKLY:
        return round(months * 52 / 12)
    return months


# --------------------------------------------------------------------------
# The mandated origins
# --------------------------------------------------------------------------


def last_period_of_month(month: str, grain: str) -> str:
    """The last period at `grain` that reports under calendar `month`."""
    if grain != WEEKLY:
        return month
    probe = period_index(period_key(date(int(month[:4]), int(month[5:7]), 1), WEEKLY), WEEKLY)
    # A calendar month touches at most six ISO weeks; this window cannot miss
    # the boundary in either direction.
    weeks = [i for i in range(probe - 1, probe + 8) if period_month(index_to_period(i, WEEKLY), WEEKLY) == month]
    if not weeks:  # pragma: no cover - unreachable for a real month
        raise ValueError(f"no ISO week reports under {month}")
    return index_to_period(max(weeks), WEEKLY)


def first_period_of_month(month: str, grain: str) -> str:
    """The first period at `grain` that reports under calendar `month`.

    The partner of `last_period_of_month`. Together they turn a month-shaped
    filter - which is what a planner types, and what the API validates - into
    the index range it covers at whatever grain the panel is built at.
    """
    if grain != WEEKLY:
        return month
    probe = period_index(period_key(date(int(month[:4]), int(month[5:7]), 1), WEEKLY), WEEKLY)
    weeks = [
        i
        for i in range(probe - 1, probe + 8)
        if period_month(index_to_period(i, WEEKLY), WEEKLY) == month
    ]
    if not weeks:  # pragma: no cover - unreachable for a real month
        raise ValueError(f"no ISO week reports under {month}")
    return index_to_period(min(weeks), WEEKLY)


#: The two mandated origins, by the last period included in training.
#:
#: The monthly pair is the contract. The weekly pair is **derived** from it as
#: the last week that reports under the same month, and deriving rather than
#: typing it is what caught the off-by-one: 2025-W40 runs 29 Sep to 5 Oct, its
#: Thursday is 2 October, so it reports as October. Training through W40 would
#: have handed the weekly run an extra week of real time the monthly run never
#: saw, and every comparison between the two would have been unfair by a week.
_MONTHLY_TRAIN_ENDS: Final[tuple[str, str]] = ("2025-09", "2026-01")

ORIGIN_TRAIN_ENDS: Final[dict[str, tuple[str, str]]] = {
    MONTHLY: _MONTHLY_TRAIN_ENDS,
    WEEKLY: (
        last_period_of_month(_MONTHLY_TRAIN_ENDS[0], WEEKLY),
        last_period_of_month(_MONTHLY_TRAIN_ENDS[1], WEEKLY),
    ),
}
