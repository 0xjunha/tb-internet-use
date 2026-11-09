# Tool call parsing

Stages 3 to 5 of the [pipeline](../../../README.md#pipeline): read ATIF trajectories and convert every tool call in them to common types.

| Stage | Section | Code |
|---|---|---|
| 3 | [Data model](#data-model) | [model.py](model.py) |
| 4 | [Tool call labeling](#tool-call-labeling) | [catalogs/](catalogs/README.md) |
| 5 | [Conversion](#conversion), [Result formats](#result-formats) | [convert.py](convert.py), [result_formats.py](result_formats.py), [harnesses/](harnesses/) |

## Data model

ATIF keeps each harness's own tool names, and different harnesses have different tool names for the same roles.
For example, a shell call is named `Bash` in Claude Code, `exec_command` in Codex and `run_terminal_command` in Grok Build.
ATIF has an `agent.tool_definitions` field, but none of these trajectories fill it, so analysis needs common types.

```
trajectory.json -> RawToolCall -> ToolCall(raw, action, output)
```

| Type | Content |
|---|---|
| `RawToolCall` | One call in the trajectory and its result, as is |
| `ToolCall.action` | Request: what the call tried to do, in the kinds that matter for internet use |
| `ToolCall.output` | Result: tool output text, status, exit code, handles |

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
| `UnknownAction` | Tool the harness does not have (broken or disabled names), and Codex `exec` until its steps are converted |

## Tool call labeling

[Tool catalog](catalogs/README.md): 1,617,509 calls, 117 tools, 364 rows.

| Step | Method |
|---|---|
| Count tools and arguments | Code: [`build_harness_tool_catalog.py`](../../../scripts/build_harness_tool_catalog.py) |
| Label `action_type`, `action_field` | LLM draft, human review of every row |
| Settle doubtful labels | LLM checks raw trajectories, human decides |

Tools whose `Action` varies by call are labeled [`Deferred`](catalogs/README.md#deferred-tools).

## Conversion

`convert_trial(trial_dir)` in [convert.py](convert.py) runs these steps for every call of one trial.

| Step | Code | Produces |
|---|---|---|
| Read a trajectory, pair calls with results | [`atif_reader.py`](atif_reader.py) | `RawToolCall` |
| Build the action from catalog labels | [`catalog_loader.py`](catalog_loader.py), [`convert.py`](convert.py) | `Action` |
| Match the result against the harness's declared result formats | [`result_formats.py`](result_formats.py), one [`HarnessToolCallConverter`](harnesses/base.py) per harness in [harnesses/](harnesses/) | `ToolCallOutput` |
| Fill what labels cannot express, e.g. handle kinds, terminate, Deferred tools | `HarnessToolCallConverter.refine_action`, `deferred_action` | `Action` |

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

Every format of every tool is in the [result format catalog](catalogs/README.md#result-format-catalog), written from the code by [`build_harness_result_format_catalog.py`](../../../scripts/build_harness_result_format_catalog.py) and reviewed by hand. [`audit_results.py`](../../../scripts/audit_results.py) counts each format on the raw trials into the [result format audit](catalogs/README.md#result-format-audit).

### What a result splits into

```
raw text         = notices + annotated output
annotated output = annotation + tool output
```

| Part | What it is | Where it goes |
|---|---|---|
| Tool output | What the tool itself produced | `ToolCallOutput.tool_output_text` |
| Annotation | What the harness wrote about the call, e.g. an exit code line | Execution status, exit code, handles, output path, truncation |
| Notice | A message the harness may add at the start or end of any result, e.g. Grok's completion notifications | Cut before matching, fills no field. Still in `raw.result` for stage 10 |

A truncation marker, which a harness leaves inside a tool output it cut, stays in the tool output and sets `is_truncated`.

### Two kinds of result format

A result format describes one shape of a tool's annotated output.
A converter declares, per tool, a list of formats ([`HarnessResultFormatList`](result_formats.py)) and the tool's notices.
Syntax and rules are in [result_formats.py](result_formats.py).

| | Text format | JSON format |
|---|---|---|
| Class | [`HarnessTextResultFormat`](result_formats.py) | [`HarnessJsonResultFormat`](result_formats.py) |
| Annotated output | A string | A JSON object |
| Declared as | A template: fixed text plus `{name:type}` placeholders | JSON paths the object must have or lack, and an optional condition on one value |
| Has this format when | The template matches the whole annotated output, first character to last | The paths are present or absent as declared and the condition holds |
| Tool output | The `tool_output` placeholder | The `tool_output` value path |
| Annotation values | The other placeholders | The other value paths |
| Example | Devin `exec` in [devin.py](harnesses/devin.py) | Cursor CLI `shellToolCall` in [cursor_cli.py](harnesses/cursor_cli.py) |

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

[`HarnessToolCallConverter.parse_output`](harnesses/base.py) runs the hooks in this order. A harness overrides a hook when its trajectory differs.

1. `extract_tool_result_raw_text`: the result text in the trajectory.
2. `extract_tool_result_json`: the JSON object, for a tool with JSON formats.
3. `select_formats`: the tool's JSON list when there is a JSON object, else its text list.
4. [`parse_output_with_formats`](result_formats.py): cut the notices, try the formats in order, build `ToolCallOutput` from the first that matches.
5. The converter's own `parse_output` may then add what formats cannot express, e.g. Claude Code's structured result fields.

### Outcomes

| Outcome | `tool_output_text` | Status | `harness_result_format` |
|---|---|---|---|
| A format matched | The tool output | The format's status | `MatchedFormat(name)` |
| The tool has formats, none matched | The raw text as is | `unknown`, never `finished` by default | `UnmatchedFormat.UNKNOWN` |
| The tool has no formats | The raw text as is | `unknown` | `UnmatchedFormat.SKIPPED` |

`tool_output_text` is `""` when the tool showed no output, and `None` only when the trajectory holds no text of what it returned, e.g. an image, a PDF or a Cursor blob id.
[`harness_result_format`](model.py) names the format, as in the catalog and the audit, for audits and evidence only. Later stages must not branch on it.
