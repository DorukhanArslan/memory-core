#!/usr/bin/env python3
"""Rename the project, or check that its name is declared and spelled consistently.

pyproject.toml declares the name once: ``[project] name`` is the distribution name (lower-case
words joined by ``-``; PEP 621 keeps it there) and ``display-name`` in ``[tool.<package>]`` is
how prose and the UI write the product. ``<package>/project_name.py`` repeats the two values,
since an installed package has no pyproject.toml, and derives every other form from them;
runtime code spells the name only through that module::

    python scripts/rename_project.py --check
    python scripts/rename_project.py --to <dist-name> [--display <text>]

``--to`` renames the project from the declared name: the package directory (``git mv``), the
declaration, the constant module, uv.lock (relocked by ``uv lock --offline`` when uv is
installed, else its own entries rewritten) and every spelling of the name in the tracked
files. ``--display`` defaults to the new distribution name. It commits nothing and ends with
``--check``, which lists every disagreement between the declaration, the package directory,
the constant module, pyproject.toml and uv.lock, and every string in runtime code that spells
the name itself, and exits 1 if there is one.

Spellings. The words of a name (``probe-kit``: probe, kit) give its forms: kebab
(``probe-kit``: the distribution name and the slug of file and directory names), snake
(``probe_kit``: the package and identifiers), upper snake (``PROBE_KIT``: constants and the
``PROBE_KIT_`` environment prefix), Pascal and camel case (``ProbeKit``, ``probeKit``), title
and upper kebab (``Probe-Kit``, ``PROBE-KIT``) and the display name.
A one-word name spells several forms alike, so the context of each occurrence decides: an
identifier, an import, a module path or a package directory (``name/``) takes the snake form; a
word joined by ``-``, a dot-file name, the last part of a path, a package extra and a quoted
name take the kebab form; any other word, the display name. Once the display name equals the
distribution name, a quoted display name reads as the distribution name, so code that means
the display name imports DISPLAY_NAME instead of quoting it. The rename tooling (UNTOUCHED)
spells no project name.

Upstream names. OpenClaw's memory component is itself called memory-core. A rename never
touches the spellings PROTECTED matches (its paths and package, the plugin config key, the
identifiers and prose that name the upstream component), so the project's own occurrences stay
distinguishable from them, and a rename *to* a name refuses while that name is spelled anywhere
else in the tree.
"""

from __future__ import annotations

import argparse
import ast
import functools
import io
import json
import re
import shutil
import string
import subprocess
import sys
import tokenize
import tomllib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = "pyproject.toml"
LOCKFILE = "uv.lock"
CONSTANT_MODULE = "project_name.py"
DIST_NAME_RE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z][a-z0-9]*)*")

# A rename leaves these byte-identical: the upstream licence notice and the rename tooling,
# which reads the project name from the declaration and spells only upstream names. Files in a
# hidden top-level directory (local tool configuration) are left alone as well.
UNTOUCHED = ("LICENSE.openclaw", "scripts/rename_project.py", "tests/unit/test_project_name.py")

# Upstream spellings no rename touches (module docstring). Write a new mention of OpenClaw's
# component as "OpenClaw memory-core", a path or the config key, or add its phrase here;
# anything else reads as the project's own name once the project is called memory-core.
PROTECTED = (
    # Paths in the OpenClaw checkout and its package name.
    r"extensions/memory-core\b",
    r"@openclaw/memory-core\b",
    # The plugin config key, plugins.entries["memory-core"].
    r'entries\??\.?\["memory-core"\]',
    r'entries\.get\("memory-core"',
    r"entries\.memory-core\b",
    r'"entries":\s*\{\s*"memory-core"',
    r'\.get\("entries", \{\}\)\s*\.get\("memory-core"',
    # Identifiers that name the upstream component, and the locals that hold its config entry
    # (by their context: bare, they are the project's own snake and camel forms).
    r"(?<![\w$])(?:initialize_memory_core_workspace|_memory_core_plugin_config"
    r"|test_runner_resolves_memory_core_plugin_config"
    r"|test_from_workspace_initialize_creates_memory_core_files|resolveMemoryCoreNowMs"
    r"|resolveMemoryCorePluginConfig|configureMemoryCoreDreamingStateForTests"
    r"|loadMemoryCoreTestHelpers|memoryCoreConfig)(?![\w$])",
    r'(?<![\w$])memory_core(?= = _as_dict\(entries\.get\(|\.get\("config"\))',
    r"(?<![\w$])memoryCore(?= = isRecord\(entries|\??\.config\b)",
    # Prose that names the upstream component.
    r"OpenClaw(?:'s)?(?: TypeScript)? [Mm]emory-[Cc]ore\b",
    r"upstream `memory-core`",
    r"the memory-core workspace surface",
    r"plug-and-play memory-core port\b",
    r"Tak-çalıştır memory-core portu",
    r"memory-core (?:Python package )?MVP\b",
    r"optional memory-core\s+capabilities",
    r"is memory-core only",
    r"Python memory-core package",
    r"memory-core behaviou?r",
    r"memory-core prompt section",
    r"measured memory-core parity",
    r"deterministic memory-core\s+boundaries",
    r"memory-core function behavior",
    r"the memory-core plugin config",
    r"\(memory-core manager\.ts\)",
)
_PROTECTED_RE = re.compile("|".join(f"(?:{pattern})" for pattern in PROTECTED))

FORMS = (
    "kebab",
    "title_kebab",
    "upper_kebab",
    "snake",
    "upper_snake",
    "pascal",
    "camel",
    "display",
    "display_upper",
)
_LOWER = frozenset(string.ascii_lowercase)
_UPPER_OR_DIGIT = frozenset(string.ascii_uppercase + string.digits)
_LOWER_OR_DIGIT = _LOWER | frozenset(string.digits)
_ALNUM = _UPPER_OR_DIGIT | _LOWER
_IDENTIFIER_CHAR = re.compile(r"[A-Za-z0-9_]")
_IDENTIFIER_START = re.compile(r"[A-Za-z_]")
_IMPORT_BEFORE = re.compile(r"(?:^|[`'\"(;])\s*(?:from|import)\s+$")


@dataclass(frozen=True)
class ProjectName:
    dist: str
    display: str

    @property
    def package(self) -> str:
        return self.dist.replace("-", "_")

    def spell(self, form: str) -> str:
        words = self.dist.split("-")
        titled = [word.capitalize() for word in words]
        return {
            "kebab": self.dist,
            "title_kebab": "-".join(titled),
            "upper_kebab": self.dist.upper(),
            "snake": self.package,
            "upper_snake": self.package.upper(),
            "pascal": "".join(titled),
            "camel": words[0] + "".join(titled[1:]),
            "display": self.display,
            "display_upper": self.display.upper(),
        }[form]

    @functools.cached_property
    def spellings(self) -> dict[str, frozenset[str]]:
        """Every spelling of the name and the forms it can stand for."""
        forms: dict[str, set[str]] = {}
        for form in FORMS:
            forms.setdefault(self.spell(form), set()).add(form)
        for spelling, found in forms.items():
            if spelling.casefold() == self.display.casefold():
                found.add("display_upper" if spelling.isupper() else "display")
        return {spelling: frozenset(found) for spelling, found in forms.items()}

    @functools.cached_property
    def pattern(self) -> re.Pattern[str]:
        """Any spelling, longest first (name_matches keeps those that stand as a word)."""
        return re.compile("|".join(map(re.escape, sorted(self.spellings, key=len, reverse=True))))


def read_declaration(root: Path) -> ProjectName:
    name, problems = declared_name(root)
    if name is None or problems:
        raise SystemExit("\n".join(problems))
    return name


def declared_name(root: Path) -> tuple[ProjectName | None, list[str]]:
    """The declared name and the problems of the declaration itself. With ``[project] name``
    edited by hand, the display name comes from the one ``[tool.*]`` table that holds it, so
    the check can still list each place that disagrees; no usable name gives None."""
    try:
        data = tomllib.loads((root / PYPROJECT).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        return None, [f"{PYPROJECT}: {error}"]
    dist = data.get("project", {}).get("name")
    if not isinstance(dist, str):
        return None, [f"{PYPROJECT}: no [project] name"]
    package, tools = ProjectName(dist, "").package, data.get("tool", {})
    tables = [key for key, table in tools.items() if isinstance(table, dict)]
    tables = [key for key in tables if "display-name" in tools[key]]
    problems = []
    if package in tables:
        display = tools[package]["display-name"]
    elif len(tables) == 1:
        display = tools[tables[0]]["display-name"]
        problems.append(
            f"{PYPROJECT}: the declared name is {dist}, but the display-name table is"
            f" [tool.{tables[0]}], not [tool.{package}]"
        )
    else:
        return None, [f"{PYPROJECT}: no display-name in [tool.{package}]"]
    if not isinstance(display, str):
        return None, [*problems, f"{PYPROJECT}: display-name is not a string"]
    name = ProjectName(dist, display)
    invalid = [f"{PYPROJECT}: {problem}" for problem in name_problems(name)]
    return (None if invalid else name), [*problems, *invalid]


# --- finding and rewriting spellings -------------------------------------------------------


def protected_spans(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in _PROTECTED_RE.finditer(text)]


def stands_as_word(text: str, start: int, end: int) -> bool:
    """Whether ``text[start:end]`` is a whole word; a camelCase neighbour is a boundary."""
    spelling = text[start:end]
    before, after = text[start - 1 : start], text[end : end + 1]
    capitalized = spelling[:1].isupper() and not spelling.isupper()
    if before in (_UPPER_OR_DIGIT if capitalized else _ALNUM):
        return False
    if not spelling[-1:].isupper():
        return after not in _LOWER_OR_DIGIT
    if after not in _ALNUM:
        return True
    # A spelling that ends in a one-letter word (ProbeA) may run into the next camelCase word.
    return not spelling.isupper() and after.isupper() and text[end + 1 : end + 2] in _LOWER


def name_matches(text: str, name: ProjectName) -> list[re.Match[str]]:
    """Occurrences of the name outside the protected upstream spellings."""
    matches = [
        match
        for match in name.pattern.finditer(text)
        if stands_as_word(text, match.start(), match.end())
    ]
    protected = protected_spans(text) if matches else []
    return [
        match
        for match in matches
        if not any(match.start() < stop and begin < match.end() for begin, stop in protected)
    ]


def _within(match: re.Match[str], spans: Iterable[tuple[int, int]]) -> bool:
    return any(start <= match.start() and match.end() <= end for start, end in spans)


def _token_spans(text: str) -> Iterator[tuple[tokenize.TokenInfo, tuple[int, int]]]:
    """The tokens of Python source, each with its span in ``text``."""
    offsets = [0]
    for line in text.split("\n"):
        offsets.append(offsets[-1] + len(line) + 1)
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        start, end = token.start, token.end
        yield token, (offsets[start[0] - 1] + start[1], offsets[end[0] - 1] + end[1])


def python_name_spans(text: str) -> frozenset[tuple[int, int]]:
    """Spans of the identifier tokens of Python source."""
    return frozenset(span for token, span in _token_spans(text) if token.type == tokenize.NAME)


def classify(text: str, start: int, end: int, forms: frozenset[str], identifier: bool) -> str:
    """The form one occurrence stands for, from its neighbours (module docstring)."""
    before, before2 = text[start - 1 : start], text[max(start - 2, 0) : max(start - 1, 0)]
    after, after2 = text[end : end + 1], text[end + 1 : end + 2]
    candidates: list[str] = []
    if identifier:
        candidates += ["snake", "upper_snake", "pascal", "camel"]
    if after.isascii() and after.isupper():
        candidates += ["camel", "pascal"]
    if before.isascii() and (before.islower() or before.isdigit()):
        candidates += ["pascal"]
    if "_" in (before, after):
        candidates += ["snake", "upper_snake"]
    if "-" in (before, after):
        candidates += ["kebab", "title_kebab", "upper_kebab"]
    if before == "." and not _IDENTIFIER_CHAR.match(before2):
        candidates += ["kebab"]
    if (after == "." and _IDENTIFIER_START.match(after2)) or (
        before == "." and _IDENTIFIER_CHAR.match(before2)
    ):
        candidates += ["snake"]
    if after == "/" or _IMPORT_BEFORE.search(text[text.rfind("\n", 0, start) + 1 : start]):
        candidates += ["snake"]
    if after == "[" or before == "/" or (before == after and before in "'\"`"):
        candidates += ["kebab"]
    candidates += ["display", "display_upper", *FORMS]
    return next(form for form in candidates if form in forms)


def rewrite_text(text: str, old: ProjectName, new: ProjectName, *, python: bool) -> str:
    matches = name_matches(text, old)
    if not matches:
        return text
    identifiers = python_name_spans(text) if python else frozenset()
    parts, last = [], 0
    for match in matches:
        start, end = match.span()
        forms = old.spellings[match.group()]
        form = classify(text, start, end, forms, (start, end) in identifiers)
        parts += [text[last:start], new.spell(form)]
        last = end
    return "".join(parts) + text[last:]


# --- the tracked tree ------------------------------------------------------------------------


def tracked_files(root: Path) -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout.decode("utf-8")
    return [path for path in listing.split("\0") if path]


def in_scope(path: str) -> bool:
    """Whether a rename may change this tracked path (see UNTOUCHED)."""
    return path not in UNTOUCHED and not (path.startswith(".") and "/" in path)


def read_texts(root: Path) -> dict[str, str]:
    """The text of every tracked file a rename may change; binary files are skipped."""
    texts = {}
    for path in tracked_files(root):
        file = root / path
        if not in_scope(path) or file.is_symlink() or not file.is_file():
            continue
        try:
            texts[path] = file.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
    return texts


# --- the declaration files -----------------------------------------------------------------


def _replace_once(text: str, pattern: str, replacement: str, where: str) -> str:
    text, count = re.subn(pattern, lambda _match: replacement, text)
    if count != 1:
        raise SystemExit(f"{where}: expected one match of {pattern!r}, found {count}")
    return text


def rewrite_pyproject(text: str, old: ProjectName, new: ProjectName) -> str:
    """The name fields of pyproject.toml: the declaration and the packaging entries."""
    dist, package = re.escape(old.dist), re.escape(old.package)
    for pattern, replacement in (
        (rf'(?m)^name = "{dist}"$', f'name = "{new.dist}"'),
        (rf'(?m)^\[tool\.{package}\]$', f"[tool.{new.package}]"),
        (r"(?m)^display-name = .*$", f"display-name = {json.dumps(new.display)}"),
        (rf'"{dist}\[demo\]"', f'"{new.dist}[demo]"'),
        (rf'(?m)^path = "{package}/__init__\.py"$', f'path = "{new.package}/__init__.py"'),
        (rf'(?m)^packages = \["{package}"\]$', f'packages = ["{new.package}"]'),
        (rf'(?m)^only-include = \["{package}",', f'only-include = ["{new.package}",'),
    ):
        text = _replace_once(text, pattern, replacement, PYPROJECT)
    return text


def rewrite_constant_module(text: str, new: ProjectName) -> str:
    for constant, value in (("DIST_NAME", new.dist), ("DISPLAY_NAME", new.display)):
        text = _replace_once(
            text, rf"(?m)^{constant} = .*$", f"{constant} = {json.dumps(value)}", CONSTANT_MODULE
        )
    return text


def rewrite_lockfile(text: str, old: ProjectName, new: ProjectName) -> str:
    """The project's own entries in uv.lock, for a tree without uv (a relock sorts them)."""
    dist = re.escape(old.dist)
    text = _replace_once(text, rf'(?m)^name = "{dist}"$', f'name = "{new.dist}"', LOCKFILE)
    return re.sub(rf'\{{ name = "{dist}",', f'{{ name = "{new.dist}",', text)


# --- rename ----------------------------------------------------------------------------------


def name_problems(name: ProjectName) -> list[str]:
    problems = []
    if not DIST_NAME_RE.fullmatch(name.dist):
        problems.append(f"{name.dist!r} is not lower-case words joined by '-'")
    if not name.display.strip() or name.display != name.display.strip() or "\n" in name.display:
        problems.append(f"display name {name.display!r} is empty, padded or spans lines")
    return problems


def rename(root: Path, new: ProjectName) -> None:
    old = read_declaration(root)
    problems = name_problems(new)
    if new.dist == old.dist:
        problems.append(f"the project is already named {new.dist}")
    if (root / new.package).exists():
        problems.append(f"{new.package}/ already exists")
    if problems:
        raise SystemExit("\n".join(problems))
    texts = read_texts(root)
    collisions = [
        f"{path}:{text.count(chr(10), 0, match.start()) + 1}: {match.group()}"
        for path, text in texts.items()
        for match in name_matches(text, new)
    ]
    if collisions:
        raise SystemExit(
            f"the tree already spells {new.dist} outside the protected upstream spellings, so the"
            " rename could not be told apart from them later:\n" + "\n".join(collisions[:20])
        )
    constant_module = f"{old.package}/{CONSTANT_MODULE}"
    uv = shutil.which("uv")
    for path, text in texts.items():
        if path == LOCKFILE:
            updated = text if uv else rewrite_lockfile(text, old, new)
        else:
            updated = text
            if path == PYPROJECT:
                updated = rewrite_pyproject(text, old, new)
            elif path == constant_module:
                updated = rewrite_constant_module(text, new)
            updated = rewrite_text(updated, old, new, python=path.endswith(".py"))
        if updated != text:
            (root / path).write_bytes(updated.encode("utf-8"))
    move_paths(root, old, new)
    relock = [uv, "lock", "--offline", "--quiet"] if uv else None
    if relock and subprocess.run(relock, cwd=root, check=False).returncode:
        raise SystemExit("renamed, but `uv lock --offline` failed; relock by hand")
    problems = check(root)
    if problems:
        raise SystemExit("renamed, but the check fails:\n" + "\n".join(problems))
    print(f"renamed {old.dist} ({old.display}) to {new.dist} ({new.display}); nothing committed")


def move_paths(root: Path, old: ProjectName, new: ProjectName) -> None:
    """``git mv`` every tracked path that spells the old name, shallowest part first."""
    while True:
        moves = {}
        for path in filter(in_scope, tracked_files(root)):
            parts = path.split("/")
            renamed = rewrite_text(path, old, new, python=False).split("/")
            for depth, (part, new_part) in enumerate(zip(parts, renamed)):
                if part != new_part:
                    moves["/".join(parts[: depth + 1])] = "/".join(renamed[: depth + 1])
                    break
        if not moves:
            return
        for source, target in moves.items():
            subprocess.run(["git", "mv", source, target], cwd=root, check=True)


# --- check -----------------------------------------------------------------------------------


def check(root: Path) -> list[str]:
    name, problems = declared_name(root)
    if name is None:
        return problems
    return [
        *problems,
        *package_problems(root, name),
        *pyproject_problems(root, name),
        *lockfile_problems(root, name),
        *runtime_spellings(root, name),
    ]


def package_problems(root: Path, name: ProjectName) -> list[str]:
    if not (root / name.package / "__init__.py").is_file():
        return [f"the package directory {name.package}/ is missing"]
    module = f"{name.package}/{CONSTANT_MODULE}"
    if not (root / module).is_file():
        return [f"{module} is missing"]
    values = {
        node.targets[0].id: node.value.value
        for node in ast.parse((root / module).read_text(encoding="utf-8")).body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    return [
        f"{module}: {constant} is {values.get(constant)!r}, the declaration says {declared!r}"
        for constant, declared in (("DIST_NAME", name.dist), ("DISPLAY_NAME", name.display))
        if values.get(constant) != declared
    ]


def pyproject_problems(root: Path, name: ProjectName) -> list[str]:
    data = tomllib.loads((root / PYPROJECT).read_text(encoding="utf-8"))
    hatch = data.get("tool", {}).get("hatch", {})
    targets = hatch.get("build", {}).get("targets", {})
    fields = (
        ("the dev dependency group", data.get("dependency-groups", {}).get("dev", [])),
        ("[tool.hatch.version] path", [hatch.get("version", {}).get("path")]),
        ("the wheel packages", targets.get("wheel", {}).get("packages", [])),
        ("the sdist only-include", targets.get("sdist", {}).get("only-include", [])),
    )
    expected = (f"{name.dist}[demo]", f"{name.package}/__init__.py", name.package, name.package)
    return [
        f"{PYPROJECT}: {field} does not hold {value!r}"
        for (field, values), value in zip(fields, expected)
        if value not in values
    ]


def lockfile_problems(root: Path, name: ProjectName) -> list[str]:
    packages = tomllib.loads((root / LOCKFILE).read_text(encoding="utf-8")).get("package", [])
    own = [entry.get("name") for entry in packages if entry.get("source") == {"editable": "."}]
    if own != [name.dist]:
        return [f"{LOCKFILE}: the project's own entry is {own}, not [{name.dist!r}]"]
    return []


def runtime_spellings(root: Path, name: ProjectName) -> list[str]:
    """Strings in runtime code (the package, the Lab, the examples, the Python scripts) that
    spell the name instead of deriving it from the constant module. The TypeScript oracle runner
    is test tooling: it keeps its literals, which a rename rewrites."""
    constant_module = f"{name.package}/{CONSTANT_MODULE}"
    problems = []
    for path, text in read_texts(root).items():
        if path == constant_module or not path.startswith(
            (f"{name.package}/", "demo/", "examples/", "scripts/")
        ):
            continue
        matches = name_matches(text, name)
        if not matches:
            continue
        if path.endswith(".py"):
            spans = python_string_spans(text, matches)
        elif path.startswith("demo/") and path.endswith((".js", ".html", ".css")):
            spans = web_code_spans(text, Path(path).suffix)
        else:
            continue
        for match in matches:
            if _within(match, spans):
                line = text.count("\n", 0, match.start()) + 1
                problems.append(
                    f"{path}:{line}: runtime code spells the name ({match.group()}); derive it"
                    f" from {constant_module}"
                )
    return problems


def python_string_spans(text: str, matches: list[re.Match[str]]) -> list[tuple[int, int]]:
    """The string literals of Python source that hold one of ``matches``, without docstrings
    and ``__all__`` entries."""
    string_types = {tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", tokenize.STRING)}
    strings = {}
    for token, span in _token_spans(text):
        if token.type in string_types and any(_within(match, [span]) for match in matches):
            strings[token.start] = span
    if not strings:
        return []
    skipped = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                skipped.add((first.lineno, first.col_offset))
        if (
            isinstance(node, ast.Assign)
            and any(getattr(target, "id", None) == "__all__" for target in node.targets)
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            skipped.update((element.lineno, element.col_offset) for element in node.value.elts)
    return [span for start, span in strings.items() if start not in skipped]


def web_code_spans(text: str, suffix: str) -> list[tuple[int, int]]:
    """What a browser runs or shows: JavaScript literals, or HTML and CSS outside comments."""
    if suffix == ".js":
        return js_literal_spans(text)
    comment = re.compile(r"<!--.*?-->|\{#.*?#\}" if suffix == ".html" else r"/\*.*?\*/", re.S)
    spans, last = [], 0
    for match in comment.finditer(text):
        spans.append((last, match.start()))
        last = match.end()
    return [*spans, (last, len(text))]


_REGEX_AFTER = frozenset("(,=:[!&|?{};+-*%<>~^") | {"", "return", "typeof", "case", "in", "of"}


def js_literal_spans(text: str) -> list[tuple[int, int]]:
    """Spans of the strings, template-literal text and regular expressions of JavaScript."""
    spans: list[tuple[int, int]] = []
    size = len(text)

    def quoted(start: int, quote: str) -> int:
        index = start + 1
        while index < size and text[index] not in (quote, "\n"):
            index += 2 if text[index] == "\\" else 1
        spans.append((start + 1, index))
        return index + 1

    def regex(start: int) -> int:
        index, in_class = start + 1, False
        while index < size and text[index] != "\n":
            char = text[index]
            if char == "\\":
                index += 2
                continue
            if char == "/" and not in_class:
                break
            in_class = (in_class or char == "[") and char != "]"
            index += 1
        spans.append((start + 1, index))
        index += 1
        while index < size and text[index].isalpha():
            index += 1
        return index

    def template(start: int) -> int:
        piece = index = start + 1
        while index < size:
            if text[index] == "\\":
                index += 2
            elif text[index] == "`":
                spans.append((piece, index))
                return index + 1
            elif text.startswith("${", index):
                spans.append((piece, index))
                piece = index = code(index + 2, nested=True)
            else:
                index += 1
        spans.append((piece, size))
        return size

    def code(index: int, *, nested: bool) -> int:
        depth, previous = 0, ""
        while index < size:
            char = text[index]
            if text.startswith("//", index):
                end = text.find("\n", index)
                index = size if end < 0 else end
            elif text.startswith("/*", index):
                end = text.find("*/", index + 2)
                index = size if end < 0 else end + 2
            elif char in "'\"":
                index, previous = quoted(index, char), char
            elif char == "`":
                index, previous = template(index), char
            elif char == "/" and previous in _REGEX_AFTER:
                index, previous = regex(index), "/"
            elif char.isalnum() or char in "_$":
                end = index
                while end < size and (text[end].isalnum() or text[end] in "_$"):
                    end += 1
                index, previous = end, text[index:end]
            else:
                if char == "{":
                    depth += 1
                elif char == "}":
                    if nested and depth == 0:
                        return index + 1
                    depth -= 1
                if not char.isspace():
                    previous = char
                index += 1
        return index

    code(0, nested=False)
    return spans


def main() -> int:
    parser = argparse.ArgumentParser(description="Rename the project, or check its name.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="check the name's consistency")
    action.add_argument("--to", metavar="DIST_NAME", help="rename the project to this name")
    parser.add_argument("--display", help="the new display name (default: the new name)")
    args = parser.parse_args()
    if args.check:
        if args.display is not None:
            parser.error("--display goes with --to")
        problems = check(ROOT)
        print("\n".join(problems) if problems else "the project name is consistent")
        return 1 if problems else 0
    rename(ROOT, ProjectName(args.to, args.to if args.display is None else args.display))
    return 0


if __name__ == "__main__":
    sys.exit(main())
