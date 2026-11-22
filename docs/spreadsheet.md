# Spreadsheet

`scripts/build_spreadsheet.py` builds a spreadsheet for Google Sheets from the row files of a run of `run_pipeline.py`, for a reader who decides whether a benchmark turns the internet off and what to give agents instead. `scripts/publish_spreadsheet.py` uploads it to Google Sheets under one link across runs.

The spreadsheet holds rows with targets and host names from trajectories, so it stays under `out/` with the rows and never goes into the repository.

## Building

```bash
nice -n 10 uv run python -I scripts/build_spreadsheet.py <run_dir>
```

It writes `internet_use.xlsx` under `<run_dir>/spreadsheet/` (or `--out-dir`), with `formula_check.csv`, which holds each formula cell and chart with the value computed from the file and that of its Python copy.

Each tab of results opens with its title and a sentence that says what its table holds. `Web tools` has a second sentence under it, which says that its requests are the ones seen in the trajectories and what each sender means for a network that is turned off. A table shows one number per fact, the lower bound. The upper bound shows only in the key numbers of `Overview`, in the column `Request, upper bound` of `Tasks`, in the lines of sender `unknown` of `Web tools` and in `Bounds`, which splits the difference by cause.

| Tab | What it holds |
|---|---|
| `Overview` | Key numbers, each with its lower and upper bound: the trials with a request from the task environment, those that received what a request asked for, those with a request other than a package install or a connectivity check, and those with a web tool request sent from outside. Under the first stands one number in a cell over both columns, the share of the lower-bound trials whose requests all go to `pypi`, `apt` or `npm`, which mirrors of these registries would serve. Python counts it over the lines of `Registries and hosts`, by what the commands name, so a registry set in a configuration file is not seen, and a trial that only checked the connection counts among them. Then three charts: the tasks by their share of trials with a request, the trials by registry or kind of host, and the solved tasks by the share of their passed trials without a request. Then a table that Python counts, the ten tasks with the largest share of trials with a request other than a package install or a connectivity check, the trials of the key number of that name, with the hosts that most of those trials asked. The upper bound of web tools also counts sender `unknown` and unreadable trajectories |
| `Tasks` | For each task, the share of trials with a request from the task environment, by category, with a bar of both bounds under the header `Request bounds`, and whether it was solved without a request: `yes (≥50%)` when at least half of the passed trials show no request, `yes (<50%)` when at least one does and fewer than half, so that the answer rests on few trials, `maybe` when every passed trial shows a request but some only in the upper bound, which may have sent nothing, `no` when every passed trial is in the lower bound, and `never solved` |
| `Requested items` | What the trials of each task asked for, e.g. the package `orjson` of `orjson==3.10.12` or a host name. A package request to a URL of a registry shows its host name, e.g. `pypi.org` of `https://pypi.org/pypi/x/json`, unless the URL is a wheel file of pip, which shows the name of the wheel. A package request whose command names no package shows a text in parentheses that says where the names are, after the named items of its task: `(package index update)`, e.g. `apt-get update`, `(package registry ping)`, e.g. `npm ping`, `(packages from dependency file)`, e.g. `npm ci`, `pip install -r reqs.txt` or `playwright install-deps`, and `(package name in variable)`, e.g. `pip install $PKG`. A request to install a file on the machine has no line, e.g. `pip install ./dist/x.whl`. Python counts its lines, and the checks hold only the trials of each category against `Chart data`, so a line that is too low would pass |
| `Registries and hosts` | The package registries and hosts requested from the task environment, without connectivity checks. One table of host services, then one table per host service with a line per registry or host name, the ten of most tasks and one line for the rest, each with its tasks, its trials and a bar of trials. A host of a package registry counts in the line of its registry, e.g. `pypi.org` in `pypi`. Python counts its lines |
| `Web tools` | Requests of web tools that leave from the harness or the model provider, which turning off the network of the task environment does not block |
| `Bounds` | Why the upper bound is higher, each trial by the first cause that matches, and how far the requests of the lower bound got, each trial by the furthest of its requests, with a bar of trials in each line |
| `Method & checks` | What the numbers cannot say, the terms, whether every formula gives the value that Python counted, and what the numbers rest on. Its lines on harnesses whose trajectories lack calls name only those with a trial in the run, each with what it lacks, from `MISSING_CALLS_BY_HARNESS` of `spreadsheet_method_and_checks_tab.py` |
| `Chart data` | The tables that the charts of `Overview` draw, and the trials of each category, which the checks hold other tabs against |

`Tasks` and `Requested items` name a task by `task_name` without the part up to its first `/`, e.g. `atrx-vep-crispr` for `terminal-bench/atrx-vep-crispr`, and only a run of several benchmark versions puts its version in a first column `benchmark_version`, since with one version the column would repeat the same text on every line. The formulas, frozen panes, filters, color scales and bars of the two tabs, and the formulas of other tabs over them, take their columns from whether `benchmark_version` is shown.

The row tabs `trial_rows`, `trial_category_measure_rows` and `network_request_rows` sit between the tabs of results and `Method & checks`. Each names the task of a row by `benchmark_version` and `task_name`, the name without the part up to its first `/`, as `Tasks` shows it, so that a task is found by the same text in every tab. Only a run of several benchmark versions adds a column `task_key` to each, e.g. `4-1-0 atrx-vep-crispr`, since a count of tasks needs one column that tells them apart and a criterion cannot hold a version alone, which Google Sheets would read as a date. `trial_rows` ends with `unreadable_trajectory_reason`, which few trials have. `network_request_rows` leaves out the columns that hold one value in every row it holds, e.g. `is_internet_use`, those that another column gives, e.g. `result_view`, and those that no number of the file reads and that need the pipeline to be understood, e.g. `request_index`. The file `network_request_rows.csv` of the run folder holds them all. A column of a row tab is as wide as its name and 95 of 100 of its values need. The last holds only the request rows in the lower bound and those of web tools, since all of them, about 250,000 rows, would fill most of the 10 million cells that one Google Sheets file allows.

## How the numbers are checked

Every number in front is a formula over the row tabs, except those in grey italics, which need rows the file does not hold or a count that no formula can make, e.g. the causes of `Bounds`. The counts of `Requested items` are plain numbers, since about four thousand lines of `COUNTUNIQUEIFS` would make Google Sheets slow. `Method & checks` holds them against the formulas of `Chart data`, where the trials of each category must be equal, so a single line that is too low passes. The counts of `Registries and hosts` are plain numbers too, since a request row names several hosts in one cell and a host finds its registry in the host catalog. `Method & checks` holds the trials of all its lines together against a formula over `network_request_rows`. The total of the causes in `Bounds` sums the cause cells, so the check of the total against the upper bound holds each cause. A note of `Overview` that holds a number is a formula that joins the count, written with `TEXT(count,"#,##0")`, to its text, e.g. `of 66 tasks`. The lower column of the line on packages of `Overview` is a formula that subtracts a number Python counted, the trials of the lower bound that may have a request of another category, since a formula would need the bound of each trial over all categories beside each row of `trial_category_measure_rows`.

Each tab of formulas has a hidden copy `<tab> (Python)` with the values that `spreadsheet_python_counts.py` counted from the full CSV files. `Method & checks` counts the cells where a formula differs from its copy, so the check runs again wherever the file is opened.

Before that, `check_spreadsheet_formulas.py` computes the formulas of the written file and reads the ranges of its charts. The build exits with 1 when a formula differs from its copy, a check does not hold or a chart does not draw numbers from every row of its labels. The formulas use `COUNTUNIQUEIFS`, `MAXIFS`, `IF`, `TEXT` and `SPARKLINE`, which Google Sheets has.

| Module | What it does |
|---|---|
| `build_spreadsheet.py` | Calls the others in order and writes the file |
| `spreadsheet_python_counts.py` | Counts every value in plain Python, e.g. the cause of each trial only in the upper bound |
| `spreadsheet_tabs.py` | Holds the names and colors of the tabs |
| `spreadsheet_row_tabs.py` | Lays out the row tabs and builds the formulas over them that several tabs share |
| `spreadsheet_result_tabs.py` | Lays out `Tasks`, `Requested items`, `Web tools` and `Bounds` |
| `spreadsheet_registries_and_hosts_tab.py` | Lays out `Registries and hosts` and counts its lines |
| `spreadsheet_overview_tab.py` | Lays out `Overview` and `Chart data` |
| `spreadsheet_method_and_checks_tab.py` | Lays out `Method & checks` |
| `spreadsheet_cells.py` | Writes cells, formulas and charts without knowing what they mean |

## Publishing

`scripts/publish_spreadsheet.py` uploads the file through the Google API, since the Drive connector of an assistant takes at most 10 MB per request and the file is larger.

```bash
uv run python -I scripts/publish_spreadsheet.py auth
```

```bash
uv run python -I scripts/publish_spreadsheet.py publish <run_dir>/spreadsheet/internet_use.xlsx [--pdf-dir DIR]
```

| Step | What it needs or does |
|---|---|
| Once | An OAuth client of the type Desktop app in a Google Cloud project with the Drive and Sheets APIs on, saved as `client_secret.json` in `~/.config/tb-internet-audit/` (or the folder `TB_GSHEET_CONF` names) |
| `auth` | Signs in in the browser with the scope `drive.file`, so the script sees only the files it created, and saves the sign-in there. A client in testing mode asks again after 7 days |
| `publish` | Creates the spreadsheet the first time and records its id there, then replaces its content on later runs and sets its name again, so that a changed `SPREADSHEET_TITLE` of `spreadsheet_cells.py` reaches the file of the link. It reads back `Method & checks` as Google Sheets computed it, exits with 1 when a check is not true, and with `--pdf-dir` saves each visible tab as a PDF to look at |
