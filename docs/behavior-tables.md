# Behavior tables

Behavior tables describe how programs, code and servers behave and which naming conventions they follow, as the rules of stages 6 to 10 read them, e.g. which curl options take a value, which output lines show a download or which extension a Python file has.
Each lives in a `*_tables.py` module beside the code that reads it.
Each table holds only rows that the trajectories use, i.e. rows that change what the code reading them returns on the 2026-10-08 data. A row that only a manual lists is left out, e.g. sudo's `-g`.
Mappings that need no judgment live in CSV catalogs instead, e.g. the [program catalog](../src/tb_internet_use/parse/program/catalogs/program_catalog.csv).

This page is written by `scripts/build_behavior_tables_doc.py` from `src/tb_internet_use/behavior_tables.py`, so edit the tables and run it again.

| Basis | Meaning |
|---|---|
| trajectories | The rows are chosen from what the trajectories hold, e.g. the wrappers that commands use or the lines that programs print. |
| manuals | The values follow the programs' documentation, e.g. which curl options take a value. |
| standards | The rows follow a standard or a common convention, e.g. the `.py` extension. |

## Summary

| Table | Module | Basis | Rows | What it holds |
|---|---|---|---|---|
| [`WRAPPERS`](#wrappers) | `parse/shell/program_tables.py` | trajectories, manuals | 11 | Commands that run the command in their arguments. |
| [`PROGRAMS_GIVING_RUN_TIME_ARGUMENTS`](#programs_giving_run_time_arguments) | `parse/shell/program_tables.py` | manuals | 2 | Programs that run another program with arguments the text does not show. |
| [`PYTHON_OPTIONS_WITH_VALUE_BEFORE_MODULE`](#python_options_with_value_before_module) | `parse/shell/program_tables.py` | manuals | 2 | Python options that take the next word as their value, e.g. -X in `python -X dev -m pip`. |
| [`VERSIONED_PROGRAMS`](#versioned_programs) | `parse/shell/program_tables.py` | standards | 4 | Programs whose name often ends with a version, e.g. python3.11, pip3 and gcc-12. |
| [`SHELL_PROGRAMS`](#shell_programs) | `parse/shell/program_tables.py` | manuals | 3 | Shells that run a file, a `-c` text or their stdin as shell text, e.g. bash in `bash -c 'a && b'`. |
| [`EXIT_CODE_SHELL_OPTION_NAMES`](#exit_code_shell_option_names) | `parse/shell/program_tables.py` | manuals | 1 | Option names after `bash -o` that change what the exit code says, e.g. pipefail in `bash -o pipefail -c a`. |
| [`OPTION_SYNTAX_OF_PROGRAM`](#option_syntax_of_program) | `parse/program/option_syntax_tables.py` | trajectories, manuals | 29 | Syntax of the programs whose options decide a file, a script, a target or code, by the name `normalized_program_name` gives. |
| [`CODE_PROGRAMS`](#code_programs) | `interpret/callrun/code_program_tables.py` | trajectories, manuals | 4 | Programs that run code, by the name `normalized_program_name` gives. |
| [`LANGUAGE_OF_FILE_EXTENSION`](#language_of_file_extension) | `interpret/callrun/code_program_tables.py` | standards | 5 | Languages of the code files a command runs directly, e.g. ./get.py. |
| [`SHELL_FILE_EXTENSIONS`](#shell_file_extensions) | `interpret/callrun/code_program_tables.py` | standards | 1 | Extensions of the shell files a command runs directly, e.g. ./fetch.sh. |
| [`OPTION_MEANINGS_OF_PROGRAM`](#option_meanings_of_program) | `interpret/request/option_meaning_tables.py` | trajectories, manuals | 12 | Option meanings of the programs with a request row in the program catalog, by the name `normalized_program_name` gives. |
| [`SCHEMELESS_URL_PROGRAMS`](#schemeless_url_programs) | `interpret/request/target_tables.py` | manuals | 1 | Programs that read a target without a scheme as a URL, e.g. pypi.org/simple in `curl pypi.org/simple`. |
| [`PROGRAMS_WITH_HOST_AS_FIRST_TARGET`](#programs_with_host_as_first_target) | `interpret/request/target_tables.py` | manuals | 5 | Programs whose first target is the host they connect to or look up, e.g. a.org in `nc a.org 80` or `nslookup a.org`. |
| [`PROGRAMS_WITH_HOST_AS_EVERY_TARGET`](#programs_with_host_as_every_target) | `interpret/request/target_tables.py` | manuals | 1 | Name lookup programs whose every target is a host, e.g. a.org and b.org in `getent hosts a.org b.org`. |
| [`NETWORK_CALL_OF_LANGUAGE`](#network_call_of_language) | `interpret/request/code_request_tables.py` | trajectories, manuals | 2 | Network calls in code, by language. |
| [`PROGRAM_RUN_BY_CODE`](#program_run_by_code) | `interpret/request/code_request_tables.py` | manuals |  | A program that the code runs, e.g. pip in `subprocess.run(["pip", "install", "x"])` or `os.system("python -m pip install x")`. |
| [`HOST_NAMED_BY_CODE`](#host_named_by_code) | `interpret/request/code_request_tables.py` | trajectories |  | Hosts that code names as an address tuple, e.g. ("api", 8000), or as the argument of a name lookup. |
| [`SCHEMA_HOST_NAMES`](#schema_host_names) | `interpret/request/code_request_tables.py` | trajectories | 4 | Hosts of XML namespaces and schemas, whose URLs code uses as names and does not fetch unless they name a file. |
| [`PROGRAM_OUTPUT_LINE_PATTERNS`](#program_output_line_patterns) | `interpret/observation/line_pattern_tables.py` | trajectories | 36 | Lines that programs print, read in every call's output except a web tool result. |
| [`WEB_TOOL_RESULT_LINE_PATTERNS`](#web_tool_result_line_patterns) | `interpret/observation/line_pattern_tables.py` | trajectories | 1 | Web tool results are page text, so only a page that a server gave instead of the content counts, e.g. a robot check. |

## Tables

### `WRAPPERS`

Module: [`parse/shell/program_tables.py`](../src/tb_internet_use/parse/shell/program_tables.py). Basis: trajectories, manuals.

Commands that run the command in their arguments.

| Key | options_with_value | operand_count | takes_assignments |
|---|---|---|---|
| `sudo` | `-u` | 0 | yes |
| `env` | `-u` | 0 | yes |
| `timeout` | `--kill-after`, `--signal`, `-k`, `-s` | 1 | no |
| `nohup` |  | 0 | no |
| `nice` | `-n` | 0 | no |
| `time` | `-f`, `-o` | 0 | yes |
| `stdbuf` |  | 0 | no |
| `setsid` |  | 0 | no |
| `exec` | `-a` | 0 | no |
| `command` |  | 0 | no |
| `xargs` | `-I`, `-L`, `-P`, `-a`, `-d`, `-n` | 0 | no |

### `PROGRAMS_GIVING_RUN_TIME_ARGUMENTS`

Module: [`parse/shell/program_tables.py`](../src/tb_internet_use/parse/shell/program_tables.py). Basis: manuals.

Programs that run another program with arguments the text does not show.

`find`, `xargs`

### `PYTHON_OPTIONS_WITH_VALUE_BEFORE_MODULE`

Module: [`parse/shell/program_tables.py`](../src/tb_internet_use/parse/shell/program_tables.py). Basis: manuals.

Python options that take the next word as their value, e.g. -X in `python -X dev -m pip`.

`-W`, `-X`

### `VERSIONED_PROGRAMS`

Module: [`parse/shell/program_tables.py`](../src/tb_internet_use/parse/shell/program_tables.py). Basis: standards.

Programs whose name often ends with a version, e.g. python3.11, pip3 and gcc-12.

`clang`, `gcc`, `pip`, `python`

### `SHELL_PROGRAMS`

Module: [`parse/shell/program_tables.py`](../src/tb_internet_use/parse/shell/program_tables.py). Basis: manuals.

Shells that run a file, a `-c` text or their stdin as shell text, e.g. bash in `bash -c 'a && b'`.

`bash`, `dash`, `sh`

### `EXIT_CODE_SHELL_OPTION_NAMES`

Module: [`parse/shell/program_tables.py`](../src/tb_internet_use/parse/shell/program_tables.py). Basis: manuals.

Option names after `bash -o` that change what the exit code says, e.g. pipefail in `bash -o pipefail -c a`.

`pipefail`

### `OPTION_SYNTAX_OF_PROGRAM`

Module: [`parse/program/option_syntax_tables.py`](../src/tb_internet_use/parse/program/option_syntax_tables.py). Basis: trajectories, manuals.

Syntax of the programs whose options decide a file, a script, a target or code, by the name `normalized_program_name` gives. A program without one has no option with a value.

| Key | short_options_with_value | long_options_with_value | one_dash_long_options | options_end_at_first_plain_argument | script_options |
|---|---|---|---|---|---|
| `curl` | `oDrmcbFTAuwXHd` | `--connect-timeout`, `--data-binary`, `--data-raw`, `--data-urlencode`, `--data`, `--header`, `--max-time`, `--output`, `--range`, `--request`, `--retry-delay`, `--retry`, `--upload-file`, `--url-query`, `--user`, `--write-out` |  | no |  |
| `wget` | `O` |  |  | no |  |
| `pip` | `reitfd` | `--dest`, `--extra-index-url`, `--find-links`, `--implementation`, `--index-url`, `--no-binary`, `--only-binary`, `--platform`, `--progress-bar`, `--python-version`, `--python`, `--report`, `--target`, `--timeout` |  | no |  |
| `uv` | `e` | `--extra-index-url`, `--index-url`, `--python`, `--with` |  | no |  |
| `npm` |  | `--package`, `--prefix` |  | no |  |
| `pnpm` | `p` | `--dir` |  | no |  |
| `npx` | `p` | `--package`, `--prefix` |  | no |  |
| `bun` | `pe` | `--eval` |  | no |  |
| `apt-get` | `o` |  |  | no |  |
| `git` | `Cboc` | `--branch`, `--depth`, `--filter` |  | no |  |
| `rsync` |  | `--exclude` |  | no |  |
| `ping` | `ciW` |  |  | no |  |
| `nc` | `wq` |  |  | no |  |
| `gh` |  | `--jq` |  | no |  |
| `conda` | `nc` |  |  | no |  |
| `huggingface-cli` |  | `--local-dir`, `--revision` |  | no |  |
| `python` | `cmWX` |  |  | yes |  |
| `node` | `epr` | `-pe` | `-pe` | yes |  |
| `tsx` | `e` | `--eval` |  | yes |  |
| `head` | `nc` |  |  | no |  |
| `tail` | `nc` |  |  | no |  |
| `grep` | `efmABC` | `--exclude-dir`, `--exclude`, `--include` |  | no | `--file`, `--regexp`, `-e`, `-f` |
| `egrep` |  |  |  | no | `--file`, `--regexp`, `-e`, `-f` |
| `rg` | `egmABCr` | `--context`, `--glob`, `--max-count`, `--type` |  | no | `--file`, `--regexp`, `-e`, `-f` |
| `sed` | `e` |  |  | no | `--expression`, `--file`, `-e`, `-f` |
| `awk` | `Fvf` |  |  | no | `--file`, `--source`, `-e`, `-f` |
| `jq` | `f` |  |  | no | `--from-file`, `-f` |
| `cut` | `dfc` |  |  | no |  |
| `sort` | `ktoST` |  |  | no |  |

### `CODE_PROGRAMS`

Module: [`interpret/callrun/code_program_tables.py`](../src/tb_internet_use/interpret/callrun/code_program_tables.py). Basis: trajectories, manuals.

Programs that run code, by the name `normalized_program_name` gives.

| Key | language | inline_code_options | file_subcommand | needs_code_file_extension |
|---|---|---|---|---|
| `python` | python | `-c` |  | no |
| `node` | javascript | `-e`, `-p`, `-pe` |  | no |
| `bun` | javascript | `--eval`, `-e` | `run` | yes |
| `tsx` | javascript | `--eval`, `-e` |  | no |

### `LANGUAGE_OF_FILE_EXTENSION`

Module: [`interpret/callrun/code_program_tables.py`](../src/tb_internet_use/interpret/callrun/code_program_tables.py). Basis: standards.

Languages of the code files a command runs directly, e.g. ./get.py.

| Key | Value |
|---|---|
| `.py` | python |
| `.js` | javascript |
| `.mjs` | javascript |
| `.cjs` | javascript |
| `.ts` | javascript |

### `SHELL_FILE_EXTENSIONS`

Module: [`interpret/callrun/code_program_tables.py`](../src/tb_internet_use/interpret/callrun/code_program_tables.py). Basis: standards.

Extensions of the shell files a command runs directly, e.g. ./fetch.sh.

`.sh`

### `OPTION_MEANINGS_OF_PROGRAM`

Module: [`interpret/request/option_meaning_tables.py`](../src/tb_internet_use/interpret/request/option_meaning_tables.py). Basis: trajectories, manuals.

Option meanings of the programs with a request row in the program catalog, by the name `normalized_program_name` gives. A program without a row sends no request only with --help or --version, and its other options change nothing.

| Key | no_request_options | offline_options | quiet_progress_options | quiet_error_options | error_showing_options | index_options | package_file_options |
|---|---|---|---|---|---|---|---|
| `curl` | `--version` |  |  | `--silent`, `-s` | `--show-error`, `-S` |  |  |
| `wget` |  |  |  | `-q` |  |  |  |
| `pip` | `--help`, `--version` | `--no-index` | `--quiet`, `-q` |  |  | `--extra-index-url`, `--index-url`, `-i` | `-e`, `-r` |
| `uv` | `--help` |  | `--quiet`, `-q` |  |  | `--extra-index-url`, `--index-url` | `-e` |
| `npm` |  | `--offline`, `--prefer-offline` | `--quiet` | `--silent` |  |  |  |
| `pnpm` |  | `--offline` |  |  |  |  |  |
| `bun` |  |  |  |  |  |  |  |
| `npx` | `--version` | `--no-install` |  |  |  |  |  |
| `apt` |  |  | `-q` |  |  |  |  |
| `apt-get` | `--help` |  | `-q` |  |  |  |  |
| `git` |  |  | `--quiet`, `-q` |  |  |  |  |
| `nc` |  |  |  |  |  |  |  |

### `SCHEMELESS_URL_PROGRAMS`

Module: [`interpret/request/target_tables.py`](../src/tb_internet_use/interpret/request/target_tables.py). Basis: manuals.

Programs that read a target without a scheme as a URL, e.g. pypi.org/simple in `curl pypi.org/simple`.

`curl`

### `PROGRAMS_WITH_HOST_AS_FIRST_TARGET`

Module: [`interpret/request/target_tables.py`](../src/tb_internet_use/interpret/request/target_tables.py). Basis: manuals.

Programs whose first target is the host they connect to or look up, e.g. a.org in `nc a.org 80` or `nslookup a.org`. Later targets are not read.

`dig`, `host`, `nc`, `nslookup`, `ping`

### `PROGRAMS_WITH_HOST_AS_EVERY_TARGET`

Module: [`interpret/request/target_tables.py`](../src/tb_internet_use/interpret/request/target_tables.py). Basis: manuals.

Name lookup programs whose every target is a host, e.g. a.org and b.org in `getent hosts a.org b.org`.

`getent`

### `NETWORK_CALL_OF_LANGUAGE`

Module: [`interpret/request/code_request_tables.py`](../src/tb_internet_use/interpret/request/code_request_tables.py). Basis: trajectories, manuals.

Network calls in code, by language. One request per code text, however many of these it holds.

| Key | Value |
|---|---|
| python | `\brequests\.(?:get\|post\|put\|head\|request\|Session)\b\|\bhttpx\.(?:get\|post\|stream\|Client\|AsyncClient)\b\|\baiohttp\.ClientSession\b\|\burlopen\(\|\burlretrieve\(\|\b(?:snapshot_download\|hf_hub_download\|from_pretrained\|load_dataset)\(\|\bnltk\.download\(\|\bsocket\.(?:create_connection\|getaddrinfo\|gethostbyname)\b` |
| javascript | `\bfetch\(\|\bhttps?\.get\(` |

### `PROGRAM_RUN_BY_CODE`

Module: [`interpret/request/code_request_tables.py`](../src/tb_internet_use/interpret/request/code_request_tables.py). Basis: manuals.

A program that the code runs, e.g. pip in `subprocess.run(["pip", "install", "x"])` or `os.system("python -m pip install x")`. The name is a whole word of a string, so `.git` in `["rm", "-rf", ".git"]` names no program.

```text
\b(?:subprocess\.\w+|os\.system|os\.popen)\([^)]*?(?<=['"\s/])(pip|curl|git|npm|apt-get)(?=['"\s])
```

### `HOST_NAMED_BY_CODE`

Module: [`interpret/request/code_request_tables.py`](../src/tb_internet_use/interpret/request/code_request_tables.py). Basis: trajectories.

Hosts that code names as an address tuple, e.g. ("api", 8000), or as the argument of a name lookup. The tuple's parenthesis follows no name, so call arguments such as `d.get("count", 0)` are no address.

```text
(?<![\w.\])])\(\s*['"](\w[\w.-]*)['"]\s*,\s*\d+\s*\)|(?:gethostbyname|getaddrinfo)\(\s*['"]([\w.-]+)['"]
```

### `SCHEMA_HOST_NAMES`

Module: [`interpret/request/code_request_tables.py`](../src/tb_internet_use/interpret/request/code_request_tables.py). Basis: trajectories.

Hosts of XML namespaces and schemas, whose URLs code uses as names and does not fetch unless they name a file.

`json-schema.org`, `purl.org`, `schemas.openxmlformats.org`, `www.w3.org`

### `PROGRAM_OUTPUT_LINE_PATTERNS`

Module: [`interpret/observation/line_pattern_tables.py`](../src/tb_internet_use/interpret/observation/line_pattern_tables.py). Basis: trajectories.

Lines that programs print, read in every call's output except a web tool result.

The first matching row decides, so the order of the rows matters.

| Row (1-based) | kind | printing_programs | is_printed_by_other_programs_too | regex |
|---|---|---|---|---|
| 1 | program_missing |  | yes | `(?<![\w.+-])(?P<program0>[\w.+-]+): command not found$\|(?<!\S)\S+: (?:line )?\d+: (?:\w+: )?(?P<program1>[\w.+/-]+): not found$\|^\S*sh: (?:\w+: )?(?P<program2>[\w.+/-]+): not found$\|No module named (?P<program3>pip)\b\|failed to run command [‘'](?P<program4>[^’']+)[’']: No such file\|^(?:\S*sh: )?(?:line \d+: )?(?P<program5>/\S+): No such file or directory$` |
| 2 | refused_locally | pip | no | `externally-managed-environment\|^hint: See PEP 668` |
| 3 | version_notice | pip | no | `^\[notice\] (?:A new release of pip is available\|To update, run:)` |
| 4 | proxy_refused |  | yes | `ProxyError` |
| 5 | name_not_resolved |  | yes | `Could not resolve host:? (?P<host0>[\w.-]+\.\w+)` |
| 6 | name_not_resolved |  | yes | `Temporary failure in name resolution\|Name or service not known\|nodename nor servname\|No address associated with hostname\|curl: \(6\)` |
| 7 | tls_failed |  | yes | `SSL certificate problem\|CERTIFICATE_VERIFY_FAILED\|SSLError\|curl: \((?:35\|60)\)` |
| 8 | connection_failed | curl | no | `Failed to connect to (?P<host0>[\w.-]+\.\w+)` |
| 9 | connection_failed |  | yes | `Connection refused\|Connection timed out\|ConnectTimeout\|Network is unreachable\|No route to host\|ECONNREFUSED\|ETIMEDOUT\|ENETUNREACH\|curl: \(7\)` |
| 10 | connection_lost |  | yes | `Connection reset by peer\|ECONNRESET\|Read timed out\|curl: \((?:52\|56)\)` |
| 11 | http_status | git, http_headers | yes | `HTTP/[\d.]+ (?P<status_code0>[1-5]\d\d)` |
| 12 | http_status | wget | yes | `ERROR (?P<status_code0>[45]\d\d):\|awaiting response\.\.\. (?P<status_code1>[1-5]\d\d)` |
| 13 | http_status | git, http_failure | yes | `returned error: (?P<status_code0>[45]\d\d)` |
| 14 | http_status |  | yes | `(?P<status_code0>[45]\d\d) (?:Client\|Server) Error\|HTTP Error (?P<status_code1>[45]\d\d)` |
| 15 | http_status | npm | no | `npm (?:ERR!\|error) (?:code E(?P<status_code0>[45]\d\d)\|(?P<status_code1>404))` |
| 16 | not_found | pip | no | `No matching distribution found for (?P<packages0>\S+)\|Could not find a version that satisfies the requirement (?P<packages1>\S+)` |
| 17 | not_found | apt | no | `^E: Unable to locate package (?P<packages0>\S+)\|^E: Package '(?P<packages1>[^']+)' has no installation candidate` |
| 18 | already_present | pip | no | `^Requirement already satisfied: (?P<packages0>[\w.-]+)` |
| 19 | already_present | uv | no | `^Audited \d+ packages?` |
| 20 | already_present | apt | no | `^(?P<packages0>\S+) is already the newest version` |
| 21 | downloaded | playwright | no | `\) downloaded to /` |
| 22 | downloaded | pip | no | `^Successfully downloaded (?P<packages0>\S.*)` |
| 23 | downloaded | pip_index | no | `^Available versions: ` |
| 24 | download_started | code, git, pip, playwright, uv | yes | `^[ \t]*Downloading (?:https?://\S*/)?(?P<packages0>[\w.-]+)` |
| 25 | downloaded | code, git, pip, playwright, uv | yes | `^[ \t]*Downloaded (?P<packages0>[\w.-]+)` |
| 26 | downloaded | apt | no | `^Get:\d+ https?://(?P<host0>[\w.-]+\.\w+)(?:\S* \S+ \S+ (?P<packages1>[\w.+-]+) (?:amd64\|arm64\|armhf\|i386\|all) \S+ \[)?\|^Fetched [\d.,]+ [kMG]?B in` |
| 27 | downloaded | wget | no | `saved \[\d+` |
| 28 | installed | pip | no | `^Successfully installed (?P<packages0>\S.*)` |
| 29 | installed | uv | no | `^Installed \d+ packages?\|^ \+ (?P<packages0>[\w.-]+)==` |
| 30 | installed | npm | no | `\badded \d+ packages?\b` |
| 31 | installed | apt | no | `^Setting up (?P<packages0>\S+) \(\|^Unpacking (?P<packages1>\S+) \(` |
| 32 | server_answered | npm | no | `\baudited \d+ packages?\b\|found \d+ vulnerabilit` |
| 33 | server_answered | apt | no | `^Hit:\d+ https?://(?P<host0>[\w.-]+\.\w+)` |
| 34 | bare_status_code |  | yes | `^(?i:(?:status\|code\|http\|http_code\|http status\|response) ?[:=] ?)?(?P<status_code0>000\|[1-5]\d\d)$` |
| 35 | connected | wget | yes | `\.\.\. connected\.` |
| 36 | connected | git, http_headers | yes | `^\* Connected to (?P<host0>[\w.-]+\.\w+)` |

### `WEB_TOOL_RESULT_LINE_PATTERNS`

Module: [`interpret/observation/line_pattern_tables.py`](../src/tb_internet_use/interpret/observation/line_pattern_tables.py). Basis: trajectories.

Web tool results are page text, so only a page that a server gave instead of the content counts, e.g. a robot check.

The first matching row decides, so the order of the rows matters.

| Row (1-based) | kind | printing_programs | is_printed_by_other_programs_too | regex |
|---|---|---|---|---|
| 1 | server_answered |  | no | `not a robot` |

## Rules inside code

These rules about programs, output, hosts and package names stay in logic modules, since they need code that a table cannot hold, e.g. a condition on an option's value, or they are a pattern of a format, e.g. a URL.

| Rule | Module | What it holds |
|---|---|---|
| `_VERSION_SUFFIX` | `parse/shell/programs.py` | A version at the end of a program name, e.g. 3.11 in python3.11 or -12 in gcc-12. |
| `_find_exec_words` | `parse/shell/programs.py` | Take the command of `find -exec` or `-execdir`, without its `{}` and its `;` or `+` end. |
| `_python_module_words` | `parse/shell/programs.py` | Take the module and its arguments from `python [options] -m module ...`, empty without -m. |
| `_shell_invocation` | `parse/shell/programs.py` | Read a shell's options up to the first operand, which is the text when -c is given, or else the file it runs. |
| `WrittenFiles.record_command` | `interpret/callrun/_written_files.py` | Record what a command writes, i.e. files it redirects to, `tee` files, `sed -i` files and the destination of `cp` or `mv`. |
| `tee_file_destinations` | `interpret/callrun/_output_routes.py` | List the files a `tee` command writes its input to, appending with -a, e.g. log in `tee -a log`. |
| `_command_reads` | `interpret/callrun/_file_reads.py` | List the files that a reading command reads, i.e. the files it names, e.g. fetch.log in `tail -n 5 fetch.log`, and its stdin file, e.g. log in `grep x < log`. |
| `_KEY_PRESS_CHARACTERS` | `interpret/callrun/_poll_links.py` | Characters that typed input holds when it only presses keys, e.g. Enter or Ctrl-C. |
| `_ENDED_STATUSES` | `interpret/callrun/_poll_links.py` | Statuses of a poll that saw the polled command end. |
| `_rule_after_options` | `interpret/request/_program_options.py` | Change a request rule by the curl or wget options that change what a run prints and what its exit code 0 means. |
| `_SCP_LIKE_ADDRESS` | `interpret/request/_targets.py` | A remote git address without a scheme, e.g. github.com in `git@github.com:org/repo.git`. The host needs a user or a dot, so a refspec such as `main:main` in `git fetch origin main:main` is no address. |
| `_SCHEMELESS_HOST` | `interpret/request/_targets.py` | A host at the start of a URL without a scheme, e.g. pypi.org in `pypi.org/simple` or localhost in `localhost:8000/x`. |
| `_PATH_OR_URL` | `interpret/request/_targets.py` | Targets that name a local path, a URL or an archive instead of a package, e.g. `./dist/x.whl`, `.` or `.[dev]`. |
| `_remote_host_names` | `interpret/request/_targets.py` | Find the hosts a direct connection names, e.g. host for `nc host 80` or `rsync f host:/x`, and both for `dig @8.8.8.8 a.org`. |
| `_URL` | `interpret/request/_code_requests.py` | A URL with an http or https scheme, ending before a space, a quote, a backtick, an angle bracket or a closing bracket. |
| `_is_schema_name` | `interpret/request/_code_requests.py` | Check whether a URL is an XML namespace or schema name rather than a file, e.g. `http://www.w3.org/2000/svg`. |
| `_TEMPLATE_CHARACTER` | `network/hosts.py` | A character that a shell or code template computes, e.g. $ in `$HOST` or { in `{host}`. |
| `_LOCAL_NAME` | `network/hosts.py` | Names that resolve to this machine or its private network, e.g. localhost or db.internal. |
| `_RESERVED_NAME` | `network/hosts.py` | Names reserved for examples and tests by RFC 2606 and RFC 6761, e.g. example.com or x.test. |
| `_ARCHIVE_FILE` | `network/package_names.py` | A wheel or source archive file or its metadata, whose name ends at the first dash before a digit, e.g. `requests-2.32.3-py3-none-any.whl.metadata`. |
| `_AFTER_NAME` | `network/package_names.py` | Where a version, an extra, an architecture or a list separator starts after a name, e.g. == in `requests==2.0`. |
| `_DASHED_VERSION_AT_END` | `network/package_names.py` | A version after a dash at the end of a name, e.g. -2.32.3 in `requests-2.32.3`. A dash before a digit inside a name stays, e.g. in the apt package `openjdk-17-jdk`. |
| `_SEPARATORS` | `network/package_names.py` | Runs of separators that package indexes treat as one, e.g. `_` and `.` in `Typing_Extensions`. |
| `_ANSI_CSI_SEQUENCE` | `interpret/observation/_extract_observations.py` | An ANSI control sequence of the CSI form, i.e. ESC and `[`, then parameter and intermediate bytes and a final byte, e.g. the color code `\x1b[32m`. |
