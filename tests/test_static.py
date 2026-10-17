"""The single page must at least parse: a JS syntax error silently disables every button."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parent.parent / "static" / "index.html"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_page_script_parses():
    html = PAGE.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert scripts, "no inline script found"
    check = "try { new Function(require('fs').readFileSync(0, 'utf8')); } catch (e) { console.error(e.message); process.exit(1); }"
    proc = subprocess.run(["node", "-e", check], input=scripts[-1], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, "static/index.html script has a syntax error: " + proc.stderr
