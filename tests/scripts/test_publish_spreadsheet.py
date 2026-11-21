"""Test how `publish_spreadsheet.py` names the published file and reads back the checks from Google Sheets."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import script_module

publish_spreadsheet = script_module("publish_spreadsheet")

_HEADER = ["Check", "Left", "Right", "Holds", "How"]


class _FakeDriveFiles:
    """Drive `files()` that records each request and answers it with a made-up file."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def update(self, **arguments: Any) -> _FakeDriveFiles:
        self.requests.append(("update", arguments))
        return self

    def create(self, **arguments: Any) -> _FakeDriveFiles:
        self.requests.append(("create", arguments))
        return self

    def execute(self) -> dict[str, str]:
        return {"id": "f1", "webViewLink": "https://docs.google.com/spreadsheets/d/f1"}


@pytest.mark.parametrize(
    ("values", "all_checks_hold_value", "check_count", "failing_checks", "is_passed"),
    [
        pytest.param(
            [
                ["Method & checks"],
                ["All checks hold", True],
                ["Formulas against the counts of Python"],
                _HEADER,
                ["Overview: cells that differ", 0, 0, True, "117 formula cells"],
                ["Sums and order"],
                _HEADER,
                ["Tasks: cells that differ", 0, 0, True],
            ],
            True,
            2,
            [],
            True,
            id="every check holds",
        ),
        pytest.param(
            [
                ["All checks hold", True],
                _HEADER,
                ["Overview: cells that differ", 0, 0, True],
                ["Tasks: cells that differ", 3, 0],
            ],
            True,
            2,
            ["Tasks: cells that differ"],
            False,
            id="a check whose cell is empty, which AND would skip",
        ),
        pytest.param(
            [
                ["All checks hold", False],
                _HEADER,
                ["Overview: cells that differ", 1, 0, False],
            ],
            False,
            1,
            ["Overview: cells that differ"],
            False,
            id="a check does not hold",
        ),
        pytest.param(
            [
                ["All checks hold", "#NAME?"],
                _HEADER,
                ["Registries and hosts: cells that differ", "#NAME?", 0, "#NAME?"],
            ],
            "#NAME?",
            1,
            ["Registries and hosts: cells that differ"],
            False,
            id="a formula Google Sheets could not compute",
        ),
        pytest.param(
            [
                ["All checks hold", "#NAME?"],
                _HEADER,
                ["Tasks: cells that differ", 0, 0, True],
            ],
            "#NAME?",
            1,
            [],
            False,
            id="every check holds but the cell of all checks is not true",
        ),
    ],
)
def test_reads_the_cell_of_all_checks_and_the_checks_that_are_not_true(
    values: list[list[object]],
    all_checks_hold_value: object,
    check_count: int,
    failing_checks: list[str],
    is_passed: bool,
):
    check_read_back = publish_spreadsheet.check_read_back_of(values)

    assert (
        check_read_back.all_checks_hold_value,
        check_read_back.check_count,
        check_read_back.failing_checks,
        check_read_back.is_passed(),
    ) == (all_checks_hold_value, check_count, failing_checks, is_passed)


def test_rows_after_the_checks_are_not_checks():
    check_read_back = publish_spreadsheet.check_read_back_of(
        [
            _HEADER,
            ["Tasks: cells that differ", 0, 0, True],
            [],
            ["Terms"],
            ["Lower bound", "Trials whose trajectory confirms it"],
            ["Premises of comparing tasks"],
            ["3-0-0", 74, 60, 60, 0],
        ]
    )

    assert (check_read_back.check_count, check_read_back.failing_checks) == (1, [])


@pytest.mark.parametrize(
    ("published_file_id", "request_name", "expected_body"),
    [
        pytest.param(
            "f1",
            "update",
            {"name": "Terminal-Bench 4.1 Internet Use"},
            id="replaces the content and the name of the published file",
        ),
        pytest.param(
            None,
            "create",
            {
                "name": "Terminal-Bench 4.1 Internet Use",
                "mimeType": "application/vnd.google-apps.spreadsheet",
            },
            id="creates the file under the name",
        ),
    ],
)
def test_publishing_sets_the_spreadsheet_title_as_the_file_name(
    published_file_id: str | None,
    request_name: str,
    expected_body: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    drive_files = _FakeDriveFiles()
    drive = SimpleNamespace(files=lambda: drive_files)
    monkeypatch.setattr(publish_spreadsheet, "_build_service", lambda *_: drive)
    monkeypatch.setattr(
        publish_spreadsheet, "_read_published_file_id", lambda: published_file_id
    )
    monkeypatch.setattr(
        publish_spreadsheet, "PUBLISHED_SPREADSHEET_ID_PATH", tmp_path / "id.json"
    )
    spreadsheet_path = tmp_path / "internet_use.xlsx"
    spreadsheet_path.write_bytes(b"xlsx")

    publish_spreadsheet.publish_spreadsheet(spreadsheet_path)

    [(name, arguments)] = drive_files.requests
    assert (name, arguments["body"]) == (request_name, expected_body)
