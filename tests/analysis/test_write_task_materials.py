"""Test the task file of `analysis/write_task_materials.py` on made-up trials, reports, flags and pipeline rows."""

from analysis_modules import analysis_module
from made_up_reports import (
    made_up_effect,
    made_up_failed_request,
    made_up_request_group,
)

write_task_materials = analysis_module("write_task_materials")
report_files = analysis_module("report_files")
pipeline_rows = analysis_module("pipeline_rows")


def trial_facts(trial_id, reward):
    return pipeline_rows.TrialFacts(trial_id, "a", "codex", "m", reward, True)


def request_row(trial_id, host_names, category="content_fetch", is_internet_use="true"):
    return pipeline_rows.RequestRow(
        trial_id,
        "main",
        4,
        "curl",
        "",
        host_names,
        category,
        is_internet_use,
        "task_environment",
        "received",
        "lower_and_upper",
    )


def report_of(request_groups):
    return {
        "request_groups": request_groups,
        "graded_answer_reach": "some",
        "graded_answer_reach_detail": "The structure file.",
        "failed_requests": [made_up_failed_request()],
        "online_rule": {
            "treatment": "did_not_mention",
            "reason_given": "",
            "step_ids": [],
        },
        "request_rows_disputed": [],
        "notes": "Nothing else.",
    }


def material_text():
    no_effect = made_up_request_group(
        steps=[(4, "success_only")], effects=[made_up_effect("none_shown")]
    )
    trial = report_files.TrialReports(
        "t1",
        "a",
        "codex",
        "m",
        "1.0",
        "requested_and_solved",
        ((0, report_of([made_up_request_group()])), (1, report_of([no_effect]))),
    )
    picked_rows = [
        {
            "trial_id": "t1",
            "harness": "codex",
            "model": "m",
            "reward": "1.0",
            "reading_group": "requested_and_solved",
        }
    ]
    flag_rows = [
        {
            "trial_id": "t1",
            "reader_index": "1",
            "flag": "notes_too_long",
            "where": "notes",
            "detail": "151 words",
        }
    ]
    # t1 and t2 ask files.a.org, t3 failed, and a request to a local host is left out.
    task_requests = write_task_materials.TaskRequests(
        [trial_facts("t1", 1.0), trial_facts("t2", 1.0), trial_facts("t3", 0.0)],
        {
            "t1": [
                request_row("t1", "files.a.org"),
                request_row("t1", "db", is_internet_use="false"),
            ],
            "t2": [request_row("t2", "files.a.org")],
            "t3": [request_row("t3", "pypi.org", "package")],
        },
    )
    return write_task_materials.task_material_text_of(
        "a", picked_rows, [trial], flag_rows, task_requests
    )


def test_the_file_marks_reader_text_as_data_and_shows_where_readers_differ():
    text = material_text()

    assert text.index(write_task_materials.READER_TEXT_NOTICE) < text.index(
        "### t1 reader 0"
    )
    assert (
        "- t1 trial_use_summary: reader 0 `graded_answer_made_or_changed`, reader 1 `no_effect_on_graded_answer_shown`"
        in text
    )
    assert "| t1 | 1 | notes_too_long | notes | 151 words |" in text


def test_the_host_table_counts_trials_and_confirmed_non_package_rows_of_all_trials_of_the_task():
    text = material_text()

    assert (
        "all 3 readable trials of the task, not only the read ones. 2 were solved, 2 of those with a confirmed non-package request."
        in text
    )
    assert (
        "| files.a.org | content_fetch | task_environment | received | 2 | 2 |" in text
    )
    assert "| pypi.org | package | task_environment | received | 1 | 0 |" in text
    assert "| db |" not in text


def test_a_report_shows_its_groups_effects_failed_requests_and_notes():
    text = material_text()

    assert "- request steps: 4 wanted_content, 5 nothing" in text
    assert (
        "- effect entered_answer at steps 9, tests_grade_part yes, answer_part: The positions. The value went into the answer."
        in text
    )
    assert (
        "failed_requests:\n- step_ids: 6; hosts: a.org; failure_shown: timeout;" in text
    )
    assert "graded_answer_reach: some. The structure file." in text
    assert "notes: Nothing else." in text
