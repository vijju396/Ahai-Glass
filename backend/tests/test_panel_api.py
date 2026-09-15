"""Panel build route contracts.

The build itself streams 1.5 M panel rows and takes ~140 s, so it is exercised
end to end separately (docs/STATUS.md). These cover the route contracts and
the gates.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.session import session_scope
from app.models.datasets import Dataset, DatasetVersion, IngestionStatus
from app.models.mappings import MappingVersion, PreprocessingRun
from app.models.panel import PanelBuild


def _preprocessing_run(status: str = "completed", *, with_artifacts: bool = True) -> str:
    with session_scope() as db:
        dataset = Dataset(name="Panel fixture", source_label="source")
        db.add(dataset)
        db.flush()
        version = DatasetVersion(
            dataset_id=dataset.id, version_number=1,
            status=IngestionStatus.COMPLETED, progress_pct=100.0,
        )
        db.add(version)
        db.flush()
        mapping = MappingVersion(
            dataset_version_id=version.id, version_number=1, state="confirmed",
            confirmed_at=datetime.now(timezone.utc), confirmed_by="planner",
        )
        db.add(mapping)
        db.flush()
        run = PreprocessingRun(
            mapping_id=mapping.id,
            status=status,
            progress_pct=100.0 if status == "completed" else 40.0,
            artifacts_json=(
                {
                    "branch_dim": "/tmp/branch_dim.parquet",
                    "order_fact": "/tmp/order_fact.parquet",
                }
                if with_artifacts
                else None
            ),
        )
        db.add(run)
        db.flush()
        return run.id


@pytest.fixture()
def no_job_submission(monkeypatch: pytest.MonkeyPatch):
    """Stop the route actually launching a 140-second build."""
    submitted: list[str] = []

    class _Runner:
        def submit(self, job_id, kind, fn, *args, **kwargs):  # noqa: ANN001, ANN002
            submitted.append(job_id)
            return None

    monkeypatch.setattr("app.services.panel_service.get_runner", lambda: _Runner())
    return submitted


class TestBuildSubmission:
    def test_it_returns_202_without_waiting(self, client, no_job_submission) -> None:
        run_id = _preprocessing_run()
        response = client.post(
            "/api/panel/builds",
            json={"preprocessing_run_id": run_id, "training_cut_period": "2025-09"},
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] == "pending"
        assert body["training_cut_period"] == "2025-09"
        assert body["horizons"] == "1,2,3,4,5,6"
        assert no_job_submission == [body["id"]]

    def test_it_defaults_to_the_newest_completed_run(self, client, no_job_submission) -> None:
        """An earlier run may predate a fix - two exist on this project, and the
        older one reports zero non-glass SKUs (D-024)."""
        first = _preprocessing_run()
        second = _preprocessing_run()
        response = client.post("/api/panel/builds", json={"training_cut_period": "2025-09"})
        assert response.status_code == 202
        assert response.json()["preprocessing_run_id"] == second
        assert response.json()["preprocessing_run_id"] != first

    def test_an_incomplete_preprocessing_run_is_refused(self, client, no_job_submission) -> None:
        run_id = _preprocessing_run(status="running")
        response = client.post(
            "/api/panel/builds", json={"preprocessing_run_id": run_id}
        )
        assert response.status_code == 409
        error = response.json()["error"]
        assert "not completed" in error["message"]
        assert "preprocessing" in (error["remediation"] or "").lower()

    def test_a_run_without_artifacts_is_refused(self, client, no_job_submission) -> None:
        run_id = _preprocessing_run(with_artifacts=False)
        response = client.post(
            "/api/panel/builds", json={"preprocessing_run_id": run_id}
        )
        assert response.status_code == 409
        assert "artifacts" in response.json()["error"]["message"]

    def test_no_completed_run_at_all_is_refused_with_guidance(
        self, client, no_job_submission
    ) -> None:
        response = client.post("/api/panel/builds", json={})
        assert response.status_code == 409
        assert "Confirm a mapping" in response.json()["error"]["remediation"]

    def test_an_unknown_run_returns_404(self, client, no_job_submission) -> None:
        response = client.post(
            "/api/panel/builds", json={"preprocessing_run_id": "nope"}
        )
        assert response.status_code == 404

    def test_a_malformed_cut_period_is_rejected(self, client, no_job_submission) -> None:
        run_id = _preprocessing_run()
        response = client.post(
            "/api/panel/builds",
            json={"preprocessing_run_id": run_id, "training_cut_period": "Sept 2025"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_failed"

    def test_horizons_are_deduplicated_and_sorted(self, client, no_job_submission) -> None:
        run_id = _preprocessing_run()
        response = client.post(
            "/api/panel/builds",
            json={"preprocessing_run_id": run_id, "horizons": [3, 1, 3, 2]},
        )
        assert response.json()["horizons"] == "1,2,3"

    def test_a_non_positive_horizon_is_dropped_and_an_empty_set_refused(
        self, client, no_job_submission
    ) -> None:
        run_id = _preprocessing_run()
        response = client.post(
            "/api/panel/builds",
            json={"preprocessing_run_id": run_id, "horizons": [0, -2]},
        )
        assert response.status_code == 422
        assert "horizon of 1 or more" in response.json()["error"]["message"]

    def test_a_cut_may_be_omitted_to_use_every_origin(self, client, no_job_submission) -> None:
        run_id = _preprocessing_run()
        response = client.post(
            "/api/panel/builds", json={"preprocessing_run_id": run_id}
        )
        assert response.status_code == 202
        assert response.json()["training_cut_period"] is None


class TestBuildReads:
    def _seed_completed_build(self) -> str:
        run_id = _preprocessing_run()
        with session_scope() as db:
            build = PanelBuild(
                preprocessing_run_id=run_id,
                status="completed",
                stage_detail="Complete",
                progress_pct=100.0,
                duration_seconds=139.9,
                training_cut_period="2025-09",
                horizons="1,2,3,4,5,6",
                panel_rows=1_503_753,
                series_count=68_675,
                period_count=28,
                observed_rows=634_951,
                materialised_zero_rows=868_802,
                censored_rows=109_145,
                training_rows=3_895_148,
                scoring_rows=360_702,
                feature_count=35,
                artifacts_json={"panel": "/tmp/panel.parquet"},
                summary_json={
                    "period_range": ["2024-04", "2026-07"],
                    "target_source_rows": {"order": 994_526, "sales_proxy": 509_227},
                    "series_universe": {
                        "panel_series": 68_675,
                        "sales_control_series": 63_210,
                        "stock_only_pairs_excluded": 78_694,
                    },
                    "feature_manifest": {"feature_count": 35, "max_lookback_months": 11},
                },
            )
            db.add(build)
            db.flush()
            return build.id

    def test_current_returns_the_latest_build(self, client) -> None:
        build_id = self._seed_completed_build()
        body = client.get("/api/panel/builds/current").json()
        assert body["id"] == build_id
        assert body["panel_rows"] == 1_503_753
        assert body["series_count"] == 68_675

    def test_it_reports_observed_and_materialised_rows_separately(self, client) -> None:
        """An observed zero and a materialised zero are different facts."""
        self._seed_completed_build()
        body = client.get("/api/panel/builds/current").json()
        assert body["observed_rows"] == 634_951
        assert body["materialised_zero_rows"] == 868_802
        assert body["observed_rows"] + body["materialised_zero_rows"] == body["panel_rows"]

    def test_the_summary_distinguishes_the_two_target_sources(self, client) -> None:
        self._seed_completed_build()
        summary = client.get("/api/panel/builds/current").json()["summary"]
        assert summary["target_source_rows"]["order"] == 994_526
        assert summary["target_source_rows"]["sales_proxy"] == 509_227

    def test_the_summary_separates_the_panel_universe_from_the_sales_control(
        self, client
    ) -> None:
        """68,675 is the panel; 63,210 remains a control on the sales file."""
        self._seed_completed_build()
        universe = client.get("/api/panel/builds/current").json()["summary"][
            "series_universe"
        ]
        assert universe["panel_series"] == 68_675
        assert universe["sales_control_series"] == 63_210
        assert universe["stock_only_pairs_excluded"] == 78_694

    def test_builds_are_listed_and_paginated(self, client) -> None:
        self._seed_completed_build()
        body = client.get("/api/panel/builds").json()
        assert body["total"] >= 1
        assert {"items", "total", "offset", "limit"} <= set(body)

    def test_detail_is_addressable_by_id(self, client) -> None:
        build_id = self._seed_completed_build()
        assert client.get(f"/api/panel/builds/{build_id}").json()["id"] == build_id

    def test_no_build_yet_returns_a_structured_404(self, client) -> None:
        response = client.get("/api/panel/builds/current")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_an_unknown_build_returns_404(self, client) -> None:
        assert client.get("/api/panel/builds/nope").status_code == 404
