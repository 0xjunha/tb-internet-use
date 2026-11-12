"""Tests for program/catalog_loader.py."""

from pathlib import Path

import pytest

from tb_internet_use.program.catalog_loader import load_program_catalog, program_catalog
from tb_internet_use.program.model import AskedPackagesSource

HEADER = (
    "program,subcommand,command_count,trial_count,reads_file_arguments,request_kind,"
    "printing_programs,exit_zero_means,fetches_only_to_run_or_build,asked_packages_source,"
    "asks_for_no_content,prints_response_body,runs_next_program,reviewed,note"
)
UV_PIP_INSTALL = "uv,pip install,,,no,package,uv pip,nothing,no,targets,no,no,no,,"
UV_PIP = "uv,pip,,,no,package,uv pip,nothing,no,targets,no,no,no,,"
CAT = "cat,,,,yes,,,,,,,,,,"


def _catalog(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / "catalog.csv"
    path.write_text("\n".join([HEADER, *rows]) + "\n")
    return path


def test_labels_of_a_program_come_longest_subcommand_first(tmp_path: Path):
    catalog = load_program_catalog(_catalog(tmp_path, UV_PIP, UV_PIP_INSTALL, CAT))
    assert [label.subcommand_words for label in catalog["uv"]] == [
        ("pip", "install"),
        ("pip",),
    ]
    rule = catalog["uv"][0].request_rule
    assert (
        rule is not None and rule.asked_packages_source == AskedPackagesSource.TARGETS
    )
    assert (
        catalog["cat"][0].reads_file_arguments
        and catalog["cat"][0].request_rule is None
    )


@pytest.mark.parametrize(
    "rows",
    [
        (UV_PIP, UV_PIP),  # repeated program and subcommand
        (
            "uv,pip,,,no,package,uv pip,nothing,no,targets,maybe,no,no,,",
        ),  # not yes or no
        ("uv,pip,,,no,packages,uv pip,nothing,no,targets,no,no,no,,",),  # unknown kind
        (
            "uv,pip,,,no,package,uv pipx,nothing,no,targets,no,no,no,,",
        ),  # unknown printing program
        (
            "uv,pip,,,no,package,uv pip,nothing,no,,no,no,no,,",
        ),  # missing asked_packages_source
        ("uv,pip,,,no,,uv pip,,,,,,,,",),  # request labels without a kind
        ("git,clone,,,yes,,,,,,,,,,",),  # reads_file_arguments on a subcommand row
    ],
)
def test_bad_rows_raise(tmp_path: Path, rows: tuple[str, ...]):
    with pytest.raises(ValueError):
        load_program_catalog(_catalog(tmp_path, *rows))


def test_committed_catalog_loads():
    assert program_catalog()
