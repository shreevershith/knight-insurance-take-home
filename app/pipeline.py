"""ingest -> extract (LLM) -> verify evidence -> reconcile -> rules -> narrate (LLM, validated).

Stateless: every call builds its result from the request inputs only.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .extraction import SourceExtraction, extract_source
from .ingest import Packet
from .llm import LLMClient
from .models import (DISCLAIMER, EXTRACTED_FIELDS, AttachmentInfo, FieldResult, Issue, Narrative,
                     OverallStatus, RuleResult, RuleStatus)
from .narrative import build_issues, generate_narrative
from .reconcile import reconcile_field
from .rules import evaluate_rules, overall_status


class ExtractionStatus(BaseModel):
    source_file: str
    kind: str
    status: str  # "ok" | "failed"
    error_kind: Optional[str] = None
    message: Optional[str] = None
    mentions_kept: int = 0
    mentions_discarded: int = 0


class ModelInfo(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None


class Evaluation(BaseModel):
    rules: list[RuleResult]
    overall_status: OverallStatus
    rule_counts: dict[str, int]
    issues: list[Issue]
    disclaimer: str = DISCLAIMER


class ProcessResult(Evaluation):
    model: ModelInfo
    inventory: list[AttachmentInfo]
    extraction: list[ExtractionStatus]
    fields: dict[str, FieldResult]
    warnings: list[str] = Field(default_factory=list)
    narrative: Narrative


def build_fields(packet: Packet, extractions: list[SourceExtraction]) -> dict[str, FieldResult]:
    ok = [e for e in extractions if e.ok]
    failed = [e.source_file for e in extractions if not e.ok]
    checked = [e.source_file for e in ok]
    fields: dict[str, FieldResult] = {}
    for name in EXTRACTED_FIELDS:
        mentions = [m for e in ok for m in e.mentions if m.field == name]
        fields[name] = reconcile_field(name, mentions, checked, failed)
    fields["schedule_vehicle_count"] = packet.schedule
    fields["loss_runs_present"] = packet.loss_runs
    return fields


def evaluate(fields: dict[str, FieldResult]) -> Evaluation:
    """Deterministic part only (used by Rerun checks): no LLM call."""
    rules = evaluate_rules(fields)
    return Evaluation(
        rules=rules, overall_status=overall_status(rules),
        rule_counts={s.value: sum(r.status == s for r in rules) for s in RuleStatus},
        issues=build_issues(fields, rules),
    )


def process_packet(packet: Packet, llm: Optional[LLMClient]) -> ProcessResult:
    if llm is not None:
        extractions = [extract_source(llm, s) for s in packet.sources]
    else:
        from .llm import LLMError
        err = LLMError("config", "no model configured")
        extractions = [SourceExtraction(s.source_file, s.kind, ok=False, error=err) for s in packet.sources]

    fields = build_fields(packet, extractions)
    ev = evaluate(fields)
    narrative = generate_narrative(llm, fields, ev.rules, ev.overall_status, ev.issues)

    warnings = list(packet.warnings)
    for e in extractions:
        warnings += e.warnings
    return ProcessResult(
        **ev.model_dump(),
        model=ModelInfo(provider=getattr(llm, "provider", None), model=getattr(llm, "model", None)),
        inventory=packet.inventory,
        extraction=[ExtractionStatus(
            source_file=e.source_file, kind=e.kind, status="ok" if e.ok else "failed",
            error_kind=e.error.kind if e.error else None, message=e.error.message if e.error else None,
            mentions_kept=len(e.mentions), mentions_discarded=e.discarded,
        ) for e in extractions],
        fields=fields, warnings=warnings, narrative=narrative,
    )
