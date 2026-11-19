"""Tests for parse_codex_exec_script.py, with made-up scripts shaped as in the trajectories."""

import pytest

from tb_internet_use.tool_call.model import (
    OtherAction,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
)
from tb_internet_use.tool_call.parse_codex_exec_script import (
    actions_from_web_run_argument,
    parse_codex_exec_script,
)


@pytest.mark.parametrize(
    ("code", "argument"),
    [
        (
            'tools.x({cmd: "ls", yield_time_ms: 1000})',
            {"cmd": "ls", "yield_time_ms": 1000},
        ),
        ('tools.x({"cmd": "ls"})', {"cmd": "ls"}),
        ('const c = "ls";\ntools.x({cmd: c})', {"cmd": "ls"}),
        # Without a semicolon the name that starts the next statement ends the value.
        ('const c = "ls"\ntools.x({cmd: c})', {"cmd": "ls"}),
        (
            'const cmd = `ls`; tools.x({cmd, workdir: "/w"})',
            {"cmd": "ls", "workdir": "/w"},
        ),
        ('const d = "/a"; tools.x({cmd: `ls ${d}/b`})', {"cmd": "ls /a/b"}),
        ('const d = "/a"; const p = `${d}/b`; tools.x({cmd: p})', {"cmd": "/a/b"}),
        ('const $c = "ls"; tools.x({cmd: $c})', {"cmd": "ls"}),
        ("tools.x({cmd: String.raw`a\\d`})", {"cmd": "a\\d"}),
        (
            "tools.x({session_id: 0x1F, chars: '\\u0003'})",
            {"session_id": 31, "chars": "\x03"},
        ),
        (
            'tools.x({a: 1.5, b: 1e3, c: .5, d: 10n, e: true, f: null, g: ["a", 1]})',
            {
                "a": 1.5,
                "b": 1000.0,
                "c": 0.5,
                "d": 10,
                "e": True,
                "f": None,
                "g": ["a", 1],
            },
        ),
        (
            'tools.x({cmd: "a\\"b\\\\c\\td\\x41\\u{42}\\r\\b\\f\\v\\0\\\nz"})',
            {"cmd": 'a"b\\c\tdAB\r\b\f\v\0z'},
        ),
        ('tools.x({cmd: "\\uD83D\\uDE00"})', {"cmd": "\U0001f600"}),  # a surrogate pair
        ("tools.x({cmd: `a\\`b\\` \\${x} \\n`})", {"cmd": "a`b` ${x} \n"}),
        (
            "const n = 1.0; tools.x({cmd: `${n} ${true} ${null}`})",
            {"cmd": "1 true null"},
        ),
    ],
)
def test_literal_arguments_are_read(code: str, argument: dict[str, object]):
    assert parse_codex_exec_script(code) == [("x", argument)]


@pytest.mark.parametrize(
    "code",
    [
        'tools.x({cmd: "a" + b, workdir: "/w"})',
        'tools.x({cmd: "a" in b, workdir: "/w"})',
        'tools.x({cmd: f({a: 1}), workdir: "/w"})',
        'tools.x({cmd: ["a", c], workdir: "/w"})',
        'const c = "a" + b; tools.x({cmd: c, workdir: "/w"})',
        "const c = String.raw`a``b`; tools.x({cmd: c, workdir: '/w'})",  # a tagged call
        'let c = "ls"; tools.x({cmd: c, workdir: "/w"})',
        'let c = "a"; { const c = "b"; } tools.x({cmd: c, workdir: "/w"})',
        'for (const c of ["a", "b"]) tools.x({cmd: c, workdir: "/w"})',
    ],
)
def test_a_value_that_is_not_a_literal_is_left_out(code: str):
    assert parse_codex_exec_script(code) == [("x", {"workdir": "/w"})]


def test_calls_are_found_in_order_outside_comments_strings_and_regexes():
    code = (
        '// tools.a({cmd: "no"})\n/** tools.b()\n */\n'
        'const re = /tools\\.c\\(/g; const s = "tools.d()"; const f = tools.e;\n'
        'text(`${await tools.x({cmd: "a"})}`); await tools.y({});'
    )
    assert parse_codex_exec_script(code) == [("x", {"cmd": "a"}), ("y", {})]


@pytest.mark.parametrize(
    "code",
    [
        "const h = (a + b) / 2;",  # a slash after a value divides
        "const h = xs[0] / 2;",
        "const h = 10 / 2;",
        "const h = n / 2;",
        'xs.filter(x=>/a"b/.test(x));',  # a slash after an operator starts a regex
        '/"/.test(s);',
        'const r = /a\\/"/;',
        'const r = /[/"]/;',
    ],
)
def test_a_slash_is_a_division_or_a_regex_by_what_comes_before(code: str):
    assert parse_codex_exec_script(code + ' tools.x({cmd: "a/b"})') == [
        ("x", {"cmd": "a/b"})
    ]


# A slash after one of these names starts a regex, e.g. `return /"/.test(s)`, where a division would leave the quote to open a string.
@pytest.mark.parametrize(
    "keyword",
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
    ],
)
def test_a_slash_after_a_keyword_that_comes_before_a_value_starts_a_regex(
    keyword: str,
):
    code = f'const f = (s) => {{ {keyword} /"/.test(s); }}; tools.x({{cmd: "a/b"}})'
    assert parse_codex_exec_script(code) == [("x", {"cmd": "a/b"})]


@pytest.mark.parametrize(
    "code",
    [
        'tools.x({cmd: "unclosed})',
        'tools.x({cmd: "a\nb"})',  # a line break inside a string
        "tools.x(); const s = `x",
        "tools.x(); const s = `${x",
        "tools.x(); const r = /x",
        "tools.x(); const r = /a\n/;",
        'tools.x("\\u{110000}")',
    ],
)
def test_a_script_that_does_not_tokenize_has_no_calls(code: str):
    assert parse_codex_exec_script(code) == []


def test_a_call_whose_argument_does_not_parse_has_none():
    code = 'tools.a({cmd: "ls"); tools.b({a: 1,); tools.c([1'
    assert parse_codex_exec_script(code) == [("a", None), ("b", None), ("c", None)]
    assert parse_codex_exec_script("tools.x([ ) + ])") == [("x", None)]


def test_web_run_gives_one_action_per_kind_of_request_and_keeps_only_urls():
    argument = {
        "search_query": [{"q": "a"}, {"q": "b"}, {"q": "a"}, {"q": ""}, "bare"],
        "image_query": [{"q": "i"}],
        "open": {"ref_id": "HTTPS://a.org"},
        "find": [{"ref_id": "turn0view1"}, {"ref_id": "https://b.org"}],
        "click": [{"ref_id": "turn1view0", "id": 3}],
        "screenshot": [{"ref_id": "turn0view0", "pageno": 1}],
        "response_length": "short",
    }
    assert actions_from_web_run_argument(argument) == [
        WebSearchAction(("a", "b")),
        WebSearchAction(("i",)),
        WebFetchAction(("HTTPS://a.org",)),
        WebFindAction(("https://b.org",)),
        OtherAction(),
        OtherAction(),
    ]
