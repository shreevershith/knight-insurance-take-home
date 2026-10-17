# Demo video script (target about 8 minutes)

The brief requires the video to show: **upload → extraction with evidence → rule results → a correction followed by rerunning checks → switching to another submission.** Every one of these is covered below, in that order.

**Before recording**
- Have the server running (`uvicorn app.main:app --port 8000`) and http://localhost:8000 open, starting on the empty screen.
- Have a file explorer open on `sample_data/`.
- **Never open `.env` on screen**, because it holds your API key. Show `.env.example` instead.
- Close any other tabs or notifications that might show personal data.

---

### 0:00–0:45 · Intro and architecture
- *"This is an underwriter submission review assistant for the Knight Insurance exercise. It reads one broker packet, extracts the fields with source evidence, runs the five supplied rules in plain code, and drafts a summary and a follow-up email."*
- Show the architecture diagram in the README. Say the key line: **"The model reads documents and writes prose. Code decides every value, state and rule result."**
- Mention the model: Groq `openai/gpt-oss-120b`, chosen through env, with Ollama as the local alternative. Show `.env.example`.

### 0:45–2:45 · Upload and extraction with evidence (SUB-C, the richest sample)
1. Drag the four files from `sample_data/SUB-C/` into the drop zone. Point out that the type comes from the content heading, not the filename. Click **Process submission** and point at the processing state.
2. **Status header:** "Needs review" for Metro Route Example LLC, 1 PASS · 2 FLAG · 2 UNKNOWN, the disclaimer, and the per-call status line (each extraction call ok, summary from the model, model name).
3. **Action items** (the badge in the section nav shows 4): the code-built list of what to resolve. Each item is grouped as Conflicting or Flagged, shows its values and sources, and says which rule it affects. Say: *"This is what an underwriter acts on first."*
4. Click **Review** on the radius item. It jumps to the field with the correction box open. Then scroll through **Fields & evidence**:
   - *Business name*: two evidence items, `application.pdf · PDF page 1` and `broker_email.txt · email body, line 8`, each showing the real source line.
   - *Garaging state*: the email says "CA" and the PDF says "California", and both normalize to CA, so it is KNOWN.
   - *Operating radius*: **CONFLICT**, with 80 miles (PDF) and 180 miles (email) side by side, each with its evidence. Say: *"The app never picks a source. The value stays null until a reviewer resolves it."*
   - *Hazardous materials*: the same pattern, No vs Yes.
   - *Schedule vehicle count*: 3, derived by code from `CSV data rows 1-3 (header excluded)`.
5. Say: *"Every excerpt is checked in code. The quoted line and the value must actually be in the file, and the page or line number is computed, not taken from the model. A made-up value is thrown out with a warning."*

### 2:45–3:45 · Rule results
- **Rule checks:**
  - R1 PASS.
  - R2 **FLAG**, declared 4 vs 3 schedule rows.
  - R3 **UNKNOWN**: the conflict is checked before the 150-mile threshold.
  - R4 **UNKNOWN**: the Yes/No answers conflict.
  - R5 **FLAG**: the email says loss runs will come later, but a promise isn't an attachment.
- Show the *Inputs used* column (field, value, state).
- **Underwriter summary:** it's labelled AI-GENERATED. Issues are grouped Conflicting / Flagged, both values are quoted, and nothing is decided.
- **Documents received:** three files, detected types, readable, pages and rows. No loss runs report among them.
- **Draft broker email:** labelled "DRAFT ONLY — NOT SENT", editable. Make a small edit, then click **Copy email**.

### 3:45–5:15 · Correction, then rerun checks
1. In the open correction box on *Operating radius* (or click **Correct**), type `far`, then **Save**. The value is rejected with a clear message from the same normalizer.
2. Type `80` and **Save**. Point out the **HUMAN OVERRIDE** badge, *"Original extraction: CONFLICT"*, and both original alternatives still shown with their evidence.
3. On *Hazardous materials*, click **Correct**, enter `No`, then **Save**.
4. Point at "Corrections pending" and click **Rerun checks**. The page returns to Action items: the counts become 3 PASS · 2 FLAG · 0 UNKNOWN, and only the count mismatch and loss runs remain. In Rule checks, R3 and R4 are **PASS** with the override flag in *Inputs used*. Say: *"Rerun is deterministic. No model call happens."*
5. The summary is now marked **STALE**. Click **Regenerate**: the issue list drops radius and hazmat and lists the overrides. Overall stays NEEDS_REVIEW because of R2 and R5.
6. Optional: click **Revert** on hazardous materials, rerun, and show R4 back to UNKNOWN.

### 5:15–6:30 · Switching to another submission (SUB-B), then SUB-A
1. Click **New**. Everything clears, with no Metro Route data left anywhere.
2. Upload `sample_data/SUB-B/`. Point out:
   - R1 **FLAG** (no effective date).
   - R2 PASS (2 = 2).
   - R3 and R4 **UNKNOWN** (missing).
   - R5 **FLAG**.
3. Open *Requested effective date*: **MISSING**, with the evidence showing the "Not provided" lines from both files and the sources inspected. Say: *"Missing is never treated as a conflict, and absence is never treated as No."*
4. Show the email: it asks for exactly the three missing values and the loss runs report.
5. Click **New**, then upload `sample_data/SUB-A/`. **READY_FOR_REVIEW**, all PASS: the radius is exactly 150, which passes (the flag is for more than 150), and `loss_runs.pdf` was identified by its heading. A zero-claims report still counts. The draft card says no follow-up is needed.

### 6:30–7:15 · Failure handling (optional but strong)
- In a terminal, restart with a bad model name:
  - PowerShell: `$env:LLM_MODEL="does-not-exist"; uvicorn app.main:app --port 8000`
  - Git Bash: `LLM_MODEL=does-not-exist uvicorn app.main:app --port 8000`
- Process SUB-C. Show:
  - The red **"Model extraction failed"** panel with the provider's reason.
  - The fields are **NOT_EXTRACTED**, which is different from missing.
  - The schedule count, loss runs result and inventory are still there.
  - The summary is labelled **"TEMPLATE · NOT AI-GENERATED"**.
- Say: *"The app never presents template text as model output."* Restart normally afterwards.

### 7:15–8:00 · Tests and wrap-up
- In a terminal: `python -m pytest -q`, which shows **193 passed** with no API key and no network. Mention the fake LLM, which parses whatever text it is given rather than returning stored answers.
- Briefly list the limitations from the README:
  - Evidence matching is line-based.
  - Ollama hasn't been run.
  - Free-text fields worded differently show as conflicts.
  - No OCR.
- Close with: *"Readiness for human review only. It is not an approval, decline, quote or coverage decision."*
