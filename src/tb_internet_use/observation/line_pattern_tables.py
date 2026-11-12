"""Define the tables of output line patterns that show how far a network request got, one for program output and one for web tool results.

The first row that matches a line decides its observation, so specific rows come before general ones.
No alternative may start with an unbounded repeat that can begin anywhere in a line, since one long line would then take quadratic time.
Every alternative matches lines in the trajectories, since one that matched none on the 2026-10-08 data was removed.
"""

import itertools
import re
from dataclasses import dataclass

from tb_internet_use.network.model import PrintingProgram
from tb_internet_use.observation.model import ObservationKind


@dataclass(frozen=True, slots=True)
class LinePattern:
    """Row of a line pattern table, giving a matching output line its kind and printing programs."""

    kind: ObservationKind
    printing_programs: frozenset[PrintingProgram]
    is_printed_by_other_programs_too: bool
    # Groups named `host`, `packages`, `program` and `status_code`, each with a number to keep names unique, fill the observation's fields.
    regex: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class LinePatternTable:
    """Ordered rows of line patterns, the first matching row deciding a line, used to find observations in output lines."""

    rows: tuple[LinePattern, ...]
    # All rows as one regex without named groups, to skip quickly the lines that no row matches.
    any_row_regex: re.Pattern[str]


def _line_pattern_table(*rows: LinePattern) -> LinePatternTable:
    """Make a table of rows, with one regex of all of them."""
    sources = (re.sub(r"\(\?P<\w+>", "(?:", row.regex.pattern) for row in rows)
    return LinePatternTable(
        rows, re.compile("|".join(f"(?:{source})" for source in sources))
    )


def _program_output_row(
    kind: ObservationKind,
    *alternatives: str,
    printed_only_by: PrintingProgram | None = None,
    printed_also_by: tuple[PrintingProgram, ...] = (),
) -> LinePattern:
    """Make a program output row for a line that only one program prints, or that any program can print, with the programs known to print it."""
    regex = _numbered_regex(alternatives)
    if printed_only_by is not None:
        return LinePattern(kind, frozenset({printed_only_by}), False, regex)
    return LinePattern(kind, frozenset(printed_also_by), True, regex)


def _web_tool_row(kind: ObservationKind, *alternatives: str) -> LinePattern:
    """Make a row of the web tool result table, whose lines no program prints."""
    return LinePattern(kind, frozenset(), False, _numbered_regex(alternatives))


def _numbered_regex(alternatives: tuple[str, ...]) -> re.Pattern[str]:
    """Join alternatives into one regex, numbering each named group so that alternatives can share a group name, e.g. host0 and host1."""
    numbers = itertools.count()
    return re.compile(
        re.sub(
            r"\(\?P<(host|packages|program|status_code)>",
            lambda m: f"(?P<{m.group(1)}{next(numbers)}>",
            "|".join(alternatives),
        )
    )


_HOST = r"(?P<host>[\w.-]+\.\w+)"
# Printing programs that print response headers, e.g. `HTTP/1.1 200 OK`.
_HEADER_PRINTING_PROGRAMS = (PrintingProgram.HTTP_HEADERS, PrintingProgram.GIT)
# Printing programs that print `Downloading x` lines.
_DOWNLOAD_PRINTING_PROGRAMS = (
    PrintingProgram.PIP,
    PrintingProgram.UV,
    PrintingProgram.PLAYWRIGHT,
    PrintingProgram.GIT,
    PrintingProgram.CODE,
)
# Labels that curl `-w` formats put before a bare status code, e.g. `status: 200`.
_STATUS_CODE_LABEL = r"(?i:(?:status|code|http|http_code|http status|response) ?[:=] ?)"

# Lines that programs print, read in every call's output except a web tool result.
PROGRAM_OUTPUT_LINE_PATTERNS = _line_pattern_table(
    _program_output_row(
        ObservationKind.PROGRAM_MISSING,
        # bash prints `bash: x: command not found`, and `./run.sh: line 3: type: x: not found` after a builtin such as type or exec.
        # dash prints `sh: 1: x: not found` or `./run.sh: 3: x: not found`. A shell or script name comes first, unlike `daemon: not found`.
        r"(?<![\w.+-])(?P<program>[\w.+-]+): command not found$",
        r"(?<!\S)\S+: (?:line )?\d+: (?:\w+: )?(?P<program>[\w.+/-]+): not found$",
        r"^\S*sh: (?:\w+: )?(?P<program>[\w.+/-]+): not found$",
        r"No module named (?P<program>pip)\b",
        r"failed to run command [‘'](?P<program>[^’']+)[’']: No such file",
        r"^(?:\S*sh: )?(?:line \d+: )?(?P<program>/\S+): No such file or directory$",
    ),
    _program_output_row(
        ObservationKind.REFUSED_LOCALLY,
        r"externally-managed-environment",
        r"^hint: See PEP 668",
        printed_only_by=PrintingProgram.PIP,
    ),
    _program_output_row(
        ObservationKind.VERSION_NOTICE,
        r"^\[notice\] (?:A new release of pip is available|To update, run:)",
        printed_only_by=PrintingProgram.PIP,
    ),
    _program_output_row(
        ObservationKind.PROXY_REFUSED,
        r"ProxyError",
    ),
    _program_output_row(
        ObservationKind.NAME_NOT_RESOLVED,
        rf"Could not resolve host:? {_HOST}",
    ),
    _program_output_row(
        ObservationKind.NAME_NOT_RESOLVED,
        r"Temporary failure in name resolution",
        r"Name or service not known",
        r"nodename nor servname",
        r"No address associated with hostname",
        r"curl: \(6\)",
    ),
    _program_output_row(
        ObservationKind.TLS_FAILED,
        r"SSL certificate problem",
        r"CERTIFICATE_VERIFY_FAILED",
        r"SSLError",
        r"curl: \((?:35|60)\)",
    ),
    _program_output_row(
        ObservationKind.CONNECTION_FAILED,
        rf"Failed to connect to {_HOST}",
        printed_only_by=PrintingProgram.CURL,
    ),
    _program_output_row(
        ObservationKind.CONNECTION_FAILED,
        r"Connection refused",
        r"Connection timed out",
        r"ConnectTimeout",
        r"Network is unreachable",
        r"No route to host",
        r"ECONNREFUSED",
        r"ETIMEDOUT",
        r"ENETUNREACH",
        r"curl: \(7\)",
    ),
    _program_output_row(
        ObservationKind.CONNECTION_LOST,
        r"Connection reset by peer",
        r"ECONNRESET",
        r"Read timed out",
        r"curl: \((?:52|56)\)",
    ),
    _program_output_row(
        ObservationKind.HTTP_STATUS,
        r"HTTP/[\d.]+ (?P<status_code>[1-5]\d\d)",
        printed_also_by=_HEADER_PRINTING_PROGRAMS,
    ),
    _program_output_row(
        ObservationKind.HTTP_STATUS,
        r"ERROR (?P<status_code>[45]\d\d):",
        r"awaiting response\.\.\. (?P<status_code>[1-5]\d\d)",
        printed_also_by=(PrintingProgram.WGET,),
    ),
    _program_output_row(
        ObservationKind.HTTP_STATUS,
        r"returned error: (?P<status_code>[45]\d\d)",
        printed_also_by=(PrintingProgram.HTTP_FAILURE, PrintingProgram.GIT),
    ),
    _program_output_row(
        ObservationKind.HTTP_STATUS,
        r"(?P<status_code>[45]\d\d) (?:Client|Server) Error",
        r"HTTP Error (?P<status_code>[45]\d\d)",
    ),
    _program_output_row(
        ObservationKind.HTTP_STATUS,
        r"npm (?:ERR!|error) (?:code E(?P<status_code>[45]\d\d)|(?P<status_code>404))",
        printed_only_by=PrintingProgram.NPM,
    ),
    _program_output_row(
        ObservationKind.NOT_FOUND,
        r"No matching distribution found for (?P<packages>\S+)",
        r"Could not find a version that satisfies the requirement (?P<packages>\S+)",
        printed_only_by=PrintingProgram.PIP,
    ),
    _program_output_row(
        ObservationKind.NOT_FOUND,
        r"^E: Unable to locate package (?P<packages>\S+)",
        r"^E: Package '(?P<packages>[^']+)' has no installation candidate",
        printed_only_by=PrintingProgram.APT,
    ),
    _program_output_row(
        ObservationKind.ALREADY_PRESENT,
        r"^Requirement already satisfied: (?P<packages>[\w.-]+)",
        printed_only_by=PrintingProgram.PIP,
    ),
    _program_output_row(
        ObservationKind.ALREADY_PRESENT,
        r"^Audited \d+ packages?",
        printed_only_by=PrintingProgram.UV,
    ),
    _program_output_row(
        ObservationKind.ALREADY_PRESENT,
        r"^(?P<packages>\S+) is already the newest version",
        printed_only_by=PrintingProgram.APT,
    ),
    # playwright prints `Downloading Chromium ...` before the download, which can still fail, and `... downloaded to /...` once it is done.
    _program_output_row(
        ObservationKind.DOWNLOADED,
        r"\) downloaded to /",
        printed_only_by=PrintingProgram.PLAYWRIGHT,
    ),
    _program_output_row(
        ObservationKind.DOWNLOADED,
        r"^Successfully downloaded (?P<packages>\S.*)",
        printed_only_by=PrintingProgram.PIP,
    ),
    _program_output_row(
        ObservationKind.DOWNLOADED,
        r"^Available versions: ",
        printed_only_by=PrintingProgram.PIP_INDEX,
    ),
    _program_output_row(
        ObservationKind.DOWNLOAD_STARTED,
        # Old pip prints a URL before the file name, e.g. `Downloading https://files.pythonhosted.org/.../x-1.0.tar.gz`.
        r"^[ \t]*Downloading (?:https?://\S*/)?(?P<packages>[\w.-]+)",
        printed_also_by=_DOWNLOAD_PRINTING_PROGRAMS,
    ),
    # cargo prints this line too, and has no printing program.
    _program_output_row(
        ObservationKind.DOWNLOADED,
        r"^[ \t]*Downloaded (?P<packages>[\w.-]+)",
        printed_also_by=_DOWNLOAD_PRINTING_PROGRAMS,
    ),
    # A package's Get line ends with its name, architecture, version and size. An index's does not.
    _program_output_row(
        ObservationKind.DOWNLOADED,
        rf"^Get:\d+ https?://{_HOST}(?:\S* \S+ \S+ (?P<packages>[\w.+-]+) (?:amd64|arm64|armhf|i386|all) \S+ \[)?",
        r"^Fetched [\d.,]+ [kMG]?B in",
        printed_only_by=PrintingProgram.APT,
    ),
    _program_output_row(
        ObservationKind.DOWNLOADED, r"saved \[\d+", printed_only_by=PrintingProgram.WGET
    ),
    _program_output_row(
        ObservationKind.INSTALLED,
        r"^Successfully installed (?P<packages>\S.*)",
        printed_only_by=PrintingProgram.PIP,
    ),
    _program_output_row(
        ObservationKind.INSTALLED,
        r"^Installed \d+ packages?",
        r"^ \+ (?P<packages>[\w.-]+)==",
        printed_only_by=PrintingProgram.UV,
    ),
    _program_output_row(
        ObservationKind.INSTALLED,
        r"\badded \d+ packages?\b",
        printed_only_by=PrintingProgram.NPM,
    ),
    _program_output_row(
        ObservationKind.INSTALLED,
        r"^Setting up (?P<packages>\S+) \(",
        r"^Unpacking (?P<packages>\S+) \(",
        printed_only_by=PrintingProgram.APT,
    ),
    _program_output_row(
        ObservationKind.SERVER_ANSWERED,
        r"\baudited \d+ packages?\b",
        r"found \d+ vulnerabilit",
        printed_only_by=PrintingProgram.NPM,
    ),
    _program_output_row(
        ObservationKind.SERVER_ANSWERED,
        rf"^Hit:\d+ https?://{_HOST}",
        printed_only_by=PrintingProgram.APT,
    ),
    _program_output_row(
        ObservationKind.BARE_STATUS_CODE,
        rf"^{_STATUS_CODE_LABEL}?(?P<status_code>000|[1-5]\d\d)$",
    ),
    _program_output_row(
        ObservationKind.CONNECTED,
        r"\.\.\. connected\.",
        printed_also_by=(PrintingProgram.WGET,),
    ),
    _program_output_row(
        ObservationKind.CONNECTED,
        rf"^\* Connected to {_HOST}",
        printed_also_by=_HEADER_PRINTING_PROGRAMS,
    ),
)
# Web tool results are page text, so only a page that a server gave instead of the content counts, e.g. a robot check.
WEB_TOOL_RESULT_LINE_PATTERNS = _line_pattern_table(
    _web_tool_row(
        ObservationKind.SERVER_ANSWERED,
        r"not a robot",
    ),
)
