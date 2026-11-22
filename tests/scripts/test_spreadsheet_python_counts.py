"""Test `spreadsheet_python_counts.py` on the made-up run."""

import csv
from collections import Counter
from pathlib import Path

import pytest
from conftest import TASK_0_4, TASK_A_3, TASK_A_4, TASK_B_3, script_module

spreadsheet_python_counts = script_module("spreadsheet_python_counts")


def _counts_of(run_dir: Path):
    return spreadsheet_python_counts.count_spreadsheet_values(
        spreadsheet_python_counts.RowFiles(run_dir)
    )


def test_lists_every_task_of_the_trial_rows_also_one_without_requests_and_tells_versions_apart(
    made_up_run_dir: Path,
):
    counts = _counts_of(made_up_run_dir)

    assert counts.tasks == [TASK_A_3, TASK_B_3, TASK_0_4, TASK_A_4]
    assert counts.trial_ids_of_task(TASK_A_3) == {"t6", "t7"}


def test_a_trial_passed_only_with_a_reward_of_one(made_up_run_dir: Path):
    assert _counts_of(made_up_run_dir).passed_trial_ids == {
        "t1",
        "t2",
        "t4",
        "t6",
        "t8",
    }


def test_counts_registries_and_hosts_and_requested_items_from_lower_bound_rows_of_the_task_environment(
    made_up_run_dir: Path,
):
    counts = _counts_of(made_up_run_dir)
    line_key = spreadsheet_python_counts.RegistryOrHostServiceLineKey
    item_key = spreadsheet_python_counts.RequestedItemLineKey

    # `requests` of t1 and `Requests` of t3 are one item. npm of t6 is only in the upper bound.
    assert {
        key: (line.trial_ids, line.requested_items)
        for key, line in counts.registry_or_host_service_lines.items()
    } == {
        line_key("package", "pypi"): (
            {"t1", "t3", "t5"},
            {"requests", "(named_in_file)"},
        ),
        line_key("content_fetch", "code_hosting"): ({"t5"}, {"github.com"}),
        line_key("remote_api_call", "web_api"): ({"t5"}, {"api.github.com"}),
        line_key("other_web", "unknown"): ({"t5"}, {"b.org"}),
    }
    assert counts.requested_item_trial_ids == {
        item_key(TASK_A_4, line_key("package", "pypi"), "requests"): {"t1", "t3"},
        item_key(TASK_0_4, line_key("package", "pypi"), "(named_in_file)"): {"t5"},
        item_key(TASK_0_4, line_key("content_fetch", "code_hosting"), "github.com"): {
            "t5"
        },
        item_key(TASK_0_4, line_key("remote_api_call", "web_api"), "api.github.com"): {
            "t5"
        },
        item_key(TASK_0_4, line_key("other_web", "unknown"), "b.org"): {"t5"},
    }


@pytest.mark.parametrize(
    ("target", "package_registry", "package_name"),
    [
        pytest.param("orjson==3.10.12", "pypi", "orjson", id="pip version"),
        pytest.param("uvicorn[standard]>=0.30", "pypi", "uvicorn", id="pip extras"),
        pytest.param(
            "Typing_Extensions", "pypi", "typing-extensions", id="pip name as compared"
        ),
        pytest.param("torch==2.11.0+cpu", "pytorch", "torch", id="pytorch as pip"),
        pytest.param("left-pad@1.3.0", "npm", "left-pad", id="npm version"),
        pytest.param("@babel/core@7", "npm", "@babel/core", id="npm scope stays"),
        pytest.param("ovmf/trixie", "apt", "ovmf", id="apt release"),
        pytest.param("g++", "apt", "g++", id="apt name with +"),
        pytest.param("/app/work/x.deb", "apt", "/app/work/x.deb", id="apt path"),
        pytest.param(
            "github.com/a/b@v1",
            "go_module_proxy",
            "github.com/a/b@v1",
            id="other registry",
        ),
        pytest.param(
            "git+https://github.com/a/b.git",
            "pypi",
            "git+https://github.com/a/b.git",
            id="pip url stays",
        ),
        pytest.param(
            "dist/Foo_Bar-2.1.0-py3-none-any.whl",
            "pypi",
            "foo-bar",
            id="pip wheel file",
        ),
        pytest.param("./vendor/pkg", "pypi", "./vendor/pkg", id="pip path stays"),
    ],
)
def test_gives_the_package_name_without_version_and_extras(
    target: str, package_registry: str, package_name: str
):
    assert (
        spreadsheet_python_counts.package_name_of(target, package_registry)
        == package_name
    )


def test_gives_the_host_of_a_request_that_is_no_package():
    row = {"category": "content_fetch", "host_names": "github.com"}

    assert spreadsheet_python_counts.requested_item_of(row) == "github.com"
    assert (
        spreadsheet_python_counts.requested_item_of(row | {"host_names": ""})
        == "(no host name)"
    )


def test_gives_what_a_package_request_without_a_target_says_of_it():
    row = {
        "category": "package",
        "target": "",
        "target_kind": "",
        "package_registry": "apt",
        "host_names": "",
        "unknown_target_reason": "",
    }

    # e.g. `apt-get update`.
    assert spreadsheet_python_counts.requested_item_of(row) == "(no package named)"
    assert (
        spreadsheet_python_counts.requested_item_of(
            row | {"unknown_target_reason": "value_set_at_run_time"}
        )
        == "(value_set_at_run_time)"
    )


@pytest.mark.parametrize(
    ("target", "package_registry", "host_names", "requested_item"),
    [
        pytest.param(
            "https://pypi.org/pypi/x/json", "pypi", "pypi.org", "pypi.org", id="pip url"
        ),
        pytest.param(
            "http://deb.debian.org/debian/dists/x/Release",
            "apt",
            "deb.debian.org",
            "deb.debian.org",
            id="apt url",
        ),
        pytest.param(
            "https://files.pythonhosted.org/p/x/x-1.0.tar.gz",
            "pypi",
            "files.pythonhosted.org",
            "files.pythonhosted.org",
            id="pip source archive url",
        ),
        pytest.param(
            "https://files.pythonhosted.org/p/n/Foo_Bar-2.1.0-py3-none-any.whl",
            "pypi",
            "files.pythonhosted.org",
            "foo-bar",
            id="pip wheel url keeps the wheel name",
        ),
        pytest.param(
            "https://dl-cdn.alpinelinux.org/alpine/v3/main/x",
            "apk",
            "",
            "(no host name)",
            id="url without host name",
        ),
    ],
)
def test_gives_the_host_of_a_package_request_to_a_registry_url(
    target: str, package_registry: str, host_names: str, requested_item: str
):
    row = {
        "category": "package",
        "target": target,
        "target_kind": "url",
        "package_registry": package_registry,
        "host_names": host_names,
        "unknown_target_reason": "",
    }

    assert spreadsheet_python_counts.requested_item_of(row) == requested_item


def test_keys_web_tool_requests_by_the_harness_of_their_trial_and_counts_the_upper_bound_alone(
    made_up_run_dir: Path,
):
    lines = _counts_of(made_up_run_dir).web_tool_lines
    line_key = spreadsheet_python_counts.WebToolLineKey

    assert {
        key: (line.lower_trial_ids, line.upper_trial_ids) for key, line in lines.items()
    } == {
        line_key("codex", "web_search_call", "provider_server", "search"): (
            {"t3"},
            {"t3"},
        ),
        line_key("cursor-cli", "web_search_call", "provider_server", "search"): (
            {"t8"},
            {"t8"},
        ),
        line_key("codex", "web_fetch", "harness_process", "content_fetch"): (
            set(),
            {"t6"},
        ),
        line_key("codex", "exec", "unknown", "search"): ({"t6"}, {"t6"}),
        line_key("codex", "exec", "unknown", "content_fetch"): ({"t6"}, {"t6"}),
    }


def test_judges_each_task_by_the_bounds_of_its_passed_trials(made_up_run_dir: Path):
    counts = _counts_of(made_up_run_dir)
    verdict = spreadsheet_python_counts.SolvedWithoutRequestVerdict

    # t2 of 4-0-0 a and t8 of 3-0-0 b passed with neither. t4, unreadable, and t6 passed with upper_only.
    assert {
        task: counts.passed_trial_counts_of(task).verdict for task in counts.tasks
    } == {
        TASK_A_3: verdict.MAYBE,
        TASK_B_3: verdict.YES,
        TASK_0_4: verdict.MAYBE,
        TASK_A_4: verdict.YES,
    }
    assert counts.passed_trial_counts_of(
        TASK_A_4
    ) == spreadsheet_python_counts.PassedTrialCounts(2, 1, 0)


@pytest.mark.parametrize(
    ("passed_trial_counts", "verdict"),
    [
        pytest.param((3, 1, 1), "yes", id="one passed trial without a request"),
        pytest.param(
            (3, 0, 1),
            "maybe",
            id="one passed trial only in the upper bound",
        ),
        pytest.param((3, 0, 0), "no", id="every passed trial lower"),
        pytest.param((0, 0, 0), "never solved", id="no passed trial"),
    ],
)
def test_gives_each_verdict_by_its_rule(
    passed_trial_counts: tuple[int, int, int], verdict: str
):
    assert (
        spreadsheet_python_counts.PassedTrialCounts(*passed_trial_counts).verdict
        == verdict
    )


def _bounds_row(**columns: str) -> dict[str, str]:
    """Make a row of the columns that `upper_bound_only_cause_of` reads, a confirmed request of the task environment unless given."""
    return {
        "made_by": "curl",
        "sender": "task_environment",
        "request_certainty": "confirmed",
        "request_uncertainty_reason": "",
        "unknown_target_reason": "",
        "level": "attempted",
        "stop_reason": "not_visible",
        "is_internet_use": "",
    } | columns


_UNCERTAIN = {"request_certainty": "uncertain"}


@pytest.mark.parametrize(
    ("rows", "cause"),
    [
        pytest.param(
            [_bounds_row(unknown_target_reason="built_in_code"), _bounds_row()],
            "CONFIRMED_REQUEST_TO_ADDRESS_BUILT_IN_CODE",
            id="an address built in code before another confirmed request",
        ),
        pytest.param(
            [
                _bounds_row(
                    **_UNCERTAIN, request_uncertainty_reason="url_outside_code_call"
                ),
                _bounds_row(),
            ],
            "CONFIRMED_REQUEST_NOT_KNOWN_AS_INTERNET",
            id="a confirmed request before an uncertain one",
        ),
        pytest.param(
            [_bounds_row(sender="unknown")],
            "WEB_TOOL_OF_UNKNOWN_SENDER",
            id="only a web tool of unknown sender",
        ),
        pytest.param(
            [
                _bounds_row(sender="unknown"),
                _bounds_row(
                    **_UNCERTAIN, request_uncertainty_reason="url_outside_code_call"
                ),
            ],
            "URL_OUTSIDE_CODE_CALL",
            id="a web tool of unknown sender beside a request of the task environment",
        ),
        pytest.param(
            [
                _bounds_row(
                    **_UNCERTAIN, request_uncertainty_reason="url_outside_code_call"
                ),
                _bounds_row(
                    **_UNCERTAIN,
                    request_uncertainty_reason="fetches_only_what_is_missing",
                ),
            ],
            "FETCHES_ONLY_WHAT_IS_MISSING",
            id="a program that fetches only what is missing before a URL in code",
        ),
        pytest.param(
            [_bounds_row(**_UNCERTAIN, request_uncertainty_reason="unknown_code_call")],
            "OTHER_UNCERTAIN_REQUEST",
            id="another uncertain request",
        ),
        pytest.param(
            [
                _bounds_row(
                    **_UNCERTAIN,
                    request_uncertainty_reason="program_run_by_code",
                    unknown_target_reason="built_in_code",
                )
            ],
            "OTHER_UNCERTAIN_REQUEST",
            id="an uncertain request built in code is no confirmed request",
        ),
        pytest.param(
            [
                _bounds_row(is_internet_use="true", stop_reason="not_needed"),
                _bounds_row(
                    **_UNCERTAIN, request_uncertainty_reason="url_outside_code_call"
                ),
            ],
            "URL_OUTSIDE_CODE_CALL",
            id="a confirmed request that is internet use falls through",
        ),
        pytest.param([], "OTHER_UNCERTAIN_REQUEST", id="a trial without rows"),
    ],
)
def test_gives_a_trial_only_in_the_upper_bound_the_first_cause_its_rows_meet(
    rows: list[dict[str, str]], cause: str
):
    assert (
        spreadsheet_python_counts.upper_bound_only_cause_of(rows, is_unreadable=False)
        == spreadsheet_python_counts.UpperBoundOnlyCause[cause]
    )


def test_counts_each_trial_only_in_the_upper_bound_once_by_its_cause(
    made_up_run_dir: Path,
):
    counts = _counts_of(made_up_run_dir)
    cause = spreadsheet_python_counts.UpperBoundOnlyCause

    # t6 runs `npx` and has web tools of unknown sender.
    assert counts.upper_bound_only_cause_by_trial_id == {
        "t4": cause.UNREADABLE_TRAJECTORY,
        "t6": cause.FETCHES_ONLY_WHAT_IS_MISSING,
    }
    assert counts.example_counts_by_upper_bound_only_cause == {
        cause.UNREADABLE_TRAJECTORY: Counter({"missing": 1}),
        cause.FETCHES_ONLY_WHAT_IS_MISSING: Counter({"npx": 2}),
    }


def test_gives_each_trial_of_the_lower_bound_the_furthest_result_of_its_requests(
    made_up_run_dir: Path,
):
    result = spreadsheet_python_counts.BestRequestResult

    # t5 failed a clone and reached the server of a page.
    assert _counts_of(made_up_run_dir).best_request_result_by_trial_id == {
        "t1": result.RECEIVED,
        "t3": result.NOT_VISIBLE,
        "t5": result.SERVER_ANSWERED,
    }


@pytest.mark.parametrize(
    ("levels_and_stop_reasons", "best_request_result"),
    [
        pytest.param(
            [("reached", "failed"), ("executed", "failed")],
            "SERVER_ANSWERED",
            id="a server that refused answered",
        ),
        pytest.param(
            [("received", "")],
            "SERVER_ANSWERED",
            id="a received row of a trial outside the received lower bound",
        ),
        pytest.param(
            [("attempted", "failed"), ("executed", "not_visible")],
            "FAILED_WITHOUT_ANSWER",
            id="a request that did not run",
        ),
        pytest.param(
            [("executed", "failed")],
            "FAILED_WITHOUT_ANSWER",
            id="a request that did not reach a server",
        ),
        pytest.param(
            [("executed", "not_needed"), ("attempted", "not_visible")],
            "NOT_VISIBLE",
            id="nothing beyond the run",
        ),
    ],
)
def test_gives_the_furthest_result_by_its_rule(
    levels_and_stop_reasons: list[tuple[str, str]], best_request_result: str
):
    rows = [
        _bounds_row(level=level, stop_reason=stop_reason)
        for level, stop_reason in levels_and_stop_reasons
    ]

    assert (
        spreadsheet_python_counts.best_request_result_of(rows, is_received=False)
        == spreadsheet_python_counts.BestRequestResult[best_request_result]
    )


@pytest.mark.parametrize(
    ("share", "band"),
    [
        pytest.param(0.0, 0, id="0%"),
        pytest.param(0.0999, 0, id="below 10%"),
        pytest.param(6 / 60, 1, id="10% of 60 trials"),
        pytest.param(18 / 60, 3, id="30% as a division"),
        pytest.param(0.95, 9, id="95%"),
        pytest.param(1.0, 9, id="100% in the last band"),
    ],
)
def test_puts_a_share_in_its_band_of_10_points(share: float, band: int):
    assert spreadsheet_python_counts.share_band_of(share) == band


def test_task_category_measures_written_by_the_run_agree_and_a_changed_line_differs(
    made_up_run_dir: Path,
):
    row_files = spreadsheet_python_counts.RowFiles(made_up_run_dir)
    counts = spreadsheet_python_counts.count_spreadsheet_values(row_files)
    assert (
        spreadsheet_python_counts.differing_task_category_measure_line_count_of(
            row_files, counts
        )
        == 0
    )

    lines = list(csv.reader(row_files.task_category_measures.open()))
    lines[1][5] = str(int(lines[1][5]) + 1)
    with row_files.task_category_measures.open("w", newline="") as csv_file:
        csv.writer(csv_file).writerows(lines)

    assert (
        spreadsheet_python_counts.differing_task_category_measure_line_count_of(
            row_files, counts
        )
        == 1
    )


def test_refuses_a_row_file_whose_columns_are_not_the_fields_of_its_type(
    made_up_run_dir: Path,
):
    path = made_up_run_dir / "trial_rows.csv"
    path.write_text(path.read_text().replace("trial_id,", "id,", 1))

    with pytest.raises(ValueError, match="not the fields of TrialRow"):
        _counts_of(made_up_run_dir)
