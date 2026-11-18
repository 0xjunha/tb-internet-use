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
| Internet use | A request that the agent's own call causes and that turning the internet off would block. So a request to localhost is a network request but not internet use, and a failed request still counts |
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

| # | Step | Question it answers | Output | Judgment rules | Status |
|---|---|---|---|---|---|
| 0 | Collect trials | Which trials are there, and what is known about each (e.g. task, reward)? | `Trial` | 0 | Built |
| 1 | Convert tool calls | What did the trajectory record, in types that hide the harness? | `ToolCall` | 18 | Rebuilt, with shell text split into commands |
| 2 | Expand tool calls | What did each call actually run, and where does that output show up? | `ExpandedToolCall` | 23 | Built and run on the sample of 100 trials, with `pipeline.py` calling it after step 1. Its catalogs still lack rows for many programs and options, which come out as unknown. The old code still runs for steps 3 to 5 |
| 3 | Extract network requests | Which of what ran is a request, and for which target? | `NetworkRequest` | 6 | Built and run on the sample of 100 trials, with `pipeline.py` calling it after step 2. Every option of a fetching program that the sample uses has a row of its catalog except `curl -X` with a variable as its value. Programs and subcommands without a row in this catalog or in that of step 2, e.g. `lake build`, `sbt` and `git status`, still come out as unknown inputs, and `go build -o` as an uncertain request. The old code still runs for steps 4 and 5 |
| 4 | Decide request results | How far did each request get, and on what evidence? | `NetworkRequestResult` | 19 | Built and run on the sample of 100 trials, with `pipeline.py` calling it after step 3. Its catalogs and those of steps 2 and 3 still lack rows for many programs and options, so many results stay at `ATTEMPTED` or are assumed. The old code still runs for step 5 |
| 5 | Export rows | Which category is each request, and what do the rows say for each task? | `NetworkRequestRow`, `TrialRow`, `TrialCategoryMeasureRow` | 17 | Being built, with its types, the trial row, the category of a request, the network request row and the redaction of credentials, while `export_rows` still exports only a read trial without requests and no main measure rows |

A judgment rule is a choice that facts alone do not settle, e.g. whether a negative exit code means the command was killed.
Judgment rules are kept apart from outside knowledge, one function each in the `judgment_rules.py` of the step, each marked provisional or decided, and all are provisional today.
For a step that is not built yet, the number counts the places found so far.

Steps 1 and 2 are built to know nothing about the internet, so they can serve other analyses of tool calls. Steps 3 to 5 are the internet analysis.

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
