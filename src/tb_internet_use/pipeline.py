"""Open the files of one trial, make the doors of outside knowledge and call the steps of the pipeline in order, which take text and types and never a path."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tb_internet_use.expanded_tool_call import expand_tool_calls
from tb_internet_use.expanded_tool_call.model import ExpandedToolCall
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    ExpandedToolCallKnowledge,
)
from tb_internet_use.knowledge.network_request_knowledge import (
    NetworkRequestKnowledge,
)
from tb_internet_use.knowledge.network_request_result_knowledge import (
    NetworkRequestResultKnowledge,
)
from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.network_request import extract_network_requests
from tb_internet_use.network_request.model import (
    NetworkRequest,
    NoNetworkRequestReason,
)
from tb_internet_use.network_request_result import decide_network_request_results
from tb_internet_use.network_request_result.model import (
    NetworkRequestResult,
    OutputLineKind,
    UnusedOutputLineReason,
)
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call.model import HarnessToolCall
from tb_internet_use.tool_call.parse_trajectory import parse_trajectory
from tb_internet_use.trial.model import (
    TrialFileTexts,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)

_TRAJECTORY_FILE_NAME = "trajectory.json"
_DETAIL_FILE_NAME = "detail.json"
_STATUS_FILE_NAME = "status.json"


def read_trajectory(
    trial_dir: Path,
) -> tuple[HarnessToolCall, ...] | UnreadableTrajectory:
    """Read the tool calls of one trial from the trajectory file in its folder, or an `UnreadableTrajectory` when the file is missing or is not JSON.

    The name of the folder is the trial id of the calls.
    """
    try:
        # The bytes go to `parse_trajectory` as they are, so that it also reports broken UTF-8.
        trajectory_text = (trial_dir / _TRAJECTORY_FILE_NAME).read_bytes()
    except FileNotFoundError:
        return UnreadableTrajectory(UnreadableTrajectoryReason.MISSING)
    return parse_trajectory(trajectory_text, trial_dir.name)


def read_trial_file_texts(trial_dir: Path) -> TrialFileTexts:
    """Read the detail file and the status file of one trial folder as bytes, for `collect_trials`.

    The name of the folder is the trial id. The bytes go to `collect_trials` as they are, so that its reading functions report broken UTF-8 or JSON with the trial id. A missing file raises `FileNotFoundError`.
    """
    return TrialFileTexts(
        trial_id=trial_dir.name,
        detail_text=(trial_dir / _DETAIL_FILE_NAME).read_bytes(),
        status_text=(trial_dir / _STATUS_FILE_NAME).read_bytes(),
    )


@dataclass(frozen=True, slots=True)
class KnowledgeDoors:
    """Doors of outside knowledge that the steps of one run ask, made from the catalogs of the repo and passed to each entry function as its `knowledge`.

    Each door counts its lookups in its `uses`, so a caller that makes new doors for each trial gets the lookups of that trial.
    """

    tool_call_knowledge: ToolCallKnowledge = field(default_factory=ToolCallKnowledge)
    expanded_tool_call_knowledge: ExpandedToolCallKnowledge = field(
        default_factory=ExpandedToolCallKnowledge
    )
    network_request_knowledge: NetworkRequestKnowledge = field(
        default_factory=NetworkRequestKnowledge
    )
    network_request_result_knowledge: NetworkRequestResultKnowledge = field(
        default_factory=NetworkRequestResultKnowledge
    )


def run_steps_to_expanded_tool_calls(
    harness_tool_calls: Sequence[HarnessToolCall],
    *,
    knowledge_doors: KnowledgeDoors,
    tool_call_judgment_rule_use_counts: Counter[str],
    expanded_tool_call_judgment_rule_use_counts: Counter[str],
) -> tuple[ExpandedToolCall, ...]:
    """Run `convert_tool_calls` and then `expand_tool_calls` on the tool calls of one trial, with the doors of `knowledge_doors`.

    Each step counts the uses of its judgment rules in its own counter, e.g. `treat_lines_joined_after_three_repairs_as_left_joined` in `tool_call_judgment_rule_use_counts` when `convert_tool_calls` splits a shell text and in `expanded_tool_call_judgment_rule_use_counts` when `expand_tool_calls` splits the text of a file it follows.
    Each `ExpandedToolCall` holds its `ToolCall`, so the output of `convert_tool_calls` is not returned apart.
    """
    tool_calls = convert_tool_calls(
        harness_tool_calls,
        knowledge=knowledge_doors.tool_call_knowledge,
        judgment_rule_use_counts=tool_call_judgment_rule_use_counts,
    )
    return expand_tool_calls(
        tool_calls,
        knowledge=knowledge_doors.expanded_tool_call_knowledge,
        judgment_rule_use_counts=expanded_tool_call_judgment_rule_use_counts,
    )


def run_steps_to_network_requests(
    harness_tool_calls: Sequence[HarnessToolCall],
    *,
    knowledge_doors: KnowledgeDoors,
    tool_call_judgment_rule_use_counts: Counter[str],
    expanded_tool_call_judgment_rule_use_counts: Counter[str],
    network_request_judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
) -> tuple[NetworkRequest, ...]:
    """Run `convert_tool_calls`, `expand_tool_calls` and then `extract_network_requests` on the tool calls of one trial, with the doors of `knowledge_doors`.

    Each step counts the uses of its judgment rules in its own counter, as in `run_steps_to_expanded_tool_calls`, and `extract_network_requests` counts in `no_network_request_counts` each program run, code call or URL in code that gave no request, by its reason.
    """
    expanded_tool_calls = run_steps_to_expanded_tool_calls(
        harness_tool_calls,
        knowledge_doors=knowledge_doors,
        tool_call_judgment_rule_use_counts=tool_call_judgment_rule_use_counts,
        expanded_tool_call_judgment_rule_use_counts=expanded_tool_call_judgment_rule_use_counts,
    )
    return extract_network_requests(
        expanded_tool_calls,
        knowledge=knowledge_doors.network_request_knowledge,
        judgment_rule_use_counts=network_request_judgment_rule_use_counts,
        no_network_request_counts=no_network_request_counts,
    )


def run_steps_to_network_request_results(
    harness_tool_calls: Sequence[HarnessToolCall],
    *,
    knowledge_doors: KnowledgeDoors,
    tool_call_judgment_rule_use_counts: Counter[str],
    expanded_tool_call_judgment_rule_use_counts: Counter[str],
    network_request_judgment_rule_use_counts: Counter[str],
    no_network_request_counts: Counter[NoNetworkRequestReason],
    network_request_result_judgment_rule_use_counts: Counter[str],
    unused_output_line_counts: Counter[tuple[UnusedOutputLineReason, OutputLineKind]],
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ],
) -> tuple[NetworkRequestResult, ...]:
    """Run `convert_tool_calls`, `expand_tool_calls`, `extract_network_requests` and then `decide_network_request_results` on the tool calls of one trial, with the doors of `knowledge_doors`.

    Each step counts the uses of its judgment rules in its own counter, as in `run_steps_to_network_requests`, and `decide_network_request_results` counts in `unused_output_line_counts` and `program_counts_of_unowned_output_lines` each output line that a pattern fits and that gave no evidence.
    Each `NetworkRequestResult` holds its `NetworkRequest`, so the output of `extract_network_requests` is not returned apart.
    """
    expanded_tool_calls = run_steps_to_expanded_tool_calls(
        harness_tool_calls,
        knowledge_doors=knowledge_doors,
        tool_call_judgment_rule_use_counts=tool_call_judgment_rule_use_counts,
        expanded_tool_call_judgment_rule_use_counts=expanded_tool_call_judgment_rule_use_counts,
    )
    network_requests = extract_network_requests(
        expanded_tool_calls,
        knowledge=knowledge_doors.network_request_knowledge,
        judgment_rule_use_counts=network_request_judgment_rule_use_counts,
        no_network_request_counts=no_network_request_counts,
    )
    return decide_network_request_results(
        expanded_tool_calls,
        network_requests,
        knowledge=knowledge_doors.network_request_result_knowledge,
        judgment_rule_use_counts=network_request_result_judgment_rule_use_counts,
        unused_output_line_counts=unused_output_line_counts,
        program_counts_of_unowned_output_lines=program_counts_of_unowned_output_lines,
    )
