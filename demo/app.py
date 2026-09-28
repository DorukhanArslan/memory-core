"""memory-core Lab: app factory and the shell route (demo-only).

The Lab UI is one Jinja shell plus ES modules under ``demo/static/lab/``; it
talks only to ``/api/lab/*`` (:mod:`demo.lab_api`) and the kept ``/api/*``
endpoints (:mod:`demo.lab_kept_api`). All state lives in one
:class:`~demo.lab_runtime.LabRuntime` whose workspaces sit in the system temp
directory (``memory-core-lab-workspace`` and ``memory-core-live-task-demo-workspace``),
never in the repo tree.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from starlette.responses import Response

from demo import LAB_TITLE
from demo.lab_api import build_router
from demo.lab_kept_api import build_kept_router
from demo.lab_runtime import LabError, LabRuntime, safe_exception_message
from memory_core.project_name import (
    DISPLAY_NAME,
    DIST_NAME,
    ENV_PREFIX,
    PACKAGE_NAME,
    STATE_DIRNAME,
)

DEMO_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = DEMO_ROOT.parent
# The name forms the shell page hands the Lab's scripts (data-* attributes of <body>), so the
# UI spells the project name only through them.
SHELL_CONTEXT = {
    "lab_title": LAB_TITLE,
    "project": {
        "name": DIST_NAME,
        "display": DISPLAY_NAME,
        "package": PACKAGE_NAME,
        "state_dir": STATE_DIRNAME,
        "env_prefix": ENV_PREFIX,
    },
}

# DESIGN §8.2: model and file text never reach innerHTML, and the shell loads
# only same-origin scripts and styles.
SHELL_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


class RevalidatedStaticFiles(StaticFiles):
    """Static files the browser must revalidate, so a rebuilt Lab never runs stale CSS or JS."""

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def load_env_defaults(path: Path = PROJECT_ROOT / ".env") -> None:
    """Load ``NAME=value`` lines into ``os.environ``; names already set win."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def create_app(lab: LabRuntime | None = None) -> FastAPI:
    lab = lab if lab is not None else LabRuntime()
    app = FastAPI(title=LAB_TITLE)
    app.state.lab = lab
    app.mount("/static", RevalidatedStaticFiles(directory=DEMO_ROOT / "static"), name="static")
    templates = Jinja2Templates(directory=DEMO_ROOT / "templates")

    @app.exception_handler(LabError)
    async def lab_error_handler(request: Request, exc: LabError):
        del request
        return JSONResponse(exc.payload(), status_code=exc.status)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        del request
        return JSONResponse(
            {
                "error": safe_exception_message(exc, lab.secret_values(None)),
                "code": "internal_error",
                "redacted": True,
            },
            status_code=500,
        )

    @app.get("/", response_class=HTMLResponse)
    def shell(request: Request):
        response = templates.TemplateResponse(request, "index.html", SHELL_CONTEXT)
        response.headers["Content-Security-Policy"] = SHELL_CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-cache"
        return response

    app.include_router(build_router(lab))
    app.include_router(build_kept_router(lab))
    return app


load_env_defaults()
app = create_app()
