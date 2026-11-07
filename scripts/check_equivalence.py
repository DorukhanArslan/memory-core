"""Compare Python with pinned OpenClaw source; full acceptance is the default."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from equivalence.harness import run_suite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True,
                        help="Unmodified Git checkout at the exact pinned OpenClaw commit.")
    parser.add_argument("--node", type=Path, required=True, help="Supported Node executable.")
    parser.add_argument("--smoke", action="store_true",
                        help="Compare registered cases only; does not establish full equivalence.")
    parser.add_argument("--report", type=Path, required=True, help="Retain every mismatch and coverage gap as JSON.")
    args = parser.parse_args()
    report, code = run_suite(checkout=args.reference.resolve(), node=args.node.resolve(), smoke=args.smoke)
    try:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError):
        print("Equivalence report could not be retained.", file=sys.stderr)
        return 2
    print(json.dumps({"mode": report["mode"], "status": report["status"],
                      "summary": report.get("summary", {}), "errors": report["errors"],
                      "fullScopePassed": report["fullScopePassed"], "report": str(args.report)}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
