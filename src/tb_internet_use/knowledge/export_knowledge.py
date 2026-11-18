"""Answer the questions of `export_rows` about public hosts, web tools and package registries from the export catalogs, counting every use of a row and every input without one.

A blank cell is unknown only in the column that answers the question of each file, i.e. `service`, `sender` and `package_registry`. A blank there gives the `Unknown…` answer of the row, which counts as a use of the row and not as an unknown input. Every other column fails the load when it is blank where the README of the catalogs asks for a value.
"""

import functools
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tb_internet_use.expanded_tool_call.model import ProgramInvocation
from tb_internet_use.export.model import (
    HostService,
    NetworkRequestSender,
    PackageRegistry,
    PublicHost,
    UnknownNetworkRequestSender,
    UnknownPackageRegistry,
    UnknownPublicHost,
)
from tb_internet_use.knowledge.catalog import Catalog, KnowledgeUses, load_catalog
from tb_internet_use.tool_call.model import HarnessTool

EXPORT_CATALOGS_DIR = Path(__file__).parent / "catalogs" / "export"
PUBLIC_HOSTS_CSV = "public_hosts.csv"
HARNESS_WEB_TOOLS_CSV = "harness_web_tools.csv"
PROGRAM_PACKAGE_REGISTRIES_CSV = "program_package_registries.csv"


class ExportKnowledge:
    """Door of `export_rows` to the outside knowledge, made for one trial and passed to `export_rows`, which asks it one question per method.

    An answer is a value or an `Unknown…` type of the step's model, never a default.
    `uses` counts every catalog row that answered and every input without one.
    The loaded catalogs are cached per process, so making a door per trial is cheap.
    """

    def __init__(self, *, catalogs_dir: Path = EXPORT_CATALOGS_DIR) -> None:
        self.uses = KnowledgeUses()
        self._catalogs = _load_export_catalogs(catalogs_dir)

    def public_host(self, host_name: str) -> PublicHost | UnknownPublicHost:
        """Answer which service a public host gives, or `UnknownPublicHost` for a host without a row or with a blank `service`.

        The name is matched in lower case, since host names do not differ by case (RFC 4343), e.g. `PyPI.org` asks the row of `pypi.org`.
        One lookup counts the row `(lower-case name,)`, or the same key as an unknown input.
        """
        row = self._catalogs.public_hosts.lookup((host_name.lower(),), self.uses)
        return UnknownPublicHost() if row is None else row

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


@functools.cache
def _load_export_catalogs(catalogs_dir: Path) -> _ExportCatalogs:
    """Load the three export CSVs of a folder once per process, raising ValueError on a row that `export_rows` cannot use."""
    return _ExportCatalogs(
        public_hosts=load_catalog(
            catalogs_dir / PUBLIC_HOSTS_CSV,
            key_columns=("host_name",),
            row_from_columns=_public_host_from_columns,
        ),
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
    )


@dataclass(frozen=True, slots=True)
class _ExportCatalogs:
    """Loaded catalogs of `export_rows`, shared by every `ExportKnowledge` of a process."""

    public_hosts: Catalog[PublicHost | UnknownPublicHost]
    harness_web_tools: Catalog[NetworkRequestSender | UnknownNetworkRequestSender]
    program_package_registries: Catalog[PackageRegistry | UnknownPackageRegistry]


def _public_host_from_columns(
    columns: Mapping[str, str],
) -> PublicHost | UnknownPublicHost:
    """Read one row of `public_hosts.csv`, raising ValueError on a host name that is empty or not in lower case, on a service that is no `HostService` and on a `package_registry` that is missing for a registry or given for any other service."""
    _check_review_columns(columns)
    _check_host_name(columns["host_name"])
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


def _check_review_columns(columns: Mapping[str, str]) -> None:
    """Raise ValueError on a row that does not say what it was checked against, or whose `reviewed` is neither empty nor `yes`."""
    if not columns["checked_against"]:
        raise ValueError("checked_against is empty")
    if columns["reviewed"] not in ("", "yes"):
        raise ValueError(f"reviewed is {columns['reviewed']!r}, not empty or yes")


def _check_host_name(host_name: str) -> None:
    """Raise ValueError on a host name that is empty or not in lower case, since the door matches names in lower case."""
    if not host_name or host_name != host_name.lower():
        raise ValueError(f"host name {host_name!r} is empty or not in lower case")


def _check_words(columns: Mapping[str, str], column_name: str) -> None:
    """Raise ValueError on a cell that is not words split by one space, which an empty cell is."""
    cell = columns[column_name]
    if " ".join(cell.split()) != cell:
        raise ValueError(f"{column_name} {cell!r} is not words split by one space")
