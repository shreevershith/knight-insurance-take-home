"""R1-R5 and overall status. Pure functions: no I/O, no LLM.

Authoritative definitions: candidate_materials/rules.json. Rules read each
field's *effective* value/state (human override if present, else extracted).
"""
from __future__ import annotations

from typing import Mapping

from .models import (FIELD_LABELS, FieldResult, FieldState, OverallStatus, RuleInput,
                     RuleResult, RuleStatus)

RADIUS_THRESHOLD_MILES = 150

RULE_NAMES = {
    "R1": "Required identity and effective date",
    "R2": "Vehicle count reconciliation",
    "R3": "Operating radius",
    "R4": "Hazardous materials",
    "R5": "Loss runs attachment",
}

_STATE_WORDS = {
    FieldState.MISSING: "missing",
    FieldState.INVALID: "invalid",
    FieldState.CONFLICT: "conflicting between sources",
    FieldState.NOT_EXTRACTED: "not extracted (model extraction failed)",
}


def _input(f: FieldResult) -> RuleInput:
    return RuleInput(field=f.name, value=f.effective_value, state=f.effective_state,
                     override=f.override is not None,
                     cross_checked=f.override is not None or f.cross_checked)


def _desc(f: FieldResult) -> str:
    label = FIELD_LABELS.get(f.name, f.name)
    st = f.effective_state
    if st == FieldState.KNOWN and not f.resolved:
        return (f"{label} = {f.effective_value!r} was not cross-checked (model extraction failed for "
                + ", ".join(f.unchecked_sources) + ")")
    if st == FieldState.KNOWN:
        return f"{label} = {f.effective_value!r}"
    if st == FieldState.CONFLICT:
        vals = " vs ".join(a.display for a in f.alternatives)
        return f"{label} is conflicting between sources ({vals})"
    return f"{label} is {_STATE_WORDS.get(st, st.value)}"


def _result(rule_id: str, status: RuleStatus, reason: str, fields: list[FieldResult]) -> RuleResult:
    return RuleResult(id=rule_id, name=RULE_NAMES[rule_id], status=status, reason=reason,
                      inputs_used=[_input(f) for f in fields])


def rule_r1(name: FieldResult, date: FieldResult) -> RuleResult:
    fields = [name, date]
    missing = [f for f in fields if f.effective_state == FieldState.MISSING]
    if missing:  # FLAG for absence takes precedence over UNKNOWN
        return _result("R1", RuleStatus.FLAG, "; ".join(_desc(f) for f in missing) + ".", fields)
    unresolved = [f for f in fields if not f.resolved]
    if unresolved:
        return _result("R1", RuleStatus.UNKNOWN, "; ".join(_desc(f) for f in unresolved) + ".", fields)
    return _result("R1", RuleStatus.PASS, "Business name and effective date are present and valid.", fields)


def rule_r2(declared: FieldResult, schedule: FieldResult) -> RuleResult:
    fields = [declared, schedule]
    unresolved = [f for f in fields if not f.resolved]
    if unresolved:
        extra = ""
        if schedule in unresolved and schedule.notes:
            extra = f" ({schedule.notes[0]})"
        return _result("R2", RuleStatus.UNKNOWN,
                       "; ".join(_desc(f) for f in unresolved) + extra + ".", fields)
    d, s = int(declared.effective_value), int(schedule.effective_value)
    if d == s:
        return _result("R2", RuleStatus.PASS, f"Declared count {d} equals schedule count {s}.", fields)
    return _result("R2", RuleStatus.FLAG,
                   f"Declared count {d} differs from schedule count {s} (CSV data rows).", fields)


def rule_r3(radius: FieldResult) -> RuleResult:
    # Unresolved values are UNKNOWN before any threshold test.
    if not radius.resolved:
        return _result("R3", RuleStatus.UNKNOWN, _desc(radius) + ".", [radius])
    r = float(radius.effective_value)
    if r > RADIUS_THRESHOLD_MILES:
        return _result("R3", RuleStatus.FLAG,
                       f"Radius {radius.effective_value} miles is greater than {RADIUS_THRESHOLD_MILES}.", [radius])
    return _result("R3", RuleStatus.PASS,
                   f"Radius {radius.effective_value} miles is at or below {RADIUS_THRESHOLD_MILES}.", [radius])


def rule_r4(hazmat: FieldResult) -> RuleResult:
    if not hazmat.resolved:
        return _result("R4", RuleStatus.UNKNOWN, _desc(hazmat) + ".", [hazmat])
    if hazmat.effective_value is True:
        return _result("R4", RuleStatus.FLAG, "Hazardous materials answered Yes.", [hazmat])
    return _result("R4", RuleStatus.PASS, "Hazardous materials answered No.", [hazmat])


def rule_r5(loss_runs: FieldResult) -> RuleResult:
    st = loss_runs.effective_state
    if st == FieldState.KNOWN and loss_runs.effective_value is True:
        files = ", ".join(sorted({e.source_file for e in loss_runs.evidence})) if loss_runs.override is None else ""
        reason = "A readable loss runs / loss history report is attached" + (f" ({files})." if files else ".")
        return _result("R5", RuleStatus.PASS, reason, [loss_runs])
    if st == FieldState.KNOWN and loss_runs.effective_value is False:
        return _result("R5", RuleStatus.FLAG,
                       "No loss runs / loss history report is attached (an email promise does not count).",
                       [loss_runs])
    if st == FieldState.MISSING:  # e.g. human confirmed absent
        return _result("R5", RuleStatus.FLAG, "No loss runs / loss history report is attached.", [loss_runs])
    note = loss_runs.notes[0] if loss_runs.notes else "Loss runs presence could not be determined."
    return _result("R5", RuleStatus.UNKNOWN, note, [loss_runs])


def evaluate_rules(fields: Mapping[str, FieldResult]) -> list[RuleResult]:
    return [
        rule_r1(fields["business_name"], fields["requested_effective_date"]),
        rule_r2(fields["declared_vehicle_count"], fields["schedule_vehicle_count"]),
        rule_r3(fields["operating_radius_miles"]),
        rule_r4(fields["hazardous_materials"]),
        rule_r5(fields["loss_runs_present"]),
    ]


def overall_status(rules: list[RuleResult]) -> OverallStatus:
    if rules and all(r.status == RuleStatus.PASS for r in rules):
        return OverallStatus.READY_FOR_REVIEW
    return OverallStatus.NEEDS_REVIEW
