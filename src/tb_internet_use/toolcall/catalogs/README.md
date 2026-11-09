# Harness tool catalog

`harness_tool_catalog.csv` records all tool names and arguments from different agent
harnesses found in ATIF trajectories, and how often each tool and argument was called.

Each harness tool name is then mapped to one of the `Action` types in [model.py](../model.py),
and its arguments to the fields of that `Action` type. These mappings are labeled and
reviewed manually.

[build_harness_tool_catalog.py](../../../../scripts/build_harness_tool_catalog.py) counts the calls and writes the CSV with
`action_type` and `action_field` left empty for those labels. It refuses to overwrite
an existing file, so it cannot erase them.

- **`action_type`:** `Action` type for the tool, or `Deferred`. Broken tool names are
  `UnknownAction`. Tools that do not matter for internet-use analysis are
  `OtherAction`, with no further breakdown.
- **`action_field`:** Field of that `Action` type for the argument. Empty if unused.

## Result format catalog

`harness_result_format_catalog.csv` lists every result format the converters declare
(see [Result formats](../README.md#result-formats)), one row per (harness, tool, format),
in the order the formats are tried.
[build_harness_result_format_catalog.py](../../../../scripts/build_harness_result_format_catalog.py)
writes it from the code alone, without reading any trajectory. Only `reviewed` is filled
by hand, and it is kept as long as `template`, `status`, `is_truncated`,
`no_tool_output_text` and `handle_kind` stay the same. A test checks that the committed
file matches the code.

- **`kind`:** `text` or `json`.
- **`template`:** the template of a text format, or the present paths, absent paths and
  condition of a JSON format.
- **`is_truncated`:** `True` or `False` for every result of the format, empty when the
  format does not tell, `when <marker>` when a marker in the tool output tells, or
  `by <path>` when the value at that path of the result tells.
- **`no_tool_output_text`:** `True` when the trajectory holds no text of what the tool
  returned, e.g. an image, so `tool_output_text` is None.
- **`handle_kind`:** kind of the handles the format gives; `by <path>`, e.g.
  `by task.task_type`, means the value at that path of the result names the kind.

## Result format audit

`harness_result_format_audit.csv` holds what the last audit found on the raw trials, one
row per (harness, tool, format), with the same keys as the catalog.
[audit_results.py](../../../../scripts/audit_results.py) rewrites it, with the checks in
[result_format_audit.py](../result_format_audit.py). It also prints a report, which is
not committed.

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
- **`multi_match`:** results that also matched a later format of the list; expected
  where a general form follows a specific one.

## Deferred tools

`Deferred` means the tool name alone cannot decide the `Action`, so the converter
decides it per call in a later stage.

| Harness | Tool | Why | Decided by |
|---|---|---|---|
| codex | `exec` | Runs JS that can call several tools, so the steps of its `RunScriptAction` vary by call | The `tools.*` calls in the JS code of the `input` argument |
| codex | `web_search_call` | One tool searches, opens a page or finds text in a page, so the `Action` type varies by call | The `action_type` argument: `search`, `open_page` or `find_in_page` |
| cursor-cli | `mcpToolCall` | Wraps any MCP tool, such as Playwright `browser_navigate`, so the `Action` type depends on the wrapped tool | The `toolName` argument, which names the wrapped tool |
