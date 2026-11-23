"""Test the matching of failed requests, the comparison per request step and the agreement counts of `analysis/reader_agreement.py` on made-up reports."""

import csv
import json
import sys

from analysis_modules import analysis_module
from made_up_reports import (
    made_up_effect,
    made_up_failed_request,
    made_up_request_group,
)

reader_agreement = analysis_module("reader_agreement")
Match = reader_agreement.EntryMatch


def groups_of(*step_id_lists):
    return [{"request_step_ids": list(step_ids)} for step_ids in step_id_lists]


def test_groups_are_matched_one_to_one_by_most_shared_steps():
    first = groups_of([1, 2, 3], [10], [20])
    second = groups_of([3], [1, 2, 4], [30])

    assert reader_agreement.match_entries_by_steps(
        first, second, "request_step_ids"
    ) == [
        Match(0, 1, 2),
    ]


def test_a_group_matched_once_is_not_matched_again_and_the_next_best_pair_is_taken():
    # Both groups of the second reader share step 5 with the first group, and the second also shares step 9 with the other.
    first = groups_of([5, 6], [9])
    second = groups_of([5, 6, 7], [5, 9])

    assert reader_agreement.match_entries_by_steps(
        first, second, "request_step_ids"
    ) == [
        Match(0, 0, 2),
        Match(1, 1, 1),
    ]


def test_among_equal_shared_steps_the_pair_with_the_larger_share_of_overlap_wins():
    first = groups_of([1])
    second = groups_of([1, 2, 3], [1])

    assert reader_agreement.match_entries_by_steps(
        first, second, "request_step_ids"
    ) == [Match(0, 1, 1)]


def test_cannot_tell_agrees_only_with_itself_and_is_counted_apart():
    agreement = reader_agreement.KeyAgreement()
    for first_value, second_value in (
        ("cannot_tell", "cannot_tell"),
        ("used_to_make_answer", "used_to_make_answer"),
        ("cannot_tell", "not_used"),
        ("not_used", "used_to_make_answer"),
    ):
        agreement.add(first_value, second_value)

    assert agreement == reader_agreement.KeyAgreement(
        agree=2, disagree=2, agree_on_cannot_tell=1, disagree_with_one_cannot_tell=1
    )


def write_two_reports(tmp_path, reports):
    (tmp_path / "reports").mkdir()
    for reader_index, report in enumerate(reports):
        (tmp_path / "reports" / f"t_{reader_index}.json").write_text(json.dumps(report))
    (tmp_path / "readings.json").write_text(
        json.dumps([{"trial_id": "t", "reader_index": i} for i in range(len(reports))])
    )


def report_of(request_groups, failed_requests=(), disputed=()):
    return {
        "request_groups": request_groups,
        "failed_requests": list(failed_requests),
        "online_rule": {
            "treatment": "did_not_mention",
            "reason_given": "",
            "step_ids": [],
        },
        "request_rows_disputed": list(disputed),
        "notes": "",
    }


def rows_of(path):
    with path.open() as csv_file:
        return list(csv.DictReader(csv_file))


def test_main_compares_each_request_step_whatever_groups_the_readers_formed(
    tmp_path, monkeypatch
):
    # Reader 0 puts steps 4 and 5 in one group, reader 1 in two, and only reader 0 lists step 8.
    first = report_of(
        [
            made_up_request_group(steps=[(4, "wanted_content"), (5, "nothing")]),
            made_up_request_group(
                steps=[(8, "not_recorded")], effects=[made_up_effect("none_shown")]
            ),
        ],
        failed_requests=[made_up_failed_request([5, 6])],
        disputed=[{"step_id": 9, "target": "", "dispute": "never_sent", "reason": ""}],
    )
    second = report_of(
        [
            made_up_request_group(steps=[(4, "wanted_content")]),
            made_up_request_group(
                steps=[(5, "nothing")],
                prior_candidate="in_file_or_output",
                effects=[made_up_effect("none_shown")],
            ),
        ],
        failed_requests=[
            made_up_failed_request([6], failure_shown="connection_or_dns")
        ],
    )
    write_two_reports(tmp_path, [first, second])
    monkeypatch.setattr(sys, "argv", ["reader_agreement.py", str(tmp_path)])

    reader_agreement.main()

    agreement = {row["key"]: row for row in rows_of(tmp_path / "reader_agreement.csv")}
    assert (
        agreement["response"]["agree"],
        agreement["response"]["listed_by_one_reader_only"],
    ) == ("2", "1")
    assert agreement["prior_candidate"]["disagree"] == "1"
    assert agreement["step_label"]["agree"] == "2"
    assert agreement["failed_requests.failure_shown"]["disagree"] == "1"
    assert agreement["trial_use_summary"]["agree"] == "1"
    assert agreement["request_rows_disputed"]["disagree"] == "1"
    assert agreement["effects"]["counted_over"] == "trials"
    # Reader 1 lists step 5 alone in its own group, still `nothing`, and steps 4 and 5 keep their merged labels.
    assert agreement["merged_step_label"]["agree"] == "2"
    for key in ("first_request_start", "content_kinds_reaching_graded_answer"):
        assert agreement[key]["agree"] == "1"
    confusion = {
        (row["reader_0_step_label"], row["reader_1_step_label"]): row["steps"]
        for row in rows_of(tmp_path / "step_label_confusion.csv")
    }
    assert confusion == {
        ("entered_answer", "entered_answer"): "1",
        ("not_received", "not_received"): "1",
        ("not_recorded", "not_listed"): "1",
    }
    (trial,) = rows_of(tmp_path / "trial_comparisons.csv")
    assert (trial["group_count_0"], trial["group_count_1"]) == ("2", "2")
    assert trial["first_request_start_0"] == "from_the_start"
    assert trial["content_kinds_reaching_graded_answer_1"] == "data"
    assert trial["effects_0"] == "entered_answer:yes none_shown:yes"
    assert trial["request_rows_disputed_0"] == "9  never_sent"


def test_two_readers_agree_on_a_step_in_several_groups_when_its_sets_of_facts_are_equal():
    entered = made_up_request_group(steps=[(5, "wanted_content")])
    no_effect = made_up_request_group(
        steps=[(5, "success_only")], effects=[made_up_effect("none_shown")]
    )
    # Reader 1 gives the same two groups in the other order, reader 2 only one of them.
    readers = [
        report_of([entered, no_effect]),
        report_of([no_effect, entered]),
        report_of([entered]),
    ]

    facts = [reader_agreement.step_facts_of(report)[5] for report in readers]

    assert facts[0]["step_label"] == {"entered_answer", "received_no_effect_shown"}
    assert facts[0]["response"] == {"wanted_content", "success_only"}
    assert facts[0] == facts[1]
    assert facts[0]["step_label"] != facts[2]["step_label"]
