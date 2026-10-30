"""Extraction, coverage, fraud, critic, settlement agents (Agents & Orchestration, L11)"""

from .coverage import Admissibility, CoverageAgent
from .critic import CriticAgent, CriticReport
from .extraction import ExtractionAgent
from .fraud import FraudAgent
from .permissions import TOOL_ACL, ToolBelt, ToolPermissionError
from .services import PastClaim, PolicyInfo, Services, make_stub_services, reference_calculate
from .settlement import OutputGuardError, SettlementAgent


class Team:
    """The five specialists sharing one Services object (one per graph)."""

    def __init__(self, services: Services, playbook=None):
        self.services = services
        self.extraction = ExtractionAgent(services)
        self.coverage = CoverageAgent(services, playbook=playbook)
        self.fraud = FraudAgent(services)
        self.critic = CriticAgent(services)
        self.settlement = SettlementAgent(services)


__all__ = [
    "Admissibility", "CoverageAgent", "CriticAgent", "CriticReport", "ExtractionAgent",
    "FraudAgent", "OutputGuardError", "PastClaim", "PolicyInfo", "Services", "SettlementAgent",
    "TOOL_ACL", "Team", "ToolBelt", "ToolPermissionError", "make_stub_services",
    "reference_calculate",
]
