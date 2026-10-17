"""Per-field normalization. Pure functions; no I/O.

Each normalizer takes the raw text the model (or a human) supplied and returns a
NormResult. Code - not the model - decides what a value means.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Optional

from dateutil import parser as dateparser


@dataclass
class NormResult:
    valid: bool
    value: Any = None
    display: Optional[str] = None
    error: Optional[str] = None

    @property
    def key(self) -> Any:
        """Comparison key used by reconciliation."""
        return comparison_key(self.value)


def _ok(value: Any, display: Optional[str] = None) -> NormResult:
    return NormResult(True, value, display if display is not None else str(value))


def _bad(error: str) -> NormResult:
    return NormResult(False, None, None, error)


def _clean(raw: Any) -> str:
    return re.sub(r"\s+", " ", str(raw if raw is not None else "")).strip()


def comparison_key(value: Any) -> Any:
    if isinstance(value, str):
        return text_key(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def text_key(s: str) -> str:
    """Case-insensitive, whitespace-collapsed, ignoring surrounding punctuation."""
    return _clean(s).casefold().strip(" .,;:")


# ---------------------------------------------------------------- strings
def normalize_text(raw: Any) -> NormResult:
    s = _clean(raw)
    if not s:
        return _bad("empty value")
    return _ok(s)


normalize_business_name = normalize_text


def normalize_operations(raw: Any) -> NormResult:
    s = _clean(raw)
    if not s:
        return _bad("empty value")
    return _ok(s.rstrip(" ."), s)


# ---------------------------------------------------------------- dates
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_US = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def normalize_date(raw: Any) -> NormResult:
    s = _clean(raw)
    if not s:
        return _bad("empty value")
    for pattern, order in ((_ISO, "ymd"), (_US, "mdy")):
        m = pattern.match(s)
        if m:
            parts = dict(zip(order, map(int, m.groups())))
            try:
                d = date(parts["y"], parts["m"], parts["d"])
            except ValueError:
                return _bad(f"'{s}' is not a valid calendar date")
            return _ok(d.isoformat())
    if any(mon in s.lower() for mon in _MONTHS) and re.search(r"\b\d{4}\b", s):
        cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s, flags=re.I)
        try:
            # Parse with two different defaults: if they disagree, a component
            # (day/month/year) was missing in the source and we must not invent it.
            a = dateparser.parse(cleaned, default=datetime(2000, 1, 1))
            b = dateparser.parse(cleaned, default=datetime(2001, 2, 2))
        except (ValueError, OverflowError):
            return _bad(f"'{s}' is not a valid calendar date")
        if a.date() != b.date():
            return _bad(f"'{s}' is not a complete date")
        return _ok(a.date().isoformat())
    return _bad(f"'{s}' is not a recognizable date")


# ---------------------------------------------------------------- state
US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
_CODES = set(US_STATES.values())


def normalize_state(raw: Any) -> NormResult:
    s = _clean(raw).strip(" .,")
    if not s:
        return _bad("empty value")
    if s.upper() in _CODES:
        return _ok(s.upper())
    code = US_STATES.get(s.lower().replace(".", ""))
    if code:
        return _ok(code)
    return _bad(f"'{s}' is not a recognized US state name or code")


# ---------------------------------------------------------------- numbers
_NUM = r"(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
_COUNT_RE = re.compile(
    rf"^{_NUM}\s*(?:vehicles?|units?|power units?|trucks?|vans?|autos?)?\.?$", re.I
)
_RADIUS_RE = re.compile(
    rf"^(?:within|up to)?\s*{_NUM}\s*(?:miles?|mi\.?)?(?:\s*radius)?\.?$", re.I
)


def _to_number(s: str) -> float:
    return float(s.replace(",", ""))


def normalize_count(raw: Any) -> NormResult:
    s = _clean(raw)
    if not s:
        return _bad("empty value")
    m = _COUNT_RE.match(s)
    if not m:
        return _bad(f"'{s}' is not a whole number of vehicles")
    n = _to_number(m.group(1))
    if n < 0:
        return _bad(f"'{s}' is negative")
    if n != int(n):
        return _bad(f"'{s}' is not a whole number")
    return _ok(int(n))


def normalize_radius(raw: Any) -> NormResult:
    s = _clean(raw)
    if not s:
        return _bad("empty value")
    m = _RADIUS_RE.match(s)
    if not m:
        return _bad(f"'{s}' is not a numeric radius in miles")
    n = _to_number(m.group(1))
    if n < 0:
        return _bad(f"'{s}' is negative")
    value: Any = int(n) if n == int(n) else n
    return _ok(value, f"{value} miles")


# ---------------------------------------------------------------- booleans
_TRUE = {"yes", "y", "true"}
_FALSE = {"no", "n", "false"}


def normalize_bool(raw: Any) -> NormResult:
    if isinstance(raw, bool):
        return _ok(raw, "Yes" if raw else "No")
    s = _clean(raw).strip(" .!").lower()
    if not s:
        return _bad("empty value")
    if s in _TRUE:
        return _ok(True, "Yes")
    if s in _FALSE:
        return _ok(False, "No")
    return _bad(f"'{_clean(raw)}' is not an explicit Yes/No answer (ambiguous)")


NORMALIZERS: dict[str, Callable[[Any], NormResult]] = {
    "business_name": normalize_business_name,
    "requested_effective_date": normalize_date,
    "garaging_state": normalize_state,
    "operations_description": normalize_operations,
    "declared_vehicle_count": normalize_count,
    "operating_radius_miles": normalize_radius,
    "hazardous_materials": normalize_bool,
    "loss_runs_present": normalize_bool,
    "schedule_vehicle_count": normalize_count,
}


def normalize(field: str, raw: Any) -> NormResult:
    return NORMALIZERS[field](raw)
