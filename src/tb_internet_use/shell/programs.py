"""Find the program a shell command runs, past wrappers such as sudo, and the shell text it runs."""

import re
from dataclasses import dataclass
from typing import NamedTuple

from tb_internet_use.shell.model import ShellCommand


@dataclass(frozen=True, slots=True)
class _Wrapper:
    """Argument rules of a wrapper such as sudo, used to find the command it runs."""

    # Options that take the next word as their value, e.g. -u in `sudo -u root`.
    options_with_value: frozenset[str] = frozenset()
    # Words before the command that are neither options nor assignments.
    # e.g. 30 in `timeout 30 curl u`
    operands: int = 0
    # Whether NAME=value words before the command set its environment, e.g. A=1 in `env A=1 curl u`.
    takes_assignments: bool = False


_TIMEOUT = _Wrapper(frozenset({"-s", "--signal", "-k", "--kill-after"}), operands=1)
# Commands that run the command in their arguments.
_WRAPPERS = {
    "sudo": _Wrapper(
        frozenset({"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-R", "-t", "-T", "-U"})
        | {"--user", "--group", "--close-from", "--chdir", "--host", "--prompt"}
        | {"--role", "--chroot", "--type", "--command-timeout", "--other-user"},
        takes_assignments=True,
    ),
    "doas": _Wrapper(frozenset({"-u", "-C"})),
    "env": _Wrapper(
        frozenset({"-u", "--unset", "-C", "--chdir"}), takes_assignments=True
    ),
    "timeout": _TIMEOUT,
    "gtimeout": _TIMEOUT,
    "nohup": _Wrapper(),
    "nice": _Wrapper(frozenset({"-n", "--adjustment"})),
    "time": _Wrapper(frozenset({"-f", "--format", "-o", "--output"})),
    "stdbuf": _Wrapper(frozenset({"-i", "--input", "-o", "--output", "-e", "--error"})),
    "setsid": _Wrapper(),
    "unbuffer": _Wrapper(),
    "exec": _Wrapper(frozenset({"-a"})),
    "command": _Wrapper(),
    "xargs": _Wrapper(
        frozenset({"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s"})
        | {"--arg-file", "--delimiter", "--max-lines", "--max-args", "--max-procs"}
        | {"--max-chars"}
    ),
}
# Programs that run another program with arguments the text does not show.
_PROGRAMS_GIVING_RUN_TIME_ARGUMENTS = frozenset({"find", "xargs"})
# Python options that take the next word as their value, e.g. -X in `python -X dev -m pip`.
_PYTHON_OPTIONS_WITH_VALUE = frozenset({"-X", "-W"})
# Programs whose name often ends with a version, e.g. python3.11, pip3 and gcc-12.
_VERSIONED_PROGRAMS = frozenset(
    {"python", "pip", "pypy", "pydoc", "ruby", "gem", "perl", "php", "node", "lua"}
    | {"gcc", "g++", "clang", "clang++", "java", "javac"}
)
_VERSION_SUFFIX = re.compile(r"-?\d+(?:\.\d+)*$")
_SHELL_PROGRAMS = frozenset({"bash", "sh", "zsh", "dash"})
# A cluster of one-letter shell options, e.g. -e or -euxc.
_SHELL_OPTION_CLUSTER = re.compile(r"-[a-zA-Z]+")
# Options that `set -o` and `bash -o` take and that change what the exit code says.
_SHELL_OPTION_NAMES = frozenset({"errexit", "pipefail"})
# Long shell options that take the next word as their value, e.g. `bash --rcfile f`.
_SHELL_LONG_OPTIONS_WITH_VALUE = frozenset({"--rcfile", "--init-file"})


def gets_arguments_at_run_time(command: ShellCommand) -> bool:
    """Check whether a command's program gets arguments that the text does not show.

    e.g. curl in `find . -exec curl {} \\;` or `cat urls | xargs curl`.
    """
    skipped = _unwrap_program(command.words).skipped_wrappers
    return bool(skipped & _PROGRAMS_GIVING_RUN_TIME_ARGUMENTS)


def nested_shell_text(command: ShellCommand) -> str | None:
    """Find the shell text a command runs, e.g. `a && b` for `bash -c 'a && b'` or `eval 'a && b'`."""
    words = program_words(command)
    if words[:1] == ("eval",):
        return " ".join(words[1:]) or None
    if words[:1] and words[0] in _SHELL_PROGRAMS:
        return _shell_invocation(words[1:]).text
    return None


def shell_options_at_start(command: ShellCommand) -> frozenset[str]:
    """Find the errexit and pipefail options a shell command turns on before its text runs.

    e.g. errexit for `bash -e fetch.sh` or `sh -ec 'a; b'`, pipefail for `bash -o pipefail -c a`.
    """
    words = program_words(command)
    if words[:1] and words[0] in _SHELL_PROGRAMS:
        return _shell_invocation(words[1:]).options
    return frozenset()


def program_words(command: ShellCommand) -> tuple[str, ...]:
    """Find the program a command runs, named as `normalized_program_name` gives it, then its arguments.

    Wrappers and `python -m` are skipped, e.g. pip for `sudo python3 -m pip install x`.
    For `find -exec` and `xargs`, it is the program they run.
    """
    return _unwrap_program(command.words).words


def _unwrap_program(words: tuple[str, ...]) -> _UnwrappedProgram:
    """Skip the wrappers before a program, and return its words and the wrappers skipped."""
    skipped: set[str] = set()
    while words:
        name = normalized_program_name(words[0])
        arguments = words[1:]
        # `command -v x` only looks x up, while `command x` runs it.
        is_lookup = name == "command" and arguments[:1] in (("-v",), ("-V",))
        if name == "find" and (exec_words := _find_exec_words(arguments)) is not None:
            skipped.add(name)
            words = exec_words
        elif name in _WRAPPERS and not is_lookup:
            skipped.add(name)
            words = _command_after_wrapper(_WRAPPERS[name], arguments)
        elif name == "python" and (module := _python_module_words(arguments)):
            words = module
        else:
            return _UnwrappedProgram((name, *arguments), frozenset(skipped))
    return _UnwrappedProgram((), frozenset(skipped))


class _UnwrappedProgram(NamedTuple):
    """Program found past a command's wrappers, used by `program_words` and `gets_arguments_at_run_time`."""

    words: tuple[str, ...]  # the program, then its arguments
    skipped_wrappers: frozenset[str]  # e.g. sudo and xargs


def normalized_program_name(word: str) -> str:
    """Strip the directory and version from a program word.

    e.g. python for /usr/bin/python3.11, gcc for gcc-12 and playwright for playwright@1.49.
    A name such as base64 keeps its digits, since only known versioned programs lose them.
    """
    base = word.rsplit("/", 1)[-1] or word
    name = base.split("@", 1)[0] or base
    unversioned = _VERSION_SUFFIX.sub("", name)
    return unversioned if unversioned in _VERSIONED_PROGRAMS else name


def _find_exec_words(arguments: tuple[str, ...]) -> tuple[str, ...] | None:
    """Take the command of `find -exec` or `-execdir`, without its `{}` and its `;` or `+` end."""
    start = next(
        (i for i, w in enumerate(arguments) if w in ("-exec", "-execdir")), None
    )
    if start is None:
        return None
    exec_words = arguments[start + 1 :]
    end = next(
        (i for i, w in enumerate(exec_words) if w in (";", "+")), len(exec_words)
    )
    return tuple(w for w in exec_words[:end] if w != "{}")


def _command_after_wrapper(
    wrapper: _Wrapper, arguments: tuple[str, ...]
) -> tuple[str, ...]:
    """Skip a wrapper's own words and return those of the command it runs."""
    index = 0
    operands_left = wrapper.operands
    while index < len(arguments):
        word = arguments[index]
        if word == "--":
            index += 1
            break
        if word.startswith("-") and len(word) > 1:
            index += 2 if word in wrapper.options_with_value else 1
        elif wrapper.takes_assignments and "=" in word and not word.startswith("="):
            index += 1
        elif operands_left:
            operands_left -= 1
            index += 1
        else:
            break
    return arguments[index:]


def _python_module_words(arguments: tuple[str, ...]) -> tuple[str, ...]:
    """Take the module and its arguments from `python [options] -m module ...`, empty without -m."""
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if word == "-m":
            return arguments[index + 1 :]
        if word in _PYTHON_OPTIONS_WITH_VALUE:
            index += 2
        elif word.startswith("-") and word not in ("-", "-c"):
            index += 1
        else:
            return ()
    return ()


def _shell_invocation(arguments: tuple[str, ...]) -> _ShellInvocation:
    """Read a shell's options up to the first operand, which is the text when -c is given.

    e.g. text a for `bash -c -e a`, and no text for `bash fetch.sh -c a`.
    """
    options: set[str] = set()
    reads_text = False
    index = 0
    while index < len(arguments):
        word = arguments[index]
        following = arguments[index + 1] if index + 1 < len(arguments) else None
        if word in ("-o", "+o", "-O", "+O") or word in _SHELL_LONG_OPTIONS_WITH_VALUE:
            if word == "-o" and following in _SHELL_OPTION_NAMES:
                options.add(following)
            index += 2
        elif _SHELL_OPTION_CLUSTER.fullmatch(word):
            letters = word[1:]
            if "e" in letters:
                options.add("errexit")
            reads_text = reads_text or "c" in letters
            if "o" in letters:  # e.g. -euo pipefail
                if following in _SHELL_OPTION_NAMES:
                    options.add(following)
                index += 1
            index += 1
        elif word == "--":
            index += 1
            break
        elif word.startswith(("--", "+")):
            index += 1
        else:
            break
    text = arguments[index] if reads_text and index < len(arguments) else None
    return _ShellInvocation(text, frozenset(options))


class _ShellInvocation(NamedTuple):
    """Invocation of a shell such as `bash -e -c a`, read by `nested_shell_text` and `shell_options_at_start`."""

    text: str | None  # the text after -c
    options: frozenset[str]  # errexit and pipefail, when its options turn them on
