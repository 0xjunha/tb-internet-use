"""Test the lines of `Registries and hosts` on request rows that the made-up run does not hold."""

from pathlib import Path

from conftest import (
    LOWER_AND_UPPER,
    TASK_0_4,
    TASK_A_4,
    UPPER_ONLY,
    made_up_request_row,
    made_up_trial_row,
    script_module,
    write_made_up_run,
)

from tb_internet_use.export.model import NetworkRequestCategory

spreadsheet_python_counts = script_module("spreadsheet_python_counts")
spreadsheet_registries_and_hosts_tab = script_module(
    "spreadsheet_registries_and_hosts_tab"
)

CONNECTIVITY_CHECK = NetworkRequestCategory.CONNECTIVITY_CHECK
CONTENT_FETCH = NetworkRequestCategory.CONTENT_FETCH
OTHER_WEB = NetworkRequestCategory.OTHER_WEB
PACKAGE = NetworkRequestCategory.PACKAGE


def test_lines_leave_out_connectivity_checks_and_join_a_registry_host_with_its_registry(
    tmp_path: Path,
):
    trial_rows = [
        made_up_trial_row(trial_id, task, "codex", 1.0, LOWER_AND_UPPER, UPPER_ONLY)
        for trial_id, task in (("t1", TASK_A_4), ("t2", TASK_A_4), ("t3", TASK_0_4))
    ]
    request_rows = [
        made_up_request_row(
            "t1",
            0,
            PACKAGE,
            LOWER_AND_UPPER,
            UPPER_ONLY,
            target="requests",
            package_registry="pypi",
        ),
        # A URL of the host of a registry counts in the line of that registry.
        made_up_request_row(
            "t2",
            0,
            OTHER_WEB,
            LOWER_AND_UPPER,
            UPPER_ONLY,
            made_by="curl",
            target="https://pypi.org/simple/requests/",
            host_names="pypi.org",
            host_service="package_registry",
        ),
        # Only a connectivity check, so the trial and its host are in no line.
        made_up_request_row(
            "t3",
            0,
            CONNECTIVITY_CHECK,
            LOWER_AND_UPPER,
            UPPER_ONLY,
            made_by="curl",
            target="https://www.google.com",
            host_names="www.google.com",
            host_service="search_engine",
        ),
        # One row with two hosts counts under each.
        made_up_request_row(
            "t1",
            1,
            CONTENT_FETCH,
            LOWER_AND_UPPER,
            UPPER_ONLY,
            made_by="curl",
            host_names="github.com b.org",
            host_service="code_hosting unknown",
        ),
        # An upper-bound row counts nowhere.
        made_up_request_row(
            "t3",
            1,
            CONTENT_FETCH,
            UPPER_ONLY,
            UPPER_ONLY,
            made_by="curl",
            host_names="github.com",
            host_service="code_hosting",
        ),
    ]
    row_files = spreadsheet_python_counts.RowFiles(
        write_made_up_run(tmp_path / "run", trial_rows, request_rows)
    )

    tab = spreadsheet_registries_and_hosts_tab.lay_out_registries_and_hosts_tab(
        row_files, spreadsheet_python_counts.count_spreadsheet_values(row_files)
    )

    assert tab.trial_ids == {"t1", "t2"}
    assert {
        row[0].value: (row[1].value, row[2].value)
        for row in tab.grid.rows
        if len(row) > 2 and isinstance(row[2].value, int)
    } == {
        "package_registry": (1, 2),
        "pypi": (1, 2),
        "code_hosting": (1, 1),
        "github.com": (1, 1),
        "unknown": (1, 1),
        "b.org": (1, 1),
    }
