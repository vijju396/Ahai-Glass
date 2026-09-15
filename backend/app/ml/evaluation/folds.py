"""Rolling-origin fold construction.

Chronological only. There is no random-split code path in this module or
anywhere else in the project, by design.

**Why the reference fold sizing could not be ported as-is.** Sodexo's
`rolling_folds` (`validation_plan.py:39-51`) requires
`length >= max(30, validation_size * 2) + validation_size * 3`. Its `30` is a
half-day-grain constant - 30 slots is 15 days. At AIS's monthly grain with a
six-month horizon the same formula demands 48 months of history; the panel has
**28** (2024-04 .. 2026-07, measured). Three non-overlapping expanding-window
folds are therefore not affordable, and pretending otherwise by shrinking the
horizon would evaluate a model on a plan nobody asked for.

So the sizing constant is re-derived for this grain rather than copied, and the
two origins `docs/ARCHITECTURE.md` §7 mandates are named constants:

| Origin | Train through | Validate | Train months |
|---|---|---|---|
| `primary` | 2025-09 | 2025-10 .. 2026-03 | 18 |
| `second` | 2026-01 | 2026-02 .. 2026-07 | 22 |

Their validation windows **overlap** on 2026-02 and 2026-03. That is a real
property of the mandate, not a bug, and it is why `aggregate_test_points`
exists: averaging the two origins' metrics would count those two months twice.
See `docs/DECISIONS.md` D-038.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.ml.features.panel import index_to_period, month_index

#: The mandated horizon. Six months, no retraining between them.
DEFAULT_HORIZON = 6

#: Mandated origins, by the last period included in training.
PRIMARY_TRAIN_END = "2025-09"
SECOND_TRAIN_END = "2026-01"

#: The training floor at monthly grain. Twelve months is one complete annual
#: cycle - below it a seasonal period of 12 cannot even be estimated, so a fold
#: that trains on less is not evidence about a seasonal model. This replaces
#: Sodexo's `30`, which is a count of half-day slots and means nothing here.
MIN_TRAIN_PERIODS = 12


@dataclass(frozen=True)
class Origin:
    """One chronological origin: train through `train_end_index`, forecast the
    `horizon` periods after it.

    Indices are absolute month counters (`app.ml.features.panel.month_index`),
    not row positions, so an origin is meaningful independently of how many rows
    a particular series happens to have.
    """

    name: str
    fold_index: int
    train_start_index: int
    train_end_index: int
    validation_start_index: int
    validation_end_index: int
    mandated: bool = False

    @property
    def horizon(self) -> int:
        return self.validation_end_index - self.validation_start_index + 1

    @property
    def train_periods(self) -> int:
        return self.train_end_index - self.train_start_index + 1

    @property
    def train_end_period(self) -> str:
        return index_to_period(self.train_end_index)

    @property
    def validation_periods(self) -> tuple[str, ...]:
        return tuple(
            index_to_period(i)
            for i in range(self.validation_start_index, self.validation_end_index + 1)
        )

    def horizon_of(self, period_index: int) -> int | None:
        """1-based steps ahead of the origin, or None if outside the window."""
        if not self.validation_start_index <= period_index <= self.validation_end_index:
            return None
        return period_index - self.train_end_index

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "fold_index": self.fold_index,
            "train_start_period": index_to_period(self.train_start_index),
            "train_end_period": self.train_end_period,
            "train_periods": self.train_periods,
            "validation_start_period": index_to_period(self.validation_start_index),
            "validation_end_period": index_to_period(self.validation_end_index),
            "horizon": self.horizon,
            "mandated": self.mandated,
        }


def mandated_origins(
    panel_start_index: int,
    panel_end_index: int,
    *,
    horizon: int = DEFAULT_HORIZON,
) -> list[Origin]:
    """The two origins `docs/ARCHITECTURE.md` §7 requires, where they fit.

    An origin is returned only if the panel actually contains its full
    validation window and at least `MIN_TRAIN_PERIODS` of training history. A
    mandate that the data cannot satisfy is dropped with the caller able to see
    it is missing, rather than silently truncated to a shorter horizon.
    """
    origins: list[Origin] = []
    for fold_index, (name, train_end) in enumerate(
        (("primary", PRIMARY_TRAIN_END), ("second", SECOND_TRAIN_END))
    ):
        train_end_index = month_index(train_end)
        validation_end = train_end_index + horizon
        if train_end_index < panel_start_index or validation_end > panel_end_index:
            continue
        if train_end_index - panel_start_index + 1 < MIN_TRAIN_PERIODS:
            continue
        origins.append(
            Origin(
                name=name,
                fold_index=fold_index,
                train_start_index=panel_start_index,
                train_end_index=train_end_index,
                validation_start_index=train_end_index + 1,
                validation_end_index=validation_end,
                mandated=True,
            )
        )
    return origins


def build_origins(
    panel_start_index: int,
    panel_end_index: int,
    *,
    horizon: int = DEFAULT_HORIZON,
    min_train_periods: int = MIN_TRAIN_PERIODS,
    max_origins: int = 2,
    include_mandated: bool = True,
) -> list[Origin]:
    """Expanding-window origins, oldest first.

    The mandated origins come first when they fit. Additional origins are then
    generated by walking backwards from the panel end in `horizon`-sized steps,
    skipping any whose validation window duplicates one already present and any
    whose training window is shorter than `min_train_periods`.

    **`max_origins` defaults to 2 - the mandated pair - on purpose.** Measured
    on the real panel, adding a third origin (train through 2025-07) takes the
    total test periods from 12 to 18 while the *distinct* test periods stay at
    12: four of its six validation months are already covered. It would raise
    the reported fold count without adding independent evidence, which is the
    kind of number that looks like rigour and is not. Raise `max_origins`
    deliberately if a longer panel later makes a third origin genuinely
    disjoint; `aggregate_test_points` will show whether it is.

    Returns `[]` when the panel cannot support a single honest origin. That is a
    real answer - the caller reports "not evaluated" rather than inventing a
    fold.
    """
    origins: list[Origin] = []
    if include_mandated:
        origins.extend(mandated_origins(panel_start_index, panel_end_index, horizon=horizon))

    taken = {(o.validation_start_index, o.validation_end_index) for o in origins}
    validation_end = panel_end_index
    while len(origins) < max_origins:
        validation_start = validation_end - horizon + 1
        train_end_index = validation_start - 1
        if train_end_index - panel_start_index + 1 < min_train_periods:
            break
        key = (validation_start, validation_end)
        if key not in taken:
            taken.add(key)
            origins.append(
                Origin(
                    name=f"generated_{train_end_index}",
                    fold_index=-1,
                    train_start_index=panel_start_index,
                    train_end_index=train_end_index,
                    validation_start_index=validation_start,
                    validation_end_index=validation_end,
                )
            )
        validation_end -= horizon

    origins.sort(key=lambda o: o.train_end_index)
    return [
        Origin(
            name=o.name,
            fold_index=index,
            train_start_index=o.train_start_index,
            train_end_index=o.train_end_index,
            validation_start_index=o.validation_start_index,
            validation_end_index=o.validation_end_index,
            mandated=o.mandated,
        )
        for index, o in enumerate(origins)
    ]


def fast_holdout_origin(origins: Iterable[Origin]) -> Origin | None:
    """The single origin an expensive model is evaluated on.

    Sodexo sizes its fast holdout to consume the same *total* test rows a
    3-fold CV would (`validation_plan.py:16-25`), so `validation_points` stays
    comparable between a CV-evaluated model and a holdout-evaluated one. That
    arithmetic does not survive the move to monthly grain: matching three
    six-month folds would need an eighteen-month validation window, and an
    eighteen-month-ahead forecast is not the six-month plan being evaluated.

    AIS therefore keeps the horizon honest and gives up the row-count
    comparability, using the **latest** origin - the one with the most training
    history. `validation_points` then differs between evaluation modes, the
    leaderboard labels which mode produced each row, and metrics are never
    blended across modes (`docs/DECISIONS.md` D-037).
    """
    ordered = sorted(origins, key=lambda o: o.train_end_index)
    return ordered[-1] if ordered else None


def aggregate_test_points(origins: Iterable[Origin]) -> tuple[int, int]:
    """`(total_test_periods, distinct_test_periods)` across origins.

    The two differ whenever validation windows overlap - which the mandated
    pair does, on 2026-02 and 2026-03. A caller that averages per-origin
    metrics weights those two months twice; a caller that pools the underlying
    residuals over distinct `(series, period)` pairs does not. This function
    exists so the difference is visible rather than assumed away.
    """
    total = 0
    distinct: set[int] = set()
    for origin in origins:
        span = range(origin.validation_start_index, origin.validation_end_index + 1)
        total += len(span)
        distinct.update(span)
    return total, len(distinct)


def smallest_fold_train_size(
    length: int, *, folds: int = 3, validation_size: int = DEFAULT_HORIZON
) -> int:
    """The training rows the FIRST rolling-origin fold will actually see.

    Sodexo's `smallest_fold_train_size` (`validation_plan.py:28-36`):
    eligibility and seasonal-period selection are checked against this, not the
    full window, because a period that only fits the full series makes every
    individual fold's fit fail at runtime.

    Lives here rather than in `seasonality.py` so fold arithmetic has exactly
    one owner - the lesson of `docs/DECISIONS.md` D-036.
    """
    candidate = length - validation_size * folds
    return candidate if candidate > 0 else length
