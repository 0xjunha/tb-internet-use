# Outside knowledge

Facts that no trajectory holds, e.g. that the Codex tool `exec_command` runs a shell command. A person fills and reviews them. A step asks for them only through its door, one class per step, which its entry function takes as an argument.

Every door guarantees three things:

- An answer is a value or an unknown, never a default.
- Each unknown input is counted.
- Each use of a fact is counted.

A door reads a CSV only through `Catalog` in [catalog.py](catalog.py), whose `lookup` records the use or the miss itself. The counts depend on the dataset, so each run writes them under `out/` and no script writes a catalog.

Knowledge that a CSV cannot hold, e.g. a result format with a template and a function that builds the tool output text, is declared in Python under [declarations/](declarations/). A step reaches it through its door too, and imports no module of `knowledge/` when it runs. Since a Python line has no columns for a review, a hand-filled `<what one row is>_reviews.csv` beside the Python files records what each declared fact was checked against and whether a person reviewed it, e.g. [harness_result_format_reviews.csv](declarations/tool_call/harness_result_formats/README.md#review-record).

| File | Door that reads it | One row | Question it answers |
|---|---|---|---|
| [catalogs/tool_call/harness_tools.csv](catalogs/tool_call/harness_tools.csv) | `ToolCallKnowledge` in [tool_call_knowledge.py](tool_call_knowledge.py) | One tool of one harness | Which `ToolCallAction` type is a call of the tool, and does the tool stop something started earlier? |
| [catalogs/tool_call/harness_tool_arguments.csv](catalogs/tool_call/harness_tool_arguments.csv) | `ToolCallKnowledge` | One argument of a harness tool that fills an action field | Which field of the action does the argument fill, and which kind of target do its handles name? |
| [declarations/tool_call/harness_result_formats/](declarations/tool_call/harness_result_formats/README.md) | `ToolCallKnowledge` | The result formats of one harness tool | Which formats can a result of the tool have, and what does each say about the call? |

The columns of both CSVs are described in the [harness tool catalog](catalogs/tool_call/README.md).

A declared result format is counted like a catalog row. `ToolCallKnowledge.harness_result_format` counts the format a result matched as a use of the row `(harness, tool, format)`, and a result that matched none as an unknown input `(harness, tool, unknown_format)` or `(harness, tool, skipped_format)`, both under the source name `harness_result_formats`.

## Adding a fact

1. Run the audit of the step on the trials, e.g. `nice -n 10 uv run python -I scripts/audit_tool_call_knowledge.py <raw_trials_dir>` for step 1.
2. Read `out/tool_call_knowledge/unknown_inputs.csv` from the top. The inputs that the most trials asked for come first.
3. Add a row for the input to the catalog by hand. A harness tool that touches the task environment gets the `ToolCallAction` type for what it does, e.g. `SearchFilesAction` for a grep tool, and a tool that only handles the harness's own state gets `OtherAction`. `harness_tool_arguments_in_data.csv` in the same folder lists the arguments of the tool and their value types, to choose which fill an action field.
4. Write in `checked_against` what the fact was checked against, e.g. a section of a manual or `8 sampled tool calls in the trajectories (terminal-bench 2026-10-08)`. Leave `reviewed` empty until a person has reviewed the row, then write `yes`. For a declared result format, write both in its row of `harness_result_format_reviews.csv`, and add, rename or remove that row when the format is added, renamed or removed.
5. Run `./scripts/check.sh`. A row that the step cannot use, e.g. an `action_type` that names no class, raises when the catalog is loaded.
6. Run the audit again. The input is gone from `unknown_inputs.csv`, and `row_uses.csv` shows how often the new row was used.
