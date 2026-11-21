"""Result types for network requests, giving for each request how far it got, why it stopped there and the evidence in the trajectory.

The four levels alone cannot tell "it failed there" from "nothing shows beyond there", so each result also says why it stopped.

The module also holds the answers of `NetworkRequestResultKnowledge` and the types that `decide_network_request_results` passes between its pieces, e.g. `UnknownOutputLineMeaning` and `OutputPlaceSources`, since a step never imports its knowledge class when it runs.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from tb_internet_use.expanded_tool_call.model import FileUse
from tb_internet_use.network_request.model import (
    NetworkRequest,
    NetworkRequestCertainty,
    NoContentRequested,
)
from tb_internet_use.tool_call.model import ExecutionStatus, ToolCallKey

# Evidence in the trajectory for the result of a request.
type NetworkRequestResultEvidence = (
    OutputLineEvidence
    | HttpStatusEvidence
    | ExitCodeEvidence
    | ExecutionStatusEvidence
    | FileUseEvidence
    | ShownContentEvidence
)
# Reason that the level of a result is assumed, as the evidence or the choice of a judgment rule that leaves it unsure.
type NetworkRequestResultAssumptionReason = (
    SharedOutputLineAssumptionReason
    | UnknownProgramOutputLinesAssumptionReason
    | UnknownRunBesideAssumptionReason
    | MissingProgramOfAnotherCommandAssumptionReason
    | SharedHttpStatusAssumptionReason
    | SharedFileUseAssumptionReason
    | JudgmentRuleAssumptionReason
)


@dataclass(frozen=True, slots=True)
class NetworkRequestResult:
    """Result of one network request, decided from its own evidence."""

    # The request that `extract_network_requests` found.
    network_request: NetworkRequest
    # The certainty that it is a request, after the evidence. `CONFIRMED` when `network_request.certainty` is, or when an output line of this request alone shows that it was sent.
    request_certainty_after_evidence: NetworkRequestCertainty
    level: NetworkRequestResultLevel
    # None when the request got what it asked for, i.e. `RECEIVED`, or `REACHED` for a request that asks for no content.
    stop_reason: NetworkRequestResultStopReason | None
    # The certainty of `level`. With `NOT_VISIBLE` it says how sure the level is that was reached, not what lies beyond it.
    level_certainty: NetworkRequestResultCertainty
    evidence: tuple[NetworkRequestResultEvidence, ...]
    # Every reason that `level_certainty` is `ASSUMED`, each once, empty when it is `CONFIRMED`. They are the reasons of the evidence that shows `level` and `stop_reason`, and a judgment rule that picked them, e.g. a `SharedOutputLineAssumptionReason` for `Fetched 10 kB in 1s` that `apt-get install -y a b` printed once for two requests.
    assumption_reasons: tuple[NetworkRequestResultAssumptionReason, ...]

    def __post_init__(self) -> None:
        """Refuse a level and stop reason that a request cannot have, a claim that rests on no evidence, a request certainty that the evidence cannot give, and reasons that do not fit the certainty or the evidence.

        A failure is recorded only when the trajectory shows a trace of it, and a request is lifted to confirmed only by an output line of this request alone, e.g. `npm ERR! code E404` under `npx tsc`.
        A confirmed result has no assumption reason and an assumed one has at least one, and a shared output line that is a reason is a line of the evidence that other requests own too.
        """
        if not _is_valid_level_and_stop_reason(
            self.level,
            self.stop_reason,
            asks_for_no_content=isinstance(
                self.network_request.received_content_destination,
                NoContentRequested,
            ),
        ):
            raise ValueError(f"{self.level} cannot stop with {self.stop_reason}")
        if not self.evidence and (
            self.level != NetworkRequestResultLevel.ATTEMPTED
            or self.stop_reason == NetworkRequestResultStopReason.FAILED
        ):
            raise ValueError(f"{self.level} and {self.stop_reason} without evidence")
        if (
            self.network_request.certainty == NetworkRequestCertainty.CONFIRMED
            and self.request_certainty_after_evidence
            == NetworkRequestCertainty.UNCERTAIN
        ):
            raise ValueError("evidence cannot make a confirmed request uncertain")
        if (
            self.network_request.certainty == NetworkRequestCertainty.UNCERTAIN
            and self.request_certainty_after_evidence
            == NetworkRequestCertainty.CONFIRMED
            and not _has_output_line_evidence_of_this_request_alone(self.evidence)
        ):
            raise ValueError(
                "an uncertain request lifted to confirmed without an output line of its own"
            )
        if (
            self.level_certainty == NetworkRequestResultCertainty.CONFIRMED
            and self.assumption_reasons
        ):
            raise ValueError("a confirmed result with assumption reasons")
        if (
            self.level_certainty == NetworkRequestResultCertainty.ASSUMED
            and not self.assumption_reasons
        ):
            raise ValueError("an assumed result without assumption reasons")
        for assumption_reason in self.assumption_reasons:
            if isinstance(
                assumption_reason, SharedOutputLineAssumptionReason
            ) and not _has_shared_output_line_evidence(
                self.evidence, assumption_reason
            ):
                raise ValueError(
                    f"{assumption_reason} names no output line of the evidence that other requests own too"
                )


def _has_shared_output_line_evidence(
    evidence: tuple[NetworkRequestResultEvidence, ...],
    shared_output_line_assumption_reason: SharedOutputLineAssumptionReason,
) -> bool:
    """Tell whether the evidence holds the output line that a shared output line reason names, marked as one that other requests own too."""
    return any(
        isinstance(piece, OutputLineEvidence)
        and piece.is_shared_with_other_requests
        and (
            piece.showing_tool_call_key,
            piece.line_index,
            piece.line_index_in_json_string,
        )
        == (
            shared_output_line_assumption_reason.showing_tool_call_key,
            shared_output_line_assumption_reason.line_index,
            shared_output_line_assumption_reason.line_index_in_json_string,
        )
        for piece in evidence
    )


def _is_valid_level_and_stop_reason(
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason | None,
    *,
    asks_for_no_content: bool,
) -> bool:
    """Tell whether a request can stop at a level for a reason.

    A request has no stop reason only when it got what it asked for, which is `RECEIVED`, or `REACHED` for a request that asks for no content, e.g. `curl -I u`. `NOT_NEEDED` stops only at `EXECUTED`, and `FAILED` and `NOT_VISIBLE` stop at any level below `RECEIVED`.
    A request whose received content destination is not known, e.g. one in code, counts as one that asks for content, since only `NoContentRequested` makes `REACHED` a success.
    """
    if stop_reason is None:
        success_level = (
            NetworkRequestResultLevel.REACHED
            if asks_for_no_content
            else NetworkRequestResultLevel.RECEIVED
        )
        return level == success_level
    if stop_reason == NetworkRequestResultStopReason.NOT_NEEDED:
        return level == NetworkRequestResultLevel.EXECUTED
    return level != NetworkRequestResultLevel.RECEIVED


def _has_output_line_evidence_of_this_request_alone(
    evidence: tuple[NetworkRequestResultEvidence, ...],
) -> bool:
    """Tell whether the evidence holds an output line that no other request can have printed."""
    return any(
        isinstance(piece, OutputLineEvidence)
        and not piece.is_shared_with_other_requests
        for piece in evidence
    )


class NetworkRequestResultLevel(StrEnum):
    """Level that a request reached, each one including those before it.

    Comparing two levels with `<` or `max` without a `key` raises `TypeError`, since a string enum would otherwise compare the spelled values, which sort in level order only by chance.
    The value stays text, so a row can write it as it is.
    """

    ATTEMPTED = "attempted"  # a call asked for it
    EXECUTED = "executed"  # what makes the request ran
    REACHED = "reached"  # a server answered
    RECEIVED = "received"  # the content arrived

    def __lt__(self, other: object) -> NoReturn:
        raise _level_comparison_error()

    def __le__(self, other: object) -> NoReturn:
        raise _level_comparison_error()

    def __gt__(self, other: object) -> NoReturn:
        raise _level_comparison_error()

    def __ge__(self, other: object) -> NoReturn:
        raise _level_comparison_error()


def _level_comparison_error() -> TypeError:
    return TypeError(
        "NetworkRequestResultLevel has no order of its own. Pass the order of the levels as a key."
    )


class NetworkRequestResultStopReason(StrEnum):
    """Reason a request has no higher level."""

    # The trajectory shows that the next level failed, e.g. `Could not resolve host` or HTTP 404.
    FAILED = "failed"
    # The trajectory shows nothing beyond this level, e.g. output sent to /dev/null.
    NOT_VISIBLE = "not_visible"
    # Nothing had to be sent, e.g. pip `Requirement already satisfied`.
    NOT_NEEDED = "not_needed"


class NetworkRequestResultCertainty(StrEnum):
    """Strength of the ground for a result."""

    # It rests on evidence of this request alone, or the request has no evidence.
    CONFIRMED = "confirmed"
    # It rests on evidence shared with other requests or on a judgment rule, e.g. one error line for two `curl` commands.
    ASSUMED = "assumed"


@dataclass(frozen=True, slots=True)
class OutputLineEvidence:
    """Evidence in a line of a call's `tool_output_text`."""

    # The call whose result shows the line.
    showing_tool_call_key: ToolCallKey
    # The 0-based index of the line in the text split at "\n".
    line_index: int
    # The 0-based index of the line in the `output` string of the JSON object that the output line holds, e.g. a Codex step result.
    # None when the output line holds no such object.
    line_index_in_json_string: int | None
    kind: OutputLineKind
    # Other requests reach the same place and can print the line too. False for a line of another command that stopped this request, e.g. `rg: command not found` before `&& pip install y`.
    is_shared_with_other_requests: bool


@dataclass(frozen=True, slots=True)
class HttpStatusEvidence:
    """Evidence in `ToolCallResult.http_status`, the HTTP status a web fetch reports."""

    showing_tool_call_key: ToolCallKey
    http_status: int


@dataclass(frozen=True, slots=True)
class ExitCodeEvidence:
    """Evidence in the exit code of the command text that ran the request."""

    reporter_tool_call_key: ToolCallKey
    exit_code: int
    # The command text ran other requests too, so the exit code is about all of them. It does not make the result assumed, since whether a command ran holds for every request of it.
    is_shared_with_other_requests: bool


@dataclass(frozen=True, slots=True)
class ExecutionStatusEvidence:
    """Evidence in the execution status of the call that ran the request, e.g. `NOT_RUN` for a call that the harness refused."""

    reporter_tool_call_key: ToolCallKey
    execution_status: ExecutionStatus
    # The call ran other requests too, so the status is about all of them. It does not make the result assumed, since whether a command ran holds for every request of it.
    is_shared_with_other_requests: bool


@dataclass(frozen=True, slots=True)
class FileUseEvidence:
    """Evidence in a later use of the file that holds what the request received, e.g. `tar xzf a.tgz` after `curl -O u/a.tgz`."""

    file_use: FileUse


@dataclass(frozen=True, slots=True)
class ShownContentEvidence:
    """Evidence in a result that shows the received content itself, e.g. the page text in the result of a web fetch."""

    showing_tool_call_key: ToolCallKey


@dataclass(frozen=True, slots=True)
class SharedOutputLineAssumptionReason:
    """Assumption reason of a result whose level an output line shows that other requests own too, so that any of them may have printed it, e.g. one `Fetched 10 kB in 1s` under `apt-get install -y a b`.

    The line is named by where it is, which is one line in a trial, so that the results that share it can be found together.
    """

    # The call whose result shows the line.
    showing_tool_call_key: ToolCallKey
    # The 0-based index of the line in the text split at "\n".
    line_index: int
    # The 0-based index of the line in the `output` string of the JSON object that the output line holds, None when it holds none.
    line_index_in_json_string: int | None


@dataclass(frozen=True, slots=True)
class UnknownProgramOutputLinesAssumptionReason:
    """Assumption reason of a result whose level an output line that the request owns shows, also one that other requests own too, where `NetworkRequestResultKnowledge` knows no lines that the run of the request prints, e.g. `HTTP/1.1 200 OK` under `mytool https://a.org/x`.

    `treat_line_that_unknown_printer_may_have_printed_as_shared` chose to treat such a line as one that another run may have printed.
    """


@dataclass(frozen=True, slots=True)
class UnknownRunBesideAssumptionReason:
    """Assumption reason of a result whose level a line that any program prints shows, where a run whose content or program is unknown reaches the same place, e.g. `Connection refused` under `curl -s u; ./test.sh`.

    `treat_line_that_unknown_printer_may_have_printed_as_shared` chose to treat such a line as one that the unknown run may have printed.
    """


@dataclass(frozen=True, slots=True)
class MissingProgramOfAnotherCommandAssumptionReason:
    """Assumption reason of a result that a missing program line stopped, where the word of that line is the program of another command whose output reaches the place too, e.g. the first `rg` of `rg a; rg x && pip install y` under `rg: command not found`."""


@dataclass(frozen=True, slots=True)
class SharedHttpStatusAssumptionReason:
    """Assumption reason of a result whose level the HTTP status of a web fetch shows, where the call of the fetch made other requests too, so that the status may be theirs."""


@dataclass(frozen=True, slots=True)
class SharedFileUseAssumptionReason:
    """Assumption reason of a result whose level a use of its saved file shows, where another request of the call saved the same file, so that the use may be of the content of either, e.g. `tar xzf a` after `curl -o a u1; curl -o a u2`."""


@dataclass(frozen=True, slots=True)
class JudgmentRuleAssumptionReason:
    """Assumption reason of a result whose level or stop reason a rule of `judgment_rules.py` gave, other than `treat_line_that_unknown_printer_may_have_printed_as_shared`, e.g. `REACHED` for exit 0 of `curl -s u` by `treat_exit_code_meaning_as_assumed_level`.

    It does not name the rule, since the uses of each rule are counted outside the output types.
    """


class OutputLineKind(StrEnum):
    """Kind of evidence in an output line, without the level it gives a request."""

    # The host name did not resolve, e.g. `Could not resolve host: pypi.org`.
    NAME_NOT_RESOLVED = "name_not_resolved"
    # No connection was made, e.g. `Connection refused` or a connect timeout.
    CONNECTION_FAILED = "connection_failed"
    # A connection was made and then broke, e.g. `Connection reset by peer`.
    CONNECTION_LOST = "connection_lost"
    # A proxy refused the request or could not be reached.
    PROXY_REFUSED = "proxy_refused"
    TLS_FAILED = "tls_failed"
    # A connection was made, as wget's `connected.` shows.
    CONNECTED = "connected"
    # A response status, e.g. `HTTP/1.1 404 Not Found`.
    HTTP_STATUS = "http_status"
    # A line that only a server's answer gives, without a status code, e.g. apt `Hit:1`.
    SERVER_ANSWERED = "server_answered"
    # The package or repository was not found, e.g. pip `No matching distribution found for x`.
    NOT_FOUND = "not_found"
    # The package was already there, e.g. pip `Requirement already satisfied`.
    ALREADY_PRESENT = "already_present"
    # The program is not installed, e.g. `pip: command not found`.
    PROGRAM_MISSING = "program_missing"
    # The program refused before asking a server, e.g. pip's externally-managed-environment error.
    REFUSED_LOCALLY = "refused_locally"
    # pip's notice of a newer pip.
    VERSION_NOTICE = "version_notice"
    # A download began, e.g. pip `Downloading x.whl`.
    DOWNLOAD_STARTED = "download_started"
    # Content arrived, e.g. wget `saved` or apt `Get:1`.
    DOWNLOADED = "downloaded"
    # A package was installed, e.g. pip `Successfully installed`, which may come from a cache.
    INSTALLED = "installed"
    # A line of only a 3-digit number, which is a status code only if e.g. `curl -w "%{http_code}"` printed it.
    BARE_STATUS_CODE = "bare_status_code"


class PrintingProgram(StrEnum):
    """Name that an output line pattern gives to what prints its line, compared with what the run of a request can print to tell whether the line can be its own."""

    PIP = "pip"
    PIP_INDEX = "pip_index"  # pip run as `pip index versions`
    UV = "uv"
    NPM = "npm"
    APT = "apt"
    GIT = "git"
    CURL = "curl"
    WGET = "wget"
    PLAYWRIGHT = "playwright"
    HTTP_HEADERS = "http_headers"  # a run that prints response headers, e.g. `curl -i`
    HTTP_FAILURE = "http_failure"  # a run that prints an HTTP failure line
    CODE = "code"  # Python or JavaScript code


@dataclass(frozen=True, slots=True)
class OutputLineMeaning:
    """Answer of `NetworkRequestResultKnowledge` for one output line that a pattern fits, with the names in the line as it writes them."""

    kind: OutputLineKind
    printing_programs: frozenset[PrintingProgram]
    # Programs outside `printing_programs` print the same line too, e.g. `Connection refused`.
    is_printed_by_other_programs_too: bool
    # None when the line names no host.
    host_name_text: str | None
    # None when the line names no package.
    package_names_text: str | None
    # The program word of a `PROGRAM_MISSING` line, None for other lines.
    missing_program_word: str | None
    # None when the line holds no status code.
    status_code: int | None


@dataclass(frozen=True, slots=True)
class UnknownOutputLineMeaning:
    """Answer of `NetworkRequestResultKnowledge` for an output line that no pattern fits."""


@dataclass(frozen=True, slots=True)
class ProgramOutputLines:
    """Answer of `NetworkRequestResultKnowledge` about the lines that one run of a program prints."""

    printing_programs: frozenset[PrintingProgram]
    prints_status_code: bool  # e.g. `curl -w "%{http_code}"`


@dataclass(frozen=True, slots=True)
class UnknownProgramOutputLines:
    """Answer of `NetworkRequestResultKnowledge` for a program run without a row, or with an option without a row, in the output line catalog."""


class ProgramExitCodeMeaning(StrEnum):
    """Answer of `NetworkRequestResultKnowledge` about what an exit code of a program run says of its request."""

    NOTHING = "nothing"  # it ends with this code without the network too
    SERVER_ANSWERED = "server_answered"
    REQUEST_SUCCEEDED = "request_succeeded"


@dataclass(frozen=True, slots=True)
class UnknownProgramExitCodeMeaning:
    """Answer of `NetworkRequestResultKnowledge` for a program run and exit code without a row in the exit code catalog."""


@dataclass(frozen=True, slots=True)
class ToolOutputLine:
    """Line of a call's `tool_output_text`, returned by `parse_tool_output_text`."""

    # The 0-based index of the line in the text split at "\n".
    line_index: int
    # The 0-based index in the `output` string of the JSON object that the line holds, None when it holds none.
    line_index_in_json_string: int | None
    # The line split at "\r", the last part first, since the last part is what a terminal still shows.
    parts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnreadablePackageNamesText:
    """Result of `parse_package_names_text` for a text that holds no word or a word without a package name, e.g. `==2.0`."""


@dataclass(frozen=True, slots=True)
class OutputPlaceSourceCommands:
    """Commands of one call whose output reaches an output place."""

    tool_call_key: ToolCallKey
    command_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class OutputPlaceSources:
    """Result of one call seen as an output place, with every run whose output reaches it, collected from the `OutputPlace`s and written files of all calls."""

    showing_tool_call_key: ToolCallKey
    source_commands: tuple[OutputPlaceSourceCommands, ...]
    # The result also shows the content of a file, e.g. after `cat notes.md`, so a line in it need not be a trace.
    may_show_file_content: bool
    # The result also shows page text of a web step of a tool script.
    may_show_page_text: bool
    is_web_tool_result: bool


@dataclass(frozen=True, slots=True)
class OutputLineWithMeaning:
    """Output line of a result that a pattern fits, with its place and its meaning."""

    showing_tool_call_key: ToolCallKey
    line_index: int  # 0-based in the text split at "\n"
    line_index_in_json_string: int | None
    output_line_meaning: OutputLineMeaning


@dataclass(frozen=True, slots=True)
class OutputLineOwners:
    """Output line with the requests that can have printed it, chosen among the requests whose output reaches its place."""

    output_line_with_meaning: OutputLineWithMeaning
    # Empty when no request owns the line.
    owner_network_requests: tuple[NetworkRequest, ...]
    # The line names a host or package that none of the owners names, e.g. `Downloading B` under `pip install A`.
    names_another_target: bool


@dataclass(frozen=True, slots=True)
class EvidenceWithLevel:
    """Evidence of one request with the level and stop reason that it shows, kept inside `decide_network_request_results` until the evidence of the request is combined."""

    evidence: NetworkRequestResultEvidence
    level: NetworkRequestResultLevel
    stop_reason: NetworkRequestResultStopReason | None
    # Every reason that a result that rests on this evidence is assumed, empty for evidence of this request alone that no judgment rule gave.
    assumption_reasons: tuple[NetworkRequestResultAssumptionReason, ...]

    @property
    def may_belong_to_another_request(self) -> bool:
        """Tell whether another request or a run that is not read can have printed the line or caused the evidence, i.e. it has a reason other than a judgment rule."""
        return any(
            not isinstance(assumption_reason, JudgmentRuleAssumptionReason)
            for assumption_reason in self.assumption_reasons
        )

    @property
    def rests_on_judgment_rule(self) -> bool:
        """Tell whether a judgment rule gave the level or stop reason."""
        return any(
            isinstance(assumption_reason, JudgmentRuleAssumptionReason)
            for assumption_reason in self.assumption_reasons
        )


class UnusedOutputLineReason(StrEnum):
    """Reason an output line that a pattern fits gave no evidence, counted for tracking and never written into a result."""

    # The result is no output place, e.g. the result of a plan tool.
    NOT_AN_OUTPUT_PLACE = "not_an_output_place"
    # The result shows the content of a file.
    FILE_CONTENT = "file_content"
    # The result shows page text of a web step.
    PAGE_TEXT = "page_text"
    # Every run that reaches the place is read and no request owns the line, e.g. the result of `ls`.
    NO_UNKNOWN_RUN = "no_unknown_run"
    # The missing program is the program of a command that has no request, e.g. `rg: command not found`.
    MISSING_PROGRAM_OF_COMMAND_WITHOUT_REQUEST = (
        "missing_program_of_command_without_request"
    )
    # No request owns the line and a run whose content or program is unknown reaches the place, e.g. `Downloading torch-2.3.0.whl` in the result of `./setup.sh`. No request is made from it.
    UNOWNED_LINE_IN_UNKNOWN_RUN = "unowned_line_in_unknown_run"
    # The line is a bare number and the run prints no status code.
    STATUS_CODE_NOT_PRINTED_BY_RUN = "status_code_not_printed_by_run"
