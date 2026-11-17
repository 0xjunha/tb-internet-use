"""Tests for knowledge/catalog.py, with made-up rows."""

from collections import Counter
from pathlib import Path

import pytest

from tb_internet_use.knowledge.catalog import (
    Catalog,
    KnowledgeUses,
    KnowledgeUsesTotal,
    load_catalog,
)

CATALOG = Catalog("tools.csv", {("h", "known"): "row of known"})


def _write_csv(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "tools.csv"
    path.write_text("harness,tool,label\n" + rows)
    return path


def test_lookup_of_a_key_with_a_row_returns_the_row_and_records_a_use():
    uses = KnowledgeUses()

    assert CATALOG.lookup(("h", "known"), uses) == "row of known"
    assert CATALOG.lookup(("h", "known"), uses) == "row of known"
    assert uses == KnowledgeUses(
        row_use_counts=Counter({("tools.csv", ("h", "known")): 2})
    )


def test_lookup_of_a_key_without_a_row_returns_none_and_records_a_miss():
    uses = KnowledgeUses()

    assert CATALOG.lookup(("h", "new"), uses) is None
    assert uses == KnowledgeUses(
        unknown_input_counts=Counter({("tools.csv", ("h", "new")): 1})
    )


def test_load_catalog_keys_each_row_by_its_key_columns_in_file_order(tmp_path):
    path = _write_csv(tmp_path, "h,b,second\nh,a,first\n")

    catalog = load_catalog(
        path,
        key_columns=("harness", "tool"),
        row_from_columns=lambda columns: columns["label"].upper(),
    )

    assert catalog.file_name == "tools.csv"
    assert catalog.row_keys == (("h", "b"), ("h", "a"))
    assert catalog.lookup(("h", "a"), KnowledgeUses()) == "FIRST"


def test_load_catalog_rejects_two_rows_with_one_key_and_names_the_line(tmp_path):
    path = _write_csv(tmp_path, "h,a,first\nh,a,second\n")

    with pytest.raises(ValueError, match="two rows") as error:
        load_catalog(
            path,
            key_columns=("harness", "tool"),
            row_from_columns=lambda columns: columns["label"],
        )
    assert error.value.__notes__ == ["tools.csv line 3"]


def test_total_adds_the_lookups_of_trials_and_counts_each_trial_once_per_key():
    used, unknown = ("tools.csv", ("h", "known")), ("tools.csv", ("h", "new"))
    first_trial = KnowledgeUses(Counter({used: 3}), Counter({unknown: 2}))
    second_trial = KnowledgeUses(Counter({used: 1}))
    total = KnowledgeUsesTotal()

    total.add_trial(first_trial)
    total.add_trial(second_trial)

    assert total == KnowledgeUsesTotal(
        row_use_counts=Counter({used: 4}),
        row_trial_counts=Counter({used: 2}),
        unknown_input_counts=Counter({unknown: 2}),
        unknown_input_trial_counts=Counter({unknown: 1}),
    )
