"""PII must never reach the modelling panel, a profile, or an API payload.

Rule C13. The dataset carries customer names, GST numbers, PAN, CIN, TAN,
emails, mobiles and addresses; none of it is modelling-relevant and all of it
is personal or commercially sensitive.
"""

from __future__ import annotations

import inspect

from app.domain.ais import source_spec
from app.services.ingestion.ais_ingestion import _ColumnStatsAccumulator


class TestPiiDeclaration:
    def test_every_known_pii_column_is_declared(self) -> None:
        expected = {
            # Sales
            "Customer Code", "Customer Name", "GST Number", "Consignee Code",
            "Consignee Name",
            # Orders
            "Invoice No",
            # Location master
            "PAN No", "GSTIN", "CIN Number", "TIN No / VAT ??", "TAN Reg No",
            "ST Reg No", "Contact person Code", "Contact Person", "Email",
            "Branch Email", "Landline Number", "Fax", "Mobile", "Address1",
            "Address2", "Zip",
        }
        assert expected <= source_spec.ALL_PII_COLUMNS

    def test_modelling_relevant_columns_are_not_marked_pii(self) -> None:
        """Over-marking is its own failure: it would strip the branch hierarchy
        and lead times the model needs."""
        keep = {
            "Branch Code", "Branch Name", "Region", "Zone", "Supply Hub", "Tier",
            "Avg Lead Time", "Std. LeadTime", "Transit Lead Time", "Service Factor",
            "Truck (MoQ)", "City", "District", "State", "Quantity", "Oracle No",
            "Product Code", "Despatch Qty",
        }
        assert not (keep & source_spec.ALL_PII_COLUMNS)

    def test_each_spec_declares_its_own_pii(self) -> None:
        assert source_spec.SALES_SPEC.pii_columns == source_spec.SALES_PII
        assert source_spec.ORDERS_SPEC.pii_columns == source_spec.ORDERS_PII
        assert source_spec.LOCATION_MASTER_SPEC.pii_columns == source_spec.LOCATION_PII

    def test_stock_and_product_master_carry_no_pii(self) -> None:
        assert source_spec.STOCK_SPEC.pii_columns == frozenset()
        assert source_spec.PRODUCT_MASTER_SPEC.pii_columns == frozenset()


class TestPiiNeverEntersAProfile:
    COLUMNS = ["Branch", "Customer Name", "GST Number", "Quantity"]
    PII = frozenset({"Customer Name", "GST Number"})

    def _profile(self) -> dict:
        accumulator = _ColumnStatsAccumulator(self.COLUMNS, self.PII)
        for index in range(20):
            accumulator.observe(
                ["AGRA", f"SALONI ENTERPRISES {index}", f"09AFMPG904{index}G1Z8", index]
            )
        return accumulator.result()

    def test_pii_columns_are_flagged(self) -> None:
        profile = self._profile()
        assert profile["Customer Name"]["is_pii"] is True
        assert profile["GST Number"]["is_pii"] is True
        assert profile["Branch"]["is_pii"] is False

    def test_no_pii_value_is_retained_anywhere_in_the_profile(self) -> None:
        profile = self._profile()
        for column in ("Customer Name", "GST Number"):
            stats = profile[column]
            assert stats["sample_values"] == []
            assert stats["min_value"] is None
            assert stats["max_value"] is None
            assert stats["mean_value"] is None
            assert stats["distinct_count"] is None

    def test_pii_columns_are_still_counted(self) -> None:
        """Counting is required - a planner must see that the column exists and
        how complete it is - but the values are not."""
        profile = self._profile()
        assert profile["Customer Name"]["non_null_count"] == 20
        assert profile["Customer Name"]["null_count"] == 0

    def test_non_pii_columns_keep_their_samples(self) -> None:
        profile = self._profile()
        assert profile["Branch"]["sample_values"] == ["AGRA"]
        assert profile["Quantity"]["detected_type"] == "numeric"

    def test_no_pii_value_appears_in_the_serialised_profile(self) -> None:
        import json

        serialised = json.dumps(self._profile())
        assert "SALONI" not in serialised
        assert "09AFMPG" not in serialised

    def test_pii_column_records_why_its_values_are_absent(self) -> None:
        note = self._profile()["Customer Name"]["note"]
        assert note and "PII" in note


class TestPiiNotInApiPayloads:
    def test_dataset_schemas_declare_no_pii_field(self) -> None:
        from app.schemas import datasets as dataset_schemas

        source = inspect.getsource(dataset_schemas)
        for column in source_spec.ALL_PII_COLUMNS:
            token = column.lower().replace(" ", "_").replace("/", "_")
            # A schema field named after a PII column would serialise its values.
            assert f"    {token}:" not in source.lower()

    def test_profile_response_exposes_only_the_excluded_column_list(self) -> None:
        from app.schemas.datasets import DatasetProfileResponse

        assert "pii_columns_excluded" in DatasetProfileResponse.model_fields
