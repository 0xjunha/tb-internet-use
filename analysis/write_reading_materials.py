"""Write for each picked trial the request rows and the text dump of its trajectory that its reader gets, beside a link to its raw trajectory file.

A reader reads the dump with short scripts of its own, so the dump marks the start of each step and of each part of it with a line in `[[ ]]`, which the text of a trajectory seldom holds, keeps of a long observation only its start and its end, where errors usually sit, and leaves out images, which only fill the reader's context.

Run it after `pick_trials.py` as `uv run python -I analysis/write_reading_materials.py <pipeline_run_dir> <raw_trials_dir> <out_dir>`.
"""

import argparse
import csv
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# `python -I` leaves the folder of this script off `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from output_files import write_csv
from pipeline_rows import (
    TRIAL_REQUEST_COLUMNS,
    RequestRow,
    read_request_rows_by_trial,
)
from trajectory_steps import MAIN_TRAJECTORY_ID, TrajectoryStep, trajectory_steps_of

# A longer observation keeps its first `OBSERVATION_HEAD_CHARACTERS` and its last `OBSERVATION_TAIL_CHARACTERS` characters.
OBSERVATION_HEAD_CHARACTERS = 1500
OBSERVATION_TAIL_CHARACTERS = 1000
# The start of the line before the steps of a subagent trajectory in the dump.
SUBAGENT_TRAJECTORY_HEADING = "[[[ subagent trajectory"
# A heading keeps this many characters of a `tool_call_id`, since some harnesses write ids of tens of thousands of characters.
HEADING_ID_CHARACTER_LIMIT = 40
# A result that gives its output as text and then again in sections, e.g. `out\n\n[stdout]\nout\n[metadata] {...}` of Claude Code.
_REPEATED_OUTPUT = re.compile(
    r"\A(?P<head>.*?)\n\n(?:\[stdout\]\n(?P<stdout>.*?))?(?:\n?\[stderr\]\n(?P<stderr>.*?))?(?:\n\[metadata\] (?P<metadata>\{[^\n]*\}))?\Z",
    re.DOTALL,
)
_DEFAULT_METADATA = '{"noOutputExpected": false}'
# An image written into text as a data URI, e.g. `data:image/png;base64,iVBOR...`.
_IMAGE_DATA_URI = re.compile(r"data:image/[\w.+-]+;base64,[A-Za-z0-9+/]+=*")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument(
        "pipeline_run_dir",
        type=Path,
        help="the output folder of a pipeline run, with network_request_rows.csv",
    )
    parser.add_argument("raw_trials_dir", type=Path)
    parser.add_argument(
        "out_dir", type=Path, help="the folder with picked_trials.csv of pick_trials.py"
    )
    arguments = parser.parse_args()

    trial_ids = picked_trial_ids_of(arguments.out_dir / "picked_trials.csv")
    request_rows_by_trial = read_request_rows_by_trial(
        arguments.pipeline_run_dir / "network_request_rows.csv",
        trial_ids=set(trial_ids),
    )
    largest_dump = (0, "")
    for trial_id in trial_ids:
        trial_out_dir = arguments.out_dir / "trials" / trial_id
        trial_out_dir.mkdir(parents=True, exist_ok=True)
        _write_request_rows(
            trial_out_dir / "requests.csv", request_rows_by_trial.get(trial_id, [])
        )
        trajectory = json.loads(
            (arguments.raw_trials_dir / trial_id / "trajectory.json").read_text()
        )
        _link_trajectory(
            trial_out_dir / "trajectory.json",
            (arguments.raw_trials_dir / trial_id / "trajectory.json").resolve(),
        )
        dump_text = trajectory_dump_text_of(trajectory)
        (trial_out_dir / "trajectory_dump.txt").write_text(dump_text)
        largest_dump = max(largest_dump, (len(dump_text), trial_id))
    print(
        f"wrote the materials of {len(trial_ids)} trials, the largest dump has {largest_dump[0]} characters ({largest_dump[1]})"
    )


def picked_trial_ids_of(picked_trials_path: Path) -> list[str]:
    """List the ids of the picked trials in file order, without empty slots."""
    with picked_trials_path.open(newline="") as csv_file:
        return [row["trial_id"] for row in csv.DictReader(csv_file) if row["trial_id"]]


def trajectory_dump_text_of(trajectory: dict[str, Any]) -> str:
    """Write a trajectory as text, one block per step, the steps of subagent trajectories after those of the agent under a heading of their own."""
    blocks: list[str] = []
    current_trajectory_id = MAIN_TRAJECTORY_ID
    for trajectory_step in trajectory_steps_of(trajectory):
        if trajectory_step.trajectory_id != current_trajectory_id:
            current_trajectory_id = trajectory_step.trajectory_id
            blocks.append(
                f"{SUBAGENT_TRAJECTORY_HEADING} {current_trajectory_id}, whose step ids count from 1 again ]]]"
            )
        blocks.append(step_block_of(trajectory_step))
    return "\n\n".join(blocks) + "\n"


def step_block_of(trajectory_step: TrajectoryStep) -> str:
    """Write one step as its heading line and a marked section for each of its message, reasoning, tool calls and observation results."""
    step = trajectory_step.step
    is_sidechain = trajectory_step.is_sidechain
    sidechain_text = (
        "not recorded" if is_sidechain is None else str(is_sidechain).lower()
    )
    lines = [
        f"[[[ step_id {step.get('step_id')} | source {step.get('source')} | is_sidechain {sidechain_text} ]]]"
    ]
    for heading, value in (
        ("message", step.get("message")),
        ("reasoning", step.get("reasoning_content")),
    ):
        text = content_text_of(value)
        if text:
            lines += [f"[[ {heading} ]]", text]
    for call_index, tool_call in enumerate(step.get("tool_calls") or []):
        if not isinstance(tool_call, dict):
            continue
        lines.append(
            f"[[ tool call {call_index}: {tool_call.get('function_name')} | tool_call_id {heading_id_of(tool_call.get('tool_call_id'))} ]]"
        )
        lines.append(arguments_text_of(tool_call.get("arguments")))
    observation = step.get("observation")
    results = observation.get("results") if isinstance(observation, dict) else None
    for result_index, result in enumerate(results or []):
        if not isinstance(result, dict):
            continue
        source_call_id = result.get("source_call_id")
        call_text = (
            f" | for tool_call_id {heading_id_of(source_call_id)}"
            if source_call_id
            else ""
        )
        lines.append(f"[[ observation result {result_index}{call_text} ]]")
        lines.append(
            cut_text_of(observation_text_of(result.get("content")), step.get("step_id"))
        )
    return "\n".join(lines)


def content_text_of(content: object) -> str:
    """Give the text of a message, reasoning or observation content, which is a string or a list of parts, with each image replaced by a marker."""
    if content is None:
        return ""
    if isinstance(content, str):
        return _IMAGE_DATA_URI.sub("[image data left out]", content)
    if isinstance(content, list):
        return "\n".join(_part_text_of(part) for part in content)
    return json.dumps(content, ensure_ascii=False)


def observation_text_of(content: object) -> str:
    """Give the text of an observation result, with output that the result repeats printed once, and a result that is a JSON object of plain values one value per line, e.g. `{"returncode": 0, "output": "..."}` of mini-swe-agent, so that its output keeps its lines."""
    text = text_without_repeated_output_of(content_text_of(content))
    if not text.startswith("{"):
        return text
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(value, dict) or not all(
        isinstance(item, str | int | float | bool) or item is None
        for item in value.values()
    ):
        return text
    return arguments_text_of(value)


def text_without_repeated_output_of(text: str) -> str:
    """Print once the output of a result that gives it twice, first as text and then under `[stdout]` and `[stderr]`, as Claude Code writes the result of `Bash`.

    The sections stay as they are, an empty `[stderr]` and the default `[metadata] {"noOutputExpected": false}` aside, and the first copy goes only when it holds the same words as the sections, e.g. not for a preview of a large output saved to a file.
    """
    match = _REPEATED_OUTPUT.match(text)
    if match is None or (match["stdout"] is None and match["stderr"] is None):
        return text
    stdout, stderr = match["stdout"] or "", match["stderr"] or ""
    if match["head"].split() != f"{stdout}\n{stderr}".split():
        return text
    sections = []
    if stdout.strip() or not stderr.strip():
        sections.append(f"[stdout]\n{stdout}")
    if stderr.strip():
        sections.append(f"[stderr]\n{stderr}")
    if match["metadata"] is not None and match["metadata"] != _DEFAULT_METADATA:
        sections.append(f"[metadata] {match['metadata']}")
    return "\n".join(sections)


def arguments_text_of(arguments: object) -> str:
    """Write the arguments of a tool call one per line, a string as it is so that a command or a file keeps its lines, any other value as JSON."""
    if not isinstance(arguments, dict):
        return content_text_of(arguments)
    return "\n".join(
        f"{name}: {content_text_of(value) if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}"
        for name, value in arguments.items()
    )


def heading_id_of(tool_call_id: object) -> str:
    """Give a `tool_call_id` as a heading shows it, its first `HEADING_ID_CHARACTER_LIMIT` characters and a marker when it is longer."""
    text = str(tool_call_id)
    if len(text) <= HEADING_ID_CHARACTER_LIMIT:
        return text
    left_out = len(text) - HEADING_ID_CHARACTER_LIMIT
    return f"{text[:HEADING_ID_CHARACTER_LIMIT]}... ({left_out} more characters)"


def cut_text_of(text: str, step_id: object) -> str:
    """Keep the first `OBSERVATION_HEAD_CHARACTERS` and the last `OBSERVATION_TAIL_CHARACTERS` characters of a longer text, with a marker of the cut between them."""
    if len(text) <= OBSERVATION_HEAD_CHARACTERS + OBSERVATION_TAIL_CHARACTERS:
        return text
    left_out = len(text) - OBSERVATION_HEAD_CHARACTERS - OBSERVATION_TAIL_CHARACTERS
    return (
        text[:OBSERVATION_HEAD_CHARACTERS]
        + f"\n[[ CUT here, {left_out} characters of this result left out, the whole result is in step_id {step_id} of trajectory.json ]]\n"
        + text[-OBSERVATION_TAIL_CHARACTERS:]
    )


def _part_text_of(part: object) -> str:
    """Give the text of one part of a content list, and for an image or another kind of part a marker with its type."""
    if not isinstance(part, dict):
        return content_text_of(part)
    if part.get("type") == "text":
        return content_text_of(part.get("text"))
    return f"[{part.get('type', 'untyped')} part left out]"


def _link_trajectory(link_path: Path, trajectory_path: Path) -> None:
    """Put a link to the raw trajectory file beside the dump, so that a prompt names one folder for every file of the trial."""
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    link_path.symlink_to(trajectory_path)


def _write_request_rows(path: Path, request_rows: Sequence[RequestRow]) -> None:
    write_csv(
        path,
        TRIAL_REQUEST_COLUMNS,
        (
            [getattr(row, column) for column in TRIAL_REQUEST_COLUMNS]
            for row in request_rows
        ),
    )


if __name__ == "__main__":
    main()
