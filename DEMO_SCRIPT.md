# Demo video script (target about 8 minutes)

The brief requires the video to show: **upload → extraction with evidence → rule results → a correction followed by rerunning checks → switching to another submission.** Every one of these is covered below, in that order.

**Before recording**
- Start the server from the project folder with `.venv/Scripts/python -m uvicorn app.main:app --port 8000` and open http://localhost:8000. Start on the empty screen.
- Have a file explorer open on `sample_data/`.
- **Never open `.env` on screen**, because it holds your API key. Show `.env.example` instead.
- Close other tabs and notifications that might show personal data.

---

### 0:00–0:45 · Intro and architecture
- *"This is an underwriter submission review assistant for the Knight Insurance exercise. It reads one broker packet, extracts the fields with the source line for each value, runs the five supplied rules in plain code, and drafts a summary and a follow-up email."*
- Show the architecture diagram in the README. Say the key line: **"The model reads documents and writes prose. Code decides every value, state and rule result."**
- Point at the model in the top bar: Groq `openai/gpt-oss-120b`, set only through env, with Ollama as the local alternative. Show `.env.example`.
- Say it plainly: *"I used Claude Code to implement this from my written spec, phase by phase. I reviewed each phase, made the design decisions, and tested it with my own harder packets."*

### 0:45–2:45 · Upload and extraction with evidence (SUB-C)
1. Drag the **three** files from `sample_data/SUB-C/` (application.pdf, broker_email.txt, vehicles.csv) into the drop zone. Click **Process submission**.
2. While it runs, point at the processing view: the six steps in order, each marked **Code** or **Model**, and the timer. Say: *"Only extraction and the write-up use the model; everything else is code."*
3. **Status header:** "Needs review" for Metro Route Example LLC, with three cells: 1 passed (R1), 2 flagged (R2 vehicle count, R5 loss runs), 2 unresolved (R3 radius, R4 hazardous materials).
4. **Action items** (4): what the underwriter acts on first. Two are Conflicting (radius, hazmat) and two are Flagged (loss runs, vehicle count), each with its values, sources and the rule it affects.
5. Click **Review** on the radius item. It jumps to the field with the correction box open. Leave it open for now and scroll through **Fields & evidence**:
   - *Business name*: two evidence lines, `application.pdf · PDF page 1` and `broker_email.txt · email body, line 8`, each showing the real source line.
   - *Garaging state*: the email says "CA" and the PDF says "California". Both normalize to CA, so it's Known, not a conflict.
   - *Operating radius*: **Conflict**, with **Source A · application.pdf · 80 miles** and **Source B · broker_email.txt · 180 miles** side by side. Say: *"The app never picks a source. The value stays unresolved until a reviewer decides."*
   - *Hazardous materials*: the same pattern, No vs Yes.
   - *Schedule vehicle count*: 3, counted by code from `CSV data rows 1-3 (header excluded)`.
6. Say: *"Every excerpt is checked in code. The quoted line and the value must actually be in the file, and the page or line number is computed, not taken from the model. A made-up value is thrown out with a warning."* Also say: *"Document types come from each file's heading, not its name."*

### 2:45–3:45 · Rule results, summary, documents, email
- **Rule checks:**
  - R1 PASS.
  - R2 **FLAG**: declared 4 vs 3 rows in the schedule.
  - R3 **UNKNOWN**: the conflict is checked before the 150-mile threshold, so 180 doesn't flag.
  - R4 **UNKNOWN**: the Yes/No answers conflict.
  - R5 **FLAG**: the email says loss runs will come later, but a promise isn't an attachment.
  - Point at the inputs line under each rule (field = value · state).
- **Underwriter summary:** labelled AI-generated. One paragraph about the applicant, then boxed Conflicting and Flagged groups. Both values are quoted and nothing is decided.
- **Documents received:** three files with their detected types, all readable. No loss runs report among them.
- **Draft broker email:** labelled "Draft only — not sent". Point out one numbered request per line. Make a small edit, then click **Copy email**. Say: *"Nothing is sent. The underwriter copies it into their own mail client, as the brief requires."*

### 3:45–5:15 · Correction, then rerun checks
1. In the radius correction box, type `far` and **Save**. It's rejected with a clear message from the same normalizer.
2. Type `80` and **Save**. Point out the purple **Human override** tag, *"Original extraction: Conflict"*, and both source cards still shown below.
3. On *Hazardous materials*, click **Correct**, enter `No`, **Save**.
4. Point at "Corrections pending" and click **Rerun checks**. The page goes back to Action items: the cells become 3 passed / 2 flagged / 0 unresolved, and only the vehicle count and loss runs remain. In Rule checks, R3 and R4 are **PASS**, with the inputs marked as overridden. Say: *"Rerun is pure code. No model call happens."*
5. The summary now shows **Stale**. Click **Regenerate**: radius and hazmat drop out, and an **Overrides applied** box lists both corrections. Overall stays Needs review because of R2 and R5.
6. Optional: click **Revert** on hazardous materials, rerun, and show R4 back to Unknown.

### 5:15–6:30 · Switching to another submission (SUB-B), then SUB-A
1. Click **New**. Everything clears, with no Metro Route data left anywhere.
2. Upload the three files from `sample_data/SUB-B/`:
   - R1 **FLAG** (no effective date).
   - R2 PASS (2 = 2).
   - R3 and R4 **UNKNOWN** (missing).
   - R5 **FLAG**.
3. Open *Requested effective date*: **Missing**, with the "Not provided" lines from both files as evidence. Say: *"Missing is never treated as a conflict, and absence is never treated as No."*
4. Show the email: it asks for exactly the three missing values and the loss runs report, one per line.
5. Click **New**, then upload the four files from `sample_data/SUB-A/`. **Ready for review**, all five passed. The radius is exactly 150, which passes (the rule flags only above 150), and `loss_runs.pdf` was recognised from its heading. A zero-claims report still counts. The email section says no follow-up is needed.

### 6:30–7:15 · Failure handling (optional but strong)
- Stop the server (Ctrl+C) and restart it with a model name that doesn't exist:
  - PowerShell: `$env:LLM_MODEL="does-not-exist"; .venv/Scripts/python -m uvicorn app.main:app --port 8000`
  - Git Bash: `LLM_MODEL=does-not-exist .venv/Scripts/python -m uvicorn app.main:app --port 8000`
- Process SUB-C. Show:
  - The red **"Model extraction failed"** panel with the provider's reason ("The model … does not exist").
  - The fields are **Not extracted**, which is different from missing.
  - The schedule count, loss runs result and documents are still evaluated.
  - The summary is labelled **"Template · not AI-generated"**.
- Say: *"The app never presents template text as model output."* Then restart normally (close the terminal, or run `Remove-Item Env:LLM_MODEL` in PowerShell).

### 7:15–8:30 · Tests, harder data, wrap-up
- In a terminal: `.venv/Scripts/python -m pytest -q`, which shows **193 passed** in a few seconds with no API key and no network. Say: *"That's 109 test functions. Many run against a list of inputs, like every date format, so pytest counts 193. They use a fake model that parses whatever text it's given; nothing is hard-coded per sample."*
- Optional (about 30 seconds): upload `sample_data/extra/X4-injection/`. The email tells "the AI" to report No and 50 miles and to say "approved". Show the real values (Yes, 200 miles), R3 and R4 FLAG, and no "approved" anywhere. Mention the six extra packets in `sample_data/extra/` and `scripts/live_check.py`, which runs them against the real model.
- Briefly list the limitations from the README:
  - Evidence matching is line-based.
  - Ollama hasn't been run.
  - Business names and operations worded very differently show as conflicts.
  - No OCR.
- Close with: *"This is readiness for human review only. It is not an approval, decline, quote or coverage decision."*
