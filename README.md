# Underwriter Submission Review Assistant

Knight Insurance take-home: AI Solutions Developer. All data is fictional.

A local web app that reads one commercial auto submission packet (broker email, application PDF, vehicle schedule CSV, optional loss runs PDF). It extracts the business fields with source evidence, runs the five supplied rules (R1–R5) in plain code, and shows an underwriter summary plus an editable draft email to the broker for missing, conflicting or flagged information. The email is never sent.

> The status is readiness for human review only. It is not an approval, decline, quote or coverage decision.

## Setup and run

Requires Python 3.11+ (developed and tested on Python 3.12, Windows).

```bash
git clone https://github.com/shreevershith/knight-insurance-take-home.git
cd knight-insurance-take-home
python -m venv .venv
```

Activate the venv: `.venv\Scripts\Activate.ps1` (PowerShell), `source .venv/Scripts/activate` (Git Bash) or `source .venv/bin/activate` (macOS/Linux). Then:

```bash
pip install -r requirements.txt
cp .env.example .env            # PowerShell: Copy-Item .env.example .env
# edit .env and set LLM_API_KEY
uvicorn app.main:app --port 8000
```

Open http://localhost:8000, drop in the files from one folder in `sample_data/` (e.g. `sample_data/SUB-C/`), or paste a broker email, and click **Process submission**.

Tests (no API key or network needed):

```bash
python -m pytest -q
```

## Model / provider

- **Groq**, model `openai/gpt-oss-120b`, for extraction and for the summary and email. Get a free key at https://console.groq.com/keys and set it in `.env`. (Groq has retired `llama-3.3-70b-versatile`, the model first planned.)
- Configuration is through env only: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS` (see `.env.example`). The key is never logged or shown.
- **Ollama (local alternative):** set `LLM_BASE_URL=http://localhost:11434/v1` and `LLM_MODEL` to a local model (e.g. `llama3.1`), and leave the key empty. Not tested on Ollama.
- **Data handling:** Groq is hosted, so document text is sent to Groq for extraction. The summary call receives only the structured results, never the documents. Use Ollama to keep everything on the machine.

## AI coding tools used

- **Claude Code** (Anthropic): implemented the code, tests and this README from my written specification, phase by phase. I reviewed each phase and made the design decisions.
- **Google Stitch**: a visual mockup of the review page. Only visual ideas were adopted; no Stitch code was used.

## Architecture

```
browser (static/index.html, vanilla JS)      stateless: the browser holds the result
   │  /api/process  /api/override  /api/rerun  /api/narrative  /api/config
   ▼
FastAPI (app/main.py) → pipeline.py
   ingest.py        read files, detect document type from the heading, attachment inventory   [code]
   schedule.py      schedule_vehicle_count from the CSV                                         [code]
   extraction.py    one model call per document → raw values + quoted lines                    [model]
                    verify: the quoted line and the value must be in the source; locator computed [code]
   normalize.py     dates, states, counts, radius, Yes/No                                       [code]
   reconcile.py     merge sources → KNOWN / MISSING / CONFLICT / INVALID / NOT_EXTRACTED        [code]
   rules.py         R1–R5 and overall status (pure functions)                                   [code]
   narrative.py     issue list                                                                  [code]
                    snapshot, issue sentences, broker email from the structured result          [model]
                    validate → one retry → labelled template fallback                           [code]
   llm.py           OpenAI-compatible client: JSON mode, temperature 0, timeout, one retry, typed errors
```

The model reads documents and writes prose. Code decides every value, state, rule result and issue.

## Design decisions

- **Evidence is verified in code.** A value is kept only if its quoted line and the value itself are found in the source text. Page and line numbers are computed, not taken from the model. Anything that can't be found is discarded with a visible warning.
- **Conflicts are never resolved silently.** Two different values give CONFLICT with no value, keeping both alternatives and their evidence, until a reviewer corrects it. "Not provided" in one source next to a value in another is not a conflict. Harmless differences are normalized first (150 = 150.0, CA = California).
- **NOT_EXTRACTED.** If a model call fails, a field with no value is NOT_EXTRACTED rather than MISSING, because absence was never checked. A value found only in the sources that worked is marked "not cross-checked", and the rules treat it as UNKNOWN, so a failed call can't hide a conflict.
- **Rules are pure code**, exactly as in `rules.json`. R1 FLAG for a missing value takes precedence; R2–R4 return UNKNOWN for unresolved values before any threshold or Yes/No test.
- **Corrections** are validated by the same normalizer, labelled HUMAN OVERRIDE, and keep the original value and evidence. **Rerun checks** recalculates the rules with no model call; the summary is then marked stale until regenerated.
- **Stateless server.** No session or database; each request carries its own data, so one packet can't leak into another.
- **Prompt injection.** Document text is wrapped in random markers and marked untrusted, the summary step never sees documents, model output must still pass evidence and narrative checks, and the page renders document text as plain text only.
- **Narrative checks.** One sentence per issue, naming the field and quoting its values; the email asks for every issue, one per line; no decision words (approve, decline, recommend, risk, premium, price, quote, bind, eligible, coverage, accept, reject); no status that contradicts the rules. On failure: one retry, then a template labelled "not AI-generated".
- **Loss runs** count only when a readable document's heading says loss runs or loss history; a zero-claims report counts, an email promise does not. An unreadable or unidentifiable PDF makes R5 UNKNOWN.

Notes on the materials: "eight business fields" is read as the 7 text fields plus `loss_runs_present`, with `schedule_vehicle_count` as the derived count. No other inconsistencies found.

## Tests

### Unit tests (no model)

```bash
python -m pytest -q     # 193 passed: 109 test functions, several run over lists of inputs
```

No test calls a live model. A fake model (`tests/fake_llm.py`) answers from the text it is given, so nothing is hard-coded per sample. Coverage includes: R1–R5 edge cases (missing beats conflict, 150 / 150.0 / 150.1, 0 = 0, conflicts before thresholds, email promise vs report), normalization and CSV handling, conflict and missing semantics, discarding a made-up value, model failures and retries, narrative checks, corrections and rerun, packet isolation, and SUB-A/B/C end to end.

Live results on the supplied samples (Groq `openai/gpt-oss-120b`), matching the expected outcomes:

| Sample | R1 | R2 | R3 | R4 | R5 | Overall |
|---|---|---|---|---|---|---|
| SUB-A | PASS | PASS (3 = 3) | PASS (150) | PASS | PASS | READY_FOR_REVIEW |
| SUB-B | FLAG (no date) | PASS (2 = 2) | UNKNOWN (missing) | UNKNOWN (missing) | FLAG (promise only) | NEEDS_REVIEW |
| SUB-C | PASS | FLAG (4 vs 3) | UNKNOWN (180 vs 80) | UNKNOWN (Yes vs No) | FLAG | NEEDS_REVIEW |

### Live checks with the real model (17 packets)

```bash
python scripts/live_check.py     # needs LLM_API_KEY; prints one line per packet and a 17/17 tally
```

This runs the three supplied samples plus 14 packets of my own in `sample_data/extra/`, each with an `expected.json` worked out from `rules.json` beforehand. T1–T8 are short broker emails across different states and outcomes (the 150 / 150.1 boundary, prose with "three trucks", an impossible date and a radius in km, a non-US state, a correction later in the email, a broker asking for approval, email only). X1–X6 are harder packets (a prose email with values on PDF page 2, format variants, invalid values, a prompt-injection email, a conflict within one email, zero vehicles). All 17 match, and no summary or email contains decision words. `python scripts/make_extra_samples.py` rebuilds the packets.

## Time spent

About 6¾ hours on Saturday, October 17, 2026 (first to last commit), plus reading the materials and recording the video.

## Known limitations

- Ollama is supported through env but was not tested.
- Evidence matching is line by line: a value split across two PDF lines, or rewritten by the model (e.g. "CA" for "California"), is discarded with a warning rather than matched.
- "Not cross-checked" applies when a whole model call fails, not per field.
- Business names, and operations descriptions that differ by more than small words, show as conflicts; there is no meaning-based matching.
- The summary paragraph is checked for forbidden words and status, not fact by fact.
- Out of scope: OCR / scanned PDFs, bounding-box highlighting, mailbox, authentication, storage, deployment.
- Results are not saved; reloading or New clears the review.
