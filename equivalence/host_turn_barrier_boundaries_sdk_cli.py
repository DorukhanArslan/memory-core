"""Actual SDK process for the closed host next-turn boundary family."""
import json
import os
import sys
import traceback

from equivalence.host_turn_barrier_boundaries_sdk import run_host_turn_barrier_boundaries_sdk_host


def main():
    try:
        output = run_host_turn_barrier_boundaries_sdk_host(json.load(sys.stdin))
    except Exception as error:
        json.dump({"fatal": {"name": type(error).__name__, "message": str(error),
            "traceback": "".join(traceback.format_exception(error))}, "pid": os.getpid()},
            sys.stdout, ensure_ascii=False, allow_nan=False)
        sys.stdout.write("\n")
        raise
    json.dump(output, sys.stdout, ensure_ascii=False, allow_nan=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
