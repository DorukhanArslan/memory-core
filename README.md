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
memory lab. Enter an OpenAI-compatible API key, send a message, inspect memory
recall, run a manual memory flush, or enable auto flush to write durable
memories while chatting.

The chat demo uses only the OpenAI-compatible engine. The browser keeps the API
key in session storage and sends it with each chat/flush request; the backend
does not write it to disk. Defaults are `https://api.openai.com/v1` and
`gpt-5.5`. You can also configure the backend with environment variables:

```bash
export OPENCLAW_DEMO_OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENCLAW_DEMO_OPENAI_API_KEY="sk-demo-key"
export OPENCLAW_DEMO_OPENAI_MODEL="gpt-5.5"
```

Memory flush writes are restricted to `memory/YYYY-MM-DD.md`, matching
OpenClaw pre-compaction memory flush behavior. The demo appends to the canonical
daily file and rejects timestamped variants or other write targets.

Smoke test the chat lab endpoints:

```bash
curl -s http://127.0.0.1:8000/api/chat/state
curl -s -X POST http://127.0.0.1:8000/api/chat/send \
  -H 'Content-Type: application/json' \
  -d '{"message":"Ben teknik cevapları Türkçe tercih ediyorum.","engine":"openai","openai":{"apiKey":"sk-demo-key","model":"gpt-5.5"},"autoFlush":true}'
```

## Live OpenAI-Compatible Embeddings

The demo and tests default to deterministic fake embeddings. To add a live
provider flow, configure `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and model
`text-embedding-3-small`.
