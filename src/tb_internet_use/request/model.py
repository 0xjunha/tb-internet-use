"""Types for candidate requests in commands, code and web tool actions, with facts about their runs that later decide how far each request got.

The same exit code can mean different things, e.g. plain `curl` exits 0 even after an HTTP 404, while `curl -f` exits 0 only when the content arrived.
These facts come from the command alone, before any output is read.
"""

from dataclasses import dataclass

from tb_internet_use.network.model import Host, PrintingProgram
from tb_internet_use.program.model import ExitZeroMeans, RequestKind
from tb_internet_use.toolcall.model import ToolCallKey

# Source of a candidate request within its call, which is a shell command, code it ran or a web tool action.
type RequestSource = FromCommand | FromCode | FromWebTool


@dataclass(frozen=True, slots=True)
class CandidateRequest:
    """Candidate request found in a tool call's commands, code and web tool actions before any output is read.

    Requests to local hosts such as localhost are candidates too, so that their output lines link to them instead of to another request or to a request inferred from output.
    """

    call: ToolCallKey
    source: RequestSource
    kind: RequestKind
    # Name of the program that makes it, as `normalized_program_name` gives it. None for a web tool action.
    # e.g. pip for `sudo python3 -m pip install x`, curl for `/usr/bin/curl u`, node for code in `node fetch.js`
    program_name: str | None
    # Packages, URLs, repositories or queries it asks for, one per value of a variable with known values.
    targets: tuple[RequestTarget, ...]
    # The hosts its targets, its code or a package index option name.
    hosts: tuple[Host, ...]
    # Normalized names of the packages it asks for. Empty when it asks for none, e.g. `apt-get update`.
    # None when it may ask for packages its words do not name, e.g. `pip install -r reqs.txt` or `pip install $PKG`.
    asked_package_names: frozenset[str] | None
    # Programs whose output lines its run can print, e.g. uv and pip for `uv pip install`.
    printing_programs: frozenset[PrintingProgram]
    # Its program runs or builds something and fetches only what that needs, e.g. `npx tsc`, `uv run` or `lake build`.
    fetches_only_to_run_or_build: bool
    # An option makes it stay off the network or prefer local copies, e.g. `--offline`, `--no-index` or `--prefer-offline`.
    has_offline_option: bool
    # Meaning of its program's exit code 0, e.g. SERVER_RESPONDED for plain `curl`.
    # None when it is not known, e.g. for code, a web tool action or a program without a rule.
    exit_zero_means: ExitZeroMeans | None
    # It asks for no content back, e.g. `curl -I`, `wget --spider` or `git push`.
    asks_for_no_content: bool
    # The response body goes to stdout, e.g. curl without -o. True for a web tool action, whose result shows the response.
    # None for code, whose words cannot tell.
    prints_response_body: bool | None
    # It prints the HTTP status code, e.g. `curl -w "%{http_code}"`.
    prints_status_code: bool
    # An option hides its progress lines, e.g. `pip -q` or `curl -s`.
    quiet_progress_lines: bool
    # An option hides its error lines, e.g. `curl -s` without -S.
    quiet_error_lines: bool


@dataclass(frozen=True, slots=True)
class FromCommand:
    """Request source for a shell command of the call."""

    command_id: int


@dataclass(frozen=True, slots=True)
class FromCode:
    """Request source for Python or JavaScript code that a command of the call ran."""

    runner_command_id: int


@dataclass(frozen=True, slots=True)
class FromWebTool:
    """Request source for a web tool action of the call."""

    # 0-based in `RunToolScriptAction.steps`, None when the web action is the call's action.
    step_index: int | None


@dataclass(frozen=True, slots=True)
class RequestTarget:
    """Target of a candidate request, such as a package, URL, repository or query, with the value it has when its command runs.

    A for loop gives one target per value, e.g. a.org and b.org for `$u` in `for u in a.org b.org; do curl $u; done`.
    Targets with the same written text and no loop variable are alternatives, e.g. after `A=1` in one if branch and `A=2` in the other.
    """

    # The target as the command's words write it, e.g. `$u` or `https://a.org/x`.
    written: str
    # The target with variable values filled in. None when a value is unknown, e.g. for `$PKG` set outside the text.
    value: str | None
    # The for loop variable whose items give one target each, so its command runs once per value. None outside such a loop.
    loop_variable: str | None
