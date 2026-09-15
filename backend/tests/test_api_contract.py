"""FastAPI response-contract tests for the Phase 1 surface."""

from __future__ import annotations


def test_health_returns_component_breakdown(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded", "error"}
    assert body["app_name"]
    names = {component["name"] for component in body["components"]}
    assert {"database", "model_registry", "source_data", "ml_dependencies"} <= names


def test_health_reports_registry_ok(client) -> None:
    body = client.get("/api/health").json()
    registry = next(c for c in body["components"] if c["name"] == "model_registry")
    assert registry["status"] == "ok"
    assert "13" in (registry["detail"] or "")


def test_models_endpoint_returns_all_thirteen_in_order(client) -> None:
    response = client.get("/api/models")
    assert response.status_code == 200
    body = response.json()
    assert body["official_model_count"] == 13
    assert len(body["models"]) == 13
    assert [m["model_id"] for m in body["models"]] == [
        "sarimax", "sarimax_exog", "auto_arima", "auto_arima_exog",
        "xgboost", "xgboost_exog", "exp_additive", "exp_additive_damped",
        "exp_multiplicative", "exp_multiplicative_damped", "var", "var_exog",
        "lstm",
    ]
    assert [m["rank"] for m in body["models"]] == list(range(1, 14))


def test_models_endpoint_carries_display_names_and_eligibility_metadata(client) -> None:
    models = {m["model_id"]: m for m in client.get("/api/models").json()["models"]}
    assert models["sarimax"]["display_name"] == "SARIMAX"
    assert models["lstm"]["display_name"] == "LSTM"
    assert models["auto_arima"]["min_required_history"] == 24
    assert models["sarimax"]["min_required_history"] == 12
    assert models["auto_arima"]["uses_fast_holdout"] is True
    assert models["sarimax"]["uses_fast_holdout"] is False
    assert models["xgboost"]["supports_pooled_training"] is True
    assert models["sarimax"]["supports_pooled_training"] is False
    assert models["var_exog"]["requires_exogenous"] is True


def test_models_endpoint_separates_baselines_from_the_thirteen(client) -> None:
    body = client.get("/api/models").json()
    baseline_ids = {b["method_id"] for b in body["baselines"]}
    model_ids = {m["model_id"] for m in body["models"]}
    assert baseline_ids == {"naive", "seasonal_naive", "ma3", "ma6"}
    assert not baseline_ids & model_ids


def test_models_endpoint_explains_the_ineligibility_reality(client) -> None:
    notes = " ".join(client.get("/api/models").json()["notes"]).lower()
    assert "q80" in notes and "not additional models" in notes
    assert "baseline" in notes


def test_unknown_route_returns_the_structured_error_shape(client) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert "correlation_id" in error


def test_openapi_document_is_generated(client) -> None:
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/api/models" in response.json()["paths"]


def test_correlation_id_is_echoed(client) -> None:
    response = client.get("/api/health", headers={"X-Correlation-ID": "abc123"})
    assert response.headers["X-Correlation-ID"] == "abc123"


class TestContractMatchesTheAdapters:
    """The API must not advertise a requirement the model does not enforce.

    Phase 5 removed a duplicated threshold table from the contract service for
    exactly this reason; these tests keep the two bound together.
    """

    def test_advertised_minimum_history_equals_the_enforced_minimum(self, client) -> None:
        from app.ml.adapters.base import ModelContext
        from app.ml.registry.model_registry import MODEL_REGISTRY

        body = client.get("/api/models").json()
        profile = body["min_history_profile"]
        for descriptor in body["models"]:
            adapter = MODEL_REGISTRY[descriptor["model_id"]](
                ModelContext(min_history_profile=profile)
            )
            assert descriptor["min_required_history"] == adapter.min_required_history(), (
                f"{descriptor['model_id']}: API says "
                f"{descriptor['min_required_history']}, adapter enforces "
                f"{adapter.min_required_history()}"
            )

    def test_advertised_capabilities_equal_the_adapter_flags(self, client) -> None:
        from app.ml.registry.model_registry import MODEL_REGISTRY

        for descriptor in client.get("/api/models").json()["models"]:
            adapter = MODEL_REGISTRY[descriptor["model_id"]]
            assert descriptor["requires_exogenous"] == adapter.requires_exogenous
            assert descriptor["supports_pooled_training"] == adapter.supports_pooled_training
            assert descriptor["uses_fast_holdout"] == adapter.uses_fast_holdout
            assert descriptor["dependency_module"] == adapter.dependency_module
            assert descriptor["display_name"] == adapter.display_name
            assert descriptor["family"] == adapter.family

    def test_the_helper_agrees_with_the_route(self, client) -> None:
        from app.services.model_contract_service import min_required_history

        body = client.get("/api/models").json()
        for descriptor in body["models"]:
            assert descriptor["min_required_history"] == min_required_history(
                descriptor["model_id"], body["min_history_profile"]
            )
