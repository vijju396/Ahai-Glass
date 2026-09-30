"""model run horizon totals

The same backtest scored on the total the plan is held to - six months - rather
than on one period at a time. Stored on the row so the leaderboard and the
champion ranking read it instead of re-deriving it from `origins_json` on every
request.

Backfilled in place from `origins_json`, which is the same data a fresh run
would score, so an existing run gets the same numbers a retrain would give it.
A row whose origins were never stored keeps NULL metrics and 0 blocks, which is
the honest reading: not measured.

Revision ID: f3c71a90b2d4
Revises: a41c9b7f2d10
Create Date: 2026-09-22 00:00:00.000000+00:00
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = 'f3c71a90b2d4'
down_revision = 'a41c9b7f2d10'
branch_labels = None
depends_on = None


def _run_periods(bind) -> dict[str, int]:
    """How many forecast periods a six-month total spans, per training run.

    Not one number for the whole table. A run is scored on the grain it was
    trained at: six months is 6 rows on a monthly run and 26 on a weekly one,
    and using today's setting for both silently gives every older monthly run
    zero blocks - a 26-period window never fits inside a 6-period validation.
    The grain is read from the run's own stored origins, from the recorded
    `grain` where present and otherwise from the shape of the period labels
    (`2026-W13` is a week, `2026-03` is a month). A run whose grain cannot be
    read falls back to the deployment setting.
    """
    from app.core.config import get_settings
    from app.ml.features.grain import (
        grain_of_period,
        normalise_grain,
        periods_spanning_months,
    )

    default = normalise_grain(get_settings().panel_grain)
    periods: dict[str, int] = {}
    for run_id, raw in bind.execute(
        sa.text("SELECT id, origins_json FROM training_run")
    ).fetchall():
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = None
        origins = (raw or {}).get("origins") if isinstance(raw, dict) else raw
        grain = None
        for origin in origins or []:
            grain = origin.get("grain") or grain_of_period(
                origin.get("validation_start_period") or ""
            )
            if grain:
                break
        periods[str(run_id)] = periods_spanning_months(
            6, normalise_grain(grain) if grain else default
        )
    return periods


def upgrade() -> None:
    op.add_column('model_run', sa.Column('horizon_mape', sa.Float(), nullable=True))
    op.add_column('model_run', sa.Column('horizon_wape', sa.Float(), nullable=True))
    op.add_column(
        'model_run',
        sa.Column('horizon_blocks', sa.Integer(), nullable=False, server_default='0'),
    )

    from app.ml.evaluation.horizon_totals import horizon_totals

    bind = op.get_bind()
    periods_by_run = _run_periods(bind)
    from app.core.config import get_settings
    from app.ml.features.grain import grain_of_period, periods_spanning_months

    fallback = periods_spanning_months(6, get_settings().panel_grain)
    rows = bind.execute(
        sa.text(
            "SELECT id, training_run_id, origins_json FROM model_run "
            "WHERE origins_json IS NOT NULL AND status = 'completed'"
        )
    ).fetchall()
    for row_id, run_id, origins in rows:
        if isinstance(origins, str):
            try:
                origins = json.loads(origins)
            except ValueError:
                continue
        # The row's own grain first. Every stored origin carries a period
        # label, so the row can say what it was trained at even where the
        # parent run recorded nothing - and one run here did record nothing,
        # which would otherwise have left all 678 of its rows unscored.
        row_grain = next(
            (
                g
                for origin in origins or []
                if (g := grain_of_period(origin.get("train_end_period") or ""))
            ),
            None,
        )
        periods = (
            periods_spanning_months(6, row_grain)
            if row_grain
            else periods_by_run.get(str(run_id), fallback)
        )
        totals = horizon_totals(origins, periods)
        if not totals.blocks:
            continue
        bind.execute(
            sa.text(
                "UPDATE model_run SET horizon_mape = :mape, horizon_wape = :wape, "
                "horizon_blocks = :blocks WHERE id = :id"
            ),
            {
                "mape": totals.mape,
                "wape": totals.wape,
                "blocks": totals.blocks,
                "id": row_id,
            },
        )


def downgrade() -> None:
    op.drop_column('model_run', 'horizon_blocks')
    op.drop_column('model_run', 'horizon_wape')
    op.drop_column('model_run', 'horizon_mape')
