"""The coverage analyst keeps the model's rationale and what it was shown (for the eval judge).

Before 12 Nov 2026 `_ask_model` dropped the rationale, so the RAGAS faithfulness judge scored a
placeholder sentence the eval adapter wrote, not anything the model said.
"""

from claimsense.agents import Team
from claimsense.agents.coverage import CANDIDATE_CHARS, CoverageDecision, LineChoice

from .conftest import C, room_breach_packet


class FakeModel:
    """Answers the clause-selection call with fixed choices."""

    def __init__(self, choices):
        self.choices = choices

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _messages):
        return CoverageDecision(choices=self.choices)


def test_the_model_rationale_is_kept_only_for_choices_that_stand(services):
    team = Team(services)
    claim = team.extraction.run(room_breach_packet())[0]
    team.coverage.llm = FakeModel(
        [
            LineChoice(line_id="L1", clause_id=C.ROOM_RENT_LIMIT, rationale="Room capped per day."),
            LineChoice(line_id="L2", clause_id="made:up", rationale="Invalid pick."),
            LineChoice(line_id="L3", clause_id=C.HOSPITALISATION, rationale="OT is covered."),
            LineChoice(line_id="L5", clause_id=C.NON_PAYABLE_ITEMS, rationale="Gloves excluded."),
        ]
    )
    choices, _, notes = team.coverage.choose_clauses(claim, locked={"L5": C.HOSPITALISATION})

    assert team.coverage.rationales == {"L1": "Room capped per day.", "L3": "OT is covered."}
    assert team.coverage.rationale_clauses == {"L1": C.ROOM_RENT_LIMIT, "L3": C.HOSPITALISATION}
    assert any(n.startswith("L2:") for n in notes), "the invalid pick fell back"
    assert choices["L5"] == C.HOSPITALISATION, "the human lock wins, so no model reason for L5"


def test_what_the_model_was_shown_is_recorded_per_line(services):
    team = Team(services)
    claim = team.extraction.run(room_breach_packet())[0]
    team.coverage.choose_clauses(claim)  # stub mode: no model, so no rationale
    assert team.coverage.rationales == {}
    assert set(team.coverage.shown) == {line.line_id for line in claim.bill_lines}
    assert all(
        texts and all(len(t) <= CANDIDATE_CHARS for t in texts)
        for texts in team.coverage.shown.values()
    )
