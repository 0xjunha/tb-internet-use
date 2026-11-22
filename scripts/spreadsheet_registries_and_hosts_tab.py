"""Lay out the tab `Registries and hosts` of the spreadsheet of `build_spreadsheet.py`, with one line per package registry or host name under its host service.

A category splits one host over several lines, e.g. `pypi.org` over `package` and `other_web`, so the lines are grouped by the service of the host instead, e.g. `github.com` under `code_hosting`.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from openpyxl.utils import get_column_letter
from spreadsheet_cells import (
    CellStyle,
    TabCell,
    TabGrid,
    sparkline_bar_formula,
)
from spreadsheet_python_counts import (
    RowFiles,
    SpreadsheetPythonCounts,
    csv_dicts_of,
)
from spreadsheet_row_tabs import LOWER_AND_UPPER, TASK_ENVIRONMENT, header_cells_of
from spreadsheet_tabs import REGISTRIES_AND_HOSTS_TAB_NAME, RESULTS_TAB_COLOR

from tb_internet_use.export.model import (
    HostService,
    NetworkRequestCategory,
    NetworkRequestRow,
    PublicHost,
)
from tb_internet_use.knowledge.export_knowledge import ExportKnowledge

# The `host_service` of a public host without a row of the host catalog.
_UNKNOWN_HOST_SERVICE = "unknown"
# The lines that the table of a host service shows before it joins the rest in one line.
_SHOWN_LINE_COUNT = 10

# 1-based columns of every table of the tab.
_TRIALS_COLUMN = 3
_BAR_COLUMN = 4
_LAST_COLUMN = 5


@dataclass(frozen=True, slots=True)
class RegistriesAndHostsTab:
    """`Registries and hosts` tab with the trials of its lines, which `Method & checks` holds against a formula over the request rows."""

    grid: TabGrid
    # The trials of every line together.
    trial_ids: frozenset[str]
    # The trials of each line by its host service and its registry or host name, e.g. `("package_registry", "pypi")`, which `Overview` reads.
    trial_ids_by_host_service_and_name: dict[tuple[str, str], frozenset[str]]


@dataclass(frozen=True, slots=True)
class _RegistryOrHostLineKey:
    """Line of `Registries and hosts`, for lower-bound requests from the task environment that are no connectivity checks."""

    # A `HostService` value, or `unknown` for a public host without a row of the host catalog.
    host_service: str
    # The registry name under `package_registry`, e.g. `pypi`, and the host name under another service, e.g. `github.com`.
    registry_or_host_name: str


def lay_out_registries_and_hosts_tab(
    row_files: RowFiles, counts: SpreadsheetPythonCounts
) -> RegistriesAndHostsTab:
    """Lay out one table of host services and one table per host service with a line per registry or host, counted by Python.

    The counts are plain numbers, since a request row names several hosts in one cell and a host finds its registry in the host catalog, which no formula over the request rows reads.
    """
    trial_ids_by_line_key = _count_trial_ids_by_line_key(row_files)
    grid = TabGrid(REGISTRIES_AND_HOSTS_TAB_NAME, tab_color=RESULTS_TAB_COLOR)
    grid.add_row(TabCell(grid.name, style=CellStyle.TITLE))
    grid.add_note(
        "Registries and hosts requested from the task environment. (connectivity checks are excluded)",
        _LAST_COLUMN,
    )
    grid.add_row()
    host_services = sorted(
        {key.host_service for key in trial_ids_by_line_key},
        key=lambda host_service: _sort_key_of(
            _joined_trial_ids_of(
                _trial_ids_by_name_of(trial_ids_by_line_key, host_service).values()
            ),
            counts,
            host_service,
        ),
    )
    grid.add_row(TabCell("Host services", style=CellStyle.SECTION))
    _add_table(
        grid,
        "Host service",
        [
            (
                host_service,
                _joined_trial_ids_of(trial_ids_by_name.values()),
                _line_count_text_of(host_service, len(trial_ids_by_name)),
            )
            for host_service in host_services
            for trial_ids_by_name in (
                _trial_ids_by_name_of(trial_ids_by_line_key, host_service),
            )
        ],
        "Registries or hosts",
        counts,
    )
    for host_service in host_services:
        grid.add_row()
        grid.add_row(TabCell(host_service, style=CellStyle.SECTION))
        if host_service == _UNKNOWN_HOST_SERVICE:
            grid.add_note(
                "Public hosts whose service is not classified yet.", _LAST_COLUMN
            )
        trial_ids_by_name = _trial_ids_by_name_of(trial_ids_by_line_key, host_service)
        names = sorted(
            trial_ids_by_name,
            key=lambda name: _sort_key_of(trial_ids_by_name[name], counts, name),
        )
        table_lines = [
            (name, trial_ids_by_name[name], "") for name in names[:_SHOWN_LINE_COUNT]
        ]
        other_names = names[_SHOWN_LINE_COUNT:]
        if other_names:
            table_lines.append(
                (
                    f"({len(other_names):,} more)",
                    _joined_trial_ids_of(
                        trial_ids_by_name[name] for name in other_names
                    ),
                    "",
                )
            )
        _add_table(
            grid,
            "Registry" if host_service == HostService.PACKAGE_REGISTRY else "Host name",
            table_lines,
            "",
            counts,
        )
    grid.fixed_column_widths = {_BAR_COLUMN: 24}
    return RegistriesAndHostsTab(
        grid,
        frozenset(_joined_trial_ids_of(trial_ids_by_line_key.values())),
        {
            (key.host_service, key.registry_or_host_name): frozenset(trial_ids)
            for key, trial_ids in trial_ids_by_line_key.items()
        },
    )


def _count_trial_ids_by_line_key(
    row_files: RowFiles,
) -> dict[_RegistryOrHostLineKey, set[str]]:
    """Collect the trials of each line over the lower-bound request rows from the task environment, leaving out connectivity checks.

    A connectivity check asks a host for no content, e.g. `curl -I https://pypi.org`, so it is no request that a registry or host had to answer with content.
    """
    export_knowledge = ExportKnowledge()
    trial_ids_by_line_key: dict[_RegistryOrHostLineKey, set[str]] = {}
    for row in csv_dicts_of(row_files.network_request_rows, NetworkRequestRow):
        if (
            row["sender"] != TASK_ENVIRONMENT
            or row["request_measure_bound"] != LOWER_AND_UPPER
            or row["category"] == NetworkRequestCategory.CONNECTIVITY_CHECK
        ):
            continue
        for line_key in _line_keys_of(row, export_knowledge):
            trial_ids_by_line_key.setdefault(line_key, set()).add(row["trial_id"])
    return trial_ids_by_line_key


def _line_keys_of(
    row: dict[str, str], export_knowledge: ExportKnowledge
) -> list[_RegistryOrHostLineKey]:
    """Give the lines that a request row counts in, the registry of a package request and otherwise each of its hosts under its service.

    A host of a package registry counts in the line of its registry, e.g. `curl https://pypi.org/simple/x/ | head` in `pypi` beside `pip install x`, since both ask the same registry.
    """
    if row["category"] == NetworkRequestCategory.PACKAGE:
        return [
            _RegistryOrHostLineKey(
                HostService.PACKAGE_REGISTRY,
                row["package_registry"] or "(no registry)",
            )
        ]
    host_names = row["host_names"].split()
    if not host_names:
        return [_RegistryOrHostLineKey(_UNKNOWN_HOST_SERVICE, "(no host name)")]
    line_keys: list[_RegistryOrHostLineKey] = []
    for host_name, host_service in zip(
        host_names, row["host_service"].split(), strict=True
    ):
        registry_or_host_name = host_name.lower()
        if host_service == HostService.PACKAGE_REGISTRY:
            public_host = export_knowledge.public_host(host_name, url_path=None)
            if isinstance(public_host, PublicHost) and public_host.package_registry:
                registry_or_host_name = public_host.package_registry
        line_keys.append(_RegistryOrHostLineKey(host_service, registry_or_host_name))
    return line_keys


def _trial_ids_by_name_of(
    trial_ids_by_line_key: dict[_RegistryOrHostLineKey, set[str]], host_service: str
) -> dict[str, set[str]]:
    """Give the trials of the lines of one host service by their registry or host name."""
    return {
        key.registry_or_host_name: trial_ids
        for key, trial_ids in trial_ids_by_line_key.items()
        if key.host_service == host_service
    }


def _joined_trial_ids_of(trial_id_sets: Iterable[set[str]]) -> set[str]:
    joined_trial_ids: set[str] = set()
    for trial_ids in trial_id_sets:
        joined_trial_ids |= trial_ids
    return joined_trial_ids


def _sort_key_of(
    trial_ids: set[str], counts: SpreadsheetPythonCounts, name: str
) -> tuple[int, int, int, str]:
    """Give a key that puts the hosts without a catalog row last and otherwise the line of most tasks first, then of most trials.

    Tasks come before trials, since a host that one task asks in many trials is data of that task, e.g. `rest.uniprot.org`, while a host that many tasks ask is shared by them.
    """
    return (
        1 if name == _UNKNOWN_HOST_SERVICE else 0,
        -len(counts.tasks_of(trial_ids)),
        -len(trial_ids),
        name,
    )


def _line_count_text_of(host_service: str, line_count: int) -> str:
    if host_service == HostService.PACKAGE_REGISTRY:
        noun = "registry" if line_count == 1 else "registries"
    else:
        noun = "host" if line_count == 1 else "hosts"
    return f"{line_count:,} {noun}"


def _add_table(
    grid: TabGrid,
    name_header: str,
    table_lines: list[tuple[str, set[str], str]],
    last_header: str,
    counts: SpreadsheetPythonCounts,
) -> None:
    """Add a header and one row per line, with bars on the scale of the table's largest count of trials."""
    header_row = grid.add_row(
        *header_cells_of(name_header, "Tasks", "Trials", "", last_header)
    )
    first_row = header_row + 1
    last_row = header_row + max(len(table_lines), 1)
    trials_letter = get_column_letter(_TRIALS_COLUMN)
    scale_maximum = f"MAX(${trials_letter}${first_row}:${trials_letter}${last_row})"
    for name, trial_ids, last_text in table_lines:
        row = grid.next_row
        grid.add_row(
            TabCell(name),
            TabCell(len(counts.tasks_of(trial_ids)), style=CellStyle.PYTHON_COUNT),
            TabCell(len(trial_ids), style=CellStyle.PYTHON_COUNT),
            TabCell(
                None,
                formula=sparkline_bar_formula(
                    f"{trials_letter}{row}", scale_maximum=scale_maximum
                ),
                style=CellStyle.BAR,
            ),
            TabCell(last_text),
        )
