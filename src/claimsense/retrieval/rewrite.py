"""Rewrite bill-line terms into policy wording before searching (T11, L6).

This is a fixed glossary, not a model. Bill text is untrusted, so it never reaches an LLM here, and
a rewrite holds only the glossary's own wording, so injected words can't add to the query.

Write entries only from the dev claim terms and the policy wording. The ``bill_line_other`` labels
must stay out of it, or evaluate.py can no longer show overfitting.
"""

import re

_ROOM = "room rent, boarding, nursing expenses"
_DIAGNOSTICS = "costs towards diagnostics, diagnostic imaging modalities"
_MEDICINES = "medicines and drugs"

GLOSSARY = {
    "diagnostics": _DIAGNOSTICS,
    "icu": "intensive care unit expenses",
    "laboratory": _DIAGNOSTICS,
    "medicines": _MEDICINES,
    "nursing": _ROOM,
    "ot": "operation theatre charges",
    "pharmacy": _MEDICINES,
    "rmo": "medical practitioner fees",
    "room charges": _ROOM,
    "ward": _ROOM,
}

_TERMS = re.compile(r"\b(" + "|".join(GLOSSARY) + r")\b", re.IGNORECASE)


def rewrite_query(text: str) -> str | None:
    """The policy wording for each glossary term in ``text``, or None if there are none."""
    wording = [GLOSSARY[match.group(1).lower()] for match in _TERMS.finditer(text)]
    return ", ".join(dict.fromkeys(wording)) or None
