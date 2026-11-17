"""Tests for scripts/trial_folders_and_csv_files.py, i.e. the choice of trial folders that the audit scripts share and their CSV writer, on made-up folders."""

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "trial_folders_and_csv_files",
    Path(__file__).parents[1] / "scripts/trial_folders_and_csv_files.py",
)
assert _SPEC is not None and _SPEC.loader is not None
trial_folders = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = trial_folders
_SPEC.loader.exec_module(trial_folders)


def _raw_trials_dir(tmp_path: Path) -> Path:
    """Make a raw trials folder with the trial folders t1, t2 and t3, created out of name order, and a file beside them that is no trial folder."""
    raw_trials_dir = tmp_path / "raw"
    for trial_id in ("t3", "t1", "t2"):
        (raw_trials_dir / trial_id).mkdir(parents=True)
    (raw_trials_dir / "notes.txt").write_text("")
    return raw_trials_dir


def _chosen_trial_ids(raw_trials_dir: Path, *options: str) -> list[str]:
    parser = argparse.ArgumentParser()
    trial_folders.add_trial_choice_arguments(parser)
    arguments = parser.parse_args([str(raw_trials_dir), *options])
    return [path.name for path in trial_folders.chosen_trial_dirs_from(arguments)]


def test_without_options_every_trial_folder_is_chosen_by_name(tmp_path):
    assert _chosen_trial_ids(_raw_trials_dir(tmp_path)) == ["t1", "t2", "t3"]


def test_limit_chooses_the_first_trial_folders_by_name(tmp_path):
    assert _chosen_trial_ids(_raw_trials_dir(tmp_path), "--limit", "2") == ["t1", "t2"]


def test_trial_ids_choose_the_listed_trial_folders_in_the_order_of_the_file(tmp_path):
    trial_ids_file = tmp_path / "trial_ids.txt"
    trial_ids_file.write_text("t3\nt1\n")

    assert _chosen_trial_ids(
        _raw_trials_dir(tmp_path), "--trial-ids", str(trial_ids_file)
    ) == ["t3", "t1"]


def test_limit_and_trial_ids_exclude_each_other(tmp_path):
    with pytest.raises(SystemExit):
        _chosen_trial_ids(tmp_path, "--limit", "1", "--trial-ids", "f")


def test_trial_ids_are_the_first_column_of_lines_that_are_neither_empty_nor_comments():
    file_text = "# trial_id\tharness\nt1\tcodex\tfirst\n\n   \nt2\n#t3\n"

    assert trial_folders.trial_ids_from_file_text(file_text) == ["t1", "t2"]


def test_write_csv_writes_the_header_and_every_row_with_newline_ends(tmp_path):
    path = tmp_path / "rows.csv"

    trial_folders.write_csv(path, ("a", "b"), [("1", "x,y"), ("2", "")])

    assert path.read_bytes() == b'a,b\n1,"x,y"\n2,\n'
