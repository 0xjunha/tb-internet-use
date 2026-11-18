"""Tests for export/judgment_rules.py, one table of each rule with a made-up situation, the value it gives and the name it is counted under."""

from collections import Counter
from collections.abc import Callable

import pytest

from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    OutputVisibility,
    UnknownProgramInvocation,
)
from tb_internet_use.export.judgment_rules import (
    treat_assumed_failure_as_possibly_received,
    treat_assumed_not_needed_result_as_upper_bound_only,
    treat_content_piped_to_consuming_command_as_other_web,
    treat_content_piped_to_showing_command_as_other_web,
    treat_discarded_content_as_other_web,
    treat_host_target_that_may_receive_content_as_other_web,
    treat_local_host_name_of_web_tool_as_unknown_internet_use,
    treat_repository_request_for_no_content_as_other_web,
    treat_request_of_unknown_sender_as_possibly_from_task_environment,
    treat_request_without_host_name_as_sent_to_default_registry_host,
    treat_reserved_host_name_as_unknown_internet_use,
    treat_saved_content_from_package_registry_host_as_fetched_file,
    treat_shown_content_from_registry_or_model_hub_host_as_other_web,
    treat_shown_content_from_search_engine_host_as_other_web,
    treat_single_label_host_name_as_not_internet_use,
    treat_templated_host_name_as_unknown_internet_use,
    treat_url_query_value_and_fragment_as_credential,
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
)
from tb_internet_use.network_request.model import (
    ContentDiscarded,
    ContentPipedToCommand,
    ContentSaved,
    ContentShownInResult,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoContentRequested,
    ReceivedContentDestination,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResult,
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
)
from tb_internet_use.tool_call.model import HarnessTool, ToolCallKey


def _request(
    words: tuple[str, ...],
    target_kind: NetworkRequestTargetKind,
    received_content_destination: ReceivedContentDestination,
    *host_names: str,
) -> NetworkRequest:
    """Make the request of a made-up command for the situation of a rule, which reads none of its fields."""
    return NetworkRequest(
        tool_call_key=ToolCallKey("t1", "main", 1, 0),
        index_in_tool_call=0,
        source=FromCommand(
            0, CallCommandText(), UnknownProgramInvocation(words[0], words[1:])
        ),
        target=words[-1],
        target_kind=target_kind,
        host_names=host_names,
        received_content_destination=received_content_destination,
        certainty=NetworkRequestCertainty.UNCERTAIN,
        uncertainty_reason=NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM,
    )


def _web_tool_request(
    harness_tool: HarnessTool,
    target: str,
    target_kind: NetworkRequestTargetKind,
    *host_names: str,
) -> NetworkRequest:
    """Make the request of a made-up web tool call whose content is shown in the result, for the situation of a rule about web tools."""
    return NetworkRequest(
        tool_call_key=ToolCallKey("t1", "main", 1, 0),
        index_in_tool_call=0,
        source=FromWebTool(None, harness_tool),
        target=target,
        target_kind=target_kind,
        host_names=host_names,
        received_content_destination=ContentShownInResult(),
        certainty=NetworkRequestCertainty.CONFIRMED,
        uncertainty_reason=None,
    )


def _assumed_result(
    stop_reason: NetworkRequestResultStopReason, output_line_kind: OutputLineKind
) -> NetworkRequestResult:
    """Make the result of a made-up request that rests on one output line shared with another request."""
    return NetworkRequestResult(
        network_request=_request(
            ("curl", "https://a.org/x"),
            NetworkRequestTargetKind.URL,
            ContentShownInResult(),
            "a.org",
        ),
        request_certainty_after_evidence=NetworkRequestCertainty.UNCERTAIN,
        level=NetworkRequestResultLevel.EXECUTED,
        stop_reason=stop_reason,
        level_certainty=NetworkRequestResultCertainty.ASSUMED,
        evidence=(
            OutputLineEvidence(
                ToolCallKey("t1", "main", 1, 0), 0, None, output_line_kind, True
            ),
        ),
    )


PAGE_READ_ROW_FROM_UNKNOWN_SENDER = NetworkRequestRow(
    trial_id="t1",
    trajectory_id="main",
    step_id=1,
    call_index=0,
    request_index=0,
    source_kind=NetworkRequestSourceKind.WEB_TOOL,
    source="web tool",
    made_by="Fetch",
    target="https://a.org/p",
    unknown_target_reason=None,
    target_kind=NetworkRequestTargetKind.URL,
    host_names="a.org",
    received_content_destination="shown",
    request_certainty=NetworkRequestCertainty.CONFIRMED,
    request_uncertainty_reason=None,
    level=NetworkRequestResultLevel.RECEIVED,
    stop_reason=None,
    level_certainty=NetworkRequestResultCertainty.ASSUMED,
    evidence="content shown in call 1.0",
    category=NetworkRequestCategory.PAGE_READ,
    host_scope="public",
    host_service="unknown",
    package_registry="",
    is_internet_use=True,
    sender=NetworkRequestSender.UNKNOWN,
    result_view=NetworkRequestResultView.RECEIVED,
    request_measure_bound=MeasureBound.LOWER_AND_UPPER,
    received_measure_bound=MeasureBound.UPPER_ONLY,
)

# (rule, its situation, the value it gives)
JUDGMENT_RULE_CASES: list[tuple[Callable[..., object], tuple[object, ...], object]] = [
    (
        treat_url_query_value_and_fragment_as_credential,
        ("curl 'https://a.org/x?token=abc&page=2#k'",),
        True,
    ),
    (
        treat_repository_request_for_no_content_as_other_web,
        (
            _request(
                ("git", "https://github.com/a/b"),
                NetworkRequestTargetKind.REPOSITORY_URL,
                NoContentRequested(),
                "github.com",
            ),
        ),
        True,
    ),
    (
        treat_discarded_content_as_other_web,
        (
            _request(
                ("curl", "https://a.org/x"),
                NetworkRequestTargetKind.URL,
                ContentDiscarded(),
                "a.org",
            ),
        ),
        True,
    ),
    (
        treat_host_target_that_may_receive_content_as_other_web,
        (
            _request(
                ("nc", "api"),
                NetworkRequestTargetKind.HOST,
                ContentShownInResult(),
                "api",
            ),
        ),
        True,
    ),
    (
        treat_saved_content_from_package_registry_host_as_fetched_file,
        (
            _request(
                ("wget", "https://pypi.org/packages/x.whl"),
                NetworkRequestTargetKind.URL,
                ContentSaved("x.whl"),
                "pypi.org",
            ),
        ),
        True,
    ),
    (
        treat_content_piped_to_consuming_command_as_other_web,
        (
            _request(
                ("curl", "https://a.org/x.tgz"),
                NetworkRequestTargetKind.URL,
                ContentPipedToCommand(1, OutputVisibility.NONE),
                "a.org",
            ),
        ),
        True,
    ),
    (
        treat_content_piped_to_showing_command_as_other_web,
        (
            _request(
                ("curl", "https://a.org/x"),
                NetworkRequestTargetKind.URL,
                ContentPipedToCommand(1, OutputVisibility.PARTIAL),
                "a.org",
            ),
        ),
        True,
    ),
    (
        treat_shown_content_from_search_engine_host_as_other_web,
        (
            _request(
                ("curl", "https://duckduckgo.com/html?q=x"),
                NetworkRequestTargetKind.URL,
                ContentShownInResult(),
                "duckduckgo.com",
            ),
        ),
        True,
    ),
    (
        treat_shown_content_from_registry_or_model_hub_host_as_other_web,
        (
            _request(
                ("curl", "https://pypi.org/project/requests/"),
                NetworkRequestTargetKind.URL,
                ContentShownInResult(),
                "pypi.org",
            ),
        ),
        True,
    ),
    (
        treat_web_tool_request_without_host_name_as_internet_use,
        (
            _web_tool_request(
                HarnessTool("codex", "web_search_call"),
                "how to x?",
                NetworkRequestTargetKind.SEARCH_QUERY,
            ),
        ),
        True,
    ),
    (
        treat_request_without_host_name_as_sent_to_default_registry_host,
        (
            _request(
                ("apt-get", "update"),
                NetworkRequestTargetKind.PACKAGE_NAME,
                ContentSaved(None),
            ),
            PackageRegistry("apt", ("deb.debian.org", "archive.ubuntu.com")),
        ),
        ("deb.debian.org", "archive.ubuntu.com"),
    ),
    (
        treat_templated_host_name_as_unknown_internet_use,
        (
            _request(
                ("curl", "https://$HOST/x"),
                NetworkRequestTargetKind.URL,
                ContentShownInResult(),
                "$HOST",
            ),
        ),
        True,
    ),
    (
        treat_single_label_host_name_as_not_internet_use,
        (
            _request(
                ("curl", "http://db:5432/"),
                NetworkRequestTargetKind.URL,
                ContentShownInResult(),
                "db",
            ),
        ),
        True,
    ),
    (
        treat_reserved_host_name_as_unknown_internet_use,
        (
            _request(
                ("curl", "https://example.com/"),
                NetworkRequestTargetKind.URL,
                ContentShownInResult(),
                "example.com",
            ),
        ),
        True,
    ),
    (
        treat_local_host_name_of_web_tool_as_unknown_internet_use,
        (
            _web_tool_request(
                HarnessTool("claude-code", "WebFetch"),
                "http://localhost:3000/",
                NetworkRequestTargetKind.URL,
                "localhost",
            ),
        ),
        True,
    ),
    (
        treat_assumed_not_needed_result_as_upper_bound_only,
        (
            _assumed_result(
                NetworkRequestResultStopReason.NOT_NEEDED,
                OutputLineKind.ALREADY_PRESENT,
            ),
        ),
        True,
    ),
    (
        treat_assumed_failure_as_possibly_received,
        (
            _assumed_result(
                NetworkRequestResultStopReason.FAILED, OutputLineKind.CONNECTION_FAILED
            ),
        ),
        True,
    ),
    (
        treat_request_of_unknown_sender_as_possibly_from_task_environment,
        (PAGE_READ_ROW_FROM_UNKNOWN_SENDER,),
        True,
    ),
]


@pytest.mark.parametrize(("rule", "situation", "value"), JUDGMENT_RULE_CASES)
def test_each_rule_gives_its_provisional_value_and_counts_one_use_under_its_name(
    rule: Callable[..., object], situation: tuple[object, ...], value: object
):
    use_counts: Counter[str] = Counter()

    assert rule(*situation, use_counts=use_counts) == value
    assert use_counts == Counter({rule.__name__: 1})
