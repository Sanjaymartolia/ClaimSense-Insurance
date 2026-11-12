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
_FEES = "surgeon, anaesthetist, medical practitioner, consultants, specialist fees"
_THEATRE = "operation theatre charges"

GLOSSARY = {
    "diagnostics": _DIAGNOSTICS,
    "icu": "intensive care unit expenses",
    "laboratory": _DIAGNOSTICS,
    "medicines": _MEDICINES,
    "nursing": _ROOM,
    "ot": _THEATRE,
    "pharmacy": _MEDICINES,
    "rmo": "medical practitioner fees",
    "room charges": _ROOM,
    "ward": _ROOM,
}

# A bill line's category (contracts.LineCategory value) -> the clause 4.1 wording that pays for it.
# A procedure name such as "Appendectomy" appears in no clause that pays for it, so the name alone
# finds only lists that mention it. "consumables" and "other" are left out on purpose: a category
# must not decide whether a line is payable.
CATEGORY_WORDING = {
    "doctor_fees": _FEES,
    "icu": GLOSSARY["icu"],
    "investigations": _DIAGNOSTICS,
    "medicines": _MEDICINES,
    "nursing": _ROOM,
    "ot": _THEATRE,
    "procedure": f"{_FEES}, {_THEATRE}",
    "room": _ROOM,
}

_TERMS = re.compile(r"\b(" + "|".join(GLOSSARY) + r")\b", re.IGNORECASE)


def rewrite_query(text: str, category: str | None = None) -> str | None:
    """The policy wording for each glossary term in ``text`` and for the line's ``category``.

    None if there is none. An unknown category adds nothing, so it can't inject words either.
    """
    wording = [GLOSSARY[match.group(1).lower()] for match in _TERMS.finditer(text)]
    if category in CATEGORY_WORDING:
        wording.append(CATEGORY_WORDING[category])
    return ", ".join(dict.fromkeys(wording)) or None
