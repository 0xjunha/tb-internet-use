# Terminal-Bench internet use analysis

Analysis of internet use patterns of agents in Terminal-Bench trajectories.

Source: 15,813 readable ATIF trajectories out of 15,990 trials of Terminal-Bench 3/4 leaderboard runs

## Approach

Parse all tool calls and their outputs from the trajectories into common types.
From these, extract internet requests from what the agent ran (Request), and observations
of network results, such as download progress or search results, from what came back (Receive).
Link the two to determine how far each request got, as far as the logs show:

1. **Attempted:** the agent sent a call containing an internet request, even if the harness rejected it.
2. **Executed:** the command or tool actually ran.
3. **Reached:** the request got to the remote server. An HTTP 403 counts, since the server responded.
4. **Received:** the agent got the requested content, such as a finished download or search results.

Further analysis builds on this data.

| Side | Source |
|---|---|
| Request | Shell commands, code written to files and run later, code in Codex `exec`, input sent to running processes, web tool arguments |
| Receive | Tool call outputs, background output polled later, harness output files and redirected logs read later, completion notifications |

The pipeline has two parts, so rules can change without touching the parser.

**Parse: record what the logs say, without deciding whether a call used the internet.**

1. Define common data models to represent tool calls and tool call outputs related to internet use.
2. Build a catalog of all known tool calls found in the trajectories.
3. Convert `trajectory.json` of different harnesses into a common format.
4. Split shell commands and code into individual commands.

**Interpret: apply rules to the parsed data to decide what happened.**

5. Extract internet requests and their targets from commands, code, process input and web tool arguments.
6. Extract observations of network results from tool outputs, polled output, files read later and completion notifications.
7. Link requests to their output observations.
8. Decide how far each request got: attempted, executed, reached or received.
9. Aggregate the results for each research question.

## Data model

ATIF keeps each harness's own tool names, and different harnesses have different tool names for the same roles.
For example, a shell call is named `Bash` in Claude Code, `exec_command` in Codex and `run_terminal_command` in Grok Build.

ATIF has an `agent.tool_definitions` field, but none of these trajectories fill it.
Therefore, analysis needs common types to represent tool calls:

- **`ToolCall`:** one logged call, in a harness-agnostic form.
- **`Action`:** what the call tried to do, abstracted to the kinds that matter for internet use.

Defined in [model.py](src/tb_internet_use/toolcall/model.py).

| `ToolCall` field | Content |
|---|---|
| `raw_args`, `output.raw_result` | Log as is |
| `actions` | Request, in common types |
| `output` | Result: text, status, exit code, handles |

| `Action` | Why tracked |
|---|---|
| `RunCommandAction` | Shell requests, such as `curl`, `pip install`, `git clone` |
| `WebSearchAction`, `WebFetchAction`, `WebFindAction` | Dedicated web tools |
| `WriteFileAction`, `EditFileAction` | Network code written to a file and run later |
| `ReadFileAction` | Output sent to a log file instead of stdout |
| `PollAction` | Background output arrives in a later call; stopping shows whether it finished |
| `OtherAction` | Not needed for the above, such as grep tools, to-do lists, subagent management |
| `UnknownAction` | Tool the harness does not have (broken or disabled names) |

## Tool call labeling

[Tool catalog](src/tb_internet_use/toolcall/catalogs/README.md): 1,617,509 calls, 117 tools, 364 rows.

| Step | Method |
|---|---|
| Read trajectories, pair calls with results | Code: [`atif_reader.py`](src/tb_internet_use/toolcall/atif_reader.py) |
| Count tools and arguments | Code: [`build_harness_tool_catalog.py`](scripts/build_harness_tool_catalog.py) |
| Label `action_type`, `action_field` | LLM draft, human review of every row |
| Settle doubtful labels | LLM checks raw logs, human decides |
| Convert calls | Code (next) |

Tools whose type varies by call are labeled `Deferred`; the converter decides.

## Limits

- Currently, only ATIF trajectories are used as inputs. Several agent harnesses have missing information in ATIF, and their counts are lower bounds:
  - Devin, Grok Build: subagent and pre-compaction calls missing.
  - Cursor: subagents' inner calls missing.
- Log reads through `grep`-style tools are not counted as `ReadFileAction`.
