"""Tests for shell/programs.py."""

import pytest

from tb_internet_use.shell.model import ShellCommand
from tb_internet_use.shell.programs import (
    gets_arguments_at_run_time,
    nested_shell_text,
    normalized_program_name,
    program_words,
    shell_options_at_start,
)


def _command(*words: str) -> ShellCommand:
    return ShellCommand(id=0, words=words)


@pytest.mark.parametrize(
    ("word", "name"),
    [
        ("curl", "curl"),
        ("/usr/bin/python3.11", "python"),
        ("pip3", "pip"),
        ("gcc-12", "gcc"),
        ("playwright@1.49.0", "playwright"),
        ("@scope/pkg@1.2", "pkg"),
        ("./fetch.sh", "fetch.sh"),
        ("./@scope", "@scope"),
        (".", "."),
        # Digits that are part of a name stay.
        ("base64", "base64"),
        ("sqlite3", "sqlite3"),
        ("md5", "md5"),
    ],
)
def test_normalized_program_name(word: str, name: str):
    assert normalized_program_name(word) == name


@pytest.mark.parametrize(
    ("words", "program"),
    [
        (("pip3", "install", "--user", "x"), ("pip", "install", "--user", "x")),
        (
            ("sudo", "-u", "root", "timeout", "30", "env", "A=1", "apt-get", "install"),
            ("apt-get", "install"),
        ),
        (("sudo", "-n", "curl", "u"), ("curl", "u")),
        (("sudo", "--user", "root", "curl", "u"), ("curl", "u")),
        (("timeout", "--signal", "KILL", "30", "curl", "u"), ("curl", "u")),
        (("sudo", "-k", "apt-get", "update"), ("apt-get", "update")),
        (("/usr/bin/sudo", "curl", "u"), ("curl", "u")),
        (("doas", "curl", "u"), ("curl", "u")),
        (("timeout", "-s", "KILL", "30", "curl", "u"), ("curl", "u")),
        (("nohup", "nice", "-n", "10", "pip", "install", "x"), ("pip", "install", "x")),
        (("time", "curl", "u"), ("curl", "u")),
        (("exec", "curl", "u"), ("curl", "u")),
        (("stdbuf", "-oL", "curl", "u"), ("curl", "u")),
        (("command", "curl", "u"), ("curl", "u")),
        (("command", "-v", "curl"), ("command", "-v", "curl")),  # only a lookup
        (("env", "3proxy", "x"), ("3proxy", "x")),
        (("/usr/bin/env", "python3", "x.py"), ("python", "x.py")),
        (("python3", "-m", "pip", "install", "-q", "x"), ("pip", "install", "-q", "x")),
        (("python", "-u", "-m", "pip", "install", "x"), ("pip", "install", "x")),
        (("python3", "get.py"), ("python", "get.py")),
        (("python", "-c", "x"), ("python", "-c", "x")),
        (
            ("find", ".", "-name", "*.u", "-exec", "curl", "-s", "{}", ";"),
            ("curl", "-s"),
        ),
        (("find", ".", "-execdir", "curl", "{}", "+", "-print"), ("curl",)),
        (("find", ".", "-name", "x"), ("find", ".", "-name", "x")),
        (("xargs", "-n1", "-I", "{}", "curl", "-s", "{}"), ("curl", "-s", "{}")),
        (("xargs", "-n", "1", "curl", "-s"), ("curl", "-s")),
        (("sudo",), ()),
    ],
)
def test_program_words_skip_wrappers(words: tuple[str, ...], program: tuple[str, ...]):
    assert program_words(_command(*words)) == program


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (("find", ".", "-exec", "curl", "{}", ";"), True),
        (("xargs", "curl", "-s"), True),
        (("sudo", "xargs", "curl", "-s"), True),
        (("curl", "-s", "u"), False),
        (("find", ".", "-name", "x"), False),
    ],
)
def test_gets_arguments_at_run_time(words: tuple[str, ...], expected: bool):
    assert gets_arguments_at_run_time(_command(*words)) == expected


@pytest.mark.parametrize(
    ("words", "text"),
    [
        (("bash", "-c", "a && b"), "a && b"),
        (("sh", "-lc", "a"), "a"),
        (("zsh", "-c", "a"), "a"),
        (("bash", "-o", "pipefail", "-c", "a"), "a"),
        (("bash", "-euo", "pipefail", "-c", "a"), "a"),
        (("sudo", "-n", "bash", "-c", "a"), "a"),
        (("bash", "--rcfile", "f", "-c", "a"), "a"),
        (("eval", "a", "&&", "b"), "a && b"),
        (("bash", "fetch.sh", "-c", "a"), None),  # -c is an argument of fetch.sh
        (("bash", "-c", "-e", "a"), "a"),  # options go on after -c
        (("bash", "-c"), None),
        (("python", "-c", "a"), None),
    ],
)
def test_nested_shell_text(words: tuple[str, ...], text: str | None):
    assert nested_shell_text(_command(*words)) == text


@pytest.mark.parametrize(
    ("words", "options"),
    [
        (("bash", "-e", "fetch.sh"), {"errexit"}),
        (("sh", "-ec", "a"), {"errexit"}),
        (("bash", "-euo", "pipefail", "-c", "a"), {"errexit", "pipefail"}),
        (("bash", "-o", "pipefail", "-c", "a"), {"pipefail"}),
        (("bash", "-c", "a"), set()),
        (("bash", "fetch.sh", "-e"), set()),  # -e is an argument of fetch.sh
        (("python", "-e"), set()),
    ],
)
def test_shell_options_at_start(words: tuple[str, ...], options: set[str]):
    assert shell_options_at_start(_command(*words)) == options
