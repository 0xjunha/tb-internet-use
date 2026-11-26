"""Tests for export/judgment_rules.py, with one table that holds a made-up situation of each rule and the value the rule gives, and a check that each use is counted under the name of the rule."""

import dataclasses
from collections import Counter
from collections.abc import Callable

import pytest
from made_up_network_request_rows import build_network_request_row

from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    UnknownProgramInvocation,
)
from tb_internet_use.export.judgment_rules import (
    treat_assumed_failure_as_possibly_received,
    treat_assumed_not_needed_result_as_upper_bound_only,
    treat_discarded_content_as_connectivity_check,
    treat_host_name_with_empty_label_as_unknown_internet_use,
    treat_host_target_that_may_receive_content_as_other_web,
    treat_local_or_single_label_host_name_of_web_tool_as_unknown_internet_use,
    treat_repository_request_for_no_content_as_other_web,
    treat_request_of_unknown_sender_as_possibly_from_task_environment,
    treat_request_without_host_name_as_sent_to_default_registry_host,
    treat_reserved_host_name_as_unknown_internet_use,
    treat_saved_content_from_unrecognized_url_as_content_fetch,
    treat_single_label_host_name_as_not_internet_use,
    treat_templated_host_name_as_unknown_internet_use,
    treat_trial_with_success_line_shared_by_confirmed_requests_as_received,
    treat_url_query_value_and_fragment_as_credential,
    treat_url_request_to_package_registry_host_as_package,
    treat_url_request_to_search_engine_host_as_search,
    treat_url_request_without_path_or_query_to_package_registry_or_search_engine_host_as_connectivity_check,
    treat_variable_without_program_variable_row_as_not_changing_package_registry,
    treat_web_tool_request_without_url_as_internet_use,
    treat_web_tool_url_without_host_name_as_unknown_internet_use,
)
from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
    NetworkRequestSourceKind,
    PackageRegistry,
    UnknownChangesPackageRegistry,
    UnknownPackageRegistry,
    UnknownProgramVariable,
)
from tb_internet_use.network_request.model import (
    ContentDiscarded,
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
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetReason,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResult,
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
    SharedOutputLineAssumptionReason,
)
from tb_internet_use.tool_call.model import HarnessTool, ToolCallKey


def _request(
    words: tuple[str, ...],
    target_kind: NetworkRequestTargetKind,
    received_content_destination: ReceivedContentDestination,
    *host_names: str,
) -> NetworkRequest:
    """Make the request of a made-up command for the situation of a rule.

    Of its fields only `target` is read, by `treat_request_without_host_name_as_sent_to_default_registry_host`.
    """
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
        assumption_reasons=(
            SharedOutputLineAssumptionReason(ToolCallKey("t1", "main", 1, 0), 0, None),
        ),
    )


CONTENT_FETCH_ROW_FROM_UNKNOWN_SENDER = NetworkRequestRow(
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
    category=NetworkRequestCategory.CONTENT_FETCH,
    host_scope="public",
    host_service="unknown",
    package_registry="",
    is_internet_use=True,
    sender=NetworkRequestSender.UNKNOWN,
    result_view=NetworkRequestResultView.RECEIVED,
    request_measure_bound=MeasureBound.LOWER_AND_UPPER,
    received_measure_bound=MeasureBound.UPPER_ONLY,
    is_among_success_line_owners_one_of_which_received=False,
)

# A row with the category, sender and bounds of each of `apt-get install -y a b` under one `Fetched 10 kB in 1s` that both own, whose other columns are those of a `curl` that saved what it received.
PACKAGE_ROW_RECEIVED_IN_UPPER_BOUND_ONLY = build_network_request_row(
    NetworkRequestCategory.PACKAGE,
    NetworkRequestSender.TASK_ENVIRONMENT,
    MeasureBound.LOWER_AND_UPPER,
    MeasureBound.UPPER_ONLY,
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
        treat_discarded_content_as_connectivity_check,
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
        treat_url_request_without_path_or_query_to_package_registry_or_search_engine_host_as_connectivity_check,
        (
            _request(
                ("curl", "https://pypi.org"),
                NetworkRequestTargetKind.URL,
                ContentShownInResult(),
                "pypi.org",
            ),
        ),
        True,
    ),
    (
        treat_url_request_to_package_registry_host_as_package,
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
        treat_url_request_to_search_engine_host_as_search,
        (
            _request(
                ("curl", "https://html.duckduckgo.com/html?q=x"),
                NetworkRequestTargetKind.URL,
                ContentShownInResult(),
                "html.duckduckgo.com",
            ),
        ),
        True,
    ),
    (
        treat_saved_content_from_unrecognized_url_as_content_fetch,
        (
            _request(
                ("curl", "https://a.org/x"),
                NetworkRequestTargetKind.URL,
                ContentSaved("x"),
                "a.org",
            ),
        ),
        True,
    ),
    (
        treat_web_tool_request_without_url_as_internet_use,
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
        treat_web_tool_url_without_host_name_as_unknown_internet_use,
        (
            _web_tool_request(
                HarnessTool("claude-code", "WebFetch"),
                "file:///app/x.html",
                NetworkRequestTargetKind.URL,
            ),
        ),
        True,
    ),
    (
        treat_variable_without_program_variable_row_as_not_changing_package_registry,
        (
            _request(
                ("npx", "x"),
                NetworkRequestTargetKind.PACKAGE_NAME,
                ContentSaved(None),
            ),
            "PORT",
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
            {},
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
        treat_host_name_with_empty_label_as_unknown_internet_use,
        (
            _request(
                ("curl", "..."),
                NetworkRequestTargetKind.URL,
                ContentShownInResult(),
                "...",
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
        treat_local_or_single_label_host_name_of_web_tool_as_unknown_internet_use,
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
        (CONTENT_FETCH_ROW_FROM_UNKNOWN_SENDER,),
        True,
    ),
    (
        treat_trial_with_success_line_shared_by_confirmed_requests_as_received,
        (
            [
                dataclasses.replace(
                    PACKAGE_ROW_RECEIVED_IN_UPPER_BOUND_ONLY, request_index=index
                )
                for index in (0, 1)
            ],
        ),
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


# (answers of `ExportKnowledge.changes_package_registry` by variable name for a made-up `pkg install x` with a registry row, the hosts that the rule gives)
_DEFAULT_REGISTRY_CASES_BY_VARIABLE_ANSWERS = [
    # No `NAME=value` before the command name, e.g. `pkg install x`.
    ({}, ("reg.org",)),
    # Variables that the program reads for something else, e.g. `MODE=quiet pkg install x`.
    ({"MODE": False}, ("reg.org",)),
    ({"MODE": False, "HOME": False}, ("reg.org",)),
    # A variable that names another index, e.g. `PKG_INDEX=http://localhost:3141 pkg install x`, also beside one read for something else.
    ({"PKG_INDEX": True}, ()),
    ({"MODE": False, "PKG_INDEX": True}, ()),
    # A variable whose row leaves its answer blank, e.g. `GOPATH=/x pkg install x`, may change the registry too.
    ({"GOPATH": UnknownChangesPackageRegistry()}, ()),
    ({"MODE": False, "GOPATH": UnknownChangesPackageRegistry()}, ()),
    # A variable without a row that `treat_variable_without_program_variable_row_as_not_changing_package_registry` did not take as one that leaves the registry.
    ({"PORT": UnknownProgramVariable()}, ()),
]


@pytest.mark.parametrize(
    ("changes_package_registry_by_variable_name", "host_names"),
    _DEFAULT_REGISTRY_CASES_BY_VARIABLE_ANSWERS,
)
def test_default_registry_holds_only_when_every_variable_before_the_command_name_leaves_it(
    changes_package_registry_by_variable_name: dict[
        str, bool | UnknownChangesPackageRegistry | UnknownProgramVariable
    ],
    host_names: tuple[str, ...],
):
    use_counts: Counter[str] = Counter()
    network_request = _request(
        ("pkg", "install", "x"),
        NetworkRequestTargetKind.PACKAGE_NAME,
        ContentSaved(None),
    )

    assert (
        treat_request_without_host_name_as_sent_to_default_registry_host(
            network_request,
            PackageRegistry("reg", ("reg.org",)),
            changes_package_registry_by_variable_name,
            use_counts=use_counts,
        )
        == host_names
    )
    assert use_counts == Counter(
        {treat_request_without_host_name_as_sent_to_default_registry_host.__name__: 1}
    )


def test_variables_do_not_matter_for_a_local_path_or_a_program_without_a_registry():
    use_counts: Counter[str] = Counter()
    local_path_request = dataclasses.replace(
        _request(
            ("pkg", "install", "."),
            NetworkRequestTargetKind.PACKAGE_NAME,
            ContentSaved(None),
        ),
        target=UnknownNetworkRequestTarget(
            UnknownNetworkRequestTargetReason.LOCAL_PATH
        ),
    )
    request = _request(
        ("pkg", "install", "x"),
        NetworkRequestTargetKind.PACKAGE_NAME,
        ContentSaved(None),
    )

    for network_request, package_registry in (
        (local_path_request, PackageRegistry("reg", ("reg.org",))),
        (request, UnknownPackageRegistry()),
        (request, None),
    ):
        assert (
            treat_request_without_host_name_as_sent_to_default_registry_host(
                network_request,
                package_registry,
                {"MODE": False},
                use_counts=use_counts,
            )
            == ()
        )
