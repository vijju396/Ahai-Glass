"""Champion selections, as an append-only history.

One table, and the append-only shape is the whole design. A selection row is
**never updated**: an override writes a new row that supersedes the previous
one, and a rollback writes another that supersedes the override. So

- the audit history is the table, not a second log that can drift from it,
- rollback is "make the superseded row's choice current again", which is a
  write rather than a deletion, and
- a forecast that recorded `champion_selection_id` can still resolve which
  choice was in force when it was produced, months later.

`is_active` is the one mutable field, and only in the sense that superseding a
row clears it. The pair (`scope_level`, `scope_key`) is unique among active
rows, enforced by a partial index rather than by convention.

The full ranking that produced the choice is stored in `ranking_json`, not
recomputed on read. A leaderboard rebuilt from today's rows would answer a
different question from the one the planner saw when they accepted it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UuidPkMixin

#: How a selection came about. `automatic` is the deterministic ranking;
#: `manual_override` requires a reason; `rollback` restores an earlier choice
#: and records which row it restored.
SELECTION_SOURCES: tuple[str, ...] = ("automatic", "manual_override", "rollback")

#: What a scope means. `overall` is the whole network; `region` and `branch` are
#: the geographic champions; `value_class` and `product_group` are the segment
#: champions - and they are named after the two columns the aggregate tier
#: actually groups by (`scope_builder.SEGMENT_COLUMNS`), not after a taxonomy
#: that exists only in prose. `series` is a single branch x SKU where the
#: evidence supports one.
#:
#: The Syntetos-Boylan demand segment is deliberately absent: it classifies an
#: individual series' sparsity, and an aggregate of many series does not have
#: one. It is used for quantile calibration, where it belongs.
SCOPE_KINDS: tuple[str, ...] = (
    "overall",
    "region",
    "branch",
    "value_class",
    "product_group",
    "series",
)

#: The scope kinds whose `model_run.scope_key` is written as `column=value`.
SEGMENT_SCOPE_KINDS: frozenset[str] = frozenset({"value_class", "product_group"})

#: A manual override must say why, and ten characters is the floor
#: (docs/API_CONTRACT.md §5). "because" is not a reason.
MIN_OVERRIDE_REASON_CHARS = 10


class ChampionSelection(Base, UuidPkMixin, TimestampMixin):
    """One champion decision for one scope. Append-only."""

    __tablename__ = "champion_selection"
    __table_args__ = (
        # Unique among *active* rows only: the superseded history for the same
        # scope must be allowed to accumulate. A partial index rather than a
        # plain constraint, and portable - `sqlite_where` and `postgresql_where`
        # carry the same predicate, so the PostgreSQL migration is a rename of
        # the dialect keyword and nothing more.
        Index(
            "uq_champion_active_scope",
            "scope_kind",
            "scope_key",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active"),
        ),
        Index("ix_champion_active", "is_active", "scope_kind", "scope_key"),
        Index("ix_champion_run", "training_run_id", "scope_kind"),
    )

    training_run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("training_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    scope_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    #: `NATIONAL` for overall; the branch, region, class or segment value
    #: otherwise; `branch|sku` for a series.
    scope_key: Mapped[str] = mapped_column(String(300), nullable=False)
    #: The scope level of the `model_run` rows this decision was made from, so
    #: a branch-level decision is never traced back to series-level metrics.
    evaluated_scope_level: Mapped[str | None] = mapped_column(String(20))

    champion_model_id: Mapped[str] = mapped_column(String(40), nullable=False)
    champion_display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    challenger_model_id: Mapped[str | None] = mapped_column(String(40))
    #: The legacy lowest-valid-MAPE winner, recorded beside the operational
    #: champion and never conflated with it (docs/DECISIONS.md D-011).
    legacy_champion_model_id: Mapped[str | None] = mapped_column(String(40))

    champion_model_run_id: Mapped[str | None] = mapped_column(String(32))
    champion_wape: Mapped[float | None] = mapped_column(Float)
    champion_mae: Mapped[float | None] = mapped_column(Float)
    champion_bias: Mapped[float | None] = mapped_column(Float)
    champion_validation_points: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    champion_evaluation_mode: Mapped[str | None] = mapped_column(String(30))

    #: A baseline can never be champion, but it can be better. Recorded so the
    #: leaderboard states it rather than implying otherwise.
    best_baseline_model_id: Mapped[str | None] = mapped_column(String(40))
    best_baseline_wape: Mapped[float | None] = mapped_column(Float)
    beaten_by_baseline: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    selection_source: Mapped[str] = mapped_column(
        String(20), default="automatic", nullable=False
    )
    #: Required, and length-checked, for `manual_override` and `rollback`.
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(String(120))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The row this one replaced, and - for a rollback - the row it restored.
    supersedes_id: Mapped[str | None] = mapped_column(String(32))
    restored_from_id: Mapped[str | None] = mapped_column(String(32))

    ranked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    excluded_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: The whole leaderboard as it stood, including the unranked rows and their
    #: reasons. Stored, not recomputed.
    ranking_json: Mapped[dict | None] = mapped_column(JSON)
    notes_json: Mapped[list | None] = mapped_column(JSON)

    training_run: Mapped["TrainingRun"] = relationship(  # noqa: F821
        back_populates="champion_selections"
    )
