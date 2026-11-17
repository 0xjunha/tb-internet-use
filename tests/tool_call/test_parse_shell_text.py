"""Tests for parse_shell_text.py, with made-up shell texts."""

from collections import Counter

import pytest

import tb_internet_use.tool_call.parse_shell_text as parse_shell_text_module
from tb_internet_use.tool_call.judgment_rules import (
    treat_lines_joined_after_three_repairs_as_left_joined,
)
from tb_internet_use.tool_call.model import (
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
    UnreadableShellText,
    VariableAssignment,
)
from tb_internet_use.tool_call.parse_shell_text import (
    command_substitution_texts_of,
    parse_shell_text,
)

SUCCESS = ExitOutcome.SUCCESS
FAILURE = ExitOutcome.FAILURE

# (text, the whole expected result), where a field left out has its default
WHOLE_RESULT_CASES = [
    (
        "cd /app && curl -s u > log",
        ParsedShellText(
            (
                ShellCommand(0, ("cd", "/app"), succeeded_if_text_exits_zero=True),
                ShellCommand(
                    1,
                    ("curl", "-s", "u"),
                    stdout=FileDestination("log", False),
                    runs_if=(RunCondition((0,), SUCCESS),),
                    succeeded_if_text_exits_zero=True,
                ),
            ),
            (),
        ),
    ),
    # Text that a command runs stays one word of it.
    (
        "sudo bash -c 'curl u'",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("sudo", "bash", "-c", "curl u"),
                    succeeded_if_text_exits_zero=True,
                ),
            ),
            (),
        ),
    ),
    # eval runs its text in this shell, but its assignments are left to the caller that reads the text.
    (
        "eval 'A=1'; echo $A",
        ParsedShellText(
            (
                ShellCommand(0, ("eval", "A=1")),
                ShellCommand(
                    1,
                    ("echo", "$A"),
                    expansion_word_indexes=(1,),
                    succeeded_if_text_exits_zero=True,
                ),
            ),
            (),
        ),
    ),
    (
        "U=a.org; curl $U",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("curl", "$U"),
                    expansion_word_indexes=(1,),
                    succeeded_if_text_exits_zero=True,
                ),
            ),
            (VariableAssignment("U", "a.org", 0, None),),
        ),
    ),
    (
        "curl u | tail -1",
        ParsedShellText(
            (
                ShellCommand(0, ("curl", "u"), stdout=PipeDestination(1)),
                ShellCommand(1, ("tail", "-1"), succeeded_if_text_exits_zero=True),
            ),
            (),
        ),
    ),
    # tree-sitter puts the `-` in no node, and the reading adds it back.
    (
        "python - <<EOF\nimport x\nEOF",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("python", "-"),
                    stdin_text="import x\n",
                    succeeded_if_text_exits_zero=True,
                ),
            ),
            (),
        ),
    ),
    # The `-` that tree-sitter leaves out takes its place among the words, so later word indexes count it.
    (
        "cmd - 2>&1 $A",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("cmd", "-", "$A"),
                    expansion_word_indexes=(2,),
                    succeeded_if_text_exits_zero=True,
                ),
            ),
            (),
        ),
    ),
    # A word after the redirect target of a statement that is no simple command is lost, and `[ ]` gives no command.
    ("[ -f x ] > f b", ParsedShellText((), ())),
    # A word that tree-sitter put into a redirect takes its place among the words, and its $(...) is walked once.
    (
        "cmd 2>&1 $(curl u)",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("cmd", "$(curl u)"),
                    expansion_word_indexes=(1,),
                    succeeded_if_text_exits_zero=True,
                ),
                ShellCommand(1, ("curl", "u"), stdout=CaptureDestination()),
            ),
            (),
        ),
    ),
    # The reserved word time and its -p are no words of the command, so word indexes start after them.
    (
        "time -p curl $U",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("curl", "$U"),
                    expansion_word_indexes=(1,),
                    succeeded_if_text_exits_zero=True,
                ),
            ),
            (),
        ),
    ),
    (
        "for p in A B; do pip install $p; done",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("pip", "install", "$p"),
                    expansion_word_indexes=(2,),
                    in_loop_body=True,
                ),
            ),
            (VariableAssignment("p", "A", 0, 1), VariableAssignment("p", "B", 0, 1)),
        ),
    ),
    (
        "curl u > /dev/null 2>&1",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("curl", "u"),
                    stdout=DiscardDestination(),
                    stderr=DiscardDestination(),
                    succeeded_if_text_exits_zero=True,
                ),
            ),
            (),
        ),
    ),
    (
        "curl u >> log 2>&1 &",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("curl", "u"),
                    stdout=FileDestination("log", True),
                    stderr=FileDestination("log", True),
                ),
            ),
            (),
        ),
    ),
    (
        "a || b",
        ParsedShellText(
            (
                ShellCommand(0, ("a",)),
                ShellCommand(1, ("b",), runs_if=(RunCondition((0,), FAILURE),)),
            ),
            (),
        ),
    ),
    (
        "set -e; a; b",
        ParsedShellText(
            (
                ShellCommand(0, ("set", "-e")),
                ShellCommand(
                    1,
                    ("a",),
                    runs_if=(RunCondition((0,), SUCCESS),),
                    succeeded_if_text_exits_zero=True,
                ),
                ShellCommand(
                    2,
                    ("b",),
                    runs_if=(RunCondition((1,), SUCCESS),),
                    succeeded_if_text_exits_zero=True,
                ),
            ),
            (),
        ),
    ),
    (
        "grep x < log",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("grep", "x"),
                    stdin_file_path="log",
                    succeeded_if_text_exits_zero=True,
                ),
            ),
            (),
        ),
    ),
    (
        "echo \"$(date)\" '$HOME' `ls`",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("echo", "$(date)", "$HOME", "`ls`"),
                    expansion_word_indexes=(1, 3),
                    succeeded_if_text_exits_zero=True,
                ),
                ShellCommand(1, ("date",), stdout=CaptureDestination()),
                ShellCommand(2, ("ls",), stdout=CaptureDestination()),
            ),
            (),
        ),
    ),
    (
        "f() { curl u; }",
        ParsedShellText((ShellCommand(0, ("curl", "u"), in_function_body=True),), ()),
    ),
    (
        "case x in a) curl u ;; esac",
        ParsedShellText((ShellCommand(0, ("curl", "u"), in_case_branch=True),), ()),
    ),
    # Without fi the text has a syntax error, and the test `[ -f x ]` is no simple command.
    (
        "if [ -f x ]; then curl u",
        ParsedShellText(
            (ShellCommand(0, ("curl", "u"), structure_may_be_wrong=True),), ()
        ),
    ),
    (
        "cp {a,b} d && curl u",
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("cp", "{a,b}", "d"),
                    succeeded_if_text_exits_zero=True,
                    structure_may_be_wrong=True,
                ),
                ShellCommand(
                    1,
                    ("curl", "u"),
                    runs_if=(RunCondition((0,), SUCCESS),),
                    succeeded_if_text_exits_zero=True,
                    structure_may_be_wrong=True,
                ),
            ),
            (),
        ),
    ),
    # tree-sitter reads the second line as more words of c, and a `;` keeps it apart.
    (
        "a | b | c\nd 2>&1 | e",
        ParsedShellText(
            (
                ShellCommand(0, ("a",), stdout=PipeDestination(1)),
                ShellCommand(1, ("b",), stdout=PipeDestination(2)),
                ShellCommand(2, ("c",)),
                ShellCommand(
                    3, ("d",), stdout=PipeDestination(4), stderr=PipeDestination(4)
                ),
                ShellCommand(4, ("e",), succeeded_if_text_exits_zero=True),
            ),
            (),
        ),
    ),
    ("", ParsedShellText((), ())),
    ("# note", ParsedShellText((), ())),
    # A redirect alone and an assignment alone run no command.
    ("> f", ParsedShellText((), ())),
    ("A=1", ParsedShellText((), (VariableAssignment("A", "1", 0, None),))),
    # The outer shell runs `$(curl u)` and hands its output to bash.
    (
        'bash -c "echo $(curl u)"',
        ParsedShellText(
            (
                ShellCommand(
                    0,
                    ("bash", "-c", "echo $(curl u)"),
                    expansion_word_indexes=(2,),
                    succeeded_if_text_exits_zero=True,
                ),
                ShellCommand(1, ("curl", "u"), stdout=CaptureDestination()),
            ),
            (),
        ),
    ),
    # A syntax error with no command is unreadable, and the assignment read from it is dropped.
    (")))", UnreadableShellText()),
    ("A=1 )))", UnreadableShellText()),
]

# (text, the command by its first word, stdout, stderr,
#  run conditions as (first words of the deciding commands, outcome), succeeded_if_text_exits_zero)
STRUCTURE_CASES = [
    # Sequences and lists
    ("a; b", "a", "result", "result", [], False),
    ("a; b", "b", "result", "result", [], True),
    ("a && b && c", "c", "result", "result", [(["a", "b"], SUCCESS)], True),
    ("a && b || c", "b", "result", "result", [(["a"], SUCCESS)], False),
    ("a && b || c", "c", "result", "result", [(["a", "b"], FAILURE)], False),
    ("a || b && c", "b", "result", "result", [(["a"], FAILURE)], False),
    ("a || b && c", "c", "result", "result", [(["a", "b"], SUCCESS)], True),
    (
        "(cd d && make) || curl u",
        "curl",
        "result",
        "result",
        [(["cd", "make"], FAILURE)],
        False,
    ),
    ("curl -s u & b", "curl", "result", "result", [], False),
    ("curl u > log 2>&1 &", "curl", "file log", "file log", [], False),
    # A side whose deciding commands are unknown makes the whole list's unknown.
    ("! curl -f u", "curl", "result", "result", [], False),
    ("! a && curl u", "curl", "result", "result", [([], SUCCESS)], True),
    # tree-sitter reads `! a | b` as `(! a) | b`. Bash runs `! (a | b)`.
    ("! a | b", "b", "result", "result", [], False),
    (
        "if ! a | grep -q x; then c; else d; fi",
        "c",
        "result",
        "result",
        [([], SUCCESS)],
        False,
    ),
    (
        "[ -f x ] && echo yes || curl u",
        "curl",
        "result",
        "result",
        [([], FAILURE)],
        False,
    ),
    ("a && ! b || curl u", "curl", "result", "result", [([], FAILURE)], False),
    ("(a &) && curl u", "curl", "result", "result", [([], SUCCESS)], True),
    ("f() { a; } && b", "b", "result", "result", [([], SUCCESS)], True),
    # if, while and until
    (
        "if curl -f u; then echo ok; fi",
        "echo",
        "result",
        "result",
        [(["curl"], SUCCESS)],
        False,
    ),
    (
        "if a; then b; else curl u; fi",
        "curl",
        "result",
        "result",
        [(["a"], FAILURE)],
        False,
    ),
    (
        "if a; then b; elif c; then d; fi",
        "d",
        "result",
        "result",
        [(["a"], FAILURE), (["c"], SUCCESS)],
        False,
    ),
    (
        "if a; then b; elif c; then d; else e; fi",
        "e",
        "result",
        "result",
        [(["a"], FAILURE), (["c"], FAILURE)],
        False,
    ),
    (
        "while curl -s u; do sleep 1; done",
        "sleep",
        "result",
        "result",
        [(["curl"], SUCCESS)],
        False,
    ),
    (
        "until curl -s u; do sleep 1; done",
        "sleep",
        "result",
        "result",
        [(["curl"], FAILURE)],
        False,
    ),
    ("while a # c\ndo b; done; d", "b", "result", "result", [(["a"], SUCCESS)], False),
    # set -e and pipefail
    ("a; set -e; b", "a", "result", "result", [], False),
    ("set -o errexit; a; b", "a", "result", "result", [(["set"], SUCCESS)], True),
    ("set -eu; a; b", "a", "result", "result", [(["set"], SUCCESS)], True),
    (
        "set -euo pipefail; a | b; c",
        "a",
        "pipe to b",
        "result",
        [(["set"], SUCCESS)],
        True,
    ),
    ("set -e; set +e; a; b", "a", "result", "result", [(["set"], SUCCESS)], False),
    ("set -- -e x; a; b", "a", "result", "result", [], False),
    ("grep -e x f; a; b", "a", "result", "result", [], False),
    # set -e does not end the text when the left side of && fails.
    ("set -e; a && b; c", "a", "result", "result", [(["set"], SUCCESS)], False),
    ("set -e; a && b; c", "c", "result", "result", [(["set"], SUCCESS)], True),
    ("set -e; { a; b; } && c", "a", "result", "result", [(["set"], SUCCESS)], False),
    (
        "set -e; false && echo x > f; true",
        "true",
        "result",
        "result",
        [(["set"], SUCCESS)],
        True,
    ),
    (
        "set -e; a; b | while read x; do :; done; c",
        "c",
        "result",
        "result",
        [(["a"], SUCCESS), ([], SUCCESS)],
        True,
    ),
    (
        "set -e; if a; then b; fi; c",
        "a",
        "result",
        "result",
        [(["set"], SUCCESS)],
        False,
    ),
    (
        "set -e; while a; do b; done; c",
        "c",
        "result",
        "result",
        [(["set"], SUCCESS)],
        True,
    ),
    ("set -e; ! a; b", "b", "result", "result", [(["set"], SUCCESS)], True),
    # Statements other than commands that end the text on failure
    ("set -e; V=$(curl u); b", "b", "result", "result", [(["curl"], SUCCESS)], True),
    ("set -e; A=1 B=$(b); c", "c", "result", "result", [(["b"], SUCCESS)], True),
    ("set -e; ! a | b; c", "c", "result", "result", [(["set"], SUCCESS)], True),
    # eval is a command here, so a `set +e` in its text does not turn set -e off.
    ('set -e; eval "set +e"; a; b', "b", "result", "result", [(["a"], SUCCESS)], True),
    # The $(...) whose exit code an assignment takes decides the text's exit code.
    ("x=$(curl u)", "curl", "capture", "result", [], True),
    ("set -e; X=1; b", "b", "result", "result", [(["set"], SUCCESS)], True),
    (
        "set -e; (cd x && make); b",
        "b",
        "result",
        "result",
        [(["cd", "make"], SUCCESS)],
        True,
    ),
    (
        "set -e; [ -f x ]; b",
        "b",
        "result",
        "result",
        [(["set"], SUCCESS), ([], SUCCESS)],
        True,
    ),
    # Inside a non-last pipeline stage set -e still holds.
    (
        "set -e; { a; b; } | c",
        "b",
        "pipe to c",
        "result",
        [(["set"], SUCCESS), (["a"], SUCCESS)],
        False,
    ),
    # Bash turns set -e off inside $(...).
    ("set -e; x=$(a; b); c", "b", "capture", "result", [(["set"], SUCCESS)], True),
    # set inside a subshell or a function ends with it.
    ("(set -e; a); b; c", "b", "result", "result", [], False),
    ("f() { set -e; }; a; b", "a", "result", "result", [], False),
    ("set -o pipefail; curl u | tail -1", "curl", "pipe to tail", "result", [], True),
    (
        "set -o pipefail; a | b && c",
        "c",
        "result",
        "result",
        [(["a", "b"], SUCCESS)],
        True,
    ),
    ("a | b && c", "c", "result", "result", [(["b"], SUCCESS)], True),
    # exit
    ("a || exit 1; curl u", "curl", "result", "result", [(["a"], SUCCESS)], True),
    (
        "a || { echo failed; exit 1; }; curl u",
        "curl",
        "result",
        "result",
        [(["a"], SUCCESS)],
        True,
    ),
    ("a || { exit 1; echo x; }; b", "b", "result", "result", [], True),
    ("a || (exit 1); b", "b", "result", "result", [], True),
    ("a || exit 1 2>/dev/null; b", "b", "result", "result", [(["a"], SUCCESS)], True),
    (
        "cat > f <<EOF || exit 1\nhi\nEOF\nb",
        "b",
        "result",
        "result",
        [(["cat"], SUCCESS)],
        True,
    ),
    ("f() { a || return 1; b; }", "b", "result", "result", [(["a"], SUCCESS)], False),
    ("a && exit 0; b", "b", "result", "result", [(["a"], FAILURE)], True),
    ("a; exit 0; b", "b", "result", "result", [], False),
    (
        "X=$(curl -s u) || exit 1; echo $X",
        "echo",
        "result",
        "result",
        [(["curl"], SUCCESS)],
        True,
    ),
    # Pipes
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
    ("curl u >| f", "curl", "file f", "result", [], True),
    ("curl u >& f", "curl", "file f", "file f", [], True),
    ("curl u 2>/dev/null", "curl", "result", "discard", [], True),
    ("curl u 2>&-", "curl", "result", "discard", [], True),
    ("curl u 1>&3", "curl", "result", "result", [], True),
    ("curl u 3> f", "curl", "result", "result", [], True),
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
    ("A=$(curl u) b", "curl", "capture", "result", [], False),
    ('X="$(a)" && b', "b", "result", "result", [(["a"], SUCCESS)], True),
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
    ("time (a && b)", "b", "result", "result", [(["a"], SUCCESS)], True),
    # time times the whole pipeline and leaves its pipes, conditions and exit code as they are.
    ("time a | b", "a", "pipe to b", "result", [], False),
    ("a && time b > f", "b", "file f", "result", [(["a"], SUCCESS)], True),
    ("! time a", "a", "result", "result", [], False),
    ("time (a) || b", "b", "result", "result", [(["a"], FAILURE)], False),
    ("time a && b", "b", "result", "result", [(["a"], SUCCESS)], True),
    # exec with a word that tree-sitter put into its redirect runs that word, so later output stays.
    ("exec > f x; y", "y", "result", "result", [], True),
    # A $(...) in a word that tree-sitter put into a redirect gets the scope after the redirects, as one before the redirect does.
    # Bash expands the words before it applies the redirects, so curl's stderr would reach the result there.
    ("cmd 2>/dev/null $(curl u)", "curl", "capture", "discard", [], False),
    # The outer shell runs the $(...) in a word that it expands, also inside single quotes within double quotes.
    ('eval "$(ssh-agent -s)"', "ssh-agent", "capture", "result", [], False),
    ("bash -c \"bash -c 'echo $(a)'\"", "a", "capture", "result", [], False),
    # tree-sitter reads these as `(a && b) 2>&1 | c`. Bash runs `a && (b 2>&1 | c)`.
    ("a && b 2>&1 | c", "a", "result", "result", [], True),
    ("a && b 2>&1 | c", "b", "pipe to c", "pipe to c", [(["a"], SUCCESS)], False),
    ("a && b 2>&1 | c", "c", "result", "result", [(["a"], SUCCESS)], True),
    ("a || b 2>&1 | c", "c", "result", "result", [(["a"], FAILURE)], False),
    # tree-sitter reads these as `(a && b) > f` and `(a | b) > f`.
    ("a && b > f", "a", "result", "result", [], True),
    ("a && b > f", "b", "file f", "result", [(["a"], SUCCESS)], True),
    ("a | b > f 2>&1", "a", "pipe to b", "result", [], False),
    ("a | b > f 2>&1", "b", "file f", "file f", [], True),
    # tree-sitter reads what follows `<<EOF` on its line as part of the heredoc.
    (
        "cat > f.py <<EOF && python f.py\nx\nEOF",
        "python",
        "result",
        "result",
        [(["cat"], SUCCESS)],
        True,
    ),
    ("cat > f.py <<EOF && python f.py\nx\nEOF", "cat", "file f.py", "result", [], True),
    ("cat <<EOF || b\nx\nEOF", "b", "result", "result", [(["cat"], FAILURE)], False),
    (
        "cd x && a <<EOF || true\ny\nEOF",
        "true",
        "result",
        "result",
        [(["cd", "a"], FAILURE)],
        False,
    ),
    (
        "cd x && a <<EOF || true\ny\nEOF",
        "a",
        "result",
        "result",
        [(["cd"], SUCCESS)],
        False,
    ),
    ("python - <<EOF | tail -5\nx\nEOF", "python", "pipe to tail", "result", [], False),
    ("cat <<EOF | grep a | wc -l\nx\nEOF", "grep", "pipe to wc", "result", [], False),
    ("cat <<EOF |& grep x\ny\nEOF", "cat", "pipe to grep", "pipe to grep", [], False),
    ("cd x && python - <<EOF | grep y\nz\nEOF", "cd", "result", "result", [], True),
    (
        "cd x && python - <<EOF | grep y\nz\nEOF",
        "python",
        "pipe to grep",
        "result",
        [(["cd"], SUCCESS)],
        False,
    ),
    (
        "cd x && python - <<EOF | grep y\nz\nEOF",
        "grep",
        "result",
        "result",
        [(["cd"], SUCCESS)],
        True,
    ),
]

# Text that a command of the outer text runs, read with that command as `runner` as the caller of `parse_shell_text` does.
# (outer text, first word of the runner, inner text, set_arguments_at_start, command_substitution_texts_run_by_outer_shell,
#  the inner command by its first word, stdout, stderr, run conditions as in STRUCTURE_CASES, succeeded_if_text_exits_zero)
INNER_TEXT_STRUCTURE_CASES = [
    (
        "bash -c 'curl u && b'",
        "bash",
        "curl u && b",
        (),
        frozenset(),
        "b",
        "result",
        "result",
        [(["curl"], SUCCESS)],
        True,
    ),
    (
        "bash -c 'curl u 2>&1' > log",
        "bash",
        "curl u 2>&1",
        (),
        frozenset(),
        "curl",
        "file log",
        "file log",
        [],
        True,
    ),
    (
        "bash -c 'curl u' 2> err",
        "bash",
        "curl u",
        (),
        frozenset(),
        "curl",
        "result",
        "file err",
        [],
        True,
    ),
    (
        "bash -c a || b",
        "bash",
        "a",
        (),
        frozenset(),
        "a",
        "result",
        "result",
        [],
        False,
    ),
    # set of the outer text holds in the text of bash -c only through its options.
    (
        "set -e; bash -c 'a; b'",
        "bash",
        "a; b",
        (),
        frozenset(),
        "a",
        "result",
        "result",
        [(["set"], SUCCESS)],
        False,
    ),
    (
        "bash -euo pipefail -c 'a | b; c'",
        "bash",
        "a | b; c",
        ("-euo", "pipefail"),
        frozenset(),
        "a",
        "pipe to b",
        "result",
        [],
        True,
    ),
    # The outer shell turns `\$` into `$`, so the inner shell runs curl.
    (
        'bash -c "echo $HOME; x=\\$(curl u)"',
        "bash",
        "echo $HOME; x=$(curl u)",
        (),
        frozenset(),
        "curl",
        "capture",
        "result",
        [],
        True,
    ),
    # eval runs its text left of ||, and the caller gives it no set options.
    (
        'set -e; eval "a; b" || c',
        "eval",
        "a; b",
        (),
        frozenset(),
        "b",
        "result",
        "result",
        [(["set"], SUCCESS)],
        False,
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
    ("a && b ||", [("a",), ("b",)]),
    # tree-sitter puts a `-` before a heredoc or a redirect with a descriptor number in no node.
    ("cat - - <<EOF\nx\nEOF", [("cat", "-", "-")]),
    ("cat - \\\n  <<EOF\nx\nEOF", [("cat", "-")]),
    ("cat - 2>/dev/null", [("cat", "-")]),
    ("cat 2>&1 - <<EOF\nx\nEOF", [("cat", "-")]),
    ("cat - 2>&1 - <<EOF\nx\nEOF", [("cat", "-", "-")]),
    ("cmd - 2>&1 a", [("cmd", "-", "a")]),
    ("cmd - 2>&1 a - <<EOF\nx\nEOF", [("cmd", "-", "a", "-")]),
    # Guards that a written option before a heredoc gains no `-`.
    ("python -u <<EOF\nx\nEOF", [("python", "-u")]),
    # A `-` in a tree with a syntax error stays lost, and the commands are marked (see test_structure_may_be_wrong).
    ("python - <<EOF `\nx\nEOF", [("python",), ("x",), ("EOF",)]),
    # tree-sitter puts words after a redirect target into the redirect, and the reading gives them back to the command.
    ("cmd >f a", [("cmd", "a")]),
    ("cmd 2>&1 a b", [("cmd", "a", "b")]),
    # The word that tree-sitter put into the redirect is itself a `-`.
    ("cmd > f -", [("cmd", "-")]),
    ("curl -o x 2>/dev/null u", [("curl", "-o", "x", "u")]),
    ("cmd > f a | b", [("cmd", "a"), ("b",)]),
    ("a && b > f c", [("a",), ("b", "c")]),
    ("cat <<EOF a\nx\nEOF", [("cat", "a")]),
    ("cat <<EOF > f a\nx\nEOF", [("cat", "a")]),
    # The words after a redirect that tree-sitter misread stay lost, and the commands are marked (see test_structure_may_be_wrong).
    ("python - <<EOF 2>&1 | tail -5\nx\nEOF", [("python", "-")]),
    # The reserved word time and its -p start a pipeline and are no words of its first command.
    ("time curl u", [("curl", "u")]),
    ("time (a && b)", [("a",), ("b",)]),
    ("time -p (a)", [("a",)]),
    ("x && time a; time b", [("x",), ("a",), ("b",)]),
    ("(time a)", [("a",)]),
    ("time python - <<EOF\nx\nEOF", [("python", "-")]),
    ("time > f x", [("x",)]),
    # Guards that time is dropped only as the first word, and -p only after it.
    ("echo time", [("echo", "time")]),
    ("/usr/bin/time curl u", [("/usr/bin/time", "curl", "u")]),
    ("mkdir -p x", [("mkdir", "-p", "x")]),
    # After a pipe or an assignment and in quotes, time is a program.
    ("a | time b", [("a",), ("time", "b")]),
    ("a |& time b", [("a",), ("time", "b")]),
    ("X=1 time b", [("time", "b")]),
    ("'time' b", [("time", "b")]),
    # Wrong, since bash runs nothing for time alone. It stays as the earlier code gave it, see the module docstring.
    ("time", [("time",)]),
    ("time -p", [("time", "-p")]),
    # tree-sitter misreads what time times here, so the words keep time and the commands are marked (see test_structure_may_be_wrong).
    ("time { a; }", [("time", "{", "a"), ("}",)]),
    ("time A=1 b", [("time", "A=1", "b")]),
    ("time a[0]=1 b", [("time", "a[0]=1", "b")]),
    ("pip install \\\n  x", [("pip", "install", "x")]),
]

# (outer text, first word of the runner, inner text, command_substitution_texts_run_by_outer_shell,
#  the words of every outer command, the words of every inner command)
INNER_TEXT_COMMAND_CASES = [
    (
        "bash -c 'echo $(curl u)'",
        "bash",
        "echo $(curl u)",
        frozenset(),
        [("bash", "-c", "echo $(curl u)")],
        [("echo", "$(curl u)"), ("curl", "u")],
    ),
    # The outer shell expands `$B` in the word, so the caller passes every `$(...)` of the text, and a, which the inner shell runs, is lost.
    (
        "bash -c 'echo $(a) '\"$B\"",
        "bash",
        "echo $(a) $B",
        frozenset({"$(a)"}),
        [("bash", "-c", "echo $(a) $B")],
        [("echo", "$(a)", "$B")],
    ),
    # The word that holds the text has no expansion, so the `$(a)` of the next word does not count as run.
    (
        "bash -c 'echo $(a)' \"$(a)\"",
        "bash",
        "echo $(a)",
        frozenset(),
        [("bash", "-c", "echo $(a)", "$(a)"), ("a",)],
        [("echo", "$(a)"), ("a",)],
    ),
]

# (word as written, its value, whether it holds an expansion)
WORD_CASES = [
    ("plain", "plain", False),
    ("'a b'", "a b", False),
    ("''", "", False),
    ("'$A'", "$A", False),
    ('""', "", False),
    ('"a $B c"', "a $B c", True),
    ('"${A}b"', "${A}b", True),
    # In double quotes, \ escapes only $ ` " \ and a line break.
    ('"a \\"b\\" \\$c \\\\ d"', 'a "b" $c \\ d', False),
    ('"a \\`b\\`"', "a `b`", False),
    ('"\\$A"', "$A", False),
    ('"a\\nb"', "a\\nb", False),
    ('"a\\\nb"', "ab", False),
    ('"a\nb"', "a\nb", False),
    # An expansion inside double quotes is kept as written, escapes included.
    ('"$(echo \\"x\\")"', '$(echo \\"x\\")', True),
    ('"é $(a) ü"', "é $(a) ü", True),
    ("$'a\\tb'", "a\\tb", False),
    ("a\"b\"'c'$D", "abc$D", True),
    ('x"$A"', "x$A", True),
    ("'it'\\''s'", "it's", False),
    ("a$", "a$", False),
    ("$A", "$A", True),
    ("${A:-x}", "${A:-x}", True),
    ("$(ls)", "$(ls)", True),
    ("$(echo a\\ b)", "$(echo a\\ b)", True),
    ("`ls`", "`ls`", True),
    ("<(ls)", "<(ls)", True),
    (">(ls)", ">(ls)", True),
    ("$((1+2))", "$((1+2))", True),
    ("a\\ b", "a b", False),
    ("\\$A", "$A", False),
    ("\\;", ";", False),
    ("a\\\\b", "a\\b", False),
    ("~/x", "~/x", False),
    ("*.py", "*.py", False),
    ("{a,b}", "{a,b}", False),
    ("{1..3}", "{1..3}", False),
]


def _parsed_shell_text_of(
    text: str,
    *,
    runner: ShellCommand | None = None,
    first_command_id: int = 0,
    set_arguments_at_start: tuple[str, ...] = (),
    command_substitution_texts_run_by_outer_shell: frozenset[str] = frozenset(),
) -> ParsedShellText:
    """Read a text that gives commands, with a counter of its own."""
    parsed = parse_shell_text(
        text,
        judgment_rule_use_counts=Counter(),
        first_command_id=first_command_id,
        runner=runner,
        set_arguments_at_start=set_arguments_at_start,
        command_substitution_texts_run_by_outer_shell=command_substitution_texts_run_by_outer_shell,
    )
    assert isinstance(parsed, ParsedShellText)
    return parsed


def _command_from_first_word(parsed: ParsedShellText, first_word: str) -> ShellCommand:
    """Find the only command of `parsed` whose first word is `first_word`."""
    (command,) = [c for c in parsed.commands if c.words[:1] == (first_word,)]
    return command


def _inner_parsed_shell_text_of(
    outer: ParsedShellText,
    runner_first_word: str,
    inner_text: str,
    *,
    set_arguments_at_start: tuple[str, ...] = (),
    command_substitution_texts_run_by_outer_shell: frozenset[str] = frozenset(),
) -> ParsedShellText:
    """Read the text that a command of `outer` runs, with ids after those of `outer`."""
    return _parsed_shell_text_of(
        inner_text,
        runner=_command_from_first_word(outer, runner_first_word),
        first_command_id=len(outer.commands),
        set_arguments_at_start=set_arguments_at_start,
        command_substitution_texts_run_by_outer_shell=command_substitution_texts_run_by_outer_shell,
    )


def _structure_of(
    command: ShellCommand, commands: tuple[ShellCommand, ...]
) -> tuple[str, str, list[tuple[list[str], ExitOutcome]], bool]:
    """Give a command's stdout, stderr, run conditions and `succeeded_if_text_exits_zero`, with ids shown as the first words of `commands`."""
    first_word_of_id = {c.id: c.words[0] for c in commands}
    conditions = [
        (
            [first_word_of_id[i] for i in c.deciding_command_ids],
            c.required_outcome_of_deciding_commands,
        )
        for c in command.runs_if
    ]
    return (
        _short_text_from_destination(command.stdout, first_word_of_id),
        _short_text_from_destination(command.stderr, first_word_of_id),
        conditions,
        command.succeeded_if_text_exits_zero,
    )


def _short_text_from_destination(
    destination: OutputDestination, first_word_of_id: dict[int, str]
) -> str:
    """Write a destination in short words, with a pipe named by its reader's first word."""
    match destination:
        case ResultDestination():
            return "result"
        case FileDestination(path, appends):
            return f"{'append' if appends else 'file'} {path}"
        case PipeDestination(reader_id):
            return f"pipe to {first_word_of_id[reader_id]}"
        case CaptureDestination():
            return "capture"
        case DiscardDestination():
            return "discard"


@pytest.mark.parametrize(("text", "expected"), WHOLE_RESULT_CASES)
def test_whole_result(text: str, expected: ParsedShellText | UnreadableShellText):
    assert parse_shell_text(text, judgment_rule_use_counts=Counter()) == expected


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
    parsed = _parsed_shell_text_of(text)
    assert _structure_of(
        _command_from_first_word(parsed, first_word), parsed.commands
    ) == (
        stdout,
        stderr,
        runs_if,
        succeeded_if_text_exits_zero,
    )


@pytest.mark.parametrize(
    (
        "outer_text",
        "runner_first_word",
        "inner_text",
        "set_arguments_at_start",
        "command_substitution_texts_run_by_outer_shell",
        "first_word",
        "stdout",
        "stderr",
        "runs_if",
        "succeeded_if_text_exits_zero",
    ),
    INNER_TEXT_STRUCTURE_CASES,
)
def test_inner_text_structure(
    outer_text: str,
    runner_first_word: str,
    inner_text: str,
    set_arguments_at_start: tuple[str, ...],
    command_substitution_texts_run_by_outer_shell: frozenset[str],
    first_word: str,
    stdout: str,
    stderr: str,
    runs_if: list[tuple[list[str], ExitOutcome]],
    succeeded_if_text_exits_zero: bool,
):
    outer = _parsed_shell_text_of(outer_text)
    inner = _inner_parsed_shell_text_of(
        outer,
        runner_first_word,
        inner_text,
        set_arguments_at_start=set_arguments_at_start,
        command_substitution_texts_run_by_outer_shell=command_substitution_texts_run_by_outer_shell,
    )
    commands = outer.commands + inner.commands
    assert _structure_of(_command_from_first_word(inner, first_word), commands) == (
        stdout,
        stderr,
        runs_if,
        succeeded_if_text_exits_zero,
    )


@pytest.mark.parametrize(("text", "words"), COMMAND_CASES)
def test_commands_found(text: str, words: list[tuple[str, ...]]):
    assert [c.words for c in _parsed_shell_text_of(text).commands] == words


@pytest.mark.parametrize(
    (
        "outer_text",
        "runner_first_word",
        "inner_text",
        "command_substitution_texts_run_by_outer_shell",
        "outer_words",
        "inner_words",
    ),
    INNER_TEXT_COMMAND_CASES,
)
def test_inner_text_commands_found(
    outer_text: str,
    runner_first_word: str,
    inner_text: str,
    command_substitution_texts_run_by_outer_shell: frozenset[str],
    outer_words: list[tuple[str, ...]],
    inner_words: list[tuple[str, ...]],
):
    outer = _parsed_shell_text_of(outer_text)
    inner = _inner_parsed_shell_text_of(
        outer,
        runner_first_word,
        inner_text,
        command_substitution_texts_run_by_outer_shell=command_substitution_texts_run_by_outer_shell,
    )
    assert [c.words for c in outer.commands] == outer_words
    assert [c.words for c in inner.commands] == inner_words


@pytest.mark.parametrize(("word", "value", "has_expansion"), WORD_CASES)
def test_word_value_and_expansion(word: str, value: str, has_expansion: bool):
    # The commands of a `$(...)` in the word come after echo.
    command = _parsed_shell_text_of(f"echo {word}").commands[0]
    assert command.words == ("echo", value)
    assert command.expansion_word_indexes == ((1,) if has_expansion else ())


def test_expansion_word_indexes_name_each_word_that_holds_an_expansion():
    command = _command_from_first_word(
        _parsed_shell_text_of('pip install x "$(cat reqs)" y $PKG'), "pip"
    )
    assert command.expansion_word_indexes == (3, 5)


def test_example_of_the_pipeline_doc():
    parsed = _parsed_shell_text_of(
        "bash fetch.sh > fetch.log 2>&1 || pip install requests"
    )
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
                runs_if=(RunCondition((0,), FAILURE),),
            ),
        ),
        variable_assignments=(),
    )


def test_joined_lines_are_kept_apart_before_a_comment():
    # tree-sitter reads the second line as more arguments of `grep -v grep`.
    parsed = _parsed_shell_text_of(
        "ps aux | grep a | grep -v grep # note\ncurl u 2>/dev/null | tail -1"
    )
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
    use_counts: Counter[str] = Counter()
    parsed = parse_shell_text(text, judgment_rule_use_counts=use_counts)
    assert isinstance(parsed, ParsedShellText)
    assert [c.words[0] for c in parsed.commands] == list(first_words)
    assert not any(c.structure_may_be_wrong for c in parsed.commands)
    assert use_counts == Counter()


def test_lines_joined_after_three_repairs_are_left_joined_marked_and_counted(
    shell_text_joined_after_three_repairs: str,
):
    use_counts: Counter[str] = Counter()
    parsed = parse_shell_text(
        shell_text_joined_after_three_repairs, judgment_rule_use_counts=use_counts
    )
    assert isinstance(parsed, ParsedShellText)
    assert ("f", "j") in [c.words for c in parsed.commands]
    assert all(c.structure_may_be_wrong for c in parsed.commands)
    assert use_counts == Counter(
        {treat_lines_joined_after_three_repairs_as_left_joined.__name__: 1}
    )


def test_lines_joined_after_three_repairs_are_repaired_on_when_the_rule_says_no(
    monkeypatch: pytest.MonkeyPatch, shell_text_joined_after_three_repairs: str
):
    monkeypatch.setattr(
        parse_shell_text_module,
        treat_lines_joined_after_three_repairs_as_left_joined.__name__,
        lambda repair_count, *, use_counts: False,
    )
    parsed = _parsed_shell_text_of(shell_text_joined_after_three_repairs)
    assert all(len(c.words) == 1 for c in parsed.commands)
    assert not any(c.structure_may_be_wrong for c in parsed.commands)


def test_joined_lines_with_non_ascii_words():
    # The positions where `;` goes are byte offsets.
    parsed = _parsed_shell_text_of("echo 한글 | b | c\nd é | e")
    assert [c.words for c in parsed.commands] == [
        ("echo", "한글"),
        ("b",),
        ("c",),
        ("d", "é"),
        ("e",),
    ]


def test_joined_line_with_heredoc():
    parsed = _parsed_shell_text_of("a | b | c\npython3 - <<EOF\nprint(1)\nEOF")
    assert [c.words for c in parsed.commands] == [
        ("a",),
        ("b",),
        ("c",),
        ("python3", "-"),
    ]
    assert [c.stdin_text for c in parsed.commands] == [None, None, None, "print(1)\n"]


@pytest.mark.parametrize(
    ("text", "field", "first_words"),
    [
        ("for p in a b; do pip install $p; done; c", "in_loop_body", ["pip"]),
        ("while true; do curl u; done", "in_loop_body", ["curl"]),
        ("for ((i=0; i<3; i++)); do curl u; done", "in_loop_body", ["curl"]),
        ("f() { git clone u; }; f", "in_function_body", ["git"]),
        (
            "case $OS in debian) apt-get install -y x ;; esac; b",
            "in_case_branch",
            ["apt-get"],
        ),
    ],
)
def test_flag_is_set_only_where_it_holds(text: str, field: str, first_words: list[str]):
    commands = _parsed_shell_text_of(text).commands
    assert [c.words[0] for c in commands if getattr(c, field)] == first_words


@pytest.mark.parametrize(
    ("outer_text", "inner_text", "field"),
    [
        ("for i in 1 2; do bash -c 'curl u'; done", "curl u", "in_loop_body"),
        ("f() { bash -c 'curl u'; }", "curl u", "in_function_body"),
        ("case x in x) bash -c 'curl u' ;; esac", "curl u", "in_case_branch"),
    ],
)
def test_inner_text_takes_the_flag_of_its_runner(
    outer_text: str, inner_text: str, field: str
):
    outer = _parsed_shell_text_of(outer_text)
    (curl,) = _inner_parsed_shell_text_of(outer, "bash", inner_text).commands
    assert getattr(_command_from_first_word(outer, "bash"), field)
    assert getattr(curl, field)


@pytest.mark.parametrize(
    ("text", "first_word", "stdin_text"),
    [
        ("cat <<EOF\nEOF", "cat", ""),
        ("cat <<< 'curl u'", "cat", "curl u"),
        ("while read l; do X=$(curl $l); done <<EOF\nu\nEOF", "read", "u\n"),
        ("while read l; do X=$(curl $l); done <<EOF\nu\nEOF", "curl", None),
    ],
)
def test_stdin_text(text: str, first_word: str, stdin_text: str | None):
    assert (
        _command_from_first_word(_parsed_shell_text_of(text), first_word).stdin_text
        == stdin_text
    )


@pytest.mark.parametrize(
    ("text", "first_word", "stdin_file_path", "stdin_text"),
    [
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
    command = _command_from_first_word(_parsed_shell_text_of(text), first_word)
    assert (command.stdin_file_path, command.stdin_text) == (
        stdin_file_path,
        stdin_text,
    )


def test_heredoc_with_output_file():
    cat = _command_from_first_word(
        _parsed_shell_text_of("cat <<EOF > fetch.sh\ncurl u\nEOF"), "cat"
    )
    assert (cat.stdout, cat.stdin_text) == (
        FileDestination("fetch.sh", appends=False),
        "curl u\n",
    )


@pytest.mark.parametrize(
    ("text", "flags"),
    [
        ("echo x{1..3} && curl u", [True, True]),
        ("echo {a..c}", [True]),
        ("curl 'u && echo x", [True]),  # an unclosed quote
        ("curl u && echo '{a,b}'", [False, False]),
        ('curl --data=\'{"a":1,"b":2}\' u', [False]),
        ("find . -exec curl {} \\;", [False]),
        # tree-sitter misreads what time times, so every command of the text is marked.
        ("x; time A=1 b", [True, True]),
        ("time a[0]=1 b", [True]),
        ("time { a; }", [True, True]),
        ("time ! a", [True]),
        ("time [[ -f x ]]", [True]),
        ("time (( 1 ))", [True, True]),
        ("time if a; then b; fi", [True, True, True]),
        ("time for x in a; do b; done", [True, True, True]),
        ("x; time a", [False, False]),
        # tree-sitter leaves b beside the timed subshell, which bash rejects.
        ("time (a) > f b", [True, True]),
        ("time (a) > f", [False]),
        # A word after the redirect target of a statement that is no simple command is lost.
        ("x; { a; } > f b", [True, True]),
        ("x; { a; } > f", [False, False]),
        # A `-` or the words after a redirect that tree-sitter misread are lost in a tree with a syntax error.
        ("python - <<EOF `\nx\nEOF", [True, True, True]),
        ("python - <<EOF 2>&1 | tail -5\nx\nEOF", [True]),
    ],
)
def test_structure_may_be_wrong(text: str, flags: list[bool]):
    assert [
        c.structure_may_be_wrong for c in _parsed_shell_text_of(text).commands
    ] == flags


def test_inner_text_is_marked_alone_for_its_own_brace_list():
    outer = _parsed_shell_text_of("a && bash -c 'cp {x,y} d'")
    inner = _inner_parsed_shell_text_of(outer, "bash", "cp {x,y} d")
    assert [c.structure_may_be_wrong for c in outer.commands + inner.commands] == [
        False,
        False,
        True,
    ]


def test_inner_text_takes_the_place_of_its_runner():
    outer = _parsed_shell_text_of("a && sudo bash -lc 'pip install x || true' > log &")
    runner = _command_from_first_word(outer, "sudo")
    pip = _command_from_first_word(
        _inner_parsed_shell_text_of(outer, "sudo", "pip install x || true"), "pip"
    )
    assert pip.id > runner.id
    assert pip.stdout == FileDestination("log", appends=False)
    assert pip.runs_if == runner.runs_if == (RunCondition((0,), SUCCESS),)
    assert not pip.succeeded_if_text_exits_zero  # it is left of || and started with &


def test_runner_gives_its_scope():
    runner = ShellCommand(
        id=4,
        words=("bash", "-e", "fetch.sh"),
        stdout=FileDestination("fetch.log", appends=False),
        stderr=DiscardDestination(),
        stdin_text="x\n",
        stdin_file_path="in",
        runs_if=(RunCondition((3,), SUCCESS),),
        succeeded_if_text_exits_zero=True,
        structure_may_be_wrong=True,
    )
    parsed = _parsed_shell_text_of(
        "curl -sS u 2>&1\nwget v\nls",
        runner=runner,
        first_command_id=5,
        set_arguments_at_start=("-e",),
    )
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
    assert (curl.stdin_text, curl.stdin_file_path) == (None, None)
    assert all(c.structure_may_be_wrong for c in parsed.commands)
    # bash -e makes every plain statement decide the exit code.
    assert [c.succeeded_if_text_exits_zero for c in parsed.commands] == [
        True,
        True,
        True,
    ]


def test_runner_and_set_arguments_give_the_commands_their_conditions_and_destination():
    runner = ShellCommand(
        4,
        ("bash", "-e", "fetch.sh"),
        stdout=FileDestination("fetch.log", False),
        runs_if=(RunCondition((3,), SUCCESS),),
    )
    parsed = _parsed_shell_text_of(
        "curl a; curl b",
        runner=runner,
        first_command_id=5,
        set_arguments_at_start=("-e",),
    )
    assert parsed == ParsedShellText(
        (
            ShellCommand(
                5,
                ("curl", "a"),
                stdout=FileDestination("fetch.log", False),
                runs_if=(RunCondition((3,), SUCCESS),),
            ),
            ShellCommand(
                6,
                ("curl", "b"),
                stdout=FileDestination("fetch.log", False),
                runs_if=(RunCondition((3,), SUCCESS), RunCondition((5,), SUCCESS)),
            ),
        ),
        (),
    )


def test_pipe_reader_is_an_id_from_first_command_id():
    parsed = _parsed_shell_text_of("a | b", first_command_id=7)
    assert [c.id for c in parsed.commands] == [7, 8]
    assert parsed.commands[0].stdout == PipeDestination(8)


def test_exec_redirect_from_first_command_id_sends_later_output_to_its_file():
    # The command of exec is found by its id, which starts at first_command_id.
    parsed = _parsed_shell_text_of("exec > log; curl u", first_command_id=5)
    assert parsed == ParsedShellText(
        (
            ShellCommand(5, ("exec",), stdout=FileDestination("log", False)),
            ShellCommand(
                6,
                ("curl", "u"),
                stdout=FileDestination("log", False),
                succeeded_if_text_exits_zero=True,
            ),
        ),
        (),
    )


def test_variable_assignment_ids_count_from_first_command_id():
    parsed = _parsed_shell_text_of(
        "U=x; a; for p in A B; do b; done", first_command_id=5
    )
    assert parsed.variable_assignments == (
        VariableAssignment("U", "x", 5, None),
        VariableAssignment("p", "A", 6, 7),
        VariableAssignment("p", "B", 6, 7),
    )


def test_command_substitution_run_by_outer_shell_is_not_added_again():
    outer = _parsed_shell_text_of('bash -c "echo $(curl u)"')
    inner = _inner_parsed_shell_text_of(
        outer,
        "bash",
        "echo $(curl u)",
        command_substitution_texts_run_by_outer_shell=frozenset({"$(curl u)"}),
    )
    assert inner == ParsedShellText(
        (
            ShellCommand(
                2,
                ("echo", "$(curl u)"),
                expansion_word_indexes=(1,),
                succeeded_if_text_exits_zero=True,
            ),
        ),
        (),
    )


def test_command_substitutions_run_by_outer_shells_add_up_over_two_inner_texts():
    outer = _parsed_shell_text_of("bash -c \"bash -c 'echo $(curl u)'\"")
    assert [c.words for c in outer.commands] == [
        ("bash", "-c", "bash -c 'echo $(curl u)'"),
        ("curl", "u"),
    ]
    run_by_first_shell = command_substitution_texts_of("bash -c 'echo $(curl u)'")
    second = _inner_parsed_shell_text_of(
        outer,
        "bash",
        "bash -c 'echo $(curl u)'",
        command_substitution_texts_run_by_outer_shell=run_by_first_shell,
    )
    (second_bash,) = second.commands
    # The text of the second bash is in single quotes, so its shell runs no `$(...)` of it, and the set of the first shell carries on.
    assert second_bash.expansion_word_indexes == ()
    third = _parsed_shell_text_of(
        "echo $(curl u)",
        runner=second_bash,
        first_command_id=3,
        command_substitution_texts_run_by_outer_shell=run_by_first_shell,
    )
    assert [c.words for c in third.commands] == [("echo", "$(curl u)")]


@pytest.mark.parametrize(
    ("text", "command_substitution_texts"),
    [
        ("echo $(curl u) `ls`", {"$(curl u)", "`ls`"}),
        # The outer shell runs a `$(...)` in single quotes of the text, since the text sits in its double quotes.
        ("bash -c 'echo $(curl u)'", {"$(curl u)"}),
        # A `$(...)` in double quotes of the text is found, also between single quotes there.
        ("echo \"x '$(a)'\"", {"$(a)"}),
        ("echo 'a \"b $(c)\"'", {"$(c)"}),
        ("echo $(a $(b))", {"$(a $(b))"}),
        # tree-sitter puts the space before the backticks into their node, and the text comes without it.
        ('echo "$(a) `b`"', {"$(a)", "`b`"}),
        # A single-quoted string inside a `$(...)` is not searched, since the outer shell ran the whole `$(...)`.
        ("echo $(bash -c 'echo $(a)')", {"$(bash -c 'echo $(a)')"}),
        ("echo a", set()),
    ],
)
def test_command_substitution_texts_are_the_outermost_ones_as_written(
    text: str, command_substitution_texts: set[str]
):
    assert command_substitution_texts_of(text) == command_substitution_texts


@pytest.mark.parametrize("text", ['echo "$(a) `ls`"', 'echo "$(a)  $(b)"'])
def test_command_substitution_after_another_in_double_quotes_is_not_added_again(
    text: str,
):
    parsed = _parsed_shell_text_of(
        text,
        command_substitution_texts_run_by_outer_shell=command_substitution_texts_of(
            text
        ),
    )
    assert [c.words[0] for c in parsed.commands] == ["echo"]


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
    ],
)
def test_variable_assignments(
    text: str, assignments: list[tuple[str, str | None, int, int | None]]
):
    expected = tuple(VariableAssignment(*a) for a in assignments)
    assert _parsed_shell_text_of(text).variable_assignments == expected
