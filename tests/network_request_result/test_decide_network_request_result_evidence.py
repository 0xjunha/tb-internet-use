"""Tests for _decide_network_request_result_evidence.py, with made-up calls, places, line owners and requests of one trial, lines read by the real `NetworkRequestResultKnowledge` and the real catalogs."""

import csv
import dataclasses
import shutil
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    CodeLanguage,
    CommandTextStatus,
    ExpandedToolCall,
    FileText,
    FileUse,
    FileUseKind,
    FileWriteChannel,
    PollInputText,
    ProgramInvocation,
    ProgramOption,
    RanCommand,
    RanShellText,
    RanTextSource,
    ScriptStepText,
    ShellTextSource,
    UnknownExitsWithExitCodeOfNextProgram,
    UnknownProgramInvocation,
    WrittenFile,
    WrittenFileWriter,
)
from tb_internet_use.knowledge.network_request_result_knowledge import (
    NETWORK_REQUEST_RESULT_CATALOGS_DIR,
    PROGRAM_EXIT_CODES_CSV,
    NetworkRequestResultKnowledge,
)
from tb_internet_use.network_request.model import (
    ContentSaved,
    ContentShownInResult,
    FromCode,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestSource,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoContentRequested,
    ReceivedContentDestination,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetReason,
)
from tb_internet_use.network_request_result import judgment_rules
from tb_internet_use.network_request_result._decide_network_request_result_evidence import (
    decide_network_request_result_evidence,
)
from tb_internet_use.network_request_result.model import (
    EvidenceWithLevel,
    ExecutionStatusEvidence,
    ExitCodeEvidence,
    FileUseEvidence,
    HttpStatusEvidence,
    JudgmentRuleAssumptionReason,
    MissingProgramOfAnotherCommandAssumptionReason,
    NetworkRequestResultAssumptionReason,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
    OutputLineMeaning,
    OutputLineOwners,
    OutputLineWithMeaning,
    OutputPlaceSourceCommands,
    OutputPlaceSources,
    SharedFileUseAssumptionReason,
    SharedHttpStatusAssumptionReason,
    SharedOutputLineAssumptionReason,
    ShownContentEvidence,
    UnknownProgramOutputLinesAssumptionReason,
    UnknownRunBesideAssumptionReason,
)
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    ExitOutcome,
    HarnessTool,
    HarnessToolCall,
    RunCommandAction,
    RunCondition,
    RunToolScriptAction,
    ShellCommand,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    WebFetchAction,
    WebSearchAction,
)

ATTEMPTED = NetworkRequestResultLevel.ATTEMPTED
EXECUTED = NetworkRequestResultLevel.EXECUTED
REACHED = NetworkRequestResultLevel.REACHED
RECEIVED = NetworkRequestResultLevel.RECEIVED
FAILED = NetworkRequestResultStopReason.FAILED
NOT_VISIBLE = NetworkRequestResultStopReason.NOT_VISIBLE
NOT_NEEDED = NetworkRequestResultStopReason.NOT_NEEDED
FINISHED = ExecutionStatus.FINISHED
K = OutputLineKind
URL = NetworkRequestTargetKind.URL
PACKAGE_NAME = NetworkRequestTargetKind.PACKAGE_NAME
COMMAND = RunCommandAction("x")
CALL_COMMAND_TEXT = CallCommandText()
WEB_FETCH_ACTION = WebFetchAction(("https://a.org/x",))
SHOWN_IN_RESULT = ContentShownInResult()

RULE_1 = judgment_rules.treat_exit_code_meaning_as_assumed_level.__name__
RULE_2 = judgment_rules.treat_installed_line_as_no_evidence_of_download.__name__
RULE_23 = (
    judgment_rules.treat_pip_or_apt_installed_line_of_named_package_as_received.__name__
)
RULE_24 = judgment_rules.treat_apt_download_and_install_lines_shared_by_requests_of_several_commands_as_received.__name__
RULE_25 = judgment_rules.treat_pip_saved_line_of_named_package_as_received.__name__
RULE_3 = judgment_rules.treat_version_notice_line_as_no_evidence_of_answer.__name__
RULE_4 = judgment_rules.treat_shown_result_text_as_assumed_content.__name__
RULE_5 = (
    judgment_rules.treat_size_or_type_of_saved_file_as_no_evidence_of_content.__name__
)
RULE_7 = judgment_rules.treat_web_tool_call_without_result_text_as_no_evidence_of_answer.__name__
RULE_10 = (
    judgment_rules.treat_line_naming_another_target_as_no_evidence_of_answer.__name__
)
RULE_11 = (
    judgment_rules.treat_command_without_own_evidence_as_no_evidence_of_run.__name__
)
RULE_13 = (
    judgment_rules.treat_line_beside_shown_file_or_page_text_as_not_a_trace.__name__
)
RULE_14 = judgment_rules.treat_file_use_that_may_not_have_happened_as_assumed_evidence.__name__
RULE_15 = judgment_rules.treat_failure_before_server_as_stopping_next_command.__name__
RULE_16 = judgment_rules.treat_tls_or_proxy_failure_as_before_server_answer.__name__
RULE_18 = judgment_rules.treat_shown_content_of_saved_file_as_assumed_content.__name__
RULE_19 = judgment_rules.treat_connected_line_as_assumed_server_answer.__name__
RULE_20 = (
    judgment_rules.treat_line_that_unknown_printer_may_have_printed_as_shared.__name__
)
RULE_21 = judgment_rules.treat_already_present_line_without_matching_target_as_assumed_not_needed.__name__
RULE_22 = judgment_rules.treat_lost_connection_as_after_server_answer.__name__


def key_of(step_id: int) -> ToolCallKey:
    return ToolCallKey("trial", "main", step_id, 0)


K1, K2, K3 = key_of(1), key_of(2), key_of(3)


def program(
    program_name: str,
    *subcommand_words: str,
    options: tuple[ProgramOption, ...] = (),
    unread_words: tuple[str, ...] = (),
    exits_with_exit_code_of_next_program: bool
    | UnknownExitsWithExitCodeOfNextProgram = False,
) -> ProgramInvocation:
    return ProgramInvocation(
        program_name=program_name,
        subcommand_words=subcommand_words,
        options=options,
        arguments=(),
        gets_more_arguments_at_run_time=False,
        unread_words=unread_words,
        exits_with_exit_code_of_next_program=exits_with_exit_code_of_next_program,
    )


def option(name: str, value: str | None = None) -> ProgramOption:
    return ProgramOption(name, value)


CURL = program("curl")
PIP_INSTALL = program("pip", "install")


def command(
    command_id: int,
    words: str,
    *program_invocations: ProgramInvocation | UnknownProgramInvocation,
    runs_if: tuple[RunCondition, ...] = (),
    succeeded_if_text_exits_zero: bool = True,
    structure_may_be_wrong: bool = False,
    in_function_body: bool = False,
    in_case_branch: bool = False,
) -> RanCommand:
    """Make a command, marked by `succeeded_if_text_exits_zero` unless told otherwise, as the one command or the last of a text is."""
    return RanCommand(
        shell_command=ShellCommand(
            command_id,
            tuple(words.split()),
            runs_if=runs_if,
            succeeded_if_text_exits_zero=succeeded_if_text_exits_zero,
            structure_may_be_wrong=structure_may_be_wrong,
            in_function_body=in_function_body,
            in_case_branch=in_case_branch,
        ),
        program_invocations=program_invocations,
        variable_values=(),
        stdout_routes=(),
        stderr_routes=(),
    )


def after_success_of(*deciding_command_ids: int) -> tuple[RunCondition, ...]:
    return (RunCondition(deciding_command_ids, ExitOutcome.SUCCESS),)


def call(
    tool_call_key: ToolCallKey,
    *ran_commands: RanCommand,
    execution_status: ExecutionStatus = FINISHED,
    exit_code: int | None = None,
    http_status: int | None = None,
    tool_output_text: str | None = "",
    ran_text_source: ShellTextSource = CALL_COMMAND_TEXT,
    written_files: tuple[WrittenFile, ...] = (),
    action: ToolCallAction = COMMAND,
) -> ExpandedToolCall:
    """Make a call of a command text, or of another action when `action` says so, whose command text status is that of its result."""
    is_command_text = isinstance(action, RunCommandAction)
    return ExpandedToolCall(
        tool_call=ToolCall(
            HarnessToolCall(tool_call_key, HarnessTool("h", "t"), "", {}, None),
            action,
            ToolCallResult(
                tool_output_text=tool_output_text,
                execution_status=execution_status,
                exit_code=exit_code,
                http_status=http_status,
            ),
        ),
        ran_texts=(RanShellText(ran_text_source, ran_commands),)
        if ran_commands
        else (),
        command_text_status=CommandTextStatus(
            execution_status, exit_code, tool_call_key
        )
        if is_command_text
        else None,
        output_places=(),
        written_files=written_files,
        file_uses_without_known_writer=(),
    )


def web_call(
    tool_call_key: ToolCallKey,
    *,
    tool_output_text: str | None = None,
    http_status: int | None = None,
    execution_status: ExecutionStatus = FINISHED,
    action: ToolCallAction = WEB_FETCH_ACTION,
) -> ExpandedToolCall:
    return ExpandedToolCall(
        tool_call=ToolCall(
            HarnessToolCall(tool_call_key, HarnessTool("h", "web"), "", {}, None),
            action,
            ToolCallResult(
                tool_output_text=tool_output_text,
                execution_status=execution_status,
                http_status=http_status,
            ),
        ),
        ran_texts=(),
        command_text_status=None,
        output_places=(),
        written_files=(),
        file_uses_without_known_writer=(),
    )


def request(
    tool_call_key: ToolCallKey,
    source: NetworkRequestSource,
    target: str | UnknownNetworkRequestTarget | None = None,
    *,
    target_kind: NetworkRequestTargetKind = URL,
    received_content_destination: ReceivedContentDestination = SHOWN_IN_RESULT,
    index_in_tool_call: int = 0,
    uncertainty_reason: NetworkRequestUncertaintyReason | None = None,
) -> NetworkRequest:
    """Make a request, uncertain for a program that no fact covers as `NetworkRequest` requires, or with `uncertainty_reason`, and confirmed otherwise."""
    if (
        uncertainty_reason is None
        and isinstance(source, FromCommand)
        and isinstance(source.program_invocation, UnknownProgramInvocation)
    ):
        uncertainty_reason = NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM
    return NetworkRequest(
        tool_call_key=tool_call_key,
        index_in_tool_call=index_in_tool_call,
        source=source,
        target=target,
        target_kind=target_kind,
        host_names=(),
        received_content_destination=received_content_destination,
        certainty=NetworkRequestCertainty.CONFIRMED
        if uncertainty_reason is None
        else NetworkRequestCertainty.UNCERTAIN,
        uncertainty_reason=uncertainty_reason,
    )


def from_command(
    ran_command: RanCommand,
    program_index: int = -1,
    *,
    ran_text_source: RanTextSource = CALL_COMMAND_TEXT,
) -> FromCommand:
    return FromCommand(
        ran_command.shell_command.id,
        ran_text_source,
        ran_command.program_invocations[program_index],
    )


def from_code(runner_command_id: int | None) -> FromCode:
    return FromCode(
        runner_command_id,
        PollInputText(None, K1),
        CodeLanguage.PYTHON,
        "requests.get",
    )


def from_web_tool(step_index: int | None = None) -> FromWebTool:
    return FromWebTool(step_index, HarnessTool("h", "web"))


def place(
    showing_tool_call_key: ToolCallKey,
    *source_commands: tuple[ToolCallKey, tuple[int, ...]],
    may_show_file_content: bool = False,
    may_show_page_text: bool = False,
    is_web_tool_result: bool = False,
) -> OutputPlaceSources:
    return OutputPlaceSources(
        showing_tool_call_key=showing_tool_call_key,
        source_commands=tuple(
            OutputPlaceSourceCommands(tool_call_key, command_ids)
            for tool_call_key, command_ids in source_commands
        ),
        may_show_file_content=may_show_file_content,
        may_show_page_text=may_show_page_text,
        is_web_tool_result=is_web_tool_result,
    )


def owned(
    showing_tool_call_key: ToolCallKey,
    line: str,
    *owner_network_requests: NetworkRequest,
    line_index: int = 0,
    names_another_target: bool = False,
    is_web_tool_result: bool = False,
) -> OutputLineOwners:
    """Make the owners of a line read with a `NetworkRequestResultKnowledge` of its own, so that the one under test counts nothing for it."""
    output_line_meaning = NetworkRequestResultKnowledge().output_line_meaning(
        line, is_web_tool_result=is_web_tool_result
    )
    assert isinstance(output_line_meaning, OutputLineMeaning), line
    return OutputLineOwners(
        OutputLineWithMeaning(
            showing_tool_call_key, line_index, None, output_line_meaning
        ),
        owner_network_requests,
        names_another_target,
    )


def line_evidence(
    kind: OutputLineKind,
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason | None,
    *,
    showing_tool_call_key: ToolCallKey = K1,
    line_index: int = 0,
    is_shared_with_other_requests: bool = False,
    may_belong_to_another_request_reason: NetworkRequestResultAssumptionReason
    | None = None,
    rests_on_judgment_rule: bool = False,
) -> EvidenceWithLevel:
    return EvidenceWithLevel(
        OutputLineEvidence(
            showing_tool_call_key,
            line_index,
            None,
            kind,
            is_shared_with_other_requests,
        ),
        level,
        stop_reason,
        assumption_reasons_from(
            may_belong_to_another_request_reason,
            rests_on_judgment_rule=rests_on_judgment_rule,
        ),
    )


def assumption_reasons_from(
    may_belong_to_another_request_reason: NetworkRequestResultAssumptionReason | None,
    *,
    rests_on_judgment_rule: bool,
) -> tuple[NetworkRequestResultAssumptionReason, ...]:
    return (
        *(
            ()
            if may_belong_to_another_request_reason is None
            else (may_belong_to_another_request_reason,)
        ),
        *((JudgmentRuleAssumptionReason(),) if rests_on_judgment_rule else ()),
    )


# The reason of a line at index 0 of the result of call K1 that other requests own too.
SHARED_LINE_REASON = SharedOutputLineAssumptionReason(K1, 0, None)


def exit_zero_evidence(
    level: NetworkRequestResultLevel = EXECUTED,
    stop_reason: NetworkRequestResultStopReason | None = NOT_VISIBLE,
    *,
    reporter_tool_call_key: ToolCallKey = K1,
    is_shared_with_other_requests: bool = False,
    rests_on_judgment_rule: bool = False,
) -> EvidenceWithLevel:
    return EvidenceWithLevel(
        ExitCodeEvidence(reporter_tool_call_key, 0, is_shared_with_other_requests),
        level,
        stop_reason,
        assumption_reasons_from(None, rests_on_judgment_rule=rests_on_judgment_rule),
    )


def status_evidence(
    execution_status: ExecutionStatus,
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason | None,
    *,
    reporter_tool_call_key: ToolCallKey = K1,
    is_shared_with_other_requests: bool = False,
    rests_on_judgment_rule: bool = False,
) -> EvidenceWithLevel:
    return EvidenceWithLevel(
        ExecutionStatusEvidence(
            reporter_tool_call_key, execution_status, is_shared_with_other_requests
        ),
        level,
        stop_reason,
        assumption_reasons_from(None, rests_on_judgment_rule=rests_on_judgment_rule),
    )


def file_use_evidence(
    file_use: FileUse,
    *,
    is_written_by_another_request: bool = False,
    rests_on_judgment_rule: bool = False,
) -> EvidenceWithLevel:
    return EvidenceWithLevel(
        FileUseEvidence(file_use),
        RECEIVED,
        None,
        assumption_reasons_from(
            SharedFileUseAssumptionReason() if is_written_by_another_request else None,
            rests_on_judgment_rule=rests_on_judgment_rule,
        ),
    )


def shown_content_evidence(
    showing_tool_call_key: ToolCallKey = K1,
) -> EvidenceWithLevel:
    return EvidenceWithLevel(
        ShownContentEvidence(showing_tool_call_key),
        RECEIVED,
        None,
        (JudgmentRuleAssumptionReason(),),
    )


@dataclass(frozen=True)
class Decided:
    evidence_with_levels: tuple[EvidenceWithLevel, ...]
    judgment_rule_use_counts: Counter[str]
    knowledge: NetworkRequestResultKnowledge


def decide(
    network_request: NetworkRequest,
    expanded_tool_calls: list[ExpandedToolCall],
    *,
    network_requests: list[NetworkRequest] | None = None,
    places: tuple[OutputPlaceSources, ...] = (),
    output_line_owners: tuple[OutputLineOwners, ...] = (),
    knowledge: NetworkRequestResultKnowledge | None = None,
) -> Decided:
    """Decide the evidence of one request, with the trial's requests being that one alone unless given."""
    judgment_rule_use_counts: Counter[str] = Counter()
    knowledge = knowledge or NetworkRequestResultKnowledge()
    evidence_with_levels = decide_network_request_result_evidence(
        network_request,
        network_requests if network_requests is not None else [network_request],
        expanded_tool_calls,
        places,
        output_line_owners,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    return Decided(evidence_with_levels, judgment_rule_use_counts, knowledge)


def answer_false(
    monkeypatch: pytest.MonkeyPatch, rule_name: str
) -> Callable[..., bool]:
    """Make a rule answer False while it still counts its use, so the other answer of each rule can be tested."""

    def rule_answering_false(*_: object, use_counts: Counter[str]) -> bool:
        use_counts[rule_name] += 1
        return False

    monkeypatch.setattr(judgment_rules, rule_name, rule_answering_false)
    return rule_answering_false


def exit_code_unknown_inputs(knowledge: NetworkRequestResultKnowledge) -> Counter:
    return Counter(
        {
            key: count
            for key, count in knowledge.uses.unknown_input_counts.items()
            if key[0] == PROGRAM_EXIT_CODES_CSV
        }
    )


@dataclass(frozen=True)
class LineCase:
    line: str
    program_invocation: ProgramInvocation
    words: str
    expected: EvidenceWithLevel
    rule_names: tuple[str, ...] = ()
    target: str | UnknownNetworkRequestTarget | None = None
    target_kind: NetworkRequestTargetKind = URL
    received_content_destination: ReceivedContentDestination = SHOWN_IN_RESULT


NAMED_IN_FILE = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.NAMED_IN_FILE
)

# Lines of every kind, each owned by the one request of `words`, with the evidence it gives and the rules it asks besides the one about the run.
LINE_CASES = {
    "wget saved": LineCase(
        "'x.tgz' saved [1024/1024]",
        program("wget"),
        "wget https://a.org/x.tgz",
        line_evidence(K.DOWNLOADED, RECEIVED, None),
        received_content_destination=ContentSaved("x.tgz"),
    ),
    "downloaded for a request that asks for no content": LineCase(
        "'x.tgz' saved [1024/1024]",
        program("wget"),
        "wget --spider https://a.org/x.tgz",
        line_evidence(K.DOWNLOADED, REACHED, None),
        received_content_destination=NoContentRequested(),
    ),
    "http 404": LineCase(
        "HTTP/1.1 404 Not Found",
        program("curl", options=(option("-i"),)),
        "curl -i https://a.org/x",
        line_evidence(K.HTTP_STATUS, REACHED, FAILED),
    ),
    "http 200": LineCase(
        "HTTP/1.1 200 OK",
        program("curl", options=(option("-i"),)),
        "curl -i https://a.org/x",
        line_evidence(K.HTTP_STATUS, REACHED, NOT_VISIBLE),
    ),
    "http 200 for a request that asks for no content": LineCase(
        "HTTP/1.1 200 OK",
        program("curl", options=(option("-I"),)),
        "curl -I https://a.org",
        line_evidence(K.HTTP_STATUS, REACHED, None),
        received_content_destination=NoContentRequested(),
    ),
    "name not resolved": LineCase(
        "curl: (6) Could not resolve host: a.org",
        CURL,
        "curl https://a.org/x",
        line_evidence(K.NAME_NOT_RESOLVED, EXECUTED, FAILED),
    ),
    "connection failed": LineCase(
        "curl: (7) Failed to connect to a.org port 443: Connection refused",
        CURL,
        "curl https://a.org/x",
        line_evidence(K.CONNECTION_FAILED, EXECUTED, FAILED),
    ),
    "refused locally": LineCase(
        "error: externally-managed-environment",
        PIP_INSTALL,
        "pip install x",
        line_evidence(K.REFUSED_LOCALLY, EXECUTED, FAILED),
        target="x",
        target_kind=PACKAGE_NAME,
    ),
    "program missing": LineCase(
        "bash: pip3: command not found",
        PIP_INSTALL,
        "pip3 install requests",
        line_evidence(K.PROGRAM_MISSING, ATTEMPTED, FAILED),
        target="requests",
        target_kind=PACKAGE_NAME,
    ),
    "connected": LineCase(
        "* Connected to a.org (1.2.3.4) port 443",
        program("curl", options=(option("-v"),)),
        "curl -v https://a.org/x",
        line_evidence(K.CONNECTED, REACHED, NOT_VISIBLE, rests_on_judgment_rule=True),
        (RULE_19,),
    ),
    "already present with the target's name": LineCase(
        "Requirement already satisfied: requests in /usr/lib",
        PIP_INSTALL,
        "pip install requests",
        line_evidence(K.ALREADY_PRESENT, EXECUTED, NOT_NEEDED),
        target="requests",
        target_kind=PACKAGE_NAME,
    ),
    "already present for a request without a target": LineCase(
        "Requirement already satisfied: x in /usr/lib",
        PIP_INSTALL,
        "pip install -r reqs.txt",
        line_evidence(
            K.ALREADY_PRESENT, EXECUTED, NOT_NEEDED, rests_on_judgment_rule=True
        ),
        (RULE_21,),
        target=NAMED_IN_FILE,
        target_kind=PACKAGE_NAME,
    ),
    "already present on a line without a name": LineCase(
        "Audited 3 packages in 5ms",
        program("uv", "pip", "install"),
        "uv pip install x",
        line_evidence(
            K.ALREADY_PRESENT, EXECUTED, NOT_NEEDED, rests_on_judgment_rule=True
        ),
        (RULE_21,),
        target="x",
        target_kind=PACKAGE_NAME,
    ),
    "installed": LineCase(
        "Successfully installed A-1.0",
        PIP_INSTALL,
        "pip install A",
        line_evidence(K.INSTALLED, RECEIVED, None),
        (RULE_23,),
        target="A",
        target_kind=PACKAGE_NAME,
    ),
    "apt installed": LineCase(
        "Setting up curl (7.88.1-10+deb12u8) ...",
        program("apt-get", "install"),
        "apt-get install -y curl",
        line_evidence(K.INSTALLED, RECEIVED, None),
        (RULE_23,),
        target="curl",
        target_kind=PACKAGE_NAME,
    ),
    "installed from a local path": LineCase(
        "Successfully installed app-0.1",
        PIP_INSTALL,
        "pip install -e /app",
        line_evidence(K.INSTALLED, EXECUTED, NOT_VISIBLE),
        (RULE_2,),
        target=UnknownNetworkRequestTarget(
            UnknownNetworkRequestTargetReason.LOCAL_PATH
        ),
        target_kind=PACKAGE_NAME,
    ),
    "uv installed": LineCase(
        " + x==1.0",
        program("uv", "pip", "install"),
        "uv pip install x",
        line_evidence(K.INSTALLED, EXECUTED, NOT_VISIBLE),
        (RULE_2,),
        target="x",
        target_kind=PACKAGE_NAME,
    ),
    "version notice": LineCase(
        "[notice] A new release of pip is available: 23.0 -> 24.0",
        PIP_INSTALL,
        "pip install x",
        line_evidence(K.VERSION_NOTICE, EXECUTED, NOT_VISIBLE),
        (RULE_3,),
        target="x",
        target_kind=PACKAGE_NAME,
    ),
    # The file may come from the cache of pip, so without a download line the line shows only the run. Its name is spelled another way than the target and asks no rule about another target.
    "saved package file with the name spelled another way": LineCase(
        "Successfully downloaded pyyaml-6.0",
        program("pip", "download"),
        "pip download PyYAML",
        line_evidence(K.PACKAGE_FILE_IN_FOLDER, EXECUTED, NOT_VISIBLE),
        target="PyYAML",
        target_kind=PACKAGE_NAME,
    ),
    # pip prints this only for a file new to the destination folder. Its name is spelled another way than the target and still names it.
    "pip saved package file of the target": LineCase(
        "Saved ./dl/typing_extensions-4.12.2-py3-none-any.whl",
        program("pip", "download"),
        "pip download typing-extensions -d dl",
        line_evidence(K.PACKAGE_FILE_ADDED_TO_FOLDER, RECEIVED, None),
        (RULE_25,),
        target="typing-extensions",
        target_kind=PACKAGE_NAME,
    ),
    # A file of another package, e.g. a dependency, shows only the run of the request, even when the line is taken as its own.
    "pip saved package file of another package": LineCase(
        "Saved ./dl/idna-3.7-py3-none-any.whl",
        program("pip", "download"),
        "pip download requests -d dl",
        line_evidence(K.PACKAGE_FILE_ADDED_TO_FOLDER, EXECUTED, NOT_VISIBLE),
        target="requests",
        target_kind=PACKAGE_NAME,
    ),
    # npm prints this also when it asked no server.
    "program ran": LineCase(
        "up to date, audited 1 package in 120ms",
        program("npm", "install"),
        "npm install x",
        line_evidence(K.PROGRAM_RAN, EXECUTED, NOT_VISIBLE),
        target="x",
        target_kind=PACKAGE_NAME,
    ),
    "server answered": LineCase(
        "Hit:1 http://archive.ubuntu.com/ubuntu jammy InRelease",
        program("apt-get", "update"),
        "apt-get update",
        line_evidence(K.SERVER_ANSWERED, REACHED, NOT_VISIBLE),
    ),
    "download started": LineCase(
        "Downloading x-1.0-py3-none-any.whl (10 kB)",
        PIP_INSTALL,
        "pip install x",
        line_evidence(K.DOWNLOAD_STARTED, REACHED, NOT_VISIBLE),
        target="x",
        target_kind=PACKAGE_NAME,
    ),
    "not found": LineCase(
        "ERROR: No matching distribution found for x",
        PIP_INSTALL,
        "pip install x",
        line_evidence(K.NOT_FOUND, EXECUTED, FAILED),
        target="x",
        target_kind=PACKAGE_NAME,
    ),
    "bare status code 200": LineCase(
        "200",
        program("curl", options=(option("-w", "%{http_code}"),)),
        "curl -s -o /dev/null -w %{http_code} https://a.org/x",
        line_evidence(K.BARE_STATUS_CODE, REACHED, NOT_VISIBLE),
    ),
    "bare status code 404": LineCase(
        "404",
        program("curl", options=(option("-w", "%{http_code}"),)),
        "curl -s -o /dev/null -w %{http_code} https://a.org/x",
        line_evidence(K.BARE_STATUS_CODE, REACHED, FAILED),
    ),
    "bare status code 000": LineCase(
        "000",
        program("curl", options=(option("-w", "%{http_code}"),)),
        "curl -s -o /dev/null -w %{http_code} https://a.org/x",
        line_evidence(K.BARE_STATUS_CODE, EXECUTED, FAILED),
    ),
    "tls failed": LineCase(
        "curl: (60) SSL certificate problem: unable to get local issuer certificate",
        CURL,
        "curl https://a.org/x",
        line_evidence(K.TLS_FAILED, EXECUTED, FAILED, rests_on_judgment_rule=True),
        (RULE_16,),
    ),
    "proxy refused": LineCase(
        "requests.exceptions.ProxyError: HTTPSConnectionPool(host='a.org')",
        PIP_INSTALL,
        "pip install x",
        line_evidence(K.PROXY_REFUSED, EXECUTED, FAILED, rests_on_judgment_rule=True),
        (RULE_16,),
        target="x",
        target_kind=PACKAGE_NAME,
    ),
    "connection lost": LineCase(
        "ConnectionResetError: [Errno 104] Connection reset by peer",
        PIP_INSTALL,
        "pip install x",
        line_evidence(K.CONNECTION_LOST, REACHED, FAILED, rests_on_judgment_rule=True),
        (RULE_22,),
        target="x",
        target_kind=PACKAGE_NAME,
    ),
}


def line_case_request(line_case: LineCase) -> tuple[NetworkRequest, ExpandedToolCall]:
    ran_command = command(0, line_case.words, line_case.program_invocation)
    network_request = request(
        K1,
        from_command(ran_command),
        line_case.target,
        target_kind=line_case.target_kind,
        received_content_destination=line_case.received_content_destination,
    )
    return network_request, call(K1, ran_command)


# --- Lines of a request ---


@pytest.mark.parametrize("line_case", LINE_CASES.values(), ids=LINE_CASES.keys())
def test_line_that_a_request_owns_gives_the_level_of_its_kind(line_case: LineCase):
    network_request, expanded_tool_call = line_case_request(line_case)
    decided = decide(
        network_request,
        [expanded_tool_call],
        places=(place(K1, (K1, (0,))),),
        output_line_owners=(owned(K1, line_case.line, network_request),),
    )
    assert decided.evidence_with_levels == (line_case.expected,)
    assert decided.judgment_rule_use_counts == Counter(
        {**dict.fromkeys(line_case.rule_names, 1), RULE_11: 1}
    )


@pytest.mark.parametrize(
    ("case_name", "rule_name", "level", "stop_reason", "rests_on_judgment_rule"),
    [
        ("installed", RULE_23, EXECUTED, NOT_VISIBLE, False),
        ("pip saved package file of the target", RULE_25, EXECUTED, NOT_VISIBLE, False),
        ("uv installed", RULE_2, RECEIVED, None, True),
        ("version notice", RULE_3, REACHED, NOT_VISIBLE, True),
        ("tls failed", RULE_16, REACHED, FAILED, True),
        ("connected", RULE_19, EXECUTED, NOT_VISIBLE, False),
        (
            "already present for a request without a target",
            RULE_21,
            EXECUTED,
            NOT_VISIBLE,
            False,
        ),
        ("connection lost", RULE_22, EXECUTED, FAILED, True),
    ],
)
def test_other_answer_of_a_rule_about_a_line_gives_its_other_level(
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
    rule_name: str,
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason | None,
    rests_on_judgment_rule: bool,
):
    answer_false(monkeypatch, rule_name)
    line_case = LINE_CASES[case_name]
    network_request, expanded_tool_call = line_case_request(line_case)
    decided = decide(
        network_request,
        [expanded_tool_call],
        places=(place(K1, (K1, (0,))),),
        output_line_owners=(owned(K1, line_case.line, network_request),),
    )
    [evidence_with_level] = decided.evidence_with_levels
    assert (
        evidence_with_level.level,
        evidence_with_level.stop_reason,
        evidence_with_level.rests_on_judgment_rule,
    ) == (level, stop_reason, rests_on_judgment_rule)
    assert decided.judgment_rule_use_counts == Counter({rule_name: 1, RULE_11: 1})


def pip_install_a_with_line_naming_b() -> tuple[
    NetworkRequest, ExpandedToolCall, OutputLineOwners
]:
    ran_command = command(0, "pip install A", PIP_INSTALL)
    network_request = request(
        K1, from_command(ran_command), "A", target_kind=PACKAGE_NAME
    )
    return (
        network_request,
        call(K1, ran_command),
        owned(K1, "Downloading B-1.0.whl", network_request, names_another_target=True),
    )


def test_line_naming_another_target_shows_only_the_run():
    network_request, expanded_tool_call, output_line_owners = (
        pip_install_a_with_line_naming_b()
    )
    decided = decide(
        network_request,
        [expanded_tool_call],
        places=(place(K1, (K1, (0,))),),
        output_line_owners=(output_line_owners,),
    )
    assert decided.evidence_with_levels == (
        line_evidence(K.DOWNLOAD_STARTED, EXECUTED, NOT_VISIBLE),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_10: 1, RULE_11: 1})


def test_line_naming_another_target_taken_as_the_requests_rests_on_the_rule(
    monkeypatch: pytest.MonkeyPatch,
):
    answer_false(monkeypatch, RULE_10)
    network_request, expanded_tool_call, output_line_owners = (
        pip_install_a_with_line_naming_b()
    )
    decided = decide(
        network_request,
        [expanded_tool_call],
        places=(place(K1, (K1, (0,))),),
        output_line_owners=(output_line_owners,),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.DOWNLOAD_STARTED, REACHED, NOT_VISIBLE, rests_on_judgment_rule=True
        ),
    )


@pytest.mark.parametrize("is_taken_as_the_requests", [False, True])
def test_install_line_naming_another_package_asks_the_rule_about_another_target_first(
    monkeypatch: pytest.MonkeyPatch, is_taken_as_the_requests: bool
):
    if is_taken_as_the_requests:
        answer_false(monkeypatch, RULE_10)
    ran_command = command(0, "pip install A", PIP_INSTALL)
    network_request = request(
        K1, from_command(ran_command), "A", target_kind=PACKAGE_NAME
    )
    decided = decide(
        network_request,
        [call(K1, ran_command)],
        places=(place(K1, (K1, (0,))),),
        output_line_owners=(
            owned(
                K1,
                "Successfully installed B-1.0",
                network_request,
                names_another_target=True,
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(K.INSTALLED, RECEIVED, None, rests_on_judgment_rule=True)
        if is_taken_as_the_requests
        else line_evidence(K.INSTALLED, EXECUTED, NOT_VISIBLE),
    )
    assert decided.judgment_rule_use_counts == Counter(
        {RULE_10: 1, RULE_11: 1, **({RULE_23: 1} if is_taken_as_the_requests else {})}
    )


def test_line_that_a_request_does_not_own_gives_it_nothing():
    curl_a = command(
        0, "curl -sS https://a.org/x", CURL, succeeded_if_text_exits_zero=False
    )
    curl_b = command(1, "curl -sS https://b.org/y", CURL)
    network_request_a = request(K1, from_command(curl_a), "https://a.org/x")
    network_request_b = request(
        K1, from_command(curl_b), "https://b.org/y", index_in_tool_call=1
    )
    decided = decide(
        network_request_b,
        [call(K1, curl_a, curl_b)],
        network_requests=[network_request_a, network_request_b],
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(
            owned(K1, "curl: (6) Could not resolve host: a.org", network_request_a),
        ),
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def test_line_of_several_owners_is_shared_without_the_rule_about_unknown_printers():
    curl_a = command(
        0, "curl -sS https://a.org/x", CURL, succeeded_if_text_exits_zero=False
    )
    curl_b = command(1, "curl -sS https://b.org/y", CURL)
    network_request_a = request(K1, from_command(curl_a), "https://a.org/x")
    network_request_b = request(
        K1, from_command(curl_b), "https://b.org/y", index_in_tool_call=1
    )
    decided = decide(
        network_request_a,
        [call(K1, curl_a, curl_b)],
        network_requests=[network_request_a, network_request_b],
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(
            owned(
                K1, "curl: (7) Connection refused", network_request_a, network_request_b
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.CONNECTION_FAILED,
            EXECUTED,
            FAILED,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SHARED_LINE_REASON,
        ),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def test_line_of_several_commands_with_unknown_printers_is_shared_without_the_rule_about_them():
    curl_a = command(
        0,
        "curl -L https://a.org/x",
        program("curl", options=(option("-L"),)),
        succeeded_if_text_exits_zero=False,
    )
    curl_b = command(
        1, "curl -L https://b.org/y", program("curl", options=(option("-L"),))
    )
    network_request_a = request(K1, from_command(curl_a), "https://a.org/x")
    network_request_b = request(
        K1, from_command(curl_b), "https://b.org/y", index_in_tool_call=1
    )
    decided = decide(
        network_request_a,
        [call(K1, curl_a, curl_b)],
        network_requests=[network_request_a, network_request_b],
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(
            owned(
                K1, "curl: (7) Connection refused", network_request_a, network_request_b
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.CONNECTION_FAILED,
            EXECUTED,
            FAILED,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SHARED_LINE_REASON,
        ),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def pip_install_a_b(
    *, in_two_commands: bool
) -> tuple[NetworkRequest, NetworkRequest, ExpandedToolCall, OutputPlaceSources]:
    """Make `pip install a b` with a request for each package, or `pip install a; pip install b` with the two in two commands."""
    if in_two_commands:
        pip_a = command(
            0, "pip install a", PIP_INSTALL, succeeded_if_text_exits_zero=False
        )
        pip_b = command(1, "pip install b", PIP_INSTALL)
        ran_commands = (pip_a, pip_b)
    else:
        pip_a = pip_b = command(0, "pip install a b", PIP_INSTALL)
        ran_commands = (pip_a,)
    network_request_a = request(K1, from_command(pip_a), "a", target_kind=PACKAGE_NAME)
    network_request_b = request(
        K1, from_command(pip_b), "b", target_kind=PACKAGE_NAME, index_in_tool_call=1
    )
    return (
        network_request_a,
        network_request_b,
        call(K1, *ran_commands),
        place(
            K1,
            (K1, tuple(ran_command.shell_command.id for ran_command in ran_commands)),
        ),
    )


@pytest.mark.parametrize(
    ("line", "kind", "level", "stop_reason", "rule_names"),
    [
        ("bash: pip: command not found", K.PROGRAM_MISSING, ATTEMPTED, FAILED, ()),
        (
            "[notice] A new release of pip is available: 23.0 -> 24.0",
            K.VERSION_NOTICE,
            EXECUTED,
            NOT_VISIBLE,
            (RULE_3,),
        ),
    ],
    ids=["missing program", "run without visible output"],
)
def test_line_that_shows_only_a_fact_of_one_command_holds_for_each_of_its_requests(
    line: str,
    kind: OutputLineKind,
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason,
    rule_names: tuple[str, ...],
):
    network_request_a, network_request_b, expanded_tool_call, output_place_sources = (
        pip_install_a_b(in_two_commands=False)
    )
    for network_request in (network_request_a, network_request_b):
        decided = decide(
            network_request,
            [expanded_tool_call],
            network_requests=[network_request_a, network_request_b],
            places=(output_place_sources,),
            output_line_owners=(owned(K1, line, network_request_a, network_request_b),),
        )
        assert decided.evidence_with_levels == (
            line_evidence(kind, level, stop_reason, is_shared_with_other_requests=True),
        )
        assert decided.judgment_rule_use_counts == Counter(
            {RULE_11: 1, **{rule_name: 1 for rule_name in rule_names}}
        )


def test_line_naming_both_packages_of_one_command_is_shared_when_it_shows_more_than_the_run():
    network_request_a, network_request_b, expanded_tool_call, output_place_sources = (
        pip_install_a_b(in_two_commands=False)
    )
    decided = decide(
        network_request_a,
        [expanded_tool_call],
        network_requests=[network_request_a, network_request_b],
        places=(output_place_sources,),
        output_line_owners=(
            owned(
                K1,
                "Successfully installed a-1 b-2",
                network_request_a,
                network_request_b,
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.INSTALLED,
            RECEIVED,
            None,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SHARED_LINE_REASON,
        ),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_23: 1, RULE_11: 1})


def test_line_that_shows_the_run_of_one_of_two_commands_may_belong_to_the_other():
    network_request_a, network_request_b, expanded_tool_call, output_place_sources = (
        pip_install_a_b(in_two_commands=True)
    )
    decided = decide(
        network_request_b,
        [expanded_tool_call],
        network_requests=[network_request_a, network_request_b],
        places=(output_place_sources,),
        output_line_owners=(
            owned(
                K1,
                "[notice] A new release of pip is available: 23.0 -> 24.0",
                network_request_a,
                network_request_b,
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.VERSION_NOTICE,
            EXECUTED,
            NOT_VISIBLE,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SHARED_LINE_REASON,
        ),
    )


def test_line_of_a_kind_that_gives_no_level_raises():
    output_line_owners = owned(K1, "Successfully installed x-1.0")
    made_up_kind = cast(OutputLineKind, "made_up_kind")
    output_line_owners = dataclasses.replace(
        output_line_owners,
        output_line_with_meaning=dataclasses.replace(
            output_line_owners.output_line_with_meaning,
            output_line_meaning=dataclasses.replace(
                output_line_owners.output_line_with_meaning.output_line_meaning,
                kind=made_up_kind,
            ),
        ),
    )
    pip = command(0, "pip install x", PIP_INSTALL)
    network_request = request(K1, from_command(pip), "x", target_kind=PACKAGE_NAME)
    with pytest.raises(ValueError, match="made_up_kind"):
        decide(
            network_request,
            [call(K1, pip)],
            places=(place(K1, (K1, (0,))),),
            output_line_owners=(
                dataclasses.replace(
                    output_line_owners, owner_network_requests=(network_request,)
                ),
            ),
        )


def unknown_printer_case(
    which: str,
) -> tuple[
    NetworkRequest, list[ExpandedToolCall], OutputPlaceSources, OutputLineOwners
]:
    """Make a request whose run has no known lines, or whose line any program prints beside a run that is not read, with the line it owns."""
    if which == "program without a row":
        ran_command = command(
            0,
            "mytool https://a.org/x",
            UnknownProgramInvocation("mytool", ("https://a.org/x",)),
        )
        network_request = request(K1, from_command(ran_command), "https://a.org/x")
        return (
            network_request,
            [call(K1, ran_command)],
            place(K1, (K1, (0,))),
            owned(K1, "HTTP/1.1 200 OK", network_request),
        )
    if which == "option without a row":
        ran_command = command(
            0,
            "curl --bar https://a.org/x",
            program("curl", options=(option("--bar"),)),
        )
        network_request = request(K1, from_command(ran_command), "https://a.org/x")
        return (
            network_request,
            [call(K1, ran_command)],
            place(K1, (K1, (0,))),
            owned(K1, "'x' saved [10/10]", network_request),
        )
    if which == "unread words":
        ran_command = command(
            0,
            "curl --foo x https://a.org/x",
            program("curl", unread_words=("--foo", "x", "https://a.org/x")),
        )
        network_request = request(
            K1,
            from_command(ran_command),
            "https://a.org/x",
            uncertainty_reason=NetworkRequestUncertaintyReason.UNREAD_WORDS,
        )
        return (
            network_request,
            [call(K1, ran_command)],
            place(K1, (K1, (0,))),
            owned(K1, "HTTP/1.1 200 OK", network_request),
        )
    if which == "code typed through a poll":
        network_request = request(K2, from_code(None), "https://a.org/x")
        return (
            network_request,
            [call(K1), call(K2, action=COMMAND)],
            place(K2, (K2, ())),
            owned(
                K2,
                "HTTP/1.1 200 OK",
                network_request,
            ),
        )
    if which == "code run by a program":
        ran_command = command(0, "python get.py", program("python"))
        network_request = request(K1, from_code(0), "https://a.org/x")
        return (
            network_request,
            [call(K1, ran_command)],
            place(K1, (K1, (0,))),
            owned(K1, "HTTP/1.1 200 OK", network_request),
        )
    assert which == "any program's line beside a run that is not read"
    curl = command(
        0, "curl -sS https://a.org/x -o x", CURL, succeeded_if_text_exits_zero=False
    )
    test_sh = command(1, "./test.sh", UnknownProgramInvocation("test.sh", ()))
    network_request = request(K1, from_command(curl), "https://a.org/x")
    return (
        network_request,
        [call(K1, curl, test_sh)],
        place(K1, (K1, (0, 1))),
        owned(K1, "connect: Connection refused", network_request),
    )


UNKNOWN_PRINTER_CASES = [
    "program without a row",
    "option without a row",
    "unread words",
    "code typed through a poll",
    "code run by a program",
    "any program's line beside a run that is not read",
]


@pytest.mark.parametrize("which", UNKNOWN_PRINTER_CASES)
def test_line_that_an_unknown_printer_may_have_printed_may_belong_to_another_request(
    which: str,
):
    network_request, expanded_tool_calls, output_place_sources, output_line_owners = (
        unknown_printer_case(which)
    )
    decided = decide(
        network_request,
        expanded_tool_calls,
        places=(output_place_sources,),
        output_line_owners=(output_line_owners,),
    )
    [evidence_with_level] = decided.evidence_with_levels
    assert evidence_with_level.assumption_reasons == (
        (UnknownRunBesideAssumptionReason(),)
        if which == "any program's line beside a run that is not read"
        else (UnknownProgramOutputLinesAssumptionReason(),)
    )
    assert isinstance(evidence_with_level.evidence, OutputLineEvidence)
    assert not evidence_with_level.evidence.is_shared_with_other_requests
    assert decided.judgment_rule_use_counts == Counter({RULE_20: 1, RULE_11: 1})
    if which in ("unread words", "code typed through a poll"):
        # `NetworkRequestResultKnowledge` has no row for such a run, so it is not asked and counts nothing.
        assert decided.knowledge.uses.unknown_input_counts == Counter()


@pytest.mark.parametrize(
    "which",
    ["program without a row", "any program's line beside a run that is not read"],
)
def test_line_of_an_unknown_printer_is_the_requests_own_when_the_rule_says_so(
    monkeypatch: pytest.MonkeyPatch, which: str
):
    answer_false(monkeypatch, RULE_20)
    network_request, expanded_tool_calls, output_place_sources, output_line_owners = (
        unknown_printer_case(which)
    )
    decided = decide(
        network_request,
        expanded_tool_calls,
        places=(output_place_sources,),
        output_line_owners=(output_line_owners,),
    )
    [evidence_with_level] = decided.evidence_with_levels
    assert evidence_with_level.assumption_reasons == ()


def test_line_of_an_unknown_printer_beside_a_run_that_is_not_read_gives_both_reasons_after_one_rule_use():
    mytool = command(
        0,
        "mytool https://a.org/x",
        UnknownProgramInvocation("mytool", ("https://a.org/x",)),
        succeeded_if_text_exits_zero=False,
    )
    test_sh = command(1, "./test.sh", UnknownProgramInvocation("test.sh", ()))
    network_request = request(K1, from_command(mytool), "https://a.org/x")
    decided = decide(
        network_request,
        [call(K1, mytool, test_sh)],
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(owned(K1, "connect: Connection refused", network_request),),
    )
    [evidence_with_level] = decided.evidence_with_levels
    assert evidence_with_level.assumption_reasons == (
        UnknownProgramOutputLinesAssumptionReason(),
        UnknownRunBesideAssumptionReason(),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_20: 1, RULE_11: 1})


def test_line_that_only_the_requests_program_prints_is_its_own_beside_a_run_that_is_not_read():
    npx_tsc = command(
        0,
        "npx tsc",
        program("npx"),
        UnknownProgramInvocation("tsc", ()),
    )
    network_request = request(
        K1,
        from_command(npx_tsc, 0),
        uncertainty_reason=NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING,
    )
    decided = decide(
        network_request,
        [call(K1, npx_tsc)],
        places=(place(K1, (K1, (0,))),),
        output_line_owners=(owned(K1, "npm ERR! code E404", network_request),),
    )
    assert decided.evidence_with_levels == (
        line_evidence(K.HTTP_STATUS, REACHED, FAILED),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def test_missing_program_line_of_a_program_without_a_row_is_its_own():
    ran_command = command(
        0,
        "mytool https://a.org/x",
        UnknownProgramInvocation("mytool", ("https://a.org/x",)),
    )
    network_request = request(K1, from_command(ran_command), "https://a.org/x")
    decided = decide(
        network_request,
        [call(K1, ran_command)],
        places=(place(K1, (K1, (0,))),),
        output_line_owners=(
            owned(K1, "bash: mytool: command not found", network_request),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(K.PROGRAM_MISSING, ATTEMPTED, FAILED),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


@pytest.mark.parametrize(
    ("may_show_file_content", "may_show_page_text"), [(True, False), (False, True)]
)
def test_line_beside_shown_file_or_page_text_rests_on_a_rule(
    may_show_file_content: bool, may_show_page_text: bool
):
    curl = command(1, "curl -sS https://a.org/x", CURL)
    network_request = request(K1, from_command(curl), "https://a.org/x")
    decided = decide(
        network_request,
        [
            call(
                K1,
                command(
                    0,
                    "cat notes.md",
                    program("cat"),
                    succeeded_if_text_exits_zero=False,
                ),
                curl,
            )
        ],
        places=(
            place(
                K1,
                (K1, (0, 1)),
                may_show_file_content=may_show_file_content,
                may_show_page_text=may_show_page_text,
            ),
        ),
        output_line_owners=(
            owned(K1, "curl: (7) Failed to connect to a.org port 443", network_request),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.CONNECTION_FAILED, EXECUTED, FAILED, rests_on_judgment_rule=True
        ),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_13: 1, RULE_11: 1})


def test_line_beside_shown_file_is_a_trace_when_the_rule_says_so(
    monkeypatch: pytest.MonkeyPatch,
):
    answer_false(monkeypatch, RULE_13)
    curl = command(0, "curl -sS https://a.org/x", CURL)
    network_request = request(K1, from_command(curl), "https://a.org/x")
    decided = decide(
        network_request,
        [call(K1, curl)],
        places=(place(K1, (K1, (0,)), may_show_file_content=True),),
        output_line_owners=(
            owned(K1, "curl: (7) Failed to connect to a.org port 443", network_request),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(K.CONNECTION_FAILED, EXECUTED, FAILED),
    )


def test_line_in_a_later_call_names_that_call():
    pip = command(0, "pip install x", PIP_INSTALL)
    network_request = request(K1, from_command(pip), "x", target_kind=PACKAGE_NAME)
    decided = decide(
        network_request,
        [call(K1, pip), call(K3, command(0, "cat log", program("cat")))],
        places=(place(K3, (K1, (0,))),),
        output_line_owners=(
            owned(
                K3,
                "ERROR: No matching distribution found for x",
                network_request,
                line_index=4,
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.NOT_FOUND, EXECUTED, FAILED, showing_tool_call_key=K3, line_index=4
        ),
    )


# --- A download line of a package file beside a line of a finished install or of a saved package file ---


@dataclass(frozen=True)
class DownloadAndInstallOrSaveCase:
    # Each line with whether it names a package other than the target.
    lines: tuple[tuple[str, bool], ...]
    program_invocation: ProgramInvocation
    words: str
    target: str | UnknownNetworkRequestTarget
    # The evidence of each line in order.
    expected: tuple[EvidenceWithLevel, ...]
    rule_names: tuple[str, ...] = ()


# Lines that one request owns alone, with the evidence each gives and the rules they ask besides the one about the run.
DOWNLOAD_AND_INSTALL_OR_SAVE_CASES = {
    "pip": DownloadAndInstallOrSaveCase(
        (
            ("Downloading x-1.0-py3-none-any.whl (125 kB)", False),
            ("Successfully installed x-1.0", False),
        ),
        PIP_INSTALL,
        "pip install x",
        "x",
        (
            line_evidence(K.DOWNLOAD_STARTED, RECEIVED, None),
            line_evidence(K.INSTALLED, RECEIVED, None, line_index=1),
        ),
    ),
    "uv": DownloadAndInstallOrSaveCase(
        (("Downloading pandas (10.8MiB)", False), (" + pandas==3.0.5", False)),
        program("uv", "pip", "install"),
        "uv pip install pandas",
        "pandas",
        (
            line_evidence(K.DOWNLOAD_STARTED, RECEIVED, None),
            line_evidence(K.INSTALLED, RECEIVED, None, line_index=1),
        ),
    ),
    # Both lines name only B, a dependency of A, and still show that the command received, so the rule about another target is not asked.
    "lines naming another package": DownloadAndInstallOrSaveCase(
        (
            ("Downloading B-1.0-py3-none-any.whl (10 kB)", True),
            ("Successfully installed B-1.0", True),
        ),
        PIP_INSTALL,
        "pip install A",
        "A",
        (
            line_evidence(K.DOWNLOAD_STARTED, RECEIVED, None),
            line_evidence(K.INSTALLED, RECEIVED, None, line_index=1),
        ),
    ),
    # The Get line comes before the body, and `Setting up` shows that the package arrived, so the rule about install lines of pip or apt is not asked.
    "apt": DownloadAndInstallOrSaveCase(
        (
            (
                "Get:1 http://deb.debian.org/debian bookworm/main amd64 curl amd64 7.88.1-10 [10 kB]",
                False,
            ),
            ("Setting up curl (7.88.1-10) ...", False),
        ),
        program("apt-get", "install"),
        "apt-get install -y curl",
        "curl",
        (
            line_evidence(K.DOWNLOAD_STARTED, RECEIVED, None),
            line_evidence(K.INSTALLED, RECEIVED, None, line_index=1),
        ),
    ),
    "pip download": DownloadAndInstallOrSaveCase(
        (
            ("Downloading x-1.0-py3-none-any.whl (125 kB)", False),
            ("Successfully downloaded x", False),
        ),
        program("pip", "download"),
        "pip download x",
        "x",
        (
            line_evidence(K.DOWNLOAD_STARTED, RECEIVED, None),
            line_evidence(K.PACKAGE_FILE_IN_FOLDER, RECEIVED, None, line_index=1),
        ),
    ),
    "pip download with a line of a file new to the folder": DownloadAndInstallOrSaveCase(
        (
            ("Downloading x-1.0-py3-none-any.whl (125 kB)", False),
            ("Saved ./dl/x-1.0-py3-none-any.whl", False),
        ),
        program("pip", "download"),
        "pip download x -d dl",
        "x",
        (
            line_evidence(K.DOWNLOAD_STARTED, RECEIVED, None),
            line_evidence(K.PACKAGE_FILE_ADDED_TO_FOLDER, RECEIVED, None, line_index=1),
        ),
    ),
    # A download of metadata alone shows that the index answered, and the install line of packages named in a file rests on its rule.
    "metadata download beside an install line": DownloadAndInstallOrSaveCase(
        (
            ("Downloading x-1.0-py3-none-any.whl.metadata (6.5 kB)", False),
            ("Successfully installed x-1.0", False),
        ),
        PIP_INSTALL,
        "pip install -r reqs.txt",
        NAMED_IN_FILE,
        (
            line_evidence(K.SERVER_ANSWERED, REACHED, NOT_VISIBLE),
            line_evidence(K.INSTALLED, EXECUTED, NOT_VISIBLE, line_index=1),
        ),
        (RULE_2,),
    ),
}


@pytest.mark.parametrize(
    "download_and_install_or_save_case",
    DOWNLOAD_AND_INSTALL_OR_SAVE_CASES.values(),
    ids=DOWNLOAD_AND_INSTALL_OR_SAVE_CASES.keys(),
)
def test_download_line_beside_install_or_saved_line_shows_that_the_content_arrived(
    download_and_install_or_save_case: DownloadAndInstallOrSaveCase,
):
    ran_command = command(
        0,
        download_and_install_or_save_case.words,
        download_and_install_or_save_case.program_invocation,
    )
    network_request = request(
        K1,
        from_command(ran_command),
        download_and_install_or_save_case.target,
        target_kind=PACKAGE_NAME,
        received_content_destination=ContentSaved(None),
    )
    decided = decide(
        network_request,
        [call(K1, ran_command)],
        places=(place(K1, (K1, (0,))),),
        output_line_owners=tuple(
            owned(
                K1,
                line,
                network_request,
                line_index=line_index,
                names_another_target=names_another_target,
            )
            for line_index, (line, names_another_target) in enumerate(
                download_and_install_or_save_case.lines
            )
        ),
    )
    assert decided.evidence_with_levels == download_and_install_or_save_case.expected
    assert decided.judgment_rule_use_counts == Counter(
        {**dict.fromkeys(download_and_install_or_save_case.rule_names, 1), RULE_11: 1}
    )


def test_download_and_install_lines_shared_by_the_requests_of_one_command_show_it_for_each_but_stay_shared():
    network_request_a, network_request_b, expanded_tool_call, output_place_sources = (
        pip_install_a_b(in_two_commands=False)
    )
    for network_request in (network_request_a, network_request_b):
        decided = decide(
            network_request,
            [expanded_tool_call],
            network_requests=[network_request_a, network_request_b],
            places=(output_place_sources,),
            output_line_owners=(
                owned(
                    K1,
                    "Downloading c-1.0-py3-none-any.whl (10 kB)",
                    network_request_a,
                    network_request_b,
                    names_another_target=True,
                ),
                owned(
                    K1,
                    "Successfully installed a-1 b-2 c-1.0",
                    network_request_a,
                    network_request_b,
                    line_index=1,
                ),
            ),
        )
        assert decided.evidence_with_levels == (
            line_evidence(
                K.DOWNLOAD_STARTED,
                RECEIVED,
                None,
                is_shared_with_other_requests=True,
                may_belong_to_another_request_reason=SHARED_LINE_REASON,
            ),
            line_evidence(
                K.INSTALLED,
                RECEIVED,
                None,
                line_index=1,
                is_shared_with_other_requests=True,
                may_belong_to_another_request_reason=SharedOutputLineAssumptionReason(
                    K1, 1, None
                ),
            ),
        )
        assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def test_install_line_that_a_request_of_another_command_owns_too_makes_no_pair():
    network_request_a, network_request_b, expanded_tool_call, output_place_sources = (
        pip_install_a_b(in_two_commands=True)
    )
    decided = decide(
        network_request_a,
        [expanded_tool_call],
        network_requests=[network_request_a, network_request_b],
        places=(output_place_sources,),
        output_line_owners=(
            owned(K1, "Downloading a-1-py3-none-any.whl (10 kB)", network_request_a),
            owned(
                K1,
                "Successfully installed a-1 b-2",
                network_request_a,
                network_request_b,
                line_index=1,
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(K.DOWNLOAD_STARTED, REACHED, NOT_VISIBLE),
        line_evidence(
            K.INSTALLED,
            RECEIVED,
            None,
            line_index=1,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SharedOutputLineAssumptionReason(
                K1, 1, None
            ),
        ),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_23: 1, RULE_11: 1})


def apt_get_update_and_install_curl() -> tuple[
    NetworkRequest, NetworkRequest, ExpandedToolCall, OutputPlaceSources
]:
    """Make `apt-get update && apt-get install -y curl` with the request of each command, the first without a target as `apt-get update` names none."""
    apt_get_update = command(0, "apt-get update", program("apt-get", "update"))
    apt_get_install = command(
        1,
        "apt-get install -y curl",
        program("apt-get", "install"),
        runs_if=after_success_of(0),
    )
    return (
        request(
            K1,
            from_command(apt_get_update),
            target_kind=PACKAGE_NAME,
            received_content_destination=ContentSaved(None),
        ),
        request(
            K1,
            from_command(apt_get_install),
            "curl",
            target_kind=PACKAGE_NAME,
            received_content_destination=ContentSaved(None),
            index_in_tool_call=1,
        ),
        call(K1, apt_get_update, apt_get_install),
        place(K1, (K1, (0, 1))),
    )


# Lines that only apt prints, of the package that `apt-get install -y curl` names, so that the request of the update and that of curl own them.
APT_GET_LINE = "Get:1 http://deb.debian.org/debian bookworm/main amd64 curl amd64 7.88.1-10 [10 kB]"
APT_SETTING_UP_LINE = "Setting up curl (7.88.1-10) ..."
# The reason that the line at index 1 may belong to another request.
SECOND_SHARED_LINE_REASON = SharedOutputLineAssumptionReason(K1, 1, None)


def test_apt_download_and_install_lines_that_requests_of_two_commands_own_show_it_for_each_but_stay_shared():
    update_request, install_request, expanded_tool_call, output_place_sources = (
        apt_get_update_and_install_curl()
    )
    for network_request in (update_request, install_request):
        decided = decide(
            network_request,
            [expanded_tool_call],
            network_requests=[update_request, install_request],
            places=(output_place_sources,),
            output_line_owners=(
                owned(K1, APT_GET_LINE, update_request, install_request),
                owned(
                    K1,
                    APT_SETTING_UP_LINE,
                    update_request,
                    install_request,
                    line_index=1,
                ),
            ),
        )
        assert decided.evidence_with_levels == (
            line_evidence(
                K.DOWNLOAD_STARTED,
                RECEIVED,
                None,
                is_shared_with_other_requests=True,
                may_belong_to_another_request_reason=SHARED_LINE_REASON,
            ),
            line_evidence(
                K.INSTALLED,
                RECEIVED,
                None,
                line_index=1,
                is_shared_with_other_requests=True,
                may_belong_to_another_request_reason=SECOND_SHARED_LINE_REASON,
            ),
        )
        assert decided.judgment_rule_use_counts == Counter({RULE_24: 1, RULE_11: 1})


def test_apt_download_and_install_lines_that_requests_of_two_commands_own_show_what_each_kind_shows_when_the_rule_says_so(
    monkeypatch: pytest.MonkeyPatch,
):
    answer_false(monkeypatch, RULE_24)
    update_request, install_request, expanded_tool_call, output_place_sources = (
        apt_get_update_and_install_curl()
    )
    decided = decide(
        update_request,
        [expanded_tool_call],
        network_requests=[update_request, install_request],
        places=(output_place_sources,),
        output_line_owners=(
            owned(K1, APT_GET_LINE, update_request, install_request),
            owned(
                K1, APT_SETTING_UP_LINE, update_request, install_request, line_index=1
            ),
        ),
    )
    # The update names no package, so the install line asks the rule about install lines of other requests.
    assert decided.evidence_with_levels == (
        line_evidence(
            K.DOWNLOAD_STARTED,
            REACHED,
            NOT_VISIBLE,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SHARED_LINE_REASON,
        ),
        line_evidence(
            K.INSTALLED,
            EXECUTED,
            NOT_VISIBLE,
            line_index=1,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SECOND_SHARED_LINE_REASON,
        ),
    )
    assert decided.judgment_rule_use_counts == Counter(
        {RULE_24: 1, RULE_2: 1, RULE_11: 1}
    )


def test_apt_lines_naming_another_target_that_requests_of_two_commands_own_make_no_pair():
    update_request, install_request, expanded_tool_call, output_place_sources = (
        apt_get_update_and_install_curl()
    )
    decided = decide(
        install_request,
        [expanded_tool_call],
        network_requests=[update_request, install_request],
        places=(output_place_sources,),
        output_line_owners=(
            owned(
                K1,
                "Get:2 http://deb.debian.org/debian bookworm/main amd64 libfoo amd64 1.0 [5 kB]",
                update_request,
                install_request,
                names_another_target=True,
            ),
            owned(
                K1,
                "Setting up libfoo (1.0) ...",
                update_request,
                install_request,
                line_index=1,
                names_another_target=True,
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.DOWNLOAD_STARTED,
            EXECUTED,
            NOT_VISIBLE,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SHARED_LINE_REASON,
        ),
        line_evidence(
            K.INSTALLED,
            EXECUTED,
            NOT_VISIBLE,
            line_index=1,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SECOND_SHARED_LINE_REASON,
        ),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_10: 2, RULE_11: 1})


def test_apt_download_line_of_the_request_alone_makes_no_pair_with_an_install_line_that_a_request_of_another_command_owns_too():
    # The Get line is in a place that only the install reaches, e.g. its own result, and the Setting up line in a place that the update reaches too.
    update_request, install_request, expanded_tool_call, output_place_sources = (
        apt_get_update_and_install_curl()
    )
    decided = decide(
        install_request,
        [expanded_tool_call],
        network_requests=[update_request, install_request],
        places=(output_place_sources,),
        output_line_owners=(
            owned(K1, APT_GET_LINE, install_request),
            owned(
                K1, APT_SETTING_UP_LINE, update_request, install_request, line_index=1
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(K.DOWNLOAD_STARTED, REACHED, NOT_VISIBLE),
        line_evidence(
            K.INSTALLED,
            RECEIVED,
            None,
            line_index=1,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SECOND_SHARED_LINE_REASON,
        ),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_23: 1, RULE_11: 1})


def test_pip_download_and_install_lines_that_requests_of_two_commands_own_make_no_pair():
    pip_a = command(
        0, "pip install -r a.txt", PIP_INSTALL, succeeded_if_text_exits_zero=False
    )
    pip_b = command(1, "pip install -r b.txt", PIP_INSTALL)
    network_request_a = request(
        K1, from_command(pip_a), NAMED_IN_FILE, target_kind=PACKAGE_NAME
    )
    network_request_b = request(
        K1,
        from_command(pip_b),
        NAMED_IN_FILE,
        target_kind=PACKAGE_NAME,
        index_in_tool_call=1,
    )
    decided = decide(
        network_request_a,
        [call(K1, pip_a, pip_b)],
        network_requests=[network_request_a, network_request_b],
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(
            owned(
                K1,
                "Downloading x-1.0-py3-none-any.whl (10 kB)",
                network_request_a,
                network_request_b,
            ),
            owned(
                K1,
                "Successfully installed x-1.0",
                network_request_a,
                network_request_b,
                line_index=1,
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.DOWNLOAD_STARTED,
            REACHED,
            NOT_VISIBLE,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SHARED_LINE_REASON,
        ),
        line_evidence(
            K.INSTALLED,
            EXECUTED,
            NOT_VISIBLE,
            line_index=1,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SECOND_SHARED_LINE_REASON,
        ),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_2: 1, RULE_11: 1})


def test_download_line_that_a_run_which_is_not_read_may_have_printed_makes_no_pair():
    pip = command(0, "pip install x", PIP_INSTALL, succeeded_if_text_exits_zero=False)
    setup_sh = command(1, "./setup.sh", UnknownProgramInvocation("setup.sh", ()))
    network_request = request(K1, from_command(pip), "x", target_kind=PACKAGE_NAME)
    decided = decide(
        network_request,
        [call(K1, pip, setup_sh)],
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(
            owned(K1, "Downloading x-1.0-py3-none-any.whl (10 kB)", network_request),
            owned(K1, "Successfully installed x-1.0", network_request, line_index=1),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.DOWNLOAD_STARTED,
            REACHED,
            NOT_VISIBLE,
            may_belong_to_another_request_reason=UnknownRunBesideAssumptionReason(),
        ),
        line_evidence(K.INSTALLED, RECEIVED, None, line_index=1),
    )
    assert decided.judgment_rule_use_counts == Counter(
        {RULE_20: 1, RULE_23: 1, RULE_11: 1}
    )


def test_download_line_beside_shown_file_text_makes_no_pair():
    pip = command(0, "pip install x", PIP_INSTALL)
    network_request = request(K1, from_command(pip), "x", target_kind=PACKAGE_NAME)
    decided = decide(
        network_request,
        [call(K1, pip)],
        places=(place(K1, (K1, (0,)), may_show_file_content=True),),
        output_line_owners=(
            owned(K1, "Downloading x-1.0-py3-none-any.whl (10 kB)", network_request),
            owned(K1, "Successfully installed x-1.0", network_request, line_index=1),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.DOWNLOAD_STARTED, REACHED, NOT_VISIBLE, rests_on_judgment_rule=True
        ),
        line_evidence(
            K.INSTALLED,
            RECEIVED,
            None,
            line_index=1,
            rests_on_judgment_rule=True,
        ),
    )
    assert decided.judgment_rule_use_counts == Counter(
        {RULE_13: 2, RULE_23: 1, RULE_11: 1}
    )


# --- Evidence of the run ---


def test_call_that_did_not_run_fails_every_request_at_attempted():
    curl = command(0, "curl https://a.org/x", CURL, succeeded_if_text_exits_zero=False)
    pip = command(1, "pip install y", PIP_INSTALL)
    network_request_a = request(K1, from_command(curl), "https://a.org/x")
    network_request_b = request(
        K1, from_command(pip), "y", target_kind=PACKAGE_NAME, index_in_tool_call=1
    )
    for network_request in (network_request_a, network_request_b):
        decided = decide(
            network_request,
            [call(K1, curl, pip, execution_status=ExecutionStatus.NOT_RUN)],
            network_requests=[network_request_a, network_request_b],
        )
        assert decided.evidence_with_levels == (
            status_evidence(
                ExecutionStatus.NOT_RUN,
                ATTEMPTED,
                FAILED,
                is_shared_with_other_requests=True,
            ),
        )
        assert decided.judgment_rule_use_counts == Counter()


def test_web_tool_call_that_did_not_run_fails_at_attempted():
    network_request = request(K1, from_web_tool(), "https://a.org/x")
    decided = decide(
        network_request, [web_call(K1, execution_status=ExecutionStatus.NOT_RUN)]
    )
    assert decided.evidence_with_levels == (
        status_evidence(ExecutionStatus.NOT_RUN, ATTEMPTED, FAILED),
    )
    assert decided.judgment_rule_use_counts == Counter()


@pytest.mark.parametrize("which", ["command", "web fetch"])
def test_call_that_did_not_run_gets_only_its_status_beside_a_message_of_the_harness(
    which: str,
):
    message = "The user doesn't want to proceed with this tool use."
    if which == "command":
        curl = command(0, "curl https://a.org/x", CURL)
        network_request = request(K1, from_command(curl), "https://a.org/x")
        expanded_tool_call = call(
            K1,
            curl,
            execution_status=ExecutionStatus.NOT_RUN,
            tool_output_text=message,
        )
        output_place_sources = place(K1, (K1, (0,)))
    else:
        network_request = request(K1, from_web_tool(), "https://a.org/x")
        expanded_tool_call = web_call(
            K1, tool_output_text=message, execution_status=ExecutionStatus.NOT_RUN
        )
        output_place_sources = place(K1, is_web_tool_result=True)
    decided = decide(
        network_request, [expanded_tool_call], places=(output_place_sources,)
    )
    assert decided.evidence_with_levels == (
        status_evidence(ExecutionStatus.NOT_RUN, ATTEMPTED, FAILED),
    )
    assert decided.judgment_rule_use_counts == Counter()


def test_exit_zero_of_a_text_shows_that_every_request_of_its_command_ran():
    pip = command(0, "pip install A B", PIP_INSTALL)
    network_request_a = request(K1, from_command(pip), "A", target_kind=PACKAGE_NAME)
    network_request_b = request(
        K1, from_command(pip), "B", target_kind=PACKAGE_NAME, index_in_tool_call=1
    )
    decided = decide(
        network_request_b,
        [call(K1, pip, exit_code=0)],
        network_requests=[network_request_a, network_request_b],
    )
    assert decided.evidence_with_levels == (
        exit_zero_evidence(is_shared_with_other_requests=True),
    )
    assert decided.judgment_rule_use_counts == Counter()
    assert decided.knowledge.uses.row_use_counts == Counter(
        {(PROGRAM_EXIT_CODES_CSV, ("pip", "install", "", "0")): 1}
    )


def test_exit_zero_of_a_and_b_shows_that_both_ran():
    pip = command(0, "pip install A", PIP_INSTALL)
    curl = command(1, "curl -s https://a.org/x", CURL, runs_if=after_success_of(0))
    network_request_a = request(K1, from_command(pip), "A", target_kind=PACKAGE_NAME)
    network_request_b = request(
        K1, from_command(curl), "https://a.org/x", index_in_tool_call=1
    )
    network_requests = [network_request_a, network_request_b]
    expanded_tool_calls = [call(K1, pip, curl, exit_code=0)]
    decided_a = decide(
        network_request_a, expanded_tool_calls, network_requests=network_requests
    )
    decided_b = decide(
        network_request_b, expanded_tool_calls, network_requests=network_requests
    )
    assert decided_a.evidence_with_levels == (
        exit_zero_evidence(is_shared_with_other_requests=True),
    )
    assert decided_b.evidence_with_levels == (
        exit_zero_evidence(
            REACHED,
            NOT_VISIBLE,
            is_shared_with_other_requests=True,
            rests_on_judgment_rule=True,
        ),
    )
    assert decided_a.judgment_rule_use_counts == Counter()
    assert decided_b.judgment_rule_use_counts == Counter({RULE_1: 1})


@pytest.mark.parametrize(
    ("words", "program_invocation", "level", "stop_reason"),
    [
        ("curl -s -o x https://a.org/x", CURL, REACHED, NOT_VISIBLE),
        ("wget https://a.org/x", program("wget"), RECEIVED, None),
    ],
)
def test_exit_zero_of_a_program_whose_catalog_row_says_more_asks_the_rule(
    words: str,
    program_invocation: ProgramInvocation,
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason | None,
):
    ls = command(0, "ls", program("ls"), succeeded_if_text_exits_zero=False)
    curl = command(1, words, program_invocation)
    network_request = request(K1, from_command(curl), "https://a.org/x")
    decided = decide(network_request, [call(K1, ls, curl, exit_code=0)])
    assert decided.evidence_with_levels == (
        exit_zero_evidence(level, stop_reason, rests_on_judgment_rule=True),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_1: 1})


def test_exit_zero_shows_only_the_run_when_the_rule_on_its_meaning_says_so(
    monkeypatch: pytest.MonkeyPatch,
):
    answer_false(monkeypatch, RULE_1)
    curl = command(0, "curl -s -o x https://a.org/x", CURL)
    network_request = request(K1, from_command(curl), "https://a.org/x")
    decided = decide(network_request, [call(K1, curl, exit_code=0)])
    assert decided.evidence_with_levels == (exit_zero_evidence(),)
    assert decided.judgment_rule_use_counts == Counter({RULE_1: 1})


def test_exit_zero_shows_the_run_of_a_program_without_a_catalog_row_and_counts_it_unknown():
    sbt = command(0, "sbt compile", program("sbt", "compile"))
    network_request = request(
        K1,
        from_command(sbt),
        uncertainty_reason=NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING,
    )
    decided = decide(network_request, [call(K1, sbt, exit_code=0)])
    assert decided.evidence_with_levels == (exit_zero_evidence(),)
    assert exit_code_unknown_inputs(decided.knowledge) == Counter(
        {(PROGRAM_EXIT_CODES_CSV, ("sbt", "compile", "", "0")): 1}
    )


@pytest.mark.parametrize(
    ("outer_program_invocation", "is_read"),
    [
        (program("sudo", exits_with_exit_code_of_next_program=True), True),
        (program("sudo", exits_with_exit_code_of_next_program=False), False),
        (
            program(
                "sudo",
                exits_with_exit_code_of_next_program=UnknownExitsWithExitCodeOfNextProgram(),
            ),
            False,
        ),
        (UnknownProgramInvocation("mywrap", ("curl",)), False),
    ],
    ids=["ends with the next code", "does not", "not known", "program without a row"],
)
def test_exit_zero_is_read_through_an_outer_program_only_when_it_ends_with_the_next_code(
    outer_program_invocation: ProgramInvocation | UnknownProgramInvocation,
    is_read: bool,
):
    wget = program("wget")
    sudo_wget = command(0, "sudo wget https://a.org/x", outer_program_invocation, wget)
    network_request = request(K1, from_command(sudo_wget), "https://a.org/x")
    decided = decide(network_request, [call(K1, sudo_wget, exit_code=0)])
    if is_read:
        assert decided.evidence_with_levels == (
            exit_zero_evidence(RECEIVED, None, rests_on_judgment_rule=True),
        )
        assert decided.judgment_rule_use_counts == Counter({RULE_1: 1})
    else:
        assert decided.evidence_with_levels == ()
        assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})
        assert decided.knowledge.uses.row_use_counts == Counter()


def no_run_evidence_case(which: str) -> tuple[NetworkRequest, list[ExpandedToolCall]]:
    """Make a request that has no evidence of its own that it ran."""
    curl = program("curl", options=(option("-s"),))
    if which == "a | b":
        first = command(
            0, "curl -s https://a.org/x", curl, succeeded_if_text_exits_zero=False
        )
        return request(K1, from_command(first), "https://a.org/x"), [
            call(K1, first, command(1, "tar xz", program("tar")), exit_code=0)
        ]
    if which == "a ; b":
        first = command(
            0, "curl -s -o x https://a.org/x", curl, succeeded_if_text_exits_zero=False
        )
        return request(K1, from_command(first), "https://a.org/x"), [
            call(K1, first, command(1, "ls", program("ls")), exit_code=0)
        ]
    if which == "a || b":
        second = command(
            1,
            "curl -s https://a.org/x -o x",
            curl,
            succeeded_if_text_exits_zero=False,
            runs_if=(RunCondition((0,), ExitOutcome.FAILURE),),
        )
        return request(K1, from_command(second), "https://a.org/x"), [
            call(
                K1,
                command(
                    0, "test -f x", program("test"), succeeded_if_text_exits_zero=False
                ),
                second,
                exit_code=0,
            )
        ]
    if which == "structure may be wrong":
        ran_command = command(
            0, "curl -s https://a.org/x", curl, structure_may_be_wrong=True
        )
        return request(K1, from_command(ran_command), "https://a.org/x"), [
            call(K1, ran_command, exit_code=0)
        ]
    if which == "a command of a file that a ran script holds":
        source = FileText(0, "fetch.sh", K1)
        ran_command = command(1, "curl -s https://a.org/x", curl)
        return request(
            K2, from_command(ran_command, ran_text_source=source), "https://a.org/x"
        ), [call(K2, ran_command, exit_code=0, ran_text_source=source)]
    if which == "a step of a tool script":
        source = ScriptStepText(0)
        ran_command = command(0, "curl -s https://a.org/x -o x", curl)
        return request(
            K1, from_command(ran_command, ran_text_source=source), "https://a.org/x"
        ), [call(K1, ran_command, ran_text_source=source, action=RunToolScriptAction())]
    if which == "a call that timed out":
        ran_command = command(0, "curl https://a.org/x", CURL)
        return request(K1, from_command(ran_command), "https://a.org/x"), [
            call(K1, ran_command, execution_status=ExecutionStatus.TIMED_OUT)
        ]
    if which == "code":
        python = command(0, "python get.py", program("python"))
        return request(K1, from_code(0), "https://a.org/x"), [
            call(K1, python, exit_code=0)
        ]
    assert which == "a web tool call that did not finish"
    return request(K1, from_web_tool(), "https://a.org/x"), [
        web_call(K1, execution_status=ExecutionStatus.UNKNOWN)
    ]


NO_RUN_EVIDENCE_CASES = [
    "a | b",
    "a ; b",
    "a || b",
    "structure may be wrong",
    "a command of a file that a ran script holds",
    "a step of a tool script",
    "a call that timed out",
    "code",
    "a web tool call that did not finish",
]


@pytest.mark.parametrize("which", NO_RUN_EVIDENCE_CASES)
def test_request_without_evidence_of_its_own_run_asks_the_rule_and_the_knowledge_class_nothing(
    which: str,
):
    network_request, expanded_tool_calls = no_run_evidence_case(which)
    decided = decide(network_request, expanded_tool_calls)
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})
    assert decided.knowledge.uses.row_use_counts == Counter()
    assert decided.knowledge.uses.unknown_input_counts == Counter()


def test_request_without_evidence_of_its_run_ran_when_the_rule_says_so(
    monkeypatch: pytest.MonkeyPatch,
):
    answer_false(monkeypatch, RULE_11)
    network_request, expanded_tool_calls = no_run_evidence_case("a call that timed out")
    decided = decide(network_request, expanded_tool_calls)
    assert decided.evidence_with_levels == (
        status_evidence(
            ExecutionStatus.TIMED_OUT,
            EXECUTED,
            NOT_VISIBLE,
            rests_on_judgment_rule=True,
        ),
    )


def test_line_of_a_request_does_not_spare_the_rule_on_its_run():
    curl = command(0, "curl https://a.org/x", CURL)
    network_request = request(K1, from_command(curl), "https://a.org/x")
    decided = decide(
        network_request,
        [call(K1, curl, execution_status=ExecutionStatus.TIMED_OUT)],
        places=(place(K1, (K1, (0,))),),
        output_line_owners=(
            owned(K1, "curl: (6) Could not resolve host: a.org", network_request),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(K.NAME_NOT_RESOLVED, EXECUTED, FAILED),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def test_finished_web_tool_call_shows_that_the_tool_ran():
    network_request = request(
        K1, from_web_tool(), "q", target_kind=NetworkRequestTargetKind.SEARCH_QUERY
    )
    decided = decide(
        network_request,
        [web_call(K1, tool_output_text="", action=WebSearchAction(("q",)))],
    )
    assert decided.evidence_with_levels[0] == status_evidence(
        FINISHED, EXECUTED, NOT_VISIBLE
    )


@pytest.mark.parametrize(
    ("words_before", "exit_code_is_the_commands"),
    [((), True), (("ls",), True), (("cd /app",), False)],
    ids=["alone", "after ls ;", "after cd &&"],
)
def test_other_exit_code_gives_no_level_and_asks_the_knowledge_class_only_when_it_is_the_commands(
    words_before: tuple[str, ...], exit_code_is_the_commands: bool
):
    commands_before = [
        command(
            0,
            words,
            program(words.split()[0]),
            succeeded_if_text_exits_zero=not exit_code_is_the_commands,
        )
        for words in words_before
    ]
    curl = command(
        len(commands_before),
        "curl -f -s https://a.org/x -o x",
        program("curl", options=(option("-f"), option("-s"))),
        runs_if=after_success_of(0) if not exit_code_is_the_commands else (),
    )
    network_request = request(K1, from_command(curl), "https://a.org/x")
    decided = decide(network_request, [call(K1, *commands_before, curl, exit_code=6)])
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})
    assert exit_code_unknown_inputs(decided.knowledge) == (
        Counter({(PROGRAM_EXIT_CODES_CSV, ("curl", "", "", "6")): 1})
        if exit_code_is_the_commands
        else Counter()
    )


def test_other_exit_code_with_a_catalog_row_uses_the_row_and_gives_no_level(
    tmp_path: Path,
):
    shutil.copytree(NETWORK_REQUEST_RESULT_CATALOGS_DIR, tmp_path, dirs_exist_ok=True)
    with (tmp_path / PROGRAM_EXIT_CODES_CSV).open("a", newline="") as csv_file:
        csv.writer(csv_file).writerow(
            ["curl", "", "", "6", "nothing", "made up", "", ""]
        )
    curl = command(0, "curl -s https://a.org/x -o x", CURL)
    network_request = request(K1, from_command(curl), "https://a.org/x")
    decided = decide(
        network_request,
        [call(K1, curl, exit_code=6)],
        knowledge=NetworkRequestResultKnowledge(catalogs_dir=tmp_path),
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})
    assert decided.knowledge.uses.row_use_counts == Counter(
        {(PROGRAM_EXIT_CODES_CSV, ("curl", "", "", "6")): 1}
    )


def a_and_b_with_missing_program_of_a(
    words_of_a: str, *, a_has_request: bool
) -> tuple[NetworkRequest, list[NetworkRequest], ExpandedToolCall, OutputLineOwners]:
    program_name = words_of_a.split()[0]
    a = command(0, words_of_a, program(program_name), succeeded_if_text_exits_zero=True)
    b = command(1, "pip install y", PIP_INSTALL, runs_if=after_success_of(0))
    network_request_a = request(K1, from_command(a), "https://a.org/x")
    network_request_b = request(
        K1, from_command(b), "y", target_kind=PACKAGE_NAME, index_in_tool_call=1
    )
    network_requests = (
        [network_request_a, network_request_b] if a_has_request else [network_request_b]
    )
    output_line_owners = owned(
        K1,
        f"bash: {program_name}: command not found",
        *([network_request_a] if a_has_request else []),
    )
    return (
        network_request_b,
        network_requests,
        call(K1, a, b, exit_code=127),
        output_line_owners,
    )


@pytest.mark.parametrize(
    ("words_of_a", "a_has_request"),
    [("rg foo", False), ("curl -sS https://a.org/x", True)],
    ids=["a without a request", "a with a request that owns the line"],
)
def test_missing_program_of_a_stops_b_as_a_fact(words_of_a: str, a_has_request: bool):
    network_request_b, network_requests, expanded_tool_call, output_line_owners = (
        a_and_b_with_missing_program_of_a(words_of_a, a_has_request=a_has_request)
    )
    decided = decide(
        network_request_b,
        [expanded_tool_call],
        network_requests=network_requests,
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(output_line_owners,),
    )
    assert decided.evidence_with_levels == (
        line_evidence(K.PROGRAM_MISSING, ATTEMPTED, FAILED),
    )
    assert decided.judgment_rule_use_counts == Counter()


def test_missing_program_of_a_may_belong_to_another_command_with_that_program():
    first_rg = command(0, "rg a", program("rg"), succeeded_if_text_exits_zero=False)
    a = command(1, "rg x", program("rg"))
    b = command(2, "pip install y", PIP_INSTALL, runs_if=after_success_of(1))
    network_request_b = request(K1, from_command(b), "y", target_kind=PACKAGE_NAME)
    decided = decide(
        network_request_b,
        [call(K1, first_rg, a, b, exit_code=127)],
        places=(place(K1, (K1, (0, 1, 2))),),
        output_line_owners=(owned(K1, "bash: rg: command not found"),),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.PROGRAM_MISSING,
            ATTEMPTED,
            FAILED,
            may_belong_to_another_request_reason=MissingProgramOfAnotherCommandAssumptionReason(),
        ),
    )


def test_missing_program_line_in_a_place_without_the_call_stops_nothing():
    network_request_b, network_requests, expanded_tool_call, output_line_owners = (
        a_and_b_with_missing_program_of_a("rg foo", a_has_request=False)
    )
    decided = decide(
        network_request_b,
        [expanded_tool_call, call(K2, command(0, "cat log", program("cat")))],
        network_requests=network_requests,
        places=(place(K1, (K1, (0, 1))), place(K2, (K2, (0,)))),
        output_line_owners=(
            OutputLineOwners(
                OutputLineWithMeaning(
                    K2,
                    0,
                    None,
                    output_line_owners.output_line_with_meaning.output_line_meaning,
                ),
                (),
                False,
            ),
        ),
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def curl_and_pip_with_line(
    line: str, *, line_is_shared: bool
) -> tuple[NetworkRequest, list[NetworkRequest], ExpandedToolCall, OutputLineOwners]:
    curl = command(0, "curl -sS https://a.org/x", CURL)
    pip = command(1, "pip install y", PIP_INSTALL, runs_if=after_success_of(0))
    network_request_a = request(K1, from_command(curl), "https://a.org/x")
    network_request_b = request(
        K1, from_command(pip), "y", target_kind=PACKAGE_NAME, index_in_tool_call=1
    )
    owners = (
        (network_request_a, network_request_b)
        if line_is_shared
        else (network_request_a,)
    )
    return (
        network_request_b,
        [network_request_a, network_request_b],
        call(K1, curl, pip, exit_code=7),
        owned(K1, line, *owners),
    )


def test_failure_of_a_before_a_server_stops_b_by_a_rule():
    network_request_b, network_requests, expanded_tool_call, output_line_owners = (
        curl_and_pip_with_line(
            "curl: (7) Failed to connect to a.org port 443", line_is_shared=False
        )
    )
    decided = decide(
        network_request_b,
        [expanded_tool_call],
        network_requests=network_requests,
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(output_line_owners,),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.CONNECTION_FAILED, ATTEMPTED, FAILED, rests_on_judgment_rule=True
        ),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_15: 1})


def test_failure_of_a_does_not_stop_b_when_the_rule_says_so(
    monkeypatch: pytest.MonkeyPatch,
):
    answer_false(monkeypatch, RULE_15)
    network_request_b, network_requests, expanded_tool_call, output_line_owners = (
        curl_and_pip_with_line(
            "curl: (7) Failed to connect to a.org port 443", line_is_shared=False
        )
    )
    decided = decide(
        network_request_b,
        [expanded_tool_call],
        network_requests=network_requests,
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(output_line_owners,),
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_15: 1, RULE_11: 1})


@pytest.mark.parametrize(
    ("line", "line_is_shared"),
    [
        ("curl: (7) Failed to connect to a.org port 443", True),
        ("HTTP/1.1 404 Not Found", False),
    ],
    ids=["shared failure line of a", "refusal of a server"],
)
def test_line_of_a_that_may_be_another_requests_or_shows_a_server_does_not_stop_b(
    line: str, line_is_shared: bool
):
    network_request_b, network_requests, expanded_tool_call, output_line_owners = (
        curl_and_pip_with_line(line, line_is_shared=line_is_shared)
    )
    decided = decide(
        network_request_b,
        [expanded_tool_call],
        network_requests=network_requests,
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(output_line_owners,),
    )
    assert RULE_15 not in decided.judgment_rule_use_counts
    assert all(
        evidence_with_level.level != ATTEMPTED
        for evidence_with_level in decided.evidence_with_levels
    )


def test_line_of_a_that_shows_only_its_run_does_not_stop_b():
    pip_a = command(0, "pip install A", PIP_INSTALL)
    pip_y = command(1, "pip install y", PIP_INSTALL, runs_if=after_success_of(0))
    network_request_a = request(K1, from_command(pip_a), "A", target_kind=PACKAGE_NAME)
    network_request_y = request(
        K1, from_command(pip_y), "y", target_kind=PACKAGE_NAME, index_in_tool_call=1
    )
    decided = decide(
        network_request_y,
        [call(K1, pip_a, pip_y)],
        network_requests=[network_request_a, network_request_y],
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(
            owned(K1, "Successfully installed A-1.0", network_request_a),
        ),
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def test_exit_zero_of_a_run_with_unread_words_shows_the_run_without_asking_the_knowledge_class():
    curl = command(
        0,
        "curl --foo x https://a.org/x",
        program("curl", unread_words=("--foo", "x", "https://a.org/x")),
    )
    network_request = request(
        K1,
        from_command(curl),
        "https://a.org/x",
        uncertainty_reason=NetworkRequestUncertaintyReason.UNREAD_WORDS,
    )
    decided = decide(network_request, [call(K1, curl, exit_code=0)])
    assert decided.evidence_with_levels == (exit_zero_evidence(),)
    assert decided.judgment_rule_use_counts == Counter()
    assert decided.knowledge.uses.unknown_input_counts == Counter()


def test_exit_code_of_a_text_that_did_not_finish_gives_nothing():
    pip = command(0, "pip install x", PIP_INSTALL)
    network_request = request(K1, from_command(pip), "x", target_kind=PACKAGE_NAME)
    decided = decide(
        network_request,
        [call(K1, pip, execution_status=ExecutionStatus.TIMED_OUT, exit_code=0)],
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})
    assert decided.knowledge.uses.row_use_counts == Counter()


def test_exit_code_evidence_names_the_call_that_reported_it():
    pip = command(0, "pip install x", PIP_INSTALL)
    network_request = request(K1, from_command(pip), "x", target_kind=PACKAGE_NAME)
    decided = decide(
        network_request,
        [
            dataclasses.replace(
                call(K1, pip, exit_code=0),
                command_text_status=CommandTextStatus(FINISHED, 0, K2),
            )
        ],
    )
    assert decided.evidence_with_levels == (
        exit_zero_evidence(reporter_tool_call_key=K2),
    )


def curl_failure_and_pip(
    *,
    runs_if: tuple[RunCondition, ...] = after_success_of(0),
    curl_structure_may_be_wrong: bool = False,
    pip_structure_may_be_wrong: bool = False,
) -> tuple[NetworkRequest, list[NetworkRequest], list[ExpandedToolCall]]:
    """Make `curl -sS https://a.org/x && pip install y`, or another structure of it, with the request of each, ended by exit 7."""
    curl = command(
        0,
        "curl -sS https://a.org/x",
        CURL,
        structure_may_be_wrong=curl_structure_may_be_wrong,
    )
    pip = command(
        1,
        "pip install y",
        PIP_INSTALL,
        runs_if=runs_if,
        structure_may_be_wrong=pip_structure_may_be_wrong,
    )
    network_request_a = request(K1, from_command(curl), "https://a.org/x")
    network_request_b = request(
        K1, from_command(pip), "y", target_kind=PACKAGE_NAME, index_in_tool_call=1
    )
    return (
        network_request_b,
        [network_request_a, network_request_b],
        [call(K1, curl, pip, exit_code=7)],
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"runs_if": (RunCondition((0,), ExitOutcome.FAILURE),)},
        {"curl_structure_may_be_wrong": True},
        {"pip_structure_may_be_wrong": True},
    ],
    ids=["a || b", "structure of a may be wrong", "structure of b may be wrong"],
)
def test_failure_of_a_before_a_server_stops_only_b_that_surely_needs_its_success(
    arguments: dict,
):
    network_request_b, network_requests, expanded_tool_calls = curl_failure_and_pip(
        **arguments
    )
    decided = decide(
        network_request_b,
        expanded_tool_calls,
        network_requests=network_requests,
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(
            owned(
                K1,
                "curl: (7) Failed to connect to a.org port 443",
                network_requests[0],
            ),
        ),
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def test_failure_of_a_before_a_server_does_not_stop_c_after_the_fallback_b_of_a():
    # `curl -sS https://a.org/x || curl -sS https://b.org/x && pip install y`, where curl b ran after curl a failed, and pip then ran if curl b succeeded.
    curl_a = command(0, "curl -sS https://a.org/x", CURL)
    curl_b = command(
        1,
        "curl -sS https://b.org/x",
        CURL,
        runs_if=(RunCondition((0,), ExitOutcome.FAILURE),),
    )
    pip = command(2, "pip install y", PIP_INSTALL, runs_if=after_success_of(0, 1))
    network_request_a = request(K1, from_command(curl_a), "https://a.org/x")
    network_request_b = request(
        K1, from_command(curl_b), "https://b.org/x", index_in_tool_call=1
    )
    network_request_c = request(
        K1, from_command(pip), "y", target_kind=PACKAGE_NAME, index_in_tool_call=2
    )
    decided = decide(
        network_request_c,
        [call(K1, curl_a, curl_b, pip, exit_code=7)],
        network_requests=[network_request_a, network_request_b, network_request_c],
        places=(place(K1, (K1, (0, 1, 2))),),
        output_line_owners=(
            owned(
                K1,
                "curl: (7) Failed to connect to a.org port 443",
                network_request_a,
            ),
        ),
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def test_failure_of_a_command_of_another_call_with_the_same_id_does_not_stop_b():
    network_request_b, _, expanded_tool_calls = curl_failure_and_pip()
    curl_of_call_2 = command(0, "curl -sS https://a.org/x", CURL)
    network_request_of_call_2 = request(
        K2, from_command(curl_of_call_2), "https://a.org/x"
    )
    decided = decide(
        network_request_b,
        [*expanded_tool_calls, call(K2, curl_of_call_2, exit_code=7)],
        network_requests=[network_request_of_call_2, network_request_b],
        places=(place(K1, (K1, (0, 1))), place(K2, (K2, (0,)))),
        output_line_owners=(
            owned(
                K2,
                "curl: (7) Failed to connect to a.org port 443",
                network_request_of_call_2,
            ),
        ),
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def test_line_of_a_missing_program_that_b_owns_is_not_added_again_as_the_line_that_stopped_it():
    pip_a = command(0, "pip install a", PIP_INSTALL)
    pip_b = command(1, "pip install b", PIP_INSTALL, runs_if=after_success_of(0))
    network_request_a = request(K1, from_command(pip_a), "a", target_kind=PACKAGE_NAME)
    network_request_b = request(
        K1, from_command(pip_b), "b", target_kind=PACKAGE_NAME, index_in_tool_call=1
    )
    decided = decide(
        network_request_b,
        [call(K1, pip_a, pip_b, exit_code=127)],
        network_requests=[network_request_a, network_request_b],
        places=(place(K1, (K1, (0, 1))),),
        output_line_owners=(
            owned(
                K1,
                "bash: pip: command not found",
                network_request_a,
                network_request_b,
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(
            K.PROGRAM_MISSING,
            ATTEMPTED,
            FAILED,
            is_shared_with_other_requests=True,
            may_belong_to_another_request_reason=SHARED_LINE_REASON,
        ),
    )


# --- Evidence of what was received ---


@pytest.mark.parametrize(
    ("http_status", "stop_reason"),
    [
        (100, NOT_VISIBLE),
        (200, NOT_VISIBLE),
        (301, NOT_VISIBLE),
        (404, FAILED),
        (503, FAILED),
    ],
)
def test_web_fetch_status_with_page_text_takes_the_text_as_content_only_when_the_status_did_not_fail(
    http_status: int, stop_reason: NetworkRequestResultStopReason
):
    network_request = request(K1, from_web_tool(), "https://a.org/x")
    decided = decide(
        network_request,
        [web_call(K1, tool_output_text="Example page", http_status=http_status)],
        places=(place(K1, is_web_tool_result=True),),
    )
    is_content_shown = stop_reason == NOT_VISIBLE
    assert decided.evidence_with_levels == (
        status_evidence(FINISHED, EXECUTED, NOT_VISIBLE),
        EvidenceWithLevel(
            HttpStatusEvidence(K1, http_status), REACHED, stop_reason, ()
        ),
        *((shown_content_evidence(),) if is_content_shown else ()),
    )
    assert decided.judgment_rule_use_counts == (
        Counter({RULE_4: 1}) if is_content_shown else Counter()
    )


def test_web_tool_result_of_another_call_is_not_taken_as_content():
    network_request = request(K1, from_web_tool(), "https://a.org/x")
    decided = decide(
        network_request,
        [
            web_call(K1, http_status=200),
            web_call(K2, tool_output_text="Example page", http_status=200),
        ],
        places=(place(K2, is_web_tool_result=True),),
    )
    assert decided.evidence_with_levels == (
        status_evidence(FINISHED, EXECUTED, NOT_VISIBLE),
        EvidenceWithLevel(HttpStatusEvidence(K1, 200), REACHED, NOT_VISIBLE, ()),
    )
    assert decided.judgment_rule_use_counts == Counter()


def test_web_fetch_refused_without_text():
    network_request = request(K1, from_web_tool(), "https://a.org/x")
    decided = decide(network_request, [web_call(K1, http_status=404)])
    assert decided.evidence_with_levels == (
        status_evidence(FINISHED, EXECUTED, NOT_VISIBLE),
        EvidenceWithLevel(HttpStatusEvidence(K1, 404), REACHED, FAILED, ()),
    )
    assert decided.judgment_rule_use_counts == Counter()


def test_web_fetch_status_of_several_requests_may_belong_to_another():
    network_request_a = request(K1, from_web_tool(), "https://a.org/x")
    network_request_b = request(
        K1, from_web_tool(), "https://b.org/y", index_in_tool_call=1
    )
    decided = decide(
        network_request_a,
        [web_call(K1, http_status=200)],
        network_requests=[network_request_a, network_request_b],
    )
    assert (
        EvidenceWithLevel(
            HttpStatusEvidence(K1, 200),
            REACHED,
            NOT_VISIBLE,
            (SharedHttpStatusAssumptionReason(),),
        )
        in decided.evidence_with_levels
    )


def test_web_fetch_status_outside_the_http_codes_gives_no_evidence():
    network_request = request(K1, from_web_tool(), "https://a.org/x")
    decided = decide(network_request, [web_call(K1, http_status=999)])
    assert decided.evidence_with_levels == (
        status_evidence(FINISHED, EXECUTED, NOT_VISIBLE),
    )


@pytest.mark.parametrize("tool_output_text", [None, ""])
def test_finished_web_tool_call_without_text_asks_the_rule(
    tool_output_text: str | None,
):
    network_request = request(
        K1, from_web_tool(), "q", target_kind=NetworkRequestTargetKind.SEARCH_QUERY
    )
    decided = decide(
        network_request,
        [
            web_call(
                K1, tool_output_text=tool_output_text, action=WebSearchAction(("q",))
            )
        ],
    )
    assert decided.evidence_with_levels == (
        status_evidence(FINISHED, EXECUTED, NOT_VISIBLE),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_7: 1})


def test_finished_web_tool_call_without_text_reached_the_provider_when_the_rule_says_so(
    monkeypatch: pytest.MonkeyPatch,
):
    answer_false(monkeypatch, RULE_7)
    network_request = request(
        K1, from_web_tool(), "q", target_kind=NetworkRequestTargetKind.SEARCH_QUERY
    )
    decided = decide(network_request, [web_call(K1, action=WebSearchAction(("q",)))])
    assert decided.evidence_with_levels == (
        status_evidence(FINISHED, EXECUTED, NOT_VISIBLE),
        status_evidence(FINISHED, REACHED, NOT_VISIBLE, rests_on_judgment_rule=True),
    )


def test_web_tool_result_with_a_line_of_its_patterns_is_not_taken_as_content():
    network_request = request(K1, from_web_tool(), "https://a.org/x")
    decided = decide(
        network_request,
        [web_call(K1, tool_output_text="Please verify you are not a robot")],
        places=(place(K1, is_web_tool_result=True),),
        output_line_owners=(
            owned(
                K1,
                "Please verify you are not a robot",
                network_request,
                is_web_tool_result=True,
            ),
        ),
    )
    assert decided.evidence_with_levels == (
        line_evidence(K.SERVER_ANSWERED, REACHED, NOT_VISIBLE),
        status_evidence(FINISHED, EXECUTED, NOT_VISIBLE),
    )
    assert decided.judgment_rule_use_counts == Counter()


def test_web_step_of_a_tool_script_gets_neither_the_script_result_nor_its_status_code():
    network_request = request(K1, from_web_tool(step_index=0), "https://a.org/x")
    script_call = call(
        K1,
        tool_output_text="Example page",
        http_status=200,
        action=RunToolScriptAction(steps=(WebFetchAction(("https://a.org/x",)),)),
    )
    decided = decide(
        network_request,
        [script_call],
        places=(place(K1, is_web_tool_result=True),),
    )
    assert decided.evidence_with_levels == (
        status_evidence(FINISHED, EXECUTED, NOT_VISIBLE),
    )
    assert decided.judgment_rule_use_counts == Counter()


def test_shown_result_text_of_a_command_is_its_content_by_a_rule():
    curl = command(0, "curl https://a.org/x", CURL)
    network_request = request(K1, from_command(curl), "https://a.org/x")
    decided = decide(
        network_request,
        [call(K1, curl, exit_code=0, tool_output_text="<html>page</html>")],
        places=(place(K1, (K1, (0,))),),
    )
    assert decided.evidence_with_levels == (
        exit_zero_evidence(REACHED, NOT_VISIBLE, rests_on_judgment_rule=True),
        shown_content_evidence(),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_1: 1, RULE_4: 1})


def test_shown_result_text_gives_nothing_when_the_rule_says_so(
    monkeypatch: pytest.MonkeyPatch,
):
    answer_false(monkeypatch, RULE_4)
    curl = command(0, "curl https://a.org/x", CURL)
    network_request = request(K1, from_command(curl), "https://a.org/x")
    decided = decide(
        network_request,
        [call(K1, curl, tool_output_text="<html>page</html>")],
        places=(place(K1, (K1, (0,))),),
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_4: 1, RULE_11: 1})


def shown_text_case(
    which: str,
) -> tuple[
    NetworkRequest, list[NetworkRequest], ExpandedToolCall, tuple[OutputLineOwners, ...]
]:
    """Make a request whose result gives no `ShownContentEvidence`, e.g. a result with a failed line of the request, one that another request reaches too or one without text."""
    curl = command(0, "curl https://a.org/x", CURL, succeeded_if_text_exits_zero=False)
    network_request = request(K1, from_command(curl), "https://a.org/x")
    if which == "a failed line":
        return (
            network_request,
            [network_request],
            call(K1, curl, tool_output_text="curl: (6) Could not resolve host: a.org"),
            (owned(K1, "curl: (6) Could not resolve host: a.org", network_request),),
        )
    if which == "another request reaches the result":
        other = command(1, "curl https://b.org/y", CURL)
        other_network_request = request(
            K1, from_command(other), "https://b.org/y", index_in_tool_call=1
        )
        return (
            network_request,
            [network_request, other_network_request],
            call(K1, curl, other, tool_output_text="page"),
            (),
        )
    if which == "code":
        python = command(0, "python get.py", program("python"))
        code_network_request = request(K1, from_code(0), "https://a.org/x")
        return (
            code_network_request,
            [code_network_request],
            call(K1, python, tool_output_text="page"),
            (),
        )
    if which == "a line that stopped its command":
        rg = command(0, "rg x", program("rg"))
        curl_after_rg = command(
            1, "curl https://a.org/x", CURL, runs_if=after_success_of(0)
        )
        network_request_after_rg = request(
            K1, from_command(curl_after_rg), "https://a.org/x"
        )
        return (
            network_request_after_rg,
            [network_request_after_rg],
            call(
                K1,
                rg,
                curl_after_rg,
                exit_code=127,
                tool_output_text="bash: rg: command not found",
            ),
            (owned(K1, "bash: rg: command not found"),),
        )
    assert which == "no text"
    return network_request, [network_request], call(K1, curl, tool_output_text=""), ()


@pytest.mark.parametrize(
    "which",
    [
        "a failed line",
        "a line that stopped its command",
        "another request reaches the result",
        "code",
        "no text",
    ],
)
def test_shown_result_text_is_not_asked_about(which: str):
    network_request, network_requests, expanded_tool_call, output_line_owners = (
        shown_text_case(which)
    )
    decided = decide(
        network_request,
        [expanded_tool_call],
        network_requests=network_requests,
        places=(
            place(
                K1,
                (
                    K1,
                    tuple(
                        ran_command.shell_command.id
                        for ran_text in expanded_tool_call.ran_texts
                        if isinstance(ran_text, RanShellText)
                        for ran_command in ran_text.ran_commands
                    ),
                ),
            ),
        ),
        output_line_owners=output_line_owners,
    )
    assert RULE_4 not in decided.judgment_rule_use_counts
    assert not any(
        isinstance(evidence_with_level.evidence, ShownContentEvidence)
        for evidence_with_level in decided.evidence_with_levels
    )


def test_shown_result_text_of_a_command_is_not_its_content_where_code_typed_through_a_poll_prints_too():
    curl = command(0, "curl https://a.org/x", CURL, succeeded_if_text_exits_zero=False)
    python3 = command(1, "python3", program("python3"))
    network_request = request(K1, from_command(curl), "https://a.org/x")
    typed_code_network_request = request(K2, from_code(None), "https://b.org/y")
    decided = decide(
        network_request,
        [
            call(K1, curl, python3),
            call(K2, action=COMMAND),
            call(K3, tool_output_text="page", action=COMMAND),
        ],
        network_requests=[network_request, typed_code_network_request],
        places=(place(K3, (K1, (0, 1))),),
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def saved_file_trial(
    using_command: RanCommand,
    *,
    using_exit_code: int | None = 0,
    kind: FileUseKind = FileUseKind.USES_CONTENT,
    fits_several_written_files: bool = False,
    using_command_id: int | None = 0,
    other_writer_network_request: bool = False,
) -> tuple[NetworkRequest, list[NetworkRequest], list[ExpandedToolCall], FileUse]:
    """Make call 1 `curl -s -o a.tgz u` and call 2 that uses a.tgz with `using_command`."""
    file_use = FileUse(K2, using_command_id, kind, fits_several_written_files)
    curl = command(
        0,
        "curl -s -o a.tgz https://a.org/a.tgz",
        CURL,
        succeeded_if_text_exits_zero=False,
    )
    other_curl = command(1, "curl -s -o a.tgz https://b.org/a.tgz", CURL)
    writers = (WrittenFileWriter(0, FileWriteChannel.OWN_OUTPUT_FILE),) + (
        (WrittenFileWriter(1, FileWriteChannel.OWN_OUTPUT_FILE),)
        if other_writer_network_request
        else ()
    )
    written_file = WrittenFile("a.tgz", writers, (file_use,))
    network_request = request(
        K1,
        from_command(curl),
        "https://a.org/a.tgz",
        received_content_destination=ContentSaved("a.tgz"),
    )
    network_requests = [network_request]
    ran_commands = [curl]
    if other_writer_network_request:
        ran_commands.append(other_curl)
        network_requests.append(
            request(
                K1,
                from_command(other_curl),
                "https://b.org/a.tgz",
                received_content_destination=ContentSaved("a.tgz"),
                index_in_tool_call=1,
            )
        )
    return (
        network_request,
        network_requests,
        [
            call(K1, *ran_commands, written_files=(written_file,)),
            call(K2, using_command, exit_code=using_exit_code),
        ],
        file_use,
    )


TAR = program("tar")


def test_later_use_of_the_saved_content_that_surely_happened_shows_it_was_received():
    network_request, network_requests, expanded_tool_calls, file_use = saved_file_trial(
        command(0, "tar xzf a.tgz", TAR)
    )
    decided = decide(
        network_request, expanded_tool_calls, network_requests=network_requests
    )
    assert decided.evidence_with_levels == (file_use_evidence(file_use),)
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def test_use_of_the_saved_content_in_the_same_text_after_exit_zero_surely_happened():
    curl = command(0, "curl -s -o a.tgz https://a.org/a.tgz", CURL)
    tar = command(1, "tar xzf a.tgz", TAR, runs_if=after_success_of(0))
    file_use = FileUse(K1, 1, FileUseKind.USES_CONTENT, False)
    written_file = WrittenFile(
        "a.tgz", (WrittenFileWriter(0, FileWriteChannel.OWN_OUTPUT_FILE),), (file_use,)
    )
    network_request = request(
        K1,
        from_command(curl),
        "https://a.org/a.tgz",
        received_content_destination=ContentSaved("a.tgz"),
    )
    decided = decide(
        network_request,
        [call(K1, curl, tar, exit_code=0, written_files=(written_file,))],
    )
    assert decided.evidence_with_levels == (
        exit_zero_evidence(REACHED, NOT_VISIBLE, rests_on_judgment_rule=True),
        file_use_evidence(file_use),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_1: 1})


USE_NOT_SURE_CASES = {
    "after test -f ||": {
        "using_command": command(
            1,
            "tar xzf a.tgz",
            TAR,
            succeeded_if_text_exits_zero=False,
            runs_if=(RunCondition((0,), ExitOutcome.FAILURE),),
        ),
        "using_command_id": 1,
    },
    "before ; ls": {
        "using_command": command(
            0, "tar xzf a.tgz", TAR, succeeded_if_text_exits_zero=False
        )
    },
    "exit 2": {"using_command": command(0, "tar xzf a.tgz", TAR), "using_exit_code": 2},
    "no exit code": {
        "using_command": command(0, "tar xzf a.tgz", TAR),
        "using_exit_code": None,
    },
    "path fits several files": {
        "using_command": command(0, "tar xzf a.tgz", TAR),
        "fits_several_written_files": True,
    },
    "in a function body": {
        "using_command": command(0, "tar xzf a.tgz", TAR, in_function_body=True)
    },
    "structure may be wrong": {
        "using_command": command(0, "tar xzf a.tgz", TAR, structure_may_be_wrong=True)
    },
    "outer program that does not end with the next code": {
        "using_command": command(0, "sudo tar xzf a.tgz", program("sudo"), TAR)
    },
    "in a case branch": {
        "using_command": command(0, "tar xzf a.tgz", TAR, in_case_branch=True)
    },
    "a tool": {
        "using_command": command(0, "tar xzf a.tgz", TAR),
        "using_command_id": None,
    },
    "a command without a program": {"using_command": command(0, "tar xzf a.tgz")},
}


@pytest.mark.parametrize(
    "arguments", USE_NOT_SURE_CASES.values(), ids=USE_NOT_SURE_CASES.keys()
)
def test_use_of_the_saved_content_that_may_not_have_happened_rests_on_a_rule(
    arguments: dict,
):
    network_request, network_requests, expanded_tool_calls, file_use = saved_file_trial(
        **arguments
    )
    decided = decide(
        network_request, expanded_tool_calls, network_requests=network_requests
    )
    assert decided.evidence_with_levels == (
        file_use_evidence(file_use, rests_on_judgment_rule=True),
    )
    assert decided.judgment_rule_use_counts == Counter({RULE_14: 1, RULE_11: 1})


# (case id, the line in the result of the using call 2, the place of that result, whether the use gives evidence)
MISSING_PROGRAM_OF_USE_CASES = [
    ("program of the use missing", "bash: unzip: command not found", True, False),
    ("another program missing", "bash: rg: command not found", True, True),
    (
        "place that the using call does not reach",
        "bash: unzip: command not found",
        False,
        True,
    ),
]


@pytest.mark.parametrize(
    ("line", "is_reached_by_using_call", "gives_evidence"),
    [case[1:] for case in MISSING_PROGRAM_OF_USE_CASES],
    ids=[case[0] for case in MISSING_PROGRAM_OF_USE_CASES],
)
def test_use_by_a_command_whose_program_is_missing_gives_no_evidence(
    line: str, is_reached_by_using_call: bool, gives_evidence: bool
):
    network_request, network_requests, expanded_tool_calls, file_use = saved_file_trial(
        command(0, "unzip -o -q a.tgz", program("unzip")), using_exit_code=127
    )
    decided = decide(
        network_request,
        expanded_tool_calls,
        network_requests=network_requests,
        places=(
            place(K2, (K2, (0,)))
            if is_reached_by_using_call
            else place(K2, (K1, (0,))),
        ),
        output_line_owners=(owned(K2, line),),
    )
    assert decided.evidence_with_levels == (
        (file_use_evidence(file_use, rests_on_judgment_rule=True),)
        if gives_evidence
        else ()
    )


def test_use_of_the_saved_content_in_a_file_the_script_runs_rests_on_a_rule():
    network_request, network_requests, expanded_tool_calls, file_use = saved_file_trial(
        command(0, "tar xzf a.tgz", TAR)
    )
    expanded_tool_calls[1] = call(
        K2,
        command(0, "tar xzf a.tgz", TAR),
        exit_code=0,
        ran_text_source=FileText(5, "unpack.sh", K1),
    )
    decided = decide(
        network_request, expanded_tool_calls, network_requests=network_requests
    )
    assert decided.evidence_with_levels == (
        file_use_evidence(file_use, rests_on_judgment_rule=True),
    )


def test_use_that_may_not_have_happened_gives_nothing_when_the_rule_says_so(
    monkeypatch: pytest.MonkeyPatch,
):
    answer_false(monkeypatch, RULE_14)
    network_request, network_requests, expanded_tool_calls, _ = saved_file_trial(
        command(0, "tar xzf a.tgz", TAR), using_exit_code=2
    )
    decided = decide(
        network_request, expanded_tool_calls, network_requests=network_requests
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_14: 1, RULE_11: 1})


@pytest.mark.parametrize(
    ("kind", "rule_name", "answer", "has_evidence"),
    [
        (FileUseKind.SHOWS_CONTENT, RULE_18, True, True),
        (FileUseKind.SHOWS_CONTENT, RULE_18, False, False),
        (FileUseKind.SHOWS_SIZE_OR_TYPE, RULE_5, True, False),
        (FileUseKind.SHOWS_SIZE_OR_TYPE, RULE_5, False, True),
    ],
)
def test_use_that_shows_the_saved_file_or_its_size_asks_its_rule(
    monkeypatch: pytest.MonkeyPatch,
    kind: FileUseKind,
    rule_name: str,
    answer: bool,
    has_evidence: bool,
):
    if not answer:
        answer_false(monkeypatch, rule_name)
    network_request, network_requests, expanded_tool_calls, file_use = saved_file_trial(
        command(0, "cat a.tgz", program("cat")), kind=kind
    )
    decided = decide(
        network_request, expanded_tool_calls, network_requests=network_requests
    )
    assert decided.evidence_with_levels == (
        (file_use_evidence(file_use, rests_on_judgment_rule=True),)
        if has_evidence
        else ()
    )
    assert decided.judgment_rule_use_counts == Counter({rule_name: 1, RULE_11: 1})


def test_use_of_unknown_kind_gives_nothing():
    network_request, network_requests, expanded_tool_calls, _ = saved_file_trial(
        command(0, "mytool a.tgz", UnknownProgramInvocation("mytool", ("a.tgz",))),
        kind=FileUseKind.UNKNOWN,
    )
    decided = decide(
        network_request, expanded_tool_calls, network_requests=network_requests
    )
    assert decided.evidence_with_levels == ()
    assert decided.judgment_rule_use_counts == Counter({RULE_11: 1})


def test_use_of_a_file_that_another_request_wrote_too_may_belong_to_it():
    network_request, network_requests, expanded_tool_calls, file_use = saved_file_trial(
        command(0, "tar xzf a.tgz", TAR), other_writer_network_request=True
    )
    decided = decide(
        network_request, expanded_tool_calls, network_requests=network_requests
    )
    assert decided.evidence_with_levels == (
        file_use_evidence(file_use, is_written_by_another_request=True),
    )


def test_use_of_another_file_of_the_call_gives_nothing():
    network_request, _, expanded_tool_calls, _ = saved_file_trial(
        command(0, "tar xzf a.tgz", TAR)
    )
    other_request = request(
        K1,
        network_request.source,
        "https://a.org/a.tgz",
        received_content_destination=ContentSaved("b.tgz"),
    )
    decided = decide(
        other_request, expanded_tool_calls, network_requests=[other_request]
    )
    assert decided.evidence_with_levels == ()
