# Program catalog

`program_catalog.csv` labels what a program does when a shell command runs it, one row per program and subcommand.
It is stage 7 of the [pipeline](../../../../../README.md#pipeline).
Stage 8 reads which programs read their file arguments, e.g. `tail fetch.log`, and which run the next program, e.g. tsx in `npx tsx get.ts`.
Stage 9 reads which runs make a request and what that run can show.
A program without a row reads no file and makes no request, so a missing row hides a request until someone adds it.

[build_program_catalog.py](../../../../../scripts/build_program_catalog.py) rewrites only `command_count` and `trial_count`, counted on the raw trials with the same matching that stage 9 uses.
It never changes the other columns, which are labeled by hand, and lists every other program in `out/program_catalog_candidates.csv`, which `.gitignore` keeps out of the repo.

| Column | Values |
|---|---|
| `program` | The name that `normalized_program_name` gives, e.g. `pip` for `pip3` |
| `subcommand` | Words after the program that the row needs, e.g. `pip install` for `uv pip install`. Empty for any run. The longest matching subcommand wins |
| `command_count`, `trial_count` | How many commands and trials of the raw data match the row, written by the script |
| `reads_file_arguments` | `yes` when its output can show the files it names or reads from stdin, e.g. `cat` or `tail`. Only on rows without a subcommand |
| `request_kind` | A `RequestKind` value, or empty when the run makes no request. The six columns after it are filled only with it |
| `printing_programs` | `PrintingProgram` values separated by spaces, i.e. whose output lines the run can print |
| `exit_zero_means` | An `ExitZeroMeans` value before options change it, or empty when not known |
| `fetches_only_to_run_or_build` | `yes` when the run builds or runs something and fetches only what that needs, e.g. `npx`, `lake build` |
| `asked_packages_source` | Where the packages it asks for are named: `none` (e.g. `apt-get update`), `targets` (e.g. `pip install requests`) or `file_or_project` (e.g. `npm ci`) |
| `asks_for_no_content` | `yes` when a successful run brings no content back, e.g. `git push` |
| `prints_response_body` | `yes` when the response goes to stdout before options change it, e.g. `curl` |
| `runs_next_program` | `yes` when the program named after it runs next and can make the request instead, e.g. `npx tsc` or `uv run pip install x` |
| `reviewed` | `yes` once the user has checked the row |
| `note` | Free text |

The first draft was filled by an agent from the rule tables of an earlier prototype, and no row is reviewed yet.
