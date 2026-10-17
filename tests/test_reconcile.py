from app.models import FieldState
from app.reconcile import reconcile_field
from tests.helpers import SOURCES, field_from, mention


def test_conflict_keeps_both_alternatives_value_null():
    f = field_from("operating_radius_miles", "180", "80")
    assert f.state == FieldState.CONFLICT and f.value is None
    assert [a.value for a in f.alternatives] == [180, 80]
    assert {e.source_file for a in f.alternatives for e in a.evidence} == set(SOURCES)


def test_missing_mention_is_not_conflict():
    ms = [mention("garaging_state", "CA"), mention("garaging_state", None, "application.pdf", not_provided=True)]
    f = reconcile_field("garaging_state", ms, SOURCES)
    assert f.state == FieldState.KNOWN and f.value == "CA"
    assert any("not provided" in n for n in f.notes)


def test_missing_lists_sources_and_not_provided_excerpts():
    ms = [mention("hazardous_materials", None, s, not_provided=True) for s in SOURCES]
    f = reconcile_field("hazardous_materials", ms, SOURCES)
    assert f.state == FieldState.MISSING and f.value is None
    assert len(f.evidence) == 3
    assert all(s in f.evidence[-1].locator for s in SOURCES)  # "text sources read: ..."


def test_names_case_insensitive_known():
    f = field_from("business_name", "Pacific Harbor LLC", "PACIFIC  harbor llc")
    assert f.state == FieldState.KNOWN and f.value == "Pacific Harbor LLC"


def test_state_full_name_and_code_agree():
    assert field_from("garaging_state", "CA", "California").state == FieldState.KNOWN


def test_valid_plus_invalid_is_conflict():
    f = field_from("hazardous_materials", "No", "Maybe")
    assert f.state == FieldState.CONFLICT and f.value is None
    assert any(not a.valid for a in f.alternatives)


def test_only_invalid_is_invalid():
    assert field_from("requested_effective_date", "2026-02-30").state == FieldState.INVALID


def test_intra_source_disagreement_is_conflict():
    ms = [mention("declared_vehicle_count", "3"), mention("declared_vehicle_count", "4")]
    assert reconcile_field("declared_vehicle_count", ms, SOURCES).state == FieldState.CONFLICT


def test_failed_source_not_extracted_vs_missing():
    assert field_from("operating_radius_miles", failed=["application.pdf"]).state == FieldState.NOT_EXTRACTED
    f = field_from("operating_radius_miles", "100", failed=["application.pdf"])
    assert f.state == FieldState.KNOWN and any("not cross-checked" in n for n in f.notes)
