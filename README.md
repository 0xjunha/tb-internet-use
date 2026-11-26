# Terminal-Bench internet use analysis

> **Work in progress.**

A pipeline to measure how agents on the Terminal-Bench leaderboard use the internet, based on ATIF trajectories.
It shows how often agents use the internet in each task and what for, e.g. to install a package or to search the web.

- Data: Terminal-Bench 4.1 leaderboard on Harbor Hub, downloaded on 2026-11-19 (20,839/21,450 trials are readable)

## What it answers

For each task and each category of request (e.g. package or web search) it gives two shares of the task's trials: 1) trials with an internet request 2) trials that received what a request asked for.

Each share is reported as a lower bound and an upper bound, since a trajectory does not always show whether a command ran or what it printed.

Internet request is reported in four levels:

| Level | Meaning |
|---|---|
| Attempted | The agent sent a call containing a request |
| Executed | The command or tool ran |
| Reached | The request got to the remote server, e.g. an HTTP 403 |
| Received | The agent got the content, e.g. a finished download or search results |

## Lower and upper bounds

The lower bound counts the trials that the trajectory confirms.

- Request: a call holds a request, e.g. `pip install requests`.
- Received: the output shows it, e.g. `Successfully installed requests-2.32.3`.

The upper bound adds the trials that the trajectory cannot rule out.

- Request
  - The program downloads only what is missing and no line of its output shows that it sent a request, e.g. `npx tool`.
  - The program is not in the catalogs but has a URL among its words, e.g. `mytool https://a.org/x`.
  - The target does not show whether it is on the internet, e.g. `git fetch origin` or `curl "$URL"`.
  - A variable set before the command may send it to another host or keep it from going out, e.g. `GOPROXY=http://localhost:3000 go build`.
  - The request is in the last content of a file that the trajectory shows, and a command that it does not read may have changed the file before it ran, e.g. `requests.get(u)` of fetch.py before `sed -i s/a/b/ *.py` and `python fetch.py`. Such a request is never in the lower bounds, whatever its run prints.
- Received
  - The output is discarded or never read, e.g. `pip install -q x > /dev/null`, or a background command that no later call polls.
  - Nothing shows that the command ran, e.g. a command in a loop or in a script.
  - One error line fits several requests, so each of them may still have received, e.g. one `curl: (28) Connection timed out` after two `curl` commands.

## Pipeline

| # | Step | Description | Package | Output | Judgment rules |
|---|---|---|---|---|---|
| 0 | Collect trials | Lists the trials with their task, harness, model and reward | `trial/` | `Trial` | 0 |
| 1 | Convert tool calls | Normalizes the tool calls of each harness into common types | `tool_call/` | `ToolCall` | 22 |
| 2 | Expand tool calls | Links each call to the scripts it runs and to the later calls that show its output | `expanded_tool_call/` | `ExpandedToolCall` | 23 |
| 3 | Extract network requests | Looks up each program and code call in the catalogs and reads its targets | `network_request/` | `NetworkRequest` | 7 |
| 4 | Decide request results | Matches each request's output lines and exit code to known patterns | `network_request_result/` | `NetworkRequestResult` | 23 |
| 5 | Export rows | Flattens the results into table rows per request and per trial, with category and bounds | `export/` | `NetworkRequestRow`, `TrialRow`, `TrialCategoryMeasureRow` | 22 |

## Why tool calls are expanded

A request and its output are often not in the call that caused them, so reading each call alone would miss them. The step "Expand tool calls" links the calls before requests are looked for.

- What ran can be elsewhere. `bash fetch.sh` runs the `curl` of a script that an earlier call wrote.
- Its output can be elsewhere. A background command prints into a later poll, or into a log file that a later call reads, e.g. `tail fetch.log`.
- What the trajectory does not hold stays unknown, e.g. a script of the task image. This is why the results come as bounds.

The steps also rely on two things that no trajectory gives.

- Outside knowledge: a fact about a program or a harness, e.g. that `curl -o` takes a file name. Facts are hand-filled [catalogs](src/tb_internet_use/knowledge/README.md), each with its source.
- Judgment rule: a choice that facts do not settle, e.g. whether a silent `curl` with exit code 0 received its file. Each is one named function in the `judgment_rules.py` of its step.

## How to run

```bash
# Download trajectories
uv run python -I scripts/download_trials.py <collection_dir> --leaderboard 4-1-0 --skip-archives
# Run the pipeline
uv run python -I scripts/run_pipeline.py <collection_dir>/raw
```

## Spreadsheet

The [spreadsheet guide](docs/spreadsheet.md) says how to build the Google Sheets spreadsheet from a run and publish it.

## Limits

- Most requests stop at an unknown result. A command in a loop, before a pipe or in a script often shows no output of its own, so the lower end of "received" is far below the upper end.
- Catalogs are filled from the most asked facts down. Programs, options and hosts without a row in the catalogs come out as unknown.
- ATIF leaves out some calls of several harnesses, so their counts are lower bounds.

  | Harness | Calls missing |
  |---|---|
  | Grok Build, Devin | Calls of subagents, and calls before a compaction |
  | Antigravity CLI | Calls of subagents, which run as a separate conversation |
  | Cursor CLI | Inner calls of subagents |
  | Copilot CLI | The start of some shells that a later call reads, e.g. with `read_bash` |

  Devin and Cursor CLI are on the Terminal-Bench 3.0/4.0 leaderboards only.

- Claude Code and Grok Build sometimes report the end of a background task inside the result of a later call. That report is not read.

## Development

```bash
./scripts/check.sh
```

It runs `ruff`, `pyright` and `pytest`.

Read more:

- [Pipeline example](docs/pipeline-example.md)
- [Outside knowledge](src/tb_internet_use/knowledge/README.md)
- [Tool call conversion](src/tb_internet_use/tool_call/README.md)
