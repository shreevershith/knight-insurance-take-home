"""File intake: decode, extract text, classify documents, build the attachment inventory.

Everything here is deterministic. Document type is decided from the content
heading (first few non-empty lines), never from the filename.
"""
from __future__ import annotations

import email
import email.policy
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import pdfplumber

from .models import FIELD_LABELS, AttachmentInfo, Evidence, FieldResult, FieldState
from .schedule import derive_schedule_count, parse_schedule

log = logging.getLogger(__name__)

PASTED_EMAIL_NAME = "pasted broker email"
HEADING_LINES = 5
_LOSS_RE = re.compile(r"\bloss(?:es)?[\s-]+(?:runs?|history|experience)\b|\bclaims?\s+history\b", re.I)
_APP_RE = re.compile(r"\bapplication\b", re.I)


@dataclass
class TextSource:
    """A readable text source sent to the LLM for field extraction."""

    source_file: str
    kind: str  # "email" | "pdf"
    pages: list[str]  # email: one entry; pdf: one entry per page

    @property
    def text(self) -> str:
        return "\n".join(self.pages)


@dataclass
class Packet:
    sources: list[TextSource] = field(default_factory=list)
    inventory: list[AttachmentInfo] = field(default_factory=list)
    csv_files: list[tuple[str, str]] = field(default_factory=list)
    loss_runs_docs: list[tuple[str, int, str]] = field(default_factory=list)  # file, page, heading
    warnings: list[str] = field(default_factory=list)
    schedule: Optional[FieldResult] = None
    loss_runs: Optional[FieldResult] = None


# ---------------------------------------------------------------- decoding
def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1")
    return text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")


def parse_eml(data: bytes) -> Optional[str]:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    body = msg.get_body(preferencelist=("plain",))
    if body is None:
        return None
    content = body.get_content()
    header = "\n".join(f"{h}: {msg[h]}" for h in ("From", "To", "Subject") if msg[h])
    return (header + "\n\n" if header else "") + content.replace("\r\n", "\n").replace("\r", "\n")


def extract_pdf_pages(data: bytes) -> Optional[list[str]]:
    """Text per page; None if the PDF cannot be parsed or yields no text."""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [(p.extract_text() or "") for p in pdf.pages]
    except Exception as exc:  # pdfplumber/pdfminer raise many types
        log.info("PDF parse failed: %s", type(exc).__name__)
        return None
    if not any(p.strip() for p in pages):
        return None
    return pages


# ---------------------------------------------------------------- classification
def heading_lines(text: str, n: int = HEADING_LINES) -> list[str]:
    return [ln.strip() for ln in text.split("\n") if ln.strip()][:n]


def classify_document(text: str) -> tuple[str, Optional[str]]:
    """Return (type, matching heading line). Type: loss_runs | application | unclassified.

    Only the heading is used, so an application that *asks* about loss runs in
    its body is still an application.
    """
    for line in heading_lines(text):
        if _LOSS_RE.search(line):
            return "loss_runs", line
        if _APP_RE.search(line):
            return "application", line
    return "unclassified", None


# ---------------------------------------------------------------- packet
def ingest_packet(files: list[tuple[str, bytes]], pasted_email: Optional[str] = None) -> Packet:
    packet = Packet()
    if pasted_email and pasted_email.strip():
        text = pasted_email.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
        packet.sources.append(TextSource(PASTED_EMAIL_NAME, "email", [text]))
        packet.inventory.append(AttachmentInfo(
            filename=PASTED_EMAIL_NAME, detected_type="email", readable=True,
            rows=len(text.splitlines()), note="Pasted into the text box",
        ))

    for filename, data in files:
        lower = filename.lower()
        if lower.endswith(".pdf") or data[:5] == b"%PDF-":
            _ingest_pdf(packet, filename, data)
        elif lower.endswith(".csv"):
            text = decode_text(data)
            packet.csv_files.append((filename, text))
            parsed = parse_schedule(text)
            packet.inventory.append(AttachmentInfo(
                filename=filename, detected_type="vehicle_schedule", readable=parsed.ok,
                rows=parsed.count if parsed.ok else None,
                note=None if parsed.ok else parsed.error,
            ))
        elif lower.endswith((".txt", ".eml")):
            _ingest_text(packet, filename, data, is_eml=lower.endswith(".eml"))
        else:
            packet.inventory.append(AttachmentInfo(
                filename=filename, detected_type="unsupported", readable=False,
                note="File type not supported (expected .pdf, .csv, .txt or .eml)",
            ))

    if len(packet.csv_files) > 1:
        packet.warnings.append("More than one CSV supplied; schedule count is INVALID.")
    packet.schedule = derive_schedule_count(packet.csv_files)
    packet.loss_runs = derive_loss_runs(packet)
    return packet


def _ingest_pdf(packet: Packet, filename: str, data: bytes) -> None:
    pages = extract_pdf_pages(data)
    if pages is None:
        packet.inventory.append(AttachmentInfo(
            filename=filename, detected_type="unclassified", readable=False,
            note="PDF could not be read (parse error or no selectable text)",
        ))
        return
    doc_type, heading = classify_document("\n".join(pages))
    packet.inventory.append(AttachmentInfo(
        filename=filename, detected_type=doc_type, readable=True, pages=len(pages),
        note=f"Heading: {heading}" if heading else "Heading did not identify the document type",
    ))
    if doc_type == "loss_runs":
        page_no = next((i for i, p in enumerate(pages, 1) if heading and heading in p), 1)
        packet.loss_runs_docs.append((filename, page_no, heading or ""))
    else:
        packet.sources.append(TextSource(filename, "pdf", pages))


def _ingest_text(packet: Packet, filename: str, data: bytes, is_eml: bool) -> None:
    text = parse_eml(data) if is_eml else decode_text(data)
    if text is None or not text.strip():
        packet.inventory.append(AttachmentInfo(
            filename=filename, detected_type="email", readable=False,
            note="No readable plain-text body",
        ))
        return
    doc_type, heading = classify_document(text)
    if doc_type == "loss_runs":
        packet.inventory.append(AttachmentInfo(
            filename=filename, detected_type="loss_runs", readable=True,
            rows=len(text.splitlines()), note=f"Heading: {heading}",
        ))
        packet.loss_runs_docs.append((filename, 1, heading or ""))
        return
    packet.sources.append(TextSource(filename, "email", [text]))
    packet.inventory.append(AttachmentInfo(
        filename=filename, detected_type="email", readable=True, rows=len(text.splitlines()),
    ))


# ---------------------------------------------------------------- loss runs
def derive_loss_runs(packet: Packet) -> FieldResult:
    name = "loss_runs_present"
    checked = [a.filename for a in packet.inventory]
    base = dict(name=name, label=FIELD_LABELS[name], sources_checked=checked)

    if packet.loss_runs_docs:
        return FieldResult(
            **base, value=True, display="Yes", state=FieldState.KNOWN,
            evidence=[Evidence(source_file=f, locator=f"PDF page {pg}" if f.lower().endswith(".pdf") else "document heading",
                               excerpt_or_observation=h) for f, pg, h in packet.loss_runs_docs],
        )

    inventory_obs = "; ".join(
        f"{a.filename} ({a.detected_type}{'' if a.readable else ', unreadable'})" for a in packet.inventory
    ) or "no files"
    # Email statements about loss runs are recorded as observations only - they never count.
    email_notes: list[Evidence] = []
    for src in packet.sources:
        if src.kind != "email":
            continue
        for i, line in enumerate(src.text.split("\n"), 1):
            if re.search(r"loss[\s-]+runs?|loss history", line, re.I):
                email_notes.append(Evidence(
                    source_file=src.source_file, locator=f"email body, line {i}",
                    excerpt_or_observation=f"{line.strip()} (email statement - not an attachment)",
                ))

    potential = [a for a in packet.inventory
                 if (not a.readable and a.detected_type not in ("vehicle_schedule", "email")) or a.detected_type == "unclassified"]
    if potential:
        names = ", ".join(a.filename for a in potential)
        return FieldResult(
            **base, value=None, state=FieldState.INVALID,
            notes=[f"Could not determine whether these attachments are loss runs: {names} "
                   "(unreadable or document type not identifiable)."],
            evidence=[Evidence(source_file="(packet)", locator="uploaded attachment inventory",
                               excerpt_or_observation=inventory_obs)] + email_notes,
        )
    return FieldResult(
        **base, value=False, display="No", state=FieldState.KNOWN,
        evidence=[Evidence(source_file="(packet)", locator="uploaded attachment inventory",
                           excerpt_or_observation=f"No loss runs / loss history report among supplied files: {inventory_obs}")]
        + email_notes,
    )
