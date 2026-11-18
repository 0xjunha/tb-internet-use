"""Extract the network requests of one Python or JavaScript code text from its calls and from the URLs it writes outside them, asking the code call catalog which calls fetch.

Code is not split into commands, so a request is found by the call that sends it, e.g. `requests.get("https://a.org/x")`.
A public URL that no known call holds gives an uncertain request of its own, e.g. `BASE = "https://a.org"`, since whether the code fetches it depends on the flow of the code.
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
    treat_call_name_that_ends_with_catalog_name_as_that_call,
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
from tb_internet_use.network_request.parse_code import parse_code
from tb_internet_use.network_request.parse_target import parse_target
from tb_internet_use.network_request.parse_url import SCHEME_AND_SLASHES, parse_url
from tb_internet_use.network_request.parse_urls_in_text import parse_urls_in_text
from tb_internet_use.tool_call.model import ToolCallKey

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that this module never loads `knowledge/` itself.
    from tb_internet_use.knowledge.network_request_knowledge import (
        NetworkRequestKnowledge,
    )

# The start of an argument text whose first argument is a tuple that opens with a string, e.g. `("api", 8000)`.
_TUPLE_OPENING_WITH_STRING = re.compile(r"""\s*\(\s*["']""")
# A port that closes the authority of a URL, e.g. `:8069` of `name:8069`.
_PORT_AT_END = re.compile(r":[0-9]+$")


def extract_code_network_requests(
    ran_code_text: RanCodeText,
    tool_call_key: ToolCallKey,
    first_index_in_tool_call: int,
    *,
    knowledge: NetworkRequestKnowledge,
    judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
) -> tuple[NetworkRequest, ...]:
    """Extract the requests of one code text in the order of its calls, then those of the public URLs outside every call.

    A call that sends a request gives one confirmed request per call when its target is in the text, and one per call name when it is not, e.g. `requests.get(base + path)`.
    A call without a row gives one uncertain request per URL that may be public or whose host cannot be read, and the text outside every call one per URL that may be public.
    Text that `parse_code` could not read to its end holds no call that it read, so its URLs give requests as URLs outside every call, e.g. the URL after an unclosed backtick in ``x = `; fetch("https://a.org/x")``.
    Every request gets `UnknownReceivedContentDestination`, since what code does with the content is not read.
    """
    code_language = ran_code_text.code_language
    parsed_code = parse_code(ran_code_text.code, code_language)
    code_text_requests = _CodeTextRequests(
        tool_call_key, ran_code_text, first_index_in_tool_call
    )
    for code_call in parsed_code.code_calls:
        call_name = _code_call_name_with_row(
            code_call, code_language, knowledge, judgment_rule_use_counts
        )
        match knowledge.code_call_label(code_language, call_name):
            case UnknownCodeCallLabel():
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
                    call_name,
                    code_text_requests,
                    knowledge=knowledge,
                    judgment_rule_use_counts=judgment_rule_use_counts,
                    no_network_request_counts=no_network_request_counts,
                )
            case CodeCallLabel() as code_call_label:
                _add_sending_code_call_network_request(
                    code_call, code_call_label, parsed_code, code_text_requests
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
    # The call names that already gave a request whose target the text does not show, so that a second such call of the name gives none.
    names_of_calls_without_visible_target: set[str] = field(default_factory=set)
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


def _code_call_name_with_row(
    code_call: CodeCall,
    code_language: CodeLanguage,
    knowledge: NetworkRequestKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> str:
    """Give the name to ask the door about, the name as written when it has a row, else the shorter name that the judgment rule picks, else the name as written, e.g. `urlopen` for `urllib.request.urlopen`."""
    if knowledge.has_code_call_row(code_language, code_call.name):
        return code_call.name
    shorter_call_name = treat_call_name_that_ends_with_catalog_name_as_that_call(
        code_call.name,
        lambda call_name: knowledge.has_code_call_row(code_language, call_name),
        use_counts=judgment_rule_use_counts,
    )
    return code_call.name if shorter_call_name is None else shorter_call_name


def _add_sending_code_call_network_request(
    code_call: CodeCall,
    code_call_label: CodeCallLabel,
    parsed_code: ParsedCode,
    code_text_requests: _CodeTextRequests,
) -> None:
    """Add the confirmed request of a call that sends one, with the target its text shows, or one request of unknown target per call name when the text shows none.

    The URLs in its other strings are no requests, e.g. the referer in `requests.get(u, headers={"Referer": "https://b.org"})`, and neither is the call that holds it.
    A request of unknown target still names the hosts that its URL strings write whole, e.g. `name` for `requests.get('http://name:8069' + path)`.
    """
    target_notation = code_call_label.target_notation
    target_kind = code_call_label.target_kind
    assert target_notation is not None and target_kind is not None
    target_text = _target_text_of(code_call, target_notation, parsed_code)
    if target_text is None:
        if (
            code_call_label.call_name
            in code_text_requests.names_of_calls_without_visible_target
        ):
            return
        code_text_requests.names_of_calls_without_visible_target.add(
            code_call_label.call_name
        )
        code_text_requests.add(
            code_call_label.call_name,
            UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.BUILT_IN_CODE
            ),
            target_kind,
            _host_names_closed_in_url_strings(code_call),
            None,
        )
        return
    if (
        code_call.first_argument_string is None
        and code_call.first_argument_name is not None
    ):
        code_text_requests.target_assignment_values.add(target_text)
    parsed_target = parse_target(target_text, target_notation)
    code_text_requests.add(
        code_call_label.call_name,
        target_text,
        target_kind if parsed_target.target_kind is None else parsed_target.target_kind,
        () if parsed_target.host_name is None else (parsed_target.host_name,),
        None,
    )


def _host_names_closed_in_url_strings(code_call: CodeCall) -> tuple[str, ...]:
    """List the distinct hosts of the strings of a call that start with a URL whose host ends inside the string, e.g. `name` for `'http://name:8069'` in `'http://name:8069' + path`.

    A host ends inside the string when `/`, `?` or `#` follows it there or a port closes it, e.g. `'http://a.org/'` or `'http://name:8069'`.
    A host that runs to the end of the string may go on outside it, so `'http://' + h` and `'http://api.' + domain` name no host.
    """
    host_names: list[str] = []
    for string_literal in code_call.string_literals:
        scheme_match = SCHEME_AND_SLASHES.match(string_literal)
        if scheme_match is None:
            continue
        rest = string_literal[scheme_match.end() :]
        authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
        if len(authority) == len(rest) and not _PORT_AT_END.search(authority):
            continue
        host_name = parse_url(string_literal)
        if host_name is not None:
            host_names.append(host_name)
    return tuple(dict.fromkeys(host_names))


def _target_text_of(
    code_call: CodeCall, target_notation: TargetNotation, parsed_code: ParsedCode
) -> str | None:
    """Find the target that the text of a sending call shows, or None when the code builds it.

    It is the first argument when that is one string, else the value of the one assignment of the name that the first argument is, e.g. the URL of `URL = "https://a.org/x"` for `requests.get(URL)`.
    A host and port tuple whose argument text opens with a tuple that opens with a string takes that string, e.g. `api` of `socket.create_connection(("api", 8000))`.
    Any other string of the call may be some other argument, e.g. `config.json` of `hf_hub_download(repo_id=REPO, filename="config.json")` or `tmo` of `socket.create_connection((HOST, 80), "tmo")`, so the target is built in code.
    """
    if code_call.first_argument_string is not None:
        return code_call.first_argument_string
    if code_call.first_argument_name is not None:
        assigned_values = [
            assignment.value
            for assignment in parsed_code.string_assignments
            if assignment.name == code_call.first_argument_name
        ]
        return assigned_values[0] if len(assigned_values) == 1 else None
    if (
        target_notation == TargetNotation.HOST_AND_PORT_TUPLE
        and isinstance(code_call.argument_text, str)
        and _TUPLE_OPENING_WITH_STRING.match(code_call.argument_text)
    ):
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
