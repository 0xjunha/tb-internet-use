"""Audit tool result conversion on every raw trial and write the harness result format audit CSV.

For each (harness, tool, format): calls, trials and example call keys. Also coverage
(results of an unknown format per tool), harness text of the templates left in the tool output, results that match more than
one format of their list, byte-exact round trips of text formats, and cross-source checks.
Prints counts and masked shapes only, never result text.

Usage: uv run python -I scripts/audit_results.py <raw_trials_dir> [output_csv]
           [--harness NAME ...] [--report PATH] [--limit N]
"""

import argparse
import csv
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tb_internet_use.toolcall.atif_reader import read_trial_tool_calls
from tb_internet_use.toolcall.convert import convert_call
from tb_internet_use.toolcall.harnesses import CONVERTERS, converter_for
from tb_internet_use.toolcall.model import (
    PollAction,
    RawToolCall,
    ReadFileAction,
    RunCommandAction,
    ToolCall,
    UnmatchedFormat,
)
from tb_internet_use.toolcall.result_format_audit import (
    format_kind,
    harness_text_patterns,
    matching_format_names,
    render_text_format,
)
from tb_internet_use.toolcall.result_formats import (
    HarnessResultFormatList,
    HarnessTextResultFormat,
    JsonObject,
)

PACKAGE_DIR = Path(__file__).parents[1] / "src/tb_internet_use"
DEFAULT_OUTPUT_CSV = PACKAGE_DIR / "toolcall/catalogs/harness_result_format_audit.csv"
CSV_COLUMNS = [
    "harness",
    "tool",
    "format",  # format name; also "unknown_format" and "skipped_format" rows per tool
    # text or json for a declared format, special for one built by converter code,
    # empty for the unknown_format and skipped_format rows
    "kind",
    "call_count",
    "trial_count",
    "example_calls",  # up to 3 keys: trial/trajectory#step.index
    "roundtrip_mismatches",  # text formats: render_text_format(values) != annotated output
    "harness_text_hits",  # results whose tool output holds harness text of this tool's templates
    "multi_match",  # results that also matched another format of the list
]
MAX_EXAMPLES = 3
UNKNOWN = str(UnmatchedFormat.UNKNOWN)
SKIPPED = str(UnmatchedFormat.SKIPPED)
SPECIAL = {UNKNOWN, SKIPPED}

type Key = tuple[str, str, str]  # harness, tool, format


@dataclass
class Tally:
    """Counts of one or more trials; everything is keyed by names, never by result text."""

    calls: Counter[Key] = field(default_factory=Counter)
    trials: Counter[Key] = field(default_factory=Counter)
    examples: dict[Key, list[str]] = field(default_factory=dict)
    status: Counter[tuple[str, str, str, str]] = field(default_factory=Counter)
    unknown_format: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    unknown_format_trials: Counter[tuple[str, str, str]] = field(
        default_factory=Counter
    )
    multi: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    harness_text_hits: Counter[tuple[str, str, str, str]] = field(
        default_factory=Counter
    )
    roundtrip: Counter[Key] = field(default_factory=Counter)
    notices: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    cross: Counter[tuple[str, str, str, str]] = field(default_factory=Counter)

    def merge(self, other: Tally) -> None:
        for name in (
            "calls",
            "trials",
            "status",
            "unknown_format",
            "unknown_format_trials",
            "multi",
            "harness_text_hits",
            "roundtrip",
            "notices",
            "cross",
        ):
            getattr(self, name).update(getattr(other, name))
        for key, examples in other.examples.items():
            kept = self.examples.setdefault(key, [])
            kept.extend(examples[: MAX_EXAMPLES - len(kept)])


def mask(text: str, limit: int = 70) -> str:
    """Replace paths, ids and numbers so a line shows only its shape."""
    text = re.sub(r"[^\x20-\x7e]", "?", text)
    text = re.sub(r"(?:[A-Za-z]:)?/[^\s'\",)\]}>]+", "<p>", text)
    text = re.sub(r"\b[0-9a-fA-F-]{12,}\b", "<hex>", text)
    text = re.sub(r"\b[A-Za-z0-9_]{20,}\b", "<tok>", text)
    text = re.sub(r"\d+", "9", text)
    return text[:limit]


def edges(text: str) -> str:
    lines = text.split("\n")
    return (
        f"first={mask(lines[0])!r} last={mask(lines[-1])!r} lines={min(len(lines), 50)}"
    )


def call_key(raw: RawToolCall) -> str:
    key = raw.key
    return f"{key.trial_id}/{key.trajectory_id}#{key.step_id}.{key.call_index}"


def structured_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Claude Code's `tool_use_result`, an independent source for stdout, task id and file content."""
    metadata = (result.get("extra") or {}).get("tool_result_metadata") or {}
    structured = metadata.get("tool_use_result")
    return structured if isinstance(structured, dict) else {}


def check_claude_code(
    tally: Tally,
    raw: RawToolCall,
    selected_formats: HarnessResultFormatList[Any],
    annotated_output: str,
) -> None:
    structured = structured_result(raw.result or {})
    found = selected_formats.match(annotated_output)
    if not structured or found is None:
        return
    fmt, values = found
    harness, tool = raw.tool.harness, raw.tool.name
    text = fmt.tool_output_text_of(values)

    def record(check: str, same: bool) -> None:
        tally.cross[
            (harness, tool, check, f"{'same' if same else 'differs'} ({fmt.name})")
        ] += 1

    if tool == "Bash" and text is not None:
        record(
            "format_text_vs_stdout",
            text.strip() == (structured.get("stdout") or "").strip(),
        )
    if tool == "Bash" and structured.get("backgroundTaskId"):
        record(
            "format_handle_vs_backgroundTaskId",
            values.get("handle") == structured["backgroundTaskId"],
        )
    content = (structured.get("file") or {}).get("content")
    if tool == "Read" and text is not None and isinstance(content, str):
        record("format_text_vs_file_content", text.strip() == content.strip())


def audit_result(
    tally: Tally, raw: RawToolCall, call: ToolCall, seen: set[Any]
) -> None:
    """Record what one result matched and the checks that apply to it."""
    assert raw.result is not None and call.output is not None
    harness, tool = raw.tool.harness, raw.tool.name
    output = call.output
    name = str(output.harness_result_format)  # the format column of both CSVs
    key = (harness, tool, name)
    tally.calls[key] += 1
    seen.add(("format", key))
    examples = tally.examples.setdefault(key, [])
    if len(examples) < MAX_EXAMPLES:
        examples.append(call_key(raw))
    tally.status[(harness, tool, name, output.execution_status.value)] += 1

    converter = converter_for(harness)
    raw_text = converter.extract_tool_result_raw_text(raw, raw.result)
    tool_result_json = converter.extract_tool_result_json(raw, raw.result)
    selected_formats = converter.select_formats(raw, raw.result, tool_result_json)
    if selected_formats is None or (tool_result_json is None and raw_text is None):
        return
    if output.harness_result_format is UnmatchedFormat.UNKNOWN:
        shape = (
            "json keys=" + ",".join(sorted(tool_result_json))[:70]
            if tool_result_json is not None
            else edges(raw_text or "")
        )
        tally.unknown_format[(harness, tool, shape)] += 1
        seen.add((UNKNOWN, harness, tool, shape))
        return
    annotated_output: str | JsonObject
    if tool_result_json is not None:
        annotated_output = tool_result_json
    else:
        annotated_output, cut_names = selected_formats.strip_notices(raw_text or "")
        for cut_name in cut_names:
            tally.notices[(harness, tool, cut_name)] += 1
    names = matching_format_names(selected_formats, annotated_output)
    if len(names) > 1:
        tally.multi[(harness, tool, " > ".join(names))] += 1
    found = selected_formats.match(annotated_output)
    if found is not None:
        fmt, values = found
        if (
            isinstance(fmt, HarnessTextResultFormat)
            and render_text_format(fmt, values) != annotated_output
        ):
            tally.roundtrip[(harness, tool, fmt.name)] += 1
    if output.tool_output_text:
        for part, pattern in harness_text_patterns(selected_formats):
            if pattern.search(output.tool_output_text):
                tally.harness_text_hits[(harness, tool, name, part[:40])] += 1
                break
    if harness == "claude-code" and isinstance(annotated_output, str):
        check_claude_code(tally, raw, selected_formats, annotated_output)


def audit_links(tally: Tally, calls: list[tuple[RawToolCall, ToolCall]]) -> None:
    issued: set[str] = set()
    pending_paths: dict[str, tuple[str, str]] = {}
    for raw, call in calls:
        harness, tool = raw.tool.harness, raw.tool.name
        action = call.action
        if isinstance(action, PollAction):
            for handle in action.handles:
                outcome = "issued_earlier" if handle.id in issued else "not_issued"
                tally.cross[(harness, tool, "polled_handle", outcome)] += 1
        if isinstance(action, ReadFileAction) and action.path in pending_paths:
            tally.cross[
                (*pending_paths.pop(action.path), "output_path", "read_later")
            ] += 1
        if isinstance(action, RunCommandAction) and action.command_str:
            for path in [p for p in pending_paths if p in action.command_str]:
                tally.cross[
                    (*pending_paths.pop(path), "output_path", "used_in_command_later")
                ] += 1
        output = call.output
        if output is None:
            continue
        issued.update(handle.id for handle in output.handles)
        if output.output_path:
            pending_paths.setdefault(output.output_path, (harness, tool))
    for owner in pending_paths.values():
        tally.cross[(*owner, "output_path", "not_read_later")] += 1


def audit_trial(args: tuple[str, frozenset[str]]) -> Tally:
    trial_dir, harnesses = args
    tally = Tally()
    trial = read_trial_tool_calls(Path(trial_dir))
    if not trial.calls or (harnesses and trial.calls[0].tool.harness not in harnesses):
        return tally
    seen: set[Any] = set()
    calls: list[tuple[RawToolCall, ToolCall]] = []
    for raw in trial.calls:
        call = convert_call(raw, converter_for(raw.tool.harness))
        calls.append((raw, call))
        if raw.result is None or call.output is None:
            continue
        audit_result(tally, raw, call, seen)
    audit_links(tally, calls)
    for item in seen:
        if item[0] == "format":
            tally.trials[item[1]] += 1
        else:
            tally.unknown_format_trials[item[1:]] += 1
    return tally


def audit_rows(tally: Tally) -> list[dict[str, str]]:
    """Declared formats in the catalog's order, then the other formats seen, sorted."""
    rows: list[dict[str, str]] = []
    declared: set[Key] = set()
    for harness, converter in CONVERTERS.items():
        for tool, formats in converter.declared_formats():
            for fmt in formats.formats:
                key = (harness, tool, fmt.name)
                declared.add(key)
                rows.append(_row(tally, key, format_kind(fmt)))
    for key in sorted(tally.calls):
        if key not in declared:
            rows.append(_row(tally, key, "special" if key[2] not in SPECIAL else ""))
    return rows


def _row(tally: Tally, key: Key, kind: str) -> dict[str, str]:
    harness, tool, name = key
    return {
        "harness": harness,
        "tool": tool,
        "format": name,
        "kind": kind,
        "call_count": str(tally.calls.get(key, 0)),
        "trial_count": str(tally.trials.get(key, 0)),
        "example_calls": " ".join(tally.examples.get(key, [])),
        "roundtrip_mismatches": str(tally.roundtrip.get(key, 0)),
        "harness_text_hits": str(
            sum(v for k, v in tally.harness_text_hits.items() if k[:3] == key)
        ),
        "multi_match": str(
            sum(
                v
                for k, v in tally.multi.items()
                if k[:2] == key[:2] and name in k[2].split(" > ")
            )
        ),
    }


def write_audit_csv(rows: list[dict[str, str]], path: Path) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _section(title: str, rows: Iterable[tuple[int, str]], limit: int = 40) -> list[str]:
    lines = [f"== {title}"]
    for count, label in sorted(rows, reverse=True)[:limit]:
        lines.append(f"{count:>8}  {label}")
    return lines


def report(tally: Tally) -> str:
    lines: list[str] = []
    by_tool: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for (harness, tool, name), count in tally.calls.items():
        by_tool[(harness, tool)][name] += count
    lines.append(
        "== coverage (harness, tool): total | unknown_format | skipped_format | unknown status"
    )
    for (harness, tool), counts in sorted(by_tool.items()):
        unknown = sum(
            v
            for (h, t, f, s), v in tally.status.items()
            if (h, t) == (harness, tool) and s == "unknown"
        )
        lines.append(
            f"{sum(counts.values()):>8}  {harness} {tool}: unknown_format={counts.get(UNKNOWN, 0)}"
            f" skipped_format={counts.get(SKIPPED, 0)} unknown_status={unknown}"
        )
    lines += _section(
        "formats (calls, trials)",
        ((v, f"{k} trials={tally.trials.get(k, 0)}") for k, v in tally.calls.items()),
        400,
    )
    lines += _section(
        "status by format", ((v, str(k)) for k, v in tally.status.items()), 400
    )
    lines += _section(
        "unknown_format shapes (calls, trials)",
        (
            (v, f"{k} trials={tally.unknown_format_trials.get(k, 0)}")
            for k, v in tally.unknown_format.items()
        ),
        80,
    )
    lines += _section(
        "multi-match (first > also)", ((v, str(k)) for k, v in tally.multi.items())
    )
    lines += _section(
        "harness text left in tool output",
        ((v, str(k)) for k, v in tally.harness_text_hits.items()),
    )
    lines += _section(
        "round-trip mismatches", ((v, str(k)) for k, v in tally.roundtrip.items())
    )
    lines += _section(
        "notices cut out", ((v, str(k)) for k, v in tally.notices.items())
    )
    lines += _section(
        "cross-source checks", ((v, str(k)) for k, v in tally.cross.items()), 200
    )
    return "\n".join(lines) + "\n"


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
    with ProcessPoolExecutor(max_workers=max(2, (os.cpu_count() or 2) - 2)) as pool:
        for part in pool.map(
            audit_trial, ((d, harnesses) for d in trial_dirs), chunksize=16
        ):
            tally.merge(part)

    text = report(tally)
    print(text, end="")
    if args.report:
        args.report.write_text(text)
    write_audit_csv(audit_rows(tally), args.output_csv)
    print(f"audit written: {args.output_csv}")


if __name__ == "__main__":
    main()
