"""Types for evidence in tool call results of how far a candidate request got, e.g. a download line or an HTTP status.

They are found without knowing any request, since a line can appear in a different call from its request,
e.g. `Could not resolve host: pypi.org` in a later `tail fetch.log`.
"""

from dataclasses import dataclass
from enum import StrEnum

from tb_internet_use.network.model import Host, PrintingProgram
from tb_internet_use.toolcall.model import ToolCallKey

# Place of an observation in a call's result.
type ObservationPlace = OutputLine | HttpStatusField


@dataclass(frozen=True, slots=True)
class Observation:
    """Evidence in a call's result of how far a network request got, found without knowing any request and later linked to candidate requests.

    Not every kind is network traffic. For example `pip: command not found` shows that a request never left the machine.
    """

    call: ToolCallKey
    place: ObservationPlace
    kind: ObservationKind
    # Programs known to print the line.
    # Empty for a line that any program may print, and for a result field or a web tool result, which no program prints.
    printing_programs: frozenset[PrintingProgram]
    # Programs outside `printing_programs` print the line too, e.g. cargo prints `Downloaded x` like pip.
    # True for a line that any program may print, False for a result field or a web tool result.
    is_printed_by_other_programs_too: bool
    # The host the line names. None when it names none.
    host: Host | None
    # Normalized names of the packages a DOWNLOAD_STARTED, DOWNLOADED, NOT_FOUND, ALREADY_PRESENT or INSTALLED line names.
    # They are normalized like `CandidateRequest.asked_package_names`, e.g. requests for `requests-2.32.3-py3-none-any.whl`.
    package_names: frozenset[str]
    # The program a PROGRAM_MISSING line names, as `normalized_program_name` gives it, e.g. pip for `pip: command not found`.
    missing_program: str | None
    # The 3-digit number an HTTP_STATUS or BARE_STATUS_CODE line or the HTTP status field shows, 0 for curl's `000`.
    status_code: int | None


@dataclass(frozen=True, slots=True)
class OutputLine:
    """Observation place in a line of the call's `tool_output_text`."""

    # 0-based index of the line in the text split at "\n".
    line_index: int
    # 0-based index of the line in the `output` string of the JSON object that the output line holds, e.g. a Codex step result.
    # None when the output line holds no such object.
    line_index_in_json_string: int | None


@dataclass(frozen=True, slots=True)
class HttpStatusField:
    """Observation place in `ToolCallOutput.http_status`, the HTTP status a web fetch reports."""


class ObservationKind(StrEnum):
    """Kind of evidence in an output line or result field, without the level it gives a request."""

    # The host name did not resolve, e.g. `Could not resolve host: pypi.org`.
    NAME_NOT_RESOLVED = "name_not_resolved"
    # No connection was made, e.g. `Connection refused`, a connect timeout or an unreachable host.
    CONNECTION_FAILED = "connection_failed"
    # A connection was made and then broke, e.g. `Connection reset by peer`, `Read timed out` or curl errors 52 and 56.
    CONNECTION_LOST = "connection_lost"
    # A proxy refused the request or could not be reached, e.g. `ProxyError` in a Python traceback.
    PROXY_REFUSED = "proxy_refused"
    TLS_FAILED = "tls_failed"
    # A connection was made, as wget's `connected.` shows.
    CONNECTED = "connected"
    # A response status, e.g. `HTTP/1.1 404 Not Found` or wget `awaiting response... 200`, with its code in `status_code`.
    HTTP_STATUS = "http_status"
    # A line that only a server's answer gives, without a status code, e.g. npm `audited 12 packages` or apt `Hit:1`.
    SERVER_ANSWERED = "server_answered"
    # The package or repository was not found, e.g. pip `No matching distribution found for x`.
    NOT_FOUND = "not_found"
    # The package was already there, e.g. pip `Requirement already satisfied`.
    ALREADY_PRESENT = "already_present"
    # The program is not installed, e.g. `pip: command not found`.
    PROGRAM_MISSING = "program_missing"
    # The program refused before asking a server, e.g. pip's externally-managed-environment error.
    REFUSED_LOCALLY = "refused_locally"
    # pip's notice of a newer pip, from a check of PyPI that pip repeats weekly.
    VERSION_NOTICE = "version_notice"
    # A download began, e.g. pip `Downloading x.whl`, printed when the response begins.
    DOWNLOAD_STARTED = "download_started"
    # Content arrived, e.g. wget `saved` or apt `Get:1`.
    DOWNLOADED = "downloaded"
    # A package was installed, e.g. pip `Successfully installed`, which may come from a cache.
    INSTALLED = "installed"
    # A line of only a 3-digit number, maybe after a short label such as `status: `.
    # It is a status code only if e.g. `curl -w "%{http_code}"` printed it.
    BARE_STATUS_CODE = "bare_status_code"
