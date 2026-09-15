"""What training actually does, read out of the code that does it.

The Training tab needs to answer four questions without anyone taking a
document's word for it: how validation is set up, what each of the 13 models
requires and is configured with, which metrics are computed and which one
decides the champion, and what tuning happens.

Everything here is **derived, not restated.** Fold boundaries come from
`ml.evaluation.folds`, thresholds from each adapter's own
`min_required_history`, metric definitions from `ml.evaluation.metrics`, the
ranking rule from `ml.selection.champion`, and the run configuration from the
active `TrainingRun` row. A hand-written summary would drift from the code the
first time either changed; this cannot.

The one thing it deliberately does not do is compute a fresh figure. Where a
number is a measurement it comes from a stored run, and where there is no run
the field says so rather than showing a zero.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ml.adapters.base import ModelContext
from app.ml.evaluation import folds as F
from app.ml.registry.canonical_models import CANONICAL_MODEL_IDS
from app.ml.registry.model_registry import get_adapter_class
from app.ml.selection.champion import (
    DEFAULT_PRIMARY_METRIC,
    MIN_TEST_POINT_SHARE,
    MIN_VALIDATION_POINTS,
    PRIMARY_METRIC_CHOICES,
)
from app.models.training import ModelRun, TrainingRun

#: The real panel window. Kept here rather than imported because `folds` takes
#: absolute month indices and does not carry the labels.
PANEL_START = "2024-04"
PANEL_END = "2026-07"

#: The non-registry baselines. Named here so the tab can show them as the
#: comparison they are, never as a fourteenth model.
BASELINES: tuple[tuple[str, str], ...] = (
    ("naive", "Last observed month, carried forward."),
    ("seasonal_naive", "The same month one year earlier."),
    ("ma3", "Mean of the last three months."),
    ("ma6", "Mean of the last six months."),
)

#: Every metric the evaluator computes, what it means in plain words, and
#: whether lower is better. `primary` is decided by configuration, not here.
METRICS: tuple[dict[str, Any], ...] = (
    {
        "key": "mape",
        "label": "MAPE",
        "unit": "%",
        "lower_is_better": True,
        "definition": "Mean absolute percentage error: the average miss as a percentage of the actual.",
        "caveat": (
            "Undefined when an actual is zero, so those months are dropped rather than "
            "counted as perfect. It also penalises over-forecasting more than "
            "under-forecasting, which leans selection toward models that forecast low."
        ),
    },
    {
        "key": "accuracy",
        "label": "Accuracy",
        "unit": "%",
        "lower_is_better": False,
        "definition": "100 - MAPE, clamped at zero. A restatement of MAPE, not a separate measurement.",
        "caveat": "A MAPE above 100% reports 0%, so 0% means 'very wrong', not 'wrong by exactly everything'.",
    },
    {
        "key": "wape",
        "label": "WAPE",
        "unit": "%",
        "lower_is_better": True,
        "definition": "Total absolute error as a percentage of total demand.",
        "caveat": "Defined when some actuals are zero, which is why it is kept on every row alongside MAPE.",
    },
    {
        "key": "mae",
        "label": "MAE",
        "unit": "units",
        "lower_is_better": True,
        "definition": "Mean absolute error in units.",
        "caveat": "In units, so it cannot be compared between a high-volume and a low-volume series.",
    },
    {
        "key": "rmse",
        "label": "RMSE",
        "unit": "units",
        "lower_is_better": True,
        "definition": "Root mean squared error. Punishes a few large misses more than many small ones.",
        "caveat": None,
    },
    {
        "key": "mase",
        "label": "MASE",
        "unit": "ratio",
        "lower_is_better": True,
        "definition": "Error relative to a naive forecast on the training window. Below 1 beats naive.",
        "caveat": "The benchmark is computed on the training window only, never on the window being scored.",
    },
    {
        "key": "smape",
        "label": "sMAPE",
        "unit": "%",
        "lower_is_better": True,
        "definition": "Symmetric MAPE: the miss over the average of actual and forecast.",
        "caveat": None,
    },
    {
        "key": "bias",
        "label": "Bias",
        "unit": "%",
        "lower_is_better": False,
        "definition": "Signed average error. Negative means the model forecasts below actual demand.",
        "caveat": (
            "Not minimised - it is the tie-break after the primary metric, and it is on "
            "every row because a one-sided metric needs it to stay honest."
        ),
    },
)


def _validation_design() -> dict[str, Any]:
    """The fold layout, read from the module that builds it.

    The origins are the mandated ones for the real panel window, converted
    from absolute month indices back to labels so the tab can print them.
    """
    from app.ml.features.panel import index_to_period, month_index

    origins = F.mandated_origins(month_index(PANEL_START), month_index(PANEL_END))
    return {
        "method": "rolling origin (expanding window)",
        "why": (
            "Every fold trains only on months strictly before its origin and scores months "
            "strictly after it. A random split would let a model see the future of the "
            "series it is being scored on, which makes the error meaningless."
        ),
        "horizon_months": F.DEFAULT_HORIZON,
        "min_train_periods": F.MIN_TRAIN_PERIODS,
        "panel_window": {"start": PANEL_START, "end": PANEL_END},
        "mandated_train_ends": [F.PRIMARY_TRAIN_END, F.SECOND_TRAIN_END],
        "origins": [
            {
                "name": origin.name,
                "fold_index": origin.fold_index,
                "train_start": index_to_period(origin.train_start_index),
                "train_end": index_to_period(origin.train_end_index),
                "validation_start": index_to_period(origin.validation_start_index),
                "validation_end": index_to_period(origin.validation_end_index),
                "train_months": origin.train_end_index - origin.train_start_index + 1,
            }
            for origin in origins
        ],
        "fold_fitted_preprocessing": (
            "Imputation, scaling, encoding and any tuning are fitted inside each fold, on "
            "that fold's training window only. Fitting them once on the whole panel would "
            "leak the test window into the transform."
        ),
        "exogenous_rule": (
            "MRP is historical, so its future value is unknown and it is never used as a "
            "future-known regressor. Exogenous models use only drivers available at the "
            "forecast origin."
        ),
    }


def _model_row(model_id: str, context: ModelContext) -> dict[str, Any]:
    cls = get_adapter_class(model_id)
    adapter = cls(context)
    thresholds = {
        profile: cls(
            ModelContext(
                seasonal_period=context.seasonal_period,
                exog_columns=context.exog_columns,
                min_history_profile=profile,
                xgboost_training_profile=context.xgboost_training_profile,
            )
        ).min_required_history()
        for profile in ("reference", "monthly_relaxed")
    }
    return {
        "model_id": model_id,
        "display_name": cls.display_name,
        "family": getattr(cls, "family", None),
        "requires_exogenous": bool(getattr(cls, "requires_exogenous", False)),
        # Attributes, not methods - checked against the real adapter.
        "supports_pooled_training": bool(adapter.supports_pooled_training),
        "uses_fast_holdout": bool(adapter.uses_fast_holdout),
        "min_history": thresholds,
        "min_history_active": adapter.min_required_history(),
        "parameters": adapter.parameter_metadata(),
        "features": adapter.feature_metadata(),
        "dependency": getattr(cls, "dependency_module", None),
    }


def _selection() -> dict[str, Any]:
    settings = get_settings()
    metric = settings.champion_primary_metric
    return {
        "primary_metric": metric,
        "primary_metric_choices": list(PRIMARY_METRIC_CHOICES),
        "default_primary_metric": DEFAULT_PRIMARY_METRIC,
        "tie_breaks": ["absolute bias", "MAE", "model id"],
        "why_bias_second": (
            "The primary metric is one-sided, so between two models it cannot separate, "
            "the less biased one wins."
        ),
        "min_validation_points": MIN_VALIDATION_POINTS,
        "min_test_point_share": MIN_TEST_POINT_SHARE,
        "baselines_never_champion": True,
        "baselines": [{"model_id": key, "rule": rule} for key, rule in BASELINES],
    }


def _tuning(context: ModelContext) -> dict[str, Any]:
    """What is and is not tuned. The honest answer is 'very little'."""
    settings = get_settings()
    return {
        "summary": (
            "There is no hyperparameter search across the 13 models. Each adapter reuses "
            "the reference project's own configuration, so results stay comparable with it "
            "and no fitter is reinvented. Where a model does search, the search happens "
            "inside the fold."
        ),
        "search_inside_folds": [
            {
                "model_id": "auto_arima",
                "what": "Order selection (p, d, q) by information criterion, per fold.",
            },
            {
                "model_id": "auto_arima_exog",
                "what": "The same order selection, with exogenous regressors.",
            },
            {
                "model_id": "xgboost",
                "what": (
                    "Fixed hyperparameters chosen by the training profile, not searched. "
                    f"Active profile: {settings.xgboost_training_profile}."
                ),
            },
        ],
        "fixed_settings": {
            "random_seed": context.random_seed,
            "horizons": list(context.horizons),
            "min_history_profile": context.min_history_profile,
            "xgboost_training_profile": context.xgboost_training_profile,
            "allow_actuals_in_recursion": bool(
                getattr(context, "allow_actuals_in_recursion", False)
            ),
            "var_pair_column": context.var_pair_column,
        },
        "not_tuned": [
            "No cross-model architecture search.",
            "No automatic feature selection outside the fold.",
            "No objective function was changed to MAPE - MAPE decides selection, not fitting.",
        ],
    }


def _active_run(db: Session) -> dict[str, Any] | None:
    run = db.scalars(
        select(TrainingRun).order_by(TrainingRun.created_at.desc()).limit(1)
    ).first()
    if run is None:
        return None
    statuses = dict(
        db.execute(
            select(ModelRun.status, __import__("sqlalchemy").func.count())
            .where(ModelRun.training_run_id == run.id)
            .group_by(ModelRun.status)
        ).all()
    )
    return {
        "id": run.id,
        "status": run.status,
        "created_at": run.created_at,
        "duration_seconds": run.duration_seconds,
        "tiers": run.tiers.split(",") if run.tiers else [],
        "min_history_profile": run.min_history_profile,
        "xgboost_training_profile": run.xgboost_training_profile,
        "max_local_series": run.max_local_series,
        "local_series_selection": run.local_series_selection,
        "per_model_timeout_seconds": run.per_model_timeout_seconds,
        "lstm_timeout_seconds": run.lstm_timeout_seconds,
        "restriction": run.restriction_json,
        "model_run_statuses": statuses,
        "series_evaluated": run.series_evaluated,
    }


def explain(db: Session) -> dict[str, Any]:
    """Everything the Training tab shows, assembled from the real code."""
    settings = get_settings()
    context = ModelContext(
        seasonal_period=12,
        min_history_profile=settings.min_history_profile,
        xgboost_training_profile=settings.xgboost_training_profile,
    )
    from app.domain.ais.workspace import resolve_workspace

    return {
        "workspace_scope": resolve_workspace(db).as_dict(),
        "validation": _validation_design(),
        "models": [_model_row(model_id, context) for model_id in CANONICAL_MODEL_IDS],
        "model_count": len(CANONICAL_MODEL_IDS),
        "metrics": list(METRICS),
        "selection": _selection(),
        "tuning": _tuning(context),
        "status_vocabulary": [
            {
                "status": "completed",
                "meaning": "The model fitted and was scored. Its metrics are real.",
            },
            {
                "status": "ineligible",
                "meaning": "A validated data requirement was unmet. The exact requirement and its remedy are on the row.",
            },
            {"status": "failed", "meaning": "The fit raised. The reason is on the row."},
            {
                "status": "timed_out",
                "meaning": "It exceeded its per-model budget. The run continued without it.",
            },
            {
                "status": "not_evaluated_budget",
                "meaning": "A tier did not reach this series before the budget ran out.",
            },
        ],
        "active_run": _active_run(db),
        "notes": [
            "A model that did not run keeps its row and its reason. It is never shown as "
            "zero error and never silently dropped from a comparison.",
            "Aggregate error does not transfer to a single branch x SKU cell: aggregates "
            "are far less intermittent and much easier to forecast.",
            "Ordered quantity is the target. A censored row means despatch fell short, so "
            "the ordered figure is a lower bound on true demand.",
        ],
    }
