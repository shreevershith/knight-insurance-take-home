# Underwriter Submission Review Assistant

Knight Insurance take-home: AI Solutions Developer. All data is fictional.

A small local web app that reads one commercial auto submission packet (broker email, application PDF, vehicle schedule CSV, and optional loss runs PDF), **extracts the business fields with source evidence**, **runs the five supplied rules (R1–R5) in plain code**, and shows an **underwriter summary** plus an **editable draft broker email** asking for missing, conflicting or flagged information. The email is never sent.

> The status shows readiness for human review only. It is not an approval, decline, quote or coverage decision.

---

## Quick start (clean clone)

Requires **Python 3.11+**. Developed and tested on Python 3.12 (Windows).

```bash
git clone <repo-url> knight-insurance-take-home
cd knight-insurance-take-home
python -m venv .venv
```

Activate the venv:
- Windows (PowerShell): `.venv\Scripts\Activate.ps1`
- Windows (Git Bash): `source .venv/Scripts/activate`
- macOS / Linux: `source .venv/bin/activate`

```bash
pip install -r requirements.txt
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
# edit .env and set LLM_API_KEY (see "Model / provider" below)
uvicorn app.main:app --port 8000
```

Open **http://localhost:8000**. Drag in the files from one folder in `sample_data/` (for example `sample_data/SUB-C/`) and click **Process submission**.

Run the tests (no API key or network needed):

```bash
python -m pytest -q
```

---

## Model / provider

| Setting | Default | Notes |
|---|---|---|
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | Any OpenAI-compatible endpoint |
| `LLM_API_KEY` | (none) | Read from `.env` only. Never logged or shown in the UI |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Used for extraction and for the narrative |
| `LLM_TIMEOUT_SECONDS` | `30` | Per call |

- **Groq (used for development and the demo):** create a free API key at https://console.groq.com/keys and paste it into `.env`.
  - Groq has retired the model first planned for this project, `llama-3.3-70b-versatile` (the API now returns `model_not_found`).
  - I tested `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`. Both produced exactly the expected results on the samples, and I chose `gpt-oss-120b`.
- **Ollama (local alternative, nothing leaves the machine):** install Ollama, then run `ollama pull llama3.1`. In `.env`, set `LLM_BASE_URL=http://localhost:11434/v1` and `LLM_MODEL=llama3.1`, and leave `LLM_API_KEY` empty. Only env changes are needed. The code path is the same, but I did **not** run the samples on Ollama (see Limitations).
- **Data handling:** Groq is a hosted service, so **document text is sent to Groq** for extraction. The narrative call sends only the structured results, never the documents. Use Ollama to keep everything local.

Every model call uses temperature 0 and JSON mode, has a timeout, and is retried once on a timeout, 429, 5xx or invalid JSON. Errors are typed (`auth`, `rate_limit`, `timeout`, `bad_json`, …) and shown in the UI.

---

## What it does

1. **Ingest (code).** Accepts multiple files and/or pasted email text for one packet.
   - Text is decoded with CRLF and BOM handled. PDFs are read page by page with `pdfplumber`.
   - Each document is typed from its **heading, not its filename**. An application that *asks* about loss runs is still an application.
   - Builds an **attachment inventory**: file, detected type, readable yes/no, pages or rows.
2. **Extract (LLM).** One call per text source (the email, and each PDF that isn't a loss runs report).
   - For each of the 7 text fields, the model returns a list of mentions: `{raw_value, excerpt, explicitly_not_provided}`.
   - It returns raw text only. Code does all the interpretation.
3. **Verify evidence (code).** Every mention must be found in the source text.
   - The excerpt must match a source line exactly (ignoring case, spacing and edge punctuation) or closely (similarity ≥ 0.85).
   - **The value itself must also be on that line.** A near-copy of a real line with a different number, such as "…radius miles 180" when the PDF says 80, is rejected.
   - The evidence shown is the **real source line**, with a locator computed by code (`PDF page 1`, `email body, line 13`, `CSV data rows 1-3 (header excluded)`, `uploaded attachment inventory`).
   - Mentions that fail are discarded with a visible warning.
4. **Normalize and reconcile (code).**
   - Values are normalized: dates to `YYYY-MM-DD` (impossible dates are INVALID), states to 2-letter codes, counts to whole numbers, radius to miles (150 = 150.0), Yes/No to booleans.
   - Mentions are then merged across sources, with no source ever preferred:
     - KNOWN: exactly one distinct valid value.
     - CONFLICT: two or more distinct values. The value is null and every alternative is kept with its evidence.
     - INVALID: only unusable values.
     - MISSING: no value anywhere. Lists the sources inspected, including "Not provided" lines.
     - NOT_EXTRACTED (internal): the model call failed for a source, so absence was never actually checked.
   - **Derived by code:**
     - `schedule_vehicle_count`: nonblank CSV rows after the exact header.
     - `loss_runs_present`: a readable loss runs or loss history report is attached. A promise in the email does not count.
5. **Rules (code).** R1–R5 exactly as in `rules.json`: pure functions with no I/O and no model. Overall status is READY_FOR_REVIEW only if all five PASS.
6. **Narrative (LLM writes, code decides).**
   - Code builds the issue list: Missing / Conflicting / Flagged / Unresolved.
   - The model receives **only the structured result** (known fields, issue list, rule counts, overrides), never the documents. It writes the applicant snapshot, one sentence per issue, and the broker email.
   - The status line, overrides list and disclaimer are fixed text written by code.
   - The output is validated (see Design decisions). On failure the model gets one retry with the reasons, then a clearly labelled **"Template draft — model unavailable, not AI-generated"** is shown instead.
7. **Human corrections.**
   - Any field can be corrected, or confirmed absent. Input is validated by the same normalizer and rejected with a clear message if invalid.
   - The effective value is labelled **HUMAN OVERRIDE**. The original value, state, alternatives and evidence stay visible, and the override can be reverted.
   - **Rerun checks** recomputes the rules deterministically with no model call. The summary and draft are then marked **stale**, with a **Regenerate** button.

8. **The page.** A single static page with no build step. Top to bottom:
   - Overall status, with PASS / FLAG / UNKNOWN counts and the disclaimer.
   - **Action items**: the code-built issue list. Each item has a **Review** button that jumps to the field with the correction box open.
   - The AI summary, the rule checks, and the fields with their evidence. Conflicting values appear side by side.
   - The documents received, and the editable draft email.
   - A sticky section nav. On narrow screens the packet panel collapses after processing, so the result appears first.

### Results on the supplied samples (live, Groq `openai/gpt-oss-120b`)

| Sample | R1 | R2 | R3 | R4 | R5 | Overall |
|---|---|---|---|---|---|---|
| SUB-A | PASS | PASS (3 = 3) | PASS (exactly 150) | PASS (No) | PASS (loss runs report) | READY_FOR_REVIEW |
| SUB-B | FLAG (no effective date) | PASS (2 = 2) | UNKNOWN (missing) | UNKNOWN (missing) | FLAG (email promise only) | NEEDS_REVIEW |
| SUB-C | PASS | FLAG (4 declared vs 3 rows) | UNKNOWN (email 180 vs PDF 80) | UNKNOWN (email Yes vs PDF No) | FLAG | NEEDS_REVIEW |

On each sample, all 7 fields were found in both the email and the PDF, and the evidence check discarded no mentions. Nothing about the samples is hard-coded. The same results come out of the end-to-end tests, which use a fake LLM that parses whatever document text it is given.

---

## Architecture

```
 browser (static/index.html, vanilla JS)
   │  multipart upload / JSON (stateless: the browser holds the result)
   ▼
 FastAPI  app/main.py      /api/process   /api/override   /api/rerun   /api/narrative   /api/config
   │
   ▼
 pipeline.py
   ingest.py ──────────► text sources, attachment inventory, document typing (by heading)
   │   ├ schedule.py ──► schedule_vehicle_count (CSV)            [code]
   │   └ derive_loss_runs ► loss_runs_present (inventory)        [code]
   ▼
   extraction.py ──LLM─► raw mentions per source (JSON mode, Pydantic-validated)
   │   └ verify ───────► excerpt + value must be in the source; locator computed     [code]
   ▼
   normalize.py + reconcile.py ► field value + state (KNOWN/MISSING/CONFLICT/INVALID/NOT_EXTRACTED)  [code]
   ▼
   rules.py ───────────► R1–R5 + overall status (pure functions)                   [code]
   ▼
   narrative.py
       build_issues ───► deterministic issue list                                  [code]
       LLM ────────────► snapshot, issue sentences, broker email (structured result only)
       validate ───────► retry once ► labelled template fallback                   [code]
 llm.py: OpenAI-compatible client (Groq / Ollama via env), timeout, one retry, typed errors
```

The model reads documents and writes prose. Code decides every value, state, rule result and issue.

---

## Design decisions

- **The model reads and writes, code decides.** The model never normalizes, chooses between sources, evaluates a rule or decides what the email asks for. Those are deterministic and unit-tested.
- **Evidence verification is in code.** A model can paraphrase or invent an excerpt, so the app keeps a mention only if its line and its value can be found in the source. Page and line numbers are computed, not taken from the model. This is what makes the evidence trustworthy.
- **Conflicts are never resolved silently.** Two different valid values give CONFLICT with a null value, both alternatives and their evidence. A valid value plus an unusable one for the same field is also a CONFLICT. A "Not provided" in one source next to a value in another is **not** a conflict.
- **NOT_EXTRACTED, and values that weren't cross-checked.** If a source's model call fails, a field with no value is NOT_EXTRACTED rather than MISSING, because its absence was never verified. A field with a value from only the sources that worked is shown, but tagged **not cross-checked**, and rules treat it as UNKNOWN until a reviewer confirms it. Otherwise a failed call on the application could hide an email-vs-PDF conflict and produce a false PASS or READY_FOR_REVIEW.
- **The server is stateless.** No session, cache or database. Each request carries its own files, or the field results the browser already holds, so one packet can't leak into another. The UI also clears all state on New submission and when a new packet is processed, and ignores late responses from a previous packet.
- **Prompt-injection handling.**
  - Document text is wrapped in markers with a random ID per call. Copies of the marker inside the document are removed.
  - The system prompt says the content is untrusted data and that instructions inside it must never be followed.
  - The narrative step never sees documents.
  - Whatever the model returns must still pass evidence verification and the narrative checks.
  - In the UI, all document text is rendered with `textContent`, never `innerHTML`.
- **Narrative checks (code):**
  - Exactly one issue sentence per issue, each naming its field and quoting its values (both values for a conflict).
  - The email asks about every issue.
  - Sentences are complete, not bare labels.
  - No forbidden words: approve, decline, recommend, risk, premium, price, quote, bind, eligible, coverage, accept, reject. Applicant names and descriptions are blanked out first, so "Risk Logistics LLC" does not trip the check.
  - No status wording that contradicts the rule engine.
  - The status line and the disclaimer (which itself contains "decline" and "quote") are fixed text written by code, outside the checked model text.
- **Normalization choices:**
  - Operations descriptions are compared ignoring case, spacing and edge punctuation, so "…retail goods." and "…retail goods" agree.
  - "N/A" for hazardous materials is ambiguous, so it is INVALID, not No and not missing.
  - Absence is never treated as No.
- **Loss runs.** A readable report titled loss runs or loss history counts, even with zero claims. An email statement never counts. An unreadable or unclassifiable PDF makes R5 UNKNOWN unless a real report is also attached. Because the spec has no "UNKNOWN" field state, this case is stored as INVALID with a null value and an explanatory note.

### Notes on the supplied materials

- *"Eight business fields"* in the brief: the 7 text fields above plus `loss_runs_present`. `schedule_vehicle_count` is the separately derived count, as in `field_specification.json`.
- The JSON files and the PDF agree on every rule. I found no other inconsistencies.

---

## Tests

```bash
python -m pytest -q        # 160 passed (about 4 s, no network, no API key)
```

No test calls a live model. `tests/fake_llm.py` is a test-only stand-in injected through the FastAPI dependency (`app.dependency_overrides`) or passed directly. It **derives its answers from the text it receives**: a label/value line parser for extraction, and the structured payload for the narrative. It also has failure modes: timeout, 429, bad JSON, missing keys, a hallucinated value, banned words, a wrong status, a dropped issue.

| Area | Examples |
|---|---|
| R1 | missing date → FLAG; missing plus conflict → FLAG (precedence); conflict only → UNKNOWN; invalid date → UNKNOWN |
| R2 | equal → PASS; 4 vs 3 → FLAG; 0 vs 0 → PASS; missing → UNKNOWN; bad CSV → UNKNOWN |
| R3 | 150 / 150.0 → PASS; 150.1 / 180 → FLAG; 180 vs 80 conflict → UNKNOWN; negative / non-numeric / missing → UNKNOWN |
| R4 | Yes → FLAG; No → PASS; missing / ambiguous / conflict → UNKNOWN |
| R5 | readable zero-claims report → PASS; email promise only → FLAG; unreadable PDF → UNKNOWN; application mentioning loss runs ≠ loss runs report |
| Normalize, reconcile, CSV | dates (including impossible dates), states, counts, booleans; conflict keeps both alternatives with a null value; missing ≠ conflict; case-insensitive names; CRLF, BOM, blank lines, header-only, wrong header, multiple CSVs |
| Evidence | hallucinated near-copy discarded; value not on the quoted line discarded; fuzzy excerpt accepted; real line and locator substituted |
| Failure handling | all calls fail → deterministic results kept, fields NOT_EXTRACTED, error surfaced, template labelled; one source fails → value not cross-checked → UNKNOWN; retry and error types |
| Overrides | invalid input rejected; original evidence kept; rerun changes the rule status with no model call; override labelled; revert |
| API / isolation | SUB-A then SUB-B returns no SUB-A data; pasted email only; model failure over HTTP |
| Narrative | banned words, contradicting status, dropped issue, missing conflict value and bare labels rejected; business-name masking; retry then template; documents never sent to the narrative call; injection text stays inside the data markers |
| End to end | SUB-A / SUB-B / SUB-C give the expected rule results |

---

## AI coding tools used

- **Claude Code** (Anthropic, desktop app) was the only AI coding tool used. It drafted the code, tests and README from my written specification, phase by phase, and ran the tests and live checks. I reviewed each phase and made the design decisions.
- The runtime LLM is Groq `openai/gpt-oss-120b`, as described above.

## Time spent

About 2 hours 10 minutes of build time on Saturday, October 17, 2026 (first commit to final code commit), not counting time spent reading the materials and recording the demo video.

---

## Known limitations and incomplete items

- **Ollama not run:** the Ollama path needs env changes only and uses the same code, but I didn't run the samples on a local model. Smaller local models may return weaker JSON or excerpts; failures show up as visible errors or warnings, not wrong values.
- **Evidence matching is line-based:**
  - An excerpt that wraps across two PDF lines isn't matched and is discarded with a warning.
  - A value the model rewrites instead of copying (e.g. "CA" when the line says "California") is discarded, not matched by meaning. The prompt asks for verbatim values, and this didn't happen on the samples.
  - There is no fallback search when the quoted line can't be found; the mention is simply dropped with a warning.
- **"Not cross-checked" works per source, not per field:** a source counts as unchecked only when its whole model call fails. If the evidence check discards a single field's mentions, that field is treated as not mentioned in that source.
- **Unreadable PDFs:** an unreadable PDF makes R5 UNKNOWN and appears in the inventory. It does not mark other fields as not cross-checked.
- **Free-text comparison:** operations descriptions and business names that are worded differently, beyond case, spacing and edge punctuation, show as a CONFLICT for the reviewer to resolve. There is no meaning-based matching.
- **Narrative check limits:** the snapshot isn't checked fact by fact; it only goes through the banned-word and status checks. The prompt limits it to the known fields.
- **Out of scope:** no OCR or scanned PDFs, no bounding-box highlighting (optional in the brief), no `.docx` or images, no mailbox, auth, database or deployment.
- **Data persistence:** results aren't kept. Refreshing the page or choosing New submission discards the review, by design.
- **Upload limits:** 20 files per packet and 10 MB per file.
- **Python version:** developed on Python 3.12. Python 3.11 is expected to work but I didn't test it.

## Repository layout

```
app/        main.py (routes) · pipeline.py · ingest.py · schedule.py · extraction.py · llm.py
            normalize.py · reconcile.py · rules.py · narrative.py · models.py
static/     index.html (single page, no build step)
tests/      pytest suite + fake_llm.py (test double) + pdfgen.py (builds test PDFs)
sample_data/            copy of the three supplied sample packets
candidate_materials/    the assignment materials as supplied
DEMO_SCRIPT.md          5–10 minute demo-video script
```

No secrets are in the repository. `.env` is git-ignored, and `.env.example` holds placeholders only.
