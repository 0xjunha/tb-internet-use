"""Extract the network requests of one trial from what its calls ran, asking which programs and code calls fetch and for which targets."""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call.model import ExpandedToolCall
from tb_internet_use.network_request.model import (
    NetworkRequest,
    NoNetworkRequestReason,
)

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that `extract_network_requests` never loads `knowledge/` itself.
    # The door module does not exist yet, so pyright is told to skip the missing import until it does.
    from tb_internet_use.knowledge.network_request_knowledge import (  # pyright: ignore[reportMissingImports]
        NetworkRequestKnowledge,
    )


def extract_network_requests(
    expanded_tool_calls: Sequence[ExpandedToolCall],
    *,
    knowledge: NetworkRequestKnowledge,
    judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
) -> tuple[NetworkRequest, ...]:
    """Extract the network requests of every expanded tool call of one trial, in call order, and within a call by command id, then code text, then web tool step.

    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts` under the name of the rule. Every program run, code call or URL in code that gives no request adds one to `no_network_request_counts` under its reason.
    It returns an empty tuple for every input, the same value as for a trial whose calls made no request.
    """
    return ()
