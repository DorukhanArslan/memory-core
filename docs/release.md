# Release preparation

Version 0.2.0 is unreleased. The package has no index release. These checks prepare the
current package. They do not publish it or change its runtime defaults.

## Local checks

Use Python 3.11 or newer and uv. Run from the checkout. The development tools come from
`uv.lock`; `mypy` is a development dependency, not a core dependency.

```bash
uv sync --frozen
uv run --frozen ruff check . --no-cache
uv run --frozen python scripts/rename_project.py --check
```

Use a temporary directory for tests. Blank the provider keys so that a local `.env` cannot
supply them. Disable oracle and live-test gates for this offline run.

```bash
scratch=$(mktemp -d)
env -u OPENCLAW_ORACLE_REPO -u MEMORY_CORE_LIVE_OPENAI \
  -u MEMORY_CORE_OVERFLOW_ORACLE_OUT \
  TMPDIR="$scratch" PYTHONDONTWRITEBYTECODE=1 LANGSMITH_TRACING=false \
  OPENAI_API_KEY= MEMORY_CORE_DEMO_OPENAI_API_KEY= \
  MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY= \
  uv run --frozen pytest -q -p no:cacheprovider
uv run --frozen python scripts/check_distribution.py
```

The distribution check builds a wheel and a source distribution (sdist) in temporary
storage. It checks the package files, version, Python requirement, core dependency and
upstream notice. The sdist also carries `.gitignore`, which
[Hatch includes automatically](https://hatch.pypa.io/latest/plugins/builder/sdist/#default-file-selection).
It installs each artifact in a separate environment outside the checkout.
It imports all core modules and runs a real SQLite FTS-only HostKit turn with search and
retrieval. It also runs the installed consumer type checks. No model or embeddings provider
is used. Build and install steps can download package dependencies. Temporary artifacts and
environments are removed when the command exits.

The Lab, examples, tests and scripts stay in the checkout. The `demo` extra installs the
Lab's dependencies; it does not put the Lab in the wheel. The core still depends only on
`httpx`. Optional framework imports must remain absent from a core-only install.

## Type checks

`memory_core/py.typed` exposes the existing inline annotations to type checkers.
`tests/typing/check_consumer.py` copies its consumer fixtures outside the checkout and uses
the selected installed environment. Positive examples must pass. Each deliberate invalid
call must produce the expected error at the expected line.

This checks selected exports and host/live interfaces. It does not assert strict typing for
all ported helpers. `HostKit.open(**options)` and some model callbacks retain `Any`; the
checker cannot validate all values forwarded through those interfaces.

## CI checks

The offline GitHub Actions workflow runs on pull requests, pushes to `main` and manual
requests. It uses Linux with Python 3.11 and 3.12 and installs the frozen development stack.
It checks lint, project naming, offline tests and both installed artifacts. It has read-only
repository permissions and has no publication job, provider keys or oracle checkout.
Action versions are pinned to commits from the official [checkout](https://github.com/actions/checkout),
[setup-python](https://github.com/actions/setup-python) and [setup-uv](https://github.com/astral-sh/setup-uv) repositories.

Adding the workflow does not prove that GitHub ran it. Record the actual workflow result
after an authorized push. Local macOS results do not establish Linux support. The declared
Python range has no upper bound; this matrix does not test every newer Python version.

## Recorded local verification — 2026-10-08

Code candidate `49c6867` passed these checks on macOS. The final documentation changes
only describe the results and correct the existing consolidation default description.

| Python | Full offline tests | Time | Clean wheel and sdist |
| --- | --- | --- | --- |
| 3.11.9 | 1929 passed, 1625 skipped, 0 failed | 97.01 s | imports, FTS/HostKit, dependency/notice checks and consumer types passed |
| 3.12.7 | 1929 passed, 1625 skipped, 0 failed | 91.81 s | imports, FTS/HostKit, dependency/notice checks and consumer types passed |

Ruff, project naming, workflow YAML parsing and the diff check passed. Independent review
closed the metadata-marker finding and found no remaining actionable issue in this scope.
These runs used isolated frozen development environments. The checkout's existing `.venv`
was not changed. Artifact installs resolved allowed core dependencies independently of the
development lock. Hosted Linux CI, a new full oracle run and real-provider acceptance were
not performed. No push or publication was performed.

## CI portability repair — 2026-10-09

The first [hosted Linux run](https://github.com/DorukhanArslan/memory-core/actions/runs/37914961404)
on `3f56590` failed on Python 3.11 and 3.12. Each job reported 1919 passed, 6 failed,
3 errors and 1626 skipped; the artifact step did not run. The failures came from two
environment assumptions: renaming required resolver metadata absent from the frozen-install
cache, and migration tests expected absolute paths inside HOME where messages use `~/`.

Candidate `80cbcbe` repairs these boundaries. A name-only rename rewrites the existing
project lock entries and preserves resolved dependencies. The regression checks unchanged
third-party metadata and lock markers; with uv installed it also checks the renamed lock
using real `uv lock --check --offline` with an empty cache. Migration tests assert complete
literal messages both inside and outside HOME. Migration runtime behavior is unchanged.

Local macOS verification used isolated frozen environments, temporary HOME/TMPDIR and empty
offline uv caches for both full suites. Provider keys, live gates, oracle gates and tracing
were disabled. The checkout's existing `.venv` was not changed.

| Python | Full offline tests | Time | Clean wheel and sdist |
| --- | --- | --- | --- |
| 3.11.9 | 1935 passed, 1625 skipped, 0 failed/errors | 116.60 s | imports, FTS/HostKit, dependency/notice checks and consumer types passed |
| 3.12.7 | 1935 passed, 1625 skipped, 0 failed/errors | 114.47 s | imports, FTS/HostKit, dependency/notice checks and consumer types passed |

Ruff, naming and diff checks passed. Independent spec and code review found no actionable
issue. These are tooling/test repairs, with no new OpenClaw parity claim. A fresh hosted
Linux result remains required after an authorized push. No new full oracle run, real-provider
acceptance or publication was performed. Artifact installs can download dependencies as
described above.

## Before publication

- Confirm the copyright holder and year for the project's MIT notice. Add the project's
  LICENSE and metadata, preserve LICENSE.openclaw, and update artifact allowlists and checks.
- Confirm the permanent distribution name, release version and target package index.
- Run the checks on the exact commit to publish. Check the Linux CI result.
- If the release requires a fresh full-oracle run or real-provider acceptance, run those
  separate checks and record their commit, pin, model and result. Offline CI does not replace
  them. The provider model remains a host choice.
- Obtain explicit authorization for push and publication. Build the final artifacts and
  publish only those verified files.

The release checks are adapter/build evidence. They add no OpenClaw parity claim. The
[parity matrix](parity_matrix.md) retains known tokenizer/regex, log transport, phase/runtime
and host-only boundaries. Host scheduling, retention and provider routing remain application
responsibilities.
