"""Live check: run packets through the real pipeline (model from .env) and compare R1-R5 with expected.json.

Usage: python scripts/live_check.py [sample_data/extra] [packet names...]
Calls the configured model for real, so it needs LLM_API_KEY; the pytest suite never does.
"""
import json
import pathlib
import sys
import time

from dotenv import load_dotenv

load_dotenv(".env")
sys.path.insert(0, ".")
from app.ingest import ingest_packet  # noqa: E402
from app.llm import client_from_env  # noqa: E402
from app.narrative import BANNED_RE  # noqa: E402
from app.pipeline import process_packet  # noqa: E402

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "sample_data/extra")
only = sys.argv[2:] or None
llm = client_from_env()
summary = []
for d in sorted(p for p in root.iterdir() if p.is_dir()):
    if only and d.name not in only:
        continue
    exp = json.loads((d / "expected.json").read_text())["rules"]
    files = [(p.name, p.read_bytes()) for p in sorted(d.iterdir()) if p.name != "expected.json"]
    t = time.time()
    r = process_packet(ingest_packet(files), llm)
    got = [x.status.value for x in r.rules]
    ok = got == exp
    summary.append((d.name, ok))
    print(f"\n===== {d.name}  {time.time()-t:.1f}s  {r.overall_status.value}  MATCH={ok}")
    for x, e in zip(r.rules, exp):
        flag = "" if x.status.value == e else f"   <-- expected {e}"
        print(f"  {x.id} {x.status.value:7} {x.reason}{flag}")
    for k, f in r.fields.items():
        v = f.display if f.state.value == "KNOWN" else " vs ".join(f"{a.display}{'' if a.valid else '(invalid)'}" for a in f.alternatives) or "-"
        ev = " | ".join(f"{e.source_file}@{e.locator}" for e in f.evidence[:3])
        cc = "" if f.cross_checked else " [not cross-checked]"
        print(f"  {k:25} {f.state.value:13} {v[:44]:44} {ev[:90]}{cc}")
    print("  inventory:", [(a.filename, a.detected_type, a.readable) for a in r.inventory])
    print("  extraction:", [(x.source_file, x.status, x.mentions_kept, x.mentions_discarded, x.message) for x in r.extraction])
    for w in r.warnings:
        print("  WARN:", w)
    n = r.narrative
    print("  narrative:", n.source, n.error or "", n.validation_errors)
    text = " ".join([n.snapshot, *[l for g in n.issue_groups for l in g.lines], n.email_subject, n.email_body])
    bad = sorted({m.group(0).lower() for m in BANNED_RE.finditer(text)})
    print("  snapshot:", n.snapshot)
    if bad:
        print("  !! banned words in shown text:", bad)
    time.sleep(2)
print("\nSUMMARY:", ", ".join(f"{n}={'ok' if ok else 'MISMATCH'}" for n, ok in summary))
