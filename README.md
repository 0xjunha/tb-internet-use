# Terminal-Bench internet use analysis

> **Work in progress.**

This project finds how agents on the Terminal-Bench leaderboard use the internet, reading their trajectories alone. It shows which tasks depend on the internet and for what.

A trial is one run of an agent on one task. Its trajectory is the record of the agent's tool calls and their results, and the harness is the agent program that made them, e.g. Claude Code.

The source is 15,813 readable trajectories in ATIF format, out of 15,990 trials of Terminal-Bench 3.0/4.0 leaderboard runs.

## What it answers

For each task and each category of request (e.g. packages, fetched files, web search, page reads), it gives two shares of the task's trials:

- the share of trials with at least one such request
- the share of trials that received what such a request asked for

Each share comes as a lower bound, which counts only what the trajectory confirms, and an upper bound, which also counts what it cannot rule out.
Every request is kept as a row with its place in the trajectory and its evidence, so other questions can be answered from the same rows.

## What counts

| Term | Meaning |
|---|---|
| Internet use | A request that the agent's own call causes and that turning the internet off would block. So a request to localhost, or to a name without a dot such as `db` that resolves only inside the task environment, is a network request but not internet use, and a failed request still counts |
| One request | One target that one command, code text or web tool call tries to get, e.g. two for `pip install A B` |
| How far it got | The furthest level below that the trajectory shows, with why it stopped there: it failed, nothing further is visible, or nothing needed sending (e.g. pip prints `Requirement already satisfied`) |

| Level | Meaning |
|---|---|
| Attempted | The agent sent a call containing a request, even if the harness rejected it |
| Executed | The command or tool actually ran |
| Reached | The request got to the remote server. An HTTP 403 counts, since the server responded |
| Received | The agent got the requested content, such as a finished download or search results |

## How it reads a trajectory

The pipeline reads only the text of tool calls and their results. It runs nothing from a trajectory, and it has no network logs to check against.
The hard part is that a request, or its output, is often not in the call that caused it.

| | In the call itself | Elsewhere in the trajectory | Not in the trajectory |
|---|---|---|---|
| What ran | `curl https://example.org/x` | A script that an earlier call wrote | A task script or a binary |
| Where its output shows | The call's result | A later poll, or a later read of a log file | Discarded, or never read |
| What the pipeline does | Reads it | Follows it | Records it as unknown |

Two rules follow from this.

- What the trajectory does not show is recorded as unknown and never filled with a default such as "finished". This is why the results come as bounds.
- Facts that no trajectory holds are outside knowledge, e.g. that `curl -o` takes a file name, or how a harness words a timeout. They are kept apart from the steps, in catalogs that a person fills and reviews. When a fact is missing, the answer is unknown. Each run lists its unknowns by how many trials they touch, which is the list of facts to add next.

## Pipeline

The [pipeline example](docs/pipeline-example.md) follows six made-up tool calls through these steps.

| # | Step | Question it answers | Entry function | Output | Judgment rules | Status |
|---|---|---|---|---|---|---|
| 0 | Collect trials | Which trials are there, and what is known about each (e.g. task, reward)? | `collect_trials` in `trial/` | `Trial` | 0 | Built |
| 1 | Convert tool calls | What did the trajectory record, in types that hide the harness? | `convert_tool_calls` in `tool_call/` | `ToolCall` | 18 | Built, with each shell text split into commands by shell grammar |
| 2 | Expand tool calls | What did each call actually run, and where does that output show up? | `expand_tool_calls` in `expanded_tool_call/` | `ExpandedToolCall` | 23 | Built and run on a sample of 100 trials, where many programs and options still have no catalog row and come out as unknown inputs |
| 3 | Extract network requests | Which of what ran is a request, and for which target? | `extract_network_requests` in `network_request/` | `NetworkRequest` | 6 | Built and run on a sample of 100 trials, where a program or option without a catalog row still comes out as an unknown input or an uncertain request |
| 4 | Decide request results | How far did each request get, and on what evidence? | `decide_network_request_results` in `network_request_result/` | `NetworkRequestResult` | 19 | Built and run on a sample of 100 trials, where many results stay at `ATTEMPTED` since the exit code of a text shows nothing of a command in a loop, before a pipe or in a file |
| 5 | Export rows | Which category is each request, and what do the rows say for each task? | `export_rows` in `export/` | `NetworkRequestRow`, `TrialRow`, `TrialCategoryMeasureRow` | 18 | Built and run on a sample of 100 trials, where most public hosts and web tools still have no catalog row and come out as unknown inputs |

Each step is a package of `src/tb_internet_use/` whose `__init__.py` exports only its entry function, and whose types are in its `model.py`.
`run_steps_of_trial` in `pipeline.py` reads the files of one trial folder, makes the doors of outside knowledge and calls the six entry functions in order. The steps themselves take text and types, never a path.

Steps 1 and 2 are built to know nothing about the internet, so they can serve other analyses of tool calls. Steps 3 to 5 are the internet analysis.

## Outside knowledge

Each step from step 1 on asks for outside knowledge only through its door, one class in `knowledge/` named after its output type, which its entry function takes as `knowledge`.
An answer of a door is a value or an `Unknown…` type, never a default, and the door counts each fact it used and each input it had no fact for.

| Door | Step | Where its facts live |
|---|---|---|
| `ToolCallKnowledge` | `convert_tool_calls` | `catalogs/tool_call/`, and the result formats of each harness tool under `declarations/tool_call/` |
| `ExpandedToolCallKnowledge` | `expand_tool_calls` | `catalogs/expanded_tool_call/` |
| `NetworkRequestKnowledge` | `extract_network_requests` | `catalogs/network_request/` |
| `NetworkRequestResultKnowledge` | `decide_network_request_results` | `catalogs/network_request_result/`, and the output line patterns under `declarations/network_request_result/` |
| `ExportKnowledge` | `export_rows` | `catalogs/export/` |

A catalog is a hand-filled CSV, one row per fact, e.g. one program of `program_behaviors.csv`. A declaration is Python, for facts whose order matters or that share parts, e.g. the output line patterns, of which the first that fits a line gives its meaning. Every row says what it was checked against and whether a person reviewed it.
The [knowledge README](src/tb_internet_use/knowledge/README.md) lists every file with the question it answers, and the README beside each catalog folder describes its columns.

## Judgment rules

A judgment rule is a choice that facts alone do not settle, e.g. whether a negative exit code means the command was killed.
Judgment rules are kept apart from outside knowledge, one function each in the `judgment_rules.py` of the step, which counts each of its uses. Each is marked provisional or decided. One is decided today, `treat_single_label_host_name_as_not_internet_use` of `export/`, which counts a request to a host name without a dot, e.g. `db`, as no internet use, since such a name resolves only inside the task environment.
A provisional rule keeps the choice of the earlier code, or where there was none the choice that claims least, e.g. that a command with no evidence of its own that it ran is not known to have run, so that the lower bounds stay true.

## Running

`scripts/run_pipeline.py` runs `run_steps_of_trial` on the trial folders of a raw data folder, in at most 4 processes, and writes under `out/pipeline/`, which git ignores, since the rows hold targets and host names from the trajectories.

```bash
nice -n 10 uv run python -I scripts/run_pipeline.py <raw_trials_dir> [--limit N | --trial-ids FILE] [--out-dir DIR] [--resume | --export-only]
```

| It writes | One row |
|---|---|
| `network_request_rows.csv`, `trial_rows.csv`, `trial_category_measure_rows.csv` | One row of each row type of `export_rows` |
| `task_category_measures.csv` | A task, a category and a sender, with the trials in each bound of the main measure |
| `<step package>/unknown_inputs.csv` | An input that the door of the step had no row for, most trials first |
| `<step package>/row_uses.csv`, `<step package>/judgment_rule_uses.csv` | A row of the door, or a judgment rule, with its uses, trials and tasks |
| `equations.csv` | An equation between steps, e.g. that every network request result gives one request row |
| `raised_trials.csv`, `summary.csv` | A trial that raised or ran too long, and the counts of the run |

The script exits with 1 when a trial raised or an equation differs. `--resume` goes on with a run that stopped, and `--export-only` runs only `export_rows` again on the saved output of the steps before it. Its docstring lists every file and equation.

Each step also has an audit script that runs the steps up to it, counts its output per harness and checks equations that the output must meet. They write under `out/` and print no text of a trajectory.

| Script | Step |
|---|---|
| `audit_trials.py` | `collect_trials`, with its counts held against an expectation file |
| `audit_tool_call_knowledge.py`, `audit_results.py`, `audit_parsed_shell_texts.py` | `convert_tool_calls`: the uses of its door, the result formats each result matched, and the split shell texts |
| `audit_expanded_tool_calls.py` | `expand_tool_calls` |
| `audit_network_requests.py` | `extract_network_requests` |
| `audit_network_request_results.py` | `decide_network_request_results` |
| `audit_export_knowledge.py` | `export_rows`, run again on the saved output of `run_pipeline.py` |

`build_harness_result_format_table.py` writes the declared result formats as one table for a person to read. Each script's docstring says how to run it.

## Filling outside knowledge

1. Run `scripts/run_pipeline.py` on the trials.
2. Read `out/pipeline/<step package>/unknown_inputs.csv` from the top, where the inputs that the most trials asked for come first.
3. Add a row for the input by hand to the catalog that the README of its folder names. Write in `checked_against` what the fact was checked against, e.g. a section of a manual, and leave `reviewed` empty until a person has reviewed the row.
4. Run `./scripts/check.sh`. A row that the step cannot use raises when the catalog is loaded.
5. Run the pipeline again. The input is gone from `unknown_inputs.csv`, and `row_uses.csv` shows how often the new row was used.

## Limits

- Only ATIF trajectories are read. ATIF lacks some calls of several harnesses, so what is counted for them is less than what happened:
  - Devin, Grok Build: subagent and pre-compaction calls missing.
  - Cursor CLI: subagents' inner calls missing.
- Requests made outside the trajectory, such as those of the image build or the verifier, are out of scope.

## Development

Run `ruff`, `pyright` and `pytest`:

```bash
./scripts/check.sh
```
