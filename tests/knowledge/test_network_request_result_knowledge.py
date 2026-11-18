"""Tests for knowledge/network_request_result_knowledge.py, with made-up output lines read against the declared output line patterns, made-up program output catalogs, and the rows of the real catalogs that came from the old program tables."""

import csv
import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call.model import ProgramInvocation, ProgramOption
from tb_internet_use.knowledge.catalog import KnowledgeLookupKey, KnowledgeUses
from tb_internet_use.knowledge.declarations.network_request_result.output_line_patterns import (
    PROGRAM_OUTPUT_LINE_PATTERNS,
)
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    EXPANDED_TOOL_CALL_CATALOGS_DIR,
    PROGRAM_BEHAVIORS_CSV,
)
from tb_internet_use.knowledge.network_request_result_knowledge import (
    NETWORK_REQUEST_RESULT_CATALOGS_DIR,
    OUTPUT_LINE_PATTERNS_DECLARATIONS,
    PROGRAM_EXIT_CODES_CSV,
    PROGRAM_OUTPUT_LINES_CSV,
    NetworkRequestResultKnowledge,
)
from tb_internet_use.network_request_result.model import (
    OutputLineKind,
    OutputLineMeaning,
    PrintingProgram,
    ProgramExitCodeMeaning,
    ProgramOutputLines,
    UnknownOutputLineMeaning,
    UnknownProgramExitCodeMeaning,
    UnknownProgramOutputLines,
)

K = OutputLineKind
M = ProgramExitCodeMeaning
P = PrintingProgram
_UNKNOWN_MEANING = UnknownProgramExitCodeMeaning()

# The printing programs of a pattern and whether other programs print its line too.
_ANY = (frozenset[PrintingProgram](), True)
_HEADERS = (frozenset({P.HTTP_HEADERS, P.GIT}), True)
_DOWNLOADS = (frozenset({P.PIP, P.UV, P.PLAYWRIGHT, P.GIT, P.CODE}), True)


def _only(program: PrintingProgram) -> tuple[frozenset[PrintingProgram], bool]:
    return frozenset({program}), False


def _lines(*programs: PrintingProgram) -> ProgramOutputLines:
    """Give the output lines of a run that prints the lines of the programs and no status code."""
    return ProgramOutputLines(frozenset(programs), False)


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


# The columns of the two program output catalogs.
_OUTPUT_LINES_COLUMNS = [
    "program_name",
    "subcommand",
    "option_name",
    "option_value_part",
    "printing_programs",
    "prints_status_code",
    "checked_against",
    "reviewed",
    "note",
]
_EXIT_CODES_COLUMNS = [
    "program_name",
    "subcommand",
    "option_name",
    "exit_code",
    "meaning",
    "checked_against",
    "reviewed",
    "note",
]
# A program row of `prog install` that prints the lines of two printing programs and a status code, so that a door that drops a word or a column fails.
_OUTPUT_LINES_ROW = {
    **dict.fromkeys(_OUTPUT_LINES_COLUMNS, ""),
    "program_name": "prog",
    "subcommand": "install",
    "printing_programs": "pip uv",
    "prints_status_code": "yes",
    "checked_against": "a manual",
}
# A program row of curl that prints curl lines and no status code.
_CURL_OUTPUT_LINES_ROW = {
    **_OUTPUT_LINES_ROW,
    "program_name": "curl",
    "subcommand": "",
    "printing_programs": "curl",
    "prints_status_code": "no",
}
_EXIT_CODES_ROW = {
    **dict.fromkeys(_EXIT_CODES_COLUMNS, ""),
    "program_name": "curl",
    "exit_code": "0",
    "meaning": "server_answered",
    "checked_against": "a manual",
}


def _curl_option_row(
    option_name: str,
    *,
    printing_programs: str = "changes_nothing",
    prints_status_code: str = "changes_nothing",
    option_value_part: str = "",
) -> dict[str, str]:
    return {
        **_CURL_OUTPUT_LINES_ROW,
        "option_name": option_name,
        "option_value_part": option_value_part,
        "printing_programs": printing_programs,
        "prints_status_code": prints_status_code,
    }


def _curl_exit_code_row(
    option_name: str, meaning: str, exit_code: str = "0"
) -> dict[str, str]:
    return {
        **_EXIT_CODES_ROW,
        "option_name": option_name,
        "exit_code": exit_code,
        "meaning": meaning,
    }


def _invocation(
    program_name: str = "prog",
    subcommand_words: tuple[str, ...] = (),
    *,
    options: tuple[ProgramOption, ...] = (),
    unread_words: tuple[str, ...] = (),
) -> ProgramInvocation:
    return ProgramInvocation(
        program_name=program_name,
        subcommand_words=subcommand_words,
        options=options,
        arguments=("https://a.org/x",),
        gets_more_arguments_at_run_time=False,
        unread_words=unread_words,
        exits_with_exit_code_of_next_program=False,
    )


# (rows of `program_output_lines.csv`, rows of `program_exit_codes.csv`, a part of the error message) of catalogs that fail the load.
_CATALOGS_THAT_CANNOT_LOAD = [
    (
        [{**_OUTPUT_LINES_ROW, "printing_programs": "changes_nothing"}],
        [],
        "changes_nothing in a program row",
    ),
    (
        [_CURL_OUTPUT_LINES_ROW, _curl_option_row("-i", printing_programs="none")],
        [],
        "none in an option row",
    ),
    (
        [{**_OUTPUT_LINES_ROW, "option_value_part": "%{http_code}"}],
        [],
        "option_value_part is filled in a program row",
    ),
    (
        [{**_OUTPUT_LINES_ROW, "printing_programs": "pip  uv"}],
        [],
        "'' is not a valid PrintingProgram",
    ),
    (
        [{**_OUTPUT_LINES_ROW, "printing_programs": "pip none"}],
        [],
        "'none' is not a valid PrintingProgram",
    ),
    ([{**_OUTPUT_LINES_ROW, "prints_status_code": "maybe"}], [], "not yes or no"),
    ([_curl_option_row("-i")], [], "has no program row"),
    ([{**_OUTPUT_LINES_ROW, "checked_against": ""}], [], "checked_against is empty"),
    ([{**_OUTPUT_LINES_ROW, "reviewed": "no"}], [], "not empty or yes"),
    ([{**_OUTPUT_LINES_ROW, "program_name": ""}], [], "program_name is empty"),
    (
        [{**_OUTPUT_LINES_ROW, "subcommand": "pip  install"}],
        [],
        "not words split by one space",
    ),
    ([_OUTPUT_LINES_ROW, _OUTPUT_LINES_ROW], [], "two rows have the key"),
    (
        [
            _CURL_OUTPUT_LINES_ROW,
            _curl_option_row(
                "-w", prints_status_code="yes", option_value_part="%{http_code} "
            ),
        ],
        [],
        "is not texts split by one space",
    ),
    ([], [{**_EXIT_CODES_ROW, "exit_code": "00"}], "not a whole number"),
    ([], [{**_EXIT_CODES_ROW, "exit_code": "-1"}], "not a whole number"),
    ([], [{**_EXIT_CODES_ROW, "meaning": "failed"}], "'failed' is not a valid"),
    (
        [],
        [{**_EXIT_CODES_ROW, "meaning": "changes_nothing"}],
        "changes_nothing in a program row",
    ),
    # An option row of exit 22 when only exit 0 has a program row.
    (
        [],
        [_EXIT_CODES_ROW, _curl_exit_code_row("-f", "request_succeeded", "22")],
        "has no program row",
    ),
]
# (option of curl, rows of `program_output_lines.csv` beside the curl row, the answer)
_OPTION_ROWS_OF_OUTPUT_LINES = [
    # An option row adds its printing programs.
    (
        ProgramOption("-i", None),
        [_curl_option_row("-i", printing_programs="http_headers")],
        ProgramOutputLines(frozenset({P.CURL, P.HTTP_HEADERS}), False),
    ),
    # A value that holds the text of `option_value_part` gives the row.
    (
        ProgramOption("-w", "code=%{http_code}\\n"),
        [
            _curl_option_row(
                "-w", prints_status_code="yes", option_value_part="%{http_code}"
            )
        ],
        ProgramOutputLines(frozenset({P.CURL}), True),
    ),
    # Any of the texts of `option_value_part` gives the row.
    (
        ProgramOption("-w", "%{response_code}"),
        [
            _curl_option_row(
                "-w",
                prints_status_code="yes",
                option_value_part="%{http_code} %{response_code}",
            )
        ],
        ProgramOutputLines(frozenset({P.CURL}), True),
    ),
    # A value without those texts changes nothing.
    (
        ProgramOption("-w", "%{size_download}"),
        [
            _curl_option_row(
                "-w", prints_status_code="yes", option_value_part="%{http_code}"
            )
        ],
        ProgramOutputLines(frozenset({P.CURL}), False),
    ),
    # A blank cell of an option row that does not apply leaves the answer known.
    (
        ProgramOption("-w", "%{size_download}"),
        [
            _curl_option_row(
                "-w", prints_status_code="", option_value_part="%{http_code}"
            )
        ],
        ProgramOutputLines(frozenset({P.CURL}), False),
    ),
    # A row of `no` in an option row does not take back a status code that another row prints.
    (
        ProgramOption("-s", None),
        [
            {
                **_CURL_OUTPUT_LINES_ROW,
                "option_name": "-s",
                "printing_programs": "changes_nothing",
                "prints_status_code": "no",
            },
        ],
        ProgramOutputLines(frozenset({P.CURL}), False),
    ),
]
# Values of `-w` for which a row with `option_value_part` `%{http_code}` may or may not apply, since the option has no value or its value is set when it runs.
_VALUES_OF_UNKNOWN_TEXT = [None, "$FMT", "${FMT}x"]
# (rows of `program_output_lines.csv`, invocation) whose answer is unknown because a cell that applies is blank.
_BLANK_CELLS_OF_OUTPUT_LINES = [
    ([{**_CURL_OUTPUT_LINES_ROW, "printing_programs": ""}], _invocation("curl")),
    ([{**_CURL_OUTPUT_LINES_ROW, "prints_status_code": ""}], _invocation("curl")),
    (
        [_CURL_OUTPUT_LINES_ROW, _curl_option_row("-i", printing_programs="")],
        _invocation("curl", options=(ProgramOption("-i", None),)),
    ),
    (
        [_CURL_OUTPUT_LINES_ROW, _curl_option_row("-i", prints_status_code="")],
        _invocation("curl", options=(ProgramOption("-i", None),)),
    ),
]
# (options of curl, rows of `program_exit_codes.csv` beside the curl row of exit 0, the answer for exit 0)
_OPTION_ROWS_OF_EXIT_CODES = [
    # The meaning of an option row takes the place of that of the program row.
    (
        (ProgramOption("-f", None),),
        [_curl_exit_code_row("-f", "request_succeeded")],
        ProgramExitCodeMeaning.REQUEST_SUCCEEDED,
    ),
    # `changes_nothing` keeps the meaning of the program row.
    (
        (ProgramOption("-s", None),),
        [_curl_exit_code_row("-s", "changes_nothing")],
        ProgramExitCodeMeaning.SERVER_ANSWERED,
    ),
    (
        (ProgramOption("-f", None), ProgramOption("-s", None)),
        [
            _curl_exit_code_row("-f", "request_succeeded"),
            _curl_exit_code_row("-s", "changes_nothing"),
        ],
        ProgramExitCodeMeaning.REQUEST_SUCCEEDED,
    ),
    # Two option rows of the same meaning agree.
    (
        (ProgramOption("-f", None), ProgramOption("--fail", None)),
        [
            _curl_exit_code_row("-f", "request_succeeded"),
            _curl_exit_code_row("--fail", "request_succeeded"),
        ],
        ProgramExitCodeMeaning.REQUEST_SUCCEEDED,
    ),
    # Two option rows that differ, and a blank meaning of an option row, are unknown.
    (
        (ProgramOption("-f", None), ProgramOption("-x", None)),
        [
            _curl_exit_code_row("-f", "request_succeeded"),
            _curl_exit_code_row("-x", "nothing"),
        ],
        UnknownProgramExitCodeMeaning(),
    ),
    (
        (ProgramOption("-f", None),),
        [_curl_exit_code_row("-f", "")],
        UnknownProgramExitCodeMeaning(),
    ),
]
# The options of the old curl and wget option rules, with what each adds to the lines of the program and the meaning of exit 0 it gives where it changes it.
_OPTIONS_OF_THE_OLD_RULES = [
    ("curl", ProgramOption("-i", None), {P.HTTP_HEADERS}, False),
    ("curl", ProgramOption("--include", None), {P.HTTP_HEADERS}, False),
    ("curl", ProgramOption("-I", None), {P.HTTP_HEADERS}, False),
    ("curl", ProgramOption("--head", None), {P.HTTP_HEADERS}, False),
    ("curl", ProgramOption("-v", None), {P.HTTP_HEADERS}, False),
    ("curl", ProgramOption("--verbose", None), {P.HTTP_HEADERS}, False),
    ("curl", ProgramOption("-f", None), {P.HTTP_FAILURE}, False),
    ("curl", ProgramOption("--fail", None), {P.HTTP_FAILURE}, False),
    ("curl", ProgramOption("--fail-with-body", None), {P.HTTP_FAILURE}, False),
    ("curl", ProgramOption("-w", "%{http_code}"), set(), True),
    ("curl", ProgramOption("--write-out", "status: %{http_code}\\n"), set(), True),
    ("curl", ProgramOption("-w", "%{response_code}"), set(), True),
    ("curl", ProgramOption("--write-out", "%{response_code}"), set(), True),
    ("wget", ProgramOption("-S", None), {P.HTTP_HEADERS}, False),
    ("wget", ProgramOption("--server-response", None), {P.HTTP_HEADERS}, False),
    ("wget", ProgramOption("-d", None), {P.HTTP_HEADERS}, False),
    ("wget", ProgramOption("--debug", None), {P.HTTP_HEADERS}, False),
]
# The (program, subcommand) pairs of the real program output catalogs that `program_behaviors.csv` has no row for yet.
# The rows come with the program catalog of `expand_tool_calls` and the set then shrinks, so that a pair that is misspelled never hides in it.
_PAIRS_WITHOUT_PROGRAM_BEHAVIOR_ROW_YET = {
    ("agent-browser", "install"),
    ("apt", "install"),
    ("apt", "update"),
    ("bun", "add"),
    ("dnf", "install"),
    ("dnf", "makecache"),
    ("go", "run"),
    ("lake", "build"),
    ("npm", "audit"),
    ("playwright", "install"),
    ("playwright", "install-deps"),
    ("sbt", ""),
}
# Printing programs that the output line patterns name but no program row gives, since a request of code asks the door with the run of its runner, e.g. python, and never as `CODE`.
_PRINTING_PROGRAMS_NOT_GIVEN_BY_A_PROGRAM_ROW = {P.CODE}
# (program, subcommand words, answer of `program_output_lines`, answer of `program_exit_code_meaning` for exit 0) of real program rows, with every subcommand of several words.
# The answers were read from the two CSVs by hand, so that a changed cell or a row lost from either file fails.
_ANSWERS_OF_REAL_PROGRAM_ROWS = [
    ("agent-browser", ("install",), _lines(P.PLAYWRIGHT, P.APT), _UNKNOWN_MEANING),
    ("apt", ("install",), _lines(P.APT), M.NOTHING),
    ("apt-get", ("update",), _lines(P.APT), M.NOTHING),
    ("bunx", (), _lines(P.NPM), M.NOTHING),
    ("conda", ("install",), UnknownProgramOutputLines(), M.NOTHING),
    ("curl", (), _lines(P.CURL), M.SERVER_ANSWERED),
    ("getent", ("hosts",), _lines(), _UNKNOWN_MEANING),
    ("gh", ("api",), _lines(P.GIT), M.REQUEST_SUCCEEDED),
    ("git", ("clone",), _lines(P.GIT), M.REQUEST_SUCCEEDED),
    ("git", ("submodule", "update"), _lines(P.GIT), M.NOTHING),
    ("go", ("mod", "tidy"), UnknownProgramOutputLines(), M.NOTHING),
    ("huggingface-cli", ("download",), UnknownProgramOutputLines(), M.NOTHING),
    ("npm", ("audit",), _lines(P.NPM), _UNKNOWN_MEANING),
    ("npm", ("view",), _lines(P.NPM), M.REQUEST_SUCCEEDED),
    ("pip", ("index", "versions"), _lines(P.PIP, P.PIP_INDEX), _UNKNOWN_MEANING),
    ("pip", ("install",), _lines(P.PIP), M.NOTHING),
    ("playwright", ("install-deps",), _lines(P.PLAYWRIGHT, P.APT), _UNKNOWN_MEANING),
    ("sbt", (), UnknownProgramOutputLines(), M.NOTHING),
    ("uv", ("pip", "install"), _lines(P.UV, P.PIP), M.NOTHING),
    ("uv", ("run",), _lines(P.UV, P.PIP), M.NOTHING),
    ("wget", (), _lines(P.WGET), M.REQUEST_SUCCEEDED),
]
_NOT_CHECKED = "not checked, from the old table"
# A manual page named as `name(section)`, e.g. `curl(1)`.
_MANUAL_PAGE_NAME = re.compile(r"\b[\w.+-]+\([1-9][a-z]*\)")
# A page of a program's own documentation named by its site and path, e.g. `(pip.pypa.io/en/stable/cli/pip/)`.
_DOCUMENTATION_PAGE_ADDRESS = re.compile(r"\((?:[\w-]+\.)+[a-z]+/[^)]*\)")


def _write_catalogs(
    tmp_path: Path,
    output_lines_rows: list[Mapping[str, str]],
    exit_code_rows: list[Mapping[str, str]],
) -> Path:
    for file_name, columns, rows in (
        (PROGRAM_OUTPUT_LINES_CSV, _OUTPUT_LINES_COLUMNS, output_lines_rows),
        (PROGRAM_EXIT_CODES_CSV, _EXIT_CODES_COLUMNS, exit_code_rows),
    ):
        with (tmp_path / file_name).open("w", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, columns)
            writer.writeheader()
            writer.writerows(rows)
    return tmp_path


def _knowledge(
    tmp_path: Path,
    output_lines_rows: list[Mapping[str, str]],
    exit_code_rows: Sequence[Mapping[str, str]] = (),
) -> NetworkRequestResultKnowledge:
    return NetworkRequestResultKnowledge(
        catalogs_dir=_write_catalogs(tmp_path, output_lines_rows, list(exit_code_rows))
    )


def _uses(file_name: str, *row_keys: tuple[str, ...]) -> Counter[KnowledgeLookupKey]:
    return Counter((file_name, row_key) for row_key in row_keys)


def _real_rows(file_name: str) -> list[dict[str, str]]:
    with (NETWORK_REQUEST_RESULT_CATALOGS_DIR / file_name).open(newline="") as csv_file:
        return list(csv.DictReader(csv_file))


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


def test_program_output_lines_reads_every_word_of_a_row_and_counts_each_lookup(
    tmp_path,
):
    knowledge = _knowledge(tmp_path, [_OUTPUT_LINES_ROW])

    answers = [
        knowledge.program_output_lines(_invocation("prog", ("install",)))
        for _ in range(2)
    ]

    assert answers == [ProgramOutputLines(frozenset({P.PIP, P.UV}), True)] * 2
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=_uses(
            PROGRAM_OUTPUT_LINES_CSV, ("prog", "install", ""), ("prog", "install", "")
        )
    )


def test_none_is_a_run_that_prints_no_line_of_a_pattern(tmp_path):
    knowledge = _knowledge(
        tmp_path,
        [
            {
                **_OUTPUT_LINES_ROW,
                "printing_programs": "none",
                "prints_status_code": "no",
            }
        ],
    )

    assert knowledge.program_output_lines(
        _invocation("prog", ("install",))
    ) == ProgramOutputLines(frozenset(), False)


@pytest.mark.parametrize(
    ("program_option", "option_rows", "answer"), _OPTION_ROWS_OF_OUTPUT_LINES
)
def test_option_rows_join_the_program_row_and_each_is_counted(
    tmp_path, program_option, option_rows, answer
):
    knowledge = _knowledge(tmp_path, [_CURL_OUTPUT_LINES_ROW, *option_rows])

    assert (
        knowledge.program_output_lines(_invocation("curl", options=(program_option,)))
        == answer
    )
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=_uses(
            PROGRAM_OUTPUT_LINES_CSV,
            ("curl", "", ""),
            ("curl", "", program_option.name),
        )
    )


@pytest.mark.parametrize("value", _VALUES_OF_UNKNOWN_TEXT)
def test_option_row_with_texts_on_a_value_of_unknown_text_makes_the_output_lines_unknown(
    tmp_path, value
):
    knowledge = _knowledge(
        tmp_path,
        [
            _CURL_OUTPUT_LINES_ROW,
            _curl_option_row(
                "-w", prints_status_code="yes", option_value_part="%{http_code}"
            ),
        ],
    )

    answer = knowledge.program_output_lines(
        _invocation("curl", options=(ProgramOption("-w", value),))
    )

    assert answer == UnknownProgramOutputLines()
    assert not knowledge.uses.unknown_input_counts


@pytest.mark.parametrize(
    ("program_prints_status_code", "option_prints_status_code"),
    [("yes", "no"), ("no", "yes")],
)
def test_run_prints_a_status_code_when_either_the_program_row_or_an_option_row_says_yes(
    tmp_path, program_prints_status_code, option_prints_status_code
):
    knowledge = _knowledge(
        tmp_path,
        [
            {
                **_CURL_OUTPUT_LINES_ROW,
                "prints_status_code": program_prints_status_code,
            },
            _curl_option_row("-x", prints_status_code=option_prints_status_code),
        ],
    )

    answer = knowledge.program_output_lines(
        _invocation("curl", options=(ProgramOption("-x", None),))
    )

    assert answer == ProgramOutputLines(frozenset({P.CURL}), True)


def test_option_row_answers_only_for_runs_of_its_own_subcommand(tmp_path):
    knowledge = _knowledge(
        tmp_path,
        [
            _OUTPUT_LINES_ROW,
            {
                **_OUTPUT_LINES_ROW,
                "option_name": "--verbose",
                "printing_programs": "http_headers",
                "prints_status_code": "changes_nothing",
            },
            {**_OUTPUT_LINES_ROW, "subcommand": "", "printing_programs": "npm"},
            {
                **_OUTPUT_LINES_ROW,
                "subcommand": "",
                "option_name": "--quiet",
                "printing_programs": "changes_nothing",
                "prints_status_code": "changes_nothing",
            },
        ],
    )

    of_install_with_its_option = knowledge.program_output_lines(
        _invocation("prog", ("install",), options=(ProgramOption("--verbose", None),))
    )
    of_install_with_an_option_of_no_subcommand = knowledge.program_output_lines(
        _invocation("prog", ("install",), options=(ProgramOption("--quiet", None),))
    )

    assert of_install_with_its_option == ProgramOutputLines(
        frozenset({P.PIP, P.UV, P.HTTP_HEADERS}), True
    )
    assert of_install_with_an_option_of_no_subcommand == UnknownProgramOutputLines()
    assert knowledge.uses.unknown_input_counts == _uses(
        PROGRAM_OUTPUT_LINES_CSV, ("prog", "install", "--quiet")
    )


@pytest.mark.parametrize(
    ("output_lines_rows", "invocation"), _BLANK_CELLS_OF_OUTPUT_LINES
)
def test_blank_cell_that_applies_makes_the_output_lines_unknown_and_not_a_default(
    tmp_path, output_lines_rows, invocation
):
    knowledge = _knowledge(tmp_path, output_lines_rows)

    assert knowledge.program_output_lines(invocation) == UnknownProgramOutputLines()
    assert not knowledge.uses.unknown_input_counts


def test_run_without_its_rows_is_unknown_and_counts_only_the_missing_keys(tmp_path):
    knowledge = _knowledge(
        tmp_path,
        [
            _CURL_OUTPUT_LINES_ROW,
            _curl_option_row("-i", printing_programs="http_headers"),
        ],
    )

    answers = [
        # A program without a row, and a subcommand of curl that has no row.
        knowledge.program_output_lines(_invocation("wget")),
        knowledge.program_output_lines(
            _invocation("curl", ("x",), options=(ProgramOption("-i", None),))
        ),
        # An option without a row beside one with a row.
        knowledge.program_output_lines(
            _invocation(
                "curl",
                options=(ProgramOption("-i", None), ProgramOption("-L", None)),
            )
        ),
        # Words that `expand_tool_calls` could not read after the first option without a fact.
        knowledge.program_output_lines(
            _invocation(
                "curl",
                options=(ProgramOption("-i", None),),
                unread_words=("--foo", "x", "https://a.org/x"),
            )
        ),
    ]

    assert answers == [UnknownProgramOutputLines()] * 4
    assert knowledge.uses == KnowledgeUses(
        unknown_input_counts=_uses(
            PROGRAM_OUTPUT_LINES_CSV,
            ("wget", "", ""),
            ("curl", "x", ""),
            ("curl", "", "-L"),
            ("curl", "", "--foo"),
        )
    )


def test_program_exit_code_meaning_reads_the_row_of_the_code_and_counts_it(tmp_path):
    knowledge = _knowledge(
        tmp_path,
        [],
        [
            _EXIT_CODES_ROW,
            {**_EXIT_CODES_ROW, "exit_code": "6", "meaning": "nothing"},
        ],
    )

    answers = [
        knowledge.program_exit_code_meaning(_invocation("curl"), exit_code)
        for exit_code in (0, 6, 0, 22)
    ]

    assert answers == [
        ProgramExitCodeMeaning.SERVER_ANSWERED,
        ProgramExitCodeMeaning.NOTHING,
        ProgramExitCodeMeaning.SERVER_ANSWERED,
        UnknownProgramExitCodeMeaning(),
    ]
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=_uses(
            PROGRAM_EXIT_CODES_CSV,
            ("curl", "", "", "0"),
            ("curl", "", "", "6"),
            ("curl", "", "", "0"),
        ),
        unknown_input_counts=_uses(PROGRAM_EXIT_CODES_CSV, ("curl", "", "", "22")),
    )


@pytest.mark.parametrize(
    ("program_options", "option_rows", "answer"), _OPTION_ROWS_OF_EXIT_CODES
)
def test_option_rows_of_exit_codes_take_the_place_of_the_program_row(
    tmp_path, program_options, option_rows, answer
):
    knowledge = _knowledge(tmp_path, [], [_EXIT_CODES_ROW, *option_rows])

    assert (
        knowledge.program_exit_code_meaning(
            _invocation("curl", options=program_options), 0
        )
        == answer
    )
    assert not knowledge.uses.unknown_input_counts


def test_blank_meaning_of_a_program_row_is_unknown_and_not_a_default(tmp_path):
    knowledge = _knowledge(tmp_path, [], [{**_EXIT_CODES_ROW, "meaning": ""}])

    assert (
        knowledge.program_exit_code_meaning(_invocation("curl"), 0)
        == UnknownProgramExitCodeMeaning()
    )
    assert knowledge.uses.row_use_counts == _uses(
        PROGRAM_EXIT_CODES_CSV, ("curl", "", "", "0")
    )


def test_blank_meaning_of_a_program_row_is_unknown_beside_an_option_row_with_a_meaning(
    tmp_path,
):
    knowledge = _knowledge(
        tmp_path,
        [],
        [
            {**_EXIT_CODES_ROW, "meaning": ""},
            _curl_exit_code_row("-f", "request_succeeded"),
        ],
    )

    answer = knowledge.program_exit_code_meaning(
        _invocation("curl", options=(ProgramOption("-f", None),)), 0
    )

    assert answer == UnknownProgramExitCodeMeaning()


def test_exit_code_of_an_option_without_a_row_is_unknown_and_counted_with_the_code(
    tmp_path,
):
    knowledge = _knowledge(
        tmp_path, [], [_EXIT_CODES_ROW, _curl_exit_code_row("-f", "request_succeeded")]
    )

    answer = knowledge.program_exit_code_meaning(
        _invocation(
            "curl", options=(ProgramOption("-f", None), ProgramOption("-s", None))
        ),
        0,
    )

    assert answer == UnknownProgramExitCodeMeaning()
    assert knowledge.uses == KnowledgeUses(
        unknown_input_counts=_uses(PROGRAM_EXIT_CODES_CSV, ("curl", "", "-s", "0"))
    )


@pytest.mark.parametrize(
    ("output_lines_rows", "exit_code_rows", "message"), _CATALOGS_THAT_CANNOT_LOAD
)
def test_catalog_that_decide_network_request_results_cannot_use_fails_the_load(
    tmp_path, output_lines_rows, exit_code_rows, message
):
    catalogs_dir = _write_catalogs(tmp_path, output_lines_rows, exit_code_rows)

    with pytest.raises(ValueError, match=re.escape(message)):
        NetworkRequestResultKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(
    "file_name", [PROGRAM_OUTPUT_LINES_CSV, PROGRAM_EXIT_CODES_CSV]
)
@pytest.mark.parametrize(
    "line_end", [",,a note, with an unquoted comma", ""], ids=["more", "fewer"]
)
def test_row_with_more_or_fewer_fields_than_the_header_fails_the_load(
    tmp_path, file_name, line_end
):
    catalogs_dir = _write_catalogs(
        tmp_path, [_CURL_OUTPUT_LINES_ROW], [_EXIT_CODES_ROW]
    )
    csv_path = catalogs_dir / file_name
    # The written row ends with the blank `reviewed` and `note`, so cutting those two leaves a row of two fields fewer.
    text = csv_path.read_text().rstrip("\r\n").removesuffix(",,")
    csv_path.write_text(text + line_end + "\n")

    with pytest.raises(ValueError, match="more or fewer fields than the header"):
        NetworkRequestResultKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(
    ("program_option", "answer"),
    [
        (
            ProgramOption("-w", "%{size_download}"),
            ProgramOutputLines(frozenset({P.CURL}), False),
        ),
        (ProgramOption("--write-out", "$FMT"), UnknownProgramOutputLines()),
        (ProgramOption("-w", None), UnknownProgramOutputLines()),
    ],
)
def test_real_write_out_rows_print_a_status_code_only_for_a_value_with_their_texts(
    program_option, answer
):
    knowledge = NetworkRequestResultKnowledge()

    assert (
        knowledge.program_output_lines(_invocation("curl", options=(program_option,)))
        == answer
    )


@pytest.mark.parametrize(
    "file_name", [PROGRAM_OUTPUT_LINES_CSV, PROGRAM_EXIT_CODES_CSV]
)
def test_real_catalog_loads_and_holds_no_invisible_control_characters_and_no_review_yet(
    file_name,
):
    NetworkRequestResultKnowledge()
    text = (NETWORK_REQUEST_RESULT_CATALOGS_DIR / file_name).read_text()

    assert not [c for c in text if ord(c) < 32 and c != "\n"]
    for row in _real_rows(file_name):
        assert row["reviewed"] == "", row
        assert (
            row["checked_against"].startswith(_NOT_CHECKED)
            or _MANUAL_PAGE_NAME.search(row["checked_against"])
            or _DOCUMENTATION_PAGE_ADDRESS.search(row["checked_against"])
        ), row


@pytest.mark.parametrize(
    ("program_name", "subcommand_words", "output_lines", "exit_zero_meaning"),
    _ANSWERS_OF_REAL_PROGRAM_ROWS,
)
def test_real_catalog_gives_the_pinned_answers_of_program_rows(
    program_name, subcommand_words, output_lines, exit_zero_meaning
):
    knowledge = NetworkRequestResultKnowledge()
    invocation = _invocation(program_name, subcommand_words)

    assert knowledge.program_output_lines(invocation) == output_lines
    assert knowledge.program_exit_code_meaning(invocation, 0) == exit_zero_meaning


def test_pinned_answers_hold_every_subcommand_of_several_words_of_the_real_catalogs():
    subcommands_of_several_words = {
        (row["program_name"], tuple(row["subcommand"].split(" ")))
        for file_name in (PROGRAM_OUTPUT_LINES_CSV, PROGRAM_EXIT_CODES_CSV)
        for row in _real_rows(file_name)
        if " " in row["subcommand"]
    }

    assert subcommands_of_several_words <= {
        (program_name, subcommand_words)
        for program_name, subcommand_words, _, _ in _ANSWERS_OF_REAL_PROGRAM_ROWS
    }


@pytest.mark.parametrize(
    ("program_name", "program_option", "added_printing_programs", "prints_status_code"),
    _OPTIONS_OF_THE_OLD_RULES,
)
def test_real_catalog_holds_the_curl_and_wget_options_of_the_old_rules(
    program_name, program_option, added_printing_programs, prints_status_code
):
    knowledge = NetworkRequestResultKnowledge()
    invocation = _invocation(program_name, options=(program_option,))
    program_printing_programs = {PrintingProgram(program_name)}

    assert knowledge.program_output_lines(invocation) == ProgramOutputLines(
        frozenset(program_printing_programs | added_printing_programs),
        prints_status_code,
    )
    assert not knowledge.uses.unknown_input_counts


@pytest.mark.parametrize("option_name", ["-f", "--fail", "--fail-with-body"])
def test_real_catalog_says_that_exit_zero_of_curl_with_a_fail_option_means_success(
    option_name,
):
    knowledge = NetworkRequestResultKnowledge()
    invocation = _invocation("curl", options=(ProgramOption(option_name, None),))

    assert (
        knowledge.program_exit_code_meaning(invocation, 0)
        == ProgramExitCodeMeaning.REQUEST_SUCCEEDED
    )
    assert (
        knowledge.program_exit_code_meaning(_invocation("curl"), 0)
        == ProgramExitCodeMeaning.SERVER_ANSWERED
    )


def test_real_catalog_gives_the_printing_programs_that_the_output_line_patterns_name():
    named_by_patterns = {
        printing_program
        for pattern in PROGRAM_OUTPUT_LINE_PATTERNS.patterns
        for printing_program in pattern.printing_programs
    }
    given_by_rows = {
        PrintingProgram(word)
        for row in _real_rows(PROGRAM_OUTPUT_LINES_CSV)
        for word in row["printing_programs"].split()
        if word not in ("none", "changes_nothing")
    }

    assert (
        given_by_rows
        == named_by_patterns - _PRINTING_PROGRAMS_NOT_GIVEN_BY_A_PROGRAM_ROW
    )


def test_pairs_of_the_real_catalogs_without_a_row_of_program_behaviors_are_the_pinned_ones():
    with (EXPANDED_TOOL_CALL_CATALOGS_DIR / PROGRAM_BEHAVIORS_CSV).open(
        newline=""
    ) as csv_file:
        behavior_keys = {
            (row["program_name"], row["subcommand"]) for row in csv.DictReader(csv_file)
        }
    pairs = {
        (row["program_name"], row["subcommand"])
        for file_name in (PROGRAM_OUTPUT_LINES_CSV, PROGRAM_EXIT_CODES_CSV)
        for row in _real_rows(file_name)
    }

    assert pairs - behavior_keys == _PAIRS_WITHOUT_PROGRAM_BEHAVIOR_ROW_YET


def _options(*names_and_values: str | tuple[str, str]) -> tuple[ProgramOption, ...]:
    return tuple(
        ProgramOption(*name_and_value)
        if isinstance(name_and_value, tuple)
        else ProgramOption(name_and_value, None)
        for name_and_value in names_and_values
    )


# (program name, subcommand words, options, lines it can print, meaning of exit 0) of runs with the options that the sample of trials uses, as the real catalogs must answer them.
_ANSWERS_OF_REAL_RUNS_WITH_OPTIONS = [
    (
        "curl",
        (),
        _options("-s", "-S", "-L", ("-o", "f"), ("-H", "A: b"), ("-X", "POST")),
        _lines(P.CURL),
        M.SERVER_ANSWERED,
    ),
    (
        "curl",
        (),
        _options("--silent", "--show-error", ("-d", "x"), ("-u", "a:b"), ("-m", "5")),
        _lines(P.CURL),
        M.SERVER_ANSWERED,
    ),
    (
        "curl",
        (),
        _options("-f", "-s", "-O"),
        _lines(P.CURL, P.HTTP_FAILURE),
        M.REQUEST_SUCCEEDED,
    ),
    (
        "curl",
        (),
        _options("-I", "-s"),
        _lines(P.CURL, P.HTTP_HEADERS),
        M.SERVER_ANSWERED,
    ),
    (
        "curl",
        (),
        _options("-s", ("-w", "%{http_code}")),
        ProgramOutputLines(frozenset({P.CURL}), prints_status_code=True),
        M.SERVER_ANSWERED,
    ),
    # With -D the headers go to stdout only for the value -, which the row cannot tell apart, so the lines are unknown.
    (
        "curl",
        (),
        _options(("-D", "h.txt")),
        UnknownProgramOutputLines(),
        M.SERVER_ANSWERED,
    ),
    ("wget", (), _options(("-O", "f")), _lines(P.WGET), M.REQUEST_SUCCEEDED),
    (
        "pip",
        ("install",),
        _options("-q", "--upgrade", ("--target", "d")),
        _lines(P.PIP),
        M.NOTHING,
    ),
    (
        "pip",
        ("download",),
        _options("-q", "--no-deps", ("-d", "d")),
        _lines(P.PIP),
        M.NOTHING,
    ),
    ("apt-get", ("install",), _options("-y", "-q"), _lines(P.APT), M.NOTHING),
    (
        "npm",
        ("install",),
        _options("--no-audit", "--no-fund"),
        _lines(P.NPM),
        M.NOTHING,
    ),
    (
        "git",
        ("clone",),
        _options(("--depth", "1"), "-q"),
        _lines(P.GIT),
        M.REQUEST_SUCCEEDED,
    ),
]


@pytest.mark.parametrize(
    (
        "program_name",
        "subcommand_words",
        "options",
        "output_lines",
        "exit_zero_meaning",
    ),
    _ANSWERS_OF_REAL_RUNS_WITH_OPTIONS,
)
def test_real_catalogs_answer_for_runs_with_the_options_of_the_sample(
    program_name, subcommand_words, options, output_lines, exit_zero_meaning
):
    knowledge = NetworkRequestResultKnowledge()
    program_invocation = _invocation(program_name, subcommand_words, options=options)

    assert knowledge.program_output_lines(program_invocation) == output_lines
    assert (
        knowledge.program_exit_code_meaning(program_invocation, 0) == exit_zero_meaning
    )
