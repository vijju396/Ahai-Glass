"""Application settings.

Every value is overridable by an environment variable or `backend/.env`, so
nothing operationally significant is hardcoded. The SQLite URL is the POC
default; setting `AIS_DATABASE_URL` to a PostgreSQL DSN is the only change
needed to move engines (see docs/ARCHITECTURE.md SS4).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIS_",
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "AIS Glass Forecast & Inventory Intelligence"
    app_version: str = "0.1.0"
    environment: str = "local"
    debug: bool = False

    # --- paths -------------------------------------------------------------
    project_root: Path = PROJECT_ROOT
    source_data_dir: Path = PROJECT_ROOT / "data" / "source"
    runtime_dir: Path = PROJECT_ROOT / "runtime"

    # --- persistence -------------------------------------------------------
    # SQLite for the POC. A PostgreSQL DSN here needs no code change: the
    # repository layer is engine-agnostic and every migration is Alembic-managed.
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'runtime' / 'db' / 'ais.db').as_posix()}"
    sqlite_wal: bool = True
    db_echo: bool = False

    # --- MLflow ------------------------------------------------------------
    mlflow_tracking_uri: str = (
        f"sqlite:///{(PROJECT_ROOT / 'runtime' / 'mlflow' / 'mlflow.db').as_posix()}"
    )
    mlflow_artifact_root: Path = PROJECT_ROOT / "runtime" / "mlflow" / "artifacts"
    mlflow_experiment: str = "ais-glass-forecast"
    mlflow_enabled: bool = True

    # --- CORS: the React dev origin only ----------------------------------
    frontend_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # --- ingestion ---------------------------------------------------------
    upload_max_bytes: int = 512 * 1024 * 1024
    # Structural controls from docs/VALIDATION_REPORT.md SS1. A breach never
    # continues silently; it surfaces in Data Studio and the validation report.
    expected_sales_rows: int = 1_703_042
    expected_order_rows: int = 775_912
    expected_stock_rows: int = 144_921
    expected_product_master_rows: int = 2_417
    expected_location_master_rows: int = 57
    expected_sales_skus: int = 2_260
    expected_series: int = 63_210
    expected_normalized_depots: int = 53
    control_tolerance_pct: float = 0.5

    # --- forecasting -------------------------------------------------------
    forecast_horizon_months: int = 6
    service_levels: list[int] = Field(default_factory=lambda: [80, 90, 95])
    random_seed: int = 42
    # "reference" honours the reference projects' thresholds exactly, which
    # leaves 6 of 13 models Ineligible at monthly grain. "monthly_relaxed" is
    # the documented opt-in deviation. docs/DECISIONS.md-001.
    min_history_profile: str = "reference"
    # "thorough" = Meriton's GridSearchCV; "fast" = Sodexo's fixed parameters.
    xgboost_training_profile: str = "thorough"

    # --- training budget (measured; docs/ARCHITECTURE.md SS6) --------------
    max_local_series: int = 500
    local_series_selection: str = "value"  # value | volume | shortfall
    per_model_timeout_seconds: float = 120.0
    lstm_timeout_seconds: float = 300.0
    max_training_workers: int = 4

    #: Which metric orders the leaderboard and picks the champion: "mape" or
    #: "wape". Both are computed and shown either way. MAPE is the default so
    #: the ranking agrees with the reported accuracy, which is 100 - MAPE
    #: (docs/DECISIONS.md D-043).
    champion_primary_metric: str = "mape"

    #: Locations this deployment reports on, across every screen. Empty means
    #: "whatever the active training run covered" (see
    #: `app/domain/ais/workspace.py`), which for an unrestricted run is every
    #: branch in the panel. Set as a comma-separated list, e.g.
    #: `AIS_WORKSPACE_BRANCHES=AHMEDABAD,BENGALURU`.
    #:
    #: This narrows what the application reports. Every restricted payload
    #: carries `workspace_scope` saying so - a KPI over 2 of 53 branches must
    #: never read as a national total (docs/DECISIONS.md D-049).
    workspace_branches: Annotated[list[str], NoDecode] = Field(default_factory=list)

    #: Products this deployment reports on, across every screen. Same contract
    #: as `workspace_branches` and independent of it: naming SKUs but no
    #: branches means "these products, every branch". Empty means whatever the
    #: active training run covered.
    workspace_skus: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- AI assistant ------------------------------------------------------
    #
    # These five are declared with `validation_alias` so BOTH spellings work:
    # the unprefixed names the operator is given in `.env.example`
    # (`OPENAI_API_KEY=`), and this project's own `AIS_` convention
    # (`AIS_OPENAI_API_KEY=`). Every other setting here is `AIS_`-prefixed, and
    # forcing an operator to guess that the OpenAI key needs a vendor prefix is
    # the kind of small friction that ends with the key pasted somewhere worse.
    #
    # The key is read from `backend/.env` only. It is never exposed through any
    # response, never logged, and never reaches a `VITE_` variable - the browser
    # talks to this backend, and only this backend talks to OpenAI.
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "AIS_OPENAI_API_KEY"),
    )
    #: gpt-4.1-mini: current, documented, supports tool/function calling, and
    #: roughly an order of magnitude cheaper per token than the frontier models
    #: while being more than capable of turning already-computed facts into a
    #: short paragraph - which is the whole job here. Configurable.
    openai_model: str = Field(
        default="gpt-4.1-mini",
        validation_alias=AliasChoices("OPENAI_MODEL", "AIS_OPENAI_MODEL"),
    )
    ai_assistant_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("AI_ASSISTANT_ENABLED", "AIS_AI_ASSISTANT_ENABLED"),
    )
    ai_max_output_tokens: int = Field(
        default=900,
        validation_alias=AliasChoices("AI_MAX_OUTPUT_TOKENS", "AIS_AI_MAX_OUTPUT_TOKENS"),
    )
    ai_request_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("AI_REQUEST_TIMEOUT_SECONDS", "AIS_AI_REQUEST_TIMEOUT_SECONDS"),
    )

    #: Sampling temperature for the call that WRITES the answer. Set to 2.0 on
    #: request. OpenAI's range is 0.0-2.0, and 2.0 is the maximum: token choice
    #: is close to uniform over the distribution, so prose is far more varied
    #: and markedly less reliable than at 0. Two consequences worth knowing:
    #: the same question can produce noticeably different answers, and the
    #: grounding rules in the system prompt are followed less consistently -
    #: which is exactly the risk in an application whose contract is never to
    #: state a number it did not measure. Lower it here if answers drift.
    ai_temperature: float = Field(
        default=2.0,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices("AI_TEMPERATURE", "AIS_AI_TEMPERATURE"),
    )

    #: Temperature for a call that EXPLAINS a fixed set of figures.
    #:
    #: Separate from `ai_temperature`, and low, because the two calls want
    #: opposite things. A conversational answer can afford variety. An
    #: explanation has one job - restate measured numbers clearly - and at 2.0
    #: it measurably fails: the first live drift explanation came back as
    #: "pastly observed sales and means average facts consumyac extrem
    #: acDemand unde ganho.solatu fort..." - four languages and no meaning
    #: (docs/DECISIONS.md D-061).
    #:
    #: Raise it if you want livelier prose; the coherence guard in
    #: `app/services/assistant/quality.py` will still reject an unusable one.
    ai_explanation_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices(
            "AI_EXPLANATION_TEMPERATURE", "AIS_AI_EXPLANATION_TEMPERATURE"
        ),
    )

    #: Temperature for the call that CHOOSES which tools to run. Deliberately
    #: separate, and deliberately 0. That call emits no prose - it emits
    #: function names and JSON arguments, where randomness does not read as
    #: variety, it reads as the assistant answering a different question than
    #: the one asked, or as malformed arguments the API rejects.
    ai_tool_choice_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices(
            "AI_TOOL_CHOICE_TEMPERATURE", "AIS_AI_TOOL_CHOICE_TEMPERATURE"
        ),
    )

    # --- inventory ---------------------------------------------------------
    review_period_days: int = 30
    default_lead_time_days: float = 3.0
    stock_snapshot_date: str = "2026-08-01"

    @field_validator("min_history_profile")
    @classmethod
    def _check_profile(cls, value: str) -> str:
        allowed = {"reference", "monthly_relaxed"}
        if value not in allowed:
            raise ValueError(f"min_history_profile must be one of {sorted(allowed)}")
        return value

    @field_validator("workspace_branches", "workspace_skus", mode="before")
    @classmethod
    def _split_workspace_list(cls, value: Any) -> Any:
        """Accept a comma-separated list, not only JSON.

        pydantic-settings JSON-decodes a `list[str]` env var **in the source**,
        before any validator runs, so `AIS_WORKSPACE_BRANCHES=AHMEDABAD,BENGALURU`
        raised rather than reading as two names - the form anyone would
        actually write, and the form documented in `.env`. `NoDecode` on the
        field turns that source-level decoding off so this runs instead. JSON
        still works, because a value starting with `[` is passed through.
        """
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                # `NoDecode` turned the source-level JSON decoding off, so a
                # JSON value has to be decoded here or it stays a string.
                import json

                return json.loads(text)
            return [part.strip() for part in text.split(",") if part.strip()]
        return value

    @field_validator("champion_primary_metric")
    @classmethod
    def _check_primary_metric(cls, value: str) -> str:
        allowed = {"mape", "wape"}
        if value not in allowed:
            raise ValueError(f"champion_primary_metric must be one of {sorted(allowed)}")
        return value

    @field_validator("xgboost_training_profile")
    @classmethod
    def _check_xgb_profile(cls, value: str) -> str:
        allowed = {"thorough", "fast"}
        if value not in allowed:
            raise ValueError(
                f"xgboost_training_profile must be one of {sorted(allowed)}"
            )
        return value

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.runtime_dir / "db",
            self.runtime_dir / "logs",
            self.runtime_dir / "mlflow" / "artifacts",
            self.runtime_dir / "storage" / "raw",
            self.runtime_dir / "storage" / "prepared",
            self.runtime_dir / "storage" / "profiles",
            self.runtime_dir / "storage" / "models",
            self.runtime_dir / "storage" / "forecasts",
            self.runtime_dir / "storage" / "reports",
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
