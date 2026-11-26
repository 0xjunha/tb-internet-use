# Export catalog

The export catalog is outside knowledge for `export_rows`, kept in the four CSVs of this folder. They say what a public host serves, where a web tool sends its requests from, which registry a package command asks by default and which variables of a command may change that registry, so that `export_rows` can compute the category, the sender and whether a request is internet use. They are filled by hand, their `reviewed` column says which rows a person or three agents have reviewed, and `export_rows` reads them only through `ExportKnowledge` in [export_knowledge.py](../../export_knowledge.py).

Whether a host is public at all is no fact of this folder. It is read from the name by `parse_host_name` of `network_request/`, and only a public host is looked up here. A row of `public_hosts.csv` still decides whether a request to a dotted name that the standards do not settle counts toward the lower bound of internet use, since `treat_dotted_host_name_without_public_host_row_as_unknown_internet_use` leaves a name without any row of unknown internet use, e.g. `files.acme.org`.

In each file a blank is unknown only in the column that answers the question of the file, and `ExportKnowledge` then answers with an `Unknown…` type of [model.py](../../../export/model.py). The use of such a row is counted like any other, so it leaves the list of unknown inputs. In every other column a blank fails the load where the table asks for a value.

[`public_hosts.csv`](public_hosts.csv) has one row per public host name and start of a URL path, keyed by `host_name` and `path_prefix`. Most hosts have one row with a blank `path_prefix`. A host whose paths give different services has a row for each such start and one blank row for the rest, e.g. `huggingface.co` with `/api/` for its API and a blank row for its model files. A name asked in another case finds the rows of its lower-case form, e.g. `PyPI.org` finds `pypi.org`, and no row answers for another name, e.g. `files.pythonhosted.org` for `pypi.org`.

`ExportKnowledge.public_host` picks the row whose `path_prefix` is the longest start of the path of the target URL, e.g. `/api/` for `https://huggingface.co/api/models`, also when the URL lacks its scheme as curl allows, e.g. `curl huggingface.co/api/models`, and the blank row when none is or the host is not named by the target URL, e.g. `ping pypi.org`. A `path_prefix` is matched as a plain start of the path, in its case and from its first `/`, so it should end at a segment boundary, e.g. `/api/`, since `/api` would also match `/apis/x`.

| Column | Cell | Blank |
|---|---|---|
| `host_name` | The host name in lower case, e.g. `pypi.org` | Fails the load |
| `path_prefix` | The start of the URL paths that the row covers, from the `/` after the host, e.g. `/api/` | Every other path of the host |
| `service` | A `HostService` value, e.g. `package_registry`, `code_hosting`, `model_hub`, `search_engine`, `web_api`, `file_hosting` or `documentation` | Unknown |
| `package_registry` | The registry name when `service` is `package_registry`, e.g. `pypi` | Required for a registry, and blank for any other service |

[`harness_web_tools.csv`](harness_web_tools.csv) has one row per harness tool that can make web requests, keyed by `harness` and `tool` as `harness_tools.csv` of `tool_call/` names them. A web step in a tool script is found by the tool of the script, e.g. `(codex, exec)`.

| Column | Cell | Blank |
|---|---|---|
| `harness`, `tool` | The harness and tool name, e.g. `codex` and `web_search_call` | Fails the load |
| `sender` | Where the requests of the tool leave from, as a `NetworkRequestSender` value other than `unknown`, e.g. `provider_server` | Unknown |

[`program_package_registries.csv`](program_package_registries.csv) has one row per program and subcommand that installs or looks up packages, keyed by `program_name` and `subcommand` as `program_behaviors.csv` of `expanded_tool_call/` names them, e.g. `(uv, pip install)`. Only the row of the very program and subcommand of a command answers.

| Column | Cell | Blank |
|---|---|---|
| `program_name` | The program name of the row of `program_behaviors.csv`, e.g. `pip` | Fails the load |
| `subcommand` | The subcommand words split by one space, e.g. `index versions` | The program without subcommand words, e.g. `npx` |
| `package_registry` | The registry name, e.g. `pypi` | Unknown, and then `package_registry_host_names` is blank too |
| `package_registry_host_names` | The hosts that the program asks when no configuration names another, in lower case and split by one space, without the hosts of the files that the answers link to, e.g. `files.pythonhosted.org` of pip, e.g. `deb.debian.org archive.ubuntu.com security.ubuntu.com` for `apt-get` | Blank exactly when `package_registry` is |

The default hosts hold only where no configuration that the trajectory does not show, e.g. `pip.conf` or an exported `PIP_INDEX_URL`, names another.

[`program_variables.csv`](program_variables.csv) has one row per program, subcommand and variable that a `NAME=value` before the command name gives the program, keyed by `program_name`, `subcommand` and `variable_name`, e.g. `(go, build, GOPROXY)` for `GOPROXY=https://a.org go build`. `export_rows` asks it only for a command that names no host and whose program and subcommand have a registry in `program_package_registries.csv`, and only the row of the very program, subcommand and variable answers. A variable with `yes` or a blank `changes_package_registry` makes `treat_request_without_host_name_as_sent_to_default_registry_host` give its command no default host. A variable without a row is an unknown input, which `treat_variable_without_program_variable_row_as_not_changing_package_registry` takes as one that does not change the registry, as a variable with `no` does, e.g. `PORT` of `PORT=3000 npx x`.

| Column | Cell | Blank |
|---|---|---|
| `program_name`, `subcommand` | As in `program_package_registries.csv`, e.g. `uv` and `pip install` | `program_name` fails the load, `subcommand` is the program without subcommand words |
| `variable_name` | The name as the command writes it, in its case, e.g. `DEBIAN_FRONTEND` | Fails the load |
| `changes_package_registry` | `yes` when the program reads the variable as a setting of where its package requests go or whether they go out, e.g. another index, a proxy or a mode without the network. `no` when the documentation of the program shows that it reads the variable for something else, e.g. where it installs, or not at all, e.g. `DEBIAN_FRONTEND` of `apt-get install` | Unknown |

A variable enters `program_variables.csv` only when the documentation of the program, or of what reads the variable, names it. A variable that only the task reads, e.g. a port for a server of the task, gets no row, since its name could show the content of a task, and its command gets the default hosts.

Unlike the other catalogs, `program_variables.csv` holds the documented variables of each program and subcommand with a registry whether or not a trajectory sets them, i.e. those that set or add an index, a registry or a mirror, a proxy, a mode without the network or a configuration file, e.g. `PIP_INDEX_URL`, `UV_OFFLINE`, `npm_config_registry`, `GONOPROXY` or `HTTPS_PROXY`. A variable without a row gives the default hosts, so a missing row of such a variable would put a request to a local index in the lower bound. A row is `yes` when the documentation settles that the variable changes where the requests go or whether they go out, and blank when it does not, e.g. a variable that names a configuration file the command does not show, such as `PIP_CONFIG_FILE`, or a form of a proxy variable that the program does not document, such as `http_proxy` of uv. A variable that carries options of which only some change the requests gets `yes`, e.g. `GOFLAGS` of `go build` or `JAVA_OPTS` of `sbt`.

A variable name is matched in its case, as shells and programs tell names apart by case. So a program that reads a name in either case has a row for each case it documents, e.g. `npm_config_registry` and `NPM_CONFIG_REGISTRY` of npm, or `http_proxy` and `HTTP_PROXY` of pip, and a case that no row holds, e.g. `Npm_Config_Registry`, gets the default hosts.

All four files end with the same three columns.

| Column | Cell | Blank |
|---|---|---|
| `checked_against` | What the row was checked against, naming the page and its section, e.g. `npm documentation v10 (docs.npmjs.com/cli/v10/using-npm/config), Config Settings, registry`, or the calls of the trajectories that were counted | Fails the load |
| `reviewed` | `yes` once a person has reviewed the row, `agents` once three agents each checked the row against a primary source and all found every value right, two of them seeing the values and one filling them without seeing them | Not reviewed yet |
| `note` | Free text, e.g. what the check does not cover | Nothing to note |

A host enters `public_hosts.csv` only when a page of the host itself, or a page of the service that runs it, says which `HostService` it gives, e.g. the GitHub documentation for `github.com`. Host names come from the trajectories, so a row holds only the host of a widely used public service. Such a host gets a row even when it occurs in the trajectories of one task only, while a host that is no such service gets none, since its name could show the content of a task. A host that serves an API, e.g. `rest.uniprot.org`, gets the service `web_api`, also when the API searches one database, e.g. `search.rcsb.org`, and a path that serves search results gets `search_engine`, e.g. `/search/` of `api.github.com`.

A row that `export_rows` cannot use raises `ValueError` when the catalog is loaded, e.g. a host name with a capital letter, a `path_prefix` that does not start with `/`, a `service` that is no `HostService`, a `sender` of `unknown`, host names without a registry or a `changes_package_registry` other than `yes`, `no` or blank. No script writes the four CSVs.
