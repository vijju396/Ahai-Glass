"""Stated vs observed lead time: the joins, the exclusions, and what it refuses.

Three of these guard measured defects in the real files rather than
hypotheticals:

- Location Master's last row has no branch name and carries a `Service Factor`
  of 225, which is a column sum. Letting it through would put 225 into a
  reorder-point formula as a z-score.
- 216 order lines produce a negative or absurd duration, the worst being a
  despatch dated 2002 against a 2025 order.
- 285,995 lines are invoiced *before* despatch, so Order -> Despatch -> Invoice
  is not a sequence and must not be averaged into one.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from app.domain.ais import lead_time_observed as O


def _master(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _csv(text: str) -> io.StringIO:
    """In memory rather than on disk.

    `tmp_path` needs a writable system temp directory, which this environment
    does not reliably provide, and pandas reads a file-like object just as
    happily as a path. Nothing here needs a real file.
    """
    return io.StringIO(text)


def _xlsx(rows: list[dict]) -> io.BytesIO:
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer


class TestReadMaster:
    def test_it_excludes_the_files_own_totals_row(self) -> None:
        """The row with no branch name is a column sum, not a branch."""
        frame = O.read_master(
            _csv(
                "Branch Master,,,,,\n"
                "Branch Name,Transit Lead Time,Avg Lead Time,Std. LeadTime,Service Factor,Truck (MoQ)\n"
                "AGRA,2,3,0.98,1,7.8\n"
                "BENGALURU,2,4,0.95,1,7.8\n"
                ",,,188,225,61.25\n"
            )
        )

        assert list(frame["branch"]) == ["AGRA", "BENGALURU"]
        # 225 is the thing this exclusion exists to stop.
        assert 225.0 not in set(frame["Service Factor"])

    def test_it_reads_the_header_from_the_second_line(self) -> None:
        frame = O.read_master(
            _csv("Branch Master,,\nBranch Name,Avg Lead Time,Service Factor\nAGRA,3,1\n")
        )
        assert frame["Avg Lead Time"].tolist() == [3.0]


class TestDurations:
    def test_it_excludes_an_impossible_duration_and_counts_it(self) -> None:
        """The real file's worst is a 2002 despatch against a 2025 order."""
        source = _xlsx(
            [
                {"Oracle No": "FG.AAA", "Depo": "AGRA", "Order Date": "2025-04-01", "Despatch Date": "2025-04-04",
                 "Invoice Date": "2025-04-04"},
                {"Oracle No": "FG.AAA", "Depo": "AGRA", "Order Date": "2025-04-01", "Despatch Date": "2002-05-26",
                 "Invoice Date": "2025-04-02"},
            ]
        )

        lines, notes = O.read_durations(source)

        assert notes["lines_total"] == 2
        assert notes["lines_usable"] == 1
        assert notes["lines_out_of_range"] == 1
        assert notes["worst_excluded_days"] < 0
        assert lines["order_to_despatch"].tolist() == [3]

    def test_it_reports_the_invoice_leg_as_a_shape_not_a_duration(self) -> None:
        """40% of the real file is invoiced before despatch.

        The counts are published; no mean is. A "despatch to invoice" average
        over rows that routinely run backwards would be a number that means
        nothing.
        """
        source = _xlsx(
            [
                {"Oracle No": "FG.AAA", "Depo": "A", "Order Date": "2025-04-01", "Despatch Date": "2025-04-03",
                 "Invoice Date": "2025-04-02"},
                {"Oracle No": "FG.AAA", "Depo": "A", "Order Date": "2025-04-01", "Despatch Date": "2025-04-03",
                 "Invoice Date": "2025-04-03"},
                {"Oracle No": "FG.AAA", "Depo": "A", "Order Date": "2025-04-01", "Despatch Date": "2025-04-03",
                 "Invoice Date": "2025-04-05"},
            ]
        )

        _lines, notes = O.read_durations(source)

        assert notes["invoice_before_despatch"] == 1
        assert notes["invoice_same_day"] == 1
        assert notes["invoice_after_despatch"] == 1
        assert not any("mean" in key for key in notes if "invoice" in key)

    def test_a_missing_despatch_date_is_counted_not_treated_as_zero(self) -> None:
        source = _xlsx(
            [{"Oracle No": "FG.AAA", "Depo": "A", "Order Date": "2025-04-01", "Despatch Date": None,
              "Invoice Date": None}]
        )

        lines, notes = O.read_durations(source)

        assert notes["lines_missing_a_date"] == 1
        assert lines.empty


class TestAggregate:
    def test_it_describes_the_tail_not_only_the_mean(self) -> None:
        """A branch averaging 3 days with a p95 of 10 fails on the p95 days."""
        lines = pd.DataFrame(
            {"branch": ["A"] * 20, "order_to_despatch": [2] * 19 + [30]}
        )
        row = O.aggregate(lines).iloc[0]

        assert row["lines"] == 20
        assert row["observed_median"] == 2
        assert row["observed_max"] == 30
        assert row["observed_p95"] > row["observed_median"]

    def test_an_empty_frame_produces_no_rows_rather_than_a_zero_row(self) -> None:
        assert O.aggregate(pd.DataFrame(columns=["branch", "order_to_despatch"])).empty


class TestCompare:
    def _observed(self, rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_a_stated_zero_against_real_duration_is_flagged(self) -> None:
        """Four real branches state zero days and take 2.8-4.8."""
        out = O.compare(
            _master([{"branch": "RUDRAPUR", "Avg Lead Time": 0.0, "Std. LeadTime": 0.0,
                      "Transit Lead Time": 1.0, "Service Factor": 1.0, "Truck (MoQ)": 7.8}]),
            self._observed([{"branch": "RUDRAPUR", "lines": 2034, "observed_mean": 4.75,
                             "observed_median": 4.0, "observed_std": 1.72,
                             "observed_p95": 8.0, "observed_max": 20.0}]),
        )
        row = out.iloc[0]
        assert "zero-day lead time" in row["review"]
        assert row["gap_mean"] == 4.75

    def test_it_keeps_a_branch_that_exists_on_only_one_side(self) -> None:
        """An outer join, so neither file can hide a gap in the other."""
        out = O.compare(
            _master([{"branch": "ONLY_MASTER", "Avg Lead Time": 3.0, "Std. LeadTime": 1.0,
                      "Transit Lead Time": 1.0, "Service Factor": 1.0, "Truck (MoQ)": 7.8}]),
            self._observed([{"branch": "ONLY_ORDERS", "lines": 10, "observed_mean": 3.0,
                             "observed_median": 3.0, "observed_std": 1.0,
                             "observed_p95": 5.0, "observed_max": 6.0}]),
        )
        assert set(out["branch"]) == {"ONLY_MASTER", "ONLY_ORDERS"}
        master_only = out[out["branch"] == "ONLY_MASTER"].iloc[0]
        assert "No order line matched" in master_only["review"]
        orders_only = out[out["branch"] == "ONLY_ORDERS"].iloc[0]
        assert "No stated average" in orders_only["review"]

    def test_a_branch_matching_its_stated_time_is_not_flagged(self) -> None:
        out = O.compare(
            _master([{"branch": "A", "Avg Lead Time": 3.0, "Std. LeadTime": 1.0,
                      "Transit Lead Time": 1.0, "Service Factor": 1.0, "Truck (MoQ)": 7.8}]),
            self._observed([{"branch": "A", "lines": 100, "observed_mean": 2.9,
                             "observed_median": 3.0, "observed_std": 1.0,
                             "observed_p95": 5.0, "observed_max": 6.0}]),
        )
        assert out.iloc[0]["review"] is None

    @pytest.mark.parametrize("factor,usable", [(1.0, True), (1.65, True), (225.0, False)])
    def test_a_service_factor_outside_zero_to_five_is_marked_unusable(
        self, factor: float, usable: bool
    ) -> None:
        """A service factor is a z-score. 225 cannot be one."""
        out = O.compare(
            _master([{"branch": "A", "Avg Lead Time": 3.0, "Std. LeadTime": 1.0,
                      "Transit Lead Time": 1.0, "Service Factor": factor,
                      "Truck (MoQ)": 7.8}]),
            self._observed([{"branch": "A", "lines": 10, "observed_mean": 3.0,
                             "observed_median": 3.0, "observed_std": 1.0,
                             "observed_p95": 4.0, "observed_max": 5.0}]),
        )
        assert bool(out.iloc[0]["service_factor_usable"]) is usable

    def test_it_never_rewrites_a_stated_value(self) -> None:
        """The whole point: this compares, it does not correct."""
        out = O.compare(
            _master([{"branch": "A", "Avg Lead Time": 0.0, "Std. LeadTime": 0.0,
                      "Transit Lead Time": 1.0, "Service Factor": 1.0, "Truck (MoQ)": 7.8}]),
            self._observed([{"branch": "A", "lines": 10, "observed_mean": 4.75,
                             "observed_median": 4.0, "observed_std": 1.0,
                             "observed_p95": 8.0, "observed_max": 9.0}]),
        )
        # Flagged, but the stated figure is untouched.
        assert out.iloc[0]["stated_avg"] == 0.0
        assert out.iloc[0]["review"]


def _lines(rows: list[tuple]) -> pd.DataFrame:
    """(branch, sku, period, days)."""
    return pd.DataFrame(rows, columns=["branch", "sku", "period", "order_to_despatch"])


class TestRestrict:
    """A two-branch figure must be computed over two branches, not labelled as one."""

    def _sample(self) -> pd.DataFrame:
        return _lines(
            [
                ("BENGALURU", "FG.A", "2025-04", 3),
                ("BENGALURU", "FG.B", "2025-04", 5),
                ("DELHI-1", "FG.A", "2025-04", 4),
                ("AGRA", "FG.A", "2025-04", 99),
                ("AGRA", "FG.Z", "2025-04", 99),
            ]
        )

    def test_it_cuts_both_axes(self) -> None:
        out = O.restrict(self._sample(), branches=["BENGALURU", "DELHI-1"], skus=["FG.A"])
        assert len(out) == 2
        assert set(out["branch"]) == {"BENGALURU", "DELHI-1"}
        assert set(out["sku"]) == {"FG.A"}

    def test_it_matches_case_insensitively(self) -> None:
        out = O.restrict(self._sample(), branches=["bengaluru"], skus=["fg.a"])
        assert len(out) == 1

    def test_no_restriction_keeps_everything(self) -> None:
        assert len(O.restrict(self._sample())) == 5

    def test_restricting_changes_the_aggregate(self) -> None:
        """The whole point: the excluded branch's 99-day lines must not reach it."""
        scoped = O.restrict(self._sample(), branches=["BENGALURU", "DELHI-1"])
        means = O.aggregate(scoped)["observed_mean"].tolist()
        assert max(means) < 99


class TestBySku:
    def test_it_ranks_by_line_count_and_carries_the_tail(self) -> None:
        out = O.by_sku(
            _lines(
                [("B", "FG.BUSY", "2025-04", 3)] * 5
                + [("B", "FG.QUIET", "2025-04", 9)]
            )
        )
        assert [row["sku"] for row in out] == ["FG.BUSY", "FG.QUIET"]
        assert out[0]["lines"] == 5
        assert out[1]["p95"] == 9

    def test_it_invents_no_stated_counterpart(self) -> None:
        """Location Master is branch-grained; there is no per-SKU stated figure."""
        row = O.by_sku(_lines([("B", "FG.A", "2025-04", 3)]))[0]
        assert "stated" not in " ".join(row.keys())


class TestByMonth:
    def test_it_reports_overall_and_each_branch(self) -> None:
        out = O.by_month(
            _lines(
                [
                    ("BENGALURU", "FG.A", "2025-04", 2),
                    ("DELHI-1", "FG.A", "2025-04", 6),
                    ("BENGALURU", "FG.A", "2025-05", 4),
                ]
            )
        )
        assert [row["period"] for row in out] == ["2025-04", "2025-05"]
        assert out[0]["mean"] == 4.0
        assert out[0]["BENGALURU"] == 2.0
        assert out[0]["DELHI-1"] == 6.0
        # A branch with no line that month is null, not zero.
        assert out[1]["DELHI-1"] is None


class TestDistribution:
    def test_the_tail_is_a_bucket_not_a_truncation(self) -> None:
        out = O.distribution(
            _lines([("B", "FG.A", "2025-04", d) for d in [1, 1, 2, 40]]), cap=3
        )
        labels = [row["label"] for row in out]
        assert "4+" in labels
        assert sum(row["lines"] for row in out) == 4

    def test_shares_sum_to_about_one_hundred(self) -> None:
        out = O.distribution(_lines([("B", "FG.A", "2025-04", d) for d in [1, 2, 3, 4]]))
        assert abs(sum(row["share_pct"] for row in out) - 100.0) < 0.01


class TestTrend:
    def _months(self, means: list[float]) -> list[dict]:
        return [
            {"period": f"2025-{i + 1:02d}", "lines": 10, "mean": m}
            for i, m in enumerate(means)
        ]

    def test_it_compares_the_first_third_against_the_last(self) -> None:
        out = O.trend(self._months([3, 3, 3, 4, 5, 6, 6, 6, 6]))
        assert out["early_mean"] == 3.0
        assert out["late_mean"] == 6.0
        assert out["change_pct"] == 100.0

    def test_too_few_months_produce_no_trend_rather_than_a_weak_one(self) -> None:
        assert O.trend(self._months([3, 4, 5])) is None

    def test_it_weights_by_line_count(self) -> None:
        """A month with 1 line must not swing the window like one with 1,000."""
        rows = [
            {"period": "2025-01", "lines": 1000, "mean": 3.0},
            {"period": "2025-02", "lines": 1000, "mean": 3.0},
            {"period": "2025-03", "lines": 1, "mean": 30.0},
            {"period": "2025-04", "lines": 1000, "mean": 5.0},
            {"period": "2025-05", "lines": 1000, "mean": 5.0},
            {"period": "2025-06", "lines": 1000, "mean": 5.0},
        ]
        out = O.trend(rows)
        assert out["early_mean"] < 4.0
