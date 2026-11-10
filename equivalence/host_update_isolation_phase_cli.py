"""Private SDK child entry point for the real host update/isolation experiment."""
from __future__ import annotations

import json
import os
import sys
import traceback

from equivalence.host_update_isolation_sdk import run_host_update_isolation_phase


def main():
    try:
        output = run_host_update_isolation_phase(json.load(sys.stdin))
    except Exception as error:
        json.dump({"fatal": {"name": type(error).__name__, "message": str(error),
                   "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))},
                   "pid": os.getpid()}, sys.stdout, ensure_ascii=False, allow_nan=False)
        sys.stdout.write("\n")
        raise
    json.dump(output, sys.stdout, ensure_ascii=False, allow_nan=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
