"""``memory_core.redact`` against the real ``redactSensitiveText`` (mode ``tools``) of OpenClaw.

One oracle call redacts every fixture below with ``src/logging/redact.ts`` at the pinned checkout;
each parametrized test compares the Python port with that output. The table tests compare the
pattern sources, the sensitive-key sets and the Unicode class tables with the pinned runtime.

Run: ``OPENCLAW_ORACLE_NODE=... OPENCLAW_ORACLE_REPO=/tmp/openclaw-head pytest
tests/integration/test_redact_oracle.py``.
"""

from __future__ import annotations

import functools
import os
import re
from pathlib import Path

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core import redact


def _alnum(length: int, seed: str = "a1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuVwXyZ") -> str:
    return (seed * (length // len(seed) + 1))[:length]


def _b64url(length: int) -> str:
    return (_alnum(length, "Ab-Cd_Ef0Gh1Ij2Kl3Mn4Op5Qr6St7Uv8Wx9Yz") )[:length]


LONG = _alnum(40)
SHORT = "abc123XYZ"  # below the 18-unit mask threshold
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
PEM_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7\nVJTUt9Us8cKjMzEfYyjiWA4R4/M2bS1GB4t7NXp98C3SC6dVMvDuictGeurT8jNb\n"


def _pem(label: str = "PRIVATE KEY", body: str = PEM_BODY) -> str:
    return f"-----BEGIN {label}-----\n{body}-----END {label}-----"


VENDOR_TOKENS = {
    "openai-sk": "sk-" + _alnum(30, "abcDEF123_-"),
    "openai-sk-short": "sk-abcdefgh",
    "github-ghp": "ghp_" + _alnum(36),
    "github-pat": "github_pat_" + _alnum(40, "11AbCdEf_"),
    "github-gho": "gho_" + _alnum(36),
    "github-ghu": "ghu_" + _alnum(36),
    "github-ghs": "ghs_" + _alnum(36),
    "github-ghr": "ghr_" + _alnum(36),
    "gitlab-pat": "glpat-" + _alnum(20, "abcDEF123_-="),
    "gitlab-gloas-hex": "gloas-" + "ab12" * 8,
    "gitlab-gloas-b64": "gloas-" + _alnum(64, "ABab12_-"),
    "gitlab-gldt": "gldt-" + _alnum(22, "abcXYZ12_-"),
    "gitlab-glcbt": "glcbt-ab12_" + _alnum(24, "abcXYZ12_-"),
    "gitlab-glptt": "glptt-" + _alnum(40, "abcXYZ12_-"),
    "gitlab-glft": "glft-" + _alnum(24, "abcXYZ12_-"),
    "gitlab-glft-legacy": "glft-ab12-345_",
    "gitlab-glimt": "glimt-" + _alnum(26, "abcXYZ12_-"),
    "gitlab-glagent": "glagent-" + _alnum(52, "abcXYZ12_-"),
    "gitlab-glwt": "glwt-" + _alnum(22, "abcXYZ12_-"),
    "gitlab-glsoat": "glsoat-" + _alnum(22, "abcXYZ12_-"),
    "gitlab-glffct": "glffct-" + _alnum(22, "abcXYZ12_-"),
    "gitlab-glrt": "glrt-" + _alnum(24, "abcXYZ12._-"),
    "gitlab-glrtr": "glrtr-" + _alnum(30, "abcXYZ12_-") + ".01." + "abcdef123",
    "gitlab-gr1348941": "GR1348941" + _alnum(24, "abcXYZ12_-"),
    "gitlab-session": "_gitlab_session=" + _alnum(24, "abcXYZ12%._-"),
    "slack-xoxb": "xoxb-" + "1234567890-abcdefghij",
    "slack-xapp": "xapp-1-A0123456789-" + _alnum(12, "abc123"),
    "slack-webhook": "https://hooks.slack.com/services/T01234567/B01234567/" + _alnum(24, "abcXYZ123"),
    "slack-workflow": "https://hooks.slack.com/workflows/T01234567/A01234567/12345678901234567/" + _alnum(24, "abcXYZ123"),
    "discord-webhook": "https://discord.com/api/webhooks/123456789012345678/" + _alnum(64, "abcXYZ123_-"),
    "discord-bot": "discord token: " + _alnum(24, "abcXYZ123_-") + "." + _alnum(6, "abc123") + "." + _alnum(27, "abcXYZ123_-"),
    "groq": "gsk_" + _alnum(24, "abcXYZ123_-"),
    "google-aiza": "AIza" + _alnum(35, "abcXYZ123_-"),
    "google-ya29": "ya29." + _alnum(30, "abcXYZ123_-./+="),
    "google-1-0": "1//0" + _alnum(30, "abcXYZ123_-./+="),
    "jwt": "eyJ" + _alnum(20, "abcXYZ123_-") + "." + _alnum(24, "abcXYZ123_-") + "." + _alnum(24, "abcXYZ123_-"),
    "perplexity": "pplx-" + _alnum(24, "abcXYZ123_-"),
    "fal": "fal_" + _alnum(24, "abcXYZ123_-"),
    "firecrawl": "fc-" + _alnum(24, "abcXYZ123"),
    "browserbase": "bb_live_" + _alnum(24, "abcXYZ123_-"),
    "fernet": "gAAAA" + _alnum(40, "abcXYZ123_=-"),
    "stripe-sk-live": "sk_live_" + _alnum(24, "abcXYZ123"),
    "stripe-sk-test": "sk_test_" + _alnum(24, "abcXYZ123"),
    "stripe-rk-live": "rk_live_" + _alnum(24, "abcXYZ123"),
    "sendgrid": "SG." + _alnum(22, "abcXYZ123_-") + "." + _alnum(22, "abcXYZ123_-"),
    "npm": "npm_" + _alnum(36, "abcXYZ123"),
    "pypi": "pypi-" + _alnum(40, "abcXYZ123_-"),
    "do-pat": "dop_v1_" + _alnum(64, "abcdef0123"),
    "do-oauth": "doo_v1_" + _alnum(64, "abcdef0123"),
    "do-refresh": "dor_v1_" + _alnum(64, "abcdef0123"),
    "doppler-ct": "dp.ct." + _alnum(42, "abcXYZ123"),
    "doppler-st": "dp.st." + _alnum(42, "abcXYZ123"),
    "doppler-st-named": "dp.st.prod." + _alnum(42, "abcXYZ123"),
    "docker": "dckr_pat_" + _alnum(28, "abcXYZ123_-"),
    "buildkite": "bkua_" + _alnum(40, "abcxyz0123"),
    "circleci": "CCIPAT_" + _alnum(22, "abcXYZ123") + "_" + "ab12" * 10,
    "supabase": "sbp_" + _alnum(40, "abcxyz0123"),
    "databricks": "dapi" + "ab12cd34" * 4 + "-2",
    "datadog": "ddp_" + _alnum(36, "abcXYZ123"),
    "grafana-glsa": "glsa_" + _alnum(41, "abcXYZ123_"),
    "grafana-glc": "glc_eyJ" + _alnum(80, "abcXYZ123+/="),
    "netlify": "nfp_" + _alnum(36, "abcXYZ123_"),
    "cloudflare": "CFPAT-" + _alnum(44, "abcXYZ123_-"),
    "atlassian-atctt": "ATCTT3xFfG" + _alnum(30, "abcXYZ123+/_-") + "=" + "ab12cd34",
    "atlassian-atatt": "ATATT" + _alnum(30, "abcXYZ123+/_-") + "=" + "ab12cd34",
    "atlassian-atbb": "ATBB" + _alnum(24, "abcXYZ123_=.-"),
    "bitbucket": "BBDC-" + _alnum(44, "abcXYZ123+/@_-"),
    "heroku": "HRKU-AA" + _alnum(26, "abcXYZ123_-"),
    "hubspot": "pat-eu1-12345678-1234-1234-1234-123456789012",
    "apify": "apify_api_" + _alnum(26, "abcXYZ123-"),
    "fly": "FlyV1 fm2_" + _alnum(110, "abcXYZ123+/=,_-"),
    "fio": "fio-u-" + _alnum(44, "abcXYZ123_-"),
    "am": "am_" + _alnum(16, "abcXYZ123_-"),
    "sk-underscore": "sk_" + _alnum(16, "abcXYZ123_"),
    "tavily": "tvly-" + _alnum(24, "abcXYZ123"),
    "exa": "exa_" + _alnum(24, "abcXYZ123"),
    "sytest": "syt_" + _alnum(24, "abcXYZ123"),
    "retaindb": "retaindb_" + _alnum(24, "abcXYZ123"),
    "hsk": "hsk-" + _alnum(24, "abcXYZ123"),
    "mem0": "mem0_" + _alnum(24, "abcXYZ123"),
    "byterover": "brv_" + _alnum(24, "abcXYZ123"),
    "xai": "xai-" + _alnum(40, "abcXYZ123"),
    "fireworks-dash": "fw-" + _alnum(40, "abcXYZ123"),
    "fireworks-under": "fw_" + _alnum(40, "abcXYZ123"),
    "fpk": "fpk_" + _alnum(40, "abcXYZ123"),
    "aws-akia": "AKIAIOSFODNN7EXAMPLE",
    "aws-asia": "ASIAIOSFODNN7EXAMPLE",
    "tencent-akid": "AKID" + _alnum(20, "abcXYZ123"),
    "aliyun-ltai": "LTAI" + _alnum(20, "abcXYZ123"),
    "huggingface": "hf_" + _alnum(34, "abcXYZ123"),
    "huggingface-org": "api_org_" + _alnum(34, "abcXYZ123"),
    "replicate": "r8_" + _alnum(36, "abcXYZ123"),
    "telegram-bot": "bot123456789:" + _b64url(35),
    "telegram-bare": "123456789:" + _b64url(35),
}


def _case(name: str, text: str) -> tuple[str, str]:
    return (name, text)


FIXTURES: list[tuple[str, str]] = [
    _case("empty", ""),
    _case("plain", "nothing secret here, just a sentence about keys and tokens and secrets."),
    _case("whitespace", "   \n\t  "),
]

for _name, _token in VENDOR_TOKENS.items():
    FIXTURES.append(_case(f"vendor-{_name}", f"value {_token} end"))
    FIXTURES.append(_case(f"vendor-{_name}-start-of-text", _token))
    FIXTURES.append(_case(f"vendor-{_name}-quoted", f'secret "{_token}", next'))

FIXTURES += [
    # Mask length rule: under 18 UTF-16 units is ***, otherwise 6 + ellipsis + 4.
    _case("token-17", "api_key=" + "a" * 17),
    _case("token-18", "api_key=" + "a" * 18),
    _case("token-19", "api_key=" + "a" * 19),
    _case("token-short", "password=" + SHORT),
    _case("sk-just-below-min", "sk-abcdefg"),
    _case("sk-at-min", "sk-abcdefgh"),
    _case("sk-in-word", "task-sk-abcdefghijkl and risk-abcdefgh"),
    _case("bearer-short", "Bearer short-token"),
    _case("bearer-17", "Bearer " + "x" * 17),
    _case("bearer-18", "Bearer " + "x" * 18),
    _case("bearer-long-trailing-dot", "Bearer " + LONG + "."),
    # Environment assignments.
    _case("env-plain", "OPENAI_API_KEY=" + LONG),
    _case("env-double-quoted", 'OPENAI_API_KEY="' + LONG + '"'),
    _case("env-single-quoted", "ANTHROPIC_API_KEY='" + LONG + "'"),
    _case("env-colon", "GITHUB_TOKEN: " + LONG),
    _case("env-escaped-quotes", 'export DB_PASSWORD=\\"' + LONG + '\\"'),
    _case("env-shell-ref", "export MY_TOKEN=$MY_TOKEN && echo ok"),
    _case("env-shell-ref-braced", "MY_TOKEN=${MY_TOKEN}"),
    _case("env-shell-ref-default", "MY_TOKEN=${MY_TOKEN:-" + LONG + "}"),
    _case("env-shell-ref-other", "MY_TOKEN=$OTHER_TOKEN_VALUE_THAT_IS_LONG"),
    _case("env-lower-key-not-matched", "my_token=" + LONG),
    _case("env-multi", "A_KEY=" + LONG + "\nB_SECRET=" + LONG[::-1] + "\nC=plain\nD_PASSWD=" + SHORT),
    _case("env-payment", "CARD_NUMBER=4111111111111111 CVV=123 SECURITY_CODE=9999"),
    _case("env-trailing-delims", "API_KEY=" + LONG + ");"),
    _case("env-dotenv-file", "# config\nSECRET_KEY=" + LONG + "\nDEBUG=true\nTOKEN='" + SHORT + "'\n"),
    # JSON-ish fields.
    _case("json-api-key", '{"apiKey": "' + LONG + '", "name": "x"}'),
    _case("json-token-short", '{"token": "' + SHORT + '"}'),
    _case("json-authorization", '{"authorization": "Bearer ' + LONG + '"}'),
    _case("json-cookie", '{"cookie": "session=' + LONG + '; path=/"}'),
    _case("json-x-api-key", '{"x-api-key":"' + LONG + '"}'),
    _case("json-nested", '{"a": {"password": "hunter2hunter2hunter2", "b": [{"secret": "' + LONG + '"}]}}'),
    _case("json-escaped", '"{\\"client_secret\\": \\"' + LONG + '\\"}"'),
    _case("json-payment", '{"cardNumber": "4111111111111111", "cvc": "123", "paymentCredential": "' + LONG + '"}'),
    _case("json-aws", '{"aws_secret_access_key": "' + AWS_SECRET + '", "SecretAccessKey": "' + AWS_SECRET + '"}'),
    _case("json-unclosed", '{"token": "' + LONG),
    _case("json-non-string", '{"token": 12345678901234567890, "password": null}'),
    _case("ambiguous-quoted", "client_secret: '" + LONG + "' and appSecret=\"" + LONG + '"'),
    _case("ambiguous-auth-field", "authorization: '" + LONG + "', cookie='" + LONG[::-1] + "'"),
    # CLI flags.
    _case("cli-flag-equals", "curl --api-key=" + LONG + " https://example.com"),
    _case("cli-flag-space", "tool --token " + LONG + " --verbose"),
    _case("cli-flag-quoted", "tool --password '" + LONG + "'"),
    _case("cli-flag-or", "use --token or --password to log in"),
    _case("cli-flag-and", "pass --secret and --verbose"),
    _case("cli-flag-short", "tool --secret " + SHORT),
    _case("cli-flag-aws", "aws --aws-secret-access-key " + AWS_SECRET),
    _case("cli-flag-payment", "pay --card-number 4111111111111111 --cvv 123"),
    # URLs.
    _case("url-userinfo", "https://user:" + LONG + "@example.com/path"),
    _case("url-userinfo-short", "http://admin:" + SHORT + "@10.0.0.1:8080/"),
    _case("url-wss", "wss://bot:" + LONG + "@host.example/socket"),
    _case("url-postgres", "postgres://app:" + LONG + "@db.example.com:5432/app"),
    _case("url-postgresql", "postgresql://app:p%40ss@db.example.com/app"),
    _case("url-mongodb-srv", "mongodb+srv://u:" + LONG + "@cluster0.mongodb.net/test"),
    _case("url-redis", "rediss://:" + LONG + "@cache.example.com:6380/0"),
    _case("url-amqps", "amqps://guest:" + LONG + "@mq.example.com/"),
    _case("url-no-password", "https://user@example.com/path"),
    _case("url-query-token", "GET https://api.example.com/v1?token=" + LONG + "&page=2"),
    _case("url-query-key-short", "https://api.example.com/v1?key=" + SHORT),
    _case("url-query-signature", "https://s3.example.com/f?X-Amz-Signature=" + LONG + "&X-Amz-Expires=60"),
    _case("url-query-code", "https://auth.example.com/cb?code=" + LONG + "&state=xyz"),
    _case("url-query-sig", "https://cdn.example.com/a?sig=" + LONG),
    _case("url-query-scoped-token", "https://proxy.example.com/?share_token_" + "ab12" * 4 + "=" + LONG),
    _case("url-query-encoded-key", "https://api.example.com/?%74oken=" + LONG),
    _case("url-query-bad-percent", "https://api.example.com/?to%ZZken=" + LONG),
    _case("url-query-plus-splice", "https://api.example.com/?to+ken=" + LONG),
    _case("url-query-invisible", "https://api.example.com/?tok\u200ben=" + LONG),
    _case("url-query-fragment", "https://x.example.com/?api_key=" + LONG + "#frag"),
    _case("url-query-quoted", 'fetch("https://x.example.com/?password=' + LONG + '")'),
    _case("url-benign-query", "https://example.com/search?q=hello&page=3"),
    _case("telegram-url", "https://api.telegram.org/bot123456789:" + _b64url(35) + "/getMe"),
    # Authorization headers.
    _case("auth-bearer", "Authorization: Bearer " + LONG),
    _case("auth-bearer-lower", "authorization: bearer " + LONG),
    _case("auth-bearer-short", "Authorization: Bearer " + SHORT),
    _case("auth-basic", "Authorization: Basic dXNlcjpwYXNzd29yZHBhc3N3b3Jk"),
    _case("auth-bot", "Authorization: Bot " + LONG),
    _case("auth-raw-token", "Authorization: " + LONG),
    _case("auth-digest", 'Authorization: Digest username="u", realm="r", nonce="' + LONG + '", response="' + LONG[::-1] + '"'),
    _case("auth-aws4", "Authorization: AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20260101/us-east-1/s3/aws4_request, SignedHeaders=host;x-amz-date, Signature=" + "ab12" * 16),
    _case("auth-hawk", 'Authorization: Hawk id="dh37fgj492je", ts="1353832234", nonce="j4h3g2", mac="' + LONG + '"'),
    _case("auth-proxy", "Proxy-Authorization: Basic dXNlcjpwYXNzd29yZHBhc3N3b3Jk"),
    _case("auth-proxy-bearer", "Proxy-Authorization: Bearer " + LONG),
    _case("auth-json-escaped", '{\\"Authorization\\": \\"Bearer ' + LONG + '\\"}'),
    _case("auth-json-double-escaped", '{\\\\\\"Authorization\\\\\\": \\\\\\"Bearer ' + LONG + '\\\\\\"}'),
    _case("auth-serialized-newline", "Authorization: Bearer\\n  " + LONG),
    _case("auth-folded", "Authorization: Bearer\r\n " + LONG + "\r\nHost: x"),
    _case("auth-redacted-marker", "Authorization: Bearer [REDACTED]"),
    _case("auth-equals", "Authorization=Bearer " + LONG),
    _case("auth-in-sentence", "the Authorization header was Bearer " + LONG + " in the request"),
    _case("auth-custom-scheme", "Authorization: Negotiate " + LONG),
    _case("auth-multi-header", "Authorization: Bearer " + LONG + "\nX-Api-Key: " + LONG[::-1] + "\nX-Auth-Token: " + SHORT),
    _case("auth-header-not-boundary", "xAuthorization: Bearer " + LONG),
    _case("header-x-goog", "x-goog-api-key: " + LONG),
    _case("header-api-key", "api-key=" + LONG),
    _case("header-x-openclaw-token", "X-OpenClaw-Token: " + LONG),
    _case("header-pomerium", "x-pomerium-jwt-assertion: " + LONG),
    _case("header-x-access-token", 'headers: {"x-access-token": "' + LONG + '"}'),
    _case("header-equals-form-aware", "api-key=" + LONG + "&other=1&x=2"),
    # Form bodies and standalone assignments.
    _case("form-simple", "password=" + LONG + "&user=bob"),
    _case("form-multiple", "user=bob&token=" + LONG + "&code=" + SHORT + "&x=1"),
    _case("form-encoded-key", "%70assword=" + LONG + "&a=b"),
    _case("form-plus-key", "pass+word=" + LONG + "&a=b"),
    _case("form-body-context", "body=password=" + LONG),
    _case("form-body-context-quoted", "form-body: 'token=" + LONG + "'"),
    _case("form-in-sentence", "sent client_id=abc&client_secret=" + LONG + "&grant_type=x ok"),
    _case("form-multiline", "a=1&b=2\npassword=" + LONG + "&c=3\nmore"),
    _case("form-crlf", "token=" + LONG + "&a=1\r\nsecret=" + LONG + "&b=2"),
    _case("form-quoted-value", "token=\"" + LONG + "\"&x=1"),
    _case("form-trailing-delims", "token=" + LONG + "),&x=1"),
    _case("form-benign", "a=1&b=2&c=hello"),
    _case("standalone-assign", "run with token=" + LONG + " now"),
    _case("standalone-assign-quoted", "x password=\"" + LONG + "\" y"),
    _case("standalone-assign-quoted-other-quote", "x password=\"it's " + LONG + "\" y"),
    _case("standalone-assign-backtick", "x secret=`" + LONG + "` y"),
    _case("standalone-assign-unterminated", "x secret=\"" + LONG),
    _case("standalone-shell-ref", "token=$TOKEN"),
    _case("standalone-after-comma", "a,token=" + LONG + ",b"),
    _case("standalone-first-pair", "user,token=" + LONG + "&next=1"),
    # Config assignments.
    _case("config-colon", "api_key: " + LONG),
    _case("config-spaced-equals", "client_secret = " + LONG),
    _case("config-quoted", "access_token: '" + LONG + "'"),
    _case("config-direct", "access-token=" + LONG),
    _case("config-prefixed-password", "db-password: " + LONG),
    _case("config-namespaced", "spring.datasource.password = " + LONG),
    _case("config-namespaced-colon", "app.api_key: " + LONG),
    _case("config-passphrase", "passphrase=" + LONG),
    _case("config-braces", "{password: " + LONG + "}"),
    _case("config-yaml", "server:\n  host: x\n  password: " + LONG + "\n  port: 1\n"),
    # AWS secret access keys.
    _case("aws-secret-bare", "secret is " + AWS_SECRET + " ok"),
    _case("aws-secret-field", "aws_secret_access_key = " + AWS_SECRET),
    _case("aws-secret-field-quoted", "\"SecretAccessKey\": \"" + AWS_SECRET + "\""),
    _case("aws-secret-in-url", "https://example.com/path/" + AWS_SECRET + "/more"),
    _case("aws-secret-userinfo", "https://user:" + AWS_SECRET + "@example.com/"),
    _case("aws-secret-with-underscore-neighbour", "x_" + AWS_SECRET + " y"),
    _case("aws-secret-followed-underscore", AWS_SECRET + "_suffix"),
    _case("aws-secret-base64-data-url", "data:image/png;base64," + AWS_SECRET),
    _case("aws-secret-in-longer-run", "p" + AWS_SECRET + "q"),
    _case("aws-secret-slash-at", "scheme://" + "a" * 3 + "/" + AWS_SECRET + "@host"),
    _case("aws-secret-markdown-link", "[link](https://example.com/" + AWS_SECRET + ")"),
    _case("aws-secret-quoted-url", 'url="https://h.example/' + AWS_SECRET + '" next'),
    _case("aws-secret-port-credential", "https://host:8080/" + AWS_SECRET + "@x"),
    _case("aws-secret-two", AWS_SECRET + " " + AWS_SECRET[::-1]),
    _case("aws-lowercase-run-no-match", "a" * 40),
    _case("aws-hex-run-no-match", "ab12" * 10),
    # PEM blocks.
    _case("pem-private-key", _pem()),
    _case("pem-rsa", "key:\n" + _pem("RSA PRIVATE KEY") + "\nafter"),
    _case("pem-ec", _pem("EC PRIVATE KEY")),
    _case("pem-openssh", _pem("OPENSSH PRIVATE KEY")),
    _case("pem-encrypted", _pem("ENCRYPTED PRIVATE KEY")),
    _case("pem-two-blocks", _pem() + "\nmiddle\n" + _pem("RSA PRIVATE KEY")),
    _case("pem-crlf", _pem().replace("\n", "\r\n")),
    _case("pem-single-line", "-----BEGIN PRIVATE KEY-----ABCDEF-----END PRIVATE KEY-----"),
    _case("pem-empty-body", "-----BEGIN PRIVATE KEY----------END PRIVATE KEY-----"),
    _case("pem-lowercase", _pem().lower()),
    _case("pem-incomplete", "-----BEGIN PRIVATE KEY-----\n" + PEM_BODY),
    _case("pem-end-only", PEM_BODY + "-----END PRIVATE KEY-----"),
    _case("pem-mismatched-label", "-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END EC PRIVATE KEY-----"),
    _case("pem-public-key", "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----"),
    _case("pem-in-json", '{"key": "' + _pem().replace("\n", "\\n") + '"}'),
    _case("pem-dashes-noise", "------BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY------"),
    _case("pem-nested-begin", "-----BEGIN PRIVATE KEY-----\nA\n-----BEGIN PRIVATE KEY-----\nB\n-----END PRIVATE KEY-----"),
    # base64-safe prefixes and data URLs.
    _case("base64-boundary-akia-dash", "x-AKIAIOSFODNN7EXAMPLE"),
    _case("base64-boundary-akia-alnum", "xAKIAIOSFODNN7EXAMPLE"),
    _case("base64-boundary-akia-plus", "+AKIAIOSFODNN7EXAMPLE"),
    _case("base64-data-url-akia", "data:application/x;base64,AKIAIOSFODNN7EXAMPLE"),
    _case("base64-data-url-akia-after-plus", "data:application/x;base64,Zm9v+AKIAIOSFODNN7EXAMPLE"),
    _case("base64-data-url-then-text", "data:a/b;base64,Zm9v AKIAIOSFODNN7EXAMPLE"),
    _case("base64-data-url-gaaaa", "x;base64," + VENDOR_TOKENS["fernet"]),
    _case("base64-two-tokens", "AKIAIOSFODNN7EXAMPLE,ASIAIOSFODNN7EXAMPLE;"),
    _case("base64-dapi", "a dapi" + "ab12cd34" * 4 + " b"),
    _case("base64-after-slash-eq", "k=/ATBB" + _alnum(24, "abcXYZ123_=.-")),
    # Mixed and structural.
    _case("mixed-everything", "OPENAI_API_KEY=" + LONG + " " + VENDOR_TOKENS["github-ghp"] + "\nAuthorization: Bearer " + LONG + "\n" + _pem()),
    _case("log-line", '2026-01-01T00:00:00Z INFO request {"headers": {"authorization": "Bearer ' + LONG + '"}, "url": "https://a.example/x?api_key=' + LONG + '"}'),
    _case("markdown-code", "```bash\nexport OPENAI_API_KEY=" + LONG + "\ncurl -H 'Authorization: Bearer " + LONG + "' https://x\n```"),
    _case("already-masked", "token=*** and api_key=abcdef…wxyz and Bearer ***"),
    _case("masked-quoted", 'password="***"'),
    _case("already-masked-json", '{"token": "***", "apiKey": "sk-abc…2345"}'),
    # Unicode and UTF-16.
    _case("unicode-around-token", "密码：api_key=" + LONG + " 結束"),
    _case("unicode-emoji-around", "\U0001f600 token=" + LONG + " \U0001f600"),
    _case("unicode-astral-in-token-short", "token=" + "\U0001f600" * 8),
    _case("unicode-astral-in-token-9-emoji", "token=" + "\U0001f600" * 9),
    _case("unicode-astral-in-token-mask-edges", "token=\U0001f600abcdefghijklmnopqrstuv\U0001f600\U0001f600"),
    _case("unicode-astral-token-straddles-slice", "password=ab" + "\U0001f600" * 6 + "cdefgh\U0001f600"),
    _case("unicode-astral-straddle-end", "secret=abcdefghijklmnopqr\U0001f600xyz"),
    _case("unicode-discord-gap-astral", "discord " + "\U0001f600" * 15 + " " + _alnum(24, "abcXYZ123_-") + "." + _alnum(6, "abc123") + "." + _alnum(27, "abcXYZ123_-")),
    _case("unicode-discord-gap-astral-over", "discord " + "\U0001f600" * 21 + _alnum(24, "abcXYZ123_-") + "." + _alnum(6, "abc123") + "." + _alnum(27, "abcXYZ123_-")),
    _case("unicode-discord-gap-ls", "discord\u2028\u2029" + _alnum(24, "abcXYZ123_-") + "." + _alnum(6, "abc123") + "." + _alnum(27, "abcXYZ123_-")),
    _case("unicode-discord-gap-newlines", "discord\r\n\n" + _alnum(24, "abcXYZ123_-") + "." + _alnum(6, "abc123") + "." + _alnum(27, "abcXYZ123_-")),
    _case("unicode-discord-gap-40", "discord" + "x" * 33 + " " + _alnum(24, "abcXYZ123_-") + "." + _alnum(6, "abc123") + "." + _alnum(27, "abcXYZ123_-")),
    _case("unicode-lone-high-surrogate", "token=ab\ud83dcdefghijklmnopqrstuvwxyz"),
    _case("unicode-lone-low-surrogate", "token=\ude00abcdefghijklmnopqrstuvwxyz1234"),
    _case("unicode-lone-surrogate-plain", "\ud83d no secret \ude00"),
    _case("unicode-nbsp-assign", "TOKEN:\u00a0" + LONG),
    _case("unicode-ideographic-space", "API_KEY=" + LONG + "\u3000next"),
    _case("unicode-ls-separator", "API_KEY=" + LONG + "\u2028SECRET_KEY=" + LONG[::-1]),
    _case("unicode-bom", "\ufeffapi_key: " + LONG),
    _case("unicode-fullwidth-key", "ＡＰＩ＿ＫＥＹ=" + LONG),
    _case("unicode-kelvin-sign", "TOKEN=" + LONG + " and KEY=" + LONG),
    _case("unicode-long-s", "paſſword=" + LONG + " ſk-abcdefghijkl"),
    _case("unicode-turkish-i", "Authorİzation: Bearer " + LONG),
    _case("auth-scheme-long-s-folds", "Proxy-Authorization: \u017fand 0eEo63RN-=pjGd8hQT\u4e2d"),
    _case("auth-scheme-kelvin-folds", "Authorization: \u212anown " + LONG),
    _case("unicode-url-invisible-key", "https://x.example.com/?pass\u200bword=" + LONG),
    _case("unicode-url-hangul-filler", "https://x.example.com/?pasㅤs=" + LONG),
    _case("unicode-form-invisible-key", "pass\u200bword=" + LONG + "&a=1"),
    _case("unicode-form-invisible-lead", "\u200btoken=" + LONG + "&a=1"),
    _case("unicode-form-private-use-key", "to\ue000ken=" + LONG + "&a=1"),
    _case("unicode-form-unassigned-key", "to\u0378ken=" + LONG + "&a=1"),
    _case("unicode-form-new-char-key", "to\U0001fae9ken=" + LONG + "&a=1"),
    _case("unicode-form-soft-hyphen", "to\u00adken=" + LONG + "&a=1"),
    _case("unicode-form-zwj", "tok\u200den=" + LONG + "&a=1"),
    _case("unicode-bidi-marks", "\u202etoken=" + LONG + "\u202c"),
    _case("unicode-word-boundary-before-bearer", "ſBearer " + LONG),
    _case("unicode-word-boundary-before-pass", "Kpass=" + LONG),
    _case("unicode-rtl-text", "كلمة السر: password=" + LONG),
    _case("unicode-combining", "api_key=" + LONG + "́"),
    _case("unicode-url-encoded-utf8-key", "https://x.example.com/?%E2%80%8Btoken=" + LONG),
    _case("unicode-url-encoded-bad-utf8-key", "https://x.example.com/?%E2%80token=" + LONG),
    _case("unicode-url-double-encoded", "https://x.example.com/?%2574oken=" + LONG),
    _case("unicode-url-nested-triple", "https://x.example.com/?%252574oken=" + LONG),
    # Gate edge cases (the fast path must agree with the full walk).
    _case("gate-only-aws", "x" + AWS_SECRET),
    _case("gate-only-equals-obfuscated", "a+b=" + LONG),
    _case("gate-plus-leading", "+=value"),
    _case("gate-percent-key", "%61pi=" + LONG),
    _case("gate-bare-equals-rule", "===== heading ====="),
    _case("gate-pass-colon", "pass: " + LONG),
    _case("gate-session-equals", "session=" + LONG),
    _case("gate-code-equals", "code=" + LONG),
    _case("gate-sig", "sig=" + LONG),
    _case("gate-jwt-equals", "jwt = " + LONG),
    _case("gate-underscore-password", "db_password=" + LONG),
    _case("gate-bot-token", "bot123456789:" + _b64url(30)),
    _case("gate-card", "card=4111111111111111"),
    _case("gate-userinfo", "ftp://u:" + LONG + "@h/"),
]

# Length behaviour: chunked matching above 32,768 units and chunk-unsafe patterns.
_FILLER = "lorem ipsum dolor sit amet " * 12
_PAD_16K = ("x" * 99 + " ") * 164  # 16,400 units
FIXTURES += [
    _case("big-no-secret", _FILLER * 140),
    _case("big-token-start", "OPENAI_API_KEY=" + LONG + "\n" + _FILLER * 140),
    _case("big-token-middle", _FILLER * 70 + "\ntoken=" + LONG + "\n" + _FILLER * 70),
    _case("big-token-end", _FILLER * 140 + "\nghp_" + _alnum(36)),
    _case("big-token-at-chunk-edge", "a" * 16_370 + " sk-" + _alnum(30, "abcDEF123_-") + " " + "b" * 17_000),
    _case("big-token-split-by-chunk", "a" * 16_380 + " sk-" + _alnum(30, "abcDEF123_-") + " " + "b" * 17_000),
    _case("big-two-chunks", ("y " * 8_000) + "sk-" + _alnum(30, "abcDEF123_-") + " " + ("y " * 8_000) + "ghp_" + _alnum(36)),
    _case("big-bearer-split", "Q" * 16_375 + " Bearer " + LONG + " " + "R" * 17_000),
    _case("big-auth-header-split", "Q" * 16_370 + "\nAuthorization: Bearer " + LONG + "\n" + "R" * 17_000),
    _case("big-telegram-split", "Q" * 16_375 + " " + "123456789:" + _b64url(35) + " " + "R" * 17_000),
    _case("big-akia-after-edge", "Q" * 16_384 + "AKIAIOSFODNN7EXAMPLE" + " " + "R" * 17_000),
    _case("big-akia-data-url-across-edge", "data:a/b;base64," + "Z" * 16_380 + "AKIAIOSFODNN7EXAMPLE" + " " + "R" * 17_000),
    _case("big-pem", "p " * 17_000 + _pem() + " tail"),
    _case("big-aws", "p " * 17_000 + AWS_SECRET + " tail"),
    _case("big-astral", "\U0001f600" * 17_000 + " token=" + LONG),
    _case("big-astral-straddle", "a" * 16_383 + "\U0001f600" + "sk-" + _alnum(30, "abcDEF123_-") + " " + "b" * 17_000),
    _case("big-json", '{"items": [' + ",".join('{"id": %d, "password": "%s"}' % (i, LONG) for i in range(900)) + "]}"),
    _case("big-many-env", "\n".join(f"VAR_{i}_TOKEN={LONG}{i}" for i in range(1200))),
    _case("exact-threshold", ("z" * 32_768)[:32_750] + " sk-abcdefghijklmnop"),
    _case("over-threshold-by-one", ("z" * 32_769)[:32_750] + " sk-abcdefghijklmnop12"),
]


@functools.cache
def _oracle_run() -> dict:
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    result = oracle.run(
        {"operation": "redactSensitiveText", "texts": [text for _, text in FIXTURES], "meta": True}
    )
    assert result["ok"] is True, result
    return result["result"]


_EXPECTED_BY_NAME: dict[str, str] | None = None


def _expected(name: str) -> str:
    global _EXPECTED_BY_NAME
    if _EXPECTED_BY_NAME is None:
        outputs = _oracle_run()["texts"]
        assert len(outputs) == len(FIXTURES)
        _EXPECTED_BY_NAME = {n: out for (n, _), out in zip(FIXTURES, outputs)}
    return _EXPECTED_BY_NAME[name]


_FUZZ_FRAGMENTS = [
    "token=", "api_key: ", "Authorization: ", "Bearer ", "Basic ", "Digest ", "password=", "secret=", "&", "?", "=",
    ":", ",", " ", "\n", "\r\n", "\t", '"', "'", "`", "{", "}", "(", ")", "[", "]", ";", "\\", '\\\"', "\\n",
    "\\t", "/", "@", "#", "%74", "%2", "+", "sk-", "ghp_", "AKIA", "ASIA", "eyJ", "xoxb-", "gAAAA", "dapi", "ATBB",
    "bot123456789:", "123456789:", "-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----", "PRIVATE KEY", "BEGIN ", "END ", "-----", ";base64,", "data:x/y", "https://",
    "postgres://", "user:", "x-api-key: ", "X-Auth-Token=", "--token ", "--password=", "--secret ", "or ", "and ",
    "MY_TOKEN=", "$MY_TOKEN", "${MY_TOKEN:-x}", "API_KEY=", "body=", "form-body: ", "discord ",
    "aws_secret_access_key=", AWS_SECRET, "Proxy-Authorization: ", '"authorization": "', 'apiKey": "', "***", "\u2026",
    "\U0001f600", "\u200b", "\u00a0", "\u2028", "\u3164", "\ue000", "\u0378", "\ud83d", "\ude00", "\u017f",
    "\u212a", "\u00e9", "\u4e2d", "Signature=", "Credential=", "SignedHeaders=host;x", "AWS4-HMAC-SHA256 ",
    "realm=", "nonce=", "code=", "sig=", "session=",
]
_FUZZ_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./+="


def _fuzz_texts(seed: int, count: int, max_parts: int) -> list[str]:
    import random

    rnd = random.Random(seed)

    def word() -> str:
        return "".join(rnd.choice(_FUZZ_ALPHABET) for _ in range(rnd.choice([3, 8, 12, 17, 18, 19, 24, 30, 40, 44])))

    return [
        "".join(
            word() if rnd.random() < 0.35 else rnd.choice(_FUZZ_FRAGMENTS)
            for _ in range(rnd.randint(2, max_parts))
        )
        for _ in range(count)
    ]


@pytest.mark.parametrize("seed,count,max_parts", [(1, 3000, 14), (2, 1500, 60), (3, 20, 9000)])
def test_redact_sensitive_text_matches_upstream_on_generated_texts(seed: int, count: int, max_parts: int):
    texts = _fuzz_texts(seed, count, max_parts)
    result = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"])).run(
        {"operation": "redactSensitiveText", "texts": texts}
    )
    assert result["ok"] is True, result
    mismatches = [
        (text, want, redact.redact_sensitive_text(text))
        for text, want in zip(texts, result["result"]["texts"])
        if redact.redact_sensitive_text(text) != want
    ]
    assert not mismatches, mismatches[:3]
    assert sum(1 for text in texts if redact.redact_sensitive_text(text) != text) > count // 4


def test_fixture_names_are_unique():
    names = [name for name, _ in FIXTURES]
    assert len(names) == len(set(names))
    assert len(names) >= 400


@pytest.mark.parametrize("name,text", FIXTURES, ids=[name for name, _ in FIXTURES])
def test_redact_sensitive_text_matches_upstream(name: str, text: str):
    assert redact.redact_sensitive_text(text) == _expected(name)


def test_fixtures_exercise_redaction():
    # Guard against a vacuous suite: most secret-bearing fixtures must actually change.
    changed = sum(1 for name, text in FIXTURES if _expected(name) != text)
    assert changed >= 300


def test_default_string_patterns_equal_upstream():
    assert list(redact.DEFAULT_REDACT_STRING_PATTERNS) == _oracle_run()["meta"]["defaultStringPatterns"]


def test_body_secret_keys_equal_upstream():
    assert sorted(redact.BODY_SECRET_KEYS) == sorted(_oracle_run()["meta"]["bodySecretKeys"])


def test_unicode_class_tables_equal_pinned_runtime():
    meta = _oracle_run()["meta"]

    def parse(table: str) -> list[list[int]]:
        out = []
        for token in table.split(","):
            low, _, high = token.partition("-")
            out.append([int(low, 16), int(high or low, 16)])
        return out

    assert parse(redact._UNICODE_C_RANGES) == meta["unicodeC"]
    assert parse(redact._UNICODE_Z_RANGES) == meta["unicodeZ"]


def _upstream_source(relative: str) -> str:
    return (Path(os.environ["OPENCLAW_ORACLE_REPO"]) / relative).read_text(encoding="utf-8")


def test_sensitive_url_query_param_names_equal_upstream_source():
    source = _upstream_source("packages/net-policy/src/redact-sensitive-url.ts")
    block = re.search(r"const SENSITIVE_URL_QUERY_PARAM_NAMES = new Set\(\[(.*?)\]\);", source, re.S)
    names = set(re.findall(r'"([^"]+)"', re.sub(r"//[^\n]*", "", block.group(1))))
    assert names == set(redact.SENSITIVE_URL_QUERY_PARAM_NAMES)


def test_prefilter_sources_equal_upstream_source():
    source = _upstream_source("src/logging/redact.ts")
    block = re.search(r"const DEFAULT_REDACT_PREFILTER_SOURCES: string\[\] = \[(.*?)\n\];", source, re.S)
    without_comments = re.sub(r"^\s*//[^\n]*\n", "", block.group(1), flags=re.M)
    literals = re.findall(r"String\.raw`(.*?)`", without_comments, re.S)
    resolved = [
        item.replace("${FORM_BODY_KEY_INVISIBLE_CHARS}", redact.FORM_BODY_KEY_INVISIBLE_CHARS) for item in literals
    ]
    assert resolved == list(redact.DEFAULT_REDACT_PREFILTER_SOURCES)


def test_chunk_constants_equal_upstream_source():
    source = _upstream_source("src/logging/redact-bounded.ts")
    threshold = int(re.search(r"REDACT_REGEX_CHUNK_THRESHOLD = ([0-9_]+)", source).group(1).replace("_", ""))
    size = int(re.search(r"REDACT_REGEX_CHUNK_SIZE = ([0-9_]+)", source).group(1).replace("_", ""))
    assert (threshold, size) == (redact.REDACT_REGEX_CHUNK_THRESHOLD, redact.REDACT_REGEX_CHUNK_SIZE)
    redact_source = _upstream_source("src/logging/redact.ts")
    for name, value in (
        ("DEFAULT_REDACT_MIN_LENGTH", redact.DEFAULT_REDACT_MIN_LENGTH),
        ("DEFAULT_REDACT_KEEP_START", redact.DEFAULT_REDACT_KEEP_START),
        ("DEFAULT_REDACT_KEEP_END", redact.DEFAULT_REDACT_KEEP_END),
    ):
        assert int(re.search(rf"const {name} = (\d+);", redact_source).group(1)) == value
