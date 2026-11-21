"""Load a knowledge CSV into rows by key and count every lookup of it, so that each knowledge class counts the uses of its facts and its unknown inputs in the same way."""

import csv
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# The values of the key columns of one row of a catalog or of a declaration, e.g. `("codex", "exec_command")`.
type KnowledgeRowKey = tuple[str, ...]
# The name of a catalog file, of a declaration folder or of a count that a knowledge class keeps itself, and a row key, e.g. `("harness_tools.csv", ("codex", "exec_command"))`, `("harness_result_formats", ("codex", "exec_command", "exited"))` or `("names_read_without_version", ("python3.11", "python"))`.
type KnowledgeLookupKey = tuple[str, KnowledgeRowKey]


def load_catalog[Row](
    csv_path: Path,
    *,
    key_columns: Sequence[str],
    row_from_columns: Callable[[Mapping[str, str]], Row],
) -> Catalog[Row]:
    """Load a knowledge CSV into a `Catalog` whose rows are keyed by the values of the key columns.

    `row_from_columns` turns the columns of one CSV row into the row type of the knowledge class, and raises ValueError on a value the knowledge class cannot use.
    Two rows with the same key raise ValueError, since a lookup answers with one row.
    A ValueError gets the file name and the line the reader had reached, 1-based, as a note.
    """
    rows_by_key: dict[KnowledgeRowKey, Row] = {}
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for columns in reader:
            try:
                row_key = tuple(columns[name] for name in key_columns)
                if row_key in rows_by_key:
                    raise ValueError(f"two rows have the key {row_key}")
                rows_by_key[row_key] = row_from_columns(columns)
            except ValueError as error:
                error.add_note(f"{csv_path.name} line {reader.line_num}")
                raise
    return Catalog(csv_path.name, rows_by_key)


@dataclass(frozen=True, slots=True)
class Catalog[Row]:
    """Rows of one knowledge CSV by key, held by a knowledge class and read only through `lookup`, which counts the use or the miss.

    `row_keys` gives the keys without counting, so that a knowledge class can pick the key it asks, or build an index when the file loads, e.g. `_NetworkRequestCatalogs.fetches_by_program_name`. Some methods answer from such an index, e.g. `NetworkRequestKnowledge.may_program_fetch`, which counts its answer itself, and `NetworkRequestKnowledge.has_code_call_row`, which counts nothing.
    """

    # The name of the CSV file, e.g. `harness_tools.csv`, which the counts carry.
    file_name: str
    _rows_by_key: Mapping[KnowledgeRowKey, Row]

    @property
    def row_keys(self) -> tuple[KnowledgeRowKey, ...]:
        """List the key of every row, in the order of the file."""
        return tuple(self._rows_by_key)

    def lookup(self, row_key: KnowledgeRowKey, uses: KnowledgeUses) -> Row | None:
        """Find the row of a key and record the lookup in `uses`, as a use of that row or, when no row has the key, as an unknown input."""
        row = self._rows_by_key.get(row_key)
        if row is None:
            uses.unknown_input_counts[self.file_name, row_key] += 1
        else:
            uses.row_use_counts[self.file_name, row_key] += 1
        return row


@dataclass(slots=True)
class KnowledgeUsesTotal:
    """Sum of the `KnowledgeUses` of many trials, built by an audit script to list how often and in how many trials each fact was used and each unknown input was asked."""

    row_use_counts: Counter[KnowledgeLookupKey] = field(default_factory=Counter)
    # The number of trials that used the row at least once.
    row_trial_counts: Counter[KnowledgeLookupKey] = field(default_factory=Counter)
    unknown_input_counts: Counter[KnowledgeLookupKey] = field(default_factory=Counter)
    # The number of trials that asked for the key at least once.
    unknown_input_trial_counts: Counter[KnowledgeLookupKey] = field(
        default_factory=Counter
    )

    def add_trial(self, uses: KnowledgeUses) -> None:
        """Add the lookups of one trial, counting the trial once for each key it has."""
        self.row_use_counts.update(uses.row_use_counts)
        # keys() adds one per key, so this counts trials and not lookups.
        self.row_trial_counts.update(uses.row_use_counts.keys())
        self.unknown_input_counts.update(uses.unknown_input_counts)
        self.unknown_input_trial_counts.update(uses.unknown_input_counts.keys())


@dataclass(slots=True)
class KnowledgeUses:
    """Record of the lookups of one knowledge class over one trial, filled by `Catalog.lookup` for catalog rows and by the knowledge class itself for declarations and for a few counts of its own, e.g. a program name read without its version.

    A row is one row of a catalog or of a declaration, e.g. one harness result format. A key that a knowledge class counts itself need not be the key of a row, e.g. `("pip", "any subcommand", "", "")` of `NetworkRequestKnowledge.may_program_fetch` or `("python3.11", "python")` under `names_read_without_version`.
    """

    # How often each row answered a lookup.
    row_use_counts: Counter[KnowledgeLookupKey] = field(default_factory=Counter)
    # How often a lookup found no row, by the key that was asked.
    unknown_input_counts: Counter[KnowledgeLookupKey] = field(default_factory=Counter)
