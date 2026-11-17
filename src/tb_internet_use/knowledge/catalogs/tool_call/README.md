# Harness tool catalog

The harness tool catalog is outside knowledge for step 1, kept in the two CSVs of this folder. They are labeled and reviewed manually, and the conversion reads them only through `ToolCallKnowledge` in [tool_call_knowledge.py](../../tool_call_knowledge.py).

[`harness_tools.csv`](harness_tools.csv) maps each harness tool name found in ATIF trajectories to one of the `ToolCallAction` types in [model.py](../../../tool_call/model.py), one row per tool.

- **`action_type`:** `ToolCallAction` type for the tool, or `Deferred`. A tool that touches the task environment gets the type for what it does, e.g. `SearchFilesAction` for a grep tool and `StartSubagentAction` for a tool that starts a subagent. A tool that only handles the harness's own state, e.g. a plan, a to-do list, a wait or a question to the user, is `OtherAction`, with no further breakdown. Broken tool names are `UnknownAction`.
- **`stops_execution`:** `yes` when the tool stops a command, script or subagent started earlier, so its `PollAction` is a terminate. `no` for every other `PollAction` tool, and empty for a tool of any other type.

[`harness_tool_arguments.csv`](harness_tool_arguments.csv) maps the arguments of a tool to the fields of its `ToolCallAction` type, one row per argument that fills a field. An argument without a row fills none. Two arguments of a tool can fill the same field, e.g. `to` and `recipient` of Claude Code `SendMessage`, which both name the subagent. A call with both gives a field of several values, e.g. `handles` or `paths`, the values of both without repeated ones. For a field of one value, e.g. `path`, the two must agree, and a call where they differ becomes `UnknownAction`.

- **`action_field`:** Field of the tool's `ToolCallAction` type that the argument fills.
- **`handle_kind`:** Only on a row whose `action_field` is `handles`. The kind of target the argument names, e.g. `script` for the `cell_id` of Codex `wait`. Empty when the argument alone does not tell, e.g. the `task_ids` of Grok Build `get_command_or_subagent_output`, which name a command or a subagent.

Both files end with the same three columns.

- **`checked_against`:** What the row was checked against, e.g. `8 sampled tool calls in the trajectories (terminal-bench 2026-10-08)` for a label that rests on calls read beside their trajectory.
- **`reviewed`:** `yes` once a person has reviewed the row, empty until then.
- **`note`:** Free text, e.g. what the handles of an argument name, or why a tool stays `OtherAction` although some of its calls touch the task environment.

A row the conversion cannot use raises `ValueError` when the catalog is loaded, e.g. an `action_type` that names no class or an `action_field` that the class does not have. A tool without a row becomes `UnknownAction` and is counted as an unknown input.

[audit_tool_call_knowledge.py](../../../../../scripts/audit_tool_call_knowledge.py) runs the conversion on raw trials and lists, under `out/tool_call_knowledge/`, how often each row was used, the tools without a row, and every argument in the data with its value types. These listings depend on the dataset, so they stay out of the catalog, and no script writes the two CSVs.

## Deferred tools

`Deferred` means the tool name alone cannot decide the `ToolCallAction`, so the converter of its harness decides it per call in `action_of_deferred_tool`.

| Harness | Tool | Why | Decided by |
|---|---|---|---|
| codex | `exec` | Runs JS that can call several tools, so the steps of its `RunToolScriptAction` vary by call | The `tools.*` calls in the JS code of the `input` argument, read by [parse_codex_exec_script.py](../../../tool_call/parse_codex_exec_script.py). `apply_patch` and `web__run`, whose one argument holds several actions, are mapped in code, e.g. a file that a patch deletes to a `DeleteFileAction`. Any other tool of a script gets its action from its catalog row, e.g. `clock__curr_time`, which only scripts call |
| codex | `web_search_call` | One tool searches, opens a page or finds text in a page, so the `ToolCallAction` type varies by call | The `action_type` argument: `search`, `open_page` or `find_in_page` |
| cursor-cli | `mcpToolCall` | Wraps any MCP tool, such as Playwright `browser_navigate`, so the `ToolCallAction` type depends on the wrapped tool | The `toolName` argument, which names the wrapped tool. `browser_navigate` is a `WebFetchAction`, and a wrapped tool that the converter does not know is an `UnknownAction` |
