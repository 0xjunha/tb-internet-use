"""Tests for network_request/_extract_code_network_requests.py, with made-up code texts and the real catalogs unless a case needs a row they lack."""

import csv
from collections import Counter
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CodeLanguage,
    PollInputText,
    RanCodeText,
)
from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.network_request_knowledge import (
    ANY_SUBCOMMAND,
    CODE_CALLS_CSV,
    NETWORK_REQUEST_CATALOGS_DIR,
    PROGRAM_NETWORK_REQUESTS_CSV,
    NetworkRequestKnowledge,
)
from tb_internet_use.network_request import _extract_code_network_requests
from tb_internet_use.network_request._extract_code_network_requests import (
    extract_code_network_requests,
)
from tb_internet_use.network_request.model import (
    FromCode,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoNetworkRequestReason,
    UnknownCodeCall,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetKind,
    UnknownNetworkRequestTargetReason,
    UnknownReceivedContentDestination,
)
from tb_internet_use.network_request.parse_code import parse_code
from tb_internet_use.tool_call.model import ToolCallKey

KEY = ToolCallKey("trial", "main", 1, 0)
PYTHON = CodeLanguage.PYTHON
JAVASCRIPT = CodeLanguage.JAVASCRIPT
URL = NetworkRequestTargetKind.URL
HOST = NetworkRequestTargetKind.HOST
UNKNOWN_KIND = UnknownNetworkRequestTargetKind()
BUILT_IN_CODE = UnknownNetworkRequestTarget(
    UnknownNetworkRequestTargetReason.BUILT_IN_CODE
)
UNKNOWN_CALL = UnknownCodeCall()
UNKNOWN_CODE_CALL = NetworkRequestUncertaintyReason.UNKNOWN_CODE_CALL
URL_OUTSIDE_CODE_CALL = NetworkRequestUncertaintyReason.URL_OUTSIDE_CODE_CALL
PROGRAM_RUN_BY_CODE = NetworkRequestUncertaintyReason.PROGRAM_RUN_BY_CODE
UNKNOWN_PROGRAM = NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM
U = "https://a.org/x"
# The confirmed request of `requests.get(U)`, as (call name, target, target kind, hosts, uncertainty reason).
REQUESTS_GET_U = ("requests.get", U, URL, ("a.org",), None)
# The confirmed request of `urlopen` whose argument is no literal, e.g. a request object.
URLOPEN_OF_OBJECT = ("urlopen", BUILT_IN_CODE, URL, (), None)
# The request of a URL in code outside every call.
OUTSIDE_U = (UNKNOWN_CALL, U, URL, ("a.org",), URL_OUTSIDE_CODE_CALL)
NAMESPACE_RULE = "treat_url_of_namespace_host_as_no_target"
CALL_NAME_RULE = "treat_call_name_that_ends_with_catalog_name_as_that_call"
POSSIBLY_PUBLIC_RULE = "treat_single_label_or_templated_host_name_as_possibly_public"

# (case, code, language, requests as (call name, target, target kind, hosts, uncertainty reason))
_CASES = [
    # A known call with a literal URL.
    ("literal url", f'requests.get("{U}")', PYTHON, [REQUESTS_GET_U]),
    (
        "internal host",
        'requests.get("http://localhost:8000/health")',
        PYTHON,
        [("requests.get", "http://localhost:8000/health", URL, ("localhost",), None)],
    ),
    # A URL in a name assigned once above.
    ("url assigned once", f'URL = "{U}"\nrequests.get(URL)', PYTHON, [REQUESTS_GET_U]),
    (
        "url assigned twice",
        f'URL = "{U}"\nURL = "{U}"\nrequests.get(URL)',
        PYTHON,
        [("requests.get", BUILT_IN_CODE, URL, (), None), OUTSIDE_U],
    ),
    (
        "url built from a name",
        'base = "https://a.org"\nrequests.get(base + path)',
        PYTHON,
        [
            ("requests.get", BUILT_IN_CODE, URL, (), None),
            (UNKNOWN_CALL, "https://a.org", URL, ("a.org",), URL_OUTSIDE_CODE_CALL),
        ],
    ),
    # No visible URL gives one request per call name and hosts.
    (
        "no visible url",
        "requests.get(base + path)",
        PYTHON,
        [("requests.get", BUILT_IN_CODE, URL, (), None)],
    ),
    (
        "two calls without visible url",
        "requests.get(a)\nrequests.get(a)\nrequests.post(b)",
        PYTHON,
        [
            ("requests.get", BUILT_IN_CODE, URL, (), None),
            ("requests.post", BUILT_IN_CODE, URL, (), None),
        ],
    ),
    (
        "calls without visible url with and without a host",
        "requests.get('http://name:8069' + p)\nrequests.get(u)\nrequests.get('http://name:8069/' + q)",
        PYTHON,
        [
            ("requests.get", BUILT_IN_CODE, URL, ("name",), None),
            ("requests.get", BUILT_IN_CODE, URL, (), None),
        ],
    ),
    (
        "calls without visible url with two hosts",
        "requests.get('http://a:1' + p)\nrequests.get('http://b:1' + p)",
        PYTHON,
        [
            ("requests.get", BUILT_IN_CODE, URL, ("a",), None),
            ("requests.get", BUILT_IN_CODE, URL, ("b",), None),
        ],
    ),
    (
        "parentheses that do not close",
        f'requests.get("{U}"',
        PYTHON,
        [("requests.get", BUILT_IN_CODE, URL, (), None), OUTSIDE_U],
    ),
    # The innermost call owns a string, and only the first argument is the target.
    ("nested call", f'print(requests.get("{U}").text)', PYTHON, [REQUESTS_GET_U]),
    (
        "other url of a known call",
        f'requests.get("{U}", headers={{"Referer": "https://b.org"}})',
        PYTHON,
        [REQUESTS_GET_U],
    ),
    (
        "host and port tuple",
        'socket.create_connection(("api", 8000))',
        PYTHON,
        [("socket.create_connection", "api", HOST, ("api",), None)],
    ),
    (
        "host name",
        'socket.gethostbyname("a.org")',
        PYTHON,
        [("socket.gethostbyname", "a.org", HOST, ("a.org",), None)],
    ),
    (
        "model name",
        'AutoModel.from_pretrained("bert-base")',
        PYTHON,
        [("from_pretrained", "bert-base", UNKNOWN_KIND, (), None)],
    ),
    (
        "javascript fetch",
        f'await fetch("{U}")',
        JAVASCRIPT,
        [("fetch", U, URL, ("a.org",), None)],
    ),
    (
        "javascript dotted fetch",
        f'mylib.fetch("{U}")',
        JAVASCRIPT,
        [("fetch", U, URL, ("a.org",), None)],
    ),
    # An unknown call with a public URL in its strings.
    (
        "unknown call",
        f'mylib.fetch("{U}")',
        PYTHON,
        [(UNKNOWN_CALL, U, URL, ("a.org",), UNKNOWN_CODE_CALL)],
    ),
    (
        "unknown call written like a known module",
        f'urllib.request.build_opener("{U}")',
        PYTHON,
        [(UNKNOWN_CALL, U, URL, ("a.org",), UNKNOWN_CODE_CALL)],
    ),
    # A request object is no call with a row, so both spellings give the request of urlopen, whose target is the object, and an uncertain request for the URL in it that names its host.
    (
        "request object built with a dotted name",
        f'urllib.request.urlopen(urllib.request.Request("{U}"))',
        PYTHON,
        [URLOPEN_OF_OBJECT, (UNKNOWN_CALL, U, URL, ("a.org",), UNKNOWN_CODE_CALL)],
    ),
    (
        "request object built with an imported name",
        f'from urllib.request import Request, urlopen\nurlopen(Request("{U}"))',
        PYTHON,
        [URLOPEN_OF_OBJECT, (UNKNOWN_CALL, U, URL, ("a.org",), UNKNOWN_CODE_CALL)],
    ),
    (
        "client that sends nothing",
        f's = requests.Session()\ns.get("{U}")',
        PYTHON,
        [(UNKNOWN_CALL, U, URL, ("a.org",), UNKNOWN_CODE_CALL)],
    ),
    (
        "unknown call twice",
        f'mylib.fetch("{U}")\nmylib.fetch("{U}")',
        PYTHON,
        [(UNKNOWN_CALL, U, URL, ("a.org",), UNKNOWN_CODE_CALL)] * 2,
    ),
    (
        "url repeated in one unknown call",
        f'mylib.fetch("{U}", "{U}")',
        PYTHON,
        [(UNKNOWN_CALL, U, URL, ("a.org",), UNKNOWN_CODE_CALL)],
    ),
    (
        "single label host",
        'fetch("http://db:5432")',
        PYTHON,
        [(UNKNOWN_CALL, "http://db:5432", URL, ("db",), UNKNOWN_CODE_CALL)],
    ),
    ("local url in an unknown call", 'print("http://localhost:8000")', PYTHON, []),
    ("no url", "x = compute()", PYTHON, []),
    # A public URL only in a plain string or a comment.
    (
        "url in a plain string",
        'BASE = "https://a.org"',
        PYTHON,
        [(UNKNOWN_CALL, "https://a.org", URL, ("a.org",), URL_OUTSIDE_CODE_CALL)],
    ),
    (
        "url in a comment",
        "# see https://a.org/doc",
        PYTHON,
        [(UNKNOWN_CALL, "https://a.org/doc", URL, ("a.org",), URL_OUTSIDE_CODE_CALL)],
    ),
    (
        "namespace url",
        f'NS = "http://www.w3.org/2000/svg"\nrequests.get("{U}")',
        PYTHON,
        [REQUESTS_GET_U],
    ),
    # Text after a backtick that never closes is read for URLs only.
    (
        "text not read to its end",
        f'const re = /`/; fetch("{U}")',
        JAVASCRIPT,
        [OUTSIDE_U],
    ),
    # A call that runs a program.
    (
        "program that fetches",
        'subprocess.run(["pip", "install", "x"])',
        PYTHON,
        [("subprocess.run", BUILT_IN_CODE, UNKNOWN_KIND, (), PROGRAM_RUN_BY_CODE)],
    ),
    (
        "program that fetches with a url",
        f'subprocess.run(["curl", "{U}"])',
        PYTHON,
        [
            (
                "subprocess.run",
                BUILT_IN_CODE,
                UNKNOWN_KIND,
                ("a.org",),
                PROGRAM_RUN_BY_CODE,
            )
        ],
    ),
    (
        "program in a folder",
        'subprocess.run(["/usr/bin/git", "status"])',
        PYTHON,
        [("subprocess.run", BUILT_IN_CODE, UNKNOWN_KIND, (), PROGRAM_RUN_BY_CODE)],
    ),
    (
        "shell text that fetches",
        f'os.system("curl -sO {U}")',
        PYTHON,
        [("os.system", BUILT_IN_CODE, UNKNOWN_KIND, ("a.org",), PROGRAM_RUN_BY_CODE)],
    ),
    (
        "program known not to fetch",
        'subprocess.run(["echo", "https://a.org"])',
        PYTHON,
        [],
    ),
    ("program without a row", 'subprocess.run(["rm", "-rf", ".git"])', PYTHON, []),
    (
        "program without a row and a url",
        f'subprocess.run(["mytool", "{U}"])',
        PYTHON,
        [("subprocess.run", U, URL, ("a.org",), UNKNOWN_PROGRAM)],
    ),
    (
        "program named by the python of the code",
        'subprocess.check_call([sys.executable, "-m", "pip", "install", "x"])',
        PYTHON,
        [],
    ),
    ("program not named", "subprocess.run(cmd)", PYTHON, []),
    # A built target names the host that a URL string writes whole.
    (
        "built url whose string closes the host with a port",
        "requests.get('http://name:8069' + params['url'])",
        PYTHON,
        [("requests.get", BUILT_IN_CODE, URL, ("name",), None)],
    ),
    (
        "built url whose string closes the host with a slash",
        "requests.get('https://a.org/v1/' + path)",
        PYTHON,
        [("requests.get", BUILT_IN_CODE, URL, ("a.org",), None)],
    ),
    (
        "built url whose string ends after the scheme",
        "requests.get('http://' + h)",
        PYTHON,
        [("requests.get", BUILT_IN_CODE, URL, (), None)],
    ),
    (
        "built url whose string ends inside the host",
        "requests.get('http://api.' + domain + '/x')",
        PYTHON,
        [("requests.get", BUILT_IN_CODE, URL, (), None)],
    ),
    # A string that is not the first argument is no URL target.
    (
        "string of a built url",
        'requests.get(BASE + "/x")',
        PYTHON,
        [("requests.get", BUILT_IN_CODE, URL, (), None)],
    ),
    (
        "string of a keyword argument of a name",
        'hf_hub_download(repo_id=REPO, filename="config.json")',
        PYTHON,
        [("hf_hub_download", BUILT_IN_CODE, UNKNOWN_KIND, (), None)],
    ),
    (
        "string of a keyword argument of a dataset",
        'load_dataset(path=NAME, split="train")',
        PYTHON,
        [("load_dataset", BUILT_IN_CODE, UNKNOWN_KIND, (), None)],
    ),
    (
        "string of a name call whose first argument is a name",
        'from_pretrained(MODEL, cache_dir="/tmp")',
        PYTHON,
        [("from_pretrained", BUILT_IN_CODE, UNKNOWN_KIND, (), None)],
    ),
    (
        "string after a host and port tuple of a name",
        'socket.create_connection((HOST, 80), "tmo")',
        PYTHON,
        [("socket.create_connection", BUILT_IN_CODE, HOST, (), None)],
    ),
    (
        "host and port tuple with a dotted host",
        'socket.create_connection(("a.org", 80))',
        PYTHON,
        [("socket.create_connection", "a.org", HOST, ("a.org",), None)],
    ),
    # A string that the code extends is only the start of the host.
    (
        "host and port tuple whose host string is extended",
        "socket.create_connection(('10.0.0.' + str(i), 80))",
        PYTHON,
        [("socket.create_connection", BUILT_IN_CODE, HOST, (), None)],
    ),
    # A string is no host and port tuple, also when a name holds it.
    (
        "host and port call with a string",
        'socket.create_connection("/tmp/x.sock")',
        PYTHON,
        [("socket.create_connection", BUILT_IN_CODE, HOST, (), None)],
    ),
    (
        "host and port call with a name of a string",
        'SOCK = "/tmp/x.sock"\nsocket.create_connection(SOCK)',
        PYTHON,
        [("socket.create_connection", BUILT_IN_CODE, HOST, (), None)],
    ),
    # A dotted call takes the name of its row also when the code builds its target.
    (
        "dotted call without visible url",
        "urllib.request.urlopen(req)",
        PYTHON,
        [("urlopen", BUILT_IN_CODE, URL, (), None)],
    ),
    (
        "two dotted calls of one row without visible url",
        "a.urlopen(x)\nb.urlopen(y)",
        PYTHON,
        [("urlopen", BUILT_IN_CODE, URL, (), None)],
    ),
    # A URL whose host cannot be read.
    (
        "unreadable host in an unknown call",
        'mylib.fetch("http:///x")',
        PYTHON,
        [(UNKNOWN_CALL, "http:///x", URL, (), UNKNOWN_CODE_CALL)],
    ),
    ("unreadable host in a plain string", 'X = "http:///x"', PYTHON, []),
]


def _knowledge_with_code_call_rows(
    tmp_path: Path, code_call_rows: list[dict[str, str]]
) -> NetworkRequestKnowledge:
    (tmp_path / PROGRAM_NETWORK_REQUESTS_CSV).write_text(
        (NETWORK_REQUEST_CATALOGS_DIR / PROGRAM_NETWORK_REQUESTS_CSV).read_text()
    )
    columns = [
        "code_language",
        "call_name",
        "effect",
        "target_notation",
        "target_kind",
        "checked_against",
        "reviewed",
        "note",
    ]
    with (tmp_path / CODE_CALLS_CSV).open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, columns, restval="")
        writer.writeheader()
        writer.writerows(code_call_rows)
    return NetworkRequestKnowledge(catalogs_dir=tmp_path)


def _extract(
    code: str,
    code_language: CodeLanguage = PYTHON,
    *,
    knowledge: NetworkRequestKnowledge | None = None,
    judgment_rule_use_counts: Counter[str] | None = None,
    no_network_request_counts: Counter[NoNetworkRequestReason] | None = None,
    first_index_in_tool_call: int = 0,
) -> tuple[NetworkRequest, ...]:
    return extract_code_network_requests(
        RanCodeText(ArgumentText(3), code_language, code),
        KEY,
        first_index_in_tool_call,
        knowledge=NetworkRequestKnowledge() if knowledge is None else knowledge,
        judgment_rule_use_counts=Counter()
        if judgment_rule_use_counts is None
        else judgment_rule_use_counts,
        no_network_request_counts=Counter()
        if no_network_request_counts is None
        else no_network_request_counts,
    )


def _summary(network_requests: tuple[NetworkRequest, ...]) -> list[tuple]:
    summary: list[tuple] = []
    for network_request in network_requests:
        assert isinstance(network_request.source, FromCode)
        summary.append(
            (
                network_request.source.call_name,
                network_request.target,
                network_request.target_kind,
                network_request.host_names,
                network_request.uncertainty_reason,
            )
        )
    return summary


@pytest.mark.parametrize(
    ("code", "code_language", "expected"),
    [case[1:] for case in _CASES],
    ids=[case[0] for case in _CASES],
)
def test_requests_of_code_follow_what_is_known_about_each_call(
    code, code_language, expected
):
    assert _summary(_extract(code, code_language)) == expected


def test_request_of_a_known_call_is_confirmed_numbered_and_names_the_runner_and_the_code():
    network_requests = _extract(
        f'requests.get("{U}")\nmylib.fetch("https://b.org")',
        first_index_in_tool_call=5,
    )

    assert network_requests[0] == NetworkRequest(
        tool_call_key=KEY,
        index_in_tool_call=5,
        source=FromCode(3, ArgumentText(3), PYTHON, "requests.get"),
        target=U,
        target_kind=URL,
        host_names=("a.org",),
        received_content_destination=UnknownReceivedContentDestination(),
        certainty=NetworkRequestCertainty.CONFIRMED,
        uncertainty_reason=None,
    )
    assert (
        network_requests[1].index_in_tool_call,
        network_requests[1].certainty,
        network_requests[1].received_content_destination,
    ) == (6, NetworkRequestCertainty.UNCERTAIN, UnknownReceivedContentDestination())


def test_code_typed_through_a_poll_has_no_runner_command():
    poll_input_text = PollInputText(None, ToolCallKey("trial", "main", 1, 0))

    (network_request,) = extract_code_network_requests(
        RanCodeText(poll_input_text, PYTHON, f'requests.get("{U}")'),
        KEY,
        0,
        knowledge=NetworkRequestKnowledge(),
        judgment_rule_use_counts=Counter(),
        no_network_request_counts=Counter(),
    )

    assert network_request.source == FromCode(
        None, poll_input_text, PYTHON, "requests.get"
    )


def test_text_not_read_to_its_end_is_one_that_parse_code_marks():
    assert (
        parse_code(f'const re = /`/; fetch("{U}")', JAVASCRIPT).unreadable_text_start
        == 12
    )


def test_judgment_rules_are_counted_once_per_use():
    judgment_rule_use_counts: Counter[str] = Counter()

    _extract(
        'NS = "http://www.w3.org/2000/svg"\n'
        'AutoModel.from_pretrained("bert-base")\n'
        'fetch("http://db:5432")\n'
        'X = "https://files.acme.org/x"',
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    assert judgment_rule_use_counts == Counter(
        {
            NAMESPACE_RULE: 1,
            CALL_NAME_RULE: 1,
            POSSIBLY_PUBLIC_RULE: 1,
            "treat_dotted_host_name_as_public": 1,
        }
    )


def test_calls_and_urls_that_give_no_request_are_counted_by_reason(tmp_path):
    knowledge = _knowledge_with_code_call_rows(
        tmp_path,
        [
            {
                "code_language": "python",
                "call_name": "print",
                "effect": "sends_no_network_request",
                "checked_against": "a page",
            },
            {
                "code_language": "python",
                "call_name": "subprocess.run",
                "effect": "runs_program",
                "checked_against": "a page",
            },
        ],
    )
    no_network_request_counts: Counter[NoNetworkRequestReason] = Counter()

    network_requests = _extract(
        f'print("{U}")\n'
        'len("http://localhost:8000")\n'
        'NS = "http://www.w3.org/2000/svg"\n'
        'subprocess.run(["echo", "hi"])\n'
        'X = "http://example.com/x"',
        knowledge=knowledge,
        no_network_request_counts=no_network_request_counts,
    )

    assert network_requests == ()
    assert no_network_request_counts == Counter(
        {
            NoNetworkRequestReason.NON_FETCHING_CODE_CALL: 1,
            NoNetworkRequestReason.NO_URL_THAT_MAY_BE_PUBLIC: 1,
            NoNetworkRequestReason.LOCAL_OR_RESERVED_URL_IN_CODE: 2,
            NoNetworkRequestReason.NAMESPACE_URL: 1,
            NoNetworkRequestReason.NON_FETCHING_PROGRAM_RUN_BY_CODE: 1,
        }
    )


def test_knowledge_class_is_asked_once_per_call_under_the_name_with_a_row_and_programs_by_name():
    knowledge = NetworkRequestKnowledge()

    _extract(
        f'urllib.request.urlopen("{U}")\nmylib.fetch(u)\n'
        'subprocess.run(["pip3", "install", "x"])\n'
        'subprocess.check_call([sys.executable, "-m", "pip", "install", "x"])',
        knowledge=knowledge,
    )

    assert knowledge.uses == KnowledgeUses(
        row_use_counts=Counter(
            {
                (CODE_CALLS_CSV, ("python", "urlopen")): 1,
                (CODE_CALLS_CSV, ("python", "subprocess.run")): 1,
                (CODE_CALLS_CSV, ("python", "subprocess.check_call")): 1,
            }
        ),
        unknown_input_counts=Counter(
            {
                (CODE_CALLS_CSV, ("python", "mylib.fetch")): 1,
                (PROGRAM_NETWORK_REQUESTS_CSV, ("pip3", ANY_SUBCOMMAND, "", "")): 1,
                (PROGRAM_NETWORK_REQUESTS_CSV, ("-m", ANY_SUBCOMMAND, "", "")): 1,
            }
        ),
    )


def test_namespace_url_gives_an_uncertain_request_when_the_rule_answers_no(
    monkeypatch,
):
    monkeypatch.setattr(
        _extract_code_network_requests,
        NAMESPACE_RULE,
        lambda url, *, use_counts: False,
    )

    assert _summary(_extract('NS = "http://www.w3.org/2000/svg"')) == [
        (
            UNKNOWN_CALL,
            "http://www.w3.org/2000/svg",
            URL,
            ("www.w3.org",),
            URL_OUTSIDE_CODE_CALL,
        )
    ]


def test_dotted_call_is_a_call_without_a_row_when_the_rule_answers_no(monkeypatch):
    monkeypatch.setattr(
        _extract_code_network_requests,
        CALL_NAME_RULE,
        lambda call_name, has_row, *, use_counts: None,
    )

    assert _summary(_extract(f'urllib.request.urlopen("{U}")')) == [
        (UNKNOWN_CALL, U, URL, ("a.org",), UNKNOWN_CODE_CALL)
    ]


def test_reason_without_a_dropped_url_is_not_counted():
    no_network_request_counts: Counter[NoNetworkRequestReason] = Counter()

    _extract(
        f'mylib.fetch("{U}")\nX = "https://b.org"',
        no_network_request_counts=no_network_request_counts,
    )

    assert dict(no_network_request_counts) == {}
