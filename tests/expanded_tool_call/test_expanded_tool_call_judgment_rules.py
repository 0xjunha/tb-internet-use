"""Tests for expanded_tool_call/judgment_rules.py."""

from collections import Counter
from collections.abc import Callable
from functools import partial

import pytest

from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_calls_of_other_trajectory_as_not_linked,
    treat_command_under_run_condition_as_run,
    treat_copy_with_two_arguments_as_unknown_content,
    treat_deleted_file_as_never_written,
    treat_edit_of_text_not_found_once_as_unknown_content,
    treat_file_not_named_by_command_words_as_untouched,
    treat_file_without_interpreter_line_as_of_unknown_language,
    treat_first_poll_that_saw_end_as_command_text_status,
    treat_input_of_key_presses_only_as_no_text,
    treat_outer_assignment_as_not_visible_in_new_shell,
    treat_path_that_ends_another_as_same_file,
    treat_path_that_fits_several_written_files_as_unknown_text,
    treat_poll_of_handle_that_several_calls_started_as_not_linked,
    treat_poll_result_of_several_commands_as_showing_none,
    treat_read_of_output_path_of_several_calls_as_showing_each,
    treat_script_poll_step_naming_no_handle_as_polling_none,
    treat_script_step_output_as_not_shown_in_call_result,
    treat_tool_call_not_marked_not_run_as_maybe_run,
    treat_typed_text_as_of_unknown_language,
    treat_use_after_later_overwrite_as_use_of_later_write,
    treat_use_of_path_that_fits_several_written_files_as_use_of_none,
    treat_values_outside_their_for_loop_as_one_of_them,
    treat_word_with_expansion_as_start_of_unread_words,
)

# (rule, the rule with its arguments before `use_counts`) for the rules that `expand_ran_texts` asks.
EXPAND_RAN_TEXTS_RULES: list[tuple[Callable[..., bool], Callable[..., bool]]] = [
    (rule, partial(rule, *arguments))
    for rule, arguments in [
        (treat_path_that_ends_another_as_same_file, ("fetch.sh", "/app/fetch.sh")),
        (treat_path_that_fits_several_written_files_as_unknown_text, ("fetch.sh",)),
        (treat_edit_of_text_not_found_once_as_unknown_content, ("f.sh",)),
        (treat_input_of_key_presses_only_as_no_text, ("\n",)),
        (treat_use_after_later_overwrite_as_use_of_later_write, ("log",)),
        (treat_tool_call_not_marked_not_run_as_maybe_run, ()),
        (treat_typed_text_as_of_unknown_language, ()),
        (treat_command_under_run_condition_as_run, ()),
        (treat_use_of_path_that_fits_several_written_files_as_use_of_none, ("log",)),
        (treat_file_not_named_by_command_words_as_untouched, ("*.sh",)),
        (treat_copy_with_two_arguments_as_unknown_content, ()),
        (treat_outer_assignment_as_not_visible_in_new_shell, ()),
        (treat_deleted_file_as_never_written, ("f.sh",)),
        (
            treat_file_without_interpreter_line_as_of_unknown_language,
            ("./get.py",),
        ),
    ]
]


def test_values_outside_their_for_loop_are_read_as_one_of_them_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_values_outside_their_for_loop_as_one_of_them(
        "A", use_counts=use_counts
    )
    assert use_counts == Counter(
        {"treat_values_outside_their_for_loop_as_one_of_them": 1}
    )


def test_word_with_an_expansion_starts_the_unread_words_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_word_with_expansion_as_start_of_unread_words(
        "$OPTS", use_counts=use_counts
    )
    assert use_counts == Counter(
        {"treat_word_with_expansion_as_start_of_unread_words": 1}
    )


def test_poll_of_a_handle_that_several_calls_started_is_not_linked_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_poll_of_handle_that_several_calls_started_as_not_linked(
        use_counts=use_counts
    )
    assert use_counts == Counter(
        {"treat_poll_of_handle_that_several_calls_started_as_not_linked": 1}
    )


def test_calls_of_other_trajectory_are_not_linked_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_calls_of_other_trajectory_as_not_linked(use_counts=use_counts)
    assert use_counts == Counter({"treat_calls_of_other_trajectory_as_not_linked": 1})


def test_script_poll_step_naming_no_handle_reads_no_handle_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_script_poll_step_naming_no_handle_as_polling_none(
        use_counts=use_counts
    )
    assert use_counts == Counter(
        {"treat_script_poll_step_naming_no_handle_as_polling_none": 1}
    )


def test_first_poll_that_saw_the_end_gives_the_command_text_status_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_first_poll_that_saw_end_as_command_text_status(use_counts=use_counts)
    assert use_counts == Counter(
        {"treat_first_poll_that_saw_end_as_command_text_status": 1}
    )


@pytest.mark.parametrize(
    ("rule", "asked_rule"),
    EXPAND_RAN_TEXTS_RULES,
    ids=[rule.__name__ for rule, _ in EXPAND_RAN_TEXTS_RULES],
)
def test_rule_of_expand_ran_texts_takes_the_choice_it_names_and_is_counted(
    rule: Callable[..., bool], asked_rule: Callable[..., bool]
):
    use_counts: Counter[str] = Counter()

    assert asked_rule(use_counts=use_counts) is True
    assert use_counts == Counter({rule.__name__: 1})


def test_script_step_output_is_not_shown_in_the_call_result_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_script_step_output_as_not_shown_in_call_result(
        0, use_counts=use_counts
    )
    assert use_counts == Counter(
        {"treat_script_step_output_as_not_shown_in_call_result": 1}
    )


def test_poll_result_of_several_commands_shows_none_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_poll_result_of_several_commands_as_showing_none(use_counts=use_counts)
    assert use_counts == Counter(
        {"treat_poll_result_of_several_commands_as_showing_none": 1}
    )


def test_read_of_output_path_of_several_calls_shows_each_and_counted():
    use_counts: Counter[str] = Counter()

    assert treat_read_of_output_path_of_several_calls_as_showing_each(
        use_counts=use_counts
    )
    assert use_counts == Counter(
        {"treat_read_of_output_path_of_several_calls_as_showing_each": 1}
    )
