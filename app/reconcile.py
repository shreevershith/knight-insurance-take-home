"""Merge per-source mentions into one field value + state.

Never picks a preferred source: two different valid values => CONFLICT with
value null and every alternative kept with its evidence.
"""
from __future__ import annotations

import re
from typing import Optional

from .models import FIELD_LABELS, Alternative, Evidence, FieldResult, FieldState, Mention, Override
from .normalize import comparison_key, normalize


def reconcile_field(
    name: str,
    mentions: list[Mention],
    sources_checked: list[str],
    failed_sources: Optional[list[str]] = None,
) -> FieldResult:
    failed_sources = failed_sources or []
    base = dict(name=name, label=FIELD_LABELS.get(name, name), sources_checked=list(sources_checked),
                unchecked_sources=list(failed_sources))
    notes: list[str] = []

    absent = [m for m in mentions if m.explicitly_not_provided]
    stated = [m for m in mentions if not m.explicitly_not_provided]
    valid = [m for m in stated if m.valid]
    invalid = [m for m in stated if not m.valid]

    # Group valid mentions by normalized comparison key (insertion order kept).
    groups: dict[object, list[Mention]] = {}
    for m in valid:
        groups.setdefault(comparison_key(m.normalized), []).append(m)
    if name == "operations_description":
        groups = _merge_rewordings(groups, notes)

    if failed_sources and stated:
        notes.append(
            "Model extraction failed for " + ", ".join(failed_sources)
            + "; this value was not cross-checked against that source, so rules treat it as"
            " UNKNOWN until a reviewer confirms it."
        )
    if absent and stated:
        notes.append(
            "Also marked 'not provided' in: " + ", ".join(sorted({m.source_file for m in absent}))
            + " (a missing mention is not a conflict)."
        )

    def alt_from_group(ms: list[Mention]) -> Alternative:
        return Alternative(value=ms[0].normalized, display=ms[0].display or str(ms[0].normalized),
                           evidence=[m.evidence for m in ms])

    def alt_from_invalid(m: Mention) -> Alternative:
        return Alternative(value=None, display=m.raw_value or "", valid=False, error=m.error,
                           evidence=[m.evidence])

    if len(groups) >= 2 or (len(groups) == 1 and invalid):
        alts = [alt_from_group(ms) for ms in groups.values()] + [alt_from_invalid(m) for m in invalid]
        if len(groups) >= 2:
            notes.insert(0, "Sources state different values: "
                         + " vs ".join(f"'{a.display}'" for a in alts if a.valid) + ". No source is preferred.")
        if invalid:
            notes.append("Unusable value(s) also stated: "
                         + "; ".join(f"'{m.raw_value}' in {m.source_file} ({m.error})" for m in invalid))
        return FieldResult(**base, value=None, state=FieldState.CONFLICT, alternatives=alts,
                           evidence=[e for a in alts for e in a.evidence], notes=notes)

    if len(groups) == 1:
        ms = next(iter(groups.values()))
        return FieldResult(**base, value=ms[0].normalized, display=ms[0].display,
                           state=FieldState.KNOWN, evidence=[m.evidence for m in ms], notes=notes)

    if invalid:
        notes.insert(0, "; ".join(f"'{m.raw_value}' in {m.source_file}: {m.error}" for m in invalid))
        return FieldResult(**base, value=None, state=FieldState.INVALID,
                           alternatives=[alt_from_invalid(m) for m in invalid],
                           evidence=[m.evidence for m in invalid], notes=notes)

    # No stated value anywhere.
    if failed_sources:
        return FieldResult(
            **base, value=None, state=FieldState.NOT_EXTRACTED,
            notes=["Model extraction failed for " + ", ".join(failed_sources)
                   + "; field not extracted (not the same as missing)."],
            evidence=[m.evidence for m in absent],
        )
    inspected = ", ".join(sources_checked) or "no text sources"
    evidence = [m.evidence for m in absent] + [Evidence(
        source_file="(packet)", locator="sources inspected",
        excerpt_or_observation=f"No value found in: {inspected}",
    )]
    return FieldResult(**base, value=None, state=FieldState.MISSING, evidence=evidence, notes=notes)


_STOPWORDS = {"a", "an", "the", "of", "and", "for", "to", "in", "on", "with", "by", "its", "their", "our"}


def _content_words(text: str) -> frozenset:
    return frozenset(w for w in re.findall(r"[a-z0-9]+", text.casefold()) if w not in _STOPWORDS)


def _merge_rewordings(groups: dict, notes: list[str]) -> dict:
    """Merge operations descriptions whose content words are a subset of another's.

    "hauling building supplies" and "Hauling of building supplies" describe the same
    operations; genuinely different descriptions still stay separate (CONFLICT).
    """
    merged: list[list] = []
    for key, ms in groups.items():
        words = _content_words(str(ms[0].normalized))
        for g in merged:
            if words and (words <= g[0] or g[0] <= words):
                g[0] = g[0] | words
                g[1].extend(ms)
                break
        else:
            merged.append([words, list(ms)])
    if len(merged) < len(groups):
        shown = sorted({m.display or str(m.normalized) for g in merged for m in g[1]})
        notes.append("Worded differently across sources, treated as the same description: "
                     + " / ".join(f"'{d}'" for d in shown) + ".")
    return {i: g[1] for i, g in enumerate(merged)}


# ---------------------------------------------------------------- overrides
class OverrideError(ValueError):
    pass


def apply_override(field: FieldResult, raw_value: Optional[str], confirm_absent: bool = False,
                   note: Optional[str] = None) -> FieldResult:
    """Return a copy of the field with a validated human override.

    Original value, state, alternatives and evidence are untouched.
    """
    if confirm_absent:
        ov = Override(value=None, display="(confirmed absent)", confirmed_absent=True, note=note)
    else:
        if raw_value is None or not str(raw_value).strip():
            raise OverrideError("Enter a value, or choose 'confirm absent'.")
        res = normalize(field.name, raw_value)
        if not res.valid:
            raise OverrideError(f"Invalid value for {field.label or field.name}: {res.error}")
        ov = Override(value=res.value, display=res.display or str(res.value), note=note)
    return field.model_copy(update={"override": ov})


def clear_override(field: FieldResult) -> FieldResult:
    return field.model_copy(update={"override": None})
