import pytest

from app.normalize import (normalize_bool, normalize_count, normalize_date, normalize_radius,
                           normalize_state, text_key)


@pytest.mark.parametrize("raw,expected", [
    ("2026-11-01", "2026-11-01"), ("2026-1-5", "2026-01-05"), ("11/01/2026", "2026-11-01"),
    ("November 1, 2026", "2026-11-01"), ("Nov 1st 2026", "2026-11-01"), ("2024-02-29", "2024-02-29"),
])
def test_dates_valid(raw, expected):
    r = normalize_date(raw)
    assert r.valid and r.value == expected


@pytest.mark.parametrize("raw", ["2026-02-30", "2025-02-29", "13/01/2026", "November 2026", "soon", "2026", ""])
def test_dates_invalid(raw):
    assert not normalize_date(raw).valid


@pytest.mark.parametrize("raw,code", [("CA", "CA"), ("ca", "CA"), ("California", "CA"), (" california ", "CA"),
                                      ("New York", "NY"), ("TX.", "TX")])
def test_states(raw, code):
    assert normalize_state(raw).value == code


@pytest.mark.parametrize("raw", ["Calif", "XX", "Ontario", ""])
def test_states_invalid(raw):
    assert not normalize_state(raw).valid


@pytest.mark.parametrize("raw,n", [("3", 3), ("3 vehicles", 3), ("3.0", 3), ("0", 0), ("1,200", 1200)])
def test_counts(raw, n):
    r = normalize_count(raw)
    assert r.valid and r.value == n and isinstance(r.value, int)


@pytest.mark.parametrize("raw", ["3.5", "-1", "three-ish", "", "3-4"])
def test_counts_invalid(raw):
    assert not normalize_count(raw).valid


@pytest.mark.parametrize("raw,v", [("150", 150), ("150.0", 150), ("150.1", 150.1), ("150 miles", 150),
                                   ("within 75 mi", 75)])
def test_radius(raw, v):
    r = normalize_radius(raw)
    assert r.valid and r.value == v


@pytest.mark.parametrize("raw", ["-10", "local", "100-200", ""])
def test_radius_invalid(raw):
    assert not normalize_radius(raw).valid


@pytest.mark.parametrize("raw,b", [("Yes", True), ("y", True), ("TRUE", True), ("No", False), ("n", False),
                                   ("false", False), ("No.", False)])
def test_bool(raw, b):
    assert normalize_bool(raw).value is b


@pytest.mark.parametrize("raw", ["Not provided", "maybe", "N/A", "", "Yes and no"])
def test_bool_ambiguous(raw):
    assert not normalize_bool(raw).valid


def test_text_key_ignores_case_space_trailing_period():
    assert text_key("Local delivery of  packaged goods.") == text_key("local delivery of packaged goods")


@pytest.mark.parametrize("raw,expected", [
    ("No hazardous materials are transported", False),
    ("Yes - paint and solvents", True),
    ("No.", False),
])
def test_bool_leading_explicit_answer(raw, expected):
    n = normalize_bool(raw)
    assert n.valid and n.value is expected


@pytest.mark.parametrize("raw", ["Yes, occasionally", "No, except fuel", "Not provided", "None", "N/A", "Nope maybe"])
def test_bool_hedged_or_unclear_stays_invalid(raw):
    assert not normalize_bool(raw).valid
