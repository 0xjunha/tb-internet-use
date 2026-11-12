# Behavior tables

Behavior tables describe how programs, code and servers behave and which naming conventions they follow, as the rules of stages 6 to 10 read them, e.g. which curl options take a value, which output lines show a download or which extension a Python file has.
Each lives in a `*_tables.py` module beside the code that reads it.
Mappings that need no judgment live in CSV catalogs instead, e.g. the [program catalog](../src/tb_internet_use/program/catalogs/program_catalog.csv).

This page is written by `scripts/build_behavior_tables_doc.py` from `src/tb_internet_use/behavior_tables.py`, so edit the tables and run it again.

| Basis | Meaning |
|---|---|
| trajectories | The rows are chosen from what the trajectories hold, e.g. the wrappers that commands use or the lines that programs print. |
| manuals | The values follow the programs' documentation, e.g. which curl options take a value. |
| standards | The rows follow a standard or a common convention, e.g. DNS record types or the `.py` extension. |

## Summary

| Table | Module | Basis | Rows | What it holds |
|---|---|---|---|---|
| [`WRAPPERS`](#wrappers) | `shell/program_tables.py` | trajectories, manuals | 14 | Commands that run the command in their arguments. |
| [`PROGRAMS_GIVING_RUN_TIME_ARGUMENTS`](#programs_giving_run_time_arguments) | `shell/program_tables.py` | manuals | 2 | Programs that run another program with arguments the text does not show. |
| [`PYTHON_OPTIONS_WITH_VALUE_BEFORE_MODULE`](#python_options_with_value_before_module) | `shell/program_tables.py` | manuals | 2 | Python options that take the next word as their value, e.g. -X in `python -X dev -m pip`. |
| [`VERSIONED_PROGRAMS`](#versioned_programs) | `shell/program_tables.py` | standards | 16 | Programs whose name often ends with a version, e.g. python3.11, pip3 and gcc-12. |
| [`SHELL_PROGRAMS`](#shell_programs) | `shell/program_tables.py` | manuals | 4 | Shells that run a file, a `-c` text or their stdin as shell text, e.g. bash in `bash -c 'a && b'`. |
| [`EXIT_CODE_SHELL_OPTION_NAMES`](#exit_code_shell_option_names) | `shell/program_tables.py` | manuals | 2 | Options that `set -o` and `bash -o` take and that change what the exit code says. |
| [`SHELL_LONG_OPTIONS_WITH_VALUE`](#shell_long_options_with_value) | `shell/program_tables.py` | manuals | 2 | Long shell options that take the next word as their value, e.g. `bash --rcfile f`. |
| [`OPTION_SYNTAX_OF_PROGRAM`](#option_syntax_of_program) | `program/option_syntax_tables.py` | trajectories, manuals | 34 | Syntax of the programs whose options decide a file, a script, a target or code, by the name `normalized_program_name` gives. |
| [`CODE_PROGRAMS`](#code_programs) | `callrun/code_program_tables.py` | trajectories, manuals | 6 | Programs that run code, by the name `normalized_program_name` gives. |
| [`LANGUAGE_OF_FILE_EXTENSION`](#language_of_file_extension) | `callrun/code_program_tables.py` | standards | 5 | Languages of the code files a command runs directly, e.g. ./get.py. |
| [`SHELL_FILE_EXTENSIONS`](#shell_file_extensions) | `callrun/code_program_tables.py` | standards | 2 | Extensions of the shell files a command runs directly, e.g. ./fetch.sh. |
| [`OPTION_MEANINGS_OF_PROGRAM`](#option_meanings_of_program) | `request/option_meaning_tables.py` | trajectories, manuals | 12 | Option meanings of the programs with a request row in the program catalog, by the name `normalized_program_name` gives. |
| [`SCHEMELESS_URL_PROGRAMS`](#schemeless_url_programs) | `request/target_tables.py` | manuals | 2 | Programs that read a target without a scheme as a URL, e.g. pypi.org/simple in `curl pypi.org/simple`. |
| [`PROGRAMS_WITH_HOST_AS_FIRST_TARGET`](#programs_with_host_as_first_target) | `request/target_tables.py` | manuals | 5 | Direct connection and name lookup programs whose first target is a host and the rest are ports or record types, e.g. `nc host 80`. |
| [`DNS_LOOKUP_PROGRAMS`](#dns_lookup_programs) | `request/target_tables.py` | manuals | 3 | Name lookup programs whose targets can hold DNS record types and classes before the host too, e.g. MX in `dig MX a.org`. |
| [`DNS_RECORD_TYPES_AND_CLASSES`](#dns_record_types_and_classes) | `request/target_tables.py` | standards | 13 | Common DNS record types and classes in upper case, which name no host, e.g. MX and IN in `dig IN MX a.org`. |
| [`PROGRAMS_WITH_HOST_AS_EVERY_TARGET`](#programs_with_host_as_every_target) | `request/target_tables.py` | manuals | 1 | Name lookup programs whose every target is a host, e.g. a.org and b.org in `getent hosts a.org b.org`. |
| [`NETWORK_CALL_OF_LANGUAGE`](#network_call_of_language) | `request/code_request_tables.py` | trajectories, manuals | 2 | Network calls in code, by language. |
| [`PROGRAM_RUN_BY_CODE`](#program_run_by_code) | `request/code_request_tables.py` | manuals |  | A program that the code runs, e.g. pip in `subprocess.run(["pip", "install", "x"])` or `os.system("python -m pip install x")`. |
| [`HOST_NAMED_BY_CODE`](#host_named_by_code) | `request/code_request_tables.py` | trajectories |  | Hosts that code names as an address tuple, e.g. ("api", 8000), or as the argument of a name lookup. |
| [`SCHEMA_HOST_NAMES`](#schema_host_names) | `request/code_request_tables.py` | trajectories | 9 | Hosts of XML namespaces and schemas, whose URLs code uses as names and does not fetch unless they name a file. |
| [`PROGRAM_OUTPUT_LINE_PATTERNS`](#program_output_line_patterns) | `observation/line_pattern_tables.py` | trajectories | 36 | Lines that programs print, read in every call's output except a web tool result. |
| [`WEB_TOOL_RESULT_LINE_PATTERNS`](#web_tool_result_line_patterns) | `observation/line_pattern_tables.py` | trajectories | 1 | Web tool results are page text, so only a page that a server gave instead of the content counts, e.g. a robot check. |

## Tables

### `WRAPPERS`

Module: [`shell/program_tables.py`](../src/tb_internet_use/shell/program_tables.py). Basis: trajectories, manuals.

Commands that run the command in their arguments.

| Key | options_with_value | operand_count | takes_assignments |
|---|---|---|---|
| `sudo` | `--chdir`, `--chroot`, `--close-from`, `--command-timeout`, `--group`, `--host`, `--other-user`, `--prompt`, `--role`, `--type`, `--user`, `-C`, `-D`, `-R`, `-T`, `-U`, `-g`, `-h`, `-p`, `-r`, `-t`, `-u` | 0 | yes |
| `doas` | `-C`, `-u` | 0 | no |
| `env` | `--chdir`, `--unset`, `-C`, `-u` | 0 | yes |
| `timeout` | `--kill-after`, `--signal`, `-k`, `-s` | 1 | no |
| `gtimeout` | `--kill-after`, `--signal`, `-k`, `-s` | 1 | no |
| `nohup` |  | 0 | no |
| `nice` | `--adjustment`, `-n` | 0 | no |
| `time` | `--format`, `--output`, `-f`, `-o` | 0 | yes |
| `stdbuf` | `--error`, `--input`, `--output`, `-e`, `-i`, `-o` | 0 | no |
| `setsid` |  | 0 | no |
| `unbuffer` |  | 0 | no |
| `exec` | `-a` | 0 | no |
| `command` |  | 0 | no |
| `xargs` | `--arg-file`, `--delimiter`, `--max-args`, `--max-chars`, `--max-lines`, `--max-procs`, `-E`, `-I`, `-L`, `-P`, `-a`, `-d`, `-n`, `-s` | 0 | no |

### `PROGRAMS_GIVING_RUN_TIME_ARGUMENTS`

Module: [`shell/program_tables.py`](../src/tb_internet_use/shell/program_tables.py). Basis: manuals.

Programs that run another program with arguments the text does not show.

`find`, `xargs`

### `PYTHON_OPTIONS_WITH_VALUE_BEFORE_MODULE`

Module: [`shell/program_tables.py`](../src/tb_internet_use/shell/program_tables.py). Basis: manuals.

Python options that take the next word as their value, e.g. -X in `python -X dev -m pip`.

`-W`, `-X`

### `VERSIONED_PROGRAMS`

Module: [`shell/program_tables.py`](../src/tb_internet_use/shell/program_tables.py). Basis: standards.

Programs whose name often ends with a version, e.g. python3.11, pip3 and gcc-12.

`clang++`, `clang`, `g++`, `gcc`, `gem`, `java`, `javac`, `lua`, `node`, `perl`, `php`, `pip`, `pydoc`, `pypy`, `python`, `ruby`

### `SHELL_PROGRAMS`

Module: [`shell/program_tables.py`](../src/tb_internet_use/shell/program_tables.py). Basis: manuals.

Shells that run a file, a `-c` text or their stdin as shell text, e.g. bash in `bash -c 'a && b'`.

`bash`, `dash`, `sh`, `zsh`

### `EXIT_CODE_SHELL_OPTION_NAMES`

Module: [`shell/program_tables.py`](../src/tb_internet_use/shell/program_tables.py). Basis: manuals.

Options that `set -o` and `bash -o` take and that change what the exit code says.

`errexit`, `pipefail`

### `SHELL_LONG_OPTIONS_WITH_VALUE`

Module: [`shell/program_tables.py`](../src/tb_internet_use/shell/program_tables.py). Basis: manuals.

Long shell options that take the next word as their value, e.g. `bash --rcfile f`.

`--init-file`, `--rcfile`

### `OPTION_SYNTAX_OF_PROGRAM`

Module: [`program/option_syntax_tables.py`](../src/tb_internet_use/program/option_syntax_tables.py). Basis: trajectories, manuals.

Syntax of the programs whose options decide a file, a script, a target or code, by the name `normalized_program_name` gives. A program without one has no option with a value.

| Key | short_options_with_value | long_options_with_value | one_dash_long_options | options_end_at_first_plain_argument | script_options |
|---|---|---|---|---|---|
| `curl` | `oDCEYyzKrxmcbFTeAuwXHdU` | `--cacert`, `--cert`, `--config`, `--connect-timeout`, `--continue-at`, `--cookie-jar`, `--cookie`, `--data-ascii`, `--data-binary`, `--data-raw`, `--data-urlencode`, `--data`, `--dump-header`, `--form`, `--header`, `--key`, `--limit-rate`, `--max-redirs`, `--max-time`, `--output-dir`, `--output`, `--proto`, `--proxy`, `--range`, `--referer`, `--request`, `--resolve`, `--retry-delay`, `--retry-max-time`, `--retry`, `--upload-file`, `--url-query`, `--user-agent`, `--user`, `--write-out` |  | no |  |
| `wget` | `OoaPtTwUeiQlARBDIX` | `--directory-prefix`, `--header`, `--input-file`, `--limit-rate`, `--load-cookies`, `--output-document`, `--output-file`, `--password`, `--post-data`, `--post-file`, `--save-cookies`, `--timeout`, `--tries`, `--user-agent`, `--user`, `--wait` | `-nv` | no |  |
| `pip` | `rceitfbd` | `--abi`, `--cache-dir`, `--constraint`, `--dest`, `--editable`, `--extra-index-url`, `--find-links`, `--implementation`, `--index-url`, `--log`, `--no-binary`, `--only-binary`, `--platform`, `--prefix`, `--progress-bar`, `--python-version`, `--python`, `--report`, `--requirement`, `--root`, `--src`, `--target`, `--timeout`, `--trusted-host`, `--upgrade-strategy` |  | no |  |
| `uv` | `rcepi` | `--abi`, `--cache-dir`, `--constraint`, `--default-index`, `--dest`, `--directory`, `--editable`, `--extra-index-url`, `--extra`, `--find-links`, `--from`, `--group`, `--implementation`, `--index-url`, `--index`, `--log`, `--no-binary`, `--only-binary`, `--platform`, `--prefix`, `--progress-bar`, `--project`, `--python-version`, `--python`, `--report`, `--requirement`, `--root`, `--src`, `--target`, `--timeout`, `--trusted-host`, `--upgrade-strategy`, `--with` |  | no |  |
| `npm` | `Cwp` | `--cache`, `--dir`, `--filter`, `--package`, `--prefix`, `--registry`, `--userconfig`, `--workspace` |  | no |  |
| `pnpm` | `Cwp` | `--cache`, `--dir`, `--filter`, `--package`, `--prefix`, `--registry`, `--userconfig`, `--workspace` |  | no |  |
| `npx` | `Cwp` | `--cache`, `--dir`, `--filter`, `--package`, `--prefix`, `--registry`, `--userconfig`, `--workspace` |  | no |  |
| `bun` | `Cwpe` | `--cache`, `--dir`, `--eval`, `--filter`, `--package`, `--prefix`, `--registry`, `--userconfig`, `--workspace` |  | no |  |
| `deno` | `e` | `--eval` |  | no |  |
| `apt` | `ot` | `--option`, `--target-release` |  | no |  |
| `apt-get` | `ot` | `--option`, `--target-release` |  | no |  |
| `git` | `Cbojc` | `--branch`, `--config`, `--depth`, `--filter`, `--jobs`, `--origin`, `--reference`, `--shallow-since`, `--upload-pack` |  | no |  |
| `rsync` | `eT` | `--exclude`, `--include` |  | no |  |
| `ping` | `ciWws` |  |  | no |  |
| `nc` | `pwsiq` |  |  | no |  |
| `dig` | `tcpfbky` |  |  | no |  |
| `host` | `tcNRWm` |  |  | no |  |
| `gh` | `XHfFRpDq` | `--dir`, `--field`, `--header`, `--jq`, `--method`, `--pattern`, `--raw-field`, `--repo` |  | no |  |
| `conda` | `ncp` | `--channel`, `--name`, `--prefix` |  | no |  |
| `huggingface-cli` |  | `--cache-dir`, `--exclude`, `--include`, `--local-dir`, `--repo-type`, `--revision`, `--token` |  | no |  |
| `python` | `cmWX` |  |  | yes |  |
| `node` | `epr` | `--eval`, `--print`, `--require`, `-pe` | `-pe` | yes |  |
| `tsx` | `e` | `--eval` |  | yes |  |
| `ts-node` | `e` | `--eval` |  | yes |  |
| `head` | `nc` | `--bytes`, `--lines` |  | no |  |
| `tail` | `nc` | `--bytes`, `--lines` |  | no |  |
| `grep` | `efmABCdD` | `--after-context`, `--before-context`, `--context`, `--exclude-dir`, `--exclude`, `--file`, `--include`, `--max-count`, `--regexp` |  | no | `--file`, `--regexp`, `-e`, `-f` |
| `egrep` | `efmABCdD` | `--after-context`, `--before-context`, `--context`, `--exclude-dir`, `--exclude`, `--file`, `--include`, `--max-count`, `--regexp` |  | no | `--file`, `--regexp`, `-e`, `-f` |
| `rg` | `efgtTmABCrj` | `--after-context`, `--before-context`, `--context`, `--file`, `--glob`, `--max-count`, `--regexp`, `--replace`, `--threads`, `--type-not`, `--type` |  | no | `--file`, `--regexp`, `-e`, `-f` |
| `sed` | `efl` | `--expression`, `--file` |  | no | `--expression`, `--file`, `-e`, `-f` |
| `awk` | `Fvfe` | `--assign`, `--field-separator`, `--file`, `--source` |  | no | `--file`, `--source`, `-e`, `-f` |
| `jq` | `f` | `--from-file`, `--indent` |  | no | `--from-file`, `-f` |
| `cut` | `dfcb` | `--bytes`, `--characters`, `--delimiter`, `--fields` |  | no |  |
| `sort` | `ktoST` | `--buffer-size`, `--field-separator`, `--key`, `--output` |  | no |  |

### `CODE_PROGRAMS`

Module: [`callrun/code_program_tables.py`](../src/tb_internet_use/callrun/code_program_tables.py). Basis: trajectories, manuals.

Programs that run code, by the name `normalized_program_name` gives.

| Key | language | inline_code_options | file_subcommand | needs_code_file_extension |
|---|---|---|---|---|
| `python` | python | `-c` |  | no |
| `node` | javascript | `--eval`, `--print`, `-e`, `-p`, `-pe` |  | no |
| `bun` | javascript | `--eval`, `-e` | `run` | yes |
| `deno` | javascript | `--eval`, `-e` | `run` | yes |
| `tsx` | javascript | `--eval`, `-e` |  | no |
| `ts-node` | javascript | `--eval`, `-e` |  | no |

### `LANGUAGE_OF_FILE_EXTENSION`

Module: [`callrun/code_program_tables.py`](../src/tb_internet_use/callrun/code_program_tables.py). Basis: standards.

Languages of the code files a command runs directly, e.g. ./get.py.

| Key | Value |
|---|---|
| `.py` | python |
| `.js` | javascript |
| `.mjs` | javascript |
| `.cjs` | javascript |
| `.ts` | javascript |

### `SHELL_FILE_EXTENSIONS`

Module: [`callrun/code_program_tables.py`](../src/tb_internet_use/callrun/code_program_tables.py). Basis: standards.

Extensions of the shell files a command runs directly, e.g. ./fetch.sh.

`.bash`, `.sh`

### `OPTION_MEANINGS_OF_PROGRAM`

Module: [`request/option_meaning_tables.py`](../src/tb_internet_use/request/option_meaning_tables.py). Basis: trajectories, manuals.

Option meanings of the programs with a request row in the program catalog, by the name `normalized_program_name` gives. A program without a row sends no request only with --help or --version, and its other options change nothing.

| Key | no_request_options | offline_options | quiet_progress_options | quiet_error_options | error_showing_options | index_options | package_file_options |
|---|---|---|---|---|---|---|---|
| `curl` | `--help`, `--version`, `-V`, `-h` |  |  | `--silent`, `-s` | `--show-error`, `-S` |  |  |
| `wget` | `--help`, `--version`, `-V`, `-h` |  | `--no-verbose`, `-nv` | `--quiet`, `-q` |  |  |  |
| `pip` | `--help`, `--version`, `-V`, `-h` | `--no-index` | `--quiet`, `-q` |  |  | `--extra-index-url`, `--index-url`, `-i` | `--constraint`, `--editable`, `--requirement`, `-c`, `-e`, `-r` |
| `uv` | `--help`, `--version`, `-V`, `-h` | `--offline` | `--quiet`, `-q` |  |  | `--default-index`, `--extra-index-url`, `--index-url`, `--index`, `-i` | `--constraint`, `--editable`, `--requirement`, `-c`, `-e`, `-r` |
| `npm` | `--help`, `--version` | `--offline`, `--prefer-offline` | `--quiet` | `--silent`, `-s` |  | `--registry` |  |
| `pnpm` | `--help`, `--version` | `--offline`, `--prefer-offline` | `--quiet` | `--silent`, `-s` |  | `--registry` |  |
| `bun` | `--help`, `--version` | `--offline`, `--prefer-offline` | `--quiet` | `--silent`, `-s` |  | `--registry` |  |
| `npx` | `--help`, `--version` | `--no-install`, `--offline`, `--prefer-offline` | `--quiet` | `--silent`, `-s` |  | `--registry` |  |
| `apt` | `--help`, `--version`, `-h`, `-v` |  | `--quiet`, `-q` |  |  |  |  |
| `apt-get` | `--help`, `--version`, `-h`, `-v` |  | `--quiet`, `-q` |  |  |  |  |
| `git` | `--help`, `--version` |  | `--quiet`, `-q` |  |  |  |  |
| `nc` | `--listen`, `-h`, `-l` |  |  |  |  |  |  |

### `SCHEMELESS_URL_PROGRAMS`

Module: [`request/target_tables.py`](../src/tb_internet_use/request/target_tables.py). Basis: manuals.

Programs that read a target without a scheme as a URL, e.g. pypi.org/simple in `curl pypi.org/simple`.

`curl`, `wget`

### `PROGRAMS_WITH_HOST_AS_FIRST_TARGET`

Module: [`request/target_tables.py`](../src/tb_internet_use/request/target_tables.py). Basis: manuals.

Direct connection and name lookup programs whose first target is a host and the rest are ports or record types, e.g. `nc host 80`.

`dig`, `host`, `nc`, `nslookup`, `ping`

### `DNS_LOOKUP_PROGRAMS`

Module: [`request/target_tables.py`](../src/tb_internet_use/request/target_tables.py). Basis: manuals.

Name lookup programs whose targets can hold DNS record types and classes before the host too, e.g. MX in `dig MX a.org`.

`dig`, `host`, `nslookup`

### `DNS_RECORD_TYPES_AND_CLASSES`

Module: [`request/target_tables.py`](../src/tb_internet_use/request/target_tables.py). Basis: standards.

Common DNS record types and classes in upper case, which name no host, e.g. MX and IN in `dig IN MX a.org`.

`AAAA`, `ANY`, `AXFR`, `A`, `CAA`, `CNAME`, `IN`, `MX`, `NS`, `PTR`, `SOA`, `SRV`, `TXT`

### `PROGRAMS_WITH_HOST_AS_EVERY_TARGET`

Module: [`request/target_tables.py`](../src/tb_internet_use/request/target_tables.py). Basis: manuals.

Name lookup programs whose every target is a host, e.g. a.org and b.org in `getent hosts a.org b.org`.

`getent`

### `NETWORK_CALL_OF_LANGUAGE`

Module: [`request/code_request_tables.py`](../src/tb_internet_use/request/code_request_tables.py). Basis: trajectories, manuals.

Network calls in code, by language. One request per code text, however many of these it holds.

| Key | Value |
|---|---|
| python | `\brequests\.(?:get\|post\|put\|head\|request\|Session)\b\|\bhttpx\.(?:get\|post\|stream\|Client\|AsyncClient)\b\|\baiohttp\.ClientSession\b\|\burlopen\(\|\burlretrieve\(\|\burllib3\.PoolManager\b\|\b(?:snapshot_download\|hf_hub_download\|from_pretrained\|load_dataset)\(\|\bnltk\.download\(\|\bsocket\.(?:create_connection\|getaddrinfo\|gethostbyname)\b` |
| javascript | `\bfetch\(\|\baxios\.\|\bhttps?\.get\(` |

### `PROGRAM_RUN_BY_CODE`

Module: [`request/code_request_tables.py`](../src/tb_internet_use/request/code_request_tables.py). Basis: manuals.

A program that the code runs, e.g. pip in `subprocess.run(["pip", "install", "x"])` or `os.system("python -m pip install x")`. The name is a whole word of a string, so `.git` in `["rm", "-rf", ".git"]` names no program.

```text
\b(?:subprocess\.\w+|os\.system|os\.popen)\([^)]*?(?<=['"\s/])(pip|curl|wget|git|npm|apt-get)(?=['"\s])
```

### `HOST_NAMED_BY_CODE`

Module: [`request/code_request_tables.py`](../src/tb_internet_use/request/code_request_tables.py). Basis: trajectories.

Hosts that code names as an address tuple, e.g. ("api", 8000), or as the argument of a name lookup. The tuple's parenthesis follows no name, so call arguments such as `d.get("count", 0)` are no address.

```text
(?<![\w.\])])\(\s*['"](\w[\w.-]*)['"]\s*,\s*\d+\s*\)|(?:gethostbyname|getaddrinfo)\(\s*['"]([\w.-]+)['"]
```

### `SCHEMA_HOST_NAMES`

Module: [`request/code_request_tables.py`](../src/tb_internet_use/request/code_request_tables.py). Basis: trajectories.

Hosts of XML namespaces and schemas, whose URLs code uses as names and does not fetch unless they name a file.

`json-schema.org`, `ns.adobe.com`, `purl.org`, `schemas.microsoft.com`, `schemas.openxmlformats.org`, `schemas.xmlsoap.org`, `w3.org`, `www.w3.org`, `xmlns.com`

### `PROGRAM_OUTPUT_LINE_PATTERNS`

Module: [`observation/line_pattern_tables.py`](../src/tb_internet_use/observation/line_pattern_tables.py). Basis: trajectories.

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

Module: [`observation/line_pattern_tables.py`](../src/tb_internet_use/observation/line_pattern_tables.py). Basis: trajectories.

Web tool results are page text, so only a page that a server gave instead of the content counts, e.g. a robot check.

The first matching row decides, so the order of the rows matters.

| Row (1-based) | kind | printing_programs | is_printed_by_other_programs_too | regex |
|---|---|---|---|---|
| 1 | server_answered |  | no | `not a robot` |

## Rules inside code

These rules about programs, output, hosts and package names stay in logic modules, since they need code that a table cannot hold, e.g. a condition on an option's value, or they are a pattern of a format, e.g. a URL.

| Rule | Module | What it holds |
|---|---|---|
| `_VERSION_SUFFIX` | `shell/programs.py` | A version at the end of a program name, e.g. 3.11 in python3.11 or -12 in gcc-12. |
| `_find_exec_words` | `shell/programs.py` | Take the command of `find -exec` or `-execdir`, without its `{}` and its `;` or `+` end. |
| `_python_module_words` | `shell/programs.py` | Take the module and its arguments from `python [options] -m module ...`, empty without -m. |
| `_shell_invocation` | `shell/programs.py` | Read a shell's options up to the first operand, which is the text when -c is given, or else the file it runs. |
| `WrittenFiles.record_command` | `callrun/written_files.py` | Record what a command writes, i.e. files it redirects to, `tee` files, `sed -i` files and the destination of `cp` or `mv`. |
| `tee_file_destinations` | `callrun/output_routes.py` | List the files a `tee` command writes its input to, appending with -a, e.g. log in `tee -a log`. |
| `_command_reads` | `callrun/file_reads.py` | List the files that a reading command reads, i.e. the files it names, e.g. fetch.log in `tail -n 5 fetch.log`, and its stdin file, e.g. log in `grep x < log`. |
| `_KEY_PRESS_CHARACTERS` | `callrun/poll_links.py` | Characters that typed input holds when it only presses keys, e.g. Enter or Ctrl-C. |
| `_ENDED_STATUSES` | `callrun/poll_links.py` | Statuses of a poll that saw the polled command end. |
| `_rule_after_options` | `request/program_options.py` | Change a request rule by the curl or wget options that change what a run prints and what its exit code 0 means. |
| `_SCP_LIKE_ADDRESS` | `request/targets.py` | A remote git address without a scheme, e.g. github.com in `git@github.com:org/repo.git`. The host needs a user or a dot, so a refspec such as `main:main` in `git fetch origin main:main` is no address. |
| `_SCHEMELESS_HOST` | `request/targets.py` | A host at the start of a URL without a scheme, e.g. pypi.org in `pypi.org/simple` or localhost in `localhost:8000/x`. |
| `_PATH_OR_URL` | `request/targets.py` | Targets that name a local path, a URL or an archive instead of a package, e.g. `./dist/x.whl`, `.` or `.[dev]`. |
| `_remote_host_names` | `request/targets.py` | Find the hosts a direct connection names, e.g. host for `nc host 80` or `rsync f host:/x`, and both for `dig @8.8.8.8 a.org`. |
| `_URL` | `request/code_requests.py` | A URL with an http or https scheme, ending before a space, a quote, a backtick, an angle bracket or a closing bracket. |
| `_is_schema_name` | `request/code_requests.py` | Check whether a URL is an XML namespace or schema name rather than a file, e.g. `http://www.w3.org/2000/svg`. |
| `_TEMPLATE_CHARACTER` | `network/hosts.py` | A character that a shell or code template computes, e.g. $ in `$HOST` or { in `{host}`. |
| `_LOCAL_NAME` | `network/hosts.py` | Names that resolve to this machine or its private network, e.g. localhost or db.internal. |
| `_RESERVED_NAME` | `network/hosts.py` | Names reserved for examples and tests by RFC 2606 and RFC 6761, e.g. example.com or x.test. |
| `_ARCHIVE_FILE` | `network/package_names.py` | A wheel or source archive file or its metadata, whose name ends at the first dash before a digit, e.g. `requests-2.32.3-py3-none-any.whl.metadata`. |
| `_AFTER_NAME` | `network/package_names.py` | Where a version, an extra, an architecture or a list separator starts after a name, e.g. == in `requests==2.0`. |
| `_DASHED_VERSION_AT_END` | `network/package_names.py` | A version after a dash at the end of a name, e.g. -2.32.3 in `requests-2.32.3`. A dash before a digit inside a name stays, e.g. in the apt package `openjdk-17-jdk`. |
| `_SEPARATORS` | `network/package_names.py` | Runs of separators that package indexes treat as one, e.g. `_` and `.` in `Typing_Extensions`. |
| `_ANSI_CSI_SEQUENCE` | `observation/extract.py` | An ANSI control sequence of the CSI form, i.e. ESC and `[`, then parameter and intermediate bytes and a final byte, e.g. the color code `\x1b[32m`. |
