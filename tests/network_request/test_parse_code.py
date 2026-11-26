"""Tests for network_request/parse_code.py."""

import signal
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType

import pytest

from tb_internet_use.expanded_tool_call.model import CodeLanguage
from tb_internet_use.network_request.model import (
    CodeCall,
    CodeCallAssignment,
    CodeStringAssignment,
    UnreadableCodeCallArguments,
)
from tb_internet_use.network_request.parse_code import parse_code

PYTHON = CodeLanguage.PYTHON
JAVASCRIPT = CodeLanguage.JAVASCRIPT


def _call(
    name: str,
    argument_text: str,
    string_literals: tuple[str, ...] = (),
    *,
    first_argument_string: str | None = None,
    first_argument_name: str | None = None,
    first_argument_leading_name: str | None = None,
    first_argument_code_call_index: int | None = None,
) -> CodeCall:
    return CodeCall(
        name,
        argument_text,
        string_literals,
        first_argument_string,
        first_argument_name,
        first_argument_leading_name,
        first_argument_code_call_index,
    )


def _unreadable_call(name: str) -> CodeCall:
    return CodeCall(name, UnreadableCodeCallArguments(), (), None, None, None, None)


def _names(code: str, code_language: CodeLanguage) -> tuple[str, ...]:
    return tuple(
        code_call.name for code_call in parse_code(code, code_language).code_calls
    )


@contextmanager
def _failing_after(seconds: int) -> Iterator[None]:
    """Raise in the test when the block runs longer than some seconds, so that slow reading fails instead of hanging."""

    def raise_timeout(signal_number: int, frame: FrameType | None) -> None:
        raise TimeoutError(f"took longer than {seconds} seconds")

    previous_handler = signal.signal(signal.SIGALRM, raise_timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


@pytest.mark.parametrize(
    ("code", "code_language", "code_calls"),
    [
        (
            'requests.get("https://a.org/x")',
            PYTHON,
            (
                _call(
                    "requests.get",
                    '"https://a.org/x"',
                    ("https://a.org/x",),
                    first_argument_string="https://a.org/x",
                ),
            ),
        ),
        # The URL belongs to the innermost call, and the outer call comes first.
        (
            'print(requests.get("https://a.org/x").text)',
            PYTHON,
            (
                _call("print", 'requests.get("https://a.org/x").text'),
                _call(
                    "requests.get",
                    '"https://a.org/x"',
                    ("https://a.org/x",),
                    first_argument_string="https://a.org/x",
                ),
            ),
        ),
        # Strings of a keyword argument and a dict are strings of the call too.
        (
            "requests.get('https://a.org/x', headers={'Referer': 'https://b.org'})",
            PYTHON,
            (
                _call(
                    "requests.get",
                    "'https://a.org/x', headers={'Referer': 'https://b.org'}",
                    ("https://a.org/x", "Referer", "https://b.org"),
                    first_argument_string="https://a.org/x",
                ),
            ),
        ),
        # Without a positional argument, the argument named url is the first argument.
        (
            'requests.get(url="https://a.org/x", timeout=5)',
            PYTHON,
            (
                _call(
                    "requests.get",
                    'url="https://a.org/x", timeout=5',
                    ("https://a.org/x",),
                    first_argument_string="https://a.org/x",
                ),
            ),
        ),
        # A positional argument comes before the argument named url.
        (
            'requests.request("GET", url="https://a.org/x")',
            PYTHON,
            (
                _call(
                    "requests.request",
                    '"GET", url="https://a.org/x"',
                    ("GET", "https://a.org/x"),
                    first_argument_string="GET",
                ),
            ),
        ),
        (
            "requests.get(url=URL)",
            PYTHON,
            (_call("requests.get", "url=URL", first_argument_name="URL"),),
        ),
        # A keyword is no bare name.
        ("requests.get(None)", PYTHON, (_call("requests.get", "None"),)),
        # A first argument that is a number or a tuple is no string, even before a string.
        ('f(8000, "x")', PYTHON, (_call("f", '8000, "x"', ("x",)),)),
        ('f((1, 2), "x")', PYTHON, (_call("f", '(1, 2), "x"', ("x",)),)),
        (
            'requests.get(url="https://a.org/" + path)',
            PYTHON,
            (
                _call(
                    "requests.get", 'url="https://a.org/" + path', ("https://a.org/",)
                ),
            ),
        ),
        # A dotted name is no bare name.
        ("requests.get(self.url)", PYTHON, (_call("requests.get", "self.url"),)),
        # A built URL is neither one string nor one name, but may start with a bare name.
        (
            "requests.get(base + path)",
            PYTHON,
            (_call("requests.get", "base + path", first_argument_leading_name="base"),),
        ),
        (
            "requests.get(url=BASE + path, timeout=3)",
            PYTHON,
            (
                _call(
                    "requests.get",
                    "url=BASE + path, timeout=3",
                    first_argument_leading_name="BASE",
                ),
            ),
        ),
        (
            'fetch(BASE + "/x")',
            JAVASCRIPT,
            (
                _call(
                    "fetch", 'BASE + "/x"', ("/x",), first_argument_leading_name="BASE"
                ),
            ),
        ),
        # A name that `(`, `.` or `[` reads from, a dotted name, a call or a later argument starts no first argument.
        ("requests.get(base (p))", PYTHON, (_call("requests.get", "base (p)"),)),
        (
            "requests.get(cfg .base + p)",
            PYTHON,
            (_call("requests.get", "cfg .base + p"),),
        ),
        ("requests.get(urls[0] + p)", PYTHON, (_call("requests.get", "urls[0] + p"),)),
        (
            "requests.get(cfg.base + p)",
            PYTHON,
            (_call("requests.get", "cfg.base + p"),),
        ),
        (
            "requests.get(base() + p)",
            PYTHON,
            (_call("requests.get", "base() + p"), _call("base", "")),
        ),
        (
            'f("x", base + p)',
            PYTHON,
            (_call("f", '"x", base + p', ("x",), first_argument_string="x"),),
        ),
        (
            'requests.get("https://a.org/" + path)',
            PYTHON,
            (_call("requests.get", '"https://a.org/" + path', ("https://a.org/",)),),
        ),
        (
            'requests.get("https://a.org" "/x")',
            PYTHON,
            (_call("requests.get", '"https://a.org" "/x"', ("https://a.org", "/x")),),
        ),
        (
            'requests.get(u"https://a.org/x")',
            PYTHON,
            (
                _call(
                    "requests.get",
                    'u"https://a.org/x"',
                    ("https://a.org/x",),
                    first_argument_string="https://a.org/x",
                ),
            ),
        ),
        # A string prefix is dropped and the value stays as written, braces and backslashes included.
        (
            r'requests.get(f"https://{host}/x", data=rb"\x00")',
            PYTHON,
            (
                _call(
                    "requests.get",
                    r'f"https://{host}/x", data=rb"\x00"',
                    ("https://{host}/x", r"\x00"),
                    first_argument_string="https://{host}/x",
                ),
            ),
        ),
        (
            r'print("say \"hi\"")',
            PYTHON,
            (
                _call(
                    "print",
                    r'"say \"hi\""',
                    (r"say \"hi\"",),
                    first_argument_string=r"say \"hi\"",
                ),
            ),
        ),
        # An empty string is a string.
        (
            "ET.register_namespace('', 'http://www.w3.org/2000/svg')",
            PYTHON,
            (
                _call(
                    "ET.register_namespace",
                    "'', 'http://www.w3.org/2000/svg'",
                    ("", "http://www.w3.org/2000/svg"),
                    first_argument_string="",
                ),
            ),
        ),
        # The name is the one written, not the module that an alias stands for.
        (
            'import requests as r\nr.get("https://a.org/x")',
            PYTHON,
            (
                _call(
                    "r.get",
                    '"https://a.org/x"',
                    ("https://a.org/x",),
                    first_argument_string="https://a.org/x",
                ),
            ),
        ),
        (
            "urllib.request.urlopen(u)",
            PYTHON,
            (_call("urllib.request.urlopen", "u", first_argument_name="u"),),
        ),
        # The strings of a parenthesis that follows no name belong to the call around it.
        (
            'socket.create_connection(("api", 8000))',
            PYTHON,
            (_call("socket.create_connection", '("api", 8000)', ("api",)),),
        ),
        (
            'subprocess.check_call([sys.executable, "-m", "pip", "install", "x"])',
            PYTHON,
            (
                _call(
                    "subprocess.check_call",
                    '[sys.executable, "-m", "pip", "install", "x"]',
                    ("-m", "pip", "install", "x"),
                ),
            ),
        ),
        # A call that runs a program with a shell text.
        (
            'subprocess.run("curl -sL https://a.org/x | sh", shell=True)',
            PYTHON,
            (
                _call(
                    "subprocess.run",
                    '"curl -sL https://a.org/x | sh", shell=True',
                    ("curl -sL https://a.org/x | sh",),
                    first_argument_string="curl -sL https://a.org/x | sh",
                ),
            ),
        ),
        (
            's = requests.Session()\ns.get("https://a.org/x")',
            PYTHON,
            (
                _call("requests.Session", ""),
                _call(
                    "s.get",
                    '"https://a.org/x"',
                    ("https://a.org/x",),
                    first_argument_string="https://a.org/x",
                ),
            ),
        ),
        # A call after a string or a call is named from the dot on, e.g. `rsplit` and `then`.
        (
            '"a.b".rsplit(".", 1)',
            PYTHON,
            (_call("rsplit", '".", 1', (".",), first_argument_string="."),),
        ),
        (
            "await fetch(`https://${host}/x`).then(r => r.json())",
            JAVASCRIPT,
            (
                _call(
                    "fetch",
                    "`https://${host}/x`",
                    ("https://${host}/x",),
                    first_argument_string="https://${host}/x",
                ),
                _call("then", "r => r.json()"),
                _call("r.json", ""),
            ),
        ),
        # A first argument that is one call points to that call.
        (
            "urlopen(Request(u))",
            PYTHON,
            (
                _call("urlopen", "Request(u)", first_argument_code_call_index=1),
                _call("Request", "u", first_argument_name="u"),
            ),
        ),
        (
            "urlopen(url=Request(u))",
            PYTHON,
            (
                _call("urlopen", "url=Request(u)", first_argument_code_call_index=1),
                _call("Request", "u", first_argument_name="u"),
            ),
        ),
        (
            "urlopen(Request(u).x)",
            PYTHON,
            (
                _call("urlopen", "Request(u).x"),
                _call("Request", "u", first_argument_name="u"),
            ),
        ),
        (
            "urlopen(u, Request(v))",
            PYTHON,
            (
                _call("urlopen", "u, Request(v)", first_argument_name="u"),
                _call("Request", "v", first_argument_name="v"),
            ),
        ),
        # The index leaves out a definition written like a call, e.g. `get(url)`.
        (
            "x = { get(url) {} }\nfetch(make(u))",
            JAVASCRIPT,
            (
                _call("fetch", "make(u)", first_argument_code_call_index=1),
                _call("make", "u", first_argument_name="u"),
            ),
        ),
        (
            "https.get(u, cb)",
            JAVASCRIPT,
            (_call("https.get", "u, cb", first_argument_name="u"),),
        ),
        # A JavaScript name may hold `$`.
        (
            "$http.get($url)",
            JAVASCRIPT,
            (_call("$http.get", "$url", first_argument_name="$url"),),
        ),
    ],
)
def test_calls_are_read_with_their_strings_and_first_argument(
    code: str, code_language: CodeLanguage, code_calls: tuple[CodeCall, ...]
):
    assert parse_code(code, code_language).code_calls == code_calls


@pytest.mark.parametrize(
    ("code", "code_language", "names"),
    [
        ('# see fetch("https://a.org/doc")', PYTHON, ()),
        ('"""Call urlopen("https://a.org") here."""', PYTHON, ()),
        ("'''Call urlopen(u)\nhere.'''", PYTHON, ()),
        ('print("call fetch(x) later")', PYTHON, ("print",)),
        (r'print("a \" fetch(x)")', PYTHON, ("print",)),
        ("log(`fetch(${u})`)", JAVASCRIPT, ("log",)),
        # An escaped delimiter does not close a multi-line string.
        (r"log(`a \` fetch(u)`)", JAVASCRIPT, ("log",)),
        (r"'''a \''' fetch(u)'''", PYTHON, ()),
        (
            '// fetch("https://a.org")\n/* fetch(\n"https://b.org") */\nfetch(u)',
            JAVASCRIPT,
            ("fetch",),
        ),
        # `//` is division in Python and `#` starts no comment in JavaScript.
        ("n = a // 2; fetch(u)", PYTHON, ("fetch",)),
        ("x.#p; fetch(u)", JAVASCRIPT, ("fetch",)),
        # A backtick starts no string in Python.
        ("x = `a\nfetch(u)", PYTHON, ("fetch",)),
        # A definition opens no call, and nor does a keyword.
        ('def fetch(url="https://a.org"):\n    pass', PYTHON, ()),
        ("class Client(Base):\n    pass", PYTHON, ()),
        ("async function fetch(u) { return u }", JAVASCRIPT, ()),
        ("if (ok) { fetch(u) }", JAVASCRIPT, ("fetch",)),
        # A JavaScript method or generator is defined without `function`, or with `*` after it.
        ("class A { async fetch(url) {} }", JAVASCRIPT, ()),
        ("x = { get(url) {} }", JAVASCRIPT, ()),
        ("function* fetch(u) // gen\n{}", JAVASCRIPT, ()),
        ("fetch(u).then(r => { log(r) })", JAVASCRIPT, ("fetch", "then", "log")),
        ("foo(function () { fetch(u) })", JAVASCRIPT, ("foo", "fetch")),
        # A name before a space and `(` is no call.
        ("print (x)", PYTHON, ()),
        ("while(x):\n    return(urlopen(u))", PYTHON, ("urlopen",)),
        # Calls come in the order of their names in the text.
        ("a(b(c()), d())", PYTHON, ("a", "b", "c", "d")),
    ],
)
def test_calls_are_found_outside_strings_comments_definitions_and_keywords(
    code: str, code_language: CodeLanguage, names: tuple[str, ...]
):
    assert _names(code, code_language) == names


@pytest.mark.parametrize(
    ("code", "code_language", "string_assignments"),
    [
        (
            'URL = "https://a.org/x"\nrequests.get(URL)',
            PYTHON,
            (CodeStringAssignment("URL", "https://a.org/x"),),
        ),
        # Each assignment is kept, so a later reader can tell a name given two strings.
        (
            'URL = "https://a.org/x"\nURL = "https://b.org/y"',
            PYTHON,
            (
                CodeStringAssignment("URL", "https://a.org/x"),
                CodeStringAssignment("URL", "https://b.org/y"),
            ),
        ),
        (
            'URL = f"https://{h}/x"  # docs',
            PYTHON,
            (CodeStringAssignment("URL", "https://{h}/x"),),
        ),
        (
            'def f():\n    URL = "https://a.org/x"',
            PYTHON,
            (CodeStringAssignment("URL", "https://a.org/x"),),
        ),
        (
            "const URL = 'https://a.org/x';\nlet b = `https://b.org`\nvar c = \"c\"",
            JAVASCRIPT,
            (
                CodeStringAssignment("URL", "https://a.org/x"),
                CodeStringAssignment("b", "https://b.org"),
                CodeStringAssignment("c", "c"),
            ),
        ),
        # A function body in braces inside a call holds statements.
        (
            'app.get("/", () => {\n  const U = "https://a.org/x";\n})',
            JAVASCRIPT,
            (CodeStringAssignment("U", "https://a.org/x"),),
        ),
        (
            'URL: str = "https://a.org/x"',
            PYTHON,
            (CodeStringAssignment("URL", "https://a.org/x"),),
        ),
        ('export const U = "x"', JAVASCRIPT, (CodeStringAssignment("U", "x"),)),
        ('x: int  # = "s"', PYTHON, ()),
        ('const U = "x"', PYTHON, ()),
        ('URL == "x"', PYTHON, ()),
        ('URL = "https://a.org/" + path', PYTHON, ()),
        ('if URL == "https://a.org/x":\n    pass', PYTHON, ()),
        ('import requests; URL = "https://a.org/x"', PYTHON, ()),
        # An argument named url on its own line is no assignment.
        ('requests.get(\n    url="https://a.org/x"\n)', PYTHON, ()),
        ('"""\nURL = "https://a.org/x"\n"""', PYTHON, ()),
        ('URL = "https://a.org/x', PYTHON, ()),
    ],
)
def test_string_assignments_are_one_string_given_to_a_bare_name_at_the_start_of_a_line(
    code: str,
    code_language: CodeLanguage,
    string_assignments: tuple[CodeStringAssignment, ...],
):
    assert parse_code(code, code_language).string_assignments == string_assignments


@pytest.mark.parametrize(
    ("code", "code_language", "call_assignments"),
    [
        (
            "req = urllib.request.Request(u)\nurlopen(req)",
            PYTHON,
            (CodeCallAssignment("req", 0),),
        ),
        ("x = 1\nreq = Request(u)  # r", PYTHON, (CodeCallAssignment("req", 0),)),
        ("req = Request(u); urlopen(req)", PYTHON, (CodeCallAssignment("req", 0),)),
        ("const req = make(u);", JAVASCRIPT, (CodeCallAssignment("req", 0),)),
        # The index leaves out a definition written like a call, e.g. `get(url)`.
        (
            "x = { get(url) {} }\nconst r = make(u)",
            JAVASCRIPT,
            (CodeCallAssignment("r", 0),),
        ),
        # Each assignment is kept, so a later reader can tell a name given two calls.
        (
            "r = f(u)\nr = g(v)",
            PYTHON,
            (CodeCallAssignment("r", 0), CodeCallAssignment("r", 1)),
        ),
        # The call must be all of the value.
        ("req = Request(u).read()", PYTHON, ()),
        ("req = Request(u) + x", PYTHON, ()),
        ("req = (Request(u))", PYTHON, ()),
        ("req = x or Request(u)", PYTHON, ()),
        ("req == Request(u)", PYTHON, ()),
        ("req = Request(u", PYTHON, ()),
        ("f(\n    req=Request(u)\n)", PYTHON, ()),
        ("import x; req = Request(u)", PYTHON, ()),
    ],
)
def test_call_assignments_are_one_call_given_to_a_bare_name_at_the_start_of_a_line(
    code: str,
    code_language: CodeLanguage,
    call_assignments: tuple[CodeCallAssignment, ...],
):
    assert parse_code(code, code_language).call_assignments == call_assignments


@pytest.mark.parametrize(
    ("code", "code_language", "code_calls"),
    [
        # Code cut short after the URL or inside it.
        (
            'requests.get("https://a.org/x"',
            PYTHON,
            (_unreadable_call("requests.get"),),
        ),
        ('requests.get("https://a.or', PYTHON, (_unreadable_call("requests.get"),)),
        ('"""doc\nrequests.get("https://a.org")', PYTHON, ()),
        ("/* fetch(u)", JAVASCRIPT, ()),
        # A quote that does not close ends at the line break, so the next line is read.
        (
            'print("abc)\nrequests.get("https://a.org/x")',
            PYTHON,
            (
                _unreadable_call("print"),
                _call(
                    "requests.get",
                    '"https://a.org/x"',
                    ("https://a.org/x",),
                    first_argument_string="https://a.org/x",
                ),
            ),
        ),
        # A closer leaves the brackets inside its opener unclosed.
        ('x = [g("a"]', PYTHON, (_unreadable_call("g"),)),
        (
            'print([requests.get("https://a.org"))',
            PYTHON,
            (
                _call("print", '[requests.get("https://a.org")'),
                _call(
                    "requests.get",
                    '"https://a.org"',
                    ("https://a.org",),
                    first_argument_string="https://a.org",
                ),
            ),
        ),
        # A closer without an opener is passed over.
        (
            "f(g(1)))",
            PYTHON,
            (_call("f", "g(1)", first_argument_code_call_index=1), _call("g", "1")),
        ),
        ("x = [f(1))]", PYTHON, (_call("f", "1"),)),
    ],
)
def test_calls_whose_parentheses_do_not_close_are_unreadable(
    code: str, code_language: CodeLanguage, code_calls: tuple[CodeCall, ...]
):
    assert parse_code(code, code_language).code_calls == code_calls


@pytest.mark.parametrize(
    ("code", "code_language", "unreadable_text_start"),
    [
        ('x = 1\n"""doc\nfetch(u)', PYTHON, 6),
        ("x = 1\nu'''doc", PYTHON, 6),
        ("x = 1\n/* fetch(u)", JAVASCRIPT, 6),
        # A regular expression literal that holds a backtick starts a template literal that never closes.
        ("const re = /`/; fetch(u); axios.get(v)", JAVASCRIPT, 12),
        # A quote that does not close ends at the line break, so the next line is read.
        ('print("abc\nfetch(u)', PYTHON, None),
        ('"""a"""\nfetch(u)', PYTHON, None),
        ("/* a */ fetch(`u`)", JAVASCRIPT, None),
    ],
)
def test_text_after_a_multi_line_string_or_block_comment_that_never_closes_is_unreadable(
    code: str, code_language: CodeLanguage, unreadable_text_start: int | None
):
    assert (
        parse_code(code, code_language).unreadable_text_start == unreadable_text_start
    )


@pytest.mark.parametrize(
    ("code", "code_language", "imported_full_names_by_name"),
    [
        # Python `import` statements bind the first dotted part of a module, or its `as` name to the whole module.
        ("import requests\nrequests.get(u)", PYTHON, {"requests": ("requests",)}),
        ("import os, sys", PYTHON, {"os": ("os",), "sys": ("sys",)}),
        ("import urllib.request", PYTHON, {"urllib": ("urllib",)}),
        ("import requests as rq", PYTHON, {"rq": ("requests",)}),
        ("import urllib.request as u", PYTHON, {"u": ("urllib.request",)}),
        ("import os, requests as rq", PYTHON, {"os": ("os",), "rq": ("requests",)}),
        # Python `from` statements bind a member of a module, also a class.
        (
            "from urllib.request import urlopen",
            PYTHON,
            {"urlopen": ("urllib.request.urlopen",)},
        ),
        (
            "from urllib.request import urlopen as fetch_url",
            PYTHON,
            {"fetch_url": ("urllib.request.urlopen",)},
        ),
        (
            "from urllib.request import urlopen, Request",
            PYTHON,
            {
                "urlopen": ("urllib.request.urlopen",),
                "Request": ("urllib.request.Request",),
            },
        ),
        (
            "from transformers import AutoTokenizer",
            PYTHON,
            {"AutoTokenizer": ("transformers.AutoTokenizer",)},
        ),
        (
            "from urllib.request import (\n    urlopen,  # opens\n    Request as R,\n)",
            PYTHON,
            {"urlopen": ("urllib.request.urlopen",), "R": ("urllib.request.Request",)},
        ),
        ("from .net import urlopen", PYTHON, {"urlopen": (".net.urlopen",)}),
        ("from . import net", PYTHON, {"net": (".net",)}),
        ("from helpers import *", PYTHON, {}),
        # A statement counts after indentation and after `;`, but not inside other text.
        (
            "def f():\n    import requests\n    return requests.get(u)",
            PYTHON,
            {"requests": ("requests",)},
        ),
        (
            "try:\n\timport httpx\nexcept ImportError:\n    pass",
            PYTHON,
            {"httpx": ("httpx",)},
        ),
        ("import socket  # for the port check", PYTHON, {"socket": ("socket",)}),
        (
            "import os; import urllib.request as u",
            PYTHON,
            {"os": ("os",), "u": ("urllib.request",)},
        ),
        ("x = 1; from requests import get", PYTHON, {"get": ("requests.get",)}),
        ("importlib.import_module('requests')", PYTHON, {}),
        ("x = 1  # import requests", PYTHON, {}),
        # A comment holds no import, also after `;` in it.
        ("x = 1  # see a; import requests as rq", PYTHON, {}),
        ("// const fetch = require('node-fetch')\nfetch(u)", JAVASCRIPT, {}),
        ("x = 1 // see a; import fetch from 'node-fetch'", JAVASCRIPT, {}),
        (
            (
                "/* import fetch from 'node-fetch'\nimport ws from 'ws' */\n"
                "const cp = require('child_process')"
            ),
            JAVASCRIPT,
            {"cp": ("child_process",)},
        ),
        # Known limit. A statement that a backslash continues is read up to the backslash.
        ("import os, \\\n    sys", PYTHON, {"os": ("os",)}),
        # A call that imports binds the name it is assigned to.
        (
            'subprocess = __import__("subprocess")',
            PYTHON,
            {"subprocess": ("subprocess",)},
        ),
        ('sp = __import__("subprocess")', PYTHON, {"sp": ("subprocess",)}),
        ('requests = __import__("httpx")', PYTHON, {"requests": ("httpx",)}),
        ('p = __import__("os.path")', PYTHON, {"p": ("os",)}),
        ('p = importlib.import_module("os.path")', PYTHON, {"p": ("os.path",)}),
        # Imports that bind one name to several full names keep each, in the order of the text.
        (
            (
                "try:\n    from urllib.request import urlopen\n"
                "except ImportError:\n    from urllib2 import urlopen"
            ),
            PYTHON,
            {"urlopen": ("urllib.request.urlopen", "urllib2.urlopen")},
        ),
        (
            "x = __import__('httpx')\nimport requests as x",
            PYTHON,
            {"x": ("httpx", "requests")},
        ),
        (
            "import requests\nimport requests",
            PYTHON,
            {"requests": ("requests",)},
        ),
        # JavaScript `require` bindings, also after another declaration.
        (
            'const cp = require("child_process")',
            JAVASCRIPT,
            {"cp": ("child_process",)},
        ),
        (
            'const { execSync, spawn: run } = require("child_process");',
            JAVASCRIPT,
            {"execSync": ("child_process.execSync",), "run": ("child_process.spawn",)},
        ),
        (
            'const run = require("child_process").execSync',
            JAVASCRIPT,
            {"run": ("child_process.execSync",)},
        ),
        (
            "const fs=require('fs'),{execSync}=require('child_process');",
            JAVASCRIPT,
            {"fs": ("fs",), "execSync": ("child_process.execSync",)},
        ),
        ('this.cp = require("child_process")', JAVASCRIPT, {}),
        # JavaScript `import` statements, without the prefix `node:`.
        ("import http from 'node:http'", JAVASCRIPT, {"http": ("http",)}),
        (
            'import { execSync } from "node:child_process"',
            JAVASCRIPT,
            {"execSync": ("child_process.execSync",)},
        ),
        (
            'import { execSync as run } from "child_process"',
            JAVASCRIPT,
            {"run": ("child_process.execSync",)},
        ),
        (
            'import * as cp from "node:child_process"',
            JAVASCRIPT,
            {"cp": ("child_process",)},
        ),
        (
            "import fs from 'fs'; import { execSync } from 'child_process';",
            JAVASCRIPT,
            {"fs": ("fs",), "execSync": ("child_process.execSync",)},
        ),
        # Known limit. A dynamic import binds no name.
        ('const cp = await import("child_process")', JAVASCRIPT, {}),
        # Each language reads only its own statements.
        ("import requests", JAVASCRIPT, {}),
        ("const cp = require('child_process')", PYTHON, {}),
    ],
)
def test_imported_full_names_by_name_give_the_full_names_that_imports_bind_to_a_name(
    code: str,
    code_language: CodeLanguage,
    imported_full_names_by_name: dict[str, tuple[str, ...]],
):
    assert (
        parse_code(code, code_language).imported_full_names_by_name
        == imported_full_names_by_name
    )


@pytest.mark.parametrize(
    ("code", "code_language", "bound_names"),
    [
        ("requests = {}", PYTHON, {"requests"}),
        ("requests: Dict[str, int] = {}", PYTHON, {"requests"}),
        ("    requests = load()", PYTHON, {"requests"}),
        ("requests == x", PYTHON, set()),
        ("requests += 1", PYTHON, set()),
        ("def plan(requests, pk):\n    pass", PYTHON, {"requests", "pk"}),
        ("async def plan(*args, **requests):\n    pass", PYTHON, {"args", "requests"}),
        (
            "def plan(\n    requests: dict,\n    pk=d.get(a, b),\n):\n    pass",
            PYTHON,
            {"requests", "pk"},
        ),
        ("def f(a=requests):\n    pass", PYTHON, {"a"}),
        ("class C(requests):\n    pass", PYTHON, set()),
        ("plan(requests, pk)", PYTHON, set()),
        ("f = lambda requests, pk: requests.get(pk)", PYTHON, {"f", "requests", "pk"}),
        ("sorted(xs, key=lambda requests: 0)", PYTHON, {"requests"}),
        ("for requests in batches:\n    pass", PYTHON, {"requests"}),
        ("x = 1\nimport requests", PYTHON, {"x"}),
        ('subprocess = __import__("subprocess")', PYTHON, {"subprocess"}),
        # Tuple targets, `with … as`, `except … as`, comprehension variables and attributes are not read.
        ("requests, n = load()", PYTHON, set()),
        ("with open(p) as requests:\n    pass", PYTHON, set()),
        ("try:\n    pass\nexcept E as requests:\n    pass", PYTHON, set()),
        ("xs = [r for requests in batches]", PYTHON, {"xs"}),
        ("self.requests = {}", PYTHON, set()),
        ("const requests = {}", JAVASCRIPT, set()),
        ("function plan(requests) {}", JAVASCRIPT, set()),
    ],
)
def test_bound_names_are_the_bare_names_of_python_assignments_parameters_and_loops(
    code: str, code_language: CodeLanguage, bound_names: set[str]
):
    assert parse_code(
        code, code_language
    ).names_bound_by_assignment_parameter_or_loop == frozenset(bound_names)


@pytest.mark.parametrize(
    ("code", "code_language", "code_call_count"),
    [
        (
            '"""doc\nurlopen("x")"""\nURL = "https://a.org/x"  # fetch("u")\n'
            'print(requests.get(URL, headers={"k": f"v{x}"}), [1, 2])\n' * 20_000,
            PYTHON,
            40_000,
        ),
        ("f(" * 100_000, PYTHON, 100_000),
        ('"' + 'a\\"' * 300_000, PYTHON, 0),
        ("/*" + "x" * 1_000_000, JAVASCRIPT, 0),
        ("import " + "a" * 1_000_000 + " !", PYTHON, 0),
        ("import " + "a." * 300_000 + " !", PYTHON, 0),
        ("from " + "a." * 300_000 + " import b", PYTHON, 0),
        ("from a import (\n" * 200_000, PYTHON, 0),
        ("import { a;" * 200_000, JAVASCRIPT, 0),
        ("{ a" * 300_000 + "} = require('x')", JAVASCRIPT, 1),
        ("a" * 1_000_000 + " = require('x')", JAVASCRIPT, 1),
        ("`" + "${a}" * 300_000, JAVASCRIPT, 0),
    ],
)
def test_long_code_is_read_in_time_that_grows_with_its_length(
    code: str, code_language: CodeLanguage, code_call_count: int
):
    with _failing_after(5):
        assert len(parse_code(code, code_language).code_calls) == code_call_count


def test_nested_calls_each_hold_the_text_between_their_parentheses():
    nesting_depth = 2_000
    with _failing_after(5):
        code_calls = parse_code(
            "f(" * nesting_depth + ")" * nesting_depth, PYTHON
        ).code_calls
    assert len(code_calls) == nesting_depth
    assert code_calls[0].argument_text == "f(" * 1_999 + ")" * 1_999
    assert code_calls[-1].argument_text == ""
