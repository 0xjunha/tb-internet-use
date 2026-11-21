"""Tests for _export_network_request_category.py, one made-up request or more for each condition of its module docstring in order, then requests that two conditions fit and each judgment rule with its other answer."""

from collections import Counter

import pytest

from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    CodeLanguage,
    OutputVisibility,
    ProgramInvocation,
)
from tb_internet_use.export import _export_network_request_category
from tb_internet_use.export._export_network_request_category import (
    export_network_request_category,
)
from tb_internet_use.export.judgment_rules import (
    treat_discarded_content_as_connectivity_check,
    treat_host_target_that_may_receive_content_as_other_web,
    treat_repository_request_for_no_content_as_other_web,
    treat_saved_content_from_unrecognized_url_as_content_fetch,
    treat_url_request_to_package_registry_host_as_package,
    treat_url_request_to_search_engine_host_as_search,
    treat_url_request_without_path_or_query_to_package_registry_or_search_engine_host_as_connectivity_check,
)
from tb_internet_use.export.model import (
    HostService,
    NetworkRequestCategory,
    PublicHost,
    UnknownPublicHost,
)
from tb_internet_use.network_request.model import (
    ContentDiscarded,
    ContentPipedToCommand,
    ContentSaved,
    ContentShownInResult,
    FromCode,
    FromCommand,
    FromWebTool,
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestSource,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    NoContentRequested,
    ReceivedContentDestination,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetKind,
    UnknownNetworkRequestTargetReason,
    UnknownReceivedContentDestination,
)
from tb_internet_use.tool_call.model import HarnessTool, ToolCallKey

PACKAGE = NetworkRequestCategory.PACKAGE
CONTENT_FETCH = NetworkRequestCategory.CONTENT_FETCH
SEARCH = NetworkRequestCategory.SEARCH
REMOTE_API_CALL = NetworkRequestCategory.REMOTE_API_CALL
CONNECTIVITY_CHECK = NetworkRequestCategory.CONNECTIVITY_CHECK
OTHER_WEB = NetworkRequestCategory.OTHER_WEB
UNKNOWN = NetworkRequestCategory.UNKNOWN

PACKAGE_NAME = NetworkRequestTargetKind.PACKAGE_NAME
REPOSITORY_URL = NetworkRequestTargetKind.REPOSITORY_URL
URL = NetworkRequestTargetKind.URL
SEARCH_QUERY = NetworkRequestTargetKind.SEARCH_QUERY
HOST = NetworkRequestTargetKind.HOST

# The answers of the host catalog of the made-up cases, as `ExportKnowledge` gives them for the path of the target, e.g. `WEB_API` for `/api/models` of `huggingface.co` and `SEARCH_ENGINE` for `/search/code` of `api.github.com`. `a.org` has no row.
PYPI = PublicHost(HostService.PACKAGE_REGISTRY, "pypi")
GITHUB = PublicHost(HostService.CODE_HOSTING, None)
HUGGINGFACE = PublicHost(HostService.MODEL_HUB, None)
SEARCH_ENGINE = PublicHost(HostService.SEARCH_ENGINE, None)
WEB_API = PublicHost(HostService.WEB_API, None)
RCSB_FILES = PublicHost(HostService.FILE_HOSTING, None)
DOCUMENTATION = PublicHost(HostService.DOCUMENTATION, None)
NO_ROW = UnknownPublicHost()

CONTENT_SHOWN_IN_RESULT = ContentShownInResult()

REPOSITORY_REQUEST_FOR_NO_CONTENT_RULE = (
    treat_repository_request_for_no_content_as_other_web.__name__
)
DISCARDED_CONTENT_RULE = treat_discarded_content_as_connectivity_check.__name__
HOST_TARGET_RULE = treat_host_target_that_may_receive_content_as_other_web.__name__
PACKAGE_REGISTRY_HOST_RULE = (
    treat_url_request_to_package_registry_host_as_package.__name__
)
SEARCH_ENGINE_HOST_RULE = treat_url_request_to_search_engine_host_as_search.__name__
URL_WITHOUT_PATH_OR_QUERY_RULE = treat_url_request_without_path_or_query_to_package_registry_or_search_engine_host_as_connectivity_check.__name__
SAVED_FROM_UNRECOGNIZED_URL_RULE = (
    treat_saved_content_from_unrecognized_url_as_content_fetch.__name__
)


def _command(program_name: str, *arguments: str) -> FromCommand:
    """Make the source of a request of a program with a row that the call's command runs."""
    return FromCommand(
        0,
        CallCommandText(),
        ProgramInvocation(
            program_name=program_name,
            subcommand_words=(),
            options=(),
            arguments=arguments,
            gets_more_arguments_at_run_time=False,
            unread_words=(),
            exits_with_exit_code_of_next_program=False,
        ),
    )


def _web_tool(harness: str, tool: str) -> FromWebTool:
    return FromWebTool(None, HarnessTool(harness, tool))


def _python_code(call_name: str) -> FromCode:
    return FromCode(0, ArgumentText(0), CodeLanguage.PYTHON, call_name)


def _request(
    source: NetworkRequestSource,
    target_kind: NetworkRequestTargetKind | UnknownNetworkRequestTargetKind,
    received_content_destination: ReceivedContentDestination,
    target: str | UnknownNetworkRequestTarget | None,
    *host_names: str,
) -> NetworkRequest:
    """Make a confirmed request, or an uncertain one for a program that code runs, as `extract_network_requests` gives it."""
    is_program_run_by_code = isinstance(target_kind, UnknownNetworkRequestTargetKind)
    return NetworkRequest(
        tool_call_key=ToolCallKey("t1", "main", 1, 0),
        index_in_tool_call=0,
        source=source,
        target=target,
        target_kind=target_kind,
        host_names=host_names,
        received_content_destination=received_content_destination,
        certainty=NetworkRequestCertainty.UNCERTAIN
        if is_program_run_by_code
        else NetworkRequestCertainty.CONFIRMED,
        uncertainty_reason=NetworkRequestUncertaintyReason.PROGRAM_RUN_BY_CODE
        if is_program_run_by_code
        else None,
    )


def _curl(
    url: str,
    host_name: str,
    received_content_destination: ReceivedContentDestination = CONTENT_SHOWN_IN_RESULT,
) -> NetworkRequest:
    return _request(
        _command("curl", url), URL, received_content_destination, url, host_name
    )


def _python_request(url: str, host_name: str) -> NetworkRequest:
    """Make the request of `requests.get(url)` in Python code, whose content destination the trial does not show."""
    return _request(
        _python_code("requests.get"),
        URL,
        UnknownReceivedContentDestination(),
        url,
        host_name,
    )


def _piped(visibility_at_end: OutputVisibility) -> ContentPipedToCommand:
    return ContentPipedToCommand(1, visibility_at_end)


GIT_PUSH = _request(
    _command("git", "origin", "main"), REPOSITORY_URL, NoContentRequested(), None
)
CURL_REGISTRY_TO_DEV_NULL = _curl("https://pypi.org", "pypi.org", ContentDiscarded())
SOCKET_CONNECTION = _request(
    _python_code("socket.create_connection"),
    HOST,
    UnknownReceivedContentDestination(),
    "api",
    "api",
)
CURL_PROJECT_PAGE = _curl("https://pypi.org/project/requests/", "pypi.org")
WGET_WHEEL = _request(
    _command("wget", "https://files.pythonhosted.org/x.whl"),
    URL,
    ContentSaved("x.whl"),
    "https://files.pythonhosted.org/x.whl",
    "files.pythonhosted.org",
)
PYTHON_REGISTRY_FIRST_PAGE = _python_request("https://pypi.org", "pypi.org")
PYTHON_SEARCH_ENGINE_FIRST_PAGE = _python_request(
    "https://www.google.com/", "www.google.com"
)
CURL_SEARCH_PAGE = _curl("https://html.duckduckgo.com/html?q=x", "html.duckduckgo.com")
CURL_SAVED_FROM_HOST_WITHOUT_ROW = _curl("https://a.org/x", "a.org", ContentSaved("x"))
# One request that names a search engine and a registry, e.g. two URLs in the words of one call.
CURL_SEARCH_ENGINE_AND_REGISTRY = _request(
    _command("curl", "https://html.duckduckgo.com/html?q=x"),
    URL,
    ContentShownInResult(),
    "https://html.duckduckgo.com/html?q=x",
    "html.duckduckgo.com",
    "pypi.org",
)
CURL_SEARCH_ENGINE_AND_WEB_API = _request(
    _command("curl", "https://html.duckduckgo.com/html?q=x"),
    URL,
    ContentShownInResult(),
    "https://html.duckduckgo.com/html?q=x",
    "html.duckduckgo.com",
    "rest.uniprot.org",
)

# (case, request, answers of the host catalog for its public hosts, category, judgment rules counted once)
CASES: list[
    tuple[
        str,
        NetworkRequest,
        list[PublicHost | UnknownPublicHost],
        NetworkRequestCategory,
        list[str],
    ]
] = [
    # The target kind is not known.
    (
        'code `subprocess.run(["pip", "install", "x"])`',
        _request(
            _python_code("subprocess.run"),
            UnknownNetworkRequestTargetKind(),
            UnknownReceivedContentDestination(),
            UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.BUILT_IN_CODE
            ),
        ),
        [],
        UNKNOWN,
        [],
    ),
    # The target is a package name, which does not need to be known, also when the content is saved.
    (
        "`pip install requests`",
        _request(
            _command("pip", "requests"), PACKAGE_NAME, ContentSaved(None), "requests"
        ),
        [],
        PACKAGE,
        [],
    ),
    (
        "`pip install $PKG`",
        _request(
            _command("pip", "$PKG"),
            PACKAGE_NAME,
            ContentSaved(None),
            UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.VALUE_SET_AT_RUN_TIME
            ),
        ),
        [],
        PACKAGE,
        [],
    ),
    # The target is a search query.
    (
        "Codex `web_search_call`",
        _request(
            _web_tool("codex", "web_search_call"),
            SEARCH_QUERY,
            ContentShownInResult(),
            "how to x?",
        ),
        [],
        SEARCH,
        [],
    ),
    # No content requested and the target is not a repository, whatever its host.
    (
        "`curl -I https://a.org/x`",
        _curl("https://a.org/x", "a.org", NoContentRequested()),
        [NO_ROW],
        CONNECTIVITY_CHECK,
        [],
    ),
    (
        "`ping pypi.org`",
        _request(
            _command("ping", "pypi.org"),
            HOST,
            NoContentRequested(),
            "pypi.org",
            "pypi.org",
        ),
        [PYPI],
        CONNECTIVITY_CHECK,
        [],
    ),
    (
        "`getent hosts pypi.org`",
        _request(
            _command("getent", "pypi.org"),
            HOST,
            NoContentRequested(),
            "pypi.org",
            "pypi.org",
        ),
        [PYPI],
        CONNECTIVITY_CHECK,
        [],
    ),
    # No content requested and the target is a repository.
    (
        "`git push origin main`",
        GIT_PUSH,
        [],
        OTHER_WEB,
        [REPOSITORY_REQUEST_FOR_NO_CONTENT_RULE],
    ),
    # The content is thrown away, also for a registry host, whose rule comes later, and for a host alone, whose rule comes later too.
    (
        "`curl -s -o /dev/null https://pypi.org`",
        CURL_REGISTRY_TO_DEV_NULL,
        [PYPI],
        CONNECTIVITY_CHECK,
        [DISCARDED_CONTENT_RULE],
    ),
    (
        "`nc api 8000 > /dev/null`",
        _request(_command("nc", "api", "8000"), HOST, ContentDiscarded(), "api", "api"),
        [],
        CONNECTIVITY_CHECK,
        [DISCARDED_CONTENT_RULE],
    ),
    # A host alone that may receive content.
    (
        'code `socket.create_connection(("api", 8000))`',
        SOCKET_CONNECTION,
        [],
        OTHER_WEB,
        [HOST_TARGET_RULE],
    ),
    # A URL from a web tool, whatever its host.
    (
        "`Fetch` of `https://a.org/p`",
        _request(
            _web_tool("claude-code", "Fetch"),
            URL,
            ContentShownInResult(),
            "https://a.org/p",
            "a.org",
        ),
        [NO_ROW],
        CONTENT_FETCH,
        [],
    ),
    (
        "`WebFetch` of `https://pypi.org/project/requests/`",
        _request(
            _web_tool("claude-code", "WebFetch"),
            URL,
            ContentShownInResult(),
            "https://pypi.org/project/requests/",
            "pypi.org",
        ),
        [PYPI],
        CONTENT_FETCH,
        [],
    ),
    (
        "`WebFetch` of `https://html.duckduckgo.com/html?q=x`",
        _request(
            _web_tool("claude-code", "WebFetch"),
            URL,
            ContentShownInResult(),
            "https://html.duckduckgo.com/html?q=x",
            "html.duckduckgo.com",
        ),
        [SEARCH_ENGINE],
        CONTENT_FETCH,
        [],
    ),
    (
        "`WebFetch` of `https://www.google.com/`",
        _request(
            _web_tool("claude-code", "WebFetch"),
            URL,
            ContentShownInResult(),
            "https://www.google.com/",
            "www.google.com",
        ),
        [SEARCH_ENGINE],
        CONTENT_FETCH,
        [],
    ),
    # A repository, saved or shown, also from a host without a row.
    (
        "`git clone https://github.com/a/b`",
        _request(
            _command("git", "https://github.com/a/b"),
            REPOSITORY_URL,
            ContentSaved(None),
            "https://github.com/a/b",
            "github.com",
        ),
        [GITHUB],
        CONTENT_FETCH,
        [],
    ),
    (
        "`git ls-remote https://github.com/a/b`",
        _request(
            _command("git", "https://github.com/a/b"),
            REPOSITORY_URL,
            ContentShownInResult(),
            "https://github.com/a/b",
            "github.com",
        ),
        [GITHUB],
        CONTENT_FETCH,
        [],
    ),
    (
        "`pip install git+https://a.org/b.git`",
        _request(
            _command("pip", "git+https://a.org/b.git"),
            REPOSITORY_URL,
            ContentSaved(None),
            "git+https://a.org/b.git",
            "a.org",
        ),
        [NO_ROW],
        CONTENT_FETCH,
        [],
    ),
    # A URL without a path or a query of a registry or search engine host, which a query alone, a path or a target that cannot be read leaves to the conditions after it.
    (
        'code `requests.get("https://pypi.org")`',
        PYTHON_REGISTRY_FIRST_PAGE,
        [PYPI],
        CONNECTIVITY_CHECK,
        [URL_WITHOUT_PATH_OR_QUERY_RULE],
    ),
    (
        'code `requests.get("https://www.google.com/")`',
        PYTHON_SEARCH_ENGINE_FIRST_PAGE,
        [SEARCH_ENGINE],
        CONNECTIVITY_CHECK,
        [URL_WITHOUT_PATH_OR_QUERY_RULE],
    ),
    (
        "`curl 'https://duckduckgo.com/?q=x'`",
        _curl("https://duckduckgo.com/?q=x", "duckduckgo.com"),
        [SEARCH_ENGINE],
        SEARCH,
        [SEARCH_ENGINE_HOST_RULE],
    ),
    (
        "code `requests.get(url)` whose `url` names `pypi.org` at run time",
        _request(
            _python_code("requests.get"),
            URL,
            UnknownReceivedContentDestination(),
            UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.VALUE_SET_AT_RUN_TIME
            ),
            "pypi.org",
        ),
        [PYPI],
        PACKAGE,
        [PACKAGE_REGISTRY_HOST_RULE],
    ),
    # A URL of a package registry host, shown or saved.
    (
        "`curl https://pypi.org/project/requests/`",
        CURL_PROJECT_PAGE,
        [PYPI],
        PACKAGE,
        [PACKAGE_REGISTRY_HOST_RULE],
    ),
    (
        "`wget https://files.pythonhosted.org/x.whl`",
        WGET_WHEEL,
        [PYPI],
        PACKAGE,
        [PACKAGE_REGISTRY_HOST_RULE],
    ),
    # A URL of a search engine host, also at a search path of an API host.
    (
        "`curl 'https://html.duckduckgo.com/html?q=x'`",
        CURL_SEARCH_PAGE,
        [SEARCH_ENGINE],
        SEARCH,
        [SEARCH_ENGINE_HOST_RULE],
    ),
    (
        "`curl 'https://api.github.com/search/code?q=x'`",
        _curl("https://api.github.com/search/code?q=x", "api.github.com"),
        [SEARCH_ENGINE],
        SEARCH,
        [SEARCH_ENGINE_HOST_RULE],
    ),
    # A URL of a web API host, whatever its content destination, also one without a path.
    (
        'code `requests.get("https://rest.uniprot.org/uniprotkb/P12345.json")`',
        _python_request(
            "https://rest.uniprot.org/uniprotkb/P12345.json", "rest.uniprot.org"
        ),
        [WEB_API],
        REMOTE_API_CALL,
        [],
    ),
    (
        "`curl https://api.github.com/repos/a/b | head`",
        _curl(
            "https://api.github.com/repos/a/b",
            "api.github.com",
            _piped(OutputVisibility.PARTIAL),
        ),
        [WEB_API],
        REMOTE_API_CALL,
        [],
    ),
    (
        "`curl https://api.github.com/repos/a/b`",
        _curl("https://api.github.com/repos/a/b", "api.github.com"),
        [WEB_API],
        REMOTE_API_CALL,
        [],
    ),
    (
        "`curl 'https://huggingface.co/api/models?search=x'`",
        _curl("https://huggingface.co/api/models?search=x", "huggingface.co"),
        [WEB_API],
        REMOTE_API_CALL,
        [],
    ),
    (
        'code `"https://rest.uniprot.org"`',
        _python_request("https://rest.uniprot.org", "rest.uniprot.org"),
        [WEB_API],
        REMOTE_API_CALL,
        [],
    ),
    # A URL of a host that gives a file or a page at a fixed address, saved, piped, shown or in code.
    (
        "`curl -o page.html https://docs.python.org/3/library/json.html`",
        _curl(
            "https://docs.python.org/3/library/json.html",
            "docs.python.org",
            ContentSaved("page.html"),
        ),
        [DOCUMENTATION],
        CONTENT_FETCH,
        [],
    ),
    (
        "`curl https://raw.githubusercontent.com/a/b/main/x.py | head`",
        _curl(
            "https://raw.githubusercontent.com/a/b/main/x.py",
            "raw.githubusercontent.com",
            _piped(OutputVisibility.PARTIAL),
        ),
        [GITHUB],
        CONTENT_FETCH,
        [],
    ),
    (
        "`curl https://github.com/a/b/issues`",
        _curl("https://github.com/a/b/issues", "github.com"),
        [GITHUB],
        CONTENT_FETCH,
        [],
    ),
    (
        "`curl https://files.rcsb.org/download/1abc.pdb | grep ATOM`",
        _curl(
            "https://files.rcsb.org/download/1abc.pdb",
            "files.rcsb.org",
            _piped(OutputVisibility.PARTIAL),
        ),
        [RCSB_FILES],
        CONTENT_FETCH,
        [],
    ),
    (
        "`curl -O https://huggingface.co/a/b/resolve/main/model.bin`",
        _curl(
            "https://huggingface.co/a/b/resolve/main/model.bin",
            "huggingface.co",
            ContentSaved("model.bin"),
        ),
        [HUGGINGFACE],
        CONTENT_FETCH,
        [],
    ),
    (
        'code `"https://huggingface.co"`',
        _python_request("https://huggingface.co", "huggingface.co"),
        [HUGGINGFACE],
        CONTENT_FETCH,
        [],
    ),
    # A URL whose content is saved, from a host without a row. A later read of the file does not change it.
    (
        "`curl -o x https://a.org/x`",
        CURL_SAVED_FROM_HOST_WITHOUT_ROW,
        [NO_ROW],
        CONTENT_FETCH,
        [SAVED_FROM_UNRECOGNIZED_URL_RULE],
    ),
    (
        "`curl -o page.html https://a.org/p` before `cat page.html`",
        _curl("https://a.org/p", "a.org", ContentSaved("page.html")),
        [NO_ROW],
        CONTENT_FETCH,
        [SAVED_FROM_UNRECOGNIZED_URL_RULE],
    ),
    # Any other request. Neither the end of the path nor what was sent makes another category.
    (
        "`curl https://a.org/data.csv | mytool`",
        _curl("https://a.org/data.csv", "a.org", _piped(OutputVisibility.UNKNOWN)),
        [NO_ROW],
        OTHER_WEB,
        [],
    ),
    (
        "`curl https://a.org/x.tgz | tar xz`",
        _curl("https://a.org/x.tgz", "a.org", _piped(OutputVisibility.NONE)),
        [NO_ROW],
        OTHER_WEB,
        [],
    ),
    (
        "`curl https://a.org/x | head`",
        _curl("https://a.org/x", "a.org", _piped(OutputVisibility.PARTIAL)),
        [NO_ROW],
        OTHER_WEB,
        [],
    ),
    (
        "`curl -X POST -d @in.json https://a.org/solve`",
        _curl("https://a.org/solve", "a.org"),
        [NO_ROW],
        OTHER_WEB,
        [],
    ),
    (
        'code `requests.get("https://a.org/x")`',
        _python_request("https://a.org/x", "a.org"),
        [NO_ROW],
        OTHER_WEB,
        [],
    ),
    # Requests that two conditions fit, which get the first. A registry host comes before a search engine host, which comes before a web API host, which comes before a content host, which comes before saving.
    (
        "`curl https://html.duckduckgo.com/html?q=x https://pypi.org/simple/x/` as one request",
        CURL_SEARCH_ENGINE_AND_REGISTRY,
        [SEARCH_ENGINE, PYPI],
        PACKAGE,
        [PACKAGE_REGISTRY_HOST_RULE],
    ),
    (
        "`curl https://html.duckduckgo.com/html?q=x https://rest.uniprot.org/x` as one request",
        CURL_SEARCH_ENGINE_AND_WEB_API,
        [SEARCH_ENGINE, WEB_API],
        SEARCH,
        [SEARCH_ENGINE_HOST_RULE],
    ),
    (
        "`curl https://github.com/a/b https://api.github.com/repos/a/b` as one request",
        _request(
            _command("curl", "https://github.com/a/b"),
            URL,
            ContentShownInResult(),
            "https://github.com/a/b",
            "github.com",
            "api.github.com",
        ),
        [GITHUB, WEB_API],
        REMOTE_API_CALL,
        [],
    ),
    (
        "`curl -o x.json https://rest.uniprot.org/uniprotkb/P12345.json`",
        _curl(
            "https://rest.uniprot.org/uniprotkb/P12345.json",
            "rest.uniprot.org",
            ContentSaved("x.json"),
        ),
        [WEB_API],
        REMOTE_API_CALL,
        [],
    ),
]

# (judgment rule, request, answers of the host catalog, category when the rule answers False, judgment rules still counted once)
OTHER_ANSWER_CASES: list[
    tuple[
        str,
        NetworkRequest,
        list[PublicHost | UnknownPublicHost],
        NetworkRequestCategory,
        list[str],
    ]
] = [
    (REPOSITORY_REQUEST_FOR_NO_CONTENT_RULE, GIT_PUSH, [], CONNECTIVITY_CHECK, []),
    (DISCARDED_CONTENT_RULE, CURL_REGISTRY_TO_DEV_NULL, [PYPI], OTHER_WEB, []),
    (HOST_TARGET_RULE, SOCKET_CONNECTION, [], CONNECTIVITY_CHECK, []),
    # A URL without a path or a query that the rule does not take goes by the service of its host.
    (
        URL_WITHOUT_PATH_OR_QUERY_RULE,
        PYTHON_REGISTRY_FIRST_PAGE,
        [PYPI],
        PACKAGE,
        [PACKAGE_REGISTRY_HOST_RULE],
    ),
    (
        URL_WITHOUT_PATH_OR_QUERY_RULE,
        PYTHON_SEARCH_ENGINE_FIRST_PAGE,
        [SEARCH_ENGINE],
        SEARCH,
        [SEARCH_ENGINE_HOST_RULE],
    ),
    # A registry host that the rule does not take leaves the conditions after it, i.e. a search engine host, saving and any other request.
    (PACKAGE_REGISTRY_HOST_RULE, CURL_PROJECT_PAGE, [PYPI], OTHER_WEB, []),
    (
        PACKAGE_REGISTRY_HOST_RULE,
        WGET_WHEEL,
        [PYPI],
        CONTENT_FETCH,
        [SAVED_FROM_UNRECOGNIZED_URL_RULE],
    ),
    (
        PACKAGE_REGISTRY_HOST_RULE,
        CURL_SEARCH_ENGINE_AND_REGISTRY,
        [SEARCH_ENGINE, PYPI],
        SEARCH,
        [SEARCH_ENGINE_HOST_RULE],
    ),
    (SEARCH_ENGINE_HOST_RULE, CURL_SEARCH_PAGE, [SEARCH_ENGINE], OTHER_WEB, []),
    (
        SEARCH_ENGINE_HOST_RULE,
        CURL_SEARCH_ENGINE_AND_WEB_API,
        [SEARCH_ENGINE, WEB_API],
        REMOTE_API_CALL,
        [],
    ),
    (
        SAVED_FROM_UNRECOGNIZED_URL_RULE,
        CURL_SAVED_FROM_HOST_WITHOUT_ROW,
        [NO_ROW],
        OTHER_WEB,
        [],
    ),
]


@pytest.mark.parametrize(
    ("network_request", "public_hosts", "category", "counted_rules"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_category_comes_from_the_first_condition_that_fits_and_counts_the_rule_it_asks(
    network_request: NetworkRequest,
    public_hosts: list[PublicHost | UnknownPublicHost],
    category: NetworkRequestCategory,
    counted_rules: list[str],
):
    judgment_rule_use_counts: Counter[str] = Counter()

    assert (
        export_network_request_category(
            network_request,
            public_hosts,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        == category
    )
    assert judgment_rule_use_counts == Counter(counted_rules)


@pytest.mark.parametrize(
    ("rule", "network_request", "public_hosts", "category", "counted_rules"),
    OTHER_ANSWER_CASES,
    ids=[
        f"{case[0]} on {case[1].target} {index}"
        for index, case in enumerate(OTHER_ANSWER_CASES)
    ],
)
def test_category_follows_the_other_answer_of_each_judgment_rule(
    monkeypatch: pytest.MonkeyPatch,
    rule: str,
    network_request: NetworkRequest,
    public_hosts: list[PublicHost | UnknownPublicHost],
    category: NetworkRequestCategory,
    counted_rules: list[str],
):
    monkeypatch.setattr(
        _export_network_request_category,
        rule,
        lambda network_request, *, use_counts: False,
    )
    judgment_rule_use_counts: Counter[str] = Counter()

    assert (
        export_network_request_category(
            network_request,
            public_hosts,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        == category
    )
    assert judgment_rule_use_counts == Counter(counted_rules)
