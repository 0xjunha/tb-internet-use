# Export catalog

The export catalog is outside knowledge for `export_rows`, kept in the three CSVs of this folder. They say what a public host serves, where a web tool sends its requests from and which registry a package command asks by default, so that `export_rows` can compute the category, the sender and whether a request is internet use. They are filled by hand, their `reviewed` column says which rows a person has reviewed, and `export_rows` reads them only through `ExportKnowledge` in [export_knowledge.py](../../export_knowledge.py).

Whether a host is public at all is no fact of this folder. It is read from the name by `parse_host_name` of `network_request/`, and only a public host is looked up here.

In each file a blank is unknown only in the column that answers the question of the file, and `ExportKnowledge` then answers with an `Unknown…` type of [model.py](../../../export/model.py). The use of such a row is counted like any other, so it leaves the list of unknown inputs. In every other column a blank fails the load where the table asks for a value.

[`public_hosts.csv`](public_hosts.csv) has one row per public host name and start of a URL path, keyed by `host_name` and `path_prefix`. Most hosts have one row with a blank `path_prefix`. A host whose paths give different services has a row for each such start and one blank row for the rest, e.g. `huggingface.co` with `/api/` for its API and a blank row for its model files. A name asked in another case finds the rows of its lower-case form, e.g. `PyPI.org` finds `pypi.org`, and no row answers for another name, e.g. `files.pythonhosted.org` for `pypi.org`.

`ExportKnowledge.public_host` picks the row whose `path_prefix` is the longest start of the path of the target URL, e.g. `/api/` for `https://huggingface.co/api/models`, also when the URL lacks its scheme as curl allows, e.g. `curl huggingface.co/api/models`, and the blank row when none is or the host is not named by the target URL, e.g. `ping pypi.org`. A path is matched in its case, from its first `/`.

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
| `package_registry_host_names` | The hosts that the program asks when no configuration names another, in lower case and split by one space, e.g. `deb.debian.org archive.ubuntu.com` for `apt-get` | Blank exactly when `package_registry` is |

The default hosts hold only where no configuration that the trajectory does not show, e.g. `pip.conf` or `PIP_INDEX_URL`, names another.

All three files end with the same three columns.

| Column | Cell | Blank |
|---|---|---|
| `checked_against` | What the row was checked against, naming the page and its section, e.g. `npm documentation v10 (docs.npmjs.com/cli/v10/using-npm/config), Config Settings, registry`, or the calls of the trajectories that were counted | Fails the load |
| `reviewed` | `yes` once a person has reviewed the row | Not reviewed yet |
| `note` | Free text, e.g. what the check does not cover | Nothing to note |

A host enters `public_hosts.csv` only when a page of the host itself, or a page of the service that runs it, says which `HostService` it gives, e.g. the GitHub documentation for `github.com`. Host names come from the trajectories, so a row holds only the host of a widely used public service, never a name that shows the content of a task. A host that serves an API, e.g. `rest.uniprot.org`, gets the service `web_api`, and a path that serves search results gets `search_engine`, e.g. `/search/` of `api.github.com`.

A row that `export_rows` cannot use raises `ValueError` when the catalog is loaded, e.g. a host name with a capital letter, a `path_prefix` that does not start with `/`, a `service` that is no `HostService`, a `sender` of `unknown` or host names without a registry. No script writes the three CSVs.
