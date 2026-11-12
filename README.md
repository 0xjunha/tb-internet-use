# Terminal-Bench internet use analysis

Analysis of internet use patterns of agents in Terminal-Bench trajectories.

Source: 15,813 readable ATIF trajectories out of 15,990 trials of Terminal-Bench 3.0/4.0 leaderboard runs

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

Example: [pipeline example](docs/pipeline-example.md)

- `Collect` checks the inputs and records facts about every trial.
- `Parse` records what the trajectories say, without deciding whether a call used the internet.
- `Interpret` applies rules to decide what happened, so rules can change without touching the parser.
- `Output` makes the results safe to share and reports them.

Each trial flows through the stages in one pass: tool calls as the trajectory records them (5), the commands of each shell text on its own (6), labels of the programs those commands run (7), each call expanded into one record of everything it ran, including what its own text does not show, and of the calls that show its output (8), candidate requests (9) and observations (10) side by side, requests linked to their evidence (11), and how far each got (12).

| # | Part | Input | Step | Status |
|---|---|---|---|---|
| 1 | Collect | The leaderboard snapshot and all trial files | Verify the trial list and file hashes against the leaderboard snapshot | Planned |
| 2 | Collect | One trial's files | Record facts for every trial (e.g. task, leaderboard entry, reward, whether the trajectory is readable) | Planned |
| 3 | Parse | — | Define common types for tool calls and their outputs, so later stages never need a harness's own names | Done |
| 4 | Parse | Tool names in all trajectories | Catalog every tool in the trajectories and label it with a common type by hand | Done |
| 5 | Parse | One trial's `trajectory.json` | Convert each harness's `trajectory.json` into these common types | Done (result format catalog review pending) |
| 6 | Parse | One shell text | Split each shell text into commands, looking at that text alone, with when each runs, where its output goes and what the text's exit code says about it (e.g. after `\|\|`, piped into `tail`, redirected to a log) | Done |
| 7 | Parse | Program names in all commands (6) | Catalog the programs that commands run and label by hand what each does when a command runs it (e.g. whether `tail` reads its files, whether `npx` runs the next program, whether `pip install` makes a request) | Done (program catalog review pending) |
| 8 | Interpret | All calls of one trial (5), each text parsed by 6, and the program catalog (7) | Expand each call into one record of everything it actually ran, reading all calls of the trial for what its own text does not show: the files, heredocs, code and typed input its commands run, variable values, where its output ends up after pipes, and the later calls that show that output (e.g. written files, polls and log reads) | Done |
| 9 | Interpret | One call's expanded run (8) and the program catalog (7) | From each call's expanded run, extract candidate requests with their kinds, targets, hosts and what their run can show, before any output is read (e.g. `curl -f` exits 0 only when the content arrived) | Done |
| 10 | Interpret | One call's result (5) | Apart from requests, extract observations of network results from each call's output lines and result fields (e.g. a download line, an HTTP status) | Done |
| 11 | Interpret | One trial's requests (9), observations (10) and call runs (8) | Join 9 and 10: link each request to the lines and call facts about it through the calls from 8 that show its output (e.g. lines several requests share, whether it ran, how much of its output is visible), and add requests only the output reveals | Planned |
| 12 | Interpret | One linked request (11) | For each linked request, decide the furthest level shown, how strong its evidence is, and what stopped it or hid the rest, keeping the evidence | Planned |
| 13 | Output | One result row | Redact credentials and omit hidden task lines before result rows are written | Planned |
| 14 | Output | All result rows | Aggregate the rows for each research question | Planned |
| 15 | Output | The aggregates (14) | Build the spreadsheet (e.g. tabs, formulas, charts) and check it against the aggregates | Planned |

Stages 3 to 5 are described in [Tool call parsing](src/tb_internet_use/toolcall/README.md), and stage 7 in [Program catalog](src/tb_internet_use/program/catalogs/README.md).
Work left for later is listed in [TODO](TODO.md).

### Code layout

| Package | Stages | Entrypoint function |
|---|---|---|
| `toolcall/` | 3 to 5 | `convert_trial(trial_dir) -> list[ToolCall]` |
| `shell/` | 6 | `parse_shell(text) -> ParsedShellText` |
| `program/` | 7, and shared by 8 and 9 | `program_catalog() -> Mapping[str, tuple[ProgramCatalogRow, ...]]` |
| `callrun/` | 8 | `expand_calls(calls) -> tuple[CallRun, ...]` |
| `network/` | 9, 10 | None, shared (host and package names) |
| `request/` | 9 | `extract_candidate_requests(call_run) -> tuple[CandidateRequest, ...]` |
| `observation/` | 10 | `extract_observations(call) -> tuple[Observation, ...]` |
| `trial_interpretation.py` | 8 to 10 | `interpret_trial_before_linking(calls) -> TrialLinkingInputs` |

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
