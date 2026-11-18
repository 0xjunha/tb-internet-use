# Program request catalog

The program request catalog is outside knowledge for `extract_network_requests`. It says whether a program fetches, which of its words name what kind of target, where the content it receives goes, and how its options change that. It is filled and reviewed by hand, and `extract_network_requests` reads it only through `NetworkRequestKnowledge` in [network_request_knowledge.py](../../network_request_knowledge.py). How a program reads its words, e.g. which option takes a value, is not here but in the [program catalog](../expanded_tool_call/README.md) of `expand_tool_calls`, so every program and subcommand here needs a row of `program_behaviors.csv` too.

[`program_network_requests.csv`](program_network_requests.csv) has two kinds of rows, keyed by `program_name`, `subcommand`, `option_name` and `option_value`.

- A program row has a blank `option_name` and is one program and subcommand, e.g. `(pip, install)`. It answers only for an invocation whose `ProgramInvocation.program_name` and `subcommand_words` are those of the row, and a blank `subcommand` is an invocation without subcommand words.
- An option row has an `option_name` and is one option of a program, e.g. `-o` of curl. A blank `subcommand` is every subcommand of the program and a blank `option_value` is every value. For an option of a command the door tries the row of the subcommand and the value first, then the blank subcommand with the value, then the subcommand with a blank value, then both blank, e.g. `(curl, "", -o, -)` before `(curl, "", -o, "")`. An option row needs a program row of the program, or of its subcommand when it names one, that fetches.

A cell holds a fact, a word that stands for a value, e.g. `none` or `no_request`, or a blank. A cell that does not fit the kind of row must be blank, e.g. `option_effect` of a program row or the five cells after `fetches` of a row whose `fetches` is `no`. Among the cells that fit, a blank is unknown only in `content_route`, and the door then answers with `UnknownProgramContentRoute`. Any other blank fails the load. A program or option whose fact is not known has no row at all, so it stays an unknown input, e.g. an option without a row gives `UnknownProgramOptionEffect` and its request becomes uncertain.

| Column | Row | Cell | Blank |
|---|---|---|---|
| `program_name` | both | The `program_name` of the row of `program_behaviors.csv`, e.g. `pip` | Fails the load |
| `subcommand` | both | The subcommand words split by one space, e.g. `install` or `pip install` of uv | No subcommand words, or every subcommand for an option row |
| `option_name` | option | The option as written, e.g. `-o` or `--no-index` | Makes the row a program row |
| `option_value` | option | The value the row is for, e.g. `HEAD` for `-X` of curl or `-` for `-o` of curl | Every value |
| `fetches` | program | `yes`, `no`, or `only_what_is_missing` when it fetches only what a build or run lacks, e.g. npx, `lake build` or sbt | Fails the load |
| `target_arguments` | program | Which arguments are targets. `all`, e.g. `pip install`, `first`, e.g. `git clone` or ping, `next_program` for the program it runs, e.g. tsc of `npx tsc`, or `none`, e.g. `apt-get update` | Fails the load |
| `target_kind` | program | A `NetworkRequestTargetKind` value, e.g. `package_name` or `host`, also when no argument is a target | Fails the load |
| `target_notation` | program | A `TargetNotation` value, how a target word names its host, e.g. `url_or_schemeless_url` for curl or `pip_requirement` for pip | Fails the load |
| `target_without_target_arguments` | program | The request when no argument names a target. `no_target` for one without a target, e.g. `apt-get update`, `named_in_file` for one whose targets a file or the project names, e.g. `npm install` or sbt, or `no_request`, e.g. curl alone | Fails the load |
| `content_route` | program | Where the content goes before options and redirects change it. `stdout`, e.g. curl, `own_file` for a file the program writes or an install, e.g. wget or `pip install`, or `no_content`, e.g. ping | Unknown |
| `option_effect` | option | A `ProgramOptionEffect` value, e.g. `sends_no_request` for `--no-index` of pip or `names_host_in_value` for `-i` of pip. `none` says that it changes neither whether a request is sent, nor the targets, the hosts or whether the content goes to stdout. A file that an option makes the program write, e.g. `-o` of curl, is in `written_files` of the expanded tool call and not here | Fails the load |
| `checked_against` | both | What the cells were checked against, naming the page, its section and the version, e.g. `git-clone(1) SYNOPSIS and DESCRIPTION, Git 2.56 (git-scm.com)`. A cell taken over from the old program tables without a check says `not checked, from the old table` | Fails the load |
| `reviewed` | both | `yes` once a person has reviewed the row | Not reviewed yet |
| `note` | both | Free text, e.g. why a cell is blank | Nothing to note |

A page counts as in the [program catalog](../expanded_tool_call/README.md): a page of the Linux implementation or of the program's own documentation, e.g. a Debian bookworm page on manpages.debian.org or pip.pypa.io, named with its site and version, and never a macOS BSD page for a GNU program.

`NetworkRequestKnowledge.may_program_fetch` answers for a program that code runs, whose subcommand nobody read. It says whether any program row of the name fetches and counts under the key `(program_name, "any subcommand", "", "")`, apart from the counts of the other methods.

A row that `extract_network_requests` cannot use raises `ValueError` when the catalog is loaded, e.g. a filled cell that does not fit the kind of row, a word that no column allows, a blank `checked_against` or an option row whose program has no row that fetches. No script writes the CSV.
