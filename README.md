# Terminal-Bench internet use analysis

Analysis of internet use patterns of agents in Terminal-Bench trajectories.

Source: 15,813 readable ATIF trajectories out of 15,990 trials of Terminal-Bench 3/4 leaderboard runs

## What it measures

Each internet request is placed by how far it got, as far as the logs show.
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

Parse records what the logs say, without deciding whether a call used the internet.
Interpret applies rules to decide what happened, so rules can change without touching the parser.

| # | Part | Step | Status |
|---|---|---|---|
| 1 | Parse | Define common types for tool calls and their outputs | Done |
| 2 | Parse | Catalog every tool call in the trajectories | Done |
| 3 | Parse | Convert each harness's `trajectory.json` to common types | In progress |
| 4 | Parse | Split shell commands and code into individual commands | Planned |
| 5 | Interpret | Extract internet requests and their targets | Planned |
| 6 | Interpret | Extract observations of network results | Planned |
| 7 | Interpret | Link requests to their observations | Planned |
| 8 | Interpret | Decide how far each request got | Planned |
| 9 | Interpret | Aggregate the results for each research question | Planned |

Stages 1 to 3 are described in [Tool call parsing](src/tb_internet_use/toolcall/README.md).

## Limits

- Currently, only ATIF trajectories are used as inputs. Several agent harnesses have missing information in ATIF, and their counts are lower bounds:
  - Devin, Grok Build: subagent and pre-compaction calls missing.
  - Cursor: subagents' inner calls missing.
- Log reads through `grep`-style tools are not counted as `ReadFileAction`.

## Development

Run `ruff`, `pyright` and `pytest`:

```bash
./scripts/check.sh
```
