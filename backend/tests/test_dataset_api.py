"""Dataset route contracts, against a real database and real ORM rows.

Ingestion itself is not run here - it streams 2.6 M rows and takes ~8 minutes.
These tests persist the records ingestion would produce and assert the route
contracts on top of them, including the failure paths.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db.session import session_scope
from app.models.datasets import (
    ColumnProfile,
    ControlOutcome,
    Dataset,
    DatasetVersion,
    DefectRecord,
    IngestionStatus,
    KeyReconciliation,
    SourceFile,
    ValidationControl,
)


@pytest.fixture()
def seeded_dataset():
    """A completed ingestion, as the pipeline would have persisted it."""
    # A plain NamedTemporaryFile rather than pytest's tmp_path: this machine's
    # Temp directory denies the scandir pytest performs to build tmp_path.
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - cleaned up below
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    handle.close()
    manifest = Path(handle.name)
    manifest.write_text(
        json.dumps(
            {
                "summary": {
                    "canonical_sku_count": 2260,
                    "oracle_no_count": 2147,
                    "oracle_collisions": 109,
                    "canonical_disagreements": 0,
                    "rows_missing_oracle": 11,
                    "sku_prefixes": {"FG": 1702878, "PREGST": 153},
                    "branch_universes": {
                        "location_master": 57, "stock": 54,
                        "order_depots": 53, "selling_branches": 51,
                    },
                    "sku_universes": {
                        "sales": 2260, "orders_via_oracle_no": 2063,
                        "orders_via_material_code": 3139,
                    },
                    "product_master_coverage_pct": 99.909,
                    "service_measures": {
                        "total_ordered": 2602392,
                        "total_despatched": 2133961,
                        "net_shortfall": 468431,
                        "gross_positive_shortfall": 504298,
                        "over_delivered_qty": 35867,
                        "net_fill_rate": 0.8199998,
                        "gross_shortfall_pct": 19.378,
                        "lines_total": 775912,
                        "lines_fully_unserved": 161099,
                        "lines_with_shortfall": 168599,
                        "lines_over_delivered": 9498,
                    },
                    "lead_time": {
                        "count": 775628, "median_days": 3.0, "p95_days": 6.0,
                        "max_days": 27, "unparseable_dates": 3,
                        "negative_excluded": 281,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    with session_scope() as db:
        dataset = Dataset(name="Seeded set", source_label="source")
        db.add(dataset)
        db.flush()
        version = DatasetVersion(
            dataset_id=dataset.id,
            version_number=1,
            status=IngestionStatus.COMPLETED,
            stage_detail="Complete",
            progress_pct=100.0,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            duration_seconds=475.6,
            controls_total=2,
            controls_failed=0,
            defects_total=1,
            manifest_path=str(manifest),
        )
        db.add(version)
        db.flush()

        source_file = SourceFile(
            version_id=version.id, role="sales",
            filename="Sales Data FY 24~26.xlsb",
            sheet_name="FY 25-26 Sales + FY 24-25 Sales",
            size_bytes=82_429_868, content_hash_sha256="a" * 64,
            row_count=1_703_042, column_count=33, read_seconds=260.4,
            columns_json=["Branch", "Customer Name"],
        )
        db.add(source_file)
        db.flush()
        db.add_all(
            [
                ColumnProfile(
                    source_file_id=source_file.id, column_name="Branch", ordinal=0,
                    detected_type="text", non_null_count=1_703_042, null_count=0,
                    distinct_count=51, is_constant=False, is_pii=False,
                    sample_values_json=["AGRA"],
                ),
                ColumnProfile(
                    source_file_id=source_file.id, column_name="Customer Name",
                    ordinal=1, detected_type="text", non_null_count=1_703_042,
                    null_count=0, distinct_count=None, is_constant=False,
                    is_pii=True, min_value=None, max_value=None, mean_value=None,
                    sample_values_json=[],
                    note="PII - counted only; values never read into the profile.",
                ),
            ]
        )
        db.add_all(
            [
                ValidationControl(
                    version_id=version.id, control_code="S6",
                    description="Distinct canonical SKUs", expected="2,260",
                    measured="2,260", outcome=ControlOutcome.PASS.value,
                    tolerance_pct=0.0,
                ),
                ValidationControl(
                    version_id=version.id, control_code="S9",
                    description="Product-master coverage of order lines",
                    expected=">= 99.0%", measured="99.909%",
                    outcome=ControlOutcome.PASS.value,
                ),
            ]
        )
        db.add(
            DefectRecord(
                version_id=version.id, defect_code="D17",
                title="Material Code and Oracle No are not interchangeable",
                severity="recorded", extent="3,139 vs 2,063 distinct",
                affected_rows=48_888, source_role="orders", rule_applied="C9",
                fix_description="Oracle No is the master join key in the order file.",
                evidence_json={"line_coverage_via_oracle_pct": 99.909},
            )
        )
        db.add(
            KeyReconciliation(
                version_id=version.id, finding_type="oracle_collision",
                key_value="FG.MYB.RDL.G00300A000",
                related_values_json=["FG.MYB.RDL.G00300A000", "PREGST.MYB.RDL.G00300A000"],
                occurrence_count=2,
                note="One Oracle No spans several canonical Product Codes.",
            )
        )
        dataset_id = dataset.id
    yield dataset_id
    manifest.unlink(missing_ok=True)


class TestDatasetListAndDetail:
    def test_list_is_paginated(self, client, seeded_dataset) -> None:
        body = client.get("/api/datasets").json()
        assert {"items", "total", "offset", "limit"} <= set(body)
        assert body["total"] >= 1

    def test_detail_carries_the_latest_version_progress(self, client, seeded_dataset) -> None:
        body = client.get(f"/api/datasets/{seeded_dataset}").json()
        version = body["latest_version"]
        assert version["status"] == "completed"
        assert version["progress_pct"] == 100.0
        assert version["controls_total"] == 2

    def test_unknown_dataset_returns_the_structured_error(self, client) -> None:
        response = client.get("/api/datasets/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


class TestValidationRoute:
    def test_returns_every_control_with_expected_and_measured(self, client, seeded_dataset) -> None:
        body = client.get(f"/api/datasets/{seeded_dataset}/validation").json()
        assert body["passed"] is True
        codes = {control["control_code"] for control in body["controls"]}
        assert codes == {"S6", "S9"}
        s6 = next(c for c in body["controls"] if c["control_code"] == "S6")
        assert s6["expected"] == "2,260" and s6["measured"] == "2,260"

    def test_reports_net_and_gross_shortfall_as_separate_fields(self, client, seeded_dataset) -> None:
        measures = client.get(f"/api/datasets/{seeded_dataset}/validation").json()[
            "service_measures"
        ]
        assert measures["net_shortfall"] == 468_431
        assert measures["gross_positive_shortfall"] == 504_298
        assert measures["over_delivered_qty"] == 35_867
        # They must not be equal - that is the whole point of reporting both.
        assert measures["net_shortfall"] != measures["gross_positive_shortfall"]

    def test_reports_lead_time_exclusions(self, client, seeded_dataset) -> None:
        lead_time = client.get(f"/api/datasets/{seeded_dataset}/validation").json()["lead_time"]
        assert lead_time["median_days"] == 3.0
        assert lead_time["p95_days"] == 6.0
        assert lead_time["unparseable_dates"] == 3
        assert lead_time["negative_excluded"] == 281

    def test_returns_the_defect_register_with_its_rule(self, client, seeded_dataset) -> None:
        defects = client.get(f"/api/datasets/{seeded_dataset}/validation").json()["defects"]
        assert defects[0]["defect_code"] == "D17"
        assert defects[0]["rule_applied"] == "C9"

    def test_a_failed_control_populates_a_blocking_message(self, client, seeded_dataset) -> None:
        """A failure must be impossible to mistake for a clean version."""
        with session_scope() as db:
            control = (
                db.query(ValidationControl)
                .filter(ValidationControl.control_code == "S6")
                .first()
            )
            control.outcome = ControlOutcome.FAIL.value
            control.measured = "2,147"

        body = client.get(f"/api/datasets/{seeded_dataset}/validation").json()
        assert body["passed"] is False
        assert "S6" in body["blocking_message"]
        assert "must not treat this version as clean" in body["blocking_message"]
        # The failing control is still present, with its measured value.
        s6 = next(c for c in body["controls"] if c["control_code"] == "S6")
        assert s6["outcome"] == "fail"
        assert s6["measured"] == "2,147"


class TestMappingRoute:
    def test_explains_the_canonical_key_choice(self, client, seeded_dataset) -> None:
        body = client.get(f"/api/datasets/{seeded_dataset}/mapping").json()
        assert body["canonical_sku_count"] == 2260
        assert body["oracle_no_count"] == 2147
        assert body["oracle_collision_count"] == 109
        assert body["canonical_disagreement_count"] == 0
        assert "TRIM" in body["canonical_key_rule"]
        assert "109" in body["why_not_oracle_no"]

    def test_reports_all_four_branch_universes(self, client, seeded_dataset) -> None:
        universes = client.get(f"/api/datasets/{seeded_dataset}/mapping").json()[
            "branch_universes"
        ]
        assert universes == {
            "location_master": 57, "stock": 54,
            "order_depots": 53, "selling_branches": 51,
        }

    def test_distinguishes_the_two_order_file_keys(self, client, seeded_dataset) -> None:
        universes = client.get(f"/api/datasets/{seeded_dataset}/mapping").json()[
            "sku_universes"
        ]
        assert universes["orders_via_oracle_no"] == 2063
        assert universes["orders_via_material_code"] == 3139

    def test_returns_reconciliation_findings(self, client, seeded_dataset) -> None:
        body = client.get(f"/api/datasets/{seeded_dataset}/mapping").json()
        finding = body["findings"][0]
        assert finding["finding_type"] == "oracle_collision"
        assert "PREGST.MYB.RDL.G00300A000" in finding["related_values"]

    def test_findings_can_be_filtered_by_type(self, client, seeded_dataset) -> None:
        body = client.get(
            f"/api/datasets/{seeded_dataset}/mapping",
            params={"finding_type": "canonical_disagreement"},
        ).json()
        assert body["findings"] == []


class TestProfileRoute:
    def test_lists_files_with_their_content_hash(self, client, seeded_dataset) -> None:
        body = client.get(f"/api/datasets/{seeded_dataset}/profile").json()
        assert body["total_rows_read"] == 1_703_042
        source_file = body["source_files"][0]
        assert source_file["row_count"] == 1_703_042
        assert len(source_file["content_hash_sha256"]) == 64

    def test_no_pii_value_reaches_the_payload(self, client, seeded_dataset) -> None:
        raw = client.get(f"/api/datasets/{seeded_dataset}/profile").text
        assert "SALONI" not in raw
        assert "09AFMPG" not in raw

        body = json.loads(raw)
        columns = {c["column_name"]: c for c in body["source_files"][0]["column_profiles"]}
        pii = columns["Customer Name"]
        assert pii["is_pii"] is True
        assert pii["sample_values"] == []
        assert pii["min_value"] is None and pii["max_value"] is None
        assert pii["distinct_count"] is None
        # Still counted, so completeness is visible.
        assert pii["non_null_count"] == 1_703_042

    def test_non_pii_column_keeps_its_sample(self, client, seeded_dataset) -> None:
        body = client.get(f"/api/datasets/{seeded_dataset}/profile").json()
        columns = {c["column_name"]: c for c in body["source_files"][0]["column_profiles"]}
        assert columns["Branch"]["sample_values"] == ["AGRA"]

    def test_names_the_excluded_pii_columns(self, client, seeded_dataset) -> None:
        excluded = client.get(f"/api/datasets/{seeded_dataset}/profile").json()[
            "pii_columns_excluded"
        ]
        assert "GSTIN" in excluded
        assert "Customer Name" in excluded


class TestIngestionSubmission:
    def test_create_returns_202_without_waiting(self, client, monkeypatch) -> None:
        """Ingestion takes ~475 s, so the route must never await it."""
        submitted: list[str] = []
        monkeypatch.setattr(
            "app.api.routes.datasets.dataset_service.start_ingestion",
            lambda version_id: submitted.append(version_id) or version_id,
        )
        response = client.post("/api/datasets", json={"name": "New set"})
        assert response.status_code == 202
        body = response.json()
        assert body["version_id"]
        assert submitted == [body["version_id"]]
        assert "poll" in body["message"].lower()

    def test_create_rejects_an_empty_name(self, client) -> None:
        response = client.post("/api/datasets", json={"name": ""})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_failed"

    def test_cancel_reports_when_nothing_is_running(self, client, seeded_dataset) -> None:
        body = client.post(f"/api/datasets/{seeded_dataset}/cancel").json()
        assert body["cancellation_requested"] is False
        assert "No running ingestion" in body["detail"]
