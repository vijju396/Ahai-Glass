"""Cleaning rules C1-C16, each tested against the exact defect it exists for."""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.ais import cleaning
from app.services.ingestion import readers


# --------------------------------------------------------------------------
# C8 - canonical SKU key
# --------------------------------------------------------------------------

class TestCanonicalSku:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Real values from the source files.
            ("FG.414.ADH.AFMTOY0000.AFM", "FG.414.ADH.AFMTOY0000"),
            ("FG.MW6.SWR.G00320A0S0.AF", "FG.MW6.SWR.G00320A0S0"),
            ("FG.M11.FDL.G00320A000.", "FG.M11.FDL.G00320A000"),
            ("fg.m11.fdl.g00320a000.", "FG.M11.FDL.G00320A000"),
            ("  FG.M11.FDL.G00320A000.  ", "FG.M11.FDL.G00320A000"),
            ("PREGST.MYB.RDL.G00300A000", "PREGST.MYB.RDL.G00300A000"),
            ("NONOE05.ABC.DEF.G00300A000", "NONOE05.ABC.DEF.G00300A000"),
        ],
    )
    def test_strips_suffix_and_normalises(self, raw: str, expected: str) -> None:
        assert cleaning.canonical_sku(raw) == expected

    def test_handles_the_interior_space_before_the_trailing_dot(self) -> None:
        """One real code is 'FG.TX4.LFH.GBG2120700 .' - the space survives the
        first TRIM because the dot is stripped afterwards, so a second TRIM is
        required. Without it the key carries a trailing space and never joins."""
        assert cleaning.canonical_sku("FG.TX4.LFH.GBG2120700 .") == "FG.TX4.LFH.GBG2120700"

    def test_does_not_strip_afm_from_the_middle_of_a_code(self) -> None:
        assert cleaning.canonical_sku("FG.414.ADH.AFMTOY0000") == "FG.414.ADH.AFMTOY0000"

    def test_strips_only_one_suffix_occurrence(self) -> None:
        assert cleaning.canonical_sku("FG.X.Y.Z.AFM") == "FG.X.Y.Z"

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_empty_input_yields_empty_key(self, raw) -> None:
        assert cleaning.canonical_sku(raw) == ""


# --------------------------------------------------------------------------
# C6 / C7 - branch normalisation
# --------------------------------------------------------------------------

class TestBranchNormalisation:
    def test_collapses_the_real_case_variants(self) -> None:
        """The order file's 110 depot spellings collapse to 53 by this rule."""
        variants = ["Jaipur", "JAIPUR", "jaipur", " Jaipur "]
        assert len({cleaning.canonical_branch(v) for v in variants}) == 1

    def test_collapses_the_jodhpur_typo_pattern(self) -> None:
        assert cleaning.canonical_branch("JODhPUR") == cleaning.canonical_branch("Jodhpur")

    def test_normalize_key_matches_canonical_branch(self) -> None:
        assert readers.normalize_key(" tempered ") == cleaning.canonical_branch(" tempered ")


# --------------------------------------------------------------------------
# C4 / C5 - Excel serial dates
# --------------------------------------------------------------------------

class TestExcelSerialDates:
    def test_uses_the_1899_12_30_epoch(self) -> None:
        """45751 is the first Inv Date in the FY 25-26 sheet, whose own Month
        label reads "Apr'25". On the 1899-12-30 epoch it converts to
        2025-04-04, which agrees with that label - the cross-check rule C5
        performs on every row."""
        assert readers.excel_serial_to_date(45751) == date(2025, 4, 4)

    def test_converts_the_fy2425_sample(self) -> None:
        """45383, first Inv Date of the FY 24-25 sheet, Month label "Apr'24"."""
        assert readers.excel_serial_to_date(45383.0) == date(2024, 4, 1)

    def test_a_wrong_epoch_would_shift_the_date(self) -> None:
        """Guards against the classic 1900-01-01 mistake, which lands two days
        late and would put an Apr'25 invoice in April 2025 but on the wrong
        day - and, at a month boundary, in the wrong month entirely."""
        assert readers.excel_serial_to_date(45383) == date(2024, 4, 1)
        assert readers.excel_serial_to_date(45383) != date(2024, 4, 3)

    @pytest.mark.parametrize("serial", [0, 1, 19_999, 60_001, 1_000_000])
    def test_rejects_implausible_serials_instead_of_guessing(self, serial) -> None:
        assert readers.excel_serial_to_date(serial) is None

    @pytest.mark.parametrize("value", [None, "", "not a date", "abc"])
    def test_rejects_non_numeric_values(self, value) -> None:
        assert readers.excel_serial_to_date(value) is None


# --------------------------------------------------------------------------
# C14 - corrupt despatch dates
# --------------------------------------------------------------------------

class TestLooseDateParsing:
    def test_rejects_the_zero_sentinel(self) -> None:
        """'0000-00-00' appears in Despatch Date and Last GRN Date. Parsing it
        as a real date is what produces lead times of -8,763 days."""
        assert readers.parse_loose_date("0000-00-00") is None
        assert readers.parse_loose_date("00-00-0000") is None

    @pytest.mark.parametrize("value", ["None", "nan", "NaT", "", "   "])
    def test_rejects_null_like_text(self, value) -> None:
        assert readers.parse_loose_date(value) is None

    def test_parses_an_iso_timestamp(self) -> None:
        assert readers.parse_loose_date("2025-04-08 00:00:00") == date(2025, 4, 8)

    def test_parses_a_bare_serial(self) -> None:
        assert readers.parse_loose_date("45751") == date(2025, 4, 4)


# --------------------------------------------------------------------------
# C2 - the FY 25-26 transposition
# --------------------------------------------------------------------------

class TestTranspositionDetection:
    HEADER = ["Branch", "Product Code", "HSN Code", "Product Name", "Quantity"]

    def _fy2526_row(self) -> tuple:
        # Real shape: the NAME sits under the HSN header.
        return ("AGRA", "FG.M11.FDL.G00320A000.", "BOLERO (2022) FD LH GR", 70071100.0, 2.0)

    def _fy2425_row(self) -> tuple:
        # Real shape: matches the declared header order.
        return ("AGRA", "FG.MYC.RDR.G00300A000.", 70071100.0, "VERSA RD GR RH", 3.0)

    def test_detects_the_fy2526_transposition(self) -> None:
        verdict = cleaning.detect_transposition([self._fy2526_row()] * 50, self.HEADER)
        assert verdict.is_transposed is True
        assert verdict.confidence == pytest.approx(1.0)

    def test_leaves_the_correct_sheet_alone(self) -> None:
        verdict = cleaning.detect_transposition([self._fy2425_row()] * 50, self.HEADER)
        assert verdict.is_transposed is False

    def test_is_undecided_rather_than_wrong_on_a_mixed_sample(self) -> None:
        rows = [self._fy2526_row()] * 25 + [self._fy2425_row()] * 25
        verdict = cleaning.detect_transposition(rows, self.HEADER)
        assert verdict.is_transposed is False
        assert verdict.confidence == pytest.approx(0.5)

    def test_applying_the_swap_restores_the_declared_order(self) -> None:
        hsn_index = self.HEADER.index("HSN Code")
        name_index = self.HEADER.index("Product Name")
        fixed = cleaning.apply_transposition(self._fy2526_row(), hsn_index, name_index)
        assert cleaning.looks_like_hsn(fixed[hsn_index])
        assert cleaning.looks_like_product_name(fixed[name_index])

    def test_detection_is_by_value_not_position(self) -> None:
        """The same values in a differently ordered header must still be
        judged on their content."""
        header = ["Product Name", "HSN Code"]
        rows = [("BOLERO LAMI W/S GR", 70071100.0)] * 20
        assert cleaning.detect_transposition(rows, header).is_transposed is False

    @pytest.mark.parametrize("value", [70071100.0, "70071100", "70071100.0", 700711])
    def test_hsn_pattern_accepts_real_codes(self, value) -> None:
        assert cleaning.looks_like_hsn(value)

    @pytest.mark.parametrize("value", ["BOLERO LAMI W/S GR", "", None, "12", "ABC123456"])
    def test_hsn_pattern_rejects_non_codes(self, value) -> None:
        assert not cleaning.looks_like_hsn(value)


# --------------------------------------------------------------------------
# C1 / C3 - name-based union
# --------------------------------------------------------------------------

class TestUnionByName:
    FY2526 = ["Branch", "Record Type", "Inv No", "Product Code", "Quantity"]
    # 'Doc Series' sits third, shifting everything after it.
    FY2425 = ["Branch", "Record Type", "Doc Series", "Inv No", "Product Code", "Quantity"]

    def test_shared_columns_exclude_the_sheet_only_column(self) -> None:
        shared = cleaning.shared_columns_of([self.FY2526, self.FY2425])
        assert "Doc Series" not in shared
        assert shared == ["Branch", "Record Type", "Inv No", "Product Code", "Quantity"]

    def test_projection_realigns_the_offset_sheet(self) -> None:
        """This is the whole point of C1: a positional union would read
        'Doc Series' as 'Inv No' and shift every later column by one."""
        shared = cleaning.shared_columns_of([self.FY2526, self.FY2425])
        plan = cleaning.build_union_plan(self.FY2425, shared)
        row = ("AGRA", "GLASS", "AGRA-SINV-2425-SINV", "24SIN/AGR/100001", "FG.X.Y.Z.", 3.0)
        projected = cleaning.project_row(row, plan)
        assert projected == ["AGRA", "GLASS", "24SIN/AGR/100001", "FG.X.Y.Z.", 3.0]

    def test_a_positional_union_would_have_been_wrong(self) -> None:
        row = ("AGRA", "GLASS", "AGRA-SINV-2425-SINV", "24SIN/AGR/100001", "FG.X.Y.Z.", 3.0)
        naive_positional = list(row[: len(self.FY2526)])
        assert naive_positional[2] == "AGRA-SINV-2425-SINV"  # wrong: that is Doc Series

    def test_plan_records_what_it_dropped(self) -> None:
        shared = cleaning.shared_columns_of([self.FY2526, self.FY2425])
        plan = cleaning.build_union_plan(self.FY2425, shared)
        assert plan.dropped_columns == ["Doc Series"]
        assert plan.missing_columns == []

    def test_plan_reports_a_missing_shared_column(self) -> None:
        plan = cleaning.build_union_plan(["Branch"], ["Branch", "Quantity"])
        assert plan.missing_columns == ["Quantity"]
        assert cleaning.project_row(("AGRA",), plan) == ["AGRA", None]


# --------------------------------------------------------------------------
# C9 / C10 - key reconciliation
# --------------------------------------------------------------------------

class TestKeyReconciliation:
    def test_detects_an_oracle_collision(self) -> None:
        """Real pattern: a PREGST legacy code shares an Oracle No with its FG
        twin, so Oracle No alone would merge two distinct products."""
        reconciler = cleaning.KeyReconciler()
        reconciler.observe("FG.MYB.RDL.G00300A000.", "FG.MYB.RDL.G00300A000")
        reconciler.observe("PREGST.MYB.RDL.G00300A000", "FG.MYB.RDL.G00300A000")
        result = reconciler.result()
        assert result.canonical_sku_count == 2
        assert result.oracle_no_count == 1
        assert result.collision_count == 1
        assert result.disagreement_count == 0

    def test_detects_a_canonical_disagreement(self) -> None:
        reconciler = cleaning.KeyReconciler()
        reconciler.observe("FG.A.B.C.AFM", "ORACLE-1")
        reconciler.observe("FG.A.B.C.AFM", "ORACLE-2")
        result = reconciler.result()
        assert result.disagreement_count == 1
        assert result.disagreements["FG.A.B.C"] == ["ORACLE-1", "ORACLE-2"]

    @pytest.mark.parametrize("oracle", [None, "", "   ", "None", "nan"])
    def test_counts_rows_with_no_oracle_number(self, oracle) -> None:
        reconciler = cleaning.KeyReconciler()
        reconciler.observe("FG.A.B.C.AFM", oracle)
        result = reconciler.result()
        assert result.rows_missing_oracle == 1
        assert result.canonical_sku_count == 1

    def test_tracks_prefix_distribution(self) -> None:
        reconciler = cleaning.KeyReconciler()
        reconciler.observe("FG.A.B.C", "O1")
        reconciler.observe("PREGST.A.B.C", "O2")
        reconciler.observe("NONOE05.A.B.C", "O3")
        assert reconciler.result().prefix_counts == {"FG": 1, "PREGST": 1, "NONOE05": 1}

    def test_clean_mapping_reports_no_findings(self) -> None:
        reconciler = cleaning.KeyReconciler()
        for index in range(10):
            reconciler.observe(f"FG.{index}.B.C.AFM", f"FG.{index}.B.C")
        result = reconciler.result()
        assert result.collision_count == 0
        assert result.disagreement_count == 0
        assert result.canonical_sku_count == result.oracle_no_count == 10


# --------------------------------------------------------------------------
# C15 - the Location Master footer
# --------------------------------------------------------------------------

class TestLocationFooterDetection:
    HEADER = ["Branch Code", "Branch Name", "Region", "Avg Lead Time", "Status"]

    def test_accepts_a_real_branch_row(self) -> None:
        row = ["AGRA", "AGRA", "NORTH-1", "3", "Active"]
        assert cleaning.is_location_footer_row(row, self.HEADER) is False

    def test_rejects_the_real_footer_row(self) -> None:
        """The footer shifts values left, so a number lands in Status."""
        row = ["", " ", " ", "", "57.52"]
        assert cleaning.is_location_footer_row(row, self.HEADER) is True

    def test_rejects_a_row_with_a_numeric_status(self) -> None:
        row = ["AGRA", "AGRA", "NORTH-1", "3", "57.52"]
        assert cleaning.is_location_footer_row(row, self.HEADER) is True

    def test_rejects_a_row_with_no_branch_code(self) -> None:
        assert cleaning.is_location_footer_row(["", "X", "Y", "1", "Active"], self.HEADER) is True

    def test_rejects_a_wholly_blank_row(self) -> None:
        assert cleaning.is_location_footer_row(["", "", "", "", ""], self.HEADER) is True
