"""Protected SDK process for one exact frozen query-sync boundary input."""
import json
import os
import sys
import traceback

from equivalence.query_sync_boundaries_sdk import run_query_sync_boundaries_sdk_host


def main():
    try:
        output = run_query_sync_boundaries_sdk_host(json.load(sys.stdin))
    except BaseException as error:
        json.dump({"fatal": {"name": type(error).__name__, "message": str(error),
            "traceback": "".join(traceback.format_exception(error))}, "pid": os.getpid()},
            sys.stdout, ensure_ascii=False, allow_nan=False)
        sys.stdout.write("\n")
        raise
    json.dump(output, sys.stdout, ensure_ascii=False, allow_nan=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
