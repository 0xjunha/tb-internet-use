"""Load the hand-labeled program catalog as the rows of each program, and list the programs that read their file arguments."""

import csv
import functools
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from tb_internet_use.network.model import PrintingProgram
from tb_internet_use.parse.program.model import (
    AskedPackagesSource,
    ExitZeroMeans,
    ProgramCatalogRow,
    RequestKind,
    RequestRule,
)

PROGRAM_CATALOG_CSV = Path(__file__).parent / "catalogs" / "program_catalog.csv"
# Columns of a row's request labels, filled only on a row with a `request_kind`.
_REQUEST_COLUMNS = (
    "request_kind",
    "printing_programs",
    "exit_zero_means",
    "fetches_only_to_run_or_build",
    "asked_packages_source",
    "asks_for_no_content",
    "prints_response_body",
)
# Request columns that may stay empty on a row with a `request_kind`.
_OPTIONAL_REQUEST_COLUMNS = frozenset({"printing_programs", "exit_zero_means"})


@functools.cache
def program_catalog() -> Mapping[str, tuple[ProgramCatalogRow, ...]]:
    """Load the committed program catalog once, as the rows of each program, longest subcommand first."""
    return load_program_catalog()


def file_reading_program_names() -> frozenset[str]:
    """List the programs whose file arguments a command reads, from the committed catalog."""
    return frozenset(
        name
        for name, rows in program_catalog().items()
        if any(row.reads_file_arguments for row in rows)
    )


def load_program_catalog(
    path: Path = PROGRAM_CATALOG_CSV,
) -> dict[str, tuple[ProgramCatalogRow, ...]]:
    """Read the program catalog CSV file and return the rows of each program, longest subcommand first.

    Raises ValueError for an unknown label, a repeated program and subcommand, a request label on a row without a request kind,
    a missing one on a row with it, or `reads_file_arguments` on a subcommand row.
    """
    rows_of_program: defaultdict[str, list[ProgramCatalogRow]] = defaultdict(list)
    seen: set[tuple[str, tuple[str, ...]]] = set()
    with path.open(newline="") as f:
        for csv_row in csv.DictReader(f):
            row = _catalog_row(csv_row)
            key = (row.program_name, row.subcommand_words)
            if key in seen:
                raise ValueError(f"repeated catalog row {key}")
            seen.add(key)
            rows_of_program[row.program_name].append(row)
    return {
        name: tuple(sorted(rows, key=lambda row: -len(row.subcommand_words)))
        for name, rows in rows_of_program.items()
    }


def _catalog_row(row: Mapping[str, str]) -> ProgramCatalogRow:
    """Turn one CSV row into a catalog row, checking that its columns fit together."""
    subcommand_words = tuple(row["subcommand"].split())
    reads_file_arguments = _yes_or_no(row["reads_file_arguments"])
    if reads_file_arguments and subcommand_words:
        raise ValueError(f"reads_file_arguments on a subcommand row {row}")
    return ProgramCatalogRow(
        program_name=row["program"],
        subcommand_words=subcommand_words,
        reads_file_arguments=reads_file_arguments,
        runs_next_program=_yes_or_no(row["runs_next_program"]),
        request_rule=_request_rule(row),
    )


def _request_rule(row: Mapping[str, str]) -> RequestRule | None:
    """Read a row's request labels, or None when it has no request kind."""
    if not row["request_kind"]:
        if any(row[column] for column in _REQUEST_COLUMNS):
            raise ValueError(f"request labels without a request_kind {row}")
        return None
    missing = [
        column
        for column in _REQUEST_COLUMNS
        if not row[column] and column not in _OPTIONAL_REQUEST_COLUMNS
    ]
    if missing:
        raise ValueError(f"missing request labels {missing} {row}")
    return RequestRule(
        kind=RequestKind(row["request_kind"]),
        printing_programs=frozenset(
            map(PrintingProgram, row["printing_programs"].split())
        ),
        exit_zero_means=ExitZeroMeans(row["exit_zero_means"])
        if row["exit_zero_means"]
        else None,
        fetches_only_to_run_or_build=_yes_or_no(row["fetches_only_to_run_or_build"]),
        asked_packages_source=AskedPackagesSource(row["asked_packages_source"]),
        asks_for_no_content=_yes_or_no(row["asks_for_no_content"]),
        prints_response_body=_yes_or_no(row["prints_response_body"]),
    )


def _yes_or_no(value: str) -> bool:
    """Read a yes or no column, with an empty value as no."""
    if value not in ("yes", "no", ""):
        raise ValueError(f"expected yes or no, got {value!r}")
    return value == "yes"
