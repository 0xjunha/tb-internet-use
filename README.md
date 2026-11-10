# Terminal-Bench internet use analysis

Analysis of internet use patterns of agents in Terminal-Bench trajectories.

Source: 15,813 readable ATIF trajectories out of 15,990 trials of Terminal-Bench 3/4 leaderboard runs

## What it measures

Each internet request is placed by how far it got, as far as the trajectories show.
Further analysis builds on this data.

| Level | Meaning |
|---|---|
| Attempted | The agent sent a call containing an internet request, even if the harness rejected it |
| Executed | The command or tool actually ran |
| Reached | The request got to the remote server. An HTTP 403 counts, since the server responded |
| Received | The agent got the requested content, such as a finished download or search results |

## Evidence

| Side | What it shows | Source |
|---|---|---|
| Request | What the agent ran | Shell commands, code written to files and run later, code in Codex `exec`, input sent to running processes, web tool arguments |
| Receive | What came back | Tool call outputs, background output polled later, harness output files and redirected logs read later, completion notifications |

## Pipeline

- `Collect` checks the inputs and records facts about every trial.
- `Parse` records what the trajectories say, without deciding whether a call used the internet.
- `Interpret` applies rules to decide what happened, so rules can change without touching the parser.
- `Output` makes the results safe to share and reports them.

| # | Part | Step | Status |
|---|---|---|---|
| 1 | Collect | Verify the trial list and file hashes against the leaderboard snapshot | Planned |
| 2 | Collect | Record facts for every trial (e.g. task, leaderboard entry, reward, whether the trajectory is readable) | Planned |
| 3 | Parse | Define common types for tool calls and their outputs | Done |
| 4 | Parse | Catalog and manually label every tool call in the trajectories | Done |
| 5 | Parse | Convert each harness's `trajectory.json` to common types | Done (result format catalog review pending) |
| 6 | Parse | Parse shell text into commands, with when each runs, where its output goes and what the text's exit code says about it (e.g. after `\|\|`, piped into `tail`, redirected to a log) | In progress |
| 7 | Interpret | Resolve what each call runs and which calls show its output (e.g. written files, variables, polls and log reads) | Planned |
| 8 | Interpret | Extract candidate requests with their kinds, targets, hosts and what their run can show (e.g. `curl -f` exits 0 only when the content arrived) | Planned |
| 9 | Interpret | Extract observations of network results from output lines and result fields (e.g. a download line, an HTTP status) | Planned |
| 10 | Interpret | Link each request to the lines and call facts that are about it (e.g. lines several requests share, whether it ran, how much of its output is visible), including requests only the output reveals | Planned |
| 11 | Interpret | Decide the furthest level shown, how strong its evidence is, and what stopped it or hid the rest, keeping the evidence | Planned |
| 12 | Output | Redact credentials and omit hidden task lines before rows are written | Planned |
| 13 | Output | Aggregate the results for each research question | Planned |
| 14 | Output | Build the spreadsheet (e.g. tabs, formulas, charts) and check it against the aggregates | Planned |

Stages 3 to 5 are described in [Tool call parsing](src/tb_internet_use/toolcall/README.md).
For how the data changes shape from stage to stage, see the [pipeline example](docs/pipeline-example.md).

## Limits

- Currently, only ATIF trajectories are used as inputs. Several agent harnesses have missing information in ATIF, and their counts are lower bounds:
  - Devin, Grok Build: subagent and pre-compaction calls missing.
  - Cursor: subagents' inner calls missing.
- Log reads through `grep`-style tools are not counted as `ReadFileAction`.
- Codex `exec` steps are read from the script without running it. A call in a loop is one step, and an argument the script computes is left empty.

## Development

Run `ruff`, `pyright` and `pytest`:

```bash
./scripts/check.sh
```
