"""Extract the network requests of one trial from what its calls ran, asking which programs and code calls fetch and for which targets."""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call.model import (
    ExpandedToolCall,
    RanCodeText,
    RanCommand,
    RanShellText,
    RanText,
    RanTextSource,
)
from tb_internet_use.network_request._extract_code_network_requests import (
    extract_code_network_requests,
)
from tb_internet_use.network_request._extract_command_network_requests import (
    extract_command_network_requests,
)
from tb_internet_use.network_request._extract_web_tool_network_requests import (
    extract_web_tool_network_requests,
)
from tb_internet_use.network_request.model import (
    NetworkRequest,
    NoNetworkRequestReason,
)

if TYPE_CHECKING:
    # `NetworkRequestKnowledge` is passed in and named in annotations only, so that `extract_network_requests` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.network_request_knowledge import (
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

    A call that did not run gives the requests its text shows too, since how far a request got is decided from its output later, e.g. `pip install x` in a call that the harness refused.
    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts` under the name of the rule. Every program run and every code call that gives no request adds one to `no_network_request_counts` under its reason, except a call whose name already gave a request whose target the code does not show, e.g. the second `requests.get(base + path)`.
    A URL in code adds one when it would give an uncertain request but is dropped as a namespace URL or as a local or reserved URL, so `mylib.fetch("http://localhost:8000/x")` in Python adds two, one for the URL and one for the call.
    """
    return tuple(
        network_request
        for expanded_tool_call in expanded_tool_calls
        for network_request in _extract_tool_call_network_requests(
            expanded_tool_call,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
            no_network_request_counts=no_network_request_counts,
        )
    )


def _extract_tool_call_network_requests(
    expanded_tool_call: ExpandedToolCall,
    *,
    knowledge: NetworkRequestKnowledge,
    judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
) -> list[NetworkRequest]:
    """Extract the requests of one call, those of its commands by command id first, then those of its code texts in the order they ran, then those of its web tool steps, numbering them from 0 in the call.

    A command of a file that the call runs comes after the commands of the call's own text by its id, e.g. the curl of fetch.sh after `bash fetch.sh || pip install x`.
    """
    network_requests: list[NetworkRequest] = []
    for ran_command, ran_text_source in _ran_commands_in_id_order_of(
        expanded_tool_call.ran_texts
    ):
        network_requests += extract_command_network_requests(
            ran_command,
            ran_text_source,
            expanded_tool_call,
            len(network_requests),
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
            no_network_request_counts=no_network_request_counts,
        )
    for ran_text in expanded_tool_call.ran_texts:
        if isinstance(ran_text, RanCodeText):
            network_requests += extract_code_network_requests(
                ran_text,
                expanded_tool_call.tool_call.harness_tool_call.key,
                len(network_requests),
                knowledge=knowledge,
                judgment_rule_use_counts=judgment_rule_use_counts,
                no_network_request_counts=no_network_request_counts,
            )
    network_requests += extract_web_tool_network_requests(
        expanded_tool_call.tool_call,
        len(network_requests),
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    return network_requests


def _ran_commands_in_id_order_of(
    ran_texts: Sequence[RanText],
) -> list[tuple[RanCommand, RanTextSource]]:
    """Give every command of the shell texts that a call ran with the source of its text, in the order of the command ids, which are unique within the call."""
    return sorted(
        (
            (ran_command, ran_text.source)
            for ran_text in ran_texts
            if isinstance(ran_text, RanShellText)
            for ran_command in ran_text.ran_commands
        ),
        key=lambda ran_command_and_source: ran_command_and_source[0].shell_command.id,
    )
