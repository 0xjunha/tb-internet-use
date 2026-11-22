# Harness result formats

How each harness writes the results of its tools is outside knowledge for `convert_tool_calls`, e.g. that Claude Code `Bash` writes `Exit code 1` before the output of a failed command. It is declared in Python, one module per harness, since a format is a template or a set of JSON paths, and some formats carry a function that builds the tool output text.

| File | What it holds |
|---|---|
| `<harness>.py`, e.g. [devin.py](devin.py) | The notices, shared template parts and format lists of one harness, ending in `RESULT_FORMATS_BY_TOOL`, which maps each tool name to its `HarnessToolResultDeclaration` |
| [`__init__.py`](__init__.py) | `RESULT_FORMATS_BY_HARNESS`, which maps each harness name to its `RESULT_FORMATS_BY_TOOL` |
| [harness_result_format_reviews.csv](harness_result_format_reviews.csv) | The review record, one hand-filled row per declared format |
| [harness_result_format_declaration.py](../harness_result_format_declaration.py) | The types formats are declared in and how a result is matched against them |

`convert_tool_calls` reaches them only through `ToolCallKnowledge.has_json_result_formats` and `ToolCallKnowledge.harness_result_format` in [tool_call_knowledge.py](../../../tool_call_knowledge.py). Terms, the two kinds of format and how one result is converted are in [Result formats](../../../../tool_call/README.md#result-formats).

## Table of declared result formats

[build_harness_result_format_table.py](../../../../../../scripts/build_harness_result_format_table.py) writes `out/tool_call_knowledge/harness_result_formats.csv`, one row per (harness, tool, format). Rows follow the order of `iter_declared_formats` in [harness_result_format_audit.py](../../../../../../scripts/harness_result_format_audit.py): per harness, the lists for results marked as errors, then the text lists, then the JSON lists, each in the order of its tools and its formats in the order they are tried. It reads only the Python declarations and no trajectory. The table is for reading the declarations side by side, and it is not committed, since the Python lines are the source and nothing reads the table back.

A row is what the format declares. A format whose result text does not tell the status names the judgment rule of [judgment_rules.py](../../../../tool_call/judgment_rules.py) that decides it, and its `status` is `by <judgment rule>`, e.g. `by treat_bash_output_without_exit_code_line_as_finished`. A converter's `convert_result` may still change `status`, `is_truncated`, `no_tool_output_text` or the handles after the match, e.g. the status and handles of a Grok Build wait on several tasks, the status of a Codex Ctrl-C, `is_truncated` from Claude Code's structured result, and no tool output text for a Codex script that printed only images. The status changes there are judgment rules too.

- **`kind`:** `text` or `json`.
- **`status`:** the status of every result of the format, or `by <judgment rule>` when a rule of `judgment_rules.py` decides it.
- **`template`:** the template of a text format, or the present paths, absent paths and condition of a JSON format. A carriage return is written as `\r`, so that editors keep it, and a backslash as `\\`.
- **`is_truncated`:** `True` or `False` for every result of the format, empty when the format does not tell, `when <marker>` when a marker in the tool output tells, or `by <path>` when the value at that path of the result tells.
- **`no_tool_output_text`:** `True` when the trajectory holds no text of what the tool returned, e.g. an image, so `tool_output_text` is None.
- **`handle_kind`:** kind of the handles the format gives, empty when it gives none. `by <path>`, e.g. `by task.task_type`, means the value at that path of the result names the kind.

## Review record

`harness_result_format_reviews.csv` records which declared formats a person has checked. It has one row per (harness, tool, format), in the same order as the table under `out/`, since a reviewer reads that table next to this file. No script writes it. A test fails when its rows and the declared formats do not pair up one to one in that order, e.g. after a format is added, removed or renamed, so the row is added, removed or renamed by hand in the same change.

To review a format:

1. Read its row in the table under `out/`, or its line in `<harness>.py`.
2. Check it against tool results of that tool in the trajectories, e.g. results that `audit_results.py` lists as its example calls.
3. Write in `checked_against` what it was checked against, e.g. `8 sampled tool results in the trajectories (terminal-bench 4.1, 2026-11-19)`, and write `yes` in `reviewed`.

A review covers the declaration it saw. When a declared format changes, e.g. its template or its status, clear `reviewed` of its row by hand in the same change, since no script or test notices it.

- **`checked_against`:** what the format was checked against, empty until someone checks it.
- **`reviewed`:** `yes` once a person has reviewed the row, empty until then.
- **`note`:** free text for the next reviewer, e.g. what still looks doubtful.

## Result format audit

[audit_results.py](../../../../../../scripts/audit_results.py) counts what the declared formats match on the raw trials, with the checks in [harness_result_format_audit.py](../../../../../../scripts/harness_result_format_audit.py). A run writes `out/tool_call_knowledge/harness_result_format_audit.csv`, one row per (harness, tool, format) with the same keys as the table of declared result formats, and prints a report. Neither is committed, since the counts come from the trajectories.

- **`kind`:** `text` or `json` for a declared format; empty for the `unknown_format` and `skipped_format` rows that count a tool's other results.
- **`call_count`, `trial_count`, `example_calls`:** how often it matched and where (`trial/trajectory#step.index`), never result text.
- **`roundtrip_mismatches`:** text formats whose matched values, put back into the template, do not give the annotated output again.
- **`harness_text_hits`:** results whose `tool_output_text` still holds harness text of the tool's templates, i.e. a template part between the tool output and multiline placeholders, searched with its placeholders as regexes.
- **`multi_match`:** results that matched this format and another format of the list, in either order; expected where a general format follows a specific one.
