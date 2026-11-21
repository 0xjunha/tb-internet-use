"""Export the category of one network request by what it tried to get, from the materials in the text that sent it and the services of its public hosts.

The category never reads the response or how a saved file was used later, so a command gets the same category whether it succeeded or failed.
For example, `curl -o page.html u` is a content fetch even when a later call only runs `cat page.html`.

A request gets its category from the first condition below that fits it.

- A target kind that is not known gives `UNKNOWN`.
- A package name gives `PACKAGE`.
- A search query gives `SEARCH`.
- A request that asks for no content gives `CONNECTIVITY_CHECK`, unless its target is a repository, which a judgment rule decides.
- A request whose content is thrown away is decided by a judgment rule.
- A request for a host alone that may receive content is decided by a judgment rule.
- A URL from a web tool gives `CONTENT_FETCH`.
- A repository gives `CONTENT_FETCH`, e.g. `git clone u`.
- A URL without a path or a query of a package registry or search engine host is decided by a judgment rule, e.g. `https://pypi.org` in code.
- A URL of a package registry host is decided by a judgment rule.
- A URL of a search engine host is decided by a judgment rule.
- A URL of a web API host gives `REMOTE_API_CALL`.
- A URL of a code hosting, model hub, file hosting or documentation host gives `CONTENT_FETCH`.
- A URL whose content is saved is decided by a judgment rule.
- Any other request gives `OTHER_WEB`, e.g. `curl https://a.org/x | mytool` or `requests.get("https://a.org/x")` in code.

The services of the hosts of a URL come before where its content goes, since the same URL may be saved in one call and piped in another, e.g. `curl -o x.pdb https://files.rcsb.org/download/1abc.pdb` and `curl https://files.rcsb.org/download/1abc.pdb | head`, while the host says what was asked for.
"""

from collections import Counter
from collections.abc import Sequence
from typing import assert_never

from tb_internet_use.export.judgment_rules import (
    treat_discarded_content_as_connectivity_check,
    treat_host_target_that_may_receive_content_as_other_web,
    treat_repository_request_for_no_content_as_other_web,
    treat_saved_content_from_unrecognized_url_as_content_fetch,
    treat_url_request_to_package_registry_host_as_package,
    treat_url_request_to_search_engine_host_as_search,
    treat_url_request_without_path_or_query_to_package_registry_or_search_engine_host_as_connectivity_check,
)
from tb_internet_use.export.model import (
    HostService,
    NetworkRequestCategory,
    PublicHost,
    UnknownPublicHost,
)
from tb_internet_use.export.parse_url_path import parse_url_path
from tb_internet_use.export.parse_url_query import parse_url_query
from tb_internet_use.network_request.model import (
    ContentDiscarded,
    ContentSaved,
    FromWebTool,
    NetworkRequest,
    NetworkRequestTargetKind,
    NoContentRequested,
    UnknownNetworkRequestTargetKind,
)

# The services of hosts that give a file or a page at a fixed address, e.g. `files.rcsb.org`, so that every URL of them is a content fetch.
_CONTENT_HOST_SERVICES = (
    HostService.CODE_HOSTING,
    HostService.MODEL_HUB,
    HostService.FILE_HOSTING,
    HostService.DOCUMENTATION,
)


def export_network_request_category(
    network_request: NetworkRequest,
    public_hosts: Sequence[PublicHost | UnknownPublicHost],
    *,
    judgment_rule_use_counts: Counter[str],
) -> NetworkRequestCategory:
    """Export the category of a request from the first condition of the module docstring that fits it, reading its target kind, its content destination, its source and the services of its hosts.

    `public_hosts` holds the answers of `ExportKnowledge` for the public hosts among `NetworkRequest.host_names`, where the host of a target URL is asked for the path of the URL.
    A target kind that is not known gives `UNKNOWN`, while a target that is not known does not, e.g. `pip install $PKG` is `PACKAGE`.
    A request that asks for no content is `CONNECTIVITY_CHECK` whatever its host, e.g. `ping pypi.org`, unless it is for a repository, which `treat_repository_request_for_no_content_as_other_web` decides.
    Each judgment rule adds one to `judgment_rule_use_counts` under its name when it decides a condition.
    """
    target_kind = network_request.target_kind
    received_content_destination = network_request.received_content_destination
    if isinstance(target_kind, UnknownNetworkRequestTargetKind):
        return NetworkRequestCategory.UNKNOWN
    if target_kind == NetworkRequestTargetKind.PACKAGE_NAME:
        return NetworkRequestCategory.PACKAGE
    if target_kind == NetworkRequestTargetKind.SEARCH_QUERY:
        return NetworkRequestCategory.SEARCH
    if isinstance(received_content_destination, NoContentRequested):
        if target_kind != NetworkRequestTargetKind.REPOSITORY_URL:
            return NetworkRequestCategory.CONNECTIVITY_CHECK
        if treat_repository_request_for_no_content_as_other_web(
            network_request, use_counts=judgment_rule_use_counts
        ):
            return NetworkRequestCategory.OTHER_WEB
        return NetworkRequestCategory.CONNECTIVITY_CHECK
    if isinstance(received_content_destination, ContentDiscarded):
        if treat_discarded_content_as_connectivity_check(
            network_request, use_counts=judgment_rule_use_counts
        ):
            return NetworkRequestCategory.CONNECTIVITY_CHECK
        return NetworkRequestCategory.OTHER_WEB
    if target_kind == NetworkRequestTargetKind.HOST:
        if treat_host_target_that_may_receive_content_as_other_web(
            network_request, use_counts=judgment_rule_use_counts
        ):
            return NetworkRequestCategory.OTHER_WEB
        return NetworkRequestCategory.CONNECTIVITY_CHECK
    # The conditions below are only for a URL or a repository, so a target kind added later fails here instead of taking them.
    if (
        target_kind != NetworkRequestTargetKind.URL
        and target_kind != NetworkRequestTargetKind.REPOSITORY_URL
    ):
        assert_never(target_kind)
    return _category_for_url_request(
        network_request,
        public_hosts,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )


def _category_for_url_request(
    network_request: NetworkRequest,
    public_hosts: Sequence[PublicHost | UnknownPublicHost],
    *,
    judgment_rule_use_counts: Counter[str],
) -> NetworkRequestCategory:
    """Give the category of a request for a URL or a repository that asks for content it does not throw away, by its source and target kind, then by the services of its hosts and last by whether its content is saved.

    A registry or search engine host is read beside the path and the query of the target URL, since a URL without either asks for neither a package nor a search, e.g. `requests.get("https://www.google.com")` in code that checks the network.
    """
    if isinstance(network_request.source, FromWebTool):
        return NetworkRequestCategory.CONTENT_FETCH
    if network_request.target_kind == NetworkRequestTargetKind.REPOSITORY_URL:
        return NetworkRequestCategory.CONTENT_FETCH
    if (
        (
            _has_host_service(public_hosts, HostService.PACKAGE_REGISTRY)
            or _has_host_service(public_hosts, HostService.SEARCH_ENGINE)
        )
        and _is_target_url_without_path_or_query(network_request)
        and treat_url_request_without_path_or_query_to_package_registry_or_search_engine_host_as_connectivity_check(
            network_request, use_counts=judgment_rule_use_counts
        )
    ):
        return NetworkRequestCategory.CONNECTIVITY_CHECK
    if _has_host_service(
        public_hosts, HostService.PACKAGE_REGISTRY
    ) and treat_url_request_to_package_registry_host_as_package(
        network_request, use_counts=judgment_rule_use_counts
    ):
        return NetworkRequestCategory.PACKAGE
    if _has_host_service(
        public_hosts, HostService.SEARCH_ENGINE
    ) and treat_url_request_to_search_engine_host_as_search(
        network_request, use_counts=judgment_rule_use_counts
    ):
        return NetworkRequestCategory.SEARCH
    if _has_host_service(public_hosts, HostService.WEB_API):
        return NetworkRequestCategory.REMOTE_API_CALL
    if any(
        _has_host_service(public_hosts, host_service)
        for host_service in _CONTENT_HOST_SERVICES
    ):
        return NetworkRequestCategory.CONTENT_FETCH
    if isinstance(
        network_request.received_content_destination, ContentSaved
    ) and treat_saved_content_from_unrecognized_url_as_content_fetch(
        network_request, use_counts=judgment_rule_use_counts
    ):
        return NetworkRequestCategory.CONTENT_FETCH
    # Neither a host nor saving the content says what was asked for, e.g. `curl https://a.org/x | mytool` or code.
    return NetworkRequestCategory.OTHER_WEB


def _is_target_url_without_path_or_query(network_request: NetworkRequest) -> bool:
    """Answer whether the target of a request is a URL whose path is `/` or empty and that has no query, e.g. `https://pypi.org` or `https://www.google.com/`, but not `https://duckduckgo.com/?q=x`.

    The path and the query are read for the host of the target URL among the host names of the request, so a target whose URL `parse_url_path` cannot read is not one, e.g. `git@github.com:a/b.git`.
    A request that names hosts beside its target URL, e.g. two URLs in the words of one call, is read by its target URL alone.
    """
    target = network_request.target
    if not isinstance(target, str):
        return False
    return any(
        parse_url_path(target, host_name) in ("", "/")
        and parse_url_query(target, host_name) == ""
        for host_name in network_request.host_names
    )


def _has_host_service(
    public_hosts: Sequence[PublicHost | UnknownPublicHost], host_service: HostService
) -> bool:
    """Answer whether the host catalog gives one of the public hosts the service, so that a host without a row gives none."""
    return any(
        isinstance(public_host, PublicHost) and public_host.service == host_service
        for public_host in public_hosts
    )
