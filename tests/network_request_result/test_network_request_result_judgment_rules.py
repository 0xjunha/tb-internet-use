"""Tests for network_request_result/judgment_rules.py, one table of each rule with a made-up situation, the value it gives and the name it is counted under, then the branches of the rules that take arguments."""

from collections import Counter
from collections.abc import Callable

import pytest

from tb_internet_use.network_request_result.judgment_rules import (
    treat_already_present_line_without_matching_target_as_assumed_not_needed,
    treat_apt_download_and_install_lines_shared_by_requests_of_several_commands_as_received,
    treat_command_without_own_evidence_as_no_evidence_of_run,
    treat_connected_line_as_assumed_server_answer,
    treat_exit_code_meaning_as_assumed_level,
    treat_failure_before_server_as_stopping_next_command,
    treat_file_use_that_may_not_have_happened_as_assumed_evidence,
    treat_higher_evidence_beside_failure_as_assumed_level,
    treat_installed_line_as_no_evidence_of_download,
    treat_line_beside_shown_file_or_page_text_as_not_a_trace,
    treat_line_naming_another_target_as_no_evidence_of_answer,
    treat_line_that_unknown_printer_may_have_printed_as_shared,
    treat_lost_connection_as_after_server_answer,
    treat_pip_or_apt_installed_line_of_named_package_as_received,
    treat_pip_saved_line_of_named_package_as_received,
    treat_shown_content_of_saved_file_as_assumed_content,
    treat_shown_result_text_as_assumed_content,
    treat_size_or_type_of_saved_file_as_no_evidence_of_content,
    treat_stop_reasons_of_one_level_as_first_in_fixed_order,
    treat_tls_or_proxy_failure_as_before_server_answer,
    treat_version_notice_line_as_no_evidence_of_answer,
    treat_web_tool_call_without_result_text_as_no_evidence_of_answer,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResultStopReason,
    OutputLineKind,
    ProgramExitCodeMeaning,
)

FAILED = NetworkRequestResultStopReason.FAILED
NOT_NEEDED = NetworkRequestResultStopReason.NOT_NEEDED
NOT_VISIBLE = NetworkRequestResultStopReason.NOT_VISIBLE

# (rule, its situation, the value it gives)
JUDGMENT_RULE_CASES: list[tuple[Callable[..., object], tuple[object, ...], object]] = [
    (
        treat_exit_code_meaning_as_assumed_level,
        (ProgramExitCodeMeaning.SERVER_ANSWERED,),
        True,
    ),
    (treat_pip_or_apt_installed_line_of_named_package_as_received, (), True),
    (treat_pip_saved_line_of_named_package_as_received, (), True),
    (treat_installed_line_as_no_evidence_of_download, (), True),
    (
        treat_apt_download_and_install_lines_shared_by_requests_of_several_commands_as_received,
        (),
        True,
    ),
    (treat_version_notice_line_as_no_evidence_of_answer, (), True),
    (treat_shown_result_text_as_assumed_content, (), True),
    (treat_size_or_type_of_saved_file_as_no_evidence_of_content, (), True),
    (treat_higher_evidence_beside_failure_as_assumed_level, (), True),
    (treat_web_tool_call_without_result_text_as_no_evidence_of_answer, (), True),
    (treat_line_naming_another_target_as_no_evidence_of_answer, (), True),
    (treat_command_without_own_evidence_as_no_evidence_of_run, (), True),
    (treat_line_beside_shown_file_or_page_text_as_not_a_trace, (), True),
    (treat_file_use_that_may_not_have_happened_as_assumed_evidence, (), True),
    (treat_failure_before_server_as_stopping_next_command, (), True),
    (
        treat_tls_or_proxy_failure_as_before_server_answer,
        (OutputLineKind.TLS_FAILED,),
        True,
    ),
    (
        treat_stop_reasons_of_one_level_as_first_in_fixed_order,
        ({None, FAILED},),
        None,
    ),
    (treat_shown_content_of_saved_file_as_assumed_content, (), True),
    (treat_connected_line_as_assumed_server_answer, (), True),
    (treat_line_that_unknown_printer_may_have_printed_as_shared, (), True),
    (
        treat_already_present_line_without_matching_target_as_assumed_not_needed,
        (),
        True,
    ),
    (treat_lost_connection_as_after_server_answer, (), True),
]

# (the rule with an argument, an argument it is not asked for)
RULES_WITH_ARGUMENTS_NOT_ASKED_FOR: list[tuple[Callable[..., object], object]] = [
    (treat_exit_code_meaning_as_assumed_level, ProgramExitCodeMeaning.NOTHING),
    (
        treat_tls_or_proxy_failure_as_before_server_answer,
        OutputLineKind.CONNECTION_LOST,
    ),
    (treat_stop_reasons_of_one_level_as_first_in_fixed_order, {FAILED}),
    (treat_stop_reasons_of_one_level_as_first_in_fixed_order, [FAILED, FAILED]),
]


@pytest.mark.parametrize(("rule", "situation", "value"), JUDGMENT_RULE_CASES)
def test_each_rule_gives_its_provisional_value_and_counts_one_use_under_its_name(
    rule: Callable[..., object], situation: tuple[object, ...], value: object
):
    use_counts: Counter[str] = Counter()

    assert rule(*situation, use_counts=use_counts) == value
    assert use_counts == Counter({rule.__name__: 1})


@pytest.mark.parametrize(("rule", "argument"), RULES_WITH_ARGUMENTS_NOT_ASKED_FOR)
def test_rule_refuses_an_argument_it_is_not_asked_for_and_counts_nothing(
    rule: Callable[..., object], argument: object
):
    use_counts: Counter[str] = Counter()

    with pytest.raises(ValueError):
        rule(argument, use_counts=use_counts)
    assert use_counts == Counter()


def test_exit_code_meaning_of_a_succeeded_request_is_taken_as_assumed_level():
    assert treat_exit_code_meaning_as_assumed_level(
        ProgramExitCodeMeaning.REQUEST_SUCCEEDED, use_counts=Counter()
    )


def test_proxy_failure_is_read_as_before_the_server_answer():
    assert treat_tls_or_proxy_failure_as_before_server_answer(
        OutputLineKind.PROXY_REFUSED, use_counts=Counter()
    )


@pytest.mark.parametrize(
    ("stop_reasons", "first_stop_reason"),
    [
        ([FAILED, NOT_NEEDED, None], None),
        ([NOT_NEEDED, FAILED], FAILED),
        ([NOT_VISIBLE, FAILED], FAILED),
        ([NOT_VISIBLE, NOT_NEEDED], NOT_NEEDED),
    ],
)
def test_stop_reasons_of_one_level_give_the_first_in_the_fixed_order(
    stop_reasons: list[NetworkRequestResultStopReason | None],
    first_stop_reason: NetworkRequestResultStopReason | None,
):
    assert (
        treat_stop_reasons_of_one_level_as_first_in_fixed_order(
            stop_reasons, use_counts=Counter()
        )
        == first_stop_reason
    )
