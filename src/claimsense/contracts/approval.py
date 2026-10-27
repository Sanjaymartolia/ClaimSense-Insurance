"""Approval tied to the exact worksheet payload."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from .worksheet import Worksheet


class ApprovalLevel(StrEnum):
    ADJUDICATOR = "adjudicator"
    SENIOR = "senior"  # required above the threshold or when a fraud flag is set


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class ApprovalToken(BaseModel):
    claim_id: str
    worksheet_hash: str
    level: ApprovalLevel
    approver_id: str
    decided_at: datetime

    def is_valid_for(self, worksheet: Worksheet) -> bool:
        """False as soon as anything in the worksheet changes."""
        return (
            self.claim_id == worksheet.claim_id and self.worksheet_hash == worksheet.content_hash()
        )
