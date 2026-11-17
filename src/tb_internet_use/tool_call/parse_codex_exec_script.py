"""Read the tool calls in a Codex exec script without running it.

`exec` runs JavaScript that calls tools as `tools.NAME(argument)`.
Each argument is read where it is a literal, i.e. a string or template string, a number, true, false or null, an array or object of those, or a name that `const` binds once to such a value.
Any other value is left out, so the field it would fill stays empty.

A script that cannot be split into tokens, e.g. with an unclosed string, gives no calls, and Codex reports it as a SyntaxError that ran nothing.

Two tools give their ToolCallActions from the argument's content, `apply_patch` and `web__run`, so they are read here too.
"""

import re
from dataclasses import dataclass
from typing import Any, NamedTuple

from tb_internet_use.tool_call.model import (
    DeleteFileAction,
    EditFileAction,
    OtherAction,
    ToolCallAction,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    WriteFileAction,
    strings_from_values,
)

_SKIP = re.compile(r"(?:\s+|//[^\n]*|/\*[\s\S]*?\*/)+")
_NAME = re.compile(r"[A-Za-z_$\u0080-\uffff][\w$\u0080-\uffff]*")
_NUMBER = re.compile(
    r"(?:0[xXbBoO][\da-fA-F_]+|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?)n?"
)
_QUOTED = re.compile(r"""'(?:[^'\\\n]|\\[\s\S])*'|"(?:[^"\\\n]|\\[\s\S])*\"""")
# A slash stands alone, since a regex or a comment can follow an operator, e.g. `=>/a/`.
_PUNCT = re.compile(r"\.\.\.|[{}()\[\];,.]|[!%&*+\-:<=>?^|~@#]+|/")
_ESCAPE = re.compile(
    r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|\r\n|[\s\S])"
)
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v"}
# Names after which a slash starts a regex rather than a division.
_BEFORE_REGEX = frozenset(
    [
        "return",
        "typeof",
        "instanceof",
        "in",
        "of",
        "new",
        "delete",
        "void",
        "throw",
        "case",
        "do",
        "else",
        "yield",
        "await",
    ]
)


_UNREAD = object()  # a value that is not a literal
_CLOSERS = frozenset({",", ")", "]", "}", ";"})
_OPENERS = {"(": ")", "[": "]", "{": "}"}
_KEYWORD_VALUES = {"true": True, "false": False, "null": None}


_PATCH_FILE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$", re.MULTILINE)
_MOVE_TO = "*** Move to: "
_URL = re.compile(r"https?://", re.IGNORECASE)


def parse_codex_exec_script(code: str) -> list[tuple[str, Any]]:
    """List each `tools.NAME(argument)` call in the script, in order, as the name and the literal value of the argument.

    The value is None when it is not a literal.
    A call inside a loop or a branch is listed once, whether it ran or not.
    """
    try:
        tokens, _ = _tokens_from_code(code)
    except _Unreadable, ValueError:  # ValueError from a bad escape
        return []
    return _calls_from_tokens(tokens, _consts_from_tokens(tokens))


def _tokens_from_code(
    code: str, i: int = 0, in_template: bool = False
) -> tuple[list[_Token], int]:
    """Split the code from code[i] into tokens, up to its end or to the brace that closes a `${`, and give the index after them."""
    tokens: list[_Token] = []
    depth = 0
    while True:
        if skipped := _SKIP.match(code, i):
            i = skipped.end()
        if i >= len(code):
            if in_template:
                raise _Unreadable
            return tokens, i
        char = code[i]
        previous = tokens[-1] if tokens else None
        if char in "'\"":
            if not (found := _QUOTED.match(code, i)):
                raise _Unreadable
            tokens.append(_Token("string", _unescape(found[0][1:-1])))
            i = found.end()
        elif char == "`":
            template, i = _template_from_code(code, i + 1)
            tokens.append(_Token("template", template))
        elif found := _NAME.match(code, i):
            tokens.append(_Token("name", found[0]))
            i = found.end()
        elif char.isdigit() or (char == "." and code[i + 1 : i + 2].isdigit()):
            found = _NUMBER.match(code, i)
            assert found is not None
            tokens.append(_Token("number", found[0]))
            i = found.end()
        elif char == "/" and _is_regex_start_after(previous):
            end = _regex_end_from(code, i)
            tokens.append(_Token("regex", code[i:end]))
            i = end
        elif in_template and char == "}" and depth == 0:
            return tokens, i + 1
        elif found := _PUNCT.match(code, i):
            depth += {"{": 1, "}": -1}.get(found[0], 0)
            tokens.append(_Token("punct", found[0]))
            i = found.end()
        else:
            raise _Unreadable


def _template_from_code(code: str, i: int) -> tuple[_Template, int]:
    """Read the template whose text starts at code[i], after its backtick, and give the index after it."""
    raw: list[str] = []
    exprs: list[tuple[_Token, ...]] = []
    start = i
    while i < len(code):
        if code[i] == "\\":
            i += 2
        elif code[i] == "`":
            raw.append(code[start:i])
            return _Template(
                tuple(map(_unescape, raw)), tuple(raw), tuple(exprs)
            ), i + 1
        elif code.startswith("${", i):
            raw.append(code[start:i])
            tokens, i = _tokens_from_code(code, i + 2, in_template=True)
            exprs.append(tuple(tokens))
            start = i
        else:
            i += 1
    raise _Unreadable


def _unescape(text: str) -> str:
    def character_of_escape(found: re.Match[str]) -> str:
        escape = found[1]
        if escape[0] == "u" and len(escape) > 1:
            return chr(int(escape.strip("u{}"), 16))
        if escape[0] == "x" and len(escape) == 3:
            return chr(int(escape[1:], 16))
        if escape in ("\n", "\r\n", "\r", "\u2028", "\u2029"):
            return ""  # a line continuation
        return "\0" if escape == "0" else _SIMPLE_ESCAPES.get(escape, escape)

    if "\\" not in text:
        return text
    # JavaScript writes a character past U+FFFF as two escapes, a surrogate pair.
    return (
        _ESCAPE.sub(character_of_escape, text)
        .encode("utf-16", "surrogatepass")
        .decode("utf-16", "replace")
    )


def _is_regex_start_after(previous: _Token | None) -> bool:
    if previous is None:
        return True
    if previous.kind == "name":
        return previous.value in _BEFORE_REGEX
    return previous.kind == "punct" and previous.value not in (")", "]", "}")


def _regex_end_from(code: str, i: int) -> int:
    """Find the index after the regex literal that starts at code[i]."""
    j, in_class = i + 1, False
    while j < len(code) and code[j] != "\n":
        if code[j] == "\\":
            j += 1
        elif code[j] == "[":
            in_class = True
        elif code[j] == "]":
            in_class = False
        elif code[j] == "/" and not in_class:
            flags = _NAME.match(code, j + 1)
            return flags.end() if flags else j + 1
        j += 1
    raise _Unreadable


class _Unreadable(Exception):
    """Error raised inside `parse_codex_exec_script` when the script cannot be split into tokens."""


def _calls_from_tokens(
    tokens: list[_Token], consts: dict[str, Any]
) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []
    for i, token in enumerate(tokens):
        if token.kind == "template":
            for expr in token.value.exprs:
                calls.extend(_calls_from_tokens(list(expr), consts))
        elif (
            token == ("name", "tools")
            and _is_punct_at(tokens, i + 1, ".")
            and i + 2 < len(tokens)
            and tokens[i + 2].kind == "name"
            and _is_punct_at(tokens, i + 3, "(")
        ):
            argument, end = _value_from_tokens(tokens, i + 4, consts)
            if argument is _UNREAD or not (
                _is_punct_at(tokens, end, ",") or _is_punct_at(tokens, end, ")")
            ):
                argument = None
            calls.append((tokens[i + 2].value, argument))
    return calls


def _consts_from_tokens(tokens: list[_Token]) -> dict[str, Any]:
    """Find the names that `const` binds to a literal, when the script declares them once."""
    declared: dict[str, int] = {}
    for i, token in enumerate(tokens[:-1]):
        if token.kind == "name" and token.value in ("const", "let", "var"):
            name = tokens[i + 1]
            declared[name.value] = declared.get(name.value, 0) + (name.kind == "name")
    consts: dict[str, Any] = {}
    for i, token in enumerate(tokens[:-3]):
        name = tokens[i + 1].value
        if (
            token == ("name", "const")
            and declared.get(name) == 1
            and _is_punct_at(tokens, i + 2, "=")
        ):
            value, _ = _value_from_tokens(tokens, i + 3, consts)
            if value is not _UNREAD:
                consts[name] = value
    return consts


def _value_from_tokens(
    tokens: list[_Token], i: int, consts: dict[str, Any]
) -> tuple[Any, int]:
    """Read the literal value of the expression at tokens[i], and the index after it."""
    value, j = _literal_from_tokens(tokens, i, consts)
    # Anything but a closer, or a name that starts the next statement, continues
    # the expression, e.g. "a" + b or a template that tags the value.
    after = tokens[j] if j < len(tokens) else None
    if (
        after
        and after.kind != "name"
        and not (after.kind == "punct" and after.value in _CLOSERS)
    ):
        return _UNREAD, _expression_end_from(tokens, j)
    return value, j


def _literal_from_tokens(
    tokens: list[_Token], i: int, consts: dict[str, Any]
) -> tuple[Any, int]:
    if i >= len(tokens):
        return _UNREAD, i
    kind, value = tokens[i]
    if kind == "string":
        return value, i + 1
    if kind == "number":
        return _number_from_text(value), i + 1
    if kind == "template":
        return _value_of_template(value, value.cooked, consts), i + 1
    if tokens[i : i + 3] == [("name", "String"), ("punct", "."), ("name", "raw")]:
        raw = tokens[i + 3] if i + 3 < len(tokens) else None
        if raw and raw.kind == "template":
            return _value_of_template(raw.value, raw.value.raw, consts), i + 4
    if kind == "name":
        return _KEYWORD_VALUES.get(value, consts.get(value, _UNREAD)), i + 1
    if _is_punct_at(tokens, i, "["):
        return _array_from_tokens(tokens, i + 1, consts)
    if _is_punct_at(tokens, i, "{"):
        return _object_from_tokens(tokens, i + 1, consts)
    return _UNREAD, i + 1


def _value_of_template(
    template: _Template, parts: tuple[str, ...], consts: dict[str, Any]
) -> Any:
    text = parts[0]
    for expr, part in zip(template.exprs, parts[1:], strict=True):
        value, end = _value_from_tokens(list(expr), 0, consts)
        if end != len(expr) or isinstance(value, (list, dict)) or value is _UNREAD:
            return _UNREAD
        text += _js_text_of(value) + part
    return text


def _array_from_tokens(
    tokens: list[_Token], i: int, consts: dict[str, Any]
) -> tuple[Any, int]:
    items: list[Any] = []
    while not _is_punct_at(tokens, i, "]"):
        if i >= len(tokens):
            return _UNREAD, i
        item, i = _value_from_tokens(tokens, i, consts)
        if not (
            _is_punct_at(tokens, i, ",") or _is_punct_at(tokens, i, "]")
        ):  # e.g. "a" in b
            item, i = _UNREAD, max(_expression_end_from(tokens, i), i + 1)
        items.append(item)
        i += _is_punct_at(tokens, i, ",")
    if any(item is _UNREAD for item in items):
        return _UNREAD, i + 1
    return items, i + 1


def _object_from_tokens(
    tokens: list[_Token], i: int, consts: dict[str, Any]
) -> tuple[Any, int]:
    """Read an object of the keys whose values are literals. Other keys are left out."""
    found: dict[str, Any] = {}
    while not _is_punct_at(tokens, i, "}"):
        if i >= len(tokens):
            return _UNREAD, i
        kind, key = tokens[i]
        if kind in ("name", "string", "number") and _is_punct_at(tokens, i + 1, ":"):
            value, i = _value_from_tokens(tokens, i + 2, consts)
        elif kind == "name" and (
            _is_punct_at(tokens, i + 1, ",") or _is_punct_at(tokens, i + 1, "}")
        ):
            value, i = consts.get(key, _UNREAD), i + 1  # a shorthand such as {cmd}
        else:  # a spread, a computed key or a method
            value, i = _UNREAD, max(_expression_end_from(tokens, i), i + 1)
        if not (
            _is_punct_at(tokens, i, ",") or _is_punct_at(tokens, i, "}")
        ):  # e.g. "a" in b
            value, i = _UNREAD, max(_expression_end_from(tokens, i), i + 1)
        if value is not _UNREAD:
            found[str(key)] = value
        i += _is_punct_at(tokens, i, ",")
    return found, i + 1


@dataclass(frozen=True, slots=True)
class _Template:
    cooked: tuple[str, ...]  # the text parts with escapes applied
    raw: tuple[str, ...]  # the text parts as written, for String.raw
    exprs: tuple[tuple[_Token, ...], ...]  # the tokens of each ${...}


def _is_punct_at(tokens: list[_Token], i: int, value: str) -> bool:
    return i < len(tokens) and tokens[i] == ("punct", value)


def _number_from_text(text: str) -> Any:
    text = text.replace("_", "").rstrip("n")
    try:
        if text[:2].lower() in ("0x", "0b", "0o"):
            return int(text, 0)
        return float(text) if any(c in text for c in ".eE") else int(text)
    except ValueError:
        return _UNREAD


def _js_text_of(value: str | bool | float | None) -> str:
    """Write a literal as JavaScript writes it into a string."""
    if isinstance(value, bool) or value is None:
        return {True: "true", False: "false", None: "null"}[value]
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _expression_end_from(tokens: list[_Token], i: int) -> int:
    """Find the index of the separator or closer that ends the expression at tokens[i]."""
    closers: list[str] = []
    while i < len(tokens):
        kind, value = tokens[i]
        if kind == "punct" and value in _OPENERS:
            closers.append(_OPENERS[value])
        elif kind == "punct" and closers and value == closers[-1]:
            closers.pop()
        elif kind == "punct" and not closers and value in _CLOSERS:
            return i
        i += 1
    return i


class _Token(NamedTuple):
    kind: str  # name, number, string, template, regex or punct
    value: Any


def actions_from_patch(patch: str) -> list[ToolCallAction]:
    """List the file changes of an apply_patch patch as ToolCallActions, in order.

    An added file is a write, each hunk that changes an updated file an edit, and a deleted file a DeleteFileAction, as for the delete tool of any harness.
    A hunk that changes nothing, which only places the next one, gives no ToolCallAction.
    """
    actions: list[ToolCallAction] = []
    headers = list(_PATCH_FILE.finditer(patch))
    for k, header in enumerate(headers):
        kind, path = header[1], header[2].strip()
        end = headers[k + 1].start() if k + 1 < len(headers) else None
        lines = patch[header.end() : end].split("\n")[1:]
        lines = [line for line in lines if not line.startswith("*** End")]
        while lines and not lines[-1]:
            lines.pop()
        if kind == "Delete":
            actions.append(DeleteFileAction(path))
        elif kind == "Add":
            content = "".join(line[1:] + "\n" for line in lines if line.startswith("+"))
            actions.append(WriteFileAction(path, content))
        else:
            if lines and lines[0].startswith(_MOVE_TO):
                path = lines.pop(0).removeprefix(_MOVE_TO).strip()
            actions.extend(
                EditFileAction(path, old, new)
                for old, new in _hunk_changes_from_lines(lines)
            )
    return actions


def _hunk_changes_from_lines(lines: list[str]) -> list[tuple[str, str]]:
    """List the old and new text of each hunk that changes something. Hunks start at `@@`."""
    hunks: list[list[str]] = [[]]
    for line in lines:
        if line.startswith("@@"):
            hunks.append([])
        else:
            hunks[-1].append(line)
    return [
        (
            "\n".join(line[1:] for line in hunk if line[:1] in (" ", "-", "")),
            "\n".join(line[1:] for line in hunk if line[:1] in (" ", "+", "")),
        )
        for hunk in hunks
        if any(line[:1] in ("+", "-") for line in hunk)
    ]


def actions_from_web_run_argument(argument: dict[str, Any]) -> list[ToolCallAction]:
    """List one ToolCallAction per kind of request in a web__run argument, in the order given.

    Pages are named by a URL or by a reference to an earlier result, such as `turn0search1`, and only URLs fill `urls`.
    """
    actions: list[ToolCallAction] = []
    for key, value in argument.items():
        requests = [
            r
            for r in (value if isinstance(value, list) else [value])
            if isinstance(r, dict)
        ]
        match key:
            case "search_query" | "image_query":
                queries = strings_from_values([r.get("q") for r in requests])
                actions.append(WebSearchAction(queries))
            case "open":
                actions.append(WebFetchAction(_urls_from_requests(requests)))
            case "find":
                actions.append(WebFindAction(_urls_from_requests(requests)))
            case "click" | "screenshot":
                actions.append(OtherAction())
    return actions


def _urls_from_requests(requests: list[dict[str, Any]]) -> tuple[str, ...]:
    refs = (str(r.get("ref_id")) for r in requests)
    return strings_from_values([ref for ref in refs if _URL.match(ref)])
