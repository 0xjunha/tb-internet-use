"""Extract the network requests of one Python or JavaScript code text from its calls and from the URLs it writes outside them, asking the code call catalog which calls fetch.

Code is not split into commands, so a request is found by the call that sends it, e.g. `requests.get("https://a.org/x")`.
A call is asked about under the full name that an import of the text gives its first name part, e.g. `requests.get` for `rq.get(u)` after `import requests as rq`, since a catalog row names a call by its full name.
A URL that may be public and that no known call holds gives an uncertain request of its own, e.g. `BASE = "https://a.org"`, since whether the code fetches it depends on the flow of the code.
"""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call.model import (
    CodeLanguage,
    PollInputText,
    RanCodeText,
)
from tb_internet_use.network_request._extract_command_network_requests import (
    urls_that_may_be_public,
)
from tb_internet_use.network_request.judgment_rules import (
    treat_call_name_that_ends_with_catalog_name_as_uncertain_call_of_that_name,
    treat_call_of_module_row_through_name_that_code_binds_without_import_as_call_without_row,
    treat_url_of_namespace_host_as_no_target,
)
from tb_internet_use.network_request.model import (
    CodeCall,
    CodeCallEffect,
    CodeCallLabel,
    FromCode,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoNetworkRequestReason,
    ParsedCode,
    TargetNotation,
    UnknownCodeCall,
    UnknownCodeCallLabel,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetKind,
    UnknownNetworkRequestTargetReason,
    UnknownProgramNetworkRequestLabel,
    UnknownReceivedContentDestination,
)
from tb_internet_use.network_request.parse_code import (
    BARE_NAME_PATTERN_OF_LANGUAGE,
    parse_code,
)
from tb_internet_use.network_request.parse_target import parse_target
from tb_internet_use.network_request.parse_url import SCHEME_AND_SLASHES, parse_url
from tb_internet_use.network_request.parse_urls_in_text import parse_urls_in_text
from tb_internet_use.tool_call.model import ToolCallKey

if TYPE_CHECKING:
    # `NetworkRequestKnowledge` is passed in and named in annotations only, so that this module never loads `knowledge/` itself.
    from tb_internet_use.knowledge.network_request_knowledge import (
        NetworkRequestKnowledge,
    )

# The start of an argument text whose first argument is a tuple whose first element is one whole string, e.g. `("api", 8000)` but not `("172.18.0." + str(i), 80)`.
_TUPLE_OPENING_WITH_WHOLE_STRING = re.compile(r"""\s*\(\s*(["'])[^"'\\]*\1\s*,""")
# A port that closes the authority of a URL, e.g. `:8069` of `name:8069`.
_PORT_AT_END = re.compile(r":[0-9]+$")
# A placeholder of one bare name at the start of a string, e.g. `{BASE}` of the Python f-string `f"{BASE}/config"` or `${BASE}` of the JavaScript template literal `` `${BASE}/config` ``.
_LEADING_PLACEHOLDER_OF_LANGUAGE = {
    CodeLanguage.PYTHON: re.compile(
        rf"\{{({BARE_NAME_PATTERN_OF_LANGUAGE[CodeLanguage.PYTHON]})\}}"
    ),
    CodeLanguage.JAVASCRIPT: re.compile(
        rf"\$\{{({BARE_NAME_PATTERN_OF_LANGUAGE[CodeLanguage.JAVASCRIPT]})\}}"
    ),
}


def extract_code_network_requests(
    ran_code_text: RanCodeText,
    tool_call_key: ToolCallKey,
    first_index_in_tool_call: int,
    *,
    knowledge: NetworkRequestKnowledge,
    judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
) -> tuple[NetworkRequest, ...]:
    """Extract the requests of one code text in the order of its calls, then those of the URLs that may be public outside every call.

    A call that sends a request gives one confirmed request per call when its target is in the text, and one per call name, hosts and uncertainty reason when it is not, e.g. one for all the calls `requests.get(base + path)` and another for `requests.get('http://name:8069' + path)`.
    A call that holds the target of a request gives no request when a sending call reads the target from it, e.g. `Request` of `urlopen(Request(u))`.
    A call whose name a judgment rule matches to a row only at its end, also after an import gives its full name, or through a first name part that the text binds otherwise, gives an uncertain request, e.g. `self.page.goto(u)` or `GPT2TokenizerFast.from_pretrained(m)` after `from transformers import GPT2TokenizerFast`.
    A call without a row, a Python call whose row names a module that the code reaches through a name that it binds to something else and does not import, e.g. `requests.get(rid)` after `requests = {}`, or one that holds a target that no sending call reads, gives one uncertain request per URL that may be public or whose host cannot be read, and the text outside every call one per URL that may be public.
    Text that `parse_code` could not read to its end holds no call that it read, so its URLs give requests as URLs outside every call, e.g. the URL after an unclosed backtick in ``x = `; fetch("https://a.org/x")``.
    Every request gets `UnknownReceivedContentDestination`, since what code does with the content is not read.
    """
    code_language = ran_code_text.code_language
    parsed_code = parse_code(ran_code_text.code, code_language)
    code_text_requests = _CodeTextRequests(
        tool_call_key, ran_code_text, first_index_in_tool_call
    )
    code_call_labels_and_uncertainty_reasons = [
        _code_call_label_and_uncertainty_reason_of(
            code_call,
            code_language,
            parsed_code,
            knowledge,
            judgment_rule_use_counts,
        )
        for code_call in parsed_code.code_calls
    ]
    code_call_labels = tuple(
        code_call_label
        for code_call_label, _ in code_call_labels_and_uncertainty_reasons
    )
    target_holding_call_of_sending_call_index = {
        code_call_index: target_holding_call
        for code_call_index, (code_call, code_call_label) in enumerate(
            zip(parsed_code.code_calls, code_call_labels, strict=True)
        )
        if isinstance(code_call_label, CodeCallLabel)
        and code_call_label.effect == CodeCallEffect.SENDS_NETWORK_REQUEST
        and (
            target_holding_call := _target_holding_call_of(
                code_call, parsed_code, code_call_labels
            )
        )
        is not None
    }
    read_holding_call_indexes = {
        holding_call_index
        for holding_call_index, _ in target_holding_call_of_sending_call_index.values()
    }
    for code_call_index, (
        code_call,
        (code_call_label, uncertainty_reason),
    ) in enumerate(
        zip(
            parsed_code.code_calls,
            code_call_labels_and_uncertainty_reasons,
            strict=True,
        )
    ):
        match code_call_label:
            case UnknownCodeCallLabel():
                _add_requests_of_urls_in_strings(
                    code_call,
                    UnknownCodeCall(),
                    NetworkRequestUncertaintyReason.UNKNOWN_CODE_CALL,
                    code_text_requests,
                    judgment_rule_use_counts=judgment_rule_use_counts,
                    no_network_request_counts=no_network_request_counts,
                )
            case CodeCallLabel(effect=CodeCallEffect.HOLDS_NETWORK_REQUEST_TARGET):
                if code_call_index not in read_holding_call_indexes:
                    _add_requests_of_urls_in_strings(
                        code_call,
                        UnknownCodeCall(),
                        NetworkRequestUncertaintyReason.UNKNOWN_CODE_CALL,
                        code_text_requests,
                        judgment_rule_use_counts=judgment_rule_use_counts,
                        no_network_request_counts=no_network_request_counts,
                    )
            case CodeCallLabel(effect=CodeCallEffect.SENDS_NO_NETWORK_REQUEST):
                no_network_request_counts[
                    NoNetworkRequestReason.NON_FETCHING_CODE_CALL
                ] += 1
            case CodeCallLabel(effect=CodeCallEffect.RUNS_PROGRAM):
                _add_program_run_by_code_network_requests(
                    code_call,
                    code_call_label.call_name,
                    code_text_requests,
                    knowledge=knowledge,
                    judgment_rule_use_counts=judgment_rule_use_counts,
                    no_network_request_counts=no_network_request_counts,
                )
            case CodeCallLabel():
                target_holding_call = target_holding_call_of_sending_call_index.get(
                    code_call_index
                )
                if target_holding_call is None:
                    target_code_call, target_code_call_label = (
                        code_call,
                        code_call_label,
                    )
                else:
                    holding_call_index, target_code_call_label = target_holding_call
                    target_code_call = parsed_code.code_calls[holding_call_index]
                _add_sending_code_call_network_request(
                    code_call_label.call_name,
                    target_code_call,
                    target_code_call_label,
                    parsed_code,
                    code_text_requests,
                    uncertainty_reason=uncertainty_reason,
                )
    for url in _select_urls_that_may_be_requested(
        _urls_outside_call_arguments(
            ran_code_text.code,
            parsed_code,
            code_text_requests.target_assignment_values,
        ),
        judgment_rule_use_counts=judgment_rule_use_counts,
        no_network_request_counts=no_network_request_counts,
    ):
        code_text_requests.add(
            UnknownCodeCall(),
            url,
            NetworkRequestTargetKind.URL,
            _host_names_of_urls((url,)),
            NetworkRequestUncertaintyReason.URL_OUTSIDE_CODE_CALL,
        )
    return tuple(code_text_requests.network_requests)


@dataclass(slots=True)
class _CodeTextRequests:
    """Requests of one code text kept during one `extract_code_network_requests` call, which numbers them within the tool call as they are added."""

    tool_call_key: ToolCallKey
    ran_code_text: RanCodeText
    first_index_in_tool_call: int
    network_requests: list[NetworkRequest] = field(default_factory=list)
    # The call names, each with the hosts and the uncertainty reason of its request, that already gave a request whose target the text does not show, so that a second such call of the name, hosts and reason gives none.
    # The hosts are part of it so that a call whose hosts are not known stays visible beside one whose hosts are, e.g. `requests.get(u)` beside `requests.get('http://name:8069' + path)`, and the reason so that a confirmed request stays beside an uncertain one, e.g. `page.goto(u)` beside `self.page.goto(u)`.
    call_names_host_names_and_uncertainty_reasons_without_visible_target: set[
        tuple[str, tuple[str, ...], NetworkRequestUncertaintyReason | None]
    ] = field(default_factory=set)
    # The string values whose assignment gave a call its target, so that their URLs are not counted again outside every call.
    target_assignment_values: set[str] = field(default_factory=set)

    def add(
        self,
        call_name: str | UnknownCodeCall,
        target: str | UnknownNetworkRequestTarget,
        target_kind: NetworkRequestTargetKind | UnknownNetworkRequestTargetKind,
        host_names: tuple[str, ...],
        uncertainty_reason: NetworkRequestUncertaintyReason | None,
    ) -> None:
        """Add one request of the code text with the next index of the tool call."""
        source = self.ran_code_text.source
        self.network_requests.append(
            NetworkRequest(
                tool_call_key=self.tool_call_key,
                index_in_tool_call=self.first_index_in_tool_call
                + len(self.network_requests),
                source=FromCode(
                    runner_command_id=None
                    if isinstance(source, PollInputText)
                    else source.runner_command_id,
                    code_text_source=source,
                    code_language=self.ran_code_text.code_language,
                    call_name=call_name,
                ),
                target=target,
                target_kind=target_kind,
                host_names=host_names,
                received_content_destination=UnknownReceivedContentDestination(),
                certainty=NetworkRequestCertainty.CONFIRMED
                if uncertainty_reason is None
                else NetworkRequestCertainty.UNCERTAIN,
                uncertainty_reason=uncertainty_reason,
            )
        )


def _code_call_label_and_uncertainty_reason_of(
    code_call: CodeCall,
    code_language: CodeLanguage,
    parsed_code: ParsedCode,
    knowledge: NetworkRequestKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[
    CodeCallLabel | UnknownCodeCallLabel, NetworkRequestUncertaintyReason | None
]:
    """Find the label of a call from the row of the name it stands for, with the reason that the request it sends itself is uncertain, None when that request is confirmed or the call sends none itself.

    A call whose first name part an import of the text binds is read by `_imported_code_call_label_and_uncertainty_reason_of`.
    Any other call takes the row of its name as written, else of the longest end of it with a row, e.g. `page.goto` for `self.page.goto`, and two judgment rules decide what it makes of the row.
    A row of a module is set aside when the text binds the first name part to something else, e.g. for `requests.get(rid)` after `requests = {}`.
    A row of an end of the name, or of the whole name after the text binds its first part, makes an uncertain call, e.g. `self.page.goto(u)` or `page.goto(u)` after `page = browser.new_page()`.
    A whole name with a row whose first part the text neither imports nor binds keeps its row, e.g. `fetch(u)` or `subprocess.run(cmd)` after `from helpers import *`.
    A row that a rule sets aside still counts as a use of the row, since it decided the call.
    """
    first_name_part, dot, name_rest = code_call.name.partition(".")
    imported_full_names = parsed_code.imported_full_names_by_name.get(
        first_name_part, ()
    )
    if imported_full_names:
        return _imported_code_call_label_and_uncertainty_reason_of(
            tuple(
                imported_full_name + dot + name_rest
                for imported_full_name in imported_full_names
            ),
            code_call.name,
            code_language,
            knowledge,
            judgment_rule_use_counts,
        )
    catalog_call_name = _catalog_call_name_of(code_call.name, code_language, knowledge)
    if catalog_call_name is None:
        return knowledge.code_call_label(code_language, code_call.name), None
    code_call_label = knowledge.code_call_label(code_language, catalog_call_name)
    assert isinstance(code_call_label, CodeCallLabel)
    names_bound_by_assignment_parameter_or_loop = (
        parsed_code.names_bound_by_assignment_parameter_or_loop
    )
    if (
        catalog_call_name == code_call.name
        and first_name_part not in names_bound_by_assignment_parameter_or_loop
    ):
        return code_call_label, None
    if (
        code_call_label.module_name is not None
        and treat_call_of_module_row_through_name_that_code_binds_without_import_as_call_without_row(
            first_name_part,
            names_bound_by_assignment_parameter_or_loop,
            use_counts=judgment_rule_use_counts,
        )
    ):
        return UnknownCodeCallLabel(), None
    return _label_and_uncertainty_reason_of_call_that_may_be_another_function(
        code_call.name,
        code_call_label,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )


def _imported_code_call_label_and_uncertainty_reason_of(
    full_call_names: tuple[str, ...],
    call_name: str,
    code_language: CodeLanguage,
    knowledge: NetworkRequestKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[
    CodeCallLabel | UnknownCodeCallLabel, NetworkRequestUncertaintyReason | None
]:
    """Find the label of a call whose first name part imports bind, from the full names that they give in the order of the text, with the reason that the request it sends itself is uncertain, as `_code_call_label_and_uncertainty_reason_of` gives it.

    Each full name takes its own row, else the row of its longest end, e.g. `urllib.request.urlopen` for `u.urlopen(x)` after `import urllib.request as u`, or `from_pretrained` for `transformers.GPT2TokenizerFast.from_pretrained` after `from transformers import GPT2TokenizerFast`.
    The call keeps the row when one import binds the name and its full name has the row. Otherwise it is an uncertain call of the row of the first full name with one, by the judgment rule on ends of names, e.g. `requests.get` for `http.get(u)` after `import requests as http` in a `try` and `import httpx as http` in its `except`.
    So several imports of one name never confirm a call, since they bind it to different full names, which share no row of the whole name.
    When no full name nor an end of it has a row, the call takes the row of its name as written or of its longest end, as an uncertain call too, since a module may give a function under the name of a catalog row, e.g. `fetch` for `fetch(u)` after `const fetch = require("node-fetch")`.
    The rule on rows of a module is not asked, since an import wins over an assignment.
    A call without any such row is a call without a row, counted as an unknown input under the first full name, e.g. `mylib.compute` for `m.compute(x)` after `import mylib as m`.
    """
    catalog_call_names = [
        _catalog_call_name_of(full_call_name, code_language, knowledge)
        for full_call_name in full_call_names
    ]
    first_catalog_call_name = next(
        (
            catalog_call_name
            for catalog_call_name in catalog_call_names
            if catalog_call_name is not None
        ),
        None,
    )
    if first_catalog_call_name is None:
        first_catalog_call_name = _catalog_call_name_of(
            call_name, code_language, knowledge
        )
        if first_catalog_call_name is None:
            return knowledge.code_call_label(code_language, full_call_names[0]), None
    code_call_label = knowledge.code_call_label(code_language, first_catalog_call_name)
    assert isinstance(code_call_label, CodeCallLabel)
    if full_call_names == (first_catalog_call_name,):
        return code_call_label, None
    return _label_and_uncertainty_reason_of_call_that_may_be_another_function(
        call_name, code_call_label, judgment_rule_use_counts=judgment_rule_use_counts
    )


def _catalog_call_name_of(
    call_name: str, code_language: CodeLanguage, knowledge: NetworkRequestKnowledge
) -> str | None:
    """Find the name of the row that a call name takes, the name itself when it has a row, else its longest end with a row, e.g. `page.goto` for `self.page.goto`, or None."""
    if knowledge.has_code_call_row(code_language, call_name):
        return call_name
    name_parts = call_name.split(".")
    for start in range(1, len(name_parts)):
        call_name_end = ".".join(name_parts[start:])
        if knowledge.has_code_call_row(code_language, call_name_end):
            return call_name_end
    return None


def _label_and_uncertainty_reason_of_call_that_may_be_another_function(
    call_name: str,
    code_call_label: CodeCallLabel,
    *,
    judgment_rule_use_counts: Counter[str],
) -> tuple[
    CodeCallLabel | UnknownCodeCallLabel, NetworkRequestUncertaintyReason | None
]:
    """Give the label of a call that the text does not show to be the function of its row, with the reason its own request is uncertain, as the judgment rule on ends of names decides.

    On the answer of an uncertain call, a row that sends a request gives `CALL_NAME_MAY_BE_ANOTHER_FUNCTION`, and a row that sends no request makes a call without a row, since another function of that name may send one.
    """
    if not treat_call_name_that_ends_with_catalog_name_as_uncertain_call_of_that_name(
        call_name, use_counts=judgment_rule_use_counts
    ):
        return code_call_label, None
    match code_call_label.effect:
        case CodeCallEffect.SENDS_NO_NETWORK_REQUEST:
            return UnknownCodeCallLabel(), None
        case CodeCallEffect.SENDS_NETWORK_REQUEST:
            return (
                code_call_label,
                NetworkRequestUncertaintyReason.CALL_NAME_MAY_BE_ANOTHER_FUNCTION,
            )
        case _:
            return code_call_label, None


def _target_holding_call_of(
    code_call: CodeCall,
    parsed_code: ParsedCode,
    code_call_labels: tuple[CodeCallLabel | UnknownCodeCallLabel, ...],
) -> tuple[int, CodeCallLabel] | None:
    """Find the call that holds the target of a sending call, as its 0-based index in `ParsedCode.code_calls` with its label, or None.

    It is the call that the first argument is, e.g. `Request` of `urlopen(Request(u))`, or the one call assigned to the bare name that the first argument is, when no string is assigned to that name, e.g. `Request` of `urlopen(req)` after `req = Request(u)`.
    The call must have a row that holds a target, so `urlopen(r)` after `r = requests.get(u)` reads no target from `requests.get`.
    """
    holding_call_index = code_call.first_argument_code_call_index
    first_argument_name = code_call.first_argument_name
    if (
        holding_call_index is None
        and first_argument_name is not None
        and not any(
            assignment.name == first_argument_name
            for assignment in parsed_code.string_assignments
        )
    ):
        assigned_call_indexes = [
            assignment.code_call_index
            for assignment in parsed_code.call_assignments
            if assignment.name == first_argument_name
        ]
        if len(assigned_call_indexes) == 1:
            holding_call_index = assigned_call_indexes[0]
    if holding_call_index is None:
        return None
    code_call_label = code_call_labels[holding_call_index]
    if (
        isinstance(code_call_label, CodeCallLabel)
        and code_call_label.effect == CodeCallEffect.HOLDS_NETWORK_REQUEST_TARGET
    ):
        return holding_call_index, code_call_label
    return None


def _add_sending_code_call_network_request(
    call_name: str,
    target_code_call: CodeCall,
    target_code_call_label: CodeCallLabel,
    parsed_code: ParsedCode,
    code_text_requests: _CodeTextRequests,
    *,
    uncertainty_reason: NetworkRequestUncertaintyReason | None,
) -> None:
    """Add the request of a call that sends one, confirmed unless an uncertainty reason is given, with the target its text shows, or one request of unknown target per call name, hosts and uncertainty reason when the text shows none.

    The target is read from the target call by the target notation and kind of its row, and the target call is the sending call itself or the call that holds its target, e.g. `Request` of `urlopen(req)` after `req = Request("http://api:8000/x")`.
    The URLs in the other strings of the target call are no requests, e.g. the referer in `requests.get(u, headers={"Referer": "https://b.org"})`, and neither is a call around the sending call, e.g. `print` of `print(requests.get(u))`.
    A request of unknown target still names the hosts that its URL strings write whole, e.g. `name` for `requests.get('http://name:8069' + path)`.
    It also names the host that the one string assigned to the name its first argument starts with writes whole, e.g. `localhost` for `urlopen(BASE + path)` after `BASE = "http://localhost:5000/api"`.
    A target URL that starts with a placeholder of such a name names that host too, e.g. `localhost` for `urlopen(f"{BASE}/config")`.
    """
    target_notation = target_code_call_label.target_notation
    target_kind = target_code_call_label.target_kind
    assert target_notation is not None and target_kind is not None
    target_text = _target_text_of(target_code_call, target_notation, parsed_code)
    if target_text is None:
        host_names = _host_names_closed_in_url_strings(target_code_call)
        if target_code_call.first_argument_leading_name is not None:
            assigned_url_and_host_name = _assigned_url_and_host_name_of(
                target_code_call.first_argument_leading_name, parsed_code
            )
            if assigned_url_and_host_name is not None:
                assigned_url, host_name = assigned_url_and_host_name
                code_text_requests.target_assignment_values.add(assigned_url)
                host_names = tuple(dict.fromkeys((host_name, *host_names)))
        call_name_host_names_and_uncertainty_reason = (
            call_name,
            host_names,
            uncertainty_reason,
        )
        if (
            call_name_host_names_and_uncertainty_reason
            in code_text_requests.call_names_host_names_and_uncertainty_reasons_without_visible_target
        ):
            return
        code_text_requests.call_names_host_names_and_uncertainty_reasons_without_visible_target.add(
            call_name_host_names_and_uncertainty_reason
        )
        code_text_requests.add(
            call_name,
            UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.BUILT_IN_CODE
            ),
            target_kind,
            host_names,
            uncertainty_reason,
        )
        return
    if (
        target_code_call.first_argument_string is None
        and target_code_call.first_argument_name is not None
    ):
        code_text_requests.target_assignment_values.add(target_text)
    parsed_target = parse_target(target_text, target_notation)
    host_name = parsed_target.host_name
    leading_placeholder_name = (
        _leading_placeholder_name_of(
            target_text, code_text_requests.ran_code_text.code_language
        )
        if host_name is None and target_notation == TargetNotation.URL
        else None
    )
    if leading_placeholder_name is not None:
        assigned_url_and_host_name = _assigned_url_and_host_name_of(
            leading_placeholder_name, parsed_code
        )
        if assigned_url_and_host_name is not None:
            assigned_url, host_name = assigned_url_and_host_name
            code_text_requests.target_assignment_values.add(assigned_url)
    code_text_requests.add(
        call_name,
        target_text,
        target_kind if parsed_target.target_kind is None else parsed_target.target_kind,
        () if host_name is None else (host_name,),
        uncertainty_reason,
    )


def _host_names_closed_in_url_strings(code_call: CodeCall) -> tuple[str, ...]:
    """List the distinct hosts of the strings of a call that start with a URL whose host ends inside the string, e.g. `name` for `'http://name:8069'` in `'http://name:8069' + path`."""
    return tuple(
        dict.fromkeys(
            host_name
            for string_literal in code_call.string_literals
            if (host_name := _host_name_closed_in_url_string(string_literal))
            is not None
        )
    )


def _assigned_url_and_host_name_of(
    name: str, parsed_code: ParsedCode
) -> tuple[str, str] | None:
    """Find the one string assigned to a name with its host, when the string starts with a URL whose host ends inside it, e.g. `http://localhost:5000/api` and `localhost` for `BASE`."""
    assigned_string = _assigned_string_of(name, parsed_code)
    if assigned_string is None:
        return None
    host_name = _host_name_closed_in_url_string(assigned_string)
    return None if host_name is None else (assigned_string, host_name)


def _host_name_closed_in_url_string(string_value: str) -> str | None:
    """Find the host of a string that starts with a URL whose host ends inside the string, e.g. `name` for `'http://name:8069'`, or None.

    A host ends inside the string when `/`, `?` or `#` follows it there or a port closes it, e.g. `'http://a.org/'` or `'http://name:8069'`.
    A host that runs to the end of the string may go on outside it, so `'http://' + h` and `'http://api.' + domain` name no host.
    """
    scheme_match = SCHEME_AND_SLASHES.match(string_value)
    if scheme_match is None:
        return None
    rest = string_value[scheme_match.end() :]
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if len(authority) == len(rest) and not _PORT_AT_END.search(authority):
        return None
    return parse_url(string_value)


def _leading_placeholder_name_of(
    target_text: str, code_language: CodeLanguage
) -> str | None:
    """Find the bare name of the placeholder that a target text starts with, e.g. `BASE` of `{BASE}/config` in Python or of `${BASE}/config` in JavaScript, or None, e.g. for `{cfg.base}/config`."""
    placeholder_match = _LEADING_PLACEHOLDER_OF_LANGUAGE[code_language].match(
        target_text
    )
    return None if placeholder_match is None else placeholder_match.group(1)


def _target_text_of(
    code_call: CodeCall, target_notation: TargetNotation, parsed_code: ParsedCode
) -> str | None:
    """Find the target that the text of a sending call shows, or None when the code builds it.

    A host and port tuple is read by `_target_text_of_host_and_port_tuple`.
    Any other target is the first argument when that is one string, else the value of the one assignment of the name that the first argument is, e.g. the URL of `URL = "https://a.org/x"` for `requests.get(URL)`.
    Any other string of the call may be some other argument, e.g. `config.json` of `hf_hub_download(repo_id=REPO, filename="config.json")`, so the target is built in code.
    """
    if target_notation == TargetNotation.HOST_AND_PORT_TUPLE:
        return _target_text_of_host_and_port_tuple(code_call)
    if code_call.first_argument_string is not None:
        return code_call.first_argument_string
    if code_call.first_argument_name is not None:
        return _assigned_string_of(code_call.first_argument_name, parsed_code)
    return None


def _assigned_string_of(name: str, parsed_code: ParsedCode) -> str | None:
    """Find the string of the one assignment of a string to a name, None when the code gives the name no string or more than one."""
    assigned_strings = [
        assignment.value
        for assignment in parsed_code.string_assignments
        if assignment.name == name
    ]
    return assigned_strings[0] if len(assigned_strings) == 1 else None


def _target_text_of_host_and_port_tuple(code_call: CodeCall) -> str | None:
    """Find the host that the first argument of a call writes as the first element of a host and port tuple, or None when the code builds it.

    The host is the first string when the tuple opens with that string alone, e.g. `api` of `socket.create_connection(("api", 8000))`.
    A string that more code extends names no host, e.g. `172.18.0.` of `socket.create_connection(("172.18.0." + str(i), 80))`.
    A first argument that is a string or a name is no tuple, e.g. `socket.create_connection(SOCK)` after `SOCK = "/tmp/x.sock"`, and a string after the tuple is another argument, e.g. `tmo` of `socket.create_connection((HOST, 80), "tmo")`.
    """
    if isinstance(
        code_call.argument_text, str
    ) and _TUPLE_OPENING_WITH_WHOLE_STRING.match(code_call.argument_text):
        return code_call.string_literals[0]
    return None


def _add_program_run_by_code_network_requests(
    code_call: CodeCall,
    call_name: str,
    code_text_requests: _CodeTextRequests,
    *,
    knowledge: NetworkRequestKnowledge,
    judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
) -> None:
    """Add the request of a call that runs a program, by whether any row of the program fetches.

    The program is the first word of the first string of the call without its folder, e.g. `pip` of `subprocess.run(["/usr/bin/pip", "install", "x"])` or of `os.system("pip install x")`, and its other words are not read.
    A program that may fetch gives one uncertain request of unknown target, a program known not to fetch none, and a program without a row one uncertain request per URL in the call that may be public.
    """
    program_name = _program_name_of(code_call)
    may_program_fetch = (
        UnknownProgramNetworkRequestLabel()
        if program_name is None
        else knowledge.may_program_fetch(program_name)
    )
    if isinstance(may_program_fetch, UnknownProgramNetworkRequestLabel):
        _add_requests_of_urls_in_strings(
            code_call,
            call_name,
            NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM,
            code_text_requests,
            judgment_rule_use_counts=judgment_rule_use_counts,
            no_network_request_counts=no_network_request_counts,
        )
    elif may_program_fetch:
        code_text_requests.add(
            call_name,
            UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.BUILT_IN_CODE
            ),
            UnknownNetworkRequestTargetKind(),
            _host_names_of_urls(_urls_in_strings(code_call)),
            NetworkRequestUncertaintyReason.PROGRAM_RUN_BY_CODE,
        )
    else:
        no_network_request_counts[
            NoNetworkRequestReason.NON_FETCHING_PROGRAM_RUN_BY_CODE
        ] += 1


def _program_name_of(code_call: CodeCall) -> str | None:
    """Find the program that a call runs, the first word of its first string without its folder, or None when the call has no string, e.g. `subprocess.run(cmd)`."""
    if not code_call.string_literals:
        return None
    words = code_call.string_literals[0].split()
    if not words:
        return None
    return words[0].rsplit("/", 1)[-1]


def _add_requests_of_urls_in_strings(
    code_call: CodeCall,
    call_name: str | UnknownCodeCall,
    uncertainty_reason: NetworkRequestUncertaintyReason,
    code_text_requests: _CodeTextRequests,
    *,
    judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
) -> None:
    """Add one uncertain request per distinct URL in the strings of a call that may be public or whose host cannot be read, counting the call when it has none, e.g. one for `mylib.fetch("https://a.org/x")` in Python.

    A URL whose host cannot be read gives a request without hosts, e.g. `mylib.fetch("http:///x")`, as it does for a program without a row in a command, since what such a call does with it is not known.
    """
    urls_in_strings = _urls_in_strings(code_call)
    urls_that_may_be_requested = _select_urls_that_may_be_requested(
        tuple(url for url in urls_in_strings if parse_url(url) is not None),
        judgment_rule_use_counts=judgment_rule_use_counts,
        no_network_request_counts=no_network_request_counts,
    )
    urls = tuple(
        url
        for url in urls_in_strings
        if url in urls_that_may_be_requested or parse_url(url) is None
    )
    if not urls:
        no_network_request_counts[NoNetworkRequestReason.NO_URL_THAT_MAY_BE_PUBLIC] += 1
    for url in urls:
        code_text_requests.add(
            call_name,
            url,
            NetworkRequestTargetKind.URL,
            _host_names_of_urls((url,)),
            uncertainty_reason,
        )


def _urls_in_strings(code_call: CodeCall) -> tuple[str, ...]:
    """List the distinct URLs of the strings of a call in order, without those of the calls nested in it."""
    return tuple(
        dict.fromkeys(
            url
            for string_literal in code_call.string_literals
            for url in parse_urls_in_text(string_literal)
        )
    )


def _urls_outside_call_arguments(
    code: str, parsed_code: ParsedCode, target_assignment_values: set[str]
) -> tuple[str, ...]:
    """List the distinct URLs of the code that are in no argument text of a call and in no assignment that gave a call its target, e.g. the URL of `BASE = "https://a.org"` or of a comment."""
    urls_in_call_arguments = {
        url
        for code_call in parsed_code.code_calls
        if isinstance(code_call.argument_text, str)
        for url in parse_urls_in_text(code_call.argument_text)
    }
    urls_of_target_assignments = {
        url
        for assignment in parsed_code.string_assignments
        if assignment.value in target_assignment_values
        for url in parse_urls_in_text(assignment.value)
    }
    return tuple(
        url
        for url in parse_urls_in_text(code)
        if url not in urls_in_call_arguments and url not in urls_of_target_assignments
    )


def _select_urls_that_may_be_requested(
    urls: Iterable[str],
    *,
    judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
) -> tuple[str, ...]:
    """Keep the URLs that are no namespace name and whose host may be public, counting each URL dropped under its reason.

    A URL whose host cannot be read is dropped as local or reserved, e.g. `X = "http:///x"`, since a string outside every call gives a request only for a URL that may be public.
    """
    target_urls: list[str] = []
    for url in urls:
        if treat_url_of_namespace_host_as_no_target(
            url, use_counts=judgment_rule_use_counts
        ):
            no_network_request_counts[NoNetworkRequestReason.NAMESPACE_URL] += 1
        else:
            target_urls.append(url)
    public_urls = urls_that_may_be_public(target_urls, judgment_rule_use_counts)
    if len(public_urls) < len(target_urls):
        no_network_request_counts[
            NoNetworkRequestReason.LOCAL_OR_RESERVED_URL_IN_CODE
        ] += len(target_urls) - len(public_urls)
    return public_urls


def _host_names_of_urls(urls: Iterable[str]) -> tuple[str, ...]:
    """List the distinct hosts that the URLs name, in order, e.g. `("a.org",)` for `https://a.org/x`."""
    return tuple(
        dict.fromkeys(host_name for url in urls if (host_name := parse_url(url)))
    )
