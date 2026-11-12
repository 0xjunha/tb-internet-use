"""Find the candidate request of Python or JavaScript code that calls a network library or runs a program that makes requests.

Code a command runs can fetch a URL without any request word in the shell text, e.g. `requests.get(u)` in get.py run by `python get.py`.
"""

import re

from tb_internet_use.callrun.model import CodeLanguage, RanCodeText
from tb_internet_use.network.hosts import host_from_name, host_name_in_url
from tb_internet_use.network.model import PrintingProgram
from tb_internet_use.program.catalog_loader import program_catalog
from tb_internet_use.program.model import RequestKind
from tb_internet_use.request.model import CandidateRequest, FromCode, RequestTarget
from tb_internet_use.toolcall.model import ToolCallKey

# Network calls in code, by language. One request per code text, however many of these it holds.
_NETWORK_CALL_OF_LANGUAGE = {
    CodeLanguage.PYTHON: re.compile(
        r"\brequests\.(?:get|post|put|head|request|Session)\b|\bhttpx\.(?:get|post|stream|Client|AsyncClient)\b"
        r"|\baiohttp\.ClientSession\b|\burlopen\(|\burlretrieve\(|\burllib3\.PoolManager\b"
        r"|\b(?:snapshot_download|hf_hub_download|from_pretrained|load_dataset)\(|\bnltk\.download\("
        r"|\bsocket\.(?:create_connection|getaddrinfo|gethostbyname)\b"
    ),
    CodeLanguage.JAVASCRIPT: re.compile(r"\bfetch\(|\baxios\.|\bhttps?\.get\("),
}
# A program that the code runs, e.g. pip in `subprocess.run(["pip", "install", "x"])` or `os.system("python -m pip install x")`.
# The name is a whole word of a string, so `.git` in `["rm", "-rf", ".git"]` names no program.
_PROGRAM_RUN_BY_CODE = re.compile(
    r"""\b(?:subprocess\.\w+|os\.system|os\.popen)\([^)]*?(?<=['"\s/])(pip|curl|wget|git|npm|apt-get)(?=['"\s])"""
)
_URL = re.compile(r"""https?://[^\s'"<>`)\]}]+""")
# Hosts that code names as an address tuple, e.g. ("api", 8000), or as the argument of a name lookup.
# The tuple's parenthesis follows no name, so call arguments such as `d.get("count", 0)` are no address.
_HOST_LITERAL = re.compile(
    r"""(?<![\w.\])])\(\s*['"](\w[\w.-]*)['"]\s*,\s*\d+\s*\)|(?:gethostbyname|getaddrinfo)\(\s*['"]([\w.-]+)['"]"""
)
# Hosts of XML namespaces and schemas, whose URLs code uses as names and does not fetch unless they name a file.
_SCHEMA_HOST_NAMES = frozenset(
    {
        "schemas.openxmlformats.org",
        "schemas.microsoft.com",
        "www.w3.org",
        "w3.org",
        "purl.org",
        "schemas.xmlsoap.org",
        "xmlns.com",
        "ns.adobe.com",
        "json-schema.org",
    }
)
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
    programs_run = frozenset(m.group(1) for m in _PROGRAM_RUN_BY_CODE.finditer(code))
    if not programs_run and not _NETWORK_CALL_OF_LANGUAGE[code_text.language].search(
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
    return [m.group(1) or m.group(2) for m in _HOST_LITERAL.finditer(code)]


def _is_schema_name(url: str) -> bool:
    """Check whether a URL is an XML namespace or schema name rather than a file, e.g. `http://www.w3.org/2000/svg`."""
    host_name = host_name_in_url(url)
    last_component = url.rstrip("/").rsplit("/", 1)[-1]
    return host_name in _SCHEMA_HOST_NAMES and "." not in last_component
