"""Decide what the facts of a request and the outside knowledge do not settle about its row, one named rule per situation, e.g. the category of `curl u | tar xz` or which parts of a URL in a row are hidden as credentials.

Each rule is a judgment, not a reading of the trajectory or a fact of a catalog, so it lives here where it can be found and changed.
For example, the URL `https://a.org/x?page=2&token=abc` shows no rule of which query values are secret, and only a rule says that `export_rows` hides them all.

Each rule adds one to `use_counts` under its own function name every time it decides something, so that audits can show how much of the output leans on each rule.
The counts are for tracking and never go into a row.

A rule is provisional until the user decides it. The last paragraph of each docstring marks it `Provisional.` or `Decided.`
"""

from collections import Counter

from tb_internet_use.network_request.model import NetworkRequest


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
    """Put a request whose content from a package registry host is saved in the fetched file category, e.g. `wget https://files.pythonhosted.org/.../x.whl`.

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
    """Put a request whose content goes to a command that shows none of it in the other web category, e.g. `curl u | tar xz` or `curl u | sh`.

    Such a command unpacks, runs or stores the content, much as saving it would, but the words do not say which.
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
    """Put a request whose content goes to a command that shows all or part of it in the other web category, e.g. `curl u | head`, `curl u | grep x` or `curl u | tee log`.

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
    """Put a request whose content from a search engine host is shown in the result in the other web category, e.g. `curl 'https://duckduckgo.com/html?q=x'`.

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
