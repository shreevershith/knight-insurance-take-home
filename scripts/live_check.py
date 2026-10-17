"""Live check: run packets through the real pipeline (model from .env) and compare R1-R5 with the expected results.

Runs the three supplied samples (expected results from the assignment) and every packet in
sample_data/extra/ (each with its own expected.json). Calls the configured model for real, so it
needs LLM_API_KEY; the pytest suite never does.

Usage:
  python scripts/live_check.py                # all 17
  python scripts/live_check.py SUB-C X4-injection   # only the named packets
  python scripts/live_check.py -v             # also print fields and evidence for every packet
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

# Expected R1-R5 for the supplied samples (assignment section on expected results).
SUPPLIED = {
    "SUB-A": ["PASS", "PASS", "PASS", "PASS", "PASS"],
    "SUB-B": ["FLAG", "PASS", "UNKNOWN", "UNKNOWN", "FLAG"],
    "SUB-C": ["PASS", "FLAG", "UNKNOWN", "UNKNOWN", "FLAG"],
}

args = [a for a in sys.argv[1:] if a != "-v"]
verbose = "-v" in sys.argv
packets = [(pathlib.Path("sample_data") / n, exp) for n, exp in SUPPLIED.items()]
packets += [(d, json.loads((d / "expected.json").read_text())["rules"])
            for d in sorted(pathlib.Path("sample_data/extra").iterdir()) if d.is_dir()]
if args:
    packets = [(d, e) for d, e in packets if d.name in args]

llm = client_from_env()
print(f"Model: {llm.provider} · {llm.model}\n")
passed = 0
for d, exp in packets:
    files = [(p.name, p.read_bytes()) for p in sorted(d.iterdir()) if p.is_file() and p.name != "expected.json"]
    t = time.time()
    r = process_packet(ingest_packet(files), llm)
    got = [x.status.value for x in r.rules]
    n = r.narrative
    shown = " ".join([n.snapshot, *[l for g in n.issue_groups for l in g.lines], n.email_subject, n.email_body])
    banned = sorted({m.group(0).lower() for m in BANNED_RE.finditer(shown)})
    ok = got == exp and not banned
    passed += ok
    print(f"{'PASS' if ok else 'FAIL'}  {d.name:30} {' '.join(got):34} {r.overall_status.value:16} "
          f"summary={n.source:8} {time.time()-t:4.1f}s")
    if not ok or verbose:
        for x, e in zip(r.rules, exp):
            mark = "" if x.status.value == e else f"   <-- expected {e}"
            print(f"      {x.id} {x.status.value:7} {x.reason}{mark}")
        for k, f in r.fields.items():
            v = f.display if f.state.value == "KNOWN" else " vs ".join(a.display for a in f.alternatives) or "-"
            print(f"      {k:25} {f.state.value:13} {v[:40]}")
        for w in r.warnings:
            print("      warning:", w)
        if banned:
            print("      forbidden words in summary/email:", banned)
    time.sleep(1)

print(f"\n{passed}/{len(packets)} packets match their expected R1-R5 results.")
sys.exit(0 if passed == len(packets) else 1)
