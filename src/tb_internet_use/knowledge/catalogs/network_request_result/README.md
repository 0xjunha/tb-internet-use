# Program output catalogs

The program output catalogs are outside knowledge for `decide_network_request_results`. They say which lines a program run can print, so that a line in a result is matched only to requests whose run can have printed it, and what an exit code of a program says of its request. They are filled by hand, their `reviewed` column says which rows a person or three agents have reviewed, and `decide_network_request_results` reads them only through `NetworkRequestResultKnowledge` in [network_request_result_knowledge.py](../../network_request_result_knowledge.py). How a program reads its words is in the [program catalog](../expanded_tool_call/README.md) of `expand_tool_calls`, so every program and subcommand here needs a row of `program_behaviors.csv` too. Whether a program such as sudo ends with the exit code of the program it runs is there as well, and not here.

Both files have two kinds of rows, keyed by `program_name`, `subcommand` and `option_name`, and in `program_exit_codes.csv` also by `exit_code`.

- A program row has a blank `option_name` and is one program and subcommand, e.g. `(pip, install)`. It answers only for a run whose `ProgramInvocation.program_name` and `subcommand_words` are those of the row, and a blank `subcommand` is a run without subcommand words.
- An option row has an `option_name` and is one option of the program and subcommand of its row, e.g. `-i` of curl. It needs the program row of the same program and subcommand, and in `program_exit_codes.csv` of the same exit code.

`NetworkRequestResultKnowledge` answers for a run only when the program row and a row of every option of the run are there. Otherwise it answers with the `Unknown…` type of the method and counts the keys without a row, e.g. `(curl, "", --compressed)` for `curl --compressed u`, so that the list of unknown inputs says which option to look up next. A run with words that `expand_tool_calls` could not read is unknown too, counted under its first unread word, e.g. `(curl, "", --foo)` for `curl --foo x u`.

A cell holds a fact, a word that stands for a value, e.g. `none` or `changes_nothing`, or a blank. A blank fact cell is unknown, and `NetworkRequestResultKnowledge` then answers with the `Unknown…` type of the method when the row applies to the run. `changes_nothing` is allowed only in an option row and keeps the cell of the program row.

[`program_output_lines.csv`](program_output_lines.csv) has one row per program run or option, which says which lines of the output line patterns it prints. The answer joins the printing programs of the program row with those of each option row, and a run prints a status code when any of its rows says `yes`.

| Column | Row | Cell | Blank |
|---|---|---|---|
| `program_name` | both | The `program_name` of the row of `program_behaviors.csv`, e.g. `pip` | Fails the load |
| `subcommand` | both | The subcommand words split by one space, e.g. `install` or `pip install` of uv | No subcommand words |
| `option_name` | option | The option as written, e.g. `-i` or `--include` | Makes the row a program row |
| `option_value_part` | option | Texts split by one space, of which the value of the option must hold one for the row to apply, e.g. `%{http_code} %{response_code}` for `-w` of curl. A value without them changes nothing. An option without a value, or a value without them that holds a `$`, e.g. `-w "$FMT"`, makes the answer unknown, since its text is set when it runs | The row applies to every value |
| `printing_programs` | both | `PrintingProgram` values split by one space, e.g. `uv pip`, the names that the output line patterns give to what prints their lines. `none` in a program row for a run that prints no line of a pattern, `changes_nothing` in an option row | Unknown |
| `prints_status_code` | both | `yes` when the run prints a bare status code, e.g. curl with `-w '%{http_code}'`, `no`, or `changes_nothing` in an option row | Unknown |

[`program_exit_codes.csv`](program_exit_codes.csv) has one row per program run or option and exit code. The meaning of an option row that is not `changes_nothing` takes the place of that of the program row, and two such option rows that differ make the answer unknown. Exit 0 of `curl -f` keeps the meaning of the program row, since curl ends with 0 also after an answer 401, 407 or 3xx. A blank meaning in any row of the run, the program row included, makes the answer unknown.

| Column | Row | Cell | Blank |
|---|---|---|---|
| `program_name`, `subcommand`, `option_name` | both | As in `program_output_lines.csv` | As there |
| `exit_code` | both | The exit code as a whole number, e.g. `0` | Fails the load |
| `meaning` | both | A `ProgramExitCodeMeaning` value. `nothing` when the program ends with this code without the network too, e.g. exit 0 of `pip install` with every package already there, `server_answered`, e.g. exit 0 of curl, or `request_succeeded`, e.g. exit 0 of wget. `changes_nothing` in an option row | Unknown |

Both files end with the same three columns.

| Column | Cell | Blank |
|---|---|---|
| `checked_against` | What the cells were checked against, naming the page, its section and the version, e.g. `curl(1) -f, --fail, --fail-with-body and EXIT CODES 22, curl 8.23.1 (curl.se/docs/manpage.html)`. A cell taken over from the old program tables without a check says `not checked, from the old table` | Fails the load |
| `reviewed` | `yes` once a person has reviewed the row, `agents` once three agents each checked the row against a primary source and all found every value right, two of them seeing the values and one filling them without seeing them | Not reviewed yet |
| `note` | Free text, e.g. why a cell is blank or where the row came from | Nothing to note |

A page counts as in the [program catalog](../expanded_tool_call/README.md). Which printing programs a run prints is checked against the output line patterns in [program_output.py](../../declarations/network_request_result/output_line_patterns/program_output.py) and against the program's own documentation for whether the run prints those lines. Each pattern names the printing programs known to print its line, e.g. `HTTP_HEADERS` and `GIT` for `http_status_line`, and some name none, e.g. `connection_failure`, a line that any program can print.

A row that `decide_network_request_results` cannot use raises `ValueError` when the catalogs are loaded, e.g. a row with more or fewer fields than the header, such as a `note` with an unquoted comma, a word that no column allows, `changes_nothing` in a program row, `none` in an option row, an exit code such as `00`, a blank `checked_against` or an option row without its program row. No script writes the CSVs.
