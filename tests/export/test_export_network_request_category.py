"""Tests for _export_network_request_category.py, one made-up request for each condition of its module docstring in order, then requests that two conditions fit and each judgment rule with its other answer."""

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
    treat_content_piped_to_consuming_command_as_other_web,
    treat_content_piped_to_showing_command_as_other_web,
    treat_discarded_content_as_other_web,
    treat_host_target_that_may_receive_content_as_other_web,
    treat_repository_request_for_no_content_as_other_web,
    treat_saved_content_from_package_registry_host_as_content_fetch,
    treat_shown_content_from_registry_or_model_hub_host_as_other_web,
    treat_shown_content_from_search_engine_host_as_other_web,
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
CONNECTIVITY_CHECK = NetworkRequestCategory.CONNECTIVITY_CHECK
OTHER_WEB = NetworkRequestCategory.OTHER_WEB
UNKNOWN = NetworkRequestCategory.UNKNOWN

PACKAGE_NAME = NetworkRequestTargetKind.PACKAGE_NAME
REPOSITORY_URL = NetworkRequestTargetKind.REPOSITORY_URL
URL = NetworkRequestTargetKind.URL
SEARCH_QUERY = NetworkRequestTargetKind.SEARCH_QUERY
HOST = NetworkRequestTargetKind.HOST

# The answers of the host catalog of the made-up cases. `a.org` and `api.github.com` have no row in `CASES`. `OTHER_ANSWER_CASES` gives them `PYPI` and `GITHUB` in one case each, so that a piped request whose rule answers False reaches the conditions of saved or shown content from such a host.
PYPI = PublicHost(HostService.PACKAGE_REGISTRY, "pypi")
GITHUB = PublicHost(HostService.CODE_HOSTING, None)
HUGGINGFACE = PublicHost(HostService.MODEL_HUB, None)
DUCKDUCKGO = PublicHost(HostService.SEARCH_ENGINE, None)
NO_ROW = UnknownPublicHost()

REPOSITORY_REQUEST_FOR_NO_CONTENT_RULE = (
    treat_repository_request_for_no_content_as_other_web.__name__
)
DISCARDED_CONTENT_RULE = treat_discarded_content_as_other_web.__name__
HOST_TARGET_RULE = treat_host_target_that_may_receive_content_as_other_web.__name__
SAVED_FROM_PACKAGE_REGISTRY_RULE = (
    treat_saved_content_from_package_registry_host_as_content_fetch.__name__
)
PIPED_TO_CONSUMING_COMMAND_RULE = (
    treat_content_piped_to_consuming_command_as_other_web.__name__
)
PIPED_TO_SHOWING_COMMAND_RULE = (
    treat_content_piped_to_showing_command_as_other_web.__name__
)
SHOWN_FROM_SEARCH_ENGINE_RULE = (
    treat_shown_content_from_search_engine_host_as_other_web.__name__
)
SHOWN_FROM_REGISTRY_OR_MODEL_HUB_RULE = (
    treat_shown_content_from_registry_or_model_hub_host_as_other_web.__name__
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


def _piped(visibility_at_end: OutputVisibility) -> ContentPipedToCommand:
    return ContentPipedToCommand(1, visibility_at_end)


SUBPROCESS_PIP_INSTALL = _request(
    _python_code("subprocess.run"),
    UnknownNetworkRequestTargetKind(),
    UnknownReceivedContentDestination(),
    UnknownNetworkRequestTarget(UnknownNetworkRequestTargetReason.BUILT_IN_CODE),
)
PIP_INSTALL_REQUESTS = _request(
    _command("pip", "requests"), PACKAGE_NAME, ContentSaved(None), "requests"
)
WEB_SEARCH = _request(
    _web_tool("codex", "web_search_call"),
    SEARCH_QUERY,
    ContentShownInResult(),
    "how to x?",
)
CURL_HEAD = _request(
    _command("curl", "https://a.org/x"),
    URL,
    NoContentRequested(),
    "https://a.org/x",
    "a.org",
)
GIT_PUSH = _request(
    _command("git", "origin", "main"), REPOSITORY_URL, NoContentRequested(), None
)
CURL_TO_DEV_NULL = _request(
    _command("curl", "https://a.org/x"),
    URL,
    ContentDiscarded(),
    "https://a.org/x",
    "a.org",
)
SOCKET_CONNECTION = _request(
    _python_code("socket.create_connection"),
    HOST,
    UnknownReceivedContentDestination(),
    "api",
    "api",
)
WGET_WHEEL = _request(
    _command("wget", "https://pypi.org/packages/x.whl"),
    URL,
    ContentSaved("x.whl"),
    "https://pypi.org/packages/x.whl",
    "pypi.org",
)
CURL_TO_TAR = _request(
    _command("curl", "https://a.org/x.tgz"),
    URL,
    _piped(OutputVisibility.NONE),
    "https://a.org/x.tgz",
    "a.org",
)
CURL_TO_HEAD = _request(
    _command("curl", "https://api.github.com/repos/a/b/releases/latest"),
    URL,
    _piped(OutputVisibility.PARTIAL),
    "https://api.github.com/repos/a/b/releases/latest",
    "api.github.com",
)
FETCH_PAGE = _request(
    _web_tool("claude-code", "Fetch"),
    URL,
    ContentShownInResult(),
    "https://a.org/p",
    "a.org",
)
CURL_README = _request(
    _command("curl", "https://github.com/a/b/README.md"),
    URL,
    ContentShownInResult(),
    "https://github.com/a/b/README.md",
    "github.com",
)
CURL_SEARCH_PAGE = _request(
    _command("curl", "https://duckduckgo.com/html?q=x"),
    URL,
    ContentShownInResult(),
    "https://duckduckgo.com/html?q=x",
    "duckduckgo.com",
)
CURL_PROJECT_PAGE = _request(
    _command("curl", "https://pypi.org/project/requests/"),
    URL,
    ContentShownInResult(),
    "https://pypi.org/project/requests/",
    "pypi.org",
)
CURL_POST = _request(
    _command("curl", "https://a.org/solve"),
    URL,
    ContentShownInResult(),
    "https://a.org/solve",
    "a.org",
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
        SUBPROCESS_PIP_INSTALL,
        [],
        UNKNOWN,
        [],
    ),
    # The target is a package name, which does not need to be known.
    ("`pip install requests`", PIP_INSTALL_REQUESTS, [], PACKAGE, []),
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
    # A package name, though the content is saved.
    (
        "`pip install --index-url https://mirror.internal/simple x`",
        _request(
            _command("pip", "x"),
            PACKAGE_NAME,
            ContentSaved(None),
            "x",
            "mirror.internal",
        ),
        [],
        PACKAGE,
        [],
    ),
    # The target is a search query.
    ("Codex `web_search_call`", WEB_SEARCH, [], SEARCH, []),
    # No content requested and the target is not a repository.
    ("`curl -I https://a.org/x`", CURL_HEAD, [NO_ROW], CONNECTIVITY_CHECK, []),
    # No content requested and the target is a repository.
    (
        "`git push origin main`",
        GIT_PUSH,
        [],
        OTHER_WEB,
        [REPOSITORY_REQUEST_FOR_NO_CONTENT_RULE],
    ),
    # The content is thrown away.
    (
        "`curl -s -o /dev/null https://a.org/x`",
        CURL_TO_DEV_NULL,
        [NO_ROW],
        OTHER_WEB,
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
    # Saved content from a package registry host.
    (
        "`wget https://pypi.org/packages/x.whl`",
        WGET_WHEEL,
        [PYPI],
        CONTENT_FETCH,
        [SAVED_FROM_PACKAGE_REGISTRY_RULE],
    ),
    # Saved content from a repository on code hosting, from a host without a row and from a model hub. A later read of the file does not change it.
    (
        "`pip install git+https://github.com/a/b`",
        _request(
            _command("pip", "git+https://github.com/a/b"),
            REPOSITORY_URL,
            ContentSaved(None),
            "git+https://github.com/a/b",
            "github.com",
        ),
        [GITHUB],
        CONTENT_FETCH,
        [],
    ),
    (
        "`curl -o page.html https://a.org/p` before `cat page.html`",
        _request(
            _command("curl", "https://a.org/p"),
            URL,
            ContentSaved("page.html"),
            "https://a.org/p",
            "a.org",
        ),
        [NO_ROW],
        CONTENT_FETCH,
        [],
    ),
    (
        "`curl -O https://huggingface.co/m/model.bin`",
        _request(
            _command("curl", "https://huggingface.co/m/model.bin"),
            URL,
            ContentSaved("model.bin"),
            "https://huggingface.co/m/model.bin",
            "huggingface.co",
        ),
        [HUGGINGFACE],
        CONTENT_FETCH,
        [],
    ),
    # Content piped to a command that shows none of it.
    (
        "`curl https://a.org/x.tgz | tar xz`",
        CURL_TO_TAR,
        [NO_ROW],
        OTHER_WEB,
        [PIPED_TO_CONSUMING_COMMAND_RULE],
    ),
    # Content piped to a command that shows part of it and to one that shows all of it.
    (
        "`curl https://api.github.com/repos/a/b/releases/latest | head`",
        CURL_TO_HEAD,
        [NO_ROW],
        OTHER_WEB,
        [PIPED_TO_SHOWING_COMMAND_RULE],
    ),
    (
        "`curl https://a.org/x | tee log`",
        _request(
            _command("curl", "https://a.org/x"),
            URL,
            _piped(OutputVisibility.WHOLE),
            "https://a.org/x",
            "a.org",
        ),
        [NO_ROW],
        OTHER_WEB,
        [PIPED_TO_SHOWING_COMMAND_RULE],
    ),
    # Shown content from a web tool, here a tool without a row of the web tool catalog.
    ("`Fetch` of `https://a.org/p`", FETCH_PAGE, [NO_ROW], CONTENT_FETCH, []),
    # Shown content from a code hosting host.
    (
        "`curl https://github.com/a/b/README.md`",
        CURL_README,
        [GITHUB],
        CONTENT_FETCH,
        [],
    ),
    # Shown content from a search engine host.
    (
        "`curl 'https://duckduckgo.com/html?q=x'`",
        CURL_SEARCH_PAGE,
        [DUCKDUCKGO],
        OTHER_WEB,
        [SHOWN_FROM_SEARCH_ENGINE_RULE],
    ),
    # Shown content from a package registry host and from a model hub host.
    (
        "`curl https://pypi.org/project/requests/`",
        CURL_PROJECT_PAGE,
        [PYPI],
        OTHER_WEB,
        [SHOWN_FROM_REGISTRY_OR_MODEL_HUB_RULE],
    ),
    (
        "`curl https://huggingface.co/api/models/m`",
        _request(
            _command("curl", "https://huggingface.co/api/models/m"),
            URL,
            ContentShownInResult(),
            "https://huggingface.co/api/models/m",
            "huggingface.co",
        ),
        [HUGGINGFACE],
        OTHER_WEB,
        [SHOWN_FROM_REGISTRY_OR_MODEL_HUB_RULE],
    ),
    # Any other request. What was sent does not make a remote API call, and a code hosting host without a row gives no service.
    (
        "`curl -X POST -d @in.json https://a.org/solve`",
        CURL_POST,
        [NO_ROW],
        OTHER_WEB,
        [],
    ),
    (
        "`curl https://api.github.com/repos/a/b/releases/latest`",
        _request(
            _command("curl", "https://api.github.com/repos/a/b/releases/latest"),
            URL,
            ContentShownInResult(),
            "https://api.github.com/repos/a/b/releases/latest",
            "api.github.com",
        ),
        [NO_ROW],
        OTHER_WEB,
        [],
    ),
    (
        "`curl https://a.org/x | mytool`",
        _request(
            _command("curl", "https://a.org/x"),
            URL,
            _piped(OutputVisibility.UNKNOWN),
            "https://a.org/x",
            "a.org",
        ),
        [NO_ROW],
        OTHER_WEB,
        [],
    ),
    (
        'code `requests.get("https://a.org/x")`',
        _request(
            _python_code("requests.get"),
            URL,
            UnknownReceivedContentDestination(),
            "https://a.org/x",
            "a.org",
        ),
        [NO_ROW],
        OTHER_WEB,
        [],
    ),
    # Requests that two conditions fit, which get the first. `ping pypi.org` asks for no content and is for a host alone, and is no package though its host is a registry.
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
    # A web fetch of a registry page is shown content from a web tool and from a package registry host.
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
    # Shown content from a code hosting host and a search engine host.
    (
        "`curl https://github.com/a/b https://duckduckgo.com/html?q=x` as one request",
        _request(
            _command("curl", "https://github.com/a/b"),
            URL,
            ContentShownInResult(),
            "https://github.com/a/b",
            "github.com",
            "duckduckgo.com",
        ),
        [GITHUB, DUCKDUCKGO],
        CONTENT_FETCH,
        [],
    ),
    # Discarded content for a host alone is decided by the rule about discarded content, not the one about a host alone.
    (
        "`nc api 8000 > /dev/null`",
        _request(_command("nc", "api", "8000"), HOST, ContentDiscarded(), "api", "api"),
        [],
        OTHER_WEB,
        [DISCARDED_CONTENT_RULE],
    ),
    # Shown content from a search engine host and a package registry host asks only the rule about a search engine.
    (
        "`curl https://duckduckgo.com/html?q=x https://pypi.org/simple/x/` as one request",
        _request(
            _command("curl", "https://duckduckgo.com/html?q=x"),
            URL,
            ContentShownInResult(),
            "https://duckduckgo.com/html?q=x",
            "duckduckgo.com",
            "pypi.org",
        ),
        [DUCKDUCKGO, PYPI],
        OTHER_WEB,
        [SHOWN_FROM_SEARCH_ENGINE_RULE],
    ),
    # Shown content from a code hosting host and a package registry host asks no rule.
    (
        "`curl https://github.com/a/b https://pypi.org/project/b/` as one request",
        _request(
            _command("curl", "https://github.com/a/b"),
            URL,
            ContentShownInResult(),
            "https://github.com/a/b",
            "github.com",
            "pypi.org",
        ),
        [GITHUB, PYPI],
        CONTENT_FETCH,
        [],
    ),
    # A web tool asks no rule, even for a search engine host.
    (
        "`WebFetch` of `https://duckduckgo.com/html?q=x`",
        _request(
            _web_tool("claude-code", "WebFetch"),
            URL,
            ContentShownInResult(),
            "https://duckduckgo.com/html?q=x",
            "duckduckgo.com",
        ),
        [DUCKDUCKGO],
        CONTENT_FETCH,
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
    (DISCARDED_CONTENT_RULE, CURL_TO_DEV_NULL, [NO_ROW], CONNECTIVITY_CHECK, []),
    (HOST_TARGET_RULE, SOCKET_CONNECTION, [], CONNECTIVITY_CHECK, []),
    (SAVED_FROM_PACKAGE_REGISTRY_RULE, WGET_WHEEL, [PYPI], PACKAGE, []),
    # Content piped to a command that shows none of it gets the category of saved content, which asks the rule about saved content only when a host is a package registry.
    (PIPED_TO_CONSUMING_COMMAND_RULE, CURL_TO_TAR, [NO_ROW], CONTENT_FETCH, []),
    (
        PIPED_TO_CONSUMING_COMMAND_RULE,
        CURL_TO_TAR,
        [PYPI],
        CONTENT_FETCH,
        [SAVED_FROM_PACKAGE_REGISTRY_RULE],
    ),
    # Content piped to a command that shows it gets the category of shown content.
    (PIPED_TO_SHOWING_COMMAND_RULE, CURL_TO_HEAD, [GITHUB], CONTENT_FETCH, []),
    (SHOWN_FROM_SEARCH_ENGINE_RULE, CURL_SEARCH_PAGE, [DUCKDUCKGO], SEARCH, []),
    (
        SHOWN_FROM_REGISTRY_OR_MODEL_HUB_RULE,
        CURL_PROJECT_PAGE,
        [PYPI],
        CONTENT_FETCH,
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
