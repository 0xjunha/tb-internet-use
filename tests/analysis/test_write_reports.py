"""Test `analysis/write_reports.py` on a made-up list that the reading workflow returned."""

import json

from analysis_modules import analysis_module

write_reports = analysis_module("write_reports")


def workflow_result(label, trial_id, reader_index, report):
    return {
        "label": label,
        "trial_id": trial_id,
        "reader_index": reader_index,
        "reading_group": "requested_and_solved",
        "report": report,
    }


def test_each_report_gets_its_file_and_a_null_report_only_its_label(tmp_path):
    workflow_results = [
        workflow_result("a 0", "t1", 0, {"notes": "first"}),
        workflow_result("a 1", "t1", 1, {"notes": "second"}),
        workflow_result("b 0", "t2", 0, None),
    ]

    failed_labels = write_reports.write_reports(workflow_results, tmp_path / "reports")

    assert failed_labels == ["b 0"]
    assert sorted(path.name for path in (tmp_path / "reports").iterdir()) == [
        "t1_0.json",
        "t1_1.json",
    ]
    assert json.loads((tmp_path / "reports" / "t1_1.json").read_text()) == {
        "notes": "second"
    }


def test_a_journal_gives_the_report_of_each_started_agent_and_none_without_a_result():
    readings = [
        {"label": label, "trial_id": trial_id, "reader_index": 0, "reading_group": "g"}
        for label, trial_id in (("a 0", "t1"), ("b 0", "t2"), ("c 0", "t3"))
    ]
    first_journal = [
        {"type": "launched"},
        {"type": "started", "agentId": "x1", "label": "a 0"},
        {"type": "started", "agentId": "x2", "label": "b 0"},
        {"type": "result", "agentId": "x1", "result": {"notes": "a"}},
    ]
    # A later run that read b again and c, with an agent id that the first run also used.
    second_journal = [
        {"type": "started", "agentId": "x1", "label": "b 0"},
        {"type": "started", "agentId": "x3", "label": "c 0"},
        {"type": "result", "agentId": "x1", "result": {"notes": "b"}},
    ]

    workflow_results = write_reports.workflow_results_of_journals(
        [first_journal, second_journal], readings
    )

    assert [(r["label"], r["trial_id"], r["report"]) for r in workflow_results] == [
        ("a 0", "t1", {"notes": "a"}),
        ("b 0", "t2", {"notes": "b"}),
        ("c 0", "t3", None),
    ]
