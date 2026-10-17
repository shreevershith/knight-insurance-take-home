"""Pydantic schemas shared across the pipeline.

Field names and semantics follow candidate_materials/field_specification.json.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, computed_field


class FieldState(str, Enum):
    KNOWN = "KNOWN"
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"
    INVALID = "INVALID"
    # Internal state: the model call for at least one source failed, so we did
    # not actually inspect it. Never reported as MISSING. Rules treat it as UNKNOWN.
    NOT_EXTRACTED = "NOT_EXTRACTED"


class RuleStatus(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    UNKNOWN = "UNKNOWN"


class OverallStatus(str, Enum):
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    NEEDS_REVIEW = "NEEDS_REVIEW"


DISCLAIMER = (
    "Readiness for human review only — not an approval, decline, quote or coverage decision."
)

# The 7 fields the LLM extracts from text sources.
EXTRACTED_FIELDS = [
    "business_name",
    "requested_effective_date",
    "garaging_state",
    "operations_description",
    "declared_vehicle_count",
    "operating_radius_miles",
    "hazardous_materials",
]
# Fields derived deterministically by code.
DERIVED_FIELDS = ["loss_runs_present", "schedule_vehicle_count"]
ALL_FIELDS = EXTRACTED_FIELDS + DERIVED_FIELDS

FIELD_LABELS = {
    "business_name": "Business name",
    "requested_effective_date": "Requested effective date",
    "garaging_state": "Garaging state",
    "operations_description": "Operations description",
    "declared_vehicle_count": "Declared vehicle count",
    "operating_radius_miles": "Operating radius (miles)",
    "hazardous_materials": "Hazardous materials",
    "loss_runs_present": "Loss runs present",
    "schedule_vehicle_count": "Schedule vehicle count",
}


class Evidence(BaseModel):
    source_file: str
    locator: str
    excerpt_or_observation: str


class Mention(BaseModel):
    """One verified, normalized statement about a field in one source."""

    field: str
    source_file: str
    raw_value: Optional[str] = None
    explicitly_not_provided: bool = False
    valid: bool = False
    normalized: Any = None
    display: Optional[str] = None
    error: Optional[str] = None
    evidence: Evidence


class Alternative(BaseModel):
    """A distinct candidate value for a CONFLICT field (kept, never chosen)."""

    value: Any = None
    display: str
    valid: bool = True
    error: Optional[str] = None
    evidence: list[Evidence] = Field(default_factory=list)


class Override(BaseModel):
    value: Any = None
    display: str
    confirmed_absent: bool = False
    note: Optional[str] = None


class FieldResult(BaseModel):
    name: str
    label: str = ""
    value: Any = None  # extracted / derived value (null unless KNOWN)
    display: Optional[str] = None
    state: FieldState
    evidence: list[Evidence] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    sources_checked: list[str] = Field(default_factory=list)
    # Sources whose model extraction failed, so this field was not checked there.
    unchecked_sources: list[str] = Field(default_factory=list)
    override: Optional[Override] = None

    @computed_field  # serialized so the UI and rerun requests see the effective view
    @property
    def cross_checked(self) -> bool:
        """False when a KNOWN value could not be compared against every source."""
        return not self.unchecked_sources

    @computed_field  # serialized so the UI and rerun requests see the effective view
    @property
    def resolved(self) -> bool:
        """What the rules treat as a usable value: KNOWN and cross-checked, or overridden.

        A KNOWN value from one source while another source failed extraction may
        hide a conflict, so rules treat it as UNKNOWN until a human confirms it.
        """
        if self.override is not None:
            return not self.override.confirmed_absent
        return self.state == FieldState.KNOWN and self.cross_checked

    @computed_field  # serialized so the UI and rerun requests see the effective view
    @property
    def effective_value(self) -> Any:
        if self.override is not None:
            return None if self.override.confirmed_absent else self.override.value
        return self.value

    @computed_field  # serialized so the UI and rerun requests see the effective view
    @property
    def effective_state(self) -> FieldState:
        if self.override is not None:
            return FieldState.MISSING if self.override.confirmed_absent else FieldState.KNOWN
        return self.state

    @computed_field
    @property
    def effective_display(self) -> Optional[str]:
        if self.override is not None:
            return self.override.display
        return self.display


class AttachmentInfo(BaseModel):
    filename: str
    detected_type: str  # email | application | loss_runs | vehicle_schedule | unclassified | unsupported
    readable: bool
    pages: Optional[int] = None
    rows: Optional[int] = None
    note: Optional[str] = None


class RuleInput(BaseModel):
    field: str
    value: Any = None
    state: FieldState
    override: bool = False
    cross_checked: bool = True


class RuleResult(BaseModel):
    id: str
    name: str
    status: RuleStatus
    reason: str
    inputs_used: list[RuleInput]


class Issue(BaseModel):
    """One deterministic item the summary and broker email must cover."""

    group: str  # Missing | Conflicting | Flagged | Unresolved
    field: Optional[str] = None
    label: str
    rule_ids: list[str] = Field(default_factory=list)
    text: str  # code-written factual description
    values: list[str] = Field(default_factory=list)  # values a narrative must quote (conflicts, flags)
    request: str = ""  # code-written request line, used by the template draft


class IssueGroup(BaseModel):
    group: str
    lines: list[str]


class Narrative(BaseModel):
    """Underwriter summary + draft broker email.

    status_line, overrides and disclaimer are always code-written. snapshot,
    issue lines and the email come from the model when source == "model", or
    from the deterministic template when source == "template".
    """

    source: str  # "model" | "template"
    status_line: str
    snapshot: str
    issue_groups: list[IssueGroup] = Field(default_factory=list)
    overrides: list[str] = Field(default_factory=list)
    disclaimer: str
    email_subject: str = ""
    email_body: str = ""
    error: Optional[str] = None  # why the model text is not shown (template only)
    validation_errors: list[str] = Field(default_factory=list)
    stale: bool = False
