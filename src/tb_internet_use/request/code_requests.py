"""Find the candidate request of Python or JavaScript code that calls a network library or runs a program that makes requests.

Code a command runs can fetch a URL without any request word in the shell text, e.g. `requests.get(u)` in get.py run by `python get.py`.
"""

import re

from tb_internet_use.callrun.model import RanCodeText
from tb_internet_use.network.hosts import host_from_name, host_name_in_url
from tb_internet_use.network.model import PrintingProgram
from tb_internet_use.program import program_catalog
from tb_internet_use.program.model import RequestKind
from tb_internet_use.request.code_request_tables import (
    HOST_NAMED_BY_CODE,
    NETWORK_CALL_OF_LANGUAGE,
    PROGRAM_RUN_BY_CODE,
    SCHEMA_HOST_NAMES,
)
from tb_internet_use.request.model import CandidateRequest, FromCode, RequestTarget
from tb_internet_use.toolcall.model import ToolCallKey

# A URL with an http or https scheme, ending before a space, a quote, a backtick, an angle bracket or a closing bracket.
_URL = re.compile(r"""https?://[^\s'"<>`)\]}]+""")
_PACKAGE_REQUEST_KINDS = frozenset({RequestKind.PACKAGE, RequestKind.SYSTEM_PACKAGE})


def code_request(
    call_key: ToolCallKey, code_text: RanCodeText, program_name: str | None
) -> CandidateRequest | None:
    """Make the candidate request of a code text that calls a network library or runs a program with a request rule.

    Code the trial does not show gives no request.
    """
    code = code_text.code
    if code is None:
        return None
    programs_run = frozenset(m.group(1) for m in PROGRAM_RUN_BY_CODE.finditer(code))
    if not programs_run and not NETWORK_CALL_OF_LANGUAGE[code_text.language].search(
        code
    ):
        return None
    urls = tuple(
        dict.fromkeys(url for url in _URL.findall(code) if not _is_schema_name(url))
    )
    host_names = [*(host_name_in_url(url) for url in urls), *_host_literals(code)]
    rules = [
        row.request_rule
        for program in programs_run
        for row in program_catalog().get(program, ())
        if row.request_rule is not None
    ]
    runs_package_manager = any(rule.kind in _PACKAGE_REQUEST_KINDS for rule in rules)
    return CandidateRequest(
        call=call_key,
        source=FromCode(code_text.source.runner_command_id),
        kind=RequestKind.CODE,
        program_name=program_name,
        targets=tuple(RequestTarget(url, url, None) for url in urls),
        hosts=tuple(dict.fromkeys(host_from_name(name) for name in host_names if name)),
        asked_package_names=None if runs_package_manager else frozenset(),
        printing_programs=frozenset(
            {
                PrintingProgram.CODE,
                *(p for rule in rules for p in rule.printing_programs),
            }
        ),
        fetches_only_to_run_or_build=False,
        has_offline_option=False,
        exit_zero_means=None,
        asks_for_no_content=False,
        prints_response_body=None,
        prints_status_code=False,
        quiet_progress_lines=False,
        quiet_error_lines=False,
    )


def _host_literals(code: str) -> list[str]:
    """Find the host names that code gives as an address tuple or to a name lookup, e.g. api in `("api", 8000)`."""
    return [m.group(1) or m.group(2) for m in HOST_NAMED_BY_CODE.finditer(code)]


def _is_schema_name(url: str) -> bool:
    """Check whether a URL is an XML namespace or schema name rather than a file, e.g. `http://www.w3.org/2000/svg`."""
    host_name = host_name_in_url(url)
    last_component = url.rstrip("/").rsplit("/", 1)[-1]
    return host_name in SCHEMA_HOST_NAMES and "." not in last_component
