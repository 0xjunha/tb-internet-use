"""Test `analysis/list_missing_readings.py` on made-up readings and report files."""

import json
import sys

from analysis_modules import analysis_module

list_missing_readings = analysis_module("list_missing_readings")
READINGS = [
    {
        "trial_id": "t1",
        "reader_index": 0,
        "reading_group": "g",
        "label": "a t1 reader 0",
    },
    {
        "trial_id": "t1",
        "reader_index": 1,
        "reading_group": "g",
        "label": "a t1 reader 1",
    },
    {
        "trial_id": "t2",
        "reader_index": 0,
        "reading_group": "h",
        "label": "b t2 reader 0",
    },
]
TASK_BY_TRIAL = {"t1": "a", "t2": "b"}


def test_a_reading_without_its_report_file_is_missing_and_a_task_limits_the_list():
    report_names = {"t1_0.json", "t9_0.json"}

    missing = list_missing_readings.missing_readings_of(
        READINGS, report_names, TASK_BY_TRIAL
    )
    of_task = list_missing_readings.missing_readings_of(
        READINGS, report_names, TASK_BY_TRIAL, task="b"
    )

    assert [r["label"] for r in missing] == ["a t1 reader 1", "b t2 reader 0"]
    assert [r["label"] for r in of_task] == ["b t2 reader 0"]


def test_main_prints_the_labels_as_json_and_the_counts_apart(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "readings.json").write_text(json.dumps(READINGS))
    (tmp_path / "picked_trials.csv").write_text("trial_id,task\nt1,a\nt2,b\n")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "t2_0.json").write_text("{}")
    monkeypatch.setattr(sys, "argv", ["list_missing_readings.py", str(tmp_path)])

    list_missing_readings.main()

    output = capsys.readouterr()
    assert json.loads(output.out) == ["a t1 reader 0", "a t1 reader 1"]
    assert "a g 2" in output.err
