"""Protected SDK host/actor JSON protocol for frozen forget/index-fence inputs."""
import json
import os
import sys
import traceback

from equivalence.forget_index_fence_sdk import (
    run_forget_index_fence_sdk_actor,
    run_forget_index_fence_sdk_host,
)


def main():
    try:
        request = json.loads(sys.stdin.readline())
        if request.get("mode") == "actor":
            run_forget_index_fence_sdk_actor(request)
            return
        output = run_forget_index_fence_sdk_host(request)
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
