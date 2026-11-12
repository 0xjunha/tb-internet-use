"""Run stages 8 to 10 on raw trials, count what they find and check invariants, to see a change's effect on the full data.

It prints counts, enum values and invariant names only, never text from a trajectory.

Usage: nice -n 10 uv run python -I scripts/audit_interpretation.py <raw_trials_dir> [--sample N] [--out counts.json] [--compare old.json]
"""

import argparse
import json
import random
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from tb_internet_use.callrun.model import CallRun, FileText, PollInputText
from tb_internet_use.observation.model import Observation, OutputLine
from tb_internet_use.program.model import RequestKind
from tb_internet_use.request.model import CandidateRequest, FromCode, FromCommand
from tb_internet_use.toolcall.convert import convert_trial
from tb_internet_use.toolcall.model import ToolCallKey
from tb_internet_use.trial_interpretation import interpret_trial_before_linking

# Data runs use at most 4 processes, to leave the machine usable.
_PROCESS_COUNT = 4
_PACKAGE_REQUEST_KINDS = frozenset({RequestKind.PACKAGE, RequestKind.SYSTEM_PACKAGE})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_trials_dir", type=Path)
    parser.add_argument(
        "--sample", type=int, help="count a random sample of this many trials"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, help="write the counts as JSON")
    parser.add_argument(
        "--compare", type=Path, help="print every count that differs from this JSON"
    )
    arguments = parser.parse_args()

    trial_dirs = sorted(p for p in arguments.raw_trials_dir.iterdir() if p.is_dir())
    if arguments.sample:
        trial_dirs = random.Random(arguments.seed).sample(trial_dirs, arguments.sample)
    counts: Counter[str] = Counter()
    with ProcessPoolExecutor(_PROCESS_COUNT) as pool:
        for trial_counts in pool.map(count_trial, trial_dirs, chunksize=20):
            counts.update(trial_counts)

    for name, count in sorted(counts.items()):
        print(f"{count}\t{name}")
    if arguments.out:
        arguments.out.write_text(json.dumps(dict(sorted(counts.items())), indent=1))
    if arguments.compare:
        old_counts = json.loads(arguments.compare.read_text())
        print("\nchanged counts (old -> new)")
        for name in sorted(old_counts.keys() | counts.keys()):
            if old_counts.get(name, 0) != counts.get(name, 0):
                print(f"{old_counts.get(name, 0)} -> {counts.get(name, 0)}\t{name}")


def count_trial(trial_dir: Path) -> Counter[str]:
    """Run stages 8 to 10 on one trial and count what they find, with an exception counted instead of raised."""
    counts: Counter[str] = Counter({"trials": 1})
    try:
        result = interpret_trial_before_linking(convert_trial(trial_dir))
    except Exception as error:  # noqa: BLE001, one trial must not stop the run
        counts[f"exception {type(error).__name__}"] += 1
        return counts
    counts.update(_call_run_counts(result.call_runs))
    counts.update(
        _candidate_request_counts(result.candidate_requests, result.call_runs)
    )
    counts.update(_observation_counts(result.observations))
    return counts


def _call_run_counts(call_runs: tuple[CallRun, ...]) -> Counter[str]:
    """Count the stage 8 results of one trial and the invariants they break."""
    counts: Counter[str] = Counter()
    index_of_key = {run.call.raw.key: index for index, run in enumerate(call_runs)}
    command_ids_of_call = _command_ids_of_call(call_runs)
    for index, run in enumerate(call_runs):
        counts["calls"] += 1
        command_ids = [
            c.command.id for text in run.shell_texts for c in text.commands or ()
        ]
        if sorted(command_ids) != list(range(len(command_ids))):
            counts["invariant: command ids of a call are not 0 to n-1"] += 1
        ids = set(command_ids)
        for text in run.shell_texts:
            source = type(text.source).__name__
            counts[
                f"8 shell text {source} {'known' if text.commands is not None else 'unknown'}"
            ] += 1
            runner_id = getattr(text.source, "runner_command_id", None)
            if runner_id is not None and runner_id not in ids:
                counts["invariant: runner id names no command"] += 1
            written_by = (
                text.source.written_by if isinstance(text.source, FileText) else None
            )
            if written_by is not None and index_of_key[written_by] > index:
                counts["invariant: file written after it ran"] += 1
            started_by = (
                text.source.started_by
                if isinstance(text.source, PollInputText)
                else None
            )
            if started_by is not None and index_of_key.get(started_by, index) >= index:
                counts["invariant: typed input started by a later or unknown call"] += 1
            for ran_command in text.commands or ():
                for values in ran_command.variable_values:
                    in_turn = "in turn" if values.takes_each_value_in_turn else "one of"
                    counts[f"8 variable with values, {in_turn}"] += 1
                    if not values.values:
                        counts["invariant: variable values without a value"] += 1
                for route in (*ran_command.stdout_routes, *ran_command.stderr_routes):
                    counts[f"8 route end {type(route.end).__name__}"] += 1
                    if not set(route.pipe_reader_ids) <= ids:
                        counts["invariant: pipe reader names no command"] += 1
        for code in run.code_texts:
            known = "known" if code.code is not None else "unknown"
            counts[
                f"8 code text {type(code.source).__name__} {code.language} {known}"
            ] += 1
        for poll_key in run.polls:
            counts["8 poll links"] += 1
            if index_of_key[poll_key] <= index:
                counts["invariant: poll not later than what it polls"] += 1
        status = run.command_text_status
        if status is not None:
            reporter = (
                "own result" if status.reported_by == run.call.raw.key else "poll"
            )
            counts[
                f"8 command text status {status.execution_status} from {reporter}"
            ] += 1
            if status.reported_by not in (run.call.raw.key, *run.polls):
                counts[
                    "invariant: status reported by neither the call nor its poll"
                ] += 1
        counts["8 harness output file readers"] += len(run.harness_output_file_readers)
        readers = list(run.harness_output_file_readers)
        for reads in run.redirected_output_reads:
            counts["8 redirected outputs with readers"] += 1
            counts["8 redirected output readers"] += len(reads.readers)
            readers += reads.readers
            for reader in reads.readers:
                if index_of_key[reader.call] < index:
                    counts["invariant: reader earlier than the writing call"] += 1
        for reader in readers:
            if (
                reader.command_id is not None
                and reader.command_id not in command_ids_of_call[reader.call]
            ):
                counts["invariant: reader names no command of its call"] += 1
    return counts


def _candidate_request_counts(
    requests: tuple[CandidateRequest, ...], call_runs: tuple[CallRun, ...]
) -> Counter[str]:
    """Count the candidate requests of one trial by kind, program and host kind, and the invariants they break."""
    counts: Counter[str] = Counter()
    command_ids_of_call = _command_ids_of_call(call_runs)
    for request in requests:
        counts[f"9 request {request.kind} {request.program_name}"] += 1
        counts[f"9 request source {type(request.source).__name__}"] += 1
        host_kinds = " ".join(sorted({host.kind for host in request.hosts})) or "none"
        counts[f"9 request host kinds {host_kinds}"] += 1
        counts[
            f"9 request asked packages {'unknown' if request.asked_package_names is None else 'known'}"
        ] += 1
        if request.asked_package_names and request.kind not in _PACKAGE_REQUEST_KINDS:
            counts["invariant: package names on a request of no package kind"] += 1
        counts["9 targets without a value"] += sum(
            t.value is None for t in request.targets
        )
        counts["9 targets of a loop value"] += sum(
            t.loop_variable is not None for t in request.targets
        )
        for flag in (
            "fetches_only_to_run_or_build",
            "has_offline_option",
            "asks_for_no_content",
            "prints_status_code",
            "quiet_progress_lines",
            "quiet_error_lines",
        ):
            counts[f"9 request {flag}"] += getattr(request, flag)
        source = request.source
        command_id = (
            source.command_id
            if isinstance(source, FromCommand)
            else source.runner_command_id
            if isinstance(source, FromCode)
            else None
        )
        if (
            command_id is not None
            and command_id not in command_ids_of_call[request.call]
        ):
            counts["invariant: request source names no command"] += 1
    return counts


def _observation_counts(observations: tuple[Observation, ...]) -> Counter[str]:
    """Count the observations of one trial by kind and place, and the invariants they break."""
    counts: Counter[str] = Counter()
    for observation in observations:
        place = "line" if isinstance(observation.place, OutputLine) else "field"
        if (
            isinstance(observation.place, OutputLine)
            and observation.place.line_index_in_json_string is not None
        ):
            place = "line in a JSON string"
        counts[f"10 observation {observation.kind} in a {place}"] += 1
        if (
            not observation.printing_programs
            and not observation.is_printed_by_other_programs_too
            and place != "field"
        ):
            counts["10 observation of a web tool result"] += 1
    return counts


def _command_ids_of_call(call_runs: tuple[CallRun, ...]) -> dict[ToolCallKey, set[int]]:
    """Collect the command ids of each call of one trial, by call key."""
    return {
        run.call.raw.key: {
            c.command.id for text in run.shell_texts for c in text.commands or ()
        }
        for run in call_runs
    }


if __name__ == "__main__":
    main()
