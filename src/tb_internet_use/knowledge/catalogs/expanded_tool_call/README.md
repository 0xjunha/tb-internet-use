# Program catalog

The program catalog is outside knowledge for `expand_tool_calls`, kept in the three CSVs of this folder. They say how a program reads its words, which words name a file, a text or the next program it runs, and which language a text is in. None of them says anything about the internet. They are filled by hand, their `reviewed` column says which rows a person has reviewed, and `expand_tool_calls` reads them only through `ExpandedToolCallKnowledge` in [expanded_tool_call_knowledge.py](../../expanded_tool_call_knowledge.py).

A cell holds a fact, a word that stands for a value, e.g. `none`, or a blank. The table of each file says, per column, which words it takes and what a blank means. A blank is unknown only where the table says so, and the door then answers with an `Unknown…` type of [model.py](../../../expanded_tool_call/model.py) or `OutputVisibility.UNKNOWN`. In every other fact column a blank fails the load, since the door could not read the words of a command without the cell. A fact that is not known for such a column is no row at all, so the program or option stays an unknown input.

The role columns hold a `ProgramWordRole` value, e.g. `read_file` for the arguments of cat or `program` for those of sudo.

[`program_behaviors.csv`](program_behaviors.csv) has one row per program, or per subcommand of a program, keyed by `program_name` and `subcommand`. The row of a subcommand, e.g. `(uv, run)`, answers when its words come right after the program word, or after the options before them that rows of the program without a subcommand cover, with their values, e.g. `install` of `apt-get -y install curl`. The longest such row wins over the row without a subcommand. A word before the subcommand that those rows do not cover leaves the row without a subcommand to answer, and the word stays unread.

| Column | Cell | Blank |
|---|---|---|
| `program_name` | The name without folder or version, e.g. `pip` for `/usr/bin/pip3`. It becomes `ProgramInvocation.program_name` | Fails the load |
| `subcommand` | The words that pick what the program does, split by one space, e.g. `run` for uv | The row of a call whose words fit no row of a subcommand |
| `argument_role` | The role of each word that is no option, e.g. `read_file` for cat | Unknown |
| `first_argument_role`, `last_argument_role` | The role of the first or last such word, or `same` when it has the role of `argument_role`, e.g. `run_file` for the first word of bash. `option_cluster` says that the first such word holds one-letter options without a dash, e.g. `xzf` of `tar xzf a.tgz`, read through the option rows `-x`, `-z` and `-f`, whose values are the words after it in turn. It also holds when an option with a dash comes before that word, which the page of tar does not say | Unknown |
| `stdin_role` | The role of stdin when no word names a file, or `none` when the program does not read it | Unknown |
| `visibility_of_piped_input` | How much of what comes in through a pipe the program writes to its stdout. `whole` for all of it, e.g. cat, `partial` for a part, e.g. head, `none` when it passes on none of it | Unknown |
| `gives_arguments_at_run_time` | `yes` when the program gives the next program arguments that the words do not show, e.g. xargs, else `no` | Fails the load |
| `skips_assignment_words` | `yes` when `NAME=value` words before the next program belong to the program, e.g. env, else `no` | Fails the load |
| `options_end_at_first_argument` | `yes` when no word after the first argument is an option of the program, e.g. sudo, else `no` | Unknown. A word that starts with `-` after the first argument is then neither an option nor an argument, so it and the words after it stay unread, e.g. `-n` of `echo hello -n`. A command without such a word is read as with `yes` or `no` |
| `takes_one_letter_options_joined` | `yes` when several letters after one `-` are one-letter options, e.g. `-Nnv` of sudo, else `no` | Unknown. A word of several letters after one `-` is then read only through a row of its own, as with `no`, e.g. `-n` of echo but not `-ne` |
| `runs_text_in_calling_shell` | `yes` when the text it runs sees the assignments of the calling shell, e.g. eval, else `no` | Fails the load |
| `exits_with_exit_code_of_next_program` | `yes` when it runs the next program and ends with its exit code, e.g. sudo, `no` when it does not, e.g. a row with no `program` role | Unknown |
| `name_may_end_with_version` | `yes` when the row also answers for the name with a version at its end, e.g. `python3.11` for python, else `no` | Fails the load |
| `default_run_file` | The file the program runs when its words name none, e.g. `Makefile` for make, or `none` when it runs no such file | Unknown. When its words name no file to run, a program whose row gives a word or its stdin the role `run_text` or `run_file` then runs an unknown text, and any other program runs none, e.g. `git status` |

[`program_option_behaviors.csv`](program_option_behaviors.csv) has one row per option, keyed by `program_name`, `subcommand` and `option_name` as written, e.g. `-o`. An option that takes no value needs a row too, since the first option without a row stops the reading of the command. Its program and subcommand must have a row of `program_behaviors.csv`. A row of the subcommand answers before the row without one.

The door answers for a whole word of a command, e.g. `-fsSLoout` or `--output=f`, with the rows of the options it holds, and counts one use per option. When the rows do not cover the word it counts one unknown input under the word as written, e.g. `-rn` of grep when `-n` has no row, or under `--name` for `--name=value`, so a row is added for the option the word misses. A word that starts with `+`, e.g. `+o` of bash, is read like one that starts with `-` only when the program has a row for an option that starts with `+`. Otherwise it is an argument, e.g. `+x` of chmod.

| Column | Cell | Blank |
|---|---|---|
| `program_name` | The `program_name` of the row of `program_behaviors.csv` the option belongs to | Fails the load |
| `subcommand` | The `subcommand` of that row, e.g. `exec` for the options of `npm exec` | The option of every call of the program, unless a row of the call's subcommand names the option |
| `option_name` | The option as written, e.g. `-o`, `--output` or `-exec` | Fails the load |
| `takes_value` | `yes` or `no` | Fails the load |
| `value_role` | The role of the value, or `none` for an option that takes no value | Unknown, only for an option that takes a value |
| `argument_role_with_option` | The role of each word that is no option while the option is there, or `unchanged` | Unknown |
| `first_argument_role_with_option`, `last_argument_role_with_option` | The same for the first or last word, `same` or `unchanged` | Unknown |
| `changed_option_name` | Another option whose value takes a role while this option is there, e.g. `-f` for `-x` of tar, or `none` | Fails the load |
| `changed_option_value_role` | The role that value takes, or `none` with `changed_option_name` `none` | Unknown, only for a row that names an option in `changed_option_name` |
| `gives_arguments_at_run_time` | `yes` or `no`, as in `program_behaviors.csv` | Fails the load |
| `exits_with_exit_code_of_next_program_with_option` | `yes`, `no`, or `unchanged` when the option keeps the cell of the program row | Unknown |
| `next_program_end_words` | The words that end the next program, split by spaces, e.g. `; +`, or `none` | Fails the load |

[`code_runners.csv`](code_runners.csv) has one row per program or file extension that runs text, keyed by `runner_kind` and `runner`. A name without a row is read without its version, e.g. python for `#!/usr/bin/env python3`, when the row of that name in `program_behaviors.csv` says `yes` in `name_may_end_with_version`. A lookup of a name read without its version, in this file or in `program_behaviors.csv`, adds a count under the source `names_read_without_version` beside the use of the row, so a sum over all sources is larger than the number of lookups.

| Column | Cell | Blank |
|---|---|---|
| `runner_kind` | `program_name` or `file_extension` | Fails the load |
| `runner` | A program name, e.g. `python`, or an extension with its dot, e.g. `.py` | Fails the load |
| `ran_text_language` | `shell`, `python` or `javascript` | Fails the load |

All three files end with the same three columns.

| Column | Cell | Blank |
|---|---|---|
| `checked_against` | What each cell was checked against, naming the page, its section and the version of the program, e.g. `sudo(8) EXIT VALUE, sudo 1.9.17p2`. A cell taken over from the old program tables without a check says `not checked, from the old table` | Fails the load |
| `reviewed` | `yes` once a person has reviewed the row | Not reviewed yet |
| `note` | Free text, e.g. why a cell is blank | Nothing to note |

A page counts for a cell only when it is of the program the trials run, which is Linux. A GNU page from Homebrew counts for a GNU program, and a page of the same upstream program counts with its version, e.g. sudo or curl. A macOS BSD page does not count for a GNU program. A page on the web counts the same way, e.g. a page of the Linux man-pages project on man7.org or a Debian bookworm page on manpages.debian.org, named with its site and the version or date it shows. Whether one-letter options join in one word may rest on a POSIX page, e.g. `tee(1p)`, that says the utility follows the Utility Syntax Guidelines, whose Guideline 5 allows the join, when the page of the implementation does not say otherwise. Where the implementation's page says otherwise it wins, e.g. gcc(1) "multiple single-letter options may not be grouped", and where the implementation's page says it does not follow POSIX, e.g. time(1) "does not implement the POSIX requirements" for GNU time, the POSIX page does not count.

A row that `expand_tool_calls` cannot use raises `ValueError` when the catalog is loaded, e.g. a word that no column allows, a blank `checked_against`, an option row whose program has no row, rows of one program name that differ in `name_may_end_with_version`, a `file_extension` runner without its dot or `next_program_end_words` on an option whose arguments do not become the next program. No script writes the three CSVs.
