# OpenClaw TS Oracle Parity Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an OpenClaw parity mode that runs the Python port and the original OpenClaw TypeScript memory-core functions against identical fixtures and shows step-by-step match/mismatch traces in the demo.

**Architecture:** Python owns fixture setup, Python-port execution, trace diffing, FastAPI endpoints, and UI rendering. A Node/TypeScript oracle runner is invoked through `pnpm exec tsx` inside a pinned OpenClaw checkout and calls the real OpenClaw TS exports. The first implementation compares deterministic memory-core boundaries rather than the full OpenClaw gateway/chat runtime.

**Tech Stack:** Python 3.11, FastAPI, pytest, Node.js, pnpm, tsx, original OpenClaw TypeScript source checkout.

---

## File Map

- Create `demo/openclaw_oracle.py`: resolves OpenClaw checkout metadata, invokes the Node oracle runner, normalizes errors.
- Create `demo/parity_trace.py`: builds paired temporary workspaces, runs Python reference steps, runs TS oracle steps, compares traces.
- Create `scripts/openclaw_oracle_runner.ts`: TypeScript stdin/stdout runner that imports real OpenClaw memory-core functions from a source checkout.
- Modify `demo/app.py`: add a new `/api/parity/trace` endpoint.
- Modify `demo/templates/index.html`: add an OpenClaw Parity tab and render two-column trace rows.
- Modify `tests/demo/test_demo_app.py`: assert UI and endpoint wiring.
- Create `tests/demo/test_openclaw_oracle.py`: unit tests for metadata, subprocess behavior, and structured oracle errors.
- Create `tests/demo/test_parity_trace.py`: unit tests for fixture pairing and mismatch detection.
- Create `tests/integration/test_openclaw_ts_oracle.py`: opt-in integration test that runs only when `OPENCLAW_ORACLE_REPO` points to a prepared OpenClaw checkout.

## Task 1: Oracle Metadata And Subprocess Wrapper

**Files:**
- Create: `demo/openclaw_oracle.py`
- Test: `tests/demo/test_openclaw_oracle.py`

- [ ] **Step 1: Write failing tests for oracle metadata and missing checkout**

Create `tests/demo/test_openclaw_oracle.py`:

```python
from pathlib import Path

from demo.openclaw_oracle import OpenClawOracle, OracleError


def test_oracle_metadata_reports_missing_checkout(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=tmp_path / "missing")

    metadata = oracle.metadata()

    assert metadata["available"] is False
    assert metadata["repoPath"] == str(tmp_path / "missing")
    assert metadata["commit"] is None
    assert metadata["reason"] == "checkout missing"


def test_run_returns_structured_error_when_checkout_missing(tmp_path: Path):
    oracle = OpenClawOracle(repo_path=tmp_path / "missing")

    result = oracle.run({"operation": "deepPolicy"})

    assert result["ok"] is False
    assert result["error"]["code"] == "oracle-unavailable"
    assert "checkout missing" in result["error"]["message"]


def test_oracle_error_is_safe_string():
    err = OracleError("boom")

    assert str(err) == "boom"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/demo/test_openclaw_oracle.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'demo.openclaw_oracle'`.

- [ ] **Step 3: Implement minimal metadata wrapper**

Create `demo/openclaw_oracle.py`:

```python
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_ORACLE_REPO = Path(os.getenv("OPENCLAW_ORACLE_REPO", "/tmp/openclaw-upstream"))
RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "openclaw_oracle_runner.ts"


class OracleError(RuntimeError):
    pass


class OpenClawOracle:
    def __init__(self, repo_path: Path | None = None, timeout_seconds: float = 20.0):
        self.repo_path = repo_path or DEFAULT_ORACLE_REPO
        self.timeout_seconds = timeout_seconds

    def metadata(self) -> dict[str, Any]:
        if not self.repo_path.exists():
            return self._unavailable("checkout missing")
        if not (self.repo_path / ".git").exists():
            return self._unavailable("not a git checkout")
        commit = self._git_commit()
        package_manager = "pnpm" if (self.repo_path / "pnpm-lock.yaml").exists() else "unknown"
        return {
            "available": True,
            "repoPath": str(self.repo_path),
            "commit": commit,
            "packageManager": package_manager,
            "runnerPath": str(RUNNER_PATH),
            "reason": None,
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata = self.metadata()
        if not metadata["available"]:
            return {
                "ok": False,
                "error": {
                    "code": "oracle-unavailable",
                    "message": str(metadata["reason"]),
                },
                "metadata": metadata,
            }
        if not RUNNER_PATH.exists():
            return {
                "ok": False,
                "error": {
                    "code": "oracle-runner-missing",
                    "message": f"runner missing: {RUNNER_PATH}",
                },
                "metadata": metadata,
            }
        return self._run_subprocess(payload, metadata)

    def _run_subprocess(self, payload: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"repoPath": str(self.repo_path), **payload})
        try:
            completed = subprocess.run(
                ["pnpm", "exec", "tsx", str(RUNNER_PATH)],
                input=body,
                text=True,
                capture_output=True,
                cwd=self.repo_path,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            return self._subprocess_error("pnpm-not-found", "pnpm executable not found", metadata)
        except subprocess.TimeoutExpired:
            return self._subprocess_error("oracle-timeout", "oracle runner timed out", metadata)
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "oracle runner failed").strip()
            return self._subprocess_error("oracle-runner-failed", message, metadata)
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return self._subprocess_error(
                "oracle-invalid-json",
                f"oracle returned invalid JSON: {exc.msg}",
                metadata,
            )
        if isinstance(result, dict):
            result.setdefault("metadata", metadata)
            return result
        return self._subprocess_error("oracle-invalid-payload", "oracle result was not an object", metadata)

    def _git_commit(self) -> str | None:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            cwd=self.repo_path,
            check=False,
        )
        if completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

    def _unavailable(self, reason: str) -> dict[str, Any]:
        return {
            "available": False,
            "repoPath": str(self.repo_path),
            "commit": None,
            "packageManager": None,
            "runnerPath": str(RUNNER_PATH),
            "reason": reason,
        }

    @staticmethod
    def _subprocess_error(code: str, message: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return {"ok": False, "error": {"code": code, "message": message}, "metadata": metadata}
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/demo/test_openclaw_oracle.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add demo/openclaw_oracle.py tests/demo/test_openclaw_oracle.py
git commit -m "feat: add openclaw oracle wrapper"
```

## Task 2: TypeScript Oracle Runner

**Files:**
- Create: `scripts/openclaw_oracle_runner.ts`
- Modify: `tests/demo/test_openclaw_oracle.py`
- Test: `tests/integration/test_openclaw_ts_oracle.py`

- [ ] **Step 1: Add unit test that wrapper forwards subprocess output**

Append to `tests/demo/test_openclaw_oracle.py`:

```python
import json
import subprocess


def test_run_returns_runner_json(monkeypatch, tmp_path: Path):
    repo = tmp_path / "openclaw"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pnpm-lock.yaml").write_text("lock", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
        assert cmd[:3] == ["pnpm", "exec", "tsx"]
        assert json.loads(kwargs["input"])["operation"] == "deepPolicy"
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"ok": True, "operation": "deepPolicy", "result": {"minScore": 0.8}}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    oracle = OpenClawOracle(repo_path=repo)

    result = oracle.run({"operation": "deepPolicy"})

    assert result["ok"] is True
    assert result["result"]["minScore"] == 0.8
    assert result["metadata"]["commit"] == "abc123"
```

- [ ] **Step 2: Run unit test to verify it passes with current wrapper**

Run:

```bash
pytest tests/demo/test_openclaw_oracle.py::test_run_returns_runner_json -v
```

Expected: PASS.

- [ ] **Step 3: Write opt-in integration test for real TS deep policy**

Create `tests/integration/test_openclaw_ts_oracle.py`:

```python
import os
from pathlib import Path

import pytest

from demo.openclaw_oracle import OpenClawOracle


pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)


def test_real_openclaw_oracle_deep_policy():
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))

    result = oracle.run({"operation": "deepPolicy", "config": {}})

    assert result["ok"] is True
    assert result["operation"] == "deepPolicy"
    assert result["result"]["minScore"] == 0.8
    assert result["result"]["minRecallCount"] == 3
    assert result["result"]["minUniqueQueries"] == 3
    assert result["result"]["maxAgeDays"] == 30
```

- [ ] **Step 4: Run integration test to verify it fails before runner exists**

Run:

```bash
OPENCLAW_ORACLE_REPO=/tmp/openclaw-upstream pytest tests/integration/test_openclaw_ts_oracle.py -v
```

Expected: FAIL with `oracle-runner-missing` or `oracle-runner-failed`.

- [ ] **Step 5: Implement TypeScript runner**

Create `scripts/openclaw_oracle_runner.ts`:

```typescript
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

type Payload = {
  repoPath: string;
  operation: string;
  workspaceDir?: string;
  nowMs?: number;
  timezone?: string;
  config?: Record<string, unknown>;
  query?: string;
  results?: unknown[];
  candidates?: unknown[];
  keys?: string[];
  phase?: "light" | "rem";
};

async function readStdin(): Promise<Payload> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf-8")) as Payload;
}

async function importFromRepo(repoPath: string, relativePath: string) {
  const fullPath = path.join(repoPath, relativePath);
  return await import(pathToFileURL(fullPath).href);
}

async function snapshotFiles(workspaceDir?: string): Promise<Record<string, string>> {
  if (!workspaceDir) {
    return {};
  }
  const files = [
    "MEMORY.md",
    "DREAMS.md",
    path.join("memory", ".dreams", "short-term-recall.json"),
    path.join("memory", ".dreams", "phase-signals.json"),
  ];
  const out: Record<string, string> = {};
  for (const rel of files) {
    try {
      out[rel.replaceAll("\\", "/")] = await fs.readFile(path.join(workspaceDir, rel), "utf-8");
    } catch {
      out[rel.replaceAll("\\", "/")] = "";
    }
  }
  return out;
}

async function main() {
  const payload = await readStdin();
  const repoPath = payload.repoPath;
  if (!repoPath) {
    throw new Error("repoPath is required");
  }
  const nowMs = Number.isFinite(payload.nowMs) ? Number(payload.nowMs) : Date.now();
  const timezone = payload.timezone || "UTC";

  if (payload.operation === "deepPolicy") {
    const dreaming = await importFromRepo(repoPath, "src/memory-host-sdk/dreaming.ts");
    const resolved = dreaming.resolveMemoryDeepDreamingConfig({
      pluginConfig: payload.config ?? {},
      cfg: payload.config ?? {},
    });
    return {
      ok: true,
      operation: payload.operation,
      result: {
        enabled: resolved.enabled,
        limit: resolved.limit,
        minScore: resolved.minScore,
        minRecallCount: resolved.minRecallCount,
        minUniqueQueries: resolved.minUniqueQueries,
        recencyHalfLifeDays: resolved.recencyHalfLifeDays,
        maxAgeDays: resolved.maxAgeDays,
      },
    };
  }

  const promotion = await importFromRepo(
    repoPath,
    "extensions/memory-core/src/short-term-promotion.ts",
  );

  if (payload.operation === "recordShortTermRecalls") {
    await promotion.recordShortTermRecalls({
      workspaceDir: payload.workspaceDir,
      query: payload.query ?? "",
      results: payload.results ?? [],
      nowMs,
      timezone,
    });
    return {
      ok: true,
      operation: payload.operation,
      files: await snapshotFiles(payload.workspaceDir),
    };
  }

  if (payload.operation === "recordDreamingPhaseSignals") {
    await promotion.recordDreamingPhaseSignals({
      workspaceDir: payload.workspaceDir,
      phase: payload.phase ?? "light",
      keys: payload.keys ?? [],
      nowMs,
    });
    return {
      ok: true,
      operation: payload.operation,
      files: await snapshotFiles(payload.workspaceDir),
    };
  }

  if (payload.operation === "rankShortTermPromotionCandidates") {
    const candidates = await promotion.rankShortTermPromotionCandidates({
      workspaceDir: payload.workspaceDir,
      nowMs,
      limit: 10,
      minScore: 0.75,
      minRecallCount: 3,
      minUniqueQueries: 2,
    });
    return { ok: true, operation: payload.operation, result: { candidates } };
  }

  if (payload.operation === "applyShortTermPromotions") {
    const result = await promotion.applyShortTermPromotions({
      workspaceDir: payload.workspaceDir,
      nowMs,
      timezone,
      candidates: payload.candidates ?? [],
    });
    return {
      ok: true,
      operation: payload.operation,
      result,
      files: await snapshotFiles(payload.workspaceDir),
    };
  }

  throw new Error(`unsupported operation: ${payload.operation}`);
}

main()
  .then((result) => {
    process.stdout.write(JSON.stringify(result));
  })
  .catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    process.stdout.write(JSON.stringify({ ok: false, error: { code: "runner-error", message } }));
    process.exitCode = 1;
  });
```

- [ ] **Step 6: Run integration test**

Run:

```bash
OPENCLAW_ORACLE_REPO=/tmp/openclaw-upstream pytest tests/integration/test_openclaw_ts_oracle.py -v
```

Expected: PASS if `/tmp/openclaw-upstream` has dependencies available. If it fails with missing pnpm deps, run `pnpm install` in the OpenClaw checkout outside this plan, then rerun.

- [ ] **Step 7: Run unit tests**

Run:

```bash
pytest tests/demo/test_openclaw_oracle.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/openclaw_oracle_runner.ts tests/demo/test_openclaw_oracle.py tests/integration/test_openclaw_ts_oracle.py
git commit -m "feat: add openclaw ts oracle runner"
```

## Task 3: Parity Trace Service

**Files:**
- Create: `demo/parity_trace.py`
- Test: `tests/demo/test_parity_trace.py`

- [ ] **Step 1: Write failing tests for deep policy mismatch and trace shape**

Create `tests/demo/test_parity_trace.py`:

```python
from demo.parity_trace import build_deep_policy_trace, diff_values


class FakeOracle:
    def metadata(self):
        return {"available": True, "commit": "abc123", "repoPath": "/repo"}

    def run(self, payload):
        assert payload["operation"] == "deepPolicy"
        return {
            "ok": True,
            "operation": "deepPolicy",
            "result": {
                "minScore": 0.8,
                "minRecallCount": 3,
                "minUniqueQueries": 3,
                "maxAgeDays": 30,
            },
        }


def test_diff_values_reports_mismatch():
    diff = diff_values({"minScore": 0.75}, {"minScore": 0.8})

    assert diff["status"] == "mismatch"
    assert "minScore: python=0.75 openclaw=0.8" in diff["details"]


def test_build_deep_policy_trace_shows_known_default_mismatch():
    trace = build_deep_policy_trace(FakeOracle())

    assert trace["id"] == "deep-policy"
    assert trace["diff"]["status"] == "mismatch"
    assert trace["python"]["values"]["minScore"] == 0.75
    assert trace["openclaw"]["values"]["minScore"] == 0.8
    assert trace["openclaw"]["values"]["minUniqueQueries"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/demo/test_parity_trace.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'demo.parity_trace'`.

- [ ] **Step 3: Implement parity trace helpers**

Create `demo/parity_trace.py`:

```python
from __future__ import annotations

from typing import Any

from demo.openclaw_oracle import OpenClawOracle
from demo.short_term_promotion import (
    DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    DEFAULT_PROMOTION_MIN_SCORE,
    DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
)


def diff_values(python_values: dict[str, Any], openclaw_values: dict[str, Any]) -> dict[str, Any]:
    details: list[str] = []
    for key in sorted(set(python_values) | set(openclaw_values)):
        left = python_values.get(key)
        right = openclaw_values.get(key)
        if left != right:
            details.append(f"{key}: python={left} openclaw={right}")
    return {"status": "match" if not details else "mismatch", "details": details}


def build_deep_policy_trace(oracle: OpenClawOracle | Any | None = None) -> dict[str, Any]:
    oracle = oracle or OpenClawOracle()
    python_values = {
        "minScore": DEFAULT_PROMOTION_MIN_SCORE,
        "minRecallCount": DEFAULT_PROMOTION_MIN_RECALL_COUNT,
        "minUniqueQueries": DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
        "maxAgeDays": None,
    }
    oracle_result = oracle.run({"operation": "deepPolicy", "config": {}})
    if not oracle_result.get("ok"):
        return {
            "id": "deep-policy",
            "label": "Deep dreaming policy values",
            "python": {"decision": "available", "values": python_values, "reasons": []},
            "openclaw": {
                "decision": "error",
                "values": {},
                "reasons": [oracle_result.get("error", {}).get("message", "oracle error")],
            },
            "diff": {"status": "error", "details": [oracle_result.get("error", {})]},
        }
    openclaw_values = {
        "minScore": oracle_result["result"].get("minScore"),
        "minRecallCount": oracle_result["result"].get("minRecallCount"),
        "minUniqueQueries": oracle_result["result"].get("minUniqueQueries"),
        "maxAgeDays": oracle_result["result"].get("maxAgeDays"),
    }
    return {
        "id": "deep-policy",
        "label": "Deep dreaming policy values",
        "condition": "score >= minScore && signals >= minRecallCount && contextDiversity >= minUniqueQueries && ageDays <= maxAgeDays",
        "python": {"decision": "computed", "values": python_values, "reasons": []},
        "openclaw": {"decision": "computed", "values": openclaw_values, "reasons": []},
        "diff": diff_values(python_values, openclaw_values),
    }


def build_parity_trace(oracle: OpenClawOracle | None = None) -> dict[str, Any]:
    oracle = oracle or OpenClawOracle()
    return {
        "oracle": oracle.metadata(),
        "steps": [
            build_deep_policy_trace(oracle),
        ],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/demo/test_parity_trace.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add demo/parity_trace.py tests/demo/test_parity_trace.py
git commit -m "feat: add parity trace service"
```

## Task 4: API Endpoint

**Files:**
- Modify: `demo/app.py`
- Modify: `tests/demo/test_demo_app.py`

- [ ] **Step 1: Write failing endpoint test**

Append to `tests/demo/test_demo_app.py`:

```python
def test_parity_trace_endpoint_returns_steps(monkeypatch):
    monkeypatch.setattr(
        demo_app,
        "build_parity_trace",
        lambda: {
            "oracle": {"available": True, "commit": "abc123"},
            "steps": [
                {
                    "id": "deep-policy",
                    "label": "Deep dreaming policy values",
                    "python": {"decision": "computed", "values": {"minScore": 0.75}, "reasons": []},
                    "openclaw": {"decision": "computed", "values": {"minScore": 0.8}, "reasons": []},
                    "diff": {"status": "mismatch", "details": ["minScore differs"]},
                }
            ],
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.post("/api/parity/trace", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle"]["commit"] == "abc123"
    assert payload["steps"][0]["id"] == "deep-policy"
    assert payload["steps"][0]["diff"]["status"] == "mismatch"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/demo/test_demo_app.py::test_parity_trace_endpoint_returns_steps -v
```

Expected: FAIL with `404 Not Found`.

- [ ] **Step 3: Add endpoint**

Modify imports at the top of `demo/app.py`:

```python
from demo.parity_trace import build_parity_trace
```

Add endpoint near inspector endpoints:

```python
@app.post("/api/parity/trace")
def parity_trace(payload: dict[str, Any] | None = None):
    del payload
    return build_parity_trace()
```

- [ ] **Step 4: Run endpoint test**

Run:

```bash
pytest tests/demo/test_demo_app.py::test_parity_trace_endpoint_returns_steps -v
```

Expected: PASS.

- [ ] **Step 5: Run focused app tests**

Run:

```bash
pytest tests/demo/test_demo_app.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add demo/app.py tests/demo/test_demo_app.py
git commit -m "feat: expose parity trace endpoint"
```

## Task 5: Parity UI Panel

**Files:**
- Modify: `demo/templates/index.html`
- Modify: `tests/demo/test_demo_app.py`

- [ ] **Step 1: Update home test for parity UI markers**

In `test_demo_home_loads`, add these assertions:

```python
    assert "OpenClaw Parity" in response.text
    assert "parity-trace" in response.text
    assert "/api/parity/trace" in response.text
    assert "renderParityTrace" in response.text
    assert "Python Port" in response.text
    assert "OpenClaw TS Oracle" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/demo/test_demo_app.py::test_demo_home_loads -v
```

Expected: FAIL because the parity UI markers are missing.

- [ ] **Step 3: Add tab button and panel**

In `demo/templates/index.html`, add a tab button after Tool Inspector:

```html
<button class="tab" data-tab="parity-trace" type="button">OpenClaw Parity</button>
```

Add a panel after Tool Inspector:

```html
<section id="parity-trace" class="tab-panel" aria-label="OpenClaw Parity">
  <div class="panel-heading">
    <h2>OpenClaw Parity</h2>
    <span>Python Port vs OpenClaw TS Oracle</span>
  </div>
  <button id="run-parity-trace" type="button">Run parity trace</button>
  <div id="parity-output" class="parity-output"></div>
</section>
```

- [ ] **Step 4: Add parity JavaScript renderer**

Add this script block near other render helpers:

```javascript
function renderParityTrace(payload) {
  const panel = document.querySelector("#parity-output");
  panel.replaceChildren();
  const meta = document.createElement("section");
  meta.className = "pipeline-step";
  meta.append(sectionBlock("Oracle", kvGrid({
    Available: payload.oracle && payload.oracle.available,
    Commit: payload.oracle && payload.oracle.commit || "",
    Path: payload.oracle && payload.oracle.repoPath || "",
  })));
  panel.append(meta);
  for (const step of payload.steps || []) {
    const row = document.createElement("section");
    row.className = `pipeline-step parity-row parity-${step.diff && step.diff.status || "unknown"}`;
    const heading = document.createElement("h3");
    heading.textContent = `${step.label || step.id} - ${step.diff && step.diff.status || "unknown"}`;
    const columns = document.createElement("div");
    columns.className = "inspector-grid";
    columns.append(sectionBlock("Python Port", renderJsonView(step.python || {})));
    columns.append(sectionBlock("OpenClaw TS Oracle", renderJsonView(step.openclaw || {})));
    row.append(heading);
    if (step.condition) row.append(sectionBlock("Condition", codeBlock(step.condition)));
    row.append(columns);
    row.append(sectionBlock("Diff", renderJsonView(step.diff || {})));
    panel.append(row);
  }
}
```

Add button handler near other handlers:

```javascript
document.querySelector("#run-parity-trace").onclick = async () => {
  try {
    const payload = await requestJson("/api/parity/trace", {});
    renderParityTrace(payload);
  } catch (error) {
    document.querySelector("#parity-output").textContent = error.message;
  }
};
```

- [ ] **Step 5: Run home test**

Run:

```bash
pytest tests/demo/test_demo_app.py::test_demo_home_loads -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add demo/templates/index.html tests/demo/test_demo_app.py
git commit -m "feat: add openclaw parity panel"
```

## Task 6: Recall Tracking Fixture Comparison

**Files:**
- Modify: `demo/parity_trace.py`
- Modify: `tests/demo/test_parity_trace.py`

- [ ] **Step 1: Add failing test for recall tracking step**

Append to `tests/demo/test_parity_trace.py`:

```python
def test_build_parity_trace_includes_recall_tracking_step():
    trace = build_parity_trace(FakeOracle())

    ids = [step["id"] for step in trace["steps"]]

    assert "recall-tracking" in ids
```

Update imports:

```python
from demo.parity_trace import build_deep_policy_trace, build_parity_trace, diff_values
```

Replace `FakeOracle.run` with an operation-aware implementation:

```python
    def run(self, payload):
        if payload["operation"] == "deepPolicy":
            return {
                "ok": True,
                "operation": "deepPolicy",
                "result": {
                    "minScore": 0.8,
                    "minRecallCount": 3,
                    "minUniqueQueries": 3,
                    "maxAgeDays": 30,
                },
            }
        if payload["operation"] == "recordShortTermRecalls":
            return {
                "ok": True,
                "operation": "recordShortTermRecalls",
                "files": {
                    "memory/.dreams/short-term-recall.json": '{"entries": {}}'
                },
            }
        raise AssertionError(f"unexpected operation: {payload['operation']}")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/demo/test_parity_trace.py::test_build_parity_trace_includes_recall_tracking_step -v
```

Expected: FAIL because only `deep-policy` exists.

- [ ] **Step 3: Add recall tracking trace skeleton**

Modify `demo/parity_trace.py`:

```python
def build_recall_tracking_trace(oracle: OpenClawOracle | Any) -> dict[str, Any]:
    query = "address preference"
    result = {
        "source": "memory",
        "path": "memory/2026-05-26.md",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- User prefers to be addressed as dodo.",
        "score": 1,
    }
    oracle_result = oracle.run(
        {
            "operation": "recordShortTermRecalls",
            "query": query,
            "results": [result],
            "nowMs": 1779811200000,
            "timezone": "Europe/Istanbul",
        }
    )
    openclaw_decision = "recorded" if oracle_result.get("ok") else "error"
    return {
        "id": "recall-tracking",
        "label": "Recall tracking from memory_search",
        "condition": 'result.source === "memory" && isShortTermMemoryPath(result.path)',
        "python": {
            "decision": "recordable",
            "values": {"query": query, "path": result["path"], "score": result["score"]},
            "reasons": [],
        },
        "openclaw": {
            "decision": openclaw_decision,
            "values": {"ok": oracle_result.get("ok")},
            "reasons": [] if oracle_result.get("ok") else [oracle_result.get("error", {}).get("message", "")],
        },
        "diff": {"status": "match" if oracle_result.get("ok") else "error", "details": []},
    }
```

Update `build_parity_trace`:

```python
def build_parity_trace(oracle: OpenClawOracle | None = None) -> dict[str, Any]:
    oracle = oracle or OpenClawOracle()
    return {
        "oracle": oracle.metadata(),
        "steps": [
            build_deep_policy_trace(oracle),
            build_recall_tracking_trace(oracle),
        ],
    }
```

- [ ] **Step 4: Run parity trace tests**

Run:

```bash
pytest tests/demo/test_parity_trace.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add demo/parity_trace.py tests/demo/test_parity_trace.py
git commit -m "feat: add recall tracking parity step"
```

## Task 7: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/demo/test_openclaw_oracle.py tests/demo/test_parity_trace.py tests/demo/test_demo_app.py -v
```

Expected: PASS.

- [ ] **Step 2: Run integration test when oracle checkout is prepared**

Run:

```bash
OPENCLAW_ORACLE_REPO=/tmp/openclaw-upstream pytest tests/integration/test_openclaw_ts_oracle.py -v
```

Expected: PASS if `/tmp/openclaw-upstream` exists and dependencies are installed. If skipped or unavailable, note that in the final handoff.

- [ ] **Step 3: Run lint**

Run:

```bash
ruff check .
```

Expected: PASS.

- [ ] **Step 4: Run full tests**

Run:

```bash
pytest -v
```

Expected: PASS, except the opt-in integration test remains skipped unless `OPENCLAW_ORACLE_REPO` is set.

- [ ] **Step 5: Commit final verification adjustments if needed**

If any small test or lint fix was required:

```bash
git add demo tests scripts
git commit -m "test: verify openclaw parity demo"
```

If no files changed, do not create an empty commit.

## Self-Review Notes

- Spec coverage: oracle metadata, TS runner, paired trace model, API, UI, and mismatch visibility are covered.
- The first implementation intentionally stops short of full chat runtime parity and full OpenClaw gateway execution.
- The plan includes an opt-in real TS integration test while keeping normal test runs deterministic.
- Known current mismatch `0.75/3/2` vs managed deep `0.8/3/3` is explicitly tested and displayed.
