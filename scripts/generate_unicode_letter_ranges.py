#!/usr/bin/env python3
"""Generate exact Unicode17 Letter facts with the reviewed Node24.16 binary.

No third-party Python package participates in generation or runtime matching.
The resulting class facts do not imply support for other Unicode properties,
JavaScript v-sets, or general case-fold/capture equivalence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_core.project_name import PACKAGE_NAME  # noqa: E402


PINNED_NODE_SHA256 = "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"
PINNED_RANGES_SHA256 = "26c5b6818af32e29fab028eb7e9c1b29a156a9a51ca0fef59b9fddb81d8025a9"
ENGINE = ("v24.16.0", "78.3", "17.0")
NODE_PROGRAM = r"""
const pattern = /^\p{L}$/u;
const ranges = [];
let first = null, last = null;
for (let point = 0; point <= 0x10ffff; point++) {
  if (pattern.test(String.fromCodePoint(point))) {
    if (first === null) first = point;
    last = point;
  } else if (first !== null) {
    ranges.push([first, last]);
    first = null;
  }
}
if (first !== null) ranges.push([first, last]);
process.stdout.write(JSON.stringify({
  node: process.version, icu: process.versions.icu,
  unicode: process.versions.unicode, ranges,
}));
"""


def unicode_notice(source: Path) -> str:
    match = re.search(
        r"(?ms)^ +UNICODE LICENSE V3\n.*?^ +SPDX-License-Identifier: Unicode-3\.0[^\n]*",
        source.read_text(encoding="utf-8"),
    )
    if match is None:
        raise ValueError("The supplied Node license has no complete Unicode-3.0 notice")
    return textwrap.dedent(match.group(0)).strip() + "\n"


def render_module(data: dict) -> str:
    ranges = data["ranges"]
    digest = hashlib.sha256(json.dumps(ranges, separators=(", ", ": ")).encode("ascii")).hexdigest()
    if digest != PINNED_RANGES_SHA256:
        raise ValueError("The exact Letter property facts changed")
    body = '''"""Generated Unicode17.0 General_Category=Letter facts.

Reproduce with scripts/generate_unicode_letter_ranges.py and the exact pinned
Node binary. See LICENSE.unicode for the Unicode-3.0 copyright and permission
notice. These facts are not a generic Unicode-property or regex engine.
"""

'''
    body += f'UNICODE_VERSION = "{data["unicode"]}"\n'
    body += f'NODE_VERSION = "{data["node"]}"\n'
    body += f'ICU_VERSION = "{data["icu"]}"\n'
    body += f'NODE_BINARY_SHA256 = "{PINNED_NODE_SHA256}"\n'
    body += f'RANGES_JSON_SHA256 = "{digest}"\n'
    body += f'LETTER_CODEPOINT_COUNT = {sum(last - first + 1 for first, last in ranges)}\n'
    body += "\nUNICODE_LETTER_RANGES = (\n"
    for first, last in ranges:
        body += f"    (0x{first:04X}, 0x{last:04X}),\n"
    return body + ")\n"


def generate(node: Path) -> str:
    node = node.resolve()
    if hashlib.sha256(node.read_bytes()).hexdigest() != PINNED_NODE_SHA256:
        raise ValueError("Generation requires the exact reviewed Node24.16.0 binary")
    completed = subprocess.run(
        [str(node), "-e", NODE_PROGRAM], check=True, text=True, capture_output=True,
        env={"PATH": str(node.parent), "LANG": "en_US.UTF-8", "TZ": "UTC"},
    )
    data = json.loads(completed.stdout)
    if (data["node"], data["icu"], data["unicode"]) != ENGINE:
        raise ValueError("The Node/ICU/Unicode engine identity changed")
    return render_module(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--node-license", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / PACKAGE_NAME / "_unicode_letter_ranges.py")
    parser.add_argument("--notice", type=Path, default=ROOT / "LICENSE.unicode")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    module, notice = generate(args.node), unicode_notice(args.node_license)
    if args.check:
        if args.output.read_text(encoding="utf-8") != module or args.notice.read_text(encoding="utf-8") != notice:
            raise SystemExit("The generated Letter facts or Unicode notice differ")
        return
    if args.notice.exists() and args.notice.read_text(encoding="utf-8") != notice:
        raise SystemExit("An existing Unicode notice has different content; it was preserved")
    args.output.write_text(module, encoding="utf-8")
    args.notice.write_text(notice, encoding="utf-8")


if __name__ == "__main__":
    main()
