"""Define the tables of wrappers and shells that `programs` reads to find the program a command runs and the shell text it runs.

`docs/behavior-tables.md` shows them for review.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Wrapper:
    """Argument rules of a wrapper such as sudo, used to find the command it runs."""

    # Options that take the next word as their value, e.g. -u in `sudo -u root`.
    options_with_value: frozenset[str] = frozenset()
    # How many words before the command are neither options nor assignments, e.g. 1 for 30 in `timeout 30 curl u`.
    operand_count: int = 0
    # Whether NAME=value words before the command set its environment, e.g. A=1 in `env A=1 curl u`.
    takes_assignments: bool = False


_TIMEOUT = Wrapper(frozenset({"-s", "--signal", "-k", "--kill-after"}), operand_count=1)
# Commands that run the command in their arguments.
WRAPPERS = {
    "sudo": Wrapper(
        frozenset({"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-R", "-t", "-T", "-U"})
        | {"--user", "--group", "--close-from", "--chdir", "--host", "--prompt"}
        | {"--role", "--chroot", "--type", "--command-timeout", "--other-user"},
        takes_assignments=True,
    ),
    "doas": Wrapper(frozenset({"-u", "-C"})),
    "env": Wrapper(
        frozenset({"-u", "--unset", "-C", "--chdir"}), takes_assignments=True
    ),
    "timeout": _TIMEOUT,
    "gtimeout": _TIMEOUT,
    "nohup": Wrapper(),
    "nice": Wrapper(frozenset({"-n", "--adjustment"})),
    # bash's time keyword runs a command with its prefix assignments, e.g. `time A=1 curl u`.
    "time": Wrapper(
        frozenset({"-f", "--format", "-o", "--output"}), takes_assignments=True
    ),
    "stdbuf": Wrapper(frozenset({"-i", "--input", "-o", "--output", "-e", "--error"})),
    "setsid": Wrapper(),
    "unbuffer": Wrapper(),
    "exec": Wrapper(frozenset({"-a"})),
    "command": Wrapper(),
    "xargs": Wrapper(
        frozenset({"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s"})
        | {"--arg-file", "--delimiter", "--max-lines", "--max-args", "--max-procs"}
        | {"--max-chars"}
    ),
}
# Programs that run another program with arguments the text does not show.
PROGRAMS_GIVING_RUN_TIME_ARGUMENTS = frozenset({"find", "xargs"})
# Python options that take the next word as their value, e.g. -X in `python -X dev -m pip`.
PYTHON_OPTIONS_WITH_VALUE_BEFORE_MODULE = frozenset({"-X", "-W"})
# Programs whose name often ends with a version, e.g. python3.11, pip3 and gcc-12.
VERSIONED_PROGRAMS = frozenset(
    {"python", "pip", "pypy", "pydoc", "ruby", "gem", "perl", "php", "node", "lua"}
    | {"gcc", "g++", "clang", "clang++", "java", "javac"}
)
# Shells that run a file, a `-c` text or their stdin as shell text, e.g. bash in `bash -c 'a && b'`.
SHELL_PROGRAMS = frozenset({"bash", "sh", "zsh", "dash"})
# Options that `set -o` and `bash -o` take and that change what the exit code says.
EXIT_CODE_SHELL_OPTION_NAMES = frozenset({"errexit", "pipefail"})
# Long shell options that take the next word as their value, e.g. `bash --rcfile f`.
SHELL_LONG_OPTIONS_WITH_VALUE = frozenset({"--rcfile", "--init-file"})
