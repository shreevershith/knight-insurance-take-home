from pathlib import Path

import pytest

from app.ingest import classify_document, decode_text, ingest_packet
from app.models import FieldState
from app.rules import rule_r5
from app.schedule import derive_schedule_count, parse_schedule
from tests.pdfgen import make_pdf

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"
HEADER = "vehicle_id,vin,year,make,model"


def load(sub: str) -> list[tuple[str, bytes]]:
    return [(p.name, p.read_bytes()) for p in sorted((SAMPLES / sub).iterdir())]


# ---------------- CSV
def test_csv_crlf_bom_blank_lines():
    text = decode_text(("﻿" + HEADER + "\r\nA,1,2022,M,V\r\n\r\n,,,,\r\nB,2,2023,M,V\r\n").encode("utf-8"))
    assert parse_schedule(text).count == 2


def test_csv_header_only_is_zero():
    f = derive_schedule_count([("v.csv", HEADER + "\n")])
    assert f.state == FieldState.KNOWN and f.value == 0


def test_csv_wrong_header_invalid():
    f = derive_schedule_count([("v.csv", "id,vin,year\nA,1,2\n")])
    assert f.state == FieldState.INVALID and f.value is None


def test_csv_header_case_and_spaces_tolerated():
    assert parse_schedule("Vehicle_ID, VIN ,year,make,model\nA,1,2,3,4\n").count == 1


def test_csv_empty_and_multiple():
    assert derive_schedule_count([("v.csv", "")]).state == FieldState.INVALID
    two = derive_schedule_count([("a.csv", HEADER + "\nA,1,2,3,4\n"), ("b.csv", HEADER + "\n")])
    assert two.state == FieldState.INVALID and "Multiple CSV" in two.notes[0]


def test_csv_missing_is_missing():
    assert derive_schedule_count([]).state == FieldState.MISSING


def test_csv_evidence_locator():
    f = derive_schedule_count([("vehicles.csv", HEADER + "\nA,1,2,3,4\nB,1,2,3,4\nC,1,2,3,4\n")])
    assert f.evidence[0].locator == "CSV data rows 1-3 (header excluded)"


# ---------------- classification
def test_classify_by_heading_not_body():
    app_text = "Commercial auto application\nSUB-X\nAre loss runs attached? Yes\nLoss history: see attached"
    assert classify_document(app_text)[0] == "application"
    assert classify_document("Loss runs report\nBusiness name X")[0] == "loss_runs"
    assert classify_document("Loss History Report\n")[0] == "loss_runs"
    assert classify_document("Memo\nhello")[0] == "unclassified"


# ---------------- R5 packet-level
def test_sample_a_zero_claims_report_passes():
    p = ingest_packet(load("SUB-A"))
    assert p.loss_runs.value is True and rule_r5(p.loss_runs).status.value == "PASS"
    types = {a.filename: a.detected_type for a in p.inventory}
    assert types == {"application.pdf": "application", "broker_email.txt": "email",
                     "loss_runs.pdf": "loss_runs", "vehicles.csv": "vehicle_schedule"}
    # loss runs report is not sent for field extraction
    assert [s.source_file for s in p.sources] == ["application.pdf", "broker_email.txt"]


def test_email_promise_only_flags():
    p = ingest_packet(load("SUB-B"))
    assert p.loss_runs.state == FieldState.KNOWN and p.loss_runs.value is False
    assert rule_r5(p.loss_runs).status.value == "FLAG"
    assert any("not an attachment" in e.excerpt_or_observation for e in p.loss_runs.evidence)
    assert p.loss_runs.evidence[0].locator == "uploaded attachment inventory"


def test_unreadable_pdf_unknown():
    files = load("SUB-B") + [("losses.pdf", b"%PDF-1.4 this is not really a pdf")]
    p = ingest_packet(files)
    bad = next(a for a in p.inventory if a.filename == "losses.pdf")
    assert bad.readable is False
    assert rule_r5(p.loss_runs).status.value == "UNKNOWN"


def test_application_mentioning_loss_runs_is_not_loss_runs():
    pdf = make_pdf([["Commercial auto application", "Loss runs attached: Yes", "Loss history report enclosed"]])
    p = ingest_packet([("loss_runs.pdf", pdf)])
    assert p.inventory[0].detected_type == "application"
    assert rule_r5(p.loss_runs).status.value == "FLAG"


def test_generated_loss_runs_pdf_by_heading_any_filename():
    pdf = make_pdf([["Loss History Report", "Reported claims 0"]])
    p = ingest_packet([("scan_0001.pdf", pdf)])
    assert rule_r5(p.loss_runs).status.value == "PASS"


def test_unclassified_readable_pdf_is_unknown():
    pdf = make_pdf([["Some memo", "nothing here"]])
    p = ingest_packet([("x.pdf", pdf)])
    assert rule_r5(p.loss_runs).status.value == "UNKNOWN"


def test_pdf_pages_and_pasted_email():
    pdf = make_pdf([["Commercial auto application", "Business name A"], ["Operating radius miles 90"]])
    p = ingest_packet([("app.pdf", pdf)], pasted_email="Business name: A\r\nRadius: 90\r\n")
    pdf_src = next(s for s in p.sources if s.kind == "pdf")
    assert len(pdf_src.pages) == 2 and "radius" in pdf_src.pages[1].lower()
    email_src = next(s for s in p.sources if s.kind == "email")
    assert "\r" not in email_src.text


def test_eml_upload():
    eml = (b"From: b@example.com\r\nTo: u@example.com\r\nSubject: S\r\n"
           b"Content-Type: text/plain; charset=utf-8\r\n\r\nBusiness name: X LLC\r\n")
    p = ingest_packet([("m.eml", eml)])
    assert "Business name: X LLC" in p.sources[0].text


def test_unsupported_file_listed_unreadable():
    p = ingest_packet([("photo.jpg", b"\xff\xd8\xff")])
    assert p.inventory[0].detected_type == "unsupported" and not p.inventory[0].readable


@pytest.mark.parametrize("sub,count", [("SUB-A", 3), ("SUB-B", 2), ("SUB-C", 3)])
def test_sample_schedule_counts(sub, count):
    assert ingest_packet(load(sub)).schedule.value == count
