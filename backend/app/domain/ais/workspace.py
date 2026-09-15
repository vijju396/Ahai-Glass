"""Which locations this workspace covers, resolved once for the whole app.

Every screen used to answer this question for itself. Demand Analytics and
Operational Exceptions read the panel, so they showed all 53 branches. The
Model Leaderboard and Forecast Explorer read a training run, so they showed
whichever branches that run reached. Supply Intelligence read the branch
dimension, so it showed every depot including the ones that hold no stock. The
three numbers disagreed, and nothing on any page said why.

This module makes it one answer, resolved in one place:

1. `AIS_WORKSPACE_BRANCHES` and `AIS_WORKSPACE_SKUS`, when an operator has
   named the locations and products explicitly. Those win over everything -
   they are a deliberate statement about what this deployment is for.
2. Otherwise the branches the active training run was restricted to. An app
   whose models cover two branches describing itself over fifty-three is the
   inconsistency this exists to remove.
3. Otherwise no restriction at all, which is the honest answer for an
   unrestricted run: every branch in the panel.

**This narrows what the application reports, so it must never be silent.**
Every restricted payload carries `workspace_scope`, naming the locations, where
the restriction came from, and how many branches are being left out. A KPI
computed over 2 of 53 branches that looks like a national total is exactly the
failure this repository's data-honesty rules exist to prevent
(docs/DECISIONS.md D-049).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import get_settings

#: Where a resolved scope came from. Reported verbatim on every payload.
SOURCE_SETTING = "setting"
SOURCE_TRAINING_RUN = "training_run"
SOURCE_UNRESTRICTED = "unrestricted"

#: The canonical SKU column, so `restrict` can cut both axes from one call.
SKU_COLUMN = "canonical_sku"


@dataclass(frozen=True)
class WorkspaceScope:
    """What every screen in this workspace is allowed to report on.

    Two independent axes. A branch restriction with no SKU restriction is
    valid and means "these branches, every product"; the reverse is equally
    valid. Both are reported separately so a reader can tell which one is
    narrowing what they are looking at.
    """

    branches: tuple[str, ...] | None
    source: str
    detail: str
    #: How many branches exist in the panel, when that is known. Kept so the
    #: payload can say "2 of 53" rather than just "2".
    total_branches: int | None = None
    skus: tuple[str, ...] | None = None
    total_skus: int | None = None

    @property
    def is_restricted(self) -> bool:
        return self.branches is not None or self.skus is not None

    def allows(self, branch: str | None) -> bool:
        """Whether a caller-supplied branch filter is inside this workspace."""
        if self.branches is None or branch is None:
            return True
        return branch.strip().upper() in {b.upper() for b in self.branches}

    def allows_sku(self, sku: str | None) -> bool:
        if self.skus is None or sku is None:
            return True
        return sku.strip().upper() in {s.upper() for s in self.skus}

    @staticmethod
    def _keep(frame: pd.DataFrame, column: str, wanted: tuple[str, ...]) -> pd.DataFrame:
        if frame.empty or column not in frame.columns:
            return frame
        upper = {w.upper() for w in wanted}
        return frame[frame[column].astype("string").str.upper().isin(upper)]

    def restrict(
        self, frame: pd.DataFrame, column: str, *, sku_column: str | None = None
    ) -> pd.DataFrame:
        """Cut a frame down to this workspace's locations and products.

        `sku_column` is optional and defaults to the canonical name, so an
        existing two-argument call keeps working and gains the SKU cut for
        free wherever that column is present. A missing column is left alone
        rather than raising: some frames on the way to a screen genuinely have
        no branch or no SKU axis, and a workspace restriction is not a reason
        to break them.
        """
        out = frame
        if self.branches is not None:
            out = self._keep(out, column, self.branches)
        if self.skus is not None:
            out = self._keep(out, sku_column or SKU_COLUMN, self.skus)
        return out

    def keep(self, values: Sequence[str]) -> list[str]:
        """The subset of `values` this workspace covers, order preserved."""
        if self.branches is None:
            return list(values)
        wanted = {b.upper() for b in self.branches}
        return [v for v in values if str(v).upper() in wanted]

    def note(self) -> str | None:
        """One sentence for the reader, or None when nothing was narrowed."""
        if not self.is_restricted:
            return None
        parts: list[str] = []
        if self.branches is not None:
            of_total = f" of {self.total_branches}" if self.total_branches else ""
            parts.append(
                f"{len(self.branches)}{of_total} branches ({', '.join(self.branches)})"
            )
        if self.skus is not None:
            of_total = f" of {self.total_skus}" if self.total_skus else ""
            parts.append(f"{len(self.skus)}{of_total} SKUs")
        return (
            f"This workspace covers {' and '.join(parts)}. Every figure on this page "
            "describes that slice only, not the national network. "
            f"Source: {self.detail}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "restricted": self.is_restricted,
            "branches": list(self.branches) if self.branches else None,
            "branch_count": len(self.branches) if self.branches else None,
            "total_branches": self.total_branches,
            "skus": list(self.skus) if self.skus else None,
            "sku_count": len(self.skus) if self.skus else None,
            "total_skus": self.total_skus,
            "source": self.source,
            "detail": self.detail,
            "note": self.note(),
        }

    def with_total(
        self, total_branches: int | None, total_skus: int | None = None
    ) -> "WorkspaceScope":
        if total_branches == self.total_branches and (
            total_skus is None or total_skus == self.total_skus
        ):
            return self
        return WorkspaceScope(
            branches=self.branches,
            source=self.source,
            detail=self.detail,
            total_branches=total_branches,
            skus=self.skus,
            total_skus=self.total_skus if total_skus is None else total_skus,
        )


UNRESTRICTED = WorkspaceScope(
    branches=None,
    source=SOURCE_UNRESTRICTED,
    detail="no workspace restriction is configured and the active training run covered every branch",
)


def _clean(values: Any) -> tuple[str, ...] | None:
    if not values:
        return None
    cleaned = tuple(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))
    return cleaned or None


def _from_setting() -> WorkspaceScope | None:
    settings = get_settings()
    branches = _clean(settings.workspace_branches)
    skus = _clean(settings.workspace_skus)
    if branches is None and skus is None:
        return None
    named = [
        name
        for name, value in (
            ("AIS_WORKSPACE_BRANCHES", branches),
            ("AIS_WORKSPACE_SKUS", skus),
        )
        if value is not None
    ]
    return WorkspaceScope(
        branches=branches,
        skus=skus,
        source=SOURCE_SETTING,
        detail=" and ".join(named),
    )


def _from_training_run(db: Session) -> WorkspaceScope | None:
    """The branches the active training run was restricted to, if any.

    Imported lazily: `champion_service` imports the ML selection stack, and a
    module-level import here would pull it into every request that only wanted
    to know which branches to show.
    """
    from app.core.errors import NotFoundError
    from app.services import champion_service

    try:
        run = champion_service.resolve_run(db, None)
    except NotFoundError:
        return None
    restriction = dict(getattr(run, "restriction_json", None) or {})
    branches = _clean(
        restriction.get("branches_matched") or restriction.get("branches_requested")
    )
    skus = _clean(restriction.get("skus_kept"))
    if branches is None and skus is None:
        return None
    return WorkspaceScope(
        branches=branches,
        skus=skus,
        source=SOURCE_TRAINING_RUN,
        detail=f"training run {run.id[:8]}, which was restricted to this slice",
    )


def resolve_workspace(db: Session) -> WorkspaceScope:
    """The one answer, in precedence order. Cheap enough to call per request."""
    return _from_setting() or _from_training_run(db) or UNRESTRICTED
