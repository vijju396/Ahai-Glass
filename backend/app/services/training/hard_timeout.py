"""Real pre-emption for a fit that will not stop on its own.

Phase 6 recorded (`docs/DECISIONS.md` D-039) that its budget was an admission
gate and a post-hoc verdict, not a timeout: statsmodels, pmdarima, XGBoost and
TensorFlow spend their time inside C extensions where no Python-level timer can
interrupt them, a thread cannot be killed safely, and `signal.alarm` does not
exist on Windows. It named Phase 7 as the place to fix that. This is the fix.

**How.** The evaluation of one (scope, model) runs in a separate
`multiprocessing.Process`. The parent waits `timeout` seconds, and if the child
has not finished it calls `terminate()` - a real SIGTERM/TerminateProcess, which
stops a C extension mid-loop. The model reports `TIMED_OUT` and the run
continues.

**Why it is off by default.** A fresh interpreter must re-import the model's
dependency stack, and `spawn` is the only start method Windows has. Measured on
this machine:

| Dependency | Fresh-interpreter import | Model | Median fit | Overhead share |
|---|---|---|---|---|
| `tensorflow` | **12.16 s** | `lstm` | 10.9 s | **53%** |
| `pmdarima` | **5.22 s** | `auto_arima` | 1.2 s | **81%** |
| `statsmodels.tsa.api` | **4.20 s** | `sarimax` | 2.0 s | 68% |
| `xgboost` | **2.99 s** | `xgboost` | 1.4 s | 68% |
| `pandas` | 1.30 s | - | - | - |

These figures were expected to be around 1.5 s and are not. At 500 local
series, pre-empting `auto_arima` alone would spend 43 minutes importing
pmdarima. So the honest default is **off** - `DEFAULT_HARD_TIMEOUT_MODELS` is
empty - and pre-emption is opt-in per run.

Where it *is* worth paying: the aggregate tier is 69 series, so hard-timing
every model there costs a few minutes and bounds the one failure mode the
post-hoc verdict cannot - a fit that never returns and holds a worker thread
forever. The API therefore accepts `hard_timeout_models` per submission, and
the recommendation in `docs/ARCHITECTURE.md` §6 is to use it on the aggregate
tier and rely on the Phase 6 post-hoc verdict below that.

The alternative worth noting for later: a **pre-warmed process pool** pays each
import once per worker instead of once per fit, and a timeout terminates and
rebuilds the pool. That reduces the overhead to near zero in the common case.
It is not built here because it is a second concurrency mechanism alongside the
job runner, and adding one of those without needing it yet is how a POC grows a
scheduler it cannot explain.

**What the child returns.** Predictions and diagnostics, not a fitted model
object. A Keras model does not survive pickling, and the parent does not need
one: the child writes any artifact to disk itself and returns the path.
"""

from __future__ import annotations

import multiprocessing as mp
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.core.logging import get_logger

logger = get_logger(__name__)

#: Empty on purpose. See the measured overhead table above: on this machine a
#: fresh interpreter costs more than the fit it is protecting, for every one of
#: the 13. Pre-emption is requested per run instead.
DEFAULT_HARD_TIMEOUT_MODELS: frozenset[str] = frozenset()

#: The models worth pre-empting when a caller does opt in - the two whose fit
#: time has no upper bound at all, because `auto_arima`'s stepwise search can
#: iterate indefinitely, plus `lstm` whose fit is simply long.
RUNAWAY_RISK_MODELS: frozenset[str] = frozenset(
    {"auto_arima", "auto_arima_exog", "lstm"}
)


class HardTimeout(RuntimeError):
    """Raised in the parent when a child was terminated for overrunning."""

    def __init__(self, seconds: float, limit: float) -> None:
        super().__init__(
            f"the fit was terminated after {seconds:.1f}s against a hard limit of "
            f"{limit:.1f}s; the process was killed, so no partial result is used"
        )
        self.seconds = seconds
        self.limit = limit


@dataclass
class HardTimeoutOutcome:
    """What happened, including how long the interpreter cost."""

    value: Any = None
    timed_out: bool = False
    failed: bool = False
    failure_reason: str | None = None
    elapsed_seconds: float = 0.0
    overhead_seconds: float | None = None


def _child(fn: Callable[..., Any], payload: dict[str, Any], pipe) -> None:  # noqa: ANN001
    """Runs in the child. Reports when its imports finished, then the result."""
    started = time.perf_counter()
    try:
        result = fn(**payload)
        pipe.send(("ok", result, time.perf_counter() - started))
    except Exception as exc:  # noqa: BLE001 - relayed to the parent verbatim
        pipe.send(("error", f"{type(exc).__name__}: {exc}"[:500], None))
    finally:
        pipe.close()


def run_with_hard_timeout(
    fn: Callable[..., Any],
    payload: dict[str, Any],
    *,
    timeout: float,
    context: str = "fit",
) -> HardTimeoutOutcome:
    """Run `fn(**payload)` in a child process, killing it after `timeout`.

    `fn` must be importable by name in a fresh interpreter - a module-level
    function, not a closure or a lambda - because `spawn` pickles it by
    reference. A closure raises `PicklingError` here rather than mysteriously
    hanging, which is the failure mode worth having.

    Returns an outcome rather than raising, so one overrunning model never
    stops the run. `timed_out` and `failed` are distinct: the first is a budget
    verdict, the second is a broken fit.
    """
    started = time.perf_counter()
    ctx = mp.get_context("spawn")
    parent_pipe, child_pipe = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child, args=(fn, payload, child_pipe), daemon=True)
    process.start()
    child_pipe.close()

    try:
        if parent_pipe.poll(timeout):
            status, value, inner = parent_pipe.recv()
            process.join(timeout=5)
            elapsed = time.perf_counter() - started
            if status == "ok":
                return HardTimeoutOutcome(
                    value=value,
                    elapsed_seconds=elapsed,
                    overhead_seconds=None if inner is None else max(elapsed - inner, 0.0),
                )
            return HardTimeoutOutcome(
                failed=True, failure_reason=value, elapsed_seconds=elapsed
            )

        # Nothing arrived in time. Kill it for real.
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():  # pragma: no cover - only if terminate is ignored
            process.kill()
            process.join(timeout=5)
        elapsed = time.perf_counter() - started
        logger.warning(
            "hard_timeout",
            extra={"context": context, "limit": timeout, "elapsed": round(elapsed, 2)},
        )
        return HardTimeoutOutcome(
            timed_out=True,
            failure_reason=str(HardTimeout(elapsed, timeout)),
            elapsed_seconds=elapsed,
        )
    finally:
        parent_pipe.close()
        if process.is_alive():  # pragma: no cover - belt and braces
            process.terminate()


def measure_interpreter_overhead(module: str) -> float:
    """Seconds a fresh `spawn` interpreter needs to import `module`.

    Used to justify the default model set rather than asserting it. Called by
    `tests/test_training.py`, which records the figure instead of hardcoding an
    expectation about someone else's machine.
    """
    outcome = run_with_hard_timeout(
        _import_and_return, {"module": module}, timeout=120.0, context=f"import {module}"
    )
    if outcome.timed_out or outcome.failed:
        return float("nan")
    return outcome.elapsed_seconds


def _import_and_return(module: str) -> str:
    """Module-level so `spawn` can pickle it by reference."""
    import importlib

    importlib.import_module(module)
    return module
