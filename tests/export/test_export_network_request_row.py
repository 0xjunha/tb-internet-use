"""Tests for _export_network_request_row.py, with made-up requests and made-up catalogs, one case for each condition of its module docstring in order, then requests that two conditions fit, each judgment rule with its other answer, and the text columns."""

from collections import Counter
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    CallCommandText,
    CodeLanguage,
    FileText,
    FileTextWithoutKnownWriter,
    FileUse,
    FileUseKind,
    OutputVisibility,
    PollInputText,
    ProgramInvocation,
    RanTextSource,
    ScriptStepText,
    StdinText,
    UnknownProgramInvocation,
)
from tb_internet_use.export import _export_network_request_row
from tb_internet_use.export._export_network_request_row import (
    export_network_request_row,
)
from tb_internet_use.export.judgment_rules import (
    treat_assumed_failure_as_possibly_received,
    treat_assumed_not_needed_result_as_upper_bound_only,
    treat_discarded_content_as_other_web,
    treat_host_target_that_may_receive_content_as_other_web,
    treat_local_host_name_of_web_tool_as_unknown_internet_use,
    treat_repository_request_for_no_content_as_other_web,
    treat_request_without_host_name_as_sent_to_default_registry_host,
    treat_reserved_host_name_as_unknown_internet_use,
    treat_saved_content_from_package_registry_host_as_fetched_file,
    treat_shown_content_from_search_engine_host_as_other_web,
    treat_unclassified_host_name_as_unknown_internet_use,
    treat_url_query_value_and_fragment_as_credential,
    treat_web_tool_request_without_host_name_as_internet_use,
)
from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
    NetworkRequestSourceKind,
)
from tb_internet_use.knowledge.export_knowledge import (
    HARNESS_WEB_TOOLS_CSV,
    PROGRAM_PACKAGE_REGISTRIES_CSV,
    PUBLIC_HOSTS_CSV,
    ExportKnowledge,
)
from tb_internet_use.network_request.judgment_rules import (
    treat_dotted_host_name_as_public,
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
    UnknownCodeCall,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetKind,
    UnknownNetworkRequestTargetReason,
    UnknownReceivedContentDestination,
)
from tb_internet_use.network_request_result.model import (
    ExecutionStatusEvidence,
    ExitCodeEvidence,
    FileUseEvidence,
    HttpStatusEvidence,
    NetworkRequestResult,
    NetworkRequestResultCertainty,
    NetworkRequestResultEvidence,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
    ShownContentEvidence,
)
from tb_internet_use.tool_call.model import ExecutionStatus, HarnessTool, ToolCallKey

LOWER_AND_UPPER = MeasureBound.LOWER_AND_UPPER
UPPER_ONLY = MeasureBound.UPPER_ONLY
NEITHER = MeasureBound.NEITHER
ATTEMPTED = NetworkRequestResultLevel.ATTEMPTED
EXECUTED = NetworkRequestResultLevel.EXECUTED
REACHED = NetworkRequestResultLevel.REACHED
RECEIVED = NetworkRequestResultLevel.RECEIVED
FAILED = NetworkRequestResultStopReason.FAILED
NOT_VISIBLE = NetworkRequestResultStopReason.NOT_VISIBLE
NOT_NEEDED = NetworkRequestResultStopReason.NOT_NEEDED
CONFIRMED = NetworkRequestResultCertainty.CONFIRMED
ASSUMED = NetworkRequestResultCertainty.ASSUMED
PACKAGE_NAME = NetworkRequestTargetKind.PACKAGE_NAME
REPOSITORY_URL = NetworkRequestTargetKind.REPOSITORY_URL
URL = NetworkRequestTargetKind.URL
SEARCH_QUERY = NetworkRequestTargetKind.SEARCH_QUERY
HOST = NetworkRequestTargetKind.HOST

WEB_TOOL_WITHOUT_HOST_RULE = (
    treat_web_tool_request_without_host_name_as_internet_use.__name__
)
DEFAULT_REGISTRY_RULE = (
    treat_request_without_host_name_as_sent_to_default_registry_host.__name__
)
UNCLASSIFIED_HOST_RULE = treat_unclassified_host_name_as_unknown_internet_use.__name__
RESERVED_HOST_RULE = treat_reserved_host_name_as_unknown_internet_use.__name__
LOCAL_HOST_OF_WEB_TOOL_RULE = (
    treat_local_host_name_of_web_tool_as_unknown_internet_use.__name__
)
ASSUMED_NOT_NEEDED_RULE = treat_assumed_not_needed_result_as_upper_bound_only.__name__
ASSUMED_FAILURE_RULE = treat_assumed_failure_as_possibly_received.__name__
DOTTED_HOST_RULE = treat_dotted_host_name_as_public.__name__
CREDENTIAL_RULE = treat_url_query_value_and_fragment_as_credential.__name__
REPOSITORY_REQUEST_FOR_NO_CONTENT_RULE = (
    treat_repository_request_for_no_content_as_other_web.__name__
)
DISCARDED_CONTENT_RULE = treat_discarded_content_as_other_web.__name__
HOST_TARGET_RULE = treat_host_target_that_may_receive_content_as_other_web.__name__
SAVED_FROM_PACKAGE_REGISTRY_RULE = (
    treat_saved_content_from_package_registry_host_as_fetched_file.__name__
)
SHOWN_FROM_SEARCH_ENGINE_RULE = (
    treat_shown_content_from_search_engine_host_as_other_web.__name__
)

_REVIEW_COLUMNS = ",a manual,,"
# The made-up host catalog. `a.org` and `api.github.com` have no row.
PUBLIC_HOST_ROWS = (
    "pypi.org,package_registry,pypi",
    "github.com,code_hosting,",
    "huggingface.co,model_hub,",
    "duckduckgo.com,search_engine,",
)
# The made-up web tool catalog. Claude Code `Fetch` has no row.
HARNESS_WEB_TOOL_ROWS = (
    "codex,web_search_call,provider_server",
    "codex,exec,provider_server",
    "claude-code,WebFetch,harness_process",
)
# The made-up package registry catalog. `conda install` and `uv pip install` have no row.
PROGRAM_PACKAGE_REGISTRY_ROWS = (
    "pip,install,pypi,pypi.org",
    "npm,ci,npm,registry.npmjs.org",
    "apt-get,update,apt,deb.debian.org archive.ubuntu.com",
    "npx,,npm,registry.npmjs.org",
)
# A made-up package registry catalog whose default hosts are not public, e.g. a registry served inside the task environment.
INTERNAL_PROGRAM_PACKAGE_REGISTRY_ROWS = (
    "pip,install,devpi,localhost",
    "pip,download,devpi,devpi",
)

CALL_COMMAND_TEXT = CallCommandText()
CONTENT_SHOWN_IN_RESULT = ContentShownInResult()
EXIT_CODE_0 = ExitCodeEvidence(ToolCallKey("t1", "main", 1, 0), 0, False)
SHARED_ERROR_LINE = OutputLineEvidence(
    ToolCallKey("t1", "main", 1, 0), 0, None, OutputLineKind.CONNECTION_FAILED, True
)
SHARED_ALREADY_PRESENT_LINE = OutputLineEvidence(
    ToolCallKey("t1", "main", 1, 0), 0, None, OutputLineKind.ALREADY_PRESENT, True
)
PROGRAM_MISSING_LINE = OutputLineEvidence(
    ToolCallKey("t1", "main", 1, 0), 0, None, OutputLineKind.PROGRAM_MISSING, False
)


def _write_catalogs(
    catalogs_dir: Path, program_package_registry_rows: tuple[str, ...]
) -> Path:
    """Write the three made-up export CSVs into a folder and return the folder."""
    catalogs_dir.mkdir()
    for file_name, header, rows in (
        (
            PUBLIC_HOSTS_CSV,
            "host_name,service,package_registry,checked_against,reviewed,note",
            PUBLIC_HOST_ROWS,
        ),
        (
            HARNESS_WEB_TOOLS_CSV,
            "harness,tool,sender,checked_against,reviewed,note",
            HARNESS_WEB_TOOL_ROWS,
        ),
        (
            PROGRAM_PACKAGE_REGISTRIES_CSV,
            "program_name,subcommand,package_registry,package_registry_host_names,checked_against,reviewed,note",
            program_package_registry_rows,
        ),
    ):
        lines = [header, *(row + _REVIEW_COLUMNS for row in rows)]
        (catalogs_dir / file_name).write_text("\n".join(lines) + "\n")
    return catalogs_dir


@pytest.fixture(scope="module")
def catalogs_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _write_catalogs(
        tmp_path_factory.mktemp("export") / "catalogs", PROGRAM_PACKAGE_REGISTRY_ROWS
    )


@pytest.fixture(scope="module")
def internal_catalogs_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _write_catalogs(
        tmp_path_factory.mktemp("export") / "catalogs",
        INTERNAL_PROGRAM_PACKAGE_REGISTRY_ROWS,
    )


@pytest.fixture
def knowledge(catalogs_dir: Path) -> ExportKnowledge:
    return ExportKnowledge(catalogs_dir=catalogs_dir)


def _program(program_name: str, *subcommand_words: str) -> ProgramInvocation:
    return ProgramInvocation(
        program_name=program_name,
        subcommand_words=subcommand_words,
        options=(),
        arguments=(),
        gets_more_arguments_at_run_time=False,
        unread_words=(),
        exits_with_exit_code_of_next_program=False,
    )


def _command(
    program_invocation: ProgramInvocation | UnknownProgramInvocation,
    ran_text_source: RanTextSource = CALL_COMMAND_TEXT,
) -> FromCommand:
    return FromCommand(2, ran_text_source, program_invocation)


def _web_tool(harness: str, tool: str, step_index: int | None = None) -> FromWebTool:
    return FromWebTool(step_index, HarnessTool(harness, tool))


def _request(
    source: NetworkRequestSource,
    target: str | UnknownNetworkRequestTarget | None,
    target_kind: NetworkRequestTargetKind | UnknownNetworkRequestTargetKind,
    received_content_destination: ReceivedContentDestination,
    *host_names: str,
    uncertainty_reason: NetworkRequestUncertaintyReason | None = None,
) -> NetworkRequest:
    """Make a request of the call 1.0 of trial t1, uncertain when given a reason."""
    return NetworkRequest(
        tool_call_key=ToolCallKey("t1", "main", 1, 0),
        index_in_tool_call=0,
        source=source,
        target=target,
        target_kind=target_kind,
        host_names=host_names,
        received_content_destination=received_content_destination,
        certainty=NetworkRequestCertainty.CONFIRMED
        if uncertainty_reason is None
        else NetworkRequestCertainty.UNCERTAIN,
        uncertainty_reason=uncertainty_reason,
    )


def _result(
    network_request: NetworkRequest,
    level: NetworkRequestResultLevel | None = None,
    stop_reason: NetworkRequestResultStopReason | None = None,
    level_certainty: NetworkRequestResultCertainty = CONFIRMED,
    evidence: tuple[NetworkRequestResultEvidence, ...] = (EXIT_CODE_0,),
    request_certainty_after_evidence: NetworkRequestCertainty | None = None,
) -> NetworkRequestResult:
    """Make the result of a request, by default the success that it asked for, with its own certainty after the evidence."""
    if level is None:
        level = (
            REACHED
            if isinstance(
                network_request.received_content_destination, NoContentRequested
            )
            else RECEIVED
        )
    return NetworkRequestResult(
        network_request=network_request,
        request_certainty_after_evidence=network_request.certainty
        if request_certainty_after_evidence is None
        else request_certainty_after_evidence,
        level=level,
        stop_reason=stop_reason,
        level_certainty=level_certainty,
        evidence=evidence,
    )


def _exported(
    network_request_result: NetworkRequestResult, knowledge: ExportKnowledge
) -> tuple[NetworkRequestRow, Counter[str]]:
    judgment_rule_use_counts: Counter[str] = Counter()
    network_request_row = export_network_request_row(
        network_request_result,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    return network_request_row, judgment_rule_use_counts


def _columns_of(
    network_request_row: NetworkRequestRow, column_names: list[str]
) -> dict[str, object]:
    return {
        column_name: getattr(network_request_row, column_name)
        for column_name in column_names
    }


def _curl(
    url: str,
    host_name: str,
    received_content_destination: ReceivedContentDestination = CONTENT_SHOWN_IN_RESULT,
) -> NetworkRequest:
    return _request(
        _command(_program("curl")), url, URL, received_content_destination, host_name
    )


PIP_INSTALL_REQUESTS = _request(
    _command(_program("pip", "install")),
    "requests",
    PACKAGE_NAME,
    ContentSaved(None),
)
CURL_A_ORG = _curl("https://a.org/x", "a.org")
CURL_DB = _curl("http://db:5432/", "db")
CURL_EXAMPLE = _curl("https://example.com/", "example.com")
CURL_LOCALHOST = _curl("http://localhost:8000/health", "localhost")
WEB_SEARCH = _request(
    _web_tool("codex", "web_search_call"),
    "how to x?",
    SEARCH_QUERY,
    ContentShownInResult(),
)
WEB_FETCH_LOCALHOST = _request(
    _web_tool("claude-code", "WebFetch"),
    "http://localhost:3000/",
    URL,
    ContentShownInResult(),
    "localhost",
)
NPX_TSC = _request(
    _command(_program("npx")),
    "tsc",
    PACKAGE_NAME,
    ContentSaved(None),
    uncertainty_reason=NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING,
)
MYTOOL_A_ORG = _request(
    _command(UnknownProgramInvocation("mytool", ("https://a.org/x",))),
    "https://a.org/x",
    URL,
    UnknownReceivedContentDestination(),
    "a.org",
    uncertainty_reason=NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM,
)

# (case, request, expected columns, judgment rules counted with their uses)
INTERNET_USE_CASES: list[
    tuple[str, NetworkRequest, dict[str, object], dict[str, int]]
] = [
    # A public host.
    (
        "curl https://a.org/x",
        CURL_A_ORG,
        {"is_internet_use": True, "host_scope": "public", "host_service": "unknown"},
        {DOTTED_HOST_RULE: 1},
    ),
    # No host and a web tool source.
    (
        "web search of Codex",
        WEB_SEARCH,
        {
            "category": NetworkRequestCategory.SEARCH,
            "is_internet_use": True,
            "sender": NetworkRequestSender.PROVIDER_SERVER,
            "made_by": "web_search_call",
            "source": "web tool",
            "target": "how to x?",
            "host_scope": "",
        },
        {WEB_TOOL_WITHOUT_HOST_RULE: 1},
    ),
    # No host and any other source, sent to the default registry host.
    (
        "pip install requests",
        PIP_INSTALL_REQUESTS,
        {
            "category": NetworkRequestCategory.PACKAGE,
            "package_registry": "pypi",
            "host_scope": "",
            "host_service": "",
            "is_internet_use": True,
            "sender": NetworkRequestSender.TASK_ENVIRONMENT,
            "request_measure_bound": LOWER_AND_UPPER,
        },
        {DEFAULT_REGISTRY_RULE: 1, DOTTED_HOST_RULE: 1},
    ),
    # A host name without a dot or with a template.
    (
        "curl http://db:5432/",
        CURL_DB,
        {
            "host_scope": "unknown_single_label",
            "host_service": "not_public",
            "is_internet_use": None,
            "request_measure_bound": UPPER_ONLY,
        },
        {UNCLASSIFIED_HOST_RULE: 1},
    ),
    (
        "curl https://$HOST/x",
        _curl("https://$HOST/x", "$HOST"),
        {"host_scope": "unknown_templated", "is_internet_use": None},
        {UNCLASSIFIED_HOST_RULE: 1},
    ),
    # A reserved host name.
    (
        "curl https://example.com/",
        CURL_EXAMPLE,
        {"host_scope": "reserved", "is_internet_use": None},
        {RESERVED_HOST_RULE: 1},
    ),
    # Only local hosts and a web tool source.
    (
        "web fetch of http://localhost:3000/",
        WEB_FETCH_LOCALHOST,
        {"is_internet_use": None, "sender": NetworkRequestSender.HARNESS_PROCESS},
        {LOCAL_HOST_OF_WEB_TOOL_RULE: 1},
    ),
    # Only local hosts.
    (
        "curl http://localhost:8000/health",
        CURL_LOCALHOST,
        {
            "host_scope": "local",
            "host_service": "not_public",
            "is_internet_use": False,
            "request_measure_bound": NEITHER,
            "received_measure_bound": NEITHER,
        },
        {},
    ),
    # Requests that two conditions fit, where the first wins.
    (
        "a local and a public host",
        _request(
            _command(_program("curl")),
            "http://10.0.0.5/x",
            URL,
            ContentShownInResult(),
            "10.0.0.5",
            "a.org",
        ),
        {
            "host_names": "10.0.0.5 a.org",
            "host_scope": "local public",
            "host_service": "not_public unknown",
            "is_internet_use": True,
        },
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "a single label and a public host",
        _request(
            _command(_program("curl")),
            "http://db/x",
            URL,
            ContentShownInResult(),
            "db",
            "github.com",
        ),
        {"host_service": "not_public code_hosting", "is_internet_use": True},
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "a single label and a reserved host",
        _request(
            _command(_program("curl")),
            "http://db/x",
            URL,
            ContentShownInResult(),
            "example.com",
            "db",
        ),
        {"host_scope": "reserved unknown_single_label", "is_internet_use": None},
        {UNCLASSIFIED_HOST_RULE: 1},
    ),
    (
        "a web tool with a public host",
        _request(
            _web_tool("claude-code", "WebFetch"),
            "https://a.org/p",
            URL,
            ContentShownInResult(),
            "a.org",
        ),
        {"is_internet_use": True, "category": NetworkRequestCategory.PAGE_READ},
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "a web tool with a reserved host",
        _request(
            _web_tool("claude-code", "WebFetch"),
            "https://example.com/",
            URL,
            ContentShownInResult(),
            "example.com",
        ),
        {"is_internet_use": None},
        {RESERVED_HOST_RULE: 1},
    ),
    # Requests without a host and from no web tool, in the order of the default registry rule.
    (
        "pip install -e .",
        _request(
            _command(_program("pip", "install")),
            UnknownNetworkRequestTarget(UnknownNetworkRequestTargetReason.LOCAL_PATH),
            PACKAGE_NAME,
            ContentSaved(None),
        ),
        {
            "category": NetworkRequestCategory.PACKAGE,
            "package_registry": "pypi",
            "target": "",
            "unknown_target_reason": UnknownNetworkRequestTargetReason.LOCAL_PATH,
            "is_internet_use": None,
            "request_measure_bound": UPPER_ONLY,
        },
        {DEFAULT_REGISTRY_RULE: 1},
    ),
    (
        "pip install $PKG",
        _request(
            _command(_program("pip", "install")),
            UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.VALUE_SET_AT_RUN_TIME
            ),
            PACKAGE_NAME,
            ContentSaved(None),
        ),
        {
            "category": NetworkRequestCategory.PACKAGE,
            "target": "",
            "unknown_target_reason": UnknownNetworkRequestTargetReason.VALUE_SET_AT_RUN_TIME,
            "is_internet_use": True,
        },
        {DEFAULT_REGISTRY_RULE: 1, DOTTED_HOST_RULE: 1},
    ),
    (
        "npm ci",
        _request(
            _command(_program("npm", "ci")),
            UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.NAMED_IN_FILE
            ),
            PACKAGE_NAME,
            ContentSaved(None),
        ),
        {
            "package_registry": "npm",
            "unknown_target_reason": UnknownNetworkRequestTargetReason.NAMED_IN_FILE,
            "is_internet_use": True,
            "request_measure_bound": LOWER_AND_UPPER,
        },
        {DEFAULT_REGISTRY_RULE: 1, DOTTED_HOST_RULE: 1},
    ),
    (
        "apt-get update",
        _request(
            _command(_program("apt-get", "update")),
            None,
            PACKAGE_NAME,
            ContentSaved(None),
        ),
        {
            "target": "",
            "unknown_target_reason": None,
            "package_registry": "apt",
            "is_internet_use": True,
        },
        {DEFAULT_REGISTRY_RULE: 1, DOTTED_HOST_RULE: 2},
    ),
    (
        "conda install numpy without a row",
        _request(
            _command(_program("conda", "install")),
            "numpy",
            PACKAGE_NAME,
            ContentSaved(None),
        ),
        {"package_registry": "unknown", "is_internet_use": None},
        {DEFAULT_REGISTRY_RULE: 1},
    ),
    (
        "npx tsc, uncertain",
        NPX_TSC,
        {
            "is_internet_use": True,
            "request_certainty": NetworkRequestCertainty.UNCERTAIN,
            "request_uncertainty_reason": NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING,
            "request_measure_bound": UPPER_ONLY,
        },
        {DEFAULT_REGISTRY_RULE: 1, DOTTED_HOST_RULE: 1},
    ),
    (
        "git push origin main, which the door is not asked about",
        _request(
            _command(_program("git", "push")),
            None,
            REPOSITORY_URL,
            NoContentRequested(),
        ),
        {
            "category": NetworkRequestCategory.OTHER_WEB,
            "received_content_destination": "not_requested",
            "is_internet_use": None,
            "package_registry": "",
        },
        {DEFAULT_REGISTRY_RULE: 1, REPOSITORY_REQUEST_FOR_NO_CONTENT_RULE: 1},
    ),
    (
        "code that builds its URL",
        _request(
            FromCode(0, ArgumentText(0), CodeLanguage.PYTHON, "requests.get"),
            UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.BUILT_IN_CODE
            ),
            URL,
            UnknownReceivedContentDestination(),
        ),
        {"is_internet_use": None, "category": NetworkRequestCategory.OTHER_WEB},
        {DEFAULT_REGISTRY_RULE: 1},
    ),
]


@pytest.mark.parametrize(
    ("case", "network_request", "columns", "judgment_rule_uses"),
    INTERNET_USE_CASES,
    ids=[case for case, *_ in INTERNET_USE_CASES],
)
def test_internet_use_takes_the_first_condition_that_fits_and_counts_each_rule_it_asks(
    case: str,
    network_request: NetworkRequest,
    columns: dict[str, object],
    judgment_rule_uses: dict[str, int],
    knowledge: ExportKnowledge,
):
    network_request_row, judgment_rule_use_counts = _exported(
        _result(network_request), knowledge
    )

    assert _columns_of(network_request_row, list(columns)) == columns
    assert judgment_rule_use_counts == Counter(judgment_rule_uses)


@pytest.mark.parametrize(
    (
        "network_request",
        "is_internet_use",
        "request_measure_bound",
        "judgment_rule_uses",
    ),
    [
        # A default registry inside the task environment.
        (PIP_INSTALL_REQUESTS, False, NEITHER, {DEFAULT_REGISTRY_RULE: 1}),
        # A default registry host without a dot.
        (
            _request(
                _command(_program("pip", "download")),
                "requests",
                PACKAGE_NAME,
                ContentSaved(None),
            ),
            None,
            UPPER_ONLY,
            {DEFAULT_REGISTRY_RULE: 1, UNCLASSIFIED_HOST_RULE: 1},
        ),
    ],
)
def test_default_registry_hosts_are_read_like_hosts_that_the_words_name(
    network_request: NetworkRequest,
    is_internet_use: bool | None,
    request_measure_bound: MeasureBound,
    judgment_rule_uses: dict[str, int],
    internal_catalogs_dir: Path,
):
    network_request_row, judgment_rule_use_counts = _exported(
        _result(network_request),
        ExportKnowledge(catalogs_dir=internal_catalogs_dir),
    )

    assert network_request_row.is_internet_use is is_internet_use
    assert network_request_row.request_measure_bound == request_measure_bound
    assert network_request_row.package_registry == "devpi"
    assert judgment_rule_use_counts == Counter(judgment_rule_uses)


def test_a_host_that_the_words_name_decides_a_package_request_instead_of_the_default_registry(
    knowledge: ExportKnowledge,
):
    pip_install_from_internal_index = _request(
        _command(_program("pip", "install")),
        "x",
        PACKAGE_NAME,
        ContentSaved(None),
        "mirror.internal",
    )

    network_request_row, judgment_rule_use_counts = _exported(
        _result(pip_install_from_internal_index), knowledge
    )

    assert _columns_of(
        network_request_row,
        [
            "category",
            "host_scope",
            "host_service",
            "is_internet_use",
            "request_measure_bound",
            "received_measure_bound",
            "package_registry",
        ],
    ) == {
        "category": NetworkRequestCategory.PACKAGE,
        "host_scope": "local",
        "host_service": "not_public",
        "is_internet_use": False,
        "request_measure_bound": NEITHER,
        "received_measure_bound": NEITHER,
        "package_registry": "pypi",
    }
    assert judgment_rule_use_counts == Counter()


# (judgment rule, the answer it is patched to, request, internet use with that answer)
OTHER_INTERNET_USE_ANSWER_CASES = [
    (WEB_TOOL_WITHOUT_HOST_RULE, False, WEB_SEARCH, None),
    (DEFAULT_REGISTRY_RULE, (), PIP_INSTALL_REQUESTS, None),
    (UNCLASSIFIED_HOST_RULE, False, CURL_DB, False),
    (RESERVED_HOST_RULE, False, CURL_EXAMPLE, False),
    (LOCAL_HOST_OF_WEB_TOOL_RULE, False, WEB_FETCH_LOCALHOST, False),
]


@pytest.mark.parametrize(
    ("rule_name", "answer", "network_request", "is_internet_use"),
    OTHER_INTERNET_USE_ANSWER_CASES,
    ids=[rule_name for rule_name, *_ in OTHER_INTERNET_USE_ANSWER_CASES],
)
def test_internet_use_follows_the_other_answer_of_its_judgment_rule(
    rule_name: str,
    answer: object,
    network_request: NetworkRequest,
    is_internet_use: bool | None,
    knowledge: ExportKnowledge,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        _export_network_request_row, rule_name, lambda *_, use_counts: answer
    )

    network_request_row, _ = _exported(_result(network_request), knowledge)

    assert network_request_row.is_internet_use is is_internet_use


# (case, request, sender, unknown inputs of the door after the export)
SENDER_CASES = [
    ("command", CURL_A_ORG, NetworkRequestSender.TASK_ENVIRONMENT, {}),
    (
        "code",
        _request(
            FromCode(0, ArgumentText(0), CodeLanguage.PYTHON, "requests.get"),
            "https://a.org/x",
            URL,
            UnknownReceivedContentDestination(),
            "a.org",
        ),
        NetworkRequestSender.TASK_ENVIRONMENT,
        {},
    ),
    (
        "web tool of the provider server",
        WEB_SEARCH,
        NetworkRequestSender.PROVIDER_SERVER,
        {},
    ),
    (
        "web tool of the harness process",
        WEB_FETCH_LOCALHOST,
        NetworkRequestSender.HARNESS_PROCESS,
        {},
    ),
    (
        "web tool without a row",
        _request(
            _web_tool("claude-code", "Fetch"),
            "https://a.org/p",
            URL,
            ContentShownInResult(),
            "a.org",
        ),
        NetworkRequestSender.UNKNOWN,
        {(HARNESS_WEB_TOOLS_CSV, ("claude-code", "Fetch")): 1},
    ),
]


@pytest.mark.parametrize(
    ("case", "network_request", "sender", "unknown_inputs"),
    SENDER_CASES,
    ids=[case for case, *_ in SENDER_CASES],
)
def test_sender_is_the_task_environment_for_commands_and_code_and_the_door_answer_for_web_tools(
    case: str,
    network_request: NetworkRequest,
    sender: NetworkRequestSender,
    unknown_inputs: dict[tuple[str, tuple[str, ...]], int],
    knowledge: ExportKnowledge,
):
    network_request_row, _ = _exported(_result(network_request), knowledge)

    assert network_request_row.sender == sender
    assert {
        key: count
        for key, count in knowledge.uses.unknown_input_counts.items()
        if key[0] == HARNESS_WEB_TOOLS_CSV
    } == unknown_inputs


def test_door_is_asked_about_public_hosts_and_package_commands_only(
    knowledge: ExportKnowledge,
):
    two_hosts = _request(
        _command(_program("curl")),
        "http://10.0.0.5/x",
        URL,
        ContentShownInResult(),
        "10.0.0.5",
        "a.org",
        "db",
    )
    conda_install = _request(
        _command(_program("conda", "install")),
        "numpy",
        PACKAGE_NAME,
        ContentSaved(None),
    )

    for network_request in (two_hosts, conda_install, PIP_INSTALL_REQUESTS):
        _exported(_result(network_request), knowledge)

    assert knowledge.uses.unknown_input_counts == Counter(
        {
            (PUBLIC_HOSTS_CSV, ("a.org",)): 1,
            (PROGRAM_PACKAGE_REGISTRIES_CSV, ("conda", "install")): 1,
        }
    )
    assert knowledge.uses.row_use_counts == Counter(
        {(PROGRAM_PACKAGE_REGISTRIES_CSV, ("pip", "install")): 1}
    )


# (case, request, expected columns, judgment rules counted with their uses)
COLUMN_CASES: list[tuple[str, NetworkRequest, dict[str, object], dict[str, int]]] = [
    (
        "pip install git+https://github.com/a/b",
        _request(
            _command(_program("pip", "install")),
            "git+https://github.com/a/b",
            REPOSITORY_URL,
            ContentSaved(None),
            "github.com",
        ),
        {
            "category": NetworkRequestCategory.FETCHED_FILE,
            "host_scope": "public",
            "host_service": "code_hosting",
            "is_internet_use": True,
            "package_registry": "",
        },
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "ping pypi.org",
        _request(
            _command(_program("ping")),
            "pypi.org",
            HOST,
            NoContentRequested(),
            "pypi.org",
        ),
        {
            "category": NetworkRequestCategory.CONNECTIVITY_CHECK,
            "host_service": "package_registry",
            "is_internet_use": True,
            "received_content_destination": "not_requested",
            "result_view": NetworkRequestResultView.RECEIVED,
        },
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "curl https://github.com/a/b/README.md",
        _curl("https://github.com/a/b/README.md", "github.com"),
        {"category": NetworkRequestCategory.PAGE_READ},
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "wget https://pypi.org/packages/x.whl",
        _request(
            _command(_program("wget")),
            "https://pypi.org/packages/x.whl",
            URL,
            ContentSaved("x.whl"),
            "pypi.org",
        ),
        {
            "category": NetworkRequestCategory.FETCHED_FILE,
            "host_service": "package_registry",
            "package_registry": "",
            "received_content_destination": "saved",
        },
        {DOTTED_HOST_RULE: 1, SAVED_FROM_PACKAGE_REGISTRY_RULE: 1},
    ),
    (
        "curl -O https://huggingface.co/m/model.bin",
        _curl(
            "https://huggingface.co/m/model.bin", "huggingface.co", ContentSaved(None)
        ),
        {"category": NetworkRequestCategory.FETCHED_FILE, "host_service": "model_hub"},
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "curl -s -o /dev/null https://a.org/x",
        _curl("https://a.org/x", "a.org", ContentDiscarded()),
        {
            "category": NetworkRequestCategory.OTHER_WEB,
            "received_content_destination": "discarded",
        },
        {DOTTED_HOST_RULE: 1, DISCARDED_CONTENT_RULE: 1},
    ),
    (
        "curl 'https://duckduckgo.com/html?q=x'",
        _curl("https://duckduckgo.com/html?q=x", "duckduckgo.com"),
        {
            "category": NetworkRequestCategory.OTHER_WEB,
            "target": "https://duckduckgo.com/html?q=REDACTED",
        },
        {DOTTED_HOST_RULE: 1, SHOWN_FROM_SEARCH_ENGINE_RULE: 1, CREDENTIAL_RULE: 1},
    ),
    (
        "requests.get in Python code",
        _request(
            FromCode(0, ArgumentText(0), CodeLanguage.PYTHON, "requests.get"),
            "https://a.org/x",
            URL,
            UnknownReceivedContentDestination(),
            "a.org",
        ),
        {
            "source_kind": NetworkRequestSourceKind.CODE,
            "category": NetworkRequestCategory.OTHER_WEB,
            "made_by": "python requests.get",
            "source": "code of command 0",
            "received_content_destination": "unknown",
        },
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "socket.create_connection in code",
        _request(
            FromCode(
                0, ArgumentText(0), CodeLanguage.PYTHON, "socket.create_connection"
            ),
            "api",
            HOST,
            UnknownReceivedContentDestination(),
            "api",
        ),
        {
            "category": NetworkRequestCategory.OTHER_WEB,
            "host_scope": "unknown_single_label",
            "is_internet_use": None,
        },
        {HOST_TARGET_RULE: 1, UNCLASSIFIED_HOST_RULE: 1},
    ),
    (
        "subprocess.run of pip in code",
        _request(
            FromCode(0, ArgumentText(0), CodeLanguage.PYTHON, "subprocess.run"),
            UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.BUILT_IN_CODE
            ),
            UnknownNetworkRequestTargetKind(),
            UnknownReceivedContentDestination(),
            uncertainty_reason=NetworkRequestUncertaintyReason.PROGRAM_RUN_BY_CODE,
        ),
        {
            "category": NetworkRequestCategory.UNKNOWN,
            "target": "",
            "unknown_target_reason": UnknownNetworkRequestTargetReason.BUILT_IN_CODE,
            "target_kind": None,
            "package_registry": "",
            "request_measure_bound": UPPER_ONLY,
        },
        {DEFAULT_REGISTRY_RULE: 1},
    ),
    (
        "mytool https://a.org/x, uncertain",
        MYTOOL_A_ORG,
        {
            "made_by": "mytool",
            "request_certainty": NetworkRequestCertainty.UNCERTAIN,
            "request_uncertainty_reason": NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM,
            "request_measure_bound": UPPER_ONLY,
        },
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "curl https://files.acme.org/x",
        _curl("https://files.acme.org/x", "files.acme.org"),
        {"host_scope": "public", "target_kind": URL},
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "uv pip install requests, without a row",
        _request(
            _command(_program("uv", "pip", "install")),
            "requests",
            PACKAGE_NAME,
            ContentSaved(None),
        ),
        {"made_by": "uv pip install", "package_registry": "unknown"},
        {DEFAULT_REGISTRY_RULE: 1},
    ),
    (
        "npm ci from the index of a public registry host",
        _request(
            _command(_program("npm", "ci")),
            UnknownNetworkRequestTarget(
                UnknownNetworkRequestTargetReason.NAMED_IN_FILE
            ),
            PACKAGE_NAME,
            ContentSaved(None),
            "pypi.org",
        ),
        {"package_registry": "pypi", "is_internet_use": True},
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "page of a web step of a Codex script",
        _request(
            _web_tool("codex", "exec", step_index=1),
            "https://a.org/p",
            URL,
            ContentShownInResult(),
            "a.org",
        ),
        {
            "source_kind": NetworkRequestSourceKind.WEB_TOOL,
            "sender": NetworkRequestSender.PROVIDER_SERVER,
            "made_by": "exec",
            "source": "web tool of script step 1",
        },
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "code with a call that has no row",
        _request(
            FromCode(0, ArgumentText(0), CodeLanguage.JAVASCRIPT, UnknownCodeCall()),
            "https://a.org/x",
            URL,
            UnknownReceivedContentDestination(),
            "a.org",
            uncertainty_reason=NetworkRequestUncertaintyReason.UNKNOWN_CODE_CALL,
        ),
        {"made_by": "javascript"},
        {DOTTED_HOST_RULE: 1},
    ),
    (
        "mytool add x, a package name of a program without facts",
        _request(
            _command(UnknownProgramInvocation("mytool", ("add", "x"))),
            "x",
            PACKAGE_NAME,
            UnknownReceivedContentDestination(),
            uncertainty_reason=NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM,
        ),
        {"made_by": "mytool", "package_registry": "unknown", "is_internet_use": None},
        {DEFAULT_REGISTRY_RULE: 1},
    ),
]


@pytest.mark.parametrize(
    ("case", "network_request", "columns", "judgment_rule_uses"),
    COLUMN_CASES,
    ids=[case for case, *_ in COLUMN_CASES],
)
def test_columns_of_made_up_requests(
    case: str,
    network_request: NetworkRequest,
    columns: dict[str, object],
    judgment_rule_uses: dict[str, int],
    knowledge: ExportKnowledge,
):
    network_request_row, judgment_rule_use_counts = _exported(
        _result(network_request), knowledge
    )

    assert _columns_of(network_request_row, list(columns)) == columns
    assert judgment_rule_use_counts == Counter(judgment_rule_uses)


# (case, level, stop reason, level certainty, evidence, result view, request bound, received bound, bound rule counted)
RESULT_CASES: list[
    tuple[
        str,
        NetworkRequestResultLevel,
        NetworkRequestResultStopReason | None,
        NetworkRequestResultCertainty,
        tuple[NetworkRequestResultEvidence, ...],
        NetworkRequestResultView,
        MeasureBound,
        MeasureBound,
        str | None,
    ]
] = [
    # One result for each situation of a request, from received content to a request that did not need to be sent.
    ("received", RECEIVED, None, CONFIRMED, (EXIT_CODE_0,), NetworkRequestResultView.RECEIVED, LOWER_AND_UPPER, LOWER_AND_UPPER, None),
    ("refused by the server", REACHED, FAILED, CONFIRMED, (HttpStatusEvidence(ToolCallKey("t1", "main", 1, 0), 404),), NetworkRequestResultView.NOT_RECEIVED, LOWER_AND_UPPER, NEITHER, None),
    ("server not reached", EXECUTED, FAILED, CONFIRMED, (EXIT_CODE_0,), NetworkRequestResultView.NOT_RECEIVED, LOWER_AND_UPPER, NEITHER, None),
    ("did not run", ATTEMPTED, FAILED, CONFIRMED, (PROGRAM_MISSING_LINE,), NetworkRequestResultView.NOT_RECEIVED, LOWER_AND_UPPER, NEITHER, None),
    ("server answered, content not visible", REACHED, NOT_VISIBLE, CONFIRMED, (EXIT_CODE_0,), NetworkRequestResultView.UNKNOWN, LOWER_AND_UPPER, UPPER_ONLY, None),
    ("ran, output not visible", EXECUTED, NOT_VISIBLE, CONFIRMED, (EXIT_CODE_0,), NetworkRequestResultView.UNKNOWN, LOWER_AND_UPPER, UPPER_ONLY, None),
    ("not known to have run", ATTEMPTED, NOT_VISIBLE, CONFIRMED, (), NetworkRequestResultView.UNKNOWN, LOWER_AND_UPPER, UPPER_ONLY, None),
    ("not needed", EXECUTED, NOT_NEEDED, CONFIRMED, (EXIT_CODE_0,), NetworkRequestResultView.NOT_NEEDED, NEITHER, NEITHER, None),
    # Assumed results.
    ("assumed receipt", RECEIVED, None, ASSUMED, (EXIT_CODE_0,), NetworkRequestResultView.RECEIVED, LOWER_AND_UPPER, UPPER_ONLY, None),
    ("assumed failure", EXECUTED, FAILED, ASSUMED, (EXIT_CODE_0,), NetworkRequestResultView.NOT_RECEIVED, LOWER_AND_UPPER, UPPER_ONLY, ASSUMED_FAILURE_RULE),
    ("failure on a shared error line alone", EXECUTED, FAILED, ASSUMED, (SHARED_ERROR_LINE,), NetworkRequestResultView.NOT_RECEIVED, LOWER_AND_UPPER, UPPER_ONLY, ASSUMED_FAILURE_RULE),
    ("assumed receipt of a web fetch", RECEIVED, None, ASSUMED, (HttpStatusEvidence(ToolCallKey("t1", "main", 1, 0), 200), ShownContentEvidence(ToolCallKey("t1", "main", 1, 0))), NetworkRequestResultView.RECEIVED, LOWER_AND_UPPER, UPPER_ONLY, None),
    ("assumed not needed", EXECUTED, NOT_NEEDED, ASSUMED, (SHARED_ALREADY_PRESENT_LINE,), NetworkRequestResultView.NOT_NEEDED, UPPER_ONLY, UPPER_ONLY, ASSUMED_NOT_NEEDED_RULE),
]  # fmt: skip


@pytest.mark.parametrize(
    (
        "case",
        "level",
        "stop_reason",
        "level_certainty",
        "evidence",
        "result_view",
        "request_measure_bound",
        "received_measure_bound",
        "rule_name",
    ),
    RESULT_CASES,
    ids=[case for case, *_ in RESULT_CASES],
)
def test_result_view_and_bounds_of_a_confirmed_request_that_is_internet_use(
    case: str,
    level: NetworkRequestResultLevel,
    stop_reason: NetworkRequestResultStopReason | None,
    level_certainty: NetworkRequestResultCertainty,
    evidence: tuple[NetworkRequestResultEvidence, ...],
    result_view: NetworkRequestResultView,
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
    rule_name: str | None,
    knowledge: ExportKnowledge,
):
    network_request_row, judgment_rule_use_counts = _exported(
        _result(CURL_A_ORG, level, stop_reason, level_certainty, evidence), knowledge
    )

    assert (
        network_request_row.result_view,
        network_request_row.request_measure_bound,
        network_request_row.received_measure_bound,
    ) == (result_view, request_measure_bound, received_measure_bound)
    assert (
        network_request_row.level,
        network_request_row.stop_reason,
        network_request_row.level_certainty,
    ) == (level, stop_reason, level_certainty)
    expected_counts = Counter({DOTTED_HOST_RULE: 1})
    if rule_name is not None:
        expected_counts[rule_name] += 1
    assert judgment_rule_use_counts == expected_counts


# (case, result, request bound, received bound, judgment rules counted with their uses)
BOUND_CASES: list[
    tuple[str, NetworkRequestResult, MeasureBound, MeasureBound, dict[str, int]]
] = [
    (
        "ping that reached its host",
        _result(_request(_command(_program("ping")), "a.org", HOST, NoContentRequested(), "a.org")),
        LOWER_AND_UPPER,
        LOWER_AND_UPPER,
        {DOTTED_HOST_RULE: 1},
    ),
    ("uncertain request received", _result(NPX_TSC), UPPER_ONLY, UPPER_ONLY, {DEFAULT_REGISTRY_RULE: 1, DOTTED_HOST_RULE: 1}),
    ("internet use not known, received", _result(CURL_DB), UPPER_ONLY, UPPER_ONLY, {UNCLASSIFIED_HOST_RULE: 1}),
    ("not internet use, received", _result(CURL_LOCALHOST), NEITHER, NEITHER, {}),
    # Requests that two conditions fit, where the first wins.
    (
        "not internet use, assumed not needed",
        _result(CURL_LOCALHOST, EXECUTED, NOT_NEEDED, ASSUMED),
        NEITHER,
        NEITHER,
        {},
    ),
    (
        "internet use not known, confirmed not needed",
        _result(CURL_DB, EXECUTED, NOT_NEEDED, CONFIRMED),
        NEITHER,
        NEITHER,
        {UNCLASSIFIED_HOST_RULE: 1},
    ),
    (
        "internet use not known, assumed not needed",
        _result(CURL_DB, EXECUTED, NOT_NEEDED, ASSUMED),
        UPPER_ONLY,
        UPPER_ONLY,
        {UNCLASSIFIED_HOST_RULE: 1, ASSUMED_NOT_NEEDED_RULE: 1},
    ),
    (
        "not internet use, assumed failure",
        _result(CURL_LOCALHOST, EXECUTED, FAILED, ASSUMED),
        NEITHER,
        NEITHER,
        {},
    ),
    (
        "uncertain request lifted to confirmed by its own output line",
        _result(
            NPX_TSC,
            REACHED,
            FAILED,
            CONFIRMED,
            (OutputLineEvidence(ToolCallKey("t1", "main", 1, 0), 3, None, OutputLineKind.NOT_FOUND, False),),
            NetworkRequestCertainty.CONFIRMED,
        ),
        LOWER_AND_UPPER,
        NEITHER,
        {DEFAULT_REGISTRY_RULE: 1, DOTTED_HOST_RULE: 1},
    ),
]  # fmt: skip


@pytest.mark.parametrize(
    (
        "case",
        "network_request_result",
        "request_measure_bound",
        "received_measure_bound",
        "judgment_rule_uses",
    ),
    BOUND_CASES,
    ids=[case for case, *_ in BOUND_CASES],
)
def test_bounds_take_the_first_condition_that_fits(
    case: str,
    network_request_result: NetworkRequestResult,
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
    judgment_rule_uses: dict[str, int],
    knowledge: ExportKnowledge,
):
    network_request_row, judgment_rule_use_counts = _exported(
        network_request_result, knowledge
    )

    assert (
        network_request_row.request_measure_bound,
        network_request_row.received_measure_bound,
    ) == (request_measure_bound, received_measure_bound)
    assert judgment_rule_use_counts == Counter(judgment_rule_uses)


def test_request_lifted_to_confirmed_keeps_no_uncertainty_reason(
    knowledge: ExportKnowledge,
):
    network_request_row, _ = _exported(BOUND_CASES[-1][1], knowledge)

    assert network_request_row.request_certainty == NetworkRequestCertainty.CONFIRMED
    assert network_request_row.request_uncertainty_reason is None


@pytest.mark.parametrize(
    ("rule_name", "network_request_result", "request_measure_bound", "received_measure_bound"),
    [
        (ASSUMED_NOT_NEEDED_RULE, _result(CURL_A_ORG, EXECUTED, NOT_NEEDED, ASSUMED), NEITHER, NEITHER),
        (ASSUMED_FAILURE_RULE, _result(CURL_A_ORG, EXECUTED, FAILED, ASSUMED), LOWER_AND_UPPER, NEITHER),
    ],
)  # fmt: skip
def test_bounds_follow_the_other_answer_of_their_judgment_rule(
    rule_name: str,
    network_request_result: NetworkRequestResult,
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
    knowledge: ExportKnowledge,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        _export_network_request_row, rule_name, lambda *_, use_counts: False
    )

    network_request_row, _ = _exported(network_request_result, knowledge)

    assert (
        network_request_row.request_measure_bound,
        network_request_row.received_measure_bound,
    ) == (request_measure_bound, received_measure_bound)


def test_two_requests_of_one_call_keep_its_key_and_their_index(
    knowledge: ExportKnowledge,
):
    second_request = NetworkRequest(
        tool_call_key=ToolCallKey("t9", "main/sub0", 7, 3),
        index_in_tool_call=1,
        source=_command(_program("curl")),
        target="https://a.org/y",
        target_kind=URL,
        host_names=("a.org",),
        received_content_destination=ContentShownInResult(),
        certainty=NetworkRequestCertainty.CONFIRMED,
        uncertainty_reason=None,
    )

    network_request_row, _ = _exported(_result(second_request), knowledge)

    assert _columns_of(
        network_request_row,
        ["trial_id", "trajectory_id", "step_id", "call_index", "request_index"],
    ) == {
        "trial_id": "t9",
        "trajectory_id": "main/sub0",
        "step_id": 7,
        "call_index": 3,
        "request_index": 1,
    }


@pytest.mark.parametrize(
    ("ran_text_source", "source"),
    [
        (CallCommandText(), "command 2"),
        (ScriptStepText(1), "command 2 of script step 1"),
        (PollInputText(None, ToolCallKey("t1", "main", 4, 0)), "command 2 typed by a poll"),
        (PollInputText(1, None), "command 2 typed by a poll of script step 1"),
        (FileText(0, "fetch.sh", ToolCallKey("t1", "main", 11, 0)), "command 2 in fetch.sh written by call 11.0"),
        (FileText(0, None, ToolCallKey("t1", "main", 11, 0)), "command 2 in the file of command 0 written by call 11.0"),
        (FileTextWithoutKnownWriter(0, "setup.sh"), "command 2 in setup.sh that no call wrote"),
        (FileTextWithoutKnownWriter(1, None), "command 2 in the file of command 1 that no call wrote"),
        (StdinText(0), "command 2 in the stdin of command 0"),
        (ArgumentText(0), "command 2 in an argument of command 0"),
        # A path is no credential place.
        (FileText(0, "/home/u/fetch.sh", ToolCallKey("t1", "main", 11, 0)), "command 2 in /home/u/fetch.sh written by call 11.0"),
    ],
)  # fmt: skip
def test_source_of_a_command_says_where_its_text_is(
    ran_text_source: RanTextSource, source: str, knowledge: ExportKnowledge
):
    network_request = _request(
        _command(_program("curl"), ran_text_source),
        "https://a.org/x",
        URL,
        ContentShownInResult(),
        "a.org",
    )

    network_request_row, _ = _exported(_result(network_request), knowledge)

    assert network_request_row.source_kind == NetworkRequestSourceKind.COMMAND
    assert network_request_row.source == source


def test_source_of_code_typed_by_a_poll_names_no_command(knowledge: ExportKnowledge):
    network_request = _request(
        FromCode(None, PollInputText(None, None), CodeLanguage.PYTHON, "requests.get"),
        "https://a.org/x",
        URL,
        UnknownReceivedContentDestination(),
        "a.org",
    )

    network_request_row, _ = _exported(_result(network_request), knowledge)

    assert network_request_row.source == "code typed by a poll"


@pytest.mark.parametrize(
    ("received_content_destination", "text"),
    [
        (ContentSaved("a.tgz"), "saved"),
        (ContentShownInResult(), "shown"),
        (ContentPipedToCommand(1, OutputVisibility.WHOLE), "piped_whole"),
        (ContentPipedToCommand(1, OutputVisibility.PARTIAL), "piped_partial"),
        (ContentPipedToCommand(1, OutputVisibility.NONE), "piped_none"),
        (ContentPipedToCommand(1, OutputVisibility.UNKNOWN), "piped_unknown"),
    ],
)
def test_received_content_destination_is_written_as_a_word(
    received_content_destination: ReceivedContentDestination,
    text: str,
    knowledge: ExportKnowledge,
):
    network_request_row, _ = _exported(
        _result(_curl("https://a.org/x", "a.org", received_content_destination)),
        knowledge,
    )

    assert network_request_row.received_content_destination == text


def test_evidence_is_one_short_text_per_piece_without_the_text_of_output_lines(
    knowledge: ExportKnowledge,
):
    evidence = (
        OutputLineEvidence(ToolCallKey("t1", "main", 12, 0), 0, None, OutputLineKind.NAME_NOT_RESOLVED, False),
        OutputLineEvidence(ToolCallKey("t1", "main", 12, 0), 1, None, OutputLineKind.CONNECTION_FAILED, True),
        OutputLineEvidence(ToolCallKey("t1", "main", 12, 1), 4, 2, OutputLineKind.DOWNLOADED, True),
        ExitCodeEvidence(ToolCallKey("t1", "main", 3, 0), 0, True),
        ExitCodeEvidence(ToolCallKey("t1", "main", 3, 0), 6, False),
        HttpStatusEvidence(ToolCallKey("t1", "main", 5, 0), 404),
        ExecutionStatusEvidence(ToolCallKey("t1", "main", 3, 0), ExecutionStatus.NOT_RUN, False),
        ExecutionStatusEvidence(ToolCallKey("t1", "main", 3, 0), ExecutionStatus.FINISHED, True),
        FileUseEvidence(FileUse(ToolCallKey("t1", "main", 4, 0), 1, FileUseKind.USES_CONTENT, False)),
        FileUseEvidence(FileUse(ToolCallKey("t1", "main", 4, 1), None, FileUseKind.SHOWS_CONTENT, True)),
        ShownContentEvidence(ToolCallKey("t1", "main", 5, 0)),
    )  # fmt: skip

    network_request_row, _ = _exported(
        _result(CURL_A_ORG, EXECUTED, FAILED, CONFIRMED, evidence), knowledge
    )

    assert network_request_row.evidence.split("; ") == [
        "line 0 of call 12.0, name_not_resolved",
        "line 1 of call 12.0, connection_failed, shared",
        "line 4 of call 12.1, line 2 of its output string, downloaded, shared",
        "exit code 0 of call 3.0, shared",
        "exit code 6 of call 3.0",
        "http status 404 of call 5.0",
        "execution status not_run of call 3.0",
        "execution status finished of call 3.0, shared",
        "file use uses_content by command 1 of call 4.0",
        "file use shows_content by call 4.1, fits several written files",
        "content shown in call 5.0",
    ]


# (column, request that puts a made-up credential into it, the redacted column)
REDACTED_COLUMN_CASES = [
    (
        "source",
        _request(
            _command(_program("curl"), FileText(0, "https://u:pw@a.org/s.sh", ToolCallKey("t1", "main", 2, 0))),
            "https://a.org/x",
            URL,
            ContentShownInResult(),
            "a.org",
        ),
        "command 2 in https://REDACTED@a.org/s.sh written by call 2.0",
    ),
    ("made_by", _request(_command(UnknownProgramInvocation("u:pw@tool", ())), None, URL, ContentShownInResult(), "a.org", uncertainty_reason=NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM), "REDACTED@tool"),
    ("target", _curl("user:pw@a.org/x", "a.org"), "REDACTED@a.org/x"),
    ("host_names", _curl("https://a.org/x", "u:pw@a.org"), "REDACTED@a.org"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("column_name", "network_request", "redacted_text"),
    REDACTED_COLUMN_CASES,
    ids=[column_name for column_name, *_ in REDACTED_COLUMN_CASES],
)
def test_each_column_that_holds_text_of_the_trajectory_is_redacted(
    column_name: str,
    network_request: NetworkRequest,
    redacted_text: str,
    knowledge: ExportKnowledge,
):
    network_request_row, _ = _exported(_result(network_request), knowledge)

    assert getattr(network_request_row, column_name) == redacted_text
