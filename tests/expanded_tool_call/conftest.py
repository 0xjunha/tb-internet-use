"""Fixtures shared by the tests of the expanded_tool_call package, i.e. a folder of made-up program catalogs built from the rows that a test module names."""

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    CODE_RUNNERS_CSV,
    PROGRAM_BEHAVIORS_CSV,
    PROGRAM_OPTION_BEHAVIORS_CSV,
)

# The cells of a program row that a row of a module's `PROGRAM_BEHAVIOR_ROWS` does not give.
_PROGRAM_ROW_DEFAULTS = {
    "subcommand": "",
    "argument_role": "other",
    "first_argument_role": "same",
    "last_argument_role": "same",
    "stdin_role": "none",
    "visibility_of_piped_input": "",
    "gives_arguments_at_run_time": "no",
    "skips_assignment_words": "no",
    "options_end_at_first_argument": "no",
    "takes_one_letter_options_joined": "yes",
    "takes_non_option_dash_words_as_arguments": "",
    "runs_text_in_calling_shell": "no",
    "exits_with_exit_code_of_next_program": "no",
    "name_may_end_with_version": "no",
    "default_run_file": "none",
    "checked_against": "made up",
    "reviewed": "",
    "note": "",
}
# The cells of an option row that a row of a module's `PROGRAM_OPTION_BEHAVIOR_ROWS` does not give, i.e. an option without a value that changes nothing.
_OPTION_ROW_DEFAULTS = {
    "subcommand": "",
    "takes_value": "no",
    "value_role": "none",
    "argument_role_with_option": "unchanged",
    "first_argument_role_with_option": "unchanged",
    "last_argument_role_with_option": "unchanged",
    "changed_option_names": "none",
    "changed_option_value_role": "none",
    "gives_arguments_at_run_time": "no",
    "exits_with_exit_code_of_next_program_with_option": "unchanged",
    "next_program_end_words": "none",
    "checked_against": "made up",
    "reviewed": "",
    "note": "",
}

# The cells of a code runner row that a row of a module's `CODE_RUNNER_ROWS` does not give.
_CODE_RUNNER_ROW_DEFAULTS = {
    "ran_text_language": "shell",
    "checked_against": "made up",
    "reviewed": "",
    "note": "",
}


@pytest.fixture(scope="module")
def catalogs_dir(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """Write the program catalogs of the requesting test module into a new folder and give the folder.

    The module names its rows in `PROGRAM_BEHAVIOR_ROWS` and `PROGRAM_OPTION_BEHAVIOR_ROWS`, each with the cells that differ from the defaults here, so that a case does not change when the real catalog gains rows.
    The folder has the code runner rows of `CODE_RUNNER_ROWS` when the module has it, each with the cells that differ from the defaults here, and none otherwise.
    """
    catalogs_dir = tmp_path_factory.mktemp("catalogs")
    _write_rows(
        catalogs_dir / PROGRAM_BEHAVIORS_CSV,
        ["program_name", *_PROGRAM_ROW_DEFAULTS],
        _PROGRAM_ROW_DEFAULTS,
        request.module.PROGRAM_BEHAVIOR_ROWS,
    )
    _write_rows(
        catalogs_dir / PROGRAM_OPTION_BEHAVIORS_CSV,
        ["program_name", "option_name", *_OPTION_ROW_DEFAULTS],
        _OPTION_ROW_DEFAULTS,
        request.module.PROGRAM_OPTION_BEHAVIOR_ROWS,
    )
    _write_rows(
        catalogs_dir / CODE_RUNNERS_CSV,
        ["runner_kind", "runner", *_CODE_RUNNER_ROW_DEFAULTS],
        _CODE_RUNNER_ROW_DEFAULTS,
        getattr(request.module, "CODE_RUNNER_ROWS", []),
    )
    return catalogs_dir


def _write_rows(
    csv_path: Path,
    columns: list[str],
    defaults: Mapping[str, str],
    rows: Sequence[Mapping[str, str]],
) -> None:
    with csv_path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, columns)
        writer.writeheader()
        writer.writerows({**defaults, **row} for row in rows)
