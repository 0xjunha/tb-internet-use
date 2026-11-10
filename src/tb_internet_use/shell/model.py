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
    """Output destination for the call's own result."""


@dataclass(frozen=True, slots=True)
class FileDestination:
    """Output destination for a file, e.g. `> fetch.log`."""

    path: str  # without quotes, e.g. fetch.log or $LOG/out


@dataclass(frozen=True, slots=True)
class PipeDestination:
    """Output destination for another command's stdin, e.g. the next stage of a pipeline or `>(tee log)`."""

    reader_id: int  # the first command that reads it


@dataclass(frozen=True, slots=True)
class CaptureDestination:
    """Output destination for a `$(...)` or `<(...)`, which hands it to the enclosing command."""


@dataclass(frozen=True, slots=True)
class DiscardDestination:
    """Output destination that throws output away, e.g. `> /dev/null`."""


@dataclass(frozen=True, slots=True)
class ParsedShellText:
    """Parse result of one shell text, returned by `parse_shell`."""

    commands: tuple[ShellCommand, ...]
    assignments: tuple[VariableAssignment, ...] = ()  # in order, to resolve $VAR


@dataclass(frozen=True, slots=True)
class ShellCommand:
    """One simple command in a shell text, with when it runs and where its output goes."""

    # Unique within one call.
    id: int
    # The command name, then its arguments, without quotes.
    # e.g. `("curl", "-sS", "https://a.org/x")` for `curl -sS 'https://a.org/x'`
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
    """Run condition of a command, met when its deciding commands ended with the required outcome.

    The deciding commands are the earlier commands whose exit code can decide it.
    When there are several, the one of them that ran last decides.
    For example in `a; b && c`, c depends on b only.
    In `(a || b) && c`, c runs if a succeeded, or if a failed and b succeeded.
    In `a || b`, b has RunCondition((id of a,), ExitOutcome.FAILURE).
    """

    # Empty when unknown, e.g. after `!`.
    deciding_command_ids: tuple[int, ...]
    required_outcome_of_deciding_commands: ExitOutcome


class ExitOutcome(StrEnum):
    """Exit outcome of a command, by whether its exit code is 0."""

    SUCCESS = "success"  # exit code 0
    FAILURE = "failure"  # any other exit code


@dataclass(frozen=True, slots=True)
class VariableAssignment:
    """Literal value that `NAME=value` or a for loop gives to a variable.

    Assignments in text that a new shell runs, such as `bash -c 'A=1'`, are left out.
    Those in `eval 'A=1'` count, since eval runs the text in this shell.
    """

    name: str
    value: str
    # The id the next command of the text gets, so commands from this id on come after it.
    next_command_id: int
