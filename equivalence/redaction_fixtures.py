"""Fixed synthetic inputs for ordinary default redaction comparisons.

These builders contain literal caller instructions, never expected results.
Known engine and raw-input identity differences remain ordinary catalog cases.
"""
from copy import deepcopy


def _source_literals() -> list[dict]:
    text = " " * 16380 + "CUST-1234567890" + " " * 20000
    result = []

    def add(name, text, *, patterns=None, full_context=False, mode="tools", secrets=(), value=None):
        result.append({"id": name, "covers": [], "input": {
            "text": text, "fullContext": full_context, "mode": mode,
            **({"patterns": patterns} if patterns is not None else {}),
            "registeredSecrets": list(secrets),
            "value": value if value is not None else {"ordinary": text, "token": "fixture-value", "count": 7},
            "message": {"role": "toolResult", "toolCallId": "fixture-call", "toolName": "lookup",
                        "content": [{"type": "text", "text": text}], "details": {"token": "fixture-value"},
                        "timestamp": 1000},
        }})

    add("bounded-over-32768-cross-16384", text, patterns=["CUST-[0-9]+"])
    add("host-full-context-cross-16384", text, patterns=["CUST-[0-9]+"], full_context=True, mode="off")
    add("exact-32768-utf16", "😀" * 8190 + "CUST-1234567890" + " " * 16373, patterns=["CUST-[0-9]+"])
    add("over-32768-utf16", "😀" * 8190 + "CUST-1234567890" + " " * 16374, patterns=["CUST-[0-9]+"])
    add("default-literal-url-structured", 'Authorization: Bearer fixture-secret-value https://fixture.invalid/?access_token=fixture-token',
        value={"credentials": {"apiKey": 7, "password": False}, "authorization": "Bearer fixture-secret-value", "public": "ok"})
    add("registered-uri-json-off", 'raw pa"ss\\word+fixture URI pa%22ss%5Cword%2Bfixture JSON pa\\"ss\\\\word+fixture',
        secrets=['pa"ss\\word+fixture'], mode="off")
    add("mode-off-disables-patterns-only", "CUST-1234567890 registered-fixture", patterns=["CUST-[0-9]+"],
        mode="off", secrets=["registered-fixture"])
    add("configured-replaces-sensitive-merges-tool", "CUST-1234567890 token=fixture-token", patterns=["CUST-[0-9]+"])
    add("invalid-and-unsafe-rules-skip", "CUST-1234567890 abcdef token=fixture-token", patterns=["[", "/x/qq", "(a+)+$", "CUST-[0-9]+"])
    add("flags-capture-lookbehind", "PREFIX CUST-1234567890\nref: AB12\nref: cd34", patterns=["/(CUST-)([0-9]+)/gi", "/(?<=ref: )[a-z0-9]+/gim"])
    add("sticky-dotall-lookahead", "BEGIN\nsecret END SECRET", patterns=["/BEGIN.*?END/gs", "/SECRET(?=$)/y"])
    add("non-idempotent-stages", "foo ***", patterns=[r"foo|\*"])
    # These are supported by the real JS engine. They must stay visible even
    # when the Python regex implementation cannot compile their semantics.
    add("valid-js-unicode-property", "AAA ééé token=fixture-token", patterns=[r"/\p{L}+/gu"])
    add("valid-js-v-set-intersection", "ABC abc 123", patterns=[r"/[\p{ASCII}&&\p{Letter}]+/gv"])
    add("inline-image-whitespace-wrong-mime", "image result", value={"ordinary": "image result"})
    result[-1]["input"]["message"]["content"].extend([
        {"type": "image", "data": "iVBORw0KGgo=\n", "mimeType": "image/JPEG"},
        {"type": "base64", "data": "iVBORw0KGgo=\n", "mediaType": " image/GIF ", "media_type": "image/jpeg"},
        {"type": "image_url", "image_url": {"url": "DATA:image/jpeg;base64,iVBORw0KGgo=\n"}},
    ])
    for count in (8, 9, 22):
        add(f"unicode-literal-hint-{count}-astral", "prefix:" + "𐐀" * count,
            patterns=["/(prefix:)(𐐀+)/gu"])
    add("unicode-literal-odd-hint-boundaries", "prefix:a" + "𐐀" * 8 + "b", patterns=["/(prefix:)(a𐐀+b)/gu"])
    add("unicode-literal-lone-surrogate", "prefix:" + "\ud800" * 22, patterns=[r"/(prefix:)(\ud800+)/gu"])
    add("nonunicode-literal-astral-hint", "prefix:" + "𐐀" * 22, patterns=["/(prefix:)((?:𐐀)+)/g"])
    for alias in ("L", "Letter", "gc=L", "gc=Letter", "General_Category=L", "General_Category=Letter"):
        add("letter-alias-" + alias.replace("=", "-"), "CUST:" + "𐐀" * 22 + " end", patterns=[rf"/(CUST:)(\p{{{alias}}}+)/gu"])
    add("letter-complement-before-fold", "REF:ι REF:123", patterns=[r"/(REF:)(\P{Letter}+)/giu"])
    add("letter-class-and-outer-negation", "REF:Ab_19 REF:123", patterns=[r"/(REF:)([\p{L}0-9_]+)/giu", r"/(REF:)([^\p{Letter}]+)/gu"])
    add("letter-invalid-range-stays-invalid", "REF:a REF:z", patterns=[r"/(REF:)([a-\p{L}]+)/gu"])
    result[-1]["input"]["directRegex"] = {"source": r"[a-\p{L}]", "flags": "gu"}
    add("letter-mixed-i-engine-diagnostic", "aİ aı aI ai", patterns=[r"/\p{L}i/giu"])
    add("letter-repeated-capture-engine-diagnostic", "a1", patterns=[r"/(?:(\d)|(\p{L})){2}/gu"])
    add("unsupported-valid-general-property", "AAA aaa", patterns=[r"/\p{Lu}+/gu"])
    add("unsupported-valid-v-direct-compiler", "ABC abc 123")
    result[-1]["input"]["directRegex"] = {"source": r"[\p{ASCII}&&\p{Letter}]+", "flags": "gv"}
    return result


def _helper_literals() -> list[dict]:
    return [
        {"id": "complete-tool-result", "input": {"value": {
            "content": [{"type": "text", "text": "Authorization: Bearer fixture-secret-value"},
                        {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"}],
            "details": {"token": "fixture-secret", "nested": {"apiKey": 7}}, "extra": [None, False]}}},
        {"id": "utf16-redaction-truncation-order", "input": {"value": {"content": [
            {"type": "text", "text": "a" * 7999 + "😀 token=abcdefghijklmnopqrstuvwxyz"}]}}},
        {"id": "prepared-nonidempotent-storage", "input": {
            "patterns": [r"foo|\*"], "block": {"type": "text", "text": "foo"},
            "message": {"role": "toolResult", "toolCallId": "call-1", "toolName": "demo", "timestamp": 1}}},
        {"id": "prepared-cloned-block-storage", "input": {
            "patterns": [r"foo|\*"], "block": {"type": "text", "text": "foo", "note": "foo"},
            "message": {"role": "toolResult", "toolCallId": "call-2", "timestamp": 1}}},
        {"id": "prepared-registry-invalidation-storage", "input": {
            "block": {"type": "text", "text": "later-credential"}, "laterRegisteredSecrets": ["later-credential"],
            "message": {"role": "toolResult", "toolCallId": "call-3", "timestamp": 1}}},
        {"id": "prepared-text-mutation-storage", "input": {
            "patterns": [r"foo|\*"], "block": {"type": "text", "text": "foo"}, "replacePreparedText": "foo",
            "message": {"role": "toolResult", "toolCallId": "call-4", "timestamp": 1}}},
    ]


def _session_literals() -> list[dict]:
    model = {"id": "test-model", "name": "Test Model", "api": "openai-responses", "provider": "test-provider",
             "baseUrl": "https://example.invalid", "reasoning": False, "input": ["text"],
             "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}, "contextWindow": 200000, "maxTokens": 8192}

    def response(content, reason, turn):
        return {"role": "assistant", "content": content, "api": model["api"], "provider": model["provider"],
                "model": model["id"], "usage": {"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0,
                    "totalTokens": 2, "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}},
                "stopReason": reason, "timestamp": 1000, "turnId": turn}

    seed = {"sessionId": "redaction-fixture", "sessionKey": "agent:main:dm:redaction-fixture", "nowMs": 1000,
            "systemPrompt": "Use lookup when asked.", "model": model,
            "writePrompt": "Run lookup.", "continuePrompt": "What did lookup return?",
            "writeResponses": [response([{"type": "toolCall", "id": "call-1", "name": "lookup", "arguments": {"query": "request"}}],
                "toolUse", "00000000-0000-7000-8000-000000000001"),
                response([{"type": "text", "text": "done"}], "stop", "00000000-0000-7000-8000-000000000001")],
            "continueResponses": [response([{"type": "text", "text": "remembered"}], "stop", "00000000-0000-7000-8000-000000000002")]}
    fixtures = [
        ("guarded-nonidempotent-order", {"content": [{"type": "text", "text": "foo"}], "details": {"token": "fixture-secret"}}, {"patterns": [r"foo|\*"]}),
        ("literal-uri-json-structured", {"content": [{"type": "text", "text": 'Authorization: Bearer fixture-secret-value https://fixture.invalid/?access_token=fixture-token'}],
         "details": {"credentials": {"apiKey": 7, "password": False}, "ordinary": "ok"}}, {}),
        ("registered-encoded-forms", {"content": [{"type": "text", "text": 'raw pa"ss\\word+fixture URI pa%22ss%5Cword%2Bfixture JSON pa\\"ss\\\\word+fixture'}],
         "details": {"note": 'pa"ss\\word+fixture'}}, {"registeredSecrets": ['pa"ss\\word+fixture'], "modeProbe": 'pa"ss\\word+fixture token=fixture-token'}),
        ("utf16-bound-and-persisted-details", {"content": [{"type": "text", "text": "😀" * 8190 + "CUST-1234567890" + " " * 16374}],
         "details": {"status": "complete", "log": " token=" + "z" * 40000, "sessions": [{"sessionId": f"session-{i}"} for i in range(12)]}},
         {"patterns": ["CUST-[0-9]+"]}),
        ("invalid-patterns-and-late-registration", {"content": [{"type": "text", "text": "CUST-1234567890 later-fixture-secret"}],
         "details": {"note": "later-fixture-secret"}}, {"patterns": ["[", "/x/qq", "(a+)+$", "CUST-[0-9]+"], "lateRegisteredSecret": "later-fixture-secret"}),
        ("image-record-and-url-canonicalization", {"content": [
            {"type": "image", "data": "iVBORw0KGgo=\n", "mimeType": "image/JPEG"},
            {"type": "image_url", "image_url": {"url": "DATA:image/jpeg;base64,iVBORw0KGgo=\n"}},
        ], "details": {"status": "complete"}}, {}),
        ("ordinary-prototype-key", {"content": [{"type": "text", "text": "complete"}], "details": {"__proto__": "literal", "password": "fixture-secret"}}, {}),
        ("configured-letter-live-and-persistence", {"content": [{"type": "text", "text": "CUST:" + "𐐀" * 22}],
         "details": {"note": "CUST:" + "𐐀" * 22}}, {"patterns": [r"/(CUST:)(\p{L}+)/gu"]}),
        ("configured-letter-complement-before-fold", {"content": [{"type": "text", "text": "REF:ι REF:123"}],
         "details": {"note": "REF:ι REF:123"}}, {"patterns": [r"/(REF:)(\P{Letter}+)/giu"]}),
        ("configured-letter-character-class", {"content": [{"type": "text", "text": "MATCH:Ab_19"}],
         "details": {"note": "MATCH:Ab_19"}}, {"patterns": [r"/(MATCH:)([\p{General_Category=L}0-9_]+)/giu"]}),
        ("configured-letter-mixed-i-engine-diagnostic", {"content": [{"type": "text", "text": "CASE:aİ CASE:aı CASE:aI CASE:ai"}],
         "details": {"note": "CASE:aİ CASE:aı CASE:aI CASE:ai"}}, {"patterns": [r"/(CASE:)(\p{L}i)/giu"]}),
        ("configured-letter-capture-reset-engine-diagnostic", {"content": [{"type": "text", "text": "CAP:a1"}],
         "details": {"note": "CAP:a1"}}, {"patterns": [r"/(CAP:)(?:(\d)|(\p{L})){2}/gu"]}),
    ]
    output = []
    for name, result, extra in fixtures:
        value = deepcopy(seed)
        for key in ("patterns", "registeredSecrets", "lateRegisteredSecret", "modeProbe", "directGuardMessage"):
            value.pop(key, None)
        value.update(extra)
        value["toolResult"] = result
        output.append({"id": name, "covers": [], "input": value})
    return output


_REGISTRY_FORMS = {
    'pa"ss\\word+fixture': ['pa%22ss%5Cword%2Bfixture', 'pa\\"ss\\\\word+fixture', 'pa"ss\\word+fixture'],
    'registered-fixture': ['registered-fixture'],
}


def source_policy_fixtures() -> list[dict]:
    output = []
    for case in _source_literals():
        value = deepcopy(case["input"])
        value["kind"] = "source-policy"
        value["declaredRegistryValues"] = [form for secret in value["registeredSecrets"] for form in _REGISTRY_FORMS[secret]]
        output.append({"id": "redaction-policy-" + case["id"], "requirement": "trust.configured-redaction" if ("patterns" in value or value.get("directRegex")) else "trust.secret-redaction",
                       "operation": "redaction-policy-source", "covers": [], "input": value})
    return output


def model_helper_fixtures() -> list[dict]:
    return [{"id": "model-tool-" + case["id"], "requirement": "trust.secret-redaction",
             "operation": "model-tool-result-runtime", "covers": [],
             "input": {"kind": "model-helper", **deepcopy(case["input"])}} for case in _helper_literals()]


def model_session_fixtures() -> list[dict]:
    output = []
    for case in _session_literals():
        value = deepcopy(case["input"])
        common = {"kind": "model-session", "nowMs": value["nowMs"], "agentId": "main", "sessionId": value["sessionId"],
                  "sessionKey": value["sessionKey"], "systemPrompt": value["systemPrompt"], "model": value["model"],
                  **{key: value[key] for key in ("patterns", "registeredSecrets") if key in value}}
        phases = [{"label": "write", "prompt": value["writePrompt"], "responses": value["writeResponses"], "toolResult": value["toolResult"],
                   **{key: value[key] for key in ("lateRegisteredSecret", "directGuardMessage", "modeProbe") if key in value}},
                  {"label": "continue", "prompt": value["continuePrompt"], "responses": value["continueResponses"]}, {"label": "verify"}]
        output.append({"id": "model-session-" + case["id"], "requirement": "trust.configured-redaction" if "configured-letter" in case["id"] else "trust.secret-redaction",
                       "operation": "model-session-runtime", "covers": [], "input": {**common, "phases": phases}})
    return output


def build_redaction_cases() -> list[dict]:
    from equivalence.trust_worker_profile import build_trust_worker_cases
    from equivalence.tool_error_profile import build_tool_error_cases

    return source_policy_fixtures() + model_helper_fixtures() + model_session_fixtures() + build_trust_worker_cases() + build_tool_error_cases()
