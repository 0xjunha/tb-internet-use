"""Tests for knowledge/network_request_result_knowledge.py, with made-up output lines read against the declared output line patterns."""

import time
from collections import Counter

import pytest

from tb_internet_use.knowledge.declarations.network_request_result.output_line_patterns import (
    PROGRAM_OUTPUT_LINE_PATTERNS,
)
from tb_internet_use.knowledge.network_request_result_knowledge import (
    OUTPUT_LINE_PATTERNS_DECLARATIONS,
    NetworkRequestResultKnowledge,
)
from tb_internet_use.network_request_result.model import (
    OutputLineKind,
    OutputLineMeaning,
    PrintingProgram,
    UnknownOutputLineMeaning,
)

K = OutputLineKind
P = PrintingProgram

# The printing programs of a pattern and whether other programs print its line too.
_ANY = (frozenset[PrintingProgram](), True)
_HEADERS = (frozenset({P.HTTP_HEADERS, P.GIT}), True)
_DOWNLOADS = (frozenset({P.PIP, P.UV, P.PLAYWRIGHT, P.GIT, P.CODE}), True)


def _only(program: PrintingProgram) -> tuple[frozenset[PrintingProgram], bool]:
    return frozenset({program}), False


def _also(*programs: PrintingProgram) -> tuple[frozenset[PrintingProgram], bool]:
    return frozenset(programs), True


# (made-up line, the pattern that must match it first, kind, printing programs, the texts and status code the line holds)
EXAMPLE_LINES: list[
    tuple[str, str, OutputLineKind, tuple[frozenset[PrintingProgram], bool], dict]
] = [
    (
        "bash: pip3: command not found",
        "program_missing",
        K.PROGRAM_MISSING,
        _ANY,
        {"missing_program_word": "pip3"},
    ),
    # Some programs print the line without a shell name before it.
    (
        "rg: command not found",
        "program_missing",
        K.PROGRAM_MISSING,
        _ANY,
        {"missing_program_word": "rg"},
    ),
    (
        "sh: pip: not found",
        "program_missing",
        K.PROGRAM_MISSING,
        _ANY,
        {"missing_program_word": "pip"},
    ),
    (
        "#5 0.1 /bin/sh: 1: pip: not found",
        "program_missing",
        K.PROGRAM_MISSING,
        _ANY,
        {"missing_program_word": "pip"},
    ),
    (
        "./run.sh: line 3: type: pip: not found",
        "program_missing",
        K.PROGRAM_MISSING,
        _ANY,
        {"missing_program_word": "pip"},
    ),
    (
        "/usr/bin/python3: No module named pip",
        "program_missing",
        K.PROGRAM_MISSING,
        _ANY,
        {"missing_program_word": "pip"},
    ),
    (
        "failed to run command 'cargo': No such file",
        "program_missing",
        K.PROGRAM_MISSING,
        _ANY,
        {"missing_program_word": "cargo"},
    ),
    # The word keeps its folder, as the line writes it.
    (
        "bash: /opt/tool/bin/x: No such file or directory",
        "program_missing",
        K.PROGRAM_MISSING,
        _ANY,
        {"missing_program_word": "/opt/tool/bin/x"},
    ),
    (
        "error: externally-managed-environment",
        "pip_externally_managed",
        K.REFUSED_LOCALLY,
        _only(P.PIP),
        {},
    ),
    (
        "hint: See PEP 668 for the detailed specification.",
        "pip_externally_managed",
        K.REFUSED_LOCALLY,
        _only(P.PIP),
        {},
    ),
    (
        "[notice] A new release of pip is available: 23.0 -> 24.0",
        "pip_version_notice",
        K.VERSION_NOTICE,
        _only(P.PIP),
        {},
    ),
    (
        "[notice] To update, run: pip install --upgrade pip",
        "pip_version_notice",
        K.VERSION_NOTICE,
        _only(P.PIP),
        {},
    ),
    (
        "ProxyError('Cannot connect to proxy.')",
        "proxy_error",
        K.PROXY_REFUSED,
        _ANY,
        {},
    ),
    # It matches `connection_failure` too, which comes later.
    (
        "ProxyError: Connection refused",
        "proxy_error",
        K.PROXY_REFUSED,
        _ANY,
        {},
    ),
    # It matches `name_resolution_failure` too, which comes later and reads no host.
    (
        "curl: (6) Could not resolve host: pypi.org",
        "could_not_resolve_host",
        K.NAME_NOT_RESOLVED,
        _ANY,
        {"host_name_text": "pypi.org"},
    ),
    (
        "ssh: Could not resolve hostname git.example.org: Name or service not known",
        "name_resolution_failure",
        K.NAME_NOT_RESOLVED,
        _ANY,
        {},
    ),
    (
        "socket.gaierror: [Errno -3] Temporary failure in name resolution",
        "name_resolution_failure",
        K.NAME_NOT_RESOLVED,
        _ANY,
        {},
    ),
    (
        "nodename nor servname provided",
        "name_resolution_failure",
        K.NAME_NOT_RESOLVED,
        _ANY,
        {},
    ),
    (
        "No address associated with hostname",
        "name_resolution_failure",
        K.NAME_NOT_RESOLVED,
        _ANY,
        {},
    ),
    (
        "curl: (6) Couldn't resolve",
        "name_resolution_failure",
        K.NAME_NOT_RESOLVED,
        _ANY,
        {},
    ),
    (
        "curl: (60) SSL certificate problem: unable to get local issuer certificate",
        "tls_failure",
        K.TLS_FAILED,
        _ANY,
        {},
    ),
    (
        "ssl.SSLError: [SSL: CERTIFICATE_VERIFY_FAILED]",
        "tls_failure",
        K.TLS_FAILED,
        _ANY,
        {},
    ),
    # It matches `connection_lost` too, which comes later.
    (
        "SSLError: [Errno 104] Connection reset by peer",
        "tls_failure",
        K.TLS_FAILED,
        _ANY,
        {},
    ),
    (
        "curl: (35) OpenSSL SSL_connect: Connection reset by peer",
        "tls_failure",
        K.TLS_FAILED,
        _ANY,
        {},
    ),
    # It matches `connection_failure` too, which comes later and any program prints.
    (
        "curl: (7) Failed to connect to a.org port 443: Connection refused",
        "curl_failed_to_connect",
        K.CONNECTION_FAILED,
        _only(P.CURL),
        {"host_name_text": "a.org"},
    ),
    (
        "curl: (7) Failed to connect to 127.0.0.1 port 8000 after 0 ms",
        "curl_failed_to_connect",
        K.CONNECTION_FAILED,
        _only(P.CURL),
        {"host_name_text": "127.0.0.1"},
    ),
    # A host name without a dot is not read as a host, so `curl_failed_to_connect` does not match it.
    (
        "curl: (7) Failed to connect to localhost port 80",
        "connection_failure",
        K.CONNECTION_FAILED,
        _ANY,
        {},
    ),
    (
        "curl: (7) Connection refused",
        "connection_failure",
        K.CONNECTION_FAILED,
        _ANY,
        {},
    ),
    (
        "connect ECONNREFUSED 127.0.0.1:3000",
        "connection_failure",
        K.CONNECTION_FAILED,
        _ANY,
        {},
    ),
    (
        "connect: Connection timed out",
        "connection_failure",
        K.CONNECTION_FAILED,
        _ANY,
        {},
    ),
    (
        "requests.exceptions.ConnectTimeout: timed out",
        "connection_failure",
        K.CONNECTION_FAILED,
        _ANY,
        {},
    ),
    (
        "connect: No route to host",
        "connection_failure",
        K.CONNECTION_FAILED,
        _ANY,
        {},
    ),
    (
        "Error: connect ETIMEDOUT 10.0.0.1:443",
        "connection_failure",
        K.CONNECTION_FAILED,
        _ANY,
        {},
    ),
    (
        "Error: connect ENETUNREACH 10.0.0.1:443",
        "connection_failure",
        K.CONNECTION_FAILED,
        _ANY,
        {},
    ),
    (
        "[Errno 101] Network is unreachable",
        "connection_failure",
        K.CONNECTION_FAILED,
        _ANY,
        {},
    ),
    (
        "Error: read ECONNRESET",
        "connection_lost",
        K.CONNECTION_LOST,
        _ANY,
        {},
    ),
    (
        "ConnectionResetError: [Errno 104] Connection reset by peer",
        "connection_lost",
        K.CONNECTION_LOST,
        _ANY,
        {},
    ),
    (
        "ReadTimeoutError: Read timed out. (read timeout=15)",
        "connection_lost",
        K.CONNECTION_LOST,
        _ANY,
        {},
    ),
    (
        "curl: (52) Empty reply from server",
        "connection_lost",
        K.CONNECTION_LOST,
        _ANY,
        {},
    ),
    (
        "HTTP/2 404",
        "http_status_line",
        K.HTTP_STATUS,
        _HEADERS,
        {"status_code": 404},
    ),
    (
        "HTTP/1.1 200 OK",
        "http_status_line",
        K.HTTP_STATUS,
        _HEADERS,
        {"status_code": 200},
    ),
    (
        "2025-01-01 00:00:00 ERROR 404: Not Found.",
        "wget_http_status",
        K.HTTP_STATUS,
        _also(P.WGET),
        {"status_code": 404},
    ),
    (
        "HTTP request sent, awaiting response... 200 OK",
        "wget_http_status",
        K.HTTP_STATUS,
        _also(P.WGET),
        {"status_code": 200},
    ),
    (
        "curl: (22) The requested URL returned error: 403",
        "http_returned_error",
        K.HTTP_STATUS,
        _also(P.HTTP_FAILURE, P.GIT),
        {"status_code": 403},
    ),
    (
        "requests.exceptions.HTTPError: 503 Server Error: x",
        "http_error_status",
        K.HTTP_STATUS,
        _ANY,
        {"status_code": 503},
    ),
    (
        "urllib.error.HTTPError: HTTP Error 429: Too Many Requests",
        "http_error_status",
        K.HTTP_STATUS,
        _ANY,
        {"status_code": 429},
    ),
    (
        "npm ERR! code E404",
        "npm_http_error",
        K.HTTP_STATUS,
        _only(P.NPM),
        {"status_code": 404},
    ),
    (
        "npm error 404 Not Found - GET https://registry.npmjs.org/x",
        "npm_http_error",
        K.HTTP_STATUS,
        _only(P.NPM),
        {"status_code": 404},
    ),
    (
        "ERROR: No matching distribution found for nosuchpkg",
        "pip_no_matching_distribution",
        K.NOT_FOUND,
        _only(P.PIP),
        {"package_names_text": "nosuchpkg"},
    ),
    (
        "ERROR: Could not find a version that satisfies the requirement torch==9",
        "pip_no_matching_distribution",
        K.NOT_FOUND,
        _only(P.PIP),
        {"package_names_text": "torch==9"},
    ),
    (
        "E: Unable to locate package nosuch",
        "apt_unable_to_locate_package",
        K.NOT_FOUND,
        _only(P.APT),
        {"package_names_text": "nosuch"},
    ),
    (
        "E: Package 'python' has no installation candidate",
        "apt_unable_to_locate_package",
        K.NOT_FOUND,
        _only(P.APT),
        {"package_names_text": "python"},
    ),
    (
        "Requirement already satisfied: requests in /usr/lib",
        "pip_already_satisfied",
        K.ALREADY_PRESENT,
        _only(P.PIP),
        {"package_names_text": "requests"},
    ),
    (
        "Audited 3 packages in 2ms",
        "uv_audited",
        K.ALREADY_PRESENT,
        _only(P.UV),
        {},
    ),
    (
        "curl is already the newest version (7.88).",
        "apt_already_newest",
        K.ALREADY_PRESENT,
        _only(P.APT),
        {"package_names_text": "curl"},
    ),
    # playwright prints this before the download, which can still fail.
    (
        "Downloading Chromium 131.0 (playwright build v1148)",
        "downloading",
        K.DOWNLOAD_STARTED,
        _DOWNLOADS,
        {"package_names_text": "Chromium"},
    ),
    (
        "Chromium 131.0 (playwright build v1148) downloaded to /root/.cache",
        "playwright_downloaded",
        K.DOWNLOADED,
        _only(P.PLAYWRIGHT),
        {},
    ),
    (
        "Successfully downloaded pyyaml-6.0",
        "pip_successfully_downloaded",
        K.DOWNLOADED,
        _only(P.PIP),
        {"package_names_text": "pyyaml-6.0"},
    ),
    (
        "Available versions: 2.0, 1.0",
        "pip_index_versions",
        K.DOWNLOADED,
        _only(P.PIP_INDEX),
        {},
    ),
    (
        "  Downloading torch-2.3.0.whl (64 kB)",
        "downloading",
        K.DOWNLOAD_STARTED,
        _DOWNLOADS,
        {"package_names_text": "torch-2.3.0.whl"},
    ),
    # Old pip prints a URL before the file name.
    (
        "Downloading https://files.pythonhosted.org/packages/ab/requests-2.0.tar.gz",
        "downloading",
        K.DOWNLOAD_STARTED,
        _DOWNLOADS,
        {"package_names_text": "requests-2.0.tar.gz"},
    ),
    (
        "  Downloaded serde v1.0",
        "downloaded",
        K.DOWNLOADED,
        _DOWNLOADS,
        {"package_names_text": "serde"},
    ),
    (
        "Get:1 http://archive.ubuntu.com/ubuntu jammy/main amd64 x amd64 1.0 [10 kB]",
        "apt_get",
        K.DOWNLOADED,
        _only(P.APT),
        {"host_name_text": "archive.ubuntu.com", "package_names_text": "x"},
    ),
    # The Get line of an index names no package.
    (
        "Get:2 http://deb.debian.org/debian bookworm InRelease [151 kB]",
        "apt_get",
        K.DOWNLOADED,
        _only(P.APT),
        {"host_name_text": "deb.debian.org"},
    ),
    (
        "Fetched 315 kB in 1s (300 kB/s)",
        "apt_get",
        K.DOWNLOADED,
        _only(P.APT),
        {},
    ),
    (
        "2025-01-01 (1 MB/s) - 'x.tgz' saved [1024/1024]",
        "wget_saved",
        K.DOWNLOADED,
        _only(P.WGET),
        {},
    ),
    (
        "Successfully installed requests-2.32.3 idna-3.7",
        "pip_successfully_installed",
        K.INSTALLED,
        _only(P.PIP),
        {"package_names_text": "requests-2.32.3 idna-3.7"},
    ),
    (
        "Installed 3 packages in 5ms",
        "uv_installed",
        K.INSTALLED,
        _only(P.UV),
        {},
    ),
    (
        " + requests==2.32.3",
        "uv_installed",
        K.INSTALLED,
        _only(P.UV),
        {"package_names_text": "requests"},
    ),
    (
        "added 12 packages in 3s",
        "npm_added",
        K.INSTALLED,
        _only(P.NPM),
        {},
    ),
    (
        "Setting up curl (7.88.1-10) ...",
        "apt_setting_up",
        K.INSTALLED,
        _only(P.APT),
        {"package_names_text": "curl"},
    ),
    (
        "Unpacking libcurl4:amd64 (7.88) ...",
        "apt_setting_up",
        K.INSTALLED,
        _only(P.APT),
        {"package_names_text": "libcurl4:amd64"},
    ),
    (
        "audited 12 packages in 1s",
        "npm_audited",
        K.SERVER_ANSWERED,
        _only(P.NPM),
        {},
    ),
    (
        "found 0 vulnerabilities",
        "npm_audited",
        K.SERVER_ANSWERED,
        _only(P.NPM),
        {},
    ),
    (
        "Hit:1 http://archive.ubuntu.com/ubuntu jammy InRelease",
        "apt_hit",
        K.SERVER_ANSWERED,
        _only(P.APT),
        {"host_name_text": "archive.ubuntu.com"},
    ),
    ("404", "bare_status_code", K.BARE_STATUS_CODE, _ANY, {"status_code": 404}),
    # curl writes 000 for `%{http_code}` when no answer came.
    ("000", "bare_status_code", K.BARE_STATUS_CODE, _ANY, {"status_code": 0}),
    (
        "HTTP status: 200",
        "bare_status_code",
        K.BARE_STATUS_CODE,
        _ANY,
        {"status_code": 200},
    ),
    (
        "Connecting to a.org|1.2.3.4|:443... connected.",
        "wget_connected",
        K.CONNECTED,
        _also(P.WGET),
        {},
    ),
    (
        "* Connected to a.org (1.2.3.4) port 443",
        "connected_to_host",
        K.CONNECTED,
        _HEADERS,
        {"host_name_text": "a.org"},
    ),
]
# Lines that no program output pattern matches.
LINES_WITHOUT_MEANING = [
    "exit code: 127",
    "rc=200",
    "2000",
    "curl: (28) Operation timed out after 5000 milliseconds",
    "Max retries exceeded with url: /x",
    "cat: /tmp/missing.txt: No such file or directory",
    "Successfully built x",
    "Error response from daemon: not found",
    "echo Downloading x",
    "x Requirement already satisfied: y",
    "x + y==1.0",
    "pip: command not found here",
]


def _use_key(table: str, pattern: str) -> tuple[str, tuple[str, str]]:
    return OUTPUT_LINE_PATTERNS_DECLARATIONS, (table, pattern)


@pytest.mark.parametrize(
    ("line", "pattern_name", "kind", "printing", "texts"),
    EXAMPLE_LINES,
    ids=[example[0][:40] for example in EXAMPLE_LINES],
)
def test_example_line_gets_the_meaning_of_its_first_pattern_and_counts_it(
    line: str,
    pattern_name: str,
    kind: OutputLineKind,
    printing: tuple[frozenset[PrintingProgram], bool],
    texts: dict,
):
    knowledge = NetworkRequestResultKnowledge()
    printing_programs, is_printed_by_other_programs_too = printing

    meaning = knowledge.output_line_meaning(line, is_web_tool_result=False)

    assert meaning == OutputLineMeaning(
        kind=kind,
        printing_programs=printing_programs,
        is_printed_by_other_programs_too=is_printed_by_other_programs_too,
        host_name_text=texts.get("host_name_text"),
        package_names_text=texts.get("package_names_text"),
        missing_program_word=texts.get("missing_program_word"),
        status_code=texts.get("status_code"),
    )
    assert knowledge.uses.row_use_counts == Counter(
        {_use_key("program_output", pattern_name): 1}
    )
    assert not knowledge.uses.unknown_input_counts


def test_every_program_output_pattern_has_an_example_line():
    assert {example[1] for example in EXAMPLE_LINES} == {
        pattern.name for pattern in PROGRAM_OUTPUT_LINE_PATTERNS.patterns
    }


@pytest.mark.parametrize(
    ("line", "later_pattern_name"),
    [
        ("curl: (6) Could not resolve host: pypi.org", "name_resolution_failure"),
        (
            "curl: (7) Failed to connect to a.org port 443: Connection refused",
            "connection_failure",
        ),
    ],
)
def test_line_that_two_patterns_match_is_one_that_a_later_pattern_matches_too(
    line: str, later_pattern_name: str
):
    """The example table expects the earlier pattern for these lines, so this shows that the later one would match them as well."""
    (later_pattern,) = (
        pattern
        for pattern in PROGRAM_OUTPUT_LINE_PATTERNS.patterns
        if pattern.name == later_pattern_name
    )
    assert later_pattern.regex.search(line)


@pytest.mark.parametrize("line", LINES_WITHOUT_MEANING)
def test_line_without_a_pattern_is_unknown_and_not_counted(line: str):
    knowledge = NetworkRequestResultKnowledge()

    meaning = knowledge.output_line_meaning(line, is_web_tool_result=False)

    assert meaning == UnknownOutputLineMeaning()
    assert not knowledge.uses.unknown_input_counts
    assert not knowledge.uses.row_use_counts


def test_web_tool_result_is_read_only_with_the_web_tool_result_patterns():
    knowledge = NetworkRequestResultKnowledge()
    robot_check = "Please verify you are not a robot"

    in_web_tool_result = knowledge.output_line_meaning(
        robot_check, is_web_tool_result=True
    )
    in_program_output = knowledge.output_line_meaning(
        robot_check, is_web_tool_result=False
    )
    program_line_in_web_tool_result = knowledge.output_line_meaning(
        "Successfully installed x-1.0", is_web_tool_result=True
    )

    assert in_web_tool_result == OutputLineMeaning(
        kind=K.SERVER_ANSWERED,
        printing_programs=frozenset(),
        is_printed_by_other_programs_too=False,
        host_name_text=None,
        package_names_text=None,
        missing_program_word=None,
        status_code=None,
    )
    assert in_program_output == UnknownOutputLineMeaning()
    assert program_line_in_web_tool_result == UnknownOutputLineMeaning()
    assert knowledge.uses.row_use_counts == Counter(
        {_use_key("web_tool_result", "robot_check"): 1}
    )
    assert not knowledge.uses.unknown_input_counts


def test_uses_add_up_per_pattern_over_a_trial():
    knowledge = NetworkRequestResultKnowledge()
    lines = [
        "Successfully installed x-1.0",
        "Requirement already satisfied: y in /usr/lib",
        "Successfully installed z-2.0",
        "Collecting x",
        "Collecting z",
    ]

    for line in lines:
        knowledge.output_line_meaning(line, is_web_tool_result=False)

    assert knowledge.uses.row_use_counts == Counter(
        {
            _use_key("program_output", "pip_successfully_installed"): 2,
            _use_key("program_output", "pip_already_satisfied"): 1,
        }
    )
    assert not knowledge.uses.unknown_input_counts


def test_long_lines_are_read_in_linear_time():
    knowledge = NetworkRequestResultKnowledge()
    # About 100,000 characters each, so that a pattern taking quadratic time exceeds the bound within seconds instead of hanging.
    one_long_word = "a" * 100_000
    long_line_of_spaced_words = "a: " * 33_000

    start = time.perf_counter()
    meanings = [
        knowledge.output_line_meaning(line, is_web_tool_result=False)
        for line in (one_long_word, long_line_of_spaced_words)
    ]

    assert meanings == [UnknownOutputLineMeaning(), UnknownOutputLineMeaning()]
    assert time.perf_counter() - start < 10
