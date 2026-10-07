"""Registry, user patterns and the tool-payload policies of ``redact.ts`` against the real TypeScript.

One oracle call (operation ``redactPolicies``) runs every fixed scenario below and each seeded
generated batch; a scenario is registry values, a logging config and steps, and the Python port
must return the same value at every step (see ``redact_policy_harness``).

Run: ``OPENCLAW_ORACLE_NODE=... OPENCLAW_ORACLE_REPO=/tmp/openclaw-head pytest
tests/integration/test_redact_policies_oracle.py``.
"""

from __future__ import annotations

import functools
import random

import pytest
from redact_policy_harness import compare, oracle_run

LONG = "a1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuVwXyZ"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
BIG = "z" * 40_000

SCENARIOS: list[tuple[str, dict]] = []


def scenario(name: str, steps: list[dict], **kwargs) -> None:
    SCENARIOS.append((name, {"steps": steps, **kwargs}))


def texts(name: str, values: list[str], texts_: list[str], fn: str = "sensitiveText", **extra) -> None:
    scenario(name, [{"fn": fn, "text": text, **extra} for text in texts_], registry=values)


# --- (a) the exact-secret registry ---------------------------------------------------------------------
SECRET = "hunter2-hunter2-hunter2"  # 22 units: hint mask
SHORT_SECRET = "pw-1234"  # 7 units: ***
texts(
    "registry-basic",
    [SECRET, SHORT_SECRET],
    [
        f"the password is {SECRET}.",
        f"{SECRET}{SECRET}",
        f"start {SHORT_SECRET} end {SHORT_SECRET}",
        SECRET,
        f"{SHORT_SECRET}",
        f"x{SECRET}",
        "nothing here",
        "",
        f"api_key={SECRET}",
        f"token: {SHORT_SECRET} and sk-abcdefghijklmnopqrstuvwxyz",
    ],
)
texts("registry-too-short-ignored", ["abcde", "12345", ""], ["abcde 12345 abcdef"])
texts("registry-exactly-six", ["abcdef", "ABCDEF"], ["abcdef ABCDEF abcdefABCDEF xabcdefx"])
texts(
    "registry-mask-length-boundary",
    ["a" * 17, "b" * 18, "c" * 19],
    ["a" * 17, "b" * 18, "c" * 19, "x" + "a" * 17 + "y", "x" + "b" * 18 + "y", "x" + "c" * 19 + "y"],
)
texts(
    "registry-longest-first-same-prefix",
    ["secret-value", "secret-value-longer", "secret", "secret-val"],
    [
        "secret-value-longer secret-value secret-val secret secret-valu",
        "xsecret-value-longerx",
        "secret-value-lon",
    ],
)
texts(
    "registry-prefix-collision-rejected-then-overlap",
    ["abcdefXYZ", "bcdefgHIJKL"],
    ["abcdefgHIJKL", "abcdefXYZ bcdefgHIJKL", "aabcdefXYZ", "abcdefgHIJKLabcdefXYZ"],
)
texts(
    "registry-overlapping-self",
    ["aaaaaaaa", "aaaaaa"],
    ["aaaaaaaaaaaaaaaaaaaa", "aaaaaa aaaaaaaa aaaaaaaaa", "aaaaaaa"],
)
texts(
    "registry-url-encoded-variant",
    ["my secret value+é&=/?", "plain-secret-abc"],
    [
        "https://x.test/?q=my%20secret%20value%2B%C3%A9%26%3D%2F%3F&z=1",
        "raw my secret value+é&=/? raw",
        "plain-secret-abc plain%2Dsecret",
    ],
)
texts(
    "registry-encode-uri-component-unreserved",
    ["a-b_c.d!e~f*g'h(i)j", "sp ace/slash:colon;semi"],
    [
        "a-b_c.d!e~f*g'h(i)j",
        "sp%20ace%2Fslash%3Acolon%3Bsemi",
        "sp ace/slash:colon;semi",
    ],
)
texts(
    "registry-json-escaped-variant",
    ['pa"ss\\word\nnew\ttab\x01ctl', 'quote"only-secret'],
    [
        'json: "pa\\"ss\\\\word\\nnew\\ttab\\u0001ctl" end',
        'raw: pa"ss\\word\nnew\ttab\x01ctl end',
        'x "quote\\"only-secret" y quote"only-secret',
        "pa%22ss%5Cword%0Anew%09tab%01ctl",
    ],
)
texts(
    "registry-json-other-controls",
    ["bell\x07form\x0cback\x08cr\rdel\x7fls ps end"],
    [
        "bell\x07form\x0cback\x08cr\rdel\x7fls ps end",
        "bell\\u0007form\\fback\\bcr\\rdel\x7fls ps end",
    ],
)
texts(
    "registry-astral",
    ["\U0001f600\U0001f600\U0001f600", "\U0001f600\U0001f600", "é😀 secret value long enough 🙂"],
    [
        "a\U0001f600\U0001f600\U0001f600b",
        "a\U0001f600\U0001f600b",
        "é😀 secret value long enough 🙂",
        "😀é😀 secret value long enough 🙂😀",
        "\U0001f600" * 8,
    ],
)
texts(
    "registry-astral-mask-length",
    ["😀" * 9, "😀" * 8, "x" + "😀" * 8 + "y" * 4],
    ["😀" * 9, "😀" * 8, "pre " + "😀" * 9 + " post", "x" + "😀" * 8 + "y" * 4],
)
scenario(
    "registry-lone-surrogate-uri-error",
    [
        {"fn": "registryState"},
        {"fn": "sensitiveText", "text": "a\ud800bcdefgh x"},
    ],
    registry=["a\ud800bcdefgh", "validsecret123"],
)
scenario(
    "registry-lone-surrogate-step",
    [
        {"fn": "register", "value": "x\udc00yzabcdef"},
        {"fn": "register", "value": "good-secret-1"},
        {"fn": "registryState"},
    ],
)
scenario(
    "registry-state-order",
    [
        {"fn": "registryState", "probe": ["a b c d e f", "a%20b%20c%20d%20e%20f", "abcdef"]},
        {"fn": "register", "value": "a b c d e f"},
        {"fn": "registryState"},
        {"fn": "register", "value": "abcdef"},
        {"fn": "register", "value": "zzzzzz"},
        {"fn": "register", "value": "abcdef"},
        {"fn": "registryState"},
        {"fn": "register", "value": "a b c d e f"},
        {"fn": "registryState"},
    ],
    registry=["a b c d e f"],
)
scenario(
    "registry-eviction-512",
    [
        {"fn": "registryState", "probe": ["secret-0000", "secret-0001", "secret-0511", "secret-0599"]},
        {"fn": "sensitiveText", "text": "secret-0000 secret-0001 secret-0099 secret-0599 x"},
        {"fn": "register", "value": "secret-0000"},
        {"fn": "register", "value": "secret-0600"},
        {"fn": "registryState", "probe": ["secret-0000", "secret-0001", "secret-0002"]},
        {"fn": "sensitiveText", "text": "secret-0000 secret-0001 secret-0002 secret-0003"},
    ],
    registry=[f"secret-{i:04d}" for i in range(0, 520)],
)
scenario(
    "registry-eviction-encoded-variants",
    [
        {"fn": "registryState", "probe": ["a b-0000", "a%20b-0000", "a b-0300", "a%20b-0300"]},
        {"fn": "sensitiveText", "text": "a b-0000 a%20b-0000 a b-0300 a%20b-0300 a b-0299 a%20b-0299"},
    ],
    registry=[f"a b-{i:04d}" for i in range(0, 400)],
)
scenario(
    "registry-raw-stays-newest",
    [
        {"fn": "registryState", "probe": ["q r s t u v", "q%20r%20s%20t%20u%20v"]},
        {"fn": "sensitiveText", "text": "q r s t u v q%20r%20s%20t%20u%20v"},
    ],
    registry=[f"fill-{i:04d}" for i in range(0, 511)] + ["q r s t u v"],
)
scenario(
    "registry-direct-callback",
    [
        {"fn": "registered", "text": "x aaaaaa y aaaaaaa z bbbbbb"},
        {"fn": "registered", "text": "😀 aaaaaa 😀😀 bbbbbb"},
        {"fn": "registered", "text": ""},
        {"fn": "registered", "text": "aaaaa bbbbb"},
        {"fn": "registered", "text": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    ],
    registry=["aaaaaa", "aaaaaaaa", "bbbbbb", "😀😀😀"],
)
scenario(
    "registry-empty-direct",
    [{"fn": "registered", "text": "aaaaaa"}, {"fn": "sensitiveText", "text": "aaaaaa token=abcdefghijklmnopq"}],
)
scenario(
    "registry-snapshot-isolated",
    [
        {"fn": "snapshot"},
        {"fn": "register", "value": "later-registered-secret"},
        {"fn": "snapshotRedact", "index": 0, "text": "first-registered-secret later-registered-secret"},
        {"fn": "sensitiveText", "text": "first-registered-secret later-registered-secret"},
        {"fn": "snapshot"},
        {"fn": "snapshotRedact", "index": 1, "text": "first-registered-secret later-registered-secret token=abcdefghijklmnopqrstu"},
        {"fn": "registryState"},
    ],
    registry=["first-registered-secret"],
)
scenario(
    "registry-then-default-patterns",
    [
        {"fn": "sensitiveText", "text": f"Authorization: Bearer {LONG}"},
        {"fn": "sensitiveText", "text": f"x token={LONG} y"},
        {"fn": "sensitiveText", "text": f"password={LONG}"},
        {"fn": "sensitiveText", "text": f"{LONG} then sk-abcdefghijklmnopqrstuvwxyz"},
        {"fn": "sensitiveText", "text": f"https://u:{LONG}@host/?access_token={LONG}"},
        {"fn": "sensitiveText", "text": f"MY_KEY={LONG}"},
        {"fn": "sensitiveText", "text": f"MY_KEY={LONG}", "mode": "off"},
        {"fn": "sensitiveText", "text": f"{LONG} token=abcdefghijklmnopqrstuvwxyz", "mode": "off"},
        {"fn": "sensitiveText", "text": f"-----BEGIN PRIVATE KEY-----\n{LONG}\n-----END PRIVATE KEY-----"},
    ],
    registry=[LONG],
)
scenario(
    "registry-in-pem-and-structured-text",
    [
        {"fn": "sensitiveText", "text": f"-----BEGIN PRIVATE KEY-----\n{LONG}\n-----END PRIVATE KEY-----"},
        {"fn": "sensitiveText", "text": f'{{"password": "{LONG}"}} and {LONG}'},
        {"fn": "sensitiveText", "text": f"a=1&token={LONG}&b=2"},
    ],
    registry=["PRIVATE KEY", LONG],
)
scenario(
    "registry-with-user-patterns",
    [
        {"fn": "sensitiveText", "text": f"{LONG} CUST-12345 CUST-12", "patterns": ["CUST-\\d+"]},
        {"fn": "sensitiveText", "text": f"{LONG} CUST-12345 CUST-12", "patterns": [{"matcher": "cust"}]},
        {"fn": "sensitiveText", "text": f"{LONG} token=abcdefghijklmnopqrstuvwxyz", "patterns": ["zzz"]},
        {"fn": "sensitiveText", "text": f"{LONG} token=abcdefghijklmnopqrstuvwxyz", "patterns": ["zzz"], "mode": "off"},
    ],
    registry=[LONG],
)
scenario(
    "registry-fields-and-structured",
    [
        {"fn": "field", "key": "note", "value": f"see {LONG} here"},
        {"fn": "field", "key": "password", "value": LONG},
        {"fn": "field", "key": "password", "value": "short"},
        {"fn": "field", "key": "name", "value": LONG},
        {"fn": "field", "key": "id", "value": LONG},
        {"fn": "modelVisibleField", "key": "note", "value": f"see {LONG} here"},
        {"fn": "modelVisibleField", "key": "token", "value": f"x {LONG}"},
        {"fn": "modelVisibleField", "key": "text", "value": "apple-pwdx-abcd-efgh"},
        {"fn": "modelVisibleField", "key": "text", "value": f"apple-pwdx-abcd-efgh {LONG}"},
        {"fn": "modelVisibleField", "key": "notes", "value": "short-secret!"},
        {"fn": "modelVisibleSecrets", "value": f"plain {LONG} text"},
        {"fn": "modelVisibleSecrets", "value": {"a": f"x {LONG}", "b": [f"{LONG}", "short-secret!"], "publicShare": {"id": LONG}}},
        {"fn": "modelVisibleSecrets", "value": {"publicShare": {"id": f"pre{LONG}"}, "n": 1, "t": True}},
        {"fn": "secrets", "value": {"a": f"x {LONG}", "token": "keep", "nested": {"password": f"{LONG}"}}},
        {"fn": "secrets", "value": f"s {LONG}"},
        {"fn": "secrets", "value": ""},
        {"fn": "secrets", "value": {}},
    ],
    registry=[LONG, "short-secret!"],
)
scenario(
    "registry-transcript",
    [
        {"fn": "transcriptText", "text": f"a {LONG} b"},
        {"fn": "transcriptText", "text": f"a {LONG} b", "modelVisible": True},
        {"fn": "transcriptField", "key": "next_page_token", "value": f"tok {LONG}"},
        {"fn": "transcriptField", "key": "page-cursor", "value": "abcdefghijklmnopqrstuvwxyz0123"},
        {"fn": "transcriptField", "key": "pageToken", "value": "abcdefghijklmnopqrstuvwxyz0123"},
        {"fn": "transcriptField", "key": "token", "value": "abcdefghijklmnopqrstuvwxyz0123"},
        {"fn": "transcriptField", "key": "token", "value": "abcdefghijklmnopqrstuvwxyz0123", "modelVisible": True},
        {"fn": "transcriptField", "key": "page_token", "value": "token=abcdefghijklmnopqrstuvwxyz0123", "modelVisible": True},
    ],
    registry=[LONG],
)

# --- (b) logging.redactPatterns ----------------------------------------------------------------------------
USER_TEXTS = [
    "CUST-12345678 and cust-9 plus Cust-1234567890123456789",
    "id=1234abcd5678 id: 4455-abc",
    "Foo foo FOO fooBar",
    f"token={LONG} and Bearer {LONG}",
    "plain text without anything",
    "line one\ntoken: abcdefghijklmnopqrstuvwxyz\nline three",
    'quoted "CUST-99999999999999999999" and \'CUST-1\'',
    "abc\nABC\naXc",
    "email john.doe+tag@example.com and x@y.org",
    f"AKIA{'A' * 16} {AWS_SECRET}",
    "",
]
PATTERN_CASES: list[tuple[str, list[str]]] = [
    ("bare-digits", ["CUST-\\d+"]),
    ("bare-is-case-insensitive", ["cust-\\d+"]),
    ("literal-keeps-flags-no-i", ["/cust-\\d+/"]),
    ("literal-i", ["/cust-\\d+/i"]),
    ("literal-capture", ["/foo(bar)/i"]),
    ("literal-multiline", ["/^token:\\s*(.+)$/m"]),
    ("literal-no-m-anchor", ["/^token:\\s*(.+)$/"]),
    ("literal-dotall", ["/a.c/s"]),
    ("literal-dot-no-s", ["/a.c/"]),
    ("literal-unicode-flag", ["/\\u{1F600}+/u"]),
    ("literal-sticky", ["/CUST-\\d+/y"]),
    ("literal-sticky-start", ["/abc\\n/y", "/^abc/y"]),
    ("literal-bad-flag-dup", ["/abc/ii"]),
    ("literal-gg-dup", ["/abc/gg"]),
    ("literal-d-flag-is-source", ["/abc/d"]),
    ("literal-slash-in-source", ["/a\\/b/", "/ab/c/"]),
    ("not-a-literal-leading-space", ["  /abc/i"]),
    ("whitespace-trimmed", ["   CUST-\\d+   "]),
    ("blank-skipped", ["", "   ", "\t", "CUST-\\d+"]),
    ("only-blank", ["", " "]),
    ("empty-list-is-default", []),
    ("unsafe-nested", ["(a+)+b", "CUST-\\d+"]),
    ("unsafe-nested-class", ["(\\w+\\s?)*$", "(x*)*y"]),
    ("unsafe-alternation", ["(a|aa)+b", "(a|b)*c", "(ab|a)+"]),
    ("safe-groups", ["(ab)+c", "(a|b)c+", "(?:ab){2,3}"]),
    ("invalid", ["([", "*a", "a{2,1}", "[b-a]", "CUST-\\d+"]),
    ("invalid-and-valid-mixed", ["(", "foo(bar)", ")"]),
    ("shorthand-classes", ["\\d{3}-\\d{2}-\\d{4}", "\\bcust\\b", "\\W+x", "\\S+@\\S+"]),
    ("word-boundaries", ["\\bfoo\\b", "\\Bar\\b", "\\b"]),
    ("email", ["[\\w.+-]+@[\\w-]+\\.[\\w.]+"]),
    ("alternation", ["(foo|bar)baz", "FOO|ABC"]),
    ("named-groups", ["(?<n>\\w+)@(?<d>\\w+)\\.org", "\\k<n>"]),
    ("backreference", ["/(a)\\1/", "/(?<x>b)\\k<x>/", "(.)\\1"]),
    ("octal-escape", ["\\101BC", "a\\0b", "\\1"]),
    ("hex-unicode-escapes", ["\\x43UST", "\\u0043UST-\\d", "\\cJ"]),
    ("lookahead", ["CUST(?=-\\d{5})", "id(?!:)", "(?=id)id"]),
    ("lookbehind-fixed", ["(?<=id=)[0-9a-f]{6,}", "(?<!x)CUST"]),
    ("lookbehind-variable", ["(?<=id=|ide=)[0-9a-f]{6,}", "(?<!a|bc)x", "(?<=(id)=|ide=)\\d+"]),
    ("empty-match", ["x*"]),
    ("empty-match-anchor", ["^", "$"]),
    ("empty-match-alt", ["|"]),
    ("lazy-quantifier", ["CUST-\\d+?-?", "a{1,2}?b"]),
    ("literal-braces-nonunicode", ["a{", "a{x}", "{2}x", "a{,3}", "x}y", "x]y"]),
    ("char-class-edge", ["[^]", "[]", "[a-]", "[-a]", "[\\d-x]", "[a-\\d]", "[\\]x]", "[\\b]", "[\\w-]"]),
    ("char-class-negated-escape", ["[\\D]x", "[\\W]y", "[^\\d]3", "[\\S]x", "[^\\S]x", "/[\\W\\d]/u", "[\\s\\S]+?"]),
    ("case-insensitive-non-ascii", ["/ünï(c)ode/i", "ÉCOLE"]),
    ("case-insensitive-u", ["/ünï(c)ode/iu", "/\\w+@/iu"]),
    ("multiline-dollar", ["/ONE$/m", "/^line/m", "/three$/m"]),
    ("secret-last-capture", ["id:\\s*(\\d{4,})-(\\w+)", "(key)=(?:(\\w+))?"]),
    ("secret-quoted", ["\"secret\":\\s*(\"[^\"]+\")", "'(CUST-\\d+)'"]),
    ("match-star-masked", ["\\*\\*\\*", "(\\*{3})"]),
    ("long-token-hint", ["[A-Za-z0-9]{30,}", "(?:token=)(\\S+)"]),
    ("equals-default-source", ["\\bBearer\\s+([-A-Za-z0-9._~+/=]{18,})(?![-A-Za-z0-9._~+/=])"]),
    ("pem-source-string", ["-----BEGIN [A-Z ]*PRIVATE KEY-----[\\s\\S]+?-----END [A-Z ]*PRIVATE KEY-----"]),
    ("chunk-unsafe-prefix", ["(^|[^A-Za-z0-9_])tok_\\w{6,}", "(^|[^A-Za-z0-9])zz\\w+"]),
    ("matcher-cust", [{"matcher": "cust"}]),
    ("matcher-whole-and-string", [{"matcher": "whole"}, "CUST-\\d+"]),
    ("matcher-aws-explicit", [{"matcher": "aws"}, "CUST-\\d+"]),
    ("matcher-before-aws", ["CUST-\\d+", {"matcher": "aws"}]),
    ("string-then-matcher-dedupe", [{"matcher": "cust"}, {"matcher": "cust"}]),
    ("default-string-subset", ["\\bsk-[A-Za-z0-9_-]{8,}\\b", "ghp_[A-Za-z0-9]{20,}"]),
]
MATCHER_TEXTS = [
    "CUST-12 CUST-1234 CUST-12345678 ZZ123 ZZ12345",
    "😀 CUST-1234 😀😀 ZZ1234 CUST-9",
]
EXTRA_TEXTS = [
    "😀😀😀 CUST-12345678 😀",
    "ünï(c)ode UNÏCODE ÜNÏCODE école ÉCOLE",
    "line1\r\nONE\nlineTWO\rthree line three",
    "a{ a{x} {2}x a{,3} x}y x]y",
    "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----",
    "tok_abcdef123 xtok_abcdef123 zzabc ;base64,zzabc zzabc",
    '"secret": "super-secret-value" \'CUST-5\'',
    "*** ***x",
    "abcabc aXbXc (a)(a) aabb bb",
]
for _name, _patterns in PATTERN_CASES:
    scenario(
        f"patterns-{_name}",
        [
            {"fn": "compile", "pattern": p} for p in _patterns if isinstance(p, str)
        ]
        + [
            {"fn": "sensitiveText", "text": text, "patterns": _patterns}
            for text in USER_TEXTS + EXTRA_TEXTS + MATCHER_TEXTS
        ],
    )
    scenario(
        f"patterns-file-config-{_name}",
        [
            {"fn": "sensitiveTextConfig", "text": text}
            for text in USER_TEXTS[:6] + EXTRA_TEXTS[:3]
        ]
        + [{"fn": "toolPayloadHost", "text": text} for text in USER_TEXTS[:6] + EXTRA_TEXTS[:3]],
        fileConfig={"redactPatterns": [p for p in _patterns if isinstance(p, str)]},
    )
scenario(
    "patterns-mode-off",
    [
        {"fn": "sensitiveText", "text": f"CUST-1234 token={LONG}", "patterns": ["CUST-\\d+"], "mode": "off"},
        {"fn": "sensitiveText", "text": f"CUST-1234 token={LONG}", "mode": "off"},
        {"fn": "sensitiveText", "text": f"CUST-1234 token={LONG}", "mode": "weird"},
        {"fn": "sensitiveText", "text": f"CUST-1234 token={LONG}", "mode": "tools"},
    ],
)
scenario(
    "patterns-keep-structural-protections",
    [
        {"fn": "sensitiveText", "text": f"https://x.test/?access_token={LONG}&x=1", "patterns": ["zzzz"]},
        {"fn": "sensitiveText", "text": f"a=1&password={LONG}&b=2", "patterns": ["zzzz"]},
        {"fn": "sensitiveText", "text": f"Authorization: Bearer {LONG}", "patterns": ["zzzz"]},
        {"fn": "sensitiveText", "text": f"aws_secret_access_key = {AWS_SECRET}", "patterns": ["zzzz"]},
        {"fn": "sensitiveText", "text": f"{AWS_SECRET}", "patterns": ["zzzz"]},
        {"fn": "sensitiveText", "text": f"sk-abcdefghijklmnopqrstuvwxyz token={LONG}", "patterns": ["zzzz"]},
        {"fn": "sensitiveText", "text": f"sk-abcdefghijklmnopqrstuvwxyz token={LONG}", "patterns": []},
    ],
)
scenario(
    "patterns-config-reading-defaults",
    [
        {"fn": "sensitiveTextConfig", "text": f"CUST-1234 token={LONG} sk-abcdefghijklmnopqrstuvwxyz"},
        {"fn": "toolPayloadHost", "text": f"CUST-1234 token={LONG} sk-abcdefghijklmnopqrstuvwxyz"},
        {"fn": "secrets", "value": {"a": "CUST-1234", "token": "keep-me-plain", "n": f"token={LONG}"}},
        {"fn": "modelVisibleSecrets", "value": {"a": "CUST-1234", "token": "keep-me-plain", "n": f"token={LONG}"}},
        {"fn": "modelVisibleSecrets", "value": "CUST-1234 SECRET_KEY=abcdefghijklmnopqrstuvwx"},
    ],
    fileConfig={"redactPatterns": ["CUST-\\d+"]},
)
scenario(
    "patterns-config-empty-block",
    [
        {"fn": "sensitiveTextConfig", "text": f"CUST-1234 token={LONG}"},
        {"fn": "toolPayloadHost", "text": f"CUST-1234 token={LONG}"},
    ],
    fileConfig={"redactPatterns": []},
)
scenario(
    "patterns-config-all-invalid",
    [
        {"fn": "sensitiveTextConfig", "text": f"CUST-1234 token={LONG} sk-abcdefghijklmnopqrstuvwxyz"},
        {"fn": "toolPayloadHost", "text": f"CUST-1234 token={LONG} sk-abcdefghijklmnopqrstuvwxyz"},
    ],
    fileConfig={"redactPatterns": ["(a+)+$", "(["]},
)
scenario(
    "patterns-no-config-file",
    [
        {"fn": "sensitiveTextConfig", "text": f"CUST-1234 token={LONG} sk-abcdefghijklmnopqrstuvwxyz"},
        {"fn": "toolPayloadHost", "text": f"CUST-1234 token={LONG} sk-abcdefghijklmnopqrstuvwxyz"},
    ],
)
scenario(
    "patterns-big-text-chunking",
    [
        {"fn": "sensitiveText", "text": BIG[:32_760] + "CUST-1234 " + BIG[:200] + "CUST-5678", "patterns": ["CUST-\\d+"]},
        {"fn": "sensitiveText", "text": BIG[:32_765] + "CUST-1234", "patterns": ["CUST-\\d+"]},
        {"fn": "sensitiveText", "text": BIG[:16_380] + "CUST-1234", "patterns": ["CUST-\\d+"]},
        {"fn": "sensitiveText", "text": BIG[:16_380] + "CUST-1234" + BIG, "patterns": ["CUST-\\d+"]},
        {"fn": "sensitiveText", "text": BIG[:16_380] + "CUST-1234" + BIG, "patterns": ["(^|[^A-Za-z0-9_])CUST-\\d+"]},
        {"fn": "sensitiveText", "text": BIG[:16_380] + "CUST-1234" + BIG, "patterns": ["/^zzz/"]},
        {"fn": "sensitiveText", "text": BIG[:16_380] + "CUST-1234" + BIG, "patterns": ["/CUST-\\d+/y"]},
        {"fn": "sensitiveText", "text": ("😀" * 17_000) + "CUST-1234", "patterns": ["/CUST-\\d+/u", "😀+"]},
        {"fn": "sensitiveText", "text": ("😀" * 17_000) + "CUST-1234", "patterns": ["/😀{2}/u"]},
        {"fn": "sensitiveText", "text": ("😀" * 17_000) + "CUST-1234", "patterns": ["😀{2}"]},
    ],
)

# --- (c) policies: tool payload, model visible, full context ----------------------------------------------------
POLICY_TEXTS = [
    f"password={LONG} CUST-1234 sk-abcdefghijklmnopqrstuvwxyz",
    f"const apiKey = process.env.API_KEY; MY_TOKEN={LONG}",
    f"Authorization: Bearer {LONG}",
    f'{{"apiKey": "{LONG}", "name": "x"}}',
    f"hello {LONG}",
    "just text with CUST-1234 only",
    f"sk_{'a' * 24} xam_{'b' * 20} JWT={LONG}",
    f"-----BEGIN PRIVATE KEY-----\n{LONG}\n-----END PRIVATE KEY-----",
    f"{AWS_SECRET} aws_secret_access_key={AWS_SECRET}",
    "123456789:" + "A" * 30 + " bot123456789:" + "B" * 30,
    "x1234567:" + "A" * 30,
    "BEGIN\n-----BEGIN RSA PRIVATE KEY-----\n" + LONG + "\n-----END RSA PRIVATE KEY-----\nEND",
    "",
]
POLICY_CONFIGS = [
    ("none", None),
    ("empty", {"redactPatterns": []}),
    ("cust", {"redactPatterns": ["CUST-\\d+"]}),
    ("cust-and-unsafe", {"redactPatterns": ["(a+)+b", "CUST-\\d+", "(["]}),
    ("case-i", {"redactPatterns": ["/hello (\\w+)/"]}),
]
for _cname, _config in POLICY_CONFIGS:
    for _full in (False, True):
        scenario(
            f"policy-{_cname}-{'full' if _full else 'plain'}",
            [{"fn": "toolPayload", "text": text} for text in POLICY_TEXTS]
            + [{"fn": "modelVisibleText", "text": text} for text in POLICY_TEXTS]
            + [
                {"fn": "field", "key": key, "value": value}
                for key in ("note", "token", "password", "text", "MY_API_KEY")
                for value in POLICY_TEXTS[:6]
            ]
            + [
                {"fn": "modelVisibleField", "key": key, "value": value}
                for key in ("note", "token", "password", "text", "MY_API_KEY")
                for value in POLICY_TEXTS[:6]
            ],
            config=_config,
            fullContext=_full,
            registry=["registered-secret-xyz"],
        )
scenario(
    "policy-full-context-big-text",
    [
        {"fn": "toolPayload", "text": BIG[:32_760] + f"sk-{'a' * 30}" + BIG[:100]},
        {"fn": "toolPayload", "text": BIG[:16_380] + f"sk-{'a' * 30}" + BIG[:16_000] + f"password={LONG}"},
        {"fn": "toolPayload", "text": BIG[:16_380] + "CUST-1234" + BIG},
        {"fn": "modelVisibleText", "text": BIG[:16_380] + f"sk-{'a' * 30}" + BIG},
        {"fn": "modelVisibleText", "text": BIG[:16_380] + f"ghp_{'a' * 36}" + BIG[:20] + f"ghp_{'b' * 36}"},
        {"fn": "toolPayload", "text": "x" * 20_000 + "\n" + "token=" + "a" * 40 + "x" * 20_000 + "\n" + "token=" + "b" * 40},
    ],
    config={"redactPatterns": ["CUST-\\d+"]},
    fullContext=True,
)
scenario(
    "policy-full-context-big-text-plain",
    [
        {"fn": "toolPayload", "text": BIG[:32_760] + f"sk-{'a' * 30}" + BIG[:100]},
        {"fn": "toolPayload", "text": BIG[:16_380] + f"sk-{'a' * 30}" + BIG[:16_000] + f"password={LONG}"},
        {"fn": "toolPayload", "text": BIG[:16_380] + "CUST-1234" + BIG},
        {"fn": "modelVisibleText", "text": BIG[:16_380] + f"sk-{'a' * 30}" + BIG},
        {"fn": "modelVisibleText", "text": BIG[:16_380] + f"ghp_{'a' * 36}" + BIG[:20] + f"ghp_{'b' * 36}"},
        {"fn": "toolPayload", "text": "x" * 20_000 + "\n" + "token=" + "a" * 40 + "x" * 20_000 + "\n" + "token=" + "b" * 40},
    ],
    config={"redactPatterns": ["CUST-\\d+"]},
)
scenario(
    "policy-full-context-skips-prefilter",
    [
        {"fn": "toolPayload", "text": text}
        for text in [
            "JWT=abcdefghijklmnopqrstuvwxyz",
            "am_abcdefghijklmnop",
            "sk_abcdefghijklmnop",
            "xsk_abcdefghijklmnop",
            "999999:AAAAAAAAAAAAAAAAAAAAAAAA",
            "Bearer abcdefghijklmnopqrstuvwxyz",
            "bearer   abcdefghijklmnopqrstuvwxyz",
            "ſk-abcdefghijklmnopqrstuvwxyz",
            "KEY=abcdefghijklmnopqrstuvwxyz",
        ]
    ],
    fullContext=True,
)
scenario(
    "policy-with-registry-and-public-share",
    [
        {"fn": "field", "key": "id", "value": "plain-id-value-1234567890"},
        {"fn": "modelVisibleField", "key": "note", "value": "x registered-secret-xyz y"},
        {"fn": "toolPayload", "text": "x registered-secret-xyz y"},
        {"fn": "modelVisibleText", "text": "x registered-secret-xyz y"},
    ],
    registry=["registered-secret-xyz"],
    fullContext=True,
)
scenario(
    "transcript-config",
    [
        {"fn": "transcriptText", "text": f"CUST-1234 sk-abcdefghijklmnopqrstuvwxyz token={LONG}", "cfg": {"logging": {"redactPatterns": ["CUST-\\d+"]}}},
        {"fn": "transcriptText", "text": f"CUST-1234 sk-abcdefghijklmnopqrstuvwxyz token={LONG}", "cfg": {"logging": {"redactPatterns": ["CUST-\\d+"]}}, "modelVisible": True},
        {"fn": "transcriptText", "text": f"CUST-1234 HOST-77 token={LONG}", "cfg": {"logging": {"redactPatterns": []}}},
        {"fn": "transcriptText", "text": f"CUST-1234 HOST-77 token={LONG}", "cfg": {}},
        {"fn": "transcriptText", "text": f"CUST-1234 HOST-77 token={LONG}"},
        {"fn": "transcriptField", "key": "password", "value": "CUST-1234 hunter2hunter2", "cfg": {"logging": {"redactPatterns": ["CUST-\\d+"]}}},
        {"fn": "transcriptField", "key": "password", "value": "CUST-1234 hunter2hunter2", "cfg": {"logging": {"redactPatterns": ["CUST-\\d+"]}}, "modelVisible": True},
        {"fn": "transcriptField", "key": "next_page_token", "value": "CUST-1234 abcdefghijklmnopqrstuvwxyz", "cfg": {"logging": {"redactPatterns": ["CUST-\\d+"]}}},
        {"fn": "transcriptField", "key": "page_cursor", "value": f"token={LONG}", "modelVisible": True},
        {"fn": "transcriptField", "key": "pagetoken", "value": f"token={LONG}"},
        {"fn": "transcriptField", "key": "Page-Token", "value": "HOST-77"},
    ],
    fileConfig={"redactPatterns": ["HOST-\\d+"]},
)
scenario(
    "policy-structured-with-user-patterns",
    [
        {"fn": "secrets", "value": {"a": "CUST-1234 hello", "token": "plain-token-value", "list": ["CUST-5", {"password": "x"}], "n": 5, "k": True}},
        {"fn": "modelVisibleSecrets", "value": {"a": "CUST-1234 hello", "token": "plain-token-value", "list": ["CUST-5", {"password": "x"}], "n": 5, "k": True, "code": 5}},
        {"fn": "modelVisibleSecrets", "value": {"MY_SECRET": "CUST-1234", "session": "$WORKSPACE_DIR/a.jsonl", "text": "aaaa-bbbb-cccc-dddd CUST-12"}},
        {"fn": "secrets", "value": {"MY_SECRET": "CUST-1234", "session": "$WORKSPACE_DIR/a.jsonl", "text": "aaaa-bbbb-cccc-dddd CUST-12"}},
    ],
    fileConfig={"redactPatterns": ["CUST-\\d+"]},
)


# --- computeSensitiveRedactionBitmap: where redaction would replace a unit ------------------------------------
def _bitmap_texts() -> list[str]:
    from test_redact_oracle import FIXTURES, _fuzz_texts

    return [text for _, text in FIXTURES if len(text) < 5000] + _fuzz_texts(41, 400, 14)


_BITMAP_TEXTS = _bitmap_texts()
scenario(
    "bitmap-default-patterns",
    [{"fn": "bitmap", "text": text} for text in _BITMAP_TEXTS],
)
scenario(
    "bitmap-user-patterns",
    [
        {"fn": "bitmap", "text": text, "patterns": patterns}
        for patterns in (["CUST-\\d+", "/foo(bar)/i", "/\\u{1F600}+/u"], [{"matcher": "cust"}, "x*"], [])
        for text in USER_TEXTS + EXTRA_TEXTS + MATCHER_TEXTS
    ]
    + [{"fn": "bitmap", "text": text, "mode": "off"} for text in USER_TEXTS[:3]],
)


@functools.cache
def _fixed_oracle() -> list[dict]:
    return oracle_run([scn for _, scn in SCENARIOS])


def test_scenario_names_are_unique():
    names = [name for name, _ in SCENARIOS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("index", range(len(SCENARIOS)), ids=[name for name, _ in SCENARIOS])
def test_scenario_matches_upstream(index: int):
    _, scn = SCENARIOS[index]
    bad = compare(scn, _fixed_oracle()[index])
    assert not bad, bad[:3]


# Valid JavaScript this port reports as unsupported (dropped like an invalid entry), see
# docs/gap6-redaction-notes.md.
UNSUPPORTED = ["(?<n>a)|(?<n>b)", "(?<=;base64,[A-Za-z0-9+/=]*)zz", "/\\p{L}+/u", "/\\P{Lu}/u", "(?<=a+)b", "(?<!\\d{1,3})x", "a{99999999999}"]


def test_unsupported_syntax_is_reported_not_guessed():
    from memory_core.redact_user_patterns import compile_redact_pattern

    steps = [{"fn": "compile", "pattern": pattern} for pattern in UNSUPPORTED]
    [out] = oracle_run([{"steps": steps}])
    for pattern, result in zip(UNSUPPORTED, out["steps"], strict=True):
        assert result["value"]["reason"] is None, pattern  # JavaScript accepts it
        compiled = compile_redact_pattern(pattern)
        assert compiled is not None and compiled.reason == "unsupported-syntax", pattern


def test_scenarios_exercise_redaction():
    # A scenario set that never changes a text would pass for an identity port.
    changed = 0
    total = 0
    for (_name, scn), out in zip(SCENARIOS, _fixed_oracle(), strict=True):
        for step, result in zip(scn["steps"], out["steps"], strict=True):
            if "text" in step and isinstance(result.get("value"), str):
                total += 1
                changed += result["value"] != step["text"]
    assert total > 1500 and changed > total // 4, (changed, total)


# --- generated -------------------------------------------------------------------------------------------------
_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./+= "
_FRAGMENTS = [
    "token=", "password: ", "Authorization: Bearer ", "sk-", "ghp_", "&", "?", "=", ":", " ", "\n", "\"", "'", "CUST-", "id=",
    "ZZ", "😀", "é", "%20", "\\n", "\\\"", "@example.com", "foo", "bar", "\r\n", "api_key=", "PRIVATE KEY", "xoxb-",
]
_USER_PATTERN_POOL = [
    "CUST-\\d+", "/foo(bar)/i", "\\bsecret\\w*\\b", "(?<=id=)[0-9a-f]{6,}", "id:\\s*(\\d{4,})-(\\w+)", "/^token:\\s*(.+)$/m",
    "/a.c/s", "/ünï(c)ode/iu", "[A-Z]{3}-\\d{3}", "x*", "(foo|bar)baz", "\\d{3}-\\d{2}-\\d{4}", "(?:key|pass)=([^&\\s]+)",
    "/(a)\\1/", "[\\w.+-]+@[\\w-]+\\.[\\w.]+", "^foo", "bar$", "/\\bfoo\\b/y", "(a+)+b", "([", "", "  ", "é+", "😀+", "/😀{1,2}/u",
    "/\\u{1F600}/u", "(ab|a)+", "ZZ\\d{3,}", "(?<n>\\w)\\k<n>", "\\bsk-[A-Za-z0-9]{8,}", "=([^&\\s]{4,})", "[^\\s]{20,}",
]


def _random_text(rnd: random.Random, secrets: list[str], max_parts: int) -> str:
    def word() -> str:
        return "".join(rnd.choice(_ALPHABET) for _ in range(rnd.choice([3, 8, 12, 17, 18, 19, 24, 40])))

    parts = []
    for _ in range(rnd.randint(1, max_parts)):
        roll = rnd.random()
        if roll < 0.3:
            parts.append(word())
        elif roll < 0.45 and secrets:
            parts.append(rnd.choice(secrets))
        else:
            parts.append(rnd.choice(_FRAGMENTS))
    return "".join(parts)


def _random_scenario(rnd: random.Random) -> dict:
    secrets = []
    if rnd.random() < 0.7:
        for _ in range(rnd.randint(1, 6)):
            kind = rnd.random()
            value = "".join(rnd.choice(_ALPHABET) for _ in range(rnd.choice([3, 6, 7, 12, 17, 18, 19, 30])))
            if kind < 0.2:
                value = rnd.choice(["é", "😀", " ", "\"", "\\", "/", "&", "\n"]) + value
            elif kind < 0.3:
                value = value[:4] + rnd.choice(["%", "+", "😀😀", "\t"]) + value[4:]
            secrets.append(value)
    patterns = rnd.sample(_USER_PATTERN_POOL, rnd.randint(0, 4))
    config = {"redactPatterns": patterns} if rnd.random() < 0.5 else None
    steps: list[dict] = []
    for _ in range(rnd.randint(2, 6)):
        text = _random_text(rnd, secrets, 14)
        fn = rnd.choice(["sensitiveText", "toolPayload", "modelVisibleText", "field", "modelVisibleField", "secrets", "modelVisibleSecrets"])
        if fn == "sensitiveText":
            steps.append({"fn": fn, "text": text, "patterns": patterns if patterns and rnd.random() < 0.8 else None, "mode": rnd.choice(["tools", "tools", "off"])})
        elif fn in ("toolPayload", "modelVisibleText"):
            steps.append({"fn": fn, "text": text})
        elif fn in ("field", "modelVisibleField"):
            steps.append({"fn": fn, "key": rnd.choice(["note", "token", "password", "text", "id", "API_KEY", "name"]), "value": text})
        else:
            steps.append({"fn": fn, "value": {rnd.choice(["a", "token", "text", "list"]): [text, _random_text(rnd, secrets, 5)] if rnd.random() < 0.4 else text}})
    return {
        "steps": steps,
        "registry": secrets,
        "config": config,
        "fullContext": rnd.random() < 0.4,
        "fileConfig": {"redactPatterns": patterns} if patterns and rnd.random() < 0.5 else None,
    }


@pytest.mark.parametrize("seed,count", [(21, 450), (22, 450)])
def test_generated_scenarios_match_upstream(seed: int, count: int):
    rnd = random.Random(seed)
    scenarios = [_random_scenario(rnd) for _ in range(count)]
    wants = oracle_run(scenarios)
    mismatches = []
    changed = 0
    for scn, want in zip(scenarios, wants, strict=True):
        bad = compare(scn, want)
        if bad:
            mismatches.append((scn["registry"], scn["config"], scn["fileConfig"], scn["fullContext"], bad[:2]))
        for step, result in zip(scn["steps"], want["steps"], strict=True):
            changed += result.get("value") != step.get("text", step.get("value"))
    assert not mismatches, (len(mismatches), mismatches[:2])
    assert changed > count
