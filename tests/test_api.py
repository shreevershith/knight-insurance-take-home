"""HTTP API with the fake LLM injected via FastAPI dependency override."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_llm
from tests.fake_llm import FakeLLM

SAMPLES = Path(__file__).resolve().parent.parent / "candidate_materials" / "sample_submissions"


@pytest.fixture
def fake():
    llm = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    yield llm
    app.dependency_overrides.clear()


@pytest.fixture
def client(fake):
    return TestClient(app)


def upload(client, name, **data):
    files = [("files", (p.name, p.read_bytes())) for p in sorted((SAMPLES / name).iterdir())]
    return client.post("/api/process", files=files, data=data)


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Submission Review Assistant" in r.text


def test_empty_request_rejected(client):
    assert client.post("/api/process").status_code == 400


def test_sub_a_then_sub_b_returns_no_sub_a_data(client):
    a = upload(client, "SUB-A")
    assert a.json()["overall_status"] == "READY_FOR_REVIEW"
    b = upload(client, "SUB-B")
    assert b.status_code == 200
    body = b.text
    assert "Pacific Harbor" not in body and "loss_runs.pdf" not in body
    assert [r["status"] for r in b.json()["rules"]] == ["FLAG", "PASS", "UNKNOWN", "UNKNOWN", "FLAG"]


def test_pasted_email_only(client):
    email = (SAMPLES / "SUB-B" / "broker_email.txt").read_text()
    r = client.post("/api/process", data={"email_text": email}).json()
    assert r["fields"]["business_name"]["value"] == "Canyon Parcel Example LLC"
    assert r["fields"]["schedule_vehicle_count"]["state"] == "MISSING"


def test_override_validation_and_rerun(client, fake):
    res = upload(client, "SUB-C").json()
    fields = res["fields"]
    bad = client.post("/api/override", json={"field": fields["operating_radius_miles"], "value": "far"})
    assert bad.status_code == 422 and "not a numeric radius" in bad.json()["detail"]

    ok = client.post("/api/override", json={"field": fields["operating_radius_miles"], "value": "80"}).json()
    assert ok["override"]["display"] == "80 miles" and ok["effective_state"] == "KNOWN"
    assert ok["state"] == "CONFLICT" and len(ok["alternatives"]) == 2  # original kept
    fields["operating_radius_miles"] = ok

    calls_before = len(fake.calls)
    ev = client.post("/api/rerun", json={"fields": fields}).json()
    assert len(fake.calls) == calls_before  # rerun is deterministic: no model call
    r3 = ev["rules"][2]
    assert r3["status"] == "PASS" and r3["inputs_used"][0]["override"] is True

    reverted = client.post("/api/override", json={"field": ok, "revert": True}).json()
    assert reverted["override"] is None and reverted["state"] == "CONFLICT"


def test_narrative_endpoint_reflects_overrides(client):
    fields = upload(client, "SUB-C").json()["fields"]
    fields["hazardous_materials"] = client.post(
        "/api/override", json={"field": fields["hazardous_materials"], "value": "No"}).json()
    n = client.post("/api/narrative", json={"fields": fields}).json()
    assert n["source"] == "model"
    assert any("HUMAN OVERRIDE" in o for o in n["overrides"])
    assert not any("Hazardous" in ln for g in n["issue_groups"] for ln in g["lines"])


def test_model_failure_still_returns_deterministic_results():
    app.dependency_overrides[get_llm] = lambda: FakeLLM(modes={"fail_extraction", "fail_narrative"})
    try:
        r = upload(TestClient(app), "SUB-B").json()
    finally:
        app.dependency_overrides.clear()
    assert {x["status"] for x in r["extraction"]} == {"failed"}
    assert r["fields"]["schedule_vehicle_count"]["value"] == 2
    assert r["rules"][4]["status"] == "FLAG"
    assert r["narrative"]["source"] == "template"
