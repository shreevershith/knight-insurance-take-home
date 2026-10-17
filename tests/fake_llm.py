"""Test double for the LLM client. Lives only under tests/.

It derives its answers from the text it is sent (a simple label/value parser for
extraction; the structured payload for the narrative) - nothing is hard-coded
per sample, so editing a sample file changes its output.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from app.llm import LLMError, run_with_retry

LABELS = {
    "business_name": ["business name", "applicant name", "named insured"],
    "requested_effective_date": ["requested effective date", "effective date"],
    "garaging_state": ["garaging state"],
    "operations_description": ["operations description", "operations"],
    "declared_vehicle_count": ["declared vehicle count", "vehicle count", "number of vehicles"],
    "operating_radius_miles": ["operating radius miles", "operating radius", "radius"],
    "hazardous_materials": ["hazardous materials", "hazmat"],
}
_LINE_RES = [
    (field, re.compile(rf"^\s*{re.escape(label)}\s*(?:\(miles\))?\s*[:\-]?\s+(.+?)\s*$", re.I))
    for field, labels in LABELS.items() for label in sorted(labels, key=len, reverse=True)
]
_DOC_RE = re.compile(r"<<<DOC-(\w+)>>>\n(.*)\n<<<END-DOC-\1>>>", re.S)
_DATA_RE = re.compile(r"<<<DATA-(\w+)>>>\n(.*)\n<<<END-DATA-\1>>>", re.S)


def parse_document(text: str) -> dict:
    fields: dict[str, list] = {f: [] for f in LABELS}
    for line in text.split("\n"):
        if re.match(r"^\[PAGE \d+\]$", line.strip()):
            continue
        for field, rx in _LINE_RES:
            m = rx.match(line)
            if m:
                value = m.group(1)
                if re.fullmatch(r"not provided\.?", value, re.I):
                    fields[field].append({"raw_value": None, "excerpt": line.strip(),
                                          "explicitly_not_provided": True})
                else:
                    fields[field].append({"raw_value": value, "excerpt": line.strip(),
                                          "explicitly_not_provided": False})
                break
    return {"fields": fields}


def write_narrative(payload: dict) -> dict:
    known = payload["known_applicant_fields"]
    issues = payload["issues"]
    lines = [i["facts"] for i in issues]
    return {
        "snapshot": "Applicant details: " + "; ".join(f"{k} {v}" for k, v in known.items()) + ".",
        "issue_lines": lines,
        "email_subject": "Information request for your submission" if issues else "",
        "email_body": ("Hello,\n\nPlease help with the following items:\n"
                       + "\n".join(f"- {ln}" for ln in lines) + "\n\nThank you,\nUnderwriting team")
        if issues else "",
    }


class FakeLLM:
    """modes: set of behaviours, e.g. {"fail_extraction"}, {"bad_json"}, {"banned_once"}.

    fail_sources: source filenames whose extraction call times out.
    """

    provider = "fake"
    model = "fake-label-parser"

    def __init__(self, modes: Optional[set[str]] = None, fail_sources: Optional[set[str]] = None,
                 extra_mentions: Optional[dict[str, list[dict]]] = None):
        self.modes = modes or set()
        self.fail_sources = fail_sources or set()
        self.extra_mentions = extra_mentions or {}
        self.calls: list[tuple[str, str, str]] = []  # (purpose, system, user)
        self._narrative_calls = 0

    def chat_json(self, system: str, user: str, *, validate: Optional[Callable[[dict], Any]] = None) -> Any:
        purpose = "narrative" if "issue_lines" in system else "extraction"
        return run_with_retry(lambda: self._respond(purpose, system, user), validate)

    def _respond(self, purpose: str, system: str, user: str) -> str:
        self.calls.append((purpose, system, user))
        if "bad_json" in self.modes:
            return "this is not json {"
        if purpose == "extraction":
            src = re.match(r"Source file: (.+?) \(", user)
            if "fail_extraction" in self.modes or (src and src.group(1) in self.fail_sources):
                raise LLMError("timeout", "No response within 30 s.")
            doc = _DOC_RE.search(user)
            out = parse_document(doc.group(2) if doc else "")
            for f, ms in self.extra_mentions.items():
                out["fields"][f] += ms
            if "missing_keys" in self.modes:
                out["fields"].pop("hazardous_materials")
            return json.dumps(out)

        if "fail_narrative" in self.modes:
            raise LLMError("rate_limit", "Provider rate limit reached (HTTP 429).")
        self._narrative_calls += 1
        data = _DATA_RE.search(user)
        out = write_narrative(json.loads(data.group(2)))
        if "banned_always" in self.modes or ("banned_once" in self.modes and self._narrative_calls == 1):
            out["snapshot"] += " We recommend approval; the risk looks low."
        if "wrong_status" in self.modes:
            out["snapshot"] += " This submission is ready for review."
        if "drop_issue" in self.modes and out["issue_lines"]:
            out["issue_lines"].pop()
        return json.dumps(out)
