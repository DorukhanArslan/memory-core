# memory-core

Python port of OpenClaw core memory, pinned to upstream commit
`7f6798094ce9486a8f463772f4535484aca73fe2`.

The first implementation slice covers `MEMORY.md`, `memory/YYYY-MM-DD.md`,
`memory_search`, `memory_get`, hybrid search, citations, and a local FastAPI demo.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run Tests

```bash
pytest -v
ruff check .
```

## Run Demo

```bash
uvicorn demo.app:app --reload --port 8000
```

Open <http://localhost:8000>, click Seed Memory, click Reindex, then test
`memory_search` and `memory_get`.

Smoke test the demo endpoints:

```bash
python - <<'PY'
import httpx

base = "http://127.0.0.1:8000"
print(httpx.get(base + "/").status_code)
print(httpx.post(base + "/api/seed").json())
print(httpx.post(base + "/api/reindex").json())
print(httpx.post(base + "/api/search", json={"query": "lemon pepper"}).json()["results"][0]["path"])
print(httpx.post(base + "/api/get", json={"path": "MEMORY.md", "from": 3, "lines": 1}).json()["text"])
PY
```

Expected output contains:

```text
200
{'ok': True}
MEMORY.md
User prefers lemon pepper wings with blue cheese.
```

## Live OpenAI-Compatible Embeddings

The demo and tests default to deterministic fake embeddings. To add a live
provider flow, configure `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and model
`text-embedding-3-small`.
