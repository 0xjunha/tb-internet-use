"""Count every tool and argument key in raw ATIF trajectories and write them as CSV.

action_type and action_field stay empty, to be filled by hand once.

Usage: uv run python scripts/build_harness_tool_catalog.py <raw_trials_dir> [output_csv]
"""

import argparse
import csv
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from tb_internet_use.toolcall.atif_reader import TrajectoryStatus, read_trial_tool_calls

PACKAGE_DIR = Path(__file__).parents[1] / "src/tb_internet_use"
DEFAULT_OUTPUT_CSV = PACKAGE_DIR / "toolcall/catalogs/harness_tool_catalog.csv"

CSV_COLUMNS = [
    "harness",  # ATIF agent.name
    "tool",  # ATIF function_name
    "action_type",  # filled by hand: Action class for this tool, or Deferred
    "tool_call_count",  # number of calls to this tool
    "tool_trial_count",  # number of trials that called this tool at least once
    "arg_name",  # ATIF arguments key; empty if the tool never had an argument
    "action_field",  # filled by hand: Action field for this argument; empty if unused
    "arg_call_count",  # number of calls to this tool that had this argument
    "arg_value_types",  # JSON types seen for this argument, e.g. "integer|string"
]


JSON_TYPES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}


def count_trial(trial_dir: Path) -> tuple[TrajectoryStatus, Counter, Counter]:
    """Return the trial's status, calls per tool, and calls per (tool, arg, type)."""
    trial = read_trial_tool_calls(trial_dir)

    tool_counter = Counter()  # (harness, tool) -> number of calls
    arg_counter = Counter()  # ((harness, tool), arg name, arg type) -> number of calls
    for call in trial.calls:
        harness_tool = (call.tool.harness, call.tool.name)
        tool_counter[harness_tool] += 1
        for arg_name, value in call.args.items():
            arg_counter[(harness_tool, arg_name, JSON_TYPES[type(value)])] += 1
    return trial.trajectory_status, tool_counter, arg_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_trials_dir", type=Path)
    parser.add_argument("output_csv", type=Path, nargs="?", default=DEFAULT_OUTPUT_CSV)
    paths = parser.parse_args()

    # Totals across all trials
    status_counts = Counter()  # trajectory status -> number of trials
    tool_call_counts = Counter()  # (harness, tool) -> number of calls
    tool_trial_counts = Counter()  # (harness, tool) -> number of trials that called it

    # (harness, tool) -> arg name -> arg type -> number of calls
    arg_type_counts = defaultdict(lambda: defaultdict(Counter))

    # Keep folders only
    trial_dirs = [p for p in paths.raw_trials_dir.iterdir() if p.is_dir()]

    # Count trials in parallel and merge each result here
    with ProcessPoolExecutor() as pool:
        for status, tool_counter, arg_counter in pool.map(count_trial, trial_dirs):
            status_counts[status.value] += 1
            tool_call_counts.update(tool_counter)
            # keys() adds one per tool, so this counts trials, not calls
            tool_trial_counts.update(tool_counter.keys())
            for (harness_tool, arg_name, type_name), count in arg_counter.items():
                arg_type_counts[harness_tool][arg_name][type_name] += count

    # "x" refuses to overwrite a file that may already hold labels
    with paths.output_csv.open("x", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        # Sort so every run writes the same file
        for harness_tool, call_count in sorted(tool_call_counts.items()):
            prefix = [*harness_tool, "", call_count, tool_trial_counts[harness_tool]]
            # A tool that never had an argument still gets one row
            if harness_tool not in arg_type_counts:
                writer.writerow([*prefix, "", "", "", ""])
            for arg_name, type_counts in sorted(arg_type_counts[harness_tool].items()):
                value_types = "|".join(sorted(type_counts))
                # A call has each arg once, so total() is the arg's call count
                writer.writerow(
                    [*prefix, arg_name, "", type_counts.total(), value_types]
                )

    total_calls = sum(tool_call_counts.values())
    print(f"{status_counts}, {total_calls} calls, {len(tool_call_counts)} tools")


if __name__ == "__main__":
    main()
