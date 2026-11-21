"""Run the steps up to `extract_network_requests` on raw trials, count the requests per harness and check the equations that the requests must meet.

An equation sets a count of the requests beside a count that this script takes another way, e.g. from the words of the commands with its own URL pattern, from the counts of `NetworkRequestKnowledge` or from the actions of the calls, so that a request that the step dropped or made twice shows as a difference.
An equation whose right side is 0 counts values that break a rule that holds whatever the data, e.g. a request whose URL target has a host without `$` that is missing from `host_names`.
Each equation of `EQUATIONS` has its definition above its name.

It writes `trial_outcomes.csv`, `trials_not_extracted.csv`, `counts_by_harness.csv`, `equations.csv`, `equation_examples.csv`, `judgment_rule_uses.csv`, `knowledge_row_uses.csv`, `unknown_inputs.csv`, `uncertain_requests_by_means.csv`, `uncertain_requests_by_trial.csv`, `host_names_by_scope.csv` and `subagent_prompt_urls.csv` under the output folder, `out/network_request/` unless `--out-dir` names another, which `.gitignore` keeps out of the repo.
They hold counts, harness names, trial ids, tool call keys, exception type names, host names, and the program names, subcommands, options, option values and call names of the catalogs and of what ran, never other text from a trajectory.
The rows of each file are described above the call that writes it in `write_audit_files`.

The script ends with exit code 1 when a trial raised an exception or an equation differs.
Run it as `nice -n 10 uv run python -I scripts/audit_network_requests.py <raw_trials_dir> [--limit N | --trial-ids FILE] [--out-dir DIR]`.
"""

import argparse
import csv
import functools
import io
import json
import re
import sys
import tokenize
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from tb_internet_use.expanded_tool_call.model import (
    ArgumentText,
    ExpandedToolCall,
    FileText,
    ProgramInvocation,
    RanCodeText,
    RanCommand,
    RanShellText,
    StdinText,
    UnknownProgramInvocation,
    UnknownRanText,
)
from tb_internet_use.knowledge.catalog import KnowledgeUses, KnowledgeUsesTotal
from tb_internet_use.knowledge.network_request_knowledge import (
    ANY_SUBCOMMAND,
    CODE_CALLS_CSV,
    NETWORK_REQUEST_CATALOGS_DIR,
    PROGRAM_NETWORK_REQUESTS_CSV,
    NetworkRequestKnowledge,
)
from tb_internet_use.network_request import extract_network_requests, judgment_rules
from tb_internet_use.network_request.model import (
    ContentPipedToCommand,
    ContentSaved,
    FetchingProgramLabel,
    FromCode,
    FromCommand,
    FromWebTool,
    HostNameScope,
    NetworkRequest,
    NetworkRequestTargetKind,
    NoNetworkRequestReason,
    UnknownHostNameScope,
    UnknownProgramNetworkRequestLabel,
)
from tb_internet_use.network_request.parse_code import parse_code
from tb_internet_use.network_request.parse_host_name import parse_host_name
from tb_internet_use.network_request.parse_url import parse_url
from tb_internet_use.pipeline import (
    PipelineKnowledge,
    read_trajectory,
    read_trial_file_texts,
    run_steps_to_expanded_tool_calls,
)
from tb_internet_use.tool_call.model import (
    FileDestination,
    StartSubagentAction,
    ToolCallKey,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    indexed_action_steps_of,
)
from tb_internet_use.trial import collect_trials
from tb_internet_use.trial.model import UnreadableTrajectory

# `python -I` leaves the folder of this script off `sys.path`, so the script puts it there to import the module beside it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trial_folders_and_csv_files import (
    PROCESS_COUNT,
    add_trial_choice_arguments,
    chosen_trial_dirs_from,
    write_csv,
)

OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "network_request"
# Every equation in the order of the output.
# The comment above each name gives its left side beside its right side.
EQUATIONS = (
    # `ProgramInvocation`s and `UnknownProgramInvocation`s of the commands beside lookups of program rows of `program_network_requests.csv`, i.e. uses and unknown inputs without an option and not under `any subcommand`, plus `UnknownProgramInvocation`s.
    "program_invocations_equal_program_lookups",
    # Program runs with a request, i.e. distinct (call, command id, program invocation) of the `FromCommand` requests, beside runs that the `NetworkRequestKnowledge` of this script answers with `FetchingProgramLabel`, minus the counts `option_sends_no_request` and `no_target_arguments`, plus runs without a row that run nothing else and have a URL in their words, with the variables of one sure value filled, found with this script's own pattern, whose host `parse_host_name` does not read as local or reserved.
    "command_request_runs_equal_fetching_and_public_url_runs",
    # `RanCodeText`s without a `FromCode` request beside those whose URLs, found with this script's own pattern, are all local, reserved, of a namespace host with no dot in the last path part or on a line with a call of a `sends_no_network_request` row, and in which no call name of a `sends_network_request` row is followed by `(` outside strings and comments, before the point where `parse_code` stops reading and other than as the name of a JavaScript method definition.
    "code_texts_without_request_show_no_request",
    # Calls with a request beside those whose requests have the indexes 0, 1, 2 and so on in order.
    "indexes_run_from_zero_in_each_call",
    # Pairs of requests of one call with the same target where one comes from the command that runs the text of the other, e.g. `python -c` and its code, beside 0.
    "no_request_repeats_a_request_of_the_text_it_runs",
    # Fields of the requests that break, one for a saved path that is neither a written file of the call nor a file its command's stdout goes to, one for a pipe reader that is no command of the same call reading a stdout route of its command, and one for a URL target whose host holds no `$` and is missing from `host_names`, beside 0.
    # A tail that reads the output of `bash fetch.sh` reads a stdout route of the curl in fetch.sh, so that pipe reader breaks nothing.
    "request_fields_agree",
    # Requests of `pip install` runs with arguments and without unread words, file options, value options, options that send no request, run time arguments or `$` in a word, beside arguments that are no local path, plus 1 when one argument is a local path, by this script's own reading of a local path.
    "pip_install_requests_equal_targets",
    # `FromCode` requests over the bound of a code text beside 0.
    # The bound is the places of `http://` or `https://` in the code, since each call without a row gives one request per URL of its own, plus the places where a call name of a `sends_network_request` or `runs_program` row is followed by `(`.
    "code_requests_within_urls_and_calls",
    # `FromWebTool` requests beside queries and URLs of the web actions of the calls and their script steps, plus 1 for each such action without one.
    "web_tool_requests_equal_web_targets",
    # Names counted in the counter of `extract_network_requests` beside those of `network_request/judgment_rules.py`.
    "judgment_rule_names_are_of_this_step",
)
# The two sides of an equation, as `equations.csv` names them.
_SIDES = ("left", "right")
# The trial outcome of a trial that ran through the steps.
EXTRACTED = "extracted"
# The trial outcome of an id that names no folder under the raw trials folder.
NOT_FOUND = "not found"
# The examples kept per equation and per trial outcome, so that the CSVs stay short.
_EXAMPLE_LIMIT = 20
# The rule names that the counter of `extract_network_requests` may hold.
JUDGMENT_RULE_NAMES = frozenset(
    name
    for name in dir(judgment_rules)
    if name.startswith("treat_") and callable(getattr(judgment_rules, name))
)
# An http or https URL, written again here so that the recounts do not go through `parse_urls_in_text`. A `{...}` or `${...}` part stays in it, as in the f-string `f"http://{host}:{port}/x"` or `http://${HOST}/x`.
_URL = re.compile(r"""https?://(?:\$?\{[^{}\s]*\}|[^\s'"`<>()\[\]{}\\])+""")
# The start of a URL, whose places bound the code requests even when the rest is no URL that `_URL` reads, e.g. `http://[^` of a pattern in code, which the step reads as a URL whose host cannot be read.
_URL_START = re.compile(r"https?://")
# The hosts whose URLs name an XML or JSON namespace, written again here from `treat_url_of_namespace_host_as_no_target`.
_NAMESPACE_HOST_NAMES = frozenset(
    {"schemas.openxmlformats.org", "www.w3.org", "purl.org", "json-schema.org"}
)
# The archive file name endings that a pip requirement can name as a local file.
_ARCHIVE_ENDINGS = (".whl", ".zip", ".tar.gz", ".tgz")
_NOT_LOCAL_OR_RESERVED = "may be public"
# A comment or a quoted string of JavaScript, i.e. `//` to the line end, `/* */`, or text in single, double or back quotes, the leftmost first.
_JAVASCRIPT_STRING = re.compile(
    r"""//[^\n]*|/\*.*?\*/|'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`""",
    re.DOTALL,
)
# A method definition of JavaScript after the `(` of its name, i.e. its parameters, `)` and `{`, e.g. `url) {` of `fetch(url) { return p }` in a class or an object.
_JAVASCRIPT_METHOD_DEFINITION_END = re.compile(r"[^()]*\)\s*\{")
# The tokens of Python that hold a string or a comment, i.e. the text of an f-string but not its `{...}` parts.
_PYTHON_STRING_TOKEN_TYPES = frozenset(
    {tokenize.STRING, tokenize.FSTRING_MIDDLE, tokenize.COMMENT}
)
# A variable as `$NAME` or `${NAME}`, filled where it has one sure value.
_PLAIN_VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_trial_choice_arguments(parser)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    arguments = parser.parse_args()

    trial_dirs = list(dict.fromkeys(chosen_trial_dirs_from(arguments)))
    total = TrialAuditTotal()
    with ProcessPoolExecutor(PROCESS_COUNT) as pool:
        for trial_audit in pool.map(audit_trial, trial_dirs, chunksize=5):
            total.add_trial(trial_audit)
    write_audit_files(total, arguments.out_dir)
    print(f"trials: {dict(sorted(total.outcome_counts.items()))}")
    for equation, left, right in total.equation_rows():
        print(f"{equation}: {left} = {right} {'holds' if left == right else 'differs'}")
    print(f"written under {arguments.out_dir}")
    if total.has_exception_or_differing_equation():
        sys.exit(1)


def write_audit_files(total: TrialAuditTotal, out_dir: Path) -> None:
    """Write the CSVs from the sum of the trials, with the rows of each described above the call that writes it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # `trial_outcomes.csv` has one row for each outcome of a trial, e.g. `extracted`, `not found` or `exception` with its type name, with its trials and the first 20 trial ids.
    write_csv(
        out_dir / "trial_outcomes.csv",
        ("outcome", "trial_count", "first_trial_ids"),
        (
            (outcome, count, " ".join(total.trial_id_examples_by_outcome[outcome]))
            for outcome, count in sorted(total.outcome_counts.items())
        ),
    )
    # `trials_not_extracted.csv` has one row for each trial that was not extracted, with its outcome.
    write_csv(
        out_dir / "trials_not_extracted.csv",
        ("trial_id", "outcome"),
        total.trials_not_extracted,
    )
    # `counts_by_harness.csv` has one row for each harness, or `all`, with a count, e.g. requests by certainty, source kind, target kind, uncertainty reason and destination of the received content, runs, calls and URLs without a request by reason, and code texts not read to their end.
    write_csv(
        out_dir / "counts_by_harness.csv",
        ("harness", "count_name", "count"),
        (
            (harness, count_name, count)
            for (harness, count_name), count in sorted(total.counts.items())
        ),
    )
    # `equations.csv` has one row for each equation of `EQUATIONS`, with its two sides and whether they are equal.
    write_csv(
        out_dir / "equations.csv",
        ("equation", "left", "right", "holds"),
        (
            (equation, left, right, "yes" if left == right else "no")
            for equation, left, right in total.equation_rows()
        ),
    )
    # `equation_examples.csv` has one row for each call where an equation differs, or a trial with a blank `tool_call_key` for an equation counted per trial, the first 20 per equation, with the call name or `url` that a code text without a request shows when there is one.
    write_csv(
        out_dir / "equation_examples.csv",
        ("equation", "trial_id", "tool_call_key", "name"),
        total.equation_examples,
    )
    # `judgment_rule_uses.csv` has one row for each judgment rule, with its uses and trials.
    write_csv(
        out_dir / "judgment_rule_uses.csv",
        ("judgment_rule", "use_count", "trial_count"),
        (
            (name, count, total.judgment_rule_trial_counts[name])
            for name, count in total.judgment_rule_use_counts.most_common()
        ),
    )
    uses_total = total.knowledge_uses_total
    # `knowledge_row_uses.csv` has one row for each row of a catalog of `NetworkRequestKnowledge`, or a program name that code runs under `any subcommand`, with its uses and trials.
    write_csv(
        out_dir / "knowledge_row_uses.csv",
        ("catalog", "row_key", "use_count", "trial_count"),
        (
            (
                catalog,
                " ".join(row_key),
                count,
                uses_total.row_trial_counts[catalog, row_key],
            )
            for (catalog, row_key), count in uses_total.row_use_counts.most_common()
        ),
    )
    # `unknown_inputs.csv` has one row for each program, option or code call without a row, with its lookups, its trials and its tasks, most lookups first.
    write_csv(
        out_dir / "unknown_inputs.csv",
        ("catalog", "row_key", "lookup_count", "trial_count", "task_count"),
        (
            (
                catalog,
                " | ".join(row_key),
                count,
                uses_total.unknown_input_trial_counts[catalog, row_key],
                len(total.unknown_input_tasks[catalog, row_key]),
            )
            for (catalog, row_key), count in sorted(
                uses_total.unknown_input_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
    )
    # `uncertain_requests_by_means.csv` has one row for each uncertainty reason and a program or call name, with its requests, commands or code texts, trials and tasks, by reason and most requests first within a reason, marking a program whose command runs a text that the trial does not hold.
    write_csv(
        out_dir / "uncertain_requests_by_means.csv",
        (
            "uncertainty_reason",
            "means_name",
            "request_count",
            "command_or_code_text_count",
            "trial_count",
            "task_count",
            "runs_text_the_trial_does_not_hold",
        ),
        (
            (
                reason,
                means_name,
                count,
                len(total.uncertain_places[reason, means_name]),
                len(total.uncertain_trials[reason, means_name]),
                len(total.uncertain_tasks[reason, means_name]),
                "yes" if (reason, means_name) in total.uncertain_runners else "",
            )
            for (reason, means_name), count in sorted(
                total.uncertain_request_counts.items(),
                key=lambda item: (item[0][0], -item[1], item[0][1]),
            )
        ),
    )
    # `uncertain_requests_by_trial.csv` has one row for each trial and an uncertainty reason, with its requests.
    write_csv(
        out_dir / "uncertain_requests_by_trial.csv",
        ("trial_id", "uncertainty_reason", "request_count"),
        sorted(total.uncertain_requests_by_trial),
    )
    # `host_names_by_scope.csv` has one row for each host scope with a blank host name, the number of host names of that scope that the requests name, once per request and name, and its trials, `no host name` with the requests that name none and their trials, or a name that `treat_dotted_host_name_as_public` reads as public with its requests and its trials.
    write_csv(
        out_dir / "host_names_by_scope.csv",
        ("host_scope", "host_name", "request_count", "trial_count"),
        [
            (scope, "", count, len(total.host_scope_trials[scope]))
            for scope, count in sorted(total.host_scope_request_counts.items())
        ]
        + [
            (
                "public by treat_dotted_host_name_as_public",
                host_name,
                count,
                len(trials),
            )
            for host_name, (count, trials) in sorted(
                total.dotted_public_host_names.items(),
                key=lambda item: (-len(item[1][1]), item[0]),
            )
        ],
    )
    # `subagent_prompt_urls.csv` has one row, with the `StartSubagentAction` calls whose arguments hold a URL that may be public, e.g. `http://db:5432/doc`, and their trials.
    write_csv(
        out_dir / "subagent_prompt_urls.csv",
        ("call_count", "trial_count"),
        [
            (
                total.counts["all", "subagent calls with a public URL"],
                len(total.subagent_url_trials),
            )
        ],
    )


def audit_trial(trial_dir: Path) -> TrialAudit:
    """Run the steps up to `extract_network_requests` on one trial, then count and check its requests, with an exception named instead of raised."""
    if not trial_dir.is_dir():
        return TrialAudit(trial_dir.name, NOT_FOUND)
    try:
        harness_tool_calls = read_trajectory(trial_dir)
        if isinstance(harness_tool_calls, UnreadableTrajectory):
            return TrialAudit(trial_dir.name, f"unreadable {harness_tool_calls.reason}")
        (trial,) = collect_trials([read_trial_file_texts(trial_dir)], {})
        worker_process_knowledge = knowledge_of_worker_process()
        pipeline_knowledge = worker_process_knowledge.pipeline_knowledge
        # The knowledge classes serve every trial of the worker process, so their uses start empty for each trial.
        pipeline_knowledge.tool_call_knowledge.uses = KnowledgeUses()
        pipeline_knowledge.expanded_tool_call_knowledge.uses = KnowledgeUses()
        pipeline_knowledge.network_request_knowledge.uses = KnowledgeUses()
        # The steps up to `extract_network_requests` run as `run_steps_to_network_request_results` runs them, keeping the expanded calls that the recounts read.
        expanded_tool_calls = run_steps_to_expanded_tool_calls(
            harness_tool_calls,
            pipeline_knowledge=pipeline_knowledge,
            tool_call_judgment_rule_use_counts=Counter(),
            expanded_tool_call_judgment_rule_use_counts=Counter(),
        )
        judgment_rule_use_counts: Counter[str] = Counter()
        no_network_request_counts: Counter[NoNetworkRequestReason] = Counter()
        network_requests = extract_network_requests(
            expanded_tool_calls,
            knowledge=pipeline_knowledge.network_request_knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
            no_network_request_counts=no_network_request_counts,
        )
        trial_audit = TrialAudit(
            trial_dir.name,
            EXTRACTED,
            harness=trial.harness,
            task=f"{trial.benchmark_version} {trial.task_name}",
            judgment_rule_use_counts=judgment_rule_use_counts,
            knowledge_uses=pipeline_knowledge.network_request_knowledge.uses,
        )
        TrialChecker(
            trial_audit,
            expanded_tool_calls,
            network_requests,
            no_network_request_counts,
            worker_process_knowledge.own_network_request_knowledge,
            worker_process_knowledge.code_call_names,
        ).check()
    except Exception as error:  # noqa: BLE001, one trial must not stop the run
        return TrialAudit(trial_dir.name, f"exception {type(error).__name__}")
    return trial_audit


@dataclass(frozen=True, slots=True)
class CodeCallNames:
    """Call names of the code call catalog by effect and language, read by this script from the CSV itself so that its recounts do not go through `NetworkRequestKnowledge`."""

    # By (code language, effect), e.g. ("python", "sends_network_request").
    names_by_language_and_effect: dict[tuple[str, str], tuple[str, ...]]

    def names_of(self, code_language: str, *effects: str) -> tuple[str, ...]:
        """Give the call names of a language with one of the effects."""
        return tuple(
            name
            for effect in effects
            for name in self.names_by_language_and_effect.get(
                (code_language, effect), ()
            )
        )


def code_call_names_from_csv(csv_path: Path) -> CodeCallNames:
    """Read the call names of a code call catalog file by language and effect."""
    names_by_language_and_effect: dict[tuple[str, str], tuple[str, ...]] = {}
    with csv_path.open(newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            key = (row["code_language"], row["effect"])
            names_by_language_and_effect[key] = (
                *names_by_language_and_effect.get(key, ()),
                row["call_name"],
            )
    return CodeCallNames(names_by_language_and_effect)


@dataclass(frozen=True, slots=True)
class WorkerProcessKnowledge:
    """Knowledge classes and the call names of the code call catalog, made once in each worker process and used for each of its trials."""

    # The knowledge classes that the steps ask.
    pipeline_knowledge: PipelineKnowledge = field(default_factory=PipelineKnowledge)
    # The `NetworkRequestKnowledge` that `TrialChecker` asks whether a program fetches, so that its lookups do not count as lookups of the step.
    own_network_request_knowledge: NetworkRequestKnowledge = field(
        default_factory=NetworkRequestKnowledge
    )
    code_call_names: CodeCallNames = field(
        default_factory=lambda: code_call_names_from_csv(
            NETWORK_REQUEST_CATALOGS_DIR / CODE_CALLS_CSV
        )
    )


@functools.cache
def knowledge_of_worker_process() -> WorkerProcessKnowledge:
    """Give the knowledge classes of this worker process, made at its first trial."""
    return WorkerProcessKnowledge()


@dataclass(slots=True)
class TrialAudit:
    """Result of auditing one trial, sent from a worker process to the main process that sums the trials."""

    trial_id: str
    # `extracted`, `not found`, `unreadable` with the reason, or `exception` with the type name.
    outcome: str
    harness: str = ""
    # The benchmark version and the task name, which together name a task.
    task: str = ""
    # By (harness or `all`, count name).
    counts: Counter[tuple[str, str]] = field(default_factory=Counter)
    # By (equation, `left` or `right`), every side at 0 before the trial adds to it, so that an equation the trials never reach still shows.
    equation_sides: Counter[tuple[str, str]] = field(
        default_factory=lambda: Counter(
            dict.fromkeys(
                ((equation, side) for equation in EQUATIONS for side in _SIDES), 0
            )
        )
    )
    # (equation, tool call key or a blank for an equation counted per trial, name) of each call or trial where an equation differs.
    equation_examples: list[tuple[str, str, str]] = field(default_factory=list)
    judgment_rule_use_counts: Counter[str] = field(default_factory=Counter)
    knowledge_uses: KnowledgeUses = field(default_factory=KnowledgeUses)
    # By (uncertainty reason, program or call name), the requests.
    uncertain_request_counts: Counter[tuple[str, str]] = field(default_factory=Counter)
    # By (uncertainty reason, program or call name), each command or code text as the text of its call key and its place.
    uncertain_places: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    # The (uncertainty reason, program name) whose command runs a text that the trial does not hold.
    uncertain_runners: set[tuple[str, str]] = field(default_factory=set)
    host_scope_request_counts: Counter[str] = field(default_factory=Counter)
    dotted_public_host_names: Counter[str] = field(default_factory=Counter)
    has_subagent_url: bool = False

    def count(self, count_name: str, amount: int = 1) -> None:
        """Add to a count of the trial's harness and of all harnesses."""
        self.counts[self.harness, count_name] += amount
        self.counts["all", count_name] += amount

    def add_sides(
        self,
        equation: str,
        left: int,
        right: int,
        tool_call_key: ToolCallKey | None,
        name: str = "",
    ) -> None:
        """Add the two sides of an equation for one call or one trial, keeping the call as an example when they differ."""
        if equation not in EQUATIONS:
            raise ValueError(f"no equation {equation}")
        self.equation_sides[equation, "left"] += left
        self.equation_sides[equation, "right"] += right
        if left != right:
            self.equation_examples.append(
                (
                    equation,
                    ""
                    if tool_call_key is None
                    else _text_of_tool_call_key(tool_call_key),
                    name,
                )
            )


@dataclass(slots=True)
class TrialAuditTotal:
    """Sum of the `TrialAudit` of many trials, built by `main` to write the CSVs."""

    outcome_counts: Counter[str] = field(default_factory=Counter)
    trial_id_examples_by_outcome: dict[str, list[str]] = field(default_factory=dict)
    # (trial id, outcome) of each trial whose outcome is not `extracted`.
    trials_not_extracted: list[tuple[str, str]] = field(default_factory=list)
    counts: Counter[tuple[str, str]] = field(default_factory=Counter)
    equation_sides: Counter[tuple[str, str]] = field(default_factory=Counter)
    equation_examples: list[tuple[str, str, str, str]] = field(default_factory=list)
    judgment_rule_use_counts: Counter[str] = field(default_factory=Counter)
    judgment_rule_trial_counts: Counter[str] = field(default_factory=Counter)
    knowledge_uses_total: KnowledgeUsesTotal = field(default_factory=KnowledgeUsesTotal)
    unknown_input_tasks: dict[tuple[str, tuple[str, ...]], set[str]] = field(
        default_factory=dict
    )
    uncertain_request_counts: Counter[tuple[str, str]] = field(default_factory=Counter)
    uncertain_places: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    uncertain_trials: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    uncertain_tasks: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    uncertain_runners: set[tuple[str, str]] = field(default_factory=set)
    # (trial id, uncertainty reason, requests).
    uncertain_requests_by_trial: list[tuple[str, str, int]] = field(
        default_factory=list
    )
    host_scope_request_counts: Counter[str] = field(default_factory=Counter)
    host_scope_trials: dict[str, set[str]] = field(default_factory=dict)
    # By host name, its requests and its trials.
    dotted_public_host_names: dict[str, tuple[int, set[str]]] = field(
        default_factory=dict
    )
    subagent_url_trials: set[str] = field(default_factory=set)

    def add_trial(self, trial_audit: TrialAudit) -> None:
        """Add what one trial counted, keeping the first examples of each outcome and equation."""
        trial_id = trial_audit.trial_id
        self.outcome_counts[trial_audit.outcome] += 1
        trial_ids = self.trial_id_examples_by_outcome.setdefault(
            trial_audit.outcome, []
        )
        if len(trial_ids) < _EXAMPLE_LIMIT:
            trial_ids.append(trial_id)
        if trial_audit.outcome != EXTRACTED:
            self.trials_not_extracted.append((trial_id, trial_audit.outcome))
        self.counts.update(trial_audit.counts)
        self.equation_sides.update(trial_audit.equation_sides)
        for equation, tool_call_key, name in trial_audit.equation_examples:
            kept = sum(
                1 for example in self.equation_examples if example[0] == equation
            )
            if kept < _EXAMPLE_LIMIT:
                self.equation_examples.append((equation, trial_id, tool_call_key, name))
        self.judgment_rule_use_counts.update(trial_audit.judgment_rule_use_counts)
        self.judgment_rule_trial_counts.update(
            trial_audit.judgment_rule_use_counts.keys()
        )
        self.knowledge_uses_total.add_trial(trial_audit.knowledge_uses)
        for lookup_key in trial_audit.knowledge_uses.unknown_input_counts:
            self.unknown_input_tasks.setdefault(lookup_key, set()).add(trial_audit.task)
        self.uncertain_request_counts.update(trial_audit.uncertain_request_counts)
        reasons_of_trial: Counter[str] = Counter()
        for means_key, count in trial_audit.uncertain_request_counts.items():
            self.uncertain_places.setdefault(means_key, set()).update(
                f"{trial_id}:{place}"
                for place in trial_audit.uncertain_places.get(means_key, ())
            )
            self.uncertain_trials.setdefault(means_key, set()).add(trial_id)
            self.uncertain_tasks.setdefault(means_key, set()).add(trial_audit.task)
            reasons_of_trial[means_key[0]] += count
        self.uncertain_runners |= trial_audit.uncertain_runners
        self.uncertain_requests_by_trial += [
            (trial_id, reason, count) for reason, count in reasons_of_trial.items()
        ]
        self.host_scope_request_counts.update(trial_audit.host_scope_request_counts)
        for scope in trial_audit.host_scope_request_counts:
            self.host_scope_trials.setdefault(scope, set()).add(trial_id)
        for host_name, count in trial_audit.dotted_public_host_names.items():
            known_count, trials = self.dotted_public_host_names.get(
                host_name, (0, set())
            )
            self.dotted_public_host_names[host_name] = (
                known_count + count,
                trials | {trial_id},
            )
        if trial_audit.has_subagent_url:
            self.subagent_url_trials.add(trial_id)

    def equation_rows(self) -> list[tuple[str, int, int]]:
        """List each equation with its two sides, in the order of `EQUATIONS`."""
        return [
            (
                equation,
                self.equation_sides[equation, "left"],
                self.equation_sides[equation, "right"],
            )
            for equation in EQUATIONS
        ]

    def has_exception_or_differing_equation(self) -> bool:
        """Tell whether a trial raised an exception or the two sides of an equation differ, which makes `main` end with exit code 1."""
        return any(
            outcome.startswith("exception") for outcome in self.outcome_counts
        ) or any(left != right for _, left, right in self.equation_rows())


class TrialChecker:
    """Checker of the requests of one trial, which adds its counts and the sides of each equation to a `TrialAudit`.

    It reads the expanded calls, its own `NetworkRequestKnowledge` and the code call catalog file, so its recounts do not go through `extract_network_requests`, though they read URLs, host names and code with the same `parse_url`, `parse_host_name` and `parse_code`.
    """

    def __init__(
        self,
        trial_audit: TrialAudit,
        expanded_tool_calls: Sequence[ExpandedToolCall],
        network_requests: Sequence[NetworkRequest],
        no_network_request_counts: Counter[NoNetworkRequestReason],
        own_knowledge: NetworkRequestKnowledge,
        code_call_names: CodeCallNames,
    ) -> None:
        self.trial_audit = trial_audit
        self.expanded_tool_calls = expanded_tool_calls
        self.network_requests = network_requests
        self.no_network_request_counts = no_network_request_counts
        self.own_knowledge = own_knowledge
        self.code_call_names = code_call_names
        self.network_requests_by_key: dict[ToolCallKey, list[NetworkRequest]] = {}
        for network_request in network_requests:
            self.network_requests_by_key.setdefault(
                network_request.tool_call_key, []
            ).append(network_request)

    def check(self) -> None:
        """Count the trial and check every equation of `EQUATIONS`."""
        self.count_requests()
        self.check_program_lookups()
        self.check_command_request_runs()
        self.check_trial_without_call()
        for expanded_tool_call in self.expanded_tool_calls:
            network_requests = self.network_requests_by_key.get(
                expanded_tool_call.tool_call.harness_tool_call.key, []
            )
            self.check_code_texts(expanded_tool_call, network_requests)
            self.check_indexes(expanded_tool_call, network_requests)
            self.check_repeats(expanded_tool_call, network_requests)
            self.check_fields(expanded_tool_call, network_requests)
            self.check_pip_install(expanded_tool_call, network_requests)
            self.check_web_tool(expanded_tool_call, network_requests)
            self.count_subagent_urls(expanded_tool_call)
        self.trial_audit.add_sides(
            "judgment_rule_names_are_of_this_step",
            len(self.trial_audit.judgment_rule_use_counts),
            len(self.trial_audit.judgment_rule_use_counts.keys() & JUDGMENT_RULE_NAMES),
            None,
        )

    def check_trial_without_call(self) -> None:
        """Count the trial under `trials`, and under `trials with a request` when its calls gave a request."""
        self.trial_audit.count("trials")
        if self.network_requests:
            self.trial_audit.count("trials with a request")

    def count_requests(self) -> None:
        """Count the requests by certainty, source, target kind, reason, destination and host scope, the runs, calls and URLs without a request by reason, and the code texts and those not read to their end."""
        trial_audit = self.trial_audit
        for network_request in self.network_requests:
            trial_audit.count("requests")
            trial_audit.count(f"requests {network_request.certainty}")
            trial_audit.count(f"requests from {type(network_request.source).__name__}")
            trial_audit.count(
                f"requests of target kind {_name_of_value(network_request.target_kind)}"
            )
            trial_audit.count(
                f"requests of uncertainty reason {network_request.uncertainty_reason or 'none'}"
            )
            trial_audit.count(
                f"requests whose content goes to {_name_of_destination(network_request)}"
            )
            if not network_request.host_names:
                trial_audit.host_scope_request_counts["no host name"] += 1
            for host_name in network_request.host_names:
                scope = _host_scope_name_of(host_name)
                trial_audit.host_scope_request_counts[scope] += 1
                if scope == "unknown_dotted_name":
                    trial_audit.dotted_public_host_names[host_name] += 1
            if network_request.uncertainty_reason is not None:
                means_key = (
                    network_request.uncertainty_reason.value,
                    _means_name_of(network_request),
                )
                trial_audit.uncertain_request_counts[means_key] += 1
                trial_audit.uncertain_places.setdefault(means_key, set()).add(
                    _place_text_of(network_request)
                )
                if self._runs_unknown_text(network_request):
                    trial_audit.uncertain_runners.add(means_key)
        for reason, count in self.no_network_request_counts.items():
            trial_audit.count(f"runs, calls or URLs without a request, {reason}", count)
        for expanded_tool_call in self.expanded_tool_calls:
            for ran_text in expanded_tool_call.ran_texts:
                if not isinstance(ran_text, RanCodeText):
                    continue
                trial_audit.count("code texts")
                unreadable_text_start = parse_code(
                    ran_text.code, ran_text.code_language
                ).unreadable_text_start
                if unreadable_text_start is None:
                    continue
                trial_audit.count("code texts not read to their end")
                if not _URL.search(ran_text.code[unreadable_text_start:]):
                    trial_audit.count(
                        "code texts not read to their end without a URL after that point"
                    )

    def _runs_unknown_text(self, network_request: NetworkRequest) -> bool:
        """Tell whether the command of a request runs a text that the trial does not hold, e.g. bash of `bash setup.sh https://a.org/x`."""
        source = network_request.source
        if not isinstance(source, FromCommand):
            return False
        expanded_tool_call = self._expanded_tool_call_of(network_request.tool_call_key)
        return any(
            isinstance(ran_text, UnknownRanText)
            and getattr(ran_text.source, "runner_command_id", None) == source.command_id
            for ran_text in expanded_tool_call.ran_texts
        )

    def _expanded_tool_call_of(self, tool_call_key: ToolCallKey) -> ExpandedToolCall:
        return next(
            expanded_tool_call
            for expanded_tool_call in self.expanded_tool_calls
            if expanded_tool_call.tool_call.harness_tool_call.key == tool_call_key
        )

    def check_program_lookups(self) -> None:
        """Check that `NetworkRequestKnowledge` was asked once for each program invocation of the commands."""
        program_invocation_count = 0
        unknown_program_invocation_count = 0
        for expanded_tool_call in self.expanded_tool_calls:
            for ran_command in _ran_commands_of(expanded_tool_call):
                for program_invocation in ran_command.program_invocations:
                    program_invocation_count += 1
                    if isinstance(program_invocation, UnknownProgramInvocation):
                        unknown_program_invocation_count += 1
        uses = self.trial_audit.knowledge_uses
        program_lookup_count = sum(
            count
            for counts in (uses.row_use_counts, uses.unknown_input_counts)
            for (catalog, row_key), count in counts.items()
            if catalog == PROGRAM_NETWORK_REQUESTS_CSV
            and not row_key[2]
            and row_key[1] != ANY_SUBCOMMAND
        )
        self.trial_audit.add_sides(
            "program_invocations_equal_program_lookups",
            program_invocation_count,
            program_lookup_count + unknown_program_invocation_count,
            None,
        )

    def check_command_request_runs(self) -> None:
        """Check that the runs with a request are the fetching runs that were not stopped, plus the runs without a row that show a URL that may be public."""
        expected_run_count = -(
            self.no_network_request_counts[
                NoNetworkRequestReason.OPTION_SENDS_NO_REQUEST
            ]
            + self.no_network_request_counts[NoNetworkRequestReason.NO_TARGET_ARGUMENTS]
        )
        for expanded_tool_call in self.expanded_tool_calls:
            for ran_command in _ran_commands_of(expanded_tool_call):
                expected_run_count += self._expected_runs_with_request_of(
                    ran_command, expanded_tool_call
                )
        request_runs = {
            (
                network_request.tool_call_key,
                network_request.source.command_id,
                network_request.source.program_invocation,
            )
            for network_request in self.network_requests
            if isinstance(network_request.source, FromCommand)
        }
        self.trial_audit.add_sides(
            "command_request_runs_equal_fetching_and_public_url_runs",
            len(request_runs),
            expected_run_count,
            None,
        )

    def _expected_runs_with_request_of(
        self, ran_command: RanCommand, expanded_tool_call: ExpandedToolCall
    ) -> int:
        """Count the runs of a command that this script expects a request of, before the counts of runs that an option or the lack of target arguments stops."""
        command_id = ran_command.shell_command.id
        runs_held_text = _runs_held_text(command_id, expanded_tool_call)
        expected_run_count = 0
        last_position = len(ran_command.program_invocations) - 1
        for position, program_invocation in enumerate(ran_command.program_invocations):
            if isinstance(program_invocation, UnknownProgramInvocation):
                words: Sequence[str] = program_invocation.words
                runs_something_else = runs_held_text
            else:
                program_network_request_label = (
                    self.own_knowledge.program_network_request_label(program_invocation)
                )
                if isinstance(program_network_request_label, FetchingProgramLabel):
                    expected_run_count += 1
                    continue
                if not isinstance(
                    program_network_request_label, UnknownProgramNetworkRequestLabel
                ):
                    continue
                words = _words_of(program_invocation)
                runs_something_else = position < last_position or runs_held_text
            if not runs_something_else and any(
                _scope_of_url(url) == _NOT_LOCAL_OR_RESERVED
                for word in words
                for url in _URL.findall(_filled_word_of(word, ran_command))
            ):
                expected_run_count += 1
        return expected_run_count

    def check_code_texts(
        self,
        expanded_tool_call: ExpandedToolCall,
        network_requests: Sequence[NetworkRequest],
    ) -> None:
        """Check that a code text without a request shows no URL that may be public and no call that sends one, and that no code text has more requests than its URLs and calls."""
        for ran_text in expanded_tool_call.ran_texts:
            if not isinstance(ran_text, RanCodeText):
                continue
            code_requests = [
                network_request
                for network_request in network_requests
                if isinstance(network_request.source, FromCode)
                and network_request.source.code_text_source == ran_text.source
            ]
            code_language = ran_text.code_language.value
            sending_names = self.code_call_names.names_of(
                code_language, "sends_network_request"
            )
            tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
            if not code_requests:
                missed_name = self._name_of_missed_request(ran_text, sending_names)
                self.trial_audit.add_sides(
                    "code_texts_without_request_show_no_request",
                    1,
                    0 if missed_name else 1,
                    tool_call_key,
                    missed_name or "",
                )
            bound = len(_URL_START.findall(ran_text.code)) + sum(
                len(_call_places(name, ran_text.code))
                for name in self.code_call_names.names_of(
                    code_language, "sends_network_request", "runs_program"
                )
            )
            self.trial_audit.add_sides(
                "code_requests_within_urls_and_calls",
                max(0, len(code_requests) - bound),
                0,
                tool_call_key,
            )

    def _name_of_missed_request(
        self, ran_code_text: RanCodeText, sending_names: Sequence[str]
    ) -> str | None:
        """Name the call of a code text that sends a request, or `url` for a URL that may be public, or None when the text shows neither.

        A call name counts outside strings and comments, before the point where `parse_code` stops reading, since the step reads no call after it, and not as the name of a JavaScript method definition, e.g. `fetch(url) {`.
        """
        code = ran_code_text.code
        code_language = ran_code_text.code_language.value
        unreadable_text_start = parse_code(
            code, ran_code_text.code_language
        ).unreadable_text_start
        code_outside_strings = _code_outside_strings(
            code[:unreadable_text_start], code_language
        )
        for name in sending_names:
            if any(
                code_language == "python"
                or not _JAVASCRIPT_METHOD_DEFINITION_END.match(
                    code_outside_strings, call_place.end()
                )
                for call_place in _call_places(name, code_outside_strings)
            ):
                return name
        non_fetching_names = self.code_call_names.names_of(
            ran_code_text.code_language.value, "sends_no_network_request"
        )
        for line in code.splitlines():
            if any(_call_places(name, line) for name in non_fetching_names):
                continue
            if any(
                _scope_of_url(url) == _NOT_LOCAL_OR_RESERVED
                and not _is_namespace_url(url)
                for url in _URL.findall(line)
            ):
                return "url"
        return None

    def check_indexes(
        self,
        expanded_tool_call: ExpandedToolCall,
        network_requests: Sequence[NetworkRequest],
    ) -> None:
        """Check that the requests of a call have the indexes 0, 1, 2 and so on."""
        if not network_requests:
            return
        indexes = [
            network_request.index_in_tool_call for network_request in network_requests
        ]
        self.trial_audit.add_sides(
            "indexes_run_from_zero_in_each_call",
            1,
            1 if indexes == list(range(len(indexes))) else 0,
            expanded_tool_call.tool_call.harness_tool_call.key,
        )

    def check_repeats(
        self,
        expanded_tool_call: ExpandedToolCall,
        network_requests: Sequence[NetworkRequest],
    ) -> None:
        """Count the pairs of requests with one target where one comes from the command that runs the text of the other."""
        repeat_count = 0
        for network_request in network_requests:
            runner_command_id = _runner_command_id_of(network_request)
            if runner_command_id is None or not isinstance(network_request.target, str):
                continue
            repeat_count += sum(
                1
                for other in network_requests
                if isinstance(other.source, FromCommand)
                and other.source.command_id == runner_command_id
                and other.target == network_request.target
            )
        self.trial_audit.add_sides(
            "no_request_repeats_a_request_of_the_text_it_runs",
            repeat_count,
            0,
            expanded_tool_call.tool_call.harness_tool_call.key,
        )

    def check_fields(
        self,
        expanded_tool_call: ExpandedToolCall,
        network_requests: Sequence[NetworkRequest],
    ) -> None:
        """Count the fields of the requests of a call that do not agree with it, i.e. each saved path, pipe reader and URL host, so that a request with two such fields counts twice."""
        ran_commands_by_id = {
            ran_command.shell_command.id: (ran_text, ran_command)
            for ran_text in expanded_tool_call.ran_texts
            if isinstance(ran_text, RanShellText)
            for ran_command in ran_text.ran_commands
        }
        written_paths = {
            written_file.path for written_file in expanded_tool_call.written_files
        }
        broken_count = 0
        for network_request in network_requests:
            source = network_request.source
            ran_text_and_command = (
                ran_commands_by_id.get(source.command_id)
                if isinstance(source, FromCommand)
                else None
            )
            destination = network_request.received_content_destination
            if isinstance(destination, ContentSaved) and destination.path is not None:
                stdout_paths = (
                    {
                        output_route.end.path
                        for output_route in ran_text_and_command[1].stdout_routes
                        if isinstance(output_route.end, FileDestination)
                    }
                    if ran_text_and_command
                    else set()
                )
                broken_count += destination.path not in written_paths | stdout_paths
            if isinstance(destination, ContentPipedToCommand):
                broken_count += (
                    ran_text_and_command is None
                    or destination.reader_command_id not in ran_commands_by_id
                    or not any(
                        destination.reader_command_id
                        in output_route.pipe_reader_command_ids
                        for output_route in ran_text_and_command[1].stdout_routes
                    )
                )
            if (
                isinstance(network_request.target, str)
                and network_request.target_kind
                in (
                    NetworkRequestTargetKind.URL,
                    NetworkRequestTargetKind.REPOSITORY_URL,
                )
                and (host_name := parse_url(network_request.target)) is not None
                and "$" not in host_name
            ):
                broken_count += host_name not in network_request.host_names
        self.trial_audit.add_sides(
            "request_fields_agree",
            broken_count,
            0,
            expanded_tool_call.tool_call.harness_tool_call.key,
        )

    def check_pip_install(
        self,
        expanded_tool_call: ExpandedToolCall,
        network_requests: Sequence[NetworkRequest],
    ) -> None:
        """Check that each plain `pip install` run gives one request per argument that is no local path, and one for all local paths."""
        for ran_command in _ran_commands_of(expanded_tool_call):
            program_invocation = ran_command.program_invocations[-1]
            if not _is_plain_pip_install(program_invocation, ran_command):
                continue
            assert isinstance(program_invocation, ProgramInvocation)
            local_path_count = sum(
                _is_local_path(argument) for argument in program_invocation.arguments
            )
            self.trial_audit.add_sides(
                "pip_install_requests_equal_targets",
                sum(
                    1
                    for network_request in network_requests
                    if isinstance(network_request.source, FromCommand)
                    and network_request.source.command_id
                    == ran_command.shell_command.id
                    and network_request.source.program_invocation == program_invocation
                ),
                len(program_invocation.arguments)
                - local_path_count
                + (1 if local_path_count else 0),
                expanded_tool_call.tool_call.harness_tool_call.key,
            )

    def check_web_tool(
        self,
        expanded_tool_call: ExpandedToolCall,
        network_requests: Sequence[NetworkRequest],
    ) -> None:
        """Check that a call gives one web tool request per query or URL of its web actions, and one for such an action without one."""
        expected_count = 0
        for _, action in indexed_action_steps_of(expanded_tool_call.tool_call.action):
            match action:
                case (
                    WebSearchAction(queries=targets)
                    | WebFetchAction(urls=targets)
                    | WebFindAction(urls=targets)
                ):
                    expected_count += len(targets) or 1
                case _:
                    pass
        self.trial_audit.add_sides(
            "web_tool_requests_equal_web_targets",
            sum(
                isinstance(network_request.source, FromWebTool)
                for network_request in network_requests
            ),
            expected_count,
            expanded_tool_call.tool_call.harness_tool_call.key,
        )

    def count_subagent_urls(self, expanded_tool_call: ExpandedToolCall) -> None:
        """Count a call that starts a subagent with a URL that may be public in its arguments."""
        tool_call = expanded_tool_call.tool_call
        if not isinstance(tool_call.action, StartSubagentAction):
            return
        argument_text = json.dumps(tool_call.harness_tool_call.args)
        if any(
            _scope_of_url(url) == _NOT_LOCAL_OR_RESERVED
            for url in _URL.findall(argument_text)
        ):
            self.trial_audit.count("subagent calls with a public URL")
            self.trial_audit.has_subagent_url = True


def _ran_commands_of(expanded_tool_call: ExpandedToolCall) -> list[RanCommand]:
    """Give every command of the shell texts that a call ran."""
    return [
        ran_command
        for ran_text in expanded_tool_call.ran_texts
        if isinstance(ran_text, RanShellText)
        for ran_command in ran_text.ran_commands
    ]


def _runs_held_text(command_id: int, expanded_tool_call: ExpandedToolCall) -> bool:
    """Tell whether a command runs a shell or code text that the trial holds."""
    return any(
        isinstance(ran_text, RanShellText | RanCodeText)
        and isinstance(ran_text.source, FileText | StdinText | ArgumentText)
        and ran_text.source.runner_command_id == command_id
        for ran_text in expanded_tool_call.ran_texts
    )


def _filled_word_of(word: str, ran_command: RanCommand) -> str:
    """Fill each `$NAME` or `${NAME}` of a word whose variable has exactly one value and no value set at run time, e.g. `http://localhost:8000/` for `http://$H:8000/` after `H=localhost`, written again here so that the recount does not go through the code it checks."""
    sure_value_of_name = {
        variable_values.name: variable_values.values[0]
        for variable_values in ran_command.variable_values
        if len(variable_values.values) == 1
        and not variable_values.has_value_set_at_run_time
    }
    return _PLAIN_VARIABLE.sub(
        lambda match: sure_value_of_name.get(
            match.group(1) or match.group(2), match.group(0)
        ),
        word,
    )


def _words_of(program_invocation: ProgramInvocation) -> tuple[str, ...]:
    """Give the option values, arguments and unread words of a program run."""
    return (
        *(
            program_option.value
            for program_option in program_invocation.options
            if program_option.value is not None
        ),
        *program_invocation.arguments,
        *program_invocation.unread_words,
    )


def _scope_of_url(url: str) -> str:
    """Give the scope of the host of a URL as `parse_host_name` reads it, or `may be public` for a host that is neither local nor reserved or that cannot be read."""
    host_name = parse_url(url)
    if host_name is None:
        return _NOT_LOCAL_OR_RESERVED
    host_name_scope = parse_host_name(host_name)
    if isinstance(host_name_scope, HostNameScope) and host_name_scope in (
        HostNameScope.LOCAL,
        HostNameScope.RESERVED,
    ):
        return host_name_scope.value
    return _NOT_LOCAL_OR_RESERVED


def _host_scope_name_of(host_name: str) -> str:
    """Name the scope of a host name, e.g. `public` or `unknown_single_label`."""
    host_name_scope = parse_host_name(host_name)
    if isinstance(host_name_scope, UnknownHostNameScope):
        return f"unknown_{host_name_scope.reason.value}"
    return host_name_scope.value


def _is_namespace_url(url: str) -> bool:
    """Tell whether a URL names a namespace, i.e. its host is a namespace host and its last path part has no dot."""
    host_name = parse_url(url)
    last_path_part = url.rstrip("/").rsplit("/", 1)[-1]
    return host_name in _NAMESPACE_HOST_NAMES and "." not in last_path_part


def _code_outside_strings(code: str, code_language: str) -> str:
    """Blank the string literals and comments of a code text, keeping the place of every other character, so that a call name written in a string is not read as a call, e.g. `urlopen(` in `src.replace("urlopen(u)", "")`.

    Python is split by `tokenize`, and a text that it cannot split is kept whole. JavaScript loses its comments and quoted strings by a pattern written here, so a call inside a template expression is blanked too.
    """
    if code_language != "python":
        return _JAVASCRIPT_STRING.sub(lambda match: " " * len(match.group(0)), code)
    line_starts = [0]
    for line in code.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))
    characters = list(code)
    try:
        for token in tokenize.generate_tokens(io.StringIO(code).readline):
            if token.type not in _PYTHON_STRING_TOKEN_TYPES:
                continue
            start = line_starts[token.start[0] - 1] + token.start[1]
            end = line_starts[token.end[0] - 1] + token.end[1]
            for index in range(start, end):
                if characters[index] != "\n":
                    characters[index] = " "
    except tokenize.TokenError, SyntaxError:
        return code
    return "".join(characters)


def _call_places(call_name: str, text: str) -> list[re.Match[str]]:
    """Find the places where a call name, or a dotted name that ends with it, is followed by `(`."""
    return list(re.finditer(rf"(?<![\w]){re.escape(call_name)}\(", text))


def _is_plain_pip_install(
    program_invocation: ProgramInvocation | UnknownProgramInvocation,
    ran_command: RanCommand,
) -> bool:
    """Tell whether a run is `pip install` with arguments and without unread words, options other than those that change nothing about the targets, run time arguments or `$` in a word."""
    return (
        isinstance(program_invocation, ProgramInvocation)
        and program_invocation.program_name == "pip"
        and program_invocation.subcommand_words == ("install",)
        and bool(program_invocation.arguments)
        and not program_invocation.unread_words
        and not program_invocation.gets_more_arguments_at_run_time
        and not any(
            program_option.name
            in (
                "-r",
                "--requirement",
                "-e",
                "--editable",
                "--no-index",
                "--help",
                "--version",
            )
            for program_option in program_invocation.options
        )
        and not any("$" in word for word in ran_command.shell_command.words)
    )


def _is_local_path(argument: str) -> bool:
    """Tell whether a pip argument names a local path, by this script's own reading apart from `parse_target`, e.g. `./dist/x.whl`, `src/pkg` or `file:///tmp/x.whl`."""
    scheme_match = re.search(r"([a-z][a-z0-9+.-]*)://", argument)
    if scheme_match:
        scheme = scheme_match.group(1)
        return scheme == "file" or scheme.endswith("+file")
    return (
        argument.startswith(("/", "~", "./", "../", ".["))
        or argument in (".", "..")
        or argument.endswith(_ARCHIVE_ENDINGS)
        or "/" in argument
    )


def _runner_command_id_of(network_request: NetworkRequest) -> int | None:
    """Give the id of the command that runs the text a request comes from, or None for a request of the call's own text or of a web tool."""
    source = network_request.source
    if isinstance(source, FromCode):
        return source.runner_command_id
    if isinstance(source, FromCommand):
        return getattr(source.ran_text_source, "runner_command_id", None)
    return None


def _means_name_of(network_request: NetworkRequest) -> str:
    """Give the program name of a command request, or the call name of a code request, which is `unknown call` when no row covers it."""
    source = network_request.source
    if isinstance(source, FromCommand):
        return source.program_invocation.program_name
    if isinstance(source, FromCode):
        return source.call_name if isinstance(source.call_name, str) else "unknown call"
    return source.harness_tool.name


def _place_text_of(network_request: NetworkRequest) -> str:
    """Write the command or code text of a request as the text of its call key and its command id or code text source."""
    source = network_request.source
    place = (
        source.command_id
        if isinstance(source, FromCommand)
        else source.code_text_source
        if isinstance(source, FromCode)
        else source.step_index
    )
    return f"{_text_of_tool_call_key(network_request.tool_call_key)}:{place}"


def _name_of_value(value: object) -> str:
    """Name an enum member by its value and any other value by its type."""
    return str(getattr(value, "value", type(value).__name__))


def _name_of_destination(network_request: NetworkRequest) -> str:
    """Name where the content of a request goes, telling a saved file with a path from one without."""
    destination = network_request.received_content_destination
    if isinstance(destination, ContentSaved):
        return (
            "ContentSaved with a path"
            if destination.path
            else "ContentSaved without a path"
        )
    return type(destination).__name__


def _text_of_tool_call_key(tool_call_key: ToolCallKey) -> str:
    """Write a tool call key as one CSV value, its trajectory id, step id and 0-based call index joined by `:`."""
    return f"{tool_call_key.trajectory_id}:{tool_call_key.step_id}:{tool_call_key.call_index}"


if __name__ == "__main__":
    main()
