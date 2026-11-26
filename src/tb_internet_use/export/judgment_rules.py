"""Decide what the facts of a request and the outside knowledge do not settle about its row, one named rule per situation, e.g. the category of `curl -s -o /dev/null u` or which parts of a URL in a row are hidden as credentials.

Each rule is a judgment, not a reading of the trajectory or a fact of a catalog, so it lives here where it can be found and changed.
For example, the URL `https://a.org/x?page=2&token=abc` shows no rule of which query values are secret, and only a rule says that `export_rows` hides them all.

Each rule adds one to `use_counts` under its own function name every time it decides something, so that audits can show how much of the output leans on each rule.
The counts are for tracking and never go into a row.

A rule is provisional until the user decides it. The last paragraph of each docstring marks it `Provisional.` or `Decided.`, e.g. `treat_single_label_host_name_as_not_internet_use` is decided.
"""

from collections import Counter
from collections.abc import Mapping, Sequence

from tb_internet_use.export.model import (
    NetworkRequestRow,
    PackageRegistry,
    UnknownChangesPackageRegistry,
    UnknownPackageRegistry,
    UnknownProgramVariable,
)
from tb_internet_use.network_request.model import (
    NetworkRequest,
    UnknownNetworkRequestTarget,
    UnknownNetworkRequestTargetReason,
)
from tb_internet_use.network_request_result.model import NetworkRequestResult


def treat_url_query_value_and_fragment_as_credential(
    text: str, *, use_counts: Counter[str]
) -> bool:
    """Treat every query value and the fragment of each URL in a text of a row as a credential, whatever the name of the value, e.g. both values and the fragment of `https://a.org/x?token=abc&page=2#k`.

    A URL may carry a token in any query value or in its fragment, and its text does not say which value is secret.
    `redact_credentials` asks it once for a text with a query value or a fragment in a piece that holds `://`.
    On `True` every such value and fragment is replaced by `REDACTED`. On `False` they stay as written.
    A use is such a text.
    A URL that holds whitespace keeps the text after the whitespace as written, e.g. `token=abc` in `https://a.org/x?q=hello world&token=abc`, since `redact_credentials` reads each piece between whitespace on its own.

    Provisional. No earlier code chose, and hiding every value is the choice that hides the most. The other choice hides only the values whose name a catalog lists as a credential.
    """
    use_counts[treat_url_query_value_and_fragment_as_credential.__name__] += 1
    return True


def treat_repository_request_for_no_content_as_other_web(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request to a repository that asks for no content in the other web category, e.g. `git push origin main`.

    Such a request sends to a repository and receives nothing, so it is neither a content fetch nor a plain check that a host answers.
    `export_network_request_category` asks it for a request whose target kind is `REPOSITORY_URL` and whose content destination is `NoContentRequested`.
    On `True` the category is `OTHER_WEB`. On `False` it is `CONNECTIVITY_CHECK`, as for any other request that asks for no content.
    A use is such a request.

    Provisional. No earlier code chose, and other web claims no replacement. The other choices are a connectivity check or a remote API call.
    """
    use_counts[treat_repository_request_for_no_content_as_other_web.__name__] += 1
    return True


def treat_discarded_content_as_connectivity_check(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request whose content is thrown away in the connectivity check category, e.g. `curl -s -o /dev/null -w '%{http_code}' u`.

    Throwing the content away keeps only whether and how the host answered, e.g. its status code, but the words do not say that the agent wanted no more.
    `export_network_request_category` asks it for a request that asks for content and whose content destination is `ContentDiscarded` and whose target kind is `URL`, `REPOSITORY_URL` or `HOST`.
    On `True` the category is `CONNECTIVITY_CHECK`. On `False` it is `OTHER_WEB`.
    A use is such a request.
    The category never changes the result of the request, so a discarded page still counts as received when its result says so.

    Decided. The user decided on 2026-11-21 that such a request is a connectivity check, since what it keeps of the answer is only that the host answered.
    """
    use_counts[treat_discarded_content_as_connectivity_check.__name__] += 1
    return True


def treat_host_target_that_may_receive_content_as_other_web(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request for a host alone that may receive content in the other web category, e.g. `socket.create_connection(("api", 8000))` in code.

    A connection to a host and a port may only check that it answers or may carry any protocol, and the words do not say which.
    `export_network_request_category` asks it for a request whose target kind is `HOST` and whose content destination is neither `NoContentRequested` nor `ContentDiscarded`.
    On `True` the category is `OTHER_WEB`. On `False` it is `CONNECTIVITY_CHECK`.
    A use is such a request.

    Provisional. No earlier code chose, and other web claims no replacement.
    """
    use_counts[treat_host_target_that_may_receive_content_as_other_web.__name__] += 1
    return True


def treat_url_request_without_path_or_query_to_package_registry_or_search_engine_host_as_connectivity_check(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request for a URL without a path or a query to a package registry or search engine host in the connectivity check category, e.g. `requests.get("https://pypi.org")` or `urllib.request.urlopen("https://www.google.com/")` in code.

    The first page of a registry or a search engine holds no package and no search results, so asking for it shows only whether the host answers, as code does that checks whether the network works before it installs or searches.
    `export_network_request_category` asks it for a request from a command or code whose target kind is `URL`, that asks for content it does not throw away, one of whose public hosts the host catalog gives the service `PACKAGE_REGISTRY` or `SEARCH_ENGINE`, and whose target URL `parse_url_path` reads with the path `/` or none and `parse_url_query` with no query.
    A target whose URL cannot be read is not asked about, e.g. `requests.get(url)` whose `url` gets its value at run time, and neither is a URL with a query alone, e.g. `https://duckduckgo.com/?q=x`, which asks a search.
    On `True` the category is `CONNECTIVITY_CHECK`. On `False` it is the category of the conditions after it, i.e. `PACKAGE` or `SEARCH` by the service of the host.
    A use is such a request.

    Decided. The user decided on 2026-11-21 that such a URL is a connectivity check, since a request that asks a registry or a search engine for nothing in particular only checks that the internet answers.
    """
    use_counts[
        treat_url_request_without_path_or_query_to_package_registry_or_search_engine_host_as_connectivity_check.__name__
    ] += 1
    return True


def treat_url_request_to_package_registry_host_as_package(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request for a URL one of whose hosts is a package registry in the package category, e.g. `curl https://pypi.org/pypi/x/json` or `wget https://files.pythonhosted.org/.../x.whl`.

    A registry host gives packages and their metadata, also when no installer asks it, but a page of it may only be read as documentation, e.g. `curl https://pypi.org/project/requests/`, and the words do not say which.
    `export_network_request_category` asks it for a request from a command or code whose target kind is `URL`, that asks for content it does not throw away, and one of whose public hosts the host catalog gives the service `PACKAGE_REGISTRY`, unless `treat_url_request_without_path_or_query_to_package_registry_or_search_engine_host_as_connectivity_check` took it.
    On `True` the category is `PACKAGE`. On `False` it is the category of the conditions after it, e.g. `CONTENT_FETCH` for saved content.
    A use is such a request.

    Decided. The user decided on 2026-11-21 that a URL sent to a registry host is a package, since the replacement when the internet is off is the mirror of that registry.
    """
    use_counts[treat_url_request_to_package_registry_host_as_package.__name__] += 1
    return True


def treat_url_request_to_search_engine_host_as_search(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request for a URL one of whose hosts is a search engine in the search category, e.g. `curl 'https://html.duckduckgo.com/html?q=x'` or `curl 'https://api.github.com/search/code?q=x'`.

    A command can ask a search engine for its results or for any other page of it, and the words alone do not say which.
    `export_network_request_category` asks it for a request from a command or code whose target kind is `URL`, that asks for content it does not throw away, none of whose public hosts is a package registry, or whose registry host `treat_url_request_to_package_registry_host_as_package` did not take, and one of which the host catalog gives the service `SEARCH_ENGINE` for the path of the target, unless `treat_url_request_without_path_or_query_to_package_registry_or_search_engine_host_as_connectivity_check` took it.
    On `True` the category is `SEARCH`. On `False` it is the category of the conditions after it.
    A use is such a request.

    Decided. The user decided on 2026-11-21 that a URL sent to a search engine host is a search, also the search paths of an API host, e.g. `/search/` of `api.github.com`.
    """
    use_counts[treat_url_request_to_search_engine_host_as_search.__name__] += 1
    return True


def treat_saved_content_from_unrecognized_url_as_content_fetch(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request for a URL whose content is saved and whose hosts give no known service in the content fetch category, e.g. `curl -o x https://a.org/x`.

    Saving the content shows that the agent wanted the file or page itself, but neither the host nor the words say whether it is data, a document or an answer of an API.
    `export_network_request_category` asks it for a request from a command or code whose target kind is `URL`, whose content destination is `ContentSaved` and that no service of its public hosts puts in a category, e.g. for `a.org` without a row of the host catalog.
    On `True` the category is `CONTENT_FETCH`. On `False` it is `OTHER_WEB`.
    A use is such a request.

    Decided. The user decided on 2026-11-21 that a saved file without other facts is taken as fetched content, whose replacement is to put the file in the image.
    """
    use_counts[treat_saved_content_from_unrecognized_url_as_content_fetch.__name__] += 1
    return True


def treat_web_tool_request_without_url_as_internet_use(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Count a web tool request without a URL as internet use, e.g. a harness web search with only a query such as `how to x?`, or a web fetch called without a URL.

    A web search tool sends its query to a search service that the trajectory does not name, and a fetch without a URL names no host either, so the trajectory does not say where the request went. The provider of the tool gets it in either case.
    `export_network_request_row` asks it for each request without a host name whose source is a web tool and whose target is no URL.
    On `True` `is_internet_use` is True. On `False` it is None, so the request counts only toward the upper bound.
    A use is such a request.

    Provisional. No earlier code chose. A web tool is made to reach the internet, and the other choice would leave every web search unknown.
    """
    use_counts[treat_web_tool_request_without_url_as_internet_use.__name__] += 1
    return True


def treat_web_tool_url_without_host_name_as_unknown_internet_use(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Leave the internet use of a web tool request unknown when its target is a URL whose host was not read, e.g. a fetch of `file:///app/x.html`, of `localhost:3000/x` or of `a.org/x` without a scheme.

    Such a URL may name a local file or a local host as well as a public one, and the trajectory does not say which.
    `export_network_request_row` asks it for each request without a host name whose source is a web tool and whose target is a URL.
    On `True` `is_internet_use` is None, so the request counts only toward the upper bound. On `False` it is True, as for a web search.
    A use is such a request.

    Provisional. Until the review of 2026-11-24 such a request was counted as internet use with a web search. The review recommended to leave it unknown, since the URLs whose host was not read mix local files and local hosts with public ones, and the user has not yet confirmed it.
    """
    use_counts[
        treat_web_tool_url_without_host_name_as_unknown_internet_use.__name__
    ] += 1
    return True


def treat_variable_without_program_variable_row_as_not_changing_package_registry(
    network_request: NetworkRequest, variable_name: str, *, use_counts: Counter[str]
) -> bool:
    """Take a variable without a row of `program_variables.csv` that a `NAME=value` before the command name gives a program with a default registry as one that does not change that registry, e.g. `PORT` of `PORT=3000 npx x`.

    Nearly all such names are read by the task's own programs, e.g. `PORT` or `AUDIT_URL` before `npx` and `ITERS` or `MODE` before `sbt`, so no documentation of the program names them and no catalog can list them. The catalog holds every variable that the documentation of the program names as a setting of its index, registry, proxy, offline mode or configuration file, whether or not a trajectory sets it, in each case of the name that the documentation gives, e.g. `PIP_INDEX_URL` of `pip install` or both `npm_config_registry` and `NPM_CONFIG_REGISTRY` of `npx`.
    `export_network_request_row` asks it once for each name of a request without a host name whose program and subcommand have a `PackageRegistry`, when `ExportKnowledge.changes_package_registry` answers `UnknownProgramVariable` for the name.
    On `True` the answer for the name is False, so `treat_request_without_host_name_as_sent_to_default_registry_host` reads it as it reads `DEBIAN_FRONTEND` of `apt-get install`. On `False` the answer stays `UnknownProgramVariable`, and that rule gives the command no host.
    A row whose `changes_package_registry` is blank is not asked about, since the documentation names its variable without settling the effect, e.g. `GOPATH` of `go build`, whose command then gets no host.
    A use is such a name of a request.

    Decided. The user decided on 2026-11-25 that a variable without a row does not change the registry, since such names are the task's own and cannot be listed, while the variables that programs read for their registry are in the catalog. Before, 204 such names in 3,104 lookups of the 21,450 Terminal-Bench 4.1 trials gave their commands no host.
    """
    use_counts[
        treat_variable_without_program_variable_row_as_not_changing_package_registry.__name__
    ] += 1
    return True


def treat_request_without_host_name_as_sent_to_default_registry_host(
    network_request: NetworkRequest,
    package_registry: PackageRegistry | UnknownPackageRegistry | None,
    changes_package_registry_by_variable_name: Mapping[
        str, bool | UnknownChangesPackageRegistry | UnknownProgramVariable
    ],
    *,
    use_counts: Counter[str],
) -> tuple[str, ...]:
    """Give the hosts that a request whose words name no host is taken to be sent to, i.e. the default registry hosts of its program and subcommand, e.g. `pypi.org` for `pip install requests`.

    A program that installs packages usually names no host, and whether the request went out at all is decided from its output lines when results are decided.
    `export_network_request_row` asks it for each request without a host name whose source is no web tool. It gives the hosts the same reading as hosts that the words name.
    `package_registry` is the answer of `ExportKnowledge.package_registry`, or None for a request that `ExportKnowledge` is not asked about, e.g. `git fetch origin`.
    `changes_package_registry_by_variable_name` holds the answer of `ExportKnowledge.changes_package_registry` for each variable that a `NAME=value` before the command name gives the program, e.g. for `DEBIAN_FRONTEND` of `DEBIAN_FRONTEND=noninteractive apt-get install -y x`, where False stands for an `UnknownProgramVariable` that `treat_variable_without_program_variable_row_as_not_changing_package_registry` took as one that does not change the registry, e.g. for `PORT` of `PORT=3000 npx x`. It is empty for a request with no `PackageRegistry` and for a command without such a `NAME=value`.
    It gives the host names of a `PackageRegistry`, e.g. `deb.debian.org archive.ubuntu.com security.ubuntu.com` for `apt-get update`, also when a file names the targets, e.g. `pip install -r reqs.txt`, and when every such variable has the answer False, e.g. `DEBIAN_FRONTEND` for `apt-get install`.
    It gives no host when a variable has the answer True, an `UnknownChangesPackageRegistry` or an `UnknownProgramVariable`, since the command itself then shows a setting that may send the request to another host or keep it from going out, e.g. `GOPROXY=http://localhost:3000 go build` for a local module proxy or `GOPATH=/x go build`, whose row is blank. A `NAME=value` that is a word of another program, e.g. of env in `env PIP_INDEX_URL=… pip install x`, and one before a command that runs the text of the request, e.g. `PIP_INDEX_URL=… bash setup.sh`, are not read.
    It gives no host for a target that is a local path, e.g. `pip install -e .`, since a local project may or may not ask a registry for what it depends on. It gives none either for `UnknownPackageRegistry` or None. Without a host the request's internet use is not known.
    The other choices are no host for every request, which leaves all of them unknown, the registry hosts for a local path too, the registry hosts whatever the variables, or the host that a variable names, e.g. `localhost` for the local module proxy above, which needs a fact of how each program reads the value of each variable.
    A use is such a request.

    Provisional. The user chose on 2026-11-18 to send a request of a program and subcommand with a registry row to the registry hosts. Leaving a local path, a request without a row and a request with a variable that may change the registry unknown claims least, and keeps a request to a local index out of the lower bound.
    """
    use_counts[
        treat_request_without_host_name_as_sent_to_default_registry_host.__name__
    ] += 1
    target = network_request.target
    if (
        isinstance(target, UnknownNetworkRequestTarget)
        and target.reason == UnknownNetworkRequestTargetReason.LOCAL_PATH
    ):
        return ()
    if not isinstance(package_registry, PackageRegistry):
        return ()
    if any(
        isinstance(
            changes_package_registry,
            UnknownChangesPackageRegistry | UnknownProgramVariable,
        )
        or changes_package_registry
        for changes_package_registry in changes_package_registry_by_variable_name.values()
    ):
        return ()
    return package_registry.host_names


def treat_dotted_host_name_without_public_host_row_as_unknown_internet_use(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Leave the internet use of a request unknown when a host name of it has a dot and no row of the public host catalog, and no host of it is a public address or has such a row, e.g. `curl https://files.acme.org/x`.

    The standards do not settle whether such a name is public, and `treat_dotted_host_name_as_public` reads it as public only so that a URL with it gives a request. It may also be the name of a service inside the task's network, which the trajectory alone does not tell apart. A row of `public_hosts.csv` names a widely used public service, e.g. `pypi.org`.
    `export_network_request_row` asks it for a request with such a host name, among the hosts that its words name, before the rules on templated, reserved, local and single-label names, so that such a request never counts as no internet use. A host that a request is taken to be sent to comes from the registry catalog and counts as listed, e.g. `pypi.org` for `pip install requests`.
    On `True` `is_internet_use` is None, so the request counts only toward the upper bound. On `False` it is True, as for a public host with a row.
    A use is such a request.

    Provisional. The earlier code counted every dotted name that is no local or reserved name as public, so a request to a service inside the task's network counted toward the lower bound. The review of 2026-11-24 recommended to count toward the lower bound only the hosts with a row of `public_hosts.csv`, which may lower that bound much, and the user has not yet confirmed it.
    """
    use_counts[
        treat_dotted_host_name_without_public_host_row_as_unknown_internet_use.__name__
    ] += 1
    return True


def treat_templated_host_name_as_unknown_internet_use(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Leave the internet use of a request unknown when a host name of it holds a template and none is public, e.g. `mytool https://$HOST/x`.

    `$HOST` gets its value when the command runs, and the trajectory does not show the value.
    `export_network_request_row` asks it for a request with such a host name and no public host, among the hosts that its words name or that it is taken to be sent to.
    On `True` `is_internet_use` is None, so the request counts only toward the upper bound. On `False` it is False, as for `localhost`, and the request counts in no bound.
    A use is such a request.

    Provisional. No earlier code chose, and unknown claims least.
    """
    use_counts[treat_templated_host_name_as_unknown_internet_use.__name__] += 1
    return True


def treat_host_name_with_empty_label_as_unknown_internet_use(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Leave the internet use of a request unknown when a host name of it has an empty label and none is public or templated, e.g. `curl ...` or `https://../x` in code.

    RFC 1035 allows an empty label only for the root, so no resolver finds such a name on the internet, but the text may stand for a host that the trajectory does not show.
    `export_network_request_row` asks it for a request with such a host name, among the hosts that its words name or that it is taken to be sent to.
    On `True` `is_internet_use` is None, so the request counts only toward the upper bound. On `False` it is False and the request counts in no bound.
    A use is such a request.

    Decided. The user decided on 2026-11-21 that such a name is never a public host and counts only toward the upper bound.
    """
    use_counts[treat_host_name_with_empty_label_as_unknown_internet_use.__name__] += 1
    return True


def treat_single_label_host_name_as_not_internet_use(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Count a request with a host name without a dot, and none public, templated, with an empty label or reserved, as no internet use, also when local host names sit beside it, e.g. `curl http://db:8000/x` or `socket.create_connection(("api", 8000))` in code.

    A name without a dot does not resolve on public DNS, only inside a container network or through `/etc/hosts`, so the request goes to a service inside the task environment, which turning the internet off would not block.
    `export_network_request_row` asks it for a request from a command or code with such a host name and no host that is public, templated or reserved or has an empty label, among the hosts that its words name or that it is taken to be sent to.
    A web tool request with such a host name is left to `treat_local_or_single_label_host_name_of_web_tool_as_unknown_internet_use`, since the name then resolves where the web tool sends from.
    On `True` `is_internet_use` is False, as for `localhost`, and the request counts in no bound. On `False` it is None, so the request counts only toward the upper bound.
    A use is such a request.

    Decided. The user decided on 2026-11-19 that a name without a dot is read as a service inside the task environment. Some such names in code are no hosts at all but test strings, which the choice also counts as no internet use.
    """
    use_counts[treat_single_label_host_name_as_not_internet_use.__name__] += 1
    return True


def treat_reserved_host_name_as_unknown_internet_use(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Leave the internet use of a request unknown when a host name of it is reserved for examples and tests and none is public, templated or with an empty label, e.g. `curl https://example.com/`.

    A reserved name resolves nowhere by the standards, but the task environment may still map it to a service of its own.
    `export_network_request_row` asks it for a request with such a host name, among the hosts that its words name or that it is taken to be sent to.
    On `True` `is_internet_use` is None, so the request counts only toward the upper bound. On `False` it is False and the request counts in no bound.
    Counting such a request as internet use would need a rule of another form, since neither answer gives True.
    A use is such a request.

    Provisional. No earlier code chose, and unknown claims least.
    """
    use_counts[treat_reserved_host_name_as_unknown_internet_use.__name__] += 1
    return True


def treat_local_or_single_label_host_name_of_web_tool_as_unknown_internet_use(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Leave the internet use of a web tool request unknown when all its host names are local or have no dot, e.g. a fetch tool that runs on the provider's server reading `http://localhost:3000/` or `http://db:8000/`.

    A local name, and a name without a dot, means the machine that sends the request or its network, and a web tool may send from the harness process or the provider's server instead of the task environment.
    `export_network_request_row` asks it for a request from a web tool whose host names are all local or have no dot.
    On `True` `is_internet_use` is None, so the request counts only toward the upper bound. On `False` it is False, as for a command that asks `localhost`.
    A use is such a request.

    Provisional. No earlier code chose, and unknown claims least.
    """
    use_counts[
        treat_local_or_single_label_host_name_of_web_tool_as_unknown_internet_use.__name__
    ] += 1
    return True


def treat_assumed_not_needed_result_as_upper_bound_only(
    network_request_result: NetworkRequestResult, *, use_counts: Counter[str]
) -> bool:
    """Count a request whose result is assumed to be not needed only toward the upper bound of the trials that have a request, e.g. a `pip install x` that shares a `Requirement already satisfied` line with another request.

    A request that did not need to be sent is left out of the share of trials that have a request, but an assumed result may belong to the other request.
    `export_network_request_row` asks it for a request that may be internet use whose result is `NOT_NEEDED` and `ASSUMED`.
    On `True` the request bound is `UPPER_ONLY`. On `False` it is `NEITHER`, as for a confirmed `NOT_NEEDED`.
    A use is such a request.

    Provisional. No earlier code chose. The upper bound includes what is assumed, and the lower bound stays true either way.
    """
    use_counts[treat_assumed_not_needed_result_as_upper_bound_only.__name__] += 1
    return True


def treat_assumed_failure_as_possibly_received(
    network_request_result: NetworkRequestResult, *, use_counts: Counter[str]
) -> bool:
    """Count a request whose failure is assumed toward the upper bound of the trials that received something, e.g. two `curl` commands that share one error line.

    An error line shared by two requests may belong to only one of them, so the other may have received its content.
    `export_network_request_row` asks it for a request that counts in some request bound whose result is `FAILED` and `ASSUMED`.
    On `True` the received bound is `UPPER_ONLY`. On `False` it is `NEITHER`, as for a confirmed failure.
    A use is such a request.

    Provisional. No earlier code chose. The upper bound includes what is assumed, and the lower bound stays true either way.
    """
    use_counts[treat_assumed_failure_as_possibly_received.__name__] += 1
    return True


def treat_trial_with_success_line_shared_by_confirmed_requests_as_received(
    network_request_rows: Sequence[NetworkRequestRow], *, use_counts: Counter[str]
) -> bool:
    """Count the trial in the lower bound of received for a category and sender when an output line of success that several of its requests share shows that one of them received, e.g. one `Fetched 10 kB in 1s` under `apt-get install -y a b`, where each request alone stays assumed.

    Which owner of the line printed it is not known, but whichever did is a confirmed request of this category and sender that received, so what is unknown is which request received, not whether one did. The measure counts trials, not requests.
    A line counts the trial in the lower bound of received only when every result that holds it as a shared output line has the same category and sender, is in the lower bound of requests, has the result view `RECEIVED` and is assumed for shared output lines alone with this very line among them. An owner that is an uncertain request, of another category or sender, not a success, assumed for another line alone or assumed for another reason, e.g. a judgment rule or a run that is not read beside it, breaks it, since the line may be that owner's.
    `mark_network_request_rows_among_success_line_owners` asks it, for `export_rows`, once for each category and sender of a trial with such a line in which no row is in the lower bound of received by its own result, giving the rows of the owners of those lines. Where a row is, the bound cannot rise and the rule is not asked.
    On `True` those rows are among success line owners one of which received and the trial counts in the lower bound of received for the category and sender, while the received bound of each row stays as its own result gives it. On `False` the trial counts as its rows alone give it, i.e. only in the upper bound.
    A use is such a category and sender of a trial.

    Decided. The user decided on 2026-11-19 that the trial counts in the lower bound of received, since the unit of the measure is the trial.
    """
    use_counts[
        treat_trial_with_success_line_shared_by_confirmed_requests_as_received.__name__
    ] += 1
    return True


def treat_request_of_unknown_sender_as_possibly_from_task_environment(
    network_request_row: NetworkRequestRow, *, use_counts: Counter[str]
) -> bool:
    """Count a request whose sender is not known toward the upper bounds of the trial row, e.g. a page that a web tool without a row of the web tool catalog read.

    The bounds of a trial row are about what the task environment sent, and a sender that is not known is one of the task environment, the harness process and the provider server.
    `export_trial_row` asks it for each request row whose sender is `UNKNOWN`.
    On `True` the row counts with its own bounds, but a `LOWER_AND_UPPER` counts as `UPPER_ONLY`. On `False` the row counts in no bound of the trial row, as for a row from the provider server.
    A use is such a request row.

    Provisional. No earlier code chose. Leaving the row out would read it as not sent from the task environment and lower the upper bound, while counting it in the lower bound would make that bound wrong.
    """
    use_counts[
        treat_request_of_unknown_sender_as_possibly_from_task_environment.__name__
    ] += 1
    return True
