"""ORM model registry.

Importing this package registers every table on `Base.metadata`, which Alembic
autogeneration and the test fixtures both rely on.
"""

from app.models.champions import ChampionSelection
from app.models.forecasts import ForecastRow, ForecastRun
from app.models.datasets import (
    ColumnProfile,
    ControlOutcome,
    Dataset,
    DatasetVersion,
    DefectRecord,
    DefectSeverity,
    IngestionStatus,
    KeyReconciliation,
    SourceFile,
    ValidationControl,
)
from app.models.mappings import (
    ColumnRoleAssignment,
    MappingRuleResult,
    MappingVersion,
    PreprocessingRun,
)
from app.models.panel import PanelBuild
from app.models.training import (
    ModelRun,
    QuantileCalibration,
    TrainingRun,
)

__all__ = [
    "ChampionSelection",
    "ColumnProfile",
    "ColumnRoleAssignment",
    "ControlOutcome",
    "Dataset",
    "DatasetVersion",
    "DefectRecord",
    "DefectSeverity",
    "ForecastRow",
    "ForecastRun",
    "IngestionStatus",
    "KeyReconciliation",
    "MappingRuleResult",
    "MappingVersion",
    "ModelRun",
    "PanelBuild",
    "PreprocessingRun",
    "QuantileCalibration",
    "SourceFile",
    "TrainingRun",
    "ValidationControl",
]
