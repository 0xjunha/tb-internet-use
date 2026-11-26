# TODO

## Convert tool calls

- **Results that every format accepts.** A few result formats take any text as a plain result, e.g. `bare_output` of Claude Code `Bash`, so an unexpected result there can never become `unknown_format`. Decide whether to mark these formats in their declarations, and whether an audit should report the common first lines inside them.
- **Codex `exec` steps.** One `exec` script has one result for all its steps, and `treat_script_step_output_as_shown_in_call_result` reads that result as showing the output of no step, since the user decided on 2026-11-24 that the script's code decides what it prints. Decide whether to read the output of a step when a script has one step that prints its own result, and how to count a step inside a loop or a condition, which `parse_codex_exec_script` lists once whether it ran or not.
- **`web__run` references.** `web__run` can name a page by a reference to an earlier result, e.g. `turn0view0`, and only URLs reach `WebFetchAction.urls`. Decide whether to resolve such references to URLs.

## Expand tool calls

- **Values of a variable assigned twice in sequence.** `U=a; curl $U; U=b; curl $U` gives the second curl both a and b, though it can only see b. Fixing it needs the branches each assignment runs in, e.g. inside `if` or after `&&`.

## Decide request results

- **Exit codes at the end of background output files.** When a later call reads a Claude Code background output file, its last line can be `[exited with code N]`. Read it as the exit code of the background command.
- **Effects seen in later calls.** A later use of a saved file counts as `FileUseEvidence`, but a later `import requests` that works says nothing about an earlier `pip install requests`. Decide whether such effects count as evidence.
