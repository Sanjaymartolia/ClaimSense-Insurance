"""What gets passed from step to step (LangGraph state).

Each step returns only the fields it changes, and LangGraph merges them in. A field
marked `operator.add` GROWS (new items are appended); every other field is
OVERWRITTEN. Choosing wrong quietly loses information on every loop (TODO 6b).
"""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage


class ClaimState(TypedDict, total=False):
    # inputs
    claim_id: str
    question: str  # the adjudicator's instruction or follow-up question

    # working memory
    messages: Annotated[list[AnyMessage], operator.add]
    hits: list  # retrieved passages, as dicts
    steps: Annotated[list[str], operator.add]  # node names in the order visited
    actions: Annotated[list[dict], operator.add]  # every tool call: {tool, args, status}

    # outputs (these become the trace)
    worksheet: dict | None  # ONLY ever written by the compute_worksheet tool
    answer: str
    route: str  # ready_for_approval | needs_review
    review_flags: list
    citations: list
    approval: dict | None  # an ApprovalToken, written by agent.resume() (TODO 6c)
