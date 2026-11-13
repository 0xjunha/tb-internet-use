"""Tests for parse/shell/_parse_shell.py."""

import pytest

from tb_internet_use.parse.shell import parse_shell
from tb_internet_use.parse.shell.model import (
    CaptureDestination,
    DiscardDestination,
    ExitOutcome,
    FileDestination,
    OutputDestination,
    ParsedShellText,
    PipeDestination,
    ResultDestination,
    RunCondition,
    ShellCommand,
    VariableAssignment,
)

S = ExitOutcome.SUCCESS
F = ExitOutcome.FAILURE

# (text, the command by its first word, stdout, stderr,
#  run conditions as (first words of the deciding commands, outcome), succeeded_if_text_exits_zero)
STRUCTURE_CASES = [
    # Sequences and lists
    ("a; b", "a", "result", "result", [], False),
    ("a; b", "b", "result", "result", [], True),
    ("a && b && c", "c", "result", "result", [(["a", "b"], S)], True),
    ("a && b || c", "b", "result", "result", [(["a"], S)], False),
    ("a && b || c", "c", "result", "result", [(["a", "b"], F)], False),
    ("a || b && c", "b", "result", "result", [(["a"], F)], False),
    ("a || b && c", "c", "result", "result", [(["a", "b"], S)], True),
    (
        "(cd d && make) || curl u",
        "curl",
        "result",
        "result",
        [(["cd", "make"], F)],
        False,
    ),
    ("curl -s u & b", "curl", "result", "result", [], False),
    # A side whose deciding commands are unknown makes the whole list's unknown.
    ("! curl -f u", "curl", "result", "result", [], False),
    ("! a && curl u", "curl", "result", "result", [([], S)], True),
    # tree-sitter reads `! a | b` as `(! a) | b`. Bash runs `! (a | b)`.
    ("! a | b", "b", "result", "result", [], False),
    (
        "if ! a | grep -q x; then c; else d; fi",
        "c",
        "result",
        "result",
        [([], S)],
        False,
    ),
    ("[ -f x ] && echo yes || curl u", "curl", "result", "result", [([], F)], False),
    ("a && ! b || curl u", "curl", "result", "result", [([], F)], False),
    ("(a &) && curl u", "curl", "result", "result", [([], S)], True),
    ("f() { a; } && b", "b", "result", "result", [([], S)], True),
    # if, while, until, for, case and function bodies
    (
        "if curl -f u; then echo ok; fi",
        "echo",
        "result",
        "result",
        [(["curl"], S)],
        False,
    ),
    ("if a; then b; else curl u; fi", "curl", "result", "result", [(["a"], F)], False),
    (
        "if a; then b; elif c; then d; fi",
        "d",
        "result",
        "result",
        [(["a"], F), (["c"], S)],
        False,
    ),
    (
        "if a; then b; elif c; then d; else e; fi",
        "e",
        "result",
        "result",
        [(["a"], F), (["c"], F)],
        False,
    ),
    (
        "while curl -s u; do sleep 1; done",
        "sleep",
        "result",
        "result",
        [(["curl"], S)],
        False,
    ),
    (
        "until curl -s u; do sleep 1; done",
        "sleep",
        "result",
        "result",
        [(["curl"], F)],
        False,
    ),
    ("while a # c\ndo b; done; d", "b", "result", "result", [(["a"], S)], False),
    ("for p in a b; do pip install $p; done", "pip", "result", "result", [], False),
    ("case x in x) a ;; esac", "a", "result", "result", [], False),
    ("f() { a; }", "a", "result", "result", [], False),
    # set -e and pipefail
    ("set -e; a; b", "a", "result", "result", [(["set"], S)], True),
    ("set -e; a; b", "b", "result", "result", [(["a"], S)], True),
    ("a; set -e; b", "a", "result", "result", [], False),
    ("set -o errexit; a; b", "a", "result", "result", [(["set"], S)], True),
    ("set -eu; a; b", "a", "result", "result", [(["set"], S)], True),
    ("set -euo pipefail; a | b; c", "a", "pipe to b", "result", [(["set"], S)], True),
    ("set -e; set +e; a; b", "a", "result", "result", [(["set"], S)], False),
    ("set -- -e x; a; b", "a", "result", "result", [], False),
    ("grep -e x f; a; b", "a", "result", "result", [], False),
    # set -e does not end the text when the left side of && fails.
    ("set -e; a && b; c", "a", "result", "result", [(["set"], S)], False),
    ("set -e; a && b; c", "c", "result", "result", [(["set"], S)], True),
    ("set -e; { a; b; } && c", "a", "result", "result", [(["set"], S)], False),
    (
        "set -e; false && echo x > f; true",
        "true",
        "result",
        "result",
        [(["set"], S)],
        True,
    ),
    (
        "set -e; a; b | while read x; do :; done; c",
        "c",
        "result",
        "result",
        [(["a"], S), ([], S)],
        True,
    ),
    ("set -e; if a; then b; fi; c", "a", "result", "result", [(["set"], S)], False),
    ("set -e; while a; do b; done; c", "c", "result", "result", [(["set"], S)], True),
    ("set -e; ! a; b", "b", "result", "result", [(["set"], S)], True),
    # Statements other than commands that end the text on failure
    ("set -e; V=$(curl u); b", "b", "result", "result", [(["curl"], S)], True),
    ("set -e; A=1 B=$(b); c", "c", "result", "result", [(["b"], S)], True),
    ("set -e; ! a | b; c", "c", "result", "result", [(["set"], S)], True),
    ('set -e; eval "set +e"; a; b', "b", "result", "result", [(["set"], S)], True),
    # The $(...) whose exit code an assignment takes decides the text's exit code.
    ("x=$(curl u)", "curl", "capture", "result", [], True),
    ("set -e; X=1; b", "b", "result", "result", [(["set"], S)], True),
    ("set -e; (cd x && make); b", "b", "result", "result", [(["cd", "make"], S)], True),
    ("set -e; [ -f x ]; b", "b", "result", "result", [(["set"], S), ([], S)], True),
    # Inside a non-last pipeline stage set -e still holds.
    (
        "set -e; { a; b; } | c",
        "b",
        "pipe to c",
        "result",
        [(["set"], S), (["a"], S)],
        False,
    ),
    # Bash turns set -e off inside $(...).
    ("set -e; x=$(a; b); c", "b", "capture", "result", [(["set"], S)], True),
    # eval runs in this shell, so the left side of || stays free of set -e.
    ('set -e; eval "a; b" || c', "b", "result", "result", [(["set"], S)], False),
    # set inside a subshell, a function or bash -c ends with it.
    ("(set -e; a); b; c", "b", "result", "result", [], False),
    ("f() { set -e; }; a; b", "a", "result", "result", [], False),
    ("set -e; bash -c 'a; b'", "a", "result", "result", [(["set"], S)], False),
    ("bash -euo pipefail -c 'a | b; c'", "a", "pipe to b", "result", [], True),
    ("set -o pipefail; curl u | tail -1", "curl", "pipe to tail", "result", [], True),
    ("set -o pipefail; a | b && c", "c", "result", "result", [(["a", "b"], S)], True),
    ("a | b && c", "c", "result", "result", [(["b"], S)], True),
    # exit
    ("a || exit 1; curl u", "curl", "result", "result", [(["a"], S)], True),
    (
        "a || { echo failed; exit 1; }; curl u",
        "curl",
        "result",
        "result",
        [(["a"], S)],
        True,
    ),
    ("a || { exit 1; echo x; }; b", "b", "result", "result", [], True),
    ("a || (exit 1); b", "b", "result", "result", [], True),
    ("a || exit 1 2>/dev/null; b", "b", "result", "result", [(["a"], S)], True),
    (
        "cat > f <<EOF || exit 1\nhi\nEOF\nb",
        "b",
        "result",
        "result",
        [(["cat"], S)],
        True,
    ),
    ("f() { a || return 1; b; }", "b", "result", "result", [(["a"], S)], False),
    ("a && exit 0; b", "b", "result", "result", [(["a"], F)], True),
    ("a; exit 0; b", "b", "result", "result", [], False),
    (
        "X=$(curl -s u) || exit 1; echo $X",
        "echo",
        "result",
        "result",
        [(["curl"], S)],
        True,
    ),
    # Pipes
    ("curl u | tail -1", "curl", "pipe to tail", "result", [], False),
    ("curl u | tail -1", "tail", "result", "result", [], True),
    ("curl u |& grep x", "curl", "pipe to grep", "pipe to grep", [], False),
    ("curl u 2>&1 | grep x", "curl", "pipe to grep", "pipe to grep", [], False),
    ("a 2>&1 >/dev/null | b", "a", "discard", "pipe to b", [], False),
    ("{ a; b; } | c", "a", "pipe to c", "result", [], False),
    ("{ a; b; } | c", "b", "pipe to c", "result", [], False),
    ("{ x | y; } |& z", "x", "pipe to y", "pipe to z", [], False),
    ("a | { b; c; }", "a", "pipe to b", "result", [], False),
    ("a | b | c", "b", "pipe to c", "result", [], False),
    ("a | (( x ))", "a", "discard", "result", [], False),
    # Redirects
    ("curl u > out.txt 2>&1", "curl", "file out.txt", "file out.txt", [], True),
    ("curl u 2>&1 > out.txt", "curl", "file out.txt", "result", [], True),
    ("2>&1 curl u > f", "curl", "file f", "result", [], True),
    ("> out.txt curl u 2>&1", "curl", "file out.txt", "file out.txt", [], True),
    ("curl u &> out.txt", "curl", "file out.txt", "file out.txt", [], True),
    ("curl u &>> f", "curl", "append f", "append f", [], True),
    ("curl u >> f", "curl", "append f", "result", [], True),
    ("curl u 2>> f", "curl", "result", "append f", [], True),
    ("curl u >> f 2>&1", "curl", "append f", "append f", [], True),
    ("curl u >| f", "curl", "file f", "result", [], True),
    ("curl u >& f", "curl", "file f", "file f", [], True),
    ("curl u 2>/dev/null", "curl", "result", "discard", [], True),
    ("curl u 2>&-", "curl", "result", "discard", [], True),
    ("curl u 1>&3", "curl", "result", "result", [], True),
    ("curl u 3> f", "curl", "result", "result", [], True),
    ("curl u < in.txt", "curl", "result", "result", [], True),
    (
        "curl u 2> /dev/stdout | grep x",
        "curl",
        "pipe to grep",
        "pipe to grep",
        [],
        False,
    ),
    ("echo x > /dev/stderr | cat", "echo", "result", "result", [], False),
    ("{ curl u; } > log 2>&1", "curl", "file log", "file log", [], True),
    ("exec > log 2>&1; curl u", "curl", "file log", "file log", [], True),
    ("exec > >(tee log) 2>&1; curl u", "curl", "pipe to tee", "pipe to tee", [], True),
    ("a > >(b) | c", "a", "pipe to b", "result", [], False),
    ("a > >(b) | c", "b", "pipe to c", "result", [], False),
    ("a 2> >(tee log)", "a", "result", "pipe to tee", [], True),
    ("a 2> >(tee log)", "tee", "result", "result", [], False),
    # $(...), backticks and <(...) hand their stdout to the enclosing command, >(...) does not.
    ("x=$(curl -s u); echo $x", "curl", "capture", "result", [], False),
    ("echo $(curl u)", "curl", "capture", "result", [], False),
    ("A=$(curl u) b", "curl", "capture", "result", [], False),
    ('X="$(a)" && b', "b", "result", "result", [(["a"], S)], True),
    ("for f in $(ls); do a; done", "ls", "capture", "result", [], False),
    ("case $(uname) in x) a ;; esac", "uname", "capture", "result", [], False),
    (
        "while read l; do echo $l; done < <(curl -s u)",
        "curl",
        "capture",
        "result",
        [],
        False,
    ),
    ('jq . <<< "$(curl -s u)"', "curl", "capture", "result", [], False),
    ("cat <<EOF\n$(curl u)\nEOF", "curl", "capture", "result", [], False),
    ("a | tee >(curl -T - u) | b", "curl", "pipe to b", "result", [], False),
    ("time (a && b)", "b", "result", "result", [(["a"], S)], True),
    # Text run by bash -c, and a $(...) that this shell runs before bash does
    ("bash -c 'curl u && b'", "b", "result", "result", [(["curl"], S)], True),
    ("bash -c 'curl u 2>&1' > log", "curl", "file log", "file log", [], True),
    ("bash -c 'curl u' 2> err", "curl", "result", "file err", [], True),
    ("bash -c a || b", "a", "result", "result", [], False),
    ('bash -c "echo $(curl u)"', "curl", "capture", "result", [], False),
    ('eval "$(ssh-agent -s)"', "ssh-agent", "capture", "result", [], False),
    ('bash -c "echo $HOME; x=\\$(curl u)"', "curl", "capture", "result", [], True),
    ("bash -c \"bash -c 'echo $(a)'\"", "a", "capture", "result", [], False),
    # tree-sitter reads these as `(a && b) 2>&1 | c`. Bash runs `a && (b 2>&1 | c)`.
    ("a && b 2>&1 | c", "a", "result", "result", [], True),
    ("a && b 2>&1 | c", "b", "pipe to c", "pipe to c", [(["a"], S)], False),
    ("a && b 2>&1 | c", "c", "result", "result", [(["a"], S)], True),
    ("a || b 2>&1 | c", "c", "result", "result", [(["a"], F)], False),
    # tree-sitter reads these as `(a && b) > f` and `(a | b) > f`.
    ("a && b > f", "a", "result", "result", [], True),
    ("a && b > f", "b", "file f", "result", [(["a"], S)], True),
    ("a | b > f 2>&1", "a", "pipe to b", "result", [], False),
    ("a | b > f 2>&1", "b", "file f", "file f", [], True),
    # tree-sitter reads what follows `<<EOF` on its line as part of the heredoc.
    (
        "cat > f.py <<EOF && python f.py\nx\nEOF",
        "python",
        "result",
        "result",
        [(["cat"], S)],
        True,
    ),
    ("cat > f.py <<EOF && python f.py\nx\nEOF", "cat", "file f.py", "result", [], True),
    ("cat <<EOF || b\nx\nEOF", "b", "result", "result", [(["cat"], F)], False),
    (
        "cd x && a <<EOF || true\ny\nEOF",
        "true",
        "result",
        "result",
        [(["cd", "a"], F)],
        False,
    ),
    ("cd x && a <<EOF || true\ny\nEOF", "a", "result", "result", [(["cd"], S)], False),
    ("python - <<EOF | tail -5\nx\nEOF", "python", "pipe to tail", "result", [], False),
    ("cat <<EOF | grep a | wc -l\nx\nEOF", "grep", "pipe to wc", "result", [], False),
    ("cat <<EOF |& grep x\ny\nEOF", "cat", "pipe to grep", "pipe to grep", [], False),
    ("cd x && python - <<EOF | grep y\nz\nEOF", "cd", "result", "result", [], True),
    (
        "cd x && python - <<EOF | grep y\nz\nEOF",
        "python",
        "pipe to grep",
        "result",
        [(["cd"], S)],
        False,
    ),
    (
        "cd x && python - <<EOF | grep y\nz\nEOF",
        "grep",
        "result",
        "result",
        [(["cd"], S)],
        True,
    ),
]

# (text, the words of every command in order)
COMMAND_CASES = [
    ("echo 'curl u; wget v'", [("echo", "curl u; wget v")]),
    ('echo "curl u"', [("echo", "curl u")]),
    ("# curl u\nls", [("ls",)]),
    ("cat <<EOF\ncurl u\nEOF", [("cat",)]),
    ("cat <<'EOF'\n$(curl u)\nEOF", [("cat",)]),
    ("echo $(curl u)", [("echo", "$(curl u)"), ("curl", "u")]),
    (
        "bash -c 'echo $(curl u)'",
        [("bash", "-c", "echo $(curl u)"), ("echo", "$(curl u)"), ("curl", "u")],
    ),
    (
        'bash -c "echo $(curl u)"',
        [("bash", "-c", "echo $(curl u)"), ("echo", "$(curl u)"), ("curl", "u")],
    ),
    (
        "bash -c 'echo $(a) '\"$B\"",
        [("bash", "-c", "echo $(a) $B"), ("echo", "$(a)", "$B"), ("a",)],
    ),
    (
        "bash -c 'echo $(a)' \"$(a)\"",
        [("bash", "-c", "echo $(a)", "$(a)"), ("echo", "$(a)"), ("a",), ("a",)],
    ),
    ("time (a && b)", [("time",), ("a",), ("b",)]),
    ("a && b ||", [("a",), ("b",)]),
    ("pip install \\\n  x", [("pip", "install", "x")]),
]


@pytest.mark.parametrize(
    (
        "text",
        "first_word",
        "stdout",
        "stderr",
        "runs_if",
        "succeeded_if_text_exits_zero",
    ),
    STRUCTURE_CASES,
)
def test_structure(
    text: str,
    first_word: str,
    stdout: str,
    stderr: str,
    runs_if: list[tuple[list[str], ExitOutcome]],
    succeeded_if_text_exits_zero: bool,
):
    parsed = parse_shell(text)
    command = _command(parsed, first_word)
    first_word_of_id = {c.id: c.words[0] for c in parsed.commands}
    conditions = [
        (
            [first_word_of_id[i] for i in c.deciding_command_ids],
            c.required_outcome_of_deciding_commands,
        )
        for c in command.runs_if
    ]
    actual = (
        _shown(command.stdout, parsed),
        _shown(command.stderr, parsed),
        conditions,
        command.succeeded_if_text_exits_zero,
    )
    assert actual == (stdout, stderr, runs_if, succeeded_if_text_exits_zero)


@pytest.mark.parametrize(("text", "words"), COMMAND_CASES)
def test_commands_found(text: str, words: list[tuple[str, ...]]):
    assert [c.words for c in parse_shell(text).commands] == words


def test_example_of_the_pipeline_doc():
    parsed = parse_shell("bash fetch.sh > fetch.log 2>&1 || pip install requests")
    assert parsed == ParsedShellText(
        commands=(
            ShellCommand(
                id=0,
                words=("bash", "fetch.sh"),
                stdout=FileDestination("fetch.log", appends=False),
                stderr=FileDestination("fetch.log", appends=False),
            ),
            ShellCommand(
                id=1,
                words=("pip", "install", "requests"),
                runs_if=(RunCondition((0,), F),),
            ),
        )
    )


@pytest.mark.parametrize(
    "text",
    [
        "ps aux | grep a | grep -v grep\ncurl u 2>/dev/null | tail -1",
        "ps aux | grep a | grep -v grep # note\ncurl u 2>/dev/null | tail -1",
    ],
)
def test_joined_lines_are_kept_apart(text: str):
    # tree-sitter reads the second line as more arguments of `grep -v grep`.
    parsed = parse_shell(text)
    assert [c.words for c in parsed.commands] == [
        ("ps", "aux"),
        ("grep", "a"),
        ("grep", "-v", "grep"),
        ("curl", "u"),
        ("tail", "-1"),
    ]
    grep, curl = parsed.commands[2], parsed.commands[3]
    assert (grep.stdout, grep.stderr) == (ResultDestination(), ResultDestination())
    assert curl.stderr == DiscardDestination()
    assert not grep.succeeded_if_text_exits_zero


@pytest.mark.parametrize(
    ("text", "first_words"),
    [
        ("a | b | c\nd\ne 2>&1", "abcde"),  # two joined lines found in one pass
        (
            "s\nn 2>&1 | p | q | r\nf 2>/dev/null | g | h\nx 2>&1\ns",
            "snpqrfghxs",
        ),  # two passes
    ],
)
def test_several_joined_lines_are_kept_apart(text: str, first_words: str):
    commands = parse_shell(text).commands
    assert [c.words[0] for c in commands] == list(first_words)
    assert not any(c.structure_may_be_wrong for c in commands)


def test_joined_lines_with_non_ascii_words():
    # The positions where `;` goes are byte offsets.
    parsed = parse_shell("echo 한글 | b | c\nd é | e")
    assert [c.words for c in parsed.commands] == [
        ("echo", "한글"),
        ("b",),
        ("c",),
        ("d", "é"),
        ("e",),
    ]


def test_joined_line_with_heredoc():
    parsed = parse_shell("a | b | c\npython3 - <<EOF\nprint(1)\nEOF")
    assert [c.words for c in parsed.commands] == [("a",), ("b",), ("c",), ("python3",)]
    assert [c.stdin_text for c in parsed.commands] == [None, None, None, "print(1)\n"]


@pytest.mark.parametrize(
    ("text", "field", "first_words"),
    [
        ("for p in a b; do pip install $p; done; c", "in_loop_body", ["pip"]),
        ("while true; do curl u; done", "in_loop_body", ["curl"]),
        ("for ((i=0; i<3; i++)); do curl u; done", "in_loop_body", ["curl"]),
        ("for i in 1 2; do bash -c 'curl u'; done", "in_loop_body", ["bash", "curl"]),
        ("f() { git clone u; }; f", "in_function_body", ["git"]),
        ("f() { bash -c 'curl u'; }", "in_function_body", ["bash", "curl"]),
        (
            "case $OS in debian) apt-get install -y x ;; esac; b",
            "in_case_branch",
            ["apt-get"],
        ),
        ("case x in x) bash -c 'curl u' ;; esac", "in_case_branch", ["bash", "curl"]),
        ("nohup pip install x > p.log 2>&1 & b", "runs_in_background", ["nohup"]),
        ("a && bash -c 'curl u' & b", "runs_in_background", ["a", "bash", "curl"]),
    ],
)
def test_flag_is_set_only_where_it_holds(text: str, field: str, first_words: list[str]):
    commands = parse_shell(text).commands
    assert [c.words[0] for c in commands if getattr(c, field)] == first_words


@pytest.mark.parametrize(
    ("text", "first_word", "has_expansion"),
    [
        ("pip install $PKG", "pip", True),
        ('pip install "$(cat reqs)"', "pip", True),
        ("pip install x", "pip", False),
        ("echo '$A'", "echo", False),
    ],
)
def test_has_expansion(text: str, first_word: str, has_expansion: bool):
    assert _command(parse_shell(text), first_word).has_expansion == has_expansion


def test_background_command_keeps_its_destinations():
    curl = _command(parse_shell("curl u > log 2>&1 &"), "curl")
    assert curl.runs_in_background
    assert (curl.stdout, curl.stderr) == (
        FileDestination("log", appends=False),
        FileDestination("log", appends=False),
    )


@pytest.mark.parametrize(
    ("text", "first_word", "stdin_text"),
    [
        ("python - <<EOF\nimport requests\nEOF", "python", "import requests\n"),
        ("cat <<EOF\nEOF", "cat", ""),
        ("cat <<< 'curl u'", "cat", "curl u"),
        ("while read l; do X=$(curl $l); done <<EOF\nu\nEOF", "read", "u\n"),
        ("while read l; do X=$(curl $l); done <<EOF\nu\nEOF", "curl", None),
    ],
)
def test_stdin_text(text: str, first_word: str, stdin_text: str | None):
    assert _command(parse_shell(text), first_word).stdin_text == stdin_text


@pytest.mark.parametrize(
    ("text", "first_word", "stdin_file_path", "stdin_text"),
    [
        ("grep x < log", "grep", "log", None),
        ("{ cat; tail -1; } < f", "tail", "f", None),
        # A later pipeline stage reads the pipe.
        ("{ echo x | grep x; } < f", "grep", None, None),
        ("{ echo x | grep x; } < f", "echo", "f", None),
        ("a | grep x < f", "grep", "f", None),
        # `< <(cmd)` gives stdin the output of cmd.
        ("while read l; do echo $l; done < <(curl u)", "read", None, None),
        # The later redirect of stdin wins, as in bash.
        ("cat <<EOF < f\nx\nEOF", "cat", "f", None),
        ("cat < f <<EOF\nx\nEOF", "cat", None, "x\n"),
        ("cat 3< f", "cat", None, None),
        ("cat <&3", "cat", None, None),
        # A substitution runs before the redirect, so it does not read f.
        ("X=$(cat) < f", "cat", None, None),
    ],
)
def test_stdin_file_path(
    text: str, first_word: str, stdin_file_path: str | None, stdin_text: str | None
):
    command = _command(parse_shell(text), first_word)
    assert (command.stdin_file_path, command.stdin_text) == (
        stdin_file_path,
        stdin_text,
    )


def test_heredoc_with_output_file():
    cat = _command(parse_shell("cat <<EOF > fetch.sh\ncurl u\nEOF"), "cat")
    assert (cat.stdout, cat.stdin_text) == (
        FileDestination("fetch.sh", appends=False),
        "curl u\n",
    )


@pytest.mark.parametrize(
    ("text", "flags"),
    [
        ("cp {a,b} d && curl u", [True, True]),
        ("echo x{1..3} && curl u", [True, True]),
        ("echo {a..c}", [True]),
        ("curl 'u && echo x", [True]),  # an unclosed quote
        ("a && bash -c 'cp {x,y} d'", [False, False, True]),
        ("curl u && echo '{a,b}'", [False, False]),
        ('curl --data=\'{"a":1,"b":2}\' u', [False]),
        ("find . -exec curl {} \\;", [False]),
    ],
)
def test_structure_may_be_wrong(text: str, flags: list[bool]):
    assert [c.structure_may_be_wrong for c in parse_shell(text).commands] == flags


def test_nested_text_takes_the_place_of_its_runner():
    parsed = parse_shell("a && sudo bash -lc 'pip install x || true' > log &")
    bash = _command(parsed, "sudo")
    pip = _command(parsed, "pip")
    assert pip.id > bash.id
    assert pip.stdout == FileDestination("log", appends=False)
    assert pip.runs_if == bash.runs_if == (RunCondition((0,), S),)
    assert pip.runs_in_background
    assert not pip.succeeded_if_text_exits_zero  # it is left of ||


def test_nesting_depth_is_limited():
    text = 'bash -c "bash -c \'bash -c \\"bash -c curl\\"\'"'
    words = [c.words[0] for c in parse_shell(text).commands]
    assert words == ["bash", "bash", "bash", "bash"]


def test_runner_gives_its_scope():
    runner = ShellCommand(
        id=4,
        words=("bash", "-e", "fetch.sh"),
        stdout=FileDestination("fetch.log", appends=False),
        stderr=DiscardDestination(),
        stdin_file_path="in",
        runs_if=(RunCondition((3,), S),),
        succeeded_if_text_exits_zero=True,
        structure_may_be_wrong=True,
    )
    parsed = parse_shell("curl -sS u 2>&1\nwget v\nls", runner=runner, first_id=5)
    curl, wget, _ = parsed.commands
    assert curl.id == 5
    assert (curl.stdout, curl.stderr) == (
        FileDestination("fetch.log", appends=False),
    ) * 2
    assert (wget.stdout, wget.stderr) == (
        FileDestination("fetch.log", appends=False),
        DiscardDestination(),
    )
    assert curl.runs_if == runner.runs_if
    # Text run by a command takes no stdin from it, a chosen limit noted at `_FIELDS_FROM_RUNNER`.
    assert curl.stdin_file_path is None
    assert all(c.structure_may_be_wrong for c in parsed.commands)
    # bash -e makes every plain statement decide the exit code.
    assert [c.succeeded_if_text_exits_zero for c in parsed.commands] == [
        True,
        True,
        True,
    ]


def test_pipe_reader_is_an_id_from_first_id():
    parsed = parse_shell("a | b", first_id=7)
    assert [c.id for c in parsed.commands] == [7, 8]
    assert parsed.commands[0].stdout == PipeDestination(8)


@pytest.mark.parametrize(
    ("text", "assignments"),
    [
        ('URL="https://a.org/x"; curl "$URL"', [("URL", "https://a.org/x", 0, None)]),
        ("echo $U; U=x; echo $U", [("U", "x", 1, None)]),
        ("export A=1; local B=2", [("A", "1", 0, None), ("B", "2", 0, None)]),
        ("X=", [("X", "", 0, None)]),
        ("X={a,b}", [("X", "{a,b}", 0, None)]),
        ("X=*.txt", [("X", "*.txt", 0, None)]),  # an assignment is not globbed
        ("X=$(date)", [("X", None, 0, None)]),
        ("X=$A/x", [("X", None, 0, None)]),
        ("X=(a b)", [("X", None, 0, None)]),
        ("X+=a", [("X", None, 0, None)]),
        ("for p in a b; do pip install $p; done", [("p", "a", 0, 1), ("p", "b", 0, 1)]),
        ("for p in 'a b' c; do :; done", [("p", "a b", 0, 1), ("p", "c", 0, 1)]),
        ("for p in $(ls); do :; done", [("p", None, 0, 2)]),
        ("for i in {1..3}; do :; done", [("i", None, 0, 1)]),
        ("for f in *.txt; do :; done", [("f", None, 0, 1)]),
        ("for f in 'a*'; do :; done", [("f", "a*", 0, 1)]),
        ("for x; do :; done", [("x", None, 0, 1)]),  # loops over the arguments
        (
            "for i in 1 2; do for j in a; do x; done; y; done; z",
            [("i", "1", 0, 2), ("i", "2", 0, 2), ("j", "a", 0, 1)],
        ),
        ("for ((i=0; i<3; i++)); do :; done", [("i", None, 0, None)]),
        ("A=1 curl u", []),  # A is given to curl only
        ("bash -c 'A=1'", []),  # assignments in text a new shell runs are left out
        ("eval 'A=1'; echo $A", [("A", "1", 1, None)]),  # eval runs in this shell
    ],
)
def test_assignments(
    text: str, assignments: list[tuple[str, str | None, int, int | None]]
):
    expected = tuple(VariableAssignment(*a) for a in assignments)
    assert parse_shell(text).assignments == expected


def _command(parsed: ParsedShellText, first_word: str) -> ShellCommand:
    """The only command whose first word is `first_word`."""
    (command,) = [c for c in parsed.commands if c.words[:1] == (first_word,)]
    return command


def _shown(destination: OutputDestination, parsed: ParsedShellText) -> str:
    """A destination in short words, with a pipe named by its reader's first word."""
    match destination:
        case ResultDestination():
            return "result"
        case FileDestination(path, appends):
            return f"{'append' if appends else 'file'} {path}"
        case PipeDestination(reader_id):
            (reader,) = [c for c in parsed.commands if c.id == reader_id]
            return f"pipe to {reader.words[0]}"
        case CaptureDestination():
            return "capture"
        case DiscardDestination():
            return "discard"
