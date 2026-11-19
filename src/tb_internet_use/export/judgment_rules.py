"""Decide what the facts of a request and the outside knowledge do not settle about its row, one named rule per situation, e.g. the category of `curl u | wc -c` or which parts of a URL in a row are hidden as credentials.

Each rule is a judgment, not a reading of the trajectory or a fact of a catalog, so it lives here where it can be found and changed.
For example, the URL `https://a.org/x?page=2&token=abc` shows no rule of which query values are secret, and only a rule says that `export_rows` hides them all.

Each rule adds one to `use_counts` under its own function name every time it decides something, so that audits can show how much of the output leans on each rule.
The counts are for tracking and never go into a row.

A rule is provisional until the user decides it. The last paragraph of each docstring marks it `Provisional.` or `Decided.`, e.g. `treat_single_label_host_name_as_not_internet_use` is decided.
"""

from collections import Counter
from collections.abc import Sequence

from tb_internet_use.export.model import (
    NetworkRequestRow,
    PackageRegistry,
    UnknownPackageRegistry,
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

    Such a request sends to a repository and receives nothing, so it is neither a fetched file nor a plain check that a host answers.
    `export_network_request_category` asks it for a request whose target kind is `REPOSITORY_URL` and whose content destination is `NoContentRequested`.
    On `True` the category is `OTHER_WEB`. On `False` it is `CONNECTIVITY_CHECK`, as for any other request that asks for no content.
    A use is such a request.

    Provisional. No earlier code chose, and other web claims no replacement. The other choices are a connectivity check or a remote API call.
    """
    use_counts[treat_repository_request_for_no_content_as_other_web.__name__] += 1
    return True


def treat_discarded_content_as_other_web(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request whose content is thrown away in the other web category, e.g. `curl -s -o /dev/null -w '%{http_code}' u`.

    Throwing the content away often checks only that a host answers, but the words do not say so.
    `export_network_request_category` asks it for a request that asks for content and whose content destination is `ContentDiscarded` and whose target kind is `URL`, `REPOSITORY_URL` or `HOST`.
    On `True` the category is `OTHER_WEB`. On `False` it is `CONNECTIVITY_CHECK`.
    A use is such a request.

    Provisional. No earlier code chose, and other web claims no replacement.
    """
    use_counts[treat_discarded_content_as_other_web.__name__] += 1
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


def treat_saved_content_from_package_registry_host_as_fetched_file(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request whose content from a package registry host is saved in the fetched file category, e.g. `wget https://pypi.org/.../x.whl`.

    Saving a file from a registry may get a package without its installer, and the words do not say whether a mirror of the registry would replace it.
    `export_network_request_category` asks it for a request for a URL or a repository whose content is saved and one of whose public hosts the host catalog gives the service `PACKAGE_REGISTRY`.
    It is also asked for such a request whose content goes to a command that shows none of it, when `treat_content_piped_to_consuming_command_as_other_web` answers `False`.
    On `True` the category is `FETCHED_FILE`, as for any saved content. On `False` it is `PACKAGE`.
    A use is such a request.

    Provisional. No earlier code chose. It follows the category of saved content, whose replacement is to put the file in the image.
    """
    use_counts[
        treat_saved_content_from_package_registry_host_as_fetched_file.__name__
    ] += 1
    return True


def treat_content_piped_to_consuming_command_as_other_web(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request whose content goes to a command that shows none of it in the other web category, e.g. `curl u | wc -c` or `curl u | md5sum`.

    Such a command uses the content without showing it, much as saving it would, but the words do not say how.
    `export_network_request_category` asks it for a request for a URL or a repository whose content goes to a command with `OutputVisibility.NONE` at the end.
    On `True` the category is `OTHER_WEB`. On `False` it is the category that the request would get if its content were saved.
    A use is such a request.

    Provisional. No earlier code chose, and other web claims no replacement.
    """
    use_counts[treat_content_piped_to_consuming_command_as_other_web.__name__] += 1
    return True


def treat_content_piped_to_showing_command_as_other_web(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request whose content goes to a command that shows all or part of it in the other web category, e.g. `curl u | head` or `curl u | grep x`.

    Such a command may show the content whole or only some lines of it, so whether the agent read it as a page is not known.
    `export_network_request_category` asks it for a request for a URL or a repository whose content goes to a command with `OutputVisibility.WHOLE` or `OutputVisibility.PARTIAL` at the end.
    On `True` the category is `OTHER_WEB`. On `False` it is the category that the request would get if its content were shown in the result.
    A use is such a request.

    Provisional. No earlier code chose, and other web claims no replacement.
    """
    use_counts[treat_content_piped_to_showing_command_as_other_web.__name__] += 1
    return True


def treat_shown_content_from_search_engine_host_as_other_web(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request whose content from a search engine host is shown in the result in the other web category, e.g. `curl 'https://html.duckduckgo.com/html?q=x'`.

    A command can ask a search engine for its search page or for any other page of it, and the words alone do not say which.
    `export_network_request_category` asks it for a request for a URL or a repository from a command or code whose content is shown, none of whose public hosts is code hosting and one of which the host catalog gives the service `SEARCH_ENGINE`.
    It is also asked for such a request whose content goes to a command that shows all or part of it, when `treat_content_piped_to_showing_command_as_other_web` answers `False`.
    On `True` the category is `OTHER_WEB`. On `False` it is `SEARCH`.
    A use is such a request.

    Provisional. No earlier code chose, and other web claims no replacement.
    """
    use_counts[treat_shown_content_from_search_engine_host_as_other_web.__name__] += 1
    return True


def treat_shown_content_from_registry_or_model_hub_host_as_other_web(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Put a request whose content from a package registry or model hub host is shown in the result in the other web category, e.g. `curl https://pypi.org/project/requests/`.

    Such a host serves both pages of documentation and data for programs, e.g. a JSON index, and the words do not say which was shown.
    `export_network_request_category` asks it for a request for a URL or a repository from a command or code whose content is shown, none of whose public hosts is code hosting or a search engine and one of which the host catalog gives the service `PACKAGE_REGISTRY` or `MODEL_HUB`.
    It is also asked for such a request whose content goes to a command that shows all or part of it, when `treat_content_piped_to_showing_command_as_other_web` answers `False`.
    On `True` the category is `OTHER_WEB`. On `False` it is `PAGE_READ`.
    A use is such a request.

    Provisional. No earlier code chose, and other web claims no replacement.
    """
    use_counts[
        treat_shown_content_from_registry_or_model_hub_host_as_other_web.__name__
    ] += 1
    return True


def treat_web_tool_request_without_host_name_as_internet_use(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Count a web tool request whose words name no host as internet use, e.g. a harness web search with only a query such as `how to x?`.

    A web search tool sends its query to a search service that the trajectory does not name, and a web fetch tool called without a URL names no host either, so the trajectory does not say where the request went.
    `export_network_request_row` asks it for each request without a host name whose source is a web tool.
    On `True` `is_internet_use` is True. On `False` it is None, so the request counts only toward the upper bound.
    A use is such a request.

    Provisional. No earlier code chose. A web tool is made to reach the internet, and the other choice would leave every web search unknown.
    """
    use_counts[treat_web_tool_request_without_host_name_as_internet_use.__name__] += 1
    return True


def treat_request_without_host_name_as_sent_to_default_registry_host(
    network_request: NetworkRequest,
    package_registry: PackageRegistry | UnknownPackageRegistry | None,
    *,
    use_counts: Counter[str],
) -> tuple[str, ...]:
    """Give the hosts that a request whose words name no host is taken to be sent to, i.e. the default registry hosts of its program and subcommand, e.g. `pypi.org` for `pip install requests`.

    A program that installs packages usually names no host, and whether the request went out at all is decided from its output lines when results are decided.
    `export_network_request_row` asks it for each request without a host name whose source is no web tool. It gives the hosts the same reading as hosts that the words name.
    `package_registry` is the answer of `ExportKnowledge.package_registry`, or None for a request that the door is not asked about, e.g. `git fetch origin`.
    It gives the host names of a `PackageRegistry`, e.g. `deb.debian.org archive.ubuntu.com` for `apt-get update`, also when a file names the targets, e.g. `pip install -r reqs.txt`.
    It gives no host for a target that is a local path, e.g. `pip install -e .`, since a local project may or may not ask a registry for what it depends on. It gives none either for `UnknownPackageRegistry` or None. Without a host the request's internet use is not known.
    The other choices are no host for every request, which leaves all of them unknown, or the registry hosts for a local path too.
    A use is such a request.

    Provisional. The user chose on 2026-11-18 to send a request of a program and subcommand with a registry row to the registry hosts. Leaving a local path and a request without a row unknown claims least.
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
    if isinstance(package_registry, PackageRegistry):
        return package_registry.host_names
    return ()


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


def treat_single_label_host_name_as_not_internet_use(
    network_request: NetworkRequest, *, use_counts: Counter[str]
) -> bool:
    """Count a request with a host name without a dot, and none public, templated or reserved, as no internet use, also when local host names sit beside it, e.g. `curl http://db:8000/x` or `socket.create_connection(("api", 8000))` in code.

    A name without a dot does not resolve on public DNS, only inside a container network or through `/etc/hosts`, so the request goes to a service inside the task environment, which turning the internet off would not block.
    `export_network_request_row` asks it for a request from a command or code with such a host name and no public, templated or reserved host, among the hosts that its words name or that it is taken to be sent to.
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
    """Leave the internet use of a request unknown when a host name of it is reserved for examples and tests and none is public or templated, e.g. `curl https://example.com/`.

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
