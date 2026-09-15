"""Advisory semantic-role suggestion.

**Suggestions are never authoritative.** Every one is returned with a
confidence and a rationale, marked `is_suggested`, and must survive human
review before a mapping can be confirmed.

Detection is schema-agnostic. It uses structural signals from the column
profile - does it parse as a date, how many distinct values relative to the row
count, is it numeric, is it constant - plus *generic* lexical cues only
("date", "qty", "price", "stock"). It never special-cases a specific dataset's
column name, so the same suggester works on a dataset with entirely unrelated
headers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ml.features.roles import SemanticRole

# Generic lexical cues. Deliberately common tokens, not dataset field names.
_TIME_TOKENS = ("date", "time", "month", "period", "year", "week", "day", "dt")
_TARGET_TOKENS = ("qty", "quantity", "demand", "order", "volume", "units", "sales")
_PRICE_TOKENS = ("price", "mrp", "rate", "cost", "value", "amount")
# Includes the abbreviations ERP exports commonly use for a closing balance
# ("clo", "cls", "bal", "oh"). Without them a column like "CLO QTY" matches the
# demand cue `qty` first and gets suggested as the forecast TARGET - a stock
# quantity standing in for demand is the single worst mislabel available here.
_INVENTORY_TOKENS = (
    "stock", "inventory", "onhand", "on_hand", "closing", "balance",
    "clo", "cls", "bal", "oh", "wip", "soh",
)
_SUPPLY_TOKENS = (
    "despatch", "dispatch", "receipt", "shipped", "delivered", "supply", "grn",
    "issued", "fulfilled",
)
_CAPACITY_TOKENS = ("capacity", "lead", "moq", "truck", "review")
_ID_TOKENS = ("code", "id", "no", "number", "sku", "branch", "depot", "location", "item")
_IGNORE_TOKENS = ("uom", "series", "record", "flag", "reason", "type")


@dataclass
class ColumnSignals:
    """The structural facts a suggestion is derived from.

    Mirrors what the Phase 2 profiler already computes, so suggestion needs no
    second pass over the source files.
    """

    source_role: str
    column_name: str
    ordinal: int
    detected_type: str
    row_count: int
    non_null_count: int
    distinct_count: int | None
    is_constant: bool
    is_pii: bool
    parses_as_date: bool = False
    sample_values: tuple[str, ...] = ()

    @property
    def null_share(self) -> float:
        if not self.row_count:
            return 0.0
        return 1.0 - (self.non_null_count / self.row_count)

    @property
    def cardinality_ratio(self) -> float | None:
        """Distinct values as a share of rows. Low means dimension-like, near
        1.0 means identifier-like."""
        if self.distinct_count is None or not self.row_count:
            return None
        return self.distinct_count / self.row_count


@dataclass
class Suggestion:
    source_role: str
    column_name: str
    role: SemanticRole
    confidence: float
    rationale: str


def _tokens(column_name: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", column_name.lower())) - {""}


def _matches(column_name: str, cues: tuple[str, ...]) -> bool:
    lowered = column_name.lower()
    tokens = _tokens(column_name)
    return any(cue in tokens or cue in lowered for cue in cues)


def suggest_role(signals: ColumnSignals) -> Suggestion:
    """Suggest one column's role. Always returns something, so no column is
    silently left unclassified."""
    name = signals.column_name

    # PII is not a judgement call - it is declared, and it outranks everything.
    if signals.is_pii:
        return Suggestion(
            signals.source_role, name, SemanticRole.EXCLUDED_PII, 1.0,
            "Declared a PII column, so it can only be excluded from modelling.",
        )

    # A column that actually parses as a date is the strongest structural signal
    # available; the lexical cue only reinforces it.
    if signals.parses_as_date:
        confidence = 0.95 if _matches(name, _TIME_TOKENS) else 0.8
        return Suggestion(
            signals.source_role, name, SemanticRole.TIME_COLUMN, confidence,
            "Values parse as dates"
            + (" and the name carries a time cue." if confidence > 0.9 else "."),
        )

    if signals.is_constant:
        return Suggestion(
            signals.source_role, name, SemanticRole.IGNORED, 0.9,
            "Constant across every row, so it carries no information.",
        )

    if signals.non_null_count == 0:
        return Suggestion(
            signals.source_role, name, SemanticRole.IGNORED, 0.95,
            "Entirely empty.",
        )

    ratio = signals.cardinality_ratio
    is_numeric = signals.detected_type == "numeric"

    if is_numeric:
        # Order matters: supply and inventory cues are checked before the
        # generic target cue, because "despatch qty" carries both and the more
        # specific reading is the right one.
        if _matches(name, _SUPPLY_TOKENS):
            return Suggestion(
                signals.source_role, name, SemanticRole.SUPPLY, 0.75,
                "Numeric with a supply/fulfilment cue in the name; known only "
                "up to now, so it is a historical signal.",
            )
        if _matches(name, _INVENTORY_TOKENS):
            return Suggestion(
                signals.source_role, name, SemanticRole.INVENTORY, 0.75,
                "Numeric with an inventory cue in the name.",
            )
        if _matches(name, _CAPACITY_TOKENS):
            return Suggestion(
                signals.source_role, name, SemanticRole.CAPACITY, 0.7,
                "Numeric with a capacity or lead-time cue in the name.",
            )
        if _matches(name, _PRICE_TOKENS):
            return Suggestion(
                signals.source_role, name, SemanticRole.HISTORICAL_DRIVER, 0.7,
                "Numeric price-like column. Suggested as a HISTORICAL driver, "
                "not future-known: a price can change, so its future value is "
                "not knowable in advance.",
            )
        if _matches(name, _TARGET_TOKENS):
            return Suggestion(
                signals.source_role, name, SemanticRole.TARGET_COLUMN, 0.65,
                "Numeric with a demand cue in the name. Review this - several "
                "columns can look like the target, and only one is.",
            )
        return Suggestion(
            signals.source_role, name, SemanticRole.HISTORICAL_DRIVER, 0.4,
            "Numeric with no recognised cue; a historical driver is the safe "
            "default because it cannot leak future information.",
        )

    # Non-numeric. Low cardinality relative to rows means dimension-like.
    if ratio is not None and ratio < 0.001 and _matches(name, _ID_TOKENS):
        return Suggestion(
            signals.source_role, name, SemanticRole.SERIES_IDENTIFIER, 0.7,
            f"Text with only {signals.distinct_count} distinct values across "
            f"{signals.row_count:,} rows and an identifier cue in the name.",
        )
    if ratio is not None and ratio < 0.01:
        return Suggestion(
            signals.source_role, name, SemanticRole.STATIC_ATTRIBUTE, 0.6,
            f"Text repeating across many rows ({signals.distinct_count} distinct), "
            "which is characteristic of a grouping attribute.",
        )
    if _matches(name, _IGNORE_TOKENS):
        return Suggestion(
            signals.source_role, name, SemanticRole.IGNORED, 0.5,
            "Text with a bookkeeping cue in the name and no modelling use.",
        )
    return Suggestion(
        signals.source_role, name, SemanticRole.IGNORED, 0.3,
        "High-cardinality free text with no recognised role. Ignored by default "
        "rather than guessed into a feature.",
    )


def suggest_all(signals: list[ColumnSignals]) -> list[Suggestion]:
    """Suggest for every column, then resolve singleton contention.

    When several columns are suggested as the target - which happens on this
    dataset, where ordered and despatched quantity both look like demand - the
    highest-confidence one keeps the role and the rest fall back to historical
    drivers with the contention stated in their rationale. A person still has
    to confirm the choice.
    """
    suggestions = [suggest_role(signal) for signal in signals]

    for role in (SemanticRole.TARGET_COLUMN, SemanticRole.TIME_COLUMN):
        contenders = [s for s in suggestions if s.role is role]
        if len(contenders) <= 1:
            continue
        winner = max(contenders, key=lambda s: (s.confidence, -len(s.column_name)))
        fallback = (
            SemanticRole.HISTORICAL_DRIVER
            if role is SemanticRole.TARGET_COLUMN
            else SemanticRole.IGNORED
        )
        for suggestion in contenders:
            if suggestion is winner:
                suggestion.rationale += (
                    f" Chosen over {len(contenders) - 1} other candidate(s) for this "
                    "role; confirm it is the right one."
                )
                continue
            suggestion.role = fallback
            suggestion.confidence = min(suggestion.confidence, 0.35)
            suggestion.rationale = (
                f"Also looked like {role.value!r}, but {winner.column_name!r} scored "
                f"higher. Demoted to {fallback.value!r} - reassign if this is actually "
                "the target."
            )
    return suggestions
