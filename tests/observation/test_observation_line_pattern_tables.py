"""Tests for observation/line_pattern_tables.py, through the observations that extract.py makes of example lines."""

import pytest

from tb_internet_use.network.model import PrintingProgram
from tb_internet_use.observation.extract import extract_observations
from tb_internet_use.observation.line_pattern_tables import PROGRAM_OUTPUT_LINE_PATTERNS
from tb_internet_use.observation.model import Observation, ObservationKind
from tb_internet_use.toolcall.model import (
    ExecutionStatus,
    HarnessTool,
    RawToolCall,
    RunCommandAction,
    ToolCall,
    ToolCallKey,
    ToolCallOutput,
)

# (made-up line, kind, the field that the line fills, if any, as (name, value))
EXAMPLE_LINES = [
    (
        "bash: pip: command not found",
        ObservationKind.PROGRAM_MISSING,
        ("missing_program", "pip"),
    ),
    (
        "sh: pip: not found",
        ObservationKind.PROGRAM_MISSING,
        ("missing_program", "pip"),
    ),
    (
        "#5 0.1 /bin/sh: 1: pip: not found",
        ObservationKind.PROGRAM_MISSING,
        ("missing_program", "pip"),
    ),
    (
        "./run.sh: line 3: type: pip: not found",
        ObservationKind.PROGRAM_MISSING,
        ("missing_program", "pip"),
    ),
    (
        "/usr/bin/python3: No module named pip",
        ObservationKind.PROGRAM_MISSING,
        ("missing_program", "pip"),
    ),
    (
        "failed to run command 'cargo': No such file",
        ObservationKind.PROGRAM_MISSING,
        ("missing_program", "cargo"),
    ),
    (
        "bash: /opt/tool/bin/x: No such file or directory",
        ObservationKind.PROGRAM_MISSING,
        ("missing_program", "x"),
    ),
    ("error: externally-managed-environment", ObservationKind.REFUSED_LOCALLY, None),
    (
        "hint: See PEP 668 for the detailed specification.",
        ObservationKind.REFUSED_LOCALLY,
        None,
    ),
    (
        "[notice] A new release of pip is available: 24.0 -> 25.0",
        ObservationKind.VERSION_NOTICE,
        None,
    ),
    (
        "[notice] To update, run: pip install --upgrade pip",
        ObservationKind.VERSION_NOTICE,
        None,
    ),
    ("ProxyError('Cannot connect to proxy.')", ObservationKind.PROXY_REFUSED, None),
    (
        "curl: (6) Could not resolve host: pypi.org",
        ObservationKind.NAME_NOT_RESOLVED,
        ("host", "pypi.org"),
    ),
    (
        "ssh: Could not resolve hostname git.example.org: Name or service not known",
        ObservationKind.NAME_NOT_RESOLVED,
        None,
    ),
    (
        "socket.gaierror: [Errno -3] Temporary failure in name resolution",
        ObservationKind.NAME_NOT_RESOLVED,
        None,
    ),
    ("ping: x: Name or service not known", ObservationKind.NAME_NOT_RESOLVED, None),
    ("nodename nor servname provided", ObservationKind.NAME_NOT_RESOLVED, None),
    ("No address associated with hostname", ObservationKind.NAME_NOT_RESOLVED, None),
    ("curl: (6) Couldn't resolve", ObservationKind.NAME_NOT_RESOLVED, None),
    (
        "curl: (60) SSL certificate problem: unable to get local issuer certificate",
        ObservationKind.TLS_FAILED,
        None,
    ),
    (
        "ssl.SSLError: [SSL: CERTIFICATE_VERIFY_FAILED]",
        ObservationKind.TLS_FAILED,
        None,
    ),
    (
        "curl: (7) Failed to connect to a.org port 443",
        ObservationKind.CONNECTION_FAILED,
        ("host", "a.org"),
    ),
    (
        "ConnectionRefusedError: [Errno 111] Connection refused",
        ObservationKind.CONNECTION_FAILED,
        None,
    ),
    ("connect ECONNREFUSED 127.0.0.1:3000", ObservationKind.CONNECTION_FAILED, None),
    ("connect: Connection timed out", ObservationKind.CONNECTION_FAILED, None),
    (
        "requests.exceptions.ConnectTimeout: timed out",
        ObservationKind.CONNECTION_FAILED,
        None,
    ),
    ("connect: No route to host", ObservationKind.CONNECTION_FAILED, None),
    ("Error: connect ETIMEDOUT 10.0.0.1:443", ObservationKind.CONNECTION_FAILED, None),
    (
        "Error: connect ENETUNREACH 10.0.0.1:443",
        ObservationKind.CONNECTION_FAILED,
        None,
    ),
    ("Error: read ECONNRESET", ObservationKind.CONNECTION_LOST, None),
    ("[Errno 101] Network is unreachable", ObservationKind.CONNECTION_FAILED, None),
    (
        "ConnectionResetError: [Errno 104] Connection reset by peer",
        ObservationKind.CONNECTION_LOST,
        None,
    ),
    (
        "ReadTimeoutError: Read timed out. (read timeout=15)",
        ObservationKind.CONNECTION_LOST,
        None,
    ),
    ("curl: (52) Empty reply from server", ObservationKind.CONNECTION_LOST, None),
    ("HTTP/2 404", ObservationKind.HTTP_STATUS, ("status_code", 404)),
    ("HTTP/1.1 200 OK", ObservationKind.HTTP_STATUS, ("status_code", 200)),
    (
        "2025-01-01 00:00:00 ERROR 404: Not Found.",
        ObservationKind.HTTP_STATUS,
        ("status_code", 404),
    ),
    (
        "HTTP request sent, awaiting response... 200 OK",
        ObservationKind.HTTP_STATUS,
        ("status_code", 200),
    ),
    (
        "curl: (22) The requested URL returned error: 403",
        ObservationKind.HTTP_STATUS,
        ("status_code", 403),
    ),
    (
        "requests.exceptions.HTTPError: 503 Server Error: x",
        ObservationKind.HTTP_STATUS,
        ("status_code", 503),
    ),
    (
        "urllib.error.HTTPError: HTTP Error 429: Too Many Requests",
        ObservationKind.HTTP_STATUS,
        ("status_code", 429),
    ),
    ("npm error code E404", ObservationKind.HTTP_STATUS, ("status_code", 404)),
    (
        "ERROR: No matching distribution found for nosuchpkg",
        ObservationKind.NOT_FOUND,
        ("package_names", frozenset({"nosuchpkg"})),
    ),
    (
        "ERROR: Could not find a version that satisfies the requirement torch==9",
        ObservationKind.NOT_FOUND,
        ("package_names", frozenset({"torch"})),
    ),
    (
        "E: Unable to locate package nosuch",
        ObservationKind.NOT_FOUND,
        ("package_names", frozenset({"nosuch"})),
    ),
    (
        "E: Package 'python' has no installation candidate",
        ObservationKind.NOT_FOUND,
        ("package_names", frozenset({"python"})),
    ),
    (
        "Requirement already satisfied: numpy in /usr/lib",
        ObservationKind.ALREADY_PRESENT,
        ("package_names", frozenset({"numpy"})),
    ),
    ("Audited 3 packages in 2ms", ObservationKind.ALREADY_PRESENT, None),
    (
        "curl is already the newest version (7.88).",
        ObservationKind.ALREADY_PRESENT,
        ("package_names", frozenset({"curl"})),
    ),
    (
        "Downloading Chromium 131.0 (playwright build v1148)",
        ObservationKind.DOWNLOAD_STARTED,
        None,
    ),
    (
        "Chromium 131.0 (playwright build v1148) downloaded to /root/.cache",
        ObservationKind.DOWNLOADED,
        None,
    ),
    (
        "Successfully downloaded requests",
        ObservationKind.DOWNLOADED,
        ("package_names", frozenset({"requests"})),
    ),
    ("Available versions: 2.0, 1.0", ObservationKind.DOWNLOADED, None),
    (
        "  Downloading requests-2.32.3-py3-none-any.whl (64 kB)",
        ObservationKind.DOWNLOAD_STARTED,
        ("package_names", frozenset({"requests"})),
    ),
    (
        "Downloading https://files.pythonhosted.org/packages/ab/requests-2.0.tar.gz",
        ObservationKind.DOWNLOAD_STARTED,
        ("package_names", frozenset({"requests"})),
    ),
    (
        "  Downloaded serde v1.0",
        ObservationKind.DOWNLOADED,
        ("package_names", frozenset({"serde"})),
    ),
    (
        "Get:1 http://deb.debian.org/debian bookworm/main amd64 curl amd64 7.88 [315 kB]",
        ObservationKind.DOWNLOADED,
        ("package_names", frozenset({"curl"})),
    ),
    ("Fetched 315 kB in 1s (300 kB/s)", ObservationKind.DOWNLOADED, None),
    (
        "2025-01-01 (1 MB/s) - 'a.tgz' saved [1024/1024]",
        ObservationKind.DOWNLOADED,
        None,
    ),
    (
        "Successfully installed requests-2.32.3 idna-3.7",
        ObservationKind.INSTALLED,
        ("package_names", frozenset({"requests", "idna"})),
    ),
    ("Installed 3 packages in 5ms", ObservationKind.INSTALLED, None),
    (
        " + requests==2.32.3",
        ObservationKind.INSTALLED,
        ("package_names", frozenset({"requests"})),
    ),
    ("added 12 packages in 3s", ObservationKind.INSTALLED, None),
    (
        "Setting up curl (7.88.1-10) ...",
        ObservationKind.INSTALLED,
        ("package_names", frozenset({"curl"})),
    ),
    (
        "Unpacking libcurl4:amd64 (7.88) ...",
        ObservationKind.INSTALLED,
        ("package_names", frozenset({"libcurl4"})),
    ),
    ("audited 12 packages in 1s", ObservationKind.SERVER_ANSWERED, None),
    ("found 0 vulnerabilities", ObservationKind.SERVER_ANSWERED, None),
    (
        "Hit:1 http://deb.debian.org/debian bookworm InRelease",
        ObservationKind.SERVER_ANSWERED,
        ("host", "deb.debian.org"),
    ),
    ("200", ObservationKind.BARE_STATUS_CODE, ("status_code", 200)),
    ("000", ObservationKind.BARE_STATUS_CODE, ("status_code", 0)),
    ("HTTP status: 404", ObservationKind.BARE_STATUS_CODE, ("status_code", 404)),
    ("Connecting to a.org|1.2.3.4|:443... connected.", ObservationKind.CONNECTED, None),
    (
        "* Connected to a.org (1.2.3.4) port 443",
        ObservationKind.CONNECTED,
        ("host", "a.org"),
    ),
]
# Lines that must give no observation.
LINES_WITHOUT_OBSERVATION = [
    "exit code: 127",
    "rc=200",
    "2000",
    "curl: (28) Operation timed out after 5000 milliseconds",
    "Max retries exceeded with url: /x",
    "cat: /tmp/missing.txt: No such file or directory",
    "Successfully built x",
    "Error response from daemon: not found",
]


def _call(text: str) -> ToolCall:
    key = ToolCallKey("trial", "main", 1, 0)
    output = ToolCallOutput(
        tool_output_text=text, execution_status=ExecutionStatus.FINISHED
    )
    return ToolCall(
        RawToolCall(key, HarnessTool("h", "t"), "", {}, None),
        RunCommandAction("x"),
        output,
    )


def _only_observation(line: str) -> Observation:
    (observation,) = extract_observations(_call(line))
    return observation


@pytest.mark.parametrize(
    ("line", "kind", "field"), EXAMPLE_LINES, ids=[e[0][:40] for e in EXAMPLE_LINES]
)
def test_example_line(
    line: str, kind: ObservationKind, field: tuple[str, object] | None
):
    observation = _only_observation(line)
    assert observation.kind == kind
    if field is not None:
        name, value = field
        actual = getattr(observation, name)
        assert (actual.name if name == "host" else actual) == value


@pytest.mark.parametrize("line", LINES_WITHOUT_OBSERVATION)
def test_line_without_observation(line: str):
    assert extract_observations(_call(line)) == ()


def test_every_row_has_an_example_line():
    rows_hit = {
        index
        for line, _, _ in EXAMPLE_LINES
        for index, row in enumerate(PROGRAM_OUTPUT_LINE_PATTERNS.rows)
        if row.regex.search(line)
        and not any(
            r.regex.search(line) for r in PROGRAM_OUTPUT_LINE_PATTERNS.rows[:index]
        )
    }
    assert rows_hit == set(range(len(PROGRAM_OUTPUT_LINE_PATTERNS.rows)))


def test_printing_programs_of_rows():
    assert _only_observation(
        "Successfully installed x-1.0"
    ).printing_programs == frozenset({PrintingProgram.PIP})
    download = _only_observation("Downloading x-1.0.tar.gz")
    assert (
        download.is_printed_by_other_programs_too
        and PrintingProgram.UV in download.printing_programs
    )
    refused = _only_observation("Connection refused")
    assert (refused.printing_programs, refused.is_printed_by_other_programs_too) == (
        frozenset(),
        True,
    )
