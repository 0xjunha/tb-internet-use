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
    treat_content_piped_to_consuming_command_as_other_web,
    treat_content_piped_to_showing_command_as_other_web,
    treat_discarded_content_as_other_web,
    treat_host_target_that_may_receive_content_as_other_web,
    treat_repository_request_for_no_content_as_other_web,
    treat_saved_content_from_package_registry_host_as_fetched_file,
    treat_shown_content_from_registry_or_model_hub_host_as_other_web,
    treat_shown_content_from_search_engine_host_as_other_web,
    treat_url_query_value_and_fragment_as_credential,
)
from tb_internet_use.network_request.model import (
    ContentDiscarded,
    ContentPipedToCommand,
    ContentSaved,
    ContentShownInResult,
    FromCommand,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoContentRequested,
    ReceivedContentDestination,
)
from tb_internet_use.tool_call.model import ToolCallKey


def _request(
    words: tuple[str, ...],
    target_kind: NetworkRequestTargetKind,
    received_content_destination: ReceivedContentDestination,
    host_name: str,
) -> NetworkRequest:
    """Make the request of a made-up command for the situation of a category rule, which reads none of its fields."""
    return NetworkRequest(
        tool_call_key=ToolCallKey("t1", "main", 1, 0),
        index_in_tool_call=0,
        source=FromCommand(
            0, CallCommandText(), UnknownProgramInvocation(words[0], words[1:])
        ),
        target=words[-1],
        target_kind=target_kind,
        host_names=(host_name,),
        received_content_destination=received_content_destination,
        certainty=NetworkRequestCertainty.UNCERTAIN,
        uncertainty_reason=NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM,
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
]


@pytest.mark.parametrize(("rule", "situation", "value"), JUDGMENT_RULE_CASES)
def test_each_rule_gives_its_provisional_value_and_counts_one_use_under_its_name(
    rule: Callable[..., object], situation: tuple[object, ...], value: object
):
    use_counts: Counter[str] = Counter()

    assert rule(*situation, use_counts=use_counts) == value
    assert use_counts == Counter({rule.__name__: 1})
