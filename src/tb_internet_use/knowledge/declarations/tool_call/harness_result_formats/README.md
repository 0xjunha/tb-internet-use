# Harness result formats

How each harness writes the results of its tools is outside knowledge for step 1, e.g. that Claude Code `Bash` writes `Exit code 1` before the output of a failed command. It is declared in Python, one module per harness, since a format is a template or a set of JSON paths, and some formats carry a function that builds the tool output text.

| File | What it holds |
|---|---|
| `<harness>.py`, e.g. [devin.py](devin.py) | The notices, shared template parts and format lists of one harness, ending in `RESULT_FORMATS_BY_TOOL`, which maps each tool name to its `HarnessToolResultDeclaration` |
| [`__init__.py`](__init__.py) | `RESULT_FORMATS_BY_HARNESS`, which maps each harness name to its `RESULT_FORMATS_BY_TOOL` |
| [harness_result_format_declaration.py](../../../harness_result_format_declaration.py) | The types formats are declared in and how a result is matched against them |

Step 1 reaches them only through `ToolCallKnowledge.has_json_result_formats` and `ToolCallKnowledge.harness_result_format` in [tool_call_knowledge.py](../../../tool_call_knowledge.py). Terms, the two kinds of format and how one result is converted are in [Result formats](../../../../tool_call/README.md#result-formats).

## Result format catalog

`harness_result_format_catalog.csv` lists every result format the harnesses declare, one row per (harness, tool, format), in the order the formats are tried.
[build_harness_result_format_catalog.py](../../../../../../scripts/build_harness_result_format_catalog.py) writes it from the code alone, without reading any trajectory. Only `reviewed` and `note` are filled by hand. `reviewed` is kept as long as `template`, `status`, `is_truncated`, `no_tool_output_text` and `handle_kind` stay the same, and `note` is always kept. A test checks that the committed file matches the code.

A row is what the format declares. A converter's `convert_result` may still change `status`, `is_truncated`, `no_tool_output_text` or the handles after the match, e.g. the status and handles of a Grok multi-wait, the status of a Codex Ctrl-C or a negative Devin exit code, `is_truncated` from Claude Code's structured result, and no tool output text for a Codex script that printed only images. The status changes are judgment rules in [judgment_rules.py](../../../../tool_call/judgment_rules.py).

- **`kind`:** `text` or `json`.
- **`template`:** the template of a text format, or the present paths, absent paths and
  condition of a JSON format. A carriage return is written as `\r`, so that editors keep
  it, and a backslash as `\\`.
- **`is_truncated`:** `True` or `False` for every result of the format, empty when the
  format does not tell, `when <marker>` when a marker in the tool output tells, or
  `by <path>` when the value at that path of the result tells.
- **`no_tool_output_text`:** `True` when the trajectory holds no text of what the tool
  returned, e.g. an image, so `tool_output_text` is None.
- **`handle_kind`:** kind of the handles the format gives, empty when it gives none; `by <path>`, e.g.
  `by task.task_type`, means the value at that path of the result names the kind.

## Result format audit

[audit_results.py](../../../../../../scripts/audit_results.py) counts what the declared formats match on the raw trials, with the checks in [harness_result_format_audit.py](../../../harness_result_format_audit.py). A run writes `out/tool_call_knowledge/harness_result_format_audit.csv`, one row per (harness, tool, format) with the same keys as the catalog, and prints a report. Neither is committed, since the counts come from the trajectories.

- **`kind`:** `text` or `json` for a declared format; `special` for a form built by
  converter code, e.g. Claude Code `image`, Codex `no_content`; empty for the
  `unknown_format` and `skipped_format` rows that count a tool's other results.
- **`call_count`, `trial_count`, `example_calls`:** how often it matched and where
  (`trial/trajectory#step.index`), never result text.
- **`roundtrip_mismatches`:** text formats whose matched values, put back into the
  template, do not give the annotated output again.
- **`harness_text_hits`:** results whose `tool_output_text` still holds harness text of
  the tool's templates, i.e. a template part between the tool output and multiline
  placeholders, searched with its placeholders as regexes.
- **`multi_match`:** results that matched this format and another format of the list,
  in either order; expected where a general form follows a specific one.
