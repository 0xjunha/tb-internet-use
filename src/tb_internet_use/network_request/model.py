"""Request types for the commands, code and web tool calls that the calls of one trial ran, one request per target, holding only the materials that later rules compute from.

One command can ask for several things, e.g. `pip install requests git+https://github.com/a/b` asks for a package and a repository, and each can end differently.

The module also holds the answers of `NetworkRequestKnowledge` and of the reading functions that `extract_network_requests` tells apart when it runs, e.g. `UnknownProgramNetworkRequestLabel`, since a step never imports its knowledge class when it runs.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from tb_internet_use.expanded_tool_call.model import (
    CodeLanguage,
    CodeTextSource,
    OutputVisibility,
    ProgramInvocation,
    RanTextSource,
    UnknownProgramInvocation,
)
from tb_internet_use.tool_call.model import (
    HarnessTool,
    ShellCommandVariableAssignment,
    ToolCallKey,
)

# Place of a request within its call, with what made it there.
type NetworkRequestSource = FromCommand | FromCode | FromWebTool
# Where the content that a request receives goes.
type ReceivedContentDestination = (
    NoContentRequested
    | ContentDiscarded
    | ContentSaved
    | ContentShownInResult
    | ContentPipedToCommand
    | UnknownReceivedContentDestination
)
# Answer of `NetworkRequestKnowledge` about a program and subcommand that has a row of the program request catalog.
type ProgramNetworkRequestLabel = FetchingProgramLabel | NonFetchingProgramLabel


@dataclass(frozen=True, slots=True)
class NetworkRequest:
    """Request for one target that a tool call made or may have made, to any host. Whether it is internet use is computed when rows are exported.

    Requests to local hosts such as localhost are requests too, so that their output lines go to them instead of to another request.
    """

    # The call that ran it.
    tool_call_key: ToolCallKey
    # The 0-based index among the requests of the call, so that two requests of one command can be told apart, e.g. the two of `curl u u`.
    index_in_tool_call: int
    source: NetworkRequestSource
    # What it asks for, with the values of variables filled in, e.g. `requests` or `https://a.org/x`.
    # None when its words name none, e.g. `apt-get update`.
    target: str | UnknownNetworkRequestTarget | None
    target_kind: NetworkRequestTargetKind | UnknownNetworkRequestTargetKind
    # The hosts its words name, e.g. in a URL or an index option. Empty when they name none, e.g. `pip install requests`.
    host_names: tuple[str, ...]
    received_content_destination: ReceivedContentDestination
    # The certainty from what ran alone, before any output is read.
    certainty: NetworkRequestCertainty
    # None when the request is confirmed.
    uncertainty_reason: NetworkRequestUncertaintyReason | None

    def __post_init__(self) -> None:
        """Refuse an uncertain request without a reason, a confirmed one with a reason, and a reason or a confirmation that its source cannot give.

        A reason names the knowledge that would settle the request, e.g. `UNKNOWN_CODE_CALL` a row of the code call catalog, so a reason of another source would point at the wrong file.
        """
        is_uncertain = self.certainty == NetworkRequestCertainty.UNCERTAIN
        if is_uncertain != (self.uncertainty_reason is not None):
            raise ValueError(f"{self.certainty} with {self.uncertainty_reason}")
        if not _is_uncertainty_reason_possible_for_source(
            self.uncertainty_reason, self.source
        ):
            raise ValueError(f"{self.uncertainty_reason} does not fit {self.source}")


def _is_uncertainty_reason_possible_for_source(
    uncertainty_reason: NetworkRequestUncertaintyReason | None,
    source: NetworkRequestSource,
) -> bool:
    """Tell whether `extract_network_requests` can give a request of this source this reason, or no reason for a confirmed request.

    A program that no fact covers, e.g. `UnknownProgramInvocation("mytool", …)`, and a call in code that no row covers, i.e. an `UnknownCodeCall`, give only uncertain requests, since no fact says that they fetch.
    """
    match uncertainty_reason:
        case None:
            return not _is_unknown_program_or_code_call(source)
        case NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM:
            # A program in a command without a row of the program request catalog, e.g. `mytool https://a.org/x` or `bash setup.sh https://a.org/x`, or a program that a code call with a row runs, e.g. `subprocess.run(["mytool", "https://a.org/x"])`.
            return isinstance(source, FromCommand) or (
                isinstance(source, FromCode) and isinstance(source.call_name, str)
            )
        case NetworkRequestUncertaintyReason.UNREAD_WORDS:
            return _is_command_of_known_program(source)
        case NetworkRequestUncertaintyReason.UNKNOWN_OPTION_EFFECT:
            return _is_command_of_known_program(source)
        case NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING:
            return _is_command_of_known_program(source)
        case NetworkRequestUncertaintyReason.STRUCTURE_MAY_BE_WRONG:
            return _is_command_of_known_program(source)
        case NetworkRequestUncertaintyReason.UNKNOWN_CODE_CALL:
            return isinstance(source, FromCode) and isinstance(
                source.call_name, UnknownCodeCall
            )
        case NetworkRequestUncertaintyReason.URL_OUTSIDE_CODE_CALL:
            return isinstance(source, FromCode) and isinstance(
                source.call_name, UnknownCodeCall
            )
        case NetworkRequestUncertaintyReason.PROGRAM_RUN_BY_CODE:
            return isinstance(source, FromCode) and isinstance(source.call_name, str)
        case NetworkRequestUncertaintyReason.CALL_NAME_MAY_BE_ANOTHER_FUNCTION:
            return isinstance(source, FromCode) and isinstance(source.call_name, str)
        case NetworkRequestUncertaintyReason.FINDS_TEXT_IN_OPENED_PAGE:
            return isinstance(source, FromWebTool)


def _is_command_of_known_program(source: NetworkRequestSource) -> bool:
    """Tell whether the source is a command whose program the catalog of `expand_tool_calls` covers."""
    return isinstance(source, FromCommand) and isinstance(
        source.program_invocation, ProgramInvocation
    )


def _is_unknown_program_or_code_call(source: NetworkRequestSource) -> bool:
    """Tell whether the source is a program without a row of the catalog of `expand_tool_calls` or a call in code without a row of the code call catalog."""
    if isinstance(source, FromCommand):
        return isinstance(source.program_invocation, UnknownProgramInvocation)
    if isinstance(source, FromCode):
        return isinstance(source.call_name, UnknownCodeCall)
    return False


@dataclass(frozen=True, slots=True)
class FromCommand:
    """Request source for a program that a shell command of the call runs."""

    command_id: int
    # Where the text of the command is, e.g. in a file that another call wrote, so that a person can find it in the trajectory.
    ran_text_source: RanTextSource
    # The reading of the words of the program that makes the request, one of the command's `RanCommand.program_invocations`, e.g. the one of `pip install` in `sudo uv run pip install x`.
    program_invocation: ProgramInvocation | UnknownProgramInvocation
    # The `NAME=value` before the command name, which the first program of the command gets as variables and may pass on to the programs it runs, e.g. `PIP_INDEX_URL=https://a.org/simple` of `PIP_INDEX_URL=https://a.org/simple pip install x`.
    # It exists because such a variable can change where a request whose words name no host goes, or whether it goes out, e.g. to another index than the default registry of pip.
    variable_assignments: tuple[ShellCommandVariableAssignment, ...] = ()


@dataclass(frozen=True, slots=True)
class FromCode:
    """Request source for a call or a URL in Python or JavaScript code that a command of the tool call ran or that a poll typed, e.g. `requests.get(u)` or `BASE = "https://a.org"`."""

    # None for code typed through a poll, whose runner is a command of the call that started the handle, named by `code_text_source.starter_tool_call_key`.
    runner_command_id: int | None
    # Where the code is.
    code_text_source: CodeTextSource
    code_language: CodeLanguage
    # The name of the row of the call that sends it, e.g. `requests.get`, also for `rq.get(u)` after `import requests as rq`. An `UnknownCodeCall` when the request comes from a URL that no call with a row is known to send, e.g. one in a call without a row, in a `Request` that no call with a row sends or in no call at all.
    call_name: str | UnknownCodeCall


@dataclass(frozen=True, slots=True)
class UnknownCodeCall:
    """Call in code that no fact says sends a request, or no call at all, for a URL in code that gives an uncertain request, e.g. `mylib.fetch("https://a.org/x")` in Python or `URL = "https://a.org/x"`."""


@dataclass(frozen=True, slots=True)
class FromWebTool:
    """Request source for a web tool action of the call. Where the tool sends from is computed from the tool when rows are exported."""

    # The 0-based index in `RunToolScriptAction.steps`, None when the web action is the call's action.
    step_index: int | None
    # The tool of the call. For a web step of a tool script it is the script tool, e.g. `exec` of Codex, since the trajectory names no tool for a step.
    harness_tool: HarnessTool


@dataclass(frozen=True, slots=True)
class UnknownNetworkRequestTarget:
    """Target that a request has and the trial does not show, standing where the target text would."""

    reason: UnknownNetworkRequestTargetReason

    def __bool__(self) -> bool:
        """Refuse to be read as True or False, so that `if network_request.target` never takes a target that the trial does not show for a target that it shows, since a target that names none is None."""
        raise TypeError("the target of the request is not known")


class UnknownNetworkRequestTargetReason(StrEnum):
    """Reason the trial does not show the target of a request."""

    # A variable without a literal value, e.g. `pip install $PKG`, or arguments that the program gets when it runs, e.g. `cat urls.txt | xargs curl`.
    VALUE_SET_AT_RUN_TIME = "value_set_at_run_time"
    # A file or the project names the targets, e.g. `pip install -r reqs.txt` or `npm ci`.
    NAMED_IN_FILE = "named_in_file"
    # The target is a path on the machine, so the words do not show whether a registry is asked, e.g. `pip install -e .` or `pip install ./dist/x.whl`.
    LOCAL_PATH = "local_path"
    # An option that no fact covers, so which word is the target is not known, e.g. `curl --foo x u`.
    UNREAD_WORDS = "unread_words"
    # An option whose effect no fact of the request catalog covers stands where no word names a target, so its value may name one, e.g. `curl -K cfg`.
    UNKNOWN_OPTION_EFFECT = "unknown_option_effect"
    # Code builds the target or passes it to a program it runs, e.g. `requests.get(base + path)` or `subprocess.run(["pip", "install", "x"])`.
    BUILT_IN_CODE = "built_in_code"


class NetworkRequestTargetKind(StrEnum):
    """Kind of thing that a request asks for."""

    PACKAGE_NAME = "package_name"
    REPOSITORY_URL = "repository_url"
    URL = "url"
    SEARCH_QUERY = "search_query"
    HOST = "host"  # a host alone, e.g. `ping pypi.org`


@dataclass(frozen=True, slots=True)
class UnknownNetworkRequestTargetKind:
    """Target kind that the source of a request does not tell, e.g. for a program that code runs or a call whose target is a name such as `from_pretrained("bert-base")`."""

    def __bool__(self) -> bool:
        """Refuse to be read as True or False, so that `if code_call_label.target_kind` never takes a kind that the row leaves blank for a kind that it gives, since a call that sends no request has None."""
        raise TypeError("the target kind is not known")


@dataclass(frozen=True, slots=True)
class NoContentRequested:
    """Content destination of a request that asks for no content back, e.g. `ping`, `curl -I` or `npm ping`."""


@dataclass(frozen=True, slots=True)
class ContentDiscarded:
    """Content destination of a request whose content is thrown away, e.g. `curl u > /dev/null`."""


@dataclass(frozen=True, slots=True)
class ContentSaved:
    """Content destination of a request whose content goes to a file or is installed, e.g. `curl -o a.tgz u`, `curl u > a.tgz` or `pip install x`."""

    # The file as `WrittenFile.path` names it. None when the words name no file, e.g. `pip install x`.
    path: str | None


@dataclass(frozen=True, slots=True)
class ContentShownInResult:
    """Content destination of a request whose content goes to a result that the trajectory shows, e.g. plain `curl u` or a web fetch tool."""


@dataclass(frozen=True, slots=True)
class ContentPipedToCommand:
    """Content destination of a request whose content goes to another command, e.g. `curl u | tar xz` or `curl u | jq .`."""

    reader_command_id: int
    # How much of the content the result still shows, e.g. `PARTIAL` after `| head` and `NONE` after `| wc -c`.
    visibility_at_end: OutputVisibility


@dataclass(frozen=True, slots=True)
class UnknownReceivedContentDestination:
    """Content destination that the trial does not show, e.g. for code or for `x=$(curl u)`."""


class NetworkRequestCertainty(StrEnum):
    """Strength of the ground for calling something a request."""

    # What made it is known to fetch, e.g. `pip install x` or `curl u`.
    CONFIRMED = "confirmed"
    # It may be a request, e.g. a URL that may be public in the words of a program that no fact covers, or a program that fetches only what is missing, e.g. `npx tsc`.
    UNCERTAIN = "uncertain"


class NetworkRequestUncertaintyReason(StrEnum):
    """Reason a request is uncertain, so that uncertain requests can be grouped into what knowledge would settle and what would not."""

    # The words of the program show a URL that may be public or whose host cannot be read, e.g. `http://db:5432` or `http://[::1/x`, and no fact says whether the program fetches. This holds for a program that no fact covers, e.g. `mytool https://a.org/x`. It also holds for a program that has a row only in the catalog of program behaviors of `expand_tool_calls`, e.g. `bash setup.sh u`, and for a program run by code.
    UNKNOWN_PROGRAM = "unknown_program"
    # The program invocation has unread words, since an option has no row in the catalog of `expand_tool_calls`, e.g. `curl --foo x u`.
    UNREAD_WORDS = "unread_words"
    # The program has a row and an option it was read with has none in the request catalog, which may stop the request, e.g. `-K` of `curl -K cfg u`.
    UNKNOWN_OPTION_EFFECT = "unknown_option_effect"
    # A URL that may be public or whose host cannot be read sits in the arguments of a call that has no row, e.g. `mylib.fetch("https://a.org/x")` in Python, or of a call that holds the target of a request that no call with a row reads from it, e.g. `Request("https://a.org/x")` passed to `opener.open`.
    UNKNOWN_CODE_CALL = "unknown_code_call"
    # A URL that may be public sits in code outside the arguments of every call, e.g. `URL = "https://a.org/x"`. No added fact settles it.
    URL_OUTSIDE_CODE_CALL = "url_outside_code_call"
    # Code runs a program that may fetch, and its words are not read, e.g. `subprocess.run(["pip", "install", "x"])`.
    PROGRAM_RUN_BY_CODE = "program_run_by_code"
    # A call in code has the name of a row that sends a request only at its end, also after an import of the code text gives its full name, or as a whole after the text binds its first part to a value and does not import it, so the text does not show that it is the function of the row, e.g. `self.page.goto(u)`, `GPT2TokenizerFast.from_pretrained(m)` after `from transformers import GPT2TokenizerFast` or `page.goto(u)` after `page = browser.new_page()`.
    CALL_NAME_MAY_BE_ANOTHER_FUNCTION = "call_name_may_be_another_function"
    # The program fetches only what is missing, e.g. `npx tsc`. A line of its output that shows that the request was sent settles that it fetched, e.g. `npm warn exec The following package was not found and will be installed: tsc@2.0.4` of `npx tsc`, and nothing settles that it did not.
    FETCHES_ONLY_WHAT_IS_MISSING = "fetches_only_what_is_missing"
    # The words of the command may hold words of another command, since `parse_shell_text` left lines joined that tree-sitter-bash still read as one after three repairs and marked the command with `structure_may_be_wrong`, e.g. a next line `echo https://b.org` read as more words of `curl -s http://localhost:8000/x`. No added fact settles it.
    STRUCTURE_MAY_BE_WRONG = "structure_may_be_wrong"
    # A web tool looks for text in a page that it opened, e.g. a web find of Codex, and may search the page it already holds without a new request. No added fact settles it.
    FINDS_TEXT_IN_OPENED_PAGE = "finds_text_in_opened_page"


@dataclass(frozen=True, slots=True)
class FetchingProgramLabel:
    """Label of a program and subcommand that fetches, read by `extract_network_requests` to make the requests of a command."""

    fetches_only_what_is_missing: bool  # e.g. `npx`, `lake build`, `sbt`
    target_arguments: TargetArguments
    target_kind: NetworkRequestTargetKind
    target_notation: TargetNotation
    target_without_target_arguments: TargetWithoutTargetArguments
    content_route: ProgramContentRoute | UnknownProgramContentRoute


@dataclass(frozen=True, slots=True)
class NonFetchingProgramLabel:
    """Label of a program and subcommand that is known not to fetch, e.g. `echo` or `cat`."""


@dataclass(frozen=True, slots=True)
class UnknownProgramNetworkRequestLabel:
    """Answer of `NetworkRequestKnowledge` for a program and subcommand without a row of the program request catalog, also standing where True or False would for a program name without any row."""

    def __bool__(self) -> bool:
        """Refuse to be read as True or False, so that `if may_program_fetch(…)` never takes a program without a row for one that fetches."""
        raise TypeError("whether the program fetches is not known")


class TargetArguments(StrEnum):
    """Arguments of a fetching program that name its targets."""

    ALL = "all"  # e.g. `pip install A B C`
    FIRST = "first"  # e.g. `git clone u dir`
    NEXT_PROGRAM = "next_program"  # e.g. `tsc` in `npx tsc`
    NONE = "none"  # e.g. `apt-get update`


class TargetNotation(StrEnum):
    """Notation of a target word, which tells `parse_target` how to read its host and kind."""

    # A URL with a scheme, e.g. the argument of `requests.get`.
    URL = "url"
    # A URL that may lack its scheme, e.g. `curl pypi.org/simple`.
    URL_OR_SCHEMELESS_URL = "url_or_schemeless_url"
    # A URL or an address as scp writes it, e.g. `git clone git@github.com:a/b.git`.
    URL_OR_SCP_LIKE_ADDRESS = "url_or_scp_like_address"
    # A host alone, e.g. `ping pypi.org`.
    HOST_NAME = "host_name"
    # A host and a path as rsync writes them, e.g. `host:/x`.
    RSYNC_ADDRESS = "rsync_address"
    # A name, a `git+` address, a URL or a local path, e.g. `pip install ./dist/x.whl`.
    PIP_REQUIREMENT = "pip_requirement"
    # A name that holds no host, e.g. `apt-get install x`.
    NAME = "name"
    # A host and a port in one argument of a call in code, e.g. `socket.create_connection(("api", 8000))`.
    HOST_AND_PORT_TUPLE = "host_and_port_tuple"


class TargetWithoutTargetArguments(StrEnum):
    """Request that a fetching program makes when no argument names a target."""

    # One request without a target, e.g. `apt-get update`.
    NO_TARGET = "no_target"
    # One request whose targets a file or the project names, e.g. `npm install`.
    NAMED_IN_FILE = "named_in_file"
    # No request, e.g. `curl` without arguments.
    NO_REQUEST = "no_request"


class ProgramContentRoute(StrEnum):
    """Route that a fetching program gives the content it receives, before its options and redirects are read."""

    STDOUT = "stdout"  # e.g. `curl`
    OWN_FILE = "own_file"  # e.g. `wget`, `pip install` or `git clone`
    NO_CONTENT = "no_content"  # e.g. `ping` or `npm ping`


@dataclass(frozen=True, slots=True)
class UnknownProgramContentRoute:
    """Content route that the row of a fetching program leaves blank, standing where a `ProgramContentRoute` would."""


class ProgramOptionEffect(StrEnum):
    """Effect of one option of a fetching program on its requests."""

    # It changes neither whether a request is sent, nor the targets, the hosts or whether the content goes to stdout.
    NONE = "none"
    # With it the program sends no request, e.g. `--help` or `--no-index` of pip.
    SENDS_NO_REQUEST = "sends_no_request"
    # With it the program fetches only what is missing, e.g. `--prefer-offline` of npm.
    FETCHES_ONLY_WHAT_IS_MISSING = "fetches_only_what_is_missing"
    # With it the program asks for no content back, e.g. `-I` of curl.
    ASKS_FOR_NO_CONTENT = "asks_for_no_content"
    # With it the content goes to stdout, e.g. `-o -` of curl.
    SENDS_CONTENT_TO_STDOUT = "sends_content_to_stdout"
    # With it the content goes to a file that the program writes itself, e.g. `-o a.tgz` or `-O` of curl, unlike another file it writes, e.g. the headers of `-D h.txt`.
    SENDS_CONTENT_TO_FILE = "sends_content_to_file"
    # Its value names a host that the request asks, e.g. `-i` of pip.
    NAMES_HOST_IN_VALUE = "names_host_in_value"
    # Its value is a file that names the targets, e.g. `-r` of pip.
    NAMES_TARGETS_IN_FILE = "names_targets_in_file"
    # Its value is one target in the notation of the program, e.g. `-e` of pip, which takes a local path or a `git+` address.
    NAMES_TARGET_IN_VALUE = "names_target_in_value"


@dataclass(frozen=True, slots=True)
class UnknownProgramOptionEffect:
    """Answer of `NetworkRequestKnowledge` for an option without a row of the program request catalog."""


@dataclass(frozen=True, slots=True)
class CodeCallLabel:
    """Label of one call name of a code language in the code call catalog."""

    # The name as the row writes it, e.g. `urlopen` for a call written `urllib.request.urlopen`.
    call_name: str
    effect: CodeCallEffect
    # None unless the call sends a request or holds the target of one.
    target_notation: TargetNotation | None
    # None unless the call sends a request or holds the target of one. An `UnknownNetworkRequestTargetKind` when the row of such a call leaves it blank.
    target_kind: NetworkRequestTargetKind | UnknownNetworkRequestTargetKind | None
    # The Python module that the name starts with when code writes the call through that module, e.g. `requests` for `requests.get`.
    # None for a name that is not written through a module, e.g. `urlopen` or `page.goto`, where `page` is an object, so that a call written without an import of the module can be told apart, e.g. `requests.get(rid)` where `requests` is a dict.
    module_name: str | None

    def __post_init__(self) -> None:
        """Refuse a target notation or kind for a call that neither sends a request nor holds the target of one, and such a call without both."""
        has_target = self.effect in CODE_CALL_EFFECTS_WITH_TARGET
        has_target_notation = self.target_notation is not None
        has_target_kind = self.target_kind is not None
        if (has_target_notation, has_target_kind) != (has_target, has_target):
            raise ValueError(
                f"{self.effect} with {self.target_notation} and {self.target_kind}"
            )


class CodeCallEffect(StrEnum):
    """Effect of a call in code that the code call catalog names."""

    # The call sends a request itself, e.g. `requests.get`.
    SENDS_NETWORK_REQUEST = "sends_network_request"
    # The call builds the target of a request that another call sends, e.g. `urllib.request.Request`, whose object `urlopen` sends.
    HOLDS_NETWORK_REQUEST_TARGET = "holds_network_request_target"
    # The call runs a program named in its first string, e.g. `subprocess.run`.
    RUNS_PROGRAM = "runs_program"
    SENDS_NO_NETWORK_REQUEST = "sends_no_network_request"


# The effects of the calls whose row names a target notation and kind.
CODE_CALL_EFFECTS_WITH_TARGET = frozenset(
    {CodeCallEffect.SENDS_NETWORK_REQUEST, CodeCallEffect.HOLDS_NETWORK_REQUEST_TARGET}
)


@dataclass(frozen=True, slots=True)
class UnknownCodeCallLabel:
    """Answer of `NetworkRequestKnowledge` for a call name without a row of the code call catalog."""


@dataclass(frozen=True, slots=True)
class ParsedCode:
    """Reading of one code text by `parse_code`, with its call sites and the names it gives one string or one call to."""

    # The calls in text order, a nested call after the call that holds it.
    code_calls: tuple[CodeCall, ...]
    string_assignments: tuple[CodeStringAssignment, ...]
    call_assignments: tuple[CodeCallAssignment, ...]
    # The distinct full names that the imports of the text bind to each name, in the order of the text, e.g. `("requests",)` for `rq` of `import requests as rq`, `("urllib.request.urlopen",)` for `urlopen` of `from urllib.request import urlopen`, `("urllib",)` for `urllib` of `import urllib.request`, `("child_process.execSync",)` for `execSync` of `const { execSync } = require("child_process")` or `("requests", "httpx")` for `http` of `import requests as http` in a `try` and `import httpx as http` in its `except`.
    # It exists because a call is found by its form, so `rq.get(u)` is a call of `requests.get` only through this name, and `requests.get(rid)` is a call of the library when the text imports `requests` and not when it binds `requests` to a dict instead.
    imported_full_names_by_name: Mapping[str, tuple[str, ...]]
    # The bare names that Python binds by an assignment at the start of a line, a parameter of a `def` or `lambda` or the variable of a `for` loop that starts a line, e.g. `requests` of `requests = {}`, `def plan(requests, pk):` or `for requests in batches:`. Empty for JavaScript.
    # It exists so that a call through a name that the text binds to something else, e.g. `requests.get(rid)` after `requests = {}`, is not read as a call of the module, while a call through a name the text neither imports nor binds, e.g. after `from helpers import *`, still is.
    names_bound_by_assignment_parameter_or_loop: frozenset[str]
    # The 0-based index of the code from which the text was not read, None when all of it was read.
    # It exists because a multi-line string, template string or block comment that never closes hides every call after it, e.g. `fetch(u)` after the backtick of `/`/` in JavaScript.
    unreadable_text_start: int | None


@dataclass(frozen=True, slots=True)
class CodeCall:
    """Call site in code as `parse_code` reads it, e.g. `requests.get` with the text between its parentheses."""

    # The name as written, bare or dotted, e.g. `fetch` or `urllib.request.urlopen`.
    name: str
    # The text between its parentheses, with the nested calls in it. Unreadable when the parentheses do not close.
    argument_text: str | UnreadableCodeCallArguments
    # The quoted strings of its arguments, in order, without those inside the parentheses of a nested call, which belong to that call.
    string_literals: tuple[str, ...]
    # The first argument when it is positional, or else the argument named `url`, when that argument is one string literal, e.g. the URL of `requests.get("https://a.org/x")` or of `requests.get(timeout=3, url="https://a.org/x")`.
    first_argument_string: str | None
    # The same argument when it is one bare name, e.g. `URL` in `requests.get(URL)`.
    first_argument_name: str | None
    # The bare name that the same argument starts with when more of the argument follows it, e.g. `BASE` in `requests.get(BASE + path)`.
    # None when `(`, `.` or `[` follows the name, since the argument then reads from the name and does not start with its value, e.g. `urls[0] + path`.
    first_argument_leading_name: str | None
    # The 0-based index in `ParsedCode.code_calls` of the call that the same argument is as a whole, e.g. of `Request` in `urlopen(Request(u))`.
    first_argument_code_call_index: int | None

    def __post_init__(self) -> None:
        """Refuse strings or a first argument for a call whose arguments could not be read."""
        if isinstance(self.argument_text, UnreadableCodeCallArguments) and (
            self.string_literals
            or self.first_argument_string is not None
            or self.first_argument_name is not None
            or self.first_argument_leading_name is not None
            or self.first_argument_code_call_index is not None
        ):
            raise ValueError(f"unreadable arguments of {self.name} with values")


@dataclass(frozen=True, slots=True)
class UnreadableCodeCallArguments:
    """Arguments of a call in code whose parentheses do not close, standing where the argument text would."""


@dataclass(frozen=True, slots=True)
class CodeStringAssignment:
    """Assignment of one string literal to a bare name in code, e.g. `URL = "https://a.org/x"`."""

    name: str
    value: str


@dataclass(frozen=True, slots=True)
class CodeCallAssignment:
    """Assignment of one call to a bare name in code, e.g. `req = urllib.request.Request(u)`, so that a call given the name can be read through it."""

    name: str
    # The 0-based index in `ParsedCode.code_calls` of the call.
    code_call_index: int


class NoNetworkRequestReason(StrEnum):
    """Reason a program run, a code call or a URL in code gave no request, counted for tracking and never written into a request."""

    NON_FETCHING_PROGRAM = "non_fetching_program"
    OPTION_SENDS_NO_REQUEST = "option_sends_no_request"
    NO_TARGET_ARGUMENTS = "no_target_arguments"
    # The program has no row and runs something else whose text the trial holds, e.g. `sudo`.
    PROGRAM_RUNS_SOMETHING_ELSE = "program_runs_something_else"
    # A program without a row, also one that code runs, or a code call without a row shows no URL that may be public or whose host cannot be read, e.g. `mytool sync`.
    NO_URL_THAT_MAY_BE_PUBLIC = "no_url_that_may_be_public"
    NON_FETCHING_CODE_CALL = "non_fetching_code_call"
    NON_FETCHING_PROGRAM_RUN_BY_CODE = "non_fetching_program_run_by_code"
    # A URL in code that is used as a name, e.g. an XML namespace.
    NAMESPACE_URL = "namespace_url"
    LOCAL_OR_RESERVED_URL_IN_CODE = "local_or_reserved_url_in_code"


@dataclass(frozen=True, slots=True)
class ParsedTarget:
    """Reading of one target word in the notation of its program, e.g. a pip requirement or an scp-like address."""

    # None when the word names no host, e.g. `requests` or `main:main`.
    host_name: str | None
    # None when the notation does not change the kind of the row.
    target_kind: NetworkRequestTargetKind | None
    # True for a path on the machine, e.g. `.` or `./dist/x.whl` for a pip requirement.
    is_local_path: bool


class HostNameScope(StrEnum):
    """Scope of a host name as `parse_host_name` reads it from the standards, read by `extract_network_requests` to tell which URLs may be public and when rows are exported to tell internet use."""

    PUBLIC = "public"  # e.g. a public IP address
    LOCAL = "local"  # e.g. `localhost`, `10.0.0.5` or a `.internal` name
    RESERVED = "reserved"  # e.g. `example.com`


@dataclass(frozen=True, slots=True)
class UnknownHostNameScope:
    """Scope of a host name that the standards do not settle, with the form of the name."""

    reason: UnknownHostNameScopeReason


class UnknownHostNameScopeReason(StrEnum):
    """Form of a host name whose scope the standards do not settle."""

    DOTTED_NAME = "dotted_name"  # e.g. `files.acme.org`
    SINGLE_LABEL = "single_label"  # e.g. `db`
    TEMPLATED = "templated"  # e.g. `$HOST`
    EMPTY_LABEL = "empty_label"  # e.g. `a..org` or `...`, no name by RFC 1035
