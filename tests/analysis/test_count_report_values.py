"""Test the counts of `analysis/count_report_values.py` on made-up trials with one or two reports."""

from analysis_modules import analysis_module
from made_up_reports import (
    made_up_effect,
    made_up_failed_request,
    made_up_request_group,
)

count_report_values = analysis_module("count_report_values")
report_files = analysis_module("report_files")


def made_up_trial(trial_id, task, reports, reading_group="requested_and_solved"):
    return report_files.TrialReports(
        trial_id=trial_id,
        task=task,
        harness="codex",
        model="m",
        reward="1.0",
        reading_group=reading_group,
        reports=tuple(enumerate(reports)),
    )


def report_of(request_groups, failed_requests=(), disputed=()):
    return {
        "request_groups": request_groups,
        "failed_requests": list(failed_requests),
        "request_rows_disputed": list(disputed),
        "notes": "",
    }


ENTERED = made_up_request_group()
NO_EFFECT = made_up_request_group(
    steps=[(4, "success_only")], effects=[made_up_effect("none_shown")]
)
# Trial t1 is read twice, its readers differ, and t2 of another task is read once.
TRIALS = [
    made_up_trial("t1", "a", [report_of([ENTERED]), report_of([NO_EFFECT])]),
    made_up_trial("t2", "b", [report_of([ENTERED])]),
    made_up_trial(
        "t3",
        "b",
        [{"failed_requests": [], "request_rows_disputed": [], "notes": ""}],
        "not_received_in_read_tasks",
    ),
]


def rows_by_value(rows, breakdown="all", breakdown_value="all"):
    return {
        row[4]: row[5:]
        for row in rows
        if row[2] == breakdown and row[3] == breakdown_value
    }


def test_a_trial_counts_for_reader_0_both_and_either_and_a_trial_without_groups_not_at_all():
    rows = count_report_values.trial_counts_of(
        TRIALS,
        "summary",
        count_report_values._groups_part(
            lambda groups: [count_report_values.trial_use_summary_of(groups)]
        ),
    )

    assert rows_by_value(rows) == {
        "graded_answer_made_or_changed": (2, 1, 2, ""),
        "no_effect_on_graded_answer_shown": (0, 0, 1, ""),
    }
    assert rows_by_value(rows, "task", "b") == {
        "graded_answer_made_or_changed": (1, 1, 1, "")
    }


def test_failed_requests_are_counted_as_items_of_reader_0_and_of_all_readings():
    trial = made_up_trial(
        "t1",
        "a",
        [
            report_of(
                [],
                [
                    made_up_failed_request(),
                    made_up_failed_request(failure_shown="nothing"),
                ],
            ),
            report_of([], [made_up_failed_request()]),
        ],
    )

    rows = count_report_values.item_counts_of(
        [trial],
        "failure_shown",
        "failed request",
        count_report_values._items_of("failed_requests", lambda e: e["failure_shown"]),
    )

    assert rows_by_value(rows) == {"nothing": (1, "", "", 1), "timeout": (1, "", "", 2)}


def test_a_row_disputed_by_both_readers_is_told_from_one_disputed_by_one():
    def disputed(step_id):
        return {"step_id": step_id, "target": "", "dispute": "never_sent", "reason": ""}

    trial = made_up_trial(
        "t1",
        "a",
        [
            report_of([], disputed=[disputed(3), disputed(4)]),
            report_of([], disputed=[disputed(3)]),
        ],
    )

    rows = count_report_values.disputed_row_agreement_counts_of([trial])

    assert rows_by_value(rows) == {
        "both_readers": ("", "", "", 1),
        "reader_0_only": ("", "", "", 1),
    }


def test_effects_and_content_kinds_count_only_groups_with_a_received_step():
    unrecorded = made_up_request_group(
        steps=[(4, "not_recorded")], content_kinds=["documentation"]
    )
    tables = count_report_values.count_tables_of(
        [made_up_trial("t1", "a", [report_of([unrecorded, NO_EFFECT])])]
    )

    assert rows_by_value(tables["effect_counts.csv"]) == {
        "none_shown yes": (1, 1, 1, "")
    }
    assert set(rows_by_value(tables["content_kind_counts.csv"])) == {"data"}
