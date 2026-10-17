"""Deterministic vehicle-schedule count from the CSV (no LLM, no VIN validation)."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Optional

from .models import FIELD_LABELS, Evidence, FieldResult, FieldState

EXPECTED_HEADER = ["vehicle_id", "vin", "year", "make", "model"]
HEADER_TEXT = ",".join(EXPECTED_HEADER)


@dataclass
class ScheduleParse:
    ok: bool
    count: Optional[int] = None
    error: Optional[str] = None
    vehicle_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_schedule(text: str) -> ScheduleParse:
    """Count nonblank data rows after the exact header. Header-only => 0."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        return ScheduleParse(False, error=f"CSV could not be parsed: {exc}")
    nonblank = [r for r in rows if any(c.strip() for c in r)]
    if not nonblank:
        return ScheduleParse(False, error="CSV is empty (no header row)")
    header = [c.strip().lower() for c in nonblank[0]]
    if header != EXPECTED_HEADER:
        return ScheduleParse(
            False, error=f"CSV header is '{','.join(nonblank[0])}'; expected '{HEADER_TEXT}'"
        )
    data = nonblank[1:]
    result = ScheduleParse(True, count=len(data))
    result.vehicle_ids = [r[0].strip() for r in data if r]
    odd = [i for i, r in enumerate(data, 1) if len(r) != len(EXPECTED_HEADER)]
    if odd:
        result.notes.append(
            f"Data row(s) {', '.join(map(str, odd))} do not have 5 columns; still counted as vehicle records."
        )
    return result


def derive_schedule_count(csv_files: list[tuple[str, str]]) -> FieldResult:
    """csv_files: list of (filename, decoded text)."""
    name = "schedule_vehicle_count"
    base = dict(name=name, label=FIELD_LABELS[name], sources_checked=[f for f, _ in csv_files])
    if not csv_files:
        return FieldResult(
            **base,
            state=FieldState.MISSING,
            evidence=[Evidence(
                source_file="(packet)",
                locator="uploaded attachment inventory",
                excerpt_or_observation="No vehicle schedule CSV was supplied in this packet.",
            )],
        )
    if len(csv_files) > 1:
        names = ", ".join(f for f, _ in csv_files)
        return FieldResult(
            **base,
            state=FieldState.INVALID,
            notes=[f"Multiple CSV files supplied ({names}); cannot tell which is the vehicle schedule."],
            evidence=[Evidence(
                source_file=f, locator="uploaded attachment inventory",
                excerpt_or_observation="One of several CSV files supplied; schedule count not derived.",
            ) for f, _ in csv_files],
        )
    filename, text = csv_files[0]
    parsed = parse_schedule(text)
    if not parsed.ok:
        return FieldResult(
            **base,
            state=FieldState.INVALID,
            notes=[parsed.error or "CSV unreadable"],
            evidence=[Evidence(source_file=filename, locator="CSV header",
                               excerpt_or_observation=parsed.error or "CSV unreadable")],
        )
    n = parsed.count or 0
    if n == 0:
        locator = "CSV header only (0 data rows)"
        obs = f"Header '{HEADER_TEXT}' present with no nonblank data rows."
    else:
        locator = f"CSV data rows 1-{n} (header excluded)" if n > 1 else "CSV data row 1 (header excluded)"
        ids = ", ".join(i for i in parsed.vehicle_ids if i)
        obs = f"{n} nonblank data row(s) after header '{HEADER_TEXT}'" + (f" (vehicle_id: {ids})" if ids else "")
    return FieldResult(
        **base,
        value=n,
        display=str(n),
        state=FieldState.KNOWN,
        notes=parsed.notes,
        evidence=[Evidence(source_file=filename, locator=locator, excerpt_or_observation=obs)],
    )
