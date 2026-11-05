# Tool call parsing

Stages 1 to 3 of the [pipeline](../../../README.md#pipeline): read ATIF trajectories and convert every logged tool call to common types.

## Data model

ATIF keeps each harness's own tool names, and different harnesses have different tool names for the same roles.
For example, a shell call is named `Bash` in Claude Code, `exec_command` in Codex and `run_terminal_command` in Grok Build.
ATIF has an `agent.tool_definitions` field, but none of these trajectories fill it, so analysis needs common types.

```
trajectory.json -> RawToolCall -> ToolCall(raw, action, output)
```

| Type | Content |
|---|---|
| `RawToolCall` | One logged call and its result, as is |
| `ToolCall.action` | Request: what the call tried to do, in the kinds that matter for internet use |
| `ToolCall.output` | Result: text, status, exit code, handles |

Defined in [model.py](model.py).

| `Action` | Why tracked |
|---|---|
| `RunCommandAction` | Shell requests, such as `curl`, `pip install`, `git clone` |
| `RunScriptAction` | Requests from code that can call several tools, such as Codex `exec` |
| `WebSearchAction`, `WebFetchAction`, `WebFindAction` | Dedicated web tools |
| `WriteFileAction`, `EditFileAction` | Network code written to a file and run later |
| `ReadFileAction` | Output sent to a log file instead of stdout |
| `PollAction` | Background output arrives in a later call; stopping shows whether it finished |
| `OtherAction` | Not needed for the above, such as grep tools, to-do lists, subagent management |
| `UnknownAction` | Tool the harness does not have (broken or disabled names) |

## Tool call labeling

[Tool catalog](catalogs/README.md): 1,617,509 calls, 117 tools, 364 rows.

| Step | Method |
|---|---|
| Count tools and arguments | Code: [`build_harness_tool_catalog.py`](../../../scripts/build_harness_tool_catalog.py) |
| Label `action_type`, `action_field` | LLM draft, human review of every row |
| Settle doubtful labels | LLM checks raw logs, human decides |

Tools whose `Action` varies by call are labeled [`Deferred`](catalogs/README.md#deferred-tools).

## Conversion

| Step | Code | Produces |
|---|---|---|
| Read a trajectory, pair calls with results | [`atif_reader.py`](atif_reader.py) | `RawToolCall` |
| Build the action from catalog labels | [`catalog_loader.py`](catalog_loader.py), [`convert.py`](convert.py) | `Action` |
| Parse the result, fill what labels cannot express | [`HarnessConverter`](harnesses/base.py), one per harness (next) | `ToolCallOutput`, `Action` |
