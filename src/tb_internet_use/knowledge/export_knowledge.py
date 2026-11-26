"""Answer the questions of `export_rows` about public hosts, web tools, package registries and the variables that may change them from the export catalogs, counting every use of a row and every input without one.

A blank cell is unknown only in the column that answers the question of each file, i.e. `service`, `sender`, `package_registry` and `changes_package_registry`. A blank there gives the `Unknown…` answer of the row, which counts as a use of the row and not as an unknown input. A blank `path_prefix` is the row of every other path of its host. Every other column fails the load when it is blank where the README of the catalogs asks for a value.
"""

import functools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tb_internet_use.expanded_tool_call.model import ProgramInvocation
from tb_internet_use.export.model import (
    HostService,
    NetworkRequestSender,
    PackageRegistry,
    PublicHost,
    UnknownChangesPackageRegistry,
    UnknownNetworkRequestSender,
    UnknownPackageRegistry,
    UnknownProgramVariable,
    UnknownPublicHost,
)
from tb_internet_use.knowledge.catalog import Catalog, KnowledgeUses, load_catalog
from tb_internet_use.tool_call.model import HarnessTool

EXPORT_CATALOGS_DIR = Path(__file__).parent / "catalogs" / "export"
PUBLIC_HOSTS_CSV = "public_hosts.csv"
HARNESS_WEB_TOOLS_CSV = "harness_web_tools.csv"
PROGRAM_PACKAGE_REGISTRIES_CSV = "program_package_registries.csv"
PROGRAM_VARIABLES_CSV = "program_variables.csv"
# A variable name as shell grammar writes it before `=`, e.g. `PIP_INDEX_URL`.
_VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ExportKnowledge:
    """Outside knowledge of `export_rows`, made for one trial and passed to it as `knowledge`, which it asks one question per method.

    An answer is a value or an `Unknown…` type of the step's model, never a default.
    `uses` counts every catalog row that answered and every input without one.
    The loaded catalogs are cached per process, so making one per trial is cheap.
    """

    def __init__(self, *, catalogs_dir: Path = EXPORT_CATALOGS_DIR) -> None:
        self.uses = KnowledgeUses()
        self._catalogs = _load_export_catalogs(catalogs_dir)

    def public_host(
        self, host_name: str, *, url_path: str | None
    ) -> PublicHost | UnknownPublicHost:
        """Answer which service a public host gives at a path, or `UnknownPublicHost` for a host without a row for the path or with a blank `service`.

        `url_path` is the path of the URL that names the host, as `parse_url_path` reads it, or None when the request names the host without such a URL, e.g. `ping pypi.org`.
        The row is the one of the host whose `path_prefix` is the longest start of `url_path`, e.g. `/api/` for `/api/models` of `huggingface.co`. Without one, or for None, it is the row whose `path_prefix` is blank.
        The name is matched in lower case, since host names do not differ by case (RFC 4343), e.g. `PyPI.org` asks the row of `pypi.org`. The path keeps its case, since paths can differ by case (RFC 3986).
        One lookup counts the row `(lower-case name, path_prefix)`, or `(lower-case name, "")` as an unknown input when the host has no row for the path.
        """
        lower_case_host_name = host_name.lower()
        path_prefix = _longest_path_prefix_of(
            self._catalogs.path_prefixes_by_host_name.get(lower_case_host_name, ()),
            url_path,
        )
        row = self._catalogs.public_hosts.lookup(
            (lower_case_host_name, path_prefix), self.uses
        )
        return UnknownPublicHost() if row is None else row

    def has_public_host_row(self, host_name: str) -> bool:
        """Tell whether the host catalog has a row of a host name, for any path and also one with a blank `service`, without counting, for the judgment rule of `export_rows` on dotted host names.

        The name is matched in lower case, as in `public_host`. Only `public_host` counts, so a host is counted once, under the row for the path of its URL.
        """
        return host_name.lower() in self._catalogs.path_prefixes_by_host_name

    def network_request_sender(
        self, harness_tool: HarnessTool
    ) -> NetworkRequestSender | UnknownNetworkRequestSender:
        """Answer where the web requests of a harness tool are sent from, or `UnknownNetworkRequestSender` for a tool without a row or with a blank `sender`.

        `harness_tool` is the tool of `FromWebTool`, which for a web step in a tool script is the tool of the script, e.g. Codex `exec`.
        One lookup counts the row `(harness, tool)`, or the same key as an unknown input.
        """
        row = self._catalogs.harness_web_tools.lookup(
            (harness_tool.harness, harness_tool.name), self.uses
        )
        return UnknownNetworkRequestSender() if row is None else row

    def package_registry(
        self, program_invocation: ProgramInvocation
    ) -> PackageRegistry | UnknownPackageRegistry:
        """Answer which registry, and which of its hosts, a program and subcommand ask by default, or `UnknownPackageRegistry` for one without a row or with a blank `package_registry`.

        The row is the one whose `program_name` and `subcommand` are those of the invocation, with the subcommand words joined by one space, e.g. `(uv, pip install)`. No other row answers, since the subcommand was settled when the command was read.
        One lookup counts that row, or the same key as an unknown input.
        """
        row = self._catalogs.program_package_registries.lookup(
            (
                program_invocation.program_name,
                " ".join(program_invocation.subcommand_words),
            ),
            self.uses,
        )
        return UnknownPackageRegistry() if row is None else row

    def changes_package_registry(
        self, program_invocation: ProgramInvocation, variable_name: str
    ) -> bool | UnknownChangesPackageRegistry | UnknownProgramVariable:
        """Answer whether a variable that a `NAME=value` before the command name gives a program and subcommand can change where its package requests go or whether they go out, e.g. True for `GOPROXY` of `go build` and False for `DEBIAN_FRONTEND` of `apt-get install`, `UnknownChangesPackageRegistry` for a row with a blank `changes_package_registry`, e.g. `GOPATH` of `go build`, or `UnknownProgramVariable` for a variable without a row, e.g. `PORT` of `npx`.

        The row is the one whose `program_name` and `subcommand` are those of the invocation, as for `package_registry`, and whose `variable_name` is the name in its case, since variable names differ by case.
        One lookup counts that row, or the same key as an unknown input.
        """
        row = self._catalogs.program_variables.lookup(
            (
                program_invocation.program_name,
                " ".join(program_invocation.subcommand_words),
                variable_name,
            ),
            self.uses,
        )
        return UnknownProgramVariable() if row is None else row


@functools.cache
def _load_export_catalogs(catalogs_dir: Path) -> _ExportCatalogs:
    """Load the four export CSVs of a folder once per process, raising ValueError on a row that `export_rows` cannot use, and index the path prefixes of each host."""
    public_hosts = load_catalog(
        catalogs_dir / PUBLIC_HOSTS_CSV,
        key_columns=("host_name", "path_prefix"),
        row_from_columns=_public_host_from_columns,
    )
    path_prefixes_by_host_name: dict[str, list[str]] = {}
    for host_name, path_prefix in public_hosts.row_keys:
        path_prefixes_by_host_name.setdefault(host_name, []).append(path_prefix)
    return _ExportCatalogs(
        public_hosts=public_hosts,
        path_prefixes_by_host_name={
            host_name: tuple(path_prefixes)
            for host_name, path_prefixes in path_prefixes_by_host_name.items()
        },
        harness_web_tools=load_catalog(
            catalogs_dir / HARNESS_WEB_TOOLS_CSV,
            key_columns=("harness", "tool"),
            row_from_columns=_network_request_sender_from_columns,
        ),
        program_package_registries=load_catalog(
            catalogs_dir / PROGRAM_PACKAGE_REGISTRIES_CSV,
            key_columns=("program_name", "subcommand"),
            row_from_columns=_package_registry_from_columns,
        ),
        program_variables=load_catalog(
            catalogs_dir / PROGRAM_VARIABLES_CSV,
            key_columns=("program_name", "subcommand", "variable_name"),
            row_from_columns=_changes_package_registry_from_columns,
        ),
    )


@dataclass(frozen=True, slots=True)
class _ExportCatalogs:
    """Loaded catalogs of `export_rows`, shared by every `ExportKnowledge` of a process."""

    public_hosts: Catalog[PublicHost | UnknownPublicHost]
    # The `path_prefix` of each row of a host in `public_hosts.csv`, in the order of the file, e.g. `("/api/", "")` for `huggingface.co`.
    path_prefixes_by_host_name: Mapping[str, tuple[str, ...]]
    harness_web_tools: Catalog[NetworkRequestSender | UnknownNetworkRequestSender]
    program_package_registries: Catalog[PackageRegistry | UnknownPackageRegistry]
    program_variables: Catalog[bool | UnknownChangesPackageRegistry]


def _longest_path_prefix_of(path_prefixes: Sequence[str], url_path: str | None) -> str:
    """Find the longest of the path prefixes of a host that starts `url_path`, or the blank prefix when none does or `url_path` is None."""
    if url_path is None:
        return ""
    return max(
        (
            path_prefix
            for path_prefix in path_prefixes
            if path_prefix and url_path.startswith(path_prefix)
        ),
        key=len,
        default="",
    )


def _public_host_from_columns(
    columns: Mapping[str, str],
) -> PublicHost | UnknownPublicHost:
    """Read one row of `public_hosts.csv`, raising ValueError on a host name that is empty or not in lower case, on a path prefix that is neither blank nor starts with `/`, on a service that is no `HostService` and on a `package_registry` that is missing for a registry or given for any other service."""
    _check_review_columns(columns)
    _check_host_name(columns["host_name"])
    path_prefix = columns["path_prefix"]
    if path_prefix and not path_prefix.startswith("/"):
        raise ValueError(
            f"path_prefix {path_prefix!r} is neither blank nor starts with /"
        )
    service = columns["service"]
    package_registry = columns["package_registry"]
    is_package_registry = service == HostService.PACKAGE_REGISTRY
    if bool(package_registry) != is_package_registry:
        raise ValueError(
            f"package_registry is {package_registry!r}, but it holds a name exactly when service is {HostService.PACKAGE_REGISTRY}"
        )
    if service == "":
        return UnknownPublicHost()
    return PublicHost(HostService(service), package_registry or None)


def _network_request_sender_from_columns(
    columns: Mapping[str, str],
) -> NetworkRequestSender | UnknownNetworkRequestSender:
    """Read one row of `harness_web_tools.csv`, raising ValueError on an empty harness or tool and on a sender that is no `NetworkRequestSender` or is the word `unknown`, since only a blank is unknown."""
    _check_review_columns(columns)
    if not columns["harness"] or not columns["tool"]:
        raise ValueError("harness or tool is empty")
    sender = columns["sender"]
    if sender == NetworkRequestSender.UNKNOWN:
        raise ValueError("sender is unknown only when blank")
    return (
        UnknownNetworkRequestSender() if sender == "" else NetworkRequestSender(sender)
    )


def _package_registry_from_columns(
    columns: Mapping[str, str],
) -> PackageRegistry | UnknownPackageRegistry:
    """Read one row of `program_package_registries.csv`, raising ValueError on an empty program name, on words not split by one space and on host names given without a registry or missing with one."""
    _check_review_columns(columns)
    if not columns["program_name"]:
        raise ValueError("program_name is empty")
    _check_words(columns, "subcommand")
    _check_words(columns, "package_registry_host_names")
    package_registry_name = columns["package_registry"]
    host_names = tuple(columns["package_registry_host_names"].split())
    if bool(package_registry_name) != bool(host_names):
        raise ValueError(
            f"package_registry is {package_registry_name!r} and package_registry_host_names is {columns['package_registry_host_names']!r}, but both are blank or both are given"
        )
    for host_name in host_names:
        _check_host_name(host_name)
    if not package_registry_name:
        return UnknownPackageRegistry()
    return PackageRegistry(package_registry_name, host_names)


def _changes_package_registry_from_columns(
    columns: Mapping[str, str],
) -> bool | UnknownChangesPackageRegistry:
    """Read one row of `program_variables.csv`, raising ValueError on an empty program name, on subcommand words not split by one space, on a variable name that shell grammar cannot assign and on a `changes_package_registry` that is neither `yes`, `no` nor blank."""
    _check_review_columns(columns)
    if not columns["program_name"]:
        raise ValueError("program_name is empty")
    _check_words(columns, "subcommand")
    variable_name = columns["variable_name"]
    if not _VARIABLE_NAME.fullmatch(variable_name):
        raise ValueError(f"variable_name {variable_name!r} is no variable name")
    changes_package_registry = columns["changes_package_registry"]
    if changes_package_registry == "":
        return UnknownChangesPackageRegistry()
    if changes_package_registry not in ("yes", "no"):
        raise ValueError(
            f"changes_package_registry is {changes_package_registry!r}, not yes, no or blank"
        )
    return changes_package_registry == "yes"


def _check_review_columns(columns: Mapping[str, str]) -> None:
    """Raise ValueError on a row that does not say what it was checked against, or whose `reviewed` is none of empty, `yes` and `agents`."""
    if not columns["checked_against"]:
        raise ValueError("checked_against is empty")
    if columns["reviewed"] not in ("", "yes", "agents"):
        raise ValueError(
            f"reviewed is {columns['reviewed']!r}, not empty, yes or agents"
        )


def _check_host_name(host_name: str) -> None:
    """Raise ValueError on a host name that is empty or not in lower case, since `ExportKnowledge` matches names in lower case."""
    if not host_name or host_name != host_name.lower():
        raise ValueError(f"host name {host_name!r} is empty or not in lower case")


def _check_words(columns: Mapping[str, str], column_name: str) -> None:
    """Raise ValueError on a cell that is not words split by one space, which an empty cell is."""
    cell = columns[column_name]
    if " ".join(cell.split()) != cell:
        raise ValueError(f"{column_name} {cell!r} is not words split by one space")
