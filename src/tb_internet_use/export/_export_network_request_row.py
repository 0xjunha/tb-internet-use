"""Export the row of one network request, with what the trajectory shows of it, its result, and the columns computed from them and from outside knowledge.

A request records only the materials that rules compute from, so its category, the scope and service of its hosts, whether it is internet use, where it was sent from and the bounds of the main measure in which it counts are computed here.
For example, `pip install requests` names no host, and it is internet use only because the default registry of `pip install` is the public host `pypi.org`.

Whether a request is internet use comes from the first condition below that fits it.

- A public host gives True.
- No host and a web tool source is decided by a judgment rule, e.g. a web search.
- No host and any other source gives the hosts that a judgment rule takes it to be sent to, read by the conditions below, or None without such hosts, e.g. `git fetch origin`.
- A host name with a template is decided by a judgment rule.
- A reserved host name is decided by a judgment rule.
- Only local hosts or host names without a dot and a web tool source is decided by a judgment rule.
- Host names without a dot, alone or beside local hosts, are decided by a judgment rule, which counts them as no internet use, e.g. `curl http://db:8000/x`.
- Only local hosts gives False, e.g. `curl http://localhost:8000/health`.

The request bound comes from the first condition below that fits it.

- Not internet use gives `NEITHER`.
- A confirmed `NOT_NEEDED` result gives `NEITHER`, since a request that did not need to be sent is left out of the share of trials that have a request.
- An assumed `NOT_NEEDED` result is decided by a judgment rule.
- Unknown internet use or an uncertain request gives `UPPER_ONLY`.
- Any other request gives `LOWER_AND_UPPER`, whatever its level, e.g. also `test -f x || curl -s u -o x`, which nothing shows to have run.

The received bound comes from the first condition below that fits it.

- A request bound `NEITHER` gives `NEITHER`.
- A confirmed failure gives `NEITHER`.
- An assumed failure is decided by a judgment rule.
- A confirmed success with a request bound `LOWER_AND_UPPER` gives `LOWER_AND_UPPER`.
- Any other result gives `UPPER_ONLY`, e.g. an assumed success or a result that is not visible.
"""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    FileText,
    FileTextWithoutKnownWriter,
    OutputVisibility,
    PollInputText,
    ProgramInvocation,
    RanTextSource,
    ScriptStepText,
    StdinText,
)
from tb_internet_use.export._export_network_request_category import (
    export_network_request_category,
)
from tb_internet_use.export._redact_credentials import redact_credentials
from tb_internet_use.export.judgment_rules import (
    treat_assumed_failure_as_possibly_received,
    treat_assumed_not_needed_result_as_upper_bound_only,
    treat_local_or_single_label_host_name_of_web_tool_as_unknown_internet_use,
    treat_request_without_host_name_as_sent_to_default_registry_host,
    treat_reserved_host_name_as_unknown_internet_use,
    treat_single_label_host_name_as_not_internet_use,
    treat_templated_host_name_as_unknown_internet_use,
    treat_web_tool_request_without_host_name_as_internet_use,
)
from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
    NetworkRequestSourceKind,
    PackageRegistry,
    PublicHost,
    UnknownPackageRegistry,
    UnknownPublicHost,
)
from tb_internet_use.network_request.judgment_rules import (
    treat_dotted_host_name_as_public,
)
from tb_internet_use.network_request.model import (
    ContentDiscarded,
    ContentPipedToCommand,
    ContentSaved,
    ContentShownInResult,
    FromCode,
    FromCommand,
    FromWebTool,
    HostNameScope,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestSource,
    NetworkRequestTargetKind,
    NoContentRequested,
    ReceivedContentDestination,
    UnknownCodeCall,
    UnknownHostNameScope,
    UnknownHostNameScopeReason,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetKind,
    UnknownReceivedContentDestination,
)
from tb_internet_use.network_request.parse_host_name import parse_host_name
from tb_internet_use.network_request_result.model import (
    ExecutionStatusEvidence,
    ExitCodeEvidence,
    FileUseEvidence,
    HttpStatusEvidence,
    NetworkRequestResult,
    NetworkRequestResultCertainty,
    NetworkRequestResultEvidence,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    ShownContentEvidence,
)
from tb_internet_use.tool_call.model import ToolCallKey

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that `export_rows` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.export_knowledge import ExportKnowledge

# The text between the texts of two pieces of evidence in the `evidence` column, which differs from the `, ` inside the text of one piece.
_EVIDENCE_SEPARATOR = "; "


def export_network_request_row(
    network_request_result: NetworkRequestResult,
    *,
    knowledge: ExportKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> NetworkRequestRow:
    """Export the `NetworkRequestRow` of one network request result, by the conditions of the module docstring, with its credentials redacted.

    It asks `knowledge` about each public host of the request, about the package registry of a command whose target is a package name, and about the sender of a web tool.
    Each judgment rule adds one to `judgment_rule_use_counts` under its name when it decides something, also the rule of `extract_network_requests` that reads a dotted host name as public.
    The four columns that hold text of the trajectory, i.e. `source`, `made_by`, `target` and `host_names`, pass through `redact_credentials`.
    `is_among_success_line_owners_one_of_which_received` is False here, since it rests on the rows of the other requests that share an output line, and `mark_network_request_rows_among_success_line_owners` sets it once all rows of the trial are made.
    """
    network_request = network_request_result.network_request
    host_name_scopes = _host_name_scopes_of(
        network_request.host_names, judgment_rule_use_counts=judgment_rule_use_counts
    )
    public_hosts = [
        knowledge.public_host(host_name)
        for host_name, host_name_scope in zip(
            network_request.host_names, host_name_scopes, strict=True
        )
        if host_name_scope == HostNameScope.PUBLIC
    ]
    package_registry = _package_registry_for(network_request, knowledge=knowledge)
    is_internet_use = _internet_use_from_host_name_scopes(
        host_name_scopes,
        network_request,
        package_registry,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    category = export_network_request_category(
        network_request,
        public_hosts,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    request_measure_bound = _request_measure_bound_of(
        network_request_result,
        is_internet_use,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    tool_call_key = network_request.tool_call_key
    target = network_request.target
    target_kind = network_request.target_kind
    request_certainty = network_request_result.request_certainty_after_evidence
    return NetworkRequestRow(
        trial_id=tool_call_key.trial_id,
        trajectory_id=tool_call_key.trajectory_id,
        step_id=tool_call_key.step_id,
        call_index=tool_call_key.call_index,
        request_index=network_request.index_in_tool_call,
        source_kind=_source_kind_of(network_request.source),
        source=redact_credentials(
            _source_text_from_source(network_request.source),
            judgment_rule_use_counts=judgment_rule_use_counts,
        ),
        made_by=redact_credentials(
            _made_by_text_from_source(network_request.source),
            judgment_rule_use_counts=judgment_rule_use_counts,
        ),
        target=redact_credentials(
            target if isinstance(target, str) else "",
            judgment_rule_use_counts=judgment_rule_use_counts,
        ),
        unknown_target_reason=target.reason
        if isinstance(target, UnknownNetworkRequestTarget)
        else None,
        target_kind=None
        if isinstance(target_kind, UnknownNetworkRequestTargetKind)
        else target_kind,
        host_names=redact_credentials(
            " ".join(network_request.host_names),
            judgment_rule_use_counts=judgment_rule_use_counts,
        ),
        received_content_destination=_received_content_destination_text_of(
            network_request.received_content_destination
        ),
        request_certainty=request_certainty,
        request_uncertainty_reason=network_request.uncertainty_reason
        if request_certainty == NetworkRequestCertainty.UNCERTAIN
        else None,
        level=network_request_result.level,
        stop_reason=network_request_result.stop_reason,
        level_certainty=network_request_result.level_certainty,
        evidence=_EVIDENCE_SEPARATOR.join(
            _evidence_text_from_evidence(evidence)
            for evidence in network_request_result.evidence
        ),
        category=category,
        host_scope=" ".join(map(_host_scope_text_of, host_name_scopes)),
        host_service=_host_service_text_of(host_name_scopes, public_hosts),
        package_registry=_package_registry_text_of(
            category, public_hosts, package_registry
        ),
        is_internet_use=is_internet_use,
        sender=_sender_from_source(network_request.source, knowledge=knowledge),
        result_view=_result_view_from_stop_reason(network_request_result.stop_reason),
        request_measure_bound=request_measure_bound,
        received_measure_bound=_received_measure_bound_of(
            network_request_result,
            request_measure_bound,
            judgment_rule_use_counts=judgment_rule_use_counts,
        ),
        is_among_success_line_owners_one_of_which_received=False,
    )


def _host_name_scopes_of(
    host_names: Sequence[str], *, judgment_rule_use_counts: Counter[str]
) -> tuple[HostNameScope | UnknownHostNameScope, ...]:
    """Give the scope of each host name in order, as `parse_host_name` reads it and `treat_dotted_host_name_as_public` decides a dotted name, e.g. PUBLIC for `files.acme.org`.

    A name without a dot or with a template keeps its unknown scope, e.g. `db` or `$HOST`, so the `host_scope` column shows its form while `treat_single_label_host_name_as_not_internet_use` decides the internet use of `db`.
    """
    host_name_scopes: list[HostNameScope | UnknownHostNameScope] = []
    for host_name in host_names:
        host_name_scope = parse_host_name(host_name)
        if (
            isinstance(host_name_scope, UnknownHostNameScope)
            and host_name_scope.reason == UnknownHostNameScopeReason.DOTTED_NAME
        ):
            host_name_scope = treat_dotted_host_name_as_public(
                host_name_scope, use_counts=judgment_rule_use_counts
            )
        host_name_scopes.append(host_name_scope)
    return tuple(host_name_scopes)


def _package_registry_for(
    network_request: NetworkRequest, *, knowledge: ExportKnowledge
) -> PackageRegistry | UnknownPackageRegistry | None:
    """Find the default package registry of the program of a command whose target is a package name, e.g. `pypi` for `pip install requests`, or None for a request that the door is not asked about, e.g. `git fetch origin` or code."""
    source = network_request.source
    if (
        network_request.target_kind != NetworkRequestTargetKind.PACKAGE_NAME
        or not isinstance(source, FromCommand)
        or not isinstance(source.program_invocation, ProgramInvocation)
    ):
        return None
    return knowledge.package_registry(source.program_invocation)


def _internet_use_from_host_name_scopes(
    host_name_scopes: Sequence[HostNameScope | UnknownHostNameScope],
    network_request: NetworkRequest,
    package_registry: PackageRegistry | UnknownPackageRegistry | None,
    *,
    judgment_rule_use_counts: Counter[str],
) -> bool | None:
    """Give whether a request is internet use by the first condition of the module docstring that fits it, or None when the conditions cannot tell.

    A request without a host name and from no web tool reads the hosts of `treat_request_without_host_name_as_sent_to_default_registry_host` as if its words named them, e.g. `pypi.org` for `pip install requests`.
    """
    if host_name_scopes:
        return _internet_use_from_nonempty_host_name_scopes(
            host_name_scopes,
            network_request,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
    if isinstance(network_request.source, FromWebTool):
        if treat_web_tool_request_without_host_name_as_internet_use(
            network_request, use_counts=judgment_rule_use_counts
        ):
            return True
        return None
    default_registry_host_names = (
        treat_request_without_host_name_as_sent_to_default_registry_host(
            network_request, package_registry, use_counts=judgment_rule_use_counts
        )
    )
    if not default_registry_host_names:
        return None
    return _internet_use_from_nonempty_host_name_scopes(
        _host_name_scopes_of(
            default_registry_host_names,
            judgment_rule_use_counts=judgment_rule_use_counts,
        ),
        network_request,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )


def _internet_use_from_nonempty_host_name_scopes(
    host_name_scopes: Sequence[HostNameScope | UnknownHostNameScope],
    network_request: NetworkRequest,
    *,
    judgment_rule_use_counts: Counter[str],
) -> bool | None:
    """Give whether a request with at least one host is internet use from the scopes of its hosts, asking a judgment rule when the scopes cannot tell."""
    if HostNameScope.PUBLIC in host_name_scopes:
        return True
    if any(
        isinstance(host_name_scope, UnknownHostNameScope)
        and host_name_scope.reason != UnknownHostNameScopeReason.SINGLE_LABEL
        for host_name_scope in host_name_scopes
    ):
        return _internet_use_from_rule_answer(
            treat_templated_host_name_as_unknown_internet_use(
                network_request, use_counts=judgment_rule_use_counts
            )
        )
    if HostNameScope.RESERVED in host_name_scopes:
        return _internet_use_from_rule_answer(
            treat_reserved_host_name_as_unknown_internet_use(
                network_request, use_counts=judgment_rule_use_counts
            )
        )
    if isinstance(network_request.source, FromWebTool):
        return _internet_use_from_rule_answer(
            treat_local_or_single_label_host_name_of_web_tool_as_unknown_internet_use(
                network_request, use_counts=judgment_rule_use_counts
            )
        )
    # Only local hosts and names without a dot are left here.
    if any(
        isinstance(host_name_scope, UnknownHostNameScope)
        for host_name_scope in host_name_scopes
    ):
        if treat_single_label_host_name_as_not_internet_use(
            network_request, use_counts=judgment_rule_use_counts
        ):
            return False
        return None
    return False


def _internet_use_from_rule_answer(is_unknown_internet_use: bool) -> bool | None:
    """Give None for a judgment rule that answers `True` and False for one that answers `False`."""
    if is_unknown_internet_use:
        return None
    return False


def _source_kind_of(source: NetworkRequestSource) -> NetworkRequestSourceKind:
    """Give the kind of the request source, one per member of `NetworkRequestSource`."""
    match source:
        case FromCommand():
            return NetworkRequestSourceKind.COMMAND
        case FromCode():
            return NetworkRequestSourceKind.CODE
        case FromWebTool():
            return NetworkRequestSourceKind.WEB_TOOL


def _source_text_from_source(source: NetworkRequestSource) -> str:
    """Give the place of the request within its call as a short text, e.g. `command 2 in fetch.sh written by call 11.0`, `code of command 0` or `web tool of script step 1`.

    A call is written as its step id and call index, e.g. `11.0`.
    """
    match source:
        case FromCommand(command_id=command_id, ran_text_source=ran_text_source):
            return f"command {command_id}{_ran_text_source_text_of(ran_text_source)}"
        case FromCode(runner_command_id=None):
            return "code typed by a poll"
        case FromCode(runner_command_id=runner_command_id):
            return f"code of command {runner_command_id}"
        case FromWebTool(step_index=None):
            return "web tool"
        case FromWebTool(step_index=step_index):
            return f"web tool of script step {step_index}"


def _ran_text_source_text_of(ran_text_source: RanTextSource) -> str:
    """Give where the text of a command is, as the end of the `source` text of its request, e.g. ` in setup.sh that no call wrote`, empty for the command text of the call."""
    match ran_text_source:
        case CallCommandText():
            return ""
        case ScriptStepText(step_index=step_index):
            return f" of script step {step_index}"
        case PollInputText(step_index=None):
            return " typed by a poll"
        case PollInputText(step_index=step_index):
            return f" typed by a poll of script step {step_index}"
        case FileText(
            runner_command_id=runner_command_id,
            path=path,
            writer_tool_call_key=writer_tool_call_key,
        ):
            return f" in {_file_path_text_of(path, runner_command_id)} written by call {_tool_call_key_text_of(writer_tool_call_key)}"
        case FileTextWithoutKnownWriter(runner_command_id=runner_command_id, path=path):
            return (
                f" in {_file_path_text_of(path, runner_command_id)} that no call wrote"
            )
        case StdinText(runner_command_id=runner_command_id):
            return f" in the stdin of command {runner_command_id}"
        case ArgumentText(runner_command_id=runner_command_id):
            return f" in an argument of command {runner_command_id}"


def _file_path_text_of(path: str | None, runner_command_id: int) -> str:
    """Give the path of a file that a command runs, or `the file of command 0` when its words name none, e.g. the Makefile of `make`."""
    if path is None:
        return f"the file of command {runner_command_id}"
    return path


def _tool_call_key_text_of(tool_call_key: ToolCallKey) -> str:
    """Give a call as its step id and 0-based call index, e.g. `11.0`."""
    return f"{tool_call_key.step_id}.{tool_call_key.call_index}"


def _made_by_text_from_source(source: NetworkRequestSource) -> str:
    """Give what made the request as a short text, e.g. `pip install` for a program and subcommand, `mytool` for a program without a row, `python requests.get` for code and `WebFetch` for a web tool.

    Code whose call has no row of the code call catalog gives its language alone, e.g. `python`.
    """
    match source:
        case FromCommand(program_invocation=ProgramInvocation() as program_invocation):
            return " ".join(
                (program_invocation.program_name, *program_invocation.subcommand_words)
            )
        case FromCommand(program_invocation=unknown_program_invocation):
            return unknown_program_invocation.program_name
        case FromCode(code_language=code_language, call_name=UnknownCodeCall()):
            return code_language.value
        case FromCode(code_language=code_language, call_name=call_name):
            return f"{code_language.value} {call_name}"
        case FromWebTool(harness_tool=harness_tool):
            return harness_tool.name


def _received_content_destination_text_of(
    received_content_destination: ReceivedContentDestination,
) -> str:
    """Give the destination of the received content as a word, e.g. `saved` or `piped_partial`."""
    match received_content_destination:
        case NoContentRequested():
            return "not_requested"
        case ContentDiscarded():
            return "discarded"
        case ContentSaved():
            return "saved"
        case ContentShownInResult():
            return "shown"
        case ContentPipedToCommand(visibility_at_end=visibility_at_end):
            return _piped_content_destination_text_of(visibility_at_end)
        case UnknownReceivedContentDestination():
            return "unknown"


def _piped_content_destination_text_of(output_visibility: OutputVisibility) -> str:
    """Give the word of content piped to a command, by how much of it the result still shows, e.g. `piped_none` after `| wc -c`."""
    match output_visibility:
        case OutputVisibility.WHOLE:
            return "piped_whole"
        case OutputVisibility.PARTIAL:
            return "piped_partial"
        case OutputVisibility.NONE:
            return "piped_none"
        case OutputVisibility.UNKNOWN:
            return "piped_unknown"


def _evidence_text_from_evidence(evidence: NetworkRequestResultEvidence) -> str:
    """Give one piece of evidence as a short text that says where it is in the trajectory and what it shows, e.g. `line 0 of call 12.0, name_not_resolved` or `exit code 0 of call 3.0, shared`.

    The text of an output line is not copied, so no credential in it reaches the row.
    `shared` ends the text of evidence that other requests share.
    """
    match evidence:
        case OutputLineEvidence(line_index_in_json_string=None):
            text = f"line {evidence.line_index} of call {_tool_call_key_text_of(evidence.showing_tool_call_key)}, {evidence.kind}"
            return _evidence_text_with_shared_mark_of(
                text, evidence.is_shared_with_other_requests
            )
        case OutputLineEvidence(line_index_in_json_string=line_index_in_json_string):
            text = f"line {evidence.line_index} of call {_tool_call_key_text_of(evidence.showing_tool_call_key)}, line {line_index_in_json_string} of its output string, {evidence.kind}"
            return _evidence_text_with_shared_mark_of(
                text, evidence.is_shared_with_other_requests
            )
        case HttpStatusEvidence():
            return f"http status {evidence.http_status} of call {_tool_call_key_text_of(evidence.showing_tool_call_key)}"
        case ExitCodeEvidence():
            text = f"exit code {evidence.exit_code} of call {_tool_call_key_text_of(evidence.reporter_tool_call_key)}"
            return _evidence_text_with_shared_mark_of(
                text, evidence.is_shared_with_other_requests
            )
        case ExecutionStatusEvidence():
            text = f"execution status {evidence.execution_status} of call {_tool_call_key_text_of(evidence.reporter_tool_call_key)}"
            return _evidence_text_with_shared_mark_of(
                text, evidence.is_shared_with_other_requests
            )
        case FileUseEvidence(file_use=file_use):
            text = f"file use {file_use.kind} by {_using_command_text_of(file_use.command_id)}call {_tool_call_key_text_of(file_use.using_tool_call_key)}"
            if file_use.fits_several_written_files:
                text += ", fits several written files"
            return text
        case ShownContentEvidence():
            return f"content shown in call {_tool_call_key_text_of(evidence.showing_tool_call_key)}"


def _evidence_text_with_shared_mark_of(
    text: str, is_shared_with_other_requests: bool
) -> str:
    """Add `, shared` to the text of evidence that other requests share."""
    if is_shared_with_other_requests:
        return f"{text}, shared"
    return text


def _using_command_text_of(command_id: int | None) -> str:
    """Give the using command before its call, e.g. `command 1 of `, empty for a tool."""
    if command_id is None:
        return ""
    return f"command {command_id} of "


def _host_scope_text_of(host_name_scope: HostNameScope | UnknownHostNameScope) -> str:
    """Give the scope of one host as a word, e.g. `public`, or `unknown_single_label` for `db`."""
    if isinstance(host_name_scope, UnknownHostNameScope):
        return f"unknown_{host_name_scope.reason}"
    return host_name_scope.value


def _host_service_text_of(
    host_name_scopes: Sequence[HostNameScope | UnknownHostNameScope],
    public_hosts: Sequence[PublicHost | UnknownPublicHost],
) -> str:
    """Give the service of each host in order, separated by spaces, e.g. `not_public unknown` for `10.0.0.5 a.org`.

    A public host gives the service of its row of the host catalog, or `unknown` without one. Any other host gives `not_public`, also one whose scope is not known, e.g. `db`, since the door is asked only about public hosts.
    `public_hosts` holds the answers for the public hosts in the same order.
    """
    remaining_public_hosts = iter(public_hosts)
    host_service_texts: list[str] = []
    for host_name_scope in host_name_scopes:
        if host_name_scope != HostNameScope.PUBLIC:
            host_service_texts.append("not_public")
            continue
        match next(remaining_public_hosts):
            case PublicHost(service=service):
                host_service_texts.append(service.value)
            case UnknownPublicHost():
                host_service_texts.append("unknown")
    return " ".join(host_service_texts)


def _package_registry_text_of(
    category: NetworkRequestCategory,
    public_hosts: Sequence[PublicHost | UnknownPublicHost],
    package_registry: PackageRegistry | UnknownPackageRegistry | None,
) -> str:
    """Give the registry of a package request, e.g. `pypi`, empty for any other category.

    The registry of a public host of the request comes first, then the default registry of its program. Without either it is `unknown`, also for a request that the door is not asked about.
    """
    if category != NetworkRequestCategory.PACKAGE:
        return ""
    for public_host in public_hosts:
        if isinstance(public_host, PublicHost) and public_host.package_registry:
            return public_host.package_registry
    if isinstance(package_registry, PackageRegistry):
        return package_registry.name
    return "unknown"


def _sender_from_source(
    source: NetworkRequestSource, *, knowledge: ExportKnowledge
) -> NetworkRequestSender:
    """Give where a request was sent from, which is the task environment for a command or code and the answer of `knowledge` for a web tool, `UNKNOWN` without a row."""
    if not isinstance(source, FromWebTool):
        return NetworkRequestSender.TASK_ENVIRONMENT
    network_request_sender = knowledge.network_request_sender(source.harness_tool)
    if isinstance(network_request_sender, NetworkRequestSender):
        return network_request_sender
    return NetworkRequestSender.UNKNOWN


def _result_view_from_stop_reason(
    stop_reason: NetworkRequestResultStopReason | None,
) -> NetworkRequestResultView:
    """Give the view of a result for reports, which its stop reason alone settles, e.g. `RECEIVED` for no stop reason, also for `ping` that reached its host."""
    match stop_reason:
        case None:
            return NetworkRequestResultView.RECEIVED
        case NetworkRequestResultStopReason.FAILED:
            return NetworkRequestResultView.NOT_RECEIVED
        case NetworkRequestResultStopReason.NOT_VISIBLE:
            return NetworkRequestResultView.UNKNOWN
        case NetworkRequestResultStopReason.NOT_NEEDED:
            return NetworkRequestResultView.NOT_NEEDED


def _request_measure_bound_of(
    network_request_result: NetworkRequestResult,
    is_internet_use: bool | None,
    *,
    judgment_rule_use_counts: Counter[str],
) -> MeasureBound:
    """Give the bounds in which the request makes its trial count as one that has a request, by the first condition of the module docstring that fits it.

    The level and the evidence are not read, since a request is confirmed by knowledge of what made it, and how far it got matters only for the received bound.
    """
    if is_internet_use is False:
        return MeasureBound.NEITHER
    if network_request_result.stop_reason == NetworkRequestResultStopReason.NOT_NEEDED:
        if (
            network_request_result.level_certainty
            == NetworkRequestResultCertainty.CONFIRMED
        ):
            return MeasureBound.NEITHER
        if treat_assumed_not_needed_result_as_upper_bound_only(
            network_request_result, use_counts=judgment_rule_use_counts
        ):
            return MeasureBound.UPPER_ONLY
        return MeasureBound.NEITHER
    if (
        is_internet_use is None
        or network_request_result.request_certainty_after_evidence
        == NetworkRequestCertainty.UNCERTAIN
    ):
        return MeasureBound.UPPER_ONLY
    return MeasureBound.LOWER_AND_UPPER


def _received_measure_bound_of(
    network_request_result: NetworkRequestResult,
    request_measure_bound: MeasureBound,
    *,
    judgment_rule_use_counts: Counter[str],
) -> MeasureBound:
    """Give the bounds in which the request makes its trial count as one that received something, by the first condition of the module docstring that fits it, never stronger than `request_measure_bound`."""
    if request_measure_bound == MeasureBound.NEITHER:
        return MeasureBound.NEITHER
    is_confirmed = (
        network_request_result.level_certainty
        == NetworkRequestResultCertainty.CONFIRMED
    )
    if network_request_result.stop_reason == NetworkRequestResultStopReason.FAILED:
        if is_confirmed:
            return MeasureBound.NEITHER
        if treat_assumed_failure_as_possibly_received(
            network_request_result, use_counts=judgment_rule_use_counts
        ):
            return MeasureBound.UPPER_ONLY
        return MeasureBound.NEITHER
    if (
        network_request_result.stop_reason is None
        and is_confirmed
        and request_measure_bound == MeasureBound.LOWER_AND_UPPER
    ):
        return MeasureBound.LOWER_AND_UPPER
    return MeasureBound.UPPER_ONLY
