"""Tests for expanded_tool_call/_expand_program_invocations.py, on a made-up program catalog whose rows the cases name, so that a case does not change when the real catalog gains rows."""

from collections import Counter
from pathlib import Path
from typing import NamedTuple

import pytest

from tb_internet_use.expanded_tool_call import _expand_program_invocations
from tb_internet_use.expanded_tool_call._expand_program_invocations import (
    expand_program_invocations,
)
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_word_with_expansion_as_one_argument,
)
from tb_internet_use.expanded_tool_call.model import (
    ProgramBehavior,
    ProgramInvocation,
    ProgramOption,
    ProgramWordRole,
    UnknownExitsWithExitCodeOfNextProgram,
    UnknownProgramBehavior,
    UnknownProgramInvocation,
    UnknownProgramWordRole,
)
from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    BLANK_PROGRAM_BEHAVIOR_CELLS,
    EXPANDED_TOOL_CALL_CATALOGS_DIR,
    PROGRAM_BEHAVIORS_CSV,
    PROGRAM_OPTION_BEHAVIORS_CSV,
    ExpandedToolCallKnowledge,
)
from tb_internet_use.tool_call.model import ShellCommand

UNKNOWN_ROLE = UnknownProgramWordRole()
UNKNOWN_EXITS_WITH_EXIT_CODE_OF_NEXT_PROGRAM = UnknownExitsWithExitCodeOfNextProgram()
EXPANSION_RULE_NAME = treat_word_with_expansion_as_one_argument.__name__

_RUNS_NEXT_PROGRAM = {
    "argument_role": "program",
    "options_end_at_first_argument": "yes",
    "exits_with_exit_code_of_next_program": "yes",
}
_TAKES_OTHER_VALUE = {"takes_value": "yes", "value_role": "other"}
# The cells of a row whose page says neither whether one-letter options join nor whether options end at the first argument.
_READING_NOT_KNOWN = {
    "options_end_at_first_argument": "",
    "takes_one_letter_options_joined": "",
}
# Made-up rows, each named by the program and the cells that differ from the defaults of `conftest.py`. mytool has no row.
PROGRAM_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {"program_name": "sudo", **_RUNS_NEXT_PROGRAM, "skips_assignment_words": "yes"},
    {"program_name": "env", **_RUNS_NEXT_PROGRAM, "skips_assignment_words": "yes"},
    {
        "program_name": "timeout",
        **_RUNS_NEXT_PROGRAM,
        "first_argument_role": "other",
        "exits_with_exit_code_of_next_program": "",
    },
    {
        "program_name": "xargs",
        **_RUNS_NEXT_PROGRAM,
        "gives_arguments_at_run_time": "yes",
        "exits_with_exit_code_of_next_program": "no",
    },
    {"program_name": "command", **_RUNS_NEXT_PROGRAM},
    {
        "program_name": "find",
        "argument_role": "",
        "takes_one_letter_options_joined": "no",
        "exits_with_exit_code_of_next_program": "",
    },
    {
        "program_name": "chmod",
        "argument_role": "changed_file",
        "first_argument_role": "other",
    },
    {
        "program_name": "bash",
        "first_argument_role": "run_file",
        "stdin_role": "run_text",
        "options_end_at_first_argument": "yes",
    },
    {
        "program_name": "python",
        "first_argument_role": "run_file",
        "options_end_at_first_argument": "yes",
        "name_may_end_with_version": "yes",
    },
    {"program_name": "pip", "name_may_end_with_version": "yes"},
    {
        "program_name": "pip",
        "subcommand": "install",
        "name_may_end_with_version": "yes",
    },
    {"program_name": "curl"},
    {
        "program_name": "sed",
        "argument_role": "read_file",
        "first_argument_role": "pattern",
    },
    {"program_name": "tee", "argument_role": "written_file"},
    {"program_name": "tar", "first_argument_role": "option_cluster"},
    {
        "program_name": "grep",
        "argument_role": "read_file",
        "first_argument_role": "pattern",
    },
    {"program_name": "cat", "argument_role": "read_file"},
    {
        "program_name": "cp",
        "argument_role": "copy_source",
        "last_argument_role": "copy_destination",
    },
    {"program_name": "tail", "argument_role": "read_file"},
    {"program_name": "git", **_READING_NOT_KNOWN},
    {"program_name": "git", "subcommand": "clone"},
    {"program_name": "echo", **_READING_NOT_KNOWN},
    {"program_name": "printf", **_READING_NOT_KNOWN},
    {"program_name": "plusprog", **_READING_NOT_KNOWN},
    {
        "program_name": "node",
        "first_argument_role": "run_file",
        "options_end_at_first_argument": "yes",
    },
    {"program_name": "prog", "argument_role": "read_file"},
    {"program_name": "late"},
]
# Made-up rows, each named by the program, the option and the cells that differ from the defaults of `conftest.py`.
PROGRAM_OPTION_BEHAVIOR_ROWS: list[dict[str, str]] = [
    {"program_name": "sudo", "option_name": "-u", **_TAKES_OTHER_VALUE},
    {"program_name": "timeout", "option_name": "--signal", **_TAKES_OTHER_VALUE},
    {"program_name": "xargs", "option_name": "-I", **_TAKES_OTHER_VALUE},
    {"program_name": "xargs", "option_name": "-n", **_TAKES_OTHER_VALUE},
    {
        "program_name": "command",
        "option_name": "-v",
        "argument_role_with_option": "other",
        "exits_with_exit_code_of_next_program_with_option": "no",
    },
    {
        "program_name": "find",
        "option_name": "-name",
        "takes_value": "yes",
        "value_role": "pattern",
    },
    {"program_name": "find", "option_name": "-print"},
    # A made-up option that takes a value attached with `=` and starts a next program up to `;`.
    {
        "program_name": "find",
        "option_name": "--each",
        **_TAKES_OTHER_VALUE,
        "argument_role_with_option": "program",
        "gives_arguments_at_run_time": "yes",
        "next_program_end_words": ";",
    },
    *(
        {
            "program_name": "find",
            "option_name": option_name,
            "argument_role_with_option": "program",
            "gives_arguments_at_run_time": "yes",
            "exits_with_exit_code_of_next_program_with_option": "no",
            "next_program_end_words": "; +",
        }
        for option_name in ("-exec", "-execdir")
    ),
    {
        "program_name": "bash",
        "option_name": "-c",
        "first_argument_role_with_option": "run_text",
    },
    {
        "program_name": "bash",
        "option_name": "-s",
        "first_argument_role_with_option": "same",
    },
    {
        "program_name": "bash",
        "option_name": "-n",
        "first_argument_role_with_option": "",
    },
    {"program_name": "bash", "option_name": "-e"},
    {"program_name": "bash", "option_name": "-u"},
    {"program_name": "bash", "option_name": "-o", **_TAKES_OTHER_VALUE},
    {"program_name": "bash", "option_name": "+o", **_TAKES_OTHER_VALUE},
    {
        "program_name": "python",
        "option_name": "-c",
        "first_argument_role_with_option": "run_text",
    },
    {
        "program_name": "python",
        "option_name": "-m",
        "first_argument_role_with_option": "program",
        "exits_with_exit_code_of_next_program_with_option": "",
    },
    {"program_name": "python", "option_name": "-u"},
    {"program_name": "pip", "option_name": "-q"},
    *({"program_name": "curl", "option_name": f"-{letter}"} for letter in "fsSL"),
    *(
        {
            "program_name": "curl",
            "option_name": option_name,
            "takes_value": "yes",
            "value_role": "written_file",
        }
        for option_name in ("-o", "--output")
    ),
    {
        "program_name": "curl",
        "option_name": "-O",
        "argument_role_with_option": "written_file_source",
    },
    {"program_name": "curl", "option_name": "-H", **_TAKES_OTHER_VALUE},
    {
        "program_name": "sed",
        "option_name": "-i",
        "argument_role_with_option": "changed_file",
    },
    {
        "program_name": "sed",
        "option_name": "-e",
        "takes_value": "yes",
        "value_role": "pattern",
        "first_argument_role_with_option": "same",
    },
    {
        "program_name": "tee",
        "option_name": "-a",
        "argument_role_with_option": "appended_file",
    },
    {
        "program_name": "tar",
        "option_name": "-f",
        "takes_value": "yes",
        "value_role": "used_file",
    },
    {"program_name": "tar", "option_name": "-x"},
    {"program_name": "tar", "option_name": "-z"},
    {
        "program_name": "tar",
        "option_name": "-c",
        "changed_option_name": "-f",
        "changed_option_value_role": "written_file",
    },
    {
        "program_name": "tar",
        "option_name": "-t",
        "changed_option_name": "-f",
        "changed_option_value_role": "read_file",
    },
    {
        "program_name": "grep",
        "option_name": "-e",
        "takes_value": "yes",
        "value_role": "pattern",
        "first_argument_role_with_option": "same",
    },
    {"program_name": "grep", "option_name": "-r"},
    {"program_name": "grep", "option_name": "--color"},
    {"program_name": "tail", "option_name": "-n", **_TAKES_OTHER_VALUE},
    {"program_name": "git", "option_name": "-C", **_TAKES_OTHER_VALUE},
    {"program_name": "echo", "option_name": "-n"},
    {"program_name": "echo", "option_name": "-e"},
    {"program_name": "plusprog", "option_name": "+o"},
    {
        "program_name": "git",
        "subcommand": "clone",
        "option_name": "--depth",
        **_TAKES_OTHER_VALUE,
    },
    {
        "program_name": "node",
        "option_name": "-pe",
        "takes_value": "yes",
        "value_role": "run_text",
    },
    {"program_name": "node", "option_name": "-p", **_TAKES_OTHER_VALUE},
    {"program_name": "node", "option_name": "-e", **_TAKES_OTHER_VALUE},
    # Two options of prog that give the arguments different roles, and two that give its exit code different answers.
    {
        "program_name": "prog",
        "option_name": "-r",
        "argument_role_with_option": "used_file",
    },
    {
        "program_name": "prog",
        "option_name": "-w",
        "argument_role_with_option": "written_file",
    },
    {
        "program_name": "prog",
        "option_name": "-y",
        "exits_with_exit_code_of_next_program_with_option": "yes",
    },
    {
        "program_name": "prog",
        "option_name": "-k",
        "exits_with_exit_code_of_next_program_with_option": "no",
    },
    # Options of late that make the arguments or the first argument programs although they come after them.
    {
        "program_name": "late",
        "option_name": "-m",
        "argument_role_with_option": "program",
    },
    {
        "program_name": "late",
        "option_name": "-p",
        "first_argument_role_with_option": "program",
    },
]


def _program_invocation(
    program_name: str,
    *,
    subcommand_words: tuple[str, ...] = (),
    options: tuple[ProgramOption, ...] = (),
    arguments: tuple[str, ...] = (),
    gets_more_arguments_at_run_time: bool = False,
    unread_words: tuple[str, ...] = (),
    exits_with_exit_code_of_next_program: bool
    | UnknownExitsWithExitCodeOfNextProgram = False,
) -> ProgramInvocation:
    return ProgramInvocation(
        program_name,
        subcommand_words,
        options,
        arguments,
        gets_more_arguments_at_run_time,
        unread_words,
        exits_with_exit_code_of_next_program,
    )


def _option(name: str, value: str | None = None) -> ProgramOption:
    return ProgramOption(name, value)


# The sudo, bash and pip that several cases expect.
_SUDO = _program_invocation("sudo", exits_with_exit_code_of_next_program=True)
_PIP_INSTALL = _program_invocation(
    "pip", subcommand_words=("install",), options=(_option("-q"),), arguments=("x",)
)
_CURL_U = _program_invocation("curl", arguments=("u",))

# (words, 0-based indexes of the words with an expansion, the programs they run). Made-up commands that the reading was designed for, cases of the tests of the old code and cases that showed a bug in an earlier version.
INVOCATION_CASES = [
    # The made-up commands that the reading was designed for.
    (
        "sudo bash -c 'curl u'",
        ("sudo", "bash", "-c", "curl u"),
        (),
        (
            _SUDO,
            _program_invocation(
                "bash", options=(_option("-c"),), arguments=("curl u",)
            ),
        ),
    ),
    (
        "mytool run x",
        ("mytool", "run", "x"),
        (),
        (UnknownProgramInvocation("mytool", ("run", "x")),),
    ),
    ("./a.out", ("./a.out",), (), (UnknownProgramInvocation("a.out", ()),)),
    (
        "xargs curl -sO",
        ("xargs", "curl", "-sO"),
        (),
        (
            _program_invocation("xargs"),
            _program_invocation(
                "curl",
                options=(_option("-s"), _option("-O")),
                gets_more_arguments_at_run_time=True,
            ),
        ),
    ),
    (
        "xargs mytool",
        ("xargs", "mytool"),
        (),
        (_program_invocation("xargs"), UnknownProgramInvocation("mytool", ())),
    ),
    (
        "curl --foo x u",
        ("curl", "--foo", "x", "u"),
        (),
        (_program_invocation("curl", unread_words=("--foo", "x", "u")),),
    ),
    (
        "sudo pip3 install -q x",
        ("sudo", "pip3", "install", "-q", "x"),
        (),
        (_SUDO, _PIP_INSTALL),
    ),
    (
        "sudo python3 -m pip install -q x",
        ("sudo", "python3", "-m", "pip", "install", "-q", "x"),
        (),
        (
            _SUDO,
            _program_invocation(
                "python",
                options=(_option("-m"),),
                exits_with_exit_code_of_next_program=UNKNOWN_EXITS_WITH_EXIT_CODE_OF_NEXT_PROGRAM,
            ),
            _PIP_INSTALL,
        ),
    ),
    (
        "curl -fsSLoout u",
        ("curl", "-fsSLoout", "u"),
        (),
        (
            _program_invocation(
                "curl",
                options=(
                    _option("-f"),
                    _option("-s"),
                    _option("-S"),
                    _option("-L"),
                    _option("-o", "out"),
                ),
                arguments=("u",),
            ),
        ),
    ),
    (
        "python get.py -o x",
        ("python", "get.py", "-o", "x"),
        (),
        (_program_invocation("python", arguments=("get.py", "-o", "x")),),
    ),
    (
        "find . -name '*.sh' -exec chmod +x {} ; -print",
        ("find", ".", "-name", "*.sh", "-exec", "chmod", "+x", "{}", ";", "-print"),
        (),
        (
            _program_invocation(
                "find",
                options=(_option("-name", "*.sh"), _option("-exec"), _option("-print")),
                arguments=(".", ";"),
            ),
            _program_invocation(
                "chmod", arguments=("+x", "{}"), gets_more_arguments_at_run_time=True
            ),
        ),
    ),
    (
        "env A=1 curl u",
        ("env", "A=1", "curl", "u"),
        (),
        (
            _program_invocation(
                "env", arguments=("A=1",), exits_with_exit_code_of_next_program=True
            ),
            _CURL_U,
        ),
    ),
    (
        "git -C dir clone u",
        ("git", "-C", "dir", "clone", "u"),
        (),
        (
            _program_invocation(
                "git", options=(_option("-C", "dir"),), arguments=("clone", "u")
            ),
        ),
    ),
    (
        "find . -maxdepth 2",
        ("find", ".", "-maxdepth", "2"),
        (),
        (
            _program_invocation(
                "find",
                arguments=(".",),
                unread_words=("-maxdepth", "2"),
                exits_with_exit_code_of_next_program=UNKNOWN_EXITS_WITH_EXIT_CODE_OF_NEXT_PROGRAM,
            ),
        ),
    ),
    (
        "curl $OPTS u",
        ("curl", "$OPTS", "u"),
        (1,),
        (_program_invocation("curl", arguments=("$OPTS", "u")),),
    ),
    # The cases of the old tests of the programs past wrappers, of shell texts and of option values.
    (
        "sudo -u root timeout --signal KILL 30 env A=1 curl u",
        (
            "sudo",
            "-u",
            "root",
            "timeout",
            "--signal",
            "KILL",
            "30",
            "env",
            "A=1",
            "curl",
            "u",
        ),
        (),
        (
            _program_invocation(
                "sudo",
                options=(_option("-u", "root"),),
                exits_with_exit_code_of_next_program=True,
            ),
            _program_invocation(
                "timeout",
                options=(_option("--signal", "KILL"),),
                arguments=("30",),
                exits_with_exit_code_of_next_program=UNKNOWN_EXITS_WITH_EXIT_CODE_OF_NEXT_PROGRAM,
            ),
            _program_invocation(
                "env", arguments=("A=1",), exits_with_exit_code_of_next_program=True
            ),
            _CURL_U,
        ),
    ),
    ("/usr/bin/sudo curl u", ("/usr/bin/sudo", "curl", "u"), (), (_SUDO, _CURL_U)),
    # command -v only looks curl up, so curl is no next program.
    (
        "command -v curl",
        ("command", "-v", "curl"),
        (),
        (
            _program_invocation(
                "command", options=(_option("-v"),), arguments=("curl",)
            ),
        ),
    ),
    # 3x=1 is no `NAME=value` word, since a name does not start with a digit, so env runs it.
    (
        "env 3x=1 curl u",
        ("env", "3x=1", "curl", "u"),
        (),
        (
            _program_invocation("env", exits_with_exit_code_of_next_program=True),
            UnknownProgramInvocation("3x=1", ("curl", "u")),
        ),
    ),
    (
        "/usr/bin/env python3.11 x.py",
        ("/usr/bin/env", "python3.11", "x.py"),
        (),
        (
            _program_invocation("env", exits_with_exit_code_of_next_program=True),
            _program_invocation("python", arguments=("x.py",)),
        ),
    ),
    (
        "python -u -m pip install -q x",
        ("python", "-u", "-m", "pip", "install", "-q", "x"),
        (),
        (
            _program_invocation(
                "python",
                options=(_option("-u"), _option("-m")),
                exits_with_exit_code_of_next_program=UNKNOWN_EXITS_WITH_EXIT_CODE_OF_NEXT_PROGRAM,
            ),
            _PIP_INSTALL,
        ),
    ),
    (
        "find . -execdir curl {} + -print",
        ("find", ".", "-execdir", "curl", "{}", "+", "-print"),
        (),
        (
            _program_invocation(
                "find",
                options=(_option("-execdir"), _option("-print")),
                arguments=(".", "+"),
            ),
            _program_invocation(
                "curl", arguments=("{}",), gets_more_arguments_at_run_time=True
            ),
        ),
    ),
    (
        "xargs -n1 -I {} curl -s {}",
        ("xargs", "-n1", "-I", "{}", "curl", "-s", "{}"),
        (),
        (
            _program_invocation(
                "xargs", options=(_option("-n", "1"), _option("-I", "{}"))
            ),
            _program_invocation(
                "curl",
                options=(_option("-s"),),
                arguments=("{}",),
                gets_more_arguments_at_run_time=True,
            ),
        ),
    ),
    # The arguments that xargs gives sudo go on to curl, whose words reach the end of the command.
    (
        "xargs sudo curl",
        ("xargs", "sudo", "curl"),
        (),
        (
            _program_invocation("xargs"),
            _program_invocation(
                "sudo",
                exits_with_exit_code_of_next_program=True,
                gets_more_arguments_at_run_time=True,
            ),
            _program_invocation("curl", gets_more_arguments_at_run_time=True),
        ),
    ),
    # sudo runs no next program here, so it does not end with the exit code of one.
    ("sudo", ("sudo",), (), (_program_invocation("sudo"),)),
    # The words of sudo are not all read, so whether it runs a next program is not known and its row answers.
    (
        "sudo -Z curl",
        ("sudo", "-Z", "curl"),
        (),
        (
            _program_invocation(
                "sudo",
                unread_words=("-Z", "curl"),
                exits_with_exit_code_of_next_program=True,
            ),
        ),
    ),
    # -c is an argument of fetch.sh, since the options of bash end at its first argument.
    (
        "bash fetch.sh -c a",
        ("bash", "fetch.sh", "-c", "a"),
        (),
        (_program_invocation("bash", arguments=("fetch.sh", "-c", "a")),),
    ),
    (
        "bash -euo pipefail -c a",
        ("bash", "-euo", "pipefail", "-c", "a"),
        (),
        (
            _program_invocation(
                "bash",
                options=(
                    _option("-e"),
                    _option("-u"),
                    _option("-o", "pipefail"),
                    _option("-c"),
                ),
                arguments=("a",),
            ),
        ),
    ),
    (
        "curl -H a:b u -- -x",
        ("curl", "-H", "a:b", "u", "--", "-x"),
        (),
        (
            _program_invocation(
                "curl", options=(_option("-H", "a:b"),), arguments=("u", "-x")
            ),
        ),
    ),
    (
        "--output=out",
        ("curl", "--output=out", "u"),
        (),
        (
            _program_invocation(
                "curl", options=(_option("--output", "out"),), arguments=("u",)
            ),
        ),
    ),
    (
        "cat - log",
        ("cat", "-", "log"),
        (),
        (_program_invocation("cat", arguments=("-", "log")),),
    ),
    (
        "tail -n 5 log",
        ("tail", "-n", "5", "log"),
        (),
        (
            _program_invocation(
                "tail", options=(_option("-n", "5"),), arguments=("log",)
            ),
        ),
    ),
    # The letters of -$n come from a variable when the command runs, so it is one argument.
    (
        "tail -$n log",
        ("tail", "-$n", "log"),
        (1,),
        (_program_invocation("tail", arguments=("-$n", "log")),),
    ),
    # -pe has a row of its own, so its letters are not read apart.
    (
        "node -pe code",
        ("node", "-pe", "code"),
        (),
        (_program_invocation("node", options=(_option("-pe", "code"),)),),
    ),
    (
        "python -uc code x",
        ("python", "-uc", "code", "x"),
        (),
        (
            _program_invocation(
                "python",
                options=(_option("-u"), _option("-c")),
                arguments=("code", "x"),
            ),
        ),
    ),
    (
        "tar xzf a.tgz",
        ("tar", "xzf", "a.tgz"),
        (),
        (
            _program_invocation(
                "tar", options=(_option("-x"), _option("-z"), _option("-f", "a.tgz"))
            ),
        ),
    ),
    ("$CMD x", ("$CMD", "x"), (0,), (UnknownProgramInvocation("$CMD", ("x",)),)),
    ("no words", (), (), ()),
    # Cases that showed a bug in an earlier version of the reading.
    (
        "sudo env timeout 5 curl u",
        ("sudo", "env", "timeout", "5", "curl", "u"),
        (),
        (
            _SUDO,
            _program_invocation("env", exits_with_exit_code_of_next_program=True),
            _program_invocation(
                "timeout",
                arguments=("5",),
                exits_with_exit_code_of_next_program=UNKNOWN_EXITS_WITH_EXIT_CODE_OF_NEXT_PROGRAM,
            ),
            _CURL_U,
        ),
    ),
    # -r has a row and -n has none, so the word and the words after it are unread.
    (
        "grep -rn x .",
        ("grep", "-rn", "x", "."),
        (),
        (_program_invocation("grep", unread_words=("-rn", "x", ".")),),
    ),
    (
        "tail -5 f",
        ("tail", "-5", "f"),
        (),
        (_program_invocation("tail", unread_words=("-5", "f")),),
    ),
    (
        "sed -n 1p f",
        ("sed", "-n", "1p", "f"),
        (),
        (_program_invocation("sed", unread_words=("-n", "1p", "f")),),
    ),
    # cat skips no assignment words, so `A=1` is a file argument like any other.
    (
        "cat A=1 f",
        ("cat", "A=1", "f"),
        (),
        (_program_invocation("cat", arguments=("A=1", "f")),),
    ),
    # The row of --depth is one of the subcommand clone, so git without it has no row for --depth.
    (
        "git clone --depth 1 u",
        ("git", "clone", "--depth", "1", "u"),
        (),
        (
            _program_invocation(
                "git",
                subcommand_words=("clone",),
                options=(_option("--depth", "1"),),
                arguments=("u",),
            ),
        ),
    ),
    (
        "git --depth 1 u",
        ("git", "--depth", "1", "u"),
        (),
        (_program_invocation("git", unread_words=("--depth", "1", "u")),),
    ),
    # echo, printf, plusprog and git leave blank whether one-letter options join and whether options end at the first argument.
    # A command without a word that starts with - is read fully.
    (
        "echo hello",
        ("echo", "hello"),
        (),
        (_program_invocation("echo", arguments=("hello",)),),
    ),
    (
        "printf '%s\\n' a",
        ("printf", "%s\\n", "a"),
        (),
        (_program_invocation("printf", arguments=("%s\\n", "a")),),
    ),
    # A word with its own row before the first argument is read as today.
    (
        "echo -n hello",
        ("echo", "-n", "hello"),
        (),
        (_program_invocation("echo", options=(_option("-n"),), arguments=("hello",)),),
    ),
    (
        "git -C dir status",
        ("git", "-C", "dir", "status"),
        (),
        (
            _program_invocation(
                "git", options=(_option("-C", "dir"),), arguments=("status",)
            ),
        ),
    ),
    # After the first argument a word that starts with - may be an option or an argument, so it stays unread, its own row and `--` included.
    (
        "echo hello -n",
        ("echo", "hello", "-n"),
        (),
        (_program_invocation("echo", arguments=("hello",), unread_words=("-n",)),),
    ),
    (
        "echo a -- b",
        ("echo", "a", "--", "b"),
        (),
        (_program_invocation("echo", arguments=("a",), unread_words=("--", "b")),),
    ),
    # A word that starts with + is an argument of a program without an option that starts with +, wherever it stands.
    (
        "echo a +x",
        ("echo", "a", "+x"),
        (),
        (_program_invocation("echo", arguments=("a", "+x")),),
    ),
    # plusprog has the option +o, so after the first argument +o may be that option or an argument.
    (
        "plusprog a +o b",
        ("plusprog", "a", "+o", "b"),
        (),
        (_program_invocation("plusprog", arguments=("a",), unread_words=("+o", "b")),),
    ),
    (
        "plusprog +o b",
        ("plusprog", "+o", "b"),
        (),
        (_program_invocation("plusprog", options=(_option("+o"),), arguments=("b",)),),
    ),
    # -n and -e have rows, but whether -ne holds both is not known.
    (
        "echo -ne a",
        ("echo", "-ne", "a"),
        (),
        (_program_invocation("echo", unread_words=("-ne", "a")),),
    ),
    # --color takes no value, but the value written after `=` cannot be an argument, so it stays the value of the option. This pins a choice that the facts of the catalog do not settle.
    (
        "grep --color=auto x f",
        ("grep", "--color=auto", "x", "f"),
        (),
        (
            _program_invocation(
                "grep", options=(_option("--color", "auto"),), arguments=("x", "f")
            ),
        ),
    ),
    (
        "bash -c $CMD",
        ("bash", "-c", "$CMD"),
        (2,),
        (_program_invocation("bash", options=(_option("-c"),), arguments=("$CMD",)),),
    ),
    # The words after the text of -c are arguments of that text, not options of bash.
    (
        "bash -c text name a",
        ("bash", "-c", "text", "name", "-a"),
        (),
        (
            _program_invocation(
                "bash", options=(_option("-c"),), arguments=("text", "name", "-a")
            ),
        ),
    ),
    # bash has a row for +o, so +o is an option, while chmod has no option with + and +x is its argument.
    (
        "bash +o posix f.sh",
        ("bash", "+o", "posix", "f.sh"),
        (),
        (
            _program_invocation(
                "bash", options=(_option("+o", "posix"),), arguments=("f.sh",)
            ),
        ),
    ),
    (
        "chmod +x f.sh",
        ("chmod", "+x", "f.sh"),
        (),
        (_program_invocation("chmod", arguments=("+x", "f.sh")),),
    ),
    # An option that takes a value, written last without one, is unread with its word, whether the value would be the next word or in a cluster.
    (
        "curl -o",
        ("curl", "-o"),
        (),
        (_program_invocation("curl", unread_words=("-o",)),),
    ),
    (
        "curl -fo",
        ("curl", "-fo"),
        (),
        (_program_invocation("curl", unread_words=("-fo",)),),
    ),
    ("sed -e", ("sed", "-e"), (), (_program_invocation("sed", unread_words=("-e",)),)),
    ("tar xf", ("tar", "xf"), (), (_program_invocation("tar", unread_words=("xf",)),)),
    # The value of the cluster word is a word with an expansion, which is read as one value.
    (
        "tar xzf $F",
        ("tar", "xzf", "$F"),
        (2,),
        (
            _program_invocation(
                "tar", options=(_option("-x"), _option("-z"), _option("-f", "$F"))
            ),
        ),
    ),
    # The letters of $X are known only when the command runs, so it is unread with the words after it.
    (
        "tar $X a",
        ("tar", "$X", "a"),
        (1,),
        (_program_invocation("tar", unread_words=("$X", "a")),),
    ),
    (
        "sudo $P u",
        ("sudo", "$P", "u"),
        (1,),
        (_SUDO, UnknownProgramInvocation("$P", ("u",))),
    ),
    # The -m after `a` would make `a` the next program, which would own -m, so what `a` is stays unknown.
    (
        "late a -m",
        ("late", "a", "-m"),
        (),
        (_program_invocation("late", unread_words=("a", "-m")),),
    ),
    # The option with its value after `=` starts the next program like -exec does.
    (
        "find . --each=v chmod {} ; -print",
        ("find", ".", "--each=v", "chmod", "{}", ";", "-print"),
        (),
        (
            _program_invocation(
                "find",
                options=(_option("--each", "v"), _option("-print")),
                arguments=(".", ";"),
                exits_with_exit_code_of_next_program=UNKNOWN_EXITS_WITH_EXIT_CODE_OF_NEXT_PROGRAM,
            ),
            _program_invocation(
                "chmod", arguments=("{}",), gets_more_arguments_at_run_time=True
            ),
        ),
    ),
    # Nothing is left of the program word without its folder, so it stays as written.
    ("dir/ x", ("dir/", "x"), (), (UnknownProgramInvocation("dir/", ("x",)),)),
]

# (words, 0-based indexes of the words with an expansion, the role of each word)
ROLE_CASES = [
    # echo leaves blank whether options end at its first argument, so -n after hello has an unknown role and is no option.
    (
        "echo hello -n",
        ("echo", "hello", "-n"),
        (),
        (None, ProgramWordRole.OTHER, UNKNOWN_ROLE),
    ),
    # The -e row says that the first argument is not apart from the others, and the -i row gives the others `CHANGED_FILE`, so f.sh is changed and not a pattern.
    (
        "sed -i -e s/a/b/ f.sh",
        ("sed", "-i", "-e", "s/a/b/", "f.sh"),
        (),
        (None, None, None, ProgramWordRole.PATTERN, ProgramWordRole.CHANGED_FILE),
    ),
    (
        "tee -a log",
        ("tee", "-a", "log"),
        (),
        (None, None, ProgramWordRole.APPENDED_FILE),
    ),
    # The -i row changes the read files of the sed row into changed files and keeps the pattern.
    (
        "sed -i s/a/b/ f g",
        ("sed", "-i", "s/a/b/", "f", "g"),
        (),
        (
            None,
            None,
            ProgramWordRole.PATTERN,
            ProgramWordRole.CHANGED_FILE,
            ProgramWordRole.CHANGED_FILE,
        ),
    ),
    (
        "sed s/a/b/ f",
        ("sed", "s/a/b/", "f"),
        (),
        (None, ProgramWordRole.PATTERN, ProgramWordRole.READ_FILE),
    ),
    (
        "grep -e a -e b log",
        ("grep", "-e", "a", "-e", "b", "log"),
        (),
        (
            None,
            None,
            ProgramWordRole.PATTERN,
            None,
            ProgramWordRole.PATTERN,
            ProgramWordRole.READ_FILE,
        ),
    ),
    (
        "cp a b c",
        ("cp", "a", "b", "c"),
        (),
        (
            None,
            ProgramWordRole.COPY_SOURCE,
            ProgramWordRole.COPY_SOURCE,
            ProgramWordRole.COPY_DESTINATION,
        ),
    ),
    # Two options give the arguments different roles, so their role is unknown.
    ("prog -r -w f", ("prog", "-r", "-w", "f"), (), (None, None, None, UNKNOWN_ROLE)),
    ("prog -r f", ("prog", "-r", "f"), (), (None, None, ProgramWordRole.USED_FILE)),
    # -c and -t name -f with different roles for its value.
    (
        "tar -c -t -f a.tgz",
        ("tar", "-c", "-t", "-f", "a.tgz"),
        (),
        (None, None, None, None, UNKNOWN_ROLE),
    ),
    # -c names -f in `changed_option_name`, so the value of -f is written and not used.
    (
        "tar -cf a.tgz",
        ("tar", "-cf", "a.tgz"),
        (),
        (None, None, ProgramWordRole.WRITTEN_FILE),
    ),
    (
        "tar -f a.tgz",
        ("tar", "-f", "a.tgz"),
        (),
        (None, None, ProgramWordRole.USED_FILE),
    ),
    # The row gives the first argument the role of a cluster even after options with a dash, so src is read as letters and -s has no row.
    (
        "tar -cf a.tgz src",
        ("tar", "-cf", "a.tgz", "src"),
        (),
        (None, None, ProgramWordRole.WRITTEN_FILE, UNKNOWN_ROLE),
    ),
    (
        "tar xzf a.tgz",
        ("tar", "xzf", "a.tgz"),
        (),
        (None, None, ProgramWordRole.USED_FILE),
    ),
    # The value `-` of an option whose row names a file stands for stdout, which the row cannot say.
    (
        "curl -o - u",
        ("curl", "-o", "-", "u"),
        (),
        (None, None, UNKNOWN_ROLE, ProgramWordRole.OTHER),
    ),
    (
        "curl -o out u",
        ("curl", "-o", "out", "u"),
        (),
        (None, None, ProgramWordRole.WRITTEN_FILE, ProgramWordRole.OTHER),
    ),
    (
        "curl -O u",
        ("curl", "-O", "u"),
        (),
        (None, None, ProgramWordRole.WRITTEN_FILE_SOURCE),
    ),
    (
        "sudo bash -c 'curl u'",
        ("sudo", "bash", "-c", "curl u"),
        (),
        (None, None, None, ProgramWordRole.RUN_TEXT),
    ),
    (
        "bash fetch.sh -c a",
        ("bash", "fetch.sh", "-c", "a"),
        (),
        (None, ProgramWordRole.RUN_FILE, ProgramWordRole.OTHER, ProgramWordRole.OTHER),
    ),
    # -s reads the commands from stdin, so x is no file.
    ("bash -s x", ("bash", "-s", "x"), (), (None, None, ProgramWordRole.OTHER)),
    # -n only checks the syntax, and its row leaves the role of the first argument blank.
    ("bash -n fetch.sh", ("bash", "-n", "fetch.sh"), (), (None, None, UNKNOWN_ROLE)),
    (
        "python -c code x",
        ("python", "-c", "code", "x"),
        (),
        (None, None, ProgramWordRole.RUN_TEXT, ProgramWordRole.OTHER),
    ),
    (
        "timeout 30 curl u",
        ("timeout", "30", "curl", "u"),
        (),
        (None, ProgramWordRole.OTHER, None, ProgramWordRole.OTHER),
    ),
    (
        "env A=1 curl u",
        ("env", "A=1", "curl", "u"),
        (),
        (None, ProgramWordRole.OTHER, None, ProgramWordRole.OTHER),
    ),
    (
        "find . -exec chmod +x {} ; -print",
        ("find", ".", "-exec", "chmod", "+x", "{}", ";", "-print"),
        (),
        (
            None,
            UNKNOWN_ROLE,
            None,
            None,
            ProgramWordRole.OTHER,
            ProgramWordRole.CHANGED_FILE,
            ProgramWordRole.OTHER,
            None,
        ),
    ),
    (
        "git -C dir clone u",
        ("git", "-C", "dir", "clone", "u"),
        (),
        (
            None,
            None,
            ProgramWordRole.OTHER,
            ProgramWordRole.OTHER,
            ProgramWordRole.OTHER,
        ),
    ),
    (
        "pip install -q x",
        ("pip", "install", "-q", "x"),
        (),
        (None, None, None, ProgramWordRole.OTHER),
    ),
    (
        "curl -H a:b -- -x",
        ("curl", "-H", "a:b", "--", "-x"),
        (),
        (None, None, ProgramWordRole.OTHER, None, ProgramWordRole.OTHER),
    ),
    # The attached value has no word of its own, so the word keeps the None of an option name.
    (
        "curl --output=out u",
        ("curl", "--output=out", "u"),
        (),
        (None, None, ProgramWordRole.OTHER),
    ),
    (
        "curl --foo x u",
        ("curl", "--foo", "x", "u"),
        (),
        (None, UNKNOWN_ROLE, UNKNOWN_ROLE, UNKNOWN_ROLE),
    ),
    ("mytool run x", ("mytool", "run", "x"), (), (None, UNKNOWN_ROLE, UNKNOWN_ROLE)),
    (
        "curl $OPTS u",
        ("curl", "$OPTS", "u"),
        (1,),
        (None, ProgramWordRole.OTHER, ProgramWordRole.OTHER),
    ),
    # The value `-` of an option whose row names a file stands for stdout, which the row cannot say, in each of its three spellings.
    (
        "curl -o- u",
        ("curl", "-o-", "u"),
        (),
        (None, UNKNOWN_ROLE, ProgramWordRole.OTHER),
    ),
    (
        "curl --output=- u",
        ("curl", "--output=-", "u"),
        (),
        (None, UNKNOWN_ROLE, ProgramWordRole.OTHER),
    ),
    (
        "bash +o posix f.sh",
        ("bash", "+o", "posix", "f.sh"),
        (),
        (None, None, ProgramWordRole.OTHER, ProgramWordRole.RUN_FILE),
    ),
    (
        "chmod +x f.sh",
        ("chmod", "+x", "f.sh"),
        (),
        (None, ProgramWordRole.OTHER, ProgramWordRole.CHANGED_FILE),
    ),
    (
        "cat A=1 f",
        ("cat", "A=1", "f"),
        (),
        (None, ProgramWordRole.READ_FILE, ProgramWordRole.READ_FILE),
    ),
    (
        "bash -c $CMD",
        ("bash", "-c", "$CMD"),
        (2,),
        (None, None, ProgramWordRole.RUN_TEXT),
    ),
    (
        "bash -c text name a",
        ("bash", "-c", "text", "name", "-a"),
        (),
        (
            None,
            None,
            ProgramWordRole.RUN_TEXT,
            ProgramWordRole.OTHER,
            ProgramWordRole.OTHER,
        ),
    ),
    ("curl -fo", ("curl", "-fo"), (), (None, UNKNOWN_ROLE)),
    ("tar xf", ("tar", "xf"), (), (None, UNKNOWN_ROLE)),
    ("tar xzf $F", ("tar", "xzf", "$F"), (2,), (None, None, ProgramWordRole.USED_FILE)),
    ("late a -m", ("late", "a", "-m"), (), (None, UNKNOWN_ROLE, UNKNOWN_ROLE)),
    ("sudo $P u", ("sudo", "$P", "u"), (1,), (None, None, UNKNOWN_ROLE)),
]


class _Expansion(NamedTuple):
    """Result of one `expand_program_invocations` call in a test, with the counts of the door and of the judgment rule."""

    program_invocations: tuple[ProgramInvocation | UnknownProgramInvocation, ...]
    roles: tuple[ProgramWordRole | UnknownProgramWordRole | None, ...]
    program_behaviors: tuple[ProgramBehavior | UnknownProgramBehavior, ...]
    program_word_indexes: tuple[int, ...]
    uses: KnowledgeUses
    judgment_rule_use_counts: Counter[str]


def _expansion_of(
    catalogs_dir: Path,
    words: tuple[str, ...],
    expansion_word_indexes: tuple[int, ...] = (),
) -> _Expansion:
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    judgment_rule_use_counts: Counter[str] = Counter()
    program_invocations, roles, program_behaviors, program_word_indexes = (
        expand_program_invocations(
            ShellCommand(0, words, expansion_word_indexes=expansion_word_indexes),
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
    )
    return _Expansion(
        program_invocations,
        roles,
        program_behaviors,
        program_word_indexes,
        knowledge.uses,
        judgment_rule_use_counts,
    )


def _pieces_of(program_invocations: tuple) -> list[str]:
    """List the words, option names and values that the programs hold besides their program words."""
    pieces: list[str] = []
    for program_invocation in program_invocations:
        if isinstance(program_invocation, UnknownProgramInvocation):
            pieces += program_invocation.words
            continue
        pieces += [
            *program_invocation.subcommand_words,
            *(option.name for option in program_invocation.options),
            *(option.value or "" for option in program_invocation.options),
            *program_invocation.arguments,
            *program_invocation.unread_words,
        ]
    return pieces


def _written_program_words_of(
    program_invocations: tuple, words: tuple[str, ...], roles: tuple
) -> list[str]:
    """Find the program word of each program as written, i.e. the next word with the role None that is the program name or whose name without its folder starts with it, e.g. pip3 for pip."""
    written_program_words: list[str] = []
    index = 0
    for program_invocation in program_invocations:
        while not (
            roles[index] is None
            and (
                words[index] == program_invocation.program_name
                or words[index]
                .rsplit("/", 1)[-1]
                .startswith(program_invocation.program_name)
            )
        ):
            index += 1
        written_program_words.append(words[index])
        index += 1
    return written_program_words


# The words and expansion indexes of every case once, for the checks that hold for any command.
_DISTINCT_WORD_CASES = list(
    {case[1:3]: case[0] for case in INVOCATION_CASES + ROLE_CASES}.items()
)


@pytest.mark.parametrize(
    ("words", "expansion_word_indexes", "program_invocations"),
    [case[1:] for case in INVOCATION_CASES],
    ids=[case[0] for case in INVOCATION_CASES],
)
def test_words_are_read_into_the_programs_they_run(
    catalogs_dir, words, expansion_word_indexes, program_invocations
):
    expansion = _expansion_of(catalogs_dir, words, expansion_word_indexes)
    assert expansion.program_invocations == program_invocations


@pytest.mark.parametrize(
    ("words", "expansion_word_indexes"),
    [word_case for word_case, _ in _DISTINCT_WORD_CASES],
    ids=[case_id for _, case_id in _DISTINCT_WORD_CASES],
)
def test_every_letter_of_the_words_is_in_one_piece_of_the_programs_and_every_word_has_a_role(
    catalogs_dir, words, expansion_word_indexes
):
    """Hold the letters of the pieces of the programs and their program words against the letters of the words, without `-` and `=`, so that no word is read twice or dropped.

    Letters and not words are held, since `-fsSL` becomes four options and an attached value leaves the word of its option.
    """
    expansion = _expansion_of(catalogs_dir, words, expansion_word_indexes)

    def letters_of(texts: list[str]) -> list[str]:
        return sorted("".join(texts).replace("-", "").replace("=", ""))

    assert len(expansion.roles) == len(words)
    assert letters_of(
        _pieces_of(expansion.program_invocations)
        + _written_program_words_of(
            expansion.program_invocations, words, expansion.roles
        )
    ) == letters_of(list(words))


@pytest.mark.parametrize(
    ("words", "expansion_word_indexes", "roles"),
    [case[1:] for case in ROLE_CASES],
    ids=[case[0] for case in ROLE_CASES],
)
def test_each_word_gets_the_role_that_the_program_row_and_option_rows_give_together(
    catalogs_dir, words, expansion_word_indexes, roles
):
    assert _expansion_of(catalogs_dir, words, expansion_word_indexes).roles == roles


@pytest.mark.parametrize(
    ("words", "exits_with_exit_code_of_next_program"),
    [
        (("prog", "-y", "f"), True),
        (("prog", "-y", "-k", "f"), UNKNOWN_EXITS_WITH_EXIT_CODE_OF_NEXT_PROGRAM),
        (("prog", "-y", "-y", "f"), True),
    ],
)
def test_two_options_that_change_the_exit_code_answer_differently_give_unknown(
    catalogs_dir, words, exits_with_exit_code_of_next_program
):
    # prog runs no next program, so its words must stay unread for the options to answer.
    (program_invocation,) = _expansion_of(
        catalogs_dir, (*words, "--foo")
    ).program_invocations
    assert isinstance(program_invocation, ProgramInvocation)
    assert (
        program_invocation.exits_with_exit_code_of_next_program
        == exits_with_exit_code_of_next_program
    )


def test_door_is_asked_once_per_program_and_option_and_counts_an_option_without_a_row_as_the_whole_word(
    catalogs_dir,
):
    uses = _expansion_of(catalogs_dir, ("find", ".", "-maxdepth", "2")).uses

    assert uses == KnowledgeUses(
        row_use_counts=Counter({(PROGRAM_BEHAVIORS_CSV, ("find", "")): 1}),
        unknown_input_counts=Counter(
            {(PROGRAM_OPTION_BEHAVIORS_CSV, ("find", "", "-maxdepth")): 1}
        ),
    )


@pytest.mark.parametrize(
    ("words", "unknown_option_inputs"),
    [
        (("xargs", "curl", "-sO"), ()),
        (("curl", "-fsSLoout", "u"), ()),
        (("xargs", "-n1"), ()),
        # -X has no row, so the word is one unknown input and no letter is one.
        (("curl", "-fsXL", "u"), (("curl", "", "-fsXL"),)),
        # src is the first argument, whose role is a cluster, and -s has no row.
        (("tar", "-cf", "a.tgz", "src"), (("tar", "", "src"),)),
        (("grep", "-rn", "x", "."), (("grep", "", "-rn"),)),
        (("tail", "-5", "f"), (("tail", "", "-5"),)),
        (("sed", "-n", "1p", "f"), (("sed", "", "-n"),)),
        # echo may not join one-letter options, so -ne is one unknown input.
        (("echo", "-ne", "a"), (("echo", "", "-ne"),)),
    ],
)
def test_each_word_of_options_is_one_question_of_the_door_and_at_most_one_unknown_input(
    catalogs_dir, words, unknown_option_inputs
):
    uses = _expansion_of(catalogs_dir, words).uses

    assert uses.unknown_input_counts == Counter(
        (PROGRAM_OPTION_BEHAVIORS_CSV, row_key) for row_key in unknown_option_inputs
    )


@pytest.mark.parametrize(
    ("words", "blank_cell_count"),
    [
        # A word after the first argument of echo is not asked as an option, since no row could tell whether it is an option there, so the blank cell is the one unknown input. The words after it are not asked either.
        (("echo", "a", "-foo", "-n"), 1),
        (("echo", "a", "--", "b"), 1),
        # +o has a row of plusprog, so after the first argument it may be that option or an argument.
        (("plusprog", "a", "+o", "b"), 1),
        # Before the first argument the cell is not needed.
        (("echo", "-n", "a"), 0),
        # +x is no option of echo, so it is an argument whatever the cell says.
        (("echo", "a", "+x"), 0),
        # node says yes in the cell, so -v after the script is its argument.
        (("node", "x.js", "-v"), 0),
    ],
)
def test_each_word_left_unread_for_a_blank_options_end_cell_is_one_unknown_input(
    catalogs_dir, words, blank_cell_count
):
    uses = _expansion_of(catalogs_dir, words).uses

    assert uses.unknown_input_counts == Counter(
        {
            (
                BLANK_PROGRAM_BEHAVIOR_CELLS,
                (words[0], "", "options_end_at_first_argument"),
            ): blank_cell_count
        }
    )


def test_program_word_that_is_only_a_folder_is_counted_as_written(catalogs_dir):
    uses = _expansion_of(catalogs_dir, ("dir/", "x")).uses

    assert uses.unknown_input_counts == Counter(
        {(PROGRAM_BEHAVIORS_CSV, ("dir/", "")): 1}
    )


def test_each_program_is_given_with_its_row_at_the_same_index(catalogs_dir):
    program_behaviors = _expansion_of(
        catalogs_dir, ("sudo", "env", "mytool", "x")
    ).program_behaviors

    assert [
        program_behavior.program_name
        if isinstance(program_behavior, ProgramBehavior)
        else program_behavior
        for program_behavior in program_behaviors
    ] == ["sudo", "env", UnknownProgramBehavior()]


def test_each_program_is_given_with_the_index_of_its_word(catalogs_dir):
    # The words of find follow those of the programs that -exec starts, so the index of a program word is not the count of the words after it.
    expansion = _expansion_of(
        catalogs_dir,
        ("find", ".", "-exec", "./a.sh", ";", "-exec", "./b.sh", ";", "-print"),
    )

    assert [
        program_invocation.program_name
        for program_invocation in expansion.program_invocations
    ] == ["find", "a.sh", "b.sh"]
    assert expansion.program_word_indexes == (0, 3, 6)


def test_cluster_word_with_an_expansion_is_not_asked_of_the_door(catalogs_dir):
    uses = _expansion_of(catalogs_dir, ("tar", "$X", "a"), (1,)).uses

    assert uses == KnowledgeUses(
        row_use_counts=Counter({(PROGRAM_BEHAVIORS_CSV, ("tar", "")): 1})
    )


def test_program_word_with_an_expansion_is_not_asked_of_the_door(catalogs_dir):
    expansion = _expansion_of(catalogs_dir, ("$CMD", "-x", "u"), (0,))

    assert expansion.uses == KnowledgeUses()
    assert expansion.judgment_rule_use_counts == Counter()


@pytest.mark.parametrize(
    ("words", "expansion_word_indexes", "rule_use_count"),
    [
        (("curl", "$OPTS", "u"), (1,), 1),
        (("curl", "$A", "$B"), (1, 2), 2),
        (("bash", "-c", "$CMD"), (2,), 1),
        # The value of an option is read as one word like an argument.
        (("curl", "-o", "$F", "u"), (2,), 1),
        (("tar", "xzf", "$F"), (2,), 1),
        # A skipped `NAME=value` word, the word of the next program and a word whose place makes it a cluster are not read as one argument.
        (("env", "A=$X", "curl", "u"), (1,), 0),
        (("sudo", "$P", "u"), (1,), 0),
        (("tar", "$X", "a"), (1,), 0),
        # An argument that the option after it makes a program is unread with the words after it before the rule is asked.
        (("late", "a", "-p", "b", "$X"), (4,), 0),
    ],
)
def test_rule_on_words_with_an_expansion_is_counted_once_per_word_read_as_one_argument_or_value(
    catalogs_dir, words, expansion_word_indexes, rule_use_count
):
    expansion = _expansion_of(catalogs_dir, words, expansion_word_indexes)
    assert expansion.judgment_rule_use_counts == Counter(
        {EXPANSION_RULE_NAME: rule_use_count} if rule_use_count else {}
    )


@pytest.mark.parametrize(
    ("words", "expansion_word_indexes", "program_invocation", "roles"),
    [
        (
            ("curl", "-s", "$OPTS", "u"),
            (2,),
            _program_invocation(
                "curl", options=(_option("-s"),), unread_words=("$OPTS", "u")
            ),
            (None, None, UNKNOWN_ROLE, UNKNOWN_ROLE),
        ),
        # For a value, the option that would take it is unread too.
        (
            ("curl", "-s", "-o", "$F", "u"),
            (3,),
            _program_invocation(
                "curl", options=(_option("-s"),), unread_words=("-o", "$F", "u")
            ),
            (None, None, UNKNOWN_ROLE, UNKNOWN_ROLE, UNKNOWN_ROLE),
        ),
    ],
)
def test_word_with_an_expansion_and_the_words_after_it_are_unread_when_the_rule_says_no(
    catalogs_dir,
    monkeypatch,
    words,
    expansion_word_indexes,
    program_invocation,
    roles,
):
    monkeypatch.setattr(
        _expand_program_invocations,
        EXPANSION_RULE_NAME,
        lambda word, *, use_counts: False,
    )

    expansion = _expansion_of(catalogs_dir, words, expansion_word_indexes)

    assert expansion.program_invocations == (program_invocation,)
    assert expansion.roles == roles


def test_wrapper_chain_shell_option_with_a_plus_and_echo_are_read_on_the_real_catalogs():
    """Read commands on the real catalog folder, so that a renamed column or cell word of a row these commands use fails here."""
    knowledge = ExpandedToolCallKnowledge(catalogs_dir=EXPANDED_TOOL_CALL_CATALOGS_DIR)
    unknown_exits = UNKNOWN_EXITS_WITH_EXIT_CODE_OF_NEXT_PROGRAM

    wrapper_chain = expand_program_invocations(
        ShellCommand(0, ("sudo", "env", "timeout", "5", "curl", "u")),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    )
    shell_option = expand_program_invocations(
        ShellCommand(1, ("bash", "+o", "posix", "f.sh")),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    )
    # The row of echo leaves blank whether options end at its first argument.
    echo = expand_program_invocations(
        ShellCommand(2, ("echo", "-n", "hello", "-n")),
        knowledge=knowledge,
        judgment_rule_use_counts=Counter(),
    )

    assert wrapper_chain[0] == (
        _SUDO,
        _program_invocation("env", exits_with_exit_code_of_next_program=True),
        _program_invocation(
            "timeout",
            arguments=("5",),
            exits_with_exit_code_of_next_program=unknown_exits,
        ),
        _program_invocation(
            "curl", arguments=("u",), exits_with_exit_code_of_next_program=unknown_exits
        ),
    )
    assert wrapper_chain[3] == (0, 1, 2, 4)
    assert wrapper_chain[1] == (
        None,
        None,
        None,
        ProgramWordRole.OTHER,
        None,
        UNKNOWN_ROLE,
    )
    assert shell_option[:2] == (
        (
            _program_invocation(
                "bash", options=(_option("+o", "posix"),), arguments=("f.sh",)
            ),
        ),
        (None, None, ProgramWordRole.OTHER, ProgramWordRole.RUN_FILE),
    )
    assert echo[:2] == (
        (
            _program_invocation(
                "echo",
                options=(_option("-n"),),
                arguments=("hello",),
                unread_words=("-n",),
            ),
        ),
        (None, None, ProgramWordRole.OTHER, UNKNOWN_ROLE),
    )
