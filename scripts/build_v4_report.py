#!/usr/bin/env python
"""Assemble reports/erdos-v4-report.html from reports/v4_report_src/* and the extracted data JSON.

Usage: python scripts/build_v4_report.py <report_data.json> [out.html]

The page is static: narrative HTML parts (00_*.html .. 50_*.html, concatenated in
name order) plus one inline script (60_*.js .. 62_*.js) that renders tables and
Chart.js figures from the embedded JSON. No computation happens here; the data
comes from scripts/extract_v4_report_data.py run on qz.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "reports", "v4_report_src")


def main() -> int:
    data_path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(REPO_ROOT, "reports", "erdos-v4-report.html")
    data = json.load(open(data_path, encoding="utf-8"))
    data["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # the prompts are long and not shown; keep the page small
    for n in data.get("nodes", []):
        n.pop("llm_input", None)
        n.pop("llm_output", None)

    html = "".join(open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(SRC, "*.html"))))
    js = "\n".join(open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(SRC, "*.js"))))
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    blob = blob.replace("</", "<\\/")  # a reflection text must not close the <script> element
    if "__REPORT_DATA__" not in html or "__REPORT_APP__" not in html:
        raise SystemExit("template placeholders missing")
    html = html.replace("__REPORT_DATA__", blob).replace("__REPORT_APP__", js)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print(f"wrote {out}: {len(html) / 1e6:.2f} MB, {len(data.get('nodes', []))} nodes, "
          f"{len(data.get('timeline', [])) - 1} breakthroughs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
