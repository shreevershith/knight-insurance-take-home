import pytest

from app.models import FieldState, OverallStatus, RuleStatus
from app.reconcile import apply_override
from app.rules import evaluate_rules, overall_status, rule_r1, rule_r2, rule_r3, rule_r4, rule_r5
from app.schedule import derive_schedule_count
from tests.helpers import base_fields, field_from

P, F, U = RuleStatus.PASS, RuleStatus.FLAG, RuleStatus.UNKNOWN


def test_all_pass_is_ready():
    rules = evaluate_rules(base_fields())
    assert [r.status for r in rules] == [P] * 5
    assert overall_status(rules) == OverallStatus.READY_FOR_REVIEW


def test_any_non_pass_needs_review():
    rules = evaluate_rules(base_fields(hazardous_materials=field_from("hazardous_materials", "Yes")))
    assert overall_status(rules) == OverallStatus.NEEDS_REVIEW


# ---------------- R1
def test_r1_missing_date_flags():
    r = rule_r1(field_from("business_name", "Acme"), field_from("requested_effective_date"))
    assert r.status == F and "missing" in r.reason


def test_r1_missing_plus_conflict_flags_precedence():
    r = rule_r1(field_from("business_name", "Acme", "Zenith"), field_from("requested_effective_date"))
    assert r.status == F


def test_r1_conflict_only_unknown():
    r = rule_r1(field_from("business_name", "Acme"),
                field_from("requested_effective_date", "2026-11-01", "2026-12-01"))
    assert r.status == U


def test_r1_invalid_date_unknown():
    r = rule_r1(field_from("business_name", "Acme"), field_from("requested_effective_date", "2026-02-30"))
    assert r.status == U and "invalid" in r.reason


def test_r1_case_insensitive_names_pass():
    r = rule_r1(field_from("business_name", "Acme LLC", "ACME llc"),
                field_from("requested_effective_date", "2026-11-01", "11/01/2026"))
    assert r.status == P


def test_r1_not_extracted_is_unknown():
    r = rule_r1(field_from("business_name", failed=["application.pdf"]),
                field_from("requested_effective_date", "2026-11-01"))
    assert r.status == U and "model extraction failed" in r.reason


# ---------------- R2
@pytest.mark.parametrize("declared,sched,expected", [("3", "3", P), ("4", "3", F), ("0", "0", P), ("2", "2.0", P)])
def test_r2_counts(declared, sched, expected):
    assert rule_r2(field_from("declared_vehicle_count", declared),
                   field_from("schedule_vehicle_count", sched)).status == expected


def test_r2_missing_declared_unknown():
    assert rule_r2(field_from("declared_vehicle_count"), field_from("schedule_vehicle_count", "3")).status == U


def test_r2_bad_csv_unknown():
    sched = derive_schedule_count([("v.csv", "id,vin\nA,1\n")])
    assert sched.state == FieldState.INVALID
    r = rule_r2(field_from("declared_vehicle_count", "1"), sched)
    assert r.status == U and "header" in r.reason


def test_r2_conflicting_declared_unknown():
    assert rule_r2(field_from("declared_vehicle_count", "4", "3"),
                   field_from("schedule_vehicle_count", "3")).status == U


# ---------------- R3
@pytest.mark.parametrize("raw,expected", [
    ("150", P), ("150.0", P), ("150 miles", P), ("0", P), ("150.1", F), ("180", F),
    ("-5", U), ("about a hundred", U), ("50-100", U),
])
def test_r3_threshold_and_invalid(raw, expected):
    assert rule_r3(field_from("operating_radius_miles", raw)).status == expected


def test_r3_conflict_unknown_before_threshold():
    r = rule_r3(field_from("operating_radius_miles", "180", "80"))
    assert r.status == U and "180" in r.reason and "80" in r.reason


def test_r3_missing_unknown():
    assert rule_r3(field_from("operating_radius_miles")).status == U


def test_r3_150_and_150_0_are_not_a_conflict():
    f = field_from("operating_radius_miles", "150", "150.0")
    assert f.state == FieldState.KNOWN and rule_r3(f).status == P


# ---------------- R4
@pytest.mark.parametrize("raws,expected", [
    (("Yes",), F), (("No",), P), (("true",), F), (("n",), P), ((), U),
    (("Sometimes",), U), (("Yes", "No"), U),
])
def test_r4(raws, expected):
    assert rule_r4(field_from("hazardous_materials", *raws)).status == expected


# ---------------- R5 (field-level; packet-level derivation tested in test_ingest)
def test_r5_states():
    assert rule_r5(field_from("loss_runs_present", "true")).status == P
    assert rule_r5(field_from("loss_runs_present", "false")).status == F


# ---------------- overrides
def test_override_changes_rule_and_keeps_original():
    radius = field_from("operating_radius_miles", "180", "80")
    assert rule_r3(radius).status == U
    fixed = apply_override(radius, "80")
    r = rule_r3(fixed)
    assert r.status == P and r.inputs_used[0].override is True
    # original extracted state/alternatives/evidence retained
    assert fixed.state == FieldState.CONFLICT and fixed.value is None
    assert len(fixed.alternatives) == 2 and len(fixed.evidence) == 2


def test_override_confirm_absent_is_missing():
    f = apply_override(field_from("requested_effective_date", "2026-11-01"), None, confirm_absent=True)
    assert f.effective_state == FieldState.MISSING
    assert rule_r1(field_from("business_name", "Acme"), f).status == F


def test_override_rejects_invalid_value():
    from app.reconcile import OverrideError
    with pytest.raises(OverrideError):
        apply_override(field_from("operating_radius_miles"), "-3")
    with pytest.raises(OverrideError):
        apply_override(field_from("requested_effective_date"), "2026-02-30")
