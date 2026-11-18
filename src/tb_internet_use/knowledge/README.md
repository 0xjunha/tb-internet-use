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
| [catalogs/tool_call/harness_return_code_interpretations.csv](catalogs/tool_call/harness_return_code_interpretations.csv) | `ToolCallKnowledge` | One text that a harness tool writes in place of an exit code | Which exit code does the text stand for? |
| [declarations/tool_call/harness_result_formats/](declarations/tool_call/harness_result_formats/README.md) | `ToolCallKnowledge` | The result formats of one harness tool | Which formats can a result of the tool have, and what does each say about the call? |
| [catalogs/expanded_tool_call/program_behaviors.csv](catalogs/expanded_tool_call/program_behaviors.csv) | `ExpandedToolCallKnowledge` in [expanded_tool_call_knowledge.py](expanded_tool_call_knowledge.py) | One program, or one subcommand of it | How does the program read its words, which of them name a file, text or the next program it runs, and what does it do with its stdin? |
| [catalogs/expanded_tool_call/program_option_behaviors.csv](catalogs/expanded_tool_call/program_option_behaviors.csv) | `ExpandedToolCallKnowledge` | One option of a program | Does the option take a value, what is the value, and how does the option change the roles of the other words? |
| [catalogs/expanded_tool_call/code_runners.csv](catalogs/expanded_tool_call/code_runners.csv) | `ExpandedToolCallKnowledge` | One program or file extension | Which language is the text that the program runs or the file holds? |
| [catalogs/network_request/program_network_requests.csv](catalogs/network_request/program_network_requests.csv) | `NetworkRequestKnowledge` in [network_request_knowledge.py](network_request_knowledge.py) | One program or subcommand, or one option of it | Does the program fetch, which arguments name what kind of target, where does the content go, and how does the option change that? |
| [declarations/network_request_result/output_line_patterns/](declarations/network_request_result/output_line_patterns/) | `NetworkRequestResultKnowledge` in [network_request_result_knowledge.py](network_request_result_knowledge.py) | One pattern of output line, e.g. `pip_already_satisfied` | What does a line in a result mean, e.g. `Could not resolve host: a.org`, and which programs print it? |

The columns of the CSVs are described beside them, those of `tool_call/` in the [harness tool catalog](catalogs/tool_call/README.md) and those of `expanded_tool_call/` in the [program catalog](catalogs/expanded_tool_call/README.md) and those of `network_request/` in the [program request catalog](catalogs/network_request/README.md).

A declared result format is counted like a catalog row. `ToolCallKnowledge.harness_result_format` counts the format a result matched as a use of the row `(harness, tool, format)`, and a result that matched none as an unknown input `(harness, tool, unknown_format)` or `(harness, tool, skipped_format)`, both under the source name `harness_result_formats`.

Output line patterns are declared in Python too, since a table is ordered and the first pattern that matches a line gives its meaning, and patterns share parts such as the regex of a host name. [output_line_pattern_declaration.py](output_line_pattern_declaration.py) holds the types, [program_output.py](declarations/network_request_result/output_line_patterns/program_output.py) the patterns read in program output and [web_tool_result.py](declarations/network_request_result/output_line_patterns/web_tool_result.py) those read in the result of a call made only of web tool actions. `NetworkRequestResultKnowledge.output_line_meaning` counts the pattern that matched a line as a use of the row `(table, pattern)` under the source name `output_line_patterns`. A line that matched none gives `UnknownOutputLineMeaning` and is not counted, since an output line has no name, so a missing pattern cannot be noticed the way a missing catalog row can. Requests whose output was shown but gave no trace are counted by program later, from the output types. `output_line_pattern_reviews.csv` in the same folder is the review record, one hand-filled row per pattern in the order of the tables, and a test fails when its rows and the declared patterns do not pair up in that order.

## Adding a fact

1. Run the audit of the step on the trials, e.g. `nice -n 10 uv run python -I scripts/audit_tool_call_knowledge.py <raw_trials_dir>` for step 1.
2. Read `out/tool_call_knowledge/unknown_inputs.csv` from the top. The inputs that the most trials asked for come first.
3. Add a row for the input to the catalog by hand. A harness tool that touches the task environment gets the `ToolCallAction` type for what it does, e.g. `SearchFilesAction` for a grep tool, and a tool that only handles the harness's own state gets `OtherAction`. `harness_tool_arguments_in_data.csv` in the same folder lists the arguments of the tool and their value types, to choose which fill an action field.
4. Write in `checked_against` what the fact was checked against, e.g. a section of a manual or `8 sampled tool calls in the trajectories (terminal-bench 2026-10-08)`. Leave `reviewed` empty until a person has reviewed the row, then write `yes`. For a declared result format, write both in its row of `harness_result_format_reviews.csv`, and for an output line pattern in its row of `output_line_pattern_reviews.csv`. Add, rename or remove that row when the format or pattern is added, renamed or removed.
5. Run `./scripts/check.sh`. A row that the step cannot use, e.g. an `action_type` that names no class, raises when the catalog is loaded.
6. Run the audit again. The input is gone from `unknown_inputs.csv`, and `row_uses.csv` shows how often the new row was used.
