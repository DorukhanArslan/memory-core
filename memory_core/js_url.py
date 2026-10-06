"""``new URL(text).hostname`` for the endpoint classifiers (WHATWG URL host parsing, no base).

Only the host is needed, so this implements the scheme/authority split, userinfo and port
validation, percent-decoding, IDNA (NFKC + lower-case + punycode, the UTS 46 mapping without its
validity checks: an invalid non-ASCII host can differ), IPv4 number forms and IPv6 compression.
``None`` stands for the ``TypeError`` ``new URL`` throws.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from urllib.parse import unquote_to_bytes

_SPECIAL = frozenset({"ftp", "file", "http", "https", "ws", "wss"})
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
_FORBIDDEN_HOST = frozenset("\x00\t\n\r #/:<>?@[\\]^|")
_FORBIDDEN_DOMAIN = _FORBIDDEN_HOST | frozenset("%\x7f") | {chr(i) for i in range(0x20)}


def url_hostname(text: str) -> str | None:
    """The ``hostname`` of ``new URL(text)`` (not lower-cased), or ``None`` when it throws."""

    value = text.strip("".join(chr(i) for i in range(0x21)))
    for char in "\t\n\r":
        value = value.replace(char, "")
    match = _SCHEME_RE.match(value)
    if not match:
        return None
    scheme = match.group(1).lower()
    rest = value[match.end() :]
    if scheme in _SPECIAL:
        return _special_hostname(scheme, rest)
    if not rest.startswith("//"):
        return ""
    authority = re.split(r"[/?#]", rest[2:], maxsplit=1)[0]
    host_port = _strip_userinfo(authority)
    host, port_ok = _split_port(host_port)
    if not port_ok:
        return None
    return _parse_opaque_host(host)


def _special_hostname(scheme: str, rest: str) -> str | None:
    rest = rest.lstrip("/\\") if scheme != "file" else rest
    if scheme == "file":
        if rest.startswith(("//", "\\\\")):
            authority = re.split(r"[/\\?#]", rest[2:], maxsplit=1)[0]
            if authority == "" or authority.lower() == "localhost":
                return ""
            host = _parse_special_host(authority)
            return "" if host == "localhost" else host
        return ""
    authority = re.split(r"[/\\?#]", rest, maxsplit=1)[0]
    host_port = _strip_userinfo(authority)
    host, port_ok = _split_port(host_port)
    if not port_ok:
        return None
    if host == "":
        return None
    return _parse_special_host(host)


def _strip_userinfo(authority: str) -> str:
    at = authority.rfind("@")
    return authority if at < 0 else authority[at + 1 :]


def _split_port(host_port: str) -> tuple[str, bool]:
    in_brackets = False
    colon = -1
    for index, char in enumerate(host_port):
        if char == "[":
            in_brackets = True
        elif char == "]":
            in_brackets = False
        elif char == ":" and not in_brackets:
            colon = index
            break
    if colon < 0:
        return host_port, True
    port = host_port[colon + 1 :]
    if port == "":
        return host_port[:colon], True
    if not port.isascii() or not port.isdigit():
        return host_port, False
    return host_port[:colon], int(port) <= 65535


def _parse_opaque_host(host: str) -> str | None:
    if host.startswith("["):
        return _parse_ipv6(host)
    if any(char in _FORBIDDEN_HOST for char in host):
        return None
    out = []
    for char in host:
        code = ord(char)
        if code < 0x20 or code > 0x7E:
            out.append("".join(f"%{b:02X}" for b in char.encode("utf-8", "replace")))
        else:
            out.append(char)
    return "".join(out)


def _parse_special_host(host: str) -> str | None:
    if host.startswith("["):
        return _parse_ipv6(host)
    decoded = unquote_to_bytes(host).decode("utf-8", "replace")
    if decoded.isascii():
        ascii_domain = decoded.lower()
    else:
        try:
            ascii_domain = _to_ascii_domain(decoded)
        except UnicodeError:
            return None
    if ascii_domain == "" or any(char in _FORBIDDEN_DOMAIN for char in ascii_domain):
        return None
    if _ends_in_number(ascii_domain):
        return _parse_ipv4(ascii_domain)
    return ascii_domain


def _to_ascii_domain(domain: str) -> str:
    """UTS 46 non-transitional ToASCII without the validity checks (keeps ``ß`` and ``ς``)."""

    labels = []
    for label in re.split("[.\u3002\uff0e\uff61]", unicodedata.normalize("NFKC", domain)):
        label = "".join(char.lower() for char in label)
        labels.append(
            label if label.isascii() else "xn--" + label.encode("punycode").decode("ascii")
        )
    return ".".join(labels)


def _parse_ipv6(host: str) -> str | None:
    if not host.endswith("]"):
        return None
    inner = host[1:-1]
    try:
        address = ipaddress.IPv6Address(inner)
    except ValueError:
        return None
    pieces = [int.from_bytes(address.packed[i : i + 2], "big") for i in range(0, 16, 2)]
    best_start, best_len = -1, 0
    index = 0
    while index < 8:
        if pieces[index] != 0:
            index += 1
            continue
        start = index
        while index < 8 and pieces[index] == 0:
            index += 1
        if index - start > best_len:
            best_start, best_len = start, index - start
    if best_len < 2:
        best_start = -1
    out = ""
    ignore0 = False
    for i, piece in enumerate(pieces):
        if ignore0 and piece == 0:
            continue
        ignore0 = False
        if best_start == i:
            out += "::" if i == 0 else ":"
            ignore0 = True
            continue
        out += f"{piece:x}"
        if i != 7:
            out += ":"
    return f"[{out}]"


def _ends_in_number(domain: str) -> bool:
    parts = domain.split(".")
    if parts[-1] == "":
        if len(parts) == 1:
            return False
        parts.pop()
    last = parts[-1]
    if last != "" and last.isdigit() and last.isascii():
        return True
    return _parse_ipv4_number(last) is not None


def _parse_ipv4_number(text: str) -> int | None:
    if text == "":
        return None
    radix = 10
    if len(text) >= 2 and text[:2].lower() == "0x":
        text, radix = text[2:], 16
    elif len(text) >= 2 and text[0] == "0":
        text, radix = text[1:], 8
    if text == "":
        return 0
    try:
        if not text.isascii():
            return None
        return int(text, radix)
    except ValueError:
        return None


def _parse_ipv4(domain: str) -> str | None:
    parts = domain.split(".")
    if parts[-1] == "" and len(parts) > 1:
        parts.pop()
    if len(parts) > 4:
        return None
    numbers = []
    for part in parts:
        number = _parse_ipv4_number(part)
        if number is None:
            return None
        numbers.append(number)
    if any(n > 255 for n in numbers[:-1]):
        return None
    if numbers[-1] >= 256 ** (5 - len(numbers)):
        return None
    ipv4 = numbers[-1]
    for index, number in enumerate(numbers[:-1]):
        ipv4 += number * 256 ** (3 - index)
    return ".".join(str((ipv4 >> shift) & 0xFF) for shift in (24, 16, 8, 0))
