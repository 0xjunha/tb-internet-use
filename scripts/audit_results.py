"""Audit tool result conversion on every raw trial and write the harness result format audit CSV.

The CSV goes to `out/tool_call_knowledge/` by default, which `.gitignore` keeps out of the repo, since its counts come from the trajectories.

It counts the calls, trials and example call keys of each (harness, tool, format).
It also counts coverage (results of an unknown format per tool), harness text of the templates left in the tool output, results that match more than one format of their list, byte-exact round trips of text formats, and cross-source checks.
Prints counts and masked shapes only, never result text.

Run it as `uv run python -I scripts/audit_results.py <raw_trials_dir> [output_csv] [--harness NAME ...] [--report PATH] [--limit N]`.
"""

import argparse
import csv
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from tb_internet_use.knowledge.harness_result_format_audit import (
    all_matches_of,
    format_kind_of,
    harness_text_patterns_of,
    iter_declared_formats,
    render_text_format,
)
from tb_internet_use.knowledge.harness_result_format_declaration import (
    HarnessResultFormat,
    HarnessTextResultFormat,
    MatchedValues,
    annotated_output_and_notice_names_of,
)
from tb_internet_use.knowledge.tool_call_knowledge import (
    ToolCallKnowledge,
    harness_tool_result_declaration_of,
)
from tb_internet_use.pipeline import read_trajectory
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call.harnesses import converter_for
from tb_internet_use.tool_call.harnesses.claude_code import structured_result_of
from tb_internet_use.tool_call.model import (
    HarnessToolCall,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    ToolCall,
    UnmatchedFormat,
)
from tb_internet_use.trial.model import UnreadableTrajectory

DEFAULT_OUTPUT_CSV = (
    Path(__file__).resolve().parents[1]
    / "out"
    / "tool_call_knowledge"
    / "harness_result_format_audit.csv"
)
CSV_COLUMNS = [
    "harness",
    "tool",
    "format",  # format name, or "unknown_format" and "skipped_format" rows per tool
    # text or json for a declared format, empty for the unknown_format and skipped_format rows
    "kind",
    "call_count",
    "trial_count",
    "example_calls",  # up to 3 keys, each `trial/trajectory#step.index`
    "roundtrip_mismatches",  # text formats whose `render_text_format(values)` differs from the annotated output
    "harness_text_hits",  # results whose tool output holds harness text of this tool's templates
    "multi_match",  # results that also matched another format of the list
]
MAX_EXAMPLES = 3
# Data runs use at most 4 processes, to leave the machine usable.
_PROCESS_COUNT = 4
UNKNOWN = str(UnmatchedFormat.UNKNOWN)
SKIPPED = str(UnmatchedFormat.SKIPPED)

type Key = tuple[str, str, str]  # harness, tool, format
type Shape = tuple[str, str, str]  # harness, tool, masked shape of an unknown format


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("raw_trials_dir", type=Path)
    parser.add_argument("output_csv", type=Path, nargs="?", default=DEFAULT_OUTPUT_CSV)
    parser.add_argument(
        "--harness",
        action="append",
        default=[],
        help="only trials of this harness (repeatable)",
    )
    parser.add_argument(
        "--report", type=Path, default=None, help="also write the report here"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="only the first N trial folders"
    )
    args = parser.parse_args()

    trial_dirs = sorted(
        entry.path for entry in os.scandir(args.raw_trials_dir) if entry.is_dir()
    )[: args.limit]
    harnesses = frozenset(args.harness)
    tally = Tally()
    with ProcessPoolExecutor(_PROCESS_COUNT) as pool:
        for trial_tally in pool.map(
            audit_trial, ((d, harnesses) for d in trial_dirs), chunksize=16
        ):
            tally.merge(trial_tally)

    text = report(tally)
    print(text, end="")
    if args.report:
        args.report.write_text(text)
    write_audit_csv(audit_rows(tally), args.output_csv)
    print(f"audit written: {args.output_csv}")


def audit_trial(args: tuple[str, frozenset[str]]) -> Tally:
    trial_dir, harnesses = args
    tally = Tally()
    harness_tool_calls = read_trajectory(Path(trial_dir))
    # A trial whose trajectory cannot be read counts as one without calls.
    if isinstance(harness_tool_calls, UnreadableTrajectory) or not harness_tool_calls:
        return tally
    if harnesses and harness_tool_calls[0].tool.harness not in harnesses:
        return tally
    trial_seen = TrialSeen()
    tool_calls = convert_tool_calls(
        harness_tool_calls,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    for tool_call in tool_calls:
        if tool_call.result is not None:
            audit_result(tally, tool_call, trial_seen)
    audit_links(tally, tool_calls)
    tally.trial_counts.update(trial_seen.format_keys)
    tally.unknown_format_trial_counts.update(trial_seen.unknown_shapes)
    return tally


def audit_result(tally: Tally, tool_call: ToolCall, trial_seen: TrialSeen) -> None:
    """Record what one result matched and the checks that apply to it."""
    harness_tool_call, tool_call_result = tool_call.harness_tool_call, tool_call.result
    assert harness_tool_call.result is not None and tool_call_result is not None
    harness, tool = harness_tool_call.tool.harness, harness_tool_call.tool.name
    name = str(tool_call_result.harness_result_format)  # the format column of both CSVs
    key = (harness, tool, name)
    tally.call_counts[key] += 1
    trial_seen.format_keys.add(key)
    example_call_keys = tally.example_call_keys.setdefault(key, [])
    if len(example_call_keys) < MAX_EXAMPLES:
        example_call_keys.append(call_key(harness_tool_call))
    tally.status_counts[
        (harness, tool, name, tool_call_result.execution_status.value)
    ] += 1

    converter = converter_for(harness)
    harness_tool_result_declaration = harness_tool_result_declaration_of(
        harness_tool_call.tool
    )
    tool_result_raw_text = converter.tool_result_raw_text_of(
        harness_tool_call, harness_tool_call.result
    )
    tool_result_json = (
        converter.tool_result_json_of(harness_tool_call, harness_tool_call.result)
        if harness_tool_result_declaration.json_formats is not None
        else None
    )
    selected_format_list = harness_tool_result_declaration.format_list_for_result(
        tool_result_json,
        is_marked_as_error=converter.is_marked_as_error(
            harness_tool_call, harness_tool_call.result
        ),
    )
    if selected_format_list is UnmatchedFormat.SKIPPED:
        return
    if isinstance(selected_format_list, UnmatchedFormat):
        # A tool with JSON formats only has no list for a text result, so its raw text is the annotated output, with no notices to cut.
        annotated = None if tool_result_raw_text is None else (tool_result_raw_text, [])
    else:
        annotated = annotated_output_and_notice_names_of(
            tool_result_raw_text, tool_result_json, selected_format_list
        )
    if annotated is None:
        return
    if tool_call_result.harness_result_format is UnmatchedFormat.UNKNOWN:
        shape = (
            "json keys=" + ",".join(sorted(tool_result_json))[:70]
            if tool_result_json is not None
            else edges(tool_result_raw_text or "")
        )
        tally.unknown_format_call_counts[(harness, tool, shape)] += 1
        trial_seen.unknown_shapes.add((harness, tool, shape))
        return
    if isinstance(selected_format_list, UnmatchedFormat):
        return
    annotated_output, cut_notice_names = annotated
    for cut_notice_name in cut_notice_names:
        tally.cut_notice_counts[(harness, tool, cut_notice_name)] += 1
    matches = all_matches_of(selected_format_list, annotated_output)
    if len(matches) > 1:
        tally.multi_match_counts[
            (
                harness,
                tool,
                " > ".join(
                    harness_result_format.name for harness_result_format, _ in matches
                ),
            )
        ] += 1
    if matches:
        harness_result_format, matched_values = matches[0]
        if (
            isinstance(harness_result_format, HarnessTextResultFormat)
            and render_text_format(harness_result_format, matched_values)
            != annotated_output
        ):
            tally.roundtrip_mismatch_counts[
                (harness, tool, harness_result_format.name)
            ] += 1
        if harness == "claude-code":
            check_claude_code(
                tally, harness_tool_call, harness_result_format, matched_values
            )
    if tool_call_result.tool_output_text:
        for part, pattern in harness_text_patterns_of(selected_format_list):
            if pattern.search(tool_call_result.tool_output_text):
                tally.harness_text_hit_counts[(harness, tool, name, part[:40])] += 1
                break


@dataclass
class TrialSeen:
    """Record of what one trial had at least once, kept for the trial counts."""

    format_keys: set[Key] = field(default_factory=set)
    unknown_shapes: set[Shape] = field(default_factory=set)


def call_key(harness_tool_call: HarnessToolCall) -> str:
    key = harness_tool_call.key
    return f"{key.trial_id}/{key.trajectory_id}#{key.step_id}.{key.call_index}"


def edges(text: str) -> str:
    lines = text.split("\n")
    return (
        f"first={mask(lines[0])!r} last={mask(lines[-1])!r} lines={min(len(lines), 50)}"
    )


def mask(text: str, limit: int = 70) -> str:
    """Replace paths, ids and numbers so a line shows only its shape."""
    text = re.sub(r"[^\x20-\x7e]", "?", text)
    text = re.sub(r"(?:[A-Za-z]:)?/[^\s'\",)\]}>]+", "<p>", text)
    text = re.sub(r"\b[0-9a-fA-F-]{12,}\b", "<hex>", text)
    text = re.sub(r"\b[A-Za-z0-9_]{20,}\b", "<tok>", text)
    text = re.sub(r"\d+", "9", text)
    return text[:limit]


def check_claude_code(
    tally: Tally,
    harness_tool_call: HarnessToolCall,
    harness_result_format: HarnessResultFormat[Any],
    matched_values: MatchedValues,
) -> None:
    """Compare what the format gave with Claude Code's structured result, an independent source."""
    structured_result = structured_result_of(harness_tool_call.result or {})
    if not structured_result:
        return
    harness, tool = harness_tool_call.tool.harness, harness_tool_call.tool.name
    text = harness_result_format.tool_output_text_of(matched_values)

    def record(check: str, same: bool) -> None:
        tally.cross_check_counts[
            (
                harness,
                tool,
                check,
                f"{'same' if same else 'differs'} ({harness_result_format.name})",
            )
        ] += 1

    if tool == "Bash" and text is not None:
        record(
            "format_text_vs_stdout",
            text.strip() == (structured_result.get("stdout") or "").strip(),
        )
    if tool == "Bash" and structured_result.get("backgroundTaskId"):
        record(
            "format_handle_vs_backgroundTaskId",
            matched_values.get("handle") == structured_result["backgroundTaskId"],
        )
    content = (structured_result.get("file") or {}).get("content")
    if tool == "Read" and text is not None and isinstance(content, str):
        record("format_text_vs_file_content", text.strip() == content.strip())


def audit_links(tally: Tally, tool_calls: Sequence[ToolCall]) -> None:
    issued: set[str] = set()
    pending_paths: dict[str, tuple[str, str]] = {}
    for tool_call in tool_calls:
        harness, tool = (
            tool_call.harness_tool_call.tool.harness,
            tool_call.harness_tool_call.tool.name,
        )
        action = tool_call.action
        if isinstance(action, PollAction):
            for handle in action.handles:
                outcome = "issued_earlier" if handle.id in issued else "not_issued"
                tally.cross_check_counts[(harness, tool, "polled_handle", outcome)] += 1
        if isinstance(action, ReadFileAction) and action.path in pending_paths:
            tally.cross_check_counts[
                (*pending_paths.pop(action.path), "output_path", "read_later")
            ] += 1
        if isinstance(action, RunCommandAction) and action.command_str:
            for path in [p for p in pending_paths if p in action.command_str]:
                tally.cross_check_counts[
                    (*pending_paths.pop(path), "output_path", "used_in_command_later")
                ] += 1
        tool_call_result = tool_call.result
        if tool_call_result is None:
            continue
        issued.update(handle.id for handle in tool_call_result.handles)
        if tool_call_result.output_path:
            pending_paths.setdefault(tool_call_result.output_path, (harness, tool))
    for owner in pending_paths.values():
        tally.cross_check_counts[(*owner, "output_path", "not_read_later")] += 1


def report(tally: Tally) -> str:
    lines: list[str] = []
    by_tool: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for (harness, tool, name), count in tally.call_counts.items():
        by_tool[(harness, tool)][name] += count
    lines.append(
        "== coverage (harness, tool): total | unknown_format | skipped_format | unknown status"
    )
    for (harness, tool), counts in sorted(by_tool.items()):
        unknown = sum(
            v
            for (h, t, f, s), v in tally.status_counts.items()
            if (h, t) == (harness, tool) and s == "unknown"
        )
        lines.append(
            f"{sum(counts.values()):>8}  {harness} {tool}: unknown_format={counts.get(UNKNOWN, 0)}"
            f" skipped_format={counts.get(SKIPPED, 0)} unknown_status={unknown}"
        )
    lines += _section(
        "formats (calls, trials)",
        (
            (v, f"{k} trials={tally.trial_counts.get(k, 0)}")
            for k, v in tally.call_counts.items()
        ),
        400,
    )
    lines += _section(
        "status by format", ((v, str(k)) for k, v in tally.status_counts.items()), 400
    )
    lines += _section(
        "unknown_format shapes (calls, trials)",
        (
            (v, f"{k} trials={tally.unknown_format_trial_counts.get(k, 0)}")
            for k, v in tally.unknown_format_call_counts.items()
        ),
        80,
    )
    lines += _section(
        "multi-match (first > also)",
        ((v, str(k)) for k, v in tally.multi_match_counts.items()),
    )
    lines += _section(
        "harness text left in tool output",
        ((v, str(k)) for k, v in tally.harness_text_hit_counts.items()),
    )
    lines += _section(
        "round-trip mismatches",
        ((v, str(k)) for k, v in tally.roundtrip_mismatch_counts.items()),
    )
    lines += _section(
        "notices cut out", ((v, str(k)) for k, v in tally.cut_notice_counts.items())
    )
    lines += _section(
        "cross-source checks",
        ((v, str(k)) for k, v in tally.cross_check_counts.items()),
        200,
    )
    return "\n".join(lines) + "\n"


def _section(title: str, rows: Iterable[tuple[int, str]], limit: int = 40) -> list[str]:
    lines = [f"== {title}"]
    for count, label in sorted(rows, reverse=True)[:limit]:
        lines.append(f"{count:>8}  {label}")
    return lines


def write_audit_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def audit_rows(tally: Tally) -> list[dict[str, str]]:
    """List the declared formats in the order of the table of declared result formats, then the unknown and skipped results seen per tool, sorted."""
    rows: list[dict[str, str]] = []
    declared: set[Key] = set()
    for harness, tool, harness_result_format in iter_declared_formats():
        key = (harness, tool, harness_result_format.name)
        declared.add(key)
        rows.append(_row(tally, key, format_kind_of(harness_result_format)))
    # Every matched format is declared, so the other keys are `unknown_format` and `skipped_format`.
    for key in sorted(tally.call_counts):
        if key not in declared:
            rows.append(_row(tally, key, ""))
    return rows


def _row(tally: Tally, key: Key, kind: str) -> dict[str, str]:
    harness, tool, name = key
    return {
        "harness": harness,
        "tool": tool,
        "format": name,
        "kind": kind,
        "call_count": str(tally.call_counts.get(key, 0)),
        "trial_count": str(tally.trial_counts.get(key, 0)),
        "example_calls": " ".join(tally.example_call_keys.get(key, [])),
        "roundtrip_mismatches": str(tally.roundtrip_mismatch_counts.get(key, 0)),
        "harness_text_hits": str(
            sum(v for k, v in tally.harness_text_hit_counts.items() if k[:3] == key)
        ),
        "multi_match": str(
            sum(
                v
                for k, v in tally.multi_match_counts.items()
                if k[:2] == key[:2] and name in k[2].split(" > ")
            )
        ),
    }


@dataclass
class Tally:
    """Tally of the counts of one trial or, once the main process merges them, of many, keyed by names and never by result text."""

    call_counts: Counter[Key] = field(default_factory=Counter)
    trial_counts: Counter[Key] = field(default_factory=Counter)
    example_call_keys: dict[Key, list[str]] = field(default_factory=dict)
    status_counts: Counter[tuple[str, str, str, str]] = field(default_factory=Counter)
    unknown_format_call_counts: Counter[Shape] = field(default_factory=Counter)
    unknown_format_trial_counts: Counter[Shape] = field(default_factory=Counter)
    multi_match_counts: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    harness_text_hit_counts: Counter[tuple[str, str, str, str]] = field(
        default_factory=Counter
    )
    roundtrip_mismatch_counts: Counter[Key] = field(default_factory=Counter)
    cut_notice_counts: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    cross_check_counts: Counter[tuple[str, str, str, str]] = field(
        default_factory=Counter
    )

    def merge(self, other: Tally) -> None:
        for name in (f.name for f in fields(self)):
            counts = getattr(self, name)
            if isinstance(counts, Counter):
                counts.update(getattr(other, name))
        for key, example_call_keys in other.example_call_keys.items():
            kept = self.example_call_keys.setdefault(key, [])
            kept.extend(example_call_keys[: MAX_EXAMPLES - len(kept)])


if __name__ == "__main__":
    main()
