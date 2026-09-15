"""LSTM.

The only one of the 13 with no `_exog` sibling in either reference, so none is
invented here - that would make it a fourteenth model.

Synthesised from both references, as recorded in docs/MODEL_INVENTORY.md SS2.13:

- **Meriton's 64-unit layer** (`training_service.py:1235`) rather than Sodexo's
  32. More capacity is safe precisely because of the next point.
- **Sodexo's `EarlyStopping(monitor="loss", patience=8,
  restore_best_weights=True)`** (`models.py:313`), which Meriton lacks - it runs
  a fixed 25 epochs with no stopping criterion and can overfit or waste epochs.
- `epochs=80, batch_size=16, shuffle=False` from Sodexo.
- `MinMaxScaler` fitted on the **training target only**, in both.
- `set_random_seed` plus best-effort op-determinism, identical in both.
- Sequence window `min(12, max(3, len // 4))` - Meriton uses 30 and Sodexo 42,
  both sized for daily/half-day grain. At monthly grain with at most 22
  training rows, 12 is the largest window that leaves anything to train on.

**The recursion policy differs from both references.** Their loops append the
*actual* value when the output frame carries one (`Meriton :1257`,
`Sodexo :327`), which on a validation fold makes each step one-step-ahead.
AIS defaults to feeding the model's own predictions, so a six-month fold is a
genuine six-month forecast. `context.allow_actuals_in_recursion=True`
reproduces the reference exactly, for parity tests
(docs/DECISIONS.md D-031).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.ml.adapters.base import ForecastModelAdapter, ModelContext

#: Meriton's layer width (`training_service.py:1235`).
DEFAULT_UNITS = 64
#: Sodexo's training schedule (`models.py:307-315`).
DEFAULT_EPOCHS = 80
DEFAULT_BATCH_SIZE = 16
#: Sodexo's EarlyStopping patience.
DEFAULT_PATIENCE = 8
#: Window ceiling at monthly grain. See the module docstring.
MAX_SEQUENCE_LENGTH = 12


class LstmAdapter(ForecastModelAdapter):
    model_id = "lstm"
    display_name = "LSTM"
    dependency_module = "tensorflow"
    family = "neural_network"
    requires_exogenous = False
    uses_fast_holdout = True

    def _history_thresholds(self) -> dict[str, int]:
        # The reference gate is `len > sequence_length + 2`. With the window
        # auto-sized from history, a floor of 14 keeps the smallest usable
        # window (3) meaningful while admitting AIS's 18-22 row windows.
        return {"reference": 14, "monthly_relaxed": 14}

    def __init__(self, context: ModelContext | None = None) -> None:
        super().__init__(context)
        self._model: Any = None
        self._scaler: Any = None
        self._sequence_length = 0
        self._scaled_history: list[float] = []
        self._epochs_run: int | None = None

    def _sequence_length_for(self, observations: int) -> int:
        return min(MAX_SEQUENCE_LENGTH, max(3, observations // 4))

    def _fit(self, train_df: pd.DataFrame, context: ModelContext) -> None:
        from sklearn.preprocessing import MinMaxScaler
        from tensorflow.keras.callbacks import EarlyStopping
        from tensorflow.keras.layers import LSTM, Dense, Input
        from tensorflow.keras.models import Sequential
        from tensorflow.keras.utils import set_random_seed

        set_random_seed(context.random_seed)
        try:
            import tensorflow as tf

            tf.config.experimental.enable_op_determinism()
        except (AttributeError, RuntimeError):
            # Best-effort in both references; some builds do not support it.
            pass

        values = pd.to_numeric(train_df["target"], errors="coerce").astype(float)
        self._sequence_length = self._sequence_length_for(len(values))
        if len(values) <= self._sequence_length + 2:
            raise ValueError(
                f"Not enough rows for LSTM sequence training: {len(values)} "
                f"observations against a window of {self._sequence_length}."
            )

        # Fitted on the training target only - never on validation or horizon
        # rows. Identical in both references.
        self._scaler = MinMaxScaler()
        scaled = self._scaler.fit_transform(values.to_frame()).reshape(-1)

        x_train: list[np.ndarray] = []
        y_train: list[float] = []
        for index in range(self._sequence_length, len(scaled)):
            x_train.append(scaled[index - self._sequence_length : index])
            y_train.append(scaled[index])
        x = np.array(x_train).reshape((-1, self._sequence_length, 1))
        y = np.array(y_train)

        model = Sequential(
            [
                Input((self._sequence_length, 1)),
                LSTM(DEFAULT_UNITS),
                Dense(1),
            ]
        )
        model.compile(loss="mse", optimizer="adam")
        history = model.fit(
            x,
            y,
            epochs=DEFAULT_EPOCHS,
            batch_size=DEFAULT_BATCH_SIZE,
            verbose=0,
            shuffle=False,
            callbacks=[
                EarlyStopping(
                    monitor="loss",
                    patience=DEFAULT_PATIENCE,
                    restore_best_weights=True,
                )
            ],
        )
        self._model = model
        self._epochs_run = len(history.history.get("loss", []))
        self._scaled_history = list(scaled)

    def _predict(self, horizon_df: pd.DataFrame, context: ModelContext) -> Any:
        history = list(self._scaled_history)
        predictions: list[float] = []
        for _, row in horizon_df.iterrows():
            window = np.array(history[-self._sequence_length :]).reshape(
                (1, self._sequence_length, 1)
            )
            predicted_scaled = float(self._model(window, training=False).numpy()[0][0])
            predictions.append(
                float(self._scaler.inverse_transform([[predicted_scaled]])[0][0])
            )
            actual = row.get("target")
            if (
                context.allow_actuals_in_recursion
                and actual is not None
                and not pd.isna(actual)
            ):
                history.append(
                    float(self._scaler.transform([[float(actual)]])[0][0])
                )
            else:
                # AIS default: the walk feeds its own prediction, so a six-month
                # fold is a genuine six-month forecast.
                history.append(predicted_scaled)
        return predictions

    def parameter_metadata(self) -> dict[str, Any]:
        return {
            "units": DEFAULT_UNITS,
            "dense_units": 1,
            "loss": "mse",
            "optimizer": "adam",
            "epochs_configured": DEFAULT_EPOCHS,
            "epochs_run": self._epochs_run,
            "batch_size": DEFAULT_BATCH_SIZE,
            "shuffle": False,
            "early_stopping": {
                "monitor": "loss",
                "patience": DEFAULT_PATIENCE,
                "restore_best_weights": True,
            },
            "sequence_length": self._sequence_length,
            "scaler": "MinMaxScaler on the training target only",
            "random_seed": self.context.random_seed,
            "allow_actuals_in_recursion": self.context.allow_actuals_in_recursion,
            "evaluation_policy": "single chronological holdout (expensive-model policy)",
            "ported_from": (
                "Meriton training_service.py:1235 (64 units) + "
                "Sodexo models.py:313 (EarlyStopping patience 8)"
            ),
        }

    def feature_metadata(self) -> list[str]:
        return [f"target_lag_{index}" for index in range(self._sequence_length, 0, -1)]

    def save(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Keras native format, not pickle: a Keras model is not reliably
        # picklable across versions.
        self._model.save(destination.with_suffix(".keras"))
        destination.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "sequence_length": self._sequence_length,
                    "scaled_history": self._scaled_history,
                    "epochs_run": self._epochs_run,
                    "scaler_min": self._scaler.min_.tolist(),
                    "scaler_scale": self._scaler.scale_.tolist(),
                    "scaler_data_min": self._scaler.data_min_.tolist(),
                    "scaler_data_max": self._scaler.data_max_.tolist(),
                }
            ),
            encoding="utf-8",
        )

    def load(self, source: Path) -> None:
        import numpy as np_local
        from sklearn.preprocessing import MinMaxScaler
        from tensorflow.keras.models import load_model

        self._model = load_model(source.with_suffix(".keras"))
        meta = json.loads(source.with_suffix(".meta.json").read_text(encoding="utf-8"))
        self._sequence_length = meta["sequence_length"]
        self._scaled_history = [float(v) for v in meta["scaled_history"]]
        self._epochs_run = meta["epochs_run"]

        scaler = MinMaxScaler()
        scaler.min_ = np_local.array(meta["scaler_min"])
        scaler.scale_ = np_local.array(meta["scaler_scale"])
        scaler.data_min_ = np_local.array(meta["scaler_data_min"])
        scaler.data_max_ = np_local.array(meta["scaler_data_max"])
        scaler.data_range_ = scaler.data_max_ - scaler.data_min_
        scaler.n_features_in_ = 1
        self._scaler = scaler

        self._fitted = True
        self.diagnostics.fitted = True
