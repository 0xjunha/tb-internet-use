"""Declare the output line patterns of program output, read in the result of every call except a web tool result.

A pattern that reads a name comes before a general pattern that matches the same line, e.g. `could_not_resolve_host` before `name_resolution_failure`.
No alternative may start with an unbounded repeat that can begin anywhere in a line, since one long line would then take quadratic time.
"""

from tb_internet_use.knowledge.declarations.network_request_result.output_line_pattern_declaration import (
    OutputLinePattern,
    OutputLinePatternTable,
)
from tb_internet_use.network_request_result.model import (
    OutputLineKind,
    PrintingProgram,
)


def _make_program_output_pattern(
    name: str,
    kind: OutputLineKind,
    *alternatives: str,
    printed_only_by: PrintingProgram | None = None,
    printed_also_by: tuple[PrintingProgram, ...] = (),
) -> OutputLinePattern:
    """Make the pattern of a line that only one program prints, or that any program can print, with the programs known to print it.

    A line that only one program prints has no other printing programs, so giving both `printed_only_by` and `printed_also_by` raises `ValueError`.
    """
    if printed_only_by is not None and printed_also_by:
        raise ValueError(
            f"pattern {name} gives both printed_only_by and printed_also_by"
        )
    if printed_only_by is not None:
        return OutputLinePattern(
            name, kind, frozenset({printed_only_by}), False, alternatives
        )
    return OutputLinePattern(name, kind, frozenset(printed_also_by), True, alternatives)


# A host name or address with at least one dot, e.g. `pypi.org` or `127.0.0.1`.
_HOST_NAME_TEXT = r"(?P<host_name_text>[\w.-]+\.\w+)"
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

PROGRAM_OUTPUT_LINE_PATTERNS = OutputLinePatternTable(
    "program_output",
    (
        _make_program_output_pattern(
            "program_missing",
            OutputLineKind.PROGRAM_MISSING,
            # bash prints `bash: x: command not found`, and `./run.sh: line 3: type: x: not found` after a builtin such as type or exec.
            # dash prints `sh: 1: x: not found` or `./run.sh: 3: x: not found`. A shell or script name comes first, unlike `daemon: not found`.
            r"(?<![\w.+-])(?P<missing_program_word>[\w.+-]+): command not found$",
            r"(?<!\S)\S+: (?:line )?\d+: (?:\w+: )?(?P<missing_program_word>[\w.+/-]+): not found$",
            r"^\S*sh: (?:\w+: )?(?P<missing_program_word>[\w.+/-]+): not found$",
            r"No module named (?P<missing_program_word>pip)\b",
            r"failed to run command [‘'](?P<missing_program_word>[^’']+)[’']: No such file",
            r"^(?:\S*sh: )?(?:line \d+: )?(?P<missing_program_word>/\S+): No such file or directory$",
        ),
        _make_program_output_pattern(
            "pip_externally_managed",
            OutputLineKind.REFUSED_LOCALLY,
            r"^error: externally-managed-environment",
            r"^hint: See PEP 668",
            printed_only_by=PrintingProgram.PIP,
        ),
        _make_program_output_pattern(
            "pip_version_notice",
            OutputLineKind.VERSION_NOTICE,
            r"^\[notice\] (?:A new release of pip is available|To update, run:)",
            printed_only_by=PrintingProgram.PIP,
        ),
        _make_program_output_pattern(
            "proxy_error",
            OutputLineKind.PROXY_REFUSED,
            r"ProxyError",
        ),
        _make_program_output_pattern(
            "could_not_resolve_host",
            OutputLineKind.NAME_NOT_RESOLVED,
            rf"Could not resolve host:? {_HOST_NAME_TEXT}",
        ),
        _make_program_output_pattern(
            "name_resolution_failure",
            OutputLineKind.NAME_NOT_RESOLVED,
            r"Temporary failure in name resolution",
            r"Name or service not known",
            r"No address associated with hostname",
            r"curl: \(6\)",
            # Node.js and Go, e.g. `getaddrinfo ENOTFOUND registry.npmjs.org` and `dial tcp: lookup a.org: no such host`.
            r"getaddrinfo ENOTFOUND",
            r": no such host",
        ),
        _make_program_output_pattern(
            "tls_failure",
            OutputLineKind.TLS_FAILED,
            r"SSL certificate problem",
            r"CERTIFICATE_VERIFY_FAILED",
            r"SSLError",
            r"curl: \((?:35|60)\)",
        ),
        _make_program_output_pattern(
            "curl_failed_to_connect",
            OutputLineKind.CONNECTION_FAILED,
            rf"Failed to connect to {_HOST_NAME_TEXT}",
            printed_only_by=PrintingProgram.CURL,
        ),
        _make_program_output_pattern(
            "connection_failure",
            OutputLineKind.CONNECTION_FAILED,
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
        _make_program_output_pattern(
            "connection_lost",
            OutputLineKind.CONNECTION_LOST,
            r"Connection reset by peer",
            r"ECONNRESET",
            r"Read timed out",
            r"curl: \((?:52|56)\)",
        ),
        _make_program_output_pattern(
            "http_status_line",
            OutputLineKind.HTTP_STATUS,
            r"HTTP/[\d.]+ (?P<status_code>[1-5]\d\d)",
            printed_also_by=_HEADER_PRINTING_PROGRAMS,
        ),
        _make_program_output_pattern(
            "wget_http_status",
            OutputLineKind.HTTP_STATUS,
            r"ERROR (?P<status_code>[45]\d\d):",
            r"awaiting response\.\.\. (?P<status_code>[1-5]\d\d)",
            printed_also_by=(PrintingProgram.WGET,),
        ),
        _make_program_output_pattern(
            "http_returned_error",
            OutputLineKind.HTTP_STATUS,
            r"returned error: (?P<status_code>[45]\d\d)",
            printed_also_by=(PrintingProgram.HTTP_FAILURE, PrintingProgram.GIT),
        ),
        _make_program_output_pattern(
            "http_error_status",
            OutputLineKind.HTTP_STATUS,
            r"(?P<status_code>[45]\d\d) (?:Client|Server) Error",
            r"HTTP Error (?P<status_code>[45]\d\d)",
            # httpx `raise_for_status`, e.g. `Client error '401 Unauthorized' for url 'https://a.org/x'`.
            r"(?:Client|Server) error '(?P<status_code>[45]\d\d) ",
        ),
        _make_program_output_pattern(
            "npm_http_error",
            OutputLineKind.HTTP_STATUS,
            r"npm (?:ERR!|error) (?:code E(?P<status_code>[45]\d\d)|(?P<status_code>404))",
            printed_only_by=PrintingProgram.NPM,
        ),
        _make_program_output_pattern(
            "pip_no_matching_distribution",
            OutputLineKind.NOT_FOUND,
            r"No matching distribution found for (?P<package_names_text>\S+)",
            r"Could not find a version that satisfies the requirement (?P<package_names_text>\S+)",
            printed_only_by=PrintingProgram.PIP,
        ),
        _make_program_output_pattern(
            "apt_unable_to_locate_package",
            OutputLineKind.NOT_FOUND,
            r"^E: Unable to locate package (?P<package_names_text>\S+)",
            r"^E: Package '(?P<package_names_text>[^']+)' has no installation candidate",
            r"^E: Couldn't find any package by (?:glob|regex) '(?P<package_names_text>[^']+)'",
            printed_only_by=PrintingProgram.APT,
        ),
        _make_program_output_pattern(
            "pip_already_satisfied",
            OutputLineKind.ALREADY_PRESENT,
            r"^Requirement already satisfied: (?P<package_names_text>[\w.-]+)",
            printed_only_by=PrintingProgram.PIP,
        ),
        _make_program_output_pattern(
            "uv_audited",
            OutputLineKind.ALREADY_PRESENT,
            r"^Audited \d+ packages?",
            printed_only_by=PrintingProgram.UV,
        ),
        _make_program_output_pattern(
            "apt_already_newest",
            OutputLineKind.ALREADY_PRESENT,
            r"^(?P<package_names_text>\S+) is already the newest version",
            printed_only_by=PrintingProgram.APT,
        ),
        # playwright prints `Downloading Chromium ...` before the download, which can still fail, and `... downloaded to /...` once it is done.
        _make_program_output_pattern(
            "playwright_downloaded",
            OutputLineKind.DOWNLOADED,
            r"\) downloaded to /",
            printed_only_by=PrintingProgram.PLAYWRIGHT,
        ),
        _make_program_output_pattern(
            "pip_successfully_downloaded",
            OutputLineKind.DOWNLOADED,
            r"^Successfully downloaded (?P<package_names_text>\S.*)",
            printed_only_by=PrintingProgram.PIP,
        ),
        _make_program_output_pattern(
            "pip_index_versions",
            OutputLineKind.DOWNLOADED,
            r"^Available versions: ",
            printed_only_by=PrintingProgram.PIP_INDEX,
        ),
        # pip prints this for the metadata of a wheel, also when the wheel itself then comes from its cache as `Using cached x.whl`, so the line shows that the index answered but is no download of a package file.
        _make_program_output_pattern(
            "pip_downloading_metadata",
            OutputLineKind.SERVER_ANSWERED,
            r"^[ \t]*Downloading (?P<package_names_text>[\w.-]+\.metadata)\b",
            printed_only_by=PrintingProgram.PIP,
        ),
        _make_program_output_pattern(
            "downloading",
            OutputLineKind.DOWNLOAD_STARTED,
            # Old pip prints a URL before the file name, e.g. `Downloading https://files.pythonhosted.org/.../x-1.0.tar.gz`.
            r"^[ \t]*Downloading (?:https?://\S*/)?(?P<package_names_text>[\w.-]+)",
            printed_also_by=_DOWNLOAD_PRINTING_PROGRAMS,
        ),
        # lake prints this before it clones a dependency, which can still fail.
        _make_program_output_pattern(
            "lake_cloning",
            OutputLineKind.DOWNLOAD_STARTED,
            r": cloning (?:(?:https?|ssh|git)://|git@)",
            printed_only_by=PrintingProgram.LAKE,
        ),
        # Ivy prints this before it downloads a file of a dependency, which can still fail.
        _make_program_output_pattern(
            "ivy_downloading",
            OutputLineKind.DOWNLOAD_STARTED,
            r"^(?:\[info\] )?downloading https?://\S+ \.\.\.",
            printed_only_by=PrintingProgram.IVY,
        ),
        # cargo prints this line too, and has no printing program.
        _make_program_output_pattern(
            "downloaded",
            OutputLineKind.DOWNLOADED,
            r"^[ \t]*Downloaded (?P<package_names_text>[\w.-]+)",
            printed_also_by=_DOWNLOAD_PRINTING_PROGRAMS,
        ),
        # A package's Get line ends with its name, architecture, version and size. An index's does not.
        _make_program_output_pattern(
            "apt_get",
            OutputLineKind.DOWNLOADED,
            rf"^Get:\d+ https?://{_HOST_NAME_TEXT}(?:\S* \S+ \S+ (?P<package_names_text>[\w.+-]+) (?:amd64|arm64|armhf|i386|all) \S+ \[)?",
            r"^Fetched [\d.,]+ [kMG]?B in",
            printed_only_by=PrintingProgram.APT,
        ),
        _make_program_output_pattern(
            "wget_saved",
            OutputLineKind.DOWNLOADED,
            r"saved \[\d+",
            printed_only_by=PrintingProgram.WGET,
        ),
        _make_program_output_pattern(
            "pip_successfully_installed",
            OutputLineKind.INSTALLED,
            r"^Successfully installed (?P<package_names_text>\S.*)",
            printed_only_by=PrintingProgram.PIP,
        ),
        _make_program_output_pattern(
            "uv_installed",
            OutputLineKind.INSTALLED,
            r"^Installed \d+ packages?",
            r"^ \+ (?P<package_names_text>[\w.-]+)==",
            printed_only_by=PrintingProgram.UV,
        ),
        _make_program_output_pattern(
            "npm_added",
            OutputLineKind.INSTALLED,
            r"\badded \d+ packages?\b",
            printed_only_by=PrintingProgram.NPM,
        ),
        _make_program_output_pattern(
            "apt_setting_up",
            OutputLineKind.INSTALLED,
            r"^Setting up (?P<package_names_text>\S+) \(",
            r"^Unpacking (?P<package_names_text>\S+) \(",
            printed_only_by=PrintingProgram.APT,
        ),
        _make_program_output_pattern(
            "npm_audited",
            OutputLineKind.SERVER_ANSWERED,
            r"\baudited \d+ packages?\b",
            r"found \d+ vulnerabilit",
            printed_only_by=PrintingProgram.NPM,
        ),
        # npx prints this after it asked the registry for the package, and only when the package is missing.
        _make_program_output_pattern(
            "npm_exec_package_not_found",
            OutputLineKind.SERVER_ANSWERED,
            r"^npm (?:WARN|warn) exec The following packages? (?:was|were) not found and will be installed",
            printed_only_by=PrintingProgram.NPM,
        ),
        _make_program_output_pattern(
            "apt_hit",
            OutputLineKind.SERVER_ANSWERED,
            rf"^Hit:\d+ https?://{_HOST_NAME_TEXT}",
            printed_only_by=PrintingProgram.APT,
        ),
        _make_program_output_pattern(
            "bare_status_code",
            OutputLineKind.BARE_STATUS_CODE,
            rf"^{_STATUS_CODE_LABEL}?(?P<status_code>000|[1-5]\d\d)$",
        ),
        _make_program_output_pattern(
            "wget_connected",
            OutputLineKind.CONNECTED,
            r"\.\.\. connected\.",
            printed_also_by=(PrintingProgram.WGET,),
        ),
        _make_program_output_pattern(
            "connected_to_host",
            OutputLineKind.CONNECTED,
            rf"^\* Connected to {_HOST_NAME_TEXT}",
            printed_also_by=_HEADER_PRINTING_PROGRAMS,
        ),
    ),
)
