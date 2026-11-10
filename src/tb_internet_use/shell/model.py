"""Types for the simple commands in a shell text, with when each runs and where its output goes."""

from dataclasses import dataclass
from enum import StrEnum

# Where a command's stdout or stderr goes.
type OutputDestination = (
    ResultDestination
    | FileDestination
    | PipeDestination
    | CaptureDestination
    | DiscardDestination
)


@dataclass(frozen=True, slots=True)
class ResultDestination:
    """Output reaches the call's own result."""


@dataclass(frozen=True, slots=True)
class FileDestination:
    """Output is redirected to a file, e.g. `> fetch.log`."""

    path: str


@dataclass(frozen=True, slots=True)
class PipeDestination:
    """Output feeds the next stage of a pipeline."""

    reader_id: int  # the first command of the next stage


@dataclass(frozen=True, slots=True)
class CaptureDestination:
    """Output is captured by `$(...)` or `<(...)` for the enclosing command."""


@dataclass(frozen=True, slots=True)
class DiscardDestination:
    """Output is redirected to /dev/null."""


@dataclass(frozen=True, slots=True)
class ParsedShellText:
    """Every simple command in one shell text, in order, and its literal assignments."""

    commands: tuple[ShellCommand, ...]
    assignments: tuple[VariableAssignment, ...] = ()  # in order, to resolve $VAR


@dataclass(frozen=True, slots=True)
class ShellCommand:
    """One simple command in a shell text, with when it runs and where its output goes."""

    # Unique within one call.
    id: int
    # The command name, then its arguments, without quotes.
    # e.g. ("curl", "-sS", "https://a.org/x") for `curl -sS 'https://a.org/x'`
    words: tuple[str, ...]
    # A word holds $VAR, $(...) or similar, kept as written in `words`.
    # e.g. `pip install "$PKG"`
    has_expansion: bool = False
    # What a heredoc or herestring gives to stdin.
    # e.g. the lines between `<<EOF` and `EOF`, or "x" in `cat <<< x`
    stdin_text: str | None = None
    stdout: OutputDestination = ResultDestination()
    stderr: OutputDestination = ResultDestination()
    # All must hold for it to run.
    runs_if: tuple[RunCondition, ...] = ()
    # May run any number of times, including none.
    # e.g. pip in `for p in a b; do pip install $p; done`
    in_loop_body: bool = False
    # Runs only if the function is called.
    # e.g. git in `f() { git clone u; }; f`
    in_function_body: bool = False
    # Runs only if its pattern matches.
    # e.g. apt-get in `case $OS in debian) apt-get install -y x ;; esac`
    in_case_branch: bool = False
    # Started with &, so the text does not wait for it.
    # e.g. `nohup pip install x > p.log 2>&1 &`
    runs_in_background: bool = False
    # If the whole text exits 0, this command exited 0.
    # e.g. b in `a; b`
    #      a and b in `a && b`, or in `set -e; a; b`
    #      neither in `a || b`
    #      tail only in `curl u | tail -1`
    #      curl and tail in `set -o pipefail; curl u | tail -1`
    #      b only in `curl u & b`
    succeeded_if_text_exits_zero: bool = False
    # The text has a syntax error or a brace list, so the fields above may be wrong.
    # e.g. `cp {a,b} d && curl u`
    structure_may_be_wrong: bool = False


@dataclass(frozen=True, slots=True)
class RunCondition:
    """A command runs only if the deciding commands ended with the required outcome.

    The deciding commands are the earlier commands whose exit code decides it.
    For example in `a; b && c`, c depends on b only.
    In `a || b`, b has RunCondition((id of a,), ExitOutcome.FAILURE).
    """

    # Empty when unknown, e.g. after `!`.
    deciding_command_ids: tuple[int, ...]
    required_outcome_of_deciding_commands: ExitOutcome


class ExitOutcome(StrEnum):
    """Whether a command exited with code 0."""

    SUCCESS = "success"  # exit code 0
    FAILURE = "failure"  # any other exit code


@dataclass(frozen=True, slots=True)
class VariableAssignment:
    """A literal value given to a variable by `NAME=value`, or one value of a for loop."""

    name: str
    value: str
