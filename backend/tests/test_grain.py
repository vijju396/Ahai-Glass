"""The grain module, asserted rather than assumed.

`app/ml/features/grain.py` is the only module that knows what a period is, so
every other module's integer arithmetic is only correct if this one is. These
tests are the reason its docstring is allowed to make claims.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pytest

from app.ml.features import grain as G


class TestNormalisation:
    def test_it_accepts_both_spellings_of_each_grain(self) -> None:
        assert G.normalise_grain("week") == G.WEEKLY
        assert G.normalise_grain("weekly") == G.WEEKLY
        assert G.normalise_grain("month") == G.MONTHLY
        assert G.normalise_grain("monthly") == G.MONTHLY

    def test_it_ignores_case_and_surrounding_space(self) -> None:
        assert G.normalise_grain("  Weekly ") == G.WEEKLY

    def test_it_refuses_anything_else(self) -> None:
        """A misspelled grain must stop the process, not silently pick one."""
        with pytest.raises(ValueError, match="grain must be one of"):
            G.normalise_grain("daily")


class TestIndexRoundTrip:
    """The claim the rest of the ML layer rests on: label -> index -> label is
    the identity, and the index rises strictly with time."""

    def test_weekly_round_trips_over_four_years(self) -> None:
        # Every real ISO week from 2024 to 2027 inclusive, generated from dates
        # rather than from a year x week product, so no non-existent week
        # (2025-W53) is invented and no real one (2026-W53) is missed.
        monday = date(2024, 1, 1)
        seen = []
        while monday <= date(2027, 12, 27):
            period = G.period_key(monday, G.WEEKLY)
            index = G.period_index(period, G.WEEKLY)
            assert G.index_to_period(index, G.WEEKLY) == period
            seen.append((period, index))
            monday += timedelta(days=7)

        assert len(seen) == 209
        indices = [i for _, i in seen]
        assert indices == sorted(indices)
        assert len(set(indices)) == len(indices), "two weeks share an index"
        # Consecutive weeks are consecutive integers - the property that makes
        # a lag of 52 mean "a year back" rather than "roughly a year back".
        assert all(b - a == 1 for a, b in zip(indices, indices[1:]))

    def test_the_fifty_three_week_year_does_not_collide(self) -> None:
        """2026 has 53 ISO weeks. `year * 52 + week` would put 2026-W53 and
        2027-W01 on the same index; deriving from the Monday's ordinal cannot."""
        assert G.period_index("2026-W53", G.WEEKLY) + 1 == G.period_index(
            "2027-W01", G.WEEKLY
        )

    def test_the_iso_year_is_not_the_calendar_year(self) -> None:
        assert G.period_key(date(2025, 12, 29), G.WEEKLY) == "2026-W01"

    def test_monthly_round_trips(self) -> None:
        for year in range(2024, 2028):
            for month in range(1, 13):
                period = f"{year:04d}-{month:02d}"
                index = G.period_index(period, G.MONTHLY)
                assert G.index_to_period(index, G.MONTHLY) == period

    def test_is_period_rejects_free_text(self) -> None:
        assert G.is_period("2026-W05", G.WEEKLY)
        assert not G.is_period("not a period", G.WEEKLY)
        assert not G.is_period("", G.MONTHLY)


class TestTheThursdayRule:
    def test_a_week_reports_under_the_month_holding_its_thursday(self) -> None:
        # 2025-W40 runs 29 Sep - 5 Oct; its Thursday is 2 October.
        assert G.period_month("2025-W40", G.WEEKLY) == "2025-10"

    def test_monthly_periods_are_their_own_month(self) -> None:
        assert G.period_month("2026-03", G.MONTHLY) == "2026-03"

    def test_every_week_lands_in_exactly_one_month(self) -> None:
        """No week is split, so month totals add back to the horizon total
        exactly - the property the six-month roll-up depends on."""
        monday = date(2024, 1, 1)
        months: Counter[str] = Counter()
        weeks = 0
        while monday <= date(2026, 12, 28):
            months[G.period_month(G.period_key(monday, G.WEEKLY), G.WEEKLY)] += 1
            weeks += 1
            monday += timedelta(days=7)
        assert sum(months.values()) == weeks
        assert set(months.values()) <= {4, 5}, "a month with 3 or 6 weeks"

    def test_calendar_month_number_is_a_real_lookup_at_weekly(self) -> None:
        """ISO week 5 is not the same calendar month every year, so the number
        cannot be arithmetic on the index."""
        assert G.calendar_month_number(
            G.period_index("2026-W05", G.WEEKLY), G.WEEKLY
        ) == 1
        assert G.calendar_month_number(
            G.period_index("2025-W05", G.WEEKLY), G.WEEKLY
        ) == 1
        assert G.calendar_month_number(
            G.period_index("2026-01", G.MONTHLY), G.MONTHLY
        ) == 1


class TestSpansAndLags:
    def test_the_annual_lag_is_one_cycle(self) -> None:
        assert G.annual_lag(G.MONTHLY) == 12
        assert G.annual_lag(G.WEEKLY) == 52

    def test_six_months_is_six_periods_or_twenty_six(self) -> None:
        assert G.periods_spanning_months(6, G.MONTHLY) == 6
        assert G.periods_spanning_months(6, G.WEEKLY) == 26

    def test_the_mandated_horizon_matches_that_span(self) -> None:
        for name in G.GRAINS:
            assert G.HORIZON[name] == G.periods_spanning_months(6, name)

    def test_the_training_floor_is_one_annual_cycle(self) -> None:
        for name in G.GRAINS:
            assert G.MIN_TRAIN_PERIODS[name] == G.PERIODS_PER_YEAR[name]


class TestMonthBoundaries:
    def test_first_and_last_bracket_the_month(self) -> None:
        first = G.first_period_of_month("2026-01", G.WEEKLY)
        last = G.last_period_of_month("2026-01", G.WEEKLY)
        lo = G.period_index(first, G.WEEKLY)
        hi = G.period_index(last, G.WEEKLY)
        assert lo <= hi
        # Everything between them reports under the month, and the periods on
        # either side do not - which is what makes a month-shaped filter
        # convertible to an index range without losing or gaining a week.
        for i in range(lo, hi + 1):
            assert G.period_month(G.index_to_period(i, G.WEEKLY), G.WEEKLY) == "2026-01"
        for i in (lo - 1, hi + 1):
            assert G.period_month(G.index_to_period(i, G.WEEKLY), G.WEEKLY) != "2026-01"

    def test_monthly_boundaries_are_the_month_itself(self) -> None:
        assert G.first_period_of_month("2026-01", G.MONTHLY) == "2026-01"
        assert G.last_period_of_month("2026-01", G.MONTHLY) == "2026-01"

    def test_it_holds_across_a_year_boundary_and_a_leap_february(self) -> None:
        for month in ("2024-02", "2024-12", "2025-01", "2026-12", "2027-01"):
            first = G.first_period_of_month(month, G.WEEKLY)
            last = G.last_period_of_month(month, G.WEEKLY)
            assert G.period_month(first, G.WEEKLY) == month
            assert G.period_month(last, G.WEEKLY) == month


class TestMandatedOrigins:
    def test_the_weekly_origins_are_derived_from_the_monthly_contract(self) -> None:
        """Typing the weekly pair by hand is what the derivation prevents:
        2025-W40's Thursday is 2 October, so training through it would hand the
        weekly run a week of real time the monthly run never saw."""
        monthly = G.ORIGIN_TRAIN_ENDS[G.MONTHLY]
        weekly = G.ORIGIN_TRAIN_ENDS[G.WEEKLY]
        assert monthly == ("2025-09", "2026-01")
        assert weekly == ("2025-W39", "2026-W05")
        for month, week in zip(monthly, weekly):
            assert G.period_month(week, G.WEEKLY) == month
            assert week == G.last_period_of_month(month, G.WEEKLY)

    def test_the_week_after_each_cut_off_is_already_the_next_month(self) -> None:
        for week in G.ORIGIN_TRAIN_ENDS[G.WEEKLY]:
            nxt = G.index_to_period(G.period_index(week, G.WEEKLY) + 1, G.WEEKLY)
            assert G.period_month(nxt, G.WEEKLY) != G.period_month(week, G.WEEKLY)
