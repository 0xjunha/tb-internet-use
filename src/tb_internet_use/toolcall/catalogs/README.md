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

## Deferred tools

`Deferred` means the tool name alone cannot decide the `Action` type, so the converter
decides it per call in a later stage.

| Harness | Tool | Why | Decided by |
|---|---|---|---|
| codex | `exec` | Runs JS that can call several tools, so one call can hold several different `Action` types | The `tools.*` calls in the JS code of the `input` argument |
| codex | `web_search_call` | One tool searches, opens a page or finds text in a page, so the `Action` type varies by call | The `action_type` argument: `search`, `open_page` or `find_in_page` |
| cursor-cli | `mcpToolCall` | Wraps any MCP tool, such as Playwright `browser_navigate`, so the `Action` type depends on the wrapped tool | The `toolName` argument, which names the wrapped tool |
