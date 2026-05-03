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
python -m uvicorn demo.app:app --port 8000
```

Open <http://127.0.0.1:8000>. The first screen is an OpenClaw-style chat
memory lab: send a message, inspect memory recall, run a manual memory flush,
or enable auto flush to write durable memories while chatting.

Fake mode is deterministic and requires no network. OpenAI-compatible chat mode
is enabled only when all of these environment variables are set:

```bash
export OPENCLAW_DEMO_OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENCLAW_DEMO_OPENAI_API_KEY="..."
export OPENCLAW_DEMO_OPENAI_MODEL="..."
```

Memory flush writes are restricted to `memory/YYYY-MM-DD.md`, matching
OpenClaw pre-compaction memory flush behavior. The demo appends to the canonical
daily file and rejects timestamped variants or other write targets.

Smoke test the chat lab endpoints:

```bash
curl -s http://127.0.0.1:8000/api/chat/state
curl -s -X POST http://127.0.0.1:8000/api/chat/send \
  -H 'Content-Type: application/json' \
  -d '{"message":"Ben teknik cevapları Türkçe tercih ediyorum.","engine":"fake","autoFlush":true}'
```

## Live OpenAI-Compatible Embeddings

The demo and tests default to deterministic fake embeddings. To add a live
provider flow, configure `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and model
`text-embedding-3-small`.
