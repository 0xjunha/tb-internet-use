"""Types for the program catalog, the hand-labeled table of what each program and subcommand does when a command runs it, and the request labels it shares with candidate requests.

A command names a program by its words, e.g. `uv pip install x`, and whether it reads files or makes a request depends on the program alone.
"""

from dataclasses import dataclass
from enum import StrEnum

from tb_internet_use.network.model import PrintingProgram


@dataclass(frozen=True, slots=True)
class ProgramCatalogRow:
    """Labels of one program and subcommand in the program catalog, read when finding file readers and candidate requests."""

    # The program as `normalized_program_name` gives it.
    program_name: str
    # The words after the program that the row needs, e.g. ("pip", "install") for `uv pip install`. Empty for any run of the program.
    subcommand_words: tuple[str, ...]
    # Its file arguments and its stdin file are files it reads, so its output can show them, e.g. cat or tail.
    reads_file_arguments: bool
    # The program named after it runs next and can make the request instead, e.g. tsc in `npx tsc` or pip in `uv run pip install x`.
    runs_next_program: bool
    # None when its run makes no request.
    request_rule: RequestRule | None


@dataclass(frozen=True, slots=True)
class RequestRule:
    """Request labels of one catalog row, copied to a candidate request after the command's options change them.

    Each field means what the `CandidateRequest` field of the same name means, e.g. `exit_zero_means` is SERVER_RESPONDED for curl until -f changes it.
    """

    kind: RequestKind
    printing_programs: frozenset[PrintingProgram]
    exit_zero_means: ExitZeroMeans | None
    fetches_only_to_run_or_build: bool
    # Where the packages it asks for are named, which decides the candidate request's `asked_package_names`.
    asked_packages_source: AskedPackagesSource
    asks_for_no_content: bool
    prints_response_body: bool


class RequestKind(StrEnum):
    """Kind of a candidate request, by the program or tool that makes it."""

    # A language package manager, e.g. pip, npm or uv.
    PACKAGE = "package"
    # A system package manager, e.g. apt-get or dnf.
    SYSTEM_PACKAGE = "system_package"
    # A git operation on a remote repository or its host's API, e.g. git clone or `gh api`.
    GIT = "git"
    # A download or HTTP client, e.g. curl or wget.
    URL = "url"
    # A direct connection to a named host, e.g. nc, ping or dig.
    REMOTE_HOST = "remote_host"
    # Network calls in Python or JavaScript code.
    CODE = "code"
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"
    # A search for text in a page.
    WEB_FIND = "web_find"


class ExitZeroMeans(StrEnum):
    """Meaning of exit code 0 of a request's own program, after the options that change it.

    Asking for no content, e.g. `curl -fI`, does not change it, since `asks_for_no_content` records that.
    """

    # The program also exits 0 without the network, e.g. pip with every package cached.
    NOTHING = "nothing"
    # The server answered, maybe with an HTTP error, e.g. curl without -f.
    SERVER_RESPONDED = "server_responded"
    # The server answered without an error, e.g. `curl -f`, wget or git clone.
    REQUEST_SUCCEEDED = "request_succeeded"


class AskedPackagesSource(StrEnum):
    """Place where the packages that a run of a program asks for are named."""

    # No package, e.g. `apt-get update` or `uv venv`.
    NONE = "none"
    # The command's targets, e.g. requests in `pip install requests`.
    TARGETS = "targets"
    # A file or the project, e.g. package.json for `npm ci` or pyproject.toml for `uv sync`.
    FILE_OR_PROJECT = "file_or_project"
