"""Tests for network_request/_extract_web_tool_network_requests.py, with made-up tool calls."""

from collections import Counter

import pytest

from tb_internet_use.network_request import _extract_web_tool_network_requests
from tb_internet_use.network_request._extract_web_tool_network_requests import (
    extract_web_tool_network_requests,
)
from tb_internet_use.network_request.model import (
    ContentShownInResult,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
)
from tb_internet_use.tool_call.model import (
    HarnessTool,
    HarnessToolCall,
    RunCommandAction,
    RunToolScriptAction,
    StartSubagentAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    UnknownAction,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
)

KEY = ToolCallKey("trial", "main", 1, 0)
WEB_TOOL = HarnessTool("claude-code", "WebSearch")
CODEX_EXEC = HarnessTool("codex", "exec")
SEARCH_QUERY = NetworkRequestTargetKind.SEARCH_QUERY
URL = NetworkRequestTargetKind.URL
WEB_FIND_RULE = "treat_web_find_as_uncertain_request"

# (case, action, requests as (target, target kind, hosts))
_CASES = [
    (
        "search",
        WebSearchAction(("a", "b")),
        [("a", SEARCH_QUERY, ()), ("b", SEARCH_QUERY, ())],
    ),
    ("search without a query", WebSearchAction(()), [(None, SEARCH_QUERY, ())]),
    (
        "fetch",
        WebFetchAction(("https://a.org/x", "http://localhost:8000/")),
        [
            ("https://a.org/x", URL, ("a.org",)),
            ("http://localhost:8000/", URL, ("localhost",)),
        ],
    ),
    ("fetch without a url", WebFetchAction(()), [(None, URL, ())]),
    # A query is no URL, so it names no host even when it is written like one.
    (
        "search for a url",
        WebSearchAction(("https://a.org/x",)),
        [("https://a.org/x", SEARCH_QUERY, ())],
    ),
    (
        "fetch of a url without a scheme",
        WebFetchAction(("a.org/x",)),
        [("a.org/x", URL, ())],
    ),
    (
        "find",
        WebFindAction(("https://a.org/guide",)),
        [("https://a.org/guide", URL, ("a.org",))],
    ),
    ("find without a url", WebFindAction(()), [(None, URL, ())]),
    ("unknown action", UnknownAction(), []),
    ("subagent", StartSubagentAction(), []),
    ("command", RunCommandAction("curl https://a.org"), []),
]


def _tool_call(
    action: ToolCallAction, harness_tool: HarnessTool = WEB_TOOL
) -> ToolCall:
    return ToolCall(HarnessToolCall(KEY, harness_tool, "", {}, None), action, None)


@pytest.mark.parametrize(
    ("action", "expected"),
    [case[1:] for case in _CASES],
    ids=[case[0] for case in _CASES],
)
def test_web_actions_give_one_request_per_query_or_url_or_one_without_a_target(
    action, expected
):
    network_requests = extract_web_tool_network_requests(
        _tool_call(action), 0, judgment_rule_use_counts=Counter()
    )

    assert [
        (request.target, request.target_kind, request.host_names)
        for request in network_requests
    ] == expected


def test_request_of_a_web_action_is_confirmed_shown_in_the_result_and_numbered():
    network_requests = extract_web_tool_network_requests(
        _tool_call(WebSearchAction(("a", "b"))), 4, judgment_rule_use_counts=Counter()
    )

    assert network_requests == tuple(
        NetworkRequest(
            tool_call_key=KEY,
            index_in_tool_call=index,
            source=FromWebTool(None, WEB_TOOL),
            target=query,
            target_kind=SEARCH_QUERY,
            host_names=(),
            received_content_destination=ContentShownInResult(),
            certainty=NetworkRequestCertainty.CONFIRMED,
            uncertainty_reason=None,
        )
        for index, query in ((4, "a"), (5, "b"))
    )


def test_web_step_of_a_tool_script_names_its_step_and_the_script_tool():
    script = RunToolScriptAction(
        "...",
        (
            RunCommandAction("ls"),
            WebFetchAction(("https://docs.example.org/guide",)),
            WebSearchAction(("q",)),
        ),
    )

    network_requests = extract_web_tool_network_requests(
        _tool_call(script, CODEX_EXEC), 0, judgment_rule_use_counts=Counter()
    )

    assert [
        (request.index_in_tool_call, request.source, request.target_kind)
        for request in network_requests
    ] == [
        (0, FromWebTool(1, CODEX_EXEC), URL),
        (1, FromWebTool(2, CODEX_EXEC), SEARCH_QUERY),
    ]


def test_web_find_rule_is_counted_once_per_find():
    judgment_rule_use_counts: Counter[str] = Counter()

    extract_web_tool_network_requests(
        _tool_call(
            RunToolScriptAction(
                None,
                (
                    WebFindAction(("https://a.org/x", "https://a.org/y")),
                    WebFindAction(()),
                    WebFetchAction(("https://a.org/z",)),
                ),
            )
        ),
        0,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    assert judgment_rule_use_counts == Counter({WEB_FIND_RULE: 2})


@pytest.mark.parametrize(
    ("answer", "certainty", "uncertainty_reason"),
    [
        (
            True,
            NetworkRequestCertainty.UNCERTAIN,
            NetworkRequestUncertaintyReason.FINDS_TEXT_IN_OPENED_PAGE,
        ),
        (False, NetworkRequestCertainty.CONFIRMED, None),
    ],
    ids=["uncertain", "confirmed on the other answer"],
)
def test_web_find_gives_requests_whose_certainty_the_rule_says(
    monkeypatch: pytest.MonkeyPatch,
    answer: bool,
    certainty: NetworkRequestCertainty,
    uncertainty_reason: NetworkRequestUncertaintyReason | None,
):
    monkeypatch.setattr(
        _extract_web_tool_network_requests,
        WEB_FIND_RULE,
        lambda *, use_counts: answer,
    )

    network_requests = extract_web_tool_network_requests(
        _tool_call(WebFindAction(("https://a.org/guide", "https://b.org/x"))),
        0,
        judgment_rule_use_counts=Counter(),
    )

    assert [
        (request.certainty, request.uncertainty_reason) for request in network_requests
    ] == [(certainty, uncertainty_reason)] * 2
