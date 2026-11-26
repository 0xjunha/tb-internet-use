"""Find the call sites of a Python or JavaScript code text and the names it gives one string or one call to, reading only its names, strings, comments and brackets.

Code that a command runs can send a request that no word of the command shows, e.g. `requests.get(u)` in get.py run by `python get.py`.
The code is read as text and never run, so a call is found by its form, a name right before `(`, and not by what the name is bound to.
For example `r.get(u)` stays `r.get` after `import requests as r`.
Whether a call sends a request is a fact of the code call catalog, so the reading knows no library.
The exceptions are the full names that the imports of a text bind to names and the bare names that a Python text binds to something else, which the reading records although they say nothing of a call on their own.
So `r` of `r.get(u)` can be read as `requests` after `import requests as r`.
A call such as `requests.get(rid)` has the form of a call of the library `requests` also where `requests` is a dict, and only these names tell the two apart, e.g. `requests = {}` and no `import requests` in the text.

Text after a multi-line string, a template string or a block comment that never closes is not read, and `ParsedCode.unreadable_text_start` says from where.

Known limits
- A JavaScript regular expression literal is read as code, since only a parser tells it from a division. So `//` in it starts a comment and a quote or backtick in it starts a string, e.g. in `/https?:\\/\\//` or `/`/`. A backtick that never closes sets `unreadable_text_start`.
- A quote `'` or `"` that does not close ends at the line break, so the rest of its line is not read, e.g. `fetch(u)` in `x = /'/; fetch(u)`.
- Python binds a name also as a tuple target, by `with … as` or `except … as`, as the variable of a comprehension or of a `for` that does not start its line, and after `;`, none of which is read, e.g. `requests` of `requests, n = load()`. An attribute such as `self.requests = {}` binds no bare name. A call through such a name stays the call of the module, e.g. `self.requests.get(rid)`.
- An import is read at the start of a line or after `;`, by its form alone and outside comments, so a line of a multi-line string that starts with `import` counts too. A Python import that a backslash continues on the next line is read only up to the backslash, and `from a import *` binds no name that the text shows. A JavaScript `import { … }` is read only when its braces close on its line, and neither `import("y")` nor a call of a member of `require("y")` is read, e.g. `execSync` of `require("child_process").execSync(c)`.
- A Python f-string that holds its own quote inside braces, e.g. `f"{d["k"]}"`, ends at that quote. A JavaScript template literal nested in `${}` ends the same way.
"""

import keyword
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from enum import Enum

from tb_internet_use.expanded_tool_call.model import CodeLanguage
from tb_internet_use.network_request.model import (
    CodeCall,
    CodeCallAssignment,
    CodeStringAssignment,
    ParsedCode,
    UnreadableCodeCallArguments,
)

_CLOSER_OF_OPENER = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = frozenset(_CLOSER_OF_OPENER.values())
_WHITESPACE = re.compile(r"\s+")
# A number, with the letters and dots that can follow its first digit, e.g. `8000`, `0x1F` or `1.5`.
_NUMBER = re.compile(r"\d[\w.]*")
# The punctuation that reads from a name right after it, so that an argument that starts with the name does not start with its value, e.g. `[` of `urls[0] + path`.
_PUNCTUATION_THAT_READS_FROM_A_NAME = frozenset({"(", ".", "["})
# The tokens right before a parameter of a `def` or `lambda`, e.g. `,` before `pk` in `def plan(requests, pk)`.
_TOKENS_BEFORE_A_PARAMETER = frozenset({"(", ",", "*"})
# What follows the variable of a `for` loop that is one bare name, e.g. ` in` of `for requests in batches:`.
_LOOP_VARIABLE_END = re.compile(r"[ \t]+in\b")
# The words before a name that make it the name of a definition, so its parenthesis opens no call, e.g. `def fetch(url)`.
_DEFINING_WORDS = frozenset({"def", "class", "function"})
# The reserved words of JavaScript, e.g. `if` in `if (ok)`.
_JAVASCRIPT_KEYWORDS = frozenset(
    {
        "await",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "continue",
        "debugger",
        "default",
        "delete",
        "do",
        "else",
        "export",
        "extends",
        "false",
        "finally",
        "for",
        "function",
        "if",
        "import",
        "in",
        "instanceof",
        "let",
        "new",
        "null",
        "return",
        "super",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "var",
        "void",
        "while",
        "with",
        "yield",
    }
)
# A string body that ends at its quote or before a line break, which leaves the string unclosed, as Python and JavaScript read `'…'` and `"…"`.
_SINGLE_LINE_STRING_BODY_OF_QUOTE = {
    quote: re.compile(
        rf"((?:[^{quote}\\\n]|\\(?:.|\Z))*)(?:({quote})|(?=\n)|\Z)", re.DOTALL
    )
    for quote in ("'", '"')
}
# What follows the closing parenthesis of a JavaScript definition that is written like a call, e.g. ` {` after `async fetch(url)` in a class body.
_JAVASCRIPT_DEFINITION_BODY_START = re.compile(r"\s*\{")
# A string body that may span lines, as Python reads `'''…'''` and `"""…"""` and JavaScript reads a template literal.
_MULTI_LINE_STRING_BODY_OF_DELIMITER = {
    delimiter: re.compile(
        rf"((?:[^\\]|\\(?:.|\Z))*?)(?:({re.escape(delimiter)})|\Z)", re.DOTALL
    )
    for delimiter in ("'''", '"""', "`")
}


@dataclass(frozen=True, slots=True)
class _CodeSyntax:
    """Syntax of one code language that `parse_code` reads, i.e. its names, keywords, comments, strings and declarations."""

    # A name with its dotted parts, e.g. `urllib.request.urlopen`.
    dotted_name: re.Pattern[str]
    # What follows the closing parenthesis of a definition that is written like a call, None in a language without one.
    definition_body_start: re.Pattern[str] | None
    keywords: frozenset[str]
    # The start of a comment that ends at a line break, e.g. `#` or `//`.
    line_comment_start: str
    has_block_comments: bool
    # The letters that may come right before a quote and are no part of the string value, e.g. `f` of `f"x"`.
    string_prefix: re.Pattern[str] | None
    string_delimiters: tuple[str, ...]
    # An assignment to a bare name at the start of a line, up to the value, e.g. `const URL = `.
    assignment_start: re.Pattern[str]
    # What may follow the value of such an assignment, e.g. a line break or `;`.
    assignment_end: re.Pattern[str]
    # Whether the bare names that an assignment, a parameter or a loop binds are recorded, only for Python.
    records_bound_names: bool


_PYTHON_NAME = r"[^\W\d]\w*"
_JAVASCRIPT_NAME = r"(?:[^\W\d]|\$)[\w$]*"
# The pattern of a bare name of each code language, e.g. `$url` in JavaScript, also for reading the name in a placeholder of a string, e.g. `{BASE}` of `f"{BASE}/x"`.
BARE_NAME_PATTERN_OF_LANGUAGE = {
    CodeLanguage.PYTHON: _PYTHON_NAME,
    CodeLanguage.JAVASCRIPT: _JAVASCRIPT_NAME,
}
# A Python `import` statement at the start of a line or after `;`, after optional indentation, up to the end of the statement, e.g. `import os, sys` in `    import os, sys  # x`.
_PYTHON_IMPORT_STATEMENT = re.compile(
    r"(?:^|;)[ \t]*import[ \t]+([^#;\n]*)", re.MULTILINE
)
# One module of an import statement with its first dotted part and an optional `as` name, e.g. `urllib.request` or `requests as rq`.
_PYTHON_IMPORTED_MODULE = re.compile(
    rf"\s*(({_PYTHON_NAME})(?:\.{_PYTHON_NAME})*)(?:\s+as\s+({_PYTHON_NAME}))?\s*"
)
# The start of a Python `from` statement at the start of a line or after `;`, up to the names it imports, with its module, which may be relative, e.g. `from urllib.request import ` or `from .net import `.
_PYTHON_FROM_IMPORT_START = re.compile(
    rf"(?:^|;)[ \t]*from[ \t]+(\.*(?:{_PYTHON_NAME}(?:\.{_PYTHON_NAME})*)?)[ \t]+import[ \t]*",
    re.MULTILINE,
)
# The names of a `from` statement in parentheses, which may span lines, e.g. `(urlopen,\n Request)`. A name list that holds another parenthesis is not read, so that a list that never closes is not read to the end of the code once for each such statement.
_PYTHON_FROM_IMPORT_NAMES_IN_PARENTHESES = re.compile(r"\(([^()]*)\)")
# The names of a `from` statement up to the end of the statement when they are not in parentheses, e.g. `urlopen, Request` of `from urllib.request import urlopen, Request  # x`.
_PYTHON_FROM_IMPORT_NAMES = re.compile(r"[^#;\n(]*")
# A comment in the parentheses of a `from` statement, e.g. `# for the port check`.
_PYTHON_COMMENT = re.compile(r"#[^\n]*")
# One name of a `from` statement with an optional `as` name, e.g. `urlopen` or `urlopen as fetch_url`.
_PYTHON_IMPORTED_NAME = re.compile(
    rf"\s*({_PYTHON_NAME})(?:\s+as\s+({_PYTHON_NAME}))?\s*"
)
# The calls whose value is the module that their first string names, with whether the value is the top-level package of a dotted name, as `__import__("os.path")` gives `os` while `importlib.import_module("os.path")` gives `os.path`.
_IS_TOP_LEVEL_PACKAGE_OF_IMPORTING_CALL_NAME = {
    "__import__": True,
    "importlib.import_module": False,
}
# A Python assignment of one call that imports to a bare name, at the start of a line or after `;`, whose only argument is one string and which ends its statement, e.g. `sp = __import__("subprocess")`.
_PYTHON_IMPORTING_CALL_ASSIGNMENT = re.compile(
    rf"(?:^|;)[ \t]*({_PYTHON_NAME})[ \t]*=[ \t]*(__import__|importlib\.import_module)\([ \t]*(['\"])([^'\"\n]*)\3[ \t]*\)[ \t]*(?=;|\n|$)",
    re.MULTILINE,
)
# A JavaScript `import` statement at the start of a line or after `;`, with what it binds and the module, e.g. `import { execSync } from "node:child_process"`, `import http from "http"` or `import * as cp from "child_process"`.
_JAVASCRIPT_IMPORT_STATEMENT = re.compile(
    rf"(?:^|;)[ \t]*import[ \t]*(?:\*[ \t]*as[ \t]+({_JAVASCRIPT_NAME})|\{{([^{{}};\n]*)\}}|({_JAVASCRIPT_NAME}))[ \t]*from[ \t]*(['\"])([^'\"\n]*)\4",
    re.MULTILINE,
)
# A JavaScript binding of what `require` gives, a module or one of its members, to a bare name or to the names of braces, e.g. `cp = require("child_process")`, `{ execSync } = require("child_process")` or `run = require("child_process").execSync`.
_JAVASCRIPT_REQUIRE_BINDING = re.compile(
    rf"(?<![\w$.])(?:({_JAVASCRIPT_NAME})|\{{([^{{}};\n]*)\}})[ \t]*=[ \t]*require\([ \t]*(['\"])([^'\"\n]*)\3[ \t]*\)(?:\.({_JAVASCRIPT_NAME}))?"
)
# One name in the braces of a JavaScript `import` statement, with the name it is bound to when that differs, e.g. `execSync` or `execSync as run`.
_JAVASCRIPT_IMPORTED_NAME = re.compile(
    rf"\s*({_JAVASCRIPT_NAME})(?:\s+as\s+({_JAVASCRIPT_NAME}))?\s*"
)
# One name in the braces of a JavaScript `require` binding, with the name it is bound to when that differs, e.g. `execSync` or `execSync: run`.
_JAVASCRIPT_REQUIRED_NAME = re.compile(
    rf"\s*({_JAVASCRIPT_NAME})(?:\s*:\s*({_JAVASCRIPT_NAME}))?\s*"
)
# The prefix of a JavaScript module name that names a built-in module of Node.js, which is the same module without it, e.g. `node:child_process`.
_NODE_BUILT_IN_MODULE_PREFIX = "node:"
# Any character but a line break, which a comment is blanked out by before imports are read.
_SPACES_OF_NON_LINE_BREAKS = re.compile(r"[^\n]")
_SYNTAX_OF_LANGUAGE = {
    CodeLanguage.PYTHON: _CodeSyntax(
        dotted_name=re.compile(rf"{_PYTHON_NAME}(?:\.{_PYTHON_NAME})*"),
        definition_body_start=None,
        keywords=frozenset(keyword.kwlist),
        line_comment_start="#",
        has_block_comments=False,
        string_prefix=re.compile(r"(?:[rR][fFbB]?|[fFbB][rR]?|[uU])(?=['\"])"),
        string_delimiters=('"""', "'''", '"', "'"),
        assignment_start=re.compile(rf"({_PYTHON_NAME})[ \t]*(?::[^=\n#]*)?=[ \t]*"),
        assignment_end=re.compile(r"[ \t]*(?:;|#|\n|\Z)"),
        records_bound_names=True,
    ),
    CodeLanguage.JAVASCRIPT: _CodeSyntax(
        dotted_name=re.compile(rf"{_JAVASCRIPT_NAME}(?:\.{_JAVASCRIPT_NAME})*"),
        definition_body_start=_JAVASCRIPT_DEFINITION_BODY_START,
        keywords=_JAVASCRIPT_KEYWORDS,
        line_comment_start="//",
        has_block_comments=True,
        string_prefix=None,
        string_delimiters=("`", '"', "'"),
        assignment_start=re.compile(
            rf"(?:export[ \t]+)?(?:(?:const|let|var)[ \t]+)?({_JAVASCRIPT_NAME})[ \t]*=[ \t]*"
        ),
        assignment_end=re.compile(r"[ \t]*(?:;|//|\n|\Z)"),
        records_bound_names=False,
    ),
}


@dataclass(frozen=True, slots=True)
class _ArgumentToken:
    """Token of a call argument that `parse_code` keeps to tell whether the argument is one string, one bare name or one call, or starts with a bare name."""

    argument_token_kind: _ArgumentTokenKind
    text: str
    # The 0-based place of the call among the opened calls of the code, as `_OpenCall.code_call_index` counts it, for a token of kind `CALL` only.
    code_call_index: int | None = None


class _ArgumentTokenKind(Enum):
    """Kind of a token of a call argument, as far as `parse_code` tells the first argument apart."""

    STRING = "string"  # a string that closes
    NAME = "name"  # a bare name that is no keyword, e.g. `URL`
    CALL = "call"  # the name of a call, e.g. `g` in `f(g(1))`
    OTHER = "other"  # anything else, e.g. `self.url`, `+` or `(`


@dataclass(slots=True)
class _OpenCall:
    """Call whose opening parenthesis `parse_code` has read and whose closing one it has not, collecting its strings and arguments."""

    name: str
    # The 0-based index of its place among the opened calls of the code, in text order, where a definition written like a call also takes a place.
    code_call_index: int
    # The 0-based position in the code right after its opening parenthesis.
    argument_start: int
    string_literals: list[str] = field(default_factory=list)
    # The first few tokens of the argument being read, enough to tell `url="x"` from one string.
    argument_tokens: list[_ArgumentToken] = field(default_factory=list)
    argument_token_count: int = 0
    argument_count: int = 0
    # The value of the first argument when it is positional and one token.
    first_positional_value: _ArgumentToken | None = None
    # The bare name that the first argument starts with when it is positional and more of it follows the name.
    first_positional_leading_name: str | None = None
    is_first_argument_keyword: bool = False
    # The value of the argument named `url` when it is one token.
    url_argument_value: _ArgumentToken | None = None
    # The bare name that the value of the argument named `url` starts with when more of the value follows the name.
    url_argument_leading_name: str | None = None
    # The name that the call is assigned to when the call starts the value of an assignment, which holds only the call if nothing but the end of the statement follows its closing parenthesis.
    assigned_name: str | None = None


@dataclass(frozen=True, slots=True)
class _OpenBracket:
    """Bracket whose opener `parse_code` has read and whose closer it has not, with the call that owns the strings inside it."""

    closer: str
    # The call that the bracket opens, None for a bracket that follows no name, e.g. the inner `(` of `f(("api", 8000))`.
    open_call: _OpenCall | None
    # The innermost call around the bracket, which owns the strings in it.
    string_owner: _OpenCall | None
    # Whether the bracket holds the parameters of a Python `def`, e.g. `(requests, pk)` of `def plan(requests, pk):`.
    is_parameter_list: bool = False


@dataclass(slots=True)
class _CodeReadingState:
    """Reading state kept during one `parse_code` call, shared by the functions that read one token each."""

    code: str
    code_syntax: _CodeSyntax
    open_brackets: list[_OpenBracket] = field(default_factory=list)
    # The closers of the open brackets, counted so that a closer without an opener is found without a walk of the brackets.
    open_closer_counts: Counter[str] = field(default_factory=Counter)
    # The calls in text order, None while a call is open and for a definition written like a call, e.g. `async fetch(url) {` in a JavaScript class body.
    code_calls: list[CodeCall | None] = field(default_factory=list)
    string_assignments: list[CodeStringAssignment] = field(default_factory=list)
    # The assignments of one call, whose `code_call_index` is the place of the call among the opened calls until `_parsed_code_from` turns it into an index of `ParsedCode.code_calls`.
    call_assignments: list[CodeCallAssignment] = field(default_factory=list)
    # The names assigned by an assignment whose value starts with a call, by the 0-based position of the name of that call, e.g. `req` at the position of `Request` in `req = Request(u)`.
    assigned_name_of_call_name_start: dict[int, str] = field(default_factory=dict)
    is_at_line_start: bool = True
    # The 0-based position of the token that starts the current line, e.g. of `for` in `for requests in batches:`.
    line_start_token_position: int | None = None
    # The text of the token before the current one, e.g. `def` before `fetch` in `def fetch(url)`.
    previous_token_text: str = ""
    # Whether the next `(` opens the parameters of a `def`, set by the name after `def`.
    is_next_bracket_parameter_list: bool = False
    # The 0-based position after a `for` that starts a line, so that the name right after it is read as the loop variable.
    line_start_for_end: int | None = None
    # The number of open brackets around a `lambda` whose parameters are being read, None outside them, e.g. 1 inside `sorted(xs, key=lambda requests, ` before its `:`.
    lambda_parameter_bracket_count: int | None = None
    # The bare names that an assignment at the start of a line, a parameter of a `def` or `lambda` or the variable of a `for` loop binds, e.g. `requests` of `requests = {}`.
    names_bound_by_assignment_parameter_or_loop: set[str] = field(default_factory=set)
    unreadable_text_start: int | None = None
    # The 0-based start and end of each comment, so that an import in a comment is not read, e.g. `// const fetch = require("node-fetch")`.
    comment_spans: list[tuple[int, int]] = field(default_factory=list)


def parse_code(code: str, code_language: CodeLanguage) -> ParsedCode:
    """Find the calls of a code text with their strings and first argument, the assignments of one string or one call to a name at the start of a line, the full names that its imports bind to names and the bare names that Python binds otherwise.

    A call is a name, bare or dotted, right before `(`, e.g. `requests.get(` or `fetch(`, outside strings and comments.
    A string belongs to the innermost call whose parentheses hold it, so in `print(requests.get("https://a.org/x"))` it belongs to `requests.get`.
    A call whose parentheses do not close, e.g. in a text cut short, gets `UnreadableCodeCallArguments` and no strings.
    The text is read in one pass, but each closed call copies the text between its parentheses into `argument_text`.
    So nested calls take time and memory in proportion to the length of the text times the depth of the nesting, e.g. about 96 million characters for `f(` 8000 times followed by `)` 8000 times.
    """
    state = _CodeReadingState(code, _SYNTAX_OF_LANGUAGE[code_language])
    position = 0
    while position < len(code):
        position = _read_token(state, position)
    for open_bracket in reversed(state.open_brackets):
        if open_bracket.open_call is not None:
            _close_call_unreadable(state, open_bracket.open_call)
    code_without_comments = _code_without_comments_of(code, state.comment_spans)
    if code_language == CodeLanguage.PYTHON:
        import_bindings = [
            *_import_bindings_of_python_statements(code_without_comments),
            *_import_bindings_of_python_importing_calls(code_without_comments),
        ]
    else:
        import_bindings = _import_bindings_of_javascript_statements(
            code_without_comments
        )
    return _parsed_code_from(state, _imported_full_names_by_name_of(import_bindings))


def _code_without_comments_of(code: str, comment_spans: list[tuple[int, int]]) -> str:
    """Give the code with each comment replaced by spaces, keeping its line breaks so that lines still start where they did, e.g. `x = 1` and a blank line for `x = 1  # import requests as rq` and a line of `/* … */`."""
    if not comment_spans:
        return code
    parts: list[str] = []
    position = 0
    for comment_start, comment_end in comment_spans:
        parts.append(code[position:comment_start])
        parts.append(
            _SPACES_OF_NON_LINE_BREAKS.sub(" ", code[comment_start:comment_end])
        )
        position = comment_end
    parts.append(code[position:])
    return "".join(parts)


@dataclass(frozen=True, slots=True)
class _ImportBinding:
    """Binding of a name by one import of a code text, which `parse_code` gathers into `ParsedCode.imported_full_names_by_name`, e.g. `rq` to `requests` for `import requests as rq`."""

    # The 0-based position of the import in the code, so that the full names of a name keep the order of the text.
    position: int
    name: str
    # The dotted name of the module or of its member that the name stands for, e.g. `urllib.request.urlopen`.
    full_name: str


def _import_bindings_of_python_statements(code: str) -> list[_ImportBinding]:
    """Find the names that the `import` and `from` statements of a Python text bind, e.g. `rq` to `requests` for `import requests as rq` or `fetch_url` to `urllib.request.urlopen` for `from urllib.request import urlopen as fetch_url`.

    `import urllib.request` binds `urllib` to `urllib`, since only its first dotted part becomes a name, and a relative module keeps its dots, e.g. `.net.urlopen` for `urlopen` of `from .net import urlopen`.
    A statement counts at the start of any line after optional indentation and after `;`, so an import inside a function or a `try` counts too, and so does `import json` of `import os; import json`.
    The names of a `from` statement may span lines inside parentheses, e.g. `from urllib.request import (` with `urlopen,` and `Request,` on the next lines.
    """
    import_bindings: list[_ImportBinding] = []
    for import_statement_match in _PYTHON_IMPORT_STATEMENT.finditer(code):
        for imported_module_text in import_statement_match.group(1).split(","):
            imported_module_match = _PYTHON_IMPORTED_MODULE.fullmatch(
                imported_module_text
            )
            if imported_module_match is None:
                continue
            module_name, first_module_name_part, bound_name = (
                imported_module_match.groups()
            )
            import_bindings.append(
                _ImportBinding(
                    import_statement_match.start(),
                    first_module_name_part if bound_name is None else bound_name,
                    first_module_name_part if bound_name is None else module_name,
                )
            )
    for from_import_start_match in _PYTHON_FROM_IMPORT_START.finditer(code):
        names_start = from_import_start_match.end()
        names_in_parentheses_match = _PYTHON_FROM_IMPORT_NAMES_IN_PARENTHESES.match(
            code, names_start
        )
        if names_in_parentheses_match is not None:
            names_text = _PYTHON_COMMENT.sub("", names_in_parentheses_match.group(1))
        else:
            names_match = _PYTHON_FROM_IMPORT_NAMES.match(code, names_start)
            assert names_match is not None  # The pattern matches an empty text.
            names_text = names_match.group()
        module_name = from_import_start_match.group(1)
        for imported_name_text in names_text.split(","):
            imported_name_match = _PYTHON_IMPORTED_NAME.fullmatch(imported_name_text)
            if imported_name_match is None:
                continue
            imported_name, bound_name = imported_name_match.groups()
            import_bindings.append(
                _ImportBinding(
                    from_import_start_match.start(),
                    imported_name if bound_name is None else bound_name,
                    _full_name_of_member(module_name, imported_name),
                )
            )
    return import_bindings


def _full_name_of_member(module_name: str, member_name: str) -> str:
    """Give the full name of a member of a module, e.g. `urllib.request.urlopen`, `.net.urlopen` of the relative module `.net` or `.urlopen` of the relative module `.`."""
    if module_name.endswith("."):
        return module_name + member_name
    return f"{module_name}.{member_name}"


def _import_bindings_of_python_importing_calls(code: str) -> list[_ImportBinding]:
    """Find the names that a Python text assigns a module to by a call that imports, e.g. `sp` to `subprocess` for `sp = __import__("subprocess")`.

    `__import__` gives the top-level package of a dotted name, so `x = __import__("os.path")` binds `x` to `os`, while `x = importlib.import_module("os.path")` binds it to `os.path`.
    """
    import_bindings: list[_ImportBinding] = []
    for importing_call_match in _PYTHON_IMPORTING_CALL_ASSIGNMENT.finditer(code):
        name, importing_call_name, _, module_name = importing_call_match.groups()
        is_top_level_package = _IS_TOP_LEVEL_PACKAGE_OF_IMPORTING_CALL_NAME[
            importing_call_name
        ]
        import_bindings.append(
            _ImportBinding(
                importing_call_match.start(),
                name,
                module_name.split(".")[0] if is_top_level_package else module_name,
            )
        )
    return import_bindings


def _import_bindings_of_javascript_statements(code: str) -> list[_ImportBinding]:
    """Find the names that the `import` statements and the `require` bindings of a JavaScript text bind, e.g. `execSync` to `child_process.execSync` for `const { execSync } = require("node:child_process")`.

    A name bound to the default export or to all of a module stands for the module, e.g. `http` of `import http from "http"` or `cp` of `import * as cp from "child_process"`, as Node.js gives the module itself for both.
    A module name with the prefix `node:` names the same built-in module, so the prefix is dropped.
    """
    import_bindings: list[_ImportBinding] = []
    for import_statement_match in _JAVASCRIPT_IMPORT_STATEMENT.finditer(code):
        namespace_name, names_text, default_name, _, module_name = (
            import_statement_match.groups()
        )
        import_bindings += _javascript_import_bindings_of(
            import_statement_match.start(),
            _JAVASCRIPT_IMPORTED_NAME,
            _javascript_module_name_of(module_name),
            namespace_name or default_name,
            names_text,
        )
    for require_binding_match in _JAVASCRIPT_REQUIRE_BINDING.finditer(code):
        bound_name, names_text, _, module_name, member_name = (
            require_binding_match.groups()
        )
        full_name = _javascript_module_name_of(module_name)
        if member_name is not None:
            full_name = f"{full_name}.{member_name}"
        import_bindings += _javascript_import_bindings_of(
            require_binding_match.start(),
            _JAVASCRIPT_REQUIRED_NAME,
            full_name,
            bound_name,
            names_text,
        )
    return import_bindings


def _javascript_module_name_of(module_name: str) -> str:
    """Give the module name that a JavaScript import names, without the prefix `node:` of a built-in module, e.g. `child_process` of `node:child_process`."""
    return module_name.removeprefix(_NODE_BUILT_IN_MODULE_PREFIX)


def _javascript_import_bindings_of(
    position: int,
    imported_name_pattern: re.Pattern[str],
    full_name: str,
    bound_name: str | None,
    names_text: str | None,
) -> list[_ImportBinding]:
    """Give the names that one JavaScript `import` or `require` at a 0-based position binds, the bare name bound to what it gives or else each name in its braces bound to a member of it, read by the pattern of one name in such braces, e.g. `run` to `child_process.execSync` for `execSync as run` in `import { execSync as run } from "child_process"`."""
    if bound_name is not None:
        return [_ImportBinding(position, bound_name, full_name)]
    import_bindings: list[_ImportBinding] = []
    for imported_name_text in (names_text or "").split(","):
        imported_name_match = imported_name_pattern.fullmatch(imported_name_text)
        if imported_name_match is None:
            continue
        member_name, other_bound_name = imported_name_match.groups()
        import_bindings.append(
            _ImportBinding(
                position,
                member_name if other_bound_name is None else other_bound_name,
                f"{full_name}.{member_name}",
            )
        )
    return import_bindings


def _imported_full_names_by_name_of(
    import_bindings: list[_ImportBinding],
) -> dict[str, tuple[str, ...]]:
    """Give the distinct full names that the imports of a text bind to each name, in the order of the text, e.g. `("requests", "httpx")` for `http` of `import requests as http` in a `try` and `import httpx as http` in its `except`, since the text does not show which import ran."""
    full_names_by_name: dict[str, dict[str, None]] = {}
    for import_binding in sorted(
        import_bindings, key=lambda import_binding: import_binding.position
    ):
        full_names_by_name.setdefault(import_binding.name, {})[
            import_binding.full_name
        ] = None
    return {name: tuple(full_names) for name, full_names in full_names_by_name.items()}


def _parsed_code_from(
    state: _CodeReadingState, imported_full_names_by_name: dict[str, tuple[str, ...]]
) -> ParsedCode:
    """Build the reading of the code from the state at its end, turning the places of the opened calls into indexes of `ParsedCode.code_calls`, which leaves out the definitions written like calls."""
    code_call_index_of_opened_call_index: dict[int, int] = {}
    for opened_call_index, code_call in enumerate(state.code_calls):
        if code_call is not None:
            code_call_index_of_opened_call_index[opened_call_index] = len(
                code_call_index_of_opened_call_index
            )
    return ParsedCode(
        code_calls=tuple(
            code_call
            if code_call.first_argument_code_call_index is None
            else replace(
                code_call,
                first_argument_code_call_index=code_call_index_of_opened_call_index.get(
                    code_call.first_argument_code_call_index
                ),
            )
            for code_call in state.code_calls
            if code_call is not None
        ),
        string_assignments=tuple(state.string_assignments),
        call_assignments=tuple(
            CodeCallAssignment(
                call_assignment.name,
                code_call_index_of_opened_call_index[call_assignment.code_call_index],
            )
            for call_assignment in state.call_assignments
        ),
        imported_full_names_by_name=imported_full_names_by_name,
        names_bound_by_assignment_parameter_or_loop=frozenset(
            state.names_bound_by_assignment_parameter_or_loop
        ),
        unreadable_text_start=state.unreadable_text_start,
    )


def _read_token(state: _CodeReadingState, position: int) -> int:
    """Read the whitespace, comment or token that starts at a 0-based position of the code, and give the position after it."""
    code = state.code
    whitespace_match = _WHITESPACE.match(code, position)
    if whitespace_match is not None:
        if "\n" in whitespace_match.group():
            state.is_at_line_start = True
            if not state.open_brackets:
                state.lambda_parameter_bracket_count = None
        return whitespace_match.end()
    comment_end = _comment_end_of(state, position)
    if comment_end is not None:
        state.comment_spans.append((position, comment_end))
        return comment_end
    if state.is_at_line_start:
        state.is_at_line_start = False
        state.line_start_token_position = position
        if _may_assign_here(state):
            _read_assignment(state, position)
    string_literal_end = _read_string_literal(state, position)
    if string_literal_end is not None:
        return string_literal_end
    name_match = state.code_syntax.dotted_name.match(code, position)
    if name_match is not None:
        return _read_name(state, name_match.group(), name_match.end())
    number_match = _NUMBER.match(code, position)
    if number_match is not None:
        _add_argument_token(
            state, _ArgumentToken(_ArgumentTokenKind.OTHER, number_match.group())
        )
        state.previous_token_text = number_match.group()
        return number_match.end()
    _read_punctuation(state, position)
    return position + 1


def _comment_end_of(state: _CodeReadingState, position: int) -> int | None:
    """Find the 0-based position after a comment that starts at a position, None when no comment starts there."""
    code = state.code
    code_syntax = state.code_syntax
    if code.startswith(code_syntax.line_comment_start, position):
        line_end = code.find("\n", position)
        return len(code) if line_end == -1 else line_end
    if code_syntax.has_block_comments and code.startswith("/*", position):
        block_end = code.find("*/", position + 2)
        if block_end == -1:
            state.unreadable_text_start = position
            return len(code)
        return block_end + 2
    return None


def _may_assign_here(state: _CodeReadingState) -> bool:
    """Tell whether a statement can start here, i.e. no bracket is open or the innermost open bracket is a brace, so `url="x"` on its own line right inside the parentheses of a call is no assignment."""
    return not state.open_brackets or state.open_brackets[-1].closer == "}"


def _read_assignment(state: _CodeReadingState, position: int) -> None:
    """Record the assignment of one string to a bare name that starts at a position, e.g. `URL = "https://a.org/x"`, when one starts there.

    When the value starts with a call instead, e.g. `req = Request(u)`, the name is kept for that call, and `_close_call` records the assignment if the call is all of the value.
    """
    code_syntax = state.code_syntax
    assignment_start_match = code_syntax.assignment_start.match(state.code, position)
    if assignment_start_match is None:
        return
    name = assignment_start_match.group(1)
    if name in code_syntax.keywords:
        return
    value_start = assignment_start_match.end()
    # `requests == x` compares and binds nothing.
    if code_syntax.records_bound_names and not state.code.startswith("=", value_start):
        state.names_bound_by_assignment_parameter_or_loop.add(name)
    string_literal = _string_literal_from(state.code, value_start, code_syntax)
    if string_literal is None:
        state.assigned_name_of_call_name_start[value_start] = name
        return
    if string_literal.value is not None and code_syntax.assignment_end.match(
        state.code, string_literal.end
    ):
        state.string_assignments.append(
            CodeStringAssignment(name, string_literal.value)
        )


def _read_string_literal(state: _CodeReadingState, position: int) -> int | None:
    """Read the string that starts at a position into the call that owns it, and give the position after it, None when no string starts there."""
    string_literal = _string_literal_from(state.code, position, state.code_syntax)
    if string_literal is None:
        return None
    value = string_literal.value
    if value is None:
        if string_literal.may_span_lines:
            state.unreadable_text_start = position
        _add_argument_token(state, _ArgumentToken(_ArgumentTokenKind.OTHER, ""))
    else:
        string_owner = _string_owner_of(state)
        if string_owner is not None:
            string_owner.string_literals.append(value)
        _add_argument_token(state, _ArgumentToken(_ArgumentTokenKind.STRING, value))
    state.previous_token_text = ""
    return string_literal.end


def _string_literal_from(
    code: str, position: int, code_syntax: _CodeSyntax
) -> _StringLiteral | None:
    """Find the string that starts at a position, None when no string starts there."""
    quote_position = position
    if code_syntax.string_prefix is not None:
        string_prefix_match = code_syntax.string_prefix.match(code, position)
        if string_prefix_match is not None:
            quote_position = string_prefix_match.end()
    for delimiter in code_syntax.string_delimiters:
        if not code.startswith(delimiter, quote_position):
            continue
        body_start = quote_position + len(delimiter)
        may_span_lines = delimiter in _MULTI_LINE_STRING_BODY_OF_DELIMITER
        if may_span_lines:
            body_match = _MULTI_LINE_STRING_BODY_OF_DELIMITER[delimiter].match(
                code, body_start
            )
        else:
            body_match = _SINGLE_LINE_STRING_BODY_OF_QUOTE[delimiter].match(
                code, body_start
            )
        assert body_match is not None  # Both patterns match an empty body.
        value = body_match.group(1) if body_match.group(2) else None
        return _StringLiteral(value, body_match.end(), may_span_lines)
    return None


@dataclass(frozen=True, slots=True)
class _StringLiteral:
    """String that `_string_literal_from` found, for the reading of a call argument or of an assignment."""

    # The value as written between its quotes, None when the string does not close, e.g. `"abc` before a line break.
    value: str | None
    # The 0-based position after the string.
    end: int
    # Whether the string may span lines, e.g. `"""…"""` or a template literal, so that one that does not close runs to the end of the code.
    may_span_lines: bool


def _string_owner_of(state: _CodeReadingState) -> _OpenCall | None:
    """Find the innermost open call around the current position, which owns a string read there."""
    if not state.open_brackets:
        return None
    return state.open_brackets[-1].string_owner


def _read_name(state: _CodeReadingState, name: str, name_end: int) -> int:
    """Read a bare or dotted name that ends at a position, opening a call when `(` follows it right away, and give the position after what it read."""
    code_syntax = state.code_syntax
    is_call = (
        state.code.startswith("(", name_end)
        and name not in code_syntax.keywords
        and state.previous_token_text not in _DEFINING_WORDS
    )
    if code_syntax.records_bound_names:
        _read_bound_name(state, name, name_end, is_call=is_call)
    state.previous_token_text = name
    if not is_call:
        is_bare_name = "." not in name and name not in code_syntax.keywords
        _add_argument_token(
            state,
            _ArgumentToken(
                _ArgumentTokenKind.NAME if is_bare_name else _ArgumentTokenKind.OTHER,
                name,
            ),
        )
        return name_end
    code_call_index = len(state.code_calls)
    _add_argument_token(
        state, _ArgumentToken(_ArgumentTokenKind.CALL, name, code_call_index)
    )
    open_call = _OpenCall(
        name,
        code_call_index,
        name_end + 1,
        assigned_name=state.assigned_name_of_call_name_start.get(name_end - len(name)),
    )
    state.code_calls.append(None)
    _open_bracket(state, "(", open_call)
    return name_end + 1


def _read_bound_name(
    state: _CodeReadingState, name: str, name_end: int, *, is_call: bool
) -> None:
    """Record a bare name that a parameter of a Python `def` or `lambda` or the variable of a `for` loop that starts a line binds, e.g. `requests` of `def plan(requests, pk):`, `lambda requests: 0` or `for requests in batches:`, and note where such parameters start.

    A parameter is a bare name right after the `(` of a `def`, after a `,` or after `*` in it, or the same after `lambda` up to its `:`, so a default value or a type is not read as one, e.g. `b` of `def f(a=b)`.
    """
    previous_token_text = state.previous_token_text
    if name == "for" and state.line_start_token_position == name_end - len(name):
        state.line_start_for_end = name_end
        return
    if (
        previous_token_text == "def"
        and not is_call
        and state.code.startswith("(", name_end)
    ):
        state.is_next_bracket_parameter_list = True
        return
    if name == "lambda":
        state.lambda_parameter_bracket_count = len(state.open_brackets)
        return
    if "." in name or name in state.code_syntax.keywords or is_call:
        return
    open_brackets = state.open_brackets
    is_def_parameter = (
        bool(open_brackets)
        and open_brackets[-1].is_parameter_list
        and previous_token_text in _TOKENS_BEFORE_A_PARAMETER
    )
    is_lambda_parameter = state.lambda_parameter_bracket_count == len(
        open_brackets
    ) and previous_token_text in (*_TOKENS_BEFORE_A_PARAMETER, "lambda")
    is_loop_variable = (
        previous_token_text == "for"
        and state.line_start_for_end is not None
        and not state.code[state.line_start_for_end : name_end - len(name)].strip()
        and _LOOP_VARIABLE_END.match(state.code, name_end) is not None
    )
    if is_def_parameter or is_lambda_parameter or is_loop_variable:
        state.names_bound_by_assignment_parameter_or_loop.add(name)


def _read_punctuation(state: _CodeReadingState, position: int) -> None:
    """Read one character that is no name, number, string or comment, e.g. a bracket, a comma or `=`."""
    character = state.code[position]
    # A generator is defined by `function*`, so its name still follows `function`, e.g. `function* fetch(u)`.
    if not (character == "*" and state.previous_token_text == "function"):
        state.previous_token_text = character
    if character in _CLOSER_OF_OPENER:
        _add_argument_token(state, _ArgumentToken(_ArgumentTokenKind.OTHER, character))
        _open_bracket(
            state,
            character,
            None,
            is_parameter_list=character == "(" and state.is_next_bracket_parameter_list,
        )
        state.is_next_bracket_parameter_list = False
    elif character in _CLOSERS:
        _close_bracket(state, character, position)
    elif character == "," and (open_call := _innermost_open_call_of(state)) is not None:
        _finish_argument(open_call)
    else:
        if character == ":" and state.lambda_parameter_bracket_count == len(
            state.open_brackets
        ):
            state.lambda_parameter_bracket_count = None
        _add_argument_token(state, _ArgumentToken(_ArgumentTokenKind.OTHER, character))


def _open_bracket(
    state: _CodeReadingState,
    opener: str,
    open_call: _OpenCall | None,
    *,
    is_parameter_list: bool = False,
) -> None:
    """Push a bracket, which a call opens or which follows no name, with the call that owns the strings in it."""
    string_owner = open_call if open_call is not None else _string_owner_of(state)
    closer = _CLOSER_OF_OPENER[opener]
    state.open_brackets.append(
        _OpenBracket(closer, open_call, string_owner, is_parameter_list)
    )
    state.open_closer_counts[closer] += 1


def _close_bracket(state: _CodeReadingState, closer: str, position: int) -> None:
    """Close the innermost open bracket of a closer, and leave the brackets inside it unclosed, e.g. the call `g(` in `[g("a"]`.

    A closer without an open bracket of its kind is passed over, e.g. the last `)` of `f(x))`.
    """
    if state.open_closer_counts[closer] == 0:
        return
    while True:
        open_bracket = state.open_brackets.pop()
        state.open_closer_counts[open_bracket.closer] -= 1
        if open_bracket.closer == closer:
            break
        if open_bracket.open_call is not None:
            _close_call_unreadable(state, open_bracket.open_call)
    if open_bracket.open_call is not None:
        _close_call(state, open_bracket.open_call, position)
    lambda_parameter_bracket_count = state.lambda_parameter_bracket_count
    if (
        lambda_parameter_bracket_count is not None
        and len(state.open_brackets) < lambda_parameter_bracket_count
    ):
        state.lambda_parameter_bracket_count = None


def _close_call(state: _CodeReadingState, open_call: _OpenCall, position: int) -> None:
    """Record a call whose closing parenthesis is at a 0-based position, unless it is a definition written like a call, e.g. `async fetch(url) {` in a JavaScript class body."""
    definition_body_start = state.code_syntax.definition_body_start
    if definition_body_start is not None and definition_body_start.match(
        state.code, position + 1
    ):
        return
    _finish_argument(open_call)
    if open_call.is_first_argument_keyword:
        first_argument_value = open_call.url_argument_value
        first_argument_leading_name = open_call.url_argument_leading_name
    else:
        first_argument_value = open_call.first_positional_value
        first_argument_leading_name = open_call.first_positional_leading_name
    state.code_calls[open_call.code_call_index] = CodeCall(
        name=open_call.name,
        argument_text=state.code[open_call.argument_start : position],
        string_literals=tuple(open_call.string_literals),
        first_argument_string=_token_text_of_kind(
            first_argument_value, _ArgumentTokenKind.STRING
        ),
        first_argument_name=_token_text_of_kind(
            first_argument_value, _ArgumentTokenKind.NAME
        ),
        first_argument_leading_name=first_argument_leading_name,
        first_argument_code_call_index=None
        if first_argument_value is None
        or first_argument_value.argument_token_kind != _ArgumentTokenKind.CALL
        else first_argument_value.code_call_index,
    )
    if open_call.assigned_name is not None and state.code_syntax.assignment_end.match(
        state.code, position + 1
    ):
        state.call_assignments.append(
            CodeCallAssignment(open_call.assigned_name, open_call.code_call_index)
        )


def _close_call_unreadable(state: _CodeReadingState, open_call: _OpenCall) -> None:
    """Record a call whose parentheses do not close, without its strings."""
    state.code_calls[open_call.code_call_index] = CodeCall(
        name=open_call.name,
        argument_text=UnreadableCodeCallArguments(),
        string_literals=(),
        first_argument_string=None,
        first_argument_name=None,
        first_argument_leading_name=None,
        first_argument_code_call_index=None,
    )


def _token_text_of_kind(
    argument_token: _ArgumentToken | None, argument_token_kind: _ArgumentTokenKind
) -> str | None:
    """Find the text of an argument token when it is of a kind, e.g. the string of `"https://a.org/x"`."""
    if (
        argument_token is None
        or argument_token.argument_token_kind != argument_token_kind
    ):
        return None
    return argument_token.text


def _innermost_open_call_of(state: _CodeReadingState) -> _OpenCall | None:
    """Find the call that the innermost open bracket opens, None when that bracket opens no call."""
    if not state.open_brackets:
        return None
    return state.open_brackets[-1].open_call


def _add_argument_token(
    state: _CodeReadingState, argument_token: _ArgumentToken
) -> None:
    """Add a token to the argument being read when the innermost open bracket is a call, keeping only the first four, which tell `url="x"` from one string and `url=BASE + p` from `url=urls[0]`."""
    open_call = _innermost_open_call_of(state)
    if open_call is None:
        return
    if open_call.argument_token_count < 4:
        open_call.argument_tokens.append(argument_token)
    open_call.argument_token_count += 1


def _finish_argument(open_call: _OpenCall) -> None:
    """End the argument being read at a comma or the closing parenthesis, keeping the first argument and the argument named `url` when each is one token, or else the bare name that each starts with."""
    argument_tokens = open_call.argument_tokens
    argument_token_count = open_call.argument_token_count
    open_call.argument_tokens = []
    open_call.argument_token_count = 0
    if argument_token_count == 0:
        return
    is_keyword_argument = (
        argument_token_count >= 2
        and argument_tokens[0].argument_token_kind == _ArgumentTokenKind.NAME
        and argument_tokens[1] == _ArgumentToken(_ArgumentTokenKind.OTHER, "=")
    )
    if open_call.argument_count == 0:
        open_call.is_first_argument_keyword = is_keyword_argument
        if not is_keyword_argument and argument_token_count == 1:
            open_call.first_positional_value = argument_tokens[0]
        if not is_keyword_argument:
            open_call.first_positional_leading_name = _leading_name_of(
                argument_tokens, argument_token_count, value_start=0
            )
    if is_keyword_argument and argument_tokens[0].text == "url":
        if argument_token_count == 3:
            open_call.url_argument_value = argument_tokens[2]
        open_call.url_argument_leading_name = _leading_name_of(
            argument_tokens, argument_token_count, value_start=2
        )
    open_call.argument_count += 1


def _leading_name_of(
    argument_tokens: list[_ArgumentToken],
    argument_token_count: int,
    *,
    value_start: int,
) -> str | None:
    """Find the bare name that the value of an argument starts with when more of the value follows the name, e.g. `BASE` of `BASE + path`, or None, e.g. for `BASE` alone or `urls[0] + path`.

    The value starts at a 0-based index of the tokens of the argument, 0 for a positional argument and 2 after `url=`.
    """
    if argument_token_count < value_start + 2:
        return None
    leading_token, next_token = argument_tokens[value_start : value_start + 2]
    if leading_token.argument_token_kind != _ArgumentTokenKind.NAME or (
        next_token.argument_token_kind == _ArgumentTokenKind.OTHER
        and next_token.text in _PUNCTUATION_THAT_READS_FROM_A_NAME
    ):
        return None
    return leading_token.text
