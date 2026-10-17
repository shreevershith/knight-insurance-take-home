"""FastAPI app: static UI + stateless JSON API.

Every request carries everything it needs (uploaded files, or the field results
the browser already holds), and nothing is stored server-side, so one packet's
data can never leak into another.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .ingest import ingest_packet
from .llm import LLMClient, LLMConfig, client_from_env
from .models import ALL_FIELDS, FieldResult, Narrative
from .narrative import generate_narrative
from .pipeline import Evaluation, ProcessResult, evaluate, process_packet
from .reconcile import OverrideError, apply_override, clear_override

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_FILES = 20
MAX_FILE_BYTES = 10 * 1024 * 1024

app = FastAPI(title="Underwriter Submission Review Assistant")


def get_llm() -> LLMClient:
    """Overridden in tests with a fake client."""
    return client_from_env()


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config() -> dict:
    cfg = LLMConfig.from_env()
    return {"provider": cfg.provider, "model": cfg.model,
            "key_configured": bool(cfg.api_key) or cfg.is_local}


@app.post("/api/process", response_model=ProcessResult)
async def process(files: list[UploadFile] = File(default=[]), email_text: Optional[str] = Form(default=None),
                  llm: LLMClient = Depends(get_llm)) -> ProcessResult:
    files = [f for f in files if f.filename]
    if not files and not (email_text and email_text.strip()):
        raise HTTPException(400, "Add the submission files and/or paste the broker email.")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Too many files (max {MAX_FILES} per submission).")
    payload: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(400, f"{f.filename} is larger than 10 MB.")
        payload.append((Path(f.filename).name, data))
    packet = ingest_packet(payload, pasted_email=email_text)
    return process_packet(packet, llm)


class FieldsRequest(BaseModel):
    fields: dict[str, FieldResult]


def _check_fields(fields: dict[str, FieldResult]) -> None:
    missing = [f for f in ALL_FIELDS if f not in fields]
    if missing:
        raise HTTPException(400, "Missing fields: " + ", ".join(missing))


class OverrideRequest(BaseModel):
    field: FieldResult
    value: Optional[str] = None
    confirm_absent: bool = False
    revert: bool = False


@app.post("/api/override", response_model=FieldResult)
def override(req: OverrideRequest) -> FieldResult:
    """Validate a correction with the same normalizer used for extraction."""
    if req.revert:
        return clear_override(req.field)
    try:
        return apply_override(req.field, req.value, confirm_absent=req.confirm_absent)
    except OverrideError as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/rerun", response_model=Evaluation)
def rerun(req: FieldsRequest) -> Evaluation:
    """Deterministic: recompute rules + issue list from the (possibly overridden) fields. No LLM call."""
    _check_fields(req.fields)
    return evaluate(req.fields)


@app.post("/api/narrative", response_model=Narrative)
def narrative(req: FieldsRequest, llm: LLMClient = Depends(get_llm)) -> Narrative:
    _check_fields(req.fields)
    ev = evaluate(req.fields)
    return generate_narrative(llm, req.fields, ev.rules, ev.overall_status, ev.issues)
