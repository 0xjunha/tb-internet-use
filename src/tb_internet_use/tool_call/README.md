# Convert tool calls

The step "Convert tool calls" of the [pipeline](../../../README.md#pipeline), whose entry function is `convert_tool_calls`: read ATIF trajectories and convert every tool call in them to common types.

| Section | Code |
|---|---|
| [Data model](#data-model) | [model.py](model.py) |
| [Tool call labeling](#tool-call-labeling) | [knowledge/](../knowledge/README.md) |
| [Conversion](#conversion), [Result formats](#result-formats) | [_convert_tool_calls.py](_convert_tool_calls.py), [_convert_tool_call_action.py](_convert_tool_call_action.py), [_convert_tool_call_result.py](_convert_tool_call_result.py), [harnesses/](harnesses/), [judgment_rules.py](judgment_rules.py) |

## Data model

ATIF keeps each harness's own tool names, and different harnesses have different tool names for the same roles.
For example, a shell call is named `Bash` in Claude Code, `exec_command` in Codex and `run_terminal_command` in Grok Build.
ATIF has an `agent.tool_definitions` field, but none of these trajectories fill it, so analysis needs common types.

```
trajectory.json -> HarnessToolCall -> ToolCall(harness_tool_call, action, result)
```

| Type | Content |
|---|---|
| `HarnessToolCall` | One call in the trajectory and its result, as is |
| `ToolCall.action` | Request: what the call tried to do, with one type for each kind of act on the task environment |
| `ToolCall.result` | Result: tool output text, status, exit code, HTTP status, handles |

Defined in [model.py](model.py).

A tool that touches the task environment gets the type for what it does, the same in every harness. A tool that only handles the harness's own state is `OtherAction`. A type has a field only where a later step reads it, and every argument stays in `HarnessToolCall.args`.

| `ToolCallAction` | What the tool does | e.g. |
|---|---|---|
| `RunCommandAction` | Runs a string in a shell | Claude Code `Bash`, Codex `exec_command` |
| `RunToolScriptAction` | Runs code that calls harness tools, with one step per tool call found in the code | Codex `exec` |
| `WriteFileAction` | Writes a whole file | Claude Code `Write` |
| `EditFileAction` | Replaces text in a file | Grok Build `search_replace` |
| `DeleteFileAction` | Deletes a file | Cursor CLI `deleteToolCall`, a `Delete File` of a Codex patch |
| `ReadFileAction` | Reads a file, an image too | Devin `read`, Codex `view_image` |
| `SearchFilesAction` | Searches the content of files | Grok Build `grep`, Muse Code `search` |
| `ListFilesAction` | Finds files by name or lists a folder | Cursor CLI `globToolCall`, Grok Build `list_dir` |
| `WebSearchAction`, `WebFetchAction`, `WebFindAction` | Searches the web, opens a page, finds text in a page | Claude Code `WebSearch`, `WebFetch` |
| `StartSubagentAction` | Starts a subagent, whose own calls may or may not be in the trajectory | Claude Code `Agent`, Devin `run_subagent` |
| `PollAction` | Reads from, writes to or stops a command, script or subagent started earlier | Codex `write_stdin`, Claude Code `TaskStop`, `SendMessage` |
| `OtherAction` | Only handles the harness's own state, e.g. a plan, a to-do list, a wait or a question to the user | Codex `update_plan`, Devin `todo_write` |
| `UnknownAction` | A tool without a row in the catalog, e.g. a broken or disabled name, or a call that could not be converted | |

## Tool call labeling

What each harness tool does is outside knowledge, which no trajectory holds. It is kept in the [harness tool catalog](../knowledge/catalogs/tool_call/README.md), two hand-filled CSVs under [knowledge/](../knowledge/README.md): one row per harness tool, and one row per argument that fills an action field.

| Step | Method |
|---|---|
| List the tools and arguments in the data | Code: [`audit_tool_call_knowledge.py`](../../../scripts/audit_tool_call_knowledge.py), which writes under `out/` and never into the catalog |
| Label `action_type`, `action_field` | LLM draft, then human review, which the `reviewed` column records per row |
| Settle doubtful labels | LLM checks raw trajectories, human decides |

Tools whose `ToolCallAction` varies by call are labeled [`Deferred`](../knowledge/catalogs/tool_call/README.md#deferred-tools).

## Conversion

`read_trajectory(trial_dir)` in [pipeline.py](../pipeline.py) opens the trajectory file of one trial, and `convert_tool_calls(harness_tool_calls, knowledge=..., judgment_rule_use_counts=...)` in [_convert_tool_calls.py](_convert_tool_calls.py) converts every call that was read.
`knowledge` is a `ToolCallKnowledge`, the only way from this step to the harness tool catalog and the declared result formats. It counts every use of a catalog row or a declared result format and every input without one, so a run can list the rows it used, the tools without a row and the results without a format.

| Step | Code | Produces |
|---|---|---|
| Read the text of a trajectory file, pair calls with results | [`parse_trajectory.py`](parse_trajectory.py) | `HarnessToolCall`, or `UnreadableTrajectory` when the file is missing or is not JSON |
| Build the action from the label of the tool and the arguments | [`_convert_tool_call_action.py`](_convert_tool_call_action.py), with the label from [`tool_call_knowledge.py`](../knowledge/tool_call_knowledge.py) | `ToolCallAction`, `UnknownAction` for a tool without a row or for a call whose two arguments give a field of one value different values |
| Match the result against the harness's declared result formats | [`_convert_tool_call_result.py`](_convert_tool_call_result.py), one [`HarnessToolCallConverter`](harnesses/harness_tool_call_converter.py) per harness in [harnesses/](harnesses/), with the formats from [`tool_call_knowledge.py`](../knowledge/tool_call_knowledge.py) | `ToolCallResult` |
| Fill what the action type and argument fields of a label cannot express, e.g. the handles a result names, the terminate of a stop tool, Deferred tools | `HarnessToolCallConverter.refine_action`, `action_of_deferred_tool` | `ToolCallAction` |

## Result formats

Each harness writes a tool result in its own words, and each tool has several result formats, e.g. for a finished, running or refused call.
The table shows only one situation, a shell command that exits with code 0 and prints `hello`, with made-up values.

| Harness | Tool | Format | Result in the trajectory |
|---|---|---|---|
| Claude Code | `Bash` | `bare_output` | `hello`, with no exit code line |
| Codex | `exec_command` | `exited` | `Chunk ID: a1b2c3`<br>`Wall time: 0.0512 seconds`<br>`Process exited with code 0`<br>`Original token count: 1`<br>`Output:`<br>`hello` |
| Cursor CLI | `shellToolCall` | `exited` | `{"success": {"exitCode": 0, "interleavedOutput": "hello"}}` |
| Devin | `exec` | `exited` | `Output from command in shell 3:`<br>`hello`<br>`Exit code: 0` |
| Grok Build | `run_terminal_command` | `exited` | `exit: 0`<br>`hello` |
| mini-swe-agent | `bash` | `exited` | `{"output": "hello", "returncode": 0}` |
| Muse Code | `bash` | `exited` | `{"terminal_status": "completed", "exit_code": 0, "output": "hello", "truncated": false}` |

The formats are outside knowledge, declared per harness in [knowledge/declarations/tool_call/harness_result_formats/](../knowledge/declarations/tool_call/harness_result_formats/README.md). Every format of every tool is in the [result format catalog](../knowledge/declarations/tool_call/harness_result_formats/README.md#result-format-catalog), written from the code by [`build_harness_result_format_catalog.py`](../../../scripts/build_harness_result_format_catalog.py) and reviewed by hand. [`audit_results.py`](../../../scripts/audit_results.py) counts each format on the raw trials into the [result format audit](../knowledge/declarations/tool_call/harness_result_formats/README.md#result-format-audit).

### What a result splits into

```
raw text         = notices + annotated output
annotated output = annotation + tool output
```

| Part | What it is | Where it goes |
|---|---|---|
| Tool output | What the tool itself produced | `ToolCallResult.tool_output_text` |
| Annotation | What the harness wrote about the call, e.g. an exit code line | Execution status, exit code, HTTP status, handles, output path, truncation |
| Notice | A message the harness may add at the start or end of any result, e.g. Grok's completion notifications | Cut before matching, fills no field. Still in `harness_tool_call.result` for later steps |

A truncation marker, which a harness leaves inside a tool output it cut, stays in the tool output and sets `is_truncated`.

### Two kinds of result format

A result format describes one shape of a tool's annotated output.
A harness declares, per tool, up to three lists of formats ([`HarnessResultFormatList`](../knowledge/harness_result_format_declaration.py)) with the tool's notices, in a `HarnessToolResultDeclaration`: one for text results, one for JSON results, and one for text results that the harness marked as an error.
Syntax and rules are in [harness_result_format_declaration.py](../knowledge/harness_result_format_declaration.py).

| | Text format | JSON format |
|---|---|---|
| Class | [`HarnessTextResultFormat`](../knowledge/harness_result_format_declaration.py) | [`HarnessJsonResultFormat`](../knowledge/harness_result_format_declaration.py) |
| Annotated output | A string | A JSON object |
| Declared as | A template: fixed text plus `{name:type}` placeholders | JSON paths the object must have or lack, and an optional condition on one value |
| Has this format when | The template matches the whole annotated output, first character to last | The paths are present or absent as declared and the condition holds |
| Tool output | The `tool_output` placeholder | The `tool_output` value path |
| Annotation values | The other placeholders | The other value paths |
| Example | Devin `exec` in [devin.py](../knowledge/declarations/tool_call/harness_result_formats/devin.py) | Cursor CLI `shellToolCall` in [cursor_cli.py](../knowledge/declarations/tool_call/harness_result_formats/cursor_cli.py) |

Format `exited` of each example, with made-up values.

```
Text format (Devin exec)

template
  Output from command in shell {handle:id}:
  {tool_output:text}
  Exit code: {exit_code:int}

annotated output
  Output from command in shell 3:
  hello
  Exit code: 0
```

```
JSON format (Cursor CLI shellToolCall)

present paths  success.exitCode
absent paths   success.shellId, success.outputLocation
value paths    tool_output = success.interleavedOutput
               exit_code   = success.exitCode

annotated output
  {"success": {"exitCode": 0, "interleavedOutput": "hello"}}
```

Both give `tool_output_text="hello"`, `exit_code=0`, status `finished`.

### How one result is parsed

[`convert_tool_call_result`](_convert_tool_call_result.py) hands a call with a result to [`HarnessToolCallConverter.convert_result`](harnesses/harness_tool_call_converter.py), which runs these steps in order. A harness overrides a hook when its trajectory differs.

1. `tool_result_raw_text_of`: the result text in the trajectory.
2. `tool_result_json_of`: the JSON object, asked only for a tool that `ToolCallKnowledge.has_json_result_formats` says has JSON formats. A harness may hold a result without text as a JSON object from the trajectory, e.g. the one image item of a Claude Code `Read` of an image file, or the empty result entry of a Codex `web_search_call`.
3. `is_marked_as_error`: whether the harness marked the result as an error, which only Claude Code reads.
4. `ToolCallKnowledge.harness_result_format`: the declared format the result has, or an `UnmatchedFormat`. It picks the tool's JSON list when there is a JSON object, its list for results marked as errors when it has one and the result is marked, else its text list, then cuts the notices and tries the formats in order. It counts the format or the unmatched result.
5. [`result_from_harness_result_format`](_convert_tool_call_result.py): build `ToolCallResult` from the format that matched, or keep the raw text when none did.
   A format whose result text does not tell the status names a rule of [judgment_rules.py](judgment_rules.py) in place of a status, e.g. Claude Code `Bash` output without an `Exit code` line, and the rule decides it.
6. The converter's own `convert_result` may then add what formats cannot express, e.g. Claude Code's structured result fields, or apply a rule of [judgment_rules.py](judgment_rules.py), e.g. exit code 130 after a Codex Ctrl-C read as killed.

### Outcomes

| Outcome | `tool_output_text` | Status | `harness_result_format` |
|---|---|---|---|
| A format matched | The tool output | The format's status, or the one its judgment rule decides | `MatchedFormat(name)` |
| The tool has formats, none matched | The raw text as is | `unknown`, never `finished` by default | `UnmatchedFormat.UNKNOWN` |
| The tool has no formats | The raw text as is | `unknown` | `UnmatchedFormat.SKIPPED` |

`tool_output_text` is `""` when the tool showed no output, and `None` only when the trajectory holds no text of what it returned, e.g. an image, a PDF or a Cursor blob id.
`handles` name what a later call can poll. A result with handles is usually `running`, but a `finished` Codex `exec` or `wait` result also names the sessions of commands its script left running, read from step results it printed as JSON.
[`harness_result_format`](model.py) names the format, as in the catalog and the audit, for audits and evidence only. Later steps must not branch on it.

## Judgment rules

A judgment rule is a choice that the trajectory does not settle, here a status or exit code that the result text does not state. The thirteen of this step are in [judgment_rules.py](judgment_rules.py), and all are provisional, since they keep the choice of the earlier code.
A declared result format names the rule that decides its status with `judgment_rule="<function name>"`, and a harness converter calls a rule itself when the situation is more than one format.
Each use of a rule is counted in the `judgment_rule_use_counts` of `convert_tool_calls`, and [audit_tool_call_knowledge.py](../../../scripts/audit_tool_call_knowledge.py) writes the sums over the trials to `out/tool_call_knowledge/judgment_rule_uses.csv`.

| Function | Where it is applied | Choice |
|---|---|---|
| `treat_bash_output_without_exit_code_line_as_finished` | Claude Code `Bash` format `bare_output` | Output without an `Exit code` line is a finished command |
| `treat_bash_output_without_exit_code_line_as_exit_code_0` | [claude_code.py](harnesses/claude_code.py) | Such a command that its structured result does not call interrupted or give a meaning for code 1 exited 0 |
| `treat_script_syntax_error_as_not_run` | Codex `exec` format `failed_syntax` | A script that failed with a `SyntaxError` ran nothing |
| `treat_web_search_call_without_content_as_finished` | Codex `web_search_call` format `no_content` | A `web_search_call` result without content is a finished search |
| `treat_failed_file_tool_call_as_not_run` | The failure formats of Claude Code `Read`, Grok Build `read_file` and `search_replace` and Cursor `readToolCall` and `editToolCall` | A file tool call that gives a reason it failed did no work |
| `treat_get_output_without_exit_code_as_running` | Devin `get_output` format `running` | Output without an `Exit code` line is from a command still running |
| `treat_web_fetch_text_as_finished` | Claude Code `WebFetch` format `page` | Page text is a finished fetch |
| `treat_negative_exit_code_as_killed` | Devin `exec` format `killed`, `get_output` format `killed_silent_twice` and [devin.py](harnesses/devin.py) for any other format | A negative exit code, which only Devin writes as -1 for a command it stopped, means the command was killed |
| `treat_written_input_as_running_target` | Devin `write_to_process` format `written` | A process that got input is still running |
| `treat_accepted_stop_request_as_killed` | Muse `work_stop` format `accepted` | Work whose stop request was accepted was killed |
| `treat_failed_task_without_exit_code_as_killed` | Grok Build `get_command_or_subagent_output` formats `failed_signaled` and `failed_signaled_empty` | A failed task without an `Exit Code` line was killed |
| `treat_exit_code_130_after_ctrl_c_as_killed` | [codex.py](harnesses/codex.py) | Exit code 130 after a Codex `write_stdin` that sent Ctrl-C means the process was killed |
| `treat_wait_on_several_tasks_as_their_shared_status` | [grok_build.py](harnesses/grok_build.py) | A Grok Build wait on several tasks gets the status of the state they all share, and unknown when the states differ |
