"""Tests for scripts/audit_export_knowledge.py, run on the output of scripts/run_pipeline.py for made-up trial folders, with the written files, the counts of `export_rows` or the lookups of `ExportKnowledge` changed so that the equation under test differs.

The equations hold whatever the catalogs say, so the cases use the catalogs of the repo. Beside the equations, some cases assert the exit code and what the other CSVs of the audit hold, e.g. the rows of `row_uses.csv` that the catalogs of the repo give.
"""

import csv
import importlib.util
import json
import sys
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Self

import pytest

_SCRIPTS_DIR = Path(__file__).parents[2] / "scripts"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # the audit imports `run_pipeline` by this name
    spec.loader.exec_module(module)
    return module


run_pipeline = _load_script("run_pipeline")
audit = _load_script("audit_export_knowledge")

# Commands of made-up trials whose rows reach many rules, e.g. a request that runs only when its file is missing, a package of a variable, a program without a row, a discarded page with a query, a host without a dot, a reserved host beside a templated one, a clone of a repository and two downloads that share one line of success.
_BASH_CALLS_OF_TRIAL = {
    "t1": [
        (
            "test -f x.tgz || wget -O x.tgz https://files.acme.org/x.tgz; pip install $PKGS; mytool https://b.org/y",
            "Successfully installed requests-2.32.3",
        )
    ],
    "t2": [
        (
            'curl -s -o /dev/null "https://a.org/x?token=abc"; curl http://db:5432/; git clone https://github.com/a/b',
            "",
        ),
        (
            "pip install --index-url https://example.com/simple --extra-index-url 'https://{host}/simple' x",
            "",
        ),
    ],
    "t3": [("ls", "notes.txt")],
    "t4": None,
    # Two wget requests own one `saved` line, which only wget prints, so the trial counts in the lower bound of received file fetches although each request stays assumed.
    "t6": [
        (
            "wget https://a.org/x.tgz https://a.org/y.tgz; ./check.sh",
            "'x.tgz' saved [1024/1024]",
        )
    ],
}

# A made-up Claude Code trajectory whose one `WebFetch` call reads a host without a dot, which the rule for local hosts and hosts without a dot of a web tool decides rather than the rule for a host without a dot.
_WEB_FETCH_TRAJECTORY = json.dumps(
    {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "claude-code"},
        "steps": [
            {
                "step_id": 1,
                "tool_calls": [
                    {
                        "tool_call_id": "call-1",
                        "function_name": "WebFetch",
                        "arguments": {"url": "http://db:8000/", "prompt": "read it"},
                    }
                ],
                "observation": {
                    "results": [{"source_call_id": "call-1", "content": "a page"}]
                },
            }
        ],
    }
).encode()


class _InProcessPool:
    """Stand-in for the process pools of both scripts, which runs each task in the test process so that what a test patches on a script reaches the task."""

    def __init__(self, process_count: int) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exception: object) -> None:
        pass

    def map(
        self, function: Callable[[Path], Any], items: Iterable[Path], chunksize: int
    ) -> Iterator[Any]:
        return map(function, items)

    def submit(self, function: Callable[[Path], Any], item: Path) -> Future:
        """Run the function at once and give a future that holds its value."""
        future: Future = Future()
        future.set_result(function(item))
        return future

    def kill_workers(self) -> None:
        pass


@pytest.fixture
def run_dir(tmp_path, monkeypatch, write_trial_folder) -> Path:
    """Run `run_pipeline.py` on the made-up trials and give its output folder."""
    raw_trials_dir = tmp_path / "raw"
    for trial_id, bash_calls in _BASH_CALLS_OF_TRIAL.items():
        write_trial_folder(raw_trials_dir, trial_id, bash_calls)
    write_trial_folder(raw_trials_dir, "t5", _WEB_FETCH_TRAJECTORY)
    run_dir = tmp_path / "run"
    monkeypatch.setattr(run_pipeline, "ProcessPoolExecutor", _InProcessPool)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_pipeline", str(raw_trials_dir), "--out-dir", str(run_dir)],
    )
    run_pipeline.main()
    return run_dir


def _run_audit(monkeypatch: pytest.MonkeyPatch, run_dir: Path, out_dir: Path) -> int:
    """Run `main` of the audit on a run folder and give its exit code, 0 when it returns."""
    monkeypatch.setattr(audit, "ProcessPoolExecutor", _InProcessPool)
    monkeypatch.setattr(
        sys, "argv", ["audit_export_knowledge", str(run_dir), "--out-dir", str(out_dir)]
    )
    try:
        audit.main()
    except SystemExit as exit_info:
        assert isinstance(exit_info.code, int)
        return exit_info.code
    return 0


def _csv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="") as csv_file:
        return list(csv.reader(csv_file))


def _differing_equations(out_dir: Path) -> list[str]:
    return [
        row[0] for row in _csv_rows(out_dir / "equations.csv")[1:] if row[3] == "no"
    ]


def _replace_in_file(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def test_every_equation_holds_on_the_rows_of_made_up_trials(
    run_dir, tmp_path, monkeypatch
):
    out_dir = tmp_path / "audit"

    exit_code = _run_audit(monkeypatch, run_dir, out_dir)

    assert exit_code == 0
    equation_rows = _csv_rows(out_dir / "equations.csv")[1:]
    assert [row[0] for row in equation_rows] == list(audit.EQUATIONS)
    assert _differing_equations(out_dir) == []
    sides = {row[0]: (int(row[1]), int(row[2])) for row in equation_rows}
    # The made-up trials reach the rules, so the equations do not hold only because both sides are 0.
    for rule_name in (
        "treat_request_without_host_name_as_sent_to_default_registry_host",
        "treat_single_label_host_name_as_not_internet_use",
        "treat_templated_host_name_as_unknown_internet_use",
        "treat_local_or_single_label_host_name_of_web_tool_as_unknown_internet_use",
        "treat_url_query_value_and_fragment_as_credential",
        "treat_dotted_host_name_as_public",
        "treat_trial_with_success_line_shared_by_confirmed_requests_as_received",
    ):
        assert sides[f"{rule_name}_uses_equal_its_situations"][0] > 0, rule_name
    assert (
        sides[
            "measure_rows_above_their_request_rows_equal_categories_and_senders_with_success_line_owners"
        ][0]
        > 0
    )
    assert sides["package_registry_lookups_equal_package_name_commands"][0] > 0
    rule_rows = _csv_rows(out_dir / "judgment_rule_uses.csv")
    assert rule_rows[0] == ["judgment_rule", "use_count", "trial_count", "task_count"]
    assert [
        "treat_reserved_host_name_as_unknown_internet_use",
        "0",
        "0",
        "0",
    ] in rule_rows
    assert _csv_rows(out_dir / "row_uses.csv")[1:] == [
        ["program_package_registries.csv", '["pip", "install"]', "2", "2", "1"],
        ["harness_web_tools.csv", '["claude-code", "WebFetch"]', "1", "1", "1"],
        ["public_hosts.csv", '["github.com"]', "1", "1", "1"],
    ]
    assert _csv_rows(out_dir / "trials_not_audited.csv") == [
        ["trial_id", "exception_type"]
    ]


# (equation, file of the run, text in it, text that replaces it everywhere), for seven of the ten equations that read a written file, two of them with two cases.
BROKEN_FILE_CASES = [
    (
        "written_request_rows_differing_from_rows_exported_again",
        "network_request_rows.csv",
        "https://b.org/y",
        "https://b.org/z",
    ),
    (
        "text_cells_with_unredacted_userinfo",
        "network_request_rows.csv",
        "https://b.org/y",
        "https://user:pw@b.org/y",
    ),
    (
        "text_cells_with_unredacted_query_value",
        "network_request_rows.csv",
        "token=REDACTED",
        "token=abc",
    ),
    (
        "text_cells_with_unredacted_fragment",
        "network_request_rows.csv",
        "https://b.org/y",
        "https://b.org/y#k",
    ),
    (
        "measure_rows_differing_from_their_strongest_request_rows",
        "trial_category_measure_rows.csv",
        "t1,package,task_environment,lower_and_upper",
        "t1,package,task_environment,upper_only",
    ),
    # The rows of t6 lose their mark, so the main measure line of t6, counted in the lower bound of received by its shared line, rests on no request row.
    (
        "measure_rows_differing_from_their_strongest_request_rows",
        "network_request_rows.csv",
        "upper_only,true",
        "upper_only,false",
    ),
    (
        "measure_rows_above_their_request_rows_equal_categories_and_senders_with_success_line_owners",
        "network_request_rows.csv",
        "upper_only,true",
        "upper_only,false",
    ),
    (
        "measure_rows_above_their_request_rows_equal_categories_and_senders_with_success_line_owners",
        "trial_category_measure_rows.csv",
        "t6,file_fetch,task_environment,lower_and_upper,lower_and_upper",
        "t6,file_fetch,task_environment,lower_and_upper,upper_only",
    ),
    (
        "task_lines_whose_trial_count_differs_from_trial_rows",
        "trial_rows.csv",
        "t4,4-0-0,terminal-bench/a",
        "t4,4-0-0,terminal-bench/b",
    ),
]


@pytest.mark.parametrize(("equation", "file_name", "old", "new"), BROKEN_FILE_CASES)
def test_a_changed_file_of_the_run_makes_its_equation_differ_and_exits_1(
    run_dir, tmp_path, monkeypatch, equation, file_name, old, new
):
    _replace_in_file(run_dir / file_name, old, new)
    out_dir = tmp_path / "audit"

    exit_code = _run_audit(monkeypatch, run_dir, out_dir)

    assert exit_code == 1
    assert equation in _differing_equations(out_dir)


def test_task_lines_out_of_order_or_below_the_unreadable_trials_differ(
    run_dir, tmp_path, monkeypatch
):
    task_lines_path = run_dir / "task_category_measures.csv"
    header, *lines = _csv_rows(task_lines_path)
    # The upper count of requests of every line drops to 0, below the one unreadable trial of the task and, on the lines with a lower count above 0, below that lower count.
    column = header.index("request_upper_trial_count")
    with task_lines_path.open("w", newline="") as csv_file:
        csv.writer(csv_file, lineterminator="\n").writerows(
            [header, *([*line[:column], "0", *line[column + 1 :]] for line in lines)]
        )
    out_dir = tmp_path / "audit"

    _run_audit(monkeypatch, run_dir, out_dir)

    assert {
        "task_lines_whose_counts_are_out_of_order",
        "task_lines_whose_upper_count_is_below_unreadable_trials",
    } <= set(_differing_equations(out_dir))


# (equation, rule names that a changed `export_rows` counts once more), one case for a rule of `export/judgment_rules.py` asked for a request, one for `treat_trial_with_success_line_shared_by_confirmed_requests_as_received`, asked for a category and sender of a trial, one for `treat_dotted_host_name_as_public` and one for a name that is no rule.
BROKEN_COUNT_CASES = [
    (
        "treat_discarded_content_as_other_web_uses_equal_its_situations",
        ["treat_discarded_content_as_other_web"],
    ),
    (
        "treat_dotted_host_name_as_public_uses_equal_its_situations",
        ["treat_dotted_host_name_as_public"],
    ),
    (
        "treat_trial_with_success_line_shared_by_confirmed_requests_as_received_uses_equal_its_situations",
        ["treat_trial_with_success_line_shared_by_confirmed_requests_as_received"],
    ),
    ("judgment_rule_names_are_of_this_step", ["treat_x_as_y"]),
]


@pytest.mark.parametrize(("equation", "extra_rule_names"), BROKEN_COUNT_CASES)
def test_a_rule_counted_out_of_its_situation_makes_its_equation_differ(
    run_dir, tmp_path, monkeypatch, equation, extra_rule_names
):
    def export_rows_counting_more(*arguments: Any, **keywords: Any) -> Any:
        keywords["judgment_rule_use_counts"].update(extra_rule_names)
        return run_pipeline.export_rows(*arguments, **keywords)

    monkeypatch.setattr(audit, "export_rows", export_rows_counting_more)
    out_dir = tmp_path / "audit"

    _run_audit(monkeypatch, run_dir, out_dir)

    assert equation in _differing_equations(out_dir)


def test_a_lookup_of_the_knowledge_class_out_of_its_situation_makes_its_equation_differ(
    run_dir, tmp_path, monkeypatch
):
    def export_rows_asking_one_host_more(*arguments: Any, **keywords: Any) -> Any:
        keywords["knowledge"].public_host("pypi.org")
        return run_pipeline.export_rows(*arguments, **keywords)

    monkeypatch.setattr(audit, "export_rows", export_rows_asking_one_host_more)
    out_dir = tmp_path / "audit"

    _run_audit(monkeypatch, run_dir, out_dir)

    assert "public_host_lookups_equal_public_host_scopes" in _differing_equations(
        out_dir
    )


def test_a_trial_without_saved_results_is_named_and_exits_1(
    run_dir, tmp_path, monkeypatch
):
    (run_dir / "network_request_results" / "t2.pickle").unlink()
    out_dir = tmp_path / "audit"

    exit_code = _run_audit(monkeypatch, run_dir, out_dir)

    assert exit_code == 1
    assert _csv_rows(out_dir / "trials_not_audited.csv")[1:] == [
        ["t2", "FileNotFoundError"]
    ]
