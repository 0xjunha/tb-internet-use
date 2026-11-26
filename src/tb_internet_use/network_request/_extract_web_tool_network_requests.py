"""Extract the network requests of the web tool actions of one tool call, one per search query or URL, whether the action is the call's own or a step of a tool script.

A web tool sends from wherever its harness runs it, e.g. a provider's search, so where a request left from is computed from the tool when rows are exported and not written here.
"""

from collections import Counter

from tb_internet_use.network_request.judgment_rules import (
    treat_web_find_as_uncertain_request,
)
from tb_internet_use.network_request.model import (
    ContentShownInResult,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
)
from tb_internet_use.network_request.parse_url import parse_url
from tb_internet_use.tool_call.model import (
    ToolCall,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    indexed_action_steps_of,
)


def extract_web_tool_network_requests(
    tool_call: ToolCall,
    first_index_in_tool_call: int,
    *,
    judgment_rule_use_counts: Counter[str],
) -> tuple[NetworkRequest, ...]:
    """Extract one request per query of a web search and per URL of a web fetch or a web find, and one without a target for such an action that names none, in step order.

    The requests of a search and a fetch are confirmed, and those of a find are uncertain or confirmed as `treat_web_find_as_uncertain_request` says.
    Every request shows its content in the result, and its tool is the tool of the call, also for a step of a tool script, e.g. `exec` of Codex.
    """
    harness_tool = tool_call.harness_tool_call.tool
    network_requests: list[NetworkRequest] = []
    for step_index, action in indexed_action_steps_of(tool_call.action):
        match action:
            case WebSearchAction(queries=queries):
                targets = queries or (None,)
                target_kind = NetworkRequestTargetKind.SEARCH_QUERY
                uncertainty_reason = None
            case WebFetchAction(urls=urls):
                targets = urls or (None,)
                target_kind = NetworkRequestTargetKind.URL
                uncertainty_reason = None
            case WebFindAction(urls=urls):
                targets = urls or (None,)
                target_kind = NetworkRequestTargetKind.URL
                uncertainty_reason = (
                    NetworkRequestUncertaintyReason.FINDS_TEXT_IN_OPENED_PAGE
                    if treat_web_find_as_uncertain_request(
                        use_counts=judgment_rule_use_counts
                    )
                    else None
                )
            case _:
                continue
        for target in targets:
            network_requests.append(
                NetworkRequest(
                    tool_call_key=tool_call.harness_tool_call.key,
                    index_in_tool_call=first_index_in_tool_call + len(network_requests),
                    source=FromWebTool(step_index, harness_tool),
                    target=target,
                    target_kind=target_kind,
                    host_names=_host_names_of_target(target, target_kind),
                    received_content_destination=ContentShownInResult(),
                    certainty=NetworkRequestCertainty.CONFIRMED
                    if uncertainty_reason is None
                    else NetworkRequestCertainty.UNCERTAIN,
                    uncertainty_reason=uncertainty_reason,
                )
            )
    return tuple(network_requests)


def _host_names_of_target(
    target: str | None, target_kind: NetworkRequestTargetKind
) -> tuple[str, ...]:
    """Give the host that a URL target names, e.g. `("a.org",)` for `https://a.org/x`, and none for a search query, a missing target or a URL without a scheme."""
    if target is None or target_kind != NetworkRequestTargetKind.URL:
        return ()
    host_name = parse_url(target)
    return () if host_name is None else (host_name,)
