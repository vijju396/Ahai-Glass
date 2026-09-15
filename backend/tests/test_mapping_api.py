"""Mapping lifecycle contracts: draft, edit, validate, confirm, immutability."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.session import session_scope
from app.models.datasets import (
    ColumnProfile,
    Dataset,
    DatasetVersion,
    IngestionStatus,
    SourceFile,
)

ORDER_COLUMNS = [
    "Depo", "Supply Hub", "Order Date", "Despatch Date", "Material Code",
    "Oracle No", "Quantity", "Despatch Qty", "MRP Rate", "Invoice No", "Month",
]


@pytest.fixture()
def ingested_dataset():
    """A completed ingestion with one profiled source file, enough for the
    mapping service to enumerate columns."""
    with session_scope() as db:
        dataset = Dataset(name="Mapping fixture", source_label="source")
        db.add(dataset)
        db.flush()
        version = DatasetVersion(
            dataset_id=dataset.id,
            version_number=1,
            status=IngestionStatus.COMPLETED,
            progress_pct=100.0,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            controls_total=11,
            controls_failed=0,
        )
        db.add(version)
        db.flush()
        source_file = SourceFile(
            version_id=version.id, role="orders",
            filename="Orders & Receipts (Lead Time).xlsx",
            size_bytes=67_571_606, content_hash_sha256="b" * 64,
            row_count=775_912, column_count=len(ORDER_COLUMNS),
            columns_json=ORDER_COLUMNS,
        )
        db.add(source_file)
        db.flush()
        for index, column in enumerate(ORDER_COLUMNS):
            is_date = "Date" in column
            is_pii = column == "Invoice No"
            db.add(
                ColumnProfile(
                    source_file_id=source_file.id, column_name=column, ordinal=index,
                    detected_type="text" if (is_date or column in {"Depo", "Supply Hub", "Oracle No", "Material Code", "Month"}) else "numeric",
                    non_null_count=775_912, null_count=0,
                    distinct_count=None if is_pii else (53 if column == "Depo" else 96),
                    is_constant=False, is_pii=is_pii,
                    sample_values_json=[] if is_pii else (
                        ["2025-04-01 00:00:00"] if is_date else ["5"]
                    ),
                )
            )
        dataset_id = dataset.id
    return dataset_id


def _create(client, dataset_id: str) -> dict:
    response = client.post(
        f"/api/datasets/{dataset_id}/mapping/versions", json={"notes": "first draft"}
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestSuggestions:
    def test_suggestions_are_advisory_and_never_authoritative(self, client, ingested_dataset) -> None:
        body = client.get(f"/api/datasets/{ingested_dataset}/mapping/suggestions").json()
        assert body["total"] > 0
        assert all(s["is_authoritative"] is False for s in body["suggestions"])
        assert "advisory" in body["note"].lower()
        assert "human review" in body["note"].lower()

    def test_every_suggestion_carries_a_rationale(self, client, ingested_dataset) -> None:
        body = client.get(f"/api/datasets/{ingested_dataset}/mapping/suggestions").json()
        assert all(s["rationale"] for s in body["suggestions"])

    def test_pii_is_suggested_only_as_excluded(self, client, ingested_dataset) -> None:
        body = client.get(f"/api/datasets/{ingested_dataset}/mapping/suggestions").json()
        invoice = next(s for s in body["suggestions"] if s["column_name"] == "Invoice No")
        assert invoice["role"] == "excluded_pii"


class TestDraftCreation:
    def test_a_draft_is_created_with_every_column_assigned(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        assert mapping["state"] == "draft"
        assert mapping["version_number"] == 1
        assigned = {a["column_name"] for a in mapping["assignments"]}
        assert set(ORDER_COLUMNS) <= assigned

    def test_the_ais_template_defaults_are_applied(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        roles = {a["column_name"]: a["role"] for a in mapping["assignments"]}
        assert roles["Quantity"] == "target_column"
        assert roles["Order Date"] == "time_column"
        assert roles["Depo"] == "series_identifier"
        assert roles["Oracle No"] == "series_identifier"
        # Despatched quantity is a supply signal, never the target.
        assert roles["Despatch Qty"] == "supply"
        assert roles["Invoice No"] == "excluded_pii"

    def test_mrp_defaults_to_historical_not_future_known(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        mrp = next(a for a in mapping["assignments"] if a["column_name"] == "MRP Rate")
        assert mrp["role"] == "historical_driver"
        assert mrp["notes"] and "not knowable" in mrp["notes"]

    def test_the_config_defaults_suit_intermittent_demand(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        assert mapping["frequency"] == "monthly"
        assert mapping["forecast_horizon"] == 6
        # A month with no order is a real zero, not an absent observation.
        assert mapping["missing_timestamp_policy"] == "explicit_zero"
        assert mapping["target_imputation_policy"] == "leave_missing"

    def test_everything_starts_unreviewed(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        assert all(a["is_suggested"] for a in mapping["assignments"])
        assert mapping["unreviewed_count"] >= 2  # target + time column
        assert mapping["can_confirm"] is False

    def test_the_future_known_set_is_exposed_with_its_exclusions(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        assert "calendar_month" in mapping["future_known_columns"]
        assert "horizon_step" in mapping["future_known_columns"]
        # And the columns deliberately NOT future-known, with reasons.
        reasons = mapping["not_future_known_reasons"]
        assert "MRP Rate" in reasons
        assert "Despatch Qty" in reasons
        assert "censored" in reasons["Despatch Qty"]


class TestEditing:
    def test_editing_clears_the_suggested_flag(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        response = client.patch(
            f"/api/mappings/{mapping['id']}",
            json={
                "assignments": [
                    {
                        "source_role": "orders", "column_name": "Quantity",
                        "role": "target_column", "rationale": "Confirmed by the planner.",
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        quantity = next(
            a for a in response.json()["assignments"] if a["column_name"] == "Quantity"
        )
        assert quantity["is_suggested"] is False
        assert quantity["rationale"] == "Confirmed by the planner."

    def test_pii_cannot_be_reassigned_to_a_feature_role(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        response = client.patch(
            f"/api/mappings/{mapping['id']}",
            json={
                "assignments": [
                    {
                        "source_role": "orders", "column_name": "Invoice No",
                        "role": "static_attribute",
                    }
                ]
            },
        )
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "validation_failed"
        assert "PII" in error["message"] or "excluded" in error["message"]

    def test_an_unknown_column_is_rejected(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        response = client.patch(
            f"/api/mappings/{mapping['id']}",
            json={
                "assignments": [
                    {"source_role": "orders", "column_name": "Nope", "role": "ignored"}
                ]
            },
        )
        assert response.status_code == 422

    def test_config_can_be_edited_on_a_draft(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        response = client.patch(
            f"/api/mappings/{mapping['id']}", json={"config": {"forecast_horizon": 3}}
        )
        assert response.json()["forecast_horizon"] == 3


class TestValidationRules:
    def test_a_template_draft_has_no_blocking_violations(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        assert mapping["blocking_count"] == 0

    def test_removing_the_target_produces_a_blocking_rule(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        response = client.patch(
            f"/api/mappings/{mapping['id']}",
            json={
                "assignments": [
                    {"source_role": "orders", "column_name": "Quantity", "role": "ignored"}
                ]
            },
        )
        body = response.json()
        assert body["blocking_count"] >= 1
        assert any(r["rule_code"] == "R1" for r in body["rule_results"])
        assert body["can_confirm"] is False

    def test_claiming_mrp_is_future_known_is_blocked_as_leakage(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        body = client.patch(
            f"/api/mappings/{mapping['id']}",
            json={
                "assignments": [
                    {
                        "source_role": "orders", "column_name": "MRP Rate",
                        "role": "future_known_driver",
                    }
                ]
            },
        ).json()
        r5 = next(r for r in body["rule_results"] if r["rule_code"] == "R5")
        assert r5["severity"] == "blocking"
        assert "MRP Rate" in (r5["columns"] or [])
        assert "leakage" in (r5["remediation"] or "").lower()

    def test_rule_results_include_warnings_not_only_blockers(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        body = client.patch(
            f"/api/mappings/{mapping['id']}",
            json={"config": {"target_imputation_policy": "zero"}},
        ).json()
        assert any(r["rule_code"] == "R9" and r["severity"] == "warning" for r in body["rule_results"])
        # A warning must not block confirmation.
        assert body["blocking_count"] == 0


class TestConfirmation:
    def _review_required_roles(self, client, mapping_id: str) -> dict:
        return client.patch(
            f"/api/mappings/{mapping_id}",
            json={
                "assignments": [
                    {"source_role": "orders", "column_name": "Quantity", "role": "target_column"},
                    {"source_role": "orders", "column_name": "Order Date", "role": "time_column"},
                ]
            },
        ).json()

    def test_confirmation_is_refused_while_the_target_is_unreviewed(self, client, ingested_dataset) -> None:
        """A suggested target is a guess. On this dataset several columns look
        like demand, so the choice must be made explicitly."""
        mapping = _create(client, ingested_dataset)
        response = client.post(
            f"/api/mappings/{mapping['id']}/confirm", json={"confirmed_by": "planner"}
        )
        assert response.status_code == 422
        error = response.json()["error"]
        assert "reviewed" in error["message"].lower()
        assert "Quantity" in error["details"]["unreviewed_columns"]

    def test_confirmation_succeeds_once_required_roles_are_reviewed(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        reviewed = self._review_required_roles(client, mapping["id"])
        assert reviewed["unreviewed_count"] == 0
        assert reviewed["can_confirm"] is True

        response = client.post(
            f"/api/mappings/{mapping['id']}/confirm", json={"confirmed_by": "planner"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"] == "confirmed"
        assert body["confirmed_by"] == "planner"
        assert body["confirmed_at"]

    def test_confirmation_is_refused_while_a_blocking_rule_fails(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        self._review_required_roles(client, mapping["id"])
        client.patch(
            f"/api/mappings/{mapping['id']}",
            json={"config": {"forecast_horizon": 6}},
        )
        client.patch(
            f"/api/mappings/{mapping['id']}",
            json={
                "assignments": [
                    {
                        "source_role": "orders", "column_name": "MRP Rate",
                        "role": "future_known_driver",
                    }
                ]
            },
        )
        response = client.post(
            f"/api/mappings/{mapping['id']}/confirm", json={"confirmed_by": "planner"}
        )
        assert response.status_code == 422
        violations = response.json()["error"]["details"]["violations"]
        assert any(v["rule"] == "R5" for v in violations)

    def test_a_confirmed_mapping_is_immutable(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        self._review_required_roles(client, mapping["id"])
        client.post(f"/api/mappings/{mapping['id']}/confirm", json={"confirmed_by": "planner"})

        response = client.patch(
            f"/api/mappings/{mapping['id']}",
            json={
                "assignments": [
                    {"source_role": "orders", "column_name": "Quantity", "role": "ignored"}
                ]
            },
        )
        assert response.status_code == 409
        error = response.json()["error"]
        assert "immutable" in error["message"].lower()
        assert "new mapping version" in (error["remediation"] or "")

    def test_confirming_twice_is_refused(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        self._review_required_roles(client, mapping["id"])
        client.post(f"/api/mappings/{mapping['id']}/confirm", json={"confirmed_by": "planner"})
        again = client.post(
            f"/api/mappings/{mapping['id']}/confirm", json={"confirmed_by": "planner"}
        )
        assert again.status_code == 409

    def test_a_new_version_supersedes_the_previous_confirmed_one(self, client, ingested_dataset) -> None:
        first = _create(client, ingested_dataset)
        self._review_required_roles(client, first["id"])
        client.post(f"/api/mappings/{first['id']}/confirm", json={"confirmed_by": "planner"})

        second = _create(client, ingested_dataset)
        assert second["version_number"] == 2
        self._review_required_roles(client, second["id"])
        client.post(f"/api/mappings/{second['id']}/confirm", json={"confirmed_by": "planner2"})

        # The first is superseded, not overwritten - a training run may have used it.
        reloaded = client.get(f"/api/mappings/{first['id']}").json()
        assert reloaded["state"] == "superseded"
        assert reloaded["superseded_at"]
        assert reloaded["confirmed_by"] == "planner"


class TestPreprocessingGate:
    def test_preprocessing_requires_a_confirmed_mapping(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        response = client.post(f"/api/mappings/{mapping['id']}/preprocess")
        assert response.status_code == 409
        error = response.json()["error"]
        assert "confirmed" in error["message"].lower()

    def test_no_preprocessing_run_reports_not_found_rather_than_empty(self, client, ingested_dataset) -> None:
        mapping = _create(client, ingested_dataset)
        response = client.get(f"/api/mappings/{mapping['id']}/preprocessing")
        assert response.status_code == 404


class TestMappingListing:
    def test_mappings_are_listed_and_paginated(self, client, ingested_dataset) -> None:
        _create(client, ingested_dataset)
        body = client.get("/api/mappings").json()
        assert body["total"] >= 1
        assert {"items", "total", "offset", "limit"} <= set(body)

    def test_current_mapping_returns_the_latest_version(self, client, ingested_dataset) -> None:
        _create(client, ingested_dataset)
        second = _create(client, ingested_dataset)
        current = client.get(f"/api/datasets/{ingested_dataset}/mapping/current").json()
        assert current["id"] == second["id"]
        assert current["version_number"] == 2

    def test_an_unknown_mapping_returns_a_structured_404(self, client) -> None:
        response = client.get("/api/mappings/nope")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
