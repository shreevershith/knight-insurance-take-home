"""Builders for test FieldResults, going through the real normalizer + reconciler."""
from __future__ import annotations

from app.models import Evidence, FieldResult, Mention
from app.normalize import normalize
from app.reconcile import reconcile_field

SOURCES = ["broker_email.txt", "application.pdf"]


def mention(field: str, raw: str | None, source: str = "broker_email.txt", not_provided: bool = False) -> Mention:
    ev = Evidence(source_file=source, locator="email body, line 1", excerpt_or_observation=f"{field}: {raw}")
    if not_provided:
        return Mention(field=field, source_file=source, explicitly_not_provided=True, evidence=ev)
    n = normalize(field, raw)
    return Mention(field=field, source_file=source, raw_value=raw, valid=n.valid, normalized=n.value,
                   display=n.display, error=n.error, evidence=ev)


def field_from(field: str, *raws, failed: list[str] | None = None) -> FieldResult:
    """field_from('x', '150') -> KNOWN; ('180','80') -> CONFLICT; () -> MISSING."""
    ms = [mention(field, r, SOURCES[i % 2]) for i, r in enumerate(raws)]
    return reconcile_field(field, ms, SOURCES, failed)


def base_fields(**over) -> dict[str, FieldResult]:
    """A fully passing packet; override individual fields with kwargs."""
    f = {
        "business_name": field_from("business_name", "Acme LLC"),
        "requested_effective_date": field_from("requested_effective_date", "2026-11-01"),
        "garaging_state": field_from("garaging_state", "CA"),
        "operations_description": field_from("operations_description", "Local delivery"),
        "declared_vehicle_count": field_from("declared_vehicle_count", "3"),
        "operating_radius_miles": field_from("operating_radius_miles", "150"),
        "hazardous_materials": field_from("hazardous_materials", "No"),
        "schedule_vehicle_count": field_from("schedule_vehicle_count", "3"),
        "loss_runs_present": field_from("loss_runs_present", "true"),
    }
    f.update(over)
    return f
