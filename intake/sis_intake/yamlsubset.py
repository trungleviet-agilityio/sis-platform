"""A small, fail-closed parser for a documented YAML subset (stdlib only).

Supported: block maps and lists, plain and quoted scalars, int, bool, null, comments,
flow lists of scalars and flow maps of scalars on one line (a flow map value may itself be
a flow list of scalars, as in `release: {steps: [10, 100]}`).

Rejected with a line number: anchors, aliases, tags, multiple documents, block scalars,
multi-line scalars, nested flow collections, tab indentation, duplicate keys, and plain
scalars that YAML 1.1 would read as something other than a string, an int, a bool or null
(floats, dates, yes/no/on/off, 0x and octal forms). Quote such values to keep them strings.
"""

from __future__ import annotations

import re
from typing import Any


class YamlError(Exception):
    """A parse error with the 1-based line number."""

    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


class _Line:
    __slots__ = ("indent", "no", "text")

    def __init__(self, no: int, indent: int, text: str) -> None:
        self.no = no
        self.indent = indent
        self.text = text


_PLAIN_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_.\-/]*)[ ]*:(?:[ ]+(.*))?$")
_INT = re.compile(r"^[-+]?(0|[1-9][0-9]*)$")
_NUMBER_LIKE = [
    re.compile(r"^[-+]?(\d[\d_]*\.?\d*|\.\d+)([eE][-+]?\d+)?$"),
    re.compile(r"^[-+]?\d+(:[0-5]?\d)+(\.\d*)?$"),
    re.compile(r"^[-+]?0[xXoObB][0-9a-fA-F_]*$"),
    re.compile(r"^\d{4}-\d{1,2}-\d{1,2}"),
    re.compile(r"^[-+]?\.(inf|Inf|INF|nan|NaN|NAN)$"),
]
_MAX_DEPTH = 32
_MAX_INT_DIGITS = 18
_AMBIGUOUS_BOOLS = {"yes", "no", "on", "off", "y", "n"}
_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "/": "/"}


def _opens_quote(text: str, i: int) -> bool:
    return i == 0 or text[i - 1] in " ,[{"


def _strip_comment(text: str) -> str:
    quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote is None:
            if ch in "\"'" and _opens_quote(text, i):
                quote = ch
            elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
                return text[:i].rstrip()
        elif quote == '"' and ch == "\\":
            i += 1
        elif ch == quote:
            if quote == "'" and text[i + 1 : i + 2] == "'":
                i += 1
            else:
                quote = None
        i += 1
    return text.rstrip()


def _tokenize(text: str) -> list[_Line]:
    lines: list[_Line] = []
    for no, raw in enumerate(text.splitlines(), start=1):
        body = raw.lstrip(" ")
        indent = len(raw) - len(body)
        if body.startswith("\t"):
            raise YamlError(no, "tab characters are not allowed in indentation")
        content = _strip_comment(body)
        if not content:
            continue
        if content == "---" or content.startswith("--- ") or content == "...":
            raise YamlError(no, "document markers (multiple documents) are not supported")
        lines.append(_Line(no, indent, content))
    return lines


def _parse_quoted(text: str, start: int, no: int) -> tuple[str, int]:
    """Parse a quoted scalar beginning at text[start]; return (value, index after it)."""
    quote = text[start]
    out: list[str] = []
    i = start + 1
    while i < len(text):
        ch = text[i]
        if quote == '"' and ch == "\\":
            esc = text[i + 1 : i + 2]
            if esc not in _ESCAPES:
                raise YamlError(no, "unsupported escape sequence in double-quoted string")
            out.append(_ESCAPES[esc])
            i += 2
            continue
        if ch == quote:
            if quote == "'" and text[i + 1 : i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise YamlError(no, "unterminated quoted string (multi-line scalars are not supported)")


def _split_key(text: str, no: int) -> tuple[str, str] | None:
    """Split 'key: rest'. Returns None when text is not a mapping entry."""
    if text[0] in "\"'":
        key, end = _parse_quoted(text, 0, no)
        tail = text[end:].lstrip(" ")
        if not tail.startswith(":"):
            return None
        after = tail[1:]
        if after and not after.startswith(" "):
            return None
        return key, after.strip()
    if text[0] in "[{":
        return None
    match = _PLAIN_KEY.match(text)
    if match is None:
        return None
    return match.group(1), (match.group(2) or "").strip()


def _resolve_plain(text: str, no: int) -> Any:
    if text in ("", "~", "null", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if text.lower() in _AMBIGUOUS_BOOLS:
        raise YamlError(no, f"ambiguous boolean {text!r}: write true or false, or quote the string")
    if _INT.match(text):
        if len(text.lstrip("+-")) > _MAX_INT_DIGITS:
            raise YamlError(no, f"integer has more than {_MAX_INT_DIGITS} digits: quote it")
        return int(text)
    for pattern in _NUMBER_LIKE:
        if pattern.match(text):
            raise YamlError(no, f"ambiguous number or date {text!r}: quote it to keep a string")
    return text


def _scalar(text: str, no: int) -> Any:
    first = text[0]
    if first == "&":
        raise YamlError(no, "anchors are not supported")
    if first == "*":
        raise YamlError(no, "aliases are not supported")
    if first == "!":
        raise YamlError(no, "tags are not supported")
    if first in "|>":
        raise YamlError(no, "block scalars (multi-line) are not supported")
    if first in "%@`":
        raise YamlError(no, f"reserved indicator {first!r} at the start of a scalar")
    if first in "\"'":
        value, end = _parse_quoted(text, 0, no)
        if text[end:].strip():
            raise YamlError(no, "unexpected text after quoted string")
        return value
    if text in ("-", "=", "<<", "?") or text.startswith(("- ", "? ")) or "\t" in text:
        raise YamlError(no, "plain scalar not accepted by YAML parsers: quote it")
    if re.search(r":(\s|$)", text):
        raise YamlError(no, "nested mapping on one line is not supported")
    return _resolve_plain(text, no)


def _split_flow(inner: str, no: int, allow_list: bool) -> list[str]:
    """Split flow items on commas outside quotes; a flow map may hold one-level lists."""
    items: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    depth = 0
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote is None:
            if ch in "{}" or (ch == "[" and (not allow_list or depth)) or (ch == "]" and not depth):
                raise YamlError(no, "nested flow collections are not supported")
            if ch == "[":
                depth = 1
            elif ch == "]":
                depth = 0
            elif ch == "," and not depth:
                items.append("".join(buf).strip())
                buf = []
                i += 1
                continue
            elif ch in "\"'" and ("".join(buf).strip() == "" or buf[-1] in " :["):
                quote = ch
        elif quote == '"' and ch == "\\":
            buf.append(ch)
            i += 1
            ch = inner[i] if i < len(inner) else ""
        elif ch == quote:
            if quote == "'" and inner[i + 1 : i + 2] == "'":
                buf.append(ch)
                i += 1
                ch = "'"
            else:
                quote = None
        buf.append(ch)
        i += 1
    if depth:
        raise YamlError(no, "unclosed '[' in flow collection")
    last = "".join(buf).strip()
    if last or items:
        items.append(last)
    if items and items[-1] == "":
        items.pop()
    return items


def _flow(text: str, no: int, allow_list: bool = True) -> Any:
    opener = text[0]
    closer = "]" if opener == "[" else "}"
    if not text.endswith(closer):
        raise YamlError(no, "flow collection must close on the same line")
    items = _split_flow(text[1:-1], no, opener == "{" and allow_list)
    if any(item == "" for item in items):
        raise YamlError(no, "empty item in flow collection")
    if opener == "[":
        return [_scalar(item, no) for item in items]
    result: dict[str, Any] = {}
    for item in items:
        pair = _split_key(item, no)
        if pair is None:
            raise YamlError(no, "flow map entries must be 'key: value'")
        key, rest = pair
        if key in result:
            raise YamlError(no, f"duplicate key {key!r}")
        if not rest:
            result[key] = None
        elif rest[0] == "[":
            result[key] = _flow(rest, no, allow_list=False)
        else:
            result[key] = _scalar(rest, no)
    return result


def _inline(text: str, no: int) -> Any:
    if text[0] in "[{":
        return _flow(text, no)
    return _scalar(text, no)


def _is_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


class _Parser:
    def __init__(self, lines: list[_Line]) -> None:
        self.lines = lines
        self.pos = 0
        self.depth = 0

    def _enter(self, no: int) -> None:
        self.depth += 1
        if self.depth > _MAX_DEPTH:
            raise YamlError(no, f"nesting deeper than {_MAX_DEPTH} levels")

    def _nested(self, indent: int) -> Any:
        if self.pos < len(self.lines) and self.lines[self.pos].indent > indent:
            return self.block(self.lines[self.pos].indent)
        return None

    def _no_continuation(self, indent: int) -> None:
        if self.pos < len(self.lines) and self.lines[self.pos].indent > indent:
            raise YamlError(
                self.lines[self.pos].no,
                "unexpected indented line (multi-line scalars are not supported)",
            )

    def block(self, indent: int) -> Any:
        line = self.lines[self.pos]
        if line.indent != indent:
            raise YamlError(line.no, "unexpected indentation")
        if _is_item(line.text):
            return self.list_(indent)
        return self.map_(indent)

    def map_(self, indent: int) -> dict[str, Any]:
        self._enter(self.lines[self.pos].no)
        result = self._map(indent)
        self.depth -= 1
        return result

    def _map(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self.pos < len(self.lines) and self.lines[self.pos].indent == indent:
            line = self.lines[self.pos]
            if _is_item(line.text):
                raise YamlError(line.no, "list item where a 'key: value' entry was expected")
            pair = _split_key(line.text, line.no)
            if pair is None:
                raise YamlError(line.no, "expected 'key: value'")
            key, rest = pair
            if key in result:
                raise YamlError(line.no, f"duplicate key {key!r}")
            self.pos += 1
            if rest == "":
                result[key] = self._nested(indent)
            else:
                result[key] = _inline(rest, line.no)
                self._no_continuation(indent)
        if self.pos < len(self.lines) and self.lines[self.pos].indent > indent:
            raise YamlError(self.lines[self.pos].no, "unexpected indentation")
        return result

    def list_(self, indent: int) -> list[Any]:
        self._enter(self.lines[self.pos].no)
        result = self._list(indent)
        self.depth -= 1
        return result

    def _list(self, indent: int) -> list[Any]:
        result: list[Any] = []
        while (
            self.pos < len(self.lines)
            and self.lines[self.pos].indent == indent
            and _is_item(self.lines[self.pos].text)
        ):
            line = self.lines[self.pos]
            rest = line.text[1:].lstrip(" ")
            offset = len(line.text) - len(rest)
            if rest == "":
                self.pos += 1
                result.append(self._nested(indent))
            elif _is_item(rest):
                raise YamlError(line.no, "nested lists on one line are not supported")
            elif _split_key(rest, line.no) is not None:
                self.lines[self.pos] = _Line(line.no, indent + offset, rest)
                result.append(self.map_(indent + offset))
            else:
                self.pos += 1
                result.append(_inline(rest, line.no))
                self._no_continuation(indent)
        if self.pos < len(self.lines) and self.lines[self.pos].indent > indent:
            raise YamlError(self.lines[self.pos].no, "unexpected indentation")
        return result


def parse(text: str) -> Any:
    """Parse one document. Returns None for an empty document. Raises YamlError."""
    lines = _tokenize(text)
    if not lines:
        return None
    parser = _Parser(lines)
    value = parser.block(lines[0].indent)
    if parser.pos < len(lines):
        raise YamlError(lines[parser.pos].no, "unexpected content (check the indentation)")
    return value
