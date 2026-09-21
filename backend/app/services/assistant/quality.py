"""Reject model output that is not usable prose.

This exists because of a measured failure, not a hypothetical one. The first
live drift explanation, written at temperature 2.0, came back as:

    "Drift shows how demand has changed compared to pastly observed sales and
     means average facts consumyac extrem acDemand unde ganho.solatu
     fortAshutadaastracted goverrtqeicaier Porուլի demandbuyakers फ
     whatsappialog القوة.Id.Offset july viac našem Committeebiased spot'm
     juvenileAdvice d"

Four scripts, no meaning, and it would have rendered on the page beneath a
chart as though it explained something. A deterministic fallback already
existed for a provider *failure*; there was nothing for a provider that
answers confidently with nonsense.

The checks are deliberately blunt. They are not trying to judge whether an
explanation is good - that is not something a heuristic can do. They are
trying to catch output that is obviously not English prose about these
numbers, and to prefer a plain template over it. A false negative just means
a slightly worse sentence ships; a false positive means a correct sentence is
replaced by a correct template. Both are acceptable; printing the text above
is not.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Above this share of non-Latin characters the text is not English prose.
#: Indian-numbering output legitimately contains ₹ and ×, so the bar is not
#: zero - but a tenth of the characters is already far past punctuation.
MAX_NON_LATIN_SHARE = 0.08

#: A usable explanation is at least this long. Anything shorter is a refusal
#: or a fragment, and the template says more.
MIN_CHARS = 80

#: The floor for a chat answer, which is a different thing from an explanation.
#: An explanation sits under a chart and has a paragraph of work to do; an
#: answer to "what is next month" can legitimately be one sentence. Holding
#: chat to the 80-character explanation floor rejected "Ordered demand is
#: rising. Latest - 200,686 units." at 55 characters, which is a good answer.
#: The script and token-soup checks are what catch nonsense; length does not.
MIN_ANSWER_CHARS = 20

#: Below this share of recognisable words the text is token soup.
MIN_WORDLIKE_SHARE = 0.75

#: A single word longer than this is a concatenation artefact
#: ("fortAshutadaastracted"), not a word.
MAX_WORD_LENGTH = 28

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")

#: Punctuation stripped before a token is tested for word-likeness.
#:
#: The assistant answers in markdown - bold figures, bullet lists - and the
#: guard was written for the plain prose of a drift explanation. "**Latest**"
#: is a word wearing asterisks, and a bullet "-" is not a word at all. Counting
#: both against the text rejected "Ordered demand is rising. - **Latest** -
#: 200,686 units." as token soup, which is a correct answer in the house style.
_TRIM = ".,;:()[]{}%—–-*_`#>\"'"

#: A token made only of punctuation carries no evidence either way, so it is
#: left out of the denominator rather than counted as a non-word.
_PUNCT_ONLY = re.compile(r"^[^\w]+$")


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str | None = None


def _non_latin_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    foreign = sum(1 for c in letters if "LATIN" not in unicodedata.name(c, ""))
    return foreign / len(letters)


def check_explanation(
    text: str,
    *,
    must_mention: tuple[str, ...] = (),
    min_chars: int = MIN_CHARS,
) -> Verdict:
    """Whether `text` is usable prose about the facts it was given.

    `must_mention` is an optional set of tokens - a figure, a scope name -
    that a grounded explanation would be expected to contain. A miss is only
    reported when *none* of them appear, because an explanation may reasonably
    mention some and not others.
    """
    stripped = (text or "").strip()
    if len(stripped) < min_chars:
        return Verdict(False, f"too short ({len(stripped)} characters)")

    share = _non_latin_share(stripped)
    if share > MAX_NON_LATIN_SHARE:
        return Verdict(False, f"{share:.0%} of letters are not Latin script")

    tokens = stripped.split()
    if not tokens:
        return Verdict(False, "no words")

    judged = [t for t in tokens if not _PUNCT_ONLY.match(t)]
    if not judged:
        return Verdict(False, "no words")

    wordlike = sum(1 for t in judged if _WORD.fullmatch(t.strip(_TRIM)))
    if wordlike / len(judged) < MIN_WORDLIKE_SHARE:
        # Figures and units are not word-like, so a heavily numeric sentence
        # can dip here legitimately; the bar is set low enough to allow it.
        numeric = sum(1 for t in judged if any(c.isdigit() for c in t))
        if (wordlike + numeric) / len(judged) < MIN_WORDLIKE_SHARE:
            return Verdict(
                False,
                f"only {wordlike}/{len(judged)} tokens are words",
            )

    longest = max((len(t.strip(_TRIM)) for t in tokens), default=0)
    if longest > MAX_WORD_LENGTH:
        return Verdict(False, f"contains a {longest}-character token")

    if must_mention:
        lowered = stripped.lower()
        if not any(str(m).lower() in lowered for m in must_mention if str(m).strip()):
            return Verdict(
                False,
                "mentions none of the figures it was given, so it is not grounded",
            )

    return Verdict(True)
