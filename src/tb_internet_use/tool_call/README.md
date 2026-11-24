# Convert tool calls

The step "Convert tool calls" of the [pipeline](../../../README.md#pipeline), whose entry function is `convert_tool_calls`: read ATIF trajectories and convert every tool call in them to common types.

| Section | Code |
|---|---|
| [Data model](#data-model) | [model.py](model.py) |
| [Tool call labeling](#tool-call-labeling) | [knowledge/](../knowledge/README.md) |
| [Conversion](#conversion), [Result formats](#result-formats) | [_convert_tool_calls.py](_convert_tool_calls.py), [_convert_tool_call_action.py](_convert_tool_call_action.py), [_convert_tool_call_result.py](_convert_tool_call_result.py), [harnesses/](harnesses/), [judgment_rules.py](judgment_rules.py) |
| [Shell texts](#shell-texts) | [_convert_parsed_shell_texts.py](_convert_parsed_shell_texts.py), [parse_shell_text.py](parse_shell_text.py) |

## Data model

ATIF keeps each harness's own tool names, and different harnesses have different tool names for the same roles.
For example, a shell call is named `Bash` in Claude Code, `exec_command` in Codex and `run_terminal_command` in Grok Build.
ATIF has an `agent.tool_definitions` field, but none of these trajectories fill it, so analysis needs common types.

```
trajectory.json -> HarnessToolCall -> ToolCall(harness_tool_call, action, result)
```

| Type | Content |
|---|---|
| `HarnessToolCall` | One call in the trajectory and its result, as is, or a message in which the harness reports the end of earlier work, e.g. an Antigravity CLI `SYSTEM_MESSAGE` |
| `ToolCall.action` | Request: what the call tried to do, with one type for each kind of act on the task environment |
| `ToolCall.result` | Result: tool output text, status, exit code, HTTP status, handles |

Defined in [model.py](model.py).

A tool that touches the task environment gets the type for what it does, the same in every harness. A tool that only handles the harness's own state is `OtherAction`. A type has a field only where a later step reads it, and every argument stays in `HarnessToolCall.args`.

| `ToolCallAction` | What the tool does | e.g. |
|---|---|---|
| `RunCommandAction` | Runs a string in a shell. `parsed_shell_text` holds that string split into commands | Claude Code `Bash`, Codex `exec_command` |
| `RunToolScriptAction` | Runs code that calls harness tools, with one step per tool call found in the code | Codex `exec` |
| `WriteFileAction` | Writes a whole file | Claude Code `Write` |
| `EditFileAction` | Replaces text in a file | Grok Build `search_replace` |
| `DeleteFileAction` | Deletes a file | Cursor CLI `deleteToolCall`, a `Delete File` of a Codex patch |
| `ChangeFilesAction` | Adds, changes and deletes files in one go, with one `WriteFileAction`, `EditFileAction` or `DeleteFileAction` per file change | Copilot CLI `apply_patch` |
| `ReadFileAction` | Reads a file, an image too | Devin `read`, Codex `view_image` |
| `SearchFilesAction` | Searches the content of files | Grok Build `grep`, Muse Code `search` |
| `ListFilesAction` | Finds files by name or lists a folder | Cursor CLI `globToolCall`, Grok Build `list_dir` |
| `WebSearchAction`, `WebFetchAction`, `WebFindAction` | Searches the web, opens a page, finds text in a page | Claude Code `WebSearch`, `WebFetch` |
| `StartSubagentAction` | Starts a subagent, whose own calls may or may not be in the trajectory | Claude Code `Agent`, Devin `run_subagent` |
| `PollAction` | Reads from, writes to or stops a command, script or subagent started earlier | Codex `write_stdin`, Claude Code `TaskStop`, `SendMessage`, an Antigravity CLI `SYSTEM_MESSAGE`, Claude Code `task-notification` or Grok Build `system-reminder` that reports the end of a task |
| `OtherAction` | Only handles the harness's own state, e.g. a plan, a to-do list, a wait or a question to the user | Codex `update_plan`, Devin `todo_write` |
| `UnknownAction` | A tool without a row in the catalog, e.g. a broken or disabled name, or a call that could not be converted | |

### Shell texts

[`parse_shell_text`](parse_shell_text.py) is a reading function: it splits a shell text such as `cd /app && curl -s u > log` into its simple commands by bash grammar alone, without outside knowledge.
Text that a command runs, e.g. `curl u` in `bash -c 'curl u'`, stays one word of that command, since knowing that `bash -c` runs it is knowledge about programs.

| Type | Content |
|---|---|
| `ParsedShellText` | The commands of one text and its variable assignments, e.g. `U=a.org` in `U=a.org; curl $U` |
| `UnreadableShellText` | A text with a syntax error that gives no command at all, e.g. `)))` |
| `ShellCommand` | One simple command: its words, when it runs (`runs_if`, loop, function or case body), where its stdin comes from and its stdout and stderr go, and whether a syntax error, a brace list, joined lines or a statement that tree-sitter-bash misreads and the reading does not repair (a `time` before a reserved word, `((`, an assignment or words beside a subshell, e.g. `time { a; }`, or a statement that is no simple command with words after its redirect target, e.g. `{ a; } > f b`) may have made these wrong |

[`convert_parsed_shell_texts`](_convert_parsed_shell_texts.py) calls `parse_shell_text` on each command string of the action that `convert_tool_call_action` builds and puts the result in `RunCommandAction.parsed_shell_text`, which stays None when the trajectory has no command string.
A Codex `exec` script can run several command strings, one per `RunCommandAction` step, and the command ids go on across its steps, e.g. 0 and 1 for `a; b` in the first step and 2 for `c` in the next, so that they are unique within the call.
[`audit_parsed_shell_texts.py`](../../../scripts/audit_parsed_shell_texts.py) checks on raw trials that every parsed shell text holds together, e.g. that the ids of a call go 0, 1, 2 and that a pipe reader is a command of the same shell text, and counts the shell texts, commands and `UnreadableShellText`s of each harness under `out/parsed_shell_texts/`.

### Messages that the harness writes

A harness sends a long command to the background, and its result then only names the task, e.g. Antigravity CLI `Tool is running as a background task with task id: c1/task-23` Claude Code `Command running in background with ID: b1` or Grok Build `<task-id>call-...</task-id>`. When the task ends, the harness writes the end to the agent in a step of its own, outside the results of calls, and the agent may never poll the task.
`parse_trajectory` reads each such message as a `HarnessToolCall` after the calls of its step, with `is_harness_message` true, no `tool_call_id`, no arguments and the message as the `content` of its result. Its tool name is the name the harness gives the message, and its result formats are declared like those of a tool. The converter makes it a `PollAction` of the task it names, so that `expand_tool_calls` links it to the call that started the task as it links a poll.

| Harness | Tool name | Message | Example |
|---|---|---|---|
| Antigravity CLI | `SYSTEM_MESSAGE` | A step with `source` `system` and `extra.antigravity_type` `SYSTEM_MESSAGE`. Steps of the type `ERROR_MESSAGE`, which report errors of the model's responses, are not read | `Task id "c1/task-23" finished with result:` followed by the exit code and the output. Only a message whose `sender` is the task id it names is an end, since the prompt of a `schedule` timer comes from the timer's task and holds text the agent wrote |
| Claude Code | `task-notification` | A `user` step that starts with `<task-notification>`, whole, since it holds one block, whose `<event>` can hold any text a command printed. Or each block of a `user` step that starts with `[SYSTEM NOTIFICATION - NOT USER INPUT]`, split only where a line that closes a block, an empty line and a line that opens one meet, so one step can give several. A block that a summary of the conversation quotes is not read | `<status>completed</status>` and `Background command "..." completed (exit code 0)`, with the output file but no output, or a `Monitor` event with the lines its command printed |
| Grok Build | `system-reminder` | A `user` step that starts with `<system-reminder>`, whole, since it holds one block. Grok Build adds such blocks to the results of calls too, where the result formats cut them as notices and they are not read | `Background task "call-..." completed (exit code: 0).` with the command but no output, or a reminder of something else, e.g. the workflows it offers |

Audits and judgment rule counts read `is_harness_message` to keep messages apart from the calls of the agent, e.g. the unknown input of an unmatched message ends with `is_harness_message`, and `expand_tool_calls` never asks a judgment rule whether a message ran.
The first `user` step of an agent is never read as such a message, since it is the task or the prompt that the parent agent wrote for a subagent, e.g. the first step of a Claude Code subagent that the main trajectory keeps with `extra.is_sidechain` true.
A message in no declared format is an `UnknownAction` with an unknown status, e.g. the prompt of a timer that the agent set with Antigravity CLI `schedule`, the end of a Claude Code subagent, whose `Agent` call names no task, or a Grok Build reminder that the local date changed.

## Tool call labeling

What each harness tool does is outside knowledge, which no trajectory holds. It is kept in the [harness tool catalog](../knowledge/catalogs/tool_call/README.md), hand-filled CSVs under [knowledge/](../knowledge/README.md): one row per harness tool, one row per argument that fills an action field, and one row per text that a tool writes in place of an exit code, e.g. `No matches found` in a Claude Code `Bash` result.

| Step | Method |
|---|---|
| List the tools and arguments in the data | Code: [`audit_tool_call_knowledge.py`](../../../scripts/audit_tool_call_knowledge.py), which writes under `out/` and never into the catalog |
| Label `action_type`, `action_field` | LLM draft, then a review by a person or by three agents, which the `reviewed` column records per row as `yes` or `agents` |
| Settle doubtful labels | LLM checks raw trajectories, human decides |

Tools whose `ToolCallAction` varies by call are labeled [`Deferred`](../knowledge/catalogs/tool_call/README.md#deferred-tools).

## Conversion

`read_trajectory(trial_dir)` in [pipeline.py](../pipeline.py) opens the trajectory file of one trial, and `convert_tool_calls(harness_tool_calls, knowledge=..., judgment_rule_use_counts=...)` in [_convert_tool_calls.py](_convert_tool_calls.py) converts every call that was read.
`knowledge` is a `ToolCallKnowledge`, the only way from this step to the harness tool catalog and the declared result formats. It counts every use of a catalog row or a declared result format and every input without one, so a run can list the rows it used, the tools without a row and the results without a format.

| Step | Code | Produces |
|---|---|---|
| Read the text of a trajectory file, pair calls with results, and read each message that the harness writes outside the results of calls as a call | [`parse_trajectory.py`](parse_trajectory.py) | `HarnessToolCall`, or `UnreadableTrajectory` of [`trial/model.py`](../trial/model.py) when the text is not JSON. For a missing file, `read_trajectory` in [pipeline.py](../pipeline.py) gives the `UnreadableTrajectory` itself |
| Match the result against the harness's declared result formats | [`_convert_tool_call_result.py`](_convert_tool_call_result.py), one [`HarnessToolCallConverter`](harnesses/harness_tool_call_converter.py) per harness in [harnesses/](harnesses/), with the formats from [`tool_call_knowledge.py`](../knowledge/tool_call_knowledge.py) | `ToolCallResult` |
| Build the action from the label of the tool and the arguments, with the result at hand | [`_convert_tool_call_action.py`](_convert_tool_call_action.py), with the label from [`tool_call_knowledge.py`](../knowledge/tool_call_knowledge.py) | `ToolCallAction`, `UnknownAction` for a tool without a row or for a call whose two arguments give a field of one value different values |
| Fill what the action type and argument fields of a label cannot express, e.g. the handles a result names, the terminate of a stop tool, Deferred tools | `HarnessToolCallConverter.refine_action`, `action_of_deferred_tool` | `ToolCallAction` |
| Split each command string of the action into commands | [`_convert_parsed_shell_texts.py`](_convert_parsed_shell_texts.py), which calls the reading function [`parse_shell_text`](parse_shell_text.py) | `RunCommandAction.parsed_shell_text`: `ParsedShellText`, or `UnreadableShellText` for a text with a syntax error and no command |

## Result formats

Each harness writes a tool result in its own words, and each tool has several result formats, e.g. for a finished, running or refused call.
The table shows only one situation, a shell command that exits with code 0 and prints `hello`, with made-up values.

| Harness | Tool | Format | Result in the trajectory |
|---|---|---|---|
| Antigravity CLI | `run_command` | `exited` | `Created At: 2026-11-13T02:21:04Z`<br>`Completed At: 2026-11-13T02:21:04Z`<br>`Command exited with code 0.`<br><br>`Command output:`<br>`hello` |
| Claude Code | `Bash` | `bare_output` | `hello`, with no exit code line |
| Codex | `exec_command` | `exited` | `Chunk ID: a1b2c3`<br>`Wall time: 0.0512 seconds`<br>`Process exited with code 0`<br>`Original token count: 1`<br>`Output:`<br>`hello` |
| Copilot CLI | `bash` | `exited` | `hello`<br>`<shellId: 3 completed with exit code 0>`<br>`{"detailedContent": "hello\n<shellId: 3 completed with exit code 0>", "structuredContent": {"shellId": "3"}}` |
| Cursor CLI | `shellToolCall` | `exited` | `{"success": {"exitCode": 0, "interleavedOutput": "hello"}}` |
| Devin | `exec` | `exited` | `Output from command in shell 3:`<br>`hello`<br>`Exit code: 0` |
| Grok Build | `run_terminal_command` | `exited` | `exit: 0`<br>`hello` |
| mini-swe-agent | `bash` | `exited` | `{"output": "hello", "returncode": 0}` |
| Muse Code | `bash` | `exited` | `{"terminal_status": "completed", "exit_code": 0, "output": "hello", "truncated": false}` |

The formats are outside knowledge, declared per harness in [knowledge/declarations/tool_call/harness_result_formats/](../knowledge/declarations/tool_call/harness_result_formats/README.md). [`build_harness_result_format_table.py`](../../../scripts/build_harness_result_format_table.py) writes every format of every tool to a [table under `out/`](../knowledge/declarations/tool_call/harness_result_formats/README.md#table-of-declared-result-formats) for reading. A person records which formats were checked in the [review record](../knowledge/declarations/tool_call/harness_result_formats/README.md#review-record), a hand-filled CSV beside the declarations. [`audit_results.py`](../../../scripts/audit_results.py) counts each format on the raw trials into the [result format audit](../knowledge/declarations/tool_call/harness_result_formats/README.md#result-format-audit).

### What a result splits into

```
raw text         = notices + annotated output
annotated output = annotation + tool output
```

| Part | What it is | Where it goes |
|---|---|---|
| Tool output | What the tool itself produced | `ToolCallResult.tool_output_text` |
| Annotation | What the harness wrote about the call, e.g. an exit code line | Execution status, exit code, HTTP status, handles, output path, truncation |
| Notice | A message the harness may add at the start or end of any result, e.g. Grok Build's completion notifications or the `Created At` lines of Antigravity CLI | Cut before matching, fills no field. Still in `harness_tool_call.result` for later steps |

A truncation marker, which a harness leaves inside a tool output it cut, stays in the tool output and sets `is_truncated`.

### Two kinds of result format

A result format describes one shape of a tool's annotated output.
A harness declares, per tool, up to three lists of formats ([`HarnessResultFormatList`](../knowledge/declarations/tool_call/harness_result_format_declaration.py)) with the tool's notices, in a `HarnessToolResultDeclaration`: one for text results, one for JSON results, and one for text results that the harness marked as an error.
Syntax and rules are in [harness_result_format_declaration.py](../knowledge/declarations/tool_call/harness_result_format_declaration.py).

| | Text format | JSON format |
|---|---|---|
| Class | [`HarnessTextResultFormat`](../knowledge/declarations/tool_call/harness_result_format_declaration.py) | [`HarnessJsonResultFormat`](../knowledge/declarations/tool_call/harness_result_format_declaration.py) |
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

### How one result is converted

[`convert_tool_call_result`](_convert_tool_call_result.py) hands a call with a result to [`HarnessToolCallConverter.convert_result`](harnesses/harness_tool_call_converter.py), which runs these steps in order. A harness overrides a hook when its trajectory differs.

1. `tool_result_raw_text_of`: the result text in the trajectory, e.g. without the JSON line that ends every Copilot CLI result.
2. `tool_result_json_of`: the JSON object, asked only for a tool that `ToolCallKnowledge.has_json_result_formats` says has JSON formats. A harness may hold a result without text as a JSON object from the trajectory, e.g. the one image item of a Claude Code `Read` of an image file, or the empty result entry of a Codex `web_search_call`.
3. `is_marked_as_error`: whether the harness marked the result as an error, which only Claude Code and Copilot CLI read.
4. `ToolCallKnowledge.harness_result_format`: the declared format the result has, or an `UnmatchedFormat`. It picks the tool's JSON list when there is a JSON object, its list for results marked as errors when it has one and the result is marked, else its text list, then cuts the notices and tries the formats in order. It counts the format or the unmatched result.
5. [`result_from_matched_or_unmatched_format`](_convert_tool_call_result.py): build `ToolCallResult` from the format that matched, or keep the raw text when none did.
   A format whose result text does not tell the status names a rule of [judgment_rules.py](judgment_rules.py) in place of a status, e.g. Claude Code `Bash` output without an `Exit code` line, and the rule decides it.
6. The converter's own `convert_result` may then add what formats cannot express, e.g. Claude Code's structured result fields, or apply a rule of [judgment_rules.py](judgment_rules.py), e.g. exit code 130 after a Codex Ctrl-C read as killed. Claude Code `Bash` asks `ToolCallKnowledge.exit_code_of_harness_return_code_interpretation` which exit code a `returnCodeInterpretation` such as `No matches found` stands for, and a text without a row leaves the exit code unknown.

### Outcomes

| Outcome | `tool_output_text` | Status | `harness_result_format` |
|---|---|---|---|
| A format matched | The tool output | The format's status, or the one its judgment rule decides | `MatchedFormat(name)` |
| The tool has formats, none matched | The raw text as is | `unknown`, never `finished` by default | `UnmatchedFormat.UNKNOWN` |
| The tool has no formats | The raw text as is | `unknown` | `UnmatchedFormat.SKIPPED` |

`tool_output_text` is `""` when the tool showed no output, and `None` only when the trajectory holds no text of what it returned, e.g. an image, a PDF, a Cursor CLI blob id, or a message that the harness wrote about the end of a task without its output, e.g. a Claude Code `task-notification` that says `completed (exit code 0)`.
`handles` name what a later call can poll. A result can name them whatever its status, e.g. a `finished` Devin `exec` result names the shell the command ran in, and a `finished` Codex `exec` or `wait` result names the sessions of commands its script left running, read from step results it printed as JSON.
[`harness_result_format`](model.py) names the format, as in the table of declared result formats and the audit, for audits and evidence only. Later steps must not branch on it.

## Judgment rules

A judgment rule is a choice that the trajectory does not settle, here a status or exit code that the result text does not state, or how far to repair a shell text that tree-sitter-bash misreads. The nineteen of this step are in [judgment_rules.py](judgment_rules.py), and all are provisional, since they keep the choice of the earlier code or, where it had none, take the choice that claims least.
A declared result format names the rule that decides its status with `judgment_rule="<function name>"`, and a harness converter calls a rule itself when the situation is more than one format. `parse_shell_text` calls the rule about joined lines itself.
Each use of a rule is counted in the `judgment_rule_use_counts` of `convert_tool_calls`, and [audit_tool_call_knowledge.py](../../../scripts/audit_tool_call_knowledge.py) writes the sums over the trials to `out/tool_call_knowledge/judgment_rule_uses.csv`.

| Function | Where it is applied | Choice |
|---|---|---|
| `treat_bash_output_without_exit_code_line_as_finished` | Claude Code `Bash` formats `bare_output`, `persisted_output` and `persisted_output_partial` | Output without an `Exit code` line is a finished command |
| `treat_bash_output_without_exit_code_line_as_exit_code_0` | [claude_code.py](harnesses/claude_code.py) | Such a command that its structured result does not call interrupted or give a `returnCodeInterpretation` exited 0 |
| `treat_script_syntax_error_as_not_run` | Codex `exec` format `failed_syntax` | A script that failed with a `SyntaxError` ran nothing |
| `treat_web_search_call_without_content_as_finished` | Codex `web_search_call` format `no_content` | A `web_search_call` result without content is a finished search |
| `treat_failed_file_tool_call_as_not_run` | The failure formats of Claude Code `Read`, Grok Build `read_file` and `search_replace`, Cursor CLI `readToolCall` and `editToolCall` and Copilot CLI `view`, `create` and `edit` | A file tool call that gives a reason it failed did no work |
| `treat_get_output_without_exit_code_as_running` | Devin `get_output` formats `running` and `running_incremental` | Output without an `Exit code` line is from a command still running |
| `treat_web_fetch_text_as_finished` | Claude Code `WebFetch` and Muse Code `web_fetch` format `page` | Page text is a finished fetch |
| `treat_negative_exit_code_as_killed` | Devin `exec` format `killed` and `get_output` format `killed_silent_twice` | A negative exit code, which only Devin writes as -1 for a command it stopped, means the command was killed |
| `treat_written_input_as_running_target` | Devin `write_to_process` format `written`, Antigravity CLI `manage_task` format `input_sent` | A process that got input is still running |
| `treat_idle_subagent_as_unknown_status` | Copilot CLI `read_agent` format `idle` | A subagent that is idle and waits for a message has an unknown status, since a message can set it to work again |
| `treat_accepted_stop_request_as_killed` | Muse Code `work_stop` format `accepted` | Work whose stop request was accepted was killed |
| `treat_failed_task_without_exit_code_as_killed` | Grok Build `get_command_or_subagent_output` formats `failed_signaled` and `failed_signaled_empty` | A failed task without an `Exit Code` line was killed |
| `treat_exit_code_130_after_ctrl_c_as_killed` | [codex.py](harnesses/codex.py) | Exit code 130 after a Codex `write_stdin` that sent Ctrl-C means the process was killed |
| `treat_wait_on_several_tasks_as_their_shared_status` | [grok_build.py](harnesses/grok_build.py) | A Grok Build wait on several tasks gets the status of the state they all share, and unknown when the states differ |
| `treat_tool_failure_message_as_not_run` | Claude Code `tool_use_error`, Muse Code `rejected`, Codex `exec_command` formats `rejected` and `rejected_command`, `write_stdin` format `rejected_stdin` and `wait` format `rejected_arguments`, Grok Build `rejected` and `rejected_arguments`, Devin `rejected` of `exec`, `get_output`, `kill_shell`, `read`, `write`, `edit` and `webfetch`, Copilot CLI `invalid_delay` of `read_bash` and `invalid_input` of `create`, `edit` and `read_agent`, Antigravity CLI `failed` of `run_command`, `manage_task`, `read_file`, `write_file`, `edit_file` and `search_web` and `manage_task` format `rejected_arguments` | A call whose result says only that it failed did no work |
| `treat_shell_id_with_exit_code_as_running` | Cursor CLI `shellToolCall` formats `background` and `background_requested` | A shell result with a shell id is a command still running, and its exit code is not read |
| `treat_stop_request_for_ended_work_as_finished` | Muse Code `work_stop` format `already_ended` | Work that had already ended when asked to stop finished |
| `treat_cut_off_web_search_as_finished` | Claude Code `WebSearch` format `cut_off` | A search cut off before any result is a finished search |
| `treat_lines_joined_after_three_repairs_as_left_joined` | [parse_shell_text.py](parse_shell_text.py), for a shell text whose lines tree-sitter-bash still joins after three repairs, e.g. `d` after `a \| b \| c` read as more words of `c` | Leave the lines joined and mark every command of the text with `structure_may_be_wrong` |
