"""Tests for parse/program/catalog_rows.py, driven by the committed program catalog."""

import pytest

from tb_internet_use.parse.program import program_catalog
from tb_internet_use.parse.program.catalog_rows import (
    last_program_words,
    matched_catalog_row,
    matched_catalog_rows,
)
from tb_internet_use.parse.program.model import ProgramCatalogRow

ALL_ROWS = [row for rows in program_catalog().values() for row in rows]


@pytest.mark.parametrize(
    "row",
    ALL_ROWS,
    ids=[f"{r.program_name} {' '.join(r.subcommand_words)}" for r in ALL_ROWS],
)
def test_every_catalog_row_matches_a_command_of_its_own(row: ProgramCatalogRow):
    words = (row.program_name, *row.subcommand_words, "x")
    matched = matched_catalog_row(words)
    assert matched is not None
    assert matched.row == row


def test_rows_of_programs_that_run_the_next_program_come_first():
    rows = matched_catalog_rows(("npx", "-y", "playwright@1.49", "install", "x"))
    assert [(m.program_name, m.row.subcommand_words) for m in rows] == [
        ("npx", ()),
        ("playwright", ("install",)),
    ]
    assert rows[0].next_program_words == ("playwright@1.49", "install", "x")


def test_options_after_the_next_program_are_not_its_runners():
    (npx, *_) = matched_catalog_rows(("npx", "-y", "tsc", "--version"))
    assert npx.parsed_arguments.options == (("-y", None),)


@pytest.mark.parametrize(
    ("words", "last_words"),
    [
        ("npx tsx get.ts", "tsx get.ts"),
        ("uv run python get.py", "python get.py"),
        ("uv run python -m pip install x", "pip install x"),
        ("npx", "npx"),
        ("python get.py", "python get.py"),
    ],
)
def test_last_program_words(words: str, last_words: str):
    assert last_program_words(tuple(words.split())) == tuple(last_words.split())
