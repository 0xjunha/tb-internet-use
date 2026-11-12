"""Tests for request/program_options.py."""

import pytest

from tb_internet_use.network.model import PrintingProgram
from tb_internet_use.program.arguments import parse_arguments
from tb_internet_use.program.model import (
    AskedPackagesSource,
    ExitZeroMeans,
    RequestKind,
    RequestRule,
)
from tb_internet_use.request.program_options import OptionFacts, option_facts

CURL_RULE = RequestRule(
    kind=RequestKind.URL,
    printing_programs=frozenset({PrintingProgram.CURL}),
    exit_zero_means=ExitZeroMeans.SERVER_RESPONDED,
    fetches_only_to_run_or_build=False,
    asked_packages_source=AskedPackagesSource.NONE,
    asks_for_no_content=False,
    prints_response_body=True,
)
WGET_RULE = RequestRule(
    kind=RequestKind.URL,
    printing_programs=frozenset({PrintingProgram.WGET}),
    exit_zero_means=ExitZeroMeans.REQUEST_SUCCEEDED,
    fetches_only_to_run_or_build=False,
    asked_packages_source=AskedPackagesSource.NONE,
    asks_for_no_content=False,
    prints_response_body=False,
)


def _facts(program: str, arguments: str, rule: RequestRule = CURL_RULE) -> OptionFacts:
    return option_facts(
        program, parse_arguments(program, tuple(arguments.split())), rule
    )


@pytest.mark.parametrize(
    ("program", "arguments", "sends_no_request"),
    [
        ("curl", "--version", True),
        ("pip", "install --help", True),
        ("rsync", "-avh a b", False),  # -h is human-readable sizes for rsync
        ("git", "ls-remote -h u", False),  # -h is --heads for git ls-remote
    ],
)
def test_sends_no_request(program: str, arguments: str, sends_no_request: bool):
    assert _facts(program, arguments).sends_no_request == sends_no_request


@pytest.mark.parametrize(
    ("program", "arguments", "quiet_progress_lines", "quiet_error_lines"),
    [
        ("curl", "-s u", True, True),
        ("curl", "-sS u", True, False),
        ("wget", "-q u", True, True),
        ("pip", "install -q x", True, False),
        ("npm", "install --silent", True, True),
        ("git", "clone u", False, False),
    ],
)
def test_quiet_lines(
    program: str, arguments: str, quiet_progress_lines: bool, quiet_error_lines: bool
):
    facts = _facts(program, arguments)
    assert (facts.quiet_progress_lines, facts.quiet_error_lines) == (
        quiet_progress_lines,
        quiet_error_lines,
    )


def test_offline_index_and_package_file_options():
    pip = _facts("pip", "install --no-index --extra-index-url https://e.org -r r.txt")
    assert pip.has_offline_option
    assert pip.index_urls == ("https://e.org",)
    assert pip.names_packages_in_files
    assert not _facts("curl", "--offline u").has_offline_option
    # -c is conda's channel, not pip's constraints file.
    assert not _facts("conda", "install -c conda-forge numpy").names_packages_in_files


@pytest.mark.parametrize(
    ("arguments", "exit_zero_means", "asks_for_no_content", "prints_body", "added"),
    [
        ("u", ExitZeroMeans.SERVER_RESPONDED, False, True, set()),
        (
            "-fsSL u",
            ExitZeroMeans.REQUEST_SUCCEEDED,
            False,
            True,
            {PrintingProgram.HTTP_FAILURE},
        ),
        ("-o out u", ExitZeroMeans.SERVER_RESPONDED, False, False, set()),
        ("-o - u", ExitZeroMeans.SERVER_RESPONDED, False, True, set()),
        ("-O u", ExitZeroMeans.SERVER_RESPONDED, False, False, set()),
        (
            "-I u",
            ExitZeroMeans.SERVER_RESPONDED,
            True,
            False,
            {PrintingProgram.HTTP_HEADERS},
        ),
        ("-X HEAD u", ExitZeroMeans.SERVER_RESPONDED, True, False, set()),
        (
            "-v u",
            ExitZeroMeans.SERVER_RESPONDED,
            False,
            True,
            {PrintingProgram.HTTP_HEADERS},
        ),
    ],
)
def test_curl_options_change_the_rule(
    arguments, exit_zero_means, asks_for_no_content, prints_body, added
):
    rule = _facts("curl", arguments).rule
    assert rule.exit_zero_means == exit_zero_means
    assert (rule.asks_for_no_content, rule.prints_response_body) == (
        asks_for_no_content,
        prints_body,
    )
    assert rule.printing_programs == {PrintingProgram.CURL, *added}


def test_curl_prints_headers_only_when_it_dumps_them_to_stdout():
    assert (
        PrintingProgram.HTTP_HEADERS in _facts("curl", "-D - u").rule.printing_programs
    )
    assert (
        PrintingProgram.HTTP_HEADERS
        not in _facts("curl", "-D h.txt u").rule.printing_programs
    )


def test_curl_write_out_prints_the_status_code():
    assert _facts("curl", "-w %{http_code} -o /dev/null u").prints_status_code
    assert not _facts("curl", "-w %{time_total} u").prints_status_code


@pytest.mark.parametrize(
    ("arguments", "asks_for_no_content", "prints_body", "added"),
    [
        ("u", False, False, set()),
        ("-qO- u", False, True, set()),
        ("--spider u", True, False, set()),
        ("-S u", False, False, {PrintingProgram.HTTP_HEADERS}),
    ],
)
def test_wget_options_change_the_rule(
    arguments, asks_for_no_content, prints_body, added
):
    rule = _facts("wget", arguments, WGET_RULE).rule
    assert (rule.asks_for_no_content, rule.prints_response_body) == (
        asks_for_no_content,
        prints_body,
    )
    assert rule.printing_programs == {PrintingProgram.WGET, *added}


def test_other_programs_keep_the_rule():
    assert _facts("pip", "install -fq x").rule == CURL_RULE
